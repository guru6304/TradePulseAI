"""Guarded offline options checkpoint with immutable source/log-bound receipts."""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from verify_offline import (ExecutionResult, case_ids, digest, offline_network,
                            python_result, timestamp)
from volume_research.verify import snapshot as volume_snapshot

APP = Path(__file__).resolve().parents[1]
MODULES = (
    "option_intelligence.tests.test_identity", "option_intelligence.tests.test_context",
    "option_intelligence.tests.test_quotes", "option_intelligence.tests.test_fitness",
    "option_intelligence.tests.test_compatibility",
    "test_volume_primitives", "test_volume_execution", "test_volume_retest",
    "test_option_observations", "test_option_execution", "test_contract_universe",
    "test_phase4_strategy", "test_astra_research", "test_market_data_contract",
    "test_cash_lineage", "test_astra_ranking", "test_astra_rank_history", "test_h1_paper_conflicts",
)
SAFE = dict(ACTIVE_BROKER="paper_sim", TELEGRAM_DRY_RUN="true",
            ENABLE_BACKGROUND_SCHEDULER="false", PYTHONDONTWRITEBYTECODE="1")


def snapshot():
    result = volume_snapshot()
    for path in sorted((APP/"option_intelligence").rglob("*.py")):
        result[path.relative_to(APP).as_posix()] = digest(path)
    for name in (".gitattributes", "docs/research/TP_OPTION_EXPERIMENT_MANIFEST_V1.json"):
        result[name] = digest(APP/name)
    return result


def validate(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    tests = data["tests"]
    if (data["kind"] != "TP_OPTION_INTELLIGENCE_OFFLINE_CHECKPOINT"
            or data["status"] != "PASS" or data["exit_code"] != 0
            or data["modules"] != list(MODULES) or data["safe_flags"] != SAFE
            or data["external_network"] != "BLOCKED" or data["unraisable_errors"]
            or data["source_before"] != data["source_after"]
            or data["source_after"] != snapshot()
            or tests["status"] != "PASS" or tests["exit_code"] != 0
            or not tests["executed"] or tests["executed"] != tests["passed"]
            or tests["expected_ids"] != tests["executed_ids"]
            or tests["executed_ids"] != tests["passed_ids"]
            or len(set(tests["executed_ids"])) != tests["executed"]
            or any(tests[key] for key in ("failures","errors","skipped","expected_failures","unexpected_successes"))):
        raise ValueError("OPTION_CHECKPOINT_SOURCE_OR_EXECUTION_MISMATCH")
    log = (APP/data["log"]).resolve()
    if not log.is_relative_to(APP) or digest(log) != data["log_sha256"]:
        raise ValueError("OPTION_CHECKPOINT_LOG_MISMATCH")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args(argv)
    if args.validate:
        data = validate(args.validate.resolve())
        print(json.dumps(dict(status="PASS",executed=data["tests"]["executed"],scope="OFFLINE_SOURCE_AND_LOG_BOUND")))
        return 0
    if not args.receipt:
        parser.error("--receipt or --validate is required")
    receipt = args.receipt.resolve()
    if not receipt.is_relative_to(APP):
        parser.error("receipt must be within this application workspace")
    log = receipt.with_suffix(".txt")
    if receipt.exists() or log.exists():
        parser.error("existing evidence cannot be overwritten; use a fresh suffix")
    receipt.parent.mkdir(parents=True,exist_ok=True)
    started, clock, before = timestamp(), time.monotonic(), snapshot()
    source_head = subprocess.run(["git","rev-parse","HEAD"],cwd=APP,check=True,
                                capture_output=True,text=True).stdout.strip()
    with receipt.open("x",encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS",started_at=started),stream)
    unraisable=[]
    with log.open("x",encoding="utf-8",newline="\n") as stream:
        with ExitStack() as guards, redirect_stdout(stream), redirect_stderr(stream):
            offline_network(guards)
            guards.enter_context(patch.dict(os.environ,SAFE))
            guards.enter_context(patch.object(sys,"unraisablehook",
                lambda event: unraisable.append(type(event.exc_value).__name__)))
            import test_bot  # noqa: F401; existing credential-free bootstrap
            guards.enter_context(patch.dict(os.environ,SAFE))
            suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
            expected=list(case_ids(suite))
            result=unittest.TextTestRunner(verbosity=2,resultclass=ExecutionResult,stream=stream).run(suite)
            tests=python_result(result,expected)
    after=snapshot()
    status="PASS" if tests["status"] == "PASS" and before == after and not unraisable else "FAIL"
    packages={}
    for name in ("cryptography","cffi","pycparser","tzdata","websockets"):
        try:
            packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name]="NOT_INSTALLED"
    data=dict(kind="TP_OPTION_INTELLIGENCE_OFFLINE_CHECKPOINT",status=status,
        exit_code=0 if status == "PASS" else 1,source_head=source_head,started_at=started,
        completed_at=timestamp(),elapsed_seconds=round(time.monotonic()-clock,3),
        command=[sys.executable,"-B","-m","option_intelligence.verify","--receipt",receipt.relative_to(APP).as_posix()],
        cwd=str(APP),safe_flags=SAFE,external_network="BLOCKED",unraisable_errors=unraisable,
        python_version=sys.version,platform=platform.platform(),installed_packages=packages,
        modules=list(MODULES),module_counts={name:sum(item.startswith(name+".") for item in tests["executed_ids"]) for name in MODULES},
        tests=tests,source_before=before,source_after=after,
        log=log.relative_to(APP).as_posix(),log_sha256=digest(log),
        limitation="Supplied synthetic mechanics and selected regressions only; no broker, market, source-authority or execution acceptance.")
    receipt.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(dict(status=status,executed=tests["executed"],passed=tests["passed"],
        failures=tests["failures"],errors=tests["errors"],skipped=tests["skipped"],receipt=str(receipt))))
    return data["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
