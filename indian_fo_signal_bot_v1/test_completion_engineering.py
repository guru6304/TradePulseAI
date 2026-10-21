"""Completion regressions: synthetic inputs, temporary stores, forbidden transport."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]

from config import BotConfig
from strategies import TradeSignal


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


def signal_fixture(**changes):
    fields = dict(symbol="RELIANCE", segment="NSE_EQUITY_INTRADAY", strategy_id="strat_1_order_block",
        strategy_name="Offline ranking fixture", direction="BULLISH (BUY)", instrument_label="RELIANCE EQ",
        entry_price=100.0, entry_zone_low=99.0, entry_zone_high=100.0, stop_loss=98.0,
        invalidation_level=98.5, target_1=104.0, target_2=106.0, risk_reward="1:2 / 1:3",
        confidence_pct=60, quality_score=60, win_rate_benchmark="Unverified fixture only",
        position_qty=10, capital_risk_inr=25.0, est_charges_inr=5.0, rationale="Offline fixture",
        timestamp="2026-10-16 10:35:00", is_simulated=True, data_mode="SIMULATED",
        provider="paper_sim", state_context="SCANNER")
    fields.update(changes)
    return TradeSignal(**fields)


class TestCompletionConfiguration(unittest.TestCase):
    def test_commented_template_documentation_preserves_assignment_bytes_and_values(self):
        from config import _load_dotenv, ConfigValidationError
        heading = "Official Endpoints Used:"
        template = Path(__file__).with_name(".env.example").read_text(encoding="utf-8")
        self.assertIn(heading, template)
        assignments = "ACTIVE_BROKER=upstox\nUPSTOX_ACCESS_TOKEN=OFFLINE_REPAIR_CANARY\n"
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text(heading + "\n" + assignments, encoding="utf-8")
            with self.assertRaises(ConfigValidationError):
                _load_dotenv(str(path))
            self.assertNotIn("ACTIVE_BROKER", os.environ)
            path.write_text("# " + heading + "\n" + assignments, encoding="utf-8")
            _load_dotenv(str(path))
            self.assertEqual(os.environ["ACTIVE_BROKER"], "upstox")
            self.assertEqual(os.environ["UPSTOX_ACCESS_TOKEN"], "OFFLINE_REPAIR_CANARY")
            self.assertTrue(path.read_text().endswith(assignments))

    def test_invalid_utf8_does_not_apply_any_partial_configuration_or_echo_input(self):
        from config import _load_dotenv, ConfigValidationError
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_bytes(b"ACTIVE_BROKER=upstox\nCANARY=PRIVATE_CANARY\xff\n")
            with self.assertRaises(ConfigValidationError) as caught:
                _load_dotenv(str(path))
            self.assertNotIn("ACTIVE_BROKER", os.environ)
            self.assertNotIn("PRIVATE_CANARY", str(caught.exception))

    def test_syntax_diagnostic_classifies_without_disclosing_line_or_values(self):
        repository = Path(__file__).resolve().parent
        for raw, reason in (("MALFORMED_SECRET_CANARY", "DOTENV_ASSIGNMENT_MISSING_EQUALS"),
                            ("BAD KEY=SECRET_CANARY", "DOTENV_KEY_INVALID"),
                            ('UPSTOX_ACCESS_TOKEN="SECRET_CANARY', "DOTENV_QUOTE_UNTERMINATED")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                shutil.copyfile(repository / "config.py", temporary / "config.py")
                (temporary / ".env").write_text("# isolated fixture\n" + raw + "\n", encoding="utf-8")
                snippet = ("import sys,runpy;sys.path[:0]=sys.argv[1:3];"
                           "sys.argv=[sys.argv[3]];runpy.run_path(sys.argv[0],run_name='__main__')")
                result = subprocess.run([sys.executable, "-B", "-c", snippet, str(temporary), str(repository),
                    str(repository / "configuration_check.py")], cwd=temporary, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                report = json.loads(result.stdout)
                self.assertEqual(report["reason_code"], reason)
                self.assertEqual(report["line_number"], 2)
                self.assertNotIn("SECRET_CANARY", result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_comments_blank_lines_and_empty_values_are_handled_safely(self):
        repository = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            shutil.copyfile(repository / "config.py", temporary / "config.py")
            content = (
                "# Header comment\n"
                "   # Indented comment\n"
                "\n"
                "   \n"
                "TEST_EMPTY_VAL=\n"
                "ACTIVE_BROKER=paper_sim\n"
            )
            (temporary / ".env").write_text(content, encoding="utf-8")
            snippet = ("import sys,runpy;sys.path[:0]=sys.argv[1:3];"
                       "sys.argv=[sys.argv[3]];runpy.run_path(sys.argv[0],run_name='__main__')")
            result = subprocess.run([sys.executable, "-B", "-c", snippet, str(temporary), str(repository),
                str(repository / "configuration_check.py")], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["configuration_ready"])
            self.assertEqual(report["reason_code"], "LOCAL_CONFIGURATION_VALID")

    def test_nul_byte_and_missing_key_diagnostics(self):
        repository = Path(__file__).resolve().parent
        for raw, reason, expected_line in (
            ("=MISSING_KEY_CANARY", "DOTENV_KEY_INVALID", 2),
            ("VALID_KEY=VALUE\x00NUL_CANARY", "DOTENV_NUL_BYTE", 2),
        ):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                shutil.copyfile(repository / "config.py", temporary / "config.py")
                (temporary / ".env").write_text("# header\n" + raw + "\n", encoding="utf-8")
                snippet = ("import sys,runpy;sys.path[:0]=sys.argv[1:3];"
                           "sys.argv=[sys.argv[3]];runpy.run_path(sys.argv[0],run_name='__main__')")
                result = subprocess.run([sys.executable, "-B", "-c", snippet, str(temporary), str(repository),
                    str(repository / "configuration_check.py")], cwd=temporary, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                report = json.loads(result.stdout)
                self.assertEqual(report["reason_code"], reason)
                self.assertEqual(report["line_number"], expected_line)
                self.assertNotIn("CANARY", result.stdout + result.stderr)

    def test_environment_precedence_and_duplicate_keys(self):
        from config import _load_dotenv
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("PRECEDENCE_KEY=FROM_FILE_1\nPRECEDENCE_KEY=FROM_FILE_2\nOTHER_KEY=FROM_FILE\n", encoding="utf-8")
            with patch.dict(os.environ, {"OTHER_KEY": "FROM_PROCESS"}, clear=False):
                _load_dotenv(str(env_file))
                self.assertEqual(os.environ["PRECEDENCE_KEY"], "FROM_FILE_1")
                self.assertEqual(os.environ["OTHER_KEY"], "FROM_PROCESS")

    def test_workspace_relative_discovery_ignores_arbitrary_cwd(self):
        repository = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proj = root / "proj"
            proj.mkdir()
            shutil.copyfile(repository / "config.py", proj / "config.py")
            (proj / ".env").write_text("ACTIVE_BROKER=paper_sim\nDISCOVERED_TOKEN=FROM_PROJ\n", encoding="utf-8")
            other_dir = root / "arbitrary_cwd"
            other_dir.mkdir()
            (other_dir / ".env").write_text("ACTIVE_BROKER=upstox\nDISCOVERED_TOKEN=FROM_CWD\n", encoding="utf-8")
            code = ("import sys,os;sys.path.insert(0, sys.argv[1]);from config import BotConfig,_load_dotenv;"
                    "_load_dotenv();print(os.environ.get('DISCOVERED_TOKEN',''))")
            result = subprocess.run([sys.executable, "-B", "-c", code, str(proj)],
                cwd=other_dir, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), "FROM_PROJ")

    def test_syntax_pass_does_not_declare_broker_or_readiness_receipt(self):
        repository = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            shutil.copyfile(repository / "config.py", temporary / "config.py")
            (temporary / ".env").write_text("ACTIVE_BROKER=paper_sim\nTELEGRAM_DRY_RUN=true\nENABLE_BACKGROUND_SCHEDULER=false\n", encoding="utf-8")
            snippet = ("import sys,runpy;sys.path[:0]=sys.argv[1:3];"
                       "sys.argv=[sys.argv[3]];runpy.run_path(sys.argv[0],run_name='__main__')")
            result = subprocess.run([sys.executable, "-B", "-c", snippet, str(temporary), str(repository),
                str(repository / "configuration_check.py")], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["scope"], "LOCAL_CONFIGURATION_ONLY")
            self.assertEqual(report["authentication"], "NOT_TESTED")
            self.assertEqual(report["quote"], "NOT_TESTED")
            self.assertEqual(report["candles"], "NOT_TESTED")
            self.assertFalse(report["readiness_receipt_issued"])
            self.assertFalse(report["live_requests"])



class TestCandidateValidationAndRanking(unittest.TestCase):
    def test_required_store_initialization_failure_blocks_delivery_and_reports_error(self):
        from datetime import datetime
        from brokers import MultiBrokerScanner, SimulatedNSEAdapter
        from scanner_engine import IntradayBotEngine
        from storage import PersistenceError
        from strategies import IST
        clock = lambda: datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        cfg = BotConfig(active_broker="paper_sim", telegram_dry_run=True,
                        enable_persistence=True, database_url=":memory:")
        scanner = MultiBrokerScanner(cfg, clock=clock)
        scanner.adapters["paper_sim"] = _fixtures._FixtureTriggeredAdapter(SimulatedNSEAdapter(clock=clock))
        with patch("scanner_engine.SQLitePersistenceStore", side_effect=PersistenceError("Offline init failure")):
            engine = IntradayBotEngine(cfg, clock=clock, broker_scanner=scanner)
        self.addCleanup(engine.close)
        with patch.object(engine.telegram, "send_signal", side_effect=AssertionError("No unaudited delivery")) as delivery:
            report = engine.run_single_scan()
        self.assertGreater(report["total_signals"], 0)
        self.assertEqual(report["persistence_status"], "ERROR")
        self.assertEqual(report["persistence_error"], "Offline init failure")
        delivery.assert_not_called()
        self.assertTrue(all(item.get("reason") == "persistence_unavailable"
                            for item in report["telegram_dispatches"]))

    def test_quality_then_observed_reward_risk_then_identity_order_is_input_invariant(self):
        from strategies import rank_signal_candidates
        signals = [signal_fixture(symbol="TCS", instrument_label="TCS EQ"),
                   signal_fixture(symbol="INFY", instrument_label="INFY EQ"),
                   signal_fixture(symbol="SBIN", instrument_label="SBIN EQ", target_1=105),
                   signal_fixture(symbol="LT", instrument_label="LT EQ", quality_score=80)]
        original = [copy.deepcopy(signal.to_dict()) for signal in signals]
        expected = ["LT", "SBIN", "INFY", "TCS"]
        self.assertEqual([s.symbol for s in rank_signal_candidates(signals)], expected)
        self.assertEqual([s.symbol for s in rank_signal_candidates(list(reversed(signals)))], expected)
        self.assertEqual([s.to_dict() for s in signals], original)

    def test_malformed_levels_scores_and_direction_are_rejected(self):
        from strategies import validate_trade_signal
        changes = [dict(target_1=99), dict(target_2=103), dict(entry_zone_high=98),
                   dict(invalidation_level=101), dict(target_1=float("inf")),
                   dict(quality_score=True), dict(quality_score=101),
                   dict(position_type="SHORT_EQUITY_INTRADAY"), dict(position_qty=True)]
        for mutation in changes:
            with self.subTest(fields=list(mutation)), self.assertRaises(ValueError):
                validate_trade_signal(signal_fixture(**mutation))

    def test_short_and_long_put_premium_have_distinct_price_ordering(self):
        from strategies import validate_trade_signal
        short = signal_fixture(direction="BEARISH (SELL)", stop_loss=102, invalidation_level=101.5,
                               target_1=96, target_2=94)
        put = signal_fixture(direction="BEARISH (BUY PE)", segment="NSE_FO_INDEX")
        validate_trade_signal(short)
        validate_trade_signal(put)

    def test_storage_cannot_persist_invalid_target_geometry(self):
        from storage import SQLitePersistenceStore, PersistenceValidationError
        with SQLitePersistenceStore(":memory:") as store:
            with self.assertRaises(PersistenceValidationError):
                store.save_signal(signal_fixture(target_1=99), broker="Paper Sim")
            self.assertEqual(store.query_signals()["total_count"], 0)

    def test_telegram_reports_setup_quality_and_configured_risk_without_benchmark_claim(self):
        from telegram_bot import TelegramSignalDispatcher
        cfg = BotConfig(active_broker="paper_sim", telegram_dry_run=True, max_risk_per_trade_pct=0.5)
        with patch("urllib.request.urlopen", side_effect=AssertionError("No delivery")):
            result = TelegramSignalDispatcher(cfg).send_signal(signal_fixture(), broker_name="Paper Sim")
        text = result["message_html"]
        self.assertIn("Setup Quality:", text)
        self.assertIn("60/100", text)
        self.assertIn("0.5%", text)
        self.assertNotIn("Unverified fixture only", text)
        self.assertNotIn("Confidence:", text)
        self.assertNotIn("1% Risk", text)
        self.assertTrue(result["dry_run"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
