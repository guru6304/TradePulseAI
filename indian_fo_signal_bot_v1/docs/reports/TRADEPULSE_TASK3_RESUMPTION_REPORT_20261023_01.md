# TradePulse AI — Task 3 resumption

`TASK_3_STATUS=BLOCKED_AWAITING_OPERATOR_INPUT`

## Current state and verification

Repository: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`;
application directory: `indian_fo_signal_bot_v1`.
Actual HEAD: `93357342939815d1084691eba7c1b295b2d2117a`, advanced from the prior
reported commit. The working tree was clean at entry. No application source,
operator configuration, original data, database, old receipt or release was
changed. This run adds only its new report, checklist and diagnostic receipts.

The full source snapshot still matches the genuinely tested snapshot. The existing
validator accepts `master_task3_completion_20261023_01.json` and all its log hashes.
Its actual results remain **804/804 Python PASS**, zero failures/errors/skips,
**11/11 dashboard PASS**, **62 Python files compiled**, no unraisable exceptions.
These results were reused, not rerun or relabelled as a new execution. Tested HEAD
was `5c9f09536384dc4161714e189cbaf0b0eb8f6e4f`; current code-byte equivalence is
recorded independently. The historical-helper bytes and its seven-test log also
match the prior passing helper receipt.

The existing 91-file Task 3 source candidate passes manifest/integrity inspection:
SHA256 `af80797e8534ee0abfb80adb019cf59ef36e43fdd6fe649f11479308d02e3a96`.
No new software release or large suite was necessary. The old historical log
mismatch remains preserved and superseded by the valid full receipt.

## Track A — current operator inputs

The helper accepts the requested arguments and `operator_check_02` was unused.
It was executed from the application directory:

```powershell
.venv_phase4\Scripts\python.exe -B docs/evidence/task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02
```

Its new receipt reports exit code **2**, missing/ineligible operator inputs. The
PowerShell invocation wrapper reported nonzero exit 1. This is an input-blocked
qualification result, not a failing software regression. All seven fixed input
files are absent from the selected roots: cash observations and manifest, dated
master and manifest, frozen plan, publisher trust policy and rights policy. No
usable rights-document/grant pair was loaded. No authentic cash study or private
research database was opened; there are no real metrics or study evidence IDs.
Coverage is NOT_ASSESSED for absent candles. Option execution remains a separate
recorded dependency, never inferred from cash data or present liquidity.

Evidence: [qualification receipt](../evidence/task3_completion_track_a_20261023_01_operator_check_02.json)
and [its historical-input blocker messages](../evidence/task3_completion_track_a_20261023_01_operator_check_02_blockers.md).
The current combined messages below correct the next-check stage to a fresh label.

## Track B — credentials progressed; scope and runtime profile blocked

Actual command executed:

```powershell
.venv_phase4\Scripts\python.exe -B dhan_feed_control.py
```

It returned exit **1**, BLOCKED, with
`EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED`; instrument_count is **0**.
Dhan-specific credentials now pass the local missing/placeholder check. The
previous credential-presence blocker is therefore RESOLVED **for configuration
presence only**. Authentication, permissions and token validity are unproven.
No new credential values are requested or disclosed.

The separate required-runtime check also returned exit **1**:
`active_broker=dhan`, Telegram dry-run true, scheduler false. The authorized Task 3
probe requires **paper_sim**. This produces the precise operator-input blocker
`PAPER_SIM_SAFETY_PROFILE_REQUIRED`. It is an effective operator setting, not a
source-code regression. The workflow withheld the probe; no source change is
needed to handle this observed configuration. No private `.env` selection or
credential entry was silently rewritten.

No smoke command, connection, authentication, subscription, packets or completed
live candles occurred. No actual live shutdown was needed. No orders, account
mutations, token refresh, Telegram delivery or scheduler activation occurred.
The current configuration must not be described as the required paper_sim profile.

Evidence: [actual preflight](../evidence/task3_resumption_dhan_preflight_20261023_01.json)
and [runtime admission check](../evidence/task3_resumption_runtime_profile_20261023_01.json).

## Current acceptance gates

The authoritative current Task 3 checklist is
[task3_resumption_acceptance_20261023_01.json](../evidence/task3_resumption_acceptance_20261023_01.json).
It explicitly supersedes the prior checklist while preserving that bound receipt.

| Gate | Status |
| --- | --- |
| Current full offline verification | PASS — exact source/log proof reused |
| Regression and safety software controls | PASS for the tested source |
| Historical source authenticity / rights approval | BLOCKED |
| Real cash study | BLOCKED |
| Option study | BLOCKED — separate data dependency recorded |
| Dhan credential presence | PASS locally; authentication unconfirmed |
| Dhan local preflight | BLOCKED — empty scope |
| Required safe runtime profile | BLOCKED — selected broker is dhan |
| Dhan authentication/subscription | NOT_ATTEMPTED |
| Authentic live observations / completed candles | BLOCKED |
| Current evidence integrity | PASS |
| Combined safety/evidence acceptance | BLOCKED_RUNTIME_PROFILE |
| Production readiness / whole Task 3 | BLOCKED |

The six phases remain foundation, historical validation, live ingestion, guarded
scanner/recommendations, context/dashboard/alerts, and paper/performance/release.
This remains Task 3 within phases 2 and 3. No Task 4, new phase, strategy change or
score recalculation was introduced.

## ACTION REQUIRED FROM YOU

Current [separate machine/human blocker messages](../evidence/task3_resumption_operator_blockers_20261023_01.md)
state findings, commands, evidence, required inputs, responsible party and passing
results for every open code.

For Dhan, preserve the credentials you supplied. In the **application** `.env`:

1. Set `ACTIVE_BROKER=paper_sim` to satisfy `PAPER_SIM_SAFETY_PROFILE_REQUIRED`; leave `TELEGRAM_DRY_RUN=true` and `ENABLE_BACKGROUND_SCHEDULER=false` intact. This run's settings came from the application loader, with no initial process overrides for those Dhan/provider keys.
2. Set `DHAN_FEED_INSTRUMENTS_JSON` to exactly one permitted canonical record backed by the project's trusted provider/master mapping. Resolve `EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED` without inventing an ID, borrowing another broker token or expanding the initial scope.

Confirm the safe profile locally, then rerun preflight:

```powershell
.venv_phase4\Scripts\python.exe -B -c "from config import BotConfig; c=BotConfig(); print(c.active_broker, c.telegram_dry_run, c.enable_background_scheduler); assert c.active_broker=='paper_sim' and c.telegram_dry_run is True and c.enable_background_scheduler is False"
.venv_phase4\Scripts\python.exe -B dhan_feed_control.py
```

Passing output must show `paper_sim True False`, then preflight PASS,
instrument_count 1 and live_requests false. Only then is the already-authorized
`.venv_phase4\Scripts\python.exe -B dhan_feed_control.py --smoke --seconds 15`
permitted. Do not extend the window automatically; observed authentication is not
completed-candle acceptance.

For historical research, provide each separate missing item privately:

| Exact blocker | Required location/content under `.local/task3-history/` |
| --- | --- |
| HISTORICAL_CASH_DATA_MISSING | `source/cash_observations.json` and frozen `source/study_plan.json`, following the existing helper contract. |
| PUBLISHER_TRUST_ROOT_MISSING | Independently approved public verification roots in `operator/publisher_trust.json`; no test roots or private signing keys. |
| PUBLISHER_AUTHENTICITY_UNVERIFIED | Genuine detached `source/cash_manifest.json` and `source/master_manifest.json` binding the exact originals and scope. |
| HISTORICAL_INSTRUMENT_MASTER_MISSING | Authentic dated `source/instrument_master.json` covering the selected identity and dates. |
| HISTORICAL_RIGHTS_DOCUMENT_MISSING | Actual licence/permission document under `operator/rights_documents/` with its exact hash/path mapping in rights policy. |
| HISTORICAL_RESEARCH_SCOPE_UNAPPROVED | Independently reviewed, current artifact-specific grant in `operator/rights_policy.json`, authorizing HISTORICAL_RESEARCH. |

Use helper `--help` for exact schemas. After supplying the required originals and
separate operator policy, use the next unused stage:

```powershell
.venv_phase4\Scripts\python.exe -B docs/evidence/task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03
```

Resolution requires exit 0 and genuine source/rights/identity/quality checks passing.
Then use `--run-cash-study`, an explicit private
`--private-db .local/task3-history/operator/study.sqlite3`, and a fresh stage to
obtain real retained input/result IDs and supported metrics. Keep credentials,
private keys, licence documents, databases and original licensed data out of chat
and public ZIPs. `OPTION_EXECUTION_DATA_MISSING` remains a separate deferred
dependency; a cash helper PASS cannot accept options.
