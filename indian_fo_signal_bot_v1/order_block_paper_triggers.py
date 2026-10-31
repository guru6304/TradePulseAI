"""Isolated first-retest follow-through experiment. Evidence only; no fill policy.

The unchanged detector describes a completed first retest. Requiring subsequent
follow-through after that consumed retest is a NEW experimental assumption. Local
retained-source integrity does not establish publisher authenticity or returns.
All functions read through the caller's transaction and never mutate storage.
"""
import copy
import hashlib
import inspect
import json
from datetime import timedelta

from candle_lineage import digest, load_scan_evaluations
from paper_portfolio import PaperAccountConfig
from paper_triggers import source_observation
from strategies import (compute_atr,
    evaluate_order_block_fvg, format_ist_timestamp, parse_ist_timestamp, signal_state_identity)

RULE_ID = "ob.cash.first_retest_follow_through_close.evidence.v1"
STRATEGY = "strat_1_order_block"


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _version():
    return hashlib.sha256(inspect.getsource(evaluate_order_block_fvg).encode()).hexdigest()


def _prefix(work, candidate, stamp):
    batches = [b for b in work["snapshot"]["batches"]
               if b["content"]["identity"] == candidate["instrument_identity"]]
    _require(len(batches) == 1, "OB_SOURCE_IDENTITY_MISMATCH")
    bars = [b for b in batches[0]["content"]["candles"]
            if parse_ist_timestamp(b["timestamp"]) <= stamp]
    _require(len(bars) >= 30, "OB_WARMUP_REQUIRED")
    _require(parse_ist_timestamp(bars[-1]["timestamp"]) == stamp, "OB_SELECTED_OBSERVATION_MISSING")
    _require(all(b.get("is_complete") is True and b.get("interval_min") == 5 for b in bars), "OB_COMPLETED_INPUT_REQUIRED")
    stamps = [parse_ist_timestamp(b["timestamp"]) for b in bars]
    session = [t for t in stamps if t.date() == stamp.date()]
    _require(session[0].strftime("%H:%M") == "09:15" and
             all(b-a == timedelta(minutes=5) for a, b in zip(session, session[1:])), "OB_SESSION_HISTORY_GAP")
    return bars


def _selected_structure(bars, candidate, checks, side):
    """Freeze the successful origin, never the newest future rolling-window zone."""
    direction = "bull" if side == "LONG" else "bear"
    stamp = checks["ob."+direction+".origin"].get("measurements", {}).get("candidate_timestamp")
    recent = bars[-15:]
    origins = [n for n, bar in enumerate(recent) if bar["timestamp"] == stamp]
    _require(len(origins) == 1 and 1 <= origins[0] <= len(recent)-5, "OB_SELECTED_ORIGIN_REQUIRED")
    index = origins[0]
    origin, imp1, imp2 = recent[index:index+3]
    subsequent = recent[index+3:]
    low, high = float(origin["low"]), float(origin["high"])
    atr = max(.05, compute_atr(bars, 10)[-1])
    if side == "LONG":
        valid = (origin["close"] < origin["open"] and (imp1["close"] > high or imp2["close"] > high)
            and (imp2["low"] > high or imp2["close"]-origin["open"] >= 1.5*atr)
            and not any(b["close"] < low for b in subsequent)
            and not any(b["low"] <= high*1.0015 for b in subsequent[:-1])
            and bars[-1]["low"] <= high*1.0015 and bars[-1]["close"] > origin["open"]
            and bars[-1]["close"] >= low)
    else:
        valid = (origin["close"] > origin["open"] and (imp1["close"] < low or imp2["close"] < low)
            and (imp2["high"] < low or origin["open"]-imp2["close"] >= 1.5*atr)
            and not any(b["close"] > high for b in subsequent)
            and not any(b["high"] >= low*.9985 for b in subsequent[:-1])
            and bars[-1]["high"] >= low*.9985 and bars[-1]["close"] < origin["open"]
            and bars[-1]["close"] <= high)
    _require(valid and candidate["entry_zone_low"] == round(low,2)
             and candidate["entry_zone_high"] == round(high,2)
             and candidate["invalidation_level"] == round(low if side == "LONG" else high,2),
             "OB_SELECTED_STRUCTURE_CONFLICT")
    return dict(origin=copy.deepcopy(origin), impulse_1=copy.deepcopy(imp1), impulse_2=copy.deepcopy(imp2),
                zone_low=low, zone_high=high, detection_atr=atr, first_retest=copy.deepcopy(bars[-1]))


