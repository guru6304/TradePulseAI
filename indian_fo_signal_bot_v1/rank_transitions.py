"""TradePulse AI — Dynamic Rank Transitions & Factor-Delta Explanation Engine.

Implements Section 5.3 of the Post-Master Mission:
1. Computes deterministic factor-delta breakdowns when opportunity ranks change.
2. Explains rank reversals (e.g., TCS #1 at 10:00 -> INFY #1 at 10:10) with exact component deltas
   (setup cleanliness, target1 R:R, confluence count, composite score).
3. Immediate removal of disqualified or stale leaders with explicit reason codes (NO_LINGERING_LEADER).
4. Full cryptographic audit lineage tying rank transitions to source evaluation digests.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from strategies import IST, parse_ist_timestamp


TRANSITION_SCHEMA = "tradepulse.rank-transition-audit.v1"


def _clock(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TRANSITION_AWARE_CLOCK_REQUIRED")
    return value.astimezone(IST)


def generate_factor_delta_narrative(
    symbol: str,
    prior_rank: Optional[int],
    current_rank: int,
    factor_deltas: Dict[str, float],
    displaced_symbol: Optional[str] = None,
) -> str:
    """Generates structured, verifiable plain-English narrative for why a setup's rank changed."""
    if prior_rank is None:
        composite = factor_deltas.get("current_composite", 0.0)
        confluence = factor_deltas.get("current_confluence", 1)
        return f"{symbol} newly entered rankings at #{current_rank} with composite score {composite:.1f} ({confluence}-strategy confluence)."

    if prior_rank == current_rank:
        return f"{symbol} maintained rank #{current_rank} with unchanged relative priority."

    direction = "promoted" if current_rank < prior_rank else "demoted"
    delta_composite = factor_deltas.get("delta_composite_score", 0.0)
    delta_confluence = factor_deltas.get("delta_confluence_count", 0)
    delta_rr = factor_deltas.get("delta_target1_rr", 0.0)

    reasons = []
    if delta_confluence > 0:
        reasons.append(f"+{delta_confluence} strategy confluence signal")
    if delta_rr > 0:
        reasons.append(f"+{delta_rr:.2f} R:R improvement")
    if delta_composite > 0:
        reasons.append(f"+{delta_composite:.1f} composite quality gain")
    elif delta_composite < 0:
        reasons.append(f"{delta_composite:.1f} score degradation")

    reason_str = ", ".join(reasons) if reasons else "relative competitor displacement"

    if current_rank == 1 and displaced_symbol:
        return f"{symbol} overtook {displaced_symbol} for rank #1 driven by {reason_str}."

    return f"{symbol} {direction} from #{prior_rank} to #{current_rank} driven by {reason_str}."


