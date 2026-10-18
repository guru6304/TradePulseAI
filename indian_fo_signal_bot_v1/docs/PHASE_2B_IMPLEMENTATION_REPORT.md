# TradePulse AI — Phase 2B Implementation Report (`PHASE_2B_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-17  
**Scope:** Phase 2B — Persistent Option Apex OI Baselines and Live-Data Reliability  
**Baseline Artifact:** `indian_fo_signal_bot_phase2a.zip` (65/65 tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase2b.zip` (73/73 tests passing)


## 1. Step 1 — Pre-Implementation Audit of Phase 2A Baseline

### 1.1 Baseline Inspection & Test Verification
Extracting `indian_fo_signal_bot_phase2a.zip` into `/tmp/phase2b_baseline/indian_fo_signal_bot_v1` and running `python3 test_bot.py -v` confirmed **65 passing tests (`0` failed, `0` skipped)** across `config.py`, `brokers.py`, `strategies.py`, `storage.py`, `scanner_engine.py`, `telegram_bot.py`, `server.py`, `public/index.html`, and `test_bot.py`.

### 1.2 Trace of OI Snapshot & Baseline Flow in Phase 2A
Tracing the Phase 2A baseline across `brokers.py`, `storage.py`, `scanner_engine.py`, `config.py`, `server.py`, and `public/index.html` revealed the exact root causes preventing Strategy 3 (`Option Apex OI Shift`, `strat_3_option_apex_oi`) from operating after an application restart when `ACTIVE_BROKER=angelone`:

1. **In-Memory-Only `self._prior_oi_baseline` Dict (`brokers.py` L250, L641–L664):**
   - `AngelOneSmartAPIAdapter.__init__()` initialized `self._prior_oi_baseline: Dict[Tuple[str, str], Dict[int, Dict[str, int]]] = {}` purely in volatile process memory.
   - `AngelOneSmartAPIAdapter.set_prior_oi_baseline(index_symbol, expiry, strike_baseline)` validated and populated `self._prior_oi_baseline[(sym, exp_str)]` in memory, but **never persisted baseline records to SQLite (`storage.py`)** and **never restored baseline records on startup**.
   - `IntradayBotEngine` (`scanner_engine.py` L85–L96) restored `mitigated_order_blocks` from `SQLitePersistenceStore` on startup, but never called `set_prior_oi_baseline()` or attached `self.store` to `self.broker`.
   - Consequently, on every application restart (or fresh `IntradayBotEngine` instantiation), `self._prior_oi_baseline` was empty (`{}`). When `IntradayBotEngine.run_single_scan()` called `self.broker.fetch_option_chain("NIFTY")`, `AngelOneSmartAPIAdapter.get_option_chain()` (`brokers.py` L703–L715) found `prior_map is None` and raised `UnsupportedBrokerCapabilityError`.

2. **Schema Gap Between `oi_snapshots` and True Prior-Session OI Baselines (`storage.py` L161–L184, L367–L550):**
   - `oi_snapshots` stores full option-chain snapshots (`strikes_json`) captured during a scan and computes `intraday_oi_diff` (`VALID_INTRADAY_DIFF`, `NO_PRIOR_SNAPSHOT`, `STALE_PRIOR_SNAPSHOT`) by comparing a snapshot against an earlier snapshot from the **same IST session date** within `max_snapshot_age_minutes=60`.
   - However, `oi_snapshots` can only be saved **after** `get_option_chain()` succeeds (`scanner_engine.py` L224–L231), which already required `ce_oi_change` and `pe_oi_change` to be present on every strike row!
   - Furthermore, Strategy 3 (`evaluate_option_apex_oi_shift`) requires **previous trading session's closing OI (`ce_prev_oi` / `pe_prev_oi`)** to compute cumulative session net OI change (`ce_oi_change = ce_oi - ce_prev_oi`, `pe_oi_change = pe_oi - pe_prev_oi`), whereas `intraday_oi_diff` measures short-horizon rolling intraday change between two snapshots on the **same** trading day.

3. **Scrip Master Re-Parsing & Refresh Hazards (`brokers.py` L440–L525, L695–L696):**
   - `AngelOneSmartAPIAdapter.load_scrip_master()` parsed NFO `OPTIDX` rows into `self._scrip_master_options`, but did not track file modification time (`mtime`), file age, or load status diagnostics (`get_scrip_master_status()`), and did not reject non-empty Scrip Master files that contained zero valid `NIFTY`/`BANKNIFTY` `OPTIDX` contracts.
   - `get_option_chain()` only auto-loaded `angel_scrip_master_path` if `not self._scrip_master_options`, without a safe refresh mechanism (`refresh_scrip_master_safely()`) that validates a newly downloaded candidate file before replacing active in-memory contracts.

4. **Lack of Option Apex & Scrip Master Readiness Diagnostics in `/api/health` and UI (`scanner_engine.py` L103–L151, `public/index.html`):**
   - `get_broker_status()` reported `connection_state`, `data_mode`, and `connectivity_verified`, but did not report `scrip_master` status (`LOADED_FRESH`, `LOADED_STALE`, `NOT_CONFIGURED`, `MISSING_FILE`, `CORRUPT_FILE`) or per-index `option_apex` readiness (`READY`, `SIMULATED_READY`, `UNAVAILABLE_NO_SCRIP_MASTER`, `UNAVAILABLE_NO_PRIOR_BASELINE`, `UNAVAILABLE_STALE_BASELINE`, `UNAVAILABLE_INCOMPLETE_PAIRS`, `UNAVAILABLE_EXPIRED_CONTRACT`).


## 2. Database Schema & Migration Details (`storage.py`)

### 2.1 New `oi_baselines` Table & Index (`initialize_schema`)
`SQLitePersistenceStore.initialize_schema()` uses idempotent `CREATE TABLE IF NOT EXISTS` statements, so existing Phase 1D–2A SQLite database files (`tradepulse_phase1d.db`) automatically migrate on startup without data loss:

```sql
CREATE TABLE IF NOT EXISTS oi_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL UNIQUE,
    index_symbol TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike INTEGER NOT NULL,
    option_type TEXT NOT NULL,
    open_interest INTEGER NOT NULL,
    source TEXT NOT NULL,
    observation_timestamp TEXT NOT NULL,
    session_date TEXT NOT NULL,
    is_simulated INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    created_at_ist TEXT NOT NULL,
    updated_at_ist TEXT NOT NULL,
    UNIQUE(index_symbol, expiry, strike, option_type, session_date, data_mode)
);

