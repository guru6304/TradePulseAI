# Phase 5 context, dashboard and alerts - 2026-10-24

**Final engineering verdict: `PHASE_5_IMPLEMENTATION_ACCEPTED`.** All eleven
Phase 5 software gates pass for the offline import, enrichment, existing API/UI
and local alert workflows. Final verification passes 1,019 Python tests, 22 Node
tests, JavaScript syntax and 80 compiled Python files; current-source/log
validation, the final-source 13-check Chrome run and inspection of the new
111-file public release also pass. Actual source acquisition, publisher authority
and rights remain separate external dependencies.

This is the original roadmap's Phase 5, context enrichment, dashboard and alerts.
Older modules labelled Phase 5A/B/C retain their historical/paper meanings; they
are not renamed into proof of company-context acquisition. No source request,
genuine publisher approval, live delivery, trading action or profitability is
accepted by these authored offline fixtures.

## Authority, shared contracts and ownership

The mission authorizes Phase 5 implementation in the existing Python/SQLite/
vanilla-JavaScript architecture after the shared Phase 4 contracts were recorded.
The [initial matrix](phase45_shared_contracts_and_requirements_20261023_01.md)
was created before parallel production assignments. Existing canonical identity,
qualified completed candles, `TradeSignal`, detailed strategy/candidate states,
numeric risk, rank order and immutable scan results remain the base contracts.

| Actual worker | Exclusive implementation and later handoff |
|---|---|
| `/root/dhan_track_b` | New `context_data.py`, `test_context_data.py`; later new `context_workflow.py`, `test_context_workflow.py` under coordinator-mediated ownership |
| `/root/phase4_readiness_qa` | `notification_outbox.py`, `telegram_bot.py`, existing `public/index.html`, `test_cash_dashboard.js`, initial `test_context_alerts.py` |
| `/root/historical_track_a` | Feed/ranker gap files and tests, then independent new `test_phase45_integration.py` and separate QA report |
| `/root` | Shared `storage.py`, `candle_lineage.py`, `scanner_engine.py`, `server.py`, canonical test registration, HTTP/integration regressions, release wiring, evidence and handover; final alert/failure-path repairs after worker handoff |
| `/root/phase45_perf_review` | Independent read-scoped cache/security review; identified additional stored-payload, receipt and existing-import inventory guards for coordinator reproduction and correction |

File ownership was disjoint during production work; shared changes were mediated
by the coordinator. Workers genuinely executed in parallel. The independent
integration reviewer did not implement the production fixes it requested. Later
coordinator finalization does not represent continuing worker execution after
their handoffs. No worker committed, staged, rewrote old evidence or modified
saved configuration.

## Implemented context and provenance contracts

The only new acquisition interface is an explicit **bounded offline JSON import**
implemented by `context_data.parse_context_bytes`. There is no network source
adapter, source polling, fallback provider, paid service or new package.

| Contract | Fields and observable semantics |
|---|---|
| Source document | `tradepulse.context-source.v1`, `records`; provider supplied separately. Records carry source ID/name, safe HTTPS URL or record reference, original reference, canonical identity, title/summary, publication/event times and optional correction/retraction/conflict/interpretation. |
| Normalized ingestion | `tradepulse.context-ingestion.v1`; original-byte SHA, provider, collection time, mapping/policy identity, records, status/reasons and stable ingestion identity. |
| Logical record and semantic content | Record identity binds provider/source/reference/canonical instrument. Content identity binds actual source facts independently of recollection time, supporting semantic deduplication. |
| Candidate overlay | `tradepulse.candidate-context.v1`; candidate ID, `QUALIFIED`, `WARNING_ONLY`, `UNAVAILABLE` or `MISSING`, reasons, source records, `actionable=false`, `affects_ranking=false`. |
| Retained scan overlay | `tradepulse.scan-context.v1`; run/snapshot IDs, evaluation cutoff and mode, original decision time, exact Phase 4 evaluation digest, ingestion/capture links and per-candidate overlays. |

