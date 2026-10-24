# TRADEPULSE AI — PHASE 6 GAP & DEFECT REGISTER

**Document ID:** `docs/reports/phase6_gap_and_defect_register_20261024_01.md`  
**Stage:** `phase6_20261024_01`  
**Date:** 2026-10-24  
**Author:** TradePulse AI Quality & Integration Engineering  
**Baseline Hash:** Verified identical to `master_phase45_20261024_03.json`  
**Scope:** Phase 6 Requirements (REQ-6.1 through REQ-6.12), Defect Identification, Reproduction Strategy, and Resolution Tracking

---

## 1. Summary of Requirements Classification

| Requirement ID | Description | Pre-Fix Status | Gap / Defect Identified | Action Item / Target Suite |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-6.1** | End-to-End Paper Lifecycle | `PARTIALLY_IMPLEMENTED` | Core logic in `paper_portfolio.py` & `forward_paper.py` lacks a dedicated unified Phase 6 test suite verifying candidate-to-settlement state transitions. | Implement `test_phase6_paper_lifecycle.py` (Workstream A). |
| **REQ-6.2** | Deterministic Sizing & Risk | `IMPLEMENTED_AND_VERIFIED` | Production path enforces position, capital, and daily limits; needs formal fault-injection regression tests. | Add boundary & negative tests in `test_phase6_risk_recovery.py` (Workstream B). |
| **REQ-6.3** | Event Idempotency & Concurrency | `IMPLEMENTED_AND_VERIFIED` | Key hashing and event idempotency present; needs explicit test verification of duplicate submissions under concurrent load. | Add concurrency and duplicate replay tests in `test_phase6_paper_lifecycle.py`. |
| **REQ-6.4** | Atomic Persistence & Fail-Closed | `IMPLEMENTED_AND_VERIFIED` | `paper_transaction` handles atomicity; verify rollback behavior under injected store failures. | Add injected failure tests in `test_phase6_risk_recovery.py`. |
| **REQ-6.5** | Restart / Crash Recovery | `PARTIALLY_IMPLEMENTED` | Forward coordinator recovers pending fills from `paper_events`; needs comprehensive test proving no duplicate fills on restart. | Add crash recovery tests in `test_phase6_risk_recovery.py`. |
| **REQ-6.6** | EOD Reconciliation & Statement | `IMPLEMENTED_AND_VERIFIED` | `session_statement` computes hash and event digest; needs end-to-end multi-position settlement verification. | Add multi-trade EOD reconciliation tests in `test_phase6_paper_lifecycle.py`. |
| **REQ-6.7** | Reproducible Performance Harness | `IMPLEMENTED_AND_VERIFIED` | `DeterministicBacktestEngine` and `IndianCostModel` implement deterministic backtests with frozen assumptions. | Create `test_phase6_performance_validity.py` (Workstream C). |
| **REQ-6.8** | Look-Ahead Bias Prevention | `IMPLEMENTED_AND_VERIFIED` | `verify_no_lookahead_leakage` guards candle slices; needs test asserting failure on look-ahead violation. | Add negative look-ahead tests in `test_phase6_performance_validity.py`. |
| **REQ-6.9** | Empirical External-Data Gate | `BLOCKED_BY_EXTERNAL_DEPENDENCY` | Genuine publisher-signed historical datasets with cryptographic trust roots (Ed25519) and legal redistribution rights are absent from the local repository. | Test must confirm gate blocks empirical acceptance without signed data (`test_phase6_performance_validity.py`). |
| **REQ-6.10** | Dashboard Paper & EOD Display | `PARTIALLY_IMPLEMENTED` | `public/index.html` has paper API endpoints (`/api/paper-portfolio`, `/api/paper-session`) but needs dedicated UI layout and renderer regression tests. | Add paper portfolio UI cards to `index.html` and tests to `test_cash_dashboard.js` (Workstream D). |
| **REQ-6.11** | Operational Safety Defaults | `IMPLEMENTED_AND_VERIFIED` | `ACTIVE_BROKER=paper_sim`, `TELEGRAM_DRY_RUN=true`, `ENABLE_BACKGROUND_SCHEDULER=false` strictly enforced. | Verify safety defaults in preflight checks and `test_verify_offline.py`. |
| **REQ-6.12** | Release Packaging & Manifest | `PARTIALLY_IMPLEMENTED` | `release_management.py` needs inclusion of new Phase 6 test modules, reports, and release manifest validation. | Update `release_management.py` and run closeout validation script. |

---

## 2. Detailed Gap Analysis & Reproduction Cases

