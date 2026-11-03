# Agent 2 — Part B options intelligence checkpoint 1 — 3 November 2026 IST

Completed an isolated descriptive exact-contract/supplied-quote research component on `feature/new-strategies`, based on approved Volume checkpoint `6e6bd76673638bf4fa8aa575bd2f37fdc62d41d4`. The commit containing this report is this Part B checkpoint; its SHA is supplied in the owner handoff and Git history. Local commit only; no push, merge, signal activation or next checkpoint.

`TP-OPTION-FIT-1.0` is default OFF. Explicit Boolean `enabled=True` permits offline analysis only. Every result has `actionable:false`, `eligible:false`, `execution_allowed:false` and `historical_replay_allowed:false`; these fields cannot be supplied as constructor/replacement arguments. `VERIFIED` describes checks on supplied facts and arithmetic, never publisher authentication, real listing authority, execution readiness or a probability.

This first checkpoint implements descriptive identity/quote quality, indicative friction/premium scenarios and optional context. It does not select a directional thesis, recommend a CE/PE, rank contracts, accept future triggers, create entries/exits or maintain positions. Main retains Option Apex prospective admission, execution, account safety and APIs. The earlier volume implementation, tests, manifest, report and receipt are unchanged; its original source/log receipt still validates.

## Authority and actual interface audit

Read the existing Agent 2 master prompt; finalized Stage1 specification `TP-STAGE1-QUANT-DECISION-SPEC-2026-10-31-V1.0`, especially §7 and §9; [H0/H1 strategy contract](../agent-contracts/TP_STRATEGY_INTEGRATION_CONTRACT_V1.md); [UI/API contract](../agent-contracts/TP_UI_API_CONTRACT_V1.md); current [master status](../project/TRADEPULSE_MASTER_STATUS.md); and [Volume Checkpoint 1](TP_VOLUME_CHECKPOINT_1_20261103.md). The complete final quantitative specification remains the calculation authority, SHA-256 `9d6a892092d780afbcb45673cae083df242528eda8b87f8bfdd1403fd062944d`.

The [read-only option interface audit](TP_OPTION_INTERFACE_AUDIT_20261103.md) inspected actual exact/native master, observation/Greek/OI/depth structures, historical option execution and tests. Findings:

- `ContractIdentity` retains provider/token/expiry/strike/side/lot/date/units, but its normalized validator does not retain premium tick. Native masters do not establish effective dates or publisher authority. No tick, date, listing or token-to-terms truth is inferred here.
- Existing `tradepulse.option-capture.v1` preserves ABSENT/NULL/OBSERVED fields, including zero, but leaves source time, normalized units and executable depth unavailable. V3 `cp` is previous close price, not previous OI. Greek magnitudes from distinct endpoints cannot establish common units.
- Current historical Option Apex replay uses a different archived-contract schema and explicit bid/ask bars/ticks/source gates. This component never calls or modifies that engine.
- No existing API accepts this result schema. No scanner/ranking/account consumer was added. Native captures and core identities cannot be automatically cast into this component; compatibility tests prove the missing boundaries remain unavailable.

## Exact files and implemented modules

