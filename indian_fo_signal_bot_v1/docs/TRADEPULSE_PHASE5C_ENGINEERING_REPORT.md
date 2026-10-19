# TradePulse AI - Phase 5C engineering evidence

2026-10-19, Windows PowerShell, Python 3.14.6. This is **offline paper-system
acceptance in the scope below**. Real broker acceptance, market liquidity,
operational profitability and exchange-calendar authority are not established.
Earlier Phase 5A/5B reports remain historical evidence, not substitutes for this run.

## Baseline and scope

Before source edits, `../phase5c_baseline.tmp` captured the bytes of 64 non-secret
source/template/documentation files. It excludes `.env` and database contents.
Comparison against that snapshot attributes this package independently of Git.
The freshly executed strict baseline was **539 passed, 0 failed, 0 skipped,
121.048 seconds, exit 0**. The paper/integration/forward baseline was **46 passed,
6.351 seconds, exit 0**. All **28** then-existing top-level modules compiled in memory.
Baseline Python warnings: **0**; application WARNING records: **3**, all expected
scanner-overlap rejection fixtures. The focused baseline had no warnings.

Only these project files change in this package:

| File | Change |
| --- | --- |
| `paper_portfolio.py` | Stream position/event reconciliation and Decimal summary accumulation; bounded previews; fail-closed malformed ledger reporting; direct service candidate size bound; coordinator open-position input independent of previews. |
| `storage.py` | Additive ordering metadata, transactional insert triggers and account indexes; bounded, scoped keyset queries. Existing paper-table column layouts are preserved. |
| `forward_paper.py` | Use full operational open-position input; stream terminal decisions instead of retaining the entire decision history. Pending decisions retain the existing chronological policy. |
| `server.py` | Read-only GET/HEAD paper-ledger route and query/error handling. |
| `test_bot.py` | Include the new module once in the established suite; discovery guard remains. |
| `test_phase5c_recovery.py` (new) | 20 deterministic multi-session/fault/pagination/large-ledger regressions. |
| This report (new) | Current evidence, limitations and acceptance decision. |
| `TRADEPULSE_PAPER_PORTFOLIO_REPORT.md` | Current reporting, session/recovery behavior and limitations. |
| `TRADEPULSE_CAPABILITY_MATRIX.md` | Phase 5C evidence and unchanged milestone scores. |
| `TRADEPULSE_COMPLETION_ROADMAP.md` | Close the scoped offline exercise and name remaining acceptance work. |

The three companion documents are under `docs/`. No configuration, broker,
strategy, sizing, costs, provenance or historical execution policy was edited.
Comparison artifacts/logs under the workspace root are not application inputs.
The nine evidence artifacts added there are `phase5c_baseline.tmp`,
`phase5c_baseline_full.tmp`, `phase5c_baseline_focused.tmp`,
`phase5c_development_tests.tmp`, `phase5c_focused.tmp`,
`phase5c_recovery_final.tmp`, `phase5c_final_full.tmp`,
`phase5c_final_focused.tmp` and `phase5c_final_safety.tmp`.

## Confirmed defects corrected

`PaperPortfolio._snapshot` previously materialized every position and every event,
although it returned only 200 events. `_reconcile_checked` repeatedly filtered the
whole event list for each position: O(positions * events), with full-ledger memory.
Reports had no continuation for truncated decisions and unbounded positions.

Reconciliation now streams positions and indexed per-position events, retaining
one entry, exit and last mark rather than all observations. Account aggregates use
Decimal accumulators with the existing cent rounding; no floating SQL aggregate
or second balance system was introduced. Orphan/scope/lifecycle checks and cost,
net P&L and reservation recalculation remain. A mark after exit also rejects.
Malformed/oversized record parsing fails closed; unusable summaries return
RECONCILIATION_REQUIRED with null accounting rather than fabricated zero equity.

Bounding position previews would make a coordinator that consumed those previews
miss open positions. `open_positions()` now supplies its operational input;
`test_coordinator_uses_open_positions_even_when_report_preview_omits_them` proves
mark/exit processing works even with every preview omitted. The legacy open-fill
capital-release guard likewise inspects the full position stream.

## Session, EOD and recovery evidence

The established convention is **the aware observation clock converted to IST,
then its calendar date**. There is no roll-back to the last trading session during
weekends or before market open. Daily entries and realized exit-date P&L reset at
IST midnight; lifetime realized P&L, fees, equity and reservations do not. Current
open net MTM, including estimated close costs, remains in the new day's loss test.
Tests cover 18:29:59 UTC to 18:30:00 UTC and a Friday-to-Monday boundary.

