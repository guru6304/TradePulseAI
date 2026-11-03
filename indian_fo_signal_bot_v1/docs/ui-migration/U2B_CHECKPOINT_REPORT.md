# TradePulse AI — U2-B Checkpoint Implementation Report
**Stage 4 / Agent 3 / React UI Migration — Real Browser Acceptance & Security Hardening**  
**Date:** 2026-11-03  
**Worktree:** `C:\Users\91810\TradePulseAI-Worktrees\ui`  
**Branch:** `feature/new-ui`  
**Starting Git Commit (U2 Corrected):** `4df14b7`  
**Authoritative Contracts & Reference Documents:**
- `TP_UI_API_CONTRACT_V1.md`
- `TP_STRATEGY_INTEGRATION_CONTRACT_V1.md`
- `TRADEPULSE_MASTER_STATUS.md`
- R1 Ranking Audit: `astra_rank_independent_review_20261026_01.md` & `rank_history.py`
- Approved Google Stitch Design Specifications: Mobile (390px), Tablet (768px), Desktop (1440px)

---

## 1. Executive Summary

Checkpoint **U2-B (Real Browser Acceptance)** executes genuine HTTP-served headless browser testing against the compiled React + TypeScript frontend and a canonical Python API backend, resolving documentation and contract discrepancies from previous checkpoints, hardening local proxy security, and capturing a complete visual evidence portfolio.

### Key Achievements in U2-B:

1. **Genuine Real-Browser Acceptance (Zero ES Module `file://` Shortcuts)**:
   - Developed a controlled local HTTP serving and proxy harness (`run_browser_acceptance.mjs`) serving production build assets on `http://127.0.0.1:5173` while proxying `/api/*` requests to an offline Python backend on `http://127.0.0.1:8000`.
   - Automated Headless Chromium 155 (`chrome.exe`) directly via the Chrome DevTools Protocol (CDP) using Node v24's native WebSocket implementation.
   - Clearly separated real-browser evidence from jsdom unit tests and Python API unit tests.

2. **Multi-Viewport Visual & Responsive Validation (31 Captured Screenshots)**:
   - Validated all 8 application views across three standard form factors:
     - **Mobile (390x844)**: iPhone 14 geometry with thumb-driven `MobileNav` and "More" action sheet.
     - **Tablet (768x1024)**: iPad portrait layout with sidebar navigation and responsive KPI cards.
     - **Desktop (1440x900)**: Institutional dark terminal layout with sticky rank headers and X-Ray drawer.
   - Confirmed **zero horizontal overflow / page clipping** across all viewports and views (`horizontalOverflow: PASS`).
   - Saved 31 high-resolution visual evidence artifacts directly into `indian_fo_signal_bot_v1/docs/project/ui-evidence/`.

3. **X-Ray Focus Management & Accessibility Hardening**:
   - Implemented accessible keyboard focus management in `XRayDrawer.tsx`:
     - When the drawer opens, `document.activeElement` (the triggering Inspect button) is retained, and focus is shifted to the drawer's Close button.
     - Dismissal via `Escape` key, backdrop click, or close button automatically restores focus to the triggering Inspect button.
   - Tested and verified modal dismissal and focus restoration in real Chromium.

4. **Reconciliation of Rank History & Predecessor Rank Contracts**:
   - Resolved the misconception from U1 and U2 reports claiming that rank history was missing due to an unexposed `/api/rank-history` endpoint.
   - Verified against `TP_UI_API_CONTRACT_V1.md` and R1 ranking audit (`astra_rank_independent_review_20261026_01.md`) that no separate `/api/rank-history` endpoint was ever part of the contract.
   - Confirmed that retained ranking history is natively embedded within `/api/opportunity-rankings` via `previous_rank`, `rank_change_reason`, `component_changes`, `historical_rows`, and `snapshot.previous_snapshot`.
   - Verified that the UI faithfully surfaces predecessor rank badges (`(prior #3)` / `(new)`) without fabricating synthetic score deltas or routes.

