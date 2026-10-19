# TradePulse AI - durable forward paper portfolio

2026-10-18, Phase 5A closeout plus Phase 5B integration; Phase 5C addendum dated 2026-10-19. **Offline simulated accounting PASS in the stated cash-only scope; operational acceptance NOT_TESTED.** No order interface, broker execution, production account, scheduler activation or live Telegram delivery is provided by this service. Earlier integrated counts are in the [Phase 5A/5B report](TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md); current counts are in the [Phase 5C report](TRADEPULSE_PHASE5C_ENGINEERING_REPORT.md).

## Account, persistence and explicit integration

`PaperAccountConfig` is an immutable account/run/provider/source-mode/risk/cost/session/fill-policy identity. Its canonical hash is retained in `paper_accounts`. Only explicit construction of `PaperPortfolio` creates an account; normal scans, configuration preflights and read APIs do not. Source mode LIVE/SIMULATED is retained independently of `execution_mode=SIMULATED`. Mocked LIVE adapter flags in tests exercise the strict parser only and never establish accepted broker observations.

The existing `SQLitePersistenceStore` owns all connections/migrations. Additive tables are `paper_accounts`, `paper_positions`, `paper_events`, and `paper_candidate_decisions`; pre-existing signal, replay and archive rows retain their semantics. `paper_transaction` uses the existing reentrant lock and connection lifecycle, `BEGIN IMMEDIATE` for writes, rollback on exceptions including commit failures, and SQLite `query_only` for read contexts. Independent store instances compete through SQLite, not separate in-memory balances.

The explicit runtime entry is `IntradayBotEngine.run_single_scan(paper_portfolio=portfolio)`. It requires the same store/provider, a forward-close account, dry run and disabled scheduler. Calls without this argument retain ordinary scanner behavior. No HTTP write endpoint or automatic scheduler enrollment was added. **Calling this method with a real adapter can read market data and therefore still requires separate authorization; tests replace transport with labelled fixtures.**

`ForwardPaperCoordinator.consume_scan` accepts a successfully persisted scan, binds every candidate field to its stored signal/dedup key and scan run, then records QUEUED/REJECTED/FILLED decisions with bounded reason codes and transition history. Full candidate rationale, contract identity, source timestamp and recomputed risk decision persist in the position/entry event. A candidate or successful scan alone is not a fill. QUEUED candidates reserve no capital.

## Fill and lifecycle assumptions

The forward runtime requires `NEXT_COMPLETED_BAR_CLOSE_V1`: a candidate from a completed five-minute bar waits for the **next** completed five-minute observation, then uses its observed close plus the existing adverse slippage model. The actual fill timestamp is that observation's end. Prior intrabar excursions do not become a fictitious post-entry exit. A setup touching invalidation/target before that close is conservatively rejected. Prices and quantities are hypothetical; OHLCV does not prove execution or liquidity.

The original explicit Phase 5A policy `OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1` remains available to direct service callers for labelled retrospective candle simulation, including same-bar exits. It is not accepted by the forward scanner coordinator. Its additional timing guard prevents spending capital released later in the same assumed fill bar. Policy selection changes the immutable account hash and cannot silently alter an existing account.

Only validated NSE cash EQ long/short candidates and whole shares are supported. Futures, options, index spot, unknown identities and unqualified local declarations reject. Historical Strategy 3 is never enabled. Provider, account, source mode, run, strategy, instrument and event scopes remain explicit.

Open positions consume exact next completed observations. Stops win intrabar stop/target collisions; adverse stop gaps use the observed open, favorable target gaps cap at target. Default EOD treatment closes from the completed 15:15-15:20 bar at its close if no earlier modeled exit occurred. Missing that observation leaves an explicit unresolved EOD position; there is no invented square-off. Partial closes, deposits/withdrawals and manual accounting adjustments are unsupported and have no mutation API.

## Capital, P&L and risk

Sizing reuses `strategies.size_position` and the unchanged configurable `IndianCostModel`. Available capital excludes reservations, realized losses and adverse open raw MTM; unrealized gains are not new spending power. Reservations are not P&L debits. Entry quantity satisfies all-in modeled stop risk, capital, whole-share and configured per-position/aggregate **entry-notional** exposure caps. Exposure is not a changing mark-price margin model. No derivative margin, liquidity guarantee or gap-loss maximum is implied.

