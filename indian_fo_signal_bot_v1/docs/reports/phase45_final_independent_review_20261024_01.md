# Phase 4/5 final code review - 2026-10-24

**Review disposition: no remaining actionable defect found in the inspected
offline context, persistence, cache, API and local-preview contracts.** This is a
code-review result, not final Phase 4 or Phase 5 acceptance. The coordinator's
final canonical verification, current-source browser check, release inspection
and evidence sealing were still pending when this report was written. This
report does not assert their results or imply genuine market/source acceptance.

## Reviewer, ownership and execution limits

The actual reviewer is `/root/phase45_perf_review`. The reviewer first traced the
concurrent dashboard regression, then implemented optional cache forwarding in
`context_workflow.py` and `notification_outbox.py` under exclusive coordinator
assignment. The coordinator integrated the outer storage/lineage readers. This
review therefore includes review of that worker's own cache contribution; it is
not represented as wholly independent authorship of every inspected change.

The later stored-payload findings were reported independently to the coordinator.
The reviewer authored only the separate five-case corruption helper. The
coordinator executed the before cases, implemented the production guards, copied
the behaviors into canonical discovery and added the two follow-up regressions.
This reviewer did not implement those guard corrections.

The present review read production code, canonical tests and retained receipts,
and compared file/log hashes. It executed no test, browser, provider request,
notification or trading action, changed no saved setting, and opened no
operational database. The only file written by this final review is this report.
The scope is selected changed contracts and their reachable consumers, not a
claim of exhaustive line-by-line review of the entire repository.

## Findings and verified dispositions

| Finding and actual boundary | Final source and canonical regression | Disposition |
|---|---|---|
| Repeated evaluation/context validation multiplied work under the SQLite lock | `storage.py:3142` now queries scan history within `lineage_read`; its fresh cache at `storage.py:3177` reaches the existing evaluation loader, context loader and alert-decision validation. `candle_lineage.py:461` does the same for signal annotation; `notification_outbox.py:395` creates its own cache inside the read transaction. The unchanged budget remains in `test_bot.TestIndianFOSignalBotPhase1F.test_p1f_concurrent_promise_all_burst_across_all_dashboard_endpoints` at `test_bot.py:2333`. | Implementation reviewed; no threshold or validation removal found. Final execution of that unchanged test remains part of the coordinator's pending full verification. |
| SQLite can retain BLOBs in nominal TEXT payload columns, previously causing an uncaught `AttributeError` | `notification_outbox.py:59` and `:250` now reject non-text or oversized intent/decision JSON before `.encode`/decoding. `test_context_http.TestStoredContextPayloadGuards.test_nontext_original_outbox_payload_is_graceful_persistence_failure` and `.test_nontext_context_decision_returns503_from_supported_alert_api` use actual SQLite BLOB values. | Corrected. Failure becomes `PersistenceValidationError`, or the supported context-alert handler's 503/UNAVAILABLE response. |
| Oversized/non-text retained source, mapping and snapshot JSON reached the decoder | `context_workflow._stored_json` at `context_workflow.py:41` enforces text type and a 4 MiB UTF-8 byte cap before decoding. `ingest` at `:65` applies the same cap to new normalized envelope/mapping writes; `_snapshot` at `:188` bounds new snapshots. Canonical `.test_oversized_or_nontext_stored_snapshot_is_rejected_before_decoding` and `.test_oversized_or_nontext_stored_source_json_is_rejected_before_decoding` inspect decoder calls for the actual offending stored value. | Corrected. Limits apply on write and read; the regression proves rejection before parsing the oversized or wrong-type value, not merely eventual checksum failure. |
| Integer `original_bytes` could be coerced through `bytes(integer)` before validation | `context_workflow._load_ingestion` at `context_workflow.py:98` now requires actual nonempty `bytes`, at most `context_data.MAX_BYTES` (256 KiB), before invoking source validation. Canonical `.test_integer_or_oversized_original_bytes_rejected_before_source_validator` stores integer 16 and an oversized BLOB. | Corrected. No integer allocation/coercion is used. The real source validator remains wrapped by the test and must not be called for either invalid stored value. |
| Retained receipt JSON lacked a corresponding predecode boundary | `notification_outbox._checked` at `notification_outbox.py:59`, specifically `:79`, requires null or bounded text before parsing a receipt; exact intent/receipt equality checks remain. Canonical `.test_corrupt_receipt_type_or_size_is_rejected_before_decoding` uses oversized text and a BLOB. | Corrected. Receipt corruption cannot reach JSON decoding first or become an acknowledgement through a recomputed checksum alone. |
| Import quota accounting trusted malformed existing normalized inventory and could misclassify storage corruption as a bad request | `context_workflow.ingest` at `context_workflow.py:65` now loads complete existing rows through `_load_ingestion` before counting their records. Canonical `.test_corrupt_existing_import_inventory_returns_storage_failure` exercises the actual import handler and checks 503 plus unchanged ingestion count. | Corrected. Existing raw/source/capture integrity is checked; no new ingestion is committed on corrupt inventory. |

