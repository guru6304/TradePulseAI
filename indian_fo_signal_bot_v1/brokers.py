import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import random
import re
import unicodedata
import struct
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
from functools import wraps
from config import BotConfig
from instrument_identity import (IdentityValidationError, canonical_symbol, spot_identity, bind_candles,
                                 check_echo, positive_integer, digest, option_contract, check_chain_metadata, INDICES, EQUITIES)
from strategies import (
    IST,
    NSE_OPEN_TIME,
    NSE_CLOSE_TIME,
    aggregate_intraday_candles,
    format_ist_timestamp,
    parse_ist_timestamp,
    validate_candles,
)
from storage import (
    PersistenceError,
    PersistenceValidationError,
    count_trading_sessions_between,
    is_closing_session_timestamp,
    is_nse_trading_day,
    resolve_effective_trading_session_date,
    resolve_prior_trading_session_date,
)

SIMULATED_BROKER_KEYS = ("paper_sim", "simulated", "sim")
LIVE_BROKER_KEYS = ("angelone", "dhan", "upstox")
INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY")


class BrokerDataError(RuntimeError):
    """Raised when a broker adapter encounters invalid configuration, authentication failure, or malformed market data."""


class BrokerIdentityError(BrokerDataError):
    """Structured identity rejection, independent of candle freshness."""
    error_category = "INVALID_INSTRUMENT_IDENTITY"

    def __init__(self, rejection):
        self.rejection = rejection
        super().__init__(rejection["reason"])


