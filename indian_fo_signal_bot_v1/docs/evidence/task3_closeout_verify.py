"""Validate Task 3 receipts and preservation without rebuilding software."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot
from release_management import ReleasePackager


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((APP / "docs/evidence" / name).read_text(encoding="utf-8"))


def main():
    destination = APP / "docs/evidence/task3_real_acceptance_closeout.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS"), stream)
    baseline = read("task3_real_acceptance_baseline.json")
    source = source_snapshot()
    assert source == baseline["source_snapshot"]
    preserved = {name: checksum(APP / "docs/evidence" / name) == value
                 for name, value in baseline["prior_evidence_hashes"].items()}
    assert all(preserved.values())
    a = read("task3_track_a_focused_current.json")
    b = read("task3_track_b_acceptance_001.json")
    shared = read("task3_shared_verification_001.json")
    discovery = read("task3_track_a_input_discovery_verified.json")
    for receipt in (a, shared):
        assert receipt["status"] == "PASS"
        assert receipt["source_before"] == receipt["source_after"] == source
        result = receipt["python"]
        assert result["status"] == "PASS" and result["executed"] == result["passed"]
        assert not any(result[k] for k in ("failures", "errors", "skipped"))
        assert not receipt["unraisable_errors"]
        for name, value in receipt["logs"].items():
            assert checksum(APP / name) == value
    for name, value in b["source_hashes"].items():
        assert source[name] == value
    result_b = b["offline_verification"]
    assert result_b["exit_code"] == 0 and result_b["executed"] == result_b["passed"]
    assert not any(result_b[k] for k in ("failures", "errors", "skips"))
    assert not b["network_attempted"] and not b["smoke_command_executed"]
    assert not discovery["authentic_cash_study_executed"]
    assert discovery["qualifying_cash_candle_count"] == 0
    b_log = (APP / "docs/evidence/task3_track_b_focused_001.txt").read_text(encoding="utf-8")
    b_ids = re.findall(r"^test_\S+ \(([^)]+)\)", b_log, re.MULTILINE)
    assert len(b_ids) == result_b["executed"]
    ids = a["python"]["executed_ids"] + b_ids + shared["python"]["executed_ids"]
    assert len(ids) == len(set(ids)) == 150
    node = (APP / "docs/evidence/task3_dashboard_001.txt").read_text(encoding="utf-8")
    counts = {label: int(re.search(r"\b" + label + r" (\d+)\s*$", node, re.MULTILINE)[1])
              for label in ("tests", "pass", "fail", "skipped")}
    assert counts["tests"] == counts["pass"] == 11 and not counts["fail"] and not counts["skipped"]
    assert all(check["exit_code"] == 0 for check in shared["checks"])
    archive = APP / "docs/evidence/task2_parallel_release.zip"
    inspected = ReleasePackager(APP).inspect_bundle(archive)
    assert inspected["sha256"] == read("task2_parallel_release_build.json")["sha256"]
    assert inspected["sha256"] == read("task2_parallel_release_inspect.json")["sha256"]
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("RELEASE_MANIFEST.json"))
        for name in manifest["files"]:
            assert bundle.read(name) == (APP / name).read_bytes()
    from config import BotConfig, _is_placeholder_value
    cfg = BotConfig()
    assert cfg.active_broker == "paper_sim" and cfg.telegram_dry_run is True
    assert cfg.enable_background_scheduler is False
    # Compare locally loaded long secret literals without ever returning their values.
    fields = ("angel_api_key", "angel_client_code", "angel_totp_secret", "dhan_client_id",
              "dhan_access_token", "upstox_api_key", "upstox_access_token", "telegram_bot_token",
              "telegram_chat_id", "gemini_api_key")
    secrets = [str(getattr(cfg, name)) for name in fields
               if not _is_placeholder_value(getattr(cfg, name)) and len(str(getattr(cfg, name))) >= 8]
    new_files = list((APP / "docs/evidence").glob("task3_*"))
    report = APP / "docs/reports/TRADEPULSE_TASK3_REAL_DATA_ACCEPTANCE_REPORT.md"
    for path in new_files + [report]:
        if path.is_file():
            body = path.read_bytes()
            assert not any(value.encode() in body for value in secrets), "Configured secret found in new evidence"
    diff = subprocess.run(["git", "diff", "--check"], cwd=APP, capture_output=True, text=True)
    assert diff.returncode == 0
    prior = read("task3_prior_manifest_validation_001.json")
    assert prior["exit_code"] == 1 and prior["failure_reason"] == "EVIDENCE_LOG_INTEGRITY_FAILURE"
    receipt = dict(status="COMPLETED_WITH_EXTERNAL_BLOCKERS_AND_PRIOR_EVIDENCE_FAILURE",
        client_date="2026-10-23", recorded_at=datetime.now(timezone.utc).isoformat(),
        scope="CURRENT_SELECTED_OFFLINE_CHECKS_AND_REAL_INPUT_ACCEPTANCE_DECISIONS",
        source_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        initial_working_tree=baseline["working_tree"],
        final_working_tree=subprocess.check_output(["git", "status", "--porcelain"], cwd=APP, text=True),
        software_source_changed=False, source_snapshot=source, prior_evidence_unchanged=preserved,
        verification=dict(historical_python_passed=a["python"]["passed"],
            dhan_python_passed=result_b["passed"], shared_python_passed=shared["python"]["passed"],
            fresh_distinct_python_passed=len(ids), failures=0, errors=0, skipped=0,
            dashboard=counts, compiled=len(shared["compiled_files"]),
            current_source_and_scoped_log_hashes="PASS", full_suite_rerun=False,
            previous_full_manifest="FAIL_EVIDENCE_LOG_INTEGRITY_FAILURE"),
        historical_acceptance=a["acceptance"], dhan_acceptance=b["acceptance"],
        real_cash_study_executed=False, real_option_study_executed=False, live_probe_attempted=False,
        production_readiness="BLOCKED", release_regenerated=False,
        existing_source_release_inspection=inspected, scores_recalculated=False,
        safety=dict(active_broker=cfg.active_broker, telegram_dry_run=True, scheduler_enabled=False,
                    configured_long_secret_literals_checked=len(secrets), secret_matches_in_new_artifacts=0,
                    orders=False, account_mutations=False, telegram_deliveries=False),
        report=dict(path=report.relative_to(APP).as_posix(), sha256=checksum(report)),
        artifact_hashes={p.relative_to(APP).as_posix(): checksum(p) for p in new_files
                         if p.is_file() and p != destination}, diff_check_exit_code=diff.returncode)
    with destination.open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(dict(status=receipt["status"], fresh_python_passed=len(ids),
        dashboard_passed=counts["pass"], compiled=receipt["verification"]["compiled"],
        preserved_entry_evidence=len(preserved), software_source_changed=False, live_probe_attempted=False)))


if __name__ == "__main__":
    main()
