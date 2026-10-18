from instrument_identity import IdentityValidationError, digest
import argparse
import atexit
import hashlib
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from brokers import INDEX_SYMBOLS
from config import BotConfig, ConfigValidationError
from historical_data import (
    STRATEGY_HISTORICAL_DATA_REQUIREMENTS,
    HistoricalDataError,
    HistoricalDataValidationError,
    LookAheadBiasError,
    compute_point_in_time_universe_breadth,
    evaluate_phase3a_backtest_readiness,
    get_point_in_time_candle_slice,
    validate_and_prepare_historical_dataset,
    verify_no_lookahead_leakage,
)
from scanner_engine import safe_console_print
from storage import (
    PersistenceError,
    PersistenceValidationError,
    SQLitePersistenceStore,
)
from strategies import (
    IST,
    TradeSignal,
    evaluate_option_apex_oi_shift,
    evaluate_orb_breakout,
    evaluate_order_block_fvg,
    evaluate_supertrend_pullback,
    evaluate_vwap_pullback,
    format_ist_timestamp,
    parse_ist_timestamp,
    size_position,
)


BACKTEST_ENGINE_VERSION = "phase_3b_1c_risk_v1.0.0"


class BacktestError(RuntimeError):
    """Base exception for deterministic backtesting errors."""


class BacktestValidationError(ValueError):
    """Raised when backtest parameters, date ranges, or inputs are invalid."""


class BacktestEligibilityError(BacktestError):
    """Raised for unsupported historical strategies or missing/invalid historical inputs."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class BacktestReadinessError(BacktestError):
    """Raised when a LIVE backtest is requested before Phase 2C/3A readiness gates pass."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


STRATEGY_3_HISTORICAL_BLOCK_REASON = (
    "Historical Strategy 3 (Option Apex OI Shift) is not supported until validated contract-level "
    "option execution is implemented. Supplied option chains, contract candles, lot metadata, "
    "readiness flags, and SIMULATED/LIVE mode cannot enable it. Underlying index candles must "
    "never be used as option-premium execution prices."
)


def _strategy_3_historical_rejection() -> Dict[str, Any]:
    return {
        "eligible": False,
        "strategy_id": "strat_3_option_apex_oi",
        "strategy_name": "Option Apex OI Shift Trap + PCR",
        # Retain the existing status for clients; reason_code describes the unconditional block.
        "status": "BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN",
        "reason_code": "HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED",
        "reason": STRATEGY_3_HISTORICAL_BLOCK_REASON,
        "required_action": (
            "Implement and validate point-in-time option contract selection, historical closing-OI "
            "provenance, contract-candle fills, long-call/long-put accounting, and historical lot "
            "metadata before separately enabling Strategy 3 historical execution."
        ),
    }


def _ensure_historical_strategy_supported(strategy_id: str) -> None:
    if str(strategy_id or "").strip() == "strat_3_option_apex_oi":
        rejection = _strategy_3_historical_rejection()
        raise BacktestEligibilityError(
            f"{rejection['status']}: {rejection['reason']}", details=rejection
        )


# ============================================================================
# 1. STRATEGY ELIGIBILITY SPECIFICATION & MATRIX (Section 5)
# ============================================================================
STRATEGY_BACKTEST_ELIGIBILITY: Dict[str, Dict[str, Any]] = {
    "strat_1_order_block": {
        "strategy_id": "strat_1_order_block",
        "strategy_name": "Order Block + BOS & FVG Retest",
        "strategy_version": "phase_1c_bidirectional_v1",
        "evaluator_function": "evaluate_order_block_fvg",
        "required_instruments": "15 NSE Cash Equities (NSE_EQUITY_INTRADAY). Index spot (NIFTY/BANKNIFTY) is NOT directly executable without futures contract OHLCV + historical lot size.",
        "allowed_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "timeframe_min": 5,
        "min_completed_bars": 30,
        "required_candle_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "required_indicators": [
            "Wilder ATR(10)",
            "Session VWAP (resets at 09:15 IST)",
            "20-bar Average Volume (avg_vol_20)",
            "15-bar Unmitigated Order Block / BOS / FVG structure",
        ],
        "required_volume_oi_options_inputs": {
            "requires_positive_volume": True,
            "requires_historical_option_chain": False,
            "requires_prior_session_closing_oi": False,
            "requires_opening_range_0915_0930": False,
        },
        "entry_rules": (
            "Bullish (BUY): Red 5m OB candle followed by 2-bar bullish BOS above OB high + FVG or >=1.5x ATR(10) "
            "displacement; first unmitigated retest dipping <= OB high * 1.0015 and closing > OB open & >= OB low. "
            "Bearish (SELL): Green 5m OB candle followed by 2-bar bearish BOS below OB low + FVG or >=1.5x ATR(10) "
            "displacement; first unmitigated retest rallying >= OB low * 0.9985 and closing < OB open & <= OB high."
        ),
        "exit_stop_target_rules": (
            "Stop-Loss (S1): zone_low - 0.25*ATR(10) (Long) or zone_high + 0.25*ATR(10) (Short); minimum risk 0.50 INR. "
            "Targets: T1 = entry +/- 2.0*risk, T2 = entry +/- 3.0*risk. Mandatory intraday EOD square-off at 15:20 IST."
        ),
        "historical_data_availability": "ELIGIBLE_WHEN_5M_OHLCV_DATASET_VALIDATED",
        "backtest_eligibility": "ELIGIBLE_EQUITY_5M",
        "restriction_reason": (
            "Eligible for NSE equities with validated 5m OHLCV bars (>=30 bars, positive volume). "
            "Blocked on NIFTY/BANKNIFTY index spot series because an index spot level is not an executable instrument "
            "and reports zero volume."
        ),
    },
    "strat_2_vwap_pullback": {
        "strategy_id": "strat_2_vwap_pullback",
        "strategy_name": "Institutional VWAP Pullback + Volume",
        "strategy_version": "phase_1c_bidirectional_v1",
        "evaluator_function": "evaluate_vwap_pullback",
        "required_instruments": "15 NSE Cash Equities (NSE_EQUITY_INTRADAY) with positive traded volume.",
        "allowed_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "timeframe_min": 5,
        "min_completed_bars": 35,
        "required_candle_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "required_indicators": [
            "Session VWAP (volume-weighted typical price)",
            "EMA(20)",
            "Wilder RSI(14)",
            "Wilder ATR(10)",
            "20-bar Average Volume (RVOL >= 1.4x)",
        ],
        "required_volume_oi_options_inputs": {
            "requires_positive_volume": True,
            "requires_historical_option_chain": False,
            "requires_prior_session_closing_oi": False,
            "requires_opening_range_0915_0930": False,
        },
        "entry_rules": (
            "Bullish (BUY): low <= VWAP*1.0025, close > VWAP, close > open, close >= EMA20*0.998, "
            "volume >= 1.4*avg_vol_20 (avg_vol_20 > 0), and 48.0 <= RSI(14) <= 72.0. "
            "Bearish (SELL): high >= VWAP*0.9975, close < VWAP, close < open, close <= EMA20*1.002, "
            "volume >= 1.4*avg_vol_20, and 28.0 <= RSI(14) <= 52.0."
        ),
        "exit_stop_target_rules": (
            "Stop-Loss (S1): min(low, VWAP) - 0.35*ATR(10) (Long) or max(high, VWAP) + 0.35*ATR(10) (Short). "
            "Targets: T1 = entry +/- 1.8*risk, T2 = entry +/- 2.5*risk. Mandatory intraday EOD square-off at 15:20 IST."
        ),
        "historical_data_availability": "ELIGIBLE_WHEN_5M_OHLCV_DATASET_VALIDATED",
        "backtest_eligibility": "ELIGIBLE_EQUITY_5M",
        "restriction_reason": (
            "Requires >=35 completed 5m bars with positive traded volume (avg_vol_20 > 0). "
            "Blocked on zero-volume index spot series."
        ),
    },
    "strat_3_option_apex_oi": {
        "strategy_id": "strat_3_option_apex_oi",
        "strategy_name": "Option Apex OI Shift Trap + PCR",
        "strategy_version": "phase_1c_bidirectional_v1",
        "evaluator_function": "evaluate_option_apex_oi_shift",
        "required_instruments": "Strictly NIFTY and BANKNIFTY NFO Option Contracts (NSE_FO_INDEX).",
        "allowed_segments": ["NSE_FO_INDEX"],
        "timeframe_min": 5,
        "min_completed_bars": 15,
        "required_candle_fields": [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "option_chain.atm_strike",
            "option_chain.pcr",
            "option_chain.strikes[].ce_ltp",
            "option_chain.strikes[].pe_ltp",
            "option_chain.strikes[].ce_oi",
            "option_chain.strikes[].pe_oi",
            "option_chain.strikes[].ce_oi_change (from verified prior-session CLOSING_BASELINE)",
            "option_chain.strikes[].pe_oi_change (from verified prior-session CLOSING_BASELINE)",
            "traded_option_contract_5m_ohlcv (for post-entry option premium stop/target simulation)",
            "historical_lot_size",
        ],
        "required_indicators": [
            "Session VWAP on underlying index",
            "Wilder ATR(10) on underlying index",
            "Aggregate Put-Call Ratio (PCR)",
            "ATM Strike Call/Put Net OI Change vs Prior Session Closing OI",
        ],
        "required_volume_oi_options_inputs": {
            "requires_positive_volume": False,
            "requires_historical_option_chain": True,
            "requires_prior_session_closing_oi": True,
            "requires_opening_range_0915_0930": False,
        },
        "entry_rules": (
            "Bullish (BUY CE): ATM ce_oi_change < 0 AND pe_oi_change > 0 AND PCR >= 1.10 AND Spot >= VWAP*0.998. "
            "Bearish (BUY PE): ATM pe_oi_change < 0 AND ce_oi_change > 0 AND PCR <= 0.85 AND Spot <= VWAP*1.002."
        ),
        "exit_stop_target_rules": (
            "Option Premium Stop-Loss: 0.78 * opt_premium (risk = max(1.0, opt_premium - sl_premium)). "
            "Targets: T1 = opt_premium + 1.6*risk, T2 = opt_premium + 2.4*risk. Requires historical 5m OHLC of the "
            "specific ATM CE/PE option contract to evaluate intrabar stops and targets."
        ),
        "historical_data_availability": "UNAVAILABLE_HISTORICAL_OPTION_CHAIN_AND_EXPIRED_CONTRACTS",
        "backtest_eligibility": "BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN",
        "historical_execution_supported": False,
        "reason_code": "HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED",
        "restriction_reason": STRATEGY_3_HISTORICAL_BLOCK_REASON,
    },
    "strat_4_orb_filtered": {
        "strategy_id": "strat_4_orb_filtered",
        "strategy_name": "15m Opening Range Breakout (ORB) + RVOL",
        "strategy_version": "phase_1c_bidirectional_v1",
        "evaluator_function": "evaluate_orb_breakout",
        "required_instruments": "15 NSE Cash Equities (NSE_EQUITY_INTRADAY) with complete 09:15-09:30 IST opening bars and positive volume.",
        "allowed_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "timeframe_min": 5,
        "min_completed_bars": 30,
        "required_candle_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "required_indicators": [
            "15m Opening Range High/Low (first 3 completed bars 09:15, 09:20, 09:25 IST)",
            "Session VWAP",
            "Wilder RSI(14)",
            "Wilder ATR(10)",
            "20-bar Average Volume (RVOL >= 1.6x)",
        ],
        "required_volume_oi_options_inputs": {
            "requires_positive_volume": True,
            "requires_historical_option_chain": False,
            "requires_prior_session_closing_oi": False,
            "requires_opening_range_0915_0930": True,
        },
        "entry_rules": (
            "Bullish (BUY): >=4 session bars, prev close <= orb_high, curr close > orb_high, curr close > VWAP, "
            "RSI(14) >= 55.0, RVOL >= 1.6x. "
            "Bearish (SELL): >=4 session bars, prev close >= orb_low, curr close < orb_low, curr close < VWAP, "
            "RSI(14) <= 45.0, RVOL >= 1.6x."
        ),
        "exit_stop_target_rules": (
            "Stop-Loss (S1): max(orb_low, low - 0.25*(orb_high - orb_low)) (Long) or "
            "min(orb_high, high + 0.25*(orb_high - orb_low)) (Short). "
            "Targets: T1 = entry +/- 1.6*risk, T2 = entry +/- 2.4*risk. Mandatory intraday EOD square-off at 15:20 IST."
        ),
        "historical_data_availability": "ELIGIBLE_WHEN_5M_OHLCV_AND_ORB_BARS_VALIDATED",
        "backtest_eligibility": "ELIGIBLE_EQUITY_5M",
        "restriction_reason": (
            "Requires >=30 completed 5m bars, positive traded volume, and all three 09:15, 09:20, 09:25 IST "
            "opening-range bars on each evaluated session. Blocked on zero-volume index spot series."
        ),
    },
    "strat_5_supertrend_pullback": {
        "strategy_id": "strat_5_supertrend_pullback",
        "strategy_name": "Supertrend (10,3) Pullback + 200 EMA",
        "strategy_version": "phase_1c_bidirectional_v1",
        "evaluator_function": "evaluate_supertrend_pullback",
        "required_instruments": "15 NSE Cash Equities (NSE_EQUITY_INTRADAY) with >=200 completed 5m bars and positive volume.",
        "allowed_segments": ["NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"],
        "timeframe_min": 5,
        "min_completed_bars": 200,
        "required_candle_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "required_indicators": [
            "EMA(200)",
            "Supertrend(period=10, multiplier=3.0)",
            "Session VWAP",
            "Wilder ATR(10)",
            "20-bar Average Volume (RVOL >= 1.3x)",
            "Session Window Filter (blocks 09:15-09:44 and 11:30-13:30 IST)",
        ],
        "required_volume_oi_options_inputs": {
            "requires_positive_volume": True,
            "requires_historical_option_chain": False,
            "requires_prior_session_closing_oi": False,
            "requires_opening_range_0915_0930": False,
        },
        "entry_rules": (
            "Active only during 09:45-11:25 and 13:35-15:25 IST. "
            "Bullish (BUY): st_dir[-1]==1 and st_dir[-2]==1, close > EMA200, prev_close > prev_EMA200, close > VWAP, "
            "(low <= ST*1.004 or low <= VWAP*1.003), close > open, volume >= 1.3*avg_vol_20. "
            "Bearish (SELL): st_dir[-1]==-1 and st_dir[-2]==-1, close < EMA200, prev_close < prev_EMA200, close < VWAP, "
            "(high >= ST*0.996 or high >= VWAP*0.997), close < open, volume >= 1.3*avg_vol_20."
        ),
        "exit_stop_target_rules": (
            "Stop-Loss (S1): min(curr_st, low) - 0.25*ATR(10) (Long) or max(curr_st, high) + 0.25*ATR(10) (Short). "
            "Targets: T1 = entry +/- 1.5*risk, T2 = entry +/- 2.5*risk. Mandatory intraday EOD square-off at 15:20 IST."
        ),
        "historical_data_availability": "ELIGIBLE_WHEN_200_BAR_5M_OHLCV_VALIDATED",
        "backtest_eligibility": "ELIGIBLE_EQUITY_5M_WITH_200_BAR_WARMUP",
        "restriction_reason": (
            "Requires >=200 completed 5m bars (>=3 prior 75-bar NSE sessions) and positive volume. "
            "Blocked if dataset has <200 bars or zero volume."
        ),
    },
}


