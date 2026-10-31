"""Offline VWAP opt-in execution: real scanner lineage, simulated accounting only."""
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
from test_astra_vwap_paper_triggers import VWAPScannerFixture

POLICY = "VWAP_REPEATED_RECLAIM_CLOSE_V1"


def queued_vwap(owner, side="LONG", **settings):
    fixture = VWAPScannerFixture(owner, side)
    values = dict(account_id="vwap-execution", run_id="offline", provider="angelone",
                  source_data_mode="LIVE", fill_policy=POLICY)
    values.update(settings)
    paper = PaperPortfolio(fixture.store, PaperAccountConfig(**values), clock=lambda: fixture.now)
    first = fixture.scan(paper)
    candidate = fixture.candidate(first)
    decision = next(d for d in paper.snapshot()["candidate_decisions"] if d["candidate"] == candidate)
    guard = lambda: fixture.engine._require_current_scan_data("angelone", now_dt=fixture.now)
    return SimpleNamespace(fixture=fixture, paper=paper, first=first, candidate=candidate,
                           decision_id=decision["candidate_id"], guard=guard)


def later_vwap(ready, *, consume=False, **overrides):
    values = (dict(open=100.05, high=100.5, low=100, close=100.3, volume=2500)
              if ready.fixture.side == "LONG" else
              dict(open=99.95, high=100, low=99.5, close=99.7, volume=2500))
    values.update(overrides)
    ready.fixture.append_bar(**values)
    ready.later = ready.fixture.scan(ready.paper if consume else None)
    ready.bar = ready.fixture.retained_bar(ready.later)
    ready.arguments = dict(candidate_decision_id=ready.decision_id,
                           source_scan_run_id=ready.later["run_id"], entry_guard=ready.guard)
    return ready.later


def ready_vwap_trigger(owner, side="LONG", **settings):
    ready = queued_vwap(owner, side, **settings)
    later_vwap(ready)
    ready.paper.observe_candidate(ready.decision_id, ready.bar, ready.later["run_id"])
    return ready


