"""Explicit synthetic rank-change prototype; no live/empirical authority."""
import copy
from datetime import datetime
import unittest

import test_bot
from opportunity_ranking import build_snapshot, current_view, digest


def evaluation(run="r1", watermark="2026-10-16 09:55:00", tcs=90, infy=80):
    rows = []
    for symbol, quality in (("TCS", tcs), ("INFY", infy)):
        rows.append(dict(candidate_id=run+symbol, symbol=symbol, strategy_id="strat_4_orb_filtered",
            position_type="LONG_EQUITY_INTRADAY",
            status="QUALIFIED", ranking=dict(qualified=True), explanation=dict(setup_quality=quality),
            risk_reward=dict(allowed=True, gross_t1_rr=2.0), source_reference=dict(run_id=run,
                provider="upstox", data_mode="SIMULATED", candle_timestamps=[watermark],
                candle_digest=digest([symbol, watermark, quality]), instrument_identity=dict(provider="upstox",
                    symbol=symbol, identifier="SYNTHETIC_"+symbol, exchange="NSE", instrument_type="EQ", is_index=False))))
    return dict(run_id=run, actionable=False, data_mode="SIMULATED", candidate_evaluations=rows)


class TestAstraRanking(unittest.TestCase):
    def build(self, value=None, now="2026-10-16T10:00:05+05:30", previous=None):
        return build_snapshot(value or evaluation(), provider="upstox", as_of=now, previous=previous)

    def test_tcs_infy_rank_reversal_records_actual_factor_and_source_changes(self):
        first = self.build()
        second = self.build(evaluation("r2", "2026-10-16 10:05:00", 85, 95),
                            now="2026-10-16T10:10:05+05:30", previous=first)
        self.assertEqual([row["symbol"] for row in first["rows"]], ["TCS", "INFY"])
        self.assertEqual([row["symbol"] for row in second["rows"]], ["INFY", "TCS"])
        self.assertEqual(second["rows"][0]["previous_rank"], 2)
        self.assertEqual(second["rows"][0]["component_changes"]["rule_quality"], dict(previous=80, current=95))
        self.assertNotEqual(first["rank_version"], second["rank_version"])
        self.assertFalse(second["actionable"])
        self.assertIn("NET_EXECUTABLE_REWARD", second["rows"][0]["missing_components"])

    def test_permutation_ties_and_duplicate_input_keep_deterministic_priority(self):
        source = evaluation(tcs=85, infy=85)
        first = self.build(source)
        permuted = copy.deepcopy(source)
        permuted["candidate_evaluations"].reverse()
        self.assertEqual(first, self.build(permuted))
        duplicate = self.build(source, previous=first)
        self.assertEqual(first["rank_version"], duplicate["rank_version"])
        self.assertTrue(all(row["rank_change_reason"] == "UNCHANGED_PRIORITY" for row in duplicate["rows"]))

    def test_stale_and_forming_rows_never_keep_current_priority(self):
        source = evaluation()
        self.assertEqual(self.build(source, now="2026-10-16T10:02:00+05:30")["rows"], [])
        self.assertEqual(self.build(source, now="2026-10-16T09:59:59+05:30")["rows"], [])
        first = self.build()
        state = current_view(first, "2026-10-16T10:06:01+05:30")
        self.assertEqual(state["current_rows"], [])
        self.assertEqual(len(state["archive"]["rows"]), 2)
        self.assertFalse(state["actionable"])

    def test_rejection_high_score_and_empty_refresh_remove_prior_rank(self):
        first = self.build()
        changed = evaluation("r2", "2026-10-16 10:05:00")
        changed["candidate_evaluations"][0].update(status="REJECTED", explanation=dict(setup_quality=100))
        second = self.build(changed, now="2026-10-16T10:10:05+05:30", previous=first)
        self.assertEqual([row["symbol"] for row in second["rows"]], ["INFY"])
        self.assertEqual(second["removals"][0]["symbol"], "TCS")
        empty = dict(changed, candidate_evaluations=[])
        self.assertEqual(self.build(empty, now="2026-10-16T10:10:05+05:30", previous=first)["rows"], [])

    def test_archived_current_view_expires_at_the_same_boundary_as_rebuild(self):
        snapshot = self.build()
        for now, expected_rows in (("2026-10-16T10:01:00+05:30", 2),
                                   ("2026-10-16T10:01:01+05:30", 0)):
            with self.subTest(now=now):
                view = current_view(snapshot, now)
                rebuilt = self.build(now=now)
                self.assertEqual(len(rebuilt["rows"]), expected_rows)
                self.assertEqual(len(view["current_rows"]), expected_rows)
                self.assertEqual(view["archive"], snapshot)

    def test_out_of_order_or_same_watermark_revision_requires_explicit_new_source(self):
        first = self.build()
        with self.assertRaisesRegex(ValueError, "CHRONOLOGY"):
            self.build(previous=first, now="2026-10-16T10:00:00+05:30")
        with self.assertRaisesRegex(ValueError, "REVISION"):
            self.build(evaluation(tcs=99), previous=first)

    def test_multiple_setups_do_not_double_count_symbol_or_rank_option_premium_as_cash(self):
        source = evaluation()
        other = copy.deepcopy(source["candidate_evaluations"][0])
        other.update(strategy_id="strat_1_order_block", candidate_id="other")
        source["candidate_evaluations"].append(other)
        source["candidate_evaluations"][1]["source_reference"]["instrument_identity"]["instrument_type"] = "OPTION"
        result = self.build(source)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual({row["reason_code"] for row in result["exclusions"]},
            {"REDUNDANT_SYMBOL_SETUP", "CASH_IDENTITY_REQUIRED_CONTRACT_RANKING_SEPARATE"})

    def test_snapshot_tampering_is_rejected_and_reads_do_not_mutate(self):
        snapshot = self.build()
        before = copy.deepcopy(snapshot)
        view = current_view(snapshot, "2026-10-16T10:01:00+05:30")
        view["current_rows"].clear()
        self.assertEqual(snapshot, before)
        snapshot["rows"][0]["rank"] = 200
        with self.assertRaisesRegex(ValueError, "INTEGRITY"):
            current_view(snapshot, "2026-10-16T10:01:00+05:30")

    def test_opposite_direction_is_a_new_opportunity_not_unchanged_priority(self):
        original = evaluation()
        for candidate in original["candidate_evaluations"]:
            candidate["position_type"] = "LONG_EQUITY_INTRADAY"
        first = self.build(original)
        later = evaluation("r2", "2026-10-16 10:05:00")
        for candidate in later["candidate_evaluations"]:
            candidate["position_type"] = "SHORT_EQUITY_INTRADAY" if candidate["symbol"] == "TCS" else "LONG_EQUITY_INTRADAY"
        second = self.build(later, now="2026-10-16T10:10:05+05:30", previous=first)
        self.assertIsNone(second["rows"][0]["previous_rank"])
        self.assertEqual(second["rows"][0]["rank_change_reason"], "NEWLY_QUALIFIED")
        self.assertEqual(second["removals"][0]["symbol"], "TCS")

    def test_multi_strategy_confluence_boosts_composite_score_and_records_confluence_metadata(self):
        source = evaluation(tcs=80, infy=85)
        # Add a second strategy for TCS (strat_1_order_block with quality 75)
        tcs_ob = copy.deepcopy(source["candidate_evaluations"][0])
        tcs_ob.update(candidate_id="r1TCS_ob", strategy_id="strat_1_order_block",
                      explanation=dict(setup_quality=75))
        source["candidate_evaluations"].append(tcs_ob)
        result = self.build(source)

        # Without confluence, INFY (quality 85) would beat TCS (quality 80).
        # With 2 strategies, TCS gets 1.15x multiplier: 80 * 1.15 = 92.0 composite score.
        # INFY has 1 strategy: 85 * 1.0 = 85.0 composite score.
        # Therefore, TCS outranks INFY!
        self.assertEqual([row["symbol"] for row in result["rows"]], ["TCS", "INFY"])
        tcs_row = result["rows"][0]
        self.assertEqual(tcs_row["rank"], 1)
        self.assertEqual(tcs_row["score_components"]["confluence_count"], 2)
        self.assertEqual(tcs_row["score_components"]["confluence_multiplier"], 1.15)
        self.assertEqual(tcs_row["score_components"]["confluence_strategies"],
                         ["strat_1_order_block", "strat_4_orb_filtered"])
        self.assertEqual(tcs_row["score_components"]["composite_score"], 92.0)
        self.assertEqual(tcs_row["score_components"]["rule_quality"], 80)
        self.assertEqual(tcs_row["component_versions"]["confluence"], "MULTI_STRATEGY_CONFLUENCE_V1")

        # The runner-up setup for TCS was excluded as redundant symbol setup
        redundants = [x for x in result["exclusions"] if x["reason_code"] == "REDUNDANT_SYMBOL_SETUP"]
        self.assertEqual(len(redundants), 1)
        self.assertEqual(redundants[0]["candidate_id"], "r1TCS_ob")

    def test_multi_strategy_confluence_caps_composite_score_at_100(self):
        source = evaluation(tcs=95, infy=70)
        tcs_ob = copy.deepcopy(source["candidate_evaluations"][0])
        tcs_ob.update(candidate_id="r1TCS_ob", strategy_id="strat_1_order_block",
                      explanation=dict(setup_quality=95))
        source["candidate_evaluations"].append(tcs_ob)
        result = self.build(source)
        # 95 * 1.15 = 109.25, capped at 100.0
        self.assertEqual(result["rows"][0]["score_components"]["composite_score"], 100.0)

    def test_opposing_directions_on_same_symbol_do_not_conflate(self):
        source = evaluation(tcs=80, infy=70)
        tcs_short = copy.deepcopy(source["candidate_evaluations"][0])
        tcs_short.update(candidate_id="r1TCS_short", strategy_id="strat_1_order_block",
                         position_type="SHORT_EQUITY_INTRADAY", explanation=dict(setup_quality=75))
        source["candidate_evaluations"].append(tcs_short)
        result = self.build(source)
        # LONG TCS has 1 strategy, SHORT TCS has 1 strategy -> confluence_count is 1 for both
        tcs_row = result["rows"][0]
        self.assertEqual(tcs_row["symbol"], "TCS")
        self.assertEqual(tcs_row["score_components"]["confluence_count"], 1)
        self.assertEqual(tcs_row["score_components"]["confluence_multiplier"], 1.0)
        self.assertEqual(tcs_row["score_components"]["composite_score"], 80.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

