# Phase 4 closure and current-source review - 2026-10-24

**Final engineering verdict: `PHASE_4_IMPLEMENTATION_ACCEPTED`.** All eleven
Phase 4 software gates pass against the frozen final source. The final canonical
run passes 1,019 Python tests, 22 Node tests, JavaScript syntax and 80 compiled
Python files. Current-source/log validation, the 13-check actual Chrome run and
inspection of the new 111-file public release also pass. Acceptance follows the
implemented production paths and requirement-specific tests below; totals alone
are not its basis.

The scope is Phase 4 scanner and explainable-recommendation engineering, followed
by compatibility with the separate Phase 5 context overlay. No genuine market
observation, live recommendation, historical-study approval, empirical return,
publisher-rights acceptance or complete F&O execution acceptance is established.
The original six phases and milestone rubric remain unchanged.

## Starting state and authority

The supplied Phase 4 gap-closure and Phase 5 implementation mission authorizes
correction of demonstrated software gaps while preserving existing formulas,
interfaces, configuration, databases and old evidence. The initial
[requirements and shared-contract matrix](phase45_shared_contracts_and_requirements_20261023_01.md)
was recorded before production assignments. It connects the mission's P4-A through
P4-K gates to actual code, consumers, positive and negative evidence, initial states
and owners. The fixed completion roadmap, capability matrix, market-data matrix
and strategy/risk audit remain the preserved authority for existing behavior.

The application is `indian_fo_signal_bot_v1` under the supplied workspace.
The [starting baseline](../evidence/phase45_baseline_20261023_01.json) records clean
HEAD `f56927389f07b6cca52abebc6e9d22debd0a50d4`, 77 source files, 407 retained
documents/evidence files and hashes of both `.env` files. It validated the actual
starting source against the retained 924-Python/14-Node/72-compilation proof and
the existing 102-file Phase 4 archive. That archive's SHA-256 is
`4e32d72553ab7b3572ffc115ca845f15e65971181958fc87e6bd02f5c0829aa2`.
Those totals establish the starting baseline only.

Operational database, WAL and SHM contents were not opened, migrated, reset or
hashed. Existing receipts and the earlier accepted Phase 4 report remain
historical records. New failed receipts are also retained rather than rewritten.

## Actual scanner contract and strategy coverage

The existing path remains adapter observations, canonical identity and completed
candle qualification, existing evaluators, scanner sizing and geometry,
deterministic ranking, transactional cash/evaluation persistence, existing APIs,
dashboard and dry-run outbox. Provider selection remains distinct from paper
execution. A feed failure cannot silently substitute another provider, REST,
simulation or fabricated history.

All five existing evaluators retain their signatures, formulas and thresholds.
The detailed wrapper records predicates actually visited during the original
short-circuit evaluation; it does not invent later failed rules. All use completed
five-minute input:

| Evaluator | Required history and preserved input/rule contract | Verification locators |
|---|---|---|
| Order Block / BOS / FVG | 30 bars; existing structural origin, BOS/FVG or displacement, first retest and mitigation/invalidation rules | `test_phase4_explanations.TestPhase4StrategyExplanations.test_all_five_bidirectional_actual_signals_match_direct_evaluation`; actual wire-adapter path in `test_phase4_e2e.py` |
| VWAP Pullback | 35 bars; session opening coverage, existing VWAP/EMA/RSI/volume and directional confirmation rules | `test_phase4_recommendations.py::test_existing_vwap_and_orb_fixtures_are_explained_through_actual_scanner`; partial-session negative cases |
| ORB | 30 bars and exact 09:15/09:20/09:25 opening range; existing breakout/VWAP/RSI/RVOL rules | `test_phase4_strategy.py` opening-range positives and each missing/incomplete opening-bar negative |
| Supertrend Pullback | 200 bars; existing Supertrend(10,3), EMA200, full-session VWAP and directional/RVOL/time rules | `test_phase4_explanations.py::test_all_five_warmup_below_and_exact_boundary`; actual scanner and raw-packet diagnostics described below |
| Option Apex OI Shift | Completed underlying prefix, session VWAP, validated option identity/lot, aligned chain/premium/PCR/OI inputs | `test_phase4_explanations.py::test_option_chain_missing_and_invalid_fail_without_invented_oi`; existing option identity/execution tests |

