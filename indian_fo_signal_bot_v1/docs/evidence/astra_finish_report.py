"""Update the explicitly mutable master report from the final partial-slice proof."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt = Path(args.receipt)
    assert receipt.name == args.receipt and receipt.suffix == ".json"
    proof = validate_evidence(APP / "docs/evidence" / receipt)
    p = proof["python"]
    node = next(check for check in proof["checks"] if check.get("command", [None])[0] == "node" and "executed" in check)
    compiled = next(check["compiled_files"] for check in proof["checks"] if "compiled_files" in check)
    stamp = datetime.now(timezone.utc).isoformat()
    notes = (APP / "docs/project/ASTRA_STRATEGY_RESEARCH_NOTES.md").read_text(encoding="utf-8")
    strategy = notes.split("## Current strategy contracts\n", 1)[1].split("## Historical execution", 1)[0]
    research = notes.split("## Prioritized experimental slate and study protocol\n", 1)[1].split("## Remaining review", 1)[0]
    report = APP / "docs/project/TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md"
    text = report.read_text(encoding="utf-8")
    sections = {
1: """## 1. Executive verdict

**PARTIAL VERIFIED OFFLINE ENGINEERING; MASTER MISSION INCOMPLETE.** This session
closed GET/HEAD scan mutation, undeclared historical study-session coverage, and
misleading dashboard sizing/missing-price/stale-P&L behavior, including absent
quality and invalidation. It added a read-only
paper journal, strategy evidence passports in scanner/history/UI, and a tested
standalone deterministic cash rank-change prototype. Original evaluator formulas,
paper accounting and saved operating settings remain unchanged.

The most important remaining defect is **B01 premature automatic paper entry**.
Its isolated reproduction filled98 when the long threshold100 was never reached
(candle high99). The assigned worker stopped at a usage limit after creating
unintegrated drafts under `docs/drafts/`; forward_paper.py and paper_portfolio.py
were not changed. No trigger repair or new paper-lifecycle acceptance is claimed.
The prototype ranker is not connected to scanner persistence/API/UI yet.

The owner has already chosen personal validation before customers, NSE cash and
staged exact-contract derivatives, selective explainable ranking, strategy-specific
paper triggers, existing Python/SQLite/JS, and no real orders. BSE/swing/positional
and public launch are not accepted. A universal next-close or three-bar rule is
superseded. Workers cannot continue after usage limits/session end; this report and
checkpoint identify the first incomplete action.
""",
2: """## 2. Audit manifest and Git state

Branch main; starting HEAD `fcdbadb`, full SHA and88 source-file hashes in
`../evidence/astra_baseline_20261024_01.json`. The initial source matched the retained
Phase6 receipt; new source requires the new proof below.522 prior documents were
inventoried, including releases under docs/evidence (the baseline's top-level ZIP
list is empty because archives are in that subdirectory). Original BRD was read
as ZIP/XML and preserved. Both saved environment files are compared locally by
whole-file integrity, with no credential values copied here. Operational DB/WAL/SHM
were never opened; concurrent external application activity is not attested.

Runtime: Python3.14.6, Node24.18.0, Windows PowerShell. No dependency upgrades or
Git mutations. An unrelated untracked TRADEPULSE_AI_PLUS_PROJECT_INTELLIGENCE_REPORT.md
was observed and left intact. Windows sandbox-created temporary directories may
remain access-denied; no recursive cleanup was attempted.

Changed existing code: server.py, historical_study.py, scanner_engine.py,
candle_lineage.py, public/index.html, test_cash_dashboard.js, test_bot.py and
release_management.py. New implemented modules: strategy_evidence.py and
opportunity_ranking.py; new tests: test_astra_http_safety.py, test_astra_research.py,
test_astra_ranking.py. The unintegrated docs/drafts/astra_paper_triggers_20261025_01.py is a draft, not tested
behavior. Exact final hashes and historical archive checks are in the new
astra_preservation receipt. Source inspection was targeted, not an exhaustive audit
of every function in the repository.
""",
3: """## 3. BRD acceptance ledger

