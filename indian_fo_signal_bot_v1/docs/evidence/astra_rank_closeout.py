"""Preserve prior handoff, bind verified C03 source, and update mission documents.

Explicit invocation only; no runtime initialization or operational database access.
Existing receipts and handoff archives are never overwritten.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from astra_preservation_check import sha, historical_receipt
from verify_offline import source_snapshot, validate_evidence

NAMES = ["TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md", "TRADEPULSE_ASTRA_CHECKPOINT.md",
         "TRADEPULSE_ASTRA_PROGRESS.md", "TRADEPULSE_ASTRA_TASK_LEDGER.md"]


def exclusive(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--supplement", action="append", default=[])
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_]+", args.stage)
    evidence = APP / "docs/evidence"
    proof_path = evidence / args.receipt
    assert proof_path.parent == evidence and proof_path.suffix == ".json"
    proof = validate_evidence(proof_path)
    baseline = json.loads((evidence / "astra_baseline_20261024_01.json").read_text(encoding="utf-8"))
    owner_path = evidence / "astra_owner_changes_20261026_01.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert all(sha(APP / name) == value for name, value in baseline["preserved_documents"].items())
    assert set(owner["saved_config"]) == set(baseline["saved_config_hashes"])
    assert all(row["baseline_hash"] == baseline["saved_config_hashes"][name]
               and sha(Path(name)) == row["observed_hash"] for name, row in owner["saved_config"].items())
    assert all(sha(APP / name) == row["observed_hash"] for name, row in owner["external_source"].items())
    assert sha(Path(r"C:\Users\HP\Downloads\TradePulse_AI_BRD_and_Project_Status_2026-10-24.docx")) == baseline["brd_sha256"]
    closeout_path = evidence / ("astra_rank_closeout_" + args.stage + ".json")
    if args.validate_only:
        result = json.loads(closeout_path.read_text(encoding="utf-8"))
        assert result["source"] == source_snapshot(APP)
        assert all(sha(APP / name) == value for name, value in result["files"].items())
        print(json.dumps(dict(status="PASS", scope=result["scope"], files=len(result["files"]))))
        return

    assert not closeout_path.exists()
    historical = [historical_receipt("master_phase45_20261024_03.json", "phase45_release_20261024_01.zip"),
                  historical_receipt("master_phase6_20261024_01.json", "phase6_release_20261024_01.zip")]
    browser_paths = [evidence / name for name in ("astra_browser_chrome_20261026_02.json",
                                                  "astra_browser_edge_20261026_01.json")]
    extra_paths = list(browser_paths) + [owner_path]
    for browser_path in browser_paths:
        browser = json.loads(browser_path.read_text(encoding="utf-8"))
        assert browser["status"] == "PASS" and browser["exit_code"] == 0
        assert browser["assertions"] == {"passed": 36, "total": 36}
        assert browser["source_unchanged"] and all(sha(APP / k) == v for k, v in browser["source_after"].items())
        assert browser["external_assets_omitted"] and browser["server_thread_stopped"] and browser["temporary_profile_removed"]
        for artifact in browser["artifacts"]:
            path = evidence / artifact["file"]
            assert path.parent == evidence and sha(path) == artifact["sha256"]
            extra_paths.append(path)
    demo_path = evidence / "astra_rank_integrated_demo_20261027_01.json"
    demo = json.loads(demo_path.read_text(encoding="utf-8"))
    assert demo["status"] == "PASS" and demo["exit_code"] == 0 and all(demo["checks"].values())
    assert demo["source_before"] == demo["source_after"] == proof["source_after"]
    assert sha(APP / demo["helper"]) == demo["helper_sha256"]
    extra_paths += [demo_path, APP / demo["helper"], APP / "docs/reports/astra_d01_contract_inventory_20261026_01.md",
                    APP / "docs/reports/astra_context_health_review_20261026_01.md",
                    APP / "docs/reports/astra_reference_cache_review_20261027_01.md"]
    supplements = [(APP / name).resolve() for name in args.supplement]
    assert all(path.is_file() and path.is_relative_to(APP / "docs") for path in supplements)
    assert all(path.is_file() for path in extra_paths)
    count = proof["python"]["executed"]
    node = next(c["executed"] for c in proof["checks"] if isinstance(c["command"], list) and c["command"][0] == "node" and "executed" in c)
    compiled = next(c["compiled_files"] for c in proof["checks"] if "compiled_files" in c)
    now = datetime.now(timezone.utc).isoformat()
    paths = [APP / "docs/project" / name for name in NAMES]
    assert not (evidence / ("astra_handoff_before_rank_" + args.stage + ".json")).exists()
    assert not (evidence / ("astra_rank_preservation_" + args.stage + ".json")).exists()
    previous = {path.name: path.read_text(encoding="utf-8") for path in paths}
    archive = evidence / ("astra_handoff_before_rank_" + args.stage + ".json")
    exclusive(archive, dict(recorded_at=now, files=previous,
                           original_bytes_base64={path.name: base64.b64encode(path.read_bytes()).decode("ascii") for path in paths},
                           sha256={path.name: sha(path) for path in paths}))
    preservation_path = evidence / ("astra_rank_preservation_" + args.stage + ".json")
    exclusive(preservation_path, dict(status="PASS", recorded_at=now,
        scope="C03_CASH_PRIORITY_OFFLINE_SLICE_NOT_MISSION_ACCEPTANCE", current_receipt=args.receipt,
        current_receipt_sha256=sha(proof_path), source=source_snapshot(APP), python=count, node=node,
        compiled_files=compiled, historical=historical,
        prior_documents_preserved=len(baseline["preserved_documents"]),
        both_env_files_match_original_baseline=all(r["unchanged_since_baseline"] for r in owner["saved_config"].values()),
        owner_confirmed_external_changes_preserved=True, owner_changes_receipt=owner_path.name,
        original_brd_preserved=True, operational_db="NOT_OPENED_CONTENTS_UNATTESTED", provider_requests=0,
        dynamic_ranking="RETAINED_SOURCE_TRANSACTION_API_UI_VERIFIED_OFFLINE",
        paper_trigger="ORB_PROSPECTIVE_MECHANICS_OTHER_STRATEGIES_UNAVAILABLE"))

    content = previous[NAMES[0]]
    def section(number, title, body):
        nonlocal content
        start = content.index(f"## {number}. ")
        end = content.index(f"## {number + 1}. ", start)
        content = content[:start] + f"## {number}. {title}\n\n" + body.strip() + "\n\n" + content[end:]
    content = re.sub(r"Last updated UTC: .*", "Last updated UTC: " + now, content, count=1)
    content = content.replace("Work spanning 2026-10-24–25", "Work spanning 2026-10-24–26")
    section(1, "Executive verdict", f"""
