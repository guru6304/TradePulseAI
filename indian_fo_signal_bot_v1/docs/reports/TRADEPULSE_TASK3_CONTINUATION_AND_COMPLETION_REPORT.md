# TradePulse AI — Task 3 continuation and completion contract

`TASK_3_STATUS=BLOCKED_AWAITING_OPERATOR_INPUT`

Client date: 2026-10-23, Asia/Kolkata. Independent engineering and current full
offline verification are complete. Real historical and Dhan acceptance are not
complete. Task 4 has not started. The single current checklist is
[task3_completion_acceptance_20261023_01.json](../evidence/task3_completion_acceptance_20261023_01.json).

## Repository and preservation

Repository: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`.
Application directory: `indian_fo_signal_bot_v1`.
Entry HEAD: `5c9f09536384dc4161714e189cbaf0b0eb8f6e4f`; entry worktree was clean.
This advances the prior reported HEAD through an existing commit; no agent reset,
checkout, cleanup, staging or commit was performed. The entry software source
hashes still matched the previous snapshot. All 205 evidence files present at
entry, prior releases, previous reports and local configuration are preserved.
Initial/final status and byte-preservation results are bound by the
[new closeout](../evidence/task3_completion_closeout_20261023_01.json).

Actual changes:

- `dhan_feed_control.py`: first-probe preflight now requires exactly one instrument.
- `test_task2_integration.py`: socket-blocked regression proves a two-instrument preflight fails safely.
- Root `.gitignore`: protects the operator's application `.local/` input/policy directory; no real inputs or approvals were created there.
- Existing runbook, ledger and release-evidence locator: document the current proof, private operator workflow and exact matching candidate.
- New continuation report and evidence helpers/receipts: retain precise blockers, actual commands, hashes and input validation. Evidence helpers stay outside the public source ZIP and are explicitly referenced in its runbook.

## Remediation loop and full verification

Two agent-remediable findings were resolved:

1. `CODE_DEFECT:DHAN_FIRST_PROBE_PREFLIGHT`: preflight accepted two valid instruments while the authorized first probe permits one. The new regression failed before the fix (`'PASS' != 'BLOCKED'`). A two-line scope guard fixes the preflight; the existing socket guard and general feed-library scope remain intact. All **33 focused tests passed**, zero failures/errors/skips. [Regression, correction and actual preflight receipt](../evidence/task3_completion_track_b_20261023_01.json).
2. `EVIDENCE_LOG_INTEGRITY_FAILURE`: the historical Task 2 Python log differs from its recorded hash. Its recorded SHA256 is `98a5442500c5d7c3cefa55ebdf3368a34c780c827dab92742b67ea70c7a1a327`; actual entry SHA256 is `0c38d5bafe46335efa4fdb15e50749a3909ee983ce70ee62c10bb4513a8b782c`. The cause of that historical change is unconfirmed. Old bytes were preserved; a genuinely executed new full run supplies current proof. The old manifest remains historical, not repaired or relabelled.

Executed from the application directory:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage task3_completion_20261023_01
.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task3_completion_20261023_01.json
```

The CLI permits explicit unique `[a-z0-9_-]{1,64}` labels, not a predefined stage
enum. This label was documented and checked unused before execution. Results:

| Check | Executed result |
| --- | --- |
| Complete Python suite | **804/804 PASS**, 322.904 seconds; zero failures/errors/skips |
| Dashboard | **11/11 PASS**, zero failures/skips |
| JavaScript syntax | PASS |
| Python compilation | **62 files PASS** |
| Unraisable/resource errors | None in the full run; ResourceWarnings are errors |
| Current evidence validator | **PASS**, exit 0 |
| Source before/after/current | Equal for the executed snapshot |

[Full receipt](../evidence/master_task3_completion_20261023_01.json),
[Python log](../evidence/master_task3_completion_20261023_01_python.txt),
[dashboard log](../evidence/master_task3_completion_20261023_01_node.txt), and
[syntax log](../evidence/master_task3_completion_20261023_01_syntax.txt).
Tests prohibit outbound sockets; loopback application fixtures remain allowed.
Expected negative-test storage/provider failures are not real broker requests.
The new total includes the new scope regression; no previous total was forced.

The changed software requires a new source candidate. The exact ZIP is
`docs/evidence/task3_completion_release_20261023_01.zip`, with matching
`task3_completion_release_build_20261023_01.json` and
`task3_completion_release_inspect_20261023_01.json`. The closeout records its exact
ZIP/manifest hashes and verifies all archived file sizes, hashes, archive integrity
and equality to the final public files. Prior ZIPs and records are untouched.
Package integrity is separate from production or authentic-data acceptance.

