# TRADEPULSE AI — DUAL-BROKER AUDIT, BLOCKER ANALYSIS & READINESS REASSESSMENT

## Mission

Continue the existing TradePulse AI / Indian F&O Signal Bot project in the current workspace.

Perform a complete evidence-based audit of:
1. Angel One SmartAPI integration.
2. Upstox integration.
3. Shared provider selection and configuration.
4. Cash-equity market-data acceptance.
5. Scanner, persistence, API, and dashboard integration.
6. Historical data, F&O, paper-trading, and release blockers.
7. Overall implementation completeness, readiness, and the formal M01–M12 milestone acceptance status.

The local `.env` placement mistake has been corrected. The latest diagnostic shows that configuration preflight passes, an Angel One RELIANCE quote was returned, but the candle request failed with HTTP 403 and the overall diagnostic exited 1. Upstox remains the active application provider.

Do not assume that any previous report or test result is still current. Inspect the actual workspace and verify the evidence.

## 1. Mandatory safety rules

- Do not place, modify, or cancel orders.
- Do not call broker order, position, holdings, balance, or other unnecessary account endpoints.
- Do not enable production services, scheduled jobs, real trading, or live Telegram delivery.
- Preserve `telegram_dry_run=true` and `enable_background_scheduler=false`.
- Do not make any new live broker requests during this audit. The recent diagnostic already provides a bounded observation. Diagnose the evidence and code first.
- Do not switch the configured provider to force a pass.
- Do not change credentials or configuration values automatically.
- Never print or request `.env` contents, API keys, PINs, TOTP secrets, tokens, authentication headers, or other secrets.
- Never fabricate market data, provider responses, timestamps, test results, or successful acceptance.
- Never weaken identity, provenance, source qualification, freshness, completed-candle, session, duplicate, risk, replay, or safety checks.
- Preserve existing user modifications, architecture, and unrelated work.
- Do not delete files, perform broad refactors, add unnecessary dependencies, skip tests, or weaken assertions.
- Treat the latest diagnostic output as evidence, not as proof that every integration stage works.
- Clearly distinguish source-code inspection, mocked tests, historical reports, and genuine provider observations.
- Do not mark an official milestone accepted without satisfying its full existing acceptance rubric.

## 2. Establish the workspace and preserve changes

Confirm that the project root is:

`C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`

Verify the working directory before running any command.

Inspect the current working-tree changes using Git if repository metadata is available. If Git metadata is unavailable, do not initialize a repository or alter the workspace just to obtain a diff.

Read these existing documents if present:

- `docs/TRADEPULSE_CONTINUOUS_ACCEPTANCE_REPORT.md`
- `docs/TRADEPULSE_PHASE5C_ENGINEERING_REPORT.md`
- `docs/TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md`
- `docs/TRADEPULSE_FO_CONTRACT_COVERAGE.md`
- `docs/TRADEPULSE_HISTORICAL_PROVENANCE_DESIGN.md`
- `docs/TRADEPULSE_PAPER_PORTFOLIO_REPORT.md`
- `docs/TRADEPULSE_CAPABILITY_MATRIX.md`
- `docs/TRADEPULSE_COMPLETION_ROADMAP.md`

Use the actual files and current contents. If a document is missing, report it instead of inventing its contents.

Record:
- The current branch and existing changes, if available.
- The exact Python version and environment used.
- The active application provider.
- Configuration-loading behavior and source precedence, without revealing values.
- Current scheduler and Telegram safety settings.
- The baseline tests and reports used for this reassessment.

## 3. Audit `.env` discovery and configuration loading

Inspect how the application loads environment variables. Trace the configuration path from process startup to broker initialization.

Determine:
- Which directory is used to locate `.env`, if any.
- Whether loading depends on the current working directory.
- Whether the project uses an explicit path, a dotenv library, or process-level environment variables.
- Whether the four existing Angel One fields are recognized.
- Whether configuration preflight checks field presence and basic validity without exposing values.
- Whether provider selection remains explicitly controlled by the existing configuration.
- Whether tests accurately cover the original wrong-directory failure and the corrected project-root behavior.

