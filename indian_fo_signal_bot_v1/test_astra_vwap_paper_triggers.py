"""Synthetic offline inputs; unchanged scanner/detector, no activation or market claims."""
import copy
import json
import math
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


from test_astra_paper_triggers import ORBScannerFixture
from paper_portfolio import PaperAccountConfig
from strategies import parse_ist_timestamp
from vwap_paper_triggers import build_contract, evaluate_observation


class VWAPScannerFixture(ORBScannerFixture):
    def __init__(self, owner, side="LONG"):
        super().__init__(owner, side)
        start = self.now.replace(hour=9, minute=15, second=0)
        self.bars[:] = []
        for index in range(35):
            close = 100 + (0.1 if index % 2 else -0.1)
            row = dict(timestamp=(start + timedelta(minutes=5 * index)).isoformat(),
                open=100, high=100.3, low=99.7, close=close, volume=1000)
            if index == 34:
                row.update(open=100, high=100.4, low=99.95, close=100.25, volume=2500)
            if side == "SHORT":
                row.update(open=200-row["open"], high=200-row["low"],
                    low=200-row["high"], close=200-row["close"])
            self.bars.append(row)
        self.scenario.now = parse_ist_timestamp(self.bars[-1]["timestamp"]) + timedelta(minutes=5, seconds=5)

    @staticmethod
    def candidate(summary):
        matches = [s for s in summary["signals"] if s["strategy_id"] == "strat_2_vwap_pullback"]
        if len(matches) != 1:
            raise AssertionError("Expected one actual VWAP candidate: " + str(summary.get("signals")))
        return copy.deepcopy(matches[0])


