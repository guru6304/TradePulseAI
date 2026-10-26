"""Unique offline focused execution receipts; no operational config or DB."""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import warnings

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import ExecutionResult, case_ids, python_result, offline_network, digest, timestamp, source_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("tests", nargs="+")
    args = parser.parse_args()
    if not args.stage.replace("_", "").isalnum():
        parser.error("Simple unique stage required")
    output = APP / "docs/evidence" / ("astra_" + args.stage)
    before = source_snapshot(APP)
    receipt, log = output.with_suffix(".json"), output.with_suffix(".txt")
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS"), stream)
    unraisable, started = [], timestamp()
    with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        stack.enter_context(patch("sys.unraisablehook", side_effect=lambda event: unraisable.append(type(event.exc_value).__name__)))
        warnings.simplefilter("error", ResourceWarning)
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.tests)
        expected = list(case_ids(suite))
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExecutionResult).run(suite)
    report = python_result(result, expected)
    report.update(kind="EXECUTED_FOCUSED_OFFLINE_VERIFICATION", started_at=started, completed_at=timestamp(),
        command=sys.argv, source_before=before, source_after=source_snapshot(APP),
        log=log.relative_to(APP).as_posix(), log_sha256=digest(log), unraisable_errors=unraisable)
    if unraisable:
        report.update(status="FAIL", exit_code=1)
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "executed", "passed", "failures", "errors", "exit_code", "unraisable_errors")}))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
