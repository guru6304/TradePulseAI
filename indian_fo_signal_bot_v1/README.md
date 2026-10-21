# TradePulse × OrderBlock AI — Indian Equity & Nifty/BankNifty F&O Signal Bot (Phase 3B)

Deterministic Python signal research, live-data diagnostic, historical data quality, and point-in-time backtesting system for **Indian Intraday Cash Equities (NSE)** and **Nifty 50 / Bank Nifty F&O**.

> **Important Scope & Safety Notice:**  
> - TradePulse AI is strictly a **read-only market analytics, signal research, and historical backtesting system** — **NOT** an automated order execution system. All order placement (`/order/*`) and GTT mutation (`/gtt/*`) routes are blocked in code.  
> - **Implementation Status:** Phase 3B.1B acceptance/readiness remediation. Offline results are recorded below; Python 3.14 HTTPError cleanup ResourceWarnings remain.
> - **Data Acceptance Status:** `BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED` inside the offline sandbox environment. Synthetic fixture runs are explicitly labeled `SIMULATED/TEST MODE` (`SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED`) and must never be represented as live-data acceptance or strategy profitability proof.

---

## Quick Start & Verification (Windows PowerShell)

### 1. Extract Archive & Initialize `.env`
```powershell
Expand-Archive -Path .\indian_fo_signal_bot_phase3b.zip -DestinationPath .	radepulse_phase3b -Force
Set-Location .	radepulse_phase3b\indian_fo_signal_bot_v1
if (-not (Test-Path -LiteralPath .\.env)) { Copy-Item .\.env.example .\.env }
```

### 2. Compile All Top-Level Modules in Memory & Run Offline Tests
```powershell
@'
from pathlib import Path
for p in Path('.').glob('*.py'):
    compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec')
'@ | python -B -
python -B -W error::ResourceWarning -m unittest -v test_bot.TestIndianFOSignalBotPhase3B1B
python -B -W error::ResourceWarning -m unittest -v test_bot.TestIndianFOSignalBotPhase3B1A
python -B -W error::ResourceWarning .\test_bot.py -v
```

### 3. Inspect Strategy Backtest Eligibility Matrix (Phase 3B)
```powershell
python .acktest_engine.py --eligibility
python .acktest_engine.py --eligibility --json
```

### 4. Run a Deterministic Backtest on a Synthetic Fixture (`SIMULATED/TEST MODE`)
```powershell
python .acktest_engine.py --strategy strat_1_order_block --symbol RELIANCE --data-mode SIMULATED --synthetic-fixture order_block_bull --capital 200000 --risk-pct 0.5 --slippage-bps 0
```

### 5. Run Phase 2C Live-Data Acceptance Diagnostics & Phase 3A Readiness Audit
```powershell
# Offline readiness check (zero network calls):
python .\diagnostics.py --offline
python .\historical_data.py --readiness --data-mode LIVE

# Live Angel One acceptance check (after filling ANGEL_* credentials in .env):
python .\diagnostics.py
```

### 6. Import Historical 5m Candles & Run a Historical Backtest from SQLite
```powershell
python -B .\historical_data.py --import-file .\reliance_5m_live.json --symbol RELIANCE --provider angelone --data-mode LIVE
python -B .\backtest_engine.py --strategy strat_2_vwap_pullback --symbol RELIANCE --provider angelone --data-mode LIVE --execution-scope HISTORICAL_RESEARCH --json
```

