"""TP-VOL-BREAKOUT-1.0, final Stage 1 section 5; isolated and default OFF."""
from datetime import time

from . import BREAKOUT_ENABLED
from .models import Detection, detection_failure_status, local_time, make_pending, require
from .primitives import D, ValidationError, ceil_tick, clv, floor_tick, validate_setup

VERSION = "TP-VOL-BREAKOUT-1.0"


def detect_breakout(ctx, direction, *, costs, market, enabled=BREAKOUT_ENABLED):
    if enabled is not True:
        return Detection("DISABLED", ("RESEARCH_FLAG_OFF",))
    try:
        validate_setup(ctx)
        require(direction in ("LONG", "SHORT"), "INVALID_DIRECTION")
        require(time(9, 40) <= local_time(ctx.decision_at) <= time(14, 40), "SETUP_CUTOFF")
        require(len(ctx.prior) >= 4, "INSUFFICIENT_HISTORY")
        bar, prior, tick = ctx.current, ctx.prior, ctx.tick
        require(ctx.rvol.value >= D("1.8"), "RVOL_BELOW_1_8")
        location = clv(bar)
        if direction == "LONG":
            require(bar.close >= max(b.high for b in prior[-4:])+tick,
                    "FOUR_BAR_BREAKOUT_NOT_CLOSED")
            require(bar.close > bar.open and location >= D("0.70"), "DIRECTION_OR_CLV")
            trigger = ceil_tick(bar.high+tick, tick)
            stop = floor_tick(min(bar.low, prior[-1].low, prior[-2].low)-tick, tick)
        else:
            require(bar.close <= min(b.low for b in prior[-4:])-tick,
                    "FOUR_BAR_BREAKOUT_NOT_CLOSED")
            require(bar.close < bar.open and location <= D("0.30"), "DIRECTION_OR_CLV")
            trigger = floor_tick(bar.low-tick, tick)
            stop = ceil_tick(max(bar.high, prior[-1].high, prior[-2].high)+tick, tick)
        pending = make_pending(ctx, direction, trigger, stop, costs, market,
                               ctx.decision_at, 2, VERSION)
        return Detection("PENDING_B", ("BREAKOUT_QUALIFIED_OFFLINE",), pending)
    except ValidationError as exc:
        return Detection(detection_failure_status(exc.code), (exc.code,))
