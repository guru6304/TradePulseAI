# TradePulse AI — Phase 3B Implementation Report (`PHASE_3B_REPORT.md`)

**Date:** 2026-10-17  
**Scope:** Phase 3B — Deterministic Backtesting Engine and Historical Strategy Evaluation  
**Baseline Artifact:** `indian_fo_signal_bot_phase3a.zip` (`89/89` tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase3b.zip` (`101/101` tests passing, `0` `ResourceWarning`s)  
**Implementation Status:** **`IMPLEMENTED_VERIFIED`**  
**Data Acceptance Status:** **`BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED`** (Synthetic/Test Mode Runs Labeled `SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED`)

## 1. Executive Summary & Mandatory Status Separation

Phase 3B extends the verified Phase 3A baseline (`indian_fo_signal_bot_phase3a.zip`) with a deterministic, point-in-time historical backtesting engine (`backtest_engine.py`), SQLite backtest run and trade-ledger persistence (`storage.py`), read-only/validated backtest HTTP endpoints (`server.py`), and deterministic SQLite connection cleanup that eliminates all `ResourceWarning`s under `python -W error::ResourceWarning`.

In strict compliance with Section 3 and Section 17 of the Phase 3B specification, two independent statuses are maintained across the engine, CLI, SQLite database, HTTP APIs, and documentation:

| Status Dimension | Current Value | Meaning & Evidence |
| :--- | :--- | :--- |
| **Implementation Status** | **`IMPLEMENTED_VERIFIED`** | The deterministic backtesting engine, point-in-time no-look-ahead replay, next-candle open execution, conservative same-candle collision resolution, Indian statutory cost model, daily risk controls, SQLite persistence, and HTTP API endpoints are implemented and verified across **101 passing automated tests (`0` failed, `0` skipped, `0` `ResourceWarning`s)**. |
| **Data Acceptance Status** | **`BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED`** | Outbound internet access is disabled in the sandbox VM and no live Angel One credentials, live `OpenAPIScripMaster.json`, or live `LIVE`-mode historical datasets exist in this environment. All tests executed in the sandbox use synthetic fixtures explicitly labeled `SIMULATED/TEST MODE` (`SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED`). |
| **Actual `LIVE` Historical Data Tested?** | **NO** | Zero live historical market data was tested in this sandbox environment. |
| **Any Profitability Claim Justified?** | **NO** | Synthetic fixture runs verify deterministic engine mechanics and accounting accuracy only; no strategy profitability claim is made or justified until verified multi-session `LIVE` historical datasets are evaluated out-of-sample. |
| **Is Phase 3C Safe to Begin?** | **Implementation-Ready; Blocked on Local Live-Data Acceptance** | The codebase and backtest infrastructure are clean, tested, and ready (`101/101` tests passing with `0` `ResourceWarning`s), **but Phase 3C (live historical strategy evaluation / walk-forward optimization) must NOT make live performance claims until local Phase 2C live-data acceptance (`python .\diagnostics.py`) and Phase 3A `LIVE` dataset ingestion are completed on your local Windows machine.** |

## 2. Step A — Pre-Implementation Audit of Phase 3A Baseline

1. **Baseline Extraction & Test Rerun:**
   - Extracted `indian_fo_signal_bot_phase3a.zip` into `/tmp/phase3b_baseline/indian_fo_signal_bot_v1` (21 files).
   - Ran `python3 -m py_compile` across all 10 baseline modules (exit code `0`) and `python3 test_bot.py -v` (`89/89` tests passed in `22.710s`).
2. **SQLite `ResourceWarning` Investigation:**
   - Running `python3 -W default test_bot.py` and `python3 -W error::ResourceWarning test_bot.py` on the untouched Phase 3A baseline reproduced `ResourceWarning: unclosed database in <sqlite3.Connection object>`.
   - **Root Cause:** `SQLitePersistenceStore(":memory:")` in `storage.py` kept a persistent `self._memory_conn` open without a `close()` method, `__del__()` finalizer, or `atexit` cleanup hook, and `configure_server_runtime()` in `server.py` replaced `DashboardRequestHandler.engine` without closing the prior engine's `SQLitePersistenceStore`.
   - **Resolution:** Added `_ACTIVE_SQLITE_STORES` (`weakref.WeakSet`) + `@atexit.register` cleanup + `close()` / `__enter__()` / `__exit__()` / `__del__()` on `SQLitePersistenceStore` (`storage.py`) and `IntradayBotEngine` (`scanner_engine.py`), and closed replaced engines in `configure_server_runtime()` (`server.py`) and CLI runners (`historical_data.py`, `diagnostics.py`, `backtest_engine.py`).
3. **Phase 2C & Phase 3A Gate Verification:**
   - Re-running `python3 diagnostics.py --offline` confirmed `Broker Connection State: UNAVAILABLE_MISSING_CREDENTIALS` and `Live Connectivity Verified: NO`.
   - Re-running `python3 historical_data.py --readiness --data-mode LIVE` confirmed `Overall Gate Status: BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED` and `phase3_ready_for_execution = False`. Both gates remain intact and unweakened.

## 3. Baseline (Phase 3A) vs Phase 3B Behavior Comparison

| Capability / Area | Phase 3A Baseline Behavior | Phase 3B Behavior |
| :--- | :--- | :--- |
| **Historical Data Validation & Point-in-Time Slicing** | Implemented in `historical_data.py` (`validate_and_prepare_historical_dataset`, `get_point_in_time_candle_slice`, `verify_no_lookahead_leakage`). | Preserved 100% intact and invoked at every simulated decision step inside `DeterministicBacktestEngine.run_backtest()`. |
| **Deterministic Historical Strategy Backtesting** | Not implemented (deferred at Phase 3A gate). | Implemented in `backtest_engine.py` (`DeterministicBacktestEngine`), supporting point-in-time replay, next-candle open execution (`NEXT_CANDLE_OPEN`), conservative same-candle collision resolution, gap handling, and mandatory EOD square-off (`15:20 IST`). |
| **Strategy Eligibility & Blocking Enforcement** | Static readiness dictionary in `historical_data.py`. | Programmatic `evaluate_strategy_backtest_eligibility()` in `backtest_engine.py`: allows Strategies 1, 2, 4, and 5 on validated NSE 5m equity series; blocks Strategy 3 (`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`), zero-volume/index-spot series (`BLOCKED_INDEX_SPOT_NOT_EXECUTABLE`, `BLOCKED_ZERO_VOLUME_SERIES`), missing ORB bars, and `< 200` warm-up bars for Strategy 5. |
| **Indian Market Transaction Costs & Slippage** | Simple `calculate_indian_statutory_charges()` in `strategies.py` with flat ₹40 brokerage and no slippage breakdown. | Configurable `IndianCostModel` in `backtest_engine.py` itemizing per-leg brokerage (`min(20, 0.03%)`), sell-side STT, NSE exchange transaction charges, SEBI fees, buy-side stamp duty, 18% GST, and per-leg execution slippage (`bps`) without double counting. |
| **Position Sizing & Daily Risk Controls** | `account_capital_inr` (`150000`) and `max_risk_per_trade_pct` (`1.0`) in `config.py`. | Added `max_daily_loss_inr` (`2000.0`), `daily_profit_target_inr` (`4000.0`), and `max_concurrent_positions` (`1`) in `config.py` and `BacktestConfig`, enforcing capital exposure limits, daily loss halts (`DAILY_LOSS_LIMIT_REACHED`), and daily profit targets (`DAILY_PROFIT_TARGET_REACHED`). |
| **SQLite Persistence & HTTP API** | 7 tables (`scan_runs`, `signals`, `oi_snapshots`, `mitigated_order_blocks`, `oi_baselines`, `historical_datasets`, `historical_candles`). | Added backward-compatible `backtest_runs` and `backtest_trades` tables in `storage.py`, plus `GET /api/backtest-eligibility`, `GET /api/backtest-runs`, `GET /api/backtest-runs/<run_id>`, and `POST /api/backtest` in `server.py`. |
| **SQLite Resource Lifecycle** | Emitted `ResourceWarning: unclosed database` on `:memory:` connections during GC. | Zero `ResourceWarning`s (`python3 -W error::ResourceWarning test_bot.py -v` passes all 101 tests). |

## 4. Complete List of Added, Modified, and Deleted Files

| File Path | Action | Reason for Addition / Modification |
| :--- | :--- | :--- |
| `backtest_engine.py` | **Added** | Implements `STRATEGY_BACKTEST_ELIGIBILITY`, `IndianCostModel`, `BacktestConfig`, `evaluate_strategy_backtest_eligibility()`, `split_sessions_chronologically()`, `compute_backtest_metrics()`, `DeterministicBacktestEngine`, report formatter, and CLI runner. |
| `config.py` | **Modified** | Added `max_daily_loss_inr` (default `2000.0`), `daily_profit_target_inr` (default `4000.0`), and `max_concurrent_positions` (default `1`) with validation in `BotConfig.validate()` and safe serialization in `to_safe_dict()`. |
| `.env.example` | **Modified** | Added `MAX_DAILY_LOSS_INR=2000`, `DAILY_PROFIT_TARGET_INR=4000`, and `MAX_CONCURRENT_POSITIONS=1` configuration templates (no real credentials). |
| `storage.py` | **Modified** | Added deterministic connection lifecycle cleanup (`close()`, `__enter__()`, `__exit__()`, `__del__()`, `_ACTIVE_SQLITE_STORES` weakset + `atexit` hook); added `backtest_runs` and `backtest_trades` tables; added `save_backtest_run()`, `query_backtest_runs()`, and `get_backtest_run_detail()`; added `backtest_runs_count` and `backtest_trades_count` to `check_health()`. |
| `scanner_engine.py` | **Modified** | Added `IntradayBotEngine.close()`, `__enter__()`, `__exit__()`, and `__del__()` to deterministically close `self.store`. |
| `historical_data.py` | **Modified** | Updated CLI `main()` to close `SQLitePersistenceStore` deterministically via `try ... finally: store.close()`. |
| `diagnostics.py` | **Modified** | Updated `run_angelone_diagnostics()` and `main()` to close internally created `SQLitePersistenceStore` instances deterministically. |
| `server.py` | **Modified** | Added `GET /api/backtest-eligibility`, `GET /api/backtest-runs`, `GET /api/backtest-runs/<run_id>`, and `POST /api/backtest` (plus `/api/v1/*` aliases); updated `configure_server_runtime()` to close replaced engine stores. |
| `test_bot.py` | **Modified** | Preserved all 89 Phase 1A–3A tests and added `TestIndianFOSignalBotPhase3B` (12 new deterministic test suites, bringing total to **101 passing tests**). |
| `README.md` | **Modified** | Updated with Phase 3B architecture, CLI usage, HTTP endpoints, and exact Windows PowerShell commands. |
| `PHASE_3B_REPORT.md` & `docs/PHASE_3B_REPORT.md` | **Added** | Master Phase 3B implementation report. |
| `PHASE_3B_TEST_REPORT.md` & `docs/PHASE_3B_TEST_REPORT.md` | **Added** | Complete test & compilation report (`101/101` passing, `0` warnings). |
| `PHASE_3B_STRATEGY_ELIGIBILITY.md` & `docs/PHASE_3B_STRATEGY_ELIGIBILITY.md` | **Added** | 5-strategy backtest eligibility matrix and input dependency audit. |
| `PHASE_3B_BACKTEST_METHODOLOGY.md` & `docs/PHASE_3B_BACKTEST_METHODOLOGY.md` | **Added** | Mathematical specification of no-look-ahead replay, execution, costs, risk controls, and metrics. |
| *(Deleted Files)* | **None (`0` deleted)** | All Phase 1A–3A source files, documentation, and tests were preserved intact. |

## 5. Exact Windows PowerShell Commands to Run Tests & Backtests

1. **Extract `indian_fo_signal_bot_phase3b.zip` and verify bytecode compilation:**
   ```powershell
   Expand-Archive -Path .\indian_fo_signal_bot_phase3b.zip -DestinationPath .	radepulse_phase3b -Force
   Set-Location .	radepulse_phase3b\indian_fo_signal_bot_v1
   Copy-Item .\.env.example .\.env -Force
   python -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py diagnostics.py historical_data.py backtest_engine.py test_bot.py
   ```

2. **Run the complete 101-test suite (treating `ResourceWarning` as an error):**
   ```powershell
   python -W error::ResourceWarning .	est_bot.py -v
   ```

3. **Inspect the Strategy Backtest Eligibility Matrix (CLI):**
   ```powershell
   python .acktest_engine.py --eligibility
   python .acktest_engine.py --eligibility --json
   ```

4. **Run a Deterministic Backtest on a Synthetic Fixture (`SIMULATED/TEST MODE`):**
   ```powershell
   python .acktest_engine.py --strategy strat_1_order_block --symbol RELIANCE --data-mode SIMULATED --synthetic-fixture order_block_bull --capital 200000 --risk-pct 0.5 --slippage-bps 0
   ```

5. **Run a Deterministic Backtest on Persisted SQLite Historical Candles:**
   ```powershell
   python .acktest_engine.py --strategy strat_2_vwap_pullback --symbol TCS --provider angelone --data-mode LIVE --start-date 2026-10-01 --end-date 2026-10-16 --period-type FULL
   ```

## 6. Known Limitations & Next Acceptance Requirements Before Phase 3C

1. **Local Phase 2C Live-Data Acceptance Required First:** Run `python .\diagnostics.py` on your local Windows machine with valid Angel One SmartAPI credentials (`ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET`) so broker connectivity reaches `CONNECTED_VERIFIED`.
2. **Import Verified `LIVE` Historical 5m Equity Candles:** Fetch or import multi-session historical 5-minute OHLCV candles (`>= 200` bars across `>= 3` sessions for Strategy 5; complete `09:15–09:25 IST` ORB bars for Strategy 4) via `python .\historical_data.py --import-file <path> --symbol <SYM> --provider angelone --data-mode LIVE`.
3. **Strategy 3 (`Option Apex OI Shift`) Historical Replay Blocker:** Strategy 3 remains blocked (`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`) unless historical 5-minute option-chain snapshots (`oi_snapshots`), validated prior-session closing OI baselines (`CLOSING_BASELINE`), and historical option contract OHLCV bars + lot size metadata are available for the target dates.
4. **Options Margin Modeling Not Invented:** For derivatives, no SPAN/exposure margin model is fabricated; cash equity intraday backtests enforce capital exposure (`quantity * entry_price <= current_equity`), while derivative backtests require explicit historical lot-size metadata.