def identity_checked(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except IdentityValidationError as exc:
        raise BrokerIdentityError(exc.rejection) from exc


class UnsupportedBrokerCapabilityError(BrokerDataError):
    """
    Raised when a requested market-data capability is not supported by the broker's
    official public API or lacks required external contract/baseline inputs,
    as distinct from a transient network, rate-limit, or authentication failure.
    """


def _is_placeholder_secret(val: Optional[str]) -> bool:
    if not val or not str(val).strip():
        return True
    lower = str(val).strip().lower()
    return lower.startswith("your_") or "placeholder" in lower or "example" in lower


def _redact_secrets(text: str, secrets: List[Optional[str]]) -> str:
    """Redacts any non-empty secret values from error or log strings."""
    out = str(text or "")
    for sec in secrets:
        if sec and isinstance(sec, str):
            s = sec.strip()
            if len(s) >= 3 and not _is_placeholder_secret(s):
                out = out.replace(s, "[REDACTED]")
    return out


def generate_totp(base32_secret: str, interval: int = 30, for_time: Optional[float] = None) -> str:
    """RFC 6238 TOTP generator for unattended Angel One SmartAPI login (zero external dependencies)."""
    if _is_placeholder_secret(base32_secret):
        raise ValueError("Invalid or placeholder TOTP secret.")
    clean = base32_secret.strip().replace(" ", "").upper()
    padding = (8 - len(clean) % 8) % 8
    try:
        key = base64.b32decode(clean + "=" * padding, casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("TOTP secret is not valid Base32.") from exc
    if not key:
        raise ValueError("TOTP secret decoded to empty key.")
    ts = time.time() if for_time is None else float(for_time)
    counter = int(ts) // interval
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


def resolve_nse_session_dates(
    ref_dt: datetime,
    warmup_sessions: int = 3,
    configured_holidays: Optional[List[str]] = None,
) -> Tuple[List[date], date]:
    """
    Derives the current trading session date and prior `warmup_sessions` trading dates
    from `ref_dt` in Asia/Kolkata:
    - If `ref_dt.date()` falls on a weekend (Saturday=5, Sunday=6) or a configured NSE holiday,
      rolls back to the most recent NSE trading day.
    - Preceding warm-up dates step backward skipping weekends and configured holidays,
      returned in chronological order.
    """
    ist_dt = parse_ist_timestamp(ref_dt)
    session_day = resolve_effective_trading_session_date(ist_dt.date(), configured_holidays)

    warmup_days: List[date] = []
    cursor = session_day - timedelta(days=1)
    while len(warmup_days) < max(0, int(warmup_sessions)):
        if is_nse_trading_day(cursor, configured_holidays):
            warmup_days.append(cursor)
        cursor -= timedelta(days=1)
    warmup_days.reverse()
    return warmup_days, session_day


class CandleFreshnessError(BrokerDataError):
    """Structured candle rejection, separate from transport/authentication failure."""
    def __init__(self, freshness):
        self.freshness = freshness
        self.error_category = "STALE_MARKET_DATA" if freshness["status"] == "STALE" else freshness["status"]
        super().__init__(freshness["reason"])


def candle_session_context(now_ist, configured_holidays=None, session_start_ist="09:15", session_end_ist="15:30"):
    """Configured weekday calendar only; session close is exclusive for new signals."""
    ref = parse_ist_timestamp(now_ist)
    start = datetime.strptime(session_start_ist, "%H:%M").time()
    end = datetime.strptime(session_end_ist, "%H:%M").time()
    if start >= end:
        raise ValueError("Session start must precede session end.")
    day = ref.date()
    if day.weekday() >= 5:
        state = "weekend"
        expected = resolve_effective_trading_session_date(day, configured_holidays)
    elif day.isoformat() in (configured_holidays or []):
        state = "configured_holiday:" + day.isoformat()
        expected = resolve_effective_trading_session_date(day, configured_holidays)
    elif ref.time().replace(tzinfo=None) < start:
        state = "before_session_open"
        expected = resolve_prior_trading_session_date(day, configured_holidays)
    elif ref.time().replace(tzinfo=None) >= end:
        state = "after_session_close"
        expected = day
    else:
        state, expected = "within_session", day
    return ref, start, end, state, expected


def _explicit_candle_timestamp(value, normalized_ist=False):
    """Raw live timestamps require an offset or UTC epoch; normalized IST is explicit."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing or invalid timestamp.")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-naive live datetime.")
        return parse_ist_timestamp(value)
    if isinstance(value, (int, float)):
        return parse_ist_timestamp(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing or invalid timestamp.")
    raw = value.strip()
    if normalized_ist:
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        except ValueError:
            pass
    try:
        number = float(raw)
    except ValueError:
        number = None
    if number is not None:
        return parse_ist_timestamp(number)
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-naive live timestamp has no explicit convention.")
    return dt.astimezone(IST)


def assess_live_candle_batch(
    candles, interval_min=5, now_ist=None, configured_holidays=None,
    session_start_ist="09:15", session_end_ist="15:30", max_delay_seconds=60.0,
    future_skew_seconds=5.0, *, provider="unknown", symbol="UNKNOWN", context="REFERENCE",
    normalized_ist=False, reverse_chronological=False, max_staleness_minutes=None,
):
    """One live/reference policy. Never called by historical ingestion or replay.

    Raw wire input is strict. Project-normalized IST strings require an explicit
    convention at the caller boundary. Incomplete bars remain displayable but cannot
    establish freshness. No silent sorting/deduplication or synthetic promotion.
    """
    provider = str(provider or "unknown").strip().lower()
    result = dict(provider=provider, symbol=symbol, interval_min=interval_min, context=context,
                  status="NOT_CHECKED", is_fresh=False, live_signal_allowed=False,
                  reference_usable=False, batch_valid=False, completed_candles=0,
                  latest_candle_timestamp_ist=None, latest_completed_timestamp_ist=None,
                  wall_clock_age_minutes=None, session_adjusted_lag_minutes=None,
                  calendar_policy="WEEKDAYS_AND_CONFIGURED_HOLIDAYS_ONLY")
    normalized = []
    def reject(code, reason):
        result.update(status=code, reason_code=code, reason=reason)
        return normalized, result
    if isinstance(interval_min, bool) or not isinstance(interval_min, int) or interval_min <= 0:
        return reject("INVALID_INTERVAL", "Candle interval must be a positive integer.")
    for value in (max_delay_seconds, future_skew_seconds):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return reject("INVALID_POLICY", "Candle delay/skew must be finite and non-negative.")
    if context not in ("REFERENCE", "SCANNER", "DIAGNOSTIC"):
        return reject("INVALID_CONTEXT", "Live candle validation requires an explicit supported context.")
    if context == "SCANNER" and provider not in LIVE_BROKER_KEYS:
        return reject("INVALID_PROVENANCE", "An unknown/synthetic provider cannot authorize live signals.")
    try:
        ref = _explicit_candle_timestamp(now_ist if now_ist is not None else datetime.now(IST))
        ref, start, end, state, expected = candle_session_context(
            ref, configured_holidays, session_start_ist, session_end_ist)
    except (ValueError, TypeError, OverflowError, OSError):
        return reject("INVALID_REFERENCE_TIME", "Invalid reference clock or configured session.")
    result.update(session_state=state, expected_session_date=expected.isoformat(),
                  evaluated_at_ist=format_ist_timestamp(ref), max_delay_seconds=max_delay_seconds,
                  future_skew_seconds=future_skew_seconds)
    if not isinstance(candles, list) or not candles:
        return reject("EMPTY", "Candle series is empty or missing.")
    parsed = []
    for row in candles:
        if not isinstance(row, dict):
            return reject("MALFORMED_CANDLE", "Candle row must be an object.")
        if row.get("is_simulated") or str(row.get("data_mode", "LIVE")).upper() != "LIVE":
            return reject("INVALID_PROVENANCE", "Synthetic or unknown provenance cannot establish live freshness.")
        if "interval_min" in row and (isinstance(row["interval_min"], bool) or row["interval_min"] != interval_min):
            return reject("INVALID_INTERVAL", "Candle interval metadata disagrees with requested interval.")
        if row.get("is_complete") is not None and not isinstance(row["is_complete"], bool):
            return reject("INVALID_COMPLETION", "Candle completion flag must be boolean.")
        if row.get("timestamp_timezone") not in (None, "Asia/Kolkata"):
            return reject("INVALID_TIMESTAMP", "Unknown normalized candle timestamp convention.")
        try:
            ts = _explicit_candle_timestamp(row.get("timestamp"), normalized_ist)
        except (ValueError, TypeError, OverflowError, OSError):
            return reject("INVALID_TIMESTAMP", "Missing, malformed or timezone-naive live timestamp.")
        if ts > ref + timedelta(seconds=future_skew_seconds):
            return reject("FUTURE_TIMESTAMP", "Live candle timestamp exceeds the allowed clock skew.")
        session_open = datetime.combine(ts.date(), start, tzinfo=IST)
        session_close = datetime.combine(ts.date(), end, tzinfo=IST)
        elapsed = (ts - session_open).total_seconds()
        if (not is_nse_trading_day(ts.date(), configured_holidays) or not session_open <= ts < session_close
                or elapsed % (interval_min * 60) != 0):
            return reject("INVALID_CANDLE_GRID", "Candle is outside the configured trading session or interval grid.")
        parsed.append((ts, min(ts + timedelta(minutes=interval_min), session_close), row))
    if reverse_chronological:
        parsed.reverse()
    for previous, current in zip(parsed, parsed[1:]):
        if current[0] == previous[0]:
            return reject("DUPLICATE_TIMESTAMP", "Duplicate candle timestamps are not accepted.")
        if current[0] < previous[0]:
            return reject("OUT_OF_ORDER", "Candle timestamps are not strictly chronological.")
        if current[0].date() == previous[0].date() and current[0] != previous[0] + timedelta(minutes=interval_min):
            return reject("CANDLE_GAP", "Missing intraday candle interval in the returned batch.")
    try:
        normalized = validate_candles([dict(row, timestamp=ts) for ts, _, row in parsed],
                                      deduplicate=False, sort_chronologically=False, interval_min=interval_min,
                                      now=ref, default_is_simulated=False)
    except (ValueError, TypeError, OverflowError):
        return reject("MALFORMED_CANDLE", "Candle OHLCV validation failed.")
    completed = []
    for bar, (ts, closed, row) in zip(normalized, parsed):
        bar.update(timestamp_timezone="Asia/Kolkata", interval_min=interval_min, data_mode="LIVE",
                   is_simulated=False, is_complete=bool(row.get("is_complete") is not False and closed <= ref))
        if bar["is_complete"]:
            completed.append((bar, closed))
    result.update(batch_valid=True, completed_candles=len(completed),
                  incomplete_candles=len(normalized)-len(completed),
                  latest_candle_timestamp_ist=normalized[-1]["timestamp"])
    if not completed:
        return reject("NO_COMPLETED_CANDLES", "No completed candle is available for freshness evidence.")
    latest, closed = completed[-1]
    result.update(latest_completed_timestamp_ist=latest["timestamp"],
                  wall_clock_age_minutes=round((ref - parse_ist_timestamp(latest["timestamp"])).total_seconds()/60, 4))
    max_lag = interval_min * 60 + max_delay_seconds
    if max_staleness_minutes is not None:
        if (isinstance(max_staleness_minutes, bool) or not isinstance(max_staleness_minutes, (int, float))
                or not math.isfinite(max_staleness_minutes) or max_staleness_minutes <= 0):
            return reject("INVALID_POLICY", "Explicit maximum candle age must be finite and positive.")
        # Legacy age is measured from bar open; it may tighten, never relax, defaults.
        max_lag = min(max_lag, max(0, max_staleness_minutes * 60 - interval_min * 60))
    reference = ref if state == "within_session" else datetime.combine(expected, end, tzinfo=IST)
    lag = (reference - closed).total_seconds()
    result.update(reference_timestamp_ist=format_ist_timestamp(reference),
                  session_adjusted_lag_minutes=round(lag/60, 4), max_close_lag_seconds=max_lag,
                  max_staleness_minutes=(max_lag+interval_min*60)/60)
    if state == "within_session":
        if closed.date() != expected or lag > max_lag:
            return reject("STALE", "Latest completed live candle is stale for the current session.")
        result.update(is_fresh=True, live_signal_allowed=provider in LIVE_BROKER_KEYS, status="FRESH_IN_SESSION")
    else:
        # Reference use requires the actual closing bar, not an arbitrary old intraday bar.
        if closed.date() != expected or closed != reference:
            return reject("STALE", "Latest completed candle is stale relative to the most recent session close.")
        result.update(is_fresh=True, reference_usable=True, status="FRESH_PRIOR_SESSION_CLOSE")
        if context == "SCANNER":
            return reject("MARKET_CLOSED", "Closed-session reference data cannot authorize a new live signal.")
    result.update(reason_code=result["status"], reason="Completed candle satisfies the configured freshness policy.")
    return normalized, result


def evaluate_candle_freshness(candles, interval_min=5, now_ist=None, configured_holidays=None,
                              session_start_ist="09:15", session_end_ist="15:30",
                              max_staleness_minutes=None, max_delay_seconds=60.0, future_skew_seconds=5.0,
                              *, provider="unknown", symbol="UNKNOWN", context="REFERENCE"):
    """Assess the explicitly project-normalized IST candle contract (diagnostics/receipts)."""
    return assess_live_candle_batch(
        candles, interval_min, now_ist, configured_holidays, session_start_ist, session_end_ist,
        max_delay_seconds, future_skew_seconds, normalized_ist=True,
        provider=provider, symbol=symbol, context=context,
        max_staleness_minutes=max_staleness_minutes)[1]


def enforce_live_candle_batch(adapter, candles, symbol_meta, interval_min, provider, *,
                              normalized_ist=False, reverse_chronological=False,
                              context="REFERENCE", max_staleness_minutes=None):
    cfg = adapter.config
    adapter.last_candle_response_at_ist = format_ist_timestamp(adapter.clock())
    normalized, report = assess_live_candle_batch(
        candles, interval_min, adapter.clock(), cfg.configured_holidays,
        cfg.session_start_ist, cfg.session_end_ist,
        cfg.live_candle_max_delay_seconds, cfg.live_candle_future_skew_seconds,
        provider=provider, symbol=symbol_meta["symbol"], context=context,
        normalized_ist=normalized_ist, reverse_chronological=reverse_chronological,
        max_staleness_minutes=max_staleness_minutes)
    adapter.last_candle_freshness = report
    adapter.last_candle_timestamp_ist = report["latest_completed_timestamp_ist"]
    if not report["is_fresh"] or context == "SCANNER" and not report["live_signal_allowed"]:
        error = CandleFreshnessError(report)
        adapter.last_error_category = error.error_category
        adapter.last_error_message = str(error)
        raise error
    adapter.last_error_category = "NONE"
    adapter.last_error_message = None
    adapter.last_market_data_at_ist = report["evaluated_at_ist"]
    return normalized


def validate_symbol_meta(symbol_meta: Dict[str, Any], broker_key: str, master=None) -> Dict[str, Any]:
    """Resolve exact provider-specific identity before transport; never infer from token shape."""
    bkey = str(broker_key or "").strip().lower()
    if bkey in SIMULATED_BROKER_KEYS:
        if not isinstance(symbol_meta, dict):
            raise BrokerDataError("symbol_meta must be a dictionary.")
        raw_symbol = symbol_meta.get("symbol")
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise BrokerDataError("symbol_meta is missing a valid 'symbol' identifier.")
        symbol = raw_symbol.strip().upper()
        if symbol not in SimulatedNSEAdapter.BASE_PRICES and "base_price" not in symbol_meta:
            raise BrokerDataError(f"Unknown symbol '{symbol}' for SimulatedNSEAdapter.")
        return {"symbol": symbol, "is_index": symbol in INDEX_SYMBOLS}
    identity = identity_checked(spot_identity, symbol_meta, bkey, master)
    result = dict(symbol=identity["symbol"], is_index=identity["is_index"],
                  exchange=identity["exchange"], instrument_identity=identity)
    if bkey == "angelone":
        result["angel_token"] = identity["identifier"]
    elif bkey == "dhan":
        result.update(security_id=identity["identifier"],
                      exchange_segment="IDX_I" if identity["is_index"] else "NSE_EQ",
                      instrument="INDEX" if identity["is_index"] else "EQUITY")
    else:
        result["upstox_key"] = identity["identifier"]
    return result


def _parse_and_select_expiry(expiry_strings: List[Any], session_date: date, provider_name: str) -> str:
    """
    Validates a list of YYYY-MM-DD expiry strings and returns the nearest expiry >= session_date.
    """
    if not isinstance(expiry_strings, list) or not expiry_strings:
        raise BrokerDataError(f"{provider_name} returned an empty expiry list.")
    valid_dates: List[Tuple[date, str]] = []
    for item in expiry_strings:
        if not isinstance(item, str) or not item.strip():
            continue
        s = item.strip()
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError as exc:
            raise BrokerDataError(f"{provider_name} returned malformed expiry date '{s}'.") from exc
        if d >= session_date:
            valid_dates.append((d, s))
    if not valid_dates:
        raise BrokerDataError(f"{provider_name} returned no active expiry dates on or after {session_date.isoformat()}.")
    valid_dates.sort(key=lambda pair: pair[0])
    return valid_dates[0][1]


def _normalize_angel_expiry_str(raw_expiry: str) -> Tuple[str, str]:
    """
    Normalizes an Angel One expiry date string (either 'DDMMMYYYY' like '22OCT2026' or '28OCT25',
    or ISO 'YYYY-MM-DD' like '2026-10-22') into a pair `(iso_yyyy_mm_dd, angel_ddmmmyyyy)`.
    """
    if not isinstance(raw_expiry, str) or not raw_expiry.strip():
        raise BrokerDataError("Empty Angel One expiry date string.")
    s = raw_expiry.strip().upper()
    for fmt in ("%Y-%m-%d", "%d%b%Y", "%d-%b-%Y", "%d%b%y"):
        try:
            dt = datetime.strptime(s, fmt).date()
            return dt.strftime("%Y-%m-%d"), dt.strftime("%d%b%Y").upper()
        except ValueError:
            continue
    raise BrokerDataError(f"Malformed Angel One expiry date '{raw_expiry}'. Expected 'YYYY-MM-DD' or 'DDMMMYYYY'.")


def _normalize_angel_scrip_strike(raw_strike: Any, index_symbol: str = "NIFTY") -> int:
    """
    Normalizes a strike value from Angel One OpenAPIScripMaster.json or optionGreek response:
    - In OpenAPIScripMaster.json, NFO OPTIDX strikes are stored in paise (`strike_rupees * 100.0`,
      e.g., `"2480000.000000"` for NIFTY 24800 or `"5240000.000000"` for BANKNIFTY 52400).
    - In optionGreek responses, `strikePrice` is in rupees (`"24800.000000"`).
    """
    if isinstance(raw_strike, bool) or raw_strike is None:
        raise BrokerDataError(f"Invalid Angel One option strike: {raw_strike!r}")
    try:
        val = float(raw_strike)
    except (TypeError, ValueError) as exc:
        raise BrokerDataError(f"Non-numeric Angel One option strike: {raw_strike!r}") from exc
    if not math.isfinite(val) or val <= 0:
        raise BrokerDataError(f"Non-positive Angel One option strike: {raw_strike!r}")

    # OpenAPIScripMaster.json encodes NIFTY/BANKNIFTY strikes multiplied by 100 (e.g. 2480000.0 for 24800)
    if val >= 200000.0:
        val = val / 100.0
    if not val.is_integer():
        raise BrokerDataError("Fractional option strikes are unsupported; strike metadata cannot be rounded.")
    return int(val)


class BaseBrokerAdapter:
    name: str = "base"
    is_simulated: bool = False

    def get_intraday_candles(
        self,
        symbol_meta: Dict[str, Any],
        interval_min: int = 5,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_option_chain(
        self,
        index_symbol: str,
        bias: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


def _safe_angel_market_read(function):
    """Keep untrusted response/parser causes out of public market-data errors."""
    @wraps(function)
    def guarded(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except BrokerDataError as exc:
            self.last_market_data_at_ist = None
            clean = self._sanitize(str(exc))
            exc.args = (clean,)
            if hasattr(exc, "rejection"):
                exc.rejection = dict(exc.rejection, reason=self._sanitize(exc.rejection["reason"]))
            if isinstance(exc, BrokerIdentityError):
                self.last_error_category = exc.error_category
                # This local identity rejection made no HTTP request. Earlier
                # provider failures must not be attached to the new operation.
                self.last_http_status = None
            elif self.last_error_category == "NONE":
                self.last_error_category = "INVALID_RESPONSE"
            self.last_error_message = clean
            exc.error_category = self.last_error_category
            raise exc from None
        except Exception:
            self.last_market_data_at_ist = None
            message = self._record_adapter_error("INVALID_RESPONSE", "Angel One market-data response could not be validated.")
            raise BrokerDataError(message) from None
    return guarded


class AngelOneSmartAPIAdapter(BaseBrokerAdapter):
    """
    Phase 2A Official Read-Only Angel One SmartAPI Adapter:
    - Authentication:
      * Login: POST https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword
      * Token Refresh: POST https://apiconnect.angelone.in/rest/auth/angelbroking/jwt/v1/generateTokens
      * Session Profile: GET https://apiconnect.angelone.in/rest/secure/angelbroking/user/v1/getProfile
    - Read-Only Market Data:
      * Quotes (LTP / OHLC / FULL): POST https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/
      * Intraday / Historical Candles: POST https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData
      * Option Greeks & IV: POST https://apiconnect.angelone.in/rest/secure/angelbroking/marketData/v1/optionGreek
      * Put-Call Ratio Summary: GET https://apiconnect.angelone.in/rest/secure/angelbroking/marketData/v1/putCallRatio
    - Strict Read-Only Enforcement:
      * Order placement, modification, cancellation, and GTT rule mutation are strictly prohibited.
    """
    name = "Angel One SmartAPI"
    is_simulated = False
    BASE_URL = "https://apiconnect.angelone.in"
    MAX_QUOTE_TOKENS_PER_REQUEST = 50
    SUPPORTED_QUOTE_MODES = ("LTP", "OHLC", "FULL")
    SUPPORTED_INTERVALS = {
        1: "ONE_MINUTE",
        3: "THREE_MINUTE",
        5: "FIVE_MINUTE",
        10: "TEN_MINUTE",
        15: "FIFTEEN_MINUTE",
        30: "THIRTY_MINUTE",
        60: "ONE_HOUR",
    }
    TOKEN_EXPIRY_ERROR_CODES = {"AG8001", "AG8002", "AB1010"}
    AUTH_REJECTED_ERROR_CODES = {"AB1000", "AB1007", "AB1050", "AG8004"}
    SERVER_TEMP_ERROR_CODES = {"AB1004", "AB2001"}
    FORBIDDEN_ORDER_PATH_PREFIXES = (
        "/rest/secure/angelbroking/order/",
        "/rest/secure/angelbroking/gtt/",
    )
    READ_ONLY_ENDPOINTS = {
        ("GET", "/rest/secure/angelbroking/user/v1/getProfile"),
        ("POST", "/rest/secure/angelbroking/market/v1/quote/"),
        ("POST", "/rest/secure/angelbroking/historical/v1/getCandleData"),
        ("POST", "/rest/secure/angelbroking/marketData/v1/optionGreek"),
        ("GET", "/rest/secure/angelbroking/marketData/v1/putCallRatio"),
    }

    def __init__(
        self,
        config: BotConfig,
        clock: Optional[Callable[[], datetime]] = None,
        persistence_store: Optional[Any] = None,
    ):
        self.config = config
        self.clock = clock or (lambda: datetime.now(IST))
        self.persistence_store: Optional[Any] = persistence_store
        self.jwt_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.authenticated_at_ist: Optional[str] = None
        self.profile_verified_at_ist: Optional[str] = None
        self.last_market_data_at_ist: Optional[str] = None
        self.last_quote_timestamp_ist: Optional[str] = None
        self.last_candle_timestamp_ist: Optional[str] = None
        self.last_candle_freshness: Optional[Dict[str, Any]] = None
        self.last_error_category: str = "NONE"
        self.last_error_message: Optional[str] = None
        self._last_request_wall: float = 0.0
        self._authorized_reads = 0
        self._session_redactions = []
        self._last_totp_code = None
        self.session_recovery_enabled = True  # Narrow acceptance commands explicitly disable retry/login recovery.
        self.last_http_status = None

        # Scrip Master registries, metadata & prior OI baselines for NFO Option Chain assembly
        self._scrip_master_equities: Dict[str, Dict[str, Any]] = {}
        self._scrip_master_indices: Dict[str, Dict[str, Any]] = {}
        self._scrip_master_options: List[Dict[str, Any]] = []
        self._scrip_master_meta: Dict[str, Any] = {
            "status": "NOT_CONFIGURED",
            "configured_path": None,
            "loaded_path": None,
            "loaded_mtime": None,
            "file_size_bytes": None,
            "loaded_at_ist": None,
            "equities_loaded": 0,
            "indices_loaded": 0,
            "index_options_loaded": 0,
            "malformed_rows_rejected": 0,
            "last_error": None,
        }
        self._prior_oi_baselines: Dict[Tuple[str, str], Dict[int, Dict[str, int]]] = {}
        self._prior_oi_baseline_meta: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.fetch_option_greeks_in_chain: bool = False

        self._init_scrip_master_from_config()
        if self.persistence_store is not None:
            self.restore_all_baselines_from_store()

    def _init_scrip_master_from_config(self) -> None:
        scrip_path = str(getattr(self.config, "angel_scrip_master_path", "") or "").strip()
        if not scrip_path:
            self._scrip_master_meta["status"] = "NOT_CONFIGURED"
            self._scrip_master_meta["configured_path"] = None
            return
        self._scrip_master_meta["configured_path"] = os.path.basename(scrip_path)
        if not os.path.isfile(scrip_path):
            self._scrip_master_meta["status"] = "FILE_MISSING"
            self._scrip_master_meta["last_error"] = (
                f"Configured ANGEL_SCRIP_MASTER_PATH does not exist: {os.path.basename(scrip_path)}"
            )
            return
        try:
            self.load_scrip_master(scrip_path)
        except Exception as exc:
            self._scrip_master_meta["status"] = "CORRUPT_ERROR"
            self._scrip_master_meta["last_error"] = self._sanitize(str(exc))

    def attach_persistence_store(self, store: Optional[Any]) -> None:
        self.persistence_store = store
        if store is not None:
            self.restore_all_baselines_from_store()

    def _secret_values(self) -> List[Optional[str]]:
        return [
            self.config.angel_api_key,
            self.config.angel_pin,
            self.config.angel_totp_secret,
            self.jwt_token,
            self.refresh_token,
            self.feed_token,
            self.config.angel_client_code,
            self._last_totp_code,
            *self._session_redactions,
        ]

    def _sanitize(self, message: str) -> str:
        try:
            clean = sanitize_broker_message(self.config, message)
            variants = [variant for value in self._secret_values() if value for variant in
                        (str(value), urllib.parse.quote(str(value), safe=""), urllib.parse.quote_plus(str(value)))]
            clean = _redact_secrets(clean, variants)
            return sanitize_upstox_error_detail(self.config, {"message": clean}).get(
                "provider_error_message", "Angel One request failed; safe detail is unavailable.")
        except Exception:
            return "Angel One request failed; safe detail is unavailable."

    def _invalidate_session(self, clear_refresh=False):
        values = [v for v in (self.jwt_token, self.refresh_token, self.feed_token) if v]
        if values:
            self._session_redactions = list(dict.fromkeys(self._session_redactions + values))[-12:]
        self.jwt_token = None
        if clear_refresh:
            self.refresh_token = None
        self.feed_token = None
        self.authenticated_at_ist = None
        self.profile_verified_at_ist = None
        self.last_market_data_at_ist = None
        self.last_quote_timestamp_ist = None
        self.last_candle_timestamp_ist = None
        self.last_candle_freshness = None

    @staticmethod
    def _close_http_error(error):
        try:
            error.close()
        except Exception:
            # Preserve the safe original HTTP failure even if cleanup fails.
            pass

    @staticmethod
    def _read_response_bytes(response):
        content = response.read(8 * 1024 * 1024 + 1)
        if not isinstance(content, bytes) or len(content) > 8 * 1024 * 1024:
            raise BrokerDataError("Angel One response exceeded the supported size or encoding.")
        return content

    @staticmethod
    def _decode_response(raw_bytes):
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate response field.")
                result[key] = value
            return result
        return json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=unique_fields)

    def _record_adapter_error(self, category: str, message: str) -> str:
        clean_msg = self._sanitize(message)
        self.last_error_category = str(category or "NETWORK_API_FAILURE").strip().upper()
        self.last_error_message = clean_msg
        return clean_msg

    def is_connection_verified(self) -> bool:
        """
        Returns True ONLY when the adapter has BOTH an active authenticated session
        (`jwt_token` + `authenticated_at_ist`) AND a verified successful market-data fetch
        (`last_market_data_at_ist`), with no active error.
        Configured credentials or `authenticate()` / `get_profile()` alone NEVER satisfy this check.
        """
        return bool(
            self.jwt_token
            and self.authenticated_at_ist
            and self.last_market_data_at_ist
            and not self.last_error_message
        )

    @staticmethod
    def _normalize_bearer_token(raw_token: Any) -> str:
        if not isinstance(raw_token, str) or not raw_token.strip():
            return ""
        tok = raw_token.strip()
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        return tok

    def _validate_credentials(self) -> None:
        missing = [
            name
            for name, val in (
                ("ANGEL_API_KEY", self.config.angel_api_key),
                ("ANGEL_CLIENT_CODE", self.config.angel_client_code),
                ("ANGEL_PIN", self.config.angel_pin),
                ("ANGEL_TOTP_SECRET", self.config.angel_totp_secret),
            )
            if _is_placeholder_secret(val)
        ]
        if missing:
            msg = f"Angel One SmartAPI credentials are missing or set to placeholder values ({', '.join(missing)})."
            self._record_adapter_error("MISSING_CREDENTIALS", msg)
            raise BrokerDataError(msg)

    def _headers(self, include_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": str(self.config.angel_api_key or ""),
        }
        if include_auth and self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        return headers

    def _respect_rate_limit(self) -> None:
        min_interval = float(getattr(self.config, "angel_min_request_interval_seconds", 0.0) or 0.0)
        if min_interval > 0.0 and self._last_request_wall > 0.0:
            elapsed = time.monotonic() - self._last_request_wall
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_wall = time.monotonic()

    @staticmethod
    def _extract_error_code_and_message(raw: Dict[str, Any]) -> Tuple[str, str]:
        value = raw.get("errorcode") or raw.get("errorCode")
        code = value.strip().upper() if isinstance(value, str) else ""
        if not re.fullmatch(r"(?:AB|AG)[0-9]{4,8}", code):
            code = ""
        value = raw.get("message") or raw.get("emsg")
        msg = value.strip() if isinstance(value, str) else "Unknown SmartAPI error"
        return code, msg

    def _is_token_expired_response(self, raw: Dict[str, Any]) -> bool:
        code, msg = self._extract_error_code_and_message(raw)
        if code in self.TOKEN_EXPIRY_ERROR_CODES:
            return True
        msg_low = msg.lower()
        return any(tok in msg_low for tok in ("invalid token", "token expired", "session expired", "invalid session", "invalid jwt"))

    def _format_api_error(self, context: str, raw: Dict[str, Any]) -> str:
        code, msg = self._extract_error_code_and_message(raw)
        code_part = f" [{code}]" if code else ""
        if code in self.TOKEN_EXPIRY_ERROR_CODES:
            category = "session/token expired or invalid"
        elif code in self.AUTH_REJECTED_ERROR_CODES:
            category = "authentication/credential rejected"
        elif code in self.SERVER_TEMP_ERROR_CODES:
            category = "temporary Angel One server error"
        else:
            category = "API error"
        return self._sanitize(f"Angel One SmartAPI {context} failed ({category}{code_part}): {msg}")

    def authenticate(self) -> bool:
        """
        Authenticates with Angel One SmartAPI via official `loginByPassword` + RFC 6238 TOTP.
        Stores `jwt_token`, `refresh_token`, `feed_token`, and `authenticated_at_ist` ONLY after
        a verified successful response containing a non-empty `jwtToken`.
        """
        self.last_http_status = None
        self._invalidate_session(clear_refresh=True)
        self._validate_credentials()
        now_ist = parse_ist_timestamp(self.clock())
        try:
            totp_code = generate_totp(str(self.config.angel_totp_secret), for_time=now_ist.timestamp())
            self._last_totp_code = totp_code
        except ValueError as exc:
            self.jwt_token = None
            raise BrokerDataError(self._sanitize("Angel One TOTP generation failed.")) from None

        payload = json.dumps({
            "clientcode": str(self.config.angel_client_code).strip(),
            "password": str(self.config.angel_pin).strip(),
            "totp": totp_code,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
            data=payload,
            headers=self._headers(include_auth=False),
            method="POST",
        )
        timeout_sec = float(getattr(self.config, "angel_request_timeout_seconds", 8.0) or 8.0)
        self._respect_rate_limit()
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw_bytes = self._read_response_bytes(resp)
        except urllib.error.HTTPError as http_exc:
            code = http_exc.code
            self.last_http_status = code
            self._close_http_error(http_exc)
            self._invalidate_session(clear_refresh=True)
            category = {401: "AUTH_FAILURE", 403: "ACCESS_DENIED", 429: "RATE_LIMIT"}.get(code, "NETWORK_API_FAILURE")
            message = self._record_adapter_error(category,
                f"Angel One SmartAPI authentication failed with HTTP {code}.")
            raise BrokerDataError(message) from None
        except Exception as exc:
            self._invalidate_session(clear_refresh=True)
            raise BrokerDataError(self._record_adapter_error(
                "NETWORK_API_FAILURE", "Angel One SmartAPI authentication transport failed.")) from None

        try:
            data = self._decode_response(raw_bytes)
        except Exception as exc:
            self._invalidate_session(clear_refresh=True)
            raise BrokerDataError(self._record_adapter_error("INVALID_RESPONSE", "Angel One SmartAPI login returned malformed non-JSON response.")) from None

        if not isinstance(data, dict):
            self._invalidate_session(clear_refresh=True)
            raise BrokerDataError(self._record_adapter_error("INVALID_RESPONSE", "Angel One SmartAPI login response is not a JSON object."))

        token_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        jwt_tok = self._normalize_bearer_token(token_data.get("jwtToken"))
        if data.get("status") is True and jwt_tok:
            self.jwt_token = jwt_tok
            self.refresh_token = self._normalize_bearer_token(token_data.get("refreshToken")) or None
            self.feed_token = str(token_data.get("feedToken") or "").strip() or None
            self.authenticated_at_ist = now_ist.strftime("%Y-%m-%d %H:%M:%S")
            self.last_error_category = "NONE"
            self.last_error_message = None
            return True

        self._invalidate_session(clear_refresh=True)
        code, msg = self._extract_error_code_and_message(data)
        detail = f" [{code}] {msg}" if (code or msg != "Unknown SmartAPI error") else ""
        err_str = self._record_adapter_error("AUTH_FAILURE", f"Angel One SmartAPI login rejected by server.{detail}")
        raise BrokerDataError(err_str)

    def refresh_access_token(self) -> bool:
        """
        Refreshes the active JWT token using `POST /rest/auth/angelbroking/jwt/v1/generateTokens`.
        Raises BrokerDataError if `refresh_token` is unavailable or rejected by SmartAPI.
        """
        self._validate_credentials()
        if not self.refresh_token:
            raise BrokerDataError("Angel One SmartAPI refresh_token is not available; full authentication required.")

        payload = json.dumps({"refreshToken": self.refresh_token}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}/rest/auth/angelbroking/jwt/v1/generateTokens",
            data=payload,
            headers=self._headers(include_auth=True),
            method="POST",
        )
        timeout_sec = float(getattr(self.config, "angel_request_timeout_seconds", 8.0) or 8.0)
        self._respect_rate_limit()
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw_bytes = self._read_response_bytes(resp)
        except urllib.error.HTTPError as http_exc:
            code = http_exc.code
            self._close_http_error(http_exc)
            self._invalidate_session()
            raise BrokerDataError(self._record_adapter_error("SESSION_EXPIRED",
                f"Angel One SmartAPI token refresh failed with HTTP {code}.")) from None
        except Exception as exc:
            self._invalidate_session()
            raise BrokerDataError(
                self._sanitize(f"Angel One SmartAPI token refresh failed ({type(exc).__name__}).")
            ) from None

        try:
            data = self._decode_response(raw_bytes)
        except Exception as exc:
            self._invalidate_session()
            raise BrokerDataError("Angel One SmartAPI generateTokens returned malformed JSON.") from None

        token_data = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
        new_jwt = self._normalize_bearer_token(token_data.get("jwtToken"))
        if isinstance(data, dict) and data.get("status") is True and new_jwt:
            self.jwt_token = new_jwt
            self.refresh_token = self._normalize_bearer_token(token_data.get("refreshToken")) or self.refresh_token
            self.feed_token = str(token_data.get("feedToken") or "").strip() or self.feed_token
            self.authenticated_at_ist = parse_ist_timestamp(self.clock()).strftime("%Y-%m-%d %H:%M:%S")
            return True

        self._invalidate_session()
        raise BrokerDataError(self._format_api_error("token refresh", data if isinstance(data, dict) else {}))

    def _recover_session(self) -> None:
        """
        Attempts to recover an expired session once: tries `refresh_access_token()` if
        a `refresh_token` is present, falling back to a fresh `authenticate()` call.
        """
        self.jwt_token = None
        if self.refresh_token:
            try:
                self.refresh_access_token()
                return
            except BrokerDataError:
                self.refresh_token = None
        self.authenticate()

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        context: str = "request",
        allow_reauth_retry: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes a read-only JSON request against Angel One SmartAPI with:
        - Strict order-placement path blocking
        - Automatic initial login if `self.jwt_token` is not yet acquired
        - Single automatic token-refresh / re-login retry on `AG8001` / `AG8002` / `AB1010` / HTTP 401
        - Distinct rate-limit (429) and access-denied (403) errors and secret redaction
        """
        norm_path = "/" + str(path or "").lstrip("/")
        allow_reauth_retry = allow_reauth_retry and self.session_recovery_enabled
        self.last_http_status = None
        parsed = urllib.parse.urlsplit(norm_path)
        profile_query = (parsed.path == "/rest/secure/angelbroking/user/v1/getProfile"
                         and set(urllib.parse.parse_qs(parsed.query)) <= {"refreshToken"})
        if ((method.upper(), parsed.path) not in self.READ_ONLY_ENDPOINTS or parsed.fragment
                or (parsed.query and not profile_query)):
            raise BrokerDataError("Unsupported endpoints, orders and GTT mutations are strictly disabled in this read-only adapter.")

        if not self.jwt_token:
            self.authenticate()

        timeout_sec = float(getattr(self.config, "angel_request_timeout_seconds", 8.0) or 8.0)
        body_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            f"{self.BASE_URL}{norm_path}",
            data=body_bytes,
            headers=self._headers(include_auth=True),
            method=method.upper(),
        )
        self._respect_rate_limit()

        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw_bytes = self._read_response_bytes(resp)
        except urllib.error.HTTPError as http_exc:
            code = http_exc.code
            self.last_http_status = code
            self._close_http_error(http_exc)
            if code in (401, 403):
                self._invalidate_session()
            if code == 401 and allow_reauth_retry:
                self._recover_session()
                return self._request_json(
                    method=method,
                    path=norm_path,
                    payload=payload,
                    context=context,
                    allow_reauth_retry=False,
                )
            if code == 401:
                self.jwt_token = None
                err_str = self._record_adapter_error(
                    "SESSION_EXPIRED",
                    f"Angel One SmartAPI {context} failed with HTTP 401 (session expired or invalid).",
                )
                raise BrokerDataError(err_str) from None
            if code in (403, 429):
                err_str = self._record_adapter_error(
                    "ACCESS_DENIED" if code == 403 else "RATE_LIMIT",
                    f"Angel One SmartAPI {context} failed: {'access denied' if code == 403 else 'rate limit'} (HTTP {code}).",
                )
                raise BrokerDataError(err_str) from None
            err_str = self._record_adapter_error(
                "NETWORK_API_FAILURE",
                f"Angel One SmartAPI {context} failed with HTTP {code}.",
            )
            raise BrokerDataError(err_str) from None
        except Exception as exc:
            err_str = self._record_adapter_error(
                "NETWORK_API_FAILURE",
                f"Angel One SmartAPI {context} failed ({type(exc).__name__}).",
            )
            raise BrokerDataError(err_str) from None

        try:
            raw = self._decode_response(raw_bytes)
        except Exception as exc:
            err_str = self._record_adapter_error(
                "INVALID_RESPONSE",
                f"Angel One SmartAPI {context} returned malformed non-JSON response.",
            )
            raise BrokerDataError(err_str) from None

        if not isinstance(raw, dict):
            err_str = self._record_adapter_error(
                "INVALID_RESPONSE",
                f"Angel One SmartAPI {context} response is not a JSON object.",
            )
            raise BrokerDataError(err_str)

        if raw.get("status") is not True:
            code, _ = self._extract_error_code_and_message(raw)
            if self._is_token_expired_response(raw):
                if allow_reauth_retry:
                    self._recover_session()
                    return self._request_json(
                        method=method,
                        path=norm_path,
                        payload=payload,
                        context=context,
                        allow_reauth_retry=False,
                    )
                self._invalidate_session()
                err_str = self._record_adapter_error("SESSION_EXPIRED", self._format_api_error(context, raw))
                raise BrokerDataError(err_str)
            cat = "AUTH_FAILURE" if code in self.AUTH_REJECTED_ERROR_CODES else "NETWORK_API_FAILURE"
            if cat == "AUTH_FAILURE":
                self._invalidate_session()
            err_str = self._record_adapter_error(cat, self._format_api_error(context, raw))
            raise BrokerDataError(err_str)

        if parsed.path != "/rest/secure/angelbroking/user/v1/getProfile":
            self._authorized_reads += 1
        return raw

    def get_profile(self) -> Dict[str, Any]:
        """
        Retrieves the authenticated user's read-only profile via
        `GET /rest/secure/angelbroking/user/v1/getProfile` to verify live session validity.
        """
        query = f"?refreshToken={urllib.parse.quote(self.refresh_token)}" if self.refresh_token else ""
        raw = self._request_json(
            "GET",
            f"/rest/secure/angelbroking/user/v1/getProfile{query}",
            payload=None,
            context="getProfile",
        )
        data = raw.get("data")
        if not isinstance(data, dict) or not data.get("clientcode"):
            err_str = self._record_adapter_error("AUTH_FAILURE", "Angel One SmartAPI getProfile response missing 'clientcode'.")
            raise BrokerDataError(err_str)
        self.profile_verified_at_ist = parse_ist_timestamp(self.clock()).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "clientcode": str(data.get("clientcode")).strip(),
            "name": str(data.get("name") or "").strip(),
            "exchanges": list(data.get("exchanges") or []),
            "products": list(data.get("products") or []),
            "broker": self.name,
            "is_simulated": False,
            "data_mode": "LIVE",
        }

    # -------------------------------------------------------------------------
    # Step 3.1: Instrument & Scrip Master Resolution (Hardened in Phase 2B)
    # -------------------------------------------------------------------------
    def _parse_and_validate_scrip_master_records(
        self,
        records: Any,
        require_index_options: bool = False,
        strict: bool = False,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], List[Dict[str, Any]], int]:
        if not isinstance(records, list) or not records:
            raise BrokerDataError("Angel One Scrip Master payload must be a non-empty JSON list of instrument objects.")

        master_revision = digest(records)
        eq_map: Dict[str, Dict[str, Any]] = {}
        idx_map: Dict[str, Dict[str, Any]] = {}
        opt_list: List[Dict[str, Any]] = []
        seen_opt_keys: Dict[Tuple[str, str, int, str], str] = {}
        seen_opt_tokens: Dict[str, Tuple[str, str, int, str]] = {}
        malformed_rows = 0

        for row in records:
            if not isinstance(row, dict):
                malformed_rows += 1
                continue
            token = str(row.get("token") or "").strip()
            symbol = str(row.get("symbol") or "").strip().upper()
            name = str(row.get("name") or "").strip().upper()
            exch_seg = str(row.get("exch_seg") or "").strip().upper()
            inst_type = str(row.get("instrumenttype") or "").strip().upper()
            if not token or not token.isdigit() or not exch_seg:
                malformed_rows += 1
                continue

            raw_lot = row.get("lotsize")
            if raw_lot is not None and str(raw_lot).strip() != "":
                try:
                    lot_val = identity_checked(positive_integer, raw_lot, "master lot_size")
                except (TypeError, ValueError):
                    malformed_rows += 1
                    continue
                if lot_val <= 0:
                    malformed_rows += 1
                    continue
                lot_size = lot_val
            else:
                if exch_seg == "NFO" and inst_type == "OPTIDX" and name in INDEX_SYMBOLS:
                    raise BrokerIdentityError(dict(reason_code="INCOMPLETE_CONTRACT", reason="Option master lot size is required."))
                lot_size = 1
            if "multiplier" in row and (isinstance(row["multiplier"], bool) or row["multiplier"] != 1):
                raise BrokerIdentityError(dict(reason_code="UNSUPPORTED_MULTIPLIER", reason="Master multiplier is unsupported."))

            if exch_seg == "NSE":
                if inst_type == "AMXIDX" or token in ("99926000", "99926009"):
                    norm_idx = identity_checked(canonical_symbol, name or symbol)
                    identity_checked(spot_identity, dict(symbol=norm_idx, angel_token=token), "angelone")
                    if symbol and identity_checked(canonical_symbol, symbol) != norm_idx:
                        raise BrokerIdentityError(dict(reason_code="IDENTITY_MISMATCH", reason="Master index name and trading symbol disagree."))
                    if norm_idx in idx_map and idx_map[norm_idx]["lot_size"] != lot_size:
                        raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Duplicate index master rows disagree on lot metadata."))
                    idx_map[norm_idx] = {
                        "symbol": norm_idx,
                        "trading_symbol": symbol or norm_idx,
                        "angel_token": token,
                        "exchange": "NSE",
                        "is_index": True,
                        "lot_size": lot_size,
                    }
                elif symbol.endswith("-EQ") or inst_type in ("", "EQ"):
                    base_sym = name or (symbol[:-3] if symbol.endswith("-EQ") else symbol)
                    if not base_sym:
                        malformed_rows += 1
                        continue
                    if symbol and identity_checked(canonical_symbol, symbol) != base_sym:
                        raise BrokerIdentityError(dict(reason_code="IDENTITY_MISMATCH", reason="Master equity name and trading symbol disagree."))
                    if base_sym in EQUITIES:
                        identity_checked(spot_identity, dict(symbol=base_sym, angel_token=token), "angelone")
                    if base_sym in eq_map and eq_map[base_sym]["angel_token"] != token:
                        raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Master equity has conflicting tokens."))
                    if any(r["angel_token"] == token and r["symbol"] != base_sym for r in eq_map.values()):
                        raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Master equity token has conflicting symbols."))
                    candidate = dict(symbol=base_sym, angel_token=token, exchange="NSE", lot_size=lot_size)
                    identity_checked(spot_identity, candidate, "angelone", {base_sym: candidate})
                    eq_map[base_sym] = {
                        "symbol": base_sym,
                        "trading_symbol": symbol or f"{base_sym}-EQ",
                        "angel_token": token,
                        "exchange": "NSE",
                        "is_index": False,
                        "lot_size": lot_size,
                    }
            elif exch_seg == "NFO" and inst_type == "OPTIDX" and name in INDEX_SYMBOLS:
                raw_exp = str(row.get("expiry") or "").strip()
                raw_strike = row.get("strike")
                opt_type = str(row.get("option_type") or "").strip().upper()
                if not opt_type:
                    if symbol.endswith("CE"):
                        opt_type = "CE"
                    elif symbol.endswith("PE"):
                        opt_type = "PE"
                if opt_type not in ("CE", "PE") or not raw_exp or raw_strike is None:
                    malformed_rows += 1
                    continue
                try:
                    iso_exp, angel_exp = _normalize_angel_expiry_str(raw_exp)
                    strike_int = _normalize_angel_scrip_strike(raw_strike, index_symbol=name)
                except BrokerDataError:
                    malformed_rows += 1
                    continue

                expected_symbol = f"{name}{angel_exp}{strike_int}{opt_type}"
                short_expiry = angel_exp[:-4] + angel_exp[-2:]
                if symbol not in (expected_symbol, f"{name}{short_expiry}{strike_int}{opt_type}"):
                    raise BrokerIdentityError(dict(reason_code="CONTRACT_IDENTITY_MISMATCH", reason="Option trading symbol disagrees with expiry, strike or side."))
                step = int(self.config.fo_indices.get(name, {}).get("strike_step", 50 if name == "NIFTY" else 100))
                if strike_int <= 0 or strike_int % step != 0:
                    malformed_rows += 1
                    continue

                contract_key = (name, iso_exp, strike_int, opt_type)
                if contract_key in seen_opt_keys:
                    if seen_opt_keys[contract_key] != token:
                        raise BrokerDataError(
                            f"Conflicting Angel One Scrip Master tokens for {name} {iso_exp} {strike_int} {opt_type}: "
                            f"{seen_opt_keys[contract_key]} vs {token}."
                        )
                    old = next(c for c in opt_list if c["angel_token"] == token)
                    if old["lot_size"] != lot_size:
                        raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Duplicate option rows disagree on lot size."))
                    continue
                if token in seen_opt_tokens and seen_opt_tokens[token] != contract_key:
                    raise BrokerDataError(
                        f"Duplicate Angel One NFO token {token} assigned to multiple option contracts: "
                        f"{seen_opt_tokens[token]} vs {contract_key}."
                    )
                seen_opt_keys[contract_key] = token
                seen_opt_tokens[token] = contract_key
                opt_list.append({
                    "index_symbol": name,
                    "symbol": symbol or f"{name}{angel_exp}{strike_int}{opt_type}",
                    "angel_token": token,
                    "exchange": "NFO",
                    "expiry": iso_exp,
                    "expiry_angel": angel_exp,
                    "strike": strike_int,
                    "option_type": opt_type,
                    "lot_size": lot_size,
                    "instrument_identity": dict(provider="angelone", symbol=symbol, underlying=name,
                        exchange="NFO", segment="NSE_FO_INDEX", instrument_type="OPTIDX", is_index=False,
                        identifier=token, expiry=iso_exp, strike=strike_int, option_type=opt_type,
                        lot_size=lot_size, multiplier=1, source="LOADED_ANGEL_MASTER",
                        source_revision=master_revision, historical_validity="NOT_ESTABLISHED"),
                })

        if strict and malformed_rows > 0:
            raise BrokerDataError(
                f"Angel One Scrip Master strict validation failed: {malformed_rows} malformed record(s) rejected."
            )

        if len(eq_map) + len(idx_map) + len(opt_list) == 0:
            raise BrokerDataError(
                "Angel One Scrip Master validation failed: 0 valid NSE/NFO instruments found in payload."
            )

        if require_index_options:
            if not opt_list:
                raise BrokerDataError(
                    "Angel One Scrip Master refresh rejected: 0 valid NIFTY/BANKNIFTY OPTIDX contracts found."
                )
            # Verify at least one paired CE/PE strike exists
            by_idx_exp_strike: Dict[Tuple[str, str, int], set] = {}
            for c in opt_list:
                by_idx_exp_strike.setdefault((c["index_symbol"], c["expiry"], int(c["strike"])), set()).add(c["option_type"])
            paired_count = sum(1 for sides in by_idx_exp_strike.values() if "CE" in sides and "PE" in sides)
            if paired_count == 0:
                raise BrokerDataError(
                    "Angel One Scrip Master refresh rejected: no paired CE/PE option contracts found."
                )

        return eq_map, idx_map, opt_list, malformed_rows

    def load_scrip_master(
        self,
        source: Any,
        require_index_options: bool = False,
        strict: bool = False,
    ) -> Dict[str, int]:
        """
        Loads and validates Angel One `OpenAPIScripMaster.json` records from a list of dicts
        or a local file path.
        - Validates schema into temporary structures first so a corrupt or malformed source
          NEVER overwrites an already-loaded valid in-memory Scrip Master.
        - Tracks file age, modification timestamp, and malformed row counts in `_scrip_master_meta`.
        """
        source_path: Optional[str] = None
        file_mtime: Optional[float] = None
        file_size: Optional[int] = None

        if isinstance(source, str):
            source_path = source.strip()
            if not os.path.isfile(source_path):
                if not (self._scrip_master_equities or self._scrip_master_indices or self._scrip_master_options):
                    self._scrip_master_meta.update({
                        "status": "FILE_MISSING",
                        "configured_path": os.path.basename(source_path),
                        "last_error": f"Angel One Scrip Master file not found: {os.path.basename(source_path)}",
                    })
                raise BrokerDataError(f"Angel One Scrip Master file not found: {source_path}")
            try:
                stat_res = os.stat(source_path)
                file_mtime = float(stat_res.st_mtime)
                file_size = int(stat_res.st_size)
                with open(source_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except Exception as exc:
                if not (self._scrip_master_equities or self._scrip_master_indices or self._scrip_master_options):
                    self._scrip_master_meta.update({
                        "status": "CORRUPT_ERROR",
                        "configured_path": os.path.basename(source_path),
                        "last_error": f"Failed to parse Angel One Scrip Master JSON: {exc}",
                    })
                raise BrokerDataError(f"Failed to parse Angel One Scrip Master JSON: {exc}") from exc
        elif isinstance(source, list):
            records = source
        else:
            raise BrokerDataError("load_scrip_master requires a list of instrument dicts or a JSON file path.")

        try:
            eq_map, idx_map, opt_list, malformed_rows = self._parse_and_validate_scrip_master_records(
                records,
                require_index_options=require_index_options,
                strict=strict,
            )
        except BrokerDataError as exc:
            if not (self._scrip_master_equities or self._scrip_master_indices or self._scrip_master_options):
                self._scrip_master_meta.update({
                    "status": "CORRUPT_ERROR",
                    "configured_path": os.path.basename(source_path) if source_path else self._scrip_master_meta.get("configured_path"),
                    "last_error": str(exc),
                })
            raise

        now_ist_str = format_ist_timestamp(parse_ist_timestamp(self.clock()))
        self._scrip_master_equities = eq_map
        self._scrip_master_indices = idx_map
        self._scrip_master_options = opt_list
        self._scrip_master_meta = {
            "status": "LOADED",
            "configured_path": os.path.basename(source_path) if source_path else (self._scrip_master_meta.get("configured_path") or "in_memory_records"),
            "loaded_path": os.path.realpath(source_path) if source_path else None,
            "loaded_mtime": file_mtime,
            "file_size_bytes": file_size,
            "loaded_at_ist": now_ist_str,
            "source_revision": digest(records),
            "historical_validity": "NOT_ESTABLISHED",
            "equities_loaded": len(eq_map),
            "indices_loaded": len(idx_map),
            "index_options_loaded": len(opt_list),
            "malformed_rows_rejected": malformed_rows,
            "last_error": None,
        }

        if self.persistence_store is not None and opt_list:
            self.restore_all_baselines_from_store()

        return {
            "equities_loaded": len(eq_map),
            "indices_loaded": len(idx_map),
            "index_options_loaded": len(opt_list),
            "malformed_rows_rejected": malformed_rows,
        }

    def ensure_scrip_master_loaded(self) -> None:
        """
        Ensures the configured local Scrip Master file is loaded once and cached in memory.
        Does NOT download or re-parse the file on every scan unless the file's mtime changed.
        If the file on disk was modified, validates the updated file via `refresh_scrip_master_safely`
        so a corrupt replacement never overwrites valid in-memory contracts.
        """
        scrip_path = str(getattr(self.config, "angel_scrip_master_path", "") or "").strip()
        if not scrip_path:
            return
        if not os.path.isfile(scrip_path):
            if not (self._scrip_master_equities or self._scrip_master_indices or self._scrip_master_options):
                self._scrip_master_meta["status"] = "FILE_MISSING"
                self._scrip_master_meta["configured_path"] = os.path.basename(scrip_path)
                self._scrip_master_meta["last_error"] = (
                    f"Angel One Scrip Master file not found: {os.path.basename(scrip_path)}"
                )
            return

        real_p = os.path.realpath(scrip_path)
        try:
            curr_mtime = float(os.path.getmtime(real_p))
        except OSError:
            return

        loaded_p = self._scrip_master_meta.get("loaded_path")
        loaded_mtime = self._scrip_master_meta.get("loaded_mtime")
        if loaded_p == real_p and loaded_mtime is not None and abs(curr_mtime - float(loaded_mtime)) < 1e-6:
            return

        # If we already have valid contracts in memory, refresh safely so a corrupt file on disk cannot clobber them
        if self._scrip_master_options or self._scrip_master_equities:
            try:
                self.refresh_scrip_master_safely(real_p)
            except BrokerDataError as exc:
                self._scrip_master_meta["last_error"] = f"Rejected corrupt Scrip Master reload: {exc}"
        else:
            self.load_scrip_master(real_p)

    def refresh_scrip_master_safely(
        self,
        candidate_source: Any,
        target_file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validates a candidate Scrip Master file or list of records before atomically replacing
        the active in-memory registries (and optionally `target_file_path` on disk).
        Guarantees that a corrupt download or malformed file never replaces a valid Scrip Master.
        """
        if isinstance(candidate_source, str):
            if not os.path.isfile(candidate_source):
                raise BrokerDataError(f"Candidate Scrip Master file not found: {candidate_source}")
            try:
                with open(candidate_source, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except Exception as exc:
                raise BrokerDataError(f"Candidate Scrip Master JSON is corrupt: {exc}") from exc
        elif isinstance(candidate_source, list):
            records = candidate_source
        else:
            raise BrokerDataError("refresh_scrip_master_safely requires a file path or list of dicts.")

        eq_map, idx_map, opt_list, malformed_rows = self._parse_and_validate_scrip_master_records(
            records,
            require_index_options=True,
            strict=False,
        )

        final_path = target_file_path or (candidate_source if isinstance(candidate_source, str) else None)
        file_mtime: Optional[float] = None
        file_size: Optional[int] = None

        if target_file_path:
            parent_dir = os.path.dirname(os.path.abspath(target_file_path))
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            tmp_path = f"{target_file_path}.tmp.{os.getpid()}"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(records, f)
                os.replace(tmp_path, target_file_path)
            except Exception as exc:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise BrokerDataError(f"Failed to atomically write refreshed Scrip Master file: {exc}") from exc

        if final_path and os.path.isfile(final_path):
            st = os.stat(final_path)
            file_mtime = float(st.st_mtime)
            file_size = int(st.st_size)

        now_ist_str = format_ist_timestamp(parse_ist_timestamp(self.clock()))
        self._scrip_master_equities = eq_map
        self._scrip_master_indices = idx_map
        self._scrip_master_options = opt_list
        self._scrip_master_meta = {
            "status": "LOADED",
            "configured_path": os.path.basename(final_path) if final_path else "in_memory_records",
            "loaded_path": os.path.realpath(final_path) if final_path and os.path.isfile(final_path) else None,
            "loaded_mtime": file_mtime,
            "file_size_bytes": file_size,
            "loaded_at_ist": now_ist_str,
            "source_revision": digest(records),
            "historical_validity": "NOT_ESTABLISHED",
            "equities_loaded": len(eq_map),
            "indices_loaded": len(idx_map),
            "index_options_loaded": len(opt_list),
            "malformed_rows_rejected": malformed_rows,
            "last_error": None,
        }

        if self.persistence_store is not None and opt_list:
            self.restore_all_baselines_from_store()

        return {
            "status": "REFRESHED",
            "equities_loaded": len(eq_map),
            "indices_loaded": len(idx_map),
            "index_options_loaded": len(opt_list),
            "malformed_rows_rejected": malformed_rows,
        }

    def get_scrip_master_status(self, now_ist: Optional[Any] = None) -> Dict[str, Any]:
        """
        Returns diagnostic metadata about the Angel One Scrip Master state, file age,
        active expiries, and paired strike counts for NIFTY and BANKNIFTY.
        """
        ref_now = parse_ist_timestamp(now_ist if now_ist is not None else self.clock())
        session_day = resolve_effective_trading_session_date(ref_now, self.config.configured_holidays)
        session_day_str = session_day.strftime("%Y-%m-%d")
        max_age_hrs = float(getattr(self.config, "angel_scrip_master_max_age_hours", 24.0) or 24.0)

        meta = dict(self._scrip_master_meta)
        loaded_mtime = meta.get("loaded_mtime")
        file_mtime_ist: Optional[str] = None
        file_age_hours: Optional[float] = None
        is_stale = False

        if loaded_mtime is not None:
            mtime_dt = datetime.fromtimestamp(float(loaded_mtime), tz=IST)
            file_mtime_ist = format_ist_timestamp(mtime_dt)
            file_age_hours = round(max(0.0, (ref_now - mtime_dt).total_seconds() / 3600.0), 2)
            if file_age_hours > max_age_hrs:
                is_stale = True

        active_expiries: Dict[str, List[str]] = {"NIFTY": [], "BANKNIFTY": []}
        paired_strikes_count: Dict[str, int] = {"NIFTY": 0, "BANKNIFTY": 0}
        for sym in INDEX_SYMBOLS:
            exps = sorted({
                c["expiry"]
                for c in self._scrip_master_options
                if c["index_symbol"] == sym and c["expiry"] >= session_day_str
            })
            active_expiries[sym] = exps
            if exps:
                nearest_exp = exps[0]
                by_strike: Dict[int, set] = {}
                for c in self._scrip_master_options:
                    if c["index_symbol"] == sym and c["expiry"] == nearest_exp:
                        by_strike.setdefault(int(c["strike"]), set()).add(c["option_type"])
                paired_strikes_count[sym] = sum(1 for legs in by_strike.values() if "CE" in legs and "PE" in legs)

        status_code = str(meta.get("status") or "NOT_CONFIGURED")
        if status_code == "LOADED":
            if self._scrip_master_options and not any(active_expiries.values()):
                status_code = "EXPIRED_CONTRACTS"
            elif is_stale:
                status_code = "STALE_FILE"

        return {
            "status": status_code,
            "configured_path": meta.get("configured_path"),
            "file_size_bytes": meta.get("file_size_bytes"),
            "file_mtime_ist": file_mtime_ist,
            "file_age_hours": file_age_hours,
            "max_age_hours": max_age_hrs,
            "is_stale": is_stale,
            "loaded_at_ist": meta.get("loaded_at_ist"),
            "equities_loaded": int(meta.get("equities_loaded") or len(self._scrip_master_equities)),
            "indices_loaded": int(meta.get("indices_loaded") or len(self._scrip_master_indices)),
            "index_options_loaded": int(meta.get("index_options_loaded") or len(self._scrip_master_options)),
            "malformed_rows_rejected": int(meta.get("malformed_rows_rejected") or 0),
            "active_expiries": active_expiries,
            "paired_strikes_count": paired_strikes_count,
            "last_error": meta.get("last_error"),
        }

    def resolve_instrument(self, symbol_or_meta: Any) -> Dict[str, Any]:
        """
        Resolves a symbol string (e.g., 'RELIANCE', 'NIFTY', 'BANKNIFTY', 'M&M') or
        a metadata dictionary into a validated Angel One instrument descriptor.
        """
        if isinstance(symbol_or_meta, str):
            sym = identity_checked(canonical_symbol, symbol_or_meta)
            if not sym:
                raise BrokerDataError("Instrument symbol cannot be empty.")
            if sym in (self.config.fo_indices or {}):
                idx_cfg = self.config.fo_indices[sym]
                meta = {
                    "symbol": sym,
                    "angel_token": idx_cfg.get("angel_token"),
                    "exchange": "NSE",
                    "lot_size": idx_cfg.get("lot_size", 1),
                    "trading_symbol": idx_cfg.get("name", sym),
                }
            else:
                match_eq = next(
                    (item for item in (self.config.equity_watchlist or []) if str(item.get("symbol", "")).upper() == sym),
                    None,
                )
                if match_eq is not None:
                    meta = {
                        "symbol": sym,
                        "angel_token": match_eq.get("angel_token"),
                        "exchange": match_eq.get("exchange", "NSE"),
                        "lot_size": 1,
                        "trading_symbol": f"{sym}-EQ",
                    }
                elif sym in self._scrip_master_indices:
                    meta = dict(self._scrip_master_indices[sym])
                elif sym in self._scrip_master_equities:
                    meta = dict(self._scrip_master_equities[sym])
                else:
                    raise BrokerIdentityError(dict(reason_code="UNKNOWN_INSTRUMENT",
                        reason="Unknown or unconfigured Angel One instrument symbol."))
        elif isinstance(symbol_or_meta, dict):
            meta = dict(symbol_or_meta)
            sym = identity_checked(canonical_symbol, meta.get("symbol"))
            meta["symbol"] = sym
            if sym and not meta.get("angel_token"):
                # Fill token from config/scrip master only if not explicitly passed
                if sym in (self.config.fo_indices or {}) and "dhan_id" not in meta and "upstox_key" not in meta:
                    meta["angel_token"] = self.config.fo_indices[sym].get("angel_token")
                else:
                    match_eq = next(
                        (item for item in (self.config.equity_watchlist or []) if str(item.get("symbol", "")).upper() == sym),
                        None,
                    )
                    if match_eq is not None and "dhan_security_id" not in meta and "upstox_key" not in meta:
                        meta["angel_token"] = match_eq.get("angel_token")
                    elif sym in self._scrip_master_equities:
                        meta["angel_token"] = self._scrip_master_equities[sym]["angel_token"]
        else:
            raise BrokerDataError("symbol_or_meta must be a symbol string or metadata dictionary.")

        validated = validate_symbol_meta(meta, "angelone", self._scrip_master_equities)
        validated["lot_size"] = identity_checked(positive_integer, meta.get("lot_size", (
            self.config.fo_indices[validated["symbol"]]["lot_size"]
            if validated["symbol"] in (self.config.fo_indices or {})
            else 1
        )), "lot_size")
        validated["trading_symbol"] = str(
            meta.get("trading_symbol")
            or (validated["symbol"] if validated["is_index"] else f"{validated['symbol']}-EQ")
        )
        return validated

    # -------------------------------------------------------------------------
    # Step 3.2: Current Quotes / Market Snapshots (LTP, OHLC, FULL)
    # -------------------------------------------------------------------------
    def _quote_identity(self, exchange, token):
        if exchange == "NSE":
            candidates = list(self._scrip_master_equities.values()) + list(self._scrip_master_indices.values())
            candidates += [dict(m, symbol=symbol) for symbol, m in INDICES.items()]
            candidates += list(EQUITIES.values())
            matches = {c["symbol"]: c for c in candidates if str(c.get("angel_token")) == token}
            if len(matches) == 1:
                return validate_symbol_meta(next(iter(matches.values())), "angelone", self._scrip_master_equities)["instrument_identity"]
        elif exchange == "NFO":
            matches = [c for c in self._scrip_master_options if c["angel_token"] == token]
            if len(matches) == 1:
                identity = matches[0]["instrument_identity"]
                return identity_checked(option_contract, identity, identity["underlying"], identity["expiry"],
                                        identity["strike"], identity["option_type"], "angelone", self.clock())
        raise BrokerIdentityError(dict(reason_code="UNKNOWN_INSTRUMENT", reason="Quote token has no unambiguous supported master identity."))

    @_safe_angel_market_read
    def get_quotes(
        self,
        exchange_tokens: Dict[str, List[str]],
        mode: str = "FULL",
    ) -> Dict[str, Any]:
        """
        Fetches real-time market quotes from official SmartAPI endpoint:
        `POST /rest/secure/angelbroking/market/v1/quote/`
        - `mode`: 'LTP', 'OHLC', or 'FULL'
        - `exchange_tokens`: e.g. `{"NSE": ["2885", "99926000"], "NFO": ["58784"]}`
        Automatically batches requests into chunks of <= 50 tokens per call.
        """
        norm_mode = str(mode or "FULL").strip().upper()
        if norm_mode not in self.SUPPORTED_QUOTE_MODES:
            raise BrokerDataError(
                f"Unsupported Angel One quote mode '{mode}'. Supported modes: {list(self.SUPPORTED_QUOTE_MODES)}."
            )
        if not isinstance(exchange_tokens, dict) or not exchange_tokens:
            raise BrokerDataError("exchange_tokens must be a non-empty dictionary mapping exchanges to token lists.")

        flat_pairs: List[Tuple[str, str]] = []
        for exch, tok_list in exchange_tokens.items():
            exch_up = str(exch or "").strip().upper()
            if exch_up not in ("NSE", "NFO", "BSE"):
                raise BrokerDataError(f"Unsupported exchange '{exch}' in Angel One quote request.")
            if not isinstance(tok_list, list) or not tok_list:
                raise BrokerDataError(f"Token list for exchange '{exch_up}' must be a non-empty list.")
            for t in tok_list:
                t_str = str(t or "").strip()
                if not t_str or not t_str.isdigit():
                    raise BrokerDataError(f"Invalid non-numeric Angel One token '{t}' for exchange '{exch_up}'.")
                self._quote_identity(exch_up, t_str)
                if (exch_up, t_str) in flat_pairs:
                    raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Duplicate quote request token."))
                flat_pairs.append((exch_up, t_str))

        fetched_norm: List[Dict[str, Any]] = []
        unfetched_all: List[Dict[str, Any]] = []
        by_token: Dict[str, Dict[str, Any]] = {}

        for start_idx in range(0, len(flat_pairs), self.MAX_QUOTE_TOKENS_PER_REQUEST):
            chunk = flat_pairs[start_idx:start_idx + self.MAX_QUOTE_TOKENS_PER_REQUEST]
            batch_map: Dict[str, List[str]] = {}
            for exch_up, t_str in chunk:
                batch_map.setdefault(exch_up, []).append(t_str)

            raw = self._request_json(
                "POST",
                "/rest/secure/angelbroking/market/v1/quote/",
                payload={"mode": norm_mode, "exchangeTokens": batch_map},
                context="market quote",
            )
            data = raw.get("data")
            if not isinstance(data, dict):
                raise BrokerDataError("Angel One market quote response missing 'data' object.")

            fetched = data.get("fetched")
            unfetched = data.get("unfetched")
            if not isinstance(fetched, list):
                raise BrokerDataError("Angel One market quote response missing 'data.fetched' list.")
            if isinstance(unfetched, list):
                unfetched_all.extend(unfetched)

            for item in fetched:
                if not isinstance(item, dict):
                    raise BrokerDataError("Angel One market quote entry is not a JSON object.")
                exch_val = str(item.get("exchange") or "").strip().upper()
                tok_val = str(item.get("symbolToken") or item.get("symboltoken") or "").strip()
                trad_sym = str(item.get("tradingSymbol") or item.get("tradingsymbol") or "").strip()
                if not exch_val or not tok_val:
                    raise BrokerDataError("Angel One quote item missing 'exchange' or 'symbolToken'.")

                if (exch_val, tok_val) not in chunk or f"{exch_val}:{tok_val}" in by_token:
                    raise BrokerIdentityError(dict(reason_code="RESPONSE_IDENTITY_MISMATCH", reason="Quote response contains an unrequested or duplicate instrument."))
                quote_identity = self._quote_identity(exch_val, tok_val)
                identity_checked(check_echo, raw, quote_identity)
                identity_checked(check_echo, item, quote_identity)

                if "ltp" not in item or item["ltp"] is None or isinstance(item["ltp"], bool):
                    raise BrokerDataError(f"Angel One quote for {exch_val}:{tok_val} missing 'ltp'.")
                try:
                    ltp = float(item["ltp"])
                except (TypeError, ValueError) as exc:
                    raise BrokerDataError(f"Angel One quote for {exch_val}:{tok_val} has non-numeric 'ltp'.") from exc
                if not math.isfinite(ltp) or ltp <= 0:
                    raise BrokerDataError(f"Angel One quote for {exch_val}:{tok_val} has non-positive 'ltp': {ltp}")

                norm_item: Dict[str, Any] = {
                    "exchange": exch_val,
                    "symbol_token": tok_val,
                    "instrument_identity": quote_identity,
                    "trading_symbol": trad_sym,
                    "ltp": round(ltp, 2),
                    "is_simulated": False,
                    "data_mode": "LIVE",
                }

                if norm_mode in ("OHLC", "FULL") or any(k in item for k in ("open", "high", "low", "close")):
                    for ohlc_k in ("open", "high", "low", "close"):
                        if ohlc_k not in item or item[ohlc_k] is None or isinstance(item[ohlc_k], bool):
                            raise BrokerDataError(
                                f"Angel One {norm_mode} quote for {exch_val}:{tok_val} missing '{ohlc_k}'."
                            )
                    try:
                        o_val = float(item["open"])
                        h_val = float(item["high"])
                        l_val = float(item["low"])
                        c_val = float(item["close"])
                    except (TypeError, ValueError) as exc:
                        raise BrokerDataError(
                            f"Angel One quote for {exch_val}:{tok_val} has non-numeric OHLC values."
                        ) from exc
                    if not all(math.isfinite(x) and x > 0 for x in (o_val, h_val, l_val, c_val)):
                        raise BrokerDataError(
                            f"Angel One quote for {exch_val}:{tok_val} has non-positive OHLC values."
                        )
                    if h_val < max(o_val, l_val, ltp) or l_val > min(o_val, h_val, ltp) or h_val < l_val:
                        raise BrokerDataError(
                            f"Angel One quote for {exch_val}:{tok_val} violates OHLC high/low relationships."
                        )
                    norm_item.update({
                        "open": round(o_val, 2),
                        "high": round(h_val, 2),
                        "low": round(l_val, 2),
                        "close": round(c_val, 2),
                    })

                if "tradeVolume" in item and item["tradeVolume"] is not None:
                    if isinstance(item["tradeVolume"], bool):
                        raise BrokerDataError("Boolean 'tradeVolume' in Angel One quote.")
                    try:
                        vol_val = int(round(float(item["tradeVolume"])))
                    except (TypeError, ValueError) as exc:
                        raise BrokerDataError("Invalid non-numeric 'tradeVolume' in Angel One quote.") from exc
                    if vol_val < 0:
                        raise BrokerDataError("Negative 'tradeVolume' in Angel One quote.")
                    norm_item["volume"] = vol_val

                if "opnInterest" in item and item["opnInterest"] is not None:
                    if isinstance(item["opnInterest"], bool):
                        raise BrokerDataError("Boolean 'opnInterest' in Angel One quote.")
                    try:
                        oi_val = int(round(float(item["opnInterest"])))
                    except (TypeError, ValueError) as exc:
                        raise BrokerDataError("Invalid non-numeric 'opnInterest' in Angel One quote.") from exc
                    if oi_val < 0:
                        raise BrokerDataError("Negative 'opnInterest' in Angel One quote.")
                    norm_item["open_interest"] = oi_val

                for opt_prev_k in ("prev_oi", "previous_oi", "prevOpenInterest"):
                    if opt_prev_k in item and item[opt_prev_k] is not None:
                        norm_item["prev_oi"] = int(round(float(item[opt_prev_k])))

                if "netChange" in item and item["netChange"] is not None:
                    norm_item["net_change"] = round(float(item["netChange"]), 2)
                if "percentChange" in item and item["percentChange"] is not None:
                    norm_item["percent_change"] = round(float(item["percentChange"]), 2)

                raw_feed_ts = item.get("exchFeedTime") or item.get("exchTradeTime")
                if raw_feed_ts:
                    try:
                        if isinstance(raw_feed_ts, str) and re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2}", raw_feed_ts):
                            observed = datetime.strptime(raw_feed_ts, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
                        else:
                            observed = _explicit_candle_timestamp(raw_feed_ts)
                        if (observed - parse_ist_timestamp(self.clock())).total_seconds() > self.config.live_candle_future_skew_seconds:
                            raise ValueError("Future quote observation.")
                        norm_item["feed_timestamp_ist"] = format_ist_timestamp(observed)
                        norm_item["quote_timestamp_ist"] = format_ist_timestamp(observed)
                    except (ValueError, TypeError, OverflowError):
                        raise BrokerDataError("Malformed or future exchange observation timestamp in Angel One quote.") from None

                fetched_norm.append(norm_item)
                by_token[f"{exch_val}:{tok_val}"] = norm_item

        if not fetched_norm:
            err_detail = ""
            if unfetched_all and isinstance(unfetched_all[0], dict):
                u0 = unfetched_all[0]
                err_detail = f" ({u0.get('errorCode', '')}: {u0.get('message', '')})"
            err_str = self._record_adapter_error(
                "INVALID_INSTRUMENT" if unfetched_all else "NETWORK_API_FAILURE",
                f"Angel One SmartAPI returned 0 fetched quotes{err_detail}.",
            )
            raise BrokerDataError(err_str)

        now_ist_str = format_ist_timestamp(parse_ist_timestamp(self.clock()))
        self.last_market_data_at_ist = now_ist_str
        for q_item in fetched_norm:
            if q_item.get("feed_timestamp_ist"):
                if not self.last_quote_timestamp_ist or q_item["feed_timestamp_ist"] > self.last_quote_timestamp_ist:
                    self.last_quote_timestamp_ist = q_item["feed_timestamp_ist"]
        self.last_error_category = "NONE"
        self.last_error_message = None

        return {
            "mode": norm_mode,
            "fetched": fetched_norm,
            "unfetched": unfetched_all,
            "by_token": by_token,
            "is_simulated": False,
            "data_mode": "LIVE",
        }

    @_safe_angel_market_read
    def get_quote(self, symbol_or_meta: Any, mode: str = "FULL") -> Dict[str, Any]:
        """Resolves a single instrument and returns its normalized quote dictionary."""
        inst = self.resolve_instrument(symbol_or_meta)
        res = self.get_quotes({inst["exchange"]: [inst["angel_token"]]}, mode=mode)
        key = f"{inst['exchange']}:{inst['angel_token']}"
        if key not in res["by_token"]:
            raise BrokerDataError(f"Angel One quote response did not include requested instrument {inst['symbol']} ({key}).")
        quote = dict(res["by_token"][key])
        identity_checked(check_echo, quote, inst["instrument_identity"])
        quote["symbol"] = inst["symbol"]
        return quote

    # -------------------------------------------------------------------------
    # Step 3.3: Historical / Intraday OHLCV Candles
    # -------------------------------------------------------------------------
    @_safe_angel_market_read
    def get_intraday_candles(
        self,
        symbol_meta: Dict[str, Any],
        interval_min: int = 5,
        pattern: Optional[str] = None,
        max_staleness_minutes: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        resolved_meta = self.resolve_instrument(symbol_meta)
        if not isinstance(interval_min, int) or isinstance(interval_min, bool) or interval_min not in self.SUPPORTED_INTERVALS:
            raise BrokerDataError(
                f"Unsupported Angel One candle interval '{interval_min}'. "
                f"Supported minute intervals: {sorted(self.SUPPORTED_INTERVALS.keys())}."
            )

        now_ist = parse_ist_timestamp(self.clock())
        warmup_days, session_day = resolve_nse_session_dates(
            now_ist,
            warmup_sessions=5,
            configured_holidays=self.config.configured_holidays,
        )
        from_day = warmup_days[0] if warmup_days else (session_day - timedelta(days=5))
        from_date = f"{from_day.isoformat()} 09:15"

        if session_day < now_ist.date():
            to_date = f"{session_day.isoformat()} 15:30"
        else:
            to_dt = max(now_ist, datetime.combine(session_day, dt_time(9, 20), tzinfo=IST))
            to_date = to_dt.strftime("%Y-%m-%d %H:%M")

        raw = self._request_json(
            "POST",
            "/rest/secure/angelbroking/historical/v1/getCandleData",
            payload={
                "exchange": resolved_meta["exchange"],
                "symboltoken": resolved_meta["angel_token"],
                "interval": self.SUPPORTED_INTERVALS[interval_min],
                "fromdate": from_date,
                "todate": to_date,
            },
            context=f"candle data ({resolved_meta['symbol']})",
        )

        rows = raw.get("data")
        if not isinstance(rows, list) or not rows:
            err_str = self._record_adapter_error(
                "NETWORK_API_FAILURE",
                f"Angel One SmartAPI returned empty candle data for {resolved_meta['symbol']}.",
            )
            raise BrokerDataError(err_str)

        candles = []
        for idx, r in enumerate(rows):
            if not isinstance(r, (list, tuple)) or len(r) < 6:
                err_str = self._record_adapter_error(
                    "NETWORK_API_FAILURE",
                    f"Angel One candle row {idx} has fewer than 6 elements.",
                )
                raise BrokerDataError(err_str)
            candles.append({
                "timestamp": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
                "is_simulated": False,
            })
        candles = identity_checked(bind_candles, candles, resolved_meta["instrument_identity"], raw)
        return enforce_live_candle_batch(
            self, candles, resolved_meta, interval_min, "angelone",
            max_staleness_minutes=max_staleness_minutes)

    # -------------------------------------------------------------------------
    # Step 3.4: NIFTY & BANKNIFTY Option Greeks, PCR & Option-Chain Assembly
    # -------------------------------------------------------------------------
    def get_option_greeks(
        self,
        index_symbol: str,
        expiry_date: str,
    ) -> Dict[Tuple[int, str], Dict[str, Any]]:
        """
        Fetches option Greeks and Implied Volatility from official SmartAPI endpoint:
        `POST /rest/secure/angelbroking/marketData/v1/optionGreek`
        Request payload: `{"name": "NIFTY" | "BANKNIFTY", "expirydate": "DDMMMYYYY"}`.
        Returns a mapping keyed by `(strike_int, option_type)` -> normalized Greek dict.
        """
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS:
            raise BrokerDataError(f"Option Greeks are restricted to {INDEX_SYMBOLS}, got '{index_symbol}'.")
        iso_exp, angel_exp = _normalize_angel_expiry_str(expiry_date)

        raw = self._request_json(
            "POST",
            "/rest/secure/angelbroking/marketData/v1/optionGreek",
            payload={"name": sym, "expirydate": angel_exp},
            context=f"optionGreek ({sym} {angel_exp})",
        )
        rows = raw.get("data")
        if not isinstance(rows, list) or not rows:
            raise BrokerDataError(f"Angel One optionGreek returned empty data for {sym} ({angel_exp}).")

        greeks_map: Dict[Tuple[int, str], Dict[str, Any]] = {}
        for idx, r in enumerate(rows):
            if not isinstance(r, dict):
                raise BrokerDataError(f"Angel One optionGreek row {idx} is not a JSON object.")
            if "name" in r and identity_checked(canonical_symbol, r["name"]) != sym:
                raise BrokerIdentityError(dict(reason_code="RESPONSE_IDENTITY_MISMATCH", reason="Greek response underlying conflicts with request."))
            if "expiry" in r and _normalize_angel_expiry_str(r["expiry"])[0] != iso_exp:
                raise BrokerIdentityError(dict(reason_code="RESPONSE_IDENTITY_MISMATCH", reason="Greek response expiry conflicts with request."))
            opt_type = str(r.get("optionType") or "").strip().upper()
            if opt_type not in ("CE", "PE"):
                raise BrokerDataError(f"Angel One optionGreek row {idx} has invalid optionType '{opt_type}'.")
            strike_int = _normalize_angel_scrip_strike(r.get("strikePrice"), index_symbol=sym)
            try:
                iv = float(r.get("impliedVolatility", 0.0))
                delta = float(r.get("delta", 0.0))
                gamma = float(r.get("gamma", 0.0))
                theta = float(r.get("theta", 0.0))
                vega = float(r.get("vega", 0.0))
                vol = float(r.get("tradeVolume", 0.0) or 0.0)
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"Angel One optionGreek row {idx} has non-numeric Greek/IV field.") from exc
            if not all(math.isfinite(v) for v in (iv, delta, gamma, theta, vega, vol)) or iv < 0:
                raise BrokerDataError(f"Angel One optionGreek row {idx} has non-finite or negative IV.")

            if (strike_int, opt_type) in greeks_map:
                raise BrokerIdentityError(dict(reason_code="AMBIGUOUS_IDENTITY", reason="Duplicate Greek contract response."))
            greeks_map[(strike_int, opt_type)] = {
                "index": sym,
                "expiry": iso_exp,
                "expiry_angel": angel_exp,
                "strike": strike_int,
                "option_type": opt_type,
                "iv": round(iv, 2),
                "delta": round(delta, 4),
                "gamma": round(gamma, 6),
                "theta": round(theta, 4),
                "vega": round(vega, 4),
                "trade_volume": int(round(vol)),
            }
        return greeks_map

    def get_put_call_ratio(self) -> List[Dict[str, Any]]:
        """
        Fetches exchange Put-Call Ratio summary from official SmartAPI endpoint:
        `GET /rest/secure/angelbroking/marketData/v1/putCallRatio`.
        """
        raw = self._request_json(
            "GET",
            "/rest/secure/angelbroking/marketData/v1/putCallRatio",
            payload=None,
            context="putCallRatio",
        )
        rows = raw.get("data")
        if not isinstance(rows, list) or not rows:
            raise BrokerDataError("Angel One putCallRatio returned empty data.")
        out: List[Dict[str, Any]] = []
        for idx, item in enumerate(rows):
            if not isinstance(item, dict) or "pcr" not in item or "tradingSymbol" not in item:
                raise BrokerDataError(f"Angel One putCallRatio row {idx} missing 'pcr' or 'tradingSymbol'.")
            try:
                pcr_val = float(item["pcr"])
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"Angel One putCallRatio row {idx} has non-numeric 'pcr'.") from exc
            if not math.isfinite(pcr_val) or pcr_val <= 0:
                raise BrokerDataError(f"Angel One putCallRatio row {idx} has non-positive 'pcr': {pcr_val}")
            out.append({
                "trading_symbol": str(item["tradingSymbol"]).strip().upper(),
                "pcr": round(pcr_val, 4),
            })
        return out

    def set_prior_oi_baseline(
        self,
        index_symbol: str,
        expiry: str,
        baseline_by_strike: Dict[int, Dict[str, int]],
        session_date: Optional[str] = None,
        observation_timestamp: Optional[Any] = None,
        source: str = "manual_baseline",
        data_mode: str = "LIVE",
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Registers verified prior-session OI baseline values (`{strike_int: {"ce_prev_oi": int, "pe_prev_oi": int}}`)
        for `(index_symbol, expiry)`.
        - Validates symbol, expiry, strike step, complete CE/PE pairs, non-negative OI, session_date (< current session),
          timestamp freshness, and strict `LIVE` data provenance.
        - When `self.persistence_store` is attached and `persist=True`, atomically persists the baseline records
          to SQLite (`oi_baselines`) so they survive application restarts.
        """
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS:
            raise BrokerDataError(f"Unsupported index_symbol '{index_symbol}' for OI baseline.")
        iso_exp, _ = _normalize_angel_expiry_str(expiry)

        dm = str(data_mode or "LIVE").strip().upper()
        if dm != "LIVE" or "sim" in str(source).lower() or "paper" in str(source).lower():
            raise BrokerDataError(
                f"AngelOneSmartAPIAdapter strictly requires LIVE OI baselines; rejected data_mode={dm!r}, source={source!r}."
            )

        if not isinstance(baseline_by_strike, dict) or not baseline_by_strike:
            raise BrokerDataError(f"baseline_by_strike for {sym} {iso_exp} must be a non-empty dictionary.")

        now_ist = parse_ist_timestamp(self.clock())
        curr_session = resolve_effective_trading_session_date(now_ist, self.config.configured_holidays)
        curr_session_str = curr_session.strftime("%Y-%m-%d")
        expected_prior = resolve_prior_trading_session_date(curr_session, self.config.configured_holidays)

        if iso_exp < curr_session_str:
            raise BrokerDataError(
                f"Cannot register OI baseline for expired contract {sym} {iso_exp} (current session {curr_session_str})."
            )

        resolved_session_str = str(session_date).strip() if session_date else expected_prior.strftime("%Y-%m-%d")
        try:
            sess_dt = datetime.strptime(resolved_session_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise BrokerDataError(f"Invalid baseline session_date '{resolved_session_str}'. Expected YYYY-MM-DD.") from exc

        if resolved_session_str >= curr_session_str:
            raise BrokerDataError(
                f"Prior-session OI baseline session_date ({resolved_session_str}) must be strictly earlier than "
                f"current trading session ({curr_session_str}). Never substitute intraday OI for previous-session OI."
            )
        if not is_nse_trading_day(sess_dt, self.config.configured_holidays):
            raise BrokerDataError(
                f"Baseline session_date {resolved_session_str} is a weekend or configured NSE holiday."
            )

        max_age = int(getattr(self.config, "angel_baseline_max_sessions_age", 1) or 1)
        sessions_age = count_trading_sessions_between(sess_dt, curr_session, self.config.configured_holidays)
        if sessions_age > max_age:
            raise BrokerDataError(
                f"Baseline session_date {resolved_session_str} is stale ({sessions_age} trading sessions old; max allowed is {max_age})."
            )

        if "intraday" in str(source).lower():
            raise BrokerDataError(
                f"Cannot register intraday observation source '{source}' as a prior-session closing OI baseline."
            )

        if observation_timestamp is not None:
            obs_dt = parse_ist_timestamp(observation_timestamp)
            if obs_dt > now_ist + timedelta(seconds=60):
                raise BrokerDataError(
                    f"Baseline observation_timestamp {format_ist_timestamp(obs_dt)} is in the future."
                )
            if obs_dt.strftime("%Y-%m-%d") != resolved_session_str:
                raise BrokerDataError(
                    f"Baseline observation_timestamp date {obs_dt.strftime('%Y-%m-%d')} does not match session_date {resolved_session_str}."
                )
            obs_ts_str = format_ist_timestamp(obs_dt)
            if not is_closing_session_timestamp(obs_dt):
                raise BrokerDataError(
                    f"Cannot promote arbitrary intraday observation timestamp {obs_ts_str} (< 15:25:00 IST session close) "
                    f"to a prior-session closing OI baseline."
                )
        else:
            obs_ts_str = f"{resolved_session_str} 15:30:00"

        step = int(self.config.fo_indices.get(sym, {}).get("strike_step", 50 if sym == "NIFTY" else 100))
        cleaned: Dict[int, Dict[str, int]] = {}
        for k, v in baseline_by_strike.items():
            try:
                strike_flt = float(k)
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"Invalid non-numeric strike {k!r} in baseline.") from exc
            if not math.isfinite(strike_flt) or strike_flt <= 0 or abs(strike_flt - round(strike_flt)) > 1e-4:
                raise BrokerDataError(f"Baseline strike must be a positive integer, got {k!r}.")
            strike_int = int(round(strike_flt))
            if strike_int % step != 0:
                raise BrokerDataError(f"Baseline strike {strike_int} for {sym} is not aligned to strike step {step}.")

            if not isinstance(v, dict) or "ce_prev_oi" not in v or "pe_prev_oi" not in v:
                raise BrokerDataError(f"Baseline for strike {k} must contain both 'ce_prev_oi' and 'pe_prev_oi'.")
            if v["ce_prev_oi"] is None or v["pe_prev_oi"] is None or isinstance(v["ce_prev_oi"], bool) or isinstance(v["pe_prev_oi"], bool):
                raise BrokerDataError(f"Baseline for strike {k} has null/boolean OI values.")
            try:
                ce_prev = int(round(float(v["ce_prev_oi"])))
                pe_prev = int(round(float(v["pe_prev_oi"])))
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"Baseline OI for strike {k} must be numeric.") from exc
            if ce_prev < 0 or pe_prev < 0:
                raise BrokerDataError(f"Baseline OI for strike {k} cannot be negative.")
            cleaned[strike_int] = {"ce_prev_oi": ce_prev, "pe_prev_oi": pe_prev}

        if persist and self.persistence_store is not None:
            try:
                self.persistence_store.save_paired_strike_baselines(
                    index_symbol=sym,
                    expiry=iso_exp,
                    baseline_by_strike=cleaned,
                    session_date=resolved_session_str,
                    observation_timestamp=obs_ts_str,
                    source=source,
                    data_mode="LIVE",
                    now_ist=now_ist,
                    configured_holidays=self.config.configured_holidays,
                    allow_newer_intraday_update=True,
                    baseline_kind="CLOSING_BASELINE",
                    require_closing_evidence=True,
                )
            except (PersistenceValidationError, PersistenceError) as exc:
                raise BrokerDataError(f"Failed to persist OI baseline for {sym} {iso_exp}: {exc}") from exc

        self._prior_oi_baselines[(sym, iso_exp)] = cleaned
        self._prior_oi_baseline_meta[(sym, iso_exp)] = {
            "session_date": resolved_session_str,
            "observation_timestamp": obs_ts_str,
            "source": source,
            "baseline_kind": "CLOSING_BASELINE",
            "data_mode": "LIVE",
            "sessions_age": sessions_age,
            "paired_strikes_count": len(cleaned),
        }
        return self._prior_oi_baseline_meta[(sym, iso_exp)]

    def import_prior_oi_baseline_file(
        self,
        file_path: str,
        default_index_symbol: Optional[str] = None,
        default_expiry: Optional[str] = None,
        default_session_date: Optional[str] = None,
        source: str = "external_verified_closing_import",
    ) -> Dict[str, Any]:
        """
        Imports a verified prior-session closing OI baseline file (JSON or CSV) into the attached
        SQLite persistence store (strictly `data_mode='LIVE'`) and restores active baselines into memory.
        """
        if self.persistence_store is None:
            raise BrokerDataError("Cannot import OI baseline file: no SQLite persistence store attached.")
        now_ist = parse_ist_timestamp(self.clock())
        try:
            res = self.persistence_store.import_prior_oi_baseline_file(
                file_path=file_path,
                default_index_symbol=default_index_symbol,
                default_expiry=default_expiry,
                default_session_date=default_session_date,
                source=source,
                data_mode="LIVE",
                now_ist=now_ist,
                configured_holidays=self.config.configured_holidays,
            )
        except (PersistenceValidationError, PersistenceError) as exc:
            raise BrokerDataError(f"OI baseline import failed: {exc}") from exc
        self.restore_all_baselines_from_store(now_ist=now_ist)
        return res

    def restore_prior_oi_baseline_from_store(
        self,
        index_symbol: str,
        expiry: str,
        required_strikes: Optional[List[int]] = None,
        now_ist: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Loads and validates a persisted prior-session LIVE OI baseline from `self.persistence_store`
        into `self._prior_oi_baselines[(sym, iso_exp)]`.
        """
        sym = str(index_symbol or "").strip().upper()
        iso_exp, _ = _normalize_angel_expiry_str(expiry)
        ref_now = parse_ist_timestamp(now_ist if now_ist is not None else self.clock())
        curr_session = resolve_effective_trading_session_date(ref_now, self.config.configured_holidays)
        max_age = int(getattr(self.config, "angel_baseline_max_sessions_age", 1) or 1)

        if self.persistence_store is None:
            return {
                "status": "PERSISTENCE_DISABLED",
                "usable": False,
                "index_symbol": sym,
                "expiry": iso_exp,
                "reason": "SQLite persistence store is not attached to AngelOneSmartAPIAdapter.",
            }

        res = self.persistence_store.load_prior_session_oi_baseline(
            index_symbol=sym,
            expiry=iso_exp,
            current_session_date=curr_session,
            data_mode="LIVE",
            configured_holidays=self.config.configured_holidays,
            max_sessions_age=max_age,
            required_strikes=required_strikes,
            now_ist=ref_now,
        )
        if res.get("usable"):
            self._prior_oi_baselines[(sym, iso_exp)] = dict(res["strikes"])
            self._prior_oi_baseline_meta[(sym, iso_exp)] = {
                "session_date": res["baseline_session_date"],
                "observation_timestamp": res.get("observation_timestamp"),
                "source": res.get("source"),
                "data_mode": "LIVE",
                "sessions_age": res.get("sessions_age"),
                "paired_strikes_count": res.get("paired_strikes_count"),
            }
        else:
            # Remove any stale/invalid entry in memory if DB check rejected it (unless memory entry was manually set for current test without DB rows)
            if res.get("status") not in ("NO_PRIOR_BASELINE", "PERSISTENCE_DISABLED"):
                self._prior_oi_baselines.pop((sym, iso_exp), None)
                self._prior_oi_baseline_meta.pop((sym, iso_exp), None)
        return res

    def restore_all_baselines_from_store(self, now_ist: Optional[Any] = None) -> Dict[str, Any]:
        """
        Restores validated prior-session LIVE OI baselines from SQLite for all active
        NIFTY and BANKNIFTY expiries on startup or after Scrip Master load.
        """
        if self.persistence_store is None:
            return {"restored": 0, "details": {}}

        ref_now = parse_ist_timestamp(now_ist if now_ist is not None else self.clock())
        curr_session = resolve_effective_trading_session_date(ref_now, self.config.configured_holidays)
        curr_session_str = curr_session.strftime("%Y-%m-%d")

        restored_count = 0
        details: Dict[str, Any] = {}
        for sym in INDEX_SYMBOLS:
            expiries = sorted({
                c["expiry"]
                for c in self._scrip_master_options
                if c["index_symbol"] == sym and c["expiry"] >= curr_session_str
            })
            if not expiries:
                # Also check if SQLite has any non-expired baselines for `sym` even before Scrip Master is loaded
                try:
                    q_res = self.persistence_store.query_oi_baselines(
                        index_symbol=sym,
                        data_mode="LIVE",
                        limit=50,
                        offset=0,
                    )
                    expiries = sorted({
                        r["expiry"]
                        for r in q_res.get("items", [])
                        if r["expiry"] >= curr_session_str and r["session_date"] < curr_session_str
                    })
                except Exception:
                    expiries = []

            for exp_str in expiries[:2]:
                res = self.restore_prior_oi_baseline_from_store(sym, exp_str, now_ist=ref_now)
                details[f"{sym}:{exp_str}"] = res.get("status")
                if res.get("usable"):
                    restored_count += 1

        return {"restored": restored_count, "details": details}

    def get_option_apex_readiness(self, now_ist: Optional[Any] = None) -> Dict[str, Any]:
        """
        Evaluates whether Strategy 3 (`Option Apex OI Shift`) has all required live inputs
        on Angel One SmartAPI (credentials, valid Scrip Master, active expiry, and verified
        prior-session LIVE OI baseline) for NIFTY and BANKNIFTY.
        Never reports Option Apex as READY when any required input is missing, stale, or incomplete.
        """
        self.ensure_scrip_master_loaded()
        ref_now = parse_ist_timestamp(now_ist if now_ist is not None else self.clock())
        curr_session = resolve_effective_trading_session_date(ref_now, self.config.configured_holidays)
        curr_session_str = curr_session.strftime("%Y-%m-%d")
        expected_prior = resolve_prior_trading_session_date(curr_session, self.config.configured_holidays)
        expected_prior_str = expected_prior.strftime("%Y-%m-%d")
        max_age = int(getattr(self.config, "angel_baseline_max_sessions_age", 1) or 1)

        creds_ok = self.config.is_broker_credentials_configured("angelone")
        scrip_status = self.get_scrip_master_status(now_ist=ref_now)

        indices_report: Dict[str, Dict[str, Any]] = {}
        for sym in INDEX_SYMBOLS:
            if not creds_ok:
                indices_report[sym] = {
                    "status": "UNAVAILABLE_MISSING_CREDENTIALS",
                    "usable": False,
                    "expiry": None,
                    "baseline_session_date": None,
                    "expected_prior_session_date": expected_prior_str,
                    "paired_strikes_ready": 0,
                    "reason": "Angel One SmartAPI credentials are missing or invalid.",
                }
                continue

            if scrip_status["status"] == "CORRUPT_ERROR" and not self._scrip_master_options:
                indices_report[sym] = {
                    "status": "UNAVAILABLE_CORRUPT_SCRIP_MASTER",
                    "usable": False,
                    "expiry": None,
                    "baseline_session_date": None,
                    "expected_prior_session_date": expected_prior_str,
                    "paired_strikes_ready": 0,
                    "reason": scrip_status.get("last_error") or "Scrip Master file is corrupt or malformed.",
                }
                continue

            sym_contracts = [c for c in self._scrip_master_options if c["index_symbol"] == sym]
            if not sym_contracts:
                indices_report[sym] = {
                    "status": "UNAVAILABLE_NO_SCRIP_MASTER",
                    "usable": False,
                    "expiry": None,
                    "baseline_session_date": None,
                    "expected_prior_session_date": expected_prior_str,
                    "paired_strikes_ready": 0,
                    "reason": f"No NFO OPTIDX contracts loaded from Scrip Master for {sym}.",
                }
                continue

            active_exps = sorted({c["expiry"] for c in sym_contracts if c["expiry"] >= curr_session_str})
            if not active_exps:
                indices_report[sym] = {
                    "status": "UNAVAILABLE_EXPIRED_CONTRACTS",
                    "usable": False,
                    "expiry": None,
                    "baseline_session_date": None,
                    "expected_prior_session_date": expected_prior_str,
                    "paired_strikes_ready": 0,
                    "reason": f"All Scrip Master option contracts for {sym} expired prior to {curr_session_str}.",
                }
                continue

            nearest_exp = active_exps[0]
            by_strike: Dict[int, set] = {}
            for c in sym_contracts:
                if c["expiry"] == nearest_exp:
                    by_strike.setdefault(int(c["strike"]), set()).add(c["option_type"])
            paired_scrip_strikes = sorted(k for k, legs in by_strike.items() if "CE" in legs and "PE" in legs)
            if not paired_scrip_strikes:
                indices_report[sym] = {
                    "status": "UNAVAILABLE_INCOMPLETE_PAIRS",
                    "usable": False,
                    "expiry": nearest_exp,
                    "baseline_session_date": None,
                    "expected_prior_session_date": expected_prior_str,
                    "paired_strikes_ready": 0,
                    "reason": f"Scrip Master has no paired CE/PE strikes for {sym} {nearest_exp}.",
                }
                continue

            # Check SQLite store first if attached
            if self.persistence_store is not None:
                store_res = self.restore_prior_oi_baseline_from_store(sym, nearest_exp, now_ist=ref_now)
                if store_res.get("usable"):
                    indices_report[sym] = {
                        "status": "READY",
                        "usable": True,
                        "expiry": nearest_exp,
                        "baseline_session_date": store_res.get("baseline_session_date"),
                        "baseline_observation_timestamp": store_res.get("observation_timestamp"),
                        "baseline_kind": store_res.get("baseline_kind", "CLOSING_BASELINE"),
                        "expected_prior_session_date": expected_prior_str,
                        "sessions_age": store_res.get("sessions_age"),
                        "baseline_source": store_res.get("source"),
                        "paired_strikes_ready": store_res.get("paired_strikes_count", 0),
                        "oi_change_measure": "angelone_quote_oi_vs_prior_baseline",
                        "reason": store_res.get("reason"),
                    }
                    continue
                elif store_res.get("status") == "NO_PRIOR_BASELINE" and store_res.get("sub_status") == "INTRADAY_OBSERVATION_ONLY":
                    indices_report[sym] = {
                        "status": "UNAVAILABLE_NO_PRIOR_BASELINE",
                        "sub_status": "INTRADAY_OBSERVATION_ONLY",
                        "usable": False,
                        "expiry": nearest_exp,
                        "baseline_session_date": store_res.get("baseline_session_date"),
                        "expected_prior_session_date": expected_prior_str,
                        "intraday_only_records_present": store_res.get("intraday_only_records_present", 0),
                        "paired_strikes_ready": 0,
                        "reason": store_res.get("reason"),
                    }
                    continue
                elif store_res.get("status") in (
                    "STALE_BASELINE",
                    "INCOMPLETE_CE_PE_PAIRS",
                    "EXPIRY_MISMATCH",
                    "EXPIRED_CONTRACT",
                    "FUTURE_TIMESTAMP_INVALID",
                    "CORRUPT_BASELINE",
                ):
                    status_map = {
                        "STALE_BASELINE": "UNAVAILABLE_STALE_BASELINE",
                        "INCOMPLETE_CE_PE_PAIRS": "UNAVAILABLE_INCOMPLETE_PAIRS",
                        "EXPIRY_MISMATCH": "UNAVAILABLE_EXPIRY_MISMATCH",
                        "EXPIRED_CONTRACT": "UNAVAILABLE_EXPIRED_CONTRACTS",
                        "FUTURE_TIMESTAMP_INVALID": "UNAVAILABLE_INVALID_BASELINE",
                        "CORRUPT_BASELINE": "UNAVAILABLE_INVALID_BASELINE",
                    }
                    indices_report[sym] = {
                        "status": status_map[store_res["status"]],
                        "usable": False,
                        "expiry": nearest_exp,
                        "baseline_session_date": store_res.get("baseline_session_date"),
                        "expected_prior_session_date": expected_prior_str,
                        "sessions_age": store_res.get("sessions_age"),
                        "paired_strikes_ready": 0,
                        "reason": store_res.get("reason"),
                    }
                    continue

            # Check in-memory baseline fallback (when persistence is disabled or set in-memory only)
            mem_base = self._prior_oi_baselines.get((sym, nearest_exp), {})
            mem_meta = self._prior_oi_baseline_meta.get((sym, nearest_exp), {})
            if mem_base:
                sess_str = str(mem_meta.get("session_date") or expected_prior_str)
                sess_age = count_trading_sessions_between(sess_str, curr_session, self.config.configured_holidays)
                if sess_str < curr_session_str and sess_age <= max_age:
                    indices_report[sym] = {
                        "status": "READY",
                        "usable": True,
                        "expiry": nearest_exp,
                        "baseline_session_date": sess_str,
                        "expected_prior_session_date": expected_prior_str,
                        "sessions_age": sess_age,
                        "baseline_source": mem_meta.get("source", "in_memory_baseline"),
                        "paired_strikes_ready": len(mem_base),
                        "oi_change_measure": "angelone_quote_oi_vs_prior_baseline",
                        "reason": f"Prior-session OI baseline loaded ({len(mem_base)} paired strikes from {sess_str}).",
                    }
                    continue
                else:
                    indices_report[sym] = {
                        "status": "UNAVAILABLE_STALE_BASELINE",
                        "usable": False,
                        "expiry": nearest_exp,
                        "baseline_session_date": sess_str,
                        "expected_prior_session_date": expected_prior_str,
                        "sessions_age": sess_age,
                        "paired_strikes_ready": 0,
                        "reason": f"In-memory baseline from {sess_str} is stale ({sess_age} sessions old).",
                    }
                    continue

            indices_report[sym] = {
                "status": "UNAVAILABLE_NO_PRIOR_BASELINE",
                "usable": False,
                "expiry": nearest_exp,
                "baseline_session_date": None,
                "expected_prior_session_date": expected_prior_str,
                "paired_strikes_ready": 0,
                "reason": (
                    f"No prior-session LIVE OI baseline (< {curr_session_str}) found for {sym} {nearest_exp} "
                    f"(expected {expected_prior_str})."
                ),
            }

        all_ready = all(r.get("usable") for r in indices_report.values())
        any_ready = any(r.get("usable") for r in indices_report.values())
        if all_ready:
            overall = "READY"
        elif any_ready:
            overall = "PARTIAL_READY"
        else:
            overall = indices_report["NIFTY"]["status"]

        return {
            "overall_status": overall,
            "usable": any_ready,
            "data_mode": "LIVE",
            "other_strategies_operational": bool(creds_ok),
            "scrip_master_status": scrip_status["status"],
            "indices": indices_report,
        }

    def get_expiry_list(self, index_symbol: str) -> List[str]:
        self.ensure_scrip_master_loaded()
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS:
            raise BrokerDataError(f"Unsupported F&O index symbol '{index_symbol}' for Angel One expiry list.")
        matching_expiries = sorted({
            c["expiry"]
            for c in self._scrip_master_options
            if c["index_symbol"] == sym
        })
        if not matching_expiries:
            raise UnsupportedBrokerCapabilityError(
                f"Angel One SmartAPI requires NFO Scrip Master (OpenAPIScripMaster.json) contracts to resolve "
                f"active option expiries for {sym}."
            )
        now_ist = parse_ist_timestamp(self.clock())
        session_date = resolve_effective_trading_session_date(now_ist, self.config.configured_holidays)
        valid = [
            e for e in matching_expiries
            if datetime.strptime(e, "%Y-%m-%d").date() >= session_date
        ]
        if not valid:
            raise UnsupportedBrokerCapabilityError(
                f"Angel One Scrip Master contains no active option expiries for {sym} on or after {session_date.isoformat()} "
                f"(expired contracts: {matching_expiries}). Refresh OpenAPIScripMaster.json."
            )
        return valid

    def get_option_chain(
        self,
        index_symbol: str,
        bias: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves and normalizes the NIFTY or BANKNIFTY option chain for Angel One SmartAPI:
        - Clearly distinguishes an unsupported capability (`UnsupportedBrokerCapabilityError` when
          NFO Scrip Master option contracts or valid prior-session OI baselines are unavailable/stale/incomplete)
          from a temporary network/auth/rate-limit failure (`BrokerDataError`).
        - Persists current-session live NFO quote OI observations into SQLite (`oi_baselines`)
          so subsequent trading sessions have a verified prior-session baseline across restarts.
        - Never substitutes same-session intraday OI changes for previous-session closing OI,
          and never fabricates or backfills missing OI values with zero.
        """
        self.ensure_scrip_master_loaded()
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS:
            raise BrokerDataError(f"Option chain is restricted to {INDEX_SYMBOLS}, got '{index_symbol}'.")

        if self._scrip_master_meta.get("status") == "CORRUPT_ERROR" and not self._scrip_master_options:
            raise UnsupportedBrokerCapabilityError(
                f"Angel One SmartAPI does not provide a single-call option-chain endpoint with previous-day OI "
                f"baselines (ce_oi_change / pe_oi_change) for {sym}, and the configured Scrip Master is corrupt: "
                f"{self._scrip_master_meta.get('last_error')}"
            )

        sym_contracts = [c for c in self._scrip_master_options if c["index_symbol"] == sym]
        if not sym_contracts:
            raise UnsupportedBrokerCapabilityError(
                f"Angel One SmartAPI does not provide a single-call option-chain endpoint with previous-day OI "
                f"baselines (ce_oi_change / pe_oi_change) for {sym}. Assembling a full chain requires dynamic NFO "
                f"Scrip Master ingestion plus persisted prior-session OI baseline snapshots."
            )

        self._validate_credentials()
        now_ist = parse_ist_timestamp(self.clock())
        curr_session = resolve_effective_trading_session_date(now_ist, self.config.configured_holidays)
        curr_session_str = curr_session.strftime("%Y-%m-%d")
        max_age = int(getattr(self.config, "angel_baseline_max_sessions_age", 1) or 1)

        if expiry:
            selected_expiry, angel_exp = _normalize_angel_expiry_str(expiry)
            if selected_expiry < curr_session_str:
                raise UnsupportedBrokerCapabilityError(
                    f"Requested Angel One option expiry {selected_expiry} for {sym} has already expired "
                    f"prior to session {curr_session_str}."
                )
        else:
            selected_expiry = self.get_expiry_list(sym)[0]
            _, angel_exp = _normalize_angel_expiry_str(selected_expiry)

        exp_contracts = [c for c in sym_contracts if c["expiry"] == selected_expiry]
        if not exp_contracts:
            avail_exps = sorted({c["expiry"] for c in sym_contracts})
            raise UnsupportedBrokerCapabilityError(
                f"No Angel One NFO option contracts found in Scrip Master for {sym} expiry {selected_expiry} "
                f"(available expiries: {avail_exps})."
            )

        # Group contracts by strike -> {'CE': token, 'PE': token}
        by_strike: Dict[int, Dict[str, str]] = {}
        for c in exp_contracts:
            by_strike.setdefault(int(c["strike"]), {})[c["option_type"]] = c["angel_token"]

        unpaired_scrip = sorted(k for k, legs in by_strike.items() if "CE" not in legs or "PE" not in legs)
        all_paired_strikes = sorted(k for k, legs in by_strike.items() if "CE" in legs and "PE" in legs)
        if not all_paired_strikes:
            raise UnsupportedBrokerCapabilityError(
                f"Angel One Scrip Master has incomplete CE/PE option pairs for {sym} {selected_expiry} "
                f"(unpaired strikes: {unpaired_scrip})."
            )

        # 1. Fetch underlying spot quote on NSE
        idx_meta = self.resolve_instrument(sym)
        spot_quote = self.get_quote(idx_meta, mode="LTP")
        spot = float(spot_quote["ltp"])
        step = int(self.config.fo_indices.get(sym, {}).get("strike_step", 50 if sym == "NIFTY" else 100))
        atm_strike = int(round(spot / step) * step)

        # Check if any strike within the ATM window in Scrip Master is unpaired
        unpaired_near_atm = [k for k in unpaired_scrip if abs(k - atm_strike) <= step * 8]
        if unpaired_near_atm:
            raise UnsupportedBrokerCapabilityError(
                f"Angel One Scrip Master has incomplete CE/PE contract pairs near ATM for {sym} {selected_expiry} "
                f"at strikes {unpaired_near_atm}."
            )

        paired_strikes = [k for k in all_paired_strikes if abs(k - atm_strike) <= step * 8]
        if not paired_strikes:
            paired_strikes = all_paired_strikes

        if atm_strike not in paired_strikes:
            atm_strike = min(paired_strikes, key=lambda k: abs(k - spot))

        nfo_tokens: List[str] = []
        for k in paired_strikes:
            nfo_tokens.append(by_strike[k]["CE"])
            nfo_tokens.append(by_strike[k]["PE"])

        quotes_res = self.get_quotes({"NFO": nfo_tokens}, mode="FULL")
        by_tok = quotes_res["by_token"]

        # Validate quotes and collect current-session live OI observations
        current_session_oi_map: Dict[int, Dict[str, int]] = {}
        latest_feed_ts: Optional[str] = None
        for k in paired_strikes:
            ce_tok = by_strike[k]["CE"]
            pe_tok = by_strike[k]["PE"]
            ce_q = by_tok.get(f"NFO:{ce_tok}")
            pe_q = by_tok.get(f"NFO:{pe_tok}")
            if not ce_q or not pe_q:
                raise BrokerDataError(f"Angel One quote response missing NFO option leg for strike {k}.")
            if "open_interest" not in ce_q or "open_interest" not in pe_q:
                raise BrokerDataError(f"Angel One FULL quote for strike {k} missing 'opnInterest'.")
            current_session_oi_map[k] = {
                "ce_oi": int(ce_q["open_interest"]),
                "pe_oi": int(pe_q["open_interest"]),
            }
            for q_leg in (ce_q, pe_q):
                fts = q_leg.get("feed_timestamp_ist")
                if fts and (latest_feed_ts is None or fts > latest_feed_ts):
                    latest_feed_ts = fts

        # Persist current-session live OI observations into `oi_baselines`:
        # - Observations at or after 15:25:00 IST qualify as CLOSING_BASELINE (`source='angelone_live_quote'`).
        # - Observations earlier than 15:25:00 IST are recorded strictly as INTRADAY_OBSERVATION
        #   (`source='angelone_intraday_observation'`) and are NEVER promoted to a prior-session closing baseline!
        if self.persistence_store is not None and is_nse_trading_day(curr_session, self.config.configured_holidays):
            obs_ts_for_store = (
                latest_feed_ts
                if (latest_feed_ts and latest_feed_ts[:10] == curr_session_str)
                else f"{curr_session_str} {now_ist.strftime('%H:%M:%S')}"
            )
            is_closing_obs = is_closing_session_timestamp(obs_ts_for_store)
            obs_source = "angelone_live_quote" if is_closing_obs else "angelone_intraday_observation"
            obs_kind = "CLOSING_BASELINE" if is_closing_obs else "INTRADAY_OBSERVATION"
            try:
                self.persistence_store.save_paired_strike_baselines(
                    index_symbol=sym,
                    expiry=selected_expiry,
                    baseline_by_strike=current_session_oi_map,
                    session_date=curr_session_str,
                    observation_timestamp=obs_ts_for_store,
                    source=obs_source,
                    data_mode="LIVE",
                    now_ist=now_ist,
                    configured_holidays=self.config.configured_holidays,
                    allow_newer_intraday_update=True,
                    baseline_kind=obs_kind,
                    auto_classify_by_timestamp=True,
                )
            except Exception:
                # Non-fatal if current-session baseline recording encounters a transient issue
                pass

        # Restore/validate prior-session OI baseline (< curr_session_str) from SQLite if attached
        baseline_map: Dict[int, Dict[str, int]] = {}
        baseline_meta: Dict[str, Any] = {}
        if self.persistence_store is not None:
            store_res = self.restore_prior_oi_baseline_from_store(
                sym,
                selected_expiry,
                required_strikes=paired_strikes,
                now_ist=now_ist,
            )
            if store_res.get("usable"):
                baseline_map = store_res["strikes"]
                baseline_meta = {
                    "baseline_session_date": store_res.get("baseline_session_date"),
                    "baseline_source": store_res.get("source"),
                }
            elif store_res.get("status") != "NO_PRIOR_BASELINE":
                raise UnsupportedBrokerCapabilityError(
                    f"Angel One SmartAPI does not provide a single-call option-chain endpoint with previous-day OI "
                    f"baselines (ce_oi_change / pe_oi_change) for {sym} {selected_expiry}: "
                    f"[{store_res.get('status')}] {store_res.get('reason')}"
                )

        if not baseline_map:
            mem_map = self._prior_oi_baselines.get((sym, selected_expiry), {})
            mem_meta = self._prior_oi_baseline_meta.get((sym, selected_expiry), {})
            if mem_map:
                sess_str = str(mem_meta.get("session_date") or "")
                if sess_str:
                    if sess_str >= curr_session_str:
                        raise UnsupportedBrokerCapabilityError(
                            f"Angel One SmartAPI does not provide a single-call option-chain endpoint with previous-day OI "
                            f"baselines: in-memory baseline session_date ({sess_str}) is not from a prior session (< {curr_session_str})."
                        )
                    sess_age = count_trading_sessions_between(sess_str, curr_session, self.config.configured_holidays)
                    if sess_age > max_age:
                        raise UnsupportedBrokerCapabilityError(
                            f"Angel One SmartAPI does not provide a single-call option-chain endpoint with previous-day OI "
                            f"baselines: baseline from {sess_str} is stale ({sess_age} trading sessions old; max {max_age})."
                        )
                baseline_map = mem_map
                baseline_meta = {
                    "baseline_session_date": sess_str or None,
                    "baseline_source": mem_meta.get("source", "in_memory_baseline"),
                }

        greeks_map: Dict[Tuple[int, str], Dict[str, Any]] = {}
        if self.fetch_option_greeks_in_chain:
            try:
                greeks_map = self.get_option_greeks(sym, angel_exp)
            except BrokerIdentityError:
                raise
            except BrokerDataError:
                greeks_map = {}

        strikes_out: List[Dict[str, Any]] = []
        total_ce_oi = 0
        total_pe_oi = 0

        for k in paired_strikes:
            ce_tok = by_strike[k]["CE"]
            pe_tok = by_strike[k]["PE"]
            ce_q = by_tok[f"NFO:{ce_tok}"]
            pe_q = by_tok[f"NFO:{pe_tok}"]
            ce_oi = int(ce_q["open_interest"])
            pe_oi = int(pe_q["open_interest"])

            strike_base = baseline_map.get(k, {})
            ce_prev = strike_base.get("ce_prev_oi", ce_q.get("prev_oi"))
            pe_prev = strike_base.get("pe_prev_oi", pe_q.get("prev_oi"))
            if ce_prev is None or pe_prev is None:
                raise UnsupportedBrokerCapabilityError(
                    f"Angel One SmartAPI does not provide a single-call option-chain endpoint with previous-day OI "
                    f"baselines (ce_oi_change / pe_oi_change) for {sym} strike {k}. Register a verified prior OI "
                    f"baseline via set_prior_oi_baseline() or persist a prior-session baseline first."
                )

            ce_prev_int = int(ce_prev)
            pe_prev_int = int(pe_prev)
            if ce_prev_int < 0 or pe_prev_int < 0:
                raise UnsupportedBrokerCapabilityError(
                    f"Angel One prior-session OI baseline for {sym} strike {k} contains negative OI."
                )

            ce_iv = float(greeks_map.get((k, "CE"), {}).get("iv", 0.0))
            pe_iv = float(greeks_map.get((k, "PE"), {}).get("iv", 0.0))

            total_ce_oi += ce_oi
            total_pe_oi += pe_oi
            strikes_out.append({
                "strike": k,
                "ce_contract": ce_q["instrument_identity"],
                "pe_contract": pe_q["instrument_identity"],
                "ce_ltp": round(float(ce_q["ltp"]), 2),
                "ce_oi": ce_oi,
                "ce_prev_oi": ce_prev_int,
                "ce_oi_change": ce_oi - ce_prev_int,
                "ce_iv": round(ce_iv, 2),
                "pe_ltp": round(float(pe_q["ltp"]), 2),
                "pe_oi": pe_oi,
                "pe_prev_oi": pe_prev_int,
                "pe_oi_change": pe_oi - pe_prev_int,
                "pe_iv": round(pe_iv, 2),
            })

        if total_ce_oi <= 0:
            raise BrokerDataError(f"Angel One option chain for {sym} has zero total Call OI; cannot compute valid PCR.")

        pcr = round(total_pe_oi / float(total_ce_oi), 2)
        return {
            "index": sym,
            "expiry": selected_expiry,
            "spot": round(spot, 2),
            "atm_strike": atm_strike,
            "pcr": pcr,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "oi_change_measure": "angelone_quote_oi_vs_prior_baseline",
            "baseline_session_date": baseline_meta.get("baseline_session_date"),
            "baseline_source": baseline_meta.get("baseline_source"),
            "strikes": strikes_out,
            "is_simulated": False,
            "data_mode": "LIVE",
        }


    def run_live_acceptance_diagnostics(
        self,
        equity_symbol: str = "RELIANCE",
        skip_network: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes the 9-check read-only Angel One live-data acceptance diagnostic suite
        against this adapter instance without starting the full scanner.
        """
        from diagnostics import run_angelone_diagnostics
        return run_angelone_diagnostics(
            config=self.config,
            adapter=self,
            store=self.persistence_store,
            clock=self.clock,
            equity_symbol=equity_symbol,
            skip_network=skip_network,
        )


class DhanHQAdapter(BaseBrokerAdapter):
    """
    Official DhanHQ v2 Adapter:
    - Intraday Candles: POST https://api.dhanhq.co/v2/charts/intraday
      Supported intervals: 1, 5, 15, 25, 60 (minutes).
    - Expiry List: POST https://api.dhanhq.co/v2/optionchain/expirylist
    - Option Chain: POST https://api.dhanhq.co/v2/optionchain (Rate limit: 1 req / 3s)
    """
    name = "DhanHQ API v2"
    is_simulated = False
    BASE_URL = "https://api.dhanhq.co/v2"
    SUPPORTED_INTERVALS = (1, 5, 15, 25, 60)

    def __init__(self, config: BotConfig, clock: Optional[Callable[[], datetime]] = None):
        self.config = config
        self.clock = clock or (lambda: datetime.now(IST))
        self._last_oc_call = 0.0

    def _validate_credentials(self) -> None:
        if _is_placeholder_secret(self.config.dhan_client_id) or _is_placeholder_secret(self.config.dhan_access_token):
            raise BrokerDataError("DhanHQ credentials are missing or set to placeholder values.")

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "client-id": str(self.config.dhan_client_id),
            "access-token": str(self.config.dhan_access_token),
        }

    def _respect_oc_rate_limit(self) -> None:
        elapsed = time.time() - self._last_oc_call
        if elapsed < 3.05:
            time.sleep(3.05 - elapsed)

    def get_intraday_candles(
        self,
        symbol_meta: Dict[str, Any],
        interval_min: int = 5,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._validate_credentials()
        validated_meta = validate_symbol_meta(symbol_meta, "dhan")
        if not isinstance(interval_min, int) or isinstance(interval_min, bool) or interval_min not in self.SUPPORTED_INTERVALS:
            raise BrokerDataError(
                f"Unsupported DhanHQ intraday interval '{interval_min}'. "
                f"Supported minute intervals: {list(self.SUPPORTED_INTERVALS)}."
            )

        now_ist = parse_ist_timestamp(self.clock())
        payload = json.dumps({
            "securityId": validated_meta["security_id"],
            "exchangeSegment": validated_meta["exchange_segment"],
            "instrument": validated_meta["instrument"],
            "interval": str(interval_min),
            "oi": False,
            "fromDate": (now_ist - timedelta(days=5)).strftime("%Y-%m-%d 09:15:00"),
            "toDate": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}/charts/intraday",
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise BrokerDataError(f"DhanHQ intraday candle request failed ({type(exc).__name__}).") from exc

        if not isinstance(data, dict):
            raise BrokerDataError("DhanHQ intraday candle response is not a JSON object.")

        opens = data.get("open")
        highs = data.get("high")
        lows = data.get("low")
        closes = data.get("close")
        volumes = data.get("volume")
        timestamps = data.get("timestamp")
        arrays = (opens, highs, lows, closes, volumes, timestamps)
        if not all(isinstance(arr, list) for arr in arrays):
            raise BrokerDataError("DhanHQ intraday candle response missing required OHLCV arrays.")
        n = len(closes)
        if n == 0 or any(len(arr) != n for arr in arrays):
            raise BrokerDataError("DhanHQ intraday candle arrays are empty or have mismatched lengths.")

        candles = [
            {
                "timestamp": timestamps[i],
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "is_simulated": False,
            }
            for i in range(n)
        ]
        candles = identity_checked(bind_candles, candles, validated_meta["instrument_identity"], data)
        return enforce_live_candle_batch(self, candles, validated_meta, interval_min, "dhan")

    def get_expiry_list(self, index_symbol: str) -> List[str]:
        self._validate_credentials()
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS or sym not in self.config.fo_indices:
            raise BrokerDataError(f"Unsupported F&O index symbol '{index_symbol}' for DhanHQ expiry list.")
        idx_meta = validate_symbol_meta(dict(self.config.fo_indices[sym], symbol=sym), "dhan")

        self._respect_oc_rate_limit()
        payload = json.dumps({
            "UnderlyingScrip": int(idx_meta["security_id"]),
            "UnderlyingSeg": "IDX_I",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}/optionchain/expirylist",
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        self._last_oc_call = time.time()
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise BrokerDataError(f"DhanHQ expiry list request failed ({type(exc).__name__}).") from exc

        if not isinstance(raw, dict) or raw.get("status") != "success":
            raise BrokerDataError("DhanHQ expiry list returned an unsuccessful status.")
        now_ist = parse_ist_timestamp(self.clock())
        _, session_date = resolve_nse_session_dates(now_ist, warmup_sessions=0)
        nearest = _parse_and_select_expiry(raw.get("data"), session_date, self.name)
        all_valid = sorted(
            s.strip()
            for s in raw.get("data", [])
            if isinstance(s, str) and datetime.strptime(s.strip(), "%Y-%m-%d").date() >= session_date
        )
        return all_valid if all_valid else [nearest]

    def get_option_chain(
        self,
        index_symbol: str,
        bias: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._validate_credentials()
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS or sym not in self.config.fo_indices:
            raise BrokerDataError(f"Unsupported F&O index symbol '{index_symbol}' for DhanHQ option chain.")
        idx_meta = validate_symbol_meta(dict(self.config.fo_indices[sym], symbol=sym), "dhan")

        selected_expiry = expiry
        if not selected_expiry:
            selected_expiry = self.get_expiry_list(sym)[0]
        else:
            try:
                datetime.strptime(selected_expiry, "%Y-%m-%d")
            except ValueError as exc:
                raise BrokerDataError(f"Invalid expiry format '{selected_expiry}'. Expected YYYY-MM-DD.") from exc

        if selected_expiry < parse_ist_timestamp(self.clock()).date().isoformat():
            raise BrokerIdentityError(dict(reason_code="EXPIRED_CONTRACT", reason="Requested option expiry is in the past."))
        self._respect_oc_rate_limit()
        payload = json.dumps({
            "UnderlyingScrip": int(idx_meta["security_id"]),
            "UnderlyingSeg": "IDX_I",
            "Expiry": selected_expiry,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}/optionchain",
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        self._last_oc_call = time.time()
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise BrokerDataError(f"DhanHQ option chain request failed ({type(exc).__name__}).") from exc

        return self._normalize_option_chain_response(sym, selected_expiry, raw)

    def _normalize_option_chain_response(
        self,
        index_symbol: str,
        expiry: str,
        raw: Dict[str, Any],
    ) -> Dict[str, Any]:
        requested = validate_symbol_meta(dict(self.config.fo_indices[index_symbol], symbol=index_symbol), "dhan")["instrument_identity"]
        identity_checked(check_chain_metadata, raw, index_symbol, expiry, "dhan", requested["identifier"])
        if not isinstance(raw, dict) or raw.get("status") != "success":
            raise BrokerDataError("DhanHQ option chain response returned unsuccessful status.")
        data = raw.get("data")
        if not isinstance(data, dict):
            raise BrokerDataError("DhanHQ option chain response missing 'data' object.")

        identity_checked(check_chain_metadata, data, index_symbol, expiry, "dhan", requested["identifier"])
        try:
            spot = float(data["last_price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerDataError("DhanHQ option chain response missing valid underlying 'last_price'.") from exc
        if not math.isfinite(spot) or spot <= 0:
            raise BrokerDataError(f"DhanHQ option chain returned invalid spot price: {spot}")

        oc_map = data.get("oc")
        if not isinstance(oc_map, dict) or not oc_map:
            raise BrokerDataError("DhanHQ option chain response contains an empty 'oc' strike map.")

        strikes: List[Dict[str, Any]] = []
        total_ce_oi = 0
        total_pe_oi = 0

        for strike_key, strike_obj in oc_map.items():
            try:
                strike_val = float(strike_key)
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"DhanHQ option chain has invalid strike key '{strike_key}'.") from exc
            if not math.isfinite(strike_val) or strike_val <= 0:
                raise BrokerDataError(f"DhanHQ option chain has non-positive strike '{strike_key}'.")
            strike_int = int(round(strike_val)) if abs(strike_val - round(strike_val)) < 1e-4 else strike_val

            if not isinstance(strike_obj, dict) or "ce" not in strike_obj or "pe" not in strike_obj:
                raise BrokerDataError(f"DhanHQ option chain strike {strike_key} is missing 'ce' or 'pe' leg.")
            ce = strike_obj["ce"]
            pe = strike_obj["pe"]
            if not isinstance(ce, dict) or not isinstance(pe, dict):
                raise BrokerDataError(f"DhanHQ option chain strike {strike_key} has malformed 'ce'/'pe' object.")

            for leg_name, leg in (("ce", ce), ("pe", pe)):
                identity_checked(check_chain_metadata, leg, index_symbol, expiry, "dhan", requested["identifier"], strike_int, leg_name.upper())
                for req_field in ("last_price", "oi", "previous_oi"):
                    if req_field not in leg or leg[req_field] is None or isinstance(leg[req_field], bool):
                        raise BrokerDataError(
                            f"DhanHQ option chain strike {strike_key} {leg_name} missing required field '{req_field}'."
                        )

            try:
                ce_ltp = float(ce["last_price"])
                ce_oi = int(ce["oi"])
                ce_prev_oi = int(ce["previous_oi"])
                ce_iv = float(ce.get("implied_volatility", 0.0) or 0.0)

                pe_ltp = float(pe["last_price"])
                pe_oi = int(pe["oi"])
                pe_prev_oi = int(pe["previous_oi"])
                pe_iv = float(pe.get("implied_volatility", 0.0) or 0.0)
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"DhanHQ option chain strike {strike_key} has non-numeric field.") from exc

            if not (math.isfinite(ce_ltp) and math.isfinite(pe_ltp) and ce_ltp >= 0 and pe_ltp >= 0):
                raise BrokerDataError(f"DhanHQ option chain strike {strike_key} has invalid option LTP.")
            if ce_oi < 0 or pe_oi < 0 or ce_prev_oi < 0 or pe_prev_oi < 0:
                raise BrokerDataError(f"DhanHQ option chain strike {strike_key} has negative OI.")

            ce_oi_change = ce_oi - ce_prev_oi
            pe_oi_change = pe_oi - pe_prev_oi
            total_ce_oi += ce_oi
            total_pe_oi += pe_oi

            strikes.append({
                "strike": strike_int,
                "ce_ltp": round(ce_ltp, 2),
                "ce_oi": ce_oi,
                "ce_prev_oi": ce_prev_oi,
                "ce_oi_change": ce_oi_change,
                "ce_iv": round(ce_iv, 2),
                "pe_ltp": round(pe_ltp, 2),
                "pe_oi": pe_oi,
                "pe_prev_oi": pe_prev_oi,
                "pe_oi_change": pe_oi_change,
                "pe_iv": round(pe_iv, 2),
            })

        strikes.sort(key=lambda s: float(s["strike"]))
        if total_ce_oi <= 0:
            raise BrokerDataError("DhanHQ option chain total Call OI is zero; cannot calculate valid PCR.")

        atm_strike = min(strikes, key=lambda s: abs(float(s["strike"]) - spot))["strike"]
        pcr = round(total_pe_oi / total_ce_oi, 2)
        return {
            "index": index_symbol,
            "expiry": expiry,
            "spot": round(spot, 2),
            "atm_strike": atm_strike,
            "pcr": pcr,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "oi_change_measure": "net_change_from_previous_day_close",
            "strikes": strikes,
            "is_simulated": False,
            "data_mode": "LIVE",
        }


def sanitize_broker_message(config, message):
    """Sanitize untrusted diagnostic/error text without serializing request objects."""
    fields = ("upstox_access_token", "upstox_api_key", "angel_api_key", "angel_pin",
              "angel_totp_secret", "dhan_access_token", "telegram_bot_token", "gemini_api_key",
              "angel_client_code", "dhan_client_id", "telegram_chat_id")
    values = [str(getattr(config, field, "") or "") for field in fields]
    variants = [variant for value in values if value for variant in
                (value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))]
    text = str(message)
    for value in sorted(set(variants), key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s,;'\"}\]]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)\b(authorization|access_token|api_key|pin|totp_secret)\b\s*[:=]\s*[^\r\n,}]+",
                  r"\1=[REDACTED]", text)
    return text


_UPSTOX_ERROR_BODY_LIMIT = 8192
_UPSTOX_ERROR_MESSAGE_LIMIT = 240


def _safe_upstox_message(config, message):
    """A broken sanitizer must never expose its input or exception context."""
    try:
        clean = sanitize_broker_message(config, message)
        if isinstance(clean, str):
            return clean
    except Exception:
        pass
    return "Upstox request failed; safe error detail is unavailable."


def sanitize_upstox_error_detail(config, detail):
    """Whitelist one documented error's code/message; never serialize other fields.

    Both snake_case and deprecated camelCase codes are documented at
    https://upstox.com/developer/api-documentation/response-structure/.
    Provider text remains an untrusted explanation, never an acceptance status.
    """
    try:
        if not isinstance(detail, dict):
            return {}
        result = {}
        for key in ("error_code", "errorCode"):
            code = detail.get(key)
            if isinstance(code, str) and re.fullmatch(r"UDAPI[0-9]{1,12}", code):
                clean = sanitize_broker_message(config, code)
                if clean == code:
                    result["provider_error_code"] = code
                break
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            # Redact before truncation/normalization so a partial secret cannot
            # survive a length cap. Keep only the first line to prevent spoofing.
            clean = sanitize_broker_message(config, message)
            if not isinstance(clean, str):
                return {}
            clean = clean.splitlines()[0] if clean.splitlines() else ""
            # Header/request dumps and personal-account explanations are omitted.
            if re.search(r"(?i)\b(authorization|headers?|cookies?|access[_-]?token|api[_-]?key|"
                         r"client[_-]?(secret|id)|user[_-]?(id|name)|account[_-]?id|ucc|name|email|phone|"
                         r"password|pin|totp[_-]?secret)\b['\"]?\s*[:=]|<[^>]+>|\b(Request|Response)\s*\(", clean):
                return result
            clean = re.sub(r"(?i)(?:[a-z][a-z0-9+.-]*://|www\.)[^\s]+", "[URL REDACTED]", clean)
            clean = re.sub(r"[^\s@]+@[^\s@]+", "[EMAIL REDACTED]", clean)
            clean = re.sub(r"(?<!\w)\+?[0-9][0-9 ()-]{6,}[0-9](?!\w)", "[NUMBER REDACTED]", clean)
            clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", clean)
            clean = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in clean)
            clean = " ".join(clean.split())
            clean = sanitize_broker_message(config, clean)
            if isinstance(clean, str) and clean:
                result["provider_error_message"] = clean[:_UPSTOX_ERROR_MESSAGE_LIMIT]
        return result
    except Exception:
        return {}


def _safe_upstox_read(function):
    """Keep raw transport/parser causes out of errors, logs and persistence."""
    @wraps(function)
    def guarded(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except BrokerDataError as exc:
            clean = _safe_upstox_message(self.config, str(exc))
            exc.args = (clean,)
            if hasattr(exc, "rejection"):
                exc.rejection = dict(exc.rejection, reason=_safe_upstox_message(self.config, exc.rejection["reason"]))
            self.last_error_category = getattr(exc, "error_category", "INVALID_RESPONSE")
            self.last_error_message = clean
            raise exc from None
        except Exception:
            self._fail("INVALID_RESPONSE", "Upstox response could not be validated.")
    return guarded


class UpstoxV2Adapter(BaseBrokerAdapter):
    """
    Official Upstox API v2 Adapter:
    - Intraday Candles: GET https://api.upstox.com/v2/historical-candle/intraday/{instrument_key}/{interval}
      Official v2 intervals: '1minute', '30minute' (Error UDAPI1020 on other strings).
      For 5m and 15m requests, fetches '1minute' bars and aggregates completed NSE session-aligned buckets.
    - Option Contracts (Expiry Resolution): GET https://api.upstox.com/v2/option/contract?instrument_key={key}
    - Put/Call Option Chain: GET https://api.upstox.com/v2/option/chain?instrument_key={key}&expiry_date={expiry}
    """
    name = "Upstox API v2"
    is_simulated = False
    BASE_URL = "https://api.upstox.com/v2"
    SUPPORTED_INTERVALS = (1, 5, 15, 30)

    def __init__(self, config: BotConfig, clock: Optional[Callable[[], datetime]] = None):
        self.config = config
        self.clock = clock or (lambda: datetime.now(IST))
        self.authenticated_at_ist = None
        self._authorized_token_sha256 = None
        self._authorized_reads = 0
        self.last_market_data_at_ist = None
        self.last_error_category = "NONE"
        self.last_error_message = None

    def _fail(self, category, message, *, http_status=None, provider_detail=None):
        self.last_error_category = category
        details = sanitize_upstox_error_detail(self.config, provider_detail)
        if details:
            message += " Provider detail: " + "; ".join(details.values())
        self.last_error_message = _safe_upstox_message(self.config, message)
        error = BrokerDataError(self.last_error_message)
        error.error_category = category
        if type(http_status) is int and 100 <= http_status <= 599:
            error.http_status = http_status
            for key, value in details.items():
                setattr(error, key, value)
        raise error from None

    def is_authentication_verified(self):
        token = str(self.config.upstox_access_token or "")
        return bool(self.authenticated_at_ist and self._authorized_token_sha256 == hashlib.sha256(token.encode()).hexdigest())

    def is_connection_verified(self):
        return bool(self.is_authentication_verified() and self.last_market_data_at_ist and self.last_error_category == "NONE")

    def _validate_credentials(self) -> None:
        if _is_placeholder_secret(self.config.upstox_access_token):
            self.authenticated_at_ist = None
            self._authorized_token_sha256 = None
            self._fail("MISSING_CREDENTIALS", "Upstox access token is missing or set to a placeholder value.")

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.upstox_access_token}",
        }

    def _request_json(self, path, params=None):
        """Bounded GET only; allowlist prevents this helper reaching trading routes."""
        self._validate_credentials()
        intraday = re.fullmatch(r"/historical-candle/intraday/([^/]+)/(1minute|30minute)", path)
        safe_intraday = False
        if intraday:
            try:
                encoded_key = intraday.group(1)
                key = urllib.parse.unquote(encoded_key, encoding="utf-8", errors="strict")
                safe_intraday = ("|" in key and all(key.split("|"))
                    and not any(c in key for c in "/\\?#%")
                    and not any(unicodedata.category(c).startswith("C") for c in key)
                    and urllib.parse.quote(key, safe="") == encoded_key)
            except (ValueError, UnicodeError):
                pass
        if not (path in ("/market-quote/quotes", "/option/contract", "/option/chain") or safe_intraday):
            self._fail("UNSUPPORTED_ENDPOINT", "Upstox diagnostic transport permits only supported market-data reads.")
        token_sha = hashlib.sha256(self.config.upstox_access_token.encode()).hexdigest()
        url = self.BASE_URL + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate response field.")
                result[key] = value
            return result
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                self._fail("INVALID_RESPONSE", "Upstox response exceeded the supported size.")
            raw = json.loads(content.decode("utf-8"), object_pairs_hook=unique_fields)
        except urllib.error.HTTPError as exc:
            code = exc.code
            if code in (401, 403):
                self.authenticated_at_ist = None
                self._authorized_token_sha256 = None
            category = {401: "AUTH_FAILURE", 403: "FORBIDDEN", 429: "RATE_LIMIT"}.get(code, "HTTP_ERROR")
            detail = None
            try:
                content = exc.read(_UPSTOX_ERROR_BODY_LIMIT + 1)
                if isinstance(content, bytes) and len(content) <= _UPSTOX_ERROR_BODY_LIMIT:
                    envelope = json.loads(content.decode("utf-8"), object_pairs_hook=unique_fields)
                    if isinstance(envelope, dict) and envelope.get("status") == "error":
                        errors = envelope.get("errors")
                        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                            detail = errors[0]
            except Exception:
                # Optional explanation only; retain the original HTTP failure.
                pass
            finally:
                try:
                    exc.close()
                except Exception:
                    # A close failure cannot replace the status with raw content.
                    pass
            self._fail(category, f"Upstox market-data request failed (HTTP {code}).",
                       http_status=code, provider_detail=detail)
        except BrokerDataError:
            raise
        except (ValueError, UnicodeError):
            self._fail("MALFORMED_RESPONSE", "Upstox returned invalid JSON or encoding.")
        except (TimeoutError, urllib.error.URLError, OSError):
            self._fail("NETWORK_API_FAILURE", "Upstox market-data request timed out or could not be completed.")
        except Exception:
            self._fail("NETWORK_API_FAILURE", "Upstox market-data request could not be completed.")
        if not isinstance(raw, dict) or raw.get("status") != "success" or not isinstance(raw.get("data"), (dict, list)):
            self._fail("PROVIDER_ERROR", "Upstox returned an unsuccessful or malformed response envelope.")
        # A successful authorized read proves endpoint access, never historical readiness.
        self.authenticated_at_ist = format_ist_timestamp(self.clock())
        self._authorized_token_sha256 = token_sha
        self._authorized_reads += 1
        return raw

    @_safe_upstox_read
    def get_quote(self, symbol_or_meta, mode="FULL"):
        """Official V2 full quote: /market-quote/quotes, instrument_key query parameter.

        Reference: https://upstox.com/developer/api-documentation/get-full-market-quote/
        No profile, OAuth exchange or trading call is performed.
        """
        if str(mode).upper() not in ("FULL", "OHLC", "LTP"):
            self._fail("INVALID_REQUEST", "Unsupported Upstox quote mode.")
        if isinstance(symbol_or_meta, str):
            symbol = identity_checked(canonical_symbol, symbol_or_meta)
            pinned = INDICES.get(symbol) or EQUITIES.get(symbol)
            if not pinned:
                self._fail("INVALID_INSTRUMENT_IDENTITY", "Unknown Upstox quote instrument.")
            symbol_or_meta = dict(pinned, symbol=symbol)
        meta = validate_symbol_meta(symbol_or_meta, "upstox")
        identity = meta["instrument_identity"]
        raw = self._request_json("/market-quote/quotes", {"instrument_key": identity["identifier"]})
        data = raw["data"]
        if not isinstance(data, dict) or len(data) != 1:
            self._fail("INVALID_RESPONSE", "Upstox quote must contain exactly one requested instrument.")
        map_key, item = next(iter(data.items()))
        if not isinstance(item, dict):
            self._fail("INVALID_RESPONSE", "Upstox quote entry must be an object.")
        # V2 uses exchange:symbol map keys, not instrument keys. Inspect both forms.
        if map_key != identity["identifier"]:
            prefix, separator, label = map_key.partition(":")
            if (not separator or prefix != ("NSE_INDEX" if identity["is_index"] else "NSE_EQ")
                    or identity_checked(canonical_symbol, label) != identity["symbol"]):
                self._fail("INVALID_INSTRUMENT_IDENTITY", "Upstox quote map key conflicts with the requested instrument.")
        echoed = identity_checked(check_echo, raw, identity) or False
        echoed = identity_checked(check_echo, item, identity) or echoed

        def number(value, positive=True):
            if isinstance(value, bool) or value is None:
                self._fail("INVALID_RESPONSE", "Upstox quote has a missing or invalid numeric field.")
            try:
                result = float(value)
            except (ValueError, TypeError, OverflowError):
                self._fail("INVALID_RESPONSE", "Upstox quote has a non-numeric field.")
            if not math.isfinite(result) or (result <= 0 if positive else result < 0):
                self._fail("INVALID_RESPONSE", "Upstox quote has a non-finite or out-of-range numeric field.")
            return result

        ltp = number(item.get("last_price"))
        ohlc = item.get("ohlc")
        if not isinstance(ohlc, dict):
            self._fail("INVALID_RESPONSE", "Upstox full quote is missing OHLC.")
        prices = {key: number(ohlc.get(key)) for key in ("open", "high", "low", "close")}
        # Previous close may be outside today's range; do not compare it with high/low.
        if not prices["low"] <= prices["open"] <= prices["high"] or not prices["low"] <= ltp <= prices["high"]:
            self._fail("INVALID_RESPONSE", "Upstox quote violates session price relationships.")
        timestamps = {}
        for field in ("timestamp", "last_trade_time"):
            if field in item:
                ts = _explicit_candle_timestamp(item[field])
                if ts > parse_ist_timestamp(self.clock()) + timedelta(seconds=self.config.live_candle_future_skew_seconds):
                    self._fail("INVALID_RESPONSE", "Upstox quote timestamp is in the future.")
                timestamps[field] = format_ist_timestamp(ts)
        quote = dict(symbol=identity["symbol"], provider="upstox", exchange=identity["exchange"],
            symbol_token=identity["identifier"], ltp=ltp, **prices, is_simulated=False, data_mode="LIVE",
            instrument_identity=dict(identity, response_binding="ECHO_CHECKED" if echoed else "REQUEST_BOUND_NO_ECHO"),
            quote_timestamp_ist=timestamps.get("timestamp"), last_trade_timestamp_ist=timestamps.get("last_trade_time"),
            timestamp_evidence="PROVIDER_TIMESTAMP" if timestamps.get("timestamp") else "NOT_SUPPLIED")
        if "volume" in item:
            quote["volume"] = number(item["volume"], positive=False)
        self.last_market_data_at_ist = format_ist_timestamp(self.clock())
        self.last_error_category, self.last_error_message = "NONE", None
        return quote

    @_safe_upstox_read
    def get_intraday_candles(
        self,
        symbol_meta: Dict[str, Any],
        interval_min: int = 5,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._validate_credentials()
        validated_meta = validate_symbol_meta(symbol_meta, "upstox")
        if not isinstance(interval_min, int) or isinstance(interval_min, bool) or interval_min not in self.SUPPORTED_INTERVALS:
            raise BrokerDataError(
                f"Unsupported Upstox intraday interval '{interval_min}'. "
                f"Supported minute intervals: {list(self.SUPPORTED_INTERVALS)}."
            )

        inst_key = urllib.parse.quote(validated_meta["upstox_key"], safe="")
        source_interval_min = 30 if interval_min == 30 else 1
        upstox_interval_str = "30minute" if source_interval_min == 30 else "1minute"
        raw = self._request_json(f"/historical-candle/intraday/{inst_key}/{upstox_interval_str}")

        if not isinstance(raw, dict) or raw.get("status") != "success":
            raise BrokerDataError("Upstox intraday candle response returned unsuccessful status.")
        candles_raw = (raw.get("data") or {}).get("candles")
        if not isinstance(candles_raw, list) or not candles_raw:
            raise BrokerDataError(f"Upstox returned empty intraday candles for {validated_meta['symbol']}.")

        now_ist = parse_ist_timestamp(self.clock())
        parsed = []
        for idx, c in enumerate(candles_raw):
            if not isinstance(c, (list, tuple)) or len(c) < 6:
                raise BrokerDataError(f"Upstox candle row {idx} has fewer than 6 elements.")
            parsed.append({
                "timestamp": c[0],
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4],
                "volume": c[5],
                "is_simulated": False,
            })

        parsed = identity_checked(bind_candles, parsed, validated_meta["instrument_identity"], raw)
        # Upstox wire order is explicitly newest-first. Validate before reversing;
        # sorting/deduplication must not conceal malformed source data or missing components.
        normalized_source, source_report = assess_live_candle_batch(
            parsed, source_interval_min, now_ist, self.config.configured_holidays,
            self.config.session_start_ist, self.config.session_end_ist,
            self.config.live_candle_max_delay_seconds, self.config.live_candle_future_skew_seconds,
            provider="upstox", symbol=validated_meta["symbol"], reverse_chronological=True)
        if not source_report["batch_valid"]:
            self.last_candle_freshness = source_report
            error = CandleFreshnessError(source_report)
            self.last_error_category, self.last_error_message = error.error_category, str(error)
            raise error
        if interval_min in (1, 30):
            candles = normalized_source
        else:
            candles = aggregate_intraday_candles(normalized_source, target_interval_min=interval_min,
                                                  source_interval_min=1, now=now_ist)
        candles = identity_checked(bind_candles, candles, validated_meta["instrument_identity"], raw)
        return enforce_live_candle_batch(self, candles, validated_meta, interval_min, "upstox", normalized_ist=True)

    @_safe_upstox_read
    def get_expiry_list(self, index_symbol: str) -> List[str]:
        self._validate_credentials()
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS or sym not in self.config.fo_indices:
            raise BrokerDataError(f"Unsupported F&O index symbol '{index_symbol}' for Upstox option contracts.")
        idx_meta = validate_symbol_meta(dict(self.config.fo_indices[sym], symbol=sym), "upstox")
        raw = self._request_json("/option/contract", {"instrument_key": idx_meta["upstox_key"]})

        if not isinstance(raw, dict) or raw.get("status") != "success":
            raise BrokerDataError("Upstox option contract response returned unsuccessful status.")
        contracts = raw.get("data")
        if not isinstance(contracts, list) or not contracts:
            raise BrokerDataError(f"Upstox returned empty option contract list for {sym}.")

        expiry_strings = []
        for c in contracts:
            if isinstance(c, dict) and "expiry" in c:
                expiry_strings.append(c["expiry"])
        now_ist = parse_ist_timestamp(self.clock())
        _, session_date = resolve_nse_session_dates(now_ist, warmup_sessions=0)
        nearest = _parse_and_select_expiry(expiry_strings, session_date, self.name)
        unique_valid = sorted({
            s.strip()
            for s in expiry_strings
            if isinstance(s, str) and datetime.strptime(s.strip(), "%Y-%m-%d").date() >= session_date
        })
        return unique_valid if unique_valid else [nearest]

    @_safe_upstox_read
    def get_option_chain(
        self,
        index_symbol: str,
        bias: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._validate_credentials()
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS or sym not in self.config.fo_indices:
            raise BrokerDataError(f"Unsupported F&O index symbol '{index_symbol}' for Upstox option chain.")
        idx_meta = validate_symbol_meta(dict(self.config.fo_indices[sym], symbol=sym), "upstox")

        selected_expiry = expiry
        if not selected_expiry:
            selected_expiry = self.get_expiry_list(sym)[0]
        else:
            try:
                datetime.strptime(selected_expiry, "%Y-%m-%d")
            except ValueError as exc:
                raise BrokerDataError(f"Invalid Upstox expiry_date '{selected_expiry}'. Expected YYYY-MM-DD.") from exc

        if selected_expiry < parse_ist_timestamp(self.clock()).date().isoformat():
            raise BrokerIdentityError(dict(reason_code="EXPIRED_CONTRACT", reason="Requested option expiry is in the past."))
        query = {
            "instrument_key": idx_meta["upstox_key"],
            "expiry_date": selected_expiry,
        }
        raw = self._request_json("/option/chain", query)

        return self._normalize_option_chain_response(sym, selected_expiry, raw)

    @_safe_upstox_read
    def _normalize_option_chain_response(
        self,
        index_symbol: str,
        expiry: str,
        raw: Dict[str, Any],
    ) -> Dict[str, Any]:
        requested = validate_symbol_meta(dict(self.config.fo_indices[index_symbol], symbol=index_symbol), "upstox")["instrument_identity"]
        identity_checked(check_chain_metadata, raw, index_symbol, expiry, "upstox", requested["identifier"])
        if not isinstance(raw, dict) or raw.get("status") != "success":
            raise BrokerDataError("Upstox option chain response returned unsuccessful status.")
        rows = raw.get("data")
        if not isinstance(rows, list) or not rows:
            raise BrokerDataError("Upstox option chain response contains an empty 'data' list.")

        spot: Optional[float] = None
        strikes: List[Dict[str, Any]] = []
        total_ce_oi = 0
        total_pe_oi = 0

        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                raise BrokerDataError(f"Upstox option chain row {idx} is not a dict.")
            identity_checked(check_chain_metadata, row, index_symbol, expiry, "upstox", requested["identifier"])
            if "underlying_spot_price" not in row or row["underlying_spot_price"] is None:
                raise BrokerDataError(f"Upstox option chain row {idx} missing 'underlying_spot_price'.")
            row_spot = float(row["underlying_spot_price"])
            if not math.isfinite(row_spot) or row_spot <= 0:
                raise BrokerDataError(f"Upstox option chain row {idx} has invalid underlying_spot_price.")
            spot = row_spot

            if "strike_price" not in row or row["strike_price"] is None:
                raise BrokerDataError(f"Upstox option chain row {idx} missing 'strike_price'.")
            strike_val = float(row["strike_price"])
            if not math.isfinite(strike_val) or strike_val <= 0:
                raise BrokerDataError(f"Upstox option chain row {idx} has invalid strike_price.")
            strike_int = int(round(strike_val)) if abs(strike_val - round(strike_val)) < 1e-4 else strike_val

            ce_obj = row.get("call_options")
            pe_obj = row.get("put_options")
            if not isinstance(ce_obj, dict) or not isinstance(pe_obj, dict):
                raise BrokerDataError(f"Upstox option chain strike {strike_int} missing 'call_options' or 'put_options'.")
            for side, leg in (("CE", ce_obj), ("PE", pe_obj)):
                identity_checked(check_chain_metadata, leg, index_symbol, expiry, "upstox", requested["identifier"], strike_int, side)
            ce_md = ce_obj.get("market_data")
            pe_md = pe_obj.get("market_data")
            if not isinstance(ce_md, dict) or not isinstance(pe_md, dict):
                raise BrokerDataError(f"Upstox option chain strike {strike_int} missing Call/Put 'market_data'.")

            for leg_name, md in (("call_options", ce_md), ("put_options", pe_md)):
                for req_field in ("ltp", "oi", "prev_oi"):
                    if req_field not in md or md[req_field] is None or isinstance(md[req_field], bool):
                        raise BrokerDataError(
                            f"Upstox option chain strike {strike_int} {leg_name}.market_data missing '{req_field}'."
                        )

            try:
                ce_ltp = float(ce_md["ltp"])
                ce_oi = int(ce_md["oi"])
                ce_prev_oi = int(ce_md["prev_oi"])
                ce_iv = float((ce_obj.get("option_greeks") or {}).get("iv", 0.0) or 0.0)

                pe_ltp = float(pe_md["ltp"])
                pe_oi = int(pe_md["oi"])
                pe_prev_oi = int(pe_md["prev_oi"])
                pe_iv = float((pe_obj.get("option_greeks") or {}).get("iv", 0.0) or 0.0)
            except (TypeError, ValueError) as exc:
                raise BrokerDataError(f"Upstox option chain strike {strike_int} has non-numeric market_data.") from exc

            if not (math.isfinite(ce_ltp) and math.isfinite(pe_ltp) and ce_ltp >= 0 and pe_ltp >= 0):
                raise BrokerDataError(f"Upstox option chain strike {strike_int} has invalid LTP.")
            if ce_oi < 0 or pe_oi < 0 or ce_prev_oi < 0 or pe_prev_oi < 0:
                raise BrokerDataError(f"Upstox option chain strike {strike_int} has negative OI.")

            ce_oi_change = ce_oi - ce_prev_oi
            pe_oi_change = pe_oi - pe_prev_oi
            total_ce_oi += ce_oi
            total_pe_oi += pe_oi

            strikes.append({
                "strike": strike_int,
                "ce_ltp": round(ce_ltp, 2),
                "ce_oi": ce_oi,
                "ce_prev_oi": ce_prev_oi,
                "ce_oi_change": ce_oi_change,
                "ce_iv": round(ce_iv, 2),
                "pe_ltp": round(pe_ltp, 2),
                "pe_oi": pe_oi,
                "pe_prev_oi": pe_prev_oi,
                "pe_oi_change": pe_oi_change,
                "pe_iv": round(pe_iv, 2),
            })

        assert spot is not None
        strikes.sort(key=lambda s: float(s["strike"]))
        if total_ce_oi <= 0:
            raise BrokerDataError("Upstox option chain total Call OI is zero; cannot calculate valid PCR.")

        atm_strike = min(strikes, key=lambda s: abs(float(s["strike"]) - spot))["strike"]
        pcr = round(total_pe_oi / total_ce_oi, 2)
        return {
            "index": index_symbol,
            "expiry": expiry,
            "spot": round(spot, 2),
            "atm_strike": atm_strike,
            "pcr": pcr,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "oi_change_measure": "net_change_from_previous_day_close",
            "strikes": strikes,
            "is_simulated": False,
            "data_mode": "LIVE",
        }


class SimulatedNSEAdapter(BaseBrokerAdapter):
    """
    Deterministic NSE Equity + Nifty 50 / Bank Nifty F&O simulator for offline testing,
    regression testing, and explicit paper simulation mode (`ACTIVE_BROKER=paper_sim`).
    Derives current session date and preceding weekday warm-up dates dynamically from
    the injected `clock` in Asia/Kolkata (never hardcoding historical dates).
    Supports both Bullish and Bearish deterministic strategy fixture patterns.
    """
    name = "NSE Live Simulation / Paper Engine (SIMULATED)"
    is_simulated = True
    SUPPORTED_INTERVALS = (1, 5, 15, 30)

    BASE_PRICES = {
        "NIFTY": 24820.0,
        "BANKNIFTY": 52450.0,
        "RELIANCE": 2945.0,
        "HDFCBANK": 1742.0,
        "ICICIBANK": 1288.0,
        "INFY": 1915.0,
        "TCS": 4180.0,
        "SBIN": 832.0,
        "BAJFINANCE": 7420.0,
        "LT": 3690.0,
        "TATAMOTORS": 965.0,
        "AXISBANK": 1198.0,
        "M&M": 3040.0,
        "BHARTIARTL": 1685.0,
        "TRENT": 7680.0,
        "HAL": 4560.0,
        "TATASTEEL": 158.0,
    }

    def __init__(self, seed: int = 42, clock: Optional[Callable[[], datetime]] = None):
        self.seed = int(seed)
        self.clock = clock or (lambda: datetime.now(IST))

    def _deterministic_rng(self, *parts: Any) -> random.Random:
        material = ":".join(str(p) for p in (self.seed, *parts)).encode("utf-8")
        digest_int = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        return random.Random(digest_int)

    @staticmethod
    def _build_session_timestamps(
        warmup_days: List[date],
        session_day: date,
        interval_min: int = 5,
        session_bars: int = 16,
    ) -> List[datetime]:
        bars_per_day = (6 * 60 + 15) // interval_min
        timestamps: List[datetime] = []
        for d in warmup_days:
            day_open = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
            for b in range(bars_per_day):
                timestamps.append(day_open + timedelta(minutes=b * interval_min))
        curr_open = datetime(session_day.year, session_day.month, session_day.day, 9, 15, tzinfo=IST)
        for b in range(session_bars):
            timestamps.append(curr_open + timedelta(minutes=b * interval_min))
        return timestamps

    def get_intraday_candles(
        self,
        symbol_meta: Dict[str, Any],
        interval_min: int = 5,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        validated_meta = validate_symbol_meta(symbol_meta, "paper_sim")
        if not isinstance(interval_min, int) or isinstance(interval_min, bool) or interval_min not in self.SUPPORTED_INTERVALS:
            raise BrokerDataError(
                f"Unsupported SimulatedNSEAdapter interval '{interval_min}'. "
                f"Supported minute intervals: {list(self.SUPPORTED_INTERVALS)}."
            )
        symbol = validated_meta["symbol"]
        base = float(symbol_meta.get("base_price") or self.BASE_PRICES[symbol])
        rng = self._deterministic_rng(symbol, interval_min, pattern or "natural")

        now_ist = parse_ist_timestamp(self.clock())
        warmup_days, session_day = resolve_nse_session_dates(now_ist, warmup_sessions=3)
        session_bars = 16  # 16 bars from 09:15 IST (09:15 to 10:30 IST for 5m bars)
        timestamps = self._build_session_timestamps(warmup_days, session_day, interval_min, session_bars)
        warmup_count = len(timestamps) - session_bars

        candles: List[Dict[str, Any]] = []
        price = base

        # 1. Generate continuous warm-up bars with zero-mean symmetric drift
        for i in range(warmup_count):
            bar_dt = timestamps[i]
            step_pct = rng.uniform(-0.0012, 0.0012)
            vol = int(rng.uniform(50000, 85000))
            o = round(price, 2)
            c = round(max(1.0, o * (1.0 + step_pct)), 2)
            hi_wick = rng.uniform(0.0004, 0.0011)
            lo_wick = rng.uniform(0.0004, 0.0011)
            h = round(max(o, c) * (1.0 + hi_wick), 2)
            l = round(min(o, c) * (1.0 - lo_wick), 2)
            h = max(h, o, c)
            l = min(l, o, c)
            price = c
            candles.append({
                "timestamp": bar_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
                "is_complete": True,
                "is_simulated": True,
            })

        anchor = price

        # 2. Generate current session bars anchored continuously to the final warm-up close
        for session_idx in range(session_bars):
            bar_dt = timestamps[warmup_count + session_idx]
            o = round(price, 2)

            if pattern is None:
                regime_bias = ((int.from_bytes(hashlib.sha256(symbol.encode("utf-8")).digest()[:2], "big") % 5) - 1) * 0.0004
                wave = math.sin(session_idx * 0.55) * 0.0014
                step_pct = regime_bias + wave + rng.uniform(-0.0012, 0.0014)
                c = round(max(1.0, o * (1.0 + step_pct)), 2)
                hi_ext = rng.uniform(0.0004, 0.0014)
                lo_ext = rng.uniform(0.0004, 0.0022)
                h = round(max(o, c) * (1.0 + hi_ext), 2)
                l = round(min(o, c) * (1.0 - lo_ext), 2)
                vol_mult = 1.65 if session_idx in (3, 7, 11, 15) and step_pct > 0 else 1.0
                vol = int(rng.uniform(52000, 88000) * vol_mult)

            elif pattern == "order_block_bull":
                if session_idx < 6:
                    c = round(anchor * (1.0002 + session_idx * 0.0002), 2)
                    h = round(max(o, c) * 1.0006, 2)
                    l = round(min(o, c) * 0.9994, 2)
                    vol = 68000
                elif session_idx == 6:
                    o = round(anchor * 1.0012, 2)
                    c = round(anchor * 0.9985, 2)
                    h = round(anchor * 1.0016, 2)
                    l = round(anchor * 0.9980, 2)
                    vol = 135000
                elif session_idx == 7:
                    o = round(anchor * 0.9986, 2)
                    c = round(anchor * 1.0052, 2)
                    h = round(anchor * 1.0058, 2)
                    l = round(anchor * 0.9984, 2)
                    vol = 235000
                elif session_idx == 8:
                    o = round(anchor * 1.0053, 2)
                    c = round(anchor * 1.0092, 2)
                    h = round(anchor * 1.0098, 2)
                    l = round(anchor * 1.0035, 2)
                    vol = 210000
                elif 9 <= session_idx <= 14:
                    frac = (session_idx - 8) / 6.0
                    c = round(anchor * (1.0092 - frac * 0.0048), 2)
                    h = round(max(o, c) * 1.0005, 2)
                    l = round(min(o, c) * 0.9998, 2)
                    vol = 62000
                else:
                    l = round(anchor * 0.9995, 2)
                    c = round(anchor * 1.0035, 2)
                    h = round(anchor * 1.0040, 2)
                    vol = 185000

            elif pattern == "order_block_bear":
                if session_idx < 6:
                    c = round(anchor * (0.9998 - session_idx * 0.0002), 2)
                    h = round(max(o, c) * 1.0006, 2)
                    l = round(min(o, c) * 0.9994, 2)
                    vol = 68000
                elif session_idx == 6:
                    o = round(anchor * 0.9988, 2)
                    c = round(anchor * 1.0015, 2)
                    h = round(anchor * 1.0020, 2)
                    l = round(anchor * 0.9984, 2)
                    vol = 135000
                elif session_idx == 7:
                    o = round(anchor * 1.0014, 2)
                    c = round(anchor * 0.9948, 2)
                    h = round(anchor * 1.0016, 2)
                    l = round(anchor * 0.9942, 2)
                    vol = 235000
                elif session_idx == 8:
                    o = round(anchor * 0.9947, 2)
                    c = round(anchor * 0.9908, 2)
                    h = round(anchor * 0.9965, 2)
                    l = round(anchor * 0.9902, 2)
                    vol = 210000
                elif 9 <= session_idx <= 14:
                    frac = (session_idx - 8) / 6.0
                    c = round(anchor * (0.9908 + frac * 0.0056), 2)
                    h = round(max(o, c) * 1.0002, 2)
                    l = round(min(o, c) * 0.9995, 2)
                    vol = 62000
                else:
                    h = round(anchor * 1.0005, 2)
                    c = round(anchor * 0.9950, 2)
                    l = round(anchor * 0.9945, 2)
                    vol = 185000

            elif pattern == "vwap_pullback_bull":
                if session_idx < 12:
                    c = round(anchor * (1.0010 + session_idx * 0.0006), 2)
                    h = round(max(o, c) * 1.0006, 2)
                    l = round(min(o, c) * 0.9995, 2)
                    vol = 76000
                elif session_idx in (12, 13, 14):
                    c = round(o * 0.9986, 2)
                    h = round(max(o, c) * 1.0003, 2)
                    l = round(min(o, c) * 0.9994, 2)
                    vol = 52000
                else:
                    l = round(anchor * 1.0032, 2)
                    c = round(anchor * 1.0078, 2)
                    h = round(anchor * 1.0084, 2)
                    vol = 168000

            elif pattern == "vwap_pullback_bear":
                if session_idx < 12:
                    c = round(anchor * (0.9990 - session_idx * 0.0006), 2)
                    h = round(max(o, c) * 1.0005, 2)
                    l = round(min(o, c) * 0.9994, 2)
                    vol = 76000
                elif session_idx in (12, 13, 14):
                    c = round(o * 1.0014, 2)
                    h = round(max(o, c) * 1.0006, 2)
                    l = round(min(o, c) * 0.9997, 2)
                    vol = 52000
                else:
                    h = round(anchor * 0.9968, 2)
                    c = round(anchor * 0.9922, 2)
                    l = round(anchor * 0.9916, 2)
                    vol = 168000

            elif pattern == "orb_breakout_bull":
                if session_idx in (0, 1, 2):
                    c = round(anchor * (1.0005 + session_idx * 0.0006), 2)
                    h = round(anchor * 1.0032, 2)
                    l = round(anchor * 0.9970, 2)
                    vol = 90000
                elif 3 <= session_idx <= 14:
                    c = round(anchor * (1.0010 + (session_idx % 3) * 0.0005), 2)
                    h = round(min(anchor * 1.0030, max(o, c) * 1.0004), 2)
                    l = round(min(o, c) * 0.9992, 2)
                    vol = 68000
                else:
                    l = round(min(o, anchor * 1.0018), 2)
                    c = round(anchor * 1.0072, 2)
                    h = round(anchor * 1.0078, 2)
                    vol = 195000

            elif pattern == "orb_breakout_bear":
                if session_idx in (0, 1, 2):
                    c = round(anchor * (0.9995 - session_idx * 0.0006), 2)
                    h = round(anchor * 1.0030, 2)
                    l = round(anchor * 0.9968, 2)
                    vol = 90000
                elif 3 <= session_idx <= 14:
                    c = round(anchor * (0.9990 - (session_idx % 3) * 0.0005), 2)
                    h = round(max(o, c) * 1.0008, 2)
                    l = round(max(anchor * 0.9970, min(o, c) * 0.9996), 2)
                    vol = 68000
                else:
                    h = round(max(o, anchor * 0.9982), 2)
                    c = round(anchor * 0.9928, 2)
                    l = round(anchor * 0.9922, 2)
                    vol = 195000

            elif pattern == "supertrend_pullback_bull":
                if session_idx < 13:
                    c = round(anchor * (1.0020 + session_idx * 0.0008), 2)
                    h = round(max(o, c) * 1.0007, 2)
                    l = round(min(o, c) * 0.9994, 2)
                    vol = 74000
                elif session_idx in (13, 14):
                    c = round(o * 0.9984, 2)
                    h = round(max(o, c) * 1.0004, 2)
                    l = round(min(o, c) * 0.9992, 2)
                    vol = 60000
                else:
                    l = round(anchor * 1.0058, 2)
                    c = round(anchor * 1.0125, 2)
                    h = round(anchor * 1.0132, 2)
                    vol = 162000

            elif pattern == "supertrend_pullback_bear":
                if session_idx < 13:
                    c = round(anchor * (0.9980 - session_idx * 0.0008), 2)
                    h = round(max(o, c) * 1.0006, 2)
                    l = round(min(o, c) * 0.9993, 2)
                    vol = 74000
                elif session_idx in (13, 14):
                    c = round(o * 1.0016, 2)
                    h = round(max(o, c) * 1.0008, 2)
                    l = round(min(o, c) * 0.9996, 2)
                    vol = 60000
                else:
                    h = round(anchor * 0.9942, 2)
                    c = round(anchor * 0.9875, 2)
                    l = round(anchor * 0.9868, 2)
                    vol = 162000

            else:
                raise ValueError(f"Unsupported simulation fixture pattern: {pattern!r}")

            h = max(h, o, c)
            l = min(l, o, c)
            price = c
            candles.append({
                "timestamp": bar_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
                "is_complete": True,
                "is_simulated": True,
            })

        return validate_candles(candles, deduplicate=True, default_is_simulated=True)

    def get_option_chain(
        self,
        index_symbol: str,
        bias: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        sym = str(index_symbol or "").strip().upper()
        if sym not in INDEX_SYMBOLS:
            raise BrokerDataError(f"Option chain is restricted to {INDEX_SYMBOLS}, got '{index_symbol}'.")
        spot = float(self.BASE_PRICES[sym])
        step = 50 if sym == "NIFTY" else 100
        atm = int(round(spot / step) * step)
        rng = self._deterministic_rng("option_chain", sym, bias or "natural")
        now_ist = parse_ist_timestamp(self.clock())
        _, session_date = resolve_nse_session_dates(now_ist, warmup_sessions=0)
        resolved_expiry = expiry or session_date.strftime("%Y-%m-%d")

        strikes = []
        total_pe_oi = 0
        total_ce_oi = 0

        for offset in range(-4, 5):
            k = atm + offset * step
            if bias == "BULLISH":
                ce_oi = 1850000 if offset <= 0 else 2600000
                ce_chg = -420000 if offset in (0, 1) else 110000
                pe_oi = 3400000 if offset <= 0 else 1400000
                pe_chg = 680000 if offset in (-1, 0) else 95000
            elif bias == "BEARISH":
                ce_oi = 3500000 if offset >= 0 else 1500000
                ce_chg = 710000 if offset in (0, 1) else 90000
                pe_oi = 1750000 if offset >= 0 else 2400000
                pe_chg = -460000 if offset in (-1, 0) else 85000
            else:
                ce_oi = int(rng.uniform(1400000, 2800000))
                pe_oi = int(rng.uniform(1400000, 2800000))
                ce_chg = int(rng.uniform(-180000, 220000))
                pe_chg = int(rng.uniform(-180000, 220000))

            total_ce_oi += ce_oi
            total_pe_oi += pe_oi
            intrinsic_ce = max(0.0, spot - k)
            intrinsic_pe = max(0.0, k - spot)
            time_val = (115.0 if sym == "NIFTY" else 260.0) * math.exp(-abs(offset) * 0.35)
            strikes.append({
                "strike": k,
                "ce_ltp": round(intrinsic_ce + time_val, 2),
                "ce_oi": ce_oi,
                "ce_prev_oi": ce_oi - ce_chg,
                "ce_oi_change": ce_chg,
                "ce_iv": round(12.4 + abs(offset) * 0.4, 2),
                "pe_ltp": round(intrinsic_pe + time_val, 2),
                "pe_oi": pe_oi,
                "pe_prev_oi": pe_oi - pe_chg,
                "pe_oi_change": pe_chg,
                "pe_iv": round(13.1 + abs(offset) * 0.45, 2),
            })
        pcr = round(total_pe_oi / max(1, total_ce_oi), 2)
        return {
            "index": sym,
            "expiry": resolved_expiry,
            "spot": spot,
            "atm_strike": atm,
            "pcr": pcr,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "oi_change_measure": "simulated_session_oi_change",
            "strikes": strikes,
            "is_simulated": True,
            "data_mode": "SIMULATED",
        }


class MultiBrokerScanner:
    """
    Unified Multi-Broker manager supporting Angel One SmartAPI, DhanHQ v2, and Upstox v2,
    plus explicit paper simulation mode (`ACTIVE_BROKER=paper_sim`).
    Does NOT silently fall back to simulated data when a live broker is configured and fails.
    """
    def __init__(
        self,
        config: BotConfig,
        clock: Optional[Callable[[], datetime]] = None,
        persistence_store: Optional[Any] = None,
    ):
        self.config = config
        self.clock = clock
        self.persistence_store = persistence_store
        self.sim = SimulatedNSEAdapter(clock=clock)
        self.adapters: Dict[str, BaseBrokerAdapter] = {
            "angelone": AngelOneSmartAPIAdapter(config, clock=clock, persistence_store=persistence_store),
            "dhan": DhanHQAdapter(config, clock=clock),
            "upstox": UpstoxV2Adapter(config, clock=clock),
            "paper_sim": self.sim,
            "simulated": self.sim,
            "sim": self.sim,
        }

    def attach_persistence_store(self, store: Optional[Any]) -> None:
        self.persistence_store = store
        angel_adapter = self.adapters.get("angelone")
        if isinstance(angel_adapter, AngelOneSmartAPIAdapter):
            angel_adapter.attach_persistence_store(store)

    def get_active_adapter(self) -> BaseBrokerAdapter:
        key = (self.config.active_broker or "").strip().lower()
        if key not in self.adapters:
            raise BrokerDataError(
                f"Unsupported active_broker '{self.config.active_broker}'. "
                f"Expected one of: {', '.join(LIVE_BROKER_KEYS + ('paper_sim',))}."
            )
        return self.adapters[key]

    def fetch_candles(
        self,
        symbol_meta: Dict[str, Any],
        interval_min: int = 5,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        adapter = self.get_active_adapter()
        if adapter.is_simulated:
            return adapter.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern=pattern)
        try:
            provider = str(self.config.active_broker).strip().lower()
            meta = (adapter.resolve_instrument(symbol_meta) if provider == "angelone"
                    else validate_symbol_meta(symbol_meta, provider))
            candles = adapter.get_intraday_candles(symbol_meta, interval_min=interval_min)
            candles = identity_checked(bind_candles, candles, meta["instrument_identity"])
            normalized_ist = bool(candles) and all(
                isinstance(c, dict) and c.get("timestamp_timezone") == "Asia/Kolkata" for c in candles)
            return enforce_live_candle_batch(adapter, candles, symbol_meta, interval_min,
                                             str(self.config.active_broker).strip().lower(),
                                             normalized_ist=normalized_ist, context="SCANNER")
        except BrokerDataError:
            raise
        except Exception as exc:
            symbol = symbol_meta.get("symbol", "UNKNOWN") if isinstance(symbol_meta, dict) else "UNKNOWN"
            raise BrokerDataError(
                f"Live broker '{adapter.name}' failed to fetch candles for {symbol} ({type(exc).__name__})."
            ) from exc

    def fetch_option_chain(
        self,
        index_symbol: str,
        bias: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        adapter = self.get_active_adapter()
        kwargs = {"bias": bias}
        if expiry is not None:
            kwargs["expiry"] = expiry
        if adapter.is_simulated:
            return adapter.get_option_chain(index_symbol, **kwargs)
        try:
            return adapter.get_option_chain(index_symbol, **kwargs)
        except BrokerDataError:
            raise
        except Exception as exc:
            raise BrokerDataError(
                f"Live broker '{adapter.name}' failed to fetch option chain for {index_symbol} ({type(exc).__name__})."
            ) from exc

    def fetch_quote(self, symbol_or_meta: Any, mode: str = "FULL") -> Dict[str, Any]:
        adapter = self.get_active_adapter()
        if not hasattr(adapter, "get_quote"):
            raise UnsupportedBrokerCapabilityError(
                f"Active broker '{adapter.name}' does not implement single-instrument market quote retrieval."
            )
        try:
            return adapter.get_quote(symbol_or_meta, mode=mode)
        except BrokerDataError:
            raise
        except Exception as exc:
            raise BrokerDataError(
                f"Broker '{adapter.name}' failed to fetch quote ({type(exc).__name__})."
            ) from exc

