# TRADEPULSE AI — POST-EXECUTION FORENSIC AUDIT, MISSING REPORT RECOVERY, AND COMPLETION VERIFICATION

## Immediate instruction

The previous task was marked complete, but the required new standalone reports were not delivered to the user. The user also cannot confirm that the implementation and readiness targets were achieved.

**Reopen the task. Do not trust the previous completion label. Do not merely edit the existing reports. Do not create documentation that claims unverified success.**

Your first responsibility is to determine what actually happened in the workspace, what was actually implemented, what tests actually passed, and whether the required acceptance targets have been achieved.

The mandatory targets remain:

- Implementation: at least 80%.
- Readiness: at least 50%.

Use the existing official M01–M12 scoring rubric and its original formulas. Calculate both scores independently.

## Step 1 — Audit the actual execution

Inspect the current workspace at:

`C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`

Do not rely solely on the previous agent's final message or its claims.

1. Find the existing canonical reports and the latest task-specific reports, if any.
2. Check whether the six required new reports were actually created and where they were saved.
3. Inspect the current source tree, tests, configuration-validation code, relevant documentation, and changed-file evidence.
4. Inspect the real Git diff and status if Git metadata is available. If unavailable, state that limitation and use other reliable evidence without inventing a before-and-after diff.
5. Identify the actual changes made during the previous task, distinguishing them from pre-existing functionality.
6. Rerun appropriate tests against the current code. Do not copy historical test results as though they were just executed.
7. Verify the current configuration-only preflight without printing `.env` contents or making live broker requests.
8. Recalculate implementation and readiness from the official rubric. Verify the milestone weights and formulas first.

Preserve unrelated user work. Do not revert the previous task or overwrite existing reports.

## Step 2 — Create the missing reports immediately

Create a new task-specific report directory, using `docs/reports/` unless an established report convention already exists.

Generate these six new Markdown files with unique filenames:

1. `TRADEPULSE_PROJECT_INVENTORY_<TASK_ID>.md`
2. `TRADEPULSE_TASK_IMPLEMENTATION_REPORT_<TASK_ID>.md`
3. `TRADEPULSE_CHANGE_LEDGER_<TASK_ID>.md`
4. `TRADEPULSE_CAPABILITY_ACCEPTANCE_REPORT_<TASK_ID>.md`
5. `TRADEPULSE_SCORECARD_AND_MILESTONE_EVIDENCE_<TASK_ID>.md`
6. `TRADEPULSE_BLOCKERS_AND_NEXT_ACTIONS_<TASK_ID>.md`

Replace `<TASK_ID>` with a real unique identifier for this execution.

These are six separate, substantive, standalone reports. **Do not treat updating an existing report, producing a brief summary, or listing planned filenames as completion.**

### Report 1: Complete current project inventory

Document what is actually present in the project: architecture, directory structure, relevant source files, functions/classes, broker adapters, configuration, cash scanner, F&O, risk, backtesting, paper trading, persistence, API/dashboard, Telegram, scheduling, tests, dependencies, and documentation.

Explain the real end-to-end execution flow, identify disconnected or incomplete paths, and classify capabilities as implemented, partial, mock-only, blocked, unverified, or not implemented.

### Report 2: Actual task implementation

Document what the previous task genuinely changed, why each change was needed, the implementation details, tests executed, failures corrected, regression checks, unresolved work, and final status.

Separate pre-existing functionality from newly implemented functionality. If a reliable baseline diff is unavailable, say so explicitly.

### Report 3: File-by-file change ledger

List actual created, modified, and deleted files, their previous and current behavior where evidence exists, the functions/classes changed, and the tests supporting each claim.

Reconcile the ledger against the actual diff or clearly document the evidence limitation.

### Report 4: Complete capability acceptance

Document every major capability, its implementation location, test coverage, evidence type, integration state, known defects, external dependencies, acceptance status, and next action.

Explicitly distinguish offline fixture success from live market-data acceptance and operational readiness.

### Report 5: Auditable scorecard

For M01–M12, include the official weight, verified baseline implementation/readiness values, final values, weighted contributions, supporting evidence, and remaining acceptance gates.

Show the exact arithmetic for both overall scores, the percentage-point changes, and the distance from the 80% and 50% targets.

Do not change the rubric or award unsupported credit.

### Report 6: Blockers and next actions

For each remaining blocker, state the evidence, classification, remediation already completed, exact remaining work, and safe next action.

For the known malformed `.env` assignment, give a local-only diagnostic that reveals the parse error without printing configuration values or secrets.

Do not request credentials or ask the user to paste `.env`.

## Step 3 — Resume implementation if the targets are not achieved

Creating reports is necessary but is not a substitute for completing the software.

If implementation is below 80%, or readiness is below 50%, identify the remaining score gap and continue the actual implementation work.

Prioritize safe, independent engineering work that improves the relevant milestone scores. Implement changes, add regression tests, run the focused and broader test suites, fix failures, inspect the diff, and recalculate both scores.

Do not stop after generating the reports.

If a local configuration defect blocks one workflow, provide a safe local diagnostic and continue unrelated work. If broker authorization or other external evidence is required, do not fabricate it or make unauthorized live requests. Finish independent work and give the user the exact safe next action.

## Step 4 — Mandatory safety rules

- No order placement, modification, cancellation, or trading endpoints.
- No live broker requests during this recovery audit and offline implementation.
- No repeated requests to investigate 403 or permission failures.
- No secrets in logs, reports, or chat.
- No fake candles, fake provider responses, or fake acceptance receipts.
- No automatic provider switching.
- No weakening data-quality, provenance, session, freshness, identity, or risk controls.
- Keep Telegram in dry-run mode and production scheduling disabled.
- Do not skip or weaken tests to manufacture a pass.
- Do not claim a test passed unless it was actually executed.
- Do not mark the task complete while either mandatory score is below target.

## Step 5 — Verify the deliverables physically

Before finishing:

1. Confirm all six new reports exist in the workspace.
2. Confirm each report contains substantive content rather than headings or placeholders.
3. Reconcile their claims with actual source files, diffs, and test results.
4. Verify that the scorecard arithmetic is correct.
5. Verify that no secrets were written to the reports.
6. Confirm that the original reports were not overwritten.
7. Record the exact relative path of each new report.
8. Check that the current implementation and readiness scores are evidence-backed.

## Step 6 — Return a verifiable final response

Your final response must include:

- Actual completion status: `COMPLETED — BOTH TARGETS VERIFIED`, `PARTIAL — EXTERNAL BLOCKER; SAFE WORK EXHAUSTED`, or `INCOMPLETE — TARGETS NOT ACHIEVED`.
- Verified baseline and final implementation scores.
- Verified baseline and final readiness scores.
- Exact percentage-point changes and score calculations.
- Accepted milestone count out of 12, with justification.
- Actual test commands and current observed outcomes.
- The complete changed-file inventory or a clear reference to the new change-ledger report.
- All six exact report paths.
- Any remaining blockers and precise user actions.
- A clear statement of whether additional implementation work is still required.

Do not report completion based on the existence of the six reports alone.

**The task is complete only when both numerical targets are met with valid evidence and the six new reports are created, populated, and verified. If either target remains unmet, explicitly state that the task is not complete and continue implementation wherever it is safe and possible.**