Direct bidirectional strategy fixtures establish software rule behavior. Actual
cash scanner fixtures exercise Order Block, VWAP, ORB and Supertrend. Option and
index fixtures retain their distinct contracts; a cash symbol or spot quote does
not establish a dated executable F&O contract. Live option/futures support is not
expanded by this mission.

`DETECTED`, `REJECTED` and `UNAVAILABLE` strategy states remain distinct from
candidate `QUALIFIED`/`REJECTED`. A detected setup rejected by sizing or numeric
geometry retains its original detection, downstream reason and null rank.
Insufficient warm-up and absent session inputs do not become ordinary setup
failures. Valid qualified input with no candidate remains `COMPLETED_EMPTY`.

## Demonstrated gaps and dispositions

| Gap or integration failure | Actual disposition and evidence | Remaining limit |
|---|---|---|
| Direct public ranker could admit a derived infinite target RR | `strategies.rank_signal_candidates` now rejects nonfinite derived T1/T2 ratios before returning a candidate. `test_phase45_scanner_gaps.py::test_ranker_rejects_derived_infinite_ratio_before_returning_candidate` covers the direct entry point; prior scanner geometry rejection stays intact. | No strategy parameter or ranking policy changed. |
| A genuine observed opening-volume baseline was not usable | `AngelLiveFeed._aggregate` retains only an actually raw-persisted same-day SNAP observation within 30 seconds before configured open. The first in-session delta still must satisfy chronology, gap and observed-quantity checks. | Without that packet, opening coverage stays unavailable. A zero baseline is never invented. |
| Buffer claim lacked true eviction and full opening-coverage evidence | New tests drive 301 completed five-minute bars through the actual ring, assert bounded 300 retention and current-session open, and reject gaps/invalid tails. A raw packet diagnostic reaches the actual Supertrend evaluator with 201 bars and observed opening lineage. | Authored packets remain fixtures and the LIVE acceptance gate still rejects their authority. |
| Context-qualified outbox validation recursed through full cash-result loading | The independent integration execution reproduced the cycle. `context_workflow._phase4` now validates direct committed result/evaluation bindings without loading the complete cash result and recursively re-entering the context outbox. | Cross-table checks are preserved; recursive full-result loading is not a trust requirement. |
| Optional context failures could leak actual SQLite exceptions | Engine context attachment and new API handlers catch real SQLite storage failures. Trigger-based tests show the original Phase 4 result remains committed while context reports unavailable; failed import returns 503 and leaves no ingestion. | This is failure isolation, not acceptance of corrupt context. |
| New context foreign keys invalidated an old privileged-corruption fixture | The fixture first retains its foreign-key rejection assertion, then explicitly removes the new dependent context rows before corrupting the parent. The original fail-closed reconciliation assertion remains unchanged. | No production foreign key was weakened. |
| Concurrent dashboard read latency exceeded the existing three-second budget | First canonical and focused repair receipts reproduce the failure. Shared read-scoped validation caches now reuse the same validated evaluation, snapshot and source components inside a locked SQLite read. The unchanged memory/file-store concurrent test passes in the 55-case repair and 59-case corruption/compatibility stages. | No cached verdict survives the read/request; the three-second budget and integrity checks remain unchanged. |
| Persisted SQLite types/sizes could escape graceful failures or be decoded before bounds checks | Independent review identified privileged stored BLOB/integer/oversize and receipt/import-inventory paths. Reproductions retained failures before repair. New guards reject invalid stored types and bound raw bytes/outbox/receipts to 256 KiB and normalized source/mapping/snapshot JSON to 4 MiB before decoding; import inventory is source-revalidated before counting records. | Seven canonical stored-payload regressions plus the full 87-case affected integration stage pass. No operational database was used. |

