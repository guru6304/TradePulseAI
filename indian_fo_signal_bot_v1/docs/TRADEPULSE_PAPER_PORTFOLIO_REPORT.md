# TradePulse AI - durable forward paper portfolio

2026-10-18, Phase 5A closeout plus Phase 5B integration. **Offline simulated accounting PASS in the stated cash-only scope; operational acceptance NOT_TESTED.** No order interface, broker execution, production account, scheduler activation or live Telegram delivery is provided by this service. Final integrated counts are in the [engineering report](TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md).

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

GET/HEAD `/api/paper-accounts` inventories existing accounts. `/api/paper-portfolio?account_id=...` reports config identity, accounting, reconciliation, positions, the latest 200 ledger events and up to 200 candidate decisions; `/api/v1/...` aliases exist. Missing accounts return NOT_CONFIGURED/404 without creation. These routes never scan, fill, mark, dispatch or contact a broker. Large-history server-side pagination and a dedicated EOD export remain work.

The final **78-test focused selection**, exit 0, contains **26 paper lifecycle/accounting tests, 6 store/API/E2E integration tests and 14 Phase 5B tests**, plus 20 contract and 12 provenance tests. Paper tests cover actual sizing/costs, concurrent capital/duplicate races across stores, event/decision transaction failure, gaps/collisions, EOD, bad/stale/missing marks, loss/exposure/count limits, immutable scopes and restart reconciliation. The genuine mocked-wire scanner path queues a real evaluator candidate, waits for the next observation, fills/marks/exits and recovers identical accounting. No evaluator, identity gate or risk decision is replaced to force a candidate.

The next paper acceptance package is a bounded **offline** multi-session fault/soak and large-ledger reporting exercise, including interruption around observation delivery and EOD, before any separately authorized operational data feed. The live provider prerequisite and master/history gates remain independent and blocked where evidence is absent.
