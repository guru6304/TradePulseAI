# TradePulse AI broker recovery and integration evidence

Date: 2026-10-18. **Result: PARTIAL PASS.** Current stage: offline integration and
read-only cash-market acceptance preparation. All final software checks pass;
neither provider has a successful real quote/candle acceptance in this mission.
LIVE historical replay and historical Strategy 3 remain blocked.

## Baseline, ownership and scope

Work used the existing project at
`C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`,
PowerShell, Python 3.14.6 and unittest. `git status --short` returned 128: this export
has no Git metadata. A snapshot of 42 non-secret source/documentation files captured
the actual starting tree; private `.env` files were excluded. Prior reports were
retained. The fresh pre-edit strict suite passed **382/382**, exit 0, in 73.342 s.

Three parallel agents inspected Angel broker safety, shared data/scanner contracts,
and project completion. Ownership excluded shared production edits: the first two
owned separate test modules, the third the capability/roadmap documents; the lead
owned production integration and final checks. All three encountered a platform
usage limit before finishing their turns. Their saved tests/drafts and source
findings were inspected, corrected and completed by the lead. They are not claimed
as completed independent approvals. Gemini/Argon review artifacts were unavailable.

The mission brief's Upstox body-discard premise was stale for this checkout: the
previous fix already existed. It was re-inspected and re-tested, not duplicated.
No Upstox adapter/diagnostic or credential changes were needed for that workstream.

## Confirmed findings and implementation

| Finding | Evidence / reproduction | Resolution and limit |
|---|---|---|
| Upstox error reporting already repaired | `UpstoxV2Adapter._request_json`, `sanitize_upstox_error_detail`, `_safe_upstox_read`; 21 HTTP-detail and 28 readiness tests, plus configuration tests | Existing 8-KiB error-body bound, safe status/code/message, closure, classifications and authentication invalidation retained. No real provider detail was obtained in this mission. |
| Angel path blocking missed actual GTT mutation routes | Starting `_request_json` blocked two prefixes; official SDK uses `/gtt-service/.../gtt/v1/createRule`, modifyRule and cancelRule. New rejection test reproduced transport/login attempts for unsupported paths | Exact method/path allowlist now rejects GTT, orders, portfolio and unknown/traversal/query variants before login. Only existing profile, quote, candle, Greeks and PCR capabilities remain allowed. Profile remains legacy-only and is never called by the new market-data command. |
| Angel HTTP errors leaked resources and raw exception causes | New login/refresh/market HTTP tests found open response streams; network traceback retained a dummy secret-bearing original cause | Close HTTP errors before raising or session recovery; suppress unsafe transport/parser causes at public market-data boundaries. Safe failures remain failures. |
| Angel could accept a missing/non-boolean success status | `raw.get('status') is False` accepted status None, 1 and string 'true' with plausible data | Require literal `status is True`; only accepted market-data envelopes increment `_authorized_reads`. Duplicate JSON and responses over 8 MiB reject before counting. |
| Failed login retained old authentication metadata | Rejected login left `authenticated_at_ist` from an earlier session | Invalidate JWT/auth/profile/market timestamps on failed authentication or rejected session; preserve bounded old-token redaction through recovery. HTTP 401/403 clear session proof; existing recovery remains bounded. |
| Angel error redaction missed encoded session/config values | New provider-error fixture exposed URL-encoded dummy API/session secrets and client code | Reuse existing configured-secret/message sanitizer, include JWT/refresh/feed tokens, client code and generated TOTP variants, cap safe text and remove terminal/header/request dumps. Raw response bodies/headers are not reported. |
| Angel accepted future quote observations and invalid market counts/prices | Future SmartAPI timestamp, out-of-range LTP and boolean volume/OI fixtures | Validate supplied timestamps and future skew; expose normalized observation time without substituting request time; reject impossible price/count values. Missing observation time remains absent for legacy bulk compatibility, and blocks the narrow diagnostic before candles. |
| Existing Angel diagnostic exceeded this acceptance scope | `run_angelone_diagnostics` and legacy CLI can call profile and instantiate/write a store or acceptance evidence | Add `run_angelone_market_data_diagnostics` and an early CLI branch. Fixed RELIANCE cash scope, no profile/store/receipt/scanner/Telegram/scheduler, quote validation before candles, freshness recheck after both reads. Legacy Phase 2C behavior is retained separately. |
| Shared candle/scanner safeguards already exist | `assess_live_candle_batch`, `enforce_live_candle_batch`, `bind_candles`, `MultiBrokerScanner.fetch_candles`, scanner `_require_current_scan_data` | Add cross-provider wire-fixture and real-evaluator gating tests instead of a new normalization abstraction. Identity, timezone, completion, OHLCV, grid/order/gaps/duplicates, freshness and provider/mode checks remain unchanged. |

