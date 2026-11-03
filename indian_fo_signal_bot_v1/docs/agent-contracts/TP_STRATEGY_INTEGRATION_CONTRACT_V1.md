# TradePulse strategy integration contract V1

## H1 checkpoint 2 additive preflight (2026-11-03 IST)

`option_preflight.prospective_preflight(declaration=None, *, master=None, decision_at)` is a pure offline boundary, schema `tradepulse.option-prospective-preflight.v1`. It separates `declaration_valid` from `source_qualified`, `prospective_ready` and `forward_entry_allowed`. The last three are always false in this checkpoint. A structurally valid declaration returns UNAVAILABLE / `INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE`; every result includes `OPTION_APEX_FORWARD_LIFECYCLE_DISABLED`. Caller qualification flags cannot activate it.

The declaration requires exact normalized OPTIDX identity, retained master bytes/revision, explicit quantity in underlying units, INR prices, retained positive tick size, quote identity digest/revision, bid/ask and both displayed sizes, and offset-bearing quote/bid/ask/liquidity/received/available clocks. The existing resolver revalidates uniqueness, provider token, dated expiry/strike/side and master integrity. Fixed v1 mechanics require same-date master capture, <=5s quote/depth age, <=1s source-clock skew, source <= received <= available <= decision, prices on tick, spread <=2% of midpoint and both displayed sizes >= requested lot-multiple quantity. These limits are conservative preflight mechanics, not fitness scoring or market validation. Missing fields return UNAVAILABLE; invalid/mismatched/stale evidence returns REJECTED with explicit reason codes. Source authenticity, exchange-calendar/session eligibility and independent qualification remain future gates; a valid declaration alone does not prove any of them.

Normalized contract declarations now optionally retain finite positive `tick_size`; absence retains prior resolver behavior but blocks preflight. Scanner Option Apex evaluation traces add `prospective_preflight` with missing qualified premium evidence. Analytical signal fields, cash allowlist, all four cash policies, conflict guard, replay scope, routes and DB schemas are unchanged. Underlying bars, inspection captures, replay and simulated premiums cannot authorize forward entry. No provider adapter or qualification implementation is added. Research and React ownership stay on their separate feature branches.

H0 source freeze: `main` at `1083092`, inspected 2026-11-02 (Asia/Calcutta). Paths and line numbers below are relative to `indian_fo_signal_bot_v1/` at that source revision. This document describes implemented interfaces; it does not authorize activation, new strategies, real data acquisition, or trading. Test execution receipts belong to the H0 entry in [TRADEPULSE_MASTER_STATUS.md](../project/TRADEPULSE_MASTER_STATUS.md).

## H1 additive safety update — account-level contrary exposure

