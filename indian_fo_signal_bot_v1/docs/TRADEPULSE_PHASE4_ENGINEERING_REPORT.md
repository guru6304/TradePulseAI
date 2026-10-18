# TradePulse AI - Phase 4 engineering evidence

Date: 2026-10-18. Workspace: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`. Runtime: Python 3.14.6, Windows PowerShell.

## Decision

**PARTIAL PASS overall; PASS for the bounded offline engineering mission.** The fresh strict baseline was 429 passing tests. After seven confirmed control repairs and 32 new regression methods, the final strict suite passed **461 tests, 0 failures, 0 skipped**, exit **0**. All 21 top-level Python modules compiled in memory. No Python warnings occurred. Three expected application WARNING records exercised overlapping-scan rejection; these are disclosed below.

The project remains at **offline integration and preparation for scoped market-data acceptance**. Neither provider was contacted in this mission. Upstox's previously reported HTTP 403 remains historical failed-attempt evidence with an unknown provider/account cause. Angel One live acceptance remains NOT_TESTED. Successful mocked responses exercise implementation behavior, not genuine authenticated broker access.

The [market-data acceptance matrix](TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md) separates quote, candle, index, derivative and historical scopes. The [capability matrix](TRADEPULSE_CAPABILITY_MATRIX.md) retains the documented weighted estimates: **62% implemented, 34% verified readiness, 0/12 full product milestones accepted, 12 remaining**. Narrow control fixes do not deliver the missing operational acceptance, contract universe, historical-source verifier, paper portfolio or release process.

## Baseline, ownership and preservation

The lead captured the existing non-secret source/documentation bytes before editing, inspected the current adapters, scanner, strategy, identity, historical/readiness and storage paths, and reran the documented suite. No Git repository metadata is available: `git status --short` returned exit 128. Comparison therefore used the captured baseline and `git diff --no-index`; no repository was initialized or reset.

Independent agent ownership was explicit:

| Workstream | Owned files | Lead integration |
| --- | --- | --- |
| Broker-neutral contract and instrument scopes | `test_phase4_market_data.py`; `docs/TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md` | Reviewed reproduced defects, repaired existing production boundaries, reconciled PASS entries with final passing tests. |
| Offline end-to-end candidate path | `test_phase4_e2e.py` | Repaired failed-scan reporting and added the independent-failure status regression. |
| Scanner/strategy/source audit and product scope | `test_phase4_strategy.py`; capability matrix; completion roadmap | Repaired the ORB mandatory-input defect, reviewed evidence boundaries and retained the milestone rubric. |
| Lead | Production corrections, `test_bot.py` integration, README, this report and final verification | Ran the combined focused, safety and full suites after integration. |

Existing user files and earlier reports were preserved. The configuration template is byte-for-byte unchanged from baseline. No credentials, selected-provider settings, risk percentages, costs, database schema, historical qualification policy or API contracts were changed. The only strategy correction requires the opening bars already implied by the existing ORB definition.

## Confirmed defects and smallest corrections

Line references below describe this final checkout. All findings are CONFIRMED by source inspection and deterministic offline regressions; none is operational broker evidence.

| Priority / defect | Execution path and failure scenario | Correction and current source | Regression evidence |
| --- | --- | --- | --- |
| P0: Upstox continued after an unusable quote observation | `run_upstox_diagnostics` could request candles when quote time was absent or already stale, before reporting the eventual failed/blocked quote. This violated the minimum-request acceptance procedure. | `upstox_diagnostics.py`, `run_upstox_diagnostics`, lines 82-112: apply the unchanged delay/skew and date limits before candle transport; stop unless quote PASS. Retain the post-candle age recheck. | Shared missing, stale and previous-day observation tests; existing missing-time and old-time assertions strengthened to require candles NOT_TESTED and exactly one request. |
| P0: overly broad Upstox intraday endpoint allowlist | `_request_json` accepted any string beginning with the intraday prefix, including traversal, query suffixes and extra path components. | `brokers.py`, `UpstoxV2Adapter._request_json`, lines 3275-3294: exact supported interval/path shape, canonical encoded instrument key, and rejection of decoded separators, query/fragment characters and controls before transport. Existing quote/chain endpoints are unchanged. | `test_upstox_intraday_allowlist_rejects_malformed_and_traversal_routes_before_transport`; existing endpoint-boundary and real adapter tests. |
| P0: contradictory wire provenance could be overwritten | Quote/candle normalization supplies LIVE fields. An explicit SIMULATED/UNKNOWN mode or simulated marker in the response envelope/data/item could previously be discarded. Angel quote parsing checked the item but omitted envelope identity metadata. | `instrument_identity.py`, `check_echo`, lines 120-154: reject explicit non-LIVE/invalid provenance and inspect the nested data object. `brokers.py`, Angel `get_quotes`, lines 1687-1692: validate envelope and item against each requested identity. Missing echo stays request-bound evidence. | `test_explicit_nonlive_wire_provenance_is_never_relabelled_live` covers both providers, envelope/data/item locations as supported by their schemas, and contradictory values. Shared identity and source-isolation suites remain passing. |
| P1: option strike could be positive infinity | `option_contract` accepted a numeric positive infinity when the requested strike and record agreed, allowing a nonsensical exact-contract identity. | `instrument_identity.py`, `option_contract`, lines 178-205: require a finite positive numeric strike before identity comparison. Existing expiry, side, lot, master and provider requirements remain mandatory. | `test_option_contract_rejects_nonfinite_and_nonpositive_matching_strikes`; missing contract-field and spot-versus-contract containment tests. This does not implement option execution. |
| P1: ORB could use later bars as the opening range | `evaluate_orb_breakout` selected the first three returned bars of the day. An otherwise fresh window beginning at 10:00 could generate a false ORB; missing/incomplete opening bars could be replaced by later ones. | `strategies.py`, `evaluate_orb_breakout`, lines 1377-1405: require the actual completed 09:15, 09:20 and 09:25 bars before computing the existing range. No new strategy model or threshold is introduced. | Four `TestPhase4StrategyRequiredData` methods: real bullish/bearish controls remain valid; shifted, each missing and incomplete opening-bar scenarios reject. |
| P1: current provider outage displayed an older successful scan | After a candidate scan, a subsequent acquisition `BrokerDataError` recorded a failed DB run but left `last_scan_summary` showing the prior success and its signals/dispatches. | `scanner_engine.py`, `run_single_scan`, lines 604-643: set a new FAILED summary with current run metadata, empty candidates/dispatches, current freshness and persistence outcome, then re-raise the original failure. Existing history is retained. | E2E success -> transport failure for both providers: no evaluator, no new signal/dry-run dispatch, a failed run is recorded and latest summary is FAILED. |
| P1: status could claim signals allowed after an independent failed read | A separate quote read after a successful scan set connection ERROR, while the fresh cached candle evidence still made the top-level `live_signals_allowed` flag true. The scan itself would refetch and fail safely; the status claim was misleading. | `scanner_engine.py`, `get_broker_status`, line 434: require CONNECTED_VERIFIED as well as fresh candle evidence. Retain the separate candle-freshness facts. | `test_independent_broker_failure_revokes_signal_status_despite_fresh_scan_evidence`: reproduced in both providers before the fix; now confirms ERROR, fresh retained candle evidence and signals disallowed. |

Initial independent defect-reproduction runs were intentionally red: the first 18 contract tests had 14 passing methods and four failing methods across five subcases; the first eight E2E tests had seven passing methods and one failing method across two provider subcases; the four ORB tests had one passing method and three failing methods across ten subcases. The later independent-status reproducer had one failing method across two provider subcases. These were investigated and fixed, not suppressed. The final suite below includes the expanded provenance coverage and the added status method.

## Offline end-to-end evidence

`test_phase4_e2e.py` uses the existing synthetic order-block fixture, explicitly labelled **OFFLINE SIMULATION**, transported as provider-shaped JSON through real adapters. Its last 60 five-minute price bars are placed within one NSE session; Upstox receives newest-first one-minute components and performs its real aggregation. No evaluator, identity validator, freshness gate, sizing decision or persistence implementation is replaced to manufacture acceptance. Wrapped evaluator/sizing functions execute their originals.

For both providers, the actual path is:

`urllib fixture -> existing adapter -> exact request/response identity -> OHLCV/order/interval/session/completion/freshness -> MultiBrokerScanner -> IntradayBotEngine -> real order-block evaluator -> real sizing/invalidation -> scoped dedup/mitigation -> temporary SQLite -> actual Telegram dry-run formatter`.

At the injected 2026-10-16 14:15:05 IST clock, the candidate references the completed **14:10** RELIANCE bar, with fixture entry **2955.74**. A deliberately extreme forming 14:15 bar is excluded. Entry, stop, invalidation and target ordering are asserted; quantity, costs, capital and risk reconcile with the unchanged real sizing function. The stored identity/provider/mode/context match the candidate. Same-scope repeated/restarted scans suppress duplicates and retain mitigation; different providers retain distinct keys. Insufficient risk budget, invalidated prices, invalid OHLCV, mismatched identity, stale data and transport failures produce no new candidate.

The mocks exercise strict LIVE adapter semantics only inside isolated test fixtures and temporary stores. They do not relabel synthetic data as accepted operational evidence, write to the configured application database, issue receipts or pass historical acceptance. E2E assertions independently verify blocked LIVE replay and historical Strategy 3.

## Executed checks and actual results

Commands ran from the project directory. Test selections overlap and must not be added together as unique test totals. `-B` prevents bytecode files; compilation uses `compile(...)` in memory. Broker transport is mocked. Existing HTTP API tests use temporary loopback servers; no production service was started.

| Check | Actual result | Exit |
| --- | --- | ---: |
| `python --version` | Python 3.14.6 | 0 |
| Baseline in-memory compile of all top-level Python files | 18 modules | 0 |
| Baseline `python -B -W error::ResourceWarning test_bot.py -v` | 429 passed, 0 failed, 0 skipped; 69.449 s | 0 |
| Baseline broker/configuration selection below | 109 passed; 4.195 s | 0 |
| New three-module selection after initial fixes, before adding independent-status method | 31 passed; 2.029 s | 0 |
| Final broker/configuration/contract/E2E/ORB selection below | 141 passed, 0 failed, 0 skipped; 5.300 s | 0 |
| Final identity/provenance/freshness/scanner/replay/risk safety selection below | 226 passed, 0 failed, 0 skipped; 24.021 s | 0 |
| **Final `python -B -W error::ResourceWarning test_bot.py -v`** | **461 passed, 0 failed, 0 skipped; 74.353 s** | **0** |
| Final in-memory compile of all top-level Python files | 21 modules | 0 |
| Added-line whitespace review with `git diff --no-index --check` against captured original bytes | No whitespace errors; final changed-file review also confirms intended scope | 0 |
| Selected Upstox configuration-only diagnostic | Configuration and instrument PASS; live checks NOT_TESTED | 0 |
| Angel configuration-only diagnostic | Configuration BLOCKED because Upstox is selected; CLI overall FAIL; live checks NOT_TESTED | 1 |

Baseline broker/configuration selection:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxReadOnlyReadiness test_bot.TestUpstoxHTTPErrorDetails test_bot.TestConfigurationPreflight test_angel_market_data test_market_data_contract -v
```

