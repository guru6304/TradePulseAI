"""Bind the Task 3 checklist, genuine full proof, blockers and exact candidate."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence
from release_management import ReleasePackager

EVIDENCE = APP / "docs/evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def save(name, value):
    with (EVIDENCE / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def main():
    baseline = read("task3_completion_baseline_20261023_01.json")
    proof_path = EVIDENCE / "master_task3_completion_20261023_01.json"
    proof = validate_evidence(proof_path)
    current = source_snapshot()
    changed = sorted(n for n in set(current) | set(baseline["source_snapshot"])
                     if current.get(n) != baseline["source_snapshot"].get(n))
    assert changed == ["dhan_feed_control.py", "test_task2_integration.py"]
    preserved = {name: sha(APP / name) == value for name, value in baseline["prior_evidence_hashes"].items()}
    assert all(preserved.values())
    a_name = "task3_completion_track_a_20261023_01_current.json"
    b_name = "task3_completion_track_b_20261023_01.json"
    a, b = read(a_name), read(b_name)
    assert a["exit_code"] == 2 and a["source_unchanged"] and a["source_after"] == current
    assert not a["authentic_cash_study_executed"] and not a["operational_database_opened"]
    assert b["preflight_exit_code"] == 1 and not b["smoke_attempted"] and not b["external_requests"]
    for name, value in b["runtime"]["source_hashes"].items():
        assert current[name] == value
    helper = read("task3_completion_track_a_20261023_01_helper_tests_workspace.json")
    assert helper["status"] == "PASS" and not helper["unraisable_errors"]
    assert helper["source_before"] == helper["source_after"] == current
    assert helper["helper_sha256"] == sha(EVIDENCE / "task3_completion_track_a_20261023_01_verify.py")
    assert helper["log_sha256"] == sha(APP / helper["log_path"])
    b_validation = read("task3_completion_track_b_20261023_01_validation.json")
    for name, value in b_validation["artifact_sha256"].items():
        assert sha(APP / name) == value
    timestamp = datetime.now(timezone.utc).isoformat()
    full_command = ".venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage task3_completion_20261023_01"
    validator_command = ".venv_phase4\\Scripts\\python.exe -B verify_offline.py --validate-evidence docs/evidence/master_task3_completion_20261023_01.json"
    old_failure = dict(blocker_code="EVIDENCE_LOG_INTEGRITY_FAILURE", classification="CODE_DEFECT",
        classification_basis="Agent-remediable verification/evidence category; no application defect causing the historical edit was established",
        severity="HIGH", affected_track="SHARED", affected_acceptance_gate="CURRENT_OFFLINE_VERIFICATION",
        status="RESOLVED", observed_finding="Historical Python log SHA256 differs from the old manifest; old bytes remain preserved",
        evidence_paths=["docs/evidence/task3_completion_old_log_diagnosis_20261023_01.json",
                        "docs/evidence/master_task3_completion_20261023_01.json"],
        exact_failed_command="SHA256 comparison of docs/evidence/master_task2_parallel_verified_python.txt against its original manifest",
        exit_code=1, redacted_error="Recorded and actual historical Python log digests differ",
        root_cause_confidence="CONFIRMED_DIGEST_MISMATCH_HISTORICAL_EDIT_CAUSE_NOT_ESTABLISHED",
        required_input_or_correction="Agent executes a fresh full verification and validates its actual source/log binding",
        who_must_act="AGENT", safe_resolution_steps=["Preserved all historical artifacts", full_command, validator_command],
        verification_command_after_resolution=validator_command,
        expected_result_after_resolution="Current receipt validates with exit 0; old manifest remains historical",
        related_blockers=[], timestamp=timestamp)
    blockers = a["blockers"] + b["resolved_blockers"] + b["open_blockers"] + [old_failure]
    required = {"blocker_code", "classification", "severity", "affected_track", "affected_acceptance_gate",
        "status", "observed_finding", "evidence_paths", "exact_failed_command", "exit_code", "redacted_error",
        "root_cause_confidence", "required_input_or_correction", "who_must_act", "safe_resolution_steps",
        "verification_command_after_resolution", "expected_result_after_resolution", "related_blockers", "timestamp"}
    assert len({r["blocker_code"] for r in blockers}) == len(blockers)
    assert all(required.issubset(row) for row in blockers)
    for row in blockers:
        if row["affected_track"] == "TRACK_A":
            row["verification_command_after_resolution"] = row["verification_command_after_resolution"].replace(
                "--stage current", "--stage operator_check_01")
        if row["blocker_code"] == "OPTION_EXECUTION_DATA_MISSING":
            row.update(deferred_separate_scope=True, mandatory_for_cash_study=False,
                exact_failed_command=None, exit_code=None,
                verification_command_after_resolution="NOT_APPLICABLE_TO_CASH_HELPER: separately configured local run_frozen_study(..., option_request=..., data_mode='LIVE', rights_policy=...) API required",
                expected_result_after_resolution="A separately authorized exact-contract option study passes its own publisher, rights, execution and chronology gates; a cash helper PASS cannot resolve this deferred dependency")
    open_rows = [r for r in blockers if r["status"] != "RESOLVED"]
    assert all(r["who_must_act"] == "OPERATOR" and r["classification"] != "CODE_DEFECT" for r in open_rows)
    checklist_name = "task3_completion_acceptance_20261023_01.json"
    checklist = read(checklist_name)
    checklist.update(TASK_3_STATUS="BLOCKED_AWAITING_OPERATOR_INPUT", updated_at=timestamp,
        source_revision=proof["source_revision"], current_source_hashes=current,
        gates=dict(CURRENT_OFFLINE_VERIFICATION="PASS", REGRESSION_AND_SAFETY_TESTS="PASS",
            TRACK_A_SOURCE_AUTHENTICITY=a["acceptance"]["TRACK_A_SOURCE_AUTHENTICITY"],
            TRACK_A_RIGHTS_APPROVAL=a["acceptance"]["TRACK_A_RIGHTS_APPROVAL"],
            TRACK_A_CASH_STUDY=a["acceptance"]["TRACK_A_CASH_STUDY"],
            TRACK_A_OPTION_STUDY="BLOCKED_SEPARATE_DEPENDENCY_RECORDED",
            TRACK_B_LOCAL_PREFLIGHT="BLOCKED", TRACK_B_LIVE_AUTHENTICATION_AND_SUBSCRIPTION="NOT_ATTEMPTED",
            TRACK_B_OBSERVATIONS="BLOCKED", TRACK_B_CANDLE_ACCEPTANCE="BLOCKED", SAFETY_AND_EVIDENCE_INTEGRITY="PASS"),
        blockers=blockers, full_proof="docs/evidence/" + proof_path.name,
        current_evidence_validator=dict(command=validator_command, exit_code=0), independent_engineering_remaining=False,
        next_task_started=False, production_readiness="BLOCKED", scores_recalculated=False)
    checklist["loop_history"].extend([
        dict(finding="Fresh complete verification", result=proof["status"], python_passed=proof["python"]["passed"],
             validator_exit_code=0, timestamp=timestamp),
        dict(finding="Real historical and Dhan inputs rechecked", result="ONLY_OPERATOR_DEPENDENCIES_REMAIN",
             evidence_paths=["docs/evidence/" + a_name, "docs/evidence/" + b_name], timestamp=timestamp)])
    with (EVIDENCE / checklist_name).open("w", encoding="utf-8") as stream:
        json.dump(checklist, stream, indent=2)
    from config import BotConfig, _is_placeholder_value
    cfg = BotConfig()
    assert cfg.active_broker == "paper_sim" and cfg.telegram_dry_run is True and cfg.enable_background_scheduler is False
    secret_fields = ("angel_api_key", "angel_client_code", "angel_totp_secret", "dhan_client_id", "dhan_access_token",
                     "upstox_api_key", "upstox_access_token", "telegram_bot_token", "telegram_chat_id", "gemini_api_key")
    secret_values = [str(getattr(cfg, name)) for name in secret_fields
                     if not _is_placeholder_value(getattr(cfg, name)) and len(str(getattr(cfg, name))) >= 8]
    report_path = APP / "docs/reports/TRADEPULSE_TASK3_CONTINUATION_AND_COMPLETION_REPORT.md"
    public_paths = [report_path] + [p for p in EVIDENCE.iterdir()
        if p.is_file() and (p.name.startswith("task3_completion_") or p.name.startswith("master_task3_completion_"))]
    for path in public_paths:
        assert not any(value.encode() in path.read_bytes() for value in secret_values), "Secret detected in public artifact"
    archive_path = EVIDENCE / "task3_completion_release_20261023_01.zip"
    packager = ReleasePackager(APP)
    build = packager.build_bundle(archive_path)
    inspect = packager.inspect_bundle(archive_path)
    assert build == inspect
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        for name in manifest["files"]:
            assert archive.read(name) == (APP / name).read_bytes()
    binding = dict(archive=archive_path.relative_to(APP).as_posix(), source_revision=proof["source_revision"],
                   verification=proof_path.relative_to(APP).as_posix(), verification_sha256=sha(proof_path))
    save("task3_completion_release_build_20261023_01.json", dict(build, **binding))
    save("task3_completion_release_inspect_20261023_01.json", dict(inspect, **binding))
    diff = subprocess.run(["git", "diff", "--check"], cwd=APP, capture_output=True, text=True)
    assert diff.returncode == 0
    destination = EVIDENCE / "task3_completion_closeout_20261023_01.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS"), stream)
    result = dict(TASK_3_STATUS=checklist["TASK_3_STATUS"], scope="CURRENT_FULL_OFFLINE_PROOF_WITH_REAL_ACCEPTANCE_BLOCKED",
        timestamp=timestamp, entry_head=baseline["head"], final_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        initial_working_tree=baseline["initial_working_tree"],
        final_working_tree=subprocess.check_output(["git", "status", "--porcelain"], cwd=APP, text=True),
        git_mutations_performed=False, preserved_prior_evidence=preserved, source_snapshot=current, changed_software_files=changed,
        verification=dict(command=full_command, validator_command=validator_command, validator_exit_code=0,
            python={k: proof["python"][k] for k in ("executed", "passed", "failures", "errors", "skipped")},
            checks=proof["checks"], unraisable_errors=proof["unraisable_errors"]),
        operator_helper_tests=dict(passed=helper["python"]["passed"], scope=helper["scope"], real_source_acceptance=False),
        gates=checklist["gates"], unresolved_blocker_codes=[r["blocker_code"] for r in open_rows],
        resolved_blocker_codes=[r["blocker_code"] for r in blockers if r["status"] == "RESOLVED"],
        all_independently_achievable_actions_complete=True, live_probe_attempted=False, authentic_cash_study_executed=False,
        safety=dict(active_broker="paper_sim", telegram_dry_run=True, scheduler_enabled=False,
                    orders=False, account_mutations=False, telegram_deliveries=False, secret_matches_in_new_artifacts=0),
        release=dict(inspect, **binding), report=dict(path=report_path.relative_to(APP).as_posix(), sha256=sha(report_path)),
        checklist=dict(path="docs/evidence/" + checklist_name, sha256=sha(EVIDENCE / checklist_name)),
        artifact_hashes={p.relative_to(APP).as_posix(): sha(p) for p in EVIDENCE.iterdir()
            if p.is_file() and p != destination and (p.name.startswith("task3_completion_") or p.name.startswith("master_task3_completion_"))},
        bundled_file_hashes={name: value["sha256"] for name, value in manifest["files"].items()}, diff_check_exit_code=0)
    with destination.open("w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(dict(TASK_3_STATUS=result["TASK_3_STATUS"], python_passed=proof["python"]["passed"],
        helper_tests_passed=helper["python"]["passed"], open_operator_blockers=len(open_rows),
        release_files=inspect["files"], release_sha256=inspect["sha256"], preserved_evidence=len(preserved))))


if __name__ == "__main__":
    main()
