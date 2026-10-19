# TradePulse AI capability and completion assessment

Phase 5A/5B audit date: 2026-10-18. Scope: the current workspace, including its Python modules,
`public/index.html`, tests and retained phase reports. This is a product-scope audit,
not a certification of broker access, strategy profitability or production readiness.
No credentials were inspected for this assessment and no broker requests were made.

## Evidence and status rules

- `VERIFIED`: the precisely stated software behavior has implementation and passing
  deterministic regression coverage in this mission. It does not establish live access.
- `IMPLEMENTED_UNVERIFIED`: code exists, but the required meaningful test or operational
  evidence for the stated capability is absent.
- `PARTIAL`: a useful subset exists; material functionality or acceptance evidence is missing.
- `MISSING`: no implementation was found for the stated capability in the inspected tree.
- `BLOCKED_BY_EXTERNAL_DEPENDENCY`: further acceptance requires separately authorized
  provider access, trustworthy source artifacts or other evidence unavailable here.
  Missing local implementation is listed separately; external dependencies do not excuse it.

Source and test names below are evidence locators. Test presence alone is not a test
result. The lead engineering report supplies this mission's fresh execution results;
earlier reports' counts are historical. See the [Phase 5A closeout and Phase 5B engineering evidence](TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md),
the retained [Phase 4 engineering evidence](TRADEPULSE_PHASE4_ENGINEERING_REPORT.md)
and [market-data acceptance matrix](TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md).
The preceding [broker recovery report](BROKER_RECOVERY_ENGINEERING_REPORT.md) remains
historical context. The source inventory includes application modules, `test_bot.py`,
independent unittest modules, public assets, configuration templates and Markdown
reports. No CI workflow, dependency lock, deployment manifest or backup/restore runner
was found in the inspected tree. The engineering report lists this mission's files,
fresh commands, actual counts, warning inventory and configuration-only outcomes.

The supplied account of the earlier Upstox diagnostic establishes a reported HTTP 403
and unsuccessful quote check. It does not establish its provider/account cause. No
successful real-provider quote/candle evidence was supplied to this audit. An
authenticated market-data response, valid quote, usable completed candles, broker
account verification and historical replay authorization are separate claims.

## Weighted product milestones

Each row defines one milestone of the agreed feature scope. The status covers the
whole row; narrower verified software behaviors are detailed afterward. I and R are
implementation and verified-readiness scores, respectively.