Parser limits are 256 KiB and 100 records per import; text/content fields are
bounded. Duplicate JSON keys, nonfinite numbers including exponent overflow,
malformed structures, unsafe links, naive/future/reversed times, ambiguous mapping
and invalid identifiers fail explicitly. Missing source times remain missing;
they are never synthesized. Interpretation must include a rule identifier and is
labelled `SOURCE_SUPPLIED_UNVALIDATED_INTERPRETATION`; there is no inferred
sentiment model, probability or indicator.

The default policy is empty, so imported claims of verification cannot become
qualified. A separately supplied runtime `ContextSourcePolicy` can combine the
existing Ed25519 verifier with per-source/provider/domain/name/date approvals and
original artifact manifests. Signed-byte/key correspondence is rechecked using
the original bytes. Scope, revocation, mismatched source, date coverage and missing
signature backend fail closed.

Qualification is explicitly `QUALIFIED_UNDER_LOCAL_POLICY`. It establishes the
configured software policy's result, while independent publisher authority and
rights remain unestablished. A URL, checksum, public page, valid fixture signature
or request-supplied flag is insufficient. HTTP callers cannot inject trust policy,
mapping authority or local intake time. No genuine publisher, paid entitlement,
signing credential or external acquisition receipt is shipped.

`context_workflow` stores original bytes, normalized ingestion, trusted mapping
snapshot and actual local observation time. A capture ID binds ingestion and
observation time; a snapshot references those capture IDs through foreign keys.
Rehashing JSON cannot substitute raw facts, backdate local availability or replace
the separately committed Phase 4 result. Qualified history requires the original
separately supplied runtime policy again after restart; absence does not silently
reuse retained verification flags. Schema tests use memory or disposable SQLite
stores, never the user's operational database.

## Actual import-to-candidate path and time boundaries

The supported path is local guarded import, validated retained source capture,
existing actual scanner result, immutable context snapshot, retained alert decision
and the existing history/context APIs and dashboard. The scanner attaches context
only after its original result commits. Optional context failure reports
unavailable while preserving that result. Replay reads retained overlays without
creating another strategy result or alert.

Identity matching is exact canonical instrument/company matching. Relevant source
facts must be available by publication time, event time, claimed collection time
**and actual local intake**. The two explicit scopes are:

- `DECISION_TIME`: bounded by the original scan decision. Late locally observed
  facts remain absent even if their claimed collection time was backdated.
- `CURRENT_INFORMATION`: separately labelled information for a stored candidate.
  It cannot rewrite the original evaluation or imply a current recommendation.

Future facts are withheld entirely, including their text, so they cannot create a
historical warning/conflict. Stale, retracted, conflicting or unverified facts
remain warning-only/unavailable. Missing context is not a neutral assessment.
Selection and conflict/deduplication are deterministic across input order.

Tests compare original Phase 4 strategy/candidate/signal arrays before and after
enrichment, reconcile candidate IDs and exact source/time links, and demonstrate
that a rejected detected candidate remains rejected with null rank even when a
separate fixture policy qualifies its context. Context never changes entry,
invalidation, stops/targets, sizing, numeric RR, rank or actionability.

Stores enforce bounded inventories of 200 ingestions/2,000 records, 4 MiB per
snapshot and 200 snapshots per run. Overflow reports a precise failure rather than
silently omitting records. Snapshot loading reparses original ingestions and
recomputes the expected overlay against the separately retained Phase 4 result.

SQLite affinity is not treated as proof of stored type. A privileged corruptor
can put BLOBs in nominal TEXT columns or integers in BLOB columns. Readers now
reject incorrect types and enforce byte limits **before** JSON decoding or raw
coercion: 4 MiB for normalized ingestion, mapping and snapshot JSON, 256 KiB for
original source bytes, outbox bodies, context-alert decisions and receipts.
Existing ingestion rows are fully source-revalidated before a new import counts
their records. Invalid stored state produces the existing persistence-failure/
503 behavior, rolls back the import and cannot be accepted by rehashing JSON.

