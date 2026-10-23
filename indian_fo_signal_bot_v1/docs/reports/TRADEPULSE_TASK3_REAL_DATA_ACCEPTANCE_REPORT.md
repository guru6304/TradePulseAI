# TradePulse AI — Task 3 real-data acceptance

Client date: 2026-10-23, Asia/Kolkata. Execution receipts retain their actual UTC
timestamps. Outcome: offline controls pass their fresh focused checks; real cash
research and Dhan live acceptance remain blocked by missing external inputs.

## A. Current repository state

Repository: `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`.
Application: `indian_fo_signal_bot_v1`.
Entry and verified source HEAD: `2ef6751a4f393507d13522a505d1070356114779`.
Entry status: 16 modified tracked files and 33 untracked entries, containing the
existing Task 2 work. All are preserved. No software source, configuration,
strategy, database, previous receipt or release was changed. This task adds only
its evidence helpers/receipts and this report. Initial/final porcelain status and
entry-file preservation checks are recorded in
[the closeout](../evidence/task3_real_acceptance_closeout.json).

The current source snapshot exactly matches Task 2's recorded source. However,
its Python execution log has changed since its manifest was written. The existing
validator returns `EVIDENCE_LOG_INTEGRITY_FAILURE`; the Node and syntax log hashes
still match. The changed log was already present at Task 3 entry and was preserved.
There is no evidence here establishing who changed it or why. The historical
803-pass declaration is not presented as a newly validated current full-suite
receipt. See [entry baseline](../evidence/task3_real_acceptance_baseline.json) and
[prior-manifest validation](../evidence/task3_prior_manifest_validation_001.json)
for recorded/current hashes. No historical hash or log was rewritten to hide this.

## B. Track A — historical cash data

Workspace discovery found no eligible standalone cash OHLCV files, option
execution observations, operational databases, approved publisher-root records,
rights documents or operator rights grants within its documented nonprivate
scope. Discovery also inspected the existing software archives for data members.
It does not establish absence of material outside this workspace or inside
excluded credential locations.

One retained candidate exists:
`docs/evidence/angel_public_master_20261019.json.gz`. Its compressed and decompressed
hashes match the earlier local capture receipt. It contains 153,621 instrument
identity records, including 2,728 NSE equity rows, and **no historical price bars**.
The existing parser rejects the complete candidate with `INVALID_NATIVE_MASTER`.
Source assessment returns `HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT`, publisher
authenticity `NOT_ESTABLISHED`, and effective-date basis `UNKNOWN`. A matching
local capture hash does not establish approved publisher identity or rights.

No authentic cash or option study ran. Eligible cash instruments/candles and
qualifying option observations: **0**. Cash coverage, continuity, missing intervals,
corporate-action adjustments and study quality are **NOT_ASSESSED** because there
are no eligible price observations. Study period, frozen real-data configuration,
performance metrics and real input/result evidence IDs are **NOT_RUN**; no returns
or profitability claims are made. Fixtures still exercise the frozen study engine.

Evidence:

- [Verified input discovery and qualification result](../evidence/task3_track_a_input_discovery_verified.json), including hashes and linkage to the original discovery receipt.
- [Current historical test receipt](../evidence/task3_track_a_focused_current.json) and [log](../evidence/task3_track_a_focused_current.txt): **49/49 PASS**, 22.252 seconds, zero failures/errors/skips/unraisable exceptions.

The encoding-aware discovery inspected 61 public receipts, including 19 UTF-16
receipts; two empty historical receipts are explicitly identified rather than
treated as evidence. No publisher key, signature, approval or rights grant was
invented. Cash acceptance would not accept F&O: exact dated contracts, premiums,
historical bid/ask/depth and source/timestamp-bound OI with the required previous
closing baseline remain separate option-study dependencies.

## C. Track B — DhanHQ

Actual application-environment preflight ran from the application directory using
the isolated interpreter. It returned exit 1, **BLOCKED**, with:

- `DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER`
- `EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED`

Configured scope is empty. No `--smoke` command, socket, broker authentication or
subscription was attempted. Actual packets and accepted live candles: **0**.
Instrument identity, observed packet types, provider/receive timing and completed
candle acceptance therefore remain unobserved. No market-open/closed assumption
was used to explain the missing observations; preflight stopped before connection.

An independent configuration-only process confirmed `active_broker=paper_sim`,
Telegram dry-run true and scheduler false. No provider was switched and no other
broker credentials were used. Actual broker-resource shutdown is NOT_ATTEMPTED;
fake transport lifecycle tests passing is separate from a live shutdown result.

Evidence: [Dhan acceptance receipt](../evidence/task3_track_b_acceptance_001.json),
[actual preflight output](../evidence/task3_dhan_local_preflight_001.txt), and
[focused test log](../evidence/task3_track_b_focused_001.txt).
The focused feed/preflight suite passed **32/32**, 0.263 seconds, zero
failures/errors/skips. Eleven recorded source/dependency hashes remain unchanged.

## D. Verification

Commands actually executed from the application directory:

```powershell
.venv_phase4\Scripts\python.exe -B dhan_feed_control.py
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/task3_track_a_acceptance_verify.py
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning -m unittest test_dhan_feed test_task2_integration -v
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs/evidence/task3_verify_shared.py
.venv_phase4\Scripts\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task2_parallel_verified.json
.venv_phase4\Scripts\python.exe -B release_management.py inspect --archive docs/evidence/task2_parallel_release.zip
```

