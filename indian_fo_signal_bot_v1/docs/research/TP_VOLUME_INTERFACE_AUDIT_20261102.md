# Volume research interface audit — 2026-11-02

Scope: Agent 2 Part A, branch `feature/new-strategies`, starting source `627b61c17ca35e91838ef3d513fdd424509bb3fb`. This document records a read-only source audit and a proposed isolated handoff. It grants no scanner, ranking, paper-account, market-data or notification activation. No operational database was opened by this audit.

## Authority and calculation review

The authoritative calculation source is the complete `TradePulse_AI_Stage1_Final_Algorithm_Research_Spec_2026-10-31.md` under `C:\Users\91810\TradePulseAI-References\Stage1-Strategies`. Its corrected equations supersede the original GPT/Gemini BRDs and the earlier independent audit. The implementation team also reviewed the full independent dual-BRD audit and the original BRDs' volume-feature, strategy-card and pseudocode sections as reasoning background. Those documents do not supply acquired market data, measured profitability or account/data rights.

Current source contracts are [strategy integration V1](../agent-contracts/TP_STRATEGY_INTEGRATION_CONTRACT_V1.md), [UI/API V1](../agent-contracts/TP_UI_API_CONTRACT_V1.md) and the H1 checkpoint in [master status](../project/TRADEPULSE_MASTER_STATUS.md). H1 adds account-level `CONFLICTING_OPEN_POSITION`; it does not add a B/R registry, API or execution policy.

| Topic | Final approved research rule | Background rule deliberately excluded |
|---|---|---|
| Participation | Current closed slot volume / median of exactly N prior eligible same-slot sessions; N20 default; positive denominator; missing/zero-baseline explicit | Adjacent-bar mean substituted for seasonal volume; epsilon/floor manufacturing a ratio; partial history silently promoted |
| Development comparison | N = 5/10/15/20/30/50/60 on matched dates after 60 prior sessions; thresholds 1.5/1.8/2.2 development only | Best lookback chosen using holdout outcomes |
| Candle anatomy | `CLV=(C-L)/(H-L)` in [0,1]; long >=0.70, short <=0.30; zero range unavailable | Gemini signed [-1,1] CLV thresholds reused against a [0,1] variable |
| Breakout B | Four prior highs/lows; directed close at least one tick beyond range; next two eligible future bars; three-bar structural stop | GPT's original misleading retest name, optional extension/stop-size vetoes silently stacked |
| Retest R | Six prior highs/lows; frozen K; `b=max(2*tick,0.20*ATR14_prev)`; actual zone retest within four bars; next three bars for entry | Gemini VWAP/body-midpoint zone, mandatory contraction/sector/robust-Z stack, 0.15 ATR stop, scale-outs and trailing |
| Economics | Actual assumed future fill determines 1.8R target; indicative versus post-fill net RR; minimum 1.25 research gate | Trigger-price bracket reused after a gap; blended 2.3R reward or target-first ambiguous OHLC |
| Corporate actions | Consistent comparable share units; preserve raw as-traded execution prices; adjustments known as of decision | Raw price multiplied by split-adjusted shares as true turnover; future price adjustment |
| Optional context | As-of aligned 15m sector relative strength, unavailable without rejection; factor family `participation` | Institution-flow claims, unmodified empirical-Bayes estimator, mandatory robust-Z |

The independent audit also corrects Gemini's synthetic volume sum to 1,899,500 and mean to 94,975; neither number is measured NSE evidence. No 2026 fee schedule, current provider capability or legal entitlement was independently fetched for this offline checkpoint. Cost inputs must remain explicitly versioned assumptions/dependencies rather than claims of an authoritative live tariff.

## Actual interfaces and ownership

