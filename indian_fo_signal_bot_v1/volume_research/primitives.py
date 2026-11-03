"""Pure, offline Stage 1 volume features. No source authority is conferred here.

The calendar, dated identity/membership and action ledger are explicit research
inputs. Missing records are unavailable, never an implied holiday or zero volume.
Raw bars remain as traded; split-comparable prices are used only inside ATR.
"""
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from statistics import median
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
FIVE_MINUTES = timedelta(minutes=5)
WINDOWS = (5, 10, 15, 20, 30, 50, 60)


class ValidationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def D(value):
    if value is None:
        raise ValidationError("MISSING_NUMERIC_INPUT")
    if isinstance(value, bool):
        raise ValidationError("INVALID_NUMERIC_INPUT")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("INVALID_NUMERIC_INPUT") from None
    if not result.is_finite():
        raise ValidationError("NONFINITE_NUMERIC_INPUT")
    return result


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("AWARE_TIMESTAMP_REQUIRED")
    return value


def ceil_tick(value, tick):
    value, tick = D(value), D(tick)
    if tick <= 0:
        raise ValidationError("INVALID_TICK")
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def floor_tick(value, tick):
    value, tick = D(value), D(tick)
    if tick <= 0:
        raise ValidationError("INVALID_TICK")
    return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


@dataclass(frozen=True)
class Bar:
    candle_id: str
    instrument_id: str
    source: str
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    observed_at: datetime
    received_at: datetime
    finalized_at: datetime
    available_at: datetime
    complete: bool = True
    revision: int = 0
    volume_unit: str = "SHARES"
    schema_version: str = "tradepulse.volume-research.bar.v1"

    def __post_init__(self):
        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, D(getattr(self, name)))

    @property
    def session_date(self):
        return aware(self.start).astimezone(IST).date()

    @property
    def decision_ready_at(self):
        return max(aware(v) for v in (self.end, self.observed_at, self.received_at,
                                      self.finalized_at, self.available_at))


@dataclass(frozen=True)
class Session:
    session_date: date
    open_at: datetime
    close_at: datetime
    phase: str = "NORMAL"

    @property
    def slot_count(self):
        return int((aware(self.close_at) - aware(self.open_at)) / FIVE_MINUTES)


def normal_session(day):
    """Construct a declared session, without guessing whether the day traded."""
    return Session(day, datetime.combine(day, time(9, 15), IST),
                   datetime.combine(day, time(15, 30), IST))


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    provider: str
    symbol: str
    source: str
    source_revision: str
    valid_from: date
    valid_to: date
    tick: Decimal
    available_at: datetime
    exchange: str = "NSE"
    segment: str = "NSE_EQUITY_INTRADAY"
    series: str = "EQ"
    instrument_type: str = "EQ"

    def __post_init__(self):
        object.__setattr__(self, "tick", D(self.tick))


@dataclass(frozen=True)
class Membership:
    instrument_id: str
    valid_from: date
    valid_to: date
    available_at: datetime
    universe: str = "NIFTY200"
    ordinary_equity: bool = True


@dataclass(frozen=True)
class CorporateAction:
    instrument_id: str
    effective_date: date
    share_multiplier: Decimal
    available_at: datetime

    def __post_init__(self):
        object.__setattr__(self, "share_multiplier", D(self.share_multiplier))


