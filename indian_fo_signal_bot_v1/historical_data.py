import atexit
import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from config import BotConfig
from brokers import (
    INDEX_SYMBOLS,
    BrokerDataError,
    _redact_secrets,
    validate_symbol_meta,
)
from scanner_engine import safe_console_print
from storage import (
    PersistenceError,
    PersistenceValidationError,
    SQLitePersistenceStore,
    is_nse_trading_day,
)
from strategies import (
    IST,
    NSE_CLOSE_TIME,
    NSE_OPEN_TIME,
    format_ist_timestamp,
    parse_ist_timestamp,
)


class HistoricalDataError(RuntimeError):
    """Raised when a historical dataset operation or look-ahead guard fails."""


class HistoricalDataValidationError(ValueError):
    """Raised when historical OHLCV bars or provenance metadata fail quality validation."""


class LookAheadBiasError(HistoricalDataError):
    """Raised when a backtest slice contains forming or future candles after decision_time_ist."""


SUPPORTED_HISTORICAL_INTERVALS_MIN: Tuple[int, ...] = (1, 3, 5, 10, 15, 30, 60)

# Canonical specification of genuine historical inputs required by each of the 5 strategies
STRATEGY_HISTORICAL_DATA_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "strat_1_order_block": {
        "strategy_id": "strat_1_order_block",
        "strategy_name": "Order Block + BOS & FVG Retest",
        "target_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "required_interval_min": 5,
        "min_completed_bars": 30,
        "recommended_warmup_sessions": 1,
        "requires_positive_volume": True,
        "requires_opening_range_0915_0930": False,
        "requires_historical_option_chain": False,
        "requires_prior_session_closing_oi": False,
        "required_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "optional_context": ["market_breadth", "mitigated_order_blocks"],
        "historical_limitations": (
            "Requires chronological 5m OHLCV bars with zero look-ahead and point-in-time tracking "
            "of mitigated Order Block zones."
        ),
    },
    "strat_2_vwap_pullback": {
        "strategy_id": "strat_2_vwap_pullback",
        "strategy_name": "Institutional VWAP Pullback",
        "target_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "required_interval_min": 5,
        "min_completed_bars": 35,
        "recommended_warmup_sessions": 1,
        "requires_positive_volume": True,
        "requires_opening_range_0915_0930": False,
        "requires_historical_option_chain": False,
        "requires_prior_session_closing_oi": False,
        "required_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "optional_context": ["market_breadth"],
        "historical_limitations": (
            "Session VWAP resets at 09:15 IST and weights typical price by bar volume; "
            "NSE spot indices (NIFTY 99926000, BANKNIFTY 99926009) often report volume=0 on "
            "cash-index feeds, which blocks volume-weighted VWAP and 1.4x RVOL checks unless "
            "volume-bearing futures/index bars are used."
        ),
    },
    "strat_3_option_apex_oi": {
        "strategy_id": "strat_3_option_apex_oi",
        "strategy_name": "Option Apex OI Shift + PCR",
        "target_segments": ["NSE_FO_INDEX"],
        "allowed_symbols": ["NIFTY", "BANKNIFTY"],
        "required_interval_min": 5,
        "min_completed_bars": 30,
        "recommended_warmup_sessions": 1,
        "requires_positive_volume": False,
        "requires_opening_range_0915_0930": False,
        "requires_historical_option_chain": True,
        "requires_prior_session_closing_oi": True,
        "required_fields": [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "option_chain.expiry",
            "option_chain.atm_strike",
            "option_chain.pcr",
            "option_chain.strikes[].ce_ltp",
            "option_chain.strikes[].pe_ltp",
            "option_chain.strikes[].ce_oi",
            "option_chain.strikes[].pe_oi",
            "option_chain.strikes[].ce_prev_oi",
            "option_chain.strikes[].pe_prev_oi",
        ],
        "optional_context": ["market_breadth"],
        "historical_limitations": (
            "BLOCKED WITHOUT HISTORICAL OPTION-CHAIN & PRIOR-SESSION CLOSING OI: "
            "Angel One SmartAPI getCandleData does not provide historical multi-strike option-chain "
            "snapshots, historical intraday OI, or expired NFO contract tokens (OpenAPIScripMaster.json "
            "only lists active unexpired contracts). Current live option-chain data must NEVER be "
            "retrofitted onto historical dates."
        ),
    },
    "strat_4_orb_filtered": {
        "strategy_id": "strat_4_orb_filtered",
        "strategy_name": "15m Opening Range Breakout",
        "target_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "required_interval_min": 5,
        "min_completed_bars": 30,
        "recommended_warmup_sessions": 1,
        "requires_positive_volume": True,
        "requires_opening_range_0915_0930": True,
        "requires_historical_option_chain": False,
        "requires_prior_session_closing_oi": False,
        "required_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "optional_context": ["market_breadth"],
        "historical_limitations": (
            "Requires all three opening-range 5-minute bars (09:15:00, 09:20:00, 09:25:00 IST) "
            "to be present on the evaluated session date plus positive 20-bar volume for >=1.6x RVOL."
        ),
    },
    "strat_5_supertrend_pullback": {
        "strategy_id": "strat_5_supertrend_pullback",
        "strategy_name": "Supertrend (10,3) + 200 EMA",
        "target_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "required_interval_min": 5,
        "min_completed_bars": 200,
        "recommended_warmup_sessions": 3,
        "requires_positive_volume": True,
        "requires_opening_range_0915_0930": False,
        "requires_historical_option_chain": False,
        "requires_prior_session_closing_oi": False,
        "required_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "optional_context": ["market_breadth"],
        "historical_limitations": (
            "Requires >=200 completed 5-minute bars (>=3 prior NSE trading sessions of 75 bars each) "
            "to warm up the 200-period EMA and Supertrend(10,3), plus positive volume for >=1.3x RVOL."
        ),
    },
}


