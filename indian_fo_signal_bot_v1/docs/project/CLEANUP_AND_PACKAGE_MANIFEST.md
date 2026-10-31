# Track A cleanup and package manifest plan

Date: 2026-10-29 (Asia/Kolkata). Mission: `TPA-MAIN-RECOVERY-TO-RELEASE-20261029-V3`. Tasks: `H01`, `F02.2`, `WS-PACKAGING`. Authoritative progress: [TRADEPULSE_MASTER_STATUS.md](TRADEPULSE_MASTER_STATUS.md). Security dependencies: [SECURITY_REVIEW.md](SECURITY_REVIEW.md).

**V3 artifact status: NOT_BUILT / NOT_INSTALL_VERIFIED.** This is an allowlist and retention proposal, not a generated package manifest, cleanup authorization or release claim. Only this document was created. Existing public inventories/receipts, packaging source and dependency pins were read; no package, deletion, directory relocation, test execution, private payload scan, operational database access or environment-value inspection occurred. Canonical verification is active; do not clean caches or change source underneath it.

## Historical evidence, kept separate from V3

| Evidence | Historical result | Meaning and limit |
|---|---|---|
| `docs/evidence/phase6_release_inspect_20261024_01.json`; `phase6_release_manifest_20261024_01.json`; `phase6_release_20261024_01.zip` | Inspection PASS, 122 files; archive SHA-256 `ac0839aaf327f7e4fea1fc927b6e46ee886bf327a982ab9847a02239c2600296` | Historical offline candidate, publisher authentication NOT_ESTABLISHED. Inspection receipt was read; archive was not rebuilt, launched or revalidated here. It predates subsequent source changes and is not V3. |
| `docs/evidence/astra_cleanup_inventory_20261029_01.json` | Read-only inventory: 105 cache candidates, inventory size 4,557,163 bytes; 274/274 images hash-bound; no image deletion candidates | Classification at its recorded time, not a current tree scan. |
| `docs/evidence/astra_cleanup_dryrun_20261029_01.json`; `astra_cleanup_apply_20261029_01.json` | Dry run/apply retained; apply PASS: 105 files and 4,566,808 actual bytes removed; zero tracked files/images removed | Use actual receipt quantities, not inventory bytes, for deletion totals. Two empty cache directories were removed under the original policy. Do not reuse this old target list. |
| `docs/evidence/astra_cleanup_inventory_b01_vwap_20261029_01.json`; `astra_cleanup_b01_vwap_dryrun_20261029_01.json`; `astra_cleanup_b01_vwap_apply_20261029_01.json` | Fresh inventory/apply: 103 files, 4,516,743 bytes; apply PASS, zero tracked files/images removed | A separate post-verification cleanup. Its inventory binds the prior inventory. Do not combine these counts into a claim about current cache occupancy or unique lifetime files. |

Both cleanup apply receipts preserve the unknown access-denied history directory as `PRESERVED_UNINSPECTED`. The first image inventory binds historical evidence; no new complete image enumeration or count is claimed. New screenshots may exist after that inventory.

## Retention and release-exclusion policy

| Category | Developer/source workspace | Proposed customer artifact |
|---|---|---|
| Runtime source and actual served assets | Preserve current files and uncommitted work; no branch reset, merge or source move | Exact frozen allowlist and per-file hashes only; no recursive workspace copy |
| Tests, verification tools, receipt helpers and fixtures | Preserve; run from developer verification environment when authorized | Exclude test suites and developer-only runners; verification reports remain outside the artifact |
| Reports, checkpoints, old archives, screenshots and 274 historically bound images | Preserve existing paths/bytes and hash references; retain historical failures | Exclude `docs/evidence/`, `docs/reports/`, internal checkpoints, old archives, screenshots and private audit material |
| `.env`, credentials, private `.local` inputs, trusted/licensed datasets, operational DB and `-wal`/`-shm`, logs and account state | Preserve in place; do not read/copy them into the model, staging or reports | Exclude all; no preexisting user DB or provider credentials; generate empty schema in a separate user-data location only on first startup |
| `.venv*`, `node_modules`, installed developer dependencies and caches | Preserve required environments/dependencies; ignored does not mean disposable | Exclude workspace environments and development caches. Only deliberately packaged, redistributable runtime dependencies with provenance may enter a staged runtime distribution |
| `.local/astra_browser_assets_20261027_01` and retained asset/license evidence | Preserve its 20 bound asset/license files; required for reproducible historical browser checks | Do not copy the cache wholesale. Select approved runtime assets/licenses into explicit package paths, with references and hashes |
| `task2_history_m24ad64e` | Preserve uninspected; no ACL takeover or guessed classification | Exclude completely; its contents are not needed or declared safe |
| Generated project bytecode | New inventory after active processes stop; review before any later deletion | Exclude `__pycache__`, `.pyc`, `.pyo`; do not perform cleanup to make a release copy |
| Git, CI, research drafts and duplicate historical variants | Preserve repository evidence and branch work | Exclude `.git`, repository-only CI metadata, research drafts and unrelated images/documents |

