# TradePulse AI — Phase 1A Implementation Report (`PHASE_1A_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-16  
**Scope:** Phase 1A — Backend Stabilization, Bug Fixes, Regression Testing & ZIP Delivery  
**Input Artifact:** `indian_fo_signal_bot_v1.zip`  
**Output Artifact:** `indian_fo_signal_bot_phase1a.zip`


## A. Baseline Inspection & Test Results

### A.1 Original File Tree (`indian_fo_signal_bot_v1.zip`)
Extracting the original `indian_fo_signal_bot_v1.zip` archive into an untouched baseline directory (`/tmp/phase1a_baseline/indian_fo_signal_bot_v1`) confirmed the following 10 files (66,476 bytes uncompressed, 1,463 total lines):

```text
indian_fo_signal_bot_v1/
├── .env.example          (1,330 bytes, 34 lines)
├── AI_STUDIO_PROMPT.md   (1,614 bytes, 23 lines)
├── README.md             (3,316 bytes, 34 lines)
├── brokers.py            (22,000 bytes, 509 lines)
├── config.py             (4,491 bytes, 87 lines)
├── scanner_engine.py     (4,263 bytes, 97 lines)
├── server.py             (1,020 bytes, 32 lines)
├── strategies.py         (20,634 bytes, 496 lines)
├── telegram_bot.py       (3,550 bytes, 67 lines)
└── test_bot.py           (4,258 bytes, 84 lines)
```

### A.2 Baseline Test Command & Dependencies
- **Dependencies:** Python 3.9+ standard library only (zero external `pip` packages required).
- **Test Command:** `python3 test_bot.py -v`

### A.3 Actual Baseline Test Results & Non-Deterministic `PYTHONHASHSEED` Failure
Because the baseline `SimulatedNSEAdapter.get_intraday_candles()` (`brokers.py` L285) seeded its random number generator using Python's built-in `hash(symbol)` (`rng = random.Random(hash(symbol) ^ self.seed)`), the baseline test suite was **non-deterministic across Python processes**. Executing `PYTHONHASHSEED=<seed> python3 test_bot.py` across seeds `0` through `10` produced **5 failures out of 11 runs (45.5% failure rate)**:

| Process Environment (`PYTHONHASHSEED`) | Baseline `test_bot.py` Result | Failing Test Method |
| :--- | :--- | :--- |
| `PYTHONHASHSEED=0` | `PASS` (8/8) | None |
| `PYTHONHASHSEED=1` | `PASS` (8/8) | None |
| `PYTHONHASHSEED=2` | `PASS` (8/8) | None |
| `PYTHONHASHSEED=3` | **`FAIL` (7/8 passed, 1 failed)** | `test_strategy_5_supertrend_pullback` |
| `PYTHONHASHSEED=4` | `PASS` (8/8) | None |
| `PYTHONHASHSEED=5` | **`FAIL` (7/8 passed, 1 failed)** | `test_strategy_5_supertrend_pullback` |
| `PYTHONHASHSEED=6` | **`FAIL` (7/8 passed, 1 failed)** | `test_strategy_5_supertrend_pullback` |
| `PYTHONHASHSEED=7` | **`FAIL` (7/8 passed, 1 failed)** | `test_strategy_5_supertrend_pullback` |
| `PYTHONHASHSEED=8` | `PASS` (8/8) | None |
| `PYTHONHASHSEED=9` | **`FAIL` (7/8 passed, 1 failed)** | `test_strategy_5_supertrend_pullback` |
| `PYTHONHASHSEED=10` | `PASS` (8/8) | None |

Baseline failure traceback under `PYTHONHASHSEED=3` (and `5, 6, 7, 9`):
```text
FAIL: test_strategy_5_supertrend_pullback (__main__.TestIndianFOSignalBotV1.test_strategy_5_supertrend_pullback)
Traceback (most recent call last):
  File "/tmp/phase1a_baseline/indian_fo_signal_bot_v1/test_bot.py", line 70, in test_strategy_5_supertrend_pullback
    self.assertIsNotNone(sig, "Strategy 5 (Supertrend 10,3 Pullback + 200 EMA) should trigger in valid session window")
AssertionError: unexpectedly None : Strategy 5 (Supertrend 10,3 Pullback + 200 EMA) should trigger in valid session window
```

