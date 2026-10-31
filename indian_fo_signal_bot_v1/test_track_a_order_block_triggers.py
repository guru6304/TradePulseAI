"""Authored native-pattern scanner inputs; evidence-only OB contract acceptance."""
import copy
import json
import os
import sys
import unittest
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
from order_block_paper_triggers import build_contract, evaluate_observation


class OrderBlockScannerFixture(ORBScannerFixture):
    def __init__(self, owner, side="LONG"):
        super().__init__(owner, side)
        self.scenario.now = self.now.replace(hour=14, minute=15, second=5)
        pattern = "order_block_bull" if side == "LONG" else "order_block_bear"
        rows = SimulatedNSEAdapter(seed=42, clock=lambda: self.now).get_intraday_candles(
            {"symbol": "RELIANCE"}, interval_min=5, pattern=pattern)[-60:]
        opening = self.now.replace(hour=9, minute=15, second=0)
        self.bars[:] = [dict(row, timestamp=(opening+timedelta(minutes=5*n)).isoformat())
                        for n, row in enumerate(rows)]

    @staticmethod
    def candidate(summary):
        matches = [s for s in summary["signals"] if s["strategy_id"] == "strat_1_order_block"]
        if len(matches) != 1:
            raise AssertionError("Expected one actual OB scanner candidate")
        return copy.deepcopy(matches[0])


