import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

try:
    from config import BotConfig, ConfigValidationError, _is_placeholder_value, _is_valid_base32_secret
except ValueError as exc:
    if __name__ != "__main__" or type(exc).__name__ != "ConfigValidationError":
        raise
    # Dotenv parsing runs during import, before main's initialization handler.
    print(json.dumps(dict(provider="angelone", overall_status="FAIL", exit_code=1,
        checks=dict(configuration=dict(status="BLOCKED", reason=str(exc))),
        readiness_receipt_issued=False, readiness_receipt_eligible=False,
        data_persisted=False, historical_replay_allowed=False)))
    raise SystemExit(1) from None
from brokers import (
    AngelOneSmartAPIAdapter,
    BrokerDataError,
    UnsupportedBrokerCapabilityError,
    _redact_secrets,
    evaluate_candle_freshness,
    generate_totp,
    validate_symbol_meta,
)
from scanner_engine import format_console_text, safe_console_print
from storage import (
    PersistenceError,
    PersistenceValidationError,
    SQLitePersistenceStore,
)
from strategies import (
    IST,
    filter_completed_candles,
    format_ist_timestamp,
    parse_ist_timestamp,
    validate_candles,
)

VALID_CHECK_STATUSES = ("PASS", "FAIL", "WARNING", "NOT CHECKED")


def _mask_identifier(val: Optional[str]) -> str:
    """Masks a client code or non-secret identifier for safe diagnostic display (e.g. 'A1234567' -> 'A1***67')."""
    s = str(val or "").strip()
    if not s or _is_placeholder_value(s):
        return "NOT_SET"
    if len(s) <= 4:
        return s[0] + "***"
    return f"{s[:2]}***{s[-2:]}"


def _collect_all_secrets(config: BotConfig, adapter: Optional[AngelOneSmartAPIAdapter] = None) -> List[Optional[str]]:
    secrets: List[Optional[str]] = [
        config.angel_api_key,
        config.angel_pin,
        config.angel_totp_secret,
        config.dhan_access_token,
        config.upstox_access_token,
        config.upstox_api_key,
        config.telegram_bot_token,
        config.gemini_api_key,
        config.angel_client_code,
        config.dhan_client_id,
        config.telegram_chat_id,
    ]
    if adapter is not None:
        secrets.extend(adapter._secret_values())
    return secrets