### 7. Start the Multi-Threaded HTTP Server & Query Backtest Endpoints
```powershell
python .\server.py
```
In a second PowerShell window:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/backtest-eligibility" | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/backtest" -ContentType "application/json" -Body '{"strategy_id":"strat_1_order_block","symbol":"RELIANCE","data_mode":"SIMULATED","synthetic_fixture_pattern":"order_block_bull"}' | ConvertTo-Json -Depth 6
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/backtest-runs" | ConvertTo-Json -Depth 6
```

---

## Phase 3B.1B acceptance and readiness contract

`LIVE` describes data provenance; it does not establish current broker acceptance.
The engine, readiness/eligibility endpoints and CLI use `readiness_policy.py`.
A supplied connection status, `phase2c_live_accepted`, manifest count or legacy
`require_live_acceptance_for_live_mode=False` cannot establish acceptance.

| Execution scope | Required evidence | Result label |
| --- | --- | --- |
| `SIMULATED_TEST` (default for SIMULATED) | Existing synthetic fixture validation; partial sessions remain useful for mechanics tests | `SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED` |
| `HISTORICAL_RESEARCH` (explicit, LIVE provenance) | Broker-sourced archive with complete sessions and strategy warmup | `HISTORICAL_RESEARCH_ONLY_NOT_LIVE_ACCEPTED` |
| `LIVE_ACCEPTED` (default for LIVE) | Same archive contract, persisted rows and a valid provider/symbol diagnostic receipt | `LIVE_DIAGNOSTIC_ACCEPTED_RESEARCH` |

`HISTORICAL_RESEARCH` authorizes archive research only. It never marks live acceptance
or whole-watchlist readiness. Direct/request candles cannot obtain the LIVE_ACCEPTED
label; that scope reads persisted history. Historical Strategy 3 remains unconditionally
blocked in every scope, even when option data, lot metadata or acceptance flags are supplied.

Coverage is recomputed from actual candles, independently of stored manifest counters.
The contract requires LIVE, one real provider (`angelone`, `dhan`, `upstox`), consistent
row provenance, five-minute completed candles, positive volume and every expected bar
of every configured trading session from the first through last stored session. With
09:15–15:30 hours this means 75 bars/session. Explicit evaluation boundaries must also
be covered. Configured holidays/weekends are excluded; omitted sessions are not filled.
Without explicit boundaries, readiness proves only the displayed stored date range.
Strategies 1/2/4 require at least 35 bars; Strategy 5 requires 200. Other existing strategy
eligibility restrictions still apply. A read exceeding the existing 10,000-row cap is
rejected as unverifiable; this package does not implement replay pagination.

`symbol_coverage` and strategy `DATA_READY` describe research inputs. The nonempty
configured equity watchlist has `aggregate_coverage_ready=true` only when every symbol
meets the 200-bar complete-session contract. `phase2c_live_accepted` describes valid
receipts for every configured equity. `phase3_ready_for_execution` requires both, in
LIVE mode, for OHLCV strategies 1/2/4/5 only. A symbol-specific `execution_gate` may allow
research while aggregate readiness remains false. These are intentionally different scopes.
Unbounded aggregate coverage refers to each symbol's displayed stored range; it does
not verify a common train/validation/out-of-sample study period or portfolio dataset.

A diagnostic receipt is produced only by a completed online Phase 2C diagnostic with
all nine checks PASS, observed authentication/profile, both index quotes and at least
200 completed positive-volume equity candles. It binds Angel One, the tested equity/token,
NSE/5m scope, session hours and configured holidays. The consumer revalidates retained
observations, timestamps, scope and required check outcomes. The history token,
exchange and equity segment must also match the receipt's scope. Quote evidence must
be within 20 minutes at observation; candle freshness uses the existing diagnostic policy.
Receipts expire exactly 30 minutes after observation; the expiry instant is rejected.
No TTL override exists. Different providers/symbols/calendar settings cannot reuse them.
Other providers currently support archive research only. Diagnostics test one equity per
run; a whole-watchlist live claim needs a current receipt for each configured equity.
A failed online diagnostic revokes that symbol's previous receipt. An offline diagnostic
cannot issue/renew a receipt; it may report the validity of an existing one.

Persistence adds only `live_acceptance_evidence` via `CREATE TABLE IF NOT EXISTS`.
Old databases keep their existing rows and start without receipts. Missing, malformed,
inconsistent, expired or unreadable records fail closed. Recovery is to restore database
access and rerun authorized diagnostics, never to hand-edit an accepted status. No
credentials, session tokens or client identifiers are stored in receipts.

The trust boundary includes local application code, diagnostic transport and SQLite
writers. There is no receipt-upload or acceptance-override API. SHA-256 detects accidental
corruption, **not authenticity**: local code/DB writers can forge internally consistent
records, and mocked transport can simulate diagnostic success. Archives also rely on
trusted ingestion for truthful provenance. Offline tests prove software behavior only;
no real broker acceptance or profitability is claimed. Normal scanner freshness, broader
instrument identity, API authentication, accounting and LIVE/SIMULATED state isolation
remain separate remediation packages.

The header distinguishes provider connectivity from persisted acceptance evidence.
`LIVE ACCEPTANCE EVIDENCE VALID` requires receipts for the configured watchlist; it does
not claim historical coverage. The dashboard's existing hypothetical performance view
is unchanged and is not evidence from this backtest engine.

All verification commands above are offline (the full suite uses localhost HTTP fixtures).
`python -B .\diagnostics.py --offline` and historical readiness/eligibility/replay do not
contact brokers. **`python -B .\diagnostics.py` without `--offline` can contact Angel One**;
it was not executed against a real broker in this package. Existing docs below describe
earlier milestones and are not current operational acceptance evidence.

Verification on Python 3.14.6: all 25 Phase 3B.1B tests and all 14 Phase 3B.1A tests
passed. The strict full suite ran 140 tests: 139 passed, one failed because the legacy
SQLite GC warning assertion collected an unclosed `HTTPError 503` from an earlier
fixture. Other HTTPError finalizer ResourceWarnings were also printed. This is not a
warning-free full-suite pass. A standalone stdlib reproduction emits that warning for
an unclosed HTTPError and none when explicitly closed; unrelated cleanup is unchanged.
All 12 top-level Python modules compile in memory. This extracted workspace has no
Git metadata; review uses a saved baseline and an equivalent added-line whitespace check.

---

## Live candle freshness

Angel One, Dhan and Upstox candle reads share the live freshness policy. Raw live
timestamps require an explicit UTC offset or UTC epoch; normalized local strings
carry an explicit Asia/Kolkata convention. Candle timestamps denote bar opens.
Duplicates, mixed ordering, off-grid/session timestamps, intraday gaps, malformed
OHLCV and synthetic provenance are rejected before signal evaluation. Upstox's
newest-first source order is reversed explicitly before aggregation.

`LIVE_CANDLE_MAX_DELAY_SECONDS` defaults to `60`: the latest completed candle's
close may lag the clock by at most one candle interval plus that allowance.
`LIVE_CANDLE_FUTURE_SKEW_SECONDS` defaults to `5`: timestamps beyond that tolerance
are rejected; tolerated future/forming candles still cannot count as completed.
Both settings must be finite and non-negative and appear in safe configuration
output. An explicit legacy maximum-age argument may tighten this policy.

New live signals require the current configured weekday session, including its
opening time and excluding its closing time (normally 09:15 <= IST < 15:30).
Before the first completed bar, scans fail closed. Outside the session, adapter
reference reads may use the most recent trading session's actual closing bar;
manual and scheduled live scans skip without generating signals. Health reports
each instrument separately and rechecks age; connection success is not freshness.

The calendar covers weekends and `NSE_HOLIDAYS` only. It does not discover exchange
holidays or special sessions; operators must supply accurate calendar settings.
Historical ingestion/replay retain their explicit period-validation rules.
Simulation remains usable and is never reported as verified live candle evidence.

## Instrument identity policy

Live requests use exact provider-specific mappings for NIFTY, BANKNIFTY and the
15 checked-in NSE equities. The reference comes from the `BotConfig` dataclass
defaults, independent of runtime configuration. Its provenance is labelled
`CHECKED_IN_BOTCONFIG_REFERENCE_V1`; this package did not verify those mappings
against a real broker. Explicit index aliases and the equity `-EQ` suffix resolve
at adapter lookup boundaries. Scanner universes must contain unique canonical
symbols, so aliases cannot create separate state entries for one instrument.

Angel master records may add NSE equities and NIFTY/BANKNIFTY OPTIDX contracts.
Conflicting names/tokens, duplicate assignments, incomplete contracts, fractional
lots, unsupported multipliers and expired selected contracts fail closed. Option
symbols must agree with the recorded underlying, expiry, strike and CE/PE side;
both existing two-digit and four-digit year forms are accepted. Master content
has a SHA-256 revision and load time; neither establishes historical validity.
Option quantities use the master lot only when it agrees with configuration;
the existing sizing formulas and unit premium multiplier remain unchanged.

Quotes must match their requested batch, exchange, token and echoed symbol.
Candle adapters check identity fields when the response supplies them and carry
the validated identity through aggregation, scanner checks and signal storage.
Bare OHLCV responses are labelled `REQUEST_BOUND_NO_ECHO`; they cannot independently
prove the broker returned the right instrument. Echoed fields are checked, never
silently replaced. Freshness remains a separate mandatory check.

Live index spot candles cannot authorize futures proposals: there is no supported
live futures master/contract-candle resolver. Dhan/Upstox option chains remain
analytical inputs and cannot authorize Option Apex signals without a supported
option-master/lot resolver. Angel option proposals carry the exact master contract
symbol, token, expiry and provenance through persistence and alert deduplication.
The new `signals.instrument_identity_json` column is additive; legacy rows retain
an empty identity and are not promoted to verified status.

LIVE historical replay additionally requires an ingested, date-appropriate master
archive. The archived-master workflow below replaces the previous bare-envelope
input contract. Coverage and Phase 2C receipt gates retain their existing meaning;
neither replaces instrument provenance checks. Historical Strategy 3 remains
unconditionally blocked in every mode.

Offline verification for this identity package on Python 3.14.6: 32 focused identity
tests, the 140-test safeguard selection and the complete strict suite (250/250) pass.
All 13 top-level modules compile in memory; all 11 changed/new files pass saved-baseline
whitespace checks. Python warning count is zero; three expected application warnings
come from scan-overlap tests. The three SQLite migration/concurrency checks also pass
in a separate authorized run outside the Windows sandbox. No external broker or
Telegram access, order placement or real broker identity verification occurred.

## Archived instrument masters

`instrument_archive.py` imports supplied local files only. No download, credentials,
signature verifier or new provider adapter is introduced. The normalized V1 JSON
schema supports the existing `angelone`, `dhan` and `upstox` provider namespaces.
Native Angel JSON lists reuse the existing strict master parser for its supported
NSE equities, indices and OPTIDX contracts. Native Dhan/Upstox schemas, CSV, ZIP and
other file formats are unsupported. Undated native Angel snapshots and legacy
`ARCHIVED_PROVIDER_MASTER` envelopes are retained as `INCOMPLETE`; their load,
capture or file modification timestamps never establish historical applicability.

The following is a schema template, not a dated broker mapping. Replace placeholders
only with records and effective intervals supported by your source evidence:

```json
{
  "schema_version": "tradepulse.instrument-master.v1",
  "provider": "angelone",
  "records": [{
    "symbol": "<canonical symbol>",
    "identifier": "<provider identifier>",
    "exchange": "NSE",
    "instrument_type": "EQ",
    "multiplier": 1,
    "valid_from": "<source-declared YYYY-MM-DD>",
    "valid_to": "<source-declared YYYY-MM-DD>"
  }]
}
```

EQ requires NSE/unit shares; INDEX_SPOT requires a supported index. FUTIDX and
OPTIDX require NFO, matching index underlying, ISO expiry, an exact positive integer
lot and explicit unit multiplier. OPTIDX additionally requires positive strike and
CE/PE side. Contract validity cannot extend beyond expiry. Expired-today contracts
can describe earlier periods; current mappings are never substituted for dated
source records. Spot identifiers cannot authorize derivative execution. Storing
option metadata does not enable historical Strategy 3.

| Evidence | Meaning |
|---|---|
| Original bytes and `original_sha256` | Exact ingested artifact, stored as a SQLite BLOB; calculated locally before parsing. |
| Normalized records/hash, schema/parser version, counts and validation result | Locally calculated interpretation, separate from original-byte integrity. |
| `source_reference`, optional HTTPS `source_url` | User-supplied source descriptions. A URL is never fetched or treated as authenticity proof. |
| Optional capture/publication timestamps | Separate user-supplied claims requiring explicit timezone offsets. |
| `ingested_at` | Locally calculated UTC timestamp; the first timestamp survives retries. |
| Record `valid_from`/`valid_to` | Source-declared inclusive calendar-date coverage; not independently authenticated. Missing bounds do not inherit capture dates. |
| `publisher_authenticity` | Always `NOT_ESTABLISHED`. No field in this package is independently authoritative publisher evidence. |

The retained `ELIGIBLE_LOCAL_RESEARCH` status is the previous package's structural
classification only. Existing archive records are not rewritten. It is no longer
sufficient for LIVE historical replay: current eligibility also requires independent
source attribution/authentication and authoritative instrument-specific effective-date
evidence. No supported verifier or qualified historical source is currently available,
so existing declaration-only archives are ineligible. Neither a pinned ID, a supplied
URL, a saved verdict nor a `verified` field bypasses this requirement.

`REJECTED` and `INCOMPLETE` archives remain unusable. Inline API/Python objects remain
labelled `INLINE_SERIALIZATION`: their digest covers the saved serialization, not an
unavailable original external file. Synthetic fixtures never acquire authenticated
external-source status. Historical Strategy 3 remains blocked in every mode.

Run these commands from the project directory in Windows PowerShell. They read local
files/SQLite only and cannot contact a broker. The input path must be inside the
explicit import root (default: current directory); traversal, network paths and
out-of-root symlinks are rejected. Original filenames are metadata, never write paths.

```powershell
$env:DATABASE_URL = 'sqlite:///research.db'
python -B instrument_archive.py --database $env:DATABASE_URL ingest master.json --import-root .\archives --provider angelone --source-reference 'Describe the actual source and evidence limitations'
python -B instrument_archive.py --database $env:DATABASE_URL list
python -B instrument_archive.py --database $env:DATABASE_URL show '<archive_id from ingestion>'
python -B instrument_archive.py --database $env:DATABASE_URL qualify '<archive_id from ingestion>'
# qualify returns exit code 1 with the exact missing evidence; the replay attempt also fails closed.
python -B backtest_engine.py --data-mode LIVE --provider angelone --execution-scope HISTORICAL_RESEARCH --instrument-archive-id '<archive_id from ingestion>' --json
```

Optional ingestion flags are `--captured-at`, `--published-at` (aware ISO timestamps)
and `--source-url` (descriptive HTTPS URL). Backtest CLI
`--historical-instrument-master master.json --instrument-import-root .\archives`
performs the same ingestion and preserves original bytes. Python/API callers can use
`historical_instrument_archive_id`, or submit a V1 object through the existing
`historical_instrument_identity` field. Supplying both is rejected. Without a pin,
replay checks stored declarations and source qualification; it never selects by newest
capture time. A resolved declaration alone cannot authorize replay.

The additive `instrument_master_archives` table retains immutable candidate IDs,
original bytes and provenance for successful, incomplete and rejected imports.
Repeated identical ingestion is idempotent. Changed bytes or provenance create new
evidence; previous records are never overwritten or automatically superseded.
Changing the original file or refreshing the live broker cache does not change a
stored archive. Existing signals, zones, receipts and backtest results are untouched.

Resolution rechecks stored bytes, normalized content and provenance. One record must
cover every dataset date, including warm-up. Coverage gaps and conflicts touching
any requested date fail closed; partial snapshots are not stitched. Identical facts
may corroborate each other, but conflicting eligible claims block even an explicitly
pinned archive. Provider namespaces remain separate. Each new LIVE backtest retains
its archive ID, original and normalized hashes, provenance and supporting archive IDs
in existing assumptions/trade metadata when execution is supported. The current source
gate prevents new LIVE replay before strategy evaluation. Later ingestion and source
assessment never rewrite prior results.

Offline verification commands:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestInstrumentArchives -v
python -B -W error::ResourceWarning test_bot.py -v
```

