# Phase 4 closure and Phase 5 initial requirements and shared contracts

This is the initial implementation matrix, recorded before production assignments.
Authority is the supplied Phase 4 gap closure + Phase 5 mission, sections 4–10,
the fixed six-phase roadmap in that mission and the existing completion roadmap
P1.0/P1.1/P1.2 and P3.1/P3.2. Older Phase 5A/B/C labels describe historical/paper
engineering and do not establish company-context completion. No milestone or score
is redefined. All acceptance here is offline engineering.

The starting checkout is clean HEAD `f56927389f07b6cca52abebc6e9d22debd0a50d4`.
The actual current source matches the retained 924-Python/14-Node/72-compilation
receipt and the Phase 4 release. The separate baseline binds all starting source,
prior documents and both configuration hashes without opening operational databases.

| Requirement and authority | Actual code/input → output → consumer | Positive / negative evidence at start | Initial state | Remaining work / owner |
|---|---|---|---|---|
| P4-A strategy integrity; mission §5/4A | Five actual evaluators + detailed trace → scanner candidates | Existing bidirectional and trace parity; warm-up/input rejects | IMPLEMENTED_AND_VERIFIED | Re-audit boundaries; strategy owner |
| P4-B history/200-bar ST; mission §5/4A | Angel parser → bounded300/750 history → scanner | Raw199/200 count; injected qualified200 scanner positive; reconnect unavailable | PARTIALLY_IMPLEMENTED | Add true eviction regression and inspect usable pre-session baseline without inventing volume; feed owner |
| P4-C qualified input; roadmap P1.1 | Adapter/canonical gates → completed input → evaluators | Wrong token/exchange/time/volume/gap/forming rejects | IMPLEMENTED_AND_VERIFIED | Preserve production gates; coordinator |
| P4-D candidate states; mission §5/4B | Detailed evaluator + scanner risk → trace/candidate arrays | Qualified/rejected/unavailable and empty scan tests | IMPLEMENTED_AND_VERIFIED | Preserve and bind separate context overlay; coordinator |
| P4-E visited explanations; P1.2 | Actual checks + source references → APIs/UI | Trace/source/legacy positive and invalid history tests | IMPLEMENTED_AND_VERIFIED | Cross-phase immutability and failure tests; coordinator |
| P4-F/G numeric risk/ranking; §5/4C | Geometry + ranker → ordered valid candidates | Scanner rejects numeric overflow, deterministic permutations | DEFECT_CONFIRMED | Direct ranker still admits overflow RR; minimal guard + regression; strategy owner |
| P4-H persistence/API; §5/4D | scan_evaluations + immutable cash result → existing history | Rehashed corruption, FK, rollback/replay and legacy tests | IMPLEMENTED_AND_VERIFIED | Add separate context persistence without rewriting evaluations; coordinator |
| P4-I dashboard; §5/4E | Actual inline JS → cards/inspector/scan table | Numeric RR, downstream risk rejection, provenance tests | IMPLEMENTED_AND_VERIFIED | Add context and safe source views; UI owner |
| P4-J/K safety/evidence | Offline guard, exact source/log proof, public release | Retained proof validated against actual starting bytes | IMPLEMENTED_AND_VERIFIED | Fresh final proof/archive after edits; coordinator |
| P5-A context contract; mission §6/5A | No company-context record/parser exists | No end-to-end context tests at start | MISSING | Provider-neutral bounded context schema and offline adapter; context owner |
| P5-B/E qualification/attribution; §6/5A/5E | Historical publisher verifier exists; no context qualifier | Existing signature/archive tests do not qualify news | PARTIALLY_IMPLEMENTED | Context-specific policy, signature/source/rights separation; context owner |
| P5-C/D matching/no bypass; §6/5B | Existing immutable Phase4 candidate ID/identity/time | Base candidate safety exists; no context consumer | MISSING | Exact identity/time matching, no-lookahead, additive non-actionable enrichment; context + coordinator |
| P5-F dashboard; §6/5C | Existing JS/API, no context response/rendering | Existing DOM tests cover Phase4 only | MISSING | Render records/times/status/safe links and failures; UI owner |
| P5-G outbox reliability; §6/5D, roadmap P3.1 | Existing local preview outbox → ACK/RETRY/DEAD → API | Retry/restart tests exist; rehashed receipt can forge identity/mode | DEFECT_CONFIRMED | Cross-bind receipt; add context-aware immutable intents/suppression/dedup; alert owner |
| P5-H resilience; §6/5E | No context source adapter exists | None | MISSING | Explicit offline import, size/parse/time/mapping/failure bounds; context owner |
| P5-I permissions | No approved context publishers, rights or operator trust policy supplied | URL/hash/signature cannot establish rights by assertion | BLOCKED_BY_EXTERNAL_DEPENDENCY | Default unqualified; offline signed fixtures exercise software only; operator supplies actual authority/rights separately |
| P5-J/K integration/evidence | No integrated Phase5 path | None | MISSING | Persisted import → enrichment → API/UI/outbox; negative tests, strict proof and new release; coordinator and independent review |
| Phase6 financial/performance acceptance; mission §12F | Existing paper modules unchanged | Historical evidence remains historical | OUT_OF_SCOPE | Identify next task only after both decisions; do not implement |

