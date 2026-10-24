"""Phase 4/5 gap regressions using authored packets and isolated memory stores.

These are offline mechanics checks. Injected transport never acquires LIVE authority.
"""
import hashlib
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import test_bot
import test_phase4_feed_history as feed_fixtures
import test_phase4_explanations as risk_fixtures
from angel_feed import FeedError
from brokers import assess_live_candle_batch
from strategies import (
    IST, compute_supertrend, evaluate_strategy_detailed, parse_ist_timestamp,
    rank_signal_candidates, signal_risk_reward,
)


class TestPhase45ScannerGaps(unittest.TestCase):
    def harness(self):
        case = feed_fixtures.TestPhase4FeedHistory()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def push_packet(self, case, when, **fields):
        case.now = when + timedelta(seconds=1)
        case.tick += 20
        case.peers[-1].messages.append("pong")
        case.feed.poll_once()
        case.sequence += 1
        case.peers[-1].messages.append(feed_fixtures.packet(when, sequence=case.sequence, **fields))
        return case.feed.poll_once()

    def opening(self, case, opened, *, first_volume=1005):
        for index in range(16):
            case.push(opened + timedelta(seconds=20 * index), first_volume + index * 5)
        return case.feed.bars[5][-1]

    def test_ranker_rejects_derived_infinite_ratio_before_returning_candidate(self):
        for first_target in (1e300, 1.5e-300):
            with self.subTest(first_target=first_target):
                candidate = risk_fixtures.TestPhase4NumericRiskAndRanking().signal(entry_price=1e-300, stop_loss=5e-301,
                    invalidation_level=6e-301, entry_zone_low=5e-301, entry_zone_high=1e-300,
                    target_1=first_target, target_2=1e301)
                self.assertFalse(signal_risk_reward(candidate)["allowed"])
                with self.assertRaises(ValueError):
                    rank_signal_candidates([candidate])

    def test_observed_preopen_packet_can_supply_raw_opening_volume_baseline(self):
        case = self.harness()
        opened = datetime(2026, 10, 19, 9, 15, tzinfo=IST)
        case.push(opened - timedelta(seconds=20), 1000)
        baseline_id = case.feed.latest["event_id"]
        self.assertEqual(len(case.feed.bars[1]), 0)
        self.assertEqual(len(case.feed.bars[5]), 0)
        opening = self.opening(case, opened)
        self.assertEqual(parse_ist_timestamp(opening["timestamp"]), opened)
        self.assertTrue(opening["is_complete"])
        self.assertEqual(opening["volume"], 75)
        self.assertEqual(opening["volume_baseline_event_id"], baseline_id)
        self.assertNotIn("UNKNOWN_INITIAL_VOLUME_BASELINE", opening["quality_reasons"])
        with case.store.paper_transaction(write=False) as conn:
            retained = conn.execute("SELECT raw_packet FROM angel_feed_events WHERE event_id=?", (baseline_id,)).fetchone()
            self.assertIsNotNone(retained)
            self.assertEqual(case.feed.parser.parse(retained[0])["cumulative_volume"], 1000)
        self.assertEqual(opening["data_mode"], "FIXTURE")
        self.assertTrue(opening["is_simulated"])
        with self.assertRaisesRegex(FeedError, "FIXTURE_NOT_LIVE_QUALIFIED"):
            case.feed.get_candles(case.instrument, 5, case.now)

    def test_absent_old_prior_day_quote_and_unresolved_baselines_stay_unavailable(self):
        opened = datetime(2026, 10, 19, 9, 15, tzinfo=IST)
        scenarios = ("absent", "old", "prior_day", "quote", "unresolved")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                case = self.harness()
                if scenario == "old":
                    case.push(opened - timedelta(seconds=31), 1000)
                elif scenario == "prior_day":
                    case.push(opened - timedelta(days=3, seconds=20), 1000)
                elif scenario == "quote":
                    self.push_packet(case, opened - timedelta(seconds=20), mode=2, volume=1000)
                elif scenario == "unresolved":
                    self.push_packet(case, opened - timedelta(seconds=20),
                        trade_ts=opened - timedelta(minutes=2), volume=1000)
                opening = self.opening(case, opened)
                self.assertFalse(opening["is_complete"])
                self.assertIsNone(opening["volume_baseline_event_id"])
                self.assertIn("UNKNOWN_INITIAL_VOLUME_BASELINE", opening["quality_reasons"])
                self.assertFalse(case.feed.status()["live_signal_allowed"])

    def test_opening_gap_or_unobserved_quantity_keeps_existing_quality_rejection(self):
        opened = datetime(2026, 10, 19, 9, 15, tzinfo=IST)
        for scenario in ("gap", "sampled"):
            with self.subTest(scenario=scenario):
                case = self.harness()
                case.push(opened - timedelta(seconds=30), 1000)
                if scenario == "gap":
                    # The observed pre-open baseline is useful only within the
                    # existing continuity bound, not merely on the same day.
                    for index in range(16):
                        case.push(opened + timedelta(seconds=1 + 20 * index), 1005 + index * 5)
                    expected_reason = "TRADE_TIME_GAP"
                else:
                    self.opening(case, opened, first_volume=1010)
                    expected_reason = "UNOBSERVED_TRADES_IN_VOLUME_DELTA"
                self.assertFalse(case.feed.bars[5][0]["is_complete"])
                self.assertIn(expected_reason, case.feed.bars[5][0]["quality_reasons"])

    def test_preopen_time_order_and_volume_reset_are_not_accepted_as_new_baselines(self):
        opened = datetime(2026, 10, 19, 9, 15, tzinfo=IST)
        for scenario in ("time", "volume", "price"):
            with self.subTest(scenario=scenario):
                case = self.harness()
                self.push_packet(case, opened - timedelta(seconds=20), volume=1000, price=10000)
                if scenario == "time":
                    fields = {"trade_ts": opened - timedelta(seconds=21), "volume": 1005, "price": 10000}
                    reason = "OUT_OF_ORDER_TRADE_TIMESTAMP"
                elif scenario == "volume":
                    fields = {"volume": 999, "price": 10000}
                    reason = "CUMULATIVE_VOLUME_RESET"
                else:
                    fields = {"volume": 1000, "price": 10001}
                    reason = "PRICE_CHANGED_WITHOUT_TRADE_VOLUME"
                with self.assertRaisesRegex(FeedError, reason):
                    self.push_packet(case, opened - timedelta(seconds=10), **fields)
                self.assertFalse(case.feed.status()["connected"])
                self.assertFalse(case.feed.status()["live_signal_allowed"])

    def test_raw_preopen_lineage_reaches_201_bar_strategy_diagnostic_without_live_promotion(self):
        case = self.harness()
        baseline_ids = []
        for day in (19, 20, 21):
            opened = datetime(2026, 10, day, 9, 15, tzinfo=IST)
            case.push(opened - timedelta(seconds=20), 1000)
            baseline_ids.append(case.feed.latest["event_id"])
            when, volume = opened, 1005
            while when < opened.replace(hour=15, minute=30):
                case.push(when, volume)
                when += timedelta(seconds=20)
                volume += 5
                if len(case.feed._history_rows(5, case.now)) >= 201:
                    break
        history = case.feed._history_rows(5, case.now)
        self.assertEqual(len(history), 201)
        self.assertEqual(len({row["timestamp"][:10] for row in history}), 3)
        for day in (19, 20, 21):
            first = next(row for row in history if parse_ist_timestamp(row["timestamp"]).day == day)
            self.assertEqual(parse_ist_timestamp(first["timestamp"]).strftime("%H:%M"), "09:15")
        with patch("strategies.compute_supertrend", wraps=compute_supertrend) as indicator:
            _, trace = evaluate_strategy_detailed("strat_5_supertrend_pullback", history,
                symbol="RELIANCE", now=case.now)
            self.assertEqual(trace["warmup"]["observed"], 201)
            self.assertNotEqual(trace["status"], "UNAVAILABLE")
            checks = {row["rule_id"]: row for row in trace["rule_checks"]}
            self.assertEqual(checks["data.warmup"]["status"], "PASS")
            self.assertEqual(checks["session.vwap_start"]["status"], "PASS")
            indicator.assert_called_once()
        with case.store.paper_transaction(write=False) as conn:
            for event_id in baseline_ids:
                row = conn.execute("SELECT raw_packet,raw_sha256 FROM angel_feed_events WHERE event_id=?", (event_id,)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(hashlib.sha256(row[0]).hexdigest(), row[1])
        self.assertTrue(all(row["data_mode"] == "FIXTURE" and row["is_simulated"] for row in history))
        _, qualification = assess_live_candle_batch(history, 5, case.now, provider="angelone", context="SCANNER", normalized_ist=True)
        self.assertEqual(qualification["reason_code"], "INVALID_PROVENANCE")
        self.assertFalse(qualification["live_signal_allowed"])
        with self.assertRaisesRegex(FeedError, "FIXTURE_NOT_LIVE_QUALIFIED"):
            case.feed.get_candles(case.instrument, 5, case.now)

    def test_actual_ring_evicts_one_of_301_without_losing_current_session_open(self):
        case = self.harness()
        rows = [dict(timestamp=(datetime(2026, 10, day, 9, 15, tzinfo=IST)
                    + timedelta(minutes=5 * index)).isoformat(), is_complete=True)
                for day in (19, 20, 21, 22, 23) for index in range(75)]
        ring = case.feed.bars[5]
        ring.extend(rows[:300])
        self.assertEqual(len(ring), 300)
        self.assertEqual(ring[0], rows[0])
        ring.append(rows[300])
        self.assertEqual(len(ring), 300)
        self.assertEqual(ring[0], rows[1])
        selected = case.feed._history_rows(5, datetime(2026, 10, 23, 9, 20, tzinfo=IST))
        self.assertEqual(selected, rows[1:301])
        self.assertEqual(selected[-1]["timestamp"], "2026-10-23T09:15:00+05:30")
        for previous, current in zip(selected, selected[1:]):
            left, right = (parse_ist_timestamp(row["timestamp"]) for row in (previous, current))
            self.assertLess(left, right)
            if left.date() == right.date():
                self.assertEqual(right - left, timedelta(minutes=5))

    def test_evicted_history_still_never_splices_gaps_or_uses_an_invalid_current_tail(self):
        case = self.harness()
        rows = [dict(timestamp=(datetime(2026, 10, day, 9, 15, tzinfo=IST)
                    + timedelta(minutes=5 * index)).isoformat(), is_complete=True)
                for day in (19, 20, 21, 22, 23) for index in range(75)]
        ring = case.feed.bars[5]
        ring.extend(rows[:305])
        retained = list(ring)
        missing = retained[100]["timestamp"]
        ring.clear()
        ring.extend(row for row in retained if row["timestamp"] != missing)
        selected = case.feed._history_rows(5, datetime(2026, 10, 23, 9, 40, tzinfo=IST))
        previous_day = parse_ist_timestamp(missing).date()
        selected_previous = [row for row in selected if parse_ist_timestamp(row["timestamp"]).date() == previous_day]
        self.assertTrue(all(row["timestamp"] > missing for row in selected_previous))
        ring[-1]["is_complete"] = False
        selected = case.feed._history_rows(5, datetime(2026, 10, 23, 9, 40, tzinfo=IST))
        self.assertFalse(any(row["timestamp"].startswith("2026-10-23") for row in selected))


if __name__ == "__main__":
    unittest.main()