CREATE INDEX IF NOT EXISTS idx_oi_baselines_lookup
ON oi_baselines (index_symbol, expiry, data_mode, session_date DESC, strike ASC);
```

### 2.2 Stable Unique Key & Idempotent Write Semantics
- **Deterministic `dedup_key`:**
  $$\text{dedup\_key} = \texttt{\{INDEX\_SYMBOL\}:\{EXPIRY\}:\{STRIKE\}:\{OPTION\_TYPE\}:\{SESSION\_DATE\}:\{DATA\_MODE\}}$$
  Example: `NIFTY:2026-10-22:24800:CE:2026-10-15:LIVE`
- **Idempotency & Conflict Detection (`save_oi_baseline_records`):**
  - Within a single batch call, duplicate keys with the **exact same** `open_interest` are coalesced idempotently, while duplicate keys with **conflicting** `open_interest` values abort the transaction (`ROLLBACK`) and raise `PersistenceValidationError`.
  - Against existing rows in SQLite:
    - If a row with the same `(index_symbol, expiry, strike, option_type, session_date, data_mode)` already exists with the **same** `open_interest`, `save_oi_baseline_records()` returns `"unchanged"` (`idempotent_no_op`) without duplicating rows.
    - If `allow_overwrite=False` (used when loading immutable external prior-session baselines), an existing row with a **different** `open_interest` raises `PersistenceValidationError` and rolls back the entire batch.
    - If `allow_overwrite=True` (used when updating current-session end-of-day baseline observations during progressive intraday scans), the existing row is updated in place (`UPDATE oi_baselines SET open_interest = ?, ...`).

### 2.3 Strict Separation of Previous-Session OI vs Rolling Intraday OI Changes
- **Previous-Session OI (`oi_baselines` $\rightarrow$ `ce_prev_oi` / `pe_prev_oi`):**
  - Stored in `oi_baselines` by `session_date` (`YYYY-MM-DD`).
  - `load_prior_session_oi_baseline()` selects only baselines where `session_date < effective_current_session_date` (strictly prior trading session) and `data_mode` matches (`LIVE` vs `SIMULATED`).
  - Used by `AngelOneSmartAPIAdapter.get_option_chain()` to compute `ce_oi_change = ce_oi - ce_prev_oi` and `pe_oi_change = pe_oi - pe_prev_oi` (`oi_change_measure = "net_change_from_prior_session_baseline"`), which Strategy 3 (`evaluate_option_apex_oi_shift`) requires.
- **Rolling Intraday OI Change (`oi_snapshots` $\rightarrow$ `intraday_oi_diff`):**
  - Stored in `oi_snapshots` by `snapshot_timestamp` (`YYYY-MM-DD HH:MM:SS`).
  - `_compute_intraday_oi_diff()` compares only snapshots captured on the **same** `session_date` within `60` minutes (`VALID_INTRADAY_DIFF`).
  - The two measures are never substituted for one another.


## 3. Changed Files Summary

| File Path | Action | Summary of Changes |
| :--- | :--- | :--- |
| `config.py` | **Updated** | Added `angel_scrip_master_max_age_hours` (default `24.0`) and `angel_baseline_max_sessions_age` (default `1`), validated both in `BotConfig.validate()`, and exposed them in `BotConfig.to_safe_dict()`. |
| `storage.py` | **Updated** | Added `oi_baselines` table and `idx_oi_baselines_lookup` index; added NSE trading-session calendar helpers (`is_nse_trading_day`, `resolve_effective_trading_session_date`, `resolve_prior_trading_session_date`, `count_trading_sessions_between`); implemented `compute_oi_baseline_dedup_key()`, `save_oi_baseline_records()`, `save_paired_strike_baselines()`, `load_prior_session_oi_baseline()`, and `query_oi_baselines()`; added `oi_baselines_count` to `check_health()`. |
| `brokers.py` | **Updated** | Upgraded `AngelOneSmartAPIAdapter` with `persistence_store` attachment, Scrip Master schema validation & caching (`_parse_and_validate_scrip_master_records`, `load_scrip_master`, `ensure_scrip_master_loaded`, `refresh_scrip_master_safely`, `get_scrip_master_status`), persistent baseline lifecycle (`set_prior_oi_baseline`, `restore_prior_oi_baseline_from_store`, `restore_all_baselines_from_store`, `get_option_apex_readiness`), and automatic baseline restoration in `get_option_chain()`. Added `MultiBrokerScanner.attach_persistence_store()`. |
| `scanner_engine.py` | **Updated** | Connected `self.store` to `self.broker` on startup and before each scan; restored persisted prior-session OI baselines automatically; persisted verified current-session strike OI observations into `oi_baselines` during scans; enriched `get_broker_status()` with `scrip_master` and per-index `option_apex` diagnostics. |
| `server.py` | **Updated** | Added `GET /api/oi-baselines` (and `/api/v1/oi-baselines`) with query validation (`index_symbol`, `expiry`, `session_date`, `data_mode`, `limit`, `offset`) while preserving all existing routes and security controls. |
| `public/index.html` | **Updated** | Added `#optionApexCapabilityBanner` in Tab 2 (`Option Apex`), `renderOptionApexCapabilityBanner()`, `getOiBaselines()` on `TradePulseApiClient`, and Option Apex / Scrip Master / `OI Baselines` diagnostic rows in Tab 4 (`System Health`). |
| `.env.example` | **Updated** | Added `ANGEL_SCRIP_MASTER_MAX_AGE_HOURS=24` and `ANGEL_BASELINE_MAX_SESSIONS_AGE=1` placeholders. |
| `test_bot.py` | **Updated** | Preserved all 65 Phase 1A–2A tests and added `TestIndianFOSignalBotPhase2B` (8 new regression test suites, bringing total to **73 passing tests**). |
| `README.md` | **Updated** | Added Phase 2B persistent OI baseline lifecycle, Scrip Master refresh procedure, and exact Windows PowerShell commands. |
| `docs/PHASE_2B_IMPLEMENTATION_REPORT.md` | **Added** | Complete Phase 2B audit, database schema/migration guide, verification separation matrix, test results, and PowerShell operational guide. |


