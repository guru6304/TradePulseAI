# TradePulse AI testing readiness

Active execution authority: [execution ledger](../TRADEPULSE_EXECUTION_LEDGER.md).
This report covers actual local testing; it grants no live-data or trading acceptance.

## Baseline and current gate

**TESTING READY: PASS for the current source.** Final command
`python -B -W error::ResourceWarning verify_offline.py --stage final_accepted`
returned **0**: **722/722 Python cases passed**, **0 failures/errors/skips**,
267.497s; **10/10 standalone Node renderer cases passed**, 0 failed/skipped,
syntax exit 0 and **51 root Python files compiled**. No unraisable errors occurred;
source before/after matched. `master_final_accepted.json` binds actual ordered
execution IDs, commands/exits, source and log hashes. The follow-up command
`python -B verify_offline.py --validate-evidence docs/evidence/master_final_accepted.json`
returned **0**, validating this exact current source and its logs. There are no
unresolved current regression failures; retained intermediate failures are below.

Gate 0 PASS: starting branch main/HEAD 60834dd, preserved dirty Task 4 tree.
Operator continuation HEAD is bd499cdb8d312e41ef79d6a11199bbc9b6e75c6f;
existing staged/working/untracked changes remain preserved.
Fresh strict baseline: 675 Python passed (exit 0, no failures/errors/skips), six
renderer cases passed, 39 Python files compiled, local safe configuration valid.
Logs and exact commands are recorded in the ledger and `docs/evidence/master_phase0*`.

The apparent 674/675 inconsistency was an intermediate versus later final run:
`task4_full_offline_suite_final.txt` has 674, `task4_regression_verified.txt` has 675,
including the final overlap case. Current execution independently confirms 675.
Historical validator counts are not reused as current execution results.

Gate 1/2: **PASS** for the recorded source version. The complete execution-bound
run `python -B -W error::ResourceWarning verify_offline.py --stage gate2` returned 0:
**686/686 Python cases passed**, 0 failures/errors/skips, 122.560s; **8/8 Node cases
passed**, syntax exit 0, **42 root Python files compiled**. Evidence is
`docs/evidence/master_gate2.json` and its bound logs. The evidence validator returned
0 before continuing to Phase 3; that intermediate version is superseded by the
final accepted run above.
Focused integration also passed: 42 related cash/lineage/E2E cases and 25 overlapping
verification/workflow/release cases. Counts overlap. Initial red results and fixes
are retained in the ledger.

## Actual connected path

The offline workflow tests use the existing real provider adapter with intercepted
HTTP and explicitly synthetic observations, existing shared validators, SQLite
accepted-input transaction, existing scanner/evaluators/ranking/sizing, committed
signal/result links, optional explicitly attached forward paper account, actual
localhost HTTP API, and the actual inline dashboard JavaScript through Node DOM
doubles. The renderer is supplied the actual HTTP response from that workflow,
not a separately invented recommendation. This is not visual browser acceptance.

New read-only `/api/scan-lineage?run_id=...` and
`/api/cash-candles?run_id=...&batch_id=...&limit=...&offset=...` expose reconciled
source locators and completed-only input. Existing `/api/signals` adds immutable
source/run/code/config binding, paper decision/reason and `actionable=false`.
No stored candidate authorizes real execution. Legacy unretained records explicitly
say NOT_RETAINED. An inconsistent archived candidate produces 503 instead of levels.

The POST scan handler passes an explicitly injected paper portfolio when present;
default deployments create no account or financial side effect on GET. Tests attach
one by the handler's existing runtime dependency injection pattern. Operator test
startup/teardown is automated by the verification command; localhost servers and
temporary databases are closed at the end.

## Repeatable operator verification

From `indian_fo_signal_bot_v1`, with Python and Node installed:

```powershell
python -B -W error::ResourceWarning verify_offline.py --stage operator_run_001
$LASTEXITCODE
python -B verify_offline.py --validate-evidence docs/evidence/master_operator_run_001.json
$LASTEXITCODE
```

Choose a new stage identifier for each run; existing evidence is not overwritten.
The runner loads the established `test_bot.load_tests` suite, records actual ordered
case IDs, exits nonzero on failure/error/skip/missing/duplicate/zero cases, executes
Node renderer/syntax and compilation, binds source/log hashes, and blocks outbound
sockets except loopback test servers. Historical evidence fails current-source
validation after an implementation change. It never reads or refreshes broker
credentials to run the tests. Local `configuration_check.py` is separately available
and was run here; it proves configuration only.

Fast cash path (includes actual HTTP and dashboard response rendering):

```powershell
python -B -W error::ResourceWarning -m unittest test_cash_workflow -v
```

## Coverage and outstanding evidence

All ten required cash-path scenarios have focused execution: deterministic valid
candidate/paper fill; stale/incomplete/invalid rejection; gaps/order/duplicates;
idempotent repeated input; provider failure without fallback; transactional storage
rollback; restart/offline resume; actual paper risk rejection; matching API/renderer
timestamps/provenance/levels; distinct empty and error states. The full strict suite
also passed. Fixture labels are explicit even when a synthetic
fixture exercises the strict LIVE-shaped validation branch. Live acceptance and
production readiness remain separate gates and are not inferred from these tests.

## Post-gate implementation and regression history

Further code implements native contract-cache inspection, resumable ordered history,
durable local notification previews, local-origin HTTP protection, operational
paper/EOD/research/outbox reporting, three-session paper qualification and release
packaging/application restore. Every new test is included by `test_bot.load_tests`.
The existing truncated-history test still fails closed through the new snapshot
reader; the old CORS assertion intentionally requires no wildcard Origin header.

The first broader run (`master_final.json`) executed 721 cases: 717 passed, four
unique cases raised seven error records, zero failures/skips. Those older in-memory
handler fixtures omitted headers/connection context required by the new security
guard. They now supply complete local HTTP context and retain all original API,
freshness, eligibility and scheduler assertions. Real HTTP security coverage stays
active. The seven-case corrected selection passed; no guard is mocked away.

The next run (`master_final_verified.json`) passed 721/721, Node 10/10 and 51-file
compilation, but its final evidence validation failed on mixed Windows log separators.
The portability regression reproduced that failure, then passed with log-path
normalization while still rejecting changed log bytes. Fourteen focused verifier
and release cases passed. This passing execution is retained as intermediate
evidence, not a substitute for the final corrected source verification.

Exact commands/exits/logs, red results and their corrections are retained in the
[ledger](../TRADEPULSE_EXECUTION_LEDGER.md). Counts of overlapping selections and
the conditional actual-HTTP Node bridge are not added to the full suite count.
One ancillary diff-check log captured by the failed `master_final.json` was reused
for a subsequent working-tree check; that old supplemental hash is stale. Its
actual test logs remain intact. The ledger and closeout manifest disclose this;
the failed stage is not used as current acceptance evidence.