| File | Implementation |
|---|---|
| [.gitattributes](../../.gitattributes) | Adds four narrowly scoped option source/doc/receipt rules. Existing volume rules and other application paths retain their behavior. |
| [option_intelligence/__init__.py](../../option_intelligence/__init__.py) | Version/schema constants and `OPTION_INTELLIGENCE_ENABLED=False`. |
| [option_intelligence/evidence.py](../../option_intelligence/evidence.py) | Frozen scoped Evidence, explicit failures, bounded Decimal/offset time/date/tick validation, deterministic serialization/digests. |
| [option_intelligence/identity.py](../../option_intelligence/identity.py) | Frozen exact dated contract, provider/token/unit/lot/tick/status/membership validation; stable contract ID; nearest two expiries within supplied same-scope records only. |
| [option_intelligence/quotes.py](../../option_intelligence/quotes.py) | Current supplied bid/ask/size/clock/source inspection, spread/mid/size comparisons and optional displayed-depth validation. No execution/admission API. |
| [option_intelligence/context.py](../../option_intelligence/context.py) | Independent optional IV/Greeks/OI/OI-change/volume inspection, presence retention, matched OI delta and labeled Greek scenario. |
| [option_intelligence/fitness.py](../../option_intelligence/fitness.py) | Non-actionable snapshot DTO, full configuration/analysis identity, explicit cost assumptions, indicative friction/brackets/budget comparisons. |
| [option_intelligence/verify.py](../../option_intelligence/verify.py) | Guarded selected offline regression, complete test IDs and before/after source/log evidence. |
| [tests/__init__.py](../../option_intelligence/tests/__init__.py) | Synthetic fixture namespace; new tests remain below the package to preserve the approved volume source manifest. |
| [tests/test_identity.py](../../option_intelligence/tests/test_identity.py) | 29 identity/date/provider/lot/tick/units/membership/expiry-selection tests. |
| [tests/test_context.py](../../option_intelligence/tests/test_context.py) | 31 presence/unit/time/OI-change/Greek/IV/volume and scenario tests. |
| [tests/test_quotes.py](../../option_intelligence/tests/test_quotes.py) | 19 book/source/clock/cadence/size/spread/depth tests. |
| [tests/test_fitness.py](../../option_intelligence/tests/test_fitness.py) | 15 cost/bracket/sensitivity/immutable permissions/public-helper identity and decision-binding tests. |
| [tests/test_compatibility.py](../../option_intelligence/tests/test_compatibility.py) | Four actual core-schema/capture incompatibility and runtime-import isolation checks. |
| [TP_OPTION_INTERFACE_AUDIT_20261103.md](TP_OPTION_INTERFACE_AUDIT_20261103.md) | Source-derived compatibility, ownership and missing-field findings. |
| [TP_OPTION_EXPERIMENT_MANIFEST_V1.json](TP_OPTION_EXPERIMENT_MANIFEST_V1.json) | Frozen pilot assumptions, formulas, optional ablation plan and first-checkpoint scope. No empirical selection or holdout. |
| This report | Implemented scope, inputs, formulas, evidence, dependencies and review stop. |
| [Receipt](../evidence/option_intelligence_checkpoint_20261103_01.json) / [log](../evidence/option_intelligence_checkpoint_20261103_01.txt) | Immutable source-bound 330-test verification. |

Nineteen changed paths: 18 additions and one scoped attribute-file extension. No production Python, operational configuration, storage schema, shared contract or frontend file changes. No dependency download, broker request, private `.env` read, external quote acquisition, Telegram send, real order or operational database modification.

## Input and evidence requirements

The top-level `analyze_option` takes a contract declaration and supplied quote, explicit decision time, intended whole-lot count, `QuotePolicy`, `SessionWindow`, optional `FrictionAssumptions`, separately dated stock membership, optional context/depth, explicit research provenance, and Boolean opt-in. It returns `tradepulse.option-intelligence.v1`, version `TP-OPTION-FIT-1.0`. It is not a `TradeSignal`, `ContractResolution` or new HTTP schema.

