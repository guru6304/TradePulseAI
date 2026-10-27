"""Archive the verified handoff before the D01 offline implementation slice."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    names = ["TRADEPULSE_ASTRA_" + name + ".md" for name in
             ("MASTER_EXECUTION_REPORT", "CHECKPOINT", "PROGRESS", "TASK_LEDGER")]
    mutable = [APP / "docs/project" / name for name in names]
    target = APP / "docs/evidence/astra_d01_baseline_20261027_01.json"
    assert not target.exists()
    preserved = {p.relative_to(APP).as_posix(): sha(p) for p in (APP / "docs").rglob("*")
                 if p.is_file() and p not in mutable and "__pycache__" not in p.parts}
    owner_path = APP / "docs/evidence/astra_owner_changes_20261026_01.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert all(sha(Path(p)) == row["observed_hash"] for p, row in owner["saved_config"].items())
    assert all(sha(APP / p) == row["observed_hash"] for p, row in owner["external_source"].items())
    data = dict(schema="astra.d01.baseline.v1", recorded_at=datetime.now(timezone.utc).isoformat(),
                head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
                source=source_snapshot(APP), preserved_documents=preserved,
                saved_config_hashes={p: sha(Path(p)) for p in owner["saved_config"]},
                external_source_hashes={p: sha(APP / p) for p in owner["external_source"]},
                handoff={p.name: dict(sha256=sha(p), original_bytes_base64=base64.b64encode(p.read_bytes()).decode("ascii")) for p in mutable},
                prior_closeout="docs/evidence/astra_rank_closeout_20261027_02.json",
                scope="D01_OFFLINE_OBSERVATIONS_NO_PROVIDER_OR_RUNTIME_ACTIVATION")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
    checkpoint = mutable[1]
    old = checkpoint.read_text(encoding="utf-8")
    checkpoint.write_text("# D01.2 active checkpoint — 2026-10-27\n\n"
        "Mission TRADEPULSE-ASTRA-OWNER-2026-10-24-V1; Phase2/3 D01.2 IN_PROGRESS.\n"
        "C03 final proof remains a retained historical boundary:1128 Python/38 Node/97 compile.\n"
        "No new D01 tests have run. Root owns option_observations.py and registration;\n"
        "rank_store owns test_option_observations.py; rank_ui owns benchmark_observations.py\n"
        "and test_benchmark_observations.py. rank_review will review independently.\n"
        "Saved owner changes preserved; no provider/env/operational DB/Git actions.\n"
        "Next: finish bounded pure parser and benchmark alignment, then focused integration.\n"
        "Prior handoff bytes and source preserved in astra_d01_baseline_20261027_01.json.\n\n"
        "## Historical checkpoint (superseded for current-source proof after new edits)\n\n" + old, encoding="utf-8")
    ledger = mutable[3]
    ledger.write_text(ledger.read_text(encoding="utf-8").replace(
        "|D01.2|2/3|Pure observation validator and offline endpoint fixtures|NOT_STARTED|",
        "|D01.2|2/3|Pure observation validator and offline endpoint fixtures|IN_PROGRESS|"), encoding="utf-8")
    with mutable[2].open("a", encoding="utf-8") as stream:
        stream.write("\n\n2026-10-27 D01.2 started from the verified C03 checkpoint. Prior handoff bytes,\n"
                     "source and preserved document/config hashes archived in astra_d01_baseline_20261027_01.json.\n"
                     "Pure transport-free endpoint and benchmark fixtures delegated; no provider activation.\n")
    print(json.dumps(dict(status="BASELINE_RETAINED", documents=len(preserved), source_files=len(data["source"]))))


if __name__ == "__main__":
    main()