The seven canonical corruption methods are grouped at
`test_context_http.py:199`, with the receipt and inventory follow-ups at `:279`
and `:292`. Their controlled privileged writes are confined to genuine isolated
memory SQLite stores. These tests do not weaken production foreign keys or
authorize operational database edits.

## Cache safety and integrity review

`storage.lineage_read` (`storage.py:825`) obtains the existing read transaction;
`paper_transaction(write=False)` (`storage.py:924`) holds the store lock, begins a
SQLite read transaction and enforces query-only access. Scan-history readers now
use that boundary rather than holding only a lock around separate reads.

The shared dictionaries use distinct evaluation, Phase 4, context and component
keys. Entries are stored only after the relevant complete validation returns.
The evaluation loader at `candle_lineage.py:87` still checks its retained checksum,
scan/data-mode/reference scope and equality with the separately committed result.
`context_workflow._phase4` (`:129`) still checks committed input/result digests and
the decision reference; it avoids the previously reproduced recursive full-cash
load. `_load_snapshot` (`:251`) still reparses source ingestions, verifies capture
foreign-key references, rebuilds the expected context and requires exact equality.

`notification_outbox._checked_decision` (`:250`) still recomputes every individual
decision and checks each eligible intent. Component reuse does not cache a forged
decision verdict. `validate_context_intent` (`:203`) still reconstructs the
expected body and checks committed cash state, original candidate qualification,
snapshot identity/digest, Phase 4 digest and source/content references.

No global or cross-request validated cache was found. Top-level context and
decision reads create a fresh dictionary inside their locked read scope;
no-connection public loaders do not reuse a supplied dictionary from an earlier
read. Cache forwarding with an explicit connection is an internal trusted Python
interface; HTTP cannot supply it. Enrichment, import, enqueue and preview mutation
paths do not pass a shared cache. The optimization therefore preserves fresh
source validation for each supported application read operation.

## Supported path and actionability review

The inspected path is explicit offline import, retained raw/normalized source,
immutable scan-context snapshot, existing history APIs/dashboard and the existing
local outbox. It does not create an external acquisition or delivery mechanism.

| Contract | Actual source and production-path test locators |
|---|---|
| Request input cannot confer trust, mapping authority or intake time | `server.py:935` accepts only provider/collection/payload; `scanner_engine.py:186` supplies the engine clock and trusted mapping. `test_context_http.TestContextHTTP.test_no_request_can_supply_trust_mapping_or_intake_time` checks the supported HTTP route. The normal local/origin guard runs before dispatch at `server.py:1142` and `:1167`. |
| Qualified source facts remain distinct from independent authority and rights | `context_data.ContextSourcePolicy.qualify` at `context_data.py:162` checks the real fixture signature, scope, dates and separate local approvals; output explicitly leaves independent authority/rights false. `validate_ingestion` at `:390` reparses actual original bytes and requires the separately supplied policy again. `test_context_data` covers policy/signature tampering, revocation, mapping, dates and rights mismatch. |
| Historical context has no future-fact leakage | `context_data.context_for_candidate` at `:329` withholds future facts. `context_workflow._snapshot` at `:188` additionally gates actual local capture time and separates DECISION_TIME from CURRENT_INFORMATION. `test_phase45_integration.TestPhase45IndependentIntegration.test_late_backdated_import_is_excluded_from_decision_time_but_current_view_is_labelled` and `test_context_workflow.TestContextWorkflow.test_future_import_fact_cannot_create_past_conflict` exercise these distinctions. |
| Original candidate, strategy, risk and rank stay immutable | `scanner_engine.enrich_context` at `scanner_engine.py:193` creates only the separate context snapshot/decision. `test_phase45_integration.TestPhase45IndependentIntegration.test_actual_candidate_import_context_api_and_preview_preserve_phase4_result` compares original arrays through actual store/API paths. `.test_rejected_detected_candidate_stays_rejected_with_qualified_context` checks a real detected setup that remains rejected downstream. |
| Missing context remains explicit and optional failure cannot erase Phase 4 | `scanner_engine._attach_context` at `:217` uses MISSING/UNAVAILABLE; `server._handle_context` at `server.py:983` does likewise. `test_phase45_integration...test_legacy_scan_history_reports_missing_context_without_fabricated_records` and `test_context_http.TestActualContextSQLiteFailures.test_actual_sqlite_snapshot_failure_keeps_phase4_and_marks_context_unavailable` cover actual retained history and SQLite failure paths. |
| Qualified context cannot bypass candidate qualification or create live actionability | `notification_outbox._context_qualification` at `:161` requires the original qualified, non-actionable candidate, fresh qualified context and exact identity. `_decision_body` at `:231` additionally checks committed cash state and timing, retaining `actionable=false`, `LOCAL_PREVIEW_ONLY` and disabled real delivery. Unverified/stale/conflicting/rejected cases in `test_phase45_integration.py` retain suppression or warnings. |
| Alert deduplication, retries and acknowledgements preserve their meaning | `notification_outbox.preview` at `:357` validates retained content and attempts before rendering, enforces the existing retry budget and recovers an acknowledged receipt. `test_context_alerts.TestContextAlertLifecycle` covers precommit rollback, acknowledgement loss, three-attempt DEAD, concurrency, restart and rehashed message/decision rejection. The semantic key excludes collection-time churn but includes actual content references. |
| UI and message output remain informational and safe | `public/index.html:1375` clears the prior view, checks context/candidate identity and source qualification, uses text nodes and validated links, and labels current-information scope. `telegram_bot.format_context_alert_html` at `telegram_bot.py:45` escapes dynamic facts and explicitly labels a local preview for a stored candidate. Final current-source browser execution remains a separate coordinator gate. |

