import logging
import sys
import threading
import time
import uuid
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional, Callable, Any, Set, Tuple

from instrument_identity import bind_candles, canonical_symbol, option_contract, validate_signal_identity, check_chain_metadata
from config import BotConfig, ConfigValidationError, _parse_hhmm
from brokers import (BrokerIdentityError, identity_checked, validate_symbol_meta, BrokerDataError, CandleFreshnessError, UnsupportedBrokerCapabilityError,
                     MultiBrokerScanner, assess_live_candle_batch, candle_session_context)
from strategies import (
    IST,
    TradeSignal,
    compute_session_vwap,
    evaluate_order_block_fvg,
    evaluate_vwap_pullback,
    evaluate_option_apex_oi_shift,
    evaluate_orb_breakout,
    evaluate_supertrend_pullback,
    filter_completed_candles,
    format_ist_timestamp,
    parse_ist_timestamp,
    size_position,
    normalize_state_scope,
    validate_trade_signal,
    rank_signal_candidates,
)
from storage import (
    PersistenceError,
    PersistenceValidationError,
    SQLitePersistenceStore,
    is_closing_session_timestamp,
    is_nse_trading_day,
    resolve_effective_trading_session_date,
)
from telegram_bot import TelegramSignalDispatcher

logger = logging.getLogger("tradepulse.scanner")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def format_console_text(text: str, encoding: Optional[str] = None) -> str:
    """
    Formats console text safely for legacy Windows terminals (e.g., cp1252 or ascii)
    that cannot encode the Indian Rupee symbol ('₹' / U+20B9) or Unicode box characters,
    while preserving '₹' when the target encoding supports UTF-8.
    Does NOT strip currency information: replaces '₹' with 'INR ' when unencodable.
    """
    enc = (encoding or getattr(sys.stdout, "encoding", None) or "utf-8").strip()
    try:
        text.encode(enc)
        return text
    except (UnicodeEncodeError, LookupError):
        fallback = text.replace("₹", "INR ")
        try:
            return fallback.encode(enc, errors="replace").decode(enc, errors="replace")
        except LookupError:
            return fallback.encode("ascii", errors="replace").decode("ascii")


def safe_console_print(text: str, stream: Optional[Any] = None) -> str:
    """
    Prints `text` to `stream` (default `sys.stdout`) without crashing on Windows
    cp1252 / ASCII consoles. Returns the exact string written.
    """
    target = stream if stream is not None else sys.stdout
    enc = getattr(target, "encoding", None) or "utf-8"
    safe_str = format_console_text(str(text), encoding=enc)
    try:
        print(safe_str, file=target)
    except UnicodeEncodeError:
        ascii_str = format_console_text(str(text), encoding="ascii")
        print(ascii_str, file=target)
        return ascii_str
    return safe_str


