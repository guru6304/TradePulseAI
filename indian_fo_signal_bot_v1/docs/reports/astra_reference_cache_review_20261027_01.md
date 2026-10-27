# Astra scanner reference cache and release review, 2026-10-27

**Narrow review verdict: no remaining material defect identified in the reviewed
scanner metadata-cache correction or explicit local-helper release exclusion.**
This is a source review, not whole-product acceptance or a general latency
guarantee. Current canonical verification remains the coordinator's separate
responsibility.

**Ownership and independence.** `/root/rank_review` independently read the
coordinator's changes in `scanner_engine.py`, their four tests in
`test_astra_scan_references.py`, and the release policy/tests. No tests were run
and no production/test changes were made during that independent read-back.
The reviewer separately authored the four-line conditional recursion correction
in `candle_lineage.py:69-75` and the three tests in
`test_astra_evaluation_reads.py`; those changes are explicitly **not independently
reviewed by their author**. The coordinator reports separately reviewing their
semantics and running integration. This report is the only file written for the
final independent-review assignment.

**Scanner metadata boundary.** In [scanner_engine.py](../../scanner_engine.py),
the cache is created at line 846, after any durable retry has selected its retained
input and reference clock (lines 830-841). It belongs to that invocation; there
is no global, request-spanning or database verdict cache. Each lookup at lines
847-858 recomputes a digest of the raw candle content, including identity and
timestamps. Mutated inputs therefore miss the prior entry. Returned references
are deep copies at lines 858 and 871, so changes to one trace's identity or
timestamp list cannot corrupt another trace or the cached value.

Metadata still comes from `filter_completed_candles` (line 859), is bound to the
current run/provider and retained batch IDs, and retains
`source_authenticity=NOT_ESTABLISHED` (lines 861-865). Strategy evaluation remains
separate at line 876. The existing live stream/freshness checks before signal
storage, final result commit and delivery remain separate calls; the cache does
not grant authority or replace them. This review found no additional mutation,
freshness or identity hazard introduced by this reuse for the supported input
contracts. It does not establish that arbitrary future evaluator side effects
are safe.

**Corrected compatibility finding.** The coordinator identified, and this review
confirmed, that unconditional `digest(raw)` rejected supported `datetime`
timestamps before the existing candle normalizer could convert them. The
retained [before log](../evidence/astra_scan_datetime_before_20261027_01.txt)
shows four strategy errors and an unexpected `COMPLETED_EMPTY`; the single
regression failed. This was a real compatibility regression, not evidence that
the market contained no candidate.

The current correction at lines 849-855 catches `TypeError` and `ValueError`
from the optional raw fingerprint and sets it to `None`. Both cache lookup and
insertion require a non-`None` fingerprint (lines 857 and 869). Unfingerprinted
input therefore undergoes normal validation on every call; the normalized
evidence still must pass `digest(rows)`. This preserves accepted normalization
without weakening the validator or caching an unavailable fingerprint. The new
test at `test_astra_scan_references.py:105` exercises actual scanner evaluation
with datetime input. The other tests inspect normalization count and exact
retained references, separate mutable outputs and subsequent scans, and input
mutation between evaluators.

**Release exclusion.** [release_management.py](../../release_management.py):35
classifies exactly `verify_live_quick.py` as `LOCAL_ONLY_MODULES`. The fixed
`CORE_MODULES` manifest, `_bundle_path_allowed` at line 191, and `build_bundle`
at line 196 continue to include only explicitly permitted files. The helper
does not match the test-module exception and cannot enter the bundle through
this classification. `test_release_management.py:114` requires the complete
remaining root-module inventory to equal the core allowlist and requires the
two classifications to be disjoint. `test_release_operations.py:26` explicitly
asserts the helper is absent from the generated ZIP. This exclusion preserves
the operator-owned helper in the workspace; it does not validate its behavior,
import it, execute it or turn its output into acceptance evidence. The reviewer
did not access saved environment files or operational databases, or initiate
provider/API/authentication requests.

**Separately authored traversal correction.** The original recursive walker
called itself for every scalar value in a retained evaluation, although only
dictionary/list containers can contain nested `source_reference` fields. Both
loops now recurse only into those containers. Every dictionary is still checked,
including dictionaries in arbitrary extension fields, nested lists and reference
objects themselves. There is no new cache, field allowlist, payload mutation,
database write or changed invalid-reference error path.

The reviewer executed the three new tests against genuine retained evaluations
created by the existing explicitly simulated scanner fixture in an in-memory
database. Tests check bounded recursive work, equal returned/persisted payloads
and unchanged read-transaction write counts; rehashed invalid run/batch references
under arbitrary extension/list nesting; and a valid nested reference followed
by later rehashed corruption that must be revalidated. These are offline test
evaluations, not genuine live-market evidence.

The clean [before receipt](../evidence/astra_evaluation_reads_before_20261026_03.json)
has two passes and one expected reproduction failure, with zero errors. The
[after receipt](../evidence/astra_evaluation_reads_after_20261026_01.json)
has **3/3 PASS**, zero failures/errors/unraisable errors. For the same payload
shape of 3,844 containers and 33,628 scalars, recursive calls dropped from
37,472 to 3,844. This demonstrates less traversal work; it is not a timing SLA.
Earlier before stages `01` and `02` remain retained: `01` included incorrect
test expectations about the loader's outer error wrapper, and `02` ran while
the coordinator's scanner change lacked its `copy` import. Neither is used as
the clean comparison baseline.

**Coordinator executions, read back separately.** The coordinator's retained
[integration log](../evidence/astra_latency_integrated_20261027_01.txt) records
129/129 PASS before the datetime fallback. The later
[datetime/integration log](../evidence/astra_scan_datetime_after_20261027_01.txt)
records 11/11 PASS after it: four scanner-reference tests, three evaluation-read
tests and four HTTP tests. These were not executed by this reviewer. They do not
replace a canonical current-source run or establish whole-product completion.

**Source read-back SHA256 values.** These bind the reviewed/authored bytes at
report creation; subsequent changes require their own verification.

| File | SHA256 |
|---|---|
| `scanner_engine.py` | `a75867422e30b5dd6b140069ab465c1055042c93713bd66f63bee2cbd8b94840` |
| `test_astra_scan_references.py` | `396747f0ab96116fbc8cc511c7cd97a022c8167efc1919bdd9705eb2b910210b` |
| `release_management.py` | `6f9640ce2ee7bc4d834b8a9dd7a0a6f1eb4834e38b2b67231a496969ab80ea2c` |
| `test_release_management.py` | `6f22ca8316099514c5a526f4c8f779cda5569183a824446120a8da7e4b891c16` |
| `test_release_operations.py` | `969efafa3a732bb38c87971c6b9d282e19e41156288a54e8d7d3ef9419a35bd6` |
| `candle_lineage.py` (reviewer-authored correction) | `1ec634432fa577718d79fed70ee6743412464e8b4e2d5a40881ab14058670437` |
| `test_astra_evaluation_reads.py` (reviewer-authored tests) | `87bca52b267140a797115d975bde1d12171c03e4a96fb506c18175ded6e19093` |

This scope establishes specific local integrity and compatibility properties.
Live provider acceptance, strategy profitability, historical research authority,
F&O execution readiness and the remaining master mission are separate claims.
