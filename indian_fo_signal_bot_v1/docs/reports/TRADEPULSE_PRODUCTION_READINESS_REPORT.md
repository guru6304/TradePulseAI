# TradePulse AI production readiness

Execution authority: [ledger](../TRADEPULSE_EXECUTION_LEDGER.md). Continued
2026-10-22. This report is a release decision with evidence boundaries, not an
authorization to operate accounts or place orders.

## Current release decision

TESTING READY: **PASS for current source**. Final full execution and current-source
evidence validation both returned 0: **722/722 Python cases passed**, 0 failures,
errors or skips, 267.497s; **10/10 standalone Node cases passed**, syntax exit 0,
51 Python files compiled, no unraisable errors, source before/after identical.
Evidence: `master_final_accepted.json` and bound logs, plus
`master_final_accepted_validation.json`. Exact commands are in the ledger and
testing report. Earlier Gate 2 (686 cases) and later intermediate runs remain
historical; their counts are not added to this final run.

PRODUCTION READY: **BLOCKED**. LIVE READ-ONLY ACCEPTANCE:
**BLOCKED_EXTERNAL_DEPENDENCY: BLOCKED_PENDING_OPERATOR_AUTHORIZATION**.
REAL TRADING: **NOT AUTHORIZED**. These decisions do not assert that credentials
are rejected; no private broker endpoint was contacted, token refreshed or order
sent. Upstox selection, Telegram dry-run and disabled scheduler are preserved.

## Gates and concrete limits

| Gate | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Current baseline / offline integrity | Fresh 675-case baseline; final 722/722, Node 10/10, source/log validation exit 0 | No current regression failure; broader qualified/operating requirements below. |
| Cash test readiness | Actual mocked adapter, validators, immutable input, scanner/ranking/risk, transactions, paper decisions, HTTP and actual renderer | Real declared universe/provider/calendar/warmup and separately authorized end-to-end handoff. |
| Adapter contract | Public V3 intraday/V2 full-quote contracts reviewed; existing bounded parsing/no automatic retry/error categorization retained | Actual account authorization and sanitized fresh observation/identity evidence, not inferred from local configuration. |
| Contract universe | Local native Upstox stock/index derivatives import, exact terms, immutable retained bytes, atomic inspection cache, stale/expiry/last-good tests | Authentic current source capture, agreed coverage/rights/trust/effective dates, derivative price and execution acceptance. Imported facts remain ineligible. |
| Historical research | Consistent paged storage beyond 10,000 rows; chronological snapshot and actual paged/direct cash backtest equivalence | Qualified licensed cash/options, independent source/effective-date verifier, actual historical option execution. Existing denial gates remain. |
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
| Actual historical Strategy 3 | Repository research owner + publisher; qualified contract premiums and declared spread/liquidity/rollover model, then real execution implementation | No underlying-as-option-premium substitution or fabricated fill; current rejection remains explicit. |
| Operating acceptance | Operator/project owner agrees actual sessions/scenarios, supported deployment/runtime environment and monitoring/restore/rollback criteria | Deterministic failure/restart/EOD/ledger/backup drills, local health and reproducible verification. |

Missing implementation is not reclassified as an external dependency. Actual option
execution, a source authenticator/effective-date verifier, derivative margin/partial
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

## Continuation without restarting the audit

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