| ID / capability | Weight | Implementation status | Verification status | I | R | Source and test evidence | Dependencies, blocker and next action |
| --- | ---: | --- | --- | ---: | ---: | --- | --- |
| M01 Architecture and configuration | 8% | PARTIAL | PARTIAL | 75 | 50 | `config.py:BotConfig.validate`, `_load_dotenv`, `safe_dict`; `brokers.py:MultiBrokerScanner.get_active_adapter`; `TestConfigurationPreflight`; Phase 1A configuration tests | Explicit provider selection and safe flags exist; process/CWD configuration semantics are tested. Freeze a supported runtime/configuration profile and complete release configuration evidence; retain dry run and disabled scheduler. |
| M02 Broker authentication and quote access | 12% | PARTIAL | BLOCKED_BY_EXTERNAL_DEPENDENCY | 75 | 25 | `UpstoxV2Adapter._request_json/get_quote/is_authentication_verified`; `AngelOneSmartAPIAdapter.authenticate/_request_json/get_quotes`; `TestUpstoxReadOnlyReadiness`, `TestUpstoxHTTPErrorDetails`; Phase 2A/2C broker tests | Safe request/error/state handling has offline evidence. Fresh successful authorized responses for the exact provider/instrument are absent. Obtain one separately authorized cash-data acceptance; diagnose a rejection only from sanitized provider evidence. |
| M03 Candle ingestion and validation | 12% | PARTIAL | PARTIAL | 75 | 50 | `brokers.py:assess_live_candle_batch/enforce_live_candle_batch`; adapter `get_intraday_candles`; `MultiBrokerScanner.fetch_candles`; `scanner_engine.py:_assess_scan_candles/_require_current_scan_data`; `TestMarketDataFreshness` | Extensive invalidity/freshness tests support the gate. Real response timestamp conventions, coverage, publication delay and deployed endpoint availability still require scoped acceptance. Explicit calendar configuration does not discover exchange holidays/special sessions. |
| M04 Instrument identity and authoritative provenance | 10% | PARTIAL | PARTIAL | 75 | 25 | `instrument_identity.py:spot_identity/check_echo/bind_candles/option_contract/dated_identity`; `instrument_archive.py:prepare_archive/resolve_archives`; `source_qualification.py:assess_source_evidence`; identity/archive/source/official-feasibility test classes | Pinned mappings, exact identities, retained bytes and tamper rejection exist. Checked-in mappings are not current authoritative confirmation; request-bound bare candles lack independent response echo. No source-authenticity/effective-date verifier authorizes historical archives. Establish a supportable evidence acquisition/verifier design before LIVE replay. |
| M05 Options and F&O data coverage | 10% | PARTIAL | BLOCKED_BY_EXTERNAL_DEPENDENCY | 25 | 0 | `config.py:fo_indices/equity_watchlist`; Angel master parser/resolver, `get_option_chain/get_option_greeks/get_option_apex_readiness`; Dhan/Upstox chain readers; `scanner_engine.py:run_single_scan`; `test_live_index_spot_cannot_emit_futures_proposal`, `test_dhan_chain_cannot_emit_option_signal_without_master_resolver` | NIFTY/BANKNIFTY spot and analytical chain code are useful subsets. Full current NSE stock F&O universe, futures contract candles and general provider contract/lot mapping are absent. Angel option proposals require exact supported master contracts and prior OI evidence; no live F&O acceptance exists. Deliver contract/universe ingestion and separate per-instrument acceptance. |
| M06 Scanner and signal generation | 12% | PARTIAL | PARTIAL | 75 | 50 | `IntradayBotEngine.run_single_scan/_compute_universe_breadth`; five `strategies.py:evaluate_*` functions; `compute_setup_quality_score`; Phase 1B/1C strategy tests, freshness/identity scanner-gating tests | Completed-bar evaluation, explanations, invalidation and quality breakdowns exist. Whole-watchlist real-data coverage is unverified; cross-universe ranking and a general liquidity model are incomplete. Validate a bounded cash scan after provider acceptance, then add explicit ranking semantics and tests. |
| M07 Risk controls and accounting | 10% | PARTIAL | PARTIAL | 75 | 50 | `strategies.py:size_position`; `backtest_engine.py:IndianCostModel`; `paper_portfolio.py:enter/_snapshot/_reconciliation`; sizing and Phase 5A/5B tests | Explicit cash paper accounts now share capital, entry-notional exposure and daily realized/unrealized loss controls across strategies, with transactional reservations. Ordinary scans remain candidate-only unless a paper account is explicitly supplied. Derivative/margin and cross-account portfolio control, liquidity assumptions and operational acceptance remain incomplete. Costs/stop estimates are not guaranteed fills or maximum losses. |
| M08 Historical backtesting and reproducible research | 10% | PARTIAL | BLOCKED_BY_EXTERNAL_DEPENDENCY | 50 | 25 | `historical_data.py:validate_and_prepare_historical_dataset/get_point_in_time_candle_slice`; `backtest_engine.py:run_backtest/split_sessions_chronologically`; `readiness_policy.py:execution_gate/historical_coverage`; Phase 3A/3B/3B.1A/3B.1B and official-source tests | Mechanics are verified on fixtures; LIVE historical identity/source qualification remains blocked. Split helper is not automatic experiment orchestration; explicit dates constrain evaluation, but period labels alone do not select disjoint ranges. Reads above the 10,000-row replay cap are blocked. Obtain qualified data, enforce study splits and implement pagination; Strategy 3 needs a separate contract execution engine. |
| M09 Paper trading and persistence | 6% | PARTIAL | PARTIAL | 50 | 50 | `paper_portfolio.py:PaperAccountConfig/PaperPortfolio`; `forward_paper.py:ForwardPaperCoordinator`; `run_single_scan(paper_portfolio=...)`; existing store tables/transactions; Phase 5A/5B concurrency, failure, accounting and restart tests | Durable cash-only simulated entries, marks/full exits, candidate/risk linkage, EOD handling and reconciliation now run through the real scanner boundary. Current-provider operational evidence, derivative paper execution, partial fills/adjustments, dedicated EOD reporting and large-ledger/soak/recovery acceptance remain missing. Do not enable services or claim live executions. |
| M10 Telegram reporting and dashboard/API | 4% | PARTIAL | PARTIAL | 50 | 50 | `TelegramSignalDispatcher.format_signal_html/send_signal`; `server.py:DashboardRequestHandler/create_http_server`; `public/index.html:runBacktestSimulation`; Phase 1D/1E/1F HTTP/security tests and Telegram state-isolation tests | Dry-run formatting/dedup and local API workflows have offline evidence. Dashboard hypothetical curves do not execute the backtest engine. Dedicated EOD performance reporting and empirical calibration are absent; external asset dependencies need deployment review. Keep live Telegram off; connect real persisted results only with truthful labels. |
| M11 Scheduling and operational resilience | 3% | PARTIAL | PARTIAL | 75 | 50 | `MarketScanScheduler.is_market_session_open/run_scheduled_cycle/start/stop`; scanner lock/error handling; `test_p1d_scan_overlap_prevention`, `test_p1d_scheduler_session_boundaries_weekends_holidays_and_lifecycle`, Phase 1F concurrent API tests | Session/overlap/lifecycle behavior is tested in fixtures; production scheduler was not enabled. No sustained provider-outage/rate-limit/long-running recovery drill is evidenced. Run bounded offline fault-injection/soak scenarios before separately authorizing operation. |
| M12 Release, deployment, monitoring and recovery | 3% | PARTIAL | IMPLEMENTED_UNVERIFIED | 25 | 0 | Localhost defaults in `server.py:run_server`; health/status paths, SQLite cleanup and Markdown commands; no release automation/backup runner in initial tree | A runnable local application and reports exist. Reproducible installation, supported-version matrix, deployment access controls, centralized alerts, backup/restore verification and rollback drills are not delivered. Build a local release package and prove recovery without changing the current safety posture. |