New cleanup requires an immutable inventory of exact immediate `.pyc`/`.pyo` targets under the two previously approved project cache roots, tracked-file exclusions, containment/type/reparse guards, dry run, and exclusive receipts/logs. Unknown/private/dependency directories are not cleanup targets. Source preservation and a minimal customer artifact are achieved by isolated staging, not by deleting developer evidence.

## Existing builder is not the V3 customer allowlist

Source inspected: `release_management.py:ReleasePackager`. At review time it declares **43 CORE_MODULES**, **3 REQUIRED_ASSETS** and **34 PUBLIC_DOCUMENTS**. `build_bundle` also includes root `test_*.py`/`test_*.js`, README and the public-document list. `inspect_bundle` requires test files and the legacy scope. This is intentional historical developer/offline-verification packaging; it does **not** meet V3's minimal customer-package requirement.

`LOCAL_ONLY_MODULES` explicitly excludes `verify_live_quick.py`; preserve this operator-owned helper but never ship or execute it as acceptance proof. A metadata version such as `1.0.0-release-candidate` or `runtime compatible` does not prove installation, genuine live acceptance, publisher authenticity or public launch approval. The declared Python 3.10–3.14 range is a code compatibility declaration, not clean-install evidence for every interpreter/platform.

## Proposed V3 runtime allowlist — not yet built or dependency-closure verified

Preserve the current flat layout. Start from the existing registered module set to avoid silently dropping F&O, lineage, recovery or historical functionality. The proposed runtime source candidates are the following **41 modules**, excluding `verify_offline.py` and `performance_acceptance.py` from the customer's runtime. Developer verification continues to retain them. Before finalizing this proposal, prove import/CLI closure and supported operations from staging; classify support/diagnostic modules by actual use rather than deleting them speculatively.

```text
config.py                    brokers.py                  diagnostics.py
scanner_engine.py            server.py                   instrument_identity.py
paper_portfolio.py           paper_triggers.py           vwap_paper_triggers.py
historical_data.py           backtest_engine.py          forward_paper.py
readiness_policy.py           research_protocol.py        source_qualification.py
storage.py                   strategies.py               strategy_evidence.py
opportunity_ranking.py        rank_history.py             upstox_diagnostics.py
telegram_bot.py              configuration_check.py      instrument_archive.py
release_management.py         candle_lineage.py           contract_universe.py
historical_pagination.py      notification_outbox.py      publisher_trust.py
option_execution.py           option_observations.py      benchmark_observations.py
historical_study.py           dhan_feed.py                dhan_feed_control.py
angel_feed.py                 angel_feed_control.py       angel_history_capture.py
context_data.py               context_workflow.py
```

Including modules does not authorize their provider/stream/send capabilities. The supported default launch must enforce offline/paper-only safety. Existing `release_management.py` still describes the older broader bundle; including it as an operations dependency is conditional on the final closure/CLI assessment and does not make its old bundle command the V3 release builder. Any adjustment requires source review and tests after freeze.

Additional allowlisted package categories:

