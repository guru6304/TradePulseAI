"""Actual cold loopback routing rejects input before application initialization.

Every listener starts with engine/scheduler unset. Forbidden initialization is a
recorded, raising sentinel; permitted requests attach only injected fakes. No
application runtime, provider, operational store or background scheduler starts.
"""
from contextlib import ExitStack
import http.client
import json
import socket
import threading
import unittest
from unittest.mock import Mock, call, patch

import test_bot
import server
from verify_offline import offline_network


BODY_ROUTES = (
    "/api/backtest", "/api/v1/backtest",
    "/api/context-import", "/api/v1/context-import",
    "/api/context-enrich", "/api/v1/context-enrich",
)


class TestTrackAColdHTTP(unittest.TestCase):
    def setUp(self):
        guards = ExitStack()
        self.addCleanup(guards.close)
        offline_network(guards)
        self.configure = guards.enter_context(patch.object(
            server, "configure_server_runtime",
            side_effect=AssertionError("Cold HTTP fixture reached real runtime configuration")))
        self.initializations = []
        self.allow_initialization = False
        self.engine = Mock(spec=["config", "store", "get_broker_status", "run_single_scan"])
        self.engine.store = None
        self.engine.config = Mock(spec=["to_safe_dict"])
        self.engine.config.to_safe_dict.return_value = {"mode": "COLD_HTTP_FAKE_ONLY"}
        self.engine.get_broker_status.return_value = {"connection_state": "FAKE_INJECTED"}
        self.engine.run_single_scan.return_value = {
            "scan_status": "COMPLETED_EMPTY", "total_signals": 0,
            "run_id": "cold-http-injected-scan",
        }
        self.scheduler = Mock(spec=["get_status"])
        self.scheduler.get_status.return_value = {"running": False, "scope": "FAKE_ONLY"}

        def ensure_initialized(handler):
            if handler.engine is not None and handler.scheduler is not None:
                return
            self.initializations.append((handler.command, handler.path))
            if not self.allow_initialization:
                raise AssertionError("Rejected HTTP request initialized a cold runtime")
            type(handler).engine = self.engine
            type(handler).scheduler = self.scheduler

        self.handler = type("ColdHTTPFixtureHandler", (server.DashboardRequestHandler,), {
            "engine": None,
            "scheduler": None,
            "paper_portfolio": None,
            "_ensure_initialized": ensure_initialized,
            "log_message": lambda *args: None,
        })
        self.httpd = server.create_http_server("127.0.0.1", 0, self.handler)
        # The expected pre-fix sentinel failure should become a clear test
        # assertion instead of printing one server traceback per subtest.
        self.server_errors = []
        self.httpd.handle_error = lambda request, address: self.server_errors.append(address)
        self.worker = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.assertFalse(self.worker.is_alive(), "Disposable cold HTTP listener did not stop")
        self.configure.assert_not_called()

    def request(self, method, path, body=b"", headers=(), *, add_length=True,
                hosts=None, eof=False):
        """Preserve exact framing, including duplicate or absent HTTP headers."""
        connection = socket.create_connection(self.httpd.server_address, timeout=3)
        before = len(self.initializations)
        response = None
        try:
            port = self.httpd.server_port
            hosts = [f"127.0.0.1:{port}"] if hosts is None else hosts
            lines = [f"{method} {path} HTTP/1.1", "Connection: close"]
            lines.extend("Host: " + host for host in hosts)
            if method == "POST":
                lines.append("Content-Type: application/json")
                if add_length:
                    lines.append("Content-Length: " + str(len(body)))
            lines.extend(f"{name}: {value}" for name, value in headers)
            connection.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body)
            if eof:
                connection.shutdown(socket.SHUT_WR)
            response = http.client.HTTPResponse(connection, method=method)
            response.begin()
            return response.status, dict(response.getheaders()), response.read()
        except (http.client.HTTPException, OSError):
            if not self.allow_initialization and len(self.initializations) > before:
                self.fail(f"{method} {path} crossed the forbidden cold initialization boundary")
            raise
        finally:
            if response is not None:
                response.close()
            connection.close()

    def assert_cold_response(self, expected, method, path, body=b"", headers=(), **kwargs):
        status, response_headers, raw = self.request(method, path, body, headers, **kwargs)
        self.assertEqual(status, expected, raw)
        self.assertEqual(self.initializations, [], "Rejected request reached runtime initialization")
        self.assertIsNone(self.handler.engine)
        self.assertIsNone(self.handler.scheduler)
        self.assertEqual(self.engine.mock_calls, [])
        self.assertEqual(self.scheduler.mock_calls, [])
        self.assertTrue(response_headers["Content-Type"].startswith("application/json"))
        if method == "HEAD":
            self.assertEqual(raw, b"")
        else:
            self.assertIsInstance(json.loads(raw), dict)
        return response_headers, raw

    def test_unsupported_post_routes_return_405_without_initialization(self):
        for path in ("/api/unknown", "/api/v1/unknown", "/api/config", "/api/v1/config",
                     "/api", "/server.py", "/", "/api/v1/unknown/?ignored=1"):
            with self.subTest(path=path):
                self.assert_cold_response(405, "POST", path)

    def test_unknown_get_and_head_api_routes_return_404_without_initialization(self):
        for method in ("GET", "HEAD"):
            for path in ("/api", "/api/", "/api/v1", "/api/unknown", "/api/v1/unknown",
                         "/api/config-extra", "/api/v1/context-import", "/api/backtest",
                         "/api/v1/unknown/?ignored=1"):
                with self.subTest(method=method, path=path):
                    self.assert_cold_response(404, method, path)

    def test_malformed_json_and_nonobjects_reject_before_initialization(self):
        for path in BODY_ROUTES:
            for body in (b"{", b"[]", b"null", b'"text"', b"\xff"):
                with self.subTest(path=path, body=body):
                    self.assert_cold_response(400, "POST", path, body)

    def test_duplicate_keys_and_nonfinite_json_reject_before_initialization(self):
        for path in BODY_ROUTES:
            for body in (b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}',
                         b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}'):
                with self.subTest(path=path, body=body):
                    self.assert_cold_response(400, "POST", path, body)

    def test_missing_invalid_and_oversized_lengths_reject_before_initialization(self):
        for path in BODY_ROUTES:
            limit = 10 * 1024 * 1024 if path.endswith("/backtest") else 512 * 1024
            for headers in ([], [("Content-Length", "invalid")], [("Content-Length", "-1")],
                            [("Content-Length", "0")], [("Content-Length", str(limit + 1))]):
                with self.subTest(path=path, headers=headers):
                    self.assert_cold_response(400, "POST", path, headers=headers, add_length=False)

    def test_duplicate_lengths_and_transfer_encoding_reject_before_initialization(self):
        for path in BODY_ROUTES:
            cases = (
                [("Content-Length", "2"), ("Content-Length", "2")],
                [("Content-Length", "2"), ("Content-Length", "3")],
                [("Transfer-Encoding", "chunked")],
                [("Transfer-Encoding", "chunked"), ("Content-Length", "2")],
                [("Transfer-Encoding", "gzip"), ("Content-Length", "2")],
            )
            for headers in cases:
                with self.subTest(path=path, headers=headers):
                    self.assert_cold_response(400, "POST", path, headers=headers, add_length=False)

    def test_truncated_complete_json_rejects_before_initialization(self):
        for path in BODY_ROUTES:
            with self.subTest(path=path):
                self.assert_cold_response(400, "POST", path, b"{}",
                    headers=[("Content-Length", "9")], add_length=False, eof=True)

    def test_bad_host_remains_403_before_routing_or_initialization(self):
        port = self.httpd.server_port
        for hosts in ([], ["untrusted.invalid"], [f"user@localhost:{port}"],
                      [f"127.0.0.1:{port + 1}"], [f"127.0.0.1:{port}"] * 2):
            for method, path in (("GET", "/api/unknown"), ("POST", "/api/backtest")):
                with self.subTest(hosts=hosts, method=method):
                    self.assert_cold_response(403, method, path, hosts=hosts)

    def test_foreign_origin_and_cross_site_remain_403_before_initialization(self):
        for headers in ([("Origin", "https://untrusted.invalid")], [("Origin", "null")],
                        [("Sec-Fetch-Site", "cross-site")]):
            for path in ("/api/scan", "/api/v1/scan", *BODY_ROUTES, "/api/unknown"):
                with self.subTest(headers=headers, path=path):
                    response_headers, _ = self.assert_cold_response(403, "POST", path, headers=headers)
                    self.assertNotIn("Access-Control-Allow-Origin", response_headers)

    def test_get_and_head_scan_aliases_remain_405_before_initialization(self):
        for method in ("GET", "HEAD"):
            for path in ("/api/scan", "/api/v1/scan", "/api/v1/scan/?refresh=1"):
                with self.subTest(method=method, path=path):
                    _, raw = self.assert_cold_response(405, method, path)
                    if raw:
                        self.assertEqual(json.loads(raw)["reason_code"], "EXPLICIT_POST_REQUIRED")

    def test_valid_config_then_scan_aliases_share_one_injected_initialization(self):
        self.allow_initialization = True
        origin = f"http://127.0.0.1:{self.httpd.server_port}"
        for path in ("/api/config", "/api/v1/config"):
            with self.subTest(path=path):
                status, _, raw = self.request("GET", path, headers=[("Origin", origin)])
                self.assertEqual(status, 200, raw)
                payload = json.loads(raw)
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(payload["config"], {"mode": "COLD_HTTP_FAKE_ONLY"})
                self.assertEqual(payload["broker_status"], {"connection_state": "FAKE_INJECTED"})
                self.assertEqual(payload["scheduler"], {"running": False, "scope": "FAKE_ONLY"})
        for path in ("/api/scan", "/api/v1/scan"):
            with self.subTest(path=path):
                status, _, raw = self.request("POST", path)
                self.assertEqual(status, 200, raw)
                self.assertEqual(json.loads(raw), self.engine.run_single_scan.return_value)
        self.assertEqual(self.initializations, [("GET", "/api/config")])
        self.assertIs(self.handler.engine, self.engine)
        self.assertIs(self.handler.scheduler, self.scheduler)
        self.assertEqual(self.engine.run_single_scan.call_args_list, [call(), call()])
        self.assertEqual(self.engine.config.to_safe_dict.call_count, 2)
        self.assertEqual(self.engine.get_broker_status.call_count, 2)
        self.assertEqual(self.scheduler.get_status.call_count, 2)
        self.assertEqual(self.server_errors, [])

    def test_valid_scan_can_initialize_injected_runtime_before_config_read(self):
        self.allow_initialization = True
        for method, path in (("POST", "/api/v1/scan"), ("GET", "/api/config"),
                             ("POST", "/api/scan")):
            with self.subTest(method=method, path=path):
                status, _, raw = self.request(method, path)
                self.assertEqual(status, 200, raw)
                payload = json.loads(raw)
                if method == "POST":
                    self.assertEqual(payload, self.engine.run_single_scan.return_value)
                else:
                    self.assertEqual(payload["config"], {"mode": "COLD_HTTP_FAKE_ONLY"})
        self.assertEqual(self.initializations, [("POST", "/api/v1/scan")])
        self.assertEqual(self.engine.run_single_scan.call_args_list, [call(), call()])
        self.assertEqual(self.engine.config.to_safe_dict.call_count, 1)
        self.assertEqual(self.scheduler.get_status.call_count, 1)
        self.assertEqual(self.server_errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