Default square-off consumes the actual completed **15:15-15:20** observation.
The existing permitted observation delay is inclusive through **15:21:00 IST**
(60 seconds); 15:21:00.000001 rejects. Incomplete, missing, out-of-sequence and
stale bars cannot close or refresh a position. A later fresh 15:20-15:25 candle
cannot replace a missing required EOD candle. An earlier stop/target still takes
precedence under the unchanged model.

A missing final observation leaves OPEN status, its last real mark and reservation,
no settled exit fees, and UNRESOLVED_EOD_POSITION/MISSING_OR_STALE_MARKS entry blocks.
This survives restart and the next session. Yesterday's late candle fails freshness;
today's candle cannot fill yesterday's missing interval. Reconciliation reports
the structurally consistent open ledger; it **does not resolve the missing exit**.
No manual adjustment or late historical repair policy is implemented. Such an
account remains frozen until a separately specified recovery policy is approved.
Normal EOD followed by next-session entry is separately tested and preserves
lifetime accounting while resetting daily limits.

Fixtures use declared weekday sessions and an explicit test holiday, never an
invented authoritative holiday/special-session calendar. Prices are labelled
SIMULATED fixture values, not broker observations or execution evidence.

| Interruption / race | Evidence and durable result |
| --- | --- |
| Before observation / after receipt before consumption | Restart reconstructs the queued decision; consuming the same observation once then restarting produces identical accounting and one fill. |
| Candidate insertion | SQL abort creates no candidate decision or capital effect. |
| Reservation/position insertion, initial position update, mark event, entry event, FILLED decision update | SQL trigger failures roll back the whole transaction; reopening an independent store gives the exact prior report. Retry succeeds without orphan reservations. |
| Later mark update/event | Rollback retains prior mark and reservation; committed retry is idempotent; conflicting content under the same key rejects. |
| EOD position update, after closed snapshot/fee computation, before EXIT event | Abort rolls back capital release and all settled effects. Fee-computation exceptions also preserve committed state. |
| After commit before reporting callback | Deliberate reporting failure leaves exactly one committed position/decision/event pair; restart with no new price recovers unchanged accounting. |
| Duplicate EOD/exit after restart | Returns the committed effect, with fees charged once and reservation zero. New exit/mark commands cannot resurrect CLOSED. |
| Concurrent mark versus exit across stores | SQLite serializes transitions; one same-interval command wins, the other rejects. A subsequent valid exit leaves a reconciled closed position. |
| Concurrent capital allocation | Existing Phase 5A/5B independent-store/coordinator races remain in the focused/full run and prove aggregate capital cannot be spent twice. |
| Repeated reports | Identical state, no writes or new market observations; existing concurrent read-snapshot test remains passing. |

These are controlled exception/SQL-abort tests at durable boundaries, not OS
power-loss, filesystem corruption, broker-outage or backup/restore drills.
Receipt alone does not persist a candle inbox. The caller must resupply that
observation while it is still eligible; loss or late resupply leaves the account
deferred/frozen under the existing freshness and missing-interval gates.

## Bounded API and query plans

GET/HEAD `/api/paper-ledger` and `/api/v1/paper-ledger` accept exactly `account_id`,
optional `collection` (`events`, `positions`, `candidate_decisions`), `limit`
(integer 1-200, default 100), and `cursor`. Duplicate/unknown query arguments and
invalid limits/cursors return 400; a missing account returns 404 without creation.
Malformed or oversized persisted page bodies return a generic 503 /
RECONCILIATION_REQUIRED without echoing the stored body. HEAD is body-free and all
these reads retain `Cache-Control: no-store`. There is no write or export endpoint.

The cursor contains version, account, collection, last sequence and a first-page
upper watermark. Durable INTEGER PRIMARY KEY AUTOINCREMENT sequence metadata is
inserted in the same transaction as its entity, including rollback. Additive
backfill orders prior rows by their existing append rowid. Restart/migration and
VACUUM preserve page order. Cross-account/collection cursors reject. Appends after
the watermark are excluded until a new traversal; all 10,000 events are visited
once with no gaps/duplicates. Sequence gaps are allowed. Cursors are not credentials
or access-control tokens. Existing localhost binding/access assumptions remain.

Membership is pinned, **mutable position/decision bodies are current at each page's
own SQLite read snapshot**. This is not a point-in-time full-account export.
Existing portfolio keys remain, with previews capped at 200 records and 256 KiB
per collection, explicit totals/truncation flags and `ledger_page_path`. Small
accounts keep their complete lists. Operational logic never uses those previews.
Bodies over 512 KiB are rejected before decoding; JSON output expansion is checked
too. Ledger items occupy at most 900 KiB plus bounded metadata, below 1 MiB in
tested responses; byte-budget pagination can return fewer than `limit` records.
No API response materializes the entire event history. The account inventory route
remains unpaginated; the coordinator retains all currently QUEUED decisions for
chronological processing, so an unbounded pending backlog is still a scaling limit.