# ============================================================================
# 2. CONFIGURABLE INDIAN MARKET COST & SLIPPAGE MODEL (Section 9)
# ============================================================================
@dataclass
class IndianCostModel:
    """
    Configurable Indian market transaction cost and slippage model.
    Distinguishes instrument segment (`NSE_EQUITY_INTRADAY`, `NSE_FO_INDEX_FUTURES`,
    `NSE_FO_INDEX_OPTIONS`), exchange (`NSE`, `NFO`), and transaction side (`BUY` vs `SELL`).

    Default rate schedule: `NSE_OCT_2024_2026_STATUTORY_SCHEDULE` (effective 2024-10-01 onwards).
    Because historical statutory or brokerage rates may vary by broker plan and date, all rates
    are configurable and documented in the run assumptions.
    """
    schedule_name: str = "NSE_OCT_2024_2026_CONFIGURABLE_SCHEDULE"
    effective_date: str = "2024-10-01"
    is_estimated_schedule: bool = True

    # Brokerage per executed order leg (entry order + exit order)
    brokerage_per_order_inr: float = 20.0
    brokerage_max_pct_per_leg: Optional[float] = 0.0003  # 0.03% cap for equity/futures when set; None = flat ₹20/leg

    # STT (charged strictly on the SELL leg only — never double-counted on BUY)
    stt_sell_rate_equity_intraday: float = 0.00025       # 0.025% on sell leg
    stt_sell_rate_fo_futures: float = 0.0002             # 0.02% on sell leg
    stt_sell_rate_fo_options: float = 0.001              # 0.10% on sell leg premium

    # Exchange transaction charges (applied to buy_turnover + sell_turnover)
    exchange_txn_rate_equity_intraday: float = 0.0000297 # 0.00297% NSE cash
    exchange_txn_rate_fo_futures: float = 0.0000173      # 0.00173% NSE futures
    exchange_txn_rate_fo_options: float = 0.0003503      # 0.03503% NSE options premium

    # Regulatory / SEBI turnover fees (₹10 per crore = 0.0001% on buy + sell turnover)
    sebi_turnover_rate: float = 0.000001

    # Stamp duty (charged strictly on the BUY leg only — never double-counted on SELL)
    stamp_duty_buy_rate_equity_intraday: float = 0.00003 # 0.003% on buy leg
    stamp_duty_buy_rate_fo_futures: float = 0.00002      # 0.002% on buy leg
    stamp_duty_buy_rate_fo_options: float = 0.00003      # 0.003% on buy leg

    # GST (18% on brokerage + exchange_txn + sebi_charges)
    gst_rate: float = 0.18

    # Execution slippage in basis points per leg (1 bps = 0.01% = 0.0001)
    slippage_bps_per_leg: float = 5.0

    # Other explicitly configured flat/rate costs
    other_cost_per_trade_inr: float = 0.0

    def validate(self) -> None:
        for fname in (
            "brokerage_per_order_inr",
            "stt_sell_rate_equity_intraday",
            "stt_sell_rate_fo_futures",
            "stt_sell_rate_fo_options",
            "exchange_txn_rate_equity_intraday",
            "exchange_txn_rate_fo_futures",
            "exchange_txn_rate_fo_options",
            "sebi_turnover_rate",
            "stamp_duty_buy_rate_equity_intraday",
            "stamp_duty_buy_rate_fo_futures",
            "stamp_duty_buy_rate_fo_options",
            "gst_rate",
            "slippage_bps_per_leg",
            "other_cost_per_trade_inr",
        ):
            val = getattr(self, fname)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)) or float(val) < 0.0:
                raise BacktestValidationError(f"Invalid cost model parameter '{fname}': {val!r} (must be >= 0).")
        if self.brokerage_max_pct_per_leg is not None:
            if (
                isinstance(self.brokerage_max_pct_per_leg, bool)
                or not isinstance(self.brokerage_max_pct_per_leg, (int, float))
                or not math.isfinite(float(self.brokerage_max_pct_per_leg))
                or float(self.brokerage_max_pct_per_leg) < 0.0
            ):
                raise BacktestValidationError("brokerage_max_pct_per_leg must be non-negative or None.")

    def compute_trade_costs(
        self,
        raw_entry_price: float,
        raw_exit_price: float,
        quantity: int,
        position_side: str,
        segment: str = "NSE_EQUITY_INTRADAY",
        instrument_type: str = "EQ",
        exchange: str = "NSE",
    ) -> Dict[str, Any]:
        """
        Computes itemized entry/exit brokerage, STT (sell leg only), Stamp Duty (buy leg only),
        Exchange transaction charges, SEBI regulatory charges, GST, and slippage without
        double-counting any fee or slippage component.
        """
        self.validate()
        if (isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0
                or any(isinstance(p, bool) or not isinstance(p, (int, float))
                       or not math.isfinite(float(p)) or p <= 0 for p in (raw_entry_price, raw_exit_price))):
            raise BacktestValidationError("quantity, raw_entry_price, and raw_exit_price must be positive.")

        side = str(position_side).strip().upper()
        if side not in ("LONG", "SHORT"):
            raise BacktestValidationError(f"Invalid position_side {position_side!r}; expected 'LONG' or 'SHORT'.")

        slip_rate = float(self.slippage_bps_per_leg) / 10000.0
        entry_slippage_per_unit = raw_entry_price * slip_rate
        exit_slippage_per_unit = raw_exit_price * slip_rate

        if side == "LONG":
            # Long buys at entry (pays higher by entry slippage) and sells at exit (receives lower by exit slippage)
            effective_entry_price = round(raw_entry_price + entry_slippage_per_unit, 4)
            effective_exit_price = round(max(0.01, raw_exit_price - exit_slippage_per_unit), 4)
            buy_turnover = raw_entry_price * quantity
            sell_turnover = raw_exit_price * quantity
        else:
            # Short sells at entry (receives lower by entry slippage) and buys to cover at exit (pays higher by exit slippage)
            effective_entry_price = round(max(0.01, raw_entry_price - entry_slippage_per_unit), 4)
            effective_exit_price = round(raw_exit_price + exit_slippage_per_unit, 4)
            sell_turnover = raw_entry_price * quantity
            buy_turnover = raw_exit_price * quantity

        total_turnover = buy_turnover + sell_turnover

        entry_slippage_inr = round(entry_slippage_per_unit * quantity, 2)
        exit_slippage_inr = round(exit_slippage_per_unit * quantity, 2)
        total_slippage_inr = round(entry_slippage_inr + exit_slippage_inr, 2)

        seg_upper = str(segment or "NSE_EQUITY_INTRADAY").strip().upper()
        inst_upper = str(instrument_type or "EQ").strip().upper()

        if seg_upper == "NSE_FO_INDEX" and inst_upper in ("OPTIDX", "OPTION", "CE", "PE"):
            stt_rate = self.stt_sell_rate_fo_options
            exch_rate = self.exchange_txn_rate_fo_options
            stamp_rate = self.stamp_duty_buy_rate_fo_options
            flat_options_brok = True
        elif seg_upper == "NSE_FO_INDEX":
            stt_rate = self.stt_sell_rate_fo_futures
            exch_rate = self.exchange_txn_rate_fo_futures
            stamp_rate = self.stamp_duty_buy_rate_fo_futures
            flat_options_brok = False
        else:
            stt_rate = self.stt_sell_rate_equity_intraday
            exch_rate = self.exchange_txn_rate_equity_intraday
            stamp_rate = self.stamp_duty_buy_rate_equity_intraday
            flat_options_brok = False

        # Brokerage per leg (entry leg + exit leg)
        entry_turnover = buy_turnover if side == "LONG" else sell_turnover
        exit_turnover = sell_turnover if side == "LONG" else buy_turnover

        if self.brokerage_max_pct_per_leg is not None and not flat_options_brok:
            entry_brok = min(float(self.brokerage_per_order_inr), entry_turnover * float(self.brokerage_max_pct_per_leg))
            exit_brok = min(float(self.brokerage_per_order_inr), exit_turnover * float(self.brokerage_max_pct_per_leg))
        else:
            entry_brok = float(self.brokerage_per_order_inr)
            exit_brok = float(self.brokerage_per_order_inr)

        brokerage_inr = round(entry_brok + exit_brok, 2)
        stt_inr = round(sell_turnover * float(stt_rate), 2)
        exchange_txn_charge_inr = round(total_turnover * float(exch_rate), 2)
        sebi_charge_inr = round(total_turnover * float(self.sebi_turnover_rate), 2)
        stamp_duty_inr = round(buy_turnover * float(stamp_rate), 2)
        gst_inr = round(float(self.gst_rate) * (brokerage_inr + exchange_txn_charge_inr + sebi_charge_inr), 2)
        other_charges_inr = round(float(self.other_cost_per_trade_inr), 2)

        charges_inr = round(
            brokerage_inr
            + stt_inr
            + exchange_txn_charge_inr
            + sebi_charge_inr
            + stamp_duty_inr
            + gst_inr
            + other_charges_inr,
            2,
        )
        total_costs_inr = round(charges_inr + total_slippage_inr, 2)

        return {
            "schedule_name": self.schedule_name,
            "effective_date": self.effective_date,
            "is_estimated_schedule": self.is_estimated_schedule,
            "exchange": exchange,
            "segment": seg_upper,
            "instrument_type": inst_upper,
            "buy_turnover_inr": round(buy_turnover, 2),
            "sell_turnover_inr": round(sell_turnover, 2),
            "total_turnover_inr": round(total_turnover, 2),
            "entry_brokerage_inr": round(entry_brok, 2),
            "exit_brokerage_inr": round(exit_brok, 2),
            "brokerage_inr": brokerage_inr,
            "stt_inr": stt_inr,
            "exchange_txn_charge_inr": exchange_txn_charge_inr,
            "sebi_charge_inr": sebi_charge_inr,
            "stamp_duty_inr": stamp_duty_inr,
            "gst_inr": gst_inr,
            "other_charges_inr": other_charges_inr,
            "charges_inr": charges_inr,
            "slippage_bps_per_leg": float(self.slippage_bps_per_leg),
            "entry_slippage_inr": entry_slippage_inr,
            "exit_slippage_inr": exit_slippage_inr,
            "slippage_inr": total_slippage_inr,
            "total_costs_inr": total_costs_inr,
            "effective_entry_price": effective_entry_price,
            "effective_exit_price": effective_exit_price,
        }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 3. BACKTEST CONFIGURATION & ASSUMPTIONS (Sections 8, 9, 10, 13)