Archive-package verification on Python 3.14.6: 36/36 focused archive tests,
172/172 existing safeguard regressions and 286/286 complete strict-suite tests
passed with zero Python warnings. The full suite emitted three expected application
warnings from overlap-rejection fixtures. Five SQLite migration/restart/concurrency
checks passed separately in authorized execution outside the Windows sandbox.
All 14 top-level Python modules compile in memory; saved-baseline whitespace checks
pass for all six changed/new files. No real broker/Telegram access or orders occurred.
Local filesystem and SQLite writers remain inside the trust boundary; these hashes
are not cryptographic publisher authentication or protection against a database writer
who can alter both content and its recorded evidence.

## Historical source-evidence qualification

`source_qualification.py` assesses separate claims after storage revalidates original
bytes, normalization and archive identity. `qualify` performs local assessment only;
there is no automatic fetch, credentialed acceptance, signature verifier, manual
trust override or newly supported historical source. `ingest`, `show` and `list`
include the separate source assessment so the retained structural status cannot be
mistaken for current execution eligibility.

| Assessment | Established meaning in this checkout |
|---|---|
| Content integrity | Original/normalized content matches recorded local digests; this authenticates no publisher. |
| Source attribution | `USER_DECLARED` or legacy `UNKNOWN`; a URL or source description does not independently bind the file to a publisher. |
| Publisher authenticity | `NOT_ESTABLISHED`; supported verification mechanisms are currently empty. |
| Capture/publication time | `USER_DECLARED` when supplied, otherwise `UNKNOWN`. Local ingestion time is separately recorded and is not capture evidence. |
| Effective dates | `DECLARED_ONLY` or `UNKNOWN`; independently supported intervals are empty. |
| Historical eligibility | `allowed: false` with `HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT` and specific missing evidence. |

