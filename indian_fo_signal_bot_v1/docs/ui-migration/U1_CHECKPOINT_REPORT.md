# TradePulse AI — U1 Checkpoint Implementation Report (U1-C Correction)
**Stage 4 / Agent 3 / React UI Migration — Exact Backend API Parity**  
**Date:** 2026-11-03  
**Worktree:** `C:\Users\91810\TradePulseAI-Worktrees\ui`  
**Branch:** `feature/new-ui`  
**Baseline Git Commit:** `627b61c`  
**Pre-Correction Commit:** `d0c3b23`  
**Authoritative Contracts:**
- `TP_UI_API_CONTRACT_V1.md` (Inspected against `main` at `1083092`)
- `TP_STRATEGY_INTEGRATION_CONTRACT_V1.md`
- `TRADEPULSE_MASTER_STATUS.md`

---

## 1. Executive Summary & Defect Diagnosis (U1-C)

Following owner review of checkpoint `d0c3b23`, an audit was conducted comparing `server.py`, the H0 contract `TP_UI_API_CONTRACT_V1.md`, and all frontend network dispatch and documentation paths.

The audit revealed that while core frontend runtime code in `frontend/src/api/` was already using canonical backend endpoints (`/api/opportunity-rankings`, `/api/cash-candles`, `/api/scan-lineage`, `/api/signals`), the previous checkpoint report contained inaccurate endpoint documentation (e.g. `/api/rankings`, `page=N`, `/api/cash-candles-batch`, `/api/signal-lineage`, unscoped `/api/paper-portfolio`). Furthermore, runtime query parameter validation, paper account discovery, and loopback Host/Origin proxy alignment required formalization.

All contract mismatches have been systematically investigated and corrected in **U1-C**. Parity is backed by a live disposable loopback integration test (`test_ui_api_loopback_parity.py`) against `server.create_http_server()`, strict unit/component tests in Vitest (30 passing tests), strict TypeScript typechecks, clean production build, and 17 passing node regression tests.

---

## 2. Contract Mismatch & Parity Resolution Matrix

| Item # | Identified Surface | Previous Code / Report State | Verified Source Behavior (`server.py` & H0) | Final Resolution (U1-C) |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Ranking Endpoint Path** | Report listed `/api/rankings?limit=20`. Code in `client.ts` used `/api/opportunity-rankings`. | `server.py:95, 1192` defines `opportunity-rankings`. `/api/rankings` does NOT exist and returns HTTP 404 `NotFoundError`. | Standardized 100% on `/api/opportunity-rankings`. Corrected report and added unit + loopback tests asserting `/api/rankings` returns 404 and `/api/opportunity-rankings` returns 200. |
| **2** | **Ranking Pagination & Envelope** | Report listed `page=N`. Code used `limit` & `offset`. | `server.py:558` strictly allows only `{"run_id", "limit", "offset"}`. Querying `page` triggers a 400 `Invalid ranking query.` Server returns `{status, actionable, scope, as_of, current_rows, historical_rows, pagination, snapshot}`. | Enforced strict parameter sanitization in `client.ts:getOpportunityRankings` ensuring client `page` is never forwarded. Multi-page collection pins `snapshot.run_id`. Verified in loopback integration test. |
| **3** | **Cash Candles Endpoint** | Report listed `/api/cash-candles-batch?symbols=...`. Code used `/api/cash-candles`. | `server.py:95, 522` defines `/api/cash-candles`. Strictly requires `run_id` and matching `batch_id`; unknown params return 400, missing batch returns 404. `/api/cash-candles-batch` returns 404. | Enforced parameter validation in `client.ts:getCashCandles`: throws `ApiError` if `run_id` or `batch_id` is empty. Updated documentation. Verified 404 on `cash-candles-batch` and 200 on exact `run_id` + `batch_id` in loopback test. |
| **4** | **Signal Lineage Interface** | Report listed `/api/signal-lineage?symbol=...&direction=...`. Code used `getSignals` with client join. | `server.py` implements `/api/signals` with query bounds; `/api/signal-lineage` is NOT implemented and returns 404. Signal reconciliation requires exact join on `dedup_key`, `strategy_id`, `position_type`, `instrument_identity`, and aware watermark. | Clarified that `/api/signals` is the canonical endpoint. In `XRayDrawer.tsx`, if the join cannot be uniquely proven (zero or multiple matches), the drawer strictly transitions to `UNAVAILABLE` and withholds replacement price/chart data. |
| **5** | **Paper Portfolio Scoping** | Report listed `/api/paper-portfolio` without query parameters. Code called `getPaperPortfolio(accountId)`. | `server.py:933, 942` strictly requires `account_id` (1..128 chars, `[A-Za-z0-9_.:-]{1,120}`). Unscoped `/api/paper-portfolio` returns 400 `Invalid paper-report query.` | Added pre-dispatch validation in `client.ts:getPaperPortfolio` rejecting empty/invalid IDs. Added `/api/paper-accounts` client method for verified discovery if `health.paper_account_id` is null. If unconfigured, renders "No Reconciled Paper Account" without querying. |
| **6** | **Health DTO Structure** | Report assumed `market_state` and `clock_drift` fields. | `server.py:388-398` projects `status`, `broker`, `database`, `scheduler`, `last_scan`, `paper_account_id`, `operations`, `live_acceptance`. No top-level `market_state` or `clock_drift` exists. | Verified `HealthResponse` TypeScript schema against `server.py`. In `Header.tsx`, session label is mapped directly from `health.scheduler.session_state` and candle/scan timestamp, matching `public/terminal.js:243`. |
| **7** | **Host / Origin Security & Vite Proxy** | Vite dev server proxy forwarded default browser `Origin: http://localhost:5173`. | `server.py:1351` enforces strict local same-origin checks: loopback client, `Host` header port matching server bind port, and `Origin` matching `http://` + Host or absent. Mismatched Origin or `Sec-Fetch-Site: cross-site` returns 403 `LOCAL_SAME_ORIGIN_REQUIRED`. | Configured `proxy.on('proxyReq')` in `vite.config.ts` to rewrite `Origin: http://127.0.0.1:8000` and `Sec-Fetch-Site: same-origin` during local development. Verified in loopback integration tests. |

