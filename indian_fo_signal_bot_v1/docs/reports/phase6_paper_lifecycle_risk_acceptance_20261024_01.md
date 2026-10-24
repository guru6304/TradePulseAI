# TRADEPULSE AI — PHASE 6 PAPER LIFECYCLE & RISK ACCEPTANCE REPORT

**Document ID:** `docs/reports/phase6_paper_lifecycle_risk_acceptance_20261024_01.md`  
**Stage:** `phase6_20261024_01`  
**Date:** 2026-10-24  
**Author:** TradePulse AI Core Execution & Risk Engineering  
**Scope:** Workstream A (Paper Trading Lifecycle & Accounting) and Workstream B (Risk, Reliability & Operational Recovery)  
**Status:** `GATE_A_ACCEPTED` & `GATE_B_ACCEPTED` (Offline Verification Passed)

---

## 1. Executive Summary

Workstreams A and B of Phase 6 evaluated, challenged, and verified the complete paper-trading execution pipeline, double-entry financial ledger, risk limit enforcement, process crash recovery, and EOD settlement engine.

All 16 dedicated lifecycle and risk recovery regressions in `test_phase6_paper_lifecycle.py` (7 tests) and `test_phase6_risk_recovery.py` (9 tests) execute cleanly with zero failures, zero errors, and zero ResourceWarnings under `-W error::ResourceWarning`.

---

## 2. Workstream A: Paper-Trading Lifecycle & Accounting Verification

### 2.1 State Machine & Candidate Handoff
The forward lifecycle transition model was verified end-to-end:
$$\text{Scanner Candidate} \xrightarrow{\text{ForwardPaperCoordinator}} \text{QUEUED} \xrightarrow[\text{PaperPortfolio.enter}]{\text{Next Completed Bar}} \text{OPEN} \xrightarrow{\text{Bar Closes}} \text{MARK} \xrightarrow[\text{Stop/Target/EOD}]{\text{Exit Trigger}} \text{CLOSED}$$

1. **LONG Position Lifecycle:**
   - Candidate generated at bar close 10:00 IST (entry 100.0, stop 95.0, target 110.0).
   - Enters on completed next bar (10:05 bar, closing at 10:10:00 IST) at open price 100.0.
   - Sizing algorithm sizes position strictly according to risk capital (1% of starting capital) and adverse slippage.
   - Bar 10:10 marks position at close 107.0 -> records positive unrealized P&L without premature capital release.
   - Bar 10:15 touches target 110.0 -> triggers `TARGET` exit, calculating realized gross P&L, itemized charges, and net P&L.
   - Verified by `test_complete_long_position_lifecycle_to_target_exit`.

2. **SHORT Position Lifecycle:**
   - Short entry at 100.0, stop 105.0, target 90.0.
   - Price rallies against short on next bar -> triggers `STOP` exit at 105.0.
   - Full capital reserved is released, realized net loss is deducted from portfolio equity.
   - Verified by `test_complete_short_position_lifecycle_to_stop_loss_exit`.

3. **Conservative Collision Resolution:**
   - Single bar exhibits extreme volatility breaching both stop loss (95.0) and target (110.0).
   - Engine enforces conservative stop-first policy (`STOP_FIRST_COLLISION`), exiting at stop price (95.0) with realized loss. Target credit is strictly denied.
   - Verified by `test_conservative_same_candle_collision_stop_first`.

### 2.2 Double-Entry Accounting Invariants
Throughout all lifecycle stages (OPEN, MARK, CLOSED), the accounting ledger preserves exact mathematical equality without floating-point drift:
$$\text{Equity} = \text{Starting Capital} + \text{Realized Net P&L} + \text{Unrealized Net P&L}$$
$$\text{Available Capital} = \max(0, \text{Starting Capital} + \text{Realized Net P&L} + \text{Unrealized Gross Losses} - \text{Reserved Capital})$$
$$\text{Net P&L} = \text{Gross P&L} - (\text{Brokerage} + \text{STT} + \text{Exchange Charges} + \text{SEBI Turnover} + \text{Stamp Duty} + \text{GST} + \text{Slippage})$$

