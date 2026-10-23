# Phase 4 independent implementation QA — 2026-10-23

**Independent focused result: 20/20 PASS.** This report covers the new offline implementation mission, which explicitly authorizes Phase 4 engineering. It supersedes this worker's earlier read-only task scope; historical readiness reports remain unchanged. The coordinating report owns the final engineering verdict, canonical full-suite validation and release inspection.

## Ownership and safety

This worker authored `test_phase4_recommendations.py`, this new report and the exclusive offline contract-example scripts/artifacts described below. At the coordinator's explicit instruction, it also executed the shared focused runner, which created new exclusive JSON receipts and text logs under `docs/evidence/phase4_implementation_focused_` for stages `independent_qa_01`, `breadth_before_01` and `independent_qa_02`. It did not edit production files, existing tests, configuration, previous reports/evidence or release archives.

All new scanner fixtures use SQLite `:memory:`. `test_bot` supplies the established credential-free configuration bootstrap. The suite forbids `urllib.request.urlopen`, `socket.create_connection` and socket connection calls; the shared runner additionally applies the canonical external-network guard. Feed objects are explicit offline test doubles. They exercise the real provider adapter's validation, canonical identity binding, scanner, unchanged strategy rules, sizing, lineage and existing API handlers; they never establish actual market acceptance. No application listener, scheduler, broker authentication/request, account operation, order or Telegram transmission ran. No private database or `.env` content was inspected by this worker.

## Exact focused verification

