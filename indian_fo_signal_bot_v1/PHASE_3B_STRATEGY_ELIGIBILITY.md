# TradePulse AI — Phase 3B Strategy Backtest Eligibility Matrix (`PHASE_3B_STRATEGY_ELIGIBILITY.md`)

**Date:** 2026-10-17  
**Engine Version:** `phase_3b_v1.0.0`  
**Source of Truth Inspected:** `strategies.py`, `historical_data.py`, `backtest_engine.py`  
**Implementation Status:** `IMPLEMENTED_VERIFIED`  
**Data Acceptance Status:** `BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED`

## 1. Executive Summary of Strategy Eligibility

Before implementing `backtest_engine.py`, `strategies.py` was audited line-by-line to verify the exact strategy identifiers, names, mathematical indicator dependencies, session time windows, entry/exit/stop-loss/target formulas, and volume/open-interest/option-chain requirements. Zero strategy rules were weakened, altered, or fabricated.

| Strategy ID | Strategy Name | Target Universe | Timeframe & Warm-Up | Required Candle & Volume/OI Inputs | Backtest Eligibility Status | Restriction / Blocking Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`strat_1_order_block`** | Order Block + BOS & FVG Retest | 15 NSE Equities (`NSE_EQUITY_INTRADAY`) | `5m` (`>= 30` completed bars; `09:15–15:25 IST`) | `open`, `high`, `low`, `close`, `volume > 0`, Wilder `ATR(10)`, Session `VWAP`, 15-bar lookback (`completed[-15:]`), `mitigated_zones` registry | **`ELIGIBLE_EQUITY_5M`** | Eligible on NSE cash equities (`instrument_type="EQ"`, `volume > 0`). Blocked on `NIFTY`/`BANKNIFTY` index spot (`INDEX_SPOT`) because an index spot level is not an executable contract and reports `volume = 0`. |
| **`strat_2_vwap_pullback`** | Institutional VWAP Pullback + Volume | 15 NSE Equities (`NSE_EQUITY_INTRADAY`) | `5m` (`>= 35` completed bars; `09:15–15:25 IST`) | `open`, `high`, `low`, `close`, **`volume > 0`** (`avg_vol_20 > 0` and `last["volume"] >= 1.4 * avg_vol_20`), Session `VWAP`, `EMA(20)`, Wilder `RSI(14)`, Wilder `ATR(10)` | **`ELIGIBLE_EQUITY_5M`** | Eligible on NSE cash equities (`>= 35` bars, `positive_volume_ratio > 0`). Blocked on zero-volume index spot series (`evaluate_vwap_pullback` returns `None` when `avg_vol_20 <= 0`). |
| **`strat_3_option_apex_oi`** | Option Apex OI Shift Trap + PCR | Strictly `NIFTY` & `BANKNIFTY` (`NSE_FO_INDEX`) | `5m` (`>= 15` completed bars; `09:15–15:25 IST`) | Underlying 5m bars + **point-in-time historical option chain** (`atm_strike`, `pcr`, strike-wise `ce_ltp`, `pe_ltp`, `ce_oi`, `pe_oi`, `ce_oi_change`, `pe_oi_change`) + **validated prior-session `CLOSING_BASELINE`** + **historical option contract OHLCV bars & historical lot size** | **`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`** | **Strictly Blocked.** Broker REST candle APIs do not provide historical 5m multi-strike option chains; expired option tokens are purged from `OpenAPIScripMaster.json`; current option chains are never substituted for historical data. |
| **`strat_4_orb_filtered`** | 15m Opening Range Breakout (ORB) + RVOL | 15 NSE Equities (`NSE_EQUITY_INTRADAY`) | `5m` (`>= 30` total bars + `>= 4` session bars; `09:30–15:25 IST`) | Complete 3-bar `09:15, 09:20, 09:25 IST` Opening Range (`orb_high`, `orb_low`), **`volume > 0`** (`RVOL >= 1.6x`), Session `VWAP`, Wilder `RSI(14)` | **`ELIGIBLE_EQUITY_5M`** | Eligible on NSE cash equities when at least one session contains all 3 ORB bars (`09:15, 09:20, 09:25 IST`) and positive volume. Blocked if ORB bars are missing or volume is zero. |
| **`strat_5_supertrend_pullback`** | Supertrend (10,3) Pullback + 200 EMA | 15 NSE Equities (`NSE_EQUITY_INTRADAY`) | `5m` (**`>= 200` completed bars**; active `09:45–11:25` & `13:35–15:25 IST`) | `>= 200` completed 5m OHLCV bars with **`volume > 0`** (`RVOL >= 1.3x`), `EMA(200)`, `Supertrend(10, 3.0)`, Session `VWAP`, Wilder `ATR(10)` | **`ELIGIBLE_EQUITY_5M_WITH_200_BAR_WARMUP`** | Eligible on NSE cash equities when dataset provides `>= 200` completed 5m bars (`>= 3` prior 75-bar sessions) with positive volume. Blocked (`BLOCKED_INSUFFICIENT_WARMUP_BARS`) when `< 200` bars exist. |