class TestAstraVWAPExecution(unittest.TestCase):
    def test_opt_in_does_not_change_default_or_accept_orb_candidates(self):
        from test_astra_paper_triggers import ORBScannerFixture
        settings = dict(account_id="vwap-only", run_id="offline", provider="angelone", source_data_mode="LIVE")
        self.assertEqual(PaperAccountConfig(**settings).fill_policy, "OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1")
        fixture = ORBScannerFixture(self)
        paper = PaperPortfolio(fixture.store, PaperAccountConfig(**settings, fill_policy=POLICY), clock=lambda: fixture.now)
        first = fixture.scan(paper)
        candidate = fixture.candidate(first)
        decision = next(d for d in paper.snapshot()["candidate_decisions"] if d["candidate"] == candidate)
        self.assertEqual(decision["status"], "REJECTED")
        self.no_entry(SimpleNamespace(paper=paper))

    def decision(self, ready):
        return next(d for d in ready.paper.snapshot()["candidate_decisions"]
                    if d["candidate_id"] == ready.decision_id)

    def dump(self, ready):
        with ready.fixture.store.paper_transaction(write=False) as conn:
            return tuple(conn.iterdump())

    def no_entry(self, ready):
        report = ready.paper.snapshot()
        self.assertEqual(report["positions"], [])
        self.assertFalse(any(e["kind"] == "ENTRY" for e in report["events"]))
        self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
        return report

    def close_fixture(self, ready):
        ready.fixture.scenario.tearDown()
        ready.fixture.scenario.doCleanups()

    def test_actual_long_short_scanner_handoff_fills_once_at_later_close(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                ready = queued_vwap(self, side)
                self.no_entry(ready)
                later_vwap(ready, consume=True)
                report = ready.paper.snapshot()
                self.assertEqual(self.decision(ready)["status"], "FILLED")
                self.assertEqual(len(report["positions"]), 1)
                position = report["positions"][0]
                self.assertEqual(position["raw_entry_price"], ready.bar["close"])
                self.assertEqual(position["candidate"], ready.candidate)
                self.assertEqual(position["stop_loss"], ready.candidate["stop_loss"])
                self.assertEqual(position["target_price"], ready.candidate["target_1"])
                self.assertEqual(position["fill_policy"], POLICY)
                self.assertNotEqual(position["candidate_timestamp_ist"], position["fill_timestamp_ist"])
                self.assertEqual(report["reconciliation"]["status"], "OK")
                before = self.dump(ready)
                ForwardPaperCoordinator(ready.paper).consume_scan(ready.later, {ready.candidate["symbol"]: [ready.bar]})
                self.assertEqual(self.dump(ready), before)
                self.close_fixture(ready)

    def test_waiting_inside_original_bracket_does_not_fill_then_reclaim_can_fill(self):
        ready = queued_vwap(self)
        later_vwap(ready, consume=True, volume=100)
        self.no_entry(ready)
        self.assertEqual(self.decision(ready)["trigger_evaluations"][-1]["status"], "WAITING")
        later_vwap(ready, consume=True)
        self.assertEqual(self.decision(ready)["status"], "FILLED")

    def test_invalidation_target_and_square_off_precede_entry(self):
        for mode in ("invalidation", "target", "collision", "square_off"):
            with self.subTest(mode=mode):
                ready = queued_vwap(self, **({"square_off_ist": "12:15"} if mode == "square_off" else {}))
                values = {}
                if mode in ("invalidation", "collision"):
                    values["low"] = ready.candidate["invalidation_level"]
                if mode in ("target", "collision"):
                    values["high"] = ready.candidate["target_1"]
                later_vwap(ready, consume=True, **values)
                self.no_entry(ready)
                self.assertEqual(self.decision(ready)["status"], "REJECTED")
                self.close_fixture(ready)

    def test_direct_and_same_bar_entry_cannot_bypass_durable_trigger(self):
        ready = queued_vwap(self)
        later_vwap(ready)
        for arguments in ({}, ready.arguments):
            with self.subTest(arguments=bool(arguments)), self.assertRaises(PaperPortfolioError):
                ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **arguments)
            self.no_entry(ready)
        with self.assertRaises(PaperPortfolioError):
            ready.paper.observe_candidate(ready.decision_id, ready.fixture.retained_bar(ready.first), ready.first["run_id"])
        self.no_entry(ready)

    def test_stale_or_missing_intermediate_observation_cannot_be_backfilled(self):
        for mode in ("stale", "gap"):
            with self.subTest(mode=mode):
                ready = queued_vwap(self)
                later_vwap(ready)
                if mode == "stale":
                    ready.fixture.scenario.now += timedelta(minutes=2)
                else:
                    later_vwap(ready)
                ForwardPaperCoordinator(ready.paper, entry_guard=ready.guard).consume_scan(
                    ready.later, {ready.candidate["symbol"]: [ready.bar]})
                self.no_entry(ready)
                self.assertEqual(self.decision(ready)["status"], "REJECTED")
                self.close_fixture(ready)

    def test_supplied_bar_source_or_current_guard_conflict_cannot_enter(self):
        ready = ready_vwap_trigger(self)
        baseline = self.dump(ready)
        bad = dict(ready.bar, close=ready.bar["close"] + .01)
        cases = ((bad, ready.arguments), (ready.bar, dict(ready.arguments, source_scan_run_id=ready.first["run_id"])),
                 (ready.bar, dict(ready.arguments, entry_guard=None)))
        for bar, arguments in cases:
            with self.subTest(source=arguments["source_scan_run_id"], guard=bool(arguments["entry_guard"])), self.assertRaises(PaperPortfolioError):
                ready.paper.enter(ready.candidate, bar, ready.decision_id, **arguments)
            self.assertEqual(self.dump(ready), baseline)
            self.no_entry(ready)

    def test_contract_history_account_and_candidate_tampering_fail_closed(self):
        ready = ready_vwap_trigger(self)
        original = self.decision(ready)
        variants = []
        for field in ("account_id", "run_id", "config_hash", "candidate_hash", "signal_key"):
            variants.append(dict(original, **{field: "forged"}))
        changed = copy.deepcopy(original)
        changed["trigger_contract"]["contract_digest"] = "forged"
        variants.append(changed)
        changed = copy.deepcopy(original)
        changed["trigger_evaluations"][-1]["close"] = 1
        variants.append(changed)
        for changed in variants:
            with ready.fixture.store.paper_transaction() as conn:
                conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                             (json.dumps(changed), ready.decision_id))
            before = self.dump(ready)
            try:
                with self.assertRaises(PaperPortfolioError):
                    ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
                self.assertEqual(self.dump(ready), before)
            finally:
                with ready.fixture.store.paper_transaction() as conn:
                    conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                                 (json.dumps(original), ready.decision_id))
        self.no_entry(ready)

    def test_late_guard_failure_rolls_back_all_financial_and_decision_effects(self):
        ready = ready_vwap_trigger(self)
        baseline = self.dump(ready)
        calls = []
        def guard():
            calls.append(True)
            if len(calls) == 2:
                raise PaperPortfolioError("AUTHORED_LATE_DEGRADATION")
        with self.assertRaisesRegex(PaperPortfolioError, "AUTHORED_LATE_DEGRADATION"):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **dict(ready.arguments, entry_guard=guard))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.dump(ready), baseline)
        self.no_entry(ready)

    def test_entry_sql_failure_rolls_back_position_mark_and_reservation(self):
        ready = ready_vwap_trigger(self)
        with ready.fixture.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER deny_vwap_entry BEFORE INSERT ON paper_events WHEN NEW.kind='ENTRY' "
                         "BEGIN SELECT RAISE(ABORT,'AUTHORED_ENTRY_FAILURE'); END")
        before = self.dump(ready)
        with self.assertRaises(sqlite3.IntegrityError):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(self.dump(ready), before)
        self.no_entry(ready)

    def test_restart_recovery_and_idempotent_entry_need_no_new_feed(self):
        from storage import SQLitePersistenceStore
        ready = ready_vwap_trigger(self)
        result = ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        store = SQLitePersistenceStore(ready.fixture.store.database_url)
        self.addCleanup(store.close)
        paper = PaperPortfolio(store, ready.paper.config, clock=lambda: ready.fixture.now)
        before = self.dump(ready)
        self.assertTrue(paper.enter(ready.candidate, ready.bar, ready.decision_id)["idempotent"])
        recovered = ForwardPaperCoordinator(paper)._transition(ready.decision_id, "FILLED", "RETRY")
        self.assertEqual(recovered["position_id"], result["position_id"])
        self.assertEqual(self.dump(ready), before)

    def test_qualified_pending_evidence_survives_restart_before_entry(self):
        from storage import SQLitePersistenceStore
        ready = ready_vwap_trigger(self)
        store = SQLitePersistenceStore(ready.fixture.store.database_url)
        self.addCleanup(store.close)
        paper = PaperPortfolio(store, ready.paper.config, clock=lambda: ready.fixture.now)
        result = paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(len(paper.snapshot()["positions"]), 1)
        self.assertEqual(paper.snapshot()["reconciliation"]["status"], "OK")

    def test_risk_exposure_gate_rejects_qualified_trigger_without_reservation(self):
        ready = ready_vwap_trigger(self, max_position_exposure_pct=.01)
        before = self.dump(ready)
        with self.assertRaisesRegex(PaperPortfolioError, "EXPOSURE_LIMIT"):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(self.dump(ready), before)
        self.no_entry(ready)

    def test_filled_position_closes_at_eod_with_costs_and_reconciled_ledger(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                ready = queued_vwap(self, side, square_off_ist="12:20")
                later_vwap(ready, consume=True)
                self.assertEqual(self.decision(ready)["status"], "FILLED")
                later_vwap(ready, consume=True)
                report = ready.paper.snapshot()
                self.assertEqual(report["positions"][0]["status"], "CLOSED")
                self.assertEqual(report["positions"][0]["exit_reason"], "EOD")
                self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
                self.assertEqual(report["reconciliation"]["status"], "OK")
                self.assertEqual(sum(e["kind"] == "ENTRY" for e in report["events"]), 1)
                self.assertEqual(sum(e["kind"] == "EXIT" for e in report["events"]), 1)
                self.close_fixture(ready)

    def test_concurrent_coordinators_commit_only_one_entry(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from storage import SQLitePersistenceStore
        ready = ready_vwap_trigger(self)
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
        self.assertEqual(report["reconciliation"]["status"], "OK")
