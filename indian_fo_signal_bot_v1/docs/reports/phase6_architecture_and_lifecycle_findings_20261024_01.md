# TRADEPULSE AI — PHASE 6 ARCHITECTURE & LIFECYCLE FINDINGS

**Document ID:** `docs/reports/phase6_architecture_and_lifecycle_findings_20261024_01.md`  
**Stage:** `phase6_20261024_01`  
**Date:** 2026-10-24  
**Author:** TradePulse AI Core Engineering  
**Scope:** Phase 6 Architecture, Paper Trading Execution Path, Accounting Model, Risk Controls, Operational Recovery & Release Tooling  
**Prior Milestone Baseline:** `PHASE_4_IMPLEMENTATION_ACCEPTED` and `PHASE_5_IMPLEMENTATION_ACCEPTED` as of 2026-10-24 (`master_phase45_20261024_03.json`)

---

## 1. Executive Summary & Verification Context

Phase 6 ("Paper Trading, Performance Acceptance and Release") represents the final milestone of the TradePulse AI six-phase roadmap. In strict accordance with the mission instructions, an exhaustive architectural and code-level audit was conducted across the live production paths before introducing any modifications or test suites.

Key architectural confirmations:
1. **Source Code Baseline Integrity:** The repository matches the accepted Phase 4/5 baseline with 1,019 Python tests passing, 22 Node tests passing, and 80 Python files compiling cleanly.
2. **Persistence & Accounting Isolation:** Paper trading persistence resides strictly on SQLite within isolated transaction contexts (`paper_transaction`). Operational database `tradepulse_phase1d.db` (409,600 bytes) remains unmutated, empty, and preserved.
3. **Deterministic Order/Fill State Machine:** Paper positions follow an explicit forward state machine: Qualified Scanner Candidate $\to$ Candidate Queue Decision $\to$ Simulated Next-Bar Order/Fill $\to$ Active Position Mark $\to$ Stop/Target/EOD Exit $\to$ Reconciled Realized P&L.
4. **Safety & Zero-External Mutation:** All safety switches (`ACTIVE_BROKER=paper_sim`, `TELEGRAM_DRY_RUN=true`, `ENABLE_BACKGROUND_SCHEDULER=false`) remain active. No external network requests, broker mutation, or background scheduler activations occur.

---

## 2. Production Path Architecture: Qualified Scanner to Paper Settlement

```
+-------------------------------------------------------------------------------------------------+
|                                     INTRADAY BOT ENGINE                                         |
|                                                                                                 |
|   1. 5-Min OHLCV Bar Ingestion (Live/Simulated MultiBrokerScanner)                              |
|   2. Indicator & Rule Pipeline (VWAP, ATR, Supertrend, ORB, Order Block / FVG)                  |
|   3. Candidate Generation & Explainability (Quality Score >= 60, Risk/Reward >= 1.5)            |
+-------------------------------------------------------------------------------------------------+
                                                |
                                                v
+-------------------------------------------------------------------------------------------------+
|                                 FORWARD PAPER COORDINATOR                                       |
|                                                                                                 |
|   Function: ForwardPaperCoordinator.consume_scan(summary, observations)                         |
|   Step A: Persisted Scan Verification (scan_runs table verification)                            |
|   Step B: Candidate Queueing (paper_candidate_decisions: QUEUED or REJECTED)                    |
|   Step C: Mark / Exit Active Positions (OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1)         |
|   Step D: Entry Evaluation against Next Completed Bar (fill_time == signal_time + 5m)           |
+-------------------------------------------------------------------------------------------------+
                                                |
                                                v
+-------------------------------------------------------------------------------------------------+
|                                      PAPER PORTFOLIO CORE                                       |
|                                                                                                 |
|   Function: PaperPortfolio.enter(candidate, completed_next_bar, event_key)                      |
|   1. Idempotency Check: event_key / entry_key collision detection                               |
|   2. Entry Bracket Validation: stop_loss < entry < target_1 (Long) or target < entry < stop     |
|   3. Risk Limit Checks:                                                                         |
|      - max_open_positions (default 3)                                                           |
|      - max_entries_per_day (default 10)                                                         |
|      - max_daily_loss_inr (default 3,000 INR)                                                   |
|      - max_position_exposure_pct (default 50.0%)                                                |
|      - max_total_exposure_pct (default 100.0%)                                                  |
|   4. Sizing: Conservative sizing with adverse slippage and statutory charge anticipation       |
|   5. Atomic Persistence: INSERT INTO paper_positions + paper_events in single transaction        |
+-------------------------------------------------------------------------------------------------+
                                                |
                                                v
+-------------------------------------------------------------------------------------------------+
|                                   POSITION LIFECYCLE & EXIT                                     |
|                                                                                                 |
|   Function: PaperPortfolio.process_bar(position_id, completed_bar, event_key)                   |
|   1. Bar Chronology & Freshness: exactly 5m after last mark; timestamp within session          |
|   2. Exit Trigger Evaluation (Hierarchy):                                                      |
|      a. STOP_GAP: opening gap through stop loss                                                 |
|      b. TARGET_GAP_CAPPED: opening gap through target (fill capped at target)                   |
|      c. STOP_FIRST_COLLISION: simultaneous high/low breach of stop and target                   |
|      d. STOP: low <= stop (Long) or high >= stop (Short)                                        |
|      e. TARGET: high >= target (Long) or low <= target (Short)                                  |
|      f. EOD: bar_time >= square_off_ist (15:20 IST) -> close at bar close                       |
|   3. Mark Update: if no exit triggered, calculate unrealized P&L and estimated exit costs       |
+-------------------------------------------------------------------------------------------------+
                                                |
                                                v
+-------------------------------------------------------------------------------------------------+
|                                    ACCOUNTING & EOD RECONCILIATION                              |
|                                                                                                 |
|   Function: PaperPortfolio.session_statement(session_date)                                      |
|   1. Double-Entry Invariant: starting_capital + realized_net_pnl + unrealized_net_pnl == equity |
|   2. Charge Segregation: brokerage + STT + turnover + sebi + stamp + GST + slippage             |
|   3. Statement Digest: SHA-256 event digest and tamper-evident statement hash                   |
+-------------------------------------------------------------------------------------------------+
```