Final integrated broker selection:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxReadOnlyReadiness test_bot.TestUpstoxHTTPErrorDetails test_bot.TestConfigurationPreflight test_angel_market_data test_market_data_contract test_phase4_market_data test_phase4_e2e test_phase4_strategy -v
```

Final safety selection:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase2C test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B test_bot.TestPositionSizingRiskAccounting test_bot.TestStateIsolation test_bot.TestMarketDataFreshness test_bot.TestInstrumentIdentity test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility -v
```

Compilation and configuration-only commands:

```powershell
@'
from pathlib import Path
files = sorted(Path('.').glob('*.py'))
for path in files:
    compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
print('Compiled in memory:', len(files))
'@ | python -B -

python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
$LASTEXITCODE
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

No Python `ResourceWarning`, other Python warning or unraisable cleanup warning occurred in the recorded final runs. Both full runs emitted **three application WARNING records**, each `Scan ... skipped because another scan is already in progress.` These are expected overlap-protection scenarios, not skipped unittest methods. Focused broker and safety selections emitted zero application warnings. Expected ERROR logs from injected transport/database/validation failures remain visible; passing tests assert those failures safely. PowerShell's `NativeCommandError` wrapper around unittest stderr is shell formatting, not a Python test failure; process exits and unittest summaries above are authoritative.

The sandbox initially prevented access to temporary SQLite files in an independent E2E run. Authorized execution of the same offline tests resolved it; no code change or skipped test was used to bypass that environment limitation. No new dependencies were installed. Git status/history/staged-diff checks remain unavailable in this exported tree; baseline byte comparisons, AST review and no-index whitespace checks were used instead. Compilation/tests establish this Python 3.14.6 environment only, not a supported-runtime matrix.

## Configuration and provider evidence

Only supported configuration-only diagnostics were executed against the local effective configuration. Neither command creates an adapter/network request on its configuration-only branch. Secret values and `.env` contents were never displayed or copied into this report.

| Evidence | Upstox | Angel One |
| --- | --- | --- |
| Effective selected broker | `upstox` | Still `upstox`; selection was not changed |
| Safety flags | `telegram_dry_run=true`, `enable_background_scheduler=false` | Same effective flags |
| Local preflight | `configuration_ready=true`, configuration PASS, instrument PASS; exit 0 | `configuration_ready=false`, configuration BLOCKED, overall FAIL; exit 1. This does not prove Angel credentials are missing or invalid. |
| Authentication, quote, completed candles against real provider | NOT_TESTED | NOT_TESTED |
| Narrow diagnostic side effects | `data_persisted=false`, `readiness_receipt_issued=false`, `historical_replay_allowed=false` | Same false fields |
| Offline parsing, failures, shared contract and E2E | PASS in the bounded test scope above | PASS in the bounded test scope above |

`ACTIVE_BROKER` and `UPSTOX_ACCESS_TOKEN` retain their existing meaning. `UPSTOX_API_KEY` is a compatibility setting, not an access-token replacement; no OAuth/token changes were made. Upstox's earlier 403 is not evidence for a particular token, entitlement, account, API version or provider-side cause. Current HTTP parsing preserves only bounded sanitized status/code/message details. The request categories distinguish authorization from data/schema validity and from current candle/strategy readiness. No profile/account verification is claimed.

`.gitignore` excludes local `.env`/credential files and keeps `.env.example`. Whether secrets were tracked in a different Git checkout cannot be established here. The server's existing localhost default and database configuration were preserved. Tests use temporary databases and credential placeholders. No live Telegram, production scheduler/background scan, real broker/account/trading request, operational readiness receipt or production database write was performed. Existing scheduler/account-path tests remain isolated offline fixtures.

## Remaining blockers and scope limits

1. **Real-provider acceptance:** no fresh successful authenticated RELIANCE quote plus completed candles and process exit has been supplied. Index-specific candles, F&O, Greeks/OI and operational breadth need separate evidence. Checked-in identities are consistency references, not current authoritative master observations.
2. **Derivative execution:** current spot mappings do not resolve live futures/stock F&O contracts. Angel index-option identity/analytics support remains conditional on a current exact master and verified prior-session closing OI. Upstox analytical chains do not supply a supported executable option resolver. No cash fixture establishes contract fills, lots or entitlement.
3. **Historical provenance/research:** no independent archive authenticity/effective-date verifier exists. `source_qualification.assess_source_evidence` and `instrument_archive.resolve_archives` continue to block LIVE historical eligibility. A receipt/URL/hash/manual flag cannot replace this. Replay pagination above the 10,000-row cap and enforced chronological study orchestration remain work; historical Strategy 3 still lacks true option-contract fills/accounting and remains blocked in all modes.
4. **Strategy/portfolio scope:** a small fresh sample does not establish every strategy's warmup or complete session VWAP input. The scanner has no shared forward portfolio capital/exposure/day-P&L reservation. The synthetic adapter and replay ledger are not a durable paper-trading portfolio or EOD reconciliation service.
5. **Delivery/operations:** persistence before delivery lacks a durable outbox; fixed risk/benchmark/probability labels require truthful reporting work. A complete exchange calendar, current endpoint compatibility, long-running outage drills, reproducible release, backup/restore and deployment acceptance remain unproven. See the ordered [P0-P4 roadmap](TRADEPULSE_COMPLETION_ROADMAP.md).

## Changed files

Modified: `brokers.py`, `instrument_identity.py`, `scanner_engine.py`, `strategies.py`, `upstox_diagnostics.py`, `test_bot.py`, `README.md`, `docs/TRADEPULSE_CAPABILITY_MATRIX.md`, `docs/TRADEPULSE_COMPLETION_ROADMAP.md`.

Created: `test_phase4_market_data.py` (19 methods), `test_phase4_e2e.py` (9 methods), `test_phase4_strategy.py` (4 methods), `docs/TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md`, this report. The existing `test_bot.load_tests` includes the three modules in the established strict command; discovery avoids duplicate loading. Existing warning policies/assertions were not weakened, no failures were skipped, and unrelated user changes were preserved. Temporary comparison/test-log artifacts were removed after extracting the evidence above.

## Single best next step and external authorization gate

Obtain explicit authorization for **one selected-Upstox RELIANCE cash-data diagnostic**, during an actual configured NSE session after completed five-minute candles are available. Run from the project directory only after the configuration preflight passes:

```powershell
# CONTACTS UPSTOX: separate authorization required; NOT executed in Phase 4.
python -B .\upstox_diagnostics.py --symbol RELIANCE --json
$LASTEXITCODE
```

The existing path uses GET `/v2/market-quote/quotes`, then only after quote identity, prices and observation freshness pass, GET `/v2/historical-candle/intraday/NSE_EQ%7CINE002A01018/1minute`; it validates/aggregates to completed five-minute bars. There is no profile/account call, automatic provider switch or retry loop in this procedure. Retain only the sanitized JSON and actual process exit. On rejection, stop and identify the smallest external action from the returned evidence; do not guess its cause or request credentials in chat.

Authorization alone does not establish acceptance. A successful result would support only this RELIANCE cash quote/candle path, not full account verification, a full-universe scan, derivative readiness, a Phase 2C receipt, LIVE historical replay or historical Strategy 3. Live acceptance is **NOT_TESTED** at the close of this mission.
