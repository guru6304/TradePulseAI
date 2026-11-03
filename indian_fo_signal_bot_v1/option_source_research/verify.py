"""Guarded D2 mechanics receipt; no provider capture or qualification effects."""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from option_intelligence.verify import snapshot as approved_snapshot
from verify_offline import ExecutionResult, case_ids, digest, offline_network, python_result, timestamp
from .fixtures import example_vectors
from .mapping import map_synthetic_fixture

APP=Path(__file__).resolve().parents[1]
MODULES=("option_source_research.tests.test_decoder", "option_source_research.tests.test_mapping",
    "option_intelligence.tests.test_identity", "option_intelligence.tests.test_context",
    "option_intelligence.tests.test_quotes", "option_intelligence.tests.test_fitness",
    "option_intelligence.tests.test_compatibility")
SAFE=dict(ACTIVE_BROKER="paper_sim", TELEGRAM_DRY_RUN="true",
          ENABLE_BACKGROUND_SCHEDULER="false", PYTHONDONTWRITEBYTECODE="1")


def snapshot():
    result=approved_snapshot()
    paths=list((APP/"option_source_research").rglob("*.py"))+[APP/"option_source_research/.gitattributes"]
    for path in sorted(paths):
        result[path.relative_to(APP).as_posix()]=digest(path)
    return result


def validate(path):
    data=json.loads(path.read_text(encoding="utf-8"))
    tests=data["tests"]
    if (data["kind"]!="TP_D2_SOURCE_MAPPING_OFFLINE_RECEIPT" or data["status"]!="PASS"
            or data["exit_code"] or data["source_before"]!=snapshot()
            or data["source_before"]!=data["source_after"] or data["unraisable_errors"]
            or data["external_network"]!="BLOCKED" or data["safe_flags"]!=SAFE
            or data["modules"]!=list(MODULES) or tests["status"]!="PASS" or tests["exit_code"]
            or not tests["executed"] or tests["executed"]!=tests["passed"]
            or len(set(tests["executed_ids"]))!=tests["executed"]
            or tests["expected_ids"]!=tests["executed_ids"] or tests["executed_ids"]!=tests["passed_ids"]
            or any(tests[key] for key in ("failures","errors","skipped","expected_failures","unexpected_successes"))):
        raise ValueError("D2_SOURCE_OR_EXECUTION_MISMATCH")
    log=(APP/data["log"]).resolve()
    if not log.is_relative_to(APP) or digest(log)!=data["log_sha256"]:
        raise ValueError("D2_LOG_MISMATCH")
    expected_vectors=example_vectors()
    if len(data["vectors"])!=len(expected_vectors):
        raise ValueError("D2_VECTOR_COUNT_MISMATCH")
    for vector,(name,fixture,state,reason) in zip(data["vectors"],expected_vectors):
        mapped=map_synthetic_fixture(fixture,enabled=True)
        if (vector["name"]!=name or vector["fixture_sha256"]!=mapped.fixture_digest
                or vector["expected_state"]!=state or vector["expected_reason"]!=reason
                or vector["actual_state"]!=mapped.state or vector["reason_codes"]!=list(mapped.reason_codes)
                or any(vector[key] for key in ("source_qualified","prospective_ready","forward_entry_allowed"))):
            raise ValueError("D2_VECTOR_MISMATCH")
    return data


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt",type=Path)
    parser.add_argument("--validate",type=Path)
    args=parser.parse_args(argv)
    if args.validate:
        data=validate(args.validate.resolve())
        print(json.dumps(dict(status="PASS",executed=data["tests"]["executed"],scope="OFFLINE_SOURCE_AND_LOG_BOUND")))
        return 0
    if not args.receipt:
        parser.error("--receipt or --validate is required")
    receipt=args.receipt.resolve()
    if not receipt.is_relative_to(APP):
        parser.error("receipt must remain inside application workspace")
    log=receipt.with_suffix(".txt")
    if receipt.exists() or log.exists():
        parser.error("existing evidence cannot be overwritten; use a fresh suffix")
    receipt.parent.mkdir(parents=True,exist_ok=True)
    before, started, clock=snapshot(),timestamp(),time.monotonic()
    head=subprocess.run(["git","rev-parse","HEAD"],cwd=APP,capture_output=True,text=True,check=True).stdout.strip()
    with receipt.open("x",encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS",started_at=started),stream)
    unraisable=[]
    with log.open("x",encoding="utf-8",newline="\n") as stream:
        with ExitStack() as guards,redirect_stdout(stream),redirect_stderr(stream):
            offline_network(guards)
            guards.enter_context(patch.dict(os.environ,SAFE))
            guards.enter_context(patch.object(sys,"unraisablehook",lambda item:unraisable.append(type(item.exc_value).__name__)))
            import test_bot  # existing credential-free bootstrap, no private .env
            guards.enter_context(patch.dict(os.environ,SAFE))
            suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES)
            expected=list(case_ids(suite))
            result=unittest.TextTestRunner(verbosity=2,stream=stream,resultclass=ExecutionResult).run(suite)
            tests=python_result(result,expected)
            vectors=[]
            for name,fixture,state,reason in example_vectors():
                mapped=map_synthetic_fixture(fixture,enabled=True)
                vectors.append(dict(name=name,fixture_sha256=mapped.fixture_digest,
                    expected_state=state,actual_state=mapped.state,expected_reason=reason,
                    reason_codes=list(mapped.reason_codes),source_qualified=mapped.source_qualified,
                    prospective_ready=mapped.prospective_ready,forward_entry_allowed=mapped.forward_entry_allowed))
    after=snapshot()
    vector_ok=all(item["expected_state"]==item["actual_state"] and item["expected_reason"] in item["reason_codes"]
                  and not any(item[key] for key in ("source_qualified","prospective_ready","forward_entry_allowed")) for item in vectors)
    status="PASS" if tests["status"]=="PASS" and before==after and not unraisable and vector_ok else "FAIL"
    data=dict(kind="TP_D2_SOURCE_MAPPING_OFFLINE_RECEIPT",status=status,exit_code=0 if status=="PASS" else 1,
        command=[sys.executable,"-B","-m","option_source_research.verify","--receipt",receipt.relative_to(APP).as_posix()],
        cwd=str(APP),source_head=head,started_at=started,completed_at=timestamp(),elapsed_seconds=round(time.monotonic()-clock,3),
        python_version=sys.version,safe_flags=SAFE,external_network="BLOCKED",unraisable_errors=unraisable,
        modules=list(MODULES),module_counts={name:sum(item.startswith(name+".") for item in tests["executed_ids"]) for name in MODULES},
        tests=tests,vectors=vectors,source_before=before,source_after=after,
        log=log.relative_to(APP).as_posix(),log_sha256=digest(log),real_captures=0,
        limitation="Synthetic mapping and selected supplied-input regressions; no source qualification, entitlement or market acceptance.")
    receipt.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(dict(status=status,executed=tests["executed"],passed=tests["passed"],failures=tests["failures"],errors=tests["errors"],skipped=tests["skipped"])))
    return data["exit_code"]


if __name__=="__main__":
    raise SystemExit(main())
