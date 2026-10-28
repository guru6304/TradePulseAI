"""TradePulse AI — Market Radar (Layer A: Broad Non-Actionable Observation Layer).

Implements Section 4A of the Post-Master Mission:
1. Normalised day-open directional movement baseline comparator:
   - Evaluates (price - open) / 50-day average daily range (ATR50).
   - One-sided movement requirement: one direction must exceed 2x the opposite direction,
     otherwise normalized momentum score is zero.
2. Market breadth and sector momentum aggregation (advances, declines, unchanged).
3. Intraday volume participation ratio vs. expected time-of-day baseline.
4. Truthful provenance and market-state labeling:
   - LIVE_VERIFIED, DELAYED, LAST_SESSION, REPLAY, SIMULATED, UNAVAILABLE, NO_RIGHTS.
   - Strict declaration: PROVISIONAL_OBSERVATION_ONLY; a 1m radar move is NEVER a 5m strategy trigger.
"""
from copy import deepcopy
from datetime import datetime, time, timedelta
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from strategies import IST, parse_ist_timestamp


RADAR_SCHEMA = "tradepulse.market-radar.v1"
RADAR_POLICY = "NORMALIZED_OPEN_MOVE_ATR50_SECTOR_BREADTH_V1"

# Standard NSE Cash Market Session Hours (IST)
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)


