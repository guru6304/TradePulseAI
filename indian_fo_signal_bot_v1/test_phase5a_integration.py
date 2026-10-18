"""Offline Phase 5A integration: existing SQLite and read-only application routes."""
import copy
import http.client
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from instrument_identity import IdentityValidationError
from server import DashboardRequestHandler, create_http_server
from storage import SQLitePersistenceStore
from strategies import IST


class TestPhase5AApplicationIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tradepulse_offline_phase5a_")
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "integration.sqlite")
        self.store = SQLitePersistenceStore(self.path)
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 16, 10, 35, 5, tzinfo=IST)

    @staticmethod
    def _master_bytes():
        return json.dumps(dict(schema_version="tradepulse.contract-master.v1", provider="upstox", records=[dict(
            provider="upstox", symbol="RELIANCE", identifier="NSE_EQ|INE002A01018", exchange="NSE",
            segment="NSE_EQUITY_INTRADAY", instrument_type="EQ", valid_from="2026-10-01", valid_to="2026-10-31",
            price_unit="INR", quantity_unit="SHARES", lot_size=1, multiplier=1
        )])).encode()

    def _ingest(self):
        return self.store.ingest_contract_master_bytes(self._master_bytes(), provider="upstox",
            source_reference="OFFLINE_SYNTHETIC_DECLARATION", source_version="OFFLINE_V1",
            captured_at="2026-10-16T09:00:00+05:30")

    def test_transaction_rolls_back_reservation_and_event_together(self):
        for store in (self.store, SQLitePersistenceStore(":memory:")):
            self.addCleanup(store.close)
            with self.assertRaisesRegex(RuntimeError, "OFFLINE failure"):
                with store.paper_transaction() as conn:
                    conn.execute("INSERT INTO paper_accounts VALUES (?, ?, ?, ?)", ("rollback", "hash", "{}", "stamp"))
                    conn.execute("INSERT INTO paper_positions VALUES (?, ?, ?, ?)", ("position", "rollback", "entry", "{}"))
                    conn.execute("INSERT INTO paper_events VALUES (?, ?, ?, ?, ?, ?)",
                                 ("event", "rollback", "entry", "ENTRY", "position", "{}"))
                    raise RuntimeError("OFFLINE failure")
            self.assertEqual(store.list_paper_accounts(), [])
            with store.paper_transaction(write=False) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM paper_events").fetchone()[0], 0)

    def test_read_context_enforces_no_writes_and_restores_memory_connection(self):
        for store in (self.store, SQLitePersistenceStore(":memory:")):
            self.addCleanup(store.close)
            with self.assertRaises(sqlite3.OperationalError):
                with store.paper_transaction(write=False) as conn:
                    conn.execute("INSERT INTO paper_accounts VALUES ('blocked', 'hash', '{}', 'stamp')")
            self.assertEqual(store.list_paper_accounts(), [])
            with store.paper_transaction() as conn:
                conn.execute("INSERT INTO paper_accounts VALUES ('allowed', 'hash', '{}', 'stamp')")
            self.assertEqual(self.store.list_paper_accounts()[0]["account_id"], "allowed")
            self.assertEqual(store.list_paper_accounts()[0]["account_id"], "allowed")

    def test_additive_migration_preserves_existing_scan_history(self):
        self.store.record_scan_run(run_id="existing", started_at_ist="2026-10-16 10:30:00",
            completed_at_ist="2026-10-16 10:30:01", duration_ms=1, status="COMPLETED_EMPTY",
            broker="OFFLINE", data_mode="SIMULATED", is_simulated=True)
        self.store.close()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            for table in ("paper_events", "paper_positions", "paper_accounts", "contract_master_candidates"):
                conn.execute("DROP TABLE " + table)
        restarted = SQLitePersistenceStore(self.path)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.query_scan_runs()["total_count"], 1)
        self.assertEqual(restarted.list_paper_accounts(), [])
        self.assertEqual(restarted.list_contract_master_candidates(), [])

    def test_retained_contract_declaration_reparses_after_restart_and_rejects_tamper(self):
        master = self._ingest()
        self.assertEqual(master["status"], "BLOCKED_UNQUALIFIED_MASTER")
        self.assertFalse(master["eligible"])
        self.assertEqual(self._ingest()["master_id"], master["master_id"])
        self.assertEqual(len(self.store.list_contract_master_candidates()), 1)
        restarted = SQLitePersistenceStore(self.path)
        self.addCleanup(restarted.close)
        request = dict(provider="upstox", instrument_type="EQ", as_of="2026-10-16", identifier="NSE_EQ|INE002A01018")
        report = restarted.inspect_contract_resolution(master["master_id"], **request)
        self.assertFalse(report["eligible"])
        self.assertEqual(report["status"], "BLOCKED_UNQUALIFIED_MASTER")
        with restarted.paper_transaction() as conn:
            conn.execute("UPDATE contract_master_candidates SET original_bytes=? WHERE master_id=?",
                         (b'{}', master["master_id"]))
        with self.assertRaises(IdentityValidationError) as blocked:
            restarted.get_contract_master_candidate(master["master_id"])
        self.assertEqual(blocked.exception.rejection["reason_code"], "CONTRACT_MASTER_INTEGRITY_FAILURE")

    def test_http_inspection_is_read_only_and_cannot_create_accounts_or_issue_receipts(self):
        master = self._ingest()
        engine = SimpleNamespace(store=self.store, _now_ist=lambda: self.now)
        handler = type("OfflineInspectionHandler", (DashboardRequestHandler,), {"engine": engine, "scheduler": object()})
        server = create_http_server("127.0.0.1", 0, handler_cls=handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.addCleanup(stop)
        with patch("urllib.request.urlopen", side_effect=AssertionError("Broker transport forbidden")), \
                patch("scanner_engine.IntradayBotEngine.run_single_scan", side_effect=AssertionError("Scan forbidden")), \
                patch("telegram_bot.TelegramSignalDispatcher.send_signal", side_effect=AssertionError("Delivery forbidden")):
            for prefix in ("/api", "/api/v1"):
                for method, route, expected in (
                    ("GET", "/paper-accounts", 200),
                    ("GET", "/paper-portfolio?account_id=absent", 404),
                    ("HEAD", "/paper-portfolio?account_id=absent", 404),
                    ("GET", "/paper-portfolio?account_id=a&account_id=b", 400),
                    ("GET", "/contract-masters?provider=upstox", 200),
                    ("GET", "/contract-resolution?master_id=" + master["master_id"] +
                     "&provider=upstox&instrument_type=EQ&as_of=2026-10-16&identifier=NSE_EQ%7CINE002A01018", 200),
                    ("GET", "/contract-resolution?master_id=absent", 400),
                    ("POST", "/paper-portfolio?account_id=absent", 405),
                ):
                    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                    self.addCleanup(connection.close)
                    connection.request(method, prefix + route)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected, (method, route))
                    body = response.read()
                    self.assertEqual(response.getheader("Cache-Control"), "no-store")
                    if method == "HEAD":
                        self.assertEqual(body, b'')
                    elif response.status == 200 and "contract-resolution" in route:
                        self.assertFalse(json.loads(body)["eligible"])
                    connection.close()
        self.assertEqual(self.store.list_paper_accounts(), [])
        self.assertIsNone(self.store.load_live_acceptance_evidence("upstox", "RELIANCE"))
        self.assertEqual(self.store.check_health()["signals_count"], 0)

    def test_actual_adapter_scanner_candidate_to_durable_paper_entry_exit_and_read_report(self):
        # Reuse the established OFFLINE wire scenario; actual validators,
        # evaluator, sizing, signal storage and dry-run formatting all execute.
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        from paper_portfolio import PaperAccountConfig, PaperPortfolio
        from readiness_policy import execution_gate
        scenario = TestPhase4OfflineEndToEnd()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        engine = scenario._engine("upstox", database="scanner_to_paper.sqlite")
        scanned, evaluator, sizing = scenario._scan(engine)
        scenario._assert_candidate(engine, scanned, evaluator, sizing)
        candidate = copy.deepcopy(scanned["signals"][0])
        before_candidate = copy.deepcopy(candidate)
        paper = PaperPortfolio(engine.store, PaperAccountConfig(account_id="integrated-paper",
            run_id="offline-phase5a", provider="upstox", source_data_mode="LIVE"), clock=lambda: scenario.now)
        scenario.now += timedelta(minutes=5)
        price = candidate["entry_price"]
        entry_bar = dict(timestamp="2026-10-16T14:15:00+05:30", open=price, high=price + .2,
            low=price - .2, close=price + .1, volume=10000, interval_min=5, is_complete=True,
            data_mode="LIVE", is_simulated=False, instrument_identity=copy.deepcopy(candidate["instrument_identity"]))
        entry = paper.enter(candidate, entry_bar, event_key="entry")
        self.assertEqual(entry["status"], "OPEN")
        self.assertEqual(entry["execution_mode"], "SIMULATED")
        self.assertTrue(paper.enter(candidate, entry_bar, event_key="entry")["idempotent"])
        self.assertEqual(candidate, before_candidate)
        report = engine.store.get_paper_portfolio_report("integrated-paper", as_of=scenario.now)
        self.assertEqual(report["reconciliation"]["status"], "OK")
        self.assertEqual(report["accounting"]["open_positions"], 1)
        self.assertGreater(report["accounting"]["reserved_capital_inr"], 0)
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = engine
        sent_before = set(engine.telegram.sent_cache)
        code, api_report = handler._handle_paper_portfolio({"account_id": ["integrated-paper"]})
        self.assertEqual(code, 200)
        self.assertEqual(api_report["config_hash"], report["config_hash"])
        scenario.now += timedelta(minutes=5)
        exit_bar = dict(entry_bar, timestamp="2026-10-16T14:20:00+05:30", high=candidate["target_1"] + 1)
        closed = paper.process_bar(entry["position_id"], exit_bar, event_key="exit")
        self.assertEqual(closed["status"], "CLOSED")
        after = paper.snapshot()
        self.assertEqual(after["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(after["accounting"]["closed_positions"], 1)
        self.assertTrue(paper.process_bar(entry["position_id"], exit_bar, event_key="exit")["idempotent"])
        self.assertEqual(paper.snapshot()["accounting"], after["accounting"])
        recovered = SQLitePersistenceStore(engine.store.database_url)
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.get_paper_portfolio_report("integrated-paper", as_of=scenario.now)["accounting"],
                         after["accounting"])
        self.assertEqual(engine.store.query_signals()["total_count"], 1)
        self.assertEqual(engine.telegram.sent_cache, sent_before)
        self.assertFalse(execution_gate(engine.config, engine.store, "upstox", "RELIANCE", "strat_1_order_block",
                                        data_mode="LIVE", now=scenario.now)["allowed"])
        self.assertIsNone(engine.store.load_live_acceptance_evidence("upstox", "RELIANCE"))
        self.assertEqual(scenario.forbidden_requests, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
