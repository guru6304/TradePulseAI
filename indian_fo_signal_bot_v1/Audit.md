# TradePulse AI — Phase 3B Independent Findings Verification

**Recommended model:** GPT-6.1 Sol — Extra High  
**Mode:** Strict read-only source audit  
**Current phase:** Phase 3B implementation review  
**Next phase:** Phase 3B.1 remediation planning, not Phase 3C

## Project objective

TradePulse AI is a deterministic Python research and intraday signal platform for Indian markets. It contains five strategy evaluators, broker-data adapters, Telegram alerts, a dashboard, SQLite persistence, historical-data validation, and a backtest engine.

Our goal is to establish whether the strategies perform credibly on trustworthy historical data after realistic execution costs and risk controls. We must not manufacture confidence, bypass acceptance gates, or claim profitability without evidence.

## Your assignment

Read the existing repository and verify the findings in the supplied GPT-6.1 Sol High orientation report against actual source code and tests.

**Do not edit, create, delete, rename, or reformat any project files. Do not begin Phase 3C.**

Inspect the relevant functions, their callers, storage queries, configuration defaults, and tests. Do not accept the earlier report blindly; confirm or refute each finding with evidence.

## Required verification order

1. **Historical readiness and execution gates**
   - Trace how LIVE backtests establish acceptance.
   - Determine whether incomplete datasets, missing sessions, or gaps can reach replay.
   - Check whether the acceptance gate can be disabled and how defaults are chosen.
   - Distinguish per-symbol eligibility from aggregate dataset readiness.

2. **Position sizing and accounting**
   - Trace quantity/lot sizing, capital constraints, risk percentage, stop distance, slippage, commissions, taxes, and other charges.
   - Check whether minimum quantity rules can exceed the risk budget.
   - Verify realized P&L, net P&L, drawdown, daily limits, and trade-ledger consistency.
   - Check gap fills, stop/target collisions, and end-of-day exits.

3. **LIVE/SIMULATED state isolation**
   - Trace signal deduplication keys, mitigated-zone persistence, startup loading, and every related query.
   - Determine whether provider or data mode is consistently scoped.
   - Identify reproducible cases where one mode can suppress or contaminate another.

4. **Freshness and Phase 2C acceptance**
   - Trace broker candle freshness checks through normal scanner paths.
   - Check stale-data handling and instrument identity validation.
   - Establish whether acceptance from a separate diagnostic process can be verified by a later process without trusting a manually supplied status.
   - Never make real broker or network calls.

5. **Strategy 3 contract-level execution**
   - Trace historical option inputs from import through eligibility, signal evaluation, entry/exit prices, lot sizing, and accounting.
   - Determine whether option-contract candles actually drive fills.
   - If they do not, specify what must be implemented before Strategy 3 can be evaluated.

6. **Research reproducibility and API/documentation mismatches**
   - Verify chronological train/validation/out-of-sample separation and whether date ranges are enforced.
   - Check candle pagination and dataset limits.
   - Verify CLI flags against the actual parser.
   - Determine whether the dashboard's backtest view runs the engine or displays hypothetical profiles.
   - Record other material safety, delivery, or documentation discrepancies.

## Evidence rules

For every finding, provide:
- Status: CONFIRMED, PARTIALLY CONFIRMED, NOT REPRODUCED, or UNVERIFIED.
- Exact file, function, and line range from the current checkout.
- The execution path that produces the behavior.
- A concrete failure scenario or a minimal proposed regression test.
- Severity and why it matters.
- The smallest safe correction and its dependencies.

Do not invent line numbers, claim tests were run when they were not, or infer live acceptance from mocked tests. Clearly separate source inspection, test evidence, and operational evidence.

## Deliverables

Return a concise report with:

1. Executive decision: whether Phase 3B can be accepted as research-ready.
2. A prioritized findings table.
3. Evidence for each of the six verification areas.
4. A proposed Phase 3B.1 remediation plan, split into small, independently testable work packages.
5. Regression tests required for each package.
6. Commands to run on Windows PowerShell, clearly distinguishing offline tests from commands that can contact a broker.
7. Explicit exit criteria for Phase 3B.1 and the remaining Phase 2C/live-data gates.
8. A list of unresolved questions that require evidence rather than assumptions.

Do not implement the plan. Stop after the report and wait for approval.

## Non-negotiable safeguards

- No order placement or trading execution.
- No broker/network calls during this audit.
- No secrets printed or requested.
- No mixing LIVE and SIMULATED data or state.
- No look-ahead bias or use of unfinished candles.
- No claims of profitability from synthetic fixtures.
- Do not silently relax readiness, freshness, or risk controls to make tests pass.
- Preserve the existing architecture unless a specific defect requires a justified, narrowly scoped change.

The desired outcome is a reliable, reproducible research system—not merely a passing test count.