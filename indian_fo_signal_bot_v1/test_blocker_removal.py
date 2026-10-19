"""Offline counterexamples for configuration and broker diagnostic lifecycle."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]

from config import BotConfig, ConfigValidationError, _load_dotenv
from brokers import BrokerDataError
from test_phase4_market_data import TestPhase4BrokerAcceptance as _Wire


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


class TestDeterministicConfiguration(unittest.TestCase):
    def _from_directories(self, local, parent="ACTIVE_BROKER=angelone\n", overrides=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            shutil.copyfile(Path(__file__).with_name("config.py"), project / "config.py")
            if local is not None:
                (project / ".env").write_text(local, encoding="utf-8")
            (root / ".env").write_text(parent, encoding="utf-8")
            environment = dict(os.environ)
            for key in _fixtures._test_config_defaults:
                environment.pop(key, None)
            environment.update(overrides or {})
            code = ("import sys,json;sys.path.insert(0,sys.argv[1]);from config import BotConfig;"
                    "c=BotConfig();print(json.dumps(dict(provider=c.active_broker,"
                    "dry=c.telegram_dry_run,scheduler=c.enable_background_scheduler)))")
            results = []
            for cwd in (project, root):
                result = subprocess.run([sys.executable, "-B", "-c", code, str(project)],
                    cwd=cwd, env=environment, capture_output=True, text=True, check=True)
                results.append(json.loads(result.stdout))
            return results

    def test_project_and_parent_use_identical_project_configuration(self):
        results = self._from_directories("ACTIVE_BROKER=upstox\nTELEGRAM_DRY_RUN=true\nENABLE_BACKGROUND_SCHEDULER=false\n")
        self.assertEqual(results, [dict(provider="upstox", dry=True, scheduler=False)] * 2)

    def test_missing_project_config_never_imports_parent_provider(self):
        self.assertEqual(self._from_directories(None), [dict(provider="paper_sim", dry=True, scheduler=False)] * 2)

    def test_explicit_environment_precedence_from_both_directories(self):
        results = self._from_directories("ACTIVE_BROKER=upstox\n", overrides={"ACTIVE_BROKER": "dhan"})
        self.assertEqual([r["provider"] for r in results], ["dhan", "dhan"])

    def test_explicit_path_and_first_duplicate_preserve_process_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TELEGRAM_DRY_RUN": "true"}, clear=True):
            path = Path(directory) / "chosen.env"
            raw = "ACTIVE_BROKER='upstox'\nACTIVE_BROKER=angelone\nTELEGRAM_DRY_RUN=false\n"
            path.write_text(raw, encoding="utf-8")
            _load_dotenv(str(path))
            self.assertEqual(os.environ["ACTIVE_BROKER"], "upstox")
            self.assertEqual(os.environ["TELEGRAM_DRY_RUN"], "true")
            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_malformed_dotenv_fails_atomically_without_exposing_values(self):
        for bad_line in ("MALFORMED_CANARY", "INVALID KEY=CANARY", "=CANARY", 'UPSTOX_ACCESS_TOKEN="CANARY'):
            with self.subTest(kind=bad_line.split("=")[0]), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.env"
                path.write_text("ACTIVE_BROKER=upstox\n" + bad_line + "\n", encoding="utf-8")
                with patch.dict(os.environ, {}, clear=True):
                    with self.assertRaises(ConfigValidationError) as caught:
                        _load_dotenv(str(path))
                    self.assertEqual(dict(os.environ), {})
                    rendered = "".join(traceback.format_exception(caught.exception))
                    self.assertNotIn("CANARY", rendered)

    def test_invalid_numeric_and_boolean_environment_is_secret_safe(self):
        for name in ("ACCOUNT_CAPITAL_INR", "SCAN_INTERVAL_SECONDS", "TELEGRAM_DRY_RUN", "ENABLE_BACKGROUND_SCHEDULER"):
            with self.subTest(setting=name), patch.dict(os.environ, {name: "CONFIG_CANARY"}):
                with self.assertRaises(ConfigValidationError) as caught:
                    BotConfig()
                self.assertNotIn("CONFIG_CANARY", "".join(traceback.format_exception(caught.exception)))

    def test_nonfinite_transport_policy_and_invalid_safety_types_reject(self):
        for field in ("angel_request_timeout_seconds", "angel_min_request_interval_seconds", "angel_scrip_master_max_age_hours"):
            for value in (float("nan"), float("inf")):
                with self.subTest(field=field, value=str(value)), self.assertRaises(ConfigValidationError):
                    BotConfig(**{field: value}).validate()
        for field in ("telegram_dry_run", "enable_persistence", "enable_background_scheduler"):
            with self.subTest(field=field), self.assertRaises(ConfigValidationError):
                BotConfig(**{field: "false"}).validate()

    def test_validation_does_not_echo_invalid_configuration_values(self):
        for field in ("active_broker", "session_start_ist", "configured_holidays", "database_url"):
            value = ["CONFIG_CANARY"] if field == "configured_holidays" else "CONFIG_CANARY"
            if field == "database_url":
                value = "postgres://CONFIG_CANARY"
            with self.subTest(field=field):
                with self.assertRaises(ConfigValidationError) as caught:
                    BotConfig(**{field: value}).validate()
                self.assertNotIn("CONFIG_CANARY", "".join(traceback.format_exception(caught.exception)))

    def test_missing_selected_credentials_fail_without_values(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = BotConfig(active_broker="upstox")
            with self.assertRaises(ConfigValidationError):
                cfg.validate(require_live_credentials=True)

    def test_cli_malformed_configuration_is_structured_and_never_uses_transport(self):
        repository = Path(__file__).resolve().parent
        for script, arguments in (("upstox_diagnostics.py", []), ("diagnostics.py", ["--market-data-only"])):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                shutil.copyfile(repository / "config.py", temporary / "config.py")
                (temporary / ".env").write_text("MALFORMED_SECRET_CANARY\n", encoding="utf-8")
                code = ("import sys,runpy,urllib.request;sys.path[:0]=sys.argv[1:3];"
                    "urllib.request.urlopen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No network'));"
                    "sys.argv=sys.argv[3:];runpy.run_path(sys.argv[0],run_name='__main__')")
                completed = subprocess.run([sys.executable, "-B", "-c", code, str(temporary), str(repository),
                    str(repository / script), *arguments, "--symbol", "RELIANCE", "--check-config", "--json"],
                    cwd=temporary, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 1)
                report = json.loads(completed.stdout)
                self.assertEqual(report["checks"]["configuration"]["status"], "BLOCKED")
                self.assertFalse(report["readiness_receipt_issued"])
                self.assertNotIn("MALFORMED_SECRET_CANARY", completed.stdout + completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)


class TestDiagnosticLifecycle(unittest.TestCase):
    PROVIDERS = _Wire.PROVIDERS
    setUp = _Wire.setUp
    _open = _Wire._open
    _adapter = _Wire._adapter
    _quote = _Wire._quote
    _candles = _Wire._candles
    _reset_wire = _Wire._reset_wire
    _http_error = _Wire._http_error

    def _run(self, provider, adapter):
        from diagnostics import run_angelone_market_data_diagnostics
        from upstox_diagnostics import run_upstox_diagnostics
        fn = run_angelone_market_data_diagnostics if provider == "angelone" else run_upstox_diagnostics
        return fn(adapter.config, adapter, symbol="RELIANCE", clock=lambda: self.now, evidence_mode="MOCKED")

    def test_login_quote_then_candle_403_preserves_authentication_history(self):
        adapter = self._adapter("angelone")
        adapter.jwt_token = None
        error, stream = self._http_error("angelone", 403)
        self._reset_wire(dict(status=True, data=dict(jwtToken="OFFLINE_NEW_JWT")), self._quote("angelone"), error)
        report = self._run("angelone", adapter)
        self.assertEqual(report["initial_authentication"]["status"], "PASS")
        self.assertTrue(report["initial_authentication"]["attempted"])
        self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
        self.assertEqual(report["checks"]["quote"]["status"], "PASS")
        self.assertEqual(report["checks"]["candles"]["http_status"], 403)
        self.assertEqual(report["checks"]["candles"]["error_category"], "ACCESS_DENIED")
        self.assertEqual(report["session"]["before_quote"], "AUTHENTICATED")
        self.assertEqual(report["session"]["after_candles"], "UNAUTHENTICATED")
        self.assertTrue(report["session"]["invalidation_occurred"])
        self.assertFalse(report["session"]["currently_authenticated"])
        self.assertIsNone(adapter.jwt_token)
        self.assertEqual((report["overall_status"], report["exit_code"]), ("FAIL", 1))
        self.assertFalse(report["readiness_receipt_eligible"])
        self.assertFalse(report["readiness_receipt_issued"])
        self.assertTrue(stream.closed)
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(adapter.session_recovery_enabled)
        self.assertNotIn("OFFLINE_NEW_JWT", json.dumps(report))

    def test_failed_login_does_not_attempt_quote(self):
        adapter = self._adapter("angelone")
        adapter.jwt_token = None
        error, _ = self._http_error("angelone", 401)
        self._reset_wire(error)
        report = self._run("angelone", adapter)
        self.assertEqual(report["initial_authentication"]["status"], "FAIL")
        self.assertEqual(report["checks"]["authentication"]["status"], "FAIL")
        self.assertEqual(report["checks"]["quote"]["status"], "NOT_TESTED")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(len(self.requests), 1)

    def test_quote_failure_is_independent_of_successful_login(self):
        adapter = self._adapter("angelone")
        adapter.jwt_token = None
        error, _ = self._http_error("angelone", 503)
        self._reset_wire(dict(status=True, data=dict(jwtToken="OFFLINE_NEW_JWT")), error)
        report = self._run("angelone", adapter)
        self.assertEqual(report["initial_authentication"]["status"], "PASS")
        self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(report["checks"]["authentication"]["status"], "FAIL")
        self.assertTrue(report["session"]["currently_authenticated"])
        self.assertEqual(report["overall_status"], "FAIL")

    def test_mocked_success_is_labelled_and_cannot_issue_receipt(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider), self._candles(provider))
                with patch("readiness_policy._record_completed_diagnostic", side_effect=AssertionError("No receipt")) as receipt:
                    report = self._run(provider, adapter)
                self.assertEqual(report["overall_status"], "PASS")
                self.assertEqual(report["evidence_mode"], "MOCKED")
                self.assertEqual(report["market_data_acceptance"]["scope"], "OFFLINE_CONTRACT_ONLY")
                self.assertFalse(report["market_data_acceptance"]["live_accepted"])
                self.assertFalse(report["readiness_receipt_eligible"])
                self.assertFalse(report["readiness_receipt_issued"])
                receipt.assert_not_called()

    def test_upstox_quote_authorization_history_survives_candle_403(self):
        adapter = self._adapter("upstox")
        error, _ = self._http_error("upstox", 403)
        self._reset_wire(self._quote("upstox"), error)
        report = self._run("upstox", adapter)
        self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
        self.assertFalse(report["session"]["currently_authenticated"])
        self.assertTrue(report["session"]["invalidation_occurred"])
        self.assertEqual(report["checks"]["candles"]["error_category"], "FORBIDDEN")
        self.assertEqual(report["checks"]["candles"]["provider_cause"], "NOT_ESTABLISHED")
        self.assertEqual(report["overall_status"], "FAIL")

    def test_angel_403_and_429_have_distinct_adapter_categories(self):
        for status, expected in ((403, "ACCESS_DENIED"), (429, "RATE_LIMIT")):
            with self.subTest(status=status):
                adapter = self._adapter("angelone")
                error, stream = self._http_error("angelone", status)
                self._reset_wire(error)
                with self.assertRaises(BrokerDataError):
                    adapter.get_quote("RELIANCE")
                self.assertEqual(adapter.last_error_category, expected)
                self.assertTrue(stream.closed)

    def test_login_transport_failure_is_not_an_invalid_response_or_bad_credential_claim(self):
        adapter = self._adapter("angelone")
        adapter.jwt_token = None
        self._reset_wire(TimeoutError("TRANSPORT_CANARY"))
        report = self._run("angelone", adapter)
        self.assertEqual(report["initial_authentication"]["error_category"], "NETWORK_API_FAILURE")
        self.assertEqual(report["checks"]["quote"]["status"], "NOT_TESTED")
        self.assertNotIn("TRANSPORT_CANARY", json.dumps(report))

    def test_malformed_angel_json_is_classified_as_response_failure(self):
        adapter = self._adapter("angelone")
        self._reset_wire(b"{invalid JSON RESPONSE_CANARY")
        report = self._run("angelone", adapter)
        self.assertEqual(report["checks"]["quote"]["error_category"], "INVALID_RESPONSE")
        self.assertEqual(report["overall_status"], "FAIL")
        self.assertNotIn("RESPONSE_CANARY", json.dumps(report))

    def test_mocked_legacy_diagnostic_cannot_create_live_receipt(self):
        # Reuse the existing full nine-check fixture. All validations still run;
        # only its declared evidence mode changes at the real producer boundary.
        case = _fixtures.TestIndianFOSignalBotPhase3B1B(methodName="test_receipt_producer_and_expiry_boundary")
        case.setUp()
        self.addCleanup(case.doCleanups)
        with patch("readiness_policy._record_completed_diagnostic", side_effect=AssertionError("No mock receipt")) as writer:
            report = case._produce(evidence_mode="MOCKED")
        self.assertEqual(report["evidence_mode"], "MOCKED")
        self.assertFalse(report["live_acceptance"]["accepted"])
        self.assertIsNone(case.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
        writer.assert_not_called()

    def test_legacy_profile_fields_cannot_leak_configured_secrets(self):
        case = _fixtures.TestIndianFOSignalBotPhase3B1B(methodName="test_receipt_is_secret_free")
        case.setUp()
        self.addCleanup(case.doCleanups)
        def hostile_profile(responses):
            responses[1]["data"]["products"].append(case.cfg.angel_api_key)
            responses[1]["data"]["exchanges"].append(case.cfg.angel_totp_secret)
        report = case._produce(mutate=hostile_profile, evidence_mode="MOCKED")
        rendered = json.dumps(report)
        self.assertNotIn(case.cfg.angel_api_key, rendered)
        self.assertNotIn(case.cfg.angel_totp_secret, rendered)
        self.assertFalse(report["live_acceptance"]["accepted"])

    def test_receipt_writer_rejects_mock_mode_before_processing_observations(self):
        from readiness_policy import _record_completed_diagnostic
        adapter = self._adapter("angelone")
        for mode in ("MOCKED", "OFFLINE", "UNVERIFIED"):
            with self.subTest(mode=mode):
                result = _record_completed_diagnostic(adapter.config, None, adapter, {}, {}, [],
                    "RELIANCE", self.now, evidence_mode=mode)
                self.assertFalse(result["accepted"])
                self.assertEqual(result["reason_code"], "DIAGNOSTIC_EVIDENCE_MODE_NOT_LIVE")

    def test_login_http_statuses_and_malformed_login_are_classified_independently(self):
        for status, expected in ((401, "AUTH_FAILURE"), (403, "ACCESS_DENIED"), (429, "RATE_LIMIT"), (503, "NETWORK_API_FAILURE")):
            with self.subTest(status=status):
                adapter = self._adapter("angelone")
                error, _ = self._http_error("angelone", status)
                self._reset_wire(error)
                with self.assertRaises(BrokerDataError):
                    adapter.authenticate()
                self.assertEqual(adapter.last_error_category, expected)
                self.assertIsNone(adapter.jwt_token)
        for response in (b"NOT_JSON", []):
            with self.subTest(response_type=type(response).__name__):
                adapter = self._adapter("angelone")
                self._reset_wire(response)
                with self.assertRaises(BrokerDataError):
                    adapter.authenticate()
                self.assertEqual(adapter.last_error_category, "INVALID_RESPONSE")

    def test_identity_rejection_does_not_inherit_previous_http_error(self):
        adapter = self._adapter("angelone")
        error, _ = self._http_error("angelone", 429)
        self._reset_wire(error)
        with self.assertRaises(BrokerDataError):
            adapter.get_quote("RELIANCE")
        self.assertEqual(adapter.last_error_category, "RATE_LIMIT")
        request_count = len(self.requests)
        with self.assertRaises(BrokerDataError) as caught:
            adapter.get_quote("UNKNOWN_CASH_SYMBOL")
        self.assertEqual(caught.exception.error_category, "INVALID_INSTRUMENT_IDENTITY")
        self.assertEqual(adapter.last_error_category, "INVALID_INSTRUMENT_IDENTITY")
        self.assertIsNone(adapter.last_http_status)
        self.assertEqual(len(self.requests), request_count)


del _Wire  # Imported fixture class is not another discovered test selection.

if __name__ == "__main__":
    unittest.main(verbosity=2)
