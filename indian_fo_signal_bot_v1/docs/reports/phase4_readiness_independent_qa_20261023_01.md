# Phase 4 independent readiness review — 2026-10-23

Verdict: **PHASE_4_NOT_STARTED_PHASE_3_GATE**. This is a read-only source and existing-evidence review for workstreams C, E and F of the current Phase 4 request. No production implementation, tests, provider requests, application services, configuration changes or private database inspection were performed by this worker. The only file written is this report.

The current Phase 3 acceptance matrix, `docs/evidence/phase3_angel_acceptance_20261023_02.json`, records `BLOCKED_REAL_COMPLETED_MARKET_CANDLES`, with zero accepted fresh observations and zero completed live 1-minute/5-minute candles. Actual completed-candle persistence and actual scanner consumption remain pending. The coordinating audit checks for newer receipts and independently validates source/log/release integrity; this report does not promote an old receipt into current acceptance. The newest user request forbids another observation merely to enter Phase 4, so this review makes no provider request.

## Source and evidence inspected

The inspected HEAD was `4eb7330bf074d9b07733fade6d7a8e08c200fa0b`. The source references below refer to files in `indian_fo_signal_bot_v1/`, as found during this audit. Existing Phase 3 work is preserved; the HEAD alone is not a complete description of its working tree.

| Inspected file | SHA256 |
|---|---|
| `strategies.py` | `90625a7a66984a6fd9a9f799e61229dd8c086220fd5ab7455ac75fe4266222ab` |
| `scanner_engine.py` | `80e4a604507e3ad6b1472e67f412292b7487babf3f3947f34a672f45ecbb6fb4` |
| `candle_lineage.py` | `2d324919a0c22e6fe9df3969590513a4b2ac178dcdf04213ca5b49204be29866` |
| `server.py` | `dfbcd6b07426774cad7147aebffb1efad1c53538deeb51641e24125a0bdf8e5c` |
| `public/index.html` | `3ca6c5237e250878940ab2fa87bb2e5c56c54b720074713aaf1f50ad66235eb1` |

Inspected evidence includes the Phase 3 completion report `_03`, acceptance matrix `_02`, `master_phase3_angel_20261023_03.json`, and closeout validation `_03`. The existing strict receipt reports 862 executed and passed Python tests, 11 executed and passed Node tests, 68 compiled Python files and zero unraisable exceptions. Those are **previously recorded results**, not new executions by this worker. Its expected/executed/passed lists include the ranking, cash-workflow and Angel integration tests cited below. The coordinating engineer validates current binding; this worker did not run the canonical verifier or rebuild a release.

## Current candidate, ranking and explanation contracts

`strategies.py:15` defines the existing `TradeSignal`; `to_dict` at line 73 serializes its declared fields. It already carries symbol/segment, strategy identifier/name, direction, entry price/zone, stop, invalidation, targets, a display risk/reward string, quantity, estimated risk/charges, rationale, timestamp, mode, provider/context/interval, canonical instrument identity, quality score and feature breakdown. Reuse this contract rather than introducing a parallel signal model before an evidenced need exists.

`validate_trade_signal` at `strategies.py:94` validates finite numeric levels, positive quantity, integer quality in 0–100, zone ordering, direction/position-type agreement, and directionally consistent stop/invalidation/entry/targets. Long options use premium-price geometry for both CE and PE. Identity/provenance are explicitly separate gates.

`compute_setup_quality_score` at `strategies.py:177` specifies the current deterministic confluence calculation: RVOL weight 0.30, directional VWAP alignment 0.25, ATR displacement 0.30 and actual breadth 0.15. Missing features remain unavailable and weights are renormalized over supplied features. `score_breakdown` at lines 299–315 exposes raw inputs, normalized values, effective weights and the explicit statement that this is not a calibrated win probability. An absent breadth observation is not synthesized.

`rank_signal_candidates` at `strategies.py:130` already implements deterministic ordering. It first validates every candidate, then sorts by descending quality, descending numeric target-1 reward/risk, symbol, strategy ID, direction, position type, timestamp, label and canonical full candidate JSON. The numeric ratio is `abs(target_1-entry_price)/abs(entry_price-stop_loss)`; the display `risk_reward` string does not control ordering. The function returns a sorted copy. Exact duplicate candidate values are equivalent; this is candidate priority, not capital allocation.

`scanner_engine.py:953` recomputes sizing at the scanner boundary, rejects ineligible sizing, validates levels and calls the ranker at line 978. Its response declares `QUALITY_THEN_TARGET1_REWARD_RISK_THEN_IDENTITY_V1` and `CANDIDATE_PRIORITY_ONLY_NO_CAPITAL_ALLOCATION` at lines 1124–1125. Identity, freshness and required persistence remain independent of score; ranking does not establish live acceptance.