Actual `EXPLAIN QUERY PLAN` in the fixture selects:

```text
SEARCH o USING INDEX idx_paper_ledger_page
  (account_id=? AND collection=? AND sequence_id>? AND sequence_id<?)
SEARCH t USING INDEX idx_paper_events_account
  (account_id=? AND event_id=?) LEFT-JOIN
SEARCH paper_events USING INDEX idx_paper_events_position
  (account_id=? AND position_id=?)
```

The page query uses keyset bounds, never OFFSET/full-history JSON loading. The
per-position event stream is account-scoped and index ordered. Summary/reconciliation
still read the account history in O(events + positions); they are not constant-time
materialized balances. Startup currently checks/backfills ordering metadata on
each store initialization; no unlimited-history latency guarantee is made.

## Measured synthetic ledger exercise

Dedicated 20-test run: `../phase5c_recovery_final.tmp`, exit 0, 18.247 seconds.
Each size has four events per closed position (initial MARK, ENTRY, later MARK,
EXIT), generated from a real service-produced cash lifecycle and deterministically
cloned onto supplied weekday fixture timestamps. Clones have unique position,
candidate and event identities. The large fixture tests persisted graph structure
and arithmetic; bulk insertion does not re-run scanner/strategy/risk acceptance
for 2,500 trades. It cannot support returns or market-data claims. The smaller
fault and scanner tests exercise the actual transition methods.
The large decision rows are separate terminal REJECTED reporting fixtures, not
claims of 2,500 scanner-generated decisions linked to those lifecycle graphs.

Timings are **measurements only**, not passes against an undefined SLA. No latency
threshold was selected after observation. Timers include local SQLite connection
work; startup is independent-store initialization plus immutable account reopening.
Reconciliation verifies recovered state; summary includes reconciliation and JSON
preview construction. JSON encoding/network latency is not in the summary timer.
Accounts share a temporary store that retains earlier fixture sizes: total store
events at each startup are 100, 1,100 and 11,100; the table's event/position/decision
counts and read timings scope the selected account. This also exercises isolation
from other accounts. No production database was used.

| Events | Positions / decisions | Startup ms | Reconcile ms | Summary ms | First event page ms | First decision page ms | Summary bytes | Event page bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 25 / 25 | 10.959 | 11.969 | 33.882 | 7.100 | 2.890 | 400353 | 237682 |
| 1000 | 250 / 250 | 16.654 | 104.294 | 165.302 | 12.120 | 4.739 | 551953 | 237897 |
| 10000 | 2500 / 2500 | 117.216 | 1386.387 | 2075.567 | 17.859 | 7.803 | 552767 | 238028 |

The final full-suite repeat at 10,000 account events measured startup 202.263 ms,
reconciliation 2,846.992 ms, summary 3,652.264 ms, event page 26.683 ms and decision
page 12.960 ms. The 98-test focused repeat measured 188.345 / 2,479.929 / 4,263.200 /
32.185 / 13.815 ms respectively. These varying host measurements are retained in
their logs; the dedicated table is one run, not a statistical latency claim.

Hard assertions check exact event/position counts, net P&L and fees multiplied from
the validated template, zero closed reservations, reconciliation OK, stable complete
event/position/decision traversal, account isolation, response bounds and indexed
plans. A separate 50,000-byte-per-decision fixture exercises byte-limited pages.
Malformed and oversized/Unicode-expanding bodies fail closed without stuck cursors.
Only these finite sizes and this host/runtime are evidenced; no long-running
operational soak, memory-profiler measurement or production concurrency SLA exists.

## Verification delivery

All tests below actually ran. Focused selections overlap the full suite and must
not be added together as unique tests. None failed or skipped in the final runs.

| Run / root log | Passed | Failed / skipped | Seconds | Exit | Python warnings | Application WARNING records |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline full, `phase5c_baseline_full.tmp` | 539 | 0 / 0 | 121.048 | 0 | 0 | 3 |
| Baseline paper/integration/forward, `phase5c_baseline_focused.tmp` | 46 | 0 / 0 | 6.351 | 0 | 0 | 0 |
| Final Phase 5C, `phase5c_recovery_final.tmp` | 20 | 0 / 0 | 18.247 | 0 | 0 | 0 |
| Final full, `phase5c_final_full.tmp` | 559 | 0 / 0 | 146.190 | 0 | 0 | 3 |
| Final contract/provenance/paper/integration/forward/recovery, `phase5c_final_focused.tmp` | 98 | 0 / 0 | 40.756 | 0 | 0 | 0 |
| Final safety selection, `phase5c_final_safety.tmp` | 232 | 0 / 0 | 68.655 | 0 | 0 | 0 |