| Phase | Previous report | Current evidence and boundary |
|---|---|---|
|1 foundation|Offline accepted|EXISTING_RECEIPT_VALIDATED at baseline; current regressions and read-safety fix verified; comprehensive customer security NOT_ESTABLISHED|
|2 historical/research|Mechanics accepted, empirical blocked|VERIFIED_CURRENT_SOURCE_AND_TEST for exact fold coverage; genuine empirical/OOS BLOCKED_EXTERNAL|
|3 live market data|Adapters tested, live not accepted|Existing fixture regression coverage; real fresh completed scanner-consumed bars NOT_ESTABLISHED; no provider call|
|4 scanner/ranking|Offline accepted|Current regression proof; evidence-passport integration verified; new ranker prototype tested, runtime rank history NOT_ESTABLISHED|
|5 context/dashboard/alerts|Offline accepted|Current Node/HTTP regressions; paper journal and truthfulness fixes verified; browser visual/mobile/new delivery acceptance NOT_ATTEMPTED|
|6 paper/performance/release|Offline accounting accepted|Existing accounting regressions pass; B01 DEFECT_REPRODUCED and NOT_REPAIRED; no new auto-trigger acceptance or customer release|

Passing old paper tests means their retained contracts still work; those tests did
not require the missing future strategy predicate. No green suite is used to
erase this newly demonstrated requirement gap. Prior report statements of complete
Phase6 are valid only within their original tested boundary.
""",
4: """## 4. Architecture and call flows

```mermaid
flowchart LR
  A[Authorized feed or explicit replay] --> B[Identity / session / completed candle gates]
  B --> C[Existing evaluator and sizing]
  C --> D[Deterministic candidate rank]
  D --> E[Transactional signals / evaluations / input lineage]
  E --> F[Explicit ForwardPaperCoordinator]
  F --> G[Existing PaperPortfolio / ledger]
  E --> H[Read API / dashboard]
  G --> H
  X[New rank-change prototype] -. integration pending .-> E
  T[New ORB trigger draft] -. integration pending .-> F
```

Concrete symbols: `scanner_engine.IntradayBotEngine.run_single_scan` creates the
explicit coordinator, freezes input, invokes `evaluate_strategy_detailed`, applies
sizing/geometry, calls `rank_signal_candidates`, saves evaluations and commits
cash inputs before `ForwardPaperCoordinator.consume_scan`. `_replay_cash_result`
supports existing retained-work recovery. `PaperPortfolio.enter/process_bar`
own financial effects and reconciliation; no second ledger was added.

`server.DashboardRequestHandler._handle_scan` passes an explicitly injected paper
portfolio. `_dispatch_get_or_head` now returns405 for scan aliases before runtime
initialization. POST remains explicit. `candle_lineage.annotate_signals` loads
retained evaluations/context and exposes descriptive maturity; it cannot promote
actionability. `historical_study.run_frozen_study` verifies exact consumed session
declarations before archiving/executing folds. `option_execution.py` remains the
separate historical premium/depth/lot-aware runner. Exact symbol line ranges are
recorded in astra_code_locations evidence; source hashes identify the revision.

Configuration and providers retain existing boundaries; no token handling changes.
Scheduler remains disabled in saved settings. SQLite operational schema and data
were not migrated by this slice. Existing tests cover transactions, recovery,
loopback policy, source integrity and release exclusion; new customer auth,
multi-tenant isolation and an SBOM/security attestation remain unimplemented.
""",
5: "## 5. Complete strategy contract matrix\n\n" + strategy,
6: """## 6. Dynamic ranking specification and demo

Implemented prototype `opportunity_ranking.build_snapshot/current_view` reuses rule
quality then actual gross T1 RR, stable symbol/strategy/identity ties. It retains
rank_version, as_of, data watermark, input digest, component versions, previous/new
rank, component changes and removal reasons. One selected setup per symbol avoids
double counting. Exact option-contract ranking is deliberately separate; option
premiums cannot enter the cash comparison. Missing relative strength, sector,
regime, depth, spread, net executable reward and empirical edge remain explicit.
It does not invent those features or turn gross RR into net RR/probability.

Eight actual prototype tests pass. The synthetic demo: at10:00, TCS quality90 and
INFY80; at10:10, TCS85 and INFY95. INFY moves2->1, TCS1->2, with changed rule-quality
values and source watermarks retained. Equal-score permutations and duplicate input
keep stable priority/version. Stale/forming/rejected inputs leave current ranks;
same-watermark revised data or reversed chronology reject. Expired reads return an
empty current list plus a separately labelled archive without mutating state.
Independent review found expiry five minutes later than rebuild eligibility;
an exact-boundary regression failed before correction. Both now expire at source
bar start +5 minutes +60 seconds. See `astra_rank_demo_20261025_01.json` for
actual synthetic snapshot output, and the retained before/after focused receipts.

