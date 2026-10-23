"""Explicit, read-only SmartAPI WebSocket 2.0 market feed.

Protocol: official documentation and angel-one/smartapi-python, checked 2026-10-23.
The SDK is a schema reference only: TLS verification remains enabled, text
heartbeat is explicit, retry is bounded, and no SDK logging/auth/order code runs.
"""
import copy
import hashlib
import json
import logging
import math
import re
import struct
import threading
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone

from candle_lineage import digest, encoded
from instrument_identity import bind_candles, spot_identity
from strategies import IST, parse_ist_timestamp

PROTOCOL = "angel-smartapi-websocket-v2-20261023"
PROTOCOL_SOURCES = ("https://smartapi.angelone.in/docs",
    "https://smartapi.angelbroking.com/docs",
    "https://raw.githubusercontent.com/angel-one/smartapi-python/main/SmartApi/smartWebSocketV2.py")
PACKET_SIZES = {1: 51, 2: 123, 3: 379}
ENDPOINT = "wss://smartapisocket.angelone.in/smart-stream"
MAX_MESSAGE_BYTES = 65536
ONE_MINUTE_CAPACITY = 750
FIVE_MINUTE_CAPACITY = 300  # Bounded lookback exceeds the existing 200-bar strategy minimum.


class FeedError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FeedError("EXPLICIT_CLOCK_REQUIRED")
    return value.astimezone(IST)


def _epoch(value, divisor):
    try:
        if value <= 0:
            raise ValueError()
        return datetime.fromtimestamp(value/divisor, timezone.utc).astimezone(IST)
    except (ValueError, OverflowError, OSError):
        raise FeedError("INVALID_EXCHANGE_TIMESTAMP") from None