Do not print secret values or dump the environment. Do not modify provider selection or silently add fallback credentials.

If a reproducible configuration bug exists, make the smallest safe correction and add a regression test. Preserve the existing configuration architecture.

## 4. Audit Angel One end to end

Inspect the actual Angel One implementation, including authentication, quote retrieval, candle retrieval, instrument mapping, rate-limit handling, timestamp parsing, source qualification, and error sanitization.

Use the latest supplied diagnostic as the initial evidence:

- Provider: `angelone`.
- Symbol: `RELIANCE`.
- Exchange: `NSE`.
- Instrument token reported: `2885`.
- Configuration check: PASS.
- Instrument reference check: PASS, with historical validity not established.
- Quote check: PASS, LTP `1220.3`, observation age `0.622` seconds, timestamp `2026-10-19 10:51:51`.
- Candle check: FAIL, HTTP `403`, error category `ACCESS_DENIED`.
- Authentication acceptance: FAIL because no successful authorized market-data response was observed.
- Overall status: FAIL.
- Exit code: `1`.
- Data persisted: `false`.
- Readiness receipt issued: `false`.
- Active application provider: `upstox`.
- Scheduler disabled; Telegram dry run enabled.

Investigate, using source code and existing sanitized logs, whether the HTTP 403 originates from:
- The specific candle endpoint or request format.
- Provider permissions or subscription/authorization restrictions.
- Session/token handling.
- Rate limiting or provider throttling.
- Incorrect segment, exchange, instrument identity, or historical request parameters.
- Another documented or evidenced cause.

Do not select a cause merely because it is plausible. Label the cause UNKNOWN when evidence is insufficient.

Check whether the implementation correctly:
- Uses the documented supported authentication and market-data flow.
- Separates a successful quote from successful candle acceptance.
- Limits retries and does not automatically recover a session.
- Sanitizes errors and avoids credential leakage.
- Validates response schema, instrument identity, timestamps, candle completion, session, and freshness.
- Rejects unqualified observations and avoids issuing a readiness receipt.
- Prevents isolated provider diagnostics from changing the configured application provider.

Do not issue another live request to confirm the 403. If external authorization is the remaining blocker, state the exact evidence needed for the next authorized test.

## 5. Audit Upstox end to end

Inspect the actual Upstox implementation and the earlier reported HTTP 403/FORBIDDEN result.

Trace:
- Configuration and credential discovery.
- Authentication and token lifecycle.
- Read-only quote and candle request construction.
- Instrument mapping and segment requirements.
- Response parsing and error handling.
- Timestamp, freshness, candle completion, and source qualification.
- Persistence and downstream scanner integration.
- Existing offline tests and their limitations.

Determine whether the earlier 403 cause is established, still unknown, or superseded by later evidence.

Do not assume that Upstox works simply because it is selected. Do not assume it fails solely because of an older report. Report the newest actual evidence and its date.

Do not switch to Angel One or change the active provider. Treat provider selection and isolated diagnostics as separate concerns.

For each provider, create an evidence matrix with:
- Configuration readiness.
- Authentication acceptance.
- Quote acceptance.
- Candle acceptance.
- Instrument identity qualification.
- Timestamp/freshness qualification.
- Persistence.
- Scanner integration.
- Dashboard integration.
- Current blockers.
- Last verified evidence and verification method.

Use PASS, FAIL, BLOCKED, PARTIAL, or NOT TESTED precisely.

## 6. Audit the cash-equity scanner and dashboard

Inspect the actual scanner, backend routes, persistence layer, and dashboard implementation.

Verify offline that:
- Invalid credentials are rejected safely.
- Stale candles are rejected.
- Incomplete candles are not accepted as completed observations.
- Invalid or unqualified source provenance is rejected.
- Duplicate and replay protections remain effective.
- A genuine no-signal evaluation is distinguishable from missing data or a failed provider request.
- Scanner output is exposed through the correct existing backend routes.
- The dashboard does not represent unknown provenance or old stored data as current live data.
- `LIVE SOURCE (STORED)` is distinguishable from a current accepted live observation.
- Error and unavailable states are truthful.
- Scheduler and Telegram dry-run protections remain intact.