class IntradayBotEngine:
    """
    Main Phase 1D / 2A / 2B Scanner Engine:
    - Scans NIFTY 50 & BANK NIFTY F&O across Option Apex OI Shift + Order Block + VWAP + ORB + Supertrend
    - Scans NSE Intraday Equity stocks across Order Block + VWAP + ORB + Supertrend
    - Evaluates both Bullish and Bearish setups symmetrically
    - Persists signals, scan-run metadata, OI snapshots, OI baselines, and mitigated Order Blocks to SQLite
    - Restores validated prior-session OI baselines into AngelOneSmartAPIAdapter on startup and before scans
    - Prevents overlapping concurrent scans via non-blocking lock (`SKIPPED_OVERLAP`)
    - Clearly distinguishes `COMPLETED` (with signals), `COMPLETED_EMPTY` (0 signals), and `FAILED` scans
    - Tracks live broker verification status and Option Apex readiness without claiming connectivity until verified
    - Never silently falls back from failed live broker data to simulated data
    """
    def __init__(
        self,
        config: Optional[BotConfig] = None,
        clock: Optional[Callable[[], datetime]] = None,
        broker_scanner: Optional[MultiBrokerScanner] = None,
        store: Optional[SQLitePersistenceStore] = None,
    ):
        self.config = config or BotConfig()
        self.clock = clock
        self.telegram = TelegramSignalDispatcher(self.config)
        self._scan_lock = threading.Lock()
        self._zone_states: Dict[Tuple[str, str, str], Set[str]] = {}

        # Operational state tracking
        self.last_broker_verified_at: Optional[str] = None
        self.last_broker_error: Optional[str] = None
        self.last_broker_error_category: str = "NONE"
        self.last_candle_timestamp_ist: Optional[str] = None
        self.last_candle_freshness: Optional[Dict[str, Any]] = None
        self._candle_evidence: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.last_persistence_status: str = "DISABLED"
        self.last_persistence_error: Optional[str] = None
        self.last_scan_summary: Optional[Dict[str, Any]] = None

        self.store: Optional[SQLitePersistenceStore] = store
        if self.store is None and self.config.enable_persistence:
            try:
                self.store = SQLitePersistenceStore(
                    self.config.database_url or "sqlite:///tradepulse_phase1d.db"
                )
                self.last_persistence_status = "OK"
            except Exception as exc:
                self.last_persistence_status = "ERROR"
                self.last_persistence_error = str(exc)
                logger.error("Failed to initialize persistence store: %s", exc)

        self.broker = broker_scanner or MultiBrokerScanner(
            self.config,
            clock=clock,
            persistence_store=self.store,
        )
        if hasattr(self.broker, "attach_persistence_store"):
            self.broker.attach_persistence_store(self.store)

        if self.store is not None:
            try:
                adapter = self.broker.get_active_adapter()
                provider, mode, _ = self._scanner_scope(adapter)
                for segment in ("NSE_FO_INDEX", "NSE_EQUITY_INTRADAY"):
                    self._load_zone_state(provider, mode, segment)
                self.last_persistence_status = "OK"
            except Exception as exc:
                self.last_persistence_status = "ERROR"
                self.last_persistence_error = str(exc)
                logger.error("Failed to load persisted mitigated Order Blocks: %s", exc)

    def _scanner_scope(self, adapter) -> Tuple[str, str, str]:
        return normalize_state_scope(self.config.active_broker,
                                     "SIMULATED" if adapter.is_simulated else "LIVE", "SCANNER")

    def _load_zone_state(self, provider: str, mode: str, segment: str) -> Set[str]:
        key = (provider, mode, segment)
        zones = self._zone_states.setdefault(key, set())
        if self.store is not None:
            zones.update(self.store.load_mitigated_order_blocks(
                provider=provider, data_mode=mode, state_context="SCANNER", segment=segment, interval_min=5))
        return zones

    @property
    def mitigated_order_blocks(self) -> Set[str]:
        """Read-only snapshot of the current scanner scope, for status/inspection."""
        with self._scan_lock:
            provider, mode, _ = self._scanner_scope(self.broker.get_active_adapter())
            return set().union(*(zones for (p, m, _), zones in self._zone_states.items()
                                 if (p, m) == (provider, mode)))

    def _assess_scan_candles(self, candles, symbol, provider, now_dt):
        normalized_ist = bool(candles) and all(
            isinstance(c, dict) and c.get("timestamp_timezone") == "Asia/Kolkata" for c in candles)
        normalized, report = assess_live_candle_batch(
            candles, 5, now_dt, self.config.configured_holidays,
            self.config.session_start_ist, self.config.session_end_ist,
            self.config.live_candle_max_delay_seconds, self.config.live_candle_future_skew_seconds,
            provider=provider, symbol=symbol, context="SCANNER", normalized_ist=normalized_ist)
        # The full batch was validated above. Retain only the last completed candle
        # and its unfinished tail for clock-based health/dispatch rechecks.
        latest_complete = max((i for i, c in enumerate(normalized) if c["is_complete"]), default=0)
        self._candle_evidence[(provider, symbol)] = {
            "report": report, "candles": normalized[latest_complete:] if report["live_signal_allowed"] else None}
        if not report["live_signal_allowed"]:
            raise CandleFreshnessError(report)
        return normalized

    def _freshness_status(self, provider, now_dt):
        items = {}
        for symbol in list(self.config.fo_indices) + [m["symbol"] for m in self.config.equity_watchlist]:
            entry = self._candle_evidence.get((provider, symbol), {})
            report = entry.get("report", dict(status="NOT_CHECKED", reason_code="NOT_CHECKED",
                                              is_fresh=False, live_signal_allowed=False,
                                              provider=provider, symbol=symbol, interval_min=5))
            if entry.get("candles"):
                _, report = assess_live_candle_batch(
                    entry["candles"], 5, now_dt, self.config.configured_holidays,
                    self.config.session_start_ist, self.config.session_end_ist,
                    self.config.live_candle_max_delay_seconds, self.config.live_candle_future_skew_seconds,
                    provider=provider, symbol=symbol, context="SCANNER", normalized_ist=True)
            items[symbol] = report
        allowed = bool(items) and all(r.get("live_signal_allowed", False) for r in items.values())
        return dict(provider=provider, context="SCANNER", interval_min=5,
                    status="FRESH_IN_SESSION" if allowed else "BLOCKED", is_fresh=allowed,
                    live_signal_allowed=allowed, evaluated_at_ist=format_ist_timestamp(now_dt), instruments=items)

    def _fetch_scan_candles(self, meta, provider):
        symbol = meta["symbol"]
        try:
            adapter = self.broker.get_active_adapter()
            validated = (adapter.resolve_instrument(meta) if provider == "angelone"
                         else validate_symbol_meta(meta, provider))
            if symbol != validated["symbol"]:
                raise BrokerIdentityError(dict(reason_code="NONCANONICAL_CONFIGURATION", reason="Configure canonical symbols; aliases are accepted at adapter lookup boundaries."))
            candles = self.broker.fetch_candles(meta, interval_min=5)
            candles = identity_checked(bind_candles, candles, validated["instrument_identity"])
            return self._assess_scan_candles(candles, symbol, provider, self._now_ist())
        except BrokerDataError as exc:
            report = getattr(exc, "freshness", dict(status=getattr(exc, "error_category", "PROVIDER_ERROR"),
                                                     reason_code=getattr(exc, "rejection", {}).get("reason_code", "PROVIDER_ERROR"),
                                                    reason=str(exc), provider=provider, symbol=symbol,
                                                    interval_min=5, is_fresh=False, live_signal_allowed=False))
            self._candle_evidence[(provider, symbol)] = {"report": report, "candles": None}
            raise

    def _require_current_scan_data(self, provider, now_dt=None):
        status = self._freshness_status(provider, now_dt if now_dt is not None else self._now_ist())
        if not status["live_signal_allowed"]:
            rejected = next(r for r in status["instruments"].values() if not r.get("live_signal_allowed"))
            raise CandleFreshnessError(rejected)

    def _now_ist(self) -> datetime:
        if self.clock is not None:
            return parse_ist_timestamp(self.clock())
        return datetime.now(IST)

    def close(self) -> None:
        """Closes the underlying SQLitePersistenceStore connection deterministically."""
        if self.store is not None:
            try:
                self.store.close()
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def get_broker_status(self) -> Dict[str, Any]:
        """
        Returns the honest operational status of the active broker adapter,
        Scrip Master loader, and Option Apex (Strategy 3) readiness:
        - 'SIMULATED': Explicit paper simulation mode (`paper_sim`).
        - 'UNAVAILABLE_MISSING_CREDENTIALS': Live broker selected, but credentials are missing or placeholders.
        - 'ERROR': Live broker selected and most recent request failed.
        - 'CONNECTED_VERIFIED': Live broker selected and connectivity was verified by a successful data fetch.
        - 'CONFIGURED_UNVERIFIED': Live broker credentials are present, but connectivity has not yet been verified.
        """
        try:
            adapter = self.broker.get_active_adapter()
        except BrokerDataError as exc:
            return {
                "active_broker": self.config.active_broker,
                "broker_name": "UNKNOWN",
                "connection_state": "INVALID_CONFIG",
                "is_simulated": False,
                "data_mode": "LIVE",
                "connectivity_verified": False,
                "last_verified_at_ist": None,
                "last_error": str(exc),
                "scrip_master": {"status": "INVALID_CONFIG", "last_error": str(exc)},
                "option_apex": {
                    "overall_status": "INVALID_CONFIG",
                    "usable": False,
                    "live_verified": False,
                    "data_mode": "LIVE",
                    "other_strategies_operational": False,
                    "indices": {},
                },
            }

        now_dt = self._now_ist()
        is_sim = bool(adapter.is_simulated)
        if is_sim:
            return {
                "active_broker": self.config.active_broker,
                "broker_name": adapter.name,
                "connection_state": "SIMULATED",
                "is_simulated": True,
                "data_mode": "SIMULATED",
                "auth_verified": False,
                "market_data_verified": False,
                "connectivity_verified": False,
                "last_verified_at_ist": None,
                "last_market_data_at_ist": self.last_candle_timestamp_ist,
                "last_candle_timestamp_ist": self.last_candle_timestamp_ist,
                "candle_freshness": {"status": "SIMULATED", "is_fresh": False, "live_signal_allowed": False},
                "live_signals_allowed": False,
                "error_category": "SIMULATED",
                "last_error_category": "SIMULATED",
                "last_error": None,
                "scrip_master": {
                    "status": "NOT_APPLICABLE",
                    "reason": "Simulated mode uses deterministic in-memory contract definitions.",
                },
                "option_apex": {
                    "overall_status": "SIMULATED_READY",
                    "usable": True,
                    "live_verified": False,
                    "data_mode": "SIMULATED",
                    "other_strategies_operational": True,
                    "scrip_master_status": "NOT_APPLICABLE",
                    "indices": {
                        "NIFTY": {
                            "status": "SIMULATED_READY",
                            "usable": True,
                            "oi_change_measure": "simulated_session_oi_change",
                            "reason": "Deterministic simulated option chain active.",
                        },
                        "BANKNIFTY": {
                            "status": "SIMULATED_READY",
                            "usable": True,
                            "oi_change_measure": "simulated_session_oi_change",
                            "reason": "Deterministic simulated option chain active.",
                        },
                    },
                },
            }

        creds_ok = self.config.is_broker_credentials_configured()
        adapter_err_msg = getattr(adapter, "last_error_message", None)
        adapter_err_cat = getattr(adapter, "last_error_category", "NONE")
        effective_err = self.last_broker_error or adapter_err_msg

        auth_verified = (bool(adapter.is_authentication_verified()) if hasattr(adapter, "is_authentication_verified")
                         else bool(getattr(adapter, "jwt_token", None) and getattr(adapter, "authenticated_at_ist", None)))
        market_data_ts = getattr(adapter, "last_market_data_at_ist", None) or self.last_broker_verified_at
        market_data_verified = bool(market_data_ts and not effective_err)

        if not creds_ok:
            state = "UNAVAILABLE_MISSING_CREDENTIALS"
            err_cat = "MISSING_CREDENTIALS"
        elif effective_err:
            state = "ERROR"
            if adapter_err_cat and adapter_err_cat != "NONE":
                err_cat = adapter_err_cat
            elif self.last_broker_error_category and self.last_broker_error_category != "NONE":
                err_cat = self.last_broker_error_category
            else:
                low_e = str(effective_err).lower()
                if any(k in low_e for k in ("login", "auth", "totp", "credential", "ab1000", "ab1007", "ab1050", "ag8004")):
                    err_cat = "AUTH_FAILURE"
                elif any(k in low_e for k in ("expired", "ag8001", "ag8002", "ab1010", "http 401")):
                    err_cat = "SESSION_EXPIRED"
                elif "stale" in low_e:
                    err_cat = "STALE_MARKET_DATA"
                elif "rate limit" in low_e or "429" in low_e:
                    err_cat = "RATE_LIMIT"
                else:
                    err_cat = "NETWORK_API_FAILURE"
        elif self.last_broker_verified_at or (hasattr(adapter, "is_connection_verified") and adapter.is_connection_verified()):
            state = "CONNECTED_VERIFIED"
            err_cat = "NONE"
        else:
            state = "CONFIGURED_UNVERIFIED"
            err_cat = "NONE"

        if hasattr(adapter, "get_scrip_master_status"):
            scrip_master_info = adapter.get_scrip_master_status(now_ist=now_dt)
        else:
            scrip_master_info = {
                "status": "NOT_APPLICABLE",
                "reason": f"{adapter.name} resolves option chains directly via single-call endpoints.",
            }

        if hasattr(adapter, "get_option_apex_readiness"):
            option_apex_info = adapter.get_option_apex_readiness(now_ist=now_dt)
            option_apex_info["live_verified"] = bool(state == "CONNECTED_VERIFIED" and option_apex_info.get("usable"))
            option_apex_info["broker_connection_state"] = state
            if state == "ERROR":
                option_apex_info["overall_status"] = "ERROR"
                option_apex_info["usable"] = False
                option_apex_info["last_broker_error"] = self.last_broker_error
        else:
            # DhanHQ / Upstox single-call option chain adapters
            if not creds_ok:
                oa_status = "UNAVAILABLE_MISSING_CREDENTIALS"
                oa_usable = False
            elif state == "ERROR":
                oa_status = "ERROR"
                oa_usable = False
            else:
                oa_status = "UNAVAILABLE_CONTRACT_IDENTITY"
                oa_usable = False
            option_apex_info = {
                "overall_status": oa_status,
                "usable": oa_usable,
                "live_verified": bool(state == "CONNECTED_VERIFIED" and oa_usable),
                "broker_connection_state": state,
                "data_mode": "LIVE",
                "other_strategies_operational": bool(creds_ok and state != "ERROR"),
                "scrip_master_status": "NOT_APPLICABLE",
                "indices": {
                    sym: {
                        "status": oa_status,
                        "usable": oa_usable,
                        "oi_change_measure": "net_change_from_previous_day_close",
                        "reason": f"{adapter.name} provides previous-session OI in single-call option chain.",
                    }
                    for sym in ("NIFTY", "BANKNIFTY")
                },
            }

        candle_fresh = self._freshness_status(str(self.config.active_broker).strip().lower(), now_dt)
        return {
            "active_broker": self.config.active_broker,
            "broker_name": adapter.name,
            "connection_state": state,
            "is_simulated": False,
            "data_mode": "LIVE",
            "auth_verified": auth_verified,
            "market_data_verified": market_data_verified,
            "connectivity_verified": state == "CONNECTED_VERIFIED",
            "last_verified_at_ist": self.last_broker_verified_at or (market_data_ts if state == "CONNECTED_VERIFIED" else None),
            "last_market_data_at_ist": market_data_ts,
            "last_candle_response_at_ist": getattr(adapter, "last_candle_response_at_ist", None),
            "last_quote_timestamp_ist": getattr(adapter, "last_quote_timestamp_ist", None),
            "last_candle_timestamp_ist": getattr(adapter, "last_candle_timestamp_ist", None) or self.last_candle_timestamp_ist,
            "candle_freshness": candle_fresh,
            "live_signals_allowed": bool(state == "CONNECTED_VERIFIED" and candle_fresh["live_signal_allowed"]),
            "error_category": err_cat,
            "last_error_category": err_cat,
            "last_error": effective_err,
            "scrip_master": scrip_master_info,
            "option_apex": option_apex_info,
        }

    @staticmethod
    def _compute_universe_breadth(
        candles_by_symbol: Dict[str, List[Dict[str, Any]]],
        now_val: Optional[Any] = None,
    ) -> Optional[Dict[str, int]]:
        advances = 0
        declines = 0
        for candles in candles_by_symbol.values():
            try:
                completed = filter_completed_candles(candles, interval_min=5, now=now_val)
                if not completed:
                    continue
                vwaps = compute_session_vwap(completed)
                last_close = float(completed[-1]["close"])
                curr_vwap = float(vwaps[-1])
                if last_close > curr_vwap * 1.0002:
                    advances += 1
                elif last_close < curr_vwap * 0.9998:
                    declines += 1
            except Exception:
                continue
        if advances + declines == 0:
            return None
        return {"advances": advances, "declines": declines}

    def _replay_cash_result(self, work, paper_coordinator=None):
        from candle_lineage import replay_summary
        summary = replay_summary(work)
        if paper_coordinator is not None:
            snapshot = work["snapshot"]
            observations = dict(snapshot["auxiliary"]["index_candles"])
            observations.update({b["content"]["identity"]["symbol"]: b["content"]["candles"]
                                 for b in snapshot["batches"]})
            try:
                summary["paper_portfolio"] = paper_coordinator.consume_scan(work["result"], observations)
            except Exception:
                summary["paper_portfolio"] = dict(status="UNAVAILABLE", execution_mode="SIMULATED",
                                                  reason_code="PAPER_CYCLE_REQUIRES_RECOVERY")
        self.last_scan_summary = summary
        return summary

    def resume_cash_scan(self, run_id, *, paper_portfolio=None):
        """Explicit OFFLINE recovery; no transport or notification delivery."""
        return self.run_single_scan(paper_portfolio=paper_portfolio, resume_run_id=run_id)

    def run_single_scan(self, *, paper_portfolio=None, resume_run_id=None) -> Dict[str, Any]:
        from candle_lineage import (runtime_profile, code_fingerprint, digest, make_snapshot,
                                    completed_cash_batch)
        recovery = None
        if resume_run_id is not None:
            if self.store is None or not self.config.telegram_dry_run or self.config.enable_background_scheduler:
                raise PersistenceValidationError("LINEAGE_SAFE_OFFLINE_RECOVERY_REQUIRED")
            recovery = self.store.load_cash_scan(resume_run_id)
            snapshot = recovery["snapshot"]
            if (digest(runtime_profile(self.config)) != snapshot["profile_digest"]
                    or code_fingerprint() != snapshot["code_digest"]):
                raise PersistenceValidationError("LINEAGE_RECOVERY_CONFIGURATION_OR_CODE_CHANGED")
            for batch, meta in zip(snapshot["batches"], self.config.equity_watchlist):
                completed_cash_batch(batch["content"]["candles"], meta, snapshot["profile"], snapshot["reference"])
        paper_coordinator = None
        if paper_portfolio is not None:
            from forward_paper import ForwardPaperCoordinator
            paper_coordinator = ForwardPaperCoordinator(paper_portfolio)
            if (paper_portfolio.store is not self.store or paper_portfolio.config.provider != self.config.active_broker
                    or not self.config.telegram_dry_run or self.config.enable_background_scheduler
                    or paper_portfolio.config.source_data_mode != ("SIMULATED" if self.broker.get_active_adapter().is_simulated else "LIVE")):
                raise ValueError("Explicit paper account/store/provider and safe runtime configuration must agree.")
        started_wall = time.perf_counter()
        recovery_clock = parse_ist_timestamp(recovery["snapshot"]["reference"]) if recovery else None
        scan_now = lambda: recovery_clock if recovery_clock is not None else self._now_ist()
        now_dt = scan_now()
        started_ist = format_ist_timestamp(now_dt)
        run_id = recovery["run_id"] if recovery else f"scan_{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        lineage_tx, durable_work = None, None
        result_committed = False
        is_simulated = None
        deferred_dispatches = []

        if not self._scan_lock.acquire(blocking=False):
            logger.warning("Scan %s skipped because another scan is already in progress.", run_id)
            overlap_summary = {
                "status": "skipped",
                "scan_status": "SKIPPED_OVERLAP",
                "reason": "scan_already_in_progress",
                "run_id": run_id,
                "started_at_ist": started_ist,
                "completed_at_ist": started_ist,
                "duration_ms": 0.0,
                "total_signals": 0,
                "signals": [],
                "telegram_dispatches": [],
            }
            if self.store is not None and recovery is None:
                try:
                    adapter = self.broker.get_active_adapter()
                    self.store.record_scan_run(
                        run_id=run_id,
                        started_at_ist=started_ist,
                        completed_at_ist=started_ist,
                        duration_ms=0.0,
                        status="SKIPPED_OVERLAP",
                        broker=adapter.name,
                        data_mode="SIMULATED" if adapter.is_simulated else "LIVE",
                        is_simulated=bool(adapter.is_simulated),
                    )
                except Exception as db_exc:
                    logger.error("Failed to record SKIPPED_OVERLAP scan run: %s", db_exc)
            return overlap_summary

        try:
            persisted_signals_count = 0
            self.config.validate(require_live_credentials=False)
            if hasattr(self.broker, "attach_persistence_store"):
                self.broker.attach_persistence_store(self.store)
            adapter = self.broker.get_active_adapter()
            if hasattr(adapter, "attach_persistence_store"):
                adapter.attach_persistence_store(self.store)

            broker_label = adapter.name
            is_simulated = bool(adapter.is_simulated)
            data_mode = "SIMULATED" if is_simulated else "LIVE"
            provider, data_mode, state_context = self._scanner_scope(adapter)
            if recovery is not None and recovery["status"] == "COMMITTED":
                return self._replay_cash_result(recovery, paper_coordinator)
            if not is_simulated and self.config.enable_persistence and self.store is None:
                raise PersistenceError("Required scanner storage is unavailable; no acquisition attempted.")
            if not is_simulated:
                _, _, _, session_state, _ = candle_session_context(
                    now_dt, self.config.configured_holidays, self.config.session_start_ist, self.config.session_end_ist)
                if session_state != "within_session":
                    summary = dict(status="skipped", scan_status="SKIPPED_OUTSIDE_SESSION", reason=session_state,
                                   data_mode="LIVE", is_simulated=False, run_id=run_id, total_signals=0,
                                   signals=[], telegram_dispatches=[], candle_freshness=self._freshness_status(provider, now_dt))
                    self.last_scan_summary = summary
                    return summary
                # Invalidate prior scan coverage; a failed instrument cannot leave peers verified.
                for symbol in list(self.config.fo_indices) + [m["symbol"] for m in self.config.equity_watchlist]:
                    self._candle_evidence.pop((provider, symbol), None)
            zone_states = {}
            for segment in ("NSE_FO_INDEX", "NSE_EQUITY_INTRADAY"):
                loaded = self._load_zone_state(provider, data_mode, segment)
                zone_states[segment] = loaded if is_simulated else set(loaded)
            now_val = now_dt if recovery else (self.clock() if self.clock is not None else None)

            logger.info("Starting scan %s via %s (mode=%s)", run_id, broker_label, data_mode)

            signals: List[TradeSignal] = []
            telegram_dispatches: List[Dict[str, Any]] = []
            instrument_errors: List[Dict[str, str]] = []
            oi_snapshots_saved = 0
            persistence_status = "OK" if self.store is not None else ("ERROR" if self.config.enable_persistence else "DISABLED")
            persistence_error: Optional[str] = self.last_persistence_error if persistence_status == "ERROR" else None

            try:
                index_candles_map: Dict[str, List[Dict[str, Any]]] = {}
                index_oc_map: Dict[str, Optional[Dict[str, Any]]] = {}
                for idx_sym, idx_meta in self.config.fo_indices.items():
                    meta_with_sym = dict(idx_meta, symbol=idx_sym)
                    index_candles_map[idx_sym] = (recovery["snapshot"]["auxiliary"]["index_candles"][idx_sym] if recovery else
                        self.broker.fetch_candles(meta_with_sym, interval_min=5) if is_simulated
                        else self._fetch_scan_candles(meta_with_sym, provider))
                    if recovery:
                        index_candles_map[idx_sym] = self._assess_scan_candles(index_candles_map[idx_sym], idx_sym, provider, now_dt)
                    try:
                        index_oc_map[idx_sym] = (recovery["snapshot"]["auxiliary"]["option_chains"][idx_sym]
                                                if recovery else self.broker.fetch_option_chain(idx_sym))
                        if not is_simulated and index_oc_map[idx_sym]:
                            oc = index_oc_map[idx_sym]
                            requested = index_candles_map[idx_sym][-1]["instrument_identity"]
                            identity_checked(check_chain_metadata, oc, idx_sym, oc.get("expiry"), provider, requested["identifier"])
                            if not oc.get("expiry") or oc["expiry"] < now_dt.date().isoformat():
                                raise BrokerIdentityError(dict(reason_code="EXPIRED_CONTRACT", reason="Chain expiry is missing or expired."))
                            if provider == "angelone":
                                seen_strikes = set()
                                for row in oc.get("strikes", []):
                                    if row["strike"] in seen_strikes:
                                        raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Duplicate option-chain strike."))
                                    seen_strikes.add(row["strike"])
                                    for side in ("CE", "PE"):
                                        contract = identity_checked(option_contract, row.get(side.lower()+"_contract", {}),
                                            idx_sym, oc["expiry"], row["strike"], side, provider, now_dt)
                                        trusted = adapter._quote_identity("NFO", contract["identifier"])
                                        if contract != trusted or contract["lot_size"] != idx_meta["lot_size"]:
                                            raise BrokerIdentityError(dict(reason_code="CONTRACT_IDENTITY_MISMATCH", reason="Chain contract conflicts with loaded master or configured lot."))
                    except UnsupportedBrokerCapabilityError as cap_exc:
                        logger.info(
                            "Option chain capability unavailable on %s for %s: %s",
                            broker_label,
                            idx_sym,
                            cap_exc,
                        )
                        index_oc_map[idx_sym] = None
                        instrument_errors.append({
                            "symbol": idx_sym,
                            "strategy": "strat_3_option_apex_oi",
                            "error_type": "UnsupportedBrokerCapabilityError",
                            "error": str(cap_exc),
                        })

                if not is_simulated:
                    symbols = [identity_checked(canonical_symbol, m["symbol"]) for m in self.config.equity_watchlist]
                    if len(symbols) != len(set(symbols)) or any(s in self.config.fo_indices for s in symbols):
                        raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Configured universe contains duplicate or conflicting instruments."))
                equity_candles_map: Dict[str, List[Dict[str, Any]]] = {}
                for eq_meta in self.config.equity_watchlist:
                    sym = eq_meta["symbol"]
                    if recovery:
                        bars = next(b["content"]["candles"] for b in recovery["snapshot"]["batches"]
                                    if b["content"]["identity"]["symbol"] == sym)
                        equity_candles_map[sym] = self._assess_scan_candles(bars, sym, provider, now_dt)
                    else:
                        equity_candles_map[sym] = (self.broker.fetch_candles(eq_meta, interval_min=5) if is_simulated
                                                  else self._fetch_scan_candles(eq_meta, provider))

                # Record latest candle timestamp from retrieved index/equity candles
                if not is_simulated:
                    self._require_current_scan_data(provider, now_dt=scan_now())
                    now_val = scan_now()
                sample_candles = index_candles_map.get("NIFTY") or next(iter(equity_candles_map.values()), [])
                if sample_candles:
                    self.last_candle_timestamp_ist = format_ist_timestamp(sample_candles[-1]["timestamp"])
                if not is_simulated and not recovery:
                    self.last_broker_verified_at = format_ist_timestamp(scan_now())
                    self.last_broker_error = None
                    self.last_broker_error_category = "NONE"
            except BrokerDataError as exc:
                if isinstance(exc, (CandleFreshnessError, BrokerIdentityError)):
                    raise
                self.last_broker_error = str(exc)
                self.last_broker_error_category = getattr(exc, "error_category", None) or getattr(adapter, "last_error_category", "NETWORK_API_FAILURE")
                duration_ms = round((time.perf_counter() - started_wall) * 1000.0, 2)
                completed_ist = format_ist_timestamp(scan_now())
                self.last_candle_freshness = self._freshness_status(provider, scan_now())
                self.last_scan_summary = dict(
                    status="error", scan_status="FAILED", run_id=run_id,
                    started_at_ist=started_ist, completed_at_ist=completed_ist, duration_ms=duration_ms,
                    broker=broker_label, data_mode=data_mode, is_simulated=is_simulated,
                    total_signals=0, persisted_signals=0, duplicate_signals=0, oi_snapshots_saved=0,
                    signals=[], telegram_dispatches=[], candle_freshness=self.last_candle_freshness,
                    error_type=type(exc).__name__, error_category=self.last_broker_error_category,
                    persistence_status="NOT_ATTEMPTED" if self.store is not None else "DISABLED")
                logger.error("Scan %s failed due to BrokerDataError: %s", run_id, exc)
                if self.store is not None:
                    try:
                        self.store.record_scan_run(
                            run_id=run_id,
                            started_at_ist=started_ist,
                            completed_at_ist=completed_ist,
                            duration_ms=duration_ms,
                            status="FAILED",
                            broker=broker_label,
                            data_mode=data_mode,
                            is_simulated=is_simulated,
                            error_type="BrokerDataError",
                            error_message=str(exc),
                        )
                        self.last_scan_summary["persistence_status"] = "OK"
                    except Exception as db_exc:
                        self.last_scan_summary["persistence_status"] = "ERROR"
                        logger.error("Failed to record FAILED scan run %s: %s", run_id, db_exc)
                raise

            if not is_simulated and self.store is not None and equity_candles_map:
                if recovery:
                    durable_work = recovery
                else:
                    snapshot = make_snapshot(self.config, equity_candles_map, index_candles_map,
                                             index_oc_map, zone_states, scan_now())
                    snapshot["acquisition_errors"] = instrument_errors[:]
                    durable_work = self.store.prepare_cash_scan(run_id, snapshot)
                requested_run_id = run_id
                run_id = durable_work["run_id"]
                lineage_tx = self.store.scan_result_transaction()
                lineage_tx.__enter__()
                durable_work = self.store.load_cash_scan(run_id)
                if durable_work["status"] == "COMMITTED":
                    transaction, lineage_tx = lineage_tx, None
                    transaction.__exit__(None, None, None)
                    return self._replay_cash_result(durable_work, paper_coordinator)
                retained = durable_work["snapshot"]
                # Retry always evaluates the first accepted input/zone state at its original reference.
                if recovery or run_id != requested_run_id:
                    recovery_clock = parse_ist_timestamp(retained["reference"])
                now_dt, now_val = parse_ist_timestamp(retained["reference"]), parse_ist_timestamp(retained["reference"])
                started_ist = format_ist_timestamp(now_dt)
                zone_states = {key: set(value) for key, value in retained["zones"].items()}
                equity_candles_map = {b["content"]["identity"]["symbol"]: b["content"]["candles"] for b in retained["batches"]}
                index_candles_map = retained["auxiliary"]["index_candles"]
                index_oc_map = retained["auxiliary"]["option_chains"]
                instrument_errors = retained.get("acquisition_errors", [])[:]
            all_candles_map = dict(index_candles_map, **equity_candles_map)
            market_breadth = self._compute_universe_breadth(all_candles_map, now_val=now_val)

            # 1. Persist OI snapshots & Evaluate F&O Indices (Strictly NIFTY 50 and BANK NIFTY)
            for idx_sym, idx_meta in self.config.fo_indices.items():
                candles = index_candles_map[idx_sym]
                oc = index_oc_map[idx_sym]

                completed_idx = filter_completed_candles(candles, interval_min=5, now=now_val)
                snap_ts = completed_idx[-1]["timestamp"] if completed_idx else started_ist

                if self.store is not None and oc:
                    try:
                        snap_res = self.store.save_oi_snapshot(
                            option_chain=oc,
                            snapshot_timestamp=snap_ts,
                            broker=broker_label,
                            scan_run_id=run_id,
                            now_ist=now_dt,
                        )
                        if snap_res.get("inserted"):
                            oi_snapshots_saved += 1
                    except Exception as db_exc:
                        persistence_status = "ERROR"
                        persistence_error = str(db_exc)
                        self.last_persistence_status = "ERROR"
                        self.last_persistence_error = str(db_exc)
                        logger.error("OI snapshot persistence failed for %s: %s", idx_sym, db_exc)

                    # Also record current-session OI observations into `oi_baselines` (strictly isolated by data_mode)
                    try:
                        snap_dt_parsed = parse_ist_timestamp(snap_ts)
                        sess_date_str = snap_dt_parsed.strftime("%Y-%m-%d")
                        exp_str = str(oc.get("expiry") or "")
                        if (
                            exp_str
                            and exp_str >= sess_date_str
                            and is_nse_trading_day(snap_dt_parsed.date(), self.config.configured_holidays)
                        ):
                            strike_oi_map = {
                                int(s["strike"]): {
                                    "ce_oi": int(s["ce_oi"]),
                                    "pe_oi": int(s["pe_oi"]),
                                }
                                for s in (oc.get("strikes") or [])
                                if "strike" in s and "ce_oi" in s and "pe_oi" in s
                            }
                            if strike_oi_map:
                                is_closing_obs = is_closing_session_timestamp(snap_dt_parsed)
                                if is_simulated:
                                    src_label = "simulated_option_chain" if is_closing_obs else "simulated_intraday_observation"
                                else:
                                    src_label = (
                                        f"{self.config.active_broker}_option_chain"
                                        if is_closing_obs
                                        else f"{self.config.active_broker}_intraday_observation"
                                    )
                                b_kind = "CLOSING_BASELINE" if is_closing_obs else "INTRADAY_OBSERVATION"
                                self.store.save_paired_strike_baselines(
                                    index_symbol=idx_sym,
                                    expiry=exp_str,
                                    baseline_by_strike=strike_oi_map,
                                    session_date=sess_date_str,
                                    observation_timestamp=format_ist_timestamp(snap_dt_parsed),
                                    source=src_label,
                                    data_mode=data_mode,
                                    now_ist=now_dt,
                                    configured_holidays=self.config.configured_holidays,
                                    allow_newer_intraday_update=True,
                                    baseline_kind=b_kind,
                                    auto_classify_by_timestamp=True,
                                )
                    except Exception as base_exc:
                        logger.debug("Non-fatal baseline observation update skipped for %s: %s", idx_sym, base_exc)

                if oc is not None and not is_simulated and provider != "angelone":
                    instrument_errors.append(dict(symbol=idx_sym, strategy="strat_3_option_apex_oi",
                        reason_code="UNSUPPORTED_CONTRACT", error="Provider has no supported option-master/lot resolver; chain is analytical only."))
                if oc is not None and (is_simulated or provider == "angelone"):
                    try:
                        sig_oi = evaluate_option_apex_oi_shift(
                            index_symbol=idx_sym,
                            candles=candles,
                            option_chain=oc,
                            lot_size=idx_meta["lot_size"],
                            capital_inr=self.config.account_capital_inr,
                            risk_pct=self.config.max_risk_per_trade_pct,
                            now=now_val,
                            market_breadth=market_breadth,
                        )
                        if sig_oi:
                            sig_oi.is_simulated = is_simulated
                            sig_oi.data_mode = data_mode
                            if not is_simulated:
                                side = "CE" if sig_oi.position_type == "LONG_CALL_OPTION" else "PE"
                                leg = next((r for r in oc["strikes"] if r["strike"] == oc["atm_strike"]), {})
                                contract = identity_checked(option_contract, leg.get(side.lower()+"_contract", {}),
                                                            idx_sym, oc["expiry"], oc["atm_strike"], side, provider, now_dt)
                                if contract["lot_size"] != idx_meta["lot_size"]:
                                    raise BrokerIdentityError(dict(reason_code="CONTRACT_LOT_MISMATCH", reason="Configured lot disagrees with selected option contract."))
                                label_prefix = f"{idx_sym} {oc['atm_strike']} {side}"
                                if (sig_oi.symbol != idx_sym or sig_oi.segment != "NSE_FO_INDEX"
                                        or not (sig_oi.instrument_label == label_prefix or sig_oi.instrument_label.startswith(label_prefix + " ("))):
                                    raise BrokerIdentityError(dict(reason_code="CONTRACT_IDENTITY_MISMATCH", reason="Evaluator option identity conflicts with selected contract."))
                                sig_oi.instrument_identity = contract
                                sig_oi.instrument_label = contract["symbol"]
                            signals.append(sig_oi)
                    except Exception as eval_exc:
                        logger.error("Option Apex evaluation error on %s: %s", idx_sym, eval_exc)
                        instrument_errors.append({"symbol": idx_sym, "strategy": "strat_3_option_apex_oi", "error": str(eval_exc),
                                                  "identity_rejection": getattr(eval_exc, "rejection", None)})

                if not is_simulated:
                    instrument_errors.append(dict(symbol=idx_sym, reason_code="UNSUPPORTED_CONTRACT",
                                                  error="Live futures require an explicit futures master and contract candles."))
                    continue
                try:
                    s_ob = evaluate_order_block_fvg(
                        symbol=idx_sym,
                        candles=candles,
                        capital_inr=self.config.account_capital_inr,
                        risk_pct=self.config.max_risk_per_trade_pct,
                        segment="NSE_FO_INDEX",
                        now=now_val,
                        market_breadth=market_breadth,
                        mitigated_zones=zone_states["NSE_FO_INDEX"],
                        lot_size=idx_meta["lot_size"],
                    )
                    if s_ob:
                        s_ob.is_simulated = is_simulated
                        s_ob.data_mode = data_mode
                        signals.append(s_ob)
                except Exception as eval_exc:
                    logger.error("Order Block evaluation error on %s: %s", idx_sym, eval_exc)
                    instrument_errors.append({"symbol": idx_sym, "strategy": "strat_1_order_block", "error": str(eval_exc)})

                for eval_fn in (
                    evaluate_vwap_pullback,
                    evaluate_orb_breakout,
                    evaluate_supertrend_pullback,
                ):
                    try:
                        s = eval_fn(
                            symbol=idx_sym,
                            candles=candles,
                            capital_inr=self.config.account_capital_inr,
                            risk_pct=self.config.max_risk_per_trade_pct,
                            segment="NSE_FO_INDEX",
                            lot_size=idx_meta["lot_size"],
                            now=now_val,
                            market_breadth=market_breadth,
                        )
                        if s:
                            s.is_simulated = is_simulated
                            s.data_mode = data_mode
                            signals.append(s)
                    except Exception as eval_exc:
                        logger.error("Strategy %s error on %s: %s", eval_fn.__name__, idx_sym, eval_exc)
                        instrument_errors.append({"symbol": idx_sym, "strategy": eval_fn.__name__, "error": str(eval_exc)})

            # 2. Evaluate Intraday Equity Watchlist
            for eq_meta in self.config.equity_watchlist:
                sym = eq_meta["symbol"]
                candles = equity_candles_map[sym]

                try:
                    s_ob = evaluate_order_block_fvg(
                        symbol=sym,
                        candles=candles,
                        capital_inr=self.config.account_capital_inr,
                        risk_pct=self.config.max_risk_per_trade_pct,
                        segment="NSE_EQUITY_INTRADAY",
                        now=now_val,
                        market_breadth=market_breadth,
                        mitigated_zones=zone_states["NSE_EQUITY_INTRADAY"],
                    )
                    if s_ob:
                        s_ob.is_simulated = is_simulated
                        s_ob.data_mode = data_mode
                        signals.append(s_ob)
                except Exception as eval_exc:
                    logger.error("Order Block evaluation error on %s: %s", sym, eval_exc)
                    instrument_errors.append({"symbol": sym, "strategy": "strat_1_order_block", "error": str(eval_exc)})

                for eval_fn in (
                    evaluate_vwap_pullback,
                    evaluate_orb_breakout,
                    evaluate_supertrend_pullback,
                ):
                    try:
                        s = eval_fn(
                            symbol=sym,
                            candles=candles,
                            capital_inr=self.config.account_capital_inr,
                            risk_pct=self.config.max_risk_per_trade_pct,
                            segment="NSE_EQUITY_INTRADAY",
                            now=now_val,
                            market_breadth=market_breadth,
                        )
                        if s:
                            s.is_simulated = is_simulated
                            s.data_mode = data_mode
                            signals.append(s)
                    except Exception as eval_exc:
                        logger.error("Strategy %s error on %s: %s", eval_fn.__name__, sym, eval_exc)
                        instrument_errors.append({"symbol": sym, "strategy": eval_fn.__name__, "error": str(eval_exc)})

            # Recompute quantities at the scanner boundary; evaluator-supplied quantities
            # cannot override account risk, whole-lot rules or capital requirements.
            sized_signals = []
            for sig in signals:
                is_option = sig.position_type in ("LONG_CALL_OPTION", "LONG_PUT_OPTION")
                instrument_type = "OPTIDX" if is_option else "FUTIDX" if sig.segment == "NSE_FO_INDEX" else "EQ"
                lot = self.config.fo_indices.get(sig.symbol, {}).get("lot_size") if instrument_type != "EQ" else 1
                side = "LONG" if is_option or "BULLISH" in sig.direction else "SHORT"
                sizing = size_position(sig.entry_price, sig.stop_loss, self.config.account_capital_inr,
                                       self.config.max_risk_per_trade_pct, side,
                                       instrument_type=instrument_type, lot_size=lot)
                if not sizing["eligible"]:
                    instrument_errors.append({"symbol": sig.symbol, "strategy": sig.strategy_id,
                                              "error": sizing["reason_code"]})
                    continue
                sig.position_qty = sizing["quantity"]
                sig.capital_risk_inr = sizing["estimated_risk_inr"]
                sig.est_charges_inr = sizing["estimated_charges_inr"]
                try:
                    validate_trade_signal(sig)
                except ValueError:
                    instrument_errors.append(dict(symbol=sig.symbol, strategy=sig.strategy_id,
                        reason_code="INVALID_SIGNAL_LEVELS", error="Candidate levels or metadata failed validation."))
                    continue
                sized_signals.append(sig)
            signals = rank_signal_candidates(sized_signals)

            # 3. Persist Signals, Deduplicate & Dispatch New Signals to Telegram
            persisted_signals_count = 0
            duplicate_signals_count = 0

            for sig in signals:
                if not is_simulated:
                    self._require_current_scan_data(provider, now_dt=scan_now())
                sig.provider = provider
                sig.state_context = state_context
                sig.interval_min = 5
                if not is_simulated:
                    if sig.segment == "NSE_EQUITY_INTRADAY":
                        sig.instrument_identity = dict(equity_candles_map[sig.symbol][-1]["instrument_identity"])
                    identity_checked(validate_signal_identity, sig.to_dict())
                is_duplicate_in_db = False
                if self.store is not None:
                    try:
                        was_inserted, _ = self.store.save_signal(
                            sig,
                            broker=broker_label,
                            scan_run_id=run_id,
                            now_ist=now_dt,
                        )
                        if durable_work:
                            self.store._lineage_checkpoint("after_signal_write")
                        if was_inserted:
                            persisted_signals_count += 1
                        else:
                            duplicate_signals_count += 1
                            is_duplicate_in_db = True
                    except Exception as db_exc:
                        persistence_status = "ERROR"
                        persistence_error = str(db_exc)
                        self.last_persistence_status = "ERROR"
                        self.last_persistence_error = str(db_exc)
                        logger.error("Signal persistence failed for %s: %s", sig.symbol, db_exc)

                if (self.config.enable_persistence or self.store is not None) and persistence_status != "OK":
                    # An unaudited recommendation must not escape after a required
                    # store fails. Keep the candidate visible with explicit failure.
                    telegram_dispatches.append({
                        "ok": False,
                        "skipped": True,
                        "reason": "persistence_unavailable",
                        "symbol": sig.symbol,
                        "strategy_id": sig.strategy_id,
                    })
                elif is_duplicate_in_db:
                    telegram_dispatches.append({
                        "ok": True,
                        "skipped": True,
                        "reason": "duplicate_in_persistence_store",
                        "symbol": sig.symbol,
                        "strategy_id": sig.strategy_id,
                    })
                elif durable_work:
                    deferred_dispatches.append((len(telegram_dispatches), sig))
                    telegram_dispatches.append(dict(ok=False, skipped=True, reason="delivery_not_recorded"))
                else:
                    if not is_simulated:
                        self._require_current_scan_data(provider, now_dt=scan_now())
                    res = self.telegram.send_signal(sig, broker_name=broker_label)
                    telegram_dispatches.append(res)

            if not is_simulated:
                self._require_current_scan_data(provider, now_dt=scan_now())
            if self.store is not None:
                try:
                    for segment, zones in zone_states.items():
                        self.store.save_mitigated_order_blocks(
                            zones, provider=provider, data_mode=data_mode, state_context=state_context,
                            segment=segment, interval_min=5, now_ist=now_dt,
                        )
                        if durable_work:
                            self.store._lineage_checkpoint("after_zone_write")
                except Exception as db_exc:
                    persistence_status = "ERROR"
                    persistence_error = str(db_exc)
                    self.last_persistence_status = "ERROR"
                    self.last_persistence_error = str(db_exc)
                    logger.error("Mitigated Order Block persistence failed: %s", db_exc)
            if not durable_work:
                for segment, zones in zone_states.items():
                    self._zone_states[(provider, data_mode, segment)].update(zones)

            duration_ms = round((time.perf_counter() - started_wall) * 1000.0, 2)
            completed_ist = format_ist_timestamp(scan_now())
            scan_status = "COMPLETED" if len(signals) > 0 else "COMPLETED_EMPTY"

            if self.store is not None:
                try:
                    self.store.record_scan_run(
                        run_id=run_id,
                        started_at_ist=started_ist,
                        completed_at_ist=completed_ist,
                        duration_ms=duration_ms,
                        status=scan_status,
                        broker=broker_label,
                        data_mode=data_mode,
                        is_simulated=is_simulated,
                        total_signals=len(signals),
                        persisted_signals=persisted_signals_count,
                        duplicate_signals=duplicate_signals_count,
                        oi_snapshots_saved=oi_snapshots_saved,
                        market_breadth=market_breadth,
                        error_type="PersistenceError" if persistence_status == "ERROR" else None,
                        error_message=persistence_error,
                    )
                    if durable_work:
                        self.store._lineage_checkpoint("after_scan_result_write")
                    if persistence_status != "ERROR":
                        self.last_persistence_status = "OK"
                        self.last_persistence_error = None
                except Exception as db_exc:
                    persistence_status = "ERROR"
                    persistence_error = str(db_exc)
                    self.last_persistence_status = "ERROR"
                    self.last_persistence_error = str(db_exc)
                    logger.error("Scan-run metadata persistence failed for %s: %s", run_id, db_exc)

            logger.info(
                "%s scan %s in %.2fms: status=%s, signals=%d, persisted=%d, duplicates=%d, persistence=%s",
                "Staged" if durable_work else "Completed",
                run_id,
                duration_ms,
                scan_status,
                len(signals),
                persisted_signals_count,
                duplicate_signals_count,
                persistence_status,
            )

            summary = {
                "status": "ok",
                "scan_status": scan_status,
                "run_id": run_id,
                "started_at_ist": started_ist,
                "completed_at_ist": completed_ist,
                "duration_ms": duration_ms,
                "broker": broker_label,
                "is_simulated": is_simulated,
                "data_mode": data_mode,
                "market_breadth": market_breadth,
                "total_signals": len(signals),
                "ranking_policy": "QUALITY_THEN_TARGET1_REWARD_RISK_THEN_IDENTITY_V1",
                "ranking_scope": "CANDIDATE_PRIORITY_ONLY_NO_CAPITAL_ALLOCATION",
                "empty_reason": (None if signals else "NO_ELIGIBLE_SETUP_FOR_ACCEPTED_INPUT"),
                "persisted_signals": persisted_signals_count,
                "duplicate_signals": duplicate_signals_count,
                "oi_snapshots_saved": oi_snapshots_saved,
                "persistence_status": persistence_status,
                "persistence_error": persistence_error,
                "instrument_errors": instrument_errors,
                "signals": [s.to_dict() for s in signals],
                "telegram_dispatches": telegram_dispatches,
                "candle_freshness": ({"status": "SIMULATED", "live_signal_allowed": False} if is_simulated
                                     else self._freshness_status(provider, scan_now())),
            }
            if durable_work:
                if persistence_status != "OK":
                    raise PersistenceError("LINEAGE_SCAN_RESULT_ROLLED_BACK")
                summary["input_lineage"] = dict(version="cash-lineage-v1", run_id=run_id,
                    batch_ids=[b["batch_id"] for b in durable_work["snapshot"]["batches"]],
                    work_id=durable_work["snapshot"]["work_id"], reference=durable_work["snapshot"]["reference"],
                    source_authenticity="NOT_ESTABLISHED", recovery_mode=bool(recovery or recovery_clock))
                if recovery or recovery_clock:
                    summary["candle_freshness"] = dict(status="RECOVERED_ACCEPTED_INPUT", live_signal_allowed=False)
                summary["notification_intents"] = [self.store.enqueue_notification_preview(
                    run_id, sig, self.telegram, broker_label, summary["input_lineage"]["batch_ids"], now_dt)
                    for _, sig in deferred_dispatches]
                self.store.finish_cash_scan(run_id, summary)
                transaction, lineage_tx = lineage_tx, None
                transaction.__exit__(None, None, None)
                result_committed = True
                logger.info("Committed scan %s with exact cash input linkage", run_id)
                self.store._lineage_checkpoint("after_result_commit")
                for segment, zones in zone_states.items():
                    self._zone_states[(provider, data_mode, segment)].update(zones)
                for ordinal, (index, sig) in enumerate(deferred_dispatches):
                    if recovery or recovery_clock or not self._freshness_status(provider, scan_now())["live_signal_allowed"]:
                        summary["telegram_dispatches"][index] = dict(ok=False, skipped=True, reason="recovery_or_stale_delivery_suppressed")
                    else:
                        try:
                            if not self.config.telegram_dry_run:
                                summary["telegram_dispatches"][index] = dict(ok=False, skipped=True, reason="durable_live_delivery_not_authorized")
                            else:
                                summary["telegram_dispatches"][index] = self.store.preview_notification(
                                    summary["notification_intents"][ordinal], now=scan_now())
                        except Exception:
                            summary["telegram_dispatches"][index] = dict(ok=False, skipped=True, reason="delivery_unconfirmed")
                if recovery or recovery_clock:
                    for symbol in all_candles_map:
                        self._candle_evidence.pop((provider, symbol), None)
            self.last_scan_summary = summary
            if paper_coordinator is not None:
                try:
                    summary["paper_portfolio"] = paper_coordinator.consume_scan(summary, all_candles_map)
                except Exception:
                    # Signal generation and paper effects are separate claims.
                    # Durable event keys allow recovery after a partial handoff.
                    summary["paper_portfolio"] = {"status": "UNAVAILABLE", "execution_mode": "SIMULATED",
                                                  "reason_code": "PAPER_CYCLE_REQUIRES_RECOVERY"}
            return summary
        except (CandleFreshnessError, BrokerIdentityError) as exc:
            self.last_broker_error = str(exc)
            self.last_broker_error_category = exc.error_category
            self.last_candle_freshness = self._freshness_status(provider, scan_now())
            if durable_work and not result_committed:
                # All staged result writes are rolled back by the owner context.
                persisted_signals_count = 0
                self.last_persistence_status = "ERROR"
                self.last_persistence_error = "LINEAGE_SCAN_RESULT_ROLLED_BACK"
            self.last_scan_summary = dict(status="error", scan_status="FAILED", error_type=type(exc).__name__,
                                          freshness=getattr(exc, "freshness", None), rejection=getattr(exc, "rejection", None), total_signals=persisted_signals_count,
                                          persisted_signals=persisted_signals_count, signals=[], telegram_dispatches=[])
            if self.store is not None and not durable_work:
                try:
                    self.store.record_scan_run(
                        run_id=run_id, started_at_ist=started_ist, completed_at_ist=format_ist_timestamp(scan_now()),
                        duration_ms=(time.perf_counter()-started_wall)*1000, status="FAILED", broker=adapter.name,
                        data_mode="LIVE", is_simulated=False, total_signals=persisted_signals_count,
                        persisted_signals=persisted_signals_count, error_type=type(exc).__name__, error_message=str(exc))
                except PersistenceError as db_exc:
                    self.last_persistence_status, self.last_persistence_error = "ERROR", str(db_exc)
            raise
        except (PersistenceError, PersistenceValidationError) as exc:
            self.last_persistence_status, self.last_persistence_error = "ERROR", str(exc)
            self.last_scan_summary = dict(status="error", scan_status="FAILED", run_id=run_id,
                persistence_status="ERROR", total_signals=0, persisted_signals=0, signals=[], telegram_dispatches=[],
                reason_code="LINEAGE_REQUIRES_RECOVERY", error_type=type(exc).__name__)
            raise
        except BrokerDataError:
            # Acquisition failures already publish their existing FAILED outcome.
            raise
        except Exception as exc:
            if is_simulated is False and self.store is not None:
                self.last_persistence_status = "RECONCILIATION_REQUIRED" if result_committed else "ERROR"
                self.last_persistence_error = type(exc).__name__
                self.last_scan_summary = dict(status="error", scan_status="RECOVERY_REQUIRED", run_id=run_id,
                    persistence_status=self.last_persistence_status, total_signals=0, persisted_signals=0,
                    signals=[], telegram_dispatches=[], reason_code="LINEAGE_REQUIRES_RECOVERY",
                    error_type=type(exc).__name__)
            raise
        finally:
            try:
                if lineage_tx is not None:
                    lineage_tx.__exit__(*sys.exc_info())
            finally:
                self._scan_lock.release()


