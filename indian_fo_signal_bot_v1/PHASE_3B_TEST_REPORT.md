# TradePulse AI — Phase 3B Test & Verification Report (`PHASE_3B_TEST_REPORT.md`)

**Date:** 2026-10-17  
**Baseline Artifact:** `indian_fo_signal_bot_phase3a.zip` (`89/89` tests passing; SQLite `ResourceWarning`s present under `-W error::ResourceWarning`)  
**Output Artifact:** `indian_fo_signal_bot_phase3b.zip` (`101/101` tests passing; `0` `ResourceWarning`s under `-W error::ResourceWarning`)  
**Implementation Status:** `IMPLEMENTED_VERIFIED`  
**Data Acceptance Status:** `BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED`

## 1. Summary of Compilation, Baseline Rerun & Full-Suite Test Execution

| Verification Step | Command Executed | Result | Details |
| :--- | :--- | :--- | :--- |
| **1. Baseline Rerun (Phase 3A Untouched)** | `python3 test_bot.py -v` | **`89 / 89 PASS`** (`0` failed, `0` skipped) | Confirmed baseline 89 tests pass in `22.710s`. |
| **2. Baseline SQLite `ResourceWarning` Investigation** | `python3 -W error::ResourceWarning test_bot.py -v` (on untouched Phase 3A) | **Confirmed Warning** (`ResourceWarning: unclosed database in <sqlite3.Connection object>`) | Root-caused to `SQLitePersistenceStore(":memory:")` keeping `_memory_conn` open without `close()` / `__del__` / `atexit` cleanup and `configure_server_runtime()` overwriting `DashboardRequestHandler.engine` without closing the prior engine's store. |
| **3. Phase 3B Python Bytecode Compilation** | `python3 -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py diagnostics.py historical_data.py backtest_engine.py test_bot.py` | **Exit Code `0`** | All 11 Python modules compiled with zero syntax errors or warnings. |
| **4. Phase 3B Full Test Suite with `ResourceWarning` as Error** | `python3 -W error::ResourceWarning test_bot.py -v` | **`101 / 101 PASS`** (`0` failed, `0` skipped, **`0` warnings**) | All 89 existing Phase 1A–3A tests + 12 new Phase 3B test suites passed in `50.613s` with `ResourceWarning` treated as a fatal error. |
| **5. Phase 2C Offline Diagnostic Rerun** | `python3 -W error::ResourceWarning diagnostics.py --offline` | **`UNAVAILABLE_MISSING_CREDENTIALS`** (Gate Preserved) | `Live Connectivity Verified: NO`, `PASS=1 | WARNING=2 | FAIL=2 | NOT CHECKED=4`, `0` `ResourceWarning`s. |
| **6. Phase 3A Historical Readiness Rerun** | `python3 -W error::ResourceWarning historical_data.py --readiness --data-mode LIVE` | **`BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED`** | `phase3_ready_for_execution = False`, Strategy 3 `BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`, `0` `ResourceWarning`s. |

## 2. Root-Cause Analysis & Resolution of SQLite `ResourceWarning`s

1. **Observed Symptom in Phase 3A:**
   Running `python3 -W default test_bot.py` on the Phase 3A baseline emitted `ResourceWarning: unclosed database in <sqlite3.Connection object>` during garbage collection at test teardown and interpreter exit.
2. **Root Cause Identified:**
   - In `storage.py`, when `database_url == ":memory:"`, `SQLitePersistenceStore.__init__()` opened a persistent `self._memory_conn = sqlite3.connect(":memory:", ...)` connection so all queries shared the same in-memory database. However, `SQLitePersistenceStore` had no `close()` method, context manager, finalizer (`__del__`), or `atexit` hook. When test cases finished and `IntradayBotEngine` or `SQLitePersistenceStore` instances were garbage-collected, `sqlite3.Connection.__del__` emitted `ResourceWarning: unclosed database`.
   - In `server.py`, `configure_server_runtime()` replaced `DashboardRequestHandler.engine` (which is initialized at import time with `:memory:`) without closing the previous `DashboardRequestHandler.engine.store`.
3. **Deterministic Fix Implemented (`storage.py`, `scanner_engine.py`, `server.py`, `historical_data.py`, `diagnostics.py`):**
   - Added `_ACTIVE_SQLITE_STORES: "weakref.WeakSet[SQLitePersistenceStore]"` and an `@atexit.register` hook `_close_all_active_sqlite_stores()`.
   - Implemented `SQLitePersistenceStore.close()`, `__enter__()`, `__exit__()`, and `__del__()` to deterministically close `self._memory_conn`.
   - Added `IntradayBotEngine.close()`, `__enter__()`, `__exit__()`, and `__del__()` in `scanner_engine.py`.
   - Updated `configure_server_runtime()` in `server.py` and CLI entrypoints in `historical_data.py`, `diagnostics.py`, and `backtest_engine.py` to close stores deterministically.
   - Verified via `python3 -W error::ResourceWarning test_bot.py -v` (`101/101` tests passing with `0` warnings).

