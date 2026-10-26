# Astra strategy and research evidence notes

Mission: `TRADEPULSE-ASTRA-OWNER-2026-10-24-V1`. Research workstream checkpoint,
2026-10-24. This is supporting material for the single master execution report,
not a separate project acceptance. No evaluator formula was changed in this work.

## Completed narrow correction

`historical_study.run_frozen_study` previously accepted a declared fold with a
missing intermediate test session, although the underlying engine scored the
inclusive first-to-last date range. It also accepted an omitted training session,
although it passed every earlier source bar as warm-up. Thus the frozen
declaration could disagree with the actual information set. This is a reproduced
study-integrity defect, not evidence that any real published study was affected.

Before repair, the two existing Astra regressions failed with `ValueError not
raised`. The new check requires the training declaration to equal the complete
source prefix before the first test session, and the test declaration to equal
all source sessions inside its bounds. It runs before evidence retention or any
fold evaluation and applies to cash and the separate option runner. Explicit
unscored gaps between test folds remain permitted when included in later training
prefixes. No missing market sessions or candles are manufactured.

Executed evidence, all retained without replacing earlier logs:

| Evidence | Actual result |
|---|---|
| `docs/evidence/astra_research_partition_before_20261024_01.txt` | 2 tests, 2 expected regression failures, exit 1, before production repair |
| `docs/evidence/astra_research_partition_after_20261024_01.txt` | 23 tests, 22 passed and 1 existing temporary SQLite durability test errored under sandbox access denial, exit 1 |
| `docs/evidence/astra_research_partition_after_20261024_02.txt` | Same 23 tests outside the sandbox, all passed, exit 0; 10 Astra tests and 13 existing study tests |

The successful command was Python 3.14 under `.venv_phase4`, with `-B -W
error::ResourceWarning -m unittest -v test_astra_research test_historical_study`.
No skipped tests or resource warnings were reported. Full canonical verification
and an independent review remain coordinator responsibilities. Tests use isolated
fixtures and temporary stores; authentic profitability is not measured.

## Current strategy contracts

All five evaluate completed five-minute candles. Source helpers enforce the
strategy's minimum and session-opening coverage; scanner provenance, freshness,
full continuity and input-consumer checks remain separate mandatory gates. A
valid evaluator output is a decision-time reference, not an instruction to fill
a future observation. None of these evaluator functions defines pending setup
expiry, a universal three-bar deadline, partial exits or a trailing stop.

