# Phase 4 readiness: existing strategy and risk contracts

Verdict: **PHASE_4_NOT_STARTED_PHASE_3_GATE**. This is a source-only readiness
audit under the user's hard gate. The coordinating agent owns verification of
the newest Phase 3 receipts. This worker neither accepts Phase 3 nor starts
Phase 4 implementation. No strategy, test, configuration, existing document or
historical evidence was modified. No test, broker request, network call or
operational database read was performed for this audit.

The inspected strategy implementations are real source functions, not merely
names in planning documents. They are already dispatched by the existing cash
scanner. This does not establish real market-data availability, research
acceptance, profitability or current operational acceptance.

## Source identity and common contracts

Source SHA256 at inspection:

| File | SHA256 |
|---|---|
| `strategies.py` | `90625a7a66984a6fd9a9f799e61229dd8c086220fd5ab7455ac75fe4266222ab` |
| `scanner_engine.py` | `80e4a604507e3ad6b1472e67f412292b7487babf3f3947f34a672f45ecbb6fb4` |
| `backtest_engine.py` | `037aae0a6d32aa2d99bb3fdef7f933fdaec87ed052929019d17feec3bb111df7` |
| `test_phase4_strategy.py` | `c8462b6ed413f14a7aaf0d3371db9eed049d00577b2b24c6b6888764083b542a` |

All five evaluators call `filter_completed_candles(..., interval_min=5, now=now)`.
The filter and structural validator are at `strategies.py:389` and
`strategies.py:544`. They validate numeric finite OHLCV, directional high/low
relationships and chronological order, coalesce duplicate timestamps, and
filter incomplete candles. When `now` is supplied, completion depends on bar
start plus five minutes. Explicit `is_complete=False` remains incomplete.

The strategy-level validator is not the full LIVE qualification boundary. In
particular, omitted `now` and omitted completion metadata default to complete;
the helper coalesces duplicates rather than independently establishing provider
identity, session continuity or acquisition freshness. LIVE callers must retain
the stricter broker/scanner validation and provenance path. This is a contract
boundary observation, not a reproduced production bypass.

Indicators use only the supplied ordered prefix: EMA is initialized from the
first close (`strategies.py:757`); RSI uses its initial running history and then
Wilder-style updates (`strategies.py:772`); ATR uses true range and a running
initial average before recursive updates (`strategies.py:823`); VWAP resets on
each IST calendar session and weights typical price by volume
(`strategies.py:854`); Supertrend uses ATR and current/prior bars
(`strategies.py:878`). Minimum evaluator lengths are code admission thresholds,
not a claim that indicators have statistically converged.

Notation below: `E` is the last completed close rounded to two decimals; `A` is
`max(0.05, ATR(10)[-1])`; `W` is the current session VWAP; `V20` is average volume
of the preceding 20 completed bars, excluding the last bar. Cash/futures target
distance is `D=max(0.5, abs(E-SL))`; option premium distance instead uses
`max(1.0, premium-SL)`. Targets are rounded to two decimals. These are current
source rules, not proposed changes or recommended trading assumptions.

## Exact evaluator rules and support boundaries

| Strategy ID | Interval and admitted input | Source and existing dispatch |
|---|---|---|
| `strat_1_order_block` | 5m; at least 30 completed bars; last 15 searched for the block/impulse/retest | `strategies.py:912`; cash `scanner_engine.py:912` |
| `strat_2_vwap_pullback` | 5m; at least 35 completed bars; VWAP, EMA20, RSI14, ATR10, positive V20 | `strategies.py:1109`; cash `scanner_engine.py:930` |
| `strat_3_option_apex_oi` | 5m underlying plus validated ATM chain, explicit derivative lot; NIFTY/BANKNIFTY only | `strategies.py:1272`; index/option `scanner_engine.py:824` |
| `strat_4_orb_filtered` | 5m; at least 30 completed bars overall, at least four current-session bars, exact opening three bars | `strategies.py:1429`; cash `scanner_engine.py:930` |
| `strat_5_supertrend_pullback` | 5m; at least 200 completed bars; Supertrend(10,3), EMA200, session VWAP, ATR10, positive V20 | `strategies.py:1596`; cash `scanner_engine.py:930` |

### Order Block + BOS/FVG first retest

The evaluator searches the recent 15 bars backwards. A bullish block is a red
bar followed by two impulse bars, at least one impulse close above the block
high, and either the second impulse low above that high or displacement from
block open to second impulse close of at least `1.5*A`. A later close below
block low invalidates it. A prior post-impulse low at or below
`block_high*1.0015` marks it mitigated. The current first retest requires that
low condition, a close above block open and a close at or above block low
(`strategies.py:938`).

