# TradePulse AI testing readiness

Active execution authority: [execution ledger](../TRADEPULSE_EXECUTION_LEDGER.md).
This report covers actual local testing; it grants no live-data or trading acceptance.

## Baseline and current gate

**TESTING READY: PASS for the current source.** Final command
`.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase4ab_verified`
returned **0**: **758/758 Python cases passed**, **0 failures/errors/skips**,
265.931s; **10/10 standalone Node renderer cases passed**, 0 failed/skipped,
syntax exit 0 and **56 root Python files compiled**. No unraisable errors occurred;
source before/after matched. `master_phase4ab_verified.json` binds actual ordered
execution IDs, commands/exits, source and log hashes. The follow-up command
`.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_phase4ab_verified.json`
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

## Phase 4A/4B acceptance - 2026-10-22

Current HEAD: `205803131d7e1a17d6b42ce976efe7dff30e475a`; prior counts/HEADs above
are historical. The supplied 736-case evidence genuinely matched source at entry,
but its signature test used a hash mock when the base interpreter lacked crypto.
Actual artifact compilation was 53, correcting the reported 52. The old release
failure lacked publisher_trust.py in CORE_MODULES and consequently in the extracted
bootstrap; the registration is retained and passes. No production module/test was
removed or reclassified.

The tested interpreter is the project-local Python 3.14.6 environment with pinned
cryptography 50.0.2/cffi 2.1.1/pycparser 3.11/tzdata 2026.5. Case 01 now uses real
Ed25519 signing and verification under a public test-only key. Case 03 independently
forces unavailable-backend denial. A direct runtime check also verifies a 64-byte
signature and rejects changed bytes. No mock fallback or skipped crypto positive
test remains. The base interpreter is a different environment; an earlier PyPI
timeout does not describe this installed test backend.

Four new integration cases exercise signed scope/effective coverage, reparse of
original bytes, the actual store/readiness/cash replay path, current revocation and
future-publication rejection. Eighteen option tests cover exact contracts, next-open
chronology/no look-ahead, CE/PE selection, real bid/ask/depth, ticks/slippage/estimated
charges, capital/lot/risk, malformed/missing/gapped data, OI baseline integrity,
offsets, expiry/EOD, unresolved collision/exit liquidity, repeat/persistence, actual
HTTP, and genuine-signature LIVE-shaped fixtures. Fixture roots are never installed
as production roots or real licensed-data evidence. Cash tests remain in the full
suite; the legacy API status assertion remains unchanged and now passes.

The actual local CLI also passed using a temporary synthetic request and memory
database (`phase4b_cli_verified.json`): one modeled trade, actual bid 30 separately
recorded from modeled exit 27.0, ledger reconciled. Extracted release bootstrap
imports both production modules and requires real crypto. requirements.txt is now
in the source binding and release; a changed dependency declaration invalidates
old proof. Final log binding includes exactly the three commands, not globbed
unrelated auxiliary files.

The ledger retains all exact commands/exits and failed intermediates. Significant
results: 33 real-crypto/release cases passed; source-path red run then 18 passed;
75 affected cash/option/release cases passed; expanded 50 passed after fixes; 65
final affected cases passed; final 36 source/option/crypto cases passed. These overlap
and are not added. The first 758-case full run had 757 passed/one legacy metadata
failure; compatibility was restored in code. A later passing run was superseded
after a fractional-OI rounding defect was reproduced/fixed. The final 758/758
execution and current-source evidence validation above both pass.

Phase 4A and bounded Phase 4B offline engineering PASS. Real historical option
study/production remain unaccepted: authentic licensed signed inputs, actual
publisher roots, cost/calendar/data/operating acceptance are missing. Supported
mechanics and limits are specified in the runbook; no partial/short-margin,
overnight, invented settlement or missing-liquidity fill is claimed. Keep the
original option request separately; this V1 stores results/digests rather than a
durable complete option-input archive. Current safety is paper_sim/dry-run true/
scheduler false. No live broker request, order or Telegram delivery was made.