## Existing APIs and dashboard

The server extends its loopback/same-origin routes, also supporting `/api/v1/`:

| Route | Contract and consumer |
|---|---|
| `POST /api/context-import` | Exactly `provider`, `collected_at`, `payload` (object or original JSON string); stores validated offline input. |
| `POST /api/context-enrich` | `run_id`, optional `as_of`/`evaluation_mode`; retains a snapshot and alert decision. Future or naive cutoffs reject. |
| `GET /api/context?run_id=...` | Latest retained snapshot or selected `snapshot_id`; without a run, bounded ingestion inventory via limit/offset. Raw bytes and private trust policy are not returned. |
| `GET /api/context-alerts?run_id=...` | Bounded retained eligibility/suppression decisions. |
| Existing scan/signals/history/outbox routes | Additive context, source/time/snapshot references and decisions; legacy history remains missing/unavailable. |

The new body readers enforce 512 KiB, explicit unambiguous Content-Length, no
Transfer-Encoding, strict JSON and a five-second read bound. Both import and
enrich timeout paths are covered. Invalid requests return 400; storage or integrity
failures return 503. Reads do not fetch, enrich, schedule or transmit anything.

The existing inline renderer shows source facts, safe links, source and collection
times, freshness, policy limitations, scope and suppression. It uses safe text
rendering for untrusted titles/summaries and validated HTTPS links with
`noopener noreferrer`. Malformed/wrong-identity input and API failure clear old
facts. Candidate state and Phase 4 explanation remain visible under the same
contracts. No framework or unrelated screen was introduced.

The retained actual Chrome 155 [stage 03](../evidence/phase45_browser_20261024_03.json)
passed 13 DOM/API checks, exit 0: real signals API rendering, literal hostile markup,
safe-link attributes, policy/time labels, actual current/stale states, wrong
mapping/missing/503 clearing, blocked external probe, no runtime JavaScript
exception and only loopback GET/HEAD reaching the application. Original inline
renderer functions were unchanged in the served fixture; external CDN/CSS was
omitted and chart drawing stubbed. This does not accept full styling, all browsers
or real publisher content. The final-source
[stage 04](../evidence/phase45_browser_20261024_04.json) repeats all 13 checks
successfully, exit 0, with source unchanged, no runtime JavaScript exceptions,
Chrome exit 0, server thread stopped and disposable profile removed. The external
probe was blocked before request transport.

## Alert lifecycle and safety

Context alerts extend `notification_outbox.py`; they do not introduce a channel
or service. `ELIGIBLE`, `SUPPRESSED`, `UNAVAILABLE` business decisions are separate
from outbox `PENDING`, `RETRY`, `ACKNOWLEDGED`, `DEAD` states. Eligibility requires an
originally qualified retained cash candidate and fresh context qualified under
separately configured local policy. Rejected/missing/stale/conflicting/unverified
inputs preserve suppression reasons and cannot produce an eligible alert.

Deduplication binds candidate identity, semantic record/content IDs and policy.
Changed collection/evaluation timestamps alone do not create another intent.
Changed actual facts can produce exactly one new intent while retaining the
original candidate and prior snapshot. Retry uses the actual execution clock,
not a historical decision cutoff, with the existing three-attempt limit and
bounded backoff. No fourth attempt or false acknowledgement occurs.

Preview payloads bind exact run/candidate/input batches, original immutable
notification descriptors or context snapshot/Phase 4 digests, actual source facts
and reconstructed message. Retained eligibility/reason/policy is recomputed from
the sources. Rehashing altered payload, receipt or decision JSON cannot grant
delivery, LIVE acceptance, alternative message content or eligibility. Legacy
outbox rows without new descriptors expose their limited historical binding.

