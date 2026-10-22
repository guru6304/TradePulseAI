# TradePulse AI production readiness

Execution authority: [ledger](../TRADEPULSE_EXECUTION_LEDGER.md). Continued
2026-10-22. This report is a release decision with evidence boundaries, not an
authorization to operate accounts or place orders.

## Current release decision

TESTING READY: **PASS for current source**. Final full execution and current-source
evidence validation both returned 0: **758/758 Python cases passed**, 0 failures,
errors or skips, 265.931s; **10/10 standalone Node cases passed**, syntax exit 0,
56 Python files compiled, no unraisable errors, source before/after identical.
Evidence: `master_phase4ab_verified.json` and bound logs, plus
`phase4ab_final_validation.json`. Exact commands are in the ledger and
testing report. Earlier Gate 2 (686 cases) and later intermediate runs remain
historical; their counts are not added to this final run.

PRODUCTION READY: **BLOCKED**. LIVE READ-ONLY ACCEPTANCE:
**BLOCKED_EXTERNAL_DEPENDENCY: BLOCKED_PENDING_OPERATOR_AUTHORIZATION**.
REAL TRADING: **NOT AUTHORIZED**. These decisions do not assert that credentials
are rejected; no private broker endpoint was contacted, token refreshed or order
sent. The explicit current selection is paper_sim, Telegram dry-run true and
scheduler disabled. Only the existing broker-selection line was changed to honor
this mission; no credential was printed or altered.

## Gates and concrete limits

| Gate | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Current baseline / offline integrity | Earlier baseline 675; supplied 736 artifact confirmed; current 758/758, Node 10/10, source/log validation exit 0 | No current regression failure; broader qualified/operating requirements below. |
| Cash test readiness | Actual mocked adapter, validators, immutable input, scanner/ranking/risk, transactions, paper decisions, HTTP and actual renderer | Real declared universe/provider/calendar/warmup and separately authorized end-to-end handoff. |
| Adapter contract | Public V3 intraday/V2 full-quote contracts reviewed; existing bounded parsing/no automatic retry/error categorization retained | Actual account authorization and sanitized fresh observation/identity evidence, not inferred from local configuration. |
| Contract universe | Local native Upstox stock/index derivatives import, exact terms, immutable retained bytes, atomic inspection cache, stale/expiry/last-good tests | Authentic current source capture, agreed coverage/rights/trust/effective dates, derivative price and execution acceptance. Imported facts remain ineligible. |
| Historical research | Consistent paged storage; cash equivalence; genuine Ed25519 source verifier and current trust-to-replay path; bounded exact-option bid/ask execution | Real authorized publisher roots/licensed signed inputs, actual empirical studies; broader derivative/partial/margin models and operating acceptance. |
| Paper operations and delivery | Final full regression passes: transactional cash ledger/EOD/recovery, durable local previews/retries/attempt audit, three fixture sessions across restart, actual API/UI reporting | Agreed real-session soak, derivative/margin and partial-execution scope, approved repair and real-delivery policy. |
| Release engineering | Final full regression and source/log validation pass; isolated actual store/cash/paper/outbox restore; deterministic scoped ZIP and extracted inventory bootstrap; same-origin guard/alerts; CI definition | Hosted runtime matrix, authenticated deployment/central alerting/browser visuals and real operating acceptance. |

