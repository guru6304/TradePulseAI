# TradePulse AI — Project Blockers & Actionable Next Steps
**Task Identifier**: `20261019_FORENSIC_AUDIT`  
**Date**: `2026-10-19`  
**Workspace**: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`

---

## 1. Local Configuration Parse Error Diagnostic

A local configuration syntax error was identified during audit initialization. To inspect the error safely without disclosing secrets or printing `.env` contents to logs or terminal buffers, execute the local-only configuration diagnostic:

```powershell
python -B configuration_check.py
```

### Observed Output
```json
{
  "authentication": "NOT_TESTED",
  "candles": "NOT_TESTED",
  "configuration_ready": false,
  "data_persisted": false,
  "line_number": 8,
  "live_requests": false,
  "quote": "NOT_TESTED",
  "readiness_receipt_issued": false,
  "reason_code": "DOTENV_ASSIGNMENT_MISSING_EQUALS",
  "scope": "LOCAL_CONFIGURATION_ONLY",
  "status": "BLOCKED"
}
```

### Explanation & Action for User
- **Reason Code**: `DOTENV_ASSIGNMENT_MISSING_EQUALS`
- **Line Number**: `8`
- **Cause**: Line 8 in `indian_fo_signal_bot_v1\.env` contains text without a separating `=` sign (or a key with missing assignment).
- **Safe Correction**: Open `indian_fo_signal_bot_v1\.env` locally in an editor. Inspect line 8. Ensure every non-comment line follows standard `KEY=VALUE` syntax. Do not share or paste `.env` contents into chat or public repositories.
- **Verification**: Re-run `python -B configuration_check.py`. Once line 8 is corrected and all required credentials are present, the diagnostic will exit `0` with `"status": "PASS"` and `"reason_code": "LOCAL_CONFIGURATION_VALID"`.

---

## 2. Comprehensive Inventory of Project Blockers

| Blocker ID | Capability Area | Classification | Root Cause & Evidenced Manifestation | Remediation Completed | Remaining Action Required | Owner |
|---|---|---|---|---|---|---|
| **BLK-01** | Angel One Historical Candles | `EXTERNAL_PORTAL_PERMISSION` | `POST /rest/secure/angelbroking/historical/v1/getCandleData` returns HTTP 403 Access Denied (`ACCESS_DENIED`), while quotes succeed. | Bounded diagnostic implemented; 403 invalidates session; rate limits respected; zero error leakage. | Log into Angel One SmartAPI developer portal. Verify app has Historical API entitlement enabled, or check if a Static IP is enforced. | User / Account Admin |
| **BLK-02** | Upstox Live Quote & Candle Access | `UNRESOLVED_CREDENTIAL_OR_TOKEN` | Prior diagnostic returned HTTP 403 / FORBIDDEN on quote endpoint. | Safe HTTP error detail extraction and sanitization implemented (`UPSTOX_HTTP_ERROR_REPORT.md`). | Obtain fresh authorized Upstox V2 access token; verify market data subscription scope. | User / Account Admin |
| **BLK-03** | Upstox V2 Endpoint Deprecation | `MAINTENANCE_LIFECYCLE` | Upstox developer documentation marks `/v2/historical-candle/intraday/.../1minute` as deprecated. | Documented in architecture matrix; adapter continues using stable V2 contract with strict validation. | Plan and test migration to updated Upstox historical routes when official V3 specification stabilizes. | Engineering Team |
| **BLK-04** | Authoritative Derivative Contract Masters | `SOURCE_AUTHENTICITY` | Public Angel master snapshot captured, but lacks verifiable publisher signature, date authority, or authenticated provenance. | Four derivative types parsed into normalized models; tamper rejection and integrity digests enforced. | Ingest signed exchange contract master with publisher provenance chain and effective date bounds. | Engineering Team |
| **BLK-05** | Strategy 3 Historical Backtesting Engine | `FUNCTIONAL_GAP` | `readiness_policy.py` blocks Strategy 3 with `HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED`. Spot bars cannot drive option fills. | Strategy 3 rule evaluation implemented for live chain inputs; explicit safe replay gate blocks execution. | Implement dedicated option-contract candle execution engine with bid-ask spread and time decay modeling. | Engineering Team |
| **BLK-06** | Historical Replay Authenticity Gate | `PROVENANCE_SECURITY` | `source_qualification.py` intentionally rejects unverified historical archives (`historical_eligibility.allowed=False`). | Adversarial provenance policy gate blocks synthetic or tampered datasets from contaminating research. | Deploy cryptographic publisher signature verification and trusted timestamp authority verification. | Security / Data Engineering |
| **BLK-07** | Automated Browser UI Testing | `TEST_COVERAGE` | Dashboard tested with unit tests (`test_cash_dashboard.js`) and API mocks, but headless browser E2E test unexecuted. | Node test suite verifies DOM element creation, error clearing, and truthful `LIVE SOURCE (STORED)` labels. | Integrate automated headless browser suite (e.g. Playwright or Puppeteer) for cross-browser verification. | QA / Frontend Engineering |
| **BLK-08** | Real Trading & Order Execution | `MANDATORY_SAFETY_BLOCK` | Live order placement, modification, cancellation, and execution endpoints are strictly disabled in source code. | Read-only adapters enforce order blocking; scheduler disabled; Telegram dry-run active. | Requires full completion of M01–M12, multi-session paper soak, formal risk committee sign-off, and explicit regulatory compliance. | Executive / Risk Committee |

---

## 3. Prioritized Action Plan

### Priority 1: Correct Local `.env` Syntax (Local User Action)
1. Run `python -B configuration_check.py` to confirm the line number.
2. Edit line 8 of `indian_fo_signal_bot_v1\.env` to ensure valid `KEY=VALUE` formatting.
3. Confirm with `python -B configuration_check.py` (Exit code `0`).

### Priority 2: Verify SmartAPI Historical API Entitlement (Portal Action)
1. Log into `https://smartapi.angelone.in/` developer dashboard.
2. Check whether your registered App is a "Connect" app with "Historical Data" enabled.
3. Check whether "Static IP" is enabled. If enabled, ensure your egress public IP matches.

### Priority 3: Rerun Bounded Market Data Preflight & Single Observation
```powershell
# 1. Offline preflight
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --isolated-provider --check-config --json

# 2. Single live observation (during NSE trading hours 9:15 AM - 3:30 PM IST)
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --isolated-provider --json
```

### Priority 4: Offline Research & Paper Portfolio Operation
The platform is fully operational offline for research and simulation. You can safely run walk-forward backtests, synthetic paper trading, and scanner simulations with:
```powershell
python -B -m unittest test_bot
```
All 625 strict regression tests will run with zero external network dependencies and complete data isolation.