| Strategy and source | Actual directional predicates | Entry, invalidation, stop, targets |
|---|---|---|
| Order Block/BOS/FVG, `strategies.py:evaluate_order_block_fvg`, minimum 30 bars | Last 15 bars searched newest eligible origin first. Bull: red origin, either next two closes above origin high, then FVG (second impulse low above origin high) OR displacement from origin open at least 1.5 ATR(10). No subsequent close below origin low; no earlier mitigation by low <= origin high * 1.0015. Current low <= that boundary, close above origin open and >= origin low. Bear mirrors with green origin, closes below origin low, second impulse high below origin low OR 1.5 ATR displacement, no close above origin high, no earlier high >= origin low * 0.9985, and current high reaching that boundary with close below origin open and <= origin high. Supplied mitigated-zone set prevents reuse. There is no minimum RVOL or directional VWAP gate here. | Decision close. Long invalidation origin low; stop origin low - 0.25 ATR. Short invalidation origin high; stop origin high + 0.25 ATR. T1/T2 at 2/3 modeled risk units. Zone consumed only after eligible sizing. |
| VWAP Pullback, `evaluate_vwap_pullback`, minimum 35 | Positive preceding-20-bar volume average, RVOL >= 1.4. Bull: low <= VWAP * 1.0025, close > VWAP and open, close >= EMA20 * 0.998, RSI14 inclusive **48–72**. Bear: high >= VWAP * 0.9975, close < VWAP and open, close <= EMA20 * 1.002, RSI14 inclusive **28–52**. | Decision close. Long invalidation min(low,VWAP), stop that level - 0.35 ATR; short invalidation max(high,VWAP), stop + 0.35 ATR. T1/T2 1.8/2.5 risk units. |
| Option Apex, `evaluate_option_apex_oi_shift`, evaluator minimum **1** bar | NIFTY/BANKNIFTY only, validated chain with ATM row. Long CE: CE OI change < 0, PE OI change > 0, **PCR >= 1.10**, spot close >= VWAP * 0.998. Long PE: PE OI change < 0, CE OI change > 0, **PCR <= 0.85**, spot close <= VWAP * 1.002. OI labels are implemented heuristic interpretations, not proven aggressor positions or forecasts. | Selected CE/PE premium LTP reference; both positions buy premium, including bearish PE. Stop/invalidation 0.78 * premium; T1/T2 +1.6/+2.4 premium risk units. An LTP is not an executable ask. Exact dated contract/lot/tick, aligned premium/chain/prior-close OI authority and liquidity are additional execution requirements. |
| Filtered ORB, `evaluate_orb_breakout`, minimum 30 | At least 4 current-session bars and exact opening starts 09:15/09:20/09:25. Positive prior-20 volume average. Bull: prior close <= ORB high, current close > ORB high and VWAP, RSI >= 55, RVOL >= 1.6. Bear: prior close >= ORB low, current close < ORB low and VWAP, RSI <= 45, RVOL >= 1.6. Prior close need not lie inside both range boundaries. A wick touch alone does not pass. | Decision close. Long invalidation ORB high; stop max(ORB low, current low - 0.25 * range). Short invalidation ORB low; stop min(ORB high, current high + 0.25 * range). T1/T2 1.6/2.4 risk units. |
| Supertrend Pullback, `evaluate_supertrend_pullback`, minimum 200 | Supertrend(10,3) current and prior direction must agree. Long: both current/prior closes above their EMA200, current close > VWAP and open, low <= ST * 1.004 OR <= VWAP * 1.003, RVOL >= 1.3. Short mirrors below EMA/VWAP/open with high >= ST * 0.996 OR >= VWAP * 0.997. Exclude 09:15 <= candle start < 09:45 and 11:30 <= start <= 13:30 IST. Positive prior-20 volume average. | Decision close. Invalidation current Supertrend. Long stop min(ST,low) - 0.25 ATR; short stop max(ST,high) + 0.25 ATR. T1/T2 1.5/2.5 risk units. |

Cash target construction uses `max(0.50, abs(entry-stop))`; option targets use
`max(1.00, entry-stop)`. ATR is floored at 0.05 where used. Prices are rounded by
the evaluator. Displayed nominal multiples can therefore differ from actual
price-level RR. `signal_risk_reward` and the existing ranker calculate numerical
geometry; benchmark strings and `confidence_pct` aliases do not establish win
probabilities. Position sizing can independently reject an otherwise detected
setup. Existing tests include `test_p1c_strategy_*_bidirectional*`, Order Block
mitigation/reuse, and Option Apex strict-field cases in `test_bot.py`; these were
source-inspected here, not re-executed by the focused research command.

`strategy_evidence.py` exposes descriptive independent JSON copies, exact bands
and predicates, no empirical metrics, no automatic promotion, and no entry
authority. Unknown identifiers stay `RESEARCH_HYPOTHESIS`. Registered evaluator
mechanics remain `OFFLINE_MECHANICS_TESTED`; empirical/OOS/reviewed live-paper
evidence is not supplied by this registry. The old shared-contract document and
preregistration are preserved as earlier proposals. Their universal future-close
continuation and any arbitrary global expiry proposal are superseded by this
mission's strategy-specific requirement. A descriptive registry does not enforce
the coordinator's execution policy; that must be reviewed separately.

## Historical execution and evidence boundaries

Cash `BacktestConfig` supports `NEXT_CANDLE_OPEN`, configurable T1 or T2 full exit,
and `STOP_LOSS_FIRST_CONSERVATIVE`. This is a separate research fill cohort from
any future automatic paper-trigger policy. It does not imply a one-second delay
or universal minimum-one-tick slippage rule. `IndianCostModel` defaults to five
basis points per leg and explicit charge assumptions; no current exchange fee
certification is claimed here.