## Track A — authentic cash research

Current nonprivate workspace discovery and explicit operator-input checks still
find no eligible original cash OHLCV package, approved publisher roots, current
rights document/grant or authentic dated master. The retained Angel instrument
snapshot contains identities, not price bars; its previous rejected/unqualified
status is not upgraded by a matching hash. No authentic cash study, real metrics,
trade count or real study evidence IDs were created. Coverage/quality remain
NOT_ASSESSED for absent observations. Option execution remains a separate recorded
data dependency, never accepted from cash inputs or present live depth.

The new evidence-only operator helper reuses `TrustAnchorConfig`, current
source/rights verification, existing identity/quality gates, the existing backtest
engine and `run_frozen_study`. Data and independently selected operator-policy
directories must be separate. Missing inputs fail closed. Only explicit
`--run-cash-study` can open the selected private research SQLite file. No publisher
keys, grants, data, source authority or legal rights are generated by the helper.
Its complete contract is available with:

```powershell
.venv_phase4\Scripts\python.exe -B docs/evidence/task3_completion_track_a_20261023_01_verify.py --help
```

Seven isolated helper checks pass, including genuine test-key verification,
revocation, missing rights, path/identity rejection and durable fixture study
recovery. These are engineering fixtures, not authentic provider acceptance.
The first sandbox attempt failed before evaluation because host Temp directories
were inaccessible (7 cases, 14 setup/cleanup errors); that failed receipt is
preserved. The fixture harness was adapted to owned workspace directories with
guarded cleanup, and **7/7 passed**, zero failures/errors/skips, 6.185 seconds.
No additional elevated execution was needed. See
`task3_completion_track_a_20261023_01_helper_tests_workspace.json` and its log.

The actual missing-input receipt and individual human-readable messages are under
`docs/evidence/task3_completion_track_a_20261023_01_current.*`.
The authoritative combined checklist binds those receipts and their hashes.

## Track B — Dhan read-only acceptance

