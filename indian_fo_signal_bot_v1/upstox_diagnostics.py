"""One-instrument read-only Upstox diagnostic. No store, scanner or receipt producer.

Running the CLI contacts Upstox. Importing it performs no market-data requests.
"""
import argparse
import json
from datetime import datetime

try:
    from config import BotConfig
except ValueError as exc:
    if __name__ != "__main__" or type(exc).__name__ != "ConfigValidationError":
        raise
    print(json.dumps(dict(provider="upstox", overall_status="FAIL", exit_code=1,
        checks=dict(configuration=dict(status="BLOCKED", reason=str(exc))),
        readiness_receipt_issued=False, readiness_receipt_eligible=False,
        data_persisted=False, historical_replay_allowed=False)))
    raise SystemExit(1) from None
from brokers import (UpstoxV2Adapter, BrokerDataError, sanitize_broker_message,
                     sanitize_upstox_error_detail, validate_symbol_meta, evaluate_candle_freshness)
from strategies import IST, filter_completed_candles, format_ist_timestamp, parse_ist_timestamp


def run_upstox_diagnostics(config=None, adapter=None, *, symbol, clock=None, sample_size=5, config_only=False,
                          evidence_mode="UNVERIFIED"):
    """Observe quote/candles only; success is not a Phase 2C readiness receipt."""
    cfg = config or BotConfig()
    clock_fn = clock or (lambda: datetime.now(IST))
    checks = {key: {"status": "NOT_TESTED", "reason": "Required preceding checks have not completed."}
              for key in ("configuration", "instrument", "authentication", "quote", "candles")}
    selected = str(cfg.active_broker or "").strip().lower()
    report = dict(provider="upstox", scope="LOCAL_CONFIGURATION_PREFLIGHT" if config_only else "READ_ONLY_NSE_CASH_MARKET_DATA", symbol="RELIANCE",
                  checks=checks, readiness_receipt_issued=False, historical_replay_allowed=False,
                  authentication_scope="AUTHORIZED_MARKET_DATA_READ_ONLY_NO_PROFILE_CHECK",
                  data_persisted=False, config_only=bool(config_only),
                  evidence_mode="OFFLINE_PREFLIGHT" if config_only else "UNVERIFIED",
                  executed_at_ist=format_ist_timestamp(clock_fn()), readiness_receipt_eligible=False,
                  initial_authentication=dict(status="NOT_TESTED", attempted=False,
                      reason="Pre-issued bearer token; no login endpoint is called."),
                  session=dict(currently_authenticated=False, invalidation_occurred=False),
                  effective_configuration={"active_broker": selected if selected in
                      ("upstox", "angelone", "dhan", "paper_sim", "sim", "simulated") else "INVALID",
                      "telegram_dry_run": cfg.telegram_dry_run is True,
                      "enable_background_scheduler": cfg.enable_background_scheduler is True})

    def result(key, status, reason, **details):
        checks[key] = dict(status=status, reason=sanitize_broker_message(cfg, reason), **details)

    def finish():
        if config_only:
            ready = all(checks[key]["status"] == "PASS" for key in ("configuration", "instrument"))
            report.update(configuration_ready=ready, overall_status="NOT_TESTED" if ready else "FAIL", exit_code=0 if ready else 1)
        else:
            passed = all(c["status"] == "PASS" for c in checks.values()) and report["session"]["currently_authenticated"]
            report.update(overall_status="PASS" if passed else "FAIL", exit_code=0 if passed else 1)
        report["market_data_acceptance"] = dict(status=report["overall_status"],
            scope="OFFLINE_CONTRACT_ONLY" if report["evidence_mode"] in ("MOCKED", "OFFLINE", "OFFLINE_PREFLIGHT") else "SCOPED_READ_ONLY_CHECKS",
            live_accepted=False, reason="Narrow diagnostics never issue operational readiness evidence.")
        return report

    try:
        if evidence_mode not in ("UNVERIFIED", "MOCKED", "OFFLINE", "LIVE_REQUEST"):
            raise ValueError()
        if not config_only:
            report["evidence_mode"] = evidence_mode
        cfg.validate(require_live_credentials=True)
        if cfg.active_broker.strip().lower() != "upstox" or not cfg.telegram_dry_run or cfg.enable_background_scheduler:
            result("configuration", "BLOCKED", "Select Upstox, enable Telegram dry run and disable the background scheduler.")
            return finish()
        if isinstance(sample_size, bool) or not isinstance(sample_size, int) or not 1 <= sample_size <= 10:
            result("configuration", "BLOCKED", "Completed sample size must be between 1 and 10.")
            return finish()
        if not cfg.is_broker_credentials_configured("upstox"):
            result("configuration", "BLOCKED", "A locally configured Upstox access token is required.")
            return finish()
        result("configuration", "PASS", "Required local configuration is present; this does not verify authentication.")
    except Exception:
        result("configuration", "BLOCKED", "Local configuration is invalid or required credentials are missing.")
        return finish()

    try:
        # Explicit initial scope; no caller-controlled instrument key or universe expansion.
        if symbol != "RELIANCE":
            raise ValueError()
        pinned = next(m for m in cfg.equity_watchlist if m["symbol"] == symbol)
        meta = validate_symbol_meta(pinned, "upstox")
        if meta["upstox_key"] != "NSE_EQ|INE002A01018":
            raise ValueError()
        identity = meta["instrument_identity"]
        result("instrument", "PASS", "Configured NSE cash instrument matches the checked-in identity reference.",
               instrument_key=identity["identifier"], historical_validity="NOT_ESTABLISHED")
    except Exception:
        result("instrument", "BLOCKED", "Initial scope requires the checked-in RELIANCE NSE cash mapping.")
        return finish()

    if config_only:
        return finish()

    reader = adapter or UpstoxV2Adapter(cfg, clock=clock_fn)
    if not isinstance(reader, UpstoxV2Adapter) or reader.config is not cfg:
        result("configuration", "BLOCKED", "Diagnostic requires the existing configured Upstox adapter.")
        return finish()
    reads_before = reader._authorized_reads

    def session(stage):
        authenticated = bool(reader.is_authentication_verified())
        previous = report["session"]["currently_authenticated"]
        report["session"][stage] = "AUTHENTICATED" if authenticated else "UNAUTHENTICATED"
        report["session"]["currently_authenticated"] = authenticated
        if previous and not authenticated:
            report["session"]["invalidation_occurred"] = True

    def authentication():
        accepted = reader._authorized_reads > reads_before
        result("authentication", "PASS" if accepted else "FAIL",
               "An authorized market-data response was observed in this diagnostic." if accepted else
               "No successful authorized response was observed in this diagnostic.")

    session("before_quote")
    try:
        quote = reader.get_quote(meta)
        timestamp = quote["quote_timestamp_ist"]
        if timestamp is None:
            result("quote", "BLOCKED", "Quote has no provider observation timestamp; currentness is unestablished.")
        else:
            observed, now = parse_ist_timestamp(timestamp), parse_ist_timestamp(clock_fn())
            age = (now - observed).total_seconds()
            if (observed.date() != now.date() or age > cfg.live_candle_max_delay_seconds
                    or age < -cfg.live_candle_future_skew_seconds):
                result("quote", "FAIL", "Quote observation is outside the configured diagnostic delay/skew allowance.")
            else:
                result("quote", "PASS", "Standalone quote prices, supplied identity fields and timestamp validated.",
                       ltp=quote["ltp"], quote_timestamp_ist=timestamp,
                       response_binding=quote["instrument_identity"]["response_binding"],
                       identity_limitation="Missing identity echo remains request-bound evidence only.")
    except Exception as exc:
        result("quote", "FAIL", "Standalone quote check failed.",
               error_category=_safe_category(exc), **_safe_http_error_details(cfg, exc))
    session("after_quote")
    authentication()

    # Candle acceptance requires a valid, current quote observation first.
    if checks["quote"]["status"] != "PASS":
        return finish()

    session("before_candles")
    try:
        candles = reader.get_intraday_candles(meta, interval_min=5)
        # Recheck the retained batch at observation completion using the unchanged
        # live freshness policy. Never weaken it for a diagnostic.
        freshness = evaluate_candle_freshness(candles, interval_min=5, now_ist=clock_fn(),
            configured_holidays=cfg.configured_holidays, session_start_ist=cfg.session_start_ist,
            session_end_ist=cfg.session_end_ist, max_delay_seconds=cfg.live_candle_max_delay_seconds,
            future_skew_seconds=cfg.live_candle_future_skew_seconds, context="DIAGNOSTIC", provider="upstox", symbol=symbol)
        if not freshness["is_fresh"]:
            result("candles", "FAIL", "Completed candles do not satisfy the existing freshness policy.",
                   freshness_status=freshness["status"])
        elif freshness["session_state"] != "within_session":
            result("candles", "BLOCKED", "Prior-session reference candles do not establish current-session acceptance.",
                   freshness_status=freshness["status"])
        else:
            completed = filter_completed_candles(candles, interval_min=5, now=clock_fn())
            if not completed:
                raise ValueError()
            # Report a bounded completed-only sample, never the response/headers.
            sample = [{key: bar[key] for key in ("timestamp", "open", "high", "low", "close", "volume")}
                      for bar in completed[-sample_size:]]
            result("candles", "PASS", "Completed intraday OHLCV sample passes ordering, interval and freshness checks.",
                   interval_min=5, completed_sample=sample, freshness_status=freshness["status"],
                   incomplete_bars_excluded=sum(not c["is_complete"] for c in candles),
                   response_binding=candles[-1]["instrument_identity"]["response_binding"])
    except Exception as exc:
        result("candles", "FAIL", "Intraday candle validation or freshness check failed.",
               error_category=_safe_category(exc), **_safe_http_error_details(cfg, exc))
    session("after_candles")

    # Diagnostic quote observation must also be current after both reads. Reuse
    # the configured delay allowance without altering the candle freshness policy.
    if checks["quote"]["status"] == "PASS":
        observed = parse_ist_timestamp(checks["quote"]["quote_timestamp_ist"])
        now = parse_ist_timestamp(clock_fn())
        age = (now - observed).total_seconds()
        if observed.date() != now.date() or age > cfg.live_candle_max_delay_seconds or age < -cfg.live_candle_future_skew_seconds:
            result("quote", "FAIL", "Quote observation is outside the configured diagnostic delay/skew allowance.")
        else:
            checks["quote"]["observation_age_seconds"] = round(age, 3)
            checks["quote"]["max_quote_delay_seconds"] = cfg.live_candle_max_delay_seconds
    authentication()
    return finish()