## Progress calculation and counting

The weights above sum to 100. The rubric is deliberately coarse and evidence-based:

| Score | Implementation meaning | Verified-readiness meaning |
| ---: | --- | --- |
| 0 | No useful implementation for the agreed scope | No applicable verification of the usable scope, or its necessary provider/data evidence is wholly absent |
| 25 | A narrow subset, structural support or prototype exists | Source inspection and narrowly scoped tests support only a limited subset; decisive evidence is missing |
| 50 | Core mechanics exist with major functional gaps | Meaningful deterministic/integration tests pass; broader functional or operational evidence remains missing |
| 75 | Most core mechanics exist with tested behavior; scoped gaps remain | Applicable offline evidence and scoped operational acceptance exist; final breadth/recovery evidence remains |
| 100 | The entire row's agreed functionality is implemented and reviewed | All row-specific tests and necessary real operational evidence are accepted, repeatable and current |

`weighted progress = sum(weight * score / 100)`.

| ID | Weight | I points | R points |
| --- | ---: | ---: | ---: |
| M01 | 8 | 6.00 | 4.00 |
| M02 | 12 | 9.00 | 3.00 |
| M03 | 12 | 9.00 | 6.00 |
| M04 | 10 | 7.50 | 2.50 |
| M05 | 10 | 2.50 | 0.00 |
| M06 | 12 | 9.00 | 6.00 |
| M07 | 10 | 7.50 | 5.00 |
| M08 | 10 | 5.00 | 2.50 |
| M09 | 6 | 3.00 | 3.00 |
| M10 | 4 | 2.00 | 2.00 |
| M11 | 3 | 2.25 | 1.50 |
| M12 | 3 | 0.75 | 0.00 |
| Total | 100 | **63.50%** | **35.50%** |

Phase 4's retained assessment was 62% implementation / 34% verified readiness.
Only M09 changes in Phase 5A/5B: I=25 to 50 and R=25 to 50. The implemented durable
cash lifecycle and real scanner-to-ledger/concurrency/recovery tests satisfy the
existing 50-point core-mechanics/integration rubric. Its 6% weight adds 1.5 points
to each total. This change reflects delivered behavior, not a larger test count.
All other scores remain unchanged: no current authoritative derivative universe,
real broker acceptance, archive authenticator or release/recovery process was
delivered. No milestone is promoted to operational acceptance.

These percentages are audit estimates of this explicit scope, not measured probabilities,
profitability claims or guarantees of production readiness. They are not interchangeable.
Additional mocked tests can improve confidence in a particular control without removing
the external acceptance limitation or automatically changing these coarse scores.

