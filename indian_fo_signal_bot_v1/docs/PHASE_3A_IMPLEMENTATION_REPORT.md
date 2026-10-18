# TradePulse AI — Phase 3A Implementation Report (`PHASE_3A_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-17  
**Scope:** Phase 3A — Historical Market Data Quality and Backtest Dataset Preparation  
**Baseline Artifact:** `indian_fo_signal_bot_phase2c.zip` (81/81 tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase3a.zip` (89/89 tests passing)  
**Phase 3 Execution Readiness Gate:** **`BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED` (`phase3_ready_for_execution = False`)**


## 1. Pre-Implementation Gate Verification: Phase 2C Live-Data Acceptance Status

Before implementing any Phase 3A modules, `indian_fo_signal_bot_phase2c.zip` was extracted into `/tmp/phase3a_baseline/indian_fo_signal_bot_v1` and verified via `python3 test_bot.py -v` (`81/81` tests passing) and `python3 diagnostics.py --offline`:

```text
Overall Diagnostic Verdict : WARNING
Broker Connection State    : UNAVAILABLE_MISSING_CREDENTIALS
Live Connectivity Verified : NO
SQLite Health & Baselines  : total_baselines=0 (closing_baselines=0, intraday_observations=0, live_closing=0)
Option Apex Readiness      : UNAVAILABLE_NO_SCRIP_MASTER (NIFTY=UNAVAILABLE_NO_SCRIP_MASTER; BANKNIFTY=UNAVAILABLE_NO_SCRIP_MASTER)
```

### 1.1 Gate Verdict
- **Local Phase 2C Live-Data Acceptance Completed?** **NO.** Outbound internet access is disabled in the sandbox VM and no live Angel One credentials (`ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET`), downloaded `OpenAPIScripMaster.json`, or live `CLOSING_BASELINE` records exist in this environment.
- **Phase 3 Backtest Execution Readiness:** **NOT READY (`phase3_ready_for_execution = False`).**
- In strict compliance with the Phase 3A gate rule (*"Before implementing anything, verify whether local Phase 2C live-data acceptance has been completed. If not, prepare an audit and data-quality plan only; do not claim Phase 3 is ready for execution"*):
  1. Phase 3A implements the **historical data-quality audit, dataset schema, provenance tracker, look-ahead guardrails, and resumable/idempotent SQLite dataset import & validation pipeline** (`historical_data.py`, `storage.py`, `server.py`), and **does not implement a historical walk-forward backtest execution engine, performance optimization, or profitability claims**.
  2. `evaluate_phase3a_backtest_readiness()` (`historical_data.py`) and `GET /api/historical-readiness` (`server.py`) programmatically enforce `phase3_ready_for_execution = False` (`overall_gate_status = "BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED"`) until local Phase 2C live connectivity (`CONNECTED_VERIFIED`) and live `LIVE`-mode historical datasets are present.


## 2. Objective 1 — Audit of Existing Candle Retrieval, Timestamp Normalization, Session Calendars, Instrument Metadata & SQLite Storage

| Audited Area | Existing Phase 2C Implementation | Phase 3A Audit Findings & Gaps Resolved |
| :--- | :--- | :--- |
| **1. Candle Retrieval (`brokers.py`)** | `AngelOneSmartAPIAdapter.get_intraday_candles()` (`L1069–L1149`), `DhanHQAdapter.get_intraday_candles()` (`L1546–L1616`), and `UpstoxV2Adapter.get_intraday_candles()` (`L1755–L1817`) retrieve short lookback windows (5 warm-up sessions on Angel One/Dhan; single current session on Upstox v2 intraday) and return transient in-memory lists. | **Gaps found:** (a) Retrieved candles were discarded after `run_single_scan()` with no SQLite table for historical OHLCV bars or dataset provenance. (b) Index spot symbols (`NIFTY`, `BANKNIFTY`) carry `volume = 0` on Angel One (`99926000`, `99926009`), Dhan (`IDX_I`), and Upstox (`NSE_INDEX`), which was not explicitly audited against volume-dependent strategy rules (`RVOL >= 1.4x/1.6x/1.3x` and volume-weighted `VWAP`). |
| **2. Timestamp Normalization (`strategies.py`)** | `parse_ist_timestamp()` (`L60–L118`) normalizes ISO-8601 strings (`Z`, `+00:00`, `+05:30`), Angel One `exchFeedTime` (`DD-MMM-YYYY HH:MM:SS`), and Unix epoch seconds/milliseconds into `Asia/Kolkata` (`IST`). | **Gaps found:** `validate_candles()` verified monotonic non-decreasing timestamps and `09:15–15:30` bounds when called by strategies, but did not validate alignment to the exact NSE 5-minute bar-start grid (`09:15:00`, `09:20:00`, ..., `15:25:00` — 75 bars/day) or reject bars stamped at `15:30:00` (which is session close, not a valid 5m bar start) or off-grid minutes (`10:02:00`, `10:00:15`). Added `validate_bar_timestamp_on_nse_grid()` and `generate_nse_session_bar_timestamps()`. |
| **3. Session Calendars & Holidays (`storage.py`, `brokers.py`)** | `is_nse_trading_day()` (`storage.py` `L69–L81`) and `resolve_nse_session_dates()` (`brokers.py` `L85–L117`) skip Saturdays, Sundays, and dates in `config.configured_holidays` (`NSE_HOLIDAYS`). | **Gaps found:** No function enumerated expected trading sessions across a historical `[start_date, end_date]` range (`list_expected_nse_trading_sessions()`) or audited a multi-day candle dataset to distinguish (a) legitimate weekend/holiday non-trading days, (b) missing full trading sessions, (c) missing intraday 5-minute bars within an active session, and (d) bars erroneously present on a weekend or configured NSE holiday. |
| **4. Instrument Metadata (`config.py`, `brokers.py`)** | `BotConfig` (`config.py` `L73–L115`) defines `fo_indices` (`NIFTY`, `BANKNIFTY`) and 15 NSE equities (`RELIANCE`, `HDFCBANK`, `ICICIBANK`, `INFY`, `TCS`, `LT`, `SBIN`, `AXISBANK`, `KOTAKBANK`, `BHARTIARTL`, `ITC`, `BAJFINANCE`, `M&M`, `TATAMOTORS`, `TATASTEEL`) with static `angel_token`, `dhan_id`, and `upstox_key`. | **Gaps found:** Historical option contracts (`NFO OPTIDX`) expire weekly/monthly and change `symboltoken` every expiry cycle; `OpenAPIScripMaster.json` only lists **currently active** contracts and does not contain expired historical option tokens or historical strike metadata. Documented and enforced in `evaluate_phase3a_backtest_readiness()`. |
| **5. SQLite Storage (`storage.py`)** | `SQLitePersistenceStore` (`storage.py`) persisted 5 tables: `scan_runs`, `signals`, `oi_snapshots`, `mitigated_order_blocks`, and `oi_baselines`. | **Gaps found:** Lacked `historical_datasets` (provenance metadata & SHA-256 dataset checksums) and `historical_candles` (normalized IST OHLCV bars with composite uniqueness, conflict detection, and resumable ingestion watermarks). Added both tables idempotently in `initialize_schema()`. |


## 3. Objective 2 — Historical Dataset Schema, Provenance Specification & Strategy Input Requirements

### 3.1 SQLite Schema for Historical Datasets & Candles (`storage.py`)

`SQLitePersistenceStore.initialize_schema()` adds two new tables with WAL-mode concurrency and parameterized SQL queries:

```sql
CREATE TABLE IF NOT EXISTS historical_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    segment TEXT NOT NULL,
    exchange TEXT NOT NULL,
    instrument_token TEXT NOT NULL,
    interval_min INTEGER NOT NULL,
    from_timestamp_ist TEXT NOT NULL,
    to_timestamp_ist TEXT NOT NULL,
    retrieved_at_ist TEXT NOT NULL,
    source_timestamp_ist TEXT,
    data_mode TEXT NOT NULL,
    is_simulated INTEGER NOT NULL,
    bar_count INTEGER NOT NULL,
    completed_bar_count INTEGER NOT NULL,
    missing_bar_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    zero_volume_bar_count INTEGER NOT NULL,
    Positive_volume_ratio REAL NOT NULL,
    quality_status TEXT NOT NULL,
    transformations_json TEXT NOT NULL,
    quality_summary_json TEXT NOT NULL,
    sha256_checksum TEXT NOT NULL,
    created_at_ist TEXT NOT NULL,
    updated_at_ist TEXT NOT NULL,
    UNIQUE(provider, symbol, interval_min, data_mode, from_timestamp_ist, to_timestamp_ist)
);

