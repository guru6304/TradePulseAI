"""Read-only evidence descriptions; never a source, trading or promotion gate.

The five existing evaluators have retained offline mechanics evidence. No accepted
qualified empirical study or reviewed live-paper evidence is supplied here.
Caller scores, synthetic results and external benchmark slogans cannot promote a
strategy. Changes to maturity require a separately reviewed evidence integration.
"""
from copy import deepcopy


SCHEMA_VERSION = "tradepulse.strategy-evidence.v1"
RULE_VERSION = "phase_1c_bidirectional_v1"

_COMMON_REQUIREMENTS = (
    "Qualified completed 5-minute observations with exact instrument identity and source chronology",
    "All current-session bars from 09:15 IST and strategy-specific prior warm-up",
    "Frozen study inputs, source/configuration versions, chronological partitions and modeled costs",
    "Authentic historical originals, approved publisher trust roots and detached matching manifests",
    "Current operator-reviewed research rights and authoritative dated instrument coverage",
)

_STRATEGIES = {
    "strat_1_order_block": dict(
        strategy_name="Order Block + BOS & FVG Retest", min_completed_bars=30,
        entry_rule="COMPLETED_CANDLE_FIRST_RETEST_CONFIRMATION",
        entry_explanation="Order block, break of structure, FVG or displacement, and first unmitigated retest must already pass at the decision candle close.",
        invalidation="Long: order-block low; short: order-block high.",
        stop_rule="Long: zone low minus 0.25 ATR; short: zone high plus 0.25 ATR.",
        target_risk_multipliers=[2.0, 3.0],
        predicates={
            "shared": "Search the last 15 completed bars, newest eligible origin first; ATR(10) floored at 0.05. No minimum RVOL or VWAP directional gate.",
            "long": "Red origin; either of the next two closes above origin high; second impulse low above origin high OR displacement from origin open >= 1.5 ATR. No subsequent close below origin low. No earlier post-impulse low <= origin high * 1.0015. Decision low <= origin high * 1.0015, close > origin open and close >= origin low.",
            "short": "Green origin; either of the next two closes below origin low; second impulse high below origin low OR displacement from origin open >= 1.5 ATR. No subsequent close above origin high. No earlier post-impulse high >= origin low * 0.9985. Decision high >= origin low * 0.9985, close < origin open and close <= origin high.",
            "reuse": "A supplied mitigated-zone set also prevents repeated zone use; zone is consumed after eligible sizing."},
        regime_hypothesis="Continuation after displacement and a first held retest; unvalidated in market data.",
        evaluator="strategies.py:evaluate_order_block_fvg"),
    "strat_2_vwap_pullback": dict(
        strategy_name="Institutional VWAP Pullback + Volume", min_completed_bars=35,
        entry_rule="COMPLETED_CANDLE_VWAP_RECLAIM_OR_REJECTION",
        entry_explanation="VWAP touch and directional close, EMA20 alignment, RVOL at least 1.4, and the existing directional RSI band must pass together.",
        invalidation="Long: lower of decision low and VWAP; short: higher of decision high and VWAP.",
        stop_rule="Invalidation level with a 0.35 ATR adverse buffer.",
        target_risk_multipliers=[1.8, 2.5],
        predicates={
            "long": "Low <= VWAP * 1.0025; close > VWAP and open; close >= EMA20 * 0.998; RVOL >= 1.4; 48 <= RSI14 <= 72.",
            "short": "High >= VWAP * 0.9975; close < VWAP and open; close <= EMA20 * 1.002; RVOL >= 1.4; 28 <= RSI14 <= 52.",
            "volume": "Positive average of the preceding 20 completed bars; current bar excluded."},
        rsi_bands={"long_inclusive": [48.0, 72.0], "short_inclusive": [28.0, 52.0]},
        regime_hypothesis="Volume-supported continuation after a VWAP pullback; unvalidated in market data.",
        evaluator="strategies.py:evaluate_vwap_pullback"),
    "strat_3_option_apex_oi": dict(
        strategy_name="Option Apex OI Shift Trap + PCR", min_completed_bars=1,
        entry_rule="COMPLETED_UNDERLYING_CANDLE_AND_QUALIFIED_OI_CHAIN",
        entry_explanation="Underlying VWAP plus paired ATM OI-change signs and PCR select a long call or a long put. A bearish underlying signal still buys premium.",
        invalidation="Selected option premium stop, not the underlying spot level.",
        stop_rule="0.78 times observed selected premium; target risk floor is INR 1 per unit.",
        target_risk_multipliers=[1.6, 2.4],
        predicates={
            "long_call": "NIFTY/BANKNIFTY only; ATM CE OI change < 0, ATM PE OI change > 0, aggregate PCR >= 1.10 and underlying close >= session VWAP * 0.998.",
            "long_put": "NIFTY/BANKNIFTY only; ATM PE OI change < 0, ATM CE OI change > 0, aggregate PCR <= 0.85 and underlying close <= session VWAP * 1.002.",
            "premium": "Entry reference is selected ATM CE/PE LTP, not an observed executable ask; execution qualification is separate."},
        pcr_thresholds={"long_call_min_inclusive": 1.10, "long_put_max_inclusive": 0.85},
        regime_hypothesis="OI positioning and underlying VWAP agreement; unvalidated in market data.",
        evaluator="strategies.py:evaluate_option_apex_oi_shift",
        additional_requirements=["Exact dated expiry, strike, CE/PE, token, segment, lot and tick identity",
            "Separate contract premium bid/ask/depth observations and prior-session closing OI provenance"],
        warmup_note="Evaluator minimum is one completed bar plus session opening coverage; historical eligibility metadata separately lists 15. Neither implies empirical adequacy.",
        position_semantics="LONG_CALL_OPTION_OR_LONG_PUT_OPTION"),
    "strat_4_orb_filtered": dict(
        strategy_name="15m Opening Range Breakout (ORB) + RVOL", min_completed_bars=30,
        entry_rule="COMPLETED_CLOSE_CROSSING_OPENING_RANGE",
        entry_explanation="Prior close must be on the non-breakout side of the relevant opening-range boundary and the current close strictly beyond it, with VWAP, RSI and RVOL at least 1.6 confirmation. A wick touch is insufficient.",
        invalidation="Long: opening-range high; short: opening-range low.",
        stop_rule="Long: max(ORB low, decision low - 0.25 * ORB range); short: min(ORB high, decision high + 0.25 * ORB range).",
        target_risk_multipliers=[1.6, 2.4],
        predicates={
            "long": "Prior close <= ORB high; close > ORB high and session VWAP; RSI14 >= 55; RVOL >= 1.6.",
            "short": "Prior close >= ORB low; close < ORB low and session VWAP; RSI14 <= 45; RVOL >= 1.6.",
            "opening_range": "High/low of exact 09:15, 09:20 and 09:25 bars. At least four current-session bars and positive prior-20-bar volume baseline."},
        regime_hypothesis="Opening-range expansion with volume confirmation; unvalidated in market data.",
        evaluator="strategies.py:evaluate_orb_breakout",
        additional_requirements=["Exact 09:15, 09:20 and 09:25 opening bars plus at least four current-session bars"]),
    "strat_5_supertrend_pullback": dict(
        strategy_name="Supertrend (10,3) Pullback + 200 EMA", min_completed_bars=200,
        entry_rule="COMPLETED_CANDLE_ESTABLISHED_TREND_PULLBACK",
        entry_explanation="Two consecutive established Supertrend directions, current/prior EMA200 alignment, VWAP, pullback, directional candle and RVOL at least 1.3 must pass outside excluded session windows.",
        invalidation="Decision Supertrend level.",
        stop_rule="Long: lower of Supertrend and decision low minus 0.25 ATR; short: higher of Supertrend and decision high plus 0.25 ATR.",
        target_risk_multipliers=[1.5, 2.5],
        predicates={
            "long": "Current and prior Supertrend(10,3) directions +1; current and prior closes > their EMA200; close > VWAP and open; low <= Supertrend * 1.004 OR low <= VWAP * 1.003; RVOL >= 1.3.",
            "short": "Current and prior Supertrend(10,3) directions -1; current and prior closes < their EMA200; close < VWAP and open; high >= Supertrend * 0.996 OR high >= VWAP * 0.997; RVOL >= 1.3.",
            "session": "Reject candle starts 09:15 <= time < 09:45 and 11:30 <= time <= 13:30 IST; positive prior-20-bar volume baseline."},
        regime_hypothesis="Continuation of an established trend after pullback; unvalidated in market data.",
        evaluator="strategies.py:evaluate_supertrend_pullback",
        additional_requirements=["Excluded candle starts: 09:15 through 09:40 and 11:30 through 13:30 IST"]),
}


