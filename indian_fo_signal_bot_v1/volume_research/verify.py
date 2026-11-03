"""Reproducible offline checkpoint runner; never starts an application runtime.

Uses the established credential-free bootstrap and outbound-network guard.
Receipts and logs are created exclusively, preserving earlier execution evidence.
"""
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
                            python_result, source_snapshot, timestamp)

APP = Path(__file__).resolve().parents[1]
MODULES = (
    "test_volume_primitives", "test_volume_execution", "test_volume_retest",
    "test_phase4_strategy", "test_astra_research", "test_market_data_contract",
    "test_cash_lineage", "test_astra_ranking", "test_astra_rank_history",
    "test_h1_paper_conflicts",
)
SAFE = dict(ACTIVE_BROKER="paper_sim", TELEGRAM_DRY_RUN="true",
            ENABLE_BACKGROUND_SCHEDULER="false", PYTHONDONTWRITEBYTECODE="1")


def snapshot():
    files = source_snapshot(APP)
    for path in sorted((APP / "volume_research").rglob("*.py")):
        files[path.relative_to(APP).as_posix()] = digest(path)
    manifest = APP / "docs/research/TP_VOLUME_EXPERIMENT_MANIFEST_V1.json"
    files[manifest.relative_to(APP).as_posix()] = digest(manifest)
    return files


def validate(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    result = data["python"]
    if (data["kind"] != "TRADEPULSE_VOLUME_OFFLINE_CHECKPOINT"
            or data["status"] != "PASS" or data["exit_code"] != 0
            or data["source_before"] != data["source_after"]
            or data["source_before"] != snapshot()
            or data["unraisable_errors"] or data["external_network"] != "BLOCKED"
            or data["safe_flags"] != SAFE or data["modules"] != list(MODULES)
            or result["status"] != "PASS" or result["exit_code"] != 0
            or not result["executed"] or result["executed"] != result["passed"]
            or len(set(result["expected_ids"])) != result["executed"]
            or result["expected_ids"] != result["executed_ids"]
            or result["executed_ids"] != result["passed_ids"]
            or any(result[n] for n in ("failures", "errors", "skipped",
                                       "expected_failures", "unexpected_successes"))):
        raise ValueError("CHECKPOINT_SOURCE_OR_EXECUTION_MISMATCH")
    log = (APP / data["log"]).resolve()
    if not log.is_relative_to(APP) or digest(log) != data["log_sha256"]:
        raise ValueError("CHECKPOINT_LOG_MISMATCH")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args(argv)
    if args.validate:
        data = validate(args.validate.resolve())
        print(json.dumps(dict(status="PASS", executed=data["python"]["executed"],
                              scope="OFFLINE_SOURCE_AND_LOG_BOUND")))
        return 0
    if not args.receipt:
        parser.error("--receipt or --validate is required")
    receipt = args.receipt.resolve()
    if not receipt.is_relative_to(APP):
        parser.error("receipt must remain within the application workspace")
    log = receipt.with_suffix(".txt")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    # Both paths checked before reserving either. Never replace old evidence.
    if receipt.exists() or log.exists():
        parser.error("receipt/log already exists; choose a fresh run suffix")
    started = timestamp()
    before = snapshot()
    source_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=APP,
        check=True, capture_output=True, text=True).stdout.strip()
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS", started_at=started), stream)
    clock = time.monotonic()
    unraisable = []
    with log.open("x", encoding="utf-8", newline="\n") as stream:
        with ExitStack() as guards, redirect_stdout(stream), redirect_stderr(stream):
            offline_network(guards)
            guards.enter_context(patch.dict(os.environ, SAFE))
            guards.enter_context(patch.object(sys, "unraisablehook",
                lambda event: unraisable.append(type(event.exc_value).__name__)))
            import test_bot  # noqa: F401; established defaults, no private .env
            guards.enter_context(patch.dict(os.environ, SAFE))
            suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
            expected = list(case_ids(suite))
            result = unittest.TextTestRunner(verbosity=2, resultclass=ExecutionResult,
                                            stream=stream).run(suite)
            result_data = python_result(result, expected)
    after = snapshot()
    status = ("PASS" if result_data["status"] == "PASS" and before == after
              and not unraisable else "FAIL")
    packages = {}
    for name in ("cryptography", "cffi", "pycparser", "tzdata", "websockets"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "NOT_INSTALLED"
    counts = {}
    for name in MODULES:
        ids = [value for value in result_data["executed_ids"] if value.startswith(name+".")]
        counts[name] = len(ids)
    data = dict(kind="TRADEPULSE_VOLUME_OFFLINE_CHECKPOINT", status=status,
        exit_code=0 if status == "PASS" else 1, started_at=started,
        completed_at=timestamp(), elapsed_seconds=round(time.monotonic()-clock, 3),
        command=[sys.executable, "-B", "-m", "volume_research.verify", "--receipt",
                 receipt.relative_to(APP).as_posix()], cwd=str(APP), source_head=source_head,
        safe_flags=SAFE, external_network="BLOCKED", execution_mode="OFFLINE_ONLY",
        python_version=sys.version, platform=platform.platform(), installed_packages=packages,
        modules=list(MODULES), module_test_counts=counts, python=result_data,
        source_before=before, source_after=after, unraisable_errors=unraisable,
        log=log.relative_to(APP).as_posix(), log_sha256=digest(log),
        limitation="Synthetic mechanics and selected baseline only; no market, performance or activation acceptance.")
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(dict(status=status, executed=result_data["executed"],
        passed=result_data["passed"], failures=result_data["failures"],
        errors=result_data["errors"], skipped=result_data["skipped"], receipt=str(receipt))))
    return data["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
