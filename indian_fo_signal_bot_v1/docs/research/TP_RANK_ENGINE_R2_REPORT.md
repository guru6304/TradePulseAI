# TradePulse AI — R2 ranking reliability

Checkpoint date: **2026-11-03 IST**. Worktree `C:\Users\91810\TradePulseAI-Worktrees\main`, branch `main`; approved base **`663a86859ea8daed9880f763413554116e601067`**. Initial tree was clean. Read [R1](TP_RANK_ENGINE_R1_AUDIT.md) and the H0/H1 [strategy](../agent-contracts/TP_STRATEGY_INTEGRATION_CONTRACT_V1.md) / [UI API](../agent-contracts/TP_UI_API_CONTRACT_V1.md) contracts before implementation. This is one isolated backend reliability checkpoint, with offline fixture verification only.

## Result and scope

R2 tightens scanner admission to the existing ranking/paper close-age ceiling, authenticates whole-universe coverage for ranking lifetime, blocks current rank views after recorded failures or unresolved work, and records previously unretained pre-input failures. Empty successful results get a lifetime derived from their actual completed inputs. Missing cash evaluator results cannot publish partial priority.

Scoring weights, normalization, setup rules, quality→gross-T1-RR order, tie-breaking, one-symbol selection, paper triggers/fills, four-strategy cash allowlist and `CONFLICTING_OPEN_POSITION` are unchanged. Option Apex stays fail-closed. No React, research algorithm, feature-branch merge, broker/live-data request, credentials, real order, Telegram send or operational database operation is included. All SQL execution used disposable test stores. No database table or migration is added.

## Root causes and before/after behavior