`ACKNOWLEDGED` means `DRY_RUN_RECORDED`, never delivered. Precommit failures roll
back attempts, postcommit acknowledgement loss recovers the retained receipt,
concurrent enqueue remains one semantic intent and SQLite backup/restart preserves
pending/acknowledged state without a second successful render. Telegram messages
use supported numeric gross RR and explicitly label nominal ratios and unavailable
net RR. No real send was attempted.

Repeated integrity validation originally made concurrent dashboard reads exceed
the existing three-second budget. The repaired read path shares validated
evaluation/snapshot/source components only within its locked SQLite read scope.
Every new request revalidates source, result and decisions; no global or
cross-request trust cache is introduced. The original concurrent test passes for
memory and disposable file stores without changing the latency assertion.

## Requirement disposition and evidence

| Gate and actual code/consumer | Positive and failure evidence | Current state |
|---|---|---|
| P5-A: `context_data` schemas -> workflow/API | `test_context_data.py` validates precise identity/time/status/interpretation semantics and limits | `IMPLEMENTED_AND_VERIFIED` |
| P5-B: local source policy/raw reparse -> qualified/warning records | Actual fixture Ed25519 signature, revocation/scope/date/rights negatives, unknown policy, malformed/stale/conflicting/retracted inputs | `IMPLEMENTED_AND_VERIFIED` |
| P5-C: `context_workflow` -> immutable candidate overlays | Actual scanner/import/history integration, exact company matching, captured intake time, decision/current separation, snapshot/source FKs | `IMPLEMENTED_AND_VERIFIED` |
| P5-D: scanner/candidate preservation -> API/outbox | Rejected actual detected setup stays rejected; all original arrays remain equal; unqualified context never admits an alert | `IMPLEMENTED_AND_VERIFIED` |
| P5-E: source record/rule -> UI/message | Actual source references/times and unvalidated-interpretation labels; missing values remain absent | `IMPLEMENTED_AND_VERIFIED` |
| P5-F: existing inline UI/real APIs | 22 Node tests and final-source Chrome stage 04; hostile markup, unsafe links, stale/missing/wrong mapping/503 | `IMPLEMENTED_AND_VERIFIED` |
| P5-G: existing outbox -> local preview/receipt | `test_context_alerts.py` lifecycle, exact-once replay, three-attempt DEAD, concurrency, restart, rehashed intent/receipt/decision rejection | `IMPLEMENTED_AND_VERIFIED` |
| P5-H: bounded offline adapter/API -> explicit errors | Strict parser/stored-payload/size/time bounds, both request timeouts, actual SQLite trigger rollback, no request-driven policy/provider switching | `IMPLEMENTED_AND_VERIFIED` |
| P5-I: local policy/guards/safe rendering -> no invented authority | Trust/mapping/intake injection rejected, no secrets in APIs, XSS literal text and external browser request blocked | `IMPLEMENTED_AND_VERIFIED` |
| P5-J: additive integration -> old scanner/history/concurrent reads | Existing behavior and corruption checks retained; unchanged concurrent budget passes in the final full suite; stored types/sizes reject before decoding | `IMPLEMENTED_AND_VERIFIED` |
| P5-K: final verifier/packager -> current source/release | Final 1,019-case canonical proof, current-source/log validator, final browser04 and inspected 111-file release | `IMPLEMENTED_AND_VERIFIED` |

Every state in this table is for software behavior. Genuine source accessibility,
publisher authority and licensed use remain external dependencies described below;
they are not relabelled as verified by this table.

The [independent integration review](phase45_independent_integration_qa_20261023_01.md)
records 15 passed cases through actual scanner/store/API/outbox logic using
authored memory-store inputs. It reproduced a real context/cash/outbox recursive
validation cycle; the workflow owner replaced the recursive full-cash-result call
with direct committed/evaluation bindings. The corrected path has an explicit
actual cash v2 context regression.

