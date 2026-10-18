# TradePulse AI historical provenance design and feasibility

Phase 5A review date: 2026-10-18. This work inspected the existing source, retained
feasibility reports and deterministic tests. It made no network request, downloaded
no instrument artifact, inspected no credentials and changed no production source
qualification or replay policy. The [Phase 5A engineering report](TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md)
owns final integrated results; counts below are the provenance workstream's executed
selections, which overlap the complete suite.

**Decision: historical source qualification remains BLOCKED.** The current tree has
no supported publisher-authenticity or authoritative effective-date verifier. No
independently authenticated master artifact or acquisition attestation was supplied
to this workstream. A positive verifier would therefore require an invented trust
root or a caller declaration. No such verifier was implemented. This is a limitation
of the available evidence and implementation, not proof that providers cannot supply
additional evidence.

## Existing evidence and execution path

| Boundary | Current implementation and established fact | What it does not establish |
| --- | --- | --- |
| Byte import | `SQLitePersistenceStore.ingest_instrument_master_bytes` calls `prepare_archive`, stores exact bytes and deterministic candidate JSON, and retains rejected/incomplete candidates. Local-file import constrains the import root and byte count. | The caller's provider, URL, filename or source description does not authenticate the bytes. `INLINE_SERIALIZATION` is a local transformation rather than an original provider response. |
| Archive identity | `prepare_archive` records original SHA-256, normalized-record SHA-256, parser/schema version and provenance metadata in the archive identity. Ingestion time is locally generated, retained on idempotent retries and excluded from that identity. | Matching hashes prove local consistency, not publisher identity. Capture/publication timestamps are timezone-aware declarations, not independent clock evidence. |
| Read validation | `get_instrument_master_archive` reparses retained original bytes with retained metadata and compares the reconstructed candidate, archive ID and stored status before exposing the archive. | This detects inconsistent corruption/substitution; it does not protect against an actor controlling the application, every database row and its trust configuration. |
| Record/date inspection | `resolve_archive_declarations` checks provider, exchange/token, contract facts, conflicting overlapping claims and full requested-date coverage. `dated_identity` checks the requested identity, instrument type and applicable dated contract/lot facts. `inspect_archived_instrument_identity` explicitly reports historical eligibility false. | `ELIGIBLE_LOCAL_RESEARCH` and `SOURCE_DECLARED_ARCHIVE_COVERAGE` are structural/declaration statuses. They are not permission to execute LIVE replay. Capture date and expiry cannot supply an authoritative listing/start date or missing lot/token history. |
| Source assessment | `assess_source_evidence` distinguishes integrity, declared source/capture/publication dates, local ingestion time, submitted qualification claims and missing authority. It always returns `historical_eligibility.allowed=False` under `historical-source-evidence-v1`. | There are no supported signature, authenticated-acquisition, date-authority or trust-expiry validators. The documentation review date is not artifact capture time. |
| Assessment retention | `qualify_instrument_master_archive` recomputes the assessment after archive validation, stores it by archive ID/policy version and rejects a differing existing current-policy payload. Historical policy rows remain retained. | A saved `allowed`, `verified`, signature-shaped field or stale policy row is not an execution credential. Current qualification never imports a caller's verdict. |
| Strict execution resolution | `resolve_archived_instrument_identity` and `resolve_archives` recheck scope/coverage and current assessment; the strict resolver rejects unsupported source evidence even if a supplied qualification dictionary claims success. Archive pins select evidence; they do not bypass conflict or qualification checks. | An inspectable declaration cannot become accepted history by changing the API caller or selecting a different archive ID. |
| Replay entry points | `DeterministicBacktestEngine.run_backtest` enforces strategy support, acceptance/coverage, historical OHLCV/session validity and eligibility, then resolves an archived instrument over the entire validated dataset, including warmup, before any evaluator call. Inline, stored and CLI/API paths converge here. | A current quote, accepted cash diagnostic, complete bar count or evaluation-only date range cannot authenticate earlier warmup identity/history. Historical Strategy 3 is independently rejected before archive processing. |

