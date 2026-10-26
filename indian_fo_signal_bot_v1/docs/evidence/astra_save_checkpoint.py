"""Save and independently recheck the explicitly partial Astra handoff."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence, source_snapshot


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--preservation", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9_]+", args.stage)
    assert all(Path(name).name == name for name in (args.receipt, args.preservation))
    evidence = APP / "docs/evidence"
    closeout = evidence / ("astra_checkpoint_closeout_" + args.stage + ".json")
    proof = validate_evidence(evidence / args.receipt)
    preservation = json.loads((evidence / args.preservation).read_text())
    assert preservation["status"] == "PASS" and preservation["source"] == source_snapshot(APP)
    assert preservation["current_receipt_sha256"] == sha(evidence / args.receipt)
    current_time = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
    if args.validate:
        retained = json.loads(closeout.read_text())
        assert retained["source"] == source_snapshot(APP)
        assert all(sha(APP / name) == value for name, value in retained["files"].items())
        write_new(evidence / ("astra_checkpoint_validation_" + args.stage + ".json"),
            dict(status="PASS", checked_at_ist=current_time, closeout_sha256=sha(closeout),
                bound_files=len(retained["files"]), scope="PARTIAL_HANDOFF_INTEGRITY_NOT_MISSION_COMPLETION"))
        print(json.dumps(dict(status="PASS", scope="PARTIAL_HANDOFF_INTEGRITY", files=len(retained["files"]))))
        return
    assert not closeout.exists(), "Use a new stage; preserve prior closeout"
    python_count = proof["python"]["executed"]
    node_count = next(c["executed"] for c in proof["checks"] if isinstance(c["command"], list)
                      and c["command"][0] == "node" and "executed" in c)
    compiled = next(c["compiled_files"] for c in proof["checks"] if "compiled_files" in c)
    project = APP / "docs/project"
    report = project / "TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md"
    body = report.read_text(encoding="utf-8")
    assert [int(n) for n in re.findall(r"^## (\d+)\.", body, flags=re.M)] == list(range(1, 19))
    assert args.receipt in body and "MASTER MISSION INCOMPLETE" in body
    checkpoint = project / "TRADEPULSE_ASTRA_CHECKPOINT.md"
    with (evidence / ("astra_checkpoint_previous_" + args.stage + ".md")).open("xb") as stream:
        stream.write(checkpoint.read_bytes())
    checkpoint.write_text(f"""# TradePulse Astra execution checkpoint

Updated: {current_time} (Asia/Kolkata).
Mission: TRADEPULSE-ASTRA-OWNER-2026-10-24-V1, attachment
5f1549b7-3993-4c83-bda2-00ee685779af/Pasted text.txt.
Status: PARTIAL VERIFIED OFFLINE SLICE; MASTER MISSION INCOMPLETE.

Current phase/workstream: Phase6, B01 paper lifecycle. Current task/subtask: B01.2.
Last completed operation: current-source canonical verification PASS, then
historical archive/config/document preservation and18-section master report.
{python_count}/{python_count} Python tests, {node_count}/{node_count} Node tests,
{compiled} compiled root Python files; zero failures/errors/skips/unraisables.
Receipt: ../evidence/{args.receipt}. Exit0; exact IDs/logs/source hashes retained.
Current source contains {len(proof['source_after'])} hashed source/config-example/assets.

The interrupted operation is B01.2: strategy-specific future paper triggers.
Only an unintegrated ORB draft was created; resumed worker corrected one trace
field (observed -> measurements), then hit its usage limit. Both versions are
preserved under docs/drafts/. Latest: astra_paper_triggers_20261025_01.py.
forward_paper.py and paper_portfolio.py remain unchanged. No trigger policy is
registered. Compilation/tests of other code do not qualify this draft.

Single exact next action: inspect that draft's build_contract/source_observation
against the actual committed candle-lineage and evaluator trace schema, then
implement B01.2's atomic strategy-specific consumer/direct-enter guard with
negative and real scanner-path fixture tests. Preserve original detection rules.
No universal next-close or arbitrary three-bar expiry. Unsupported strategies
remain unavailable until their own explicit future policy exists. Preserve old
financial history/recovery while rejecting unsafe automatic legacy entry.

Git branch main, HEAD {preservation['head']}. No staging/commit/reset performed.
Modified existing: server.py, historical_study.py, scanner_engine.py,
candle_lineage.py, public/index.html, test_cash_dashboard.js, test_bot.py,
release_management.py. New implemented modules strategy_evidence.py and
opportunity_ranking.py; new test_astra_http_safety.py/test_astra_research.py/
test_astra_ranking.py. Evidence helpers,18-section master report and three
persistent checkpoint files are retained. Consult preservation.changed_source
for exact source hashes; HEAD alone does not identify these uncommitted changes.
Unrelated TRADEPULSE_AI_PLUS_PROJECT_INTELLIGENCE_REPORT.md remains untouched.

