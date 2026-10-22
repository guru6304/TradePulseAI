"""Actual local HTTP boundary; blocks browser origin and Host rebinding."""
import http.client
import unittest
from unittest.mock import patch

import test_bot


class TestLocalAPISecurity(unittest.TestCase):
    def setUp(self):
        from test_cash_workflow import TestCashWorkflow
        self.workflow = TestCashWorkflow()
        self.workflow.setUp()
        self.addCleanup(self.workflow.doCleanups)

    def request(self, method, path, headers=None):
        conn = http.client.HTTPConnection(*self.workflow.server.server_address, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            response.read()
            return response.status, response.getheader("Access-Control-Allow-Origin")
        finally:
            conn.close()

    def test_foreign_origin_cannot_scan_or_read_local_records(self):
        with patch.object(self.workflow.engine, "run_single_scan", return_value={}) as scan:
            for method, route in (("POST", "/api/scan"), ("GET", "/api/scan"), ("GET", "/api/signals"), ("OPTIONS", "/api/scan")):
                code, cors = self.request(method, route, {"Origin": "https://untrusted.invalid"})
                self.assertEqual(code, 403)
                self.assertIsNone(cors)
            scan.assert_not_called()

    def test_dns_rebinding_host_and_cross_site_requests_are_rejected(self):
        for headers in ({"Host": "untrusted.invalid"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Origin": "null"}, {"Host": "user@localhost"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", "/api/health", headers)[0], 403)

    def test_same_origin_and_local_cli_keep_existing_read_and_scan_contract(self):
        host, port = self.workflow.server.server_address
        origin = f"http://{host}:{port}"
        self.assertEqual(self.request("GET", "/api/signals", {"Origin": origin})[0], 200)
        self.assertEqual(self.request("POST", "/api/scan", {"Origin": origin})[0], 200)
        self.assertEqual(self.request("OPTIONS", "/api/scan"), (204, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