| Verified gap | Before at `663a868` | R2 behavior and source |
|---|---|---|
| Scanner close-age mismatch | Shared SCANNER allowance was `interval*60 + delay`, permitting360s after a five-minute close at delay60; rank and prospective paper required at most60s. | [`brokers.py:299`](../../brokers.py#L299): SCANNER uses `min(configured delay,60)` **after close**. Smaller limits and zero remain stricter. REFERENCE/DIAGNOSTIC retain their legacy semantics. No limit is relaxed. |
| Prior snapshot survives a newer failed attempt | Rank read selected latest COMMITTED work and ignored later FAILED attempts, even at the same wall-clock second. | [`rank_history.py:228`](../../rank_history.py#L228): overlay checks later same-broker LIVE/non-simulated failed scan rows using monotonic persisted row order. Current rows are withheld; immutable history remains. |
| Unresolved partial work is ignored by rank reads | A result-write rollback leaves PENDING input, while older priority could still read as current. Older-reference pending work could also block scanner progress without blocking rank views. | Any same-provider PENDING work suppresses current priority, regardless of reference ordering. Its retained inputs are validated. The same overlay applies to explicit/pinned run reads. |
| Generic/configuration/setup failure before accepted input lacks durable failure state | Certain exceptions updated only in-memory state; a restarted reader could still treat the predecessor as current. | [`scanner_engine.py:662`](../../scanner_engine.py#L662), [`:1432`](../../scanner_engine.py#L1432): local adapter mode is known before validation/setup; pre-input failure is retained in existing `scan_runs` after transaction cleanup. Failed committed-recovery attempts use a separate failure UUID and never replace the saved successful outcome. |
| Failure recorder itself unavailable | No reliable attempt record can be retained when the writer is unavailable. | [`server.py:557`](../../server.py#L557): running API returns existing503 UNAVAILABLE for `SCAN_FAILURE_RECORD_UNAVAILABLE`, withholding old rows. This process-local guard is explicitly limited across restart; see blockers. |
| Empty successful rank expires immediately | Zero rows caused `valid_until=scan reference`, so a later read labelled a healthy zero-setup scan stale. | [`rank_history.py:199`](../../rank_history.py#L199), [`opportunity_ranking.py:140`](../../opportunity_ranking.py#L140): expiry is derived from the complete retained universe's completed close plus configured delay capped at60s. A read clock never refreshes that lifetime. |
| Coverage is implicit in acquisition but not bound to empty-result lifetime | No candidate row meant no row watermark from which to establish current empty coverage. | New authenticated `tradepulse.rank-coverage.v1` metadata binds configured/observed symbols, completed watermarks and expiry. All required equities and indices must be present at the same completed five-minute slot. |
| A cash evaluator throws after input preparation | Scanner catches individual evaluator errors; a subset of traces/signals could otherwise reach publication. | [`rank_history.py:128`](../../rank_history.py#L128): rank-required R2 work needs one trace for every configured cash symbol × the four approved cash evaluators. Missing/duplicate traces fail the result transaction with `RANK_STRATEGY_COVERAGE_INCOMPLETE`. Normal REJECTED/UNAVAILABLE detector traces remain valid completed evaluations. |

## Freshness, coverage and clocks

The SCANNER rule is `0 <= decision_time - completed_close <= min(configured delay,60s)`, retaining all existing session, identity, OHLCV, ordering, gap, provenance and explicit-clock checks. A raw forming bar cannot establish completed evidence. Paper's independent account mark/trigger limits remain in place and can be stricter.

At a common five-minute grid, a <=60s close-age allowance cannot admit two different latest completed slots across required symbols. R2 additionally verifies the retained universe explicitly: exact configured cash and index symbol sets, completed inputs, same session date, one watermark, and the configured close-age boundary. It rejects a previous-slot peer and does not substitute missing symbols or expand the universe.

Coverage is derived from retained inputs at the original scan reference, not API request time. The same coverage expiry can only tighten a nonempty snapshot's former row-based expiry. An empty snapshot remains `CURRENT_CANDIDATE_PRIORITY` with `current_rows=[]` until that source-derived expiry; at expiry+1s it is stale. This expresses a fresh zero-opportunity result, not an entry authority.

The implementation still uses the weekday/configured-holiday calendar; no independently qualified exchange-calendar feed is introduced. Provider timestamps are not invented or replaced with request times. Existing raw source-clock, UTC normalization, missing OHLCV, incomplete, gap, duplicate and out-of-order tests remain part of regression.

## Persistence, recovery and publication

New rank-required input snapshots have `rank_coverage_required:true`, included in work identity ([`candle_lineage.py:218`](../../candle_lineage.py#L218)). This makes coverage requirements source-bound rather than a removable result-only declaration. History bodies add coverage, and reconstruction checks it against retained inputs before checking the rebuilt ranking. Legacy bodies without the flag retain their original reconstruction semantics. Code changes archive incompatible current views; R2 neither rewrites nor migrates old stores or pending work.

The original input preparation and `BEGIN IMMEDIATE` result transactions remain separate. Signals, evaluations, rank, outbox and COMMITTED result still publish atomically. The <=60s scanner check is repeated at existing publication checkpoints: a fixture moving the clock from close+5s to close+61s after rank insertion rolls back result effects, leaving only accepted PENDING input for recovery.

Failure suppression uses existing state, not a mutable rewrite of a rank snapshot:

1. Same-provider PENDING work wins first, consistent with the scanner's existing provider-wide recovery barrier. This includes a pending attempt with an older source reference.
2. A latest committed result marked recovered/non-current cannot restore currentness to an older selected run.
3. Later persisted FAILED/RECOVERY_REQUIRED rows for the provider's broker and LIVE/non-simulated mode suppress current rows. Row IDs resolve same-second and clock-rollback ambiguity conservatively; a failure persisted after another attempt's success still blocks until a new genuine success.
4. An ordinary SKIPPED_OVERLAP or failure from another provider is not an acquisition-failure barrier for this provider.
5. A genuinely new committed/current input restores currentness, including a healthy empty result. Idempotent replay and offline recovery do not clear a later failure merely by being read/replayed.

Recorded failures and PENDING barriers survive store reopen. If failure recording itself cannot persist, only the active process knows that unrecorded attempt: the API guard cannot reconstruct it after restart. That limitation is not described as restart-proof failure suppression.

## API and contract compatibility

Routes, query parameters, row fields, paging limits, run pinning, existing status strings and false actionability are preserved. Suppression uses `ARCHIVED_NON_CURRENT_SCAN` with empty current rows and the requested historical page still available. Stale clock status remains separate. Existing invalid-query/integrity/storage HTTP error shapes remain unchanged.

The additive metadata contract is documented in both agent-contract addenda:

- `snapshot.coverage`: null for legacy inputs, otherwise `{schema_version,complete,expected_symbols,observed_symbols,source_data_watermarks,max_close_lag_seconds,valid_until}`. Source watermarks are completed **bar starts**, and expiry is offset-aware.
- `snapshot.current_scan_state`: `{reason_code,run_id}`. Reasons: `LATEST_COMMITTED_SCAN_CURRENT`, `PENDING_SCAN_REQUIRES_RECOVERY`, `NEWER_SCAN_FAILED`, `LATEST_SCAN_NOT_CURRENT`, `NO_CURRENT_COMMITTED_SCAN`.

`snapshot.valid_until` remains the client expiry field. `snapshot.reference` remains scan reference, top-level `as_of` remains server read time, and `pagination.total` retains its meaning. No cursor, route, client clock override or actionability is added. A pinned historical run cannot bypass the failure barrier.

The static terminal paging/clock suites verify compatibility; this is not React/browser acceptance. Antigravity's UI and the Strategies branch were not changed or merged.

## Scoring and paper safety

`strategies.py` and its scoring helper were not modified. The existing quality score still uses RVOL.30 / directional VWAP distance.25 / displacement.30 / optional breadth.15 with existing normalization and missing-feature renormalization. Ranking still sorts quality descending, then actual gross T1 RR, then deterministic identities, retaining one cash setup per symbol. Rank version mathematics are unchanged; coverage expiry affects currentness only.

The pure ranking regression tests check ties/permutation, direction identity, revisions and ordering. The actual retained TCS/INFY two-scan test still verifies volume-driven rank reversal, previous ranks, component changes and distinct run/version identities. This remains evidence for dynamic quality re-ranking, not proof of a relative-strength algorithm or empirical edge.

Four cash trigger and execution suites, paper conflict/race/restart tests and Option Apex preflight tests are included in the focused regression. No paper implementation, cash allowlist, account policy, order path or option lifecycle was activated or changed. The existing scheduler remains default OFF and still has no automatic paper-account handoff; a deterministic scheduled-cycle test calls one fixture cycle without starting a background thread and verifies stale rejection.

## Verification and evidence

All runs use Python `-B`, the credential-free `test_bot` bootstrap, explicit safe flags, `verify_offline.offline_network`, fixture-only transports and disposable stores. The receipt runner binds exact expected/executed/passed IDs, source manifests before/after, runner/log hashes and subprocess results. Existing evidence is never overwritten.

Exact final command from `indian_fo_signal_bot_v1`:

```powershell
$env:ACTIVE_BROKER='paper_sim'
$env:TELEGRAM_DRY_RUN='true'
$env:ENABLE_BACKGROUND_SCHEDULER='false'
python -B docs/research/evidence/TP_RANK_R2_verify.py --stage after02
```

The runner's exact module list is retained in [`TP_RANK_R2_verify.py`](evidence/TP_RANK_R2_verify.py). It includes R2 regressions, market-data/freshness, pure ranking and retained history, scan references, recommendation/evaluation storage, cash lineage/recovery, all four cash paper trigger/execution policies, conflict protection, Option Apex preflight, workflow and HTTP safety. Node commands are `node --test --test-reporter=tap test_terminal_opportunities.js` and the same command for `test_terminal_clock.js`.

| Evidence | Observed result and interpretation |
|---|---|
| [Initial baseline](evidence/TP_RANK_R2_before_20261103.json) / [log](evidence/TP_RANK_R2_before_20261103.txt) | Ten new methods at original production code;13 assertion failures and one error across methods/subtests, two methods passed. Includes two fixture assumptions corrected before the accepted red run: one-vs-two-symbol count and a too-specific exception subclass. |
| [Corrected baseline](evidence/TP_RANK_R2_before_20261103_02.json) / [log](evidence/TP_RANK_R2_before_20261103_02.txt) | Ten methods at original production code;14 assertion failures across methods/subtests, zero errors/skips, two methods passed. Establishes freshness, failed/pending currentness and empty-lifetime failures without changing production. |
| [First broader implementation run](evidence/TP_RANK_R2_20261103_after01.json) / [log](evidence/TP_RANK_R2_20261103_after01.txt) | 327 methods,319 successful methods, two assertion failures and eight errors across subtests, zero skips; source unchanged during execution. No passing acceptance claimed. Stale/forming fixtures assumed the old scanner window; two new fixtures needed source-clock/mock-callable corrections. |
| Targeted correction checks |41 methods initially exposed a request-clock equality caused by changing a shared test clock; corrected only the three fresh SCANNER positive controls instead. Subsequent39-method R2+market-data run passed. These development checks are not substituted for the final source-bound receipt. |
| [Final regression](evidence/TP_RANK_R2_20261103_after02.json) / [log](evidence/TP_RANK_R2_20261103_after02.txt) | **330/330 Python methods passed**, zero failures/errors/skips, exit0. Includes17 R2 methods and313 existing methods. Unittest recorded14688.263s elapsed; this uncontrolled run is not a latency/throughput/soak benchmark. Source unchanged during the run; final manifest, runner/log hashes and exact IDs are retained. |
| [Final terminal tests](evidence/TP_RANK_R2_20261103_after02_test_terminal_opportunities.txt) / [clock tests](evidence/TP_RANK_R2_20261103_after02_test_terminal_clock.txt) | **15/15 terminal opportunity tests** and **2/2 timezone parent tests passed**, zero failures/skips, exit0. Each clock parent validates nine child checks (UTC and America/New_York); this remains synthetic client compatibility, not React/live/browser acceptance. |

Compatibility test updates make the stricter behavior explicit: old SCANNER360s expectations become60s; fresh positive controls move from close+65s to exactly60s; three paper negative tests now require rejection at the scanner boundary rather than allowing stale input to reach a paper evaluator. No trigger acceptance, scoring threshold or paper safety expectation was relaxed.

Final review confirmed zero source-manifest mismatches, matching runner/log hashes and no unraisable errors. Source/report whitespace checks pass. Three trailing spaces emitted on failed-subtest lines remain in the raw earlier logs; those evidence bytes are preserved rather than changed to silence the staged whitespace check.

## Files changed

| Area | Files and purpose |
|---|---|
| Admission | `brokers.py`: context-specific close-age ceiling. |
| Input/history | `candle_lineage.py`, `rank_history.py`: bound coverage flag, full evaluation/series coverage, source-derived expiry and failed/pending overlay. |
| Snapshot builder | `opportunity_ranking.py`: optional authenticated source-expiry input; sorting/components untouched. |
| Orchestration/API | `scanner_engine.py`, `server.py`: retain pre-input failures safely after cleanup, preserve committed recovery outcome, withhold rows on unavailable failure recording. |
| Tests | New `test_r2_ranking_reliability.py`; focused expectations in `test_bot.py`, `test_market_data_contract.py` and VWAP/Order Block/Supertrend trigger test files. Production paper modules unchanged. |
| Handoff | Both agent-contract addenda, this report, current status/checkpoint links and isolated verification evidence/runner. |

## Remaining blockers and limits

- True cross-sectional return-relative strength, sector/regime factors, cost-aware target economics and empirically calibrated edge are still missing. R2 implements none of them and does not change their unavailable labels. Research ownership remains separate.
- No live provider, entitlement, source authenticity, current mapping/rights, exchange calendar, empirical/OOS, live paper or commercial acceptance was established. Fixture success cannot satisfy these gates.
- The unrecordable-failure guard is process-local. A process restart cannot reconstruct a failed attempt that could not be written anywhere. Stored failures and accepted PENDING work are durable; disk failure/power-loss acceptance needs separately reviewed operating/restore policy.
- Full-universe coverage remains required; one bad required instrument suppresses current priority. Failure/PENDING barriers are conservative by provider, so a failed attempt under another configuration of the same provider can also suppress priority until a genuine success. No coverage-aware partial-universe ranking or candle-correction workflow is added.
- `_coverage` adds a bounded retained-series normalization pass on reconstruction/read. Extended512-symbol backend load, p95/p99 latency, lock-timeout and soak acceptance remain unmeasured.
- Scheduler polling is still not aligned to every candle close; tighter admission can reduce availability when feeds/acquisition are late. Scheduler-to-paper orchestration and rank-to-capital allocation remain absent, and all operational activation remains default OFF.
- No operational database migration or code/config-change recovery conversion was performed. Existing pending work remains subject to original code/profile recovery guards.

**Stop after R2 for owner review. Commit locally only; no push, merge, R3, scoring enhancement, strategy activation or live action.**
