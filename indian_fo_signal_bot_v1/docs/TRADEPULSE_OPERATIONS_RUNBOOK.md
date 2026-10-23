# Local testing, recovery and release operations

Keep the [execution ledger](TRADEPULSE_EXECUTION_LEDGER.md) as the continuation
checkpoint. These commands do not authorize broker requests or real trading.

## Repeatable offline testing

Use the application directory with Python and Node installed. Signature verification
now requires the pinned runtime dependencies. On this Windows checkout the tested
interpreter is `.venv_phase4\Scripts\python.exe` (Python 3.14.6). For a new isolated
installation, run `python -m venv .venv_phase4`, then
`.venv_phase4\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt`.
Use that same interpreter for verification; a base interpreter without cryptography
cannot pass the genuine signature tests. There is no mocked cryptographic fallback.

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage operator_001
$LASTEXITCODE
.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_operator_001.json
$LASTEXITCODE
```

Use a new stage name each time. The command starts and stops only local test
servers with credential-free deterministic fixtures and temporary SQLite stores.
It executes the established unified suite, actual dashboard JavaScript tests,
syntax and compilation. It records actual IDs/counts and hashes. An old PASS does
not validate a changed source version. Exit nonzero must be investigated; do not
delete/skip assertions or relabel an intermediate log as final.

`python -B configuration_check.py` is a separate zero-disclosure local preflight.
PASS establishes local configuration only. Keep the current requested paper_sim, Telegram dry-run true,
scheduler false and localhost. Never put secrets in arguments, reports or fixtures.

## Pending accepted cash work

Inspect `store.pending_cash_scans(limit=100)` in the intended explicit database.
Input commit is not result commit. Resume with the matching original code/runtime,
nonsecret execution configuration and `engine.resume_cash_scan(run_id, paper_portfolio=...)`.
The same paper account/store must be supplied when continuing a paper handoff.
Recovery uses retained acceptance time and does not fetch current data or deliver
notifications. Inspect the original result on idempotent replay rather than treating
its zero new signals as a new empty scan.

A different pending input for the provider must wait for earlier recovery. Do not
delete pending work or manually edit consumed zones to bypass it. A code/config
mismatch or digest/reconciliation failure requires investigation or a separately
reviewed migration. Current freshness must come from a later separately authorized
fresh acquisition; retained input does not establish it.

Read-only inspection routes: `/api/scan-lineage?run_id=...`,
`/api/cash-candles?run_id=...&batch_id=...&limit=100&offset=0`, `/api/signals`,
`/api/paper-portfolio?account_id=...`, `/api/paper-ledger?account_id=...` and
`/api/paper-session?account_id=...&session_date=YYYY-MM-DD`. No GET creates a paper
account, marks a position or invents a missing final observation.

## Native contract inspection cache

Supply an operator-obtained local native JSON or bounded gzip file. No CLI download
or provider switch occurs:

```powershell
python -B contract_universe.py --file LOCAL_NATIVE_FILE.json --database LOCAL_TEST.sqlite --captured-at AWARE_CAPTURE_TIMESTAMP --source-reference PUBLIC_SOURCE_REFERENCE --source-version SOURCE_VERSION
$LASTEXITCODE
```

The source reference and timestamp are supplied claims. PASS means an internally
consistent same-date inspection cache was stored, not that its source is authentic,
historically qualified or executable. Invalid/older/conflicting refreshes retain
the last-good pointer and rejection history; a stale last-good cache cannot be
promoted to current. Review exact master IDs and terms; no automatic rollover or
lot/expiry inference is permitted. Qualified dated source acceptance is separate.

## Historical replay boundaries

Stored snapshots use insertion watermarks and ordered pages. Resumable cursors
exclude later inserts and reject changed/deleted original rows. The backtest engine
loads a consistent snapshot beyond 10,000 bars; its explicit 250,000-bar in-memory
resource bound fails closed. Gaps, source/provenance, complete-session and qualified
history gates remain. Snapshot hashes establish integrity only.

No actual historical option execution is accepted without exact dated contracts,
qualified observed option premiums and an implemented execution model. Underlying
prices, model premiums and unqualified declarations cannot substitute for those.

## Paper soak acceptance policy

The local deterministic qualification minimum is three trading sessions with exact
event/capital/fee/position reconciliation, including a restart with queued work,
interrupted transaction and repeated callback, a provider/outage interval, missing
required EOD observation, and a later explicit recovery. Every injected failure
must leave an auditable state; no duplicate position/fee/capital effect is allowed.
Measured fixtures and expected prices must be retained. Existing recovery and
continuous-acceptance suites exercise these mechanics; their final execution and
exact supported scenarios are recorded in the ledger. This is not a real-session
soak or a latency/availability SLA.

Real operating soak remains pending an agreed environment/session calendar and
owner-approved scenario schedule. Require at least three declared consecutive
market sessions, zero unexplained ledger differences, no stale/rejected candidate
shown as accepted, no duplicate financial/delivery effect, complete EOD or explicit
unresolved status, and successful backup/restore/recovery inspection. Missing final
prices retain real reservations/open positions; do not invent square-off fills or
automatically approve financial repairs.

## External read acceptance gate

The operator must privately confirm the intended account/environment and locally
verified credential/permission scope, then explicitly authorize exactly one
read-only RELIANCE quote GET and one candle GET. No orders, refresh, broad scanning,
background jobs, portfolio mutation or unrelated provider calls are included.
Without that precise authorization record BLOCKED_PENDING_OPERATOR_AUTHORIZATION
and continue offline work. Never request or print a secret in chat.

## Local access and stored reporting

Serve the dashboard from the server's own `http://127.0.0.1:PORT/` origin.
Requests require a loopback peer and loopback Host matching the listening port;
foreign Origin/Host and cross-site browser requests receive 403 before engine
initialization. Opening the HTML directly as `file://` or hosting it on a separate
origin is not supported by this local security profile. Deployment beyond loopback
requires a separately designed authenticated proxy/profile; do not relax the guard.

