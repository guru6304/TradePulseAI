"""Evidence must follow actual execution, including subtests and missing cases."""
import io
import socket
import json
import tempfile
from pathlib import Path
import unittest
from contextlib import ExitStack
from verify_offline import ExecutionResult, offline_network, python_result, source_snapshot, validate_evidence, digest, reserve_evidence


class TestVerificationEvidence(unittest.TestCase):
    def run_cases(self, cls):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(cls)
        expected = [case.id() for case in suite]
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=ExecutionResult).run(suite)
        return python_result(result, expected)

    def test_success_uses_executed_case_ids_instead_of_historical_count(self):
        class Fixture(unittest.TestCase):
            def test_observed(self):
                self.assertEqual(2+2, 4)
        result = self.run_cases(Fixture)
        self.assertEqual((result["status"], result["executed"], result["passed"]), ("PASS", 1, 1))

    def test_zero_cases_and_missing_case_never_pass(self):
        result = ExecutionResult(io.StringIO(), True, 1)
        self.assertEqual(python_result(result, ["missing.case"])["status"], "FAIL")
        self.assertEqual(python_result(result, [])["status"], "FAIL")

    def test_multiple_subtest_failures_are_not_counted_as_multiple_passed_cases(self):
        class Fixture(unittest.TestCase):
            def test_failures(self):
                for number in range(2):
                    with self.subTest(number=number):
                        self.fail("OFFLINE expected assertion")
        result = self.run_cases(Fixture)
        self.assertEqual((result["status"], result["executed"], result["passed"], result["failures"]),
                         ("FAIL", 1, 0, 2))

    def test_skip_is_not_strict_acceptance(self):
        class Fixture(unittest.TestCase):
            @unittest.skip("OFFLINE verification fixture")
            def test_skipped(self):
                pass
        self.assertEqual(self.run_cases(Fixture)["status"], "FAIL")

    def test_external_dns_is_blocked_before_any_broker_transport(self):
        with ExitStack() as stack:
            offline_network(stack)
            with self.assertRaisesRegex(OSError, "EXTERNAL_NETWORK_BLOCKED"):
                socket.getaddrinfo("api.upstox.com", 443)

    def test_failed_exit_and_unraisable_error_cannot_be_relabelled_pass(self):
        # Deliberately synthetic validator fixtures, never execution evidence.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"app.py").write_text("value=1\n", encoding="utf-8")
            (root/"python.txt").write_text("OFFLINE VALIDATOR FIXTURE\n", encoding="utf-8")
            before = source_snapshot(root)
            data = dict(kind="EXECUTED_OFFLINE_VERIFICATION", status="PASS", exit_code=0,
                source_before=before, source_after=before, unraisable_errors=[],
                python=dict(status="PASS", exit_code=0, executed=1, passed=1, expected_ids=["fixture"],
                    executed_ids=["fixture"], passed_ids=["fixture"], failures=0, errors=0, skipped=0,
                    expected_failures=0, unexpected_successes=0, log="python.txt"),
                checks=[dict(command=["node", "fixture.js"], exit_code=0, status="PASS", executed=1, passed=1, failures=0, skipped=0),
                        dict(command=["node", "--check", "fixture.js"], exit_code=0, status="PASS"),
                        dict(command="py_compile", exit_code=0, status="PASS", compiled_files=1)],
                logs={"python.txt": digest(root/"python.txt")})
            path = root/"evidence.json"
            for field, value in (("exit_code", 1), ("unraisable_errors", ["ResourceWarning"])):
                changed = dict(data, **{field:value})
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate_evidence(path, root)
            path.write_text(json.dumps(data), encoding="utf-8")
            validate_evidence(path, root)
            (root/"python.txt").write_text("CHANGED VALIDATOR FIXTURE\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_evidence(path, root)

    def test_evidence_rejects_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"app.py").write_text("value=1\n", encoding="utf-8")
            data = dict(kind="EXECUTED_OFFLINE_VERIFICATION", status="PASS", source_before=source_snapshot(root), source_after={})
            path = root/"evidence.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            (root/"app.py").write_text("value=2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_evidence(path, root)

    def test_windows_command_log_paths_match_normalized_manifest_paths(self):
        # Synthetic evidence shape: test portability, not actual execution proof.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"app.py").write_text("value=1\n", encoding="utf-8")
            (root/"requirements.txt").write_text("cryptography==50.0.2\n",encoding="utf-8")
            logs = {}
            for name in ("python", "node", "syntax"):
                local = root/"docs/evidence"/(name+".txt")
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text("OFFLINE VALIDATOR FIXTURE\n", encoding="utf-8")
                logs[local.relative_to(root).as_posix()] = digest(local)
            sources = source_snapshot(root)
            data = dict(kind="EXECUTED_OFFLINE_VERIFICATION", status="PASS", exit_code=0,
                source_before=sources, source_after=sources, unraisable_errors=[],
                python=dict(status="PASS", exit_code=0, executed=1, passed=1, expected_ids=["fixture"],
                    executed_ids=["fixture"], passed_ids=["fixture"], failures=0, errors=0, skipped=0,
                    expected_failures=0, unexpected_successes=0, log="docs/evidence/python.txt"),
                checks=[dict(command=["node", "fixture.js"], exit_code=0, status="PASS", executed=1,
                            passed=1, failures=0, skipped=0, log="docs\\evidence\\node.txt"),
                        dict(command=["node", "--check", "fixture.js"], exit_code=0, status="PASS",
                            log="docs\\evidence\\syntax.txt"),
                        dict(command="py_compile", exit_code=0, status="PASS", compiled_files=1)], logs=logs)
            path = root/"evidence.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(validate_evidence(path, root)["status"], "PASS")
            (root/"requirements.txt").write_text("cryptography==0\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"SOURCE_OR_STATUS"):
                validate_evidence(path,root)
            (root/"requirements.txt").write_text("cryptography==50.0.2\n",encoding="utf-8")
            (root/"docs/evidence/node.txt").write_text("TAMPERED", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_evidence(path, root)

    def test_concurrent_stage_reservation_never_clobbers_existing_evidence(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"nested"/"stage.json"
            def attempt(_):
                try:
                    reserve_evidence(path)
                    return True
                except FileExistsError:
                    return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(attempt, range(8))), 1)
            self.assertEqual(json.loads(path.read_text())["status"], "IN_PROGRESS")
