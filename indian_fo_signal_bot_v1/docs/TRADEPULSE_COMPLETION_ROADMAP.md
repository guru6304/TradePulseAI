# TradePulse AI remaining-work roadmap

Phase 4 audit date: 2026-10-18. The current stage is offline integration and market-data
acceptance preparation. Real provider cash-data acceptance is unestablished; LIVE
historical replay and historical Strategy 3 remain blocked. The companion
[capability matrix](TRADEPULSE_CAPABILITY_MATRIX.md) defines the weighted scope and
evidence rules: **62% implementation, 34% verified readiness; 0/12 fully accepted
product milestones, 12 remaining**. These are audit estimates, not forecasts of
profitability or production readiness.

Fresh baseline, fixes, commands, exit codes and warning inventory are recorded in the
[Phase 4 engineering report](TRADEPULSE_PHASE4_ENGINEERING_REPORT.md). The
[market-data acceptance matrix](TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md) separates
provider transport/authentication, quote validity, completed candles, cash/index/F&O
scope and historical provenance. The capability matrix traces the actual
adapter-to-scanner-to-strategy-to-storage/dry-run path. Public API documentation and
mocked responses are not operational acceptance.

The 12 milestones are M01-M12 in that matrix. Work packages below are smaller delivery
units; do not add their count to the milestone denominator. Multiple packages can
advance one milestone, and a cross-cutting package can advance several. No calendar
estimate is asserted because provider/source-evidence lead times and the paper-portfolio
scope are unresolved.

## P0: reliable, validated market data

| Package / milestones | Deliverable and dependency | Regression and acceptance criteria |
| --- | --- | --- |
| P0.1 Scoped broker diagnostics and shared contract (M01-M03) | Offline delivery is the existing Upstox and narrow Angel quote/candle commands, with Phase 4 fixes and shared negative cases described in the engineering report. Adapter parsing stays provider-specific; both use the established identity/time/completion/freshness boundaries. Provider choice stays explicit. | Mock HTTP/auth/rate-limit/schema/body-size/read/close failures; no secret-bearing diagnostics; no trading/profile/funds/positions calls in the narrow commands; invalid/failed quote prevents candle transport; configuration-only path makes no network request, writes no receipt and starts no service. A bar start plus interval may derive a bar end, but cannot invent a provider observation timestamp. |
| P0.2 One authorized cash-data observation (M02-M04) | After separate authorization, run one provider at a time for one supported NSE equity. Retain sanitized structured output plus exit code and exact provider/symbol/interval/date scope. This is an external evidence dependency. | Actual quote identity and observation timestamp pass; completed candles pass OHLCV, ordering, duplicates, interval, coverage and freshness. Authentication evidence is limited to authorized market-data response. Failed calls produce a precise external corrective action without automatic fallback or tight retries. |
| P0.3 Endpoint/master/calendar fit (M03-M05) | Confirm current provider endpoint support and accepted timestamp conventions; obtain a current trustworthy instrument master and accurate session calendar. Separate public documentation from runtime evidence. | Exact token/key/exchange/type mapping, ambiguity/lot/expiry checks, missing or naive timestamps, holidays/special sessions and freshness delay boundaries. Bare candles retain `REQUEST_BOUND_NO_ECHO`; local request time never becomes provider observation time. |
| P0.4 Historical source-evidence design (M04/M08) | Establish whether independently authoritative source attribution, publisher authenticity and historical effective dates can be acquired. Implement only a defensible verifier with retained evidence and clear trust boundary. Depends on actual source artifacts/provider capabilities; no verifier exists today. | Tampered bytes/metadata, forged URLs/flags/hashes, mismatched dates/providers/segments, stale policy and archive pins fail closed. Every provider remains blocked until its separate evidence requirement passes; do not accept a current master as historical coverage. |

P0 exit: one narrowly documented real cash-data path accepted, safe diagnostics and
the shared scanner gate tested, current mapping/calendar prerequisites established,
and historical evidence feasibility explicitly resolved. Cash acceptance alone does
not satisfy P0.4 or release replay.