# ============================================================================
@dataclass
class BacktestConfig:
    starting_capital_inr: float = 100000.0
    risk_per_trade_pct: float = 1.0
    max_daily_loss_inr: Optional[float] = 2000.0
    daily_profit_target_inr: Optional[float] = 4000.0
    max_concurrent_positions: int = 1
    execution_convention: str = "NEXT_CANDLE_OPEN"
    target_mode: str = "TARGET_1"                    # "TARGET_1" or "TARGET_2"
    same_candle_collision_rule: str = "STOP_LOSS_FIRST_CONSERVATIVE"
    last_entry_Cutoff_ist: str = "15:15"             # No new intraday entries at/after 15:15 IST
    eod_square_off_ist: str = "15:20"                # Mandatory MIS square-off on the 15:20 IST bar (or last session bar)
    allow_overnight_carry: bool = False              # Strictly intraday MIS by default
    enforce_capital_exposure_limit: bool = True      # Mandatory; False is rejected (no verified margin model).
    historical_lot_size: Optional[int] = None        # Required if backtesting F&O derivative contracts
    instrument_type: str = "EQ"                      # "EQ", "INDEX_SPOT", "FUTIDX", "OPTIDX"
    period_type: str = "FULL"                        # "FULL", "TRAIN", "VALIDATION", "OUT_OF_SAMPLE"
    evaluation_start_date: Optional[str] = None      # Optional YYYY-MM-DD start of trade evaluation window (earlier bars warm up indicators)
    evaluation_end_date: Optional[str] = None        # Optional YYYY-MM-DD end of trade evaluation window
    require_live_acceptance_for_live_mode: bool = True  # Deprecated: cannot bypass LIVE_ACCEPTED.
    cost_model: IndianCostModel = field(default_factory=IndianCostModel)
    execution_scope: Optional[str] = None             # LIVE_ACCEPTED, HISTORICAL_RESEARCH, SIMULATED_TEST
    historical_instrument_identity: Optional[Dict[str, Any]] = None  # Inline source; ingestion retains its provenance limits.
    historical_instrument_archive_id: Optional[str] = None  # Immutable ingested archive reference.

    def validate(self) -> None:
        if isinstance(self.starting_capital_inr, bool) or not isinstance(self.starting_capital_inr, (int, float)) or not math.isfinite(float(self.starting_capital_inr)) or float(self.starting_capital_inr) <= 0:
            raise BacktestValidationError(f"starting_capital_inr must be > 0, got {self.starting_capital_inr!r}.")
        if isinstance(self.risk_per_trade_pct, bool) or not isinstance(self.risk_per_trade_pct, (int, float)) or not (0.0 < float(self.risk_per_trade_pct) <= 100.0):
            raise BacktestValidationError(f"risk_per_trade_pct must be in (0, 100], got {self.risk_per_trade_pct!r}.")
        if self.max_daily_loss_inr is not None:
            if isinstance(self.max_daily_loss_inr, bool) or not isinstance(self.max_daily_loss_inr, (int, float)) or not math.isfinite(float(self.max_daily_loss_inr)) or float(self.max_daily_loss_inr) <= 0:
                raise BacktestValidationError("max_daily_loss_inr must be > 0 when set.")
        if self.daily_profit_target_inr is not None:
            if isinstance(self.daily_profit_target_inr, bool) or not isinstance(self.daily_profit_target_inr, (int, float)) or not math.isfinite(float(self.daily_profit_target_inr)) or float(self.daily_profit_target_inr) <= 0:
                raise BacktestValidationError("daily_profit_target_inr must be > 0 when set.")
        if isinstance(self.max_concurrent_positions, bool) or not isinstance(self.max_concurrent_positions, int) or self.max_concurrent_positions < 1:
            raise BacktestValidationError("max_concurrent_positions must be an integer >= 1.")
        if self.enforce_capital_exposure_limit is not True:
            raise BacktestValidationError("Capital exposure checks cannot be disabled without a verified margin model.")
        if self.historical_lot_size is not None and (
                isinstance(self.historical_lot_size, bool) or not isinstance(self.historical_lot_size, int)
                or self.historical_lot_size <= 0):
            raise BacktestValidationError("historical_lot_size must be a positive integer when provided.")
        if str(self.instrument_type).strip().upper() not in ("EQ", "INDEX_SPOT", "FUTIDX"):
            raise BacktestValidationError("Historical execution supports EQ or explicit FUTIDX contracts; options remain unsupported.")
        if self.execution_convention != "NEXT_CANDLE_OPEN":
            raise BacktestValidationError(
                f"Unsupported execution_convention {self.execution_convention!r}; only 'NEXT_CANDLE_OPEN' is supported to prevent look-ahead bias."
            )
        if self.target_mode not in ("TARGET_1", "TARGET_2"):
            raise BacktestValidationError("target_mode must be 'TARGET_1' or 'TARGET_2'.")
        if self.same_candle_collision_rule != "STOP_LOSS_FIRST_CONSERVATIVE":
            raise BacktestValidationError(
                "same_candle_collision_rule must be 'STOP_LOSS_FIRST_CONSERVATIVE'."
            )
        if self.period_type not in ("FULL", "TRAIN", "VALIDATION", "OUT_OF_SAMPLE"):
            raise BacktestValidationError(
                f"Invalid period_type {self.period_type!r}; expected FULL, TRAIN, VALIDATION, or OUT_OF_SAMPLE."
            )
        if self.evaluation_start_date and self.evaluation_end_date:
            d1 = datetime.strptime(self.evaluation_start_date.strip(), "%Y-%m-%d").date()
            d2 = datetime.strptime(self.evaluation_end_date.strip(), "%Y-%m-%d").date()
            if d2 < d1:
                raise BacktestValidationError(
                    f"evaluation_end_date ({self.evaluation_end_date}) cannot be earlier than evaluation_start_date ({self.evaluation_start_date})."
                )
        self.cost_model.validate()


# ============================================================================
# 4. CHRONOLOGICAL PERIOD SPLITTING (Section 13)
# ============================================================================
def split_sessions_chronologically(
    session_dates: List[str],
    train_ratio: float = 0.60,
    validation_ratio: float = 0.20,
    test_ratio: float = 0.20,
) -> Dict[str, Any]:
    """
    Splits a sorted list of distinct NSE trading session dates ('YYYY-MM-DD') into
    non-overlapping chronological TRAIN, VALIDATION, and OUT_OF_SAMPLE periods.
    Requires at least 3 distinct trading sessions so each split receives >= 1 session.
    """
    if abs((train_ratio + validation_ratio + test_ratio) - 1.0) > 1e-6:
        raise BacktestValidationError("train_ratio + validation_ratio + test_ratio must equal 1.0.")
    unique_sessions = sorted({str(s).strip() for s in (session_dates or []) if str(s).strip()})
    n = len(unique_sessions)
    if n < 3:
        return {
            "status": "BLOCKED_INSUFFICIENT_HISTORICAL_SESSIONS",
            "total_sessions": n,
            "reason": (
                f"Chronological TRAIN / VALIDATION / OUT_OF_SAMPLE splitting requires at least 3 distinct "
                f"validated trading sessions, but only {n} session(s) are available."
            ),
            "splits": None,
        }

    n_train = max(1, int(round(n * train_ratio)))
    n_val = max(1, int(round(n * validation_ratio)))
    if n_train + n_val >= n:
        n_train = max(1, n - 2)
        n_val = 1
    n_test = n - n_train - n_val

    train_sess = unique_sessions[:n_train]
    val_sess = unique_sessions[n_train : n_train + n_val]
    test_sess = unique_sessions[n_train + n_val :]

    return {
        "status": "READY",
        "total_sessions": n,
        "reason": None,
        "splits": {
            "TRAIN": {
                "period_type": "TRAIN",
                "sessions": train_sess,
                "start_date": train_sess[0],
                "end_date": train_sess[-1],
                "sessions_count": len(train_sess),
            },
            "VALIDATION": {
                "period_type": "VALIDATION",
                "sessions": val_sess,
                "start_date": val_sess[0],
                "end_date": val_sess[-1],
                "sessions_count": len(val_sess),
            },
            "OUT_OF_SAMPLE": {
                "period_type": "OUT_OF_SAMPLE",
                "sessions": test_sess,
                "start_date": test_sess[0],
                "end_date": test_sess[-1],
                "sessions_count": len(test_sess),
            },
        },
    }