**PARTIAL VERIFIED OFFLINE ENGINEERING; MASTER MISSION INCOMPLETE.** Dynamic cash
candidate priority now consumes retained scanner inputs, commits immutable history
with the scan result, and serves a bounded read-only API/dashboard. A two-stock
actual evaluator fixture changes TCS/INFY priority on new volume evidence and
retains the explanation. Fixture inputs do not establish real market acceptance.

Current-source canonical proof: **{count}/{count} Python tests, {node}/{node} Node
tests, {compiled} compiled Python files**, zero failures/errors/skips/unraisables.
Source stayed unchanged during the run. All priority output remains non-actionable;
rule quality and actual gross reward/risk are not probabilities or net returns.

Scanner context decisions now share one authenticated write transaction, avoiding
repeated full snapshot/evaluation validation for every candidate. Health checks
share one fresh read snapshot across symbols and still validate every receipt.
Corruption, duplicate and rollback regressions pass. An instrumented concurrent
health probe still exceeded its3s limit; the final canonical result is a bounded
offline test result, not a production latency guarantee or proof of its cause.

B01's verified ORB prospective paper trigger remains covered. It requires a later
qualified close cross and scanner health; unsupported strategies do not inherit
it. Legacy automatic next-close entries reject; committed accounting recovery
remains supported. Other strategy/F&O triggers, authentic empirical/OOS evidence,
genuine live consumer acceptance and customer launch remain incomplete.

