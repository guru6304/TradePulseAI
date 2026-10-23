"""OFFLINE authored DhanHQ v2 wire fixtures. Never broker acceptance."""
import copy
import json
import struct
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import test_bot  # established credential-free bootstrap
from config import BotConfig
from dhan_feed import DhanLiveFeed, FeedError, PacketParser, WebSocketTransport
from storage import SQLitePersistenceStore
from strategies import IST, validate_candles


def packet(ts, *, price=100.0, volume=1000, quantity=5, code=8, security=2885, segment=1):
    size = {2: 16, 4: 50, 5: 12, 6: 16, 8: 162, 50: 10}[code]
    value = bytearray(size)
    struct.pack_into("<BHB I", value, 0, code, size, segment, security)
    if code == 50:
        struct.pack_into("<H", value, 8, volume)
    elif code == 2:
        struct.pack_into("<fI", value, 8, price, int(ts.timestamp()))
    elif code == 5:
        struct.pack_into("<I", value, 8, volume)
    elif code == 6:
        struct.pack_into("<fI", value, 8, price, volume)
    else:
        struct.pack_into("<fhIfiii", value, 8, price, quantity, int(ts.timestamp()), price, volume, 500, 600)
        offset = 34
        if code == 8:
            struct.pack_into("<III", value, offset, 20, 30, 10)
            offset += 12
        struct.pack_into("<ffff", value, offset, 100, 0, max(price, 110), min(price, 90))
        if code == 8:
            for i in range(5):
                struct.pack_into("<iihhff", value, 62+i*20, 10+i, 20+i, 2, 3, price-1-i, price+1+i)
    return bytes(value)


class FakePeer:
    def __init__(self):
        self.messages = []
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(json.loads(value))

    def recv(self, timeout=1):
        if not self.messages:
            raise TimeoutError()
        value = self.messages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