The archive V1 parser currently supports normalized EQ, INDEX_SPOT, FUTIDX and
OPTIDX records with its existing type-specific restrictions; executable historical
identity remains limited to dated NSE equities and explicit index futures. Native
Angel JSON snapshots reuse the existing parser offline but carry unknown effective
dates and remain incomplete for replay. Native Dhan/Upstox archive formats are not
supported by this parser. A new current-contract structural boundary elsewhere in
Phase 5A must not silently extend historical trust or this execution scope.

`readiness_policy.execution_gate` is an acceptance/coverage decision, not the final
archive authenticity check. For `HISTORICAL_RESEARCH`, valid complete fixture bars can
produce `execution_gate.allowed=True` while `evaluate_phase3a_backtest_readiness`
keeps `phase3_ready_for_execution=False`; the engine subsequently rejects insufficient
source evidence before strategy evaluation or result persistence. These fields must
remain distinct in reports. `LIVE_ACCEPTED` additionally requires its independent
persisted, scoped diagnostic receipt and stored-history requirements. The narrow
Upstox/Angel cash commands do not issue that receipt.

## Evidence contract for a future verifier

The following is a design, not a new accepted artifact format or an implemented
positive verifier. Extend the existing archive and versioned-assessment mechanisms
only after an actual source mechanism is established; do not create a competing
archive pipeline.

| Evidence dimension | Required retained facts and binding | Existing implementation / remaining work |
| --- | --- | --- |
| Exact content and transformations | Original response/file bytes, encoding/compression format, original digest, normalization/parser/schema version, normalized digest, and deterministic relationship between original and normalized records. Preserve original bytes before converting native formats or stripping a BOM. | Exact JSON bytes and deterministic normalization already exist. Native-format expansion requires provider-specific parsing plus tests; a normalized wrapper alone is not original acquisition evidence. |
| Acquisition context | Provider and publisher identity, independently established source endpoint, explicit request scope, collector identity/version, capture method, response artifact ID, retained safe source metadata and binding to the exact original digest. Record transforms separately. | Current source URL/reference and input kind are declarations. No collector or independently checkable acquisition proof exists. Never retain credentials, authorization headers, secret query parameters, account responses or complete request objects. |
| Publisher trust | A documented verification mechanism and a trust root established independently of the submitted artifact. Define publisher/segment authority, accepted algorithms, key identity, validity/rotation/revocation and failure policy. | No supported protocol or independently established publisher key was found in the retained evidence. A submitter's public key, certificate-shaped JSON or `signature_valid=true` supplies no authority. |
| Capture/publication time | A defined clock/attestation trust model binding capture time to original bytes and source; publication time must be separately evidenced where required. Distinguish source event time, capture time, local ingestion time and verifier evaluation time. | Timestamps are currently retained declarations or local observations. A future signature proves only the claims its authenticated signer is authoritative to make. HTTP Date/ETag/Last-Modified alone would not establish historical instrument validity. No such headers were newly observed here. |
| Instrument identity | Exact provider, exchange/segment, underlying/canonical symbol, provider identifier, type, applicable contract symbol/expiry/strike/side/lot/multiplier/units and master source revision. Bind the requested record to the authenticated artifact. | Existing record/identity parsers check consistency. Supported fields and types vary by source; do not infer a contract token from a spot identifier or a lot from a default. |
| Effective-date authority | Independently supported instrument-specific intervals for identifier assignment, listing, expiry, lot/multiplier changes and other material facts. Establish the publisher's authority for that date and segment. Cover every replay/warmup date, not just evaluation dates. | Current intervals are declarations. An expiry supplies an end constraint, not a listing/start date or an entire identifier/lot history. Capture time cannot backdate a current snapshot. Conflicting overlaps fail rather than choosing the newest file. |
| Candle dataset provenance | Bind original historical candle responses, request/provider/instrument/interval/date scope and transforms to the retained dataset digest, in addition to the master evidence. Preserve completion/session/order/coverage checks and point-in-time access. | Existing historical manifests and validators establish local consistency and data quality. A qualified master would not independently authenticate arbitrary candle bytes labelled with its provider. Trustworthy acquisition of historical prices remains a separate research prerequisite. |
| Reproducible decision | Archive/original/normalized/dataset digests; exact requested instrument, date and warmup scope; verifier implementation/version; policy version and effective policy window; trust-root/revocation material; evaluation clock convention; deterministic decision/reasons. Retain prior decisions without granting them current authority. | Archive/policy assessment retention exists. No actual verifier version, trust window or revocation protocol can be specified as implemented until a supported mechanism exists. A positive cached decision must never be reusable across changed bytes, provider, instrument, date, policy or authority material. |