## P1: scanner and strategy correctness

| Package / milestones | Deliverable and dependency | Regression and acceptance criteria |
| --- | --- | --- |
| P1.0 Offline candidate path and mandatory input (M03/M06/M07/M09-M11) | Phase 4 adds a deterministic adapter/scanner/real-evaluator/store/dry-run harness and targeted mandatory-opening-range regressions. See the engineering report for executed evidence. This is offline simulation and leaves the operational milestone scores unchanged. | Provider-shaped input must pass actual identity, ordering, OHLCV, timestamp, interval, completion and freshness checks; real evaluators produce the candidate; sizing/invalidation/timestamps reconcile; same-candle retries deduplicate. Missing/stale/mismatched/malformed data and provider failure produce no new stored/reported candidate. ORB requires the actual completed 09:15/09:20/09:25 bars rather than the first three returned later bars. Latest failure evidence replaces a previous successful scan summary. |
| P1.1 Bounded cash scanner acceptance (M03/M06/M11) | Extend acceptance to a declared cash universe, preserving shared identity/freshness validation and provider isolation. Depends on P0.2/P0.3; no full-market scan is authorized by this roadmap. Declare the strategy-specific coverage/warmup required, including session-VWAP start coverage rather than inferring it from a small fresh sample. | A failed/stale/invalid instrument cannot produce an eligible signal; slow evaluation rechecks freshness; broker outage produces no simulated fallback; overlap and provider/mode/context dedup remain deterministic. Operational freshness is rechecked for the entire required universe before persistence/dispatch. An earlier successful run remains history and cannot mask the current outage. |
| P1.2 Ranking and communication semantics (M06/M10) | Specify deterministic candidate ranking/tie-breaking and explain score limitations. Review hardcoded benchmark/probability and risk-label wording. Existing quality score is confluence, not empirical win probability. | Equal-score ties and input-order invariance; missing features never fabricate breadth; entry/stop/invalidation/targets and configured risk are reported truthfully. No synthetic or external benchmark is presented as project performance. |
| P1.3 Explicit derivatives scope (M04-M06) | Add supported contract/universe ingestion, exact futures/options IDs, expiry/strike/side/lot mapping and contract candles. Start with an explicitly chosen derivative scope; the 15 cash symbols do not establish a full F&O universe. | Spot cannot authorize futures; stale/expired/ambiguous/mismatched contracts reject; exact lot sizes and price units persist through signals. Upstox/Dhan analytical chains remain unable to authorize Option Apex without a supported contract resolver. |
| P1.4 Strategy model coverage (M06) | Specify which liquidity/structure features are required, then add only missing deterministic rules with fixtures. Keep the five existing evaluators and documented BOS/FVG rule scope explicit. | Bull/bear boundary cases, first retest/mitigation, no forming/future candle use and meaningful invalidation. A market-structure label does not imply statistically effective signals. |

P1 exit: supported universe and strategy behavior are explicitly bounded, invalid data
cannot reach evaluation/persistence/dispatch, and candidate ordering/explanations are
tested. Profitable performance remains a separate research question.

## P2: historical research, backtesting and paper trading

