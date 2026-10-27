# Astra D01.2 offline observation acceptance — 2026-10-27

**VERIFIED_COMPLETE within pure offline observation mechanics. Master mission incomplete.**
Recorded UTC: 2026-10-27T08:44:20.480013+00:00; project timezone Asia/Kolkata. HEAD `4030b39c97a78b9ab3e8885a13d80e193dfcc73e`.

`option_observations.parse_option_capture` separates Upstox V2 chain, Upstox V3 Greeks
and Angel Greek schemas. It retains original UTF-8 text/hash, exact request, row paths,
field presence/raw values and master metadata. Rebuilding the master from its original
bytes binds unique dated contract and underlying declarations. Local master/receive/
availability/cutoff ordering is checked. These are declarations, not publisher authority.
V3 identity uses nested instrument_token, never its display-label dictionary key.
Missing, null and observed zero remain distinct. Endpoint IV/Greek/quantity scaling and
source clocks stay unavailable; no local receive time is substituted. Precision loss,
fractional counts, malformed/duplicate data, conflicting identity and future inputs reject.
Native masters without dated declarations remain unsupported by this interface.

`inspect_depth` checks positive ordered prices, integral quantities and uncrossed top of
book; only explicit synthetic underlying-unit fixtures compute size coverage. It never
claims executable depth or a fill. `compare_oi` requires exact matching identity/revision,
units, source references, availability and clocks. Unknown prev_oi semantics do not become
prior close. Declared synthetic prior-close arithmetic requires the explicitly named earlier
weekday and exact15:30 IST; a qualified trading calendar and source authority remain absent.

`benchmark_observations.align_benchmark_windows` checks distinct declared EQ/index roles,
completed contiguous five-minute bars, exact equal past-only windows, OHLC/volume, availability,
freshness and adjustment convention. It preserves canonical input hashes and reports only
descriptive first-close/last-close returns. It does not resolve a canonical dated benchmark
master, verify a holiday calendar, establish sector constituents, or create cash lineage.
No sorting, intersection trimming, forward fill or factor promotion occurs.

All outputs remain non-actionable and ineligible. The modules have no transport/storage
entry point and are not wired into adapters, scanner ranking, paper execution or the UI.
Existing option replay actually rejects both a capture and its relabelled replay-shaped
form. No Option Apex, cash ordering, strategy formula, provider selection or settings change.
Bounds include2MiB raw option bodies/master artifacts,100 legs,50 V3 request keys,30 depth
levels, bounded metadata traversal, and strict offset clocks. Benchmark windows additionally
require a single weekday session; the nominal375-row limit cannot admit out-of-session bars.

| Verification | Executed result / limitation |
|---|---|
| Final focused | 56/56 PASS, astra_d01_final_focused_20261027_01.json |
| Existing-contract integration | 108/108 PASS, astra_d01_integrated_20261027_02.json; predates final numeric/clock repairs, covered by canonical below |
| Canonical current source | 1184/1184 Python, 38/38 Node, 101 compilation checks; exit0; no failures/errors/skips/unraisables |
| Source freeze | Exact source_before equals source_after; receipt master_astra_d01_20261027_01.json |
| Review | Production review by rank_store, who authored the option tests and declares that limitation; root reviewed benchmark code/tests. No product-wide sign-off |
| Preservation | 727 prior document/evidence files and confirmed external source/config hashes unchanged; previous handoff bytes archived |

Retained failures: first options run26/27 from an absent-field path test assertion; numeric
string underflow/exponent regression failed before repair; native JSON number regression
failed three subcases before the review fix; invalid offset regression failed for options
while benchmark already rejected it. The sandbox integration run88/108 had25 error events,
including temporary-file/SQLite access and cleanup errors; permitted rerun108/108 passed.
No timeout or trust rule was weakened. Review diagnostics retain native literal before/after.
All machine receipts, including failures, are preserved. The final canonical is the authority
for current-source totals; old C03/B01 receipts are historical boundaries.

Production files: option_observations.py, benchmark_observations.py; tests with corresponding
test_ names; release_management.py and test_bot.py registration. No new retained release ZIP.
No environment edit, operational DB access/migration, provider/auth request, notification,
real order, Git mutation, public launch or empirical performance claim. Owner-confirmed
broker/config/app-env/live-helper changes remain preserved; helper was never run or imported.

Next approved offline action: E01.2b: retain versioned production UI assets and extend the existing CDP harness to render unchanged dashboard HTML with verified local assets for visual/mobile/accessibility checks, using astra_browser_production_assets_plan_20261027_01.md; no provider calls.
D01 live adapter/capability admission still requires dated unit/clock/source policies and
separately authorized genuine inputs. Broader paper triggers, authentic research/live
acceptance, full security/operations and commercial rights remain open.

Schema evidence: [Upstox chain](https://upstox.com/developer/api-documentation/get-pc-option-chain/),
[Upstox Greeks](https://upstox.com/developer/api-documentation/option-greek/),
[Angel moderator announcement](https://smartapi.angelone.in/smartapi/forum/topic/4254/announcing-option-greeks-api-for-smartapi-users),
public documentation reconfirmed2026-10-27. The Angel announcement is historical schema
evidence; its deleted-topic notice and inaccessible main documentation preclude claiming
current entitlement. See the preserved D01.1 inventory for exact source applicability.
