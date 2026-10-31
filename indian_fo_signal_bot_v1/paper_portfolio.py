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
from paper_triggers import TRIGGER_FILL_POLICIES
from strategies import IST, TradeSignal, format_ist_timestamp, parse_ist_timestamp, signal_state_identity, size_position, validate_candles

FORWARD_FILL_POLICY = "NEXT_COMPLETED_BAR_CLOSE_V1"


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
            if self.fill_policy not in ("OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1", FORWARD_FILL_POLICY, *TRIGGER_FILL_POLICIES):
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
    def report_existing(cls, store, account_id, as_of=None, session_date=None):
        """Read-only integration: never creates an account, event or position."""
        _name(account_id)
        now = as_of or datetime.now(IST)
        with store.paper_transaction(write=False) as conn:
            row = conn.execute("SELECT config_hash,config_json FROM paper_accounts WHERE account_id=?", (account_id,)).fetchone()
            if row is None:
                return dict(status="NOT_CONFIGURED", account_id=account_id, execution_mode="SIMULATED", positions=[], events=[], candidate_decisions=[])
            try:
                config = PaperAccountConfig(**json.loads(row["config_json"]))
                if config.config_hash != row["config_hash"]:
                    raise ValueError()
            except (ValueError, TypeError):
                return dict(status="RECONCILIATION_REQUIRED", account_id=account_id,
                            execution_mode="SIMULATED", entry_blocks=["ACCOUNT_CONFIG_CORRUPT"], positions=[], events=[], candidate_decisions=[])
            instance = cls.__new__(cls)
            instance.store, instance.config, instance.clock = store, config, lambda: now
            return (instance._session_statement(conn, session_date, instance._now()) if session_date is not None
                    else instance._snapshot(conn, instance._now()))

    def _positions(self, conn):
        for row in conn.execute("SELECT position_id,CASE WHEN length(CAST(payload_json AS BLOB))<=524288 "
                                "THEN payload_json END AS body FROM paper_positions "
                                "WHERE account_id=? ORDER BY position_id", (self.config.account_id,)):
            position = self._decode(row["body"])
            if position["position_id"] != row["position_id"]:
                _reject("POSITION_ID_MISMATCH")
            yield position

    @staticmethod
    def _decode(body):
        value = json.loads(body)
        if not isinstance(value, dict):
            _reject("MALFORMED_PAPER_LEDGER")
        return value

    def _events(self, conn, position_id=None, *, preview=False):
        scope = " AND position_id=?" if position_id is not None else ""
        order = " ORDER BY rowid DESC LIMIT 200" if preview else " ORDER BY rowid"
        params = (self.config.account_id, position_id) if position_id is not None else (self.config.account_id,)
        for row in conn.execute("SELECT event_id,event_key,kind,position_id,"
                                "CASE WHEN length(CAST(payload_json AS BLOB))<=524288 THEN payload_json END AS body "
                                "FROM paper_events WHERE account_id=?" + scope + order, params):
            yield dict(event_id=row["event_id"], event_key=row["event_key"], kind=row["kind"],
                       position_id=row["position_id"], payload=self._decode(row["body"]))

    def _reconciliation(self, conn):
        try:
            return self._reconcile_checked(conn)
        except (KeyError, ValueError, TypeError, ArithmeticError, RecursionError):
            return dict(status="RECONCILIATION_REQUIRED", errors=["MALFORMED_PAPER_LEDGER"])

    def _reconcile_checked(self, conn):
        errors = set()
        # Indexed per-position streams retain only the last mark and single
        # entry/exit, even if one position has many thousands of observations.
        for position in self._positions(conn):
            entry, exit_event, mark = None, None, None
            entries, exits = 0, 0
            for event in self._events(conn, position["position_id"]):
                if event["kind"] == "ENTRY":
                    entry = event["payload"]["entry"]
                    entries += 1
                elif event["kind"] == "EXIT":
                    exit_event = event["payload"]["exit"]
                    exits += 1
                elif event["kind"] == "MARK":
                    if exits:
                        errors.add("MARK_AFTER_CLOSED_POSITION")
                    mark = event["payload"]["mark"]
                else:
                    errors.add("UNKNOWN_PAPER_EVENT_KIND")
            if (position["status"] not in ("OPEN", "CLOSED") or entries != 1
                    or exits != (1 if position["status"] == "CLOSED" else 0)
                    or position["config_hash"] != self.config.config_hash
                    or position["account_id"] != self.config.account_id
                    or position["provider"] != self.config.provider
                    or position["source_data_mode"] != self.config.source_data_mode
                    or position["execution_mode"] != "SIMULATED"):
                errors.add("POSITION_LEDGER_SCOPE_OR_LIFECYCLE_MISMATCH")
                continue
            for key, value in entry.items():
                if position.get(key) != value:
                    errors.add("POSITION_ENTRY_LEDGER_MISMATCH")
                    break
            if exits:
                if any(position.get(key) != value for key, value in exit_event.items()):
                    errors.add("POSITION_EXIT_LEDGER_MISMATCH")
                costs = self._costs(position["raw_entry_price"], position["raw_exit_price"], position["quantity"], position["side"])
                sign = 1 if position["side"] == "LONG" else -1
                gross = _money(sign * (position["raw_exit_price"] - position["raw_entry_price"]) * position["quantity"])
                if (position["costs"] != costs or position["gross_pnl_inr"] != gross
                        or position["net_pnl_inr"] != _sum([gross, -costs["total_costs_inr"]])
                        or position["reserved_capital_inr"] != 0
                        or position["effective_exit_price"] != costs["effective_exit_price"]):
                    errors.add("RECALCULATED_EXIT_ACCOUNTING_MISMATCH")
            else:
                if mark is None or any(position.get(key) != value for key, value in mark.items()):
                    errors.add("POSITION_MARK_LEDGER_MISMATCH")
                costs = self._costs(position["raw_entry_price"], position["mark_price"], position["quantity"], position["side"])
                sign = 1 if position["side"] == "LONG" else -1
                gross = _money(sign * (position["mark_price"] - position["raw_entry_price"]) * position["quantity"])
                if (position["estimated_close_costs"] != costs or position["unrealized_gross_pnl_inr"] != gross
                        or position["unrealized_net_pnl_inr"] != _sum([gross, -costs["total_costs_inr"]])
                        or position["reserved_capital_inr"] != position["initial_reserved_capital_inr"]):
                    errors.add("RECALCULATED_MARK_ACCOUNTING_MISMATCH")
        if conn.execute("SELECT 1 FROM paper_events e LEFT JOIN paper_positions p "
                        "ON p.position_id=e.position_id AND p.account_id=e.account_id "
                        "WHERE e.account_id=? AND p.position_id IS NULL LIMIT 1", (self.config.account_id,)).fetchone():
            errors.add("ORPHAN_PAPER_EVENT")
        account = conn.execute("SELECT config_hash,config_json FROM paper_accounts WHERE account_id=?",
                               (self.config.account_id,)).fetchone()
        if not account or account["config_hash"] != self.config.config_hash or account["config_json"] != _encode(self.config.to_dict()):
            errors.add("ACCOUNT_CONFIG_CORRUPT")
        return dict(status="OK" if not errors else "RECONCILIATION_REQUIRED", errors=sorted(errors))

    def _snapshot(self, conn, now):
        try:
            return self._snapshot_checked(conn, now)
        except (KeyError, ValueError, TypeError, ArithmeticError, RecursionError):
            return dict(status="RECONCILIATION_REQUIRED", account_id=self.config.account_id,
                        execution_mode="SIMULATED", accounting=None, entry_blocks=["RECONCILIATION_REQUIRED"],
                        reconciliation=dict(status="RECONCILIATION_REQUIRED", errors=["MALFORMED_PAPER_LEDGER"]),
                        positions=[], events=[], candidate_decisions=[])

    @staticmethod
    def _preview_append(items, item, used):
        size = len(json.dumps(item, allow_nan=False).encode("utf-8"))
        if len(items) < 200 and used + size <= 256 * 1024:
            items.append(item)
            return used + size
        return used

    def _snapshot_checked(self, conn, now):
        reconciliation = self._reconciliation(conn)
        day = now.date().isoformat()
        totals = dict.fromkeys(("realized", "unrealized", "reserved", "raw_losses", "exposure", "daily_realized", "fees", "slippage"), Decimal(0))
        positions, used, opened, closed, entries = [], 0, 0, 0, 0
        blocks = set()
        if reconciliation["status"] != "OK":
            blocks.add("RECONCILIATION_REQUIRED")
        for p in self._positions(conn):
            used = self._preview_append(positions, p, used)
            entries += p["entry_timestamp_ist"][:10] == day
            if p["status"] == "CLOSED":
                closed += 1
                values = dict(realized=p["net_pnl_inr"], fees=p["costs"]["charges_inr"], slippage=p["costs"]["slippage_inr"],
                              daily_realized=p["net_pnl_inr"] if p["exit_timestamp_ist"][:10] == day else 0)
            elif p["status"] == "OPEN":
                opened += 1
                values = dict(unrealized=p["unrealized_net_pnl_inr"], reserved=p["reserved_capital_inr"],
                              raw_losses=min(0, p["unrealized_gross_pnl_inr"]), exposure=p["raw_entry_price"] * p["quantity"])
                closed_at = parse_ist_timestamp(p["mark_timestamp_ist"]) + timedelta(minutes=self.config.interval_min)
                age = (now - closed_at).total_seconds()
                if age < 0 or age > self.config.max_mark_age_seconds:
                    blocks.add("MISSING_OR_STALE_MARKS")
                square_off = datetime.combine(parse_ist_timestamp(p["entry_timestamp_ist"]).date(),
                                              time.fromisoformat(self.config.square_off_ist), tzinfo=IST)
                if now >= square_off:
                    blocks.add("UNRESOLVED_EOD_POSITION")
            else:
                _reject("INVALID_POSITION_STATUS")
            for key, value in values.items():
                totals[key] += Decimal(str(value))
        realized, unrealized, reserved, raw_losses, exposure, daily_realized, fees, slippage = map(_money, totals.values())
        daily_net = _sum([daily_realized, unrealized])
        loss_breached = daily_net <= -self.config.max_daily_loss_inr
        if loss_breached:
            blocks.add("DAILY_LOSS_LIMIT")
        if entries >= self.config.max_entries_per_day:
            blocks.add("DAILY_ENTRY_LIMIT")
        if opened >= self.config.max_open_positions:
            blocks.add("OPEN_POSITION_LIMIT")
        accounting = dict(starting_capital_inr=self.config.starting_capital_inr,
            realized_net_pnl_inr=realized, unrealized_net_pnl_inr=unrealized,
            equity_inr=_sum([self.config.starting_capital_inr, realized, unrealized]), reserved_capital_inr=reserved,
            available_capital_inr=max(0, _sum([self.config.starting_capital_inr, realized, raw_losses, -reserved])),
            gross_exposure_inr=exposure, fees_paid_inr=fees, slippage_paid_inr=slippage,
            open_positions=opened, closed_positions=closed,
            day=dict(date=day, entries=entries, realized_net_pnl_inr=daily_realized,
                     unrealized_net_pnl_inr=unrealized, net_pnl_inr=daily_net, loss_limit_breached=loss_breached))
        decisions, events = [], []
        used = 0
        for row in conn.execute("SELECT CASE WHEN length(CAST(payload_json AS BLOB))<=524288 THEN payload_json END AS body "
                                "FROM paper_candidate_decisions WHERE account_id=? ORDER BY candidate_id LIMIT 200", (self.config.account_id,)):
            used = self._preview_append(decisions, self._decode(row["body"]), used)
        used = 0
        for e in self._events(conn, preview=True):
            used = self._preview_append(events, dict(event_id=e["event_id"], event_key=e["event_key"], kind=e["kind"],
                                                   position_id=e["position_id"], **e["payload"]), used)
        events.reverse()
        total_events = conn.execute("SELECT COUNT(*) FROM paper_events WHERE account_id=?", (self.config.account_id,)).fetchone()[0]
        total_decisions = conn.execute("SELECT COUNT(*) FROM paper_candidate_decisions WHERE account_id=?", (self.config.account_id,)).fetchone()[0]
        return dict(status="RECONCILIATION_REQUIRED" if reconciliation["status"] != "OK" else "BLOCKED" if blocks else "OK",
            account_id=self.config.account_id, run_id=self.config.run_id, config_hash=self.config.config_hash,
            provider=self.config.provider, source_data_mode=self.config.source_data_mode, execution_mode="SIMULATED",
            fill_policy=self.config.fill_policy, as_of_ist=format_ist_timestamp(now), accounting=accounting,
            entry_blocks=sorted(blocks), reconciliation=reconciliation, positions=positions,
            events=events, total_events=total_events, candidate_decisions=decisions,
            total_positions=opened + closed, total_candidate_decisions=total_decisions,
            previews_truncated=dict(positions=len(positions) < opened + closed, events=len(events) < total_events,
                                    candidate_decisions=len(decisions) < total_decisions),
            ledger_page_path="/api/paper-ledger")

    def snapshot(self, as_of=None):
        with self.store.paper_transaction(write=False) as conn:
            return self._snapshot(conn, self._now(as_of))

    def reconcile(self):
        with self.store.paper_transaction(write=False) as conn:
            return self._reconciliation(conn)

    def open_positions(self):
        """Internal coordinator input, independent of bounded report previews."""
        with self.store.paper_transaction(write=False) as conn:
            return [p for p in self._positions(conn) if p["status"] == "OPEN"]

    def review_unresolved_eod(self, position_id, event_key, *, requested_action="KEEP_FROZEN", observation_sha256=None):
        """Audit a freeze/denied repair request. Never change a financial row.

        A hash is a reference to a proposed observation, not qualification or a
        price. Historical repair requires a separately approved policy; this
        method cannot approve it or replay a late candle into the live ledger.
        """
        _name(event_key)
        if requested_action not in ("KEEP_FROZEN", "REQUEST_LATE_HISTORICAL_REPAIR"):
            _reject("UNAPPROVED_FINANCIAL_RECOVERY_ACTION")
        if observation_sha256 is not None and (not isinstance(observation_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", observation_sha256)):
            _reject("INVALID_OBSERVATION_REFERENCE")
        request = dict(position_id=position_id, requested_action=requested_action, observation_sha256=observation_sha256)
        request_hash = _hash(request)
        now = self._now()
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT CASE WHEN length(CAST(payload_json AS BLOB))<=524288 THEN payload_json END "
                               "FROM paper_recovery_decisions WHERE account_id=? AND event_key=?",
                               (self.config.account_id, event_key)).fetchone()
            if row:
                try:
                    saved = self._decode(row[0])
                    if (saved['record_sha256']!=_hash({k:v for k,v in saved.items() if k!='record_sha256'})
                            or saved['request_hash']!=_hash(saved['request'])
                            or saved['config_hash']!=self.config.config_hash or saved['account_id']!=self.config.account_id
                            or saved['financial_mutations'] is not False):
                        raise ValueError()
                except (KeyError,ValueError,TypeError,RecursionError):
                    _reject('RECONCILIATION_REQUIRED')
                if saved["request_hash"] != request_hash:
                    _reject("EVENT_IDEMPOTENCY_CONFLICT")
                return dict(saved, idempotent=True)
            if self._reconciliation(conn)["status"] != "OK":
                _reject("RECONCILIATION_REQUIRED")
            row = conn.execute("SELECT payload_json FROM paper_positions WHERE account_id=? AND position_id=?",
                               (self.config.account_id, position_id)).fetchone()
            if not row:
                _reject("POSITION_NOT_IN_ACCOUNT")
            p = self._decode(row[0])
            if p["status"] != "OPEN":
                _reject("POSITION_ALREADY_CLOSED")
            cutoff = datetime.combine(parse_ist_timestamp(p["entry_timestamp_ist"]).date(),
                                      time.fromisoformat(self.config.square_off_ist), tzinfo=IST)
            if now <= cutoff + timedelta(seconds=self.config.max_mark_age_seconds):
                _reject("EOD_RECOVERY_NOT_DUE")
            key = _hash([self.config.account_id, "recovery", event_key])
            decision = dict(decision_id=key, account_id=self.config.account_id, config_hash=self.config.config_hash,
                provider=self.config.provider, source_data_mode=self.config.source_data_mode, execution_mode="SIMULATED",
                position_id=position_id, request_hash=request_hash, request=request,
                status="FROZEN" if requested_action == "KEEP_FROZEN" else "BLOCKED_POLICY_APPROVAL_REQUIRED",
                reason_code="MISSING_EOD_OBSERVATION_NO_FINANCIAL_REPAIR_AUTHORIZED",
                observed_at_ist=format_ist_timestamp(now), financial_mutations=False,
                readiness_receipt_issued=False, historical_replay_allowed=False)
            decision['record_sha256']=_hash(decision)
            conn.execute("INSERT INTO paper_recovery_decisions VALUES(?,?,?,?,?)",
                         (key, self.config.account_id, event_key, self.config.config_hash, _encode(decision)))
            return decision

    def session_statement(self, session_date, as_of=None):
        with self.store.paper_transaction(write=False) as conn:
            return self._session_statement(conn, session_date, self._now(as_of))

    def _session_statement(self, conn, session_date, now):
        """Read-only event-derived EOD summary; later-session P&L cannot leak in."""
        try:
            day = datetime.strptime(session_date, "%Y-%m-%d").date()
            if day.isoformat() != session_date or day.weekday() >= 5 or session_date in self.config.configured_holidays:
                raise ValueError()
            end = datetime.combine(day, time.fromisoformat(self.config.session_end_ist), tzinfo=IST)
            if now < end:
                _reject("SESSION_NOT_ENDED")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, PaperPortfolioError):
                raise
            _reject("INVALID_CONFIGURED_SESSION_DATE")
        recon = self._reconciliation(conn)
        if recon["status"] != "OK":
            return dict(status="RECONCILIATION_REQUIRED", account_id=self.config.account_id,
                        session_date=session_date, accounting=None, reconciliation=recon)
        try:
            totals = dict.fromkeys(("realized", "realized_day", "gross_day", "fees_day", "fees", "slippage",
                                   "unrealized", "raw_losses", "reserved"), Decimal(0))
            opened = closed = entries = event_count = 0
            digest = hashlib.sha256()
            for p in self._positions(conn):
                entry = mark = exit_data = None
                for event in self._events(conn, p["position_id"]):
                    payload = event["payload"]
                    field = {"ENTRY": "entry", "MARK": "mark", "EXIT": "exit"}[event["kind"]]
                    state = payload[field]
                    timestamp_key = {"ENTRY": "entry_timestamp_ist", "MARK": "mark_timestamp_ist", "EXIT": "exit_timestamp_ist"}[event["kind"]]
                    if parse_ist_timestamp(state[timestamp_key]).date() > day:
                        continue
                    encoded = _encode(event).encode()
                    digest.update(len(encoded).to_bytes(8, 'big'))
                    digest.update(encoded)
                    event_count += 1
                    if field == "entry":
                        entry = state
                    elif field == "mark":
                        mark = state
                    else:
                        exit_data = state
                if entry is None:
                    continue
                entries += entry["entry_timestamp_ist"][:10] == session_date
                if exit_data is not None:
                    closed += 1
                    in_day = exit_data["exit_timestamp_ist"][:10] == session_date
                    values = dict(realized=exit_data["net_pnl_inr"], realized_day=exit_data["net_pnl_inr"] if in_day else 0,
                        gross_day=exit_data["gross_pnl_inr"] if in_day else 0,
                        fees_day=exit_data["costs"]["charges_inr"] if in_day else 0,
                        fees=exit_data["costs"]["charges_inr"], slippage=exit_data["costs"]["slippage_inr"])
                else:
                    if mark is None:
                        _reject("MISSING_SESSION_MARK")
                    opened += 1
                    values = dict(unrealized=mark["unrealized_net_pnl_inr"], raw_losses=min(0, mark["unrealized_gross_pnl_inr"]),
                                  reserved=entry["initial_reserved_capital_inr"])
                for key, value in values.items():
                    totals[key] += Decimal(str(value))
            amount = {k: _money(v) for k,v in totals.items()}
            accounting = dict(realized_net_pnl_inr_lifetime=amount["realized"], realized_net_pnl_inr_session=amount["realized_day"],
                realized_gross_pnl_inr_session=amount["gross_day"], fees_paid_inr_session=amount["fees_day"],
                fees_paid_inr_lifetime=amount["fees"], slippage_paid_inr_lifetime=amount["slippage"],
                unrealized_net_pnl_inr=amount["unrealized"], reserved_capital_inr=amount["reserved"],
                equity_inr=_sum([self.config.starting_capital_inr, amount["realized"], amount["unrealized"]]),
                available_capital_inr=max(0, _sum([self.config.starting_capital_inr, amount["realized"], amount["raw_losses"], -amount["reserved"]])),
                open_positions=opened, closed_positions=closed, entries_in_session=entries)
            statement = dict(status="OK", account_id=self.config.account_id, config_hash=self.config.config_hash,
                provider=self.config.provider, source_data_mode=self.config.source_data_mode, execution_mode="SIMULATED",
                session_date=session_date, session_end_ist=format_ist_timestamp(end), accounting=accounting,
                eod_status="UNRESOLVED" if opened else "RECONCILED", historical_replay_allowed=False,
                readiness_receipt_issued=False, valuation="LAST_RECORDED_MARK_NOT_FRESH_ACCEPTANCE",
                calendar_authority="CONFIGURED_WEEKDAYS_AND_HOLIDAYS_ONLY", event_count=event_count,
                event_digest_sha256=digest.hexdigest(), financial_mutations=False)
            return dict(statement, statement_sha256=_hash(statement))
        except (KeyError, ValueError, TypeError, ArithmeticError, RecursionError):
            return dict(status="RECONCILIATION_REQUIRED", account_id=self.config.account_id,
                        session_date=session_date, accounting=None)

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
        if len(_encode(data).encode("utf-8")) > 65536:
            _reject("BOUNDED_CANDIDATE_REQUIRED")
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
            (_hash([self.config.account_id, key]), self.config.account_id, key, kind, position["position_id"], self._record(payload)))

    @staticmethod
    def _record(value):
        encoded = _encode(value)
        if len(encoded.encode("utf-8")) > 524288:
            _reject("BOUNDED_PAPER_RECORD_REQUIRED")
        return encoded

    def _save(self, conn, position):
        conn.execute("UPDATE paper_positions SET payload_json=? WHERE account_id=? AND position_id=?",
                     (self._record(position), self.config.account_id, position["position_id"]))

    def _mark_or_exit(self, conn, position, bar, key, command_hash, *, mark_only=False):
        sign = 1 if position["side"] == "LONG" else -1
        opening, stop, target = bar["open"], position["stop_loss"], position["target_price"]
        loss_touch = bar["low"] <= stop if sign == 1 else bar["high"] >= stop
        profit_touch = bar["high"] >= target if sign == 1 else bar["low"] <= target
        reason, exit_price = None, None
        if not mark_only and sign * opening <= sign * stop:
            reason, exit_price = "STOP_GAP", opening
        elif not mark_only and sign * opening >= sign * target:
            reason, exit_price = "TARGET_GAP_CAPPED", target
        elif not mark_only and loss_touch:
            reason, exit_price = "STOP_FIRST_COLLISION" if profit_touch else "STOP", stop
        elif not mark_only and profit_touch:
            reason, exit_price = "TARGET", target
        elif not mark_only and (parse_ist_timestamp(bar["timestamp"]) + timedelta(minutes=5)).time() >= time.fromisoformat(self.config.square_off_ist):
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

    def observe_candidate(self, candidate_id, supplied, source_scan_run_id):
        """Retain one strategy observation without reserving capital or filling."""
        from paper_triggers import strategy_observation_record, validate_strategy_history
        if self.config.fill_policy not in TRIGGER_FILL_POLICIES:
            _reject("STRATEGY_TRIGGER_POLICY_REQUIRED")
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM paper_candidate_decisions WHERE account_id=? AND candidate_id=?",
                               (self.config.account_id, candidate_id)).fetchone()
            decision = self._decode(row[0]) if row else None
            if not decision or decision.get("candidate_id") != candidate_id:
                _reject("PAPER_DECISION_NOT_ELIGIBLE")
            if decision["status"] != "QUEUED":
                return decision
            try:
                self._candidate(decision["candidate"])
                self._bar(supplied, decision["candidate"]["instrument_identity"], self._now())
                cache = {}
                _, records = validate_strategy_history(self.store, conn, decision, self.config, cache)
                if records and parse_ist_timestamp(supplied["timestamp"]) == parse_ist_timestamp(records[-1]["timestamp_ist"]):
                    replay = dict(decision, trigger_evaluations=records[:-1])
                    repeated = strategy_observation_record(self.store, conn, replay, supplied, source_scan_run_id,
                        self._now(), self.config, cache)
                    expected = dict(records[-1], observed_at_ist=repeated["observed_at_ist"])
                    if "evidence_record" in expected:
                        expected["evidence_record"] = dict(expected["evidence_record"], observed_at_ist=repeated["observed_at_ist"])
                    if repeated != expected:
                        _reject("PAPER_TRIGGER_OBSERVATION_CONFLICT")
                    return decision
                if records and records[-1]["status"] != "WAITING":
                    _reject("PAPER_TRIGGER_HISTORY_AFTER_TERMINAL")
                record = strategy_observation_record(self.store, conn, decision, supplied, source_scan_run_id,
                    self._now(), self.config, cache)
            except (KeyError, TypeError, ValueError) as exc:
                if isinstance(exc, PaperPortfolioError):
                    raise
                _reject(str(exc) if isinstance(exc, ValueError) else "PAPER_TRIGGER_EVIDENCE_INVALID")
            decision["trigger_evaluations"].append(record)
            decision.update(trigger_timestamp_ist=record["trigger_timestamp_ist"], reason_code=record["reason_code"],
                status="REJECTED" if record["status"] == "INVALIDATED" else "QUEUED")
            decision["history"] = (decision["history"] + [dict(status=decision["status"],
                reason_code=record["reason_code"], observed_at_ist=record["observed_at_ist"])])[-32:]
            conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE account_id=? AND candidate_id=?",
                         (self._record(decision), self.config.account_id, candidate_id))
            return decision

    def enter(self, candidate, completed_next_bar, event_key, *, candidate_decision_id=None,
              source_scan_run_id=None, entry_guard=None):
        """Atomically reserve and simulate the next completed bar, including exits."""
        data, side = self._candidate(candidate)
        now = self._now()
        command_hash = _hash(dict(operation="ENTRY", candidate=data, bar=completed_next_bar))
        with self.store.paper_transaction(write=True) as conn:
            retry = self._event_retry(conn, event_key, command_hash)
            if retry:
                if self.config.fill_policy in TRIGGER_FILL_POLICIES and self._reconciliation(conn)["status"] != "OK":
                    _reject("RECONCILIATION_REQUIRED")
                return retry
            decision = None
            triggered_policy = self.config.fill_policy in TRIGGER_FILL_POLICIES
            if triggered_policy and candidate_decision_id is None:
                _reject("PAPER_TRIGGER_DECISION_REQUIRED")
            if candidate_decision_id is not None and not triggered_policy:
                _reject("LEGACY_AUTOMATIC_TRIGGER_UNSUPPORTED")
            if candidate_decision_id is not None:
                row = conn.execute("SELECT payload_json FROM paper_candidate_decisions WHERE account_id=? AND candidate_id=?",
                                   (self.config.account_id, candidate_decision_id)).fetchone()
                decision = json.loads(row[0]) if row else None
                if (not decision or candidate_decision_id != event_key or decision.get("candidate_id") != candidate_decision_id or decision["status"] != "QUEUED"
                        or decision["candidate_hash"] != _hash(data) or decision["config_hash"] != self.config.config_hash):
                    _reject("PAPER_DECISION_NOT_ELIGIBLE")
            trigger_evidence = None
            if triggered_policy:
                from paper_triggers import strategy_entry_evidence
                try:
                    trigger_evidence = strategy_entry_evidence(self.store, conn, decision, completed_next_bar,
                        source_scan_run_id, now, self.config)
                except (KeyError, TypeError, ValueError) as exc:
                    _reject(str(exc) if isinstance(exc, ValueError) else "PAPER_TRIGGER_EVIDENCE_INVALID")
                if not callable(entry_guard):
                    _reject("CURRENT_SCANNER_GUARD_REQUIRED")
                entry_guard()
            bar = self._bar(completed_next_bar, data["instrument_identity"], now)
            signal_time = parse_ist_timestamp(data["timestamp"])
            fill_time = parse_ist_timestamp(bar["timestamp"])
            if ((fill_time <= signal_time if triggered_policy else fill_time != signal_time + timedelta(minutes=5))
                    or fill_time.date() != signal_time.date()
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
            forward_close = self.config.fill_policy in (FORWARD_FILL_POLICY, *TRIGGER_FILL_POLICIES)
            if not forward_close and any(p["status"] == "CLOSED" and
                    parse_ist_timestamp(p["exit_timestamp_ist"]) + timedelta(minutes=5) > fill_time
                    for p in self._positions(conn)):
                _reject("CAPITAL_RELEASE_AFTER_ASSUMED_FILL")
            opening = bar["close"] if forward_close else bar["open"]
            sign = 1 if side == "LONG" else -1
            if forward_close and ((bar["low"] <= data["invalidation_level"] or bar["high"] >= data["target_1"])
                    if side == "LONG" else (bar["high"] >= data["invalidation_level"] or bar["low"] <= data["target_1"])):
                _reject("SETUP_INVALIDATED_BEFORE_CLOSE_FILL")
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
                candidate=data, risk_decision=sizing,
                candidate_timestamp_ist=format_ist_timestamp(signal_time), entry_key=entry_key, side=side,
                raw_entry_price=opening, effective_entry_price=sizing["effective_entry_price"],
                quantity=sizing["quantity"], stop_loss=data["stop_loss"], target_price=data["target_1"],
                invalidation_level=data["invalidation_level"], entry_timestamp_ist=bar["timestamp"],
                fill_timestamp_ist=format_ist_timestamp(fill_time + timedelta(minutes=5) if forward_close else fill_time),
                estimated_stop_risk_inr=sizing["estimated_risk_inr"], initial_reserved_capital_inr=sizing["capital_required_inr"],
                status="OPEN", reserved_capital_inr=sizing["capital_required_inr"], fill_policy=self.config.fill_policy,
                entry_provenance=bar)
            if trigger_evidence is not None:
                position.update(trigger_evidence)
            conn.execute("INSERT INTO paper_positions(position_id,account_id,entry_key,payload_json) VALUES(?,?,?,?)",
                (position["position_id"], self.config.account_id, entry_key, self._record(position)))
            immutable = {key: value for key, value in position.items() if key not in ("status", "reserved_capital_inr")}
            # Entry and first-bar result commit together; no capital-only orphan.
            result = self._mark_or_exit(conn, position, bar, event_key + ":fill", command_hash, mark_only=forward_close)
            if triggered_policy:
                self._bar(completed_next_bar, data["instrument_identity"], self._now())
                entry_guard()  # A late degradation rolls back position, mark and reservation.
            self._event(conn, event_key, "ENTRY", position,
                dict(command_hash=command_hash, entry=immutable, result=result))
            if decision is not None:
                transition = dict(status="FILLED", reason_code="PAPER_RISK_APPROVED", observed_at_ist=format_ist_timestamp(now))
                decision.update(transition, position_id=position["position_id"])
                decision["history"] = (decision["history"] + [transition])[-32:]
                conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE account_id=? AND candidate_id=?",
                             (_encode(decision), self.config.account_id, candidate_decision_id))
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
            if self._reconciliation(conn)["status"] != "OK":
                _reject("RECONCILIATION_REQUIRED")
            row = conn.execute("SELECT payload_json FROM paper_positions WHERE account_id=? AND position_id=?",
                               (self.config.account_id, position_id)).fetchone()
            position = self._decode(row[0]) if row else None
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