class PacketParser:
    """WebSocket library reassembles frames; each complete message is strict.

    Paise prices apply only to the admitted NSE cash segment. Mode4/20-depth is
    deliberately unsupported. Dummy OI change and packet-received fields confer
    no authority. Buy flag1 / sell flag0 follow official documentation; the SDK
    internally reverses names and then swaps them again at the public boundary.
    """
    def parse(self, raw):
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_MESSAGE_BYTES:
            raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN")
        mode = raw[0]
        if mode not in PACKET_SIZES or len(raw) != PACKET_SIZES[mode]:
            raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN")
        if raw[1] != 1:
            raise FeedError("UNSUPPORTED_EXCHANGE_SEGMENT")
        token_bytes, null, padding = raw[2:27].partition(b"\x00")
        if not null or any(padding):
            raise FeedError("INVALID_INSTRUMENT_TOKEN")
        try:
            token = token_bytes.decode("ascii")
        except UnicodeError:
            raise FeedError("INVALID_INSTRUMENT_TOKEN") from None
        if not token or not token.isdigit() or str(int(token)) != token:
            raise FeedError("INVALID_INSTRUMENT_TOKEN")
        sequence, epoch_ms, price = struct.unpack_from("<qqq", raw, 27)
        if sequence < 0 or price <= 0:
            raise FeedError("INVALID_SEQUENCE_OR_PRICE")
        event = dict(provider="angelone", packet_type=mode, subscription_mode=mode,
            exchange="NSE", exchange_type=1, security_id=token, sequence_number=sequence,
            exchange_timestamp=_epoch(epoch_ms, 1000).isoformat(),
            exchange_timestamp_semantics="EXCHANGE_FEED_EPOCH_MILLISECONDS",
            ltp=price/100, cumulative_volume=None, last_trade_quantity=None,
            average_trade_price=None, total_pending_buy=None, total_pending_sell=None,
            day_ohlc=None, depth=None, depth_exchange_timestamp=None,
            last_trade_timestamp=None, last_trade_timestamp_raw=None,
            last_trade_timestamp_unit=None, open_interest=None,
            oi_change_percent=None, packet_hash=hashlib.sha256(raw).hexdigest())
        if mode >= 2:
            quantity, average, volume = struct.unpack_from("<qqq", raw, 51)
            pending_buy, pending_sell = struct.unpack_from("<dd", raw, 75)
            if min(quantity, average, volume) < 0 or any(not math.isfinite(n) or n < 0 for n in (pending_buy,pending_sell)):
                raise FeedError("INVALID_QUOTE_QUANTITY")
            prices = struct.unpack_from("<qqqq", raw, 91)
            if min(prices) < 0:
                raise FeedError("INVALID_DAY_PRICE")
            event.update(last_trade_quantity=quantity, average_trade_price=average/100 if average else None,
                cumulative_volume=volume, total_pending_buy=pending_buy, total_pending_sell=pending_sell,
                day_ohlc={k: p/100 if p else None for k,p in zip(("open","high","low","previous_close"), prices)})
            if all(prices[:3]) and not prices[2] <= prices[0] <= prices[1]:
                raise FeedError("INVALID_DAY_OHLC")
        if mode == 3:
            raw_trade_time, oi = struct.unpack_from("<qq", raw, 123)
            if raw_trade_time < 0 or oi < 0:
                raise FeedError("INVALID_TRADE_TIMESTAMP_OR_OI")
            event.update(last_trade_timestamp_raw=raw_trade_time, open_interest=oi)
            # The table specifies epoch-ms for feed time but leaves LTT units
            # unspecified. Resolve a unit only when exactly one interpretation
            # agrees with the explicit provider clock. Never guess from magnitude.
            feed_at = datetime.fromisoformat(event["exchange_timestamp"])
            candidates = []
            for divisor, unit in ((1,"EPOCH_SECONDS"),(1000,"EPOCH_MILLISECONDS")):
                try:
                    trade_at = _epoch(raw_trade_time, divisor)
                    if 0 <= (feed_at-trade_at).total_seconds() <= 30:
                        candidates.append((trade_at,unit))
                except FeedError:
                    pass
            if len(candidates) == 1:
                event.update(last_trade_timestamp=candidates[0][0].isoformat(),
                    last_trade_timestamp_unit=candidates[0][1],
                    trade_clock_resolution="UNIQUE_PROVIDER_CLOCK_CONSISTENCY")
            else:
                event["trade_clock_resolution"] = "UNRESOLVED_OR_STALE_NO_CANDLES"
            depth = dict(buy=[],sell=[])
            for offset in range(147,347,20):
                flag, quantity, price, orders = struct.unpack_from("<HqqH", raw, offset)
                if flag not in (0,1) or min(quantity,price) < 0 or (quantity and not price):
                    raise FeedError("INVALID_DEPTH")
                depth["buy" if flag == 1 else "sell"].append(dict(quantity=quantity,
                    price=price/100 if price else None, orders=orders))
            if any(len(levels)!=5 for levels in depth.values()):
                raise FeedError("INVALID_DEPTH_SIDE_COUNT")
            bids=[p["price"] for p in depth["buy"] if p["quantity"]]
            asks=[p["price"] for p in depth["sell"] if p["quantity"]]
            if (any(a<b for a,b in zip(bids,bids[1:])) or any(a>b for a,b in zip(asks,asks[1:]))
                    or (bids and asks and bids[0]>asks[0])):
                raise FeedError("CROSSED_OR_UNORDERED_DEPTH")
            event["depth"]=depth
            limits=struct.unpack_from("<qqqq",raw,347)
            if min(limits)<0:
                raise FeedError("INVALID_CIRCUIT_PRICE")
            event["price_limits"]={k:p/100 if p else None for k,p in zip(
                ("upper_circuit","lower_circuit","year_high","year_low"),limits)}
        return event

    def feed(self, raw):
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_MESSAGE_BYTES:
            raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN")
        events=[]
        pos=0
        while pos<len(raw):
            size=PACKET_SIZES.get(raw[pos])
            if size is None or pos+size>len(raw):
                raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN")
            events.append((raw[pos:pos+size],self.parse(raw[pos:pos+size])))
            pos+=size
        return events


class WebSocketTransport:
    def __init__(self, credentials):
        from config import _is_placeholder_value
        keys=("auth_token","api_key","client_code","feed_token")
        if not isinstance(credentials,dict) or any(_is_placeholder_value(credentials.get(k)) for k in keys):
            raise FeedError("ANGEL_FEED_CREDENTIALS_MISSING")
        try:
            from websockets.sync.client import connect
        except ImportError:
            raise FeedError("PINNED_WEBSOCKET_RUNTIME_REQUIRED") from None
        logger=logging.getLogger("tradepulse.angel.private_transport")
        logger.addHandler(logging.NullHandler())
        logger.propagate=False
        logger.setLevel(logging.CRITICAL+1)
        headers={"Authorization":credentials["auth_token"],"x-api-key":credentials["api_key"],
            "x-client-code":credentials["client_code"],"x-feed-token":credentials["feed_token"]}
        try:
            self.socket=connect(ENDPOINT,additional_headers=headers,open_timeout=10,close_timeout=2,
                max_size=MAX_MESSAGE_BYTES,max_queue=16,compression=None,proxy=None,
                ping_interval=None,logger=logger)
        except Exception as exc:
            status=getattr(getattr(exc,"response",None),"status_code",None)
            raise FeedError("ANGEL_AUTHENTICATION_REJECTED" if status in (401,403)
                else "ANGEL_PROVIDER_UNAVAILABLE") from None

    def send(self,value):
        self.socket.send(value)

    def recv(self,timeout=1):
        return self.socket.recv(timeout=timeout)

    def close(self):
        self.socket.close()


