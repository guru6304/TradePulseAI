# TradePulse AI — parallel historical qualification and Dhan feed implementation

## A. Repository integrity

Repository: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`.
Entry HEAD: `205803131d7e1a17d6b42ce976efe7dff30e475a`.
Entry modifications and their file hashes are preserved in
`docs/evidence/task2_parallel_baseline.json`. The existing 758-test receipt was
checked against the entry source and log bytes, without claiming a new run:
`task2_baseline_receipt.json`. No reset, checkout, clean or commit was performed.
HEAD advanced externally during work to
`2ef6751a4f393507d13522a505d1070356114779`; the worktree was preserved.
Initial status contained 21 modified files and the retained untracked Phase 4A/4B
implementation/evidence. The final porcelain status and immutable historical
evidence checks are retained in `task2_parallel_closeout.json`. This task did not
edit either local `.env` file.

Files changed in this task, excluding retained machine evidence:

| File | Purpose |
| --- | --- |
| `historical_study.py` | Original-byte archive, current rights/source qualification, frozen walk-forward studies. |
| `option_execution.py` | Retain original replay inputs when persisting completed option results. |
| `test_historical_study.py` | Thirteen historical evidence and cash/option study regressions. |
| `dhan_feed.py` | Continuous documented binary transport, normalization, aggregation, persistence and health. |
| `test_dhan_feed.py` | Twenty-six deterministic protocol, failure and lifecycle tests. |
| `config.py` | Explicit bounded Dhan scope, canonical validation and safe status count. |
| `.env.example` | Empty opt-in subscription list; existing `.env` files preserved. |
| `requirements.txt` | Pin compatible synchronous `websockets==15.0.1`. |
| `dhan_feed_control.py` | Configuration-only preflight and explicit bounded read-only probe. |
| `brokers.py` | Opt-in Dhan feed attachment, guarded reads and deterministic detach/close. |
| `scanner_engine.py` | Expose stream status, block stale/fixture signals and stop feed before SQLite. |
| `server.py` | Stream failure alerts in existing health response. |
| `public/index.html` | Continuous-feed state in existing health panel. |
| `test_task2_integration.py` | Six shared preflight, fallback, status and cleanup regressions. |
| `test_cash_dashboard.js` | Render stale/fixture/unavailable feed states without acceptance. |
| `test_bot.py` | Register the three new independent suites exactly once. |
| `verify_offline.py` | Bind configuration template and source revision into execution evidence. |
| `release_management.py` | Include new modules and the explicit public documentation handover. |
| `test_release_operations.py` | Check README/runbook links inside ZIP and extracted new-module bootstrap. |
| `README.md` | Current entrypoints, scoped status and historical-score labeling. |
| `docs/TRADEPULSE_OPERATIONS_RUNBOOK.md` | Operator APIs, fields, stream lifecycle, evidence retention and limits. |
| `docs/TRADEPULSE_EXECUTION_LEDGER.md` | Current task, dual revision record, safety and acceptance boundaries. |
| `docs/RELEASE_EVIDENCE_LOCATION.md` | Exact repository evidence locations and source-package scope. |
| This report | Consolidated implementation, verification and remaining dependencies. |

## B. Track A — Historical source and strategy validation

| Deliverable | Status and evidence |
| --- | --- |
| Acquisition/identity/lineage inspection | Reused `historical_data`, `historical_pagination`, `instrument_archive`, `instrument_identity`, `candle_lineage`, `source_qualification`, `publisher_trust`, `storage`, existing engine and contract validation; no acquisition rewrite. |
| Source and rights qualification | IMPLEMENTED AND OFFLINE-TESTED. Current genuine Ed25519 verification remains mandatory, with a separately controlled rights document/hash/provider/publisher/use/symbol/date/revocation approval. No production root or rights approval was invented. |
| Durable originals | IMPLEMENTED AND OFFLINE-TESTED. Exact master, observations, manifests, rights documents and frozen plan/result bytes are content addressed in SQLite. Reopening and altered-byte denial are tested. Loading bytes does not restore stale authority. |
| Cash and chronological research | IMPLEMENTED AND OFFLINE-TESTED. Existing quality checks reject order/duplicates/forming bars and audit missing coverage. Expanding chronological folds freeze config, runtime profile, strategy/source/dependency and policy hashes before evaluation. Actual cash replay checks only test-window entries and repeatability; no optimizer uses test results. Existing charge/fill/metrics implementation is reused. |
| Strategy 3 execution study | IMPLEMENTED AND OFFLINE-TESTED. Existing exact contract, next-open, executable bid/ask/depth, lot/tick/expiry, costs/capital, prior-closing OI and unresolved-data rules remain. Actual two-session option replay tests the future evaluation window. Completed persisted replay now retains original inputs; nonpersistent replay only computes its evidence ID. |
| REAL SOURCE VERIFIED | BLOCKED. No operator-approved genuine provider roots and independently authenticated, rights-cleared data were supplied. |
| HISTORICAL STUDY ACCEPTED | BLOCKED. Test-only real signatures and test-only rights documents prove controls, not authentic market data or profitability. OHLCV/IV/OI without the required historical execution observations remains insufficient. |

Focused command: `.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning -m unittest test_historical_study test_option_execution test_phase4_acceptance test_publisher_trust -v`.
Final receipt `task2_track_a_focused_runtime_bound.json`: **49 passed**, zero
failures/errors/skips, 26.971 seconds, unchanged scoped source hashes. It includes
13 new study tests plus existing option, identity and cryptographic regressions.
Representative tests include
`test_genuine_signature_and_separate_documented_operator_rights_are_both_required`,
`test_original_bytes_are_durable_across_file_store_close_and_reopen`, and
`test_actual_cash_engine_walk_forward_is_frozen_repeatable_and_fixture_labelled`.

## C. Track B — DhanHQ live feed

**IMPLEMENTED AND OFFLINE-TESTED** for bounded canonical NSE cash/index spot
instruments. Protocol sources were read before implementing packet layouts:
[Dhan v2 live feed](https://dhanhq.co/docs/v2/live-market-feed/),
[annexure](https://dhanhq.co/docs/v2/annexure/), and
[official SDK](https://github.com/dhan-oss/DhanHQ-py/blob/main/src/dhanhq/marketfeed.py).
Unsigned SDK field types resolve ambiguous documentation labels.
[WebSocket sync transport](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html)
is pinned with bounded frame/queue sizes, TLS, ping/pong, read timeout and cleanup.

The adapter implements ticker, quote, full five-level depth, OI, previous-close
and disconnect packets; fragmented/coalesced frames, malformed/unknown versions,
subscription validation/rejection, authentication/permission failure, duplicate
and delayed/out-of-order events, missing heartbeat/trade freshness, reconnect
and resubscription, storage failure and graceful threaded shutdown are tested.
Events retain canonical identity, provider/exchange/receive clocks, packet hashes,
connection identity and available fields. Missing fields stay explicit. Pending
quantities are never executed-side volume, and depth has no invented own clock.

One- and five-minute candles use exchange sessions and Kolkata time. Cumulative
volume is differenced once; missing baseline, trade gaps, sampled volume jumps
and unproven close boundaries make affected bars incomplete. No fabricated zero
volume, backfill, closing observation or simulation fallback repairs a failed live
feed. Reconnect resets consumable state and starts a separate retained lineage.
Indices/tickers without volume cannot produce qualified OHLCV; derivatives remain
unsupported by this initial pinned live mapping. Session-final minutes require an
observed close boundary and may stay provisional. Buffers and connection event
budgets are bounded; overload fails closed.

Focused command: `.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning -m unittest test_dhan_feed -v`.
Final `task2_track_b_focused_002.json`: **26 passed**, zero failures/errors/skips,
0.602 seconds, both owned source files compile. All are authored wire fixtures
or mocked transport; an injected peer permanently remains FIXTURE.

**READ-ONLY LIVE SMOKE TEST: BLOCKED; NOT RUN.** Local preflight
`python -B dhan_feed_control.py` found
`DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER` and
`EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED` (zero configured instruments).
`task2_dhan_local_preflight.json` records no live requests, no authentication
claim and no accepted feed. No Upstox/Angel credentials were borrowed.

## D. Shared integration

Existing canonical identity, candle quality policy, SQLite store, scanner and
readiness rules are reused. Streaming is explicit and bounded; configuration
never starts a socket, scheduler, Telegram delivery or order execution.
The path is documented and fixture-tested as:
source bytes/packet → normalization → existing canonical identity → session/time
quality checks → source hashes/provenance → SQLite → existing backtest/scanner
consumer → independent readiness and guarded outputs. Historical records and
stream connection records retain distinct origins and compatible candle fields.
Provider/identity/interval/time/connection keys prevent cross-provider overwrite;
conflicting observations invalidate affected data instead of silently replacing it.

The existing Dhan adapter consumes a stream only when explicitly attached. Errors
raise to the existing consumer, without REST/simulation fallback. No watchlist-wide
scanner or scheduler was started. To consume a bounded feed, the operator must
also configure a matching bounded scanner universe; unmapped subscriptions fail
explicitly. Existing persisted live acceptance remains independently required.
Shared tests include missing credentials/scope, invalid mappings, unsafe flags,
bounded probe, no fallback, old connection-state override and feed-before-store
shutdown. Dashboard checks show stale, fixture and unavailable states accurately.

## E. Verification results

Final command, from the application directory:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage task2_parallel_verified
.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task2_parallel_verified.json
.venv_phase4\Scripts\python.exe -B docs/evidence/task2_closeout_verify.py
```