# ============================================================================
# 5. STRATEGY ELIGIBILITY & INPUT VALIDATION (Section 5 & Section 12)
# ============================================================================
def evaluate_strategy_backtest_eligibility(
    strategy_id: str,
    symbol: str,
    segment: str,
    candles: List[Dict[str, Any]],
    interval_min: int = 5,
    instrument_type: str = "EQ",
    historical_lot_size: Optional[int] = None,
    historical_option_chains_by_timestamp: Optional[Dict[str, Dict[str, Any]]] = None,
    historical_option_candles_by_contract: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    evaluation_start_date: Optional[str] = None,
    evaluation_end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates whether `strategy_id` is eligible to run a historical backtest on the supplied
    validated dataset and metadata. Never silently weakens strategy rules.
    """
    sid = str(strategy_id or "").strip()
    if sid not in STRATEGY_BACKTEST_ELIGIBILITY:
        raise BacktestValidationError(
            f"Unknown strategy_id {strategy_id!r}. Valid strategies: {sorted(STRATEGY_BACKTEST_ELIGIBILITY.keys())}"
        )

    spec = STRATEGY_BACKTEST_ELIGIBILITY[sid]
    if sid == "strat_3_option_apex_oi":
        return _strategy_3_historical_rejection()

    sym = str(symbol or "").strip().upper()
    seg = str(segment or "").strip().upper()
    inst_type = str(instrument_type or ("INDEX_SPOT" if sym in INDEX_SYMBOLS else "EQ")).strip().upper()

    if int(interval_min) != int(spec["timeframe_min"]):
        return {
            "eligible": False,
            "strategy_id": sid,
            "strategy_name": spec["strategy_name"],
            "status": "BLOCKED_TIMEFRAME_MISMATCH",
            "reason": f"{spec['strategy_name']} requires {spec['timeframe_min']}m candles, got {interval_min}m.",
        }

    # Index Spot vs Executable Derivative Contract rule (Section 9)
    if sym in INDEX_SYMBOLS or seg == "NSE_FO_INDEX":
        if sid != "strat_3_option_apex_oi":
            if inst_type == "INDEX_SPOT":
                return {
                    "eligible": False,
                    "strategy_id": sid,
                    "strategy_name": spec["strategy_name"],
                    "status": "BLOCKED_NON_EXECUTABLE_INDEX_SPOT",
                    "reason": (
                        f"{sym} index spot prices are not directly executable trading fills and carry zero cash-index "
                        f"volume. Backtesting {spec['strategy_name']} on {sym} requires executable futures contract "
                        f"OHLCV bars (instrument_type='FUTIDX') with positive volume and verified historical_lot_size."
                    ),
                }
            if isinstance(historical_lot_size, bool) or not isinstance(historical_lot_size, int) or historical_lot_size <= 0:
                return {
                    "eligible": False,
                    "strategy_id": sid,
                    "strategy_name": spec["strategy_name"],
                    "status": "BLOCKED_MISSING_HISTORICAL_LOT_SIZE",
                    "reason": (
                        f"Backtesting derivative symbol {sym} ({inst_type}) requires verified historical_lot_size "
                        f"metadata for the test dates; current lot sizes must not be retroactively assumed."
                    ),
                }

    if (seg == "NSE_EQUITY_INTRADAY" and inst_type != "EQ") or (seg == "NSE_FO_INDEX" and inst_type != "FUTIDX"):
        return {"eligible": False, "strategy_id": sid, "strategy_name": spec["strategy_name"],
                "status": "BLOCKED_INSTRUMENT_QUANTITY_RULES",
                "reason": "Only equity shares or explicit index futures with supplied historical lots are supported."}

    completed_bars = [b for b in (candles or []) if b.get("is_complete") is True]
    min_bars = int(spec["min_completed_bars"])
    if len(completed_bars) < min_bars:
        status_code = (
            "BLOCKED_INSUFFICIENT_200_BAR_WARMUP"
            if min_bars >= 200
            else "BLOCKED_INSUFFICIENT_WARMUP_BARS"
        )
        return {
            "eligible": False,
            "strategy_id": sid,
            "strategy_name": spec["strategy_name"],
            "status": status_code,
            "reason": (
                f"{spec['strategy_name']} requires at least {min_bars} completed {interval_min}m bars, "
                f"but dataset contains only {len(completed_bars)} completed bar(s)."
            ),
        }

    # Filter bars in evaluation window to check volume and ORB requirements
    eval_bars = completed_bars
    if evaluation_start_date:
        eval_bars = [b for b in eval_bars if str(b.get("session_date") or str(b["timestamp"])[:10]) >= evaluation_start_date]
    if evaluation_end_date:
        eval_bars = [b for b in eval_bars if str(b.get("session_date") or str(b["timestamp"])[:10]) <= evaluation_end_date]

    if not eval_bars:
        return {
            "eligible": False,
            "strategy_id": sid,
            "strategy_name": spec["strategy_name"],
            "status": "BLOCKED_EMPTY_EVALUATION_PERIOD",
            "reason": "No completed candles exist inside the requested evaluation date range.",
        }

    if spec["required_volume_oi_options_inputs"]["requires_positive_volume"]:
        zero_vol_count = sum(1 for b in completed_bars if float(b.get("volume", 0.0)) <= 0.0)
        if zero_vol_count == len(completed_bars) or any(float(b.get("volume", 0.0)) <= 0.0 for b in eval_bars):
            return {
                "eligible": False,
                "strategy_id": sid,
                "strategy_name": spec["strategy_name"],
                "status": "BLOCKED_ZERO_VOLUME_SERIES",
                "reason": (
                    f"{spec['strategy_name']} requires positive traded volume (volume > 0) for RVOL and "
                    f"volume-weighted session VWAP, but dataset contains zero-volume bars."
                ),
            }

    if spec["required_volume_oi_options_inputs"]["requires_opening_range_0915_0930"]:
        eval_sessions = sorted({str(b.get("session_date") or str(b["timestamp"])[:10]) for b in eval_bars})
        all_ts = {str(b["timestamp"]) for b in completed_bars}
        missing_orb_sessions = [
            s for s in eval_sessions
            if not all(f"{s} {t_str}" in all_ts for t_str in ("09:15:00", "09:20:00", "09:25:00"))
        ]
        if missing_orb_sessions:
            return {
                "eligible": False,
                "strategy_id": sid,
                "strategy_name": spec["strategy_name"],
                "status": "BLOCKED_MISSING_OPENING_RANGE_BARS",
                "reason": (
                    f"Strategy 4 (15m ORB) requires all three opening-range 5m bars (09:15, 09:20, 09:25 IST) "
                    f"on each evaluated session; missing on session(s): {missing_orb_sessions}."
                ),
            }

    return {
        "eligible": True,
        "strategy_id": sid,
        "strategy_name": spec["strategy_name"],
        "status": "ELIGIBLE",
        "reason": None,
    }


# ============================================================================
# 6. PERFORMANCE METRICS COMPUTATION (Section 11)
# ============================================================================
def compute_backtest_metrics(
    trades: List[Dict[str, Any]],
    starting_capital_inr: float,
    session_dates_evaluated: List[str],
    total_bars_evaluated: int,
    missing_bars_count: int = 0,
    open_position_missing_bars_count: int = 0,
    rejected_signals: Optional[List[Dict[str, Any]]] = None,
    daily_status_by_session: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Computes all required Phase 3B performance metrics from the simulated trade ledger.
    Handles zero trades, zero losses, and zero denominators safely without fabricating finite
    profit factors when losing_trades == 0.
    """
    rej_list = list(rejected_signals or [])
    rej_by_reason: Dict[str, int] = {}
    for item in rej_list:
        r_key = str(item.get("reason") or "UNKNOWN")
        rej_by_reason[r_key] = rej_by_reason.get(r_key, 0) + 1

    n_trades = len(trades)
    wins = [t for t in trades if float(t["net_pnl_inr"]) > 0.0]
    losses = [t for t in trades if float(t["net_pnl_inr"]) < 0.0]
    flats = [t for t in trades if float(t["net_pnl_inr"]) == 0.0]

    n_win = len(wins)
    n_loss = len(losses)
    n_flat = len(flats)
    win_rate_pct = round((n_win / n_trades) * 100.0, 2) if n_trades > 0 else 0.0

    gross_pnl_inr = round(sum(float(t["gross_pnl_inr"]) for t in trades), 2)
    total_charges_inr = round(sum(float(t["charges_inr"]) for t in trades), 2)
    total_slippage_inr = round(sum(float(t["slippage_inr"]) for t in trades), 2)
    total_costs_inr = round(sum(float(t["total_costs_inr"]) for t in trades), 2)
    net_pnl_inr = round(sum(float(t["net_pnl_inr"]) for t in trades), 2)

    avg_win_inr = round(sum(float(t["net_pnl_inr"]) for t in wins) / n_win, 2) if n_win > 0 else 0.0
    avg_loss_inr = round(sum(float(t["net_pnl_inr"]) for t in losses) / n_loss, 2) if n_loss > 0 else 0.0
    expectancy_inr = round(net_pnl_inr / n_trades, 2) if n_trades > 0 else 0.0

    gross_profit_wins = sum(float(t["net_pnl_inr"]) for t in wins)
    gross_loss_abs = sum(abs(float(t["net_pnl_inr"])) for t in losses)

    if n_trades == 0 or (gross_profit_wins == 0.0 and gross_loss_abs == 0.0):
        profit_factor: Optional[float] = None
        profit_factor_status = "NO_TRADES" if n_trades == 0 else "ZERO_PNL"
        profit_factor_display = "N/A (NO_TRADES)" if n_trades == 0 else "0.00 (ZERO_PNL)"
    elif gross_loss_abs == 0.0:
        profit_factor = None
        profit_factor_status = "UNDEFINED_ZERO_LOSSES"
        profit_factor_display = "INF_NO_LOSSES"
    else:
        profit_factor = round(gross_profit_wins / gross_loss_abs, 4)
        profit_factor_status = "FINITE"
        profit_factor_display = f"{profit_factor:.2f}"

    # Equity curve and peak-to-trough maximum drawdown
    equity_curve: List[Dict[str, Any]] = [
        {
            "step": 0,
            "timestamp": None,
            "equity_inr": round(float(starting_capital_inr), 2),
            "drawdown_inr": 0.0,
            "drawdown_pct": 0.0,
        }
    ]
    curr_eq = float(starting_capital_inr)
    peak_eq = curr_eq
    max_dd_inr = 0.0
    max_dd_pct = 0.0

    for idx, t in enumerate(trades, start=1):
        curr_eq = round(curr_eq + float(t["net_pnl_inr"]), 2)
        if curr_eq > peak_eq:
            peak_eq = curr_eq
        dd_inr = round(peak_eq - curr_eq, 2)
        dd_pct = round((dd_inr / peak_eq) * 100.0, 4) if peak_eq > 0 else 0.0
        if dd_inr > max_dd_inr:
            max_dd_inr = dd_inr
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
        equity_curve.append({
            "step": idx,
            "timestamp": t["exit_timestamp"],
            "equity_inr": curr_eq,
            "drawdown_inr": dd_inr,
            "drawdown_pct": dd_pct,
        })

    return_on_capital_pct = round((net_pnl_inr / float(starting_capital_inr)) * 100.0, 4)
    avg_r_multiple = (
        round(sum(float(t["realized_r_multiple"]) for t in trades) / n_trades, 4)
        if n_trades > 0
        else 0.0
    )

    # Consecutive wins and losses
    max_consec_wins = 0
    max_consec_losses = 0
    cur_w = 0
    cur_l = 0
    for t in trades:
        npnl = float(t["net_pnl_inr"])
        if npnl > 0:
            cur_w += 1
            cur_l = 0
            if cur_w > max_consec_wins:
                max_consec_wins = cur_w
        elif npnl < 0:
            cur_l += 1
            cur_w = 0
            if cur_l > max_consec_losses:
                max_consec_losses = cur_l
        else:
            cur_w = 0
            cur_l = 0

    # Long vs Short breakdown
    def _side_stats(side_label: str) -> Dict[str, Any]:
        sub = [t for t in trades if t.get("position_side") == side_label]
        s_cnt = len(sub)
        s_wins = [t for t in sub if float(t["net_pnl_inr"]) > 0.0]
        s_losses = [t for t in sub if float(t["net_pnl_inr"]) < 0.0]
        return {
            "trades": s_cnt,
            "winning_trades": len(s_wins),
            "losing_trades": len(s_losses),
            "win_rate_pct": round((len(s_wins) / s_cnt) * 100.0, 2) if s_cnt > 0 else 0.0,
            "gross_pnl_inr": round(sum(float(t["gross_pnl_inr"]) for t in sub), 2),
            "total_costs_inr": round(sum(float(t["total_costs_inr"]) for t in sub), 2),
            "net_pnl_inr": round(sum(float(t["net_pnl_inr"]) for t in sub), 2),
            "average_r_multiple": round(sum(float(t["realized_r_multiple"]) for t in sub) / s_cnt, 4) if s_cnt > 0 else 0.0,
        }

    long_vs_short = {
        "LONG": _side_stats("LONG"),
        "SHORT": _side_stats("SHORT"),
    }

    # Performance by day
    by_day: Dict[str, Dict[str, Any]] = {}
    running_day_eq = float(starting_capital_inr)
    all_days = sorted(set(session_dates_evaluated) | {str(t["session_date"]) for t in trades})
    for d_str in all_days:
        d_trades = [t for t in trades if str(t["session_date"]) == d_str]
        d_wins = [t for t in d_trades if float(t["net_pnl_inr"]) > 0.0]
        d_losses = [t for t in d_trades if float(t["net_pnl_inr"]) < 0.0]
        d_gross = round(sum(float(t["gross_pnl_inr"]) for t in d_trades), 2)
        d_costs = round(sum(float(t["total_costs_inr"]) for t in d_trades), 2)
        d_net = round(sum(float(t["net_pnl_inr"]) for t in d_trades), 2)
        running_day_eq = round(running_day_eq + d_net, 2)
        d_meta = (daily_status_by_session or {}).get(d_str, {})
        by_day[d_str] = {
            "session_date": d_str,
            "trades": len(d_trades),
            "winning_trades": len(d_wins),
            "losing_trades": len(d_losses),
            "gross_pnl_inr": d_gross,
            "total_costs_inr": d_costs,
            "net_pnl_inr": d_net,
            "ending_equity_inr": running_day_eq,
            "daily_loss_limit_triggered": bool(d_meta.get("daily_loss_limit_triggered", False)),
            "daily_profit_target_triggered": bool(d_meta.get("daily_profit_target_triggered", False)),
        }

    # Performance by strategy
    by_strategy: Dict[str, Dict[str, Any]] = {}
    for sid in sorted({str(t["strategy_id"]) for t in trades}):
        s_trades = [t for t in trades if str(t["strategy_id"]) == sid]
        s_wins = [t for t in s_trades if float(t["net_pnl_inr"]) > 0.0]
        s_losses = [t for t in s_trades if float(t["net_pnl_inr"]) < 0.0]
        by_strategy[sid] = {
            "strategy_id": sid,
            "trades": len(s_trades),
            "winning_trades": len(s_wins),
            "losing_trades": len(s_losses),
            "win_rate_pct": round((len(s_wins) / len(s_trades)) * 100.0, 2) if s_trades else 0.0,
            "gross_pnl_inr": round(sum(float(t["gross_pnl_inr"]) for t in s_trades), 2),
            "total_costs_inr": round(sum(float(t["total_costs_inr"]) for t in s_trades), 2),
            "net_pnl_inr": round(sum(float(t["net_pnl_inr"]) for t in s_trades), 2),
        }

    # Exposure & holding duration
    holding_mins = [float(t.get("holding_minutes", 0.0)) for t in trades]
    holding_bars_list = [int(t.get("holding_bars", 0)) for t in trades]
    total_bars_in_market = sum(holding_bars_list)
    exposure_pct = (
        round((total_bars_in_market / max(1, int(total_bars_evaluated))) * 100.0, 2)
        if total_bars_evaluated > 0
        else 0.0
    )
    exposure_metrics = {
        "total_bars_evaluated": int(total_bars_evaluated),
        "total_bars_in_market": int(total_bars_in_market),
        "time_in_market_pct": exposure_pct,
        "average_holding_minutes": round(sum(holding_mins) / n_trades, 2) if n_trades > 0 else 0.0,
        "max_holding_minutes": round(max(holding_mins), 2) if n_trades > 0 else 0.0,
        "min_holding_minutes": round(min(holding_mins), 2) if n_trades > 0 else 0.0,
    }

    return {
        "total_trades": n_trades,
        "winning_trades": n_win,
        "losing_trades": n_loss,
        "breakeven_trades": n_flat,
        "win_rate_pct": win_rate_pct,
        "gross_pnl_inr": gross_pnl_inr,
        "total_charges_inr": total_charges_inr,
        "total_slippage_inr": total_slippage_inr,
        "total_costs_inr": total_costs_inr,
        "net_pnl_inr": net_pnl_inr,
        "average_win_inr": avg_win_inr,
        "average_loss_inr": avg_loss_inr,
        "expectancy_per_trade_inr": expectancy_inr,
        "profit_factor": profit_factor,
        "profit_factor_status": profit_factor_status,
        "profit_factor_display": profit_factor_display,
        "max_drawdown_inr": max_dd_inr,
        "max_drawdown_pct": max_dd_pct,
        "starting_capital_inr": round(float(starting_capital_inr), 2),
        "ending_capital_inr": round(float(starting_capital_inr) + net_pnl_inr, 2),
        "return_on_starting_capital_pct": return_on_capital_pct,
        "average_r_multiple": avg_r_multiple,
        "consecutive_wins_max": max_consec_wins,
        "consecutive_losses_max": max_consec_losses,
        "long_vs_short_performance": long_vs_short,
        "performance_by_day": by_day,
        "performance_by_strategy": by_strategy,
        "exposure_and_holding_duration": exposure_metrics,
        "missing_bars_count": int(missing_bars_count),
        "open_position_missing_bars_count": int(open_position_missing_bars_count),
        "rejected_signals_count": len(rej_list),
        "rejected_signals_by_reason": rej_by_reason,
        "equity_curve": equity_curve,
        "profitability_claim_justified": False,
        "profitability_note": (
            "Win rate alone never establishes profitability. No strategy profitability claim is made "
            "until Phase 2C live-data acceptance and out-of-sample LIVE historical validation pass."
        ),
    }


# ============================================================================
# 7. DETERMINISTIC POINT-IN-TIME BACKTESTING ENGINE (Sections 6, 7, 8, 10, 12)
# ============================================================================
class DeterministicBacktestEngine:
    """
    Deterministic, point-in-time historical backtesting engine for TradePulse AI:
    - Enforces Phase 2C/3A readiness gates on LIVE runs and labels SIMULATED/TEST runs explicitly.
    - Replays completed 5m candles bar-by-bar using `get_point_in_time_candle_slice` and
      `verify_no_lookahead_leakage` so strategies never access future or forming candles.
    - Executes entries strictly at the next contiguous same-session 5m candle's open
      (`NEXT_CANDLE_OPEN`), rejecting entries when the next bar is missing, at/after 15:15 IST,
      or gapped beyond stop-loss.
    - Resolves same-candle stop-loss and target collisions conservatively (`STOP_LOSS_FIRST_CONSERVATIVE`).
    - Squares off all intraday positions at 15:20 IST (or last session bar) with zero overnight carry.
    - Enforces configurable capital, per-trade risk, daily loss limit, and daily profit target.
    """

    def __init__(
        self,
        bot_config: Optional[BotConfig] = None,
        store: Optional[SQLitePersistenceStore] = None,
        broker_status: Optional[Dict[str, Any]] = None,
        clock: Optional[Any] = None,
    ) -> None:
        self.bot_config = bot_config or BotConfig()
        self.store = store
        self.broker_status = broker_status
        self.clock = clock or (lambda: datetime.now(IST))

    def _invoke_strategy_evaluator(
        self,
        strategy_id: str,
        symbol: str,
        segment: str,
        pit_candles: List[Dict[str, Any]],
        decision_dt: datetime,
        capital_inr: float,
        risk_pct: float,
        mitigated_zones: Set[str],
        market_breadth: Optional[Dict[str, Any]] = None,
        option_chain: Optional[Dict[str, Any]] = None,
        lot_size: Optional[int] = None,
        execution_costs: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> Optional[TradeSignal]:
        if strategy_id == "strat_1_order_block":
            return evaluate_order_block_fvg(
                symbol=symbol,
                candles=pit_candles,
                capital_inr=capital_inr,
                risk_pct=risk_pct,
                segment=segment,
                now=decision_dt,
                market_breadth=market_breadth,
                mitigated_zones=mitigated_zones,
                lot_size=lot_size, execution_costs=execution_costs,
            )
        if strategy_id == "strat_2_vwap_pullback":
            return evaluate_vwap_pullback(
                symbol=symbol,
                candles=pit_candles,
                capital_inr=capital_inr,
                risk_pct=risk_pct,
                segment=segment,
                now=decision_dt,
                market_breadth=market_breadth,
                lot_size=lot_size, execution_costs=execution_costs,
            )
        if strategy_id == "strat_3_option_apex_oi":
            _ensure_historical_strategy_supported(strategy_id)
        if strategy_id == "strat_4_orb_filtered":
            return evaluate_orb_breakout(
                symbol=symbol,
                candles=pit_candles,
                capital_inr=capital_inr,
                risk_pct=risk_pct,
                segment=segment,
                now=decision_dt,
                market_breadth=market_breadth,
                lot_size=lot_size, execution_costs=execution_costs,
            )
        if strategy_id == "strat_5_supertrend_pullback":
            return evaluate_supertrend_pullback(
                symbol=symbol,
                candles=pit_candles,
                capital_inr=capital_inr,
                risk_pct=risk_pct,
                segment=segment,
                now=decision_dt,
                market_breadth=market_breadth,
                lot_size=lot_size, execution_costs=execution_costs,
            )
        raise BacktestValidationError(f"Unsupported strategy_id: {strategy_id!r}")

    def run_backtest(
        self,
        strategy_id: str,
        symbol: str,
        candles: Optional[List[Dict[str, Any]]] = None,
        segment: Optional[str] = None,
        exchange: str = "NSE",
        provider: Optional[str] = None,
        instrument_token: str = "2885",
        interval_min: int = 5,
        data_mode: str = "SIMULATED",
        backtest_config: Optional[BacktestConfig] = None,
        universe_candles_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        historical_option_chains_by_timestamp: Optional[Dict[str, Dict[str, Any]]] = None,
        historical_option_candles_by_contract: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        persist_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes a deterministic historical backtest for `strategy_id` on `symbol`.
        If `candles` is None, loads persisted candles for `(symbol, interval_min, data_mode)`
        from `self.store`.

        Entry convention: both the raw next open and the adverse-slippage effective entry
        must lie strictly between stop and selected target (LONG: stop < price < target;
        SHORT: target < price < stop). Equality rejects entry, with stop rejection taking
        precedence. Effective prices use the cost model's four-decimal rounding. OHLC
        triggers/raw fills remain separate from the existing slippage cost adjustment.
        """
        _ensure_historical_strategy_supported(strategy_id)

        bt_cfg = backtest_config or BacktestConfig(
            starting_capital_inr=self.bot_config.account_capital_inr,
            risk_per_trade_pct=self.bot_config.max_risk_per_trade_pct,
            max_daily_loss_inr=self.bot_config.max_daily_loss_inr,
            daily_profit_target_inr=self.bot_config.daily_profit_target_inr,
            max_concurrent_positions=self.bot_config.max_concurrent_positions,
        )
        bt_cfg.validate()

        sym = str(symbol or "").strip().upper()
        seg = str(segment or ("NSE_FO_INDEX" if sym in INDEX_SYMBOLS else "NSE_EQUITY_INTRADAY")).strip().upper()
        dm = str(data_mode or "SIMULATED").strip().upper()
        if dm not in ("LIVE", "SIMULATED"):
            raise BacktestValidationError(f"Invalid data_mode {data_mode!r}; expected 'LIVE' or 'SIMULATED'.")
        from readiness_policy import resolve_provider
        provider = resolve_provider(self.bot_config, dm, provider)

        # Same scoped decision returned by readiness/eligibility APIs. Legacy gate
        # flags and connection booleans cannot supply acceptance evidence.
        readiness = evaluate_phase3a_backtest_readiness(
            config=self.bot_config,
            store=self.store,
            broker_status=self.broker_status,
            target_data_mode=dm,
            provider=provider, symbol=sym, strategy_id=strategy_id,
            execution_scope=bt_cfg.execution_scope, now=self.clock(),
            candles=candles, segment=seg, exchange=exchange,
            instrument_token=instrument_token, interval_min=interval_min,
            start_date=bt_cfg.evaluation_start_date, end_date=bt_cfg.evaluation_end_date,
        )
        gate = readiness["execution_gate"]
        if not gate["allowed"]:
            raise BacktestReadinessError(
                f"Backtest blocked by acceptance/coverage policy: {gate['reason_code']}", gate
            )

        # Load candles from SQLite store if not passed directly
        if candles is None:
            if self.store is None:
                raise BacktestValidationError("No candles list provided and SQLite store is None.")
            q_res = self.store.query_historical_candles(
                symbol=sym,
                interval_min=interval_min,
                data_mode=dm,
                provider=provider if provider and provider != "synthetic_fixture" else None,
                limit=10000,
                offset=0,
            )
            candles = q_res.get("items", [])
            if not candles:
                raise BacktestEligibilityError(
                    f"No persisted {dm} historical candles found in SQLite for symbol={sym}, interval={interval_min}m."
                )
            first_row = candles[0]
            seg = str(first_row.get("segment") or seg)
            exchange = str(first_row.get("exchange") or exchange)
            provider = str(first_row.get("provider") or provider)
            instrument_token = str(first_row.get("instrument_token") or instrument_token)

        # Validate & prepare dataset via Phase 3A validator (enforces IST grid, holidays, duplicates, OHLCV, mode isolation)
        try:
            prepared = validate_and_prepare_historical_dataset(
                candles=candles,
                symbol=sym,
                segment=seg,
                exchange=exchange,
                provider=provider,
                instrument_token=instrument_token,
                interval_min=interval_min,
                data_mode=dm,
                configured_holidays=self.bot_config.configured_holidays,
                session_start_ist=self.bot_config.session_start_ist or "09:15",
                session_end_ist=self.bot_config.session_end_ist or "15:30",
                allow_identical_duplicates=True,
                sort_chronologically=True,
                reject_forming_candles=True,
                require_complete_sessions=dm == "LIVE",
                reference_time_ist=self.clock(),
            )
        except HistoricalDataValidationError as exc:
            raise BacktestValidationError(str(exc)) from exc

        manifest = prepared["manifest"]
        validated_bars: List[Dict[str, Any]] = prepared["candles"]

        # Verify Strategy Eligibility before replay
        eligibility = evaluate_strategy_backtest_eligibility(
            strategy_id=strategy_id,
            symbol=sym,
            segment=seg,
            candles=validated_bars,
            interval_min=interval_min,
            instrument_type=bt_cfg.instrument_type,
            historical_lot_size=bt_cfg.historical_lot_size,
            historical_option_chains_by_timestamp=historical_option_chains_by_timestamp,
            historical_option_candles_by_contract=historical_option_candles_by_contract,
            evaluation_start_date=bt_cfg.evaluation_start_date,
            evaluation_end_date=bt_cfg.evaluation_end_date,
        )
        if not eligibility["eligible"]:
            raise BacktestEligibilityError(f"{eligibility['status']}: {eligibility['reason']}")

        historical_identity = {"historical_validity": "SIMULATED_UNVERIFIED"}
        if dm == "LIVE":
            try:
                if self.store is None:
                    raise IdentityValidationError("ARCHIVE_STORE_REQUIRED", "LIVE historical identity requires durable archive storage.")
                archive_id = bt_cfg.historical_instrument_archive_id
                if bt_cfg.historical_instrument_identity is not None:
                    if archive_id is not None:
                        raise IdentityValidationError("AMBIGUOUS_ARCHIVE_INPUT", "Supply an archive ID or inline archive, not both.")
                    inline = bt_cfg.historical_instrument_identity
                    if not isinstance(inline, dict):
                        raise IdentityValidationError("INVALID_ARCHIVE_SCHEMA", "Inline archive must be an object.")
                    digest(inline)  # Reject non-JSON/nonfinite inline provenance with a structured error.
                    ingested = self.store.ingest_instrument_master_bytes(
                        json.dumps(inline, sort_keys=True, allow_nan=False).encode(), provider, "inline-master.json",
                        str(inline.get("source_reference") or "INLINE_USER_SUPPLIED_ARCHIVE"),
                        input_kind="INLINE_SERIALIZATION")
                    archive_id = ingested["archive_id"]
                    if ingested["status"] != "ELIGIBLE_LOCAL_RESEARCH":
                        raise IdentityValidationError("HISTORICAL_IDENTITY_UNVERIFIED", "Inline/legacy master has no eligible archive provenance and coverage.")
                historical_identity = self.store.resolve_archived_instrument_identity(provider, sym, instrument_token,
                    exchange, bt_cfg.instrument_type.upper(), validated_bars[0]["session_date"],
                    validated_bars[-1]["session_date"], bt_cfg.historical_lot_size, archive_id)
            except IdentityValidationError as exc:
                error = BacktestEligibilityError(f"{exc.rejection['reason_code']}: {exc}")
                error.details = exc.rejection
                raise error from exc

        # Determine evaluation window bars (earlier bars warm up indicators without triggering trades)
        all_sessions = sorted({b["session_date"] for b in validated_bars})
        eval_sessions = [
            s for s in all_sessions
            if (bt_cfg.evaluation_start_date is None or s >= bt_cfg.evaluation_start_date)
            and (bt_cfg.evaluation_end_date is None or s <= bt_cfg.evaluation_end_date)
        ]
        eval_sessions_set = set(eval_sessions)

        bar_delta = timedelta(minutes=interval_min)
        cutoff_time = dt_time(
            int(bt_cfg.last_entry_Cutoff_ist.split(":")[0]),
            int(bt_cfg.last_entry_Cutoff_ist.split(":")[1]),
        )
        square_off_time = dt_time(
            int(bt_cfg.eod_square_off_ist.split(":")[0]),
            int(bt_cfg.eod_square_off_ist.split(":")[1]),
        )

        # Pre-index last bar index of each session date for EOD / end-of-session handling
        last_bar_idx_by_session: Dict[str, int] = {}
        for idx, b in enumerate(validated_bars):
            last_bar_idx_by_session[b["session_date"]] = idx

        # Replay state
        mitigated_zones: Set[str] = set()
        current_capital_inr = float(bt_cfg.starting_capital_inr)
        trades: List[Dict[str, Any]] = []
        rejected_signals: List[Dict[str, Any]] = []
        daily_status: Dict[str, Dict[str, Any]] = {
            s: {
                "session_date": s,
                "realized_net_pnl_inr": 0.0,
                "worst_intraday_unrealized_pnl_inr": 0.0,
                "daily_loss_limit_triggered": False,
                "daily_profit_target_triggered": False,
            }
            for s in eval_sessions
        }

        open_position: Optional[Dict[str, Any]] = None
        pending_signal: Optional[Tuple[int, TradeSignal]] = None
        open_position_missing_bars_count = 0
        total_eval_bars = 0

        def estimate_execution_costs(entry, stop, quantity, side):
            return bt_cfg.cost_model.compute_trade_costs(
                entry, stop, quantity, side, segment=seg,
                instrument_type=bt_cfg.instrument_type, exchange=exchange)

        for idx, bar in enumerate(validated_bars):
            bar_start_dt = parse_ist_timestamp(bar["timestamp"])
            bar_end_dt = bar_start_dt + bar_delta
            bar_time = bar_start_dt.timetz().replace(tzinfo=None)
            sess_date = bar["session_date"]
            in_eval_window = sess_date in eval_sessions_set
            if in_eval_window:
                total_eval_bars += 1

            # Check if there was a missing-bar time gap while a position was open on the same session
            if open_position is not None and idx > open_position["entry_bar_idx"]:
                prev_bar = validated_bars[idx - 1]
                if prev_bar["session_date"] == sess_date:
                    prev_start_dt = parse_ist_timestamp(prev_bar["timestamp"])
                    gap_mins = int((bar_start_dt - prev_start_dt).total_seconds() // 60)
                    if gap_mins > interval_min:
                        missed_count = (gap_mins // interval_min) - 1
                        open_position_missing_bars_count += max(1, missed_count)
                        open_position["missing_bars_during_trade"] += max(1, missed_count)

            # ----------------------------------------------------------------
            # STEP A: Execute Pending Signal at Next Eligible Candle Open
            # ----------------------------------------------------------------
            if pending_signal is not None:
                sig_bar_idx, sig = pending_signal
                pending_signal = None
                sig_bar = validated_bars[sig_bar_idx]
                sig_bar_start_dt = parse_ist_timestamp(sig_bar["timestamp"])
                expected_entry_dt = sig_bar_start_dt + bar_delta

                day_state = daily_status.setdefault(
                    sess_date,
                    {
                        "session_date": sess_date,
                        "realized_net_pnl_inr": 0.0,
                        "worst_intraday_unrealized_pnl_inr": 0.0,
                        "daily_loss_limit_triggered": False,
                        "daily_profit_target_triggered": False,
                    },
                )

                if sess_date != sig_bar["session_date"]:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "SIGNAL_ON_FINAL_SESSION_BAR_NO_OVERNIGHT_ENTRY",
                    })
                elif bar_start_dt != expected_entry_dt:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "MISSING_NEXT_CANDLE_GAP",
                        "expected_entry_timestamp": format_ist_timestamp(expected_entry_dt),
                        "actual_next_timestamp": bar["timestamp"],
                    })
                elif bar_time >= cutoff_time:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "SIGNAL_AT_OR_AFTER_EOD_ENTRY_CUTOFF",
                        "entry_bar_timestamp": bar["timestamp"],
                    })
                elif open_position is not None:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "MAX_CONCURRENT_POSITIONS_REACHED",
                    })
                elif day_state["daily_loss_limit_triggered"]:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "DAILY_LOSS_LIMIT_REACHED",
                    })
                elif day_state["daily_profit_target_triggered"]:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "DAILY_PROFIT_TARGET_REACHED",
                    })
                else:
                    is_long = "BULLISH" in sig.direction.upper()
                    pos_side = "LONG" if is_long else "SHORT"
                    raw_open_price = float(bar["open"])
                    slip_rate = float(bt_cfg.cost_model.slippage_bps_per_leg) / 10000.0
                    entry_slippage_per_unit = raw_open_price * slip_rate
                    eff_entry_preview = round(
                        raw_open_price + entry_slippage_per_unit
                        if is_long
                        else max(0.01, raw_open_price - entry_slippage_per_unit),
                        4,
                    )
                    valid_prices = all(
                        not isinstance(p, bool) and isinstance(p, (int, float))
                        and math.isfinite(float(p)) and p > 0
                        for p in (sig.stop_loss, sig.target_1, sig.target_2)
                    )
                    stop_loss_price = float(sig.stop_loss) if valid_prices else 0.0
                    target_price = float(sig.target_1 if bt_cfg.target_mode == "TARGET_1" else sig.target_2) if valid_prices else 0.0

                    # Both raw and effective entry must remain strictly inside the bracket.
                    gap_invalidated = (
                        (raw_open_price <= stop_loss_price or eff_entry_preview <= stop_loss_price)
                        if is_long
                        else (raw_open_price >= stop_loss_price or eff_entry_preview >= stop_loss_price)
                    )
                    if not valid_prices or sig.direction not in ("BULLISH (BUY)", "BEARISH (SELL)"):
                        rejected_signals.append({
                            "signal_timestamp": sig.timestamp, "symbol": sym, "strategy_id": strategy_id,
                            "direction": sig.direction, "reason": "INVALID_SIGNAL_PRICES_OR_DIRECTION",
                        })
                    elif gap_invalidated:
                        rejected_signals.append({
                            "signal_timestamp": sig.timestamp,
                            "symbol": sym,
                            "strategy_id": strategy_id,
                            "direction": sig.direction,
                            "reason": "NEXT_OPEN_GAP_BEYOND_STOP_LOSS",
                            "next_open": raw_open_price,
                            "effective_entry_price": eff_entry_preview,
                            "stop_loss": stop_loss_price,
                        })
                    elif (
                        (raw_open_price >= target_price or eff_entry_preview >= target_price)
                        if is_long
                        else (raw_open_price <= target_price or eff_entry_preview <= target_price)
                    ):
                        rejected_signals.append({
                            "signal_timestamp": sig.timestamp,
                            "symbol": sym,
                            "strategy_id": strategy_id,
                            "direction": sig.direction,
                            "reason": "NEXT_OPEN_GAP_BEYOND_TARGET",
                            "next_open": raw_open_price,
                            "effective_entry_price": eff_entry_preview,
                            "target_price": target_price,
                        })
                    else:
                        sizing = size_position(
                            raw_open_price, stop_loss_price, current_capital_inr,
                            bt_cfg.risk_per_trade_pct, pos_side,
                            instrument_type=str(bt_cfg.instrument_type).strip().upper(),
                            lot_size=bt_cfg.historical_lot_size,
                            cost_estimator=lambda q: estimate_execution_costs(raw_open_price, stop_loss_price, q, pos_side),
                        )
                        if not sizing["eligible"]:
                            rejected_signals.append({
                                "signal_timestamp": sig.timestamp, "symbol": sym,
                                "strategy_id": strategy_id, "direction": sig.direction,
                                "reason": sizing["reason_code"], "sizing": sizing,
                            })
                        else:
                            qty = sizing["quantity"]
                            open_position = {
                                "signal": sig,
                                "signal_timestamp": sig.timestamp,
                                "entry_bar_idx": idx,
                                "entry_timestamp": bar["timestamp"],
                                "session_date": sess_date,
                                "position_side": pos_side,
                                "direction": sig.direction,
                                "raw_entry_price": raw_open_price,
                                "stop_loss": stop_loss_price,
                                "target_price": target_price,
                                "target_1": float(sig.target_1),
                                "target_2": float(sig.target_2),
                                "quantity": int(qty),
                                "risk_amount_inr": sizing["estimated_risk_inr"],
                                "sizing": sizing,
                                "missing_bars_during_trade": 0,
                            }

            # ----------------------------------------------------------------
            # STEP B: Evaluate Active Open Position on Current Bar
            # ----------------------------------------------------------------
            if open_position is not None:
                pos_side = open_position["position_side"]
                is_long = pos_side == "LONG"
                sl_price = float(open_position["stop_loss"])
                tp_price = float(open_position["target_price"])
                is_entry_bar = idx == open_position["entry_bar_idx"]

                bar_o = float(bar["open"])
                bar_h = float(bar["high"])
                bar_l = float(bar["low"])
                bar_c = float(bar["close"])

                # Track worst intrabar unrealized excursion for daily risk telemetry
                worst_price = bar_l if is_long else bar_h
                unreal_gross = (
                    (worst_price - open_position["raw_entry_price"]) * open_position["quantity"]
                    if is_long
                    else (open_position["raw_entry_price"] - worst_price) * open_position["quantity"]
                )
                day_state = daily_status.setdefault(
                    sess_date,
                    {
                        "session_date": sess_date,
                        "realized_net_pnl_inr": 0.0,
                        "worst_intraday_unrealized_pnl_inr": 0.0,
                        "daily_loss_limit_triggered": False,
                        "daily_profit_target_triggered": False,
                    },
                )
                if unreal_gross < day_state["worst_intraday_unrealized_pnl_inr"]:
                    day_state["worst_intraday_unrealized_pnl_inr"] = round(unreal_gross, 2)

                exit_reason: Optional[str] = None
                raw_exit_price: Optional[float] = None
                same_candle_collision = False

                # 1. Check gap open on subsequent bars (idx > entry_bar_idx)
                if not is_entry_bar:
                    if is_long and bar_o <= sl_price:
                        exit_reason = "STOP_LOSS_GAP_OPEN"
                        raw_exit_price = bar_o
                    elif not is_long and bar_o >= sl_price:
                        exit_reason = "STOP_LOSS_GAP_OPEN"
                        raw_exit_price = bar_o
                    elif is_long and bar_o >= tp_price:
                        exit_reason = "TARGET_GAP_OPEN"
                        raw_exit_price = bar_o
                    elif not is_long and bar_o <= tp_price:
                        exit_reason = "TARGET_GAP_OPEN"
                        raw_exit_price = bar_o

                # 2. Check intrabar High/Low stop-loss and target hits (with conservative collision rule)
                if exit_reason is None:
                    stop_hit = (bar_l <= sl_price) if is_long else (bar_h >= sl_price)
                    target_hit = (bar_h >= tp_price) if is_long else (bar_l <= tp_price)

                    if stop_hit and target_hit:
                        # Conservative Same-Candle Collision Rule: Stop-Loss is ALWAYS assumed hit first
                        exit_reason = "STOP_LOSS_SAME_CANDLE_CONSERVATIVE"
                        raw_exit_price = sl_price
                        same_candle_collision = True
                    elif stop_hit:
                        exit_reason = "STOP_LOSS"
                        raw_exit_price = sl_price
                    elif target_hit:
                        exit_reason = bt_cfg.target_mode
                        raw_exit_price = tp_price

                # 3. Check mandatory EOD square-off or end-of-session / end-of-dataset bar
                is_last_bar_of_session = idx == last_bar_idx_by_session.get(sess_date, -1)
                if exit_reason is None and not bt_cfg.allow_overnight_carry:
                    if bar_time >= square_off_time:
                        exit_reason = "EOD_SQUARE_OFF"
                        raw_exit_price = bar_c
                    elif is_last_bar_of_session:
                        exit_reason = (
                            "END_OF_DATASET_SQUARE_OFF"
                            if idx == len(validated_bars) - 1 and bar_time < square_off_time
                            else "EOD_SQUARE_OFF"
                        )
                        raw_exit_price = bar_c

                if exit_reason is not None and raw_exit_price is not None:
                    qty = int(open_position["quantity"])
                    raw_entry = float(open_position["raw_entry_price"])
                    gross_pnl = round(
                        ((raw_exit_price - raw_entry) * qty)
                        if is_long
                        else ((raw_entry - raw_exit_price) * qty),
                        2,
                    )
                    cost_info = bt_cfg.cost_model.compute_trade_costs(
                        raw_entry_price=raw_entry,
                        raw_exit_price=raw_exit_price,
                        quantity=qty,
                        position_side=pos_side,
                        segment=seg,
                        instrument_type=bt_cfg.instrument_type,
                        exchange=exchange,
                    )
                    charges_inr = float(cost_info["charges_inr"])
                    slippage_inr = float(cost_info["slippage_inr"])
                    total_costs_inr = float(cost_info["total_costs_inr"])
                    net_pnl = round(gross_pnl - total_costs_inr, 2)

                    risk_amt = max(0.01, float(open_position["risk_amount_inr"]))
                    r_mult = round(net_pnl / risk_amt, 4)
                    holding_bars = (idx - int(open_position["entry_bar_idx"])) + 1
                    entry_dt = parse_ist_timestamp(open_position["entry_timestamp"])
                    holding_minutes = round(
                        max(float(interval_min), (bar_end_dt - entry_dt).total_seconds() / 60.0),
                        2,
                    )

                    sig_obj: TradeSignal = open_position["signal"]
                    trade_record = {
                        "trade_index": len(trades) + 1,
                        "strategy_id": strategy_id,
                        "strategy_name": sig_obj.strategy_name,
                        "strategy_version": STRATEGY_BACKTEST_ELIGIBILITY[strategy_id]["strategy_version"],
                        "symbol": sym,
                        "segment": seg,
                        "exchange": exchange,
                        "direction": open_position["direction"],
                        "position_side": pos_side,
                        "signal_timestamp": open_position["signal_timestamp"],
                        "entry_timestamp": open_position["entry_timestamp"],
                        "exit_timestamp": bar["timestamp"],
                        "session_date": sess_date,
                        "raw_entry_price": round(raw_entry, 4),
                        "entry_price": float(cost_info["effective_entry_price"]),
                        "raw_exit_price": round(float(raw_exit_price), 4),
                        "exit_price": float(cost_info["effective_exit_price"]),
                        "quantity": qty,
                        "stop_loss": sl_price,
                        "target_price": tp_price,
                        "target_1": float(open_position["target_1"]),
                        "target_2": float(open_position["target_2"]),
                        "exit_reason": exit_reason,
                        "same_candle_collision": same_candle_collision,
                        "holding_bars": holding_bars,
                        "holding_minutes": holding_minutes,
                        "missing_bars_during_trade": int(open_position["missing_bars_during_trade"]),
                        "gross_pnl_inr": gross_pnl,
                        "charges_inr": charges_inr,
                        "slippage_inr": slippage_inr,
                        "total_costs_inr": total_costs_inr,
                        "net_pnl_inr": net_pnl,
                        "risk_amount_inr": round(risk_amt, 2),
                        "realized_r_multiple": r_mult,
                        "dataset_id": manifest["dataset_id"],
                        "dataset_checksum": manifest["sha256_checksum"],
                        "data_mode": dm,
                        "is_simulated": dm == "SIMULATED",
                        "provider": provider,
                        "cost_breakdown": cost_info,
                        "signal_metadata": {
                            "instrument_identity": historical_identity,
                            "provider": sig_obj.provider,
                            "data_mode": sig_obj.data_mode,
                            "state_context": sig_obj.state_context,
                            "interval_min": sig_obj.interval_min,
                            "quality_score": sig_obj.quality_score,
                            "score_breakdown": sig_obj.score_breakdown,
                            "invalidation_level": sig_obj.invalidation_level,
                            "entry_zone_low": sig_obj.entry_zone_low,
                            "entry_zone_high": sig_obj.entry_zone_high,
                            "rationale": sig_obj.rationale,
                            "sizing": open_position["sizing"],
                        },
                    }
                    trades.append(trade_record)
                    current_capital_inr = round(current_capital_inr + net_pnl, 2)
                    open_position = None

                    day_state["realized_net_pnl_inr"] = round(
                        float(day_state["realized_net_pnl_inr"]) + net_pnl, 2
                    )
                    if (
                        bt_cfg.max_daily_loss_inr is not None
                        and day_state["realized_net_pnl_inr"] <= -abs(float(bt_cfg.max_daily_loss_inr))
                    ):
                        day_state["daily_loss_limit_triggered"] = True
                    if (
                        bt_cfg.daily_profit_target_inr is not None
                        and day_state["realized_net_pnl_inr"] >= abs(float(bt_cfg.daily_profit_target_inr))
                    ):
                        day_state["daily_profit_target_triggered"] = True

            # ----------------------------------------------------------------
            # STEP C: Point-in-Time Signal Evaluation at Current Bar Close
            # ----------------------------------------------------------------
            # Slice strictly up to idx + 1 and verify zero look-ahead leakage at bar_end_dt
            pit_slice = get_point_in_time_candle_slice(
                validated_bars[: idx + 1],
                decision_time_ist=bar_end_dt,
                interval_min=interval_min,
                expected_data_mode=dm,
            )
            verify_no_lookahead_leakage(pit_slice, decision_time_ist=bar_end_dt, interval_min=interval_min)

            if not in_eval_window:
                continue

            # If a position is already open, do not queue overlapping signals on the same symbol
            if open_position is not None:
                continue

            pit_breadth: Optional[Dict[str, Any]] = None
            if universe_candles_by_symbol:
                pit_breadth = compute_point_in_time_universe_breadth(
                    universe_candles_by_symbol,
                    decision_time_ist=bar_end_dt,
                    interval_min=interval_min,
                    expected_data_mode=dm,
                )

            pit_option_chain = (
                (historical_option_chains_by_timestamp or {}).get(bar["timestamp"])
                if historical_option_chains_by_timestamp
                else None
            )

            sig = self._invoke_strategy_evaluator(
                strategy_id=strategy_id,
                symbol=sym,
                segment=seg,
                pit_candles=pit_slice,
                decision_dt=bar_end_dt,
                capital_inr=current_capital_inr,
                risk_pct=bt_cfg.risk_per_trade_pct,
                mitigated_zones=mitigated_zones,
                market_breadth=pit_breadth,
                option_chain=pit_option_chain,
                lot_size=bt_cfg.historical_lot_size,
                execution_costs=estimate_execution_costs,
            )

            if sig is not None:
                # Replay provenance is explicit even if an evaluator returns default metadata.
                sig.provider = provider
                sig.data_mode = dm
                sig.is_simulated = dm == "SIMULATED"
                sig.state_context = gate["execution_scope"]
                sig.interval_min = interval_min
                if sig.symbol != sym or sig.segment != seg:
                    raise BacktestValidationError("Evaluator signal identity conflicts with the replay instrument.")
                if dm == "LIVE":
                    sig.instrument_identity = dict(historical_identity)
                if idx == len(validated_bars) - 1:
                    rejected_signals.append({
                        "signal_timestamp": sig.timestamp,
                        "symbol": sym,
                        "strategy_id": strategy_id,
                        "direction": sig.direction,
                        "reason": "END_OF_DATASET_NO_NEXT_CANDLE",
                    })
                else:
                    pending_signal = (idx, sig)

        metrics = compute_backtest_metrics(
            trades=trades,
            starting_capital_inr=bt_cfg.starting_capital_inr,
            session_dates_evaluated=eval_sessions,
            total_bars_evaluated=total_eval_bars,
            missing_bars_count=int(manifest["missing_bars_count"]),
            open_position_missing_bars_count=open_position_missing_bars_count,
            rejected_signals=rejected_signals,
            daily_status_by_session=daily_status,
        )

        assumptions = {
            "engine_version": BACKTEST_ENGINE_VERSION,
            "execution_scope": gate["execution_scope"],
            "sizing_policy": "ALL_IN_PLANNED_STOP_RISK_FULL_NOTIONAL_V1",
            "estimated_risk_is_guaranteed_loss": False,
            "strategy_id": strategy_id,
            "strategy_version": STRATEGY_BACKTEST_ELIGIBILITY[strategy_id]["strategy_version"],
            "execution_convention": bt_cfg.execution_convention,
            "target_mode": bt_cfg.target_mode,
            "same_candle_collision_rule": bt_cfg.same_candle_collision_rule,
            "last_entry_cutoff_ist": bt_cfg.last_entry_Cutoff_ist,
            "eod_square_off_ist": bt_cfg.eod_square_off_ist,
            "allow_overnight_carry": bt_cfg.allow_overnight_carry,
            "starting_capital_inr": float(bt_cfg.starting_capital_inr),
            "risk_per_trade_pct": float(bt_cfg.risk_per_trade_pct),
            "max_daily_loss_inr": bt_cfg.max_daily_loss_inr,
            "daily_profit_target_inr": bt_cfg.daily_profit_target_inr,
            "max_concurrent_positions": bt_cfg.max_concurrent_positions,
            "enforce_capital_exposure_limit": bt_cfg.enforce_capital_exposure_limit,
            "instrument_type": bt_cfg.instrument_type,
            "historical_lot_size": bt_cfg.historical_lot_size,
            "instrument_identity": historical_identity,
            "period_type": bt_cfg.period_type,
            "evaluation_start_date": bt_cfg.evaluation_start_date or (eval_sessions[0] if eval_sessions else None),
            "evaluation_end_date": bt_cfg.evaluation_end_date or (eval_sessions[-1] if eval_sessions else None),
            "cost_model": bt_cfg.cost_model.to_dict(),
        }

        run_hash_input = json.dumps(
            {
                "dataset_id": manifest["dataset_id"],
                "dataset_checksum": manifest["sha256_checksum"],
                "strategy_id": strategy_id,
                "assumptions": assumptions,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        run_hash = hashlib.sha256(run_hash_input.encode("utf-8")).hexdigest()[:12]
        run_id = f"bt_{strategy_id}_{sym}_{dm}_{bt_cfg.period_type}_{run_hash}"

        data_acceptance_status = gate["reason_code"]
        run_label = (
            "SIMULATED/TEST MODE (SYNTHETIC OR PAPER FIXTURE — NOT LIVE ACCEPTANCE)"
            if dm == "SIMULATED"
            else gate["execution_scope"] + " (BROKER-SOURCED HISTORICAL RECORDS)"
        )

        result_payload = {
            "run_id": run_id,
            "engine_version": BACKTEST_ENGINE_VERSION,
            "implementation_status": "IMPLEMENTED_VERIFIED",
            "data_acceptance_status": data_acceptance_status,
            "execution_scope": gate["execution_scope"],
            "acceptance_gate": gate,
            "run_label": run_label,
            "strategy_id": strategy_id,
            "strategy_name": STRATEGY_BACKTEST_ELIGIBILITY[strategy_id]["strategy_name"],
            "strategy_version": STRATEGY_BACKTEST_ELIGIBILITY[strategy_id]["strategy_version"],
            "symbol": sym,
            "segment": seg,
            "exchange": exchange,
            "interval_min": interval_min,
            "dataset_id": manifest["dataset_id"],
            "dataset_checksum": manifest["sha256_checksum"],
            "dataset_quality_status": manifest["quality_status"],
            "provider": provider,
            "data_mode": dm,
            "is_simulated": dm == "SIMULATED",
            "period_type": bt_cfg.period_type,
            "from_timestamp_ist": manifest["from_timestamp_ist"],
            "to_timestamp_ist": manifest["to_timestamp_ist"],
            "starting_capital_inr": round(float(bt_cfg.starting_capital_inr), 2),
            "ending_capital_inr": round(current_capital_inr, 2),
            "risk_per_trade_pct": float(bt_cfg.risk_per_trade_pct),
            "max_daily_loss_inr": bt_cfg.max_daily_loss_inr,
            "daily_profit_target_inr": bt_cfg.daily_profit_target_inr,
            "assumptions": assumptions,
            "metrics": metrics,
            "trades": trades,
            "rejected_signals": rejected_signals,
            "created_at_ist": format_ist_timestamp(datetime.now(IST)),
        }

        if persist_run and self.store is not None:
            self.store.save_backtest_run(result_payload, trades)

        return result_payload


# ============================================================================
# 8. CLI ENTRY POINT (`python .\backtest_engine.py ...`)
# ============================================================================
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="TradePulse Phase 3B — Deterministic Historical Backtesting Engine CLI"
    )
    parser.add_argument(
        "--eligibility",
        action="store_true",
        help="Print the 5-strategy backtest eligibility matrix and Phase 2C/3A readiness status.",
    )
    parser.add_argument(
        "--strategy",
        default="strat_1_order_block",
        choices=sorted(STRATEGY_BACKTEST_ELIGIBILITY.keys()),
        help="Strategy identifier to evaluate (default: strat_1_order_block).",
    )
    parser.add_argument(
        "--symbol",
        default="RELIANCE",
        help="Instrument symbol to backtest (default: RELIANCE).",
    )
    parser.add_argument(
        "--data-mode",
        default="SIMULATED",
        choices=["LIVE", "SIMULATED"],
        help="Dataset mode: SIMULATED (for deterministic synthetic validation) or LIVE (requires Phase 2C/3A acceptance).",
    )
    parser.add_argument(
        "--synthetic-fixture",
        choices=[
            "order_block_bull",
            "order_block_bear",
            "vwap_pullback_bull",
            "vwap_pullback_bear",
            "orb_breakout_bull",
            "orb_breakout_bear",
            "supertrend_pullback_bull",
            "supertrend_pullback_bear",
        ],
        help="Run a deterministic SIMULATED backtest using a named synthetic fixture pattern.",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000.0,
        help="Starting capital in INR (default: 100000.0).",
    )
    parser.add_argument(
        "--risk-pct",
        type=float,
        default=1.0,
        help="Risk per trade as %% of capital (default: 1.0).",
    )
    parser.add_argument(
        "--max-daily-loss",
        type=float,
        default=2000.0,
        help="Maximum daily realized loss limit in INR (default: 2000.0).",
    )
    parser.add_argument(
        "--daily-profit-target",
        type=float,
        default=4000.0,
        help="Daily realized profit target in INR (default: 4000.0).",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=5.0,
        help="Execution slippage in basis points per leg (default: 5.0).",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist the backtest run and trade ledger into SQLite.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit output as formatted JSON.",
    )
    parser.add_argument("--execution-scope", choices=["LIVE_ACCEPTED", "HISTORICAL_RESEARCH", "SIMULATED_TEST"],
                        help="Default: LIVE_ACCEPTED for LIVE, SIMULATED_TEST for SIMULATED.")
    parser.add_argument("--provider", choices=["angelone", "dhan", "upstox"],
                        help="Historical provider (defaults to configured live provider, otherwise angelone).")
    parser.add_argument("--historical-instrument-master", help="Local JSON archive under --instrument-import-root; original bytes are preserved.")
    parser.add_argument("--instrument-import-root", default=".", help="Allowed local archive input directory.")
    parser.add_argument("--instrument-archive-id", help="Immutable archive ID previously ingested in this SQLite database.")
    args = parser.parse_args(argv)

    cfg = BotConfig(database_url=os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db"))
    store = SQLitePersistenceStore(cfg.database_url or "sqlite:///tradepulse_phase1d.db")
    atexit.register(store.close)

    if args.eligibility:
        readiness = evaluate_phase3a_backtest_readiness(
            config=cfg,
            store=store,
            target_data_mode=args.data_mode,
            provider=args.provider,
            symbol=args.symbol.upper(), strategy_id=args.strategy, execution_scope=args.execution_scope,
        )
        payload = {
            "engine_version": BACKTEST_ENGINE_VERSION,
            "implementation_status": "IMPLEMENTED_VERIFIED",
            "data_acceptance_status": readiness["execution_gate"]["reason_code"],
            "readiness": readiness,
            "strategy_eligibility_matrix": STRATEGY_BACKTEST_ELIGIBILITY,
        }
        if args.json:
            safe_console_print(json.dumps(payload, indent=2))
        else:
            safe_console_print("=" * 88)
            safe_console_print("TRADEPULSE AI — PHASE 3B BACKTEST ENGINE & STRATEGY ELIGIBILITY MATRIX")
            safe_console_print("=" * 88)
            safe_console_print(f"Engine Version         : {BACKTEST_ENGINE_VERSION}")
            safe_console_print(f"Implementation Status  : {payload['implementation_status']}")
            safe_console_print(f"Data Acceptance Status : {payload['data_acceptance_status']}")
            safe_console_print("-" * 88)
            for sid, spec in STRATEGY_BACKTEST_ELIGIBILITY.items():
                safe_console_print(f"[{spec['backtest_eligibility']:<38}] {spec['strategy_name']} ({sid})")
                safe_console_print(f"    Restriction: {spec['restriction_reason']}")
            safe_console_print("=" * 88)
        return 0

    candles_input: Optional[List[Dict[str, Any]]] = None
    provider_name = args.provider

    if args.synthetic_fixture:
        if args.data_mode != "SIMULATED":
            safe_console_print("[FAIL] --synthetic-fixture can only be used with --data-mode SIMULATED.")
            return 2
        from brokers import SimulatedNSEAdapter
        sim = SimulatedNSEAdapter(
            seed=42,
            clock=lambda: datetime(2026, 10, 16, 15, 30, tzinfo=IST),
        )
        raw_sim = sim.get_intraday_candles(
            {"symbol": args.symbol},
            interval_min=5,
            pattern=args.synthetic_fixture,
        )
        # Append contiguous 10:35:00 bar on 2026-10-16 so a signal at 10:30:00 close fills at 10:35:00 open
        last_c = raw_sim[-1]
        if str(last_c["timestamp"]).endswith("10:30:00"):
            is_bear_fix = "bear" in args.synthetic_fixture
            raw_sim.append({
                "timestamp": "2026-10-16 10:35:00",
                "open": last_c["close"],
                "high": round(last_c["close"] * (1.002 if is_bear_fix else 1.025), 2),
                "low": round(last_c["close"] * (0.975 if is_bear_fix else 0.998), 2),
                "close": round(last_c["close"] * (0.980 if is_bear_fix else 1.020), 2),
                "volume": int(last_c["volume"] * 1.2),
                "is_complete": True,
                "is_simulated": True,
                "data_mode": "SIMULATED",
            })
        candles_input = raw_sim
        provider_name = "paper_sim_fixture"

    archive_id = args.instrument_archive_id
    if args.historical_instrument_master:
        try:
            if archive_id:
                raise IdentityValidationError("AMBIGUOUS_ARCHIVE_INPUT", "Supply a file or archive ID, not both.")
            from readiness_policy import resolve_provider
            archive_provider = resolve_provider(cfg, args.data_mode, provider_name)
            candidate = store.ingest_instrument_master_file(args.historical_instrument_master,
                archive_provider, "CLI_USER_SUPPLIED_ARCHIVE", import_root=args.instrument_import_root)
            if candidate["status"] != "ELIGIBLE_LOCAL_RESEARCH":
                raise IdentityValidationError("HISTORICAL_IDENTITY_UNVERIFIED", "Archive is retained but cannot authorize LIVE history.")
            archive_id = candidate["archive_id"]
        except (OSError, ValueError) as exc:
            failure = {"status": "error", "error_type": "BacktestValidationError",
                       "message": "Historical instrument-master evidence could not authorize replay.",
                       "rejection": getattr(exc, "rejection", {"reason_code": "ARCHIVE_FILE_ERROR"})}
            safe_console_print(json.dumps(failure) if args.json else failure["message"])
            store.close()
            return 1
    bt_cfg = BacktestConfig(
        historical_instrument_archive_id=archive_id,
        starting_capital_inr=args.capital,
        risk_per_trade_pct=args.risk_pct,
        max_daily_loss_inr=args.max_daily_loss,
        daily_profit_target_inr=args.daily_profit_target,
        execution_scope=args.execution_scope,
        cost_model=IndianCostModel(slippage_bps_per_leg=args.slippage_bps),
    )

    engine = DeterministicBacktestEngine(bot_config=cfg, store=store)
    try:
        res = engine.run_backtest(
            strategy_id=args.strategy,
            symbol=args.symbol,
            candles=candles_input,
            provider=provider_name,
            data_mode=args.data_mode,
            backtest_config=bt_cfg,
            persist_run=args.persist,
        )
        if args.json:
            safe_console_print(json.dumps(res, indent=2))
        else:
            m = res["metrics"]
            safe_console_print("=" * 88)
            safe_console_print(f"TRADEPULSE AI — PHASE 3B BACKTEST REPORT ({res['run_id']})")
            safe_console_print("=" * 88)
            safe_console_print(f"Run Label              : {res['run_label']}")
            safe_console_print(f"Implementation Status  : {res['implementation_status']}")
            safe_console_print(f"Data Acceptance Status : {res['data_acceptance_status']}")
            safe_console_print(f"Strategy & Symbol      : {res['strategy_name']} ({res['strategy_id']}) on {res['symbol']} [{res['data_mode']}]")
            safe_console_print(f"Dataset ID & Checksum  : {res['dataset_id']} ({res['dataset_checksum'][:16]}...)")
            safe_console_print(f"Trades (Win/Loss/Flat) : {m['total_trades']} ({m['winning_trades']}W / {m['losing_trades']}L / {m['breakeven_trades']}F) | Win Rate: {m['win_rate_pct']}%")
            safe_console_print(f"Gross / Costs / Net    : Gross={m['gross_pnl_inr']} INR | Costs={m['total_costs_inr']} INR | Net={m['net_pnl_inr']} INR")
            safe_console_print(f"Profit Factor & Max DD : PF={m['profit_factor_display']} | Max Drawdown={m['max_drawdown_inr']} INR ({m['max_drawdown_pct']}%)")
            safe_console_print("=" * 88)
        return 0
    except BacktestError as exc:
        if args.json and isinstance(exc, (BacktestEligibilityError, BacktestReadinessError)) and exc.details:
            safe_console_print(json.dumps({
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "rejection": exc.details,
            }, indent=2))
        else:
            safe_console_print(f"[BLOCKED] {type(exc).__name__}: {exc}")
        return 2
    except Exception as exc:
        safe_console_print(f"[ERROR] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
