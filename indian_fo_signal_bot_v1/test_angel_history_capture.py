"""Bounded history transport fixtures; never real provider or rights acceptance."""
import io
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import test_bot
from angel_history_capture import capture_one_history, HistoryCaptureError, _NoRedirect
from brokers import AngelOneSmartAPIAdapter
from config import BotConfig
from strategies import IST


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json", "Date": "Fri, 16 Oct 2026 11:00:00 GMT"}


class TestAngelHistoryCapture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ANGEL_HISTORY_TEST_ONLY_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = BotConfig(active_broker="paper_sim", telegram_dry_run=True, enable_background_scheduler=False,
            angel_api_key="TEST_PRIVATE_API_KEY", angel_scrip_master_path="", angel_min_request_interval_seconds=0)
        self.now = datetime(2026, 10, 16, 16, tzinfo=IST)
        self.adapter = AngelOneSmartAPIAdapter(self.config, clock=lambda: self.now)
        self.adapter.jwt_token = "TEST_PRIVATE_JWT"
        self.adapter.load_scrip_master([dict(token="2885", symbol="RELIANCE-EQ", name="RELIANCE",
            expiry="", strike="-1", lotsize="1", instrumenttype="", exch_seg="NSE", tick_size="5")], strict=True)
        self.rows = [[bar["timestamp"].replace(" ", "T") + "+05:30", bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]]
            for bar in test_bot.TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")]
        self.raw = json.dumps(dict(status=True, data=self.rows)).encode()
        self.calls = []
        self.responses = []
        self.adapter.authenticate = Mock(side_effect=AssertionError("Login forbidden"))
        self.adapter._recover_session = Mock(side_effect=AssertionError("Refresh forbidden"))

    def transport(self, request, timeout):
        self.calls.append((request, timeout))
        response = Response(self.raw)
        self.responses.append(response)
        return response

    def capture(self, **kwargs):
        return capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "one", transport=self.transport, **kwargs)

    def test_one_request_retains_exact_originals_and_separate_simulated_candidates(self):
        result = self.capture()
        self.assertEqual(len(self.calls), 1)
        request, timeout = self.calls[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.full_url.endswith("historical/v1/getCandleData"))
        self.assertEqual(json.loads(request.data), dict(exchange="NSE", symboltoken="2885", interval="FIVE_MINUTE",
            fromdate="2026-10-15 09:15", todate="2026-10-15 15:25"))
        self.assertEqual(timeout, 8.0)
        self.assertEqual((self.root / "one/response.bin").read_bytes(), self.raw)
        normalized = json.loads((self.root / "one/normalized_candidate.json").read_bytes())
        self.assertEqual(len(normalized["candles"]), 75)
        self.assertTrue(all(b["data_mode"] == "SIMULATED" and b["is_simulated"] for b in normalized["candles"]))
        self.assertEqual(result["quality_status"], "COMPLETE_VERIFIED")
        self.assertFalse(result["research_eligible"])
        self.assertEqual(result["publisher_signature"], "NOT_SUPPLIED")
        self.assertTrue(self.responses[0].closed)
        self.adapter.authenticate.assert_not_called()
        self.adapter._recover_session.assert_not_called()
        self.assertNotIn("TEST_PRIVATE", json.dumps(result))

    def test_74_bars_are_retained_with_missing_coverage_instead_of_filled(self):
        del self.rows[20]
        self.raw = json.dumps(dict(status=True, data=self.rows)).encode()
        result = self.capture()
        self.assertEqual(result["normalized_bar_count"], 74)
        self.assertEqual(result["missing_bars_count"], 1)
        self.assertEqual(result["quality_status"], "INCOMPLETE_MISSING_BARS")
        self.assertFalse(result["research_eligible"])

    def test_http403_preserves_original_private_error_and_does_not_guess_cause_or_retry(self):
        stream = io.BytesIO(b"PRIVATE_ERROR_WITH_TEST_PRIVATE_JWT")
        error = urllib.error.HTTPError("https://private.invalid/?secret=TEST_PRIVATE_JWT", 403,
            "PRIVATE_REASON", {"Authorization": "TEST_PRIVATE_JWT"}, stream)
        calls = []
        def denied(request, timeout):
            calls.append(request)
            raise error
        result = capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "denied", transport=denied)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result["provider_cause"], "NOT_ESTABLISHED")
        self.assertEqual(result["normalization_status"], "HTTP_REQUEST_REJECTED")
        self.assertEqual((self.root / "denied/response.bin").read_bytes(), b"PRIVATE_ERROR_WITH_TEST_PRIVATE_JWT")
        self.assertNotIn("TEST_PRIVATE", json.dumps(result))
        self.assertTrue(stream.closed)
        self.assertFalse((self.root / "denied/normalized_candidate.json").exists())

    def test_unsafe_profile_unauthenticated_or_unmapped_calls_never_reach_transport(self):
        for key, value in (("active_broker", "upstox"), ("telegram_dry_run", False), ("enable_background_scheduler", True)):
            old = getattr(self.config, key)
            setattr(self.config, key, value)
            with self.assertRaises(HistoryCaptureError):
                self.capture()
            setattr(self.config, key, old)
        self.adapter.jwt_token = None
        with self.assertRaises(HistoryCaptureError):
            self.capture()
        self.adapter.jwt_token = "TEST_PRIVATE_JWT"
        self.adapter._scrip_master_equities.clear()
        with self.assertRaises(HistoryCaptureError):
            self.capture()
        self.assertFalse(self.calls)

    def test_angel_data_configuration_is_independent_of_execution_and_does_not_authorize_orders(self):
        self.config.active_broker = "angelone"
        result = self.capture()
        self.assertEqual(result["execution_scope"], "READ_ONLY_DATA_CAPTURE_NO_EXECUTION")
        self.assertEqual(result["order_calls"], 0)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][0].full_url.endswith("historical/v1/getCandleData"))

    def test_oversize_response_is_retained_only_as_incomplete_prefix_without_normalization(self):
        with patch("angel_history_capture.MAX_BYTES", 32):
            result = self.capture()
        self.assertFalse(result["original_response_complete"])
        self.assertEqual(result["response_bytes"], 33)
        self.assertEqual(result["normalization_status"], "RESPONSE_RESOURCE_LIMIT")
        self.assertTrue((self.root / "one/response_prefix.bin").is_file())
        self.assertFalse((self.root / "one/response.bin").exists())
        self.assertFalse((self.root / "one/normalized_candidate.json").exists())

    def test_forming_weekend_or_holiday_session_is_not_requested(self):
        for day in ("2026-10-17", "2026-10-19"):
            with self.assertRaises(HistoryCaptureError):
                capture_one_history(self.adapter, "RELIANCE", day, self.root, "bad", transport=self.transport)
        self.config.configured_holidays = ["2026-10-15"]
        with self.assertRaises(HistoryCaptureError):
            self.capture()
        self.assertFalse(self.calls)

    def test_actual_transport_requires_explicit_authorization_and_private_local_root(self):
        with patch("angel_history_capture._secure_open") as network:
            with self.assertRaises(HistoryCaptureError):
                capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "bad")
            with self.assertRaises(HistoryCaptureError):
                capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "bad", allow_live_request=True)
            network.assert_not_called()

    def test_duplicate_out_of_order_crossed_ohlc_or_naive_source_time_fail_without_normalized_file(self):
        for change in (lambda: self.rows.insert(1, list(self.rows[0])), lambda: self.rows.reverse(),
                lambda: self.rows[0].__setitem__(2, 0), lambda: self.rows[0].__setitem__(0, "2026-10-15T09:15:00")):
            with self.subTest(change=change):
                original = json.loads(json.dumps(self.rows))
                change()
                self.raw = json.dumps(dict(status=True, data=self.rows)).encode()
                stage = "bad_" + str(len(self.calls))
                result = capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, stage, transport=self.transport)
                self.assertEqual(result["normalization_status"], "SOURCE_SCHEMA_IDENTITY_OR_QUALITY_REJECTED")
                self.assertFalse((self.root / stage / "normalized_candidate.json").exists())
                self.rows = original

    def test_network_exception_text_never_enters_receipt_and_no_retry(self):
        denied = Mock(side_effect=OSError("TEST_PRIVATE_JWT Authorization PRIVATE"))
        result = capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "network", transport=denied)
        self.assertEqual(denied.call_count, 1)
        self.assertEqual(result["normalization_status"], "TRANSPORT_OR_CAPTURE_FAILURE")
        self.assertNotIn("TEST_PRIVATE", json.dumps(result))

    def test_stage_reuse_and_path_traversal_are_rejected_before_new_request(self):
        self.capture()
        with self.assertRaises(FileExistsError):
            self.capture()
        with self.assertRaises(HistoryCaptureError):
            capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "../escape", transport=self.transport)
        self.assertEqual(len(self.calls), 1)

    def test_http_redirect_is_not_followed_and_is_not_data_acceptance(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, None, None, None, None))
        response = Response(b"PRIVATE_REDIRECT_BODY")
        response.status = 302
        result = capture_one_history(self.adapter, "RELIANCE", "2026-10-15", self.root, "redirect",
            transport=lambda request, timeout: response)
        self.assertEqual(result["http_status"], 302)
        self.assertEqual(result["redirects_followed"], 0)
        self.assertFalse(result["research_eligible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