Counting uses exactly M01-M12, not test classes, old phase reports or workstreams:
**0 of 12 complete; 12 remain unaccepted as full product milestones.** All 12 have some
implementation, and 10 have implementation scores of at least 50. A milestone counts
complete only at I=100 and R=100; a successful engineering patch is not completion of
an entire product milestone. Use the same denominator in the roadmap and final report.

## Product-specific coverage and important distinctions

| Capability | Classification | Evidence and practical limit |
| --- | --- | --- |
| NIFTY and BANKNIFTY mapping | PARTIAL | `BotConfig.fo_indices`, `spot_identity`, `test_exact_index_mappings_and_swapped_tokens_all_providers` pin exact checked-in spot mappings. No current broker/official-master observation was made here. |
| NSE equity and full stock F&O universe | PARTIAL | Default `equity_watchlist` contains 15 cash-equity metadata records. It is neither an authoritative current F&O membership feed nor a stock-futures/options contract universe. |
| EMA/RSI/ATR/VWAP/Supertrend calculations and bidirectional evaluators | VERIFIED | `strategies.py:compute_ema/compute_rsi/compute_atr/compute_session_vwap/compute_supertrend`; Phase 1A/1C tests check mechanics and expected fixture signals. Statistical strategy effectiveness remains unverified. |
| BOS, FVG and order-block mitigation | VERIFIED | `evaluate_order_block_fvg` implements its explicit displacement/retest rules; `test_p1c_order_block_mitigation_first_retest_and_invalidation` and state-isolation tests cover the implemented pattern. This is not validation of every discretionary market-structure concept. |
| General liquidity pools/sweeps | MISSING | No separate liquidity-pool/sweep detector was found. Relative volume and pattern displacement do not establish that capability. |
| Candidate quality/explanations | VERIFIED | `compute_setup_quality_score`, `TradeSignal.rationale/score_breakdown/invalidation_level`, and quality/breadth fixture tests support a deterministic setup score. It is not a calibrated win probability. |
| Cross-universe candidate ranking | PARTIAL | Quality scores are available, but the inspected scan loop appends evaluator results without an explicit portfolio/candidate ranking stage. Persisted-history ordering is not a quality-ranking policy. |
| PCR/OI/Greeks and prior-closing-baseline analytics | PARTIAL | Angel chain/Greeks, prior-baseline validation/restoration and Option Apex readiness are implemented and fixture-tested. Provider support differs; real contract, lot, expiry, snapshot and prior-closing-baseline evidence remains separate. |
| Live futures proposals from spot candles | VERIFIED | Explicitly rejected by `run_single_scan` and `test_live_index_spot_cannot_emit_futures_proposal`; implementing a safe block is not implementing futures support. |
| Historical Strategy 3 fills | MISSING | `readiness_policy.execution_gate` and `_ensure_historical_strategy_supported` reject `HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED` before replay. A chain plus underlying bars does not supply exact option-contract fills. |
| Live historical source qualification | BLOCKED_BY_EXTERNAL_DEPENDENCY | `assess_source_evidence` always reports historical eligibility false because independent publisher/authenticity/effective-date evidence is not established; a supported verifier is also unimplemented. Hashes, URL strings and caller-supplied flags cannot satisfy it. |
| Replay mechanics, stops/targets, entry gaps and EOD square-off | VERIFIED | Phase 3B, 3B.1A and sizing tests cover next-open fills, conservative collisions, gaps, costs and replay exits. This evidence comes from fixtures, not a real historical performance study. |
| Durable cash forward paper portfolio | VERIFIED | Explicit immutable accounts, candidate decisions, atomic reservations, simulated fills/full exits/marks and ledger reconciliation are demonstrated offline through the actual scanner path. See the paper report. Real operational acceptance and derivative execution are separate and absent. |
| Dedicated EOD performance report | MISSING | EOD simulated exits and read-only account/day accounting exist; a published EOD reconciliation/export workflow is not delivered. OI baseline storage and replay square-off remain separate capabilities. |
| Live Telegram delivery and deployment recovery | IMPLEMENTED_UNVERIFIED | Delivery code exists; only dry-run/mocked behavior is accepted here. No live delivery or deployment/recovery drill was performed. |

## Scanner path and evidence boundaries

