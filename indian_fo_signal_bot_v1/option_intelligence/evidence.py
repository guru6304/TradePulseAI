"""Shared bounded arithmetic and explicitly scoped supplied-input evidence."""
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
STATES = ("VERIFIED", "UNAVAILABLE", "STALE", "INVALID", "NOT_ESTABLISHED")


class CheckError(ValueError):
    def __init__(self, state, code):
        self.state, self.code = state, code
        super().__init__(code)


def require(condition, state, code):
    if not condition:
        raise CheckError(state, code)


def number(value):
    require(value is not None, "UNAVAILABLE", "NUMERIC_INPUT_UNAVAILABLE")
    require(not isinstance(value, bool) and isinstance(value, (int, float, str, Decimal)),
            "INVALID", "INVALID_NUMERIC_INPUT")
    require(not isinstance(value, str) or (len(value) <= 64 and bool(re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value))),
        "INVALID", "INVALID_NUMERIC_INPUT")
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise CheckError("INVALID", "INVALID_NUMERIC_INPUT") from None
    require(result.is_finite(), "INVALID", "NONFINITE_NUMERIC_INPUT")
    require(result.copy_abs() <= Decimal(2**53-1) and
            (result == 0 or result.copy_abs() >= Decimal("1e-18")),
            "INVALID", "NUMERIC_INPUT_OUT_OF_BOUNDS")
    return Decimal(0) if result == 0 else result


def timestamp(value):
    if value is None:
        raise CheckError("UNAVAILABLE", "TIMESTAMP_UNAVAILABLE")
    if isinstance(value, str):
        require(bool(re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value)), "INVALID", "OFFSET_TIMESTAMP_REQUIRED")
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise CheckError("INVALID", "INVALID_TIMESTAMP") from None
    require(isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None, "INVALID", "OFFSET_TIMESTAMP_REQUIRED")
    try:
        value.astimezone(IST)
    except (ValueError, OverflowError):
        raise CheckError("INVALID", "INVALID_TIMESTAMP") from None
    return value


def day(value):
    if value is None:
        raise CheckError("UNAVAILABLE", "DATE_UNAVAILABLE")
    if type(value) is date:
        return value
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)),
            "INVALID", "CANONICAL_DATE_REQUIRED")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CheckError("INVALID", "INVALID_DATE") from None


def text(value, code="TEXT_UNAVAILABLE"):
    require(value is not None, "UNAVAILABLE", code)
    require(isinstance(value, str) and 0 < len(value) <= 512 and value == value.strip()
            and all(ord(c) >= 32 and ord(c) != 127 for c in value), "INVALID", "INVALID_TEXT")
    return value


def ceil_tick(value, tick):
    value, tick = number(value), number(tick)
    require(tick > 0, "INVALID", "INVALID_TICK")
    return (value/tick).to_integral_value(rounding=ROUND_CEILING)*tick


def floor_tick(value, tick):
    value, tick = number(value), number(tick)
    require(tick > 0, "INVALID", "INVALID_TICK")
    return (value/tick).to_integral_value(rounding=ROUND_FLOOR)*tick


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key:json_value(item) for key,item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("Unsupported research receipt value")


def digest(value):
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Evidence:
    state: str
    reason_codes: tuple[str, ...]
    value: object = None
    scope: str = "SUPPLIED_INPUT_VALIDATION_ONLY"

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError("Unsupported evidence state")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))

    def to_dict(self):
        return json_value(self)