Long entry is `E`; `SL=block_low-0.25*A`; structural invalidation is block low;
targets are `E+2D` and `E+3D` (`strategies.py:972`). The bearish branch mirrors
the logic using a green block, lower closes, an optional downward FVG, prior
high at or above `block_low*0.9985`, entry below block open, `SL=block_high+0.25*A`,
invalidation at block high and targets `E-2D`, `E-3D`
(`strategies.py:1028`). Mitigation state is an explicit input/output set; sizing
must succeed before the newly triggered zone is marked used. The searched
15-bar prefix is not explicitly restricted to the current session.

### VWAP pullback/rejection

Long requires last low at or below `W*1.0025`, a bullish candle closing above
VWAP and at or above `EMA20*0.998`, RSI14 in `[48,72]`, and volume at least
`1.4*V20`. `SL=min(last_low,W)-0.35*A`; invalidation is `min(last_low,W)`;
targets are `E+1.8D`, `E+2.5D` (`strategies.py:1141`).

Short requires last high at or above `W*0.9975`, a bearish candle closing below
VWAP and at or below `EMA20*1.002`, RSI14 in `[28,52]`, and the same volume
surge. `SL=max(last_high,W)+0.35*A`; invalidation is `max(last_high,W)`;
targets are `E-1.8D`, `E-2.5D` (`strategies.py:1205`). The setup zone spans
entry and VWAP. This implementation exists and is connected; authentic
operational acceptance is a separate gate.

### Option Apex OI shift

The direct evaluator accepts any nonempty completed underlying prefix; it has
no explicit 15/30/35-bar minimum (`strategies.py:1285`). It validates the chain's
ATM, positive PCR, positive CE/PE premiums, nonnegative OI and supplied OI
changes (`strategies.py:553`). It does not itself establish the authenticity,
freshness or prior-close authority of those observations.

Call entry requires call OI change below zero, put OI change above zero,
PCR at least `1.10`, and underlying close at least `W*0.998`. Put entry requires
the converse OI signs, PCR at most `0.85`, and close at most `W*1.002`.
Both buy premium: `SL=0.78*premium`, targets `premium+1.6D` and
`premium+2.4D`, setup zone `[0.97*premium,1.02*premium]`; invalidation equals
the premium stop (`strategies.py:1309`, `strategies.py:1366`). A bearish market
view buying a put still uses long-premium price geometry.

The scanner separately checks Angel-specific exact option contract, expiry,
strike, side, lot and instrument identity (`scanner_engine.py:839`). Non-Angel
LIVE analytical chains do not establish supported execution contracts
(`scanner_engine.py:821`). LIVE futures proposals from the other four index
evaluators are explicitly withheld for lack of exact futures master and contract
candles (`scanner_engine.py:858`). Historical option replay has separate,
stronger observation/chronology rules in `option_execution.py`; cash acceptance
cannot establish option-history acceptance.

### Opening Range Breakout

Current-day opening bars must start exactly `09:15`, `09:20`, `09:25`; a later
fresh window is not substituted (`strategies.py:1447`). Let `H`/`L` be their
highest high/lowest low. Long requires prior close at or below `H`, current
close above `H` and VWAP, RSI14 at least 55 and RVOL at least 1.6.
`SL=max(L,last_low-0.25*(H-L))`, structural invalidation `H`, targets
`E+1.6D`, `E+2.4D` (`strategies.py:1472`).

Short requires prior close at or above `L`, current close below `L` and VWAP,
RSI14 at most 45 and RVOL at least 1.6. `SL=min(H,last_high+0.25*(H-L))`,
invalidation `L`, targets `E-1.6D`, `E-2.4D` (`strategies.py:1531`).

### Filtered Supertrend pullback

The last bar must be within session, outside `09:15 <= time < 09:45`, and
outside the inclusive `11:30`–`13:30` exclusion window
(`strategies.py:1607`). Long requires bullish Supertrend on the last two bars,
both closes above their EMA200, current close above VWAP, a bullish candle,
volume at least `1.3*V20`, and low near ST (`<=ST*1.004`) or VWAP
(`<=W*1.003`). `SL=min(ST,last_low)-0.25*A`, invalidation `ST`, targets
`E+1.5D`, `E+2.5D` (`strategies.py:1634`).

Short requires bearish Supertrend on the last two bars, both closes below
EMA200, current close below VWAP, a bearish candle, the same volume threshold,
and high near ST (`>=ST*0.996`) or VWAP (`>=W*0.997`).
`SL=max(ST,last_high)+0.25*A`, invalidation `ST`, targets `E-1.5D`,
`E-2.5D` (`strategies.py:1699`).

