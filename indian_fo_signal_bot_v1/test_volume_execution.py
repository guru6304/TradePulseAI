"""Deterministic B and shared execution vectors, all authored synthetic data."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, time, timedelta
import json
import unittest

from test_volume_primitives import make_bar, make_context
from volume_research import BREAKOUT_ENABLED, RETEST_ENABLED
from volume_research.breakout import VERSION, detect_breakout
from volume_research.models import (
    CostModel, MarketEvidence, advance_pending, advance_position, economics,
    make_pending,
)
from volume_research.primitives import D, ValidationError, prepare_setup


def costs_at(at, **overrides):
    values = dict(version="SYNTHETIC_COST_V1", effective_from=date(2020, 1, 1),
        effective_to=date(2030, 1, 1), available_at=at, quantity=1,
        fees_win_inr=D(0), fees_loss_inr=D(0), entry_impact=D(0),
        exit_impact_win=D(0), exit_impact_loss=D(0))
    values.update(overrides)
    return CostModel(**values)


def market_at(at, **overrides):
    values = dict(source_id="SYNTHETIC_LIQUIDITY", observed_at=at, available_at=at,
        liquid=True, trading_permitted=True, exposure="NONE", max_risk_inr=D(1000),
        available_capital_inr=D(10000))
    values.update(overrides)
    return MarketEvidence(**values)


def detect(ctx=None, direction="LONG", **overrides):
    ctx = ctx or make_context()
    arguments = dict(costs=costs_at(ctx.decision_at), market=market_at(ctx.decision_at), enabled=True)
    arguments.update(overrides)
    return detect_breakout(ctx, direction, **arguments)


def mirror(bar):
    return replace(bar, open=D(200)-bar.open, high=D(200)-bar.low,
                   low=D(200)-bar.high, close=D(200)-bar.close)


def short_context():
    ctx = make_context()
    return prepare_setup(mirror(ctx.current), tuple(mirror(b) for b in ctx.prior),
                         ctx.profile, ctx.decision_at)


def future(candidate, *, offset=0, **values):
    start = (candidate.last_bar or candidate.context.current).end + timedelta(minutes=5*offset)
    defaults = dict(open="100.85", high="101.00", low="100.40", close="100.90")
    defaults.update(values)
    return make_bar(start, **defaults)


def step(candidate, bar, **overrides):
    arguments = dict(decision_at=bar.decision_ready_at, costs=costs_at(bar.end), market=market_at(bar.end))
    arguments.update(overrides)
    return advance_pending(candidate, bar, **arguments)


def position_step(position, bar, **overrides):
    arguments = dict(decision_at=bar.decision_ready_at, market=market_at(bar.end))
    arguments.update(overrides)
    return advance_position(position, bar, **arguments)


class TestVolumeBreakoutAndExecution(unittest.TestCase):
    def test_flags_default_off_and_no_core_registration(self):
        self.assertFalse(BREAKOUT_ENABLED)
        self.assertFalse(RETEST_ENABLED)
        ctx = make_context()
        self.assertEqual("DISABLED", detect_breakout(ctx, "LONG", costs=None, market=None).status)
        self.assertEqual("DISABLED", detect(ctx, enabled=1).status)

    def test_stage1_exact_long_geometry_and_future_fill(self):
        candidate = detect().pending
        self.assertEqual(VERSION, candidate.candidate_version)
        self.assertEqual(D("100.85"), candidate.trigger)
        self.assertEqual(D("99.95"), candidate.stop)
        result = step(candidate, future(candidate))
        self.assertEqual("FILLED_RESEARCH", result.status)
        self.assertEqual(D("100.85"), result.position.entry)
        self.assertEqual(D("102.50"), result.position.target)
        self.assertEqual("BAR_BASED_APPROXIMATION", result.position.fill_basis)

    def test_short_mirrored_geometry_and_fill(self):
        candidate = detect(short_context(), "SHORT").pending
        self.assertEqual(D("99.15"), candidate.trigger)
        self.assertEqual(D("100.05"), candidate.stop)
        result = step(candidate, mirror(future(candidate)))
        self.assertEqual("FILLED_RESEARCH", result.status)
        self.assertEqual(D("97.50"), result.position.target)

    def test_exact_decimal_rvol_and_clv_boundaries(self):
        for direction, values in (("LONG", dict(open="100.10", high="101", low="100", close="100.70", volume=1800)),
                                  ("SHORT", dict(open="100.20", high="100.30", low="99.30", close="99.60", volume=1800))):
            ctx = make_context(values=values)
            self.assertEqual("PENDING_B", detect(ctx, direction).status)
        self.assertEqual(("RVOL_BELOW_1_8",), detect(make_context(values=dict(volume=1799))).reason_codes)

    def test_four_prior_range_excludes_current_and_no_vwap_veto(self):
        candidate = detect().pending
        self.assertIsNotNone(candidate)
        ctx = make_context(values=dict(close="100.30"))
        self.assertEqual(("FOUR_BAR_BREAKOUT_NOT_CLOSED",), detect(ctx).reason_codes)

    def test_setup_and_retest_bar_cannot_fill(self):
        candidate = detect().pending
        self.assertEqual(("FUTURE_INTERVAL_REQUIRED",), step(candidate, candidate.context.current).reason_codes)

    def test_b_two_bar_expiry_and_second_bar_trigger(self):
        candidate = detect().pending
        miss = future(candidate, open="100.50", high="100.80", low="100.10", close="100.60")
        first = step(candidate, miss)
        self.assertEqual(1, first.pending.bars_seen)
        self.assertEqual("EXPIRED", step(first.pending, replace(miss, **self.shift(miss))).status)
        self.assertEqual("FILLED_RESEARCH", step(first.pending, future(first.pending)).status)

    @staticmethod
    def shift(bar):
        delta = timedelta(minutes=5)
        return dict(candle_id=bar.candle_id+":next", **{name:getattr(bar, name)+delta
            for name in ("start", "end", "observed_at", "received_at", "finalized_at", "available_at")})

    def test_delayed_setup_skips_only_intervals_started_before_decision(self):
        base = make_context()
        late_bar = replace(base.current, available_at=base.current.end+timedelta(seconds=1))
        ctx = prepare_setup(late_bar, base.prior, base.profile, late_bar.available_at)
        candidate = detect(ctx).pending
        self.assertEqual("NO_FILL", step(candidate, future(candidate)).status)
        full_future = future(candidate, offset=1)
        self.assertEqual("FILLED_RESEARCH", step(candidate, full_future).status)

    def test_delayed_monitor_does_not_skip_next_active_pending_bar(self):
        candidate = detect().pending
        miss = future(candidate, open="100.50", high="100.80", low="100.10", close="100.60")
        delayed = replace(miss, available_at=miss.end+timedelta(seconds=1))
        first = step(candidate, delayed)
        self.assertEqual("PENDING", first.status)
        self.assertEqual("FILLED_RESEARCH", step(first.pending, future(first.pending)).status)

    def test_duplicates_restart_snapshot_and_correction_cannot_reconsume(self):
        candidate = detect().pending
        miss = future(candidate, open="100.50", high="100.80", low="100.10", close="100.60")
        pending = step(candidate, miss).pending
        recovered = replace(pending)  # immutable state can be supplied after restart
        self.assertEqual(pending, step(recovered, miss).pending)
        self.assertEqual(pending.candidate_id, recovered.candidate_id)
        self.assertEqual("NO_FILL", step(recovered, replace(miss, revision=1)).status)

    def test_future_missing_bar_and_source_and_tick_reject(self):
        candidate = detect().pending
        cases = ((future(candidate, offset=1), "MISSING_FUTURE_BAR"),
                 (replace(future(candidate), source="WRONG"), "FUTURE_SOURCE_MISMATCH"),
                 (replace(future(candidate), close="100.911"), "PRICE_OFF_TICK"),
                 (replace(future(candidate), volume=0), "ZERO_TRADED_VOLUME"))
        for bar, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual((reason,), step(candidate, bar).reason_codes)

    def test_gap_boundary_and_adverse_impact_recalculate_target(self):
        candidate = detect().pending
        self.assertEqual(("EXCESSIVE_GAP",), step(candidate,
            future(candidate, open="100.90")).reason_codes)
        result = step(candidate, future(candidate), costs=costs_at(candidate.decision_at, entry_impact=D(".02")))
        self.assertEqual("FILLED_RESEARCH", result.status)
        self.assertEqual(D("100.90"), result.position.entry)
        self.assertEqual(D("102.65"), result.position.target)
        self.assertEqual(candidate.stop, result.position.stop)

    def test_short_adverse_impact_and_gap(self):
        candidate = detect(short_context(), "SHORT").pending
        bar = mirror(future(candidate))
        result = step(candidate, bar, costs=costs_at(bar.end, entry_impact=D(".02")))
        self.assertEqual(D("99.10"), result.position.entry)
        self.assertEqual(D("97.35"), result.position.target)
        self.assertEqual(("EXCESSIVE_GAP",), step(candidate, replace(bar, open="99.10")).reason_codes)

    def test_stop_breach_before_entry_cancels(self):
        candidate = detect().pending
        bar = future(candidate, open="100.10", high="100.50", low="99.90", close="100.20")
        self.assertEqual(("STRUCTURE_INVALIDATED",), step(candidate, bar).reason_codes)

    def test_fill_bar_ambiguous_stop_or_target_abstains(self):
        candidate = detect().pending
        for values in (dict(low="99.90"), dict(high="103")):
            self.assertEqual(("AMBIGUOUS_OHLC",), step(candidate, future(candidate, **values)).reason_codes)

    def test_costs_net_rr_quantity_capital_band_and_exposure_rechecked(self):
        candidate = detect().pending
        bar = future(candidate)
        cases = ((dict(costs=costs_at(bar.end, fees_win_inr=D(1))), "NET_RR_BELOW_1_25"),
                 (dict(costs=costs_at(bar.end, quantity=2)), "QUANTITY_CHANGED"),
                 (dict(market=market_at(bar.end, liquid=False)), "LIQUIDITY_UNAVAILABLE"),
                 (dict(market=market_at(bar.end, max_risk_inr=D(".5"))), "RISK_BUDGET_EXCEEDED"),
                 (dict(market=market_at(bar.end, available_capital_inr=D(100))), "CAPITAL_UNAVAILABLE"),
                 (dict(market=market_at(bar.end, upper_band=D(102))), "PRICE_BAND_UNATTAINABLE"),
                 (dict(market=market_at(bar.end, exposure="DUPLICATE_DIRECTION")), "DUPLICATE_EXPOSURE"),
                 (dict(market=market_at(bar.end, exposure="CONFLICTING_DIRECTION")), "CONFLICTING_DIRECTION"),
                 (dict(market=market_at(bar.end-timedelta(minutes=5))), "STALE_MARKET_EVIDENCE"))
        for kwargs, code in cases:
            with self.subTest(code=code):
                self.assertEqual((code,), step(candidate, bar, **kwargs).reason_codes)

    def test_cost_unavailable_expired_and_invalid_stop(self):
        ctx = make_context()
        self.assertEqual(("COSTS_UNAVAILABLE",), detect(ctx, costs=None).reason_codes)
        self.assertEqual(("COST_SCHEDULE_UNAVAILABLE",), detect(ctx,
            costs=costs_at(ctx.decision_at, effective_to=date(2025,1,1))).reason_codes)
        with self.assertRaises(ValidationError):
            make_pending(ctx, "LONG", D(100), D(100), costs_at(ctx.decision_at),
                         market_at(ctx.decision_at), ctx.decision_at, 2, VERSION)

    def test_tick_rounded_exit_costs_can_turn_net_rr_into_rejection(self):
        for ctx, direction in ((make_context(), "LONG"), (short_context(), "SHORT")):
            candidate = detect(ctx, direction).pending
            bar = future(candidate)
            if direction == "SHORT":
                bar = mirror(bar)
            costs = costs_at(bar.end, fees_win_inr=D(".45"),
                             exit_impact_win=D(".02"), exit_impact_loss=D(".02"))
            result = step(candidate, bar, costs=costs)
            self.assertEqual(("NET_RR_BELOW_1_25",), result.reason_codes)

    def test_stale_setup_liquidity_and_future_costs_are_unavailable(self):
        ctx = make_context()
        self.assertEqual(("STALE_MARKET_EVIDENCE",), detect(ctx,
            market=market_at(ctx.decision_at-timedelta(minutes=5))).reason_codes)
        self.assertEqual(("COSTS_NOT_AVAILABLE",), detect(ctx,
            costs=costs_at(ctx.decision_at+timedelta(seconds=1))).reason_codes)

    def test_setup_and_fill_cutoffs(self):
        ctx = make_context(at=time(14,35))
        candidate = detect(ctx).pending
        self.assertEqual("FILLED_RESEARCH", step(candidate, future(candidate)).status)
        late = future(candidate, offset=1)
        self.assertEqual("NO_FILL", step(candidate, late).status)
        self.assertEqual(("SETUP_CUTOFF",), detect(make_context(at=time(14,40))).reason_codes)
        self.assertEqual(("SETUP_CUTOFF",), detect(make_context(at=time(9,30))).reason_codes)

    def test_later_ambiguous_bar_stop_first_and_gap_loss_adverse(self):
        candidate = detect().pending
        position = step(candidate, future(candidate)).position
        bar = make_bar(position.last_bar.end, open="99.50", high="103", low="99", close="100")
        result = position_step(position, bar)
        self.assertEqual("AMBIGUOUS_OHLC_STOP_FIRST", result.exit.reason)
        self.assertEqual(D("99.50"), result.exit.price)
        self.assertTrue(result.exit.ambiguous)

    def test_short_stop_gap_and_target_tick(self):
        candidate = detect(short_context(), "SHORT").pending
        position = step(candidate, mirror(future(candidate))).position
        bar = make_bar(position.last_bar.end, open="100.50", high="101", low="97", close="100")
        result = position_step(position, bar)
        self.assertEqual(D("100.50"), result.exit.price)
        self.assertTrue(result.exit.ambiguous)

    def test_target_exit_and_impact_not_counted_twice(self):
        candidate = detect().pending
        position = step(candidate, future(candidate), costs=costs_at(candidate.decision_at,
            exit_impact_win=D(".02"))).position
        bar = make_bar(position.last_bar.end, open="101", high="103", low="100.50", close="102")
        result = position_step(position, bar)
        self.assertEqual(D("102.45"), result.exit.price)
        self.assertEqual("TARGET", result.exit.reason)
        _, loss, ratio = economics("LONG", D(100), D(99), D(".05"),
            costs_at(bar.end, quantity=10, fees_win_inr=D(1), fees_loss_inr=D(1),
                     exit_impact_win=D(".1"), exit_impact_loss=D(".1")))
        self.assertEqual(D(12), loss)
        self.assertEqual(D(16)/D(12), ratio)

    def test_twelve_post_fill_bar_time_stop(self):
        candidate = detect().pending
        position = step(candidate, future(candidate)).position
        for count in range(1,13):
            bar = make_bar(position.last_bar.end, open="101", high="101.5", low="100.5", close="101")
            result = position_step(position, bar)
            if count < 12:
                self.assertEqual("OPEN_RESEARCH", result.status)
                position = result.position
            else:
                self.assertEqual("TIME_EXIT_12_BARS", result.exit.reason)

    def test_1515_exit_precedes_twelve_bars(self):
        candidate = detect(make_context(at=time(14,35))).pending
        position = step(candidate, future(candidate)).position
        for _ in range(6):
            bar = make_bar(position.last_bar.end, open="101", high="101.5", low="100.5", close="101")
            result = position_step(position, bar)
            if result.position:
                position = result.position
        self.assertEqual("SESSION_EXIT_1515", result.exit.reason)

    def test_halt_or_missing_bar_retains_open_unfilled_exit(self):
        candidate = detect().pending
        position = step(candidate, future(candidate)).position
        bar = make_bar(position.last_bar.end, open="101", high="101.5", low="100.5", close="101")
        result = position_step(position, bar, market=market_at(bar.end, trading_permitted=False))
        self.assertEqual("UNFILLED_EXIT", result.status)
        self.assertIsNone(result.exit.price)
        self.assertEqual(position, result.position)
        missing = make_bar(bar.end, open="101", high="101.5", low="100.5", close="101")
        self.assertEqual("UNFILLED_EXIT", position_step(position, missing).status)

    def test_candidate_contract_is_nonactionable_finite_and_deterministic(self):
        candidate = detect().pending
        payload = candidate.to_dict()
        json.dumps(payload, allow_nan=False)
        self.assertFalse(payload["actionable"])
        self.assertEqual("ordinal_quality_not_probability", payload["confidence_type"])
        self.assertEqual("NOT_EVALUATED", payload["option_fit"]["status"])
        self.assertIsNone(payload["target"])
        self.assertEqual(candidate.candidate_id, detect().pending.candidate_id)
        with self.assertRaises(FrozenInstanceError):
            candidate.trigger = D(1)


if __name__ == "__main__":
    unittest.main()
