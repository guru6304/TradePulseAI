# TradePulse AI — Phase 1F Implementation Report (`PHASE_1F_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-16  
**Scope:** Phase 1F — Fix Browser Dashboard `API DISCONNECTED` / `Failed to fetch` Under Concurrent `Promise.all()` Requests  
**Baseline Artifact:** `indian_fo_signal_bot_phase1e.zip` (53/53 tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase1f.zip` (57/57 tests passing)


## 1. Root-Cause Analysis of Browser `API DISCONNECTED` / `Failed to fetch`

### 1.1 Primary Root Cause: Single-Threaded `HTTPServer` + 5-Socket Backlog (`server.py`)
1. **Browser Request Fan-Out (`public/index.html` L1866–L1874):**
   When `http://127.0.0.1:8080/` loads in Chrome or Edge, `DOMContentLoaded` calls `refreshAllDashboardData()`, which uses `Promise.all()` to issue **7 concurrent `fetch()` requests simultaneously** (plus the browser's automatic `GET /favicon.ico`, totaling **8 simultaneous HTTP connections**):
   - `GET /api/health` (`loadHealthAndConfig`)
   - `GET /api/config` (`loadHealthAndConfig`)
   - `GET /api/signals?limit=20&offset=0` (`loadSignals`)
   - `GET /api/scans?limit=15&offset=0` (`loadScanRuns`)
   - `GET /api/oi-snapshots?index_symbol=NIFTY&limit=1&offset=0` (`refreshHeaderIndexPills`)
   - `GET /api/oi-snapshots?index_symbol=BANKNIFTY&limit=1&offset=0` (`refreshHeaderIndexPills`)
   - `GET /api/oi-snapshots?index_symbol=NIFTY&limit=20&offset=0` (`loadOiSnapshots`)
2. **Single-Threaded Blocking & Windows TCP Listen Backlog Overflow (`server.py` L6, L488):**
   In Phase 1E, `server.py` imported `HTTPServer` (`from http.server import BaseHTTPRequestHandler, HTTPServer`) and created `server = HTTPServer((host, port), DashboardRequestHandler)` in `run_server()`.
   - Python's `HTTPServer` inherits from `socketserver.TCPServer`, which is **strictly single-threaded** and sets `request_queue_size = 5` (`socket.listen(5)`).
   - Because `BaseHTTPRequestHandler` defaults to `HTTP/1.0` (closing each TCP socket after a single response), Chrome opens up to 6–8 parallel TCP connections to `127.0.0.1:8080` at the same instant.
   - On Windows, when simultaneous `SYN` packets exceed the 5-socket `listen(5)` backlog while the single server thread is busy servicing the first request (or running a ~700ms `POST /api/scan`), the Windows TCP/IP stack immediately rejects the overflow connections (`WSAECONNREFUSED`) or stalls queued requests past `AbortController` timeouts. Chrome surfaces this as `TypeError: Failed to fetch`, causing `loadHealthAndConfig()` to enter `catch (err)` and render `API DISCONNECTED` / `Backend API Unreachable at http://127.0.0.1:8080`.
3. **Why the Phase 1E 53-Test Suite Did Not Catch It (`test_bot.py` L2134–L2139):**
   `test_p1e_api_dashboard_workflows_and_xss_safe_payloads` issued sequential `urllib.request.urlopen()` calls (`h0 = get_json("/api/health")`, `c0 = get_json("/api/config")`, etc.) one at a time on a single thread, never exercising concurrent `Promise.all()` socket bursts or concurrent reads during an active scan.

### 1.2 Secondary Concurrency Hazard: Shared SQLite `:memory:` Connection & Lock Contention (`storage.py`)
Auditing `storage.py` (`SQLitePersistenceStore`) for multi-threaded request execution revealed two concurrency hazards when switching to `ThreadingHTTPServer`:
1. **Shared In-Memory Connection (`self._memory_conn`):** When `database_url` is `:memory:`, `SQLitePersistenceStore._get_connection()` returns a single shared `sqlite3.Connection` (`check_same_thread=False`). Without a mutex lock, concurrent `ThreadingHTTPServer` worker threads executing `with conn:` transactions or concurrent cursors on `self._memory_conn` can raise `sqlite3.OperationalError: cannot start a transaction within a transaction` or `sqlite3.InterfaceError`.
2. **File-Backed SQLite Contention:** When `database_url` points to a file (`sqlite:///tradepulse_phase1d.db`), `_get_connection()` opens a new connection per operation (`timeout=10.0`), but lacked an explicit `PRAGMA busy_timeout=30000;` and in-process `threading.RLock()` coordination between concurrent readers and writers.


## 2. Changed Files Summary

| File Path | Action | Explanation of Change |
| :--- | :--- | :--- |
| `server.py` | **Updated** | Replaced single-threaded `HTTPServer` with Python's standard-library `ThreadingHTTPServer` (`TradePulseThreadingHTTPServer` & `create_http_server`), configured `daemon_threads = True`, `allow_reuse_address = True`, and `request_queue_size = 64`, and added graceful handling for `BrokenPipeError` / `ConnectionResetError` if a browser client aborts a request. Kept `DashboardRequestHandler(BaseHTTPRequestHandler)` and all Phase 1D/1E routes, status codes, CORS headers, and static-file security controls intact. |
| `storage.py` | **Updated** | Added `self._db_lock = threading.RLock()` to `SQLitePersistenceStore`, increased connection `timeout=30.0`, added `PRAGMA busy_timeout=30000;` and `PRAGMA foreign_keys=ON;` on every connection, and synchronized all database read/write operations (`initialize_schema`, `check_health`, `load_mitigated_order_blocks`, `save_mitigated_order_blocks`, `save_signal`, `query_signals`, `save_oi_snapshot`, `query_oi_snapshots`, `record_scan_run`, `query_scan_runs`) under `with self._db_lock:`. |
| `test_bot.py` | **Updated** | Preserved all 53 Phase 1A–1E tests and added `TestIndianFOSignalBotPhase1F` (4 new test suites, bringing total to **57 passing tests**). |
| `README.md` | **Updated** | Updated documentation with Phase 1F overview and exact Windows PowerShell commands. |
| `docs/PHASE_1F_IMPLEMENTATION_REPORT.md` | **Added** | Complete Phase 1F root-cause analysis, concurrency audit, regression test inventory, and manual browser verification steps. |


## 3. Regression & Concurrency Tests Added (`TestIndianFOSignalBotPhase1F`)

1. **`test_p1f_server_uses_threading_http_server_and_base_request_handler`**:
   - Confirms `DashboardRequestHandler` inherits from `BaseHTTPRequestHandler` and **not** `SimpleHTTPRequestHandler`.
   - Confirms `run_server()` and `create_http_server()` instantiate `ThreadingHTTPServer` with `daemon_threads = True` and `request_queue_size >= 64`.
2. **`test_p1f_concurrent_promise_all_burst_across_all_dashboard_endpoints`**:
   - Uses a `threading.Barrier(36)` and `ThreadPoolExecutor(max_workers=36)` to fire 6 simultaneous 6-endpoint dashboard bursts (36 parallel HTTP requests to `/api/health`, `/api/config`, `/api/signals`, `/api/scans`, `/api/oi-snapshots?index_symbol=NIFTY`, and `/api/oi-snapshots?index_symbol=BANKNIFTY`) against both `:memory:` and file-backed SQLite databases.
   - Verifies all 36 simultaneous requests return `HTTP 200 OK` with valid JSON payloads in `< 3.0s`.
3. **`test_p1f_concurrent_reads_do_not_block_during_active_slow_scan_and_overlap_returns_409`**:
   - Starts a slow `POST /api/scan` request on one thread and, while the scan is paused inside `get_intraday_candles()`, fires concurrent `GET` requests to `/api/health`, `/api/config`, `/api/signals`, `/api/scans`, and `/api/oi-snapshots`, plus a second overlapping `POST /api/scan`.
   - Confirms all 5 `GET` endpoints complete in `< 1.0s` with `HTTP 200 OK` without waiting for the scan to finish, the overlapping `POST /api/scan` immediately returns `HTTP 409 Conflict` (`SKIPPED_OVERLAP`), and the primary scan completes with `HTTP 200 OK` (`COMPLETED`).
4. **`test_p1f_private_file_disclosure_remains_blocked_under_concurrent_requests`**:
   - Fires concurrent requests for 18 sensitive/traversal paths (`/.env`, `/.env.example`, `/config.py`, `/storage.py`, `/server.py`, `/brokers.py`, `/strategies.py`, `/scanner_engine.py`, `/telegram_bot.py`, `/test_bot.py`, `/tradepulse_phase1d.db`, `/README.md`, `/docs/PHASE_1E_IMPLEMENTATION_REPORT.md`, `/../.env`, `/%2e%2e/.env`, `/public/../.env`, `/public/..%2fconfig.py`, `/public/.env`) and verifies every one returns `HTTP 404 Not Found` while `/` and `/api/health` return `HTTP 200 OK`.


## 4. Compilation & Test Execution Results

### 4.1 Python Bytecode Compilation Check
```bash
python3 -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py test_bot.py
```
Result: **Exit code `0`** across all 8 Python modules.

### 4.2 Complete 57-Test Suite Execution (`test_bot.py`)
```bash
python3 test_bot.py -v
```
- **Total Tests Executed:** `57` (`20` Phase 1A + `11` Phase 1B + `8` Phase 1C + `11` Phase 1D + `3` Phase 1E + `4` Phase 1F)
- **Passed:** `57`
- **Failed:** `0`
- **Skipped:** `0`
- **Execution Time:** `17.716s` (`OK`)


## 5. Manual Browser Verification Steps & Honest Execution Disclosure

### 5.1 Honest Statement on Browser Execution
- **Automated Multi-Threaded HTTP & Concurrency Verification Executed:** All 57 automated tests in `test_bot.py` (including 36-thread simultaneous HTTP bursts against `ThreadingHTTPServer`) were executed inside the Linux VM sandbox.
- **Real GUI Browser Verification:** A real interactive Windows Chrome GUI browser test was **not** executed inside this headless sandbox VM (which has no outbound internet access to load external CDN scripts `cdn.tailwindcss.com` and `cdn.jsdelivr.net/npm/chart.js`). The exact manual Chrome verification steps for Windows PowerShell are documented below.

### 5.2 Manual Browser Verification Steps (Windows PowerShell + Chrome)
1. **Extract and enter the Phase 1F directory:**
   ```powershell
   Expand-Archive -Path .\indian_fo_signal_bot_phase1f.zip -DestinationPath .\tradepulse_phase1f -Force
   Set-Location .\tradepulse_phase1f\indian_fo_signal_bot_v1
   Copy-Item .\.env.example .\.env -Force
   ```
2. **Compile and run the 57-test suite:**
   ```powershell
   python -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py test_bot.py
   python .\test_bot.py -v
   ```
3. **Start the multi-threaded server:**
   ```powershell
   python .\server.py
   ```
   Verify the console prints:
   `TradePulse & OrderBlock Server (Phase 1F) running at http://127.0.0.1:8080`
4. **Verify in Google Chrome (`http://127.0.0.1:8080/`):**
   - Open `http://127.0.0.1:8080/` and open Chrome DevTools (**F12 $\rightarrow$ Network tab**).
   - Confirm that `/`, `/api/health`, `/api/config`, `/api/signals`, `/api/scans`, and `/api/oi-snapshots` all return **`200 OK`** in parallel with zero `Failed to fetch` errors.
   - Confirm the rose `Backend API Unreachable` banner is **hidden**, and the top header pill displays **`SIMULATED DATA MODE`** and **`NSE Live Simulation / Paper Engine (SIMULATED) • SIMULATED`**.
   - Click **`⚡ Scan Market Now`** and confirm it populates Tab 1 (`Live Signal Terminal`), Tab 2 (`Option Apex`), and Tab 4 (`Scan History`) while keeping the UI responsive.
   - Visit `http://127.0.0.1:8080/.env` and `http://127.0.0.1:8080/config.py` and confirm both return **`HTTP 404 Not Found`**.


## 6. Remaining Limitations

1. **No Live Broker Network Connectivity Claimed:** No live broker credentials are included, and live broker adapters (`AngelOneSmartAPIAdapter`, `DhanHQAdapter`, `UpstoxV2Adapter`) remain unverified against live exchange servers until credentials are configured in `.env`.
2. **Single-Process SQLite Architecture:** `ThreadingHTTPServer` + `SQLitePersistenceStore` (`threading.RLock()` + WAL mode + `busy_timeout=30000`) provides thread-safe concurrent read/write access within a single server process. Multi-process or multi-host horizontal scaling would require migrating to a client-server database such as PostgreSQL.
3. **Read-Only Analytics Only:** Live order placement remains disabled (`POST` to any route other than `/api/scan` returns `405 Method Not Allowed`).