No reviewed path promotes a rejected candidate, changes original strategy/risk
fields or calls a real sender from the new context-alert workflow. Existing
stored-signal annotation explicitly remains non-actionable at
`candle_lineage.py:461`. A successful local preview is not message delivery,
live recommendation acceptance, publisher acceptance or evidence of profitability.

## Retained execution evidence and exact review binding

The independent five-case helper reproduced the original failures in
[corrupt_payload_before_01](../evidence/phase45_alerts_corrupt_payload_before_01.json):
five executed, zero passed, eight subtest failures and two errors. Subtest failure
counts are not additional discovered test methods. The separate
[follow-up before receipt](../evidence/phase45_alerts_corrupt_followup_before_01.json)
retains seven executed, five passed, three subtest failures and zero errors for
the receipt/inventory follow-ups alongside the earlier corrected behaviors.

The coordinator's
[focused after receipt](../evidence/phase45_alerts_corrupt_followup_after_01.json)
records **87 executed and passed**, zero failures/errors/skips/unraisable errors,
exit 0. Its five modules are the 17 HTTP/SQLite/corruption cases, context-data,
workflow, alert lifecycle and independent integration suites. This review read
the actual IDs and code paths; it does not infer acceptance from that total alone.

The reviewer independently hashed all 85 receipt source entries: all current
files match `source_after`, and the retained before/after source maps are equal.
The actual retained log hash matches its receipt:
`b38448204fc2e99cd2b03bf398c7d137816633a3b33f3de3a5862ba402d7560d`.
Key reviewed SHA-256 values are:

| File | SHA-256 |
|---|---|
| `context_workflow.py` | `948d6157171a6ad9b5dafe871572e2d6a1d39f18d06916712d7089c91bb95b97` |
| `notification_outbox.py` | `0c0b7ef4f22431d1dbf55dcae0467f73fe3e06160ec7da55e79db5d661443325` |
| `test_context_http.py` | `3a0afaa98cfdb0cef78a72a704e63ae5bffb5e2aa4566199fbffd079b3070f2d` |

This focused receipt does not replace the pending canonical full run, JavaScript
and compilation checks, current-source browser stage, release manifest/exclusion
inspection or final closeout validation. This report makes no assertion that any
pending stage has already passed or that a new accepted archive already exists.

## Remaining gates and scope limits

| Category | Disposition at review completion |
|---|---|
| Confirmed software defects remaining | None identified in this reviewed scope after the recorded fixes. This is not proof that no defect exists elsewhere. |
| Missing in-scope implementation or acceptance work | No further context/cache/outbox/API implementation gap identified here. Coordinator must finish and inspect the final canonical, browser, release and sealed acceptance evidence before declaring phase acceptance. |
| External/provider/rights dependencies | Genuine publisher approval, source rights/acquisition and actual market acceptance remain unavailable. Authored source documents, generated fixture signatures and memory-store consumer execution prove software behavior only. Operators/providers must supply separately authorized genuine evidence for those operational claims. |
| Explicit future-phase work | Broader paper lifecycle, measured performance and final product release acceptance remain Phase 6 under the existing six-phase roadmap. No new phase, milestone score or strategy-performance claim is introduced. |