| Boundary | Inspected source and implications |
|---|---|
| Five existing evaluators | [strategies.py](../../strategies.py), `STRATEGY_WARMUP_BARS` at line 151 and `evaluate_strategy_detailed` at 243 hard-code five IDs. `TradeSignal` at line 16 is a mutable legacy DTO with quantity, confidence alias and two targets. New research DTOs should remain separate until Main approves adaptation. |
| Scanner retained candidate | [scanner_engine.py](../../scanner_engine.py), lines 847–909, owns source references, trace binding and `tradepulse.candidate-evaluation.v1`; retained candidates have `actionable:false`. Lines 1043–1095 dispatch existing evaluators. No new B/R import/registration is appropriate here. |
| Cash lineage | [candle_lineage.py](../../candle_lineage.py), `completed_cash_batch` at 161 validates identity, LIVE provenance, timezone, interval and completed bars. Source authenticity remains `NOT_ESTABLISHED`; a digest does not establish rights. `make_snapshot` at 203 retains configured sector labels, not dated sector authority. |
| Code fingerprint | `candle_lineage.code_fingerprint` at 149 hashes non-test root Python files. A research subpackage avoids unnecessary root-file fingerprint changes solely from adding unused research modules. Future integrations must still review fingerprint compatibility. |
| Rank | [opportunity_ranking.py](../../opportunity_ranking.py), lines 41–149, orders current qualified cash candidates by quality then actual gross T1 RR and deterministic identity, retaining one symbol including competing directions. Sector, spread/depth, relative strength, net executable reward and empirical edge are explicitly missing. |
| Rank history | [rank_history.py](../../rank_history.py), `record` at 261 requires retained scanner input and the scanner transaction. `read_current` at 311 reads retained snapshots and expires stale data. No research writer or alternate ranker is authorized. |
| Research study | [research_protocol.py](../../research_protocol.py), `StudyProtocol` at 25 supports only the existing four historical cash strategies. `run_qualified_study` at 96 requires frozen data, archived identity and existing source-qualification gates. It is not a new B/R dispatch interface. |
| Future paper | [paper_triggers.py](../../paper_triggers.py), lines 15–19, provides only ORB/VWAP/OB/ST policies. ORB `build_contract` at 56 requires retained scanner evidence, freezes a later completed-close crossing and has no bar TTL. This differs from B/R high/low future trigger mechanics. [forward_paper.py](../../forward_paper.py), `consume_scan` at 178, owns guarded, durable handoff. |
| Account safety | [paper_portfolio.py](../../paper_portfolio.py), `enter` at 741 and H1 contrary-exposure check around 795, remains Main-owned. All retained positions are checked atomically before new effects. Research must not bypass or duplicate the ledger service. |
| Persistence | [storage.py](../../storage.py), schema initialization around 334, `scan_result_transaction` at 836 and `paper_transaction` at 930, are operational boundaries. No migration, store initialization or operational write is part of Part A. |
| UI/API | [server.py](../../server.py) provides retained reads and explicit POST operations; there is no B/R research or contract-fitness endpoint. Cold recognized reads may initialize runtime/store. No HTTP invocation is needed for pure research. |

## Existing feature overlap

Existing filtered ORB at `strategies.py:1618` requires the actual first three current-session bars at 09:15, 09:20 and 09:25. It uses a rolling mean of the previous 20 adjacent candles, RVOL >=1.6, VWAP and RSI 55/45, ATR10, and 1.6R/2.4R targets. It detects a completed close crossing the opening range. B's four-bar rolling structure and seasonal same-slot median, and R's six-bar impulse plus actual future retest, are distinct versions; neither can inherit ORB evidence or replace it.

Existing VWAP at `strategies.py:1273` uses prior adjacent-bar mean RVOL >=1.4 with VWAP/EMA20/RSI and session-open requirements. `compute_setup_quality_score` at 327 already rewards volume. A future comparison must retain the feature family, units, lookback and score use so the same participation observation is not rewarded twice.

**Comparable real-data denominator: 0 instrument/session events.** No matched, rights-qualified point-in-time NIFTY200 archive containing both seasonal history and actual existing ORB/ranking evaluation inputs was supplied or acquired. Empirical B/R/ORB overlap counts, win rates, incremental expectancy and top-K performance are **UNAVAILABLE**. Synthetic overlap/exclusivity fixtures can verify logic only. A future comparator must run the actual filtered ORB and current ranking policy on the identical qualified dataset, expose absent records and zero-signal runs, and group overlapping underlying/direction/risk-family events before counting outcomes.

## Clocks, identity and source dependencies

The common core bar timestamp denotes start. `parse_ist_timestamp` at `strategies.py:470` accepts naive IST for legacy convenience; raw live `_explicit_candle_timestamp` at `brokers.py:172` requires offset/epoch unless normalized IST is explicitly declared. `assess_live_candle_batch` at 202 rejects duplicates, order/grid/session gaps and malformed provenance before normalization. Its freshness allowance can be 360 seconds from a completed 5m close, while rank/paper gates require at most 60 seconds. Research must use explicit aware source/received/available clocks, never assume these gates are interchangeable, and reject a future interval that began before the decision was available.

`spot_identity` at `instrument_identity.py:67` and `bind_candles` at 160 establish provider/token request binding and conflict checks. Checked-in mappings declare historical validity `NOT_ESTABLISHED`. Current watchlist/sector configuration is not a dated NIFTY200 universe, sector taxonomy or corporate-action ledger. The existing weekday/configured-holiday calendar is not an independently verified complete exchange calendar. Research calendar and membership inputs must carry their own dated source/availability declarations and reject absent special-session policy honestly.