5. **Proxy Security Hardening (Socket `remoteAddress` Loopback Verification)**:
   - Hardened `frontend/vite.config.ts` proxy middleware in both development (`server.proxy`) and preview (`preview.proxy`).
   - Replaced reliance on client-supplied `Host` headers alone by inspecting the underlying TCP socket `req.socket.remoteAddress` for loopback addresses (`127.0.0.1`, `::1`, `::ffff:127.0.0.1`), combined with client `Host` and `Origin` validation before applying `Origin` and `Sec-Fetch-Site` rewrites.

6. **Preservation of Safety & Trading Invariants**:
   - Verified that the frontend contains zero trade execution controls, broker order forms, or credentials.
   - Verified correct rendering of the paper rejection reason code `CONFLICTING_OPEN_POSITION`.
   - Verified fallback to `UNAVAILABLE` when candidate signal lineage cannot be joined.

---

## 2. Exact Changed Files

| File Path | Nature of Change | Purpose / Description |
| :--- | :--- | :--- |
| `run_browser_acceptance.mjs` | Created | Standalone, reproducible headless Chromium browser acceptance test runner using Chrome DevTools Protocol (CDP) over native WebSocket; orchestrates HTTP serving and Python backend lifecycle. |
| `indian_fo_signal_bot_v1/offline_backend_server.py` | Created | Deterministic, offline Python test backend fixture using `DashboardRequestHandler` from `server.py` with zero operational database mutation, zero live broker connection, and complete 25-candidate ranking, lineage, candle, and paper-rejection fixtures. |
| `frontend/package.json` | Modified | Added npm script `"test:browser": "node ../run_browser_acceptance.mjs"` for convenient developer execution from the `frontend/` directory. |
| `frontend/src/views/XRayDrawer.tsx` | Modified | Implemented accessible focus management (`useRef`), capturing triggering Inspect button on open, shifting focus to close button, and restoring focus on modal dismissal. |
| `frontend/vite.config.ts` | Modified | Hardened development and preview proxy header rewriting using underlying TCP socket IP (`req.socket.remoteAddress`) loopback verification in conjunction with Host and Origin validation. |
| `indian_fo_signal_bot_v1/docs/project/ui-evidence/*.png` (31 files) | Created | Full suite of real browser screenshot artifacts captured across Desktop, Tablet, and Mobile viewports for all 8 views and interactions. |
| `indian_fo_signal_bot_v1/docs/ui-migration/U2B_CHECKPOINT_REPORT.md` | Modified | Comprehensive U2-B acceptance report, browser parity analysis, rank history reconciliation, screenshot inventory, and verification evidence. |

---

## 3. Real Browser Acceptance Results & Methodology

### 3.1. Methodology Distinction

| Test Layer | Harness | Target Environment | Coverage |
| :--- | :--- | :--- | :--- |
| **Real Browser Acceptance** | Chrome DevTools Protocol (CDP) over Node WebSocket | Headless Chromium 155 (`http://127.0.0.1:5173`) | Rendered DOM, network requests, layout metrics, focus management, CSS transforms, screenshot artifacts |
| **Component & Unit Testing** | Vitest 2.1.9 + jsdom | Node.js virtual DOM environment | Component lifecycles, React Context state machines, mock API clients, mock timers, event dispatching |
| **Backend Loopback Parity** | Python `unittest` | Live Python `server.py` HTTP loopback socket (`127.0.0.1:0`) | Exact HTTP status codes, query parameter parsing, CORS/Host rejection, required DTO schema fields |
| **Legacy Regressions** | Node test runner (`node --test`) | Vanilla Node terminal harnesses | Timezone invariance (UTC, America/New_York), snapshot bounds, pagination clamps, clock drift |

### 3.2. Multi-Viewport Real Browser Validation Matrix

Each view was navigated to over HTTP (`http://127.0.0.1:5173/#/{view}`), evaluated for DOM content and layout width constraints, and captured to a PNG screenshot:

