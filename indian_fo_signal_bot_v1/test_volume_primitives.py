"""Authored arithmetic fixtures only; no acquired market data or access rights."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import unittest

from volume_research.primitives import (
    IST, Bar, CorporateAction, D, Instrument, Membership, Session, ValidationError,
    VolumeProfile, atr14, ceil_tick, clv, comparison_rvol, floor_tick,
    normal_session, prepare_setup, seasonal_rvol, sector_relative_strength,
    validate_bar, validate_future, validate_setup,
)


def make_bar(start, *, candle_id=None, open="100.10", high="100.30", low="100.00",
             close="100.20", volume="1000", **overrides):
    end = start + timedelta(minutes=5)
    values = dict(candle_id=candle_id or "SYNTH:" + start.isoformat(),
                  instrument_id="SYNTH:EQ:1", source="AUTHORED_SYNTHETIC",
                  start=start, end=end, open=open, high=high, low=low, close=close,
                  volume=volume, observed_at=end, received_at=end,
                  finalized_at=end, available_at=end)
    values.update(overrides)
    return Bar(**values)


def make_context(*, day=date(2026, 11, 2), at=time(10), values=None, history_count=20):
    previous, cursor = [], day - timedelta(days=1)
    while len(previous) < max(history_count, 2):
        if cursor.weekday() < 5:
            previous.append(cursor)
        cursor -= timedelta(days=1)
    days = tuple(reversed(previous)) + (day,)
    sessions = tuple(normal_session(d) for d in days)
    start = datetime.combine(day, at, IST)
    current = make_bar(start, open="100.10", high="100.80", low="100.00",
                       close="100.70", volume="2000")
    if values:
        current = replace(current, **values)
    history = tuple(make_bar(datetime.combine(d, at, IST)) for d in days[:-1])
    prior_slots = [s.open_at + timedelta(minutes=5 * index)
                   for s in sessions[-2:] for index in range(75)
                   if s.open_at + timedelta(minutes=5 * index) < start]
    prior = tuple(make_bar(slot) for slot in prior_slots[-15:])
    known = sessions[0].open_at - timedelta(days=1)
    instrument = Instrument("SYNTH:EQ:1", "synthetic", "SYNTH", "AUTHORED_SYNTHETIC",
                            "synthetic-v1", days[0], day, D("0.05"), known)
    member = Membership(instrument.instrument_id, days[0], day, known)
    profile = VolumeProfile(instrument, sessions, (member,), history, (), day)
    return prepare_setup(current, prior, profile, current.decision_ready_at)


class TestVolumePrimitives(unittest.TestCase):
    def assertCode(self, code, callback):
        with self.assertRaises(ValidationError) as failure:
            callback()
        self.assertEqual(code, failure.exception.code)

    def test_default_context_and_exact_stage1_rvol(self):
        context = make_context()
        self.assertEqual(D(2), context.rvol.value)
        self.assertEqual(D(1000), context.rvol.baseline)
        self.assertEqual(20, context.rvol.window)
        self.assertEqual(20, len(context.rvol.session_dates))
        self.assertEqual(context, validate_setup(context))

    def test_frozen_dtos(self):
        context = make_context()
        with self.assertRaises(FrozenInstanceError):
            context.current.volume = D(0)

    def test_decimal_tick_boundaries(self):
        self.assertEqual(D("102.50"), ceil_tick(D("100.85") + D("1.8") * D(".9"), ".05"))
        self.assertEqual(D("99.95"), floor_tick("99.999999", ".05"))
        self.assertEqual(D("100.85"), ceil_tick("100.85", ".05"))
        self.assertCode("INVALID_TICK", lambda: ceil_tick(100, 0))

    def test_nonfinite_bool_missing_and_invalid_numeric(self):
        for value, code in ((None, "MISSING_NUMERIC_INPUT"), (True, "INVALID_NUMERIC_INPUT"),
                            ("NaN", "NONFINITE_NUMERIC_INPUT"), ("Infinity", "NONFINITE_NUMERIC_INPUT"),
                            ("abc", "INVALID_NUMERIC_INPUT")):
            with self.subTest(value=value):
                self.assertCode(code, lambda: D(value))

    def test_clv_long_short_mirrored_domain(self):
        context = make_context()
        self.assertEqual(D(".875"), clv(context.current))
        short = replace(context.current, open="100.70", close="100.10")
        self.assertEqual(D(".125"), clv(short))
        flat = replace(short, open=100, high=100, low=100, close=100)
        self.assertCode("ZERO_CANDLE_RANGE", lambda: clv(flat))

    def test_no_half_formed_bar(self):
        context = make_context()
        self.assertCode("BAR_NOT_AVAILABLE", lambda: validate_bar(
            context.current, context.profile.sessions[-1], context.current.start + timedelta(minutes=2)))
        self.assertCode("INCOMPLETE_BAR", lambda: validate_bar(
            replace(context.current, complete=False), context.profile.sessions[-1], context.decision_at))

    def test_aware_time_and_five_minute_grid(self):
        context = make_context()
        self.assertCode("AWARE_TIMESTAMP_REQUIRED", lambda: validate_bar(
            replace(context.current, start=context.current.start.replace(tzinfo=None)),
            context.profile.sessions[-1], context.decision_at))
        bar = make_bar(context.current.start + timedelta(minutes=1))
        self.assertCode("INVALID_FIVE_MINUTE_SLOT", lambda: validate_bar(
            bar, context.profile.sessions[-1], bar.decision_ready_at))

    def test_source_clock_and_late_availability(self):
        context = make_context()
        bad = replace(context.current, received_at=context.current.end - timedelta(seconds=1))
        self.assertCode("INVALID_SOURCE_CLOCK_ORDER", lambda: validate_bar(
            bad, context.profile.sessions[-1], context.decision_at))
        late = replace(context.current, available_at=context.decision_at + timedelta(seconds=1))
        self.assertCode("BAR_NOT_AVAILABLE", lambda: validate_bar(
            late, context.profile.sessions[-1], context.decision_at))

    def test_invalid_geometry_off_tick_and_negative_volume(self):
        context = make_context()
        for values, code in ((dict(low=101), "INVALID_OHLC"),
                             (dict(volume=-1), "INVALID_VOLUME"),
                             (dict(close="100.711"), "PRICE_OFF_TICK")):
            with self.subTest(code=code):
                self.assertCode(code, lambda: prepare_setup(replace(context.current, **values),
                    context.prior, context.profile, context.decision_at))

    def test_normal_session_has_75_slots_and_special_is_unavailable(self):
        context = make_context()
        self.assertEqual(75, context.profile.sessions[-1].slot_count)
        special = replace(context.profile.sessions[-1], phase="SPECIAL")
        self.assertCode("SPECIAL_SESSION_UNSUPPORTED", lambda: validate_bar(
            context.current, special, context.decision_at))
        broken = replace(context.profile.sessions[-1], close_at=context.current.end)
        profile = replace(context.profile, sessions=context.profile.sessions[:-1] + (broken,))
        self.assertCode("INVALID_NORMAL_SESSION", lambda: seasonal_rvol(
            context.current, profile, context.decision_at))

    def test_missing_most_recent_slot_does_not_backfill_older_session(self):
        context = make_context(history_count=21)
        profile = replace(context.profile, history=context.profile.history[:-1])
        self.assertCode("INSUFFICIENT_HISTORY", lambda: seasonal_rvol(
            context.current, profile, context.decision_at))

    def test_current_zero_distinct_from_missing_and_zero_baseline(self):
        context = make_context()
        zero_current = replace(context.current, volume=0)
        self.assertEqual(D(0), seasonal_rvol(zero_current, context.profile, context.decision_at).value)
        profile = replace(context.profile, history=tuple(replace(b, volume=0) for b in context.profile.history))
        self.assertCode("ZERO_BASELINE", lambda: seasonal_rvol(context.current, profile, context.decision_at))
        self.assertCode("MISSING_NUMERIC_INPUT", lambda: replace(context.current, volume=None))

    def test_duplicate_and_nonprior_history(self):
        context = make_context()
        for additional, code in ((context.profile.history[-1], "DUPLICATE_HISTORY_SLOT"),
                                 (context.current, "NONPRIOR_HISTORY")):
            profile = replace(context.profile, history=context.profile.history + (additional,))
            self.assertCode(code, lambda: seasonal_rvol(context.current, profile, context.decision_at))

    def test_split_normalizes_shares_as_of_effective_date(self):
        context = make_context()
        effective = context.profile.sessions[10].session_date
        action = CorporateAction(context.current.instrument_id, effective, D(2),
                                 context.profile.sessions[0].open_at)
        history = tuple(replace(b, volume=500 if b.session_date < effective else 1000)
                        for b in context.profile.history)
        profile = replace(context.profile, history=history, actions=(action,))
        self.assertEqual(D(2), seasonal_rvol(context.current, profile, context.decision_at).value)

    def test_no_future_action_adjustment_and_unknown_ledger(self):
        context = make_context()
        action = CorporateAction(context.current.instrument_id, context.current.session_date + timedelta(days=1),
                                 D(100), context.decision_at + timedelta(days=1))
        profile = replace(context.profile, actions=(action,))
        self.assertEqual(D(2), seasonal_rvol(context.current, profile, context.decision_at).value)
        profile = replace(context.profile, actions_complete_through=context.current.session_date - timedelta(days=1))
        self.assertCode("CORPORATE_ACTION_HISTORY_UNAVAILABLE", lambda: seasonal_rvol(
            context.current, profile, context.decision_at))

    def test_late_action_and_structural_split_boundary_reject(self):
        context = make_context(at=time(9, 40))
        action = CorporateAction(context.current.instrument_id, context.current.session_date,
                                 D(2), context.decision_at + timedelta(seconds=1))
        profile = replace(context.profile, actions=(action,))
        self.assertCode("CORPORATE_ACTION_NOT_AVAILABLE", lambda: seasonal_rvol(
            context.current, profile, context.decision_at))
        action = replace(action, available_at=context.profile.sessions[0].open_at)
        profile = replace(context.profile, actions=(action,))
        self.assertCode("CORPORATE_ACTION_IN_STRUCTURE_WINDOW", lambda: prepare_setup(
            context.current, context.prior, profile, context.decision_at))

    def test_matched60_windows(self):
        context = make_context(history_count=60)
        results = comparison_rvol(context.current, context.profile, context.decision_at)
        self.assertEqual((5, 10, 15, 20, 30, 50, 60), tuple(r.window for r in results))
        self.assertTrue(all(r.value == 2 for r in results))
        context = make_context(history_count=59)
        self.assertCode("INSUFFICIENT_HISTORY", lambda: comparison_rvol(
            context.current, context.profile, context.decision_at))

    def test_special_prior_session_not_mapped_to_normal_slot(self):
        context = make_context(history_count=21)
        sessions = tuple(replace(s, phase="SPECIAL") if index == 20 else s
                         for index, s in enumerate(context.profile.sessions))
        profile = replace(context.profile, sessions=sessions)
        result = seasonal_rvol(context.current, profile, context.decision_at)
        self.assertNotIn(sessions[20].session_date, result.session_dates)
        self.assertEqual(D(2), result.value)

    def test_dated_identity_membership_source_and_ordinary_equity(self):
        context = make_context()
        for profile, code in (
            (replace(context.profile, members=()), "POINT_IN_TIME_UNIVERSE_UNAVAILABLE"),
            (replace(context.profile, members=(replace(context.profile.members[0], ordinary_equity=False),)),
             "INELIGIBLE_UNIVERSE_MEMBER"),
            (replace(context.profile, members=(replace(context.profile.members[0],
                                                      available_at=context.decision_at + timedelta(seconds=1)),)),
             "MEMBERSHIP_NOT_AVAILABLE"),
            (replace(context.profile, instrument=replace(context.profile.instrument, source="WRONG")),
             "SOURCE_IDENTITY_MISMATCH"),
            (replace(context.profile, instrument=replace(context.profile.instrument,
                                                        valid_to=context.current.session_date - timedelta(days=1))),
             "DATED_IDENTITY_UNAVAILABLE"),
        ):
            with self.subTest(code=code):
                self.assertCode(code, lambda: prepare_setup(context.current, context.prior, profile,
                                                          context.decision_at))

    def test_reject_missing_duplicate_and_out_of_order_prior_bars(self):
        context = make_context()
        for prior, code in ((context.prior[:5] + context.prior[6:], "ATR_INSUFFICIENT_HISTORY"),
                             (context.prior[:-1] + (context.prior[-2],), "DUPLICATE_CANDLE_ID"),
                             (context.prior[:4] + (context.prior[5], context.prior[4]) + context.prior[6:],
                              "MISSING_HISTORY_SLOT")):
            self.assertCode(code, lambda: prepare_setup(context.current, prior, context.profile,
                                                      context.decision_at))

    def test_atr_seed_rma_and_overnight_gap(self):
        context = make_context()
        prior = tuple(replace(b, open=100, high=101, low=99, close=100) for b in context.prior)
        self.assertEqual(D(2), atr14(prior, context.decision_at))
        extra = make_bar(context.current.start, open=100, high=104, low=100, close=102)
        self.assertEqual((D(26) + D(4)) / D(14), atr14(prior + (extra,), extra.end))
        overnight = make_context(at=time(9, 15))
        prior = tuple(replace(b, open=100, high=101, low=99, close=100) for b in overnight.prior)
        next_day = make_bar(overnight.current.start, open=110, high=111, low=109, close=110)
        self.assertEqual((D(26) + D(11)) / D(14), atr14(prior + (next_day,), next_day.end))

    def test_atr_requires_prior_close_and_complete_bars(self):
        context = make_context()
        self.assertCode("ATR_INSUFFICIENT_HISTORY", lambda: atr14(context.prior[-14:], context.decision_at))
        self.assertCode("ATR_BAR_UNAVAILABLE", lambda: atr14(
            context.prior[:-1] + (replace(context.prior[-1], complete=False),), context.decision_at))

    def test_supplied_feature_values_cannot_override_calculations(self):
        context = make_context()
        self.assertCode("FEATURE_CONTEXT_MISMATCH", lambda: validate_setup(replace(context, atr=D(999))))
        self.assertCode("FEATURE_CONTEXT_MISMATCH", lambda: validate_setup(
            replace(context, rvol=replace(context.rvol, value=D(999)))))

    def test_current_price_not_in_atr(self):
        context = make_context()
        other = prepare_setup(replace(context.current, high=200), context.prior, context.profile,
                              context.decision_at)
        self.assertEqual(context.atr, other.atr)

    def test_setup_decision_must_share_current_session_date(self):
        context = make_context()
        self.assertCode("DECISION_SESSION_MISMATCH", lambda: prepare_setup(
            context.current, context.prior, context.profile, context.decision_at + timedelta(days=1)))

    def test_future_identity_and_session_validation(self):
        context = make_context()
        bar = make_bar(context.current.end)
        self.assertEqual(bar, validate_future(bar, context, bar.end))
        self.assertCode("SOURCE_IDENTITY_MISMATCH", lambda: validate_future(
            replace(bar, instrument_id="WRONG"), context, bar.end))

    def test_sector_missing_is_soft_and_residual_is_aligned(self):
        context = make_context()
        now = context.current
        before = make_bar(now.start - timedelta(minutes=15), close=100)
        sector_now = replace(now, instrument_id="SECTOR", open=100, high=102, low=100, close=101)
        sector_before = replace(before, instrument_id="SECTOR")
        missing = sector_relative_strength(now, before)
        self.assertEqual("MISSING", missing.status)
        self.assertIsNone(missing.value)
        result = sector_relative_strength(now, before, sector_now, sector_before, now.end)
        self.assertEqual("AVAILABLE", result.status)
        self.assertEqual((D("100.7") / D(100)).ln() - (D(101) / D(100)).ln(), result.value)
        wrong = replace(sector_before, end=sector_before.end - timedelta(minutes=5))
        result = sector_relative_strength(now, before, sector_now, wrong, now.end)
        self.assertEqual("SECTOR_TIMESTAMPS_MISALIGNED", result.reason_code)

    def test_sector_identity_incomplete_and_invalid_data_are_soft_missing(self):
        context = make_context()
        now = context.current
        before = make_bar(now.start - timedelta(minutes=15), close=100)
        sector_now = replace(now, instrument_id="SECTOR")
        sector_before = replace(before, instrument_id="SECTOR")
        for change, reason in ((dict(instrument_id="WRONG"), "SECTOR_IDENTITY_MISMATCH"),
                               (dict(source="WRONG"), "SECTOR_IDENTITY_MISMATCH"),
                               (dict(complete=False), "SECTOR_INCOMPLETE_BAR"),
                               (dict(low=200), "SECTOR_INVALID_INPUT")):
            with self.subTest(reason=reason):
                result = sector_relative_strength(now, before, sector_now,
                                                   replace(sector_before, **change), now.end)
                self.assertEqual("MISSING", result.status)
                self.assertEqual(reason, result.reason_code)


if __name__ == "__main__":
    unittest.main()