### A.4 Confirmed Baseline Defects & Exact Code Locations
1. **Forced Synthetic Signal Injection (`scanner_engine.py` L34–L35, L58–L61; `brokers.py` L287–L289):** `IntradayBotEngine.run_single_scan()` explicitly passed `pattern="order_block_bull"`, `"vwap_pullback_bull"`, and `patterns[i % len(patterns)]` into `self.broker.fetch_candles()`, and `SimulatedNSEAdapter.get_intraday_candles()` defaulted `pattern=None` to `patterns[abs(hash(symbol)) % len(patterns)]`, forcing synthetic signals on every scan.
2. **Non-Deterministic `hash(symbol)` Seeding (`brokers.py` L285):** `random.Random(hash(symbol) ^ self.seed)` depended on Python's randomized per-process string hash salt (`PYTHONHASHSEED`).
3. **Warm-Up Price Discontinuity & Backward Timestamp Mutation (`brokers.py` L290–L413):** Warm-up bars (`session_idx < 0`) used a positive-drift walk `rng.uniform(-0.0012, 0.0016)` running overnight through non-market hours (`15:30` to `02:10 AM`), and `session_idx == 0` abruptly reset prices to `base * 1.001`. Furthermore, `supertrend_pullback_bull` at `session_idx == 35` (`L407`) overwrote `bar_dt = datetime(2026, 10, 16, 10, 30)` after bar 34's `12:05` timestamp, moving candle timestamps backward in time by 95 minutes.
4. **Lack of Timezone & Completed-Candle Filtering (`brokers.py` L92, L156; `strategies.py` L157–L496):** Timestamps were naive strings without `Asia/Kolkata` timezone awareness, and strategy evaluators treated the last candle in the list as completed without checking `is_complete` or comparing `bar_start + interval` against an injectable clock.
5. **Arithmetic SMA Used Instead of Wilder's RMA in RSI & ATR (`strategies.py` L65–L102):** `compute_rsi()` used `sum(gains[-period:]) / period` (and returned `100.0` instead of `50.0` on flat price series where `avg_gain == 0` and `avg_loss == 0`), while `compute_atr()` used `sum(trs[i-period+1:i+1]) / len(window)` instead of Wilder's recursive smoothing.
6. **Silent Live-to-Simulation Fallback (`brokers.py` L492–L509):** `MultiBrokerScanner.fetch_candles()` and `fetch_option_chain()` caught bare `Exception` on live broker adapters and silently returned `self.sim` data without raising an error or labeling the fallback.
7. **Unescaped Telegram HTML Entities (`telegram_bot.py` L18–L38):** `TelegramSignalDispatcher.format_signal_html()` interpolated `sig.instrument_label`, `sig.strategy_name`, `sig.rationale`, and `broker_name` into HTML tags without `html.escape()`, producing invalid HTML on symbols like `M&M` (`<code>M&M EQ</code>`).


## B. Changes Made in Phase 1A

### Fix A — Remove Forced Synthetic Signal Generation
- **Problem Found:** Normal scans in `IntradayBotEngine.run_single_scan()` forced synthetic candlestick patterns (`order_block_bull`, `vwap_pullback_bull`, `orb_breakout_bull`, `supertrend_pullback_bull`) across watchlist symbols, and `SimulatedNSEAdapter` assigned a forced pattern even when `pattern=None`.
- **Root Cause:** Demo pattern overrides were coupled directly into the default `pattern=None` branch of `SimulatedNSEAdapter.get_intraday_candles()` (`brokers.py` L287–L289) and hardcoded in `scanner_engine.py` (L34, L58–L61).
- **Files Changed:** `scanner_engine.py`, `brokers.py`, `strategies.py`.
- **What Changed:**
  - Removed all `pattern=...` and `bias="BULLISH"` arguments from `IntradayBotEngine.run_single_scan()` (`scanner_engine.py`).
  - Separated the `pattern is None` branch in `SimulatedNSEAdapter.get_intraday_candles()` (`brokers.py`) from the named test-fixture branches (`pattern="order_block_bull"`, etc.) so `pattern=None` generates an unforced, continuous SHA-256-seeded market series.
  - Added `is_simulated: bool` and `data_mode: str` (`"SIMULATED"` vs `"LIVE"`) fields to `TradeSignal` (`strategies.py`), `SimulatedNSEAdapter.get_option_chain()`, and `IntradayBotEngine.run_single_scan()`.