Executed from the application directory:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs\evidence\phase4_implementation_focused_20261023_01.py --stage independent_qa_02 test_phase4_recommendations
```

The command returned **exit 0**: 20 executed, 20 passed, zero failures, errors, skips or unraisable exceptions. The log records **1.461 seconds**. ResourceWarnings were errors. The receipt's complete source snapshots are identical before/after the run; this worker independently compared them and verified the actual log SHA256 against its recorded checksum. The preceding 19/19 run at stage `independent_qa_01` remains preserved; the twentieth regression was added only after a newly reproduced breadth defect.

| Artifact | SHA256 |
|---|---|
| `test_phase4_recommendations.py` | `61e83d7cb03b17d8996684754ac6aca643f6bea3449429f88aed454e44891ea7` |
| Focused log `phase4_implementation_focused_independent_qa_02.txt` | `bf88f53018f18914c524ef2a7f805c94654e0331f83e6a9d41184e1a5bccf5b4` |

The focused receipt binds the actual application source present during this run. Any subsequent production correction requires the coordinator's final strict verification; this report does not claim that a focused run validates untested later edits.

## Reproduction and regression results

The initial independent post-evaluation disconnect test reproduced a real output race: the actual order-block evaluator detected a fixture setup, the attached feed changed to `DISCONNECTED` with `live_signal_allowed=false`, and the previous scanner still committed one candidate instead of raising `BrokerDataError`. The single-test run returned exit 1 with `AssertionError: BrokerDataError not raised`; an initial six-test run had five passes and that same failure. The coordinator retained the before/after evidence under `phase4_implementation_focused_disconnect_before_01` and `_after_01`.

The scanner now rechecks attached-feed eligibility along with cached candle age before persistence/output and around the final transaction boundary. Independent regressions pass for disconnect immediately after actual strategy detection, quality degradation while the socket still reports LIVE, disconnect after a staged signal write, and disconnect at the final `before_result_commit` checkpoint. These cases leave zero committed signals, scan results and notification intents. A disconnect after commit preserves valid historical candidate records while suppressing notification preview and returning current readiness as false.

The strategy worker separately reproduced an existing candidate generated without the current 09:15 bar. Its correction validates the data required for session VWAP rather than reducing strategy warm-up or filling missing data. This worker independently tested the real scanner with a fresh contiguous 09:20 tail that still has sufficient flat warm-up: it now reports `UNAVAILABLE` / `SESSION_START_COVERAGE_MISSING` for order-block and VWAP rules, with no candidate. This worker did not independently execute the strategy worker's pre-fix counterexample.

This worker then independently reproduced the related universe-breadth defect. The focused command with `--stage breadth_before_01 test_phase4_recommendations.TestPhase4IndependentRecommendations.test_partial_session_peer_cannot_contribute_invented_vwap_breadth` returned exit 1: one test, one failure, no errors/skips/unraisable exceptions, stable source. A full 09:15/09:20 fixture peer correctly contributed one advance; adding a peer with only 09:20 incorrectly raised advances to two. The preserved failing log SHA256 is `ce701d7f0ef3c1f0a2a074ec790abc001b0f61f27e8cb80c902203c96791725b`. After the coordinator added the opening-coverage check to `_compute_universe_breadth`, the final 20-test run proves the full-session comparator still counts, the partial peer is excluded, and partial-only input yields unavailable breadth. No replacement breadth was invented.

Supertrend's insufficient-history and fully warmed scanner paths are covered independently. The positive test uses the original existing SBIN fixture sessions, more than 200 completed bars and the existing 10:35 evaluation clock. The negative test retains only 20 completed observations plus a forming tail; it cannot become a candidate. The feed worker owns the separate bounded-buffer/recovery change and its evidence; this scanner test alone does not prove feed retention capacity.

Metadata corruption tests alter persisted evaluation JSON, then repeat the attack with a correctly recomputed payload checksum. Both existing signal-history and scan-history route handlers return HTTP 503 without serving inconsistent evaluation fields. These assertions exercise checksum validation and agreement with the independently retained committed cash result, not just JSON parsing. The coordinator also corrected `_handle_scans` exception classification so `PersistenceValidationError` cannot be mislabeled as an ordinary invalid query.

## Requirements-to-code-to-independent-test matrix

The test locators below are methods of `TestPhase4IndependentRecommendations` in `test_phase4_recommendations.py`. Source function names are stable locators; final source hashes belong to the coordinator's canonical receipt.

| Requirement / gate | Inspected implementation contract | Independently executed coverage |
|---|---|---|
| A: qualified completed input | Existing Angel adapter stream attachment, `enforce_live_candle_batch`, `IntradayBotEngine._fetch_scan_candles` and retained cash snapshots | `test_valid_fixture_uses_actual_scanner_and_excludes_forming_tail_from_lineage`; invalid-input and stale/forming-only tests |
| A/J: reject invalid identity/time/volume | Existing broker and canonical identity gates | Wrong token, wrong exchange, gap, duplicate, disordered input, missing/negative volume, future time, out-of-session time and ambiguous timezone each fail before real strategy/output |
| B: actual cash strategy integration | `evaluate_strategy_detailed` delegates once to existing evaluators; scanner retains public evaluator call path | Real scanner positives for order-block, VWAP, ORB and Supertrend; no ready-made candidate is injected for these positive cases |
| C: warm-up integrity | Existing 30/35/200-bar requirements and session-required inputs | Explicit insufficient completed history; full Supertrend history; missing current session-open VWAP input rejected despite sufficient count |
| D/E: candidate and explanation semantics | Scanner `strategy_evaluations`, `candidate_evaluations`, source references and conservative `actionable=false` | Detected real setup becomes qualified candidate; unsupported strategy warm-up is unavailable; deliberately corrupted target/high score produces retained rejected candidate with no rank |
| E: unsupported assumptions | Existing numeric helper and explicit warning fields | No fabricated win probability; liquidity, fills/slippage, empirical performance and net target RR remain unavailable |
| E/F: breadth validity | `_compute_universe_breadth` now requires the actual current session opening bar | Full-session peer remains counted; adding a later-only peer does not alter breadth; partial-only peers return unavailable |
| F: ranking | Existing `rank_signal_candidates`, quality → numeric target-1 RR → identity/full-value tie-break | All six permutations of a three-candidate set, exact-identity ties, input immutability, and rejection of invalid high-quality geometry |
| G: risk/reward | `signal_risk_reward` reports gross per-unit INR distances and actual entry/stop ratios | Independent arithmetic from emitted prices for risk, both target distances and both ratios; zero/invalid/nonfinite geometry cannot enter ranking |
| H: persistence/idempotency | Scan-evaluation JSON, immutable cash result, existing dedup and replay | Exact trace/candidate roundtrip; repeated scan retains same candidate/source explanation while emitting no new signal and storing one scan/signal |
| H: existing consumer compatibility | `_handle_signals`, `_handle_scans`, candidate annotation and cash lineage | Actual existing handlers expose matching candidate/strategy metadata, retain `CANDIDATE_ONLY`, and never grant real execution actionability |
| H/J: tamper and safe failure | Persisted checksum plus committed cash-result cross-binding | Changed bytes and recomputed-checksum inconsistency rejected with HTTP 503 by both history handlers |
| I: broader compatibility | Existing source/output structure remains additive | Focused assertions preserve original signal prices and ordinary history fields; full legacy/dashboard compatibility remains the coordinator's canonical suite responsibility |
| J: lifecycle and operating safety | Engine closes explicitly attached feed; provider choice remains independent of real execution permission | Shutdown stops feed and detaches it; in-memory database, selected provider, dry-run true and scheduler false remain unchanged |
| K: reproducibility | Shared focused runner retains exact IDs, source snapshots, command and log checksum | 20/20 PASS, source stable, checksum matches; canonical full verification and release acceptance are separate coordinating gates |

## Final consumer review and executed contract example

The final read-only source review found one additional display omission: the existing scan-history renderer listed strategy traces but omitted candidate records rejected later by sizing or level validation. With no stored accepted signal, the dashboard could show a detected setup and zero signals without showing its downstream rejection reason. The coordinator corrected `scanEvaluationText` to append candidate status/reason codes. This worker read the correction and its new actual-renderer test: a `DETECTED` setup with candidate `REJECTED` / `INVALID_SIGNAL_LEVELS` now appears in the `COMPLETED_EMPTY` scan table. The coordinator reports 14/14 focused Node tests passing; this worker did not execute that Node run. No other concrete Phase 4 source omission was found in this review.

The 20-test focused snapshot predates that final UI change, so it remains correctly bound to its tested source. The coordinating current full proof is `docs/evidence/master_phase4_implementation_20261023_02.json`; its final status and source/log validation belong to the coordinator. Earlier `_01` full proof and release remain preserved historical artifacts.

To provide an inspectable example against the final frozen source, this worker executed:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs\evidence\phase4_implementation_contract_example_20261023_02.py
```

