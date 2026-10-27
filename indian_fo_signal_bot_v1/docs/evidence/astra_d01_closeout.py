"""Bind the D01 offline slice to executed tests and preserved prior evidence."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

NAMES = ["TRADEPULSE_ASTRA_" + name + ".md" for name in
         ("MASTER_EXECUTION_REPORT", "CHECKPOINT", "PROGRESS", "TASK_LEDGER")]
CHANGES = {"option_observations.py", "benchmark_observations.py", "test_option_observations.py",
           "test_benchmark_observations.py", "test_bot.py", "release_management.py"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exclusive(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def preserved(baseline):
    for path, checksum in baseline["preserved_documents"].items():
        assert sha(APP / path) == checksum, path
    for path, checksum in baseline["saved_config_hashes"].items():
        assert sha(Path(path)) == checksum, "saved configuration changed"
    for path, checksum in baseline["external_source_hashes"].items():
        assert sha(APP / path) == checksum, path
    for row in baseline["handoff"].values():
        assert hashlib.sha256(base64.b64decode(row["original_bytes_base64"])).hexdigest() == row["sha256"]


def replace_section(content, number, body):
    start = re.search(rf"^## {number}\. .*\n", content, re.M)
    end = re.search(rf"^## {number+1}\. ", content, re.M)
    assert start and end
    return content[:start.end()] + "\n" + body.strip() + "\n\n" + content[end.start():]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_]+", args.stage)
    evidence = APP / "docs/evidence"
    proof_path = evidence / args.receipt
    assert proof_path.parent == evidence and proof_path.suffix == ".json"
    proof = validate_evidence(proof_path)
    baseline_path = evidence / "astra_d01_baseline_20261027_01.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    preserved(baseline)
    source = source_snapshot(APP)
    assert set(source) >= set(baseline["source"])
    changes = {p for p, checksum in source.items() if baseline["source"].get(p) != checksum}
    assert changes == CHANGES, changes
    closeout = evidence / ("astra_d01_closeout_" + args.stage + ".json")
    now = datetime.now(timezone.utc).isoformat()
    if args.validate_only:
        saved = json.loads(closeout.read_text(encoding="utf-8"))
        assert saved["source"] == source
        assert all(sha(APP / p) == checksum for p, checksum in saved["files"].items())
        result = dict(status="PASS", scope=saved["scope"], recorded_at=now,
                      closeout_sha256=sha(closeout), source_files=len(source), files=len(saved["files"]),
                      preserved_documents=len(baseline["preserved_documents"]),
                      current_receipt_validated=True, new_tests_executed=False)
        exclusive(evidence / ("astra_d01_closeout_validation_" + args.stage + ".json"), result)
        print(json.dumps(result))
        return
    assert not closeout.exists()
    review_path = APP / "docs/reports/astra_d01_independent_review_20261027_01.md"
    assert review_path.is_file()
    reviewed = json.loads((evidence / "astra_d01_review_numeric_literals_after_20261027_01.json").read_text(encoding="utf-8"))
    assert reviewed["status"] == "PASS" and reviewed["case_count"] == reviewed["expected_behavior_count"] == 6
    assert reviewed["source_sha256_before"] == reviewed["source_sha256_after"]
    assert all(source[p] == checksum for p, checksum in reviewed["source_sha256_after"].items())
    assert all(case["expected_behavior"] for case in reviewed["cases"])
    focused_path = evidence / "astra_d01_final_focused_20261027_01.json"
    focused = json.loads(focused_path.read_text(encoding="utf-8"))
    assert focused["status"] == "PASS" and focused["source_before"] == focused["source_after"] == source
    assert sha(APP / focused["log"]) == focused["log_sha256"]
    tests = proof["python"]["executed"]
    node = next(c["executed"] for c in proof["checks"] if isinstance(c["command"], list) and c["command"][0] == "node" and "executed" in c)
    compiled = next(c["compiled_files"] for c in proof["checks"] if "compiled_files" in c)
    new_tests = sum(test.startswith(("test_option_observations.", "test_benchmark_observations.")) for test in proof["python"]["executed_ids"])
    assert new_tests == focused["executed"]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
    report_path = APP / ("docs/reports/astra_d01_completion_" + args.stage + ".md")
    next_action = ("E01.2b: retain versioned production UI assets and extend the existing CDP harness "
                   "to render unchanged dashboard HTML with verified local assets for visual/mobile/accessibility checks, "
                   "using astra_browser_production_assets_plan_20261027_01.md; no provider calls.")
    report = f"""# Astra D01.2 offline observation acceptance — 2026-10-27