## 3. Phase 3B Test Inventory (`TestIndianFOSignalBotPhase3B` — 12 Test Suites)

| Test Method in `test_bot.py` | Coverage Area | Deterministic Hand-Calculated Assertions Verified | Result |
| :--- | :--- | :--- | :---: |
| `test_p3b_01_historical_replay_ordering_and_no_lookahead_guarantees` | Replay ordering & no-look-ahead | Verifies reversed/shuffled candle arrays sort identically before replay; verifies appending future crash/spike candles after trade exit (`10:45:00`) cannot alter earlier signal decisions (`10:30:00`), entry prices (`10:35:00`), or P&L. | `PASS` |
| `test_p3b_02_signal_timing_next_candle_open_execution_and_hand_calculated_long_trade` | Next-candle open fill & hand-calculated `LONG` trade | Signal at `10:30:00` (`stop_loss=2937.72`, `target_1=2991.78`); next bar (`10:35:00`) opens at `2957.72` (`risk_per_unit=20.00 INR`, `qty=50` shares for `₹1,000` risk budget); `10:40:00` hits `target_1=2991.78` $ightarrow$ `gross_pnl=1703.00`, `brokerage=40.00`, `stt=37.40`, `exchange_txn=8.84`, `sebi=0.30`, `stamp_duty=4.44`, `gst=8.85`, `charges=99.83`, `net_pnl=1603.17`, `R=1.6032`. | `PASS` |
| `test_p3b_03_hand_calculated_short_trade_entry_target_and_stop_accounting` | Hand-calculated `SHORT` trade & side-specific taxes | Bearish Order Block on `RELIANCE` at `10:30:00`; next bar opens at `stop_loss - 10.00` (`qty=100` shares); hits `target_1`; verifies STT is charged on the entry (SELL) leg and Stamp Duty on the exit (BUY) leg. | `PASS` |
| `test_p3b_04_same_candle_stop_target_collision_conservative_long_and_short` | Conservative same-candle collision | Both `LONG` and `SHORT` trades where a single 5m candle breaches both `stop_loss` and `target_1` resolve conservatively to `STOP_LOSS_SAME_CANDLE_CONSERVATIVE` at `stop_loss` (`same_candle_collision=True`, `net_pnl < 0`). | `PASS` |
| `test_p3b_05_gap_handling_missing_next_candle_and_gap_beyond_stop_or_target` | Missing-bar & opening gap rules | (A) Missing `10:35:00` bar after `10:30:00` signal rejects entry (`MISSING_NEXT_CANDLE_GAP=1`). (B) Next bar opening beyond `stop_loss` rejects entry (`NEXT_OPEN_GAP_BEYOND_STOP_LOSS=1`). (C) Subsequent bar gapping below `stop_loss` at open exits at gap open (`STOP_LOSS_GAP_OPEN`). | `PASS` |
| `test_p3b_06_session_boundaries_eod_cutoff_and_mandatory_square_off` | Session entry cutoff & EOD square-off | Signals at/after `last_entry_Cutoff_ist` are rejected (`SIGNAL_AT_OR_AFTER_EOD_ENTRY_CUTOFF=1`); open intraday positions are squared off at session/dataset end (`END_OF_DATASET_SQUARE_OFF`). | `PASS` |
| `test_p3b_07_daily_loss_limit_daily_profit_target_and_position_sizing` | Capital exposure, daily loss & profit limits | Verifies `INSUFFICIENT_CAPITAL` rejection when capital < 1 share price; verifies `daily_profit_target_triggered=True` when net daily P&L reaches target; verifies `daily_loss_limit_triggered=True` when net daily loss breaches `-max_daily_loss_inr`. | `PASS` |
| `test_p3b_08_indian_cost_model_exact_hand_calculated_schedule` | Itemized Indian cost schedule (`EQ`, `FUTIDX`, `OPTIDX`) | Hand-calculated verification of `100` shares @ `₹1,000` $ightarrow$ `₹1,020` with `5 bps` slippage (`entry_eff=1000.50`, `exit_eff=1019.49`, `slippage=101.00`, `charges=82.78`, `total_costs=183.78`), brokerage cap on small orders, and `FUTIDX`/`OPTIDX` rate schedules. | `PASS` |
| `test_p3b_09_zero_trades_and_zero_losses_metrics_edge_cases` | Zero-trade & zero-loss metric edge cases | When `total_trades == 0`, `profit_factor is None` (`UNDEFINED_ZERO_TRADES`, `"N/A (0 trades)"`). When `winning_trades > 0` and `losing_trades == 0`, `profit_factor is None` (`INFINITE_NO_LOSSES`, `"INF_NO_LOSSES"`). | `PASS` |
| `test_p3b_10_live_readiness_gate_live_vs_simulated_isolation_and_strategy_blocking` | Phase 2C/3A gates, mode isolation & Strategy 3 blocking | Blocks `LIVE` backtest when Phase 2C live acceptance is incomplete; blocks `SIMULATED` candles passed under `LIVE` mode; blocks Strategy 3 (`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`); blocks `NIFTY` index spot (`BLOCKED_INDEX_SPOT_NOT_EXECUTABLE`); blocks Strategy 5 when `< 200` bars (`BLOCKED_INSUFFICIENT_WARMUP_BARS`). | `PASS` |
| `test_p3b_11_chronological_period_splits_reproducibility_and_all_eligible_strategies` | Train/Val/OOS splits, reproducibility & Strategies 1, 2, 4, 5 | Verifies `< 3` sessions reports `INSUFFICIENT_SESSIONS_FOR_3WAY_SPLIT`; verifies 4-session split (`2 TRAIN`, `1 VALIDATION`, `1 OUT_OF_SAMPLE`); verifies Strategies 1, 2, 4, and 5 execute deterministically and repeated runs produce identical `run_id`, `dataset_checksum`, and metrics. | `PASS` |
| `test_p3b_12_sqlite_persistence_http_api_routes_resource_warnings_and_security` | SQLite persistence, HTTP API validation, security & `gc.collect()` | Verifies `GET /api/backtest-eligibility`, `POST /api/backtest`, `GET /api/backtest-runs`, `GET /api/backtest-runs/<run_id>`, `HTTP 422` on Strategy 3 & `LIVE` gate failure, `HTTP 404` on `/backtest_engine.py`, and zero `ResourceWarning`s on `gc.collect()`. | `PASS` |

