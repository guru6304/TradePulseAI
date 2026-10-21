# TradePulse AI — Task 2 Blockers & Next Actions
**Task ID:** `20261020_TASK2_CONFIG_AND_CASH_DATA_ACCEPTANCE`  
**Date:** `2026-10-19`  
**Workspace:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`  
**Operating Posture:** Strictly Offline — Safe runtime boundaries preserved.

---

## 1. Prioritized Blocker Register

| Priority | Blocker ID | Affected Milestone | Description & Root Cause | Classification | Responsible Party | Testable Completion Condition |
|---|---|---|---|---|---|---|
| **P1** | `BLK-01` | M01 | **Active `.env` Syntax Error on Line 7/8 (`DOTENV_ASSIGNMENT_MISSING_EQUALS`)**: Local configuration file contains an assignment missing the `=` delimiter. | Local Action | Local Operator / User | `python -B configuration_check.py` returns `exit code 0` with `status: PASS` and `LOCAL_CONFIGURATION_VALID`. |
| **P2** | `BLK-02` | M02, M03 | **Angel One Candle API HTTP 403 `ACCESS_DENIED`**: Endpoint `/historical/v1/getCandleData` rejected access during live diagnostic. Likely caused by missing "Historical Data" API subscription or Static IP mismatch on SmartAPI portal. | External Dependency | Angel One Account Owner / SmartAPI Portal | Standalone diagnostic returns HTTP 200 with non-empty candle array for RELIANCE 5m intraday. |
| **P3** | `BLK-03` | M02 | **Upstox API Quote HTTP 403 `FORBIDDEN` / V2 Deprecation**: Upstox V2 intraday candle route is deprecated; quote endpoint rejected access with HTTP 403. | External Dependency | Upstox Account Owner / Upstox Developer Portal | Diagnostic returns HTTP 200 for Upstox quote and valid token validation. |
| **P4** | `BLK-04` | M05, M06 | **Dynamic NFO Scrip Master Feed Missing**: Options and F&O derivative candles/contracts currently rely on static snapshot observations rather than an automated daily NFO master ingestion feed. | Local Implementation | Core Engineering | Daily automated download of `OpenAPIScripMaster.json` parses all active strikes/expiries for index & stock F&O. |
| **P5** | `BLK-05` | M04, M08 | **Authoritative Historical Source Qualification Gate**: `assess_source_evidence` rejects historical replay files lacking digital publisher signatures. | External Dependency / Architecture | Quant Research / Compliance | Digital signature or HMAC manifest verifier authenticates historical parquet/csv files before LIVE replay. |
| **P6** | `BLK-06` | M08 | **Strategy 3 (Option Contract) Historical Execution**: Replay engine rejects Strategy 3 (`HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED`) due to lack of tick-level bid/ask option execution data. | Local Architecture | Quant Research | Discrete contract pricing/fill model maps underlying spot moves to historical option premiums during replay. |

---

## 2. Partitioned Remediation Actions

### Category A: Immediate Local Actions (Executable Safely Offline)

1. **Local Operator `.env` Line 7/8 Syntax Correction**:
   - **Responsible**: Local User / Operator.
   - **Action**: Open `.env` in your text editor (already open at Line 1). Inspect line 7 (or 8). Ensure the line conforms to `KEY=VALUE` syntax (for example: `ACTIVE_BROKER=paper_sim` or `ACTIVE_BROKER=angelone`). Save the file.
   - **Verification**: Run `python -B configuration_check.py`. Confirm it exits 0 with `LOCAL_CONFIGURATION_VALID`.
   - **Safety Boundary**: NEVER paste `.env` into chat, NEVER display or log secret values, and NEVER commit `.env` to git.

2. **Automated Daily NFO Master Ingestion**:
   - **Responsible**: Core Engineering.
   - **Action**: Implement a cached fetcher for Angel One's publicly accessible scrip master JSON (`https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json`) with automated daily expiry/strike pruning.
   - **Verification**: `python -B -m unittest test_phase5a_contracts` passes with dynamic scrip master fixture.

3. **Discrete Option Fill Simulation Model (Strategy 3 Replay)**:
   - **Responsible**: Quant Research.
   - **Action**: Implement Black-Scholes or delta-approximation fills for Strategy 3 historical replay when underlying spot moves trigger entry, stop, or target.
   - **Verification**: Historical backtest executes Strategy 3 across split sessions without raising `HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED`.

---

### Category B: External Actions (Requiring External Credentials / Portal Approval)

1. **Angel One SmartAPI Developer Portal Review**:
   - **Responsible**: Angel One Account Owner.
   - **Prerequisites**: Access to `https://smartapi.angelbroking.com/`.
   - **Steps**:
     a. Log in to SmartAPI portal.
     b. Verify the App Status is Active.
     c. Enable "Historical Data" API permission for the app.
     d. If Static IP is enabled on the app, ensure your current public IP is whitelisted, or create an app with IP restriction disabled for dynamic development IPs.
   - **Testable Verification**: Run a bounded, read-only diagnostic preflight in offline mode first, then execute single quote/candle check.