Completed and verified scope: GET/HEAD scan405 before initialization and POST
support; complete research fold declarations; descriptive strategy metadata;
safe missing quantity/price/quality/invalidation and stale P&L display; read-only
bounded paper journal; deterministic standalone rank-change prototype and exact
freshness expiry. Prototype is not connected to scanner/storage/API; next C03.2
requires authenticated retained inputs, atomic persistence and read-only UI.

Retained failures: first canonical20261024_01 failed1056/1059 (old GET contract
assumptions/draft placement); focused sandbox temporary-directory failures;
HTTP request-body fixture reset; rank expiry before-fix failure; UI before-fix
failure. These are never passing receipts. Corrected focused26/26 and Node32/32
preceded final canonical. Earlier combined focused54/54 is historical stage proof.

P0 B01 remains OPEN: synthetic long threshold100/high99 filled98 under legacy
automatic close policy. No new-policy paper cohort, genuine live acceptance,
empirical profitability or customer release. Both paper workers stopped; no
active agent/background work is assumed. No commands remain running at handoff.

Independent read-only HTTP/research/metadata/rank review found expiry mismatch,
which root reproduced/fixed/tested. UI review was author self-review. Final paper
review is outstanding. No claim of full independent product/browser acceptance.

Preservation: {args.preservation};522 prior documents, both.env files and original
BRD unchanged; both older release archives match their packaged historical source.
Both proofs also hash empty public/rea, omitted by both manifests; exact exception
is recorded and verified. No other omitted source file is allowed by that check.
Operational DB/WAL/SHM never opened; their contents/concurrent activity unattested.
No provider calls, real orders, notifications, saved settings or scheduler changes.
No new release ZIP. External blockers: qualified historical rights/data, separately
authorized real-market observation, commercial/legal/customer readiness. B01/C03
are feasible offline internal work; no extra owner approval is needed for them.

Safe first command: Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md
Then inspect relevant diff and latest receipt; do not repeat the initial audit.
Resume instruction: CONTINUE FROM CHECKPOINT. Resume B01.2, preserve all verified
work/evidence, finish the strategy-specific paper transaction, then C03.2.
""", encoding="utf-8")
    ledger = """# TradePulse Astra task ledger

Mission TRADEPULSE-ASTRA-OWNER-2026-10-24-V1. States describe scoped evidence only.

