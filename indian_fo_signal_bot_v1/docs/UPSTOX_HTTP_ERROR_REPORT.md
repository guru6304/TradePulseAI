# Upstox HTTP error reporting and acceptance evidence

Date: 2026-10-18. Result: **PARTIAL PASS**. Offline implementation and verification
passed. A fresh live acceptance attempt was **NOT_TESTED**: this task permits one
only with explicit live authorization and user readiness, which have not been
established for this run. No broker API request was made.

## Confirmed defect and remaining uncertainty

Before editing, `UpstoxV2Adapter._request_json` closed HTTPError without reading its
body, then raised a category and generic HTTP message. The diagnostic retained only
the category. This discarded potentially useful provider evidence. It did not
establish why the provider returned 403. No account, token, permission or endpoint
root cause is established by the evidence currently available.

The user's supplied brief reports a previous real quote failure: configuration and
instrument PASS, quote FAIL / FORBIDDEN, authentication FAIL, candles NOT_TESTED,
exit 1. This is user-reported operational evidence, not a request made or reproduced
by this implementation run. No provider error code/body was supplied in that brief.

## Implementation and changed files

Paths below are relative to `indian_fo_signal_bot_v1`.

| File / functions | Purpose |
|---|---|
| `brokers.py`: `UpstoxV2Adapter._request_json` | Read at most 8,193 error bytes; discard explanations above 8,192 bytes; close in `finally`; retain the original HTTP classification/status. Accept the documented error envelope and only its first error object. |
| `brokers.py`: `sanitize_upstox_error_detail` | Support `errors[0].error_code` and deprecated `errorCode`, plus `message`. Allow bounded UDAPI codes; redact configured secrets/encoded variants and bearer values; omit header/request/account dumps; redact URLs, emails and long numeric identifiers; remove terminal controls and subsequent lines; cap messages at 240 characters. Other response fields are never forwarded. |
| `brokers.py`: `_safe_upstox_message`, `_fail`, `_safe_upstox_read`, `sanitize_broker_message` | Preserve safe details in adapter errors and attach curated scalar fields. Fail safely if sanitization raises or returns an invalid type. Include configured client/chat identifiers in redaction. |
| `upstox_diagnostics.py`: `run_upstox_diagnostics`, `_safe_http_error_details` | Add validated `http_status`, optional `provider_error_code` and `provider_error_message` to quote/candle failure JSON. Never stringify arbitrary exceptions or copy response/request objects. |
| `test_bot.py`: new `TestUpstoxHTTPErrorDetails` | Add 21 offline regression tests using existing quote/candle fixture helpers, real urllib HTTPError instances and synthetic response streams. |
| `README.md` | Explain safe error fields, bounds, unresolved live status, V2 deprecation and the additional offline test command. |
| `docs/UPSTOX_HTTP_ERROR_REPORT.md` | This evidence report. |

HTTP classification remains 401 AUTH_FAILURE, 403 FORBIDDEN, 429 RATE_LIMIT, other
statuses HTTP_ERROR. Empty, malformed, HTML, oversized, duplicate-key, excessively
nested and unexpected error bodies retain the HTTP failure without provider text.
Read/close errors cannot replace the original failure with an unsafe exception.
Only the first documented error is reported; additional errors and unknown schemas
are deliberately unavailable. Provider explanations remain untrusted text, not
independent proof of a provider/account diagnosis or an acceptance decision.

401/403 still clear authentication verification. Failed HTTP requests never
increment successful authorized-read counters or establish a verified connection.
Other HTTP failures preserve prior authentication evidence but fail connection
verification. A failed quote ends the diagnostic before a candle request.

AST comparison against the saved pre-edit source confirms that `_fail` and
`_request_json` are the only changed Upstox methods. Quote/candle parsing, endpoint
allowlisting, headers, successful-response parsing and all other broker classes
retain their existing behavior. Existing test classes retain their baseline AST.
No credentials, configuration, strategies, accounting, storage/schema, scanner,
identity, provenance, freshness or historical-readiness implementation was edited.