Daily loss policy uses realized net P&L on the observation's exit date plus current open net MTM, including estimated round-trip costs; missing/stale marks freeze entries rather than imply zero loss. Account-wide open-position and daily-entry limits apply across permitted strategies. Fees/slippage appear as estimated close provisions while open, and are settled exactly once on full exit. Closed net P&L equals raw gross P&L minus the model's charges/slippage; remaining reservation becomes zero. Per-account balance and equity are derived from persisted positions/events, not a second cash service.

This cash subset does not provide a portfolio across accounts/providers, partial-fill liquidity, a dedicated published EOD performance report or operational soak evidence. Statutory/brokerage assumptions remain configurable estimates.

## Atomicity, replay and recovery

Entry reservation, position, initial mark, entry event and FILLED candidate decision commit in the **same transaction**. Deterministic account/candidate/event keys prevent a retry or concurrent scan from consuming capital twice. A conflicting key/body rejects. Exits/marks are likewise transactional. Duplicate replay returns the original effect without refreshing a stale observation or posting costs again.

Service events are append-only by implementation; the separate position snapshot is checked against entry/last-mark/exit events on recovery. Reconciliation independently recalculates costs, gross/net P&L and reservation release. A decision/report callback failure after commit can be recovered from the durable effect; a failure during any write rolls back all effects. A transaction-injection test fails the FILLED-decision update and proves zero positions/events/reservations remain before retry.

An actor controlling every database row and application/trust configuration is outside tamper-proof claims. No cryptographic external ledger attestation is implemented. Source corruption/conflicting snapshots fail closed. This is auditable local accounting, not a brokerage statement.

## Read-only reporting and evidence

GET/HEAD `/api/paper-accounts` inventories existing accounts. `/api/paper-portfolio?account_id=...` reports config identity, accounting and reconciliation with bounded position, recent-event and candidate-decision previews; `/api/v1/...` aliases exist. Each preview is capped at 200 records and 256 KiB, with explicit totals/truncation flags. Small accounts keep complete lists. Missing accounts return NOT_CONFIGURED/404 without creation. These routes never scan, fill, mark, dispatch or contact a broker. Phase 5C adds server-side pages as described below; a dedicated EOD export remains work.

The Phase 5A/5B **78-test focused selection**, exit 0, contained **26 paper lifecycle/accounting tests, 6 store/API/E2E integration tests and 14 Phase 5B tests**, plus 20 contract and 12 provenance tests. Paper tests cover actual sizing/costs, concurrent capital/duplicate races across stores, event/decision transaction failure, gaps/collisions, EOD, bad/stale/missing marks, loss/exposure/count limits, immutable scopes and restart reconciliation. The genuine mocked-wire scanner path queues a real evaluator candidate, waits for the next observation, fills/marks/exits and recovers identical accounting. No evaluator, identity gate or risk decision is replaced to force a candidate.

Phase 5A/5B identified a bounded offline multi-session interruption/EOD and large-ledger reporting exercise as the next package. Phase 5C now supplies the deterministic evidence below. It does not supply a long-running operational soak. The live provider prerequisite and master/history gates remain independent and blocked where evidence is absent.

## Phase 5C offline closeout (2026-10-19)

The [Phase 5C engineering report](TRADEPULSE_PHASE5C_ENGINEERING_REPORT.md) records fresh baseline/final commands, warning inventory, fault boundaries, query plans and measured performance. Twenty new tests cover Friday/Monday restart, observation receipt before commit, candidate/reservation/entry/mark/exit/fee/EOD failures, post-commit reporting failure, concurrent mark/exit, malformed ledger records, metadata migration/VACUUM and account-scoped pagination. Existing independent-store capital allocation and consistent read-snapshot tests remain required.

Daily accounting uses the aware clock's **IST calendar date**, including weekends; realized day P&L and entry counts reset at IST midnight while open net MTM and lifetime balances remain. A normal EOD exit permits a later session's entry under the same account. A missing EOD observation instead preserves the open position and reservation indefinitely: no settled exit fees, no invented final price and no next-session repair. Yesterday's bar is stale; today's bar cannot replace the exact missing interval. Entries remain blocked by stale marks/unresolved EOD. A manual resolution/adjustment policy is still unsupported.

The completed 15:15-15:20 EOD bar may be observed through the existing inclusive 60-second delay (15:21:00 IST); later, incomplete or out-of-sequence bars reject. Fixture weekdays and configured test holidays are not authoritative exchange-calendar evidence.

