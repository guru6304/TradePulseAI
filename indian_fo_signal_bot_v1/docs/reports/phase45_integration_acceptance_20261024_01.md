# Phase 4 and Phase 5 integration acceptance — 2026-10-24

**Phase 4: `PHASE_4_IMPLEMENTATION_ACCEPTED`.**
**Phase 5: `PHASE_5_IMPLEMENTATION_ACCEPTED`.**
Both decisions cover the defined offline engineering requirements. The actual
integrated paths, failure regressions, final source-bound verification, browser
execution and public archive inspection support the separate decisions.

This mission implements the original roadmap's scanner/recommendation and
context/dashboard/alerts engineering. It preserves the six phases and their
milestone rubric. Software acceptance does not qualify a genuine market feed,
historical study, context publisher, licensed use, F&O execution or profitable
strategy.

The [initial shared requirements matrix](phase45_shared_contracts_and_requirements_20261023_01.md)
was written before parallel implementation. The separate
[Phase 4 closure](phase45_phase4_closure_20261024_01.md) and
[Phase 5 completion](phase45_phase5_completion_20261024_01.md) reports describe
each requirement and its code/test contracts. The final
[machine matrix](../evidence/phase45_acceptance_20261024_01.json) records all
eleven gates for each phase as `IMPLEMENTED_AND_VERIFIED` for offline engineering;
external source/market acceptance remains separately blocked.

## Integrated behavior and actual evidence

| Required behavior | Supported execution path and evidence |
|---|---|
| Original strategy decisions stay immutable | Actual scanner fixture creates a committed cash result and evaluations. Offline source import and enrichment create a separate digest-bound context snapshot. `test_phase45_integration.TestPhase45IndependentIntegration` compares the original strategy/candidate/signal arrays before and after enrichment, API reads and preview. |
| Context cannot promote a rejected candidate | A real detected setup rejected by the scanner keeps `REJECTED`, null rank and `actionable=false` with locally policy-qualified context; outbox decision is suppressed. No score or context predicate overrides mandatory data, warm-up, sizing or geometry. |
| Identity and time stay consistent | Exact canonical provider/symbol/identifier/exchange/segment/type/revision matching; publication/event/collection and independently captured intake time must precede the cutoff. Later facts are withheld entirely. `DECISION_TIME` and separately labelled `CURRENT_INFORMATION` preserve the original decision. |
| Persisted alerts have real source links | Context alert bodies and retained eligibility decisions are rebuilt from the candidate and immutable snapshot, original raw input and current separately supplied local policy. Snapshot/capture/Phase 4 mismatches, altered reason/policy and rehashed payloads fail closed. |
| Repeated work does not duplicate results | Original scan replay remains idempotent; semantic context IDs ignore collection/evaluation timestamp churn. Identical facts reuse one intent; changed facts can create one new intent. Retry/restart and postcommit acknowledgement loss do not render an acknowledged preview twice. |
| API, dashboard and persistence agree | Actual local HTTP routes expose the same stored snapshot/candidate IDs. Existing inline rendering is exercised in Node and actual Chrome against real local API payloads, with safe links, literal hostile markup, correct warnings, scope and failure clearing. |
| Failures retain truthful output | Optional overlay storage failure preserves the already committed Phase 4 result and reports context unavailable. Import rollback leaves zero sources. Corruption yields storage/integrity failure rather than substituted facts; absent context remains missing, never neutral. |
| Existing concurrent dashboard behavior remains required | The original 36-request memory/file SQLite burst retains its three-second per-request assertion. Validated inputs are reused only within one locked SQLite read snapshot, with all decision/body checks retained and no cache across requests. |

The independent reviewer authored and executed fifteen integration cases through
the actual engine, store, APIs and outbox, using isolated memory stores and
authored candle/context inputs. It reproduced the context/cash/outbox recursion;
the production owner corrected the cycle. Its
[independent report](phase45_independent_integration_qa_20261023_01.md) retains
the original finding and limits. A later independent source review found the
stored-payload type/size candidates that triggered the final hardening loop.
No worker's fixtures are represented as genuine market or publisher evidence.
The [final code review](phase45_final_independent_review_20261024_01.md)
independently read back the 87-case focused log and all 85 matching source hashes,
and found no remaining actionable issue in its inspected paths. It distinguishes
the reviewer's cache authorship from independently raised guard defects corrected
by the coordinator; it leaves final canonical/browser/archive gates to closeout.

