# Astra mission contracts and ownership — 2026-10-24

This is an implementation contract, not an acceptance claim. The original six
phases remain unchanged. The supplied master mission controls scope; the original
BRD and earlier reports are evidence to audit. Baseline source has 88 files and
the current-source Phase 6 receipt validates 1,040 retained Python executions.

## Required behavior

| ID | Requirement and owning phase | Intended evidence |
|---|---|---|
| A01 | Preserve saved settings, prior artifacts, original BRD and operational DB; phases 1/6 | Before/after hashes for source documents/config; DB never opened |
| A02 | Validate actual retained Phase 4/5/6 source/log/archive claims; phase 6 | Historical binding versus current receipt explicitly distinguished |
| A03 | Keep source/rights/dated identity/study/live gates truthful; phases 2/3 | Precise evidence and missing prerequisite report |
| A04 | Retain qualified, source-bound, versioned paper setup; phases 4/6 | Scanner/evaluation/decision integration tests |
| A05 | Automatic next eligible completed-candle trigger; phase 6 | Long/short non-trigger, touch, confirmation, chronology, expiry tests |
| A06 | Reuse transactional risk/accounting and conservative simulated fills/exits; phase 6 | Recovery/concurrency/rollback/cost/P&L/EOD tests |
| A07 | Retain trigger/source/processing timestamps, evaluations and full history; phase 6 | Durable ledger and read-back evidence |
| A08 | GET/HEAD cannot scan or mutate paper state; phases 5/6 | Actual HTTP method regression |
| A09 | Ranked opportunities, maturity, trigger and paper journal truthfulness; phases 4/5 | Node tests plus actual integration/render evidence |
| A10 | Freeze research comparison/promotion design without empirical claims; phase 2 | Per-strategy hierarchy and qualified-study controls |
| A11 | Official regulatory/data-rights review and commercial hypotheses; phase 6 | Dated primary citations and launch prerequisites |
| A12 | Canonical strict verification, new release, updated BRD and independent review; phase 6 | Fresh execution-bound receipts and archive integrity |

## Paper policy

Existing cash strategies already require completed-candle confirmations, including
OB first retest, VWAP reclaim/rejection, ORB crossing, and Supertrend pullback.
Their formulas and original decision entry prices are preserved. A new explicitly
versioned **future completed-close continuation** paper policy adds an entry gate:
after creation, a qualified completed 5-minute candle must close at or beyond the
original entry threshold in the setup direction. A wick touch alone is insufficient.
This is an additional paper-entry policy, not a claim that every original strategy
uses threshold crossing or that a retest is re-run. Unsupported rule kinds reject.

Existing accounts retain their original immutable fill policies. New trigger
accounts use a distinct policy identifier, through the existing coordinator and
portfolio. No second ledger. Pending states retain existing top-level QUEUED,
FILLED, REJECTED for compatibility, with precise lifecycle/reason metadata.
Versioned setup identity binds candidate, qualified persisted evaluation/rank,
source input digest, rule/version, instrument and explicit fill/expiry assumptions.
Only persisted qualified evaluations may create eligible new-policy setups.

Bound pending validity to a small explicit number of consecutive same-session
bars and square-off. Each required observation must arrive in order and within
freshness limits. Missing observations freeze/reject; never recreate a historical
entry from a later batch. Process replay one observation at a time with an explicit
replay clock. Retain every bounded setup evaluation and source/processing time.
The new policy fills at the observed confirmation close with conservative tick
rounding and modeled costs, never at an assumed exact trigger. Tick assumptions
are explicit simulation parameters, not exchange contract authority. Reject a
bar which already invalidates the setup or touches its first target before fill.
Existing stop-first, gap, EOD, risk, transaction and reconciliation controls remain.
T1 full exit is supported; T2/trailing/partial exits must be marked unsupported.
MFE/MAE and duration may be null where intrabar sequencing prevents exact values.

LIVE source scope is separate from SIMULATED execution. Synthetic native-wire
tests never establish genuine live acceptance. No provider request, scheduler,
real order or Telegram transmission is authorized by local implementation.

## Exclusive ownership

| Worker | Files |
|---|---|
| /root/astra_paper_audit | forward_paper.py, paper_portfolio.py, new paper_triggers.py, new test_astra_paper_triggers.py, new paper architecture report and focused evidence |
| /root/astra_product_audit | public/index.html, test_cash_dashboard.js, new product/regulatory report and focused evidence |
| /root/astra_research_audit | new strategy_evidence.py, new test_astra_research.py, historical_study.py only after preserved repro, new research/data reports and focused evidence |
| /root | scanner_engine.py, storage.py, candle_lineage.py, server.py, test_bot.py, release_management.py, new integration/HTTP tests, canonical evidence, updated BRD and final integration |

Shared changes are mediated by the coordinator. No worker edits saved config,
operational DB, prior reports/receipts/releases or another owner's files. Each
worker records actual reproduction, commands/results, limitations and final hashes.
Independent review follows integration and precedes final source-bound verification.
