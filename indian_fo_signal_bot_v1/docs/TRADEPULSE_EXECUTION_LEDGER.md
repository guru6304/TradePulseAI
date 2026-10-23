# TradePulse AI execution ledger

## Objective and safety

Deliver a traceable, explainable Indian cash/F&O intelligence product: first prove
offline end-to-end testing readiness, then implement independent production work.
Only executed evidence passes a gate. Fixtures are not live acceptance. The current
runtime selects paper_sim, Telegram dry-run and disabled production scheduler.
The current Task 2 authorizes a minimal read-only Dhan feed probe only after
offline tests and local preflight pass. Token refresh, orders, account mutation,
Telegram delivery and scheduler activation are outside scope. Preserve existing work.

## Current Task 2: historical qualification and Dhan feed

Two explicitly requested worker tracks implemented historical qualification and
Dhan streaming, coordinated through the existing canonical instrument/candle
contracts. Entry baseline: HEAD `205803131d7e1a17d6b42ce976efe7dff30e475a`,
existing source/log receipt verified against the entry files (758/10/56; not rerun).
During work HEAD advanced externally to
`2ef6751a4f393507d13522a505d1070356114779`; no agent performed a git mutation.
All prior modifications, evidence and releases were preserved.

Track A adds immutable SQLite originals, current operator-reviewed rights scope,
current genuine publisher verification and frozen chronological walk-forward
evaluation using the existing engine. Completed persisted option replays retain
their complete original embedded source/manifest bytes. Real historical-study
acceptance remains blocked without approved roots, rights and authentic sources.

Track B implements documented v2 binary normalization, bounded subscriptions,
volume-aware 1m/5m aggregation, durable source lineage, health, reconnect isolation
and cleanup. Root integration adds explicit configuration, adapter attachment,
guarded candle consumption and health/dashboard visibility. Configuration never
starts a socket or changes provider. Fixture streams cannot supply LIVE scanner
bars. Local preflight found missing/placeholder Dhan credentials and an empty
instrument scope: no live probe was attempted.

Verification and exact per-file changes are recorded in
[the consolidated report](reports/TRADEPULSE_TASK2_PARALLEL_IMPLEMENTATION_REPORT.md).
Machine evidence and the exact final ZIP/build/inspect records are retained at
the [documented repository evidence location](RELEASE_EVIDENCE_LOCATION.md).
Final canonical `verify_offline.py --stage task2_parallel_verified`: **803/803
Python PASS**, zero failures/errors/skips, **11/11 dashboard PASS**, **62 compiled**,
298.968 seconds, unchanged source and no unraisable errors. Validator exit 0.
Focused Track A:49 PASS; Track B:26 PASS; shared integration:69 PASS. The receipt
`docs/evidence/task2_parallel_closeout.json` binds those source hashes, preserved
historical evidence and the exact new release candidate. No real source/study or
live acceptance is established by these offline results.
The fixed six product phases remain unchanged. Scores have not been recalculated;
the former 64.25/37.00 estimates and 0/12 milestone result are historical.
Next dependency: an operator-approved authentic provider source with documented
rights and local account permissions, to exercise real historical/live gates.

## Historical Phase 4A/4B checkpoint (preceding request)

Master execution started 2026-10-21; continued 2026-10-22. Active stage:
**Phase 4A/4B PASS - OFFLINE ENGINEERING**, with Phase 4 real-data qualification and Phase 7
BLOCKED_EXTERNAL_DEPENDENCY. Offline cash testing and the available Phase 5/6
engineering checks are PASS for the current source.
Next action: obtain operator-approved publisher roots/rights and an authentic
signed dated contract + bid/ask/depth/prior-closing-OI dataset; run the existing
qualification gates and option CLI under that explicit local trust profile.
Trust verification and bounded historical option execution are implemented and
focused-tested; authentic data/operating acceptance remains separate. Do not restart
the baseline audit or enable live services.
Contract cache, history pagination, durable dry-run outbox, operational API/UI,
three-session paper qualification, isolated application restore and CI are implemented.
Qualified sources, actual option execution and exact authorized live reads remain
separate acceptance requirements; missing implementation is not an external excuse.

Actual repository root is `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`;
application directory `indian_fo_signal_bot_v1`, branch `main`, starting HEAD
`60834ddf0f6258e63fc73680df508075f5dd21b8`. Task 4 edits and untracked files are
present and are the preserved starting state. No reset/clean/checkout was performed.
No prior execution ledger existed. Historical reports/evidence remain historical.

## Ordered gates

| Phase | Gate | Status | Required evidence / independent next work |
| --- | --- | --- | --- |
| 0 | True current baseline | PASS | Fresh 675/675 Python, 6/6 Node, 39 files compiled, local config and Task 4 audit exit 0. |
| 1 | Offline integrity/recovery | PASS | Full signal-field reconciliation repaired; 686-case strict suite passes. |
| 2 | TESTING READY | PASS | Actual cash/scanner/paper/HTTP/renderer path and negatives/restart pass; repeatable command and source-bound manifest. |
| 3 | Adapters and contract universe | PASS | Offline parser/cache/expiry/last-good and existing adapter negative tests; publisher authenticity and live access unaccepted. |
| 4 | Qualified reproducible research | IN_PROGRESS | Pagination and reproducibility fix PASS; qualified source BLOCKED_EXTERNAL_DEPENDENCY; source verifier/option execution remain local implementation gaps. |
| 5 | Paper operations/delivery | PASS | Scoped cash testing: three-session fixture, faults/restart/EOD, durable local previews and actual reporting pass in final 722-case run. Real delivery/session/derivative acceptance absent. |
| 6 | Release engineering | PASS | Available local checks: source/log validation, 56-file deterministic candidate, application restore, startup/security/runbook pass. Hosted runtime matrix, authenticated deployment/central alerting and operating acceptance remain unaccepted. |
| 7 | Controlled external acceptance | BLOCKED_EXTERNAL_DEPENDENCY | BLOCKED_PENDING_OPERATOR_AUTHORIZATION; separately confirm account/permissions and authorize exactly one RELIANCE quote GET and one candle GET. |

