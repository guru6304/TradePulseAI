"""Supplied quote/depth inspection, not Option Apex prospective admission.

VERIFIED is strictly scoped to numeric, identity, time and declared-unit checks.
Displayed size is a snapshot; it never proves a future fill or real liquidity.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from .evidence import (IST, CheckError, Evidence, ceil_tick, day, number,
                       require, text, timestamp)
from .identity import ExactOptionContract


@dataclass(frozen=True)
class QuotePolicy:
    source_id: str
    evidence_reference: str | None
    available_at: datetime | None
    documented_cadence_seconds: Decimal | None
    timestamp_resolution_seconds: Decimal | None
    max_age_seconds: Decimal = Decimal("3")
    max_leg_skew_seconds: Decimal = Decimal("1")


@dataclass(frozen=True)
class SessionWindow:
    session_date: date
    open_at: datetime
    close_at: datetime
    phase: str
    source_reference: str
    available_at: datetime


@dataclass(frozen=True)
class QuoteMetrics:
    quote_id: str
    contract_id: str
    source_id: str
    observed_at: datetime
    bid_at: datetime
    ask_at: datetime
    received_at: datetime
    available_at: datetime
    bid: Decimal
    ask: Decimal
    bid_units: int
    ask_units: int
    requested_units: int
    age_seconds: Decimal
    leg_skew_seconds: Decimal
    mid: Decimal
    spread: Decimal
    relative_spread: Decimal
    displayed_size_ratio: Decimal
    pilot_spread_limit: Decimal
    within_pilot_spread: bool
    inspected_at: datetime
    fillability: str = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class QuoteResult:
    evidence: Evidence
    metrics: QuoteMetrics | None = None


def _field(record, key):
    require(key in record and record[key] is not None, "UNAVAILABLE", key.upper()+"_UNAVAILABLE")
    return record[key]


def requested_units(lots, contract):
    require(type(lots) is int and 0 < lots <= 1000000, "INVALID", "INVALID_LOT_COUNT")
    require(isinstance(contract, ExactOptionContract), "UNAVAILABLE", "EXACT_CONTRACT_UNAVAILABLE")
    return lots * contract.lot_size


def quantity_units(raw, unit, contract):
    value = number(raw)
    require(value >= 0 and value == value.to_integral_value(), "INVALID", "INVALID_QUOTE_SIZE")
    require(unit in ("UNDERLYING_UNITS", "CONTRACTS"), "NOT_ESTABLISHED", "QUANTITY_UNIT_NOT_ESTABLISHED")
    return int(value) * (contract.lot_size if unit == "CONTRACTS" else 1)


def policy_bounds(policy, decision):
    require(isinstance(policy, QuotePolicy), "NOT_ESTABLISHED", "QUOTE_CADENCE_POLICY_NOT_ESTABLISHED")
    text(policy.source_id)
    # The baseline is a declared pilot, not a universal freshness guarantee.
    age, skew = number(policy.max_age_seconds), number(policy.max_leg_skew_seconds)
    require(0 < age <= 3 and 0 <= skew <= age, "INVALID", "INVALID_PILOT_FRESHNESS_POLICY")
    require(policy.evidence_reference is not None and policy.available_at is not None
            and policy.documented_cadence_seconds is not None
            and policy.timestamp_resolution_seconds is not None,
            "NOT_ESTABLISHED", "QUOTE_CADENCE_OR_CLOCK_EVIDENCE_NOT_ESTABLISHED")
    text(policy.evidence_reference)
    require(timestamp(policy.available_at) <= decision, "UNAVAILABLE", "POLICY_NOT_YET_AVAILABLE")
    cadence, resolution = number(policy.documented_cadence_seconds), number(policy.timestamp_resolution_seconds)
    require(0 < cadence <= age and 0 < resolution <= age,
            "NOT_ESTABLISHED", "QUOTE_CADENCE_OR_CLOCK_UNSUPPORTED")
    require(resolution <= skew, "NOT_ESTABLISHED", "LEG_ALIGNMENT_PRECISION_UNSUPPORTED")
    return age, skew


def validate_session(session, decision):
    require(isinstance(session, SessionWindow), "NOT_ESTABLISHED", "SESSION_CALENDAR_NOT_ESTABLISHED")
    text(session.source_reference)
    require(timestamp(session.available_at) <= decision, "UNAVAILABLE", "CALENDAR_NOT_YET_AVAILABLE")
    today = decision.astimezone(IST).date()
    require(day(session.session_date) == today, "INVALID", "SESSION_DATE_MISMATCH")
    require(session.phase in ("NORMAL", "CLOSED", "SPECIAL"), "INVALID", "INVALID_SESSION_PHASE")
    require(session.phase != "CLOSED", "UNAVAILABLE", "CLOSED_SESSION")
    require(session.phase == "NORMAL", "NOT_ESTABLISHED", "SPECIAL_SESSION_POLICY_NOT_ESTABLISHED")
    opening, closing = timestamp(session.open_at), timestamp(session.close_at)
    require(opening.astimezone(IST).date() == closing.astimezone(IST).date() == today
            and opening.astimezone(IST).time() == time(9, 15)
            and closing.astimezone(IST).time() == time(15, 30), "INVALID", "INVALID_NORMAL_SESSION")
    require(opening <= decision <= closing, "UNAVAILABLE", "OUTSIDE_DECLARED_SESSION")
    return opening, closing


def validate_envelope(record, contract, decision, policy):
    require(isinstance(record, dict), "INVALID", "INVALID_QUOTE_RECORD")
    require(_field(record, "contract_id") == contract.contract_id
            and _field(record, "provider") == contract.provider
            and _field(record, "source_revision") == contract.source_revision,
            "INVALID", "QUOTE_CONTRACT_IDENTITY_MISMATCH")
    require(_field(record, "source_id") == policy.source_id, "INVALID", "QUOTE_SOURCE_MISMATCH")
    observed, received, available = (timestamp(_field(record, key))
        for key in ("observed_at", "received_at", "available_at"))
    require(observed <= received <= available, "INVALID", "INVALID_QUOTE_CLOCK_ORDER")
    require(available <= decision, "UNAVAILABLE", "QUOTE_NOT_YET_AVAILABLE")
    require(observed.astimezone(IST).date() == decision.astimezone(IST).date(),
            "STALE", "QUOTE_SESSION_STALE")
    return observed, received, available


def inspect_quote(record, contract, *, decision_at, intended_lots, policy, session):
    """Inspect a current supplied book. No LTP/spot fallback and no future fill."""
    try:
        decision = timestamp(decision_at)
        units = requested_units(intended_lots, contract)
        age_limit, skew_limit = policy_bounds(policy, decision)
        opening, _ = validate_session(session, decision)
        observed, received, available = validate_envelope(record, contract, decision, policy)
        bid, ask = number(_field(record, "bid")), number(_field(record, "ask"))
        require(0 < bid <= ask, "INVALID", "NONPOSITIVE_OR_CROSSED_BOOK")
        require(bid < ask, "INVALID", "LOCKED_BOOK_EXCLUDED_BY_RESEARCH_POLICY")
        require(bid == ceil_tick(bid, contract.tick_size) and ask == ceil_tick(ask, contract.tick_size),
                "INVALID", "QUOTE_PRICE_OFF_TICK")
        require(_field(record, "price_unit") == "INR", "INVALID", "QUOTE_PRICE_UNIT_MISMATCH")
        unit = _field(record, "quantity_unit")
        bid_units = quantity_units(_field(record, "bid_size"), unit, contract)
        ask_units = quantity_units(_field(record, "ask_size"), unit, contract)
        bid_at, ask_at = timestamp(_field(record, "bid_at")), timestamp(_field(record, "ask_at"))
        require(opening <= min(bid_at, ask_at) <= max(bid_at, ask_at) <= observed,
                "INVALID", "INVALID_QUOTE_LEG_CLOCK")
        age = number(str((decision-min(bid_at, ask_at)).total_seconds()))
        skew = number(str(abs((bid_at-ask_at).total_seconds())))
        require(age <= age_limit, "STALE", "QUOTE_TOO_OLD")
        require(skew <= skew_limit, "STALE", "QUOTE_LEGS_NOT_SYNCHRONIZED")
        spread, mid = ask-bid, (ask+bid)/2
        limit = Decimal(".01") if contract.instrument_type == "OPTIDX" else Decimal(".02")
        metrics = QuoteMetrics(text(_field(record, "quote_id")), contract.contract_id,
            policy.source_id, observed, bid_at, ask_at, received, available,
            bid, ask, bid_units, ask_units, units, age, skew, mid, spread,
            spread/mid, Decimal(min(bid_units, ask_units))/units, limit, spread/mid <= limit, decision)
        if min(bid_units, ask_units) < units:
            return QuoteResult(Evidence("UNAVAILABLE", ("INSUFFICIENT_DISPLAYED_SIZE",)), metrics)
        return QuoteResult(Evidence("VERIFIED", ("SUPPLIED_QUOTE_CHECKS_PASSED",
            "PILOT_SPREAD_COMPARISON_NOT_VALIDATED", "FUTURE_FILLABILITY_NOT_ESTABLISHED")), metrics)
    except CheckError as error:
        return QuoteResult(Evidence(error.state, (error.code,)))


@dataclass(frozen=True)
class DepthMetrics:
    bid_levels: tuple
    ask_levels: tuple
    bid_total_units: int
    ask_total_units: int
    requested_units: int
    bid_displayed_coverage: bool
    ask_displayed_coverage: bool
    execution_guarantee: str = "NOT_ESTABLISHED"


def inspect_depth(record, contract, quote, *, decision_at, policy):
    """Optional displayed-depth context; deeper quantity never replaces L1 size."""
    if record is None:
        return Evidence("UNAVAILABLE", ("DEPTH_NOT_SUPPLIED",))
    try:
        require(isinstance(quote, QuoteMetrics), "UNAVAILABLE", "CURRENT_QUOTE_UNAVAILABLE_FOR_DEPTH")
        decision = timestamp(decision_at)
        require(quote.contract_id == contract.contract_id, "INVALID", "DEPTH_QUOTE_CONTRACT_MISMATCH")
        require(quote.inspected_at == decision, "UNAVAILABLE", "DEPTH_QUOTE_DECISION_MISMATCH")
        age, skew = policy_bounds(policy, decision)
        observed, _, _ = validate_envelope(record, contract, decision, policy)
        require(0 <= (decision-observed).total_seconds() <= age, "STALE", "DEPTH_TOO_OLD")
        require(abs((quote.observed_at-observed).total_seconds()) <= skew,
                "STALE", "DEPTH_QUOTE_NOT_ALIGNED")
        require(_field(record, "price_unit") == "INR", "INVALID", "DEPTH_PRICE_UNIT_MISMATCH")
        unit = _field(record, "quantity_unit")
        parsed = []
        for name, descending in (("bids", True), ("asks", False)):
            rows = _field(record, name)
            require(isinstance(rows, (tuple, list)) and 1 <= len(rows) <= 30,
                    "INVALID", "INVALID_DEPTH_LEVELS")
            side = []
            for row in rows:
                require(isinstance(row, dict) and set(row) == {"price", "quantity"},
                        "INVALID", "INVALID_DEPTH_LEVEL")
                price = number(row["price"])
                require(price > 0 and price == ceil_tick(price, contract.tick_size),
                        "INVALID", "DEPTH_PRICE_OFF_TICK")
                size = quantity_units(row["quantity"], unit, contract)
                if side:
                    require(price < side[-1][0] if descending else price > side[-1][0],
                            "INVALID", "UNSORTED_OR_DUPLICATE_DEPTH")
                side.append((price, size))
            parsed.append(tuple(side))
        bids, asks = parsed
        require(bids[0][0] < asks[0][0], "INVALID", "CROSSED_OR_LOCKED_DEPTH")
        require(bids[0] == (quote.bid, quote.bid_units) and asks[0] == (quote.ask, quote.ask_units),
                "INVALID", "DEPTH_TOP_QUOTE_MISMATCH")
        bid_total, ask_total = sum(q for _,q in bids), sum(q for _,q in asks)
        return Evidence("VERIFIED", ("SUPPLIED_DISPLAYED_DEPTH_VALIDATED",
            "DISPLAYED_QUANTITY_IS_NOT_EXECUTED_FLOW"), DepthMetrics(bids, asks,
                bid_total, ask_total, quote.requested_units,
                bid_total >= quote.requested_units, ask_total >= quote.requested_units))
    except CheckError as error:
        return Evidence(error.state, (error.code,))
