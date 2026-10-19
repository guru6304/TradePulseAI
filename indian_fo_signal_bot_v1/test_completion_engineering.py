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


class TestCandidateValidationAndRanking(unittest.TestCase):
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