@dataclass(frozen=True)
class VolumeProfile:
    instrument: Instrument
    sessions: tuple
    members: tuple
    history: tuple
    actions: tuple
    actions_complete_through: date

    def __post_init__(self):
        for name in ("sessions", "members", "history", "actions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class SeasonalRVOL:
    value: Decimal
    baseline: Decimal
    window: int
    session_dates: tuple


@dataclass(frozen=True)
class SetupContext:
    current: Bar
    prior: tuple
    rvol: SeasonalRVOL
    atr: Decimal
    tick: Decimal
    decision_at: datetime
    profile: VolumeProfile

    def __post_init__(self):
        object.__setattr__(self, "prior", tuple(self.prior))
        object.__setattr__(self, "atr", D(self.atr))
        object.__setattr__(self, "tick", D(self.tick))


def _calendar(profile):
    dates = tuple(s.session_date for s in profile.sessions)
    if not dates or dates != tuple(sorted(set(dates))):
        raise ValidationError("INVALID_SESSION_CALENDAR")
    result = {}
    for session in profile.sessions:
        opening, closing = aware(session.open_at), aware(session.close_at)
        if session.phase not in ("NORMAL", "SPECIAL", "CLOSED"):
            raise ValidationError("INVALID_SESSION_PHASE")
        if session.phase == "NORMAL":
            expected = normal_session(session.session_date)
            if opening != expected.open_at or closing != expected.close_at or session.slot_count != 75:
                raise ValidationError("INVALID_NORMAL_SESSION")
        elif session.phase == "SPECIAL" and closing <= opening:
            raise ValidationError("INVALID_SPECIAL_SESSION")
        result[session.session_date] = session
    return result


def _geometry(bar):
    if not all(isinstance(getattr(bar, n), Decimal) and getattr(bar, n).is_finite()
               for n in ("open", "high", "low", "close", "volume")):
        raise ValidationError("INVALID_NUMERIC_INPUT")
    if not (0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
        raise ValidationError("INVALID_OHLC")
    if bar.volume < 0:
        raise ValidationError("INVALID_VOLUME")
    if bar.volume_unit != "SHARES":
        raise ValidationError("INVALID_VOLUME_UNIT")


def validate_bar(bar, session, decision_at):
    decision_at = aware(decision_at)
    for field in ("start", "end", "observed_at", "received_at", "finalized_at", "available_at"):
        aware(getattr(bar, field))
    if not all(isinstance(v, str) and v.strip()
               for v in (bar.candle_id, bar.instrument_id, bar.source, bar.schema_version)):
        raise ValidationError("SOURCE_IDENTITY_UNAVAILABLE")
    if type(bar.complete) is not bool or not bar.complete:
        raise ValidationError("INCOMPLETE_BAR")
    if type(bar.revision) is not int or bar.revision < 0:
        raise ValidationError("INVALID_CORRECTION_REVISION")
    _geometry(bar)
    if session is None:
        raise ValidationError("SESSION_CALENDAR_UNAVAILABLE")
    if session.phase != "NORMAL":
        raise ValidationError("SPECIAL_SESSION_UNSUPPORTED")
    expected = normal_session(session.session_date)
    if session.open_at != expected.open_at or session.close_at != expected.close_at:
        raise ValidationError("INVALID_NORMAL_SESSION")
    if (bar.session_date != session.session_date or bar.end - bar.start != FIVE_MINUTES
            or bar.start < session.open_at or bar.end > session.close_at
            or (bar.start - session.open_at) % FIVE_MINUTES != timedelta(0)):
        raise ValidationError("INVALID_FIVE_MINUTE_SLOT")
    if (bar.observed_at < bar.end or bar.received_at < bar.observed_at
            or bar.finalized_at < bar.end or bar.available_at < max(bar.received_at, bar.finalized_at)):
        raise ValidationError("INVALID_SOURCE_CLOCK_ORDER")
    if decision_at < bar.decision_ready_at:
        raise ValidationError("BAR_NOT_AVAILABLE")
    return bar


def _identity(bar, profile, decision_at):
    instrument = profile.instrument
    if (not all(isinstance(v, str) and v.strip() for v in
                (instrument.instrument_id, instrument.provider, instrument.symbol,
                 instrument.source, instrument.source_revision))
            or (instrument.exchange, instrument.segment, instrument.series, instrument.instrument_type)
            != ("NSE", "NSE_EQUITY_INTRADAY", "EQ", "EQ")):
        raise ValidationError("ORDINARY_EQUITY_IDENTITY_REQUIRED")
    if (bar.instrument_id != instrument.instrument_id or bar.source != instrument.source):
        raise ValidationError("SOURCE_IDENTITY_MISMATCH")
    if not instrument.valid_from <= bar.session_date <= instrument.valid_to:
        raise ValidationError("DATED_IDENTITY_UNAVAILABLE")
    if aware(instrument.available_at) > aware(decision_at):
        raise ValidationError("IDENTITY_NOT_AVAILABLE")
    if instrument.tick <= 0:
        raise ValidationError("INVALID_TICK")
    if any(getattr(bar, n) % instrument.tick for n in ("open", "high", "low", "close")):
        raise ValidationError("PRICE_OFF_TICK")


def _membership(current, profile, decision_at):
    matches = [m for m in profile.members if m.instrument_id == current.instrument_id
               and m.valid_from <= current.session_date <= m.valid_to]
    if len(matches) != 1:
        raise ValidationError("POINT_IN_TIME_UNIVERSE_UNAVAILABLE")
    member = matches[0]
    if member.universe != "NIFTY200" or member.ordinary_equity is not True:
        raise ValidationError("INELIGIBLE_UNIVERSE_MEMBER")
    if aware(member.available_at) > aware(decision_at):
        raise ValidationError("MEMBERSHIP_NOT_AVAILABLE")


def _actions(profile, current, decision_at):
    if profile.actions_complete_through < current.session_date:
        raise ValidationError("CORPORATE_ACTION_HISTORY_UNAVAILABLE")
    relevant, seen = [], set()
    for action in profile.actions:
        if action.instrument_id != current.instrument_id:
            raise ValidationError("CORPORATE_ACTION_IDENTITY_MISMATCH")
        if action.effective_date in seen:
            raise ValidationError("DUPLICATE_CORPORATE_ACTION")
        seen.add(action.effective_date)
        if action.share_multiplier <= 0:
            raise ValidationError("INVALID_SHARE_MULTIPLIER")
        if action.effective_date <= current.session_date:
            if aware(action.available_at) > aware(decision_at):
                raise ValidationError("CORPORATE_ACTION_NOT_AVAILABLE")
            relevant.append(action)
    return tuple(relevant)


def _multiplier(bar, actions):
    factor = D(1)
    for action in actions:
        if bar.session_date < action.effective_date:
            factor *= action.share_multiplier
    return factor


def seasonal_rvol(current, profile, decision_at, n=20):
    if type(n) is not int or n not in WINDOWS:
        raise ValidationError("UNSUPPORTED_RVOL_WINDOW")
    calendar = _calendar(profile)
    validate_bar(current, calendar.get(current.session_date), decision_at)
    _identity(current, profile, decision_at)
    actions = _actions(profile, current, decision_at)
    previous = tuple(s.session_date for s in profile.sessions
                     if s.session_date < current.session_date and s.phase == "NORMAL")
    if len(previous) < n:
        raise ValidationError("INSUFFICIENT_HISTORY")
    expected = previous[-n:]
    slot = current.start.astimezone(IST).timetz().replace(tzinfo=None)
    matching = {}
    for bar in profile.history:
        if aware(bar.start).astimezone(IST).timetz().replace(tzinfo=None) != slot:
            continue
        if bar.session_date >= current.session_date:
            raise ValidationError("NONPRIOR_HISTORY")
        if bar.session_date not in expected:
            continue
        if bar.session_date in matching:
            raise ValidationError("DUPLICATE_HISTORY_SLOT")
        validate_bar(bar, calendar.get(bar.session_date), decision_at)
        _identity(bar, profile, decision_at)
        matching[bar.session_date] = bar.volume * _multiplier(bar, actions)
    if set(matching) != set(expected):
        raise ValidationError("INSUFFICIENT_HISTORY")
    baseline = median(tuple(matching[day] for day in expected))
    if baseline <= 0:
        raise ValidationError("ZERO_BASELINE")
    return SeasonalRVOL(current.volume / baseline, baseline, n, expected)


def comparison_rvol(current, profile, decision_at):
    """Matched development evaluation dates; even N5 requires 60 valid slots."""
    seasonal_rvol(current, profile, decision_at, 60)
    return tuple(seasonal_rvol(current, profile, decision_at, n) for n in WINDOWS)


def clv(bar):
    _geometry(bar)
    if bar.high == bar.low:
        raise ValidationError("ZERO_CANDLE_RANGE")
    return (bar.close - bar.low) / (bar.high - bar.low)


def atr14(prior, decision_at):
    """Wilder RMA: seed first 14 TRs, then recurse, overnight gaps INCLUDED.

    The first bar supplies previous close only; >=15 completed observations are
    therefore required. Caller selects a declared chronological feature window.
    """
    prior = tuple(prior)
    if len(prior) < 15:
        raise ValidationError("ATR_INSUFFICIENT_HISTORY")
    for bar in prior:
        _geometry(bar)
        if bar.complete is not True or aware(decision_at) < bar.decision_ready_at:
            raise ValidationError("ATR_BAR_UNAVAILABLE")
    if any(a.start >= b.start or a.end > b.start for a, b in zip(prior, prior[1:])):
        raise ValidationError("NONMONOTONIC_HISTORY")
    ranges = tuple(max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                   for a, b in zip(prior, prior[1:]))
    result = sum(ranges[:14], D(0)) / D(14)
    for value in ranges[14:]:
        result = (D(13) * result + value) / D(14)
    if result <= 0:
        raise ValidationError("ZERO_ATR")
    return result


def _next_slot(bar, calendar):
    session = calendar[bar.session_date]
    if bar.end < session.close_at:
        return bar.end
    following = [s for day, s in calendar.items() if day > bar.session_date and s.phase != "CLOSED"]
    if not following:
        raise ValidationError("SESSION_CALENDAR_UNAVAILABLE")
    if following[0].phase != "NORMAL":
        raise ValidationError("SPECIAL_SESSION_UNSUPPORTED")
    return following[0].open_at


def prepare_setup(current, prior, profile, decision_at):
    decision_at = aware(decision_at)
    if decision_at.astimezone(IST).date() != current.session_date:
        raise ValidationError("DECISION_SESSION_MISMATCH")
    prior = tuple(prior)
    calendar = _calendar(profile)
    validate_bar(current, calendar.get(current.session_date), decision_at)
    _identity(current, profile, decision_at)
    _membership(current, profile, decision_at)
    actions = _actions(profile, current, decision_at)
    if len(prior) < 15:
        raise ValidationError("ATR_INSUFFICIENT_HISTORY")
    for bar in prior:
        validate_bar(bar, calendar.get(bar.session_date), decision_at)
        _identity(bar, profile, decision_at)
    chain = prior + (current,)
    if len({b.candle_id for b in chain}) != len(chain):
        raise ValidationError("DUPLICATE_CANDLE_ID")
    for earlier, later in zip(chain, chain[1:]):
        if earlier.start >= later.start:
            raise ValidationError("NONMONOTONIC_HISTORY")
        if _next_slot(earlier, calendar) != later.start:
            raise ValidationError("MISSING_HISTORY_SLOT")
        if earlier.observed_at > later.observed_at or earlier.available_at > later.available_at:
            raise ValidationError("NONMONOTONIC_SOURCE_CLOCK")
    if any(prior[-6].session_date < action.effective_date <= current.session_date for action in actions):
        raise ValidationError("CORPORATE_ACTION_IN_STRUCTURE_WINDOW")
    comparable = tuple(replace(bar, open=bar.open / _multiplier(bar, actions),
                               high=bar.high / _multiplier(bar, actions),
                               low=bar.low / _multiplier(bar, actions),
                               close=bar.close / _multiplier(bar, actions),
                               volume=bar.volume * _multiplier(bar, actions)) for bar in prior)
    return SetupContext(current, prior, seasonal_rvol(current, profile, decision_at),
                        atr14(comparable, decision_at), profile.instrument.tick, decision_at, profile)


def validate_setup(context):
    expected = prepare_setup(context.current, context.prior, context.profile, context.decision_at)
    if context != expected:
        raise ValidationError("FEATURE_CONTEXT_MISMATCH")
    return context


def validate_future(bar, context, decision_at):
    """Validate a future observation, without deciding trigger eligibility."""
    calendar = _calendar(context.profile)
    validate_bar(bar, calendar.get(bar.session_date), decision_at)
    _identity(bar, context.profile, decision_at)
    if bar.session_date != context.current.session_date:
        raise ValidationError("SESSION_CHANGED")
    return bar


@dataclass(frozen=True)
class SectorStrength:
    status: str
    value: Decimal | None
    reason_code: str


def sector_relative_strength(stock_now, stock_before, sector_now=None, sector_before=None,
                             decision_at=None):
    """Aligned 15m log return residual; missing/misaligned sector stays soft."""
    if sector_now is None or sector_before is None:
        return SectorStrength("MISSING", None, "SECTOR_UNAVAILABLE")
    values = (stock_now, stock_before, sector_now, sector_before)
    try:
        if decision_at is None or any(b.decision_ready_at > aware(decision_at) for b in values):
            return SectorStrength("MISSING", None, "SECTOR_NOT_AVAILABLE")
        if (stock_now.instrument_id != stock_before.instrument_id
                or stock_now.source != stock_before.source
                or sector_now.instrument_id != sector_before.instrument_id
                or sector_now.source != sector_before.source
                or stock_now.instrument_id == sector_now.instrument_id):
            return SectorStrength("MISSING", None, "SECTOR_IDENTITY_MISMATCH")
        if (stock_now.end != sector_now.end or stock_before.end != sector_before.end
                or stock_now.end - stock_before.end != timedelta(minutes=15)):
            return SectorStrength("MISSING", None, "SECTOR_TIMESTAMPS_MISALIGNED")
        for bar in values:
            _geometry(bar)
            if bar.complete is not True:
                return SectorStrength("MISSING", None, "SECTOR_INCOMPLETE_BAR")
            if aware(bar.end) - aware(bar.start) != FIVE_MINUTES:
                return SectorStrength("MISSING", None, "SECTOR_INVALID_INTERVAL")
    except ValidationError:
        return SectorStrength("MISSING", None, "SECTOR_INVALID_INPUT")
    value = (stock_now.close / stock_before.close).ln() - (sector_now.close / sector_before.close).ln()
    return SectorStrength("AVAILABLE", value, "ALIGNED_15M_LOG_RESIDUAL")