The source-backed baseline gap is narrower than reconnect restoration. Existing
reconnect/restart behavior intentionally clears volatile feed history. It does not
reconstruct a LIVE cache from saved rows without a separately qualified retention
policy. Tests assert honest unavailability after reconnect, session grace and
heartbeat behavior, continuity across eligible session boundaries, and rejection
of sequence reset, stale/previous-day/QUOTE baseline, unresolved quantity,
opening gap and out-of-order observations.

The existing 300 five-minute/750 one-minute capacities and 200-bar Supertrend
minimum are unchanged. A 199-bar prefix is insufficient. An exact 200-bar fixture
can pass that count and still fail session-VWAP coverage. The new 201-bar diagnostic
establishes that enough completed bars plus the observed opening baseline reach
the actual evaluator; it does not prove that an actual market session supplied
them. `test_phase45_scanner_gaps.py` and `test_phase4_feed_history.py` keep those
claims separate.

## Requirements-to-code-to-test disposition

The initial matrix remains preserved. The table below records the final offline
software disposition. The final canonical receipt binds the executed test IDs,
logs and exact source. Genuine market/provider/rights dependencies remain separate
from these software gates.

| Gate and actual implementation/consumer | Positive and negative executed-path coverage | Current state |
|---|---|---|
| P4-A: existing evaluators -> detailed traces -> scanner | All five direct bidirectional and warm-up boundaries; actual cash scanner strategies; missing chain/session/input cases | `IMPLEMENTED_AND_VERIFIED` |
| P4-B: `AngelLiveFeed` aggregation/history -> scanner | True 301/300 eviction, raw 201-bar ST path, 199/200 boundaries, gaps, invalid tail, reconnect and no invented baseline | `IMPLEMENTED_AND_VERIFIED` |
| P4-C: canonical candle/identity policy -> evaluators | Wrong identity/token/exchange, stale/future/naive/out-of-session, forming-only, gaps, invalid OHLCV; post-acquisition disconnect/quality revocation | `IMPLEMENTED_AND_VERIFIED` |
| P4-D: strategy traces plus scanner gates -> retained candidates | Detected downstream rejection, insufficient history, missing opening coverage and valid empty scan | `IMPLEMENTED_AND_VERIFIED` |
| P4-E: actual visited checks/source references -> API/UI | Direct/wrapped evaluator parity, single-call override, actual source/scan/batch linkage, legacy unavailable states | `IMPLEMENTED_AND_VERIFIED` |
| P4-F: numeric geometry/sizing -> candidate risk | Actual-level gross RR, long/short/long-put geometry, zero/nonfinite/overflow rejection, whole-unit/lot conventions | `IMPLEMENTED_AND_VERIFIED` |
| P4-G: existing ranker -> deterministic ordered candidates | Permutations/repeated ties and direct ratio overflow; rejected high-score setup remains unranked | `IMPLEMENTED_AND_VERIFIED` |
| P4-H: `scan_evaluations`, cash result, context overlay -> existing history routes | Rollback, replay, duplicate, missing parent, source binding and recomputed-checksum corruption; actual SQLite optional-failure tests | `IMPLEMENTED_AND_VERIFIED` |
| P4-I: existing inline dashboard -> current/history/explanation cards | 22 Node tests and final-source Chrome stage 04; escaping, lineage, rejected/missing/stale/failure states | `IMPLEMENTED_AND_VERIFIED` |
| P4-J: existing interfaces/security -> concurrent application reads | No external actions; old/new API semantics and corruption checks preserved; unchanged concurrency test passes in focused and final full runs | `IMPLEMENTED_AND_VERIFIED` |
| P4-K: canonical verifier and packager -> source-bound release evidence | Final 1,019-case canonical pass, current-source/log validator, final browser run and exact 111-file release inspection | `IMPLEMENTED_AND_VERIFIED` |

Numeric gross RR uses actual entry-to-stop and target distances, not nominal
display strings. The message formatter now presents those supported numeric values
and labels legacy nominal ratios. Net target RR remains unavailable: the existing
stop-exit charge model does not supply supported target-exit spread/slippage,
depth or fill evidence. Quality aliases and benchmark strings remain unvalidated
as empirical probabilities or performance. No return objective is promised.

