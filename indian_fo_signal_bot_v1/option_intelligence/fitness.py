"""Descriptive exact-contract snapshot research, never a readiness/fill service.

Current spread/friction and premium brackets are estimates under explicit caller
assumptions. They are not actual entry, future bid, P&L or a trading probability.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from . import OPTION_INTELLIGENCE_ENABLED, SCHEMA, VERSION
from .context import inspect_context
from .evidence import (IST, CheckError, Evidence, ceil_tick, day, digest,
                       floor_tick, json_value, number, require, text, timestamp)
from .identity import ExactOptionContract, validate_contract
from .quotes import QuoteMetrics, QuoteResult, inspect_depth, inspect_quote


@dataclass(frozen=True)
class FrictionAssumptions:
    version: str
    source_reference: str
    effective_from: date
    effective_to: date
    available_at: datetime
    entry_impact: Decimal
    exit_impact: Decimal
    round_trip_fees_inr: Decimal
    risk_budget_inr: Decimal
    capital_budget_inr: Decimal
    premium_loss_fraction: Decimal = Decimal(".35")


@dataclass(frozen=True)
class FrictionEstimate:
    assumptions_version: str
    intended_units: int
    ask_plus_impact_estimate: Decimal
    current_bid_minus_impact_estimate: Decimal
    spread_cost_inr: Decimal
    additional_impact_and_rounding_inr: Decimal
    round_trip_fees_inr: Decimal
    snapshot_friction_inr: Decimal
    gross_premium_risk_inr: Decimal
    friction_per_gross_risk: Decimal
    premium_loss_fraction: Decimal
    indicative_premium_stop: Decimal
    indicative_premium_target: Decimal
    projected_stop_bid_after_impact: Decimal
    estimated_loss_inr: Decimal
    indicative_target_net_rr: Decimal
    premium_capital_with_fees_inr: Decimal
    within_declared_risk_budget: bool
    within_declared_capital_budget: bool
    basis: str = "CONSTANT_BOOK_SNAPSHOT_PROXY_AND_HYPOTHETICAL_BID_TARGET"
    source_fee_authority: str = "NOT_ESTABLISHED"
    fill_status: str = "NOT_EXECUTED"


def estimate_friction(contract, quote_result, assumptions, *, decision_at):
    """Quoted spread once, impact once; exact whole-lot units and adverse ticks."""
    try:
        require(isinstance(contract, ExactOptionContract), "UNAVAILABLE", "EXACT_CONTRACT_UNAVAILABLE")
        require(isinstance(quote_result, QuoteResult) and quote_result.evidence.state == "VERIFIED"
                and isinstance(quote_result.metrics, QuoteMetrics),
                "UNAVAILABLE", "VALID_CURRENT_QUOTE_REQUIRED_FOR_FRICTION")
        require(quote_result.metrics.contract_id == contract.contract_id,
                "INVALID", "FRICTION_QUOTE_CONTRACT_MISMATCH")
        require(type(quote_result.metrics.requested_units) is int and
                quote_result.metrics.requested_units > 0 and contract.lot_size > 0 and
                quote_result.metrics.requested_units % contract.lot_size == 0,
                "INVALID", "FRICTION_QUANTITY_NOT_WHOLE_LOTS")
        require(isinstance(assumptions, FrictionAssumptions), "UNAVAILABLE", "COST_ASSUMPTIONS_UNAVAILABLE")
        text(assumptions.version)
        text(assumptions.source_reference)
        decision = timestamp(decision_at)
        require(quote_result.metrics.inspected_at == decision,
                "UNAVAILABLE", "FRICTION_QUOTE_DECISION_MISMATCH")
        require(day(assumptions.effective_from) <= day(assumptions.effective_to),
                "INVALID", "INVALID_COST_VALIDITY")
        require(day(assumptions.effective_from) <= decision.astimezone(IST).date()
                <= day(assumptions.effective_to), "UNAVAILABLE", "DATED_COST_ASSUMPTIONS_UNAVAILABLE")
        require(timestamp(assumptions.available_at) <= decision, "UNAVAILABLE", "COST_ASSUMPTIONS_NOT_AVAILABLE")
        entry_impact, exit_impact, fees = map(number, (assumptions.entry_impact,
            assumptions.exit_impact, assumptions.round_trip_fees_inr))
        require(min(entry_impact, exit_impact, fees) >= 0, "INVALID", "NEGATIVE_COST_ASSUMPTION")
        risk_budget, capital_budget = number(assumptions.risk_budget_inr), number(assumptions.capital_budget_inr)
        require(risk_budget > 0 and capital_budget > 0, "INVALID", "INVALID_SCENARIO_BUDGET")
        loss_fraction = number(assumptions.premium_loss_fraction)
        require(loss_fraction in (Decimal(".25"), Decimal(".35"), Decimal(".45")),
                "INVALID", "UNDECLARED_PREMIUM_LOSS_VARIANT")
        q, tick = quote_result.metrics, contract.tick_size
        entry = ceil_tick(q.ask+entry_impact, tick)
        current_exit = floor_tick(q.bid-exit_impact, tick)
        require(current_exit > 0, "INVALID", "NONPOSITIVE_ESTIMATED_BID_EXIT")
        stop = floor_tick((1-loss_fraction)*entry, tick)
        require(0 < stop < entry, "INVALID", "INVALID_PREMIUM_STOP")
        risk = entry-stop
        target = ceil_tick(entry+Decimal("1.8")*risk, tick)
        stop_exit = floor_tick(stop-exit_impact, tick)
        target_exit = floor_tick(target-exit_impact, tick)
        require(stop_exit > 0 and target_exit > entry, "INVALID", "INVALID_PROJECTED_BID_EXIT")
        units = q.requested_units
        spread_cost = units*q.spread
        added_impact = units*((entry-q.ask)+(q.bid-current_exit))
        friction = spread_cost+added_impact+fees
        gross_risk = units*risk
        estimated_loss = units*(entry-stop_exit)+fees
        target_gain = units*(target_exit-entry)-fees
        require(target_gain > 0, "INVALID", "COSTS_EXCEED_HYPOTHETICAL_TARGET_GAIN")
        capital = units*entry+fees
        value = FrictionEstimate(assumptions.version, units, entry, current_exit,
            spread_cost, added_impact, fees, friction, gross_risk, friction/gross_risk,
            loss_fraction, stop, target, stop_exit, estimated_loss, target_gain/estimated_loss,
            capital, estimated_loss <= risk_budget, capital <= capital_budget)
        return Evidence("VERIFIED", ("SUPPLIED_ASSUMPTION_ARITHMETIC_VALIDATED",
            "FEES_UNVERIFIED", "FUTURE_BID_UNAVAILABLE", "NOT_AN_EXECUTED_FILL_OR_PNL"), value)
    except CheckError as error:
        return Evidence(error.state, (error.code,))


@dataclass(frozen=True)
class AnalysisConfiguration:
    intended_lots: int
    quote_policy: object
    session: object
    assumptions: object
    context_max_age_seconds: object


@dataclass(frozen=True)
class IntelligenceResult:
    status: str
    decision_at: datetime | None
    provenance: str
    contract: object
    identity: Evidence
    quote: object
    depth: Evidence
    context: object
    friction: Evidence
    config_hash: str | None
    configuration: AnalysisConfiguration | None = None
    candidate_version: str = VERSION
    actionable: bool = field(default=False, init=False)
    eligible: bool = field(default=False, init=False)
    execution_allowed: bool = field(default=False, init=False)
    historical_replay_allowed: bool = field(default=False, init=False)
    confidence_type: str = "ordinal_quality_not_probability"

    def to_dict(self):
        value = json_value(self)
        if self.context is not None:
            value["context"] = self.context.to_dict()
        metrics = self.quote.metrics if self.quote is not None else None
        value.update(as_of=metrics.observed_at.isoformat() if metrics is not None else None,
            observed_at=metrics.observed_at.isoformat() if metrics is not None else None,
            received_at=metrics.received_at.isoformat() if metrics is not None else None,
            available_at=metrics.available_at.isoformat() if metrics is not None else None,
            source_id=metrics.source_id if metrics is not None else None,
            underlying_thesis=None, completed_underlying_candle_id=None,
            thesis_status="NOT_CONSUMED_BY_DESCRIPTIVE_SNAPSHOT_CHECKPOINT")
        value.update(schema_version=SCHEMA, calculation_scope="OFFLINE_SUPPLIED_SNAPSHOT_ONLY",
            source_authenticity=dict(state="NOT_ESTABLISHED", reason_codes=["NO_PUBLISHER_ATTESTATION"]),
            listing_authority=dict(state="NOT_ESTABLISHED", reason_codes=["SUPPLIED_MASTER_IS_NOT_AUTHORITY"]),
            historical_option_pnl=dict(state="UNAVAILABLE",
                reason_codes=["BLOCKED_DATA_FOR_HISTORICAL_OPTION_PNL"]),
            execution_boundary=dict(owner="CURSOR_MAIN", status="NOT_IMPLEMENTED_IN_RESEARCH_COMPONENT",
                reason_codes=["QUALIFIED_UNDERLYING_THESIS_AND_FUTURE_EXACT_QUOTE_REQUIRED",
                              "NO_SCANNER_ADMISSION_OR_ENTRY_SERVICE"]),
            strategy_rules_reference=dict(last_new_entry_ist="14:45", mandatory_exit_ist="15:15",
                expiry_day_entries=False, future_revalidation_required=True,
                policy_status="REFERENCE_ONLY_NO_EXECUTION_IMPLEMENTED"),
            option_fit_semantics="DESCRIPTIVE_CONTRACT_AND_FRICTION_RESEARCH_NOT_DIRECTIONAL_ALPHA")
        value["analysis_id"] = "option-intelligence:"+digest(value)
        return value


def analyze_option(contract_record, quote_record, *, decision_at, intended_lots,
                   policy, session, assumptions=None, membership=None,
                   context_record=None, context_max_age_seconds=None, depth_record=None,
                   provenance="UNVERIFIED_CAPTURE", enabled=OPTION_INTELLIGENCE_ENABLED):
    """No external calls. Optional features never establish an underlying thesis."""
    absent = Evidence("UNAVAILABLE", ("NOT_EVALUATED",))
    if enabled is not True:
        return IntelligenceResult("DISABLED", None, provenance, None,
            absent, None, absent, None, absent, None)
    try:
        decision = timestamp(decision_at)
        require(provenance in ("SYNTHETIC_FIXTURE", "UNVERIFIED_CAPTURE"),
                "INVALID", "EXPLICIT_RESEARCH_PROVENANCE_REQUIRED")
        identity = validate_contract(contract_record, decision_at=decision, membership=membership)
        configuration = AnalysisConfiguration(intended_lots, policy, session, assumptions, context_max_age_seconds)
        try:
            config_hash = digest(dict(version=VERSION, intended_lots=intended_lots,
                policy=policy, session=session, assumptions=assumptions,
                context_max_age_seconds=context_max_age_seconds))
        except (TypeError, ValueError):
            raise CheckError("INVALID", "INVALID_RESEARCH_CONFIGURATION") from None
        if identity.evidence.state != "VERIFIED":
            return IntelligenceResult(identity.evidence.state, decision, provenance,
                identity.contract, identity.evidence, None, absent, None, absent, config_hash, configuration)
        contract = identity.contract
        quote = inspect_quote(quote_record, contract, decision_at=decision,
            intended_lots=intended_lots, policy=policy, session=session)
        depth = inspect_depth(depth_record, contract, quote.metrics,
            decision_at=decision, policy=policy)
        context = inspect_context(context_record, contract, decision_at=decision,
            max_age_seconds=context_max_age_seconds)
        friction = estimate_friction(contract, quote, assumptions, decision_at=decision)
        return IntelligenceResult("RESEARCH_SNAPSHOT_ANALYZED", decision, provenance,
            contract, identity.evidence, quote, depth, context, friction, config_hash, configuration)
    except CheckError as error:
        failure = Evidence(error.state, (error.code,))
        return IntelligenceResult(error.state, None, provenance, None,
            failure, None, absent, None, absent, None)