## Risk, exits, ranking and actionability

`TradeSignal` is a candidate data object (`strategies.py:15`), not an order or
guarantee of an executable price. It carries entry/zone, stop, two targets,
invalidation, sizing, charges, rationale, bar timestamp, source mode and identity.
It does not contain a distinct detected/qualified/actionable state machine,
strategy-version field or per-condition pass/failure list. Those are future
Phase 4 presentation/interface questions, not evidence that implementation began.

Evaluators emit levels; they do not monitor exits or place orders. Structural
invalidation may differ from the buffered stop. Historical execution separately
uses next-contiguous-candle-open admission, conservative stop-first collisions
and the configured intraday square-off convention (`backtest_engine.py:549`,
`backtest_engine.py:1083`, `backtest_engine.py:1785`). A historical fill model
cannot be represented as an observed live fill.

`size_position` validates finite positive inputs, stop direction, supported
instrument types, multiplier one, explicit whole lots for derivatives and long
premium only for options (`strategies.py:655`). It finds the maximum whole-unit
or whole-lot quantity satisfying both the cent-floored risk budget and capital
reserve, with nonnegative estimated charges/slippage included. Futures reserve
full notional; no verified margin model is asserted. Gap losses can exceed the
modeled stop risk. Scanner sizing currently uses its existing approximate Indian
charge schedule with default zero modeled slippage; these are source assumptions,
not confirmation of the applicable current statutory schedule or available
executable depth (`strategies.py:637`, `strategies.py:705`).

At the scanner boundary, evaluator quantities are recomputed before acceptance
(`scanner_engine.py:953`). `validate_trade_signal` requires finite price/risk
fields, positive whole quantity, integer quality `[0,100]`, ordered setup zone,
compatible direction/position type and directional stop/invalidation/entry/target
geometry (`strategies.py:94`). Long premium has long-price geometry even for
bearish puts. Exact identity/provenance remain separate checks. No new universal
minimum RR, liquidity model or capital-allocation policy is implied by this
validator.

Ranking already exists: quality descending, then **computed gross T1 reward/risk**
descending, then symbol/strategy/direction/position type/timestamp/label and a
canonical full-JSON tie-break (`strategies.py:130`). It validates all candidates
first and does not trust the display ratio string. Scanner calls it after
resizing and geometry rejection (`scanner_engine.py:978`). Its summary labels
the policy `QUALITY_THEN_TARGET1_REWARD_RISK_THEN_IDENTITY_V1` and scope
`CANDIDATE_PRIORITY_ONLY_NO_CAPITAL_ALLOCATION` (`scanner_engine.py:1124`).
Each candidate is sized against the account configuration independently; ranking
does not reserve portfolio capital across all candidates.

The setup-quality score is deterministic confluence, not a probability.
Available features are RVOL, directional VWAP/ATR distance, ATR displacement and
optional market breadth, with base weights `.30/.25/.30/.15`, renormalized over
available inputs (`strategies.py:177`, `strategies.py:218`). Missing breadth
remains unavailable. The legacy `confidence_pct` alias mirrors setup quality
(`strategies.py:48`). The hardcoded `win_rate_benchmark` strings at
`strategies.py:1011`, `strategies.py:1191`, `strategies.py:1349`,
`strategies.py:1517` and `strategies.py:1685` are not authenticated research or
calibrated TradePulse results. The scanner serializes the candidate object
(`scanner_engine.py:1133`); existing Telegram formatting appropriately labels
setup quality unverified (`telegram_bot.py:43`). Future compatibility work must
avoid turning legacy names/text into new performance claims.

## Findings and limits: source facts versus unexecuted concerns

1. **Warm-up capacity mismatch is a source-backed limitation.** Supertrend needs
   200 completed 5m bars, while the current Angel stream deque retains at most
   150 (`angel_feed.py:261`, `angel_feed.py:358`, `angel_feed.py:595`). In a path
   consisting solely of that buffer, Supertrend cannot pass its length check.
   No fresh operational failure was reproduced, and this audit does not assume
   an authorized alternate history source or permit a fallback. The handoff audit
   must verify the exact serving path before any future implementation decision.
2. **Target labels and actual RR can differ by source arithmetic.** Targets use
   a minimum modeled target distance of 0.5 INR (one INR for options) rather than
   always the actual stop distance. For illustration only, `E=100`, `SL=99.80`
   under VWAP gives modeled T1 `100.90`, actual gross RR `4.5`, versus nominal
   text `1:1.8`. This is an algebraic consequence, not an executed test or a
   conclusion that the preserved target rule is defective. Ranking already
   computes actual gross RR. Existing dashboard and Telegram display the string
   (`public/index.html:1414`, `telegram_bot.py:49`); future explanation work
   should distinguish nominal model multiples, gross level RR and costs.