| Check | Executed result |
| --- | --- |
| Complete Python regression | **803/803 PASS**, zero failures/errors/skips, 298.968 seconds. |
| Dashboard | **11/11 PASS**, zero failures/skips; JavaScript syntax PASS. |
| Python compilation | **62 files PASS**. |
| Source and execution evidence | Before/after/current hashes equal; validator exit 0; no unraisable resource errors. |
| Shared focused checks | **69 PASS**, 17.479 seconds, unchanged source during that run. |
| Runtime dependencies | `pip check` exit 0, no broken requirements. |
| Diff inspection | `git diff --check` exit 0; Git reports LF/CRLF conversion notices. |

The full runner prohibits non-loopback network access and binds actual case IDs,
source/configuration/dependency hashes and all log hashes. Tested revision:
`2ef6751a4f393507d13522a505d1070356114779` with the retained working changes.
`master_task2_parallel_verified.json` is current proof; earlier focused snapshots
are scoped historical receipts after later source refinements. Existing error-path
fixtures intentionally log rejected credentials, unavailable storage and stale
candles; these are passing negative tests. No unexpected warning or resource leak
appeared. Sandbox temp-directory ACL failures during setup were resolved by
running offline temporary-file tests with the approved local permissions. The
normalization fixture identity binding was corrected to preserve FIXTURE status;
no production provenance check was weakened.

