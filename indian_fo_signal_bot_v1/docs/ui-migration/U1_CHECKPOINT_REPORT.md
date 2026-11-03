# TradePulse AI — U1 Checkpoint Implementation Report
**Stage 4 / Agent 3 / React UI Migration**  
**Date:** 2026-11-03  
**Worktree:** `C:\Users\91810\TradePulseAI-Worktrees\ui`  
**Branch:** `feature/new-ui`  
**Baseline Git Commit:** `627b61c`  

---

## 1. Executive Summary

The U1 checkpoint delivers the complete, self-contained modern frontend foundation for **TradePulse AI**, migrating from the standalone vanilla terminal prototype to a strict, production-grade **React 18 + TypeScript + Vite + Tailwind CSS** architecture.

The implementation faithfully reflects the approved **Stitch Institutional Terminal Precision** design (`C:\Users\91810\TradePulseAI-References\Stage2-UI`) while strictly adhering to the immutable contracts:
- `TP_UI_API_CONTRACT_V1.md`
- `TP_STRATEGY_INTEGRATION_CONTRACT_V1.md`
- `TRADEPULSE_MASTER_STATUS.md`

All code is contained within the `frontend/` directory, completely preserving the existing Python backend (`server.py`) and the vanilla terminal (`public/terminal.*`) as zero-risk fallbacks.

---

## 2. Implemented Architecture & Component Hierarchy

```
frontend/
├── index.html                 # Dark mode, CSP-safe, zero external fonts/CDNs
├── package.json               # React 18, Vite 5, Tailwind 3, Vitest 2
├── tsconfig.json              # Strict TypeScript 5.6 configuration
├── vite.config.ts             # Base './', API proxy to localhost:8000, JSDOM test runner
├── tailwind.config.js         # Stitch institutional dark palette & design tokens
└── src/
    ├── main.tsx               # Root entrypoint
    ├── App.tsx                # TerminalProvider wrapper + Shell
    ├── index.css              # Custom scrollbars, tabular numbers, typography
    ├── types/
    │   └── api.ts             # Strict TypeScript definitions for all backend endpoints
    ├── utils/
    │   └── time.ts            # Timezone-safe IST parsing, leap year validation, INR formatters
    ├── api/
    │   ├── client.ts          # Read-only GET/HEAD same-origin client (no POST/PUT/DELETE)
    │   └── snapshot-collector.ts # Bounded multi-page snapshot pagination & invariant enforcement
    ├── context/
    │   └── TerminalContext.tsx# Reactive state: routing, health, snapshots, selection, lifecycle
    ├── components/
    │   ├── common/
    │   │   ├── Icons.tsx      # Bundled SVG icons matching Stitch icon specifications
    │   │   └── StatusBadge.tsx# Qualified, Radar, Long, Short, Paper, Stale status chips
    │   └── layout/
    │       ├── Shell.tsx      # Responsive desktop/tablet/mobile viewport container
    │       ├── Header.tsx     # Institutional banner, clock, search bar, GET refresh
    │       ├── Sidebar.tsx    # Desktop 224px left navigation (hidden on mobile)
    │       └── MobileNav.tsx  # Mobile bottom bar + hamburger drawer (390px responsive)
    └── views/
        ├── PulseView.tsx      # Shortlist hero cards, zero-signal truthful waiting state, KPIs
        ├── OpportunitiesView.tsx # Canonical priority ranking table, filter tabs, run watermark ribbon
        ├── XRayDrawer.tsx     # Candidate inspect drawer: factor breakdown, 5m lineage, diagnostics
        ├── CandleChart.tsx    # Retained 5m SVG candlestick chart + accessible OHLC data table
        ├── OptionsView.tsx    # Derivatives overview (truthful mock/unsupported notification)
        ├── StrategiesView.tsx # Active pipeline strategy registry & parameter inspection
        ├── PaperView.tsx      # Virtual execution ledger, portfolio summary & rejection auditor
        ├── HealthView.tsx     # Backend heartbeat, clock drift, Upstox connectivity inspector
        └── AdminResearchView.tsx # Read-only calibration and research environment audit
```

---

## 3. Authoritative Route-to-API Mapping Table

Every frontend screen and data fetcher was verified against real backend endpoints defined in `TP_UI_API_CONTRACT_V1.md`. **Zero Stitch imaginary routes were invented.**

| UI Component | Backend API Endpoint | HTTP Method | Fallback / Unavailable Behavior | Parity Contract Verified |
| :--- | :--- | :--- | :--- | :--- |
| **Header / Clock** | `/api/health` | `GET` | Shows `OFFLINE` badge, amber stale warning if drift detected | Verified `HealthResponse` |
| **Pulse Hero Cards** | `/api/rankings?limit=20` | `GET` | "No Qualified Opportunities" waiting card with truthful IST timestamp | Verified `RankingResponse` |
| **Pulse KPIs** | `/api/rankings`, `/api/health` | `GET` | Displays actual candidate count, market state, and backend version | Verified `RankingResponse` |
| **Opportunities Table**| `/api/rankings?page=N&limit=20&run_id=...` | `GET` | Shows empty state "No matching candidates for filter" | Verified multi-page snapshot |
| **X-Ray Lineage** | `/api/scan-lineage?run_id=...` | `GET` | Retains snapshot timestamp, explains missing lineage | Verified `ScanLineageResponse` |
| **X-Ray 5m Candles** | `/api/cash-candles-batch?symbols=...` | `GET` | Renders zero-lookahead notice or "Historical candles unavailable" | Verified `CashCandlesResponse` |
| **X-Ray Signal Detail**| `/api/signal-lineage?symbol=...&direction=...` | `GET` | Fallback to ranking row factor scores if signal payload absent | Verified `SignalItem` |
| **Paper Ledger** | `/api/paper-portfolio` | `GET` | Displays virtual trades or empty ledger notice; audit badges | Verified `PaperPortfolioResponse` |
| **System Settings** | `/api/config` | `GET` | Read-only configuration dump with locked production toggles | Verified `ConfigResponse` |
| **Rank History / Delta**| *Not Implemented in Backend* | `N/A` | Displays "Backend Rank History endpoint (/api/rank-history) not yet provisioned. Showing single-snapshot priority." | Truthful limitation notice |
| **Manual Execution**| *Blocked by Policy* | `N/A` | No POST execution buttons exist in UI; paper trigger reasons displayed read-only | Enforces read-only safety |

