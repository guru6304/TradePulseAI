"""OFFLINE SIMULATION: native ST scanner input and opt-in paper accounting.

Only fixture-backed read endpoints and disposable SQLite stores are used.
Synthetic wire rows establish software behavior, never live acceptance,
publisher authenticity, empirical strategy performance or executable quotes.
"""
import copy
import json
import os
import sqlite3
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from forward_paper import ForwardPaperCoordinator
from paper_portfolio import PaperAccountConfig, PaperPortfolio, PaperPortfolioError
from test_track_a_supertrend_triggers import SupertrendScannerFixture

POLICY = "ST_REPEATED_PULLBACK_CLOSE_V1"


def queued_st(owner, side="LONG", **settings):
    fixture = SupertrendScannerFixture(owner, side)
    values = dict(account_id="st-execution", run_id="offline", provider="angelone",
                  source_data_mode="LIVE", fill_policy=POLICY)
    values.update(settings)
    paper = PaperPortfolio(fixture.store, PaperAccountConfig(**values), clock=lambda: fixture.now)
    first = fixture.scan(paper)
    candidate = fixture.candidate(first)
    decision = next(d for d in paper.snapshot()["candidate_decisions"] if d["candidate"] == candidate)
    guard = lambda: fixture.engine._require_current_scan_data("angelone", now_dt=fixture.now)
    return SimpleNamespace(fixture=fixture, paper=paper, first=first, candidate=candidate,
        decision_id=decision["candidate_id"], guard=guard, contract=decision["trigger_contract"])


def later_st(ready, *, consume=False, **overrides):
    entry = ready.candidate["entry_price"]
    if ready.fixture.side == "LONG":
        values = dict(open=entry, close=entry+.05, low=ready.contract["invalidation"]+.01, high=entry+.10)
    else:
        values = dict(open=entry, close=entry-.05, high=ready.contract["invalidation"]-.01, low=entry-.10)
    values["volume"] = 2*sum(b["volume"] for b in ready.fixture.bars[-20:])/20
    values.update(overrides)
    ready.fixture.append_bar(**values)
    ready.later = ready.fixture.scan(ready.paper if consume else None)
    ready.bar = ready.fixture.retained_bar(ready.later)
    ready.arguments = dict(candidate_decision_id=ready.decision_id,
        source_scan_run_id=ready.later["run_id"], entry_guard=ready.guard)
    return ready.later


def ready_st_trigger(owner, side="LONG", **settings):
    ready = queued_st(owner, side, **settings)
    later_st(ready)
    ready.paper.observe_candidate(ready.decision_id, ready.bar, ready.later["run_id"])
    return ready