## 4. Verification Status Separation Matrix

Every capability is explicitly separated across **Implemented in code**, **Verified by mocked tests**, and **Verified against the real broker API**:

| Capability / Component | Implemented in Code | Verified by Mocked Tests (`test_bot.py`) | Verified Against Real Broker API | Notes / Remaining Limitations |
| :--- | :---: | :---: | :---: | :--- |
| **`oi_baselines` SQLite Schema, Idempotent Upserts & Conflict Rejection** | Yes | Yes (`test_p2b_idempotent_baseline_writes_and_duplicate_conflict_rejection`) | N/A (Local SQLite) | Enforces composite `UNIQUE(index_symbol, expiry, strike, option_type, session_date, data_mode)` with parameterized SQL and atomic rollback on conflict. |
| **Persist & Restore Prior-Session OI Baselines Across Application Restart** | Yes | Yes (`test_p2b_persist_and_restore_oi_baselines_across_restart_and_option_apex_signal`) | No | Restores validated prior-session baselines on startup and before `get_option_chain()`, enabling Strategy 3 (`Option Apex`) across restarts. |
| **Complete CE/PE Pairing & Expiry Mismatch Rejection** | Yes | Yes (`test_p2b_ce_pe_pairing_and_expiry_mismatch_rejection`) | No | Rejects incomplete strike pairs (`missing_pe` / `missing_ce`), expired contracts, and mismatched expiries with explicit errors/statuses. |
| **Stale, Future-Dated & Weekend/Holiday Session-Date Validation** | Yes | Yes (`test_p2b_stale_missing_future_dated_and_weekend_holiday_baselines`) | No | Rejects future observation timestamps, same-day baselines masquerading as prior-session baselines, and baselines older than `angel_baseline_max_sessions_age` trading sessions while honoring weekends and `NSE_HOLIDAYS`. |
| **Previous-Session OI vs Rolling Intraday OI Semantics & `LIVE`/`SIMULATED` Isolation** | Yes | Yes (`test_p2b_previous_session_vs_intraday_oi_semantics_and_mode_isolation`) | No | `SIMULATED` baselines can never satisfy `LIVE` Angel One scans (and vice versa). |
| **Scrip Master Validation, Mtime Caching & Atomic Safe Refresh** | Yes | Yes (`test_p2b_scrip_master_validation_corruption_caching_and_safe_refresh`) | No | Corrupt downloads or malformed JSON files are rejected by `refresh_scrip_master_safely()` without overwriting the active valid Scrip Master. |
| **SQLite Transaction Rollback & Multi-Threaded Concurrent Access** | Yes | Yes (`test_p2b_sqlite_transaction_rollback_and_concurrent_baseline_access`) | N/A (Local SQLite) | Verified with 12 concurrent reader/writer threads under `threading.RLock()` and WAL mode. |
| **Scanner Resilience (Strategies 1, 2, 4, 5 Continue When Option Apex Unavailable) & Dashboard Diagnostics** | Yes | Yes (`test_p2b_scanner_resilience_dashboard_health_api_and_security_controls`) | No | Live broker verification requires running with real Angel One credentials on the user's local machine. |


