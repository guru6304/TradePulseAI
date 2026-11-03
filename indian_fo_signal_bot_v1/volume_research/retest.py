"""TP-VOL-RETEST-1.0: isolated, future-only impulse/retest experiment.

The immutable state is a research receipt, never a production TradeSignal.
Thresholds follow Stage 1 final spec section 6 and are unvalidated hypotheses.
"""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from .primitives import (
    Bar, SetupContext, ValidationError, D, ceil_tick, floor_tick, clv,
    validate_setup,
)
from .models import (
    CostModel, MarketEvidence, PendingCandidate, make_pending,
    detection_failure_status, digest, validate_admission, validate_future,
)


VERSION = "TP-VOL-RETEST-1.0"
IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class RetestState:
    context: SetupContext
    direction: str
    status: str
    decision_at: datetime
    costs: CostModel | None = None
    reference: Decimal | None = None
    tolerance: Decimal | None = None
    bars_seen: int = 0
    last_bar: Bar | None = None
    last_decision_at: datetime | None = None
    revision: int = 0
    reason_codes: tuple[str, ...] = ()
    pending: PendingCandidate | None = None
    candidate_version: str = VERSION
    actionable: bool = False
    confidence_type: str = "ordinal_quality_not_probability"

    @property
    def config_hash(self):
        return digest(dict(version=VERSION, range_bars=6, rvol_window=20,
            rvol_min="1.8", long_clv_min=".70", short_clv_max=".30",
            retest_window=4, entry_window=3, zone_ticks=2, zone_atr=".20",
            impulse_cutoff_ist="14:20", retest_cutoff_ist="14:40",
            costs=asdict(self.costs) if self.costs is not None else None))

    @property
    def state_id(self):
        bar = self.context.current
        return "volume-retest:" + digest(dict(version=VERSION,
            instrument=bar.instrument_id, source=bar.source,
            candle=bar.candle_id, candle_revision=bar.revision,
            direction=self.direction, decision=self.decision_at,
            config_hash=self.config_hash))

    def to_dict(self):
        impulse = self.context.current
        latest = self.last_bar or impulse
        return dict(schema_version="tradepulse.volume-research-retest.v1",
            state_id=self.state_id, candidate_version=VERSION,
            config_hash=self.config_hash, revision=self.revision,
            direction=self.direction, status=self.status, actionable=False,
            execution_mode="OFFLINE_RESEARCH_ONLY",
            confidence_type="ordinal_quality_not_probability",
            source_authenticity="NOT_ESTABLISHED", source_id=impulse.source,
            instrument_id=impulse.instrument_id,
            completed_candle_id=impulse.candle_id,
            observed_at=latest.observed_at.isoformat(),
            received_at=latest.received_at.isoformat(),
            finalized_at=latest.finalized_at.isoformat(),
            available_at=latest.available_at.isoformat(),
            as_of=latest.end.isoformat(), impulse_candle_end=impulse.end.isoformat(),
            decision_at=self.decision_at.isoformat(),
            last_completed_candle_id=latest.candle_id,
            last_available_at=latest.available_at.isoformat(),
            feature_family="participation", rvol20=str(self.context.rvol.value),
            atr14_prior=str(self.context.atr),
            reference=str(self.reference) if self.reference is not None else None,
            tolerance=str(self.tolerance) if self.tolerance is not None else None,
            retest_bars_observed=self.bars_seen,
            retest_bars_allowed=4, future_entry_bars_allowed=3,
            reason_codes=list(self.reason_codes),
            pending=self.pending.to_dict() if self.pending is not None else None)