def strategy_evidence(strategy_id):
    """Return an independent JSON-safe view without reading data or accepting claims."""
    if not isinstance(strategy_id, str):
        raise ValueError("A strategy identifier string is required.")
    definition = _STRATEGIES.get(strategy_id)
    result = dict(schema_version=SCHEMA_VERSION, strategy_id=strategy_id,
        maturity_state="OFFLINE_MECHANICS_TESTED" if definition else "RESEARCH_HYPOTHESIS",
        empirical_status="EMPIRICAL_VALIDATION_BLOCKED", empirical_performance_claim_allowed=False,
        paper_evidence_status="NOT_ESTABLISHED", out_of_sample_evidence_status="NOT_ESTABLISHED",
        rule_version=RULE_VERSION if definition else None,
        explanation=("Existing evaluator mechanics have offline test evidence. Qualified empirical validation and reviewed live-paper evidence are not established."
            if definition else "This identifier has no registered implemented evaluator evidence; it cannot inherit another strategy's maturity."),
        requirements=list(_COMMON_REQUIREMENTS), supported=definition is not None,
        score_semantics="RULE_SCORE_NOT_WIN_PROBABILITY", benchmark_claim_status="EXTERNAL_PERCENTAGES_NOT_VALIDATED",
        promotion_automatic=False, empirical_metrics=None)
    if definition:
        result.update(deepcopy(definition))
        result["requirements"].extend(result.pop("additional_requirements", []))
        result.update(timeframe_min=5, decision_entry_reference="DECISION_CLOSE_OR_OBSERVED_OPTION_PREMIUM",
            paper_policy_relationship="Detection is not a future fill. Execution requires its own strategy-specific, version-bound later-observation predicate and fill policy; this descriptive registry grants no entry authority.",
            historical_execution="NEXT_CANDLE_OPEN_MODELED_FILL_WITH_CONSERVATIVE_STOP_FIRST",
            evaluator_pending_expiry="NOT_DEFINED_BY_EVALUATOR; execution policy must declare its own strategy-specific expiry",
            evaluator_trailing_stop="NOT_IMPLEMENTED_BY_EVALUATOR",
            target_note="Cash target construction uses max(INR 0.50, entry-stop distance); display numeric risk/reward from actual levels. Targets are levels, not empirical returns.",
            evidence_scope="OFFLINE_SOFTWARE_ONLY")
        if strategy_id == "strat_3_option_apex_oi":
            result["target_note"] = "Premium target construction uses max(INR 1.00, entry-stop distance); both CE and PE positions are long premium."
            result["historical_execution"] = "SEPARATE_QUALIFIED_OPTION_ENGINE_NEXT_ASK_OPEN_LONG_PREMIUM"
    return result
