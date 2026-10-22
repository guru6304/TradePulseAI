# Local testing, recovery and release operations

Keep the [execution ledger](TRADEPULSE_EXECUTION_LEDGER.md) as the continuation
checkpoint. These commands do not authorize broker requests or real trading.

## Repeatable offline testing

Use the application directory with Python and Node installed:

```powershell
python -B -W error::ResourceWarning verify_offline.py --stage operator_001
$LASTEXITCODE
python -B verify_offline.py --validate-evidence docs/evidence/master_operator_001.json
$LASTEXITCODE
```

Use a new stage name each time. The command starts and stops only local test
servers with credential-free deterministic fixtures and temporary SQLite stores.
It executes the established unified suite, actual dashboard JavaScript tests,
syntax and compilation. It records actual IDs/counts and hashes. An old PASS does
not validate a changed source version. Exit nonzero must be investigated; do not
delete/skip assertions or relabel an intermediate log as final.

`python -B configuration_check.py` is a separate zero-disclosure local preflight.
PASS establishes local configuration only. Keep Upstox, Telegram dry-run true,
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