Existing evaluator rationale and feature breakdown support explanations, but the inspected `TradeSignal` is not a complete structured record of every rule pass/failure. Ordinary evaluator no-match returns and scanner `instrument_errors` are not equivalent to a retained, strategy-specific rejection record. The scanner summary serializes `TradeSignal` directly at line 1133; it does not itself emit an explicit detected → qualified → actionable state machine. These are **Phase 4 contract/coverage gaps to resolve after the dependency gate**, not a reproduced case of an unsafe actionable recommendation.

The `confidence_pct` compatibility field is synchronized with `quality_score` in `TradeSignal.__post_init__`; consumers must preserve its documented score meaning. Neither the field name nor fixture values establish confidence calibration, empirical win probability or profitability. Telegram's current formatter at `telegram_bot.py:43` calls it setup quality with predictive performance unverified and reports configured risk at line 51.

## Actual API and dashboard consumer path

The existing scan path returns its summary through `server.py:279` (`_handle_scan`). Invalid provider/candle input produces HTTP 502 with `scan_status=FAILED`, LIVE mode and structured freshness/identity reason data; required persistence failure produces HTTP 503 with zero committed signals. A scan overlap returns HTTP 409. A completed valid-input scan with no setup is distinct from these failures.

The stored-history path is `server.py:318` (`_handle_signals`) → `store.query_signals` → `candle_lineage.annotate_signals` at line 342. `annotate_signals` (`candle_lineage.py:352`) reconciles committed retained inputs, attaches batch/run references, defaults the result to `CANDIDATE_ONLY`, and **always sets `actionable=false`** at line 370. A scoped paper decision adds `PAPER_<status>` and a reason code; a simulated fill never authorizes a real order. Corrupt/unreconciled lineage returns HTTP 503 rather than an ordinary history response.

`server.py:399` exposes bounded read-only `/api/scan-lineage` and `/api/cash-candles` inspection. The public summary (`candle_lineage.py:338`) includes source/profile/code bindings, input identities, interval, validation and observation times. It explicitly reports source authenticity not established, historical replay disallowed and current live acceptance false. The existence of these locators therefore does not qualify research rights or live acceptance.

`public/index.html:1416` renders stored candidate/paper status and reason; line 1420 renders input batches/run. The inspector at line 1488 shows supported levels and setup quality; line 1527 labels breadth unavailable when absent; line 1548 includes rationale, status and source batches. The UI retains persisted quantity and labels its configurable quantity calculation as a preview at line 1543. A preview is not a server sizing decision or an order. No UI rewrite is needed to test this path.

The immediate scan response and reconciled stored-history response serve different existing purposes. Before claiming Phase 4 explainability/actionability acceptance, specify additive compatible semantics for both, including rule evidence, qualified/rejected states and unavailable warnings. Do not rename `actionable=false` to true to create acceptance; recommendation eligibility and permission to execute must remain distinct. Existing history order is not automatically the rank order of one scan, so a future contract must state the ranking scope and whether an ordinal is retained.

## Existing tests relevant to the new contract

These tests were **read, not executed here**. Names are locators of existing coverage; their presence alone is not a new PASS.

| Existing test/location | What its assertions exercise | Limit |
|---|---|---|
| `test_completion_engineering.py:207`, `TestCandidateValidationAndRanking.test_quality_then_observed_reward_risk_then_identity_order_is_input_invariant` | Quality → numeric reward/risk → identity ordering, reversed input equivalence and no input mutation | Not an all-permutations/exact-identity-tie or current live consumer proof |
| Same class, line 219 and line 229 | Malformed geometry/scores/direction rejection; distinct short and long-put geometry | Not every evaluator's complete positive/negative acceptance |
| `test_bot.py:1301`, setup-quality reproducibility/boundary/missing-breadth test | Deterministic score and unavailable breadth | Not calibrated performance |
| `test_phase4_e2e.py:209` and subsequent tests | Provider-shaped fixtures through real evaluators, sizing, persistence, dry-run, restart/dedup and failure invalidation | Deterministic offline fixtures, not Phase 3 live acceptance |
| `test_cash_workflow.py:72` | Actual loopback scan → retained lineage → paper decision → HTTP history → actual JS renderer, with matching fields | Fixture scope is explicitly `OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE` |
| `test_cash_workflow.py:144` | Paper risk rejection remains `actionable=false`, no paper position | No live execution authorization |
| `test_cash_lineage.py` | Tamper rejection, transaction rollback, retained input links, idempotent retry/recovery | Current real feed-to-consumer acceptance still pending |
| `test_phase3_angel_integration.py:119`, line 216 and line 243 | Stream failure without REST/provider fallback; source-event links; completed-candle subgate cannot falsely accept scanner | Does not make the connection-only probe a scanner success |
| `test_cash_dashboard.js` | True empty/failure states, fixture labels, paper rejection, source references and failed/late health/report state | DOM harness is not an interactive-browser or real-feed acceptance run |