The System Health tab has a manual **Read stored reports** button. It reads the
explicitly attached paper account, optional entered EOD date, five retained backtest
runs and notification state. It never creates accounts or calls a scan/fill/sender.
No account means no account automatically selected. Failed reads remove old values.
Reconciliation failure hides accounting. EOD before session end or missing observations
remains unavailable/unresolved. The separate friction calculator stays hypothetical.
The renderer tests use actual HTTP payloads and a DOM double, not visual acceptance.

`GET /api/notification-outbox?limit=100&status=RETRY` lists metadata (limit 1-200).
`GET /api/historical-candle-pages?symbol=RELIANCE&data_mode=SIMULATED&provider=offline_fixture&limit=100`
returns a snapshot and `next_cursor` (limit 1-10,000). Continue with identical filters
and URL-encoded cursor; changed original rows or mismatched scope fail closed.
No route performs provider acquisition or historical-source qualification.

Health operational alerts distinguish pending cash recovery, notification previews
requiring attention, stale candles, provider errors and paper reconciliation failures.
Storage/reconciliation failures return 503. These are local observations, not central
alerting, broker authentication or an availability SLA. A pending-count preview is
capped at 200; an absent recent-process scan is not a complete historical job audit.

## Durable notification previews

Only `LOCAL_PREVIEW_ONLY` is implemented for durable cash intents. An intent commits
with its scan result. Normal dry-run processing records a preview receipt afterward;
lost acknowledgement/restart can reuse the same receipt. Recovery does not dispatch.
No destination, credentials, live sender or background worker is attached.

To explicitly resume a local preview in the intended test store, call
`store.preview_notification(intent_id, now=aware_reference)` after inspecting its
committed scan and immutable candidate. This is a write to the preview audit only.
Failures back off 5s then 10s, stop at three attempts (DEAD), and never claim delivery.
Do not alter SQL state to reset DEAD or turn an acknowledgement into real delivery.
Investigate retained attempt reasons/payload hashes and require a reviewed retry
policy for any new action. Real Telegram delivery remains unauthorized and untested.

## Reproducible release and rollback drill

Run the full verification first and validate its source-bound evidence. Then, from
the application directory, choose a new artifact name:

```powershell
python -B release_management.py bundle --output tradepulse_candidate_001.zip
$LASTEXITCODE
python -B release_management.py inspect --archive tradepulse_candidate_001.zip
$LASTEXITCODE
python -B release_management.py restore-drill --backup LOCAL_ISOLATED_BACKUP.db --as-of AWARE_REFERENCE_TIMESTAMP
$LASTEXITCODE
```

The artifact contains allowlisted application/public/template/test/runbook files
and `RELEASE_MANIFEST.json`, with fixed ZIP ordering/timestamps and SHA-256 bindings.
It excludes `.env`, databases, evidence logs and private deployment state. Build
refuses an existing destination. Inspection reads without extracting and rejects
unexpected paths, links, duplicates, size excess and changed file bytes. Hashes do
not prove publisher identity; retain the externally reviewed release hash separately.