def build_contract(store, conn, source_run_id, candidate, config, queued_at):
    """Return non-actionable frozen evidence contract from qualified retained input.

    ``config`` is an existing PaperAccountConfig; its fill policy is unchanged.
    No paper account need exist. ``queued_at`` is the proposed decision clock.
    """
    _require(isinstance(config, PaperAccountConfig), "OB_ACCOUNT_CONFIG_REQUIRED")
    _require(isinstance(candidate, dict) and candidate.get("strategy_id") == STRATEGY
             and candidate.get("segment") == "NSE_EQUITY_INTRADAY", "OB_CASH_CANDIDATE_REQUIRED")
    _require(candidate.get("position_type") in ("LONG_EQUITY_INTRADAY", "SHORT_EQUITY_INTRADAY"), "OB_DIRECTION_REQUIRED")
    _require(candidate.get("provider") == config.provider and candidate.get("data_mode") == config.source_data_mode
             and STRATEGY in config.allowed_strategies, "OB_ACCOUNT_SOURCE_SCOPE_MISMATCH")
    stamp = parse_ist_timestamp(candidate["timestamp"])
    queued = parse_ist_timestamp(queued_at)
    bar, reference, work = source_observation(store, conn, source_run_id, candidate, candidate["timestamp"])
    _require(candidate in work["result"].get("signals", []), "OB_RETAINED_CANDIDATE_REQUIRED")
    bars = _prefix(work, candidate, stamp)
    _require(stamp + timedelta(minutes=5) <= parse_ist_timestamp(reference["retrieved_at"]) <= queued
             <= stamp + timedelta(minutes=5, seconds=config.max_mark_age_seconds), "OB_QUEUE_TIME_INVALID")
    _require(queued.strftime("%H:%M") < config.square_off_ist and stamp.date().isoformat() not in config.configured_holidays,
             "OB_SESSION_EXPIRED")
    evaluation = load_scan_evaluations(conn, source_run_id)
    matches = [q for q in evaluation["candidate_evaluations"] if q.get("candidate_id") == signal_state_identity(candidate)[0]]
    _require(len(matches) == 1, "OB_QUALIFIED_EVALUATION_REQUIRED")
    qualified = matches[0]
    trace = qualified.get("explanation", {}).get("rule_evaluation")
    _require(qualified.get("status") == "QUALIFIED" and qualified.get("ranking", {}).get("qualified") is True
             and isinstance(trace, dict) and trace in evaluation["strategy_evaluations"]
             and trace.get("strategy_id") == STRATEGY and trace.get("status") == "DETECTED", "OB_QUALIFIED_EVALUATION_REQUIRED")
    side = "LONG" if candidate["position_type"] == "LONG_EQUITY_INTRADAY" else "SHORT"
    direction = "bull" if side == "LONG" else "bear"
    checks = {c.get("rule_id"): c for c in trace.get("rule_checks", [])}
    required = ["ob."+direction+"."+name for name in
                ("origin", "bos", "displacement", "validity", "first_retest", "retest")] + ["risk.position_size"]
    _require(all(checks.get(k, {}).get("status") == "PASS" for k in required), "OB_DETECTION_CHECKS_REQUIRED")
    selected = _selected_structure(bars, candidate, checks, side)
    zone_key = candidate["symbol"]+":OB:"+("BULL" if side == "LONG" else "BEAR")+":"+selected["origin"]["timestamp"]
    _require(zone_key not in work["snapshot"].get("zones", {}).get("NSE_EQUITY_INTRADAY", []),
             "OB_ZONE_ALREADY_MITIGATED_AT_DETECTION")
    for owner in (qualified, trace):
        ref = owner.get("source_reference", {})
        _require(owner.get("symbol") == candidate["symbol"] and owner.get("data_mode") == candidate["data_mode"]
                 and ref.get("run_id") == source_run_id and ref.get("provider") == config.provider
                 and ref.get("instrument_identity") == candidate["instrument_identity"]
                 and ref.get("batch_ids") == [reference["batch_id"]]
                 and ref.get("candle_timestamps", [None])[-1] == candidate["timestamp"], "OB_EVALUATION_SCOPE_MISMATCH")
    _require(round(float(bar["close"]), 2) == candidate["entry_price"], "OB_DECISION_CLOSE_MISMATCH")
    contract = dict(schema_version="tradepulse.order_block-experiment.v1", rule_id=RULE_ID, actionable=False,
        accepted_fill_policy=False, financial_mutations=False, evidence_scope="EXPERIMENTAL_NO_EMPIRICAL_PROMOTION",
        candidate=copy.deepcopy(candidate), config=json.loads(json.dumps(config.to_dict())), config_hash=config.config_hash,
        side=side, detector_version=_version(), selected_structure=selected, zone_key=zone_key,
        mitigation_semantics="ORIGINAL_FIRST_RETEST_CONSUMED_NO_ZONE_RESELECTION",
        threshold=float(bar["high"] if side == "LONG" else bar["low"]), initial_previous_close=float(bar["close"]),
        invalidation_semantics="EXPERIMENTAL_WICK_OR_EQUALITY_GUARD_STRONGER_THAN_DETECTOR_CLOSE_INVALIDATION", original_run_id=source_run_id, source_reference=reference,
        queued_at_ist=format_ist_timestamp(queued), decision_timestamp_ist=format_ist_timestamp(stamp),
        original_history_digest=digest(bars), original_history_count=len(bars), evaluation_digest=digest(qualified),
        invalidation=candidate["invalidation_level"], stop_loss=candidate["stop_loss"],
        target_1=candidate["target_1"], target_2=candidate["target_2"],
        expiry_policy="SAME_SESSION_ACCOUNT_SQUARE_OFF_NO_BAR_TTL",
        fill_assumption="NONE_EVIDENCE_ONLY_OBSERVED_CLOSE_REFERENCE",
        execution_limitations="NO_EXECUTABLE_SPREAD_OR_QUALIFIED_TICK_NO_CAPITAL_OR_EXPOSURE_CHECK")
    contract["contract_digest"] = digest(contract)
    return contract