## Baseline and test evidence

Workspace: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`.
Commands ran from its existing `indian_fo_signal_bot_v1` subdirectory in PowerShell,
using Python **3.14.6** and the standard-library unittest runner. `git status --short`
returned 128 because this exported workspace has no Git metadata. No prior Git diff
can be reconstructed. A private-config-free snapshot of 41 source/documentation
files was used to check preservation and changes against the actual starting tree.

| Check | Pass / fail | Process exit |
|---|---|---|
| Pre-edit Upstox + configuration baseline | 41 / 0 | 0 |
| Actual pre-edit offline configuration preflight | Configuration and mapping PASS; live NOT_TESTED | 0 |
| Initial new HTTP + Upstox + configuration tests | 62 / 0 | 0 |
| Identity / freshness / archive / source / containment / readiness regressions | 171 / 0; 16.200 s | 0 |
| First strict full run | 382 / 0; 63.090 s | 0 |
| Strengthened quoted-header/request-dump regression, before final hardening | One test failed, with three failed subtests | 1 |
| Final HTTP + Upstox + configuration tests | 62 / 0; 1.655 s | 0 |
| Final strict full run, after hardening | **382 / 0; 64.735 s** | **0** |
| Actual final offline configuration preflight | Configuration and mapping PASS; live NOT_TESTED | 0 |
| In-memory compilation | All 16 top-level Python modules | 0 |
| Whitespace / saved-original review | All five changed/new files passed; 37 original source/documentation files unchanged | 0 |

The strengthened test exposed quoted dictionary keys and request-object text that
could bypass the first draft's header detection. The final sanitizer omits those
messages; the same test and final full suite pass. No failing assertion was weakened.

The final full log contains **zero Python warnings**, zero ResourceWarnings and
zero ignored-exception messages. Three expected application WARNING entries say
that a scan was skipped because another scan was already in progress. Existing
failure fixtures also produce intentional application ERROR logs. The PowerShell
Tee-Object wrapper renders unittest stderr as NativeCommandError text; the actual
Python exit is 0. No warning filter or garbage-collection setting was relaxed.

The 21 new tests cover HTTP 400/401/403/404/418/429/500, both documented code spellings,
missing/invalid/nested fields, invalid encoding and duplicate JSON, bounded reads
including the exact size boundary, read/close failures, configured secrets and
URL-encoded variants, unconfigured bearer values, PII/header/request-field exclusion,
Unicode/terminal controls/multiline spoofing, redaction before truncation, sanitizer
failures, authentication/counter state, CLI failure details, stopping after a failed
quote, candle HTTP failures after a successful quote, and unchanged receipt/replay
restrictions. Existing tests cover network failures, allowlisting, valid data,
identity, timestamps, freshness, provenance and historical gates.

Exact validation commands executed:

```powershell
python --version
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxReadOnlyReadiness test_bot.TestConfigurationPreflight -v
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxHTTPErrorDetails test_bot.TestUpstoxReadOnlyReadiness test_bot.TestConfigurationPreflight -v
python -B -W error::ResourceWarning -m unittest test_bot.TestInstrumentIdentity test_bot.TestMarketDataFreshness test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B -v
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxHTTPErrorDetails.test_bearer_urls_headers_and_personal_fields_are_not_disclosed -v
python -B -W error::ResourceWarning test_bot.py -v
python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

The full command ran twice. Output was captured with `2>&1 | Tee-Object -FilePath`
into task-specific temporary logs and `exit $LASTEXITCODE` propagated Python's exit.
Compilation used `compile(path.read_bytes(), str(path), 'exec')` for every top-level
Python file. Final whitespace checks compare saved originals with current files
using `git -c core.autocrlf=false diff --no-index --check`, without a Git repository.
Windows test fixtures required execution outside the filesystem sandbox to access
temporary SQLite/configuration files and loopback test servers. These are offline
fixtures, not production server or broker acceptance runs.

