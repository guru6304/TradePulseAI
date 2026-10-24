# Phase 4 closure and Phase 5 context handover — 2026-10-24

This handover describes offline engineering. It does not accept real market data,
publisher authority, licensed context use, profitable strategies or live delivery.
The original six phases and milestone rubric are unchanged. Existing historical,
paper and derivative modules with earlier Phase 5A/B labels remain separate from
the context/dashboard/alerts phase implemented here.

The existing five strategies, qualified-candle policy, candidate fields, sizing
and ranking remain the Phase 4 decision. The direct ranker now rejects nonfinite
derived target RR. The bounded Angel history remains 300 five-minute and 750
one-minute bars. A raw-persisted same-day SNAP observation no more than 30 seconds
before the configured opening can provide an observed cumulative-volume baseline.
The first in-session delta must still match the observed quantity with valid
chronology and gap checks. No zero baseline or missing candle is invented.
Without that observation, session opening coverage remains unavailable. Reconnect
and restart still do not restore volatile feed history automatically.

`context_data.py` implements a provider-neutral, bounded **offline JSON import**.
It does not retrieve a website or make a provider request. Input has schema
`tradepulse.context-source.v1` and a `records` array. Each record carries source
ID/name, safe HTTPS URL, source record reference, canonical instrument identity,
publication/event timestamps, title/summary and optional original reference,
correction/retraction/conflict and explicit interpretation. Missing information
remains unavailable. There is no automatic sentiment model or trading indicator.

The source adapter checks structure, duplicate JSON keys, finite values, text and
payload limits, URLs, identities and aware timestamps. A URL, checksum or supplied
`verified` flag cannot establish authority. The default source policy is empty:
imports are unverified/warning-only. A separately supplied runtime
`ContextSourcePolicy` may combine an existing Ed25519 trust configuration,
per-source domain/name/provider approvals and artifact manifests. Qualification is
explicitly **under that local policy**; a valid signature still does not establish
independent publisher authority or licensing. The software ships no genuine
approved publisher, paid source, credential, signing key or external acquisition.
HTTP clients cannot supply trust policy, mapping authority or local intake time.

`context_workflow.py` retains original input, normalized ingestion, trusted mapping
snapshot and a local capture ID. Immutable scan-context snapshots bind those
captures to the exact original Phase 4 evaluation digest. Recomputed checksums
cannot replace source facts, local intake times or the independently retained
Phase 4 result. Operator policy must be explicitly supplied again after restart
for qualified history to be revalidated; absence fails closed.
Stored normalized input, mapping and scan-context JSON each have a 4 MiB bound
checked before decoding. Original source bytes retain the 256 KiB import bound;
SQLite values of an unexpected type fail as persistence errors.

Context never changes entry/stop/targets, risk, rank or candidate actionability.
It distinguishes `QUALIFIED`, `WARNING_ONLY`, `UNAVAILABLE` and `MISSING`; missing
context is not a neutral market assessment. Identity must match exactly.
Publication, event, claimed collection **and actual local intake** availability
are checked. Later facts are withheld from historical decisions.

Two time scopes are explicit:

- `DECISION_TIME` uses the original scan reference and cannot include later input.
- `CURRENT_INFORMATION` is a separately labelled update for a stored candidate.
  It cannot retrofit the original strategy decision or imply a current trade.

Existing `POST /api/scan`, `GET /api/scans` and `GET /api/signals` add context
metadata. The scanner enriches after its original result commits; optional context
failure leaves that original result intact and reports context unavailable.
Idempotent scan replay reads retained context without issuing a new alert.
The existing dashboard cards, inspector and scan-history table show source facts,
safe links, times, qualification, scope, warnings and alert suppression. Source
text uses safe text rendering. API failures clear previous facts.

Additional loopback/same-origin routes are:

| Method and route | Behavior |
|---|---|
| `POST /api/context-import` | Body contains exactly `provider`, `collected_at`, `payload` (object or original JSON string); validated offline import only |
| `POST /api/context-enrich` | `run_id`, optional `as_of` and `evaluation_mode`; stores an immutable context snapshot and local alert decision |
| `GET /api/context?run_id=...` | Reads the latest snapshot; optional `snapshot_id` selects retained history |
| `GET /api/context?limit=...&offset=...` | Bounded normalized import inventory; no raw source/private policy response |
| `GET /api/context-alerts?run_id=...` | Bounded retained alert decisions |
| `GET /api/notification-outbox` | Existing preview lifecycle plus context references and suppression decisions |

The new routes also support the existing `/api/v1/` prefix. They do not start a
fetcher, scheduler or message service. JSON request size and read time are bounded.
Use isolated fixture databases for evaluation and schema checks. Do not migrate or
reset an operational database as part of this offline handover.

Context alerts extend the existing outbox. Only an originally qualified retained
cash candidate with fresh context qualified under separate local policy can
produce an eligible **local preview**. Rejected candidates and unqualified,
stale, conflicting or unavailable context retain suppression reasons. Deduplication
uses candidate identity, actual semantic context content and policy, so later
timestamps alone do not create another alert. Changed facts can create one new
intent without changing the original decision.

Business states `ELIGIBLE`, `SUPPRESSED`, `UNAVAILABLE` are separate from persisted
`PENDING`, `RETRY`, `ACKNOWLEDGED`, `DEAD`. Acknowledgement means
`DRY_RUN_RECORDED`, never delivered. Retry timing uses the actual execution clock,
not an old decision cutoff. Backoff is bounded to three attempts; acknowledgement
loss/restart cannot render a successful intent twice. The body and receipt are
cross-bound to original candidates, input batches and context snapshots, not just
their own checksums. Old notification history reports its limited legacy binding.
Messages report supported numeric gross RR and label old nominal ratios.

Keep saved `.env`, provider and risk settings unchanged, execution in paper mode,
Telegram in dry-run mode and the production scheduler disabled. No new dependency,
real source access or message delivery is enabled by this change.

The canonical offline verifier is still:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage unique_review_stage
```

Use a unique stage; validate the resulting receipt with `--validate-evidence PATH`.
Final Phase 4, Phase 5 and integration reports are retained under `docs/reports/`
with prefix `phase45_`; matching `phase45_*` and `master_phase45_*` machine evidence
remains in the original repository's `docs/evidence/`. Hand over that evidence
separately from the public ZIP. Exclude `.env`, databases/WAL/SHM, private source
captures, trust-policy material and `.local` data from public archives.
