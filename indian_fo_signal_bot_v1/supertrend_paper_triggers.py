"""Isolated repeated Supertrend pullback experiment; evidence only, never fills.

The unchanged detector describes a completed pullback. Requiring those predicates
again on a strictly later completed bar is a NEW experimental hypothesis. The
original stop, targets and Supertrend invalidation stay frozen; no trailing rule
is inferred. Local retained-source integrity proves neither publisher
authenticity nor trading performance. Functions never mutate storage.
"""
import copy
import hashlib
import inspect
import json
from datetime import timedelta

from backtest_engine import IndianCostModel
from candle_lineage import digest, load_scan_evaluations
from paper_portfolio import PaperAccountConfig
from paper_triggers import source_observation
from strategies import (compute_atr, compute_ema, compute_session_vwap,
    compute_supertrend, evaluate_supertrend_pullback, format_ist_timestamp,
    parse_ist_timestamp, signal_state_identity)

RULE_ID = "supertrend.cash.later_repeated_pullback.evidence.v1"
STRATEGY = "strat_5_supertrend_pullback"


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _version():
    return hashlib.sha256(inspect.getsource(evaluate_supertrend_pullback).encode()).hexdigest()


def _prefix(work, candidate, stamp):
    batches = [b for b in work["snapshot"]["batches"]
               if b["content"]["identity"] == candidate["instrument_identity"]]
    _require(len(batches) == 1, "ST_SOURCE_IDENTITY_MISMATCH")
    bars = [b for b in batches[0]["content"]["candles"]
            if parse_ist_timestamp(b["timestamp"]) <= stamp]
    _require(len(bars) >= 200, "ST_WARMUP_REQUIRED")
    _require(parse_ist_timestamp(bars[-1]["timestamp"]) == stamp, "ST_SELECTED_OBSERVATION_MISSING")
    _require(all(b.get("is_complete") is True and b.get("interval_min") == 5 for b in bars),
             "ST_COMPLETED_INPUT_REQUIRED")
    stamps = [parse_ist_timestamp(b["timestamp"]) for b in bars]
    _require(all(a < b for a, b in zip(stamps, stamps[1:])), "ST_HISTORY_ORDER_INVALID")
    sessions = {}
    for item in stamps:
        _require(item.weekday() < 5 and "09:15" <= item.strftime("%H:%M") <= "15:25"
                 and item.minute % 5 == 0 and item.second == 0 and item.microsecond == 0,
                 "ST_NSE_HISTORY_REQUIRED")
        sessions.setdefault(item.date(), []).append(item)
    _require(all(len(items) <= 75 and all(b-a == timedelta(minutes=5)
                 for a, b in zip(items, items[1:])) for items in sessions.values()), "ST_SESSION_HISTORY_GAP")
    _require(sessions[stamp.date()][0].strftime("%H:%M") == "09:15", "ST_SESSION_HISTORY_GAP")
    return bars


