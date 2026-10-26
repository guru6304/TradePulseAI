"""Prospective ORB paper experiment, separate from the existing detection rule.

This rule is not an empirical strategy promotion. The original completed ORB
breakout remains unchanged. A later completed close must cross the frozen signal
candle extreme; old arbitrary entry prices and other strategies are unsupported.
"""
import hashlib
import inspect
from datetime import timedelta

from candle_lineage import digest, load, load_scan_evaluations
from strategies import evaluate_orb_breakout, format_ist_timestamp, parse_ist_timestamp, signal_state_identity


ORB_FILL_POLICY = "ORB_FOLLOW_THROUGH_CLOSE_V1"
ORB_RULE_ID = "orb.signal_extreme_completed_close_cross.v1"
ORB_STRATEGY = "strat_4_orb_filtered"


def strategy_version():
    return "orb-detection-sha256:" + hashlib.sha256(inspect.getsource(evaluate_orb_breakout).encode()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def source_observation(store, conn, run_id, candidate, stamp):
    """Read and verify the actual committed scanner input, never an HTTP claim."""
    work = load(store, run_id, connection=conn, read_cache={})
    _require(work["status"] == "COMMITTED", "COMMITTED_TRIGGER_SOURCE_REQUIRED")
    matches = [b for b in work["snapshot"]["batches"]
               if b["content"]["identity"] == candidate["instrument_identity"]]
    _require(len(matches) == 1, "TRIGGER_SOURCE_IDENTITY_MISMATCH")
    batch = matches[0]
    bars = [b for b in batch["content"]["candles"]
            if parse_ist_timestamp(b["timestamp"]) == parse_ist_timestamp(stamp)]
    _require(len(bars) == 1, "TRIGGER_SOURCE_OBSERVATION_MISSING")
    return bars[0], dict(run_id=run_id, batch_id=batch["batch_id"],
        work_id=work["snapshot"]["work_id"], snapshot_code_digest=work["snapshot"]["code_digest"],
        observation_digest=digest(bars[0]), retrieved_at=work["snapshot"]["reference"],
        source_authenticity="NOT_ESTABLISHED"), work


def build_contract(store, conn, run_id, candidate, square_off_ist):
    _require(candidate.get("strategy_id") == ORB_STRATEGY, "STRATEGY_FUTURE_TRIGGER_UNAVAILABLE")
    _require(candidate.get("segment") == "NSE_EQUITY_INTRADAY", "UNSUPPORTED_PAPER_CONTRACT")
    bar, reference, work = source_observation(store, conn, run_id, candidate, candidate["timestamp"])
    _require(work["result"].get("signals") and candidate in work["result"]["signals"], "TRIGGER_CANDIDATE_SOURCE_MISMATCH")
    evaluation = load_scan_evaluations(conn, run_id)
    _require(isinstance(evaluation, dict), "RETAINED_TRIGGER_EVALUATION_REQUIRED")
    candidates = [c for c in evaluation["candidate_evaluations"]
                  if c.get("candidate_id") == signal_state_identity(candidate)[0]]
    _require(len(candidates) == 1, "QUALIFIED_TRIGGER_CANDIDATE_REQUIRED")
    qualified = candidates[0]
    _require(qualified.get("status") == "QUALIFIED" and qualified.get("ranking", {}).get("qualified") is True,
             "QUALIFIED_TRIGGER_CANDIDATE_REQUIRED")
    trace = qualified.get("explanation", {}).get("rule_evaluation")
    _require(isinstance(trace, dict) and trace in evaluation["strategy_evaluations"]
             and trace.get("status") == "DETECTED" and trace.get("strategy_id") == ORB_STRATEGY,
             "ORB_DETECTION_EVIDENCE_REQUIRED")
    side = "LONG" if candidate["position_type"] == "LONG_EQUITY_INTRADAY" else "SHORT"
    direction = "bull" if side == "LONG" else "bear"
    checks = {c.get("rule_id"): c for c in trace.get("rule_checks", [])}
    required = ["orb.opening_bars", "orb." + direction + ".prior",
                "orb.bull.breakout" if side == "LONG" else "orb.bear.breakdown",
                "vwap." + direction, "rsi." + direction, "volume.surge", "risk.position_size"]
    _require(all(checks.get(key, {}).get("status") == "PASS" for key in required), "ORB_RULE_CHECKS_REQUIRED")
    _require(round(float(bar["close"]), 2) == candidate["entry_price"], "ORB_DECISION_CLOSE_MISMATCH")
    boundary = checks["orb.bull.breakout" if side == "LONG" else "orb.bear.breakdown"].get("observed", {}).get("threshold")
    _require(boundary is not None and round(float(boundary), 2) == candidate["invalidation_level"],
             "ORB_RANGE_INVALIDATION_MISMATCH")
    _require(qualified["source_reference"].get("batch_ids") == [reference["batch_id"]], "ORB_EVALUATION_BATCH_MISMATCH")
    threshold = float(bar["high"] if side == "LONG" else bar["low"])
    contract = dict(schema_version="tradepulse.paper-trigger.v1", rule_id=ORB_RULE_ID,
        strategy_id=ORB_STRATEGY, strategy_version=strategy_version(), side=side,
        threshold=threshold, invalidation=candidate["invalidation_level"],
        initial_previous_close=float(bar["close"]), decision_timestamp_ist=candidate["timestamp"],
        candidate_digest=digest(candidate), evaluation_digest=digest(qualified), source_reference=reference,
        expiry_policy="SAME_SESSION_ACCOUNT_SQUARE_OFF_NO_BAR_TTL", square_off_ist=square_off_ist,
        fill_policy=ORB_FILL_POLICY, fill_assumption="OBSERVED_COMPLETED_CLOSE_PLUS_CONFIGURED_ADVERSE_COST_MODEL",
        tick_rounding="NOT_MODELED_NO_QUALIFIED_TICK", lot_assumption="CASH_EQUITY_ONE_SHARE",
        evidence_scope="PROSPECTIVE_PAPER_EXPERIMENT_NO_EMPIRICAL_PROMOTION")
    contract["contract_digest"] = digest(contract)
    return contract


def assert_contract(store, conn, decision, config):
    expected = build_contract(store, conn, decision["source_scan_run_id"], decision["candidate"], config.square_off_ist)
    _require(decision.get("trigger_contract") == expected, "PAPER_TRIGGER_CONTRACT_INTEGRITY_FAILURE")
    return expected


def observation_record(store, conn, decision, supplied, source_run_id, now, config):
    contract = assert_contract(store, conn, decision, config)
    candidate = decision["candidate"]
    original, reference, _ = source_observation(store, conn, source_run_id, candidate, supplied["timestamp"])
    for key in ("open", "high", "low", "close", "volume", "instrument_identity", "data_mode", "is_simulated", "is_complete", "interval_min"):
        _require(original.get(key) == supplied.get(key), "TRIGGER_OBSERVATION_SOURCE_CONFLICT")
    prior = decision.get("trigger_evaluations", [])
    last = prior[-1] if prior else None
    stamp = parse_ist_timestamp(original["timestamp"])
    previous_stamp = parse_ist_timestamp(last["timestamp_ist"] if last else candidate["timestamp"])
    _require(stamp == previous_stamp + timedelta(minutes=5), "TRIGGER_OBSERVATION_GAP_OR_ORDER")
    _require(stamp.date() == parse_ist_timestamp(candidate["timestamp"]).date(), "TRIGGER_SESSION_EXPIRED")
    close_time = stamp + timedelta(minutes=5)
    _require(close_time > parse_ist_timestamp(decision["queued_at_ist"]), "TRIGGER_OBSERVATION_PRECEDES_DECISION")
    _require(0 <= (now - close_time).total_seconds() <= config.max_mark_age_seconds, "TRIGGER_OBSERVATION_STALE_OR_FORMING")
    _require(now.strftime("%H:%M") < config.square_off_ist, "TRIGGER_SESSION_EXPIRED")
    _require(len(prior) < 75, "TRIGGER_SESSION_OBSERVATION_BOUND")
    previous_close = float(last["close"] if last else contract["initial_previous_close"])
    threshold = contract["threshold"]
    invalid = (original["low"] <= contract["invalidation"] or original["high"] >= candidate["target_1"]
               if contract["side"] == "LONG" else
               original["high"] >= contract["invalidation"] or original["low"] <= candidate["target_1"])
    crossed = (previous_close <= threshold < original["close"] if contract["side"] == "LONG"
               else previous_close >= threshold > original["close"])
    status = "INVALIDATED" if invalid else "TRIGGERED" if crossed else "WAITING"
    return dict(timestamp_ist=format_ist_timestamp(stamp), close=float(original["close"]),
        previous_close=previous_close, threshold=threshold, status=status,
        reason_code={"INVALIDATED": "SETUP_INVALIDATED_BEFORE_CLOSE_FILL", "TRIGGERED": "ORB_FUTURE_CLOSE_CROSS_CONFIRMED",
                     "WAITING": "ORB_FUTURE_CLOSE_CROSS_NOT_CONFIRMED"}[status],
        source_reference=reference, observation=original,
        observed_at_ist=format_ist_timestamp(now), trigger_timestamp_ist=format_ist_timestamp(close_time) if crossed and not invalid else None)
