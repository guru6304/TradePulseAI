"""Guarded offline R2 regression receipt; no operational data or provider access.

From app root: python -B docs/research/evidence/TP_RANK_R2_verify.py --stage after01
Choose a fresh stage for reruns; retained evidence is never overwritten.
"""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APP))
from verify_offline import (offline_network, ExecutionResult, case_ids, python_result,
                            source_snapshot, timestamp, run_node_tests)

MODULES = [
    "test_r2_ranking_reliability", "test_bot.TestMarketDataFreshness",
    "test_astra_ranking", "test_astra_rank_history", "test_astra_scan_references",
    "test_market_data_contract", "test_phase4_recommendations", "test_phase4_evaluation_storage",
    "test_cash_lineage", "test_h1_paper_conflicts", "test_h1_option_preflight",
    "test_astra_paper_triggers", "test_astra_vwap_paper_triggers", "test_astra_vwap_execution",
    "test_track_a_order_block_triggers", "test_track_a_order_block_execution",
    "test_track_a_supertrend_triggers", "test_track_a_supertrend_execution",
    "test_phase5b_forward", "test_cash_workflow", "test_astra_http_safety", "test_track_a_cold_http",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    stage = parser.parse_args().stage
    if not re.fullmatch(r"[a-z0-9_]{1,32}", stage):
        parser.error("Use a short lowercase stage")
    os.chdir(APP)
    prefix = Path(__file__).with_name("TP_RANK_R2_20261103_"+stage)
    receipt = prefix.with_suffix(".json")
    receipt.open("x", encoding="utf-8").close()
    log = prefix.with_suffix(".txt")
    before, started = source_snapshot(), timestamp()
    unraisable = []
    with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        stack.enter_context(patch("sys.unraisablehook", side_effect=lambda e: unraisable.append(type(e.exc_value).__name__)))
        import test_bot  # credential-free defaults and .env hidden before config import
        suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
        expected = list(case_ids(suite))
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExecutionResult).run(suite)
        python = python_result(result, expected)
    checks = []
    for stem in ("test_terminal_opportunities", "test_terminal_clock"):
        checks.append(run_node_tests(["node", "--test", "--test-reporter=tap", stem+".js"],
            prefix.with_name(prefix.name+"_"+stem+".txt")))
    after = source_snapshot()
    passed = python["exit_code"] == 0 and before == after and not unraisable and all(c["exit_code"] == 0 for c in checks)
    data = dict(kind="EXECUTED_R2_OFFLINE_REGRESSION", status="PASS" if passed else "FAIL",
        exit_code=0 if passed else 1, started_at=started, finished_at=timestamp(),
        base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        command=[sys.executable, "-B", "docs/research/evidence/TP_RANK_R2_verify.py", "--stage", stage],
        modules=MODULES, python=python, checks=checks, source_before=before, source_after=after,
        source_unchanged=before == after, unraisable_errors=unraisable,
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
        scope="OFFLINE_FIXTURES_ONLY_NO_LIVE_OR_EMPIRICAL_ACCEPTANCE")
    receipt.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(dict(status=data["status"], executed=python["executed"], passed=python["passed"],
        failures=python["failures"], errors=python["errors"], skipped=python["skipped"],
        source_unchanged=before==after, checks=checks), indent=2))
    if not passed:
        print(log.read_text(encoding="utf-8")[-12000:])
    raise SystemExit(data["exit_code"])


if __name__ == "__main__":
    main()