- **Why the Fix Is Correct:** Normal scans now evaluate natural input candles strictly against the strategy rules without manufacturing signals, while unit tests can still request explicit fixture patterns when testing individual strategy rules.
- **Relevant Regression Tests:** `test_normal_scan_does_not_force_signals_on_non_triggering_candles`, `test_explicit_simulation_mode_is_labeled`, `test_full_engine_and_telegram_dispatch`.

### Fix B — Deterministic Simulated Market Data
- **Problem Found:** `SimulatedNSEAdapter` produced different candles across separate Python processes whenever `PYTHONHASHSEED` varied.
- **Root Cause:** `brokers.py` L285 used Python's process-salted `hash(symbol)` function.
- **Files Changed:** `brokers.py`.
- **What Changed:** Added `SimulatedNSEAdapter._deterministic_rng(*parts)` which derives an 8-byte integer seed from `hashlib.sha256` over `(self.seed, symbol, interval_min, pattern)`. Applied deterministic SHA-256 seeding to both `get_intraday_candles()` and `get_option_chain()`.
- **Why the Fix Is Correct:** `hashlib.sha256` is a cryptographic hash whose digest is invariant across platforms, Python versions, and `PYTHONHASHSEED` settings.
- **Relevant Regression Tests:** `test_simulated_candles_deterministic_across_repeated_runs`, `test_cross_process_pythonhashseed_determinism`.

### Fix C — Candle Generation & OHLCV Validation
- **Problem Found:** Warm-up bars drifted away from `base` and ran through overnight non-market hours, while session bar 0 reset abruptly to `base * 1.001` and bar 35 of `supertrend_pullback_bull` jumped backward in time from `12:05` to `10:30`.
- **Root Cause:** Lack of continuous price anchoring (`anchor = price`) between warm-up and session bars, and absence of OHLCV / timestamp invariant validation.
- **Files Changed:** `brokers.py`, `strategies.py`.
- **What Changed:**
  - Implemented `validate_candles(candles, deduplicate=True)` in `strategies.py` enforcing finite positive OHLC prices, non-negative volume, `high >= max(open, close)`, `low <= min(open, close)`, `high >= low`, strictly non-decreasing timestamps, and consistent duplicate timestamp handling.
  - Updated `SimulatedNSEAdapter._build_session_timestamps()` to generate 3 prior NSE sessions of 75 five-minute bars (`09:15` to `15:25 IST` on `2026-10-13`, `2026-10-14`, `2026-10-15` = 225 warm-up bars) followed by 16 current-session bars (`09:15` to `10:30 IST` on `2026-10-16`), anchoring session bar 0 continuously to the final warm-up close (`anchor = price`).
- **Why the Fix Is Correct:** Every generated and ingested candle series is validated against all OHLCV and chronological invariants before any indicator or strategy calculation runs.
- **Relevant Regression Tests:** `test_ohlcv_invariants_and_warmup_continuity`, `test_validate_candles_rejects_invalid_ohlcv_and_backward_timestamps`.

### Fix D — Timestamps & Market-Session Handling
- **Problem Found:** Naive timestamps were sliced as strings (`ts_str[11:16]`), incomplete forming bars were not filtered out, and time-dependent logic could not be tested with an injectable clock.
- **Root Cause:** Absence of `zoneinfo.ZoneInfo("Asia/Kolkata")` parsing, completed-candle boundary checks (`bar_start + interval <= now`), and clock injection.
- **Files Changed:** `strategies.py`, `brokers.py`, `scanner_engine.py`.
- **What Changed:**
  - Added `IST = ZoneInfo("Asia/Kolkata")`, `parse_ist_timestamp()`, `format_ist_timestamp()`, `is_within_nse_session()`, and `filter_completed_candles(candles, interval_min=5, now=None)` in `strategies.py`.
  - Added optional `clock` callable injection to `AngelOneSmartAPIAdapter`, `DhanHQAdapter`, `UpstoxV2Adapter`, `SimulatedNSEAdapter`, `MultiBrokerScanner`, and `IntradayBotEngine`, and optional `now` parameter to all 5 strategy evaluators.
