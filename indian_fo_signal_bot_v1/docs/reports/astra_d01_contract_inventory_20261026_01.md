# Astra D01.1: option and benchmark observation contract inventory

Date/access date: 2026-10-26, Asia/Kolkata. Owner: `/root/rank_review`.
Status: **READ-ONLY INVENTORY COMPLETE; D01 IMPLEMENTATION AND PROVIDER ACCEPTANCE NOT ESTABLISHED.**

This inventory inspected source and official public documentation. It created only
this report. No production or test code, configuration, environment file, operational
database or existing evidence was changed. No test, broker/auth/market-data request,
subscription, order or notification ran. Public documentation retrieval is distinct
from broker API access. This does not replace current C03 canonical verification.

The next useful implementation is a pure, bounded observation validator and offline
endpoint fixtures. Reuse the existing exact-contract and historical execution
contracts; do not treat the existing flattened option chains as a complete
point-in-time contract-fitness input.

## Existing contracts and exact reuse boundaries

| Existing source | Reusable contract | Boundary that D01 must retain or supply |
|---|---|---|
| `instrument_identity.py:428`, `validate_contract_identity` | Provider-specific identifiers; exact cash/index/futures/options classification; underlying, expiry, strike and side; declared validity interval; explicit price/quantity units, positive lot and multiplier 1. | Structural declarations do not confer source authority. This normalized identity does not retain a tick-size field. Supply separately qualified tick terms before execution. |
| `instrument_identity.py:734`, `resolve_contract_identity` | Rebuild from retained original master bytes; exact unique selection; date, ambiguity, expiry and inactive checks. | Resolution deliberately remains `eligible=false` and `historical_replay_allowed=false` without independent qualification. Same-day native inspection does not establish listing intervals. |
| `instrument_identity.py:181`, `option_contract` | Exact loaded Angel index-option token, master revision, expiry, strike, CE/PE, lot and multiplier for existing live proposals. | This is narrower than the neutral identity type: Angel index options only. Do not broaden it silently to stock options, futures or Upstox proposals. |
| `contract_universe.py:18`, `inspect_upstox_native_contracts` | Local native row checks bind derivative key/token, underlying key, label, expiry, strike, side and lot; paired CE/PE lot consistency. | Output at line 89 is unqualified inspection evidence with unknown effective dates. It does not carry native `tick_size`; preserve that omission as unavailable for executable normalization. No automatic rollover or master download. |
| `option_execution.py:65`, `_prepare`; `:224`, `run` | Existing `tradepulse.option-request.v1` / `tradepulse.option-observations.v1`: exact archived contract digest, five-minute underlying/premium rows, offset-aware times, bid/ask OHLC, opening depth in units, traded volume, paired ATM chain, prior closing OI, source qualification for historical research. | This is a historical/synthetic replay input, not an adapter snapshot. It supports long index CE/PE, one position, observed opening depth, modeled adverse tick rounding and explicit unresolved exits. Missing intrabar executable quotes cannot be created from LTP or bar volume. Do not repurpose snapshot quotes as five-minute bid/ask bars. |
| `brokers.py:1649`, Angel `get_quotes` | Exact token/exchange identity, finite LTP/OHLC, optional OI/volume, optional exchange-feed/trade timestamps. | The normalized object drops order-book depth and total buy/sell quantities. Timestamps are not required for every response, and normalization alone does not establish synchronized leg freshness. |
| `brokers.py:1953`, Angel `get_option_greeks` | Underlying/expiry echo checks when present, CE/PE, strike, duplicate-leg rejection and finite numeric parsing. | Missing Greek/IV fields currently become zero; values are rounded and returned without raw-unit, model/time-basis or source-clock metadata. A new validator must distinguish absent, invalid and observed zero. Reuse exact matching rules, not the zero-default semantics. |
| `brokers.py:2050`, `:2228`, `:2566`, Angel baseline and chain path | Paired-strike baseline storage/restoration, session-age checks, current OI versus retained prior baseline, explicit unsupported-capability failure, master-bound `ce_contract` / `pe_contract`. | The flattened chain omits each leg's quote/source clock, depth and most sensitivities. Optional Greek acquisition failure can yield absent Greek maps followed by zero IV. Its closing-window classification must not be asserted equivalent to the stricter historical runner's exact prior-session 15:30 baseline. |
| `brokers.py:3616`, Upstox chain normalizer | Requested underlying/expiry consistency, finite spot/LTP, OI/previous-OI arithmetic, sorted strikes and PCR mechanics. | Output at line 3694 discards leg instrument keys, bid/ask prices/quantities, volume and delta/gamma/theta/vega. Missing IV becomes zero. The output label `net_change_from_previous_day_close` is an implementation claim requiring dated baseline evidence; the public chain schema alone only labels `prev_oi` previous OI. |
| `brokers.py:3424`, Upstox quote; `brokers.py:202`, candle validation | Existing spot identity and quote echo checks; source timestamps when supplied; candle chronology/session/freshness gates. | The quote path validates spot metadata, not arbitrary derivative contracts. A quote is neither an executable option snapshot nor a benchmark return series. |