The command returned exit 0 / PASS, with identical before/after source snapshots, both in-memory scenarios cleaned and zero unraisable errors. The JSON explicitly labels itself `OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE`, with `operational_acceptance=false`; nested LIVE modes are preserved as the existing validation-contract labels rather than misrepresented as genuine observations. No unittest cases were executed by the example and no cases are added to the 20-test count.

The example contains one actual qualified order-block scanner result with all four strategy traces, source/candle/batch references, full candidate data, exact existing signal-history/scan-history agreement, an idempotent repeat with no new signal, and a separate 20-completed-bar `COMPLETED_EMPTY` result with precise unavailable warm-up reasons. It uses the canonical offline-network guard and the established credential-free test fixture; it starts no listener and emits no credentials. No private database or operator configuration is loaded.

| Final example artifact | SHA256 |
|---|---|
| `docs/evidence/phase4_implementation_contract_example_20261023_02.py` | `4b7dbc233dd0ee6cb49101a80fe5a8aa66ede13438cc71444fea09e0e2021b20` |
| Matching `_02.json` | `0dc099fb143457afcf2881d907f97d9a6870e548038a5a7f3fc219b50a2d7a17` |
| Matching `_02.txt` execution log | `47a5780f8e2403319bccb14dfb7e7e0efb08b57657af9d436c3aedc65d9e654b` |

The JSON binds its exact script bytes, source snapshots, command and log hash; stdout additionally reported the JSON hash. This worker independently checked those bindings. The earlier example `_01.py/.json/.txt` remains unchanged as a pre-UI-correction snapshot. The `_02` script is a byte-identical exclusive copy, so its script hash matches `_01`; its command, artifact paths, runtime IDs, source snapshot and resulting JSON are separately bound.

## Independent conclusion and limits

The 20 focused cases pass without weakening validators, reducing warm-up, inventing missing observations or enabling execution. No unresolved failure remains in this independent test module at the recorded source snapshot. The coordinator must still complete and validate the full regression/compilation/dashboard/release checks against its final source before using `PHASE_4_IMPLEMENTATION_ACCEPTED`.

This evidence establishes deterministic offline engineering behavior for the tested input-to-candidate-to-persistence/API paths. It does not establish live operation, historical research qualification, profitability, predictive performance, external messaging, paper-performance acceptance or broad F&O acceptance. No unrelated market-day activity was executed as part of this QA mission.
