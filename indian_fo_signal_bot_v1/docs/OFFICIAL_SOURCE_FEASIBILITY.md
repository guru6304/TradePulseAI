# Official-source evidence and verifier feasibility

Review date: 2026-10-18. Scope: offline historical archive qualification and public
documentation research. No credentials, broker endpoints, instrument downloads,
Telegram service or orders were used. SDK source was read as text, never executed.

## Decision and provider matrix

No independently checkable archive authentication plus effective-date verification
method was established for any provider in this package. No verifier was added.
All three providers remain **BLOCKED for LIVE historical replay**. This is a finding
about the evidence available to this checkout, not proof that the providers cannot
supply further evidence. Successful structural validation remains insufficient.

| Dimension | Angel One SmartAPI | DhanHQ | Upstox |
|---|---|---|---|
| Source identity | Official documentation is indexed with a master URL; direct documentation access was denied. Endpoint identity is only partially established in this review. | Official instrument documentation and SDK identify the CSV sources. | Official instrument documentation links BOD sources and documents expired-contract queries. |
| Exact-content binding | No provider-bound archive bytes or independently verifiable signature/checksum obtained. | No provider-bound archive bytes or independently verifiable signature/checksum obtained. | No provider-bound archive bytes, signed manifest or captured authenticated response obtained. |
| Capture evidence | None for an instrument artifact. Review date is not its capture time. | None for an instrument artifact. Review date is not its capture time. | None for an instrument artifact. Review date is not its capture time. |
| Historical effective dates | No authoritative record-specific validity interval established. | Expiry is documented; a record-specific historical validity interval is unestablished. | Expired contracts are documented; expiry does not prove listing/start date or the entire lot/token history. |
| Exact replay and warm-up coverage | Unestablished. | Unestablished. | Unestablished, despite a documented route for investigating expired contracts. |
| Implementable verifier now | None supported by the evidence examined. | None supported by the evidence examined. | None supported by the evidence examined. |
| Overall historical status | **BLOCKED** | **BLOCKED** | **BLOCKED** |

Documentation-level source identity is partial progress. It does not earn an archive
the status VERIFIED FOR SPECIFIC SCOPE, or make the overall historical status
PARTIALLY VERIFIED. No actual archive has been qualified.

## Evidence register and limitations

All URLs below were examined through public browsing on **2026-10-18**. This date
records our review/attempt, not server publication, instrument capture or effective
time. No documentation snapshot or provider signature was retained as an authenticated
artifact; linked pages and SDK branches can change. No HTTP Date, Last-Modified or
ETag value was obtained for a master, and none is inferred.

### Angel One