| Package / milestones | Deliverable and dependency | Regression and acceptance criteria |
| --- | --- | --- |
| P2.1 Qualified historical dataset (M04/M08) | Import real supported history only after P0.4. Prove full session coverage, warmup and intended evaluation range; implement replay pagination above the current 10,000-row cap without truncation. | Gaps/missing sessions/duplicates/provider-mode mixing/range changes reject. Pagination has no gaps/duplicates and no limit can silently cut a study short. Per-symbol readiness remains separate from aggregate common-period readiness. |
| P2.2 Enforced chronological experiment protocol (M08) | Turn the existing split helper and explicit date controls into auditable train/validation/out-of-sample study orchestration. Current `period_type` labels alone do not select a split. | Disjoint chronological periods, strict selection and warmup-only earlier data; frozen parameters and dataset/config hashes; repeatable output; no overlap, look-ahead or use of out-of-sample data for fitting. |
| P2.3 Historical Strategy 3 contract execution (M05/M07/M08) | Implement exact historical contract-candle entry/exit fills, chain snapshots at decision time, verified prior-session closing OI, expiry/strike selection, dated lot metadata and premium accounting. Depends on P1.3/P2.1. | Changing only option-contract candles changes fills/P&L; underlying changes cannot substitute premium fills; mismatch/missing contract data rejects. Cost/lot/gap/collision/EOD accounting reconciles. Remove the unconditional block only after this complete contract is accepted. |
| P2.4 Durable forward paper portfolio (M07/M09) | Add an order-free paper fill/position/exit/mark-to-market ledger and shared capital/exposure/daily loss accounting. Reuse sizing and replay cost contracts; keep synthetic data labelled. | Concurrent candidates cannot each reserve the same capital; daily realized/unrealized loss and position limits block later entries; costs book once; restart reconciliation/idempotency and provider/mode/context isolation hold. |
| P2.5 EOD reconciliation and research evidence (M08-M10) | Produce a dedicated report from actual ledger/results, reconcile trade totals/equity/drawdown/costs and missing data, then evaluate frozen strategies on qualified out-of-sample history. | Empty-day/multi-day/report-retry tests; reconciled paper/replay statements; losses and uncertainty retained; no fixture profitability claim. Replay EOD square-off and OI closing-baseline storage are not an EOD performance report. |

P2 exit: reproducible qualified cash research, separately accepted derivative execution
where implemented, and a restart-safe paper ledger. No order-execution capability is
required or authorized.

## P3: reporting, deployment and recovery

| Package / milestones | Deliverable and dependency | Regression and acceptance criteria |
| --- | --- | --- |
| P3.1 Truthful dashboard/reporting and delivery state (M09/M10) | Connect a view to persisted real backtest/paper results; keep hypothetical profiles explicitly separate. Replace fixed benchmark/probability and `1% Risk` wording with truthful semantics/configured values. Specify a durable delivery outbox/retry contract: today a stored signal can suppress a later retry after dispatch failure. Dry-run formatting remains default; live delivery needs separate authorization. | API/UI scope and pagination; XSS/private-file/secret protection; labels distinguish fixture/research/operational evidence. Failed sends do not consume Telegram cache entries; persisted delivery state additionally proves retry/restart idempotency without duplicate successful deliveries or lost alerts. |
| P3.2 Bounded resilience/soak evidence (M11/M12) | Exercise slow providers, rate limiting, timeouts, network failure, SQLite contention and shutdown/restart using offline fault injection before any authorized scheduled use. | No overlap/leaked responses/connections/threads, no fallback to synthetic data, deterministic recovery and clear unavailable state. Do not activate production scheduler during this mission. |
| P3.3 Reproducible release and recovery (M01/M09/M12) | Define supported Python/runtime versions, reproducible installation, local deployment/security profile, monitor/runbook, backup/restore and rollback. Preserve localhost binding and existing database configuration until a separately reviewed deployment requires changes. | Clean-environment install/test; configuration-only smoke checks; restore from a fixture backup and reconcile rows/checksums; failure alerts redact secrets; rollback drill succeeds. Public exposure/authentication is a distinct review, not an assumed property of a localhost server. |

P3 exit: repeatable local release, verified backup/restore and outage recovery, bounded
operational evidence and truthful user-facing reports. Scheduler/live Telegram switches
remain separately controlled.

## P4: enhancements and optimization

After P0-P3 acceptance, prioritize measured bottlenecks and documented research needs:
larger universe support, additional provider parity, websocket ingestion if justified,
portfolio ranking improvements, statistically defensible calibration and walk-forward
analysis. Any new strategy/liquidity feature needs point-in-time data and frozen
out-of-sample evaluation. Optimization must not weaken identity, freshness, provenance,
resource cleanup, sizing or acceptance gates.

