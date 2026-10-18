# Upstox configuration fix, verification and roadmap

Date: 2026-10-18. Work performed in the existing project directory. No broker,
Telegram or trading requests were made. No live acceptance receipt was issued.

## Root cause and configuration source

Before editing, the project-root `.env` was byte-identical to `.env.example`.
It selected `ACTIVE_BROKER=paper_sim`, with Telegram dry run true and scheduler
false. There were no duplicate keys, malformed assignments or UTF-8 BOM in that
file, and no process override for those three settings in the inspected process.
A real `BotConfig()` invocation from the documented project directory reproduced
exactly those effective values. The immediate cause was the unchanged template
value, not an Upstox authentication response.

`config.py:50-65` loads `.env` relative to the current working directory and uses
`os.environ.setdefault`; `BotConfig.__post_init__` reads the resulting environment.
Therefore existing process values win, duplicate file keys retain their first
value, and no parent file is searched. `_load_dotenv` has one automatic invocation;
other application modules consume `BotConfig`. There is no justification for a
global Upstox default, automatic parent fallback or environment override.

The separate parent `.env` selected Upstox and contained non-placeholder Upstox
values. It also contained malformed lines and repeated safety-setting keys, but
it was not consulted by the project-directory invocation. Its contents were not
printed or copied into reports. Only its two existing Upstox values were copied
locally into the corresponding project-root placeholders. Existing non-placeholder
local credentials would have been preserved. The parent file was left unchanged.

Only `ACTIVE_BROKER`, `UPSTOX_API_KEY` and `UPSTOX_ACCESS_TOKEN` lines changed in the
private project `.env`. The existing safe Telegram/scheduler settings already
matched requirements. Every other line, including database configuration, was
preserved. No secret-bearing backup, fixture or report was created.

The loader is unchanged. Its simple assignment/quote handling is not a shell
interpreter: malformed non-assignment lines are ignored and inline comments on a
broker value are not removed. Tests verify that such an invalid broker value is
rejected rather than silently promoted. These parser limitations did not cause the
observed project-file failure. A different terminal's environment may still differ;
the offline preflight must verify that terminal's effective settings.

## Minimal implementation and effective result

`upstox_diagnostics.run_upstox_diagnostics(..., config_only=True)` and CLI flag
`--check-config` reuse the existing configuration and RELIANCE mapping checks,
then return before constructing an adapter. Output exposes only three effective
settings, with invalid broker strings replaced by `INVALID`. A ready offline
configuration exits 0 with `configuration_ready=true` and overall live status
`NOT_TESTED`; it never reports a live PASS from local configuration alone.

Actual local preflight result:

| Check | Observed result |
|---|---|
| Effective active broker | `upstox` |
| Telegram dry run | `true` |
| Background scheduler | `false` |
| Configuration / pinned instrument checks | PASS / PASS |
| Instrument | RELIANCE, `NSE_EQ|INE002A01018` |
| Authentication / quote / candles | NOT_TESTED / NOT_TESTED / NOT_TESTED |
| Overall live status | NOT_TESTED |
| Configuration ready / actual process exit | true / 0 |
| Data persisted / receipt issued / historical replay allowed | false / false / false |

The access token remains a pre-issued bearer token. The API key is read but unused
by adapter requests. No OAuth issuance/refresh, profile endpoint, new provider,
instrument scope, freshness tolerance or execution gate was added.

## Baseline failure and test isolation

The requested pre-edit full suite actually ran **348 tests: 347 passed, one failed**.
`TestIndianFOSignalBotPhase1C.test_p1c_backward_compatibility_and_scanner_bidirectional_dispatch`
observed one order-block signal where its unchanged assertion requires at least
two. Local `.env` had introduced a file-backed default database, allowing earlier
fixture state to contaminate later tests. This failure was reproduced before any
implementation edit; it was not evidence of a strategy or broker failure.

The baseline also emitted an unclosed-file ResourceWarning in the old Phase 1D
security fixture. That fixture read the real project `.env` without closing the
reader, temporarily rewrote it with a canary, and cleaned up a project database.
The baseline project `.env` still contained only template placeholders and was
restored by that fixture. No application database existed in the initial snapshot;
the legacy cleanup left no new database behind. This test behavior was unsafe
once users configure real credentials or maintain a real database.

The suite now seeds application environment variables from literal source defaults
and bypasses the automatic local-dotenv probe only while initially importing
`config` for tests. Production loader behavior is unchanged. Tests use in-memory
defaults unless they explicitly request isolated temporary persistence. Loader
tests exercise the real loader in temporary working directories/subprocesses.

The two private-file HTTP tests now create credential/database/public-file fixtures
in temporary directories. They no longer back up, overwrite or remove the user's
`.env`, application database or existing public files. The public HTML fixture uses
the actual checked-in HTML. All existing security/strategy assertions were retained.
The three directly affected scanner/security tests passed separately after this
change, and the strict full suite passed without the baseline resource warning.