This task did not edit saved configuration, operational databases or Git history.
The owner confirmed separate broker/config/app-env/live-helper edits, which remain
preserved. The app env differs from the original baseline; the root env matches.
The unrun local live helper is explicitly excluded from release packaging.
No provider call, real order or notification send occurred in this task. The next engineering
task is D01.2: provider-neutral exact option/Greeks/benchmark validators and offline
fixtures, using the completed D01.1 inventory. Chrome and Edge each passed36 actual
DOM/keyboard checks at desktop/mobile viewports. External styling/chart assets were
omitted, so full visual/mobile acceptance and product/security review remain open.
""")
    content = content.replace("## 2. Audit manifest and Git state\n", "## 2. Audit manifest and Git state\n\nOwner-confirmed parallel changes to brokers.py/config.py/app .env and local verify_live_quick.py are preserved and separately hash-bound in astra_owner_changes_20261026_01.json. The app env differs from the original baseline. This task did not execute the helper or activate these settings; it excluded only this named local helper from release packaging. Its printed PASS labels are not acceptance evidence.\n")
    content = content.replace("browser visual/mobile/new delivery acceptance NOT_ATTEMPTED",
        "actual Chrome/Edge DOM and keyboard checks pass; external-asset styling/mobile visual/new delivery acceptance NOT_ESTABLISHED")
    content = content.replace("new ranker prototype tested, runtime rank history NOT_ESTABLISHED",
        "source-bound cash rank history/API/UI VERIFIED_OFFLINE; empirical factors and exact option ranking unavailable")
    content = content.replace("X[New rank-change prototype] -. integration pending .-> E",
        "E --> X[Authenticated cash rank history]\n  X --> H")
    content = content.replace("SQLite operational schema and data\nwere not migrated by this slice.",
        "The additive rank table/index migration was tested only in isolated fixtures;\noperational SQLite schema and data were not opened or migrated by this slice.")
    content = content.replace("Exact final hashes and historical archive checks are in the new\nastra_preservation receipt.",
        "C03 additionally adds rank_history.py/test_astra_rank_history.py, changes storage.py\nand scanner/lineage/server/UI integration, and registers release/test modules. The\nHTTP recovery also changes notification_outbox.py/readiness_policy.py and adds\ntest_astra_context_batch.py/test_astra_health_reads.py plus scanner-reference and\nevaluation-read regression modules. Exact source reuse and container traversal\npreserve identity, strategy, freshness and nested reference validation. Exact current hashes and\nhistorical archive checks are in astra_rank_preservation_" + args.stage + ".json.")
    section(6, "Dynamic ranking specification and integrated evidence", """
`opportunity_ranking.build_snapshot/current_view` uses rule quality descending,
actual gross T1 reward/risk descending, then deterministic identity ties. Policy
`CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2` includes LONG/SHORT position type
in each opportunity identity and retains one selected setup per cash symbol.
Missing relative strength, sector, regime, liquidity, spread, net executable reward
and empirical edge remain unavailable. No new indicator formula or strategy
promotion was introduced. Exact option-contract fitness is a separate requirement.

`rank_history.record` runs inside `candle_lineage.finish`'s existing scan transaction.
It checks committed candle identity/timestamps/digests, evaluation/trace links,
persisted qualified signal geometry and direction, and the frozen runtime/source
profile before writing. The input snapshot requires ranking, so removal of result
flags and a rank row cannot downgrade a new scan into legacy compatibility.
Signals, evaluations, outbox and rank result commit or roll back together.
Accepted pending input batches may remain available for later recovery.

History links the preceding committed scan in the same runtime scope. Append
checks latest committed input before consulting surviving rank rows; a deleted
latest row cannot be skipped by a later valid scan. Reversed input chronology
rejects. Reads verify current source plus one predecessor's base priority; they
do not recursively audit all historical deltas. The current change explanation
is fully rebuilt. Checksums and cross-table links establish local consistency,
not publisher authenticity or protection against wholesale database rewriting.
The indexed input-scope lookup avoids sorting the full scan history for latest.

GET/HEAD `/api/opportunity-rankings` and `/api/v1/opportunity-rankings` accept only
run_id, bounded limit and offset. They never acquire data, queue paper decisions or
write ranks. The server supplies time; invalid/corrupt data is unavailable with no
fallback to an older current row. Changed profile/code and stale/future snapshots
have empty current rows and an explicit archive. Ordinary SIMULATED scans lack
durable cash input and remain unavailable. Source authenticity is NOT_ESTABLISHED.