class MarketScanScheduler:
    """
    Reliable Indian Market-Session Scan Scheduler:
    - Enforces configurable IST session start/end boundaries (`session_start_ist`..`session_end_ist`),
      weekend exclusion (Saturday/Sunday), and optional `configured_holidays` (`YYYY-MM-DD`).
    - Prevents overlapping scan executions via `IntradayBotEngine`'s lock.
    - Guarantees single-thread idempotency via `_lifecycle_lock` so repeated `start()` calls
      never spawn duplicate background threads.
    - Supports both deterministic single-cycle execution (`run_scheduled_cycle()`) for testing
      and background thread execution (`start()` / `stop()`) with graceful shutdown.
    - Never initiates real-money orders.
    """
    def __init__(
        self,
        engine: IntradayBotEngine,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.engine = engine
        self.config = engine.config
        self.clock = clock or engine.clock or (lambda: datetime.now(IST))
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.cycles_executed: int = 0
        self.last_cycle_result: Optional[Dict[str, Any]] = None

    def is_market_session_open(self, now_dt: Optional[Any] = None) -> Tuple[bool, str]:
        """
        Determines whether the NSE intraday session is open at `now_dt` (in Asia/Kolkata).
        Returns `(is_open: bool, reason: str)`.
        """
        self.config.validate(require_live_credentials=False)
        ist_dt = parse_ist_timestamp(now_dt if now_dt is not None else self.clock())
        _, _, _, state, _ = candle_session_context(
            ist_dt, self.config.configured_holidays, self.config.session_start_ist, self.config.session_end_ist)
        return state == "within_session", state

    def run_scheduled_cycle(self) -> Dict[str, Any]:
        """
        Executes a single scheduled scan cycle if within NSE session boundaries;
        otherwise skips cleanly and records the reason.
        """
        now_dt = parse_ist_timestamp(self.clock())
        is_open, reason = self.is_market_session_open(now_dt)
        if not is_open:
            ts_str = format_ist_timestamp(now_dt)
            logger.info("Scheduled scan skipped at %s IST: %s", ts_str, reason)
            res = {
                "status": "skipped",
                "scan_status": "SKIPPED_OUTSIDE_SESSION",
                "reason": reason,
                "timestamp_ist": ts_str,
                "total_signals": 0,
                "signals": [],
            }
            self.last_cycle_result = res
            return res

        try:
            res = self.engine.run_single_scan()
            self.cycles_executed += 1
            self.last_cycle_result = res
            return res
        except BrokerDataError as exc:
            ts_str = format_ist_timestamp(now_dt)
            logger.error("Scheduled scan failed at %s IST due to BrokerDataError: %s", ts_str, exc)
            res = {
                "status": "error",
                "scan_status": "FAILED",
                "error_type": "BrokerDataError",
                "message": str(exc),
                "freshness": getattr(exc, "freshness", None),
                "reason_code": getattr(exc, "freshness", {}).get("reason_code", "PROVIDER_ERROR"),
                "timestamp_ist": ts_str,
                "total_signals": 0,
                "signals": [],
            }
            self.last_cycle_result = res
            return res

    def _loop(self) -> None:
        interval = max(5, int(self.config.scan_interval_seconds or 60))
        logger.info("MarketScanScheduler background loop started (interval=%ds).", interval)
        while not self._stop_event.is_set():
            try:
                self.run_scheduled_cycle()
            except Exception as exc:
                logger.error("Unexpected error in scheduler loop: %s", exc)
            if self._stop_event.wait(timeout=interval):
                break
        logger.info("MarketScanScheduler background loop stopped gracefully.")

    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return bool(self._thread is not None and self._thread.is_alive())

    def start(self) -> bool:
        """
        Starts the background scheduler thread if not already running.
        Thread-safe and idempotent: returns True if a new thread was started,
        or False if the scheduler thread was already active.
        """
        with self._lifecycle_lock:
            self.config.validate(require_live_credentials=False)
            if self._thread is not None and self._thread.is_alive():
                logger.info("MarketScanScheduler.start() called while already running; ignoring duplicate call.")
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="TradePulseScanScheduler",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=timeout)
            self._thread = None

    def get_status(self) -> Dict[str, Any]:
        try:
            is_open, session_reason = self.is_market_session_open()
        except Exception as exc:
            is_open, session_reason = False, f"invalid_config:{exc}"
        running = self.is_running()
        return {
            "running": running,
            "enabled_in_config": bool(self.config.enable_background_scheduler),
            "session_open": is_open,
            "session_state": session_reason,
            "session_start_ist": self.config.session_start_ist,
            "session_end_ist": self.config.session_end_ist,
            "scan_interval_seconds": int(self.config.scan_interval_seconds or 60),
            "configured_holidays": list(self.config.configured_holidays or []),
            "cycles_executed": self.cycles_executed,
        }


if __name__ == "__main__":
    import os as _os
    _cfg = BotConfig(database_url=_os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db"))
    engine = IntradayBotEngine(_cfg)
    summary = engine.run_single_scan()
    safe_console_print(
        f"[TradePulse & OrderBlock Bot v1] Active Broker: {summary['broker']} "
        f"(Mode: {summary['data_mode']} | Scan Status: {summary['scan_status']})"
    )
    safe_console_print(
        f"Total Signals Triggered: {summary['total_signals']} "
        f"(Persisted: {summary.get('persisted_signals', 0)} | Duplicates: {summary.get('duplicate_signals', 0)})"
    )
    for s in summary["signals"][:6]:
        safe_console_print(
            f" -> [{s['segment']}] {s['instrument_label']} | {s['strategy_name']} | "
            f"Entry: ₹{s['entry_price']} | SL: ₹{s['stop_loss']} | T1: ₹{s['target_1']} | Quality: {s['quality_score']}/100"
        )
