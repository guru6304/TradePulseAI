# TradePulse AI — Phase 2C Implementation Report (`PHASE_2C_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-17  
**Scope:** Phase 2C — Angel One Live-Data Acceptance and Operational Validation  
**Baseline Artifact:** `indian_fo_signal_bot_phase2b.zip` (73/73 tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase2c.zip` (81/81 tests passing)

---

## 1. Step 1 — Pre-Change Audit of Phase 2B Baseline

### 1.1 Baseline Inspection & Test Verification
Extracting `indian_fo_signal_bot_phase2b.zip` and running `python3 test_bot.py -v` confirmed **73 passing tests (`0` failed, `0` skipped)** across `config.py`, `brokers.py`, `strategies.py`, `storage.py`, `scanner_engine.py`, `telegram_bot.py`, `server.py`, `public/index.html`, and `test_bot.py`.

### 1.2 Live-Data Path Trace & Audit Findings Across Phase 2B Modules

Tracing the live-data path from authentication (`AngelOneSmartAPIAdapter.authenticate`) through quote/candle retrieval (`get_quotes`, `get_intraday_candles`), signal evaluation (`IntradayBotEngine.run_single_scan`), OI baseline restoration (`restore_prior_oi_baseline_from_store`), and dashboard health reporting (`GET /api/health`, `public/index.html`) revealed four concrete gaps that needed to be resolved before live-data acceptance:

1. **Critical OI-Baseline Provenance Flaw — Intraday Snapshots Promoted to Closing Baselines (`brokers.py` L1315–L1328, `scanner_engine.py` L325–L347, `storage.py` L695–L796):**
   - In Phase 2B, whenever `AngelOneSmartAPIAdapter.get_option_chain()` or `IntradayBotEngine.run_single_scan()` executed at any time during the trading day (for example at `10:35:00 IST`), it called `save_paired_strike_baselines()` and wrote the current intraday OI into `oi_baselines` without distinguishing an arbitrary mid-session observation (`< 15:25:00 IST`) from an official or session-close baseline (`>= 15:25:00 IST`).
   - On the next trading day (`Session T+1`), `load_prior_session_oi_baseline()` queried `SELECT ... FROM oi_baselines WHERE session_date < current_session_date` and treated that `10:35:00 IST` intraday snapshot as if it were the prior trading session's closing OI (`ce_prev_oi` / `pe_prev_oi`).
   - **Why this is invalid:** Strategy 3 (`Option Apex OI Shift`) evaluates cumulative session net OI change against the **previous trading session's closing OI**. Using a random mid-day snapshot from the prior day distorts `ce_oi_change` and `pe_oi_change`.
   - **Correction implemented in Phase 2C:** Added explicit `baseline_kind` (`CLOSING_BASELINE` vs `INTRADAY_OBSERVATION`) provenance to `oi_baselines`. Any automatic scan observation captured before `15:25:00 IST` is classified as `INTRADAY_OBSERVATION` (`source="angelone_live_intraday_observation"` or `"angelone_live_scan_intraday_observation"`) and can **never** overwrite a `CLOSING_BASELINE` or be loaded by `load_prior_session_oi_baseline()` as a prior-session closing baseline. When only `INTRADAY_OBSERVATION` rows exist for the prior session, `load_prior_session_oi_baseline()` preserves `status="NO_PRIOR_BASELINE"` (`sub_status="INTRADAY_OBSERVATION_ONLY"`) so Option Apex reports `UNAVAILABLE_NO_PRIOR_BASELINE` rather than computing changes against mid-day OI.

2. **Lack of Standalone Read-Only Local Diagnostic Workflow (`diagnostics.py`):**
   - Phase 2B required either running a full 17-symbol universe scan (`POST /api/scan`) or writing ad-hoc Python one-liners to verify Angel One connectivity.
   - **Correction implemented in Phase 2C:** Added `diagnostics.py` (`python .\diagnostics.py`) and `AngelOneSmartAPIAdapter.run_live_acceptance_diagnostics()` to independently check all 9 operational readiness areas and report `PASS`, `FAIL`, `WARNING`, or `NOT CHECKED` with strict secret redaction and zero order capability.

3. **Outside-Market-Session & Holiday Candle Freshness Interpretation (`brokers.py` L69–L92, L1118–L1125):**
   - In Phase 2B, `resolve_nse_session_dates()` skipped Saturdays and Sundays but did not skip dates configured in `NSE_HOLIDAYS` (`config.configured_holidays`). Furthermore, passing `max_staleness_minutes=20` outside market hours (such as on a weekend or after `15:30 IST`) compared raw wall-clock elapsed minutes `(now_ist - latest_dt)` against `20` minutes, rejecting valid prior-session closing candles (`15:25:00 IST`).
   - **Correction implemented in Phase 2C:** Updated `resolve_nse_session_dates()` to honor `configured_holidays` and added `evaluate_candle_freshness()`, which distinguishes active market hours (`FRESH_IN_SESSION` vs `STALE`) from outside-session/holiday windows (`FRESH_PRIOR_SESSION_CLOSE` when the latest completed bar is from the effective trading session's close `>= 15:15 IST`, vs `STALE` if bars are from an older session or midday dropout).

4. **Verification State & Observation-Timestamp Granularity in Health API & Dashboard (`brokers.py`, `scanner_engine.py`, `public/index.html`):**
   - `AngelOneSmartAPIAdapter` tracked `authenticated_at_ist` on login, but did not separately track `last_market_data_at_ist`, `last_quote_timestamp_ist`, `last_candle_timestamp_ist`, `last_candle_freshness`, or `last_error_category` (`AUTH_FAILURE`, `SESSION_EXPIRED`, `NETWORK_API_FAILURE`, `MISSING_CREDENTIALS`, `STALE_MARKET_DATA`, `RATE_LIMIT`, `UNSUPPORTED_CAPABILITY`, `NONE`).
   - **Correction implemented in Phase 2C:** Added `is_connection_verified()` (which requires `jwt_token` + `authenticated_at_ist` + `last_market_data_at_ist` + `last_error_message is None`), exposed source observation timestamps and candle freshness in `GET /api/health`, and updated `public/index.html` to display source observation timestamps (`Source Obs (IST)`) distinctly from browser poll time (`UI Poll`).

---

## 2. Step 2 — Safe Local Diagnostic Command (`diagnostics.py`)

### 2.1 Exact Local Diagnostic Commands (Windows PowerShell)

1. **Full Live-Data Acceptance Diagnostic (executes read-only Angel One auth, profile, `NIFTY`/`BANKNIFTY` quotes, `RELIANCE` 5m candles, Scrip Master, SQLite, Option Apex readiness, and security redaction checks):**
   ```powershell
   python .\diagnostics.py
   ```
2. **Custom NSE Equity Symbol or JSON Output:**
   ```powershell
   python .\diagnostics.py --equity TCS
   python .\diagnostics.py --json
   ```
3. **Offline Configuration, Scrip Master, SQLite & Baseline Readiness Check (zero network requests):**
   ```powershell
   python .\diagnostics.py --offline
   ```
4. **Safe Atomic Scrip Master Refresh + Diagnostic Check:**
   ```powershell
   Invoke-WebRequest -Uri "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json" -OutFile ".\OpenAPIScripMaster.candidate.json"
   python .\diagnostics.py --refresh-scrip-master .\OpenAPIScripMaster.candidate.json --offline
   ```
5. **Validated Prior-Session Closing OI Baseline Import (`.json` or `.csv`) + Diagnostic Check:**
   ```powershell
   python .\diagnostics.py --import-baseline .\nifty_closing_baseline.json --offline
   ```

### 2.2 Expected Output Example 1 — Successful Live-Data Acceptance (Fictional Redacted Values)

```text
======================================================================================
TRADEPULSE AI — PHASE 2C ANGEL ONE SMARTAPI LIVE-DATA ACCEPTANCE DIAGNOSTICS
======================================================================================
Executed At (IST)          : 2026-10-16 10:35:00
Overall Diagnostic Verdict : PASS
Broker Connection State    : CONNECTED_VERIFIED
Live Connectivity Verified : YES (CONNECTED_VERIFIED)
Last Market Data (IST)     : 2026-10-16 10:35:00
Latest Quote Feed (IST)    : 2026-10-16 10:34:55
Latest 5m Candle Bar (IST) : 2026-10-16 10:30:00
--------------------------------------------------------------------------------------
[PASS       ] 1. Configuration & Credential Presence
              ACTIVE_BROKER='angelone', all 4 ANGEL_* credentials present, TOTP Base32 seed valid (client_code=A9***43).
[PASS       ] 2. Angel One Authentication & Profile Verification
              Authenticated and verified profile for client_code=A9***43 (exchanges=['nse_cm', 'nse_fo']).
[PASS       ] 3. NIFTY & BANKNIFTY Market Quote Retrieval
              Retrieved FULL quotes: NIFTY LTP=24820.5 (feed=2026-10-16 10:34:55 IST), BANKNIFTY LTP=52460.0 (feed=2026-10-16 10:34:55 IST).
[PASS       ] 4. NSE Equity Intraday Candle Retrieval (RELIANCE)
              Retrieved 241 5m candles for RELIANCE (token=2885); latest bar=2026-10-16 10:30:00 IST, close=2950.3.
[PASS       ] 5. Candle Normalization, Ordering, OHLCV Integrity & Freshness
              All 241 bars sorted in IST, OHLCV invariants valid, completed_bars=241 (sufficient >=200 for 200 EMA), freshness=FRESH_IN_SESSION.
[PASS       ] 6. Scrip Master Status, File Age & Contract Resolution
              Scrip Master LOADED (age=0.0h <= 24.0h): index_options=10, NIFTY nearest_expiry=2026-10-22 (3 paired strikes), BANKNIFTY nearest_expiry=2026-10-22 (2 paired strikes).
[PASS       ] 7. SQLite Health & OI Baseline Counts
              SQLite OK (path=tradepulse_phase1d.db): total_baselines=10 (closing_baselines=10, intraday_observations=0, live_closing=10).
[PASS       ] 8. Per-Index Option Apex Readiness & Baseline Provenance
              Option Apex overall_status=READY: NIFTY=READY (baseline=2026-10-15, kind=CLOSING_BASELINE, pairs=3); BANKNIFTY=READY (baseline=2026-10-15, kind=CLOSING_BASELINE, pairs=2)
[PASS       ] 9. Throttling, Timeouts, Session Recovery & Secret Redaction
              Read-only order blocking verified, zero secrets in diagnostic output, timeout=5.0s, min_request_interval=0.35s, session-expiry recovery=refreshTokens + TOTP fallback.
--------------------------------------------------------------------------------------
Summary Counts: PASS=9 | WARNING=0 | FAIL=0 | NOT CHECKED=0
======================================================================================
```

### 2.3 Expected Output Example 2 — Failure & Warning Output (Rejected Login + Missing Prior Closing Baseline, Fictional Redacted Values)

```text
======================================================================================
TRADEPULSE AI — PHASE 2C ANGEL ONE SMARTAPI LIVE-DATA ACCEPTANCE DIAGNOSTICS
======================================================================================
Executed At (IST)          : 2026-10-16 10:35:00
Overall Diagnostic Verdict : FAIL
Broker Connection State    : ERROR
Live Connectivity Verified : NO
Last Market Data (IST)     : None
Latest Quote Feed (IST)    : None
Latest 5m Candle Bar (IST) : None
--------------------------------------------------------------------------------------
[PASS       ] 1. Configuration & Credential Presence
              ACTIVE_BROKER='angelone', all 4 ANGEL_* credentials present, TOTP Base32 seed valid (client_code=A9***43).
[FAIL       ] 2. Angel One Authentication & Profile Verification
              Authentication/profile check failed: Angel One SmartAPI loginByPassword failed (invalid client code, PIN, or TOTP [AB1007]): Invalid key [REDACTED] or pin [REDACTED] or totp [REDACTED]
[NOT CHECKED] 3. NIFTY & BANKNIFTY Market Quote Retrieval
              Skipped quote retrieval because Step 2 authentication did not succeed.
[NOT CHECKED] 4. NSE Equity Intraday Candle Retrieval (RELIANCE)
              Skipped candle retrieval because Step 2 authentication did not succeed.
[NOT CHECKED] 5. Candle Normalization, Ordering, OHLCV Integrity & Freshness
              Not checked because Step 4 did not return candles.
[PASS       ] 6. Scrip Master Status, File Age & Contract Resolution
              Scrip Master LOADED (age=1.2h <= 24.0h): index_options=10, NIFTY nearest_expiry=2026-10-22 (3 paired strikes), BANKNIFTY nearest_expiry=2026-10-22 (2 paired strikes).
[WARNING    ] 7. SQLite Health & OI Baseline Counts
              SQLite OK (path=tradepulse_phase1d.db), but 0 LIVE CLOSING_BASELINE rows exist (intraday_observations=6). Option Apex requires a prior-session closing baseline.
[WARNING    ] 8. Per-Index Option Apex Readiness & Baseline Provenance
              Option Apex overall_status=UNAVAILABLE_NO_PRIOR_BASELINE (Strategies 1, 2, 4, 5 remain operational): NIFTY=UNAVAILABLE_NO_PRIOR_BASELINE[INTRADAY_OBSERVATION_ONLY] (baseline=None, kind=None, pairs=0); BANKNIFTY=UNAVAILABLE_NO_PRIOR_BASELINE (baseline=None, kind=None, pairs=0)
[PASS       ] 9. Throttling, Timeouts, Session Recovery & Secret Redaction
              Read-only order blocking verified, zero secrets in diagnostic output, timeout=8.0s, min_request_interval=0.35s, session-expiry recovery=TOTP re-login ready.
--------------------------------------------------------------------------------------
Summary Counts: PASS=3 | WARNING=2 | FAIL=1 | NOT CHECKED=3
======================================================================================
```

---

## 3. Step 4 — Validated Prior-Session Closing OI Baseline Lifecycle & External Import Format

### 3.1 Provenance Separation Rules (`oi_baselines.baseline_kind`)
1. **`CLOSING_BASELINE`:**
   - Represents official or session-close open interest (`>= 15:25:00 IST` on the relevant NSE session date) or an explicitly validated external prior-session closing import (`import_prior_oi_baseline_file`).
   - Only `CLOSING_BASELINE` records from a strictly prior trading session (`session_date < effective_current_session_date`) are eligible to be loaded by `load_prior_session_oi_baseline()` to compute `ce_oi_change = ce_oi - ce_prev_oi` and `pe_oi_change = pe_oi - pe_prev_oi`.
2. **`INTRADAY_OBSERVATION`:**
   - Automatically recorded when scans or option-chain fetches run before `15:25:00 IST` during the trading day (`source="angelone_live_intraday_observation"` or `"angelone_live_scan_intraday_observation"`).
   - Never overwrites an existing `CLOSING_BASELINE` for the same session and is **never** promoted to a closing baseline on the next trading day.
   - If a session ends with only `INTRADAY_OBSERVATION` rows in SQLite (because no scan was run at `>= 15:25:00 IST` and no closing baseline was imported), the next trading day reports `UNAVAILABLE_NO_PRIOR_BASELINE` (`sub_status="INTRADAY_OBSERVATION_ONLY"`).

### 3.2 Documented External Closing-Baseline Import Formats (`--import-baseline`)
When a prior-session closing baseline was not captured live at `15:25–15:30 IST`, you can import it from a JSON or CSV file using `python .\diagnostics.py --import-baseline <path>`:

- **JSON Format (`nifty_closing_baseline.json`):**
  ```json
  {
    "index_symbol": "NIFTY",
    "expiry": "2026-10-22",
    "session_date": "2026-10-15",
    "observation_timestamp": "2026-10-15 15:30:00",
    "source": "official_nse_bhavcopy_import",
    "data_mode": "LIVE",
    "strikes": {
      "24750": {"ce_oi": 1600000, "pe_oi": 2100000},
      "24800": {"ce_oi": 2270000, "pe_oi": 2720000},
      "24850": {"ce_oi": 2000000, "pe_oi": 1800000}
    }
  }
  ```
- **CSV Format (`banknifty_closing_baseline.csv`):**
  ```csv
  index_symbol,expiry,strike,ce_oi,pe_oi,session_date,observation_timestamp,source
  BANKNIFTY,2026-10-22,52400,900000,1200000,2026-10-15,2026-10-15 15:30:00,official_nse_bhavcopy_import
  BANKNIFTY,2026-10-22,52500,950000,1100000,2026-10-15,2026-10-15 15:30:00,official_nse_bhavcopy_import
  ```

---

## 4. Verification Matrix (Code vs Mocked Tests vs Live API vs Local User Checks)

| Capability / Acceptance Criterion | Implemented in Code | Verified by Mocked Automated Tests (`test_bot.py`) | Verified Against Real Live Angel One API in Sandbox VM | Checks User Must Perform Locally on Windows |
| :--- | :---: | :---: | :---: | :--- |
| **1. Safe Read-Only Diagnostic CLI (`diagnostics.py`, 9 checks, `PASS`/`FAIL`/`WARNING`/`NOT CHECKED`)** | Yes (`diagnostics.py`, `brokers.py`) | Yes (`test_p2c_diagnostic_command_checks_and_secret_redaction`) | **No** (Sandbox has no outbound internet or user credentials) | Run `python .\diagnostics.py --offline` then `python .\diagnostics.py` with `.env` configured. |
| **2. Strict Secret Redaction (API Key, PIN, TOTP Seed, 6-Digit TOTP, JWT, Refresh & Feed Tokens)** | Yes (`brokers.py`, `diagnostics.py`, `config.py`) | Yes (`test_p2a_rate_limits_timeouts_secret_redaction_and_order_blocking`, `test_p2c_diagnostic_command_checks_and_secret_redaction`) | N/A (Local Security Control) | Confirm console output of `python .\diagnostics.py` masks `client_code` and prints zero secrets. |
| **3. `CONNECTED_VERIFIED` Requires Auth + Actual Market-Data Request (Auth/Profile Alone Stays `CONFIGURED_UNVERIFIED`)** | Yes (`brokers.py` `is_connection_verified`, `scanner_engine.py`) | Yes (`test_p2c_connection_state_transitions_and_auth_alone_not_verified`) | **No** | Verify `GET /api/health` shows `CONFIGURED_UNVERIFIED` before scan and `CONNECTED_VERIFIED` after live scan/diagnostic. |
| **4. Outside-Market-Session & Holiday Candle Freshness (`FRESH_IN_SESSION`, `FRESH_PRIOR_SESSION_CLOSE`, `STALE`)** | Yes (`brokers.py` `evaluate_candle_freshness`, `resolve_nse_session_dates`) | Yes (`test_p2c_malformed_stale_quotes_candles_and_outside_session_holiday_freshness`) | **No** | Run `python .\diagnostics.py` during and outside NSE market hours (`09:15–15:30 IST`) and inspect Check 5. |
| **5. OI Baseline Provenance (`CLOSING_BASELINE` vs `INTRADAY_OBSERVATION`) & Blocking Invalid Intraday Promotion** | Yes (`storage.py`, `brokers.py`, `scanner_engine.py`) | Yes (`test_p2c_oi_baseline_provenance_and_invalid_closing_baseline_promotion_blocked`) | N/A (Local SQLite & Provenance Rules) | Run a scan at `15:25–15:30 IST` (or import a closing baseline file) and verify `closing_baselines` count in Check 7. |
| **6. Validated External Prior-Session Closing Baseline Import (`--import-baseline` JSON & CSV)** | Yes (`storage.py`, `brokers.py`, `diagnostics.py`) | Yes (`test_p2c_validated_external_closing_baseline_import_workflow_json_and_csv`) | N/A (Local File Import & SQLite) | Run `python .\diagnostics.py --import-baseline <file> --offline` if seeding Day 1 prior-session closing OI. |
| **7. Dashboard Source Observation Timestamps, Error Categories & Private-File Confinement (`/diagnostics.py` 404)** | Yes (`public/index.html`, `server.py`, `scanner_engine.py`) | Yes (`test_p2c_dashboard_health_api_error_categories_and_private_file_protection`) | N/A (Local HTTP Server & UI) | Open `http://127.0.0.1:8080/` and verify Tab 4 Health rows and `http://127.0.0.1:8080/diagnostics.py` returning HTTP 404. |
| **8. Order Execution & GTT Mutation Blocking (`/order/*`, `/gtt/*`)** | Yes (`brokers.py` `_request_json`) | Yes (`test_p2a_rate_limits_timeouts_secret_redaction_and_order_blocking`, Check 9) | N/A (Local Security Control) | Verified automatically in Check 9 of `python .\diagnostics.py`. |

---

## 5. Changed & Added Files Summary

| File Path | Action | Summary of Changes |
| :--- | :--- | :--- |
| `diagnostics.py` | **Added** | Standalone read-only local diagnostic runner (`run_angelone_diagnostics`, `format_diagnostics_report`, `main`) checking all 9 required acceptance areas with `--equity`, `--offline`, `--json`, `--import-baseline`, and `--refresh-scrip-master` CLI options. |
| `storage.py` | **Updated** | Added `baseline_kind` (`CLOSING_BASELINE` vs `INTRADAY_OBSERVATION`) column & migration to `oi_baselines`; added `is_closing_session_timestamp()` (`>= 15:25:00 IST`); blocked mid-session observations from overwriting or being loaded as closing baselines; added `import_prior_oi_baseline_file()` for JSON/CSV imports; added `oi_closing_baselines_count`, `oi_intraday_observations_count`, and `oi_live_closing_baselines_count` to `check_health()`. |
| `brokers.py` | **Updated** | Added `evaluate_candle_freshness()`, holiday-aware `resolve_nse_session_dates()`, `is_connection_verified()`, `last_market_data_at_ist`, `last_quote_timestamp_ist`, `last_candle_timestamp_ist`, `last_candle_freshness`, `last_error_category`, `import_prior_oi_baseline_file()`, and `run_live_acceptance_diagnostics()` on `AngelOneSmartAPIAdapter`; updated `set_prior_oi_baseline()` and `get_option_chain()` to enforce closing-baseline provenance. |
| `scanner_engine.py` | **Updated** | Updated `_persist_current_session_oi_baseline()` to classify observations by timestamp (`INTRADAY_OBSERVATION` before `15:25:00 IST`, `CLOSING_BASELINE` at/after `15:25:00 IST`); enriched `get_broker_status()` with `auth_verified`, `market_data_verified`, `last_market_data_at_ist`, `last_quote_timestamp_ist`, `last_candle_timestamp_ist`, `candle_freshness`, and `error_category` / `last_error_category`. |
| `server.py` | **Updated** | Added `baseline_kind` query filter validation (`CLOSING_BASELINE` or `INTRADAY_OBSERVATION`) on `GET /api/oi-baselines`. |
| `public/index.html` | **Updated** | Updated header telemetry and Tab 4 System Health panel to display source observation timestamps (`Source Obs (IST)`) separately from browser refresh time (`UI Poll`), plus `Last Market-Data Time (IST)`, `Candle Freshness Status`, `Last Broker Error / Category`, and `Closing Baselines` vs `Intraday Obs` counts. |
| `test_bot.py` | **Updated** | Preserved all 73 Phase 1A–2B tests and added `TestIndianFOSignalBotPhase2C` (8 new test suites, bringing total to **81 passing tests**). |
| `README.md` | **Updated** | Added Phase 2C Windows PowerShell operational workflow, local diagnostic commands, and closing OI baseline import instructions. |
| `docs/PHASE_2C_IMPLEMENTATION_REPORT.md` | **Added** | Complete Phase 2C audit, diagnostic command reference, redacted output examples, baseline provenance guide, and 4-column verification matrix. |

---

## 6. Compilation & Automated Test Suite Results

### 6.1 Python Bytecode Compilation
```bash
python3 -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py diagnostics.py test_bot.py
```
Result: **Exit code `0`** across all 9 Python modules with zero warnings.

### 6.2 Full 81-Test Suite Execution (`test_bot.py`)
```bash
python3 test_bot.py -v
```
- **Total Tests Executed:** `81` (`20` Phase 1A + `11` Phase 1B + `8` Phase 1C + `11` Phase 1D + `3` Phase 1E + `4` Phase 1F + `8` Phase 2A + `8` Phase 2B + `8` Phase 2C)
- **Passed:** `81`
- **Failed:** `0`
- **Skipped:** `0`
- **Warnings:** `0`
- **Execution Time:** `21.392s` (`OK`)

---

## 7. Remaining Limitations

1. **Live Broker API Not Executed Inside Sandbox VM:** Outbound internet access is disabled in the sandbox VM and no user credentials exist in this environment. Real Angel One network verification is **not claimed** here and must be executed locally on your Windows machine using `python .\diagnostics.py`.
2. **Prior-Session Closing OI Baseline Requirement for Option Apex:** Because Angel One SmartAPI's quote endpoint reports only current `opnInterest` and does not provide `previous_oi`, Strategy 3 (`Option Apex OI Shift`) requires a validated `CLOSING_BASELINE` from the prior trading session (either captured automatically by running a scan between `15:25:00` and `15:30:00 IST` on the prior session or imported via `python .\diagnostics.py --import-baseline <file>`). Mid-session intraday snapshots (`< 15:25:00 IST`) are never promoted to closing baselines.
3. **Read-Only Scope Only:** Order placement, modification, cancellation, and GTT rule mutations remain strictly blocked in code (`/rest/secure/angelbroking/order/*` and `/gtt/*` raise `BrokerDataError`). Historical walk-forward backtesting remains deferred until local live-data acceptance and baseline provenance are verified on your machine.
