"""Phase 4 deterministic offline fixtures; no market acceptance evidence."""
import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import test_bot  # Credential-free test bootstrap before broker/config imports.
from brokers import SimulatedNSEAdapter
from strategies import (
    IST, STRATEGY_WARMUP_BARS, TradeSignal, evaluate_strategy_detailed,
    evaluate_order_block_fvg, evaluate_vwap_pullback, evaluate_option_apex_oi_shift,
    evaluate_orb_breakout, evaluate_supertrend_pullback, filter_completed_candles,
    rank_signal_candidates, signal_risk_reward,
)


class TestPhase4StrategyExplanations(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.now)

    def candles(self, symbol="RELIANCE", pattern="order_block_bull"):
        return self.sim.get_intraday_candles({"symbol": symbol}, interval_min=5, pattern=pattern)

    def assert_json(self, value):
        self.assertEqual(value, json.loads(json.dumps(value, allow_nan=False)))

    def test_all_five_bidirectional_actual_signals_match_direct_evaluation(self):
        fixtures = [
            ("strat_1_order_block", evaluate_order_block_fvg, "RELIANCE", "order_block_bull", {}),
            ("strat_1_order_block", evaluate_order_block_fvg, "BAJFINANCE", "order_block_bear", {}),
            ("strat_2_vwap_pullback", evaluate_vwap_pullback, "TCS", "vwap_pullback_bull", {}),
            ("strat_2_vwap_pullback", evaluate_vwap_pullback, "INFY", "vwap_pullback_bear", {}),
            ("strat_3_option_apex_oi", evaluate_option_apex_oi_shift, "NIFTY", "vwap_pullback_bull",
             {"option_chain": self.sim.get_option_chain("NIFTY", bias="BULLISH"), "lot_size": 75, "capital_inr": 500000}),
            ("strat_3_option_apex_oi", evaluate_option_apex_oi_shift, "BANKNIFTY", "vwap_pullback_bear",
             {"option_chain": self.sim.get_option_chain("BANKNIFTY", bias="BEARISH"), "lot_size": 30, "capital_inr": 500000}),
            ("strat_4_orb_filtered", evaluate_orb_breakout, "ICICIBANK", "orb_breakout_bull", {}),
            ("strat_4_orb_filtered", evaluate_orb_breakout, "AXISBANK", "orb_breakout_bear", {}),
            ("strat_5_supertrend_pullback", evaluate_supertrend_pullback, "SBIN", "supertrend_pullback_bull", {}),
            ("strat_5_supertrend_pullback", evaluate_supertrend_pullback, "TATAMOTORS", "supertrend_pullback_bear", {}),
        ]
        for sid, fn, symbol, pattern, args in fixtures:
            with self.subTest(sid=sid, symbol=symbol):
                bars = self.candles(symbol, pattern)
                direct = fn(symbol, copy.deepcopy(bars), **copy.deepcopy(args))
                candidate, trace = evaluate_strategy_detailed(sid, copy.deepcopy(bars), symbol=symbol, **copy.deepcopy(args))
                self.assertIsNotNone(direct)
                self.assertEqual(direct.to_dict(), candidate.to_dict())
                self.assertEqual(trace["status"], "DETECTED")
                self.assertEqual(trace["reason_codes"], ["SETUP_DETECTED"])
                self.assertEqual(trace["warmup"], {"required": STRATEGY_WARMUP_BARS[sid],
                    "observed": len(filter_completed_candles(bars)), "interval_min": 5})
                self.assertTrue(any(row["rule_id"] == "risk.position_size" and row["status"] == "PASS" for row in trace["rule_checks"]))
                self.assertTrue(signal_risk_reward(candidate)["allowed"])
                self.assert_json(trace)

    def test_all_five_warmup_below_and_exact_boundary(self):
        bars = self.candles("SBIN", "supertrend_pullback_bull")
        chain = self.sim.get_option_chain("NIFTY", bias="BULLISH")
        for sid, required in STRATEGY_WARMUP_BARS.items():
            for size in (required - 1, required):
                with self.subTest(strategy=sid, size=size):
                    args = {"symbol": "NIFTY", "option_chain": chain, "lot_size": 75} if sid == "strat_3_option_apex_oi" else {"symbol": "SBIN"}
                    _, trace = evaluate_strategy_detailed(sid, bars[-size:] if size else [], **args)
                    self.assertEqual(trace["warmup"]["observed"], size)
                    check = next(row for row in trace["rule_checks"] if row["rule_id"] == "data.warmup")
                    self.assertEqual(check["status"], "UNAVAILABLE" if size < required else "PASS")
                    if size < required:
                        self.assertEqual(trace["status"], "UNAVAILABLE")
                        self.assertIn("INSUFFICIENT_COMPLETED_CANDLES", trace["reason_codes"])

    def test_completed_count_excludes_explicit_incomplete_and_future_bars(self):
        bars = self.candles("TCS", "vwap_pullback_bull")[-35:]
        bars[-1]["is_complete"] = False
        _, trace = evaluate_strategy_detailed("strat_2_vwap_pullback", bars, symbol="TCS", now=self.now)
        self.assertEqual(trace["warmup"]["observed"], 34)
        self.assertEqual(trace["status"], "UNAVAILABLE")
        bars[-1]["is_complete"] = True
        _, trace = evaluate_strategy_detailed("strat_2_vwap_pullback", bars, symbol="TCS", now=self.now - timedelta(minutes=5))
        self.assertEqual(trace["warmup"]["observed"], 34)
        self.assertEqual(trace["status"], "UNAVAILABLE")

    def test_volume_rejection_records_actual_threshold(self):
        bars = self.candles("INFY", "vwap_pullback_bear")
        bars[-1]["volume"] = 25000
        candidate, trace = evaluate_strategy_detailed("strat_2_vwap_pullback", bars, symbol="INFY")
        self.assertIsNone(candidate)
        self.assertEqual(trace["status"], "REJECTED")
        self.assertIn("VOLUME_SURGE_BELOW_1_4", trace["reason_codes"])
        row = next(row for row in trace["rule_checks"] if row["reason"] == "VOLUME_SURGE_BELOW_1_4")
        self.assertEqual(row["measurements"]["threshold"], 1.4)
        self.assertLess(row["measurements"]["rvol"], 1.4)
        self.assertFalse(any(row["rule_id"] == "rsi.bear" for row in trace["rule_checks"]))

    def test_zero_baseline_volume_unavailable(self):
        bars = self.candles("TCS", "vwap_pullback_bull")
        for row in bars:
            row["volume"] = 0
        _, trace = evaluate_strategy_detailed("strat_2_vwap_pullback", bars, symbol="TCS")
        self.assertEqual(trace["status"], "UNAVAILABLE")
        self.assertIn("POSITIVE_BASELINE_VOLUME_REQUIRED", trace["reason_codes"])

    def test_option_chain_missing_and_invalid_fail_without_invented_oi(self):
        bars = self.candles("NIFTY", "vwap_pullback_bull")
        _, missing = evaluate_strategy_detailed("strat_3_option_apex_oi", bars, symbol="NIFTY", option_chain=None)
        self.assertEqual(missing["status"], "UNAVAILABLE")
        self.assertIn("OPTION_CHAIN_REQUIRED", missing["reason_codes"])
        self.assertFalse(any(row["rule_id"].startswith("oi.") for row in missing["rule_checks"]))
        bad_chain = self.sim.get_option_chain("NIFTY", bias="BULLISH")
        del bad_chain["pcr"]
        with self.assertRaises(ValueError):
            evaluate_option_apex_oi_shift("NIFTY", bars, bad_chain)
        candidate, invalid = evaluate_strategy_detailed("strat_3_option_apex_oi", bars, symbol="NIFTY", option_chain=bad_chain)
        self.assertIsNone(candidate)
        self.assertIn("INVALID_EVALUATION_INPUT", invalid["reason_codes"])
        self.assert_json(invalid)

    def test_orb_missing_opening_bar_is_unavailable(self):
        bars = self.candles("ICICIBANK", "orb_breakout_bull")
        bars = [row for row in bars if row["timestamp"] != "2026-10-16 09:15:00"]
        _, trace = evaluate_strategy_detailed("strat_4_orb_filtered", bars, symbol="ICICIBANK")
        self.assertEqual(trace["status"], "UNAVAILABLE")
        self.assertIn("ORB_OPENING_RANGE_BARS_MISSING", trace["reason_codes"])

    def test_missing_current_session_open_cannot_use_partial_vwap(self):
        cases = [
            ("strat_1_order_block", evaluate_order_block_fvg, "RELIANCE", "order_block_bull", {}),
            ("strat_2_vwap_pullback", evaluate_vwap_pullback, "TCS", "vwap_pullback_bull", {}),
            ("strat_3_option_apex_oi", evaluate_option_apex_oi_shift, "NIFTY", "vwap_pullback_bull",
             {"option_chain": self.sim.get_option_chain("NIFTY", bias="BULLISH"), "lot_size": 75, "capital_inr": 500000}),
            ("strat_5_supertrend_pullback", evaluate_supertrend_pullback, "SBIN", "supertrend_pullback_bull", {}),
        ]
        for sid, fn, symbol, pattern, arguments in cases:
            with self.subTest(strategy=sid):
                bars = self.candles(symbol, pattern)
                self.assertIsNotNone(fn(symbol, bars, **arguments))
                trimmed = [row for row in bars if row["timestamp"] != "2026-10-16 09:15:00"]
                self.assertGreaterEqual(len(trimmed), STRATEGY_WARMUP_BARS[sid])
                self.assertIsNone(fn(symbol, trimmed, **arguments))
                candidate, trace = evaluate_strategy_detailed(sid, trimmed, symbol=symbol, **arguments)
                self.assertIsNone(candidate)
                self.assertEqual(trace["status"], "UNAVAILABLE")
                self.assertIn("SESSION_START_COVERAGE_MISSING", trace["reason_codes"])
                row = next(row for row in trace["rule_checks"] if row["rule_id"] == "session.vwap_start")
                self.assertEqual(row["measurements"]["observed_first_timestamp"], "2026-10-16 09:20:00")

    def test_supertrend_excluded_window_is_rule_rejection(self):
        bars = self.candles("SBIN", "supertrend_pullback_bull")
        bars[-1]["timestamp"] = "2026-10-16 12:15:00"
        _, trace = evaluate_strategy_detailed("strat_5_supertrend_pullback", bars, symbol="SBIN")
        self.assertEqual(trace["status"], "REJECTED")
        self.assertIn("SUPERTREND_EXCLUDED_SESSION_WINDOW", trace["reason_codes"])

    def test_invalid_candles_unavailable_and_direct_contract_unchanged(self):
        bars = self.candles()
        bars[-1]["high"] = -1
        with self.assertRaises(ValueError):
            evaluate_order_block_fvg("RELIANCE", bars)
        candidate, trace = evaluate_strategy_detailed("strat_1_order_block", bars, symbol="RELIANCE")
        self.assertIsNone(candidate)
        self.assertEqual(trace["status"], "UNAVAILABLE")
        self.assertEqual(trace["reason_codes"], ["INVALID_EVALUATION_INPUT"])
        self.assertNotIn("-1", json.dumps(trace))

    def test_ob_trace_preserves_mitigation_state_and_duplicate_rejection(self):
        bars = self.candles()
        zones = set()
        candidate, first = evaluate_strategy_detailed("strat_1_order_block", bars, symbol="RELIANCE", mitigated_zones=zones)
        self.assertIsNotNone(candidate)
        self.assertEqual(len(zones), 1)
        duplicate, second = evaluate_strategy_detailed("strat_1_order_block", bars, symbol="RELIANCE", mitigated_zones=zones)
        self.assertIsNone(duplicate)
        self.assertEqual(second["status"], "REJECTED")
        self.assertIn("BULL_BLOCK_ALREADY_MITIGATED", second["reason_codes"])

    def test_override_without_trace_is_called_once(self):
        bars = self.candles()
        expected = evaluate_order_block_fvg("RELIANCE", bars)
        override = Mock(side_effect=lambda symbol, candles: expected)
        actual, trace = evaluate_strategy_detailed("strat_1_order_block", bars, symbol="RELIANCE", evaluator=override)
        self.assertIs(actual, expected)
        override.assert_called_once_with(symbol="RELIANCE", candles=bars)
        self.assertEqual(trace["status"], "DETECTED")
        self.assertEqual(trace["rule_checks"][0]["reason"], "CALLABLE_DIAGNOSTICS_UNAVAILABLE")

    def test_override_without_candidate_or_trace_is_unavailable(self):
        override = Mock(side_effect=lambda symbol, candles: None)
        candidate, trace = evaluate_strategy_detailed("strat_1_order_block", [], symbol="RELIANCE", evaluator=override)
        self.assertIsNone(candidate)
        self.assertEqual(override.call_count, 1)
        self.assertEqual(trace["status"], "UNAVAILABLE")
        self.assertIn("CALLABLE_DIAGNOSTICS_UNAVAILABLE", trace["reason_codes"])

    def test_wrapped_evaluator_retains_diagnostics(self):
        bars = self.candles()
        wrapped = Mock(wraps=evaluate_order_block_fvg)
        signal, trace = evaluate_strategy_detailed("strat_1_order_block", bars, symbol="RELIANCE", evaluator=wrapped)
        self.assertIsNotNone(signal)
        self.assertEqual(wrapped.call_count, 1)
        self.assertTrue(any(row["rule_id"] == "data.warmup" for row in trace["rule_checks"]))

    def test_internal_type_error_does_not_retry_or_echo_private_error(self):
        def faulty(symbol, candles, evaluation_trace=None):
            raise TypeError("private-token-value")
        override = Mock(side_effect=faulty)
        candidate, trace = evaluate_strategy_detailed("strat_1_order_block", [], symbol="RELIANCE", evaluator=override)
        self.assertIsNone(candidate)
        self.assertEqual(override.call_count, 1)
        self.assertEqual(trace["status"], "UNAVAILABLE")
        self.assertNotIn("private-token-value", json.dumps(trace))

    def test_unknown_strategy_and_missing_symbol_are_unavailable(self):
        candidate, trace = evaluate_strategy_detailed("unimplemented", [])
        self.assertIsNone(candidate)
        self.assertEqual(trace["reason_codes"], ["UNSUPPORTED_STRATEGY"])
        candidate, trace = evaluate_strategy_detailed("strat_1_order_block", self.candles())
        self.assertIsNone(candidate)
        self.assertEqual(trace["reason_codes"], ["STRATEGY_SYMBOL_REQUIRED"])