The dashboard presents current or historical priority, LONG/SHORT, prior/new rank,
changed components, source watermark, missing factors and removals. All strings
use safe text rendering. Async generation checks prevent old responses restoring
an expired or failed view. Expiry is source bar start +5 minutes +60 seconds;
monotonic elapsed time prevents a backward wall-clock jump extending that window.
The panel is a bounded preview; full user pagination/browser acceptance remains
separate. No ranking control executes a paper or real order.

The integrated synthetic TCS/INFY test uses the actual native-adapter mocked wire,
existing ORB evaluator, scanner and SQLite lineage. New volumes change their
priority and produce retained rule-quality/component deltas. Other tests cover
duplicate replay/restart, empty refresh/removal, direction identity, exact expiry,
profile/code archive, source/score forgery, required-history downgrade, deleted
latest append, predecessor corruption, rollback, indexed lookup and read-only
HTTP/renderer failure handling. This is software acceptance, not observed edge.

Retained integrated demo `astra_rank_integrated_demo_20261027_01.json` executes
that real scanner fixture: TCS quality78 to69; INFY63 to81. Initial TCS/INFY order
becomes INFY/TCS with previous ranks2/1 and SCORE_COMPONENT_CHANGED. Gross T1 RR
is approximately1.6 in both examples. This artifact contains no genuine market data.
""")
    content = content.replace("## 7. Options, volume, depth and Greeks assessment\n",
        "## 7. Options, volume, depth and Greeks assessment\n\nD01.1 inventory is now complete in [the focused contract report](../reports/astra_d01_contract_inventory_20261026_01.md), accessed2026-10-26. Existing exact-contract identity and historical quote/depth replay are reusable. The inspected live chain flatteners discard fields and default some missing Greeks/IV to zero; source clocks and endpoint unit policies remain incomplete. This is an inspected integration boundary, not a new runtime acceptance. Next D01.2 must preserve raw units/presence/clock provenance and keep missing normalization unavailable. Official examples do not establish a cross-endpoint IV scale conversion. C03 did not change adapters; separately confirmed owner edits are listed in section2.\n")
    content = content.replace("|R01 prototype coverage boundary|New rank history is standalone. Net friction, source authenticity and sector correlation are unavailable, not imputed. No runtime integration claim.|",
        "|R01 coverage boundary|Cash rank history/API/UI integrated offline. Net friction, publisher authenticity, sector correlation and exact option fitness remain unavailable.|")
    content = content.replace("|R02 medium stale current priority, corrected|",
        "|R03 high rank history integrity, corrected|Independent review reproduced result/row downgrade and append past deleted latest history. Required input marker and committed-input predecessor selection now reject both; before/after logs retained.|\n|R04 medium rank semantics/clock, corrected|Directional identities are distinct; browser uses monotonic elapsed time for expiry. Both findings reproduced before repair and covered in canonical proof.|\n|R05 repeated context validation, corrected|16 candidates caused17 context reconstructions and33 evaluation checks. One authenticated batch reduces those to2 each including construction; per-decision checks and atomic rollback remain. Health receipt reads also share one fresh snapshot.|\n|R06 concurrent HTTP latency, observed limitation|Three intermediate canonical stages failed HTTP timing; instrumented after-probe still exceeded the3s health assertion. The final uninstrumented proof is stated separately. No global latency guarantee or sole-cause attribution.|\n|R02 medium stale current priority, corrected|")
    content = content.replace("vanilla JS kept. Incomplete trigger and dynamic ranker are not dressed as live UI.",
        "vanilla JS kept. Integrated candidate priority remains separate from paper trigger\nauthority; synthetic acceptance is never displayed as live-market validation.")
    content = content.replace("32 Node\ntests pass; actual browser/mobile/accessibility acceptance was not rerun.",
        "38 Node tests pass. Chrome and Edge each pass36 actual DOM/keyboard checks at\ndesktop/mobile viewports; production-asset visual styling and full accessibility\nacceptance remain unestablished.")
    content = content.replace("UI review was its author's self-review.\nFull paper/product/browser approval remains outstanding after worker limits.",
        "Earlier UI review was its author's self-review. Subsequent independent rank\nreview and browser DOM/keyboard checks are documented in section15. Full paper,\nproduct/security and production-assets visual/accessibility approval remain open.")
    content = content.replace("Paper draft and final browser/product acceptance remain unreviewed. UI self-review is not independent.",
        "B01 repair and C03 received scoped independent review; Chrome/Edge DOM/keyboard checks passed. Full product/security and production-assets visual/accessibility acceptance remain open.")
    content = content.replace("Personal alpha: finish B01, integrate rank snapshots, preserve localhost isolation,",
        "Personal alpha: extend qualified strategy policies, verify actual browser usability, preserve localhost isolation,")
    content = content.replace("|C03 /4 /coordinator|Prototype VERIFIED; integration NOT_STARTED|Atomically persist rank snapshots with scan inputs, expose read API/UI and test source tamper/rollback, duplicate/empty/out-of-order runs. Preserve original ranker.|",
        "|C03 /4,5 /coordinator|VERIFIED_COMPLETE for offline cash priority scope|Source-bound atomic history, read API/UI, TCS/INFY evaluator fixture, adversarial corruption/rollback/ordering and canonical proof. Wider empirical/contract factors remain unavailable.|")
    content = content.replace("|F02 /6 /coordinator|Current-slice proof; final release NOT_STARTED|Finish B01/C03, canonical final receipt, independent review and fresh archive. Prior archives preserved.|",
        "|F02 /6 /coordinator|Current-slice proof; mission release NOT_STARTED|B01 ORB and C03 source verified; D01, broader lifecycle, browser and full review remain. Existing release packager includes new modules; no new archive or customer release.|")
    content = content.replace("|D01 /2,3 /data owner|Documentation PARTIAL|", "|D01 /2,3 /data owner|D01.1 inventory VERIFIED; D01.2 NOT_STARTED|")
    content = content.replace("Journal bounded preview only; full paging, browser/mobile/keyboard review still pending.",
        "Journal/rank bounded previews. Chrome/Edge actual DOM/keyboard pass at two viewports; full paging, production-assets visual/mobile/accessibility acceptance pending.")
    content = content.replace("Offline B01/C03/D01/E02 can proceed", "Offline remaining B01/D01/E01.2/E02 can proceed")
    old_start = content.index("## 15. ")
    old_end = content.index("## 16. ", old_start)
    old15 = content[old_start:old_end].replace("**Latest executed canonical proof:**", "**Historical B01 boundary proof:**", 1)
    intro = f"""## 15. Verification ledger