CREATE TABLE IF NOT EXISTS historical_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL UNIQUE,
    dataset_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    segment TEXT NOT NULL,
    exchange TEXT NOT NULL,
    instrument_token TEXT NOT NULL,
    interval_min INTEGER NOT NULL,
    candle_timestamp TEXT NOT NULL,
    session_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    open_interest INTEGER NOT NULL DEFAULT 0,
    is_complete INTEGER NOT NULL,
    is_simulated INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_timestamp TEXT,
    retrieved_at_ist TEXT NOT NULL,
    transformations_json TEXT NOT NULL,
    created_at_ist TEXT NOT NULL,
    updated_at_ist TEXT NOT NULL,
    UNIQUE(provider, symbol, interval_min, candle_timestamp, data_mode)
);
```

- **Deterministic Candle `dedup_key`:**
  $$\text{dedup\_key} = \texttt{\{PROVIDER\}:\{SYMBOL\}:\{INTERVAL\_MIN\}m:\{CANDLE\_TIMESTAMP\}:\{DATA\_MODE\}}$$
  Example: `angelone:RELIANCE:5m:2026-10-16 09:15:00:LIVE`
- **Deterministic Dataset `dataset_id`:**
  $$\text{dataset\_id} = \texttt{ds\_\{provider\}\_\{symbol\}\_\{interval\}m\_\{mode\}\_\{sha256[:12]\}}$$

### 3.2 External JSON & CSV Import Schema (`import_historical_candles_file`)

1. **JSON Format (`reliance_5m_live.json`):**
   ```json
   {
     "provider": "angelone",
     "symbol": "RELIANCE",
     "segment": "NSE_EQUITY_INTRADAY",
     "exchange": "NSE",
     "instrument_token": "2885",
     "interval_min": 5,
     "retrieved_at_ist": "2026-10-16 15:35:00",
     "source_timestamp_ist": "2026-10-16 15:25:00",
     "data_mode": "LIVE",
     "transformations": ["ist_normalized", "nse_5m_grid_verified"],
     "candles": [
       {
         "timestamp": "2026-10-16 09:15:00",
         "open": 2940.0,
         "high": 2948.5,
         "low": 2938.0,
         "close": 2945.0,
         "volume": 125400,
         "open_interest": 0,
         "is_complete": true
       }
     ]
   }
   ```

2. **CSV Format (`tcs_5m_live.csv`):**
   ```csv
   timestamp,open,high,low,close,volume,open_interest,provider,symbol,segment,exchange,instrument_token,interval_min,data_mode,retrieved_at_ist,source_timestamp_ist
   2026-10-16 09:15:00,4120.0,4128.0,4115.0,4125.5,84200,0,angelone,TCS,NSE_EQUITY_INTRADAY,NSE,11536,5,LIVE,2026-10-16 15:35:00,2026-10-16 15:25:00
   ```

### 3.3 Genuine Strategy Input Requirements vs Realistic Historical Data Availability (`STRATEGY_HISTORICAL_DATA_REQUIREMENTS`)

| Strategy ID & Name | Target Universe | Minimum Warm-Up Bars | Genuinely Required Inputs (`strategies.py`) | Historical Validation Status & Limitations |
| :--- | :--- | :---: | :--- | :--- |
| **`strat_1_order_block`**<br>Order Block + BOS & FVG Retest | 15 NSE Equities + `NIFTY`/`BANKNIFTY` | `30` completed 5m bars (`>= 1` session) | Completed 5m OHLCV (`open`, `high`, `low`, `close`, `volume`), Wilder `ATR(10)`, session `VWAP`, 15-bar lookback for unmitigated OB/BOS/FVG, and point-in-time `mitigated_zones` registry. | **Ready for 15 NSE Equities** once live 5m OHLCV bars (`>= 30` bars) are imported (`READY`). Note: On `NIFTY`/`BANKNIFTY` index spot tokens (`99926000`/`99926009`), broker `getCandleData` reports `volume=0` (affecting `RVOL` in quality score and switching `compute_session_vwap` to equal-weighted typical price fallback). |
| **`strat_2_vwap_pullback`**<br>Institutional VWAP Pullback | 15 NSE Equities (`NIFTY`/`BANKNIFTY` require traded volume) | `35` completed 5m bars | Completed 5m OHLCV **with positive traded `volume > 0`** (`last["volume"] >= 1.4 * avg_vol_20` where `avg_vol_20 > 0`), session `VWAP`, `EMA(20)`, Wilder `RSI(14)`, Wilder `ATR(10)`. | **Ready for 15 NSE Equities** once live 5m OHLCV bars (`>= 35` bars with positive volume) are imported. **Blocked on Index Spot (`NIFTY`/`BANKNIFTY`)** if index spot candles have `volume=0` (`evaluate_vwap_pullback` explicitly returns `None` when `avg_vol_20 <= 0`). |
| **`strat_3_option_apex_oi`**<br>Option Apex OI Shift + PCR | Strictly `NIFTY` & `BANKNIFTY` F&O | `15` completed 5m bars + **Historical Option Chain + Prior Closing OI** | Underlying 5m bars + **point-in-time historical option chain** at each 5m bar (`atm_strike`, `pcr`, strike-wise `ce_ltp`, `pe_ltp`, `ce_oi`, `pe_oi`, `ce_iv`, `pe_iv`) + **validated `CLOSING_BASELINE` from prior session** (`ce_oi_change`, `pe_oi_change`). | **`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`**. Angel One SmartAPI, DhanHQ, and Upstox REST APIs do **not** provide historical 5-minute option-chain snapshots, expired option contract tokens in current Scrip Master, or historical strike-level OI/LTP/IV series. Current option chains are **never** substituted for historical data. |
| **`strat_4_orb_filtered`**<br>15m Opening Range Breakout | 15 NSE Equities (`NIFTY`/`BANKNIFTY` require traded volume) | `30` completed 5m bars + complete `09:15, 09:20, 09:25 IST` ORB bars | Complete 3-bar `09:15–09:30 IST` Opening Range (`orb_high`, `orb_low`), completed 5m OHLCV **with positive `volume > 0`** (`RVOL >= 1.6x`), session `VWAP`, Wilder `RSI(14)`. | **Ready for 15 NSE Equities** once live 5m OHLCV bars (`>= 30` bars, positive volume, complete `09:15–09:25` ORB bars) are imported. **Blocked on Index Spot** when index spot candles report `volume=0`. |
| **`strat_5_supertrend_pullback`**<br>Supertrend (10,3) + 200 EMA | 15 NSE Equities (`NIFTY`/`BANKNIFTY` require traded volume) | **`200` completed 5m bars** (`>= 3` prior 75-bar NSE sessions) | `>= 200` completed 5m OHLCV bars **with positive `volume > 0`** (`last["volume"] >= 1.3 * avg_vol_20`), `EMA(200)`, `Supertrend(10, 3.0)`, session `VWAP`, Wilder `ATR(10)`, chop-window filter (`09:45–11:30` & `13:30–15:25 IST`). | **Ready for 15 NSE Equities** once `>= 200` completed live 5m OHLCV bars with positive volume are imported; reports `INSUFFICIENT_WARMUP_BARS` (`< 200` bars) or `ZERO_VOLUME_INDEX_SERIES` when `volume == 0`. |


## 4. Objectives 3, 4 & 5 — IST Grid Validation, Gap/Holiday Auditing, Provenance & Look-Ahead Prevention

### 4.1 IST Timestamp Grid, Holiday & Missing-Bar Rules (`historical_data.py`)
1. **Strict IST Normalization:** Every bar timestamp is parsed via `parse_ist_timestamp()` and formatted as `"YYYY-MM-DD HH:MM:SS"` in `Asia/Kolkata` (`IST`, UTC+05:30).
2. **NSE 5-Minute Session Grid (`validate_bar_timestamp_on_nse_grid`):**
   - For `interval_min = 5`, valid NSE bar start times run from `09:15:00 IST` (covering `09:15:00–09:19:59`) to `15:25:00 IST` (covering `15:25:00–15:29:59`), totaling exactly **75 bars per complete NSE trading session**.
   - Any bar stamped at `15:30:00 IST` (session close boundary), before `09:15:00 IST`, after `15:25:00 IST`, with non-zero seconds (`10:05:30`), or on an off-grid minute (`10:02:00`) raises `HistoricalDataValidationError`.
   - Any bar stamped on a Saturday, Sunday, or a date in `configured_holidays` (`NSE_HOLIDAYS`) raises `HistoricalDataValidationError`.
3. **Missing Bars & Gap Auditing Without Fabrication (`validate_and_prepare_historical_dataset`):**
   - Computes expected trading sessions via `list_expected_nse_trading_sessions(first_date, last_date, configured_holidays)` (automatically excluding weekends and configured NSE holidays).
   - Audits every observed session against the 75-bar 5m grid and records `missing_sessions`, `missing_bar_count`, `missing_bars_sample`, `orb_complete_sessions` (whether all three `09:15, 09:20, 09:25 IST` Opening Range bars exist), and `session_coverage_pct` in `quality_summary`.
   - **Zero Fabrication Rule:** Missing bars are **never** interpolated, forward-filled, or synthesized. Datasets with missing bars are explicitly tagged `quality_status = "VALID_WITH_GAPS"`.
4. **Duplicate Detection & Malformed OHLCV Rejection:**
   - **Exact Identical Duplicates:** Coalesced idempotently and counted in `duplicate_count` with transformation tag `"deduplicated_exact_bars"`.
   - **Conflicting Duplicates:** Two records with the same `timestamp` but different `open`, `high`, `low`, `close`, `volume`, or `open_interest` raise `HistoricalDataValidationError` (`"Conflicting duplicate candle timestamp..."`).
   - **Malformed OHLCV Rejection:** Non-numeric, boolean, `NaN`/`Inf`, `<= 0` prices, negative volume/OI, `high < max(open, close)`, `low > min(open, close)`, or `high < low` raise `HistoricalDataValidationError`.

### 4.2 Look-Ahead Bias Prevention (`historical_data.py`)
1. **Completed vs Forming Bar Separation (`get_point_in_time_candle_slice`):**
   - At any backtest decision timestamp $T_{\text{decision}}$ (in IST), a candle with start timestamp $T_{\text{bar}}$ and interval $\Delta t$ minutes is included **if and only if**:
     $$T_{\text{bar}} + \Delta t \le T_{\text{decision}} \quad \text{and} \quad \texttt{is\_complete} = \texttt{True}$$
   - Example: At `10:04:59 IST`, the `10:00:00 IST` 5-minute bar (`10:00–10:05 IST`) is still forming (`10:05:00 > 10:04:59`) and is **excluded**; the latest visible bar is `09:55:00 IST`. Only at `10:05:00 IST` does the `10:00:00 IST` bar become visible.
2. **Look-Ahead Audit Guard (`verify_no_lookahead_leakage`):**
   - Verifies that every bar in a strategy evaluation slice satisfies `bar_close_time <= decision_time_ist` and `is_complete is True`, raising `LookAheadBiasError` on any violation.
3. **Point-in-Time Market Breadth (`compute_point_in_time_universe_breadth`):**
   - Computes `{"advances": int, "declines": int}` across the universe using **only** completed bars on the active `session_date` with `bar_end <= decision_time_ist`, preventing end-of-day breadth from leaking into morning signal scoring.


## 5. Objective 6 — Realistic Historical Options Data Limitations

1. **Lack of Historical Intraday Option-Chain Snapshots on Broker REST APIs:**
   - Angel One SmartAPI (`/rest/secure/angelbroking/market/v1/quote/`, `/marketData/v1/optionGreek`, `/marketData/v1/putCallRatio`), DhanHQ (`/v2/optionchain`), and Upstox (`/v2/option/chain`) return **live point-in-time** snapshots for currently active contracts only; none of these endpoints accept a historical timestamp parameter to replay past 5-minute option chains.
2. **Expired Option Contract Token Turnover in `OpenAPIScripMaster.json`:**
   - Weekly and monthly `NIFTY` and `BANKNIFTY` option contracts expire and are purged from `OpenAPIScripMaster.json` after expiry day. Consequently, historical `symboltoken` identifiers for expired strikes cannot be resolved from a current Scrip Master download.
3. **Why Strategy 3 (`Option Apex OI Shift`) Remains Blocked for Historical Backtesting:**
   - Strategy 3 requires simultaneous historical 5m underlying spot/VWAP, strike-level Call/Put LTP (`ce_ltp`, `pe_ltp`), strike-level Call/Put Open Interest (`ce_oi`, `pe_oi`), aggregate `PCR`, and validated prior-session closing OI (`CLOSING_BASELINE` `ce_prev_oi`, `pe_prev_oi`).
   - Rather than substituting synthetic option chains or pretending current option-chain snapshots are historical data, TradePulse Phase 3A explicitly marks `strat_3_option_apex_oi` as **`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`** unless verified historical `oi_snapshots` and `CLOSING_BASELINE` rows covering the target backtest dates have been captured and persisted in SQLite.


## 6. Objective 7 — Resumable, Idempotent Storage/Import Workflows & Windows PowerShell Instructions

### 6.1 Resumable & Idempotent SQLite Workflow (`storage.py`)
- **`save_historical_candle_dataset()`:**
  - Wraps dataset + candle persistence in an atomic SQLite transaction (`with self._db_lock:`, `with conn:`).
  - Re-importing the exact same candles is an **idempotent no-op** (`inserted=0`, `unchanged=N`, `updated=0`).
  - Importing an extended date range (e.g., resuming after Session 1 to add Session 2) inserts only the newly added bars (`inserted=75`, `unchanged=75`) and advances the watermark.
  - Importing a conflicting OHLCV bar for an existing `(provider, symbol, interval_min, candle_timestamp, data_mode)` with `allow_overwrite=False` aborts the entire batch (`ROLLBACK`) and raises `PersistenceValidationError`.
- **`get_historical_ingestion_watermark()`:**
  - Returns `earliest_candle_timestamp_ist`, `latest_candle_timestamp_ist`, `next_resume_from_timestamp_ist` (`latest + interval_min`), `total_bars`, `completed_bars`, and `distinct_sessions` so interrupted historical downloads can resume from `next_resume_from_timestamp_ist`.

### 6.2 Windows PowerShell Commands for Phase 3A

1. **Extract `indian_fo_signal_bot_phase3a.zip` and verify compilation + all 89 unit tests:**
   ```powershell
   Expand-Archive -Path .\indian_fo_signal_bot_phase3a.zip -DestinationPath .\tradepulse_phase3a -Force
   Set-Location .\tradepulse_phase3a\indian_fo_signal_bot_v1
   Copy-Item .\.env.example .\.env -Force
   python -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py diagnostics.py historical_data.py test_bot.py
   python .\test_bot.py -v
   ```

2. **Check Phase 3A Historical Data Quality & Backtest Readiness Gate (CLI):**
   ```powershell
   python .\historical_data.py --readiness --data-mode LIVE
   python .\historical_data.py --readiness --data-mode LIVE --json
   ```

3. **Import a Historical 5m Candle Dataset (`.json` or `.csv`) with Provenance & Grid Validation:**
   ```powershell
   python .\historical_data.py --import-file .\reliance_5m_live.json --symbol RELIANCE --provider angelone --data-mode LIVE
   ```

4. **Check Resumable Ingestion Watermark for a Symbol:**
   ```powershell
   python .\historical_data.py --watermark --symbol RELIANCE --provider angelone --data-mode LIVE
   ```

5. **Inspect HTTP Endpoints (`GET /api/historical-datasets` and `GET /api/historical-readiness`):**
   ```powershell
   python .\server.py
   # In a second PowerShell window:
   Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/historical-readiness?data_mode=LIVE" | ConvertTo-Json -Depth 6
   Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/historical-datasets?data_mode=LIVE" | ConvertTo-Json -Depth 6
   ```


## 7. Changed & Added Files Summary

| File Path | Action | Summary of Changes |
| :--- | :--- | :--- |
| `historical_data.py` | **Added** | Historical market data quality validator, NSE 5m session grid/holiday auditor, provenance builder, point-in-time look-ahead prevention (`get_point_in_time_candle_slice`, `verify_no_lookahead_leakage`, `compute_point_in_time_universe_breadth`), strategy readiness evaluator (`evaluate_phase3a_backtest_readiness`), and CLI (`--readiness`, `--import-file`, `--watermark`). |
| `storage.py` | **Updated** | Added `historical_datasets` and `historical_candles` tables and indexes; added `save_historical_candle_dataset()`, `import_historical_candles_file()`, `get_historical_ingestion_watermark()`, `query_historical_datasets()`, and `query_historical_candles()`; added `historical_datasets_count`, `historical_candles_count`, and `historical_live_candles_count` to `check_health()`. |
| `server.py` | **Updated** | Added read-only `GET /api/historical-datasets` (`/api/v1/historical-datasets`) and `GET /api/historical-readiness` (`/api/v1/historical-readiness`) endpoints while keeping `historical_data.py` blocked from static HTTP disclosure (`404 Not Found`) and preserving all Phase 1A–2C routes. |
| `test_bot.py` | **Updated** | Preserved all 81 Phase 1A–2C tests and added `TestIndianFOSignalBotPhase3A` (8 new deterministic test suites, bringing total to **89 passing tests**). |
| `README.md` | **Updated** | Added Phase 3A historical dataset schema, provenance specification, look-ahead prevention rules, and Windows PowerShell instructions. |
| `docs/PHASE_3A_IMPLEMENTATION_REPORT.md` | **Added** | Complete Phase 3A gate verification, audit, dataset schema, strategy input matrix, options data limitations, and 89-test verification report. |


## 8. Four-Way Verification Separation Matrix

| Capability / Component | Functionality Implemented in Code | Mocked Automated Tests Passed (`test_bot.py`) | Real Historical / Live Data Actually Obtained in Sandbox | Historical Inputs Still Unavailable / Blocked |
| :--- | :---: | :---: | :---: | :--- |
| **1. Phase 2C Live-Data Acceptance Gate Check (`evaluate_phase3a_backtest_readiness`)** | Yes (`historical_data.py`, `server.py`) | Yes (`test_p3a_phase2c_gate_strategy3_option_apex_blocked_and_http_security`) | **None** (`UNAVAILABLE_MISSING_CREDENTIALS` in sandbox VM) | Local Windows execution of `python .\diagnostics.py` with live Angel One credentials required before Phase 3 execution is unblocked. |
| **2. NSE 5m Session Grid (`09:15–15:25 IST`), Weekend & Holiday Boundary Validation** | Yes (`historical_data.py`) | Yes (`test_p3a_timestamp_boundaries_grid_alignment_weekends_and_holidays`) | N/A (Deterministic Calendar & Grid Validator) | Official NSE holiday dates must be supplied via `NSE_HOLIDAYS` in `.env`. |
| **3. Missing-Bar & Missing-Session Audit Without Data Fabrication** | Yes (`historical_data.py`) | Yes (`test_p3a_missing_bars_audit_and_multi_session_gap_detection`) | **None** (Tested on deterministic fixtures) | Real multi-session historical 5m candles for NIFTY, BANKNIFTY, and 15 NSE equities must be fetched/imported locally. |
| **4. Duplicate Coalescing vs Conflicting Duplicate Rejection & Malformed OHLCV Rejection** | Yes (`historical_data.py`, `storage.py`) | Yes (`test_p3a_duplicate_bars_idempotent_coalescing_and_conflict_rejection`, `test_p3a_malformed_ohlcv_records_and_zero_volume_index_audit`) | N/A (Deterministic Data Quality Control) | Index spot tokens (`NIFTY`, `BANKNIFTY`) report `volume = 0`, blocking volume-dependent RVOL rules (`strat_2`, `strat_4`, `strat_5`) on spot indices unless futures volume is supplied. |
| **5. Point-in-Time Candle Slicing & Look-Ahead Bias Prevention (`get_point_in_time_candle_slice`)** | Yes (`historical_data.py`) | Yes (`test_p3a_forming_candles_and_strict_point_in_time_lookahead_prevention`) | N/A (Deterministic Look-Ahead Guard) | None for OHLCV strategies (`strat_1`, `strat_2`, `strat_4`, `strat_5`). |
| **6. Resumable, Idempotent SQLite Dataset Storage, Watermarks & JSON/CSV Import** | Yes (`storage.py`, `historical_data.py`) | Yes (`test_p3a_resumable_idempotent_storage_json_csv_import_and_watermark`) | N/A (Local SQLite Persistence) | None. |
| **7. Strict `LIVE` vs `SIMULATED` Dataset Mode Isolation** | Yes (`storage.py`, `historical_data.py`) | Yes (`test_p3a_data_mode_isolation_between_live_and_simulated_datasets`) | N/A (Local SQLite Isolation) | `SIMULATED` datasets can never satisfy `LIVE` backtest readiness. |
| **8. Strategy 3 (`Option Apex OI Shift`) Historical Validation Gate** | Yes (`historical_data.py`) | Yes (`test_p3a_phase2c_gate_strategy3_option_apex_blocked_and_http_security`) | **None** | **Blocked (`BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN`)**: Historical 5m option-chain snapshots, expired contract tokens, strike LTP/IV/OI, and prior-session closing OI baselines are not available from broker REST candle endpoints. |


## 9. Compilation & Full-Suite Test Execution Results

### 9.1 Python Bytecode Compilation
```bash
python3 -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py diagnostics.py historical_data.py test_bot.py
```
Result: **Exit code `0`** across all 10 Python modules with zero warnings or errors.

### 9.2 Full 89-Test Suite Execution (`test_bot.py`)
```bash
python3 test_bot.py -v
```
- **Total Tests Executed:** `89` (`20` Phase 1A + `11` Phase 1B + `8` Phase 1C + `11` Phase 1D + `3` Phase 1E + `4` Phase 1F + `8` Phase 2A + `8` Phase 2B + `8` Phase 2C + `8` Phase 3A)
- **Passed:** `89`
- **Failed:** `0`
- **Skipped:** `0`
- **Execution Time:** `21.513s` (`OK`)
