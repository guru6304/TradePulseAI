"""Reopen final reports, current executed evidence and release bytes before closeout.

This consumes actual verification; it does not execute tests or authenticate a
publisher. Run after the final source-bound suite and report updates.
"""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import subprocess
import sys
import zipfile

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence, digest
from release_management import ReleasePackager


def read_json(path):
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))


def main():
    evidence = APP/"docs/evidence"
    final_path = evidence/"master_final_accepted.json"
    final = validate_evidence(final_path, APP)
    python = final["python"]
    required = ["docs/TRADEPULSE_EXECUTION_LEDGER.md", "docs/TRADEPULSE_OPERATIONS_RUNBOOK.md",
        "docs/TRADEPULSE_CAPABILITY_MATRIX.md", "docs/reports/TRADEPULSE_TEST_READINESS_REPORT.md",
        "docs/reports/TRADEPULSE_PRODUCTION_READINESS_REPORT.md"]
    texts = {name: (APP/name).read_text(encoding="utf-8") for name in required}
    assert all(text.strip() for text in texts.values())
    for report in ("docs/reports/TRADEPULSE_TEST_READINESS_REPORT.md", "docs/reports/TRADEPULSE_PRODUCTION_READINESS_REPORT.md"):
        assert str(python["executed"]) in texts[report] and "master_final_accepted.json" in texts[report]
    release_path = evidence/"master_release_candidate_002.zip"
    release = ReleasePackager().inspect_bundle(release_path)
    with zipfile.ZipFile(release_path) as archive:
        manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
    # A tracked empty extensionless placeholder is inventoried but never served.
    # Preserve it in the workspace and explicitly exclude it from runtime assets.
    excluded_sources = {"public/rea": "EMPTY_UNSERVED_TRACKED_PLACEHOLDER"}
    for name, value in final["source_after"].items():
        if name in excluded_sources:
            assert (APP/name).stat().st_size==0 and value==digest(APP/name)
            continue
        assert name in manifest["files"], ("release omits verified source", name)
        assert manifest["files"][name]["sha256"] == value, ("release source mismatch", name)
    for name, metadata in manifest["files"].items():
        assert digest(APP/name)==metadata["sha256"], ("release differs from current file", name)
    assert release == read_json(evidence/"master_release_candidate_002_build.json")
    assert release == read_json(evidence/"master_release_candidate_002_inspect.json")
    config = read_json(evidence/"master_final_config.txt")
    assert (config["status"]=="PASS" and config["active_broker"]=="upstox"
            and config["telegram_dry_run"] is True and config["enable_background_scheduler"] is False
            and config["live_requests"] is False and config["readiness_receipt_issued"] is False)
    weights = [8,12,12,10,10,12,10,10,6,4,3,3]
    implementation = [75,75,75,75,25,75,75,50,50,50,75,50]
    readiness = [50,25,50,25,0,50,50,25,50,50,50,50]
    scores = dict(implementation=sum(w*s/100 for w,s in zip(weights,implementation)),
                  readiness=sum(w*s/100 for w,s in zip(weights,readiness)), whole_milestones_accepted=0)
    assert sum(weights)==100 and scores["implementation"]==64.25 and scores["readiness"]==37
    baseline_path = evidence/"master_phase0_python.txt"
    baseline_raw = baseline_path.read_bytes()
    baseline_text = baseline_raw.decode("utf-16" if baseline_raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    baseline_counts = re.findall(r"Ran (\d+) tests", baseline_text)
    assert baseline_counts and re.search(r"^OK\s*$", baseline_text, re.MULTILINE)
    baseline_count = int(baseline_counts[-1])
    git = lambda *args: subprocess.run(["git", *args], cwd=APP, check=True,
        capture_output=True, text=True).stdout.strip()
    diff_check = subprocess.run(["git", "diff", "--check"], cwd=APP, capture_output=True, text=True)
    assert diff_check.returncode==0
    stage_results = []
    for name in ("master_gate2.json", "master_history.json", "master_final.json", "master_final_verified.json", "master_final_accepted.json"):
        data = read_json(evidence/name)
        stage_results.append(dict(file="docs/evidence/"+name, sha256=digest(evidence/name),
            status=data["status"], exit_code=data["exit_code"], python_executed=data["python"]["executed"],
            python_passed=data["python"]["passed"], failure_records=data["python"]["failures"],
            error_records=data["python"]["errors"], skipped=data["python"]["skipped"],
            stale_log_references=[key for key,value in data["logs"].items() if digest(APP/key)!=value],
            current_source_matches=data["source_after"]==final["source_after"]))
    report = dict(kind="MASTER_EXECUTION_CLOSEOUT", scope="OFFLINE_ONLY_NO_LIVE_ACCEPTANCE",
        completed_at=datetime.now(timezone.utc).isoformat(), head=git("rev-parse", "HEAD"),
        branch=git("branch", "--show-current"), working_tree=git("status", "--short"),
        outcomes=dict(testing_ready="PASS", production_ready="BLOCKED", live_read_only="BLOCKED",
                      real_trading="NOT_AUTHORIZED"),
        external_reason="BLOCKED_PENDING_OPERATOR_AUTHORIZATION", final_verification=stage_results[-1],
        stage_results=stage_results, overlapping_counts_summed=False, official_scores=scores,
        starting_baseline=dict(executed=baseline_count, passed=baseline_count,
            log=baseline_path.relative_to(APP).as_posix(), sha256=digest(baseline_path)),
        python_execution_delta=python["executed"]-baseline_count,
        final_checks=final["checks"], unraisable_errors=final["unraisable_errors"],
        release_source_exclusions=excluded_sources,
        release=dict(path=release_path.relative_to(APP).as_posix(), **release),
        safety=config, diff_check_exit_code=diff_check.returncode,
        report_hashes={name: digest(APP/name) for name in required},
        workflow_sha256=digest(APP.parent/".github/workflows/offline.yml"),
        closeout_verifier_sha256=digest(Path(__file__)),
        hosted_ci_executed=False, production_deployment_executed=False,
        local_implementation_gaps=["INDEPENDENT_SOURCE_AUTHENTICITY_EFFECTIVE_DATE_VERIFIER",
            "HISTORICAL_OPTION_EXECUTION", "DERIVATIVE_MARGIN_PARTIAL_EXECUTION",
            "REAL_DELIVERY_OUTBOX_WORKER", "AUTHENTICATED_NONLOCAL_DEPLOYMENT_CENTRAL_ALERTING"],
        next_action="Declare independently verifiable publisher trust/effective-date policy; implement fail-closed source verifier without restarting baseline audit.")
    path = evidence/"master_closeout.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(dict(status="PASS", python_executed=python["executed"], python_passed=python["passed"],
                         release_sha256=release["sha256"], evidence=path.relative_to(APP).as_posix())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