Public contract references: the adapter's reviewed route shapes are documented in
[Upstox V3 intraday](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)
and [V2 full quotes](https://upstox.com/developer/api-documentation/get-full-market-quote/).
The [native JSON documentation](https://upstox.com/developer/api-documentation/instruments/)
defines explicit underlying/key, expiry, lot and strike fields; the new parser
checks those supplied facts and does not invent listing intervals. The
[standard API limits](https://upstox.com/developer/api-documentation/rate-limiting/)
are an operational budget to qualify later, not permission to issue requests now.
Documentation review is not live endpoint/account acceptance.

## External blockers and owners

| Blocker | Owner / evidence required | Work that proceeds independently |
| --- | --- | --- |
| Precise read authorization | Operator privately confirms intended account/environment, locally verified credentials/permissions and exactly one RELIANCE quote GET + one candle GET; no secrets in chat | Offline input/scanner/paper/API/UI, regression and release engineering. |
| Authoritative NFO/calendar scope | Publisher/project owner supplies authentic retained current/dated native master/calendar, rights and independently supportable trust/effective dates | Native parser/cache/expiry/conflict/refresh and calendar failure tests. |
| Qualified cash/options history | Licensed publisher + project owner supplies genuine observations, exact dated contracts, independent authenticity/effective-date mechanism and approved execution assumptions | Stored-history pagination, chronology, reproducibility, rejection and accounting mechanics. |
| Actual historical Strategy 3 | Bounded long-option model implemented; repository owner/publisher must supply qualified contract/premium/depth/closing-OI artifacts and approve execution assumptions | Existing model/qualification gates remain; no underlying-as-premium substitution or invented fill/settlement. |
| Operating acceptance | Operator/project owner agrees actual sessions/scenarios, supported deployment/runtime environment and monitoring/restore/rollback criteria | Deterministic failure/restart/EOD/ledger/backup drills, local health and reproducible verification. |

Missing implementation is not reclassified as an external dependency. Bounded
option execution and the publisher verifier now exist. General derivative margin/partial
execution, a real-delivery outbox worker and authenticated nonlocal deployment with
central alerting remain local functional gaps. Their acceptance also requires agreed
scope and independent artifacts. Existing rejection gates are preserved.

## Implemented and locally exercised release behavior

`release_management.py` builds a reproducible allowlisted ZIP containing source,
public assets, configuration template, tests and the runbook. It refuses existing
destinations and embeds a file-hash manifest. Inspection rejects undeclared paths,
links, duplicates, excessive size and modified content. A generated extracted
bundle loads its unique unified test inventory. SHA-256 establishes local content
integrity, not publisher authenticity or trusted deployment identity.
The tracked empty extensionless `public/rea` placeholder is retained in the
workspace/source inventory but excluded from the release's approved served assets;
the closeout manifest records that explicit non-runtime exclusion.

`verify_application_restore` copies an online backup into an isolated temporary
database and opens the actual application store/migrations. It validates retained
cash scan/results, paper reconciliation and outbox attempt/receipt audit. A test
changes persisted quantity without breaking SQLite integrity: the old SQLite drill
passes but the new application drill fails. Tests also prove the backup is unchanged
and the original account retains its position/reconciliation. No active database is
replaced, downgraded or financially repaired by a drill.

The local HTTP server checks loopback peer/Host/port and same-origin browser requests
before initializing the engine. Foreign Origin, DNS Host, cross-site and null-Origin
requests receive 403; wildcard CORS is removed. This intentionally strengthens the
old local browser contract: serve the UI from the server origin, not file URLs or
an unrelated origin. It is not an authenticated public-host deployment profile.
Static path traversal/secret-redaction/configuration regressions remain in the suite.

Health reports pending accepted input, retry/dead previews, provider/stale evidence
and paper reconciliation. Required storage/reconciliation failure yields 503.
Stored-report UI reads actual paper, EOD, retained research and outbox APIs. Failure
clears prior accounting, and delayed responses cannot restore it after health fails.
The pure friction simulator remains hypothetical. Browser DOM-double tests do not
establish visual acceptance or that external CDN assets are deployment-ready.

Cash scanner notification intents now commit atomically with results. Subsequent
local dry-run preview acknowledgements retain attempt/receipt audit, bounded retry,
terminal failure and restart/concurrent duplicate protection. No real delivery
worker, destination, live sender or background scheduler is attached. Real Telegram
delivery and exactly-once remote effects have not been tested or claimed.

The three-session fixture (configured weekdays Oct 16, 19, 20) closes one real paper
ledger lifecycle per session, reopens the store after entry, repeats callbacks,
reconciles increasing fees and preserves earlier EOD statement hashes. Separate
existing tests cover queue recovery, transaction interruptions, outages and missing
EOD bars. These are deterministic qualification scenarios, not live-session soak,
authoritative exchange-calendar acceptance or strategy-performance evidence.

The CI workflow is implemented for Python 3.10-3.14 on Windows/Ubuntu with Node 24,
read-only repository permissions and explicit offline-evidence uploads. Hosted CI
has not run here. Only installed Python 3.14.6 and Node 24.18.0 have local execution
evidence. The [runbook](../TRADEPULSE_OPERATIONS_RUNBOOK.md) supplies exact verification,
bundle inspection, isolated restore and future reviewed deployment/rollback steps.

## Per-milestone reassessment against the unchanged rubric

The following table is the prior master-checkpoint assessment, retained for
before/after comparison. The Phase 4A/4B addendum below supersedes its old claims
that the verifier and all historical option execution are missing. Scores remain
unchanged after reassessment of the same whole-row scope.

Previous state is the accepted Task 3/4 allocation. Current source and fresh
execution are assessed against the original row's full scope, not against new
narrow helper functions. Test selections/logs/exit counts are in the execution
ledger; the final full-run manifest binds actual case IDs to source and logs.
No overlapping focused counts are added to the full result.

| Milestone / weight | Previous I/R and acceptance | Current implementation and new evidence | Current whole-row status / remaining gate | Current I/R; score impact |
| --- | --- | --- | --- | --- |
| M01 / 8 | 75/50; partial | Existing configuration plus strict credential-free runner, evidence reservation/negative validation, complete extracted test bootstrap; `test_verify_offline`, `test_release_operations`, current configuration preflight | IN_PROGRESS: supported runtime/deployment profile needs executed matrix and operating acceptance | 75/50; no next threshold |
| M02 / 12 | 75/25; no current accepted access | Existing Upstox V3 candle/V2 quote/error policy reviewed against public docs; current offline adapter/read-only-readiness/HTTP-error tests retained | BLOCKED_EXTERNAL_DEPENDENCY: exact account/permission confirmation and authorized two-GET result absent | 75/25; documentation/fixtures do not establish access |
| M03 / 12 | 75/50; offline input mechanics accepted | Full persisted candidate reconciliation, actual mocked-adapter-to-paper/HTTP/renderer path; gaps/order/invalid/stale/provider/rollback/restart cases in `test_cash_workflow`, `test_cash_lineage` | IN_PROGRESS: real response coverage/publication delay/calendar/watchlist acceptance absent | 75/50; offline Gate 2 PASS is narrower than whole row |
| M04 / 10 | 75/25; provenance partial | `contract_universe.py` exact native terms/retained bytes/cache refresh/last-good/expiry/conflict; `test_contract_universe` plus existing source/identity gates | IN_PROGRESS: independent authenticity/effective-date verifier implementation and trusted artifacts absent | 75/25; observations remain explicitly ineligible |
| M05 / 10 | 25/0; limited F&O | General native stock/index FUT/CE/PE observation parser replaces the previous pinned-only inspection limitation; exact mapping/lot/expiry tests | IN_PROGRESS: no accepted authoritative universe or qualified derivative candles/premiums/execution | 25/0; import/cache subset does not implement full F&O coverage |
| M06 / 12 | 75/50; candidate scanner partial | Existing deterministic quality/risk validation/ranking retained; full source/result/decision/HTTP path now tested, including genuine empty versus failed scans; `test_completion_engineering`, `test_cash_workflow` | IN_PROGRESS: whole-universe operating evidence, general liquidity policy and broader fundamentals/news research absent | 75/50; no profitability or 5-10% upside acceptance |
| M07 / 10 | 75/50; cash paper risk partial | Actual exposure rejection stays nonactionable through API/UI; all persisted candidate fields reconciled; restored ledger tested; existing accounting/sizing/cost tests | IN_PROGRESS: derivative margin, partial fills and cross-account risk/operating policy incomplete | 75/50; cash evidence does not satisfy derivative scope |
| M08 / 10 | 50/25; history/research partial | `historical_pagination.py` removes 10,000-row truncation, resumed scoped snapshots, 10,050 exact bars and actual paged/direct cash replay equivalence; `test_historical_pagination` | IN_PROGRESS: qualified licensed history, source verifier, historical option execution and actual studies absent | 50/25; major functional/data gaps remain |
| M09 / 6 | 50/50; cash paper partial | Actual connected forward paper decisions/fills; three-session reopen/callback/fee/EOD digest test and application restore, existing failure/missing-EOD/concurrency evidence | IN_PROGRESS: real-session acceptance, derivative/partial scope and approved financial repairs/export incomplete | 50/50; local cash qualification does not accept full row |
| M10 / 4 | 50/50; reporting partial | Durable local preview intent/attempt/receipt, retry/dead/restart audit; outbox and stored paper/EOD/research UI, actual HTTP renderer bridge and stale-result clearing; `test_notification_outbox`, `test_cash_workflow`, Node renderer | IN_PROGRESS: real-delivery worker/operating acceptance, full reporting and browser/CDN deployment acceptance absent | 50/50; dry-run receipts are not remote delivery |
| M11 / 3 | 75/50; scheduler/resilience partial | Existing disabled scheduler/session/overlap policy retained; pending-recovery and retry/stale/provider/ledger alerts; offline failure/restart scenarios rerun | IN_PROGRESS: centralized alerting, sustained real-session/outage/ownership and supported deployment acceptance absent | 75/50; scheduler never enabled |
| M12 / 3 | 50/50; local release helpers accepted | Actual deterministic archive/extracted inventory, isolated application-level restore, same-origin guard, CI definition and operational runbook; `test_release_operations`, `test_release_management`, `test_local_api_security` | IN_PROGRESS: authenticated deployment, centrally operated monitoring, hosted runtime matrix and operating rollback acceptance absent | 50/50; remaining major deployment/monitoring gaps prevent 75 |

Recomputed `sum(weight * I / 100)` = **64.25**, `sum(weight * R / 100)` = **37.00**;
weights sum to 100. Whole product milestones accepted remain **0/12**. This does
not erase the new offline cash testing gate, contract cache, history pagination,
preview durability, reporting and release/recovery evidence. Each is recorded
against its own scoped criteria. No row reaches the original 75/100 threshold
merely from these narrower changes or from an increased test count.

## Prior continuation target (completed as offline engineering in Phase 4A/4B)

The next research task is an explicit source-verifier interface in
`source_qualification.py`/`instrument_archive.py`, preserving default denial.
Before positive acceptance, the project/publisher owner must specify the trust
anchor, independently verifiable publisher artifact, licensed scope and effective
dates. Tests must reject altered bytes, wrong instruments/dates, expired/revoked or
unknown authority and caller-forged flags; only independently supported artifacts
may qualify. A generic URL/hash or a locally generated signature is insufficient.
This is missing code plus missing trust evidence, not an authorization to fabricate
a successful positive fixture or to issue private requests.

Historical Strategy 3 still requires an actual exact-contract options execution
model, qualified observed premiums and declared spread/liquidity/rollover/margin
assumptions. It remains explicitly rejected with
`HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED`. These are outstanding production
requirements; the current implementation is not declared a completed product.

## Phase 4A acceptance and Phase 4B outcome - 2026-10-22

**Phase 4A PASS - OFFLINE ENGINEERING; Phase 4B PASS - BOUNDED OPTION MECHANICS.**
HEAD `205803131d7e1a17d6b42ce976efe7dff30e475a`, preserved working tree. Source-bound
final evidence is `docs/evidence/master_phase4ab_verified.json`; current validator
returned 0. Exact full command:
`.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase4ab_verified`.
It executed 758/758 passed, zero failures/errors/skips, 265.931s; Node 10/10,
56 files compiled, zero unraisable errors and no source change. Actual installed
runtime is Python 3.14.6 with cryptography 50.0.2/cffi 2.1.1/pycparser 3.11/
tzdata 2026.5. The source snapshot now binds requirements.txt. Hosted CI remains
unexecuted; the runtime matrix is not represented as tested here.

The supplied 736 PASS artifact genuinely matched entry source, but the base Python
had no cryptography and its positive test substituted a hash mock. The corrected
test case 01 genuinely signs/verifies using Ed25519; case 03 independently proves
missing-backend denial. A direct backend probe verifies a 64-byte signature and
InvalidSignature on altered bytes in the exact interpreter used by tests. No
alternate/mock/HMAC backend is substituted. The old artifact actually compiled
53 files, correcting the claimed 52. Old release failures were missing production
module registration and consequent extracted-bootstrap import failure. Both are
verified fixed; the new engine is also registered as production, with pinned
dependencies bundled and installed by CI. No test/module was dropped to pass.

`source_qualification.py`, `instrument_archive.py`, `instrument_identity.py`,
`storage.py`, `publisher_trust.py` and `backtest_engine.py` now enforce exact signed
bytes versus reparsed records, schema/type/provider/exchange/segment/instrument
scope, effective dates, publication before replay, current trust/revocation and
policy fingerprint. Actual store -> qualification -> dated identity -> readiness
-> cash replay is exercised, including revocation/changed bytes/future-publication
denials before strategy evaluation. Operator roots enter explicit local service
configuration, not an HTTP body or a saved assessment. Real roots/manifests and
licensing evidence remain absent; test keys do not qualify NSE/broker artifacts.

`option_execution.py` is a working execution branch through the existing Strategy 3
evaluator and cost model, `run_backtest`, readiness admission, actual HTTP and CLI.
It consumes explicit exact-contract premium bid/ask bars and opening depth, uses
known prefixes/prior closing OI, fills no earlier than next option open, supports
long calls/puts, lot/risk/capital checks, marks, opening gap stops/target exits,
observed expiry/EOD exit, ledger reconciliation and deterministic persisted results.
Raw observed quotes, modeled capped target references/fills and estimated costs
are separate. Slippage is applied once per leg, not to stop/target thresholds.
Fractional OI changes cannot be rounded into signals; exact observed differences
are required. Underlying bars never supply premium fills. Legacy override flags
remain blocked; the legacy default API eligibility status is preserved.

Precise V1 limits: NIFTY/BANKNIFTY OPTIDX, one open long position, full premium
reservation, opening quote liquidity, all-or-none fills. Intrabar stops/collisions
without executable trigger quotes remain unresolved, with stop priority and no
target award. Missing prices/depth/EOD retain reservations, never forward-fill or
settle at invented prices. No short margin, partial fills, overnight exercise/
settlement, general stock-options engine or real operational calendar acceptance
is claimed. Inputs must be retained separately: stored results include source
digests/IDs, assumptions and ledger, not a durable complete option-input archive.
These are functional limits, not renamed external blockers.

The actual local CLI passed with a temporary synthetic request/in-memory database:
one trade, observed bid 30, modeled fill 27.0, ledger OK, empirical claims false
(`phase4b_cli_verified.json`). Eighteen option cases and four new trust-path cases
raise execution count 736 -> 758; existing fourteen signature cases now use real
crypto. Failed intermediates, compatibility correction, observation-label and OI
regressions are retained in the ledger. No current test failure or stale final
source/log binding remains. A prior passed full run is explicitly historical after
the final OI fix, rather than relabeled current.

Final local release: `docs/evidence/phase4ab_release_final.zip`, 62 manifested
source/test/template/runbook/dependency files. Build and inspection exit 0.
SHA-256 `bc3f3cfc370c5e702dfcb565313f35006419d938469e66593b97910d92db7eff`.
Extracted bootstrap imports both production modules and requires real crypto.
The final closeout `docs/evidence/phase4ab_closeout.json` binds reports, source,
runtime, worktree, release and historical stage outcomes. Earlier master artifacts
are retained as historical; no previous failed evidence is overwritten.

Reassessment under the unchanged whole-row rubric: M04 gains the implemented,
genuinely tested trust gate, and M08 gains bounded option replay. Actual licensed
data, empirical research, broader derivative/margin/partial scope and operating
acceptance are still absent. No whole-row next threshold is established:
implementation **64.25 -> 64.25**, readiness **37.00 -> 37.00**, **0/12** accepted.
Testing readiness passes; production and real historical option study remain
BLOCKED/NOT ACCEPTED. This is engineering evidence, not profitability evidence.

Next task: obtain the operator-approved real trust-root/publication/rights profile
and an authentic signed dated master + premium/bid/ask/depth/prior-closing-OI dataset,
retain its exact inputs and run the existing qualification/engine gates. Require
scope/date/digest/key verification, no unresolved fills, reconciled ledger and a
reviewed calendar/cost/study protocol before accepting real research. No keys or
secrets should be submitted in chat. No live requests, orders, token refresh,
Telegram delivery or scheduler activation were made; paper_sim/dry-run true/
scheduler false is confirmed. Package downloads from official PyPI were software
installation, not broker or market-data acquisition.