| View Name | Route | Desktop (1440x900) | Tablet (768x1024) | Mobile (390x844) | Horizontal Overflow Check |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Pulse** | `#/pulse` | PASS (`342 KB`) | PASS (`241 KB`) | PASS (`171 KB`) | PASS (No clipping) |
| **Opportunities** | `#/opportunities` | PASS (`315 KB`) | PASS (`241 KB`) | PASS (`174 KB`) | PASS (No clipping) |
| **Opportunities (Page 2)** | `#/opportunities` | PASS (`261 KB`) | PASS (`188 KB`) | PASS (`130 KB`) | PASS (No clipping) |
| **X-Ray (Open)** | `#/opportunities` | PASS (`300 KB`) | PASS (`138 KB`) | PASS (`86 KB`) | PASS (No clipping) |
| **X-Ray (Diagnostics Tab)**| `#/opportunities` | PASS (`295 KB`) | PASS (`138 KB`) | PASS (`86 KB`) | PASS (No clipping) |
| **Options Lab** | `#/options` | PASS (`159 KB`) | PASS (`127 KB`) | PASS (`104 KB`) | PASS (No clipping) |
| **Strategies & Research** | `#/strategies` | PASS (`359 KB`) | PASS (`275 KB`) | PASS (`198 KB`) | PASS (No clipping) |
| **Paper Portfolio** | `#/paper` | PASS (`210 KB`) | PASS (`179 KB`) | PASS (`138 KB`) | PASS (No clipping) |
| **Health & Diagnostics** | `#/health` | PASS (`225 KB`) | PASS (`187 KB`) | PASS (`143 KB`) | PASS (No clipping) |
| **Admin Research** | `#/admin-research` | PASS (`198 KB`) | PASS (`167 KB`) | PASS (`135 KB`) | PASS (No clipping) |
| **Mobile "More" Sheet** | `#/pulse` (mobile) | N/A | N/A | PASS (`149 KB`) | PASS (No clipping) |

### 3.3. Complete 31-Screenshot Visual Evidence Inventory

All 31 screenshots are saved in `indian_fo_signal_bot_v1/docs/project/ui-evidence/` and verified:

| # | Artifact Filename | Viewport | View / State | Visual Verification Target |
| :-: | :--- | :--- | :--- | :--- |
| 1 | `tradepulse_u2b_pulse_desktop.png` | Desktop (1440x900) | Pulse | Top shortlist cards, 4-column KPI stats, "What Changed" delta cards |
| 2 | `tradepulse_u2b_pulse_tablet.png` | Tablet (768x1024) | Pulse | Responsive tablet layout, stat grid reflow, sidebar navigation |
| 3 | `tradepulse_u2b_pulse_mobile.png` | Mobile (390x844) | Pulse | 2-column KPI stats, bottom `MobileNav` bar, compact summary cards |
| 4 | `tradepulse_u2b_opportunities_desktop.png` | Desktop (1440x900) | Opportunities | 20-candidate table, server ranking `#1..#20`, predecessor rank `(prior #3)` |
| 5 | `tradepulse_u2b_opportunities_tablet.png` | Tablet (768x1024) | Opportunities | Table horizontal scroll container, column alignment, sticky headers |
| 6 | `tradepulse_u2b_opportunities_mobile.png` | Mobile (390x844) | Opportunities | Mobile horizontal swiping, compact row badges, inspect action buttons |
| 7 | `tradepulse_u2b_opportunities_page2_desktop.png` | Desktop (1440x900) | Opps (Page 2) | Candidates `#21..#25`, client pagination info `"Page 2 of 2"`, disabled Next button |
| 8 | `tradepulse_u2b_opportunities_page2_tablet.png` | Tablet (768x1024) | Opps (Page 2) | Tablet pagination bar layout, enabled Previous button, disabled Next button |
| 9 | `tradepulse_u2b_opportunities_page2_mobile.png` | Mobile (390x844) | Opps (Page 2) | Mobile pagination bar responsiveness, thumb-accessible paging buttons |
| 10 | `tradepulse_u2b_xray_open_desktop.png` | Desktop (1440x900) | X-Ray Drawer | Sliding inspector panel, 5m candlestick chart, active close button focus |
| 11 | `tradepulse_u2b_xray_open_tablet.png` | Tablet (768x1024) | X-Ray Drawer | 500px tablet drawer overlay, dimmed background backdrop blur |
| 12 | `tradepulse_u2b_xray_open_mobile.png` | Mobile (390x844) | X-Ray Drawer | Full-width immersive mobile sheet, top close control, zero lookahead notice |
| 13 | `tradepulse_u2b_xray_diagnostics_desktop.png` | Desktop (1440x900) | X-Ray (Diagnostics) | Amber `CONFLICTING_OPEN_POSITION` badge, cryptographic source lineage |
| 14 | `tradepulse_u2b_xray_diagnostics_tablet.png` | Tablet (768x1024) | X-Ray (Diagnostics) | Tablet paper decision status, source digest SHA-256, opportunity key |
| 15 | `tradepulse_u2b_xray_diagnostics_mobile.png` | Mobile (390x844) | X-Ray (Diagnostics) | Mobile paper trigger decision, reason code display, read-only footer |
| 16 | `tradepulse_u2b_options_desktop.png` | Desktop (1440x900) | Options Lab | Index strike selector, unavailable options chain notice, institutional styling |
| 17 | `tradepulse_u2b_options_tablet.png` | Tablet (768x1024) | Options Lab | Tablet options layout, strike table placeholder, clear unavailable states |
| 18 | `tradepulse_u2b_options_mobile.png` | Mobile (390x844) | Options Lab | Mobile options summary, compact parameters, no fictitious options data |
| 19 | `tradepulse_u2b_strategies_desktop.png` | Desktop (1440x900) | Strategies | 4 institutional strategy catalog cards, parameters, indicators, rules |
| 20 | `tradepulse_u2b_strategies_tablet.png` | Tablet (768x1024) | Strategies | 2-column strategy grid, setup parameters, entry/invalidation formulas |
| 21 | `tradepulse_u2b_strategies_mobile.png` | Mobile (390x844) | Strategies | Stacked strategy catalog cards, readable fonts, touch-friendly scrolling |
| 22 | `tradepulse_u2b_paper_desktop.png` | Desktop (1440x900) | Paper Portfolio | Reconciled ledger accounting, capital stats, open simulated positions |
| 23 | `tradepulse_u2b_paper_tablet.png` | Tablet (768x1024) | Paper Portfolio | Tablet portfolio layout, P&L metrics, zero real-broker trading controls |
| 24 | `tradepulse_u2b_paper_mobile.png` | Mobile (390x844) | Paper Portfolio | Stacked portfolio accounting cards, position table with horizontal scroll |
| 25 | `tradepulse_u2b_health_desktop.png` | Desktop (1440x900) | System Health | Engine status, scheduler loop, broker connectivity, scan execution logs |
| 26 | `tradepulse_u2b_health_tablet.png` | Tablet (768x1024) | System Health | Tablet diagnostic metrics, recent scan history table, clock sync status |
| 27 | `tradepulse_u2b_health_mobile.png` | Mobile (390x844) | System Health | Mobile health cards, uptime status badge, scan cycles executed |
| 28 | `tradepulse_u2b_admin-research_desktop.png` | Desktop (1440x900) | Admin Research | Historical datasets table, backtest run inspector, parameter filters |
| 29 | `tradepulse_u2b_admin-research_tablet.png` | Tablet (768x1024) | Admin Research | Tablet dataset search, backtest runs query, execution mode badges |
| 30 | `tradepulse_u2b_admin-research_mobile.png` | Mobile (390x844) | Admin Research | Mobile dataset listings, backtest status, read-only administration |
| 31 | `tradepulse_u2b_mobile_more_sheet.png` | Mobile (390x844) | Mobile More Sheet | Thumb-accessible popover menu (`role="menu"`), secondary route links |