Strategy 3 historical software is implemented in `option_execution.py`, reached
through the existing backtest engine and `run_frozen_study(option_request=...)`.
It requires an exact dated option master, separate underlying candles, chain and
bid/ask premium observations. It buys the next eligible observed ask open, applies
adverse slippage/tick rounding and all-or-none opening depth and lot constraints.
It never substitutes underlying price for premium. An intrabar stop touch with
unknown executable depth becomes `INTRABAR_STOP_REQUIRES_OBSERVED_EXECUTABLE_QUOTE`
and leaves accounting unresolved. Later observed-open gap stops, capped targets,
EOD/expiry exits require bid-side observations and depth. A missing exit is not a
fabricated close. Cash-only `research_protocol.StudyProtocol` still excludes
Strategy 3; that is a scope boundary, not absence of the separate option engine.

`historical_study` now freezes the exact source-session prefix/range as well as
configuration, data, current source hashes and rights/trust fingerprints before
evaluation. `HistoricalEvidenceArchive` retains original bytes and detects
tampering; a local digest is integrity evidence, not publisher authenticity.
`OperatorRightsPolicy` needs a retained rights document and explicit approval;
local approval does not prove a legal license. Publisher qualification remains
separate Ed25519 verification against approved roots. The existing tests using
test-only keys and rights documents are fixtures, including the test named
`test_real_shaped_signed_cash_study_replays_and_rechecks_current_rights`.

Retained public Phase 3 matrix `phase3_angel_acceptance_20261023_02.json` records
73 original historical bars with missing 15:15 and 15:20 intervals, insufficient
authentic complete study coverage and missing qualifying rights/trust/dated
identity authority. It also records a genuine stale feed packet with zero fresh
accepted events and zero completed accepted one/five-minute candles. This is
inspection of retained public evidence, not revalidation of private raw data or
a new observation. No current-source real completed-candle scanner acceptance or
qualified empirical study is established by this work.

The newer mission requires separate exact authorization before any provider
request, regardless of earlier one-shot stage text. No login, feed, history,
refresh, order or message request was made here. The old Phase 3 report's claim
that 2026-10-26 is the next official session is not adopted without a dated
official session notice. Operational stores, `.env`, raw licensed data and prior
receipts were not opened or changed by this workstream.

Earlier prose assertions of universal 60/20/20 partitioning, at least 50% win rate,
one-second next-open timing, hard-coded option lot examples and exhaustive
absence of option code gaps are not current source-derived acceptance. Preserve
those reports, but prefer exact executable contracts and current source-bound
tests. No win-rate target alone earns strategy promotion.

## Prioritized experimental slate and study protocol

These are unimplemented research hypotheses, not promoted strategies. A numerical
data acquisition price is **unknown** until scoped vendor/license quotes exist;
this work incurs no subscription or provider call. Reuse already-authorized
qualified inputs where available, and keep cash/option cohorts separate.