def _safe_http_error_details(config, exc):
    """Report curated scalar fields only, never arbitrary exception text/objects."""
    try:
        status = getattr(exc, "http_status", None)
        if type(status) is not int or not 100 <= status <= 599:
            return {}
        details = sanitize_upstox_error_detail(config, {
            "error_code": getattr(exc, "provider_error_code", None),
            "message": getattr(exc, "provider_error_message", None),
        })
        return dict(http_status=status, **details, **({"provider_cause": "NOT_ESTABLISHED"} if status == 403 else {}))
    except Exception:
        return {}


def _safe_category(exc):
    category = getattr(exc, "error_category", "VALIDATION_FAILED")
    allowed = {"AUTH_FAILURE", "FORBIDDEN", "RATE_LIMIT", "HTTP_ERROR", "NETWORK_API_FAILURE", "PROVIDER_ERROR",
               "MALFORMED_RESPONSE", "INVALID_RESPONSE", "INVALID_INSTRUMENT_IDENTITY", "MISSING_CREDENTIALS",
               "STALE_MARKET_DATA", "INVALID_TIMESTAMP", "CANDLE_GAP", "DUPLICATE_TIMESTAMP", "OUT_OF_ORDER"}
    return category if category in allowed else "VALIDATION_FAILED"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Upstox quote and completed-candle diagnostic; contacts Upstox.")
    parser.add_argument("--symbol", choices=["RELIANCE"], required=True, help="Explicit initial NSE cash instrument.")
    parser.add_argument("--sample-size", type=int, default=5, choices=range(1, 11))
    parser.add_argument("--json", action="store_true", help="JSON output (also the default).")
    parser.add_argument("--check-config", action="store_true", help="Offline configuration/mapping preflight; no adapter or network calls.")
    args = parser.parse_args(argv)
    try:
        options = dict(symbol=args.symbol, sample_size=args.sample_size, evidence_mode="LIVE_REQUEST")
        if args.check_config:
            options["config_only"] = True
        report = run_upstox_diagnostics(**options)
    except Exception:
        # Configuration construction/clock failures must not escape as raw traces.
        report = {"overall_status": "FAIL", "exit_code": 1, "reason": "Upstox diagnostic could not initialize safely.",
                  "readiness_receipt_issued": False, "historical_replay_allowed": False, "data_persisted": False}
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