## 5. Compilation & Test Suite Execution Results

### 5.1 Python Bytecode Compilation Check
```bash
python3 -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py test_bot.py
```
Result: **Exit code `0`** across all 8 Python modules.

### 5.2 Complete 73-Test Suite Execution (`test_bot.py`)
```bash
python3 test_bot.py -v
```
- **Total Tests Executed:** `73` (`20` Phase 1A + `11` Phase 1B + `8` Phase 1C + `11` Phase 1D + `3` Phase 1E + `4` Phase 1F + `8` Phase 2A + `8` Phase 2B)
- **Passed:** `73`
- **Failed:** `0`
- **Skipped:** `0`
- **Execution Time:** `21.175s` (`OK`)


## 6. Documented Scrip Master & Baseline Operational Procedure (Windows PowerShell)

1. **Extract `indian_fo_signal_bot_phase2b.zip` and initialize `.env`:**
   ```powershell
   Expand-Archive -Path .\indian_fo_signal_bot_phase2b.zip -DestinationPath .\tradepulse_phase2b -Force
   Set-Location .\tradepulse_phase2b\indian_fo_signal_bot_v1
   Copy-Item .\.env.example .\.env -Force
   ```

2. **Compile and run the 73-test regression suite offline:**
   ```powershell
   python -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py test_bot.py
   python .\test_bot.py -v
   ```

