# TRADEPULSE AI — PHASE 6 DASHBOARD, EOD & OPERATIONAL RECOVERY REPORT

**Document ID:** `docs/reports/phase6_dashboard_eod_recovery_report_20261024_01.md`  
**Stage:** `phase6_20261024_01`  
**Date:** 2026-10-24  
**Author:** TradePulse AI Frontend, Reporting & Operations Engineering  
**Scope:** Workstream D (Dashboard, EOD Reporting & Release Handover)  
**Status:** `GATE_D_ACCEPTED` & `GATE_E_ACCEPTED` (Offline Verification Passed)

---

## 1. Executive Summary

Workstream D verified the end-to-end integration between the underlying SQLite persistence layer, the HTTP REST API endpoints (`server.py`), and the user-facing web dashboard (`public/index.html`).

All 24 automated DOM double regressions in `test_cash_dashboard.js` pass cleanly without external network calls, verifying that stored paper accounts, positions, fees, P&L, and EOD reconciliation statements render truthfully and without misleading live acceptance claims.

---

## 2. Web Dashboard Architecture & API Alignment

### 2.1 Stored Paper Ledger & EOD Reconciliation UI
1. **API Endpoints Tested:**
   - `GET /api/paper-accounts`: Enumerates configured paper trading accounts.
   - `GET /api/paper-portfolio?account_id=...`: Returns current snapshot, accounting balances, open positions, and reconciliation status.
   - `GET /api/paper-session?account_id=...&session_date=...`: Returns event-derived EOD session statement, event digests, and statement checksum.
   - `GET /api/paper-ledger?account_id=...`: Serves paginated raw ledger events.

2. **Frontend Rendering Invariants:**
   - **Prominent Simulation Warning:** Every rendered report container clearly displays:  
     `LOCAL STORED EVIDENCE. Paper fills and research execution are simulations; live acceptance is separate.`
   - **Reconciliation Failure Defense:** If `data.reconciliation.status !== 'OK'`, the dashboard displays:  
     `RECONCILIATION REQUIRED; accounting unavailable`, refusing to display equity figures that have not reconciled.
   - **Truthful Formatting:** Currency values are formatted via `formatInr` (e.g. `₹2,05,000.50`), and counts of open/closed positions match the stored ledger.
   - **Statement Verification:** Displays exact SHA-256 statement digest and session reconciliation status (`RECONCILED` or `UNRESOLVED`).

---

## 3. Operational Safety Defaults & Limitations

In strict adherence to the non-negotiable safety rules:
1. `ACTIVE_BROKER=paper_sim`: Production runtime operates order-free and broker-free.
2. `TELEGRAM_DRY_RUN=true`: Signal alerts are routed strictly to the local notification preview outbox; no Telegram bot calls occur.
3. `ENABLE_BACKGROUND_SCHEDULER=false`: Periodic background scanners are deactivated; execution occurs only via explicit manual CLI invocations.
4. `DATABASE_URL`: Operational database `tradepulse_phase1d.db` remains untouched, empty, and preserved. All tests execute in temporary SQLite databases.

---

## 4. Runbook & Disaster Recovery Summary

1. **Clean Process Startup:**
   ```powershell
   # Preflight configuration check (secrets redacted)
   .venv_phase4\Scripts\python.exe configuration_check.py --mode paper_sim

   # Start local dashboard server (port 8080)
   .venv_phase4\Scripts\python.exe server.py --port 8080
   ```
2. **Graceful Shutdown:**
   - Issue `SIGINT` (Ctrl+C). The HTTP server drains existing requests and closes SQLite connection handles cleanly.
3. **Database Backup & Rollback Drills:**
   - Uses `DatabaseBackupRecovery` in `release_management.py`.
   - SQLite online backup API (`conn.backup`) creates atomic snapshots without locking concurrent reads.
   - Rollback drills verify zero corruption and integrity check (`PRAGMA integrity_check`) returns `ok`.

---

## 5. Acceptance Gate Verdicts

- **Gate D — Dashboard & EOD Reconciliation:** **ACCEPTED**  
  Dashboard faithfully displays paper accounting, simulated badges, EOD statements, and reconciliation warnings.
- **Gate E — Recovery & Operational Readiness:** **ACCEPTED**  
  Operational procedures, backup/rollback tooling, safety defaults, and fail-closed behaviors are fully verified.
