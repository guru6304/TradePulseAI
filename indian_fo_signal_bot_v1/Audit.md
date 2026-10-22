TRADEPULSE AI — PHASE 4A EXECUTION PROMPT
Publisher Trust, Effective-Date Verification, Replay Gating, and Measurable Forward Progress
You are working inside the current TradePulse AI repository as its implementation owner. Execute real code changes and tests. This is not an audit-only assignment, and it is not permission to rewrite the roadmap or restart the baseline.
1. Product end goal — do not lose this context
TradePulse AI must become a dependable, explainable, evidence-driven Indian-market trading-intelligence system for both NSE cash equities and F&O. Its complete target includes trustworthy live and historical data, exact instrument identity, robust candle validation, transparent ranked signals, portfolio-level risk controls, reproducible backtests, realistic dated-option execution, safe paper trading, API/dashboard/notifications/EOD, recovery, monitoring, secure deployment and release operations.

The aim of discovering credible cash-equity momentum opportunities—including possible 5–10% moves without requiring a gap-up—is a research hypothesis, not a return guarantee. Never fabricate prices, source authenticity, fills, historical premiums or trading results. Do not place real orders.

Keep telegram_dry_run=true, enable_background_scheduler=false, live order placement disabled, and live broker requests off unless a separate, explicit operator authorization covers a narrowly defined read-only test. Do not paste or print secrets.
2. Verified handover checkpoint
Use docs/reports/TRADEPULSE_COMPLETE_PROJECT_HANDOVER.md as the current source map and docs/TRADEPULSE_EXECUTION_LEDGER.md as the continuation checkpoint.

The handover reports:
- Branch main; reported HEAD f9488168468819fd3706dbb1cfb5ab616e10c241 (verify the real HEAD once only because repository state may have advanced).
- Offline testing readiness: PASS for its declared scope.
- Latest accepted evidence: docs/evidence/master_final_accepted.json; 722/722 Python test cases, 10/10 Node dashboard checks, 51 Python files compiled, evidence validation returned exit 0.
- Official rubric scores: implementation 64.25%, verified readiness 37.00%, zero of 12 whole milestones accepted.
- Active continuation: Phase 4A publisher trust/effective-date verification in source_qualification.py and instrument_archive.py.
- Strategy 3 historical option execution is still unimplemented (HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED).
- Live read-only acceptance has not been run/authorized in the current accepted checkpoint. Real trading is NOT AUTHORIZED.
Those are handover claims. Preserve the reports/logs as historical evidence and do not claim the 722-test suite was rerun in this task unless it really was. Confirm the working tree, staged/unstaged changes and HEAD before touching code, then continue. Do not do another full baseline audit.
3. Execution rules — measurable work, not endless phases
1. Read the existing handover, execution ledger, source_qualification.py, instrument_archive.py, readiness_policy.py, historical_data.py, historical_pagination.py, relevant contract/archive tests and verify_offline.py. Read enough source to understand the current interfaces, then implement.
2. Preserve all staged, unstaged and untracked user work. Never use git reset, git clean, blanket checkout, or destructive cleanup. Do not modify historical logs to make a result look green.
3. Do not create another master roadmap, another broad audit, or multiple duplicate reports. Append a concise evidence-backed entry to the existing execution ledger and update only the directly relevant official report/matrix if a gate or rubric threshold genuinely changes.
4. For every discovered defect: reproduce it with a focused test, fix it, add a regression test, run the target test and relevant regressions, and retain the exact command/result/log.
5. Do not weaken an assertion to pass tests. Do not call mocks or synthetic fixtures live/qualified evidence.
6. Continue through independent local tasks when an external publisher artifact, key, license or broker authorization is unavailable. Record precisely what is blocked and keep implementing everything that can be proven offline.
7. Report engineering progress separately from official rubric score. Never manufacture a score increase. The task is not complete merely because a report was generated.
4. Phase 4A task — design and implement a real fail-closed trust verifier
4.1 Define the verification contract
Inspect the current schemas and public interfaces first. Design a versioned, explicit signed artifact/manifest contract that binds at least:
- Publisher identifier and trusted key identifier.
- Artifact type and schema version.
- Exact artifact bytes through a cryptographic digest.
- Exchange, market segment, instrument/contract scope and record coverage where applicable.
- Publisher publication time, capture/observation time and effective-from/effective-until times as distinct fields.
- Source/version identity, applicable rights/licence evidence or a documented independently validated entitlement reference.
- Signature algorithm/version and signature bytes.
Canonicalization, digest algorithm, signature input, date/time representation, trust-policy version and verification result must be deterministic and documented. Reject duplicate/ambiguous manifest keys and unsupported schema or algorithms.