The three full-suite WARNING records all say a scan was skipped because another
scan is already in progress; they are expected overlap-test evidence, also present
in the fresh baseline. There are no remaining Python/ResourceWarning diagnostics.
Normal `git diff --check` exits 0 with **8 LF-to-CRLF policy advisories**, one for
each modified tracked file in the inventory (not the two new files). No whitespace
error is reported. `git -c core.autocrlf=false diff --check` exits 0 without those
advisories; repository Git configuration was not changed. A separate whitespace /
final-newline check covers all **10** files, including the two untracked additions.
In-memory compilation of all **29** final top-level Python modules exits 0.

An early development-only 15-test run had 14 successes and one fixture error:
seeding a second account twice reused a unique decision key. The fixture now
continues its sequence; no production assertion, warning policy or resource control
was weakened. A subsequent 64-test intermediate run passed before the last two
session-boundary cases were added. Final counts above supersede those runs.

Run from `indian_fo_signal_bot_v1`; **all commands here are offline**. Actual test
processes set `PYTHONDONTWRITEBYTECODE=1`, used `2>&1 | Tee-Object -FilePath` to retain
the named root logs, and propagated `$LASTEXITCODE`. Core test commands were:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'

# Full command: both the pre-edit baseline and final run.
python -B -W error::ResourceWarning test_bot.py -v

# Fresh pre-edit focused baseline (46).
python -B -W error::ResourceWarning -m unittest test_phase5a_paper test_phase5a_integration test_phase5b_forward -v

# Final dedicated Phase 5C exercise (20), including the benchmark.
python -B -W error::ResourceWarning -m unittest test_phase5c_recovery -v

# Final focused scope (98).
python -B -W error::ResourceWarning -m unittest test_phase5a_contracts test_phase5a_provenance test_phase5a_paper test_phase5a_integration test_phase5b_forward test_phase5c_recovery -v

# Final safety selection (232).
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B test_bot.TestPositionSizingRiskAccounting test_bot.TestStateIsolation test_bot.TestMarketDataFreshness test_bot.TestInstrumentIdentity test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility test_bot.TestConfigurationPreflight test_bot.TestHTTPErrorFixtureCleanup -v

@'
from pathlib import Path
for path in sorted(Path('.').glob('*.py')):
    compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
'@ | python -B -

git diff --check
git -c core.autocrlf=false diff --check

# Configuration-only branches: no adapter/network/store/receipt path.
python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --check-config --json
```

The Upstox preflight exits **0** with configuration/instrument PASS, overall
NOT_TESTED, authentication/quote/candles NOT_TESTED, no persistence/receipt and
historical replay false. The Angel preflight exits **1** with configuration BLOCKED
because the selected provider is Upstox; all market-data checks are NOT_TESTED.
Both safe outputs show `telegram_dry_run=true` and
`enable_background_scheduler=false`. An API key/token presence check is not an
authenticated response. No live command is included or authorized here.

The restricted shell required approved execution for temporary SQLite/test
fixtures. Tests use temporary databases, simulated or mocked broker transport and
ephemeral loopback HTTP fixtures; no production server/scheduler was started.
No real broker/account/order endpoint or live Telegram delivery was called. No
credential value/header or `.env` content was opened for inspection or printed.
The configuration preflights use the existing redacted loader. Config/template,
database configuration, localhost binding, broker/identity/freshness/provenance,
sizing/cost and historical gates match the pre-edit snapshot. Only this Windows /
Python 3.14.6 runtime was validated; no supported-runtime matrix, real exchange
calendar or real feed was accepted. PowerShell labels redirected unittest stderr
as NativeCommandError in Tee logs; the recorded Python exit/status and warning
inventory above distinguish that shell formatting from an actual test failure.

## Milestones, limits and next acceptance

The established M01-M12 denominator, weights and rubric are unchanged. M09 remains
I=50/R=50: this package supplies broader offline evidence but cash-only execution,
unresolved-EOD recovery policy, partial fills/adjustments and dedicated EOD export
remain scoped gaps; R=75 also requires scoped operational acceptance. M12 remains
I=25/R=0: exception/restart tests do not deliver release automation or verified
backup/restore. All other rows are unchanged. Weighted scores remain **63.50%
implementation / 35.50% readiness; 0/12 milestones accepted**. Extra tests do not
automatically promote coarse milestone scores.

The next external acceptance task remains one separately authorized selected-Upstox
RELIANCE cash quote/completed-candle diagnostic, retaining sanitized JSON and actual
exit code in the appropriate session. A PASS would cover only that path. No command
here authorizes it. For paper operations, specify unresolved-EOD recovery and
read-only session export before an operational multi-session soak. Derivative master,
contract fills, authoritative calendars and independent historical-source evidence
remain separate prerequisites. LIVE historical replay and historical Strategy 3
remain blocked. No receipt or acceptance flag is issued.