---

## 3. Authoritative Route-to-API Mapping Table

Every frontend screen and data fetcher was verified against real backend endpoints defined in `TP_UI_API_CONTRACT_V1.md` and `server.py`. **Zero Stitch imaginary routes are utilized.**

| UI Component | Backend API Endpoint | HTTP Method | Query Parameters & Constraints | Fallback / Unavailable Behavior | Parity Contract Verified |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Header / Clock** | `/api/health` | `GET` | No query consumed | `OFFLINE` badge; alerts reflected from `operations.alerts` | Verified `HealthResponse` |
| **Pulse Hero Cards** | `/api/opportunity-rankings` | `GET` | `limit=100`, `offset=0` | "No Qualified Opportunities" waiting card with truthful IST timestamp | Verified `RankingResponse` |
| **Pulse KPIs** | `/api/opportunity-rankings`, `/api/health` | `GET` | `limit=100`, `offset=0` | Shows candidate count from complete snapshot; session state from `scheduler.session_state` | Verified `RankingResponse` |
| **Opportunities Table**| `/api/opportunity-rankings` | `GET` | `run_id=<pinned>`, `limit=100`, `offset=0,100..` (Strict: no `page` param) | Shows empty state "No matching candidates for filter" | Verified multi-page snapshot |
| **X-Ray Lineage** | `/api/scan-lineage` | `GET` | Required `run_id` (1..160 chars) | Retains snapshot timestamp, displays error if batch missing | Verified `ScanLineageResponse` |
| **X-Ray 5m Candles** | `/api/cash-candles` | `GET` | Required `run_id` and matching `batch_id`; `limit=100`, `offset=N` | Renders zero-lookahead notice or "Historical candles unavailable" | Verified `CashCandlesResponse` |
| **X-Ray Signal Detail**| `/api/signals` | `GET` | `symbol`, `strategy_id`, `provider`, `segment`, `start_time`, `end_time`, `limit=200`, `offset=0` | Exact join on candidate identity/watermark; displays `UNAVAILABLE` if match count !== 1 | Verified `SignalItem` |
| **Paper Ledger** | `/api/paper-portfolio` | `GET` | Strictly requires `account_id` (1..128 chars) | Displays "No Reconciled Paper Account" if unconfigured; displays audit badges | Verified `PaperPortfolioResponse` |
| **Paper Accounts** | `/api/paper-accounts` | `GET` | `limit=100`, optional `cursor` | Used for verified account discovery when `health.paper_account_id` is null | Verified `PaperAccountsResponse` |
| **Options Lab** | `/api/oi-snapshots` | `GET` | `limit=10` | Displays "Contract viability comes first" notice and historical previews | Verified `OiSnapshotItem` |
| **Strategies** | `/api/backtest-eligibility` | `GET` | No query consumed | Displays 5 baseline strategies + 2 gated research algorithms | Verified eligibility DTO |
| **System Settings** | `/api/config` | `GET` | No query consumed | Read-only configuration dump with locked production toggles | Verified `ConfigResponse` |
| **Scan Telemetry** | `/api/scans` | `GET` | `limit=10`, `offset=0` | Retained scan execution table with duration, signals, and broker mode | Verified `ScanListResponse` |
| **Rank History / Delta**| *Not Implemented in Backend* | `N/A` | Endpoint does not exist | Displays "Backend Rank History endpoint (/api/rank-history) not yet provisioned. Showing single-snapshot priority." | Truthful limitation notice |
| **Manual Execution**| *Blocked by Policy* | `N/A` | No POST execution buttons exist in UI | Displays paper trigger reasons (`CONFLICTING_OPEN_POSITION`) read-only | Enforces read-only safety |