External dependencies remain: lawful completed cash 5m history; 60-session matched warmup; effective-dated NIFTY200 ordinary-equity membership and identity; point-in-time corporate actions/volume units; holidays and special-session definitions; dated tick/market-band/phase and liquidity evidence; versioned cash long/short fees and friction; synchronized sector prices/classification if optional strength is evaluated. No historical-data entitlement, account access or capture rights are established by documentation, a local declaration or a hash.

## Proposed additive handoff for owner review

Part A should expose a separate pure research package with flags default OFF and no imports from scanner/account/storage/notification modules. Its frozen records should retain candidate and rule versions, as-of and observed/received/available times, source and exact instrument ID, completed setup/impulse/retest candle IDs, direction, status/reason codes, future trigger policy/window, structural stop, post-fill target/risk/cost assumptions, and `confidence_type="ordinal_quality_not_probability"`. Output must remain `actionable:false`; fill results are labeled bar approximations when only OHLCV is supplied.

This is a **proposed research schema**, not an assertion that current `TradeSignal`, HTTP, ranking or paper consumers accept it. Main must separately approve new strategy IDs/versions/flags, typed adapters, source admission, future trigger policy, duplicate/capital handling and retained evidence before any production integration. No existing contract change or operational migration is required for an isolated package; future consumer synchronization is a review dependency.

The initial package API inspected during implementation is:

| Module | Research API |
|---|---|
| `volume_research/__init__.py` | `BREAKOUT_ENABLED=False`, `RETEST_ENABLED=False`, ordinal confidence semantics; no production registration |
| `volume_research/primitives.py` | Frozen `Bar`, `Session`, `Instrument`, `Membership`, `CorporateAction`, `VolumeProfile`, `SeasonalRVOL`, `SetupContext`, `SectorStrength`; `prepare_setup`, `seasonal_rvol`, `comparison_rvol`, `clv`, `atr14`, `sector_relative_strength`, Decimal tick helpers |
| `volume_research/breakout.py` | `detect_breakout` produces `Detection`, with an optional `PendingCandidate`, for `TP-VOL-BREAKOUT-1.0` |
| `volume_research/retest.py` | `detect_retest`, `advance_retest` return frozen `RetestState`, initially `WAIT_RETEST`, later `PENDING_R` or explicit terminal reason, for `TP-VOL-RETEST-1.0` |
| `volume_research/models.py` | Frozen `CostModel`, `MarketEvidence`, `PendingCandidate`, `Detection`, `Position`, `Exit`, `StepResult`; `advance_pending`, `advance_position`; `PendingCandidate.to_dict()` proposes `tradepulse.volume-research-candidate.v1` |

The proposed candidate JSON uses decimal strings for levels/features, aware ISO clocks, `candidate_version`, `config_hash`, `as_of`, `observed_at`, `available_at`, `decision_at`, `source_id`, `instrument_id`, completed candle ID/revision, direction, pending status, trigger policy, structural stop, deferred actual-fill target, cost-model version, reason codes and `option_fit={status:NOT_EVALUATED,contract:null}`. It preserves `actionable:false`, `execution_mode:OFFLINE_RESEARCH_ONLY`, and `source_authenticity:NOT_ESTABLISHED`. These names do not extend `tradepulse.candidate-evaluation.v1` or any HTTP response.

The package accepts research declarations; it does not authenticate them. Its caller-supplied `MarketEvidence` and `CostModel` do not bypass Main's source qualification, actual account capacity, exposure transaction, exact rights or fee schedule verification. Stateless step results must be retained by a future harness; a caller must not reuse pre-terminal states as separate trades.

Options work has not begun. Current exact historical replay in `option_execution.py` and presence-preserving captures in `option_observations.py` do not provide qualified future premium quotes or a prospective ledger. Main retains Option Apex ownership.

## Offline verification boundary

This audit itself executed no tests. Recommended baseline uses safe process flags (`ACTIVE_BROKER=paper_sim`, `TELEGRAM_DRY_RUN=true`, `ENABLE_BACKGROUND_SCHEDULER=false`), the credential-free `test_bot` bootstrap, `verify_offline.offline_network` and disposable fixtures, with result IDs retained through `ExecutionResult`. Relevant modules are `test_phase4_strategy`, `test_astra_research`, `test_market_data_contract`, `test_cash_lineage`, `test_astra_ranking`, `test_astra_rank_history` and `test_h1_paper_conflicts`. Actual executed commands/counts belong in the new checkpoint receipt; historical H0/H1 pass counts are not a rerun claim.