`scan_evaluations` remains additive and bound to the separately committed result,
candidate identities and source batches. Rehashing an inconsistent explanation
does not make it valid. Context snapshots and alert decisions are separate
immutable overlays: `test_phase45_integration.py` checks equality of original
strategy/candidate/signal arrays before and after enrichment and persistence.

## Independent QA and observed execution

The actual parallel strategy/feed worker subsequently owned only the new
`test_phase45_integration.py` for independent integration review. Its
[independent QA report](phase45_independent_integration_qa_20261023_01.md) records
15 passing production-path cases and the reproduced recursive-validation defect,
with limits of the authored memory-store fixtures. The coordinator and relevant
production owner repaired the cycle; the reviewer did not edit those fixes.

The retained
[135-case integrated receipt](../evidence/phase45_alerts_integrated_final_01.json)
and [28-case SQLite/alert/integration receipt](../evidence/phase45_alerts_sqlite_after_01.json)
record successful focused executions, exit 0. They are intermediate source-bound
stages, not final-source replacement proof.

The [first canonical receipt](../evidence/master_phase45_20261024_01.json)
records 1,010 executed Python tests: 1,007 passed, one failure and two errors,
exit 1. The failure is the concurrent dashboard budget. The errors were the old
privileged-deletion fixture encountering the new context foreign key and a Windows
TCP reset in an early-rejection HTTP fixture that unnecessarily sent an unread
body. Their fixture corrections preserve the original assertions. The
[focused repair receipt](../evidence/phase45_alerts_repair_verification_01.json)
records 12 executed, 11 passed, one latency failure and zero errors. That remains
historical failure evidence. After read-scoped validation reuse, the unchanged
concurrency case and 54 affected cases
[passed together](../evidence/phase45_alerts_repair_verification_03.json), exit 0.
No latency budget or corruption assertion was weakened.

The [second canonical run](../evidence/master_phase45_20261024_02.json) then passed
1,012/1,012 Python tests, 22/22 Node tests, JavaScript syntax and 80 compiled Python
files, exit 0; failures/errors/skips/expected failures/unexpected successes and
unraisable exceptions are zero. It ran from `2026-10-24T03:45:27.141343+00:00`
through `2026-10-24T03:49:18.417566+00:00`. This is a genuine intermediate full run,
not the proof for subsequent source hardening.

An independent cache/security review by `/root/phase45_perf_review` subsequently
identified actual stored-payload boundaries requiring stronger guards. The
[first reproduction](../evidence/phase45_alerts_corrupt_payload_before_01.json)
executed five cases with zero passes, eight failed subtests and two errors. The
[follow-up reproduction](../evidence/phase45_alerts_corrupt_followup_before_01.json)
executed seven cases with five passes and three failed subtests. Test-case counts
and subtest failures are distinct. Production guards now reject incorrect SQLite
types and excessive payloads before decoding or coercion, including receipts and
the existing import inventory. The unchanged concurrent budget also passes in the
[59-case affected stage](../evidence/phase45_alerts_corrupt_payload_after_01.json).
After all seven stored-payload regressions were registered canonically, the
[87-case final affected stage](../evidence/phase45_alerts_corrupt_followup_after_01.json)
passed, exit 0. These source changes require the fresh final canonical stage below.

Actual Chrome 155 [stage 03](../evidence/phase45_browser_20261024_03.json)
passed 13 DOM/API/security checks, exit 0. It executed unchanged inline renderer
implementations against the actual local application APIs and authored fixture
inputs. CDN/CSS dependencies were omitted and chart drawing stubbed; there is no
full visual or cross-browser acceptance claim. The retained stage predates the
latest backend repairs. The final-source
[stage 04](../evidence/phase45_browser_20261024_04.json) repeated all 13 checks
successfully, exit 0, with source unchanged throughout. Chrome exited successfully,
the application server thread stopped and its disposable browser profile was
removed. External requests were blocked before transport.

