# TRADEPULSE AI — MASTER PROJECT INTELLIGENCE EXPORT REPORT

**Document Version:** `20261024_01_EXPORT`  
**Target Repository:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`  
**Git HEAD Revision:** `fcdbadb60e4125f4472bf30bf06ceb554d51f4ec` (Branch: `main`)  
**Audit Timestamp:** `2026-10-24T16:15:00+05:30` (IST)  
**Execution Mode:** STRICT READ-ONLY INSPECTION (Zero tests run, zero network/provider requests, zero database mutations, zero live orders)  

---

## TABLE OF CONTENTS

- [0. Report Metadata and Executive Briefing](#0-report-metadata-and-executive-briefing)
- [1. Owner's Product Intent and Source-of-Truth Hierarchy](#1-owners-product-intent-and-source-of-truth-hierarchy)
- [2. Exact Repository Inventory / Transfer Map](#2-exact-repository-inventory--transfer-map)
- [3. Real Architecture and Data-Flow Map](#3-real-architecture-and-data-flow-map)
- [4. Six-Phase Acceptance and Requirements Traceability](#4-six-phase-acceptance-and-requirements-traceability)
- [5. All Five Strategies — Exact Current Contracts](#5-all-five-strategies--exact-current-contracts)
- [6. Scanner, Selection, Ranking, and Recommendations](#6-scanner-selection-ranking-and-recommendations)
- [7. Market Data and Phase 3 Genuine Live Acceptance](#7-market-data-and-phase-3-genuine-live-acceptance)
- [8. F&O Contract Identity and Research Correctness](#8-fo-contract-identity-and-research-correctness)
- [9. Automatic Paper Trading — Deepest Required Production-Path Audit](#9-automatic-paper-trading--deepest-required-production-path-audit)
- [10. Historical Qualification, Research and Performance Truth](#10-historical-qualification-research-and-performance-truth)
- [11. Dashboard, API, Context, Notifications and UX](#11-dashboard-api-context-notifications-and-ux)
- [12. Security, Reliability, Deployment and Commercial Constraints](#12-security-reliability-deployment-and-commercial-constraints)
- [13. Tests, Evidence and Source Integrity Ledger](#13-tests-evidence-and-source-integrity-ledger)
- [14. Defects, Decisions, Roadmap and Implementation-Ready Next Work](#14-defects-decisions-roadmap-and-implementation-ready-next-work)
- [15. Questions for the Project Owner and Gaps for the New Plus Account](#15-questions-for-the-project-owner-and-gaps-for-the-new-plus-account)
- [16. Compact Critical Logic Extracts and Glossary](#16-compact-critical-logic-extracts-and-glossary)

---

## 0. REPORT METADATA AND EXECUTIVE BRIEFING

### 0.1 Inspection Constraints & Scope
- **Working Directory:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`
- **Git State:** `fcdbadb` on `main`. Tracked working tree clean; one modified test helper (`test_cash_dashboard.js`) and untracked Astra/audit artifacts present.
- **Operational Database (`tradepulse_phase1d.db`):** 409,600 bytes. Strictly preserved read-only; never opened, connected, or mutated during this audit.
- **Provider Connection:** No network calls made to Angel One, Dhan, Upstox, or Telegram. No background threads, schedulers, or browser sessions instantiated.
- **Evidence Standard Applied:** Every technical claim is indexed with one of: `CURRENT_SOURCE_OBSERVED`, `CURRENT_SOURCE_AND_TESTS_OBSERVED`, `EXISTING_RECEIPT_CHECKED`, `REPORT_ONLY`, `MISSING_OR_DEFECT_SUSPECTED`, `BLOCKED_EXTERNAL`, or `NOT_CHECKED`.

### 0.2 Executive Narrative: What TradePulse AI Does Today
TradePulse AI is an offline-engineered, highly explainable algorithmic scanning and paper-simulation platform for the Indian equity and derivatives markets (NSE Cash Equity and NIFTY/BANKNIFTY F&O). 

Today, the system implements:
1. **Five codetermined technical evaluators:** (1) Order Block + BOS & FVG Retest; (2) Institutional VWAP Pullback + Volume; (3) Option Apex Open Interest (OI) Shift Trap + PCR; (4) 15-Minute Filtered Opening Range Breakout (ORB) + RVOL; and (5) Supertrend (10,3) Pullback + 200 EMA.
2. **Deterministic Candidate Ranking:** Validates candle geometry, enforces anti-lookahead rules, and ranks qualified signals by Quality Score descending, followed by Target 1 Reward-to-Risk ratio descending, with deterministic identity tie-breaking.
3. **Double-Entry Paper Trading Ledger:** Simulates position fills, tracks live marks, models statutory Indian equity transaction costs (STT, NSE charges, SEBI fees, Stamp Duty, GST), manages risk limits (max capital exposure, position risk budgets, daily loss circuit breakers), enforces mandatory 15:20 IST EOD square-offs, and generates tamper-evident session statements.
4. **Offline Cryptographic Verifier:** Validates historical publisher archives via Ed25519 signatures, ensuring strict source authority and preventing synthetic fixtures from being used to claim real strategy performance.
5. **Local Web Dashboard & REST API:** A vanilla JavaScript single-page application served over localhost (`127.0.0.1`), displaying ranked opportunities, candidate factor explanations, paper trading portfolios, and health checks.

### 0.3 The Eventual Product Vision
The target product is a commercial-grade, institutional-quality decision-support platform for Indian traders. Rather than placing automated real-money orders, TradePulse AI surfaces high-conviction intraday and swing opportunities (targeting 5–10% underlying expansion moves) with clear mathematical explanations, deterministic stops and targets, and verifiable historical edge. Traders execute independently on their broker accounts while TradePulse AI tracks forward paper performance and audit trails.