The historical helper executes the existing `test_historical_study`,
`test_option_execution`, `test_phase4_acceptance` and `test_publisher_trust` suites.
The shared helper executes `test_market_data_contract`, `test_cash_lineage`,
`test_release_operations`, `test_verify_offline` and `test_phase5a_integration`;
it also executes `node test_cash_dashboard.js`, `node --check test_cash_dashboard.js`
and compiles every top-level Python file in memory. Outbound sockets are blocked
during shared/historical tests; loopback application fixtures remain permitted.

| Current check | Result |
| --- | --- |
| Historical qualification/study controls | 49/49 PASS |
| Dhan feed/preflight controls | 32/32 PASS |
| Shared contract/storage/readiness/release controls | 69/69 PASS, 13.308 seconds |
| Total fresh Python cases across these disjoint suites | **150/150 PASS**, zero failures/errors/skips |
| Dashboard and JavaScript syntax | **11/11 PASS**, syntax PASS |
| Python compilation | **62 files PASS** |
| Current scoped source/log bindings | PASS; before/after/entry source hashes match |
| Historical full-suite manifest validation | **FAIL**: existing Python log hash mismatch |
| Complete 803-case suite this task | NOT_RERUN; no software source changed |

No ResourceWarning or unraisable leak occurred in the fresh checks. Expected
negative fixtures log unavailable storage, rejected input and stale feeds; they
are passing failure-mode tests. A metadata display initially used the Windows
default text encoding for a Unicode dashboard log and failed; reading that
existing UTF-8 log explicitly corrected the display without altering the file.

[Shared receipt](../evidence/task3_shared_verification_001.json),
[Python log](../evidence/task3_shared_python_001.txt), and
[dashboard log](../evidence/task3_dashboard_001.txt) bind the current executions.
Source revision remains `2ef6751a4f393507d13522a505d1070356114779` with the preserved
working changes. Per the no-source-change rule, no new full verification manifest
or software release was manufactured. The existing Task 2 source ZIP still
passes its own 91-file manifest/integrity checks; its original build/inspection
records describe that exact ZIP. This package check cannot repair the separate
Python execution-log binding. Task 3's new report is outside that historical ZIP.

## E. Acceptance matrix

| Acceptance gate | Current status |
| --- | --- |
| OFFLINE_QUALIFICATION_TESTS | PASS, current scoped tests |
| AUTHENTIC_SOURCE_VERIFICATION | BLOCKED |
| RIGHTS_AND_SCOPE_VERIFICATION | BLOCKED |
| CASH_HISTORICAL_STUDY | BLOCKED |
| OPTION_HISTORICAL_STUDY | BLOCKED |
| DHAN_LOCAL_PREFLIGHT | BLOCKED |
| DHAN_AUTHENTICATION | NOT_ATTEMPTED |
| DHAN_SUBSCRIPTION | NOT_ATTEMPTED |
| DHAN_REAL_OBSERVATIONS | BLOCKED |
| DHAN_LIVE_CANDLE_ACCEPTANCE | BLOCKED |
| DHAN_CLEAN_SHUTDOWN | NOT_ATTEMPTED |
| Offline shared engineering controls | PASS for the stated current test scope |
| Production readiness / real execution | BLOCKED / NOT_AUTHORIZED |

Fixture streams, test signatures and study fixtures do not receive real provider
acceptance. Connection state cannot replace candle freshness. Failure blocks
affected LIVE recommendations without simulated, REST or other-provider fallback.
No actual orders, account mutations, Telegram delivery or scheduler activation ran.

## F. Required operator actions

Provide a small authentic original cash OHLCV dataset with its detached publisher
manifest, independently approved publisher root/key record, dated canonical master
and actual rights document plus local operator approval for historical research.
Retain acquisition/publication timestamps and disclose corporate-action treatment.
Configure trust/rights through the existing local engine/operator policy APIs;
dataset and HTTP-supplied flags are not approval. Option studies additionally need
their separate executable historical contract/premium/depth/OI observations.

For Dhan, configure Dhan-specific credentials locally in the application's `.env`
or process environment, following the existing
[runbook](../TRADEPULSE_OPERATIONS_RUNBOOK.md). Set
`DHAN_FEED_INSTRUMENTS_JSON` to exactly one permitted canonical instrument backed
by a verified mapping. Keep paper_sim unchanged, Telegram dry-run and scheduler
disabled. Re-run preflight; only a passing preflight permits the already-authorized
15-second read-only probe. Do not paste credentials into chat or include private
configuration/data in a release ZIP.

## G. Fixed-roadmap status

The six phases remain unchanged: (1) trustworthy data/system foundation;
(2) historical data/strategy validation; (3) live market-data ingestion;
(4) scanner/explainable recommendations; (5) context/dashboard/alerts;
(6) paper trading/performance acceptance/release. This task checks real acceptance
for phases 2 and 3 and verifies existing guards in 1 and 4. Phase 5 remains outside
scope; phase 6 receives evidence-preservation checks, not new release acceptance.
Completion scores and accepted milestone totals were not recalculated.

## H. Immediate next dependency

An operator-approved authentic historical cash-data package containing original
observations, approved publisher trust and documented rights is the next research
dependency. Until it exists, no reproducible real-data cash study can be accepted.
The independent Dhan probe remains gated by its missing local credentials/scope.
