"""Isolated engineering tests of the operator evidence helper; no real acceptance."""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict
import gc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
import verify_offline as verification

HELPER = APP / "docs/evidence/task3_completion_track_a_20261023_01_verify.py"
spec = importlib.util.spec_from_file_location("task3_operator_helper", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class TestOperatorHelper(unittest.TestCase):
    def setUp(self):
        from test_historical_study import TestHistoricalStudy
        from publisher_trust import TRUST_POLICY_VERSION
        self.fixture = TestHistoricalStudy()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.temporary = tempfile.TemporaryDirectory(prefix="TRADEPULSE_TEST_ONLY_HELPER_")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.operator = self.base / "source", self.base / "operator"
        self.source.mkdir()
        self.operator.mkdir()
        self.bars = self.fixture.bars("LIVE")
        self.raw = helper.json.dumps(dict(schema_version="tradepulse.cash-observations.v1", candles=self.bars)).encode()
        self.write(self.source / "cash_observations.json", self.raw)
        f = self.fixture.fixture
        self.write(self.source / "cash_manifest.json", json.dumps(f._build_manifest(self.raw, instrument_scope="RELIANCE",
            artifact_type="cash-observations", artifact_schema_version="tradepulse.cash-observations.v1")).encode())
        self.write(self.source / "instrument_master.json", self.fixture.raw)
        self.write(self.source / "master_manifest.json", json.dumps(f._build_manifest(self.fixture.raw, instrument_scope="RELIANCE",
            publisher_publication_time="2026-10-01T00:00:00+00:00", capture_observation_time="2026-10-01T00:05:00+00:00")).encode())
        self.plan = dict(schema_version="tradepulse.local-cash-study.v1", provider="angelone", symbol="RELIANCE",
            instrument_token="2885", strategy_id="strat_1_order_block", training_sessions=2, test_sessions=1,
            backtest_config=asdict(__import__("backtest_engine").BacktestConfig()))
        self.write_json(self.source / "study_plan.json", self.plan)
        self.trust = dict(policy_version=TRUST_POLICY_VERSION, anchors=self.fixture.engine.publisher_trust_config._anchors)
        self.write_json(self.operator / "publisher_trust.json", self.trust)
        self.document = self.fixture.document
        self.write(self.operator / "rights.pdf", self.document)
        grant = dict(self.fixture.grant, artifact_sha256s=[helper.sha(self.raw), helper.sha(self.fixture.raw)])
        self.rights = dict(grants=[grant], documents={helper.sha(self.document): "rights.pdf"})
        self.write_json(self.operator / "rights_policy.json", self.rights)
        self.args = argparse.Namespace(input_root=self.source, operator_policy=self.operator,
            run_cash_study=False, private_db=None)

    def write(self, path, raw):
        path.write_bytes(raw)

    def write_json(self, path, value):
        self.write(path, json.dumps(value).encode())

    def check(self):
        return helper.evaluate(self.args)[0]

    def test_test_only_approved_shapes_validate_exact_identity_without_database(self):
        result = self.check()
        self.assertEqual(result["identity_status"], "RESOLVED_DATED_AUTHENTIC_IDENTITY")
        self.assertEqual(result["quality_status"], "COMPLETE_VERIFIED")
        self.assertTrue(all(row["allowed"] for row in result["publisher_qualifications"]))
        self.assertIsNone(result["study"])
        self.assertFalse(list(self.base.rglob("*.sqlite3")))

    def test_revoked_key_cannot_verify_sources(self):
        self.trust["anchors"][0]["revoked"] = True
        self.write_json(self.operator / "publisher_trust.json", self.trust)
        self.assertFalse(any(row["publisher_verified"] for row in self.check()["publisher_qualifications"]))

    def test_missing_rights_document_cannot_establish_scope(self):
        (self.operator / "rights.pdf").unlink()
        self.assertFalse(any(row["rights_verified"] for row in self.check()["publisher_qualifications"]))

    def test_rights_document_escape_rejected_before_reading(self):
        self.rights["documents"][helper.sha(self.document)] = "../outside-private-file.pdf"
        self.write_json(self.operator / "rights_policy.json", self.rights)
        with self.assertRaises(ValueError):
            self.check()
        with self.assertRaises(ValueError):
            helper.contained(self.operator, str(self.base / "outside"))

    def test_signed_source_cannot_be_substituted_or_wrong_cash_identity_accepted(self):
        self.plan["instrument_token"] = "999999"
        self.write_json(self.source / "study_plan.json", self.plan)
        self.assertEqual(self.check()["identity_status"], "REJECTED")
        self.write(self.source / "cash_observations.json", self.raw + b" ")
        self.assertFalse(self.check()["publisher_qualifications"][0]["publisher_verified"])

    def test_private_database_escape_is_rejected(self):
        self.args.run_cash_study = True
        self.args.private_db = self.base / "outside.sqlite3"
        with self.assertRaises(ValueError):
            self.check()
        self.assertFalse(self.args.private_db.exists())

    def test_fixture_only_private_study_persists_actual_original_inputs_and_result(self):
        self.args.run_cash_study = True
        self.args.private_db = self.operator / "study.sqlite3"
        result = self.check()["study"]
        self.assertEqual(result["status"], "QUALIFIED_REPRODUCIBLE_BOUNDED_STUDY")
        from historical_study import HistoricalEvidenceArchive
        from storage import SQLitePersistenceStore
        with SQLitePersistenceStore(str(self.args.private_db)) as store:
            saved = HistoricalEvidenceArchive(store).load(result["input_evidence_id"])
            self.assertEqual(saved["artifacts"]["cash_dataset"], self.raw)
            self.assertTrue(HistoricalEvidenceArchive(store).load(result["result_evidence_id"]))


before = verification.source_snapshot(APP)
unraisable = []
log = APP / "docs/evidence/task3_completion_track_a_20261023_01_helper_tests.txt"
with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
    verification.offline_network(stack)
    stack.enter_context(patch("sys.unraisablehook", side_effect=lambda event: unraisable.append(type(event.exc_value).__name__)))
    compile(HELPER.read_text(encoding="utf-8"), str(HELPER), "exec")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestOperatorHelper)
    expected = list(verification.case_ids(suite))
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=verification.ExecutionResult).run(suite)
    elapsed = time.monotonic() - started
    details = verification.python_result(result, expected)
    gc.collect()