class AngelLiveFeed:
    provider="angelone"

    def __init__(self,config,store,instrument,credentials=None,transport_factory=None,clock=None,
                 monotonic=None,max_reconnects=2):
        if not isinstance(instrument,dict) or not isinstance(instrument.get("instrument_identity"),dict):
            raise FeedError("ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED")
        self.config,self.store=config,store
        self.instrument=copy.deepcopy(instrument)
        supplied=instrument["instrument_identity"]
        master_record=instrument.get("master_record") or supplied.get("master_record")
        master={instrument["symbol"]:master_record} if master_record else None
        self.identity=spot_identity(instrument,"angelone",master)
        if (self.identity["is_index"] or self.identity["instrument_type"]!="EQ" or
                any(supplied.get(k)!=self.identity[k] for k in self.identity)):
            raise FeedError("ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED")
        if not self.identity["identifier"].isdigit():
            raise FeedError("INVALID_INSTRUMENT_TOKEN")
        self.current_master_sha256=instrument.get("current_master_sha256")
        self.credentials=dict(credentials or {})
        self.factory=transport_factory
        self.fixture=transport_factory is not None
        self.data_mode="FIXTURE" if self.fixture else "LIVE"
        self.clock=clock or (lambda:datetime.now(IST))
        self.monotonic=monotonic or time.monotonic
        if type(max_reconnects) is not int or not 0<=max_reconnects<=3:
            raise FeedError("INVALID_RECONNECT_BUDGET")
        self.max_reconnects=max_reconnects
        self.reconnects=0
        self.connection_id=None
        self.transport=None
        self._thread=None
        self._stop=threading.Event()
        self._lock=threading.RLock()
        self.state,self.reason="STOPPED","NOT_STARTED"
        self.closed_cleanly=True
        self.parser=PacketParser()
        self._reset()
        with store.paper_transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS angel_feed_events (
                event_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, raw_packet BLOB NOT NULL,
                raw_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS angel_feed_candles (
                candle_key TEXT PRIMARY KEY, connection_id TEXT NOT NULL, provider TEXT NOT NULL,
                identifier TEXT NOT NULL, interval_min INTEGER NOT NULL, timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS angel_feed_forming (
                connection_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS angel_feed_rejections (
                rejection_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, raw_packet BLOB NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""")

    def _reset(self):
        self.subscribed=False
        self.observed=False
        self.seen=OrderedDict()
        self.last_sequence=None
        self.last_feed_at=None
        self.last_received=None
        self.latest=None
        self.previous=None
        self.current=None
        self.bars={1:deque(maxlen=ONE_MINUTE_CAPACITY),5:deque(maxlen=FIVE_MINUTE_CAPACITY)}
        self.events=0
        self.duplicates=0
        self.packet_types=set()
        self.connected_clock=None
        self.last_ping=None
        self.last_pong=None
        self.pending_pong=None
        self.last_rejected_event=None
        self.rejected_packets=0
        self.quality_degraded=False

    def _request(self,action):
        return encoded(dict(correlationID="tpangel001",action=action,
            params=dict(mode=3,tokenList=[dict(exchangeType=1,tokens=[self.identity["identifier"]])])))

    def _validate_current_master(self):
        """Require the control's byte-bound current mapping, not just a pinned token.

        The digest identifies the retained original master; it is not a publisher
        signature, an independently authenticated source or research approval.
        """
        record=self.instrument.get("master_record")
        sha=self.current_master_sha256
        if (not isinstance(sha,str) or re.fullmatch(r"[0-9a-f]{64}",sha) is None
                or not isinstance(record,dict)
                or record.get("symbol")!=self.identity["symbol"]
                or record.get("trading_symbol")!=self.identity["symbol"]+"-EQ"
                or str(record.get("angel_token"))!=self.identity["identifier"]
                or record.get("exchange")!="NSE" or record.get("is_index") is not False
                or type(record.get("lot_size")) is not int or record["lot_size"]!=1
                or record.get("expiry") not in (None,"")
                or record.get("is_simulated") is True or record.get("data_mode","LIVE")!="LIVE"):
            raise FeedError("ANGEL_CURRENT_MASTER_BINDING_REQUIRED")
        try:
            checked=spot_identity(record,"angelone",{self.identity["symbol"]:record})
            if any(checked.get(k)!=self.identity.get(k) for k in self.identity):
                raise ValueError()
        except (ValueError,TypeError):
            raise FeedError("ANGEL_CURRENT_MASTER_BINDING_REQUIRED") from None

    def connect(self):
        with self._lock:
            if self.transport is not None:
                raise FeedError("ALREADY_CONNECTED")
            if self.connection_id is not None:
                if self.reconnects>=self.max_reconnects:
                    raise FeedError("RECONNECT_BUDGET_EXHAUSTED")
                self.reconnects+=1
            try:
                self.config.validate(require_live_credentials=False)
            except Exception:
                self._fault("ANGEL_CONFIGURATION_MISSING_OR_INVALID")
                raise FeedError(self.reason) from None
            if (self.config.active_broker not in ("angelone","paper_sim","simulated","sim") or
                self.config.telegram_dry_run is not True or self.config.enable_background_scheduler is not False):
                self._fault("PAPER_ONLY_READ_ONLY_FEED_SAFETY_REQUIRED")
                raise FeedError(self.reason)
            if not self.fixture:
                try:
                    self._validate_current_master()
                except FeedError as exc:
                    self._fault(exc.code)
                    raise
            self._reset()
            self.connection_id=uuid.uuid4().hex
            try:
                self.transport=self.factory() if self.factory else WebSocketTransport(self.credentials)
                self.transport.send(self._request(1))
                self.subscribed=True
                self.closed_cleanly=False
                self.connected_clock=self.monotonic()
                self.state,self.reason="CONNECTED_AWAITING_DATA","SUBSCRIPTION_UNCONFIRMED"
            except FeedError as exc:
                self._fault(exc.code)
                raise
            except Exception:
                self._fault("ANGEL_PROVIDER_UNAVAILABLE")
                raise FeedError(self.reason) from None
            return self.status()

    def unsubscribe(self):
        with self._lock:
            if not self.transport or not self.subscribed:
                raise FeedError("NOT_SUBSCRIBED")
            self.transport.send(self._request(0))
            self.subscribed=False
            self.observed=False
            self.current=None
            self.previous=None

    def subscribe(self):
        with self._lock:
            if not self.transport or self.subscribed:
                raise FeedError("ALREADY_SUBSCRIBED_OR_DISCONNECTED")
            self.transport.send(self._request(1))
            self.subscribed=True
            self.bars={1:deque(maxlen=ONE_MINUTE_CAPACITY),5:deque(maxlen=FIVE_MINUTE_CAPACITY)}
            self.last_sequence=None

    def poll_once(self):
        if self.transport is None:
            raise FeedError("FEED_NOT_CONNECTED")
        try:
            self._heartbeat()
            message=self.transport.recv(timeout=1)
            with self._lock:
                if message in ("pong",b"pong"):
                    self.last_pong=self.monotonic()
                    self.pending_pong=None
                    return []
                if isinstance(message,str):
                    if len(message)>4096:
                        raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN")
                    try:
                        error=json.loads(message)
                    except (ValueError,TypeError):
                        raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN") from None
                    if isinstance(error,dict) and error.get("errorCode") in ("E1001","E1002"):
                        raise FeedError("ANGEL_SUBSCRIPTION_REJECTED_"+error["errorCode"])
                    raise FeedError("ANGEL_PACKET_SCHEMA_UNKNOWN")
                output=[]
                try:
                    packets=self.parser.feed(message)
                except FeedError as exc:
                    self._retain_rejection(message,None,exc.code)
                    raise
                for raw,event in packets:
                    try:
                        if self._consume(raw,event):
                            output.append(copy.deepcopy(event))
                    except FeedError as exc:
                        self._retain_rejection(raw,event,exc.code)
                        raise
                return output
        except TimeoutError:
            self.check_health()
            return []
        except FeedError as exc:
            with self._lock:
                self._fault(exc.code)
            raise
        except Exception:
            with self._lock:
                self._fault("ANGEL_STREAM_OR_PERSISTENCE_FAILURE")
            raise FeedError(self.reason) from None

    def _retain_rejection(self,raw,event,reason):
        if not isinstance(raw,bytes) or len(raw)>MAX_MESSAGE_BYTES or self.rejected_packets>=100:
            return
        rejection=dict(accepted=False,provider="angelone",connection_id=self.connection_id,
            packet_sha256=hashlib.sha256(raw).hexdigest(),reason_code=reason,
            receive_timestamp=_aware(self.clock()).isoformat(),data_mode=self.data_mode,
            is_simulated=self.fixture,packet_type=event.get("packet_type") if event else None,
            security_id=event.get("security_id") if event else None,
            exchange_timestamp=event.get("exchange_timestamp") if event else None,
            instrument_identity=copy.deepcopy(self.identity))
        rejection_id=digest(rejection)
        with self.store.paper_transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO angel_feed_rejections VALUES (?,?,?,?,?)",(
                rejection_id,self.connection_id,raw,encoded(rejection),digest(rejection)))
        self.last_rejected_event=rejection
        self.rejected_packets+=1

    def _heartbeat(self):
        current=self.monotonic()
        if self.pending_pong is not None and current-self.pending_pong>=30:
            raise FeedError("ANGEL_HEARTBEAT_TIMEOUT")
        if self.last_ping is None or current-self.last_ping>=10:
            self.transport.send("ping")
            self.last_ping=current
            if self.pending_pong is None:
                self.pending_pong=current

    def _consume(self,raw,event):
        if not self.subscribed or event["security_id"]!=self.identity["identifier"]:
            raise FeedError("ANGEL_INSTRUMENT_IDENTITY_MISMATCH")
        if event["packet_hash"] in self.seen:
            self.duplicates+=1
            return False
        now=_aware(self.clock())
        feed_at=datetime.fromisoformat(event["exchange_timestamp"])
        if feed_at>now+timedelta(seconds=self.config.live_candle_future_skew_seconds):
            raise FeedError("FUTURE_EXCHANGE_TIMESTAMP")
        if (now-feed_at).total_seconds()>30:
            raise FeedError("STALE_EXCHANGE_TIMESTAMP")
        if self.last_feed_at and feed_at<self.last_feed_at:
            raise FeedError("OUT_OF_ORDER_EVENT")
        if self.last_sequence is not None and event["sequence_number"]<=self.last_sequence:
            raise FeedError("OUT_OF_ORDER_OR_CONFLICTING_SEQUENCE")
        if self.events>=250000:
            raise FeedError("CONNECTION_EVENT_BUDGET_EXHAUSTED")
        event.update(instrument_identity=copy.deepcopy(self.identity),data_mode=self.data_mode,
            is_simulated=self.fixture,connection_id=self.connection_id,receive_timestamp=now.isoformat(),
            protocol=PROTOCOL,current_master_sha256=self.current_master_sha256,
            source="angel_websocket_v2",source_authenticity="INJECTED_FIXTURE" if self.fixture else "AUTHENTICATED_TLS_FEED")
        event["event_id"]=hashlib.sha256((self.connection_id+event["packet_hash"]).encode()).hexdigest()
        with self.store.paper_transaction() as conn:
            conn.execute("INSERT INTO angel_feed_events VALUES (?,?,?,?,?,?)",(
                event["event_id"],self.connection_id,raw,event["packet_hash"],encoded(event),digest(event)))
            self._aggregate(event,conn)
        self.seen[event["packet_hash"]]=None
        if len(self.seen)>4096:
            self.seen.popitem(last=False)
        self.events+=1
        self.last_feed_at=feed_at
        self.last_sequence=event["sequence_number"]
        self.last_received=now
        self.latest=copy.deepcopy(event)
        self.packet_types.add(event["packet_type"])
        self.observed=True
        self.state,self.reason=("FIXTURE" if self.fixture else "LIVE"),"OBSERVATIONS_RECEIVED"
        return True

    def _aggregate(self,event,conn):
        # LTP/QUOTE have no usable trade clock. Pending depth quantities are not volume.
        if event["subscription_mode"]!=3:
            return
        if event["last_trade_timestamp"] is None:
            self.quality_degraded=True
            if self.current:
                self.current["_valid"]=False
                self.current["quality_reasons"].append("UNRESOLVED_TRADE_CLOCK")
            return
        ts=datetime.fromisoformat(event["last_trade_timestamp"])
        from brokers import candle_session_context,is_nse_trading_day
        _,start,end,_,_=candle_session_context(ts,self.config.configured_holidays,
            self.config.session_start_ist,self.config.session_end_ist)
        if not is_nse_trading_day(ts.date(),self.config.configured_holidays) or not start<=ts.time()<end:
            return  # Preserve genuine closed-session observations; no new completed bars.
        previous=self.previous
        if previous and ts<previous["time"]:
            raise FeedError("OUT_OF_ORDER_TRADE_TIMESTAMP")
        volume=event["cumulative_volume"]
        same_day=previous is not None and previous["time"].date()==ts.date()
        delta=volume-previous["volume"] if same_day else None
        if delta is not None and delta<0:
            raise FeedError("CUMULATIVE_VOLUME_RESET")
        if delta==0:
            if event["ltp"]!=previous["price"]:
                raise FeedError("PRICE_CHANGED_WITHOUT_TRADE_VOLUME")
            return
        session_open=datetime.combine(ts.date(),start,IST)
        minute=session_open+timedelta(minutes=int((ts-session_open).total_seconds()//60))
        gap=same_day and (ts-previous["time"]).total_seconds()>30
        sampled=delta is not None and delta!=event["last_trade_quantity"]
        if gap or sampled:
            self.quality_degraded=True
        if self.current and minute>self.current["_start"]:
            boundary=(minute==self.current["_start"]+timedelta(minutes=1) and not gap and not sampled)
            self._finish(self.current,boundary,event["receive_timestamp"],conn)
            self.current=None
        if self.current is None:
            self.current=dict(timestamp=minute.isoformat(),open=event["ltp"],high=event["ltp"],low=event["ltp"],
                close=event["ltp"],volume=delta,_start=minute,_valid=bool(same_day and not gap and not sampled),
                _event_ids=[],_last=ts,_volume_baseline_event_id=previous.get("event_id") if same_day else None,
                quality_reasons=[])
            if not same_day:
                self.current["quality_reasons"].append("UNKNOWN_INITIAL_VOLUME_BASELINE")
        else:
            self.current.update(high=max(self.current["high"],event["ltp"]),low=min(self.current["low"],event["ltp"]),
                close=event["ltp"],volume=self.current["volume"]+delta if self.current["volume"] is not None else None,
                _valid=self.current["_valid"] and not gap and not sampled)
        if gap:
            self.current["quality_reasons"].append("TRADE_TIME_GAP")
        if sampled:
            self.current["quality_reasons"].append("UNOBSERVED_TRADES_IN_VOLUME_DELTA")
        self.current["_last"]=ts
        if len(self.current["_event_ids"])>=10000:
            raise FeedError("FORMING_BAR_EVENT_BUDGET_EXHAUSTED")
        self.current["_event_ids"].append(event["event_id"])
        self.previous=dict(time=ts,volume=volume,price=event["ltp"],event_id=event["event_id"])
        provisional=self._public_bar(self.current,False,event["receive_timestamp"])
        conn.execute("INSERT OR REPLACE INTO angel_feed_forming VALUES (?,?,?)",(
            self.connection_id,encoded(provisional),digest(provisional)))

    def _public_bar(self,internal,complete,received):
        row={k:copy.deepcopy(v) for k,v in internal.items() if not k.startswith("_")}
        row.update(interval_min=1,is_complete=bool(complete),timestamp_timezone="Asia/Kolkata",provider="angelone",
            data_mode=self.data_mode,is_simulated=self.fixture,source="angel_websocket_v2",connection_id=self.connection_id,
            source_event_ids=internal["_event_ids"],source_observation_at=internal["_last"].isoformat(),
            volume_baseline_event_id=internal["_volume_baseline_event_id"],
            received_at=received,current_master_sha256=self.current_master_sha256,
            candle_semantics="OBSERVED_SNAP_TRADES_WITH_CUMULATIVE_VOLUME",
            source_authenticity="INJECTED_FIXTURE" if self.fixture else "AUTHENTICATED_TLS_FEED")
        if self.fixture:
            row["instrument_identity"]=dict(self.identity,response_binding="FIXTURE_NOT_LIVE")
        else:
            row=bind_candles([row],self.identity)[0]
        return row

    def _finish(self,internal,boundary,received,conn):
        row=self._public_bar(internal,internal["_valid"] and boundary,received)
        if not boundary:
            row["quality_reasons"].append("UNPROVEN_CLOSE_BOUNDARY")
        self.bars[1].append(row)
        self._persist_bar(row,conn)
        start=internal["_start"].replace(hour=int(self.config.session_start_ist[:2]),
            minute=int(self.config.session_start_ist[3:]),second=0,microsecond=0)
        if int((internal["_start"]-start).total_seconds()//60)%5!=4:
            return
        parts=list(self.bars[1])[-5:]
        if len(parts)!=5 or any(parse_ist_timestamp(p["timestamp"])!=internal["_start"]-timedelta(minutes=4-i) for i,p in enumerate(parts)):
            return
        five=copy.deepcopy(parts[0])
        five.update(interval_min=5,high=max(p["high"] for p in parts),low=min(p["low"] for p in parts),close=parts[-1]["close"],
            volume=sum(p["volume"] for p in parts) if all(p["volume"] is not None for p in parts) else None,
            is_complete=all(p["is_complete"] for p in parts),component_count=5,expected_components=5,
            source_event_ids=[eid for p in parts for eid in p["source_event_ids"]],
            source_observation_at=parts[-1]["source_observation_at"],received_at=received,
            quality_reasons=sorted({r for p in parts for r in p["quality_reasons"]}))
        self.bars[5].append(five)
        self._persist_bar(five,conn)
        if five["is_complete"]:
            self.quality_degraded=False

    def _persist_bar(self,row,conn):
        key=digest(["angelone",self.data_mode,self.connection_id,self.identity["identifier"],row["interval_min"],row["timestamp"]])
        previous=conn.execute("SELECT payload_sha256 FROM angel_feed_candles WHERE candle_key=?",(key,)).fetchone()
        if previous and previous[0]!=digest(row):
            raise FeedError("CANDLE_CORRECTION_CONFLICT")
        conn.execute("INSERT OR IGNORE INTO angel_feed_candles VALUES (?,?,?,?,?,?,?,?)",(
            key,self.connection_id,"angelone",self.identity["identifier"],row["interval_min"],row["timestamp"],encoded(row),digest(row)))

    def _history_rows(self, interval, now, *, copy_rows=True):
        """Latest contiguous completed run per observed session, never filled gaps.

        An invalid initial bar in a new session cannot erase separately observed
        qualified history. Conversely, today's latest invalid bar cannot expose
        an older current-session prefix as current accepted input. Closed-session
        trailing partials remain persisted but never become completed history.
        The canonical gate still validates the resulting entire batch afterward.
        """
        from brokers import candle_session_context
        ref = _aware(now)
        _, _, _, session_state, _ = candle_session_context(ref, self.config.configured_holidays,
            self.config.session_start_ist, self.config.session_end_ist)
        sessions = OrderedDict()
        for row in self.bars[interval]:
            sessions.setdefault(parse_ist_timestamp(row["timestamp"]).date(), []).append(row)
        selected = []
        for day, rows in sessions.items():
            if day == ref.date() and session_state == "within_session" and not rows[-1]["is_complete"]:
                continue
            run, latest_run = [], []
            previous = None
            for row in rows:
                timestamp = parse_ist_timestamp(row["timestamp"])
                if not row["is_complete"]:
                    run, previous = [], None
                    continue
                if previous is not None and timestamp != previous + timedelta(minutes=interval):
                    run = []
                run.append(row)
                latest_run = run
                previous = timestamp
            selected.extend(latest_run)
        return copy.deepcopy(selected) if copy_rows else selected

    def _tail(self,interval,now):
        rows=self._history_rows(interval,now)
        from brokers import assess_live_candle_batch
        return assess_live_candle_batch(rows,interval,now,self.config.configured_holidays,
            self.config.session_start_ist,self.config.session_end_ist,self.config.live_candle_max_delay_seconds,
            self.config.live_candle_future_skew_seconds,provider="angelone",symbol=self.identity["symbol"],
            context="SCANNER",normalized_ist=True)

    def get_candles(self,meta,interval_min=5,now=None):
        with self._lock:
            if type(interval_min) is not int or interval_min not in (1,5):
                raise FeedError("UNSUPPORTED_FEED_INTERVAL")
            master=self.identity.get("master_record")
            expected=spot_identity(meta,"angelone",{self.identity["symbol"]:master} if master else None)
            if any(expected.get(k)!=self.identity.get(k) for k in self.identity):
                raise FeedError("ANGEL_INSTRUMENT_IDENTITY_MISMATCH")
            self.check_health(now)
            if self.fixture:
                raise FeedError("FIXTURE_NOT_LIVE_QUALIFIED")
            if self.state!="LIVE" or not self.observed or not self.subscribed or self.transport is None:
                raise FeedError("FEED_UNAVAILABLE")
            if self.quality_degraded:
                raise FeedError("ANGEL_CANDLES_QUALITY_GAP_REQUIRES_CLEAN_WINDOW")
            rows,assessment=self._tail(interval_min,now or self.clock())
            if not assessment["live_signal_allowed"]:
                raise FeedError("ANGEL_CANDLES_"+assessment["reason_code"])
            return rows

    def check_health(self,now=None):
        with self._lock:
            ref=_aware(now or self.clock())
            if self.transport:
                if self.pending_pong is not None and self.monotonic()-self.pending_pong>=30:
                    self._fault("ANGEL_HEARTBEAT_TIMEOUT")
                elif (self.last_received and (ref-self.last_received).total_seconds()>30
                        and self._session_requires_fresh_observation(ref)):
                    self._fault("ANGEL_FEED_STALE")
                elif not self.last_received and self.connected_clock is not None and self.monotonic()-self.connected_clock>30:
                    self._fault("ANGEL_SUBSCRIPTION_UNCONFIRMED")
            return self.status()

    def _session_requires_fresh_observation(self, ref):
        """Keep healthy heartbeat history over a closure; never confer LIVE readiness.

        This concerns transport lifetime only. Canonical SCANNER session/freshness
        checks remain unchanged. A new session has at most 30 seconds to produce
        fresh observations, after which the usual fail-closed disconnect applies.
        """
        from brokers import candle_session_context
        _, start, _, state, _ = candle_session_context(ref, self.config.configured_holidays,
            self.config.session_start_ist, self.config.session_end_ist)
        if state != "within_session":
            return False
        opened = datetime.combine(ref.date(), start, IST)
        return not (self.last_received < opened and (ref-opened).total_seconds() <= 30)

    def status(self):
        with self._lock:
            ref=_aware(self.clock())
            fresh=self.last_received is not None and (ref-self.last_received).total_seconds()<=30
            state=self.state
            if self.transport and self.last_received and not fresh:
                state="STALE"
            if self.transport and ((self.pending_pong is not None and self.monotonic()-self.pending_pong>=30)
                    or (not self.last_received and self.connected_clock is not None and self.monotonic()-self.connected_clock>30)):
                state="STALE"
            eligible=bool(state=="LIVE" and self.transport and self.subscribed and self.observed and not self.fixture and fresh and not self.quality_degraded
                and self._tail(1,ref)[1]["live_signal_allowed"] and self._tail(5,ref)[1]["live_signal_allowed"])
            return dict(provider="angelone",protocol=PROTOCOL,state=state,status=state,reason_code=self.reason,
                data_mode=self.data_mode,is_simulated=self.fixture,connected=self.transport is not None,
                instrument_identity=copy.deepcopy(self.identity),current_master_sha256=self.current_master_sha256,
                subscribed_instruments=int(self.subscribed),observed_subscriptions=int(self.observed),
                received_events=self.events,duplicate_packets=self.duplicates,packet_types=sorted(self.packet_types),
                connection_id=self.connection_id,reconnects=self.reconnects,max_reconnects=self.max_reconnects,
                last_event_at=self.last_feed_at.isoformat() if self.last_feed_at else None,
                last_trade_at=self.latest.get("last_trade_timestamp") if self.latest else None,
                last_received_at=self.last_received.isoformat() if self.last_received else None,
                last_pong_observed=self.last_pong is not None,live_signal_allowed=eligible,
                rejected_packets=self.rejected_packets,last_rejected_event=copy.deepcopy(self.last_rejected_event),
                current_live_acceptance=False,closed_cleanly=self.closed_cleanly,
                quality_degraded=self.quality_degraded,
                candle_counts={str(n):len(v) for n,v in self.bars.items()},
                complete_candle_counts={str(n):sum(r["is_complete"] for r in v) for n,v in self.bars.items()},
                history=dict(capacity_5m=FIVE_MINUTE_CAPACITY,
                    selected_completed_5m=len(self._history_rows(5,ref,copy_rows=False)),
                    selection_policy="LATEST_CONTIGUOUS_COMPLETED_RUN_PER_OBSERVED_SESSION",
                    restoration_status="NOT_RESTORED_ON_RECONNECT_OR_RESTART",
                    lookback_count_is_live_acceptance=False),
                raw_lineage_persisted=self.events>0,backfill_status="NOT_AVAILABLE_NEW_CONNECTION_LINEAGE_REQUIRED")

    def _fault(self,code):
        self.state,self.reason="UNAVAILABLE",code
        old,self.transport=self.transport,None
        if old:
            try:
                old.close()
                self.closed_cleanly=True
            except Exception:
                self.closed_cleanly=False
        self.current=None
        self.previous=None

    def reconnect(self):
        with self._lock:
            self._fault("RECONNECTING")
        return self.connect()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise FeedError("ALREADY_RUNNING")
            self._stop.clear()
            self._thread=threading.Thread(target=self._run,name="angel-read-only-feed",daemon=True)
            self._thread.start()
            return self._thread

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.transport is None:
                    self.connect()
                self.poll_once()
            except FeedError:
                if self.reason.startswith("ANGEL_SUBSCRIPTION_REJECTED") or self.reason in (
                    "ANGEL_AUTHENTICATION_REJECTED","ANGEL_FEED_CREDENTIALS_MISSING",
                    "ANGEL_CONFIGURATION_MISSING_OR_INVALID","ANGEL_CURRENT_MASTER_BINDING_REQUIRED",
                    "PAPER_ONLY_READ_ONLY_FEED_SAFETY_REQUIRED"):
                    break
                if self.reconnects>=self.max_reconnects:
                    break
                self._stop.wait(min(2**self.reconnects,4))

    def stop(self):
        self._stop.set()
        with self._lock:
            if self.transport and self.subscribed:
                try:
                    self.transport.send(self._request(0))
                except Exception:
                    pass
            self._fault("STOPPED")
            self.subscribed=False
            self.state="STOPPED"
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=12)
            if self._thread.is_alive():
                raise FeedError("ANGEL_SHUTDOWN_TIMEOUT")
        if not self.closed_cleanly:
            raise FeedError("ANGEL_SHUTDOWN_FAILED")