| Input | Exact requirements / unavailable behavior |
|---|---|
| Contract | Explicit `provider`, `identifier`, `symbol`, `underlying`, `underlying_identifier`, `exchange`, `segment`, `instrument_type`, `option_type`, `expiry`, `strike`, `lot_size`, `tick_size`, `multiplier`, `price_unit`, `quantity_unit`, `valid_from`, `valid_to`, `contract_status`, `source`, `source_revision`, `master_id`, `master_sha256`, `source_observed_at`, `received_at`, `available_at`. No guessed default lot, premium tick, symbol mapping or effective date. |
| Contract scope | NFO OPTIDX for NIFTY/BANKNIFTY, or OPTSTK with a separately supplied as-of ordinary NIFTY200 membership declaration. Provider-specific token format, distinct underlying/option tokens, INR premium per underlying unit, UNDERLYING_UNITS quantity, multiplier1, positive exact integer lot, positive premium tick. Valid dates must cover the decision and not extend beyond expiry. Expiry must be strictly later than the decision's IST date; expiry-day excluded. ACTIVE declaration required; UNKNOWN is NOT_ESTABLISHED. |
| Identity source | Nonempty source/revision/master reference and 64-character lowercase SHA-256; ordered source/received/available times, available by decision. These validate a declaration only. Source authentication, actual listing and historical validity are not certified by a digest or ACTIVE label. |
| Stock membership | Exact provider/underlying/token, `universe=NIFTY200`, `ordinary_equity=True`, effective dates, available time, source/revision. Missing or out-of-date membership remains unavailable. Membership never proves option listing. |
| Quote | Explicit `quote_id`, exact `contract_id`, provider and master `source_revision`, quote `source_id`, `observed_at`, `received_at`, `available_at`, `bid_at`, `ask_at`, `bid`, `ask`, `bid_size`, `ask_size`, `price_unit`, `quantity_unit`. No LTP/spot/old-premium fallback. Positive on-tick `bid<ask`; research policy excludes locked as well as crossed markets. |
| Sizes | Nonnegative whole supplied counts with explicit CONTRACTS or UNDERLYING_UNITS unit. CONTRACTS multiply the dated lot exactly once. Both top sizes must cover `intended_lots*lot_size`; insufficient size is UNAVAILABLE while valid numeric metrics remain visible. Deeper aggregate size never replaces insufficient L1 size. |
| Quote policy | Exact expected source ID; explicit cadence/clock evidence reference, available time, documented cadence and timestamp resolution. Pilot maximum age<=3s, separate leg skew bound; declared cadence/resolution must support these bounds, and resolution cannot exceed leg skew. Missing evidence is NOT_ESTABLISHED, not silently a fresh quote. Reference strings still do not authenticate the source. |
| Quote clocks | Leg times no later than source snapshot, then `observed<=received<=available<=decision`. Oldest leg age is used; stale prior-session or over-age/misaligned legs are STALE. No local-receive-time substitution for missing source time. |
| Session | Explicit dated source/available-time declaration. NORMAL is09:15–15:30 IST; CLOSED yields UNAVAILABLE; special-session policy is NOT_ESTABLISHED. No weekday or holiday inference from current config. This is descriptive observation time, not permission to enter after14:45. |
| Cost assumptions | Effective-dated version/source/availability, nonnegative incremental entry/exit impact per underlying unit, explicit full round-trip INR fees for the intended quantity, positive declared risk/capital scenario budgets, and loss fraction25/35/45%. No real tax/broker plan is filled in; missing assumptions yield UNAVAILABLE. Budget comparisons are arithmetic, not account authority. |
| Optional context | Exact contract ID/provider/master revision; source ID and source/received/available clocks; caller-declared independent max age; scalar `fields` and explicit `units`. Eight fields: IV, delta, gamma, vega, theta, OI, OI change, volume. Each keeps ABSENT/NULL/OBSERVED and its own state; optional problems do not veto independently valid quote arithmetic. |
| Optional depth | Exact same contract/source revision/source and current decision, aligned source clocks, INR and explicit quantity unit; 1–30 unique sorted bid/ask levels with on-tick positive prices and nonnegative integer size. Top level must agree with current quote. Coverage is displayed arithmetic, not executable flow or future fillability. |
| Numeric/time domain | No Boolean numerics, NaN/infinity, unbounded input or naive time. Input scalar absolute bound2^53-1; nonzero magnitude>=1e-18. These are explicit engineering bounds, not trading thresholds. Offsets and canonical dates required. |

Evidence states:

- **VERIFIED:** supplied structure, identity join, declared units, as-of clocks and/or arithmetic passed the named checks. Scope is always supplied-input validation; authenticity remains separate.
- **UNAVAILABLE:** missing/null data, future availability, closed session, insufficient displayed size or missing cost inputs. Examples: `MISSING_TICK_SIZE`, `BID_AT_UNAVAILABLE`, `QUOTE_NOT_YET_AVAILABLE`, `INSUFFICIENT_DISPLAYED_SIZE`.
- **STALE:** observed data exceed explicit age/alignment/session bounds, such as `QUOTE_TOO_OLD`, `QUOTE_LEGS_NOT_SYNCHRONIZED`, `OPTIONAL_CONTEXT_STALE`.
- **INVALID:** malformed/nonfinite/on-tick/geometry errors, identity or unit mismatches, crossed/locked book, invalid lot/expiry, inconsistent OI change. No source or price is repaired.
- **NOT_ESTABLISHED:** unknown status/units, missing cadence or calendar evidence, unjoined OI baseline semantics, provider authenticity, actual listing authority and future fillability.

