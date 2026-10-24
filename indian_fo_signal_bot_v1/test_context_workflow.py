"""Memory-only context persistence and snapshot consumer tests; no real source."""
import copy
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_context_data as context_fixtures
from candle_lineage import digest, encoded
from context_workflow import candidate_context
from storage import SQLitePersistenceStore, PersistenceValidationError


class TestContextWorkflow(unittest.TestCase):
    def setUp(self):
        self.fixture = context_fixtures.TestContextData()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = self.fixture.now
        self.evaluation = dict(schema_version="tradepulse.scan-evaluation.v1", run_id="run",
            strategy_evaluations=[], candidate_evaluations=[copy.deepcopy(self.fixture.candidate)],
            data_mode="SIMULATED", actionable=False)
        self.store.record_scan_run("run", self.now.isoformat(), self.now.isoformat(), 0,
            "COMPLETE", "paper_sim", "SIMULATED", True)
        self.store.save_scan_evaluations("run", self.evaluation)

    def import_one(self, *, when=None, observed=None, raw=None):
        return self.store.import_context(raw if raw is not None else self.fixture.raw(),
            provider="offline_notices", collected_at=(when or self.now).isoformat(),
            observed_at=(observed or when or self.now).isoformat(),
            trusted_identities=[self.fixture.identity])

    def counts(self):
        with self.store.lineage_read() as conn:
            return tuple(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in ("context_ingestions", "scan_context_snapshots", "scan_context_sources"))

    def test_import_and_snapshot_are_idempotent_without_mutating_phase4(self):
        original = self.store.load_scan_evaluations("run")
        ingestion = self.import_one()
        self.assertEqual(self.import_one(observed=self.now + timedelta(minutes=1)), ingestion)
        first = self.store.enrich_scan_context("run")
        second = self.store.enrich_scan_context("run")
        self.assertEqual(first, second)
        self.assertEqual(first["phase4_digest"], digest(original))
        self.assertFalse(first["actionable"])
        self.assertFalse(first["affects_ranking"])
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(self.store.load_scan_evaluations("run"), original)
        self.assertEqual(self.store.load_scan_context("run"), first)
        self.assertEqual(self.store.list_context_ingestions()["items"], [ingestion])

    def test_source_capture_id_binds_observed_time_and_snapshot_foreign_key(self):
        ingestion = self.import_one()
        snapshot = self.store.enrich_scan_context("run")
        with self.store.lineage_read() as conn:
            row = conn.execute("SELECT * FROM context_ingestions").fetchone()
        self.assertEqual(row["capture_id"], digest(["context-capture-v1", ingestion["ingestion_id"], row["observed_at"]]))
        self.assertEqual(snapshot["capture_ids"], [row["capture_id"]])
        earlier = (self.now - timedelta(minutes=1)).isoformat()
        changed = digest(["context-capture-v1", ingestion["ingestion_id"], earlier])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.paper_transaction() as conn:
                conn.execute("UPDATE context_ingestions SET observed_at=?,capture_id=?", (earlier, changed))
        self.assertEqual(self.store.load_scan_context("run"), snapshot)

    def test_observed_time_tamper_without_capture_change_fails_reads(self):
        self.import_one()
        self.store.enrich_scan_context("run")
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE context_ingestions SET observed_at=?", ((self.now + timedelta(seconds=1)).isoformat(),))
        for read in (self.store.list_context_ingestions, lambda: self.store.load_scan_context("run")):
            with self.subTest(read=read), self.assertRaises(PersistenceValidationError):
                read()

    def test_backdated_collection_cannot_enter_earlier_decision(self):
        later = self.now + timedelta(minutes=5)
        self.import_one(observed=later)
        context = self.store.enrich_scan_context("run")
        self.assertEqual(context["status"], "UNAVAILABLE")
        self.assertEqual(context["candidate_contexts"][0]["records"], [])
        self.assertIn("CONTEXT_LOCAL_CAPTURE_AFTER_AS_OF", context["reason_codes"])
        self.assertNotIn(self.fixture.row["title"], json.dumps(context))

    def test_future_import_fact_cannot_create_past_conflict(self):
        first = self.import_one()
        self.fixture.row["title"] = "Future changed source fact"
        self.import_one(when=self.now + timedelta(minutes=1))
        snapshot = self.store.enrich_scan_context("run")
        record = snapshot["candidate_contexts"][0]["records"][0]
        self.assertEqual(record["content_id"], first["records"][0]["content_id"])
        self.assertFalse(record["conflict"])
        self.assertNotIn("CONTEXT_CONFLICTING", snapshot["reason_codes"])

    def test_current_information_is_separate_and_cannot_rewrite_decision_snapshot(self):
        self.import_one(observed=self.now + timedelta(minutes=1))
        original = self.store.enrich_scan_context("run")
        current = self.store.enrich_scan_context("run", as_of=(self.now + timedelta(minutes=2)).isoformat(),
                                                  evaluation_mode="CURRENT_INFORMATION")
        self.assertEqual(original["candidate_contexts"][0]["records"], [])
        self.assertEqual(len(current["candidate_contexts"][0]["records"]), 1)
        self.assertNotEqual(original["snapshot_id"], current["snapshot_id"])
        self.assertFalse(current["actionable"])
        self.assertEqual(self.store.load_scan_context("run", snapshot_id=original["snapshot_id"]), original)
        self.assertEqual(self.store.load_scan_context("run"), current)

    def test_decision_and_current_cutoff_modes_are_bounded(self):
        for kwargs in (dict(as_of=(self.now + timedelta(seconds=1)).isoformat()),
                       dict(as_of=(self.now - timedelta(seconds=1)).isoformat(), evaluation_mode="CURRENT_INFORMATION"),
                       dict(evaluation_mode="UNRECOGNIZED"), dict(as_of="2026-10-23T10:00:00")):
            with self.subTest(kwargs=kwargs), self.assertRaises(PersistenceValidationError):
                self.store.enrich_scan_context("run", **kwargs)

    def test_import_rollback_and_snapshot_source_link_rollback(self):
        def fail(_):
            raise RuntimeError("offline controlled interruption")
        with patch.object(self.store, "_context_checkpoint", side_effect=fail), self.assertRaises(RuntimeError):
            self.import_one()
        self.assertEqual(self.counts(), (0, 0, 0))
        self.import_one()
        with patch.object(self.store, "_context_checkpoint", side_effect=fail), self.assertRaises(RuntimeError):
            self.store.enrich_scan_context("run")
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_raw_bound_reparse_rejects_rehashed_source_facts(self):
        self.import_one()
        with self.store.paper_transaction() as conn:
            payload = json.loads(conn.execute("SELECT payload_json FROM context_ingestions").fetchone()[0])
            payload["records"][0]["title"] = "Rehashed forged source fact"
            conn.execute("UPDATE context_ingestions SET payload_json=?,payload_digest=?", (encoded(payload), digest(payload)))
        with self.assertRaises(PersistenceValidationError):
            self.store.list_context_ingestions()

    def test_snapshot_rehash_cannot_substitute_candidate_or_phase4_digest(self):
        self.import_one()
        snapshot = self.store.enrich_scan_context("run")
        forged = copy.deepcopy(snapshot)
        forged["candidate_contexts"][0]["candidate_id"] = "another-candidate"
        forged["phase4_digest"] = digest("substituted")
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE scan_context_snapshots SET payload_json=?,payload_digest=?", (encoded(forged), digest(forged)))
        with self.assertRaises(PersistenceValidationError):
            self.store.load_scan_context("run")

    def test_removed_or_changed_capture_link_is_detected(self):
        self.import_one()
        self.store.enrich_scan_context("run")
        with self.store.paper_transaction() as conn:
            conn.execute("DELETE FROM scan_context_sources")
        with self.assertRaises(PersistenceValidationError):
            self.store.load_scan_context("run")

    def test_missing_parent_and_legacy_history_remain_unavailable(self):
        self.assertIsNone(self.store.load_scan_context("legacy"))
        self.assertEqual(candidate_context(None, "legacy")["status"], "MISSING")
        self.store.record_scan_run("legacy", self.now.isoformat(), None, 0, "COMPLETE", "paper_sim", "SIMULATED", True)
        with self.assertRaisesRegex(PersistenceValidationError, "EVALUATION_NOT_RETAINED"):
            self.store.enrich_scan_context("legacy")
        self.assertEqual(candidate_context(dict(candidate_contexts=[]), "candidate")["status"], "UNAVAILABLE")

    def test_qualified_policy_is_required_after_memory_database_restart(self):
        raw = self.fixture.raw()
        policy = self.fixture.policy(raw)
        self.store.context_source_policy = policy
        self.import_one(raw=raw)
        original = self.store.enrich_scan_context("run")
        self.assertEqual(original["status"], "QUALIFIED")
        recovered = SQLitePersistenceStore(":memory:")
        self.addCleanup(recovered.close)
        self.store._memory_conn.backup(recovered._memory_conn)
        with self.assertRaises(PersistenceValidationError):
            recovered.load_scan_context("run")
        recovered.context_source_policy = policy
        self.assertEqual(recovered.load_scan_context("run"), original)
        self.assertEqual(recovered.load_scan_evaluations("run")["candidate_evaluations"][0]["status"], "REJECTED")

    def test_snapshot_scope_limits_and_pagination(self):
        self.import_one()
        self.assertEqual(self.store.list_context_ingestions(limit=1, offset=1)["items"], [])
        for args in (dict(limit=True), dict(offset=-1)):
            with self.assertRaises(PersistenceValidationError):
                self.store.list_context_ingestions(**args)
        with patch("context_workflow.MAX_SNAPSHOT_BYTES", 10), self.assertRaises(PersistenceValidationError):
            self.store.enrich_scan_context("run")
        self.assertEqual(self.counts(), (1, 0, 0))
        self.store.enrich_scan_context("run")
        with patch("context_workflow.MAX_SNAPSHOTS_PER_RUN", 1), self.assertRaises(PersistenceValidationError):
            self.store.enrich_scan_context("run", as_of=(self.now + timedelta(seconds=1)).isoformat(),
                                          evaluation_mode="CURRENT_INFORMATION")

    def test_import_bounds_prevent_unqueryable_source_sprawl(self):
        self.import_one()
        with patch("context_workflow.MAX_INGESTIONS", 1), self.assertRaises(PersistenceValidationError):
            self.import_one(when=self.now + timedelta(seconds=1))
        with patch("context_workflow.MAX_RECORDS", 1), self.assertRaises(PersistenceValidationError):
            self.import_one(when=self.now + timedelta(seconds=1))
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_collection_claim_after_local_capture_is_rejected(self):
        with self.assertRaisesRegex(PersistenceValidationError, "COLLECTION_AFTER_LOCAL_CAPTURE"):
            self.import_one(when=self.now + timedelta(minutes=1), observed=self.now)

    def test_actual_cash_scan_v2_context_intent_reloads_without_recursive_validation(self):
        import test_phase45_integration as integration_fixtures
        scenario = integration_fixtures.TestPhase45IndependentIntegration()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        engine, _, raw = scenario.engine()
        scenario.import_source(engine, raw)
        summary = engine.run_single_scan()
        self.assertEqual(summary['total_signals'], 1)
        self.assertEqual(summary['context_alert_decisions'][0]['status'], 'ELIGIBLE')
        self.assertEqual(summary['context_alert_decisions'][0]['preview']['status'], 'ACKNOWLEDGED')
        self.assertEqual(len(scenario.v2_rows(engine)), 1)
        self.assertEqual(engine.store.load_scan_context(summary['run_id']), summary['context'])
        self.assertEqual(engine.store.load_cash_scan(summary['run_id'])['status'], 'COMMITTED')
        self.assertEqual(engine.store.query_signals()['total_count'], 1)


if __name__ == "__main__":
    unittest.main()
