"""Independent byte checks for a partial checkpoint; no operational DB access."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_receipt(name, archive_name):
    path = APP / "docs/evidence" / name
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "PASS" and data["exit_code"] == 0 and not data["unraisable_errors"]
    p = data["python"]
    assert p["passed"] == p["executed"] and p["expected_ids"] == p["executed_ids"] == p["passed_ids"]
    assert all(not p[key] for key in ("failures", "errors", "skipped", "expected_failures", "unexpected_successes"))
    assert data["source_before"] == data["source_after"]
    assert all(check["status"] == "PASS" and check["exit_code"] == 0 for check in data["checks"])
    for log, checksum in data["logs"].items():
        assert sha(APP / log) == checksum
    archive_path = APP / "docs/evidence" / archive_name
    with ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        assert manifest["kind"] == "OFFLINE_RELEASE_CANDIDATE" and manifest["live_acceptance"] is False
        assert set(archive.namelist()) == set(manifest["files"]) | {"RELEASE_MANIFEST.json"}
        assert len(archive.namelist()) == len(set(archive.namelist()))
        for filename, info in manifest["files"].items():
            content = archive.read(filename)
            assert info == dict(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
            assert filename != ".env" and not filename.endswith((".db", "-wal", "-shm")) and ".local/" not in filename
        omitted = set(data["source_after"]) - set(manifest["files"])
        # Both retained verifiers hashed this empty, extensionless editor artifact.
        # Both historical release manifests intentionally enumerate public/index.html
        # and omit it. Record the precise scope difference; never skip arbitrary files.
        assert omitted == {"public/rea"}, sorted(omitted)
        assert data["source_after"]["public/rea"] == hashlib.sha256(b"").hexdigest()
        assert (APP / "public/rea").read_bytes() == b""
        for filename, checksum in data["source_after"].items():
            if filename not in omitted:
                assert manifest["files"][filename]["sha256"] == checksum
    return dict(status="HISTORICAL_RECEIPT_AND_ARCHIVE_VALIDATED", receipt=name, archive=archive_name,
        receipt_sha256=sha(path), archive_sha256=sha(archive_path), files=len(manifest["files"]),
        python=p["executed"], source_matches_current=data["source_after"] == source_snapshot(APP),
        omitted_verifier_files=[dict(path="public/rea", size=0,
            sha256=data["source_after"]["public/rea"], reason="EMPTY_EXTENSIONLESS_NONRUNTIME_ARTIFACT_OUTSIDE_RELEASE_MANIFEST")])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    assert args.stage.replace("_", "").isalnum()
    before = json.loads((APP / "docs/evidence/astra_baseline_20261024_01.json").read_text())
    for name, checksum in before["preserved_documents"].items():
        assert sha(APP / name) == checksum, name
    assert all(sha(Path(name)) == checksum for name, checksum in before["saved_config_hashes"].items())
    brd = Path(r"C:\Users\HP\Downloads\TradePulse_AI_BRD_and_Project_Status_2026-10-24.docx")
    assert sha(brd) == before["brd_sha256"]
    proof = validate_evidence(APP / "docs/evidence" / args.receipt)
    old = [historical_receipt("master_phase45_20261024_03.json", "phase45_release_20261024_01.zip"),
           historical_receipt("master_phase6_20261024_01.json", "phase6_release_20261024_01.zip")]
    source = source_snapshot(APP)
    changed = {name: checksum for name, checksum in source.items() if before["source"].get(name) != checksum}
    output = dict(status="PASS", scope="PARTIAL_OFFLINE_CHECKPOINT_NOT_MISSION_ACCEPTANCE",
        recorded_at=datetime.now(timezone.utc).isoformat(), head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        source=source, changed_source=changed, current_receipt=args.receipt, current_receipt_sha256=sha(APP / "docs/evidence" / args.receipt),
        python=proof["python"]["executed"], checks=proof["checks"], historical=old,
        prior_documents_preserved=len(before["preserved_documents"]), both_env_files_preserved=True, original_brd_preserved=True,
        operational_db="NEVER_OPENED_BY_MISSION_CONTENTS_UNATTESTED", provider_requests=0,
        paper_trigger_defect="REPRODUCED_NOT_REPAIRED", dynamic_ranker="FOCUSED_TESTED_PROTOTYPE_NOT_SCANNER_INTEGRATED")
    path = APP / "docs/evidence" / ("astra_preservation_" + args.stage + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(dict(status="PASS", preserved_documents=output["prior_documents_preserved"],
        changed_source_files=len(changed), python=output["python"], historical_archives=[p["files"] for p in old])))


if __name__ == "__main__":
    main()
