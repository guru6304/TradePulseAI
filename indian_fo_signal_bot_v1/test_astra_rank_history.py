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

    def test_actual_two_stock_scanner_refresh_reverses_priority_on_new_volume_evidence(self):
        from config import BotConfig
        from strategies import parse_ist_timestamp
        import urllib.parse
        metas = [copy.deepcopy(meta) for meta in BotConfig().equity_watchlist if meta["symbol"] in ("TCS", "INFY")]
        self.assertEqual(len(metas), 2)
        self.engine.config.equity_watchlist = metas
        batches = {meta["angel_token"]: copy.deepcopy(self.fixture.bars) for meta in metas}
        tokens = {meta["symbol"]: meta["angel_token"] for meta in metas}
        batches[tokens["TCS"]][-1]["volume"] = 5000
        batches[tokens["INFY"]][-1]["volume"] = 1700
        original = self.fixture.scenario._open
        def wire(request, timeout):
            if urllib.parse.urlsplit(request.full_url).path == self.fixture.scenario.ANGEL_CANDLES:
                token = str(json.loads(request.data)["symboltoken"])
                self.fixture.scenario.batches["angelone"] = batches[token]
            return original(request, timeout)
        with patch("urllib.request.urlopen", side_effect=wire):
            first = self.first()
            initial = self.view()
            self.assertEqual([row["symbol"] for row in initial["current_rows"]], ["TCS", "INFY"])
            for symbol, token in tokens.items():
                stamp = parse_ist_timestamp(batches[token][-1]["timestamp"]) + timedelta(minutes=5)
                batches[token].extend([
                    dict(timestamp=stamp.isoformat(), open=102, high=102.2, low=99.8, close=100, volume=1000),
                    dict(timestamp=(stamp + timedelta(minutes=5)).isoformat(), open=100, high=102.4, low=99.8,
                         close=102, volume=5500 if symbol == "INFY" else 2200)])
            self.fixture.scenario.now += timedelta(minutes=10)
            later = self.first()
            changed = self.view()
        self.assertNotEqual(first["run_id"], later["run_id"])
        self.assertEqual([row["symbol"] for row in changed["current_rows"]], ["INFY", "TCS"])
        self.assertEqual(changed["current_rows"][0]["previous_rank"], 2)
        self.assertEqual(changed["current_rows"][0]["rank_change_reason"], "SCORE_COMPONENT_CHANGED")
        self.assertIn("rule_quality", changed["current_rows"][0]["component_changes"])
        self.assertNotEqual(initial["snapshot"]["rank_version"], changed["snapshot"]["rank_version"])
        self.assertEqual(self.counts()["paper_events"], 0)
        self.assertIsNone(self.store.load_live_acceptance_evidence("angelone", "INFY"))

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
        with patch.object(self.store, "_lineage_checkpoint", side_effect=fail), self.assertRaisesRegex(RuntimeError, "rank write failure"):
            self.fixture.scan()
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

    def test_older_valid_input_cannot_replace_newer_committed_priority(self):
        first = self.first()
        before = self.counts()
        saved_clock = self.fixture.now
        self.fixture.bars.pop()
        self.fixture.scenario.now -= timedelta(minutes=5)
        with self.assertRaisesRegex(PersistenceValidationError, "RANK_OUT_OF_ORDER_SOURCE"):
            self.fixture.scan()
        self.assertEqual(self.counts(), before)
        self.fixture.scenario.now = saved_clock
        self.assertEqual(self.view()["snapshot"]["run_id"], first["run_id"])

    def test_predecessor_signal_corruption_blocks_current_rank_without_fallback(self):
        first = self.first()
        self.later()
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE signals SET position_qty=position_qty+1 WHERE scan_run_id=?", (first["run_id"],))
        with self.assertRaises(PersistenceValidationError):
            self.view()

    def test_append_cannot_skip_deleted_latest_required_rank_history(self):
        self.first()
        latest = self.later()
        with self.store.paper_transaction() as conn:
            conn.execute("DELETE FROM cash_rank_snapshots WHERE run_id=?", (latest["run_id"],))
        before = self.counts()
        self.fixture.append_bar(open=102.2, high=102.35, low=101.6, close=102.25)
        with self.assertRaises(PersistenceValidationError):
            self.fixture.scan()
        self.assertEqual(self.counts(), before)
        with self.assertRaises(PersistenceValidationError):
            self.view()

    def test_result_mode_corruption_cannot_hide_latest_committed_scan(self):
        self.first()
        latest = self.later()
        with self.store.paper_transaction() as conn:
            result = json.loads(conn.execute("SELECT result_json FROM cash_candle_scans WHERE run_id=?",
                                            (latest["run_id"],)).fetchone()[0])
            result["data_mode"] = "SIMULATED"
            conn.execute("UPDATE cash_candle_scans SET result_json=?,result_digest=? WHERE run_id=?",
                         (encoded(result), digest(result), latest["run_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.view()

    def test_latest_committed_lookup_uses_input_scope_order_index(self):
        self.first()
        from candle_lineage import runtime_profile
        with self.store.lineage_read() as conn:
            plan = conn.execute("""EXPLAIN QUERY PLAN SELECT run_id FROM cash_candle_scans
                WHERE status='COMMITTED' AND json_extract(snapshot_json,'$.profile_digest')=?
                ORDER BY json_extract(snapshot_json,'$.reference') DESC,work_id DESC,run_id DESC LIMIT 1""",
                (digest(runtime_profile(self.engine.config)),)).fetchall()
        details = " ".join(str(row[3]) for row in plan)
        self.assertIn("cash_rank_committed_input_order", details)
        self.assertNotIn("TEMP B-TREE", details)

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

    def test_deleted_row_and_result_flags_cannot_downgrade_new_scan_to_legacy(self):
        scan = self.first()
        with self.store.paper_transaction() as conn:
            result = json.loads(conn.execute("SELECT result_json FROM cash_candle_scans WHERE run_id=?", (scan["run_id"],)).fetchone()[0])
            result.pop("opportunity_ranking")
            result.pop("ranking_required")
            conn.execute("DELETE FROM cash_rank_snapshots WHERE run_id=?", (scan["run_id"],))
            conn.execute("UPDATE cash_candle_scans SET result_json=?,result_digest=? WHERE run_id=?",
                         (encoded(result), digest(result), scan["run_id"]))
        with self.assertRaises(PersistenceValidationError):
            self.view()
        with self.assertRaises(PersistenceValidationError):
            self.store.load_cash_scan(scan["run_id"])

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