class TestPhase4NumericRiskAndRanking(unittest.TestCase):
    def signal(self, **changes):
        base = TradeSignal(symbol="FIXTURE", segment="NSE_EQUITY_INTRADAY", strategy_id="strat_2_vwap_pullback",
            strategy_name="Offline fixture", direction="BULLISH (BUY)", instrument_label="FIXTURE EQ",
            entry_price=100.0, entry_zone_low=99.8, entry_zone_high=100.0, stop_loss=99.8,
            invalidation_level=99.9, target_1=100.9, target_2=101.25, risk_reward="deliberately nonnumeric label",
            confidence_pct=70, quality_score=70, win_rate_benchmark="UNVERIFIED", position_qty=10,
            capital_risk_inr=2.0, est_charges_inr=1.5, rationale="Offline fixture only",
            timestamp="2026-10-16 10:30:00", is_simulated=True, data_mode="SIMULATED")
        return replace(base, **changes)

    def test_gross_ratios_use_actual_levels_not_nominal_floor_or_label(self):
        result = signal_risk_reward(self.signal())
        self.assertTrue(result["allowed"])
        self.assertAlmostEqual(result["risk_per_unit"], .2)
        self.assertAlmostEqual(result["target1_ratio"], 4.5)
        self.assertAlmostEqual(result["target2_ratio"], 6.25)
        self.assertEqual(result["estimated_net_rr"]["status"], "UNAVAILABLE")
        self.assertEqual(result["estimated_charges_per_unit"], .15)
        self.assertEqual(result["liquidity_status"], "NOT_ESTABLISHED")
        json.dumps(result, allow_nan=False)

    def test_short_geometry_and_long_put_premium_both_supported(self):
        short = self.signal(direction="BEARISH (SELL)", position_type="SHORT_EQUITY_INTRADAY",
            stop_loss=100.2, invalidation_level=100.1, target_1=99.1, target_2=98.75)
        put = self.signal(direction="BEARISH (BUY PE)", position_type="LONG_PUT_OPTION", segment="NSE_FO_INDEX")
        for signal in (short, put):
            result = signal_risk_reward(signal)
            self.assertTrue(result["allowed"])
            self.assertAlmostEqual(result["target1_ratio"], 4.5)
            self.assertAlmostEqual(result["target2_ratio"], 6.25)

    def test_invalid_geometry_has_no_supported_ratio(self):
        for changes in ({"stop_loss": 100}, {"target_1": 99}, {"target_2": float("nan")},
                {"entry_price": True}, {"position_qty": 0}, {"invalidation_level": 100.1}):
            with self.subTest(changes=changes):
                result = signal_risk_reward(self.signal(**changes))
                self.assertFalse(result["allowed"])
                self.assertIsNone(result["target1_ratio"])
                json.dumps(result, allow_nan=False)

    def test_extreme_ratio_overflow_unavailable(self):
        signal = self.signal(entry_price=1e-300, stop_loss=5e-301, invalidation_level=6e-301,
            entry_zone_low=5e-301, entry_zone_high=1e-300, target_1=1e300, target_2=1e301)
        result = signal_risk_reward(signal)
        self.assertFalse(result["allowed"])
        json.dumps(result, allow_nan=False)

    def test_tiny_supported_distances_are_not_rounded_to_zero(self):
        signal = self.signal(entry_price=1e-100, stop_loss=5e-101, invalidation_level=6e-101,
            entry_zone_low=5e-101, entry_zone_high=1e-100, target_1=1.5e-100, target_2=2e-100)
        result = signal_risk_reward(signal)
        self.assertTrue(result["allowed"])
        self.assertGreater(result["risk_per_unit"], 0)
        self.assertAlmostEqual(result["target1_ratio"], 1)

    def test_existing_ranking_is_deterministic_and_geometry_based(self):
        low_rr = self.signal(symbol="AAA", target_1=100.4, target_2=100.6)
        high_rr = self.signal(symbol="ZZZ")
        identity_tie = self.signal(symbol="BBB")
        top_quality = self.signal(symbol="CCC", quality_score=80)
        signals = [low_rr, high_rr, identity_tie, top_quality]
        expected = ["CCC", "BBB", "ZZZ", "AAA"]
        self.assertEqual([row.symbol for row in rank_signal_candidates(signals)], expected)
        self.assertEqual([row.symbol for row in rank_signal_candidates(list(reversed(signals)))], expected)
        with self.assertRaises(ValueError):
            rank_signal_candidates([self.signal(target_1=99)])


if __name__ == "__main__":
    unittest.main()