Thirteen new `TestConfigurationPreflight` tests cover template defaults, project
versus parent lookup, missing dotenv, process precedence, duplicate/quoted keys,
malformed broker values, explicit loader paths, correct/unsafe preflight gates,
CLI exit codes, redacted invalid settings and test isolation from local/process
credentials. The existing 28 mocked Upstox tests retain quote/candle validation,
aggregation, authentication evidence, HTTP errors/timeouts/rate limits, identity
echo limitations, secret-free errors and forbidden-side-effect guards.

## Files and functions changed

| Path relative to project | Change |
|---|---|
| `.env` (private, ignored) | Three local setting/placeholder replacements; all other lines preserved. Values withheld. |
| `upstox_diagnostics.py` | `run_upstox_diagnostics`: safe effective-setting snapshot and offline early return; `finish`: explicit configuration-only outcome; `main`: `--check-config` routing. |
| `test_bot.py` | Module initialization isolates application defaults/local dotenv; Phase 1D and Phase 1E private-file HTTP fixtures use temporary paths; new `TestConfigurationPreflight` with `_effective` helper and 13 tests. |
| `README.md` | Non-overwriting template-copy instruction, offline preflight, immediate exit-code checks and isolation explanation. |
| `docs/UPSTOX_READINESS_IMPLEMENTATION.md` | Follow-up link; previous milestone results retained as historical results. |
| `docs/UPSTOX_CONFIGURATION_FIX_REPORT.md` | This report, current evidence and roadmap. |

The root `.gitignore`, placeholder `.env.example`, `config.py`, brokers, scanner,
strategies, accounting/backtest engine, storage/schema, identity/archive/source
qualification, freshness functions, server, Angel diagnostics, receipt policy and
Telegram implementation retain their baseline bytes. No repository was initialized.
Ignore rules are checked with Git in a separate temporary test repository; tracking
status remains unavailable in this exported workspace without Git metadata.

## Verification performed

Python 3.14.6, PowerShell, from the existing project directory:

| Run | Actual result |
|---|---|
| Baseline strict full suite | 347 passed, 1 failed; one unclosed-file ResourceWarning; 60.832 seconds |
| Directly affected scanner/security fixtures | 3 passed, 0 failed |
| Configuration preflight + mocked Upstox | 41 passed, 0 failed |
| Identity, provenance, freshness and historical gates | 171 passed, 0 failed; 22.395 seconds |
| Separate SQLite migration/restart/concurrency | 9 passed, 0 failed |
| Final strict full suite | **361 passed, 0 failed; 66.024 seconds** |
| Actual offline local preflight | Configuration ready, live NOT_TESTED; process exit 0 |
| In-memory compilation | 16 top-level modules passed; no bytecode artifacts |
| Saved-original whitespace checks | 5 non-secret changed/new files passed |
| Baseline/security review | 38 original non-secret files unchanged; protected modules and root ignore unchanged; configured Upstox values absent from changed sources/reports/test logs |

The final full suite emitted **zero Python warnings**, including zero ignored
resource warnings. Three expected application warnings reported skipped overlapping
scans. Intentional failure fixtures also log errors. No warning filters or
assertions were weakened. The PowerShell Tee-Object wrapper renders unittest stderr
as NativeCommandError text; the final Python process returned 0.

Commands actually run (full-suite output was retained temporarily through Tee-Object
with the Python exit code propagated):

```powershell
python -B -W error::ResourceWarning test_bot.py -v
python -B -W error::ResourceWarning -m unittest test_bot.TestConfigurationPreflight test_bot.TestUpstoxReadOnlyReadiness -v
python -B -W error::ResourceWarning -m unittest test_bot.TestInstrumentIdentity test_bot.TestMarketDataFreshness test_bot.TestInstrumentArchives test_bot.TestSourceEvidenceQualification test_bot.TestOfficialSourceFeasibility test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B -v
```

The three direct fixtures were Phase 1C backward compatibility/bidirectional
dispatch, Phase 1D private-file HTTP protection, and Phase 1E public/private serving.
The nine SQLite checks were source-assessment restart/concurrency, archive
restart/concurrency, state migration/concurrent writers/concurrent startup, Phase
2B rollback/concurrent baseline access, and Phase 3B.1B later-store revalidation.
These are the existing named methods in `test_bot.py`; no schema change was needed.
The exact SQLite command was:

```powershell
python -B -W error::ResourceWarning -m unittest test_bot.TestSourceEvidenceQualification.test_restart_preserves_versioned_assessment_and_additive_migration test_bot.TestSourceEvidenceQualification.test_policy_assessments_are_idempotent_under_concurrent_startup test_bot.TestInstrumentArchives.test_restart_and_additive_migration_preserve_existing_rows_and_archives test_bot.TestInstrumentArchives.test_concurrent_startup_and_idempotent_ingestion_preserve_evidence test_bot.TestStateIsolation.test_legacy_migration_is_additive_deterministic_and_fails_closed test_bot.TestStateIsolation.test_concurrent_database_writers_dedup_without_cross_scope_mutation test_bot.TestStateIsolation.test_concurrent_schema_initialization_is_safe test_bot.TestIndianFOSignalBotPhase2B.test_p2b_sqlite_transaction_rollback_and_concurrent_baseline_access test_bot.TestIndianFOSignalBotPhase3B1B.test_later_store_instance_revalidates_evidence_and_additive_migration -v
```

Compilation used `compile(path.read_bytes(), str(path), 'exec')` over all top-level
modules. Whitespace checks used `git -c core.autocrlf=false diff --no-index --check`
against saved original bytes, with an empty original for this new report. Private
`.env` was checked through whitelisted settings and in-process preservation checks,
never through a raw diff. No secret values were retained in the baseline snapshot.

Full/focused temporary-filesystem tests ran in authorized execution outside the
Windows sandbox. Local HTTP fixture traffic is not broker acceptance.

## Evidence-based readiness matrix

| Capability | Implemented/tested evidence | Current operational status |
|---|---|---|
| Configuration and offline RELIANCE mapping preflight | Actual local process and 13 new configuration tests | PASS for local prerequisites only |
| Upstox authorized market-data response | Existing bearer GET transport; mocked success/failure and token-change tests | NOT_TESTED against real Upstox |
| Standalone RELIANCE quote, identity and time | Existing full-quote endpoint; mocked payload/echo/price/time validation | NOT_TESTED live; missing echo remains request-bound |
| Intraday candles and five-minute aggregation | Mocked order/grid/gap/OHLCV/completion/freshness checks | NOT_TESTED live; full-session coverage is not implied by a sample |
| Current instrument-master authority | Checked-in pins and identity consistency checks | Authoritative current master provenance unverified |
| Historical archive authenticity and effective intervals | Integrity/declaration assessment and fail-closed tests | BLOCKED; no supported independent verifier established |
| LIVE historical replay | Engine and receipt/coverage/source gates tested | BLOCKED by independent source requirements |
| Historical Strategy 3 | Existing explicit containment tests | BLOCKED |
| Upstox futures/options execution identity | Analytical chain/expiry reads exist; no supported live contract-master/lot resolver | BLOCKED for execution readiness; no F&O acceptance performed |
| Strategy structure/momentum/quality scoring | Five evaluators, BOS/FVG/technical calculations and deterministic fixture tests | Implemented research code; real-data performance/profitability unverified |
| Dashboard, persistence, risk/accounting, Telegram recommendations | Existing offline/regression evidence | Implemented components; live delivery/operational product acceptance unverified; dry run/scheduler restrictions retained |
| End-of-day reporting and full F&O ranked product | Intended roadmap, not established by this package | UNVERIFIED; no completeness claim |
| Upstox readiness receipt / full account / trading readiness | Current policy remains Angel-specific; diagnostic never issues receipts | Not established or authorized by this diagnostic |

No Gemini or Argon review artifact was available in the workspace or supplied
conversation. Existing implementation, source-feasibility and audit reports were
reconciled with source, runtime configuration and current tests; they were not
treated as live operational evidence. Valid recommendations to retain architecture,
keep provenance separate, preserve gates and avoid synthetic profitability claims
remain in force.

## Next phase and exact next actions

The smallest dependency-complete software step was the offline configuration
preflight and test isolation implemented here. The next dependency is an actual,
separately authorized RELIANCE cash-data acceptance observation. No broader broker
implementation, OAuth refresh, F&O recommendation or strategy optimization is
justified before that evidence. Fix any resulting failure only after its sanitized
output identifies the failing layer.

Use separate short PowerShell commands to avoid the prior PSReadLine multiline
rendering issue. That console exception is not a Python application diagnosis.

First, offline:

```powershell
Set-Location 'C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1'
python -B .\upstox_diagnostics.py --symbol RELIANCE --check-config --json
$LASTEXITCODE
```

Stop if `configuration_ready` is false or the process exit is nonzero. Resolve any
reported environment override deliberately; do not silently replace environment
values. A different terminal may have different process overrides.

Only after separate authorization, during a configured NSE trading session with
completed five-minute data available:

```powershell
python -B .\upstox_diagnostics.py --symbol RELIANCE --json
$LASTEXITCODE
```

Provide only the sanitized report and actual process exit code for evidence review.
No live request was made in this package. A configuration failure leaves broker
authentication untested; an authorized response does not prove quote/candle
validity, full account readiness, source qualification, historical eligibility or
trading readiness. No acceptance receipt or historical unblocking follows from
a cash quote success.