2. **Upstox Developer App Access & Token Authorization**:
   - **Responsible**: Upstox Account Owner.
   - **Prerequisites**: Access to Upstox Developer Portal.
   - **Steps**:
     a. Confirm valid API Key and Secret.
     b. Generate a fresh daily Access Token via the OAuth2 flow.
     c. Note that Upstox V2 intraday candle endpoint is formally deprecated in favor of V3. If Upstox is retained as primary broker, upgrade the adapter routes to V3.

3. **Authoritative Market Data Licensing & Provenance Signatures**:
   - **Responsible**: Data Engineering / Compliance.
   - **Prerequisites**: Commercial market-data license from NSE / authorized data vendor.
   - **Steps**:
     a. Obtain licensed historical 1m/5m NSE cash & NFO data.
     b. Generate SHA-256 HMAC provenance manifests signed by the licensed data publisher.
   - **Testable Verification**: `source_qualification.assess_source_evidence` returns `allowed=True`.

---

## 3. Strict Pre-Operational Safety Gates

Before any live trading or live scheduler service can be authorized:
- [ ] Local `.env` syntax passes zero-disclosure diagnostic.
- [ ] Safe runtime constraints remain active: `TELEGRAM_DRY_RUN=true`, `ENABLE_BACKGROUND_SCHEDULER=false`.
- [ ] Angel One SmartAPI Historical Data HTTP 403 resolved on portal.
- [ ] Authoritative NFO derivative scrip master ingested and validated.
- [ ] Continuous paper trading runs across multi-session soak without state corruption.
- [ ] Full recovery drill executed using `release_management.py:DatabaseBackupRecovery`.


## Task 3 correction notice - 2026-10-21

Do not follow the historical instructions to infer subscription/IP causes, disable IP restrictions, or replace observed option premiums with Black-Scholes/delta fills. A locally generated hash/HMAC does not authenticate an external publisher. Source qualification currently has no supported verifier. Task 3 supplies corrected owners, prerequisites and closure criteria.

The original report body above is retained as historical evidence. Current authority: [Task 3 forensic, stability and readiness report](TRADEPULSE_TASK3_FORENSIC_STABILITY_AND_READINESS_REPORT.md).

## Task 4 B04 update - 2026-10-21

[Task 4 cash-candle lineage and recovery evidence](TRADEPULSE_TASK4_CASH_CANDLE_LINEAGE_AND_RECOVERY_REPORT.md)
closes B04's defined offline implementation/recovery work: immutable accepted completed
cash inputs, transactional scan/signal linkage, pending-work recovery, duplicate and
correction protection, and interrupted paper-handoff reconciliation. Live provider
handoff and operational acceptance remain unverified; this does not close end-to-end
cash acceptance. Task 3's remaining B02 and B05-B12 dependencies and owners remain
applicable; the Task 4 report carries their current closure requirements forward.

Next acceptance task: operator/account/token/scope confirmation followed by separate
authorization for the bounded Upstox RELIANCE quote/candle diagnostic. No live request
is authorized by this addendum. The offline B05 dynamic NFO import/source-universe
work can proceed independently when its authoritative input/scope is available.
Scores remain 64.25% implementation / 37.00% verified readiness; 0/12 accepted.
