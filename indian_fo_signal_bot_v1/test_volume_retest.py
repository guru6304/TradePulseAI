"""Synthetic section 6 vectors, independent of production scanner and stores."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta
import unittest

from test_volume_primitives import make_bar, make_context
from volume_research.models import CostModel, MarketEvidence, advance_pending
from volume_research.primitives import D, IST, prepare_setup
from volume_research.retest import advance_retest, detect_retest


def costs_at(at, **changes):
    values = dict(version="SYNTHETIC_ZERO_FEE_V1", effective_from=date(2026, 1, 1),
                  effective_to=date(2026, 12, 31), available_at=at,
                  quantity=1, fees_win_inr=D(0), fees_loss_inr=D(0),
                  entry_impact=D(0), exit_impact_win=D(0), exit_impact_loss=D(0))
    values.update(changes)
    return CostModel(**values)


def market_at(at, **changes):
    values = dict(source_id="AUTHORED_SYNTHETIC", observed_at=at,
                  available_at=at, liquid=True, trading_permitted=True,
                  exposure="NONE", max_risk_inr=D(100),
                  available_capital_inr=D(10000))
    values.update(changes)
    return MarketEvidence(**values)


def reflect(bar):
    return replace(bar, open=D(200) - bar.open, high=D(200) - bar.low,
                   low=D(200) - bar.high, close=D(200) - bar.close)


def short_context():
    ctx = make_context()
    return prepare_setup(reflect(ctx.current), tuple(reflect(b) for b in ctx.prior),
                         replace(ctx.profile, history=tuple(reflect(b) for b in ctx.profile.history)),
                         ctx.decision_at)


class TestVolumeRetest(unittest.TestCase):
    def detection(self, ctx=None, direction="LONG", **changes):
        ctx = ctx or make_context()
        costs = costs_at(ctx.decision_at)
        market = market_at(ctx.decision_at)
        return detect_retest(ctx, direction, costs=costs, market=market,
                             enabled=True, **changes)

    def step(self, state, bar, **changes):
        at = changes.pop("decision_at", bar.decision_ready_at)
        costs = changes.pop("costs", state.costs)
        market = changes.pop("market", market_at(at))
        return advance_retest(state, bar, decision_at=at,
                              costs=costs, market=market, **changes)

    def retest_bar(self, state, *, slot=0, **changes):
        values = dict(open="100.60", high="100.90", low="100.25",
                      close="100.50", volume="3000")
        values.update(changes)
        bar = make_bar(state.context.current.end + timedelta(minutes=5 * slot), **values)
        return reflect(bar) if state.direction == "SHORT" else bar

    def non_retest_bar(self, state, slot):
        bar = make_bar(state.context.current.end + timedelta(minutes=5 * slot),
                       open="100.70", high="100.90", low="100.50", close="100.75")
        return reflect(bar) if state.direction == "SHORT" else bar

    def test_disabled_by_default_and_only_boolean_true_enables(self):
        ctx = make_context()
        for enabled in (False, 1, "true", None):
            result = detect_retest(ctx, "LONG", costs=costs_at(ctx.decision_at),
                                   market=market_at(ctx.decision_at), enabled=enabled)
            self.assertEqual("DISABLED", result.status)
            self.assertIsNone(result.pending)

    def test_exact_long_impulse_reference_and_width(self):
        result = self.detection()
        self.assertEqual("WAIT_RETEST", result.status)
        self.assertEqual(D("100.30"), result.reference)
        self.assertEqual(D(".10"), result.tolerance)
        self.assertFalse(result.actionable)
        self.assertIsNone(result.pending)

    def test_serialized_state_preserves_impulse_retest_and_version_provenance(self):
        import json
        state = self.detection()
        original = state.to_dict()
        bar = self.retest_bar(state)
        result = self.step(state, bar)
        receipt = result.to_dict()
        self.assertEqual(original["state_id"], receipt["state_id"])
        self.assertEqual(original["config_hash"], receipt["config_hash"])
        self.assertEqual("TP-VOL-RETEST-1.0", receipt["candidate_version"])
        self.assertEqual(state.context.current.candle_id, receipt["completed_candle_id"])
        self.assertEqual(bar.candle_id, receipt["last_completed_candle_id"])
        self.assertFalse(receipt["actionable"])
        self.assertFalse(receipt["pending"]["actionable"])
        self.assertEqual(bar.candle_id, receipt["pending"]["decision_candle_id"])
        json.dumps(receipt, allow_nan=False)

    def test_long_and_short_retest_geometry_mirror(self):
        for direction, ctx in (("LONG", make_context()), ("SHORT", short_context())):
            with self.subTest(direction=direction):
                impulse = self.detection(ctx, direction)
                retest = self.retest_bar(impulse)
                result = self.step(impulse, retest)
                self.assertEqual("PENDING_R", result.status)
                self.assertEqual(3, result.pending.ttl)
                expected = (("100.95", "99.95") if direction == "LONG"
                            else ("99.05", "100.05"))
                self.assertEqual(tuple(map(D, expected)),
                                 (result.pending.trigger, result.pending.stop))
                self.assertEqual(retest, result.pending.last_bar)
                self.assertEqual(retest.decision_ready_at, result.pending.decision_at)

    def test_retest_observation_cannot_retroactively_fill(self):
        state = self.detection()
        bar = self.retest_bar(state)
        result = self.step(state, bar)
        repeated = advance_pending(result.pending, bar, decision_at=bar.decision_ready_at,
                                   costs=result.pending.costs, market=market_at(bar.decision_ready_at))
        self.assertEqual("PENDING", repeated.status)
        self.assertIsNone(repeated.position)
        future = make_bar(bar.end, open="100.90", high="101.10", low="100.60", close="101.00")
        filled = advance_pending(result.pending, future, decision_at=future.decision_ready_at,
                                 costs=result.pending.costs, market=market_at(future.decision_ready_at))
        self.assertEqual("FILLED_RESEARCH", filled.status)
        self.assertEqual(D("100.95"), filled.position.entry)

    def test_higher_retest_volume_is_soft_and_does_not_reject(self):
        impulse = self.detection()
        retest = self.retest_bar(impulse, volume="9000")
        self.assertGreater(retest.volume, impulse.context.current.volume)
        self.assertEqual("PENDING_R", self.step(impulse, retest).status)

    def test_r_pending_expires_on_third_later_bar(self):
        state = self.detection()
        retest = self.retest_bar(state)
        pending = self.step(state, retest).pending
        for slot in range(3):
            bar = make_bar(retest.end + timedelta(minutes=5 * slot),
                           open="100.60", high="100.90", low="100.50", close="100.70")
            result = advance_pending(pending, bar, decision_at=bar.end,
                                     costs=pending.costs, market=market_at(bar.end))
            self.assertEqual("EXPIRED" if slot == 2 else "PENDING", result.status)
            pending = result.pending

    def test_wide_structural_stop_has_no_automatic_optional_atr_veto(self):
        ctx = make_context(values={"low": "96.00"})
        state = self.detection(ctx)
        result = self.step(state, self.retest_bar(state))
        self.assertEqual("PENDING_R", result.status)
        self.assertGreater((result.pending.trigger-result.pending.stop) / ctx.atr, D(2))

    def test_zone_width_uses_point_two_prior_atr_when_larger_than_two_ticks(self):
        ctx = make_context(values={"open": "104.10", "high": "106.00",
                                   "low": "103.90", "close": "105.90"})
        prior = tuple(replace(bar, open="100.10", high="104.00", low="96.00", close="100.20")
                      for bar in ctx.prior)
        ctx = prepare_setup(ctx.current, prior, ctx.profile, ctx.decision_at)
        state = self.detection(ctx)
        self.assertEqual("WAIT_RETEST", state.status)
        self.assertEqual(D("1.60"), state.tolerance)

    def test_fourth_bar_can_retest_and_fourth_miss_expires(self):
        for should_retest in (True, False):
            with self.subTest(should_retest=should_retest):
                state = self.detection()
                for slot in range(4):
                    bar = (self.retest_bar(state, slot=slot) if should_retest and slot == 3
                           else self.non_retest_bar(state, slot))
                    state = self.step(state, bar)
                    if slot < 3:
                        self.assertEqual("WAIT_RETEST", state.status)
                self.assertEqual("PENDING_R" if should_retest else "EXPIRED", state.status)
                self.assertEqual(4, state.bars_seen)
                self.assertEqual(4, state.revision)

    def test_zone_boundary_touch_is_inclusive_but_overshoot_not_touch(self):
        state = self.detection()
        for low in ("100.20", "100.40"):
            with self.subTest(low=low):
                self.assertEqual("PENDING_R", self.step(state, self.retest_bar(state, low=low)).status)
        result = self.step(state, self.retest_bar(state, low="100.15"))
        self.assertEqual("WAIT_RETEST", result.status)
        self.assertIsNone(result.pending)

    def test_directional_completed_close_breach_cancels(self):
        for direction, ctx in (("LONG", make_context()), ("SHORT", short_context())):
            with self.subTest(direction=direction):
                state = self.detection(ctx, direction)
                bar = self.retest_bar(state, low="100.10", close="100.15")
                result = self.step(state, bar)
                self.assertEqual("CANCELLED", result.status)
                self.assertIn("RETEST_STRUCTURE_INVALIDATED", result.reason_codes)
                self.assertIs(result, self.step(result, self.retest_bar(state, slot=1)))

    def test_identical_observation_does_not_consume_another_slot(self):
        state = self.detection()
        bar = self.non_retest_bar(state, 0)
        result = self.step(state, bar)
        self.assertEqual(1, result.bars_seen)
        self.assertIs(result, self.step(result, bar))

    def test_impulse_or_missing_future_interval_cannot_retest(self):
        for use_impulse, code in ((True, "FUTURE_INTERVAL_REQUIRED"), (False, "MISSING_FUTURE_BAR")):
            with self.subTest(code=code):
                state = self.detection()
                bar = state.context.current if use_impulse else self.retest_bar(state, slot=1)
                result = self.step(state, bar)
                self.assertEqual("CANCELLED", result.status)
                self.assertIn(code, result.reason_codes)

    def test_delayed_impulse_receipt_excludes_already_started_interval(self):
        ctx = make_context()
        at = ctx.decision_at + timedelta(seconds=1)
        ctx = prepare_setup(ctx.current, ctx.prior, ctx.profile, at)
        state = self.detection(ctx)
        excluded = self.step(state, self.retest_bar(state))
        self.assertIn("FUTURE_INTERVAL_REQUIRED", excluded.reason_codes)
        eligible = self.step(state, self.retest_bar(state, slot=1))
        self.assertEqual("PENDING_R", eligible.status)

    def test_impulse_cutoff_and_retest_setup_cutoff(self):
        late = make_context(at=time(14, 20))  # available 14:25, after last impulse
        self.assertIn("IMPULSE_CUTOFF", self.detection(late).reason_codes)
        ctx = make_context(at=time(14, 15))  # available 14:20 inclusive
        state = self.detection(ctx)
        self.assertEqual("WAIT_RETEST", state.status)
        for slot in range(3):
            state = self.step(state, self.non_retest_bar(state, slot))
        bar = self.retest_bar(state, slot=3)
        self.assertEqual(time(14, 40), bar.end.timetz().replace(tzinfo=None))
        self.assertEqual("PENDING_R", self.step(state, bar).status)
        delayed = replace(bar, available_at=bar.end + timedelta(seconds=1))
        self.assertIn("RETEST_CUTOFF", self.step(state, delayed).reason_codes)

    def test_admission_rechecks_liquidity_exposure_and_cost_quantity(self):
        state = self.detection()
        bar = self.retest_bar(state)
        for evidence, code in ((market_at(bar.end, liquid=False), "LIQUIDITY_UNAVAILABLE"),
                               (market_at(bar.end, exposure="DUPLICATE"), "DUPLICATE_EXPOSURE"),
                               (market_at(state.decision_at), "STALE_MARKET_EVIDENCE")):
            with self.subTest(code=code):
                self.assertIn(code, self.step(state, bar, market=evidence).reason_codes)
        self.assertIn("QUANTITY_CHANGED", self.step(state, bar,
            costs=replace(state.costs, quantity=2)).reason_codes)
        self.assertIn("ZERO_TRADED_VOLUME", self.step(state,
            replace(bar, volume=0)).reason_codes)

    def test_b_and_r_are_independent_and_six_bar_range_is_not_four(self):
        from volume_research.breakout import detect_breakout
        ctx = make_context()
        prior = list(ctx.prior)
        prior[-6] = replace(prior[-6], high="100.90")
        ctx = prepare_setup(ctx.current, tuple(prior), ctx.profile, ctx.decision_at)
        costs, market = costs_at(ctx.decision_at), market_at(ctx.decision_at)
        breakout = detect_breakout(ctx, "LONG", costs=costs, market=market, enabled=True)
        retest = detect_retest(ctx, "LONG", costs=costs, market=market, enabled=True)
        self.assertEqual("PENDING_B", breakout.status)
        self.assertIn("IMPULSE_RULES_NOT_MET", retest.reason_codes)
        both = make_context()
        self.assertEqual("WAIT_RETEST", self.detection(both).status)
        self.assertEqual("PENDING_B", detect_breakout(both, "LONG",
            costs=costs_at(both.decision_at), market=market_at(both.decision_at), enabled=True).status)


if __name__ == "__main__":
    unittest.main()
