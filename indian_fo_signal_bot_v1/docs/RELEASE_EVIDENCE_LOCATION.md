# Release evidence location and scope

This ZIP is an offline source candidate. It contains the public execution ledger,
runbook, README-linked reports and tests. Historical reports retain their dates;
they do not establish current source acceptance.

Machine evidence and prior release ZIPs are intentionally retained in the original
repository, under `indian_fo_signal_bot_v1/docs/evidence/`. They are not embedded in
this source ZIP. To review or hand over this candidate, also retain that evidence
directory from the same workspace. Do not copy `.env`, databases or credentials.

The current task uses `master_task2_parallel_verified.json` and its three named
logs for complete offline verification; `task2_parallel_closeout.json` binds the
verification, source revision, final release ZIP, manifest and public reports.
`task2_parallel_release_build.json` and `task2_parallel_release_inspect.json` both
describe the exact `task2_parallel_release.zip`. Earlier Phase 4A/4B artifacts are
historical and are preserved under their original names.

Verify the source snapshot and log hashes with:

```powershell
.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task2_parallel_verified.json
.venv_phase4\Scripts\python.exe -B release_management.py inspect --archive docs/evidence/task2_parallel_release.zip
```

A clean extracted package can create a local environment, install the pinned
requirements, and run `verify_offline.py --stage extracted_review` to create its
own fresh evidence. Package hashes establish byte integrity. Offline protocol
fixtures, genuine test-key signatures and simulated studies do not establish an
approved provider root, licensed data, broker authentication, historical strategy
performance, live operational acceptance or production readiness.
