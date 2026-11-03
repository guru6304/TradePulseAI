# Agent 2 — Part A checkpoint 1 — 3 November 2026 IST

Scope: isolated synthetic volume research on `feature/new-strategies`, starting at `627b61c17ca35e91838ef3d513fdd424509bb3fb`. This checkpoint implements the approved B/R math and a conservative offline state harness. Both strategies remain default OFF. No production strategy is registered, no operational account or database is changed, and Options Contract Intelligence has not begun.

The commit containing this document is the checkpoint commit; its exact SHA is supplied in the owner handoff and Git history. No push or merge is included.

## Authority and audited interfaces

The complete final specification is `C:\Users\91810\TradePulseAI-References\Stage1-Strategies\TradePulse_AI_Stage1_Final_Algorithm_Research_Spec_2026-10-31.md`, document `TP-STAGE1-QUANT-DECISION-SPEC-2026-10-31-V1.0`, SHA-256 `9d6a892092d780afbcb45673cae083df242528eda8b87f8bfdd1403fd062944d`. Its corrected equations win over the GPT/Gemini BRDs. The full independent dual audit and relevant original BRD calculations/cards/pseudocode were reviewed as background.

The published [strategy contract](../agent-contracts/TP_STRATEGY_INTEGRATION_CONTRACT_V1.md), [UI/API contract](../agent-contracts/TP_UI_API_CONTRACT_V1.md), and current H1 entry of [master status](../project/TRADEPULSE_MASTER_STATUS.md) were inspected before implementation. The actual scanner, five evaluators, rank/history, source/identity/time validators, research protocol, paper triggers/coordinator and storage schemas were audited read-only. See the [source audit](TP_VOLUME_INTERFACE_AUDIT_20261102.md) for exact references and overlap findings.

Current ORB/VWAP use prior adjacent-bar mean volume; B/R use prior-session same-slot median volume. Existing quality already rewards participation. There is no new ranking factor or independent replacement ranker. The package lives below the root so its addition does not change `candle_lineage.code_fingerprint()` merely by adding unused non-test root modules.

## Exact files and implementation status

All changes are additive:

| File | Implemented behavior |
|---|---|
| [.gitattributes](../../.gitattributes) | Scoped LF rules for new research sources and exact-byte receipt/log retention, preserving evidence through Windows checkouts; existing application paths unaffected. |
| [volume_research/__init__.py](../../volume_research/__init__.py) | `BREAKOUT_ENABLED=False`, `RETEST_ENABLED=False`; explicit Boolean opt-in permits pure calculations only. |
| [volume_research/primitives.py](../../volume_research/primitives.py) | Frozen bar/session/identity/membership/action/profile/context DTOs, Decimal and tick validation, closed/available source clocks, RVOL20/matched60, ATR14, CLV, optional aligned sector residual. |
| [volume_research/breakout.py](../../volume_research/breakout.py) | Independent `TP-VOL-BREAKOUT-1.0` detector, immutable pending candidate or explicit disabled/rejected/unavailable reason. |
| [volume_research/retest.py](../../volume_research/retest.py) | Independent `TP-VOL-RETEST-1.0` impulse, four-bar actual retest lifecycle and separate three-bar pending entry, stable state/receipt identity. |
| [volume_research/models.py](../../volume_research/models.py) | Immutable cost/liquidity/exposure declarations, proposed candidate receipt, future entry and exit steps, actual-assumed-fill economics, gap/band/capital/ambiguity controls. |
| [volume_research/verify.py](../../volume_research/verify.py) | Guarded credential-free targeted baseline/new-suite runner, complete test IDs, source/log hashes and receipt validation. No application startup. |
| [test_volume_primitives.py](../../test_volume_primitives.py) | 28 authored arithmetic/admission tests and explicitly synthetic fixtures. |
| [test_volume_execution.py](../../test_volume_execution.py) | 27 B/shared-execution tests including long/short, availability, expiry, risk/cost/tick boundaries, ambiguity and time exits. |
| [test_volume_retest.py](../../test_volume_retest.py) | 18 R tests including B/R exclusivity and overlap, actual retest geometry, 4/3 windows, provenance and absence of optional hard vetoes. |
| [TP_VOLUME_INTERFACE_AUDIT_20261102.md](TP_VOLUME_INTERFACE_AUDIT_20261102.md) | Actual interface/formula/ownership audit and proposed handoff. |
| [TP_VOLUME_EXPERIMENT_MANIFEST_V1.json](TP_VOLUME_EXPERIMENT_MANIFEST_V1.json) | Predeclared development windows/thresholds/ablations; no executed empirical study or selected holdout. |
| This checkpoint document | Implementation, formulas, evidence, missing dependencies and review stop. |
| [Execution receipt](../evidence/volume_checkpoint_20261103_01.json) / [log](../evidence/volume_checkpoint_20261103_01.txt) | Immutable final source-bound targeted offline verification. |