## Shared interfaces frozen before implementation

Existing canonical instrument identity, candle dictionaries, `TradeSignal`,
strategy/candidate evaluations, gross numeric risk and rank order remain the Phase4
contracts. Context cannot mutate those fields, confer LIVE acceptance or make any
candidate actionable. Existing saved scan evaluations remain immutable.

The new provider-neutral module is `context_data.py`:

- `parse_context_bytes(raw_bytes, *, provider, collected_at, trusted_identities,
  source_policy=None)` returns schema `tradepulse.context-ingestion.v1`, stable
  ingestion/record identities, bounded canonical records and explicit qualification.
- `context_for_candidate(records, candidate, *, as_of, max_age_seconds=86400)`
  returns schema `tradepulse.candidate-context.v1`, candidate ID, status/reasons,
  selected records, `actionable=false`, `affects_ranking=false`.
- Source identity/reference, original-byte digest, publication/event/collection
  times, canonical mapping, correction/retraction/conflict and derivation rule IDs
  remain distinct. Missing values remain missing. Caller verified flags are not
  trust. Only separately supplied local policy can configure source trust; the
  existing signature verifier establishes key/byte correspondence, not rights.
- Availability is point-in-time: publication, event and collection are no later
  than the evaluation cutoff; stale, conflicting, retracted, unverified and
  unmapped inputs never become qualified neutral sentiment.
- No source performs networking. The supported source adapter accepts explicit
  bounded offline imports; actual provider acquisition/permission stays unavailable.

Coordinator-owned storage adds immutable context ingestions and scan-context
snapshots with checksum/source bindings to the original Phase4 result. A scan
context is schema `tradepulse.scan-context.v1`, with `run_id`, `as_of`,
`phase4_digest`, `ingestion_ids`, `candidate_contexts`, `actionable=false` and
`affects_ranking=false`. An enrichment snapshot is independent of immutable Phase4
evaluations. Existing API payloads add `context`; old history reports unavailable.
Read/import/enrich routes are local guarded application routes; they cannot accept
trust configuration from the request. No configuration or operational database is
changed by this mission.

The alert owner extends the existing outbox, rather than creating another channel.
Context-aware intents must bind an existing persisted candidate/run, source-context
snapshot digest, actual reason, local preview mode and deterministic content key.
Repeated unchanged content is deduplicated. Rejected/unqualified candidates and
missing/stale/unverified contexts produce explicit suppression/warning states.
Acknowledgement means local preview recorded, never message delivered. Existing
attempt limits/backoff/recovery remain bounded. Receipts must match retained intent
identity/mode/content even after attacker recomputation of a checksum.

## Exclusive ownership and integration protocol

| Actual worker | Exclusive production/tests |
|---|---|
| `/root/historical_track_a` | `angel_feed.py`, `strategies.py`, new `test_phase45_scanner_gaps.py`; after freeze, independent cross-phase tests in another new module |
| `/root/dhan_track_b` | New `context_data.py`, new `test_context_data.py`; no storage/server/scanner edits |
| `/root/phase4_readiness_qa` | `notification_outbox.py`, `telegram_bot.py`, `public/index.html`, `test_cash_dashboard.js`, new `test_context_alerts.py`; no storage/server/scanner edits |
| `/root` | `storage.py`, `candle_lineage.py`, `scanner_engine.py`, `server.py`, `test_bot.py`, `release_management.py`, new integration tests, reports/evidence/public handover |

The coordinator mediates shared-file patches and reconciles interface changes.
Workers return exact changed files, commands, failures and freeze hashes. Focused
tests use the isolated interpreter with ResourceWarnings as errors, memory/temp
databases and blocked external transport. The coordinator runs the canonical
strict verifier after integration, inspects actual API/UI and outbox paths, repairs
failures and obtains independent cross-review. Fresh acceptance matrices record
the final disposition separately from this starting matrix. No worker commits,
stages, changes saved settings or rewrites prior receipts.