Angel's API host now matches the current official SDK, `https://apiconnect.angelone.in`.
This corrects request construction to documented practice; it does not prove that
the former hostname was unavailable or explain the unrelated Upstox 403.

Key current source locations are `brokers.py:475` (`_safe_angel_market_read`),
`AngelOneSmartAPIAdapter` at 499, `_sanitize` at 630, `_invalidate_session` at 641,
`_read_response_bytes` at 665, `authenticate` at 780, `refresh_access_token` at 854,
`_request_json` at 919 and `get_quotes` at 1615. The narrow diagnostic begins at
`diagnostics.py:764`; CLI dispatch is in `main` at 893. Test-suite integration is
`test_bot.py:10264`, `load_tests`.

## Files changed and preservation review

| Path relative to project | Change |
|---|---|
| `brokers.py` | Angel adapter repairs above and one error-boundary decorator; no other existing broker class/function changed. |
| `diagnostics.py` | Narrow Angel market-data function and CLI branch before legacy persistence/profile paths. |
| `test_bot.py` | `load_tests` includes new modules in the established command, avoiding duplication during discovery. Every existing test class/function retains its baseline AST. |
| `test_angel_market_data.py` | 18 Angel safety tests and 10 narrow-diagnostic tests; synthetic credentials and mocked wire responses. |
| `test_market_data_contract.py` | 19 shared-contract/scanner/environment/discovery tests. |
| `README.md` | Narrow command, safe preflight/live separation and current report links. |
| `docs/TRADEPULSE_CAPABILITY_MATRIX.md` | Evidence/status matrix and explicit weighted completion rubric. |
| `docs/TRADEPULSE_COMPLETION_ROADMAP.md` | P0-P4 packages, dependencies, exit criteria and next three actions. |
| `docs/BROKER_RECOVERY_ENGINEERING_REPORT.md` | This integration and verification report. |

AST comparison confirms that the existing `run_angelone_diagnostics` implementation
and every Upstox helper/class remain unchanged. Protected production modules retain
their starting bytes: configuration, scanner, strategies, backtest/historical engine,
identity/archive/source qualification, readiness policy, storage, server and Telegram.
No schema, costs, sizing, state keys, execution gate or freshness policy changed.
No credentials or private settings were edited or displayed. The actual preflights
used the normal local configuration loader, exposing only approved safe fields.

## Executed QA evidence

| Run | Actual result | Exit |
|---|---|---:|
| Fresh strict pre-edit baseline | 382 passed, 0 failed; 73.342 s | 0 |
| Initial added-module reproduction | 34 methods: 22 passed, 10 failed, 2 errored; unittest reported 17 failing subtest/test entries and 4 error entries | 1 |
| First broker/contract/Upstox/config integration | 96 passed, 0 failed; 2.449 s | 0 |
| Existing Phase 1B/2A/2B/2C regression | 35 passed, 0 failed; 3.073 s | 0 |
| New diagnostics and contracts, intermediate | 44 passed, 0 failed; 0.217 s | 0 |
| Final production-code broker/contract/legacy integration | 70 passed, 0 failed; 3.573 s | 0 |
| Identity/freshness/archive/source/containment/replay gates | 171 passed, 0 failed; 17.226 s | 0 |
| First expanded full suite | 428 passed, 0 failed; 66.413 s | 0 |
| New suites with environment/discovery protection | 47 passed, 0 failed; 1.300 s | 0 |
| Direct contaminated-environment/discovery regression | 1 passed, 0 failed; 1.012 s | 0 |
| **Final strict integrated full suite** | **429 passed, 0 failed, 0 skipped; 64.138 s** | **0** |
| In-memory compilation | All 18 top-level modules passed | 0 |
| Final whitespace and preservation review | All 9 changed/new files passed; 38 original source/documentation files unchanged | 0 |
| Completion-rubric arithmetic | 12 categories; weights total 100%; weighted I=62%, R=34% | 0 |

Selections overlap and must not be added as unique-test totals. New tests total 47.
The initial added-module errors included a test-helper argument name collision with
the response's `provider` field. That fixture defect was corrected without relaxing
identity assertions. The failing Angel cases exposed real source defects above.