## Integrated verification plan

Run offline checks from the project directory; no command below authorizes broker
access. The existing full suite uses mocked provider transport and temporary local
SQLite/loopback HTTP fixtures; it must not use production credentials or databases.
The lead report records executed commands, counts, warning inventory and exit codes.

```powershell
python --version

@'
from pathlib import Path
for path in sorted(Path('.').glob('*.py')):
    compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
'@ | python -B -

python -B -W error::ResourceWarning -m unittest -v test_bot.TestUpstoxReadOnlyReadiness test_bot.TestUpstoxHTTPErrorDetails test_bot.TestConfigurationPreflight
python -B -W error::ResourceWarning -m unittest -v test_bot.TestMarketDataFreshness test_bot.TestInstrumentIdentity test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility
python -B -W error::ResourceWarning -m unittest -v test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B test_bot.TestPositionSizingRiskAccounting test_bot.TestStateIsolation
python -B -W error::ResourceWarning .\test_bot.py -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract -v
python -B -W error::ResourceWarning -m unittest test_phase4_market_data test_phase4_strategy test_phase4_e2e -v

# Actual local configuration preflight; this flag must make zero broker requests.
python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

The established `test_bot.py` entry point includes the independent broker/shared and
Phase 4 modules through `load_tests`; normal discovery must load each test once.
Focused runs remain useful for diagnosis. `test_phase4_strategy` includes a reproduced
pre-fix counterexample: 241 otherwise fresh consecutive bars whose current-session
window starts at 10:00 previously emitted an ORB candidate. Its regression requires
rejection while complete bullish/bearish opening-range controls remain valid.
Run final full-suite verification after integration, not only each agent's tests.
Do not add per-selection counts together as if they were unique tests; selections
overlap. Inspect baseline failures, Python/resource warnings, added-line whitespace
and final changed-file hashes/diffs without reading `.env` contents.

The legacy `diagnostics.py` path is a broader Angel Phase 2C workflow, with profile
checks and possible persistence/receipt side effects. The new scoped alternative is
`diagnostics.py --market-data-only --symbol RELIANCE --check-config --json` for offline
preflight; remove only `--check-config` for a separately authorized live attempt.
It returns before the legacy store/profile/receipt path. Neither command changes
the configured provider, and a narrow cash-data PASS never authorizes replay.

## External blockers and next three actions

1. **Obtain one separately authorized cash-data observation.** Keep provider selection
   explicit; use the verified minimum diagnostic for that provider during an appropriate
   session. Retain only sanitized output and exit status. If the provider rejects it,
   use the returned code/message to identify the exact token/account/provider action;
   no cause can be asserted from HTTP 403 alone and credentials must never enter chat.
2. **Validate mapping, calendar and declared cash breadth.** After the first narrow
   success, establish current supported instrument/session evidence and choose a
   bounded next instrument/interval; full-market scanning remains separately controlled.
3. **Resolve the historical-source and paper-scope dependencies.** Determine obtainable
   authoritative source/effective-date evidence, then approve the smallest verifier/data
   package; independently specify the durable paper ledger/portfolio limits. Keep LIVE
   historical replay and Strategy 3 blocked while their requirements remain missing.

The source-evidence limitation includes missing verifier implementation and unavailable
independent artifacts. It cannot be resolved by relabelling a local file, setting a
manual accepted flag, trusting a current quote, or switching brokers.

Completion of Phase 4 offline work means the scoped software controls and deterministic
end-to-end path pass the recorded checks. It does not complete P0 real-provider
acceptance, authorize F&O proposals from cash observations, establish current/historical
master authority, create the missing paper ledger, or release historical Strategy 3.
Keep Telegram dry run enabled and the production scheduler disabled until separately
reviewed operational gates are satisfied.
