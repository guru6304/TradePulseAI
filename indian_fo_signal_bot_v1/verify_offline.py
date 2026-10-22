"""Run the established offline suite and retain execution-bound evidence.

No broker adapter or local credentials are loaded by this entry point. Unittest's
existing credential-free bootstrap owns test configuration. Outbound sockets are
blocked; only loopback test servers are permitted. No historical test count is a
success condition. A changed source tree makes an old result historical.
"""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import py_compile
import re
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import warnings

APP = Path(__file__).resolve().parent


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def reserve_evidence(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="IN_PROGRESS", started_at=timestamp()), stream)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(root=APP):
    files = list(root.glob("*.py")) + list(root.glob("test_*.js")) + list((root/"public").rglob("*")) + [root/"requirements.txt"]
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(files) if p.is_file()}


def case_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from case_ids(item)
        else:
            yield item.id()


class ExecutionResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids, self.passed_ids = [], []

    def startTest(self, test):
        self.started_ids.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.passed_ids.append(test.id())
        super().addSuccess(test)


def python_result(result, expected):
    actual = result.started_ids
    strict = (bool(expected) and len(expected) == len(set(expected)) and actual == expected
              and result.wasSuccessful() and not result.skipped and not result.expectedFailures
              and not result.unexpectedSuccesses and len(result.passed_ids) == len(expected))
    return dict(status="PASS" if strict else "FAIL", exit_code=0 if strict else 1,
        executed=result.testsRun, passed=len(result.passed_ids), failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
        unexpected_successes=len(result.unexpectedSuccesses), expected_ids=expected,
        executed_ids=actual, passed_ids=result.passed_ids)


def _loopback(host):
    if host in (None, "", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def offline_network(stack):
    original_lookup, original_connect = socket.getaddrinfo, socket.socket.connect
    def lookup(host, *args, **kwargs):
        if not _loopback(host):
            raise OSError("OFFLINE_VERIFICATION_EXTERNAL_NETWORK_BLOCKED")
        return original_lookup(host, *args, **kwargs)
    def connect(sock, address):
        if not isinstance(address, tuple) or not _loopback(address[0]):
            raise OSError("OFFLINE_VERIFICATION_EXTERNAL_NETWORK_BLOCKED")
        return original_connect(sock, address)
    stack.enter_context(patch("socket.getaddrinfo", side_effect=lookup))
    stack.enter_context(patch("socket.socket.connect", new=connect))


def run_command(command, log, cwd=APP):
    started = timestamp()
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=60)
        output = completed.stdout+completed.stderr
        code = completed.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        output, code = type(exc).__name__+"\n", 1
    log.write_text(output, encoding="utf-8")
    return dict(command=command, cwd=str(cwd), started_at=started, completed_at=timestamp(), exit_code=code,
                status="PASS" if code == 0 else "FAIL", log=log.relative_to(APP).as_posix())