Final review also found that test_bot module cleanup restores the terminal environment
before separate modules run. Each new module now reapplies the existing offline
defaults during its own fixture lifetime. A subprocess regression restores deliberately
invalid terminal broker/session/scheduler settings, verifies isolated test success,
and checks that unittest discovery contains no duplicate test IDs.

The final log has **zero Python warnings**, zero ResourceWarnings and zero ignored
cleanup exceptions. Its only application warnings are three expected scan-overlap
messages: a scan was skipped because another was already in progress. Deliberate
failure fixtures also emit application ERROR logs. No warning filters, assertions,
tests or garbage collection were disabled. PowerShell's redirected unittest stderr
is rendered as NativeCommandError text by Tee-Object; Python's observed exit is 0.

Exact principal commands, from the project directory:

```powershell
python --version
python -B -W error::ResourceWarning test_bot.py -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract test_bot.TestUpstoxHTTPErrorDetails test_bot.TestUpstoxReadOnlyReadiness test_bot.TestConfigurationPreflight -v
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase1B test_bot.TestIndianFOSignalBotPhase2A test_bot.TestIndianFOSignalBotPhase2B test_bot.TestIndianFOSignalBotPhase2C -v
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract test_bot.TestIndianFOSignalBotPhase2A test_bot.TestIndianFOSignalBotPhase2B test_bot.TestIndianFOSignalBotPhase2C -v
python -B -W error::ResourceWarning -m unittest test_bot.TestInstrumentIdentity test_bot.TestMarketDataFreshness test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B -v
python -B -W error::ResourceWarning -m unittest test_market_data_contract.TestSharedMarketDataContract.test_independent_modules_ignore_process_configuration_and_discovery_has_no_duplicates -v
```

Full runs used `2>&1 | Tee-Object -FilePath` with task-specific temporary logs and
`exit $LASTEXITCODE` to retain and inspect actual output/status. In-memory compilation
uses `compile(path.read_bytes(), str(path), 'exec')` over all 18 top-level modules.
Whitespace checks use `git -c core.autocrlf=false diff --no-index --check` against
saved originals, without requiring Git history. Windows SQLite/configuration/loopback
fixtures required execution outside the filesystem sandbox. These are isolated test
services, not production scheduler/server activation. Non-ASCII source inspection
required UTF-8 stdout rather than the terminal's default cp1252.

## Actual broker/configuration evidence

The following are configuration-only commands, not live checks:

```powershell
python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
$LASTEXITCODE
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

| Check | Actual Upstox preflight | Actual Angel preflight |
|---|---|---|
| Effective broker / dry run / scheduler | upstox / true / false | upstox / true / false |
| Configuration | PASS | BLOCKED: Angel must be selected explicitly with valid configuration |
| Instrument | PASS: RELIANCE, NSE_EQ\|INE002A01018 | NOT_TESTED after configuration block |
| Authentication / quote / candles | NOT_TESTED / NOT_TESTED / NOT_TESTED | Same |
| configuration_ready / overall | true / NOT_TESTED | false / FAIL |
| Process exit | 0 | 1 |
| Persisted / receipt / replay allowed | false / false / false | Same |

The Angel result does not establish whether Angel credentials are configured or
whether its account would work: the currently selected provider is Upstox. No fallback
or setting change occurred. A synthetic Angel diagnostic fixture passes all checks,
but that is only evidence that the implemented path validates the fixture correctly.

**Live diagnostics: NOT_TESTED for both providers.** The supplied earlier Upstox
result remains user-reported quote FAIL / FORBIDDEN, authentication FAIL, candles
NOT_TESTED, exit 1. No new sanitized provider code/message or successful market-data
response was obtained. Its provider/account cause remains unknown; no token reissue,
permission change or portal correction is justified yet by this mission's evidence.
The existing root `upstox_acceptance_result.txt` was not parseable diagnostic JSON;
it was left unchanged, its raw contents were not displayed, and it was not treated
as a fresh acceptance result.

## Provider documentation and unresolved compatibility

- [Official SmartAPI SDK](https://github.com/angel-one/smartapi-python/blob/main/SmartApi/smartConnect.py)
  confirms current host, login/token, quote/candle/Greeks/PCR routes, real GTT prefixes,
  bearer/API-key/client-metadata headers and login payload fields. The SDK itself is
  not imported or executed; its logging/network side effects are not adopted.
- [Official SmartAPI docs](https://smartapi.angelone.in/docs) and its indexed market-data
  section describe LTP/OHLC/FULL and provider feed/trade timestamps. Direct rendered
  MarketData/RateLimit pages were unavailable through the browser tool. Indexed
  official documentation lists quote and candle per-second ceilings of 10 and 3;
  minute-limit information differs from an older announcement. Treat current exact
  limits as operational prerequisites, not verified account entitlements. Existing
  optional request pacing remains unchanged and is not a per-endpoint token bucket.
- Angel login reads existing `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN` and
  `ANGEL_TOTP_SECRET`. Optional existing settings include `ANGEL_SCRIP_MASTER_PATH`,
  `ANGEL_SCRIP_MASTER_MAX_AGE_HOURS`, `ANGEL_REQUEST_TIMEOUT_SECONDS` and
  `ANGEL_MIN_REQUEST_INTERVAL_SECONDS`. No new credential variable was invented.
  Headers currently use fixed loopback/zero client-network metadata; provider
  acceptance of those values is unverified. No IP-discovery network call was added.
- SmartAPI's documented human-readable exchange-time shape is recognized explicitly
  as NSE/IST; arbitrary timezone-naive ISO values are rejected. Verify the convention
  against an actual scoped response before operational acceptance. Missing provider
  time never becomes local request time. Prior-session references cannot pass current
  session acceptance.
- [Upstox full quotes](https://upstox.com/developer/api-documentation/get-full-market-quote/)
  matches the existing V2 path, instrument_key parameter and bearer access token.
  An API key is not an access-token substitute. [Response structure](https://upstox.com/developer/api-documentation/response-structure/)
  documents both code spellings already supported. [V2 intraday candles](https://upstox.com/developer/api-documentation/get-intra-day-candle-data/)
  is marked deprecated; actual availability is unverified, and this does not explain
  a failure at the different quote endpoint. No speculative V3/OAuth migration was made.

Pinned RELIANCE mapping, local master validation and request-bound candles do not
prove independently authoritative historical provenance. No instrument master was
downloaded. F&O needs separate current contract/universe, expiry/strike/lot, option
snapshot and candle validation; analytical chain support is not executable contract
history. See the capability matrix for each implemented subset and missing feature.

## Completion, safety and remaining work

The [weighted matrix](TRADEPULSE_CAPABILITY_MATRIX.md) estimates **62% implementation**
and **34% verified readiness** across 12 declared product milestones. Nine categories
have at least half their implementation; **0/12 are fully accepted, 12 remain partly
unaccepted** under the explicit I=100/R=100 rule. These are audit estimates, not
profitability or production-readiness guarantees. Offline engineering fixes are
complete without constituting an entire accepted product milestone.

The [P0-P4 roadmap](TRADEPULSE_COMPLETION_ROADMAP.md) records missing contract/universe
coverage, authoritative historical verifier/data, experiment orchestration/pagination,
portfolio-wide paper capital/P&L controls, forward paper ledger/EOD reporting, ranking,
empirical calibration and release/recovery evidence. Scanner optional-chain outages
currently abort the cash scan for ordinary broker errors; this is safe failure but
an availability coupling to resolve with explicit policy/tests, not silent bypass.
The dashboard friction view is explicitly hypothetical and separate from the actual
backtest API. Telegram's fixed 1% label/benchmark wording needs a truthful-reporting
review before delivery claims. No portfolio, ranking, strategy or UI redesign was
silently bundled into broker recovery.

No real order/trading/account/profile endpoint, live Telegram delivery, production
server or scheduler was invoked. Public documentation browsing was the only external
network activity. Localhost binding, database configuration, dry-run setting and
explicit provider selection were preserved. No operational receipt was issued and no historical
gate was relaxed. A cash-data PASS would establish only that provider/instrument/
interval/session scope, not F&O, full-account status, historical validity or profit.

**Next best action:** separately authorize one Upstox RELIANCE read-only attempt
during a configured NSE session with completed five-minute candles available, run
`python -B .\upstox_diagnostics.py --symbol RELIANCE --json`, then inspect its sanitized
JSON and immediate `$LASTEXITCODE`. Do not retry in a loop. If its safe provider detail
identifies an external problem, act only on that evidence. Select Angel deliberately
and pass its offline preflight before separately authorizing its market-data command;
do not send simultaneous checks or silently switch providers.
