"""Immutable research receipts and conservative OHLC execution approximation.

Fee inputs are explicit caller estimates, not a tax schedule or source licence.
Impact is per share; fees are round-trip INR for the declared integer quantity.
Entry impact is included in entry once; exit impact enters net RR once.
"""
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
from zoneinfo import ZoneInfo

from .primitives import (Bar, D, SetupContext, ValidationError, ceil_tick,
                         floor_tick, validate_future as validate_future_identity)

IST = ZoneInfo("Asia/Kolkata")
TARGET_R = Decimal("1.8")
MIN_NET_RR = Decimal("1.25")
MAX_GAP_ATR = Decimal("0.15")


def require(condition, code):
    if not condition:
        raise ValidationError(code)


def aware(value):
    require(isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None, "AWARE_TIMESTAMP_REQUIRED")
    return value


def local_time(at):
    return aware(at).astimezone(IST).time().replace(tzinfo=None)


@dataclass(frozen=True)
class CostModel:
    version: str
    effective_from: date
    effective_to: date
    available_at: datetime
    quantity: int
    fees_win_inr: Decimal
    fees_loss_inr: Decimal
    entry_impact: Decimal
    exit_impact_win: Decimal
    exit_impact_loss: Decimal
    source: str = "SYNTHETIC_FIXTURE"


@dataclass(frozen=True)
class MarketEvidence:
    source_id: str
    observed_at: datetime
    available_at: datetime
    liquid: bool
    trading_permitted: bool
    exposure: str
    max_risk_inr: Decimal
    available_capital_inr: Decimal
    lower_band: Decimal | None = None
    upper_band: Decimal | None = None


def validate_admission(costs, market, at):
    aware(at)
    require(isinstance(costs, CostModel), "COSTS_UNAVAILABLE")
    require(bool(costs.version) and bool(costs.source), "COSTS_UNAVAILABLE")
    require(type(costs.quantity) is int and costs.quantity > 0, "INVALID_QUANTITY")
    require(type(costs.effective_from) is date and type(costs.effective_to) is date
            and costs.effective_from <= at.astimezone(IST).date() <= costs.effective_to,
            "COST_SCHEDULE_UNAVAILABLE")
    require(aware(costs.available_at) <= at, "COSTS_NOT_AVAILABLE")
    for name in ("fees_win_inr", "fees_loss_inr", "entry_impact",
                 "exit_impact_win", "exit_impact_loss"):
        require(D(getattr(costs, name)) >= 0, "INVALID_COSTS")
    require(isinstance(market, MarketEvidence) and bool(market.source_id),
            "MARKET_EVIDENCE_UNAVAILABLE")
    require(aware(market.observed_at) <= aware(market.available_at) <= at,
            "MARKET_EVIDENCE_NOT_AVAILABLE")
    require(market.liquid is True, "LIQUIDITY_UNAVAILABLE")
    require(market.trading_permitted is True, "TRADING_UNAVAILABLE")
    require(market.exposure == "NONE", "CONFLICTING_DIRECTION" if
            market.exposure == "CONFLICTING_DIRECTION" else "DUPLICATE_EXPOSURE")
    require(D(market.max_risk_inr) > 0 and D(market.available_capital_inr) > 0,
            "RISK_BUDGET_UNAVAILABLE")
    for value in (market.lower_band, market.upper_band):
        if value is not None:
            require(D(value) > 0, "INVALID_PRICE_BAND")
    if market.lower_band is not None and market.upper_band is not None:
        require(D(market.lower_band) < D(market.upper_band), "INVALID_PRICE_BAND")


def _canonical(value):
    if isinstance(value, (Decimal, datetime, date)):
        return str(value)
    raise TypeError(type(value).__name__)