- [SmartAPI documentation](https://smartapi.angelone.in/docs): direct retrieval
  returned an authorization message. Search-indexed official documentation named
  `https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json`
  and an older `angelbroking.com` variant, described daily generation, and mixed
  CSV descriptions with a JSON example. These are indexed documentation claims,
  not an observed master response. Current redirect behavior, format and availability
  were not checked. Neither URL was requested.
- [Provider SDK source, SmartApi/smartConnect.py](https://raw.githubusercontent.com/angel-one/smartapi-python/main/SmartApi/smartConnect.py):
  public Python text exposes authenticated request routes, including candle retrieval.
  Reading those routes neither executes a login nor authenticates an imported master.
  This source examination did not establish a signed historical-master verifier.
- Verification performed: compare indexed endpoint attribution with the provider
  documentation domain; inspect the SDK as text. A fresh official source statement,
  exact-content acquisition proof and record-specific historical authority remain
  necessary. Do not resolve the documentation format discrepancy by assumption.

### DhanHQ

- [Instrument documentation](https://dhanhq.co/docs/v2/instruments/): retrieved HTML
  identifies compact/detailed CSV files at
  `https://images.dhan.co/api-data/api-scrip-master.csv` and
  `https://images.dhan.co/api-data/api-scrip-master-detailed.csv`, plus a segmentwise
  endpoint. Its schema describes identity, segment, lot and expiry fields.
- [Official SDK security module](https://raw.githubusercontent.com/dhan-oss/DhanHQ-py/main/src/dhanhq/_security.py):
  observed constants agree with those URLs. `Security.fetch_security_list` fetches
  content and writes it; that function does not check a publisher signature,
  independently authenticated checksum or historical validity interval.
- [Historical-data documentation](https://dhanhq.co/docs/v2/historical-data/):
  documents candle requests. A historical candle service is not, by itself, proof
  of an imported master record's historical identity.
- Verification performed: cross-check documentation URLs with SDK constants and
  inspect download logic. No CSV/API response was fetched. No historical snapshot
  manifest, capture attestation or validity authority was established.

### Upstox

- [Instrument documentation](https://upstox.com/developer/api-documentation/instruments/):
  retrieved HTML links BOD files, documents daily refresh around 06:00 and removal
  of expired/delisted instruments from the next trading day's BOD file. It warns
  that exchange tokens can be reused. These documented properties mean that a
  current file cannot simply be backdated.
- [Expired futures](https://upstox.com/developer/api-documentation/get-expired-future-contracts/)
  and [expired options](https://upstox.com/developer/api-documentation/get-expired-option-contracts/):
  retrieved documentation describes bearer-authenticated, expiry-specific contract
  queries, contract attributes and a Plus-plan requirement. Samples are not captured
  authenticated responses, and no such query was performed.
- [Expired historical candles](https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/):
  documents use of expired contract keys. This offers a future investigation path,
  not source evidence for an existing local file. Strategy 3 remains blocked even
  if an option contract appears in documentation.
- Verification performed: compare documented identity fields and query scope with
  archive requirements. No master/API response was fetched; provider binding,
  capture provenance and full historical applicability remain unestablished.

No supported signature/checksum/date-authority protocol was found in the examined
material. This bounded observation is not a claim that none exists anywhere.
Searches for those mechanisms produced no usable verifier specification. Successful
API authentication would establish an authorized session; it would not retroactively
authenticate arbitrary submitted bytes. TLS and a local hash alone remain inadequate.

## Execution-path audit

The following are current source locations; production files were not changed.

| Path | Functions and source locations | Qualification boundary |
|---|---|---|
| Byte ingestion | `storage.py:704-720`, `ingest_instrument_master_bytes`; `instrument_archive.py:147-250`, `prepare_archive` | Retains exact bytes and deterministic normalized records; never grants source trust. Caller cannot supply ingestion time. |
| Local file ingestion | `storage.py:722-741`, `ingest_instrument_master_file` | Bounded local import root, traversal/network-path rejection, then the same byte ingestion. |
| Archive inspection CLI | `instrument_archive.py:313-353`, `main` | Ingest/show/list include separate assessment; qualify reports insufficient evidence and exits 1. |
| Stored archive reads | `storage.py:743-781`, `get_instrument_master_archive` / `list_instrument_master_archives` | Reparse original bytes and compare candidate, digests and archive identity on every read. |
| Assessment | `source_qualification.py:36-98`, `assess_source_evidence`; `storage.py:783-802`, `qualify_instrument_master_archive` | Recomputes local facts; always ineligible under current policy. Immutable per-policy insert/compare; saved verdict mismatch fails closed. |
| Declaration lookup | `instrument_archive.py:253-291`, `resolve_archive_declarations`; `instrument_identity.py:202-254`, `dated_identity`; `storage.py:804-812`, `inspect_archived_instrument_identity` | Checks consistency/declared coverage only. Inspection explicitly returns LIVE historical eligibility false. |
| Execution lookup | `storage.py:814-822`, `resolve_archived_instrument_identity`; `instrument_archive.py:294-310`, `resolve_archives` | Revalidates archives and assessment, rechecks requested dates/conflicts, ignores submitted verdicts, unconditionally rejects unsupported source evidence. |
| Direct engine, caller candles or SQLite candles | `backtest_engine.py:1173-1331`, `DeterministicBacktestEngine.run_backtest` | S3 block, acceptance/coverage, dataset validation and strategy eligibility precede the strict resolver. Inline JSON is ingested; archive pins do not bypass it. Full dataset bounds include warm-up before evaluation filtering at 1333 onward. |
| Backtest CLI | `backtest_engine.py:2014-2020,2094-2113`, `main` | Local file or archive ID flows into the same engine. Eligibility rejection exits 2. |
| Backtest API | `server.py:577-696`, `DashboardRequestHandler._handle_post_backtest` | Inline/ID fields feed the same engine; eligibility rejection returns HTTP 422. |
| Readiness and listing | `historical_data.py:928-950`, `evaluate_phase3a_backtest_readiness`; `server.py:474-510`, `_handle_backtest_eligibility` | Overall LIVE readiness is false despite independent receipt/coverage success. Listing is not replay authorization. |

No executable LIVE replay bypass was found among these callers. Pure declaration
helpers can return structurally consistent identities; no engine entry point uses
them as execution authority. Direct use of the low-level assessor does not reparse
the archive, but it also cannot return positive historical eligibility. Previously
saved results may be displayed; reading them does not create new qualification.

`brokers.py` current-master load/refresh/resolve paths operate the active scanner
registry; they neither ingest historical archives nor create source assessments.
Native Angel archive parsing reuses the existing parser offline through `__new__`
with no transport call. Native Dhan/Upstox archive formats remain unsupported.
`config.py` current identifier maps, freshness settings and credential-presence flags
are not historical evidence. `diagnostics.py:682-696` records scoped acceptance only
after actual successful diagnostics; it does not authenticate archived masters.
The receipt policy and database schema were preserved byte for byte.

The local database and its writers remain within the application's trust boundary.
The tests detect inconsistent tampering, including recomputed local digests, and
reject edited saved verdicts. They do not establish resistance to an adversary who
controls application code, its clock and every database row.

## Changes and regression evidence

- `test_bot.py`: added `TestOfficialSourceFeasibility`, its fixture helpers and 13
  test methods. Covers all three providers across direct inline/pinned/SQLite,
  API inline/pinned and CLI pinned paths; asserts no evaluation or result write.
  Adds rehashed-byte and normalized-content tampering, provider/segment/wire-token
  mismatches, missing/reversed dates, warm-up bounds, requested-range changes,
  provenance mutation, stale-policy verdicts and immutable reimport history.
- `README.md`: links this review and the focused verification command.
- `docs/OFFICIAL_SOURCE_FEASIBILITY.md`: this evidence register, audit and decision.

No production functions, parser/policy versions, archive history or saved assessment
formats changed. There is no new supported verifier. Consequently there is **no valid
positive publisher-verifier result to test**. Positive local-integrity checks and
negative unsupported-verifier claims are tested without pretending a fixture proves
authenticity. Expired signatures/trust-root rotation tests require a real verifier
specification and are not claimed as implemented.

Existing source/archive tests additionally cover missing evidence, exact-byte
corruption, gaps, conflicting overlaps despite pins, synthetic/legacy archives,
additive migrations, restart/concurrency, saved-report mutation and old-result
preservation. Prior S3, acceptance, sizing/accounting, isolation, freshness and
identity tests are retained and run by the complete suite.

New class helpers: `setUp`, `_archive`, `_payload`, `_resolve`, `_history`.
The exact added regression methods are:

```text
TestOfficialSourceFeasibility.test_all_providers_reject_claimed_verifier_success_and_archive_pins
TestOfficialSourceFeasibility.test_rehashed_original_bytes_cannot_reuse_an_archive_identity
TestOfficialSourceFeasibility.test_normalized_record_tampering_fails_with_or_without_rehashed_records
TestOfficialSourceFeasibility.test_provenance_metadata_changes_cannot_reuse_a_prior_assessment
TestOfficialSourceFeasibility.test_provider_segment_and_wire_identity_mismatches_are_rejected
TestOfficialSourceFeasibility.test_missing_and_contradictory_dates_cannot_be_supplied_by_verified_claims
TestOfficialSourceFeasibility.test_replay_checks_archive_coverage_before_evaluation_start_including_warmup
TestOfficialSourceFeasibility.test_date_range_change_and_pin_never_reuse_a_coverage_verdict
TestOfficialSourceFeasibility.test_stale_policy_verdict_is_retained_but_never_consumed
TestOfficialSourceFeasibility.test_reimport_with_changed_provenance_retains_prior_archive_and_assessment
TestOfficialSourceFeasibility.test_direct_inline_pinned_and_sqlite_replay_paths_reject_for_every_provider
TestOfficialSourceFeasibility.test_api_inline_and_pinned_replay_paths_reject_for_every_provider
TestOfficialSourceFeasibility.test_cli_pinned_replay_path_rejects_for_every_provider
```

### Executed verification

Python 3.14.6, Windows PowerShell, from `indian_fo_signal_bot_v1`:

| Check | Actual result |
|---|---|
| New feasibility tests | 13 passed, 0 failed |
| Combined feasibility/source/archive selection | 70 passed, 0 failed |
| Phase 3B.1A and 3B.1B | 39 passed, 0 failed |
| Separate SQLite migration/restart/concurrency and history selection | 9 passed, 0 failed |
| Complete strict suite | **320 passed, 0 failed**, 57.307 seconds |
| In-memory top-level compilation | 15 modules passed; no bytecode artifacts |
| Saved-original whitespace/diff checks | 3 files passed, no whitespace errors |
| Saved-baseline content check | Only README/test additions; 37 of 39 baseline files unchanged; one new report, no deletions |

The initial new-class run had 11 passing tests and 2 errors caused by omitted local
`copy` imports in the new tests. Both imports were corrected before all passing
runs above; no application change was involved.

No Python warning or ignored resource exception was emitted by the passing runs.
The complete suite logged exactly three expected `[WARNING]` messages: a scan was
skipped because another scan was already in progress. Error-level messages from
intentional failure fixtures also occur; the corresponding tests pass. The
PowerShell log wrapper rendered unittest's stderr as `NativeCommandError` text;
the Python process exit code was 0. This is shell formatting, not a test failure.

Offline commands actually run (the full command was piped through `Tee-Object`
to retain and inspect its output, and its exit code was propagated):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -W error::ResourceWarning -m unittest test_bot.TestOfficialSourceFeasibility -v
python -B -W error::ResourceWarning -m unittest test_bot.TestOfficialSourceFeasibility test_bot.TestSourceEvidenceQualification test_bot.TestInstrumentArchives -v
python -B -W error::ResourceWarning -m unittest test_bot.TestIndianFOSignalBotPhase3B1A test_bot.TestIndianFOSignalBotPhase3B1B -v
python -B -W error::ResourceWarning test_bot.py -v
```

Separate database/history command:

```powershell
python -B -W error::ResourceWarning -m unittest `
  test_bot.TestSourceEvidenceQualification.test_restart_preserves_versioned_assessment_and_additive_migration `
  test_bot.TestSourceEvidenceQualification.test_policy_assessments_are_idempotent_under_concurrent_startup `
  test_bot.TestInstrumentArchives.test_restart_and_additive_migration_preserve_existing_rows_and_archives `
  test_bot.TestInstrumentArchives.test_concurrent_startup_and_idempotent_ingestion_preserve_evidence `
  test_bot.TestStateIsolation.test_legacy_migration_is_additive_deterministic_and_fails_closed `
  test_bot.TestStateIsolation.test_concurrent_database_writers_dedup_without_cross_scope_mutation `
  test_bot.TestStateIsolation.test_concurrent_schema_initialization_is_safe `
  test_bot.TestOfficialSourceFeasibility.test_stale_policy_verdict_is_retained_but_never_consumed `
  test_bot.TestOfficialSourceFeasibility.test_reimport_with_changed_provenance_retains_prior_archive_and_assessment -v
```

In-memory compilation used `compile(path.read_bytes(), str(path), 'exec')` for
every `Path('.').glob('*.py')`. The saved-baseline check compared SHA-256 hashes of
all original files, then inspected insertion-only diffs for the two modified files.
Whitespace verification uses `git -c core.autocrlf=false diff --no-index --check`
against saved original bytes (empty original for the new report). This workspace
has no Git metadata, so Git status/normal tracked-diff checks are unavailable.
The database/full-suite runs used authorized execution outside the Windows sandbox
because its temporary-directory restrictions affect file-backed SQLite fixtures.
Public browsing was separate from tests; local HTTP test servers used loopback.

## Remaining evidence and next-stage decision

For each provider, obtain evidence that independently binds a particular original
response/archive and its transformation to the provider, and separately establishes
the specific record's applicability over every replay/warm-up date. This must address
provider/segment/identifier, expiry, lot-size changes, token reuse, conflicting
versions and coverage gaps. Neither a filename nor an expiry supplies a start date.

A future mechanism might use provider-signed manifests with an independently
established key, or a controlled authenticated acquisition with independently
checkable capture attestation. Neither mechanism is established here. The latter
would need an explicit trust model for the collector, clock, evidence storage and
attestation key; an operator-entered acquisition record is still a declaration.
Publication and effective-date authority would still require separate evidence.
Any implementation must version assessments while retaining old rows, and bind
verifier version, original/normalized content, provenance and requested applicability.

**Read-only credentialed acceptance:** the offline software is ready to prepare a
separately authorized Angel One acceptance attempt after the required configuration,
current valid master/contracts and prior-session baseline evidence are available.
This review establishes none of those operational prerequisites. Existing diagnostics
must observe and persist all required checks; connectivity alone cannot pass. An
accepted receipt still cannot unlock LIVE historical replay without source evidence.
No blanket readiness or live acceptance is asserted for all providers: the existing
Phase 2C diagnostic producer is Angel-specific, and Dhan/Upstox need their own scoped
acceptance design/evidence before an equivalent claim. No acceptance run was performed.

Unresolved questions require artifacts or provider clarification: current Angel
documentation/access and master format; independently verifiable acquisition/binding
for each source; authoritative historical record/lot/token intervals; available
historical snapshot coverage; Upstox expired-response temporal semantics and account
entitlement; and actual operational diagnostic observations. Do not replace any of
these with a manual VERIFIED flag. Performance research remains premature.