`GET/HEAD /api/paper-ledger?account_id=...&collection=events&limit=100` provides `events`, `positions` and `candidate_decisions` pages, also under `/api/v1`. Limits are 1-200; opaque continuation cursors bind account/collection and pin a first-page sequence watermark. Appends are excluded from that traversal. Position/decision bodies can change between pages: this is membership stability, not a point-in-time export. Items use at most 900 KiB plus bounded metadata; oversized/malformed records fail closed without echoing their bodies. Byte limits can shorten a page. Reads do not create accounts or mutate paper state.

Reconciliation and summary construction now stream indexed rows instead of loading the entire event history or rescanning it for every position. All three synthetic ledgers (100/1,000/10,000 events, 25/250/2,500 closed positions and decisions) reconcile exact template fees/net P&L and zero reservations, with complete duplicate-free pagination. At 10,000 events the dedicated run measured startup 117.216 ms, reconciliation 1,386.387 ms, summary 2,075.567 ms and first event page 17.859 ms; the summary was 552,767 bytes. These are host-specific measurements with no invented latency acceptance threshold. Bulk fixture graphs establish storage/arithmetic behavior, not risk-approved strategy performance.

This remains cash-only offline acceptance. Dedicated EOD export, unresolved-EOD repair policy, partial fills/adjustments, derivatives, authoritative calendars, supported release/backup recovery and operational multi-session acceptance remain missing or unverified. M09 stays 50/50 under the existing rubric; historical replay and Strategy 3 remain blocked.

## Continuous acceptance additions - 2026-10-19

The prior Phase 5C section above remains dated evidence. The
[continuous report](TRADEPULSE_CONTINUOUS_ACCEPTANCE_REPORT.md) records the new
implementation, actual tests and repeated performance measurements.

`review_unresolved_eod` supplies an auditable **freeze-only** policy after the final
observation's inclusive publication window has expired. KEEP_FROZEN and denied
REQUEST_LATE_HISTORICAL_REPAIR records retain account/config/provider/mode identity,
request/record hashes and an optional observation-hash reference. They cannot
change prices, marks, fees, reservations, balance or financial history. Reuse with
different content rejects; corrupt audit records and transactional failures fail
closed. Audits are visible through bounded `recovery_decisions` ledger pages.
No HTTP write endpoint or approved financial repair was added. A late historical
price/hash cannot unlock frozen capital; a financial repair/research-fork policy
needs a separate explicit decision and qualified evidence.

GET/HEAD `/api/paper-session?account_id=...&session_date=YYYY-MM-DD` (also `/api/v1`)
now exports a bounded read-only EOD **summary** after the configured session ends.
It reconstructs session-end state from actual events and excludes later-session
P&L. It reports realized session/lifetime results/fees, recorded unrealized MTM,
reserved/available capital, unresolved status and reproducible statement/event
digests. A missing final observation stays UNRESOLVED; last recorded marks are
explicitly not fresh valuations. Restart/repeated reports and later sessions do
not change the old statement. This is not a full point-in-time ledger export.

Account inventory now defaults to 100/max 200 with append-order watermark cursors;
the legacy list is a 200-row preview. The old alphabetic inventory order is replaced
by stable append order. Queued work uses indexed chronological batches of 200 with
PARTIAL/deferred metadata. Once its required observation window has expired, an
unfilled candidate is rejected without reservation; committed fills are checked
first. Corrupt off-page decisions block processing. The 450-decision regression
drains as 200/200/50 with no financial effects. Valid position observations still
use the unchanged freshness/identity/risk/fee transaction boundary.

Startup no longer rewrites all ordering metadata on every store initialization.
A migration marker and existing transactional triggers preserve append IDs; the
pre-change counterexample advanced sequence 3 to 6 with no new entity, while the
fixed regression preserves it. Encoded financial records are bounded before commit
so the service cannot write a position/event its bounded reader rejects.

The dedicated five-repeat, 10,000-event software run measured median startup
6.8669 ms, reconciliation 1,162.6634 ms, summary 1,674.8891 ms and first event page
14.1778 ms. These are warm-cache host measurements, not a controlled speedup against
Phase 5C's one-run timings or an SLA. Complete samples/maxima/memory/concurrency
results are retained in `evidence/continuous_performance_20261019.json`.

The policy still uses configured IST weekdays/holidays; authoritative dated session
phases and special sessions are not accepted. Derivatives, partial fills/adjustments,
financial late repair, full event export, release/backup recovery and operational
soak remain missing or unverified. M09 stays 50/50, with no live readiness or
historical replay/Strategy 3 release.