No TODO/FIXME/NOT_IMPLEMENTED marker was found by a targeted text search of `strategies.py`, `scanner_engine.py`, `candle_lineage.py`, `server.py` and `public/index.html`. That result does not prove absence of defects; the HTML placeholder attributes are input hints, not unfinished recommendation outputs.

## Independent Phase 4 acceptance matrix

Every row is provisional readiness, not Phase 4 acceptance. Gate 1 prevents implementation and operational acceptance of the remaining gates.

| Gate | Current independently reviewed position | Evidence still required after Phase 3 acceptance |
|---|---|---|
| 1. Phase 3 dependency | **BLOCKED**: matrix records no accepted fresh/completed feed input and no actual consumer | Current source-bound formal Phase 3 acceptance including genuine completed intervals, durable links, actual scanner consumption and safe stop |
| 2. Scanner input | Existing validators and lineage contract; offline cases present | Verify genuine accepted input through the supported consumer, with identity/time/session/interval/provenance intact |
| 3. Strategy integration | Evaluators are called by existing scanner; strategy worker audits exact rules/warm-up | Per-claimed-strategy positive/negative real-path integration and supported/unavailable scope |
| 4. Explainable candidates | Existing rationale/breakdown/levels/lineage; structured rule/rejection/state semantics incomplete for this new contract | Add only evidenced missing semantics; prove every explanation derives from accepted input/rules |
| 5. Ranking | Existing deterministic implementation and input-reversal regression | Freeze same-input/config policy; test equal-quality/equal-ratio identity ties, repeated runs, permutations, and invalid high-score rejection before ranking |
| 6. Risk/invalidation | Existing geometry validation and sizing; separate strategy/risk audit owns detailed review | Per-strategy numeric consistency and unavailable assumptions; no score may rescue missing mandatory risk inputs |
| 7. Fail-closed LIVE | Existing stream/provider failure and invalid batch tests; observed stale packet rejected | Current genuine-consumer acceptance plus independent regression that no simulation/history/provider fallback can create actionable output |
| 8. Persistence/output | Existing committed lineage, reconciliation, HTTP and actual renderer fixture path | Additive output-state contract, ordinal/scope semantics where needed, rejection audit and genuine consumed-input references |
| 9. Regression compatibility | Existing strict `_03` receipt records PASS; no source changed by this worker | Coordinator validates current source/log binding; if implementation later changes source, run focused/integration/full canonical verifier anew |
| 10. Security/safety | No private IO/network/execution by this review; code preserves candidate-only stored outputs | Coordinator checks saved paper/dry-run/scheduler flags categorically, preserved files and no unauthorized side effects |
| 11. Evidence/reproducibility | Existing receipt/source/hash review only | Coordinator binds final audited files, exact commands, logs, gate decisions and release exclusions; offline tests never substitute for live gates |

## Prioritized findings and classifications

1. **External/provider dependency:** genuine fresh events, completed live 1m/5m candles and actual consumer evidence are missing in the inspected Phase 3 matrix. Resolve the existing Phase 3 task under the latest authorization boundary before Phase 4 production work.
2. **Missing in-scope implementation/acceptance contract, pending gate:** structured detected/qualified/rejected/recommendation states, rule-pass/rejection detail, explicit unsupported-input warnings and consistent immediate/history semantics need a bounded gap assessment. Existing `actionable=false` is a protective execution boundary, not an implementation failure to fix by enabling actionability.
3. **Test/evidence gap, pending gate:** existing ranking test covers reversed input and distinct symbol ties but does not alone prove every same-identity tie/permutation, per-strategy explanation completeness, repeated database serialization or rejected high-score candidate case under the new acceptance contract. This is not a reproduced production defect. Cross-review also identifies a future failure-injection case: disconnect or feed-quality degradation after fetch but before persistence/output. Cached candle freshness and stream health must be checked at the relevant output boundary; no runtime escape was reproduced in this audit.
4. **Historical-data governance dependency:** the genuine Angel historical response has 73/75 expected bars; publisher trust, rights, dated identity and sufficient study sessions remain separate. No interpolation, fixture or current-master capture can satisfy them. This does not authorize a historical rewrite during Phase 4.
5. **Documentation chronology:** earlier matrix rows say cross-universe ranking is absent; the later 2026-10-22 addendum explicitly includes scanner/quality/ranking/risk integration. Current `rank_signal_candidates` confirms implementation. Do not report this as a newly discovered missing ranker or alter earlier historical assessments. A new readiness addendum is the appropriate current explanation.
6. **Explicit future scope:** broader dashboard/context/alerts are Phase 5; paper performance/release operations are Phase 6. Real F&O acceptance requires independently qualified exact dated contracts, executable premiums/depth and aligned OI/prior-close data. Cash acceptance cannot establish these.

