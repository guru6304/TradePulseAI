"""Archive the accepted handoff and bind prior evidence before journal/cleanup work."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
EVIDENCE = APP / "docs/evidence"
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = EVIDENCE / "astra_journal_cleanup_baseline_20261029_01.json"
    assert not target.exists(), "unique baseline required"
    proof_path = EVIDENCE / "master_astra_e01_20261029_02.json"
    proof = validate_evidence(proof_path)
    previous = json.loads((EVIDENCE / "astra_e01_baseline_20261027_01.json").read_text(encoding="utf-8"))
    closeout_path = EVIDENCE / "astra_e01_closeout_20261029_02.json"
    closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    assert closeout["source"] == source_snapshot(APP)
    names = ["TRADEPULSE_ASTRA_" + name + ".md" for name in
             ("MASTER_EXECUTION_REPORT", "CHECKPOINT", "PROGRESS", "TASK_LEDGER")]
    paths = [APP / "docs/project" / name for name in names]
    protected = dict(previous["preserved_documents"])
    protected.update(closeout["files"])
    protected[closeout_path.relative_to(APP).as_posix()] = sha(closeout_path)
    validation = EVIDENCE / "astra_e01_closeout_validation_20261029_02.json"
    protected[validation.relative_to(APP).as_posix()] = sha(validation)
    for path in paths:
        protected.pop(path.relative_to(APP).as_posix(), None)
    assert all(sha(APP / name) == checksum for name, checksum in protected.items())
    assert all(sha(Path(name)) == checksum for name, checksum in previous["saved_config_hashes"].items())
    assert all(sha(APP / name) == checksum for name, checksum in previous["external_source_hashes"].items())
    assert all(sha(APP / name) == checksum for name, checksum in closeout["cache_files"].items())
    result = dict(schema="tradepulse.journal-cleanup-baseline.v1", recorded_at=datetime.now(timezone.utc).isoformat(),
        source=source_snapshot(APP), protected_documents=protected,
        handoff={path.name: dict(sha256=sha(path), original_bytes_base64=base64.b64encode(path.read_bytes()).decode())
                 for path in paths},
        saved_config_hashes=previous["saved_config_hashes"], external_source_hashes=previous["external_source_hashes"],
        cached_public_assets=closeout["cache_files"], prior_proof=proof_path.name, prior_proof_sha256=sha(proof_path),
        prior_proof_validated=True, prior_python=proof["python"]["executed"],
        head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        branch=subprocess.check_output(["git", "branch", "--show-current"], cwd=APP, text=True).strip(),
        starting_status=subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=APP, text=True, stderr=subprocess.DEVNULL).splitlines(),
        operational_database="NOT_OPENED", new_tests_executed=False)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
    print(json.dumps(dict(status="PASS", protected_documents=len(protected),
        source_files=len(result["source"]), archived_handoffs=len(paths), prior_python=result["prior_python"])))


if __name__ == "__main__":
    main()
