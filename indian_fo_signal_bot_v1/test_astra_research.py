"""Research-contract and partition regressions; fixtures never prove performance."""
import copy
import json
import unittest
from unittest.mock import patch

import test_bot  # Apply the canonical offline environment before production imports.
from backtest_engine import BacktestConfig
from historical_study import run_frozen_study, walk_forward_plan
from strategy_evidence import strategy_evidence


class TestAstraStrategyEvidence(unittest.TestCase):
    def test_existing_strategies_are_mechanics_only_without_empirical_metrics(self):
        from strategies import STRATEGY_WARMUP_BARS
        for strategy_id, warmup in STRATEGY_WARMUP_BARS.items():
            with self.subTest(strategy_id=strategy_id):
                result = strategy_evidence(strategy_id)
                self.assertEqual(result["maturity_state"], "OFFLINE_MECHANICS_TESTED")
                self.assertEqual(result["empirical_status"], "EMPIRICAL_VALIDATION_BLOCKED")
                self.assertEqual(result["min_completed_bars"], warmup)
                self.assertIsNone(result["empirical_metrics"])
                self.assertFalse(result["empirical_performance_claim_allowed"])
                self.assertFalse(result["promotion_automatic"])
                self.assertEqual(result["score_semantics"], "RULE_SCORE_NOT_WIN_PROBABILITY")
                json.dumps(result, allow_nan=False)

    def test_unknown_strategy_cannot_inherit_tested_or_promoted_status(self):
        result = strategy_evidence("unregistered")
        self.assertFalse(result["supported"])
        self.assertEqual(result["maturity_state"], "RESEARCH_HYPOTHESIS")
        self.assertIsNone(result["rule_version"])
        for invalid in (None, {}, [], True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                strategy_evidence(invalid)

    def test_returned_evidence_cannot_mutate_registry_or_promote_later_calls(self):
        result = strategy_evidence("strat_4_orb_filtered")
        result["maturity_state"] = "OUT_OF_SAMPLE_EVIDENCE_AVAILABLE"
        result["requirements"].clear()
        result["target_risk_multipliers"].append(99)
        again = strategy_evidence("strat_4_orb_filtered")
        self.assertEqual(again["maturity_state"], "OFFLINE_MECHANICS_TESTED")
        self.assertGreater(len(again["requirements"]), 0)
        self.assertEqual(again["target_risk_multipliers"], [1.6, 2.4])

    def test_strategy_specific_confirmation_and_premium_semantics_are_retained(self):
        ob = strategy_evidence("strat_1_order_block")
        orb = strategy_evidence("strat_4_orb_filtered")
        option = strategy_evidence("strat_3_option_apex_oi")
        self.assertIn("FIRST_RETEST", ob["entry_rule"])
        self.assertIn("CROSSING_OPENING_RANGE", orb["entry_rule"])
        self.assertEqual(option["position_semantics"], "LONG_CALL_OPTION_OR_LONG_PUT_OPTION")
        self.assertIn("contract premium", " ".join(option["requirements"]))
        self.assertEqual(strategy_evidence("strat_2_vwap_pullback")["rsi_bands"],
            {"long_inclusive": [48.0, 72.0], "short_inclusive": [28.0, 52.0]})
        self.assertEqual(option["pcr_thresholds"],
            {"long_call_min_inclusive": 1.10, "long_put_max_inclusive": 0.85})
        self.assertIn("grants no entry authority", option["paper_policy_relationship"])


class TestAstraFrozenStudyPartitions(unittest.TestCase):
    def setUp(self):
        from test_historical_study import TestHistoricalStudy
        self.fixture = TestHistoricalStudy()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.bars = self.fixture.bars()
        self.sessions = sorted({bar["timestamp"][:10] for bar in self.bars})

    def run_study(self, plan):
        return run_frozen_study(self.fixture.engine, strategy_id="strat_1_order_block",
            symbol="RELIANCE", provider="paper_sim", candles=self.bars, instrument_token="2885",
            backtest_config=BacktestConfig(execution_scope="SIMULATED_TEST"), plan=plan)

    def test_omitted_session_inside_declared_test_range_is_rejected(self):
        plan = walk_forward_plan(self.sessions, training_sessions=1, test_sessions=3)
        plan["folds"][0]["test_sessions"].remove(self.sessions[2])
        with self.assertRaisesRegex(ValueError, "every source session"):
            self.run_study(plan)

    def test_omitted_training_session_cannot_silently_change_warmup_prefix(self):
        plan = walk_forward_plan(self.sessions, training_sessions=3, test_sessions=1)
        plan["folds"][0]["train_sessions"].remove(self.sessions[1])
        with self.assertRaisesRegex(ValueError, "every source session"):
            self.run_study(plan)

    def test_undeclared_early_or_gap_warmup_is_rejected_before_retaining_or_evaluating(self):
        for omitted in (self.sessions[0], self.sessions[2]):
            plan = walk_forward_plan(self.sessions, training_sessions=3, test_sessions=1)
            plan["folds"][0]["train_sessions"].remove(omitted)
            with self.subTest(omitted=omitted), \
                    patch.object(self.fixture.engine, "run_backtest") as execute, \
                    patch("historical_study.HistoricalEvidenceArchive.retain") as retain:
                with self.assertRaisesRegex(ValueError, "every source session"):
                    self.run_study(plan)
                execute.assert_not_called()
                retain.assert_not_called()

    def test_option_study_also_rejects_undeclared_test_session_before_evaluation(self):
        plan = walk_forward_plan(self.sessions, training_sessions=1, test_sessions=3)
        plan["folds"][0]["test_sessions"].remove(self.sessions[2])
        request = {"dataset_json": json.dumps({"underlying_candles": self.bars})}
        with patch.object(self.fixture.engine, "run_backtest") as execute:
            with self.assertRaisesRegex(ValueError, "every source session"):
                run_frozen_study(self.fixture.engine, strategy_id="strat_3_option_apex_oi",
                    symbol="NIFTY", provider="paper_sim", option_request=request,
                    backtest_config=BacktestConfig(execution_scope="SIMULATED_TEST"), plan=plan)
            execute.assert_not_called()

    def test_explicit_unscored_step_session_stays_in_later_training_prefix(self):
        plan = walk_forward_plan(self.sessions, training_sessions=1, test_sessions=1, step_sessions=2)
        result = self.run_study(plan)
        self.assertEqual(result["folds"][1]["train_sessions"], self.sessions[:3])
        self.assertNotIn(self.sessions[2], [s for fold in result["folds"] for s in fold["test_sessions"]])

    def test_valid_complete_plan_remains_repeatable_and_fixture_labelled(self):
        plan = walk_forward_plan(self.sessions, training_sessions=2, test_sessions=1)
        unchanged = copy.deepcopy(plan)
        first = self.run_study(plan)
        second = self.run_study(plan)
        self.assertEqual(plan, unchanged)
        self.assertEqual(first["study_id"], second["study_id"])
        self.assertEqual(first["real_historical_study_status"], "BLOCKED")
        self.assertFalse(first["empirical_performance_claim_allowed"])
        for fold in first["folds"]:
            for trade in fold["run"]["trades"]:
                self.assertIn(trade["entry_timestamp"][:10], fold["test_sessions"])


if __name__ == "__main__":
    unittest.main()