**VERIFIED_COMPLETE within pure offline observation mechanics. Master mission incomplete.**
Recorded UTC: {now}; project timezone Asia/Kolkata. HEAD `{head}`.

`option_observations.parse_option_capture` separates Upstox V2 chain, Upstox V3 Greeks
and Angel Greek schemas. It retains original UTF-8 text/hash, exact request, row paths,
field presence/raw values and master metadata. Rebuilding the master from its original
bytes binds unique dated contract and underlying declarations. Local master/receive/
availability/cutoff ordering is checked. These are declarations, not publisher authority.
V3 identity uses nested instrument_token, never its display-label dictionary key.
Missing, null and observed zero remain distinct. Endpoint IV/Greek/quantity scaling and
source clocks stay unavailable; no local receive time is substituted. Precision loss,
fractional counts, malformed/duplicate data, conflicting identity and future inputs reject.
Native masters without dated declarations remain unsupported by this interface.

`inspect_depth` checks positive ordered prices, integral quantities and uncrossed top of
book; only explicit synthetic underlying-unit fixtures compute size coverage. It never
claims executable depth or a fill. `compare_oi` requires exact matching identity/revision,
units, source references, availability and clocks. Unknown prev_oi semantics do not become
prior close. Declared synthetic prior-close arithmetic requires the explicitly named earlier
weekday and exact15:30 IST; a qualified trading calendar and source authority remain absent.

`benchmark_observations.align_benchmark_windows` checks distinct declared EQ/index roles,
completed contiguous five-minute bars, exact equal past-only windows, OHLC/volume, availability,
freshness and adjustment convention. It preserves canonical input hashes and reports only
descriptive first-close/last-close returns. It does not resolve a canonical dated benchmark
master, verify a holiday calendar, establish sector constituents, or create cash lineage.
No sorting, intersection trimming, forward fill or factor promotion occurs.

All outputs remain non-actionable and ineligible. The modules have no transport/storage
entry point and are not wired into adapters, scanner ranking, paper execution or the UI.
Existing option replay actually rejects both a capture and its relabelled replay-shaped
form. No Option Apex, cash ordering, strategy formula, provider selection or settings change.
Bounds include2MiB raw option bodies/master artifacts,100 legs,50 V3 request keys,30 depth
levels, bounded metadata traversal, and strict offset clocks. Benchmark windows additionally
require a single weekday session; the nominal375-row limit cannot admit out-of-session bars.

| Verification | Executed result / limitation |
|---|---|
| Final focused | {new_tests}/{new_tests} PASS, astra_d01_final_focused_20261027_01.json |
| Existing-contract integration | 108/108 PASS, astra_d01_integrated_20261027_02.json; predates final numeric/clock repairs, covered by canonical below |
| Canonical current source | {tests}/{tests} Python, {node}/{node} Node, {compiled} compilation checks; exit0; no failures/errors/skips/unraisables |
| Source freeze | Exact source_before equals source_after; receipt {args.receipt} |
| Review | Production review by rank_store, who authored the option tests and declares that limitation; root reviewed benchmark code/tests. No product-wide sign-off |
| Preservation | {len(baseline['preserved_documents'])} prior document/evidence files and confirmed external source/config hashes unchanged; previous handoff bytes archived |

Retained failures: first options run26/27 from an absent-field path test assertion; numeric
string underflow/exponent regression failed before repair; native JSON number regression
failed three subcases before the review fix; invalid offset regression failed for options
while benchmark already rejected it. The sandbox integration run88/108 had25 error events,
including temporary-file/SQLite access and cleanup errors; permitted rerun108/108 passed.
No timeout or trust rule was weakened. Review diagnostics retain native literal before/after.
All machine receipts, including failures, are preserved. The final canonical is the authority
for current-source totals; old C03/B01 receipts are historical boundaries.

Production files: option_observations.py, benchmark_observations.py; tests with corresponding
test_ names; release_management.py and test_bot.py registration. No new retained release ZIP.
No environment edit, operational DB access/migration, provider/auth request, notification,
real order, Git mutation, public launch or empirical performance claim. Owner-confirmed
broker/config/app-env/live-helper changes remain preserved; helper was never run or imported.