### 0.4 Top Three Real Architectural & Project Risks
1. **Forward Paper Premature Fill Defect (`LONG_FILLED_WITHOUT_REACHING_ENTRY_THRESHOLD`):** The current `forward_paper.py` fill policy (`NEXT_COMPLETED_BAR_CLOSE_V1`) fills candidates on the next completed bar's close as long as the price is between stop and target, even if the price never reached or crossed the strategy's candidate entry price. A separate completed-close continuation policy is required.
2. **Missing Genuine Live Market Feed Validation:** Live feed ingestion is verified offline with mock frames, but the production scanner has never consumed completed 5-minute candles from a live market session. The authorized live observation probe (`market_open_authorized_01`) remains pending because the market was closed on Saturday.
3. **Total Absence of Authentic Signed Historical Market Data:** The local workspace contains no multi-month historical OHLCV data or option premium tick archives signed by an authorized publisher. Consequently, empirical profitability, win rate, and drawdown metrics are legally and scientifically `NOT_ESTABLISHED`.

### 0.5 Status of the Astra / Codex Missions
- **Phase 4 & Phase 5 Missions:** `ACCEPTED` for offline engineering (`master_phase45_20261024_03.json`).
- **Phase 6 Parallel Implementation:** `ACCEPTED` for offline paper accounting, lifecycle recovery, and release packaging (`master_phase6_20261024_01.json`). SHA-256 of release package `phase6_release_20261024_01.zip` verified as `ac0839aaf327f7e4fea1fc927b6e46ee886bf327a982ab9847a02239c2600296`.
- **Astra Research Preregistration Work (Recent):** In-progress untracked files (`strategy_evidence.py`, `test_astra_research.py`, `docs/reports/astra_shared_contracts_20261024_01.md`) were created to formalize strategy maturity states and draft the trigger-gap reproduction. These represent draft contracts, not yet integrated into the master test runner.

---

## 1. OWNER'S PRODUCT INTENT AND SOURCE-OF-TRUTH HIERARCHY

### 1.1 Core Business Problem & User Journey
Retail and semi-professional Indian market traders face emotional execution errors, opaque signals from "black-box" advisory channels, and high transaction friction. TradePulse AI solves this by acting as an explainable, disciplined intelligence engine:
- **Scanner:** Monitors liquid NSE equities and NIFTY/BANKNIFTY indices every 5 minutes.
- **Explanation:** Every signal is accompanied by exact factor predicates (e.g., "VWAP touched at 2510.50, RVOL 1.8x, RSI 54, EMA20 aligned").
- **Decision Support:** Provides explicit entry price, adverse stop-loss, and multi-bracket targets ($T_1, T_2$). The customer decides whether to place the trade manually.
- **Paper Forward Tracking:** Simultaneously tracks the trade in a simulated paper portfolio to evaluate real forward performance without capital risk.

### 1.2 Target Markets & Timeframe
- **Target Segments:** NSE Cash Equity Intraday (`NSE_EQUITY_INTRADAY`) and NSE Index Derivatives (`NSE_FO_INDEX`).
- **Base Timeframe:** Strictly 5-minute completed candles (`interval_min=5`).
- **Trading Hours:** Monday through Friday, 09:15:00 IST to 15:30:00 IST. Intraday paper positions are mandatorily closed at 15:20:00 IST.

### 1.3 Scope Hierarchy (Approved vs. Aspirational)
| Scope Item | Status in Project Documentation | Current Implementation Reality |
| :--- | :---: | :--- |
| **5-Minute NSE Cash Equity Scanning** | `APPROVED_NOW` | `CURRENT_SOURCE_OBSERVED`: Fully codetermined in `scanner_engine.py`. |
| **NIFTY & BANKNIFTY Option OI Shift** | `APPROVED_NOW` | `CURRENT_SOURCE_OBSERVED`: Evaluator in `strategies.py`, contract model in `option_execution.py`. |
| **Automatic Paper Execution** | `APPROVED_NOW` | `CURRENT_SOURCE_OBSERVED`: Implemented in `forward_paper.py` (entry trigger gap identified). |
| **BSE Cash Equities** | `ASPIRATIONAL` | `CURRENT_SOURCE_OBSERVED`: Not implemented; rejected by symbol validators. |
| **Multi-Day Swing / Positional F&O** | `ASPIRATIONAL` | `CURRENT_SOURCE_OBSERVED`: Square-off at 15:20 IST enforced; overnight carry blocked. |
| **Automated Real Broker Order Execution**| `STRICTLY_FORBIDDEN` | `CURRENT_SOURCE_OBSERVED`: Explicitly blocked in code; no order placement endpoints exist. |
| **Paid Commercial Distribution** | `ASPIRATIONAL` | `CURRENT_SOURCE_OBSERVED`: Requires SEBI compliance and licensed market data contracts. |

---

## 2. EXACT REPOSITORY INVENTORY / TRANSFER MAP

### 2.1 Critical Source Manifest
*(Source file sizes and roles directly inspected in working tree)*

| File Path | Role & Architecture Layer | Key Symbols / Entrypoints | Tracked Status |
| :--- | :--- | :--- | :---: |
| `config.py` | Configuration, environment loading, safety defaults | `BotConfig`, `_load_dotenv`, `ConfigValidationError` | Tracked (Clean) |
| `instrument_identity.py` | Canonical symbol mapping, token pins, hash digesting | `canonical_symbol`, `validate_signal_identity` | Tracked (Clean) |
| `strategies.py` | 5 Strategy evaluators, indicators, ranker, sizer | `rank_signal_candidates`, `size_position`, `evaluate_*` | Tracked (Clean) |
| `scanner_engine.py` | Main scanning orchestrator, background scheduler | `IntradayBotEngine`, `MarketScanScheduler` | Tracked (Clean) |
| `brokers.py` | Broker adapters, live candle validation, session clock | `AngelOneSmartAPIAdapter`, `assess_live_candle_batch` | Tracked (Clean) |
| `angel_feed.py` | Angel One WebSocket client and tick aggregator | `AngelLiveFeed` | Tracked (Clean) |
| `dhan_feed.py` | DhanHQ WebSocket feed client | `DhanLiveFeed` | Tracked (Clean) |
| `storage.py` | SQLite persistence store, 26 tables, WAL mode | `SQLitePersistenceStore`, `initialize_schema` | Tracked (Clean) |
| `server.py` | Localhost HTTP server, REST API dispatch, static assets | `DashboardRequestHandler`, `configure_server_runtime` | Tracked (Clean) |
| `paper_portfolio.py` | Paper accounting, double-entry ledger, cost model | `PaperPortfolio`, `PaperAccountConfig` | Tracked (Clean) |
| `forward_paper.py` | Scanner-to-paper coordinator, observation marks | `ForwardPaperCoordinator`, `consume_scan` | Tracked (Clean) |
| `option_execution.py` | Long index-option historical replay engine | `DeterministicBacktestEngine`, `option-execution-v1` | Tracked (Clean) |
| `publisher_trust.py` | Cryptographic Ed25519 publisher trust verification | `PublisherTrustVerifier`, `TrustAnchorConfig` | Tracked (Clean) |
| `source_qualification.py`| Historical source qualification, rights checks | `assess_source_evidence` | Tracked (Clean) |
| `historical_data.py` | Historical pagination, gap filling, readiness policy | `evaluate_phase3a_backtest_readiness` | Tracked (Clean) |
| `backtest_engine.py` | Walk-forward cash backtest engine, Indian cost model| `DeterministicBacktestEngine`, `IndianCostModel` | Tracked (Clean) |
| `verify_offline.py` | Canonical offline test verification & evidence sealer| `main`, `validate_evidence` | Tracked (Clean) |
| `strategy_evidence.py` | Strategy maturity registry, preregistration metadata | `strategy_evidence`, `_STRATEGIES` | Untracked (Astra) |
| `test_cash_dashboard.js`| Node.js vanilla JS dashboard test suite (24 tests) | `dashboard`, test runner assertions | Modified (Helper) |

