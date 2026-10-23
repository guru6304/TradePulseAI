"""OFFLINE authored official-SmartAPI-schema fixtures, never live acceptance."""
import copy
import hashlib
import json
import struct
import threading
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch

import test_bot
from angel_feed import AngelLiveFeed,FeedError,PacketParser,WebSocketTransport,ENDPOINT
from brokers import AngelOneSmartAPIAdapter,assess_live_candle_batch
from config import BotConfig
from storage import SQLitePersistenceStore
from strategies import IST


def packet(ts,*,mode=3,token="2885",sequence=1,price=10000,volume=1000,quantity=5,
           trade_ts=None,trade_ms=False,exchange=1):
    value=bytearray({1:51,2:123,3:379}[mode])
    struct.pack_into("<BB",value,0,mode,exchange)
    value[2:2+len(token)]=token.encode()
    struct.pack_into("<qqq",value,27,sequence,int(ts.timestamp()*1000),price)
    if mode>=2:
        struct.pack_into("<qqqddqqqq",value,51,quantity,price,volume,100.5,200.25,10000,11000,9000,9900)
    if mode==3:
        trade_ts=ts if trade_ts is None else trade_ts
        raw_time=int(trade_ts.timestamp()*(1000 if trade_ms else 1)) if isinstance(trade_ts,datetime) else trade_ts
        struct.pack_into("<qqd",value,123,raw_time,0,float("nan"))  # Documented dummy ignored.
        for i in range(10):
            buy=i<5
            level=i%5
            struct.pack_into("<HqqH",value,147+i*20,1 if buy else 0,10+level,
                price-5-level*5 if buy else price+5+level*5,2+level)
        struct.pack_into("<qqqq",value,347,12000,8000,13000,7000)
    return bytes(value)


class FakePeer:
    def __init__(self):
        self.messages=[]
        self.sent=[]
        self.closed=False

    def send(self,value):
        self.sent.append(value if value=="ping" else json.loads(value))

    def recv(self,timeout=1):
        if not self.messages:
            raise TimeoutError()
        value=self.messages.pop(0)
        if isinstance(value,Exception):
            raise value
        return value

    def close(self):
        self.closed=True