## Evidence and progress accounting

Each subsequent entry records exact command/CWD, exit/result/counts, log and scope.
All application commands run in `indian_fo_signal_bot_v1` unless stated otherwise.
Do not add overlapping suite counts. Preserve Task 4's intermediate 674-case log
and later 675-case log. Official starting allocation is historical I=64.25/R=37.00,
0/12 accepted; recompute only when fresh evidence crosses the unchanged rubric.
The testing and production reports will carry per-milestone before/after evidence.

## External dependencies

| Dependency / owner | Status | Evidence required to clear |
| --- | --- | --- |
| Exact broker read authorization / operator | BLOCKED_EXTERNAL_DEPENDENCY | Private intended account/environment and credential/permission confirmation, then explicit two-GET RELIANCE scope; no secrets in chat. |
| Authoritative current/dated NFO and calendar / licensed publisher + owner | BLOCKED_EXTERNAL_DEPENDENCY | Authentic retained source, rights, scope, effective dates and trust policy. Offline parser/cache work proceeds independently. |
| Qualified historical cash/options / publisher + owner | BLOCKED_EXTERNAL_DEPENDENCY | Licensed observations, dated exact contracts, independent authenticity/effective-date evidence. Pagination/research mechanics remain independent. |
| Operating acceptance / owner | BLOCKED_EXTERNAL_DEPENDENCY | Declared real sessions, provider/monitoring/deployment environment and acceptance evidence; offline failure/release work proceeds. |

## Phase 0 executed baseline (PASS)

All commands used the application working directory. Logs are under `docs/evidence/`.

| Exact command | Exit / counts | Log / scope |
| --- | --- | --- |
| `python -B -W error::ResourceWarning -m unittest test_bot -v` | 0; 675 passed, 0 failures/errors/skips, 156.753s | `master_phase0_python.txt`; fixtures/mocks/temp SQLite/localhost. |
| `node test_cash_dashboard.js` | 0; 6 passed, 0 failures/skips | `master_phase0_dashboard.txt`; actual inline JS, DOM double. |
| `python -B -c "import pathlib, py_compile; files=sorted(pathlib.Path('.').glob('*.py')); [py_compile.compile(str(p),doraise=True) for p in files]; print('COMPILED',len(files))"` | 0; 39 compiled, not test cases | `master_phase0_compile.txt`. |
| `python -B configuration_check.py` | 0; LOCAL_CONFIGURATION_VALID; no live requests/auth/quote/candles tested | `master_phase0_config.txt`. |
| `python -B docs/evidence/task4_verify.py` | 0; historical 675 IDs and final log agree | `master_phase0_task4_audit.txt`; ran before new implementation, refreshed derived Task 4 inventory/manifest; original logs unchanged. |

Count discrepancy resolved by direct log inspection: `task4_full_offline_suite_final.txt`
is the earlier 674-case run; `task4_regression_verified.txt` is the later 675-case run,
including the added overlap regression. The fresh baseline also executes 675.
The old audit hardcodes historical counts/hash expectations and does not execute
tests; it is not current readiness proof after source changes. New verification
records real unittest results and refuses zero/missing/duplicate/skipped cases.

## Phase 1/2 implementation and focused evidence

- `candle_lineage.py`: compare all persisted candidate prices, quantity, risk,
  strategy/provenance, scores and rationale with immutable result before exposure.
  Quantity tamper was reproduced before the fix.
- `server.py`: optional explicit paper handoff; scan storage failures return 503;
  read-only `/api/scan-lineage` and bounded `/api/cash-candles`; reconciled candidate
  source and paper-decision fields, no real-execution authorization.
- `scanner_engine.py`: explicit empty-result reason, preserving existing gates.
- `public/index.html`: source batches and paper rejection/status visible; fixture
  scope overrides live-shaped fixture metadata. Stored candidates remain candidates.
- `test_cash_workflow.py`: real mocked-adapter input through scanner/ledger/local
  HTTP and actual Node renderer; negative, duplicate, risk-rejected, restart cases.
- `verify_offline.py`, `test_verify_offline.py`: repeatable unittest entry point,
  actual execution IDs/counts, source/log binding, strict skips/subtests and loopback
  network guard. Release manifest and unified loader include the new modules.

| Exact command | Exit / counts | Evidence |
| --- | --- | --- |
| `python -B -W error::ResourceWarning -m unittest test_cash_workflow -v` | 1; 4 cases, 2 failures + 2 errors, 0 skipped | `master_cash_workflow_before.txt`; reproduced missing handoff/reasons/503 and quantity integrity gap. |
| `python -B -W error::ResourceWarning -m unittest test_cash_workflow test_cash_lineage -v` | 1; 31 cases, 2 failed, 0 errors/skips | `master_cash_workflow_first_fix.txt`; item-level fixture label missing; new reverse-wire test expectation corrected to existing strict 502 policy. No validator weakened. |
| `python -B -W error::ResourceWarning -m unittest test_cash_workflow test_cash_lineage test_phase4_e2e -v` | 0; 42 passed, 0 failures/errors/skips | `master_cash_workflow_verified.txt`. |
| `python -B -W error::ResourceWarning -m unittest test_verify_offline test_cash_workflow test_release_management -v` | 0; 25 passed, 0 failures/errors/skips | `master_verification_entrypoint_focused.txt`. |

Focused counts overlap and are not added. Public documentation review (no market
requests) is underway for Phase 3; links and exact supported contracts will be
recorded with implementation evidence. No live authorization has been inferred.