def _measure(bars, side, config):
    """Recompute unchanged predicates from the complete validated retained prefix."""
    last, prior = bars[-1], bars[-2]
    closes = [b["close"] for b in bars]
    emas = compute_ema(closes, 200)
    vwap = compute_session_vwap(bars)[-1]
    line, directions = compute_supertrend(bars, period=10, multiplier=3.0)
    atr = max(.05, compute_atr(bars, 10)[-1])
    baseline = sum(b["volume"] for b in bars[-21:-1])/20
    _require(baseline > 0, "ST_VOLUME_BASELINE_UNAVAILABLE")
    hhmm = parse_ist_timestamp(last["timestamp"]).strftime("%H:%M")
    bullish = side == "LONG"
    direction = 1 if bullish else -1
    checks = dict(
        strategy_window=not ("09:15" <= hhmm < "09:45" or "11:30" <= hhmm <= "13:30"),
        supertrend_direction=directions[-1] == direction,
        established_direction=directions[-2] == direction,
        ema200_current=last["close"] > emas[-1] if bullish else last["close"] < emas[-1],
        ema200_prior=prior["close"] > emas[-2] if bullish else prior["close"] < emas[-2],
        vwap=last["close"] > vwap if bullish else last["close"] < vwap,
        touch=(last["low"] <= line[-1]*1.004 or last["low"] <= vwap*1.003) if bullish else
              (last["high"] >= line[-1]*.996 or last["high"] >= vwap*.997),
        directional_close=last["close"] > last["open"] if bullish else last["close"] < last["open"],
        volume=last["volume"] >= 1.3*baseline)
    model = IndianCostModel(**json.loads(config.cost_model_json))
    cost = lambda entry, stop, quantity, direction: model.compute_trade_costs(
        entry, stop, quantity, direction, segment="NSE_EQUITY_INTRADAY", instrument_type="EQ", exchange="NSE")
    signal = evaluate_supertrend_pullback(last["instrument_identity"]["symbol"], bars,
        capital_inr=config.starting_capital_inr, risk_pct=config.risk_pct,
        segment="NSE_EQUITY_INTRADAY", now=parse_ist_timestamp(last["timestamp"])+timedelta(minutes=5),
        execution_costs=cost)
    checks["detector_and_cost_sizing"] = signal is not None and signal.position_type == side+"_EQUITY_INTRADAY"
    entry = round(last["close"], 2)
    stop = round(min(line[-1], last["low"])-.25*atr if bullish else max(line[-1], last["high"])+.25*atr, 2)
    risk = max(.5, entry-stop if bullish else stop-entry)
    sign = 1 if bullish else -1
    # These are measurements only, never replacement levels or a sized position.
    levels = dict(invalidation=round(line[-1], 2), stop_loss=stop,
        target_1=round(entry+sign*1.5*risk, 2), target_2=round(entry+sign*2.5*risk, 2))
    return dict(supertrend10_3=line[-1], prior_supertrend_direction=directions[-2],
        supertrend_direction=directions[-1], ema200=emas[-1], prior_ema200=emas[-2],
        vwap=vwap, atr10=atr, baseline_volume=baseline, rvol=last["volume"]/baseline,
        measured_detector_levels=levels, checks=checks)


