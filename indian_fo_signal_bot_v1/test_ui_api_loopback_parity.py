"""Real Loopback Integration Test for UI/API Contract Parity (U1-C).

Verifies actual server.py handler routing, exact endpoint paths, query validation,
DTO shapes, account scoping, and local Host/Origin restrictions against
a live disposable ThreadingHTTPServer.
"""
from contextlib import ExitStack
import http.client
import json
import socket
import threading
import unittest
from unittest.mock import Mock, patch

import server
from verify_offline import offline_network


class TestUiApiLoopbackParity(unittest.TestCase):
    def setUp(self):
        guards = ExitStack()
        self.addCleanup(guards.close)
        offline_network(guards)
        guards.enter_context(patch(
            "candle_lineage.annotate_signals",
            side_effect=lambda store, items, account_id=None: None))
        guards.enter_context(patch.object(
            server, "configure_server_runtime",
            side_effect=AssertionError("Loopback fixture reached forbidden production runtime configuration")))

        self.engine = Mock(spec=[
            "config", "store", "get_broker_status", "run_single_scan", "_now_ist", "last_scan_summary",
            "paper_portfolio",
        ])
        self.engine._now_ist.return_value = "2026-11-03T10:00:00+05:30"
        self.engine.last_scan_summary = {
            "run_id": "test-run-001",
            "scan_status": "COMPLETED",
            "started_at_ist": "2026-11-03T09:15:00+05:30",
            "completed_at_ist": "2026-11-03T09:15:05+05:30",
            "duration_ms": 5000,
            "total_signals": 1,
            "persistence_status": "COMMITTED",
        }
        self.engine.config = Mock()
        self.engine.config.active_broker = "paper_sim"
        self.engine.config.equity_watchlist = [{"symbol": "RELIANCE"}]
        self.engine.config.to_safe_dict.return_value = {"mode": "LOOPBACK_TEST"}

        self.engine.get_broker_status.return_value = {
            "active_broker": "paper_sim",
            "broker_name": "Paper Simulation",
            "connection_state": "SIMULATED",
            "is_simulated": True,
            "data_mode": "SIMULATED",
            "connectivity_verified": True,
            "last_verified_at_ist": "2026-11-03T09:15:00+05:30",
            "last_candle_timestamp_ist": "2026-11-03T09:15:00+05:30",
            "candle_freshness": {"status": "CURRENT"},
            "live_signals_allowed": False,
            "error_category": "NONE",
            "stream": {"status": "LIVE"},
        }

        # Mock store with realistic fixtures
        self.store = Mock()
        self.store.check_health.return_value = {"status": "ok"}
        self.store.pending_cash_scans.return_value = []
        self.store.list_notification_outbox.return_value = {"counts": {}}
        self.store.query_signals.return_value = {
            "total_count": 1,
            "limit": 50,
            "offset": 0,
            "items": [{
                "id": 1,
                "dedup_key": "cand-001",
                "symbol": "RELIANCE",
                "segment": "NSE_EQUITY_INTRADAY",
                "strategy_id": "strat_1_order_block",
                "strategy_name": "Order Block / BOS",
                "direction": "LONG",
                "position_type": "LONG_EQUITY_INTRADAY",
                "entry_price": 2845.5,
                "entry_zone_low": 2820.0,
                "entry_zone_high": 2845.5,
                "stop_loss": 2800.0,
                "invalidation_level": 2795.0,
                "target_1": 2900.0,
                "target_2": 2950.0,
                "timestamp": "2026-11-03T09:15:00+05:30",
                "actionable": False,
                "instrument_identity": {
                    "provider": "paper_sim",
                    "identifier": "2885",
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "segment": "NSE_EQUITY_INTRADAY",
                    "instrument_type": "EQ",
                    "is_index": False,
                },
            }],
        }
        self.store.query_paper_accounts.return_value = {
            "status": "ok",
            "execution_mode": "SIMULATED",
            "accounts": [{
                "account_id": "paper_sim_default",
                "config_hash": "a" * 64,
                "created_at_ist": "2026-11-03T09:00:00+05:30",
                "execution_mode": "SIMULATED",
            }],
            "next_cursor": None,
            "through_sequence": 1,
            "truncated": False,
        }
        self.store.get_paper_portfolio_report.return_value = {
            "status": "OK",
            "account_id": "paper_sim_default",
            "run_id": "test-run-001",
            "config_hash": "a" * 64,
            "provider": "paper_sim",
            "source_data_mode": "SIMULATED",
            "execution_mode": "SIMULATED",
            "fill_policy": "NEXT_BAR_OPEN",
            "as_of_ist": "2026-11-03T10:00:00+05:30",
            "reconciliation": {"status": "OK", "errors": []},
            "accounting": {
                "starting_capital_inr": 1000000,
                "realized_net_pnl_inr": 12500,
                "unrealized_net_pnl_inr": 0,
                "equity_inr": 1012500,
                "reserved_capital_inr": 0,
                "available_capital_inr": 1012500,
                "gross_exposure_inr": 0,
                "fees_paid_inr": 240,
                "slippage_paid_inr": 180,
                "open_positions": 0,
                "closed_positions": 2,
            },
            "positions": [],
            "events": [],
            "candidate_decisions": [],
            "total_positions": 0,
            "total_events": 0,
            "total_candidate_decisions": 0,
            "previews_truncated": {
                "positions": False,
                "events": False,
                "candidate_decisions": False,
            },
        }
        self.store.load_cash_scan.return_value = {
            "run_id": "test-run-001",
            "status": "COMMITTED",
            "work_id": "work-001",
            "version": "v1",
            "reference": "2026-11-03T09:15:00+05:30",
            "code_digest": "c" * 64,
            "profile_digest": "p" * 64,
            "snapshot": {
                "batches": [{
                    "batch_id": "batch-reliance-001",
                    "identity": {
                        "provider": "paper_sim",
                        "identifier": "2885",
                        "symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQUITY_INTRADAY",
                        "instrument_type": "EQ",
                        "is_index": False,
                    },
                    "interval_min": 5,
                    "candle_count": 2,
                    "first_timestamp": "2026-11-03T09:15:00+05:30",
                    "last_timestamp": "2026-11-03T09:20:00+05:30",
                    "validation": {},
                    "retrieved_at": "2026-11-03T09:20:05+05:30",
                    "source_observation_at": None,
                    "content": {
                        "candles": [
                            {"timestamp": "2026-11-03T09:15:00+05:30", "open": 2840, "high": 2855, "low": 2835, "close": 2850, "volume": 10000, "interval_min": 5, "is_complete": True},
                            {"timestamp": "2026-11-03T09:20:00+05:30", "open": 2850, "high": 2860, "low": 2845, "close": 2855, "volume": 12000, "interval_min": 5, "is_complete": True},
                        ],
                    },
                }],
            },
        }

        self.engine.store = self.store

        self.scheduler = Mock(spec=["get_status"])
        self.scheduler.get_status.return_value = {
            "running": True,
            "enabled_in_config": True,
            "session_open": True,
            "session_state": "OPEN",
            "session_start_ist": "09:15",
            "session_end_ist": "15:30",
            "scan_interval_seconds": 300,
            "cycles_executed": 4,
            "configured_holidays": [],
        }

        paper_mock = Mock()
        paper_mock.config.account_id = "paper_sim_default"
        self.engine.paper_portfolio = paper_mock

        def ensure_initialized(handler):
            type(handler).engine = self.engine
            type(handler).scheduler = self.scheduler
            type(handler).paper_portfolio = paper_mock

        self.handler = type("ParityTestHandler", (server.DashboardRequestHandler,), {
            "engine": None,
            "scheduler": None,
            "paper_portfolio": paper_mock,
            "_ensure_initialized": ensure_initialized,
            "log_message": lambda *args: None,
        })

        self.httpd = server.create_http_server("127.0.0.1", 0, self.handler)
        self.worker = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.worker.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)

    def request(self, method, path, headers=None):
        port = self.httpd.server_port
        default_headers = {
            "Host": f"127.0.0.1:{port}",
            "Connection": "close",
            "Accept": "application/json",
        }
        if headers:
            default_headers.update(headers)

        conn = socket.create_connection(self.httpd.server_address, timeout=3)
        try:
            lines = [f"{method} {path} HTTP/1.1"]
            for k, v in default_headers.items():
                lines.append(f"{k}: {v}")
            conn.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
            resp = http.client.HTTPResponse(conn, method=method)
            resp.begin()
            status = resp.status
            body = resp.read()
            return status, json.loads(body.decode("utf-8")) if body else {}
        finally:
            conn.close()

    def test_rankings_alias_does_not_exist_and_returns_404(self):
        """Item 1: /api/rankings does not exist; server returns 404."""
        status, body = self.request("GET", "/api/rankings")
        self.assertEqual(status, 404)
        self.assertEqual(body.get("error_type"), "NotFoundError")

    def test_opportunity_rankings_rejects_page_parameter_with_400(self):
        """Item 2: /api/opportunity-rankings rejects client 'page' with 400."""
        status, body = self.request("GET", "/api/opportunity-rankings?page=1&limit=20")
        self.assertEqual(status, 400)
        self.assertEqual(body.get("message"), "Invalid ranking query.")

    def test_cash_candles_batch_does_not_exist_and_returns_404(self):
        """Item 3: /api/cash-candles-batch does not exist; returns 404."""
        status, body = self.request("GET", "/api/cash-candles-batch?symbol=RELIANCE")
        self.assertEqual(status, 404)
        self.assertEqual(body.get("error_type"), "NotFoundError")

    def test_cash_candles_requires_both_run_id_and_batch_id(self):
        """Item 3: /api/cash-candles rejects invalid query and requires existing batch_id."""
        # Unapproved query param returns 400
        status, body = self.request("GET", "/api/cash-candles?run_id=test-run-001&symbols=RELIANCE")
        self.assertEqual(status, 400)
        self.assertEqual(body.get("message"), "Invalid cash-lineage query.")

        # Missing or non-existent batch_id returns 404 NOT_FOUND
        status, body = self.request("GET", "/api/cash-candles?run_id=test-run-001")
        self.assertEqual(status, 404)
        self.assertEqual(body.get("status"), "NOT_FOUND")

        # With both run_id and matching batch_id, returns 200
        status, body = self.request("GET", "/api/cash-candles?run_id=test-run-001&batch_id=batch-reliance-001")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("run_id"), "test-run-001")
        self.assertEqual(body.get("batch_id"), "batch-reliance-001")
        self.assertEqual(len(body.get("items", [])), 2)

    def test_signal_lineage_does_not_exist_and_returns_404(self):
        """Item 4: /api/signal-lineage does not exist; returns 404."""
        status, body = self.request("GET", "/api/signal-lineage?symbol=RELIANCE")
        self.assertEqual(status, 404)
        self.assertEqual(body.get("error_type"), "NotFoundError")

    def test_signals_supports_exact_filter_parameters(self):
        """Item 4: /api/signals returns 200 list envelope with items."""
        status, body = self.request("GET", "/api/signals?symbol=RELIANCE&limit=50&offset=0")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertIn("items", body)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["symbol"], "RELIANCE")

    def test_paper_portfolio_requires_account_id_and_rejects_unscoped_request(self):
        """Item 5: /api/paper-portfolio without account_id returns 400."""
        status, body = self.request("GET", "/api/paper-portfolio")
        self.assertEqual(status, 400)
        self.assertEqual(body.get("message"), "Invalid paper-report query.")

        # With account_id returns 200
        status, body = self.request("GET", "/api/paper-portfolio?account_id=paper_sim_default")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("account_id"), "paper_sim_default")
        self.assertEqual(body.get("status"), "OK")

    def test_paper_accounts_discovery_returns_200(self):
        """Item 5: /api/paper-accounts returns list of configured accounts."""
        status, body = self.request("GET", "/api/paper-accounts?limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(len(body.get("accounts", [])), 1)

    def test_health_dto_exact_structure(self):
        """Item 6: /api/health contains actual DTO fields, no market_state or clock_drift."""
        status, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertIn("status", body)
        self.assertIn("broker", body)
        self.assertIn("scheduler", body)
        self.assertIn("database", body)
        self.assertIn("paper_account_id", body)
        self.assertIn("operations", body)
        self.assertIn("live_acceptance", body)
        self.assertEqual(body.get("paper_account_id"), "paper_sim_default")
        # Ensure assumed non-existent fields are absent
        self.assertNotIn("market_state", body)
        self.assertNotIn("clock_drift", body)

    def test_host_origin_security_and_vite_proxy_behavior(self):
        """Verify server.py local same-origin enforcement."""
        port = self.httpd.server_port

        # Case 1: Same origin (Host 127.0.0.1:<port> + Origin http://127.0.0.1:<port>) -> 200
        status, _ = self.request("GET", "/api/health", headers={
            "Origin": f"http://127.0.0.1:{port}",
        })
        self.assertEqual(status, 200)

        # Case 2: Mismatched origin (Vite dev server default: Origin http://localhost:5173 without proxy rewrite) -> 403
        status, body = self.request("GET", "/api/health", headers={
            "Origin": "http://localhost:5173",
        })
        self.assertEqual(status, 403)
        self.assertEqual(body.get("reason_code"), "LOCAL_SAME_ORIGIN_REQUIRED")

        # Case 3: Cross-site fetch (Sec-Fetch-Site: cross-site) -> 403
        status, body = self.request("GET", "/api/health", headers={
            "Sec-Fetch-Site": "cross-site",
        })
        self.assertEqual(status, 403)
        self.assertEqual(body.get("reason_code"), "LOCAL_SAME_ORIGIN_REQUIRED")


if __name__ == "__main__":
    unittest.main()
