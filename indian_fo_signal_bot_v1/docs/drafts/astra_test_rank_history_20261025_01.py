"""OFFLINE: retained scanner inputs authenticate local ranking, never live edge."""
import copy
import json
import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


from candle_lineage import digest, encoded
from rank_history import read_current
from storage import PersistenceValidationError, SQLitePersistenceStore
from test_astra_paper_triggers import ORBScannerFixture


class TestAstraRankHistory(unittest.TestCase):
    def setUp(self):
        self.fixture = ORBScannerFixture(self)
        self.engine, self.store = self.fixture.engine, self.fixture.store

    def view(self, **kwargs):
        return read_current(self.store, self.engine.config, self.fixture.now, **kwargs)

    def counts(self):
        with self.store.lineage_read() as conn:
            return {name: conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in
                ("signals", "scan_evaluations", "cash_rank_snapshots", "paper_events", "paper_candidate_decisions", "notification_outbox")}

    def first(self):
        scan = self.fixture.scan()
        self.assertEqual(scan["scan_status"], "COMPLETED", scan.get("error"))
        self.assertTrue(scan["ranking_required"])
        self.assertIn("opportunity_ranking", scan)
        return scan

    def later(self):
        self.fixture.append_bar(open=102, high=102.3, low=101.5, close=102.2)
        scan = self.fixture.scan()
        self.assertEqual(scan["scan_status"], "COMPLETED_EMPTY")
        return scan

    def test_retained_actual_orb_rank_is_current_and_read_only(self):
        scan = self.first()
        before, requests = self.counts(), list(self.fixture.scenario.requests)
        view = self.view()
        self.assertEqual(view["status"], "CURRENT_CANDIDATE_PRIORITY")
        self.assertFalse(view["actionable"])
        self.assertEqual(view["snapshot"]["run_id"], scan["run_id"])
        self.assertEqual([row["symbol"] for row in view["current_rows"]], ["RELIANCE"])
        row = view["current_rows"][0]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["score_components"]["rule_quality"], scan["signals"][0]["quality_score"])
        self.assertIn("NET_EXECUTABLE_REWARD", row["missing_components"])
        self.assertEqual(self.view(), view)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.fixture.scenario.requests, requests)

    def test_duplicate_scan_and_store_restart_keep_one_immutable_snapshot(self):
        first = self.first()
        before = self.view()
        second = self.fixture.scan()
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(self.counts()["cash_rank_snapshots"], 1)
        store = SQLitePersistenceStore(self.store.database_url)
        try:
            self.assertEqual(read_current(store, self.engine.config, self.fixture.now), before)
        finally:
            store.close()
        self.assertEqual(self.view(run_id=first["run_id"]), before)

    def test_empty_refresh_removes_old_current_priority_and_retains_predecessor(self):
        first = self.first()
        previous = self.view()
        later = self.later()
        view = self.view()
        self.assertEqual(view["snapshot"]["run_id"], later["run_id"])
        self.assertEqual(view["current_rows"], [])
        self.assertEqual(view["snapshot"]["removals"][0]["symbol"], "RELIANCE")
        self.assertEqual(view["snapshot"]["previous_rank_version"], previous["snapshot"]["rank_version"])
        self.assertEqual(view["snapshot"]["previous_snapshot"]["run_id"], first["run_id"])
        self.assertEqual(self.view(run_id=first["run_id"])["current_rows"], [])

    def test_exact_expiry_current_clock_and_profile_cannot_resurrect_history(self):
        first = self.first()
        self.fixture.scenario.now = self.fixture.now.replace(minute=46, second=0)
        self.assertEqual(len(self.view()["current_rows"]), 1)
        self.fixture.scenario.now += timedelta(seconds=1)
        expired = self.view()
        self.assertEqual(expired["current_rows"], [])
        self.assertEqual(len(expired["historical_rows"]), 1)
        self.assertEqual(expired["status"], "STALE_OR_FUTURE_SNAPSHOT")
        other = copy.deepcopy(self.engine.config)
        other.max_risk_per_trade_pct += 0.1
        self.assertIsNone(read_current(self.store, other, self.fixture.now)["snapshot"])
        archived = read_current(self.store, other, self.fixture.now, run_id=first["run_id"])
        self.assertEqual(archived["status"], "ARCHIVED_DIFFERENT_RUNTIME_SCOPE")
        self.assertEqual(archived["current_rows"], [])

    def test_code_change_archives_without_rewriting_source(self):
        self.first()
        before = self.counts()
        with patch("rank_history.code_fingerprint", return_value="future-source"):
            view = self.view()
        self.assertEqual(view["status"], "ARCHIVED_DIFFERENT_CODE")
        self.assertEqual(view["current_rows"], [])
        self.assertEqual(len(view["historical_rows"]), 1)
        self.assertEqual(before, self.counts())

    def test_rank_insertion_failure_rolls_back_signals_evaluations_outbox_and_rank(self):
        original = self.store._lineage_checkpoint
        def fail(stage):
            if stage == "after_rank_insert":
                raise RuntimeError("OFFLINE rank write failure")
            return original(stage)
        with patch.object(self.store, "_lineage_checkpoint", side_effect=fail):
            failed = self.fixture.scan()
        self.assertNotEqual(failed["scan_status"], "COMPLETED")
        self.assertTrue(all(value == 0 for value in self.counts().values()), self.counts())
        retried = self.first()
        self.assertEqual(self.counts()["cash_rank_snapshots"], 1)
        self.assertEqual(self.view()["snapshot"]["run_id"], retried["run_id"])

    def test_missing_latest_rank_row_does_not_fall_back_to_older_rank(self):
        self.first()
        last = self.later()
        with self.store.paper_transaction() as conn:
            conn.execute("DELETE FROM cash_rank_snapshots WHERE run_id=?", (last["run_id"],))
        with self.assertRaises(PersistenceValidationError):
            self.view()

    def test_rank_payload_rehash_cannot_forge_a_score(self):
        scan = self.first()
        with self.store.paper_transaction() as conn:
            row = conn.execute("SELECT payload_json FROM cash_rank_snapshots WHERE run_id=?", (scan["run_id"],)).fetchone()
            body = json.loads(row[0])
            body["ranking"]["rows"][0]["score_components"]["rule_quality"] += 1
            body["ranking"]["snapshot_sha256"] = digest({k: v for k, v in body["ranking"].items() if k != "snapshot_sha256"})
            conn.execute("UPDATE cash_rank_snapshots SET payload_json=?,payload_sha256=? WHERE run_id=?",
                         (encoded(body), digest(body), scan["run_id"]))
            result = json.loads(conn.execute("SELECT result_json FROM cash_candle_scans WHERE run_id=?", (scan["run_id"],)).fetchone()[0])
            result["opportunity_ranking"]["payload_sha256"] = digest(body)
            conn.execute("UPDATE cash_candle_scans SET result_json=?,result_digest=? WHERE run_id=?",
                         (encoded(result), digest(result), scan["run_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.view()

    def test_source_digest_and_quality_forgery_fail_even_with_matching_evaluation_result_hashes(self):
        scan = self.first()
        with self.store.lineage_read() as conn:
            original_result = json.loads(conn.execute("SELECT result_json FROM cash_candle_scans WHERE run_id=?", (scan["run_id"],)).fetchone()[0])
            original_evaluation = json.loads(conn.execute("SELECT payload_json FROM scan_evaluations WHERE run_id=?", (scan["run_id"],)).fetchone()[0])
        for mutation in ("quality", "candle_digest"):
            with self.subTest(mutation=mutation):
                evaluation = copy.deepcopy(original_evaluation)
                candidate = evaluation["candidate_evaluations"][0]
                if mutation == "quality":
                    candidate["explanation"]["setup_quality"] += 1
                else:
                    candidate["source_reference"]["candle_digest"] = "0" * 64
                result = dict(original_result, candidate_evaluations=evaluation["candidate_evaluations"])
                with self.store.paper_transaction() as conn:
                    conn.execute("UPDATE scan_evaluations SET payload_json=?,payload_sha256=? WHERE run_id=?",
                                 (encoded(evaluation), digest(evaluation), scan["run_id"]))
                    conn.execute("UPDATE cash_candle_scans SET result_json=?,result_digest=? WHERE run_id=?",
                                 (encoded(result), digest(result), scan["run_id"]))
                with self.assertRaises(PersistenceValidationError) as caught:
                    self.view()
                self.assertIn(str(caught.exception), ("RANK_SIGNAL_COMPONENT_FAILURE", "RANK_CANDIDATE_SOURCE_FAILURE"))

    def test_missing_required_descriptor_rejects_recomputed_result_checksum(self):
        scan = self.first()
        with self.store.paper_transaction() as conn:
            result = json.loads(conn.execute("SELECT result_json FROM cash_candle_scans WHERE run_id=?", (scan["run_id"],)).fetchone()[0])
            result.pop("opportunity_ranking")
            result.pop("ranking_required")
            conn.execute("UPDATE cash_candle_scans SET result_json=?,result_digest=? WHERE run_id=?",
                         (encoded(result), digest(result), scan["run_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.view()

    def test_http_ranking_get_head_validation_and_failed_integrity_are_read_only(self):
        from test_cash_workflow import TestCashWorkflow
        # Close this test's initial wire fixture before nesting another one.
        self.fixture.scenario.tearDown()
        self.fixture.scenario.doCleanups()
        workflow = TestCashWorkflow()
        workflow.setUp()
        self.addCleanup(workflow.doCleanups)
        workflow.use_orb_account()
        self.assertEqual(workflow.request("POST", "/api/scan")[0], 200)
        code, payload = workflow.request("GET", "/api/opportunity-rankings?limit=1")
        self.assertEqual(code, 200)
        self.assertEqual(len(payload["current_rows"]), 1)
        self.assertFalse(payload["actionable"])
        requests = list(workflow.orb.scenario.requests)
        for route in ("/api/opportunity-rankings?limit=0", "/api/opportunity-rankings?limit=1&limit=2",
                      "/api/opportunity-rankings?as_of=2026-10-16", "/api/opportunity-rankings?offset=513"):
            self.assertEqual(workflow.request("GET", route)[0], 400)
        self.assertEqual(workflow.request("HEAD", "/api/opportunity-rankings")[0], 200)
        with workflow.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE cash_rank_snapshots SET payload_json='{}'")
        code, failed = workflow.request("GET", "/api/opportunity-rankings")
        self.assertEqual(code, 503)
        self.assertNotIn("current_rows", failed)
        self.assertEqual(requests, workflow.orb.scenario.requests)


if __name__ == "__main__":
    unittest.main()