def run_angelone_diagnostics(
    config: Optional[BotConfig] = None,
    adapter: Optional[AngelOneSmartAPIAdapter] = None,
    store: Optional[SQLitePersistenceStore] = None,
    clock: Optional[Callable[[], datetime]] = None,
    equity_symbol: str = "RELIANCE",
    skip_network: bool = False,
    run_live_requests: Optional[bool] = None,
    evidence_mode: str = "UNVERIFIED",
) -> Dict[str, Any]:
    """
    Phase 2C Read-Only Live-Data Acceptance & Operational Diagnostic Workflow.
    Independently checks all 9 required areas without starting the full scanner or placing orders:
      1. Configuration validity & presence of required credentials (without displaying values)
      2. Angel One authentication & profile verification (`loginByPassword` + `getProfile`)
      3. NIFTY and BANKNIFTY quote retrieval (`market/v1/quote/`) & feed observation timestamp
      4. RELIANCE (or configured NSE equity) 5-minute intraday candle retrieval (`getCandleData`)
      5. Candle timestamp IST normalization, chronological ordering, OHLCV integrity, interval & freshness
      6. Scrip Master load status, file age, and NIFTY / BANKNIFTY contract resolution
      7. SQLite health and OI baseline counts (separating CLOSING_BASELINE vs INTRADAY_OBSERVATION)
      8. Per-index Option Apex readiness (missing, stale, intraday-only, mismatched, or ready baselines)
      9. Broker throttling, timeouts, authentication expiry recovery readiness & secret redaction audit
    Outputs strictly `PASS`, `FAIL`, `WARNING`, or `NOT CHECKED` for each check.
    """
    cfg = config or BotConfig(
        database_url=os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db")
    )
    if run_live_requests is not None:
        skip_network = not bool(run_live_requests)
    if evidence_mode not in ("UNVERIFIED", "MOCKED", "OFFLINE", "LIVE_REQUEST"):
        raise ValueError("Unsupported diagnostic evidence mode.")
    if skip_network:
        evidence_mode = "OFFLINE"
    clock_fn = clock or (lambda: datetime.now(IST))
    now_ist = parse_ist_timestamp(clock_fn())
    now_ist_str = format_ist_timestamp(now_ist)

    owns_store = False
    if store is None and cfg.enable_persistence:
        try:
            store = SQLitePersistenceStore(cfg.database_url or "sqlite:///tradepulse_phase1d.db")
            owns_store = True
        except Exception:
            store = None

    if adapter is None:
        adapter = AngelOneSmartAPIAdapter(cfg, clock=clock_fn, persistence_store=store)
    elif store is not None and adapter.persistence_store is None:
        adapter.attach_persistence_store(store)

    all_secrets = _collect_all_secrets(cfg, adapter)

    def sanitize_str(text: Any) -> str:
        variants = [variant for value in _collect_all_secrets(cfg, adapter) if value for variant in
                    (str(value), urllib.parse.quote(str(value), safe=""), urllib.parse.quote_plus(str(value)))]
        return _redact_secrets(str(text or ""), sorted(set(variants), key=len, reverse=True))

    def sanitize_report(value):
        if isinstance(value, str):
            return sanitize_str(value)
        if isinstance(value, list):
            return [sanitize_report(item) for item in value]
        if isinstance(value, dict):
            return {key: sanitize_report(item) for key, item in value.items()}
        return value

    checks: Dict[str, Dict[str, Any]] = {}

    # -------------------------------------------------------------------------
    # Check 1: Configuration validity & presence of required credentials
    # -------------------------------------------------------------------------
    missing_creds: List[str] = []
    for env_name, val in (
        ("ANGEL_API_KEY", cfg.angel_api_key),
        ("ANGEL_CLIENT_CODE", cfg.angel_client_code),
        ("ANGEL_PIN", cfg.angel_pin),
        ("ANGEL_TOTP_SECRET", cfg.angel_totp_secret),
    ):
        if _is_placeholder_value(val):
            missing_creds.append(env_name)

    totp_valid_base32 = _is_valid_base32_secret(cfg.angel_totp_secret)
    totp_can_generate = False
    if totp_valid_base32:
        try:
            code = generate_totp(str(cfg.angel_totp_secret), for_time=now_ist.timestamp())
            totp_can_generate = len(code) == 6 and code.isdigit()
        except Exception:
            totp_can_generate = False

    config_valid = True
    config_err: Optional[str] = None
    try:
        cfg.validate(require_live_credentials=False)
    except ConfigValidationError as exc:
        config_valid = False
        config_err = sanitize_str(exc)

    creds_ready = (not missing_creds) and totp_valid_base32 and totp_can_generate
    active_b = str(cfg.active_broker or "").strip().lower()
    if not config_valid:
        c1_status = "FAIL"
        c1_summary = f"Configuration validation failed: {config_err}"
    elif not creds_ready:
        c1_status = "FAIL"
        reasons = []
        if missing_creds:
            reasons.append(f"missing/placeholder: {', '.join(missing_creds)}")
        elif not totp_valid_base32 or not totp_can_generate:
            reasons.append("ANGEL_TOTP_SECRET is not a valid Base32 TOTP seed")
        c1_summary = f"Angel One credentials incomplete ({'; '.join(reasons)})."
    elif active_b != "angelone":
        c1_status = "WARNING"
        c1_summary = (
            f"Angel One credentials are valid (client={_mask_identifier(cfg.angel_client_code)}), "
            f"but ACTIVE_BROKER is currently '{cfg.active_broker}' (set ACTIVE_BROKER=angelone for live scans)."
        )
    else:
        c1_status = "PASS"
        c1_summary = (
            f"Configuration valid; ACTIVE_BROKER=angelone and all 4 ANGEL_* credentials + Base32 TOTP seed verified "
            f"(client={_mask_identifier(cfg.angel_client_code)})."
        )

    checks["1_config_and_credentials"] = {
        "name": "1. Configuration & Credential Presence",
        "status": c1_status,
        "summary": c1_summary,
        "details": {
            "active_broker": cfg.active_broker,
            "config_valid": config_valid,
            "client_code_masked": _mask_identifier(cfg.angel_client_code),
            "missing_credentials": missing_creds,
            "totp_base32_valid": totp_valid_base32,
            "totp_generator_verified": totp_can_generate,
        },
    }

    # -------------------------------------------------------------------------
    # Check 2: Angel One Authentication & Profile Verification
    # -------------------------------------------------------------------------
    auth_ok = False
    profile_info: Optional[Dict[str, Any]] = None
    if not creds_ready or not config_valid or skip_network:
        c2_status = "NOT CHECKED"
        c2_summary = (
            "Skipped network authentication check (--offline / skip_network=True)."
            if skip_network
            else "Skipped authentication because required ANGEL_* credentials are missing or invalid."
        )
        c2_details: Dict[str, Any] = {"authenticated": False, "reason": c2_summary}
    else:
        try:
            adapter.authenticate()
            profile_info = adapter.get_profile()
            auth_ok = True
            exchanges = [sanitize_str(str(x)).upper() for x in (profile_info.get("exchanges") or [])]
            has_nse = "NSE" in exchanges or "nse_cm" in [x.lower() for x in exchanges]
            has_nfo = "NFO" in exchanges or "nse_fo" in [x.lower() for x in exchanges]
            if exchanges and not (has_nse and has_nfo):
                c2_status = "WARNING"
                c2_summary = (
                    f"Authenticated & verified profile for {_mask_identifier(profile_info.get('clientcode'))}, "
                    f"but account exchanges ({exchanges}) may not include both NSE and NFO."
                )
            else:
                c2_status = "PASS"
                c2_summary = (
                    f"Authenticated via loginByPassword and verified active session via getProfile "
                    f"(client={_mask_identifier(profile_info.get('clientcode'))}, exchanges={exchanges})."
                )
            c2_details = {
                "authenticated": True,
                "authenticated_at_ist": adapter.authenticated_at_ist,
                "profile_verified_at_ist": adapter.profile_verified_at_ist,
                "client_code_masked": _mask_identifier(profile_info.get("clientcode")),
                "exchanges": exchanges,
                "products": [sanitize_str(value) for value in (profile_info.get("products") or [])],
                "refresh_token_present": bool(adapter.refresh_token),
                "feed_token_present": bool(adapter.feed_token),
            }
        except Exception as exc:
            c2_status = "FAIL"
            c2_summary = sanitize_str(exc)
            c2_details = {
                "authenticated": False,
                "error_category": getattr(exc, "error_category", adapter.last_error_category),
                "identity_rejection": getattr(exc, "rejection", None),
                "error": sanitize_str(exc),
            }

    checks["2_authentication_and_profile"] = {
        "name": "2. Angel One Authentication & Profile Verification",
        "status": c2_status,
        "summary": c2_summary,
        "details": c2_details,
    }

    # -------------------------------------------------------------------------
    # Check 3: NIFTY and BANKNIFTY Quote Retrieval
    # -------------------------------------------------------------------------
    quotes_ok = False
    if not auth_ok:
        c3_status = "NOT CHECKED"
        c3_summary = "Skipped NIFTY/BANKNIFTY quote check because authentication was not completed."
        c3_details: Dict[str, Any] = {}
    else:
        try:
            nifty_inst = adapter.resolve_instrument("NIFTY")
            bnf_inst = adapter.resolve_instrument("BANKNIFTY")
            q_res = adapter.get_quotes(
                {"NSE": [nifty_inst["angel_token"], bnf_inst["angel_token"]]},
                mode="FULL",
            )
            by_tok = q_res.get("by_token", {})
            n_q = by_tok.get(f"NSE:{nifty_inst['angel_token']}")
            b_q = by_tok.get(f"NSE:{bnf_inst['angel_token']}")
            if not n_q or not b_q:
                c3_status = "FAIL"
                c3_summary = (
                    f"Quote response did not return both NIFTY and BANKNIFTY "
                    f"(fetched={len(q_res.get('fetched', []))}, unfetched={len(q_res.get('unfetched', []))})."
                )
                c3_details = {"unfetched": q_res.get("unfetched", [])}
            else:
                quotes_ok = True
                n_ts = n_q.get("feed_timestamp_ist")
                b_ts = b_q.get("feed_timestamp_ist")
                if not n_ts or not b_ts:
                    c3_status = "WARNING"
                    c3_summary = (
                        f"NIFTY (LTP={n_q['ltp']}) and BANKNIFTY (LTP={b_q['ltp']}) quotes retrieved, "
                        f"but exchFeedTime was omitted by broker response."
                    )
                else:
                    c3_status = "PASS"
                    c3_summary = (
                        f"Retrieved live FULL quotes: NIFTY={n_q['ltp']} (@ {n_ts} IST), "
                        f"BANKNIFTY={b_q['ltp']} (@ {b_ts} IST)."
                    )
                c3_details = {
                    "NIFTY": {
                        "symbol_token": n_q["symbol_token"],
                        "ltp": n_q["ltp"],
                        "open": n_q.get("open"),
                        "high": n_q.get("high"),
                        "low": n_q.get("low"),
                        "close": n_q.get("close"),
                        "feed_timestamp_ist": n_ts,
                    },
                    "BANKNIFTY": {
                        "symbol_token": b_q["symbol_token"],
                        "ltp": b_q["ltp"],
                        "open": b_q.get("open"),
                        "high": b_q.get("high"),
                        "low": b_q.get("low"),
                        "close": b_q.get("close"),
                        "feed_timestamp_ist": b_ts,
                    },
                }
        except Exception as exc:
            c3_status = "FAIL"
            c3_summary = sanitize_str(exc)
            c3_details = {
                "error_category": getattr(exc, "error_category", adapter.last_error_category),
                "identity_rejection": getattr(exc, "rejection", None),
                "error": sanitize_str(exc),
            }

    checks["3_index_quotes"] = {
        "name": "3. NIFTY & BANKNIFTY Quote Retrieval",
        "status": c3_status,
        "summary": c3_summary,
        "details": c3_details,
    }

    # -------------------------------------------------------------------------
    # Check 4: RELIANCE (or Configured Equity) Intraday Candle Retrieval
    # -------------------------------------------------------------------------
    retrieved_candles: List[Dict[str, Any]] = []
    eq_sym_clean = str(equity_symbol or "RELIANCE").strip().upper()
    if not auth_ok:
        c4_status = "NOT CHECKED"
        c4_summary = f"Skipped {eq_sym_clean} intraday candle retrieval because authentication was not completed."
        c4_details: Dict[str, Any] = {"symbol": eq_sym_clean}
    else:
        try:
            eq_inst = adapter.resolve_instrument(eq_sym_clean)
            retrieved_candles = adapter.get_intraday_candles(eq_inst, interval_min=5)
            completed_bars = filter_completed_candles(retrieved_candles, interval_min=5, now=now_ist)
            total_bars = len(retrieved_candles)
            comp_count = len(completed_bars)
            if comp_count >= 200:
                c4_status = "PASS"
                c4_summary = (
                    f"Retrieved {total_bars} 5-minute candles for {eq_sym_clean} (token={eq_inst['angel_token']}); "
                    f"{comp_count} completed bars (>= 200 required for 200-EMA strategies)."
                )
            elif comp_count >= 35:
                c4_status = "WARNING"
                c4_summary = (
                    f"Retrieved {comp_count} completed 5-minute candles for {eq_sym_clean} "
                    f"(sufficient for Strategies 1-4, but < 200 bars required for Strategy 5 200-EMA)."
                )
            else:
                c4_status = "FAIL"
                c4_summary = (
                    f"Insufficient 5-minute candle history for {eq_sym_clean}: only {comp_count} completed bars returned."
                )
            c4_details = {
                "symbol": eq_sym_clean,
                "angel_token": eq_inst["angel_token"],
                "exchange": eq_inst["exchange"],
                "total_candles": total_bars,
                "completed_candles": comp_count,
                "first_candle_timestamp_ist": retrieved_candles[0]["timestamp"] if retrieved_candles else None,
                "latest_candle_timestamp_ist": retrieved_candles[-1]["timestamp"] if retrieved_candles else None,
            }
        except Exception as exc:
            c4_status = "FAIL"
            c4_summary = sanitize_str(exc)
            c4_details = {
                "symbol": eq_sym_clean,
                "error_category": getattr(exc, "error_category", adapter.last_error_category),
                "identity_rejection": getattr(exc, "rejection", None),
                "error": sanitize_str(exc),
                "freshness": getattr(exc, "freshness", None),
            }

    checks["4_equity_intraday_candles"] = {
        "name": f"4. {eq_sym_clean} Intraday 5m Candle Retrieval",
        "status": c4_status,
        "summary": c4_summary,
        "details": c4_details,
    }

    # -------------------------------------------------------------------------
    # Check 5: Candle Timestamp Normalization, Ordering, OHLCV Integrity & Freshness
    # -------------------------------------------------------------------------
    if not retrieved_candles:
        c5_status = "NOT CHECKED"
        c5_summary = "Skipped candle integrity and freshness validation because no candles were retrieved in Check 4."
        c5_details: Dict[str, Any] = {}
    else:
        try:
            revalidated = validate_candles(
                retrieved_candles,
                deduplicate=False,
                sort_chronologically=False,
                interval_min=5,
                now=now_ist,
                default_is_simulated=False,
            )
            timestamps = [c["timestamp"] for c in revalidated]
            strictly_increasing = all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1))
            interval_aligned = all(parse_ist_timestamp(ts).minute % 5 == 0 for ts in timestamps)
            sim_flags_clean = all(not c.get("is_simulated", False) for c in revalidated)

            freshness = evaluate_candle_freshness(
                revalidated,
                interval_min=5,
                now_ist=now_ist,
                configured_holidays=cfg.configured_holidays,
                session_start_ist=str(cfg.session_start_ist or "09:15"),
                session_end_ist=str(cfg.session_end_ist or "15:30"),
                max_delay_seconds=cfg.live_candle_max_delay_seconds,
                future_skew_seconds=cfg.live_candle_future_skew_seconds,
                provider="angelone", symbol=eq_sym_clean, context="DIAGNOSTIC",
            )

            if not (strictly_increasing and interval_aligned and sim_flags_clean):
                c5_status = "FAIL"
                c5_summary = (
                    f"Candle integrity violation: strictly_increasing={strictly_increasing}, "
                    f"interval_aligned={interval_aligned}, live_provenance={sim_flags_clean}."
                )
            elif not freshness["is_fresh"]:
                c5_status = "FAIL"
                c5_summary = freshness["reason"]
            else:
                c5_status = "PASS"
                c5_summary = (
                    f"Candles verified: chronological=True, 5m_aligned=True, OHLCV_valid=True, "
                    f"freshness={freshness['status']} ({freshness['reason']})"
                )
            c5_details = {
                "strictly_increasing_timestamps": strictly_increasing,
                "five_minute_grid_aligned": interval_aligned,
                "live_provenance_verified": sim_flags_clean,
                "freshness": freshness,
            }
        except Exception as exc:
            c5_status = "FAIL"
            c5_summary = f"Candle validation error: {sanitize_str(exc)}"
            c5_details = {"error": sanitize_str(exc)}

    checks["5_candle_integrity_and_freshness"] = {
        "name": "5. Candle Timestamp, Ordering, OHLCV Integrity & Freshness",
        "status": c5_status,
        "summary": c5_summary,
        "details": c5_details,
    }

    # -------------------------------------------------------------------------
    # Check 6: Scrip Master Load Status, File Age & Contract Resolution
    # -------------------------------------------------------------------------
    adapter.ensure_scrip_master_loaded()
    sm_status = adapter.get_scrip_master_status(now_ist=now_ist)
    sm_code = sm_status.get("status", "NOT_CONFIGURED")
    nifty_exps = sm_status.get("active_expiries", {}).get("NIFTY", [])
    bnf_exps = sm_status.get("active_expiries", {}).get("BANKNIFTY", [])
    nifty_pairs = sm_status.get("paired_strikes_count", {}).get("NIFTY", 0)
    bnf_pairs = sm_status.get("paired_strikes_count", {}).get("BANKNIFTY", 0)

    if sm_code == "LOADED" and nifty_exps and bnf_exps and nifty_pairs > 0 and bnf_pairs > 0:
        c6_status = "PASS"
        c6_summary = (
            f"Scrip Master LOADED ({sm_status.get('index_options_loaded')} NFO option contracts, "
            f"age={sm_status.get('file_age_hours')}h): NIFTY expiry {nifty_exps[0]} ({nifty_pairs} pairs), "
            f"BANKNIFTY expiry {bnf_exps[0]} ({bnf_pairs} pairs)."
        )
    elif sm_code == "STALE_FILE" and nifty_exps and bnf_exps:
        c6_status = "WARNING"
        c6_summary = (
            f"Scrip Master file is older than {sm_status.get('max_age_hours')}h "
            f"(age={sm_status.get('file_age_hours')}h). Refresh OpenAPIScripMaster.json before next session."
        )
    elif sm_code == "NOT_CONFIGURED":
        c6_status = "WARNING"
        c6_summary = (
            "ANGEL_SCRIP_MASTER_PATH is not configured. Strategies 1, 2, 4, and 5 work using static equity/index tokens, "
            "but Option Apex (Strategy 3) requires OpenAPIScripMaster.json to resolve NFO option tokens."
        )
    else:
        c6_status = "FAIL"
        c6_summary = (
            sm_status.get("last_error")
            or f"Scrip Master status is {sm_code} (NIFTY pairs={nifty_pairs}, BANKNIFTY pairs={bnf_pairs})."
        )

    checks["6_scrip_master_and_contracts"] = {
        "name": "6. Scrip Master Load Status, File Age & Contract Resolution",
        "status": c6_status,
        "summary": c6_summary,
        "details": sm_status,
    }

    # -------------------------------------------------------------------------
    # Check 7: SQLite Health & OI Baseline Counts (Closing vs Intraday)
    # -------------------------------------------------------------------------
    if store is None:
        c7_status = "WARNING"
        c7_summary = "SQLite persistence is disabled (ENABLE_PERSISTENCE=false)."
        c7_details: Dict[str, Any] = {"status": "DISABLED"}
    else:
        try:
            db_health = store.check_health()
            live_closing = db_health.get("oi_live_closing_baselines_count", 0)
            intraday_obs = db_health.get("oi_intraday_observations_count", 0)
            total_base = db_health.get("oi_baselines_count", 0)
            if live_closing > 0:
                c7_status = "PASS"
                c7_summary = (
                    f"SQLite healthy ({db_health.get('database_path')}): {live_closing} verified LIVE closing baseline rows "
                    f"({intraday_obs} intraday observation rows, {total_base} total)."
                )
            else:
                c7_status = "WARNING"
                c7_summary = (
                    f"SQLite healthy ({db_health.get('database_path')}), but 0 verified LIVE closing OI baseline rows exist "
                    f"(intraday_observations={intraday_obs}). Capture EOD closing OI (>= 15:25 IST) or import a prior-session baseline."
                )
            c7_details = db_health
        except Exception as exc:
            c7_status = "FAIL"
            c7_summary = f"SQLite health check failed: {sanitize_str(exc)}"
            c7_details = {"status": "ERROR", "error": sanitize_str(exc)}

    checks["7_sqlite_and_baseline_counts"] = {
        "name": "7. SQLite Health & OI Baseline Provenance Counts",
        "status": c7_status,
        "summary": c7_summary,
        "details": c7_details,
    }

    # -------------------------------------------------------------------------
    # Check 8: Per-Index Option Apex Readiness
    # -------------------------------------------------------------------------
    oa_readiness = adapter.get_option_apex_readiness(now_ist=now_ist)
    oa_overall = oa_readiness.get("overall_status", "UNKNOWN")
    oa_indices = oa_readiness.get("indices", {})
    n_oa = oa_indices.get("NIFTY", {})
    b_oa = oa_indices.get("BANKNIFTY", {})

    hard_fail_states = {
        "UNAVAILABLE_STALE_BASELINE",
        "UNAVAILABLE_EXPIRY_MISMATCH",
        "UNAVAILABLE_INCOMPLETE_PAIRS",
        "UNAVAILABLE_CORRUPT_SCRIP_MASTER",
        "UNAVAILABLE_EXPIRED_CONTRACTS",
        "UNAVAILABLE_INVALID_BASELINE",
        "UNAVAILABLE_MISSING_CREDENTIALS",
    }
    if n_oa.get("usable") and b_oa.get("usable"):
        c8_status = "PASS"
        c8_summary = (
            f"Option Apex READY for both indices: "
            f"NIFTY ({n_oa.get('expiry')} baseline={n_oa.get('baseline_session_date')} @ {n_oa.get('baseline_observation_timestamp')}), "
            f"BANKNIFTY ({b_oa.get('expiry')} baseline={b_oa.get('baseline_session_date')} @ {b_oa.get('baseline_observation_timestamp')})."
        )
    elif n_oa.get("status") in hard_fail_states or b_oa.get("status") in hard_fail_states:
        c8_status = "FAIL"
        c8_summary = (
            f"Option Apex blocked by invalid/stale/mismatched inputs: "
            f"NIFTY={n_oa.get('status')} ({n_oa.get('reason')}) | "
            f"BANKNIFTY={b_oa.get('status')} ({b_oa.get('reason')})."
        )
    else:
        c8_status = "WARNING"
        c8_summary = (
            f"Option Apex status={oa_overall} (NIFTY={n_oa.get('status')}, BANKNIFTY={b_oa.get('status')}). "
            f"Strategies 1, 2, 4, and 5 remain operational on valid live candles."
        )

    checks["8_option_apex_readiness"] = {
        "name": "8. Per-Index Option Apex Readiness (NIFTY & BANKNIFTY)",
        "status": c8_status,
        "summary": c8_summary,
        "details": oa_readiness,
    }

    # -------------------------------------------------------------------------
    # Check 9: Broker Throttling, Timeouts, Expiry Recovery & Secret Redaction
    # -------------------------------------------------------------------------
    timeout_val = float(getattr(cfg, "angel_request_timeout_seconds", 8.0) or 8.0)
    min_interval_val = float(getattr(cfg, "angel_min_request_interval_seconds", 0.0) or 0.0)

    # Verify order-placement blocking guardrail without making any network call
    order_blocked = False
    try:
        adapter._request_json("POST", "/rest/secure/angelbroking/order/v1/placeOrder", payload={})
    except BrokerDataError as ord_exc:
        order_blocked = "strictly disabled" in str(ord_exc).lower()

    # Verify secret redaction across a sample error message containing all secrets
    test_leak_str = " ".join(str(s) for s in _collect_all_secrets(cfg, adapter) if s and not _is_placeholder_value(s))
    redacted_sample = adapter._sanitize(f"Diagnostic redaction test: {test_leak_str}")
    leaked_in_sample = any(
        s and len(str(s).strip()) >= 3 and not _is_placeholder_value(s) and str(s).strip() in redacted_sample
        for s in _collect_all_secrets(cfg, adapter)
    )

    prelim_dump = json.dumps(checks)
    leaked_in_checks = any(
        s and len(str(s).strip()) >= 3 and not _is_placeholder_value(s) and str(s).strip() in prelim_dump
        for s in _collect_all_secrets(cfg, adapter)
    )

    if not order_blocked or leaked_in_sample or leaked_in_checks or timeout_val <= 0 or min_interval_val < 0:
        c9_status = "FAIL"
        c9_summary = (
            f"Security/operational guardrail failure: order_blocked={order_blocked}, "
            f"secret_leak_detected={leaked_in_sample or leaked_in_checks}, timeout={timeout_val}s."
        )
    elif auth_ok and not adapter.refresh_token:
        c9_status = "WARNING"
        c9_summary = (
            f"Order blocking active, zero secrets leaked, timeout={timeout_val}s, rate_interval={min_interval_val}s; "
            f"refreshToken was not returned by login (session expiry will fall back to full TOTP re-login)."
        )
    else:
        c9_status = "PASS"
        c9_summary = (
            f"Read-only order blocking verified, zero secrets in diagnostic output, "
            f"timeout={timeout_val}s, min_request_interval={min_interval_val}s, "
            f"session-expiry recovery={'refreshTokens + TOTP fallback' if adapter.refresh_token else 'TOTP re-login ready'}."
        )

    checks["9_throttling_recovery_and_redaction"] = {
        "name": "9. Throttling, Timeouts, Session Recovery & Secret Redaction",
        "status": c9_status,
        "summary": c9_summary,
        "details": {
            "request_timeout_seconds": timeout_val,
            "min_request_interval_seconds": min_interval_val,
            "order_endpoints_blocked": order_blocked,
            "zero_secret_leak_verified": not (leaked_in_sample or leaked_in_checks),
            "token_expiry_codes_handled": sorted(adapter.TOKEN_EXPIRY_ERROR_CODES),
            "refresh_token_available": bool(adapter.refresh_token),
        },
    }

    # Diagnostic work may take long enough for previously fresh candles to expire.
    # Recheck the actual retained batch; connectivity and receipts cannot extend its age.
    if retrieved_candles:
        current_freshness = evaluate_candle_freshness(
            retrieved_candles, interval_min=5, now_ist=clock_fn(),
            configured_holidays=cfg.configured_holidays,
            session_start_ist=cfg.session_start_ist, session_end_ist=cfg.session_end_ist,
            max_delay_seconds=cfg.live_candle_max_delay_seconds,
            future_skew_seconds=cfg.live_candle_future_skew_seconds,
            provider="angelone", symbol=eq_sym_clean, context="DIAGNOSTIC")
        adapter.last_candle_freshness = current_freshness
        checks["5_candle_integrity_and_freshness"]["details"]["freshness"] = current_freshness
        if not current_freshness["is_fresh"]:
            c5_status = "FAIL"
            checks["5_candle_integrity_and_freshness"].update(status="FAIL", summary=current_freshness["reason"])

    # Compute overall acceptance state
    statuses = [c["status"] for c in checks.values()]
    fail_count = statuses.count("FAIL")
    warn_count = statuses.count("WARNING")
    pass_count = statuses.count("PASS")
    not_checked_count = statuses.count("NOT CHECKED")

    live_verified = bool(
        auth_ok
        and (quotes_ok or bool(retrieved_candles))
        and adapter.is_connection_verified()
        and c5_status in ("PASS", "NOT CHECKED")
    )

    if fail_count > 0:
        overall_result = "FAIL"
    elif not live_verified:
        overall_result = "WARNING" if not_checked_count > 0 else "FAIL"
    elif warn_count > 0:
        overall_result = "PASS_WITH_WARNINGS"
    else:
        overall_result = "PASS"

    for k, chk_obj in checks.items():
        chk_obj["id"] = int(k.split("_")[0])
        chk_obj["key"] = k

    # Connectivity is informational. Only completed, successful diagnostics can
    # write an acceptance receipt, and later consumers revalidate its observations.
    from readiness_policy import _record_completed_diagnostic, live_acceptance
    acceptance = {"accepted": False, "reason_code": "ACCEPTANCE_EVIDENCE_NOT_PRODUCED"}
    if store is not None and not skip_network and evidence_mode == "LIVE_REQUEST":
        try:
            store._revoke_live_acceptance_evidence("angelone", eq_sym_clean)
            if live_verified and pass_count == 9 and cfg.active_broker == "angelone":
                acceptance = _record_completed_diagnostic(
                    cfg, store, adapter, checks, c3_details, retrieved_candles,
                    eq_sym_clean, parse_ist_timestamp(clock_fn()), evidence_mode=evidence_mode)
        except Exception:
            acceptance = {"accepted": False, "reason_code": "ACCEPTANCE_EVIDENCE_PERSISTENCE_FAILED"}
    elif store is not None and skip_network:
        acceptance = live_acceptance(cfg, store, "angelone", eq_sym_clean, now_ist)

    if owns_store and store is not None:
        store.close()

    return sanitize_report({
        "diagnostic_version": "phase_2c_v1",
        "evidence_mode": evidence_mode,
        "readiness_receipt_eligible": bool(evidence_mode == "LIVE_REQUEST" and not skip_network
            and live_verified and pass_count == 9 and cfg.active_broker == "angelone" and store is not None),
        "live_acceptance": acceptance,
        "executed_at_ist": now_ist_str,
        "overall_result": overall_result,
        "overall_status": overall_result,
        "live_connectivity_verified": live_verified and evidence_mode == "LIVE_REQUEST",
        "connectivity_verified": live_verified,
        "checks_list": list(checks.values()),
        "connection_state": (
            "CONNECTED_VERIFIED"
            if live_verified
            else ("UNAVAILABLE_MISSING_CREDENTIALS" if not creds_ready else ("ERROR" if adapter.last_error_message else "CONFIGURED_UNVERIFIED"))
        ),
        "last_market_data_at_ist": adapter.last_market_data_at_ist,
        "last_quote_timestamp_ist": adapter.last_quote_timestamp_ist,
        "last_candle_timestamp_ist": adapter.last_candle_timestamp_ist,
        "candle_freshness": adapter.last_candle_freshness or {"status": "NOT_CHECKED", "is_fresh": False},
        "live_candle_signal_allowed": bool(adapter.last_candle_freshness and
                                          adapter.last_candle_freshness.get("live_signal_allowed")),
        "counts": {
            "PASS": pass_count,
            "WARNING": warn_count,
            "FAIL": fail_count,
            "NOT CHECKED": not_checked_count,
        },
        "checks": checks,
    })


