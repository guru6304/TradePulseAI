"""Update the original Astra handoffs after verified E02 work and safe cleanup."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
E = APP / "docs/evidence"
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence


def replace_section(text, number, body):
    start = re.search(rf"^## {number}\. .*\n", text, re.M)
    end = re.search(rf"^## {number + 1}\. ", text, re.M)
    assert start and end
    return text[:start.end()] + "\n" + body.strip() + "\n\n" + text[end.start():]


def row(text, key, fields):
    value = "|" + "|".join([key] + fields) + "|"
    pattern = rf"^\|{re.escape(key)}\|.*$"
    return re.sub(pattern, lambda match: value, text, flags=re.M) if re.search(pattern, text, re.M) else text.rstrip() + "\n" + value + "\n"


def main():
    proof_name = "master_astra_backend_cleanup_20261029_01.json"
    proof = validate_evidence(E / proof_name)
    cleanup = json.loads((E / "astra_cleanup_apply_20261029_01.json").read_text(encoding="utf-8-sig"))
    assert cleanup["status"] == "PASS" and not cleanup["errors"]
    python = proof["python"]["executed"]
    node = next(c["executed"] for c in proof["checks"] if "executed" in c)
    compiled = next(c["compiled_files"] for c in proof["checks"] if "compiled_files" in c)
    counts = f"{python}/{python} Python, {node}/{node} Node, {compiled} compiled Python files"
    baseline = json.loads((E / "astra_journal_cleanup_baseline_20261029_01.json").read_text(encoding="utf-8"))
    names = list(baseline["handoff"])
    paths = {name: APP / "docs/project" / name for name in names}
    old = {name: path.read_bytes() for name, path in paths.items()}
    original = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    now = datetime.now(timezone.utc).isoformat()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
    next_action = ("B01.5a: implement and test an isolated, versioned experimental VWAP cash future-reclaim "
                   "contract using the existing retained-observation rules, without automatic activation, "
                   "provider calls or a universal next-bar-close/expiry policy. Use astra_b01_pending_continuation_20261029_01.md.")
    master_name = "TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md"
    master = original[master_name]
    master = ("# TradePulse Astra master execution report\n\n"
        "Original mission TRADEPULSE-ASTRA-OWNER-2026-10-24-V1 continues; master mission INCOMPLETE.\n"
        f"Updated UTC: {now}; client date2026-10-29, Asia/Kolkata. HEAD `{head}`.\n"
        "Owner instruction: continue the original master tasks; UI work is deferred to the planned revamp.\n"
        "The owner's dev/Antigravity work remains untouched; no Git writes.\n\n" + master[master.index("## 1. Executive verdict"):])
    master = replace_section(master, 1, f"""
Original-master E02 review/recovery work now rejects conflicting or missing embedded
account/entity identities in read-only position and recovery-decision ledger pages.
Corruption returns generic503 RECONCILIATION_REQUIRED rather than HTTP200 retained
payloads. Valid events keep their distinct schema; cursor membership and ordinary
pages remain unchanged. Actual GET/HEAD tests cover both API aliases, no payload
echo, another account's isolation and unchanged temporary-database contents.

Before: two tests/24 failing assertions. After:22/22 focused recovery tests and
current canonical **{counts}**, zero failures/errors/skips/unraisables, unchanged
source during execution. Current proof: `{proof_name}`. See
[completion](../reports/astra_backend_and_cleanup_completion_20261029_01.md) and
[independent review](../reports/astra_backend_cleanup_independent_review_20261029_01.md).

Cleanup removed {cleanup['removed_files']} verified untracked bytecode files,
{cleanup['removed_bytes']:,}bytes, and two empty cache directories. All274 original
images are required hash-bound evidence and remain intact. The unknown access-denied
temporary folder remains uninspected and preserved. Source/test architecture,
credentials, private inputs, dependencies and operational databases were preserved.

