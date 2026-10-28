# TradePulse AI — Track B UI Requirement & Control Migration Matrix
**Mission ID:** `TPAI-TRACKB-PREMIUM-EXPERIENCE-RECOVERY-2026-10-28-V2`  
**Track ID:** `ANTIGRAVITY_B`  
**Git Baseline:** `c6c8040452d912c0e32a283ca9ceff7b1010bd62`  
**Date:** 2026-10-29T00:06:00+05:30  

---

## 1. Information Architecture & Navigation Mapping

| Proposed Destination | Target User Question | Content & Action Scope | Existing Source Mapping | Status |
| :--- | :--- | :--- | :--- | :---: |
| **1. Pulse (Overview)** | *"What deserves attention now?"* | Market session clock, data provenance badge, Top 1–3 qualified setups (or calm 3-column no-signal state), Rank Movers, Market Radar strip, paper summary. | `tab-terminal` (Top portion: Candidate Priority + Market Radar) | `VERIFIED` |
| **2. Opportunities** | *"Which valid setups rank highest and why?"* | Full dynamic qualified leaderboard; cash/F&O segment filters; direction/strategy filters; symbol search; Opportunity X-Ray 5m chart & factor deltas. | `tab-terminal` (Lower portion: Signals List, Level Structure Chart, Inspector) | `VERIFIED` |
| **3. Options Lab** | *"What do option-chain and contract data actually show?"* | NIFTY/BANKNIFTY spot & ATM; single cohesive No-Snapshot state (no repeated blank cards); strike-wise OI chart; option chain strike table; snapshot comparison. | `tab-option-apex` (Cleaned of raw endpoint names and internal enums) | `VERIFIED` |
| **4. Strategies & Research** | *"How do strategies work and what evidence supports them?"* | 5 strategy specification cards; rule mechanics; session windows; backtest simulator controls; equity curves; statistical limitations. | `tab-strategies` (Top 5 Strategies & Backtester) | `VERIFIED` |
| **5. Paper Portfolio** | *"What did the simulator actually do?"* | Simulated positions, virtual equity, P&L, risk limits, event ledger, session reconciliation; clear distinction between simulation and live paper marks. | Stored Paper Reports & EOD statements in `tab-brokers-telegram` | `VERIFIED` |
| **Utility: Health & Settings** | *"Is the system reliable, and how can I configure the display?"* | DB status, scheduler state, scan history table, source event logs, configuration parameters (redacted), auto-refresh interval. | `tab-brokers-telegram` (System Health, Scan History & Config) | `VERIFIED` |

---

## 2. Interactive Controls & Regression Contract Inventory

| Control ID | Component | Current Handler / Route | New Location | Expected Behavior | Test Verification |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `btnRefreshDashboard` | Button | `loadSignals()`, `loadHealthAndConfig()` | Top contextual bar | Read-only data reload without triggering scanner or broker mutations. | `test_cash_dashboard.js` (Test 31) |
| `btnRunLiveScan` | Button | `POST /api/scan` | Top contextual bar | Explicit user-triggered market scan in simulated mode; disabled outside session/simulation. | `test_cash_dashboard.js` |
| `filterSegment` | Dropdown | Local filter on `state.signals` | Opportunities Toolbar | Filters displayed candidate list by `ALL`, `NSE_FO_INDEX`, `NSE_EQUITY_INTRADAY`. | `test_cash_dashboard.js` |
| `filterStrategy` | Dropdown | Local filter on `state.signals` | Opportunities Toolbar | Filters displayed candidate list by 5 institutional strategy IDs. | `test_cash_dashboard.js` |
| `filterDirection` | Dropdown | Local filter on `state.signals` | Opportunities Toolbar | Filters by `BULLISH` or `BEARISH`. | `test_cash_dashboard.js` |
| `filterDataMode` | Dropdown | Local filter on `state.signals` | Opportunities Toolbar | Filters by `SIMULATED` vs `LIVE`. | `test_cash_dashboard.js` |
| `searchSymbol` | Input | Local search on `state.signals` | Opportunities Toolbar | Real-time text filter by symbol ticker. | `test_cash_dashboard.js` |
| `btnResetSignalFilters` | Button | Resets filter dropdowns to defaults | Opportunities Toolbar | Restores all filter selections to default without network calls. | `test_cash_dashboard.js` |
| `selectPageLimit` | Dropdown | Controls pagination size (10/20/50) | Opportunities Toolbar | Updates client-side paging slice cleanly. | `test_cash_dashboard.js` |
| `foIndexSelect` | Dropdown | `GET /api/oi-snapshots?index=...` | Options Lab Header | Toggles between NIFTY and BANKNIFTY snapshots. | `test_cash_dashboard.js` |
| `foSnapshotSelect` | Dropdown | Renders selected historical snapshot | Options Lab Controls | Renders historical strike table without network reload. | `test_cash_dashboard.js` |
| `btnApplyApiBaseUrl` | Button | Updates `state.apiBaseUrl` | Health & Settings | Sets custom API loopback URL safely. | `test_cash_dashboard.js` |
| `selectAutoRefreshSec` | Dropdown | Configures client polling timer | Health & Settings | Adjusts read-only polling cadence (15s/30s/60s/Off). | `test_cash_dashboard.js` |
| `refreshStoredReports` | Button | `GET /api/stored-reports` | Paper & Health | Reads stored simulation ledger without executing paper fills. | `test_cash_dashboard.js` |

---

## 3. Visual Anti-Pattern Remediation Log

| Screen / Component | Flagged Anti-Pattern | Root Cause in Legacy Code | Remediation in V2 |
| :--- | :--- | :--- | :--- |
| **Top Navigation** | Long numbered horizontal tabs (`1. Live Signal Terminal`, `2. Nifty & BankNifty...`) | Legacy Phase 1E layout | Sleek, labeled primary navigation with distinct brand mark and active indicator. |
| **Header Diagnostics** | Raw operational strings (`DB: OK`, `Scheduler: DISABLED`) dominating top row | Legacy debug text | Relocated to Health & Settings. Header displays only Session, Data Mode, Clock, and Scan trigger. |
| **Option Apex Heading** | Raw API string (`GET /api/oi-snapshots`) in page title | Developer debug convention | Replaced with editorial title: *"Options Positioning Lab — Intraday Derivatives Structure"*. |
| **Option Apex Status** | Internal backend enum (`SIMULATED_READY`) displayed verbatim | Raw enum rendering | Replaced with human-readable status: *"Simulation Baseline Available"*. |
| **Option Apex Empty State** | 4 repeated identical cards showing `--`, `NO_SNAPSHOT`, `No Active Signal` | Unhandled initial state | Replaced with single, elegant **Data Availability Panel** with clear explanation and demo toggle. |
| **Candidate Priority** | Giant yellow error line (`Candidate priority unavailable...`) | Single `<p>` element | Replaced with calm 3-column financial intelligence panel explaining session, gate logic, and next step. |
