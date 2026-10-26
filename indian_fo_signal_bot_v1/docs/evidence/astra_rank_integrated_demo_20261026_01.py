"""Retain an actual offline two-stock scanner rank change; no market acceptance."""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import warnings


APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import (ExecutionResult, case_ids, digest, offline_network,
                            python_result, source_snapshot, timestamp)

TEST = ("test_astra_rank_history.TestAstraRankHistory."
        "test_actual_two_stock_scanner_refresh_reverses_priority_on_new_volume_evidence")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="20261026_01")
    args = parser.parse_args()
    if not args.stage.replace("_", "").isalnum():
        parser.error("A unique alphanumeric stage is required")
    output = APP / "docs/evidence" / ("astra_rank_integrated_demo_" + args.stage + ".json")
    started = timestamp()
    with output.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS", started_at=started), stream)
    before = source_snapshot(APP)
    views, unraisable, runner_errors = [], [], []
    result, expected = None, []
    # Fixture logs stay in memory. Public evidence exports only bounded ranking
    # views, source hashes and execution outcomes, never environment/settings.
    captured = io.StringIO()
    try:
        with ExitStack() as stack, redirect_stdout(captured), redirect_stderr(captured):
            offline_network(stack)
            stack.enter_context(warnings.catch_warnings())
            warnings.simplefilter("error", ResourceWarning)
            stack.enter_context(patch("sys.unraisablehook",
                side_effect=lambda event: unraisable.append(type(event.exc_value).__name__)))
            import test_astra_rank_history as fixture_module
            original_read = fixture_module.read_current

            def retain_view(*positional, **keywords):
                view = original_read(*positional, **keywords)
                views.append(copy.deepcopy({key: view[key] for key in
                    ("status", "actionable", "as_of", "current_rows", "snapshot")}))
                return view

            stack.enter_context(patch.object(fixture_module, "read_current", side_effect=retain_view))
            suite = unittest.defaultTestLoader.loadTestsFromName(TEST)
            expected = list(case_ids(suite))
            result = unittest.TextTestRunner(stream=captured, verbosity=2,
                resultclass=ExecutionResult).run(suite)
    except Exception as exc:
        runner_errors.append(type(exc).__name__)
    after = source_snapshot(APP)
    execution = python_result(result, expected) if result is not None else dict(
        status="FAIL", exit_code=1, executed=0, passed=0, failures=0, errors=1,
        expected_ids=[TEST], executed_ids=[], passed_ids=[])
    checks = dict(
        exactly_one_requested_test=execution["executed_ids"] == [TEST],
        exactly_two_retained_views=len(views) == 2,
        initial_tcs_infy=len(views) == 2 and [r["symbol"] for r in views[0]["current_rows"]] == ["TCS", "INFY"],
        refreshed_infy_tcs=len(views) == 2 and [r["symbol"] for r in views[1]["current_rows"]] == ["INFY", "TCS"],
        views_non_actionable=bool(views) and all(v["actionable"] is False for v in views),
        source_unchanged=before == after,
        no_unraisable_errors=not unraisable,
        no_runner_errors=not runner_errors)
    passed = execution["status"] == "PASS" and all(checks.values())
    report = dict(status="PASS" if passed else "FAIL", exit_code=0 if passed else 1,
        schema_version="tradepulse.offline-integrated-rank-demo.v1",
        evidence_scope="OFFLINE_ILLUSTRATIVE_SCANNER_AND_RANK_HISTORY_MECHANICS_ONLY",
        genuine_market_data=False, empirical_edge_established=False, live_acceptance_established=False,
        provider_transport="MOCKED_FIXTURE_ONLY_EXTERNAL_SOCKETS_BLOCKED",
        fixture_description="Two-stock TCS/INFY completed-bar fixtures; later volume evidence reverses actual evaluator quality and retained priority.",
        started_at=started, completed_at=timestamp(), requested_test=TEST,
        helper=Path(__file__).relative_to(APP).as_posix(), helper_sha256=digest(Path(__file__)),
        execution=execution, checks=checks, source_before=before, source_after=after,
        unraisable_errors=unraisable, runner_errors=runner_errors, views=views)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=report["status"], artifact=output.relative_to(APP).as_posix(),
        artifact_sha256=digest(output), executed=execution["executed"], passed=execution["passed"],
        retained_views=len(views), failed_checks=[name for name, passed_check in checks.items() if not passed_check])))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