def validate_evidence(path, root=APP):
    """Validate current source/log bindings, never infer execution from file names."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("kind") != "EXECUTED_OFFLINE_VERIFICATION" or data.get("status") != "PASS"
            or data.get("exit_code") != 0 or data.get("unraisable_errors")
            or data.get("source_before") != source_snapshot(root)
            or data.get("source_after") != data.get("source_before")):
        raise ValueError("EVIDENCE_SOURCE_OR_STATUS_MISMATCH")
    python = data["python"]
    if (python["status"] != "PASS" or python["exit_code"] != 0 or not python["executed"] or python["passed"] != python["executed"]
            or python["expected_ids"] != python["executed_ids"] or python["passed_ids"] != python["expected_ids"]
            or len(set(python["executed_ids"])) != python["executed"]
            or any(python[k] for k in ("failures", "errors", "skipped", "expected_failures", "unexpected_successes"))
            or any(r["exit_code"] != 0 or r["status"] != "PASS" for r in data["checks"])):
        raise ValueError("EVIDENCE_EXECUTION_MISMATCH")
    required_logs = {name.replace("\\", "/") for name in
                     ({python["log"]} | {r["log"] for r in data["checks"] if "log" in r})}
    if not required_logs.issubset(data["logs"]) or len(data["checks"])<3:
        raise ValueError("EVIDENCE_CHECKS_OR_LOGS_MISSING")
    for check in data["checks"]:
        command = check["command"]
        if isinstance(command, list) and command[0]=="node" and "--check" not in command:
            if not check.get("executed") or check.get("passed")!=check["executed"] or check.get("failures") or check.get("skipped"):
                raise ValueError("EVIDENCE_NODE_EXECUTION_MISMATCH")
    for name, value in data["logs"].items():
        local = (root/name).resolve()
        if not local.is_relative_to(root.resolve()) or digest(local) != value:
            raise ValueError("EVIDENCE_LOG_INTEGRITY_FAILURE")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="current")
    parser.add_argument("--validate-evidence", type=Path)
    args = parser.parse_args(argv)
    if args.validate_evidence:
        try:
            data = validate_evidence(args.validate_evidence)
            print(json.dumps(dict(status="PASS", executed=data["python"]["executed"], scope="OFFLINE_ONLY")))
            return 0
        except Exception as exc:
            print(json.dumps(dict(status="FAIL", reason_code=type(exc).__name__)))
            return 1
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.stage):
        parser.error("stage must be a short lowercase identifier")
    prefix = APP/"docs/evidence"/f"master_{args.stage}"
    # Keep past runs: an explicit new stage name is required for new evidence.
    evidence = prefix.with_suffix(".json")
    try:
        reserve_evidence(evidence)
    except FileExistsError:
        parser.error("evidence stage already exists; choose a new --stage")
    started, before = timestamp(), source_snapshot()
    unraisable = []
    logfile = prefix.with_name(prefix.name+"_python.txt")
    with logfile.open("w", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        stack.enter_context(patch("sys.unraisablehook", side_effect=lambda event: unraisable.append(type(event.exc_value).__name__)))
        warnings.simplefilter("error", ResourceWarning)
        suite = unittest.defaultTestLoader.loadTestsFromName("test_bot")
        expected = list(case_ids(suite))
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExecutionResult).run(suite)
        python = python_result(result, expected)
    python.update(command=[sys.executable, "-B", "-W", "error::ResourceWarning", "verify_offline.py", "--stage", args.stage],
                  runner="unittest.TextTestRunner(test_bot.load_tests)", cwd=str(APP), log=logfile.relative_to(APP).as_posix())
    checks = []
    node_log = prefix.with_name(prefix.name+"_node.txt")
    node = run_command(["node", "test_cash_dashboard.js"], node_log)
    output = node_log.read_text(encoding="utf-8")
    counts = {key: re.search(r"\b"+word+r" (\d+)\s*$", output, re.MULTILINE)
              for key, word in (("executed", "tests"), ("passed", "pass"), ("failures", "fail"), ("skipped", "skipped"))}
    if all(counts.values()):
        node.update({k: int(v[1]) for k, v in counts.items()})
        if not node["executed"] or node["passed"] != node["executed"] or node["failures"] or node["skipped"]:
            node["status"] = "FAIL"
    else:
        node["status"] = "FAIL"
    checks.append(node)
    checks.append(run_command(["node", "--check", "test_cash_dashboard.js"], prefix.with_name(prefix.name+"_syntax.txt")))
    files = sorted(APP.glob("*.py"))
    try:
        for file in files:
            py_compile.compile(str(file), doraise=True)
        checks.append(dict(command="py_compile.compile(root *.py, doraise=True)", cwd=str(APP),
                           exit_code=0, status="PASS", compiled_files=len(files)))
    except py_compile.PyCompileError:
        checks.append(dict(command="py_compile.compile(root *.py, doraise=True)", cwd=str(APP), exit_code=1, status="FAIL"))
    after = source_snapshot()
    passed = python["status"] == "PASS" and all(c["status"] == "PASS" for c in checks) and before == after and not unraisable
    data = dict(kind="EXECUTED_OFFLINE_VERIFICATION", scope="FIXTURE_MOCK_LOCAL_HTTP_NO_LIVE_ACCEPTANCE",
        stage=args.stage, started_at=started, completed_at=timestamp(), status="PASS" if passed else "FAIL",
        exit_code=0 if passed else 1, source_before=before, source_after=after, python=python, checks=checks,
        unraisable_errors=unraisable,
        logs={p.relative_to(APP).as_posix(): digest(p) for p in (logfile,node_log,prefix.with_name(prefix.name+"_syntax.txt"))})
    evidence.write_text(json.dumps(data, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(status=data["status"], tests=python["executed"], passed=python["passed"],
        failures=python["failures"], errors=python["errors"], skipped=python["skipped"], evidence=str(evidence))))
    return data["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