The five existing strategies, scanner, production ranking, paper safety services, storage schemas, server and frontend are unchanged. No broker requests, real orders, Telegram sends, private `.env` reads, data acquisition or operational DB modifications are part of the checkpoint. Baseline tests use authored provider-shaped wire fixtures and disposable stores; logs labelled LIVE or Angel One are synthetic adapter fixtures.

## Approved formulas implemented

| Final spec | Implementation and exact pilot convention |
|---|---|
| §4 completed observations | Offset-aware start/end/source/received/finalized/available times; decision >= all relevant times; normal cash 75 five-minute slots; no incomplete candle; explicit same-session decision, identity/source/grid/geometry/tick validation. Missing calendar and unsupported special session stay unavailable. |
| §4 point-in-time universe/actions | Effective-dated ordinary EQ NIFTY200 membership and identity must cover the event and be available at decision. Caller declarations do not authenticate membership or data rights. Known, effective share multipliers adjust prior volume into current share units; no future-effective adjustment. |
| §4.1 RVOL | `RVOL_N=V_current/median(prior N eligible same-slot session volumes)`. Exactly the most recent N declared eligible sessions must be present; no skipping missing sessions or replacing missing with zero. N20 baseline; positive denominator. All N5/10/15/20/30/50/60 comparisons require matched60 valid warmup. Threshold 1.8 is unvalidated; 1.5/1.8/2.2 are declared development-only comparisons. |
| §4.1 ATR/CLV | `TR=max(H-L,abs(H-prevC),abs(L-prevC))`; first of >=15 supplied prior bars supplies previous close, seed mean of first14 TR, then Wilder `(13*ATR+TR)/14`; current excluded, overnight gaps INCLUDED. Prior OHLC become comparable only internally using already-effective actions. `CLV=(C-L)/(H-L)` in [0,1], zero range unavailable. |
| §4.1 sector | `ln(C_stock(t)/C_stock(t-3))-ln(C_sector(t)/C_sector(t-3))`, aligned 15m endpoints and identities, available as of decision. Missing sector is soft and does not veto B/R. |
| §5 B setup | Four PRIOR-bar `H4/L4`; long `C>=H4+tick`, `C>O`, `CLV>=.70`, RVOL20>=1.8; short `C<=L4-tick`, `C<O`, CLV<=.30, RVOL20>=1.8. Decisions 09:40–14:40. |
| §5 B geometry | Long `E0=ceil_tick(H_setup+tick)`, `S0=floor_tick(min(L_setup,L_prev1,L_prev2)-tick)`; short mirrored low/max-high geometry. Next TWO eligible future bars only. |
| §6 R impulse | Six PRIOR-bar `H6/L6`, directed close/CLV/RVOL as approved, decisions 09:40–14:20. Freeze K=H6 long/L6 short and `b=max(2*tick,.20*ATR_prior)`. |
| §6 R retest | Next FOUR eligible completed bars; long `K-b<=L_retest<=K+b`, `C_retest>=K`; short mirrored high touch and close<=K. Directional close outside K±b invalidates. Last retest setup 14:40. No mandatory volume contraction, sector, robust-Z or stop/ATR gate. |
| §6 R entry | Long `E0=ceil_tick(H_retest+tick)`, `S0=floor_tick(min(L_impulse,L_retest)-tick)`; short mirrored. Next THREE strictly later eligible bars only; impulse/retest candles cannot fill. |
| §§5–6,9 fill/economics | Full interval starts at/after candidate decision availability; later monitoring latency does not move that frozen boundary. Long fill=`ceil_tick(max(E0,future_open)+impact)`, short=`floor_tick(min(E0,future_open)-impact)`. Opening chase>.15 prior ATR cancels. Structural stop frozen. Long target=`ceil_tick(entry+1.8*(entry-stop))`, short mirrored floor. Known band, current liquid/tradable evidence, unchanged quantity, capital/risk/exposure and costs revalidated. |
| §9 net RR | For declared integer quantity, `(gross executable target gain-fees_win)/(gross executable stop loss+fees_loss) >=1.25`. Both projected exits include adverse impact AND tick rounding, exactly as exit steps do; entry impact is already embedded once. Costs are versioned effective-dated caller estimates, not an authoritative tariff. |
| §§5–6,9 exits | No new observed fill after14:45. Exit by next observed stop/target, 12 POST-fill bars or15:15. Entry-bar stop OR target touch has unknown path: `NO_FILL/AMBIGUOUS_OHLC` abstention. Later stop+target touch is adverse stop-first. Stops gap adversely to open; target gaps do not improve the assumed fill. No trailing. |
| §8 exposure boundary | Explicit research `MarketEvidence.exposure` rejects duplicate/opposing reservations. This is a caller assertion, not an account service. Main's atomic H1 exposure gate remains authoritative and unchanged. |

