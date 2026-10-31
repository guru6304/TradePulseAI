"""Bounded OI contract-status diagnostic using existing authored fixture constructors."""
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[2]
OUTPUT = APP / "docs/evidence/astra_d01_contract_status_probe_20261028_01.json"
SOURCE = ("option_observations.py", "instrument_identity.py", "config.py", "test_option_observations.py")
sys.path.insert(0, str(APP))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes():
    return {name: sha(APP / name) for name in SOURCE}


def main():
    assert not OUTPUT.exists(), "unique evidence file required"
    started = datetime.now(timezone.utc).isoformat()
    before = hashes()
    forbidden_attempts = []

    def guard(event, arguments):
        forbidden = event in ("socket.connect", "sqlite3.connect")
        if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(arguments[0]))
            forbidden = path.name == ".env" or path.suffix.lower() in (".db", ".sqlite", ".sqlite3") or path.name.endswith(("-wal", "-shm"))
        if forbidden:
            forbidden_attempts.append(event)
            raise RuntimeError("DIAGNOSTIC_FORBIDDEN_IO")

    sys.addaudithook(guard)
    # Match the existing offline suite's dotenv isolation without importing its
    # application bootstrap. No process setting value is copied into evidence.
    config_tree = ast.parse((APP / "config.py").read_text(encoding="utf-8"))
    defaults = {node.args[0].value: ast.literal_eval(node.args[1])
        for node in ast.walk(config_tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os" and node.func.attr == "getenv" and len(node.args) == 2}
    original_exists = os.path.exists
    with patch.dict(os.environ, defaults, clear=True), patch("os.path.exists",
            side_effect=lambda path: False if Path(path).name == ".env" else original_exists(path)):
        from instrument_identity import CONTRACT_MASTER_SCHEMA, prepare_contract_master, validate_contract_identity
        from option_observations import ObservationError, compare_oi

        # Reuse the exact existing fixture method ASTs, not the module's top-level
        # test_bot import. No strategy/scanner/broker/HTTP application is imported.
        tree = ast.parse((APP / "test_option_observations.py").read_text(encoding="utf-8"))
        methods = {
            "TestOptionObservations": {"setUp", "make_master"},
            "TestOptionOIObservations": {"setUp", "compare"},
        }
        classes = []
        locators = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in methods:
                node.body = [method for method in node.body if isinstance(method, ast.FunctionDef)
                    and method.name in methods[node.name]]
                assert {method.name for method in node.body} == methods[node.name]
                assert not node.decorator_list and all(not method.decorator_list for method in node.body)
                locators.extend(dict(class_name=node.name, method=method.name, line=method.lineno)
                    for method in node.body)
                classes.append(node)
        assert len(classes) == 2
        namespace = dict(unittest=unittest, copy=copy, json=json,
            CONTRACT_MASTER_SCHEMA=CONTRACT_MASTER_SCHEMA,
            prepare_contract_master=prepare_contract_master, compare_oi=compare_oi)
        exec(compile(ast.Module(body=classes, type_ignores=[]), str(APP / "test_option_observations.py"), "exec"), namespace)
        fixture_type = namespace["TestOptionOIObservations"]
        cases = []
        variants = (
            ("active_control", (), None),
            ("missing_current_status", ("current",), "REMOVE"),
            ("missing_baseline_status", ("baseline",), "REMOVE"),
            ("missing_both_statuses", ("current", "baseline"), "REMOVE"),
            ("explicit_unknown_current_status", ("current",), "UNKNOWN"),
            ("explicit_unknown_baseline_status", ("baseline",), "UNKNOWN"),
            ("explicit_inactive_current_status", ("current",), "INACTIVE"),
            ("explicit_null_current_status", ("current",), None),
        )
        for name, targets, value in variants:
            fixture = fixture_type()
            fixture.setUp()
            for target in targets:
                identity = getattr(fixture, target)["identity"]
                if value == "REMOVE":
                    del identity["contract_status"]
                else:
                    identity["contract_status"] = value
            inputs = copy.deepcopy((fixture.current, fixture.baseline))
            result = dict(name=name, mutated_inputs=list(targets),
                mutation="REMOVE_CONTRACT_STATUS" if value == "REMOVE" else "SET_CONTRACT_STATUS" if targets else "NONE",
                status_value=None if value == "REMOVE" else value,
                input_sha256=hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest())
            normalized = []
            for target in targets:
                identity = getattr(fixture, target)["identity"]
                try:
                    normalized.append(dict(input=target, returned_status=validate_contract_identity(identity,
                        provider=identity["provider"])["contract_status"]))
                except Exception as exc:
                    normalized.append(dict(input=target, exception_type=type(exc).__name__))
            result["identity_validator"] = normalized
            try:
                output = fixture.compare()
                result.update(returned=True, comparison_status=output["status"], delta=output["delta"],
                    actionable=output["actionable"], eligible=output["eligible"],
                    historical_replay_allowed=output["historical_replay_allowed"])
            except Exception as exc:
                result.update(returned=False, exception_type=type(exc).__name__,
                    error_code=getattr(exc, "code", None),
                    missing_key=str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else None)
            result["inputs_unchanged"] = inputs == (fixture.current, fixture.baseline)
            result["contract_satisfied"] = (result.get("returned") is True and result.get("delta") == 200
                and result.get("actionable") is False and result.get("eligible") is False) if name == "active_control" else (
                result.get("returned") is False and result.get("exception_type") == "ObservationError")
            cases.append(result)
        assert not any(name in sys.modules for name in ("test_bot", "brokers", "scanner_engine", "telegram_bot", "server"))
    after = hashes()
    leaks = [case["name"] for case in cases if case.get("exception_type") == "KeyError"]
    expected_leaks = ["missing_current_status", "missing_baseline_status", "missing_both_statuses"]
    diagnostic_completed = (before == after and not forbidden_attempts and leaks == expected_leaks
        and all(case["inputs_unchanged"] for case in cases)
        and all(case["contract_satisfied"] for case in cases if case["name"] not in expected_leaks))
    receipt = dict(schema_version="tradepulse.oi-contract-status-diagnostic.v1",
        status="DEFECT_REPRODUCED" if diagnostic_completed else "DIAGNOSTIC_INCONCLUSIVE",
        diagnostic_execution="PASS" if diagnostic_completed else "FAIL",
        scope="PURE_AUTHORED_FIXTURE_EXCEPTION_BOUNDARY_NOT_PROVIDER_OR_EXECUTION_ACCEPTANCE",
        started_at=started, completed_at=datetime.now(timezone.utc).isoformat(),
        command=[str(Path(sys.executable)), "-B", "-W", "error::ResourceWarning", str(Path(__file__).relative_to(APP))],
        helper_sha256=sha(Path(__file__)), source_sha256_before=before, source_sha256_after=after,
        source_unchanged=before == after, fixture_methods=locators,
        fixture_module_imported=False, fixture_method_ast_executed=True,
        environment_files_read=False, operational_database_accessed=False, provider_requests=0,
        forbidden_io_attempts=forbidden_attempts, production_or_test_changes=False, full_suite_executed=False,
        case_count=len(cases), contract_satisfied_count=sum(case["contract_satisfied"] for case in cases),
        cases=cases, leaked_keyerror_cases=leaks,
        finding="Missing contract_status normalizes to UNKNOWN, but compare_oi ignores that normalized result and indexes the absent raw key.",
        minimal_regression="Delete contract_status separately from current and baseline identity; require ObservationError and immutable inputs. Keep ACTIVE control and explicit UNKNOWN rejection.",
        possible_minimal_fix="Use identity.get('contract_status') for the ACTIVE requirement, or retain validated normalized identity for checks without losing separately required source_revision or changing raw equality/hash semantics.",
        safety_boundary="The defect raises before delta output; no actionable result or provider access was observed.")
    with OUTPUT.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=receipt["status"], diagnostic_execution=receipt["diagnostic_execution"],
        cases=len(cases), contract_satisfied=receipt["contract_satisfied_count"], leaked_keyerror_cases=leaks,
        source_unchanged=before == after)))
    return 0 if diagnostic_completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
