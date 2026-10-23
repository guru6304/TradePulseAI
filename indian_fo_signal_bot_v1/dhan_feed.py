"""Bounded DhanHQ v2 read-only stream. No connection starts on import.

Protocol checked against official live-market-feed / annexure docs, 2026-10-22.
Only the canonical application's pinned NSE spot identities are admitted. Five
level depth is a quote snapshot, never executed or aggressor-side trade volume.
Authored/injected transports are permanently FIXTURE, including after reconnect.
"""
import copy
import hashlib
import json
import logging
import math
import struct
import threading
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from instrument_identity import bind_candles, spot_identity
from strategies import IST, parse_ist_timestamp

PROTOCOL = "dhanhq-v2-2026-10-22"
PROTOCOL_SOURCES = ("https://dhanhq.co/docs/v2/live-market-feed/",
                    "https://dhanhq.co/docs/v2/annexure/",
                    "https://raw.githubusercontent.com/dhan-oss/DhanHQ-py/main/src/dhanhq/marketfeed.py",
                    "https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html")
SIZES = {2: 16, 4: 50, 5: 12, 6: 16, 8: 162, 50: 10}
SEGMENTS = {0: "IDX_I", 1: "NSE_EQ"}
MAX_FRAME_BYTES = 65536


class FeedError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Provider exceptions/URLs can contain tokens.


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FeedError("EXPLICIT_CLOCK_REQUIRED")
    return value.astimezone(IST)