| Priority / version | Hypothesis and inputs | Control and falsification | Acquisition dependency |
|---|---|---|---|
| 1 / `relative-participation-h1` | Ranking by stock excess return versus contemporaneous sector/index, confirmed structure and time-of-day participation may distinguish leaders from sector-wide moves. Requires aligned completed bars, point-in-time constituents and volume/turnover. | Unchanged candidate quality rank and no-trade baseline. Reject if sealed OOS incremental net expectancy/selection value is nonpositive or explained by concentrated sector exposure. | Licensed sector/index history and constituent dates; price unknown. |
| 2 / `regime-pullback-h1` | Past-only trend/volatility regime may explain when existing VWAP/ST pullbacks fail; initially a soft research feature, not extra universal gates. | Original unchanged strategies; ablation without regime feature. Reject unstable sign or lost benefit under adverse costs and alternate past-only windows. | Sufficient multi-regime complete history; price unknown. |
| 3 / `opening-rotation-h1` | Compare existing ORB signals with sector-relative participation after the actual open. | Unmodified ORB; strict chronological intraday measurement. Reject if benefit depends on hindsight, top-mover selection, or concentrated event days. | Exact open bars, sector alignment, corporate-action policy; price unknown. |
| 4 / `compression-expansion-h1` | Past-only volatility compression followed by confirmed expansion or a failed-breakout reversal may offer a distinct setup cohort. | Simple fixed ORB/return baselines; version breakout and failure variants separately. Reject if costs or plausible entry delay erase benefit. | Multi-session licensed OHLCV and executable-spread evidence; price unknown. |
| 5 / `underlying-contract-h1` | Separate underlying directional score from option contract tradability, theta/delta exposure, spread and expiry fitness. | Same underlying thesis with predeclared fixed ATM choice; compare observed net outcomes and unresolved rates. Reject if gains depend on LTP fills, stale Greeks or unrealistic depth. | Exact dated chains, quotes, volume/OI baselines and Greeks/IV with source times; entitlement and price unknown. |
| 6 / `depth-flow-h1` | Legally available quote changes/depth may improve short-horizon execution-risk estimates. It is not executed aggressor flow without genuine trade classification. | Quote-only spread/depth control; cancellation/spoofing and sampling sensitivity. Reject if effect is latency-sensitive or survives only snapshots with unknown ordering. | Licensed granular event/depth history, clock quality and retention rights; highest data/engineering burden, price unknown. |
| 7 / `futures-basis-h1` | Dated futures/cash basis and aligned OI changes may help explain participation or contract risk. | Underlying-only thesis and constant contract-selection control. Reject if roll/carry, asynchronous prices or OI timing explain the effect. | Exact dated futures, cash, contract rolls and OI baselines; price unknown. |

Original research offers motivation, not Indian five-minute evidence. Moskowitz
and Grinblatt's *Do Industries Explain Momentum?* (1999, journal publication;
publisher page lists later online publication) motivates controlling industry
effects, not copying a monthly result into this scanner.
[Original journal source](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00146),
accessed 2026-10-24. Moskowitz, Ooi and Pedersen's *Time Series Momentum* (2012)
studies longer-horizon own-return signals across futures markets; it is a basis
for a comparator hypothesis, not evidence for intraday Indian profitability.
[Author research page](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum),
accessed 2026-10-24. No external performance percentage is imported into the app.

The preserved Astra preregistration is design-only and lacks dataset binding.
Before any genuine OOS run, freeze exact originals, universe membership,
exclusions, corporate actions, strategy/config/source versions, complete session
partitions and cost schedule. Its proposed 252-session/126-training/63-validation/
63-sealed-OOS plan is a starting proposal, not proof of sufficient statistical
power. Do not silently reduce it to accommodate short data. Use past-only warm-up
and never score it as OOS; purge/embargo where labels overlap. For intraday flat
cohorts, explicitly verify no position crosses a fold. Evaluate all declared
variants, retain failures, use session-clustered uncertainty and appropriate
multiple-testing correction. Such inferential tooling is not implemented by the
small partition fix. Report unresolved positions, sample dependence, net R and
INR expectancy, win/loss magnitude, drawdown, exposure, cost share, regime/year
stability and adverse-cost sensitivity. A good fixture metric has no promotion
authority.

Maturity advances only after independent review of qualified source/rights,
frozen untouched OOS outcomes and then a separate genuine forward-paper cohort
under the exact trigger/fill policy. A revised strategy needs a new ID/version
and fresh sealed data. Data/trust failures, unresolved accounting or material
execution drift suspend conclusions. No strategy was promoted or retired here.

## Remaining review concerns

The study fix covers session declarations matching consumed source bars, not
completion of every market session or every expected interval; those remain
quality/calendar gates. Malformed plan/schema hardening beyond the existing
contracts, inferential uncertainty, empirical calibration, a multi-instrument
study orchestrator and statistical promotion workflow remain separate work.
The metadata registry is descriptive and must not become an eligibility bypass.
Pending expiry/trigger design and financial event integrity must be verified by
the paper workstream against the actual coordinator/portfolio, not inferred from
this matrix. Root canonical proof must bind all final files after parallel edits.