Do not conflate these concepts:
- A SHA-256 digest proves correspondence to a known byte sequence, not publisher identity.
- A publisher URL, filename, version, timestamp or verified=true flag is a declaration, not proof.
- A valid signature authenticates the signed material to a key; it does not by itself prove the publisher is authoritative, the data is licensed, or a publisher-claimed time is objectively true.
- Capture time, publication time, key validity and artifact effective dates have different meanings and must be checked separately.
4.2 Use appropriate cryptography
A publisher digital signature verified with a public key must use a vetted asymmetric signature implementation. HMAC uses a shared secret and is not interchangeable with a publicly verifiable publisher signature. Do not write custom RSA/ECDSA/Ed25519 cryptography.

Inspect available dependencies/runtime support. Prefer a well-maintained, pinned cryptographic library (for example, Python cryptography for a supported asymmetric scheme) if no suitable audited verifier already exists. If introducing a dependency, explicitly update the dependency declaration and CI installation steps for the existing Python 3.10–3.14 matrix, and test the declared support range as far as the available environment permits. Do not silently claim the project remains standard-library-only after introducing it. If dependency installation is unavailable, implement the clean interface and fail-closed handling where feasible, record the exact environment blocker, and continue independent work; never silently substitute HMAC or homemade crypto.

Trust anchors must come from a separately controlled local trust configuration, not from the artifact being verified. A signed artifact cannot choose or add its own trusted public key. Support policy version, permitted algorithms/types/scopes, key activation/expiry, explicit revocation and reviewed key rotation. Unknown or absent trust anchors must fail closed.

Synthetic keys may be generated only inside isolated tests. They must be unmistakably test-only and must never be installed in the production trust store or qualify genuine artifacts.
4.3 Fail-closed assessment behavior
Implement PublisherTrustVerifier or an equivalently named abstraction in the existing architecture. Integrate it into assess_source_evidence and instrument_archive.py:resolve_archives, plus the historical replay/eligibility gate. Preserve current public interfaces where reasonably possible; document justified schema/API changes.

Return structured, sanitized reason codes, such as UNKNOWN_PUBLISHER, MISSING_TRUST_ANCHOR, UNSUPPORTED_SIGNATURE_ALGORITHM, INVALID_SIGNATURE, ARTIFACT_DIGEST_MISMATCH, REVOKED_KEY, TRUST_ANCHOR_NOT_VALID, UNSUPPORTED_ARTIFACT_SCHEMA, OUTSIDE_EFFECTIVE_DATE_RANGE, MISSING_RIGHTS_EVIDENCE, CONFLICTING_ARTIFACT, UNTRUSTED_PUBLISHER_SIGNATURE and VERIFIER_UNAVAILABLE. Use exact existing reason-code conventions where they already exist.

Reject at least:
- Unknown publisher and absent/untrusted trust roots.
- Missing, malformed or invalid signature.
- Any modified artifact byte or changed signed field.
- Unsupported schema, artifact type, key or signature algorithm.
- Key not yet valid, expired or revoked at the relevant verification time.
- Invalid, future or out-of-scope effective dates and time ambiguity.
- Missing required rights/qualification metadata.
- Conflicting artifacts that purport to cover the same publisher/scope/effective interval.
- Stale/foreign/modified assessment receipts, changed archive bytes, or any attempt to promote a cache solely because its own hash is consistent.
Enforce scope matching to provider, exchange, segment, instrument/contract identity and date coverage. An authenticated artifact must not qualify records outside the signed coverage. Do not infer historical coverage from capture time. An archive must not become replay eligible just because it was retained successfully.

