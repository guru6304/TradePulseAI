"""Offline retained-evaluation traversal bounds without skipping nested references."""
import copy
import cProfile
import json
import os
import sys
import unittest
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]

from candle_lineage import digest, encoded
from storage import PersistenceValidationError


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


class TestAstraEvaluationReads(unittest.TestCase):
    def setUp(self):
        from test_astra_context_batch import TestAstraContextBatch
        # Reuse actual multi-candidate evaluator/storage setup in a private
        # in-memory database. Its source is explicitly simulated, not live proof.
        self.fixture = TestAstraContextBatch()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.store = self.fixture.store
        self.run_id = self.fixture.summary["run_id"]

    def retained(self):
        with self.store.lineage_read() as conn:
            row = conn.execute("SELECT payload_json,payload_sha256 FROM scan_evaluations WHERE run_id=?",
                               (self.run_id,)).fetchone()
            return tuple(row)

    def replace(self, payload):
        # Authored corruption/extension of genuine retained fixture evidence.
        # Rehashing is deliberate: structural validation must still run.
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE scan_evaluations SET payload_json=?,payload_sha256=? WHERE run_id=?",
                         (encoded(payload), digest(payload), self.run_id))

    def test_scalar_heavy_real_evaluation_traversal_is_container_bounded_and_read_only(self):
        original = self.retained()
        expected = json.loads(original[0])
        pending, containers, scalars = [expected], 0, 0
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                containers += 1
                pending.extend(value.values())
            elif isinstance(value, list):
                containers += 1
                pending.extend(value)
            else:
                scalars += 1
        self.assertGreater(scalars, 10000, "Use the real scalar-heavy candle-reference payload")
        profile = cProfile.Profile()
        with self.store.lineage_read() as conn:
            changes = conn.total_changes
            profile.enable()
            try:
                observed = self.store.load_scan_evaluations(self.run_id, connection=conn)
            finally:
                profile.disable()
            self.assertEqual(conn.total_changes, changes)
        self.assertEqual(observed, expected)
        self.assertEqual(self.retained(), original)
        traversals = sum(entry.callcount for entry in profile.getstats()
                         if hasattr(entry.code, "co_name") and entry.code.co_name == "references"
                         and entry.code.co_filename.replace("\\", "/").endswith("/candle_lineage.py"))
        print(f"EVALUATION_TRAVERSAL containers={containers} scalars={scalars} reference_calls={traversals}")
        self.assertGreater(traversals, 0)
        self.assertLessEqual(traversals, containers + 1,
                             "Scalar timestamp/measurement leaves must not incur recursive validation calls")

    def test_rehashed_invalid_references_inside_arbitrary_nested_extensions_reject(self):
        original = json.loads(self.retained()[0])
        bad_references = (
            {"run_id": "different-retained-run", "batch_ids": []},
            {"run_id": self.run_id, "batch_ids": ["unknown-batch"]},
            {"run_id": self.run_id, "batch_ids": "not-a-list"},
            "not-a-reference-object",
        )
        for reference in bad_references:
            with self.subTest(reference=reference):
                altered = copy.deepcopy(original)
                altered["vendor_extension"] = [7, "scalar", {"opaque": [None, [
                    {"unfamiliar": {"source_reference": reference}}]]}]
                self.replace(altered)
                retained = self.retained()
                with self.assertRaisesRegex(PersistenceValidationError, "SCAN_EVALUATION_INTEGRITY_FAILURE") as caught:
                    self.store.load_scan_evaluations(self.run_id)
                self.assertEqual(str(caught.exception.__cause__), "SCAN_EVALUATION_SCOPE_INVALID")
                self.assertEqual(self.retained(), retained)

    def test_valid_nested_reference_then_later_rehashed_corruption_is_rechecked(self):
        payload = json.loads(self.retained()[0])
        payload["vendor_extension"] = {"levels": ["scalar", {"source_reference": {
            "run_id": self.run_id, "batch_ids": [], "extra": [1, 2, {"source_reference": {
                "run_id": self.run_id, "batch_ids": []}}]}}]}
        self.replace(payload)
        original = self.retained()
        self.assertEqual(self.store.load_scan_evaluations(self.run_id), payload)
        self.assertEqual(self.retained(), original)
        payload["vendor_extension"]["levels"][1]["source_reference"]["extra"][2]["source_reference"]["run_id"] = "wrong-run"
        self.replace(payload)
        with self.assertRaisesRegex(PersistenceValidationError, "SCAN_EVALUATION_INTEGRITY_FAILURE") as caught:
            self.store.load_scan_evaluations(self.run_id)
        self.assertEqual(str(caught.exception.__cause__), "SCAN_EVALUATION_SCOPE_INVALID")


if __name__ == "__main__":
    unittest.main()