| ID | Phase | Task | State | Acceptance / remaining dependency |
|---|---|---|---|---|
|A01|1/6|Baseline recovery|VERIFIED_COMPLETE|Original Phase6 source proof validated; baseline retained|
|A02|1/6|Persistent checkpoint system|VERIFIED_COMPLETE|Current checkpoint/progress/ledger; update at each unit|
|A03|6|Historical release/receipt and preservation checks|VERIFIED_COMPLETE|Old archives match original source;522 old documents/env/BRD preserved|
|B01|6|Strategy-specific automatic paper lifecycle|IN_PROGRESS|P0 OPEN; no new trigger acceptance|
|B01.1|6|Premature fill reproduction|VERIFIED_COMPLETE|entry100/high99/fill98 synthetic reproduction retained|
|B01.2|6|Validate/integrate ORB future contract and atomic guard|IN_PROGRESS|Latest docs/drafts/astra_paper_triggers_20261025_01.py; unintegrated/untested|
|B01.3|6|Legacy automatic migration and preserved recovery|NOT_STARTED|No new entries without valid strategy contract; committed effects preserved|
|B01.4|6|Negative, concurrency, rollback, scanner/API lifecycle acceptance|NOT_STARTED|B01.2/B01.3 then actual retained fixture lineage|
|B02|5/6|GET/HEAD scan mutation prohibition|VERIFIED_COMPLETE|Before fail; focused + final canonical pass; POST remains explicit|
|C01|2|Exact declared study session coverage|VERIFIED_COMPLETE|Before failures;23 focused and canonical pass|
|C02|2/4/5|Descriptive strategy evidence metadata|VERIFIED_COMPLETE|Scanner/history/UI integration; no promotion authority|
|C03|4|Dynamic opportunity rank history|IN_PROGRESS|Pure prototype verified; production integration pending|
|C03.1|4|Deterministic prototype and expiry|VERIFIED_COMPLETE|8 tests including rank reversal, ties, source revisions and exact expiry|
|C03.2|4/5|Retained source validation/persistence/API/UI|NOT_STARTED|Trusted store boundary, atomic rollback and current/archive tests|
|D01|2/3|Broker/F&O capability matrix and normalized contracts|IN_PROGRESS|Official docs checked; endpoint/entitlement-specific fixture interfaces pending|
|E01|5/6|Truthful displays and bounded paper journal|VERIFIED_COMPLETE|32 Node tests; narrow renderer/read safety scope only|
|E01.2|5|Browser/mobile/accessibility/pagination acceptance|NOT_STARTED|No new actual-browser evidence|
|E02|1/6|Independent adversarial review|IN_PROGRESS|Scoped read-only review completed; paper and full product remain pending|
|E02.1|4|Rank expiry review finding|VERIFIED_COMPLETE|Reproduced fail then exact-boundary pass, canonical bound|
|F01|6|Commercialization/data-rights/regulatory blueprint|IN_PROGRESS|Dated official questions and hypotheses documented; actual launch/counsel/vendor decisions pending|
|F02|6|Verification and final release|IN_PROGRESS|Current slice verified; full mission release pending|
|F02.1|6|Current-slice canonical and preserved history|VERIFIED_COMPLETE|Current proof and independent byte checks, zero suite failures|
|F02.2|6|Whole mission final package|NOT_STARTED|B01/C03/remaining engineering and review; no new ZIP|
|F03|All|18-section portable master report|VERIFIED_COMPLETE|Partial status explicit; must update after future source changes|
|X01|2|Empirical/OOS acceptance|BLOCKED|Qualified original history, rights/trust/date/universe and frozen study|
|X02|3|Genuine scanner-consumed completed live candles|BLOCKED|New exact authorization and actual accepted observation evidence|
|X03|6|Customer/public launch|BLOCKED|Counsel/data rights/security/operating readiness and separate approval|
"""
    (project / "TRADEPULSE_ASTRA_TASK_LEDGER.md").write_text(ledger, encoding="utf-8")
    with (project / "TRADEPULSE_ASTRA_PROGRESS.md").open("a", encoding="utf-8") as stream:
        stream.write(f"""
## {current_time} — verified partial handoff

- UI self-review found absent quality coerced to0 and missing invalidation borrowed
  from stop. Retained32-test before FAIL, after32/32 PASS; valid zero preserved.
- B01 worker stopped after one trace-field correction; both draft versions moved
  intact to docs/drafts. No paper production behavior changed or accepted.
- Canonical {args.receipt}: {python_count}/{python_count} Python,
  {node_count}/{node_count} Node, {compiled} root Python files compiled; exit0,
  zero failures/errors/skips/unraisables. Source stayed unchanged during execution.
- Preservation {args.preservation}:522 old documents, both env files, original
  BRD and historical packaged-source bindings verified. Initial helper stopped on
  public/rea; both old proofs hash that empty extensionless artifact, outside both
  manifests. Exact omission/empty hash documented; no arbitrary exclusions.
  No operational DB access.
- Master18-section report now reflects exact final code/evidence and remaining
  B01/C03/D01 scope. Source-location and pure synthetic rank demo artifacts added.
- Current task B01.2; no workers or commands assumed active after handoff. No new
  provider, account, Telegram, scheduler, Git or release activation.
""")
    names = [report, checkpoint, project / "TRADEPULSE_ASTRA_PROGRESS.md", project / "TRADEPULSE_ASTRA_TASK_LEDGER.md",
        evidence / args.receipt, evidence / args.preservation,
        evidence / "astra_code_locations_20261025_01.json", evidence / "astra_rank_demo_20261025_01.json",
        APP / "docs/drafts/astra_newpaper_triggers.py", APP / "docs/drafts/astra_paper_triggers_20261025_01.py"]
    write_new(closeout, dict(status="PARTIAL_VERIFIED_CHECKPOINT", mission_complete=False,
        recorded_at_ist=current_time, source=source_snapshot(APP),
        files={p.relative_to(APP).as_posix(): sha(p) for p in names},
        current_receipt=args.receipt, python=python_count, node=node_count, compiled=compiled,
        next_task="B01.2", paper_trigger="REPRODUCED_NOT_REPAIRED", dynamic_ranking="PROTOTYPE_NOT_INTEGRATED",
        live_acceptance=False, empirical_acceptance=False, customer_release=False))
    print(json.dumps(dict(status="PARTIAL_CHECKPOINT_SAVED", next_task="B01.2", updated_at_ist=current_time)))


if __name__ == "__main__":
    main()
