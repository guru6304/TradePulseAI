# Upstox acceptance readiness implementation

Current follow-up: [configuration fix, verification and roadmap](UPSTOX_CONFIGURATION_FIX_REPORT.md).
The original counts below describe this implementation milestone. The follow-up
records the reproduced baseline failure, isolated offline tests, corrected local
configuration, current counts and the new `--check-config` preflight. Live broker
acceptance remains unverified.

Date: 2026-10-18. Outcome: software prepared for a separately authorized,
one-instrument read-only acceptance attempt. **No live connectivity was tested.**
All transport in tests was mocked; HTTP test servers in the existing suite used
loopback. No real credentials, public documentation requests, broker requests,
Telegram delivery or orders were used in this package.

## Credential protection and configuration

The actual workspace contains the project directory and no Git metadata.
`git rev-parse --show-toplevel` reported that it is not a Git repository. No
applicable `.gitignore` existed before this change. A workspace-root `.gitignore`
now ignores `.env`, `.env.*`, local credential/configuration names, secret
directories and private-key containers. It explicitly preserves `.env.example`
and `.env.*.example` templates at any depth. Git's actual ignore implementation
was exercised in an isolated temporary repository with a copy of these rules.
The test covers the project's `.env`, nested environment files, local config,
credentials/secrets, private keys and retained templates.

No `.env` was present when checked by filename metadata; no secret file was opened
or printed. Whether `.env` was tracked in another checkout cannot be established
without its Git metadata. Ignore rules do not untrack existing files. If another
checkout contains tracked credentials, revoke/rotate exposed secrets and review
index removal there; history rewriting/pushing requires separate approval. No
such operations were performed here.

Configure privately, only when preparing the authorized attempt:

| Existing variable | Meaning |
|---|---|
| `ACTIVE_BROKER=upstox` | Select the existing adapter. |
| `UPSTOX_ACCESS_TOKEN` | Pre-issued OAuth bearer token consumed by requests. Obtain through an authorized external process; never paste it into chat or command arguments. |
| `UPSTOX_API_KEY` | Read for compatibility but unused by current adapter requests; cannot substitute for the token. |
| `TELEGRAM_DRY_RUN=true` | Required diagnostic guard; no Telegram sender is constructed regardless. |
| `ENABLE_BACKGROUND_SCHEDULER=false` | Required diagnostic guard; no scheduler is constructed regardless. |

Keep localhost binding and the existing database configuration unchanged. No new
credential variable, OAuth exchange, token-refresh flow or database setting was
introduced. `config.py` loads `.env` at import relative to the working directory;
existing process environment variables take precedence. Run future commands from
`indian_fo_signal_bot_v1`. `.env.example` now explains the token/API-key distinction.

## Quote and transport behavior

The existing `UpstoxV2Adapter` now implements standalone full quotes using:

```text
GET https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_EQ%7CINE002A01018
```

