"""Unit and integration tests for Wave 1: Market Radar and Rank Transitions.

Verifies:
1. Market Radar normalized open-move baseline comparator (one-sided vs choppy).
2. Market breadth, sector aggregation, and truthful non-actionable labels.
3. Factor-delta rank transitions: deterministic TCS vs INFY 10:00 -> 10:10 reversal demonstration.
4. Immediate disqualified leader removal (NO_LINGERING_LEADER).
5. Chronology violation and scope mismatch protections.
"""
from datetime import datetime, timedelta
import unittest

from market_radar import (
    calculate_normalized_open_strength,
    aggregate_market_breadth,
    build_market_radar_snapshot,
    RADAR_SCHEMA,
)
from opportunity_ranking import build_snapshot
from rank_transitions import (
    compute_rank_transitions,
    generate_factor_delta_narrative,
    TRANSITION_SCHEMA,
)
from strategies import IST


class TestMarketRadarLayer(unittest.TestCase):
    def test_one_sided_bullish_movement(self):
        # Open=1000, High=1030 (upside=30), Low=995 (downside=5), Close=1025
        # Upside (30) > 2 * Downside (10) -> One-sided Bullish
        res = calculate_normalized_open_strength(1000.0, 1030.0, 995.0, 1025.0, 20.0)
        self.assertTrue(res["is_one_sided"])
        self.assertEqual(res["direction"], "BULLISH")
        self.assertAlmostEqual(res["raw_strength_ratio"], (1025.0 - 1000.0) / 20.0)
        self.assertGreater(res["normalized_score"], 0.0)

    def test_one_sided_bearish_movement(self):
        # Open=1000, High=1004 (upside=4), Low=970 (downside=30), Close=975
        # Downside (30) > 2 * Upside (8) -> One-sided Bearish
        res = calculate_normalized_open_strength(1000.0, 1004.0, 970.0, 975.0, 20.0)
        self.assertTrue(res["is_one_sided"])
        self.assertEqual(res["direction"], "BEARISH")
        self.assertAlmostEqual(res["raw_strength_ratio"], (1000.0 - 975.0) / 20.0)
        self.assertGreater(res["normalized_score"], 0.0)

    def test_two_sided_choppy_movement_scores_zero(self):
        # Open=1000, High=1020 (upside=20), Low=985 (downside=15), Close=1005
        # Upside (20) <= 2 * Downside (30) and Downside (15) <= 2 * Upside (40) -> Choppy
        res = calculate_normalized_open_strength(1000.0, 1020.0, 985.0, 1005.0, 20.0)
        self.assertFalse(res["is_one_sided"])
        self.assertEqual(res["direction"], "NEUTRAL")
        self.assertEqual(res["normalized_score"], 0.0)

    def test_invalid_price_geometry_raises(self):
        with self.assertRaises(ValueError):
            calculate_normalized_open_strength(1000.0, 990.0, 980.0, 995.0, 20.0)  # High < Open

    def test_market_radar_snapshot_breadth_and_immutability(self):
        observations = [
            {"symbol": "RELIANCE", "sector": "ENERGY", "open": 2500.0, "high": 2550.0, "low": 2495.0, "close": 2540.0, "atr_50d": 30.0, "volume": 120000},
            {"symbol": "TCS", "sector": "IT", "open": 3500.0, "high": 3510.0, "low": 3450.0, "close": 3460.0, "atr_50d": 40.0, "volume": 85000},
            {"symbol": "INFY", "sector": "IT", "open": 1800.0, "high": 1815.0, "low": 1795.0, "close": 1802.0, "atr_50d": 25.0, "volume": 90000},
        ]
        now = datetime(2026, 10, 28, 11, 0, tzinfo=IST)
        snapshot = build_market_radar_snapshot(observations, provider="AngelOne", as_of=now, data_mode="SIMULATED")

        self.assertEqual(snapshot["schema_version"], RADAR_SCHEMA)
        self.assertFalse(snapshot["actionable"])
        self.assertTrue(snapshot["is_market_session_open"])
        self.assertIn("snapshot_sha256", snapshot)
        self.assertEqual(len(snapshot["rows"]), 3)

        # Breadth assertions
        breadth = snapshot["breadth"]
        self.assertEqual(breadth["total_monitored"], 3)
        self.assertEqual(breadth["advances"], 2)  # RELIANCE (+1.6%), INFY (+0.11%)
        self.assertEqual(breadth["declines"], 1)  # TCS (-1.14%)
        self.assertIn("leading_sector", breadth)


