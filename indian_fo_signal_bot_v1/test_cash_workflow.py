"""OFFLINE synthetic input through the real scanner, ledger, HTTP and renderer."""
import copy
from datetime import timedelta
import http.client
import json
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

import test_bot  # credential-free bootstrap
from paper_portfolio import PaperAccountConfig, PaperPortfolio, FORWARD_FILL_POLICY
from scanner_engine import MarketScanScheduler
from server import DashboardRequestHandler, create_http_server
from storage import PersistenceError, PersistenceValidationError
from strategies import parse_ist_timestamp


class TestCashWorkflow(unittest.TestCase):
    def setUp(self):
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        self.fixture = TestPhase4OfflineEndToEnd()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture._engine("upstox", database="workflow.sqlite")
        self.paper_config = PaperAccountConfig(account_id="offline-cash", run_id="workflow",
            provider="upstox", source_data_mode="LIVE", fill_policy=FORWARD_FILL_POLICY)
        self.paper = PaperPortfolio(self.engine.store, self.paper_config, clock=lambda: self.fixture.now)
        self.handler = type("OfflineCashHandler", (DashboardRequestHandler,), dict(engine=self.engine,
            scheduler=MarketScanScheduler(self.engine), paper_portfolio=self.paper,
            evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE"))
        self.server = create_http_server("127.0.0.1", 0, self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()

    def advance(self, price):
        self.fixture.batches["upstox"][-1].update(open=price, high=price+.2,
            low=price-.2, close=price+.1, volume=10000)
        self.fixture.now += timedelta(minutes=5)
        # Expand completed 5m fixture observations to actual Upstox 1m wire
        # input; unfinished observations contain only supplied minutes.
        def wire(bars, interval):
            rows = []
            for bar in bars:
                stamp = parse_ist_timestamp(bar["timestamp"])
                complete = stamp + timedelta(minutes=5) <= self.fixture.now
                for minute in range(5 if complete else 1):
                    prices = ([bar["open"]]*4 if minute < 4 else
                              [bar[k] for k in ("open", "high", "low", "close")])
                    rows.append([(stamp+timedelta(minutes=minute)).isoformat(), *prices, bar["volume"]/5])
            return rows
        self.fixture._wire_rows = wire

    def use_orb_account(self, account_id="offline-cash", **settings):
        """Use retained real-evaluator ORB inputs for new automatic entries."""
        from test_astra_paper_triggers import ORBScannerFixture
        from paper_triggers import ORB_FILL_POLICY
        self.orb = ORBScannerFixture(self)
        self.engine = self.orb.engine
        self.paper_config = PaperAccountConfig(account_id=account_id, run_id="workflow",
            provider="angelone", source_data_mode="LIVE", fill_policy=ORB_FILL_POLICY, **settings)
        self.paper = PaperPortfolio(self.engine.store, self.paper_config, clock=lambda: self.orb.now)
        self.handler.engine, self.handler.paper_portfolio = self.engine, self.paper
        self.handler.scheduler = MarketScanScheduler(self.engine)

    def advance_orb_trigger(self):
        self.orb.append_bar(open=102.0, high=102.8, low=101.7, close=102.6)

    def test_real_http_scan_lineage_paper_api_and_actual_dashboard_agree(self):
        self.use_orb_account()
        code, first = self.request("POST", "/api/scan")
        self.assertEqual(code, 200)
        self.assertEqual(first["paper_portfolio"]["status"], "COMPLETED")
        code, listed = self.request("GET", "/api/signals")
        self.assertEqual(code, 200)
        item = listed["items"][0]
        self.assertEqual(item["lineage"]["status"], "COMMITTED")
        self.assertEqual(item["paper_decision"]["status"], "QUEUED")
        self.assertEqual(item["strategy_id"], "strat_4_orb_filtered")
        self.assertFalse(item["actionable"])
        self.assertEqual(listed["evidence_scope"], "OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE")
        _, duplicate = self.request("POST", "/api/scan")
        self.assertTrue(duplicate["idempotent_replay"])
        self.assertEqual(self.engine.store.query_signals()["total_count"], 1)
        run = first["run_id"]
        code, lineage = self.request("GET", "/api/scan-lineage?run_id="+run)
        self.assertEqual(code, 200)
        self.assertEqual(lineage["code_digest"], item["lineage"]["code_digest"])
        batch = lineage["batches"][0]
        code, bars = self.request("GET", "/api/cash-candles?run_id="+run+"&batch_id="+batch["batch_id"]+"&limit=20")
        self.assertEqual(code, 200)
        self.assertEqual((bars["total_count"], len(bars["items"])), (30, 20))
        self.assertTrue(all(b["is_complete"] for b in bars["items"]))
        self.advance_orb_trigger()
        self.assertEqual(self.request("POST", "/api/scan")[0], 200)
        _, listed = self.request("GET", "/api/signals")
        self.assertEqual(listed["items"][0]["paper_decision"]["status"], "FILLED")
        self.assertFalse(listed["items"][0]["actionable"])
        _, paper = self.request("GET", "/api/paper-portfolio?account_id=offline-cash")
        self.assertEqual(paper["reconciliation"]["status"], "OK")
        self.assertEqual(paper["accounting"]["open_positions"], 1)
        decision = paper["candidate_decisions"][0]
        self.assertEqual(decision["trigger_contract"]["rule_id"], "orb.signal_extreme_completed_close_cross.v1")
        self.assertEqual(decision["trigger_evaluations"][-1]["status"], "TRIGGERED")
        self.assertEqual(paper["positions"][0]["raw_entry_price"], 102.6)
        self.assertNotEqual(paper["positions"][0]["raw_entry_price"], item["entry_price"])
        _, outbox = self.request("GET", "/api/notification-outbox")
        _, research = self.request("GET", "/api/backtest-runs?limit=5")
        listed["stored_reports"] = [dict(label="Paper ledger", data=paper),
            dict(label="Notification previews", data=outbox), dict(label="Stored research runs", data=research)]
        code, listed["opportunity_rankings"] = self.request("GET", "/api/opportunity-rankings?run_id=" + run)
        self.assertEqual(code, 200)
        self.assertEqual(listed["opportunity_rankings"]["current_rows"], [])
        self.assertEqual(listed["opportunity_rankings"]["historical_rows"][0]["symbol"], "RELIANCE")
        artifact = Path(self.fixture.temp.name)/"workflow.json"
        artifact.write_text(json.dumps(listed), encoding="utf-8")
        rendered = subprocess.run(["node", "test_cash_dashboard.js", "--workflow-payload", str(artifact)],
            cwd=Path(__file__).parent, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(rendered.returncode, 0, rendered.stdout+rendered.stderr)
        self.assertIn("actual HTTP workflow payload", rendered.stdout)

    def test_api_rejects_invalid_data_and_distinguishes_empty_from_failure(self):
        original = copy.deepcopy(self.fixture.batches["upstox"])
        for change, expected in ((lambda r: r.pop(1), 502), (lambda r: r.reverse(), 502),
                       (lambda r: r.insert(1, copy.deepcopy(r[0])), 502), (lambda r: r[0].update(high=0), 502)):
            self.fixture.batches["upstox"] = copy.deepcopy(original)
            change(self.fixture.batches["upstox"])
            # The adapter handles its provider's descending convention, not
            # arbitrary reordered wire events within an input batch.
            code, result = self.request("POST", "/api/scan")
            self.assertEqual(code, expected)
            if code == 200:
                # Wire order normalization is permitted, but no duplicate work.
                self.assertEqual(result["input_lineage"]["batch_ids"],
                    self.engine.store.load_cash_scan(result["run_id"])["result"]["input_lineage"]["batch_ids"])
            else:
                self.assertEqual(code, 502)
                self.assertEqual(result["scan_status"], "FAILED")
        self.fixture.batches["upstox"] = copy.deepcopy(original)
        self.fixture.failures["upstox"] = "transport"
        code, failed = self.request("POST", "/api/scan")
        self.assertEqual((code, failed["scan_status"]), (502, "FAILED"))
        self.fixture.failures.pop("upstox")
        # A separate actual empty scan, no pending prior input, not fallback data.
        for row in self.fixture.batches["upstox"]:
            row.update(open=100, high=100, low=100, close=100, volume=1000)
        code, empty = self.request("POST", "/api/scan")
        self.assertEqual((code, empty["scan_status"]), (200, "COMPLETED_EMPTY"))
        self.assertEqual(empty["total_signals"], 0)
        self.assertTrue(empty["empty_reason"])

    def test_real_paper_risk_rejection_never_becomes_actionable(self):
        self.use_orb_account(account_id="offline-risk-reject", max_position_exposure_pct=.01)
        _, first = self.request("POST", "/api/scan")
        self.assertEqual(first["paper_portfolio"]["report"]["candidate_decisions"][0]["status"], "QUEUED")
        self.advance_orb_trigger()
        self.assertEqual(self.request("POST", "/api/scan")[0], 200)
        code, listed = self.request("GET", "/api/signals")
        self.assertEqual(code, 200)
        item = listed["items"][0]
        self.assertFalse(item["actionable"])
        self.assertEqual(item["recommendation_status"], "PAPER_REJECTED")
        self.assertEqual(item["paper_decision"]["reason_code"], "EXPOSURE_LIMIT")
        _, report = self.request("GET", "/api/paper-portfolio?account_id=offline-risk-reject")
        self.assertEqual(report["accounting"]["open_positions"], 0)
        self.assertEqual(report["candidate_decisions"][0]["trigger_evaluations"][-1]["status"], "TRIGGERED")

    def test_operations_reads_expose_retry_without_dispatch_and_health_rejects_corrupt_ledger(self):
        self.use_orb_account()
        with patch("notification_outbox.render_preview", side_effect=ValueError("OFFLINE preview failure")):
            code, scan = self.request("POST", "/api/scan")
            self.assertEqual(code, 200)
        with patch("notification_outbox.render_preview", side_effect=AssertionError("Read must never render")):
            code, outbox = self.request("GET", "/api/notification-outbox?limit=1&status=RETRY")
            self.assertEqual(code, 200)
            self.assertEqual(outbox["counts"]["RETRY"], 1)
            self.assertEqual(outbox["items"][0]["attempts"], 1)
            code, health = self.request("GET", "/api/health")
            self.assertEqual(code, 200)
            self.assertEqual(health["status"], "degraded")
            self.assertIn("NOTIFICATION_PREVIEW_REQUIRES_ATTENTION", health["operations"]["alerts"])
        self.advance_orb_trigger()
        self.assertEqual(self.request("POST", "/api/scan")[0], 200)
        with self.engine.store.paper_transaction() as conn:
            changed = conn.execute("UPDATE paper_positions SET payload_json='{}'").rowcount
            self.assertEqual(changed, 1)
        code, health = self.request("GET", "/api/health")
        self.assertEqual(code, 503)
        self.assertIn("PAPER_RECONCILIATION_REQUIRED", health["operations"]["alerts"])

    def test_http_history_pages_keep_original_snapshot_scope_and_bound_queries(self):
        from test_historical_pagination import TestHistoricalPagination
        bars = TestHistoricalPagination().bars()
        self.engine.store.save_historical_candle_dataset(bars, "RELIANCE", provider="offline_fixture",
            instrument_token="2885", data_mode="SIMULATED", reference_time_ist=self.fixture.now)
        query = "/api/historical-candle-pages?symbol=RELIANCE&data_mode=SIMULATED&provider=offline_fixture&limit=37"
        code, first = self.request("GET", query)
        self.assertEqual(code, 200)
        self.assertEqual((first["total_count"], len(first["items"])), (150, 37))
        code, second = self.request("GET", query+"&cursor="+first["next_cursor"])
        self.assertEqual(code, 200)
        self.assertEqual(first["snapshot_digest"], second["snapshot_digest"])
        self.assertFalse({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
        for suffix in ("&limit=2", "&unknown=1", "&cursor=invalid"):
            self.assertEqual(self.request("GET", query+suffix)[0], 400)

    def test_stale_or_only_incomplete_input_never_enters_accepted_store(self):
        for only_incomplete in (False, True):
            original = copy.deepcopy(self.fixture.batches["upstox"])
            if only_incomplete:
                self.fixture.batches["upstox"] = [original[-1]]
            else:
                self.fixture.batches["upstox"] = original[:-1]
                self.fixture.now += timedelta(minutes=12)
            code, result = self.request("POST", "/api/scan")
            self.assertEqual((code, result["scan_status"]), (502, "FAILED"))
            with self.engine.store.paper_transaction(write=False) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM cash_candle_facts").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)
            if not only_incomplete:
                self.fixture.now -= timedelta(minutes=12)
            self.fixture.batches["upstox"] = original

    def test_required_write_failure_has_no_committed_result_or_delivery(self):
        with patch.object(self.engine.store, "save_signal", side_effect=PersistenceError("OFFLINE write failure")), \
                patch.object(self.engine.telegram, "send_signal") as sender:
            code, failed = self.request("POST", "/api/scan")
        self.assertEqual(code, 503)
        sender.assert_not_called()
        self.assertEqual(self.engine.store.query_signals()["total_count"], 0)
        run_id = self.engine.store.pending_cash_scans()[0]["run_id"]
        self.engine.close()
        restarted = self.fixture._engine("upstox", database="workflow.sqlite")
        recovered_paper = PaperPortfolio(restarted.store, self.paper_config, clock=lambda: self.fixture.now)
        with patch.object(restarted.broker, "fetch_candles", side_effect=AssertionError("No recovery fetch")):
            result = restarted.resume_cash_scan(run_id, paper_portfolio=recovered_paper)
            repeated = restarted.resume_cash_scan(run_id, paper_portfolio=recovered_paper)
        self.handler.engine, self.handler.paper_portfolio = restarted, recovered_paper
        self.handler.scheduler = MarketScanScheduler(restarted)
        self.assertTrue(repeated["idempotent_replay"])
        self.assertEqual(result["persisted_signals"], 1)
        code, rows = self.request("GET", "/api/signals")
        self.assertEqual((code, len(rows["items"])), (200, 1))
        self.assertEqual(rows["items"][0]["lineage"]["status"], "COMMITTED")

    def test_quantity_and_risk_tamper_cannot_be_served_as_reconciled_signal(self):
        _, result = self.request("POST", "/api/scan")
        with self.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE signals SET position_qty=position_qty+1")
        with self.assertRaises(PersistenceValidationError):
            self.engine.store.load_cash_scan(result["run_id"])
        code, rows = self.request("GET", "/api/signals")
        self.assertEqual(code, 503)
        self.assertNotIn("items", rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
