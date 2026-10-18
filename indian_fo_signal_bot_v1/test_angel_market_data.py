"""Deterministic Angel market-data safety checks; no credentials or broker I/O."""

import io
import json
import os
import sys
import traceback
import unittest
import urllib.error
import urllib.parse
from datetime import datetime
from unittest.mock import patch

# Reuse the suite's existing offline config isolation before any production import.
# The integrated test_bot loader has already imported config, avoiding a cycle.
if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot as _offline_test_environment

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    # test_bot's module cleanup runs before this module in the combined suite.
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)

from brokers import AngelOneSmartAPIAdapter, BrokerDataError
from config import BotConfig
from strategies import IST


class TestAngelMarketDataSafety(unittest.TestCase):
    QUOTE_PATH = "/rest/secure/angelbroking/market/v1/quote/"

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 36, 5, tzinfo=IST)
        self.cfg = BotConfig(active_broker="angelone", database_url=":memory:",
            enable_persistence=False, telegram_dry_run=True,
            enable_background_scheduler=False, angel_api_key="OFFLINE/API+KEY ONLY",
            angel_client_code="OFFLINE_CLIENT_123", angel_pin="7531",
            angel_totp_secret="JBSWY3DPEHPK3PXP", angel_scrip_master_path="",
            angel_min_request_interval_seconds=0.0)
        self.adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        self.adapter.jwt_token = "OFFLINE/JWT+TOKEN ONLY"
        self.adapter.refresh_token = "OFFLINE/REFRESH+TOKEN ONLY"
        self.adapter.feed_token = "OFFLINE/FEED+TOKEN ONLY"
        self.adapter.authenticated_at_ist = "2026-10-16 10:35:00"
        self.requests = []
        self.responses = []
        self.transport = patch("urllib.request.urlopen", side_effect=self._open)
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def _open(self, request, timeout):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected offline transport call")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(item if isinstance(item, bytes) else json.dumps(item).encode())

    def _quote_response(self, **changes):
        item = dict(exchange="NSE", symbolToken="2885", tradingSymbol="RELIANCE-EQ",
                    ltp=2950.0, open=2940.0, high=2960.0, low=2930.0,
                    close=2900.0, tradeVolume=10000, opnInterest=0,
                    exchFeedTime="16-Oct-2026 10:36:04")
        item.update(changes)
        return dict(status=True, data=dict(fetched=[item], unfetched=[]))

    def _http_error(self, code):
        stream = io.BytesIO(b'{"status":false,"message":"Denied"}')
        error = urllib.error.HTTPError("https://offline.invalid/?token=PRIVATE_URL",
            code, "PRIVATE_HTTP_REASON", {"Authorization": "PRIVATE_HEADER"}, stream)
        self.addCleanup(error.close)
        return error, stream

    def _render_failure(self, action):
        try:
            action()
        except BrokerDataError as error:
            return "".join(traceback.format_exception(error))
        self.fail("Expected the invalid provider response to be rejected")

    def test_successful_quote_uses_only_market_endpoint_and_required_headers(self):
        self.responses = [self._quote_response()]
        quote = self.adapter.get_quote("RELIANCE")
        self.assertEqual(quote["instrument_identity"]["identifier"], "2885")
        self.assertEqual(quote["feed_timestamp_ist"], "2026-10-16 10:36:04")
        self.assertEqual(quote["ltp"], 2950.0)
        self.assertEqual(quote["data_mode"], "LIVE")
        self.assertFalse(quote["is_simulated"])
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(urllib.parse.urlsplit(request.full_url).path, self.QUOTE_PATH)
        self.assertEqual(request.get_method(), "POST")
        headers = {key.lower(): value for key, value in request.header_items()}
        for key in ("authorization", "x-privatekey", "x-usertype", "x-sourceid",
                    "x-clientlocalip", "x-clientpublicip", "x-macaddress"):
            self.assertIn(key, headers)
        payload = json.loads(request.data)
        self.assertEqual(payload, {"mode": "FULL", "exchangeTokens": {"NSE": ["2885"]}})

    def test_missing_quote_timestamp_is_not_replaced_by_request_time(self):
        self.responses = [self._quote_response(exchFeedTime=None)]
        quote = self.adapter.get_quote("RELIANCE")
        self.assertIsNone(quote.get("feed_timestamp_ist"))
        self.assertIsNone(quote.get("quote_timestamp_ist"))
        self.assertIsNone(self.adapter.last_quote_timestamp_ist)

    def test_quote_rejects_impossible_price_and_boolean_market_counts(self):
        for changes in (dict(ltp=3000), dict(tradeVolume=True), dict(opnInterest=True)):
            with self.subTest(fields=list(changes)):
                self.responses = [self._quote_response(**changes)]
                with self.assertRaises(BrokerDataError):
                    self.adapter.get_quote("RELIANCE")
                self.assertFalse(self.adapter.is_connection_verified())

    def test_duplicate_json_and_oversize_responses_never_count_as_authorized_reads(self):
        for body in (b'{"status":false,"status":true,"data":{}}', b" "*(8*1024*1024+1)):
            before = self.adapter._authorized_reads
            self.responses = [body]
            with self.assertRaises(BrokerDataError):
                self.adapter.get_quote("RELIANCE")
            self.assertEqual(self.adapter._authorized_reads, before)
            self.assertFalse(self.adapter.is_connection_verified())

    def test_invalid_and_future_quote_timestamps_are_rejected(self):
        for timestamp in ("not-a-time", "16-Oct-2026 10:38:00", True):
            with self.subTest(timestamp=timestamp):
                self.responses = [self._quote_response(exchFeedTime=timestamp)]
                with self.assertRaises(BrokerDataError):
                    self.adapter.get_quote("RELIANCE")

    def test_quote_identity_mismatch_is_rejected(self):
        for changes in (dict(symbolToken="1333"), dict(exchange="BSE"),
                        dict(tradingSymbol="HDFCBANK-EQ")):
            with self.subTest(changes=changes):
                self.responses = [self._quote_response(**changes)]
                with self.assertRaises(BrokerDataError):
                    self.adapter.get_quote("RELIANCE")

    def test_provider_acceptance_must_be_explicit_true(self):
        for status in (None, "true", 1, {}, []):
            with self.subTest(status=status):
                response = self._quote_response()
                response["status"] = status
                self.responses = [response]
                with self.assertRaises(BrokerDataError):
                    self.adapter.get_quote("RELIANCE")

    def test_provider_error_response_redacts_encoded_credentials(self):
        secret_values = self.adapter._secret_values() + [self.cfg.angel_client_code]
        variants = [variant for value in secret_values if value for variant in
                    (value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))]
        self.responses = [dict(status=False, errorcode="AB2001", message="Denied " + " | ".join(variants))]
        rendered = self._render_failure(lambda: self.adapter.get_quote("RELIANCE"))
        for value in variants:
            self.assertNotIn(value, rendered)
        self.assertIn("AB2001", rendered)

    def test_login_http_failure_closes_resource_and_erases_authentication_proof(self):
        error, stream = self._http_error(401)
        self.responses = [error]
        self.adapter.last_market_data_at_ist = "2026-10-16 10:35:00"
        rendered = self._render_failure(self.adapter.authenticate)
        self.assertTrue(stream.closed)
        self.assertIsNone(self.adapter.jwt_token)
        self.assertIsNone(self.adapter.authenticated_at_ist)
        self.assertFalse(self.adapter.is_connection_verified())
        self.assertNotIn("PRIVATE_HTTP_REASON", rendered)
        self.assertNotIn("PRIVATE_URL", rendered)

    def test_refresh_http_failure_closes_response_and_hides_original_exception(self):
        error, stream = self._http_error(401)
        self.responses = [error]
        rendered = self._render_failure(self.adapter.refresh_access_token)
        self.assertTrue(stream.closed)
        self.assertIsNone(self.adapter.jwt_token)
        self.assertNotIn("PRIVATE_HTTP_REASON", rendered)
        self.assertNotIn("PRIVATE_URL", rendered)

    def test_market_http_failures_close_and_keep_safe_categories(self):
        for code in (401, 403, 429, 503):
            with self.subTest(code=code):
                self.adapter.jwt_token = "OFFLINE/JWT+TOKEN ONLY"
                error, stream = self._http_error(code)
                self.responses = [error]
                rendered = self._render_failure(lambda: self.adapter._request_json(
                    "POST", self.QUOTE_PATH, payload={}, allow_reauth_retry=False))
                self.assertTrue(stream.closed)
                self.assertNotIn("PRIVATE_HTTP_REASON", rendered)
                self.assertNotIn("PRIVATE_URL", rendered)
                self.assertEqual(self.adapter.last_error_category,
                    "SESSION_EXPIRED" if code == 401 else "RATE_LIMIT" if code in (403, 429) else "NETWORK_API_FAILURE")

    def test_http_session_recovery_closes_error_before_single_retry(self):
        error, stream = self._http_error(401)
        self.responses = [error, dict(status=True, data=dict(jwtToken="NEW_OFFLINE_JWT")), self._quote_response()]
        quote = self.adapter.get_quote("RELIANCE")
        self.assertTrue(stream.closed)
        self.assertEqual(quote["ltp"], 2950.0)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(urllib.parse.urlsplit(self.requests[1].full_url).path,
                         "/rest/auth/angelbroking/jwt/v1/generateTokens")

    def test_rejected_login_clears_previous_authentication_state(self):
        self.adapter.last_market_data_at_ist = "2026-10-16 10:35:00"
        self.responses = [dict(status=False, errorcode="AB1007", message="Invalid password")]
        with self.assertRaises(BrokerDataError):
            self.adapter.authenticate()
        self.assertIsNone(self.adapter.jwt_token)
        self.assertIsNone(self.adapter.authenticated_at_ist)
        self.assertFalse(self.adapter.is_connection_verified())
        self.assertEqual(self.adapter.last_error_category, "AUTH_FAILURE")

    def test_network_exception_chain_does_not_expose_credentials(self):
        self.responses = [urllib.error.URLError("PRIVATE_ORIGINAL " + self.cfg.angel_api_key)]
        rendered = self._render_failure(lambda: self.adapter.get_quote("RELIANCE"))
        self.assertNotIn("PRIVATE_ORIGINAL", rendered)
        self.assertNotIn(self.cfg.angel_api_key, rendered)
        self.assertFalse(self.adapter.is_connection_verified())

    def test_malformed_response_chain_does_not_echo_provider_body(self):
        self.responses = [b'{"status":true,"PRIVATE_RAW_BODY":']
        rendered = self._render_failure(lambda: self.adapter.get_quote("RELIANCE"))
        self.assertNotIn("PRIVATE_RAW_BODY", rendered)
        self.assertFalse(self.adapter.is_connection_verified())

    def test_order_gtt_unknown_and_wrong_method_paths_are_rejected_before_login(self):
        paths = ("/rest/secure/angelbroking/order/v1/placeOrder",
                 "/gtt-service/rest/secure/angelbroking/gtt/v1/createRule",
                 "/gtt-service/rest/secure/angelbroking/gtt/v1/modifyRule",
                 "/gtt-service/rest/secure/angelbroking/gtt/v1/cancelRule",
                 "/rest/secure/angelbroking/portfolio/v1/getHolding",
                 "/rest/secure/angelbroking/market/v1/quote/../order/v1/placeOrder",
                 self.QUOTE_PATH + "?access_token=PRIVATE_QUERY")
        self.adapter.jwt_token = None
        with patch.object(self.adapter, "authenticate") as login:
            for path in paths:
                with self.subTest(path=path):
                    with self.assertRaises(BrokerDataError):
                        self.adapter._request_json("POST", path, payload={})
            with self.assertRaises(BrokerDataError):
                self.adapter._request_json("DELETE", self.QUOTE_PATH, payload={})
        login.assert_not_called()
        self.assertFalse(self.requests)

    def test_completed_candles_are_bound_and_fresh_without_profile_calls(self):
        self.responses = [dict(status=True, data=[
            ["2026-10-16T10:25:00+05:30", 100, 103, 99, 102, 1000],
            ["2026-10-16T10:30:00+05:30", 102, 104, 101, 103, 1100]])]
        candles = self.adapter.get_intraday_candles(dict(symbol="RELIANCE", angel_token="2885"), 5)
        self.assertEqual(len(candles), 2)
        self.assertTrue(all(candle["instrument_identity"]["identifier"] == "2885" for candle in candles))
        self.assertEqual(self.adapter.last_candle_freshness["status"], "FRESH_IN_SESSION")
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0].full_url.endswith("/historical/v1/getCandleData"))

    def test_stale_candles_are_rejected_without_trusted_connection(self):
        self.responses = [dict(status=True, data=[
            ["2026-10-16T09:15:00+05:30", 100, 103, 99, 102, 1000]])]
        with self.assertRaises(BrokerDataError):
            self.adapter.get_intraday_candles(dict(symbol="RELIANCE", angel_token="2885"), 5)
        self.assertFalse(self.adapter.is_connection_verified())