### Gap 1: Absence of Dedicated Phase 6 Paper Lifecycle & Accounting Test Suite
- **Defect/Gap:** While individual Phase 5A/B/C tests validated partial components of the paper portfolio, there is no single comprehensive test module (`test_phase6_paper_lifecycle.py`) registered in `test_bot.py` that verifies the complete chain from a Phase 4/5 qualified candidate to an explicit queue decision, simulated next-bar execution, adverse slippage application, dynamic mark updates, stop/target exit, and final EOD statement generation.
- **Reproduction:** Running `python -m unittest test_phase6_paper_lifecycle` returns `ModuleNotFoundError`.
- **Target Resolution:** Create `test_phase6_paper_lifecycle.py` covering:
  - Long and Short lifecycle under `OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1`.
  - Next-bar close fill under `FORWARD_FILL_POLICY` (`NEXT_COMPLETED_BAR_CLOSE_V1`).
  - Sizing with adverse slippage and statutory charge anticipation.
  - Double-entry balance reconciliation: $\text{Equity} = \text{Capital} + \text{Realized} + \text{Unrealized}$.
  - Idempotent re-entry prevention with conflicting parameter rejection.
  - Multi-position EOD settlement and tamper-evident SHA-256 statement hash verification.

### Gap 2: Incomplete Fault Injection & Recovery Test Coverage for Process Interruption
- **Defect/Gap:** The paper coordinator handles process interruption during pending orders, but needs automated fault-injection tests proving that if a process crashes immediately after committing an `ENTRY` event in `paper_events` but before updating `paper_candidate_decisions`, restarting the coordinator resumes cleanly, detects the existing entry, and updates the decision to `FILLED` without re-executing or double-reserving capital.
- **Reproduction:** Need automated test simulating interrupted state in SQLite.
- **Target Resolution:** Create `test_phase6_risk_recovery.py` with fault-injection fixtures:
  - Crash between `paper_events` INSERT and `paper_candidate_decisions` UPDATE.
  - Injection of corrupt account configuration hash -> triggers `ACCOUNT_CONFIG_CORRUPT` and blocks further trading.
  - Injection of orphaned events -> triggers `RECONCILIATION_REQUIRED`.
  - Injection of out-of-order candles -> triggers `MISSING_OR_OUT_OF_ORDER_POSITION_BAR`.
  - Rejection of unauthorized financial recovery actions (`UNAPPROVED_FINANCIAL_RECOVERY_ACTION`).

### Gap 3: Formal Verification of Performance Acceptance Metrics & External Data Gating
- **Defect/Gap:** Roadmap requires explicit verification that performance evaluation metrics (Net P&L, Sharpe, Profit Factor, Max Drawdown) strictly reconcile with trade-level executions, and that empirical performance acceptance is unconditionally BLOCKED when authentic publisher-signed market data is absent.
- **Reproduction:** Need automated test confirming that attempting to declare empirical acceptance on synthetic fixtures or unverified data raises `BacktestReadinessError` or produces `BLOCKED_BY_EXTERNAL_DEPENDENCY`.
- **Target Resolution:** Create `test_phase6_performance_validity.py` verifying:
  - Metric calculations match exact trade sums.
  - Adverse slippage and statutory cost deductions cannot be bypassed.
  - Look-ahead bias injection is detected and rejected.
  - External-data gate rejects empirical claims when data is not cryptographically signed.

### Gap 4: Web Dashboard UI Coverage for Paper Trading & EOD Reports
- **Defect/Gap:** `public/index.html` has API fetch methods for paper portfolio and session reports, but lacks dedicated DOM cards for displaying active paper positions, account equity, available margin, and EOD reconciliation status, and `test_cash_dashboard.js` lacks tests asserting these elements render correctly.
- **Reproduction:** Inspecting `test_cash_dashboard.js` shows tests for signals and scan runs, but needs dedicated assertions for `renderStoredReports` rendering of paper ledger and EOD statements.
- **Target Resolution:** Enhance `public/index.html` with explicit paper portfolio display cards, and add renderer regression tests to `test_cash_dashboard.js`.

---

## 3. Workstream Execution Roadmap

1. **Workstream A:** Create `test_phase6_paper_lifecycle.py` and register in `test_bot.py`.
2. **Workstream B:** Create `test_phase6_risk_recovery.py` and register in `test_bot.py`.
3. **Workstream C:** Create `test_phase6_performance_validity.py` and register in `test_bot.py`.
4. **Workstream D:** Update `public/index.html` and `test_cash_dashboard.js`.
5. **Coordinator:** Update `release_management.py`, run canonical offline suite (`verify_offline.py`), generate evidence, build release ZIP, and validate closeout.