def format_diagnostics_report(report: Dict[str, Any]) -> str:
    """Formats the structured diagnostic dictionary into a clean, scannable console report."""
    lines: List[str] = [
        "=" * 86,
        "TRADEPULSE AI — PHASE 2C ANGEL ONE SMARTAPI LIVE-DATA ACCEPTANCE DIAGNOSTICS",
        "=" * 86,
        f"Executed At (IST)          : {report.get('executed_at_ist')}",
        f"Overall Diagnostic Verdict : {report.get('overall_result')}",
        f"Broker Connection State    : {report.get('connection_state')}",
        f"Live Connectivity Verified : {'YES (CONNECTED_VERIFIED)' if report.get('live_connectivity_verified') else 'NO'}",
        f"Persisted Live Acceptance  : {report.get('live_acceptance', {}).get('reason_code', 'UNVERIFIED')}",
        f"Last Market Data (IST)     : {report.get('last_market_data_at_ist') or 'None'}",
        f"Latest Quote Feed (IST)    : {report.get('last_quote_timestamp_ist') or 'None'}",
        f"Latest 5m Candle Bar (IST) : {report.get('last_candle_timestamp_ist') or 'None'}",
        "-" * 86,
    ]
    for key, chk in report.get("checks", {}).items():
        st = chk.get("status", "UNKNOWN")
        name = chk.get("name", key)
        summary = chk.get("summary", "")
        lines.append(f"[{st:<11}] {name}")
        lines.append(f"              {summary}")
    lines.append("-" * 86)
    counts = report.get("counts", {})
    lines.append(
        f"Summary Counts: PASS={counts.get('PASS', 0)} | WARNING={counts.get('WARNING', 0)} | "
        f"FAIL={counts.get('FAIL', 0)} | NOT CHECKED={counts.get('NOT CHECKED', 0)}"
    )
    lines.append("=" * 86)
    return "\n".join(lines)


