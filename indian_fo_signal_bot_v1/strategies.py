import math
import json
import inspect
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from dataclasses import dataclass, asdict, field
from datetime import datetime, date, time as dt_time, timedelta, timezone
from typing import List, Dict, Optional, Any, Tuple, Set
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN_TIME = dt_time(9, 15)
NSE_CLOSE_TIME = dt_time(15, 30)


@dataclass
class TradeSignal:
    symbol: str
    segment: str               # "NSE_EQUITY_INTRADAY" or "NSE_FO_INDEX"
    strategy_id: str
    strategy_name: str
    direction: str             # "BULLISH (BUY)", "BEARISH (SELL)", "BULLISH (BUY CE)", "BEARISH (BUY PE)"
    instrument_label: str      # e.g. "RELIANCE EQ" or "NIFTY 24800 CE"
    entry_price: float
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward: str
    confidence_pct: int
    win_rate_benchmark: str
    position_qty: int
    capital_risk_inr: float
    est_charges_inr: float
    rationale: str
    timestamp: str
    is_simulated: bool = False
    data_mode: str = "LIVE"
    position_type: str = ""
    invalidation_level: float = 0.0
    quality_score: int = 0
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    # Assigned by the scanner/replay boundary, never inferred from a display label.
    provider: str = "unknown"
    state_context: str = "UNKNOWN"
    interval_min: int = 5
    instrument_identity: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quality_score == 0 and self.confidence_pct > 0:
            self.quality_score = int(self.confidence_pct)
        elif self.confidence_pct == 0 and self.quality_score > 0:
            self.confidence_pct = int(self.quality_score)

        if self.invalidation_level == 0.0:
            self.invalidation_level = round(float(self.stop_loss), 2)

        if not self.position_type:
            if "BUY CE" in self.direction:
                self.position_type = "LONG_CALL_OPTION"
            elif "BUY PE" in self.direction:
                self.position_type = "LONG_PUT_OPTION"
            elif "BULLISH" in self.direction and self.segment == "NSE_FO_INDEX":
                self.position_type = "LONG_INDEX_FUTURE"
            elif "BEARISH" in self.direction and self.segment == "NSE_FO_INDEX":
                self.position_type = "SHORT_INDEX_FUTURE"
            elif "BULLISH" in self.direction:
                self.position_type = "LONG_EQUITY_INTRADAY"
            elif "BEARISH" in self.direction:
                self.position_type = "SHORT_EQUITY_INTRADAY"
            else:
                self.position_type = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_state_scope(provider: str, data_mode: str, state_context: str) -> Tuple[str, str, str]:
    """Canonical state namespace; context labels do not confer live acceptance."""
    source = str(provider or "").strip().lower() or "unknown"
    source = {"sim": "paper_sim", "simulated": "paper_sim"}.get(source, source)
    mode = str(data_mode).strip().upper()
    context = str(state_context or "").strip().upper() or "UNKNOWN"
    if mode not in ("LIVE", "SIMULATED"):
        raise ValueError("State data_mode must be LIVE or SIMULATED.")
    if context not in ("SCANNER", "LIVE_ACCEPTED", "HISTORICAL_RESEARCH", "SIMULATED_TEST",
                       "UNKNOWN", "LEGACY_UNSCOPED"):
        raise ValueError("Unknown state_context.")
    if ((source in ("paper_sim", "synthetic_fixture") or context == "SIMULATED_TEST") and mode != "SIMULATED"
            or context in ("LIVE_ACCEPTED", "HISTORICAL_RESEARCH") and mode != "LIVE"):
        raise ValueError("State provenance and data_mode disagree.")
    return source, mode, context