- **Why the Fix Is Correct:** Any candle marked `is_complete=False` or whose closing boundary `bar_start + 5m` is after the injected `now` clock in `Asia/Kolkata` is excluded before strategy evaluation.
- **Relevant Regression Tests:** `test_timezone_and_session_boundaries`, `test_completed_candle_filtering_with_injectable_clock`.

### Fix E — Wilder's RMA RSI and ATR Calculations
- **Problem Found:** `compute_rsi()` and `compute_atr()` used simple arithmetic moving averages over `period` bars, and `compute_rsi()` returned `100.0` on flat price series (`avg_gain == 0` and `avg_loss == 0`).
- **Root Cause:** Missing Wilder recursive smoothing (`RMA`) step after the initial `period` seed average.
- **Files Changed:** `strategies.py`.
- **What Changed:**
  - Updated `compute_rsi(closes, period=14)` to seed at `i == period` with the simple mean of the first `period` gains/losses and apply Wilder's smoothing `avg = (prev_avg * (period - 1) + current) / period` for `i > period`. Explicitly returns `50.0` when `avg_gain == 0 and avg_loss == 0`, `100.0` when `avg_loss == 0`, and `0.0` when `avg_gain == 0`. Rejects `NaN`/`inf` inputs with `ValueError`.
  - Updated `compute_atr(candles, period=10)` to initialize with cumulative mean up to `period` bars and apply Wilder's smoothing `atr = (prev_atr * (period - 1) + tr) / period` for `i >= period`, rejecting `NaN`/`inf` inputs.
- **Why the Fix Is Correct:** Matches standard Wilder RSI and ATR definitions used in institutional charting and Supertrend(10,3) calculations while safely handling flat-price and short-history edge cases.
- **Relevant Regression Tests:** `test_wilder_rsi_and_atr_calculations_and_edge_cases`.

### Fix F — Fix the Failing Supertrend Strategy Test (`test_strategy_5_supertrend_pullback`)
- **Problem Found:** `test_strategy_5_supertrend_pullback` failed on 5 out of 11 `PYTHONHASHSEED` values (`3, 5, 6, 7, 9`) in the baseline project.
- **Root Cause:** Combination of `hash(symbol)` non-determinism, positive warm-up drift (`rng.uniform(-0.0012, 0.0016)`) pushing `ema200` (`844.80`) above the reset session close (`842.65`), and bar 35 occurring at `12:10 IST` (inside the `11:30–13:30` chop filter) which the baseline code tried to work around by mutating bar 35's timestamp backward to `10:30`.
- **Files Changed:** `brokers.py`, `strategies.py`, `test_bot.py`.
- **What Changed:** Anchored `supertrend_pullback_bull` continuously to the final warm-up close (`anchor = price`) across a 16-bar morning session (`09:15` to `10:30 IST`), establishing a clean uptrend above the 200 EMA and session VWAP followed by a 2-bar pullback (`10:20`, `10:25 IST`) and a high-volume bounce off Supertrend/VWAP support at `10:30 IST`. Preserved all original Supertrend strategy rules and session filters intact.
- **Why the Fix Is Correct:** Fixes the fixture discontinuity and non-determinism without weakening `evaluate_supertrend_pullback` or fabricating out-of-order timestamps.
- **Relevant Regression Tests:** `test_strategy_5_supertrend_pullback`, `test_strategy_5_supertrend_blocks_chop_and_opening_windows`, `test_cross_process_pythonhashseed_determinism`.

