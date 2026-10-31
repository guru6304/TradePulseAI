# Independent backend next-task review — 2026-10-29

Read-only source review after the instruction to stop UI work. No application imports, provider requests, environment reads, operational database access, or code/test edits were performed. Earlier UI review is superseded by that instruction; no additional UI acceptance is recommended here.

## Recommended bounded task

Harden the read-only paper-ledger API against corrupted retained position/recovery payload identity. `storage.py:query_paper_ledger` scopes its physical LEFT JOIN by account and entity ID and validates decoded payload type, size and finite serialization. It does not compare the returned position/recovery JSON's `account_id` and `position_id`/`decision_id` with the requested account and selected entity ID. Consequently, a corrupted but otherwise valid JSON object can be returned as HTTP 200 retained evidence under a conflicting wrapper identity.

This is a source-established validation gap, not a reproduced runtime incident. The proposed fix should use the existing `MALFORMED_OR_OVERSIZED_PAPER_RECORD` failure route, which `server.py:_handle_paper_portfolio` converts to generic HTTP 503 `RECONCILIATION_REQUIRED` without echoing retained bodies. Keep valid page/cursor semantics and read-only behavior unchanged.

Use collection-specific checks. Position and recovery records have embedded identities. Event payloads are different: `paper_portfolio.py:_event` stores command/result JSON separately from event identity columns, so requiring embedded `account_id`/`event_id` for all collections would incorrectly reject legitimate events. Candidate decisions need their writer contract checked separately before extending validation.

## Meaningful validation

Use temporary authored SQLite stores only. Demonstrate that valid position/recovery pages retain their normal IDs, then independently corrupt embedded account and entity IDs while leaving physical join columns intact. Require failure without returned payload bytes, no financial mutations, and no cursor/account cross-contamination. Exercise the HTTP handler's generic 503 mapping. Preserve existing valid event pages as a regression case. Retain ordinary malformed JSON/oversize and cursor-boundary coverage already present in the project rather than duplicating it.

This task strengthens local API integrity without admitting D01 observations into runtime, inventing broader B01 strategy rules, or requiring provider/live calls.

## Cleanup review already completed

The proposed cache cleanup script was inspected before application. It confines targets to the 105 inventory-listed immediate bytecode children of two approved project cache roots, excludes tracked paths and reparse chains, validates every target before deleting any, and rechecks each target immediately before literal nonrecursive removal. Empty directory removal uses `Directory.Delete(path,false)`. Its dry-run default and exclusive receipt/log creation support reviewability. Final deletion/preservation receipts were not reviewed in this report and no deletion was performed by this reviewer.