**Current-source canonical proof:** `../evidence/{args.receipt}`: PASS
{count}/{count} Python, {node}/{node} Node, {compiled} compiled files, exit 0 and
zero failures/errors/skips/unraisables. Exact executed IDs, timestamps, log hashes
and unchanged source-before/after are retained. RUN command:
`.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage {proof['stage']}`.

C03 canonical stages _01 and _02 each completed1106/1107 Python. The first timed
out in the concurrent dashboard burst; the second timed out waiting for the slow
primary scan response. Node38 and compile92 passed both. The original four-test
Phase1F class passed between them with unchanged limits. All failures remain.

Instrumented before-probe PASS4 recorded48 separate context submissions across
three scans. A deterministic regression then demonstrated17 snapshot reconstructions
and33 evaluation validations for16 candidates. Atomic batching now requires2 each
(construction plus fresh transaction validation), preserving every decision/intent
check. A separate health regression demonstrated one connection per symbol;
the shared read snapshot removes that repetition while rechecking every receipt.
Combined context/health/HTTP/rank/cash integration PASS104/104, including11 new
batch tests and3 health tests; independent read-only review found no material issue.

Instrumented after-probe FAIL3/4: a health response took3.44s against the unchanged
3s assertion. Context enrichment across3scans measured1.085s versus3.245s before;
210 acceptance lookups measured0.025s versus2.892s. These overlapping instrumented
wall times are not a controlled performance benchmark. This failure is retained;
neither successful integrity tests nor the final uninstrumented canonical result
establish a production latency guarantee. There was no timeout relaxation.

Stage _03 completed1118/1121 (two failures/one error): health3.44s>3s, primary
scan5s timeout, and a newly added unregistered local helper. Owner confirmed
separate brokers/config/app-env/helper changes; source was unchanged during that
run. The helper is preserved and explicitly excluded from bundles; focused release
tests PASS17. Existing unknown-production-module detection remains active.

