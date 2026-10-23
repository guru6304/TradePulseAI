"""Run Task 3's bounded offline safety checks, without a new software release."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import warnings

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import (ExecutionResult, case_ids, offline_network,
                            python_result, source_snapshot)


def main():
    evidence = APP / "docs/evidence"
    receipt_path = evidence / "task3_shared_verification_001.json"
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS"), stream)
    before = source_snapshot()
    modules = ["test_market_data_contract", "test_cash_lineage", "test_release_operations",
               "test_verify_offline", "test_phase5a_integration"]
    unraisable = []
    log_path = evidence / "task3_shared_python_001.txt"
    with log_path.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        stack.enter_context(patch("sys.unraisablehook", side_effect=lambda e: unraisable.append(type(e.exc_value).__name__)))
        warnings.simplefilter("error", ResourceWarning)
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in modules)
        expected = list(case_ids(suite))
        execution = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExecutionResult).run(suite)
        result = python_result(execution, expected)
    checks = []
    for command, name in [(["node", "test_cash_dashboard.js"], "task3_dashboard_001.txt"),
                          (["node", "--check", "test_cash_dashboard.js"], "task3_javascript_syntax_001.txt")]:
        completed = subprocess.run(command, cwd=APP, capture_output=True, text=True)
        with (evidence / name).open("x", encoding="utf-8") as stream:
            stream.write(completed.stdout + completed.stderr)
        checks.append(dict(command=command, exit_code=completed.returncode, log="docs/evidence/" + name))
    compiled = []
    for path in sorted(APP.glob("*.py")):
        compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
        compiled.append(path.name)
    after = source_snapshot()
    receipt = dict(scope="TASK3_SELECTED_SHARED_SAFETY_TESTS_NOT_FULL_SUITE_OR_REAL_ACCEPTANCE",
        client_date="2026-10-23", completed_at=datetime.now(timezone.utc).isoformat(),
        command=[sys.executable, "-B", "-W", "error::ResourceWarning", "docs/evidence/task3_verify_shared.py"],
        source_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        source_before=before, source_after=after, python_modules=modules, python=result,
        python_log="docs/evidence/" + log_path.name, checks=checks,
        compiled_files=compiled, unraisable_errors=unraisable, full_suite_rerun=False,
        software_source_changed=False, release_regenerated=False,
        prior_full_manifest_status="FAIL_CURRENT_LOG_INTEGRITY_BINDING",
        logs={"docs/evidence/" + name: hashlib.sha256((evidence / name).read_bytes()).hexdigest()
              for name in [log_path.name, "task3_dashboard_001.txt", "task3_javascript_syntax_001.txt"]})
    receipt["status"] = "PASS" if (result["status"] == "PASS" and before == after and not unraisable
                                   and all(c["exit_code"] == 0 for c in checks)) else "FAIL"
    with receipt_path.open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(dict(status=receipt["status"], executed=result["executed"], passed=result["passed"],
        failures=result["failures"], errors=result["errors"], skipped=result["skipped"], compiled=len(compiled))))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