class PacketParser:
    """Incremental little-endian v2 parser, bounded across fragmented payloads."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        if not isinstance(data, bytes) or not data or len(data) + len(self.buffer) > MAX_FRAME_BYTES:
            self.buffer.clear()
            raise FeedError("INVALID_OR_OVERSIZED_BINARY_FRAME")
        self.buffer.extend(data)
        output = []
        while len(self.buffer) >= 8:
            code, length, segment, security_id = struct.unpack_from("<BHB I", self.buffer)
            if code not in SIZES or length != SIZES[code]:
                self.buffer.clear()
                raise FeedError("UNKNOWN_PACKET_SCHEMA")
            if len(self.buffer) < length:
                break
            raw = bytes(self.buffer[:length])
            del self.buffer[:length]
            event = dict(packet_type=code, exchange_segment=SEGMENTS.get(segment),
                         segment_code=segment, security_id=str(security_id), packet_hash=_sha(raw),
                         ltp=None, exchange_timestamp=None, cumulative_volume=None,
                         last_trade_quantity=None, average_trade_price=None, total_pending_sell=None,
                         total_pending_buy=None, day_ohlc=None, open_interest=None,
                         depth=None, depth_exchange_timestamp=None)
            if code == 50:
                event["disconnect_code"] = struct.unpack_from("<H", raw, 8)[0]
            elif code == 2:
                event["ltp"], epoch = struct.unpack_from("<fI", raw, 8)
                event["exchange_timestamp"] = self._timestamp(epoch)
            elif code == 5:
                event["open_interest"] = struct.unpack_from("<I", raw, 8)[0]
            elif code == 6:
                event["previous_close"], event["previous_open_interest"] = struct.unpack_from("<fI", raw, 8)
            else:
                (event["ltp"], event["last_trade_quantity"], epoch, event["average_trade_price"],
                 event["cumulative_volume"], event["total_pending_sell"], event["total_pending_buy"]) = struct.unpack_from("<fHIfIII", raw, 8)
                event["exchange_timestamp"] = self._timestamp(epoch)
                offset = 34
                if code == 8:
                    (event["open_interest"], event["day_high_open_interest"],
                     event["day_low_open_interest"]) = struct.unpack_from("<III", raw, offset)
                    offset += 12
                o, c, h, l = struct.unpack_from("<ffff", raw, offset)
                # Zero day-close is documented as absent before market close.
                event["day_ohlc"] = dict(open=o or None, close=c or None, high=h or None, low=l or None)
                if code == 8:
                    event["depth"] = []
                    for pos in range(62, 162, 20):
                        bq, aq, bn, an, bp, ap = struct.unpack_from("<IIHHff", raw, pos)
                        if (not math.isfinite(bp) or not math.isfinite(ap) or bp < 0 or ap < 0
                                or (bq and bp <= 0) or (aq and ap <= 0) or (bq and aq and bp > ap)):
                            raise FeedError("INVALID_DEPTH")
                        event["depth"].append(dict(bid_quantity=bq, ask_quantity=aq,
                            bid_orders=bn, ask_orders=an, bid_price=bp if bp > 0 else None,
                            ask_price=ap if ap > 0 else None))
                    bids = [level["bid_price"] for level in event["depth"] if level["bid_quantity"]]
                    asks = [level["ask_price"] for level in event["depth"] if level["ask_quantity"]]
                    if any(a < b for a, b in zip(bids, bids[1:])) or any(a > b for a, b in zip(asks, asks[1:])):
                        raise FeedError("UNORDERED_DEPTH_LEVELS")
            for field in ("ltp", "previous_close", "average_trade_price"):
                number = event.get(field)
                if number is not None and (not math.isfinite(number) or number <= 0):
                    raise FeedError("INVALID_PACKET_PRICE")
            if event["day_ohlc"]:
                values = event["day_ohlc"]
                if any(v is not None and (not math.isfinite(v) or v <= 0) for v in values.values()):
                    raise FeedError("INVALID_DAY_OHLC")
                if all(values[k] is not None for k in ("open", "high", "low")) and not values["low"] <= values["open"] <= values["high"]:
                    raise FeedError("INVALID_DAY_OHLC")
            output.append(event)
        return output

    @staticmethod
    def _timestamp(epoch):
        if epoch <= 0:
            raise FeedError("MISSING_EXCHANGE_TIMESTAMP")
        try:
            return datetime.fromtimestamp(epoch, timezone.utc).astimezone(IST).isoformat()
        except (ValueError, OSError, OverflowError):
            raise FeedError("INVALID_EXCHANGE_TIMESTAMP") from None


class WebSocketTransport:
    """Only production transport; fixed TLS host, no URL/exception logging."""
    def __init__(self, config):
        from brokers import _is_placeholder_secret
        if any(_is_placeholder_secret(v) for v in (config.dhan_client_id, config.dhan_access_token)):
            raise FeedError("DHAN_CREDENTIALS_MISSING")
        try:
            from websockets.sync.client import connect
        except ImportError:
            raise FeedError("WEBSOCKET_DEPENDENCY_MISSING") from None
        # Suppress third-party handshake diagnostics containing the query token.
        logger = logging.getLogger("tradepulse.dhan.private_transport")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
        url = "wss://api-feed.dhan.co?" + urlencode(dict(version="2", token=config.dhan_access_token,
            clientId=config.dhan_client_id, authType="2"))
        try:
            self.socket = connect(url, open_timeout=10, close_timeout=2, ping_interval=10,
                ping_timeout=20, max_size=MAX_FRAME_BYTES, max_queue=16, compression=None,
                proxy=None, logger=logger)
        except Exception:
            raise FeedError("DHAN_CONNECTION_OR_AUTHENTICATION_FAILED") from None

    def send(self, value):
        self.socket.send(value)

    def recv(self, timeout=1):
        return self.socket.recv(timeout=timeout)

    def close(self):
        self.socket.close()


class DhanLiveFeed:
    """Bounded stream with durable canonical candles and isolated fixture lineage.

    No acknowledgement packet is documented: subscription is PENDING until a
    matching packet arrives. Quote LTT dates the last trade, not depth freshness.
    Candle completeness is conservative: cumulative-volume jumps exceeding the
    observed last-trade quantity invalidate affected bars; first partial bars,
    gaps, reconnects and missing volume never authorize scanner consumption.
    """
    def __init__(self, config, store, instruments=None, transport_factory=None, clock=None, fixture_mode=False):
        self.config, self.store = config, store
        self.clock = clock or (lambda: datetime.now(IST))
        self.factory = transport_factory
        self.fixture = bool(fixture_mode or transport_factory is not None)
        self.mode = "FIXTURE" if self.fixture else "LIVE"
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.transport = None
        self.identities = {}
        self.metas = {}
        scope = instruments if instruments is not None else getattr(config, "dhan_feed_instruments", [])
        if not isinstance(scope, list) or not 1 <= len(scope) <= 50:
            raise FeedError("EXPLICIT_BOUNDED_INSTRUMENT_SCOPE_REQUIRED")
        for meta in scope:
            identity = spot_identity(meta, "dhan")
            segment = 0 if identity["is_index"] else 1
            key = (segment, identity["identifier"])
            if key in self.identities:
                raise FeedError("DUPLICATE_INSTRUMENT_MAPPING")
            if not identity["identifier"].isdigit():
                raise FeedError("INVALID_SECURITY_ID")
            self.identities[key] = identity
            self.metas[identity["symbol"]] = copy.deepcopy(meta)
        self.active = set(self.identities)
        self.state, self.reason = "STOPPED", "NOT_STARTED"
        self.connection_id = None
        self.reconnects = 0
        self.events = 0
        self.duplicates = 0
        self.latest = {}
        self.connected_at = None
        self._reset()
        with store.paper_transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS dhan_feed_events (
                event_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL, packet_hash TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS dhan_feed_candles (
                candle_key TEXT PRIMARY KEY, connection_id TEXT NOT NULL, provider TEXT NOT NULL,
                identifier TEXT NOT NULL, interval_min INTEGER NOT NULL, timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS dhan_feed_forming (
                connection_id TEXT NOT NULL, identifier TEXT NOT NULL, payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL, PRIMARY KEY(connection_id,identifier))""")

    def _reset(self):
        self.parser = PacketParser()
        self.previous = {}
        self.current = {}
        self.bars = {key: {1: deque(maxlen=750), 5: deque(maxlen=150)} for key in self.identities}
        self.seen = OrderedDict()
        self.received = {}
        self.subscription_observed = set()
        self.latest = {}

    def _request(self, keys, subscribe=True):
        keys = list(keys)
        if not keys or len(keys) > 100 or any(key not in self.identities for key in keys):
            raise FeedError("INVALID_SUBSCRIPTION_SCOPE")
        return _json(dict(RequestCode=21 if subscribe else 22, InstrumentCount=len(keys),
            InstrumentList=[dict(ExchangeSegment=SEGMENTS[k[0]], SecurityId=k[1]) for k in sorted(keys)]))

    def connect(self):
        with self._lock:
            if self.transport is not None:
                raise FeedError("ALREADY_CONNECTED")
            if self.connection_id is not None:
                self.reconnects += 1
            self._reset()
            self.connection_id = uuid.uuid4().hex
            self.events = 0
            try:
                self.config.validate(require_live_credentials=False)
                if not self.fixture and (not self.config.telegram_dry_run or self.config.enable_background_scheduler):
                    raise FeedError("READ_ONLY_FEED_SAFETY_REQUIRED")
                self.transport = self.factory() if self.factory else WebSocketTransport(self.config)
                self.transport.send(self._request(self.active))
            except FeedError as exc:
                self._fault(exc.code)
                raise
            except Exception:
                self._fault("DHAN_CONNECTION_OR_AUTHENTICATION_FAILED")
                raise FeedError(self.reason) from None
            self.state, self.reason = "CONNECTED_AWAITING_DATA", "SUBSCRIPTION_UNCONFIRMED"
            self.connected_at = _aware(self.clock())
            return self.status()

    def unsubscribe(self, metas):
        with self._lock:
            keys = self._keys(metas)
            if not self.transport or not keys <= self.active or keys == self.active:
                raise FeedError("INVALID_UNSUBSCRIPTION")
            self.transport.send(self._request(keys, False))
            self.active -= keys
            for key in keys:
                self.current.pop(key, None)
                self.previous.pop(key, None)

    def subscribe(self, metas):
        with self._lock:
            keys = self._keys(metas)
            if not self.transport or keys & self.active:
                raise FeedError("INVALID_SUBSCRIPTION")
            self.transport.send(self._request(keys))
            self.active |= keys
            for key in keys:
                self.received.pop(key, None)
                self.subscription_observed.discard(key)
                self.bars[key] = {1: deque(maxlen=750), 5: deque(maxlen=150)}

    def _keys(self, metas):
        if not isinstance(metas, list) or not metas:
            raise FeedError("INVALID_SUBSCRIPTION_SCOPE")
        keys = set()
        for meta in metas:
            identity = spot_identity(meta, "dhan")
            key = (0 if identity["is_index"] else 1, identity["identifier"])
            if key not in self.identities or key in keys:
                raise FeedError("INVALID_SUBSCRIPTION_SCOPE")
            keys.add(key)
        return keys

    def poll_once(self):
        if self.transport is None:
            raise FeedError("FEED_NOT_CONNECTED")
        try:
            data = self.transport.recv(timeout=1)
        except TimeoutError:
            self.check_health()
            return []
        except Exception:
            with self._lock:
                self._fault("DISCONNECTED")
            raise FeedError("DISCONNECTED") from None
        with self._lock:
            try:
                events = self.parser.feed(data)
                for event in events:
                    self._consume(event, _aware(self.clock()))
                return copy.deepcopy(events)
            except FeedError as exc:
                self._fault(exc.code)
                raise
            except Exception:
                self._fault("INGESTION_OR_PERSISTENCE_FAILURE")
                raise FeedError(self.reason) from None

    def _consume(self, event, received):
        if event["packet_type"] == 50:
            code = event["disconnect_code"]
            raise FeedError("DHAN_AUTHENTICATION_FAILED" if code in (807, 808, 809, 810)
                else "DHAN_DATA_PERMISSION_MISSING" if code == 806 else "DHAN_SUBSCRIPTION_REJECTED_" + str(code))
        key = (event["segment_code"], event["security_id"])
        if key not in self.active:
            raise FeedError("UNKNOWN_OR_UNSUBSCRIBED_INSTRUMENT")
        if event["packet_hash"] in self.seen:
            self.duplicates += 1
            return
        self.seen[event["packet_hash"]] = None
        if len(self.seen) > 4096:
            self.seen.popitem(last=False)
        identity = self.identities[key]
        event.update(provider="dhan", instrument_identity=identity, exchange="NSE",
                     receive_timestamp=received.isoformat(), timestamp_semantics="LAST_TRADE_TIME",
                     data_mode=self.mode, is_simulated=self.fixture, protocol=PROTOCOL,
                     connection_id=self.connection_id)
        if event["exchange_timestamp"] is not None:
            trade_at = _aware(datetime.fromisoformat(event["exchange_timestamp"]))
            if trade_at > received + timedelta(seconds=5):
                raise FeedError("FUTURE_EXCHANGE_TIMESTAMP")
            if (received-trade_at).total_seconds() > 30:
                raise FeedError("STALE_OR_DELAYED_TRADE")
            from brokers import candle_session_context, is_nse_trading_day
            _, start, end, _, _ = candle_session_context(trade_at, self.config.configured_holidays,
                self.config.session_start_ist, self.config.session_end_ist)
            if not is_nse_trading_day(trade_at.date(), self.config.configured_holidays) or not start <= trade_at.time() < end:
                raise FeedError("OUTSIDE_TRADING_SESSION")
            prior = self.previous.get(key)
            if prior and trade_at < prior["time"]:
                raise FeedError("OUT_OF_ORDER_EVENT")
            self._aggregate(key, event, trade_at, received)
            self.received[key] = received
            self.subscription_observed.add(key)
            self.latest[key] = copy.deepcopy(event)
            self.state, self.reason = ("FIXTURE" if self.fixture else "LIVE"), "OBSERVATIONS_RECEIVED"
        self.events += 1
        if self.events > 250000:
            raise FeedError("CONNECTION_EVENT_BUDGET_EXCEEDED")
        body = _json(event)
        with self.store.paper_transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO dhan_feed_events VALUES (?,?,?,?,?)", (
                _sha((self.connection_id + event["packet_hash"]).encode()), self.connection_id,
                body, _sha(body.encode()), event["packet_hash"]))

    def _aggregate(self, key, event, ts, received):
        volume = event["cumulative_volume"]
        if volume is None:
            # Ticker/indices do not have volume. Never fill a required field with zero.
            return
        prior = self.previous.get(key)
        same_day = prior is not None and prior["time"].date() == ts.date()
        delta = volume - prior["volume"] if same_day else None
        if delta is not None and delta < 0:
            raise FeedError("CUMULATIVE_VOLUME_RESET")
        if delta == 0:
            if event["ltp"] != prior["price"]:
                raise FeedError("PRICE_CHANGED_WITHOUT_TRADE_VOLUME")
            return  # Depth-only update: LTQ is NOT summed again.
        gap = same_day and (ts-prior["time"]).total_seconds() > 30
        sampled_gap = delta is not None and delta != event["last_trade_quantity"]
        start = datetime.combine(ts.date(), datetime.strptime(self.config.session_start_ist, "%H:%M").time(), IST)
        minute = start + timedelta(minutes=int((ts-start).total_seconds() // 60))
        previous_bar = self.current.get(key)
        if previous_bar and minute > previous_bar["_start"]:
            contiguous = minute == previous_bar["_start"] + timedelta(minutes=1)
            self._finish_minute(key, previous_bar, received, contiguous and not gap and not sampled_gap)
            previous_bar = None
        if previous_bar is None:
            previous_bar = dict(timestamp=minute.isoformat(), open=event["ltp"], high=event["ltp"],
                low=event["ltp"], close=event["ltp"], volume=delta,
                _start=minute, _valid=bool(same_day and not gap and not sampled_gap),
                _events=[event["packet_hash"]], _last=ts, quality_reasons=[])
            if not same_day:
                previous_bar["quality_reasons"].append("UNKNOWN_INITIAL_VOLUME_BASELINE")
            self.current[key] = previous_bar
        else:
            previous_bar.update(high=max(previous_bar["high"], event["ltp"]),
                low=min(previous_bar["low"], event["ltp"]), close=event["ltp"],
                volume=previous_bar["volume"] + delta if previous_bar["volume"] is not None else None, _last=ts)
            previous_bar["_events"].append(event["packet_hash"])
            previous_bar["_valid"] &= not gap and not sampled_gap
        if gap:
            previous_bar["quality_reasons"].append("EVENT_TIME_GAP")
        if sampled_gap:
            previous_bar["quality_reasons"].append("UNOBSERVED_TRADES_IN_VOLUME_DELTA")
        self.previous[key] = dict(time=ts, volume=volume, price=event["ltp"])
        provisional = {k: copy.deepcopy(v) for k, v in previous_bar.items() if not k.startswith("_")}
        provisional.update(interval_min=1, is_complete=False, provider="dhan", data_mode=self.mode,
            is_simulated=self.fixture, timestamp_timezone="Asia/Kolkata", source="dhan_websocket_v2",
            connection_id=self.connection_id, source_event_hashes=previous_bar["_events"],
            instrument_identity=self.identities[key])
        payload = _json(provisional)
        with self.store.paper_transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO dhan_feed_forming VALUES (?,?,?,?)", (
                self.connection_id, key[1], payload, _sha(payload.encode())))

    def _finish_minute(self, key, internal, received, boundary_valid):
        bar = {k: copy.deepcopy(v) for k, v in internal.items() if not k.startswith("_")}
        valid = internal["_valid"] and boundary_valid
        if not boundary_valid:
            bar["quality_reasons"].append("UNPROVEN_CLOSE_BOUNDARY")
        bar.update(interval_min=1, is_complete=bool(valid), timestamp_timezone="Asia/Kolkata",
            is_simulated=self.fixture, data_mode=self.mode, provider="dhan",
            source="dhan_websocket_v2", connection_id=self.connection_id,
            source_event_hashes=internal["_events"], source_observation_at=internal["_last"].isoformat(),
            received_at=received.isoformat(), candle_semantics="OBSERVED_TRADES_WITH_CUMULATIVE_VOLUME",
            source_authenticity="INJECTED_FIXTURE" if self.fixture else "AUTHENTICATED_TLS_FEED")
        if self.fixture:
            # Production bind_candles deliberately rejects synthetic provenance;
            # retain the canonical identity as an explicitly unaccepted fixture.
            bar["instrument_identity"] = dict(self.identities[key], response_binding="FIXTURE_NOT_LIVE")
        else:
            bar = bind_candles([bar], self.identities[key])[0]
        self.bars[key][1].append(bar)
        self._persist_bar(key, bar)
        timestamp = internal["_start"]
        start = timestamp.replace(hour=int(self.config.session_start_ist[:2]), minute=int(self.config.session_start_ist[3:]), second=0, microsecond=0)
        if int((timestamp-start).total_seconds() // 60) % 5 != 4:
            return
        components = list(self.bars[key][1])[-5:]
        if len(components) != 5 or any(parse_ist_timestamp(c["timestamp"]) != timestamp - timedelta(minutes=4-i) for i, c in enumerate(components)):
            return
        five = copy.deepcopy(components[0])
        five.update(interval_min=5, high=max(c["high"] for c in components),
            low=min(c["low"] for c in components), close=components[-1]["close"],
            volume=sum(c["volume"] for c in components) if all(c["volume"] is not None for c in components) else None,
            is_complete=all(c["is_complete"] for c in components),
            component_count=5, expected_components=5,
            source_event_hashes=[h for c in components for h in c["source_event_hashes"]],
            source_observation_at=components[-1]["source_observation_at"],
            received_at=components[-1]["received_at"],
            quality_reasons=sorted({r for c in components for r in c["quality_reasons"]}))
        self.bars[key][5].append(five)
        self._persist_bar(key, five)

    def _persist_bar(self, key, bar):
        body = _json(bar)
        candle_key = _sha(_json(["dhan", self.mode, key, bar["interval_min"], bar["timestamp"], self.connection_id]).encode())
        with self.store.paper_transaction() as conn:
            old = conn.execute("SELECT payload_hash FROM dhan_feed_candles WHERE candle_key=?", (candle_key,)).fetchone()
            if old is not None and old[0] != _sha(body.encode()):
                raise FeedError("CANDLE_CORRECTION_CONFLICT")
            conn.execute("INSERT OR IGNORE INTO dhan_feed_candles VALUES (?,?,?,?,?,?,?,?)", (
                candle_key, self.connection_id, "dhan", key[1], bar["interval_min"],
                bar["timestamp"], body, _sha(body.encode())))

    def check_health(self, now=None):
        with self._lock:
            ref = _aware(now or self.clock())
            if self.transport and self.connected_at and (ref-self.connected_at).total_seconds() > 30 and any(k not in self.received for k in self.active):
                self._fault("SUBSCRIPTION_UNCONFIRMED_OR_STALE")
            if self.transport and self.received and any((ref-self.received[k]).total_seconds() > 30 for k in self.active if k in self.received):
                self._fault("STALE_FEED")
            return self.status()

    def get_candles(self, meta, interval_min=5, now=None):
        with self._lock:
            if type(interval_min) is not int or interval_min not in (1, 5):
                raise FeedError("UNSUPPORTED_FEED_INTERVAL")
            key = next(iter(self._keys([meta])))
            if key not in self.active:
                raise FeedError("INSTRUMENT_UNSUBSCRIBED")
            self.check_health(now)
            if self.fixture:
                raise FeedError("FIXTURE_NOT_LIVE_QUALIFIED")
            if self.state != "LIVE" or key not in self.subscription_observed or key not in self.received:
                raise FeedError("FEED_NOT_LIVE_OR_SUBSCRIPTION_UNCONFIRMED")
            rows, assessment = self._tail_assessment(key, interval_min, now or self.clock())
            if not assessment["live_signal_allowed"]:
                raise FeedError("FEED_CANDLES_" + assessment["reason_code"])
            return rows

    def _tail_assessment(self, key, interval_min, now):
        rows = copy.deepcopy(list(self.bars[key][interval_min]))
        # Keep only a contiguous completed tail: no bridging rejected bars.
        last_bad = max((i for i, row in enumerate(rows) if not row["is_complete"]), default=-1)
        rows = rows[last_bad+1:]
        from brokers import assess_live_candle_batch
        return assess_live_candle_batch(rows, interval_min, now,
            self.config.configured_holidays, self.config.session_start_ist, self.config.session_end_ist,
            self.config.live_candle_max_delay_seconds, self.config.live_candle_future_skew_seconds,
            provider="dhan", symbol=self.identities[key]["symbol"], context="SCANNER", normalized_ist=True)

    def status(self):
        with self._lock:
            last_event = max((e["exchange_timestamp"] for e in self.latest.values()), default=None)
            eligible = False
            reported_state = self.state
            ref = _aware(self.clock())
            if self.transport and self.connected_at and (ref-self.connected_at).total_seconds() > 30 and any(k not in self.received or (ref-self.received[k]).total_seconds() > 30 for k in self.active):
                reported_state = "STALE"
            if self.state == "LIVE" and not self.fixture and self.received:
                fresh = all(k in self.received and (ref-self.received[k]).total_seconds() <= 30 for k in self.active)
                eligible = fresh and all(self._tail_assessment(k, 5, ref)[1]["live_signal_allowed"] for k in self.active)
            return dict(provider="dhan", protocol=PROTOCOL, state=reported_state, status=reported_state,
                reason_code=self.reason, live_signal_allowed=eligible, last_event_at=last_event,
                data_mode=self.mode, is_simulated=self.fixture, connected=self.transport is not None,
                configured_instruments=len(self.identities), subscribed_instruments=len(self.active),
                observed_subscriptions=len(self.subscription_observed), received_events=self.events,
                duplicate_packets=self.duplicates, reconnects=self.reconnects,
                connection_id=self.connection_id, current_live_acceptance=False,
                last_received_at=max(self.received.values()).isoformat() if self.received else None,
                heartbeat_policy="LIBRARY_PING_PONG_PLUS_30_SECOND_TRADE_FRESHNESS",
                backfill_status="NOT_AVAILABLE_RECONNECT_STARTS_NEW_LINEAGE",
                candle_counts={self.identities[k]["symbol"]: {str(n): len(v) for n, v in self.bars[k].items()} for k in self.active})

    def _fault(self, code):
        self.state, self.reason = "UNAVAILABLE", code
        old, self.transport = self.transport, None
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.current.clear()
        self.previous.clear()

    def reconnect(self):
        with self._lock:
            self._fault("RECONNECTING")
        return self.connect()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise FeedError("ALREADY_RUNNING")
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="dhan-read-only-feed", daemon=True)
            self._thread.start()
            return self._thread

    def _run(self):
        retry = 1
        while not self._stop.is_set():
            try:
                if self.transport is None:
                    self.connect()
                self.poll_once()
                retry = 1
            except FeedError:
                if self.reason in ("DHAN_AUTHENTICATION_FAILED", "DHAN_DATA_PERMISSION_MISSING", "DHAN_CONNECTION_OR_AUTHENTICATION_FAILED") or self.reason.startswith("DHAN_SUBSCRIPTION_REJECTED"):
                    break
                self._stop.wait(retry)
                retry = min(30, retry*2)

    def stop(self):
        self._stop.set()
        with self._lock:
            if self.transport:
                try:
                    self.transport.send(_json(dict(RequestCode=12)))
                except Exception:
                    pass
            self._fault("STOPPED")
            self.state = "STOPPED"
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=12)
            if self._thread.is_alive():
                raise FeedError("SHUTDOWN_TIMEOUT")