def _parse_hhmm(hhmm_str: str) -> dt_time:
    parts = str(hhmm_str or "").strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid HH:MM time string: {hhmm_str!r}")
    return dt_time(int(parts[0]), int(parts[1]), 0)


def generate_nse_session_bar_timestamps(
    session_date: Any,
    interval_min: int = 5,
    session_start_ist: str = "09:15",
    session_end_ist: str = "15:30",
) -> List[str]:
    """
    Generates the exact list of expected bar-start timestamps ('YYYY-MM-DD HH:MM:SS' in IST)
    for a single NSE trading session.
    For `interval_min=5` and `09:15`–`15:30 IST`, returns 75 timestamps starting at
    `09:15:00` and ending at `15:25:00` (since the `15:25:00` bar closes at `15:30:00`).
    """
    if isinstance(interval_min, bool) or not isinstance(interval_min, int) or interval_min not in SUPPORTED_HISTORICAL_INTERVALS_MIN:
        raise HistoricalDataValidationError(
            f"Unsupported interval_min {interval_min!r}. Supported: {SUPPORTED_HISTORICAL_INTERVALS_MIN}"
        )
    if isinstance(session_date, datetime):
        d = parse_ist_timestamp(session_date).date()
    elif isinstance(session_date, date):
        d = session_date
    elif isinstance(session_date, str) and len(session_date.strip()) == 10:
        d = datetime.strptime(session_date.strip(), "%Y-%m-%d").date()
    else:
        d = parse_ist_timestamp(session_date).date()

    t_open = _parse_hhmm(session_start_ist)
    t_close = _parse_hhmm(session_end_ist)
    cur_dt = datetime.combine(d, t_open, tzinfo=IST)
    close_dt = datetime.combine(d, t_close, tzinfo=IST)
    delta = timedelta(minutes=interval_min)

    expected: List[str] = []
    while cur_dt + delta <= close_dt:
        expected.append(format_ist_timestamp(cur_dt))
        cur_dt += delta
    return expected


def list_expected_nse_trading_sessions(
    start_date: Any,
    end_date: Any,
    configured_holidays: Optional[List[str]] = None,
) -> List[str]:
    """
    Returns all valid NSE trading session dates ('YYYY-MM-DD') in `[start_date, end_date]`
    inclusive, skipping weekends (Saturday/Sunday) and `configured_holidays`.
    """
    if isinstance(start_date, str) and len(start_date.strip()) == 10:
        d_start = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
    elif isinstance(start_date, datetime):
        d_start = parse_ist_timestamp(start_date).date()
    elif isinstance(start_date, date):
        d_start = start_date
    else:
        d_start = parse_ist_timestamp(start_date).date()

    if isinstance(end_date, str) and len(end_date.strip()) == 10:
        d_end = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
    elif isinstance(end_date, datetime):
        d_end = parse_ist_timestamp(end_date).date()
    elif isinstance(end_date, date):
        d_end = end_date
    else:
        d_end = parse_ist_timestamp(end_date).date()

    if d_end < d_start:
        raise HistoricalDataValidationError(
            f"end_date ({d_end.isoformat()}) cannot be earlier than start_date ({d_start.isoformat()})."
        )

    sessions: List[str] = []
    cursor = d_start
    while cursor <= d_end:
        if is_nse_trading_day(cursor, configured_holidays):
            sessions.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return sessions