## 4. Captured Test Execution Output

```text
$ python3 -W error::ResourceWarning test_bot.py -v
...
test_p3b_01_historical_replay_ordering_and_no_lookahead_guarantees (__main__.TestIndianFOSignalBotPhase3B.test_p3b_01_historical_replay_ordering_and_no_lookahead_guarantees) ... ok
test_p3b_02_signal_timing_next_candle_open_execution_and_hand_calculated_long_trade (__main__.TestIndianFOSignalBotPhase3B.test_p3b_02_signal_timing_next_candle_open_execution_and_hand_calculated_long_trade) ... ok
test_p3b_03_hand_calculated_short_trade_entry_target_and_stop_accounting (__main__.TestIndianFOSignalBotPhase3B.test_p3b_03_hand_calculated_short_trade_entry_target_and_stop_accounting) ... ok
test_p3b_04_same_candle_stop_target_collision_conservative_long_and_short (__main__.TestIndianFOSignalBotPhase3B.test_p3b_04_same_candle_stop_target_collision_conservative_long_and_short) ... ok
test_p3b_05_gap_handling_missing_next_candle_and_gap_beyond_stop_or_target (__main__.TestIndianFOSignalBotPhase3B.test_p3b_05_gap_handling_missing_next_candle_and_gap_beyond_stop_or_target) ... ok
test_p3b_06_session_boundaries_eod_cutoff_and_mandatory_square_off (__main__.TestIndianFOSignalBotPhase3B.test_p3b_06_session_boundaries_eod_cutoff_and_mandatory_square_off) ... ok
test_p3b_07_daily_loss_limit_daily_profit_target_and_position_sizing (__main__.TestIndianFOSignalBotPhase3B.test_p3b_07_daily_loss_limit_daily_profit_target_and_position_sizing) ... ok
test_p3b_08_indian_cost_model_exact_hand_calculated_schedule (__main__.TestIndianFOSignalBotPhase3B.test_p3b_08_indian_cost_model_exact_hand_calculated_schedule) ... ok
test_p3b_09_zero_trades_and_zero_losses_metrics_edge_cases (__main__.TestIndianFOSignalBotPhase3B.test_p3b_09_zero_trades_and_zero_losses_metrics_edge_cases) ... ok
test_p3b_10_live_readiness_gate_live_vs_simulated_isolation_and_strategy_blocking (__main__.TestIndianFOSignalBotPhase3B.test_p3b_10_live_readiness_gate_live_vs_simulated_isolation_and_strategy_blocking) ... ok
test_p3b_11_chronological_period_splits_reproducibility_and_all_eligible_strategies (__main__.TestIndianFOSignalBotPhase3B.test_p3b_11_chronological_period_splits_reproducibility_and_all_eligible_strategies) ... ok
test_p3b_12_sqlite_persistence_http_api_routes_resource_warnings_and_security (__main__.TestIndianFOSignalBotPhase3B.test_p3b_12_sqlite_persistence_http_api_routes_resource_warnings_and_security) ... ok

----------------------------------------------------------------------
Ran 101 tests in 50.613s

OK
```