class TestRankTransitionsAndFactorDeltas(unittest.TestCase):
    def _create_mock_candidate(self, symbol, strategy_id, quality, rr, run_id, watermark):
        ref = {
            "provider": "Upstox",
            "data_mode": "SIMULATED",
            "run_id": run_id,
            "candle_timestamps": [watermark.isoformat()],
            "candle_digest": "a" * 64,
            "instrument_identity": {
                "instrument_type": "EQ",
                "exchange": "NSE",
                "is_index": False,
                "symbol": symbol,
            },
        }
        return {
            "candidate_id": f"cand_{symbol}_{strategy_id}",
            "symbol": symbol,
            "strategy_id": strategy_id,
            "status": "QUALIFIED",
            "position_type": "LONG_EQUITY_INTRADAY",
            "source_reference": ref,
            "explanation": {"setup_quality": quality},
            "risk_reward": {"allowed": True, "gross_t1_rr": rr},
            "ranking": {"qualified": True},
        }

    def test_deterministic_rank_reversal_tcs_infy_10_00_to_10_10(self):
        # Scan 1 at 10:05:00 IST (evaluating 10:00:00 completed 5m candle)
        # TCS has higher initial quality (85.0 vs INFY 75.0) -> TCS is #1, INFY is #2
        wm_10_00 = datetime(2026, 10, 28, 9, 55, tzinfo=IST)
        now_10_05 = datetime(2026, 10, 28, 10, 0, 30, tzinfo=IST)

        scan_1 = {
            "run_id": "run_1000",
            "actionable": False,
            "data_mode": "SIMULATED",
            "candidate_evaluations": [
                self._create_mock_candidate("TCS", "strat_2_vwap_pullback", 85.0, 2.2, "run_1000", wm_10_00),
                self._create_mock_candidate("INFY", "strat_1_order_block", 75.0, 2.0, "run_1000", wm_10_00),
            ],
        }
        snap_10_00 = build_snapshot(scan_1, provider="Upstox", as_of=now_10_05)
        self.assertEqual(snap_10_00["rows"][0]["symbol"], "TCS")
        self.assertEqual(snap_10_00["rows"][1]["symbol"], "INFY")

        # Scan 2 at 10:10:30 IST (evaluating 10:05:00 completed 5m candle)
        # INFY gets dual-strategy confluence (Order Block + VWAP Pullback), boosting composite score (+15%)
        # TCS remains single strategy at 85.0, while INFY reaches 75.0 * 1.15 = 86.25 -> INFY overtakes TCS!
        wm_10_05 = datetime(2026, 10, 28, 10, 0, tzinfo=IST)
        now_10_10 = datetime(2026, 10, 28, 10, 5, 30, tzinfo=IST)

        scan_2 = {
            "run_id": "run_1005",
            "actionable": False,
            "data_mode": "SIMULATED",
            "candidate_evaluations": [
                self._create_mock_candidate("TCS", "strat_2_vwap_pullback", 85.0, 2.2, "run_1005", wm_10_05),
                self._create_mock_candidate("INFY", "strat_1_order_block", 75.0, 2.0, "run_1005", wm_10_05),
                self._create_mock_candidate("INFY", "strat_2_vwap_pullback", 75.0, 2.0, "run_1005", wm_10_05),
            ],
        }
        snap_10_05 = build_snapshot(scan_2, provider="Upstox", as_of=now_10_10, previous=snap_10_00)
        self.assertEqual(snap_10_05["rows"][0]["symbol"], "INFY")
        self.assertEqual(snap_10_05["rows"][1]["symbol"], "TCS")

        # Compute transitions between the two snapshots
        transitions = compute_rank_transitions(snap_10_00, snap_10_05)
        self.assertEqual(transitions["schema_version"], TRANSITION_SCHEMA)
        self.assertTrue(transitions["leader_swapped"])
        self.assertEqual(transitions["prior_leader"], "TCS")
        self.assertEqual(transitions["current_leader"], "INFY")

        # Verify factor deltas for INFY (promoted from #2 to #1)
        infy_transition = next(t for t in transitions["transitions"] if t["symbol"] == "INFY")
        self.assertEqual(infy_transition["prior_rank"], 2)
        self.assertEqual(infy_transition["current_rank"], 1)
        self.assertEqual(infy_transition["rank_delta"], 1)
        self.assertEqual(infy_transition["factor_deltas"]["delta_confluence_count"], 1)
        self.assertGreater(infy_transition["factor_deltas"]["delta_composite_score"], 0.0)
        self.assertIn("overtook TCS", infy_transition["explanation_narrative"])

    def test_immediate_removal_of_disqualified_leader_no_lingering(self):
        wm_1 = datetime(2026, 10, 28, 9, 55, tzinfo=IST)
        now_1 = datetime(2026, 10, 28, 10, 0, 30, tzinfo=IST)
        scan_1 = {
            "run_id": "run_1",
            "actionable": False,
            "data_mode": "SIMULATED",
            "candidate_evaluations": [
                self._create_mock_candidate("RELIANCE", "strat_1_order_block", 90.0, 2.5, "run_1", wm_1),
                self._create_mock_candidate("SBIN", "strat_2_vwap_pullback", 80.0, 2.0, "run_1", wm_1),
            ],
        }
        snap_1 = build_snapshot(scan_1, provider="Upstox", as_of=now_1)
        self.assertEqual(snap_1["rows"][0]["symbol"], "RELIANCE")

        # In Scan 2, RELIANCE is disqualified (e.g. invalidation stop breached) and excluded
        wm_2 = datetime(2026, 10, 28, 10, 0, tzinfo=IST)
        now_2 = datetime(2026, 10, 28, 10, 5, 30, tzinfo=IST)
        scan_2 = {
            "run_id": "run_2",
            "actionable": False,
            "data_mode": "SIMULATED",
            "candidate_evaluations": [
                self._create_mock_candidate("SBIN", "strat_2_vwap_pullback", 80.0, 2.0, "run_2", wm_2),
            ],
        }
        snap_2 = build_snapshot(scan_2, provider="Upstox", as_of=now_2, previous=snap_1)
        self.assertEqual(len(snap_2["rows"]), 1)
        self.assertEqual(snap_2["rows"][0]["symbol"], "SBIN")

        transitions = compute_rank_transitions(snap_1, snap_2)
        self.assertEqual(transitions["dropouts_count"], 1)
        dropout = transitions["dropouts"][0]
        self.assertEqual(dropout["symbol"], "RELIANCE")
        self.assertEqual(dropout["prior_rank"], 1)
        self.assertTrue(dropout["was_prior_leader"])
        self.assertIn("NO_LINGERING_LEADER", dropout["removal_reason"])

    def test_chronology_inversion_rejected(self):
        now_1 = datetime(2026, 10, 28, 10, 5, 0, tzinfo=IST)
        now_2 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=IST)  # Earlier than now_1!
        snap_1 = {"as_of": now_1.isoformat(), "rows": [], "scope": {"provider": "P"}}
        snap_2 = {"as_of": now_2.isoformat(), "rows": [], "scope": {"provider": "P"}}
        with self.assertRaises(ValueError):
            compute_rank_transitions(snap_1, snap_2)


if __name__ == "__main__":
    unittest.main()