---

## 4. Key Design Corrections & Invariant Enforcement

### 4.1. Mobile Responsive Sidebar Resolution
- **Defect in Stitch HTML Reference**: The Stitch mobile template retained `<aside class="fixed w-56">` with `pl-56`, causing a persistent 224px dark bar that occluded 57% of mobile screens (390px iPhone viewport).
- **Production Correction**: Converted `Sidebar.tsx` to desktop-only (`hidden md:flex`). Implemented `MobileNav.tsx` featuring an institutional bottom tab bar (`Pulse`, `Opps`, `Paper`, `Health`, `More`) and a touch-friendly slide-over menu for secondary views.

### 4.2. Server-Provided Priority Ranking Preservation
- Client-side sorting never calculates an alternative score or re-ranks candidates.
- All candidate orderings strictly follow server-provided `rank` or explicit user table sort within the verified server snapshot.

### 4.3. Multi-Page Snapshot Invariant Enforcement (`snapshot-collector.ts`)
- Multi-page ranking retrieval pins subsequent pages to the first page's `run_id`.
- Enforces snapshot invariants: halts if `version`, `work_id`, `scope`, `reference`, `valid_until`, or `policy` changes across pages, validates row uniqueness, clamps at maximum 512 rows, and marks snapshots as expired when server `valid_until` has elapsed.

### 4.4. Paper Rejection Reason Code: `CONFLICTING_OPEN_POSITION`
- Added full support for the new H1 additive paper rejection reason: `CONFLICTING_OPEN_POSITION`.
- X-Ray diagnostics drawer properly renders this status chip and explains that entry was withheld due to an existing opposing position.

### 4.5. Strict CSP and Asset Bundling
- `index.html` loads zero external CDNs, scripts, or fonts.
- All 15+ institutional icons are embedded as pure SVG components.
- Font family defaults cleanly to local system sans-serif (`ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto`) and monospace (`ui-monospace, SFMono-Regular, Menlo, Consolas`).
- Production build emits only allowlisted extensions (`.html`, `.css`, `.js`), generating zero `.map` files.

---

## 5. Verification & Test Results

### 5.1. Real Loopback Integration Test Suite (`test_ui_api_loopback_parity.py`)
Command: `cd indian_fo_signal_bot_v1; python -m unittest test_ui_api_loopback_parity.py`  
Result: **10 of 10 tests passed (100%) in 0.423s**
- `test_rankings_alias_does_not_exist_and_returns_404`: Confirms `/api/rankings` returns 404 `NotFoundError`.
- `test_opportunity_rankings_rejects_page_parameter_with_400`: Confirms `/api/opportunity-rankings?page=1` returns 400 `Invalid ranking query.`
- `test_cash_candles_batch_does_not_exist_and_returns_404`: Confirms `/api/cash-candles-batch` returns 404 `NotFoundError`.
- `test_cash_candles_requires_both_run_id_and_batch_id`: Confirms `/api/cash-candles` rejects unknown query params with 400, returns 404 for missing/invalid batch, and returns 200 with OHLCV items when both `run_id` and matching `batch_id` are provided.
- `test_signal_lineage_does_not_exist_and_returns_404`: Confirms `/api/signal-lineage` returns 404 `NotFoundError`.
- `test_signals_supports_exact_filter_parameters`: Confirms `/api/signals` returns 200 list envelope with items matching filter parameters.
- `test_paper_portfolio_requires_account_id_and_rejects_unscoped_request`: Confirms `/api/paper-portfolio` without `account_id` returns 400 `Invalid paper-report query.`; with `account_id` returns 200.
- `test_paper_accounts_discovery_returns_200`: Confirms `/api/paper-accounts` returns 200 with configured accounts.
- `test_health_dto_exact_structure`: Confirms `/api/health` returns 200 with broker, scheduler, database, operations, paper_account_id; asserts non-existence of `market_state` and `clock_drift`.
- `test_host_origin_security_and_vite_proxy_behavior`: Confirms loopback Host/Origin enforcement (200 on same origin, 403 on mismatched Origin from `http://localhost:5173` without proxy header rewrite, 403 on cross-site fetch).

