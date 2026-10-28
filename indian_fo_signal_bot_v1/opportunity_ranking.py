"""Versioned cash-candidate priority snapshots; never an execution gate.

The existing quality / actual T1 RR ordering is reused. Unobserved sector,
liquidity, friction, relative strength and empirical factors stay unavailable.
The caller must supply a validated retained scan evaluation. rank_history binds
this pure builder to stored scanner inputs; this module alone is not an HTTP
input boundary and does not authenticate market-data provenance.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import math

from strategies import IST, parse_ist_timestamp

POLICY = "CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2"
SCHEMA = "tradepulse.opportunity-ranking.v1"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def _clock(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RANKING_AWARE_CLOCK_REQUIRED")
    return value.astimezone(IST)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def build_snapshot(evaluation, *, provider, as_of, previous=None):
    """An explicit scan-write consumer calls this after existing eligibility gates.

    The snapshot reports candidate priority only. No score, rank or source label
    grants real actionability, qualified research authority or a paper trigger.
    """
    now = _clock(as_of)
    if (not isinstance(evaluation, dict) or evaluation.get("actionable") is not False
            or evaluation.get("data_mode") not in ("LIVE", "SIMULATED")
            or not isinstance(evaluation.get("candidate_evaluations"), list)
            or len(evaluation["candidate_evaluations"]) > 512
            or not isinstance(provider, str) or not provider):
        raise ValueError("RANKING_VALIDATED_SCAN_REQUIRED")
    scope = dict(provider=provider, data_mode=evaluation["data_mode"], segment="NSE_EQUITY_INTRADAY")
    if previous:
        verify_snapshot(previous)
        if previous["scope"] != scope or _clock(previous["as_of"]) > now:
            raise ValueError("RANKING_SCOPE_OR_CHRONOLOGY_CONFLICT")
    candidates, excluded = [], []
    old_rows = {row["opportunity_key"]: row for row in previous["rows"]} if previous else {}
    validated_candidates = []
    for candidate in evaluation["candidate_evaluations"]:
        if not isinstance(candidate, dict):
            raise ValueError("RANKING_INVALID_CANDIDATE")
        reason = None
        reference = candidate.get("source_reference") or {}
        identity = reference.get("instrument_identity") or {}
        quality = (candidate.get("explanation") or {}).get("setup_quality")
        reward = candidate.get("risk_reward") or {}
        ratio = reward.get("gross_t1_rr")
        stamps = reference.get("candle_timestamps") or []
        if candidate.get("status") != "QUALIFIED" or (candidate.get("ranking") or {}).get("qualified") is not True:
            reason = "NOT_QUALIFIED_BY_SCANNER"
        elif (reference.get("provider") != provider or reference.get("data_mode") != scope["data_mode"]
                or reference.get("run_id") != evaluation.get("run_id")):
            reason = "SOURCE_SCOPE_MISMATCH"
        elif (identity.get("instrument_type") != "EQ" or identity.get("exchange") != "NSE"
                or identity.get("is_index") is not False or identity.get("symbol") != candidate.get("symbol")):
            reason = "CASH_IDENTITY_REQUIRED_CONTRACT_RANKING_SEPARATE"
        elif candidate.get("position_type") not in ("LONG_EQUITY_INTRADAY", "SHORT_EQUITY_INTRADAY"):
            reason = "CASH_DIRECTION_REQUIRED"
        elif (type(quality) not in (int, float) or not math.isfinite(quality) or not 0 <= quality <= 100
                or reward.get("allowed") is not True or not _number(ratio)):
            reason = "INVALID_SCORE_OR_RISK_GEOMETRY"
        elif (not isinstance(stamps, list) or not stamps or not isinstance(reference.get("candle_digest"), str)
                or len(reference["candle_digest"]) != 64):
            reason = "SOURCE_WATERMARK_OR_DIGEST_UNAVAILABLE"
        else:
            try:
                watermark = parse_ist_timestamp(stamps[-1])
                close = watermark + timedelta(minutes=5)
                if close > now or now > close + timedelta(seconds=60) or watermark.date() != now.date():
                    reason = "STALE_OR_FUTURE_SOURCE"
            except (ValueError, TypeError, OverflowError):
                reason = "INVALID_SOURCE_WATERMARK"
        if reason:
            excluded.append(dict(candidate_id=candidate.get("candidate_id"), symbol=candidate.get("symbol"), reason_code=reason))
            continue
        validated_candidates.append((candidate, reference, identity, quality, ratio, watermark))

    # Detect multi-strategy confluence per (symbol, direction) before deduplication
    symbol_strategies = {}
    for candidate, _, _, _, _, _ in validated_candidates:
        direction = "LONG" if candidate["position_type"] == "LONG_EQUITY_INTRADAY" else "SHORT"
        group_key = (candidate["symbol"], direction)
        symbol_strategies.setdefault(group_key, set()).add(candidate["strategy_id"])

    for candidate, reference, identity, quality, ratio, watermark in validated_candidates:
        direction = "LONG" if candidate["position_type"] == "LONG_EQUITY_INTRADAY" else "SHORT"
        strat_set = symbol_strategies.get((candidate["symbol"], direction), {candidate["strategy_id"]})
        confluence_count = len(strat_set)
        confluence_strategies = sorted(list(strat_set))
        confluence_multiplier = round(1.0 + 0.15 * (confluence_count - 1), 4)
        composite_score = round(min(100.0, quality * confluence_multiplier), 4)

        key = digest([scope, candidate["symbol"], candidate["strategy_id"], candidate["position_type"], identity])
        score_comp = dict(
            rule_quality=quality,
            actual_target1_rr=ratio,
            confluence_count=confluence_count,
            confluence_strategies=confluence_strategies,
            confluence_multiplier=confluence_multiplier,
            composite_score=composite_score,
        )
        row = dict(opportunity_key=key, candidate_id=candidate["candidate_id"], symbol=candidate["symbol"],
            strategy_id=candidate["strategy_id"], instrument_identity=deepcopy(identity),
            position_type=candidate["position_type"], direction=direction,
            source_data_watermark=watermark.isoformat(), source_digest=reference["candle_digest"],
            score_components=score_comp,
            component_versions=dict(rule_quality="EXISTING_EVALUATOR_V1", actual_target1_rr="PRICE_LEVEL_GEOMETRY_V1",
                confluence="MULTI_STRATEGY_CONFLUENCE_V1"),
            missing_components=["RELATIVE_STRENGTH", "SECTOR", "REGIME", "LIQUIDITY_DEPTH",
                "OBSERVED_SPREAD", "NET_EXECUTABLE_REWARD", "EMPIRICAL_EDGE"],
            priority_scope="QUALIFIED_SCANNER_CANDIDATE_ONLY", actionable=False)
        old = old_rows.get(key)
        if old:
            old_stamp = _clock(old["source_data_watermark"])
            if watermark < old_stamp or (watermark == old_stamp and
                    (row["source_digest"] != old["source_digest"] or row["score_components"] != old["score_components"])):
                raise ValueError("RANKING_SOURCE_REVISION_OR_OUT_OF_ORDER")
        candidates.append(row)
    candidates.sort(key=lambda row: (
        -row["score_components"]["composite_score"],
        -row["score_components"]["rule_quality"],
        -row["score_components"]["actual_target1_rr"],
        row["symbol"],
        row["strategy_id"],
        row["opportunity_key"]
    ))
    rows, symbols = [], set()
    for row in candidates:
        if row["symbol"] in symbols:
            excluded.append(dict(candidate_id=row["candidate_id"], symbol=row["symbol"], reason_code="REDUNDANT_SYMBOL_SETUP"))
            continue
        symbols.add(row["symbol"])
        rows.append(row)
    for rank, row in enumerate(rows, 1):
        old = old_rows.get(row["opportunity_key"])
        row.update(rank=rank, previous_rank=old["rank"] if old else None,
            rank_change_reason=("NEWLY_QUALIFIED" if old is None else "SCORE_COMPONENT_CHANGED"
                if old["score_components"] != row["score_components"] else "RELATIVE_ORDER_CHANGED"
                if old["rank"] != rank else "UNCHANGED_PRIORITY"))
        row["component_changes"] = {name: dict(previous=old["score_components"][name] if old else None, current=value)
            for name, value in row["score_components"].items() if not old or old["score_components"][name] != value}
    current_keys = {row["opportunity_key"] for row in rows}
    removals = [dict(opportunity_key=key, symbol=row["symbol"], previous_rank=row["rank"], new_rank=None,
                     reason_code="NOT_REQUALIFIED_IN_CURRENT_SCAN") for key, row in sorted(old_rows.items()) if key not in current_keys]
    # A version identifies market inputs and priority, independent of request time/run ID.
    version_rows = [{key: row[key] for key in ("opportunity_key", "rank", "source_data_watermark", "source_digest", "score_components")}
                    for row in rows]
    version = digest(dict(policy=POLICY, scope=scope, rows=version_rows))
    until = min((_clock(row["source_data_watermark"]) + timedelta(minutes=5, seconds=60) for row in rows), default=now)
    result = dict(schema_version=SCHEMA, policy=POLICY, scope=scope, run_id=evaluation.get("run_id"),
        as_of=now.isoformat(), valid_until=until.isoformat(), rank_version=version,
        previous_rank_version=previous["rank_version"] if previous else None,
        evaluation_digest=digest(dict(evaluation,
            candidate_evaluations=sorted(evaluation["candidate_evaluations"], key=encoded))), rows=rows,
        exclusions=sorted(excluded, key=encoded), removals=removals,
        actionable=False, evidence_scope="RANKING_MECHANICS_ONLY_NO_EMPIRICAL_OR_LIVE_ACCEPTANCE")
    result["snapshot_sha256"] = digest(result)
    return result


def verify_snapshot(snapshot):
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != SCHEMA
            or snapshot.get("snapshot_sha256") != digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
            or snapshot.get("actionable") is not False):
        raise ValueError("RANK_SNAPSHOT_INTEGRITY_FAILURE")


def current_view(snapshot, as_of):
    """Read-only expiration: archived ranks remain visible but never current."""
    verify_snapshot(snapshot)
    now = _clock(as_of)
    current = _clock(snapshot["as_of"]) <= now <= _clock(snapshot["valid_until"])
    return dict(status="CURRENT_CANDIDATE_PRIORITY" if current else "STALE_OR_FUTURE_SNAPSHOT",
        current_rows=deepcopy(snapshot["rows"]) if current else [], archive=deepcopy(snapshot),
        actionable=False, as_of=now.isoformat())