Two actual rehashed legacy outbox bypasses were retained in the
[before receipt](../evidence/phase45_alerts_integrity_before_01.json); the
[after receipt](../evidence/phase45_alerts_integrity_after_01.json) passes both
unchanged behaviors after cross-binding. The
[timeout-before receipt](../evidence/phase45_alerts_http_timeout_before_01.json)
records the real enrich body-reader exception; the corrected HTTP stage passes
all eight original HTTP cases. Trigger-based actual SQLite failures were retained
in the [before receipt](../evidence/phase45_alerts_sqlite_before_01.json), then
[28 affected cases passed](../evidence/phase45_alerts_sqlite_after_01.json),
including the two canonical SQLite regressions. These stages are preserved, with
the exact source/log bindings recorded by their runners.

The [135-case integrated stage](../evidence/phase45_alerts_integrated_final_01.json)
passed before the latest source repairs. The first
[canonical run](../evidence/master_phase45_20261024_01.json) executed 1,010 Python
tests: 1,007 passed, one concurrent-latency failure, two fixture errors, exit 1.
Foreign-key and early-rejection HTTP fixture updates preserve their substantive
assertions; the subsequent
[repair stage](../evidence/phase45_alerts_repair_verification_01.json) has 11/12
passed, zero errors and the remaining latency failure. No threshold was raised,
corruption check removed or failed run relabelled as accepted.

The subsequent read-scoped validation repair passes the unchanged concurrency
test in the [55-case repair stage](../evidence/phase45_alerts_repair_verification_03.json).
The [second canonical run](../evidence/master_phase45_20261024_02.json) passed
1,012/1,012 Python tests, 22/22 Node tests, JavaScript syntax and 80 compiled Python
files, exit 0, with zero failures/errors/skips/expected failures/unexpected
successes or unraisable exceptions. That intermediate full pass predates the
independent review's further corruption-boundary findings; it is retained without
being presented as final-source proof.

`/root/phase45_perf_review` reviewed the actual cache/integrity paths and found
stored BLOB/type, oversize, receipt and import-inventory gaps. The coordinator's
[first reproduction](../evidence/phase45_alerts_corrupt_payload_before_01.json)
executed five cases, zero passes, eight failed subtests and two errors. The
[follow-up reproduction](../evidence/phase45_alerts_corrupt_followup_before_01.json)
executed seven cases, five passes and three failed subtests. These are genuine
failed stages; subtest failures are not additional executed cases.

The production corrections enforce stored type/size bounds before decoding and
source revalidation before inventory counting. The
[59-case corruption/compatibility stage](../evidence/phase45_alerts_corrupt_payload_after_01.json)
passes the unchanged concurrency test alongside affected persistence cases.
The [87-case final affected stage](../evidence/phase45_alerts_corrupt_followup_after_01.json)
passes all registered source/workflow/alert/HTTP/independent integration cases,
exit 0. `test_context_http.py` now contains 17 canonical cases: eight actual HTTP,
two actual SQLite-failure and seven stored-payload guard cases. They exercise real
SQLite mutation and confirm rejected data never reaches the JSON decoder/source
validator where the applicable guard must precede it. The final canonical run
below includes these last source changes and all seven stored-payload regressions.