Determine whether the current dashboard is merely implemented, has passed static/renderer tests, has passed API tests, or has passed a real browser end-to-end test.

Do not call browser acceptance complete without actual browser evidence. Do not create synthetic data that masquerades as live data.

## 7. Re-run offline tests and inspect regressions

Use the existing test suite and test conventions. Run the focused provider/configuration tests, relevant safety tests, JavaScript renderer tests if available, and the full strict suite if the environment permits.

Compile the affected Python modules.

Record the exact commands, actual exit codes, pass/fail/skip counts, warnings, and environment.

Check the final diff for:
- Weakened validation.
- Removed assertions.
- Unnecessary provider-selection changes.
- Secret leakage.
- Changed retry behavior or transport limits.
- Scheduler or Telegram safety regressions.
- Misleading live labels.
- Unrelated changes.

Do not claim that tests passed unless they were actually run during this audit. If a test cannot run, explain why.

## 8. Audit the remaining project-wide blockers

Assess the actual evidence for these areas:

1. Authoritative cash-equity and F&O instrument identity.
2. Genuine live cash quote and completed-candle acceptance.
3. Authoritative F&O contract masters, expiries, identifiers, and executable contract mapping.
4. Historical price authenticity, provenance, chronological replay, and data-repair policy.
5. Strategy validation, realistic transaction costs, risk-adjusted metrics, and out-of-sample testing.
6. Paper portfolio recovery, market-calendar handling, missing EOD candles, financial reconciliation, and operational soak.
7. Strategy 3 acceptance and other explicitly blocked strategies.
8. Dashboard browser end-to-end acceptance.
9. Release, backup/restore, rollback, monitoring, and operational recovery.
10. Credential security and documented local setup.

Distinguish implementation existing in code from operational acceptance. Do not call a strategy profitable without reliable test evidence. Do not treat a local schema or matching hash as proof of authoritative source authenticity.

## 9. Recalculate readiness from the official rubric

Read the existing capability matrix and roadmap. Recalculate:
- Implementation completeness.
- Operational readiness.
- M01–M12 milestone acceptance status.
- Number of milestones fully accepted.
- Remaining acceptance blockers.
- The smallest next work package that can move the project forward.

Use the existing scoring definitions and weights. If the rubric is ambiguous or the available evidence is insufficient, state that and provide a range or an explicitly provisional score instead of inventing precision.

For every score, explain the evidence and the remaining criteria. Keep implementation completeness separate from readiness.

Do not mark any milestone accepted unless every mandatory criterion is supported by evidence.

## 10. Produce the deliverables

Update `docs/TRADEPULSE_CONTINUOUS_ACCEPTANCE_REPORT.md` additively with a dated audit section. Preserve the previous report and historical evidence.

Create or update a concise dual-broker matrix, using an existing project document where appropriate instead of creating unnecessary new files.

The final report must contain:

1. Executive verdict.
2. Workspace and configuration-loading findings.
3. Angel One findings, including the quote/candle discrepancy and HTTP 403 evidence.
4. Upstox findings and the current status of its prior 403.
5. Exact commands and offline test results.
6. Cash scanner, persistence, API, and dashboard status.
7. Project readiness scores with their evidence and methodology.
8. M01–M12 accepted versus unaccepted status.
9. All unresolved blockers, with clear owners/actions where determinable.
10. A prioritized next-step plan.
11. A precise go/no-go decision for the next live cash-equity observation.
12. The exact conditions required before considering derivatives or live trading.

Do not include credentials, tokens, headers, or raw environment contents in the report.

## Required final response format

Return:
- **Current verdict:** READY, NOT READY, or BLOCKED, with the scope stated.
- **Angel One status:** concise evidence-backed conclusion.
- **Upstox status:** concise evidence-backed conclusion