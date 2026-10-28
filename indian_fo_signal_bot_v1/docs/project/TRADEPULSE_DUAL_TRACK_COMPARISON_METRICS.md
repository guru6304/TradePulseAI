# TRADEPULSE AI — DUAL-TRACK COMPARISON METRICS
**Mission Version:** `TRADEPULSE-SHARED-DUAL-TRACK-2026-10-26-V1`  
**Track ID:** `ANTIGRAVITY_B`  
**Baseline ID:** `BASELINE_20261028_ASTRA_ULTRA_CANDIDATE_01`  
**Updated:** `2026-10-28T22:15:00+05:30`  

---

## 1. Measured System & Latency Metrics

| Metric Dimension | Measured Value | Unit / Sample Size | Verification Source / Receipt |
| :--- | :---: | :---: | :--- |
| **Canonical Test Execution Time** | `364.18` | seconds (1,192 tests) | `test_bot.py` exit 0 |
| **Offline Verification Suite Time** | `262.40` | seconds (1,192 tests) | `docs/evidence/master_astra_full_20261028_02_python.txt` |
| **Candidate Decision Latency (p50)** | `4.20` | milliseconds | Phase 5C Benchmark (1,000 events) |
| **Candidate Decision Latency (p99)** | `4.51` | milliseconds | Phase 5C Benchmark (10,000 events) |
| **Paper Ledger Reconciliation (100 pos)** | `9.47` | milliseconds | Phase 5C Benchmark |
| **Paper Ledger Reconciliation (10k pos)** | `766.10` | milliseconds | Phase 5C Benchmark |
| **Scanner Cycle Latency (16 cash stocks)** | `838.60` | milliseconds | In-memory simulated adapter |
| **Browser CDP Verification Duration** | `22.50` | seconds (138 checks) | `docs/evidence/astra_browser_assets_20261028_01.json` |

---

## 2. Test Execution & Coverage Counters

| Suite / Test Group | Tests Run | Tests Passed | Failures | Errors | Skipped | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Canonical Python Offline Suite** | `1,192` | `1,192` | `0` | `0` | `0` | `PASS` |
| **Node.js Dashboard Contract Suite** | `38` | `38` | `0` | `0` | `0` | `PASS` |
| **Python Syntax & Bytecode Compilation** | `101` files | `101` files | `0` | `0` | `0` | `PASS` |
| **Multi-Strategy Prospective Triggers** | `14` | `14` | `0` | `0` | `0` | `PASS` |
| **Confluence & Dynamic Ranking** | `27` | `27` | `0` | `0` | `0` | `PASS` |
| **Headless Chrome Responsive Viewports** | `138` checks | `138` checks | `0` | `0` | `0` | `PASS` |
| **Release Management & Recovery Drills** | `5` | `5` | `0` | `0` | `0` | `PASS` |

---

## 3. Paper Trading Safety & Accounting

| Safety Metric | Value | Constraint / Enforcement |
| :--- | :---: | :--- |
| **Live Broker Orders Attempted** | `0` | Strictly blocked; no order endpoints invoked |
| **Premature Paper Entries** | `0` | Strictly blocked; requires limit-touch post-detection |
| **HTTP GET/HEAD Triggered Scans** | `0` | HTTP 405 Method Not Allowed enforced |
| **Account Daily Loss Breaches** | `0` | Checked before entry; rejects when threshold reached |
| **Max Concurrent Open Positions** | `3` | Account-level exposure cap enforced |
| **Transaction Rollback Integrity** | `100%` | Verified via SQLite WAL point-in-time recovery |

---

## 4. Empirical Trading Performance

| Indicator | Value | Disclosure & Rationale |
| :--- | :---: | :--- |
| **Strategy 1 (Order Block / FVG) Net Return** | `N/A` | `EMPIRICAL_COMPARISON_NOT_ESTABLISHED` (Authorized historical tick data pending) |
| **Strategy 2 (VWAP Pullback) Net Return** | `N/A` | `EMPIRICAL_COMPARISON_NOT_ESTABLISHED` (Authorized historical tick data pending) |
| **Strategy 3 (Option Apex) Net Return** | `N/A` | `EMPIRICAL_COMPARISON_NOT_ESTABLISHED` (Authorized historical tick data pending) |
| **Strategy 4 (ORB Filtered) Net Return** | `N/A` | `EMPIRICAL_COMPARISON_NOT_ESTABLISHED` (Authorized historical tick data pending) |
| **Strategy 5 (Supertrend) Net Return** | `N/A` | `EMPIRICAL_COMPARISON_NOT_ESTABLISHED` (Authorized historical tick data pending) |
| **Overall Win Rate** | `N/A` | Under SEBI & quantitative guidelines, synthetic data cannot be used to manufacture win rates. |
