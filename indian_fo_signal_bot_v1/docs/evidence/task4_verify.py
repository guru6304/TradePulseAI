"""Reconcile Task 4 local evidence; never run a test, service or external request."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
EVIDENCE = APP / "docs/evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_log(name):
    raw = (EVIDENCE / name).read_bytes()
    return raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig").replace("\r\n", "\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=APP, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def result(name, command, expected_exit):
    output = read_log(name)
    matched = re.search(r"^Ran (\d+) tests? in ([\d.]+)s$", output, re.MULTILINE)
    assert matched, name
    total, seconds = int(matched[1]), float(matched[2])
    failed_cases = set(re.findall(r"^FAIL: ([^\s(]+)", output, re.MULTILINE))
    error_cases = set(re.findall(r"^ERROR: ([^\s(]+)", output, re.MULTILINE))
    failures = re.search(r"failures=(\d+)", output)
    errors = re.search(r"errors=(\d+)", output)
    skipped = re.search(r"skipped=(\d+)", output)
    counts = dict(executed=total, passed=total-len(failed_cases)-len(error_cases)-(int(skipped[1]) if skipped else 0),
        failure_records=int(failures[1]) if failures else 0, failed_cases=len(failed_cases),
        errors=int(errors[1]) if errors else 0, skipped=int(skipped[1]) if skipped else 0)
    assert (bool(failures or errors)) == bool(expected_exit), name
    if not expected_exit:
        assert re.search(r"^OK$", output, re.MULTILINE), name
    return dict(command=command, exit_code=expected_exit, counts=counts, seconds=seconds,
                evidence="docs/evidence/"+name, scope="OFFLINE_FIXTURE_MOCK_TEMPORARY_SQLITE")


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def main():
    # This established loader supplies credential-free test configuration and
    # does not execute cases. No local environment values are inspected here.
    inventory = list(ids(unittest.defaultTestLoader.loadTestsFromName("test_bot")))
    assert len(inventory) == len(set(inventory)), "Duplicate unified tests"
    lineage = [i for i in inventory if i.startswith("test_cash_lineage.")]
    assert len(lineage) == 27
    commands = [
        result("task4_initial_integration.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage test_phase4_e2e test_phase5b_forward test_release_management -v", 0),
        result("task4_recovery_first.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage -v", 0),
        result("task4_recovery_hardening.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage -v", 0),
        result("task4_full_offline_suite.txt", "python -B -W error::ResourceWarning -m unittest test_bot -v", 1),
        result("task4_freshness_rollback_before.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage.TestCashScannerRecovery.test_expiry_after_staged_signal_rolls_back_and_reports_zero_committed_signals -v", 1),
        result("task4_status_regression.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage test_phase4_e2e test_continuous_acceptance.TestPerformanceAcceptanceHarness -v", 0),
        result("task4_full_offline_suite_final.txt", "python -B -W error::ResourceWarning -m unittest test_bot -v", 0),
        result("task4_overlap_before.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage.TestCashScannerRecovery.test_overlapping_recovery_cannot_replace_original_committed_scan_outcome -v", 1),
        result("task4_overlap_after.txt", "python -B -W error::ResourceWarning -m unittest test_cash_lineage test_phase4_e2e -v", 0),
        result("task4_regression_verified.txt", "python -B -W error::ResourceWarning -m unittest test_bot -v", 0),
    ]
    assert commands[-1]["counts"]["executed"] == len(inventory) == 675
    node = read_log("task4_dashboard_tests.txt")
    assert re.search(r"tests 6\b", node) and re.search(r"pass 6\b", node) and re.search(r"fail 0\b", node)
    config = json.loads(read_log("task4_configuration_check.txt"))
    assert config["active_broker"] == "upstox" and config["telegram_dry_run"] is True
    assert config["enable_background_scheduler"] is False and config["live_requests"] is False
    assert config["reason_code"] == "LOCAL_CONFIGURATION_VALID"
    source_files = sorted(APP.glob("*.py"))
    assert len(source_files) == 39 and "Compiled 39 Python files" in read_log("task4_compile.txt")
    prior = json.loads((EVIDENCE / "task4_baseline.json").read_text())
    prior_hashes = prior["baseline_files"]
    intentional_python = {"storage.py", "scanner_engine.py", "release_management.py", "test_bot.py"}
    unchanged_python = {name: sha(APP / name) == value for name, value in prior_hashes.items()
                        if name.endswith(".py") and name not in intentional_python}
    assert all(unchanged_python.values()) and len(unchanged_python) == 33
    notices = ("docs/TRADEPULSE_CAPABILITY_MATRIX.md", "docs/reports/TRADEPULSE_TASK2_BLOCKERS_AND_NEXT_ACTIONS.md")
    preserved_prefix = {}
    for name in notices:
        old = git("show", "60834dd:indian_fo_signal_bot_v1/"+name)
        preserved_prefix[name] = (APP / name).read_text(encoding="utf-8").startswith(old)
    assert all(preserved_prefix.values())
    historical = {name: sha(APP / name) == value for name, value in prior_hashes.items()
                  if name.replace("\\", "/").startswith("docs/reports/")
                  and name.replace("\\", "/") not in notices}
    assert all(historical.values())
    report_path = APP / "docs/reports/TRADEPULSE_TASK4_CASH_CANDLE_LINEAGE_AND_RECOVERY_REPORT.md"
    report = report_path.read_text(encoding="utf-8")  # Physical reopening, not an editor buffer.
    assert "Final full-suite result recorded below after execution" not in report
    assert "Execution verdict: PASS" in report and "675" in report
    for method in re.findall(r"[LR]\.(test_[A-Za-z0-9_]+)", report):
        assert any(i.endswith("."+method) for i in lineage), method
    scores = json.loads((EVIDENCE / "task3_verification.json").read_text())["scores"]
    for key, target in (("implementation", 64.25), ("readiness", 37.0)):
        assert sum(w*s/100 for w, s in zip(scores["weights"], scores[key])) == target
    git("diff", "--check")
    inventory_body = dict(unique_cases=len(inventory), lineage_cases=len(lineage), case_ids=inventory)
    (EVIDENCE / "task4_test_inventory.json").write_text(json.dumps(inventory_body, indent=2)+"\n", encoding="utf-8")
    verification = dict(scope="OFFLINE_ONLY_NO_OPERATIONAL_ACCEPTANCE", head=git("rev-parse", "HEAD"),
        branch=git("branch", "--show-current"), commands=commands, unique_python_cases=len(inventory),
        node=dict(command="node test_cash_dashboard.js", exit_code=0, passed=6, failures=0, skipped=0),
        compile=dict(files=39, exit_code=0, is_test_count=False), configuration=config, scores=scores,
        unchanged_task3_python=unchanged_python, historical_reports_unchanged=historical,
        original_report_prefixes_preserved=preserved_prefix, python_sha256={p.name: sha(p) for p in source_files},
        report=dict(path=str(report_path.relative_to(APP)), sha256=sha(report_path), physically_reopened=True),
        git_status=git("status", "--short").splitlines(),
        artifacts=[dict(path=str(p.relative_to(APP)), bytes=p.stat().st_size, sha256=sha(p))
                   for p in sorted(EVIDENCE.glob("task4_*")) if p.name != "task4_verification.json"])
    (EVIDENCE / "task4_verification.json").write_text(json.dumps(verification, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(status="PASS", unique_python_cases=len(inventory), lineage_cases=len(lineage),
        node_passed=6, python_compiled=39, report_reopened=True, source_preservation=True,
        weighted_implementation=64.25, weighted_readiness=37.0)))


if __name__ == "__main__":
    main()
