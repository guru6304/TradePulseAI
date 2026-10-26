"""Offline context batch integrity and bounded repeated validation regressions."""
import copy
import json
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta
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


class TestAstraContextBatch(unittest.TestCase):
    def setUp(self):
        from brokers import MultiBrokerScanner, SimulatedNSEAdapter
        from config import BotConfig
        from scanner_engine import IntradayBotEngine
        from strategies import IST
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        config = BotConfig(active_broker="paper_sim", telegram_dry_run=True,
            database_url=":memory:", enable_background_scheduler=False)
        clock = lambda: self.now
        scanner = MultiBrokerScanner(config, clock=clock)
        scanner.adapters["paper_sim"] = _fixtures._BidirectionalFixtureAdapter(
            SimulatedNSEAdapter(seed=42, clock=clock))
        self.engine = IntradayBotEngine(config, clock=clock, broker_scanner=scanner)
        self.addCleanup(self.engine.close)
        self.store = self.engine.store
        # Isolate the post-scan context operation while retaining real scanner
        # decisions and native persistence. No context or signal is fabricated.
        with patch.object(self.engine, "_attach_context"):
            self.summary = self.engine.run_single_scan()
        self.assertEqual(self.summary["scan_status"], "COMPLETED")
        self.assertGreater(len(self.summary["candidate_evaluations"]), 1)

    def snapshot(self):
        return self.store.enrich_scan_context(self.summary["run_id"])

    def enqueue(self, snapshot, reference=None):
        return self.store.enqueue_context_alerts(self.summary["run_id"], snapshot, reference or self.now)

    def counts(self):
        with self.store.paper_transaction(write=False) as conn:
            return tuple(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                         for table in ("context_alert_decisions", "notification_outbox"))

    def test_actual_multicandidate_enrichment_validates_source_once_per_batch(self):
        import candle_lineage
        import context_workflow
        with patch("context_workflow._snapshot", wraps=context_workflow._snapshot) as reconstruct, \
                patch("candle_lineage.validate_scan_evaluations", wraps=candle_lineage.validate_scan_evaluations) as validate:
            result = self.engine.enrich_context(self.summary["run_id"])
        self.assertEqual(len(result["alert_decisions"]), len(self.summary["candidate_evaluations"]))
        self.assertTrue(all(row["status"] == "UNAVAILABLE" for row in result["alert_decisions"]))
        # One load for constructing the context and one fresh transactional load
        # for all alert decisions. Work must not grow per candidate validation.
        self.assertEqual(dict(context_reconstructions=reconstruct.call_count,
                              evaluation_validations=validate.call_count),
                         dict(context_reconstructions=2, evaluation_validations=2))

    def test_duplicate_batch_preserves_exact_decisions_order_and_row_counts(self):
        snapshot = self.snapshot()
        first = self.enqueue(snapshot)
        counts = self.counts()
        self.assertEqual([row["candidate_id"] for row in first],
                         [row["candidate_id"] for row in snapshot["candidate_contexts"]])
        self.assertTrue(all(row["status"] == "UNAVAILABLE" for row in first))
        self.assertEqual(counts, (len(snapshot["candidate_contexts"]), 0))
        self.assertEqual(self.enqueue(snapshot, self.now + timedelta(seconds=1)), first)
        self.assertEqual(self.counts(), counts)

    def test_rehashed_context_change_after_batch_is_revalidated_on_next_call(self):
        snapshot = self.snapshot()
        self.enqueue(snapshot)
        counts = self.counts()
        altered = copy.deepcopy(snapshot)
        altered["candidate_contexts"][0]["reason_codes"] = ["FORGED_BETWEEN_REQUESTS"]
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("UPDATE scan_context_snapshots SET payload_json=?,payload_digest=? WHERE snapshot_id=?",
                         (encoded(altered), digest(altered), snapshot["snapshot_id"]))
        # Even a caller presenting the newly rehashed content cannot confer
        # authority that disagrees with the raw-source reconstruction.
        with self.assertRaises(PersistenceValidationError):
            self.enqueue(altered)
        self.assertEqual(self.counts(), counts)

    def test_rehashed_evaluation_change_after_batch_invalidates_context_source(self):
        snapshot = self.snapshot()
        self.enqueue(snapshot)
        counts = self.counts()
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM scan_evaluations WHERE run_id=?",
                               (self.summary["run_id"],)).fetchone()
            evaluation = json.loads(row[0])
            evaluation["candidate_evaluations"][0]["rationale"] = "FORGED_BETWEEN_REQUESTS"
            conn.execute("UPDATE scan_evaluations SET payload_json=?,payload_sha256=? WHERE run_id=?",
                         (encoded(evaluation), digest(evaluation), self.summary["run_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.enqueue(snapshot)
        self.assertEqual(self.counts(), counts)

    def test_duplicate_batch_recomputes_every_preexisting_decision(self):
        snapshot = self.snapshot()
        decisions = self.enqueue(snapshot)
        counts = self.counts()
        altered = dict(decisions[-1], reason_code="FORGED_SUPPRESSION")
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("UPDATE context_alert_decisions SET payload_json=?,payload_digest=? WHERE decision_id=?",
                         (encoded(altered), digest(altered), altered["decision_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.enqueue(snapshot)
        self.assertEqual(self.counts(), counts)

    def test_second_decision_insert_failure_rolls_back_entire_batch_then_retries(self):
        snapshot = self.snapshot()
        before = self.counts()
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("""CREATE TRIGGER fail_second_context_decision
                BEFORE INSERT ON context_alert_decisions
                WHEN (SELECT COUNT(*) FROM context_alert_decisions) = 1
                BEGIN SELECT RAISE(ABORT, 'authored second decision failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.enqueue(snapshot)
        self.assertEqual(self.counts(), before)
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("DROP TRIGGER fail_second_context_decision")
        decisions = self.enqueue(snapshot)
        self.assertEqual(len(decisions), len(snapshot["candidate_contexts"]))
        self.assertEqual(self.counts(), (len(decisions), 0))

    def test_caller_modified_snapshot_is_rejected_before_any_decision(self):
        snapshot = self.snapshot()
        altered = copy.deepcopy(snapshot)
        altered["candidate_contexts"] = altered["candidate_contexts"][:-1]
        before = self.counts()
        with self.assertRaises(PersistenceValidationError):
            self.enqueue(altered)
        self.assertEqual(self.counts(), before)


class TestAstraQualifiedContextBatch(unittest.TestCase):
    """Real scanner/storage path with authored signed context, never live evidence."""

    def setUp(self):
        from test_phase45_integration import TestPhase45IndependentIntegration
        self.case = TestPhase45IndependentIntegration()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.engine, _, raw = self.case.engine()
        self.store = self.engine.store
        self.case.import_source(self.engine, raw)
        with patch.object(self.engine, "_attach_context"):
            self.summary = self.engine.run_single_scan()
        self.snapshot = self.store.enrich_scan_context(self.summary["run_id"])
        self.assertEqual(self.snapshot["status"], "QUALIFIED")
        self.assertEqual(len(self.snapshot["candidate_contexts"]), 1)
        self.assertEqual(self.case.v2_rows(self.engine), [])

    def enqueue(self):
        return self.store.enqueue_context_alerts(self.summary["run_id"], self.snapshot, self.engine._now_ist())

    def counts(self):
        with self.store.paper_transaction(write=False) as conn:
            return tuple(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                         for table in ("context_alert_decisions", "notification_outbox"))

    def test_qualified_duplicate_batch_and_legacy_single_share_one_exact_intent(self):
        first = self.enqueue()
        self.assertEqual(first[0]["status"], "ELIGIBLE")
        self.assertEqual(self.enqueue(), first)
        self.assertEqual(self.store.enqueue_context_alert(self.summary["run_id"], first[0]["candidate_id"],
                         self.snapshot, self.engine._now_ist()), first[0])
        rows = self.case.v2_rows(self.engine)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["attempts"]), ("PENDING", 0))
        self.assertEqual(rows[0]["intent_id"], first[0]["intent_id"])
        self.assertEqual(self.counts()[0], 1)

    def test_decision_failure_rolls_back_new_qualified_intent_as_well(self):
        before = self.counts()
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("""CREATE TRIGGER fail_qualified_context_decision
                BEFORE INSERT ON context_alert_decisions
                BEGIN SELECT RAISE(ABORT, 'authored decision failure after intent'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.enqueue()
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.case.v2_rows(self.engine), [])
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("DROP TRIGGER fail_qualified_context_decision")
        self.assertEqual(self.enqueue()[0]["status"], "ELIGIBLE")
        self.assertEqual(len(self.case.v2_rows(self.engine)), 1)

    def test_rehashed_raw_source_normalization_change_is_rejected_on_later_call(self):
        self.enqueue()
        before = self.counts()
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT ingestion_id,payload_json FROM context_ingestions").fetchone()
            payload = json.loads(row["payload_json"])
            payload["records"][0]["title"] = "FORGED_SOURCE_NORMALIZATION"
            conn.execute("UPDATE context_ingestions SET payload_json=?,payload_digest=? WHERE ingestion_id=?",
                         (encoded(payload), digest(payload), row["ingestion_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.enqueue()
        self.assertEqual(self.counts(), before)

    def test_duplicate_batch_revalidates_existing_eligible_intent_content(self):
        first = self.enqueue()
        before = self.counts()
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM notification_outbox WHERE intent_id=?",
                               (first[0]["intent_id"],)).fetchone()
            payload = json.loads(row[0])
            payload["message_html"] = "FORGED_CONTEXT_MESSAGE"
            conn.execute("UPDATE notification_outbox SET payload_json=?,content_digest=? WHERE intent_id=?",
                         (encoded(payload), digest(payload), first[0]["intent_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.enqueue()
        self.assertEqual(self.counts(), before)


if __name__ == "__main__":
    unittest.main()