After successful inspection, extract into a new isolated directory. Supply no live
credentials. Run its `verify_offline.py --stage clean_candidate_001` and validate
that new evidence before considering activation. Automated packaging tests extract
the candidate and load all unique test cases; this is bootstrap evidence, not an
additional full runtime matrix. Dependencies are Python stdlib and Node for tests;
dashboard third-party CDN assets still require deployment review/browser evidence.

For an explicit backup, use `DatabaseBackupRecovery(source_db, backup_dir).perform_backup(new_name)`;
it opens the source read-only and uses SQLite online backup, never overwrites an
artifact, and returns its SHA-256. Do not copy only an active WAL database's main
file. The CLI restore drill copies the backup into a temporary isolated database,
opens the actual application store there, and verifies retained cash results,
paper reconciliation and notification audits. It leaves the source and backup
unchanged. SQLite integrity alone does not satisfy application rollback readiness.
Empty databases do not qualify application recovery. A pending scan can be retained
but still requires the separate matching-version recovery procedure above.

For any future authorized deployment: stop the single scheduler owner; snapshot
the old release identity/configuration/schema and online database backup; restore
and test in isolation; activate only after acceptance. On failure stop writes,
retain failed-release evidence, and select the prior reviewed code/configuration
and a separately verified restore in a new location. Never overwrite the only
backup or run an unreviewed downgrade against newer schema/financial data. Database
mutation, hosting, scheduling and production activation are not authorized here.

CI is defined in `../.github/workflows/offline.yml` for Python 3.10-3.14 on Windows
and Ubuntu with Node 24 and explicit offline logs. No secret/application environment
is requested. Hosted execution, runtime matrix results, browser visuals and real
deployment acceptance are outstanding; local evidence does not stand in for them.

## Phase 4A trust and Phase 4B option replay

The active safe profile is now paper_sim, dry-run true, scheduler false. The task
changed only the existing ACTIVE_BROKER assignment to honor that explicit request;
credentials were neither printed nor altered. Software dependency installation
contacted PyPI; no broker/data/Telegram endpoint was contacted.

The tested isolated environment contains cryptography 50.0.2, cffi 2.1.1,
pycparser 3.11 and tzdata 2026.5. `requirements.txt` pins them and is bound by the
offline source snapshot and release manifest. Missing cryptography fails closed;
the positive signature tests require genuine Ed25519, not a mocked hash signature.
See `docs/evidence/phase4ab_crypto_runtime_verified.json`. A past installation
timeout is not evidence about another interpreter's installed backend.

Operator trust roots enter `DeterministicBacktestEngine(publisher_trust_config=...,
publisher_manifests={archive_id: signed_manifest_json})` through explicit local
service configuration. An HTTP body cannot choose its own trust root. Every
resolution rechecks original bytes, parsed records, signed type/provider/exchange/
segment/instrument scope, effective dates, current key validity/revocation and
publication before the requested historical session. Saved assessments cannot
authorize altered bytes or current policy. No production anchors or authentic
licensed dataset are installed by this mission.

`option_execution_request` is a versioned local JSON envelope:

```json
{
  "schema_version": "tradepulse.option-request.v1",
  "master_json": "EXACT ORIGINAL UTF-8 V1 MASTER JSON TEXT",
  "dataset_json": "EXACT ORIGINAL UTF-8 OPTION OBSERVATIONS JSON TEXT",
  "master_manifest": "DETACHED SIGNED MANIFEST JSON, REQUIRED FOR LIVE RESEARCH",
  "dataset_manifest": "DETACHED SIGNED MANIFEST JSON, REQUIRED FOR LIVE RESEARCH"
}
```

The dataset schema is `tradepulse.option-observations.v1`: exact provider, NIFTY or
BANKNIFTY, data_mode/is_simulated, chronological `underlying_candles`, `premiums`
and `chains`. A master contract supplies exact identifier, NFO/OPTIDX, underlying,
expiry, strike, CE/PE, lot size, tick size and effective interval. Every premium row
binds `identifier` and `contract_digest` to that record, with aware bar-start
`timestamp`, `available_at` exactly five minutes later, completion/mode flags,
observed `bid_open/high/low/close`, `ask_open/high/low/close`, `volume_units`, opening
`bid_size_units`/`ask_size_units` and `depth_observed_at` at bar start. No crossed
spread, off-tick price, duplicate/order conflict, naive/future bar or ambiguous
identity is accepted. The result retains original-byte digests and computed archive
IDs. Persisted completed option replays now retain the original embedded master,
observation dataset, detached manifests and replay envelope through
`HistoricalEvidenceArchive`. `input_evidence_id` identifies those exact bytes.
Nonpersistent replay only computes the ID; it does not claim a durable receipt.
Keep independent backups of the input files and SQLite evidence store.

