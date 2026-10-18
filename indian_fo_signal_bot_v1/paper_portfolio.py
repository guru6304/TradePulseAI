"""Durable, order-free forward paper accounting on the existing SQLite store.

All fills are simulated. Source mode remains separate and never confers broker
acceptance, historical eligibility, or assurance that a price was executable.
"""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from backtest_engine import IndianCostModel
from brokers import assess_live_candle_batch, candle_session_context
from instrument_identity import IdentityValidationError, check_echo, validate_signal_identity
from strategies import IST, TradeSignal, format_ist_timestamp, parse_ist_timestamp, signal_state_identity, size_position, validate_candles


class PaperPortfolioError(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _reject(code):
    raise PaperPortfolioError(code)


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def _sum(values):
    return _money(sum((Decimal(str(value)) for value in values), Decimal(0)))


def _number(value, *, zero=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or (value < 0 if zero else value <= 0)):
        _reject("INVALID_NUMERIC_INPUT")
    return float(value)


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value):
        _reject("INVALID_SCOPE_IDENTIFIER")
    return value


@dataclass(frozen=True)
class PaperAccountConfig:
    account_id: str
    run_id: str
    provider: str
    source_data_mode: str
    starting_capital_inr: float = 150000.0
    risk_pct: float = 1.0
    max_daily_loss_inr: float = 3000.0
    max_open_positions: int = 3
    max_entries_per_day: int = 10
    max_position_exposure_pct: float = 50.0
    max_total_exposure_pct: float = 100.0
    allowed_strategies: tuple = ("strat_1_order_block", "strat_2_vwap_pullback", "strat_4_orb_filtered", "strat_5_supertrend_pullback")
    interval_min: int = 5
    max_mark_age_seconds: int = 60
    session_start_ist: str = "09:15"
    session_end_ist: str = "15:30"
    square_off_ist: str = "15:20"
    configured_holidays: tuple = ()
    cost_model_json: str = "{}"
    fill_policy: str = "OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1"

    def __post_init__(self):
        _name(self.account_id)
        _name(self.run_id)
        if self.provider not in ("angelone", "upstox", "dhan") or self.source_data_mode not in ("LIVE", "SIMULATED"):
            _reject("INVALID_SOURCE_SCOPE")
        for field in ("starting_capital_inr", "risk_pct", "max_daily_loss_inr",
                      "max_position_exposure_pct", "max_total_exposure_pct"):
            _number(getattr(self, field))
        if (self.risk_pct > 100 or self.max_position_exposure_pct > self.max_total_exposure_pct
                or self.max_total_exposure_pct > 100):
            _reject("INVALID_RISK_POLICY")
        for field in ("max_open_positions", "max_entries_per_day", "max_mark_age_seconds"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                _reject("INVALID_RISK_POLICY")
        if self.max_mark_age_seconds > 60 or type(self.interval_min) is not int or self.interval_min != 5:
            _reject("UNSUPPORTED_FRESHNESS_OR_INTERVAL_POLICY")
        permitted = {"strat_1_order_block", "strat_2_vwap_pullback", "strat_4_orb_filtered", "strat_5_supertrend_pullback"}
        if (not isinstance(self.allowed_strategies, (tuple, list)) or not self.allowed_strategies
                or any(not isinstance(s, str) or s not in permitted for s in self.allowed_strategies)
                or len(set(self.allowed_strategies)) != len(self.allowed_strategies)):
            _reject("UNSUPPORTED_PAPER_STRATEGY")
        object.__setattr__(self, "allowed_strategies", tuple(self.allowed_strategies))
        try:
            if not isinstance(self.configured_holidays, (tuple, list)):
                raise ValueError()
            holidays = tuple(self.configured_holidays)
            for value in holidays:
                if not isinstance(value, str) or datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
                    raise ValueError()
            clocks = []
            for value in (self.session_start_ist, self.square_off_ist, self.session_end_ist):
                if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
                    raise ValueError()
                clocks.append(time.fromisoformat(value))
            if not clocks[0] < clocks[1] <= clocks[2] or any(c.minute % 5 for c in clocks):
                raise ValueError()
            if self.fill_policy != "OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1":
                raise ValueError()
            if not isinstance(self.cost_model_json, str):
                raise ValueError()
            parameters = json.loads(self.cost_model_json)
            if not isinstance(parameters, dict):
                raise ValueError()
            model = IndianCostModel(**parameters)
            model.validate()
            datetime.strptime(model.effective_date, "%Y-%m-%d")
            object.__setattr__(self, "cost_model_json", _encode(model.to_dict()))
            object.__setattr__(self, "configured_holidays", holidays)
        except (ValueError, TypeError, OverflowError):
            _reject("INVALID_SESSION_OR_COST_POLICY")

    def to_dict(self):
        return asdict(self)

    @property
    def config_hash(self):
        return _hash(self.to_dict())


class PaperPortfolio:
    """Explicit service; construction creates only its configured paper account.

    No adapter, order, scheduler or notification API is called. A full position
    close is supported; partial closes are deliberately unsupported.
    """

    def __init__(self, store, config, clock=None):
        if not isinstance(config, PaperAccountConfig):
            _reject("EXPLICIT_PAPER_CONFIG_REQUIRED")
        self.store, self.config = store, config
        self.clock = clock or (lambda: datetime.now(IST))
        with self.store.paper_transaction(write=True) as conn:
            current = conn.execute("SELECT config_hash,config_json FROM paper_accounts WHERE account_id=?",
                                   (config.account_id,)).fetchone()
            if current:
                if current["config_hash"] != config.config_hash or current["config_json"] != _encode(config.to_dict()):
                    _reject("IMMUTABLE_ACCOUNT_CONFIG_CONFLICT")
            else:
                conn.execute("INSERT INTO paper_accounts(account_id,config_hash,config_json,created_at_ist) VALUES(?,?,?,?)",
                             (config.account_id, config.config_hash, _encode(config.to_dict()), format_ist_timestamp(self._now())))

    def _now(self, value=None):
        value = self.clock() if value is None else value
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            _reject("EXPLICIT_AWARE_CLOCK_REQUIRED")
        return value.astimezone(IST)

    @classmethod
    def report_existing(cls, store, account_id, as_of=None):
        """Read-only integration: never creates an account, event or position."""
        _name(account_id)
        now = as_of or datetime.now(IST)
        with store.paper_transaction(write=False) as conn:
            row = conn.execute("SELECT config_hash,config_json FROM paper_accounts WHERE account_id=?", (account_id,)).fetchone()
            if row is None:
                return dict(status="NOT_CONFIGURED", account_id=account_id, execution_mode="SIMULATED", positions=[], events=[])
            try:
                config = PaperAccountConfig(**json.loads(row["config_json"]))
                if config.config_hash != row["config_hash"]:
                    raise ValueError()
            except (ValueError, TypeError):
                return dict(status="RECONCILIATION_REQUIRED", account_id=account_id,
                            execution_mode="SIMULATED", entry_blocks=["ACCOUNT_CONFIG_CORRUPT"], positions=[], events=[])
            instance = cls.__new__(cls)
            instance.store, instance.config, instance.clock = store, config, lambda: now
            return instance._snapshot(conn, instance._now())

    def _positions(self, conn):
        return [json.loads(row["payload_json"]) for row in conn.execute(
            "SELECT payload_json FROM paper_positions WHERE account_id=? ORDER BY position_id", (self.config.account_id,))]

    def _events(self, conn):
        return [dict(row, payload=json.loads(row["payload_json"])) for row in conn.execute(
            "SELECT event_id,event_key,kind,position_id,payload_json FROM paper_events WHERE account_id=? ORDER BY rowid",
            (self.config.account_id,))]

    def _reconciliation(self, conn, positions, events):
        try:
            return self._reconcile_checked(conn, positions, events)
        except (KeyError, ValueError, TypeError, ArithmeticError):
            return dict(status="RECONCILIATION_REQUIRED", errors=["MALFORMED_PAPER_LEDGER"])

    def _reconcile_checked(self, conn, positions, events):
        errors = []
        by_id = {position["position_id"]: position for position in positions}
        for position in positions:
            own = [event for event in events if event["position_id"] == position["position_id"]]
            entries = [event for event in own if event["kind"] == "ENTRY"]
            exits = [event for event in own if event["kind"] == "EXIT"]
            if (position["status"] not in ("OPEN", "CLOSED") or len(entries) != 1
                    or len(exits) != (1 if position["status"] == "CLOSED" else 0)
                    or position["config_hash"] != self.config.config_hash
                    or position["account_id"] != self.config.account_id
                    or position["provider"] != self.config.provider
                    or position["source_data_mode"] != self.config.source_data_mode
                    or position["execution_mode"] != "SIMULATED"):
                errors.append("POSITION_LEDGER_SCOPE_OR_LIFECYCLE_MISMATCH")
                continue
            expected_entry = entries[0]["payload"]["entry"]
            for key, value in expected_entry.items():
                if position.get(key) != value:
                    errors.append("POSITION_ENTRY_LEDGER_MISMATCH")
                    break
            if exits:
                expected_exit = exits[0]["payload"]["exit"]
                if any(position.get(key) != value for key, value in expected_exit.items()):
                    errors.append("POSITION_EXIT_LEDGER_MISMATCH")
                costs = self._costs(position["raw_entry_price"], position["raw_exit_price"], position["quantity"], position["side"])
                sign = 1 if position["side"] == "LONG" else -1
                gross = _money(sign * (position["raw_exit_price"] - position["raw_entry_price"]) * position["quantity"])
                if (position["costs"] != costs or position["gross_pnl_inr"] != gross
                        or position["net_pnl_inr"] != _sum([gross, -costs["total_costs_inr"]])
                        or position["reserved_capital_inr"] != 0
                        or position["effective_exit_price"] != costs["effective_exit_price"]):
                    errors.append("RECALCULATED_EXIT_ACCOUNTING_MISMATCH")
            else:
                marks = [event["payload"]["mark"] for event in own if event["kind"] == "MARK"]
                if not marks or any(position.get(key) != value for key, value in marks[-1].items()):
                    errors.append("POSITION_MARK_LEDGER_MISMATCH")
                costs = self._costs(position["raw_entry_price"], position["mark_price"], position["quantity"], position["side"])
                sign = 1 if position["side"] == "LONG" else -1
                gross = _money(sign * (position["mark_price"] - position["raw_entry_price"]) * position["quantity"])
                if (position["estimated_close_costs"] != costs or position["unrealized_gross_pnl_inr"] != gross
                        or position["unrealized_net_pnl_inr"] != _sum([gross, -costs["total_costs_inr"]])
                        or position["reserved_capital_inr"] != position["initial_reserved_capital_inr"]):
                    errors.append("RECALCULATED_MARK_ACCOUNTING_MISMATCH")
        for event in events:
            if event["position_id"] not in by_id:
                errors.append("ORPHAN_PAPER_EVENT")
        account = conn.execute("SELECT config_hash,config_json FROM paper_accounts WHERE account_id=?",
                               (self.config.account_id,)).fetchone()
        if not account or account["config_hash"] != self.config.config_hash or account["config_json"] != _encode(self.config.to_dict()):
            errors.append("ACCOUNT_CONFIG_CORRUPT")
        return dict(status="OK" if not errors else "RECONCILIATION_REQUIRED", errors=sorted(set(errors)))

    def _snapshot(self, conn, now):
        positions, events = self._positions(conn), self._events(conn)
        reconciliation = self._reconciliation(conn, positions, events)
        opened = [p for p in positions if p["status"] == "OPEN"]
        closed = [p for p in positions if p["status"] == "CLOSED"]
        day = now.date().isoformat()
        realized = _sum(p["net_pnl_inr"] for p in closed)
        unrealized = _sum(p["unrealized_net_pnl_inr"] for p in opened)
        reserved = _sum(p["reserved_capital_inr"] for p in opened)
        raw_losses = _sum(min(0, p["unrealized_gross_pnl_inr"]) for p in opened)
        exposure = _sum(p["raw_entry_price"] * p["quantity"] for p in opened)
        daily_realized = _sum(p["net_pnl_inr"] for p in closed if p["exit_timestamp_ist"][:10] == day)
        daily_net = _sum([daily_realized, unrealized])
        blocks = []
        if reconciliation["status"] != "OK":
            blocks.append("RECONCILIATION_REQUIRED")
        for position in opened:
            closed_at = parse_ist_timestamp(position["mark_timestamp_ist"]) + timedelta(minutes=self.config.interval_min)
            age = (now - closed_at).total_seconds()
            if age < 0 or age > self.config.max_mark_age_seconds:
                blocks.append("MISSING_OR_STALE_MARKS")
            square_off = datetime.combine(parse_ist_timestamp(position["entry_timestamp_ist"]).date(),
                                          time.fromisoformat(self.config.square_off_ist), tzinfo=IST)
            if now >= square_off:
                blocks.append("UNRESOLVED_EOD_POSITION")
        loss_breached = daily_net <= -self.config.max_daily_loss_inr
        if loss_breached:
            blocks.append("DAILY_LOSS_LIMIT")
        entries = sum(p["entry_timestamp_ist"][:10] == day for p in positions)
        if entries >= self.config.max_entries_per_day:
            blocks.append("DAILY_ENTRY_LIMIT")
        if len(opened) >= self.config.max_open_positions:
            blocks.append("OPEN_POSITION_LIMIT")
        accounting = dict(starting_capital_inr=self.config.starting_capital_inr,
            realized_net_pnl_inr=realized, unrealized_net_pnl_inr=unrealized,
            equity_inr=_sum([self.config.starting_capital_inr, realized, unrealized]), reserved_capital_inr=reserved,
            available_capital_inr=max(0, _sum([self.config.starting_capital_inr, realized, raw_losses, -reserved])),
            gross_exposure_inr=exposure, fees_paid_inr=_sum(p["costs"]["charges_inr"] for p in closed),
            slippage_paid_inr=_sum(p["costs"]["slippage_inr"] for p in closed),
            open_positions=len(opened), closed_positions=len(closed),
            day=dict(date=day, entries=entries, realized_net_pnl_inr=daily_realized,
                     unrealized_net_pnl_inr=unrealized, net_pnl_inr=daily_net, loss_limit_breached=loss_breached))
        return dict(status="RECONCILIATION_REQUIRED" if reconciliation["status"] != "OK" else "BLOCKED" if blocks else "OK",
            account_id=self.config.account_id, run_id=self.config.run_id, config_hash=self.config.config_hash,
            provider=self.config.provider, source_data_mode=self.config.source_data_mode, execution_mode="SIMULATED",
            fill_policy=self.config.fill_policy, as_of_ist=format_ist_timestamp(now), accounting=accounting,
            entry_blocks=sorted(set(blocks)), reconciliation=reconciliation, positions=positions,
            events=[dict(event_id=e["event_id"], event_key=e["event_key"], kind=e["kind"], position_id=e["position_id"],
                         **e["payload"]) for e in events[-200:]], total_events=len(events))

    def snapshot(self, as_of=None):
        with self.store.paper_transaction(write=False) as conn:
            return self._snapshot(conn, self._now(as_of))

    def reconcile(self):
        return self.snapshot()["reconciliation"]

    def _bar(self, bar, identity, now):
        if not isinstance(bar, dict) or bar.get("is_complete") is not True:
            _reject("COMPLETED_SOURCE_BAR_REQUIRED")
        expected_sim = self.config.source_data_mode == "SIMULATED"
        if (bar.get("data_mode") != self.config.source_data_mode or bar.get("is_simulated") is not expected_sim
                or bar.get("interval_min") != self.config.interval_min or isinstance(bar.get("interval_min"), bool)):
            _reject("BAR_SOURCE_SCOPE_MISMATCH")
        supplied = bar.get("instrument_identity")
        keys = ("provider", "symbol", "identifier", "exchange", "segment", "instrument_type", "source", "source_revision", "historical_validity")
        if not isinstance(supplied, dict) or any(supplied.get(key) != identity.get(key) for key in keys):
            _reject("BAR_INSTRUMENT_IDENTITY_MISMATCH")
        try:
            # Provenance was checked above. Preserve every identity echo while
            # avoiding promotion of explicitly SIMULATED source data to LIVE.
            check_echo({key: value for key, value in bar.items() if key not in ("data_mode", "is_simulated")}, identity)
        except IdentityValidationError:
            _reject("BAR_INSTRUMENT_IDENTITY_MISMATCH")
        raw_timestamp = bar.get("timestamp")
        normalized = bar.get("timestamp_timezone") == "Asia/Kolkata"
        try:
            for key in ("open", "high", "low", "close", "volume"):
                _number(bar.get(key))
            if not normalized:
                explicit = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")) if isinstance(raw_timestamp, str) else raw_timestamp
                if not isinstance(explicit, datetime) or explicit.tzinfo is None or explicit.utcoffset() is None:
                    raise ValueError()
            stamp = parse_ist_timestamp(raw_timestamp)
            normalized_bar = validate_candles([bar], interval_min=self.config.interval_min, now=now, deduplicate=False)[0]
            _, start, end, state, expected_date = candle_session_context(now, self.config.configured_holidays,
                self.config.session_start_ist, self.config.session_end_ist)
            session_open = datetime.combine(stamp.date(), start, tzinfo=IST)
            session_close = datetime.combine(stamp.date(), end, tzinfo=IST)
            close = stamp + timedelta(minutes=self.config.interval_min)
            if (state != "within_session" or stamp.date() != expected_date or not session_open <= stamp < close <= session_close
                    or (stamp - session_open).total_seconds() % (self.config.interval_min * 60)
                    or not 0 <= (now - close).total_seconds() <= self.config.max_mark_age_seconds
                    or normalized_bar.get("is_complete") is not True):
                raise ValueError()
            if self.config.source_data_mode == "LIVE":
                _, report = assess_live_candle_batch([bar], self.config.interval_min, now,
                    self.config.configured_holidays, self.config.session_start_ist, self.config.session_end_ist,
                    self.config.max_mark_age_seconds, 0, provider=self.config.provider,
                    symbol=identity["symbol"], context="SCANNER", normalized_ist=normalized)
                if not report["live_signal_allowed"]:
                    raise ValueError()
            if now.date().isoformat() < self._model().effective_date:
                _reject("COST_SCHEDULE_NOT_EFFECTIVE")
        except (ValueError, TypeError, KeyError, OverflowError):
            _reject("INVALID_STALE_OR_UNFINISHED_BAR")
        return dict(timestamp=format_ist_timestamp(stamp), open=float(normalized_bar["open"]), high=float(normalized_bar["high"]),
                    low=float(normalized_bar["low"]), close=float(normalized_bar["close"]), volume=float(normalized_bar["volume"]),
                    instrument_identity=supplied, source_data_mode=self.config.source_data_mode)

    def _candidate(self, candidate):
        data = candidate.to_dict() if isinstance(candidate, TradeSignal) else candidate
        if not isinstance(data, dict):
            _reject("PAPER_CANDIDATE_REQUIRED")
        data = json.loads(_encode(data))
        if (data.get("provider") != self.config.provider or data.get("data_mode") != self.config.source_data_mode
                or data.get("is_simulated") is not (self.config.source_data_mode == "SIMULATED")
                or data.get("strategy_id") not in self.config.allowed_strategies
                or data.get("interval_min") != 5 or isinstance(data.get("interval_min"), bool)):
            _reject("CANDIDATE_SCOPE_OR_STRATEGY_MISMATCH")
        identity = data.get("instrument_identity")
        if (data.get("segment") != "NSE_EQUITY_INTRADAY" or not isinstance(identity, dict)
                or identity.get("instrument_type") != "EQ" or identity.get("is_index") is not False
                or data.get("position_type") not in ("LONG_EQUITY_INTRADAY", "SHORT_EQUITY_INTRADAY")):
            _reject("UNSUPPORTED_PAPER_CONTRACT")
        try:
            validate_signal_identity(data)
            signal_state_identity(data)
        except (ValueError, IdentityValidationError):
            _reject("INVALID_CANDIDATE_IDENTITY")
        side = "LONG" if data["position_type"] == "LONG_EQUITY_INTRADAY" else "SHORT"
        if ("BULLISH" if side == "LONG" else "BEARISH") not in data.get("direction", ""):
            _reject("CANDIDATE_SIDE_CONFLICT")
        for key in ("entry_price", "stop_loss", "target_1", "target_2", "invalidation_level"):
            _number(data.get(key))
        sign = 1 if side == "LONG" else -1
        stop, invalidation, entry, target, target2 = (sign * data[key] for key in
            ("stop_loss", "invalidation_level", "entry_price", "target_1", "target_2"))
        if not stop <= invalidation < entry < target <= target2:
            _reject("INVALID_ENTRY_STOP_TARGET_BRACKET")
        return data, side

    def _model(self):
        return IndianCostModel(**json.loads(self.config.cost_model_json))

    def _costs(self, entry, exit_price, quantity, side):
        return self._model().compute_trade_costs(entry, exit_price, quantity, side,
            segment="NSE_EQUITY_INTRADAY", instrument_type="EQ", exchange="NSE")

    def _event_retry(self, conn, event_key, command_hash):
        _name(event_key)
        if event_key.endswith(":fill"):
            _reject("RESERVED_EVENT_KEY_SUFFIX")
        event = conn.execute("SELECT payload_json FROM paper_events WHERE account_id=? AND event_key=?",
                             (self.config.account_id, event_key)).fetchone()
        if not event:
            return None
        payload = json.loads(event["payload_json"])
        if payload.get("command_hash") != command_hash:
            _reject("EVENT_IDEMPOTENCY_CONFLICT")
        return dict(payload["result"], idempotent=True)

    def _event(self, conn, key, kind, position, payload):
        conn.execute("INSERT INTO paper_events(event_id,account_id,event_key,kind,position_id,payload_json) VALUES(?,?,?,?,?,?)",
            (_hash([self.config.account_id, key]), self.config.account_id, key, kind, position["position_id"], _encode(payload)))

    def _save(self, conn, position):
        conn.execute("UPDATE paper_positions SET payload_json=? WHERE account_id=? AND position_id=?",
                     (_encode(position), self.config.account_id, position["position_id"]))

    def _mark_or_exit(self, conn, position, bar, key, command_hash):
        sign = 1 if position["side"] == "LONG" else -1
        opening, stop, target = bar["open"], position["stop_loss"], position["target_price"]
        loss_touch = bar["low"] <= stop if sign == 1 else bar["high"] >= stop
        profit_touch = bar["high"] >= target if sign == 1 else bar["low"] <= target
        reason, exit_price = None, None
        if sign * opening <= sign * stop:
            reason, exit_price = "STOP_GAP", opening
        elif sign * opening >= sign * target:
            reason, exit_price = "TARGET_GAP_CAPPED", target
        elif loss_touch:
            reason, exit_price = "STOP_FIRST_COLLISION" if profit_touch else "STOP", stop
        elif profit_touch:
            reason, exit_price = "TARGET", target
        elif (parse_ist_timestamp(bar["timestamp"]) + timedelta(minutes=5)).time() >= time.fromisoformat(self.config.square_off_ist):
            reason, exit_price = "EOD", bar["close"]
        if reason:
            costs = self._costs(position["raw_entry_price"], exit_price, position["quantity"], position["side"])
            gross = _money(sign * (exit_price - position["raw_entry_price"]) * position["quantity"])
            closed = dict(status="CLOSED", raw_exit_price=exit_price, effective_exit_price=costs["effective_exit_price"],
                exit_reason=reason, exit_timestamp_ist=bar["timestamp"], gross_pnl_inr=gross,
                net_pnl_inr=_sum([gross, -costs["total_costs_inr"]]), costs=costs,
                reserved_capital_inr=0.0, unrealized_gross_pnl_inr=0.0, unrealized_net_pnl_inr=0.0,
                mark_price=bar["close"], mark_timestamp_ist=bar["timestamp"], mark_provenance=bar)
            position.update(closed)
            self._save(conn, position)
            result = dict(status="CLOSED", position_id=position["position_id"], execution_mode="SIMULATED", exit_reason=reason)
            self._event(conn, key, "EXIT", position, dict(command_hash=command_hash, exit=closed, result=result))
        else:
            costs = self._costs(position["raw_entry_price"], bar["close"], position["quantity"], position["side"])
            gross = _money(sign * (bar["close"] - position["raw_entry_price"]) * position["quantity"])
            mark = dict(mark_price=bar["close"], mark_timestamp_ist=bar["timestamp"], mark_provenance=bar,
                unrealized_gross_pnl_inr=gross, unrealized_net_pnl_inr=_sum([gross, -costs["total_costs_inr"]]),
                estimated_close_costs=costs)
            position.update(mark)
            self._save(conn, position)
            result = dict(status="OPEN", position_id=position["position_id"], execution_mode="SIMULATED")
            self._event(conn, key, "MARK", position, dict(command_hash=command_hash, mark=mark, result=result))
        return result

    def enter(self, candidate, completed_next_bar, event_key):
        """Atomically reserve and simulate the next completed bar, including exits."""
        data, side = self._candidate(candidate)
        now = self._now()
        command_hash = _hash(dict(operation="ENTRY", candidate=data, bar=completed_next_bar))
        with self.store.paper_transaction(write=True) as conn:
            retry = self._event_retry(conn, event_key, command_hash)
            if retry:
                return retry
            bar = self._bar(completed_next_bar, data["instrument_identity"], now)
            signal_time = parse_ist_timestamp(data["timestamp"])
            fill_time = parse_ist_timestamp(bar["timestamp"])
            if (fill_time != signal_time + timedelta(minutes=5) or fill_time.date() != signal_time.date()
                    or fill_time.time() >= time.fromisoformat(self.config.square_off_ist)):
                _reject("NEXT_COMPLETED_SAME_SESSION_BAR_REQUIRED")
            entry_key = _hash([self.config.run_id, signal_state_identity(data)[0]])
            existing = conn.execute("SELECT payload_json FROM paper_positions WHERE account_id=? AND entry_key=?",
                                    (self.config.account_id, entry_key)).fetchone()
            if existing:
                position = json.loads(existing["payload_json"])
                if position["candidate_hash"] != _hash(data) or position["entry_provenance"] != bar:
                    _reject("CANDIDATE_IDEMPOTENCY_CONFLICT")
                return dict(status=position["status"], position_id=position["position_id"],
                            execution_mode="SIMULATED", idempotent=True)
            snapshot = self._snapshot(conn, now)
            if snapshot["entry_blocks"]:
                _reject(snapshot["entry_blocks"][0])
            if (datetime.combine(now.date(), time.fromisoformat(self.config.square_off_ist), tzinfo=IST) <= now):
                _reject("ENTRY_AFTER_SQUARE_OFF")
            opening = bar["open"]
            sign = 1 if side == "LONG" else -1
            effective = self._costs(opening, data["stop_loss"], 1, side)["effective_entry_price"]
            if not (sign * data["stop_loss"] < sign * opening < sign * data["target_1"]
                    and sign * data["stop_loss"] < sign * effective < sign * data["target_1"]
                    and sign * opening > sign * data["invalidation_level"]):
                _reject("ENTRY_GAP_OUTSIDE_VALID_BRACKET")
            available = snapshot["accounting"]["available_capital_inr"]
            if available <= 0:
                _reject("INSUFFICIENT_CAPITAL")
            base = self.config.starting_capital_inr
            exposure_room = min(base * self.config.max_position_exposure_pct / 100,
                base * self.config.max_total_exposure_pct / 100 - snapshot["accounting"]["gross_exposure_inr"])
            if exposure_room < opening:
                _reject("EXPOSURE_LIMIT")
            # Conservatively use the smaller available-capital/exposure allowance
            # for both capital and percentage-risk sizing; never round quantity up.
            sizing_capital = min(available, exposure_room)
            sizing = size_position(opening, data["stop_loss"], sizing_capital, self.config.risk_pct, side,
                instrument_type="EQ", lot_size=1,
                cost_estimator=lambda quantity: self._costs(opening, data["stop_loss"], quantity, side))
            if not sizing["eligible"]:
                _reject(sizing["reason_code"])
            notional = _money(opening * sizing["quantity"])
            if notional > base * self.config.max_position_exposure_pct / 100:
                _reject("POSITION_EXPOSURE_LIMIT")
            if notional + snapshot["accounting"]["gross_exposure_inr"] > base * self.config.max_total_exposure_pct / 100:
                _reject("AGGREGATE_EXPOSURE_LIMIT")
            position = dict(position_id=_hash([self.config.account_id, entry_key]), account_id=self.config.account_id,
                run_id=self.config.run_id, config_hash=self.config.config_hash, provider=self.config.provider,
                source_data_mode=self.config.source_data_mode, execution_mode="SIMULATED", strategy_id=data["strategy_id"],
                symbol=data["symbol"], instrument_identity=data["instrument_identity"], candidate_hash=_hash(data),
                candidate_timestamp_ist=format_ist_timestamp(signal_time), entry_key=entry_key, side=side,
                raw_entry_price=opening, effective_entry_price=sizing["effective_entry_price"],
                quantity=sizing["quantity"], stop_loss=data["stop_loss"], target_price=data["target_1"],
                invalidation_level=data["invalidation_level"], entry_timestamp_ist=bar["timestamp"],
                estimated_stop_risk_inr=sizing["estimated_risk_inr"], initial_reserved_capital_inr=sizing["capital_required_inr"],
                status="OPEN", reserved_capital_inr=sizing["capital_required_inr"], fill_policy=self.config.fill_policy,
                entry_provenance=bar)
            conn.execute("INSERT INTO paper_positions(position_id,account_id,entry_key,payload_json) VALUES(?,?,?,?)",
                (position["position_id"], self.config.account_id, entry_key, _encode(position)))
            immutable = {key: value for key, value in position.items() if key not in ("status", "reserved_capital_inr")}
            # Entry and first-bar result commit together; no capital-only orphan.
            result = self._mark_or_exit(conn, position, bar, event_key + ":fill", command_hash)
            self._event(conn, event_key, "ENTRY", position,
                dict(command_hash=command_hash, entry=immutable, result=result))
            return result

    def process_bar(self, position_id, completed_bar, event_key):
        """Apply one next completed bar. Missing intervals freeze, never invent fills."""
        _name(event_key)
        now = self._now()
        command_hash = _hash(dict(operation="BAR", position_id=position_id, bar=completed_bar))
        with self.store.paper_transaction(write=True) as conn:
            retry = self._event_retry(conn, event_key, command_hash)
            if retry:
                return retry
            positions, events = self._positions(conn), self._events(conn)
            if self._reconciliation(conn, positions, events)["status"] != "OK":
                _reject("RECONCILIATION_REQUIRED")
            position = next((p for p in positions if p["position_id"] == position_id), None)
            if position is None:
                _reject("POSITION_NOT_IN_ACCOUNT")
            if position["status"] != "OPEN":
                _reject("POSITION_ALREADY_CLOSED")
            bar = self._bar(completed_bar, position["instrument_identity"], now)
            expected = parse_ist_timestamp(position["mark_timestamp_ist"]) + timedelta(minutes=5)
            stamp = parse_ist_timestamp(bar["timestamp"])
            if stamp != expected or stamp.date() != parse_ist_timestamp(position["entry_timestamp_ist"]).date():
                _reject("MISSING_OR_OUT_OF_ORDER_POSITION_BAR")
            return self._mark_or_exit(conn, position, bar, event_key, command_hash)
