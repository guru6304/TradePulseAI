"""Local acceptance receipts and historical coverage policy (no network operations).

Receipts trust the diagnostic producer and local SQLite writers, not HTTP callers.
The digest detects accidental corruption; it is deliberately not an authentication claim.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta

from brokers import evaluate_candle_freshness
from historical_data import (
    HistoricalDataValidationError, STRATEGY_HISTORICAL_DATA_REQUIREMENTS,
    list_expected_nse_trading_sessions, validate_and_prepare_historical_dataset,
)
from strategies import IST, filter_completed_candles, format_ist_timestamp, parse_ist_timestamp


POLICY_VERSION = "phase_3b_1b_v1"
ACCEPTANCE_TTL = timedelta(minutes=30)
REAL_PROVIDERS = {"angelone", "dhan", "upstox"}
STRATEGY_3 = "strat_3_option_apex_oi"


def resolve_provider(config, data_mode, provider=None):
    if provider:
        return str(provider).strip().lower()
    configured = str(config.active_broker).strip().lower()
    return (configured if configured in REAL_PROVIDERS else "angelone") if data_mode == "LIVE" else "synthetic_fixture"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _scope(config, symbol):
    meta = next((m for m in config.equity_watchlist if m["symbol"].upper() == symbol), None)
    if meta is None:
        raise ValueError("Acceptance scope requires a configured equity.")
    return {"kind": "NSE_EQUITY_5M", "symbol": symbol,
            "instrument_token": str(meta["angel_token"]), "exchange": "NSE", "interval_min": 5,
            "session_start_ist": config.session_start_ist or "09:15",
            "session_end_ist": config.session_end_ist or "15:30",
            "configured_holidays": sorted(config.configured_holidays or [])}


def _failure(code, reason):
    return {"accepted": False, "reason_code": code, "reason": reason}


def _validate_receipt(envelope, config, provider, symbol, now):
    """Recheck retained observations; no stored accepted boolean is consulted."""
    try:
        payload = envelope["evidence"]
        if envelope["sha256"] != _digest(payload):
            raise ValueError("Evidence digest mismatch.")
        if (provider != "angelone" or payload["provider"] != provider
                or payload["producer"] != "phase2c_diagnostics"
                or payload["policy_version"] != POLICY_VERSION
                or payload.get("evidence_mode") != "LIVE_REQUEST"
                or payload["provenance"] != "LIVE_DIAGNOSTIC_OBSERVATIONS"
                or payload["scope"] != _scope(config, symbol)):
            raise ValueError("Provider, producer, provenance or scope mismatch.")
        observed = parse_ist_timestamp(payload["observed_at_ist"])
        expires = parse_ist_timestamp(payload["expires_at_ist"])
        if expires != observed + ACCEPTANCE_TTL or observed > now:
            raise ValueError("Inconsistent observation/expiry times.")
        if now >= expires:
            return _failure("ACCEPTANCE_EVIDENCE_EXPIRED", "Diagnostic evidence has expired.")
        if payload["checks"] != {str(i): "PASS" for i in range(1, 10)}:
            raise ValueError("All nine diagnostic checks must have completed successfully.")
        exchanges = {x.lower() for x in payload["profile_exchanges"]}
        if not ({"nse", "nse_cm"} & exchanges and {"nfo", "nse_fo"} & exchanges):
            raise ValueError("Profile evidence must include NSE and NFO access.")
        if payload["observed_instrument"] != {"symbol": symbol, "exchange": "NSE",
                                             "instrument_token": payload["scope"]["instrument_token"]}:
            raise ValueError("Observed instrument does not match the acceptance scope.")
        for key in ("authenticated_at_ist", "profile_verified_at_ist"):
            age = observed - parse_ist_timestamp(payload[key])
            if not timedelta(0) <= age <= ACCEPTANCE_TTL:
                raise ValueError("Authentication/profile observation outside acceptance window.")
        for sym, token in (("NIFTY", "99926000"), ("BANKNIFTY", "99926009")):
            quote = payload["quotes"][sym]
            age = observed - parse_ist_timestamp(quote["feed_timestamp_ist"])
            if (str(quote["symbol_token"]) != token or isinstance(quote["ltp"], bool)
                    or not math.isfinite(float(quote["ltp"])) or float(quote["ltp"]) <= 0
                    or not timedelta(0) <= age <= timedelta(minutes=20)):
                raise ValueError("Missing, invalid or stale index quote evidence.")
        scope = payload["scope"]
        prepared = validate_and_prepare_historical_dataset(
            candles=payload["candles"], symbol=symbol, segment="NSE_EQUITY_INTRADAY",
            exchange="NSE", provider=provider, instrument_token=scope["instrument_token"],
            interval_min=5, data_mode="LIVE", reference_time_ist=observed,
            retrieved_at_ist=observed, configured_holidays=config.configured_holidays,
            session_start_ist=scope["session_start_ist"], session_end_ist=scope["session_end_ist"],
            allow_identical_duplicates=False, sort_chronologically=False)
        if (len(prepared["candles"]) < 200
                or prepared["manifest"]["zero_volume_bars_count"]):
            raise ValueError("Insufficient positive-volume completed observation evidence.")
        freshness = evaluate_candle_freshness(
            prepared["candles"], interval_min=5, now_ist=observed,
            configured_holidays=config.configured_holidays,
            session_start_ist=scope["session_start_ist"], session_end_ist=scope["session_end_ist"],
            max_staleness_minutes=20.0)
        if not freshness.get("is_fresh"):
            raise ValueError("Diagnostic candle observations failed freshness verification.")
        return {"accepted": True, "reason_code": "VALID_DIAGNOSTIC_EVIDENCE",
                "provider": provider, "scope": scope,
                "observed_at_ist": payload["observed_at_ist"],
                "expires_at_ist": payload["expires_at_ist"], "evidence_digest": envelope["sha256"]}
    except (KeyError, TypeError, ValueError, OverflowError):
        return _failure("ACCEPTANCE_EVIDENCE_INVALID", "Malformed or inconsistent diagnostic evidence.")


def live_acceptance(config, store, provider, symbol, now=None, *, connection=None):
    now = parse_ist_timestamp(now or datetime.now(IST))
    if store is None:
        return _failure("ACCEPTANCE_EVIDENCE_MISSING", "No persisted diagnostic evidence is available.")
    try:
        envelope = (store.load_live_acceptance_evidence(provider, symbol) if connection is None else
                    store.load_live_acceptance_evidence(provider, symbol, connection=connection))
        if envelope is None:
            return _failure("ACCEPTANCE_EVIDENCE_MISSING", "No diagnostic evidence for this provider/symbol.")
        return _validate_receipt(envelope, config, provider, symbol, now)
    except Exception:
        return _failure("ACCEPTANCE_EVIDENCE_UNREADABLE", "Diagnostic evidence could not be read or verified.")


def live_acceptance_for_symbols(config, store, provider, symbols, now=None):
    """Validate every symbol in one fresh locked read; no verdict outlives it."""
    reference = parse_ist_timestamp(now or datetime.now(IST))
    if store is None:
        return {symbol: live_acceptance(config, store, provider, symbol, reference) for symbol in symbols}
    try:
        with store.lineage_read() as conn:
            return {symbol: live_acceptance(config, store, provider, symbol, reference, connection=conn)
                    for symbol in symbols}
    except Exception:
        return {symbol: _failure("ACCEPTANCE_EVIDENCE_UNREADABLE",
            "Diagnostic evidence could not be read or verified.") for symbol in symbols}


def _record_completed_diagnostic(config, store, adapter, checks, quotes, candles, symbol, observed, *,
                                 evidence_mode="UNVERIFIED"):
    """Diagnostic-only writer; never exposed as a request or acceptance-import endpoint."""
    if evidence_mode != "LIVE_REQUEST":
        return _failure("DIAGNOSTIC_EVIDENCE_MODE_NOT_LIVE", "Mocked, offline or unverified diagnostics cannot issue live receipts.")
    scope = _scope(config, symbol)
    completed = filter_completed_candles(candles, interval_min=5, now=observed)
    # Whitelist public market observations, never credentials/profile identity or tokens.
    clean_bars = [{k: b[k] for k in ("timestamp", "open", "high", "low", "close", "volume",
                                    "data_mode", "is_simulated", "is_complete") if k in b}
                  for b in completed]
    payload = {"policy_version": POLICY_VERSION, "producer": "phase2c_diagnostics", "evidence_mode": evidence_mode,
               "provider": "angelone", "provenance": "LIVE_DIAGNOSTIC_OBSERVATIONS", "scope": scope,
               "observed_at_ist": format_ist_timestamp(observed),
               "expires_at_ist": format_ist_timestamp(observed + ACCEPTANCE_TTL),
               "authenticated_at_ist": adapter.authenticated_at_ist,
               "profile_verified_at_ist": adapter.profile_verified_at_ist,
               "profile_exchanges": sorted({str(x).lower() for x in
                   checks["2_authentication_and_profile"]["details"]["exchanges"]
                   if str(x).lower() in {"nse", "nfo", "nse_cm", "nse_fo"}}),
               "observed_instrument": {
                   "symbol": checks["4_equity_intraday_candles"]["details"]["symbol"],
                   "exchange": checks["4_equity_intraday_candles"]["details"]["exchange"],
                   "instrument_token": str(checks["4_equity_intraday_candles"]["details"]["angel_token"])},
               "checks": {str(i): c["status"] for i, c in enumerate(checks.values(), 1)},
               "quotes": {sym: {k: quotes[sym][k] for k in
                                  ("symbol_token", "ltp", "feed_timestamp_ist")}
                          for sym in ("NIFTY", "BANKNIFTY")}, "candles": clean_bars}
    envelope = {"evidence": payload, "sha256": _digest(payload)}
    result = _validate_receipt(envelope, config, "angelone", symbol, observed)
    if result["accepted"]:
        store._save_live_acceptance_evidence("angelone", symbol, envelope)
    return result


def historical_coverage(config, store, provider, symbol, data_mode="LIVE", candles=None,
                        segment="NSE_EQUITY_INTRADAY", exchange="NSE", instrument_token="2885",
                        interval_min=5, start_date=None, end_date=None, now=None):
    """Validate rows, not manifest counters. Coverage spans whole sessions, including holes.

    Without explicit bounds this proves only the first-through-last stored session range.
    A consistent bounded snapshot spans all pages; incomplete reads fail closed.
    """
    base = {"symbol": symbol, "segment": segment, "provider": provider, "data_mode": data_mode,
            "ready_for_30_bar_strategies": False, "ready_for_200_bar_supertrend": False,
            "completed_bars_count": 0, "sessions_count": 0, "missing_bars_count": 0,
            "zero_volume_bars_count": 0, "research_eligible": False}
    try:
        if data_mode != "LIVE" or provider not in REAL_PROVIDERS or interval_min != 5:
            raise ValueError("Research coverage requires broker-sourced LIVE 5m records.")
        if candles is None:
            if store is None:
                raise ValueError("No historical store or candles.")
            rows = store.read_historical_snapshot(symbol=symbol, interval_min=5, data_mode="LIVE", provider=provider)
            candles = rows["items"]
            if rows["total_count"] != len(candles):
                return {**base, "status": "COVERAGE_UNVERIFIABLE_READ_LIMIT"}
            if candles:
                segment = candles[0]["segment"]
                exchange = candles[0]["exchange"]
                instrument_token = candles[0]["instrument_token"]
        for row in candles or []:
            for key, value in (("provider", provider), ("instrument_token", instrument_token),
                               ("exchange", exchange), ("interval_min", interval_min), ("segment", segment)):
                if key in row and str(row[key]) != str(value):
                    raise ValueError("Mixed historical provenance/metadata.")
        prepared = validate_and_prepare_historical_dataset(
            candles=candles, symbol=symbol, segment=segment, exchange=exchange, provider=provider,
            instrument_token=instrument_token, interval_min=5, data_mode="LIVE",
            reference_time_ist=now, configured_holidays=config.configured_holidays,
            session_start_ist=config.session_start_ist or "09:15",
            session_end_ist=config.session_end_ist or "15:30", require_complete_sessions=False)
        manifest = prepared["manifest"]
        # Report measured gaps without accepting them. Replay still requires complete sessions.
        base.update({k: manifest[k] for k in (
            "dataset_id", "completed_bars_count", "sessions_count", "missing_bars_count",
            "zero_volume_bars_count", "from_timestamp_ist", "to_timestamp_ist", "quality_status")})
        base.update(segment=segment, exchange=exchange, instrument_token=str(instrument_token))
        if manifest["missing_bars_count"]:
            return {**base, "status": "INCOMPLETE_SESSION_COVERAGE"}
        if manifest["zero_volume_bars_count"]:
            return {**base, "status": "ZERO_VOLUME_RESEARCH_COVERAGE"}
        first = manifest["from_timestamp_ist"][:10]
        last = manifest["to_timestamp_ist"][:10]
        expected = list_expected_nse_trading_sessions(start_date or first, end_date or last,
                                                     config.configured_holidays)
        present = {b["session_date"] for b in prepared["candles"]}
        if not expected or not set(expected).issubset(present):
            return {**base, "status": "REQUESTED_SESSIONS_NOT_COVERED",
                    "missing_requested_sessions": sorted(set(expected) - present)}
        count = manifest["completed_bars_count"]
        return {**base, "segment": segment, "status": "COMPLETE_RESEARCH_COVERAGE",
                "exchange": exchange, "instrument_token": str(instrument_token),
                "research_eligible": count >= 35, "completed_bars_count": count,
                "sessions_count": manifest["sessions_count"], "from_timestamp_ist": manifest["from_timestamp_ist"],
                "to_timestamp_ist": manifest["to_timestamp_ist"], "quality_status": manifest["quality_status"],
                "ready_for_30_bar_strategies": count >= 35,
                "ready_for_200_bar_supertrend": count >= 200}
    except (HistoricalDataValidationError, ValueError, TypeError, KeyError):
        return {**base, "status": "INCOMPLETE_OR_INVALID_RESEARCH_COVERAGE"}
    except Exception:
        return {**base, "status": "COVERAGE_UNVERIFIABLE"}


def _receipt_covers_history(acceptance, coverage):
    scope = acceptance.get("scope", {})
    return bool(acceptance["accepted"] and coverage.get("segment") == "NSE_EQUITY_INTRADAY"
                and coverage.get("exchange") == scope.get("exchange")
                and coverage.get("instrument_token") == scope.get("instrument_token"))


def execution_gate(config, store, provider, symbol, strategy_id, data_mode="LIVE",
                   execution_scope=None, now=None, option_execution_request=None,
                   publisher_trust_config=None, option_config=None, **coverage_args):
    scope = execution_scope or ("LIVE_ACCEPTED" if data_mode == "LIVE" else "SIMULATED_TEST")
    result = {"allowed": False, "execution_scope": scope, "policy_version": POLICY_VERSION}
    if strategy_id == STRATEGY_3:
        if option_execution_request is not None:
            from option_execution import gate
            from backtest_engine import BacktestConfig
            from types import SimpleNamespace
            profile=option_config or BacktestConfig(instrument_type="OPTIDX",execution_scope=scope)
            profile.validate()
            context=SimpleNamespace(bot_config=config,publisher_trust_config=publisher_trust_config,
                clock=lambda:parse_ist_timestamp(now or datetime.now(IST)))
            return {**result,**gate(context,option_execution_request,data_mode,provider,symbol,profile)}
        return {**result, "reason_code": "OPTION_EXECUTION_INPUT_REQUIRED"}
    if strategy_id not in STRATEGY_HISTORICAL_DATA_REQUIREMENTS:
        return {**result, "reason_code": "UNKNOWN_STRATEGY"}
    if data_mode == "SIMULATED":
        return {**result, "allowed": scope == "SIMULATED_TEST",
                "reason_code": "SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED" if scope == "SIMULATED_TEST"
                else "EXECUTION_SCOPE_MODE_MISMATCH"}
    if data_mode != "LIVE" or scope not in ("LIVE_ACCEPTED", "HISTORICAL_RESEARCH"):
        return {**result, "reason_code": "EXECUTION_SCOPE_MODE_MISMATCH"}
    acceptance = live_acceptance(config, store, provider, symbol, now)
    result["live_acceptance"] = acceptance
    if scope == "LIVE_ACCEPTED" and not acceptance["accepted"]:
        return {**result, "reason_code": "BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED"}
    if scope == "LIVE_ACCEPTED" and coverage_args.get("candles") is not None:
        return {**result, "reason_code": "LIVE_ACCEPTED_REQUIRES_STORED_HISTORY"}
    coverage = historical_coverage(config, store, provider, symbol, data_mode, now=now, **coverage_args)
    result["coverage"] = coverage
    field = "ready_for_200_bar_supertrend" if strategy_id == "strat_5_supertrend_pullback" else "ready_for_30_bar_strategies"
    if not coverage[field]:
        return {**result, "reason_code": coverage["status"] if not coverage["research_eligible"]
                else "INSUFFICIENT_STRATEGY_WARMUP"}
    if scope == "LIVE_ACCEPTED" and not _receipt_covers_history(acceptance, coverage):
        return {**result, "reason_code": "ACCEPTANCE_EVIDENCE_SCOPE_MISMATCH"}
    return {**result, "allowed": True,
            "reason_code": "LIVE_DIAGNOSTIC_ACCEPTED_RESEARCH" if scope == "LIVE_ACCEPTED"
            else "HISTORICAL_RESEARCH_ONLY_NOT_LIVE_ACCEPTED"}


def readiness_report(config, store=None, broker_status=None, target_data_mode="LIVE",
                     provider=None, symbol=None, strategy_id="strat_1_order_block",
                     execution_scope=None, now=None, **coverage_args):
    target_data_mode = str(target_data_mode).strip().upper()
    provider = resolve_provider(config, target_data_mode, provider)
    symbol = str(symbol).strip().upper() if symbol else None
    now = parse_ist_timestamp(now or datetime.now(IST))
    symbols = list(dict.fromkeys(str(m["symbol"]).upper() for m in config.equity_watchlist))
    bounds = {k: coverage_args[k] for k in ("start_date", "end_date") if k in coverage_args}
    coverage = {s: historical_coverage(config, store, provider, s, target_data_mode, now=now, **bounds)
                for s in symbols}
    receipts = {s: live_acceptance(config, store, provider, s, now) for s in symbols}
    aggregate = bool(symbols) and all(c["ready_for_200_bar_supertrend"] for c in coverage.values())
    accepted = target_data_mode == "LIVE" and bool(symbols) and all(r["accepted"] for r in receipts.values())
    compatible = bool(symbols) and all(_receipt_covers_history(receipts[s], coverage[s]) for s in symbols)
    ready = target_data_mode == "LIVE" and aggregate and accepted and compatible
    code = ("READY_FOR_OHLCV_STRATEGIES_1_2_4_5_ONLY" if ready else
            "BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED" if not accepted else
            "BLOCKED_INCOMPLETE_LIVE_HISTORICAL_DATASETS" if not aggregate else
            "ACCEPTANCE_EVIDENCE_SCOPE_MISMATCH")
    strategies = {}
    for sid, spec in STRATEGY_HISTORICAL_DATA_REQUIREMENTS.items():
        field = "ready_for_200_bar_supertrend" if sid == "strat_5_supertrend_pullback" else "ready_for_30_bar_strategies"
        count = sum(c[field] for c in coverage.values()) if sid != STRATEGY_3 else 0
        strategies[sid] = {"strategy_id": sid, "strategy_name": spec["strategy_name"],
                           "readiness_scope": "HISTORICAL_RESEARCH_INPUTS",
                           "status": "DATA_READY" if count else "BLOCKED_MISSING_HISTORICAL_CANDLES",
                           "ready_symbols_count": count, "required_inputs": spec["required_fields"]}
        if sid == STRATEGY_3:
            strategies[sid].update(status="BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN",
                                   reason_code="OPTION_EXECUTION_INPUT_REQUIRED")
    result = {"phase": POLICY_VERSION, "evaluated_at_ist": format_ist_timestamp(now or datetime.now(IST)),
              "target_data_mode": target_data_mode, "provider": provider,
              "phase2c_live_accepted": accepted, "phase3_ready_for_execution": ready,
              "broker_connection_state": (broker_status or {}).get("connection_state", "UNVERIFIED"),
              "overall_gate_status": code, "overall_gate_reason": code,
              "aggregate_coverage_ready": aggregate, "required_symbols": symbols,
              "coverage_contract": {"interval_min": 5, "complete_sessions_required": True,
                                    "minimum_bars_per_watchlist_symbol": 200,
                                    "range": "REQUESTED_BOUNDS" if any(bounds.values()) else "PER_SYMBOL_STORED_RANGE",
                                    "shared_study_period_verified": False},
              "live_execution_scope_compatible": compatible,
              "live_acceptance_by_symbol": receipts, "symbol_coverage": coverage,
              "strategies_readiness": strategies,
              "data_acceptance_status": "SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED"
              if target_data_mode == "SIMULATED" else code}
    if symbol:
        result["execution_gate"] = execution_gate(
            config, store, provider, symbol, strategy_id, target_data_mode,
            execution_scope, now, **coverage_args)
    return result