## Repairs and retained execution history

The direct ranker rejects derived infinite target RR. The actual Angel history
ring retains 300 five-minute bars, evicts the oldest of 301, preserves continuity
checks and never lowers Supertrend's 200-bar threshold. A raw-persisted same-day
SNAP observation within thirty seconds before opening can establish an observed
volume baseline; missing/old/ambiguous observations remain ineligible. The actual
201-bar evaluator diagnostic is a fixture and still fails the genuine LIVE gate.

The initial outbox inspection reproduced two rehashed-content/receipt bypasses.
Original preview content is now bound to separately committed descriptors;
receipts are exact reconstructions of that content and local-preview state.
Context snapshots avoid recursive full cash loading while retaining committed
result/evaluation checks. Eligibility/reason/policy is recomputed from sources.
The enrich body timeout and real SQLite trigger failures have explicit controlled
regressions and corrected error handling. Numeric gross RR is displayed from
actual levels, while nominal ratios and unavailable net RR remain labelled.

Every failed receipt remains retained. The first full execution, stage
`phase45_20261024_01`, had 1,010 executed, 1,007 passed, one concurrent latency
failure and two fixture errors. Foreign-key and unread-body fixture repairs
preserved the substantive assertions. The first latency repair still failed;
the shared per-read validation cache then passed all 55 affected cases in
`phase45_alerts_repair_verification_03.json`. Stage 02's sandbox failure is also
retained separately; its temporary file-backed SQLite connections were denied by
the sandbox and were rerun with the approved offline verifier outside it.
That failed sandbox stage also retained 60 ResourceWarning unraisable records;
it is neither accepted nor omitted. Final strict and accepted focused runs have
zero unraisables. The closeout precheck first rejected historical failure records
under an overly broad zero-warning requirement; its retained
[failure record](../evidence/phase45_closeout_precheck_20261024_01.json)
documents the validator correction. Log/receipt hashes remain mandatory for all
stages; zero unraisables is mandatory for every accepted stage.

Stage `phase45_20261024_02` passed all 1,012 Python tests after the latency repair.
Independent review then reproduced corrupt stored BLOB/type and oversized payload
failures: five methods with zero passes, eight subtest failures and two errors.
The next review reproduced two further receipt/inventory methods (seven methods
including the previous five: five passed and three subtest failures). All
receipts remain unchanged. Guards now reject non-text/oversized stored JSON
before decoding, reject integer/oversized original bytes before validation or
coercion, and validate existing source captures before counting inventory for a
new import. A corrupt inventory returns storage failure, rather than blaming the
new valid input. Normalized source/identity/snapshot JSON has a 4 MiB bound;
original input and outbox payloads/receipts have a 256 KiB bound.

The final affected execution, `phase45_alerts_corrupt_followup_after_01.json`,
passed 87/87 tests, zero failures/errors/skips. All seven new stored-corruption
methods are in canonical `test_context_http.py`. The final strict stage is
`phase45_20261024_03`. Intermediate focused receipts bind their own exact source,
IDs and logs, and do not substitute for its final current-source proof.

## Final execution and source binding

The [final canonical receipt](../evidence/master_phase45_20261024_03.json) passed:
**1,019/1,019 Python tests**, **22/22 Node tests**, JavaScript syntax and
**80 compiled Python files**. Failures, errors, skips, expected failures,
unexpected successes and unraisable exceptions are zero. Source before/after
is identical across 85 files. The actual test identities and exact retained
Python/Node/compilation logs are bound by that receipt. Separate current-source
`--validate-evidence` execution also returned exit 0.