Where objective publisher-time proof is not available, record publisher-signed dates as signed claims, not independently timestamp-verified facts. If the product requirement calls for an independent trusted timestamp, specify and implement the appropriate supported evidence mechanism; do not pretend a local clock provides it.
4.4 Integration safety
The following must remain true:
- Current fail-closed behavior remains fail-closed until authentic supported trust anchors and evidence are configured.
- No synthetic test artifact can qualify a live or production archive.
- Historical replay and Strategy 3 cannot proceed on unqualified sources.
- Contract-cache last-good behavior cannot silently elevate authenticity or freshness.
- Existing accepted cash scan, candle lineage, history pagination, paper ledger, dry-run notifications, API/UI and release-verification behavior are not regressed.
- telegram_dry_run=true, enable_background_scheduler=false, and no outbound/live broker requests remain enforced.
5. Mandatory test matrix
Add focused tests using isolated temporary/in-memory storage and synthetic test-only keys, covering:
1. Correct signature and exact artifact bytes under a test trust anchor.
2. Unknown publisher / key identifier.
3. Missing trust roots and verifier dependency unavailable.
4. One-byte tampering, altered manifest fields and wrong digest.
5. Invalid signature and unsupported algorithm/schema/artifact type.
6. Key not-yet-valid, just-valid boundary, expiry boundary and revoked key.
7. Effective-date lower/upper boundary, future scope, expired scope, malformed/naive timestamps and timezone normalization.
8. Missing rights evidence and explicit distinction between integrity, authenticity and licence qualification.
9. Same-date/scope conflicting artifacts and deterministic rejection/selection rules.
10. Archive re-hashing cannot promote unauthenticated content; foreign/stale assessments cannot be reused.
11. Wrong provider, symbol, token, segment, expiry or signed coverage cannot authorize replay.
12. Historical gate rejects unqualified data before strategy evaluation/result writing.
13. Last-good archive does not bypass signature, effective-date or current-eligibility checks.
14. Tests show no external network call, no secret disclosure, and no change to live/scheduler/delivery safety settings.
Run targeted verifier/archive tests first, then the relevant existing provenance, historical pagination, contract-universe, strategy/replay-gate, cash workflow/lineage and paper tests. Finally run the project’s canonical strict offline gate if the current source is ready. Retain every failed intermediate result and explain exactly how a later run supersedes it.
6. Evidence and acceptance
Required command after implementation:
python -B -W error::ResourceWarning verify_offline.py --stage phase4a_source_trust
Then validate the exact new evidence file written by that run using the documented command:
python -B verify_offline.py --validate-evidence docs/evidence/<exact-evidence-file-written-by-the-run>.json
Do not guess the filename: inspect the real CLI output/artifact path. Record working directory, exact commands, exit codes, executed/pass/fail/error/skip counts, relevant logs, source hash identity and evidence-validation result. Verify current source matches the evidence being reported. Preserve prior evidence and do not overwrite master_final_accepted.json or historical artifacts merely to make the new run appear authoritative.

Update docs/TRADEPULSE_EXECUTION_LEDGER.md with the actual progress delta and exact next task. Update the capability matrix/production report only if new accepted evidence meets the existing scoring criteria. Official scores stay at 64.25 / 37.00 unless the existing rubric's full threshold is demonstrably crossed. Mark real-artifact qualification blocked if authentic publisher trust roots, signed artifacts or licensing evidence are unavailable.
7. Continue beyond Phase 4A — do not stop after another report
After Phase 4A code and targeted regression tests pass, continue in the same work session to the next independent local implementation task where feasible: Strategy 3 historical option execution.

First inspect the current backtest_engine.py, strategies.py, historical_data.py, readiness_policy.py and contract identity schemas. Specify an execution model that uses exact dated option-contract identity, qualified observed option-premium bars/quotes when available, explicit entry/exit/fill and costs assumptions, bid/ask or liquidity limitations, expiry/lot-size handling, and position/portfolio risk constraints. Avoid look-ahead, future contract selection and accidental mixing of underlying spot prices with option premiums.

Use synthetic premiums only for deterministic unit and integration tests, clearly labelled simulated. Do not let synthetic/model-generated premiums be accepted as observed historical data or produce a “qualified live/actual history” result. If authentic option history is unavailable, implement the engine interface, accounting/execution semantics and negative gates so actual research fails closed; document the external data blocker while continuing all testable local work.

Then extend derivatives risk controls for margin/contract quantity only as grounded in current supported contract/provider fields; mark unsupported SPAN/exposure inputs unavailable instead of inventing them. Do not implement an automated daily network downloader in this task unless source trust, rate policy, provenance and authorization design make it safe. Offline import must remain network-free.

Do not add a new numbered phase just to describe these tasks. Keep the existing roadmap and report measurable capability deltas.
8. Final report requirements
Return a concise but precise closeout including:
- Files and behavior actually changed.
- Trust model, cryptographic algorithm/library and trust-root provisioning approach.
- Targeted/regression/full test commands, counts, exit codes and evidence paths.
- Before/after behavior demonstrated by tests.
- Which acceptance requirements passed and which remain external blockers.
- Whether the option-execution engine work was also implemented in this run.
- Safety flag values and confirmation that no network/live broker/order/Telegram action occurred.
- Official scores only if a formal acceptance threshold changed; otherwise say why unchanged.
- Exact next implementation action in the existing ledger.
Do not claim production readiness. Do not say work was completed unless source changes and test results support it. Do not end with a generic recommendation to perform another audit. Continue implementation from the actual state.