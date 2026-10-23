"""Verify final source, exact release and preserved historical receipts locally."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence
from release_management import ReleasePackager


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    with (APP / "docs/evidence" / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def main():
    evidence_path = APP / "docs/evidence/master_task2_parallel_verified.json"
    result = validate_evidence(evidence_path)
    assert result["source_after"] == source_snapshot()
    destination = APP / "docs/evidence/task2_parallel_closeout.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS"), stream)
    baseline = json.loads((APP / "docs/evidence/task2_parallel_baseline.json").read_text())
    preserved = {name: sha(APP.parent / name) == checksum
                 for name, checksum in baseline["existing_files"].items()
                 if name.startswith("indian_fo_signal_bot_v1/docs/evidence/")}
    assert preserved and all(preserved.values()), "Historical evidence changed"
    from config import BotConfig
    from dhan_feed_control import preflight
    cfg = BotConfig()
    assert cfg.active_broker == "paper_sim" and cfg.telegram_dry_run is True
    assert cfg.enable_background_scheduler is False
    local = preflight(cfg)
    assert local["status"] == "BLOCKED" and local["live_requests"] is False
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
    archive_path = APP / "docs/evidence/task2_parallel_release.zip"
    packager = ReleasePackager(APP)
    built = packager.build_bundle(archive_path)
    inspected = packager.inspect_bundle(archive_path)
    assert built == inspected
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        for name, metadata in manifest["files"].items():
            assert archive.read(name) == (APP / name).read_bytes(), name
            assert sha(APP / name) == metadata["sha256"], name
    binding = dict(archive=archive_path.relative_to(APP).as_posix(), source_revision=head,
        tested_source_revision=result.get("source_revision"),
        verification=evidence_path.relative_to(APP).as_posix(), verification_sha256=sha(evidence_path))
    save("task2_parallel_release_build.json", dict(built, **binding))
    save("task2_parallel_release_inspect.json", dict(inspected, **binding))
    diff = subprocess.run(["git", "diff", "--check"], cwd=APP, capture_output=True, text=True)
    assert diff.returncode == 0, "Diff check failed"
    runtime = subprocess.run([sys.executable, "-m", "pip", "check"], cwd=APP, capture_output=True, text=True)
    assert runtime.returncode == 0, "Dependency consistency failed"
    receipt = dict(status="PASS", scope="OFFLINE_SOURCE_AND_RELEASE_INTEGRITY_NOT_REAL_PROVIDER_ACCEPTANCE",
        recorded_at=datetime.now(timezone.utc).isoformat(), entry_head=baseline["head"], final_head=head,
        initial_working_tree=baseline["working_tree"],
        final_working_tree=subprocess.check_output(["git", "status", "--porcelain"], cwd=APP.parent, text=True),
        source_revision_advanced_externally=baseline["head"] != head,
        git_mutations_performed_by_agents=False, historical_evidence_preserved=preserved,
        source_before_after_current_equal=True, source_snapshot=result["source_after"],
        verification=dict(binding, python={k: result["python"][k] for k in
            ("executed", "passed", "failures", "errors", "skipped")}, checks=result["checks"],
            unraisable_errors=result["unraisable_errors"]),
        release=dict(inspected, **binding),
        bundled_file_hashes={n: m["sha256"] for n, m in manifest["files"].items()},
        local_dhan_preflight=local, live_smoke_attempted=False,
        safe_runtime=dict(active_broker=cfg.active_broker, telegram_dry_run=cfg.telegram_dry_run,
                          scheduler_enabled=cfg.enable_background_scheduler),
        dependency_consistency=dict(exit_code=runtime.returncode, output=runtime.stdout.strip()),
        diff_check=dict(exit_code=diff.returncode, line_ending_warnings_only=bool(diff.stderr)),
        acceptance=dict(track_a="IMPLEMENTED_AND_OFFLINE_TESTED", track_b="IMPLEMENTED_AND_OFFLINE_TESTED",
            real_source_verification="BLOCKED", real_historical_study="BLOCKED",
            live_feed="BLOCKED_NOT_RUN", production="BLOCKED"), scores_recalculated=False)
    # Complete only the receipt exclusively reserved by this invocation.
    with destination.open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(dict(status="PASS", python_passed=result["python"]["passed"],
        node_passed=result["checks"][0]["passed"], release_files=inspected["files"],
        release_sha256=inspected["sha256"], preserved_evidence=len(preserved), final_head=head)))


if __name__ == "__main__":
    main()