### 5.2. Vitest Frontend Unit & Component Suite
Command: `cd frontend; npm.cmd run test`  
Result: **30 of 30 tests passed (100%) across 4 test suites**
- `src/test/api-client.test.ts`: 14 tests passed
  - GET execution with same-origin credentials, no-store, Accept json.
  - Query parameter encoding and null/undefined filtering.
  - Strict paths for `/api/opportunity-rankings`, `/api/cash-candles`, `/api/scan-lineage`, `/api/signals`, `/api/paper-portfolio`, `/api/paper-accounts`, `/api/health`, `/api/config`.
  - Rejection of invalid account ID in `getPaperPortfolio` before dispatch.
  - Rejection of missing `run_id` or `batch_id` in `getCashCandles`.
- `src/test/snapshot-collector.test.ts`: 5 tests passed
  - Pinned `run_id` across multi-page retrieval.
  - Maximum 512 total candidate boundary enforcement.
  - Invariant consistency and deadline calculation.
- `src/test/time.test.ts`: 7 tests passed
  - IST/ISO timezone normalization, leap year validation, Indian number formatting.
- `src/test/components.test.tsx`: 4 tests passed
  - Shell rendering and Pulse view.
  - Opportunities table navigation, candidate inspection, 5m candlestick chart, and X-Ray drawer with `CONFLICTING_OPEN_POSITION`.
  - Displays `UNAVAILABLE` in X-Ray drawer when signal join cannot be proven.
  - Displays truthful unconfigured paper portfolio notice when `account_id` is null.

### 5.3. TypeScript Strict Typecheck
Command: `cd frontend; npm.cmd run typecheck`  
Result: **0 errors, 0 warnings**

### 5.4. Production Build Validation
Command: `cd frontend; npm.cmd run build`  
Result: **Vite v5.4.21 production build successful**
```
dist/index.html                   0.71 kB │ gzip:  0.42 kB
dist/assets/index-DaFh9Oar.css   22.99 kB │ gzip:  5.30 kB
dist/assets/index-yupbAula.js   255.38 kB │ gzip: 69.93 kB
✓ built in 2.23s
```

### 5.5. Existing Vanilla Terminal Regression Suite
Command: `cd indian_fo_signal_bot_v1; node --test test_terminal_opportunities.js test_terminal_clock.js`  
Result: **17 of 17 tests passed (100%)** under both `TZ=UTC` and `TZ=America/New_York`.

---

## 6. Host / Origin Security & Vite Proxy Runtime Parity

The Python backend enforces local loopback security in `server.py:1351`:
1. `Host` header port must match the server's actual listening port.
2. `Origin` header must either be absent or match `http://` + Host.
3. `Sec-Fetch-Site` header must not be `cross-site`.

When developers run `npm run dev` with Vite, the browser originates requests from `http://localhost:5173`. Vite's proxy has been configured in `frontend/vite.config.ts` via `proxy.on('proxyReq')` to rewrite `Origin: http://127.0.0.1:8000` and `Sec-Fetch-Site: same-origin`. This ensures local development seamlessly satisfies `server.py` local same-origin enforcement.

---

## 7. Checkpoint U1-C Completion Status

- [x] Corrected all API paths to canonical backend interfaces (`/api/opportunity-rankings`, `/api/cash-candles`, `/api/signals`, `/api/paper-portfolio`).
- [x] Verified ranking pagination uses `limit` + `offset` (rejection of `page`).
- [x] Enforced strict required parameters for `cash-candles` (`run_id` + `batch_id`).
- [x] Clarified signal join invariants with strict `UNAVAILABLE` fallback.
- [x] Implemented paper account validation and `/api/paper-accounts` discovery.
- [x] Realigned health DTO eliminating assumed `market_state` or `clock_drift` fields.
- [x] Verified loopback Host/Origin restrictions with proxy header rewrite.
- [x] Added live disposable loopback integration test suite (`test_ui_api_loopback_parity.py`).
- [x] 100% test pass rate across all suites (10 Python loopback + 30 Vitest + 17 Node regression).
- [x] Clean production build and strict TypeScript verification.
