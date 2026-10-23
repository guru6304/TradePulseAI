# Release evidence location and scope

This ZIP is an offline source candidate. It contains the public execution ledger,
runbook, README-linked reports and tests. Historical reports retain their dates;
they do not establish current source acceptance.

Machine evidence and prior release ZIPs are intentionally retained in the original
repository, under `indian_fo_signal_bot_v1/docs/evidence/`. They are not embedded in
this source ZIP. To review or hand over this candidate, also retain that evidence
directory from the same workspace. Do not copy `.env`, databases or credentials.

Task 3 continuation uses `master_task3_completion_20261023_01.json` and its three
named logs for fresh full verification. The corresponding
`task3_completion_closeout_20261023_01.json` binds the source, checklist, blockers,
reports and exact new `task3_completion_release_20261023_01.zip`.
`task3_completion_release_build_20261023_01.json` and
`task3_completion_release_inspect_20261023_01.json` describe that exact ZIP.
The old Task 2 Python log no longer matches its original receipt; those bytes and
the failed binding are preserved as historical evidence, never rewritten.
Task 2 and Phase 4A/4B releases remain historical under their original names.

The current continuation report, precise operator blocker messages and executable
historical-input helper live in the matching repository's `docs/reports/` and
`docs/evidence/` directories, outside this public source ZIP. Retain those matching
directories for the complete handover; their hashes are bound by the continuation
closeout. Never include operator `.local/` inputs, rights documents or SQLite data
in the public ZIP.

Verify the source snapshot and log hashes with:

```powershell
.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task3_completion_20261023_01.json
.venv_phase4\Scripts\python.exe -B release_management.py inspect --archive docs/evidence/task3_completion_release_20261023_01.zip
```

A clean extracted package can create a local environment, install the pinned
requirements, and run `verify_offline.py --stage extracted_review` to create its
own fresh evidence. Package hashes establish byte integrity. Offline protocol
fixtures, genuine test-key signatures and simulated studies do not establish an
approved provider root, licensed data, broker authentication, historical strategy
performance, live operational acceptance or production readiness.

The Angel Phase 3 source change uses the fresh
`master_phase3_angel_20261023_03.json` receipt and its exact named logs. The
corresponding `phase3_angel_closeout_20261023_02.json` and validation receipt bind
the new source candidate, acceptance matrix and bounded probe. Its dedicated ZIP
is `phase3_angel_release_20261023_02.zip`. These files stay in the matching
repository evidence directory, outside the source ZIP. The continuation receipt
above describes an earlier source snapshot and is not current Angel proof.
Private `.local/phase3-angel/` contains original master/history bytes and feed
SQLite lineage; do not redistribute that area or either `.env` file.
The `_01` full receipt binds the source that performed the actual 15-second
bounded probe. `_02` additionally verifies the guarded extended-window option;
no longer or second private probe was performed during this task.

The current `_03` full receipt includes the final completed-candle/scanner diagnostic correction. `_01` and `_02` full receipts and the `_01` release/closeout remain preserved historical snapshots. Actual private probe evidence remains `phase3_angel_probe_live_20261023_01.json`.