### 3.4. Exact Execution Commands, Prerequisites & Verification Limitations

#### Prerequisites
- **Node.js**: v20.0.0 or later (tested on Node v24.2.0; requires native global `WebSocket` support).
- **Python**: 3.10 or later (tested on Python 3.12.3; standard library + bot dependencies in `indian_fo_signal_bot_v1/requirements.txt`).
- **Browser**: Google Chrome, Chromium, or Microsoft Edge installed on the host system.

#### Exact Commands for Reproducibility
```powershell
# 1. From repository root (recommended):
node run_browser_acceptance.mjs

# 2. Or from frontend directory:
cd frontend
npm run test:browser

# 3. Optional custom configuration via environment variables:
$env:CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:BACKEND_PORT="8000"
$env:FRONTEND_PORT="5173"
$env:CHROME_DEBUG_PORT="9222"
node run_browser_acceptance.mjs
```

#### Automated Harness Architecture
1. **Frontend Production Build**: Runs `npm.cmd run build` inside `frontend/` generating optimized assets in `frontend/dist`.
2. **Offline Backend Process**: Spawns `python -u indian_fo_signal_bot_v1/offline_backend_server.py 8000`. Uses `verify_offline.offline_network` to block all external socket requests. Serves canonical DTO endpoints using `DashboardRequestHandler` from `server.py`.
3. **HTTP Static & Proxy Server**: Binds to `127.0.0.1:5173`, serves static files from `frontend/dist`, and proxies `/api/*` to `127.0.0.1:8000` with same-origin header emulation.
4. **Headless Chromium Orchestration**: Spawns Chrome in `--headless=new` with remote debugging port 9222. Connects directly via native `WebSocket` over Chrome DevTools Protocol (`Page.*`, `Runtime.*`, `Emulation.*`, `Input.*`).
5. **Deterministic Tear-Down**: Closes WebSocket, terminates Chrome process, shuts down Node HTTP server, terminates Python backend process, and deletes temporary `--user-data-dir`.

#### Verification Limitations
- **Chromium Mobile Emulation**: Mobile Safari (WebKit on iOS) rendering is emulated using Chromium's mobile device metrics override (390×844, Device Scale Factor 2, `mobile: true`, touch emulation). Pixel-perfect WebKit rendering (e.g. iOS rubber-band scrolling) requires a physical Apple device or macOS Safari test runner.
- **Offline Backend Fixture**: Uses deterministic in-memory fixtures. No real Upstox or Angel One broker credentials, active market WebSocket feeds, or live exchange order APIs were connected. Operational SQLite databases (`trade_pulse.db`, `paper_portfolio.db`) were strictly untouched.

---

## 4. Interaction, Focus, and Safety Evidence

### 4.1. X-Ray Modal Focus Management & Dismissal
- **Trigger Capture**: When a user activates `Inspect` on a candidate row (e.g. `Inspect RELIANCE`), the component stores `document.activeElement`.
- **Initial Focus**: Once mounted, focus is programmatically shifted to the modal Close button (`closeButtonRef.current?.focus()`). Tested via CDP: `focusedButton="Close drawer"` (`PASS`).
- **Escape Key Dismissal**: Dispatched native keyboard events (`rawKeyDown`, `keyUp` for `Escape` / code 27). Verified modal removed from DOM (`dialogClosed: PASS`).
- **Focus Restoration**: Verified that `document.activeElement` returns to the triggering button (`activeElement aria-label="Inspect RELIANCE"`: `PASS`).

### 4.2. Paper Trigger Decision & Rejection Reason Code
- In the X-Ray drawer "Paper & Lineage" tab, the `paper_decision` payload is inspected.
- Verified display of rejection reason code `CONFLICTING_OPEN_POSITION` highlighted in amber (`text-tp-caution`):
  - Verified across Desktop, Tablet, and Mobile viewports (`PASS`).
  - Read-only action bar strictly displays `"V1 Read-Only Terminal"` with zero buy/sell buttons.

