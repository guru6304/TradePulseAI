# E01.2c next task: browser verification of existing pagination

Prepared 2026-10-29, Asia/Calcutta. **READ_ONLY_PREPARATION**. No new browser run,
application/test edit, database access or provider request. This plan does not
change the current E01.2b acceptance boundary.

The narrowest next task is to exercise the existing signal and scan pagination
with actual browser fixtures. Implemented controls should be verified before any
redesign. Full paper-ledger navigation is a separate, currently absent UI feature.

## Current source contracts

- `public/index.html:getSignalFilterParams` (line1404) sends `limit`/`offset`
  and optional filters. Page sizes10/20/50 already exist. State defaults to20;
  `renderSignalCards` computes displayed ranges and previous/next availability.
  Filter/page-size changes reset offset0; previous/next handlers use the current
  limit (lines2608–2640). Symbol input has a300ms debounce.
- `loadScanRuns`/`renderScanRunsTable` (lines2254/2307) use15-row pages and a
  status filter. Scan filter resets offset0; controls already exist.
- `server.py:_handle_signals`/`_handle_scans` and
  `storage.py:query_signals`/`query_scan_runs` provide bounded offset pages with
  `items`/`total_count`. These are existing retained-data reads.
- The actual-assets `astra_browser_assets_verify_20261029_01.py` fixture returns
  the same two signal rows without implementing query pagination and returns
  zero scans. Its health fixture has no `paper_account_id`, so it does not render
  a configured paper journal. Passing that harness does not prove page traversal
  or browser rendering of paper accounting.

## Exact next implementation and acceptance

Create a new, separately named fixture helper from the retained actual-assets
CDP harness. Keep production HTML unchanged initially. Add deterministic datasets
of45 signals and31 scan runs, apply supported filters and `limit`/`offset`, and
record raw request queries plus returned row IDs. Retain a before receipt before
repairing any reproduced production defect.

Use native keyboard activation and inspect visible rows/range text/button state:

1. Traverse first, middle and final pages; move backwards; confirm correct IDs,
   no duplicate/omitted rows within the frozen fixture, and correct disabled
   boundary controls. Verify page sizes10/20/50.
2. Change signal filter/page size and scan status from a later page. Confirm the
   request resets offset0 and focus remains on the control the user used.
3. Hold an older request, complete a newer request with a different filter URL,
   then release the older response. Verify current rows, range and focus remain
   consistent with the newer filter. Keep CDP event pumping while a response is
   held; avoid identical-URL browser request serialization.
4. Exercise empty results, a shrinking total while on a later page, malformed
   responses and503. Require truthful visible range/error state and keyboard
   recovery. Current range arithmetic can produce a start greater than the total
   if offset exceeds a shrinking total; this is a static candidate to reproduce,
   not a newly verified runtime defect. Do not silently invent a page or cache
   old data to satisfy the test.

Check desktop and320px widths first. Reuse cached asset/license validation,
request interception, per-stage immutable receipts, source hashes and cleanup.
GET/HEAD only may reach the fixture; no scan, paper observation or order action.
Add focused Node regressions only for reproduced application changes. Run the
canonical suite after those changes, rather than repeating it for fixture-only
preparation. This remains authored-fixture acceptance, not real backend/LIVE or
full accessibility certification.

## Paper journal boundary and later extension

`renderPaperJournal` (line1172) intentionally previews at most40 rows per
collection, displays retained totals and points to `/api/paper-ledger` when
truncated. Existing Node tests cover unsafe text, absent trigger data, stale mark
withholding, reconciliation failure and partial previews (lines530–588).
`loadStoredReports` requests an explicitly attached account only. Preserve these
semantics and do not make the preview look complete.

The backend already has keyset pages: `server.py:_handle_paper_portfolio`
(line819), `storage.py:query_paper_ledger` (line1030), `items` containing
`sequence_id`/`entity_id`/`payload`, `next_cursor` and `through_sequence`.
Limits are1–200, cursors bind account/collection and pin membership, and row
contents can still change. `test_phase5c_recovery.py` already tests stable pages,
append membership, cursor validation and GET/HEAD without financial mutation
(lines365–496). Cursors are not authorization tokens.

A later browser fixture should first supply an explicit fixture account and
synthetic reconciled portfolio to verify the existing bounded preview, long IDs,
hostile text, unavailable marks and failed/late reports. Adding a collection
selector and cursor navigation to the UI should be its own implementation task,
reusing this endpoint and retaining the preview. No such UI was implemented or
accepted by this preparation.