3. **Download and safely refresh `OpenAPIScripMaster.json` locally (without overwriting a valid file if a download is corrupt):**
   ```powershell
   Invoke-WebRequest -Uri "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json" -OutFile ".\OpenAPIScripMaster.candidate.json"
   python -c "from config import BotConfig; from brokers import AngelOneSmartAPIAdapter; cfg = BotConfig(angel_scrip_master_path='OpenAPIScripMaster.json'); a = AngelOneSmartAPIAdapter(cfg); print(a.refresh_scrip_master_safely('OpenAPIScripMaster.candidate.json', target_path='OpenAPIScripMaster.json'))"
   ```

4. **Understand how Persistent OI Baselines accumulate across sessions:**
   - **Day 1 (First Live Session with Angel One + Scrip Master):** When you run scans during Day 1 without a prior-session baseline in SQLite, `GET /api/health` reports `option_apex.status = "UNAVAILABLE_NO_PRIOR_BASELINE"` (`NIFTY:UNAVAILABLE_NO_PRIOR_BASELINE`, `BANKNIFTY:UNAVAILABLE_NO_PRIOR_BASELINE`). Strategies 1, 2, 4, and 5 still run normally on live Angel One candles. To seed a baseline on Day 1 from an external EOD bhavcopy/snapshot or after capturing Day 1's closing OI, call `set_prior_oi_baseline(..., persist=True)` or `store.save_paired_strike_baselines(...)`.
   - **Day 2+ (Subsequent Trading Sessions & Across Restarts):** Whenever a valid option chain is assembled during a session, `IntradayBotEngine` automatically persists the current session's strike-level CE/PE open interest into `oi_baselines` (`source="angelone_live_scan_snapshot"`, `data_mode="LIVE"`). On the next trading day (including across weekends, configured `NSE_HOLIDAYS`, and application restarts), `IntradayBotEngine` and `AngelOneSmartAPIAdapter` automatically restore the prior trading session's closing OI baseline from SQLite before assembling the option chain, transitioning `option_apex.status` to `"READY"`.


## 7. Remaining Limitations

1. **Real Broker API Not Verified in Sandbox VM:** Outbound network access is disabled in the development sandbox VM and no real credentials are included. All Angel One SmartAPI endpoints, Scrip Master loaders, and SQLite baseline lifecycles are verified via deterministic mocked tests (`73/73` passing) and have **not** been verified against the live Angel One production server in this environment.
2. **Cold-Start Prior-Session Baseline Requirement:** Because Angel One's `/rest/secure/angelbroking/market/v1/quote/` endpoint reports only current `opnInterest` and does not provide `previous_oi`, a cold-start installation on Day 1 with an empty `oi_baselines` table cannot compute previous-session OI changes until either (a) a prior-session baseline is imported into `oi_baselines` or (b) one prior session's OI observations have been recorded in `oi_baselines`. Until then, Option Apex (`strat_3_option_apex_oi`) explicitly reports `UNAVAILABLE_NO_PRIOR_BASELINE` and never fabricates zero baselines.
3. **Read-Only Scope Only:** Order execution, modification, cancellation, and GTT rule mutations are blocked in code (`/rest/secure/angelbroking/order/*` and `/gtt/*` raise `BrokerDataError`) and are out of scope for Phase 2B.