Actual local preflight was rerun after the scope correction. It returns exit 1:
`DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER` and
`EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED`.
Both `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are classified PLACEHOLDER; values
are not retained. Instrument count is 0. No smoke command, socket, authentication,
subscription, actual packets, completed live candles or live shutdown occurred.
No market-closed assumption substitutes for observations.

[Actual Dhan receipt](../evidence/task3_completion_track_b_20261023_01.json),
[preflight output](../evidence/task3_completion_track_b_20261023_01_preflight.txt),
[focused log](../evidence/task3_completion_track_b_20261023_01_focused.txt), and
[separate actionable messages](../evidence/task3_completion_track_b_20261023_01_blockers.md).
No extra observation window is requested now because no probe was possible.
After preflight passes, only the already-authorized one-instrument 15-second probe
is permitted; further candle observation requires separate authorization.

## Acceptance matrix and safety

| Mandatory gate | Status |
| --- | --- |
| CURRENT_OFFLINE_VERIFICATION | PASS — fresh full receipt and validator |
| REGRESSION_AND_SAFETY_TESTS | PASS |
| TRACK_A_SOURCE_AUTHENTICITY | BLOCKED |
| TRACK_A_RIGHTS_APPROVAL | BLOCKED |
| TRACK_A_CASH_STUDY | BLOCKED |
| TRACK_A_OPTION_STUDY | BLOCKED — separate data dependency recorded |
| TRACK_B_LOCAL_PREFLIGHT | BLOCKED |
| TRACK_B_LIVE_AUTHENTICATION_AND_SUBSCRIPTION | NOT_ATTEMPTED — preflight blocked |
| TRACK_B_OBSERVATIONS | BLOCKED — no actual observations |
| TRACK_B_CANDLE_ACCEPTANCE | BLOCKED — no actual completed candles |
| SAFETY_AND_EVIDENCE_INTEGRITY | PASS for current software/evidence; historical mismatch preserved |

Actual configuration remains `paper_sim`, Telegram dry-run true, scheduler false.
No orders, account mutations, Telegram deliveries, token refresh or real broker
requests occurred. Fixtures cannot authorize source, live-feed or candle acceptance;
stale/incomplete data blocks LIVE recommendations without provider/simulation
fallback. New evidence is checked without exposing configured secret values.

The fixed six phases remain: (1) foundation; (2) historical validation;
(3) live ingestion; (4) guarded scanner/recommendations; (5) context/dashboard/alerts;
(6) paper/performance/release. This continues 2 and 3, tests existing guards in 1
and 4, and updates source-package evidence under 6. No new phase or context feature
was added; scores and whole-product acceptance were not recalculated.

## ACTION REQUIRED FROM YOU

All paths below are relative to the application directory. Do not share original
licensed datasets, rights documents, credentials, account data or private keys in
chat. Keep original files and independently reviewed policy under the ignored
`.local/task3-history/` directory. Each blocker has a separate machine record and
human message in the Track A/Track B artifacts linked above.

| Exact missing item / blocker | Why and acceptable local input |
| --- | --- |
| `HISTORICAL_CASH_DATA_MISSING` | Put original completed 5m cash observations in `source/cash_observations.json`, its genuine detached `cash_manifest.json`, and frozen `study_plan.json`; filenames are relative to `.local/task3-history/`. The exact schema is in helper `--help`. Instrument identities are not price history. |
| `PUBLISHER_TRUST_ROOT_MISSING` | Put an independently approved Ed25519 **public** verification-root record in `operator/publisher_trust.json`, using the existing trust-policy constructor schema. Test roots, self-signing and publisher private keys are unacceptable. |
| `PUBLISHER_AUTHENTICITY_UNVERIFIED` | Obtain genuine detached publisher manifests for the exact original cash and master bytes, matching provider, symbol, schema and effective interval; put them in `source/`. A URL, filename or local hash is insufficient. |
| `HISTORICAL_INSTRUMENT_MASTER_MISSING` | Put the authentic dated EQ master and its genuine detached manifest in `source/instrument_master.json` and `source/master_manifest.json`. It must cover the selected instrument and study dates. |
| `HISTORICAL_RIGHTS_DOCUMENT_MISSING` | Put the actual provider licence/permission document under `operator/rights_documents/`, with its SHA256-to-relative-path mapping in `operator/rights_policy.json`. |
| `HISTORICAL_RESEARCH_SCOPE_UNAPPROVED` | Have the authorized operator independently review that document and supply a current, nonrevoked grant in `operator/rights_policy.json`, covering exact artifacts, publisher/provider, symbol, dates and HISTORICAL_RESEARCH use. Dataset-supplied approval flags are unacceptable. |
| `DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER` | Privately replace the Dhan-specific placeholders in the application `.env` or process environment with Dhan-issued `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`. The repository-root `.env` is not the default application file. Do not paste values into chat. |
| `EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED` | Configure `DHAN_FEED_INSTRUMENTS_JSON` locally with exactly one permitted canonical metadata record, whose Dhan ID and exchange segment agree with a verified mapping source. Do not invent an ID or expand the first probe. |

For historical inputs, first run (use a fresh stage if already used):

```powershell
.venv_phase4\Scripts\python.exe -B docs/evidence/task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_01
```

Resolution proof is exit 0 with current source authentication, rights, dated
identity, coverage and frozen chronological-plan checks passing. Then run the
same helper with `--run-cash-study` instead of `--check-inputs`, add
`--private-db .local/task3-history/operator/study.sqlite3`, and use a new stage.
The pass must include a genuine qualified study with retained input/result IDs,
source/config hashes and supported metrics; a fixture result does not resolve it.
Keep that SQLite file and original sources private and backed up.

For each Dhan blocker, rerun:

```powershell
.venv_phase4\Scripts\python.exe -B dhan_feed_control.py
```

Resolution proof is preflight PASS, instrument_count 1 and live_requests false,
with paper_sim/dry-run/scheduler settings intact. Only then use:

```powershell
.venv_phase4\Scripts\python.exe -B dhan_feed_control.py --smoke --seconds 15
```

Authentication, subscription, correctly mapped timestamped observations and clean
shutdown must be demonstrated by that actual probe. If no completed usable candle
is observed, candle acceptance stays insufficient; do not extend the window
without new authorization. `OPTION_EXECUTION_DATA_MISSING` is separately deferred:
future option acceptance needs its own exact contracts, premiums, executable
bid/ask/depth, timed OI and previous closing baseline, never reconstructed values.

Task 3 remains `BLOCKED_AWAITING_OPERATOR_INPUT` until its mandatory real-data
gates pass. Resume this Task 3 when the specified local evidence becomes available.