Canonical command and final evidence target:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase45_20261024_03
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --validate-evidence docs/evidence/master_phase45_20261024_03.json
```

The [final canonical receipt](../evidence/master_phase45_20261024_03.json)
records **1,019/1,019 Python tests**, **22/22 Node tests**, **80 compiled Python
files** and JavaScript syntax, all exit 0. Python failures, errors, skips,
expected failures, unexpected successes and unraisable exceptions are zero.
ResourceWarnings were treated as errors. Execution ran from
`2026-10-24T03:53:41.298185+00:00` through
`2026-10-24T03:57:38.152583+00:00`. All 85 source paths match the before/after
snapshot. The separate `--validate-evidence` invocation also completed exit 0
against current source and exact retained logs.

The receipt retains every expected, executed and passed Python test ID through
the canonical `unittest.TextTestRunner(test_bot.load_tests)` path. New suites are
`test_phase45_scanner_gaps`, `test_context_data`, `test_context_workflow`,
`test_context_alerts`, `test_phase45_integration` and `test_context_http`; the
unchanged legacy suites also ran. Exact output is retained in the
[Python log](../evidence/master_phase45_20261024_03_python.txt),
[Node log](../evidence/master_phase45_20261024_03_node.txt) and
[syntax log](../evidence/master_phase45_20261024_03_syntax.txt).

The new [public release](../evidence/phase45_release_20261024_01.zip) is built and
[independently inspected](../evidence/phase45_release_inspect_20261024_01.json),
exit 0. It contains 111 manifest-listed public files. SHA-256:
`6646949db0219f8921700b2cf4aae0d51667538491e1f9e06f01294f32517d1e`.
Inspection checks manifest bytes, archive paths, exact current file content,
sizes/hashes and exclusions. A private exact credential comparison passes without
exposing values; one same-key exact `.env.example` template placeholder is
excluded from that comparison. `.env`, databases/WAL/SHM, `.local`, machine evidence
and private source/policy captures are excluded. Archive integrity does not imply
publisher authentication.

Machine-evidence locations are the
[final requirement matrix](../evidence/phase45_acceptance_20261024_01.json),
[closeout](../evidence/phase45_closeout_20261024_01.json) and
[separate sealing validation](../evidence/phase45_closeout_validation_20261024_01.json).
Those sealing outputs bind the completed report files; their own recorded
execution statuses and hashes are authoritative for the sealed handover.

## Remaining blockers and preserved boundaries

| Required blocker category | Current disposition, owner and evidence needed |
|---|---|
| 1. Confirmed software defects remaining | None identified in the reviewed in-scope scanner/context paths. Latency, numeric overflow, integration recursion and stored-payload failures have corrected source and passing final canonical regressions. |
| 2. Missing in-scope implementation | None identified for the accepted offline engineering requirements. All eleven software gates pass with final-source canonical/browser evidence and inspected release. |
| 3. External/provider/rights dependencies | Genuine fresh completed-candle acceptance through the actual consumer remains separate; the raw packet/strategy tests are authored fixtures. Historical qualification and actual publisher/rights/operator authority are not supplied. F&O additionally requires dated exact contracts, executable premium/spread/depth and aligned OI/prior-close inputs. Operators/providers must supply those inputs and separately authorized evidence; no request is made here. |
| 4. Explicitly out-of-scope future-phase work | Broader paper lifecycle, measured performance and release acceptance belong to Phase 6. Historical study and live source acceptance are not retroactively granted by this engineering mission. No Phase 6 implementation starts here. |

Both `.env` files and all 407 earlier document/evidence hashes remain unchanged.
The final source has 85 paths, with 21 allowed paths added or changed from the
baseline. HEAD remains `f56927389f07b6cca52abebc6e9d22debd0a50d4`; the source
receipt identifies the actual worktree bytes, and no new commit or clean-worktree
claim is made. Saved risk/provider settings remain preserved. Execution stays
paper, Telegram dry-run and scheduler disabled. No
broker/source request, order, account mutation, Telegram transmission, dependency
installation or operational database migration occurred in this mission's stated
offline scope. Preservation and exact changed-source checks are also included in
the closeout validator's sealing contract.

Both Phase 4 and Phase 5 now have offline implementation acceptance. The next task
is Phase 6 paper-trading/performance/release acceptance under the original roadmap,
with explicit prerequisites for genuine market data, historical authority and
applicable source rights. No Phase 6 implementation starts in this mission.