class TestAngelMarketDataDiagnostics(unittest.TestCase):
    setUp = TestAngelMarketDataSafety.setUp
    _open = TestAngelMarketDataSafety._open
    _quote_response = TestAngelMarketDataSafety._quote_response
    _http_error = TestAngelMarketDataSafety._http_error

    def _candles(self):
        return dict(status=True, data=[
            ["2026-10-16T10:25:00+05:30", 100, 103, 99, 102, 1000],
            ["2026-10-16T10:30:00+05:30", 102, 104, 101, 103, 1100],
            ["2026-10-16T10:35:00+05:30", 103, 105, 102, 104, 1200]])

    def _run(self, **options):
        from diagnostics import run_angelone_market_data_diagnostics
        return run_angelone_market_data_diagnostics(self.cfg, self.adapter, symbol="RELIANCE",
            clock=lambda: self.now, **options)

    def test_preflight_has_no_adapter_transport_store_or_receipt(self):
        from diagnostics import run_angelone_market_data_diagnostics
        with patch("diagnostics.AngelOneSmartAPIAdapter", side_effect=AssertionError("No preflight adapter")), \
             patch("diagnostics.SQLitePersistenceStore", side_effect=AssertionError("No store")), \
             patch("readiness_policy._record_completed_diagnostic", side_effect=AssertionError("No receipt")):
            report = run_angelone_market_data_diagnostics(self.cfg, symbol="RELIANCE", config_only=True)
        self.assertTrue(report["configuration_ready"])
        self.assertEqual(report["overall_status"], "NOT_TESTED")
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["checks"]["authentication"]["status"], "NOT_TESTED")
        self.assertFalse(self.requests)

    def test_invalid_config_and_mapping_are_blocked_without_changing_provider(self):
        from diagnostics import run_angelone_market_data_diagnostics
        for key, value in (("active_broker", "upstox"), ("telegram_dry_run", False),
                           ("enable_background_scheduler", True), ("angel_api_key", "")):
            original = getattr(self.cfg, key)
            try:
                setattr(self.cfg, key, value)
                report = self._run(config_only=True)
                self.assertFalse(report["configuration_ready"])
                self.assertEqual(getattr(self.cfg, key), value)
            finally:
                setattr(self.cfg, key, original)
        self.assertEqual(run_angelone_market_data_diagnostics(self.cfg, symbol="NIFTY", config_only=True)["checks"]["instrument"]["status"], "BLOCKED")
        self.cfg.equity_watchlist[0] = dict(self.cfg.equity_watchlist[0], angel_token="1333")
        self.assertEqual(self._run(config_only=True)["checks"]["instrument"]["status"], "BLOCKED")
        self.assertFalse(self.requests)

    def test_success_uses_login_quote_candles_without_profile_persistence_or_delivery(self):
        from contextlib import ExitStack
        self.adapter.jwt_token = None
        self.responses = [dict(status=True, data=dict(jwtToken="NEW_OFFLINE_JWT")),
                          self._quote_response(), self._candles()]
        targets = ("brokers.AngelOneSmartAPIAdapter.get_profile", "diagnostics.SQLitePersistenceStore",
                   "scanner_engine.IntradayBotEngine.run_single_scan", "scanner_engine.MarketScanScheduler.start",
                   "telegram_bot.TelegramSignalDispatcher.send_signal", "readiness_policy._record_completed_diagnostic")
        with ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=AssertionError("Forbidden acceptance side effect"))) for target in targets]
            report = self._run()
        self.assertEqual(report["overall_status"], "PASS", report)
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
        self.assertEqual(len(report["checks"]["candles"]["completed_sample"]), 2)
        self.assertEqual(report["checks"]["candles"]["incomplete_bars_excluded"], 1)
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(self.requests[0].full_url.endswith("/loginByPassword"))
        self.assertTrue(self.requests[1].full_url.endswith("/market/v1/quote/"))
        self.assertTrue(self.requests[2].full_url.endswith("/historical/v1/getCandleData"))
        self.assertEqual(self.adapter._authorized_reads, 2)
        for key in ("data_persisted", "readiness_receipt_issued", "historical_replay_allowed"):
            self.assertFalse(report[key])
        for guard in guards:
            guard.assert_not_called()

    def test_missing_or_stale_quote_observation_stops_before_candles(self):
        for timestamp, status in ((None, "BLOCKED"), ("16-Oct-2026 09:35:00", "FAIL")):
            self.requests.clear()
            self.responses = [self._quote_response(exchFeedTime=timestamp)]
            with self.subTest(timestamp=timestamp):
                report = self._run()
                self.assertEqual(report["checks"]["quote"]["status"], status)
                self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
                self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
                self.assertEqual(report["overall_status"], "FAIL")
                self.assertEqual(len(self.requests), 1)

    def test_failed_authentication_stops_with_safe_json(self):
        self.adapter.jwt_token = None
        error, stream = self._http_error(401)
        self.responses = [error]
        report = self._run()
        self.assertTrue(stream.closed)
        self.assertEqual(report["checks"]["authentication"]["status"], "FAIL")
        self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(len(self.requests), 1)
        rendered = json.dumps(report)
        for value in (self.cfg.angel_api_key, self.cfg.angel_pin, "PRIVATE_HTTP_REASON", "PRIVATE_URL"):
            self.assertNotIn(value, rendered)

    def test_failed_quote_does_not_request_candles_or_issue_receipt(self):
        error, stream = self._http_error(503)
        self.responses = [error]
        report = self._run()
        self.assertTrue(stream.closed)
        self.assertEqual(report["checks"]["authentication"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(report["historical_replay_allowed"])
        self.assertFalse(report["readiness_receipt_issued"])

    def test_successful_quote_alone_never_establishes_full_acceptance(self):
        self.responses = [self._quote_response(), dict(status=True, data=[])]
        report = self._run()
        self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
        self.assertEqual(report["checks"]["quote"]["status"], "PASS")
        self.assertEqual(report["checks"]["candles"]["status"], "FAIL")
        self.assertEqual(report["overall_status"], "FAIL")
        self.assertFalse(report["readiness_receipt_issued"])

    def test_quote_is_rechecked_after_slow_candle_read(self):
        from datetime import timedelta
        self.responses = [self._quote_response(), self._candles()]
        original = self.adapter.get_intraday_candles
        def delayed(*args, **kwargs):
            candles = original(*args, **kwargs)
            self.now += timedelta(seconds=70)
            return candles
        with patch.object(self.adapter, "get_intraday_candles", side_effect=delayed):
            report = self._run()
        self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
        self.assertEqual(report["exit_code"], 1)

    def test_cli_preflight_is_offline_and_never_enters_legacy_diagnostics(self):
        from diagnostics import main
        out = io.StringIO()
        with patch("diagnostics.BotConfig", return_value=self.cfg), patch("sys.stdout", out), \
             patch("diagnostics.SQLitePersistenceStore", side_effect=AssertionError("No store")), \
             patch("diagnostics.run_angelone_diagnostics", side_effect=AssertionError("No legacy profile path")):
            self.assertEqual(main(["--market-data-only", "--symbol", "RELIANCE", "--check-config", "--json"]), 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["overall_status"], "NOT_TESTED")
        self.assertEqual(report["effective_configuration"]["active_broker"], "angelone")
        self.assertFalse(self.requests)

    def test_cli_rejects_legacy_side_effect_flags_and_missing_scope(self):
        from diagnostics import main
        for args in (["--check-config"], ["--market-data-only"],
                     ["--market-data-only", "--symbol", "RELIANCE", "--import-baseline", "PRIVATE_PATH"],
                     ["--market-data-only", "--symbol", "RELIANCE", "--refresh-scrip-master", "PRIVATE_PATH"]):
            with self.subTest(args=args), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(args)
            self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main(verbosity=2)
