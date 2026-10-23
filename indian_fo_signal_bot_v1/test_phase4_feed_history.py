"""Offline stream lookback tests. Authored packets never establish LIVE acceptance."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import test_bot
from angel_feed import AngelLiveFeed, FeedError
from brokers import AngelOneSmartAPIAdapter
from config import BotConfig
from storage import SQLitePersistenceStore
from strategies import IST, compute_supertrend, evaluate_strategy_detailed, parse_ist_timestamp
from test_angel_feed import FakePeer, packet


class TestPhase4FeedHistory(unittest.TestCase):
    def setUp(self):
        self.config = BotConfig(active_broker="paper_sim", telegram_dry_run=True,
            enable_background_scheduler=False, angel_scrip_master_path="")
        self.instrument = AngelOneSmartAPIAdapter(self.config).resolve_instrument("RELIANCE")
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 19, 9, 15, 1, tzinfo=IST)
        self.tick = 0.0
        self.sequence = 0
        self.peers = []
        def factory():
            peer = FakePeer()
            self.peers.append(peer)
            return peer
        self.feed = AngelLiveFeed(self.config, self.store, self.instrument,
            transport_factory=factory, clock=lambda: self.now, monotonic=lambda: self.tick)
        self.addCleanup(self.feed.stop)
        self.feed.connect()
        guard = patch("socket.socket.connect", side_effect=AssertionError("Offline fixture transport only"))
        guard.start()
        self.addCleanup(guard.stop)

    def push(self, timestamp, volume):
        self.now = timestamp + timedelta(seconds=1)
        self.tick += 20
        self.peers[-1].messages.append("pong")
        self.feed.poll_once()
        self.last_volume = volume
        self.sequence += 1
        self.peers[-1].messages.append(packet(timestamp, sequence=self.sequence,
            volume=volume, quantity=5, price=10000 + self.sequence % 11))
        self.feed.poll_once()

    def session(self, day, until_count=None):
        timestamp = datetime(2026, 10, day, 9, 15, tzinfo=IST)
        close = timestamp.replace(hour=15, minute=30)
        volume = 1000
        while timestamp < close:
            self.push(timestamp, volume)
            if until_count is not None and len(self.feed._history_rows(5, self.now)) >= until_count:
                return
            timestamp += timedelta(seconds=20)
            volume += 5

    def test_stream_capacity_must_cover_existing_two_hundred_bar_requirement(self):
        self.assertGreaterEqual(self.feed.bars[5].maxlen, 200)
        self.assertEqual(self.feed.bars[5].maxlen, 300)
        self.assertEqual(self.feed.bars[1].maxlen, 750)

    def test_three_session_packets_pass_200_bar_warmup_but_lack_session_opening_coverage(self):
        self.session(19)
        self.session(20)
        self.session(21, until_count=199)
        history = self.feed._history_rows(5, self.now)
        self.assertEqual(len(history), 199)
        with patch("strategies.compute_supertrend", wraps=compute_supertrend) as indicator:
            signal, trace = evaluate_strategy_detailed("strat_5_supertrend_pullback", history,
                symbol="RELIANCE", now=self.now)
            self.assertIsNone(signal)
            self.assertEqual(trace["status"], "UNAVAILABLE")
            self.assertIn("INSUFFICIENT_COMPLETED_CANDLES", trace["reason_codes"])
            self.assertEqual(next(row for row in trace["rule_checks"]
                if row["rule_id"] == "data.warmup")["status"], "UNAVAILABLE")
            indicator.assert_not_called()
        while len(self.feed._history_rows(5, self.now)) < 200:
            self.push(self.now - timedelta(seconds=1) + timedelta(seconds=20), self.last_volume + 5)
        history = self.feed._history_rows(5, self.now)
        self.assertEqual(len(history), 200)
        self.assertEqual(len({row["timestamp"][:10] for row in history}), 3)
        self.assertTrue(all(row["is_complete"] and row["data_mode"] == "FIXTURE" and row["is_simulated"] for row in history))
        for previous, current in zip(history, history[1:]):
            first, second = map(parse_ist_timestamp, (previous["timestamp"], current["timestamp"]))
            if first.date() == second.date():
                self.assertEqual(second - first, timedelta(minutes=5))
        # Each session's initial cumulative-volume observation lacks its preceding
        # baseline. The feed safely omits that incomplete 09:15 five-minute bar;
        # retained lookback capacity alone cannot establish full-session VWAP.
        current_day = history[-1]["timestamp"][:10]
        first_today = next(row for row in history if row["timestamp"].startswith(current_day))
        self.assertEqual(parse_ist_timestamp(first_today["timestamp"]).strftime("%H:%M"), "09:20")
        with patch("strategies.compute_supertrend", wraps=compute_supertrend) as indicator:
            signal, trace = evaluate_strategy_detailed("strat_5_supertrend_pullback", history,
                symbol="RELIANCE", now=self.now)
            self.assertIsNone(signal)
            self.assertEqual(trace["warmup"]["observed"], 200)
            self.assertEqual(trace["status"], "UNAVAILABLE")
            self.assertIn("SESSION_START_COVERAGE_MISSING", trace["reason_codes"])
            checks = {row["rule_id"]: row for row in trace["rule_checks"]}
            self.assertEqual(checks["data.warmup"]["status"], "PASS")
            self.assertEqual(checks["session.vwap_start"]["status"], "UNAVAILABLE")
            indicator.assert_not_called()
        with self.assertRaisesRegex(FeedError, "FIXTURE_NOT_LIVE_QUALIFIED"):
            self.feed.get_candles(self.instrument, 5, self.now)
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        with self.store.paper_transaction(write=False) as conn:
            for bar in (history[0], history[-1]):
                self.assertIsNotNone(conn.execute("SELECT event_id FROM angel_feed_events WHERE event_id=?",
                    (bar["volume_baseline_event_id"],)).fetchone())
                self.assertIsNotNone(conn.execute("SELECT event_id FROM angel_feed_events WHERE event_id=?",
                    (bar["source_event_ids"][-1],)).fetchone())
            retained = conn.execute("SELECT COUNT(*) FROM angel_feed_candles WHERE interval_min=5").fetchone()[0]
            self.assertGreaterEqual(retained, 200)
        self.assertLessEqual(len(self.feed.bars[1]), 750)
        self.assertLessEqual(len(self.feed.bars[5]), 300)

    def test_closed_session_preserves_history_but_heartbeat_remains_mandatory(self):
        self.session(19, until_count=2)
        count = len(self.feed._history_rows(5, self.now))
        self.now = self.now.replace(hour=16, minute=0)
        self.tick += 20
        self.peers[-1].messages.append("pong")
        self.feed.poll_once()
        status = self.feed.check_health()
        self.assertTrue(status["connected"])
        self.assertEqual(status["state"], "STALE")
        self.assertFalse(status["live_signal_allowed"])
        self.assertEqual(len(self.feed._history_rows(5, self.now)), count)
        self.tick += 10
        self.feed.poll_once()  # No pong, starts a bounded heartbeat wait.
        self.tick += 30
        with self.assertRaisesRegex(FeedError, "ANGEL_HEARTBEAT_TIMEOUT"):
            self.feed.poll_once()
        self.assertFalse(self.feed.status()["connected"])

    def test_new_session_partial_bar_retains_past_lookback_but_cannot_authorize(self):
        self.session(19, until_count=2)
        self.push(datetime(2026, 10, 20, 9, 15, tzinfo=IST), 1000)
        self.push(datetime(2026, 10, 20, 9, 16, tzinfo=IST), 1005)
        selected = self.feed._history_rows(5, self.now)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(row["timestamp"].startswith("2026-10-19") for row in selected))
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        self.assertFalse(self.feed.current["_valid"])  # Missing first-minute trade continuity, not repaired.

    def test_new_session_grace_is_thirty_seconds_not_yesterday_freshness(self):
        self.session(19, until_count=2)
        self.now = datetime(2026, 10, 20, 9, 15, 20, tzinfo=IST)
        self.tick += 20
        self.peers[-1].messages.append("pong")
        self.feed.poll_once()
        self.assertTrue(self.feed.check_health()["connected"])
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        self.now += timedelta(seconds=11)
        self.tick += 11
        self.peers[-1].messages.append("pong")
        self.feed.poll_once()
        self.assertFalse(self.feed.check_health()["connected"])
        self.assertEqual(self.feed.reason, "ANGEL_FEED_STALE")

    def test_reconnect_clears_lookback_without_loading_persisted_rows(self):
        self.session(19, until_count=2)
        old_connection = self.feed.connection_id
        self.feed.reconnect()
        self.assertNotEqual(old_connection, self.feed.connection_id)
        self.assertEqual(len(self.feed.bars[5]), 0)
        self.assertEqual(self.feed.status()["history"]["selected_completed_5m"], 0)
        self.assertEqual(self.feed.status()["history"]["restoration_status"], "NOT_RESTORED_ON_RECONNECT_OR_RESTART")
        with self.store.paper_transaction(write=False) as conn:
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM angel_feed_candles WHERE connection_id=?",
                (old_connection,)).fetchone()[0], 0)

    def test_session_selector_never_splices_a_missing_intraday_interval(self):
        self.session(19, until_count=5)
        complete = [row for row in self.feed.bars[5] if row["is_complete"]]
        missing_timestamp = complete[2]["timestamp"]
        kept = [row for row in self.feed.bars[5] if row["timestamp"] != missing_timestamp]
        self.feed.bars[5].clear()
        self.feed.bars[5].extend(kept)
        selected = self.feed._history_rows(5, self.now)
        self.assertEqual([row["timestamp"] for row in selected], [row["timestamp"] for row in complete[3:]])

    def test_daily_sequence_decrease_still_fails_closed_instead_of_guessing_reset(self):
        self.session(19, until_count=2)
        self.sequence = 0
        with self.assertRaisesRegex(FeedError, "OUT_OF_ORDER_OR_CONFLICTING_SEQUENCE"):
            self.push(datetime(2026, 10, 20, 9, 15, tzinfo=IST), 1000)
        self.assertFalse(self.feed.status()["connected"])
        self.assertFalse(self.feed.status()["live_signal_allowed"])