The first H1 checkpoint closes the **account-scoped** entry gap described in section 6. `PaperPortfolio.enter` now rejects a new opposite-side OPEN position with `PaperPortfolioError.reason_code = "CONFLICTING_OPEN_POSITION"` when the existing position has the same stable `(provider, identifier, exchange, segment, instrument_type)` identity. Symbol labels and source/master revisions do not distinguish exposure. The check reads every retained account position under the existing `BEGIN IMMEDIATE` entry transaction, after idempotent recovery and existing reconciliation/risk blocks, before new reservation/position/event effects ([paper_portfolio.py:795](../../paper_portfolio.py#L795), [storage.py:930](../../storage.py#L930)).

This tightens one risk gate without changing evaluator signatures, strategy rules, trigger formulas, cash ranking, DTO fields, account configuration hashes or SQLite schemas. Same-side entries remain subject to the existing limits; different instruments and independent simulation accounts retain their existing behavior. Closed positions release this conflict restriction, subject to the existing fill/capital chronology rules. Committed retries still recover before the new check. Existing coordinator error handling stores the new reason on a REJECTED decision; consumers must accept this additional reason string. Cross-account capital/exposure coordination and repair of pre-existing contradictory ledgers are outside this invariant. Tests: [test_h1_paper_conflicts.py:63](../../test_h1_paper_conflicts.py#L63) onward; execution receipt is in the current master status. Original H0 source anchors below remain historical anchors at their stated revision; this addendum refers to H1 source.

## 1. Ownership and boundaries

The Python core owns data admission, instrument identity, the five existing evaluators, candidate validation, rank history, SQLite transactions and paper effects. The frontend consumes retained views and may not establish eligibility by recalculating a score. Strategy experiments must be additive, default OFF, separately versioned and synchronized by the owner through `main -> dev`; H0 adds no flags or implementations. Existing four-strategy prospective paper experiments are distinct from the new Stage 1 research algorithms.

| Boundary | Existing implementation / source anchor |
|---|---|
| Provider adaptation and strict live batch admission | `brokers.py:202` (`assess_live_candle_batch`), `brokers.py:454` (`BaseBrokerAdapter`), `brokers.py:4126` (`MultiBrokerScanner`) |
| Normalization and evaluator DTOs | `strategies.py:16`, `strategies.py:95`, `strategies.py:243`, `strategies.py:539` |
| Scan/write orchestration and explanations | `scanner_engine.py:595`, `scanner_engine.py:847`, `scanner_engine.py:881` |
| Durable input provenance | `candle_lineage.py:161`, `candle_lineage.py:203`, `candle_lineage.py:430` |
| Cash candidate priority and retained history | `opportunity_ranking.py:41`, `rank_history.py:261`, `rank_history.py:311` |
| Prospective paper contracts and effects | `paper_triggers.py:196`, `forward_paper.py:178`, `paper_portfolio.py:696`, `paper_portfolio.py:741` |
| Historical Option Apex premium execution | `option_execution.py:65`, `option_execution.py:224` |
| Persistence | `storage.py:334`, `storage.py:836`, `storage.py:930` |

## 2. Completed five-minute observations and clocks

The common candle input is a `list[dict]` containing `timestamp`, `open`, `high`, `low`, `close`, `volume`. The general normalizer converts OHLCV to finite numeric values, requires strictly positive OHLC and nonnegative volume, verifies high/low geometry and returns normalized `timestamp` strings, numeric OHLCV, `is_complete: bool`, `is_simulated: bool`, preserving extra fields. The timestamp denotes **bar start**. With `now` and interval supplied, completion requires `bar_start + interval <= now`; explicit `is_complete: false` stays incomplete. General normalization can deduplicate equal timestamps, retaining the last; strict provider admission rejects duplicates before normalization (`strategies.py:539`, `strategies.py:587`, `strategies.py:609`, `strategies.py:694`).

`parse_ist_timestamp` accepts aware timestamps/UTC epoch seconds or milliseconds, converts to `Asia/Kolkata`, and also accepts naive legacy inputs as IST. `format_ist_timestamp` emits `YYYY-MM-DD HH:MM:SS` without offset (`strategies.py:470`, `strategies.py:526`). **This convenience parser is not the live transport boundary.** Raw live input requires an explicit offset/epoch; pre-normalized IST strings require the explicit `normalized_ist` caller convention (`brokers.py:172`). Option replay input requires offset-bearing ISO strings (`option_execution.py:36`).

Strict batch admission checks provider/context, explicit timestamp convention, LIVE provenance, Boolean completion, requested interval, NSE session/grid, duplicate/out-of-order rows, same-session interval gaps and OHLCV. It does not silently sort, deduplicate, manufacture bars or promote simulation. Output is `(normalized_rows, report)`; rows carry `timestamp_timezone: "Asia/Kolkata"`, `interval_min`, `data_mode: "LIVE"`, `is_simulated: false` and completion. Identity fields are preserved when supplied; this freshness checker does **not** establish identity. Separate `bind_candles` and `completed_cash_batch` gates validate the provider/instrument binding (`instrument_identity.py:160`, `candle_lineage.py:161`). The report includes `status`, `reason_code`, `batch_valid`, `is_fresh`, `live_signal_allowed`, `reference_usable`, completed/incomplete counts, latest start/completed timestamps and lag measurements (`brokers.py:202`, `brokers.py:245`, `brokers.py:285`). Closed-session reference data cannot authorize scanner entry (`brokers.py:315`). The calendar is weekdays plus configured holidays, not a separately verified exchange calendar (`brokers.py:220`).

### Freshness gates are distinct

| Consumer | Current arithmetic and meaning |
|---|---|
| Shared live admission | `max_lag = interval_min * 60 + max_delay_seconds`, compared with lag **from completed close**. With 5m and default delay 60s, this permits up to 360s close lag; freeze this actual behavior, regardless of comments calling delay a close allowance (`brokers.py:299`, `brokers.py:307`, `config.py:260`). |
| Cash rank | Same-date watermark start; completed close must be no later than rank reference; rank reference must be at most close + 60s. Snapshot `valid_until` is the earliest start + 5m + 60s (`opportunity_ranking.py:89`, `opportunity_ranking.py:139`). |
| Paper bar / trigger | Current-session completed five-minute observations; configured mark age is positive and <=60s; trigger observation rechecks <=60s close age (`paper_portfolio.py:101`, `paper_portfolio.py:534`, `paper_triggers.py:126`). |

These gates are not interchangeable. A provider batch passing the shared gate can still be too old for priority or prospective paper. H0 records the discrepancy without changing it.

### Durable cash lineage

`completed_cash_batch(rows, meta, profile, reference)` requires EQ identity, LIVE mode, `is_simulated: false`, explicit normalized timezone, five-minute interval, matching per-row provenance, source/revision and trusted spot mapping. It reruns strict scanner admission and stores **completed rows only**. Output has `batch_id`, `content {version, provider, identity, interval_min, candles}`, validation report, `retrieved_at`, retrieval clock, nullable `source_observation_at`, `source_authenticity: "NOT_ESTABLISHED"`, rejected-tail count (`candle_lineage.py:161`).

`cash-lineage-v1` profile contains provider, Python/SQLite versions, risk/session/freshness parameters and configured instrument metadata including sector. A code fingerprint hashes non-test root Python files. Snapshot includes profile/profile digest, code digest, aware reference, batches, auxiliary index candles/option chains, frozen zone state and work ID. Auxiliary options/index inputs do not become accepted cash records or publisher proof (`candle_lineage.py:17`, `candle_lineage.py:137`, `candle_lineage.py:149`, `candle_lineage.py:203`). A digest proves internal consistency, not source authenticity or historical rights.

## 3. Instrument identity, sector and dated contracts

Spot identity is provider-specific: `provider`, canonical `symbol`, exact `identifier`, `exchange`, `segment`, `instrument_type`, `is_index`, `source`, `source_revision`, `historical_validity`. Supported live providers are Angel One, Dhan and Upstox; pinned equity/index mappings are checked against caller metadata, and a loaded Angel master can provide extra mappings. EQ uses NSE / `NSE_EQUITY_INTRADAY` / `EQ`; index spot uses NSE / `NSE_FO_INDEX` / `INDEX_SPOT`. An index spot token is not an executable future or option (`instrument_identity.py:67`, `instrument_identity.py:115`). Candles bind to identity and conflicting echoed fields reject (`instrument_identity.py:123`, `instrument_identity.py:160`).

Sector is currently a configured string on equity watchlist metadata, retained in the runtime profile; no authoritative dated sector taxonomy or sector-strength rank factor is implemented. Do not convert these labels into institutional attribution or measured sector leadership (`config.py:188`, `candle_lineage.py:139`, `opportunity_ranking.py:105`).

The normalized `tradepulse.contract-master.v1` / `ContractIdentity` boundary supports EQ, INDEX_SPOT, FUTIDX, FUTSTK, OPTIDX and OPTSTK declarations. This is broader than current executable scanner/paper support. Its key fields and validation are defined at `instrument_identity.py:342`, `instrument_identity.py:378`, `instrument_identity.py:428`:

| Fields | Current requirements |
|---|---|
| `provider`, `symbol`, `identifier`, `exchange`, `segment`, `instrument_type`, `is_index` | Exact provider scope and explicit contract label. Derivative exchange is NFO. Tokens are provider-specific; Upstox FO keys use `NSE_FO\|<digits>`. `is_index` means index **spot**, so OPTIDX/FUTIDX has false. |
| `valid_from`, `valid_to`, `contract_status` | ISO dates, ordered; status ACTIVE/INACTIVE/SUSPENDED/EXPIRED/UNKNOWN. Declared dates/status do not alone establish trust. |
| `price_unit`, `quantity_unit` | INDEX_SPOT: INDEX_POINTS / NOT_EXECUTABLE. Derivatives: INR / UNDERLYING_UNITS. EQ: INR / SHARES. |
| `lot_size`, `multiplier` | Positive integer lot and explicit multiplier 1 for executable types; EQ lot 1. Index spot has no executable lot. |
| `underlying`, `underlying_identifier`, `expiry` | Required for derivatives; derivative and spot identifier must differ; validity cannot extend beyond expiry. |
| `strike`, `option_type` | Required for options: finite positive strike and CE/PE. Futures and spot cannot carry option terms. |
| `source`, `historical_validity`; retained revision/version | Normalized declarations start LOCAL_NORMALIZED_MASTER_DECLARATION / NOT_ESTABLISHED. Master parsing retains source revision/version (`instrument_identity.py:476`, `instrument_identity.py:725`). |

`ContractResolution` returns `status`, `reason`, `eligible`, `historical_replay_allowed`, nullable `identity`, nullable `master_id` (`instrument_identity.py:369`). Eligibility is a resolver decision at an explicit operation date, not a caller Boolean. Existing scanner option binding uses `option_contract(record, underlying, expiry, strike, side, provider, as_of)` and checks lot agreement before replacing a display label with the exact contract symbol (`instrument_identity.py:181`, `scanner_engine.py:999`).

**No universal option ID may be inferred from underlying + strike alone.** Integrations must carry provider token, expiry, side, date-valid contract terms, revision/digest and units. The legacy historical archive used by `option_execution.py` has a different shape from `ContractIdentity`: original records use underlying `symbol`, with a separate exact token, and require tick size. Do not cast between the two schemas by field-name coincidence (`option_execution.py:65`, `option_execution.py:89`).

## 4. Evaluator and candidate interfaces

`evaluate_strategy_detailed(strategy_id, candles, *, evaluator=None, **kwargs)` calls one existing evaluator once and returns `(Optional[TradeSignal], trace)`. It preserves actual short-circuit evaluation and does not retry after TypeError. Supported IDs and warmups are fixed at `strategies.py:151`, dispatch/trace shape at `strategies.py:243`:

| ID | Existing evaluator | Completed 5m warmup |
|---|---|---:|
| `strat_1_order_block` | `evaluate_order_block_fvg` (`strategies.py:1062`) | 30 |
| `strat_2_vwap_pullback` | `evaluate_vwap_pullback` (`strategies.py:1273`) | 35 |
| `strat_3_option_apex_oi` | `evaluate_option_apex_oi_shift` (`strategies.py:1445`) | 1 minimum; other input/rule gates remain |
| `strat_4_orb_filtered` | `evaluate_orb_breakout` (`strategies.py:1618`) | 30 |
| `strat_5_supertrend_pullback` | `evaluate_supertrend_pullback` (`strategies.py:1787`) | 200 |

Common cash evaluator arguments: `symbol`, candles, `capital_inr=150000.0`, `risk_pct=1.0`, `segment="NSE_EQUITY_INTRADAY"`, `now`, `market_breadth`, optional `lot_size`, `execution_costs`, `evaluation_trace`. OB additionally accepts mutable `mitigated_zones`; Option Apex substitutes `index_symbol`, requires `option_chain` and does not accept `segment`. VWAP and Supertrend require the current session's actual 09:15 opening bar, not just a sufficiently long rolling ring (`strategies.py:186`, `strategies.py:1291`, `strategies.py:1806`).

Trace schema `tradepulse.strategy-evaluation.v1` includes `strategy_id`, `status: DETECTED|REJECTED|UNAVAILABLE`, reason list, visited `rule_checks [{rule_id,status: PASS|FAIL|UNAVAILABLE,reason,measurements}]`, `warmup {required, observed, interval_min}`, summary and trace scope. Invalid supported inputs yield unavailable diagnostics; scanner adds `symbol`, `data_mode`, source reference. Not visited rules are not evaluated failures (`strategies.py:167`, `strategies.py:254`, `scanner_engine.py:873`).

### TradeSignal DTO

`TradeSignal.to_dict()` uses dataclass `asdict`; there is no separate Pydantic model. Full field declaration: `strategies.py:16`.

| Fields | Python / JSON types and semantics |
|---|---|
| `symbol`, `segment`, `strategy_id`, `strategy_name`, `direction`, `instrument_label` | string; label is display text until independently bound to exact identity |
| `entry_price`, `entry_zone_low`, `entry_zone_high`, `stop_loss`, `target_1`, `target_2` | float / finite number; positive price levels |
| `risk_reward`, `win_rate_benchmark`, `rationale`, `timestamp` | string; RR and benchmark text are legacy labels, not measured returns/probabilities |
| `confidence_pct`, `quality_score` | integer; quality validated 0..100, compatibility alias fills one from the other; rule quality is not win probability |
| `position_qty` | positive integer underlying units (shares for cash; not a derivative lot count) |
| `capital_risk_inr`, `est_charges_inr` | nonnegative finite number; estimates |
| `is_simulated`, `data_mode` | Boolean default false; string default LIVE |
| `position_type`, `invalidation_level`, `score_breakdown` | derived/default string; positive number defaults to stop; dict default empty |
| `provider`, `state_context`, `interval_min`, `instrument_identity` | string default unknown; string default UNKNOWN; integer default 5; dict default empty, assigned by scanner/replay |

Price geometry validation requires long `stop <= invalidation < entry < T1 <= T2`; short `T2 <= T1 < entry < invalidation <= stop`. Long calls **and puts** use long premium geometry. Entry zone must be ordered but need not contain entry (`strategies.py:95`). Identity/provenance remains a separate gate.

`signal_risk_reward` schema `tradepulse.signal-risk-reward.v1` returns `allowed`, status/reason, `price_unit: INR`, nullable risk/reward/T1/T2 ratios, `estimated_net_rr` unavailable object, `liquidity_status: NOT_ESTABLISHED`, `fill_status: LEVELS_ONLY_NOT_EXECUTED`. Valid geometry adds gross per-unit measures, charge estimates, ratio basis and nominal label. Net target RR stays unavailable because target-exit costs/slippage are not supplied (`strategies.py:196`). `size_position` returns rejected `{eligible:false,quantity:0,reason_code,...optional budget context}` or eligible quantity, risk/capital reserve, charge/slippage estimates, effective entry, lot and multiplier. It uses whole lots, unit multiplier and decimal risk/capital limits; long options only (`strategies.py:805`, `strategies.py:897`).

### Retained scan candidate and source lineage

`tradepulse.candidate-evaluation.v1` has `candidate_id`, `symbol`, `strategy_id`, `position_type`, QUALIFIED/REJECTED status, `actionable:false`, `recommendation_status:CANDIDATE_ONLY`, `data_mode`, `strategy_evidence`, `reason_codes`, risk DTO, `ranking {rank:int|null,qualified:bool,policy}`, source reference, explanation and warnings. Explanation includes finite-or-null price levels/setup quality, rationale/entry text, score breakdown and nullable actual rule trace. Source reference is `{run_id,provider,batch_ids:string[],instrument_identity,candle_timestamps:string[],candle_digest,source_authenticity:"NOT_ESTABLISHED",data_mode}` (`scanner_engine.py:847`, `scanner_engine.py:881`). Retained scan schema is `tradepulse.scan-evaluation.v1` with candidate/strategy evaluations and false actionability (`scanner_engine.py:1301`, `scanner_engine.py:1311`).

`signal_state_identity` returns `("signal:v2:" + canonical JSON, (provider,data_mode,state_context))`; it includes symbol, segment, strategy, direction, position type, label, interval and **full candle timestamp**. Unknown broker label only partitions unknown scope; it grants no provider proof. SIMULATED and LIVE/research state scopes must agree (`strategies.py:78`, `strategies.py:296`, `storage.py:172`). This signal identity is not the rank opportunity key.

## 5. Ranking, deduplication and storage versions

Scanner candidate ordering is lexicographic: descending quality, descending recomputed actual T1 gross RR, then symbol/strategy/direction/position/time/label/canonical DTO. It does not parse the nominal RR label (`strategies.py:131`). Cash snapshot policy is `CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2`, schema `tradepulse.opportunity-ranking.v1` (`opportunity_ranking.py:17`).

The cash rank builder accepts at most 512 evaluation candidates and requires qualified scanner status, correct run/provider/mode, exact NSE EQ non-index identity, cash direction, finite quality/gross RR and current watermark+digest. It sorts quality, actual T1 RR, symbol, strategy and opportunity key, then retains **one row per symbol**, excluding the rest as REDUNDANT_SYMBOL_SETUP, including competing directions. Opportunity key hashes scope, symbol, strategy, position type and identity; direction changes therefore get a distinct key (`opportunity_ranking.py:41`, `opportunity_ranking.py:60`, `opportunity_ranking.py:98`, `opportunity_ranking.py:117`).

Row outputs include key/candidate identity, symbol/strategy/position/direction, source watermark/digest, score components + versions, missing components, rank, nullable previous rank, reason and component changes. Missing factors remain RELATIVE_STRENGTH, SECTOR, REGIME, LIQUIDITY_DEPTH, OBSERVED_SPREAD, NET_EXECUTABLE_REWARD and EMPIRICAL_EDGE. Snapshot also records exclusions/removals, rank version, previous version, evaluation digest, as-of/valid-until and snapshot hash, always `actionable:false`. Same-watermark revisions or backwards source chronology reject. Rank version hashes inputs/order independently of request time/run ID (`opportunity_ranking.py:98`, `opportunity_ranking.py:109`, `opportunity_ranking.py:125`, `opportunity_ranking.py:135`).

Only the scanner result transaction appends `tradepulse.cash-rank-history.v1` with `tradepulse.cash-rank-descriptor.v1`. Reads authenticate committed source, retained explanation, code/config and predecessor; no fetch, scan or rank refresh occurs. `read_current` supports limit 1..100, offset 0..512 and optional run ID, returns current/historical page rows plus total and snapshot metadata. Explicit pagination must retain one run and consistent snapshot; expiry removes current rows but retains history (`rank_history.py:18`, `rank_history.py:261`, `rank_history.py:311`). See the UI contract for HTTP validation and frontend behavior.

| Persistence family | Existing version / transaction anchor |
|---|---|
| Cash facts, batch members, scan input/signal linkage | `cash-lineage-v1`; `cash_candle_facts`, batches/members, scans with PENDING/COMMITTED, scan inputs/signal inputs (`candle_lineage.py:233`) |
| Scan evaluations | JSON version `tradepulse.scan-evaluation.v1`; validates references on persistence (`storage.py:3125`, `candle_lineage.py:44`) |
| Cash rank snapshots | Append-only run/work identity and payload SHA; `cash_rank_snapshots` (`rank_history.py:31`) |
| Paper account/positions/events/decisions | Account config hashes; unique account+entry/event/signal keys; `paper_schema_migrations` marker `bounded-paper-v1`, durable append cursor order (`storage.py:734`) |
| Write/read discipline | Scanner result transaction; paper BEGIN IMMEDIATE writes / query-only reads and rollback (`storage.py:836`, `storage.py:930`) |

These are independent schema/version strings, not a universal numeric migration version. A new consumer must preserve existing version envelopes and reject incompatible payloads. H0 performs no production migrations.

## 6. Prospective paper state machine

`PaperAccountConfig` is immutable and hashed. It scopes account/run/provider/mode, capital, risk, daily-loss and entry/exposure/open-position limits, five-minute interval, mark age <=60s, session/square-off, holidays, cost-model JSON, strategy allowlist and fill policy (`paper_portfolio.py:63`). Only four **cash** strategies are permitted: 1/2/4/5. `PaperPortfolio._candidate` requires EQ/non-index NSE cash and LONG/SHORT equity position types (`paper_portfolio.py:103`, `paper_portfolio.py:587`).

| Strategy | Explicit prospective policy / contract implementation |
|---|---|
| ORB | `ORB_FOLLOW_THROUGH_CLOSE_V1`; later completed close crosses frozen signal high/low (`paper_triggers.py:15`, `paper_triggers.py:56`) |
| VWAP | `VWAP_REPEATED_RECLAIM_CLOSE_V1`; `vwap_paper_triggers.py:50`, `vwap_paper_triggers.py:175` |
| OB | `OB_FIRST_RETEST_FOLLOW_THROUGH_CLOSE_V1`; `order_block_paper_triggers.py:83`, `order_block_paper_triggers.py:190` |
| Supertrend | `ST_REPEATED_PULLBACK_CLOSE_V1`; `supertrend_paper_triggers.py:105`, `supertrend_paper_triggers.py:207` |
| Option Apex | **No forward premium contract policy or PaperPortfolio allowlist entry.** Historical replay is separate. |

Input to `ForwardPaperCoordinator.consume_scan(summary, observations)` is a successful persisted COMPLETED/COMPLETED_EMPTY scan, correct source mode, bounded signal list <=512 and per-symbol identity-bound observations. It validates the stored scan/signals and creates account+signal deterministic decisions; trigger policies build a frozen strategy contract. Default/legacy automatic policy is not authority for new prospective entries (`forward_paper.py:72`, `forward_paper.py:139`, `forward_paper.py:178`).

The ORB trigger DTO schema `tradepulse.paper-trigger.v1` includes rule/strategy/version, side, threshold/invalidation, initial previous close, decision timestamp, candidate/evaluation digests, exact source reference, expiry/square-off/fill policy, assumption labels and contract digest (`paper_triggers.py:96`). Its source reference contains run, batch, work, code and observation digests, retrieval timestamp and NOT_ESTABLISHED authenticity, read from an actual COMMITTED scan (`paper_triggers.py:33`). Other policy contracts keep their strategy-owned measurement/evidence envelopes; do not assume ORB fields are a generic new-strategy trigger schema.

The durable decision lifecycle is QUEUED -> FILLED or REJECTED. Individual future observation records are WAITING, TRIGGERED or INVALIDATED with timestamp, close, reason, source reference, observation time and nullable trigger timestamp. VWAP/OB/ST evidence statuses QUALIFIED_EXPERIMENTAL_TRIGGER / INVALIDATED / TARGET_ALREADY_REACHED / EXPIRED normalize into that record (`paper_triggers.py:126`, `paper_triggers.py:233`). Observations must be the exact next five-minute bar after the prior decision/history, same session and before square-off, completed and current. No same-candle retro-fill or skipped-bar substitution is supported. Histories are replayed and source-checked before effects; non-ORB policy history is bounded at 75 (`paper_triggers.py:161`, `paper_triggers.py:260`).

`observe_candidate(candidate_id, supplied, source_scan_run_id)` retains checked trigger history. `enter(candidate, completed_next_bar, event_key, *, candidate_decision_id, source_scan_run_id, entry_guard)` requires a retained TRIGGERED decision and current scanner guard for prospective policies. It rechecks provenance, future time, identity, target/invalidation touches, risk/capital/exposure/daily limits and uses observed **completed close** plus modeled adverse costs. Entry-candle earlier extrema cannot retrospectively fill/exit that close entry. Event key + command hash is idempotent; conflicting reuse rejects. Entry, reservation, mark and decision effects commit atomically; late guard failure rolls back (`paper_portfolio.py:628`, `paper_portfolio.py:696`, `paper_portfolio.py:741`, `paper_portfolio.py:798`, `paper_portfolio.py:852`).

`process_bar(position_id, completed_bar, event_key)` requires the exact next same-session 5m bar. Stops win ambiguous intrabar stop/target collisions; gap stops use observed open, gap targets are capped; EOD uses observed close. Missing data creates blocked/frozen/unresolved accounting rather than invented fills/settlement. Reconciliation blocks new risk on corrupted/stale/unresolved ledgers (`paper_portfolio.py:308`, `paper_portfolio.py:656`, `paper_portfolio.py:867`). Recovery checks an already committed deterministic entry before demanding new observations; tampered decision/entry/trigger envelopes fail (`forward_paper.py:27`, `forward_paper.py:210`).

Coordinator output: `{status: COMPLETED|PARTIAL, execution_mode:SIMULATED, actions:list, pending_batch_limit:200, pending_deferred_count:int, account_id, report}`. Actions can be terminal decisions, portfolio effect DTOs or DEFERRED/QUEUED reason objects; this is not an order API (`forward_paper.py:178`, `forward_paper.py:255`).

**PARTIAL / NOT_VERIFIED:** an unconditional same-symbol/opposite-side entry exclusion was not found in `PaperPortfolio.enter`; default concurrency limits are not a universal contrary-entry guarantee. A follow-up must use two retained opposite-side candidates and an account allowing multiple positions to establish behavior before promising such exclusion. H0 does not add it.

## 7. Option Apex: implemented scope and gaps

The existing evaluator uses ATM call/put LTP as premium entry, 0.78 premium stop and premium-derived targets, including long-put geometry; spot levels are used for directional VWAP context, not option price substitution (`strategies.py:1497`, `strategies.py:1557`). The minimal evaluator chain requires `atm_strike`, `pcr`, strikes and ATM `ce_ltp`, `pe_ltp`, `ce_oi`, `pe_oi`, signed changes; this numeric validator alone is not exact-contract/freshness acceptance (`strategies.py:703`). Legacy win-rate benchmark strings remain unevidenced labels (`strategies.py:1535`, `strategy_evidence.py:1`).

Scanner live Option Apex is provider-restricted, checks selected expiry/strike/side/lot and binds the option identity; non-Angel live option candidates are unsupported, and live index-future strategies reject for missing explicit futures master/contract candles (`scanner_engine.py:981`, `scanner_engine.py:999`, `scanner_engine.py:1018`). This is not an accepted forward option ledger.

`option_execution.py` implements point-in-time historical/synthetic long CE/PE replay with exact archive contract token/digest, dated expiry/strike/side/lot/tick, underlying candles, chains, premium bid/ask bars and observed opening depth. Request schema is `tradepulse.option-request.v1` with `master_json`, `dataset_json` and optional master/dataset manifests; dataset schema is `tradepulse.option-observations.v1`, scoped to provider/mode/NIFTY or BANKNIFTY and containing `premiums`, `underlying_candles`, `chains` (`option_execution.py:65`). It models next eligible option open, costs and adverse tick rounding; missing exits retain reservation, not zero settlement. LIVE-shaped replay requires qualified HISTORICAL_RESEARCH, not current-live authority (`option_execution.py:80`, `option_execution.py:224`, `option_execution.py:344`, `option_execution.py:371`).

Provider observation captures preserve ABSENT vs NULL vs OBSERVED field presence and raw/numeric values, source-time unavailability, and point-in-time OI baseline comparison; they do not grant execution admission (`option_observations.py:210`, `option_observations.py:230`, `option_observations.py:437`). **BLOCKED DATA / NOT_VERIFIED:** exact option observation validators -> qualified scanner consumer -> future premium trigger -> forward ledger remains incomplete; no generic new option-fitness score or new volume algorithm is implemented here.

## 8. Activation, evidence and integration handoff

Safe defaults come from `config.py:206` (`paper_sim`), `config.py:244` (Telegram dry-run true), `config.py:275` (scheduler false). The module loads optional project `.env` at import, so tests must override these explicitly and use memory/disposable stores; defaults alone are not proof of local configuration (`config.py:57`, `config.py:111`). No production configuration or credentials were included in this contract.

Prospective paper activation requires an explicitly selected immutable account fill policy plus a passed scanner portfolio and guard. These four experimental trigger modules are not promoted empirical strategies. The five existing evaluator IDs are hard-coded, and no Stage 1 new-strategy flag is established in the inspected `config.py`/`scanner_engine.py`/`strategies.py` dispatch. **NOT_VERIFIED future schema:** before adding a new strategy, define an additive ID/version/flag, default OFF, completed-bar/identity/source checks, unsupported-state behavior and separate prospective policy with tests; owner reviews the schema synchronization first.

`strategy_evidence.py:11` provides `tradepulse.strategy-evidence.v1`, rule version `phase_1c_bidirectional_v1`; its module explicitly states offline mechanics are not qualified empirical study or reviewed live-paper evidence. Confidence, synthetic fixtures, hashes, rank and historical benchmark text cannot change maturity/actionability (`strategy_evidence.py:1`). `actionable:false` is part of retained candidate/rank and experimental evidence contracts, not an error to overwrite in the UI.

## 9. Evidence map and open dependencies

The following tests were **inspected** for source coverage; this table is not an execution receipt. See the master status H0 entry for exact commands and measured results.

| Contract area | Current source tests / anchor |
|---|---|
| Provider-neutral bars, identity, UTC source clocks, gaps and stale admission | `test_market_data_contract.py:107`, `:131`, `:157`, `:171`, `:234`, `:276` |
| Retained scanner source digests, mutation isolation | `test_astra_scan_references.py:36`, `:62`, `:83` |
| Actual rule/risk trace | `test_phase4_strategy.py`; `test_phase4_explanations.py`; `test_phase4_recommendations.py` |
| Rank determinism, missing data, duplicate symbols, opposite direction, expiry, tamper | `test_astra_ranking.py:27`, `:39`, `:49`, `:87`, `:98`, `:108` |
| Rank retained input, empty refresh, expiration | `test_astra_rank_history.py:121`, `:133` |
| ORB prospective/idempotent/restart/current guard/stop-first | `test_astra_paper_triggers.py:398`, `:485`, `:513`, `:531`, `:548` |
| VWAP/OB/ST contract and financial path | `test_astra_vwap_paper_triggers.py:54`, `test_astra_vwap_execution.py`; `test_track_a_order_block_triggers.py:85`, `test_track_a_order_block_execution.py`; `test_track_a_supertrend_triggers.py`, `test_track_a_supertrend_execution.py` |
| Exact option premium replay, future/no-data/depth/risk | `test_option_execution.py:63`, `:83`, `:92`, `:100`, `:124`, `:141`, `:187`, `:212` |

Current dependencies: qualified rights/trust/chronological historical data and dated universe; separately authorized actual completed feed acceptance; forward Option Apex consumer/trigger/ledger integration; advanced rank factors/dated sector evidence; explicit contrary-entry acceptance; all-five lifecycle -> API -> browser acceptance. These cannot be replaced by offline pass counts. Freeze source interfaces now; do not implement H1 or experimental algorithms as part of H0.
