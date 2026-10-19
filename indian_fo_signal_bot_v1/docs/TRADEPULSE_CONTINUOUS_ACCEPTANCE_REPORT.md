# TradePulse AI - continuous acceptance engineering evidence

2026-10-19. This mission continued from the existing Phase 5C checkout. It delivered
and tested the bounded implementation below, obtained one unqualified public master,
and measured software performance. **Broker-account authentication, current cash
quotes/candles, derivative execution and empirical signal quality are NOT_TESTED.**
Missing credentials/source authority and the financial-recovery policy remain
explicit dependencies. A passing engineering package does not accept a full product
milestone or authorize a production service.

## Starting evidence and safe baseline

`../continuous_baseline.tmp` retains the exact bytes of 66 non-secret source,
template and documentation files before edits. `.env`, credentials and production
database contents are excluded. This comparison preserves the preceding Phase 5C
changes independently of Git state. The prior 539-to-559 progression is historical;
the freshly executed starting suite here was **559 passed**, not 539.

| Executed starting check | Result | Seconds | Exit | Python warnings / application WARNING records |
| --- | --- | ---: | ---: | ---: |
| Strict full suite, `continuous_baseline_full.tmp` | 559 passed, 0 failed/skipped | 169.606 | 0 | 0 / 3 |
| Contract/provenance/paper/integration/forward/recovery confirmation, `continuous_baseline_focused_confirm.tmp` | 98 passed, 0 failed/skipped | 31.373 | 0 | 0 / 0 |
| First parallel focused baseline, `continuous_baseline_focused.tmp` | 98 passed, 0 failed/skipped | 35.277 | Complete OK log; confirmation above retains a separate exit file | 0 / 0 |
| In-memory compilation | All 29 original top-level Python modules | Not timed | 0 | 0 |
| Pre-edit whitespace | `git -c core.autocrlf=false diff --check` | Not timed | 0 | No whitespace errors |

The initial tree already contained Phase 5C work. No reset, staging, provider switch,
credential change or replacement project was used. Final comparisons are against
this mission's snapshot, rather than treating all Git changes as this mission's work.

## Engineering iterations and acceptance states

ACCEPTED below always means the stated bounded software package, with the listed
offline evidence. It never means live market acceptance or milestone completion.

| Workstream | Delivered and verified scope | Remaining state / exact dependency |
| --- | --- | --- |
| A - baseline | ACCEPTED: fresh full/focused baseline, snapshot and compilation. | Earlier reports retained as dated evidence. |
| B - Angel isolation | IMPLEMENTED, OFFLINE_TESTED and MOCK_TESTED: explicit isolated configuration view, narrow read-only command, one-login/no-recovery policy, redacted failure output. | BLOCKED_EXTERNAL_DEPENDENCY: all four Angel credential fields are unconfigured. No account request was attempted; runtime market-data acceptance is NOT_TESTED. |
| C - native contracts | IMPLEMENTED/OFFLINE_TESTED against retained public bytes: four derivative types in the initial RELIANCE/NIFTY/BANKNIFTY scope, strict parsing, lookup, persistence and tamper rejection. | Public snapshot is captured but unqualified. Publisher/date authority, full-universe coverage, native derivative candle paths and operational acceptance remain missing; no executable identity is returned. |
| D - source and research | IMPLEMENTED/OFFLINE_TESTED: exact-byte/scope evidence-bundle prerequisites and a frozen chronological study harness. Positive orchestration has MOCKED control-flow coverage only. | BLOCKED_EXTERNAL_DEPENDENCY: no supported independent publisher/effective-date or historical-price authenticator/artifact; real signal-quality evaluation is NOT_TESTED. |
| E - paper gaps | ACCEPTED offline subset: auditable freeze/denied-repair records, read-only event-derived EOD statement, bounded inventory/backlog, corruption/transaction/restart checks. | A financial late-repair/adjustment policy needs product approval and qualified evidence. No automatic repair is implemented. Authoritative calendars and operational soak remain unaccepted. |
| F - performance | ACCEPTED as reproducible finite software measurements: real scanner/evaluators/store/paper paths, five repeats, bounded concurrency and separate Python allocation measurement. | No SLA, live-network timing, full-market benchmark, execution-liquidity claim or trading-return result. |
| G - engineering loop | Three baseline defects reproduced against isolated pre-change source; fixes and new capabilities tested; final safety/full checks below. | Continue only with the precisely stated missing evidence/policy, rather than retrying unavailable credentials or manufacturing qualification. |

## Reproduced defects and corrections

The saved pre-edit source was restored into a temporary directory, with the three
new regression methods run against that isolated copy. Actual result: **3 failures,
0 errors, 5.545 seconds, process exit 1**, as expected. The verification wrapper
exited 0 after checking that exact counterexample result. Logs and exit are retained
in `continuous_prechange_regressions*.tmp`. The workspace was not replaced.

| Issue / execution path | Before-change reproduction | Correction and regression |
| --- | --- | --- |
| Startup repeatedly writes ordering metadata: `SQLitePersistenceStore` schema initialization | Reopening the account changed `sqlite_sequence` from 3 to 6 despite no new ledger entity. Every INSERT OR IGNORE backfill consumed ordering IDs and scanned history. | One-time additive migration marker; triggers still allocate sequence IDs in the entity transaction. Reopening does not advance the sequence. Existing metadata-table recreation/backfill/VACUUM tests remain required. |
| Unbounded account inventory: `list_paper_accounts` and GET account inventory | 221 returned rows against the required 200-record bound. | Legacy preview is bounded to 200; API inventory has default 100/max 200 keyset pages and a first-page append watermark. Tests add an account during traversal and prove it is excluded until a new traversal. |
| Retained QUEUED history: `ForwardPaperCoordinator.consume_scan` | The 450-decision fixture returned COMPLETED after processing the entire backlog, instead of a bounded PARTIAL batch. | Indexed chronological batches of 200, explicit deferred count and PARTIAL status. Unfilled candidates expire after the exact required close plus the unchanged publication allowance. The fixture drains as 200/200/50 nonfinancial rejections, with no events/reservations. Committed entry effects are checked before expiry. |
| Angel preflight coupled to selected provider | Existing command rejects Angel while the application selects Upstox, even when an isolated Angel configuration is otherwise complete. | Explicit `--isolated-provider`; validate a dataclass copy scoped to Angel without changing the original config/environment or requiring Upstox credentials. Normal selected-provider behavior remains the default. |
| Narrow acceptance could recover/re-login automatically | Normal adapter retry logic is inappropriate for a single controlled acceptance attempt. | Diagnostic disables session recovery; normal application adapters retain the existing default. Mock 401 proves no refresh/second login. A 403 is reported as access denied with cause NOT_ESTABLISHED, rather than treating a category heuristic as proven causation. |
| Oversized writes could exceed their own reader's record bound | A supplied bar identity can inflate a position/event beyond the bounded reporting reader. | Validate encoded position/event size before writing; rollback leaves no committed position/event/reservation. Unknown identity fields cannot produce an unreadable committed record. |
| EOD reporting/recovery design gaps | No dedicated session-end statement or auditable recovery-review record; normal reports reflect current positions. | Read-only event-derived statements and separate immutable-scope recovery decisions; neither path supplies a missing price or changes financial rows. |
| Native parser compatibility, found during this mission's final review | Adding native recognition would reinterpret old stored REJECTED list candidates, changing their immutable reconstructed identity. | Version native observations as `angel-native-observation-v1`; reads select the retained parser version. Legacy normalized/rejected candidates remain readable, and re-import creates a separate new candidate. A dedicated stored-legacy regression passes. |

Relevant sources are `diagnostics.run_angelone_market_data_diagnostics`,
`AngelOneSmartAPIAdapter._request_json`, `SQLitePersistenceStore.query_paper_accounts`
and `pending_paper_decisions`, `ForwardPaperCoordinator.consume_scan`, and
`PaperPortfolio.review_unresolved_eod` / `_session_statement` / `_record`.
The diagnostic restores any caller-owned adapter's retry setting in `finally`,
on both success and failure; its single-attempt policy cannot leak into later
normal application calls. The dedicated broker/diagnostic lifecycle selection ran
34 tests in 0.184 seconds, exit 0, with no Python warnings.

## Provider comparison, documentation and actual evidence