def _record(store, conn, contract, config, source_run_id, now, history):
    candidate = contract["candidate"]
    _require(source_run_id != contract["original_run_id"], "OB_DISTINCT_FUTURE_RUN_REQUIRED")
    # The latest retained candle is selected; callers cannot nominate an older
    # observation from a future snapshot to borrow later retrieval authority.
    from candle_lineage import load
    work = load(store, source_run_id, connection=conn, read_cache={})
    matches = [b for b in work["snapshot"]["batches"] if b["content"]["identity"] == candidate["instrument_identity"]]
    _require(len(matches) == 1, "OB_SOURCE_IDENTITY_MISMATCH")
    supplied = matches[0]["content"]["candles"][-1]
    stamp = parse_ist_timestamp(supplied["timestamp"])
    bar, reference, work = source_observation(store, conn, source_run_id, candidate, supplied["timestamp"])
    bars = _prefix(work, candidate, stamp)
    count = contract["original_history_count"]
    _require(digest(bars[:count]) == contract["original_history_digest"], "OB_ORIGINAL_HISTORY_CHANGED")
    previous = history[-1] if history else None
    previous_stamp = parse_ist_timestamp(previous["timestamp_ist"] if previous else contract["decision_timestamp_ist"])
    _require(stamp == previous_stamp+timedelta(minutes=5), "OB_OBSERVATION_GAP_OR_ORDER")
    if previous:
        _require(digest(bars[:previous["history_count"]]) == previous["history_digest"], "OB_PRIOR_HISTORY_CHANGED")
    clock = parse_ist_timestamp(now)
    close = stamp+timedelta(minutes=5)
    _require(close <= parse_ist_timestamp(reference["retrieved_at"]) <= clock
             and close > parse_ist_timestamp(contract["queued_at_ist"])
             and 0 <= (clock-close).total_seconds() <= config.max_mark_age_seconds, "OB_OBSERVATION_TIME_INVALID")
    expired = stamp.date() != parse_ist_timestamp(contract["decision_timestamp_ist"]).date() or clock.strftime("%H:%M") >= config.square_off_ist
    invalid = bar["low"] <= contract["invalidation"] if contract["side"] == "LONG" else bar["high"] >= contract["invalidation"]
    target = bar["high"] >= contract["target_1"] if contract["side"] == "LONG" else bar["low"] <= contract["target_1"]
    previous_close = previous["close_reference"] if previous else contract["initial_previous_close"]
    threshold = contract["threshold"]
    crossed = (previous_close <= threshold < bar["close"] if contract["side"] == "LONG" else
               previous_close >= threshold > bar["close"])
    measurements = dict(previous_close=previous_close, threshold=threshold, strict_close_cross=crossed)
    status = ("EXPIRED" if expired else "INVALIDATED" if invalid else "TARGET_ALREADY_REACHED" if target else
              "QUALIFIED_EXPERIMENTAL_TRIGGER" if crossed else "WAITING")
    return dict(rule_id=RULE_ID, contract_digest=contract["contract_digest"], status=status,
        actionable=False, financial_mutations=False, source_authenticity="NOT_ESTABLISHED",
        source_reference=reference, timestamp_ist=format_ist_timestamp(stamp), observed_at_ist=format_ist_timestamp(clock),
        measurements=measurements, history_digest=digest(bars), history_count=len(bars),
        close_reference=bar["close"], trigger_timestamp_ist=format_ist_timestamp(close) if status == "QUALIFIED_EXPERIMENTAL_TRIGGER" else None)