def validate_trade_signal(signal: TradeSignal) -> None:
    """Validate candidate price geometry; identity/provenance remain separate gates.

    The entry zone describes the setup area and need not contain the observed entry.
    Long put/call candidates buy premium, so both use long-price geometry.
    """
    if not isinstance(signal, TradeSignal):
        raise ValueError("A TradeSignal candidate is required.")
    for name in ("entry_price", "entry_zone_low", "entry_zone_high", "stop_loss",
                 "invalidation_level", "target_1", "target_2", "capital_risk_inr", "est_charges_inr"):
        value = getattr(signal, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Signal {name} must be finite numeric data.")
        if value < 0 or (name not in ("capital_risk_inr", "est_charges_inr") and value == 0):
            raise ValueError(f"Signal {name} is outside its supported range.")
    if type(signal.quality_score) is not int or not 0 <= signal.quality_score <= 100:
        raise ValueError("Signal setup quality must be an integer from 0 to 100.")
    if type(signal.position_qty) is not int or signal.position_qty < 1:
        raise ValueError("Signal quantity must be a positive whole unit count.")
    if signal.entry_zone_low > signal.entry_zone_high:
        raise ValueError("Signal setup zone is inverted.")
    expected = ("LONG_CALL_OPTION" if "BUY CE" in signal.direction else "LONG_PUT_OPTION" if "BUY PE" in signal.direction
        else "LONG_INDEX_FUTURE" if "BULLISH" in signal.direction and signal.segment == "NSE_FO_INDEX"
        else "SHORT_INDEX_FUTURE" if "BEARISH" in signal.direction and signal.segment == "NSE_FO_INDEX"
        else "LONG_EQUITY_INTRADAY" if "BULLISH" in signal.direction else
        "SHORT_EQUITY_INTRADAY" if "BEARISH" in signal.direction else None)
    if signal.position_type != expected or expected is None:
        raise ValueError("Signal direction and position type disagree.")
    if expected.startswith("LONG"):
        valid = signal.stop_loss <= signal.invalidation_level < signal.entry_price < signal.target_1 <= signal.target_2
    else:
        valid = signal.target_2 <= signal.target_1 < signal.entry_price < signal.invalidation_level <= signal.stop_loss
    if not valid:
        raise ValueError("Signal stop, invalidation, entry and targets are inconsistent.")


def rank_signal_candidates(signals: List[TradeSignal]) -> List[TradeSignal]:
    """Quality descending, then observed T1 reward/risk descending, then identity.

    A deterministic candidate order is not a profitability estimate or allocation.
    Recompute numeric reward/risk rather than trusting the display-only ratio string.
    """
    for signal in signals:
        validate_trade_signal(signal)
    def key(signal):
        ratio = abs(signal.target_1 - signal.entry_price) / abs(signal.entry_price - signal.stop_loss)
        return (-signal.quality_score, -ratio, signal.symbol, signal.strategy_id, signal.direction,
                signal.position_type, signal.timestamp, signal.instrument_label,
                json.dumps(signal.to_dict(), sort_keys=True, allow_nan=False))
    return sorted(signals, key=key)


STRATEGY_EVALUATION_SCHEMA = "tradepulse.strategy-evaluation.v1"
STRATEGY_WARMUP_BARS = {"strat_1_order_block": 30, "strat_2_vwap_pullback": 35,
    "strat_3_option_apex_oi": 1, "strat_4_orb_filtered": 30, "strat_5_supertrend_pullback": 200}


def _evaluation_value(value):
    """Only supported JSON measurements; never retain arbitrary objects/errors."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_evaluation_value(item) for item in value]
    return None


def _evaluation_check(trace, rule_id, passed, reason, *, unavailable=False, **measurements):
    """Record the predicate actually visited; leave its Boolean result unchanged."""
    result = bool(passed)
    if trace is not None:
        trace.setdefault("rule_checks", []).append(dict(rule_id=rule_id,
            status="PASS" if result else "UNAVAILABLE" if unavailable else "FAIL",
            reason="CONDITION_MET" if result else reason,
            measurements={name: _evaluation_value(value) for name, value in measurements.items()}))
    return result


def _evaluation_warmup(trace, completed, required):
    if trace is not None:
        trace["warmup"] = dict(required=required, observed=len(completed), interval_min=5)
        _evaluation_check(trace, "data.completed_ohlcv", True, "INVALID_CANDLE_DATA")
    return _evaluation_check(trace, "data.warmup", len(completed) >= required,
        "INSUFFICIENT_COMPLETED_CANDLES", unavailable=True, required=required, observed=len(completed))


def _evaluation_session_start(trace, completed):
    """Session VWAP requires the actual opening bar, even with a long ring."""
    current_day = parse_ist_timestamp(completed[-1]["timestamp"]).date()
    first = next(row for row in completed if parse_ist_timestamp(row["timestamp"]).date() == current_day)
    first_dt = parse_ist_timestamp(first["timestamp"])
    return _evaluation_check(trace, "session.vwap_start", first_dt.time() == NSE_OPEN_TIME,
        "SESSION_START_COVERAGE_MISSING", unavailable=True,
        observed_first_timestamp=first["timestamp"], required_open_time="09:15:00")


def signal_risk_reward(signal):
    """Gross level geometry in INR; estimated charges are not observed fills.

    The supplied charge estimate prices the modeled stop, not both target exits.
    Net target RR stays unavailable without target-specific costs/slippage.
    """
    result = dict(schema_version="tradepulse.signal-risk-reward.v1", allowed=False,
        status="UNAVAILABLE", reason_code="INVALID_SIGNAL_GEOMETRY", price_unit="INR",
        risk_per_unit=None, raw_stop_distance=None, reward_t1_per_unit=None, reward_t2_per_unit=None,
        target1_ratio=None, target2_ratio=None, gross_t1_rr=None, gross_t2_rr=None,
        estimated_net_rr=dict(status="UNAVAILABLE", reason_code="TARGET_EXIT_COSTS_AND_SLIPPAGE_NOT_PROVIDED"),
        liquidity_status="NOT_ESTABLISHED", fill_status="LEVELS_ONLY_NOT_EXECUTED")
    try:
        validate_trade_signal(signal)
        risk = abs(signal.entry_price - signal.stop_loss)
        rewards = [abs(target - signal.entry_price) for target in (signal.target_1, signal.target_2)]
        ratios = [reward / risk for reward in rewards]
        if not all(math.isfinite(value) and value > 0 for value in [risk, *rewards, *ratios]):
            return result
        result.update(allowed=True, status="SUPPORTED_GROSS_GEOMETRY", reason_code="VALID_SIGNAL_LEVELS",
            risk_per_unit=risk, raw_stop_distance=risk,
            reward_t1_per_unit=rewards[0], reward_t2_per_unit=rewards[1],
            target1_ratio=ratios[0], target2_ratio=ratios[1],
            gross_t1_rr=ratios[0], gross_t2_rr=ratios[1],
            estimated_charges_inr=signal.est_charges_inr,
            estimated_charges_per_unit=round(signal.est_charges_inr / signal.position_qty, 8),
            nominal_strategy_rr_label=signal.risk_reward,
            ratio_basis="ABSOLUTE_TARGET_DISTANCE_DIVIDED_BY_ACTUAL_ENTRY_STOP_DISTANCE",
            estimated_charge_scope="MODELED_CHARGES_ONLY_NOT_TARGET_EXIT_COSTS_OR_OBSERVED_FEES")
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        pass
    return result


def _trace_supported(evaluator):
    # Mock side effects/wraps retain the real callable's signature. Never retry an
    # evaluator after TypeError: that could duplicate mitigation side effects.
    target = getattr(evaluator, "side_effect", None)
    if not callable(target):
        target = getattr(evaluator, "_mock_wraps", None) or evaluator
    try:
        params = inspect.signature(target).parameters
        return "evaluation_trace" in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        return False


def evaluate_strategy_detailed(strategy_id, candles, *, evaluator=None, **kwargs):
    """Run one existing evaluator once, returning its candidate and actual trace.

    Existing direct evaluator returns/exceptions remain unchanged. This boundary
    turns invalid input into an unavailable diagnostic without echoing exception
    strings. Caller-supplied evaluators preserve scanner mock/override behavior.
    Short-circuited checks are not reported as evaluated failures.
    """
    names = {"strat_1_order_block": "evaluate_order_block_fvg", "strat_2_vwap_pullback": "evaluate_vwap_pullback",
        "strat_3_option_apex_oi": "evaluate_option_apex_oi_shift", "strat_4_orb_filtered": "evaluate_orb_breakout",
        "strat_5_supertrend_pullback": "evaluate_supertrend_pullback"}
    trace = dict(schema_version=STRATEGY_EVALUATION_SCHEMA, strategy_id=strategy_id, status="UNAVAILABLE",
        reason_codes=[], rule_checks=[], warmup=dict(required=STRATEGY_WARMUP_BARS.get(strategy_id), observed=None, interval_min=5),
        summary="", trace_scope="ACTUAL_VISITED_EVALUATOR_CHECKS_SHORT_CIRCUIT_PRESERVED")
    if strategy_id not in names:
        trace.update(reason_codes=["UNSUPPORTED_STRATEGY"], summary="Strategy is not implemented by the existing evaluators.")
        return None, trace
    fn = evaluator if evaluator is not None else globals()[names[strategy_id]]
    call = dict(kwargs)
    call.pop("evaluation_trace", None)
    symbol = call.pop("symbol", None)
    index_symbol = call.pop("index_symbol", None)
    call["index_symbol" if strategy_id == "strat_3_option_apex_oi" else "symbol"] = index_symbol if index_symbol is not None else symbol
    if not isinstance(index_symbol if index_symbol is not None else symbol, str) or not (index_symbol if index_symbol is not None else symbol).strip():
        _evaluation_check(trace, "data.symbol", False, "STRATEGY_SYMBOL_REQUIRED", unavailable=True)
        trace.update(reason_codes=["STRATEGY_SYMBOL_REQUIRED"], summary="A strategy symbol is required.")
        return None, trace
    call["candles"] = candles
    if strategy_id == "strat_3_option_apex_oi":
        call.setdefault("option_chain", None)
    if _trace_supported(fn):
        call["evaluation_trace"] = trace
    try:
        signal = fn(**call)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        _evaluation_check(trace, "data.evaluation_input", False, "INVALID_EVALUATION_INPUT", unavailable=True)
        trace.update(reason_codes=["INVALID_EVALUATION_INPUT"], error_type=type(exc).__name__,
            summary="Required candle, chain, or evaluation inputs failed validation; no candidate is available.")
        return None, trace
    if not trace["rule_checks"]:
        _evaluation_check(trace, "evaluator.trace", False, "CALLABLE_DIAGNOSTICS_UNAVAILABLE", unavailable=True)
    if signal is not None:
        trace.update(status="DETECTED", reason_codes=["SETUP_DETECTED"],
            summary="Existing strategy detected a setup; source, risk and downstream actionability gates remain separate.")
    else:
        failed = [row["reason"] for row in trace["rule_checks"] if row["status"] != "PASS"]
        unavailable = any(row["status"] == "UNAVAILABLE" for row in trace["rule_checks"])
        trace.update(status="UNAVAILABLE" if unavailable else "REJECTED",
            reason_codes=list(dict.fromkeys(failed)) or ["NO_ELIGIBLE_SETUP"],
            summary="Required strategy inputs are unavailable." if unavailable else "No setup met the existing evaluated strategy conditions.")
    return signal, trace


def signal_state_identity(sig: Any, broker_name: str = "") -> Tuple[str, Tuple[str, str, str]]:
    """Shared persistence/alert identity, including the complete candle timestamp.

    Unscoped broker labels can mark simulation, but cannot establish a provider.
    Instrument labels distinguish the option contracts already represented by signals;
    exact broker-token validation remains a separate concern.
    """
    data = sig.to_dict() if isinstance(sig, TradeSignal) else sig
    if not isinstance(data, dict):
        raise ValueError("Signal identity requires a TradeSignal or dictionary.")
    mode = str(data.get("data_mode", "LIVE")).strip().upper()
    if mode not in ("LIVE", "SIMULATED"):
        raise ValueError("State data_mode must be LIVE or SIMULATED.")
    unknown_source = str(data.get("provider") or "").strip().lower() in ("", "unknown")
    if data.get("is_simulated") or (unknown_source and "SIMULATED" in str(broker_name).upper()):
        mode = "SIMULATED"
    scope = normalize_state_scope(data.get("provider"), mode, data.get("state_context"))
    interval = data.get("interval_min", 5)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError("Signal interval_min must be a positive integer.")
    fields = [str(data.get(n) or "").strip().upper()
              for n in ("symbol", "segment", "strategy_id", "direction", "position_type", "instrument_label")]
    if not all(fields):
        raise ValueError("Signal is missing required identity fields.")
    timestamp = format_ist_timestamp(data.get("timestamp"))
    # An unverified display label may partition unknown sources, but grants no provenance.
    unknown_label = str(broker_name).strip() if scope[0] == "unknown" else ""
    return "signal:v2:" + json.dumps([*scope, unknown_label, *fields, interval, timestamp],
                                     separators=(",", ":")), scope


def compute_setup_quality_score(
    rvol: Optional[float] = None,
    vwap_dist_atr: Optional[float] = None,
    displacement_atr: Optional[float] = None,
    market_breadth: Optional[Dict[str, Any]] = None,
    is_bullish: bool = True,
) -> Tuple[int, Dict[str, Any]]:
    """
    Computes a deterministic, reproducible setup-quality score in [0, 100] derived strictly
    from measurable market features.

    IMPORTANT SEMANTIC NOTE:
    This score measures structural and volume confluence of a setup at signal evaluation time.
    It is NOT a statistically calibrated win probability or guarantee of trade profitability.

    Measurable Features & Normalization ([0.0, 1.0]):
    1. Relative Volume (`rvol`, base weight = 0.30):
       Linearly normalized between 0.80x (0.0) and 2.50x (1.0) of the 20-bar volume average:
       `rvol_norm = clamp((rvol - 0.80) / 1.70, 0.0, 1.0)`
    2. Directional VWAP Distance in ATR (`vwap_dist_atr`, base weight = 0.25):
       Signed distance from session VWAP in ATR(10) units (`(close - vwap)/atr` for bullish,
       `(vwap - close)/atr` for bearish).
       - `d <= -0.25`: 0.0 (wrong side of VWAP beyond tolerance)
       - `-0.25 < d < 0.15`: `(d + 0.25) / 0.40` (ramps 0.0 -> 1.0 as price reclaims VWAP)
       - `0.15 <= d <= 1.25`: 1.0 (optimal institutional launch zone near VWAP)
       - `1.25 < d < 3.25`: `1.0 - (d - 1.25) / 2.00` (tapers 1.0 -> 0.0 as extension increases)
       - `d >= 3.25`: 0.0 (overextended from VWAP)
    3. Displacement Relative to ATR (`displacement_atr`, base weight = 0.30):
       Magnitude of structure break / signal impulse normalized by ATR(10), linearly scaled
       between 0.00 ATR (0.0) and 2.00 ATR (1.0):
       `disp_norm = clamp(displacement_atr / 2.00, 0.0, 1.0)`
    4. Market Breadth (`market_breadth`, base weight = 0.15, ONLY when genuinely provided):
       Accepts `{"advances": int, "declines": int}` (or `{"bullish": int, "bearish": int}`).
       When `market_breadth` is None or total symbols == 0, breadth is explicitly marked
       unavailable (`breadth_available = False`) and weights are renormalized across the
       available features without fabricating breadth data.
       When available (`total = advances + declines > 0`):
       `aligned_ratio = advances / total` (bullish) or `declines / total` (bearish),
       linearly normalized between 0.25 (0.0) and 0.75 (1.0):
       `breadth_norm = clamp((aligned_ratio - 0.25) / 0.50, 0.0, 1.0)`
    """
    base_weights = {
        "rvol": 0.30,
        "vwap_alignment": 0.25,
        "atr_displacement": 0.30,
        "market_breadth": 0.15,
    }

    rvol_norm: Optional[float] = None
    if rvol is not None:
        if isinstance(rvol, bool):
            raise ValueError("rvol must be a numeric value, not bool.")
        rvol_val = float(rvol)
        if not math.isfinite(rvol_val) or rvol_val < 0.0:
            raise ValueError(f"Invalid rvol value: {rvol!r}")
        rvol_norm = max(0.0, min(1.0, (rvol_val - 0.80) / 1.70))

    vwap_norm: Optional[float] = None
    if vwap_dist_atr is not None:
        if isinstance(vwap_dist_atr, bool):
            raise ValueError("vwap_dist_atr must be a numeric value, not bool.")
        d = float(vwap_dist_atr)
        if not math.isfinite(d):
            raise ValueError(f"Invalid vwap_dist_atr value: {vwap_dist_atr!r}")
        if d <= -0.25 or d >= 3.25:
            vwap_norm = 0.0
        elif d < 0.15:
            vwap_norm = (d + 0.25) / 0.40
        elif d <= 1.25:
            vwap_norm = 1.0
        else:
            vwap_norm = 1.0 - ((d - 1.25) / 2.00)
        vwap_norm = max(0.0, min(1.0, vwap_norm))

    disp_norm: Optional[float] = None
    if displacement_atr is not None:
        if isinstance(displacement_atr, bool):
            raise ValueError("displacement_atr must be a numeric value, not bool.")
        disp_val = float(displacement_atr)
        if not math.isfinite(disp_val) or disp_val < 0.0:
            raise ValueError(f"Invalid displacement_atr value: {displacement_atr!r}")
        disp_norm = max(0.0, min(1.0, disp_val / 2.00))

    breadth_norm: Optional[float] = None
    breadth_ratio: Optional[float] = None
    if market_breadth is not None:
        if not isinstance(market_breadth, dict):
            raise ValueError("market_breadth must be a dict when provided.")
        adv_raw = market_breadth.get("advances", market_breadth.get("bullish"))
        dec_raw = market_breadth.get("declines", market_breadth.get("bearish"))
        if adv_raw is None or dec_raw is None or isinstance(adv_raw, bool) or isinstance(dec_raw, bool):
            raise ValueError("market_breadth must contain numeric 'advances' and 'declines' fields.")
        try:
            adv = float(adv_raw)
            dec = float(dec_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("market_breadth 'advances' and 'declines' must be numeric.") from exc
        if not (math.isfinite(adv) and math.isfinite(dec)) or adv < 0.0 or dec < 0.0:
            raise ValueError("market_breadth 'advances' and 'declines' must be non-negative finite numbers.")
        total_breadth = adv + dec
        if total_breadth > 0.0:
            breadth_ratio = (adv / total_breadth) if is_bullish else (dec / total_breadth)
            breadth_norm = max(0.0, min(1.0, (breadth_ratio - 0.25) / 0.50))

    normalized_map: Dict[str, Optional[float]] = {
        "rvol": rvol_norm,
        "vwap_alignment": vwap_norm,
        "atr_displacement": disp_norm,
        "market_breadth": breadth_norm,
    }
    active_keys = [k for k, v in normalized_map.items() if v is not None]
    if not active_keys:
        raise ValueError("At least one measurable feature is required to compute setup quality score.")

    weight_sum = sum(base_weights[k] for k in active_keys)
    effective_weights = {
        k: (base_weights[k] / weight_sum if k in active_keys else 0.0)
        for k in base_weights
    }
    composite = sum(float(normalized_map[k]) * effective_weights[k] for k in active_keys)
    score_int = max(0, min(100, int(round(100.0 * composite))))

    breakdown = {
        "quality_score": score_int,
        "score_semantics": "deterministic_setup_quality_0_100_not_calibrated_win_probability",
        "breadth_available": breadth_norm is not None,
        "features_normalized": {
            k: (round(float(v), 4) if v is not None else None)
            for k, v in normalized_map.items()
        },
        "effective_weights": {
            k: round(w, 4) for k, w in effective_weights.items()
        },
        "raw_inputs": {
            "rvol": round(float(rvol), 4) if rvol is not None else None,
            "vwap_dist_atr": round(float(vwap_dist_atr), 4) if vwap_dist_atr is not None else None,
            "displacement_atr": round(float(displacement_atr), 4) if displacement_atr is not None else None,
            "breadth_aligned_ratio": round(breadth_ratio, 4) if breadth_ratio is not None else None,
        },
    }
    return score_int, breakdown


def parse_ist_timestamp(ts: Any) -> datetime:
    """
    Normalizes a timestamp into a timezone-aware Asia/Kolkata datetime.
    Supports:
    - datetime instances (naive assumed Asia/Kolkata; aware converted via astimezone(IST))
    - Unix epoch timestamps in seconds or milliseconds (int, float, or numeric string),
      always interpreted as UTC epoch and converted to Asia/Kolkata
    - ISO-8601 strings (with 'Z', '+00:00', '+05:30', or naive exchange-local IST strings)
    """
    if isinstance(ts, bool) or ts is None:
        raise ValueError(f"Invalid candle timestamp: {ts!r}")

    if isinstance(ts, (int, float)):
        val = float(ts)
        if not math.isfinite(val) or val <= 0:
            raise ValueError(f"Non-finite or non-positive epoch timestamp: {ts!r}")
        epoch_sec = val / 1000.0 if val >= 1e11 else val
        return datetime.fromtimestamp(epoch_sec, tz=timezone.utc).astimezone(IST)

    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=IST)
        return ts.astimezone(IST)

    if not isinstance(ts, str) or not ts.strip():
        raise ValueError(f"Invalid candle timestamp: {ts!r}")

    raw = ts.strip()
    try:
        num_val = float(raw)
        if math.isfinite(num_val) and num_val > 1e8 and "-" not in raw and ":" not in raw:
            epoch_sec = num_val / 1000.0 if num_val >= 1e11 else num_val
            return datetime.fromtimestamp(epoch_sec, tz=timezone.utc).astimezone(IST)
    except ValueError:
        pass

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if raw.endswith(" IST"):
        raw = raw[:-4].strip()
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unparseable candle timestamp: {ts!r}") from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def format_ist_timestamp(dt: Any) -> str:
    """Formats a timestamp consistently in Asia/Kolkata as 'YYYY-MM-DD HH:MM:SS'."""
    ist_dt = parse_ist_timestamp(dt)
    return ist_dt.strftime("%Y-%m-%d %H:%M:%S")


def is_within_nse_session(ts: Any) -> bool:
    """Returns True if the timestamp falls within standard NSE trading hours (09:15 to 15:30 IST)."""
    dt = parse_ist_timestamp(ts)
    t = dt.timetz().replace(tzinfo=None)
    return NSE_OPEN_TIME <= t <= NSE_CLOSE_TIME


def validate_candles(
    candles: List[Dict[str, Any]],
    deduplicate: bool = True,
    sort_chronologically: bool = False,
    interval_min: Optional[int] = None,
    now: Optional[Any] = None,
    default_is_simulated: bool = False,
) -> List[Dict[str, Any]]:
    """
    Validates and normalizes OHLCV candles to the standardized contract.
    """
    if not isinstance(candles, list):
        raise ValueError("Candles must be a list of dicts.")

    now_dt = parse_ist_timestamp(now) if now is not None else None
    bar_delta = timedelta(minutes=max(1, int(interval_min))) if interval_min is not None else None

    parsed_items = []
    for idx, c in enumerate(candles):
        if not isinstance(c, dict):
            raise ValueError(f"Candle at index {idx} is not a dict.")
        for key in ("timestamp", "open", "high", "low", "close", "volume"):
            if key not in c or c[key] is None or isinstance(c[key], bool):
                raise ValueError(f"Candle at index {idx} missing or invalid required field '{key}'.")

        dt = parse_ist_timestamp(c["timestamp"])
        try:
            o = float(c["open"])
            h = float(c["high"])
            l = float(c["low"])
            cl = float(c["close"])
            v = float(c["volume"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Candle at index {idx} has non-numeric OHLCV field.") from exc

        if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(cl)):
            raise ValueError(f"Candle at index {idx} has non-finite OHLC price.")
        if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
            raise ValueError(f"Candle at index {idx} has non-positive OHLC price.")
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"Candle at index {idx} has invalid volume: {v}")
        if h < l - 1e-9:
            raise ValueError(f"Candle at index {idx} violates high >= low ({h} < {l}).")
        if h < max(o, cl) - 1e-9:
            raise ValueError(f"Candle at index {idx} violates high >= max(open, close) ({h} < max({o}, {cl})).")
        if l > min(o, cl) + 1e-9:
            raise ValueError(f"Candle at index {idx} violates low <= min(open, close) ({l} > min({o}, {cl})).")

        explicit_complete = c.get("is_complete")
        if explicit_complete is False:
            is_complete = False
        elif now_dt is not None and bar_delta is not None:
            is_complete = (dt + bar_delta) <= now_dt
        else:
            is_complete = True if explicit_complete is None else bool(explicit_complete)

        is_sim = bool(c.get("is_simulated", default_is_simulated))
        norm_bar = dict(c)
        norm_bar.update({
            "timestamp": format_ist_timestamp(dt),
            "open": o,
            "high": h,
            "low": l,
            "close": cl,
            "volume": v,
            "is_complete": is_complete,
            "is_simulated": is_sim,
        })
        parsed_items.append((dt, idx, norm_bar))

    if sort_chronologically:
        parsed_items.sort(key=lambda item: (item[0], item[1]))

    validated: List[Dict[str, Any]] = []
    prev_dt: Optional[datetime] = None

    for dt, orig_idx, norm_bar in parsed_items:
        if prev_dt is not None:
            if dt < prev_dt:
                raise ValueError(
                    f"Candle timestamps moved backward at index {orig_idx}: {dt.isoformat()} < {prev_dt.isoformat()}"
                )
            if dt == prev_dt:
                if not deduplicate:
                    raise ValueError(f"Duplicate candle timestamp at index {orig_idx}: {dt.isoformat()}")
                validated[-1] = norm_bar
                continue
        prev_dt = dt
        validated.append(norm_bar)

    return validated


def aggregate_intraday_candles(
    source_candles: List[Dict[str, Any]],
    target_interval_min: int = 5,
    source_interval_min: int = 1,
    now: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    if target_interval_min <= 0 or source_interval_min <= 0 or target_interval_min % source_interval_min != 0:
        raise ValueError(
            f"target_interval_min ({target_interval_min}) must be a positive multiple of source_interval_min ({source_interval_min})."
        )
    required_bars = target_interval_min // source_interval_min
    now_dt = parse_ist_timestamp(now) if now is not None else None

    normalized = validate_candles(
        source_candles,
        deduplicate=True,
        sort_chronologically=True,
        interval_min=source_interval_min,
        now=now_dt,
    )
    if not normalized:
        return []

    buckets: Dict[datetime, List[Dict[str, Any]]] = {}
    for c in normalized:
        if c.get("is_complete") is False:
            continue
        dt = parse_ist_timestamp(c["timestamp"])
        t = dt.timetz().replace(tzinfo=None)
        if t < NSE_OPEN_TIME or t >= NSE_CLOSE_TIME:
            continue
        session_open = datetime(dt.year, dt.month, dt.day, 9, 15, tzinfo=IST)
        mins_since_open = int((dt - session_open).total_seconds() // 60)
        bucket_offset = (mins_since_open // target_interval_min) * target_interval_min
        bucket_start = session_open + timedelta(minutes=bucket_offset)
        buckets.setdefault(bucket_start, []).append(c)

    aggregated: List[Dict[str, Any]] = []
    bucket_delta = timedelta(minutes=target_interval_min)
    for bucket_start in sorted(buckets.keys()):
        bars = buckets[bucket_start]
        bucket_end = bucket_start + bucket_delta
        has_all_components = len(bars) == required_bars
        has_elapsed = True if now_dt is None else (bucket_end <= now_dt)
        is_complete = bool(has_all_components and has_elapsed and all(b.get("is_complete", True) for b in bars))

        aggregated.append({
            "timestamp": format_ist_timestamp(bucket_start),
            "open": bars[0]["open"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "close": bars[-1]["close"],
            "volume": round(sum(b["volume"] for b in bars), 2),
            "component_count": len(bars),
            "expected_components": required_bars,
            "is_complete": is_complete,
            "is_simulated": any(b.get("is_simulated", False) for b in bars),
        })

    return aggregated


def filter_completed_candles(
    candles: List[Dict[str, Any]],
    interval_min: int = 5,
    now: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    valid = validate_candles(candles, deduplicate=True, interval_min=interval_min, now=now)
    return [c for c in valid if c.get("is_complete") is True]


def validate_option_chain_for_strategy(option_chain: Dict[str, Any]) -> Tuple[int, float, Dict[str, Any]]:
    """
    Explicitly validates the option-chain contract and ATM strike row required by
    `evaluate_option_apex_oi_shift`. Never treats missing or None fields as zero.
    Returns `(atm_strike_int, pcr_float, validated_atm_row)`.
    Raises `ValueError` if required fields are missing, None, bool, non-numeric, or out of domain.
    """
    if not isinstance(option_chain, dict):
        raise ValueError("option_chain must be a dict.")

    for top_key in ("atm_strike", "pcr", "strikes"):
        if top_key not in option_chain or option_chain[top_key] is None or isinstance(option_chain[top_key], bool):
            raise ValueError(f"option_chain missing required field '{top_key}'.")

    try:
        atm_val = float(option_chain["atm_strike"])
        pcr_val = float(option_chain["pcr"])
    except (TypeError, ValueError) as exc:
        raise ValueError("option_chain 'atm_strike' and 'pcr' must be numeric.") from exc

    if not (math.isfinite(atm_val) and atm_val > 0):
        raise ValueError(f"option_chain has invalid atm_strike: {option_chain['atm_strike']!r}")
    if not (math.isfinite(pcr_val) and pcr_val > 0):
        raise ValueError(f"option_chain has invalid pcr: {option_chain['pcr']!r}")

    strikes = option_chain["strikes"]
    if not isinstance(strikes, list) or not strikes:
        raise ValueError("option_chain 'strikes' must be a non-empty list.")

    atm_int = int(round(atm_val))
    atm_row: Optional[Dict[str, Any]] = None
    for idx, row in enumerate(strikes):
        if not isinstance(row, dict):
            raise ValueError(f"option_chain strike row at index {idx} is not a dict.")
        if "strike" not in row or row["strike"] is None or isinstance(row["strike"], bool):
            raise ValueError(f"option_chain strike row at index {idx} missing 'strike'.")
        try:
            s_val = float(row["strike"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"option_chain strike at index {idx} is non-numeric.") from exc
        if not math.isfinite(s_val) or s_val <= 0:
            raise ValueError(f"option_chain strike at index {idx} must be finite and positive.")
        if int(round(s_val)) == atm_int:
            atm_row = row
            break

    if atm_row is None:
        raise LookupError(f"ATM strike {atm_int} not found in option_chain strikes.")

    required_strike_fields = ("ce_ltp", "pe_ltp", "ce_oi", "pe_oi", "ce_oi_change", "pe_oi_change")
    for req_key in required_strike_fields:
        if req_key not in atm_row or atm_row[req_key] is None or isinstance(atm_row[req_key], bool):
            raise ValueError(f"ATM strike {atm_int} missing required field '{req_key}'.")

    try:
        ce_ltp = float(atm_row["ce_ltp"])
        pe_ltp = float(atm_row["pe_ltp"])
        ce_oi = float(atm_row["ce_oi"])
        pe_oi = float(atm_row["pe_oi"])
        ce_oi_change = float(atm_row["ce_oi_change"])
        pe_oi_change = float(atm_row["pe_oi_change"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ATM strike {atm_int} has non-numeric OI or LTP field.") from exc

    if not all(math.isfinite(x) for x in (ce_ltp, pe_ltp, ce_oi, pe_oi, ce_oi_change, pe_oi_change)):
        raise ValueError(f"ATM strike {atm_int} contains non-finite OI or LTP values.")
    if ce_ltp <= 0 or pe_ltp <= 0:
        raise ValueError(f"ATM strike {atm_int} option LTP must be positive (ce_ltp={ce_ltp}, pe_ltp={pe_ltp}).")
    if ce_oi < 0 or pe_oi < 0:
        raise ValueError(f"ATM strike {atm_int} option OI cannot be negative (ce_oi={ce_oi}, pe_oi={pe_oi}).")

    validated_row = dict(atm_row)
    validated_row.update({
        "strike": atm_int,
        "ce_ltp": ce_ltp,
        "pe_ltp": pe_ltp,
        "ce_oi": int(round(ce_oi)),
        "pe_oi": int(round(pe_oi)),
        "ce_oi_change": int(round(ce_oi_change)),
        "pe_oi_change": int(round(pe_oi_change)),
    })
    return atm_int, pcr_val, validated_row


def calculate_indian_statutory_charges(turnover_inr: float, segment: str = "NSE_EQUITY_INTRADAY") -> float:
    if not math.isfinite(turnover_inr) or turnover_inr < 0:
        raise ValueError(f"Invalid turnover_inr: {turnover_inr}")
    if turnover_inr == 0:
        return 0.0
    brokerage = 40.0
    sell_turnover = turnover_inr / 2.0
    if segment == "NSE_FO_INDEX":
        stt = sell_turnover * 0.001
        exch_fee = turnover_inr * 0.0003503
    else:
        stt = sell_turnover * 0.00025
        exch_fee = turnover_inr * 0.0000307
    sebi_stamp = turnover_inr * 0.00002
    gst = 0.18 * (brokerage + exch_fee + sebi_stamp)
    return round(brokerage + stt + exch_fee + sebi_stamp + gst, 2)


def size_position(
    raw_entry_price, stop_loss, available_capital_inr, risk_pct, position_side,
    instrument_type="EQ", lot_size=None, contract_multiplier=1, cost_estimator=None,
) -> Dict[str, Any]:
    """Maximum whole-unit/whole-lot quantity satisfying risk AND capital limits.

    Quantities in this repository are underlying units, not lot counts; the only
    supported monetary multiplier is 1. Futures reserve full notional (no margin
    metadata exists). Options here are long premium signals only, never historical
    Strategy 3 execution. Scanner fees retain its existing estimated fee schedule.

    Estimated risk = ceil_cent(raw stop distance * quantity + modeled stop costs).
    Capital reserve = ceil_cent(max(rounded effective notional, raw notional plus
    entry slippage) + stop-exit charge reserve). Reservations are NOT P&L debits.
    Fees must be nonnegative/nondecreasing with quantity, as in both existing models.
    Decimal comparisons use no tolerance; exact cent boundaries are accepted.
    Gaps and unmodeled execution conditions can exceed this estimated stop loss.
    """
    rejected = {"eligible": False, "quantity": 0}

    def number(value, positive=True):
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("Numeric inputs must be numbers, not booleans or strings.")
        result = Decimal(str(value))
        if not result.is_finite() or (result <= 0 if positive else result < 0):
            raise ValueError("Numeric input outside its permitted finite range.")
        return result

    try:
        entry, stop = number(raw_entry_price), number(stop_loss)
        capital, percentage = number(available_capital_inr), number(risk_pct)
        multiplier = number(contract_multiplier)
        if multiplier != 1 or percentage > 100:
            raise ValueError("Only unit multiplier 1 and risk percentages <= 100 are supported.")
        if position_side not in ("LONG", "SHORT"):
            raise ValueError("Invalid position side.")
        if (position_side == "LONG" and stop >= entry) or (position_side == "SHORT" and stop <= entry):
            raise ValueError("Stop must be strictly on the loss side of entry.")
        if instrument_type not in ("EQ", "FUTIDX", "OPTIDX"):
            raise ValueError("Unsupported executable instrument type.")
        lot = 1 if lot_size is None and instrument_type == "EQ" else lot_size
        if isinstance(lot, bool) or not isinstance(lot, int) or lot <= 0:
            raise ValueError("An explicit positive integer lot is required for derivatives.")
        if instrument_type == "EQ" and lot != 1:
            raise ValueError("Equity quantity increments must be one share.")
        if instrument_type == "OPTIDX" and position_side != "LONG":
            raise ValueError("Short option premium positions are unsupported.")
        budget = (capital * percentage / 100).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
        distance = abs(entry - stop)

        def estimate(quantity):
            if cost_estimator is None:
                segment = "NSE_EQUITY_INTRADAY" if instrument_type == "EQ" else "NSE_FO_INDEX"
                costs = {"charges_inr": calculate_indian_statutory_charges(
                    float((entry + stop) * quantity), segment),
                    "slippage_inr": 0.0, "entry_slippage_inr": 0.0,
                    "effective_entry_price": float(entry)}
            else:
                costs = cost_estimator(quantity)
            charges = number(costs["charges_inr"], positive=False)
            slippage = number(costs["slippage_inr"], positive=False)
            entry_slippage = number(costs["entry_slippage_inr"], positive=False)
            effective = number(costs["effective_entry_price"])
            if entry_slippage > slippage:
                raise ValueError("Entry slippage cannot exceed total slippage.")
            if (position_side == "LONG" and effective < entry) or (position_side == "SHORT" and effective > entry):
                raise ValueError("Effective entry must apply adverse slippage.")
            risk = (distance * quantity + charges + slippage).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
            reserve = (max(effective * quantity, entry * quantity + entry_slippage) + charges).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING)
            return risk, reserve, costs

        minimum_risk, minimum_capital, _ = estimate(lot)
        context = {"risk_budget_inr": float(budget), "available_capital_inr": float(capital),
                   "minimum_quantity": lot, "minimum_estimated_risk_inr": float(minimum_risk),
                   "minimum_capital_required_inr": float(minimum_capital)}
        if minimum_capital > capital:
            return {**rejected, **context, "reason_code": "INSUFFICIENT_CAPITAL"}
        if minimum_risk > budget:
            return {**rejected, **context, "reason_code": "INSUFFICIENT_RISK_BUDGET"}
        # Raw bounds are optimistic upper limits; binary search includes exact costs.
        upper = min(int(budget // (distance * lot)), int(capital // (entry * lot)))
        low, high = 1, upper
        while low < high:
            mid = (low + high + 1) // 2
            risk, reserve, _ = estimate(mid * lot)
            if risk <= budget and reserve <= capital:
                low = mid
            else:
                high = mid - 1
        quantity = low * lot
        risk, reserve, costs = estimate(quantity)
        return {"eligible": True, "reason_code": "SIZED_WITHIN_RISK_AND_CAPITAL", "quantity": quantity,
                **context, "estimated_risk_inr": float(risk), "capital_required_inr": float(reserve),
                "raw_stop_distance": float(distance), "estimated_charges_inr": float(costs["charges_inr"]),
                "estimated_slippage_inr": float(costs["slippage_inr"]),
                "effective_entry_price": float(costs["effective_entry_price"]),
                "lot_size": lot, "contract_multiplier": 1}
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError):
        return {**rejected, "reason_code": "INVALID_SIZING_INPUT"}


def compute_ema(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("EMA period must be positive.")
    if not values:
        return []
    for v in values:
        if not math.isfinite(float(v)):
            raise ValueError(f"Non-finite value in EMA input: {v}")
    k = 2.0 / (period + 1)
    ema = [float(values[0])]
    for v in values[1:]:
        ema.append(float(v) * k + ema[-1] * (1.0 - k))
    return ema


def compute_rsi(closes: List[float], period: int = 14) -> List[float]:
    if period <= 0:
        raise ValueError("RSI period must be positive.")
    if not closes:
        return []
    clean_closes: List[float] = []
    for c in closes:
        val = float(c)
        if not math.isfinite(val):
            raise ValueError(f"Non-finite close in RSI input: {c}")
        clean_closes.append(val)

    if len(clean_closes) == 1:
        return [50.0]

    rsis: List[float] = [50.0]
    gains: List[float] = []
    losses: List[float] = []
    avg_gain = 0.0
    avg_loss = 0.0

    for i in range(1, len(clean_closes)):
        diff = clean_closes[i] - clean_closes[i - 1]
        gain = max(0.0, diff)
        loss = max(0.0, -diff)
        gains.append(gain)
        losses.append(loss)

        if i < period:
            avg_gain = sum(gains) / len(gains)
            avg_loss = sum(losses) / len(losses)
        elif i == period:
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
        else:
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_gain == 0.0 and avg_loss == 0.0:
            rsis.append(50.0)
        elif avg_loss == 0.0:
            rsis.append(100.0)
        elif avg_gain == 0.0:
            rsis.append(0.0)
        else:
            rs = avg_gain / avg_loss
            rsis.append(round(100.0 - (100.0 / (1.0 + rs)), 2))

    return rsis


def compute_atr(candles: List[Dict[str, Any]], period: int = 10) -> List[float]:
    if period <= 0:
        raise ValueError("ATR period must be positive.")
    if not candles:
        return []

    trs: List[float] = []
    for i, c in enumerate(candles):
        h = float(c["high"])
        l = float(c["low"])
        cl = float(c["close"])
        if not (math.isfinite(h) and math.isfinite(l) and math.isfinite(cl)):
            raise ValueError(f"Non-finite OHLC value in ATR input at index {i}")
        if h < l - 1e-9:
            raise ValueError(f"Invalid candle high < low in ATR input at index {i}")
        if i == 0:
            trs.append(max(0.0, h - l))
        else:
            pc = float(candles[i - 1]["close"])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    atrs: List[float] = []
    for i, tr in enumerate(trs):
        if i < period:
            atrs.append(sum(trs[: i + 1]) / (i + 1))
        else:
            prev_atr = atrs[-1]
            atrs.append((prev_atr * (period - 1) + tr) / period)
    return atrs


def compute_session_vwap(candles: List[Dict[str, Any]]) -> List[float]:
    vwaps: List[float] = []
    cum_pv = 0.0
    cum_vol = 0.0
    current_day = None
    for c in candles:
        dt = parse_ist_timestamp(c["timestamp"])
        day = dt.strftime("%Y-%m-%d")
        if day != current_day:
            current_day = day
            cum_pv = 0.0
            cum_vol = 0.0
        typ = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        v = float(c["volume"])
        if not math.isfinite(typ) or not math.isfinite(v) or v < 0:
            raise ValueError("Invalid price or volume in compute_session_vwap.")
        if v > 0:
            cum_pv += typ * v
            cum_vol += v
        vwap_val = (cum_pv / cum_vol) if cum_vol > 0 else typ
        vwaps.append(round(vwap_val, 2))
    return vwaps


def compute_supertrend(candles: List[Dict[str, Any]], period: int = 10, multiplier: float = 3.0):
    atrs = compute_atr(candles, period)
    st_line: List[float] = []
    st_dir: List[int] = []  # 1 for green/bullish, -1 for red/bearish
    final_upper = 0.0
    final_lower = 0.0
    curr_dir = 1
    for i, c in enumerate(candles):
        hl2 = (float(c["high"]) + float(c["low"])) / 2.0
        basic_upper = hl2 + multiplier * atrs[i]
        basic_lower = hl2 - multiplier * atrs[i]
        if i == 0:
            final_upper = basic_upper
            final_lower = basic_lower
            curr_dir = 1
        else:
            prev_close = float(candles[i - 1]["close"])
            if basic_upper < final_upper or prev_close > final_upper:
                final_upper = basic_upper
            if basic_lower > final_lower or prev_close < final_lower:
                final_lower = basic_lower
            if float(c["close"]) > final_upper:
                curr_dir = 1
            elif float(c["close"]) < final_lower:
                curr_dir = -1
        st_dir.append(curr_dir)
        st_line.append(round(final_lower if curr_dir == 1 else final_upper, 2))
    return st_line, st_dir


# ============================================================================
# STRATEGY 1: Institutional Order Block + BOS / Fair Value Gap (OrderBlock.com)
# Supports symmetric Bullish (BUY) and Bearish (SELL) evaluation + First-Retest Mitigation
# ============================================================================
def evaluate_order_block_fvg(
    symbol: str,
    candles: List[Dict[str, Any]],
    capital_inr: float = 150000.0,
    risk_pct: float = 1.0,
    segment: str = "NSE_EQUITY_INTRADAY",
    now: Optional[Any] = None,
    market_breadth: Optional[Dict[str, Any]] = None,
    mitigated_zones: Optional[Set[str]] = None,
    lot_size: Optional[int] = None,
    execution_costs=None,
    evaluation_trace=None,
) -> Optional[TradeSignal]:
    completed = filter_completed_candles(candles, interval_min=5, now=now)
    if not _evaluation_warmup(evaluation_trace, completed, 30):
        return None
    atrs = compute_atr(completed, 10)
    vwaps = compute_session_vwap(completed)
    recent = completed[-15:]
    last = recent[-1]
    if not _evaluation_check(evaluation_trace, "session.nse", is_within_nse_session(last["timestamp"]),
            "OUTSIDE_NSE_SESSION", unavailable=True):
        return None
    if not _evaluation_session_start(evaluation_trace, completed):
        return None
    curr_atr = max(0.05, atrs[-1])
    curr_vwap = vwaps[-1]
    avg_vol_20 = sum(c["volume"] for c in completed[-21:-1]) / 20.0
    rvol = last["volume"] / max(1.0, avg_vol_20)

    for idx in range(len(recent) - 4, 1, -1):
        ob_bar = recent[idx - 1]
        imp_1 = recent[idx]
        imp_2 = recent[idx + 1]
        zone_low = float(ob_bar["low"])
        zone_high = float(ob_bar["high"])
        subsequent = recent[idx + 2:]
        prior_post_impulse = subsequent[:-1]

        # --------------------------------------------------------------------
        # 1. Bullish Order Block + BOS / FVG Evaluation
        # --------------------------------------------------------------------
        is_red = ob_bar["close"] < ob_bar["open"]
        bos_bull = imp_1["close"] > zone_high or imp_2["close"] > zone_high
        displacement_bull = imp_2["close"] - ob_bar["open"]
        fvg_bull = imp_2["low"] > zone_high

        if (_evaluation_check(evaluation_trace, "ob.bull.origin", is_red, "BULL_BLOCK_NOT_RED", candidate_timestamp=ob_bar["timestamp"])
                and _evaluation_check(evaluation_trace, "ob.bull.bos", bos_bull, "BULL_BREAK_OF_STRUCTURE_MISSING")
                and _evaluation_check(evaluation_trace, "ob.bull.displacement", fvg_bull or displacement_bull >= 1.5 * curr_atr,
                    "BULL_FVG_OR_DISPLACEMENT_MISSING", fvg=fvg_bull, displacement=displacement_bull, required_displacement=1.5 * curr_atr)):
            bull_zone_key = f"{symbol}:OB:BULL:{ob_bar['timestamp']}"
            invalidated_bull = any(b["close"] < zone_low for b in subsequent)
            prior_mitigated_bull = any(b["low"] <= zone_high * 1.0015 for b in prior_post_impulse)
            if mitigated_zones is not None and prior_mitigated_bull:
                mitigated_zones.add(bull_zone_key)

            already_used_bull = prior_mitigated_bull or (
                mitigated_zones is not None and bull_zone_key in mitigated_zones
            )
            retested_bull = (
                last["low"] <= zone_high * 1.0015
                and last["close"] > ob_bar["open"]
                and last["close"] >= zone_low
            )

            if (_evaluation_check(evaluation_trace, "ob.bull.validity", not invalidated_bull, "BULL_BLOCK_INVALIDATED", zone_low=zone_low)
                    and _evaluation_check(evaluation_trace, "ob.bull.first_retest", not already_used_bull, "BULL_BLOCK_ALREADY_MITIGATED")
                    and _evaluation_check(evaluation_trace, "ob.bull.retest", retested_bull, "BULL_RETEST_NOT_HELD")):
                entry = round(last["close"], 2)
                sl = round(zone_low - 0.25 * curr_atr, 2)
                risk_per_share = max(0.5, entry - sl)
                t1 = round(entry + 2.0 * risk_per_share, 2)
                t2 = round(entry + 3.0 * risk_per_share, 2)
                sizing = size_position(entry, sl, capital_inr, risk_pct, "LONG",
                                       instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                                       lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                           lambda q: execution_costs(entry, sl, q, "LONG")))
                if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
                    return None
                if mitigated_zones is not None:
                    mitigated_zones.add(bull_zone_key)
                qty = sizing["quantity"]
                est_charges = sizing["estimated_charges_inr"]
                vwap_dist_atr = (entry - curr_vwap) / curr_atr
                disp_atr = max(0.0, displacement_bull) / curr_atr
                q_score, q_breakdown = compute_setup_quality_score(
                    rvol=rvol,
                    vwap_dist_atr=vwap_dist_atr,
                    displacement_atr=disp_atr,
                    market_breadth=market_breadth,
                    is_bullish=True,
                )
                return TradeSignal(
                    symbol=symbol,
                    segment=segment,
                    strategy_id="strat_1_order_block",
                    strategy_name="Order Block + BOS & FVG Retest",
                    direction="BULLISH (BUY)",
                    instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
                    entry_price=entry,
                    entry_zone_low=round(zone_low, 2),
                    entry_zone_high=round(zone_high, 2),
                    stop_loss=sl,
                    target_1=t1,
                    target_2=t2,
                    risk_reward="1:2.0 / 1:3.0",
                    confidence_pct=q_score,
                    win_rate_benchmark="58%–64% (OrderBlock.com 5m F&O Rules)",
                    position_qty=qty,
                    capital_risk_inr=sizing["estimated_risk_inr"],
                    est_charges_inr=est_charges,
                    rationale=(
                        f"5m Bullish Order Block [{zone_low:.2f}–{zone_high:.2f}] formed prior to Break of Structure "
                        f"with Fair Value Gap (FVG) up to {imp_2['low']:.2f}. First unmitigated retest held with buyer rejection."
                    ),
                    timestamp=format_ist_timestamp(last["timestamp"]),
                    invalidation_level=round(zone_low, 2),
                    quality_score=q_score,
                    score_breakdown=q_breakdown,
                )

        # --------------------------------------------------------------------
        # 2. Bearish Order Block + BOS / FVG Evaluation
        # --------------------------------------------------------------------
        is_green = ob_bar["close"] > ob_bar["open"]
        bos_bear = imp_1["close"] < zone_low or imp_2["close"] < zone_low
        displacement_bear = ob_bar["open"] - imp_2["close"]
        fvg_bear = imp_2["high"] < zone_low

        if (_evaluation_check(evaluation_trace, "ob.bear.origin", is_green, "BEAR_BLOCK_NOT_GREEN", candidate_timestamp=ob_bar["timestamp"])
                and _evaluation_check(evaluation_trace, "ob.bear.bos", bos_bear, "BEAR_BREAK_OF_STRUCTURE_MISSING")
                and _evaluation_check(evaluation_trace, "ob.bear.displacement", fvg_bear or displacement_bear >= 1.5 * curr_atr,
                    "BEAR_FVG_OR_DISPLACEMENT_MISSING", fvg=fvg_bear, displacement=displacement_bear, required_displacement=1.5 * curr_atr)):
            bear_zone_key = f"{symbol}:OB:BEAR:{ob_bar['timestamp']}"
            invalidated_bear = any(b["close"] > zone_high for b in subsequent)
            prior_mitigated_bear = any(b["high"] >= zone_low * 0.9985 for b in prior_post_impulse)
            if mitigated_zones is not None and prior_mitigated_bear:
                mitigated_zones.add(bear_zone_key)

            already_used_bear = prior_mitigated_bear or (
                mitigated_zones is not None and bear_zone_key in mitigated_zones
            )
            retested_bear = (
                last["high"] >= zone_low * 0.9985
                and last["close"] < ob_bar["open"]
                and last["close"] <= zone_high
            )

            if (_evaluation_check(evaluation_trace, "ob.bear.validity", not invalidated_bear, "BEAR_BLOCK_INVALIDATED", zone_high=zone_high)
                    and _evaluation_check(evaluation_trace, "ob.bear.first_retest", not already_used_bear, "BEAR_BLOCK_ALREADY_MITIGATED")
                    and _evaluation_check(evaluation_trace, "ob.bear.retest", retested_bear, "BEAR_RETEST_NOT_HELD")):
                entry = round(last["close"], 2)
                sl = round(zone_high + 0.25 * curr_atr, 2)
                risk_per_share = max(0.5, sl - entry)
                t1 = round(entry - 2.0 * risk_per_share, 2)
                t2 = round(entry - 3.0 * risk_per_share, 2)
                sizing = size_position(entry, sl, capital_inr, risk_pct, "SHORT",
                                       instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                                       lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                           lambda q: execution_costs(entry, sl, q, "SHORT")))
                if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
                    return None
                if mitigated_zones is not None:
                    mitigated_zones.add(bear_zone_key)
                qty = sizing["quantity"]
                est_charges = sizing["estimated_charges_inr"]
                vwap_dist_atr = (curr_vwap - entry) / curr_atr
                disp_atr = max(0.0, displacement_bear) / curr_atr
                q_score, q_breakdown = compute_setup_quality_score(
                    rvol=rvol,
                    vwap_dist_atr=vwap_dist_atr,
                    displacement_atr=disp_atr,
                    market_breadth=market_breadth,
                    is_bullish=False,
                )
                return TradeSignal(
                    symbol=symbol,
                    segment=segment,
                    strategy_id="strat_1_order_block",
                    strategy_name="Order Block + BOS & FVG Retest",
                    direction="BEARISH (SELL)",
                    instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
                    entry_price=entry,
                    entry_zone_low=round(zone_low, 2),
                    entry_zone_high=round(zone_high, 2),
                    stop_loss=sl,
                    target_1=t1,
                    target_2=t2,
                    risk_reward="1:2.0 / 1:3.0",
                    confidence_pct=q_score,
                    win_rate_benchmark="58%–64% (OrderBlock.com 5m F&O Rules)",
                    position_qty=qty,
                    capital_risk_inr=sizing["estimated_risk_inr"],
                    est_charges_inr=est_charges,
                    rationale=(
                        f"5m Bearish Order Block [{zone_low:.2f}–{zone_high:.2f}] formed prior to bearish Break of Structure "
                        f"with Fair Value Gap (FVG) down to {imp_2['high']:.2f}. First unmitigated retest rejected by sellers."
                    ),
                    timestamp=format_ist_timestamp(last["timestamp"]),
                    invalidation_level=round(zone_high, 2),
                    quality_score=q_score,
                    score_breakdown=q_breakdown,
                )

    return None


# ============================================================================
# STRATEGY 2: Institutional VWAP Pullback / Rejection + 20 EMA & Volume Surge
# ============================================================================
def evaluate_vwap_pullback(
    symbol: str,
    candles: List[Dict[str, Any]],
    capital_inr: float = 150000.0,
    risk_pct: float = 1.0,
    segment: str = "NSE_EQUITY_INTRADAY",
    now: Optional[Any] = None,
    market_breadth: Optional[Dict[str, Any]] = None,
    lot_size: Optional[int] = None,
    execution_costs=None,
    evaluation_trace=None,
) -> Optional[TradeSignal]:
    completed = filter_completed_candles(candles, interval_min=5, now=now)
    if not _evaluation_warmup(evaluation_trace, completed, 35):
        return None
    last = completed[-1]
    if not _evaluation_check(evaluation_trace, "session.nse", is_within_nse_session(last["timestamp"]), "OUTSIDE_NSE_SESSION", unavailable=True):
        return None
    if not _evaluation_session_start(evaluation_trace, completed):
        return None

    closes = [c["close"] for c in completed]
    vwaps = compute_session_vwap(completed)
    ema20 = compute_ema(closes, 20)
    rsis = compute_rsi(closes, 14)
    atrs = compute_atr(completed, 10)

    curr_vwap = vwaps[-1]
    curr_ema = ema20[-1]
    curr_rsi = rsis[-1]
    curr_atr = max(0.05, atrs[-1])
    avg_vol_20 = sum(c["volume"] for c in completed[-21:-1]) / 20.0
    if not _evaluation_check(evaluation_trace, "volume.baseline", avg_vol_20 > 0, "POSITIVE_BASELINE_VOLUME_REQUIRED", unavailable=True, baseline_volume=avg_vol_20):
        return None

    rvol = last["volume"] / avg_vol_20
    vol_surge = last["volume"] >= 1.4 * avg_vol_20

    # 1. Bullish VWAP Pullback & Reclaim
    touched_vwap_bull = last["low"] <= curr_vwap * 1.0025
    bullish_reclaim = (
        last["close"] > curr_vwap
        and last["close"] > last["open"]
        and last["close"] >= curr_ema * 0.998
    )
    rsi_bull_ok = 48.0 <= curr_rsi <= 72.0

    if (_evaluation_check(evaluation_trace, "vwap.bull.touch", touched_vwap_bull, "BULL_VWAP_TOUCH_MISSING", low=last["low"], threshold=curr_vwap * 1.0025)
            and _evaluation_check(evaluation_trace, "vwap.bull.reclaim", bullish_reclaim, "BULL_VWAP_EMA_RECLAIM_MISSING", close=last["close"], vwap=curr_vwap, ema20=curr_ema)
            and _evaluation_check(evaluation_trace, "volume.surge", vol_surge, "VOLUME_SURGE_BELOW_1_4", rvol=rvol, threshold=1.4)
            and _evaluation_check(evaluation_trace, "rsi.bull", rsi_bull_ok, "RSI_OUTSIDE_BULL_48_72", rsi14=curr_rsi, minimum=48.0, maximum=72.0)):
        entry = round(last["close"], 2)
        sl = round(min(last["low"], curr_vwap) - 0.35 * curr_atr, 2)
        risk_per_share = max(0.5, entry - sl)
        t1 = round(entry + 1.8 * risk_per_share, 2)
        t2 = round(entry + 2.5 * risk_per_share, 2)
        sizing = size_position(entry, sl, capital_inr, risk_pct, "LONG",
                               instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                               lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(entry, sl, q, "LONG")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (entry - curr_vwap) / curr_atr
        disp_atr = (last["close"] - last["low"]) / curr_atr
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=True,
        )
        return TradeSignal(
            symbol=symbol,
            segment=segment,
            strategy_id="strat_2_vwap_pullback",
            strategy_name="Institutional VWAP Pullback + Volume",
            direction="BULLISH (BUY)",
            instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
            entry_price=entry,
            entry_zone_low=round(min(curr_vwap, entry), 2),
            entry_zone_high=round(max(curr_vwap, entry), 2),
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:1.8 / 1:2.5",
            confidence_pct=q_score,
            win_rate_benchmark="65% Nifty / 68% BankNifty / 63% Equity (OneTradeJournal)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Price pulled back to session VWAP ({curr_vwap:.2f}) and reclaimed 20 EMA ({curr_ema:.2f}) "
                f"on {rvol:.1f}x relative volume with RSI(14) at {curr_rsi:.1f}."
            ),
            timestamp=format_ist_timestamp(last["timestamp"]),
            invalidation_level=round(min(last["low"], curr_vwap), 2),
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    # 2. Bearish VWAP Pullback & Rejection
    tested_vwap_bear = last["high"] >= curr_vwap * 0.9975
    bearish_rejection = (
        last["close"] < curr_vwap
        and last["close"] < last["open"]
        and last["close"] <= curr_ema * 1.002
    )
    rsi_bear_ok = 28.0 <= curr_rsi <= 52.0

    if (_evaluation_check(evaluation_trace, "vwap.bear.touch", tested_vwap_bear, "BEAR_VWAP_TOUCH_MISSING", high=last["high"], threshold=curr_vwap * 0.9975)
            and _evaluation_check(evaluation_trace, "vwap.bear.rejection", bearish_rejection, "BEAR_VWAP_EMA_REJECTION_MISSING", close=last["close"], vwap=curr_vwap, ema20=curr_ema)
            and _evaluation_check(evaluation_trace, "volume.surge", vol_surge, "VOLUME_SURGE_BELOW_1_4", rvol=rvol, threshold=1.4)
            and _evaluation_check(evaluation_trace, "rsi.bear", rsi_bear_ok, "RSI_OUTSIDE_BEAR_28_52", rsi14=curr_rsi, minimum=28.0, maximum=52.0)):
        entry = round(last["close"], 2)
        sl = round(max(last["high"], curr_vwap) + 0.35 * curr_atr, 2)
        risk_per_share = max(0.5, sl - entry)
        t1 = round(entry - 1.8 * risk_per_share, 2)
        t2 = round(entry - 2.5 * risk_per_share, 2)
        sizing = size_position(entry, sl, capital_inr, risk_pct, "SHORT",
                               instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                               lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(entry, sl, q, "SHORT")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (curr_vwap - entry) / curr_atr
        disp_atr = (last["high"] - last["close"]) / curr_atr
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=False,
        )
        return TradeSignal(
            symbol=symbol,
            segment=segment,
            strategy_id="strat_2_vwap_pullback",
            strategy_name="Institutional VWAP Pullback + Volume",
            direction="BEARISH (SELL)",
            instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
            entry_price=entry,
            entry_zone_low=round(min(curr_vwap, entry), 2),
            entry_zone_high=round(max(curr_vwap, entry), 2),
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:1.8 / 1:2.5",
            confidence_pct=q_score,
            win_rate_benchmark="65% Nifty / 68% BankNifty / 63% Equity (OneTradeJournal)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Price rallied into session VWAP ({curr_vwap:.2f}) and rejected below 20 EMA ({curr_ema:.2f}) "
                f"on {rvol:.1f}x relative volume with RSI(14) at {curr_rsi:.1f}."
            ),
            timestamp=format_ist_timestamp(last["timestamp"]),
            invalidation_level=round(max(last["high"], curr_vwap), 2),
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    return None


# ============================================================================
# STRATEGY 3: Option Apex — OI Shift Trap + PCR & VWAP (Nifty 50 & Bank Nifty F&O Only)
# ============================================================================
def evaluate_option_apex_oi_shift(
    index_symbol: str,
    candles: List[Dict[str, Any]],
    option_chain: Dict[str, Any],
    lot_size: Optional[int] = None,
    capital_inr: float = 150000.0,
    risk_pct: float = 1.0,
    now: Optional[Any] = None,
    market_breadth: Optional[Dict[str, Any]] = None,
    execution_costs=None,
    evaluation_trace=None,
) -> Optional[TradeSignal]:
    if not _evaluation_check(evaluation_trace, "option.index", index_symbol in ("NIFTY", "BANKNIFTY"), "UNSUPPORTED_OPTION_INDEX", unavailable=True):
        return None
    if not _evaluation_check(evaluation_trace, "option.candles", bool(candles), "OPTION_UNDERLYING_CANDLES_REQUIRED", unavailable=True):
        _evaluation_warmup(evaluation_trace, [], 1)
        return None
    if not _evaluation_check(evaluation_trace, "option.chain", option_chain is not None and option_chain != {}, "OPTION_CHAIN_REQUIRED", unavailable=True):
        return None
    completed = filter_completed_candles(candles, interval_min=5, now=now)
    if not _evaluation_warmup(evaluation_trace, completed, 1):
        return None
    last = completed[-1]
    if not _evaluation_check(evaluation_trace, "session.nse", is_within_nse_session(last["timestamp"]), "OUTSIDE_NSE_SESSION", unavailable=True):
        return None
    if not _evaluation_session_start(evaluation_trace, completed):
        return None

    try:
        atm, pcr, atm_row = validate_option_chain_for_strategy(option_chain)
    except LookupError:
        _evaluation_check(evaluation_trace, "option.atm", False, "ATM_STRIKE_ROW_MISSING", unavailable=True)
        return None
    _evaluation_check(evaluation_trace, "option.atm", True, "ATM_STRIKE_ROW_MISSING", atm_strike=atm, pcr=pcr)

    vwaps = compute_session_vwap(completed)
    atrs = compute_atr(completed, 10)
    curr_vwap = vwaps[-1]
    curr_atr = max(0.05, atrs[-1])
    prior_bars = completed[-21:-1] if len(completed) >= 21 else completed[:-1]
    avg_vol = (sum(c["volume"] for c in prior_bars) / len(prior_bars)) if prior_bars else last["volume"]
    rvol = last["volume"] / max(1.0, avg_vol)
    is_sim = bool(option_chain.get("is_simulated", False))

    ce_oi_chg = atm_row["ce_oi_change"]
    pe_oi_chg = atm_row["pe_oi_change"]

    # 1. Bullish Option Apex: ATM Call unwinding (< 0) + ATM Put writing (> 0) + PCR >= 1.10 + Spot >= VWAP * 0.998
    if (_evaluation_check(evaluation_trace, "oi.bull.call_unwinding", ce_oi_chg < 0, "CALL_UNWINDING_REQUIRED", ce_oi_change=ce_oi_chg)
            and _evaluation_check(evaluation_trace, "oi.bull.put_writing", pe_oi_chg > 0, "PUT_WRITING_REQUIRED", pe_oi_change=pe_oi_chg)
            and _evaluation_check(evaluation_trace, "pcr.bull", pcr >= 1.10, "PCR_BELOW_1_10", pcr=pcr, threshold=1.10)
            and _evaluation_check(evaluation_trace, "vwap.bull.spot", last["close"] >= curr_vwap * 0.998, "SPOT_BELOW_BULL_VWAP_THRESHOLD", close=last["close"], threshold=curr_vwap * 0.998)):
        opt_premium = round(float(atm_row["ce_ltp"]), 2)
        sl_premium = round(opt_premium * 0.78, 2)
        risk_per_unit = max(1.0, opt_premium - sl_premium)
        t1_premium = round(opt_premium + 1.6 * risk_per_unit, 2)
        t2_premium = round(opt_premium + 2.4 * risk_per_unit, 2)
        sizing = size_position(opt_premium, sl_premium, capital_inr, risk_pct, "LONG",
                               instrument_type="OPTIDX", lot_size=lot_size,
                               cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(opt_premium, sl_premium, q, "LONG")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        lots = qty // lot_size
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (last["close"] - curr_vwap) / curr_atr
        disp_atr = abs(last["close"] - last["open"]) / curr_atr + min(1.5, (pcr - 1.0))
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=True,
        )
        return TradeSignal(
            symbol=index_symbol,
            segment="NSE_FO_INDEX",
            strategy_id="strat_3_option_apex_oi",
            strategy_name="Option Apex OI Shift Trap + PCR",
            direction="BULLISH (BUY CE)",
            instrument_label=f"{index_symbol} {atm} CE ({lots} Lot{'s' if lots > 1 else ''} = {qty} Qty)",
            entry_price=opt_premium,
            entry_zone_low=round(opt_premium * 0.97, 2),
            entry_zone_high=round(opt_premium * 1.02, 2),
            stop_loss=sl_premium,
            target_1=t1_premium,
            target_2=t2_premium,
            risk_reward="1:1.6 / 1:2.4",
            confidence_pct=q_score,
            win_rate_benchmark="60% Win Rate (ICFM India / TradeFinder Option Apex)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Short covering at {atm} CE (OI Δ {ce_oi_chg:,}) paired with heavy Put writing "
                f"at {atm} PE (OI Δ +{pe_oi_chg:,}). Aggregate PCR = {pcr:.2f} with spot holding above VWAP ({curr_vwap:.2f})."
            ),
            timestamp=format_ist_timestamp(last["timestamp"]),
            is_simulated=is_sim,
            data_mode="SIMULATED" if is_sim else "LIVE",
            position_type="LONG_CALL_OPTION",
            invalidation_level=sl_premium,
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    # 2. Bearish Option Apex: ATM Put unwinding (< 0) + ATM Call writing (> 0) + PCR <= 0.85 + Spot <= VWAP * 1.002
    if (_evaluation_check(evaluation_trace, "oi.bear.put_unwinding", pe_oi_chg < 0, "PUT_UNWINDING_REQUIRED", pe_oi_change=pe_oi_chg)
            and _evaluation_check(evaluation_trace, "oi.bear.call_writing", ce_oi_chg > 0, "CALL_WRITING_REQUIRED", ce_oi_change=ce_oi_chg)
            and _evaluation_check(evaluation_trace, "pcr.bear", pcr <= 0.85, "PCR_ABOVE_0_85", pcr=pcr, threshold=0.85)
            and _evaluation_check(evaluation_trace, "vwap.bear.spot", last["close"] <= curr_vwap * 1.002, "SPOT_ABOVE_BEAR_VWAP_THRESHOLD", close=last["close"], threshold=curr_vwap * 1.002)):
        opt_premium = round(float(atm_row["pe_ltp"]), 2)
        sl_premium = round(opt_premium * 0.78, 2)
        risk_per_unit = max(1.0, opt_premium - sl_premium)
        t1_premium = round(opt_premium + 1.6 * risk_per_unit, 2)
        t2_premium = round(opt_premium + 2.4 * risk_per_unit, 2)
        sizing = size_position(opt_premium, sl_premium, capital_inr, risk_pct, "LONG",
                               instrument_type="OPTIDX", lot_size=lot_size,
                               cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(opt_premium, sl_premium, q, "LONG")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        lots = qty // lot_size
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (curr_vwap - last["close"]) / curr_atr
        disp_atr = abs(last["open"] - last["close"]) / curr_atr + min(1.5, max(0.0, 1.0 - pcr))
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=False,
        )
        return TradeSignal(
            symbol=index_symbol,
            segment="NSE_FO_INDEX",
            strategy_id="strat_3_option_apex_oi",
            strategy_name="Option Apex OI Shift Trap + PCR",
            direction="BEARISH (BUY PE)",
            instrument_label=f"{index_symbol} {atm} PE ({lots} Lot{'s' if lots > 1 else ''} = {qty} Qty)",
            entry_price=opt_premium,
            entry_zone_low=round(opt_premium * 0.97, 2),
            entry_zone_high=round(opt_premium * 1.02, 2),
            stop_loss=sl_premium,
            target_1=t1_premium,
            target_2=t2_premium,
            risk_reward="1:1.6 / 1:2.4",
            confidence_pct=q_score,
            win_rate_benchmark="60% Win Rate (ICFM India / TradeFinder Option Apex)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Put unwinding at {atm} PE (OI Δ {pe_oi_chg:,}) paired with aggressive Call writing "
                f"at {atm} CE (OI Δ +{ce_oi_chg:,}). Aggregate PCR = {pcr:.2f} with spot rejected below VWAP ({curr_vwap:.2f})."
            ),
            timestamp=format_ist_timestamp(last["timestamp"]),
            is_simulated=is_sim,
            data_mode="SIMULATED" if is_sim else "LIVE",
            position_type="LONG_PUT_OPTION",
            invalidation_level=sl_premium,
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    return None


# ============================================================================
# STRATEGY 4: 15-Minute Opening Range Breakout / Breakdown (ORB) + RVOL & RSI Filter
# ============================================================================
def evaluate_orb_breakout(
    symbol: str,
    candles: List[Dict[str, Any]],
    capital_inr: float = 150000.0,
    risk_pct: float = 1.0,
    segment: str = "NSE_EQUITY_INTRADAY",
    now: Optional[Any] = None,
    market_breadth: Optional[Dict[str, Any]] = None,
    lot_size: Optional[int] = None,
    execution_costs=None,
    evaluation_trace=None,
) -> Optional[TradeSignal]:
    completed = filter_completed_candles(candles, interval_min=5, now=now)
    if not _evaluation_warmup(evaluation_trace, completed, 30):
        return None
    last = completed[-1]
    last_dt = parse_ist_timestamp(last["timestamp"])
    if not _evaluation_check(evaluation_trace, "session.nse", is_within_nse_session(last_dt), "OUTSIDE_NSE_SESSION", unavailable=True):
        return None
    curr_day = last_dt.strftime("%Y-%m-%d")
    day_candles = [c for c in completed if parse_ist_timestamp(c["timestamp"]).strftime("%Y-%m-%d") == curr_day]
    if not _evaluation_check(evaluation_trace, "orb.session_bars", len(day_candles) >= 4, "ORB_CURRENT_SESSION_BARS_REQUIRED", unavailable=True, observed=len(day_candles), required=4):
        return None

    orb_bars = day_candles[:3]
    if not _evaluation_check(evaluation_trace, "orb.opening_bars", [parse_ist_timestamp(bar["timestamp"]).time() for bar in orb_bars] == [
            dt_time(9, 15), dt_time(9, 20), dt_time(9, 25)], "ORB_OPENING_RANGE_BARS_MISSING", unavailable=True,
            observed_times=[parse_ist_timestamp(bar["timestamp"]).strftime("%H:%M:%S") for bar in orb_bars]):
        return None
    orb_high = max(b["high"] for b in orb_bars)
    orb_low = min(b["low"] for b in orb_bars)

    closes = [c["close"] for c in completed]
    vwaps = compute_session_vwap(completed)
    rsis = compute_rsi(closes, 14)
    atrs = compute_atr(completed, 10)
    curr_atr = max(0.05, atrs[-1])
    curr_vwap = vwaps[-1]
    avg_vol_20 = sum(c["volume"] for c in completed[-21:-1]) / 20.0
    if not _evaluation_check(evaluation_trace, "volume.baseline", avg_vol_20 > 0, "POSITIVE_BASELINE_VOLUME_REQUIRED", unavailable=True, baseline_volume=avg_vol_20):
        return None

    prev = completed[-2]
    rvol = last["volume"] / max(1.0, avg_vol_20)

    # 1. Bullish Opening Range Breakout
    if (
        _evaluation_check(evaluation_trace, "orb.bull.prior", prev["close"] <= orb_high, "PRIOR_CLOSE_ALREADY_ABOVE_ORB", close=prev["close"], threshold=orb_high)
        and _evaluation_check(evaluation_trace, "orb.bull.breakout", last["close"] > orb_high, "ORB_HIGH_BREAKOUT_MISSING", close=last["close"], threshold=orb_high)
        and _evaluation_check(evaluation_trace, "vwap.bull", last["close"] > curr_vwap, "CLOSE_NOT_ABOVE_VWAP", close=last["close"], threshold=curr_vwap)
        and _evaluation_check(evaluation_trace, "rsi.bull", rsis[-1] >= 55.0, "RSI_BELOW_55", rsi14=rsis[-1], threshold=55.0)
        and _evaluation_check(evaluation_trace, "volume.surge", rvol >= 1.6, "VOLUME_SURGE_BELOW_1_6", rvol=rvol, threshold=1.6)
    ):
        entry = round(last["close"], 2)
        sl = round(max(orb_low, last["low"] - (orb_high - orb_low) * 0.25), 2)
        risk_per_share = max(0.5, entry - sl)
        t1 = round(entry + 1.6 * risk_per_share, 2)
        t2 = round(entry + 2.4 * risk_per_share, 2)
        sizing = size_position(entry, sl, capital_inr, risk_pct, "LONG",
                               instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                               lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(entry, sl, q, "LONG")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (entry - curr_vwap) / curr_atr
        disp_atr = (entry - orb_high) / curr_atr
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=True,
        )
        return TradeSignal(
            symbol=symbol,
            segment=segment,
            strategy_id="strat_4_orb_filtered",
            strategy_name="15m Opening Range Breakout (ORB) + RVOL",
            direction="BULLISH (BUY)",
            instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
            entry_price=entry,
            entry_zone_low=round(orb_high, 2),
            entry_zone_high=entry,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:1.6 / 1:2.4",
            confidence_pct=q_score,
            win_rate_benchmark="52% Baseline / 1.6 Profit Factor (Backx NSE Study)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Closed decisively above 15m Opening Range High ({orb_high:.2f}) with {rvol:.1f}x relative volume, "
                f"RSI(14) at {rsis[-1]:.1f}, and price holding above session VWAP ({curr_vwap:.2f})."
            ),
            timestamp=format_ist_timestamp(last_dt),
            invalidation_level=round(orb_high, 2),
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    # 2. Bearish Opening Range Breakdown
    if (
        _evaluation_check(evaluation_trace, "orb.bear.prior", prev["close"] >= orb_low, "PRIOR_CLOSE_ALREADY_BELOW_ORB", close=prev["close"], threshold=orb_low)
        and _evaluation_check(evaluation_trace, "orb.bear.breakdown", last["close"] < orb_low, "ORB_LOW_BREAKDOWN_MISSING", close=last["close"], threshold=orb_low)
        and _evaluation_check(evaluation_trace, "vwap.bear", last["close"] < curr_vwap, "CLOSE_NOT_BELOW_VWAP", close=last["close"], threshold=curr_vwap)
        and _evaluation_check(evaluation_trace, "rsi.bear", rsis[-1] <= 45.0, "RSI_ABOVE_45", rsi14=rsis[-1], threshold=45.0)
        and _evaluation_check(evaluation_trace, "volume.surge", rvol >= 1.6, "VOLUME_SURGE_BELOW_1_6", rvol=rvol, threshold=1.6)
    ):
        entry = round(last["close"], 2)
        sl = round(min(orb_high, last["high"] + (orb_high - orb_low) * 0.25), 2)
        risk_per_share = max(0.5, sl - entry)
        t1 = round(entry - 1.6 * risk_per_share, 2)
        t2 = round(entry - 2.4 * risk_per_share, 2)
        sizing = size_position(entry, sl, capital_inr, risk_pct, "SHORT",
                               instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                               lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(entry, sl, q, "SHORT")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (curr_vwap - entry) / curr_atr
        disp_atr = (orb_low - entry) / curr_atr
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=False,
        )
        return TradeSignal(
            symbol=symbol,
            segment=segment,
            strategy_id="strat_4_orb_filtered",
            strategy_name="15m Opening Range Breakout (ORB) + RVOL",
            direction="BEARISH (SELL)",
            instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
            entry_price=entry,
            entry_zone_low=entry,
            entry_zone_high=round(orb_low, 2),
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:1.6 / 1:2.4",
            confidence_pct=q_score,
            win_rate_benchmark="52% Baseline / 1.6 Profit Factor (Backx NSE Study)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Closed decisively below 15m Opening Range Low ({orb_low:.2f}) with {rvol:.1f}x relative volume, "
                f"RSI(14) at {rsis[-1]:.1f}, and price rejected below session VWAP ({curr_vwap:.2f})."
            ),
            timestamp=format_ist_timestamp(last_dt),
            invalidation_level=round(orb_low, 2),
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    return None


# ============================================================================
# STRATEGY 5: Filtered Supertrend (10,3) Pullback + 200 EMA & Session Filter
# ============================================================================
def evaluate_supertrend_pullback(
    symbol: str,
    candles: List[Dict[str, Any]],
    capital_inr: float = 150000.0,
    risk_pct: float = 1.0,
    segment: str = "NSE_EQUITY_INTRADAY",
    now: Optional[Any] = None,
    market_breadth: Optional[Dict[str, Any]] = None,
    lot_size: Optional[int] = None,
    execution_costs=None,
    evaluation_trace=None,
) -> Optional[TradeSignal]:
    completed = filter_completed_candles(candles, interval_min=5, now=now)
    if not _evaluation_warmup(evaluation_trace, completed, 200):
        return None
    last = completed[-1]
    last_dt = parse_ist_timestamp(last["timestamp"])
    if not _evaluation_check(evaluation_trace, "session.nse", is_within_nse_session(last_dt), "OUTSIDE_NSE_SESSION", unavailable=True):
        return None
    if not _evaluation_session_start(evaluation_trace, completed):
        return None
    hhmm = last_dt.strftime("%H:%M")

    if not _evaluation_check(evaluation_trace, "session.strategy_window", not ("09:15" <= hhmm < "09:45" or "11:30" <= hhmm <= "13:30"), "SUPERTREND_EXCLUDED_SESSION_WINDOW", current_time=hhmm):
        return None

    closes = [c["close"] for c in completed]
    ema200 = compute_ema(closes, 200)
    vwaps = compute_session_vwap(completed)
    st_line, st_dir = compute_supertrend(completed, period=10, multiplier=3.0)
    atrs = compute_atr(completed, 10)
    avg_vol_20 = sum(c["volume"] for c in completed[-21:-1]) / 20.0
    if not _evaluation_check(evaluation_trace, "volume.baseline", avg_vol_20 > 0, "POSITIVE_BASELINE_VOLUME_REQUIRED", unavailable=True, baseline_volume=avg_vol_20):
        return None

    curr_st = st_line[-1]
    curr_ema200 = ema200[-1]
    curr_vwap = vwaps[-1]
    curr_atr = max(0.05, atrs[-1])
    rvol = last["volume"] / avg_vol_20

    # 1. Bullish Supertrend Pullback above 200 EMA & VWAP
    # Requires an already-established bullish Supertrend (`st_dir[-2] == 1 and st_dir[-1] == 1`),
    # avoiding raw 1-bar Supertrend flip whipsaws.
    near_st_or_vwap_bull = (last["low"] <= curr_st * 1.004) or (last["low"] <= curr_vwap * 1.003)
    if (
        _evaluation_check(evaluation_trace, "st.bull.direction", st_dir[-1] == 1, "SUPERTREND_NOT_BULLISH", observed=st_dir[-1])
        and _evaluation_check(evaluation_trace, "st.bull.established", st_dir[-2] == 1, "SUPERTREND_BULL_TREND_NOT_ESTABLISHED", observed=st_dir[-2])
        and _evaluation_check(evaluation_trace, "ema.bull.current", last["close"] > curr_ema200, "CLOSE_NOT_ABOVE_EMA200", close=last["close"], threshold=curr_ema200)
        and _evaluation_check(evaluation_trace, "ema.bull.prior", completed[-2]["close"] > ema200[-2], "PRIOR_CLOSE_NOT_ABOVE_EMA200", close=completed[-2]["close"], threshold=ema200[-2])
        and _evaluation_check(evaluation_trace, "vwap.bull", last["close"] > curr_vwap, "CLOSE_NOT_ABOVE_VWAP", close=last["close"], threshold=curr_vwap)
        and _evaluation_check(evaluation_trace, "st.bull.pullback", near_st_or_vwap_bull, "BULL_SUPERTREND_OR_VWAP_PULLBACK_MISSING", low=last["low"], supertrend_threshold=curr_st * 1.004, vwap_threshold=curr_vwap * 1.003)
        and _evaluation_check(evaluation_trace, "st.bull.candle", last["close"] > last["open"], "BULLISH_CONFIRMATION_CANDLE_REQUIRED", close=last["close"], open=last["open"])
        and _evaluation_check(evaluation_trace, "volume.surge", last["volume"] >= 1.3 * avg_vol_20, "VOLUME_SURGE_BELOW_1_3", rvol=rvol, threshold=1.3)
    ):
        entry = round(last["close"], 2)
        sl = round(min(curr_st, last["low"]) - 0.25 * curr_atr, 2)
        risk_per_share = max(0.5, entry - sl)
        t1 = round(entry + 1.5 * risk_per_share, 2)
        t2 = round(entry + 2.5 * risk_per_share, 2)
        sizing = size_position(entry, sl, capital_inr, risk_pct, "LONG",
                               instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                               lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(entry, sl, q, "LONG")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (entry - curr_vwap) / curr_atr
        disp_atr = (last["close"] - last["low"]) / curr_atr
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=True,
        )
        return TradeSignal(
            symbol=symbol,
            segment=segment,
            strategy_id="strat_5_supertrend_pullback",
            strategy_name="Supertrend (10,3) Pullback + 200 EMA",
            direction="BULLISH (BUY)",
            instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
            entry_price=entry,
            entry_zone_low=round(min(curr_st, entry), 2),
            entry_zone_high=round(max(curr_st, entry), 2),
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:1.5 / 1:2.5",
            confidence_pct=q_score,
            win_rate_benchmark="44%–58% with EMA/VWAP Filter vs 35.7% Raw (LeadFinn)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Active trend above 200 EMA ({curr_ema200:.2f}) and session VWAP ({curr_vwap:.2f}) during institutional "
                f"window ({hhmm} IST). Pullback defended above Supertrend(10,3) support ({curr_st:.2f})."
            ),
            timestamp=format_ist_timestamp(last_dt),
            invalidation_level=round(curr_st, 2),
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    # 2. Bearish Supertrend Pullback below 200 EMA & VWAP
    # Requires an already-established bearish Supertrend (`st_dir[-2] == -1 and st_dir[-1] == -1`)
    # and prior bar below 200 EMA (`completed[-2]["close"] < ema200[-2]`), preventing raw 1-bar flip whipsaws.
    near_st_or_vwap_bear = (last["high"] >= curr_st * 0.996) or (last["high"] >= curr_vwap * 0.997)
    if (
        _evaluation_check(evaluation_trace, "st.bear.direction", st_dir[-1] == -1, "SUPERTREND_NOT_BEARISH", observed=st_dir[-1])
        and _evaluation_check(evaluation_trace, "st.bear.established", st_dir[-2] == -1, "SUPERTREND_BEAR_TREND_NOT_ESTABLISHED", observed=st_dir[-2])
        and _evaluation_check(evaluation_trace, "ema.bear.current", last["close"] < curr_ema200, "CLOSE_NOT_BELOW_EMA200", close=last["close"], threshold=curr_ema200)
        and _evaluation_check(evaluation_trace, "ema.bear.prior", completed[-2]["close"] < ema200[-2], "PRIOR_CLOSE_NOT_BELOW_EMA200", close=completed[-2]["close"], threshold=ema200[-2])
        and _evaluation_check(evaluation_trace, "vwap.bear", last["close"] < curr_vwap, "CLOSE_NOT_BELOW_VWAP", close=last["close"], threshold=curr_vwap)
        and _evaluation_check(evaluation_trace, "st.bear.pullback", near_st_or_vwap_bear, "BEAR_SUPERTREND_OR_VWAP_PULLBACK_MISSING", high=last["high"], supertrend_threshold=curr_st * 0.996, vwap_threshold=curr_vwap * 0.997)
        and _evaluation_check(evaluation_trace, "st.bear.candle", last["close"] < last["open"], "BEARISH_CONFIRMATION_CANDLE_REQUIRED", close=last["close"], open=last["open"])
        and _evaluation_check(evaluation_trace, "volume.surge", last["volume"] >= 1.3 * avg_vol_20, "VOLUME_SURGE_BELOW_1_3", rvol=rvol, threshold=1.3)
    ):
        entry = round(last["close"], 2)
        sl = round(max(curr_st, last["high"]) + 0.25 * curr_atr, 2)
        risk_per_share = max(0.5, sl - entry)
        t1 = round(entry - 1.5 * risk_per_share, 2)
        t2 = round(entry - 2.5 * risk_per_share, 2)
        sizing = size_position(entry, sl, capital_inr, risk_pct, "SHORT",
                               instrument_type="EQ" if segment == "NSE_EQUITY_INTRADAY" else "FUTIDX",
                               lot_size=lot_size, cost_estimator=(None if execution_costs is None else
                                   lambda q: execution_costs(entry, sl, q, "SHORT")))
        if not _evaluation_check(evaluation_trace, "risk.position_size", sizing["eligible"], sizing["reason_code"]):
            return None
        qty = sizing["quantity"]
        est_charges = sizing["estimated_charges_inr"]
        vwap_dist_atr = (curr_vwap - entry) / curr_atr
        disp_atr = (last["high"] - last["close"]) / curr_atr
        q_score, q_breakdown = compute_setup_quality_score(
            rvol=rvol,
            vwap_dist_atr=vwap_dist_atr,
            displacement_atr=disp_atr,
            market_breadth=market_breadth,
            is_bullish=False,
        )
        return TradeSignal(
            symbol=symbol,
            segment=segment,
            strategy_id="strat_5_supertrend_pullback",
            strategy_name="Supertrend (10,3) Pullback + 200 EMA",
            direction="BEARISH (SELL)",
            instrument_label=f"{symbol} EQ" if segment == "NSE_EQUITY_INTRADAY" else f"{symbol} FUT",
            entry_price=entry,
            entry_zone_low=round(min(curr_st, entry), 2),
            entry_zone_high=round(max(curr_st, entry), 2),
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:1.5 / 1:2.5",
            confidence_pct=q_score,
            win_rate_benchmark="44%–58% with EMA/VWAP Filter vs 35.7% Raw (LeadFinn)",
            position_qty=qty,
            capital_risk_inr=sizing["estimated_risk_inr"],
            est_charges_inr=est_charges,
            rationale=(
                f"Active downtrend below 200 EMA ({curr_ema200:.2f}) and session VWAP ({curr_vwap:.2f}) during institutional "
                f"window ({hhmm} IST). Pullback rejected beneath Supertrend(10,3) resistance ({curr_st:.2f})."
            ),
            timestamp=format_ist_timestamp(last_dt),
            invalidation_level=round(curr_st, 2),
            quality_score=q_score,
            score_breakdown=q_breakdown,
        )

    return None