def run_angelone_market_data_diagnostics(config=None, adapter=None, *, symbol, clock=None,
                                       config_only=False, sample_size=5, isolated_provider=False,
                                       evidence_mode="UNVERIFIED"):
    """Bound retries for this diagnostic; restore any caller-owned adapter policy."""
    previous = getattr(adapter, 'session_recovery_enabled', None)
    try:
        return _run_angelone_market_data_diagnostics(config, adapter, symbol=symbol, clock=clock,
            config_only=config_only, sample_size=sample_size, isolated_provider=isolated_provider,
            evidence_mode=evidence_mode)
    finally:
        if adapter is not None and previous is not None:
            adapter.session_recovery_enabled = previous


def _run_angelone_market_data_diagnostics(config=None, adapter=None, *, symbol, clock=None,
                                        config_only=False, sample_size=5, isolated_provider=False,
                                        evidence_mode="UNVERIFIED"):
    """One cash instrument, no profile, persistence, scan or acceptance receipt."""
    cfg = config or BotConfig()
    clock_fn = clock or (lambda: datetime.now(IST))
    checks = {key: dict(status="NOT_TESTED", reason="Required preceding checks have not completed.")
              for key in ("configuration", "instrument", "authentication", "quote", "candles")}
    selected = str(cfg.active_broker or "").strip().lower()
    report = dict(provider="angelone", symbol="RELIANCE", checks=checks, config_only=bool(config_only),
                  isolated_provider=isolated_provider is True, application_provider_changed=False,
                  transport_policy=dict(max_login_attempts=1, max_quote_requests=1, max_candle_requests=1,
                                        automatic_session_recovery=False),
                  scope="LOCAL_CONFIGURATION_PREFLIGHT" if config_only else "READ_ONLY_NSE_CASH_MARKET_DATA",
                  authentication_scope="AUTHORIZED_MARKET_DATA_READ_ONLY_NO_PROFILE_CHECK",
                  evidence_mode="OFFLINE_PREFLIGHT" if config_only else "UNVERIFIED",
                  executed_at_ist=format_ist_timestamp(clock_fn()),
                  initial_authentication=dict(status="NOT_TESTED", attempted=False),
                  session=dict(currently_authenticated=False, invalidation_occurred=False),
                  readiness_receipt_eligible=False,
                  readiness_receipt_issued=False, historical_replay_allowed=False, data_persisted=False,
                  effective_configuration=dict(active_broker=selected if selected in
                      ("angelone", "upstox", "dhan", "paper_sim", "sim", "simulated") else "INVALID",
                      telegram_dry_run=cfg.telegram_dry_run is True,
                      enable_background_scheduler=cfg.enable_background_scheduler is True))

    def result(key, status, reason, **details):
        checks[key] = dict(status=status, reason=reason, **details)

    def finish():
        if config_only:
            ready = all(checks[k]["status"] == "PASS" for k in ("configuration", "instrument"))
            report.update(configuration_ready=ready, overall_status="NOT_TESTED" if ready else "FAIL",
                          exit_code=0 if ready else 1)
        else:
            passed = all(check["status"] == "PASS" for check in checks.values())
            if report["session"].get("after_candles") == "UNAUTHENTICATED":
                passed = False
            report.update(overall_status="PASS" if passed else "FAIL", exit_code=0 if passed else 1)
        report["market_data_acceptance"] = dict(status=report["overall_status"],
            scope="OFFLINE_CONTRACT_ONLY" if report["evidence_mode"] in ("MOCKED", "OFFLINE", "OFFLINE_PREFLIGHT") else "SCOPED_READ_ONLY_CHECKS",
            live_accepted=False, reason="Narrow diagnostics never issue operational readiness evidence.")
        return report

    try:
        if type(isolated_provider) is not bool:
            raise ValueError()
        if evidence_mode not in ("UNVERIFIED", "MOCKED", "OFFLINE", "LIVE_REQUEST"):
            raise ValueError()
        if not config_only:
            report["evidence_mode"] = evidence_mode
        # Validate an explicit diagnostic view, never mutate the supplied config
        # or environment and never require a different provider's credentials.
        validation_cfg = replace(cfg, active_broker="angelone") if isolated_provider else cfg
        validation_cfg.validate(require_live_credentials=True)
        if ((selected != "angelone" and not isolated_provider) or cfg.telegram_dry_run is not True or cfg.enable_background_scheduler is not False
                or not cfg.is_broker_credentials_configured("angelone")):
            raise ValueError()
        if type(sample_size) is not int or not 1 <= sample_size <= 10:
            raise ValueError()
        result("configuration", "PASS", "Required local Angel configuration is present; authentication remains untested.")
    except Exception:
        missing = [name for name, value in (("ANGEL_API_KEY", cfg.angel_api_key),
                   ("ANGEL_CLIENT_CODE", cfg.angel_client_code), ("ANGEL_PIN", cfg.angel_pin),
                   ("ANGEL_TOTP_SECRET", cfg.angel_totp_secret)) if _is_placeholder_value(value)]
        result("configuration", "BLOCKED", "Valid local Angel credentials, explicit provider scope, Telegram dry run and disabled scheduler are required.",
               missing_configuration_fields=missing)
        return finish()
    try:
        if symbol != "RELIANCE":
            raise ValueError()
        meta = validate_symbol_meta(next(m for m in cfg.equity_watchlist if m["symbol"] == symbol), "angelone")
        if meta["angel_token"] != "2885":
            raise ValueError()
        result("instrument", "PASS", "Configured RELIANCE NSE cash instrument matches the checked-in reference.",
               instrument_token="2885", exchange="NSE", historical_validity="NOT_ESTABLISHED")
    except Exception:
        result("instrument", "BLOCKED", "Initial scope requires the checked-in RELIANCE NSE cash mapping.")
        return finish()
    if config_only:
        return finish()
    reader = adapter or AngelOneSmartAPIAdapter(cfg, clock=clock_fn)
    if not isinstance(reader, AngelOneSmartAPIAdapter) or reader.config is not cfg:
        result("configuration", "BLOCKED", "Diagnostic requires the existing configured Angel One adapter.")
        return finish()
    reader.session_recovery_enabled = False
    reads_before = reader._authorized_reads

    def session(stage):
        authenticated = bool(reader.jwt_token and reader.authenticated_at_ist)
        previous = report["session"]["currently_authenticated"]
        report["session"][stage] = "AUTHENTICATED" if authenticated else "UNAUTHENTICATED"
        report["session"]["currently_authenticated"] = authenticated
        if previous and not authenticated:
            report["session"]["invalidation_occurred"] = True

    def authentication():
        # This is historical evidence from this invocation. Current session state
        # is reported independently and cannot erase an earlier authorized read.
        accepted = reader._authorized_reads > reads_before
        result("authentication", "PASS" if accepted else "FAIL",
               "An authorized market-data response was observed." if accepted else
               "No successful authorized market-data response was observed in this diagnostic.")

    def failure(key):
        category = reader.last_error_category
        allowed = {"AUTH_FAILURE", "SESSION_EXPIRED", "RATE_LIMIT", "NETWORK_API_FAILURE",
                   "INVALID_RESPONSE", "INVALID_INSTRUMENT", "INVALID_INSTRUMENT_IDENTITY",
                   "STALE_MARKET_DATA", "MISSING_CREDENTIALS", "ACCESS_DENIED"}
        result(key, "FAIL", "Angel One market-data check failed.",
               error_category=category if category in allowed else "INVALID_RESPONSE",
               provider_error_message=reader._sanitize(reader.last_error_message or "Safe provider detail is unavailable."))
        if reader.last_http_status is not None:
            checks[key]["http_status"] = reader.last_http_status
            if reader.last_http_status == 403:
                checks[key].update(error_category="ACCESS_DENIED", provider_cause="NOT_ESTABLISHED")

    session("before_authentication")
    if not reader.jwt_token:
        report["initial_authentication"]["attempted"] = True
        try:
            if reader.authenticate() is not True or not reader.jwt_token:
                raise BrokerDataError("Authentication did not establish a session.")
            report["initial_authentication"].update(status="PASS", reason="Initial login established a session.")
        except Exception:
            failure("authentication")
            report["initial_authentication"].update(checks["authentication"])
            session("after_authentication")
            return finish()
    else:
        report["initial_authentication"]["reason"] = "Existing session reused; no login attempt was made in this invocation."
    session("after_authentication")
    session("before_quote")
    try:
        quote = reader.get_quote(meta)
        timestamp = quote.get("feed_timestamp_ist")
        if timestamp is None:
            result("quote", "BLOCKED", "Quote has no provider observation timestamp; currentness is unestablished.")
        else:
            observed, now = parse_ist_timestamp(timestamp), parse_ist_timestamp(clock_fn())
            age = (now - observed).total_seconds()
            if (observed.date() != now.date() or age > cfg.live_candle_max_delay_seconds
                    or age < -cfg.live_candle_future_skew_seconds):
                result("quote", "FAIL", "Quote observation is outside the configured delay/skew allowance.")
            else:
                result("quote", "PASS", "Quote identity, prices and provider observation time validated.",
                       ltp=quote["ltp"], quote_timestamp_ist=timestamp, observation_age_seconds=round(age, 3),
                       identity_limitation="Checked against the pinned reference; no authoritative historical validity established.")
    except Exception:
        failure("quote")
    session("after_quote")
    authentication()
    if checks["quote"]["status"] != "PASS":
        return finish()
    session("before_candles")
    try:
        candles = reader.get_intraday_candles(meta, interval_min=5)
        freshness = evaluate_candle_freshness(candles, interval_min=5, now_ist=clock_fn(),
            configured_holidays=cfg.configured_holidays, session_start_ist=cfg.session_start_ist,
            session_end_ist=cfg.session_end_ist, max_delay_seconds=cfg.live_candle_max_delay_seconds,
            future_skew_seconds=cfg.live_candle_future_skew_seconds, context="DIAGNOSTIC", provider="angelone", symbol=symbol)
        if not freshness["is_fresh"]:
            result("candles", "FAIL", "Completed candles do not satisfy the existing freshness policy.",
                   freshness_status=freshness["status"])
        elif freshness["session_state"] != "within_session":
            result("candles", "BLOCKED", "Prior-session candles do not establish current-session acceptance.",
                   freshness_status=freshness["status"])
        else:
            completed = filter_completed_candles(candles, interval_min=5, now=clock_fn())
            if not completed:
                raise ValueError()
            sample = [{k: bar[k] for k in ("timestamp", "open", "high", "low", "close", "volume")}
                      for bar in completed[-sample_size:]]
            result("candles", "PASS", "Completed intraday sample passes identity, OHLCV, interval and freshness checks.",
                   interval_min=5, completed_sample=sample, freshness_status=freshness["status"],
                   incomplete_bars_excluded=sum(not c["is_complete"] for c in candles),
                   response_binding=candles[-1]["instrument_identity"]["response_binding"])
    except Exception:
        failure("candles")
    session("after_candles")
    # A slow candle read must not leave an expired quote marked PASS.
    now = parse_ist_timestamp(clock_fn())
    observed = parse_ist_timestamp(checks["quote"]["quote_timestamp_ist"])
    age = (now - observed).total_seconds()
    if (observed.date() != now.date() or age > cfg.live_candle_max_delay_seconds
            or age < -cfg.live_candle_future_skew_seconds):
        result("quote", "FAIL", "Quote observation expired before diagnostic completion.")
    authentication()
    return finish()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="TradePulse Phase 2C — Safe Read-Only Angel One SmartAPI Live-Data Acceptance Diagnostics"
    )
    parser.add_argument(
        "--equity",
        default="RELIANCE",
        help="NSE equity symbol to use for 5-minute intraday candle check (default: RELIANCE)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run local config, Scrip Master, SQLite, and OI baseline checks without making network calls",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the diagnostic report as formatted JSON",
    )
    parser.add_argument(
        "--import-baseline",
        metavar="FILE_PATH",
        help="Validate and import an external prior-session closing OI baseline file (.json or .csv) before running checks",
    )
    parser.add_argument(
        "--refresh-scrip-master",
        metavar="CANDIDATE_JSON_PATH",
        help="Validate and atomically refresh ANGEL_SCRIP_MASTER_PATH from a candidate JSON file before running checks",
    )
    parser.add_argument("--market-data-only", action="store_true", help="Narrow RELIANCE quote/candle check; no profile, store or receipt.")
    parser.add_argument("--check-config", action="store_true", help="Offline preflight for --market-data-only; no adapter or API calls.")
    parser.add_argument("--isolated-provider", action="store_true", help="Explicit Angel-only diagnostic view; preserve the application's selected provider.")
    parser.add_argument("--symbol", choices=["RELIANCE"], help="Explicit scope for --market-data-only.")
    args = parser.parse_args(argv)
    if args.check_config and not args.market_data_only:
        parser.error("--check-config requires --market-data-only")
    if args.isolated_provider and not args.market_data_only:
        parser.error("--isolated-provider requires --market-data-only")
    if args.market_data_only:
        if not args.symbol or args.offline or args.import_baseline or args.refresh_scrip_master or args.equity != "RELIANCE":
            parser.error("Use --market-data-only --symbol RELIANCE without legacy diagnostic actions.")
        try:
            report = run_angelone_market_data_diagnostics(symbol=args.symbol, config_only=args.check_config,
                                                         isolated_provider=args.isolated_provider,
                                                         evidence_mode="LIVE_REQUEST")
        except Exception:
            report = dict(overall_status="FAIL", exit_code=1, reason="Angel market-data diagnostic could not initialize safely.",
                          readiness_receipt_issued=False, historical_replay_allowed=False, data_persisted=False)
        safe_console_print(json.dumps(report, sort_keys=True, allow_nan=False))
        return report["exit_code"]
    if args.symbol:
        parser.error("--symbol requires --market-data-only")

    cfg = BotConfig(
        database_url=os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db")
    )
    store = SQLitePersistenceStore(cfg.database_url or "sqlite:///tradepulse_phase1d.db") if cfg.enable_persistence else None
    adapter = AngelOneSmartAPIAdapter(cfg, persistence_store=store)

    if args.refresh_scrip_master:
        try:
            target_path = cfg.angel_scrip_master_path or "OpenAPIScripMaster.json"
            ref_res = adapter.refresh_scrip_master_safely(args.refresh_scrip_master, target_file_path=target_path)
            if not args.json:
                safe_console_print(f"[PASS] Refreshed Scrip Master safely: {json.dumps(ref_res)}")
        except Exception as exc:
            safe_console_print(f"[FAIL] Scrip Master refresh rejected: {adapter._sanitize(str(exc))}")
            return 2

    if args.import_baseline:
        try:
            imp_res = adapter.import_prior_oi_baseline_file(args.import_baseline)
            if not args.json:
                safe_console_print(f"[PASS] Imported closing OI baseline file: {json.dumps(imp_res)}")
        except Exception as exc:
            safe_console_print(f"[FAIL] Closing OI baseline import rejected: {adapter._sanitize(str(exc))}")
            return 2

    report = run_angelone_diagnostics(
        config=cfg,
        adapter=adapter,
        store=store,
        equity_symbol=args.equity,
        skip_network=args.offline,
        evidence_mode="LIVE_REQUEST",
    )

    if store is not None:
        store.close()

    if args.json:
        safe_console_print(json.dumps(report, indent=2))
    else:
        safe_console_print(format_diagnostics_report(report))

    return 0 if report["counts"]["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
