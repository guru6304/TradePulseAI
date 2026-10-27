# Astra D01.2 production review, 2026-10-27

**Scoped verdict: no remaining material defect identified in the reviewed final
option and benchmark validators.** The numeric-literal defect found in this
review was reproduced, repaired by the production owner and independently
rechecked. This supports continuing verification of the bounded offline slice;
provider, research, execution and whole-project acceptance remain separate. Canonical
verification remains the coordinator's separate step.

Reviewer: `/root/rank_store`. I authored the original option observation tests
and their numeric-string regression, but authored neither `option_observations.py`
nor `benchmark_observations.py`. The coordinator subsequently added the offset
and native-literal option regressions. The intended separate reviewer stopped
because of a usage limit without delivering a code review. Consequently this is
a second-person production review with disclosed test-author overlap; it is not
an independently authored option test suite. I did not author the benchmark
tests. No production or test file was edited during this review assignment.

The review read both complete production modules, the relevant normalized-master
and replay contracts, the [D01.1 inventory](astra_d01_contract_inventory_20261026_01.md),
and the retained focused receipts. It concentrated on exact option identity,
request scope, preserved source bytes, absent/null/zero values, local clocks,
units, OI baseline semantics, benchmark bounds and non-actionability. The only
execution by this reviewer during this assignment was the six-case pure authored
numeric diagnostic below; no new unit or integration suite was run by this reviewer.

## Material defect found and verified correction

Default `json.loads` floating-point conversion changed native numeric literals
before `_number` could validate them. Three invalid inputs were accepted:

| Native JSON literal | Field | Observed incorrect value before repair |
|---|---|---|
| `1e-999` | IV | `0.0`, despite nonzero input |
| `1.00000000000000001` | Volume | `1`, despite fractional input |
| `9007199254740990.5` | OI | `9007199254740990`, despite fractional input |

This defect differed from numeric-string underflow, which had already been
corrected: the native JSON decoder discarded the distinction first. Retaining
raw text alone did not make the derived `raw_value`/`numeric_value` truthful.

The [before diagnostic](../evidence/astra_d01_review_numeric_literals_before_20261027_01.json)
retains **3/6 expected behaviors** and the actual accepted values. The other
three cases were controls: native overflow was rejected, while ordinary `0.1`
and the smallest positive float represented by `5e-324` were accepted.

The owner added a bounded `parse_float` callback. It validates the original
decimal token before conversion and rejects a change in its canonical decimal
value after float conversion. It keeps the existing public value types, preserves
the original bytes and does not claim a new normalization policy. Current native
underflow raises `INVALID_NUMERIC_VALUE`; the two fractional-to-integer cases
raise `JSON_NUMBER_PRECISION_LOSS`. The same six cases in the
[after diagnostic](../evidence/astra_d01_review_numeric_literals_after_20261027_01.json)
now establish **6/6 expected behaviors**, with reviewed source unchanged during
the run. Accepted controls remain non-actionable and have no normalized IV.

The [diagnostic helper](../evidence/astra_d01_review_numeric_literals_20261027_01.py)
uses authored master and response fixtures. It does not invoke a test runner,
provider, operational database, adapter or execution engine. It records hashes
before and after each run and refuses to overwrite its output path.

The coordinator separately reproduced the option clock accepting malformed
`+05:99` offsets and corrected its strict offset-minute bounds. The
[offset-before receipt](../evidence/astra_d01_offset_before_20261027_01.json)
shows the option test failed and the benchmark test passed. The benchmark
validator already rejected that malformed offset; this report does not attribute
that defect to it. Final option source also checks timezone conversion overflow.

## Current source checks and qualification boundaries

- **Option identity and scope:** the supplied master is rebuilt from retained
  original bytes and compared in full, including provider and declaration
  metadata. Only the dated normalized declaration status is accepted for
  inspection. Selected options require exact unique token/underlying/expiry/
  strike/side, active status and coverage on the receipt's IST date. Underlying
  identity comes from the same master; its declared interval already covers the
  option interval. Native undated masters cannot satisfy this interface.
  V3 missing responses do not hide invalid requested contracts because every
  requested identity is resolved first. Outer V3 display labels do not replace
  nested instrument tokens. Duplicate and unsolicited tokens fail.