class TestDhanFeed(unittest.TestCase):
    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.config = BotConfig(active_broker="paper_sim", telegram_dry_run=True,
            enable_background_scheduler=False, dhan_client_id="OFFLINE_CLIENT", dhan_access_token="OFFLINE_TOKEN")
        self.meta = copy.deepcopy(self.config.equity_watchlist[0])
        self.ts = datetime(2026, 10, 22, 9, 15, 50, tzinfo=IST)
        self.now = self.ts+timedelta(seconds=1)
        self.peers = []
        def factory():
            peer = FakePeer()
            self.peers.append(peer)
            return peer
        self.feed = DhanLiveFeed(self.config, self.store, [self.meta], factory, clock=lambda: self.now)
        self.addCleanup(self.feed.stop)
        self.feed.connect()
        guard = patch("urllib.request.urlopen", side_effect=AssertionError("External transport forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def push(self, ts=None, **kwargs):
        ts = ts or self.ts
        self.now = ts+timedelta(seconds=1)
        self.peers[-1].messages.append(packet(ts, **kwargs))
        return self.feed.poll_once()

    def minute_series(self, end_minutes=10):
        first = self.ts
        i = 0
        while first+timedelta(seconds=i*10) <= first.replace(second=0)+timedelta(minutes=end_minutes):
            self.push(first+timedelta(seconds=i*10), volume=1000+i*5, price=100+(i%3))
            i += 1

    def test_official_little_endian_full_quote_depth_and_absent_fields(self):
        event = self.push()[0]
        self.assertEqual(event["instrument_identity"]["symbol"], "RELIANCE")
        self.assertEqual(event["cumulative_volume"], 1000)
        self.assertEqual(event["total_pending_buy"], 600)
        self.assertEqual(event["depth"][0], dict(bid_quantity=10, ask_quantity=20,
            bid_orders=2, ask_orders=3, bid_price=99, ask_price=101))
        self.assertIsNone(event["depth_exchange_timestamp"])
        self.assertIsNone(event["day_ohlc"]["close"])
        self.assertEqual(event["data_mode"], "FIXTURE")
        ticker = PacketParser().feed(packet(self.ts, code=2))[0]
        self.assertIsNone(ticker["cumulative_volume"])
        self.assertIsNone(ticker["depth"])
        quote = PacketParser().feed(packet(self.ts, code=4))[0]
        self.assertIsNone(quote["open_interest"])
        self.assertIsNone(quote["depth"])

    def test_incremental_fragments_multiple_packets_and_exact_sizes(self):
        parser = PacketParser()
        data = packet(self.ts, code=4)+packet(self.ts, code=5)+packet(self.ts, code=6)
        self.assertEqual(parser.feed(data[:7]), [])
        self.assertEqual(parser.feed(data[7:20]), [])
        self.assertEqual([p["packet_type"] for p in parser.feed(data[20:])], [4, 5, 6])
        self.assertEqual(parser.buffer, b"")

    def test_unknown_schema_malformed_length_text_and_backpressure_reject(self):
        bad = bytearray(packet(self.ts))
        bad[0] = 7  # Official enum exists; no published layout accepted by this adapter.
        for value in (bytes(bad), b"x"*65537, "not binary"):
            with self.subTest(kind=type(value).__name__, size=len(value)):
                with self.assertRaises(FeedError):
                    PacketParser().feed(value)
        bad = bytearray(packet(self.ts))
        struct.pack_into("<H", bad, 1, 161)
        self.peers[-1].messages.append(bytes(bad))
        with self.assertRaisesRegex(FeedError, "UNKNOWN_PACKET_SCHEMA"):
            self.feed.poll_once()
        self.assertFalse(self.feed.status()["connected"])

    def test_nan_negative_prices_and_crossed_depth_fail_closed(self):
        for pos, fmt, value in ((8, "<f", float("nan")), (18, "<f", -1), (74, "<f", -1), (74, "<f", 200)):
            data = bytearray(packet(self.ts))
            struct.pack_into(fmt, data, pos, value)
            with self.subTest(pos=pos), self.assertRaises(FeedError):
                PacketParser().feed(bytes(data))

    def test_subscription_scope_canonical_mapping_and_unsubscription(self):
        self.assertEqual(self.peers[0].sent[0], dict(RequestCode=21, InstrumentCount=1,
            InstrumentList=[dict(ExchangeSegment="NSE_EQ", SecurityId="2885")]))
        wrong = dict(self.meta, dhan_id="1333")
        with self.assertRaises(ValueError):
            DhanLiveFeed(self.config, self.store, [wrong], transport_factory=FakePeer)
        with self.assertRaises(FeedError):
            DhanLiveFeed(self.config, self.store, [self.meta, self.meta], transport_factory=FakePeer)
        with self.assertRaises(FeedError):
            DhanLiveFeed(self.config, self.store, [], transport_factory=FakePeer)
        second = self.config.equity_watchlist[1]
        feed = DhanLiveFeed(self.config, self.store, [self.meta, second], transport_factory=FakePeer, clock=lambda:self.now)
        self.addCleanup(feed.stop)
        feed.connect()
        feed.unsubscribe([second])
        self.assertEqual(feed.transport.sent[-1]["RequestCode"], 22)
        with self.assertRaisesRegex(FeedError, "INSTRUMENT_UNSUBSCRIBED"):
            feed.get_candles(second)
        feed.subscribe([second])
        self.assertEqual(feed.transport.sent[-1]["RequestCode"], 21)
        with self.assertRaises(FeedError):
            feed.subscribe([second])

    def test_unknown_or_conflicting_security_mapping_rejects(self):
        with self.assertRaisesRegex(FeedError, "UNKNOWN_OR_UNSUBSCRIBED_INSTRUMENT"):
            self.push(security=1333)
        self.assertEqual(self.feed.status()["state"], "UNAVAILABLE")
        self.assertFalse(self.feed.status()["live_signal_allowed"])

    def test_socket_connect_is_not_authentication_or_subscription_confirmation(self):
        status = self.feed.status()
        self.assertEqual(status["state"], "CONNECTED_AWAITING_DATA")
        self.assertEqual(status["observed_subscriptions"], 0)
        self.assertFalse(status["live_signal_allowed"])
        self.push()
        self.assertEqual(self.feed.status()["observed_subscriptions"], 1)
        self.assertEqual(self.feed.status()["last_event_at"], self.ts.isoformat())

    def test_authentication_permission_and_subscription_rejections(self):
        for code, expected in ((808, "DHAN_AUTHENTICATION_FAILED"), (806, "DHAN_DATA_PERMISSION_MISSING"), (813, "DHAN_SUBSCRIPTION_REJECTED_813")):
            if not self.feed.transport:
                self.feed.connect()
            with self.subTest(code=code), self.assertRaisesRegex(FeedError, expected):
                self.push(code=50, volume=code)
            self.assertTrue(self.peers[-1].closed)

    def test_duplicate_packets_and_depth_updates_do_not_double_count_trade_volume(self):
        self.push()
        self.push()
        self.assertEqual(self.feed.status()["duplicate_packets"], 1)
        self.push(self.ts+timedelta(seconds=10), volume=1005)
        before = self.feed.current[(1, "2885")]["volume"]
        value = bytearray(packet(self.ts+timedelta(seconds=10), volume=1005))
        struct.pack_into("<i", value, 62, 99)
        self.peers[-1].messages.append(bytes(value))
        self.feed.poll_once()
        self.assertEqual(self.feed.current[(1, "2885")]["volume"], before)
        self.assertEqual(before, 5)  # First trade of 09:16 counted exactly once.
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dhan_feed_events").fetchone()[0], 3)

    def test_candle_exact_minute_and_five_minute_boundaries_persist_lineage(self):
        self.minute_series()
        bars = list(self.feed.bars[(1, "2885")][1])
        self.assertEqual(bars[0]["timestamp"], "2026-10-22T09:15:00+05:30")
        self.assertFalse(bars[0]["is_complete"])
        self.assertIsNone(bars[0]["volume"])
        five = list(self.feed.bars[(1, "2885")][5])[-1]
        self.assertEqual(five["timestamp"], "2026-10-22T09:20:00+05:30")
        self.assertTrue(five["is_complete"])
        self.assertEqual(five["volume"], 150)
        self.assertEqual(five["high"], 102)
        self.assertEqual(five["low"], 100)
        self.assertEqual(five["component_count"], 5)
        self.assertEqual(len(five["source_event_hashes"]), 30)
        self.assertTrue(validate_candles([five], interval_min=5, now=self.now)[0]["is_simulated"])
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dhan_feed_candles WHERE interval_min=5").fetchone()[0], 2)
            forming = json.loads(conn.execute("SELECT payload_json FROM dhan_feed_forming").fetchone()[0])
            self.assertFalse(forming["is_complete"])
            self.assertEqual(forming["timestamp"], "2026-10-22T09:25:00+05:30")

    def test_unobserved_volume_jump_incomplete_not_invented_ohlc(self):
        self.push()
        self.push(self.ts+timedelta(seconds=10), volume=1500)
        self.push(self.ts+timedelta(seconds=20), volume=1505)
        bar = list(self.feed.bars[(1, "2885")][1])[0]
        self.assertFalse(bar["is_complete"])
        current = self.feed.current[(1, "2885")]
        self.assertIn("UNOBSERVED_TRADES_IN_VOLUME_DELTA", current["quality_reasons"])

    def test_ticker_or_index_missing_volume_never_creates_candle(self):
        self.push(code=2)
        self.push(self.ts+timedelta(seconds=10), code=2)
        self.assertEqual(self.feed.current, {})
        self.assertEqual(self.feed.status()["candle_counts"]["RELIANCE"]["1"], 0)

    def test_out_of_order_future_delayed_and_outside_session_rejected(self):
        self.push()
        cases = [(self.ts-timedelta(seconds=1), self.now, "OUT_OF_ORDER_EVENT"),
            (self.ts+timedelta(seconds=10), self.ts, "FUTURE_EXCHANGE_TIMESTAMP"),
            (self.ts, self.ts+timedelta(seconds=40), "STALE_OR_DELAYED_TRADE"),
            (self.ts.replace(hour=8), self.ts.replace(hour=8)+timedelta(seconds=1), "OUTSIDE_TRADING_SESSION")]
        for ts, now, code in cases:
            if not self.feed.transport:
                self.feed.connect()
                if code == "OUT_OF_ORDER_EVENT":
                    self.push()
            self.now = now
            self.peers[-1].messages.append(packet(ts, volume=1005))
            with self.subTest(code=code), self.assertRaisesRegex(FeedError, code):
                self.feed.poll_once()

    def test_cumulative_volume_reset_and_price_conflict_rejected(self):
        self.push()
        with self.assertRaisesRegex(FeedError, "CUMULATIVE_VOLUME_RESET"):
            self.push(self.ts+timedelta(seconds=10), volume=999)
        self.feed.connect()
        self.push()
        with self.assertRaisesRegex(FeedError, "PRICE_CHANGED_WITHOUT_TRADE_VOLUME"):
            self.push(self.ts+timedelta(seconds=10), volume=1000, price=101)

    def test_gap_reconnect_new_lineage_resubscribe_no_stale_replay(self):
        self.minute_series()
        original = self.feed.connection_id
        self.feed.reconnect()
        self.assertEqual(self.feed.status()["reconnects"], 1)
        self.assertNotEqual(original, self.feed.connection_id)
        self.assertTrue(self.peers[0].closed)
        self.assertEqual(self.peers[-1].sent[0]["RequestCode"], 21)
        self.assertEqual(len(self.feed.bars[(1, "2885")][5]), 0)
        self.assertEqual(self.feed.status()["observed_subscriptions"], 0)
        self.push(self.ts+timedelta(minutes=11), volume=1400)
        self.push(self.ts+timedelta(minutes=13), volume=1405)
        bar = list(self.feed.bars[(1, "2885")][1])[-1]
        self.assertFalse(bar["is_complete"])
        self.assertIn("UNPROVEN_CLOSE_BOUNDARY", bar["quality_reasons"])
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(DISTINCT connection_id) FROM dhan_feed_events").fetchone()[0], 2)

    def test_staleness_unconfirmed_timeout_and_disconnect_have_no_simulation_fallback(self):
        self.now += timedelta(seconds=31)
        self.feed.poll_once()
        self.assertEqual(self.feed.status()["state"], "UNAVAILABLE")
        self.feed.connect()
        self.push()
        self.now += timedelta(seconds=31)
        self.feed.check_health()
        self.assertEqual(self.feed.reason, "STALE_FEED")
        self.feed.connect()
        self.peers[-1].messages.append(ConnectionError("secret should never surface"))
        with self.assertRaisesRegex(FeedError, "^DISCONNECTED$"):
            self.feed.poll_once()

    def test_fixture_transport_cannot_promote_to_live_or_existing_scanner(self):
        self.minute_series()
        with self.assertRaisesRegex(FeedError, "FIXTURE_NOT_LIVE_QUALIFIED"):
            self.feed.get_candles(self.meta, 5, self.now)
        from brokers import assess_live_candle_batch
        _, result = assess_live_candle_batch(list(self.feed.bars[(1, "2885")][5]), 5, self.now,
            provider="dhan", context="SCANNER", normalized_ist=True)
        self.assertFalse(result["live_signal_allowed"])
        self.assertEqual(result["reason_code"], "INVALID_PROVENANCE")
        self.assertEqual(self.config.active_broker, "paper_sim")
        self.assertTrue(self.config.telegram_dry_run)
        self.assertFalse(self.config.enable_background_scheduler)

    def test_shutdown_closes_resource_and_is_idempotent(self):
        self.feed.stop()
        self.feed.stop()
        self.assertTrue(self.peers[0].closed)
        self.assertEqual(self.peers[0].sent[-1], dict(RequestCode=12))
        self.assertEqual(self.feed.status()["status"], "STOPPED")

    def test_real_transport_missing_credentials_and_backend_fail_safely(self):
        config = copy.deepcopy(self.config)
        config.dhan_access_token = ""
        with self.assertRaisesRegex(FeedError, "DHAN_CREDENTIALS_MISSING"):
            WebSocketTransport(config)

    def test_production_connect_enforces_read_only_safety_before_transport(self):
        config = copy.deepcopy(self.config)
        config.telegram_dry_run = False
        feed = DhanLiveFeed(config, self.store, [self.meta], clock=lambda:self.now)
        self.addCleanup(feed.stop)
        with patch("dhan_feed.WebSocketTransport", side_effect=AssertionError("Must not connect")) as transport:
            with self.assertRaisesRegex(FeedError, "READ_ONLY_FEED_SAFETY_REQUIRED"):
                feed.connect()
            transport.assert_not_called()

    def test_official_unsigned_quantities_and_missing_depth_are_not_signed_guesses(self):
        data = bytearray(packet(self.ts))
        struct.pack_into("<H", data, 12, 40000)
        struct.pack_into("<I", data, 26, 3000000000)
        event = PacketParser().feed(bytes(data))[0]
        self.assertEqual(event["last_trade_quantity"], 40000)
        self.assertEqual(event["total_pending_sell"], 3000000000)
        struct.pack_into("<IIHHff", data, 62, 0, 0, 0, 0, 0, 0)
        event = PacketParser().feed(bytes(data))[0]
        self.assertIsNone(event["depth"][0]["bid_price"])
        self.assertIsNone(event["depth"][0]["ask_price"])

    def test_bad_latest_bar_cannot_reuse_old_completed_tail_for_health(self):
        self.minute_series()
        key = (1, "2885")
        self.assertTrue(self.feed.bars[key][5][-1]["is_complete"])
        # A discontinuity invalidates a later bar; old complete rows stay audit-only.
        broken = copy.deepcopy(self.feed.bars[key][5][-1])
        broken.update(timestamp="2026-10-22T09:25:00+05:30", is_complete=False)
        self.feed.bars[key][5].append(broken)
        rows, assessment = self.feed._tail_assessment(key, 5, self.now)
        self.assertEqual(rows, [])
        self.assertFalse(assessment["live_signal_allowed"])
        self.assertEqual(assessment["reason_code"], "EMPTY")
        self.assertFalse(self.feed.status()["live_signal_allowed"])

    def test_threaded_start_and_stop_complete_without_network_or_leaks(self):
        entered = threading.Event()
        def receive(timeout=1):
            entered.set()
            self.feed._stop.wait(.01)
            raise TimeoutError()
        with patch.object(self.peers[-1], "recv", side_effect=receive):
            thread = self.feed.start()
            self.assertTrue(entered.wait(2))
            self.feed.stop()
            self.assertFalse(thread.is_alive())
        self.assertTrue(self.peers[-1].closed)

    def test_persistence_failure_revokes_feed_and_does_not_expose_memory_bar(self):
        with patch.object(self.store, "paper_transaction", side_effect=RuntimeError("OFFLINE write failure")):
            with self.assertRaisesRegex(FeedError, "INGESTION_OR_PERSISTENCE_FAILURE"):
                self.push()
        self.assertEqual(self.feed.status()["status"], "UNAVAILABLE")
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        self.assertEqual(self.feed.current, {})
        self.assertTrue(self.peers[-1].closed)
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dhan_feed_events").fetchone()[0], 0)

    def test_depth_level_order_is_validated_without_aggressor_volume_estimates(self):
        data = bytearray(packet(self.ts))
        struct.pack_into("<f", data, 94, 99.5)  # Level2 bid must not exceed level1 bid99.
        with self.assertRaisesRegex(FeedError, "UNORDERED_DEPTH_LEVELS"):
            PacketParser().feed(bytes(data))
        event = self.push()[0]
        self.assertNotIn("buy_volume", event)
        self.assertNotIn("sell_volume", event)

    def test_automatic_reconnect_counts_new_connection_after_timeout_fault(self):
        original = self.feed.connection_id
        self.now += timedelta(seconds=31)
        self.feed.check_health()
        self.assertFalse(self.feed.status()["connected"])
        with patch.object(self.feed, "poll_once", side_effect=self.feed._stop.set):
            thread = self.feed.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertNotEqual(original, self.feed.connection_id)
        self.assertEqual(self.feed.status()["reconnects"], 1)
        self.assertEqual(self.peers[-1].sent[0]["RequestCode"], 21)

