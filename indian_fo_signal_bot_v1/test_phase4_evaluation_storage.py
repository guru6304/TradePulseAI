"""Offline explanation persistence/integrity; fixtures confer no source authority."""
import copy
import unittest
from unittest.mock import patch

import test_bot  # Credential-free offline bootstrap.
import test_cash_lineage as lineage_fixtures
from candle_lineage import annotate_signals, digest, encoded
from storage import SQLitePersistenceStore, PersistenceError, PersistenceValidationError


class TestPhase4EvaluationStorage(unittest.TestCase):
    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)

    def record(self, run="run"):
        self.store.record_scan_run(run, "2026-10-16T14:15:05+05:30", None, 0,
                                   "COMPLETE", "upstox", "LIVE", False)

    def payload(self, run="run"):
        ref = dict(run_id=run, batch_ids=[], source_authenticity="NOT_ESTABLISHED")
        return dict(schema_version="tradepulse.scan-evaluation.v1", run_id=run,
            data_mode="LIVE", actionable=False,
            strategy_evaluations=[dict(strategy_id="S1", source_reference=copy.deepcopy(ref))],
            candidate_evaluations=[dict(candidate_id="candidate", actionable=False,
                status="QUALIFIED", source_reference=copy.deepcopy(ref))])

    def commit_empty(self):
        self.store.prepare_cash_scan("run", lineage_fixtures.TestCashLineage().snapshot())
        payload = self.payload()
        summary = dict(run_id="run", scan_status="COMPLETE", total_signals=0,
            persisted_signals=0, duplicate_signals=0, persistence_status="OK", signals=[],
            broker="upstox", data_mode="LIVE", actionable=False,
            strategy_evaluations=payload["strategy_evaluations"],
            candidate_evaluations=payload["candidate_evaluations"])
        with self.store.scan_result_transaction():
            self.record()
            self.store.save_scan_evaluations("run", payload)
            self.store.finish_cash_scan("run", summary)
        return payload, summary

    def test_additive_schema_legacy_scan_and_candidate_have_no_evaluation(self):
        self.record()
        self.assertIsNone(self.store.load_scan_evaluations("run"))
        self.assertIsNone(self.store.query_scan_runs()["items"][0]["evaluation"])
        item = annotate_signals(self.store, [dict(scan_run_id="run", dedup_key="candidate")])[0]
        self.assertIsNone(item["candidate_evaluation"])
        self.assertFalse(item["actionable"])
        self.assertEqual(item["recommendation_status"], "CANDIDATE_ONLY")

    def test_idempotent_payload_is_immutable_and_api_candidate_matches_identity(self):
        self.record()
        payload = self.payload()
        self.assertEqual(self.store.save_scan_evaluations("run", payload), digest(payload))
        self.assertEqual(self.store.save_scan_evaluations("run", copy.deepcopy(payload)), digest(payload))
        self.assertEqual(self.store.query_scan_runs()["items"][0]["evaluation"], payload)
        items = annotate_signals(self.store, [dict(scan_run_id="run", dedup_key=key)
                                            for key in ("candidate", "other")])
        self.assertEqual(items[0]["candidate_evaluation"], payload["candidate_evaluations"][0])
        self.assertIsNone(items[1]["candidate_evaluation"])
        changed = copy.deepcopy(payload)
        changed["candidate_evaluations"][0]["status"] = "REJECTED"
        with self.assertRaisesRegex(PersistenceValidationError, "CONFLICT"):
            self.store.save_scan_evaluations("run", changed)
        self.assertEqual(self.store.load_scan_evaluations("run"), payload)

    def test_scope_authority_duplicate_id_foreign_batch_and_run_reject(self):
        self.record()
        mutations = [lambda p: p.update(run_id="other"), lambda p: p.update(actionable=True),
            lambda p: p.update(data_mode="SIMULATED"),
            lambda p: p["candidate_evaluations"][0].update(actionable=True),
            lambda p: p["candidate_evaluations"].append(copy.deepcopy(p["candidate_evaluations"][0])),
            lambda p: p["strategy_evaluations"][0]["source_reference"].update(run_id="other"),
            lambda p: p["candidate_evaluations"][0]["source_reference"].update(batch_ids=["foreign"])]
        for mutation in mutations:
            payload = self.payload()
            mutation(payload)
            with self.subTest(mutation=mutations.index(mutation)), self.assertRaises(PersistenceValidationError):
                self.store.save_scan_evaluations("run", payload)
            self.assertIsNone(self.store.load_scan_evaluations("run"))

    def test_missing_parent_and_nonfinite_or_oversize_json_reject(self):
        with self.assertRaises(PersistenceValidationError):
            self.store.save_scan_evaluations("run", self.payload())
        self.record()
        payload = self.payload()
        payload["candidate_evaluations"][0]["score"] = float("nan")
        with self.assertRaises(PersistenceValidationError):
            self.store.save_scan_evaluations("run", payload)
        with patch("candle_lineage.MAX_BYTES", 10), self.assertRaises(PersistenceValidationError):
            self.store.save_scan_evaluations("run", self.payload())
        self.assertIsNone(self.store.load_scan_evaluations("run"))

    def test_partial_legacy_source_reference_is_preserved_without_forged_fields(self):
        self.record()
        payload = self.payload()
        payload["candidate_evaluations"][0]["source_reference"] = {"provider": "offline"}
        self.store.save_scan_evaluations("run", payload)
        self.assertEqual(self.store.load_scan_evaluations("run"), payload)

    def test_outer_rollback_removes_scan_and_evaluation(self):
        with self.assertRaisesRegex(RuntimeError, "interruption"):
            with self.store.scan_result_transaction():
                self.record()
                self.store.save_scan_evaluations("run", self.payload())
                raise RuntimeError("offline interruption")
        self.assertEqual(self.store.query_scan_runs()["total_count"], 0)
        self.assertIsNone(self.store.load_scan_evaluations("run"))

    def test_swallowed_invalid_borrowed_write_still_rolls_back_outer_scan(self):
        with self.assertRaisesRegex(PersistenceError, "NESTED_WRITE_FAILED"):
            with self.store.scan_result_transaction():
                self.record()
                bad = self.payload()
                bad["actionable"] = True
                with self.assertRaises(PersistenceValidationError):
                    self.store.save_scan_evaluations("run", bad)
        self.assertEqual(self.store.query_scan_runs()["total_count"], 0)

    def test_checksum_corruption_fails_load_scan_query_and_candidate_annotation(self):
        self.record()
        self.store.save_scan_evaluations("run", self.payload())
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE scan_evaluations SET payload_sha256='corrupt'")
        for read in (lambda: self.store.load_scan_evaluations("run"), self.store.query_scan_runs,
                     lambda: annotate_signals(self.store, [dict(scan_run_id="run", dedup_key="candidate")])):
            with self.subTest(read=read), self.assertRaises((PersistenceError, PersistenceValidationError)):
                read()

    def test_durable_commit_checks_exact_evaluations_and_preserves_lineage(self):
        payload, summary = self.commit_empty()
        self.assertEqual(self.store.load_cash_scan("run")["result"], summary)
        self.assertEqual(self.store.load_scan_evaluations("run"), payload)
        item = annotate_signals(self.store, [dict(scan_run_id="run", dedup_key="candidate")])[0]
        self.assertEqual(item["lineage"]["status"], "COMMITTED")
        self.assertFalse(item["lineage"]["current_live_acceptance"])
        self.assertFalse(item["actionable"])

    def test_recomputed_checksum_cannot_change_durable_result_evaluation(self):
        payload, _ = self.commit_empty()
        payload["strategy_evaluations"][0]["strategy_id"] = "forged"
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE scan_evaluations SET payload_json=?,payload_sha256=?",
                         (encoded(payload), digest(payload)))
        for read in (lambda: self.store.load_scan_evaluations("run"),
                     lambda: self.store.load_cash_scan("run"), self.store.query_scan_runs):
            with self.subTest(read=read), self.assertRaises((PersistenceError, PersistenceValidationError)):
                read()

    def test_missing_evaluation_after_durable_commit_fails_result_integrity(self):
        self.commit_empty()
        with self.store.paper_transaction() as conn:
            conn.execute("DELETE FROM scan_evaluations")
        for read in (lambda: self.store.load_cash_scan("run"),
                     lambda: self.store.load_scan_evaluations("run"), self.store.query_scan_runs):
            with self.subTest(read=read), self.assertRaises((PersistenceError, PersistenceValidationError)):
                read()

    def test_finish_rejects_mismatched_list_and_transaction_remains_pending(self):
        self.store.prepare_cash_scan("run", lineage_fixtures.TestCashLineage().snapshot())
        with self.assertRaisesRegex(PersistenceValidationError, "OUTCOME_INTEGRITY"):
            with self.store.scan_result_transaction():
                self.record()
                self.store.save_scan_evaluations("run", self.payload())
                self.store.finish_cash_scan("run", dict(run_id="run", persistence_status="OK", signals=[],
                    scan_status="COMPLETE", strategy_evaluations=[], candidate_evaluations=[],
                    actionable=False, data_mode="LIVE"))
        self.assertEqual(self.store.load_cash_scan("run")["status"], "PENDING")
        self.assertEqual(self.store.query_scan_runs()["total_count"], 0)
        self.assertIsNone(self.store.load_scan_evaluations("run"))


if __name__ == "__main__":
    unittest.main()