### Fix G — Prevent Silent Live-to-Simulation Fallback
- **Problem Found:** `MultiBrokerScanner.fetch_candles()` and `fetch_option_chain()` caught all exceptions from live broker adapters and silently returned simulated data from `SimulatedNSEAdapter`.
- **Root Cause:** Bare `except Exception:` blocks in `brokers.py` (L497, L507) and `AngelOneSmartAPIAdapter.authenticate()` (L83).
- **Files Changed:** `brokers.py`, `scanner_engine.py`, `server.py`, `config.py`.
- **What Changed:**
  - Introduced `BrokerDataError(RuntimeError)` in `brokers.py`.
  - Removed silent fallback to `self.sim` in `MultiBrokerScanner`: when `active_broker` is set to `"angelone"`, `"dhan"`, or `"upstox"`, any missing/placeholder credential or HTTP/network error raises `BrokerDataError` with a sanitized message that never logs or exposes API keys, PINs, TOTP seeds, or access tokens.
  - Updated `server.py` to catch `BrokerDataError` on `GET /api/scan` and return HTTP `502 Bad Gateway` with `{"status": "error", "error_type": "BrokerDataError", ...}` rather than fake simulated signals.
- **Why the Fix Is Correct:** Callers and operators immediately see live broker failures instead of acting on silent synthetic data.
- **Relevant Regression Tests:** `test_live_provider_failure_raises_explicit_error_without_silent_fallback`, `test_explicit_simulation_mode_is_labeled`.

### Fix H — Secure Telegram HTML Formatting
- **Problem Found:** `TelegramSignalDispatcher.format_signal_html()` interpolated unescaped strings into HTML markup, breaking on symbols like `M&M` or strings containing `<`, `>`, `&`, and quotes.
- **Root Cause:** Missing `html.escape()` calls in `telegram_bot.py` (L18–L38) and unsanitized exception propagation in `send_signal()`.
- **Files Changed:** `telegram_bot.py`.
- **What Changed:** Applied `html.escape(str(val), quote=True)` (`_esc()`) to all dynamic fields in `format_signal_html()`, added `[SIMULATED DATA]` header tagging when `is_simulated` is True, and sanitized `urllib` exceptions in `send_signal()` so `telegram_bot_token` is never leaked in error tracebacks.
- **Why the Fix Is Correct:** Guarantees well-formed Telegram HTML payloads for allNSE symbols (including `M&M`) and prevents HTML injection or token leakage.
- **Relevant Regression Tests:** `test_telegram_html_escaping_and_mocked_send`.


## C. Verification & Test Execution Results

### C.1 Commands Executed
1. `python3 /tmp/phase1a_work/indian_fo_signal_bot_v1/test_bot.py -v`
2. `python3 /tmp/phase1a_work/indian_fo_signal_bot_v1/scanner_engine.py`