## Gate 2 acceptance (PASS)

`python -B -W error::ResourceWarning verify_offline.py --stage gate2` returned 0:
686/686 actual Python cases passed, 0 failures/errors/skips, 122.560s. Node renderer
8/8 passed, syntax exit 0, 42 root Python files compiled. Execution IDs agree with
the loaded unique inventory; source before/after hashes match; no unraisable errors.
`python -B verify_offline.py --validate-evidence docs/evidence/master_gate2.json`
returned 0 against that exact source version. Evidence: `master_gate2.json` and
its Python/Node/syntax logs. This gate will be rerun after subsequent source changes;
its current-source validator correctly treats later code as a new version.

Testing readiness advanced from no connected HTTP/paper/source inspection proof
to PASS. This is an offline engineering gate, not a fully accepted M01-M12 product
milestone or real-market acceptance. The production and scoring gates remain separate.

## Phase 3/4 implementation and continuation checkpoint

On 2026-10-22 the operator HEAD is `bd499cdb8d312e41ef79d6a11199bbc9b6e75c6f`.
The previous HEAD/design history and all remaining tracked, staged and untracked
work are preserved. `master_phase0_python.txt` has an existing staged/working split;
it is not rewritten here. No new audit or baseline reset was started.

- `contract_universe.py`, `instrument_identity.py`, `storage.py`: local Upstox
  native JSON derivatives observation import across stock/index FUT/CE/PE, exact
  underlying/key/token/label/expiry/strike/lot checks; immutable original bytes;
  atomic pointer/attempt history; last-good retention; same-date/future/stale checks;
  canonical numeric-term conflict detection; local gzip/JSON CLI, no download.
  All observations remain unqualified, ineligible and barred from historical replay.
- `historical_pagination.py`, store/readiness/backtest integration: keyset cursor,
  insertion watermark, consistent read transaction, streaming digest and exact
  original scope; restart excludes later inserts, detects changed snapshot rows.
  Existing engine now reads beyond 10,000 instead of silently taking its first page.
  Explicit 250,000-bar replay memory limit fails closed. Paged source metadata is
  retained in backtest assumptions; qualified LIVE and Strategy 3 gates stay closed.
- Unified tests/release manifest include the new production and test modules.
  The existing truncated-read regression now patches the new snapshot reader while
  preserving its original fail-closed assertion; no acceptance gate was loosened.

| Exact command | Exit / actual results | Evidence |
| --- | --- | --- |
| `python -B -W error::ResourceWarning -m unittest test_contract_universe -v` | 1; 6 cases, 5 error records, 0 failures/skips | `master_contracts_before.txt`. |
| `python -B -W error::ResourceWarning -m unittest test_contract_universe test_phase5a_contracts test_blocker_removal -v` | 0; initial 49 passed, then expanded 52 passed; 0 failures/errors/skips | `master_contracts_first_fix.txt`, `master_contracts_verified.txt`. |
| `python -B -W error::ResourceWarning -m unittest test_historical_pagination -v` | Before: exit 1, 5 cases/10 error records; after: exit 0, 5 passed, 0 failures/errors/skips | `master_history_before.txt`, `master_history_first_fix.txt`. |
| `python -B -W error::ResourceWarning verify_offline.py --stage history` | 0; 700 passed, 0 failures/errors/skips, 202.998s; 8 Node passed, source unchanged | `master_history.json` and bound logs. |

History evidence includes 10,050 exact ordered bars, resumed cursors after reopening
the real file store, exclusion of later ingestion, change detection, and actual
paged-versus-direct backtest checksum/metrics/capital equivalence. Fixtures remain
synthetic. These tests do not qualify real history or demonstrate returns.

