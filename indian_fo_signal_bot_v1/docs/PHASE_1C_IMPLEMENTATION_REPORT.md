# TradePulse AI — Phase 1C Implementation Report (`PHASE_1C_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-16  
**Scope:** Phase 1C — Bidirectional Strategy Evaluation, Order Block Mitigation Tracking & Reproducible Setup-Quality Scoring  
**Baseline Artifact:** `indian_fo_signal_bot_phase1b.zip` (31/31 tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase1c.zip` (39/39 tests passing)


## 1. Baseline Inspection & Phase 1B Verification

### 1.1 Extracted Baseline File Inventory (`indian_fo_signal_bot_phase1b.zip`)
Extracting `indian_fo_signal_bot_phase1b.zip` into an untouched baseline directory (`/tmp/phase1c_baseline/indian_fo_signal_bot_v1`) confirmed all 12 baseline files:

```text
indian_fo_signal_bot_v1/
├── .env.example
├── AI_STUDIO_PROMPT.md
├── README.md
├── brokers.py
├── config.py
├── docs/
│   ├── PHASE_1A_IMPLEMENTATION_REPORT.md
│   └── PHASE_1B_IMPLEMENTATION_REPORT.md
├── scanner_engine.py
├── server.py
├── strategies.py
├── telegram_bot.py
└── test_bot.py
```

### 1.2 Baseline Test Execution Before Edits
Running `python3 /tmp/phase1c_baseline/indian_fo_signal_bot_v1/test_bot.py -v` against the unmodified Phase 1B baseline executed **31 tests** (`20` Phase 1A tests + `11` Phase 1B tests) with **31 passed, 0 failed, 0 skipped** (`Ran 31 tests in 4.753s — OK`).

### 1.3 Baseline Strategy & Signal Contract Inspection
Inspection of `strategies.py` (L12–L847) in the Phase 1B baseline confirmed:
1. **Unidirectional (Bullish-Only) Evaluators:** All five strategy evaluators (`evaluate_order_block_fvg`, `evaluate_vwap_pullback`, `evaluate_option_apex_oi_shift`, `evaluate_orb_breakout`, and `evaluate_supertrend_pullback`) evaluated only bullish conditions (`"BULLISH (BUY)"` or `"BULLISH (BUY CE)"`).
2. **Lack of Order Block First-Retest Mitigation Tracking:** `evaluate_order_block_fvg()` checked `invalidated = any(b["close"] < zone_low for b in subsequent)` (`L511`), but did not check whether any intermediate candle in `subsequent[:-1]` had already touched/mitigated the Order Block zone (`zone_high * 1.0015`). As a result, a zone mitigated on an earlier bar in the 15-bar lookback window could fire repeated duplicate signals on subsequent dips into the same zone.
3. **Static `confidence_pct` Constants:** Every evaluator returned a hardcoded integer literal for `confidence_pct` (`89`, `87`, `91`, `84`, `82`) regardless of actual relative volume, distance from session VWAP, ATR displacement, or market breadth.
4. **Default Fallback on Option-Chain Fields in `evaluate_option_apex_oi_shift`:** Lines 647–649 of the baseline `strategies.py` used `option_chain.get("pcr", 1.0)` and `option_chain.get("atm_strike", 24800)` instead of explicitly validating required option-chain fields before strategy evaluation.


## 2. Changed Files Summary

| File Path | Summary of Changes |
| :--- | :--- |
| `strategies.py` | Extended `TradeSignal` backward-compatibly with `position_type`, `invalidation_level`, `quality_score`, and `score_breakdown`; added `compute_setup_quality_score()` and `validate_option_chain_for_strategy()`; implemented symmetric Bearish (`BEARISH (SELL)` / `BEARISH (BUY PE)`) logic across all 5 strategies; implemented stateless candle-history and stateful set-based Order Block first-retest mitigation tracking. |
| `brokers.py` | Added deterministic bearish fixture patterns (`order_block_bear`, `vwap_pullback_bear`, `orb_breakout_bear`, `supertrend_pullback_bear`) to `SimulatedNSEAdapter.get_intraday_candles()` while preserving all Phase 1A/1B adapter and validation logic. |
| `scanner_engine.py` | Added `self.mitigated_order_blocks: Set[str]` in `IntradayBotEngine` to track mitigated Order Block zones across scans within the same process, and added `_compute_universe_breadth()` to compute genuine advance/decline breadth from completed session candles across the scanned universe. |
| `test_bot.py` | Preserved all 31 Phase 1A and Phase 1B tests intact and added `TestIndianFOSignalBotPhase1C` (8 comprehensive test methods covering all Phase 1C requirements, bringing total test count to 39). |
| `README.md` | Updated documentation with Phase 1C capabilities and 39-test execution commands. |
| `docs/PHASE_1C_IMPLEMENTATION_REPORT.md` | Added complete Phase 1C implementation report inside `docs/` while preserving `PHASE_1A_IMPLEMENTATION_REPORT.md` and `PHASE_1B_IMPLEMENTATION_REPORT.md`. |


## 3. Task 1 — Bidirectional Strategy Definitions & Signal Contracts

### 3.1 Extended `TradeSignal` Contract (100% Backward-Compatible)
`TradeSignal` preserves all 22 existing fields in their exact order and appends 4 optional defaulted fields (`position_type`, `invalidation_level`, `quality_score`, `score_breakdown`). When constructed by legacy callers that omit the new fields, `__post_init__` automatically synchronizes `quality_score` with `confidence_pct`, sets `invalidation_level = stop_loss`, and derives the canonical `position_type`:

| Signal Direction | Segment | `position_type` | Directional Price Invariant |
| :--- | :--- | :--- | :--- |
| `"BULLISH (BUY)"` | `"NSE_EQUITY_INTRADAY"` | `"LONG_EQUITY_INTRADAY"` | `stop_loss < entry_price < target_1 < target_2` |
| `"BEARISH (SELL)"` | `"NSE_EQUITY_INTRADAY"` | `"SHORT_EQUITY_INTRADAY"` | `target_2 < target_1 < entry_price < stop_loss` |
| `"BULLISH (BUY)"` | `"NSE_FO_INDEX"` | `"LONG_INDEX_FUTURE"` | `stop_loss < entry_price < target_1 < target_2` |
| `"BEARISH (SELL)"` | `"NSE_FO_INDEX"` | `"SHORT_INDEX_FUTURE"` | `target_2 < target_1 < entry_price < stop_loss` |
| `"BULLISH (BUY CE)"` | `"NSE_FO_INDEX"` | `"LONG_CALL_OPTION"` | `stop_loss < entry_price < target_1 < target_2` (Long Call premium) |
| `"BEARISH (BUY PE)"` | `"NSE_FO_INDEX"` | `"LONG_PUT_OPTION"` | `stop_loss < entry_price < target_1 < target_2` (Long Put premium) |

### 3.2 Strategy-by-Strategy Bullish & Bearish Specification

#### Strategy 1: Order Block + BOS & FVG Retest (`evaluate_order_block_fvg`)
- **Preconditions:** $\ge 30$ completed 5m candles; evaluation bar within `09:15–15:30 IST`; scans `recent = completed[-15:]`.
- **Bullish (`BULLISH (BUY)`):**
  - **Zone Identification:** `ob_bar` (`recent[idx - 1]`) is bearish (`close < open`); `imp_1` or `imp_2` closes above `zone_high = ob_bar["high"]` (bullish BOS); either `imp_2["low"] > zone_high` (bullish 3-candle FVG) or `(imp_2["close"] - ob_bar["open"]) >= 1.5 * ATR(10)`.
  - **First Retest & Trigger:** No post-impulse bar closed below `zone_low = ob_bar["low"]`; no earlier post-impulse bar (`recent[idx + 2 : -1]`) touched `zone_high * 1.0015`; current bar `last` dips into `last["low"] <= zone_high * 1.0015` and rejects higher (`last["close"] > ob_bar["open"]` and `last["close"] >= zone_low`).
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(zone_low, 2)`, `stop_loss = round(zone_low - 0.25 * ATR(10), 2)`, `risk = max(0.5, entry - stop_loss)`, `target_1 = round(entry + 2.0 * risk, 2)`, `target_2 = round(entry + 3.0 * risk, 2)`.
- **Bearish (`BEARISH (SELL)`):**
  - **Zone Identification:** `ob_bar` (`recent[idx - 1]`) is bullish (`close > open`); `imp_1` or `imp_2` closes below `zone_low = ob_bar["low"]` (bearish BOS); either `imp_2["high"] < zone_low` (bearish 3-candle FVG) or `(ob_bar["open"] - imp_2["close"]) >= 1.5 * ATR(10)`.
  - **First Retest & Trigger:** No post-impulse bar closed above `zone_high = ob_bar["high"]`; no earlier post-impulse bar (`recent[idx + 2 : -1]`) touched `zone_low * 0.9985`; current bar `last` rallies into `last["high"] >= zone_low * 0.9985` and rejects lower (`last["close"] < ob_bar["open"]` and `last["close"] <= zone_high`).
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(zone_high, 2)`, `stop_loss = round(zone_high + 0.25 * ATR(10), 2)`, `risk = max(0.5, stop_loss - entry)`, `target_1 = round(entry - 2.0 * risk, 2)`, `target_2 = round(entry - 3.0 * risk, 2)`.

#### Strategy 2: Institutional VWAP Pullback / Rejection (`evaluate_vwap_pullback`)
- **Preconditions:** $\ge 35$ completed 5m candles; evaluation bar within `09:15–15:30 IST`; 20-bar prior average volume `avg_vol_20 > 0`; `last["volume"] >= 1.4 * avg_vol_20`.
- **Bullish (`BULLISH (BUY)`):**
  - `last["low"] <= curr_vwap * 1.0025`, `last["close"] > curr_vwap`, `last["close"] > last["open"]`, `last["close"] >= curr_ema20 * 0.998`, and `48.0 <= RSI(14) <= 72.0`.
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(min(last["low"], curr_vwap), 2)`, `stop_loss = round(min(last["low"], curr_vwap) - 0.35 * ATR(10), 2)`, `risk = max(0.5, entry - stop_loss)`, `target_1 = round(entry + 1.8 * risk, 2)`, `target_2 = round(entry + 2.5 * risk, 2)`.
- **Bearish (`BEARISH (SELL)`):**
  - `last["high"] >= curr_vwap * 0.9975`, `last["close"] < curr_vwap`, `last["close"] < last["open"]`, `last["close"] <= curr_ema20 * 1.002`, and `28.0 <= RSI(14) <= 52.0` (symmetric around RSI 50.0).
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(max(last["high"], curr_vwap), 2)`, `stop_loss = round(max(last["high"], curr_vwap) + 0.35 * ATR(10), 2)`, `risk = max(0.5, stop_loss - entry)`, `target_1 = round(entry - 1.8 * risk, 2)`, `target_2 = round(entry - 2.5 * risk, 2)`.

#### Strategy 3: Option Apex OI Shift + PCR (`evaluate_option_apex_oi_shift`)
- **Preconditions & Strict Validation:** Restricted to `index_symbol in ("NIFTY", "BANKNIFTY")`. Calls `validate_option_chain_for_strategy(option_chain)`, which explicitly verifies that `"atm_strike"`, `"pcr"`, and `"strikes"` exist and that the matching ATM row contains finite, non-boolean, non-null `"ce_ltp"`, `"pe_ltp"`, `"ce_oi"`, `"pe_oi"`, `"ce_oi_change"`, and `"pe_oi_change"` (`ce_ltp > 0`, `pe_ltp > 0`, `ce_oi >= 0`, `pe_oi >= 0`, `pcr > 0`). Missing or malformed fields raise `ValueError` and are never defaulted to zero.
- **Bullish Call Buy (`BULLISH (BUY CE)`):**
  - `ce_oi_change < 0` (ATM Call short-covering) AND `pe_oi_change > 0` (ATM Put writing) AND `pcr >= 1.10` AND `last["close"] >= curr_vwap * 0.998`.
  - **Levels:** `opt_premium = round(ce_ltp, 2)`, `stop_loss = round(opt_premium * 0.78, 2)`, `risk = max(1.0, opt_premium - stop_loss)`, `target_1 = round(opt_premium + 1.6 * risk, 2)`, `target_2 = round(opt_premium + 2.4 * risk, 2)`.
- **Bearish Put Buy (`BEARISH (BUY PE)`):**
  - `pe_oi_change < 0` (ATM Put unwinding) AND `ce_oi_change > 0` (ATM Call writing) AND `pcr <= 0.85` (documented threshold symmetric to `1.10` reflecting Call-heavy open interest) AND `last["close"] <= curr_vwap * 1.002`.
  - **Levels:** `opt_premium = round(pe_ltp, 2)`, `stop_loss = round(opt_premium * 0.78, 2)`, `risk = max(1.0, opt_premium - stop_loss)`, `target_1 = round(opt_premium + 1.6 * risk, 2)`, `target_2 = round(opt_premium + 2.4 * risk, 2)`.

#### Strategy 4: 15-Minute Opening Range Breakout / Breakdown (`evaluate_orb_breakout`)
- **Preconditions:** $\ge 30$ completed 5m candles total and $\ge 4$ completed current-day candles; `orb_bars = day_candles[:3]` (`09:15–09:30 IST`), `orb_high = max(high)`, `orb_low = min(low)`; `rvol = last["volume"] / avg_vol_20 >= 1.6`.
- **Bullish Breakout (`BULLISH (BUY)`):**
  - `prev["close"] <= orb_high`, `last["close"] > orb_high`, `last["close"] > curr_vwap`, `RSI(14) >= 55.0`, `rvol >= 1.6`.
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(orb_high, 2)`, `stop_loss = round(max(orb_low, last["low"] - (orb_high - orb_low) * 0.25), 2)`, `risk = max(0.5, entry - stop_loss)`, `target_1 = round(entry + 1.6 * risk, 2)`, `target_2 = round(entry + 2.4 * risk, 2)`.
- **Bearish Breakdown (`BEARISH (SELL)`):**
  - `prev["close"] >= orb_low`, `last["close"] < orb_low`, `last["close"] < curr_vwap`, `RSI(14) <= 45.0` (symmetric to `55.0`), `rvol >= 1.6`.
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(orb_low, 2)`, `stop_loss = round(min(orb_high, last["high"] + (orb_high - orb_low) * 0.25), 2)`, `risk = max(0.5, stop_loss - entry)`, `target_1 = round(entry - 1.6 * risk, 2)`, `target_2 = round(entry - 2.4 * risk, 2)`.

#### Strategy 5: Filtered Supertrend (10,3) Pullback + 200 EMA (`evaluate_supertrend_pullback`)
- **Preconditions:** $\ge 200$ completed 5m candles; blocks opening (`09:15 <= hhmm < 09:45`) and midday chop (`11:30 <= hhmm <= 13:30`) windows; `last["volume"] >= 1.3 * avg_vol_20`. Requires an already-established Supertrend direction on the prior completed candle (`st_dir[-2] == st_dir[-1]`) and prior close aligned with the 200 EMA so that a single-bar crash/spike that flips Supertrend on the current bar is not mistaken for a pullback.
- **Bullish Pullback (`BULLISH (BUY)`):**
  - `st_dir[-1] == 1 and st_dir[-2] == 1`, `last["close"] > curr_ema200`, `completed[-2]["close"] > ema200[-2]`, `last["close"] > curr_vwap`, `last["low"] <= curr_st * 1.004 or last["low"] <= curr_vwap * 1.003`, `last["close"] > last["open"]`.
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(curr_st, 2)`, `stop_loss = round(min(curr_st, last["low"]) - 0.25 * ATR(10), 2)`, `risk = max(0.5, entry - stop_loss)`, `target_1 = round(entry + 1.5 * risk, 2)`, `target_2 = round(entry + 2.5 * risk, 2)`.
- **Bearish Pullback (`BEARISH (SELL)`):**
  - `st_dir[-1] == -1 and st_dir[-2] == -1`, `last["close"] < curr_ema200`, `completed[-2]["close"] < ema200[-2]`, `last["close"] < curr_vwap`, `last["high"] >= curr_st * 0.996 or last["high"] >= curr_vwap * 0.997`, `last["close"] < last["open"]`.
  - **Levels:** `entry = round(last["close"], 2)`, `invalidation_level = round(curr_st, 2)`, `stop_loss = round(max(curr_st, last["high"]) + 0.25 * ATR(10), 2)`, `risk = max(0.5, stop_loss - entry)`, `target_1 = round(entry - 1.5 * risk, 2)`, `target_2 = round(entry - 2.5 * risk, 2)`.


## 4. Task 2 — Order Block Mitigation & First-Retest Design

1. **Deterministic Candle-History Mitigation (`prior_post_impulse`):**
   - For any candidate Order Block at `recent[idx - 1]` with impulse bars `recent[idx]` and `recent[idx + 1]`, let `subsequent = recent[idx + 2:]` and `prior_post_impulse = subsequent[:-1]`.
   - **Bullish Zone (`[zone_low, zone_high]`):**
     - **Invalidated** if `any(b["close"] < zone_low for b in subsequent)`.
     - **Already Mitigated** if `any(b["low"] <= zone_high * 1.0015 for b in prior_post_impulse)`.
   - **Bearish Zone (`[zone_low, zone_high]`):**
     - **Invalidated** if `any(b["close"] > zone_high for b in subsequent)`.
     - **Already Mitigated** if `any(b["high"] >= zone_low * 0.9985 for b in prior_post_impulse)`.
   - Consequently, only the **first** post-impulse candle that touches the Order Block zone can trigger a signal; on all subsequent candles, that first touch is part of `prior_post_impulse`, deterministically blocking duplicate signals even in stateless calls.
2. **In-Memory Process Registry (`mitigated_zones: Optional[Set[str]]`):**
   - `evaluate_order_block_fvg()` also accepts an optional `mitigated_zones` set keyed by `f"{symbol}:OB:{BULL|BEAR}:{ob_bar['timestamp']}"`. `IntradayBotEngine` maintains `self.mitigated_order_blocks` so repeated scans against identical candle snapshots within the same process never emit duplicate Order Block signals.
3. **Persistence Limitation Documented:**
   - Because Phase 1C prohibits introducing a database or disk persistence, cross-process mitigation tracking relies on the 15-bar candle lookback window passed to `evaluate_order_block_fvg()`. If a zone was mitigated more than 15 bars ago (outside `recent`) or across separate process restarts with truncated history, persistent cross-restart state requires the database layer planned for a later phase.


## 5. Task 3 — Reproducible Setup-Quality Score Specification

`compute_setup_quality_score(rvol, vwap_dist_atr, displacement_atr, market_breadth=None, is_bullish=True)` computes a deterministic integer score in `[0, 100]` from up to four normalized `[0.0, 1.0]` evidence features:

| Feature | Base Weight (With Breadth) | Renormalized Weight (No Breadth) | Normalization Formula (`[0.0, 1.0]`) |
| :--- | :---: | :---: | :--- |
| **1. Relative Volume (`rvol`)** | `0.30` | `0.3529` (`6/17`) | $\text{clamp}\left(\frac{\text{rvol} - 0.80}{1.70},\, 0.0,\, 1.0\right)$ (`0.80x` $\rightarrow 0.0$, `2.50x` $\rightarrow 1.0$) |
| **2. Directional VWAP Alignment (`vwap_dist_atr`)** | `0.25` | `0.2941` (`5/17`) | `0.0` if $d \le -0.25$ or $d \ge 3.25$; $\frac{d + 0.25}{0.40}$ on $(-0.25, 0.15)$; `1.0` in optimal launch zone $[0.15, 1.25]$ ATR; $1.0 - \frac{d - 1.25}{2.00}$ on $(1.25, 3.25)$ |
| **3. ATR Displacement (`displacement_atr`)** | `0.30` | `0.3529` (`6/17`) | $\text{clamp}\left(\frac{\text{displacement\_atr}}{2.00},\, 0.0,\, 1.0\right)$ (`0.0 ATR` $\rightarrow 0.0$, `2.0 ATR` $\rightarrow 1.0$) |
| **4. Market Breadth (`market_breadth`)** | `0.15` | `0.0000` (Excluded) | When `advances + declines > 0`, let $r = \frac{\text{advances}}{\text{total}}$ (bullish) or $\frac{\text{declines}}{\text{total}}$ (bearish); $\text{clamp}\left(\frac{r - 0.25}{0.50},\, 0.0,\, 1.0\right)$ |

$$\text{quality\_score} = \text{clamp}\left(\text{round}\left(100 \times \sum_{k \in \text{active}} w_k^{\text{eff}} \cdot f_k^{\text{norm}}\right),\, 0,\, 100\right)$$

- **Distinction from Win Probability:** `score_breakdown["score_semantics"]` explicitly labels the metric `"deterministic_setup_quality_0_100_not_calibrated_win_probability"`.
- **Missing Breadth Handling:** When `market_breadth` is `None` (or has zero total symbols), `breadth_available` is set to `False`, `features_normalized["market_breadth"]` is `None`, and the remaining active feature weights are renormalized to sum to `1.0`.


## 6. Task 4 — Test Execution & Compilation Evidence

### 6.1 Python Bytecode Compilation Check
Command executed:
```bash
python3 -m py_compile config.py brokers.py strategies.py scanner_engine.py telegram_bot.py server.py test_bot.py
```
Result: **Exit code `0`** (all 7 Python modules compiled cleanly with zero syntax or bytecode errors).

### 6.2 Full Regression & Phase 1C Test Suite Execution
Command executed:
```bash
python3 test_bot.py -v
```
Actual execution results:
- **Total Tests Executed:** `39` (`20` Phase 1A tests + `11` Phase 1B tests + `8` Phase 1C test suites)
- **Passed:** `39`
- **Failed:** `0`
- **Skipped:** `0`
- **Execution Time:** `6.919s` (`OK`)
- **Live External Requests:** `0` (all broker and Telegram network interactions are mocked via `unittest.mock.patch`; no live broker validation is claimed).


## 7. Known Limitations & Remaining Work

1. **In-Memory / Window-Bounded Order Block Mitigation Tracking:** Without a database or persistent storage (excluded by Phase 1C scope restrictions), Order Block mitigation tracking is deterministic over the 15-bar completed candle window (`recent = completed[-15:]`) and within a single `IntradayBotEngine` process lifetime (`self.mitigated_order_blocks`), but does not persist across process restarts.
2. **Option Premium Stop/Target Modeling:** `evaluate_option_apex_oi_shift()` uses deterministic percentage risk/reward levels (`0.78x` entry premium stop-loss, `1.6R` / `2.4R` targets) on the ATM option contract LTP without live Black-Scholes Greek (Delta/Gamma/Theta) option-pricing projection.
3. **Previous-Day OI Baseline on Live REST Option Chains:** As documented in Phase 1B, DhanHQ (`previous_oi`) and Upstox (`prev_oi`) report net OI change from the prior trading day's close; computing rolling 5m/15m intraday OI deltas requires timestamped snapshot persistence in a database.
4. **No Live Broker Validation in Sandbox:** Outbound network access is disabled in the VM and no live credentials are included; all broker and Telegram HTTP paths are verified via deterministic unit and mock-HTTP tests.