### C.2 Final Test Suite Output (20 Passed, 0 Failed, 0 Skipped)
```text
test_completed_candle_filtering_with_injectable_clock (__main__.TestIndianFOSignalBotPhase1A.test_completed_candle_filtering_with_injectable_clock) ... ok
test_cross_process_pythonhashseed_determinism (__main__.TestIndianFOSignalBotPhase1A.test_cross_process_pythonhashseed_determinism)
Verifies that simulated candles and Strategy 5 evaluation are identical across ... ok
test_explicit_simulation_mode_is_labeled (__main__.TestIndianFOSignalBotPhase1A.test_explicit_simulation_mode_is_labeled) ... ok
test_full_engine_and_telegram_dispatch (__main__.TestIndianFOSignalBotPhase1A.test_full_engine_and_telegram_dispatch) ... ok
test_indian_statutory_charges (__main__.TestIndianFOSignalBotPhase1A.test_indian_statutory_charges) ... ok
test_live_provider_failure_raises_explicit_error_without_silent_fallback (__main__.TestIndianFOSignalBotPhase1A.test_live_provider_failure_raises_explicit_error_without_silent_fallback) ... ok
test_normal_scan_does_not_force_signals_on_non_triggering_candles (__main__.TestIndianFOSignalBotPhase1A.test_normal_scan_does_not_force_signals_on_non_triggering_candles) ... ok
test_ohlcv_invariants_and_warmup_continuity (__main__.TestIndianFOSignalBotPhase1A.test_ohlcv_invariants_and_warmup_continuity) ... ok
test_simulated_candles_deterministic_across_repeated_runs (__main__.TestIndianFOSignalBotPhase1A.test_simulated_candles_deterministic_across_repeated_runs) ... ok
test_strategy_1_order_block_fvg (__main__.TestIndianFOSignalBotPhase1A.test_strategy_1_order_block_fvg) ... ok
test_strategy_2_vwap_pullback (__main__.TestIndianFOSignalBotPhase1A.test_strategy_2_vwap_pullback) ... ok
test_strategy_3_option_apex_oi_shift_nifty_banknifty_only (__main__.TestIndianFOSignalBotPhase1A.test_strategy_3_option_apex_oi_shift_nifty_banknifty_only) ... ok
test_strategy_4_orb_breakout (__main__.TestIndianFOSignalBotPhase1A.test_strategy_4_orb_breakout) ... ok
test_strategy_5_supertrend_blocks_chop_and_opening_windows (__main__.TestIndianFOSignalBotPhase1A.test_strategy_5_supertrend_blocks_chop_and_opening_windows) ... ok
test_strategy_5_supertrend_pullback (__main__.TestIndianFOSignalBotPhase1A.test_strategy_5_supertrend_pullback) ... ok
test_telegram_html_escaping_and_mocked_send (__main__.TestIndianFOSignalBotPhase1A.test_telegram_html_escaping_and_mocked_send) ... ok
test_timezone_and_session_boundaries (__main__.TestIndianFOSignalBotPhase1A.test_timezone_and_session_boundaries) ... ok
test_totp_generation (__main__.TestIndianFOSignalBotPhase1A.test_totp_generation) ... ok
test_validate_candles_rejects_invalid_ohlcv_and_backward_timestamps (__main__.TestIndianFOSignalBotPhase1A.test_validate_candles_rejects_invalid_ohlcv_and_backward_timestamps) ... ok
test_wilder_rsi_and_atr_calculations_and_edge_cases (__main__.TestIndianFOSignalBotPhase1A.test_wilder_rsi_and_atr_calculations_and_edge_cases) ... ok

----------------------------------------------------------------------
Ran 20 tests in 3.407s

OK
```
- **Passed:** 20
- **Failed:** 0
- **Skipped:** 0

### C.3 Cross-Process `PYTHONHASHSEED` Determinism Verification
`test_cross_process_pythonhashseed_determinism` spawned 8 isolated Python subprocesses with `PYTHONHASHSEED` set to `0`, `1`, `3`, `5`, `6`, `7`, `9`, and `42` (covering all 5 seeds that failed in baseline). All 8 subprocesses produced byte-for-byte identical JSON outputs for both natural (`pattern=None`) and fixture (`pattern="supertrend_pullback_bull"`) candle series and identical `evaluate_supertrend_pullback` signals.


## D. Remaining Limitations

1. **Live Broker Network Calls Not Executed in Sandbox:** Because outbound internet access is disabled in this VM environment and no live broker credentials are provided, live HTTP calls to Angel One SmartAPI, DhanHQ v2, Upstox v2, and Telegram Bot API were tested via `unittest.mock.patch("urllib.request.urlopen")` rather than against live external servers.
2. **Incomplete Live Option-Chain & Intraday Interval Adapters (Deferred to Phase 1B / Phase 2):**
   - `AngelOneSmartAPIAdapter` and `UpstoxV2Adapter` do not yet implement `get_option_chain()` (they inherit `NotImplementedError` from `BaseBrokerAdapter`, which now raises `BrokerDataError` when called in live mode rather than silently returning simulated option chains).
   - `DhanHQAdapter.get_option_chain()` still requires an `"ExpiryDate"` lookup (`/v2/optionchain/expirylist`) and response schema normalization to match the strike list format consumed by `evaluate_option_apex_oi_shift()`.
   - `UpstoxV2Adapter.get_intraday_candles()` still requests `"5minute"` on `/v2/historical-candle/intraday/`, which requires 1-minute candle resampling or Upstox v3 endpoints when used with a live Upstox token.