## 2. Detailed Strategy Specifications Inspected in `strategies.py`

### 2.1 Strategy 1 — `strat_1_order_block` (`evaluate_order_block_fvg`)
- **Required Instruments & Timeframe:** 5-minute completed candles (`interval_min = 5`), minimum `30` completed bars, evaluated within `09:15–15:30 IST` (`09:15:00` to `15:25:00` bar start times).
- **Required Indicators & State:** Wilder `ATR(10)`, Session `VWAP` (`compute_session_vwap`), 15-bar lookback window (`recent = completed[-15:]`), and stateful/stateless `mitigated_zones` tracking (`{SYMBOL}:OB:{BULL|BEAR}:{OB_TIMESTAMP}`).
- **Bullish Entry & Exit Rules (`BULLISH (BUY)`):**
  - Bearish `ob_bar` (`close < open`) followed by 2-bar impulse (`imp_1`, `imp_2`) breaking above `zone_high = ob_bar["high"]` (BOS) with either 3-bar FVG (`imp_2["low"] > zone_high`) or displacement `(imp_2["close"] - ob_bar["open"]) >= 1.5 * ATR(10)`.
  - Zone is unmitigated by intermediate bars (`prior_post_impulse`) and not invalidated (`close < zone_low`).
  - Current bar dips into `last["low"] <= zone_high * 1.0015` and closes higher (`last["close"] > ob_bar["open"]` and `last["close"] >= zone_low`).
  - Levels: `entry = round(last["close"], 2)`, `invalidation = round(zone_low, 2)`, `stop_loss = round(zone_low - 0.25 * ATR(10), 2)`, `risk = max(0.5, entry - stop_loss)`, `target_1 = round(entry + 2.0 * risk, 2)`, `target_2 = round(entry + 3.0 * risk, 2)`.
- **Bearish Entry & Exit Rules (`BEARISH (SELL)`):**
  - Bullish `ob_bar` (`close > open`) followed by 2-bar impulse breaking below `zone_low = ob_bar["low"]` with bearish FVG (`imp_2["high"] < zone_low`) or displacement `>= 1.5 * ATR(10)`.
  - Current bar rallies into `last["high"] >= zone_low * 0.9985` and rejects lower (`last["close"] < ob_bar["open"]` and `last["close"] <= zone_high`).
  - Levels: `entry = round(last["close"], 2)`, `invalidation = round(zone_high, 2)`, `stop_loss = round(zone_high + 0.25 * ATR(10), 2)`, `risk = max(0.5, stop_loss - entry)`, `target_1 = round(entry - 2.0 * risk, 2)`, `target_2 = round(entry - 3.0 * risk, 2)`.

### 2.2 Strategy 2 — `strat_2_vwap_pullback` (`evaluate_vwap_pullback`)
- **Required Instruments & Timeframe:** 5-minute completed candles, minimum `35` completed bars, positive 20-bar prior average volume (`avg_vol_20 > 0`).
- **Required Indicators:** Session `VWAP`, `EMA(20)`, Wilder `RSI(14)`, Wilder `ATR(10)`.
- **Bullish Rules (`BULLISH (BUY)`):** `last["low"] <= curr_vwap * 1.0025`, `last["close"] > curr_vwap`, `last["close"] > last["open"]`, `last["close"] >= curr_ema20 * 0.998`, `last["volume"] >= 1.4 * avg_vol_20`, `48.0 <= RSI(14) <= 72.0`. Stop-loss: `round(min(last["low"], curr_vwap) - 0.35 * ATR(10), 2)`; `target_1 = entry + 1.8 * risk`; `target_2 = entry + 2.5 * risk`.
- **Bearish Rules (`BEARISH (SELL)`):** `last["high"] >= curr_vwap * 0.9975`, `last["close"] < curr_vwap`, `last["close"] < last["open"]`, `last["close"] <= curr_ema20 * 1.002`, `last["volume"] >= 1.4 * avg_vol_20`, `28.0 <= RSI(14) <= 52.0`. Stop-loss: `round(max(last["high"], curr_vwap) + 0.35 * ATR(10), 2)`; `target_1 = entry - 1.8 * risk`; `target_2 = entry - 2.5 * risk`.

### 2.3 Strategy 3 — `strat_3_option_apex_oi` (`evaluate_option_apex_oi_shift`) — **BLOCKED**
- **Required Instruments & Inputs:** Strictly `NIFTY` and `BANKNIFTY` (`NSE_FO_INDEX`). Requires:
  1. Underlying 5-minute completed candles (`>= 15` bars) and Session `VWAP`.
  2. Point-in-time historical option-chain snapshot at the exact decision timestamp (`atm_strike`, `pcr`, and ATM strike `ce_ltp`, `pe_ltp`, `ce_oi`, `pe_oi`, `ce_oi_change`, `pe_oi_change`).
  3. Validated prior-session closing OI baseline (`CLOSING_BASELINE` from `>= 15:25 IST` on the prior trading day) so `ce_oi_change = ce_oi - ce_prev_oi` and `pe_oi_change = pe_oi - pe_prev_oi` are genuine.
  4. Historical option contract OHLCV bars (`CE`/`PE` strike premium candles) and validated historical lot size (`lot_size`) to simulate option premium entry, `0.78x` stop-loss, and `1.6R`/`2.4R` target fills without fabricating option prices from underlying index movements.