class TestTrackAOrderBlockTriggers(unittest.TestCase):
    def ready(self, side="LONG", **settings):
        fixture = OrderBlockScannerFixture(self, side)
        first = fixture.scan()
        candidate = fixture.candidate(first)
        values = dict(account_id="ob-evidence", run_id="offline", provider="angelone", source_data_mode="LIVE")
        values.update(settings)
        config = PaperAccountConfig(**values)
        with fixture.store.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            contract = build_contract(fixture.store, conn, first["run_id"], candidate, config, fixture.now)
            self.assertEqual(tuple(conn.iterdump()), before)
        return fixture, contract

    def later(self, fixture, contract, crossed=True, **overrides):
        entry, threshold = contract["candidate"]["entry_price"], contract["threshold"]
        if fixture.side == "LONG":
            close = threshold+.02 if crossed else entry
            values = dict(open=entry, close=close, low=entry-.01, high=max(close,threshold)+.01, volume=100000)
        else:
            close = threshold-.02 if crossed else entry
            values = dict(open=entry, close=close, high=entry+.01, low=min(close,threshold)-.01, volume=100000)
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

    def close(self, fixture):
        fixture.scenario.tearDown()
        fixture.scenario.doCleanups()

    def test_native_long_short_contract_and_later_followthrough_are_evidence_only(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                fixture, contract = self.ready(side)
                self.assertEqual(contract, json.loads(json.dumps(contract)))
                self.assertFalse(contract["accepted_fill_policy"])
                self.assertEqual(contract["selected_structure"]["zone_low"], contract["candidate"]["entry_zone_low"])
                source = copy.deepcopy(contract["selected_structure"])
                result = self.evaluate(fixture, contract, self.later(fixture, contract))
                self.assertEqual(result["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")
                self.assertFalse(result["actionable"])
                self.assertFalse(result["financial_mutations"])
                self.assertEqual(contract["selected_structure"], source)
                self.assertNotEqual(result["timestamp_ist"], contract["decision_timestamp_ist"])
                self.close(fixture)

    def test_wick_and_equal_close_do_not_authorize_followthrough(self):
        for side in ("LONG", "SHORT"):
            fixture, contract = self.ready(side)
            result = self.evaluate(fixture, contract, self.later(fixture, contract, close=contract["threshold"]))
            self.assertEqual(result["status"], "WAITING")
            self.assertFalse(result["measurements"]["strict_close_cross"])
            self.close(fixture)

    def test_four_waits_have_no_arbitrary_ttl_and_do_not_reselect_consumed_zone(self):
        fixture, contract = self.ready()
        history = []
        for _ in range(4):
            later = self.later(fixture, contract, crossed=False)
            self.assertFalse(any(s["strategy_id"] == "strat_1_order_block" and
                s["entry_zone_low"] == contract["selected_structure"]["zone_low"] for s in later["signals"]))
            record = self.evaluate(fixture, contract, later, history)
            self.assertEqual(record["status"], "WAITING")
            history.append(record)
        result = self.evaluate(fixture, contract, self.later(fixture, contract), history)
        self.assertEqual(result["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")

    def test_original_wick_invalidation_and_target_collision_are_terminal(self):
        for side in ("LONG", "SHORT"):
            for collision in (False, True):
                fixture, contract = self.ready(side)
                values = {"low" if side == "LONG" else "high": contract["invalidation"]}
                if collision:
                    values["high" if side == "LONG" else "low"] = contract["target_1"]
                result = self.evaluate(fixture, contract, self.later(fixture, contract, **values))
                self.assertEqual(result["status"], "INVALIDATED")
                self.assertIsNone(result["trigger_timestamp_ist"])
                with self.assertRaisesRegex(ValueError, "HISTORY_AFTER_TERMINAL"):
                    self.evaluate(fixture, contract, self.later(fixture, contract), [result])
                self.close(fixture)

    def test_target_only_and_square_off_expire_without_entry(self):
        for mode in ("target", "square_off"):
            fixture, contract = self.ready(**({"square_off_ist": "14:20"} if mode == "square_off" else {}))
            values = {"high": contract["target_1"]} if mode == "target" else {}
            record = self.evaluate(fixture, contract, self.later(fixture, contract, **values))
            self.assertEqual(record["status"], "TARGET_ALREADY_REACHED" if mode == "target" else "EXPIRED")
            self.close(fixture)

    def test_original_same_run_stale_forming_and_skipped_observations_reject(self):
        fixture, contract = self.ready()
        with self.assertRaisesRegex(ValueError, "DISTINCT_FUTURE_RUN"):
            self.evaluate(fixture, contract, {"run_id": contract["original_run_id"]})
        later = self.later(fixture, contract)
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

    def test_contract_origin_mitigation_scope_and_measurement_tampering_reject(self):
        fixture, contract = self.ready()
        waiting = self.evaluate(fixture, contract, self.later(fixture, contract, crossed=False))
        later = self.later(fixture, contract)
        for field in ("zone_key", "threshold", "evaluation_digest", "original_history_digest", "mitigation_semantics"):
            bad = copy.deepcopy(contract)
            bad[field] = "forged"
            with self.assertRaises(ValueError):
                self.evaluate(fixture, bad, later, [waiting])
        for field in ("account_id", "run_id", "provider"):
            bad = copy.deepcopy(contract)
            bad["config"][field] = "upstox" if field == "provider" else "other"
            with self.assertRaises(ValueError):
                self.evaluate(fixture, bad, later, [waiting])
        bad = copy.deepcopy(contract)
        bad["selected_structure"]["origin"]["close"] = 1
        with self.assertRaisesRegex(ValueError, "CONTRACT_INTEGRITY"):
            self.evaluate(fixture, bad, later, [waiting])
        bad_record = copy.deepcopy(waiting)
        bad_record["measurements"]["threshold"] = 1
        with self.assertRaisesRegex(ValueError, "HISTORY_INTEGRITY"):
            self.evaluate(fixture, contract, later, [bad_record])
        with self.assertRaises(ValueError):
            self.evaluate(fixture, contract, {"run_id": "absent-source"})

    def test_restart_replays_same_contract_and_history_without_writes(self):
        from storage import SQLitePersistenceStore
        fixture, contract = self.ready()
        waiting = self.evaluate(fixture, contract, self.later(fixture, contract, crossed=False))
        later = self.later(fixture, contract)
        expected = self.evaluate(fixture, contract, later, [waiting])
        store = SQLitePersistenceStore(fixture.store.database_url)
        self.addCleanup(store.close)
        with store.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            self.assertEqual(evaluate_observation(store, conn, json.loads(json.dumps(contract)), later["run_id"], fixture.now,
                                                json.loads(json.dumps([waiting]))), expected)
            self.assertEqual(tuple(conn.iterdump()), before)

    def test_history_bound_default_unactivated_and_unknown_policy_rejected(self):
        with self.assertRaisesRegex(ValueError, "HISTORY_INVALID"):
            evaluate_observation(None, None, {}, "none", "none", [{}]*75)
        with self.assertRaises(ValueError):
            PaperAccountConfig(account_id="fixture", run_id="offline", provider="angelone", source_data_mode="LIVE",
                               fill_policy="UNKNOWN_OB_POLICY")
        config = PaperAccountConfig(account_id="fixture", run_id="offline", provider="angelone", source_data_mode="LIVE")
        self.assertEqual(config.fill_policy, "OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1")