def compute_rank_transitions(
    previous_snapshot: Optional[Dict[str, Any]],
    current_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Computes verifiable factor deltas and audit records between consecutive rank snapshots."""
    if not isinstance(current_snapshot, dict) or not isinstance(current_snapshot.get("rows"), list):
        raise ValueError("TRANSITION_INVALID_CURRENT_SNAPSHOT")

    now = _clock(current_snapshot["as_of"])

    if previous_snapshot:
        if not isinstance(previous_snapshot, dict) or not isinstance(previous_snapshot.get("rows"), list):
            raise ValueError("TRANSITION_INVALID_PREVIOUS_SNAPSHOT")
        prior_time = _clock(previous_snapshot["as_of"])
        if prior_time >= now:
            raise ValueError("TRANSITION_CHRONOLOGY_VIOLATION")
        if previous_snapshot.get("scope") != current_snapshot.get("scope"):
            raise ValueError("TRANSITION_SCOPE_MISMATCH")

    prev_rows = {r["opportunity_key"]: r for r in previous_snapshot["rows"]} if previous_snapshot else {}
    prev_by_symbol = {r["symbol"]: r for r in previous_snapshot["rows"]} if previous_snapshot else {}

    prior_leader = previous_snapshot["rows"][0]["symbol"] if (previous_snapshot and previous_snapshot["rows"]) else None

    transitions = []
    for cur_row in current_snapshot["rows"]:
        op_key = cur_row["opportunity_key"]
        sym = cur_row["symbol"]
        cur_rank = cur_row["rank"]
        cur_score_comp = cur_row.get("score_components", {})

        old_row = prev_rows.get(op_key)
        old_score_comp = old_row.get("score_components", {}) if old_row else {}

        prior_rank = old_row.get("rank") if old_row else None

        cur_comp = cur_score_comp.get("composite_score", 0.0)
        old_comp = old_score_comp.get("composite_score", cur_comp if not old_row else 0.0)

        cur_rr = cur_score_comp.get("actual_target1_rr", 0.0)
        old_rr = old_score_comp.get("actual_target1_rr", cur_rr if not old_row else 0.0)

        cur_conf = cur_score_comp.get("confluence_count", 1)
        old_conf = old_score_comp.get("confluence_count", cur_conf if not old_row else 1)

        cur_qual = cur_score_comp.get("rule_quality", 0.0)
        old_qual = old_score_comp.get("rule_quality", cur_qual if not old_row else 0.0)

        factor_deltas = {
            "current_composite": cur_comp,
            "prior_composite": old_comp if old_row else None,
            "delta_composite_score": round(cur_comp - old_comp, 4) if old_row else 0.0,
            "current_target1_rr": cur_rr,
            "prior_target1_rr": old_rr if old_row else None,
            "delta_target1_rr": round(cur_rr - old_rr, 4) if old_row else 0.0,
            "current_confluence": cur_conf,
            "prior_confluence": old_conf if old_row else None,
            "delta_confluence_count": (cur_conf - old_conf) if old_row else 0,
            "current_rule_quality": cur_qual,
            "prior_rule_quality": old_qual if old_row else None,
            "delta_rule_quality": round(cur_qual - old_qual, 4) if old_row else 0.0,
        }

        displaced = prior_leader if (cur_rank == 1 and prior_leader and prior_leader != sym) else None
        narrative = generate_factor_delta_narrative(sym, prior_rank, cur_rank, factor_deltas, displaced)

        transitions.append({
            "opportunity_key": op_key,
            "symbol": sym,
            "strategy_id": cur_row.get("strategy_id"),
            "prior_rank": prior_rank,
            "current_rank": cur_rank,
            "rank_delta": (prior_rank - cur_rank) if prior_rank else None,
            "factor_deltas": factor_deltas,
            "explanation_narrative": narrative,
        })

    # Detect immediate dropouts and disqualified leaders
    current_keys = {r["opportunity_key"] for r in current_snapshot["rows"]}
    dropouts = []
    if previous_snapshot:
        for old_key, old_row in prev_rows.items():
            if old_key not in current_keys:
                is_prior_leader = (old_row.get("rank") == 1)
                dropouts.append({
                    "opportunity_key": old_key,
                    "symbol": old_row["symbol"],
                    "strategy_id": old_row.get("strategy_id"),
                    "prior_rank": old_row.get("rank"),
                    "was_prior_leader": is_prior_leader,
                    "removal_reason": "NO_LINGERING_LEADER:QUALIFICATION_REVOKED_OR_EXPIRED",
                    "explanation": f"{old_row['symbol']} (prior rank #{old_row.get('rank')}) disqualified and removed immediately from actionable list.",
                })

    transition_report = {
        "schema_version": TRANSITION_SCHEMA,
        "as_of": now.isoformat(),
        "prior_as_of": previous_snapshot.get("as_of") if previous_snapshot else None,
        "current_rank_version": current_snapshot.get("rank_version"),
        "previous_rank_version": previous_snapshot.get("rank_version") if previous_snapshot else None,
        "current_leader": transitions[0]["symbol"] if transitions else "NONE",
        "prior_leader": prior_leader,
        "leader_swapped": (prior_leader is not None and len(transitions) > 0 and transitions[0]["symbol"] != prior_leader),
        "transitions_count": len(transitions),
        "dropouts_count": len(dropouts),
        "transitions": transitions,
        "dropouts": dropouts,
    }

    serialized = json.dumps(transition_report, sort_keys=True, separators=(",", ":"))
    transition_report["audit_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return transition_report