### 4.3. Client Pagination Controls (20-Row Boundary Enforcement)
- Tested with a 25-candidate dataset:
  - **Page 1**: Displays `"Page 1 of 2 · 25 matching / 25 retained candidates"`. `Previous` button is `disabled`, `Next` button is `enabled` (`PASS`).
  - **Navigation**: Clicked `Next`.
  - **Page 2**: Displays `"Page 2 of 2 · 25 matching / 25 retained candidates"`. `Previous` button is `enabled`, `Next` button is `disabled` (`PASS`).
  - **Navigation Back**: Clicked `Previous` returning to Page 1 (`PASS`).

### 4.4. Mobile Navigation & "More" Bottom Sheet
- Tested at 390px viewport width:
  - Mobile bottom navigation bar renders 4 primary tabs (`Pulse`, `Opps`, `Options`, `Paper`).
  - Clicked "More destinations" button (`aria-label="More destinations"`).
  - Verified popover bottom sheet mounts with `role="menu"` containing `Strategies`, `Health`, and `Admin Research`.
  - Captured `tradepulse_u2b_mobile_more_sheet.png`.
  - Verified clean dismissal via close button (`PASS`).

---

## 5. Contract Reconciliation: Retained Ranking History

### 5.1. Background on the "Missing Rank History" Myth
In the U1 and U2 reports, notes suggested that rank history was missing because an endpoint named `/api/rank-history` did not exist on `server.py`. 

### 5.2. Authoritative Contract & R1 Audit Grounding
An independent review of `TP_UI_API_CONTRACT_V1.md`, `rank_history.py`, and the R1 ranking audit (`astra_rank_independent_review_20261026_01.md`) confirms:
1. **No `/api/rank-history` endpoint was ever defined or intended.** Creating such an endpoint would violate the architectural contract.
2. **Retained ranking history is natively embedded within `/api/opportunity-rankings`**:
   - `current_rows[i].previous_rank`: The integer rank of the instrument in the immediate prior ranking snapshot (or `null` if newly qualified).
   - `current_rows[i].rank_change_reason`: Enum indicating why the rank changed (`"NEWLY_QUALIFIED"`, `"UNCHANGED_PRIORITY"`, `"SCORE_COMPONENT_CHANGED"`, `"RELATIVE_ORDER_CHANGED"`, `"COMPONENT_VERSION_CHANGED"`, `"SCOPE_CHANGED"`).
   - `current_rows[i].component_changes`: Dictionary detailing historical component delta scores.
   - `snapshot.previous_snapshot`: Pointer to predecessor snapshot ID and digest for cryptographic verification.
   - `historical_rows`: Full list of historical candidate rankings retained by the server.

### 5.3. Frontend Implementation Parity
The React frontend already faithfully implements this contract without any synthetic routes:
- In `OpportunitiesView.tsx`: Displays `#<rank>` alongside `(prior #<previous_rank>)` or `(new)`.
- In `PulseView.tsx`: The "What Changed" delta cards display `"Prior: #<previous_rank>"` and change reasons directly from server evidence.

---

## 6. Vite Proxy Connection Security Hardening

### 6.1. Vulnerability Analysis of Host Header Verification
In U2, the Vite proxy configuration checked:
```typescript
const clientHost = req.headers['host'] || '';
const isLocal = clientHost.startsWith('localhost:') || clientHost.startsWith('127.0.0.1:');
```
While functional for normal browser navigation, client-controlled HTTP headers such as `Host` can theoretically be spoofed by external tools or non-browser clients on adjacent network segments if the dev server was ever exposed.

### 6.2. Upgraded TCP Socket IP & Origin Verification
In `frontend/vite.config.ts`, proxy middleware in both `server.proxy` and `preview.proxy` now validates:
1. **Underlying Socket IP**: `req.socket.remoteAddress` must strictly be a loopback IP (`127.0.0.1`, `::1`, or IPv4-mapped `::ffff:127.0.0.1`).
2. **Client Host Header**: Must resolve to `localhost` or `127.0.0.1`.
3. **Incoming Origin**: If present, must strictly match local Vite ports (`http://localhost:5173`, `http://127.0.0.1:5173` for dev, or `4173` for preview).