Further native scan profiling found86 repeated source-reference normalizations
and37472 recursive reference visits in one evaluation read. A retained one-stock
regression found7 normalizations versus2; scan-local metadata reuse keys exact
raw candle content, returns deep copies, and preserves evaluator/freshness checks.
Nested reference traversal now recurses only into containers, checking every dict
even inside arbitrary extension/list fields. New regressions verify unchanged
payloads, raw-input mutation invalidation and later rehashed source corruption.
Initial scanner-after failures from a missing copy import and a mistyped test
module are retained, corrected, and superseded by actual successful checks.
Combined latency/integrity/release integration passed129/129. Review then found
raw datetime input could fail the optional fingerprint; a retained failing test
was corrected by bypassing metadata reuse when raw JSON fingerprinting fails.
The final focused scanner/evaluation/HTTP run passed11/11 (4 scanner,3 traversal,
4 original concurrent HTTP tests). Independent scanner/release review found no
remaining material issue. The traversal author owns its3 tests; coordinator
review is separate. Recursion dropped37472 to3844 calls with all nested-reference
checks retained. This is bounded work reduction, not production SLO acceptance.

Actual browsers: astra_browser_chrome_20261026_02 and astra_browser_edge_20261026_01
each PASS36, exit0. Desktop1440x1000 and mobile390x844: DOMContentLoaded, literal
hostile text, missing/zero values, native Tab/Enter refresh/navigation, real expiry,
HTTP503 clearing and delayed-response suppression. GET-only exact-origin requests,
blocked external/POST probes, no JS exception/crash, clean browser/profile/server
shutdown. Chrome155/Edge156 runs took4.755/5.43seconds. CSS/fonts omitted and
Chart/Tailwind stubbed; screenshots are diagnostic DOM evidence, not visual/mobile
layout approval. Initial Chrome _01 FAIL retained; the harness's async Enter wait
was corrected without production changes. Browser receipt/artifact hashes checked.

Integrated demo20261027_01 PASS1/1, two source-bound views, unchanged current source
snapshot matching the canonical receipt. Earlier _02 matched the prior97-file
snapshot; its first sandbox SQLite failure remains preserved. D01.1 read-only inventory
reconfirmed public schemas and documents exact unresolved units/clocks; no provider
request or validator implementation is implied by that inventory.

C03 RUN receipts: rank_history_initial_20261025_01 had one fixture exception
expectation error; integrated_20261025_01 PASS48; review_repairs_20261025_01 PASS105;
rank_history_boundary_20261026_01 PASS62. Downgrade, direction and clock before-fix
failures remain preserved. Node clock-after PASS38. rank_order_before_20261026_01
failed3 on sandbox SQLite access; authorized offline rerun _02 PASS2/FAIL1 proved
the append-history gap. Corrected boundary/canonical runs include that regression.

Independent read-only reviewer confirmed the first three repairs, then found the
append gap. Root reproduced, repaired and tested it; the reviewer subsequently
confirmed the final repair with no further material finding. This is scoped
independent review, not whole-product sign-off. Browser DOM-double tests are
distinct from actual browser acceptance. No provider/network/order/send claim.

`astra_rank_preservation_{args.stage}.json` validates522 original documents,
original BRD and both historical archives. Root env matches the original baseline;
the app env and separate source edits match the owner-confirmed change receipt,
not their original baseline. No credential values were retained. Current source differs
from their historical proof, as expected. Prior mutable handoff text is archived
in `astra_handoff_before_rank_{args.stage}.json`; machine receipts never overwrite.
`astra_rank_closeout_{args.stage}.json` binds current report/checkpoints/proof/logs.

"""
    content = content[:old_start] + intro + old15[len("## 15. Verification ledger\n\n"):] + content[old_end:]
    content = content.replace("No claim of new browser acceptance, full independent final review, empirical",
        "The historical receipt did not establish browser acceptance. The new browser scope\nis stated above; no full independent product review, empirical")
    section(17, "Next-session checkpoint", """