def build_contract(store, conn, source_run_id, candidate, config, queued_at):
    """Freeze qualified retained detection and config; no account is created."""
    _require(isinstance(config, PaperAccountConfig), "ST_ACCOUNT_CONFIG_REQUIRED")
    _require(isinstance(candidate, dict) and candidate.get("strategy_id") == STRATEGY
             and candidate.get("segment") == "NSE_EQUITY_INTRADAY", "ST_CASH_CANDIDATE_REQUIRED")
    _require(candidate.get("position_type") in ("LONG_EQUITY_INTRADAY", "SHORT_EQUITY_INTRADAY"), "ST_DIRECTION_REQUIRED")
    _require(candidate.get("provider") == config.provider and candidate.get("data_mode") == config.source_data_mode
             and STRATEGY in config.allowed_strategies, "ST_ACCOUNT_SOURCE_SCOPE_MISMATCH")
    stamp, queued = parse_ist_timestamp(candidate["timestamp"]), parse_ist_timestamp(queued_at)
    bar, reference, work = source_observation(store, conn, source_run_id, candidate, candidate["timestamp"])
    _require(candidate in work["result"].get("signals", []), "ST_RETAINED_CANDIDATE_REQUIRED")
    bars = _prefix(work, candidate, stamp)
    _require(stamp+timedelta(minutes=5) <= parse_ist_timestamp(reference["retrieved_at"]) <= queued
             <= stamp+timedelta(minutes=5, seconds=config.max_mark_age_seconds), "ST_QUEUE_TIME_INVALID")
    _require(queued.date() == stamp.date() and config.session_start_ist <= queued.strftime("%H:%M") < config.square_off_ist
             and stamp.date().isoformat() not in config.configured_holidays, "ST_SESSION_EXPIRED")
    evaluation = load_scan_evaluations(conn, source_run_id)
    _require(isinstance(evaluation, dict), "ST_QUALIFIED_EVALUATION_REQUIRED")
    matches = [q for q in evaluation["candidate_evaluations"] if q.get("candidate_id") == signal_state_identity(candidate)[0]]
    _require(len(matches) == 1, "ST_QUALIFIED_EVALUATION_REQUIRED")
    qualified = matches[0]
    trace = qualified.get("explanation", {}).get("rule_evaluation")
    _require(qualified.get("status") == "QUALIFIED" and qualified.get("ranking", {}).get("qualified") is True
             and isinstance(trace, dict) and trace in evaluation["strategy_evaluations"]
             and trace.get("strategy_id") == STRATEGY and trace.get("status") == "DETECTED", "ST_QUALIFIED_EVALUATION_REQUIRED")
    side = "LONG" if candidate["position_type"] == "LONG_EQUITY_INTRADAY" else "SHORT"
    direction = "bull" if side == "LONG" else "bear"
    checks = {c.get("rule_id"): c for c in trace.get("rule_checks", [])}
    required = ["data.warmup", "session.nse", "session.vwap_start", "session.strategy_window", "volume.baseline",
        "st."+direction+".direction", "st."+direction+".established", "ema."+direction+".current",
        "ema."+direction+".prior", "vwap."+direction, "st."+direction+".pullback", "st."+direction+".candle",
        "volume.surge", "risk.position_size"]
    _require(all(checks.get(key, {}).get("status") == "PASS" for key in required), "ST_DETECTION_CHECKS_REQUIRED")
    for owner in (qualified, trace):
        ref = owner.get("source_reference", {})
        _require(owner.get("symbol") == candidate["symbol"] and owner.get("strategy_id") == STRATEGY
                 and owner.get("data_mode") == candidate["data_mode"] and ref.get("run_id") == source_run_id
                 and ref.get("provider") == config.provider and ref.get("data_mode") == config.source_data_mode
                 and ref.get("instrument_identity") == candidate["instrument_identity"]
                 and ref.get("batch_ids") == [reference["batch_id"]]
                 and ref.get("candle_timestamps", [None])[-1] == candidate["timestamp"], "ST_EVALUATION_SCOPE_MISMATCH")
    _require(round(float(bar["close"]), 2) == candidate["entry_price"], "ST_DECISION_CLOSE_MISMATCH")
    measurements = _measure(bars, side, config)
    _require(all(measurements["checks"].values()), "ST_ORIGINAL_DETECTOR_REQUIRED")
    levels = measurements["measured_detector_levels"]
    _require(candidate["invalidation_level"] == levels["invalidation"] and
             all(candidate[key] == levels[key] for key in ("stop_loss", "target_1", "target_2")), "ST_ORIGINAL_BRACKET_CONFLICT")
    contract = dict(schema_version="tradepulse.supertrend-experiment.v1", rule_id=RULE_ID, actionable=False,
        accepted_fill_policy=False, financial_mutations=False, evidence_scope="EXPERIMENTAL_NO_EMPIRICAL_PROMOTION",
        experimental_hypothesis="LATER_REPEATED_COMPLETE_SUPERTREND_PULLBACK_NEW_ASSUMPTION",
        candidate=copy.deepcopy(candidate), config=json.loads(json.dumps(config.to_dict())), config_hash=config.config_hash,
        side=side, detector_version=_version(), original_run_id=source_run_id, source_reference=reference,
        queued_at_ist=format_ist_timestamp(queued), decision_timestamp_ist=format_ist_timestamp(stamp),
        original_history_digest=digest(bars), original_history_count=len(bars), evaluation_digest=digest(qualified),
        original_measurements=measurements, invalidation=candidate["invalidation_level"], stop_loss=candidate["stop_loss"],
        target_1=candidate["target_1"], target_2=candidate["target_2"],
        invalidation_semantics="ORIGINAL_DETECTION_SUPERTREND_WICK_OR_EQUALITY_GUARD_NO_TRAILING",
        expiry_policy="SAME_SESSION_ACCOUNT_SQUARE_OFF_NO_BAR_TTL",
        fill_assumption="NONE_EVIDENCE_ONLY_OBSERVED_CLOSE_REFERENCE",
        execution_limitations="NO_EXECUTABLE_SPREAD_OR_QUALIFIED_TICK_NO_CAPITAL_OR_EXPOSURE_CHECK")
    contract["contract_digest"] = digest(contract)
    return contract


