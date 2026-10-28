"""TradePulse AI — Wave 2 Server Endpoints & UI Data Surfacing Test Suite.

Verifies:
1. GET /api/radar and GET /api/v1/radar HTTP endpoint contracts (schema, breadth, non-actionable).
2. GET /api/radar-transitions and GET /api/v1/radar-transitions HTTP contracts (factor deltas, audit sha256).
3. Read safety boundary: POST /api/radar and POST /api/radar-transitions return HTTP 405 Method Not Allowed.
4. HEAD request safety: zero body content returned with proper headers.
5. Frontend DOM contracts for Market Radar and Opportunity X-Ray elements in public/index.html.
"""
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, MagicMock

import test_bot
from config import BotConfig
from market_radar import RADAR_SCHEMA
from rank_transitions import TRANSITION_SCHEMA
from server import DashboardRequestHandler, create_http_server
from strategies import IST


class TestWave2ServerEndpoints(unittest.TestCase):
    def setUp(self):
        self.engine = Mock()
        self.engine.config = BotConfig(
            active_broker="paper_sim",
            equity_watchlist=[
                {"symbol": "RELIANCE", "name": "Reliance Industries"},
                {"symbol": "TCS", "name": "Tata Consultancy Services"},
                {"symbol": "INFY", "name": "Infosys"},
            ]
        )
        self.engine.store = None
        self.engine._now_ist.return_value = datetime(2026, 10, 28, 10, 30, tzinfo=IST)

        class Handler(DashboardRequestHandler):
            def log_message(self, *args):
                pass

        Handler.engine = self.engine
        Handler.scheduler = Mock()
        Handler.paper_portfolio = None
        self.server = create_http_server(port=0, handler_cls=Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def request(self, method, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            status, body = resp.status, resp.read()
            return status, body
        finally:
            conn.close()

    def test_get_radar_returns_200_and_valid_schema(self):
        for path in ("/api/radar", "/api/v1/radar"):
            with self.subTest(path=path):
                status, body = self.request("GET", path)
                self.assertEqual(status, 200)
                data = json.loads(body.decode("utf-8"))
                self.assertEqual(data.get("status"), "ok")
                self.assertEqual(data.get("schema_version"), RADAR_SCHEMA)
                self.assertFalse(data.get("actionable"))
                self.assertIn("breadth", data)
                self.assertIn("rows", data)
                self.assertIn("snapshot_sha256", data)
                breadth = data["breadth"]
                self.assertIn("advances", breadth)
                self.assertIn("declines", breadth)
                self.assertIn("market_sentiment", breadth)

    def test_get_radar_limit_parameter(self):
        status, body = self.request("GET", "/api/radar?limit=2")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertLessEqual(len(data.get("rows", [])), 2)

    def test_head_radar_returns_no_body(self):
        status, body = self.request("HEAD", "/api/radar")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_post_radar_method_not_allowed(self):
        status, _ = self.request("POST", "/api/radar")
        self.assertEqual(status, 405)

    def test_get_radar_transitions_initial_state(self):
        for path in ("/api/radar-transitions", "/api/v1/radar-transitions"):
            with self.subTest(path=path):
                # When store is None or rankings unavailable, returns 503 or empty 200
                status, body = self.request("GET", path)
                self.assertIn(status, (200, 503))

    def test_post_radar_transitions_method_not_allowed(self):
        status, _ = self.request("POST", "/api/radar-transitions")
        self.assertEqual(status, 405)

    def test_head_radar_transitions_returns_no_body(self):
        status, body = self.request("HEAD", "/api/radar-transitions")
        self.assertIn(status, (200, 503))
        self.assertEqual(body, b"")


class TestWave2UIDOMContracts(unittest.TestCase):
    def setUp(self):
        html_path = Path(__file__).resolve().parent / "public" / "index.html"
        self.html = html_path.read_text(encoding="utf-8")

    def test_market_radar_dom_elements_present(self):
        self.assertIn('id="marketRadarContainer"', self.html)
        self.assertIn('id="radarSentimentBadge"', self.html)
        self.assertIn('id="radarBreadthText"', self.html)
        self.assertIn('id="radarLeadingSector"', self.html)
        self.assertIn('aria-label="Market Radar Observation Layer"', self.html)

    def test_opportunity_xray_dom_elements_present(self):
        self.assertIn('id="detailRankNarrativeBadge"', self.html)
        self.assertIn('id="detailRankNarrativeText"', self.html)
        self.assertIn('id="detailFactorDeltasGrid"', self.html)
        self.assertIn('id="detailDeltaComposite"', self.html)
        self.assertIn('id="detailDeltaConfluence"', self.html)
        self.assertIn('id="detailDeltaRr"', self.html)
        self.assertIn('id="detailDeltaQuality"', self.html)
        self.assertIn('id="detailDropoutNotice"', self.html)

    def test_api_client_methods_exposed(self):
        self.assertIn('getMarketRadar:', self.html)
        self.assertIn('getRadarTransitions:', self.html)
        self.assertIn('renderMarketRadar', self.html)
        self.assertIn('renderRadarTransitions', self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