**Confirmed newly reproduced software defects: none in this read-only QA pass.** No assertions were weakened, no defect was repaired and no new regression was run.

The parallel strategy/input reviews report additional static integration constraints for the coordinator to bind to exact source: Supertrend needs 200 completed 5-minute bars while the Angel ring retains at most 150; the default scanner universe includes indices and multiple cash instruments while the accepted initial stream scope is one NSE cash instrument. They also confirm the bounded feed-control command closes its feed and retains the actual scanner-consumer gate. These constraints must be resolved through an explicitly scoped application handoff after authorization, not an `.env` change or a claim that a diagnostic receipt proves scanner consumption. They are not reproduced runtime failures from this QA worker.

## Non-conflicting implementation and independent test plan

This plan is conditional on the Phase 3 gate passing. It is not implementation started.

| Owner | Exclusive production ownership / role | Interface boundary |
|---|---|---|
| A: input/lineage | Existing broker/feed/lineage/storage files, with exact file assignment frozen before edits | Canonical completed candles and immutable batch/run/source references; no silent fallback |
| B: strategy/risk/ranking | Sole editor of `strategies.py`; incorporates reviewed C/D rule/explanation/risk proposals | Existing evaluator signatures and `TradeSignal`; preserve parameters, deterministic score and price conventions |
| C: explanation/ranking reviewer | Independent contract review and separately named tests; no concurrent edits to B's file | Supported facts only, unavailable fields explicit, stable state/rank semantics |
| D: risk reviewer | Independent numeric/geometry review and separately named tests; no concurrent edits to B's file | Correct side/units/lot/capital assumptions; rejected candidates never promoted by ranking |
| E: existing outputs | `server.py` and `public/index.html` only, if additive changes are evidenced necessary | Compatible immediate/history responses, truthful state and lineage display; no new dashboard/alert channel |
| Coordinator | Sole editor of `scanner_engine.py`, canonical loader, release allowlist and integration documentation | Sequences A/B/E integration and any shared contract change; reviews all diffs before the strict suite |
| F: independent QA | New uniquely named acceptance test file(s), no implementation-owner file edits | Tests actual evaluator/scanner/store/API/renderer paths with isolated fixtures and no private database |

Do not edit `candle_lineage.py` or `storage.py` concurrently for competing candidate-state designs. Agree any additive fields, exact rejection codes, ranking scope and persistence ownership before A/B/E implementation. Independent F test expectations must come from the user contract and reviewed strategy rules rather than copying production calculations.

The future focused matrix should cover accepted completed input and every identity/time/session/volume/gap/duplicate disorder failure; per-strategy mandatory opening/warm-up/input boundaries; invalid/zero/nonfinite risk distances; missing unsupported liquidity; high-score invalid candidate rejection; equal-score/equal-ratio/full-identity ties and input permutations; source/profile-bound reproducibility; exact-once repeated evaluation and restart; required-store rollback/tamper; honest immediate/history states; provider disconnect without alternate data; and no real orders or Telegram dispatch.

Run focused tests first, then affected scanner/lineage/API/renderer/safety tests, then the current documented strict verifier with a new exclusive evidence stage. The existing canonical form is `.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage <new_unique_stage>`, followed by `--validate-evidence` for that exact receipt. These are future instructions, not commands executed in this audit. Inspect actual test totals rather than forcing the previous 862 count. Fixture transport must stay labeled offline and every test database must be isolated from the operator database.

## Roadmap and completion boundary

The current user request fixes six product phases: (1) foundation, (2) historical validation, (3) live ingestion, (4) scanner/explainable recommendations, (5) context/dashboard/alerts and (6) paper/performance/release. `TRADEPULSE_COMPLETION_ROADMAP.md` uses P0–P4 work-package priority labels; those labels are not extra product phases. The capability matrix retains exactly M01–M12 as the milestone denominator. Its latest inspected accepted offline addendum retains 64.25 implementation / 37.00 verified readiness and 0/12 whole milestones accepted. This review does not recompute or inflate those scores.

Files named `test_phase4_*`, historical Phase 4 reports and older Phase 5 addenda describe retained engineering history. Their names do not establish acceptance of the new six-phase Phase 4 request. Similarly, the earlier market-data matrix's NOT_TESTED cells are historical snapshots; the current Angel acceptance matrix provides the more recent scoped result and still blocks Phase 3. The appropriate single next task remains completion and evidence review of the existing bounded Phase 3 live-data/actual-consumer acceptance under current authorization. No new observation, schedule or wider provider scope is started by this report.