This trace follows the existing scanner pipeline; a quote diagnostic and a scanner
candle batch serve different purposes. Scanner evaluation consumes validated candles;
a successful standalone quote does not satisfy that candle gate. All Phase 4 wire
fixtures and strategy scenarios are **offline simulation**. Exercising a live-provider
adapter with mocked transport does not establish live broker acceptance, even when
the normalized fixture carries `data_mode="LIVE"` to exercise the stricter code path.

| Stage / capability | Classification | Current source path and evidence | Remaining limit |
| --- | --- | --- | --- |
| Explicit provider and acquisition failure | VERIFIED | `MultiBrokerScanner.get_active_adapter/fetch_candles`; `IntradayBotEngine.run_single_scan` clears earlier per-instrument coverage before a new live scan. Provider failure is raised; the live branch does not substitute `SimulatedNSEAdapter`. Phase 1A provider-failure tests, `TestMarketDataFreshness` and shared contract tests cover rejection. | A configured provider and successful mocked transport do not establish a real authorized response or real-world availability. |
| Request/instrument binding | VERIFIED | `validate_symbol_meta`, Angel `resolve_instrument`, `spot_identity/check_echo/bind_candles` run before evaluation. The manager and scanner recheck identity when a reader is replaced. `TestInstrumentIdentity` and shared contract tests cover provider/exchange/token conflicts. | Pinned mappings and request-bound bare bars are narrower evidence than a current independently echoed master identity. `REQUEST_BOUND_NO_ECHO` remains explicit. Futures need their own exact contract resolver/candles. |
| Time, order, OHLCV and session freshness | VERIFIED | Adapter parsing and `assess_live_candle_batch` reject invalid/missing/naive/future timestamps, malformed OHLCV, duplicate/out-of-order/off-grid/gapped rows and synthetic/cross-provider contamination. `_assess_scan_candles/_require_current_scan_data` recheck coverage after acquisition and before storage/dispatch. `TestMarketDataFreshness` includes slow evaluator expiry. | Candle timestamp is the provider's bar start; bar end is derived from start plus interval/session close. Neither a local check time nor a derived bar end is an independently supplied provider observation time. Calendar behavior uses weekdays plus explicitly configured holidays/session times. |
| Completed bars and strategy-required input | VERIFIED | `filter_completed_candles` runs inside the existing evaluators. Insufficient completed warmup returns no candidate. Phase 1B/1C and Phase 4 strategy-required-data tests distinguish completion/freshness from the actual opening bars needed by ORB. | A small fresh diagnostic sample does not establish every strategy's warmup, full-session VWAP coverage or whole-watchlist availability. |
| Actual deterministic strategy decisions | VERIFIED | `evaluate_order_block_fvg`, `evaluate_vwap_pullback`, `evaluate_orb_breakout`, `evaluate_supertrend_pullback` retain their existing mechanics; Option Apex separately requires its chain/master/baseline inputs. Phase 4 end-to-end tests exercise real evaluators through the adapter/scanner path rather than injecting a ready-made signal. | Rule mechanics on synthetic data establish neither statistical effectiveness nor accepted live signals. Cross-universe ranking and broad derivative execution remain incomplete. |
| Per-trade sizing, stops and invalidation | PARTIAL | Evaluators and scanner retain their sizing/invalidation boundary; the explicit cash paper account additionally reserves shared capital and enforces exposure/count/daily realized+unrealized loss. Sizing and Phase 5A/5B tests check these mechanics. | Normal candidate scans do not reserve capital automatically; derivative/cross-account risk and operational acceptance remain incomplete. A modeled stop is not a guarantee against gap loss. |
| Deduplication and order-block state | VERIFIED | `signal_state_identity/compute_signal_dedup_key`, scoped mitigated-zone storage and Telegram cache separate provider/mode/context/instrument/interval/direction/candle. Scan locking prevents overlapping evaluation. `TestStateIsolation`, Phase 1D/1F overlap tests and Phase 4 repeated-scan checks exercise these boundaries. | Persistence deduplication is not a durable Telegram delivery outbox. A stored candidate whose send fails needs an explicit retry/delivery-state design before production messaging. |
| Persistence and dry-run reporting | VERIFIED | `validate_signal_identity` precedes `SQLitePersistenceStore.save_signal`; `TelegramSignalDispatcher.send_signal` returns preview output when dry run is true. Phase 4 end-to-end fixtures persist real evaluator candidates and exercise this existing dry-run branch with external transport forbidden. | No live Telegram delivery was tested or authorized. Formatter confidence/benchmark language and its fixed `1% Risk` label require truthful reporting work; quality score is not a calibrated probability. |
| Source evidence and research execution | BLOCKED_BY_EXTERNAL_DEPENDENCY | `assess_source_evidence` reports `historical_eligibility.allowed=False`; archive resolution enforces it before LIVE replay. `execution_gate`, `_ensure_historical_strategy_supported` and source/archive tests reject missing acceptance, invalid history and historical Strategy 3. | Source authenticator/effective-date verifier implementation and independent artifacts are both absent. An accepted cash diagnostic cannot fill either gap or issue a replay receipt. |