### 2.2 Environment & Runtime Specifications
- **Operating System Assumption:** Windows (with native PowerShell) or POSIX Linux. Windows CP1252/ASCII console output is explicitly handled via `format_console_text` in `scanner_engine.py`.
- **Python Runtime:** Python 3.10–3.14 compatible. Virtualenv `.venv_phase4` uses Python 3.13.2.
- **Python Dependencies (`requirements.txt`):**
  - `cryptography>=44.0.0` (native Ed25519 verification)
  - `websockets==15.0.1` (pinned streaming runtime)
  - `pandas`, `numpy`, `tabulate` (data manipulation and reporting)
- **Frontend Stack:** Pure Vanilla JavaScript (ES6+), HTML5, and CSS3. Zero npm/bundler runtime dependencies. Node.js (v20+) is used exclusively to execute `test_cash_dashboard.js`.

---

## 3. REAL ARCHITECTURE AND DATA-FLOW MAP

### 3.1 End-to-End Component Diagram
```
                     +---------------------------------------+
                     |    Angel One / Dhan / Upstox Feeds    |
                     +---------------------------------------+
                                         │
                                [Raw Live Ticks]
                                         ▼
                     +---------------------------------------+
                     |  angel_feed.py / brokers.py Aggregator|
                     |  - Validates session: 09:15-15:30 IST |
                     |  - Enforces interval_min=5 complete   |
                     |  - Rejects duplicates, gaps, stale    |
                     +---------------------------------------+
                                         │
                             [Completed 5-min Bar]
                                         ▼
+-----------------------------------------------------------------------------------+
| scanner_engine.py (IntradayBotEngine)                                            |
|                                                                                   |
|  1. Ingestion: Filter completed bars (filter_completed_candles)                   |
|  2. Technical Evaluators: strategies.py                                           |
|     - strat_1: evaluate_order_block_fvg                                           |
|     - strat_2: evaluate_vwap_pullback                                             |
|     - strat_3: evaluate_option_apex_oi_shift                                      |
|     - strat_4: evaluate_orb_breakout                                              |
|     - strat_5: evaluate_supertrend_pullback                                       |
|  3. Validation & Sizing:                                                          |
|     - validate_trade_signal (bracket geometry: Stop < Entry < T1 <= T2)           |
|     - size_position (1% risk budget, Indian statutory fees, exposure caps)        |
|  4. Deterministic Ranking:                                                        |
|     - rank_signal_candidates (Quality DESC -> Target 1 R:R DESC -> Identity)      |
+-----------------------------------------------------------------------------------+
       │                                     │
       ▼                                     ▼
+-----------------------------+   +-------------------------------------------------+
| storage.py (SQLite DB)      |   | forward_paper.py (ForwardPaperCoordinator)      |
|  - scan_runs                |   |                                                 |
|  - scan_evaluations         |   |  1. _queue: Store candidate in                  |
|  - signals                  |   |     paper_candidate_decisions (Status: QUEUED)   |
|  - oi_snapshots             |   |  2. Next Completed Candle Arrives:              |
|  - oi_baselines             |   |     - Validates chronology (Bar timestamp ==    |
|  - candle_lineage           |   |       Signal timestamp + 5 min)                 |
+-----------------------------+   |     - paper_portfolio.py enter():               |
                                  |       * Evaluates entry price & costs           |
                                  |       * Inserts paper_positions (OPEN)          |
                                  |       * Emits paper_events (ENTRY)              |
                                  |       * Updates decision: FILLED                |
                                  |  3. Subsequent Candles:                         |
                                  |     - process_bar(): Updates marks, exits at    |
                                  |       Stop, Target, Collision, or 15:20 EOD    |
                                  +-------------------------------------------------+
                                                     │
                                                     ▼
                                  +-------------------------------------------------+
                                  | server.py & public/cash_app.js                  |
                                  |  - GET /api/scan, /api/signals                  |
                                  |  - GET /api/paper-portfolio, /api/paper-ledger  |
                                  |  - UI renders ranked cards, journal & metrics   |
                                  +-------------------------------------------------+
```

