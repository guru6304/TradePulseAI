# Astra C03 independent review record

Recorded by the coordinator on 2026-10-26, Asia/Kolkata, from the retained
`/root/rank_review` messages and executed receipts. The reviewer did not author
the rank implementation or edit files during this review. They inspected source;
the coordinator authored the regressions, repaired the implementation and ran
the tests. This record does not substitute for the canonical execution receipt.

| Finding | Reproduction and repair | Independent read-back |
|---|---|---|
| Deleting both result flags and the rank row could make a new scan look like legacy data. | `astra_rank_downgrade_before_20261025_01` failed before repair. The required-history marker now belongs to the retained input/work identity, and ordinary lineage reads reject its missing descriptor. | Reviewer confirmed the repaired input requirement. |
| LONG and SHORT opportunities shared a directionless identity. | `astra_rank_direction_before_20261025_01` failed before repair. The V2 priority policy binds position type to the opportunity key and displays direction. | Reviewer confirmed directional opportunities remain distinct. |
| Backward browser wall-clock movement could extend current-rank display. | `astra_rank_clock_before_20261025_01` failed before repair. The request-duration calculation now uses monotonic elapsed time and expiry remains tied to the server interval. | Reviewer confirmed the timing change. |
| After the newest rank row was deleted, a later scan could append against an older surviving rank. | `astra_rank_order_before_20261026_02` ran three tests: two passed, the append-gap assertion failed. `record` now selects and validates latest committed input-scoped work before append. Reads use the same input selector; mutable result mode cannot hide the latest scan. | Final review confirmed the selector, append guard, matching index and regressions; no further material ordering/predecessor defect found. |

The last repair is at `rank_history.py`'s `_latest_committed`, `record` and
`read_current`; tests cover older valid input, predecessor signal corruption,
append after deletion, result-mode hiding and indexed lookup. The focused
`astra_rank_history_boundary_20261026_01` receipt passes 62 tests. Earlier
sandbox-only failures are preserved separately and are not reproductions of
application behavior.

The reviewer called out an important transaction boundary: rank rows and scanner
results commit atomically with signal/evaluation/outbox effects, while accepted
pending input batches can remain for recovery after a rejected result. The report
therefore does not claim that every database write rolls back.

The accepted scope is offline cash-priority persistence, cross-table source
validation, direction-aware changes, bounded read-only API and expiry-aware
dashboard behavior. It does not establish publisher authenticity, genuine live
feed acceptance, executable recommendations, empirical profitability, F&O ranking,
full product/security review or whole-mission completion. Validation checks one
predecessor's source/base priority rather than recursively auditing all historical
change explanations. Coordinated rewriting of every retained source table is not
prevented by local checksums.
