"""Execute offline historical acquisition and existing qualification mechanics."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import gc
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
import verify_offline as verification

before = verification.source_snapshot(APP)
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
prefix = APP / "docs/evidence/phase3_angel_history_focused_20261023_01"
log = prefix.with_suffix(".txt")
unraisable = []
with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
    verification.offline_network(stack)
    stack.enter_context(patch("sys.unraisablehook", side_effect=lambda e: unraisable.append(type(e.exc_value).__name__)))
    suite = unittest.defaultTestLoader.loadTestsFromNames(["test_angel_history_capture", "test_historical_study"])
    expected = list(verification.case_ids(suite))
    started = time.monotonic()
    outcome = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=verification.ExecutionResult).run(suite)
    elapsed = time.monotonic() - started
    result = verification.python_result(outcome, expected)
    gc.collect()
after = verification.source_snapshot(APP)
passed = result["status"] == "PASS" and before == after and not unraisable
receipt = dict(scope="OFFLINE_HISTORY_CAPTURE_FIXTURES_AND_EXISTING_QUALIFICATION_NOT_REAL_PROVIDER_ACCEPTANCE",
    source_revision=head, source_before=before, source_after=after, source_unchanged=before == after,
    command=[sys.executable, "-B", "-W", "error::ResourceWarning", str(Path(__file__).relative_to(APP))],
    python=result, duration_seconds=round(elapsed, 3), unraisable_errors=unraisable,
    log_path=log.relative_to(APP).as_posix(), log_sha256=verification.digest(log),
    status="PASS" if passed else "FAIL", exit_code=0 if passed else 1,
    actual_private_API_calls=0, historical_research_acceptance="BLOCKED_NO_APPROVED_ROOTS_RIGHTS_OR_DATED_MASTER")
with prefix.with_suffix(".json").open("x", encoding="utf-8") as stream:
    json.dump(receipt, stream, indent=2)
    stream.write("\n")
print(json.dumps(dict(status=receipt["status"], tests=result["executed"], passed=result["passed"],
    failures=result["failures"], errors=result["errors"], skipped=result["skipped"],
    duration_seconds=receipt["duration_seconds"], source_unchanged=before == after,
    receipt=prefix.with_suffix(".json").relative_to(APP).as_posix())))
sys.exit(receipt["exit_code"])