Each chain has exact `known_at` at a completed underlying bar end, exact expiry,
paired ATM row, provider/mode scope, and the prior configured session's 15:30
`baseline_observed_at` with `baseline_kind=CLOSING_BASELINE`. V1 supports a single
paired ATM strike: PCR must equal observed put OI/call OI, and integer OI changes
must equal observed current minus prior OI. It does not silently round fractional
OI or infer a previous close. The existing Strategy 3 evaluator receives only the
known underlying prefix and matching chain; contract premiums supply fills.

V1 models one long CE/PE position, next observed option ask open, all-or-none opening
depth, full premium plus estimated fee affordability, lot/risk/capital/daily limits,
adverse slippage applied once per fill and tick rounding. Stop/target thresholds
are tick-rounded independently of slippage. Exits use observed opening bid/depth;
target price improvement is conservatively capped at the modeled limit. The result
separates the actual observed bid from modeled fill/reference and estimated costs.
It never reports a derived limit as an observed price.

An intrabar stop or stop/target collision without observed executable trigger
liquidity remains UNRESOLVED (stop priority; no optimistic target award). Missing
next entry rejects the candidate. Missing position/EOD prices or exit depth retain
the position/reservation and cannot be persisted as a completed result. No forward
fill, invented zero-price settlement, short-option margin or partial fill exists.
Expiry uses an observed pre-close EOD exit; absent quotes remain unresolved.
Configured weekday/holiday calendars and estimated cost schedules need separate
real-data/operating acceptance. Signed inputs alone do not prove profitability;
`empirical_performance_claim_allowed` stays false.

The Python entry point is `run_backtest(..., option_execution_request=request,
backtest_config=BacktestConfig(instrument_type='OPTIDX', execution_scope='SIMULATED_TEST'))`.
HTTP POST `/api/backtest` accepts the same explicit request and instrument type;
legacy flags/unbound chains still cannot enable execution. Qualified real inputs
require HISTORICAL_RESEARCH and current trusted signatures for master and complete
dataset; the default HTTP service has no real publisher roots.

CLI: `.venv_phase4\Scripts\python.exe -B backtest_engine.py --strategy strat_3_option_apex_oi --symbol NIFTY --provider upstox --data-mode SIMULATED --execution-scope SIMULATED_TEST --option-request LOCAL_FIXTURE.json --json`.
For a fixture CLI run set the process DATABASE_URL to `:memory:` so it cannot open
an operational database. `docs/evidence/phase4b_cli_verify.py` automates exactly
that temporary, credential-free scenario. It is a fixture demonstration, not a
publisher dataset or provider acceptance.

## Historical qualification and Dhan streaming (Task 2)

Current consolidated evidence and acceptance scopes are in
[the implementation report](reports/TRADEPULSE_TASK2_PARALLEL_IMPLEMENTATION_REPORT.md).
For source ZIP handover, retain the repository evidence directory described in
[release evidence location](RELEASE_EVIDENCE_LOCATION.md); the public ledger and
README-linked reports are now bundled. Prior release/evidence files are historical.