def detect_retest(
    ctx: SetupContext,
    direction: str,
    *,
    costs: CostModel,
    market: MarketEvidence,
    enabled: bool = False,
) -> RetestState:
    """Seal an independent R impulse; execution is impossible at this stage."""
    state = RetestState(ctx, direction, "DISABLED", ctx.decision_at, costs=costs,
                        reason_codes=("RESEARCH_DISABLED",))
    if enabled is not True:
        return state
    try:
        validate_setup(ctx)
        validate_admission(costs, market, ctx.decision_at)
        if market.observed_at < ctx.current.end:
            raise ValidationError("STALE_MARKET_EVIDENCE")
        if direction not in ("LONG", "SHORT"):
            raise ValidationError("INVALID_DIRECTION")
        local = ctx.decision_at.astimezone(IST)
        if not time(9, 40) <= local.time() <= time(14, 20):
            raise ValidationError("IMPULSE_CUTOFF")
        if len(ctx.prior) < 6:
            raise ValidationError("INSUFFICIENT_PRICE_HISTORY")
        if ctx.rvol.window != 20 or ctx.rvol.value < D("1.8"):
            raise ValidationError("RVOL_BELOW_THRESHOLD")
        current = ctx.current
        location = clv(current)
        previous = ctx.prior[-6:]
        reference = (max(bar.high for bar in previous) if direction == "LONG"
                     else min(bar.low for bar in previous))
        qualified = (
            current.close >= reference + ctx.tick
            and current.close > current.open and location >= D("0.70")
            if direction == "LONG" else
            current.close <= reference - ctx.tick
            and current.close < current.open and location <= D("0.30")
        )
        if not qualified:
            raise ValidationError("IMPULSE_RULES_NOT_MET")
        tolerance = max(2 * ctx.tick, D("0.20") * ctx.atr)
        return replace(state, status="WAIT_RETEST", reference=reference,
                       tolerance=tolerance, last_decision_at=ctx.decision_at,
                       reason_codes=("IMPULSE_QUALIFIED",))
    except ValidationError as exc:
        return replace(state, status=detection_failure_status(exc.code), reason_codes=(exc.code,))


def advance_retest(
    state: RetestState,
    bar: Bar,
    *,
    decision_at: datetime,
    market: MarketEvidence,
    costs: CostModel,
) -> RetestState:
    """Observe one later complete bar, at most four, then freeze entry geometry.

    A completed close outside the directional K +/- b boundary invalidates the
    impulse immediately. Contraction and sector observations are soft, so no
    volume-contraction, optional stop/ATR or sector veto is introduced here.
    """
    if state.status != "WAIT_RETEST":
        return state
    # Replaying an identical receipt cannot consume an additional pending slot.
    if state.last_bar == bar:
        return state
    try:
        validate_future(state.context, bar, decision_at, state.last_bar,
                        state.last_decision_at or state.decision_at)
        if bar.volume <= 0:
            raise ValidationError("ZERO_TRADED_VOLUME")
        validate_admission(costs, market, decision_at)
        if market.observed_at < bar.end:
            raise ValidationError("STALE_MARKET_EVIDENCE")
        if state.costs is None or costs.quantity != state.costs.quantity:
            raise ValidationError("QUANTITY_CHANGED")
        if decision_at.astimezone(IST).time() > time(14, 40):
            raise ValidationError("RETEST_CUTOFF")
        if (state.reference is None or state.tolerance is None
                or state.direction not in ("LONG", "SHORT")):
            raise ValidationError("INVALID_RETEST_STATE")
        lower = state.reference - state.tolerance
        upper = state.reference + state.tolerance
        invalid = (bar.close < lower if state.direction == "LONG"
                   else bar.close > upper)
        if invalid:
            raise ValidationError("RETEST_STRUCTURE_INVALIDATED")
        count = state.bars_seen + 1
        touched = (lower <= bar.low <= upper and bar.close >= state.reference
                   if state.direction == "LONG" else
                   lower <= bar.high <= upper and bar.close <= state.reference)
        updated = replace(state, bars_seen=count, last_bar=bar,
                          last_decision_at=decision_at, revision=state.revision + 1)
        if touched:
            impulse = state.context.current
            if state.direction == "LONG":
                trigger = ceil_tick(bar.high + state.context.tick, state.context.tick)
                stop = floor_tick(min(impulse.low, bar.low) - state.context.tick,
                                  state.context.tick)
            else:
                trigger = floor_tick(bar.low - state.context.tick, state.context.tick)
                stop = ceil_tick(max(impulse.high, bar.high) + state.context.tick,
                                 state.context.tick)
            pending = make_pending(
                state.context, state.direction, trigger, stop, costs, market,
                decision_at, 3, VERSION,
            )
            pending = replace(pending, decision_bar=bar, last_bar=bar,
                              last_decision_at=decision_at)
            return replace(updated, status="PENDING_R", pending=pending,
                           reason_codes=("RETEST_QUALIFIED_FUTURE_ENTRY_ONLY",))
        if count >= 4:
            return replace(updated, status="EXPIRED",
                           reason_codes=("RETEST_WINDOW_EXPIRED",))
        return replace(updated, reason_codes=("WAITING_FOR_RETEST",))
    except ValidationError as exc:
        return replace(state, status="CANCELLED", last_bar=bar,
                       last_decision_at=decision_at, revision=state.revision + 1,
                       reason_codes=(exc.code,))