`instrument_archive.py:103` already accepts a finite positive declared tick size,
which `option_execution` checks against every premium price. Reuse that historical
term path rather than assuming the native master's numeric tick uses the same scale.
Existing regression locators include `test_option_execution.py:131` (depth/spread/
tick/time), `:150` (OI baseline), `:275` (duplicate/future/alias inputs), and
`test_contract_universe.py`. They were inspected, not executed in this inventory.

The generic candle validation can support explicitly identified benchmark bars.
However `candle_lineage.completed_cash_batch` at line 159 requires an EQ identity;
index data in cash snapshots is auxiliary. The inspected contracts do not provide
a dedicated benchmark/sector identity, point-in-time constituent mapping, aligned
return window, adjustment convention, source manifest and freshness verdict. Keep
index direction, sector-relative strength and a stock's own volume distinct.

## Official schema reconfirmation and unresolved units

All sources below were accessed on 2026-10-26. Public documentation is schema
evidence; it does not establish account access, commercial rights, delivery latency
or observed provider behavior. No user forum comment is used as a provider guarantee.

| Official source | Confirmed fields/scope | What remains unavailable |
|---|---|---|
| [Upstox put/call chain](https://upstox.com/developer/api-documentation/get-pc-option-chain/) | GET `/v2/option/chain`, underlying instrument key and expiry; each row has expiry/strike/underlying key and separate CE/PE instrument keys. Market data includes LTP, volume, OI, previous OI and bid/ask price/quantity; Greeks include delta/gamma/theta/vega/IV and provider POP. | The displayed response lacks a per-leg observation timestamp. The field table does not specify Greek scaling/time basis, an explicit IV conversion rule, quantity-to-lot conversion or dated prior-close baseline semantics. Provider POP is not TradePulse win probability. |
| [Upstox option Greeks](https://upstox.com/developer/api-documentation/option-greek/) | GET `/v3/market-quote/option-greek`, at most 50 requested instrument keys. Response identifies the instrument token and exposes last price, LTQ, current-day volume, previous close price, IV, sensitivities and OI. | `cp` is a price, not previous OI. The displayed response lacks an observation timestamp and bid/ask depth. Its IV example differs numerically from the chain example; examples do not prove an endpoint-to-endpoint conversion. No documented day/year or volatility-point basis was found in the reviewed field table. |
| [Upstox V3 feed](https://upstox.com/developer/api-documentation/v3/get-market-data-feed/) | Instrument-keyed Protobuf feeds; `ltpc.ltt`, `currentTs`, first-level quotes/Greeks; `full` describes five levels and `full_d30` thirty levels, with Plus-related limits. `vtt` is described as volume in contracts. | Do not rename `vtt` underlying units or apply lot conversion without a qualified field rule. Feed time, last-trade time and local receive time are distinct. Depth is displayed interest, not executed aggressor flow. User entitlement and feed implementation remain unverified. |
| [Upstox instrument files](https://upstox.com/developer/api-documentation/instruments/) | Native JSON carries derivative instrument key/token, underlying key/type, expiry, strike, side, lot and tick fields. JSON examples use numeric expiry values; the local parser explicitly expects millisecond epoch. | The page's JSON and legacy CSV tick examples use different numeric forms. Do not infer tick-price scaling from examples. A current native file is not a dated authority for historical lot/tick/listing terms. |
| [SmartAPI team's Greek announcement](https://smartapi.angelone.in/smartapi/forum/topic/4254/announcing-option-greeks-api-for-smartapi-users) | Official moderator announcement specifies POST `.../marketData/v1/optionGreek`, body `name` plus `expirydate`; rows contain name, expiry, strike, CE/PE, numeric-string sensitivities, IV and trade volume. | The documented sample has no contract token or observation time; resolve its terms against one exact retained master. It provides no explicit normalized Greek/IV unit contract. Older moderator comments about live-contract-only availability are historical statements, not newly verified entitlement or expired-data coverage. |

The [SmartAPI documentation page](https://smartapi.angelone.in/docs) returned an
access-denied page to this browser. The official search index exposed FULL-quote
field descriptions including exchange feed/trade time, OI, volume and depth, but
that is **not a fresh full-page schema verification**. Treat a complete current
Angel FULL-depth parser/spec as pending until an accessible official schema is
retained. The accessible official announcement above supports only the stated
Greek shape. No access restriction was bypassed.

## Concrete next validator and fixture scope

Implement one transport-free module and one isolated offline test module before
changing adapter/network behavior. The proposed neutral envelope is a declaration
for review, not an existing accepted application contract:

| Component | Required preserved information | Validation result |
|---|---|---|
| Envelope | Schema version; provider; endpoint/schema version; raw content hash and row locator; requested scope; explicit LIVE/SIMULATED provenance; local received/available time; source time and its documented semantics when actually supplied. | Bounded deterministic parsing; unavailable source time remains unavailable. Local receipt never substitutes for a missing exchange/Greek calculation time. |
| Identity | Exact contract and underlying identities, master revision, expiry/strike/side, declared validity and lot; separate qualified price/tick/quantity terms. | Reuse identity checks. Ambiguity, mismatched echo, token reuse, expired terms or absent dated authority cannot yield executable eligibility. |
| Observation fields | Raw value, raw field/unit identifier, presence status, optional normalized value/unit, normalization-policy version and supporting source reference. | Reject booleans, nonfinite and malformed quantities; preserve zero only when observed and valid. Unknown IV/Greek scale or quantity conversion produces `UNAVAILABLE_UNIT_CONTRACT`, not guessed values. |
| Clocks and alignment | Per-component quote, OI, Greek and underlying/benchmark observation times; local availability time; decision cutoff; explicit configured freshness/alignment policy. | All decision inputs must have been available by the decision. Do not merge fresh quotes with un-timed Greeks into a fully fresh snapshot. No forward fill or nearest-expiry substitution. |
| Depth | Ordered bid/ask levels, raw quantities and declared units, quote time, depth mode and level count. | Finite positive prices, nonnegative integral counts, uncrossed top-of-book, deterministic order, requested-size coverage only after units qualify. No volume-as-depth, no fabricated intrabar execution. |
| OI | Current and baseline observations with exact same contract/units; source references; baseline session/time/kind. | Compute change only after baseline qualification. Distinguish prior close, prior intraday observation and unknown `prev_oi` semantics. No default zero and no different-strike/expiry join. |
| Benchmark | Explicit index/sector identity, completed OHLC bars and units, interval/session/adjustment convention, source lineage; dated constituent mapping only if sector factors require it. | Reuse generic candle checks; require exact overlapping past-only windows. Cash EQ lineage must not be relabelled benchmark lineage. Missing benchmark excludes that factor instead of becoming neutral evidence. |

First fixtures should target Upstox V2 chain, Upstox V3 Greeks and Angel Greek
JSON shapes independently. Use synthetic values shaped like the documented
schemas, explicitly `SYNTHETIC_FIXTURE`; never call provider endpoints. Test absent
versus zero IV, signed theta/delta, numeric strings versus invalid booleans/NaN,
duplicate contracts, wrong token/underlying/expiry/side, missing source time,
future availability, incomparable unit declarations, stale component joins,
crossed/unsorted depth, fractional quantities, insufficient depth and mismatched
OI baseline. Include a rule that V2 chain `prev_oi` without a dated baseline cannot
satisfy the historical runner's prior-close contract.

The positive test must stop at **structurally valid offline observation with
explicit unavailable capabilities** when timestamps or units are undocumented.
An explicitly declared synthetic unit/time policy can test conversion and
point-in-time mechanics, but cannot register that policy as verified provider
semantics. Preserve raw evidence and parser version so later official clarification
can be applied without rewriting old observations.

Then add a small benchmark-alignment fixture and actual existing replay-eligibility
integration test: a schema-valid snapshot alone must not become a replay dataset,
live-qualified contract, ranking factor or paper fill. No change to Option Apex
rules, historical trust gates, C03 cash ordering, provider selection or subscription
scope is necessary for this first slice.

Completion of D01.1 means this inventory and bounded next interface are reviewable.
D01 implementation, full provider fixtures, exact contract tradability, authentic
dated observations, benchmark qualification, entitlement and real-data acceptance
remain separate work. Greek magnitude and displayed depth alone establish none of
those outcomes.