The canonical final commands are:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase45_20261024_03
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --validate-evidence docs/evidence/master_phase45_20261024_03.json
```

The [final canonical receipt](../evidence/master_phase45_20261024_03.json)
records **1,019/1,019 Python tests**, **22/22 Node tests**, **80 compiled Python
files** and JavaScript syntax, all exit 0. Failures, errors, skips, expected
failures, unexpected successes and unraisable exceptions are zero;
ResourceWarnings were errors. The exact expected/executed/passed test IDs and
85-path source snapshots are retained. Execution ran from
`2026-10-24T03:53:41.298185+00:00` through
`2026-10-24T03:57:38.152583+00:00`. The separate evidence validator completed
exit 0 against exact current source and retained logs. The baseline's 924/14/72
totals are not reused as final results.

Exact output is in the
[Python log](../evidence/master_phase45_20261024_03_python.txt),
[Node log](../evidence/master_phase45_20261024_03_node.txt) and
[syntax log](../evidence/master_phase45_20261024_03_syntax.txt). Canonical discovery
includes all legacy suites and new `test_context_data`, `test_context_workflow`,
`test_context_alerts`, `test_context_http`, `test_phase45_integration` and
`test_phase45_scanner_gaps`. This is the repository's existing
`unittest.TextTestRunner(test_bot.load_tests)` path, not a substituted focused suite.

The [new archive](../evidence/phase45_release_20261024_01.zip) is built and the
[release inspection](../evidence/phase45_release_inspect_20261024_01.json) passes,
exit 0: **111 manifest-listed public files**, exact current file bytes,
manifest/path/size/hash checks and private-file exclusions. SHA-256:
`6646949db0219f8921700b2cf4aae0d51667538491e1f9e06f01294f32517d1e`.
Private exact credential comparison passes without exposing values; one same-key
exact template placeholder from `.env.example` is excluded from that comparison.
New `context_data.py` and `context_workflow.py` are explicitly packaged, with the
public handover. `.env`, databases/WAL/SHM, `.local`, private source/policy material
and machine evidence remain excluded. Public archive integrity does not establish
publisher authentication.

Machine-evidence locations are the
[final requirement matrix](../evidence/phase45_acceptance_20261024_01.json),
[closeout](../evidence/phase45_closeout_20261024_01.json) and
[separate sealing validation](../evidence/phase45_closeout_validation_20261024_01.json).
Those sealing outputs bind these final reports; their own recorded statuses and
hashes determine the sealed handover's integrity.

## Remaining blockers and operational limitations

| Required blocker category | Exact current disposition and owner |
|---|---|
| 1. Confirmed software defects remaining | None identified in the reviewed in-scope paths. Concurrent latency, recursion, timeout, actual SQLite and stored-payload findings have retained negative/positive evidence and passing final canonical regressions. |
| 2. Missing in-scope implementation | None identified for the accepted offline import/enrichment/UI/outbox requirements. All eleven software gates pass with final current-source canonical/browser evidence and inspected release. |
| 3. External/provider/rights dependencies | No genuine approved context publisher or acquisition/entitlement evidence was supplied. The operator must separately provide dated source/identity authority, trust anchors and approved rights; a provider must supply genuine original bytes and applicable proofs. Local fixture signature success is not publisher or legal-rights acceptance. Live market and historical/F&O dependencies remain separate and unchanged. |
| 4. Explicitly out-of-scope future-phase work | Phase 6 broader paper trading, performance and release acceptance; external acquisition, extra alert channels/background services and new indicators/formulas are not initiated. No profitability, fill, slippage or live-delivery acceptance is claimed. |

Both `.env` files and all 407 pre-existing document/evidence hashes remain
unchanged. The final 85-path source snapshot has 21 allowed additions/changes;
HEAD remains `f56927389f07b6cca52abebc6e9d22debd0a50d4`. No new commit or clean
worktree is claimed. Operational databases and their WAL/SHM remain unopened.
No broker request, order/account mutation, Telegram
transmission, scheduler activation, source request or dependency installation is
part of this mission. The public handover contains interfaces and honest limits;
machine receipts, private source material, policy material, `.env`, databases and
`.local` content remain excluded from the inspected public ZIP.

Both Phase 4 and Phase 5 now have offline implementation acceptance. The next
task is Phase 6 paper-trading/performance/release acceptance under the fixed
six-phase roadmap, with explicit genuine-data/authority/rights prerequisites.
This report does not begin Phase 6 or convert offline engineering evidence into
source or market acceptance.