The implementation references the documented V2 contract at
[Upstox full market quote](https://upstox.com/developer/api-documentation/get-full-market-quote/).
No documentation or endpoint request was made in this network-free package.
Current availability, entitlement and live response compatibility remain acceptance
questions; mock success does not establish them.

The adapter checks the pinned requested instrument, single-entry response/map key,
and identity fields actually echoed in the envelope/item. Mismatch fails closed.
Missing identity echo is labelled `REQUEST_BOUND_NO_ECHO`; neither a local mapping
nor request binding is promoted to independent provider identity confirmation.
The quote validates positive finite last price/OHLC, nonnegative supplied volume,
session high/low relationships and supplied timezone/epoch timestamps. Previous
close is allowed outside today's range. Missing observation timestamp is retained
as missing evidence; the diagnostic blocks acceptance. Malformed/future supplied
timestamps fail. The adapter supports existing FULL/OHLC/LTP call conventions,
using the full-quote endpoint and its validation contract for all three modes.

Upstox reads share a GET-only allowlisted helper, eight-second timeout, eight-MiB
response bound and duplicate-JSON-field rejection. HTTP 401/403 revoke retained
authentication; 429 yields `RATE_LIMIT` and does not cause a retry storm. Other
HTTP, transport, encoding/JSON and provider-envelope failures are explicit.
HTTPError response resources close before raising. Raw bodies, request objects,
headers and raw exception causes are not emitted.

`sanitize_broker_message` masks configured secret values and standard URL-encoded
forms, plus bearer/credential-labelled text. The Upstox boundary sanitizes retained
error messages, suppresses raw exception-chain rendering and converts unexpected
parser exceptions to fixed messages. Existing Upstox expiry/chain reads use that
boundary too, removing the earlier raw expiry-value leakage path. Other adapters'
implementations and Angel diagnostics are unchanged.

Authentication is recorded only after a successful authorized market-data response
envelope, independently of quote/candle validation outcomes. The evidence is bound
to the token's digest; replacing the configured token invalidates it. Presence of
configuration alone is unverified. `get_broker_status` uses observed authentication
evidence rather than defaulting to true for a non-JWT adapter with credentials.
Connection and candle freshness remain separate observations. A malformed quote can
therefore fail validation after an authorized response; no acceptance is inferred.

## Dedicated diagnostic and operational boundary

The following command **contacts Upstox and requires separate authorization**.
It was exercised through mocked entry-point tests only, not against the provider:

```powershell
python -B .\upstox_diagnostics.py --symbol RELIANCE --json
```

`--symbol` is required and currently accepts RELIANCE only. `--sample-size` accepts
1 through 10, default 5. Output is JSON, including without the optional `--json` flag.
The diagnostic validates the configured NSE cash mapping against the checked-in
`NSE_EQ|INE002A01018` reference. Unknown/changed mappings block before transport.

The normal path is exactly two GETs: standalone quote, then the existing intraday
endpoint `/v2/historical-candle/intraday/{encoded_key}/1minute`. The existing adapter
validates source order, OHLCV, timestamps and gaps before five-minute aggregation,
then applies its unchanged freshness policy. It receives the session batch and
reports a bounded completed-only sample; no nonexistent server-side sample-limit
parameter was introduced. Failed quote reads stop before the second request.

Each configuration, instrument, authentication, quote and candle check reports
`PASS`, `FAIL`, `BLOCKED` or `NOT_TESTED`. Exit 0 requires all five to pass; required
failure/blockage exits 1, parser misuse exits 2. Successful authorized reads prove
access to that market-data endpoint, not profile/account verification. The current
run must observe such a response; previously retained authentication alone cannot
pass a failed attempt.

Quote age is rechecked after both requests against the existing configured
`LIVE_CANDLE_MAX_DELAY_SECONDS` allowance, and future skew against
`LIVE_CANDLE_FUTURE_SKEW_SECONDS`, without changing the candle freshness rules.
Missing quote observation time blocks acceptance. Candle freshness is re-evaluated
at completion and prior-session reference data stays blocked for current-session
acceptance. Attempt during a configured NSE session after completed five-minute
bars exist, with a correct clock and holiday configuration. Do not relax limits
when real data fails these checks.

The diagnostic never constructs a store, scanner, scheduler or Telegram dispatcher,
does not start a server, and writes no diagnostic/market-data/acceptance records.
Its output explicitly says no receipt was issued, no data was persisted and no
historical replay was authorized. No trading, GTT, profile or option endpoints are
part of this diagnostic. `diagnostics.py` remains the existing Angel-specific CLI.
The Angel-only receipt restrictions remain byte-identical.

## Changed files and functions

| File | Exact scope |
|---|---|
| Workspace `.gitignore` | New credential/configuration ignore rules and template exceptions. |
| `.env.example` | Three explanatory Upstox authentication comments only. |
| `brokers.py:3006-3038` | New `sanitize_broker_message` and `_safe_upstox_read`. |
| `brokers.py`, `UpstoxV2Adapter` | Changed `__init__`, `_validate_credentials`, `get_intraday_candles`, `get_expiry_list`, `get_option_chain`, `_normalize_option_chain_response`; new `_fail`, `is_authentication_verified`, `is_connection_verified`, `_request_json`, `get_quote`. Existing `_headers` remains unchanged. Added `re`/`wraps` imports. |
| `scanner_engine.py:253-440` | Only `IntradayBotEngine.get_broker_status` authentication-evidence selection changed. |
| `upstox_diagnostics.py` | New `run_upstox_diagnostics`, `_safe_category`, `main` and explicit CLI entry point. |
| `test_bot.py:9457-9807` | New `TestUpstoxReadOnlyReadiness` with five fixture helpers and 28 tests. |
| `README.md` | Setup, network-contact warning, diagnostic scope and offline commands. |
| `docs/UPSTOX_READINESS_IMPLEMENTATION.md` | This report. |

No strategies, costs, sizing/accounting, state keys, schema, existing freshness
functions, source qualification or historical replay code changed. AST comparison
of the saved baseline confirms no other broker class/function or scanner method
changed. Protected modules, including `diagnostics.py`, `readiness_policy.py`,
`storage.py`, `config.py`, `strategies.py`, `backtest_engine.py`, `historical_data.py`,
identity/archive/source-qualification modules, server and Telegram code, retain
their original bytes. Existing user changes were preserved.

## Offline verification

Python 3.14.6, Windows PowerShell, from `indian_fo_signal_bot_v1`:

| Run | Actual outcome |
|---|---|
| Final focused Upstox selection | **28 passed, 0 failed** |
| Affected provider/identity/freshness/Angel diagnostic/gate/state selection | **160 passed, 0 failed**, 39.333 seconds |
| Separate SQLite migration/restart/concurrency selection | **9 passed, 0 failed** |
| Complete strict suite | **348 passed, 0 failed**, 136.952 seconds |
| In-memory top-level compilation | **16 modules passed**, no bytecode artifacts |
| Saved-original whitespace checks | **8 files passed**, no whitespace errors |
| Saved baseline | **35 of 40** original project files unchanged; five modified, two new project files, plus the new workspace `.gitignore`; no deletions |

The first new-class run had 21 passes, one failure and one error: a fixture supplied
only an unfinished source bar beyond the completed sample, and a persistence guard
named a nonexistent method. The fixture/guard were corrected. A later expanded
run had 26 passes and one ignore-test failure caused by Windows CRLF conversion on
Git stdin; the test now uses Git's NUL-delimited input/output. The final passing
tests use the real existing aggregation and ignore rules; no assertions or warning
filters were weakened. An intermediate combined run also passed 100/100 before
the final additional malformed-response test was added.

No Python warnings or ignored resource exceptions remained. The full suite logged
exactly three expected application `[WARNING]` messages for overlapping scans
being skipped. Intentional failure fixtures also produce error-level logs. The
PowerShell Tee-Object wrapper renders unittest stderr as NativeCommandError text;
Python returned exit code 0. No warning filter was relaxed.

Commands actually run:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxReadOnlyReadiness -v
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase1B test_bot.TestMarketDataFreshness test_bot.TestInstrumentIdentity test_bot.TestIndianFOSignalBotPhase2A test_bot.TestIndianFOSignalBotPhase2B test_bot.TestIndianFOSignalBotPhase2C test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B test_bot.TestStateIsolation -v
python -B -W error::ResourceWarning test_bot.py -v
```

The full command was piped to `Tee-Object` for output inspection and its Python exit
code was propagated. The separate SQLite command used:

```powershell
python -B -W error::ResourceWarning -m unittest `
  test_bot.TestSourceEvidenceQualification.test_restart_preserves_versioned_assessment_and_additive_migration `
  test_bot.TestSourceEvidenceQualification.test_policy_assessments_are_idempotent_under_concurrent_startup `
  test_bot.TestInstrumentArchives.test_restart_and_additive_migration_preserve_existing_rows_and_archives `
  test_bot.TestInstrumentArchives.test_concurrent_startup_and_idempotent_ingestion_preserve_evidence `
  test_bot.TestStateIsolation.test_legacy_migration_is_additive_deterministic_and_fails_closed `
  test_bot.TestStateIsolation.test_concurrent_database_writers_dedup_without_cross_scope_mutation `
  test_bot.TestStateIsolation.test_concurrent_schema_initialization_is_safe `
  test_bot.TestIndianFOSignalBotPhase2B.test_p2b_sqlite_transaction_rollback_and_concurrent_baseline_access `
  test_bot.TestIndianFOSignalBotPhase3B1B.test_later_store_instance_revalidates_evidence_and_additive_migration -v
```

Compilation used `compile(path.read_bytes(), str(path), 'exec')` for every top-level
Python module. Temporary-directory/full-suite checks ran in authorized execution
outside the Windows sandbox due to its temporary filesystem restrictions. Git
tracking/status checks are unavailable without metadata; isolated ignore-rule and
`git diff --no-index --check` verification do not require changing this checkout's
Git state. Saved originals/hashes support the baseline comparison.

## Remaining acceptance prerequisites

The implementation is ready for a separately authorized RELIANCE cash diagnostic,
conditional on privately configuring a usable OAuth token, a correct working
directory, clock/calendar, provider access/entitlement and a live trading session.
Real endpoint compatibility, latency, quote identity/timestamps, candle coverage
and freshness remain unverified until that attempt. Token issuance/expiry recovery
is external; no automatic refresh is claimed. Keep the local JSON report private
and review only its sanitized observations.

A cash diagnostic does not establish futures, options, contract lot/expiry/strike
mapping or Greeks readiness. Existing Upstox chains remain analytical inputs.
LIVE historical replay and historical Strategy 3 remain blocked under their
unchanged independent gates. A successful diagnostic issues no readiness receipt.