3. **Direct evaluators are not independent LIVE gates.** Their minimum lengths,
   last-bar session check and completion filtering do not replace input identity,
   whole-batch chronology/gap/freshness or provider-authority checks. They also
   use RSI/ATR/EMA across available sessions, whereas VWAP resets each session.
   Any proposed look-ahead bypass based on directly calling an evaluator is
   **unreproduced** here; production scanner ingress and historical prefix checks
   must be assessed before calling it a production defect.
4. **No-return explanations are coarse.** Most unmet strategy rules return `None`;
   scanner `instrument_errors` captures exceptions/rejections, and empty accepted
   scans expose `NO_ELIGIBLE_SETUP_FOR_ACCEPTED_INPUT`
   (`scanner_engine.py:1126`). There is no per-strategy warm-up versus rule-fail
   record for every `None` result. This is a future explanation gap, not missing
   evaluator implementation.
5. **Execution/depth/research remain separate.** Modeled sizing and generated
   levels do not establish executable cash depth, actual fills, portfolio
   allocation, authenticated historical studies or option execution evidence.
   No unsupported liquidity or universal actionability state should be inferred.

## Existing test inventory inspected, not rerun

The following named tests/classes exist in source. Their current pass counts and
source/log integrity are for the coordinating agent to establish from existing
receipts. Merely listing them here is not a new PASS claim.

| Existing source inventory | Covered intent visible in test source |
|---|---|
| `test_bot.py:188`–`:229`, `TestIndianFOSignalBotPhase1C` at `:1034` | Five evaluator positives; bidirectional levels/non-triggers, OB first-retest/mitigation, strict OI fields, Supertrend opening/chop windows |
| `test_bot.py:1301` | Quality-score reproducibility, boundaries and unavailable breadth |
| `test_phase4_strategy.py:26` | Four ORB tests: exact opening bars, later-window rejection, each missing opening bar, incomplete opening bar |
| `test_bot.py:7088` (`TestPositionSizingRiskAccounting`) | Risk/capital accounting, exact boundaries, gap/stop distinction, OB state when sizing fails |
| `test_bot.py:5353`, `:5585`, `:5809`, `:6087` | Historical prefix chronology, conservative collisions, daily risk limits, chronological splits/eligible strategy mechanics |
| `test_phase4_e2e.py:45` | Nine provider-shaped offline end-to-end tests; real evaluator, risk, persistence/dry-run, dedup/restart, invalidation, provider failure and no research promotion |
| `test_cash_workflow.py:72` | Eight HTTP/paper/dashboard/history integration tests including non-actionable risk rejection and write rollback; fixtures only |
| `test_phase4_market_data.py:121` | Quote/candle source controls, malformed/naive/future/stale/identity checks, forming bars and no silent provider fallback |

A source search found no direct `rank_signal_candidates` invocation in the
current `test_*.py` files. That search alone does not prove that integration tests
never exercise ranking. Dedicated equal-score/actual-RR/canonical-tie-break
expectations should be verified in the independent future QA pass.

## Non-conflicting plan, only after the Phase 3 hard gate passes

1. The coordinator first establishes accepted Phase 3 completed-candle,
   persistence, real scanner-consumption and safety evidence. No new live probe
   is authorized by this readiness audit.
2. Data/scanner ownership documents the exact qualified batch and warm-up horizon.
   Preserve the existing ingress, lineage and freshness controls. Resolve the
   150/200 horizon limitation as an explicit support decision before claiming
   Supertrend operational.
3. Strategy ownership preserves current formulas and supplies additive,
   versioned explanations for warm-up and rule rejection where justified.
   Distinguish candidate detection, qualification and permitted downstream action
   using existing consumer contracts instead of replacing evaluators.
4. Independent QA tests actual scanner dispatch for supported strategies, exact
   warm-up boundaries, prefix-only evaluation, invalid geometry and quantity,
   actual versus display RR, deterministic ranking/ties, insufficient option
   inputs and failure/duplicate behavior. New tests must retain clearly labelled
   fixtures and cannot mint real acceptance.
5. Risk/output ownership reviews displayed score/benchmark semantics and price
   units without adding an unapproved trading or portfolio-execution feature.
   Source changes, focused/integration/full verification and releases remain
   gated on Phase 3 acceptance and a reviewed implementation scope.

Changed file by this worker: only
`docs/reports/phase4_readiness_strategy_risk_20261023_01.md`.