Results retain exact contract terms/revision, as-of/source/received/available clocks, complete configuration and hash, deterministic analysis ID, field reasons and ordinal-quality semantics. Underlying thesis/candle are explicitly null because this descriptive checkpoint does not consume them. Historical option P&L always returns `UNAVAILABLE/BLOCKED_DATA_FOR_HISTORICAL_OPTION_PNL`. Optional Greeks are not a mandatory P&L input; the missing qualified executable bid/ask archive and absent execution engine are the historical block.

## Approved formulas and conventions

| Calculation | Implemented formula and scope |
|---|---|
| Spread | `mid=(bid+ask)/2`; `spread=ask-bid`; `relative_spread=spread/mid`. Compare inclusively against index1%/stock2% pilot bands. These are unvalidated comparison flags; a wide spread does not make otherwise correct supplied numbers INVALID or grant execution eligibility. No fitted quality score. |
| Size | `requested_units=intended_lots*lot_size`; `displayed_size_ratio=min(bid_units,ask_units)/requested_units`. Both top sides must cover intended quantity for current quote evidence. Coverage remains a supplied snapshot, not a guarantee. |
| Current-book proxy | `E=ceil_tick(ask+entry_impact)`; `X_now=floor_tick(bid-exit_impact)`. These are estimates at the supplied current book, not executed or future prices. |
| Full modeled snapshot friction | `F=qty*(E-X_now)+fees_round_trip`. Breakdown: `qty*(ask-bid) + qty*((E-ask)+(bid-X_now)) + fees`. Quoted spread once; incremental impact and adverse tick rounding once. Assumes a constant book for the proxy, not a forecast of future friction. |
| Premium scenarios | `S=floor_tick((1-loss_fraction)*E)` with25/35/45%, baseline35%; `R=E-S`; `T=ceil_tick(E+1.8*R)`. Gross unit-consistent risk=`qty*R`; friction per gross risk=`F/(qty*R)`. These are hypothetical premium levels, not underlying rupees or actual orders. |
| Indicative economics | Projected stop/target bids are adversely rounded after exit impact. Estimated loss=`qty*(E-stop_bid_after_impact)+fees`; hypothetical target gain=`qty*(target_bid_after_impact-E)-fees`; indicative net RR=gain/loss. No observed future bid is invented and no net return/expectancy is claimed. Cost estimates do not override actual Main risk gates. |
| IV/Greeks | Explicit IV PERCENT divides by100; FRACTION unchanged. Signed delta constrained to[0,1] CE /[-1,0] PE. Nonnegative gamma and vega. Vega per percentage point multiplies by100 to become per IV fraction. Theta per year divides by365 only with explicit365-calendar-day declaration; daily unit is calendar day. No inferred provider conventions or IV percentiles. |
| Greek scenario | `delta*dS + .5*gamma*dS^2 + vega_fraction*dIV_fraction + theta_day*elapsed_calendar_days`. All four validated Greeks required; missing is not zero. Label is local approximation only, never an execution price, probability, institutional flow or dealer GEX. |
| OI / OI change | Exact contract/provider/revision and compatible original quantity unit; CONTRACTS normalize once. Derive current minus actually supplied prior baseline. INTRADAY requires ordered same-session times within declared alignment; PRIOR_CLOSE requires explicit preceding-session declaration and exact15:30 IST observation. Unknown `prev_oi`, price `previous_close` or baseline semantics cannot supply a baseline. An observed signed raw `oi_change` requires that join and must agree with it; missing/null raw change does not block independently derived delta. Zero baseline gives signed change, never an invented percentage. |
| Expiries | Sort future ACTIVE/date-valid supplied records within one provider/underlying/type scope, take two unique dates. Always label supplied-subset scope and complete listing universe NOT_ESTABLISHED. No unlisted contract generation, global nearest-expiry claim or selection recommendation. |

Stage1 synthetic premium example matches E102.00, S66.30, gross one-lot risk1785 for50 units, T166.30. A separate vector proves spread/impact/rounding are not charged twice. Standalone friction/depth helpers reject cross-contract, fractional-lot or differently timed quote evidence. Equivalent Decimal spellings do not change contract identity.

## Executed evidence

From `indian_fo_signal_bot_v1`:

```powershell
python -B -m option_intelligence.verify --receipt docs/evidence/option_intelligence_checkpoint_20261103_01.json
python -B -m option_intelligence.verify --validate docs/evidence/option_intelligence_checkpoint_20261103_01.json
python -B -m volume_research.verify --validate docs/evidence/volume_checkpoint_20261103_01.json
```

**330/330 passed**, failures0, errors0, skips0, expected/unexpected failures0, unraisable errors0; exit0. Unittest **34.647s**, full guarded run **36.797s**, Python3.12.4. Current-source/log validation passes for the new receipt and the original volume receipt. Before/after source hashes match. Relevant volume and production/core files have an empty diff against6e6bd76. Whitespace checks pass.

| New options module | Passed | Existing regression group | Passed |
|---|---:|---|---:|
| Identity | 29 | Approved volume primitives / execution / retest | 28 /27 /18 |
| Optional context | 31 | Existing option observations / execution / universe | 32 /18 /9 |
| Quotes/depth | 19 | Strategy / research protocol | 4 /10 |
| Friction/result | 15 | Market admission / cash lineage | 22 /27 |
| Compatibility | 4 | Cash rank / retained rank history / H1 conflicts | 9 /18 /10 |
| **New options** | **98** | **Existing volume + core** | **232** |

The runner sets safe literal process flags (`paper_sim`, Telegram dry-run true, scheduler false, bytecode off), installs the established outbound socket/DNS guard before the credential-free `test_bot` bootstrap, and uses existing disposable fixture stores. It records all expected/executed/passed IDs, module counts, source/log hashes, interpreter/platform and installed package versions. Receipt/log are exclusive-create and cannot be overwritten by the runner. LIVE/Angel labels in baseline logs are authored adapter-shaped fixture data, not actual provider requests. Validation reruns no tests.

All targeted options runs during assembly passed (initial84, then85/93/94 as checks were added; four separate compatibility checks passed). The canonical98-new-test result is authoritative for final sources. No failed acceptance receipt was produced. This is selected offline mechanics evidence, not a full-suite, real-market, source-authentication, calibrated-score, current-fee, performance or execution acceptance result.

No dependency was installed or changed. Existing pin mismatches remain: cryptography50.0.1 versus50.0.2, pycparser2.22 versus3.11, tzdata2024.1 versus2026.5, websockets16.1.1 versus15.0.1; cffi2.1.1 matches. Source-bound success is not pinned-environment certification.

## Contract compatibility, dependencies and review stop

No existing strategy/UI/API contract migration is required for isolation. The schema is proposed research-only output; no current consumer accepts it. Main must review any future typed adaptation rather than cast a mutable legacy TradeSignal/core master/capture. Premium tick, source/leg times, quantity/Greek units, dated master authority and actual listing evidence remain explicit missing boundaries. No readiness Boolean or new provider-native adapter was added to Main-owned code.

**Genuine acquired data denominator: 0 contracts /0 quote events.** Remaining broker/data dependencies: qualified dated master with actual token/terms/lot/tick/status and listing coverage; effective-dated NIFTY200 stock membership; reliable exchange/holiday/special-session calendar; lawful synchronized bid/ask/size and any depth archive; explicit endpoint quantity, IV/vega/theta units and cadence/clock evidence; matched OI baseline semantics; actual broker-plan/effective-date fees and measured friction; publisher/source qualification, account entitlement and storage/retention rights. Current declarations and references do not establish these facts. No historical option P&L or empirical B/R comparison began.

The first checkpoint deliberately leaves future same-contract trigger revalidation, NO_FILL on missing future quotes, actual ask-side entry/later bid-side exits, underlying invalidation, premium gaps, time-policy execution, ledger recovery and portfolio/account integration to a later separately approved Main-owned lifecycle checkpoint. The manifest and DTO state those dependencies; this module cannot execute them. Prospective capture also needs separate consent and rights.

Recommended next task after owner review: Main/owner agreement on a read-only exact quote/metadata fixture contract and source-capability matrix, followed by an authorized small sample proving source timestamps, units, tick/lot/listing and fee provenance. Then synchronize a typed descriptive adapter with Main without creating a second prospective-admission path. Keep all features default OFF. **Stop here for owner review; no push, merge, activation or next checkpoint.**