Install `requirements.txt` in the isolated environment; it additionally pins
`websockets==15.0.1`. The stream was implemented against the
[official Dhan feed documentation](https://dhanhq.co/docs/v2/live-market-feed/),
[annexure](https://dhanhq.co/docs/v2/annexure/) and
[official SDK decoder](https://github.com/dhan-oss/DhanHQ-py/blob/main/src/dhanhq/marketfeed.py).
It implements v2 binary ticker, quote, OI, previous-close, full five-level depth
and disconnect packets. Unknown schemas fail closed. Depth has no documented
independent exchange observation clock; receive time is retained without calling
pending order quantities executed or aggressor-side volume.

Configure Dhan credentials only in the local application environment. Set an
explicit canonical list, for example the pinned RELIANCE mapping:
`DHAN_FEED_INSTRUMENTS_JSON='[{"symbol":"RELIANCE","dhan_id":"2885"}]'`.
The default is empty, maximum 50 instruments. Only pinned NSE cash and index-spot
mappings are supported initially; unknown mappings and derivatives are rejected.
Index/ticker packets without trade volume are useful observations, not OHLCV bars.

`python -B dhan_feed_control.py` performs local preflight without a socket. After
Task 3's scope correction, this first-probe preflight itself requires exactly one
canonical instrument; a multi-instrument list is blocked before connection. After
it passes, the task-authorized minimal read-only probe is
`python -B dhan_feed_control.py --smoke --seconds 15`, requiring exactly one
instrument, dry-run Telegram and disabled scheduler. A short observation probe
does not establish complete-candle or operating acceptance. No order, profile,
token-refresh or account mutation endpoint is used. Current local preflight is
blocked by missing/placeholder Dhan credentials and an empty configured scope;
no real connection was attempted in this task.

For explicit service integration, construct `DhanLiveFeed(config, store)` and
attach it to `engine.broker.adapters['dhan'].attach_live_feed(feed)`, then call
`feed.start()` under the operator's configured Dhan runtime. Attaching does not
start a socket. The selected provider remains unchanged; paper_sim continues to
use simulation. An attached Dhan stream supplies the existing candle consumer;
stream failure raises an error without REST or simulated fallback. Engine close
stops its attached feed before closing SQLite. Health and the existing dashboard
show stream state and blocked signals. Existing persisted live acceptance policy
still applies independently.

The feed retains per-connection packet hashes, source identity, timestamps,
forming snapshots and 1m/5m candles in provider-separated SQLite tables. Completed
5m rows pass the existing canonical assessor and enter existing scanner cash
lineage when consumed. Duplicates do not add volume; zero-volume quote updates
do not repeat last trade quantity. Missing initial cumulative-volume baseline,
delta inconsistent with the observed last trade, delayed events, gaps, reconnects
and unproven close boundaries invalidate affected bars. Reconnection resets all
consumable buffers and subscriptions are restored. There is no REST backfill:
start a new lineage and accumulate sufficient contiguous complete bars. The final
session minute remains provisional without a later observed closing boundary.
Fixture transport always stays FIXTURE and cannot serve accepted scanner bars.

Historical operators can construct `OperatorRightsPolicy(grants, documents)`
locally, where `documents` maps SHA256 to the actual reviewed rights-document
bytes. Each grant binds `rights_reference`, `publisher_id`, `provider`,
`document_sha256`, `artifact_sha256s`, `symbols`, `allowed_uses` containing
`HISTORICAL_RESEARCH`, `revoked=false`, `effective_from/until`, `approved_at`,
`review_due_at`, `approved_by` and `approval_reference`. This is an operator review
record, not independent legal verification. Do not accept that policy from HTTP
clients or dataset-supplied flags. No approved policy is supplied with the app.

`run_frozen_study` in `historical_study.py` reuses the existing backtest engine,
with explicit dated master ID and original signed cash observations (schema
`tradepulse.cash-observations.v1`, containing `candles`), or the existing option
request. Supply the engine's locally approved publisher trust configuration,
`publisher_manifests`, current rights policy and a `walk_forward_plan` of sorted
session dates. Plans freeze expanding training prefixes and disjoint future test
windows, strategy/configuration/source hashes and original input evidence before
evaluation; there is no optimizer or test-period tuning callback. `input_evidence_id`
and `result_evidence_id` recover exact retained inputs and result bytes through
`HistoricalEvidenceArchive(store).load(id)`. Loading bytes restores no authority:
re-run qualification with current revocation, validity and rights policy. Fixtures
exercise mechanics only. Real studies remain blocked until real sources and
rights pass these gates; historical OHLCV/OI alone cannot substitute executable
option bid/ask/depth and prior-closing OI observations.

## Task 3 continuation evidence and operator inputs

Use the current full-proof command from the application directory:
`.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage task3_completion_20261023_01`.
That stage has been reserved for this executed run; use a new unique stage for
later runs. Validate it with
`.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task3_completion_20261023_01.json`.
The old mismatched Task 2 manifest/log are preserved and are not current proof.

The single current checklist is
`docs/evidence/task3_completion_acceptance_20261023_01.json`. Its closeout and
precise operator blocker messages distinguish software/evidence remediation from
real historical and Dhan acceptance. A passing full offline run never clears
missing publisher roots, rights, historical prices or Dhan account configuration.

Store operator-provided original files and policy under the ignored application
`.local/task3-history/` directory. No data, roots or approvals are supplied by the
software. Source files belong under `source/`; independently reviewed trust and
rights policy belong under `operator/`, separate from dataset-supplied fields.
Use only approved public verification keys, never publisher private signing keys.
Do not put credentials, licences, account data or original market datasets into
chat, evidence logs or source ZIPs. The matching repository's Task 3 historical
helper provides its exact input-file contract via `--help`; it reuses the existing
qualification and frozen-study APIs and retains private inputs/results in the
explicit operator-selected SQLite file. Missing files stay blocked.