The scanner currently treats a live candle failure in any required configured
instrument as a failed scan, rather than a partially eligible universe. Health evidence
is scoped by provider and expires with the clock; a successful earlier scan is not
authorization to reuse candles after an outage. Phase 4 replaces the latest summary
on acquisition failure and requires a verified connection as well as fresh candle
evidence for the top-level signals-allowed status. The independent failed-read
regression covers both providers even when retained candle evidence is still fresh.
A valid candidate may be stored before
a later freshness check fails, so persisted history, latest scan status and actual
dispatch results must be interpreted together; the scanner is not an atomic
portfolio/delivery transaction.

## Remaining acceptance evidence

Phase 4 evidence locators are
`test_phase4_market_data.TestPhase4BrokerAcceptance`,
`test_phase4_market_data.TestPhase4InstrumentScope`,
`test_phase4_e2e.TestPhase4OfflineEndToEnd` and
`test_phase4_strategy.TestPhase4StrategyRequiredData`. Their relevant scopes supplement
M02-M07 and M09-M11; they do not replace the M08 source/replay requirements or M12
release/recovery evidence. The end-to-end candidate uses the real order-block
evaluator and scanner sizing, validates the actual candle reference, persists through
SQLite, and renders through the existing Telegram dry-run dispatcher. It also tests
scoped retries/restart, provider isolation, stop invalidation and rejected risk budgets.

The Phase 4 engineering report gives the fresh baseline and integrated results for
the existing broker, identity, freshness, provenance, replay-gate and scanner-safety
suites, plus new shared provider/candidate/mandatory-input regressions. They establish
no operational provider success and therefore do not remove M02/M05 external
dependencies or increase the coarse readiness scores automatically. The companion
acceptance matrix separates quote, completed-candle, index, futures, options and
historical scope, with external prerequisites for each.

1. One explicitly authorized provider/instrument quote and completed-candle check with
   sanitized output, actual process exit, observation timestamps, identity, interval,
   coverage and freshness. A 403 alone does not authorize provider switching or explain its cause.
2. Independent acceptance of additional cash/index instruments and the intended universe.
   A RELIANCE cash success cannot establish NIFTY/BANKNIFTY derivatives readiness.
3. Actual contract master, expiry/strike/lot mapping and contract-candle evidence for
   each supported derivative scope; prior-session OI evidence for Option Apex.
4. A justified historical source-evidence verifier and authoritative date coverage,
   followed by complete persisted datasets, enforced study splits and qualified replay.
   Upstox market-data diagnostics never issue the Angel-specific Phase 2C receipt.
5. Broader paper-portfolio operational/multi-session acceptance, dedicated EOD
   reconciliation/export and repeatable release/backup recovery. The cash-only
   local accounting and restart baseline is now implemented and tested offline.

No item in this matrix permits order placement, enables the scheduler, authorizes live
Telegram delivery, issues a readiness receipt or unblocks LIVE historical replay.

## Phase 5A/5B acceptance addendum

The [closeout report](TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md) records fresh counts,
status, external dependency and exact next action for each acceptance item.
The [contract report](TRADEPULSE_FO_CONTRACT_COVERAGE.md) separates six normalized
declaration types from the existing provider-specific execution/analytics support.
The [paper report](TRADEPULSE_PAPER_PORTFOLIO_REPORT.md) documents the explicit
completed-observation close fill policy and remaining limits. The provenance design
retains the absent-verifier block. All seven reports describe the same checkout;
earlier phase counts remain historical evidence rather than current totals.