Two potential mechanisms remain **unestablished options for investigation**:

1. A provider-signed manifest that binds exact artifact bytes and authoritative
   record intervals, with an independently obtained, supported publisher trust root.
   No such manifest, signature algorithm, key distribution or date-authority protocol
   was established in this checkout. Do not fabricate one from a sample.
2. A controlled provider acquisition with independently checkable capture
   attestation. Its collector, trusted clock, transport/source identity, attestation
   key and evidence retention require an explicitly reviewed threat model. Ordinary
   HTTPS fetching plus a locally written hash is not that attestation; a local
   operator's typed capture record remains a declaration. Capture authority also
   does not by itself establish every historical record's effective dates.

The next implementation decision depends on obtainable artifacts and a defensible
trust boundary, rather than a preference for a particular cryptographic library.

## Provider feasibility from retained local evidence

This review reuses [the retained official-source feasibility assessment](OFFICIAL_SOURCE_FEASIBILITY.md).
That earlier report records public-documentation research and its limitations. No
page, API, master download, endpoint entitlement or provider response was freshly
verified in this workstream. Treat its provider descriptions as investigation leads,
not current operational facts.

| Provider | Local evidence / supported path | Missing evidence and smallest next investigation |
| --- | --- | --- |
| Angel One | Existing native master parser and normalized local archive ingestion. Earlier feasibility research recorded a documented master location but could not establish independently authenticated historical snapshots/effective intervals. | Obtain an actual appropriately authorized source artifact and source/publisher statement describing exact-content binding and historical date authority. A current undated JSON snapshot cannot cover prior dates merely because capture time is supplied. |
| Dhan | Normalized archive schema can retain caller-supplied dated records. The retained documentation review describes public instrument CSV sources and expiry fields; native archive CSV ingestion is absent. | Establish an actual authoritative capture/authentication mechanism and instrument-specific historical applicability; specify native parsing only from supplied defensible examples. URL agreement with an SDK and an expiry field are insufficient. |
| Upstox | Normalized archive schema; retained research describes BOD and expired-contract APIs and warns about token reuse. The current cash diagnostic remains distinct. | Establish authorized source availability, exact-content/acquisition evidence and record-specific listing/identifier/lot applicability. An expired-contract example or a present BOD file cannot authenticate a caller's archive or backfill its entire date history. |

None of these paths currently supports a positive historical qualifier. No claim is
made that a provider lacks every possible suitable source; the missing mechanisms
and artifacts have simply not been established here. A successful separately
authorized RELIANCE quote/candle diagnostic would address current cash-data scope
only and would leave every historical item above unresolved.

## Threat model and rejection behavior