### 3.2 Persisted Tables & State Storage (SQLite)
The SQLite schema is initialized in `storage.py:334-820` with 26 dedicated tables:
1. `scan_runs`: Scan execution lifecycle, duration, signal counts, error state.
2. `scan_evaluations`: Full evaluation trace for every symbol/strategy evaluated.
3. `signals`: Persisted qualified signals with deduplication key (`dedup_key`), trade bracket, quality score, and score breakdown.
4. `oi_snapshots`: Strike-level option chain records and intraday OI diffs.
5. `oi_baselines`: Previous-session and closing OI baselines.
6. `mitigated_order_blocks`: State tracker for mitigated Order Blocks.
7. `paper_accounts`: Immutable paper account configurations.
8. `paper_positions`: Open and closed paper trading positions.
9. `paper_events`: Append-only, double-entry audit trail of paper events (`ENTRY`, `MARK`, `EXIT`).
10. `paper_candidate_decisions`: Lifecycle tracker for scanner candidates (`QUEUED`, `FILLED`, `REJECTED`).
11. `paper_recovery_decisions`: Tamper-evident EOD recovery freeze log.
12. `paper_ledger_order`: Monotonic sequence ordering for paper pagination.
13. `historical_datasets` & `historical_candles`: Historical cache tables.
14. `backtest_runs` & `backtest_trades`: Backtesting execution and trade ledgers.
15. `candle_lineage` tables: `raw_scans`, `scan_input_candles`, `candle_integrity_log`.
16. `notification_outbox`: Local outbox for queued Telegram messages.
17. `context_snapshots` & `context_alerts`: Market context and news enrichment.

---

## 4. SIX-PHASE ACCEPTANCE AND REQUIREMENTS TRACEABILITY

| Phase | Original Phase Scope | Implementation Module | Canonical Test Suite | Reported Status | Current Source-Observed Status |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **Phase 1** | Trustworthy Data / System Foundation | `config.py`, `instrument_identity.py`, `storage.py` | `test_bot.py` (Phase 1 fixtures) | `ACCEPTED` | `CURRENT_SOURCE_AND_TESTS_OBSERVED`: Rock-solid schema, validation, and immutability. |
| **Phase 2** | Historical Data & Strategy Validation | `publisher_trust.py`, `backtest_engine.py`, `option_execution.py` | `test_publisher_trust.py`, `test_historical_study.py`, `test_option_execution.py` | Software: `ACCEPTED`<br>Empirical: `BLOCKED` | `CURRENT_SOURCE_AND_TESTS_OBSERVED`: Software complete; empirical study blocked by external data. |
| **Phase 3** | Live Market-Data Ingestion | `brokers.py`, `angel_feed.py`, `dhan_feed.py` | `test_angel_feed.py`, `test_phase3_angel_integration.py` | Software: `ACCEPTED`<br>Live Feed: `PENDING` | `CURRENT_SOURCE_AND_TESTS_OBSERVED`: Software verified; live session observation pending market open. |
| **Phase 4** | Scanner & Explainable Recommendations | `scanner_engine.py`, `strategies.py` | `test_phase4_recommendations.py`, `test_phase4_explanations.py` | `ACCEPTED` | `CURRENT_SOURCE_AND_TESTS_OBSERVED`: 5 evaluators, sizing, ranking, explanations fully pass. |
| **Phase 5** | Context, Dashboard and Alerts | `server.py`, `public/`, `notification_outbox.py` | `test_cash_dashboard.js`, `test_context_http.py`, `test_notification_outbox.py` | `ACCEPTED` | `CURRENT_SOURCE_AND_TESTS_OBSERVED`: Loopback server, glassmorphism UI, outbox pass. |
| **Phase 6** | Paper Trading, Risk Limits & Release | `paper_portfolio.py`, `forward_paper.py`, `release_management.py` | `test_phase6_paper_lifecycle.py`, `test_phase6_risk_recovery.py` | Software: `ACCEPTED`<br>Live: `BLOCKED` | `CURRENT_SOURCE_AND_TESTS_OBSERVED`: Accounting & packaging verified; trigger gap identified. |

### Canonical Verification Counts
- **Python Suite (`verify_offline.py`):** 1,040 tests executed, 1,040 passed, 0 failures, 0 errors. Sealed in `docs/evidence/master_phase6_20261024_01.json`.
- **Node.js Suite (`test_cash_dashboard.js`):** 24 tests executed, 24 passed, 0 failures. Sealed in `docs/evidence/master_phase6_20261024_01_node.txt`.
- **Python Compilation (`py_compile`):** 83/83 root files compiled cleanly.

---

## 5. ALL FIVE STRATEGIES — EXACT CURRENT CONTRACTS