- **Why Strategy 3 Remains Blocked:** Angel One SmartAPI, DhanHQ, and Upstox REST APIs do not provide historical 5-minute option-chain snapshots or expired option contract tokens. `evaluate_strategy_backtest_eligibility()` and `DeterministicBacktestEngine.run_backtest()` enforce `BacktestEligibilityError` (`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`) whenever any of those 4 inputs is absent.

### 2.4 Strategy 4 — `strat_4_orb_filtered` (`evaluate_orb_breakout`)
- **Required Instruments & Timeframe:** 5-minute completed candles (`>= 30` total bars, `>= 4` current-session bars), complete 3-bar Opening Range (`09:15:00`, `09:20:00`, `09:25:00 IST`), positive volume (`avg_vol_20 > 0`).
- **Bullish Rules (`BULLISH (BUY)`):** `prev["close"] <= orb_high`, `last["close"] > orb_high`, `last["close"] > curr_vwap`, `RSI(14) >= 55.0`, `RVOL >= 1.6`. Stop-loss: `round(max(orb_low, last["low"] - (orb_high - orb_low) * 0.25), 2)`; `target_1 = entry + 1.6 * risk`; `target_2 = entry + 2.4 * risk`.
- **Bearish Rules (`BEARISH (SELL)`):** `prev["close"] >= orb_low`, `last["close"] < orb_low`, `last["close"] < curr_vwap`, `RSI(14) <= 45.0`, `RVOL >= 1.6`. Stop-loss: `round(min(orb_high, last["high"] + (orb_high - orb_low) * 0.25), 2)`; `target_1 = entry - 1.6 * risk`; `target_2 = entry - 2.4 * risk`.

### 2.5 Strategy 5 — `strat_5_supertrend_pullback` (`evaluate_supertrend_pullback`)
- **Required Instruments & Timeframe:** 5-minute completed candles, minimum **`200` completed bars** (`>= 3` prior 75-bar NSE sessions), positive volume (`avg_vol_20 > 0`). Blocks opening (`09:15 <= hhmm < 09:45`) and midday chop (`11:30 <= hhmm <= 13:30`) windows.
- **Bullish Rules (`BULLISH (BUY)`):** `st_dir[-1] == 1 and st_dir[-2] == 1`, `last["close"] > curr_ema200`, `completed[-2]["close"] > ema200[-2]`, `last["close"] > curr_vwap`, pullback touch (`last["low"] <= curr_st * 1.004 or last["low"] <= curr_vwap * 1.003`), `last["close"] > last["open"]`, `RVOL >= 1.3`. Stop-loss: `round(min(curr_st, last["low"]) - 0.25 * ATR(10), 2)`; `target_1 = entry + 1.5 * risk`; `target_2 = entry + 2.5 * risk`.
- **Bearish Rules (`BEARISH (SELL)`):** `st_dir[-1] == -1 and st_dir[-2] == -1`, `last["close"] < curr_ema200`, `completed[-2]["close"] < ema200[-2]`, `last["close"] < curr_vwap`, pullback touch (`last["high"] >= curr_st * 0.996 or last["high"] >= curr_vwap * 0.997`), `last["close"] < last["open"]`, `RVOL >= 1.3`. Stop-loss: `round(max(curr_st, last["high"]) + 0.25 * ATR(10), 2)`; `target_1 = entry - 1.5 * risk`; `target_2 = entry - 2.5 * risk`.

## 3. Non-Executable Index Spot vs Derivatives Distinction

In Indian markets, `NIFTY` (`99926000`) and `BANKNIFTY` (`99926009`) spot indices are mathematical benchmarks, **not directly tradable instruments**, and their spot candle feeds report `volume = 0`. Accordingly:
1. `evaluate_strategy_backtest_eligibility()` blocks any backtest on `instrument_type="INDEX_SPOT"` (`BLOCKED_INDEX_SPOT_NOT_EXECUTABLE`).
2. Any dataset with `positive_volume_ratio <= 0.0` is blocked (`BLOCKED_ZERO_VOLUME_SERIES`) for volume-dependent strategies (`strat_1`, `strat_2`, `strat_4`, `strat_5`).
3. Derivative backtests (`FUTIDX`, `FUTSTK`, `OPTIDX`) require explicit historical contract metadata (`historical_lot_size > 0`); the engine never retroactively applies current lot sizes to historical periods.