after = verification.source_snapshot(APP)
passed = details["status"] == "PASS" and before == after and not unraisable
receipt = dict(scope="ISOLATED_TEST_ONLY_OPERATOR_HELPER_ENGINEERING_NO_REAL_SOURCE_OR_RIGHTS_ACCEPTANCE",
    status="PASS" if passed else "FAIL", exit_code=0 if passed else 1,
    command=[sys.executable, "-B", "-W", "error::ResourceWarning", str(Path(__file__).relative_to(APP))],
    python=details, duration_seconds=round(elapsed, 3), source_before=before, source_after=after,
    source_unchanged=before == after, unraisable_errors=unraisable,
    helper_sha256=helper.sha(HELPER.read_bytes()), helper_syntax="PASS",
    log_path=log.relative_to(APP).as_posix(), log_sha256=helper.sha(log.read_bytes()),
    real_source_or_study_acceptance_claimed=False)
target = APP / "docs/evidence/task3_completion_track_a_20261023_01_helper_tests.json"
with target.open("x", encoding="utf-8") as handle:
    json.dump(receipt, handle, indent=2)
    handle.write("\n")
print(json.dumps(dict(status=receipt["status"], python=details["executed"], passed=details["passed"],
    failures=details["failures"], errors=details["errors"], duration_seconds=receipt["duration_seconds"],
    receipt=target.relative_to(APP).as_posix())))
sys.exit(receipt["exit_code"])