Public documentation was inspected without broker/market-data requests:
[V3 intraday candles](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/),
[V2 full quotes](https://upstox.com/developer/api-documentation/get-full-market-quote/),
[standard API limits](https://upstox.com/developer/api-documentation/rate-limiting/),
[native instrument JSON](https://upstox.com/developer/api-documentation/instruments/).
Existing endpoint selection and bounded no-auto-retry error handling agree with the
reviewed contracts. Public documentation is not evidence of this account's access.
The new native parser preserves observed terms instead of inferring listing dates
or treating a content hash as publisher authentication.

## Phase 5/6 implementation and executed evidence

- `notification_outbox.py`, `storage.py`, `scanner_engine.py`, `candle_lineage.py`:
  immutable local dry-run intent commits with scanner result. Rendering acknowledges
  only after commit; attempt/receipt audit, bounded 5s/10s retry, terminal DEAD,
  restart/concurrent acknowledgement idempotency, rollback/lost acknowledgement and
  tamper rejection. No destination, sender or real-delivery worker is authorized.
- `server.py`: loopback peer/Host and same-origin checks precede initialization;
  removed wildcard CORS. Local CLI and same-origin browser contracts remain.
  Bounded read-only outbox/history pages expose stored facts without dispatch or
  acquisition. Health exposes pending recovery, preview retries, stale/provider
  errors and explicit paper reconciliation; required failure returns 503.
- `public/index.html`, `test_cash_dashboard.js`, `test_cash_workflow.py`: actual
  HTTP paper/outbox/research responses feed actual renderer; stored reports and
  explicit EOD date input; missing/rejected accounting unavailable; request-sequence
  guards clear old values and discard delayed responses after health failure.
- `release_management.py`, `test_release_operations.py`: deterministic scoped ZIP,
  immutable exclusive destination, embedded hashes, no private state; inspection
  rejects changed content/undeclared paths. Extracted generated archive loads its
  unique complete unittest inventory. Isolated backup is reopened with the actual
  store/migrations, reconciled cash results, paper accounts and notification audit.
  A quantity-tampered database passes SQLite integrity but fails application restore.
- `test_paper_sessions.py`: three synthetic configured weekday sessions (Oct 16,
  19, 20), reopen after entry, repeated callbacks, exact fee/position reconciliation,
  stable prior EOD statement hashes. Existing failure/outage/missing-EOD tests are
  separate scenarios; this is not a real-market soak or exchange-calendar proof.
- `verify_offline.py`, `test_verify_offline.py`: rejects root nonzero exits and
  unraisable errors despite a forged PASS label; validates Node counts/log presence;
  atomic evidence reservation prevents concurrent overwrites and creates the
  evidence directory on a clean extracted release.
- `../.github/workflows/offline.yml`: read-only permissions, credential-free suite,
  Python 3.10-3.14 x Windows/Ubuntu, Node 24, explicit nonsecret evidence uploads.
  Workflow is implemented, not hosted-run evidence. Official actions usage was
  reviewed: [checkout](https://github.com/actions/checkout),
  [setup-python](https://github.com/actions/setup-python),
  [setup-node](https://github.com/actions/setup-node),
  [upload-artifact](https://github.com/actions/upload-artifact).

All commands below use the application CWD. Logs are `docs/evidence/`; focused
selections overlap and are not summed into an acceptance count.

| Command (prefix `python -B -W error::ResourceWarning -m unittest`) | Exit / actual results | Evidence filename |
| --- | --- | --- |
| `test_notification_outbox test_local_api_security -v` | 1; 9 cases, 6 failure records and 6 errors; initial missing outbox/request guard | `master_operations_before.txt` |
| `test_notification_outbox test_local_api_security test_cash_workflow test_cash_lineage test_phase4_e2e -v` | 0; 51 passed, 0 failures/errors/skips | `master_operations_first_fix.txt` |
| `test_verify_offline.TestVerificationEvidence.test_failed_exit_and_unraisable_error_cannot_be_relabelled_pass -v` | 1; 1 case, 2 failed subtests; false-green gap reproduced | `master_evidence_negative_before.txt` |
| `test_notification_outbox test_verify_offline test_local_api_security -v` | 0; 17 passed, 0 failures/errors/skips | `master_operations_verified.txt` |
| `test_notification_outbox test_verify_offline test_contract_universe test_local_api_security -v` | 0; 27 passed, 0 failures/errors/skips | `master_resume_focused.txt` |
| `test_release_operations -v` | 1; 4 cases, 4 errors (missing bundle/application restore) | `master_release_before.txt` |
| `test_release_operations test_release_management -v` | 0; 18 passed, 0 failures/errors/skips | `master_release_first_fix.txt` |
| `test_cash_workflow.TestCashWorkflow.test_operations_reads_expose_retry_without_dispatch_and_health_rejects_corrupt_ledger test_cash_workflow.TestCashWorkflow.test_http_history_pages_keep_original_snapshot_scope_and_bound_queries -v` | 1; 2 failed (404) | `master_observability_before.txt` |
| `test_cash_workflow test_local_api_security test_release_operations -v` | 1; 15 cases, 1 failed, 0 errors/skips; new test used a price outside entry zone, now uses actual entry and asserts one mutated position | `master_observability_first_fix.txt` |
| `test_cash_workflow test_local_api_security test_notification_outbox test_release_operations -v` | 0; 22 passed, 0 failures/errors/skips | `master_observability_verified.txt` |
| `test_paper_sessions test_release_operations test_release_management -v` | 0; 19 passed, 0 failures/errors/skips | `master_release_sessions_verified.txt` |
| `test_release_operations -v` (expanded archive bootstrap/content tamper) | 0; 5 passed, 0 failures/errors/skips | `master_release_bundle_verified.txt` |

`node test_cash_dashboard.js` returned 0 with 10/10 passed, 0 failed/skipped:
`master_reporting_node.txt`. `python -B configuration_check.py` returned 0:
`master_final_config.txt`, LOCAL_CONFIGURATION_VALID, active Upstox, dry run true,
scheduler false; authentication/quote/candles NOT_TESTED, live_requests=false.
`git diff --check` returned 0 (Git line-ending advisories only).
The first `--stage final` run failed as recorded below; it is not acceptance proof.

### Broad-run regression and correction

`python -B -W error::ResourceWarning verify_offline.py --stage final` completed
with exit 1: 721 executed, 717 passed, 0 failure records, 7 error records, 0 skipped,
218.270s. Four unique legacy handler cases lacked actual HTTP headers/connection
context (one has four subtests). Node 10/10, syntax and compilation passed; source
before/after matched. `master_final.json` and its bound logs remain a failed run.

Focused reproduction (exit 1, 2 cases/2 errors, 0 failures/skips),
`master_full_failure_reproduction.txt`:
`python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase1D.test_p1d_http_api_contracts_validation_pagination_and_secret_redaction test_bot.TestMarketDataFreshness.test_get_and_post_scan_aliases_enforce_the_same_policy -v`.

`test_bot.py:_set_loopback_request_context` now gives the four existing synthetic
requests a real-shaped Message Host, loopback peer and server port. Content-Length
and original API/freshness/eligibility/scheduler assertions remain. The security
guard is not patched or bypassed. Actual HTTP hostile-request tests remain active.

`python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase1D.test_p1d_http_api_contracts_validation_pagination_and_secret_redaction test_bot.TestIndianFOSignalBotPhase1D.test_p1d_scheduler_startup_modes_health_visibility_and_single_thread_idempotency test_bot.TestIndianFOSignalBotPhase3B1A.test_p3b1a_strategy3_http_aliases_reject_override_fields test_bot.TestMarketDataFreshness.test_get_and_post_scan_aliases_enforce_the_same_policy test_local_api_security -v`
returned 0: 7 passed, 0 failures/errors/skips, 3.591s;
`master_request_context_verified.txt`. A new full run uses `--stage final_verified`
and completed as recorded below. Original failed evidence is not overwritten.

### Windows evidence portability correction

`python -B -W error::ResourceWarning verify_offline.py --stage final_verified`
returned 0: 721/721 passed, 0 failures/errors/skips, 200.890s; Node 10/10,
syntax exit 0, 51 files compiled, source unchanged and no unraisable errors.
However `python -B verify_offline.py --validate-evidence docs/evidence/master_final_verified.json`
returned 1 (`master_final_evidence_validation.json`): new strict required-log matching
compared Windows backslash command log paths with normalized manifest keys.
This is a validator portability defect, not an accepted end-to-end evidence result.

Reproduction:
`python -B -W error::ResourceWarning -m unittest test_verify_offline.TestVerificationEvidence.test_windows_command_log_paths_match_normalized_manifest_paths -v`
returned 1: 1 case/1 error, 0 failures/skips; `master_windows_evidence_before.txt`.
`verify_offline.py` now emits POSIX-relative command paths and normalizes old
Windows references when checking required logs. Hash/path containment checks remain.
The regression accepts a consistent mixed-separator synthetic manifest then rejects
altered Node log bytes. `python -B -W error::ResourceWarning -m unittest test_verify_offline test_release_operations -v`
returned 0: 14 passed, 0 failures/errors/skips, 5.905s;
`master_windows_evidence_verified.txt`.

`python -B -W error::ResourceWarning verify_offline.py --stage final_accepted`
completed with the accepted result below. Release candidate 001 and its build/inspect
JSON remain historical. Candidate 002 includes the evidence-path fix; build and
inspection CLI both returned 0, 56 manifested files, release SHA-256
`3cf10852e3d85f4a167d1479381a929d24aadef76fcddeddca7f24e8020a937e`;
`master_release_candidate_002.zip`, `master_release_candidate_002_build.json`,
`master_release_candidate_002_inspect.json`. Final source/archive/report binding
is checked by closeout below. Neither ZIP is a deployment authorization.

Evidence limitation: the failed `master_final.json` also glob-bound the auxiliary
`master_final_diff_check.txt`. That ancillary working-tree check was subsequently
rerun into the same filename, so its old hash reference is stale. The failed run's
actual Python/Node/syntax logs remain unchanged. Gate 2, history and intermediate
verified-run log hashes still match. No hash in the old failed manifest is rewritten
to hide this; closeout records `stale_log_references` per stage. Final acceptance uses
its fresh distinct stage with only its own three actual command logs.

## Final accepted local verification and continuation decision

Application CWD; installed Python 3.14.6 and Node 24.18.0:

| Exact command | Actual result | Artifact |
| --- | --- | --- |
| `python -B -W error::ResourceWarning verify_offline.py --stage final_accepted` | Exit 0; **722 executed/722 passed**, 0 failures/errors/skips, 267.497s; **10/10 Node passed**, 0 failed/skipped; syntax exit 0, **51 Python files compiled**, no unraisable errors, source before/after identical | `master_final_accepted.json`, bound Python/Node/syntax logs |
| `python -B verify_offline.py --validate-evidence docs/evidence/master_final_accepted.json` | Exit 0; current source, execution inventory, exact log hashes, counts and exits validate | `master_final_accepted_validation.json` |
| `python -B release_management.py bundle --output docs/evidence/master_release_candidate_002.zip` | Exit 0; 56 manifested public source/test/runbook files; exclusive destination | `master_release_candidate_002_build.json`, ZIP |
| `python -B release_management.py inspect --archive docs/evidence/master_release_candidate_002.zip` | Exit 0; manifest/content/scope verified | `master_release_candidate_002_inspect.json` |
| `python -B configuration_check.py` | Exit 0; active Upstox, dry run true, scheduler false; no live requests/receipts | `master_final_config.txt` |
| `git diff --check` | Exit 0; line-ending advisories only | Rechecked without overwriting historical auxiliary evidence |

TESTING READY: **PASS**. PRODUCTION READY: **BLOCKED**.
LIVE READ-ONLY ACCEPTANCE: **BLOCKED_EXTERNAL_DEPENDENCY: BLOCKED_PENDING_OPERATOR_AUTHORIZATION**
(not run). REAL TRADING: **NOT AUTHORIZED**.

Delta from the reproduced baseline: 675 -> 722 Python cases (+47), 6 -> 10 standalone
Node cases; not a sum of overlapping runs. The ten required connected cash cases
are accepted offline, with contract-cache/history/outbox/reporting/release recovery
extensions now tested. Whole product milestone acceptance remains 0/12 after
per-row reassessment: I=64.25/R=37.00. The production report supplies each previous
state, actual implementation/evidence, current status, unmet criterion and score
reason; no score increased from test growth or documentation alone.

Reopen/closeout command: `python -B docs/evidence/master_closeout.py`. It consumes
the actual accepted run, reopens all changed reports and stage manifests, validates
current release/source/report hashes and safety configuration, records historical
stale log references, and writes exclusive `master_closeout.json`. Its result is
separate from test execution; it cannot manufacture a passing suite.

The operator HEAD remains `bd499cdb8d312e41ef79d6a11199bbc9b6e75c6f`. Existing staged
and untracked work, including the staged/working baseline-log split and the tracked
empty unserved `public/rea`, is preserved. No commit/reset/clean/deploy occurred.
Current source/working-tree/report and artifact identity are retained by closeout.

Production blockers remain exact authorized account/market observations, authentic
dated universe/calendar/history and operating/runtime/browser/deployment evidence.
Independent source verification, actual option execution, derivative/margin/partial
scope, a real-delivery worker and authenticated nonlocal deployment/central alerting
are explicitly outstanding code/scope requirements, not renamed external failures.
Further acceptance requires zero unexplained ledger differences, observed qualified
prices/identities, rejection of changed/expired/unknown trust artifacts, preserved
no-look-ahead, and the separately agreed operating tests. Do not enable services to
demonstrate completion or treat locally generated hashes as publisher credentials.

## Phase 4A executed milestone: Publisher Trust Verifier & Evidence Qualification (PASS)

- **Execution Date / Local Time:** `2026-10-22T15:50:00+05:30` (IST)
- **Scope:** Phase 4A Publisher Trust Verifier, Effective-Date Authority, Replay Gating, and 14-Case Test Matrix.
- **Implemented Modules:**
  - `publisher_trust.py`: new fail-closed Ed25519 publisher trust verification module. Implements `TrustAnchorConfig` (local operator-controlled store; never artifact-controlled), `PublisherTrustVerifier`, canonical signed payload generation (`canonical_signed_payload`), structured `TrustVerificationResult`, and all standard reason codes (`VERIFIER_UNAVAILABLE`, `MISSING_TRUST_ANCHOR`, `INVALID_SIGNATURE`, `ARTIFACT_DIGEST_MISMATCH`, etc.).
  - `source_qualification.py`: integrated `PublisherTrustVerifier` into `assess_source_evidence(..., trust_config, verification_time)`. Sets `publisher_authenticity.status = VERIFIED` and `historical_eligibility.allowed = True` with `PUBLISHER_TRUST_VERIFIED_SOURCE_QUALIFIED` upon valid verification; fails closed otherwise.
  - `instrument_archive.py`: integrated verifier into `resolve_archives(..., trust_config, verification_time)`. Returns qualified identity with `live_historical_eligible = True` when authentic; fails closed with `HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT` otherwise.
  - `release_management.py`: added `publisher_trust.py` to `ReleasePackager.CORE_MODULES`.
  - `test_publisher_trust.py`: full 14-case test matrix covering correct signature, unknown publisher/key, dependency unavailable/fail-closed, tampering, unsupported algorithms/schemas, key validity boundaries & revocation, effective-date boundaries/naive timestamps, missing rights, conflicting artifacts & deterministic selection, archive re-hashing, scope matching, historical backtest gating, last-good archive fail-closed behavior, and safety invariants.
  - `test_bot.py`: wired `test_publisher_trust` into `load_tests`.

| Exact command | Actual result | Artifact |
| --- | --- | --- |
| `python -B -W error::ResourceWarning verify_offline.py --stage phase4a_source_trust` | Exit 0; **736 executed/736 passed**, 0 failures/errors/skips; **10/10 Node passed**; syntax exit 0, **52 Python files compiled**, no unraisable errors, source before/after identical | `master_phase4a_source_trust.json`, `master_phase4a_source_trust_python.txt`, `master_phase4a_source_trust_node.txt`, `master_phase4a_source_trust_syntax.txt` |
| `python -B verify_offline.py --validate-evidence docs/evidence/master_phase4a_source_trust.json` | Exit 0; `{"status": "PASS", "executed": 736, "scope": "OFFLINE_ONLY"}` | Evidence validated against live source snapshot and logs |

- **Retained Intermediate Result:** Initial verification run failed on release manifest test due to unregistered module; preserved per audit rules as `docs/evidence/master_phase4a_source_trust_run1_failed.*` and superseded by passing run.
- **Official Scores:** Unchanged at 64.25% implementation / 37.00% verified readiness; authentic production trust anchors and licensing evidence remain external blockers.
- **Next Task:** Strategy 3 historical option execution in `backtest_engine.py` and `strategies.py`.

## Phase 4A acceptance correction and Phase 4B implementation - 2026-10-22

Starting/current observed HEAD: `205803131d7e1a17d6b42ce976efe7dff30e475a`, branch
main. Existing working/index changes were preserved; no agent commit/reset/clean.
The earlier Phase 4A entry is historical: the source-bound 736-case artifact did
validate at entry, but genuine cryptographic acceptance was not established there.
Its actual compilation count is **53**, not the supplied summary's 52.

### Phase 4A observations, corrections and evidence

- Base `C:\Python314\python.exe` could not import cryptography (ModuleNotFoundError).
  The positive test silently patched an SHA-256 hash verifier when it was absent.
  Thus the old 736 PASS proves that test implementation ran, not real Ed25519.
- A project-local `.venv_phase4` was created. Initial sandbox ensurepip/install
  failures were retried with the required permission; official PyPI binary packages
  installed successfully. Actual test interpreter: `.venv_phase4\Scripts\python.exe`,
  Python 3.14.6, cryptography 50.0.2, cffi 2.1.1, pycparser 3.11, tzdata 2026.5.
  The first isolated test could not import Asia/Kolkata until tzdata was installed;
  `phase4a_real_crypto_before.txt` is that failed import, not a signature pass.
- `test_publisher_trust.py` now uses a public TEST-ONLY deterministic Ed25519 key
  pair with actual `sign`/`verify`. The hash-based mock class/fallback was removed;
  missing-backend behavior is independently forced and denied in case 03. Case 01
  genuinely verifies the exact bytes. `phase4ab_crypto_runtime_verified.json` also
  proves a 64-byte signature and actual InvalidSignature on changed bytes. The
  base interpreter remains distinct from the tested isolated environment.
- `source_qualification.py` reparses originals before trusting normalized records,
  checks signed artifact/schema/provider/exchange/segment/instrument scope and
  record effective coverage. `instrument_archive.py` enforces publication before
  the historical session; `storage.py` and `backtest_engine.py` pass explicit current
  operator trust/manifests through resolution. Revocation/changed bytes/future
  master publication cannot reuse a past positive result.
- `publisher_trust.py` validates publication/capture ordering and current reference
  time, records a public trust-config fingerprint, and returns structured failures
  for malformed inputs. No HMAC, handwritten crypto or unsigned fallback exists.
- Historical release failure 1: publisher_trust.py was missing from CORE_MODULES.
  Failure 2: the extracted bundle lacked that module, so unittest bootstrap loaded
  FailedTest. The user's prior registration is retained and directly reverified.
  `option_execution.py` is also a production module, never reclassified as a test.
  `requirements.txt` is bundled and source-bound; extracted bootstrap imports both
  production modules and requires real crypto. CI installs the pinned dependencies.

### Phase 4B actual implementation

- `option_execution.py`: explicit `tradepulse.option-request.v1`, exact original
  master/dataset text, strict option quote schema, exact dated OPTIDX contracts,
  per-row contract digest, observed spread/depth, prior closing OI and no-look-ahead
  Strategy 3 evaluation on known underlying prefixes. No index-as-premium fill.
- `instrument_identity.py` / `instrument_archive.py`: OPTIDX dated coverage, lot,
  tick, expiry/strike/CE-PE/underlying validation. Request aliases, conflicting keys,
  wrong dates, changed lots, duplicates and incomplete/future data fail closed.
- `backtest_engine.py`, `readiness_policy.py`, `server.py`: real execution branch,
  explicit readiness admission, actual HTTP and local CLI `--option-request`.
  Legacy flags/unbound option inputs still fail. The legacy API eligibility status
  remains compatible; its reason now asks for the explicit request, and the catalog
  correctly reports that implementation exists. Cash replay semantics are retained.
- Full-premium long positions, lot/risk/capital/daily limits, modeled tick-rounded
  entry/exit, observed opening depth and conservative target caps, ledger events,
  marks, estimated cost schedule, deterministic source/config IDs, persisted results.
  Thresholds are rounded separately: slippage applies only to fills, once per leg.
  Actual observed bid is distinct from the modeled target/fill, including in storage.
- Opening gap stops use actual bid/depth; unknown intrabar trigger liquidity or
  stop/target collision stays unresolved with stop priority. Missing exit/EOD prices
  retain reservations. No forward fill, invented settlement or unsupported partial
  execution is presented as a completed trade.
- Supported scope is NIFTY/BANKNIFTY long CE/PE, one open position, configured
  calendar, estimated costs, no overnight/short margin/exercise/partial fills.
  Original option request bytes must be retained separately; result persistence
  stores the ledger/assumptions/digests, not a durable copy of the complete dataset.
  Qualified LIVE-shaped fixture tests use ephemeral TEST-ONLY roots, never installed
  production trust. Empirical performance claims remain false.

### Executed test/fix loop

Application CWD throughout. Prefix below means
`.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning -m unittest`.
Focused selections overlap and are not summed.

| Exact selection / command | Actual result | Evidence in docs/evidence |
| --- | --- | --- |
| `test_publisher_trust test_release_operations test_release_management -v` | Exit 0; 33 passed, 0 failures/errors/skips, 6.012s | `phase4a_real_crypto_focused.txt` |
| `test_phase4_acceptance -v` | Exit 1; 4 cases, 4 failure records and 1 error; scope/dates/rehash/caller-path defects reproduced | `phase4a_integration_before.txt` |
| `test_publisher_trust test_phase4_acceptance -v` | Exit 0; 18 passed, 0 failures/errors/skips | `phase4a_integration_first_fix.txt` |
| `test_option_execution -v` | Exit 1; 12 cases, 4 errors: new trades lacked existing metric/persistence aliases | `phase4b_option_first_run.txt` |
| `test_option_execution test_phase4_acceptance test_publisher_trust -v` | Exit 1; 30 cases, 1 error: test subtraction emitted an off-tick decimal; fixture arithmetic corrected, tick validation retained | `phase4b_option_first_fix.txt` |
| `test_option_execution test_phase4_acceptance test_publisher_trust test_release_operations test_release_management test_bot.TestIndianFOSignalBotPhase3B1A test_phase5a_provenance -v` | Exit 0; 75 passed, 0 failures/errors/skips, 22.765s | `phase4b_option_integrated.txt` |
| `test_option_execution test_phase4_acceptance test_publisher_trust test_verify_offline test_release_operations -v` | First exit 1: 50 cases/2 errors (bearish fixture not meeting VWAP rule; dated resolver lacked OPTIDX); second exit 1: 50 cases/1 error (missing math import); third exit 0: 50 passed | `phase4b_option_expanded.txt`, `phase4b_option_expanded_verified.txt`, `phase4b_option_expanded_verified2.txt` |
| Canonical `verify_offline.py --stage phase4b_option_final` | Exit 1; 758 executed, 757 passed, 1 failure, 0 errors/skips, 266.169s; old API status changed unnecessarily | `master_phase4b_option_final.json` and bound logs |
| `test_bot.TestIndianFOSignalBotPhase3B.test_p3b_12_sqlite_persistence_http_api_routes_resource_warnings_and_security -v` | Exit 1; 1 failed; reproduced compatibility issue. Original assertion preserved; status restored | `phase4b_legacy_listing_before.txt` |
| `test_option_execution.TestOptionExecution.test_real_strategy_next_option_open_then_target_and_persistence_are_deterministic -v` | Exit 1; 1 failed; modeled target reference labeled as actual bid. Observed quote/model fields separated and regression retained | `phase4b_observed_bid_label_before.txt` |
| `test_option_execution test_phase4_acceptance test_publisher_trust test_release_operations test_release_management test_verify_offline test_bot.TestIndianFOSignalBotPhase3B.test_p3b_12_sqlite_persistence_http_api_routes_resource_warnings_and_security -v` | Two distinct runs exit 0; 65 passed, 0 failures/errors/skips; second adds exact threshold/slippage checks | `phase4ab_pre_final_verified.txt`, `phase4ab_pre_final_verified2.txt` |
| `test_phase4_acceptance test_option_execution test_publisher_trust -v` | Exit 0; 36 passed, 0 failures/errors/skips; signed schema/scope checks | `phase4ab_source_scope_final.txt` |
| Canonical `verify_offline.py --stage phase4ab_accepted`, then its `--validate-evidence` | Both exit 0; 758/758, 0 failures/errors/skips, 254.037s; Node 10/10, 56 compiled, no unraisable errors/source changes. Historical after the subsequent OI correction | `master_phase4ab_accepted.json`, `phase4ab_evidence_validation.json` |
| `test_option_execution.TestOptionExecution.test_bad_oi_baseline_or_changed_previous_close_is_rejected -v` | Exit 1; 1 failed: legacy validator rounded fractional OI change. Enforced exact integer difference | `phase4b_fractional_oi_before.txt` |
| `test_option_execution test_phase4_acceptance test_publisher_trust -v` | Exit 0; 36 passed, 0 failures/errors/skips, 1.366s | `phase4ab_fractional_oi_verified.txt` |

`docs/evidence/phase4b_cli_verify.py` ran the actual CLI, exit 0: one synthetic
completed trade, actual bid 30, modeled exit 27.0, reconciled ledger; temporary
request and in-memory database only (`phase4b_cli_verified.json`).
The early shell-only runtime probe had a quoting SyntaxError; its empty
`phase4ab_crypto_runtime.json` stdout is not accepted evidence. The standalone
runtime verifier and `phase4ab_crypto_runtime_verified.json` supersede it.

Actual configuration initially still selected Upstox; only its existing
ACTIVE_BROKER assignment was changed to explicitly requested paper_sim. Local
preflight exit 0 confirms dry-run true, scheduler false, no live requests/receipts:
`phase4ab_safe_configuration_verified.json`. No credentials were printed/changed.
PyPI dependency downloads are distinct from the unauthorized broker/data downloads;
no broker, token refresh, Telegram send, scheduler activation or real order occurred.

Final frozen-source command: `.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase4ab_verified`.
Result/validation and release identity follow.

### Phase 4A/4B final acceptance

| Exact command (application CWD) | Executed result | Evidence |
| --- | --- | --- |
| `.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase4ab_verified` | Exit 0; **758 executed/758 passed**, 0 failures/errors/skips, **265.931s**; Node **10/10**, syntax exit 0, **56 Python files compiled**, no unraisable errors; source before/after identical | `master_phase4ab_verified.json` and bound Python/Node/syntax logs |
| `.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_phase4ab_verified.json` | Exit 0; current source, requirements and all three exact command-log hashes agree | `phase4ab_final_validation.json` |
| `.venv_phase4\Scripts\python.exe -B release_management.py bundle --output docs/evidence/phase4ab_release_final.zip` | Exit 0; 62 manifested public code/test/template/runbook/dependency files | `phase4ab_release_final_build.json` |
| `.venv_phase4\Scripts\python.exe -B release_management.py inspect --archive docs/evidence/phase4ab_release_final.zip` | Exit 0; exact scope/content/manifest validation | `phase4ab_release_final_inspect.json` |
| `.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/phase4b_cli_verify.py` | Exit 0; actual CLI, 1 synthetic long-option trade; observed bid 30/model exit 27.0, ledger OK | `phase4b_cli_verified.json` |
| `.venv_phase4\Scripts\python.exe -B docs/evidence/phase4ab_runtime_verify.py` | Exit 0; real 64-byte Ed25519 verification, changed bytes rejected; paper_sim/dry-run/scheduler safe | `phase4ab_crypto_runtime_verified.json` |

Release SHA-256: `bc3f3cfc370c5e702dfcb565313f35006419d938469e66593b97910d92db7eff`.
The earlier `phase4ab_release_001.zip` remains historical after the runbook update;
the final archive is the one above. Both historical failed/full runs and all focused
corrections remain retained; no old failure was overwritten with a passing label.
`phase4ab_closeout.py` consumes this source-bound result and records report/archive/
runtime/worktree identity in exclusive `phase4ab_closeout.json`.

**Phase 4A: PASS - OFFLINE ENGINEERING. Phase 4B: PASS - BOUNDED OPTION MECHANICS.**
**TESTING READY: PASS. PRODUCTION READY: BLOCKED. REAL HISTORICAL OPTION STUDY:
NOT ACCEPTED. LIVE READ-ONLY ACCEPTANCE: BLOCKED_PENDING_OPERATOR_AUTHORIZATION.
REAL TRADING: NOT AUTHORIZED.**

The delta is 736 -> 758 executed cases (+22: four new trust-path cases and eighteen
option-engine cases). Existing fourteen trust cases now use genuine crypto.
The earlier 736 artifact compiled 53 files; final compilation is 56, with the three
new Python files. Counts are not summed across overlapping focused selections.
No current regression failure, stale final-source binding or stale final log hash
remains. Old artifacts remain historical; the empty failed shell-probe stdout is
explicitly not a proof artifact.

Official scores remain **64.25 implementation / 37.00 readiness; 0/12 whole
milestones accepted**. M04 gains a genuine verifier and integrated replay gate;
M08 gains bounded exact-option execution. Neither accepts real licensed inputs,
general derivative/margin/partial execution, calibrated studies or operation.
These narrower engineering gates do not cross a whole-row threshold.

No real publisher trust roots were installed; public test seeds exist only in tests.
No private broker requests/data downloads, token refresh, Telegram sends, production
scheduler activation, real orders or deployment occurred. Only software dependencies
were downloaded from official PyPI. The current safety selection is paper_sim,
telegram_dry_run=true, enable_background_scheduler=false. HEAD remains
`205803131d7e1a17d6b42ce976efe7dff30e475a`; existing user changes are preserved.