Current completed unit: C03.2 authenticated cash rank persistence/read API/UI,
including missing-history append repair and canonical offline verification.
The context batch and health read repairs are verified for integrity; the failed
instrumented latency probe remains a separate limitation requiring future operating
measurements. Timeout thresholds were not changed.
Broader mission remains incomplete. Safe first command:
`Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md`.

Next eligible task: **D01.2 — implement the pure bounded observation validator
and endpoint fixtures specified by the completed D01.1 contract inventory.**
Reconfirm endpoint-specific official units/identity/timestamps before adapters;
no provider activation, guessed Greeks units, silent fallback or credentials edits.
Existing cash ranking must remain deterministic and F&O fitness separate.

E01.2 production-assets visual/mobile/accessibility checks and broader B01 policies
remain eligible work; actual browser DOM/keyboard checks are complete. Do not repeat
the baseline audit or recreate completed
ORB/ranking implementations. All new test stages/evidence must use unique names.

Resume: `CONTINUE FROM CHECKPOINT. Preserve verified B01 ORB and C03 rank history;
resume the exact active D01/E01.2 step, with no provider calls, real orders or sends.`
""")
    import subprocess
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
    content = content.replace("Branch main; starting HEAD `fcdbadb`,", "Current externally advanced HEAD `" + head + "`; this task made no Git writes.\nBranch main; starting HEAD `fcdbadb`,")
    assert len(re.findall(r"^## \d+\. ", content, re.M)) == 18
    paths[0].write_text(content, encoding="utf-8")
    paths[1].write_text(f"""# TradePulse Astra execution checkpoint

## Current verified C03 boundary — {now}

Mission incomplete. Phase4/5 task C03.2 VERIFIED_COMPLETE within offline cash
candidate priority scope. Latest canonical {args.receipt}: PASS {count} Python,
{node} Node, {compiled} compiled files, zero failures/errors/skips/unraisables.
Source/log validation and preservation PASS; source hashes in the receipt.

Actual retained scanner/evaluator inputs feed atomic rank history and bounded
read-only API/UI. TCS/INFY reversal fixture, directional identity, source corruption,
rollback, expired/history, combined downgrade and deleted-latest append checks pass.
Local integrity is not market authenticity or empirical strategy acceptance.
B01 ORB future-trigger software remains covered; other strategy/F&O policies absent.

Branch main; externally advanced HEAD {head}. Current files include rank_history.py,
opportunity_ranking.py, scanner_engine.py,
candle_lineage.py, storage.py, server.py, notification_outbox.py, readiness_policy.py,
public/index.html, new and existing tests,
release/test registration. Four mutable handoff documents were updated; prior
text is preserved in astra_handoff_before_rank_{args.stage}.json. No commands are
running at this verified boundary. This task made no provider/env/operational DB/Git
mutation. Owner-confirmed broker/config/app-env/live-helper edits are preserved;
app env no longer matches the original baseline. See astra_owner_changes_20261026_01.json.

Context/health combined regression PASS104; later combined integration PASS129.
Final scanner/evaluation/HTTP compatibility PASS11. Four scanner-reference and
three container-traversal tests are registered in the full canonical suite.
Current external HEAD is {head}; no Git writes by this task.
Instrumented after-probe FAIL3/4 (health3.44s versus3s); no latency limits changed.
Final canonical above passes, but this does not establish a production latency SLO.

Next task D01.2: implement pure bounded option/Greeks/benchmark observation
validators and offline endpoint fixtures from completed D01.1 inventory. Actual
Chrome/Edge DOM/keyboard checks each PASS36; full external-asset visual/mobile and
accessibility acceptance and broader B01 lifecycle remain eligible work.
Read the current task ledger and master report; do not repeat the baseline audit.
Resume instruction: CONTINUE FROM CHECKPOINT.

## Historical checkpoint text (superseded for current-source proof)

