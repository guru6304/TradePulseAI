"""Disposable loopback HTTP framing and startup exposure regressions.

No provider, order transport, operational store or application startup is used.
Invalid bodies must fail before backtest construction or any engine/store call.
"""
from contextlib import ExitStack
import http.client
import ipaddress
import json
import queue
import socket
import socketserver
import threading
import time
import unittest
from unittest.mock import Mock, patch

import test_bot  # Existing credential-free test bootstrap.
import server
from verify_offline import offline_network


class TestTrackASecurity(unittest.TestCase):
    def setUp(self):
        guard = ExitStack()
        offline_network(guard)
        self.addCleanup(guard.close)
        self.engine = Mock(name='uninvoked_fixture_engine')
        self.engine.store = Mock(name='uninvoked_fixture_store')
        self.engine.config.account_capital_inr = 100000.0
        self.engine.config.max_risk_per_trade_pct = 1.0
        self.engine.config.max_daily_loss_inr = 2000.0
        self.engine.config.daily_profit_target_inr = 4000.0
        self.engine.get_broker_status.return_value = {'active_broker': 'paper_sim', 'is_simulated': True}
        handler = type('BoundedBodyFixtureHandler', (server.DashboardRequestHandler,), dict(
            engine=self.engine, scheduler=Mock(name='fixture_scheduler'), paper_portfolio=None,
            HEADER_TIMEOUT_SECONDS=0.15, JSON_BODY_TIMEOUT_SECONDS=0.15, log_message=lambda *args: None))
        self.httpd = server.create_http_server('127.0.0.1', 0, handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.backtest = guard.enter_context(patch('backtest_engine.DeterministicBacktestEngine',
            side_effect=AssertionError('Rejected body reached backtest execution boundary')))

    def close_server(self):
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()
        self.assertFalse(self.thread.is_alive(), 'Disposable HTTP listener failed to stop')

    def body(self):
        return json.dumps(dict(strategy_id='strat_4_orb_filtered', symbol='RELIANCE',
            data_mode='SIMULATED', candles=[], persist_run=False)).encode('ascii')

    def raw_request(self, route, body=b'', headers=(), *, eof=False):
        """Send exact framing, including duplicates, without HTTP client normalization."""
        connection = socket.create_connection(self.httpd.server_address, timeout=2)
        try:
            port = self.httpd.server_port
            lines = [f'POST {route} HTTP/1.1', f'Host: 127.0.0.1:{port}',
                     'Content-Type: application/json', 'Connection: close']
            lines.extend(f'{name}: {value}' for name, value in headers)
            connection.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + body)
            if eof:
                connection.shutdown(socket.SHUT_WR)
            response = http.client.HTTPResponse(connection)
            try:
                response.begin()
                return response.status, response.read()
            finally:
                response.close()
        finally:
            connection.close()

    def assert_rejected_without_effects(self, route, body=b'', headers=(), **kwargs):
        code, raw = self.raw_request(route, body, headers, **kwargs)
        self.assertEqual(code, 400, raw)
        self.assertIsInstance(json.loads(raw), dict)
        self.backtest.assert_not_called()
        self.assertEqual(self.engine.mock_calls, [], 'Rejected request reached engine/provider boundary')
        self.assertEqual(self.engine.store.mock_calls, [], 'Rejected request reached persistence boundary')

    def test_backtest_rejects_duplicate_content_length_before_execution(self):
        body = self.body()
        for route in ('/api/backtest', '/api/v1/backtest'):
            for second in (len(body), len(body) + 1):
                with self.subTest(route=route, second_length=second):
                    self.assert_rejected_without_effects(route, body,
                        [('Content-Length', len(body)), ('Content-Length', second)])

    def test_backtest_rejects_transfer_encoding_with_or_without_length(self):
        body = self.body()
        for route in ('/api/backtest', '/api/v1/backtest'):
            for coding in ('chunked', 'gzip'):
                for with_length in (False, True):
                    with self.subTest(route=route, coding=coding, length=with_length):
                        headers = [('Transfer-Encoding', coding)]
                        if with_length:
                            headers.append(('Content-Length', len(body)))
                        self.assert_rejected_without_effects(route, body, headers)

    def test_backtest_rejects_complete_json_when_declared_body_is_truncated(self):
        body = self.body()
        for route in ('/api/backtest', '/api/v1/backtest'):
            with self.subTest(route=route):
                self.assert_rejected_without_effects(route, body,
                    [('Content-Length', len(body) + 19)], eof=True)

    def test_backtest_incomplete_body_times_out_and_listener_remains_usable(self):
        default = server.DashboardRequestHandler.JSON_BODY_TIMEOUT_SECONDS
        self.assertGreater(default, 0)
        self.assertLessEqual(default, 5, 'Production JSON body reads must have a bounded deadline')
        for route in ('/api/backtest', '/api/v1/backtest'):
            started = time.monotonic()
            with self.subTest(route=route):
                self.assert_rejected_without_effects(route, b'{', [('Content-Length', 128)])
                self.assertLess(time.monotonic() - started, 2)
                # A complete subsequent request must not inherit the stalled body.
                self.assert_rejected_without_effects(route, b'[]', [('Content-Length', 2)])

    def test_backtest_missing_invalid_and_oversized_length_reject_without_reading(self):
        for headers in ([], [('Content-Length', 'invalid')], [('Content-Length', '-1')],
                        [('Content-Length', '0')], [('Content-Length', 10 * 1024 * 1024 + 1)]):
            with self.subTest(headers=headers):
                self.assert_rejected_without_effects('/api/backtest', headers=headers)

    def test_backtest_duplicate_keys_and_nonfinite_values_are_rejected(self):
        prefix = b'{"strategy_id":"strat_4_orb_filtered","symbol":"RELIANCE","persist_run":false,'
        bad = [prefix + suffix for suffix in (
            b'"symbol":"RELIANCE"}', b'"unused":{"a":1,"a":2}}',
            b'"unused":NaN}', b'"unused":Infinity}', b'"unused":-Infinity}', b'"unused":1e999}')]
        for route in ('/api/backtest', '/api/v1/backtest'):
            for body in bad:
                with self.subTest(route=route, body=body):
                    self.assert_rejected_without_effects(route, body, [('Content-Length', len(body))])

    def test_backtest_malformed_nonobject_and_invalid_utf8_remain_rejected(self):
        for body in (b'{', b'[]', b'null', b'"text"', b'\xff'):
            with self.subTest(body=body):
                self.assert_rejected_without_effects('/api/backtest', body, [('Content-Length', len(body))])

    def test_valid_backtest_request_keeps_explicit_route_contract(self):
        self.backtest.side_effect = None
        self.backtest.return_value.run_backtest.return_value = {'run_id': 'authored-no-database-run'}
        body = self.body()
        code, raw = self.raw_request('/api/backtest', body, [('Content-Length', len(body))])
        self.assertEqual(code, 200, raw)
        self.assertEqual(json.loads(raw)['run_id'], 'authored-no-database-run')
        self.backtest.assert_called_once()
        self.backtest.return_value.run_backtest.assert_called_once()
        self.assertFalse(self.backtest.return_value.run_backtest.call_args.kwargs['persist_run'])
        self.engine.run_single_scan.assert_not_called()
        self.assertEqual(self.engine.store.mock_calls, [])

    def trickle_request(self, initial, remaining):
        """Keep bytes arriving faster than inactivity timeout until absolute rejection."""
        connection = socket.create_connection(self.httpd.server_address, timeout=1.25)
        stop = threading.Event()
        sent = []

        def write():
            try:
                for byte in remaining:
                    if stop.is_set():
                        return
                    connection.sendall(bytes([byte]))
                    sent.append(byte)
                    if stop.wait(0.04):
                        return
            except OSError:
                return

        writer = threading.Thread(target=write, daemon=True)
        response = None
        started = time.monotonic()
        try:
            if initial:
                connection.sendall(initial)
            writer.start()
            response = http.client.HTTPResponse(connection)
            try:
                response.begin()
                status, body = response.status, response.read()
                self.assertIn(status, (400, 408), body)
            except (http.client.RemoteDisconnected, ConnectionResetError):
                # An expired header may close before a complete HTTP response.
                status = None
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertTrue(sent, 'The client must actually deliver trickle bytes')
            self.assertLess(len(sent), len(remaining), 'Whole input arrived before rejection')
            return status
        finally:
            stop.set()
            if response is not None:
                response.close()
            connection.close()
            writer.join(timeout=1)
            self.assertFalse(writer.is_alive(), 'Trickle writer leaked after response/timeout')

    def test_absolute_header_deadline_rejects_trickle_and_listener_recovers(self):
        port = self.httpd.server_port
        request = (f'POST /api/backtest HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                   'Content-Length: 2\r\nContent-Type: application/json\r\n\r\n[]').encode('ascii')
        self.trickle_request(b'', request)
        self.backtest.assert_not_called()
        self.assertEqual(self.engine.mock_calls, [])
        self.assertEqual(self.engine.store.mock_calls, [])
        self.assert_rejected_without_effects('/api/backtest', b'[]', [('Content-Length', 2)])

    def test_absolute_body_deadline_rejects_trickle_and_listener_recovers(self):
        body = self.body()
        port = self.httpd.server_port
        headers = (f'POST /api/backtest HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                   f'Content-Length: {len(body)}\r\nContent-Type: application/json\r\n'
                   'Connection: close\r\n\r\n').encode('ascii')
        # Windows may terminate/reset the socket when the absolute deadline shuts
        # down its read side; early partial rejection and zero effects still apply.
        self.assertIn(self.trickle_request(headers, body), (400, None))
        self.backtest.assert_not_called()
        self.assertEqual(self.engine.mock_calls, [])
        self.assertEqual(self.engine.store.mock_calls, [])
        self.assert_rejected_without_effects('/api/v1/backtest', b'[]', [('Content-Length', 2)])


class TestTrackALoopbackStartup(unittest.TestCase):
    FORBIDDEN = ('0.0.0.0', '::', '192.0.2.1', '2001:db8::1', 'untrusted.invalid', '')

    def test_factory_rejects_nonloopback_before_socket_creation(self):
        with patch.object(server, 'TradePulseThreadingHTTPServer') as socket_factory:
            for host in self.FORBIDDEN:
                with self.subTest(host=host):
                    with self.assertRaises(ValueError):
                        server.create_http_server(host, 0)
            socket_factory.assert_not_called()

    def test_runner_rejects_nonloopback_before_configuration_or_binding(self):
        with ExitStack() as guards:
            configure = guards.enter_context(patch.object(server, 'configure_server_runtime'))
            factory = guards.enter_context(patch.object(server, 'create_http_server'))
            threaded = guards.enter_context(patch.object(server, 'ThreadingHTTPServer'))
            specific = guards.enter_context(patch.object(server, 'TradePulseThreadingHTTPServer'))
            guards.enter_context(patch.object(server.os, 'chdir'))
            guards.enter_context(patch.object(server.DashboardRequestHandler, 'scheduler', None))
            for host in self.FORBIDDEN:
                with self.subTest(host=host):
                    with self.assertRaises(ValueError):
                        server.run_server(host=host, port=0, start_scheduler=False)
            configure.assert_not_called()
            factory.assert_not_called()
            threaded.assert_not_called()
            specific.assert_not_called()

    def test_localhost_factory_binds_only_loopback_without_runtime_initialization(self):
        with patch.object(server, 'configure_server_runtime') as configure:
            listener = server.create_http_server('localhost', 0)
            try:
                self.assertTrue(ipaddress.ip_address(listener.server_address[0]).is_loopback)
                configure.assert_not_called()
            finally:
                listener.server_close()

    def test_localhost_runner_keeps_valid_explicit_launch_path(self):
        listener = Mock(name='disposable_mock_listener')
        with ExitStack() as guards:
            configure = guards.enter_context(patch.object(server, 'configure_server_runtime'))
            guards.enter_context(patch.object(server, 'create_http_server', return_value=listener))
            guards.enter_context(patch.object(server, 'ThreadingHTTPServer', return_value=listener))
            guards.enter_context(patch.object(server, 'TradePulseThreadingHTTPServer', return_value=listener))
            guards.enter_context(patch.object(server.os, 'chdir'))
            guards.enter_context(patch.object(server.DashboardRequestHandler, 'scheduler', None))
            guards.enter_context(patch('builtins.print'))
            server.run_server(host='localhost', port=0, start_scheduler=False)
            configure.assert_called_once()
            self.assertIs(configure.call_args.kwargs['start_scheduler'], False)
            listener.serve_forever.assert_called_once()
            listener.server_close.assert_called_once()


class TestTrackABoundedHTTPWorkers(unittest.TestCase):
    def setUp(self):
        guards = ExitStack()
        offline_network(guards)
        self.addCleanup(guards.close)
        self.configure = guards.enter_context(patch.object(server, 'configure_server_runtime'))
        accepted = queue.Queue()
        dispatched = []

        class TinyHTTPHandler(socketserver.BaseRequestHandler):
            """Only a complete small request dispatches; EOF/timeout never does."""
            def handle(self):
                accepted.put(True)
                received = b''
                try:
                    while b'\r\n\r\n' not in received and len(received) < 4096:
                        block = self.request.recv(1024)
                        if not block:
                            return
                        received += block
                    if b'\r\n\r\n' not in received:
                        return
                    dispatched.append(received.split(b'\r\n', 1)[0])
                    self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\nfixture')
                except (TimeoutError, ConnectionError):
                    return

        class TinyBoundedServer(server.TradePulseThreadingHTTPServer):
            MAX_CONCURRENT_REQUESTS = 2
            SOCKET_TIMEOUT_SECONDS = 0.25

        self.accepted, self.dispatched = accepted, dispatched
        self.httpd = TinyBoundedServer(('127.0.0.1', 0), TinyHTTPHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        self.held = []
        self.addCleanup(self.close_server)

    def close_server(self):
        for connection in self.held:
            connection.close()
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()
        self.assertFalse(self.thread.is_alive())
        self.configure.assert_not_called()

    def hold_partial_header(self):
        connection = socket.create_connection(self.httpd.server_address, timeout=1)
        self.held.append(connection)
        connection.sendall(b'GET /held HTTP/1.1\r\nHost: localhost\r\nX-Incomplete:')
        self.accepted.get(timeout=1)  # Observe the actual worker, not semaphore internals.
        return connection

    def complete_request(self):
        connection = socket.create_connection(self.httpd.server_address, timeout=1)
        try:
            connection.sendall(b'GET /ok HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            response = http.client.HTTPResponse(connection)
            try:
                response.begin()
                return response.status, response.read()
            finally:
                response.close()
        finally:
            connection.close()

    def assert_recovers(self):
        deadline = time.monotonic() + 1
        while True:
            status, body = self.complete_request()
            if status != 503 or time.monotonic() >= deadline:
                break
            time.sleep(0.005)
        self.assertEqual((status, body), (200, b'fixture'))
        self.assertEqual(self.dispatched, [b'GET /ok HTTP/1.1'])

    def test_two_partial_headers_bound_workers_and_third_is_503_then_close_recovers(self):
        self.hold_partial_header()
        self.hold_partial_header()
        self.assertEqual(self.complete_request(), (503, b''))
        self.assertEqual(self.dispatched, [], 'Overloaded or incomplete requests dispatched work')
        for connection in self.held:
            connection.close()
        self.assert_recovers()

    def test_incomplete_header_timeout_releases_slots_without_client_close(self):
        first = self.hold_partial_header()
        second = self.hold_partial_header()
        started = time.monotonic()
        self.assertEqual(first.recv(1), b'')
        self.assertEqual(second.recv(1), b'')
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(self.dispatched, [], 'Timed-out incomplete headers dispatched work')
        # Both client sockets are deliberately still open when capacity recovers.
        self.assert_recovers()


if __name__ == '__main__':
    unittest.main(verbosity=2)