class TestAstraVWAPPaperTriggers(unittest.TestCase):
    def test_contract_survives_json_storage_roundtrip(self):
        fixture, _, contract = self.ready()
        later = self.later(fixture)
        persisted = json.loads(json.dumps(contract))
        result = self.evaluate(fixture, persisted, later)
        self.assertEqual(result["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")

    def ready(self, side="LONG", **overrides):
        fixture = VWAPScannerFixture(self, side)
        first = fixture.scan()
        candidate = fixture.candidate(first)
        settings = dict(account_id="vwap-experiment", run_id="offline", provider="angelone", source_data_mode="LIVE")
        settings.update(overrides)
        config = PaperAccountConfig(**settings)
        with fixture.store.paper_transaction(write=False) as conn:
            contract = build_contract(fixture.store, conn, first["run_id"], candidate, config, fixture.now)
        return fixture, config, contract

    def later(self, fixture, **overrides):
        values = dict(open=100.05, high=100.5, low=100.0, close=100.3, volume=2500)
        values.update(overrides)
        fixture.append_bar(**values)
        return fixture.scan()

    def evaluate(self, fixture, contract, later, history=(), now=None):
        with fixture.store.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            try:
                return evaluate_observation(fixture.store, conn, contract, later["run_id"], now or fixture.now, history)
            finally:
                self.assertEqual(tuple(conn.iterdump()), before)

    @staticmethod
    def close_fixture(fixture):
        fixture.scenario.tearDown()
        fixture.scenario.doCleanups()

    def test_actual_long_and_short_later_reclaim_are_non_actionable(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                fixture, config, contract = self.ready(side)
                values = dict(open=100.05, high=100.5, low=100.0, close=100.3, volume=2500)
                if side == "SHORT":
                    values = dict(open=200-values["open"], high=200-values["low"],
                        low=200-values["high"], close=200-values["close"], volume=2500)
                fixture.append_bar(**values)
                later = fixture.scan()
                with fixture.store.paper_transaction(write=False) as conn:
                    before = tuple(conn.iterdump())
                    result = evaluate_observation(fixture.store, conn, contract, later["run_id"], fixture.now)
                    self.assertEqual(result["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")
                    self.assertFalse(result["actionable"])
                    self.assertEqual(tuple(conn.iterdump()), before)
                fixture.scenario.tearDown()
                fixture.scenario.doCleanups()

    def test_completed_close_inside_risk_range_does_not_bypass_vwap_predicates(self):
        cases = (
            ("wrong_direction", dict(open=100.35, close=100.3), "directional_close"),
            ("wick_only", dict(open=100.05, high=100.5, close=100.0), "directional_close"),
            ("no_touch", dict(open=100.4, low=100.35, high=100.6, close=100.5), "touch"),
            ("volume", dict(volume=100), "volume"),
        )
        for label, values, failed in cases:
            with self.subTest(case=label):
                fixture, _, contract = self.ready()
                later = self.later(fixture, **values)
                result = self.evaluate(fixture, contract, later)
                self.assertGreater(result["close_reference"], contract["stop_loss"])
                self.assertLess(result["close_reference"], contract["target_1"])
                self.assertEqual(result["status"], "WAITING")
                self.assertFalse(result["measurements"]["checks"][failed])
                self.close_fixture(fixture)

    def test_frozen_invalidation_and_target_take_precedence(self):
        for side in ("LONG", "SHORT"):
            for collision in (False, True):
                with self.subTest(side=side, collision=collision):
                    fixture, _, contract = self.ready(side)
                    if side == "LONG":
                        values = dict(low=contract["invalidation"], high=contract["target_1"] if collision else 100.5)
                    else:
                        values = dict(open=99.95, close=99.7, high=contract["invalidation"],
                            low=contract["target_1"] if collision else 99.5)
                    result = self.evaluate(fixture, contract, self.later(fixture, **values))
                    self.assertEqual(result["status"], "INVALIDATED")
                    self.assertIsNone(result["trigger_timestamp_ist"])
                    self.close_fixture(fixture)

    def test_target_only_and_square_off_are_terminal(self):
        fixture, _, contract = self.ready()
        result = self.evaluate(fixture, contract, self.later(fixture, high=contract["target_1"]))
        self.assertEqual(result["status"], "TARGET_ALREADY_REACHED")
        next_run = self.later(fixture)
        with self.assertRaisesRegex(ValueError, "HISTORY_AFTER_TERMINAL"):
            self.evaluate(fixture, contract, next_run, [result])
        self.close_fixture(fixture)
        fixture, _, contract = self.ready(square_off_ist="12:15")
        result = self.evaluate(fixture, contract, self.later(fixture))
        self.assertEqual(result["status"], "EXPIRED")
        self.assertFalse(result["actionable"])

    def test_same_observation_stale_future_and_gapped_sources_reject(self):
        fixture, _, contract = self.ready()
        with self.assertRaisesRegex(ValueError, "DISTINCT_FUTURE_RUN"):
            self.evaluate(fixture, contract, {"run_id": contract["original_run_id"]})
        later = self.later(fixture)
        for clock in (fixture.now+timedelta(seconds=61), fixture.now-timedelta(seconds=6)):
            with self.subTest(clock=clock):
                with self.assertRaisesRegex(ValueError, "OBSERVATION_TIME_INVALID"):
                    self.evaluate(fixture, contract, later, now=clock)
        # An unfinished last wire bar cannot become the required later input.
        fixture.scenario.now -= timedelta(minutes=1)
        forming = fixture.scan()
        with self.assertRaises(ValueError):
            self.evaluate(fixture, contract, forming)
        fixture.scenario.now += timedelta(minutes=1)
        gap = self.later(fixture)
        with self.assertRaisesRegex(ValueError, "OBSERVATION_GAP_OR_ORDER"):
            self.evaluate(fixture, contract, gap)

    def test_contract_candidate_and_source_scope_tampering_reject(self):
        fixture, _, contract = self.ready()
        later = self.later(fixture)
        for field, value in (("invalidation", 1), ("detector_version", "forged"),
                             ("actionable", True), ("accepted_fill_policy", True)):
            with self.subTest(field=field):
                bad = copy.deepcopy(contract)
                bad[field] = value
                with self.assertRaisesRegex(ValueError, "CONTRACT_INTEGRITY"):
                    self.evaluate(fixture, bad, later)
        for field, value in (("entry_price", 1), ("provider", "upstox"),
                             ("position_type", "SHORT_OPTION")):
            with self.subTest(candidate_field=field):
                bad = copy.deepcopy(contract)
                bad["candidate"][field] = value
                with self.assertRaises(ValueError):
                    self.evaluate(fixture, bad, later)
        with self.assertRaises(ValueError):
            self.evaluate(fixture, contract, {"run_id": "missing-committed-source"})

    def test_waiting_history_replays_and_rejects_measurement_and_scope_forgery(self):
        fixture, config, contract = self.ready()
        first_later = self.later(fixture, volume=100)
        waiting = self.evaluate(fixture, contract, first_later)
        self.assertEqual(waiting["status"], "WAITING")
        second_later = self.later(fixture)
        result = self.evaluate(fixture, contract, second_later, [waiting])
        self.assertEqual(result["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER")
        for field, value in (("status", "QUALIFIED_EXPERIMENTAL_TRIGGER"), ("history_digest", "forged")):
            bad = copy.deepcopy(waiting)
            bad[field] = value
            with self.assertRaisesRegex(ValueError, "HISTORY_INTEGRITY"):
                self.evaluate(fixture, contract, second_later, [bad])
        bad = copy.deepcopy(waiting)
        bad["measurements"]["vwap"] = 1
        with self.assertRaisesRegex(ValueError, "HISTORY_INTEGRITY"):
            self.evaluate(fixture, contract, second_later, [bad])
        for field in ("account_id", "run_id"):
            settings = config.to_dict()
            settings[field] = "other-scope"
            with fixture.store.paper_transaction(write=False) as conn:
                other = build_contract(fixture.store, conn, contract["original_run_id"], contract["candidate"],
                    PaperAccountConfig(**settings), contract["queued_at_ist"])
            with self.assertRaisesRegex(ValueError, "HISTORY_INTEGRITY"):
                self.evaluate(fixture, other, second_later, [waiting])
        with self.assertRaisesRegex(ValueError, "HISTORY_AFTER_TERMINAL"):
            self.evaluate(fixture, contract, second_later, [waiting, result])

    def test_restart_rebuild_is_deterministic_and_database_unchanged(self):
        from storage import SQLitePersistenceStore
        fixture, _, contract = self.ready()
        later = self.later(fixture)
        first = self.evaluate(fixture, contract, later)
        restarted = SQLitePersistenceStore(fixture.store.database_url)
        self.addCleanup(restarted.close)
        with restarted.paper_transaction(write=False) as conn:
            before = tuple(conn.iterdump())
            self.assertEqual(evaluate_observation(restarted, conn, contract, later["run_id"], fixture.now), first)
            self.assertEqual(tuple(conn.iterdump()), before)

    def test_invalid_account_policy_and_history_envelope_fail_before_source_reads(self):
        for field, value in (("risk_pct", 0), ("starting_capital_inr", 0), ("interval_min", 1)):
            with self.subTest(field=field):
                settings = dict(account_id="fixture", run_id="offline", provider="angelone", source_data_mode="LIVE")
                settings[field] = value
                with self.assertRaises(ValueError):
                    PaperAccountConfig(**settings)
        for history in ([{}]*75, "not-a-list", {"forged": True}):
            with self.assertRaisesRegex(ValueError, "HISTORY_INVALID"):
                evaluate_observation(None, None, {}, "none", "not-a-clock", history)

    def test_existing_orb_contract_and_unsupported_vwap_policy_are_unchanged(self):
        from paper_triggers import build_contract as orb_contract
        fixture = ORBScannerFixture(self)
        first = fixture.scan()
        candidate = fixture.candidate(first)
        with fixture.store.paper_transaction(write=False) as conn:
            original = orb_contract(fixture.store, conn, first["run_id"], candidate, "15:20")
        self.assertEqual(original["rule_id"], "orb.signal_extreme_completed_close_cross.v1")
        self.assertEqual(original["fill_policy"], "ORB_FOLLOW_THROUGH_CLOSE_V1")
        with self.assertRaises(ValueError):
            PaperAccountConfig(account_id="fixture", run_id="offline", provider="angelone", source_data_mode="LIVE",
                fill_policy="VWAP_FUTURE_RECLAIM_V1")

    def test_volume_and_unit_numeric_indicator_boundaries(self):
        """Volume is end-to-end; patched indicator edges test numerical checks only.

        Native scanner inputs and unchanged detector/cost sizing remain real.
        Mocked EMA/RSI measurements establish comparator boundaries, not native
        indicator acceptance or a fabricated scanner qualification trace.
        """
        for side in ("LONG", "SHORT"):
            for below in (False, True):
                with self.subTest(side=side, volume_below=below):
                    fixture, _, contract = self.ready(side)
                    baseline = sum(b["volume"] for b in fixture.bars[-20:])/20
                    threshold = baseline*1.4
                    self.assertEqual(threshold, 1505)
                    values = dict(volume=threshold-int(below))
                    if side == "SHORT":
                        values.update(open=99.95, high=100, low=99.5, close=99.7)
                    later = self.later(fixture, **values)
                    result = self.evaluate(fixture, contract, later)
                    self.assertEqual(result["measurements"]["baseline_volume"], baseline)
                    self.assertEqual(result["measurements"]["checks"]["volume"], not below)
                    self.assertEqual(result["status"], "WAITING" if below else "QUALIFIED_EXPERIMENTAL_TRIGGER")
                    self.assertFalse(result["actionable"])
                    if not below:
                        close = result["close_reference"]
                        lower, upper = (48., 72.) if side == "LONG" else (28., 52.)
                        for edge in (lower, upper, math.nextafter(lower, -math.inf), math.nextafter(upper, math.inf)):
                            with self.subTest(side=side, unit_rsi=edge):
                                with patch("vwap_paper_triggers.compute_rsi", return_value=[edge]):
                                    checked = self.evaluate(fixture, contract, later)
                                passed = lower <= edge <= upper
                                self.assertEqual(checked["measurements"]["checks"]["rsi"], passed)
                                self.assertEqual(checked["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER" if passed else "WAITING")
                                self.assertFalse(checked["actionable"])
                        multiplier = .998 if side == "LONG" else 1.002
                        equality = close/multiplier
                        self.assertEqual(equality*multiplier, close)
                        outside = math.nextafter(equality, math.inf if side == "LONG" else -math.inf)
                        for ema, passed in ((equality, True), (outside, False)):
                            with self.subTest(side=side, unit_ema=ema):
                                with patch("vwap_paper_triggers.compute_ema", return_value=[ema]):
                                    checked = self.evaluate(fixture, contract, later)
                                self.assertEqual(checked["measurements"]["checks"]["ema"], passed)
                                self.assertEqual(checked["status"], "QUALIFIED_EXPERIMENTAL_TRIGGER" if passed else "WAITING")
                                self.assertFalse(checked["actionable"])
                    self.close_fixture(fixture)