UI work is DEFERRED_OWNER_UI_REVAMP. Two small class edits made before that
instruction remain uncommitted; inline JavaScript is unchanged. The already-running
Chrome journal checks finished52/52 before shutdown; no Edge or full journal/UI
acceptance is claimed. Subsequent work followed the original master review tasks.
Broader paper lifecycle, qualified runtime observations, genuine historical/OOS/live
acceptance and customer release remain incomplete. Next: {next_action}
""")
    start = master.index("\n\n", master.index("## 2. Audit manifest"))
    end = master.index("Owner-confirmed parallel changes", start)
    master = master[:start] + "\n\n" + (
        "This continuation changes storage.py and test_phase5c_recovery.py for E02. Two\n"
        "earlier class-only edits in public/index.html predate the owner's UI deferral.\n"
        "No new application module, database schema or provider route was added. Baseline\n"
        "astra_journal_cleanup_baseline_20261029_01.json preserves1121prior documents,\n"
        "four original handoffs, saved configuration, owner-confirmed source and20cached\n"
        "public asset/license bodies. Latest prior handoff bytes are archived again.\n"
        "The new source-bound proof/closeout supersedes prior receipts for current source.\n\n") + master[end:]
    master = re.sub(r"Current externally advanced HEAD `[^`]+`", f"Current externally advanced HEAD `{head}`", master)
    master = master.replace("browser paper journal, full accessibility/contrast and new delivery acceptance remain open",
        "UI journal/accessibility work is deferred to the owner's revamp; no new delivery acceptance")
    pos = master.index("Negative controls: offline runner")
    master = master[:pos].rstrip() + ("\n|E02.2 medium ledger API identity, corrected|Two writer-backed tests reproduced24 failing assertions; positions/recovery payload identities now match account/entity wrappers or return generic503. Focused22 and current canonical pass; no financial writes or payload echo.|\n\n") + master[pos:]
    ui = master.index("\n\n", master.index("## 12. UX and product differentiation"))
    master = master[:ui] + "\n\n**DEFERRED_OWNER_UI_REVAMP.** The owner will rework the UI. Continue the original master functionality tasks; the retained UI results below describe earlier bounded work, not a new acceptance.\n" + master[ui:]
    master = re.sub(r"^\|E01 /5,6 /UI\|.*$", "|E01 /5,6 /UI|DEFERRED_OWNER_UI_REVAMP|Preserve prior verified scope; further UI work belongs to the planned revamp.|", master, flags=re.M)
    marker = master.index("\n\n", master.index("## 15. Verification ledger"))
    master = master[:marker] + "\n\n" + f"""**Current original-master source:** `{proof_name}`: PASS {counts};
zero failures/errors/skips/unraisables and exact source-before/source-after equality.
RUN: `.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage astra_backend_cleanup_20261029_01`.
Focused E02 after22/22; before2tests/24failures, plus retained initial sandbox failure.
Cleanup dryrun/apply passed:105untracked files, {cleanup['removed_bytes']:,}bytes,
two empty directories, no recursive deletion. All1121prior documents and274images
are preserved. Final independent review and separate closeout validation are retained.
No provider/order/send/operationalDB/Git mutation. E01UI work is owner-deferred.

**Historical verification ledger below:** the E01 receipts identify earlier source,
before the two class edits and ledger API correction. They were not rerun as UI work.

""" + master[marker:]
    # Retained historical block must not present its old source as current.
    master = master.replace("**Current source:** `master_astra_e01_20261029_02.json`", "**Historical E01 source:** `master_astra_e01_20261029_02.json`")
    owner = master.index("\n\n", master.index("## 16. Outstanding owner decisions"))
    master = master[:owner] + "\n\nThe owner has settled the immediate direction: continue the original Astra master mission and defer UI work to its planned revamp. No new provider authorization is inferred.\n" + master[owner:]
    master = replace_section(master, 17, f"""
Completed original-master unit: E02.2 ledger read identity validation and requested
safe cleanup. Current proof `{proof_name}`: {counts}; focused22/22.
Cleanup105files/{cleanup['removed_bytes']:,}bytes and two empty caches removed;
required evidence/data/config/source preserved. UI remains owner-deferred.
No command is running. Master mission remains incomplete.

Safe first command: `Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md`.
Exact next original-master action: **{next_action}**
Do not restart the project audit, repeat completed units, activate a provider or
switch to UI. Preserve source-bound evidence and the owner's other branch.
Resume instruction: `CONTINUE FROM CHECKPOINT`.
""")
    assert len(re.findall(r"^## \d+\. ", master, re.M)) == 18
    checkpoint = f"""# Original Astra master checkpoint - E02.2 and cleanup verified, 2026-10-29