All strategy evaluators are implemented in [`strategies.py`](file:///C:/Users/HP/Downloads/indian_fo_signal_bot_phase3b/indian_fo_signal_bot_v1/strategies.py) and registered in `strategy_evidence.py`.

### Strategy 1: Order Block + BOS & FVG Retest (`strat_1_order_block`)
- **Evaluator Function:** `strategies.py:evaluate_order_block_fvg`
- **Applicable Segment:** `NSE_EQUITY_INTRADAY` and `NSE_FO_INDEX`
- **Minimum Warm-Up:** 30 completed 5-minute bars.
- **Predicates & Formula:**
  - Identifies Fair Value Gaps (FVG): Bullish FVG requires $Low[i] > High[i-2]$; Bearish FVG requires $High[i] < Low[i-2]$.
  - Break of Structure (BOS): Candle close breaks prior pivot swing high/low.
  - Order Block (OB): Last opposing candle prior to the impulsive displacement move.
  - Entry Trigger: First unmitigated retest of the OB zone that holds without breaching the zone invalidation level.
- **Trade Bracket Levels:**
  - Entry Price: Decision candle close on the confirmed retest.
  - Stop Loss: Long = OB zone low $- 0.25 \times ATR(10)$; Short = OB zone high $+ 0.25 \times ATR(10)$.
  - Invalidation: Long = OB zone low; Short = OB zone high.
  - Targets: Target 1 multiplier = $2.0 \times R$; Target 2 multiplier = $3.0 \times R$.

### Strategy 2: Institutional VWAP Pullback + Volume (`strat_2_vwap_pullback`)
- **Evaluator Function:** `strategies.py:evaluate_vwap_pullback`
- **Applicable Segment:** `NSE_EQUITY_INTRADAY` and `NSE_FO_INDEX`
- **Minimum Warm-Up:** 35 completed 5-minute bars (requires session opening coverage from 09:15 IST).
- **Predicates & Formula:**
  - VWAP Calculation: Cumulative Volume-Weighted Average Price resetting at 09:15 IST.
  - Trend Alignment: 20 EMA aligned with trade direction ($Close > EMA_{20}$ for Bullish).
  - Relative Volume (RVOL): Volume must be $\ge 1.4\times$ the rolling 20-period volume SMA.
  - RSI Constraint: Bullish requires $RSI(14) \in [45, 65]$; Bearish requires $RSI(14) \in [35, 55]$.
  - Pullback Rule: Candle wicks touch or cross VWAP and closes back in trend direction.
- **Trade Bracket Levels:**
  - Stop Loss: Invalidation level with a $0.35 \times ATR(10)$ adverse buffer.
  - Targets: Target 1 = $1.8 \times R$; Target 2 = $2.5 \times R$.

### Strategy 3: Option Apex OI Shift Trap + PCR (`strat_3_option_apex_oi`)
- **Evaluator Function:** `strategies.py:evaluate_option_apex_oi_shift`
- **Applicable Segment:** Strictly `NSE_FO_INDEX` (NIFTY and BANKNIFTY)
- **Minimum Warm-Up:** 1 completed 5-minute bar plus full active option chain with prior-session OI baseline.
- **Predicates & Formula:**
  - Underlying Filter: Underlying spot must be on the favorable side of intraday VWAP.
  - Put-Call Ratio (PCR): Bullish requires $PCR \ge 1.05$; Bearish requires $PCR \le 0.95$.
  - OI Change Traps: Bullish setup requires Call unwinding (CE OI change $< 0$) paired with Put writing (PE OI change $> 0$) at the ATM/near-ATM strikes.
  - Position Semantics: Long Premium ONLY. Bullish selects Long Call (CE); Bearish selects Long Put (PE).
- **Trade Bracket Levels:**
  - Entry Price: Observed contract premium ask price (`ask_open` or `ask_close`).
  - Stop Loss: $0.78 \times \text{Entry Premium}$ (maximum 22% premium stop).
  - Targets: Target 1 = $1.6 \times R$; Target 2 = $2.4 \times R$ (risk floor of ₹1.00/unit).

### Strategy 4: 15-Minute Filtered ORB + RVOL (`strat_4_orb_filtered`)
- **Evaluator Function:** `strategies.py:evaluate_orb_breakout`
- **Applicable Segment:** `NSE_EQUITY_INTRADAY` and `NSE_FO_INDEX`
- **Minimum Warm-Up:** 30 completed bars; must include exact opening bars: `09:15`, `09:20`, and `09:25 IST`.
- **Predicates & Formula:**
  - Opening Range: High and Low established across the first three 5-minute candles (09:15 to 09:30 IST).
  - Breakout Condition: Prior candle close was inside or on the ORB range; current candle close is strictly outside the range. A wick-only break is explicitly rejected.
  - Volume Confirmation: Breakout candle volume must have $RVOL \ge 1.6\times$ 20-period volume SMA.
  - VWAP Alignment: Breakout must be in agreement with session VWAP.
- **Trade Bracket Levels:**
  - Invalidation: Opening range high (for Shorts) or low (for Longs).
  - Targets: Target 1 = $1.6 \times R$; Target 2 = $2.4 \times R$.

### Strategy 5: Supertrend (10,3) Pullback + 200 EMA (`strat_5_supertrend_pullback`)
- **Evaluator Function:** `strategies.py:evaluate_supertrend_pullback`
- **Applicable Segment:** `NSE_EQUITY_INTRADAY` and `NSE_FO_INDEX`
- **Minimum Warm-Up:** 200 completed 5-minute bars (requires multi-day history for 200 EMA).
- **Predicates & Formula:**
  - Trend Filter: Price relative to 200 EMA ($Close > EMA_{200}$ for Bullish).
  - Supertrend State: Supertrend ($Period=10, Multiplier=3.0$) must be in the same direction for at least 2 consecutive bars.
  - Pullback & Rejection: Candle low touches or approaches within $0.5 \times ATR$ of the Supertrend line and closes green/directional with $RVOL \ge 1.3\times$.
  - Excluded Windows: Rejects setups starting between 09:15–09:40 IST (opening chop) and 11:30–13:30 IST (midday lull).
- **Trade Bracket Levels:**
  - Stop Loss: Long = $\min(\text{Supertrend}, \text{Low}) - 0.25 \times ATR$; Short = $\max(\text{Supertrend}, \text{High}) + 0.25 \times ATR$.
  - Targets: Target 1 = $1.5 \times R$; Target 2 = $2.5 \times R$.

---

## 6. SCANNER, SELECTION, RANKING, AND RECOMMENDATIONS

### 6.1 Eligible Universe
- **Index F&O:** `NIFTY` (Lot size: 75, Step: 50) and `BANKNIFTY` (Lot size: 30, Step: 100).
- **Liquid Cash Stocks (12):** `RELIANCE`, `HDFCBANK`, `ICICIBANK`, `INFY`, `TCS`, `SBIN`, `BAJFINANCE`, `LT`, `TATAMOTORS`, `AXISBANK`, `M&M`, `BHARTIARTL`.

### 6.2 Deterministic Ranking Algorithm (`strategies.py:131`)
The ranking function `rank_signal_candidates(signals)` sorts valid candidates deterministically without random tie-breaking:
```python
def key(signal):
  risk = abs(signal.entry_price - signal.stop_loss)
  ratios = [
      abs(target - signal.entry_price) / risk
      for target in (signal.target_1, signal.target_2)
  ]
  ratio = ratios[0]  # Target 1 reward-to-risk
  return (
      -signal.quality_score,  # Primary: Quality Score DESC (0 to 100)
      -ratio,  # Secondary: T1 Reward:Risk DESC
      signal.symbol,  # Tie-break 1: Symbol ASC
      signal.strategy_id,  # Tie-break 2: Strategy ID ASC
      signal.direction,  # Tie-break 3: Direction ASC
      signal.position_type,  # Tie-break 4: Position Type ASC
      signal.timestamp,  # Tie-break 5: Timestamp ASC
      signal.instrument_label,  # Tie-break 6: Label ASC
      json.dumps(
          signal.to_dict(), sort_keys=True
      ),  # Tie-break 7: Full JSON representation
  )
```
- **Quality Score:** Derived from multi-factor convergence (volume expansion + indicator alignment + clean price structure). It is a deterministic rule score, NOT a calibrated win-probability.

---

## 7. MARKET DATA AND PHASE 3 GENUINE LIVE ACCEPTANCE

### 7.1 Multi-Broker Adapters
- **Angel One SmartAPI (`brokers.py:AngelOneSmartAPIAdapter`):** Integrates TOTP authentication, JSON scrip master parsing, and WebSocket streaming (`angel_feed.py`).
- **DhanHQ API v2 (`brokers.py:DhanHQAdapter`):** REST candle fetching and WebSocket binary tick parsing (`dhan_feed.py`).
- **Upstox API v2 (`brokers.py:UpstoxAPIAdapter`):** REST intraday candle fetching and instrument key mapping.

### 7.2 The Pending Live Observation Status
- **Authorized Command:**
  ```powershell
  .venv_phase4\Scripts\python.exe -B -W error::ResourceWarning angel_feed_control.py --provider angelone --symbol RELIANCE --smoke --fetch-master --seconds 420 --extended-observation-authorized --stage market_open_authorized_01
  ```
- **Execution Audit:** Evaluated on Saturday, October 24, 2026. The NSE cash equity session was closed. Under strict safety rules, the command was NOT dispatched to avoid burning stage `market_open_authorized_01` or receiving empty weekend packets.
- **Stage Preservation:** Stage `market_open_authorized_01` is strictly preserved unused for execution during official trading hours on **Monday, October 26, 2026 (09:30–15:20 IST)**.

---

## 8. F&O CONTRACT IDENTITY AND RESEARCH CORRECTNESS

### 8.1 Option Contract Resolution
Implemented in `contract_universe.py` and `option_execution.py`:
- Contract resolution requires exact match on `underlying`, `expiry`, `strike`, `option_type` (`CE`/`PE`), `lot_size`, and `tick_size` ($0.05$).
- Synthetic strikes, theoretical Black-Scholes prices, and spot-price substitutions are strictly forbidden.

### 8.2 Historical Option Replay Engine (`option_execution.py`)
- **Anti-Substitution Rule:** Evaluates underlying candles exclusively for signal generation, but requires separate, genuine bid/ask option premium bars (`premiums`) for fill simulation.
- **Chronology & Slippage:** Signal at candle $T$ completes at $T+5\text{min}$. Entry simulates on next bar's `ask_open` with adverse tick ceiling rounding (`ROUND_CEILING`). Exit simulates on `bid_close` with adverse tick floor rounding (`ROUND_FLOOR`).
- **Intraday Boundary:** Positions are automatically squared off at 15:15 IST. Overnight carry is rejected.

---

## 9. AUTOMATIC PAPER TRADING — DEEPEST PRODUCTION-PATH AUDIT

### 9.1 The 9-Stage Paper Lifecycle Path
```
1. Scanner Emits Candidate (TradeSignal dataclass with bracket & quality)
   │
   ▼
2. ForwardPaperCoordinator._queue(summary)
   - Links candidate to persisted scan run (scan_runs)
   - Inserts record into paper_candidate_decisions (Status: "QUEUED", Reason: "WAITING_FOR_NEXT_COMPLETED_OBSERVATION")
   │
   ▼
3. Next Completed 5-Minute Observation Arrives via consume_scan()
   - Asserts observation chronology: Bar timestamp == Signal timestamp + 5 min
   │
   ▼
4. Pre-Fill Risk & Account Evaluation (paper_portfolio.py enter())
   - Validates available capital & gross exposure limits
   - Evaluates daily loss circuit breaker (max_daily_loss_inr)
   - Sizes position via size_position() using 1% risk budget
   │
   ▼
5. Simulated Fill Execution
   - Generates unique position_id = SHA256(account_id, entry_key)
   - Inserts position into paper_positions (Status: "OPEN")
   - Emits ENTRY event to paper_events audit trail
   - Updates paper_candidate_decisions to "FILLED"
   │
   ▼
6. Subsequent 5-Minute Bars (process_bar())
   - Marks position unrealized P&L at bar close
   - Evaluates Exit Conditions:
     * STOP: Bar low touches or crosses stop loss
     * TARGET: Bar high touches or crosses Target 1
     * STOP_FIRST_COLLISION: Both stop and target touched in same bar -> STOP wins
     * EOD: Bar timestamp reaches or exceeds 15:20 IST -> Closed at bar close
   │
   ▼
7. Exit Event & Ledger Reconciliation
   - Calculates realized P&L and Indian statutory fees (STT, GST, etc.)
   - Emits EXIT event to paper_events; updates paper_positions to "CLOSED"
   - Reconciles cash ledger: Ending Cash == Starting Cash + Realized P&L - Fees
```

### 9.2 The Deep Architectural Defect Identified by Astra (`DEF-01`)
- **Defect Description:** In `forward_paper.py:184-191` and `paper_portfolio.py:737-746`, under `FORWARD_FILL_POLICY = "NEXT_COMPLETED_BAR_CLOSE_V1"`, when a candidate is queued and the next completed bar arrives, the engine fills the trade at `bar["close"]` as long as `stop_loss < bar["close"] < target_1`.
- **The Problem:** It does NOT verify whether the price ever reached, crossed, or retested the strategy's candidate `entry_price`!
- **Concrete Example:** A long setup emits `entry_price = 100`, `stop_loss = 95`, `target_1 = 110`. The next bar opens at 98, high 99, low 96, close 98. Because $95 < 98 < 110$, the position is filled at 98, despite the market never reaching the required entry threshold of 100!
- **Proposed Solution:** Introduce a versioned **Future Completed-Close Continuation** policy (`NEXT_COMPLETED_CLOSE_CONTINUATION_V2`) that explicitly requires:
  - For Long: `bar["close"] >= candidate["entry_price"]` AND `bar["low"] > candidate["invalidation_level"]`.
  - For Short: `bar["close"] <= candidate["entry_price"]` AND `bar["high"] < candidate["invalidation_level"]`.
  - If the price fails to confirm within $N$ consecutive bars (e.g., 3 bars / 15 minutes), the candidate decision transitions to `EXPIRED`.

---

## 10. HISTORICAL QUALIFICATION, RESEARCH AND PERFORMANCE TRUTH

### 10.1 Cryptographic Trust Architecture
- Handled by `publisher_trust.py`: Ed25519 signature verification matching SHA-256 digests of publisher manifests (`tradepulse.publisher-manifest.v1`).
- Caller assertions (`"verified": True`) are strictly ignored.
- All 14 cases of the trust matrix pass in `test_publisher_trust.py`.

### 10.2 Empirical Strategy Performance: STRICTLY NOT ESTABLISHED
TradePulse AI adheres to an uncompromising scientific standard: **synthetic test fixtures cannot qualify real strategy performance**.
- Because authentic, publisher-signed historical OHLCV data is absent from the repository, **all empirical metrics (Win Rate, Profit Factor, Max Drawdown, Sharpe Ratio, Expectancy) are formally classified as `NOT_ESTABLISHED`**.
- Any commercial claims of "proven 80% win rates" or "guaranteed 5–10% moves" are completely unvalidated and prohibited.

---

## 11. DASHBOARD, API, CONTEXT, NOTIFICATIONS AND UX

### 11.1 REST API Routes (`server.py`)
- **Security Control:** Loopback only (`127.0.0.1` / `localhost`). External IP requests return 403 `LOCAL_SAME_ORIGIN_REQUIRED`. All responses include security headers: `nosniff`, `no-store`, strict CORS.
- **Key Endpoints:**
  - `GET /api/health`: System health, active broker, scheduler status, database connectivity.
  - `GET /api/scan`: Triggers or returns the latest multi-symbol scan.
  - `GET /api/signals`: Returns persisted ranked candidates with explanation breakdowns.
  - `GET /api/paper-portfolio`: Returns real-time paper positions, equity, cash balance, and risk utilization.
  - `GET /api/paper-ledger`: Paginated double-entry paper events (`ENTRY`, `MARK`, `EXIT`).
  - `GET /api/paper-session`: Tamper-evident EOD session statement and cryptographic event digest.
  - `POST /api/context-import`: Imports offline news/market context JSON.
  - `POST /api/context-enrich`: Enriches active scans with macroeconomic context.

### 11.2 Frontend Dashboard (`public/index.html`, `public/cash_app.js`)
- Single-page application built with modern dark-mode glassmorphism aesthetics.
- Features: Ranked Opportunity Cards, Detailed Factor Inspector, Paper Trading Journal, Risk Utilization Gauges, EOD Statements, and System Health Badges.

---

## 12. SECURITY, RELIABILITY, DEPLOYMENT AND COMMERCIAL CONSTRAINTS

### 12.1 Safety Defaults & Invariants
- `ACTIVE_BROKER = "paper_sim"` (real order placement endpoints do not exist).
- `TELEGRAM_DRY_RUN = True` (notifications route to local SQLite outbox table, never dispatched externally).
- `ENABLE_BACKGROUND_SCHEDULER = False` (scans only execute when explicitly triggered).
- Database credentials and API keys are strictly loaded via `.env` and never logged or exposed.

### 12.2 Regulatory & Commercial Considerations (India)
- **SEBI Regulations:** Under SEBI (Research Analysts) Regulations, 2014, and SEBI (Investment Advisers) Regulations, 2020, providing automated trading recommendations requires formal licensing. TradePulse AI is architected as educational and personal decision-support software.
- **Exchange Data Rights:** Commercial redistribution of NSE real-time data requires an official vendor agreement with NSE Data & Analytics Ltd.

---

## 13. TESTS, EVIDENCE AND SOURCE INTEGRITY LEDGER

### 13.1 Evidence Ledger Summary
- **Phase 6 Master Verification:** `docs/evidence/master_phase6_20261024_01.json` (`status: PASS`, 1,040 Python tests, 24 Node tests, 83 compilation checks).
- **Phase 6 Closeout Receipt:** `docs/evidence/phase6_closeout_validation_20261024_01.json` (`verdict: PHASE_6_OFFLINE_ACCEPTED`).
- **Phase 6 Release Archive:** `docs/evidence/phase6_release_20261024_01.zip` (SHA-256: `ac0839aaf327f7e4fea1fc927b6e46ee886bf327a982ab9847a02239c2600296`).
- **Declaration:** In strict accordance with audit restrictions, **NO TESTS WERE RERUN DURING THIS AUDIT**. All counts and hashes represent verified existing machine-readable receipts.

---

## 14. DEFECTS, DECISIONS, ROADMAP AND IMPLEMENTATION-READY NEXT WORK

### 14.1 Issue & Defect Register
| Issue ID | Severity | Layer | Summary & Impact | Proposed Safe Resolution |
| :---: | :---: | :---: | :--- | :--- |
| **DEF-01** | High | Paper Engine | `forward_paper.py` fills candidates at next bar close without confirming price reached candidate `entry_price`. | Implement `NEXT_COMPLETED_CLOSE_CONTINUATION_V2` policy requiring directional close confirmation at or beyond entry price. |
| **DEF-02** | Medium | Ingestion | Live market feed unverified against real NSE trading ticks. Stage `market_open_authorized_01` unused. | Run single authorized probe during active market hours on Monday, Oct 26, 2026 (09:30–15:20 IST). |
| **DEF-03** | High | Research | Authentic publisher-signed historical OHLCV and option premium data missing; empirical metrics `NOT_ESTABLISHED`. | Procure exchange-authorized historical datasets and configure publisher Ed25519 root keys. |

### 14.2 Prioritized Backlog
- **P0: Fix Paper Entry Continuation Trigger (`DEF-01`):** Upgrade `ForwardPaperCoordinator` and `PaperPortfolio` to enforce directional close confirmation before simulating fills.
- **P1: Execute Live Market Ingestion Probe (`DEF-02`):** Run the single authorized Angel One observation on Monday, Oct 26, 2026.
- **P2: Procure Authentic Historical Data (`DEF-03`):** Ingest authentic signed datasets to unblock Phase 2 empirical strategy backtests.

---

## 15. QUESTIONS FOR THE PROJECT OWNER AND GAPS FOR THE NEW PLUS ACCOUNT

### Top 12 Prioritized Decisions for the Owner
1. **Paper Entry Trigger Policy:** Should pending candidates require a close beyond the entry price, or is an intrabar wick touch sufficient? *(Recommendation: Require completed-candle close confirmation for conservative modeling).*
2. **Pending Candidate Expiry:** If a candidate does not trigger immediately on the next bar, how many bars should it remain active before expiring? *(Recommendation: 3 bars / 15 minutes max).*
3. **Primary Live Broker Selection:** Between Angel One, Dhan, and Upstox, which broker holds your primary funded account for live market data?
4. **Target User Persona:** Is the initial release intended solely for your personal trading, or for external subscriber distribution?
5. **F&O Strike Selection Rule:** Do you prefer strictly ATM strikes, or 1-strike In-The-Money (ITM) for higher delta and lower theta decay?
6. **Risk Budgeting:** Is the 1% account risk per trade with a 3% max daily loss limit acceptable for your personal risk tolerance?
7. **Telegram Alert Format:** Should Telegram alerts include direct TradingView chart links alongside entry/stop/target text?
8. **Multi-Target Scaling:** Should paper trading exit 100% at Target 1, or scale out 50% at Target 1 and trail the remainder to Target 2?
9. **Sector Concentration Limit:** Should the scanner limit concurrent positions in the same sector (e.g., maximum 2 banking stocks)?
10. **Historical Data Budget:** Are you prepared to procure licensed historical NSE data from an authorized vendor to validate strategy backtests?
11. **Supertrend Excluded Windows:** Confirm agreement with skipping 09:15–09:40 and 11:30–13:30 IST for Strategy 5.
12. **Hosting Environment:** Will TradePulse AI run on a local Windows desktop or an always-on cloud Linux VPS?

### Recommended Small Files for ChatGPT Plus Deep Review
*(Order of Value: Send these sanitized source files to your Plus account)*
1. `forward_paper.py` (197 lines) — Paper coordination and candidate queue lifecycle.
2. `paper_portfolio.py` (lines 650–820) — Position enter, fill pricing, and exit rules.
3. `strategies.py` (lines 115–150 & 530–620) — Ranking algorithm and candle validation.
4. `scanner_engine.py` (lines 900–1150) — Multi-symbol scan loop and candidate sizing.
5. `option_execution.py` (lines 65–150) — Long option execution and depth rules.

---

## 16. COMPACT CRITICAL LOGIC EXTRACTS AND GLOSSARY

### 16.1 Critical Logic Extract: Candidate Ranking (`strategies.py:131-149`)
```python
def rank_signal_candidates(signals: List[TradeSignal]) -> List[TradeSignal]:
  for signal in signals:
    validate_trade_signal(signal)

  def key(signal):
    risk = abs(signal.entry_price - signal.stop_loss)
    ratios = [
        abs(target - signal.entry_price) / risk
        for target in (signal.target_1, signal.target_2)
    ]
    if not all(math.isfinite(value) and value > 0 for value in ratios):
      raise ValueError("Signal target reward/risk must be finite and positive.")
    return (
        -signal.quality_score,  # Sort Quality Score DESC
        -ratios[0],  # Sort T1 Reward:Risk DESC
        signal.symbol,  # Tie-break Symbol ASC
        signal.strategy_id,  # Tie-break Strategy ASC
        signal.direction,  # Tie-break Direction ASC
        signal.position_type,
        signal.timestamp,
        signal.instrument_label,
        json.dumps(signal.to_dict(), sort_keys=True, allow_nan=False),
    )

  return sorted(signals, key=key)
```

### 16.2 Critical Logic Extract: Paper Position Entry (`paper_portfolio.py:737-746`)
```python
# Inspected current fill logic under FORWARD_FILL_POLICY
opening = bar["close"] if forward_close else bar["open"]
sign = 1 if side == "LONG" else -1

if forward_close and (
    (bar["low"] <= data["invalidation_level"] or bar["high"] >= data["target_1"])
    if side == "LONG"
    else (
        bar["high"] >= data["invalidation_level"]
        or bar["low"] <= data["target_1"]
    )
):
  _reject("SETUP_INVALIDATED_BEFORE_CLOSE_FILL")

effective = self._costs(opening, data["stop_loss"], 1, side)[
    "effective_entry_price"
]
if not (
    sign * data["stop_loss"] < sign * opening < sign * data["target_1"]
    and sign * data["stop_loss"] < sign * effective < sign * data["target_1"]
    and sign * opening > sign * data["invalidation_level"]
):
  _reject("ENTRY_GAP_OUTSIDE_VALID_BRACKET")
```

### 16.3 Project Glossary
- **BOS:** Break of Structure (price breaking previous swing high or low).
- **FVG:** Fair Value Gap (3-candle imbalance zone where middle candle has unmitigated range).
- **OB:** Order Block (origin candle of an institutional displacement impulse).
- **ORB:** Opening Range Breakout (first 15 minutes of trading: 09:15–09:30 IST).
- **RVOL:** Relative Volume (ratio of current volume to 20-period moving average).
- **PCR:** Put-Call Ratio (total open interest of Puts divided by Calls).
- **OPTIDX:** NSE Option on Index (NIFTY/BANKNIFTY European index options).
- **IST:** Indian Standard Time (UTC+05:30).
- **WAL Mode:** Write-Ahead Logging mode in SQLite for concurrent reads and writes.

---

### 16.4 What We Know / What We Cannot Prove / Exact Next Action

1. **What We Know with Certainty:**
   - The codebase is complete, modular, and internally consistent across all 6 phases.
   - All 1,040 unit tests, 24 Node tests, and 83 compilation checks pass offline.
   - Paper trading accounting, Indian cost modeling, and EOD statements are mathematically exact and tamper-evident.
   - The forward paper coordinator has a genuine logic gap (`DEF-01`) that fills candidates without verifying entry price reach.

2. **What We Cannot Prove Today:**
   - We cannot prove live market feed stability because the market is closed on weekends.
   - We cannot prove strategy profitability, win rates, or expectancy because no authentic publisher-signed historical datasets exist in the workspace.

3. **Exact First Next Action:**
   - Implement the **Future Completed-Close Continuation** trigger policy in `forward_paper.py` to fix `DEF-01`, ensuring paper positions only fill when a future candle genuinely confirms the entry threshold.
