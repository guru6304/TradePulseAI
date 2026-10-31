# TradePulse AI — Owner's Workflow Board (initial snapshot)

**Snapshot source:** The owner's Astra status report, dated 29 October 2026. These are **reported** statuses for Track A `main`, not independent source-code verification. `dev` was not reviewed. The newly supplied Codex master requires the agent to replace these with source/test evidence and keep **one** authoritative tracker at `docs/project/TRADEPULSE_MASTER_STATUS.md`.

## Today's important facts

- **Tests reported:** 1,198 Python / 40 Node passed; 103 Python files compiled. This establishes only tested/offline behavior matching those source receipts.
- **Exact next unfinished task:** `B01.5b` — connect tested VWAP future-reclaim to real paper coordinator/portfolio, verify concurrency, rollback, duplicate and bypass protections.
- **Already reported complete:** recovery and checkpoints, safe GET/HEAD, historical study integrity mechanics, strategy evidence metadata, offline cash rank/history, offline options/Greeks/depth validators, ORB paper-entry fix, isolated VWAP contract, ledger API identity fix, selected performance improvements.
- **Not proven:** profitable strategies, all-strategy paper execution, advanced data-informed ranking, true broker→scanner live path, new premium UI, independent whole-product security, release installation, customer/public launch rights.

## Workflow status (reported starting point)

| Order | Work unit | Status from source report | Evidence needed to mark verified | What user should ask to see |
|---|---|---|---|---|
| W0 | Recover source, reconcile checkpoint, task board | Reported completed; recheck current HEAD | git status, receipts match current tree | Updated `TRADEPULSE_MASTER_STATUS.md` |
| W1 | B01.5b VWAP integration | **PENDING — FIRST ACTION** | failing-before / passing-after coordinated future-entry tests | source/test IDs, no premature fills |
| W1 | OB/BOS/FVG & Supertrend future paper | Pending | versioned future trigger, negative tests, EOD | strategy lifecycle matrix |
| W1 | Option Apex contract-qualified paper | Pending | exact CE/PE dated premium, identity, conservative costs | no spot-as-option substitution |
| W2 | D01 genuine runtime source-to-consumer | Partial | offline production-path replay + negative tests; separate authorized live | provenance and completeness |
| W2 | Advanced dynamic ranker | Partial | sector-relative factors, risk/cost, missingness, rank delta and no-trade tests | example rank swap with source factors |
| W3 | Premium shell and **Pulse** | Deferred | real browser desktop+mobile before/after, interaction evidence | actual screenshots not only mocks |
| W4 | Opportunities, Options, Strategies, Paper, Health | Deferred | functional routes, charts from valid data, tests on all pages | six-page gallery and test results |
| W5 | E01.4 latency, E02 security/reliability | Pending | benchmarks, threat model, fixes, backup/restore | security review, before/after metrics |
| W6 | Clean release candidate, install and ops | Pending | single lean package, checksum, independent offline launch test | archive manifest, install result |
| X01 | Authentic historical out-of-sample validation | Blocked external | authorized trusted source + frozen study results | real after-cost metrics, uncertainty |
| X02 | Authorized true live market scanner | Blocked external | real completed 5m observation consumed by production scanner | time-stamped live acceptance evidence |
| X03 | Public/commercial deployment | Blocked external | rights, legal and security/commercial approval | explicit launch gate checklist |
| LATER | Subscription billing/webhooks | **DEFERRED BY OWNER** | no implementation now | should be absent from V1 artifact |

## How to monitor work each time a session finishes

Ask Codex for **only**: (1) work unit / exact task ID; (2) actual code changed; (3) focused tests and results; (4) browser proof if UI; (5) high-severity defects; (6) current offline engineering gate count, with unknowns shown as unknown; (7) one next task; (8) current clean-release status. Do not accept an unverified '100% complete'. Do not let the agent restart from W0 every time usage limits reset.

**Resume instruction:** `CONTINUE FROM CHECKPOINT. Check TRADEPULSE_MASTER_STATUS.md and the existing checkpoint, verify the actual diff and last test evidence, then resume the exact first incomplete task. Do not redo verified work.`