---

## 4. Key Design Corrections & Invariant Enforcement

### 4.1. Mobile Responsive Sidebar Resolution
- **Defect in Stitch HTML Reference**: The Stitch mobile template retained `<aside class="fixed w-56">` with `pl-56`, causing a persistent 224px dark bar that occluded 57% of mobile screens (390px iPhone viewport).
- **Production Correction**: Converted `Sidebar.tsx` to desktop-only (`hidden md:flex`). Implemented `MobileNav.tsx` featuring an institutional bottom tab bar (`Pulse`, `Opps`, `Paper`, `Health`, `More`) and a touch-friendly slide-over menu for secondary views.

### 4.2. Server-Provided Priority Ranking Preservation
- Client-side sorting never calculates an alternative score or re-ranks candidates.
- All candidate orderings strictly follow server-provided `rank` or explicit user table sort (e.g. symbol name, RSI value) within the verified server snapshot.

### 4.3. Multi-Page Snapshot Invariant Enforcement (`snapshot-collector.ts`)
- Multi-page ranking retrieval pins subsequent pages to the first page's `run_id`.
- Enforces snapshot invariants: halts if `version` or `scope` changes across pages, validates row uniqueness, clamps at maximum 512 rows, and marks snapshots as expired when server `valid_until` has elapsed.

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

### 5.1. Vitest Frontend Unit & Component Suite
Command: `cd frontend; npm.cmd run test`  
Result: **18 of 18 tests passed (100%)**

- `src/test/time.test.ts`: 7 tests passed
  - Normalizes naive IST strings and ISO offsets to identical millisecond timestamps.
  - Rejects rollover dates (e.g., Feb 30) and non-string inputs.
  - Formats INR currency according to Indian numbering system (e.g. ₹2,845.50).
- `src/test/api-client.test.ts`: 4 tests passed
  - Executes GET requests with `same-origin`, `no-store`, and abort timeout.
  - Rejects with typed `ApiError` on HTTP 404/500 and network abort.
- `src/test/snapshot-collector.test.ts`: 5 tests passed
  - Binds subsequent pages to initial page `run_id`.
  - Enforces 512 total candidate boundary.
  - Rejects mixed versions and duplicate candidates.
- `src/test/components.test.tsx`: 2 tests passed
  - Verifies full shell rendering, status badges, and mobile navigation.
  - Validates Opportunities table pagination, candidate inspection, 5m candlestick chart rendering, and X-Ray drawer with `CONFLICTING_OPEN_POSITION`.

### 5.2. TypeScript Strict Typecheck
Command: `cd frontend; npm.cmd run typecheck`  
Result: **0 errors, 0 warnings**

### 5.3. Production Build Validation
Command: `cd frontend; npm.cmd run build`  
Result: **Vite v5.4.21 production build successful**
```
dist/index.html                   0.70 kB │ gzip:  0.42 kB
dist/assets/index-Cpea2bEA.css   22.90 kB │ gzip:  5.28 kB
dist/assets/index-CdQs3SPc.js   253.61 kB │ gzip: 69.34 kB
✓ built in 2.08s
```

### 5.4. Existing Vanilla Terminal Regression Suite
Command: `cd indian_fo_signal_bot_v1; node --test test_terminal_opportunities.js test_terminal_clock.js`  
Result: **17 of 17 tests passed (100%)** under both `TZ=UTC` and `TZ=America/New_York`.

---

## 6. Unsupported Backend Dependencies & Follow-ups for U2/U3

1. **Rank Movement History (`/api/rank-history`)**:
   - The Stitch design features a "What Changed" delta ticker. The current backend provides `run_id` and single snapshot rankings without historical rank deltas. The UI currently displays a truthful note explaining that history is not yet provisioned.
2. **Server-Side RBAC & Live Trading**:
   - Trading and execution controls are strictly omitted in the UI. The UI operates in a 100% read-only observational state.
3. **Backend Static File Serving (`server.py`)**:
   - For U2, `server.py` can be updated to optionally serve the compiled `frontend/dist/` assets under a dedicated route (e.g., `/app` or behind a flag) while preserving `/` for the legacy `public/terminal.html` until full verification.

---

## 7. Checkpoint Completion Status

- [x] Application shell with institutional styling and responsive drawer
- [x] Navigation with mobile bottom bar (fixing the 224px viewport bug)
- [x] Pulse view with hero cards and truthful zero-signal state
- [x] Opportunities view with multi-page snapshot pagination and rank preservation
- [x] Retained 5m SVG candlestick chart and accessible data table
- [x] Candidate X-Ray drawer with factor scores, geometry, and `CONFLICTING_OPEN_POSITION`
- [x] Typed same-origin API client and snapshot invariant collector
- [x] 100% test pass rate (18 Vitest tests + 17 Node regression tests)
- [x] Production build clean with zero external CDNs or sourcemaps
- [x] Worktree clean and ready for owner review at commit checkpoint