The Stage1 synthetic B vector reproduces trigger100.85, stop99.95 and post-fill target102.50. Mirrored short and impact-adjusted targets are tested. The corrected rounded-cost regression rejects a trade whose unrounded net RR would incorrectly exceed1.25.

## Evidence and practical limits

The final canonical command, from `indian_fo_signal_bot_v1`:

```powershell
python -B -m volume_research.verify --receipt docs/evidence/volume_checkpoint_20261103_01.json
python -B -m volume_research.verify --validate docs/evidence/volume_checkpoint_20261103_01.json
```

The runner sets `ACTIVE_BROKER=paper_sim`, `TELEGRAM_DRY_RUN=true`, `ENABLE_BACKGROUND_SCHEDULER=false`, `PYTHONDONTWRITEBYTECODE=1`; installs the established outbound socket/DNS guard before importing the credential-free `test_bot` bootstrap; uses disposable fixture stores. It hashes all existing verifier-covered sources plus the research package and experiment manifest before/after, records every expected/executed/passed ID, and rejects skips/unraisable errors or changed sources. Receipt validation reruns no tests. Use a fresh receipt suffix on any future execution.

The canonical guarded run passed **173/173**, failures0, errors0, skips0, expected/unexpected failures0, unraisable errors0; process exit0. Unittest execution took **39.096s**, complete guarded run/receipt preparation **41.016s**, using Python3.12.4. Before/after source hashes match. The validation command passed and confirmed current source and log hashes against all173 expected/executed/passed IDs. Production/core diff against627b61c is empty; whitespace validation passes.

| New tests | Passed | Existing selected baseline | Passed |
|---|---:|---|---:|
| `test_volume_primitives` | 28 | `test_phase4_strategy` | 4 |
| `test_volume_execution` | 27 | `test_astra_research` | 10 |
| `test_volume_retest` | 18 | `test_market_data_contract` | 22 |
| | | `test_cash_lineage` | 27 |
| | | `test_astra_ranking` | 9 |
| | | `test_astra_rank_history` | 18 |
| | | `test_h1_paper_conflicts` | 10 |
| **New total** | **73** | **Baseline total** | **100** |

The separate latest targeted command `python -B -m unittest test_volume_primitives test_volume_execution test_volume_retest -q` also executed **73/73 passed**, failures/errors/skips0. Earlier development R assembly runs encountered the not-yet-created shared `decision_bar` field; that interface was completed and all R tests reran successfully. Those intermediate errors are not acceptance receipts.