Only when all three criteria are satisfied does the proxy append `Origin: http://127.0.0.1:8000` and `Sec-Fetch-Site: same-origin` to satisfy `server.py`'s same-origin verification.

---

## 7. Verification Test Suite Results

### 7.1. Frontend Unit & Component Tests (Vitest)
```
 ✓ src/test/snapshot-collector.test.ts (5 tests)
 ✓ src/test/time.test.ts (7 tests)
 ✓ src/test/api-client.test.ts (14 tests)
 ✓ src/test/components.test.tsx (9 tests)

 Test Files  4 passed (4)
      Tests  35 passed (35)
   Duration  21.48s
```

### 7.2. TypeScript Strict Typecheck
```
> tradepulse-frontend@1.0.0 typecheck
> tsc --noEmit
(0 errors)
```

### 7.3. Vite Production Build
```
> tradepulse-frontend@1.0.0 build
> tsc && vite build

✓ 50 modules transformed.
dist/index.html                   0.71 kB │ gzip:  0.42 kB
dist/assets/index-B3szvOGC.css   23.11 kB │ gzip:  5.31 kB
dist/assets/index-CQUwDFu2.js   256.11 kB │ gzip: 69.99 kB
✓ built in 6.74s
```

### 7.4. Python Backend Loopback Parity Tests
```
..........
----------------------------------------------------------------------
Ran 10 tests in 0.430s

OK
```

### 7.5. Node Terminal Regressions
```
✔ actual terminal clock and chart contract under TZ=UTC (301ms)
✔ actual terminal clock and chart contract under TZ=America/New_York (440ms)
✔ collects more than 100 ranked rows with API limit 100 and snapshot-pinned later pages (53ms)
✔ full-snapshot search reaches a candidate beyond the first API page (21ms)
✔ zero matches keep reset and paging recovery; a shortened last page clamps locally (25ms)
✔ mixed rank versions and malformed page/duplicate identities withhold the entire collection (37ms)
✔ rejects rank collection larger than 512 rather than reading an unbounded list (6ms)
✔ local filter rerender preserves the focused filter and resets page (19ms)
✔ reordered refresh preserves a focused candidate without moving a user-owned search focus (8ms)
✔ selected X-Ray withholds old prices while refreshing then rebinds the same source identity (15ms)
✔ removed or source-revised selected candidates cannot retain old price evidence (13ms)
✔ expiry invalidates selected X-Ray and late signal completion cannot restore it (8ms)
✔ a late older ranking read cannot replace the later accepted snapshot (4ms)
✔ closing a popup cancels a pending detail and returns focus to its exact surviving candidate (5ms)
✔ signal lookup narrows supported source/time fields and never sends LONG as stored direction (6ms)
✔ X-Ray exposes retained zones, checks, warnings, maturity, context and paper trigger safely (5ms)
✔ health refresh clears the old session label on loading and error (13ms)
ℹ tests 17 | pass 17 | fail 0
```

### 7.6. Whitespace and Git Cleanliness
```
git diff --check -> Clean (0 whitespace errors)
```

---

## 8. Acceptance Verdict & Recommendation

**Verdict: ACCEPTED FOR CHECKPOINT U2-B REVIEW**

The React UI migration on `feature/new-ui` has achieved complete real-browser verification across Mobile, Tablet, and Desktop viewports using genuine HTTP serving and headless Chromium DevTools Protocol automation. X-Ray focus management, Escape dismissal, focus restoration, predecessor rank display, paper decision reasons, 20-row client pagination, and proxy loopback security are fully validated and backed by 31 real screenshot artifacts.

All changes are staged locally on `feature/new-ui`. No commits have been pushed to remote origin, no branches have been merged into `main`/`dev`, and no U3 tasks have been started.