class TestTrackASupertrendExecution(unittest.TestCase):
    def decision(self, ready):
        return next(d for d in ready.paper.snapshot()["candidate_decisions"] if d["candidate_id"] == ready.decision_id)

    def dump(self, ready):
        with ready.fixture.store.paper_transaction(write=False) as conn:
            return tuple(conn.iterdump())

    def no_entry(self, ready):
        report = ready.paper.snapshot()
        self.assertEqual(report["positions"], [])
        self.assertFalse(any(e["kind"] == "ENTRY" for e in report["events"]))
        self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
        return report

    @staticmethod
    def close_fixture(ready):
        ready.fixture.scenario.tearDown()
        ready.fixture.scenario.doCleanups()

    def test_actual_long_short_scanner_handoff_fills_once_at_later_close(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                ready = queued_st(self, side)
                self.assertEqual(self.decision(ready)["status"], "QUEUED")
                self.no_entry(ready)
                frozen = copy.deepcopy(ready.contract)
                later_st(ready, consume=True)
                report = ready.paper.snapshot()
                self.assertEqual(self.decision(ready)["status"], "FILLED")
                self.assertEqual(len(report["positions"]), 1)
                position = report["positions"][0]
                self.assertEqual(position["raw_entry_price"], ready.bar["close"])
                self.assertEqual(position["candidate"], ready.candidate)
                self.assertEqual(position["stop_loss"], ready.candidate["stop_loss"])
                self.assertEqual(position["target_price"], ready.candidate["target_1"])
                self.assertEqual(position["fill_policy"], POLICY)
                self.assertEqual(position["trigger_contract"], frozen)
                self.assertEqual(position["trigger_contract"]["invalidation"], ready.candidate["invalidation_level"])
                self.assertNotEqual(position["candidate_timestamp_ist"], position["fill_timestamp_ist"])
                self.assertEqual(report["reconciliation"]["status"], "OK")
                before = self.dump(ready)
                ForwardPaperCoordinator(ready.paper).consume_scan(ready.later, {ready.candidate["symbol"]: [ready.bar]})
                self.assertEqual(self.dump(ready), before)
                self.close_fixture(ready)

    def test_st_and_existing_strategy_policies_do_not_cross_admit(self):
        from test_astra_paper_triggers import ORBScannerFixture
        from test_astra_vwap_paper_triggers import VWAPScannerFixture
        from test_track_a_order_block_triggers import OrderBlockScannerFixture
        cases = [(SupertrendScannerFixture, policy) for policy in
                 ("ORB_FOLLOW_THROUGH_CLOSE_V1", "VWAP_REPEATED_RECLAIM_CLOSE_V1", "OB_FIRST_RETEST_FOLLOW_THROUGH_CLOSE_V1")]
        cases += [(factory, POLICY) for factory in (ORBScannerFixture, VWAPScannerFixture, OrderBlockScannerFixture)]
        for factory, policy in cases:
            with self.subTest(fixture=factory.__name__, policy=policy):
                fixture = factory(self)
                paper = PaperPortfolio(fixture.store, PaperAccountConfig(account_id="st-policy-isolation", run_id="offline",
                    provider="angelone", source_data_mode="LIVE", fill_policy=policy), clock=lambda: fixture.now)
                first = fixture.scan(paper)
                candidate = fixture.candidate(first)
                decision = next(d for d in paper.snapshot()["candidate_decisions"] if d["candidate"] == candidate)
                self.assertEqual(decision["status"], "REJECTED")
                self.no_entry(SimpleNamespace(paper=paper))
                self.close_fixture(SimpleNamespace(fixture=fixture))
        self.assertEqual(PaperAccountConfig(account_id="default", run_id="offline", provider="angelone",
            source_data_mode="LIVE").fill_policy, "OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1")

    def test_four_waits_have_no_arbitrary_ttl_and_original_bracket_does_not_trail(self):
        ready = queued_st(self)
        frozen = copy.deepcopy(ready.contract)
        for _ in range(4):
            later_st(ready, consume=True, volume=1)
            self.no_entry(ready)
            decision = self.decision(ready)
            self.assertEqual(decision["status"], "QUEUED")
            self.assertEqual(decision["trigger_evaluations"][-1]["status"], "WAITING")
            self.assertEqual(decision["trigger_contract"], frozen)
        self.assertEqual(len(self.decision(ready)["trigger_evaluations"]), 4)
        later_st(ready, consume=True)
        self.assertEqual(self.decision(ready)["status"], "FILLED")
        position = ready.paper.snapshot()["positions"][0]
        self.assertEqual(position["trigger_contract"], frozen)
        self.assertEqual(position["stop_loss"], frozen["stop_loss"])
        self.assertEqual(position["target_price"], frozen["target_1"])

    def test_repeated_direction_and_pullback_are_required_before_entry(self):
        for side in ("LONG", "SHORT"):
            for mode in ("direction", "touch"):
                with self.subTest(side=side, mode=mode):
                    ready = queued_st(self, side)
                    entry = ready.candidate["entry_price"]
                    values = ({"open": entry+(.1 if side == "LONG" else -.1)} if mode == "direction" else
                              {"low" if side == "LONG" else "high": entry+(-.01 if side == "LONG" else .01)})
                    later_st(ready, consume=True, **values)
                    self.no_entry(ready)
                    record = self.decision(ready)["trigger_evaluations"][-1]
                    self.assertEqual(record["status"], "WAITING")
                    self.assertFalse(record["evidence_record"]["measurements"]["checks"]["directional_close" if mode == "direction" else "touch"])
                    self.close_fixture(ready)

    def test_invalidation_target_collision_and_square_off_precede_entry(self):
        for side in ("LONG", "SHORT"):
            for mode in ("invalidation", "target", "collision", "square_off"):
                with self.subTest(side=side, mode=mode):
                    ready = queued_st(self, side, **({"square_off_ist": "14:10"} if mode == "square_off" else {}))
                    values = {}
                    if mode in ("invalidation", "collision"):
                        values["low" if side == "LONG" else "high"] = ready.candidate["invalidation_level"]
                    if mode in ("target", "collision"):
                        values["high" if side == "LONG" else "low"] = ready.candidate["target_1"]
                    later_st(ready, consume=True, **values)
                    self.no_entry(ready)
                    self.assertEqual(self.decision(ready)["status"], "REJECTED")
                    self.close_fixture(ready)

    def test_direct_same_bar_and_unrecorded_future_entry_cannot_bypass_trigger(self):
        ready = queued_st(self)
        later_st(ready)
        baseline = self.dump(ready)
        for arguments in ({}, ready.arguments):
            with self.subTest(arguments=bool(arguments)), self.assertRaises(PaperPortfolioError):
                ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **arguments)
            self.assertEqual(self.dump(ready), baseline)
            self.no_entry(ready)
        with self.assertRaises(PaperPortfolioError):
            ready.paper.observe_candidate(ready.decision_id, ready.fixture.retained_bar(ready.first), ready.first["run_id"])
        self.assertEqual(self.dump(ready), baseline)

    def test_stale_and_missing_intermediate_observation_cannot_be_backfilled(self):
        for mode in ("stale", "gap"):
            ready = queued_st(self)
            later_st(ready)
            if mode == "stale":
                ready.fixture.scenario.now += timedelta(minutes=2)
            else:
                later_st(ready)
            ForwardPaperCoordinator(ready.paper, entry_guard=ready.guard).consume_scan(
                ready.later, {ready.candidate["symbol"]: [ready.bar]})
            self.no_entry(ready)
            self.assertEqual(self.decision(ready)["status"], "REJECTED")
            self.assertEqual(self.decision(ready)["reason_code"], "TRIGGER_REQUIRED_OBSERVATION_WINDOW_EXPIRED")
            self.close_fixture(ready)

    def test_missing_current_guard_defers_scanner_handoff_without_entry(self):
        ready = queued_st(self)
        later_st(ready)
        result = ForwardPaperCoordinator(ready.paper).consume_scan(ready.later, {ready.candidate["symbol"]: [ready.bar]})
        self.no_entry(ready)
        self.assertEqual(self.decision(ready)["status"], "QUEUED")
        self.assertEqual(self.decision(ready)["trigger_evaluations"], [])
        self.assertTrue(any(a.get("candidate_id") == ready.decision_id and
            a.get("reason_code") == "CURRENT_SCANNER_GUARD_REQUIRED" for a in result["actions"]))

    def test_supplied_bar_source_and_missing_current_guard_fail_without_writes(self):
        ready = ready_st_trigger(self)
        baseline = self.dump(ready)
        bad = dict(ready.bar, close=ready.bar["close"]+.01)
        cases = ((bad, ready.arguments), (ready.bar, dict(ready.arguments, source_scan_run_id=ready.first["run_id"])),
                 (ready.bar, dict(ready.arguments, entry_guard=None)))
        for bar, arguments in cases:
            with self.subTest(source=arguments["source_scan_run_id"], guard=bool(arguments["entry_guard"])), self.assertRaises(PaperPortfolioError):
                ready.paper.enter(ready.candidate, bar, ready.decision_id, **arguments)
            self.assertEqual(self.dump(ready), baseline)
            self.no_entry(ready)

    def test_duplicate_qualified_observation_is_read_only_and_conflicting_bar_rejects(self):
        ready = ready_st_trigger(self)
        baseline = self.dump(ready)
        observed = ready.paper.observe_candidate(ready.decision_id, ready.bar, ready.later["run_id"])
        self.assertEqual(observed["trigger_evaluations"][-1]["status"], "TRIGGERED")
        self.assertEqual(self.dump(ready), baseline)
        with self.assertRaises(PaperPortfolioError):
            ready.paper.observe_candidate(ready.decision_id, dict(ready.bar, close=ready.bar["close"]+.01), ready.later["run_id"])
        self.assertEqual(self.dump(ready), baseline)

    def test_account_run_provider_data_mode_and_strategy_scope_do_not_cross_enter(self):
        ready = ready_st_trigger(self)
        for field, value in (("account_id", "other-st-account"), ("provider", "upstox"),
                             ("source_data_mode", "SIMULATED"), ("allowed_strategies", ("strat_1_order_block",))):
            settings = ready.paper.config.to_dict()
            settings.update(account_id="st-other-"+field)
            settings[field] = value
            paper = PaperPortfolio(ready.fixture.store, PaperAccountConfig(**settings), clock=lambda: ready.fixture.now)
            baseline = self.dump(ready)
            with self.subTest(field=field), self.assertRaises(PaperPortfolioError):
                paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
            self.assertEqual(self.dump(ready), baseline)
            self.assertEqual(paper.snapshot()["positions"], [])
        settings = ready.paper.config.to_dict()
        settings["run_id"] = "other-run"
        with self.assertRaises(PaperPortfolioError):
            PaperPortfolio(ready.fixture.store, PaperAccountConfig(**settings), clock=lambda: ready.fixture.now)
        self.no_entry(ready)

    def test_contract_nested_evidence_candidate_and_decision_scope_forgery_fail_closed(self):
        ready = ready_st_trigger(self)
        original = self.decision(ready)
        variants = [dict(original, **{field: "forged"}) for field in
                    ("account_id", "run_id", "config_hash", "candidate_hash", "signal_key")]
        for field in ("invalidation", "stop_loss", "target_1", "contract_digest"):
            changed = copy.deepcopy(original)
            changed["trigger_contract"][field] = "forged"
            variants.append(changed)
        changed = copy.deepcopy(original)
        changed["trigger_evaluations"][-1]["close"] = 1
        variants.append(changed)
        changed = copy.deepcopy(original)
        changed["trigger_evaluations"][-1]["evidence_record"]["measurements"]["supertrend10_3"] = 1
        variants.append(changed)
        for changed in variants:
            with ready.fixture.store.paper_transaction() as conn:
                conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                             (json.dumps(changed), ready.decision_id))
            baseline = self.dump(ready)
            try:
                with self.assertRaises(PaperPortfolioError):
                    ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
                self.assertEqual(self.dump(ready), baseline)
            finally:
                with ready.fixture.store.paper_transaction() as conn:
                    conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                                 (json.dumps(original), ready.decision_id))
        self.no_entry(ready)

    def test_late_guard_failure_rolls_back_position_mark_reservation_and_decision(self):
        ready = ready_st_trigger(self)
        baseline = self.dump(ready)
        calls = []
        def guard():
            calls.append(True)
            if len(calls) == 2:
                raise PaperPortfolioError("AUTHORED_LATE_ST_DEGRADATION")
        with self.assertRaisesRegex(PaperPortfolioError, "AUTHORED_LATE_ST_DEGRADATION"):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **dict(ready.arguments, entry_guard=guard))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.dump(ready), baseline)
        self.no_entry(ready)

    def test_entry_sql_failure_rolls_back_position_mark_reservation_and_decision(self):
        ready = ready_st_trigger(self)
        with ready.fixture.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER deny_st_entry BEFORE INSERT ON paper_events WHEN NEW.kind='ENTRY' "
                         "BEGIN SELECT RAISE(ABORT,'AUTHORED_ST_ENTRY_FAILURE'); END")
        baseline = self.dump(ready)
        with self.assertRaises(sqlite3.IntegrityError):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(self.dump(ready), baseline)
        self.no_entry(ready)

    def test_qualified_pending_evidence_survives_restart_before_entry(self):
        from storage import SQLitePersistenceStore
        ready = ready_st_trigger(self)
        store = SQLitePersistenceStore(ready.fixture.store.database_url)
        self.addCleanup(store.close)
        paper = PaperPortfolio(store, ready.paper.config, clock=lambda: ready.fixture.now)
        result = paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(len(paper.snapshot()["positions"]), 1)
        self.assertEqual(paper.snapshot()["positions"][0]["trigger_contract"], ready.contract)
        self.assertEqual(paper.snapshot()["reconciliation"]["status"], "OK")

    def test_restart_idempotent_entry_and_transition_need_no_new_feed(self):
        from storage import SQLitePersistenceStore
        ready = ready_st_trigger(self)
        result = ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        store = SQLitePersistenceStore(ready.fixture.store.database_url)
        self.addCleanup(store.close)
        paper = PaperPortfolio(store, ready.paper.config, clock=lambda: ready.fixture.now)
        baseline = self.dump(ready)
        self.assertTrue(paper.enter(ready.candidate, ready.bar, ready.decision_id)["idempotent"])
        recovered = ForwardPaperCoordinator(paper)._transition(ready.decision_id, "FILLED", "RETRY")
        self.assertEqual(recovered["position_id"], result["position_id"])
        self.assertEqual(self.dump(ready), baseline)

    def test_exposure_gate_rejects_qualified_trigger_without_reservation(self):
        ready = ready_st_trigger(self, max_position_exposure_pct=.01)
        baseline = self.dump(ready)
        with self.assertRaisesRegex(PaperPortfolioError, "EXPOSURE_LIMIT"):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(self.dump(ready), baseline)
        self.no_entry(ready)

    def test_new_qualified_candidate_respects_daily_entry_open_position_and_loss_caps(self):
        cases = ((dict(max_entries_per_day=1), "DAILY_ENTRY_LIMIT"),
                 (dict(max_open_positions=1), "OPEN_POSITION_LIMIT"),
                 (dict(max_daily_loss_inr=.01), "DAILY_LOSS_LIMIT"))
        for settings, reason in cases:
            with self.subTest(reason=reason):
                ready = queued_st(self, **settings)
                later_st(ready, consume=True)
                self.assertEqual(self.decision(ready)["status"], "FILLED")
                next_candidate = ready.fixture.candidate(ready.later)
                next_decision = next(d for d in ready.paper.snapshot()["candidate_decisions"] if d["candidate"] == next_candidate)
                self.assertEqual(next_decision["status"], "QUEUED")
                later_st(ready, consume=True)
                report = ready.paper.snapshot()
                rejected = next(d for d in report["candidate_decisions"] if d["candidate_id"] == next_decision["candidate_id"])
                self.assertEqual(rejected["status"], "REJECTED")
                self.assertEqual(rejected["reason_code"], reason)
                self.assertEqual(len(report["positions"]), 1)
                self.assertEqual(sum(e["kind"] == "ENTRY" for e in report["events"]), 1)
                self.assertEqual(report["reconciliation"]["status"], "OK")
                self.close_fixture(ready)

    def test_filled_position_closes_at_eod_with_costs_and_original_stop_target(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                ready = queued_st(self, side, square_off_ist="14:15")
                later_st(ready, consume=True)
                self.assertEqual(self.decision(ready)["status"], "FILLED")
                later_st(ready, consume=True)
                report = ready.paper.snapshot()
                position = report["positions"][0]
                self.assertEqual(position["status"], "CLOSED")
                self.assertEqual(position["exit_reason"], "EOD")
                self.assertEqual(position["stop_loss"], ready.candidate["stop_loss"])
                self.assertEqual(position["target_price"], ready.candidate["target_1"])
                self.assertEqual(position["trigger_contract"]["invalidation"], ready.candidate["invalidation_level"])
                self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
                self.assertGreater(report["accounting"]["fees_paid_inr"], 0)
                self.assertEqual(report["reconciliation"]["status"], "OK")
                self.assertEqual(sum(e["kind"] == "ENTRY" for e in report["events"]), 1)
                self.assertEqual(sum(e["kind"] == "EXIT" for e in report["events"]), 1)
                self.close_fixture(ready)

    def test_concurrent_coordinators_commit_only_one_entry_and_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from storage import SQLitePersistenceStore
        ready = ready_st_trigger(self)
        barrier = Barrier(2)
        def consume():
            store = SQLitePersistenceStore(ready.fixture.store.database_url)
            try:
                paper = PaperPortfolio(store, ready.paper.config, clock=lambda: ready.fixture.now)
                barrier.wait(timeout=10)
                return ForwardPaperCoordinator(paper, entry_guard=ready.guard).consume_scan(
                    ready.later, {ready.candidate["symbol"]: [ready.bar]})
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(consume) for _ in range(2)]
            for future in futures:
                self.assertEqual(future.result(timeout=30)["status"], "COMPLETED")
        report = ready.paper.snapshot()
        self.assertEqual(len(report["positions"]), 1)
        self.assertEqual(sum(e["kind"] == "ENTRY" for e in report["events"]), 1)
        self.assertEqual(report["accounting"]["reserved_capital_inr"], report["positions"][0]["reserved_capital_inr"])
        self.assertEqual(report["reconciliation"]["status"], "OK")
