"""Pure validation of explicitly unqualified asset/index observation windows.

This module performs no I/O and loads no application configuration. It neither
authenticates provenance nor creates a cash-candle lineage or research admission.
Weekday/session checks describe the expected clock shape, not a holiday calendar.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re


SCHEMA = "tradepulse.benchmark-observation-window.v1"
IST = timezone(timedelta(hours=5, minutes=30))
INTERVAL = timedelta(minutes=5)
PROVENANCE = frozenset(("SYNTHETIC_FIXTURE", "UNVERIFIED_CAPTURE"))
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_INPUT_NODES = 20000
MAX_STRING_CHARACTERS = 65536
MAX_TOTAL_TEXT_CHARACTERS = 1024 * 1024
MAX_AGE_SECONDS = 86400
_CLOCK_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class BenchmarkObservationError(ValueError):
    """A rejected window with a stable, non-promoting reason code."""

    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _reject(code):
    raise BenchmarkObservationError(code)


def _clock(value, code):
    if not isinstance(value, str) or len(value) > 32 or not _CLOCK_PATTERN.fullmatch(value):
        _reject(code)
    try:
        clock = datetime.fromisoformat(value)
        if clock.tzinfo is None or clock.utcoffset() is None:
            _reject(code)
        return clock.astimezone(IST)
    except (ValueError, TypeError, OverflowError):
        _reject(code)


def _json_hash(value):
    # Reject key coercion and non-JSON containers before computing a canonical
    # whole-envelope hash; no caller-provided digest is trusted.
    visited, total_text = 0, 0

    def validate(item, depth=0):
        nonlocal visited, total_text
        visited += 1
        if visited > MAX_INPUT_NODES:
            _reject("INPUT_NODE_LIMIT_EXCEEDED")
        if depth > 32:
            _reject("INPUT_NOT_CANONICAL_JSON")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _reject("INPUT_NOT_CANONICAL_JSON")
                validate(key, depth + 1)
                validate(child, depth + 1)
        elif type(item) is list:
            for child in item:
                validate(child, depth + 1)
        elif type(item) is str:
            total_text += len(item)
            if len(item) > MAX_STRING_CHARACTERS or total_text > MAX_TOTAL_TEXT_CHARACTERS:
                _reject("INPUT_TEXT_LIMIT_EXCEEDED")
        elif type(item) not in (str, int, float, bool, type(None)):
            _reject("INPUT_NOT_CANONICAL_JSON")
    validate(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        _reject("INPUT_NOT_CANONICAL_JSON")
    if len(raw) > MAX_INPUT_BYTES:
        _reject("INPUT_BYTES_LIMIT_EXCEEDED")
    return hashlib.sha256(raw).hexdigest()


def _text(value):
    return isinstance(value, str) and len(value) <= MAX_STRING_CHARACTERS and bool(value.strip())


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _window(envelope, expected_role, decision, max_age):
    if type(envelope) is not dict:
        _reject("OBSERVATION_ENVELOPE_REQUIRED")
    if envelope.get("role") != expected_role:
        _reject("OBSERVATION_ROLE_MISMATCH")
    identity = envelope.get("identity")
    if type(identity) is not dict or any(not _text(identity.get(key)) for key in
            ("symbol", "identifier", "provider", "source_revision")):
        _reject("EXPLICIT_INSTRUMENT_IDENTITY_REQUIRED")
    expected_type = "EQ" if expected_role == "asset" else "INDEX_SPOT"
    if identity.get("instrument_type") != expected_type:
        _reject("ASSET_EQ_REQUIRED" if expected_role == "asset" else "BENCHMARK_INDEX_SPOT_REQUIRED")
    if type(envelope.get("interval_minutes")) is not int or envelope["interval_minutes"] != 5:
        _reject("FIVE_MINUTE_INTERVAL_REQUIRED")
    expected_unit = "INR" if expected_role == "asset" else "INDEX_POINTS"
    if envelope.get("price_unit") != expected_unit:
        _reject("OBSERVATION_PRICE_UNIT_MISMATCH")
    if envelope.get("adjustment") != "UNADJUSTED":
        _reject("UNADJUSTED_OBSERVATIONS_REQUIRED")
    if type(envelope.get("provenance")) is not str or envelope["provenance"] not in PROVENANCE:
        _reject("EXPLICIT_UNQUALIFIED_PROVENANCE_REQUIRED")
    source = envelope.get("source_reference")
    if not (_text(source) or type(source) is dict and bool(source)):
        _reject("SOURCE_REFERENCE_REQUIRED")
    session = envelope.get("session_date")
    if not isinstance(session, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", session):
        _reject("SESSION_DATE_REQUIRED")
    try:
        session_day = date.fromisoformat(session)
    except ValueError:
        _reject("SESSION_DATE_REQUIRED")
    if session_day.weekday() > 4:
        _reject("WEEKDAY_SESSION_REQUIRED")
    if decision.date() != session_day:
        _reject("DECISION_SESSION_MISMATCH")
    bars = envelope.get("bars")
    if type(bars) is not list or not 2 <= len(bars) <= 375:
        _reject("OBSERVATION_WINDOW_SIZE_INVALID")
    start = datetime.combine(session_day, time(9, 15), tzinfo=IST)
    finish = datetime.combine(session_day, time(15, 30), tzinfo=IST)
    stamps, available, closes = [], [], []
    for bar in bars:
        if type(bar) is not dict:
            _reject("CANDLE_OBJECT_REQUIRED")
        if bar.get("is_complete") is not True:
            _reject("EXPLICIT_COMPLETED_CANDLE_REQUIRED")
        stamp = _clock(bar.get("timestamp"), "AWARE_CANDLE_TIMESTAMP_REQUIRED")
        if stamp.date() != session_day or stamp < start or stamp + INTERVAL > finish:
            _reject("CANDLE_OUTSIDE_SESSION")
        if stamp.second or stamp.microsecond or (stamp - start) % INTERVAL != timedelta(0):
            _reject("CANDLE_NOT_FIVE_MINUTE_ALIGNED")
        if stamps and stamp != stamps[-1] + INTERVAL:
            _reject("CANDLE_WINDOW_NOT_CONTIGUOUS_CHRONOLOGICAL")
        end = stamp + INTERVAL
        if end > decision:
            _reject("CANDLE_NOT_COMPLETED_AT_DECISION")
        publication = _clock(bar.get("available_at"), "AWARE_AVAILABILITY_TIMESTAMP_REQUIRED")
        if publication < end:
            _reject("CANDLE_AVAILABLE_BEFORE_COMPLETION")
        if publication > decision:
            _reject("CANDLE_NOT_AVAILABLE_AT_DECISION")
        prices = [bar.get(field) for field in ("open", "high", "low", "close")]
        if any(not _finite(value) or value <= 0 for value in prices):
            _reject("CANDLE_PRICE_INVALID")
        opening, high, low, close = prices
        if low > high or not low <= opening <= high or not low <= close <= high:
            _reject("CANDLE_OHLC_GEOMETRY_INVALID")
        if "volume" not in bar:
            if expected_role == "asset":
                _reject("ASSET_VOLUME_REQUIRED")
        else:
            volume = bar["volume"]
            if not _finite(volume) or volume < 0 or int(volume) != volume:
                _reject("CANDLE_VOLUME_INVALID")
        stamps.append(stamp)
        available.append(publication)
        closes.append(close)
    age = (decision - (stamps[-1] + INTERVAL)).total_seconds()
    if age > max_age:
        _reject("LATEST_COMPLETED_CANDLE_STALE")
    input_hash = _json_hash(envelope)
    try:
        return_pct = (closes[-1] / closes[0] - 1) * 100
    except (OverflowError, ZeroDivisionError):
        _reject("DESCRIPTIVE_RETURN_NONFINITE")
    if not math.isfinite(return_pct):
        _reject("DESCRIPTIVE_RETURN_NONFINITE")
    return dict(identity=deepcopy(identity), role=expected_role, price_unit=expected_unit,
        source_reference=deepcopy(source), provenance=envelope["provenance"], input_sha256=input_hash,
        first_close=closes[0], last_close=closes[-1], return_pct=return_pct,
        available_at=[clock.isoformat() for clock in available]), stamps, age


def align_benchmark_windows(asset: dict, benchmark: dict, *, decision_at: str, max_age_seconds: int) -> dict:
    """Validate exact equal windows and describe first-close to last-close change.

    Candles require ``is_complete=True`` and offset-aware ``timestamp`` and
    ``available_at`` values. Asset volume is mandatory; index volume may be
    omitted but must be valid when present. Source references are nonempty text
    or JSON objects. Equal instants with different UTC offsets align normally.
    No overlap trimming, sorting, deduplication, fill or interpolation occurs.
    """
    decision = _clock(decision_at, "AWARE_DECISION_TIMESTAMP_REQUIRED")
    if type(max_age_seconds) is not int or max_age_seconds < 0:
        _reject("NONNEGATIVE_INTEGER_MAX_AGE_REQUIRED")
    if max_age_seconds > MAX_AGE_SECONDS:
        _reject("MAX_AGE_SECONDS_EXCEEDS_SESSION_BOUND")
    left, asset_stamps, age = _window(asset, "asset", decision, max_age_seconds)
    right, index_stamps, _ = _window(benchmark, "benchmark", decision, max_age_seconds)
    a, b = left["identity"], right["identity"]
    if (a["symbol"].strip().casefold() == b["symbol"].strip().casefold()
            or (a["provider"].strip().casefold(), a["identifier"].strip()) ==
               (b["provider"].strip().casefold(), b["identifier"].strip())):
        _reject("DISTINCT_ASSET_AND_BENCHMARK_REQUIRED")
    if asset_stamps != index_stamps:
        _reject("EXACT_EQUAL_CANDLE_WINDOWS_REQUIRED")
    relative = left["return_pct"] - right["return_pct"]
    if not math.isfinite(relative):
        _reject("DESCRIPTIVE_RETURN_NONFINITE")
    synthetic = left["provenance"] == right["provenance"] == "SYNTHETIC_FIXTURE"
    return dict(schema_version=SCHEMA, actionable=False, eligible=False, empirical_acceptance=False,
        factor_status="SYNTHETIC_MECHANICS_ONLY" if synthetic else "UNQUALIFIED_SOURCE",
        decision_at=decision.isoformat(), session_date=asset["session_date"], interval_minutes=5,
        adjustment="UNADJUSTED", bar_count=len(asset_stamps),
        window=dict(start=asset_stamps[0].isoformat(), end=(asset_stamps[-1] + INTERVAL).isoformat(),
            first_close_at=(asset_stamps[0] + INTERVAL).isoformat(),
            last_close_at=(asset_stamps[-1] + INTERVAL).isoformat()),
        alignment=dict(policy="EXACT_CONTIGUOUS_COMPLETED_WINDOW_V1",
            candle_timestamps=[stamp.isoformat() for stamp in asset_stamps],
            latest_end_age_seconds=age, max_age_seconds=max_age_seconds),
        asset=left, benchmark=right, relative_return_percentage_points=relative,
        limitations=["SOURCE_AUTHORITY_NOT_ESTABLISHED", "RESEARCH_ADMISSION_NOT_ESTABLISHED",
            "NO_SECTOR_CONSTITUENT_CLAIM", "NO_CASH_LINEAGE_REUSE", "NO_EMPIRICAL_EDGE_CLAIM",
            "WEEKDAY_CLOCK_SHAPE_ONLY_NO_HOLIDAY_CALENDAR_AUTHORITY"])