def digest(value):
    return hashlib.sha256(json.dumps(value, default=_canonical, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class PendingCandidate:
    candidate_version: str
    direction: str
    context: SetupContext
    trigger: Decimal
    stop: Decimal
    costs: CostModel
    decision_at: datetime
    ttl: int
    last_bar: Bar | None = None
    bars_seen: int = 0
    revision: int = 0
    last_decision_at: datetime | None = None
    decision_bar: Bar | None = None

    @property
    def candidate_id(self):
        c = self.context
        return "volume-research:" + digest(dict(version=self.candidate_version,
            instrument=c.current.instrument_id, source=c.current.source,
            candle=c.current.candle_id, candle_revision=c.current.revision,
            direction=self.direction, trigger=self.trigger, stop=self.stop,
            decision=self.decision_at, decision_candle=(self.decision_bar or c.current).candle_id,
            config=self.config_hash))

    @property
    def config_hash(self):
        return digest(dict(version=self.candidate_version, ttl=self.ttl,
            target_r=TARGET_R, min_net_rr=MIN_NET_RR, gap_atr=MAX_GAP_ATR,
            range_bars=4 if self.candidate_version == "TP-VOL-BREAKOUT-1.0" else 6,
            rvol_window=20, rvol_min="1.8", long_clv_min="0.70", short_clv_max="0.30",
            retest_width_atr="0.20", retest_width_min_ticks=2, retest_bars=4,
            setup_cutoff="14:40", impulse_cutoff="14:20", fill_cutoff="14:45",
            atr_rule="PRIOR_WILDER14_INCLUDE_OVERNIGHT_GAPS",
            costs=asdict(self.costs), fill="ADVERSE_OHLC_V1",
            time_exit="12_POST_FILL_BARS_OR_1515"))

    def to_dict(self):
        """Proposed research schema, deliberately not the core TradeSignal DTO."""
        c = self.context
        bar = self.decision_bar or c.current
        return dict(schema_version="tradepulse.volume-research-candidate.v1",
            candidate_id=self.candidate_id, candidate_version=self.candidate_version,
            config_hash=self.config_hash, as_of=bar.end.isoformat(),
            setup_candle_end=c.current.end.isoformat(),
            observed_at=bar.observed_at.isoformat(),
            received_at=bar.received_at.isoformat(), finalized_at=bar.finalized_at.isoformat(),
            available_at=bar.available_at.isoformat(),
            decision_at=self.decision_at.isoformat(),
            source_id=c.current.source, instrument_id=c.current.instrument_id,
            instrument_identity=dict(provider=c.profile.instrument.provider,
                identifier=c.profile.instrument.instrument_id,
                symbol=c.profile.instrument.symbol, exchange="NSE",
                segment="NSE_EQUITY_INTRADAY", instrument_type="EQ",
                source=c.profile.instrument.source,
                source_revision=c.profile.instrument.source_revision,
                valid_from=c.profile.instrument.valid_from.isoformat(),
                valid_to=c.profile.instrument.valid_to.isoformat(),
                historical_validity="NOT_ESTABLISHED"),
            completed_candle_id=c.current.candle_id,
            completed_candle_revision=c.current.revision,
            decision_candle_id=bar.candle_id, decision_candle_revision=bar.revision,
            decision_candle_end=bar.end.isoformat(),
            direction=self.direction, status="PENDING_RESEARCH",
            revision=self.revision, bars_observed=self.bars_seen,
            last_observed_candle_id=self.last_bar.candle_id if self.last_bar else None,
            last_observation_available_at=(self.last_bar.available_at.isoformat()
                                          if self.last_bar else None),
            actionable=False, execution_mode="OFFLINE_RESEARCH_ONLY",
            source_authenticity="NOT_ESTABLISHED",
            confidence_type="ordinal_quality_not_probability",
            feature_family="participation", rvol20=str(c.rvol.value),
            atr14_prior=str(c.atr), future_trigger_policy=dict(
                interval_min=5, strictly_future_interval=True, eligible_bars=self.ttl,
                last_new_fill_ist="14:45", trigger=str(self.trigger)),
            structural_stop=str(self.stop), target_r=str(TARGET_R),
            indicative_risk_per_share=str(abs(self.trigger-self.stop)),
            price_unit="INR_PER_SHARE", quantity_unit="SHARES",
            target=None, target_status="REQUIRES_ACTUAL_ASSUMED_FILL",
            cost_model_version=self.costs.version,
            net_cost_estimate=dict(status="CALLER_ESTIMATE_UNVERIFIED",
                fees_win_inr=str(self.costs.fees_win_inr),
                fees_loss_inr=str(self.costs.fees_loss_inr), quantity=self.costs.quantity),
            reason_codes=["OFFLINE_SETUP_QUALIFIED", "EDGE_NOT_ESTABLISHED"],
            option_fit=dict(status="NOT_EVALUATED", contract=None))


@dataclass(frozen=True)
class Detection:
    status: str
    reason_codes: tuple[str, ...]
    pending: PendingCandidate | None = None


def detection_failure_status(code):
    rule_failures = {
        "SETUP_CUTOFF", "IMPULSE_CUTOFF", "RVOL_BELOW_1_8", "RVOL_BELOW_THRESHOLD",
        "FOUR_BAR_BREAKOUT_NOT_CLOSED", "DIRECTION_OR_CLV", "IMPULSE_RULES_NOT_MET",
        "INVALID_STOP", "INVALID_TARGET", "NET_RR_BELOW_1_25", "UNECONOMIC_COSTS",
        "RISK_BUDGET_EXCEEDED", "CAPITAL_UNAVAILABLE", "PRICE_BAND_UNATTAINABLE",
        "CONFLICTING_DIRECTION", "DUPLICATE_EXPOSURE", "INELIGIBLE_UNIVERSE_MEMBER",
    }
    return "REJECTED" if code in rule_failures else "UNAVAILABLE"


def economics(direction, entry, stop, tick, costs):
    entry, stop = D(entry), D(stop)
    require(direction in ("LONG", "SHORT"), "INVALID_DIRECTION")
    risk = entry - stop if direction == "LONG" else stop - entry
    require(entry > 0 and stop > 0 and risk > 0, "INVALID_STOP")
    target = (ceil_tick(entry + TARGET_R * risk, tick) if direction == "LONG"
              else floor_tick(entry - TARGET_R * risk, tick))
    require(target > 0 and (target > entry if direction == "LONG" else target < entry),
            "INVALID_TARGET")
    qty = costs.quantity
    # The economic gate uses the same adverse tick rounding as actual exits.
    stop_exit = (floor_tick(stop-D(costs.exit_impact_loss), tick) if direction == "LONG"
                 else ceil_tick(stop+D(costs.exit_impact_loss), tick))
    target_exit = (floor_tick(target-D(costs.exit_impact_win), tick) if direction == "LONG"
                   else ceil_tick(target+D(costs.exit_impact_win), tick))
    require(stop_exit > 0 and target_exit > 0, "INVALID_EXECUTABLE_EXIT")
    loss = qty * abs(entry-stop_exit) + D(costs.fees_loss_inr)
    reward = target_exit-entry if direction == "LONG" else entry-target_exit
    gain = qty * reward - D(costs.fees_win_inr)
    require(loss > 0 and gain > 0, "UNECONOMIC_COSTS")
    net_rr = gain / loss
    require(net_rr >= MIN_NET_RR, "NET_RR_BELOW_1_25")
    return target, loss, net_rr


def _budget_and_bands(direction, entry, stop, target, risk, costs, market):
    require(risk <= D(market.max_risk_inr), "RISK_BUDGET_EXCEEDED")
    require(costs.quantity * entry + max(D(costs.fees_win_inr), D(costs.fees_loss_inr))
            <= D(market.available_capital_inr), "CAPITAL_UNAVAILABLE")
    for price in (entry, stop, target):
        require((market.lower_band is None or price >= D(market.lower_band))
                and (market.upper_band is None or price <= D(market.upper_band)),
                "PRICE_BAND_UNATTAINABLE")


def make_pending(ctx, direction, trigger, stop, costs, market, decision_at, ttl,
                 candidate_version):
    validate_admission(costs, market, decision_at)
    require(market.observed_at >= ctx.current.end, "STALE_MARKET_EVIDENCE")
    require(direction in ("LONG", "SHORT"), "INVALID_DIRECTION")
    require(type(ttl) is int and ttl in (2, 3), "INVALID_TRIGGER_TTL")
    require(aware(decision_at) >= ctx.decision_at, "DECISION_BEFORE_SETUP")
    trigger, stop = D(trigger), D(stop)
    require(trigger == floor_tick(trigger, ctx.tick) and
            stop == floor_tick(stop, ctx.tick), "OFF_TICK_LEVEL")
    entry = (ceil_tick(trigger + D(costs.entry_impact), ctx.tick) if direction == "LONG"
             else floor_tick(trigger - D(costs.entry_impact), ctx.tick))
    target, risk, _ = economics(direction, entry, stop, ctx.tick, costs)
    _budget_and_bands(direction, entry, stop, target, risk, costs, market)
    return PendingCandidate(candidate_version, direction, ctx, trigger, stop,
                            costs, decision_at, ttl)


def validate_future(context, bar, decision_at, last_bar=None, last_decision_at=None,
                    *, not_before=None):
    """Only full future intervals; delayed publication skips already-started bars.

    A missing interval that *could* have executed is a failure, never skipped.
    This research policy stays in one session and cannot carry an overnight entry.
    """
    previous = last_bar or context.current
    ready = last_decision_at or context.decision_at
    boundary = not_before or context.decision_at
    require(isinstance(bar, Bar), "BAR_UNAVAILABLE")
    require(bar.instrument_id == context.current.instrument_id and
            bar.source == context.current.source, "FUTURE_SOURCE_MISMATCH")
    require(bar.session_date == context.current.session_date, "SESSION_CHANGED")
    validate_future_identity(bar, context, decision_at)
    require(aware(decision_at) >= aware(ready), "NON_MONOTONIC_DECISION")
    require(bar.available_at >= previous.available_at, "NON_MONOTONIC_SOURCE_CLOCK")
    require(bar.start >= boundary and bar.start >= previous.end, "FUTURE_INTERVAL_REQUIRED")
    expected = previous.end
    while expected < boundary:
        expected += timedelta(minutes=5)
    require(bar.start == expected, "MISSING_FUTURE_BAR")


@dataclass(frozen=True)
class Position:
    candidate: PendingCandidate
    entry: Decimal
    stop: Decimal
    target: Decimal
    net_rr: Decimal
    risk_inr: Decimal
    costs: CostModel
    fill_bar: Bar
    fill_decision_at: datetime
    last_bar: Bar
    last_decision_at: datetime
    post_fill_bars: int = 0
    revision: int = 0
    fill_basis: str = "BAR_BASED_APPROXIMATION"


@dataclass(frozen=True)
class Exit:
    position: Position
    price: Decimal | None
    reason: str
    bar_id: str
    available_at: datetime
    ambiguous: bool = False
    status: str = "EXITED_RESEARCH"


@dataclass(frozen=True)
class StepResult:
    status: str
    reason_codes: tuple[str, ...]
    pending: PendingCandidate | None = None
    position: Position | None = None
    exit: Exit | None = None


def advance_pending(candidate, bar, *, decision_at, costs, market):
    """Stateless replay step; terminal results must be retained by the caller.

    Same fill-bar stop or target touches have unknowable ordering: abstain from
    assigning a fill/outcome, rather than selectively assuming a winning path.
    """
    try:
        require(isinstance(candidate, PendingCandidate), "CANDIDATE_REQUIRED")
        if candidate.last_bar == bar:
            return StepResult("PENDING", ("DUPLICATE_OBSERVATION",), pending=candidate)
        validate_future(candidate.context, bar, decision_at, candidate.last_bar,
                        candidate.last_decision_at or candidate.decision_at,
                        not_before=candidate.decision_at)
        require(local_time(bar.end) <= time(14, 45) and
                local_time(decision_at) <= time(14, 45), "ENTRY_CUTOFF")
        validate_admission(costs, market, decision_at)
        require(market.observed_at >= bar.end, "STALE_MARKET_EVIDENCE")
        require(bar.volume > 0, "ZERO_TRADED_VOLUME")
        # A quantity change would silently change the frozen capital hypothesis.
        require(costs.quantity == candidate.costs.quantity, "QUANTITY_CHANGED")
        long = candidate.direction == "LONG"
        crosses = bar.high >= candidate.trigger if long else bar.low <= candidate.trigger
        stops = bar.low <= candidate.stop if long else bar.high >= candidate.stop
        if not crosses:
            require(not stops, "STRUCTURE_INVALIDATED")
            count = candidate.bars_seen + 1
            if count >= candidate.ttl:
                return StepResult("EXPIRED", ("TRIGGER_EXPIRED",))
            return StepResult("PENDING", ("TRIGGER_NOT_CROSSED",), pending=replace(
                candidate, last_bar=bar, last_decision_at=decision_at,
                bars_seen=count, revision=candidate.revision+1))
        gap = max(Decimal(0), bar.open-candidate.trigger if long else candidate.trigger-bar.open)
        require(gap <= MAX_GAP_ATR * candidate.context.atr, "EXCESSIVE_GAP")
        entry = (ceil_tick(max(candidate.trigger, bar.open)+D(costs.entry_impact), candidate.context.tick)
                 if long else floor_tick(min(candidate.trigger, bar.open)-D(costs.entry_impact),
                                         candidate.context.tick))
        require(bar.low <= entry <= bar.high, "IMPACT_PRICE_UNOBSERVED")
        target, risk, net_rr = economics(candidate.direction, entry, candidate.stop,
                                         candidate.context.tick, costs)
        _budget_and_bands(candidate.direction, entry, candidate.stop, target, risk, costs, market)
        target_touch = bar.high >= target if long else bar.low <= target
        require(not stops and not target_touch, "AMBIGUOUS_OHLC")
        position = Position(candidate, entry, candidate.stop, target, net_rr, risk,
            costs, bar, decision_at, bar, decision_at, revision=candidate.revision+1)
        return StepResult("FILLED_RESEARCH", ("BAR_BASED_APPROXIMATION",), position=position)
    except ValidationError as exc:
        return StepResult("NO_FILL", (exc.code,))


def advance_position(position, bar, *, decision_at, market):
    """Adverse stop-first on later ambiguous bars; no fictional exit in a halt."""
    try:
        require(isinstance(position, Position), "POSITION_REQUIRED")
        if position.last_bar == bar:
            return StepResult("OPEN_RESEARCH", ("DUPLICATE_OBSERVATION",), position=position)
        validate_future(position.candidate.context, bar, decision_at,
                        position.last_bar, position.last_decision_at,
                        not_before=position.fill_bar.end)
        require(isinstance(market, MarketEvidence), "MARKET_EVIDENCE_UNAVAILABLE")
        require(aware(market.observed_at) <= aware(market.available_at) <= decision_at
                and market.observed_at >= bar.end, "MARKET_EVIDENCE_NOT_AVAILABLE")
        require(market.liquid is True and market.trading_permitted is True,
                "UNFILLED_EXIT")
        require(bar.volume > 0, "UNFILLED_EXIT")
        require(local_time(bar.end) <= time(15, 15), "MISSED_MANDATORY_EXIT")
        long = position.candidate.direction == "LONG"
        stop_touch = bar.low <= position.stop if long else bar.high >= position.stop
        target_touch = bar.high >= position.target if long else bar.low <= position.target
        count = position.post_fill_bars+1
        reason, raw, impact = None, None, D(position.costs.exit_impact_loss)
        if stop_touch:
            reason = "AMBIGUOUS_OHLC_STOP_FIRST" if target_touch else "STOP"
            raw = min(position.stop, bar.open) if long else max(position.stop, bar.open)
        elif target_touch:
            reason, raw, impact = "TARGET", position.target, D(position.costs.exit_impact_win)
        elif local_time(bar.end) >= time(15, 15):
            require(local_time(bar.end) == time(15, 15), "MISSED_MANDATORY_EXIT")
            reason, raw = "SESSION_EXIT_1515", bar.close
        elif count >= 12:
            reason, raw = "TIME_EXIT_12_BARS", bar.close
        if reason:
            price = (floor_tick(raw-impact, position.candidate.context.tick) if long
                     else ceil_tick(raw+impact, position.candidate.context.tick))
            require(price > 0, "UNFILLED_EXIT")
            exit_receipt = Exit(position, price, reason, bar.candle_id, bar.available_at,
                                stop_touch and target_touch)
            return StepResult("EXITED_RESEARCH", (reason,), exit=exit_receipt)
        return StepResult("OPEN_RESEARCH", ("NO_EXIT",), position=replace(position,
            last_bar=bar, last_decision_at=decision_at, post_fill_bars=count,
            revision=position.revision+1))
    except ValidationError as exc:
        return StepResult("UNFILLED_EXIT", (exc.code,), position=position,
            exit=Exit(position, None, exc.code, getattr(bar, "candle_id", "UNAVAILABLE"),
                      decision_at, status="UNFILLED_EXIT"))
