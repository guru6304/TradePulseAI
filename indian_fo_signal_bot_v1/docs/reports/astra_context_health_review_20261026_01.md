# Astra independent context-batch and health-read review

Date: 2026-10-26, Asia/Kolkata. Reviewer: `/root/rank_review`.
Verdict: **NO MATERIAL INTEGRITY OR COMPATIBILITY DEFECT FOUND IN THE REVIEWED CHANGES.**

This was a source and regression-test inspection of the narrow latency repairs.
The reviewer did not implement the repairs, edit production/tests, execute tests,
read environment files or operational databases, or make provider/auth/API calls.
This new report is the only file written for this review. It does not certify
global performance, browser acceptance, production load or live market behavior.

## Context-batch boundary

Reviewed `notification_outbox.py:275` (`_enqueue_context_decision`), `:303`
(`_checked_context_submission`), `:308` (`enqueue_context`) and `:316`
(`enqueue_context_batch`), with the store wrapper at `storage.py:918` and scanner
consumer at `scanner_engine.py:193`.

The batch opens one existing `paper_transaction(write=True)` and creates an empty
private `read_cache` inside that context. The supplied context snapshot is checked
against the retained snapshot, reconstructed raw-source context and Phase 4
evaluation. The cache is not supplied by an HTTP caller, stored globally or
returned to the caller. No validated verdict survives the operation. The cache
reuses only the immutable input reconstruction within this locked transaction.

Every candidate still passes through `_enqueue_context_decision`: qualification,
committed-scan state, reference time, deterministic decision identity and semantic
context are recomputed. Existing decisions use `_checked_decision`; eligible
existing intents use `validate_context_intent`. The retained original content is
therefore checked even on idempotent retries. The single-candidate entry point
uses the same private writer and retains its external calling contract.

The existing transaction implementation at `storage.py:930` uses the store lock
and `BEGIN IMMEDIATE` for writes. Exceptions propagate through rollback. A failure
after writing an eligible intent or an earlier decision rolls back the entire
batch of new decisions and intents. Batch iteration preserves the authenticated
snapshot candidate order. No provider request or notification transport occurs
inside this transaction.

The reviewer inspected `test_astra_context_batch.py`, including actual
multi-candidate scanner/storage use, deterministic reconstruction counts,
idempotency and order, caller-modified snapshot rejection, source/evaluation
changes between calls, rehashed existing-decision and intent corruption, and
failure after a preceding decision or new eligible intent. These are test-source
observations, not executions performed by this reviewer.

## Preview and recovery boundary

`scanner_engine.enrich_context` now finishes the decision batch before iterating
over local previews. It retains the Telegram dry-run and disabled-scheduler checks.
`notification_outbox.preview` opens its own transaction and revalidates the
existing intent before recording a preview; it does not inherit the batch cache.

A preview failure can occur after all decisions and pending intents have committed.
The caller may consequently report context unavailable while retained pending
intents await an explicit retry. This is a recovery boundary, not an atomic
decision-plus-preview guarantee. It preserves truthful pending state and permits
idempotent recovery; no real delivery is established. Do not describe the batch
as rolling back a previously committed preview or the earlier context snapshot.

## Health read boundary

Reviewed `readiness_policy.py:116` (`live_acceptance`), `:130`
(`live_acceptance_for_symbols`), `storage.py:1298`
(`load_live_acceptance_evidence`) and `server.py:261`.

The health helper takes one reference clock and opens one fresh `lineage_read`
context for the configured symbols. It still invokes the existing acceptance
receipt validator separately for each symbol. The new optional connection
argument only borrows that context's connection: the loader neither closes nor
commits it. The owning read context retains connection cleanup, the store lock,
SQLite read transaction and query-only behavior. No verdict cache was added.

Each later health request rereads the retained evidence. Missing receipts remain
unaccepted; malformed individual receipts remain unreadable; failure opening or
closing the shared read context returns unavailable verdicts. The server's overall
acceptance aggregation still requires a nonempty configured universe and every
symbol accepted. The change does not promote missing diagnostics, reclassify
offline fixtures or bypass current receipt expiry/scope checks.

The reviewer inspected `test_astra_health_reads.py` for shared connection identity,
per-symbol equivalence to the existing validator, later malformed/deleted receipts,
missing storage and failed read context. No test was executed during this review.

## Evidence and limits

The coordinator separately reported **104/104 combined context, health, ranking
and HTTP integration tests passed, with no errors**, after these repairs. That
execution result is root-reported evidence; this reviewer has not independently
rerun or certified its receipt. Instrumented timing and the final canonical
current-source verification are owned by the coordinator and were still in
progress when this report was written.

The implementation removes repeated context reconstruction within a batch and
repeated connection setup for a health universe. Source inspection supports those
specific reductions. It does not establish a universal latency bound, throughput
improvement under production load or freedom from all future HTTP timeouts.
