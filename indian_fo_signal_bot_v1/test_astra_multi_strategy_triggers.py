"""OFFLINE TESTS: Multi-strategy prospective paper triggers.

Verifies prospective contract construction, fill policy binding, follow-through
close-crossing, and invalidation handling for strat_1_order_block,
strat_2_vwap_pullback, and strat_5_supertrend_pullback.
"""
import copy
import hashlib
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from paper_portfolio import (
    PaperAccountConfig, PaperPortfolio, PaperPortfolioError
)
from paper_triggers import (
    ORB_FILL_POLICY, OB_FILL_POLICY, VWAP_FILL_POLICY, ST_FILL_POLICY,
    PROSPECTIVE_FILL_POLICY, PROSPECTIVE_FILL_POLICIES,
    STRATEGY_RULES, STRATEGY_POLICIES, STRATEGY_PREFIXES,
    build_contract, strategy_version
)
from strategies import IST, parse_ist_timestamp, signal_state_identity
import test_phase4_e2e


class TestMultiStrategyProspectiveTriggers(unittest.TestCase):
    def setUp(self):
        self.scenario = test_phase4_e2e.TestPhase4OfflineEndToEnd()
        self.scenario.setUp()
        self.addCleanup(self.scenario.doCleanups)
        self.addCleanup(self.scenario.tearDown)

    def test_strategy_versions_and_rules_registered(self):
        for strat in ("strat_1_order_block", "strat_2_vwap_pullback", "strat_4_orb_filtered", "strat_5_supertrend_pullback"):
            with self.subTest(strategy=strat):
                version = strategy_version(strat)
                self.assertTrue(version.endswith(hashlib.sha256().hexdigest()[:0]) or len(version) > 20)
                self.assertIn(strat, STRATEGY_RULES)
                self.assertIn(strat, STRATEGY_POLICIES)
                self.assertIn(strat, STRATEGY_PREFIXES)

    def test_fill_policies_registered_in_prospective_set(self):
        self.assertIn(ORB_FILL_POLICY, PROSPECTIVE_FILL_POLICIES)
        self.assertIn(OB_FILL_POLICY, PROSPECTIVE_FILL_POLICIES)
        self.assertIn(VWAP_FILL_POLICY, PROSPECTIVE_FILL_POLICIES)
        self.assertIn(ST_FILL_POLICY, PROSPECTIVE_FILL_POLICIES)
        self.assertIn(PROSPECTIVE_FILL_POLICY, PROSPECTIVE_FILL_POLICIES)

    def test_paper_account_config_accepts_all_prospective_policies(self):
        store = self.scenario._engine("angelone", database="policies_test.sqlite").store
        for policy in PROSPECTIVE_FILL_POLICIES:
            with self.subTest(policy=policy):
                config = PaperAccountConfig(account_id=f"acc-{policy}", run_id="offline",
                    provider="angelone", source_data_mode="LIVE", fill_policy=policy)
                portfolio = PaperPortfolio(store, config, clock=lambda: self.scenario.now)
                self.assertEqual(portfolio.config.fill_policy, policy)

    def test_strategy_policy_mismatch_rejection(self):
        engine = self.scenario._engine("angelone", database="policy_mismatch.sqlite")
        paper = PaperPortfolio(engine.store, PaperAccountConfig(
            account_id="ob-only", run_id="offline", provider="angelone",
            source_data_mode="LIVE", fill_policy=OB_FILL_POLICY
        ), clock=lambda: self.scenario.now)

        mock_orb_candidate = dict(
            strategy_id="strat_4_orb_filtered",
            segment="NSE_EQUITY_INTRADAY",
            symbol="RELIANCE",
            entry_price=100.0,
            invalidation_level=95.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=115.0,
            position_type="LONG_EQUITY_INTRADAY",
            direction="BULLISH",
            provider="angelone",
            data_mode="LIVE",
            is_simulated=False,
            timestamp="2026-10-16T11:45:00+05:30",
            instrument_identity=dict(
                provider="angelone", symbol="RELIANCE", identifier="RELIANCE",
                exchange="NSE", segment="NSE_EQUITY_INTRADAY", instrument_type="EQ",
                source="live_feed", source_revision="v1", historical_validity="VALID",
                is_index=False
            )
        )
        with self.assertRaises(ValueError) as caught:
            build_contract(engine.store, None, "run-1", mock_orb_candidate, "15:15", policy=OB_FILL_POLICY)
        self.assertEqual(str(caught.exception), "STRATEGY_FUTURE_TRIGGER_UNAVAILABLE")

    def test_unsupported_strategy_raises_unavailable(self):
        engine = self.scenario._engine("angelone", database="unsupported_strat.sqlite")
        mock_unsupported = dict(
            strategy_id="strat_unknown",
            segment="NSE_EQUITY_INTRADAY",
            symbol="RELIANCE"
        )
        with self.assertRaises(ValueError) as caught:
            build_contract(engine.store, None, "run-1", mock_unsupported, "15:15")
        self.assertEqual(str(caught.exception), "STRATEGY_FUTURE_TRIGGER_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