The final [Chrome stage 04](../evidence/phase45_browser_20261024_04.json)
passed all 13 real DOM/API/security checks against the final source, exit 0.
Chrome, the local HTTP server and the disposable profile shut down cleanly.
Only loopback GET/HEAD reached the server, and an external probe was blocked.
CDN/CSS was omitted and chart drawing stubbed; this is actual inline-renderer
acceptance for fixture API data, with no full visual, cross-browser or genuine
publisher acceptance claim.

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase45_20261024_03
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --validate-evidence docs/evidence/master_phase45_20261024_03.json
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/phase45_browser_verify_20261024_01.py --stage 04
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/phase45_closeout_20261024_01.py --build-release
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/phase45_closeout_20261024_01.py --closeout
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/phase45_closeout_20261024_01.py --validate
```

Each stage uses exclusive output names. The last two commands seal and separately
revalidate this report, the machine matrix, final source/log/ZIP bindings and
baseline preservation. Their receipts are the
[closeout](../evidence/phase45_closeout_20261024_01.json) and
[separate validation](../evidence/phase45_closeout_validation_20261024_01.json).

## Release and preservation

Starting HEAD is `f56927389f07b6cca52abebc6e9d22debd0a50d4`. The baseline checked
77 source files, 407 existing documents/evidence files, both configuration hashes
and the prior 102-file archive against actual bytes. Source edits remain in the
working tree; no agent Git commit, reset, clean, staging or merge occurred.

The final closeout independently revalidates the complete strict receipt,
actual browser receipt, current source and logs, baseline preservation and new
ZIP. ZIP validation checks manifest paths, sizes, checksums and exact current
packaged files, with `.env`, operational databases/WAL/SHM, `.local`, private
source/policy material and machine evidence excluded. A private exact comparison
also checks configured credentials without printing them. Public interfaces and
limits are in the packaged [handover](../TRADEPULSE_PHASE45_HANDOVER_20261024.md).

The [new public archive](../evidence/phase45_release_20261024_01.zip) contains
111 current public files. Manifest, paths, sizes, content hashes, exact packaged
bytes and exclusions passed actual inspection in the
[release receipt](../evidence/phase45_release_inspect_20261024_01.json).
SHA-256: `6646949db0219f8921700b2cf4aae0d51667538491e1f9e06f01294f32517d1e`.
An [independent executed checker](../evidence/phase45_release_independent_20261024_01.json)
also passed all 111 payload files plus the manifest, deriving its allowlist from
the literal declarations and actual test filenames. It independently checked
ZIP CRC, exact bytes/hashes/sizes, current strict test/source/log bindings and
browser source/helper/log/cleanup bindings without importing the application or
reading configuration/databases. Its helper and receipt are sealed at closeout.
It excludes this mission's machine evidence and acceptance reports; selected
existing public documents remain in the allowlist. The repository retains the
full evidence handover separately. Both configuration files and all 407 prior documents are
unchanged; 21 source files changed within the assigned scope, including eight
new production/test files. No Git commit was created.

No operational database/WAL/SHM was opened, migrated or content-hashed. Their
contents and possible concurrent user application activity are not attested.
Both saved `.env` files and old evidence remain preserved. No provider request,
order, account mutation, Telegram send, scheduler activation or dependency
installation occurred in this mission.

## Four blocker categories and next task

| Category | Current disposition |
|---|---|
| Confirmed software defects remaining | None identified in the reviewed scope after the repairs, focused executions, final canonical run and independent code review. Previously reproduced failures retain their original before/after evidence. |
| Missing in-scope implementation | None identified for the authorized offline scanner/context/API/dashboard/outbox contracts. Unsupported genuine source/market/performance capabilities remain explicitly separate below. |
| External/provider/rights dependencies | Genuine completed market candles through the actual consumer, qualified historical research, genuine context originals, dated authority/rights and operator policy are unavailable here. F&O additionally needs dated contracts, executable premiums/spread/depth and aligned OI/prior-close data. Local fixture signatures and checksums prove none of those external facts. |
| Explicitly out-of-scope future-phase work | Phase 6 broader paper lifecycle, performance and release acceptance; new source requests, services/channels and strategy formulas are not started. |

With both engineering decisions complete, the next task follows the original
roadmap: scope Phase 6 paper/performance acceptance against the actual
remaining data and authority prerequisites. This report starts no Phase 6 work
and does not turn prior blocked data milestones into accepted ones.