3. **Bullish-Only Strategy Rules Preserved in Phase 1A:** In accordance with Requirement 4A (*"Preserve the existing strategy rules unless a change is necessary to fix a verified correctness defect"*), all 5 strategies in `strategies.py` retain their existing bullish (`BUY` / `BUY CE`) rule definitions; bearish (`SELL` / `BUY PE`) symmetry is deferred to Phase 1B.
4. **No NSE Holiday Calendar or Persistent Database Yet:** `is_within_nse_session()` enforces `09:15–15:30 IST` time-of-day boundaries but does not include an NSE exchange holiday calendar or database persistence (deferred per Section 4D and Section 6).


## E. Phase 1B Readiness & Recommended Next Backend Tasks

### Confirmed Blockers for Live Broker Operation (Recommended for Phase 1B)
1. **DhanHQ Option-Chain Expiry & Schema Normalizer (`brokers.py`):** Implement `/v2/optionchain/expirylist` lookup and normalize Dhan's option-chain JSON into the `{"spot", "atm_strike", "pcr", "strikes"}` dictionary expected by `evaluate_option_apex_oi_shift()`.
2. **Upstox 1-Minute to 5-Minute Candle Resampler & Option Chain (`brokers.py`):** Fetch `1minute` intraday bars from Upstox v2 and aggregate completed 5-minute buckets (`09:15–09:19`, etc.), and implement `UpstoxV2Adapter.get_option_chain()` via `/v2/option/chain`.
3. **Angel One Option-Chain Assembly & Segment Mapping (`brokers.py`):** Map `NFO` vs `NSE` exchange segments accurately in `AngelOneSmartAPIAdapter.get_intraday_candles()` and implement option-chain quote assembly.

### Optional / Subsequent Enhancements
1. **Bidirectional (Bearish `SELL` / `BUY PE`) Strategy Evaluators (`strategies.py`):** Add symmetric bearish Order Block, bearish VWAP rejection, bearish Option Apex Put buying, bearish ORB breakdown, and bearish Supertrend pullback rules.
2. **Dynamic Instrument Master & Lot Size Resolution (`config.py`, `brokers.py`):** Ingest current NSE F&O lot sizes and active contract tokens dynamically instead of relying on static watchlist defaults.


## F. Delivery Verification (`indian_fo_signal_bot_phase1a.zip`)

The packaged deliverable `indian_fo_signal_bot_phase1a.zip` contains the complete, runnable project with all original files preserved plus `docs/PHASE_1A_IMPLEMENTATION_REPORT.md`, and excludes `__pycache__`, `.pyc` files, virtual environments, temporary files, and real credentials:

| File Path in `indian_fo_signal_bot_phase1a.zip` | Status | Description |
| :--- | :--- | :--- |
| `indian_fo_signal_bot_v1/.env.example` | Preserved | Environment template (no real credentials) |
| `indian_fo_signal_bot_v1/AI_STUDIO_PROMPT.md` | Preserved | Original AI Studio prompt document |
| `indian_fo_signal_bot_v1/README.md` | Updated | Updated usage and Phase 1A test instructions |
| `indian_fo_signal_bot_v1/config.py` | Updated | Runtime `__post_init__` env resolution preserving `BotConfig` interface |
| `indian_fo_signal_bot_v1/brokers.py` | Updated | SHA-256 deterministic seed, continuous warm-up/session bars, `BrokerDataError` (no silent fallback) |
| `indian_fo_signal_bot_v1/strategies.py` | Updated | Wilder RMA RSI/ATR, `validate_candles`, `filter_completed_candles`, `Asia/Kolkata` timezone handling |
| `indian_fo_signal_bot_v1/scanner_engine.py` | Updated | Unforced normal scanning, injectable clock, explicit `data_mode` (`SIMULATED` vs `LIVE`) |
| `indian_fo_signal_bot_v1/telegram_bot.py` | Updated | `html.escape` on all dynamic fields (`M&M`), `[SIMULATED DATA]` badge, token-sanitized errors |
| `indian_fo_signal_bot_v1/server.py` | Updated | Explicit HTTP 502 error response on `BrokerDataError` |
| `indian_fo_signal_bot_v1/test_bot.py` | Updated | 20 unit & regression tests (100% passing across `PYTHONHASHSEED` subprocesses) |
| `indian_fo_signal_bot_v1/docs/PHASE_1A_IMPLEMENTATION_REPORT.md` | Added | Complete Phase 1A implementation and verification report |