This is **mechanics only**. It is not scanner-integrated, a persistent rank-history
API, a strategy performance improvement or a full standalone source validator.
The production scanner still owns mandatory data/strategy/risk gates. Integrating
the prototype must reread retained input/evaluation references, atomically persist
snapshots and test same-transaction failure; do not accept arbitrary HTTP score
payloads. Current UI shows the original retained scan rank with an explicit
historical label. No current dynamic leaderboard is claimed.

Future architecture: hard gates first (authorized fresh exact data, required
warm-up, strategy condition, viable cost/risk/liquidity where available). Research
soft factors through ablation; do not add unrelated indicator gates to all
strategies. Developing watchlist never creates a paper position. Correlation/sector
concentration and empirical factor calibration are still design work.
""",
7: """## 7. Options, volume, depth and Greeks assessment

Upstox's documented chain fields include exact instrument keys, expiry, strike,
bid/ask prices and quantities, volume, OI/previous OI and Greeks. The separate
Greeks endpoint exposes sensitivity/IV fields. These schemas are available in
official documentation, not evidence that this account is entitled or a response
has been observed. IV examples differ in numerical convention across endpoints;
normalize only with endpoint-specific documented units, not an unqualified merge.
[Chain](https://upstox.com/developer/api-documentation/get-pc-option-chain/),
[Greeks](https://upstox.com/developer/api-documentation/option-greek/), accessed
2026-10-24. Provider probability-of-profit fields are not calibrated TradePulse
win probabilities and are not imported as such.

The V3 feed documents regular5-level quotes and30-level mode associated with Plus,
with different connection/subscription caps. Implementation must freeze mode,
entitlement, subscription scope and source/receive clocks. More depth does not
establish executed aggressor flow. LTQ, total buy/sell quantities and snapshots
cannot be relabelled trade-direction volume.
[V3 feed](https://upstox.com/developer/api-documentation/v3/get-market-data-feed/),
accessed2026-10-24.

Current historical option runner uses next observed ask, adverse tick rounding,
lot/depth checks and observed bid exits. Unresolved intrabar stop execution remains
unresolved, not fabricated. Both CE and PE are long premium. Stock F&O expansion,
futures margin/roll semantics and a new normalized point-in-time Greeks contract
remain NOT_IMPLEMENTED in this slice. No assumption of dated lot/tick authority
from hard-coded examples, no spot-to-premium substitution and no naked-short option
paper acceptance.
""",
8: """## 8. Broker matrix and token plan

| Provider | Retained application position | Official documentation / entitlement boundary |
|---|---|---|
|Angel One|Existing adapter/feed preserved; genuine stale packet retained, complete live acceptance absent|Admin notice states daily midnight logout and distinguishes order/GTT static-IP requirements from other APIs. Account entitlement, future token validity and broader pricing not checked by a provider request.|
|Upstox|Optional read-only complement; no source switch|Analytics Token documented free, read-only and valid1 year; supported quote/history/chain/WebSocket categories. Regular full depth and Plus30-depth have distinct entitlements.|
|Dhan|Existing code preserved|Premium plan rejected by owner; no subscription, activation or new price claim. Current commercial entitlement UNKNOWN.|

[Upstox Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/)
is generated through the account interface, supports specified read-only access
and cannot place/modify orders. No daily OAuth workflow should be invented for
that use case. Standard OAuth is a different token with the documented3:30 AM
expiry boundary. [Standard token](https://upstox.com/developer/api-documentation/get-token/).
[Angel admin notice](https://smartapi.angelone.in/smartapi/forum/topic/5254/important-updates-to-smartapi-in-compliance-with-sebi-guidelines/34).
Accessed2026-10-24. The Angel page includes deleted-topic wording and user replies;
only the visible administrator notice supports the stated lifecycle fact.

Future nonsecret schema proposal: token kind, expiry timestamp, provider and
approved capability set, with the actual token held only in local secret storage.
Do not echo token length/prefix/hash, silently refresh, retry login or change
saved credentials. A future activation requires exact provider/scope/time/rate/
stage/entitlements approval. No such activation occurred; previous one-shot text
is not used as permission under this revised mission. Free API access is separate
from historical authenticity, display, derived-data and redistribution rights.
""",
9: """## 9. Bugs and security findings

| ID/severity | Evidence, correction and disposition |
|---|---|
|B01 P0 paper premature entry|Retained synthetic entry100/high99/fill98 reproduction. No repaired coordinator/portfolio. Draft only; OPEN.|
|B02 high read mutation|Actual HTTP before:2 tests,6 failed method/alias subcases. server.py rejects GET/HEAD scan before initialization. After2/2 pass, POST still consumes explicit paper sentinel.|
|C01 high study integrity|Two failed assertions proved omitted intermediate test/warm-up sessions accepted. Exact source-prefix/range guard before archive/evaluation;23 focused new+old tests pass.|
|E01 medium misleading UI|Before27 Node tests:24 pass/3 fail. Missing quantity/prices fabricated, stale equity shown. Removed frontend sizing fallback, retained null chart levels and stale mark withholding; journal tests added.|
|I01 integration regression, corrected|New maturity annotation assumed strategy_id on legacy minimal rows;4 errors retained. UNKNOWN descriptive fallback preserves legacy integrity validation. Re-run54/54 passes.|
|R01 prototype coverage boundary|New rank history is standalone. Net friction, source authenticity and sector correlation are unavailable, not imputed. No runtime integration claim.|
|R02 medium stale current priority, corrected|Independent review found read expiry5m later than rebuild qualification; exact boundary regression failed then passed after correction.|
|E03 medium absent values, corrected|UI self-review found absent quality coerced to0 and invalidation borrowed from stop;32-test before run failed one regression, after32/32 pass. Observed zero remains0.|

Negative controls: offline runner blocks non-loopback sockets; fixtures install
transport sentinels and separate stores. UI renders journal strings via safe text,
withholds corrupt financial state and bounds previews. Actual HTTP GET/HEAD and
renderer refresh tests rule out those paths invoking scans/paper mutations.
This is not proof that every possible future endpoint is safe. No real broker
order endpoint was called and no new broker dispatch was added. The current
HTTP/research/metadata/rank slice received independent read-only source review;
R02 was fixed afterwards and tested by root. UI review was its author's self-review.
Full paper/product/browser approval remains outstanding after worker limits.
""",
10: """## 10. Paper engine detailed verdict

The existing coordinator queues persisted candidates and fills the immediately
next completed close subject to bracket/risk checks. It lacks an explicit future
entry predicate, so a price inside the bracket is insufficient acceptance. The
reproduction shows exactly that. The source inspection and green old ledger tests
do not prove the requested automatic strategy-trigger product.

`docs/drafts/astra_paper_triggers_20261025_01.py` is the latest preserved
unintegrated prospective ORB draft. The earlier draft is retained alongside it;
the only resumed edit corrected a rule-trace field from observed to measurements.
Neither draft is a production module or tested policy. It proposes
freezing the confirmed signal candle high/low, a later completed directional close
cross and original range invalidation, with same-session/account square-off. This
is a new experimental rule, not the original ORB detector or a universal policy.
Its actual candle/trace/schema fields and tick policy remain unverified; do not
import or activate it merely because it compiles. Coordinator/portfolio transaction
integration, direct-entry bypass prevention, old automatic-account migration,
concurrency/restart/rollback and retained outcomes remain B01's next work.

Existing accounting still has capital/exposure/daily-limit checks, conservative
cash stop-first collisions/gaps, T1 full exit and EOD/missing-mark reconciliation.
T2/partial/trailing future lifecycle and exact excursions are not added here. The
new UI reads retained decisions/positions/events and labels missing trigger fields
unavailable. Bounded previews are explicitly partial; pagination UI remains future
work even though ledger APIs exist.

New-policy valid setups, pending setups, triggered trades, stop/target/other exits,
unresolved positions and reconciled-result counts: **NOT_ESTABLISHED**, because no
new-policy ledger cohort was executed. The legacy defect reproduction retains one
incorrect synthetic fill, not an accepted trade count. No live or empirical paper
performance is inferred from test totals or operational DB contents.
""",
11: """## 11. Historical and empirical readiness

Retained public probe evidence contains an authentic provider-response candidate:
73/75 bars for RELIANCE2026-10-22, missing15:15 and15:20. It is not an accepted study.
Publisher trust/signature, current research rights, dated identity and sufficient
complete sessions remain missing. Earlier 'no historical observations' wording is
too broad; 'zero qualified empirical datasets established' is the proper boundary.
Private originals were not re-opened or newly authenticated in this slice.

Separate historical option execution is implemented. Cash-only StudyProtocol's
Strategy3 exclusion is a scope boundary, not absence of option_execution.py.
Historical option bid/ask/depth and dated contract authority remain external gates.
Current source has publisher signature verification, independent rights policy
and immutable original-byte archives. Test roots/rights documents establish
mechanics, not real publisher/legal authorization.

No new empirical study, win-rate claim or promoted strategy. Original nominal
60/20/20, win>=50%,100-trade or lot-size prose examples are not binding code-derived
acceptance. The research design below is proposed and lacks frozen real datasets.

""" + research,
12: """## 12. UX and product differentiation

Implemented: safe persisted quantity, missing levels, stale-account withholding,
read-only bounded paper history, maturity and historical scan-rank scope.NODECOUNT Node
tests pass; actual browser/mobile/accessibility acceptance was not rerun. Existing
vanilla JS kept. Incomplete trigger and dynamic ranker are not dressed as live UI.

| Priority / feature | Customer problem and competing workaround | Cost/dependency/risk | Acceptance and value hypothesis |
|---|---|---|---|
|1 Rank movers + X-Ray|Manual sorting/screens lose why priority changed|Medium; qualified multi-symbol input and persistent snapshots; stale/missing factor risk|Trace each change to source/component and expire stale ranks; measure time to explain top3, not number of signals|
|1 Paper shadow journal|Spreadsheet/manual entry loses trigger/fill assumptions|High; B01 first, rights and costs; favorable-fill bias|Replay exact lifecycle and reconcile every event; measure unresolved-rate and explanation accuracy|
|2 Evidence passport|Headline win rate obscures data/sample/cost limits|Low local UI, high empirical dependency|Every claim links period/sample/cost/source or says unavailable; measure comprehension and trust|
|2 Saved comparison/watchlists|Repeated manual filters and separate notes|Medium; later tenant/auth scope|Reopen same retained evidence without accidental trades; measure weekly return usage|
|3 Sector/regime map|Absolute movers confuse market beta and leadership|High data/rights/constituent dependency|Past-only aligned factors and ablations; measure incremental selection value before promotion|
|3 Cash-to-contract|Underlying direction hides bad option execution|High; exact quotes/depth/Greeks/lot/expiry|Separate thesis and contract fitness, reject missing premium; measure unresolved/fill-friction rates|
|Defer missed-opportunity lab|Hindsight makes abstention look wrong|High selection-bias/counterfactual risk|No invented missed fills; preregister universe/exclusions before measuring|

Demand is **unvalidated**: no customer interviews, paid experiments or retention
data were gathered. [Chartink's guide](https://chartink.com/articles/scanner/scanner-user-guide/)
documents configurable technical/fundamental filters and crossovers.
[TradingView's screener guide](https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/)
documents multi-filter tables, saved screens/watchlists and exports. Accessed
2026-10-24. These are real alternative workflows, not proof that their users will
pay TradePulse. The proposed differentiator is an inspectable rank-change and
strategy-trigger history, to be tested against those workflows. Current brokerage
research/options competitor breadth and exact pricing still need verified review.
""",
13: """## 13. Build-to-sell plan

Personal alpha: finish B01, integrate rank snapshots, preserve localhost isolation,
deterministic tests and truthful empty states. Invite-only beta comes after genuine
scanner-consumed market data, rights/legal clearance, financial reconciliation,
stability soak and user-support/runbook acceptance. Public release additionally
needs authenticated tenant isolation, rate limiting, billing/tax/privacy design,
monitoring, incident response, independent security review and explicit approval.

Regulatory assessment is a launch question, not a ban on offline engineering.
SEBI's July23,2025 RA FAQ explains that specific-security technical research is
not exempt merely because of its methodology. The live regulations index lists
RA amendments through October10,2026; the RA master circular is dated
February6,2026. Ask qualified Indian counsel to classify ranked security targets/
stops, paid distribution and any personalized features under RA/IA rules, and map
registration, disclosures, records, complaints, performance advertising and client
obligations. The master-circular linked document failed to open in this tool; its
publication was verified, not a full clause-by-clause current legal audit.
[RA FAQ](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2025/1753268710217.pdf),
[updated regulations](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=3),
[2026 master circular](https://www.sebi.gov.in/legal/master-circulars/feb-2026/master-circular-for-research-analysts_99571.html).

NSE's current linked usage policy requires intended-use agreements, limits
redistribution, and includes restrictions concerning virtual trading/simulation.
Obtain explicit provider/exchange classification and permission for the proposed
paper product; a broker credential or 'educational' label cannot settle this.
[NSE usage policy, clauses6.3/7.3/7.4](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing%26Usage_Policy.pdf).
Its March2026 non-display policy includes derived internal analysis and requires
separate agreement/fees for external derived-data distribution.
[NSE non-display policy](https://nsearchives.nseindia.com//web/mediaattachment/2026-03/Non_Display_Policy_20260323164430.pdf).
Accessed2026-10-24. These are specific unresolved commercial-use gates; no legal
opinion or license is granted here.

Proposed discovery: interview separate cash/derivatives/self-directed cohorts;
test whether users can explain why an opportunity ranks first and why no trade
occurred. Prototype usability before price tests. Free delayed/example education
versus paid licensed research/journal tiers are hypotheses subject to rights and
legal scope. Compare willingness to pay with actual retention, support cost and
licensed data cost. No numeric subscription promise, campaign, purchase or client
enrolment. Use transparent demonstrations and non-cherry-picked case studies only
after applicable approvals; never guaranteed-profit claims.

Proposed metrics: weekly engaged researchers, qualified opportunity review rate,
explanation completion, rank freshness/removal accuracy, paper reconciliation,
unresolved marks and support burden. Candidate SLOs need measurement: no duplicate
financial events, no stale actionable rank, bounded data-to-rank latency and read
API latency within the existing test budget. Business costs remain unquoted for
licensed history/real-time/derived use, hosting, audits, counsel and support.

Keep SQLite and loopback for alpha. Before multi-user hosting: inventory retention,
authentication/authorization, per-user entitlements, encryption/key rotation,
durable event queue and measured database contention. Migrate storage only after
workload evidence; no React or speculative platform rewrite. Deployment checklist:
source-bound tests -> reviewed manifest -> isolated restore drill -> explicit
configuration/entitlement verification -> canary -> measured health. Rollback:
stop new consumers, preserve append-only financial events, return to known code,
verify schema compatibility and reconcile before resuming. No destructive live
restore without separately approved procedure. Privacy applicability/effective
dates and full SBOM review remain unverified work; do not claim commercial readiness.
""",
14: """## 14. Ordered implementation backlog

| Task / phase / owner | State | Dependency, files and measurable acceptance |
|---|---|---|
|B01 /6 /paper owner|IN_PROGRESS, P0 OPEN|Review docs/drafts/astra_paper_triggers_20261025_01.py against actual committed schema; wire explicit ORB contract in forward_paper.py and paper_portfolio.py; direct-entry, invalidation, expiry, gaps, concurrency, rollback, restart and UI tests. Migrate unsafe automatic legacy behavior without changing recorded historical accounting.|
|C03 /4 /coordinator|Prototype VERIFIED; integration NOT_STARTED|Atomically persist rank snapshots with scan inputs, expose read API/UI and test source tamper/rollback, duplicate/empty/out-of-order runs. Preserve original ranker.|
|C02 /2,4,5 /coordinator|Implemented and tested|Evidence metadata wired scanner/history/UI; no promotion authority. Additional calibration requires X01.|
|E01 /5,6 /UI|Narrow slice VERIFIED|Journal bounded preview only; full paging, browser/mobile/keyboard review still pending.|
|E02 /1,6 /independent reviewer|IN_PROGRESS|Read-only HTTP/research/metadata/rank review completed; freshness finding reproduced and fixed. Paper draft and final browser/product acceptance remain unreviewed. UI self-review is not independent.|
|D01 /2,3 /data owner|Documentation PARTIAL|Exact neutral benchmark/chain/Greeks/OI/depth contracts and offline provider fixtures; no new calls; preserve provider fail-closed behavior.|
|F02 /6 /coordinator|Current-slice proof; final release NOT_STARTED|Finish B01/C03, canonical final receipt, independent review and fresh archive. Prior archives preserved.|
|X01 /2 /operator + data owner|BLOCKED_EXTERNAL|Complete authentic history, approved trust/rights, dated corporate-action/instrument universe, frozen OOS protocol; no fixtures as edge.|
|X02 /3 /operator|BLOCKED_EXTERNAL|New exact scoped authorization, official session, unused/approved stage and real accepted stream->scanner evidence.|
|X03 /6 /owner + counsel/vendor|BLOCKED_EXTERNAL|Legal/data/tenant/security/support readiness and separate public-release approval.|

Offline B01/C03/D01/E02 can proceed without market hours or additional credentials.
There is no Phase7. The task ledger separately tracks completed B02/C01 and remaining
work; a prototype or a prior report is never whole-phase completion.
""",
15: """## 15. Verification ledger

**RUN after completed source edits:** canonical strict receipt
`docs/evidence/PROOF_RECEIPT` reports PYCOUNT Python
tests and NODECOUNT Node tests, no failures/errors/skips/unraisables, plus syntax
checks and COMPILEDCOUNT root Python files compiled. Exact commands, IDs, counts, times, source-before/after and log
hashes are retained in that receipt. This is partial-slice software proof, not B01
or real-market acceptance.

Command: `.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage PROOF_STAGE`.
Windows sandbox blocked temporary SQLite access in earlier focused runs; those
failures remain recorded, then the exact tests ran outside the sandbox with
external network still blocked by the runner.

| Stage | RUN result |
|---|---|
|Phase6 receipt validation at baseline|Exit0;1040 retained Python executions validated, not re-executed then|
|HTTP before / after|2 tests:1 pass and6 failing subcases before;2/2 after|
|Research partition before / after|2 failures before;23/23 new+existing after authorized sandbox rerun|
|UI before / worker after|24/27 pass before;30/30 after; intermediate passport test raised count to31; final32 below|
|Rank prototype initial / corrected|6/7 then7/7; deterministic canonical candidate-order digest corrected|
|Integrated focused first / second / third|Sandbox file errors;50/54 with4 real legacy missing-field errors;54/54 after compatible UNKNOWN annotation|
|First canonical,20261024_01|FAIL1056/1059 Python,2 failures and1 error: old GET assumptions and draft production placement; preserved, not accepted|
|Canonical repairs,20261025_03|26/26 pass; POST security/freshness, packaging and8 rank tests; failed sandbox and intermediate request-body fixture attempts preserved|
|Rank expiry boundary before|1/1 failed as expected before fix; included in corrected8 rank tests|
|UI review remaining before/after|31/32 then32/32; absent quality/invalidation remain unavailable, actual zero quality retained|

Retained old archives/receipts are verified separately by
`docs/evidence/astra_preservation_check.py`, which checks manifest bytes against
their historical source snapshots, not today's changed source. It also compares
522 prior documents, both env files and original BRD. Old Phase6 helper is not run
because it overwrites old receipts and infers DB preservation from size alone.
The first new preservation check exposed a verifier/archive scope difference:
both old proofs hash empty `public/rea`, while both release manifests omit it.
Its SHA256 is the empty-file digest and current size is0. The corrected check
requires exactly that omission, verifies every packaged source hash and every
archive member, and records the exception explicitly. Old archives contain111
and122 public files; they are historical releases, not this changed source.
`astra_preservation_20261025_01.json` passes these checks; no generic missing-file
exception was added. This artifact does not serve as application code or an asset.
No claim of new browser acceptance, full independent final review, empirical
execution, real provider/Telegram delivery or new release bundle.

Workers audited disjoint files. Root integrated/reviewed outputs and ran actual
checks. The paper-draft author then independently reviewed HTTP/research/metadata/
rank files they had not authored; their rank finding led to a retained failing
regression and correction. UI review was explicitly its author's self-review.
Both workers later hit usage limits; no final paper approval is implied. Current
machine receipts take precedence over
prose counts, future mutable checkpoints and historical HEAD labels.
""".replace("PYCOUNT", str(p["executed"])).replace("NODECOUNT", str(node["executed"]))
    .replace("COMPILEDCOUNT", str(compiled))
    .replace("PROOF_RECEIPT", receipt.name).replace("PROOF_STAGE", proof["stage"]),
16: """## 16. Outstanding owner decisions

Product goals are already settled. Future approval is required only for precise
provider runs/activation, paid data and licenses, account/customer security setup,
qualified legal/commercial decisions, public launch and destructive migration.
No approval is requested to resume ordinary offline B01/C03 engineering. No new
token, plan, phone/contact detail or screenshot is needed for the current work.
""",
17: """## 17. Next-session checkpoint

Exact incomplete task: **B01.2 — review the preserved docs/drafts/astra_paper_triggers_20261025_01.py draft
against actual candle-lineage/evaluator trace fields, then implement the atomic
strategy-specific trigger consumer and direct-entry guard.** The original premature
entry reproduction is retained; do not re-run the full audit or recreate the plan.
ForwardPaperCoordinator/PaperPortfolio are unchanged; no new trigger policy is
registered. Do not treat the draft's compilation as a successful lifecycle test.

Safe first command from app directory:
`Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md`.
Then inspect `git diff --stat`, relevant paper files and the current proof receipt;
the stored source hash reveals any intervening edits. Do not repeat destructive,
external or still-running commands. No session work continues after final response.

Reusable continuation: `CONTINUE FROM CHECKPOINT. Resume B01.2, preserve verified
HTTP/research/UI/passport/rank-prototype work and prior evidence. Finish the ORB
strategy-specific atomic trigger path, migrate unsafe automatic legacy behavior,
test actual scanner/ledger/API use, then integrate persistent rank history. No
provider calls or real orders; update all three checkpoint files after each unit.`
""",
18: """## 18. Source references and evidence limits

Official URLs are cited beside claims in sections7/8/12/13; accessed2026-10-24.
Provider docs describe available schemas, not account access, historic date
authority or resale rights. Regulatory documents identify questions for counsel,
not a commercial sign-off. The current NSE linked policy has changed numbering
from older drafts; use verified clauses7.3/7.4, not copied older8.3/8.4 references.

Repository evidence: baseline/extracted original BRD; preserved Phase4/5/6 strict
receipts and manifests; actual pre-fix paper/HTTP/research/UI logs; new focused and
canonical receipts; strategy research notes and earlier proposed preregistration.
Precise source symbols/ranges are in astra_code_locations evidence. No operational
DB contents, private token values or unobserved performance appear in this report.
All experimental rank/paper examples are synthetic engineering examples. Original
six-phase roadmap and every previous report/release/receipt remain preserved.
"""
    }
    for number, content in sections.items():
        content = content.replace("NODECOUNT", str(node["executed"]))
        pattern = rf"## {number}\. .*?(?=\n## \d+\.|\Z)"
        text, count = re.subn(pattern, lambda match, value=content: value.rstrip()+"\n", text, flags=re.S)
        assert count == 1, number
    text = text.replace("Working report, 2026-10-24 IST.", "Work spanning 2026-10-24–25, Asia/Kolkata.")
    # Keep prose readable without rewriting identifiers, receipt names or URLs.
    for before, after in {
        "Phase6": "Phase 6", "Phase4/5/6": "Phases 4/5/6", "Phase7": "Phase 7",
        "filled98": "filled at 98", "threshold100": "threshold 100", "high99": "high 99",
        "and88": "and 88", ".522": ". 522", "Python3.14.6": "Python 3.14.6",
        "Node24.18.0": "Node 24.18.0", "returns405": "returns 405", "at10:00": "at 10:00",
        "at10:10": "at 10:10", "quality90": "quality 90", "INFY80": "INFY 80",
        "TCS85": "TCS 85", "INFY95": "INFY 95", "moves2->1": "moves 2->1",
        "TCS1->2": "TCS 1->2", "regular5-level": "regular 5-level", "and30-level": "and 30-level",
        "valid1 year": "valid 1 year", "Plus30-depth": "Plus 30-depth", "documented3:30": "documented 3:30",
        "before:2": "before: 2", "After2/2": "After 2/2", "Before27": "Before 27",
        "pass/3": "pass / 3", "expiry5m": "expiry 5m", "borrowed from stop;32": "borrowed from stop; 32",
        "Then32": "Then 32", "coerced to0": "coerced to 0", "retained. Re-run54": "retained. Re-run 54",
        "RELIANCE2026": "RELIANCE 2026", "missing15:15": "missing 15:15", "and15:20": "and 15:20",
        "nominal\n60/20/20": "nominal\n60/20/20", "win>=50%,100-trade": "win>=50%, 100-trade",
        "scope.32": "scope. 32", "top3": "top 3", "scope;11": "scope; 11",
        "clauses7.3/7.4": "clauses 7.3/7.4", "older8.3/8.4": "older 8.3/8.4",
        "Accessed2026": "Accessed 2026", "accessed2026": "accessed 2026",
        "July23,2025": "July 23, 2025", "October10,2026": "October 10, 2026",
        "February6,2026": "February 6, 2026", "March2026": "March 2026",
        "clauses6.3/7.3/7.4": "clauses 6.3/7.3/7.4", "sections7/8/12/13": "sections 7/8/12/13",
        "size is0": "size is 0", "contain111": "contain 111", "and122": "and 122",
    }.items():
        text = text.replace(before, after)
    text = text.replace("**IN_PROGRESS — no whole-mission or customer-release acceptance.**",
        "**PARTIAL CHECKPOINT — tested changes accepted only within their stated scope.**\n\nLast regenerated UTC: " + stamp)
    text = re.sub(r"Last regenerated UTC: [^\n]+", "Last regenerated UTC: " + stamp, text)
    assert "**IN_PROGRESS" not in text
    report.write_text(text, encoding="utf-8")
    print(json.dumps(dict(status="UPDATED_PARTIAL_REPORT", python=p["executed"], node=node["executed"],
        compiled=compiled, updated_at=stamp)))


if __name__ == "__main__":
    main()
