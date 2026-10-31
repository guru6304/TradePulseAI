"""OFFLINE SIMULATION: native ST prices through the unchanged real scanner.

Only read-only Angel HTTP transport is mocked, into temporary fixture SQLite.
Synthetic wire rows retain LIVE adapter validation semantics; they establish
software behavior only, never real market data, source acceptance or returns.
No evaluation PASS records or indicator/trend outputs are fabricated.
"""
import copy
import json
import os
import sys
import unittest
from collections import Counter
from datetime import timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from brokers import SimulatedNSEAdapter
from paper_portfolio import PaperAccountConfig
from strategies import parse_ist_timestamp
from test_astra_paper_triggers import ORBScannerFixture
from supertrend_paper_triggers import build_contract, evaluate_observation


class SupertrendScannerFixture(ORBScannerFixture):
    """Native generator prices relocated onto actual prior weekday sessions.

    Preserve all native prices and their order. The chosen current completed
    signal starts at 10:00 or 14:00, with current history beginning at 09:15.
    Earlier prices occupy at most 75 bars per prior weekday (09:15..15:25);
    only the earliest retained warm-up session may be a partial trailing day.
    """
    def __init__(self, owner, side="LONG", hour=14, minute=0):
        super().__init__(owner, side)
        decision = self.now.replace(hour=hour, minute=minute, second=0)
        self.scenario.now = decision+timedelta(minutes=5, seconds=5)
        pattern = "supertrend_pullback_bull" if side == "LONG" else "supertrend_pullback_bear"
        rows = SimulatedNSEAdapter(seed=42, clock=lambda: self.now).get_intraday_candles(
            {"symbol": "RELIANCE"}, interval_min=5, pattern=pattern)
        opening = decision.replace(hour=9, minute=15)
        current_count = int((decision-opening).total_seconds()//300)+1
        needed = len(rows)-current_count
        prior = []
        day = decision-timedelta(days=1)
        while len(prior) < needed:
            if day.weekday() < 5:
                start = day.replace(hour=9, minute=15)
                prior[0:0] = [start+timedelta(minutes=5*n) for n in range(75)]
            day -= timedelta(days=1)
        stamps = prior[-needed:]+[opening+timedelta(minutes=5*n) for n in range(current_count)]
        self.bars[:] = [dict(row, timestamp=stamp.isoformat()) for row, stamp in zip(rows, stamps)]

    @staticmethod
    def candidate(summary):
        matches = [s for s in summary["signals"] if s["strategy_id"] == "strat_5_supertrend_pullback"]
        if len(matches) != 1:
            raise AssertionError("Expected one actual Supertrend scanner candidate: "+str(summary.get("signals")))
        return copy.deepcopy(matches[0])


class TestTrackASupertrendTriggers(unittest.TestCase):
    def ready(self, side="LONG", hour=14, minute=0, **settings):
        fixture = SupertrendScannerFixture(self, side, hour, minute)
        first = fixture.scan()
        candidate = fixture.candidate(first)
        values = dict(account_id="st-evidence", run_id="offline", provider="angelone", source_data_mode="LIVE")
        values.update(settings)
        config = PaperAccountConfig(**values)
        with fixture.store.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            contract = build_contract(fixture.store, conn, first["run_id"], candidate, config, fixture.now)
            self.assertEqual(tuple(conn.iterdump()), before)
        return fixture, contract

    def later(self, fixture, contract, **overrides):
        entry = contract["candidate"]["entry_price"]
        if fixture.side == "LONG":
            values = dict(open=entry, close=entry+.05, low=contract["invalidation"]+.01, high=entry+.10)
        else:
            values = dict(open=entry, close=entry-.05, high=contract["invalidation"]-.01, low=entry-.10)
        values["volume"] = 2*sum(b["volume"] for b in fixture.bars[-20:])/20
        values.update(overrides)
        fixture.append_bar(**values)
        return fixture.scan()

    def evaluate(self, fixture, contract, summary, history=(), now=None):
        with fixture.store.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            try:
                return evaluate_observation(fixture.store, conn, contract, summary["run_id"], now or fixture.now, history)
            finally:
                self.assertEqual(tuple(conn.iterdump()), before)

    @staticmethod
    def close_fixture(fixture):
        fixture.scenario.tearDown()
        fixture.scenario.doCleanups()

    def test_native_long_short_at_both_windows_freeze_original_bracket_and_have_no_effects(self):
        for side in ("LONG", "SHORT"):
            for hour in (10, 14):
                with self.subTest(side=side, hour=hour):
                    fixture, contract = self.ready(side, hour=hour)
                    stamps = [parse_ist_timestamp(b["timestamp"]) for b in fixture.bars]
                    self.assertGreaterEqual(len(stamps), 200)
                    self.assertGreater(len({s.date() for s in stamps}), 1)
                    self.assertTrue(all(count <= 75 for count in Counter(s.date() for s in stamps).values()))
                    self.assertTrue(all(s.weekday() < 5 and "09:15" <= s.strftime("%H:%M") <= "15:25" for s in stamps))
                    self.assertEqual(next(s for s in stamps if s.date() == fixture.now.date()).strftime("%H:%M"), "09:15")
                    self.assertEqual(contract, json.loads(json.dumps(contract)))
                    self.assertFalse(contract["accepted_fill_policy"])
                    self.assertEqual(contract["original_measurements"]["supertrend10_3"], contract["invalidation"])
                    frozen = copy.deepcopy(contract)
                    record = self.evaluate(fixture, contract, self.later(fixture, contract))
                    self.assertEqual(record["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")
                    self.assertTrue(all(record["measurements"]["checks"].values()))
                    self.assertFalse(record["actionable"])
                    self.assertFalse(record["financial_mutations"])
                    self.assertFalse(record["accepted_fill_policy"])
                    self.assertEqual(contract, frozen)
                    self.assertNotEqual(record["timestamp_ist"], contract["decision_timestamp_ist"])
                    self.assertIsNone(fixture.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
                    self.close_fixture(fixture)

    def test_directional_close_and_prior_twenty_volume_must_repeat(self):
        for side in ("LONG", "SHORT"):
            for failed in ("volume", "directional_close"):
                with self.subTest(side=side, failed=failed):
                    fixture, contract = self.ready(side)
                    values = {"volume": 1} if failed == "volume" else {"open": contract["candidate"]["entry_price"]+(.10 if side == "LONG" else -.10)}
                    record = self.evaluate(fixture, contract, self.later(fixture, contract, **values))
                    self.assertEqual(record["status"], "WAITING")
                    self.assertFalse(record["measurements"]["checks"][failed])
                    self.assertIsNone(record["trigger_timestamp_ist"])
                    self.close_fixture(fixture)

    def test_volume_threshold_is_inclusive_and_uses_previous_twenty_only(self):
        for side in ("LONG", "SHORT"):
            for below in (False, True):
                with self.subTest(side=side, below=below):
                    fixture, contract = self.ready(side)
                    baseline = sum(b["volume"] for b in fixture.bars[-20:])/20
                    record = self.evaluate(fixture, contract, self.later(fixture, contract, volume=1.3*baseline-int(below)))
                    self.assertEqual(record["measurements"]["baseline_volume"], baseline)
                    self.assertEqual(record["measurements"]["checks"]["volume"], not below)
                    self.assertEqual(record["status"], "WAITING" if below else "QUALIFIED_EXPERIMENTAL_TRIGGER")
                    self.close_fixture(fixture)

    def test_a_later_directional_bar_without_either_pullback_touch_waits(self):
        for side in ("LONG", "SHORT"):
            fixture, contract = self.ready(side)
            entry = contract["candidate"]["entry_price"]
            values = {"low": entry-.01} if side == "LONG" else {"high": entry+.01}
            record = self.evaluate(fixture, contract, self.later(fixture, contract, **values))
            self.assertTrue(record["measurements"]["checks"]["directional_close"])
            self.assertTrue(record["measurements"]["checks"]["volume"])
            self.assertFalse(record["measurements"]["checks"]["touch"])
            self.assertEqual(record["status"], "WAITING")
            self.close_fixture(fixture)

    def test_completed_199_bar_history_and_missing_open_cannot_create_st_candidate(self):
        for mode in ("warmup", "missing_open"):
            fixture = SupertrendScannerFixture(self)
            if mode == "warmup":
                fixture.bars[:] = fixture.bars[-199:]
            else:
                opening = fixture.now.replace(hour=9, minute=15, second=0).isoformat()
                fixture.bars[:] = [b for b in fixture.bars if b["timestamp"] != opening]
            summary = fixture.scan()
            self.assertFalse(any(s["strategy_id"] == "strat_5_supertrend_pullback" for s in summary["signals"]))
            checks = [c for e in summary.get("strategy_evaluations", []) if e["strategy_id"] == "strat_5_supertrend_pullback"
                      for c in e.get("rule_checks", [])]
            wanted = "data.warmup" if mode == "warmup" else "session.vwap_start"
            self.assertTrue(any(c["rule_id"] == wanted and c["status"] == "UNAVAILABLE" for c in checks))
            self.close_fixture(fixture)

    def test_excluded_window_has_no_detector_candidate_and_later_bar_waits(self):
        for hour, minute in ((9, 40), (11, 30), (13, 30)):
            fixture = SupertrendScannerFixture(self, hour=hour, minute=minute)
            summary = fixture.scan()
            self.assertFalse(any(s["strategy_id"] == "strat_5_supertrend_pullback" for s in summary["signals"]))
            traces = [e for e in summary.get("strategy_evaluations", []) if e["strategy_id"] == "strat_5_supertrend_pullback"]
            self.assertTrue(any(any(c["rule_id"] == "session.strategy_window" and c["status"] == "FAIL"
                                    for c in e.get("rule_checks", [])) for e in traces))
            self.close_fixture(fixture)
        fixture, contract = self.ready(hour=11, minute=25)
        record = self.evaluate(fixture, contract, self.later(fixture, contract))
        self.assertEqual(record["status"], "WAITING")
        self.assertFalse(record["measurements"]["checks"]["strategy_window"])

    def test_four_fresh_waits_do_not_expire_or_trail_original_invalidation(self):
        fixture, contract = self.ready()
        history = []
        frozen = (contract["invalidation"], contract["stop_loss"], contract["target_1"], contract["target_2"])
        for _ in range(4):
            record = self.evaluate(fixture, contract, self.later(fixture, contract, volume=1), history)
            self.assertEqual(record["status"], "WAITING")
            history.append(record)
        record = self.evaluate(fixture, contract, self.later(fixture, contract), history)
        self.assertEqual(record["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")
        self.assertEqual((contract["invalidation"], contract["stop_loss"], contract["target_1"], contract["target_2"]), frozen)

    def test_frozen_invalidation_and_t1_collision_are_terminal_before_trigger(self):
        for side in ("LONG", "SHORT"):
            for collision in (False, True):
                fixture, contract = self.ready(side)
                values = {"low" if side == "LONG" else "high": contract["invalidation"]}
                if collision:
                    values["high" if side == "LONG" else "low"] = contract["target_1"]
                record = self.evaluate(fixture, contract, self.later(fixture, contract, **values))
                self.assertEqual(record["status"], "INVALIDATED")
                self.assertIsNone(record["trigger_timestamp_ist"])
                with self.assertRaisesRegex(ValueError, "HISTORY_AFTER_TERMINAL"):
                    self.evaluate(fixture, contract, self.later(fixture, contract), [record])
                self.close_fixture(fixture)

    def test_target_only_and_square_off_are_terminal_without_trigger(self):
        for side in ("LONG", "SHORT"):
            for mode in ("target", "square_off"):
                fixture, contract = self.ready(side, **({"square_off_ist": "14:10"} if mode == "square_off" else {}))
                values = {"high" if side == "LONG" else "low": contract["target_1"]} if mode == "target" else {}
                record = self.evaluate(fixture, contract, self.later(fixture, contract, **values))
                self.assertEqual(record["status"], "TARGET_ALREADY_REACHED" if mode == "target" else "EXPIRED")
                self.assertIsNone(record["trigger_timestamp_ist"])
                self.close_fixture(fixture)

    def test_original_run_duplicate_stale_future_forming_and_skipped_observations_reject(self):
        fixture, contract = self.ready()
        with self.assertRaisesRegex(ValueError, "DISTINCT_FUTURE_RUN"):
            self.evaluate(fixture, contract, {"run_id": contract["original_run_id"]})
        later = self.later(fixture, contract, volume=1)
        record = self.evaluate(fixture, contract, later)
        with self.assertRaisesRegex(ValueError, "OBSERVATION_GAP_OR_ORDER"):
            self.evaluate(fixture, contract, later, [record])
        for clock in (fixture.now+timedelta(seconds=61), fixture.now-timedelta(seconds=6)):
            with self.assertRaisesRegex(ValueError, "OBSERVATION_TIME_INVALID"):
                self.evaluate(fixture, contract, later, now=clock)
        fixture.scenario.now -= timedelta(minutes=1)
        forming = fixture.scan()
        with self.assertRaises(ValueError):
            self.evaluate(fixture, contract, forming)
        fixture.scenario.now += timedelta(minutes=1)
        with self.assertRaisesRegex(ValueError, "OBSERVATION_GAP_OR_ORDER"):
            self.evaluate(fixture, contract, self.later(fixture, contract))

    def test_unfinished_extreme_wire_tail_cannot_repaint_latest_completed_evidence(self):
        fixture, contract = self.ready()
        later = self.later(fixture, contract, volume=1)
        expected = self.evaluate(fixture, contract, later)
        fixture.bars.append(dict(timestamp=fixture.now.replace(second=0).isoformat(),
            open=1, low=.01, high=99999, close=99998, volume=99999999))
        with_tail = fixture.scan()
        actual = self.evaluate(fixture, contract, with_tail)
        self.assertEqual(actual["timestamp_ist"], expected["timestamp_ist"])
        self.assertEqual(actual["measurements"], expected["measurements"])
        self.assertEqual(actual["status"], "WAITING")

    def test_store_rejects_original_and_prior_source_corrections_before_evaluation(self):
        from storage import PersistenceValidationError
        for original in (True, False):
            fixture, contract = self.ready()
            history = []
            if not original:
                history.append(self.evaluate(fixture, contract, self.later(fixture, contract, volume=1)))
            retained_ids = [contract["original_run_id"]] + [r["source_reference"]["run_id"] for r in history]
            before = [fixture.store.load_cash_scan(run_id) for run_id in retained_ids]
            # The real store rejects a changed earlier observation before a
            # contradictory future snapshot can reach the evidence evaluator.
            fixture.bars[0 if original else -1]["volume"] += 1
            with self.assertRaisesRegex(PersistenceValidationError, "LINEAGE_CANDLE_CORRECTION_CONFLICT"):
                self.later(fixture, contract)
            self.assertEqual([fixture.store.load_cash_scan(run_id) for run_id in retained_ids], before)
            self.close_fixture(fixture)

    def test_contract_source_measurement_and_account_scope_forgery_reject(self):
        fixture, contract = self.ready()
        waiting = self.evaluate(fixture, contract, self.later(fixture, contract, volume=1))
        later = self.later(fixture, contract)
        for field in ("invalidation", "stop_loss", "target_1", "detector_version", "evaluation_digest", "original_history_digest"):
            bad = copy.deepcopy(contract)
            bad[field] = "forged"
            with self.assertRaisesRegex(ValueError, "CONTRACT_INTEGRITY"):
                self.evaluate(fixture, bad, later, [waiting])
        bad = copy.deepcopy(contract)
        bad["source_reference"]["run_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "CONTRACT_INTEGRITY"):
            self.evaluate(fixture, bad, later, [waiting])
        for field in ("account_id", "run_id", "provider"):
            bad = copy.deepcopy(contract)
            bad["config"][field] = "upstox" if field == "provider" else "other-scope"
            with self.assertRaises(ValueError):
                self.evaluate(fixture, bad, later, [waiting])
        bad_record = copy.deepcopy(waiting)
        bad_record["measurements"]["supertrend10_3"] = 1
        with self.assertRaisesRegex(ValueError, "HISTORY_INTEGRITY"):
            self.evaluate(fixture, contract, later, [bad_record])
        with self.assertRaises(ValueError):
            self.evaluate(fixture, contract, {"run_id": "absent-committed-source"})

    def test_restart_json_contract_and_history_rebuild_without_any_database_write(self):
        from storage import SQLitePersistenceStore
        fixture, contract = self.ready()
        waiting = self.evaluate(fixture, contract, self.later(fixture, contract, volume=1))
        later = self.later(fixture, contract)
        expected = self.evaluate(fixture, contract, later, [waiting])
        store = SQLitePersistenceStore(fixture.store.database_url)
        self.addCleanup(store.close)
        with store.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            actual = evaluate_observation(store, conn, json.loads(json.dumps(contract)), later["run_id"], fixture.now,
                                          json.loads(json.dumps([waiting])))
            self.assertEqual(actual, expected)
            self.assertEqual(tuple(conn.iterdump()), before)

    def test_bounded_history_and_no_accepted_policy_or_default_activation(self):
        for history in ([{}]*75, "forged", {"forged": True}):
            with self.assertRaisesRegex(ValueError, "HISTORY_INVALID"):
                evaluate_observation(None, None, {}, "none", "none", history)
        with self.assertRaises(ValueError):
            PaperAccountConfig(account_id="fixture", run_id="offline", provider="angelone", source_data_mode="LIVE",
                               fill_policy="SUPERTREND_REPEATED_PULLBACK_CLOSE_V1")
        config = PaperAccountConfig(account_id="fixture", run_id="offline", provider="angelone", source_data_mode="LIVE")
        self.assertEqual(config.fill_policy, "OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1")