Next approved offline action: {next_action}
D01 live adapter/capability admission still requires dated unit/clock/source policies and
separately authorized genuine inputs. Broader paper triggers, authentic research/live
acceptance, full security/operations and commercial rights remain open.

Schema evidence: [Upstox chain](https://upstox.com/developer/api-documentation/get-pc-option-chain/),
[Upstox Greeks](https://upstox.com/developer/api-documentation/option-greek/),
[Angel moderator announcement](https://smartapi.angelone.in/smartapi/forum/topic/4254/announcing-option-greeks-api-for-smartapi-users),
public documentation reconfirmed2026-10-27. The Angel announcement is historical schema
evidence; its deleted-topic notice and inaccessible main documentation preclude claiming
current entitlement. See the preserved D01.1 inventory for exact source applicability.
"""
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(report)
    paths = [APP / "docs/project" / name for name in NAMES]
    content = paths[0].read_text(encoding="utf-8")
    content = re.sub(r"Last updated UTC: .*", "Last updated UTC: " + now, content, count=1)
    section1 = f"""**PARTIAL VERIFIED OFFLINE ENGINEERING; MASTER MISSION INCOMPLETE.**

D01.2 now supplies bounded, transport-free option/Greeks/depth/OI and benchmark
inspection with original source bindings, exact declared contract resolution, past-only
clocks and truthful unavailable capabilities. {new_tests} new tests and the current canonical
suite pass: **{tests}/{tests} Python, {node}/{node} Node, {compiled} compiled Python files**,
zero failures/errors/skips/unraisables. Source remained unchanged during the full run.
No native snapshot becomes an executable contract, replay dataset or ranking factor.
See [D01 completion](../reports/{report_path.name}) for exact scope and failures retained.

C03 cash rank history/API/UI and B01 ORB future-trigger mechanics remain covered by
the current full suite. Genuine empirical/OOS and live-consumer acceptance, broader
paper triggers, full visual/mobile/accessibility checks and customer readiness remain
incomplete. The earlier instrumented3s health SLO failure remains unresolved as a
production operating claim; a passing offline suite does not establish that SLO.

Owner-confirmed broker/config/app-env/live-helper edits are preserved. This slice
made no provider request, send, real order, saved-setting edit, operational DB or Git
mutation. The app env differs from the original mission baseline but matches the
owner-confirmed hash; the local helper was never run. Next: {next_action}
"""
    content = replace_section(content, 1, section1)
    content = content.replace("## 2. Audit manifest and Git state\n\n", "## 2. Audit manifest and Git state\n\n"
        f"D01.2 adds two production modules and two test modules, plus release/test registration.\n"
        f"Current source and all new evidence are bound in astra_d01_closeout_{args.stage}.json.\n"
        f"Its baseline archives all four prior handoffs; {len(baseline['preserved_documents'])} earlier documents/receipts remain byte-identical.\n"
        "Earlier source snapshots named below are historical, not current-source proof.\n\n")
    content = content.replace("Exact current hashes and\nhistorical archive checks are in astra_rank_preservation_20261027_01.json.",
                              "Historical C03 hashes and\narchive checks are in astra_rank_preservation_20261027_01.json.")
    content = content.replace("genuine empirical/OOS BLOCKED_EXTERNAL|", "D01.2 observation mechanics VERIFIED_OFFLINE; genuine empirical/OOS BLOCKED_EXTERNAL|")
    content = content.replace("## 4. Architecture and call flows\n\n", "## 4. Architecture and call flows\n\n"
        "D01 is an isolated library path: retained raw bytes + master declaration -> pure\n"
        "option inspection; explicit asset/index windows -> pure alignment. Outputs keep\n"
        "unavailable capabilities. There is no new edge into scanner, ranking or execution.\n\n")
    content = replace_section(content, 7, f"""D01.1 inventory and D01.2 pure inspection are complete within offline mechanics.
The [D01 implementation report](../reports/{report_path.name}) specifies each endpoint,
raw field presence/unit/time handling, exact declared identity, depth and OI limits,
benchmark alignment, tests, retained failures and unavailable capabilities.
Native provider fixtures are authored synthetic examples. Local master bytes and
declared dates are integrity evidence only. No source/rights/dated tick authority,
normalization policy, current entitlement or genuine live observation is established.

Upstox V2 prev_oi has no documented baseline date. V3 cp is previous close price,
not OI. Nested instrument_token identifies V3 rows. Angel Greeks lack a token/source
clock and require exact unique declared terms. IV/Greeks and REST quantities remain
unscaled; V3 feed contract-volume semantics are not borrowed by REST endpoints.
Benchmark identity remains declared, without a canonical dated master or constituents.
Synthetic OI prior-close arithmetic does not verify the previous trading session.

Existing historical option replay retains lot/tick, quote/depth and source admission
gates. Its integration test rejects snapshots even when relabelled as replay inputs.
No naked-short option, futures/roll, live F&O, premium fill or empirical acceptance.
Official schemas were reconfirmed2026-10-27 from
[chain](https://upstox.com/developer/api-documentation/get-pc-option-chain/),
[Greeks](https://upstox.com/developer/api-documentation/option-greek/) and the
[Angel announcement](https://smartapi.angelone.in/smartapi/forum/topic/4254/announcing-option-greeks-api-for-smartapi-users).
See D01.1 for exact source limitations; no broker request was made.
""")
    content = content.replace("D01.1 inventory VERIFIED; D01.2 NOT_STARTED", "D01.1/2 VERIFIED_OFFLINE; runtime admission absent")
    content = content.replace("B01 ORB and C03 source verified; D01, broader lifecycle, browser and full review remain.",
                              "B01 ORB, C03 and D01.2 source verified; runtime D01 admission, broader lifecycle, browser and full review remain.")
    content = content.replace("## 15. Verification ledger\n\n**Current-source canonical proof:**", "## 15. Verification ledger\n\n"
        f"**Current D01 source:** {args.receipt}: PASS {tests}/{tests} Python, {node}/{node} Node,\n"
        f"{compiled} compiled files, {new_tests} new tests; no failures/errors/skips/unraisables.\n"
        f"RUN: `.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage {proof['stage']}`.\n"
        f"Current source/log/handoff/preservation bindings: astra_d01_closeout_{args.stage}.json.\n"
        "Final focused56/56 and earlier integration108/108 passed; current canonical covers\n"
        "later numerical/clock repairs. Initial assertion, sandbox, underflow/precision and\n"
        "offset failures remain retained. The reviewer did not author production modules\n"
        "but authored option tests; this limitation is explicit in the review report.\n\n"
        "**Historical C03 canonical proof:**")
    content = content.replace("unchanged current source\nsnapshot matching the canonical receipt", "unchanged historical C03 source\nsnapshot matching its canonical receipt")
    content = content.replace("binds the current corrected handoff", "binds the historical C03 corrected handoff")
    content = replace_section(content, 17, f"""Current completed unit: D01.2 pure option/Greeks/depth/OI and benchmark inspection,
with current-source full offline proof and retained failure diagnostics. No command
is running at this checkpoint. Broader mission remains incomplete.
Safe first command: `Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md`.

Single next action: **{next_action}**
Reuse completed actual DOM/keyboard fixtures and preserve current outputs. Keep
genuine market/entitlement work separately gated. Do not repeat the baseline audit,
ORB implementation, C03 ranking or D01.2 parser. Evidence stages must be unique.

Resume: `CONTINUE FROM CHECKPOINT. Preserve verified B01/C03/D01.2; resume E01.2b
production-assets browser acceptance with no provider calls, real orders or sends.`
""")
    content = content.replace("Official URLs are cited beside claims in sections 7/8/12/13; accessed 2026-10-24.",
        "Official URLs are cited beside claims; D01 schemas were reconfirmed2026-10-27.\nEarlier broker/commercial/legal references retain their original2026-10-24 access dates; this slice did not revalidate those topics.")
    assert len(re.findall(r"^## \d+\. ", content, re.M)) == 18
    paths[0].write_text(content, encoding="utf-8")
    old = paths[1].read_text(encoding="utf-8")
    paths[1].write_text(f"""# TradePulse Astra checkpoint — verified D01.2 boundary

Updated UTC: {now}; timezone Asia/Kolkata; mission TRADEPULSE-ASTRA-OWNER-2026-10-24-V1.
Phase2/3 D01.2 VERIFIED_COMPLETE for pure offline observations; master mission INCOMPLETE.
Last completed: current-source canonical {args.receipt}, PASS {tests} Python/{node} Node/{compiled} compile,
followed by preservation/handoff binding. No background command or partial implementation.
Branch main; HEAD {head}; no Git writes. Source additions: option_observations.py,
benchmark_observations.py and their tests; release_management.py/test_bot.py registration.
Prior code, owner-confirmed source/env/helper and {len(baseline['preserved_documents'])} documents preserved.
No provider/env/operational DB/order/send/Git action; local helper not run/imported.

Final focused{new_tests}/{new_tests}; prior integration108/108. Initial raw-path assertion,
sandbox temp-access, string underflow/exponent, native precision and invalid offset failures
are retained in astra_d01_* evidence. Production-independent review declares option-test
authorship. Exact source/log/bindings: astra_d01_closeout_{args.stage}.json.
Missing source clocks, unit policies, publisher/date authority, benchmark master/calendar,
entitlement and genuine observations prevent runtime/research admission. Broader B01 and
production latency/visual/accessibility/security/commercial acceptance remain open.

Single exact next action: {next_action}
No additional credentials or owner approval is needed for that offline work.
Resume instruction: CONTINUE FROM CHECKPOINT.

## Historical checkpoint text (superseded for current-source proof)

""" + old, encoding="utf-8")
    with paths[2].open("a", encoding="utf-8") as stream:
        stream.write(f"\n\n{now} — D01.2 VERIFIED_COMPLETE in bounded offline scope. Two pure modules,\n"
            f"{new_tests} tests; {tests} Python/{node} Node/{compiled} compile full canonical PASS.\n"
            "Numerical underflow/JSON precision and malformed-offset findings reproduced,\n"
            "repaired and retained; no guessed units/clocks or snapshot replay promotion.\n"
            f"Preservation/current handoff: astra_d01_closeout_{args.stage}.json.\n"
            f"Next: {next_action}\n")
    ledger = paths[3].read_text(encoding="utf-8")
    ledger = re.sub(r"\|D01\.2\|[^\n]+", f"|D01.2|2/3|Pure observation validator and offline endpoint fixtures|VERIFIED_COMPLETE|{new_tests} new tests plus current canonical; no runtime/provider/research admission|", ledger)
    ledger = re.sub(r"\|F02\.1\|[^\n]+", f"|F02.1|6|Current-slice canonical and preserved history|VERIFIED_COMPLETE|{tests} Python/{node} Node/{compiled} compile; current D01 source/log/handoff bindings|", ledger)
    ledger = ledger.replace("Official docs checked; endpoint/entitlement-specific fixture interfaces pending", "D01.1/2 inventory and pure endpoint fixtures verified; qualified runtime admission and genuine data remain pending")
    ledger += "\n|E01.2b|5|Production-assets visual/mobile/accessibility acceptance|NOT_STARTED|Next: inspect existing external assets/browser harness, retain reproducible offline checks; no provider activation|\n"
    paths[3].write_text(ledger, encoding="utf-8")
    files = set(paths + [baseline_path, proof_path, report_path, review_path, Path(__file__),
                        APP / "docs/reports/astra_browser_production_assets_plan_20261027_01.md"])
    files.update(APP / p for p in proof["logs"])
    files.update(evidence.glob("astra_d01_*"))
    files = {p for p in files if p.is_file() and p != closeout}
    result = dict(status="PASS", scope="D01_PURE_OBSERVATION_OFFLINE_SLICE_NOT_MISSION_ACCEPTANCE",
        recorded_at=now, source=source, changed_source=sorted(changes), head=head,
        receipt=args.receipt, receipt_sha256=sha(proof_path), python=tests, node=node, compiled=compiled,
        new_tests=new_tests, preserved_documents=len(baseline["preserved_documents"]),
        saved_config_and_owner_changes_preserved=True, prior_handoff_archived=True,
        provider_requests=0, operational_db="NOT_OPENED_CONTENTS_UNATTESTED", release_zip="NOT_BUILT",
        files={p.relative_to(APP).as_posix(): sha(p) for p in sorted(files)})
    exclusive(closeout, result)
    print(json.dumps(dict(status="PASS", python=tests, node=node, compiled=compiled, files=len(files))))


if __name__ == "__main__":
    main()