Full reconciliation is verified by `PaperPortfolio.reconcile()`, returning `{"status": "OK", "errors": []}`.

### 2.3 Intraday EOD Settlement & Tamper-Evident Statement
- Mandatory square-off at 15:20 IST (`square_off_ist`): Open positions reaching 15:20 IST are squared off automatically at bar close with reason `EOD` (`test_mandatory_intraday_eod_square_off_at_1520`).
- Session statement generation (`session_statement`): Produces cryptographic SHA-256 event digest and tamper-evident `statement_sha256`. Mutating any field in the statement invalidates the checksum (`test_multi_trade_eod_statement_and_tamper_detection`).

---

## 3. Workstream B: Risk Enforcement, Fault Injection & Operational Recovery

### 3.1 Risk Boundary Enforcement
| Control | Invariant / Boundary | Test Result |
| :--- | :--- | :--- |
| **Max Open Positions** | Rejects 3rd position when limit is 2 (`OPEN_POSITION_LIMIT`) | `PASS` (`test_open_position_limit_enforcement`) |
| **Daily Loss Limit** | Cumulative daily net loss exceeding limit blocks entries (`DAILY_LOSS_LIMIT`) | `PASS` (`test_daily_loss_limit_blocks_new_entries`) |
| **Daily Entry Limit** | Rejects 3rd entry when limit is 2 (`DAILY_ENTRY_LIMIT`) | `PASS` (`test_daily_entry_limit_enforcement`) |
| **Invalid Bracket** | Stop >= Entry or Target <= Entry rejected (`INVALID_ENTRY_STOP_TARGET_BRACKET`) | `PASS` (`test_invalid_bracket_geometry_rejection`) |
| **Stale Candle Rejection**| Candle older than `max_mark_age_seconds` (60s) rejected (`INVALID_STALE_OR_UNFINISHED_BAR`) | `PASS` (`test_stale_mark_and_candle_age_rejection`) |
| **Contiguous Sequence** | Out-of-order or skipped 5m bar rejected (`MISSING_OR_OUT_OF_ORDER_POSITION_BAR`) | `PASS` (`test_non_contiguous_bar_rejection`) |

### 3.2 Fault Injection & Process Crash Recovery
1. **Crash During Pending Order:**
   - Simulated scenario: `PaperPortfolio.enter` inserts an `ENTRY` event into `paper_events`, but the process crashes before `paper_candidate_decisions` is updated.
   - On restart, `ForwardPaperCoordinator` inspects `paper_events`, detects the existing entry, and transitions the decision to `FILLED` (`reason_code="RECOVERED_IDEMPOTENT_ENTRY"`).
   - No duplicate order is submitted, and no duplicate capital is reserved (`test_crash_recovery_during_pending_order`).
2. **Account Config Tamper Detection:**
   - Mutating `config_json` or `config_hash` directly in SQLite triggers `IMMUTABLE_ACCOUNT_CONFIG_CONFLICT` or `ACCOUNT_CONFIG_CORRUPT`, preventing unauthorized alterations (`test_account_config_tamper_detection`).
3. **Unapproved Financial Recovery Rejection:**
   - `review_unresolved_eod` rejects unauthorized ledger mutation requests with `UNAPPROVED_FINANCIAL_RECOVERY_ACTION` (`test_unapproved_financial_recovery_action_rejection`).

---

## 4. Acceptance Gate Verdicts

- **Gate A — Paper Lifecycle Integrity:** **ACCEPTED**  
  Real production paths exercise candidate-to-settlement lifecycle; idempotency, accounting, and EOD settlement reconcile.
- **Gate B — Risk Enforcement:** **ACCEPTED**  
  All approved risk controls are traced, tested at boundaries, and demonstrated to fail closed under fault injection.