def _detect_timestamp_transformation(raw_ts: Any) -> Optional[str]:
    """Identifies what normalization transformation was applied to a raw timestamp."""
    if isinstance(raw_ts, (int, float)):
        return "epoch_ms_to_ist" if float(raw_ts) >= 1e11 else "epoch_sec_to_ist"
    if isinstance(raw_ts, str):
        s = raw_ts.strip()
        if s.isdigit():
            return "epoch_str_to_ist"
        if s.endswith("Z") or "+00:00" in s:
            return "iso8601_utc_to_ist"
        if "+05:30" in s or "T" in s:
            return "iso8601_ist_normalized"
        if any(mon in s for mon in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")):
            return "angel_feed_str_to_ist"
    return None


def validate_bar_timestamp_on_nse_grid(
    raw_ts: Any,
    interval_min: int = 5,
    configured_holidays: Optional[List[str]] = None,
    session_start_ist: str = "09:15",
    session_end_ist: str = "15:30",
) -> Tuple[datetime, str, Optional[str]]:
    """
    Normalizes `raw_ts` to a timezone-aware `Asia/Kolkata` (`IST`) datetime and validates:
    1. Not a weekend (Saturday or Sunday).
    2. Not a configured NSE holiday (`configured_holidays`).
    3. Exact minute precision (`second == 0` and `microsecond == 0`).
    4. Within NSE session bar-start window: `session_open <= bar_start` and
       `bar_start + interval_min <= session_close` (e.g., `09:15:00`..`15:25:00` for 5m bars).
    5. Aligned to the `interval_min` grid starting from `session_open` (`09:15 IST`).
    Returns `(ist_datetime, formatted_ist_str, transformation_tag)`.
    Raises `HistoricalDataValidationError` on any violation.
    """
    try:
        dt = parse_ist_timestamp(raw_ts)
    except ValueError as exc:
        raise HistoricalDataValidationError(f"Malformed candle timestamp {raw_ts!r}: {exc}") from exc

    transform_tag = _detect_timestamp_transformation(raw_ts)
    day_str = dt.strftime("%Y-%m-%d")

    if dt.weekday() >= 5:
        raise HistoricalDataValidationError(
            f"Candle timestamp {format_ist_timestamp(dt)} falls on a weekend ({dt.strftime('%A')})."
        )
    holiday_set = {str(h).strip() for h in (configured_holidays or []) if str(h).strip()}
    if day_str in holiday_set:
        raise HistoricalDataValidationError(
            f"Candle timestamp {format_ist_timestamp(dt)} falls on a configured NSE holiday ({day_str})."
        )

    if dt.second != 0 or dt.microsecond != 0:
        raise HistoricalDataValidationError(
            f"Candle timestamp {format_ist_timestamp(dt)} has non-zero seconds ({dt.second}s); "
            f"expected exact {interval_min}m bar start boundary."
        )

    t_open = _parse_hhmm(session_start_ist)
    t_close = _parse_hhmm(session_end_ist)
    session_open_dt = datetime.combine(dt.date(), t_open, tzinfo=IST)
    session_close_dt = datetime.combine(dt.date(), t_close, tzinfo=IST)
    bar_end_dt = dt + timedelta(minutes=interval_min)

    if dt < session_open_dt:
        raise HistoricalDataValidationError(
            f"Candle timestamp {format_ist_timestamp(dt)} is before NSE session open ({session_start_ist} IST)."
        )
    if bar_end_dt > session_close_dt:
        last_valid_start = format_ist_timestamp(session_close_dt - timedelta(minutes=interval_min))
        raise HistoricalDataValidationError(
            f"Candle timestamp {format_ist_timestamp(dt)} (bar end {format_ist_timestamp(bar_end_dt)}) "
            f"exceeds NSE session close ({session_end_ist} IST; last valid {interval_min}m bar start is {last_valid_start})."
        )

    mins_from_open = int((dt - session_open_dt).total_seconds() // 60)
    if mins_from_open % interval_min != 0:
        raise HistoricalDataValidationError(
            f"Candle timestamp {format_ist_timestamp(dt)} is not aligned to the {interval_min}-minute "
            f"NSE session grid starting at {session_start_ist} IST (offset={mins_from_open}m)."
        )

    return dt, format_ist_timestamp(dt), transform_tag


def compute_historical_candle_dedup_key(
    symbol: str,
    interval_min: int,
    candle_timestamp_ist: str,
    data_mode: str,
    provider: str,
) -> str:
    """
    Computes the canonical unique key for a row in `historical_candles`:
    `{SYMBOL}:{INTERVAL_MIN}m:{CANDLE_TIMESTAMP_IST}:{DATA_MODE}:{PROVIDER}`
    """
    return (
        f"{str(symbol).strip().upper()}:"
        f"{int(interval_min)}m:"
        f"{str(candle_timestamp_ist).strip()}:"
        f"{str(data_mode).strip().upper()}:"
        f"{str(provider).strip().lower()}"
    )


def validate_and_prepare_historical_dataset(
    candles: List[Dict[str, Any]],
    symbol: str,
    segment: str,
    exchange: str,
    provider: str,
    instrument_token: str,
    interval_min: int = 5,
    data_mode: str = "LIVE",
    retrieved_at_ist: Optional[Any] = None,
    reference_time_ist: Optional[Any] = None,
    configured_holidays: Optional[List[str]] = None,
    session_start_ist: str = "09:15",
    session_end_ist: str = "15:30",
    allow_identical_duplicates: bool = True,
    sort_chronologically: bool = True,
    reject_forming_candles: bool = True,
    filter_forming_candles: bool = False,
    require_complete_sessions: bool = False,
    audit_intermediate_sessions: bool = True,
    initial_transformations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Phase 3A Historical Dataset Quality & Provenance Validator:
    1. Validates instrument & provenance metadata (`symbol`, `segment`, `exchange`, `provider`,
       `instrument_token`, `interval_min`, `retrieved_at_ist`, `data_mode`).
    2. Enforces strict `LIVE` vs `SIMULATED` provenance isolation (never mixes modes).
    3. Preserves and normalizes all timestamps in `Asia/Kolkata` (`IST`), rejecting weekends,
       configured NSE holidays, pre-open/post-close timestamps, and off-grid timestamps.
    4. Validates OHLCV invariants (`open, high, low, close > 0`, `high >= max(open, close)`,
       `low <= min(open, close)`, `high >= low`, `volume >= 0`, `open_interest >= 0`).
    5. Prevents look-ahead bias by distinguishing completed vs forming candles against
       `reference_time_ist` (rejecting forming/future candles by default, or filtering them out
       when `filter_forming_candles=True`).
    6. Detects duplicate timestamps: coalesces byte-for-byte identical duplicates idempotently
       when `allow_identical_duplicates=True` (or rejects them when `False`), and ALWAYS rejects
       conflicting duplicates (same timestamp with different OHLCV).
    7. Audits missing bars across each NSE trading session (`75` bars/session for 5m candles)
       without ever fabricating or forward-filling missing data.
    8. Computes a deterministic SHA-256 checksum and `dataset_id`.
    """
    if not isinstance(candles, list) or not candles:
        raise HistoricalDataValidationError("Historical dataset requires a non-empty list of candle records.")

    sym = str(symbol or "").strip().upper()
    seg = str(segment or "").strip().upper()
    exch = str(exchange or "").strip().upper()
    prov = str(provider or "").strip().lower()
    tok = str(instrument_token or "").strip()
    dm = str(data_mode or "").strip().upper()

    if not sym or not all(ch.isalnum() or ch in ("&", "-", "_") for ch in sym):
        raise HistoricalDataValidationError(f"Invalid symbol {symbol!r}.")
    if seg not in ("NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"):
        raise HistoricalDataValidationError(
            f"Invalid segment {segment!r}. Expected 'NSE_EQUITY_INTRADAY' or 'NSE_FO_INDEX'."
        )
    if sym in INDEX_SYMBOLS and seg != "NSE_FO_INDEX":
        raise HistoricalDataValidationError(f"Index symbol {sym} must use segment 'NSE_FO_INDEX', got {seg!r}.")
    if sym not in INDEX_SYMBOLS and seg == "NSE_FO_INDEX":
        raise HistoricalDataValidationError(f"Equity symbol {sym} cannot use segment 'NSE_FO_INDEX'.")
    if exch not in ("NSE", "NFO", "BSE"):
        raise HistoricalDataValidationError(f"Invalid exchange {exchange!r}. Expected 'NSE', 'NFO', or 'BSE'.")
    if not prov:
        raise HistoricalDataValidationError("Historical dataset requires a non-empty 'provider'.")
    if not tok:
        raise HistoricalDataValidationError(f"Historical dataset for {sym} requires a non-empty 'instrument_token'.")
    if isinstance(interval_min, bool) or not isinstance(interval_min, int) or interval_min not in SUPPORTED_HISTORICAL_INTERVALS_MIN:
        raise HistoricalDataValidationError(
            f"Unsupported interval_min {interval_min!r}. Supported: {SUPPORTED_HISTORICAL_INTERVALS_MIN}"
        )
    if dm not in ("LIVE", "SIMULATED"):
        raise HistoricalDataValidationError(f"Invalid data_mode {data_mode!r}. Expected 'LIVE' or 'SIMULATED'.")

    is_sim_provider = any(k in prov for k in ("sim", "paper", "mock", "fixture"))
    if dm == "LIVE" and is_sim_provider:
        raise HistoricalDataValidationError(
            f"Provenance violation: provider '{prov}' is simulated/mock and cannot be recorded with data_mode='LIVE'."
        )
    if dm == "SIMULATED" and not is_sim_provider and prov in ("angelone", "dhan", "upstox"):
        raise HistoricalDataValidationError(
            f"Provenance violation: live broker provider '{prov}' cannot be labeled data_mode='SIMULATED'."
        )

    ref_dt = parse_ist_timestamp(reference_time_ist or retrieved_at_ist or datetime.now(IST))
    ret_dt = parse_ist_timestamp(retrieved_at_ist or ref_dt)
    ret_ist_str = format_ist_timestamp(ret_dt)

    transformations: List[str] = list(initial_transformations or [])
    transform_set: Set[str] = set(transformations)

    def _add_transform(tag: str) -> None:
        if tag and tag not in transform_set:
            transform_set.add(tag)
            transformations.append(tag)

    bar_delta = timedelta(minutes=interval_min)
    parsed_rows: List[Tuple[datetime, int, Dict[str, Any]]] = []
    filtered_forming_count = 0

    for idx, raw_bar in enumerate(candles):
        if not isinstance(raw_bar, dict):
            raise HistoricalDataValidationError(f"Candle record at index {idx} must be a dict.")

        for req_key in ("timestamp", "open", "high", "low", "close", "volume"):
            if req_key not in raw_bar or raw_bar[req_key] is None or isinstance(raw_bar[req_key], bool):
                raise HistoricalDataValidationError(
                    f"Candle record at index {idx} is missing or has invalid field '{req_key}'."
                )

        # Never overwrite conflicting source identity with import arguments.
        for key, expected in (("symbol", sym), ("segment", seg), ("exchange", exch),
                              ("provider", prov), ("instrument_token", tok)):
            if key in raw_bar and str(raw_bar[key]).strip() != str(expected):
                raise HistoricalDataValidationError(f"Historical identity mismatch at index {idx}: {key} conflicts with dataset metadata.")

        identity = raw_bar.get("instrument_identity")
        if identity:
            if not isinstance(identity, dict) or any(identity.get(k) != expected for k, expected in (
                    ("symbol", sym), ("segment", seg), ("exchange", exch), ("provider", prov), ("identifier", tok))):
                raise HistoricalDataValidationError(f"Historical candle instrument identity conflicts at index {idx}.")

        # Check per-bar data_mode / is_simulated isolation
        bar_dm = str(raw_bar.get("data_mode") or dm).strip().upper()
        if bar_dm != dm:
            raise HistoricalDataValidationError(
                f"Data-mode mixing violation at index {idx}: bar has data_mode={bar_dm!r} inside {dm!r} dataset."
            )
        if "is_simulated" in raw_bar and raw_bar["is_simulated"] is not None:
            if not isinstance(raw_bar["is_simulated"], bool) and raw_bar["is_simulated"] not in (0, 1):
                raise HistoricalDataValidationError(f"Candle at index {idx} has invalid is_simulated flag.")
            bar_is_sim = bool(raw_bar["is_simulated"])
            if dm == "LIVE" and bar_is_sim:
                raise HistoricalDataValidationError(
                    f"Data-mode mixing violation at index {idx}: simulated bar (is_simulated=True) rejected in LIVE dataset."
                )
            if dm == "SIMULATED" and not bar_is_sim:
                raise HistoricalDataValidationError(
                    f"Data-mode mixing violation at index {idx}: live bar (is_simulated=False) rejected in SIMULATED dataset."
                )

        if "symbol" in raw_bar and raw_bar["symbol"] is not None:
            if str(raw_bar["symbol"]).strip().upper() != sym:
                raise HistoricalDataValidationError(
                    f"Instrument mismatch at index {idx}: bar symbol {raw_bar['symbol']!r} != dataset symbol {sym!r}."
                )

        dt, ts_ist_str, ts_transform = validate_bar_timestamp_on_nse_grid(
            raw_bar["timestamp"],
            interval_min=interval_min,
            configured_holidays=configured_holidays,
            session_start_ist=session_start_ist,
            session_end_ist=session_end_ist,
        )
        if ts_transform:
            _add_transform(ts_transform)

        try:
            o = float(raw_bar["open"])
            h = float(raw_bar["high"])
            l = float(raw_bar["low"])
            cl = float(raw_bar["close"])
            v = float(raw_bar["volume"])
            oi_raw = raw_bar.get("open_interest", raw_bar.get("oi", 0))
            if isinstance(oi_raw, bool):
                raise ValueError("open_interest cannot be boolean.")
            oi_val = int(round(float(oi_raw or 0)))
        except (TypeError, ValueError) as exc:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) has non-numeric OHLCV/OI field: {exc}"
            ) from exc

        if not all(math.isfinite(x) for x in (o, h, l, cl, v)):
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) contains non-finite NaN/Inf values."
            )
        if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) has non-positive OHLC price: O={o}, H={h}, L={l}, C={cl}."
            )
        if v < 0:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) has negative volume ({v})."
            )
        if oi_val < 0:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) has negative open_interest ({oi_val})."
            )
        if h < l - 1e-9:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) violates high >= low ({h} < {l})."
            )
        if h < max(o, cl) - 1e-9:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) violates high >= max(open, close) ({h} < max({o}, {cl}))."
            )
        if l > min(o, cl) + 1e-9:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} ({ts_ist_str}) violates low <= min(open, close) ({l} > min({o}, {cl}))."
            )

        bar_end_dt = dt + bar_delta
        explicit_complete = raw_bar.get("is_complete")
        is_complete = bool((bar_end_dt <= ref_dt) and (explicit_complete is not False))

        if not is_complete:
            if filter_forming_candles:
                filtered_forming_count += 1
                _add_transform("filtered_forming_candles")
                continue
            if reject_forming_candles:
                reason = (
                    f"bar close {format_ist_timestamp(bar_end_dt)} > reference time {format_ist_timestamp(ref_dt)}"
                    if bar_end_dt > ref_dt
                    else "explicitly marked is_complete=False"
                )
                raise HistoricalDataValidationError(
                    f"Forming or future candle rejected at index {idx} ({ts_ist_str}): {reason}. "
                    f"Historical datasets must contain only completed bars to prevent look-ahead bias."
                )

        src_ts_raw = raw_bar.get("source_timestamp", raw_bar.get("timestamp"))
        src_ts_ist = format_ist_timestamp(parse_ist_timestamp(src_ts_raw))

        norm_record = {
            "symbol": sym,
            "segment": seg,
            "exchange": exch,
            "provider": prov,
            "instrument_token": tok,
            "interval_min": interval_min,
            "timestamp": ts_ist_str,
            "session_date": dt.strftime("%Y-%m-%d"),
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(cl, 4),
            "volume": round(v, 2),
            "open_interest": oi_val,
            "is_complete": is_complete,
            "source_timestamp_ist": src_ts_ist,
            "retrieved_at_ist": ret_ist_str,
            "data_mode": dm,
            "is_simulated": dm == "SIMULATED",
        }
        parsed_rows.append((dt, idx, norm_record))

    if not parsed_rows:
        raise HistoricalDataValidationError(
            "Historical dataset contains 0 completed bars after filtering forming candles."
        )

    # Check ordering before sorting
    was_out_of_order = any(
        parsed_rows[i][0] < parsed_rows[i - 1][0] for i in range(1, len(parsed_rows))
    )
    if was_out_of_order:
        if not sort_chronologically:
            raise HistoricalDataValidationError(
                "Historical candle timestamps are not in chronological order and sort_chronologically=False."
            )
        parsed_rows.sort(key=lambda item: (item[0], item[1]))
        _add_transform("sorted_chronologically")

    # Deduplicate / detect conflicting duplicates
    deduped_bars: List[Dict[str, Any]] = []
    by_ts: Dict[str, Dict[str, Any]] = {}
    duplicate_bars_coalesced = 0

    for dt, orig_idx, rec in parsed_rows:
        ts_key = rec["timestamp"]
        if ts_key in by_ts:
            existing = by_ts[ts_key]
            same_ohlcv = (
                abs(existing["open"] - rec["open"]) <= 1e-6
                and abs(existing["high"] - rec["high"]) <= 1e-6
                and abs(existing["low"] - rec["low"]) <= 1e-6
                and abs(existing["close"] - rec["close"]) <= 1e-6
                and abs(existing["volume"] - rec["volume"]) <= 1e-4
                and existing["open_interest"] == rec["open_interest"]
            )
            if not same_ohlcv:
                raise HistoricalDataValidationError(
                    f"Conflicting duplicate candle at {ts_ist_str} for {sym}: "
                    f"existing=({existing['open']}, {existing['high']}, {existing['low']}, {existing['close']}, vol={existing['volume']}) "
                    f"vs incoming=({rec['open']}, {rec['high']}, {rec['low']}, {rec['close']}, vol={rec['volume']})."
                )
            if not allow_identical_duplicates:
                raise HistoricalDataValidationError(
                    f"Duplicate candle timestamp {ts_key} at index {orig_idx} rejected (allow_identical_duplicates=False)."
                )
            duplicate_bars_coalesced += 1
            _add_transform("coalesced_identical_duplicates")
            continue

        by_ts[ts_key] = rec
        deduped_bars.append(rec)

    # Audit session completeness and missing bars without fabricating any missing values
    present_sessions = sorted({b["session_date"] for b in deduped_bars})
    first_session = present_sessions[0]
    last_session = present_sessions[-1]

    if audit_intermediate_sessions:
        audited_sessions = list_expected_nse_trading_sessions(
            first_session, last_session, configured_holidays=configured_holidays
        )
    else:
        audited_sessions = present_sessions

    missing_timestamps: List[str] = []
    sessions_summary: Dict[str, Dict[str, Any]] = {}
    present_ts_set = set(by_ts.keys())

    for sess_str in audited_sessions:
        expected_ts_list = generate_nse_session_bar_timestamps(
            sess_str,
            interval_min=interval_min,
            session_start_ist=session_start_ist,
            session_end_ist=session_end_ist,
        )
        sess_missing = [ts for ts in expected_ts_list if ts not in present_ts_set]
        sess_present_count = len(expected_ts_list) - len(sess_missing)
        missing_timestamps.extend(sess_missing)
        sessions_summary[sess_str] = {
            "session_date": sess_str,
            "expected_bars": len(expected_ts_list),
            "present_bars": sess_present_count,
            "missing_bars": len(sess_missing),
            "is_complete_session": len(sess_missing) == 0,
            "opening_range_0915_0930_complete": all(
                f"{sess_str} {t_str}" in present_ts_set
                for t_str in ("09:15:00", "09:20:00", "09:25:00")
            ) if interval_min == 5 else (sess_present_count > 0),
        }

    if require_complete_sessions and missing_timestamps:
        raise HistoricalDataValidationError(
            f"Historical dataset for {sym} has {len(missing_timestamps)} missing {interval_min}m bar(s) "
            f"(first missing: {missing_timestamps[0]})."
        )

    zero_volume_bars_count = sum(1 for b in deduped_bars if b["volume"] <= 0.0)
    completed_bars_count = sum(1 for b in deduped_bars if b["is_complete"])

    if missing_timestamps:
        quality_status = "INCOMPLETE_MISSING_BARS"
    elif zero_volume_bars_count > 0:
        quality_status = "WARNING_ZERO_VOLUME"
    else:
        quality_status = "COMPLETE_VERIFIED"

    for b in deduped_bars:
        b["transformations"] = list(transformations)
        b["dedup_key"] = compute_historical_candle_dedup_key(
            symbol=sym,
            interval_min=interval_min,
            candle_timestamp_ist=b["timestamp"],
            data_mode=dm,
            provider=prov,
        )

    from_ts = deduped_bars[0]["timestamp"]
    to_ts = deduped_bars[-1]["timestamp"]

    checksum_payload = json.dumps(
        {
            "symbol": sym,
            "segment": seg,
            "exchange": exch,
            "provider": prov,
            "instrument_token": tok,
            "interval_min": interval_min,
            "data_mode": dm,
            "bars": [
                [b["timestamp"], b["open"], b["high"], b["low"], b["close"], b["volume"], b["open_interest"]]
                for b in deduped_bars
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    sha256_checksum = hashlib.sha256(checksum_payload.encode("utf-8")).hexdigest()
    dataset_id = f"ds_{sym}_{interval_min}m_{dm}_{prov}_{sha256_checksum[:12]}"

    for b in deduped_bars:
        b["dataset_id"] = dataset_id

    manifest = {
        "dataset_id": dataset_id,
        "symbol": sym,
        "segment": seg,
        "exchange": exch,
        "provider": prov,
        "instrument_token": tok,
        "interval_min": interval_min,
        "from_timestamp_ist": from_ts,
        "to_timestamp_ist": to_ts,
        "retrieved_at_ist": ret_ist_str,
        "source_timestamp_ist": deduped_bars[-1]["source_timestamp_ist"],
        "data_mode": dm,
        "is_simulated": dm == "SIMULATED",
        "transformations": transformations,
        "quality_status": quality_status,
        "bars_count": len(deduped_bars),
        "completed_bars_count": completed_bars_count,
        "sessions_count": len(audited_sessions),
        "present_sessions_count": len(present_sessions),
        "missing_bars_count": len(missing_timestamps),
        "missing_timestamps": missing_timestamps,
        "zero_volume_bars_count": zero_volume_bars_count,
        "duplicate_bars_coalesced": duplicate_bars_coalesced,
        "filtered_forming_count": filtered_forming_count,
        "sessions_summary": sessions_summary,
        "sha256_checksum": sha256_checksum,
    }
    return {
        "manifest": manifest,
        "candles": deduped_bars,
    }


def verify_no_lookahead_leakage(
    candles_slice: List[Dict[str, Any]],
    decision_time_ist: Any,
    interval_min: int = 5,
) -> bool:
    """
    Strictly verifies that every candle in `candles_slice` was completely closed at or before
    `decision_time_ist` (`bar_start + timedelta(minutes=interval_min) <= decision_time_ist`)
    and `is_complete is True`.
    Raises `LookAheadBiasError` immediately if any forming or future bar is present.
    """
    decision_dt = parse_ist_timestamp(decision_time_ist)
    bar_delta = timedelta(minutes=max(1, int(interval_min)))
    prev_dt: Optional[datetime] = None

    for idx, bar in enumerate(candles_slice):
        if not isinstance(bar, dict) or "timestamp" not in bar:
            raise LookAheadBiasError(f"Invalid candle in backtest slice at index {idx}.")
        bar_start_dt = parse_ist_timestamp(bar["timestamp"])
        bar_end_dt = bar_start_dt + bar_delta

        if bar.get("is_complete") is False:
            raise LookAheadBiasError(
                f"Look-ahead violation at index {idx}: bar {bar['timestamp']} is marked is_complete=False "
                f"at decision_time_ist={format_ist_timestamp(decision_dt)}."
            )
        if bar_start_dt >= decision_dt:
            raise LookAheadBiasError(
                f"Look-ahead violation at index {idx}: future bar {bar['timestamp']} starts at or after "
                f"decision_time_ist={format_ist_timestamp(decision_dt)}."
            )
        if bar_end_dt > decision_dt:
            raise LookAheadBiasError(
                f"Look-ahead violation at index {idx}: forming bar {bar['timestamp']} "
                f"(closes at {format_ist_timestamp(bar_end_dt)}) is not yet complete at "
                f"decision_time_ist={format_ist_timestamp(decision_dt)}."
            )
        if prev_dt is not None and bar_start_dt <= prev_dt:
            raise LookAheadBiasError(
                f"Chronological ordering violation in backtest slice at index {idx}: "
                f"{format_ist_timestamp(bar_start_dt)} <= {format_ist_timestamp(prev_dt)}."
            )
        prev_dt = bar_start_dt
    return True


def get_point_in_time_candle_slice(
    candles: List[Dict[str, Any]],
    decision_time_ist: Any,
    interval_min: int = 5,
    expected_data_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Returns a strictly chronological, look-ahead-free slice of completed candles available at
    `decision_time_ist`:
    - Excludes any candle where `is_complete is False`.
    - Excludes any forming candle where `bar_start <= decision_time_ist < bar_start + interval_min`.
    - Excludes any future candle where `bar_start >= decision_time_ist`.
    - Enforces `LIVE` vs `SIMULATED` data-mode isolation across the slice.
    """
    if not isinstance(candles, list):
        raise HistoricalDataValidationError("candles must be a list of dicts.")

    decision_dt = parse_ist_timestamp(decision_time_ist)
    bar_delta = timedelta(minutes=max(1, int(interval_min)))
    exp_mode = str(expected_data_mode).strip().upper() if expected_data_mode else None

    seen_modes: Set[str] = set()
    eligible: List[Tuple[datetime, Dict[str, Any]]] = []

    for idx, c in enumerate(candles):
        if not isinstance(c, dict) or "timestamp" not in c:
            raise HistoricalDataValidationError(f"Malformed candle at index {idx} in get_point_in_time_candle_slice.")

        bar_mode = str(c.get("data_mode") or ("SIMULATED" if c.get("is_simulated") else "LIVE")).strip().upper()
        seen_modes.add(bar_mode)
        if len(seen_modes) > 1:
            raise HistoricalDataValidationError(
                "Data-mode mixing violation: LIVE and SIMULATED candles cannot be mixed in a backtest slice."
            )
        if exp_mode and bar_mode != exp_mode:
            raise HistoricalDataValidationError(
                f"Candle at index {idx} has data_mode={bar_mode!r}, expected {exp_mode!r}."
            )

        if c.get("is_complete") is False:
            continue

        bar_start = parse_ist_timestamp(c["timestamp"])
        bar_end = bar_start + bar_delta
        if bar_end <= decision_dt:
            copied = dict(c)
            copied["timestamp"] = format_ist_timestamp(bar_start)
            copied["is_complete"] = True
            copied["data_mode"] = bar_mode
            copied["is_simulated"] = bar_mode == "SIMULATED"
            eligible.append((bar_start, copied))

    eligible.sort(key=lambda item: item[0])
    result = [item[1] for item in eligible]
    verify_no_lookahead_leakage(result, decision_dt, interval_min=interval_min)
    return result


def compute_point_in_time_universe_breadth(
    universe_candles_by_symbol: Dict[str, List[Dict[str, Any]]],
    decision_time_ist: Any,
    interval_min: int = 5,
    expected_data_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes universe advance/decline breadth at `decision_time_ist` using ONLY completed
    current-session bars up to `decision_time_ist` (never peeking at end-of-day closes).
    """
    decision_dt = parse_ist_timestamp(decision_time_ist)
    session_date_str = decision_dt.strftime("%Y-%m-%d")
    advances = 0
    declines = 0
    unchanged = 0

    for sym, bars in sorted((universe_candles_by_symbol or {}).items()):
        pit_bars = get_point_in_time_candle_slice(
            bars,
            decision_time_ist=decision_dt,
            interval_min=interval_min,
            expected_data_mode=expected_data_mode,
        )
        day_bars = [b for b in pit_bars if str(b["timestamp"])[:10] == session_date_str]
        if not day_bars:
            continue
        day_open = float(day_bars[0]["open"])
        pit_close = float(day_bars[-1]["close"])
        if pit_close > day_open:
            advances += 1
        elif pit_close < day_open:
            declines += 1
        else:
            unchanged += 1

    return {
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "total_evaluated": advances + declines + unchanged,
        "as_of_ist": format_ist_timestamp(decision_dt),
    }


def evaluate_phase3a_backtest_readiness(
    config: Optional[BotConfig] = None,
    store: Optional[SQLitePersistenceStore] = None,
    broker_status: Optional[Dict[str, Any]] = None,
    target_data_mode: str = "LIVE",
    **scope: Any,
) -> Dict[str, Any]:
    """Compatibility entry point; all acceptance/coverage decisions use one policy."""
    from readiness_policy import readiness_report
    cfg = config or BotConfig(database_url=os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db"))
    report = dict(readiness_report(cfg, store, broker_status, target_data_mode, **scope))
    # Receipt/coverage decisions retain their original policy; overall research
    # readiness must also reflect the independently evaluated source-evidence gate.
    from source_qualification import POLICY_VERSION
    report["acceptance_coverage_ready_for_execution"] = report["phase3_ready_for_execution"]
    mode = str(target_data_mode).strip().upper()
    report["historical_source_qualification"] = dict(policy_version=POLICY_VERSION,
        status="NOT_ESTABLISHED" if mode == "LIVE" else "SIMULATED_NOT_APPLICABLE",
        live_historical_replay_allowed=False, reason_code="HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT",
        missing_evidence=["Independent archive-to-publisher binding", "Authoritative effective intervals", "Supported evidence verifier"])
    if mode == "LIVE":
        report["phase3_ready_for_execution"] = False
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="TradePulse Phase 3A — Historical Market Data Quality, Import & Readiness CLI"
    )
    parser.add_argument(
        "--import-candles", "--import-file",
        metavar="FILE_PATH",
        help="Validate and idempotently import a historical 5m OHLCV dataset file (.json or .csv) into SQLite",
    )
    parser.add_argument(
        "--symbol",
        default="RELIANCE",
        help="Default symbol when importing a CSV/JSON file that omits symbol column (default: RELIANCE)",
    )
    parser.add_argument(
        "--provider",
        default="angelone",
        help="Dataset provider provenance identifier (e.g., angelone, dhan, upstox, paper_sim)",
    )
    parser.add_argument(
        "--instrument-token",
        default="2885",
        help="Provider instrument token for provenance recording (default: 2885 for RELIANCE)",
    )
    parser.add_argument(
        "--data-mode",
        default="LIVE",
        choices=["LIVE", "SIMULATED"],
        help="Dataset provenance mode (LIVE or SIMULATED)",
    )
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Evaluate and print Phase 3A historical dataset and strategy readiness gate.",
    )
    parser.add_argument(
        "--watermark",
        action="store_true",
        help="Print resumable ingestion watermark for --symbol and --provider.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit output as formatted JSON",
    )
    args = parser.parse_args(argv)

    cfg = BotConfig(database_url=os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db"))
    store = SQLitePersistenceStore(cfg.database_url or "sqlite:///tradepulse_phase1d.db")
    atexit.register(store.close)

    if getattr(args, "watermark", False):
        wm = store.get_historical_ingestion_watermark(provider=args.provider or "angelone", symbol=args.symbol or "RELIANCE", interval_min=5, data_mode=args.data_mode)
        print(json.dumps(wm, indent=2, sort_keys=True))
        return 0

    if args.import_candles:
        try:
            imp_res = store.import_historical_candles_file(
                file_path=args.import_candles,
                default_symbol=args.symbol,
                default_provider=args.provider,
                default_instrument_token=args.instrument_token,
                data_mode=args.data_mode,
                configured_holidays=cfg.configured_holidays,
            )
            if args.json:
                safe_console_print(json.dumps(imp_res, indent=2))
            else:
                safe_console_print(f"[PASS] Imported historical dataset: {json.dumps(imp_res['manifest'])}")
            return 0
        except Exception as exc:
            safe_console_print(f"[FAIL] Historical dataset import rejected: {exc}")
            return 2

    readiness = evaluate_phase3a_backtest_readiness(config=cfg, store=store, target_data_mode=args.data_mode,
                                                  provider=args.provider)
    if args.json:
        safe_console_print(json.dumps(readiness, indent=2))
    else:
        safe_console_print("=" * 86)
        safe_console_print("TRADEPULSE AI — PHASE 3A HISTORICAL DATA QUALITY & BACKTEST READINESS AUDIT")
        safe_console_print("=" * 86)
        safe_console_print(f"Evaluated At (IST)         : {readiness['evaluated_at_ist']}")
        safe_console_print(f"Phase 2C Live Accepted     : {'YES' if readiness['phase2c_live_accepted'] else 'NO (NOT COMPLETED)'}")
        safe_console_print(f"Broker Connection State    : {readiness['broker_connection_state']}")
        safe_console_print(f"Phase 3 Execution Ready    : {'YES' if readiness['phase3_ready_for_execution'] else 'NO (BLOCKED)'}")
        safe_console_print(f"Overall Gate Status        : {readiness['overall_gate_status']}")
        safe_console_print(f"Gate Reason                : {readiness['overall_gate_reason']}")
        safe_console_print("-" * 86)
        for sid, s_info in readiness["strategies_readiness"].items():
            safe_console_print(f"[{s_info['status']:<38}] {s_info['strategy_name']} ({sid})")
            if s_info.get("blocker_reason"):
                safe_console_print(f"    Reason: {s_info['blocker_reason']}")
        safe_console_print("=" * 86)
    return 0


if __name__ == "__main__":
    sys.exit(main())