- Actual production `public/index.html` plus exact locally bundled CSS/JS/fonts/icons required by the final served UI, each with permitted redistribution/license metadata. The current page's remote Tailwind/Chart/font requests are an open offline-release dependency, not a finished asset bundle.
- `requirements.txt` and an approved names-only `CONFIG_EXAMPLE.env`. Do not copy `.env`. Review any shipped example for effective safe defaults and the V3 names-only requirement; the existing `.env.example` is not automatically approved for this new artifact.
- One verified Windows x64 launcher/start-stop-status path and a deliberate application-data directory for mutable state. Launcher names, runtime bundling method and release version are **TBD pending proof**.
- A compact customer documentation set: README, INSTALL_AND_START, CONFIG guidance, OPERATIONS, SECURITY, RELEASE_NOTES, current STATUS/limitations, and required LICENSE/NOTICE files. These are proposed outputs; the 34 old reports are not copied as a substitute.
- `build-manifest.json` containing relative path, bytes and SHA-256 for every shipped file, source fingerprint, build command/runtime versions, dependency/license manifest or SBOM, and declared offline/paper limits. No private path, value or account payload.

Do not use an extension-only wildcard, arbitrary `public/**` copy, or recursive repository ZIP as a release allowlist. Reject unlisted/symlink/reparse/escaped entries in staging and archive inspection. Detailed evidence lives in the developer repository, linked from concise public operating guidance.

## Current dependency pins and distribution decision

`requirements.txt` currently pins:

| Dependency | Exact local pin |
|---|---|
| cryptography | 50.0.2 |
| cffi | 2.1.1 |
| pycparser | 3.11 |
| tzdata | 2026.5 |
| websockets | 15.0.1 |

Pins alone are not a complete hash lock, license/SBOM inventory, vulnerability assessment, wheel provenance record or offline installer. No packages were installed/downloaded or dependency folders inspected here. Stage only platform/interpreter-matched permitted runtime dependencies; document their source, hashes, license notices and transitive closure. Do not copy the active virtual environment into the artifact.

Target is one Windows x64 personal-use distribution. Decide between a genuinely bundled runtime and a pinned source/runtime installer using clean-room evidence; no self-contained or one-click claim is currently justified. A source package needing Python/dependency installation must state that prerequisite honestly. An offline installer requires already permitted bundled runtime/wheels and a verified no-network installation path, not an assumption that pip will have network/cache access.

## Release gate checklist and required manifest fields

1. Freeze source only after required engineering/security/UI acceptance; record HEAD plus dirty-source fingerprint and exact approved files. Keep evidence/source outside an isolated empty staging directory.
2. Produce deterministic per-file size/hash metadata, reviewed dependency/license provenance and a declared supported Windows/Python/runtime profile. Repeated bit-for-bit reproducibility is a separate test, not inferred from fixed ZIP timestamps.
3. Build one new uniquely named candidate without overwriting history. Check the actual archive's path set, sizes and bytes against its manifest; reject traversal, duplicate names, links, unexpected executables and all excluded private/developer categories. Secret-value checks must operate locally without disclosing values or fingerprints.
4. Install/extract the actual artifact into an isolated empty environment with network disabled, no source-directory/module leakage, no broker credentials and no existing DB. Verify loopback binding, safe defaults, all destinations/no-source/demo behavior and actual browser screenshots; assert zero provider/order/send dispatch and clean shutdown.
5. Exercise first-run schema, data-directory permissions, duplicate process behavior, isolated backup/restore, upgrade and rollback preserving synthetic user data. Do not mutate or copy operational state to perform this proof.
6. Record artifact byte size/SHA-256, source/build/dependency metadata, negative exclusion cases, install/launch/browser/restore results and remaining limitations in developer evidence. Customer archive contains concise operating docs, not raw evidence or screenshots.
7. Publish only one final `dist/` artifact plus small checksum/manifest/release-note metadata **after** successful acceptance and owner-authorized delivery. Suggested naming is provisional: `TradePulseAI-<version>-windows-x64.zip`. No artifact/path/version is claimed to exist by this document.

Use `RC_INSTALLABLE_OFFLINE` only after observed package/install acceptance. Until then use `NOT_BUILT`, `INTERNAL_PREVIEW` or the actual failing/unverified gate. X01 historical/OOS, X02 genuine authorized scanner and X03 public/commercial clearance remain separate; an installable simulation candidate grants none of them.