## Actual before/after diagnostic evidence

The two actual configuration-only invocations returned the same safe results:

| Field / check | Before | After |
|---|---|---|
| Scope / config_only | LOCAL_CONFIGURATION_PREFLIGHT / true | Same |
| Configuration / instrument | PASS / PASS | PASS / PASS |
| Active broker / dry run / scheduler | upstox / true / false | Same |
| RELIANCE mapping | NSE_EQ\|INE002A01018 | Same |
| configuration_ready / overall_status | true / NOT_TESTED | Same |
| Authentication / quote / candles | NOT_TESTED / NOT_TESTED / NOT_TESTED | Same |
| Historical validity | NOT_ESTABLISHED | Same |
| Persisted / receipt / replay allowed | false / false / false | Same |
| JSON exit_code / observed process exit | 0 / 0 | 0 / 0 |

Source inspection and existing guarded preflight tests establish that this command
returns before adapter construction and cannot invoke the broker, store or receipt
producer. No fresh live diagnostic output or exit code exists for this run.
Mocked provider codes in the tests are fixtures; none identifies the real 403.

## Official documentation checked

Public documentation was accessed; no broker API, instrument download, profile,
OAuth, trading or account endpoint was called.

- [Full Market Quotes](https://upstox.com/developer/api-documentation/get-full-market-quote/)
  documents GET `/v2/market-quote/quotes`, the `instrument_key` query and bearer
  access-token authentication. These match the existing request construction.
- [Intraday Candle Data](https://upstox.com/developer/api-documentation/get-intra-day-candle-data/)
  documents the existing V2 path, bearer token and 1minute/30minute intervals, but
  marks the endpoint deprecated. Continued real availability is unverified. This
  task does not infer removal, migrate to V3 or attribute the quote 403 to deprecation.
- [Response Structure](https://upstox.com/developer/api-documentation/response-structure/)
  documents `status=error`, an `errors` array, `error_code`/`message`, and deprecated
  camelCase counterparts. Only the code/message are extracted here.
- [Authentication](https://upstox.com/developer/api-documentation/authentication/)
  distinguishes an API key/client identifier from the access token used in bearer
  requests. The existing adapter uses a pre-issued access token, not an API key in
  place of that token. No token exchange/refresh was added.
- [Error codes](https://upstox.com/developer/api-documentation/error-codes/)
  lists distinct invalid-credential/token, extended-token restriction, inactive
  client and other provider codes. None was observed from a real response here;
  the generic HTTP 403 entry cannot determine this account's root cause.

Gemini/Argon review artifacts were unavailable; no external AI review is claimed.

## Safety, remaining blockers and next step

No orders, trading-state modifications, production server startup, background
scheduler activation or live Telegram delivery occurred. Private settings were not
edited or displayed. Actual preflight confirms Telegram dry run true and scheduler
false. Tests use synthetic credentials and isolated stores. The endpoint allowlist,
data-validation policies and source/readiness gates remain intact; no acceptance
receipt was issued and LIVE historical replay and historical Strategy 3 remain
blocked. A future cash-equity pass would not prove full-account or F&O readiness,
historical provenance, replay eligibility or profitability.

The blocker to a provider diagnosis is missing fresh, authorized operational
evidence. There is no supported basis yet to change tokens, permissions, app
settings, endpoints or validation rules.

Next action, **only after separately authorizing a live read-only attempt**, is one
run from the project directory during a configured NSE session with completed
five-minute candles available:

```powershell
python -B .\upstox_diagnostics.py --symbol RELIANCE --json
$LASTEXITCODE
```

Review the sanitized JSON and immediate exit code. If the quote fails, candles must
remain NOT_TESTED. Use any returned provider code/message to justify the smallest
external corrective action; do not infer the cause from HTTP status alone or retry
in a loop. Full cash-path acceptance still requires all existing quote and completed
candle checks to pass, even when an authorized market-data response is observed.
