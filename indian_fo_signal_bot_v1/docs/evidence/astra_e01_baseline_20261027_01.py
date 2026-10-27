"""Retain prior verified handoff before the production-assets browser slice."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = APP / "docs/evidence/astra_e01_baseline_20261027_01.json"
    assert not target.exists()
    proof = validate_evidence(APP / "docs/evidence/master_astra_d01_20261027_01.json")
    closeout = json.loads((APP / "docs/evidence/astra_d01_closeout_20261027_01.json").read_text())
    assert closeout["source"] == source_snapshot(APP)
    assert all(sha(APP / name) == value for name, value in closeout["files"].items())
    names = ["TRADEPULSE_ASTRA_" + name + ".md" for name in
             ("MASTER_EXECUTION_REPORT", "CHECKPOINT", "PROGRESS", "TASK_LEDGER")]
    paths = [APP / "docs/project" / name for name in names]
    owner = json.loads((APP / "docs/evidence/astra_owner_changes_20261026_01.json").read_text())
    assert all(sha(Path(p)) == row["observed_hash"] for p, row in owner["saved_config"].items())
    assert all(sha(APP / p) == row["observed_hash"] for p, row in owner["external_source"].items())
    now = datetime.now(timezone.utc).isoformat()
    data = dict(schema="astra.e01.baseline.v1", recorded_at=now,
        head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        source=source_snapshot(APP), prior_proof="master_astra_d01_20261027_01.json",
        prior_proof_validated=True, new_tests_executed=False,
        preserved_documents={p.relative_to(APP).as_posix(): sha(p) for p in (APP / "docs").rglob("*")
            if p.is_file() and p not in paths and "__pycache__" not in p.parts},
        handoff={p.name: dict(sha256=sha(p), original_bytes_base64=base64.b64encode(p.read_bytes()).decode()) for p in paths},
        saved_config_hashes={p: sha(Path(p)) for p in owner["saved_config"]},
        external_source_hashes={p: sha(APP / p) for p in owner["external_source"]})
    with target.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
    old = paths[1].read_text(encoding="utf-8")
    paths[1].write_text(f"# E01.2b active checkpoint — {now}\n\n"
        "Phase5 production-assets browser/mobile/accessibility verification IN_PROGRESS.\n"
        "D01.2 proof1184 Python/38 Node/101 compile and closeout validated before edits; no new tests yet.\n"
        "Root owns asset acquisition, baseline, later public/index.html and test_cash_dashboard.js fixes.\n"
        "rank_ui owns only new astra_browser_assets_verify_20261027_01.py; rank_review read-only.\n"
        "Next: retain exact public CDN/font assets and licenses, run new isolated browser harness\n"
        "against unchanged production HTML, reproduce failures before minimal repairs.\n"
        "No provider/env/operational DB/order/send/Git actions. All prior handoff bytes preserved\n"
        "in astra_e01_baseline_20261027_01.json. Public dependency downloads are separately recorded.\n\n"
        "## Historical verified checkpoint\n\n" + old, encoding="utf-8")
    paths[3].write_text(paths[3].read_text(encoding="utf-8").replace(
        "|E01.2b|5|Production-assets visual/mobile/accessibility acceptance|NOT_STARTED|",
        "|E01.2b|5|Production-assets visual/mobile/accessibility acceptance|IN_PROGRESS|"), encoding="utf-8")
    with paths[2].open("a", encoding="utf-8") as stream:
        stream.write(f"\n\n{now} — E01.2b started from verified D01.2. Source/35 closeout bindings\n"
            "and owner changes validated, prior handoff archived. No repeated baseline audit.\n"
            "New actual-assets harness delegated; before/fix/after visual and semantic checks pending.\n")
    print(json.dumps(dict(status="PASS", prior_python=proof["python"]["executed"], source_files=len(data["source"]),
                         preserved_documents=len(data["preserved_documents"]))))


if __name__ == "__main__":
    main()