---

## 3. Risk Controls & Enforcement Points

The audit traced every approved risk control to its exact production enforcement point in `paper_portfolio.py` and `forward_paper.py`:

| Risk Control | Configuration Parameter | Production Enforcement Point | Behavior on Violation |
| :--- | :--- | :--- | :--- |
| **Max Open Positions** | `max_open_positions: int` (3) | `paper_portfolio.py:345-346, 728-729` | Rejects entry with `OPEN_POSITION_LIMIT`. No capital reserved. |
| **Daily Entry Limit** | `max_entries_per_day: int` (10) | `paper_portfolio.py:343-344, 728-729` | Rejects entry with `DAILY_ENTRY_LIMIT`. |
| **Max Daily Loss Limit** | `max_daily_loss_inr: float` (3000.0) | `paper_portfolio.py:340-342, 728-729` | Rejects entry with `DAILY_LOSS_LIMIT`. Triggered when daily realized + unrealized net loss breaches threshold. |
| **Per-Position Exposure** | `max_position_exposure_pct: float` (50.0%) | `paper_portfolio.py:751-754, 764-765` | Rejects entry with `EXPOSURE_LIMIT` or `POSITION_EXPOSURE_LIMIT`. |
| **Aggregate Exposure** | `max_total_exposure_pct: float` (100.0%) | `paper_portfolio.py:751-754, 766-767` | Rejects entry with `AGGREGATE_EXPOSURE_LIMIT`. |
| **Invalid Bracket Geometry** | Mathematical invariant | `paper_portfolio.py:613-617, 742-746` | Rejects with `INVALID_ENTRY_STOP_TARGET_BRACKET` or `ENTRY_GAP_OUTSIDE_VALID_BRACKET`. |
| **Same-Candle Collision** | Conservative Stop-First | `paper_portfolio.py:665-666` | Exits with `STOP_FIRST_COLLISION` at stop price. Never credits target. |
| **Stale Mark Invalidation** | `max_mark_age_seconds: int` (60s) | `paper_portfolio.py:326-329, 568-570` | Rejects entry with `MISSING_OR_STALE_MARKS`. |
| **Mandatory EOD Square-Off** | `square_off_ist: str` ("15:20") | `paper_portfolio.py:669-670, 730-731` | Rejects entries after 15:20 IST (`ENTRY_AFTER_SQUARE_OFF`); exits open positions at bar close. |

---

## 4. Transaction Boundaries & Ledger Integrity

1. **Atomic Multi-Table Writes:**
   All mutations are guarded by `store.paper_transaction(write=True)`. This context manager issues `BEGIN IMMEDIATE` on the SQLite connection. If any step fails (e.g. risk check, malformed payload, JSON serialization error), SQLite issues `ROLLBACK`, guaranteeing that orphaned fills, partial capital reservations, or half-created events cannot persist.
2. **Event Sourcing & Idempotency:**
   - Every state change inserts a row into `paper_events` with unique `(account_id, event_key)`.
   - Replaying the same `event_key` with identical command payload returns the cached result marked `idempotent: True`.
   - Replaying with conflicting parameters triggers `EVENT_IDEMPOTENCY_CONFLICT`.
3. **Double-Entry Reconciliation Invariants:**
   `reconcile_account` validates:
   $$\text{Equity} = \text{Starting Capital} + \sum \text{Realized Net P&L} + \sum \text{Unrealized Net P&L}$$
   $$\text{Available Capital} = \max(0, \text{Starting Capital} + \sum \text{Realized Net P&L} + \sum \text{Unrealized Gross Losses} - \sum \text{Reserved Capital})$$
   $$\text{Net P&L} = \text{Gross P&L} - \text{Total Statutory Costs and Slippage}$$

---

## 5. Operational Recovery & Failure Modes

1. **Process Crash During Pending Decision:**
   `ForwardPaperCoordinator` inspects `paper_events` before evaluating a pending decision. If an `ENTRY` event already exists for `candidate_id`, the coordinator recovers the filled status without duplicate order submission (`RECOVERED_IDEMPOTENT_ENTRY`).
2. **Database Busy / Lock Handling:**
   SQLite connection uses `timeout=30.0` and WAL mode (`journal_mode=WAL`), allowing concurrent readers without blocking serial write transactions.
3. **EOD Unresolved Position Recovery:**
   Positions left open past session cutoff cannot be secretly modified. `PaperPortfolio.review_unresolved_eod` logs an immutable `paper_recovery_decisions` entry and freezes the account (`status="FROZEN"`), refusing financial repair without explicit offline policy authorization.

---

## 6. Conclusion & Handoff to Workstreams

The production-path architecture is sound, mathematically rigorous, and verified in code. The identified requirements and gap closure suites will now proceed across Workstreams A, B, C, and D.