- **Bytes, fields and clocks:** raw response text/hash and source locators are
  retained. JSON duplicate keys, nonfinite numbers and invalid precision are
  rejected. Absent, null and observed zero remain distinct. Master capture must
  precede receipt, which must precede local availability and decision cutoff.
  These are declared local clocks; no exchange observation or Greek calculation
  time is inferred. IV/Greek/quantity values retain unavailable unit contracts.
  V3 `cp` remains previous close price rather than previous OI.
- **Depth and OI:** displayed levels are bounded, ordered and uncrossed; no volume
  substitutes for depth. Only an explicit synthetic underlying-unit declaration
  can yield size coverage, and `executable_depth` remains false. OI observations
  require matching full identities, source revisions and quantity units, valid
  session clocks, prior availability and a fresh current observation. Intraday
  alignment is explicit. `PRIOR_CLOSE` requires the declared preceding session
  and exactly 15:30 IST, but does not establish that date as the genuine previous
  trading session. `prior_close_authority` remains `NOT_ESTABLISHED`. Unknown
  baseline semantics, unknown units and unverified captures yield no OI delta;
  synthetic arithmetic never becomes execution or historical acceptance.
- **Benchmark windows:** asset and index roles, price units, unadjusted prices,
  distinct declared identities, exact equal five-minute windows and a common
  weekday session are checked. Bars are complete, contiguous, chronological,
  available by decision and sufficiently recent. No sorting, intersection,
  interpolation or fill hides gaps. OHLC, finite descriptive returns and asset
  volume are checked. Metadata is bounded by depth, node, text and serialized-byte
  limits; option raw/master bytes and declaration metadata are also bounded.
  Source hashes cover the supplied benchmark envelopes.
- **Benchmark identity limitation:** the benchmark function validates explicit
  identity declarations and role consistency, not a dated canonical master or
  publisher authority. Its fixtures deliberately use authored identifiers.
  Neither its input hash nor descriptive relative return supplies a qualified
  benchmark, sector constituent map, research admission or live ranking factor.
  Its output explicitly remains in synthetic or unqualified scope.

All reviewed option captures and OI comparisons remain `eligible=false`,
`actionable=false` and `historical_replay_allowed=false`. Depth remains
non-actionable/non-executable; benchmark output remains non-actionable,
ineligible and without empirical acceptance. No path in either module sends
orders, notifications or provider requests. The existing historical option
runner still requires its separate replay dataset and qualification contract;
native snapshots are not converted into bid/ask bars or prior-close evidence.

## Evidence and exact final source

The coordinator's [final focused receipt](../evidence/astra_d01_final_focused_20261027_01.json)
records **56/56 passing tests**, comprising 31 option tests and 25 benchmark
tests, with zero failures/errors/skips. This is retained coordinator execution,
not an additional suite run by this reviewer. Its production hashes agree with
the final diagnostic and readback below. These results are synthetic validation,
not genuine data acceptance. Earlier failures remain retained.

| Reviewed file | Final SHA256 |
|---|---|
| `option_observations.py` | `7133afeb3331ab8bf84490d97c55c1f41df6c7b7afda34f416f36a551a1eda48` |
| `benchmark_observations.py` | `4f749f4d112a94a18ba9ae810d17a01b5fe71d4ee4d5b2d17a5300e9538f66fa` |
| `test_option_observations.py`, overlapping test authorship disclosed | `4eeac0c460d3195fe937a72c93ed51200907b06f9f0dd19d32e4b2c0b8f676d5` |
| Review diagnostic helper | `fb98f4e3ce0dadb6ef7ba2afb1983a1942cc746355f98c67e010e0267bd44a48` |
| Review before receipt | `c4cfdec08a551d0d6e0a1b398d675c8eb011f3d64549e1a08fac42832bf05f0f` |
| Review after receipt | `04083fec00d8348b67e1706d093c864f437435024500658a6a3571ae3626ddd4` |

Review-created files are this report, the one diagnostic helper and its unique
before/after receipts. No saved configuration or existing evidence was changed;
no operational database, provider, broker account or messaging service was used.
The separate HTTP latency probe and its timing verdict were outside this review.