class TestAngelFeed(unittest.TestCase):
    def setUp(self):
        self.config=BotConfig(active_broker="paper_sim",telegram_dry_run=True,
            enable_background_scheduler=False,angel_scrip_master_path="")
        self.adapter=AngelOneSmartAPIAdapter(self.config)
        self.meta=self.adapter.resolve_instrument("RELIANCE")
        self.meta["current_master_sha256"]="a"*64
        self.store=SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.ts=datetime(2026,10,23,9,15,50,tzinfo=IST)
        self.now=self.ts+timedelta(seconds=1)
        self.tick=0.0
        self.sequence=0
        self.peers=[]
        def factory():
            peer=FakePeer()
            self.peers.append(peer)
            return peer
        self.feed=AngelLiveFeed(self.config,self.store,self.meta,transport_factory=factory,
            clock=lambda:self.now,monotonic=lambda:self.tick)
        self.addCleanup(self.feed.stop)
        self.feed.connect()
        guard=patch("urllib.request.urlopen",side_effect=AssertionError("No external transport"))
        guard.start()
        self.addCleanup(guard.stop)

    def push(self,ts=None,**kwargs):
        ts=ts or self.ts
        self.now=ts+timedelta(seconds=1)
        self.sequence+=1
        raw=packet(ts,sequence=self.sequence,**kwargs)
        self.peers[-1].messages.append(raw)
        return self.feed.poll_once()

    def series(self):
        for i in range(56):
            self.push(self.ts+timedelta(seconds=i*10),volume=1000+i*5,price=10000+(i%3)*5)

    def test_documented_modes_field_offsets_paise_and_absent_fields(self):
        parser=PacketParser()
        ltp=parser.parse(packet(self.ts,mode=1))
        self.assertEqual(ltp["ltp"],100)
        self.assertIsNone(ltp["cumulative_volume"])
        self.assertIsNone(ltp["depth"])
        quote=parser.parse(packet(self.ts,mode=2))
        self.assertEqual(quote["last_trade_quantity"],5)
        self.assertEqual(quote["total_pending_buy"],100.5)
        self.assertEqual(quote["total_pending_sell"],200.25)
        self.assertIsNone(quote["last_trade_timestamp"])
        snap=parser.parse(packet(self.ts))
        self.assertEqual(snap["last_trade_timestamp"],self.ts.isoformat())
        self.assertEqual(snap["last_trade_timestamp_unit"],"EPOCH_SECONDS")
        self.assertIsNone(snap["oi_change_percent"])
        self.assertIsNone(snap["depth_exchange_timestamp"])
        self.assertEqual(snap["price_limits"]["upper_circuit"],120)

    def test_depth_documented_buy_flag_one_sell_zero_no_implicit_reversal(self):
        snap=PacketParser().parse(packet(self.ts))
        self.assertEqual(snap["depth"]["buy"][0],dict(quantity=10,price=99.95,orders=2))
        self.assertEqual(snap["depth"]["sell"][0],dict(quantity=10,price=100.05,orders=2))
        self.assertNotIn("buy_volume",snap)
        self.assertNotIn("sell_volume",snap)

    def test_complete_websocket_messages_and_multiple_bounded_packets(self):
        raw=packet(self.ts,mode=1)+packet(self.ts,mode=2)+packet(self.ts)
        self.assertEqual([e[1]["packet_type"] for e in PacketParser().feed(raw)],[1,2,3])
        with self.assertRaisesRegex(FeedError,"ANGEL_PACKET_SCHEMA_UNKNOWN"):
            PacketParser().feed(raw[:-1])

    def test_bad_modes_sizes_empty_text_and_large_burst_are_rejected(self):
        bad=bytearray(packet(self.ts))
        bad[0]=4
        for raw in (bytes(bad),packet(self.ts)[:-1],b"",b"x"*65537,"binary required"):
            with self.subTest(size=len(raw)),self.assertRaises(FeedError):
                PacketParser().feed(raw)

    def test_bad_token_padding_exchange_negative_and_nan_fields_reject(self):
        cases=[(1,"<B",2),(43,"<q",0),(51,"<q",-1),(75,"<d",float("nan")),
            (149,"<q",-1),(147,"<H",2),(157,"<q",20000)]
        for offset,fmt,value in cases:
            raw=bytearray(packet(self.ts))
            struct.pack_into(fmt,raw,offset,value)
            with self.subTest(offset=offset),self.assertRaises(FeedError):
                PacketParser().parse(bytes(raw))
        raw=bytearray(packet(self.ts))
        raw[26]=88
        with self.assertRaisesRegex(FeedError,"INVALID_INSTRUMENT_TOKEN"):
            PacketParser().parse(bytes(raw))

    def test_trade_time_unit_resolution_preserves_raw_and_rejects_ambiguous_stale(self):
        parser=PacketParser()
        snap=parser.parse(packet(self.ts,trade_ms=True))
        self.assertEqual(snap["last_trade_timestamp"],self.ts.isoformat())
        self.assertEqual(snap["last_trade_timestamp_unit"],"EPOCH_MILLISECONDS")
        for time_value in (0,self.ts+timedelta(seconds=1),self.ts-timedelta(seconds=31)):
            event=parser.parse(packet(self.ts,trade_ts=time_value))
            self.assertIsNone(event["last_trade_timestamp"])
            self.assertEqual(event["trade_clock_resolution"],"UNRESOLVED_OR_STALE_NO_CANDLES")

    def test_constructor_validates_adapter_identity_and_rejects_index(self):
        bad=copy.deepcopy(self.meta)
        bad["angel_token"]="1333"
        with self.assertRaises(ValueError):
            AngelLiveFeed(self.config,self.store,bad,transport_factory=FakePeer)
        with self.assertRaisesRegex(FeedError,"ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED"):
            AngelLiveFeed(self.config,self.store,self.config.equity_watchlist[0],transport_factory=FakePeer)
        index=self.adapter.resolve_instrument("NIFTY")
        with self.assertRaisesRegex(FeedError,"ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED"):
            AngelLiveFeed(self.config,self.store,index,transport_factory=FakePeer)

    def test_unknown_instrument_observation_fails_before_live_state(self):
        with self.assertRaisesRegex(FeedError,"ANGEL_INSTRUMENT_IDENTITY_MISMATCH"):
            self.push(token="1333")
        self.assertFalse(self.feed.status()["connected"])
        self.assertFalse(self.feed.status()["live_signal_allowed"])

    def test_connection_and_subscription_are_pending_until_observation(self):
        self.assertEqual(self.peers[0].sent[0],dict(correlationID="tpangel001",action=1,
            params=dict(mode=3,tokenList=[dict(exchangeType=1,tokens=["2885"])])))
        self.assertEqual(self.feed.status()["state"],"CONNECTED_AWAITING_DATA")
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        event=self.push()[0]
        self.assertEqual(event["data_mode"],"FIXTURE")
        self.assertEqual(self.feed.status()["observed_subscriptions"],1)
        self.assertEqual(event["current_master_sha256"],"a"*64)

    def test_subscription_rejection_does_not_leak_provider_message(self):
        self.peers[0].messages.append(json.dumps(dict(errorCode="E1002",errorMessage="PRIVATE_TOKEN")))
        with self.assertRaisesRegex(FeedError,"^ANGEL_SUBSCRIPTION_REJECTED_E1002$"):
            self.feed.poll_once()
        self.assertNotIn("PRIVATE_TOKEN",json.dumps(self.feed.status()))
        self.assertTrue(self.peers[0].closed)

    def test_text_heartbeat_ping_pong_and_timeout(self):
        self.peers[0].messages.append("pong")
        self.feed.poll_once()
        self.assertEqual(self.peers[0].sent[-1],"ping")
        self.assertTrue(self.feed.status()["last_pong_observed"])
        self.tick=10
        self.feed.poll_once()
        self.assertEqual(self.feed.pending_pong,10)
        self.tick=40
        with self.assertRaisesRegex(FeedError,"ANGEL_HEARTBEAT_TIMEOUT"):
            self.feed.poll_once()
        self.assertFalse(self.feed.status()["connected"])

    def test_duplicate_sequence_and_out_of_order_are_explicit(self):
        self.push()
        raw=packet(self.ts,sequence=1)
        self.peers[-1].messages.append(raw)
        self.assertEqual(self.feed.poll_once(),[])
        self.assertEqual(self.feed.status()["duplicate_packets"],1)
        self.peers[-1].messages.append(packet(self.ts,sequence=1,volume=1005))
        with self.assertRaisesRegex(FeedError,"OUT_OF_ORDER_OR_CONFLICTING_SEQUENCE"):
            self.feed.poll_once()

    def test_future_stale_and_out_of_order_feed_timestamps_reject(self):
        for at,now,expected in ((self.ts+timedelta(seconds=6),self.ts,"FUTURE_EXCHANGE_TIMESTAMP"),
            (self.ts,self.ts+timedelta(seconds=31),"STALE_EXCHANGE_TIMESTAMP")):
            if not self.feed.transport:
                self.feed.connect()
            self.now=now
            self.peers[-1].messages.append(packet(at))
            with self.subTest(code=expected),self.assertRaisesRegex(FeedError,expected):
                self.feed.poll_once()
        self.feed.connect()
        self.push()
        self.now=self.ts+timedelta(seconds=1)
        self.peers[-1].messages.append(packet(self.ts-timedelta(seconds=1),sequence=2))
        with self.assertRaisesRegex(FeedError,"OUT_OF_ORDER_EVENT"):
            self.feed.poll_once()

    def test_quote_ltp_and_missing_trade_clock_never_create_trade_candles(self):
        for mode in (1,2):
            self.push(mode=mode)
        self.push(trade_ts=0)
        self.assertIsNone(self.feed.current)
        self.assertEqual(len(self.feed.bars[1]),0)

    def test_volume_deltas_depth_only_updates_and_first_baseline_unknown(self):
        self.push()
        self.assertIsNone(self.feed.current["volume"])
        self.push(self.ts+timedelta(seconds=10),volume=1005)
        self.assertEqual(self.feed.current["volume"],5)
        self.push(self.ts+timedelta(seconds=11),volume=1005,trade_ts=self.ts+timedelta(seconds=10))
        self.assertEqual(self.feed.current["volume"],5)
        self.assertEqual(self.feed.status()["received_events"],3)

    def test_missing_intervening_trades_cannot_invent_high_or_complete_bar(self):
        self.push()
        self.push(self.ts+timedelta(seconds=10),volume=2000)
        self.assertIn("UNOBSERVED_TRADES_IN_VOLUME_DELTA",self.feed.current["quality_reasons"])
        self.assertFalse(self.feed.current["_valid"])
        self.assertFalse(self.feed.bars[1][-1]["is_complete"])

    def test_cumulative_reset_or_price_change_without_volume_rejects(self):
        self.push()
        with self.assertRaisesRegex(FeedError,"CUMULATIVE_VOLUME_RESET"):
            self.push(self.ts+timedelta(seconds=10),volume=999)
        self.feed.connect()
        self.push()
        with self.assertRaisesRegex(FeedError,"PRICE_CHANGED_WITHOUT_TRADE_VOLUME"):
            self.push(self.ts+timedelta(seconds=10),price=10005)

    def test_exact_one_and_five_minute_bars_are_persisted_with_raw_lineage(self):
        self.series()
        one=list(self.feed.bars[1])
        self.assertFalse(one[0]["is_complete"])
        self.assertIsNone(one[0]["volume"])
        five=self.feed.bars[5][-1]
        self.assertEqual(five["timestamp"],"2026-10-23T09:20:00+05:30")
        self.assertTrue(five["is_complete"])
        self.assertEqual(five["volume"],150)
        self.assertEqual(five["high"],100.10)
        self.assertEqual(five["low"],100)
        self.assertEqual(five["component_count"],5)
        self.assertEqual(len(five["source_event_ids"]),30)
        with self.store.paper_transaction(write=False) as conn:
            for event_id in five["source_event_ids"]:
                raw,raw_hash,payload,payload_hash=conn.execute("SELECT raw_packet,raw_sha256,payload_json,payload_sha256 FROM angel_feed_events WHERE event_id=?",(event_id,)).fetchone()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),raw_hash)
                self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(),payload_hash)
                self.assertEqual(json.loads(payload)["instrument_identity"]["symbol"],"RELIANCE")
            forming=json.loads(conn.execute("SELECT payload_json FROM angel_feed_forming").fetchone()[0])
            baseline=json.loads(conn.execute("SELECT payload_json FROM angel_feed_events WHERE event_id=?",(
                five["volume_baseline_event_id"],)).fetchone()[0])
            last=json.loads(conn.execute("SELECT payload_json FROM angel_feed_events WHERE event_id=?",(
                five["source_event_ids"][-1],)).fetchone()[0])
            self.assertEqual(last["cumulative_volume"]-baseline["cumulative_volume"],five["volume"])
            self.assertFalse(forming["is_complete"])
            self.assertEqual(forming["timestamp"],"2026-10-23T09:25:00+05:30")

    def test_fixture_candles_cannot_be_live_consumer_input(self):
        self.series()
        with self.assertRaisesRegex(FeedError,"FIXTURE_NOT_LIVE_QUALIFIED"):
            self.feed.get_candles(self.meta)
        _,assessment=assess_live_candle_batch(list(self.feed.bars[5]),5,self.now,
            provider="angelone",context="SCANNER",normalized_ist=True)
        self.assertFalse(assessment["live_signal_allowed"])
        self.assertEqual(assessment["reason_code"],"INVALID_PROVENANCE")
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        self.assertEqual(self.config.active_broker,"paper_sim")

    def test_holiday_and_outside_session_observations_do_not_form_candles(self):
        self.config.configured_holidays=["2026-10-23"]
        self.push()
        self.assertIsNone(self.feed.current)
        self.config.configured_holidays=[]
        self.push(self.ts.replace(hour=16))
        self.assertIsNone(self.feed.current)

    def test_gap_reconnect_new_lineage_and_finite_retry_budget(self):
        self.series()
        old=self.feed.connection_id
        self.feed.reconnect()
        self.assertNotEqual(old,self.feed.connection_id)
        self.assertEqual(len(self.feed.bars[5]),0)
        self.assertEqual(self.feed.status()["reconnects"],1)
        self.assertEqual(self.peers[-1].sent[0]["action"],1)
        self.push(self.ts+timedelta(minutes=11),volume=2000)
        self.push(self.ts+timedelta(minutes=13),volume=2005)
        self.assertFalse(self.feed.bars[1][-1]["is_complete"])
        self.feed.reconnect()
        with self.assertRaisesRegex(FeedError,"RECONNECT_BUDGET_EXHAUSTED"):
            self.feed.reconnect()
        self.assertFalse(self.feed.status()["connected"])

    def test_stale_trade_stream_invalidates_health_without_simulation_fallback(self):
        self.push()
        self.now+=timedelta(seconds=31)
        self.feed.check_health()
        self.assertEqual(self.feed.reason,"ANGEL_FEED_STALE")
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        self.assertEqual(self.feed.data_mode,"FIXTURE")

    def test_unsubscribe_same_scope_blocks_further_packets(self):
        self.feed.unsubscribe()
        self.assertEqual(self.peers[0].sent[-1]["action"],0)
        with self.assertRaisesRegex(FeedError,"ANGEL_INSTRUMENT_IDENTITY_MISMATCH"):
            self.push()

    def test_transaction_failure_stops_feed_without_persisted_partial_event(self):
        with patch.object(self.feed,"_aggregate",side_effect=RuntimeError("PRIVATE_VALUE")):
            with self.assertRaisesRegex(FeedError,"^ANGEL_STREAM_OR_PERSISTENCE_FAILURE$"):
                self.push()
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM angel_feed_events").fetchone()[0],0)
        self.assertTrue(self.peers[0].closed)
        self.assertNotIn("PRIVATE_VALUE",json.dumps(self.feed.status()))

    def test_secret_free_transport_failure_and_tls_headers(self):
        credentials=dict(auth_token="OFFLINE_JWT",api_key="OFFLINE_API",client_code="OFFLINE_CLIENT",feed_token="OFFLINE_FEED")
        with patch("websockets.sync.client.connect",return_value=FakePeer()) as connect:
            transport=WebSocketTransport(credentials)
            args,kwargs=connect.call_args
            self.assertEqual(args,(ENDPOINT,))
            self.assertEqual(kwargs["additional_headers"]["x-feed-token"],"OFFLINE_FEED")
            self.assertNotIn("ssl",kwargs)
            self.assertIsNone(kwargs["proxy"])
            self.assertEqual(kwargs["max_queue"],16)
            transport.close()
        with patch("websockets.sync.client.connect",side_effect=RuntimeError("OFFLINE_JWT")):
            with self.assertRaisesRegex(FeedError,"^ANGEL_PROVIDER_UNAVAILABLE$"):
                WebSocketTransport(credentials)
        with self.assertRaisesRegex(FeedError,"ANGEL_FEED_CREDENTIALS_MISSING"):
            WebSocketTransport({})

    def test_auth_rejection_is_distinguished_from_provider_failure(self):
        class Rejected(Exception):
            response=type("Response",(),dict(status_code=401))()
        credentials={k:"OFFLINE" for k in ("auth_token","api_key","client_code","feed_token")}
        with patch("websockets.sync.client.connect",side_effect=Rejected("sensitive header")):
            with self.assertRaisesRegex(FeedError,"^ANGEL_AUTHENTICATION_REJECTED$"):
                WebSocketTransport(credentials)

    def test_unsafe_production_flags_fail_before_socket(self):
        config=copy.deepcopy(self.config)
        config.telegram_dry_run=False
        feed=AngelLiveFeed(config,self.store,self.meta)
        self.addCleanup(feed.stop)
        with patch("angel_feed.WebSocketTransport",side_effect=AssertionError("No socket")) as connect:
            with self.assertRaisesRegex(FeedError,"PAPER_ONLY_READ_ONLY_FEED_SAFETY_REQUIRED"):
                feed.connect()
            connect.assert_not_called()

    def test_thread_stop_clean_shutdown_and_idempotence(self):
        entered=threading.Event()
        def receive(timeout=1):
            entered.set()
            self.feed._stop.wait(.01)
            raise TimeoutError()
        with patch.object(self.peers[0],"recv",side_effect=receive):
            thread=self.feed.start()
            self.assertTrue(entered.wait(2))
            self.feed.stop()
            self.assertFalse(thread.is_alive())
        self.feed.stop()
        self.assertTrue(self.peers[0].closed)
        self.assertEqual(self.feed.status()["state"],"STOPPED")
        self.assertTrue(self.feed.status()["closed_cleanly"])

    def test_rejected_stale_packet_retains_raw_lineage_and_no_live_counts(self):
        self.now=self.ts+timedelta(seconds=40)
        raw=packet(self.ts)
        self.peers[0].messages.append(raw)
        with self.assertRaisesRegex(FeedError,"STALE_EXCHANGE_TIMESTAMP"):
            self.feed.poll_once()
        status=self.feed.status()
        self.assertEqual(status["received_events"],0)
        self.assertEqual(status["rejected_packets"],1)
        self.assertFalse(status["last_rejected_event"]["accepted"])
        self.assertEqual(status["last_rejected_event"]["exchange_timestamp"],self.ts.isoformat())
        self.assertEqual(status["last_rejected_event"]["packet_sha256"],hashlib.sha256(raw).hexdigest())
        self.assertFalse(status["live_signal_allowed"])
        with self.store.paper_transaction(write=False) as conn:
            retained=conn.execute("SELECT raw_packet,payload_json FROM angel_feed_rejections").fetchone()
            self.assertEqual(retained[0],raw)
            self.assertFalse(json.loads(retained[1])["accepted"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM angel_feed_events").fetchone()[0],0)

    def test_unknown_schema_retains_bounded_raw_without_invented_metadata(self):
        raw=b"\x04"*30
        self.peers[0].messages.append(raw)
        with self.assertRaisesRegex(FeedError,"ANGEL_PACKET_SCHEMA_UNKNOWN"):
            self.feed.poll_once()
        rejected=self.feed.status()["last_rejected_event"]
        self.assertIsNone(rejected["packet_type"])
        self.assertIsNone(rejected["exchange_timestamp"])
        self.assertEqual(rejected["reason_code"],"ANGEL_PACKET_SCHEMA_UNKNOWN")
        self.assertFalse(rejected["accepted"])

    def test_angel_data_selection_remains_read_only_and_other_brokers_reject(self):
        cfg=copy.deepcopy(self.config)
        cfg.active_broker="angelone"
        feed=AngelLiveFeed(cfg,self.store,self.meta,transport_factory=FakePeer,clock=lambda:self.now,monotonic=lambda:0)
        self.addCleanup(feed.stop)
        with patch("urllib.request.urlopen",side_effect=AssertionError("No REST or orders")):
            feed.connect()
            feed.stop()
        self.assertEqual(cfg.active_broker,"angelone")
        self.assertTrue(cfg.telegram_dry_run)
        self.assertFalse(cfg.enable_background_scheduler)
        for broker in ("dhan","upstox"):
            cfg=copy.deepcopy(self.config)
            cfg.active_broker=broker
            feed=AngelLiveFeed(cfg,self.store,self.meta,transport_factory=FakePeer)
            with self.assertRaisesRegex(FeedError,"PAPER_ONLY_READ_ONLY_FEED_SAFETY_REQUIRED"):
                feed.connect()
            feed.stop()

    def test_unsafe_thread_activation_terminates_without_unbounded_retry(self):
        cfg=copy.deepcopy(self.config)
        cfg.enable_background_scheduler=True
        feed=AngelLiveFeed(cfg,self.store,self.meta,transport_factory=FakePeer)
        self.addCleanup(feed.stop)
        thread=feed.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(feed.reason,"PAPER_ONLY_READ_ONLY_FEED_SAFETY_REQUIRED")

    def test_new_quality_gap_blocks_old_complete_window_until_clean_recovery(self):
        self.series()
        self.assertTrue(self.feed.bars[5][-1]["is_complete"])
        self.assertFalse(self.feed.quality_degraded)
        at=self.ts+timedelta(seconds=560)
        self.push(at,volume=2000)
        self.assertTrue(self.feed.quality_degraded)
        self.assertFalse(self.feed.status()["live_signal_allowed"])
        # Genuine new contiguous observations recover only after a clean 5m window.
        for i in range(1,61):
            self.push(at+timedelta(seconds=i*10),volume=2000+i*5)
        self.assertTrue(self.feed.bars[5][-1]["is_complete"])
        self.assertFalse(self.feed.quality_degraded)

    def test_unresolved_trade_clock_degrades_old_completed_window(self):
        self.series()
        self.assertTrue(self.feed.bars[5][-1]["is_complete"])
        self.push(self.ts+timedelta(seconds=560),volume=1300,trade_ts=0)
        self.assertTrue(self.feed.quality_degraded)
        self.assertFalse(self.feed.current["_valid"])
        self.assertIn("UNRESOLVED_TRADE_CLOCK",self.feed.current["quality_reasons"])
        self.assertFalse(self.feed.status()["live_signal_allowed"])

    def test_production_requires_current_master_binding_before_any_socket(self):
        meta=copy.deepcopy(self.meta)
        meta["master_record"]=dict(symbol="RELIANCE",trading_symbol="RELIANCE-EQ",
            angel_token="2885",exchange="NSE",is_index=False,lot_size=1)
        variants=[]
        for field,value in (("current_master_sha256",None),("current_master_sha256","A"*64),
                            ("current_master_sha256","abc"),("master_record",None)):
            wrong=copy.deepcopy(meta)
            wrong[field]=value
            variants.append(wrong)
        for field,value in (("trading_symbol","RELIANCE"),("lot_size",True),
                            ("exchange","BSE"),("data_mode","SIMULATED")):
            wrong=copy.deepcopy(meta)
            wrong["master_record"][field]=value
            variants.append(wrong)
        for wrong in variants:
            with self.subTest(meta=wrong):
                try:
                    feed=AngelLiveFeed(self.config,self.store,wrong,clock=lambda:self.now)
                except ValueError:
                    continue  # Canonical identity validation may reject conflicts earlier.
                self.addCleanup(feed.stop)
                with patch("angel_feed.WebSocketTransport",side_effect=AssertionError("No socket")) as connect:
                    with self.assertRaisesRegex(FeedError,"ANGEL_CURRENT_MASTER_BINDING_REQUIRED"):
                        feed.connect()
                    connect.assert_not_called()
        feed=AngelLiveFeed(self.config,self.store,meta,clock=lambda:self.now,monotonic=lambda:0)
        self.addCleanup(feed.stop)
        with patch("angel_feed.WebSocketTransport",return_value=FakePeer()) as connect:
            feed.connect()
            connect.assert_called_once()
            self.assertEqual(feed.status()["state"],"CONNECTED_AWAITING_DATA")
            self.assertFalse(feed.status()["live_signal_allowed"])