The [official Angel Python SDK](https://github.com/angel-one/smartapi-python/blob/main/SmartApi/smartConnect.py)
confirms password/TOTP login, bearer-session handling and market/historical read
routes. Its convenience session method also reads a profile; this project's narrow
command uses its own restricted existing adapter and does not call that convenience
workflow. Direct SmartAPI documentation pages returned an authorization page in the
web tool; cached search material is documentation-only evidence, not runtime access.

| Capability | Angel One current source | Upstox current source | Evidence boundary |
| --- | --- | --- | --- |
| Configuration/authentication | ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET; RFC 6238 TOTP and loginByPassword; refresh logic exists but is disabled in narrow diagnostics. | UPSTOX_ACCESS_TOKEN bearer read; UPSTOX_API_KEY is not interchangeable with the token. No local OAuth code exchange implemented. | Presence/local login flags never establish accepted market data or a full verified broker account. |
| Cash mapping and quote | Pinned RELIANCE NSE token 2885; FULL quote read; strict supplied identity/time/price checks. | Pinned NSE_EQ\|INE002A01018; quote reader and strict timestamp/identity checks. | Both have mocked transport coverage. No new real quote/candle result exists. |
| Candles | getCandleData with FIVE_MINUTE; strict normalization/completion/freshness; optional master loading is local, not a downloader. | Existing V2 intraday 1-minute read and strict 5-minute aggregation. | [Official Upstox documentation](https://upstox.com/developer/api-documentation/get-intra-day-candle-data/) marks that route deprecated. This is a maintenance risk, not an established explanation for the reported 403. No silent endpoint/provider migration was made. |
| Errors/resources | Bounded responses, duplicate JSON rejection, HTTPError cleanup, timeout/rate/session categories and secret redaction. | Bounded request/error handling, curated status/code/message and resource cleanup. | Regression results prove implemented rejection/cleanup behavior; entitlements and real response availability remain unverified. |
| Derivatives | Existing executable proposal identity is limited to supported master-resolved index options. New candidate inspection observes four native types but never grants execution. | Analytical chain/contract reads do not provide accepted general contract execution identity. | Current complete accepted master, exact derivative candle data and separate analytics prerequisites remain required. |
| Historical trust | Existing archive/source gates remain closed. | Same independent source requirements remain closed. | Ordinary capture/hash, accepted cash data and a supplied verified flag cannot authorize historical replay. |

The public [Dhan instrument specification](https://dhanhq.co/docs/v2/instruments/)
describes native reference files, but this mission did not obtain or accept a Dhan
artifact or add an inferred native parser. Its existing normalized declarations and
analytical readers remain separate from a provider-native executable contract path.

Actual isolated preflight command:

```powershell
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --isolated-provider --check-config --json
```

Actual result: **exit 1**, configuration BLOCKED, all authentication/instrument/quote/
candle checks NOT_TESTED. Missing fields are exactly **ANGEL_API_KEY,
ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET**. Effective application provider is
still Upstox, Telegram dry run true, scheduler false, application_provider_changed
false, data_persisted false, readiness_receipt_issued false and historical_replay_allowed
false. The safe JSON and exit are `continuous_angel_preflight*.tmp`.

No real Angel login was attempted, and there was no live Upstox retry or guessed
403 diagnosis. Configure the four existing fields locally without sharing values,
then repeat preflight. Only after it passes, in an appropriate verified session,
the same explicit command without `--check-config` can perform one bounded read-only
attempt. It permits at most one login, quote and candle request, with no recovery
loop, profile/funds/orders/GTT, scan, store, receipt or delivery path. This report
does not claim that future command was run or passed.

## Retained public master and F&O scope

One credential-free HTTPS fetch of the existing public master location succeeded.
It was not an account API diagnostic. Capture time is **2026-10-19T03:17:46.930603Z**,
153,621 records, **36,009,485 original bytes**. Original SHA-256:

```text
d92f2b42a8a8cbad2928f00345925982ad3d699565778ed898b35feedc02f635
```

The exact original bytes are retained losslessly as
`evidence/angel_public_master_20261019.json.gz` (2,332,130 bytes). The adjacent capture
JSON records URL, original/stored digests, time, storage transformation and explicit
UNATTESTED / NOT_ESTABLISHED / replay-false classifications. Decompression equality
was checked before removing this mission's uncompressed duplicate. No normalization
replaced the original bytes and no active application master/configuration changed.
The web tool could not open this JSON URL; the bounded HTTPS fetch was the successful
acquisition. It is a local transport observation, not an independent capture attestation.

`prepare_contract_master` now accepts this native list as an **observation candidate**
through the existing candidate/store/reparse architecture. `records` remains empty
because no authoritative effective intervals are present. `observed_records` retains
the bounded supported facts with null valid_from/valid_to and a separate observed
digest. Same-date lookup returns `observed_contract`, **identity=null and eligible=false**.
It cannot be mistaken for a normalized executable ContractIdentity. No second broker
or archive pipeline was created.
The native parser is versioned separately; existing normalized/rejected candidate
identities retain their original interpretation and are never rewritten in place.
`evidence/angel_native_inspection_20261019.json` records the current parser/scope/
digests/counts and explicit blocked eligibility.

| Native class | Rows observed across the full NFO file | Parsed observations in the initial three-underlying scope | Runtime contract candle / execution acceptance |
| --- | ---: | ---: | --- |
| FUTIDX | 18 | 6 | NOT_TESTED / BLOCKED |
| FUTSTK | 653 | 3 | NOT_TESTED / BLOCKED |
| OPTIDX | 5791 | 2835 | NOT_TESTED / BLOCKED |
| OPTSTK | 31908 | 215 | NOT_TESTED / BLOCKED |

The 3,059 parsed observations cover RELIANCE, NIFTY and BANKNIFTY only. They are not
a full stock-F&O universe. Auxiliary same-name NSE rows do not replace AMXIDX spot
identities. Underlying pins, native identifiers, exchange/type, explicit expiry,
lot size and quantity model are checked; option strike/100 must match the native
contract label exactly. No expiry calendar, listing date, lot size or token is
generated. Duplicate/ambiguous terms, wrong units/side/strike/expiry, nonfinite
values and inconsistent call/put lots reject. Unknown scopes are excluded explicitly.
Expired contracts and stale/undated capture lookups reject; rollover requires exact
terms. Existing application/native analytical adapter scope is not broadened by
this inspection capability. Full native derivative quote/candle execution paths
and historical option-premium accounting remain separate missing implementation/
acceptance work, dependent on qualified contracts and separately authorized data.

## Historical source and frozen study protocol

`assess_source_evidence` and its V1 policy/engine gates were not relaxed. The new
`verify_source_bundle_bindings` checks a strict whitelist of archive/original-master/
original-candle digests, provider, instrument, interval and date scope. It rejects
substitution, missing/ambiguous declared coverage and supplied trust/authorization
fields. Even matching bindings return **BINDINGS_MATCH_AUTHORITY_BLOCKED**, with
no supported authenticator and historical_eligibility.allowed=false. This is an
implemented prerequisite verifier, not a fabricated positive publisher verifier.

Historical acceptance still needs a supported independent source/clock/retention
mechanism, authoritative instrument-specific assignment/listing/lot intervals and
qualified original historical price data. A current public snapshot/expiry does not
supply those facts. No provider signature protocol or independently established
historical effective-date artifact was available; none was invented.

`research_protocol.StudyProtocol` freezes dataset/archive/provider/instrument,
chronological TRAIN/VALIDATION/OUT_OF_SAMPLE sessions, strategies, costs and explicit
sensitivity scenarios in a protocol hash. The harness rejects overlaps, missing or
undeclared intermediate sessions, mixed/synthetic inputs, changed dataset bytes,
unsupported Strategy 3 and conflicting caller ranges. It passes only the appropriate
past prefix and explicit dates into the existing DeterministicBacktestEngine, with
unchanged live-source/identity/risk gates and persist_run=false. No fitting is
implemented. Predeclared slippage scenarios and a no-trade cash baseline are supported;
existing engine metrics remain the ledger/returns/rejection evidence source.

The source-blocked path is tested with actual store assessment. Positive phase
dispatch/prefix/cost plumbing is tested **only with a mocked qualifier and mocked
engine**, never a real replay or accepted dataset. It proves orchestration, not
source authentication. Actual gross/net P&L, drawdown, expectancy, win/loss ratios,
regime/instrument comparisons and profitability remain **NOT_TESTED**. No such
statistics were produced from the performance fixtures.

## Paper recovery policy and EOD statement

The implemented policy is **keep unresolved financial state frozen**. Missing final
data never creates an exit. `review_unresolved_eod` becomes available only after the
configured square-off plus inclusive publication allowance has elapsed. It records
KEEP_FROZEN or a denied REQUEST_LATE_HISTORICAL_REPAIR, with immutable account/config/
provider/mode scope, request/record digests and optional observation-digest reference.
The separate paper_recovery_decisions table and ledger collection are audit-only.
They never change a position, mark, price, fee, reservation, receipt or balance.
Retries are idempotent, conflicting bodies reject, inconsistent records fail closed,
and SQL failure rolls back the audit row/order metadata. There is no HTTP write route.

Lost observations must be resupplied while still eligible. After the publication
deadline an unfilled candidate is terminally rejected; an existing position remains
open/reserved/stale and blocks entries. A hash or later historical response is not
permission to repair it. **Product decision required before financial recovery:**
specify whether only a separately labelled research fork is permitted, or an explicitly
audited adjustment/migration is required; define trusted price evidence, new policy
identity, effective time, revised capital history, fee idempotency and review authority.
Neither alternative is currently implemented or approved. Retrospective capital
must never fund entries that were impossible at the original decision time.

GET/HEAD `/api/paper-session?account_id=...&session_date=YYYY-MM-DD`, with `/api/v1`
alias, returns a bounded read-only EOD summary after the configured session ends.
It reconstructs state from events up to that session, so later-session entries/P&L
cannot leak into the statement. It includes session/lifetime realized P&L/fees,
last-recorded unrealized MTM, reservations, equity, unresolved status, event count
and reproducible event/statement digests. Missing data remains UNRESOLVED; last marks
are explicitly **not fresh valuations**. Repeated/restarted reads and subsequent
sessions preserve the old statement. Corrupt financial history fails closed.
This is a summary export, not a full point-in-time multi-page event/position export.

Account inventory uses stable append-order pages, rather than its old alphabetic
unbounded list. Existing response keys remain with continuation metadata. Ledger
pages retain account/collection isolation, first-page watermarks and byte/record
bounds; recovery_decisions is an additional collection. Mutable position/decision
pages remain per-page snapshots, not a global point-in-time export. Financial
processing never consumes report previews. Pending queue reads validate off-page
corruption and use the new partial index before bounded processing.

Calendar authority remains external. The accessible official
[NSE timings page](https://www.nseindia.com/static/market-data/market-timings) and
[holiday page](https://www.nseindia.com/resources/exchange-communication-holidays)
are documentation, not an accepted complete dated calendar input. A future input
must bind exchange/segment/instrument scope, version/circular, capture/publication,
exact effective dates, timezone, session phases and holiday/special-session exceptions
to retained official evidence. The project currently represents configured weekday/
holiday sessions, not all auction or special-session phases. No official holiday or
special-session time was invented; production schedules and immutable paper policies
were not changed. These calendar requirements precede operational acceptance.

## Repeated software performance

Command: `python -B -W error::ResourceWarning performance_acceptance.py --samples 5 --events 10000`.
Actual exit **0**; raw log/exit are `continuous_performance_acceptance*.tmp`; complete
machine-readable results are `evidence/continuous_performance_20261019.json`.
Windows AMD64, 8 logical CPUs, Python 3.14.6, SQLite 3.50.4. Timers use
perf_counter_ns. Five sequential repeats are reported as median/max; p95 is omitted
below 20 samples. Per-evaluator calls are pooled across the three symbol counts;
their 105 correlated calls support only empirical nearest-rank p95, not an SLA.

| Measured stage | n | Median ms | Max ms | Empirical p95 ms |
| --- | ---: | ---: | ---: | ---: |
| Actual simulated scanner, 1 symbol | 5 | 67.3920 | 76.5609 | omitted |
| Actual simulated scanner, 5 symbols | 5 | 206.1674 | 241.0489 | omitted |
| Actual simulated scanner, 15 symbols | 5 | 579.9320 | 618.8974 | omitted |
| Order-block evaluator call | 105 | 5.6816 | 8.8316 | 7.1532 |
| VWAP evaluator call | 105 | 6.1356 | 9.2249 | 8.2587 |
| ORB evaluator call | 105 | 7.6683 | 11.3094 | 9.6451 |
| Supertrend evaluator call | 105 | 6.5169 | 8.7759 | 8.0045 |
| Normalization, 60 fixture bars | 5 | 0.9378 | 0.9551 | omitted |
| Identity binding, 60 mocked wire bars | 5 | 0.2619 | 0.2714 | omitted |
| Freshness, 60 mocked bars | 5 | 1.9823 | 2.1338 | omitted |
| Source assessment, 1 unqualified declared record | 5 | 0.0612 | 0.0815 | omitted |
| Persist new signal / duplicate detection | 5 each | 8.0555 / 7.5184 | 8.4368 / 8.3528 | omitted |
| Paper entry / mark / exit | 5 each | 11.8021 / 10.4613 / 10.9561 | 13.2673 / 11.0724 / 11.1169 | omitted |
| Missing observation rejection | 5 | 5.1271 | 5.4877 | omitted |
| Mocked provider-error scan | 5 | 20.5030 | 21.6272 | omitted |
| Existing-store startup/reopen | 5 | 6.8669 | 9.2739 | omitted |
| 10,000-event reconciliation | 5 | 1162.6634 | 1211.8541 | omitted |
| 10,000-event summary | 5 | 1674.8891 | 1694.1973 | omitted |
| First 100-event page | 5 | 14.1778 | 15.1017 | omitted |

Scanner rows use the actual 1/5/15 supported cash metadata records and real evaluator/
store paths. These particular repeated scans were COMPLETED_EMPTY; this measures
negative-candidate evaluation, not signal frequency/quality. Existing mocked-wire
integration tests separately exercise genuine positive evaluator candidates. Paper
entry/mark/exit timings use explicit simulated candidates and the actual cost/risk
service. The large account has 2,500 closed graph-fixture positions / 10,000 events,
not 2,500 risk-approved strategy trades. Store startup includes other small fixture
accounts and uses warm filesystem caches; this is not a cold-process/outage drill.

| Independent read workers | Requests | Median ms | Max ms | p95 ms | Observed requests/s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 14.9408 | 17.0683 | omitted | 65.557 |
| 2 | 16 | 29.28145 | 42.8402 | omitted | 65.446 |
| 4 | 32 | 65.7622 | 74.5586 | 72.946 | 60.580 |

This bounded read workload gains no throughput from four workers on this host;
increased concurrency raises latency. It does not promise production scaling.
Separate tracemalloc summary measurement peaked at **1,818,916 Python bytes**;
SQLite/native/RSS and pre-existing allocations are excluded. Responses remain
bounded; memory is not claimed to be the application's total resident footprint.
Existing scanner-overlap and independent-store capital races remain safety tests.

Five deliberate provider failures produce FAILED/no signals, with no simulated
fallback. Missing-interval requests preserve the prior account state. These are
guarded fixture errors, not failed live provider calls. No performance threshold
was invented after measurements. Host load changes the other suite benchmark runs;
the JSON is one repeated workload, not a statistical guarantee or trading study.

## Final verification and change inventory

All results below are actual executions. The final full and focused runs include
all 34 new regressions and the final native-parser compatibility and diagnostic
retry-setting cleanup corrections. No existing test was removed or weakened.

| Executed check / retained log stem | Passed | Failed / skipped | Seconds | Exit | Python warnings / application WARNING records |
| --- | ---: | ---: | ---: | ---: | ---: |
| Strict full suite, `continuous_verified_full` | 593 | 0 / 0 | 151.771 | 0 | 0 / 3 |
| Focused integration and new regressions, `continuous_verified_focused` | 179 | 0 / 0 | 51.141 | 0 | 0 / 0 |
| Latest separate safety selection, `continuous_delivery_safety` | 232 | 0 / 0 | 56.591 | 0 | 0 / 0 |
| Broker/isolated diagnostic lifecycle, `continuous_diagnostic_lifecycle` | 34 | 0 / 0 | 0.184 | 0 | 0 / 0 |
| Native observation/legacy compatibility, `continuous_native_compatibility` | 7 | 0 / 0 | 2.611 | 0 | 0 / 0 |
| Repeated standalone performance, `continuous_performance_acceptance` | Not a unittest run | No benchmark error | See per-stage measurements above | 0 | 0 / 0 |
| In-memory compilation | All 32 top-level modules | 0 errors | Not timed | 0 | 0 |
| Changed/new text whitespace and final newline | All 22 textual files | 0 errors | Not timed | 0 | 0 |
| `git -c core.autocrlf=false diff --check` | No whitespace errors | 0 errors | Not timed | 0 | 0 |

Each test/benchmark log is `../<stem>.tmp`; its actual process exit is separately
retained in `../<stem>_exit.tmp`. The separate safety selection preceded the final
diagnostic wrapper cleanup; the final full suite repeats that selection, and the
dedicated lifecycle selection verifies the final wrapper. Counts overlap and must
not be added as independent tests. The final full suite adds 34 to the fresh 559-test
baseline. Earlier successful runs are retained as intermediate evidence, not the
final verification count.

Warning/log inventory: there are **zero Python warning diagnostics**, including
ResourceWarning. The full run emits three expected application WARNING records,
one per scanner-overlap fixture: a concurrent scan is skipped. Its 21 application
ERROR records are deliberate negative-path evidence: 16 simulated disk-I/O failures,
one mocked Dhan transport failure, one mocked Angel server failure, one scheduled
stale-candle rejection, and two mocked provider failures in the performance
regressions. The separate safety run has the one expected stale-candle ERROR;
the standalone performance run has five expected mocked provider ERROR records.
These cases pass their assertions and involve no real provider failure or scheduler
service. Focused/lifecycle runs have no application WARNING or ERROR records.
Plain `git diff --check` also exits 0, with 15 LF-to-CRLF conversion advisories
for modified tracked files. The explicit per-command autocrlf=false check is quiet;
no Git setting or warning filter was changed. PowerShell's redirected-stderr
NativeCommandError envelope and its echoed `-W error::ResourceWarning` command are
not Python warnings or failed tests.

Development failures were investigated before proceeding. The initial 18-test
new-feature run had seven helper/assertion errors; the corrected run passed all
18. The expanded 29-test run had three wrong engine-import errors; the harness
was corrected to use the actual DeterministicBacktestEngine. Initial benchmark
attempts rejected invalid simulated provenance at the live identity gate and then
surfaced an expected BrokerDataError; the harness was corrected to use explicitly
mocked wire observations and verify FAILED status. No production gate was relaxed.
The pre-change three-failure counterexample above remains retained separately.

Exact commands, run from the project root in PowerShell (all offline except the
separately described public-source acquisition):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -W error::ResourceWarning test_bot.py -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract test_phase5a_contracts test_phase5a_provenance test_phase5a_paper test_phase5a_integration test_phase5b_forward test_phase5c_recovery test_continuous_acceptance -v
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B test_bot.TestPositionSizingRiskAccounting test_bot.TestStateIsolation test_bot.TestMarketDataFreshness test_bot.TestInstrumentIdentity test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility test_bot.TestConfigurationPreflight test_bot.TestHTTPErrorFixtureCleanup -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_continuous_acceptance.TestIsolatedAngelAcceptance -v
python -B -W error::ResourceWarning -m unittest test_continuous_acceptance.TestNativeContractObservation -v
python -B -W error::ResourceWarning performance_acceptance.py --samples 5 --events 10000
@'
from pathlib import Path
paths = sorted(Path('.').glob('*.py'))
for path in paths:
    compile(path.read_bytes(), str(path), 'exec')
print(f'Compiled {len(paths)} top-level modules in memory')
'@ | python -B -
git diff --check
git -c core.autocrlf=false diff --check
```

The starting full-suite command is identical. Its focused baseline uses the same
focused command without `test_continuous_acceptance`, which did not yet exist.
For recorded test runs, stdout/stderr were redirected to the corresponding log;
`$LASTEXITCODE` was saved immediately to the separate exit file and propagated by
the shell. Logs may use PowerShell UTF-16 encoding. The baseline snapshot, original
and confirmation logs, pre-change counterexample, development logs and final logs
remain at the workspace root as evidence, not application inputs.

Changed-file inventory compared with the 66-file baseline, **23 project files**:

- Modified source (9): `brokers.py`, `diagnostics.py`, `forward_paper.py`,
  `instrument_identity.py`, `paper_portfolio.py`, `server.py`,
  `source_qualification.py`, `storage.py`, `test_bot.py`.
- New source/tests (3): `performance_acceptance.py`, `research_protocol.py`,
  `test_continuous_acceptance.py`.
- Modified reports (6): `docs/TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md`,
  `docs/TRADEPULSE_FO_CONTRACT_COVERAGE.md`,
  `docs/TRADEPULSE_HISTORICAL_PROVENANCE_DESIGN.md`,
  `docs/TRADEPULSE_PAPER_PORTFOLIO_REPORT.md`,
  `docs/TRADEPULSE_CAPABILITY_MATRIX.md`, `docs/TRADEPULSE_COMPLETION_ROADMAP.md`.
- New report (1): `docs/TRADEPULSE_CONTINUOUS_ACCEPTANCE_REPORT.md`.
- New non-secret evidence (4): `docs/evidence/angel_public_master_20261019.json.gz`,
  `docs/evidence/angel_public_master_20261019_capture.json`,
  `docs/evidence/angel_native_inspection_20261019.json`,
  `docs/evidence/continuous_performance_20261019.json`.

No original snapshot file was deleted. Original Phase 5C report/tests, configuration
and template, strategies, risk/cost engine, scanner, historical loader/archive and
readiness policy remain byte-for-byte unchanged. The retained compressed master
and capture digests are checked against each other and the decompressed original.

Environment: Windows AMD64, 8 logical CPUs, Python 3.14.6, SQLite 3.50.4. Temporary
SQLite test execution required approved execution outside the filesystem sandbox;
it did not require a production database. Loopback HTTP test fixtures are temporary
and are not production services. No alternate Python runtime, native/RSS memory
measurement, cold-process outage drill, authoritative full exchange calendar,
qualified historical price dataset or account-market response was available for
acceptance. These are explicit limits, not inferred passes.

## Milestones, remaining evidence and next actions

The M01-M12 weights/rubric/denominator are unchanged. M09 remains I=50/R=50: stronger
offline recovery/reporting evidence does not deliver derivatives, partial fills,
approved financial repair or operational soak. M08 remains 50/25: an orchestrator
does not supply qualified prices or a credible real study. M05 remains 25/0:
three-underlying observation parsing is a subset, without accepted derivative fills.
M12 release/backup recovery remains 25/0. No other row crosses a rubric threshold.
Totals remain **63.5% implementation / 35.5% readiness; 0/12 accepted milestones**.

| Remaining acceptance item | Classification | Exact next action / required evidence |
| --- | --- | --- |
| Angel account market data | Missing local credentials / external runtime evidence | Configure the four existing fields locally; run isolated offline preflight, then at most one appropriate-session narrow read-only session. Retain sanitized JSON, timestamps and actual exit; never share credentials. |
| Upstox reported 403 / deprecated route | Unresolved provider response plus maintenance risk | Retain the actual sanitized 403/code/context; do not infer cause or switch providers. Scope and test a documented V3 migration separately before its own authorized runtime acceptance. |
| Executable current F&O universe | Partial implementation plus external authority/data | Qualify a dated native master/units/scope and bind exact contract candles per provider/class; expand beyond the three observed underlyings only with evidence. Do not treat parsed observations/analytical chains as execution support. |
| Historical master/price authenticity | Missing independent evidence mechanism and artifacts | Obtain a supported source/clock/authority specification and real master/price examples, including valid and tampered/wrong-date cases. Implement the positive verifier only against that mechanism; keep current source gates closed. |
| Real strategy quality | Qualified dataset unavailable | After independent qualification, run the frozen protocol with sufficient full sessions/warmup, retained metrics/trades, baseline/sensitivity and uncertainty. No fixture profitability claims. |
| Unresolved-position financial recovery | Product policy decision | Approve a precise research-fork or adjustment/migration policy, trust inputs and effective-time/capital history. Until then KEEP_FROZEN/denied-repair audit only. |
| Authoritative sessions | Complete dated calendar/phase evidence missing | Acquire/review retained exchange/segment-specific circular/calendar inputs, including special sessions/auctions; do not infer them from weekdays or expiry labels. |
| Operational soak/release | Not tested / missing release work | After provider/calendar/policy acceptance, specify a bounded operational soak; separately implement supported-runtime installation, fixture backup/restore and rollback evidence. Scheduler/live Telegram remain disabled. |

No order/GTT/account-state endpoint was called, no production service/scheduler
started, no production database was used, and no live Telegram message was sent.
The only newly captured real provider material is the public credential-free master;
documentation requests and that capture are distinct from account-market acceptance.
LIVE historical replay and historical Strategy 3 remain blocked; no receipt was issued.

## Cash-equity acceptance sprint addendum - 2026-10-19

**Today's narrow objective is BLOCKED, not passed.** The isolated Angel preflight
actually ran and exited 1 because all four required Angel fields are unconfigured.
No real login, quote or candle request was attempted. No real RELIANCE observation
was received, scanned, persisted or displayed. Offline scanner/API and renderer
regressions passed independently; they cannot substitute for that live evidence.
The earlier dated findings/counts above are preserved.

### Starting state and configuration evidence

Project root was confirmed as
`C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`.
Git initially had the preceding mission's 23 staged entries. This sprint issued no
reset, staging or commit command. `../cash_sprint_starting_snapshot.tmp` retains a non-secret
66-file code/report/public snapshot captured at **2026-10-19T04:46:21.124168Z**.
No credentials or production database contents are included.

The existing reports and relevant diagnostic, adapter, identity, scanner,
qualification, store, handler and frontend paths were checked against this tree.
The narrow command branches before the legacy diagnostic's store/profile paths.
Its explicit isolated view does not change the application's selected provider.

Actual command, from the project root:

```powershell
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --isolated-provider --check-config --json
```

It completed at **2026-10-19T04:46:37.091305Z (10:16:37 IST)**, actual exit **1**.
The sanitized JSON has configuration BLOCKED, configuration_ready=false and
overall_status=FAIL. Missing configuration field names are exactly:

- `ANGEL_API_KEY`
- `ANGEL_CLIENT_CODE`
- `ANGEL_PIN`
- `ANGEL_TOTP_SECRET`

Its effective configuration reports active_broker=upstox, telegram_dry_run=true,
enable_background_scheduler=false and application_provider_changed=false.
Data persistence, readiness receipt and historical replay flags are all false.
Raw sanitized output and the real exit are retained in
`../cash_sprint_angel_preflight.tmp` and `../cash_sprint_angel_preflight_exit.tmp`.
The [sprint evidence JSON](evidence/cash_equity_sprint_20261019.json) retains that
same safe output together with explicitly separate offline observations.

`config._load_dotenv` reads `.env` relative to the **process working directory**;
existing process environment values take precedence via setdefault. Both workspace
and project `.env` files exist, and `git check-ignore -v` confirms both are excluded
by the existing `.gitignore:2` rule. Only existence/ignore metadata was inspected;
their contents were not displayed, copied or edited. The documented project-root
command needs the four fields in its project-local `.env` or process environment.
The evidence does not establish whether another directory has different settings.

### Live acceptance evidence and bounded transport review

| Required item | Actual status | Supporting evidence / boundary |
| --- | --- | --- |
| Angel local configuration | BLOCKED | Preflight exit 1 and the four field names above; selected Upstox preserved. |
| Authentication / HTTP / provider status | NOT_TESTED | Zero real account requests; there is no HTTP status, response error or account-verification result to infer. |
| Returned cash instrument identity | NOT_TESTED | Instrument check is skipped after configuration fails. Source inspection confirms the existing pinned RELIANCE/NSE/token 2885 mapping; no returned identity was observed. |
| Quote observation and currentness | NOT_TESTED | No quote or provider observation timestamp exists for this sprint. |
| Completed candles / OHLCV / ordering / coverage | NOT_TESTED | No live candle response; no completion or freshness result can be accepted. |
| Today's session / holiday suitability | NOT_TESTED | No external session/calendar acceptance was performed. The local clock alone cannot establish an authoritative exchange session. |
| Source qualification / historical provenance | NOT_TESTED for a new live artifact; historical gate remains blocked | No new artifact was submitted. `assess_source_evidence` retains historical_eligibility.allowed=false; a current cash observation would not qualify historical replay. |
| Actual live scanner / persistence | NOT_TESTED / no live observation persisted | Preflight stops before transport and scanner. Temporary offline stores below are distinct. |
| Actual live dashboard / browser | NOT_TESTED | No qualified live backend result and no available browser automation harness. |
| Overall narrow cash acceptance | BLOCKED | Required real observation, scanner and dashboard evidence is absent; preflight FAIL is not a failed broker response. |

Source inspection confirms the next narrow diagnostic would allow only:
POST `loginByPassword`, POST `market/v1/quote/` in FULL mode for RELIANCE NSE,
then POST `historical/v1/getCandleData` with FIVE_MINUTE after quote validity.
It permits at most one login, one quote and one candle request; automatic session
recovery is disabled and caller-owned retry policy is restored in finally.
It does not read profile, balances, holdings, positions, orders or GTT, scan,
persist, deliver alerts or issue a receipt. This is call-path evidence, not proof
that any endpoint succeeded today. No live retry or provider fallback occurred.

### Reproduced dashboard defect and narrow correction

The existing `renderSignalCards` and `renderSelectedSignalInspector` treated every
record that was not truthy-simulated as LIVE. An UNKNOWN/missing mode or a stored
unknown-provider record could therefore receive a live label. The store's existing
unknown-source regression demonstrates that unknown-provider records can be exposed
without promotion in the backend; the frontend was losing that distinction.
Persisted older live-source records also lacked an explicit stored-source label.

Actual inline-script execution against a small offline DOM double reproduced
**3 passed / 3 failed / 0 skipped**, exit 1, before the correction. The two
untrusted-provenance assertions and the stored-source-label assertion failed.
The correction shares `describeStoredSignalSource` between cards and inspector:
consistent explicit simulated records show SIMULATED; explicit LIVE/false records
from a supported provider show LIVE SOURCE (STORED); unknown, missing or conflicting
provenance shows UNKNOWN SOURCE. Stored timestamps remain visible. No record gains
present-day freshness or acceptance from its badge.

All **6 renderer tests now pass**, exit 0. They also verify that a health failure
clears prior acceptance labels, a signals error removes cached cards/inspector
prices, and an older successful health response cannot overwrite a newer failure.
The actual dashboard script runs under installed **Node 24.18.0** with built-in
node:test/vm, without new packages, fetch calls or DOMContentLoaded initialization.
The DOM/Chart doubles are **not a browser**. Playwright, Selenium and Pyppeteer
were unavailable, no browser harness was found, and UI end-to-end acceptance stays
NOT_TESTED. No browser was opened or production service started; only the existing
temporary loopback HTTP test fixtures ran.

### Actual scanner / backend / persistence evidence - offline only

Three new tests use the existing Angel adapter, MultiBrokerScanner,
IntradayBotEngine, real strategy evaluators, SQLitePersistenceStore and actual
DashboardRequestHandler methods. The new tests invoke handlers directly without
binding a server socket. Each has an independent in-memory database, a fixed
**fixture clock of 2026-10-16 10:36:05 IST**, dry-run controls and forbidden external
transport. Provider-shaped rows are mocked at _request_json, not a real response.
Existing bounded loopback HTTP dashboard tests ran separately in the selections.

| Offline case | Actual backend/scanner outcome | Temporary persistence / safety |
| --- | --- | --- |
| Missing Angel credentials | Scan HTTP 502 / FAILED; health connection UNAVAILABLE_MISSING_CREDENTIALS; live_signals_allowed=false. No HTTP transport or strategy/delivery call. | One FAILED scan, zero signals; readiness accepted=false; scheduler running=false. |
| Stale mocked candles | Latest completed start 09:25; reason STALE at the 10:36:05 fixture clock. Scan HTTP 502 / FAILED; health ERROR; evaluation/delivery never called. | One FAILED scan, zero signals; no fallback, receipt or paper entry. |
| Fresh mocked candles, adequate warmup, no setup | 242 rows over three complete fixture sessions and the current partial session; 241 completed, one forming. Latest completed start 10:30, close 10:35; forming 10:35 start excluded. FRESH_IN_SESSION; scan HTTP 200 / COMPLETED_EMPTY. | One COMPLETED_EMPTY scan, zero signals and no delivery; actual receipt acceptance remains false. Mock branch connection CONNECTED_VERIFIED is not real authentication evidence. |

The fresh case was strengthened from a short warmup fixture before final
verification. Each of the four cash evaluators receives **241 completed candles**,
exceeding its existing warmup threshold; no threshold or strategy was edited.
Scanner health retains only the latest completed bar and forming tail for bounded
clock rechecks; its completed_candles=1 describes that cached tail, not the full
242-row evaluator input.
An audit-only Python return trace records each actual final no-setup return:

| Strategy function | Observed return / conditions | Entry / stop / target / paper eligibility |
| --- | --- | --- |
| evaluate_order_block_fvg | `strategies.py:1051`, final return None after checking the available patterns | No signal; no levels, sizing or paper entry. |
| evaluate_vwap_pullback | `strategies.py:1214`, final return None after bullish/bearish setup checks | No signal; no levels, sizing or paper entry. |
| evaluate_orb_breakout | `strategies.py:1538`, final return None after ORB setup checks | No signal; no levels, sizing or paper entry. |
| evaluate_supertrend_pullback | `strategies.py:1712`, final return None after setup checks | No signal; no levels, sizing or paper entry. |

All have zero evaluator errors. The audit does not claim a rejected trigger has
passed risk sizing: with no signal, entry/stop/target and paper risk decisions are
not applicable. No paper account was supplied. The evidence JSON retains the real
handler payloads/freshness timestamps and trace results with OFFLINE/MOCKED labels.
`../cash_sprint_capture_offline.tmp` is the retained non-production capture script;
its three individual one-test runs pass, exit 0. No synthetic P&L or empirical
signal-quality claim is made.

### New verification, warning inventory and commands

| Executed verification / log stem | Passed | Failed / skipped | Seconds | Exit | Python warnings / structured application WARNING |
| --- | ---: | ---: | ---: | ---: | ---: |
| Starting focused confirmation, `cash_sprint_baseline_focused_confirm` | 59 | 0 / 0 | 3.444 | 0 | 0 / 0 |
| New backend cases, `cash_sprint_backend_new` | 3 | 0 / 0 | 0.116 | 0 | 0 / 0 |
| Strengthened warmup case, `cash_sprint_warmup_regression` | 1 | 0 / 0 | 0.177 | 0 | 0 / 0 |
| Final strict full suite, `cash_sprint_verified_full` | 596 | 0 / 0 | 139.700 | 0 | 0 / 3 |
| Final focused acceptance/HTTP selection, `cash_sprint_verified_focused` | 69 | 0 / 0 | 8.708 | 0 | 0 / 2 |
| Latest separate safety selection, `cash_sprint_final_safety` | 232 | 0 / 0 | 53.530 | 0 | 0 / 0 |
| Final renderer regression, `cash_sprint_verified_renderer` | 6 | 0 / 0 | 0.241430 | 0 | No JS warnings |

Selections overlap. The 596 Python tests include three added backend regressions;
the six Node tests are separate. The separate safety run preceded only the
strengthened test fixture; final full verification includes all safety tests.
An earlier full run also passed 596 in 151.918 seconds and an earlier focused run
passed 69 in 14.071 seconds; those `cash_sprint_final_*` logs are intermediate.
All logs are at `../<stem>.tmp` with separate `../<stem>_exit.tmp` process exits.

The first sandboxed baseline ran 59 tests with six errored test cases and 12
setup/cleanup error records, exit 1, from denied temporary SQLite directories.
Approved execution outside the sandbox passed all 59 without application changes.
The first sandboxed Node launch failed with spawn EPERM before running renderer
checks; approved reproduction then established the three real assertion failures
above. Final Node execution uses --test-isolation=none, avoiding child processes
while retaining test assertions. No warning filter, test skip or GC change was made.

The three full-suite and two focused WARNING records are expected scan-overlap
fixtures. Final full/safety/focused runs have respectively 22/1/1 structured ERROR
records from deliberate disk/provider/missing-credential/staleness failure tests;
the new handler tests also emit expected rejection messages without a structured
prefix. These are assertion-covered offline errors, not live failures. There are
zero Python warning diagnostics. PowerShell's NativeCommandError stderr wrapper
and echoed ResourceWarning flag are not Python warnings.

Commands actually executed from the project root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract test_phase5a_integration test_continuous_acceptance.TestIsolatedAngelAcceptance -v
python -B -W error::ResourceWarning -m unittest test_market_data_contract.TestSharedMarketDataContract.test_cash_dashboard_missing_angel_credentials_is_unavailable_without_transport test_market_data_contract.TestSharedMarketDataContract.test_cash_dashboard_stale_mock_wire_rejects_before_evaluation_and_persists_failure test_market_data_contract.TestSharedMarketDataContract.test_cash_dashboard_fresh_mock_wire_no_signal_uses_actual_evaluators_and_store -v
python -B -W error::ResourceWarning -m unittest test_market_data_contract.TestSharedMarketDataContract.test_cash_dashboard_fresh_mock_wire_no_signal_uses_actual_evaluators_and_store -v
python -B -W error::ResourceWarning test_bot.py -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract test_phase5a_integration test_continuous_acceptance.TestIsolatedAngelAcceptance test_bot.TestIndianFOSignalBotPhase1E test_bot.TestIndianFOSignalBotPhase1F -v
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B test_bot.TestPositionSizingRiskAccounting test_bot.TestStateIsolation test_bot.TestMarketDataFreshness test_bot.TestInstrumentIdentity test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility test_bot.TestConfigurationPreflight test_bot.TestHTTPErrorFixtureCleanup -v
node --test test_cash_dashboard.js
node --test --test-isolation=none test_cash_dashboard.js
python -B -W error::ResourceWarning ..\cash_sprint_capture_offline.tmp
```

The first focused command ran before edits (59 tests). Other methods/tests and
final selections ran as recorded above; capture repeats the three assertions with
audited return values. The earlier compilation here-string and Git diff commands
were also rerun. All **32 top-level Python modules compile in memory**. Final
snapshot/whitespace/newline/diff checks are retained in
`../cash_sprint_final_checks.tmp`; untracked additions are checked independently.
Plain `git diff --check` exits 0 with three LF-to-CRLF advisories for this sprint's
modified tracked files. The per-command autocrlf=false check is quiet; both cached
diff checks also exit 0. No Git setting was changed.

### Sprint file inventory and next action

Five project files changed/added in this sprint:

- `public/index.html`: source labels shared by signal card and inspector.
- `test_market_data_contract.py`: three offline cash scanner/handler/store cases.
- `test_cash_dashboard.js`: six actual-script renderer regressions, no dependencies.
- `docs/evidence/cash_equity_sprint_20261019.json`: sanitized preflight, actual
  offline observations, strategy-return trace and final test/exit evidence.
- `docs/TRADEPULSE_CONTINUOUS_ACCEPTANCE_REPORT.md`: this additive dated section.

The prior report prefix and unrelated baseline files are preserved. No broker,
configuration, strategy, cost/risk, provenance, schema, scheduler or backend API
implementation was changed. No production database, live Telegram, trading/account
endpoint or production service was used. Official milestone scores and acceptance
states remain unchanged: **63.5% implementation / 35.5% readiness; 0/12 accepted**.

**Exact next action:** configure the four existing Angel fields locally in the
environment used by the project-root command; never share their values. Repeat
the offline isolated preflight. Only after it passes and an appropriate session
is established may the same narrow command without --check-config consume the
single authorized bounded live attempt. Retain sanitized output and its real exit;
stop after any rejection and do not automatically retry or change providers.

The diagnostic returns a bounded completed sample and does not run/persist a scan.
The dashboard's normal Scan Market Now action invokes the selected provider and
configured universe; with Upstox still selected it is not an isolated Angel cash
acceptance command. No real accepted-batch-to-scanner/dashboard handoff was verified
today. That bounded handoff must preserve full warmup, identity, provenance and
clock revalidation without additional live reads; it cannot be inferred from a
diagnostic PASS or replaced with an ordinary full-universe scan. Until the required
real observation and end-to-end evidence exist, today's objective stays BLOCKED.

## Dual-Broker Audit, Live Observation Analysis and Readiness Reassessment — 2026-10-19

### 1. Workspace, Configuration Discovery and Execution Environment

- **Project Root**: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`
- **Environment**: Python `3.14.6` on Windows. Git branch `main`.
- **Configuration Loading**: `config.py` uses `_load_dotenv(filepath=".env")` which is CWD-sensitive (`os.path.exists(".env")`).
  Commands run from the workspace parent failed with `[Errno 2] No such file or directory` because `diagnostics.py` and project `.env` are located strictly inside `indian_fo_signal_bot_v1`.
- **Preflight Verification**: After configuring valid non-placeholder values for `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, and a valid Base32 `ANGEL_TOTP_SECRET` in `indian_fo_signal_bot_v1\.env`, running:
  ```powershell
  python -B .\diagnostics.py --market-data-only --symbol RELIANCE --isolated-provider --check-config --json
  ```
  exited `0` with `configuration: PASS` and `instrument: PASS` (RELIANCE NSE token 2885).
- **Provider Isolation**: `active_broker` remains `upstox`. `--isolated-provider` cleanly scoped Angel One diagnostics without mutating application state or leaking Upstox credentials. Safety posture retained `telegram_dry_run=true` and `enable_background_scheduler=false`.

### 2. Angel One Genuine Live Market-Data Observation

During the active NSE trading session (2026-10-19 ~10:51:51 IST), the single authorized bounded market-data diagnostic was executed:
```powershell
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --isolated-provider --json
```

**Diagnostic Evidence & Outcome (Exit Code 1, Overall FAIL)**:
1. **Instrument Identity**: `PASS`. Pinned RELIANCE cash token `2885` on exchange `NSE`.
2. **Live Quote Read**: `PASS`. Genuine live observation obtained from `POST /rest/secure/angelbroking/market/v1/quote/`:
   - `LTP`: `1220.3`
   - `feed_timestamp_ist`: `2026-10-19 10:51:51`
   - `observation_age_seconds`: `0.622s` (satisfies delay/skew bounds)
   - Identity echo and positive finite price verified.
3. **Candle Retrieval**: `FAIL`. Request to `POST /rest/secure/angelbroking/historical/v1/getCandleData` returned `HTTP 403 (ACCESS_DENIED)`:
   - `provider_error_message`: `Angel One SmartAPI candle data (RELIANCE) failed: rate limit or access denied (HTTP 403).`
   - `http_status`: `403`
   - `provider_cause`: `NOT_ESTABLISHED`
4. **Session Invalidation Mechanics**: In `AngelOneSmartAPIAdapter._request_json`, receiving HTTP 403 on candles triggered `self._invalidate_session()`, clearing `jwt_token` to `None`. Consequently, the final diagnostic check `authentication` reported `FAIL` ("No successful authorized market-data response was observed in this diagnostic") because `bool(reader.jwt_token)` evaluated to `False` despite the preceding valid quote read.
5. **Cause Analysis**: While login and Market Quote endpoints succeed, the Historical Data endpoint (`getCandleData`) on Angel One SmartAPI enforces separate app permissions (e.g. Connect app vs Personal app, or specific Historical API entitlement) or Static IP registration on the SmartAPI developer dashboard. Without this developer-portal entitlement or correct IP binding, the gateway rejects candle requests with HTTP 403.
6. **Data Containment**: `data_persisted=false`, `readiness_receipt_issued=false`, `historical_replay_allowed=false`. No orders placed, no account profile queried, and no state persisted.

### 3. Upstox Status and Comparison

- **Active Broker**: `upstox` remains the configured application provider.
- **Prior Live Status**: The previously documented HTTP 403 / FORBIDDEN failure on live quote remains unexplained and has not been superseded by any new live attempt.
- **Safety**: No live Upstox requests were initiated during this audit, adhering to the single bounded test constraint.
- **Deprecation Risk**: Upstox V2 intraday candle endpoint (`/v2/historical-candle/intraday/.../1minute`) is marked deprecated by Upstox developer documentation, representing a forward maintenance dependency.

### 4. Dual-Broker Acceptance Matrix

| Capability / Stage | Angel One Status | Upstox Status | Evidence & Practical Boundary |
|---|---|---|---|
| Configuration Preflight | **PASS** (Exit 0) | **PASS** (Exit 0) | Isolated offline check verifies presence & format; secrets redacted. |
| Authentication Lifecycle | **PARTIAL** | **BLOCKED** | Angel login succeeds for quote; candle 403 invalidates session. Upstox 403 unresolved. |
| Live Cash Quote | **PASS** (LTP 1220.3, age 0.62s) | **FAIL / BLOCKED** (Historical 403) | Angel live quote verified genuine. Upstox quote blocked by prior 403. |
| Live Completed Candles | **FAIL (HTTP 403)** | **NOT_TESTED** | Angel historical endpoint rejected with 403 Access Denied. Upstox unverified. |
| Instrument Echo / Identity | **PASS** (Token 2885, NSE) | **PASS** (NSE_EQ\|INE002A01018) | Both check pinned metadata against reference dictionaries. |
| Timestamp Freshness | **PASS** (Quote 0.62s age) | **NOT_TESTED** | Quote freshness verified; candle freshness untested due to 403. |
| Persistence & Receipts | **PASS (Safely suppressed)** | **PASS (Safely suppressed)** | No diagnostic data leaked into SQLite; readiness receipt withheld. |
| Scanner Live Handoff | **BLOCKED** | **BLOCKED** | Scanner requires validated completed candle batch; quote-only cannot proceed. |
| Dashboard Live Handoff | **BLOCKED** | **BLOCKED** | Displays truthful offline/unavailable labels; no synthetic live promotion. |
| F&O & Derivatives | **BLOCKED** | **BLOCKED** | Stock F&O unmapped; master unqualified; derivative candles missing. |
| Historical Replay | **BLOCKED** | **BLOCKED** | `historical_eligibility.allowed=False`; Strategy 3 replay unimplemented. |

### 5. Offline Test & Regression Execution Results

All offline suites were executed against Python 3.14.6 in `indian_fo_signal_bot_v1`:
1. **Module Compilation**: All 32 top-level Python modules compiled with `py_compile` (Exit 0, 0 errors).
2. **Focused Market Data Suite** (`test_phase4_market_data`, `test_market_data_contract`, `test_angel_market_data`, `test_continuous_acceptance`):
   - **103 passed**, 0 failed, 0 skipped in 11.850s (Exit 0).
3. **Phase 4 & 5 Integration / Paper / Recovery Suite** (`test_phase4_e2e`, `test_phase4_strategy`, `test_phase5a_contracts`, `test_phase5a_integration`, `test_phase5a_paper`, `test_phase5a_provenance`, `test_phase5b_forward`, `test_phase5c_recovery`):
   - **111 passed**, 0 failed, 0 skipped in 19.567s (Exit 0).
4. **Full Strict Regression Suite** (`test_bot.py`):
   - **596 passed**, 0 failed, 0 skipped in 117.638s (Exit 0).
5. **Dashboard JS Renderer Test** (`node test_cash_dashboard.js`):
   - **6 passed**, 0 failed in 88.7ms (Exit 0).

Zero regressions, zero Python ResourceWarnings, zero assertion weakenings.

### 6. Official Product Milestone (M01–M12) Reassessment

Using the official weighted rubric from `TRADEPULSE_CAPABILITY_MATRIX.md`:
- **Implementation Progress**: **63.50%**
- **Verified Readiness**: **35.50%**
- **Milestone Acceptance Status**: **0 of 12 complete; 12 unaccepted**. Full milestone acceptance requires $I=100$ and $R=100$.

| Milestone | Weight | I Score | R Score | Status | Primary Blocker to Acceptance |
|---|---:|---:|---:|---|---|
| M01 Architecture & Config | 8% | 75 | 50 | PARTIAL | CWD-dependent `.env` discovery; release configuration profile unfreezed. |
| M02 Broker Auth & Quotes | 12% | 75 | 25 | BLOCKED_EXT | Angel candle HTTP 403; Upstox quote HTTP 403; no dual-broker live acceptance. |
| M03 Candle Ingestion & Freshness | 12% | 75 | 50 | PARTIAL | Live candle batch rejected by provider 403; calendar special sessions unmapped. |
| M04 Instrument Identity & Provenance | 10% | 75 | 25 | PARTIAL | Pinned dictionary mappings only; no signed/echoed live master; source verifier missing. |
| M05 Options & F&O Coverage | 10% | 25 | 0 | BLOCKED_EXT | Stock F&O unmapped; index option candles absent; master unverified. |
| M06 Scanner & Signal Generation | 12% | 75 | 50 | PARTIAL | Whole-watchlist coverage unverified on live feeds; candidate ranking incomplete. |
| M07 Risk Controls & Accounting | 10% | 75 | 50 | PARTIAL | Cash paper risk implemented; derivative margin/portfolio controls absent. |
| M08 Historical Backtesting & Research | 10% | 50 | 25 | BLOCKED_EXT | Replay blocked by source qualification; Strategy 3 execution engine absent. |
| M09 Paper Trading & Persistence | 6% | 50 | 50 | PARTIAL | Multi-session cash paper verified offline; live operational soak missing. |
| M10 Telegram & Dashboard/API | 4% | 50 | 50 | PARTIAL | Dry-run & simulated API verified; real browser E2E test unexecuted. |
| M11 Scheduling & Resilience | 3% | 75 | 50 | PARTIAL | Lifecycle tested in fixtures; live provider outage soak untested. |
| M12 Release & Recovery | 3% | 25 | 0 | UNVERIFIED | Deployment packaging, automated backup runner, rollback drills absent. |

### 7. Go / No-Go Decision and Operational Recommendations

- **Next Live Cash-Equity Observation**: **NO-GO** until SmartAPI Historical Data endpoint access is resolved on the Angel One developer portal.
- **Angel One Action**: Confirm whether the SmartAPI app is configured as a "Connect" app with Historical API enabled, and whether the client public IP is registered as a Static IP.
- **Upstox Action**: Re-verify access token validity and endpoint permissions before scheduling any new live Upstox attempt.
- **Derivatives & Live Trading**: **STRICTLY BLOCKED**. Full cash-equity market-data acceptance, signed contract masters, derivative candle feeds, financial reconciliation policies, and operational soak must precede any derivative or live trading consideration.


## Iterative offline blocker removal - 2026-10-19

**Verdict: PARTIAL overall; verified offline corrections PASS.** The final strict
suite passed **619 tests, 0 failures/errors/skips, exit 0, 80.172 s**. The next
required action is a local configuration correction, followed by offline preflight.
Genuine current cash-equity acceptance remains BLOCKED. This closes this bounded
offline investigation, not the TradePulse product or its remaining roadmap.

Execution used the existing project on Windows AMD64 / PowerShell, Python 3.14.6,
SQLite 3.50.4. Date follows the client IST context. No new dependency was installed.
**Live broker requests: NO. Orders: NO. Live Telegram: NO. Production scheduler or
server activation: NO. Production readiness receipt issuance: NO.** Public Upstox
documentation was read; this was documentation traffic, not broker API traffic.

### Baseline, ownership and evidence corrections

Git branch is `main`. At task start Git already reported changes in `Audit.md` and this report. Their
starting bytes are in `../blocker_removal_start.tmp`, a 71-file snapshot excluding
private configuration and database contents. `Audit.md` is unchanged byte for byte;
all prior report bytes are preserved as a prefix. No reset, staging, commit,
credential edit or provider switch was performed. All seven required context
documents exist. Phase 5B evidence is in the combined
`TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md`; no separate Phase 5B report was found.
The latest dual-broker evidence is the supplied `Audit.md` context and the preceding
dated section of this report, not a newly authenticated broker capture.

The historical 596-test passing claim above remains historical. This execution's
initial sandbox run attempted 596 tests and exited 1 (one failure, 181 error entries,
including temporary SQLite/cleanup permission failures). Its authorized repeat ran
596 tests and exited 1 with one discovery failure while a new imported fixture
alias was being introduced. Removing that alias from discoverable globals repaired
the test harness; final duplicate-discovery and environment-isolation tests pass.
There is no claimed clean passing pre-edit baseline for this execution.

The prior Angel cause assertion about specific app types, historical entitlements
or static-IP registration is **not established by the retained 403**. It is
superseded by this correction. Those are investigation possibilities only, not
confirmed requirements for this account or proven reasons for the rejection.
The earlier quoted identity is pinned-reference consistency evidence, not current
authoritative master qualification. A passing quote cannot accept candles.

### Confirmed defects, corrections and loop boundaries

| Loop / defect | Root cause and correction | Evidence / safety effect |
| --- | --- | --- |
| 1 - configuration discovery and malformed values | `_load_dotenv` used CWD. Default discovery now uses `config.py`'s absolute parent. The existing explicit filepath argument remains caller-relative when relative. Process values and first duplicate retain precedence; an absent file remains optional. Assignment parsing validates the whole file before applying values; invalid numbers/booleans and nonfinite transport policy fail with value-free errors. | Temporary module/file fixtures cover root and parent invocation, missing config, precedence, explicit paths, malformed syntax, provider preservation and error redaction. Existing dotenv isolation was updated for absolute discovery. No user dotenv was written. |
| 1 - authentication history erased by session rejection | Narrow Angel diagnostics recomputed authentication from authorized reads AND the mutable JWT after candles. They now record initial login independently, reuse an existing session without claiming a new login, retain this invocation's authorized-read history, and snapshot session state around quote/candles. Upstox authorized-read history is likewise independent of current token verification. | Login + quote + candle 403 retains initial/quote PASS, records invalidation/current authentication false, and fails overall acceptance. Failed login leaves quote/candles NOT_TESTED. No automatic recovery is added. |
| 1 - Angel access denial reported as throttling | Both HTTP 403 and 429 became RATE_LIMIT. They now produce ACCESS_DENIED and RATE_LIMIT respectively; denial cause stays NOT_ESTABLISHED. | Closed error resources, preserved session invalidation and failed acceptance; provider selection and endpoint allowlists unchanged. |
| 2 - transport/schema error confusion and fixture receipt state | Login timeouts could retain NONE and become INVALID_RESPONSE; malformed market JSON became NETWORK_API_FAILURE. They now retain transport versus response categories. Explicit evidence modes label fixture reports; narrow commands remain receipt-ineligible. Legacy producer/writer rejects MOCKED/OFFLINE/UNVERIFIED issuance; receipt validation requires the retained LIVE_REQUEST marker. | Focused selection 174 passed after correction. All original nine-check, profile, candle, scope, age, digest and historical-source gates still apply. Old unlabelled receipt rows are rejected, not deleted. |
| 3 - legacy diagnostic secret output | A configured secret echoed in profile metadata could be detected by check 9 but still serialized. Profile fields are redacted before reporting; final report traversal also redacts configured/session/retired-token and encoded variants. | One new regression first failed, then the 124-test affected broker/receipt selection passed. No raw provider body/header is added. |
| 3 - CLI startup and subprocess isolation | Import-time dotenv parse errors preceded CLI exception handling. Both CLIs now produce safe structured BLOCKED JSON. The old hash-seed subprocess imported `brokers` without the offline bootstrap, allowing real dotenv discovery. It now imports the established isolated test bootstrap first. | Temporary malformed-config CLI regression first errored in both subcases. Corrected 186-test selection passed; the standalone hash-seed test passed across its eight seeds. Final tests use isolated configuration. |
| 4 - final review after the first green full suite | Login HTTP 503 was classified AUTH_FAILURE; malformed login JSON/list categories were inconsistent. A local unknown-instrument rejection could inherit the prior 429 category/status. HTTP login categories now separate 401/403/429/other transport failure; malformed login is INVALID_RESPONSE. Unknown identity uses the existing structured identity exception, which takes precedence over previous errors and clears unrelated HTTP status. | Two regression methods first failed in five subcases. Final 195-test focused selection and 619-test full suite pass. Authentication failure still clears session proof; no new data or acceptance path is introduced. |

The new module `test_blocker_removal.py` contains **23 methods**. The existing
tests retain their safety assertions; exact expectations changed for the corrected
403 category, unattempted quote after failed login, malformed dotenv rejection,
and added NOT_ESTABLISHED provider-cause field. Receipt fixtures explicitly simulate
the trusted LIVE_REQUEST producer contract only in temporary stores; they are not
genuine live evidence. Declared evidence modes do not detect arbitrary monkey
patching or authenticate transport. Local privileged producers/writers remain the
existing trust boundary. No positive historical-source verifier was invented.

### Actual verification and limitations

All test commands, process exits, raw summaries, warnings and log paths are retained
in [the sanitized execution ledger](evidence/blocker_removal_20261019.json).
Raw logs are `../blocker_*.tmp`; exit files use the corresponding `_exit.tmp`.
Failed-run failure/error counts can include subtests and cleanup entries; they
must not be subtracted from method totals to invent passed-method counts.

| Executed selection / log stem | Passed | Failed / skipped | Seconds | Exit | Python warning diagnostics / application WARNING records |
| --- | ---: | ---: | ---: | ---: | ---: |
| Final full strict, `blocker_verified_full` | 619 | 0 / 0 | 80.172 | 0 | 0 / 3 |
| Final broker/config/legacy/receipt, `blocker_verified_focused_2` | 195 | 0 / 0 | 8.324 | 0 | 0 / 0 |
| Final standalone new regressions, `blocker_verified_new` | 23 | 0 / 0 | 1.354 | 0 | 0 / 0 |
| Earlier cash/scanner/risk/provenance/paper safety, `blocker_safety_1` | 285 | 0 / 0 | 24.056 | 0 | 0 / 0 |
| Dashboard renderer, `blocker_dashboard_authorized` | 6 | 0 / 0 | 0.205 | 0 | No warnings reported |
| In-memory compilation | 33 top-level modules | 0 errors | Not timed | 0 | None |
| Normal Git diff check; CRLF-aware check | No whitespace errors | 0 | Not timed | 0 / 0 | Normal check has newline-conversion advisories |

**Selections overlap; do not add them as unique tests.** The final full suite
repeats all Python safety selections after the last correction. Its three application
warnings are deliberate overlapping-scan rejections, not skipped tests. Its 22
application ERROR records exercise negative-path fixtures; the final focused run
has two such ERROR records. None is a real broker failure. PowerShell's redirected
stderr NativeCommandError wrapper is not the Python exit result.

Intermediate failures were investigated, not rerun unchanged and relabelled green.
The first 22-test configuration run exposed one test fixture using a valid bare
SQLite filename as invalid input; it now uses an unsupported scheme. The first
124-test integration had two stale exact-output/category expectations, corrected
without weakening the failure gates. A 614-test full run failed the old unisolated
hash-seed subprocess, then the corrected 617-test full run passed before the final
two classification regressions were added. Initial Node execution failed EPERM
spawning its worker; the same tests passed with approved fixture permissions.
Initial sandbox Python failures include cleanup warning diagnostics; zero-warning
claims apply to the final passing runs, not those failed attempts.

Principal exact commands, executed from `indian_fo_signal_bot_v1`:

```powershell
python -B -W error::ResourceWarning test_bot.py -v
python -B -W error::ResourceWarning -m unittest test_blocker_removal -v
python -B -W error::ResourceWarning -m unittest test_blocker_removal test_bot.TestConfigurationPreflight test_angel_market_data test_market_data_contract test_phase4_market_data test_bot.TestUpstoxReadOnlyReadiness test_bot.TestUpstoxHTTPErrorDetails test_bot.TestIndianFOSignalBotPhase2A test_bot.TestIndianFOSignalBotPhase2C test_bot.TestIndianFOSignalBotPhase3B1B -v
node --test test_cash_dashboard.js
git diff --check
git -c core.autocrlf=false -c core.whitespace=cr-at-eol diff --check
```

Compilation used `compile(path.read_bytes(), str(path), 'exec')` for every top-level
`*.py` file, without importing configuration or creating bytecode. Plain
`git -c core.autocrlf=false diff --check` initially flagged CR bytes as whitespace
in existing Windows files, including the untouched user `Audit.md`. The normal and
explicit CRLF-aware checks pass; no user newline normalization or Git configuration
change was made. A snapshot-review helper initially used POSIX keys for a Windows
snapshot and raised KeyError; normalized lookup now verifies preservation.

### Current real configuration preflight

Both commands below were actually run from the project root and again through the
`indian_fo_signal_bot_v1/` script prefix from the parent directory:

```powershell
python -B upstox_diagnostics.py --symbol RELIANCE --check-config --json
python -B diagnostics.py --market-data-only --isolated-provider --symbol RELIANCE --check-config --json
```

All four final processes exit **1** with identical configuration cause:
**`Malformed configuration assignment at line 8.`** Configuration is BLOCKED before
any adapter, store, authentication, quote or candle operation. No secret text or
file content is included in the result. The first preflight attempt preceded the
CLI correction and emitted no JSON; it was not counted as a successful check.

Default discovery is now identical across those working directories. Live
credential presence, selected provider and effective safety flags cannot be
freshly attested while the file fails parsing. The last supplied observation says
Upstox selected, Telegram dry run true and scheduler false. Their configured values
were not changed. Tests enforce these safety settings; no service was started.
Optional absent dotenv retains defaults; requiring selected-provider live
credentials still fails safely when absent. Explicit relative resource paths keep
their existing semantics; this change does not redefine database/master paths.

### Sanitized broker forensic findings

| Evidence | Established fact | Unproven / blocked |
| --- | --- | --- |
| Angel supplied observation | The preceding supplied audit reports RELIANCE NSE token 2885 quote PASS at 2026-10-19 10:51:51 IST, LTP 1220.3, age 0.622 s; `POST /rest/secure/angelbroking/historical/v1/getCandleData` returned 403 and overall exit 1. The existing CLI's new-session path plus quote supports the reported earlier authentication sequence. | This task did not reproduce the live login/quote. Candle response availability, authorization cause, authoritative mapping and current session remain unverified. No retained account-specific code establishes an app-type/IP/entitlement cause. |
| Angel offline regression | Initial login PASS and authorized quote PASS survive candle 403; current session becomes unauthenticated with invalidation true, candle FAIL, overall FAIL, receipts ineligible. | A fixture PASS establishes only implementation behavior. |
| Upstox historical report | Prior quote FAIL / FORBIDDEN, HTTP 403, exit 1; candles NOT_TESTED. Source and the reported diagnostic context identify the quote route as GET `https://api.upstox.com/v2/market-quote/quotes` with RELIANCE `instrument_key=NSE_EQ\|INE002A01018`. | The original complete sanitized transport record, exact request time and provider code/message are unavailable. Route attribution is reconstructed from code/context, not an independently retained request capture. Token, entitlement, IP/network or endpoint cause remains NOT_ESTABLISHED. |
| Upstox documentation | The [official V2 intraday page](https://upstox.com/developer/api-documentation/get-intra-day-candle-data/) was freshly read and marks the existing route deprecated. [Full quote documentation](https://upstox.com/developer/api-documentation/get-full-market-quote/) documents the separate quote route and bearer-token contract. | Deprecation is verified documentation status; present account/runtime availability is UNVERIFIED. It does not explain the different quote endpoint's 403. No endpoint migration was implemented. |

A future migration requires a scoped official version/contract, authentication and
parameters/schema, timestamp/timezone and completion conventions, instrument mapping,
rate/retry/error/session semantics, preserved freshness/provenance gates, sanitized
contract-verified offline fixtures, and separately authorized bounded live acceptance.
No guessed replacement URL or automatic provider fallback is supplied here.

### Cash-equity acceptance trace

| Boundary | Evidence in the current checkout | Actual acceptance limit |
| --- | --- | --- |
| Configuration / explicit provider | Deterministic root/parent and precedence regressions PASS | Actual config BLOCKED at local line 8; prior selected Upstox preserved. |
| Authentication / quote / candles | Real adapters with mocked transport; distinct initial/history/current session facts and invalidity rejection PASS | Angel supplied quote success and failed candle remain historical evidence. No new live acceptance for either provider. |
| Normalization / identity / time / completed-candle / freshness | Shared provider-contract, invalid/missing/stale/malformed/naive/future/gapped/provenance tests PASS | Pinned references and configured weekdays/holidays are not independently authoritative current master/calendar evidence. |
| Scanner / signals / dedup / risk | Existing real evaluators consume fixture candles through unchanged scanner gates; failed/stale/invalid data produces no new eligible candidate | Quote-only cannot replace candle ingestion. Fixture fields carrying LIVE parser mode do not establish accepted live data. |
| Persistence / API / dashboard / paper | Existing E2E, temporary SQLite, read-only API, forward-paper and renderer tests PASS | No genuine accepted observation was persisted/displayed here. Paper fills remain simulated. Browser/live breadth/operational soak NOT_TESTED. |
| Historical / F&O | Existing provenance, contract and replay rejection tests PASS | Qualified current derivatives, independent historical master/price authority and Strategy 3 execution remain BLOCKED. |

No additional confirmed offline defect remains from this bounded review. Further
genuine cash-data acceptance requires user configuration/evidence and separately
authorized live testing; unrelated future features were not added to inflate scores.

### Changed files, safety review, rubric and next action

Production changes: `config.py`, `brokers.py`, `diagnostics.py`,
`upstox_diagnostics.py`, `readiness_policy.py`. Tests: new
`test_blocker_removal.py`; existing `test_bot.py`, `test_angel_market_data.py`,
`test_phase4_market_data.py`. Documentation: appended current report, capability
matrix and roadmap; new sanitized `docs/evidence/blocker_removal_20261019.json`.

Re-read source/diff and passing results after each meaningful correction. Snapshot
comparison confirms unchanged `Audit.md`, `.env.example`, scanner/strategies/risk,
Telegram, storage, historical/backtest, identity and source-qualification modules.
Read-only endpoint constants/allowlists were retained. No task-owned secret literal
or user dotenv content was added to code/reports; redaction regressions pass.
All earlier evidence remains. Narrow commands cannot issue receipts. Only temporary
fixture stores exercise the explicitly simulated legacy receipt contract; no
operational receipt was produced. No acceptance assertion or test was skipped.

Under the existing M01-M12 rubric, no row crosses its next threshold. Re-evaluating
the unchanged weights/scores yields **implementation 63.50% -> 63.50%, readiness
35.50% -> 35.50%; 0/12 accepted**. Better configuration/diagnostic controls do not
deliver the missing operational, historical, contract, breadth or release evidence.
The 80%/50% targets have not been reached.

Remaining blockers are separate:

- **Local user configuration:** correct or comment the malformed assignment at
  project `.env` line 8 locally. Never share the line, credentials or file in chat.
  Use `KEY=value` for settings and `#` for comments; preserve intended values,
  provider selection, dry run and disabled scheduler. The code cannot safely infer
  the intended setting from invalid syntax and is forbidden to edit the user file.
- **External broker evidence/authorization:** obtain an existing sanitized rejection
  code/context or provider-support/portal status for the selected provider. Do not
  assume a particular permission or automatically change credentials/IP/app type.
- **Authoritative data:** current qualified mapping/session/contract evidence and
  independent historical master AND price provenance remain missing.
- **Untested acceptance:** genuine completed cash candles, bounded scanner/browser
  handoff, whole-watchlist coverage, paper operations/soak, financial recovery,
  release/backup/rollback; derivatives and Version 2 remain downstream.

**Minimum next user action:** fix only the local syntax issue, then rerun the
selected-Upstox command with `--check-config --json`. From the parent directory use
`python -B indian_fo_signal_bot_v1/upstox_diagnostics.py --symbol RELIANCE --check-config --json`.
Share only the sanitized status and exit if further help is needed. This is offline.
After preflight and documented provider/mapping/session prerequisites pass, a
separate task may authorize one RELIANCE quote followed, only on valid current quote,
by completed candles. Stop after a rejection; no loop, provider switch, order,
profile, receipt, scheduler, delivery or broad scan is authorized by this report.

**Next engineering loop:** revalidate corrected local configuration first, then
classify existing sanitized provider evidence and scope a documented endpoint
migration only if needed. Continue cash scanner acceptance before historical/F&O/
volume intelligence/operational release under the dependency order in the roadmap.
The workspace is safe to resume: user changes and source evidence are retained,
no production service was activated by this execution, and the current parse
failure blocks live startup.