Updated UTC: {now}; clienttimezone Asia/Kolkata. HEAD{head}; no Git writes.
Current master task follows ORIGINAL TRADEPULSE-ASTRA-OWNER-2026-10-24-V1.
UI is DEFERRED_OWNER_UI_REVAMP. Do not resume UI work or browser acceptance.
Last completed: E02.2 position/recovery ledger payload identity and safe cleanup.
Proof {proof_name}: PASS {counts}; focused22/22; zero failures/errors/skips/unraisables.
Before2tests/24failures; generic503/noecho/GETHEAD/read-only/isolation/restart verified.
Removed105untracked bytecode files/{cleanup['removed_bytes']:,}bytes plus two emptydirs.
Preserved1121prior documents,274original images, savedsettings,dependencies,private
assets,operationalDB and ownerdev/Antigravity work. Access-denied unknowntemp retained.
Changedthisunit: storage.py,test_phase5c_recovery.py;2pre-stop CSSclass edits retained
in public/index.html, inlineJS unchanged. No provider/order/send/DB/Git action.
No command is running. Master mission remains incomplete; broaderB01/D01/empirical/
live/commercial acceptance is open. Final source/preservation checks in closeout.

Exact next action: {next_action}
Resume instruction: CONTINUE FROM CHECKPOINT.

## Historical checkpoints

""" + original["TRADEPULSE_ASTRA_CHECKPOINT.md"]
    progress = original["TRADEPULSE_ASTRA_PROGRESS.md"] + f"\n\n## 2026-10-29 - Original master E02.2 and cleanup\n\nUpdated UTC{now}. Owner clarified original master continues, UI revamp deferred. Ledger payload identity fix: before2tests/24failures; after22/22, canonical {counts}. Cleanup105files/{cleanup['removed_bytes']:,}bytes/twoemptydirs;1121docs/274images/config/data preserved. No provider/Git/financial mutation; dev work untouched. Two earlier CSSclass edits remain recorded with deferredUI scope. Next: {next_action}\n"
    ledger = original["TRADEPULSE_ASTRA_TASK_LEDGER.md"]
    ledger = row(ledger, "E01.2", ["5", "Browser/mobile/accessibility acceptance", "DEFERRED_OWNER_UI_REVAMP", "Owner will rework UI; preserve prior scoped evidence, no further UI work"])
    ledger = row(ledger, "E01.2d", ["5/6", "Paper-journal browser acceptance", "DEFERRED_OWNER_UI_REVAMP", "Pre-stop Chrome52 retained; Edge/full acceptance not established; UI revamp deferred"])
    ledger = row(ledger, "E02.2", ["1/6", "Ledger read payload account/entity validation", "VERIFIED_COMPLETE", "Positions/recovery only; before24failures, focused22, current canonical, generic503/noecho/read-only"])
    ledger = row(ledger, "H01", ["1/6", "Safe project cleanup and layout guide", "VERIFIED_COMPLETE", f"105untracked cache files/{cleanup['removed_bytes']}bytes +2emptydirs removed;274bound images kept;unknown temp retained"])
    ledger = row(ledger, "F02.1", ["6", "Current-source canonical and preservation", "VERIFIED_COMPLETE", f"{python}Python/{node}Node/{compiled}compile; original-master E02.2 closeout"])
    ledger = row(ledger, "B01.5a", ["6", "Isolated experimental VWAP future-reclaim contract", "NOT_STARTED", "Exact next original B01 pending lifecycle task; no automatic activation; continuation report prepared"])
    archive = E / "astra_backend_cleanup_handoff_previous_20261029_01.json"
    with archive.open("x", encoding="utf-8") as stream:
        json.dump(dict(recorded_at=now, handoff={name: dict(sha256=hashlib.sha256(data).hexdigest(),
            original_bytes_base64=base64.b64encode(data).decode()) for name, data in old.items()}), stream, indent=2, sort_keys=True)
    texts = {master_name: master, "TRADEPULSE_ASTRA_CHECKPOINT.md": checkpoint,
             "TRADEPULSE_ASTRA_PROGRESS.md": progress, "TRADEPULSE_ASTRA_TASK_LEDGER.md": ledger}
    for name, text in texts.items():
        paths[name].write_text(text, encoding="utf-8")
    print(json.dumps(dict(status="PASS", python=python, node=node, compiled=compiled,
        removed_files=cleanup["removed_files"], checkpoint_updated_at=now,
        ui_status="DEFERRED_OWNER_UI_REVAMP", next_task="B01.5a")))


if __name__ == "__main__":
    main()