""" + previous[NAMES[1]], encoding="utf-8")
    with paths[2].open("a", encoding="utf-8") as stream:
        stream.write(f"\n## C03 verified boundary — {now}\n\nCurrent canonical PASS {count} Python/{node} Node/{compiled} compile.\nIndependent append-gap finding reproduced (2 pass/1 fail), repaired with latest\ncommitted-input selection; focused62/62 and canonical PASS. Indexed lookup and\nresult-mode hiding covered. First two canonicals each1106/1107 had different HTTP\ntimeouts. Deterministic redundant context/health-read regressions reproduced and\nrepaired with transaction-local batching; combined integration104/104 passes and\nindependent scoped review found no material issue. Instrumented after-probe still\nFAIL3/4 on health3.44s>3s. Final canonical passes unchanged timeout limits; no\nproduction latency guarantee. Chrome/Edge each36 DOM/keyboard checks pass; full\nvisual styling absent. Integrated demo20261027_01 retains TCS78/INFY63 then69/81 against\ncurrent source. D01.1 inventory done, D01.2 validator is next.\nPrevious receipts/handoff retained;522 old docs, BRD and historical archives\npreserved. Owner-confirmed source/app-env changes are separately hash-bound. No operational/provider/Git actions and no new release archive.\n")
    replacements = {
        "B01": "|B01|6|Strategy-specific automatic paper lifecycle|IN_PROGRESS|ORB offline slice verified; other strategy/contract triggers unavailable|",
        "C03": "|C03|4|Dynamic opportunity rank history|VERIFIED_COMPLETE|Offline cash priority scope; authentic market/empirical factors separate|",
        "C03.1": "|C03.1|4|Deterministic builder and expiry|VERIFIED_COMPLETE|9 tests; direction identity and exact expiry; canonical|",
        "C03.2": "|C03.2|4/5|Retained source validation/persistence/API/UI|VERIFIED_COMPLETE|18 rank-history tests; focused 62 plus full canonical; current/history distinction|",
        "F02.1": f"|F02.1|6|Current-slice canonical and preserved history|VERIFIED_COMPLETE|{count} Python/{node} Node/{compiled} compile; exact source/log/preservation bindings|",
        "F02.2": "|F02.2|6|Whole mission final package|NOT_STARTED|D01, broader B01, browser and independent product review remain; no new ZIP|",
        "E01.2": "|E01.2|5|Browser/mobile/accessibility/pagination acceptance|IN_PROGRESS|Chrome/Edge DOM/keyboard PASS36 each; production-assets styling/full accessibility/paging pending|",
    }
    lines = previous[NAMES[3]].splitlines()
    for i, line in enumerate(lines):
        parts = line.split("|")
        if len(parts) > 2 and parts[1] in replacements:
            lines[i] = replacements[parts[1]]
    lines.extend(["|D01.1|2/3|Neutral point-in-time contract inventory|VERIFIED_COMPLETE|Source and official public-schema inventory retained; no runtime/entitlement claim|",
                  "|D01.2|2/3|Pure observation validator and offline endpoint fixtures|NOT_STARTED|Exact next task; preserve raw units/clocks/presence, reuse dated identity; no provider activation|",
                  "|E01.3|5/6|Context batching and health read integrity|VERIFIED_COMPLETE|11 batch and3 health regressions; combined104 and full canonical; transaction-local validation, no production latency claim|",
                  "|E01.5|5/6|Exact source metadata reuse and bounded evaluation traversal|VERIFIED_COMPLETE|4 scanner and3 nested-reference tests; combined129/final11/canonical; independent scanner review|",
                  "|E01.4|5/6|Production latency acceptance|NOT_STARTED|Instrumented after-probe failed3s health limit; current canonical passes original limits; controlled operating measurements pending|",
                  "|E01.2a|5|Actual browser DOM and keyboard|VERIFIED_COMPLETE|Chrome36/36 and Edge36/36; two viewports, fixture GET-only; external assets omitted|"])
    paths[3].write_text("\n".join(lines) + "\n", encoding="utf-8")
    bound_paths = paths + [archive, preservation_path, proof_path, Path(__file__).resolve()] + extra_paths + supplements
    bindings = {path.relative_to(APP).as_posix(): sha(path) for path in bound_paths}
    bindings.update(proof["logs"])
    exclusive(closeout_path, dict(status="PASS", recorded_at=now,
        scope="C03_VERIFIED_OFFLINE_BOUNDARY_NOT_WHOLE_MISSION", source=source_snapshot(APP), files=bindings))
    assert all(sha(APP / name) == value for name, value in bindings.items())
    print(json.dumps(dict(status="PASS", python=count, node=node, compiled=compiled, files=len(bindings))))


if __name__ == "__main__":
    main()