Source documentation reviewed on 2026-10-18:

| Provider | Public evidence reviewed | What remains unestablished |
|---|---|---|
| Angel | [SmartAPI documentation](https://smartapi.angelone.in/docs) was attempted; accessible content did not establish an authenticated historical master source. The existing native parser remains supported locally. | Submitted-file provenance, independent capture, authenticity and applicable historical intervals. |
| Dhan | [Provider instrument documentation](https://dhanhq.co/docs/v2/instruments/) identifies instrument CSV sources. This establishes documentation scope only; no master was downloaded. | Binding those sources to any submitted bytes, independent capture, authenticity and historical interval authority. |
| Upstox | [Instrument documentation](https://upstox.com/developer/api-documentation/instruments/) describes BOD files; [expired-futures documentation](https://upstox.com/developer/api-documentation/get-expired-future-contracts/) describes a contract API. No authenticated API call was made. | The origin/capture of local files, authoritative historical applicability and a supported evidence verifier. Native Upstox parsing remains unsupported. |

These observations do not prove that the providers lack other evidence mechanisms;
none was established for a local historical archive during this package. Public
provider documentation does not authenticate an operator-supplied file. No official
URL, provider name, claimed certificate or plausible publication date is accepted as
archive-specific proof.

For an evidence bundle obtained separately, preserve exact original bytes and retain
provider/exchange statements or acquisition records separately, without API secrets.
The evidence must bind the exact original digest (and any transformation) to the
publisher and establish instrument-specific applicability for every replay/warm-up
date. A publication date, contract expiry or capture timestamp alone is not such an
interval. Unsupported verification claims remain unvalidated; the application cannot
currently promote such a bundle to qualified status. Do not convert a failed LIVE
run to SIMULATED merely to bypass this gate. Synthetic regression research remains
available under its existing explicit simulation rules.

The additive `instrument_source_assessments` table retains archive-bound, versioned
assessments separately from original archive records. Repeated assessments are
idempotent. Stored verdicts are compared with freshly computed facts/policy before
use; changing a saved `allowed` flag cannot grant trust. Source qualification does
not update archives, past results, signals, zones or readiness receipts.

`inspect_archived_instrument_identity` supports declaration inspection and returns
`live_historical_eligible: false`; execution always uses the stricter resolver.
Existing gap/conflict checks remain in force and no conflict is resolved by choosing
the newest file. Readiness reports preserve receipt/coverage decisions separately as
`acceptance_coverage_ready_for_execution`, include `historical_source_qualification`,
and withhold overall `phase3_ready_for_execution` until source evidence is supported.
The receipt trust policy itself is unchanged.

Focused offline verification:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestSourceEvidenceQualification -v
python -B -W error::ResourceWarning test_bot.py -v
```

Source-qualification package verification on Python 3.14.6: 21/21 focused source
tests, 208/208 affected regressions and 307/307 complete strict-suite tests passed.
Python warning count is zero; the full suite emitted three expected application
warnings from scan-overlap fixtures. Seven SQLite migration/restart/concurrency
checks passed separately in authorized execution outside the Windows sandbox.
All 15 top-level modules compile in memory, and saved-baseline whitespace checks
pass for all six changed/new files. No credentialed broker, market-data, order or
Telegram calls occurred. Public documentation review was separate from offline tests.
`qualify` returns 1 for insufficient evidence; the backtest CLI retains its existing
eligibility-rejection exit code 2. No source or historical archive was authenticated.

## Official-source verifier feasibility

The [provider evidence and feasibility review](docs/OFFICIAL_SOURCE_FEASIBILITY.md)
records the public documentation examined on 2026-10-18, the six evidence dimensions
for Angel One, DhanHQ and Upstox, and all archived-master execution paths. All three
remain **BLOCKED for LIVE historical replay**: no defensible archive authenticator
and authoritative historical interval verifier was established. This package adds
offline regression protection and documentation; production policy is unchanged.
Read-only credentialed acceptance is a separate, conditional next step described
in the review. No broker acceptance was performed.

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestOfficialSourceFeasibility test_bot.TestSourceEvidenceQualification test_bot.TestInstrumentArchives -v
```

## Upstox read-only diagnostic preparation

The current [broker recovery engineering report](docs/BROKER_RECOVERY_ENGINEERING_REPORT.md),
[capability matrix](docs/TRADEPULSE_CAPABILITY_MATRIX.md) and
[remaining-work roadmap](docs/TRADEPULSE_COMPLETION_ROADMAP.md) distinguish tested
software from operational acceptance. Neither provider has passed a real cash-data
acceptance in this mission; LIVE replay and historical Strategy 3 remain blocked.

Angel One now has a narrow diagnostic in the existing diagnostics module. Provider
selection stays explicit: this preflight requires an already configured
`ACTIVE_BROKER=angelone`, existing valid local Angel credentials, Telegram dry run
and a disabled scheduler. It does not change settings or construct an adapter:

```powershell
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

With the current Upstox selection, the Angel preflight correctly returns BLOCKED
and exit 1. This does not establish whether Angel credentials or account access work.
After separate authorization and a passing preflight, the corresponding **live**
market-data command is:

```powershell
python -B .\diagnostics.py --market-data-only --symbol RELIANCE --json
$LASTEXITCODE
```

It uses the existing adapter: login if needed, one RELIANCE NSE cash quote and
five-minute candles only after quote identity/prices/observation freshness pass.
Existing session recovery is bounded to one recovery/retry; no profile, funds,
positions, option chain, scan, store, receipt, scheduler or Telegram path is called.
The legacy diagnostic without `--market-data-only` is a separate broader Phase 2C
workflow and is outside this minimum acceptance procedure.

Offline broker/contract tests are also independently runnable:

```powershell
python -B -W error::ResourceWarning -m unittest test_angel_market_data test_market_data_contract -v
```

The established `python -B -W error::ResourceWarning test_bot.py -v` command includes
these modules through its test loader; unittest discovery avoids duplicate cases.

The [configuration fix and current readiness matrix](docs/UPSTOX_CONFIGURATION_FIX_REPORT.md)
records the project-local configuration correction and current verification. The
project `.env` is the runtime file when commands run here; a parent `.env` is not
automatically loaded. An unchanged `.env.example` copy still selects `paper_sim`.
Existing process variables take precedence, so verify effective settings first.

The existing Upstox adapter now supports standalone V2 full quotes and a dedicated
one-instrument diagnostic. See [the implementation and verification report](docs/UPSTOX_READINESS_IMPLEMENTATION.md).
Successful live Upstox connectivity remains unverified; the user-reported attempt
failed with HTTP 403. See [HTTP error reporting and verification](docs/UPSTOX_HTTP_ERROR_REPORT.md).
The root `.gitignore` excludes local environment/credential files and preserves
`.env.example`. Task 3 verified this checkout's Git history and that its local `.env`
is ignored and untracked; see the [current forensic report](docs/reports/TRADEPULSE_TASK3_FORENSIC_STABILITY_AND_READINESS_REPORT.md).

Configure your local `.env` privately in `indian_fo_signal_bot_v1`: select
`ACTIVE_BROKER=upstox` and provide `UPSTOX_ACCESS_TOKEN` from an external authorized
OAuth token-issuance process. `UPSTOX_API_KEY` is read for compatibility but is unused
by the adapter; it is not an access-token substitute. No token exchange/refresh is
implemented. Existing process environment variables take precedence over `.env`.
Keep `TELEGRAM_DRY_RUN=true`, `ENABLE_BACKGROUND_SCHEDULER=false`, localhost binding
and your existing database configuration. Do not put credentials in command arguments.

First run this offline preflight (no adapter, broker request, persistence or receipt):

```powershell
python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

Proceed only when `configuration_ready` is true and the exit code is 0. Its overall
live status remains `NOT_TESTED`; configuration success is not broker acceptance.
Check `effective_configuration` for Upstox, Telegram dry run true and scheduler
false. If a process override changes these values, resolve it deliberately; the
loader never silently replaces environment settings.

**The following command contacts Upstox and requires separate authorization. It was
not run against Upstox during implementation.** Run from this project directory,
during a configured NSE session after completed five-minute candles are available:

```powershell
python -B .\upstox_diagnostics.py --symbol RELIANCE --json
$LASTEXITCODE
```

It performs one standalone quote GET followed by one intraday-candle GET for the
checked-in NSE cash key `NSE_EQ|INE002A01018`. It validates the entire returned candle
batch, then reports up to five completed candles (`--sample-size` accepts 1–10).
The intraday endpoint supplies its current-session batch; there is no invented
server-side sample-limit parameter. Requests have an eight-second timeout and an
eight-MiB response bound. Failed quote reads stop before the candle request.
HTTP failures additionally report `http_status` and, when safely extractable,
`provider_error_code` / `provider_error_message`. Error bodies have an eight-KiB
limit (plus one overflow-detection byte); only the first documented error is used.
Provider messages are sanitized, limited to one line and 240 characters, and may
be omitted when unsafe or unavailable. HTTP 403 alone does not identify its cause.
Task 3 migrated candle reads to the documented V3 route
`/v3/historical-candle/intraday/{instrument_key}/minutes/{interval}` while retaining
V2 full quotes and the existing `UpstoxV2Adapter` interface. Five- and fifteen-minute
bars still aggregate validated one-minute observations; thirty-minute reads request
thirty-minute observations. Identity, freshness and completion gates remain enforced.
See the [official V3 contract](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/).
Mocked transport verification does not establish real-provider availability.

Checks use `PASS`, `FAIL`, `BLOCKED` or `NOT_TESTED`; exit 0 requires every required
check to pass. Configuration presence is separate from successful authorized reads.
No profile check is claimed. Missing quote observation time blocks acceptance, and
the quote is rechecked after the candle request against the configured delay/skew
allowance. Closed-session reference candles cannot pass current-session acceptance.
Missing identity echo is disclosed as `REQUEST_BOUND_NO_ECHO`, not independent
instrument confirmation. The diagnostic writes no database records or receipts and
does not start a server, scanner, scheduler or Telegram sender. Angel diagnostics
and receipt restrictions remain separate; LIVE historical replay remains blocked.

Offline verification, using mocked transport only:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxReadOnlyReadiness -v
python -B -W error::ResourceWarning -m unittest test_bot.TestUpstoxHTTPErrorDetails -v
python -B -W error::ResourceWarning -m unittest test_bot.TestConfigurationPreflight -v
python -B -W error::ResourceWarning test_bot.py -v
```

The suite now isolates application environment defaults and does not import local
dotenv values. Private-file HTTP fixtures use temporary credential/database/public
paths, preserving real configuration and existing files. Tests do not establish
live connectivity or profitability.

## Repository Documentation Index

- [Phase 5A closeout and Phase 5B engineering evidence](docs/TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md): current offline implementation, verification, safety gates and remaining work.
- [F&O contract coverage](docs/TRADEPULSE_FO_CONTRACT_COVERAGE.md), [historical provenance design](docs/TRADEPULSE_HISTORICAL_PROVENANCE_DESIGN.md), and [durable paper portfolio](docs/TRADEPULSE_PAPER_PORTFOLIO_REPORT.md).
- Current weighted audit estimates are **63.5% implementation / 35.5% verified readiness**; **0/12** full product milestones accepted. Explicit cash paper accounts have offline evidence; live broker acceptance and qualified F&O/history remain separate.

- [Phase 4 engineering evidence](docs/TRADEPULSE_PHASE4_ENGINEERING_REPORT.md): fresh 429-test baseline, seven confirmed control fixes, final 461 passing offline tests and separately gated live acceptance.
- [Market-data acceptance matrix](docs/TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md): separate provider, quote/candle, cash/index/F&O and historical-evidence scopes.
- [Capability matrix](docs/TRADEPULSE_CAPABILITY_MATRIX.md) and [completion roadmap](docs/TRADEPULSE_COMPLETION_ROADMAP.md): current M01-M12 rubric, dependencies and next actions; the earlier Phase 4 estimates are retained in its report.

- `PHASE_3B_REPORT.md` (`docs/PHASE_3B_REPORT.md`) — Master Phase 3B implementation report, baseline comparison, and file change log.
- `PHASE_3B_TEST_REPORT.md` (`docs/PHASE_3B_TEST_REPORT.md`) — Complete 101-test verification output and SQLite `ResourceWarning` fix analysis.
- `PHASE_3B_STRATEGY_ELIGIBILITY.md` (`docs/PHASE_3B_STRATEGY_ELIGIBILITY.md`) — 5-strategy backtest eligibility matrix and Strategy 3 historical option-chain blocker documentation.
- `PHASE_3B_BACKTEST_METHODOLOGY.md` (`docs/PHASE_3B_BACKTEST_METHODOLOGY.md`) — Mathematical specification of point-in-time replay, next-candle open execution, conservative collision resolution, Indian market costs, position sizing, daily risk limits, and metrics.
- `docs/PHASE_3A_IMPLEMENTATION_REPORT.md` — Phase 3A historical dataset schema and look-ahead prevention audit.
- `docs/PHASE_2C_IMPLEMENTATION_REPORT.md` — Phase 2C Angel One live-data acceptance diagnostics and closing OI baseline provenance.
