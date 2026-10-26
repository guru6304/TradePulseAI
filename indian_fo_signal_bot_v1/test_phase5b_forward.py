"""OFFLINE SIMULATION: explicit scanner handoff and durable forward decisions."""
import copy
import json
import sqlite3
import os
import sys
import unittest
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from forward_paper import ForwardPaperCoordinator
from paper_portfolio import FORWARD_FILL_POLICY, PaperAccountConfig, PaperPortfolio, PaperPortfolioError
from paper_triggers import ORB_FILL_POLICY
from storage import SQLitePersistenceStore


class TestPhase5BForwardPaper(unittest.TestCase):
    def setUp(self):
        from test_phase5a_paper import TestPhase5APaperPortfolio
        self.fixture = TestPhase5APaperPortfolio()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.paper = self.fixture._service(fill_policy=FORWARD_FILL_POLICY)
        self.coordinator = ForwardPaperCoordinator(self.paper)

    def _summary(self, candidate, run="offline-scan"):
        store = self.fixture.store
        store.save_signal(candidate, broker="OFFLINE SIMULATED", scan_run_id=run, now_ist=self.fixture.now)
        store.record_scan_run(run_id=run, started_at_ist="2026-10-16 10:00:00", completed_at_ist="2026-10-16 10:05:00",
            duration_ms=1, status="COMPLETED", broker="OFFLINE", data_mode=candidate.data_mode, is_simulated=candidate.is_simulated)
        return dict(run_id=run, scan_status="COMPLETED", persistence_status="OK", data_mode=candidate.data_mode,
                    signals=[candidate.to_dict()])

    def _consume(self, **bar_changes):
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        bar = self.fixture._bar(candidate, **bar_changes)
        return candidate, summary, bar, self.coordinator.consume_scan(summary, {candidate.symbol: [bar]})

    def _orb_fixture(self):
        from test_astra_paper_triggers import ORBScannerFixture
        self.fixture.delivery.stop()
        fixture = ORBScannerFixture(self)
        paper = PaperPortfolio(fixture.store, PaperAccountConfig(account_id="forward", run_id="offline",
            provider="angelone", source_data_mode="LIVE", fill_policy=ORB_FILL_POLICY), clock=lambda: fixture.now)
        guard = lambda: fixture.engine._require_current_scan_data("angelone", now_dt=fixture.now)
        return fixture, paper, ForwardPaperCoordinator(paper, entry_guard=guard)

    def _orb_ready(self, **settings):
        from test_astra_paper_triggers import ready_orb_trigger
        self.fixture.delivery.stop()
        return ready_orb_trigger(self, **settings)

    @staticmethod
    def _orb_consume(ready, paper=None):
        return ForwardPaperCoordinator(paper or ready.paper, entry_guard=ready.guard).consume_scan(
            ready.later, {ready.candidate["symbol"]: [ready.bar]})

    def test_forward_entry_uses_observed_close_with_full_candidate_and_risk_link(self):
        ready = self._orb_ready()
        result = self._orb_consume(ready)
        self.assertEqual(result["status"], "COMPLETED")
        report = result["report"]
        self.assertEqual(report["candidate_decisions"][0]["status"], "FILLED")
        position = report["positions"][0]
        self.assertEqual(position["raw_entry_price"], ready.bar["close"])
        self.assertEqual(position["fill_timestamp_ist"], "2026-10-16 11:50:00")
        self.assertEqual(position["candidate"], ready.candidate)
        self.assertEqual(position["trigger_evaluations"][-1]["status"], "TRIGGERED")
        self.assertTrue(position["risk_decision"]["eligible"])
        self.assertEqual(position["execution_mode"], "SIMULATED")
        self.assertEqual(report["candidate_decisions"][0]["source_scan_run_id"], ready.first["run_id"])
        self.assertEqual(report["reconciliation"]["status"], "OK")

    def test_duplicate_callbacks_and_restart_keep_one_fill_and_identical_accounting(self):
        ready = self._orb_ready()
        result = self._orb_consume(ready)
        first = result["report"]
        self.assertEqual(first["accounting"]["open_positions"], 1)
        self.assertEqual(sum(e["kind"] == "ENTRY" for e in first["events"]), 1)
        repeated = self._orb_consume(ready)["report"]
        self.assertEqual(first["accounting"], repeated["accounting"])
        self.assertEqual(first["total_events"], repeated["total_events"])
        recovered = SQLitePersistenceStore(ready.fixture.store.database_url)
        self.addCleanup(recovered.close)
        report = recovered.get_paper_portfolio_report(ready.paper.config.account_id, as_of=ready.fixture.now)
        self.assertEqual(report["accounting"], first["accounting"])
        self.assertEqual(len(report["candidate_decisions"]), 1)

    def test_queue_waits_for_actual_completed_next_observation_without_reservation(self):
        fixture, paper, coordinator = self._orb_fixture()
        summary = fixture.scan(paper)
        candidate = fixture.candidate(summary)
        waiting = coordinator.consume_scan(summary, {candidate["symbol"]: [fixture.retained_bar(summary)]})
        self.assertEqual(waiting["report"]["candidate_decisions"][0]["status"], "QUEUED")
        self.assertEqual(waiting["report"]["accounting"]["reserved_capital_inr"], 0)
        fixture.append_bar(open=102, high=102.3, low=101.5, close=102.2)
        not_triggered = fixture.scan(paper)["paper_portfolio"]["report"]
        self.assertEqual(not_triggered["accounting"]["open_positions"], 0)
        self.assertEqual(not_triggered["candidate_decisions"][0]["trigger_evaluations"][-1]["status"], "WAITING")
        fixture.append_bar(open=102.2, high=102.8, low=101.7, close=102.6)
        filled = fixture.scan(paper)["paper_portfolio"]["report"]
        self.assertEqual(filled["accounting"]["open_positions"], 1)

    def test_bad_batches_never_create_position_reservation_or_partial_entry(self):
        ready = self._orb_ready()
        good = ready.bar
        variants = ([good, good], [good, ready.fixture.retained_bar(ready.first)],
                    [dict(good, is_complete=False)], [dict(good, high=1)],
                    [dict(good, data_mode="SIMULATED", is_simulated=True)],
                    [dict(good, instrument_identity=dict(good["instrument_identity"], identifier="NSE_EQ|WRONG"))])
        for batch in variants:
            with self.subTest(batch=batch):
                result = ForwardPaperCoordinator(ready.paper, entry_guard=ready.guard).consume_scan(
                    ready.later, {ready.candidate["symbol"]: batch})
                self.assertEqual(result["report"]["accounting"]["reserved_capital_inr"], 0)
                self.assertEqual(result["report"]["positions"], [])
                self.assertEqual(result["report"]["total_events"], 0)
                decision = result["report"]["candidate_decisions"][0]
                if batch[0]["instrument_identity"] != good["instrument_identity"]:
                    self.assertEqual(decision["status"], "REJECTED")
                    self.assertEqual(decision["reason_code"], "BAR_INSTRUMENT_IDENTITY_MISMATCH")
                else:
                    self.assertEqual(decision["status"], "QUEUED")
                self.assertTrue(result["actions"])
                self.assertNotEqual(result["actions"][-1]["reason_code"], "CURRENT_SCANNER_GUARD_REQUIRED")

    def test_stale_required_bar_is_rejected_without_inventing_current_fill(self):
        ready = self._orb_ready()
        ready.fixture.scenario.now += timedelta(minutes=10)
        result = self._orb_consume(ready)
        self.assertEqual(result["report"]["candidate_decisions"][0]["status"], "REJECTED")
        self.assertEqual(result["report"]["candidate_decisions"][0]["reason_code"],
                         "TRIGGER_REQUIRED_OBSERVATION_WINDOW_EXPIRED")
        self.assertEqual(result["report"]["positions"], [])

    def test_mutated_or_unpersisted_candidate_is_audited_as_rejected(self):
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        summary["signals"][0]["rationale"] = "Changed after scanner persistence"
        result = self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate)]})
        self.assertEqual(result["report"]["candidate_decisions"][0]["reason_code"], "PERSISTED_CANDIDATE_CONFLICT")
        self.assertEqual(result["report"]["accounting"]["reserved_capital_inr"], 0)
        summary["signals"][0]["instrument_identity"]["source"] = "LOCAL_NORMALIZED_MASTER_DECLARATION"
        result = self.coordinator.consume_scan(summary, {})
        self.assertTrue(all(d["status"] == "REJECTED" for d in result["report"]["candidate_decisions"]))

    def test_partial_handoff_failure_recovers_committed_effect_before_new_market_checks(self):
        ready = self._orb_ready()
        coordinator = ForwardPaperCoordinator(ready.paper, entry_guard=ready.guard)
        with patch.object(coordinator, "_transition", side_effect=RuntimeError("OFFLINE crash after atomic fill")):
            with self.assertRaises(RuntimeError):
                coordinator.consume_scan(ready.later, {ready.candidate["symbol"]: [ready.bar]})
        first = ready.paper.snapshot()
        self.assertEqual(first["accounting"]["open_positions"], 1)
        ready.fixture.scenario.now += timedelta(minutes=10)
        recovered = ForwardPaperCoordinator(ready.paper).consume_scan(ready.later, {})["report"]
        self.assertEqual(recovered["candidate_decisions"][0]["status"], "FILLED")
        self.assertEqual(recovered["accounting"], first["accounting"])
        self.assertEqual(recovered["total_events"], first["total_events"])

    def test_close_fill_rejects_setup_invalidated_before_observation_close(self):
        fixture, paper, _ = self._orb_fixture()
        fixture.scan(paper)
        fixture.append_bar(open=102, high=102.8, low=100.5, close=102.6)
        result = fixture.scan(paper)["paper_portfolio"]
        self.assertEqual(result["report"]["candidate_decisions"][0]["reason_code"], "SETUP_INVALIDATED_BEFORE_CLOSE_FILL")
        self.assertEqual(result["report"]["positions"], [])

    def test_legacy_open_fill_cannot_spend_capital_released_later_in_same_bar(self):
        legacy = self.fixture._service(account_id="legacy")
        first, candidate = self.fixture._enter(legacy)
        self.fixture._set_time("10:15")
        legacy.process_bar(first["position_id"], self.fixture._bar(candidate, stamp="10:10", high=125), "exit")
        other = self.fixture._candidate(legacy, symbol="HDFCBANK", stamp="10:05")
        with self.assertRaises(PaperPortfolioError) as caught:
            legacy.enter(other, self.fixture._bar(other, stamp="10:10"), "later-open")
        self.assertEqual(caught.exception.reason_code, "CAPITAL_RELEASE_AFTER_ASSUMED_FILL")

    def test_scanner_runtime_queues_then_fills_marks_exits_and_recovers_real_wire_candidate(self):
        fixture, paper, _ = self._orb_fixture()
        engine = fixture.engine
        first = fixture.scan(paper)
        self.assertEqual(first["paper_portfolio"]["status"], "COMPLETED")
        report = first["paper_portfolio"]["report"]
        self.assertEqual(report["candidate_decisions"][0]["status"], "QUEUED")
        self.assertEqual(report["positions"], [])
        candidate = fixture.candidate(first)
        price = candidate["entry_price"]
        fixture.append_bar(open=price, high=102.8, low=101.7, close=102.6)
        second = fixture.scan(paper)
        self.assertEqual(second["paper_portfolio"]["report"]["accounting"]["open_positions"], 1)
        fixture.append_bar(open=102.6, high=candidate["target_1"] + 1, low=102.2, close=103)
        third = fixture.scan(paper)
        final = third["paper_portfolio"]["report"]
        self.assertEqual(final["accounting"]["closed_positions"], 1)
        self.assertEqual(final["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(final["reconciliation"]["status"], "OK")
        restarted = SQLitePersistenceStore(engine.store.database_url)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.get_paper_portfolio_report("forward", fixture.now)["accounting"], final["accounting"])
        self.assertIsNone(engine.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
        self.assertEqual(fixture.scenario.forbidden_requests, [])

    def test_decision_write_failure_rolls_back_fill_events_and_reservation_atomically(self):
        ready = self._orb_ready()
        store = ready.fixture.store
        with store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER decision_failure BEFORE UPDATE ON paper_candidate_decisions "
                         "WHEN json_extract(NEW.payload_json,'$.status')='FILLED' "
                         "BEGIN SELECT RAISE(ABORT,'OFFLINE decision failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self._orb_consume(ready)
        failed = ready.paper.snapshot()
        self.assertEqual(failed["positions"], [])
        self.assertEqual(failed["total_events"], 0)
        self.assertEqual(failed["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(failed["candidate_decisions"][0]["status"], "QUEUED")
        with store.paper_transaction() as conn:
            conn.execute("DROP TRIGGER decision_failure")
        retried = self._orb_consume(ready)
        self.assertEqual(retried["report"]["accounting"]["open_positions"], 1)

    def test_concurrent_legacy_manual_entries_cannot_spend_the_same_account_capital(self):
        # Legacy accounting remains supported; it supplies no automatic trigger.
        paper = self.fixture._service(account_id="concurrent-forward", fill_policy=FORWARD_FILL_POLICY,
                                      risk_pct=100, max_position_exposure_pct=100)
        other_store = SQLitePersistenceStore(self.fixture.database)
        self.addCleanup(other_store.close)
        other = PaperPortfolio(other_store, paper.config, clock=lambda: self.fixture.now)
        candidates = [self.fixture._candidate(paper, symbol=s) for s in ("RELIANCE", "HDFCBANK")]
        def enter(service, candidate):
            try:
                return service.enter(candidate, self.fixture._bar(candidate), "manual-" + candidate.symbol)["status"]
            except PaperPortfolioError as exc:
                return exc.reason_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(enter, service, candidate)
                       for service, candidate in zip((paper, other), candidates)]
            outcomes = [future.result() for future in futures]
        report = self.fixture.store.get_paper_portfolio_report(paper.config.account_id, self.fixture.now)
        self.assertEqual(report["accounting"]["open_positions"], 1)
        self.assertLessEqual(report["accounting"]["reserved_capital_inr"], paper.config.starting_capital_inr)
        self.assertEqual(outcomes.count("OPEN"), 1)
        self.assertEqual(report["candidate_decisions"], [])
        self.assertEqual(report["reconciliation"]["status"], "OK")

    def test_runtime_rejects_different_store_before_any_broker_transport(self):
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        scenario = TestPhase4OfflineEndToEnd()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        engine = scenario._engine("upstox")
        with self.assertRaises(ValueError):
            engine.run_single_scan(paper_portfolio=self.paper)
        wrong_mode = PaperPortfolio(engine.store, PaperAccountConfig(account_id="wrong-mode", run_id="offline",
            provider="upstox", source_data_mode="SIMULATED", fill_policy=FORWARD_FILL_POLICY), clock=lambda: scenario.now)
        with self.assertRaises(ValueError):
            engine.run_single_scan(paper_portfolio=wrong_mode)
        self.assertEqual(scenario.requests, [])

    def test_reporting_keeps_decisions_and_balances_in_one_concurrent_read_snapshot(self):
        ready = self._orb_ready()
        other_store = SQLitePersistenceStore(ready.fixture.store.database_url)
        self.addCleanup(other_store.close)
        writer = PaperPortfolio(other_store, ready.paper.config, clock=lambda: ready.fixture.now)
        original = PaperPortfolio._snapshot
        invoked = []
        def snapshot_then_concurrent_fill(instance, conn, now):
            report = original(instance, conn, now)
            if instance.store is ready.fixture.store and not invoked:
                invoked.append(True)
                writer.enter(ready.candidate, ready.bar, event_key=ready.decision_id, **ready.arguments)
            return report
        with patch.object(PaperPortfolio, "_snapshot", new=snapshot_then_concurrent_fill):
            report = ready.fixture.store.get_paper_portfolio_report(ready.paper.config.account_id, ready.fixture.now)
        self.assertTrue(invoked)
        self.assertEqual(report["accounting"]["open_positions"], 0)
        self.assertEqual(report["candidate_decisions"][0]["status"], "QUEUED")
        after = ready.paper.snapshot()
        self.assertEqual(after["accounting"]["open_positions"], 1)
        self.assertEqual(after["candidate_decisions"][0]["status"], "FILLED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