This is synthetic G1 evidence and a selected baseline regression, not the historical full1,315-test suite, an empirical G2/G3 replay, live G4 acceptance, latency benchmark or reproducible pinned-environment certification. No source authenticity or trading accuracy is implied by a hash, pass count, declared calendar, membership or cost model.

Explicit conservative restrictions and deferred capabilities:

- A split inside the last-six structural window yields `CORPORATE_ACTION_IN_STRUCTURE_WINDOW`. Comparable ATR and seasonal share units are supported, but raw B/R price structure spanning the action is not inferred.
- Special/irregular sessions do not share normal slot baselines and cannot qualify V1. The calendar is declared input, not an automatically verified exchange calendar.
- Fill bars with zero traded volume, unknown liquidity/rights, missing chronology or uncertain stop/target ordering do not produce assumed fills. Only bar-based approximations exist; no L1 replay is claimed.
- A missing/invalid/halted exit retains an OPEN/UNKNOWN research position with `UNFILLED_EXIT`, null exit price and no settlement. It intentionally fails closed on later missing chronology. Recovery to a later first executable exit requires a separate audited replay/reconciliation policy; this harness does not fabricate that price or assert a complete halt-recovery engine.
- State is immutable and duplicate steps are idempotent when the caller retains the returned state. There is no durable event store or account allocator. Reusing an earlier pre-terminal state would be a caller error; summary `to_dict()` is a proposed receipt, not a complete restart/import schema.
- Caller-supplied market/cost/source declarations are unverified. There is no external freshness/source-clock attestation, provider quote capture, exact current fee service or cross-strategy/account capital synchronization.
- Development ablations, parameter comparison selection, no-time-stop experiment and price-only comparator are declared in the manifest, not executed studies. Baseline detectors implement approved RVOL rules. Turnover, optional robust-Z, fitted rank factors and all Options Contract Intelligence remain deferred.

## Missing data and research dependencies

**Comparable real-data denominator: 0 events.** Empirical B/R overlap with actual ORB/ranking, fill rate, win rate, net expectancy, top-K performance and OOS edge are UNAVAILABLE.

No rights-qualified cash archive was supplied. Next data dependencies are authorized 5m OHLCV and source availability/correction clocks; 60 valid prior sessions; effective-dated NIFTY200 constituents and provider identity; dated action/share/tick/market-band records; complete calendar and separate special-session policy; genuine synchronized liquidity/quote evidence; cash long/short costs and friction; optional dated sector prices/classification. Holdout dates, minimum economic effect and sample-size analysis are intentionally unset. Account access, entitlement, capture/storage rights and any spend remain unverified and separately scoped.

Installed dependency versions in the receipt are observations only. Existing requirements remain unchanged; mismatches to repository pins remain reproducibility dependencies: cryptography50.0.1 versus50.0.2; pycparser2.22 versus3.11; tzdata2024.1 versus2026.5; websockets16.1.1 versus15.0.1. cffi2.1.1 matches. No dependencies were downloaded or changed.

## Contract review and next checkpoint

No existing contract, HTTP field, schema migration or production configuration change is required by this isolated checkpoint. Proposed research DTOs are `tradepulse.volume-research-candidate.v1` and `tradepulse.volume-research-retest.v1`, with decimal strings, explicit unavailable reasons, future policy, source/decision-candle clocks, exact declared instrument identity, config/state IDs, ordinal confidence, and literal `actionable:false`. Options is `NOT_EVALUATED` with null contract.

Before any integration, Main/owner must approve additive strategy IDs/versions and flags, a typed adapter rather than a `TradeSignal` cast, source/freshness/identity admission, duplicate and capital handling through the existing account transaction, exact future trigger policy, retained evidence and UI consumption. The H1 `CONFLICTING_OPEN_POSITION` contract is respected; no alternate account engine is introduced.

Recommended next checkpoint after owner review: a separately authorized, rights-scoped 10-symbol/60+session data-feasibility/replay fixture contract, then actual paired B/R versus existing ORB/current-rank comparison without production registration. Complete unfilled-exit recovery and durable research replay before any lifecycle acceptance claim. Reconcile the proposed adapters with Main first. **Do not begin Part B, push, merge or activate anything until approved.**