The final candidate is `docs/evidence/task2_parallel_release.zip`, paired only
with `task2_parallel_release_build.json` and `task2_parallel_release_inspect.json`.
`task2_parallel_closeout.json` records the exact ZIP SHA256, manifest SHA256,
file count, source binding and current public-document hashes after verifying
every archived file size/hash, ZIP integrity and equality to delivered files.
README/runbook links and extracted module/test bootstrap are also exercised by
`test_release_operations`. Prior ZIPs/build receipts remain historical and intact.
The evidence directory is explicitly referenced outside the ZIP; the public ledger
and linked documents are inside it. This is source-package/offline validation,
not real provider smoke acceptance, real strategy performance or production release.

## F. Blockers requiring the user

Approved publisher trust roots, rights documentation and authentic point-in-time
historical cash/option execution observations are not supplied. Dhan-specific
local account credentials and explicit verified subscription scope must pass
preflight before the authorized minimal read-only probe. Never paste secrets into
chat or store them in evidence.

## G. Roadmap status

The fixed six phases remain: (1) trustworthy data/system foundation;
(2) historical data/strategy validation; (3) live market-data ingestion;
(4) scanner/explainable recommendations; (5) context/dashboard/alerts;
(6) paper trading/performance acceptance/release. This task advances 2 and 3,
with bounded integration into 1 and 4 and release hygiene under 6. No news/social
features or new top-level phases are introduced. Scores are not recalculated;
64.25 implementation, 37.00 readiness and 0/12 accepted milestones are historical
Phase 4A/4B estimates, not new acceptance claims.

## H. Next action

Establish an operator-approved authentic data source, with its rights and account
permissions, so the implemented historical qualification and live ingestion gates
can be exercised with genuine provider evidence.