| Threat | Existing boundary and Phase 5A regression |
| --- | --- |
| Forged `verified`, signature, certificate/key or date-authority declarations | No supported verifier is selected from caller input. New tests submit forged trust windows/key claims for all providers; both expired and future windows remain unsupported and ineligible. These tests are not cryptographic expiry/revocation verification. |
| Matching hash used as publisher proof | Integrity remains explicitly local. New exact-byte/BOM/newline/format variants share normalized facts but retain distinct original bytes/archive identities, with no authenticity promotion. |
| Substitution of raw bytes and normalized records with recomputed hashes | Reconstruct the immutable archive ID from retained bytes/metadata. A self-consistent replacement retained under an older archive ID fails before assessment; no old verdict can follow it. |
| Cross-instrument/provider substitution | Symbol/token/date/provider must agree. New swapped-token requests reject as ambiguous, foreign provider pins cannot select another provider's archive, and the same token reused for another symbol in a later interval cannot cover a crossing request. |
| False capture/publication or source metadata | Retain as declarations without source authority. New contradictory publisher URL/future timestamp claims remain untrusted; a changed capture context gets a new archive identity and cannot reuse the first assessment. |
| Foreign, edited or expired assessment | Recompute current assessment and compare its full payload under the current archive/policy key. A report from another archive fails; unsupported expired-policy rows are retained but cannot authorize execution. Actual trust-policy expiry/key rotation would require the missing real verifier specification. |
| Missing date coverage hidden by a pin or verified claim | Resolve requested scope before qualification. Capture/publication fields and claimed independently verified intervals cannot supply absent record coverage or warmup dates. Pins do not override conflicting source facts. |
| A valid input/diagnostic reused as replay authorization | New end-to-end gate tests provide valid full-session bars but assert overall source readiness false, strict replay rejected, no evaluator/result writer called, and historical Strategy 3 independently blocked for all providers. |

The local SQLite database, its writers, application code and local clock remain
within the existing trust boundary. Tests that intentionally corrupt rows establish
inconsistent-tampering detection, not resistance to a fully privileged adversary.
Supporting a stronger threat model would require protected trust configuration,
independent evidence retention and an explicit operational design.

## Changes and executed tests

Only the new `test_phase5a_provenance.py` and this design document belong to this
workstream. `source_qualification.py`, archive parsing, policy versions and production
historical gates were not changed. The twelve new methods use the existing unittest
bootstrap, controlled synthetic declarations, in-memory SQLite and a forbidden
external-transport guard. They call the real archive store, assessment, identity
lookup and replay gates. No fixture represents authentic publisher evidence.

Executed from the project directory on Windows PowerShell, Python 3.14.6:

```powershell
python -B -W error::ResourceWarning -m unittest test_phase5a_provenance -v
python -B -W error::ResourceWarning -m unittest test_phase5a_provenance test_bot.TestOfficialSourceFeasibility test_bot.TestSourceEvidenceQualification test_bot.TestInstrumentArchives -v
```

| Selection | Fresh result | Exit |
| --- | --- | ---: |
| New provenance module | 12 passed, 0 failed, 0 skipped; 0.135 s | 0 |
| New module plus existing feasibility/source/archive classes | 82 passed, 0 failed, 0 skipped; 1.616 s | 0 |

Both passing runs emitted no Python warnings or application warning records. The
combined run used approved execution outside the Windows sandbox for the existing
temporary-file/SQLite fixtures. No production database was used. The initial new-only
run failed three subcases because new tests expected a later rejection reason;
inspection confirmed the existing earlier ambiguity/coverage gates were correct.
Only those new exact reason expectations were corrected; no application behavior or
existing assertion/filter was changed. Root integration owns `test_bot.py` discovery
registration, complete-suite totals, final compilation and baseline/diff checks.

## Exit criteria and next action

Historical replay remains blocked until all relevant independent requirements pass:

1. Obtain actual source artifacts and a documented, reviewable authority mechanism
   binding exact content to the publisher and the needed historical segment/dates.
2. Establish the real trust root, acquisition/clock/retention model and authoritative
   record interval semantics; explicitly address token reuse, lot changes and expiry.
3. Implement the smallest verifier against that mechanism, including genuine valid,
   tampered, wrong-publisher, expired/revoked, wrong-scope and changed-policy examples.
   Extend existing immutable evidence/assessment storage rather than trusting flags.
4. Independently qualify historical candle acquisition, complete session/warmup
   coverage, receipt scope where required and reproducible research date separation.
5. Release only the exact accepted cash/futures scope after integrated gates pass.
   Historical Strategy 3 additionally requires its missing exact option-contract
   fills/accounting engine and remains blocked even after master qualification.

**Next action:** acquire a defensible sample evidence package and its source/trust
specification for one historical cash instrument/date range. Until that evidence is
available, continue safe offline work and retain the existing fail-closed policy;
adding a manual acceptance flag, downloading a current master or switching brokers
cannot satisfy this dependency.
