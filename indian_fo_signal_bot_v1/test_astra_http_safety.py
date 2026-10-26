"""Real loopback HTTP method boundary; no market/provider transport."""
import http.client
import threading
import unittest
from unittest.mock import Mock

import test_bot
from server import DashboardRequestHandler, create_http_server


class TestAstraReadSafety(unittest.TestCase):
    def setUp(self):
        self.engine = Mock()
        self.engine.run_single_scan.return_value = dict(scan_status="COMPLETED_EMPTY", total_signals=0)
        self.paper = object()
        class Handler(DashboardRequestHandler):
            def log_message(self, *args):
                pass
        Handler.engine = self.engine
        Handler.scheduler = Mock()
        Handler.paper_portfolio = self.paper
        self.server = create_http_server(port=0, handler_cls=Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def request(self, method, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            status, body = response.status, response.read()
            return status, body
        finally:
            connection.close()

    def test_get_and_head_scan_aliases_cannot_reach_scanner_or_paper(self):
        for method in ("GET", "HEAD"):
            for path in ("/api/scan", "/api/v1/scan", "/api/scan/?refresh=1"):
                with self.subTest(method=method, path=path):
                    status, body = self.request(method, path)
                    self.assertEqual(status, 405)
                    self.engine.run_single_scan.assert_not_called()
                    if method == "HEAD":
                        self.assertEqual(body, b"")

    def test_post_scan_remains_explicit_paper_consumer(self):
        status, body = self.request("POST", "/api/scan")
        self.assertEqual(status, 200)
        self.assertIn(b"COMPLETED_EMPTY", body)
        self.engine.run_single_scan.assert_called_once_with(paper_portfolio=self.paper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