def evaluate_observation(store, conn, contract, source_run_id, now, history=()):
    """Replay evidence, then evaluate latest later committed candle; never fill.

    ``history`` contains prior returned records. Repeats/out-of-order sources,
    forged records and continuation after any terminal status raise ValueError.
    No supplied indicator measurements or prices are accepted as authority.
    """
    _require(isinstance(contract, dict), "OB_CONTRACT_REQUIRED")
    _require(isinstance(history, (list, tuple)) and len(history) < 75, "OB_HISTORY_INVALID")
    config = PaperAccountConfig(**contract["config"])
    expected = build_contract(store, conn, contract["original_run_id"], contract["candidate"], config, contract["queued_at_ist"])
    _require(contract == expected, "OB_CONTRACT_INTEGRITY_FAILURE")
    replay = []
    for retained in history:
        _require(not replay or replay[-1]["status"] == "WAITING", "OB_HISTORY_AFTER_TERMINAL")
        rebuilt = _record(store, conn, contract, config, retained["source_reference"]["run_id"], retained["observed_at_ist"], replay)
        _require(rebuilt == retained, "OB_HISTORY_INTEGRITY_FAILURE")
        replay.append(rebuilt)
    _require(not replay or replay[-1]["status"] == "WAITING", "OB_HISTORY_AFTER_TERMINAL")
    return _record(store, conn, contract, config, source_run_id, now, replay)
