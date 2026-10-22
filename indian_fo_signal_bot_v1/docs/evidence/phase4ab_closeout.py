"""Reopen executed evidence and bind the final Phase 4A/4B release and reports."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from verify_offline import validate_evidence,digest
from release_management import ReleasePackager

def read(path):
    raw=path.read_bytes()
    return json.loads(raw.decode("utf-16" if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig"))

def main():
    evidence=APP/"docs/evidence"
    final=validate_evidence(evidence/"master_phase4ab_verified.json",APP)
    runtime=read(evidence/"phase4ab_crypto_runtime_verified.json")
    safe=read(evidence/"phase4ab_safe_configuration_verified.json")
    assert runtime["status"]=="PASS" and runtime["real_ed25519_verification"]=="PASS"
    assert runtime["signature_size"]==64 and runtime["modified_bytes_rejected"] is True
    assert Path(runtime["interpreter"]).resolve()==Path(sys.executable).resolve()
    assert safe["active_broker"]=="paper_sim" and safe["telegram_dry_run"] is True
    assert safe["enable_background_scheduler"] is False and safe["live_requests"] is False
    ids=final["python"]["passed_ids"]
    assert "test_publisher_trust.TestPublisherTrustMatrix.test_case_01_correct_signature_and_exact_artifact_bytes" in ids
    assert "test_publisher_trust.TestPublisherTrustMatrix.test_case_03_missing_trust_roots_and_verifier_dependency_unavailable" in ids
    assert sum(name.startswith("test_option_execution.") for name in ids)==18
    reports=["docs/TRADEPULSE_EXECUTION_LEDGER.md","docs/TRADEPULSE_OPERATIONS_RUNBOOK.md",
        "docs/reports/TRADEPULSE_TEST_READINESS_REPORT.md","docs/reports/TRADEPULSE_PRODUCTION_READINESS_REPORT.md"]
    for name in reports:
        assert (APP/name).read_text(encoding="utf-8").strip()
    # The runbook is bundled; other reports are separately bound in this witness.
    bundle=evidence/"phase4ab_release_final.zip"
    release=ReleasePackager().inspect_bundle(bundle)
    import zipfile
    with zipfile.ZipFile(bundle) as archive:
        manifest=json.loads(archive.read("RELEASE_MANIFEST.json"))
    for name,value in final["source_after"].items():
        if name=="public/rea":
            assert (APP/name).stat().st_size==0
            continue
        assert name in manifest["files"] and manifest["files"][name]["sha256"]==value,name
    for name,value in manifest["files"].items():
        assert digest(APP/name)==value["sha256"],name
    stages=[]
    for name in ("master_phase4a_source_trust_run1_failed.json","master_phase4a_source_trust.json",
                 "master_phase4b_option_final.json","master_phase4ab_accepted.json","master_phase4ab_verified.json"):
        data=read(evidence/name)
        stages.append(dict(file=name,sha256=digest(evidence/name),status=data["status"],exit_code=data["exit_code"],
            executed=data["python"]["executed"],passed=data["python"]["passed"],failures=data["python"]["failures"],
            errors=data["python"]["errors"],skipped=data["python"]["skipped"],compiled_files=data["checks"][-1]["compiled_files"],
            stale_log_references=[key for key,value in data["logs"].items() if digest(APP/key)!=value],
            current_source_matches=data["source_after"]==final["source_after"]))
    focused=[]
    for path in sorted(evidence.glob("phase4*.txt")):
        raw=path.read_bytes()
        body=raw.decode("utf-16" if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig")
        counts=re.findall(r"Ran (\d+) tests?",body)
        if counts:
            ok=bool(re.search(r"^OK\s*$",body,re.MULTILINE))
            failed=re.findall(r"FAILED \(([^)]+)\)",body)
            focused.append(dict(file=path.name,sha256=digest(path),executed=int(counts[-1]),
                exit_code=0 if ok else 1,status="PASS" if ok else "FAIL",failure_summary=failed[-1] if failed else None,
                overlapping_not_summed=True))
    git=lambda *args:subprocess.run(["git",*args],cwd=APP,check=True,capture_output=True,text=True).stdout.strip()
    check=subprocess.run(["git","diff","--check"],cwd=APP,capture_output=True,text=True)
    assert check.returncode==0
    report=dict(kind="PHASE4AB_EXECUTED_CLOSEOUT",status="PASS",head=git("rev-parse","HEAD"),
        working_tree=git("status","--short"),scope="OFFLINE_ENGINEERING_ONLY",runtime=runtime,safety=safe,
        phase4a="PASS_OFFLINE_ENGINEERING",phase4b="PASS_BOUNDED_OPTION_MECHANICS",
        production_ready="BLOCKED",real_historical_option_study="NOT_ACCEPTED",real_trading="NOT_AUTHORIZED",
        live_requests=0,final_evidence="master_phase4ab_verified.json",final_evidence_sha256=digest(evidence/"master_phase4ab_verified.json"),
        stages=stages,focused_runs=focused,final_checks=final["checks"],unraisable_errors=final["unraisable_errors"],
        release=dict(path=bundle.relative_to(APP).as_posix(),**release),
        reports={name:digest(APP/name) for name in reports},requirements_sha256=digest(APP/"requirements.txt"),
        workflow_sha256=digest(APP.parent/".github/workflows/offline.yml"),
        original_claim_correction=dict(claimed_compiled_files=52,artifact_compiled_files=stages[1]["compiled_files"],
            original_source_bound_check="PASS_AT_START",original_crypto_engineering_status="PARTIAL_HASH_MOCK_FALLBACK_DETECTED"),
        scores=dict(before_implementation=64.25,after_implementation=64.25,before_readiness=37.0,after_readiness=37.0,
            whole_milestones_accepted=0,rubric_changed=False),
        limits=["NIFTY_BANKNIFTY_OPTIDX_LONG_ONLY","ONE_OPEN_POSITION","NO_PARTIAL_FILLS_OR_SHORT_MARGIN",
                "OPENING_QUOTE_DEPTH_ONLY","INTRABAR_STOP_COLLISION_UNRESOLVED_WITHOUT_EXECUTABLE_QUOTE",
                "NO_OVERNIGHT_OR_INVENTED_SETTLEMENT","CONFIGURED_CALENDAR_ESTIMATED_COSTS",
                "RETAIN_ORIGINAL_REQUEST_SEPARATELY_NO_DURABLE_OPTION_DATASET_ARCHIVE"],
        external_blockers=["REAL_OPERATOR_TRUST_ANCHORS","LICENSED_SIGNED_CONTRACT_PREMIUM_DEPTH_AND_CLOSING_OI_DATA",
                           "REAL_CALENDAR_COST_AND_OPERATING_ACCEPTANCE"],
        next_task="Acquire operator-approved signed dataset/root/rights artifacts and run the existing qualification gates; keep real study unaccepted until then.")
    with (evidence/"phase4ab_closeout.json").open("x",encoding="utf-8") as target:
        json.dump(report,target,indent=2);target.write("\n")
    print(json.dumps(dict(status="PASS",python_passed=final["python"]["passed"],node_passed=final["checks"][0]["passed"],
        compiled_files=final["checks"][-1]["compiled_files"],release_sha256=release["sha256"])))

if __name__=="__main__":main()