def _record(store, conn, contract, config, source_run_id, now, history):
    candidate = contract["candidate"]
    _require(source_run_id != contract["original_run_id"], "ST_DISTINCT_FUTURE_RUN_REQUIRED")
    from candle_lineage import load
    work = load(store, source_run_id, connection=conn, read_cache={})
    matches = [b for b in work["snapshot"]["batches"] if b["content"]["identity"] == candidate["instrument_identity"]]
    _require(len(matches) == 1, "ST_SOURCE_IDENTITY_MISMATCH")
    # Select the latest retained candle; an older bar cannot borrow a newer
    # retrieval time, and an unfinished wire tail cannot authorize a trigger.
    supplied = matches[0]["content"]["candles"][-1]
    stamp = parse_ist_timestamp(supplied["timestamp"])
    bar, reference, work = source_observation(store, conn, source_run_id, candidate, supplied["timestamp"])
    bars = _prefix(work, candidate, stamp)
    _require(digest(bars[:contract["original_history_count"]]) == contract["original_history_digest"], "ST_ORIGINAL_HISTORY_CHANGED")
    previous = history[-1] if history else None
    previous_stamp = parse_ist_timestamp(previous["timestamp_ist"] if previous else contract["decision_timestamp_ist"])
    _require(stamp == previous_stamp+timedelta(minutes=5), "ST_OBSERVATION_GAP_OR_ORDER")
    if previous:
        _require(digest(bars[:previous["history_count"]]) == previous["history_digest"], "ST_PRIOR_HISTORY_CHANGED")
    clock, close = parse_ist_timestamp(now), stamp+timedelta(minutes=5)
    _require(close <= parse_ist_timestamp(reference["retrieved_at"]) <= clock
             and close > parse_ist_timestamp(contract["queued_at_ist"])
             and 0 <= (clock-close).total_seconds() <= config.max_mark_age_seconds, "ST_OBSERVATION_TIME_INVALID")
    expired = (stamp.date() != parse_ist_timestamp(contract["decision_timestamp_ist"]).date()
        or clock.date() != stamp.date() or clock.strftime("%H:%M") >= config.square_off_ist
        or stamp.date().isoformat() in config.configured_holidays)
    invalid = bar["low"] <= contract["invalidation"] if contract["side"] == "LONG" else bar["high"] >= contract["invalidation"]
    target = bar["high"] >= contract["target_1"] if contract["side"] == "LONG" else bar["low"] <= contract["target_1"]
    measurements = _measure(bars, contract["side"], config)
    status = ("EXPIRED" if expired else "INVALIDATED" if invalid else "TARGET_ALREADY_REACHED" if target else
              "QUALIFIED_EXPERIMENTAL_TRIGGER" if all(measurements["checks"].values()) else "WAITING")
    return dict(rule_id=RULE_ID, contract_digest=contract["contract_digest"], status=status,
        actionable=False, accepted_fill_policy=False, financial_mutations=False, source_authenticity="NOT_ESTABLISHED",
        source_reference=reference, timestamp_ist=format_ist_timestamp(stamp), observed_at_ist=format_ist_timestamp(clock),
        measurements=measurements, history_digest=digest(bars), history_count=len(bars),
        close_reference=bar["close"], trigger_timestamp_ist=format_ist_timestamp(close) if status == "QUALIFIED_EXPERIMENTAL_TRIGGER" else None)


def evaluate_observation(store, conn, contract, source_run_id, now, history=()):
    """Rebuild frozen evidence and replay history, then observe one later bar.

    Repeated, gapped, forged, stale or reordered observations fail closed.
    Continuation after a terminal result is rejected. No history writes occur.
    """
    _require(isinstance(contract, dict), "ST_CONTRACT_REQUIRED")
    _require(isinstance(history, (list, tuple)) and len(history) < 75, "ST_HISTORY_INVALID")
    config = PaperAccountConfig(**contract["config"])
    expected = build_contract(store, conn, contract["original_run_id"], contract["candidate"], config, contract["queued_at_ist"])
    _require(contract == expected, "ST_CONTRACT_INTEGRITY_FAILURE")
    replay = []
    for retained in history:
        _require(not replay or replay[-1]["status"] == "WAITING", "ST_HISTORY_AFTER_TERMINAL")
        rebuilt = _record(store, conn, contract, config, retained["source_reference"]["run_id"], retained["observed_at_ist"], replay)
        _require(rebuilt == retained, "ST_HISTORY_INTEGRITY_FAILURE")
        replay.append(rebuilt)
    _require(not replay or replay[-1]["status"] == "WAITING", "ST_HISTORY_AFTER_TERMINAL")
    return _record(store, conn, contract, config, source_run_id, now, replay)