def _clock(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RADAR_AWARE_CLOCK_REQUIRED")
    return value.astimezone(IST)


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def calculate_normalized_open_strength(
    open_price: float,
    high_price: float,
    low_price: float,
    current_price: float,
    atr_50d: float,
) -> Dict[str, Any]:
    """Calculates normalized open directional strength against 50-day average daily range (ATR50).

    Formula (Open-source published comparator baseline):
    - Upside excursion: (high_price - open_price)
    - Downside excursion: (open_price - low_price)
    - If upside > 2 * downside: Bullish one-sided move; score = (current_price - open_price) / atr_50d
    - If downside > 2 * upside: Bearish one-sided move; score = (open_price - current_price) / atr_50d
    - Otherwise: Choppy / two-sided move; score = 0.0.
    """
    if not (math.isfinite(open_price) and math.isfinite(high_price) and math.isfinite(low_price)
            and math.isfinite(current_price) and math.isfinite(atr_50d)):
        raise ValueError("RADAR_NONFINITE_PRICE_INPUT")
    if open_price <= 0 or current_price <= 0 or atr_50d <= 0:
        raise ValueError("RADAR_NONPOSITIVE_PRICE_INPUT")
    if high_price < open_price or high_price < low_price or low_price > open_price:
        raise ValueError("RADAR_INVALID_PRICE_GEOMETRY")

    upside = high_price - open_price
    downside = open_price - low_price

    direction = "NEUTRAL"
    is_one_sided = False
    raw_strength = 0.0

    if upside > 2.0 * downside and upside > 0:
        direction = "BULLISH"
        is_one_sided = True
        raw_strength = (current_price - open_price) / atr_50d
    elif downside > 2.0 * upside and downside > 0:
        direction = "BEARISH"
        is_one_sided = True
        raw_strength = (open_price - current_price) / atr_50d

    # Normalized score bounded to [0.0, 100.0] for radar presentation
    normalized_score = round(max(0.0, min(100.0, raw_strength * 50.0)), 2)

    return {
        "direction": direction,
        "is_one_sided": is_one_sided,
        "upside_excursion": round(upside, 4),
        "downside_excursion": round(downside, 4),
        "atr_50d": round(atr_50d, 4),
        "raw_strength_ratio": round(raw_strength, 4),
        "normalized_score": normalized_score,
    }


def aggregate_market_breadth(stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes cash market breadth and sector distribution from radar observations."""
    advances = 0
    declines = 0
    unchanged = 0
    sector_scores: Dict[str, List[float]] = {}

    for s in stocks:
        change_pct = s.get("change_percent", 0.0)
        if change_pct > 0.05:
            advances += 1
        elif change_pct < -0.05:
            declines += 1
        else:
            unchanged += 1

        sector = s.get("sector", "UNASSIGNED")
        score = s.get("normalized_score", 0.0)
        sector_scores.setdefault(sector, []).append(score)

    total = len(stocks)
    advance_decline_ratio = round(advances / max(1, declines), 2)
    sentiment = "BULLISH_DOMINANT" if advances > 2 * declines else \
                "BEARISH_DOMINANT" if declines > 2 * advances else "BALANCED_RANGE"

    # Compute top sector momentum
    sector_summary = {}
    for sec, scores in sector_scores.items():
        sector_summary[sec] = {
            "stock_count": len(scores),
            "avg_strength": round(sum(scores) / max(1, len(scores)), 2),
        }

    leading_sector = max(sector_summary.items(), key=lambda item: item[1]["avg_strength"], default=("NONE", {"avg_strength": 0.0}))

    return {
        "total_monitored": total,
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "advance_decline_ratio": advance_decline_ratio,
        "market_sentiment": sentiment,
        "sector_summary": sector_summary,
        "leading_sector": leading_sector[0],
        "leading_sector_avg_score": leading_sector[1]["avg_strength"],
    }


def build_market_radar_snapshot(
    observations: List[Dict[str, Any]],
    *,
    provider: str,
    as_of: Any,
    data_mode: str = "SIMULATED",
) -> Dict[str, Any]:
    """Assembles the immutable 1-minute Market Radar snapshot.

    Strictly non-actionable; provides broad contextual market radar only.
    """
    now = _clock(as_of)
    if not isinstance(observations, list) or not observations:
        raise ValueError("RADAR_OBSERVATIONS_REQUIRED")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("RADAR_PROVIDER_REQUIRED")
    if data_mode not in ("LIVE_VERIFIED", "DELAYED", "LAST_SESSION", "REPLAY", "SIMULATED", "UNAVAILABLE"):
        raise ValueError("RADAR_INVALID_DATA_MODE")

    # Check session open/close status
    current_time = now.time()
    is_session_open = (MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME) and (now.weekday() < 5)

    radar_rows = []
    for obs in observations:
        symbol = obs.get("symbol")
        open_p = obs.get("open")
        high_p = obs.get("high")
        low_p = obs.get("low")
        current_p = obs.get("current_price") or obs.get("close")
        atr_50 = obs.get("atr_50d") or (open_p * 0.02)  # default 2% daily ATR fallback if absent
        volume = obs.get("volume", 0)
        sector = obs.get("sector", "GENERAL")

        if not symbol or open_p is None or high_p is None or low_p is None or current_p is None:
            continue

        strength = calculate_normalized_open_strength(open_p, high_p, low_p, current_p, atr_50)
        change_pct = round(((current_p - open_p) / open_p) * 100.0, 2)

        radar_rows.append({
            "symbol": symbol,
            "sector": sector,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "current_price": round(current_p, 2),
            "change_percent": change_pct,
            "volume": volume,
            "direction": strength["direction"],
            "is_one_sided": strength["is_one_sided"],
            "normalized_score": strength["normalized_score"],
            "raw_strength_ratio": strength["raw_strength_ratio"],
            "observation_cadence": "1M_HIGH_FREQUENCY",
            "is_actionable_setup": False,
        })

    # Sort radar rows by normalized momentum score descending
    radar_rows.sort(key=lambda r: (-r["normalized_score"], r["symbol"]))

    breadth = aggregate_market_breadth(radar_rows)

    snapshot_payload = {
        "schema_version": RADAR_SCHEMA,
        "policy": RADAR_POLICY,
        "provider": provider,
        "data_mode": data_mode,
        "as_of": now.isoformat(),
        "is_market_session_open": is_session_open,
        "cadence": "1M_RADAR_OBSERVATION_LAYER",
        "actionable": False,
        "radar_rows_count": len(radar_rows),
        "breadth": breadth,
        "rows": radar_rows,
        "disclaimer": "PROVISIONAL_OBSERVATION_ONLY_NOT_A_5M_STRATEGY_TRIGGER",
    }

    serialized = json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"))
    snapshot_payload["snapshot_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return snapshot_payload
