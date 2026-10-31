"""Actual served terminal aliases/CSP stay read-only before runtime creation."""
import http.client
from pathlib import Path
import threading
import unittest

import test_bot
from server import DashboardRequestHandler, PUBLIC_WEB_DIR, create_http_server


class TestTrackATerminalHTTP(unittest.TestCase):
    def setUp(self):
        self.initializations = []
        def forbidden(handler):
            self.initializations.append(True)
            raise AssertionError("Static navigation initialized application runtime")
        handler = type('StaticOnlyTerminal', (DashboardRequestHandler,), dict(
            engine=None, scheduler=None, _ensure_initialized=forbidden, log_message=lambda *args: None))
        self.server = create_http_server('127.0.0.1', 0, handler)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.worker.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.initializations, [])

    def request(self, path, method='GET'):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_entry_aliases_serve_exact_new_local_bundle_without_initializing(self):
        expected = (Path(PUBLIC_WEB_DIR)/'terminal.html').read_bytes()
        for path in ('/', '/index.html', '/public/index.html', '/INDEX.HTML', '/terminal.html',
                     '/?demo=true&mode=LIVE_VERIFIED'):
            with self.subTest(path=path):
                code, headers, raw = self.request(path)
                self.assertEqual(code, 200)
                self.assertEqual(raw, expected)
                self.assertEqual(headers['X-Frame-Options'], 'DENY')
                self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
                csp = headers['Content-Security-Policy']
                self.assertIn("script-src 'self'", csp)
                self.assertIn("connect-src 'self'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertNotIn('unsafe-inline', csp)
                self.assertNotIn('unsafe-eval', csp)
                self.assertNotIn(b'https://', raw)
                self.assertIn(b'/terminal.js', raw)
                self.assertIn(b'/terminal.css', raw)
        code, headers, raw = self.request('/', 'HEAD')
        self.assertEqual((code, raw), (200, b''))
        self.assertEqual(int(headers['Content-Length']), len(expected))

    def test_script_styles_and_private_404s_do_not_create_runtime(self):
        for name, mime in (('terminal.js','application/javascript'), ('terminal.css','text/css')):
            code, headers, raw = self.request('/'+name)
            self.assertEqual(code, 200)
            self.assertTrue(headers['Content-Type'].startswith(mime))
            self.assertEqual(raw, (Path(PUBLIC_WEB_DIR)/name).read_bytes())
        for path in ('/.env','/server.py','/public/../.env','/%2e%2e/.env','/public/.git/config'):
            with self.subTest(path=path):
                code, _, raw = self.request(path)
                self.assertEqual(code, 404)
                self.assertNotIn(b'ANGEL_API_KEY', raw)

