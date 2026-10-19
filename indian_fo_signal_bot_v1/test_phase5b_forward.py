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

    def test_forward_entry_uses_observed_close_with_full_candidate_and_risk_link(self):
        candidate, summary, bar, result = self._consume()
        self.assertEqual(result["status"], "COMPLETED")
        report = result["report"]
        self.assertEqual(report["candidate_decisions"][0]["status"], "FILLED")
        position = report["positions"][0]
        self.assertEqual(position["raw_entry_price"], bar["close"])
        self.assertEqual(position["fill_timestamp_ist"], "2026-10-16 10:10:00")
        self.assertEqual(position["candidate"], candidate.to_dict())
        self.assertTrue(position["risk_decision"]["eligible"])
        self.assertEqual(position["execution_mode"], "SIMULATED")
        self.assertEqual(report["candidate_decisions"][0]["source_scan_run_id"], summary["run_id"])
        self.assertEqual(report["reconciliation"]["status"], "OK")

    def test_duplicate_callbacks_and_restart_keep_one_fill_and_identical_accounting(self):
        candidate, summary, bar, result = self._consume()
        first = result["report"]
        repeated = self.coordinator.consume_scan(summary, {candidate.symbol: [bar]})["report"]
        self.assertEqual(first["accounting"], repeated["accounting"])
        self.assertEqual(first["total_events"], repeated["total_events"])
        recovered = SQLitePersistenceStore(self.fixture.database)
        self.addCleanup(recovered.close)
        report = recovered.get_paper_portfolio_report(self.paper.config.account_id, as_of=self.fixture.now)
        self.assertEqual(report["accounting"], first["accounting"])
        self.assertEqual(len(report["candidate_decisions"]), 1)

    def test_queue_waits_for_actual_completed_next_observation_without_reservation(self):
        self.fixture._set_time("10:05")
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        waiting = self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate, stamp="10:00")]})
        self.assertEqual(waiting["report"]["candidate_decisions"][0]["status"], "QUEUED")
        self.assertEqual(waiting["report"]["accounting"]["reserved_capital_inr"], 0)
        self.fixture._set_time("10:10")
        filled = self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate)]})
        self.assertEqual(filled["report"]["accounting"]["open_positions"], 1)

    def test_bad_batches_never_create_position_reservation_or_partial_entry(self):
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        good = self.fixture._bar(candidate)
        variants = ([good, good], [good, self.fixture._bar(candidate, stamp="10:00")],
                    [dict(good, is_complete=False)], [dict(good, high=1)],
                    [dict(good, data_mode="LIVE", is_simulated=False)],
                    [dict(good, instrument_identity=dict(good["instrument_identity"], identifier="NSE_EQ|WRONG"))])
        for batch in variants:
            with self.subTest(batch=batch):
                result = self.coordinator.consume_scan(summary, {candidate.symbol: batch})
                self.assertEqual(result["report"]["accounting"]["reserved_capital_inr"], 0)
                self.assertEqual(result["report"]["positions"], [])
                self.assertEqual(result["report"]["total_events"], 0)

    def test_stale_required_bar_is_rejected_without_inventing_current_fill(self):
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        self.fixture._set_time("10:20")
        result = self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate)]})
        self.assertEqual(result["report"]["candidate_decisions"][0]["status"], "REJECTED")
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
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        with patch.object(self.coordinator, "_transition", side_effect=RuntimeError("OFFLINE crash after atomic fill")):
            with self.assertRaises(RuntimeError):
                self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate)]})
        first = self.paper.snapshot()
        self.assertEqual(first["accounting"]["open_positions"], 1)
        self.fixture._set_time("10:20")
        recovered = ForwardPaperCoordinator(self.paper).consume_scan(summary, {})["report"]
        self.assertEqual(recovered["candidate_decisions"][0]["status"], "FILLED")
        self.assertEqual(recovered["accounting"], first["accounting"])
        self.assertEqual(recovered["total_events"], first["total_events"])

    def test_close_fill_rejects_setup_invalidated_before_observation_close(self):
        _, _, _, result = self._consume(low=89)
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
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        scenario = TestPhase4OfflineEndToEnd()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        # Reuse Phase4's native five-minute Angel wire fixture, not injected signals.
        engine = scenario._engine("angelone", database="forward.sqlite")
        paper = PaperPortfolio(engine.store, PaperAccountConfig(account_id="forward", run_id="offline",
            provider="angelone", source_data_mode="LIVE", fill_policy=FORWARD_FILL_POLICY), clock=lambda: scenario.now)
        # Existing paper fixture forbids every dispatcher; scanner is permitted
        # to execute its genuine dry-run formatting branch during this scenario.
        self.fixture.delivery.stop()
        first = engine.run_single_scan(paper_portfolio=paper)
        self.assertEqual(first["paper_portfolio"]["status"], "COMPLETED")
        report = first["paper_portfolio"]["report"]
        self.assertEqual(report["candidate_decisions"][0]["status"], "QUEUED")
        self.assertEqual(report["positions"], [])
        candidate = first["signals"][0]
        price = candidate["entry_price"]
        scenario.batches["angelone"][-1].update(open=price, high=price + .2, low=price - .2, close=price + .1, volume=10000)
        scenario.now += timedelta(minutes=5)
        second = engine.run_single_scan(paper_portfolio=paper)
        self.assertEqual(second["paper_portfolio"]["report"]["accounting"]["open_positions"], 1)
        scenario.batches["angelone"].append(dict(timestamp="2026-10-16T14:20:00+05:30", open=price,
            high=candidate["target_1"] + 1, low=price - .1, close=price, volume=10000))
        scenario.now += timedelta(minutes=5)
        third = engine.run_single_scan(paper_portfolio=paper)
        final = third["paper_portfolio"]["report"]
        self.assertEqual(final["accounting"]["closed_positions"], 1)
        self.assertEqual(final["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(final["reconciliation"]["status"], "OK")
        restarted = SQLitePersistenceStore(engine.store.database_url)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.get_paper_portfolio_report("forward", scenario.now)["accounting"], final["accounting"])
        self.assertIsNone(engine.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
        self.assertEqual(scenario.forbidden_requests, [])

    def test_decision_write_failure_rolls_back_fill_events_and_reservation_atomically(self):
        candidate = self.fixture._candidate(self.paper)
        summary = self._summary(candidate)
        with self.fixture.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER decision_failure BEFORE UPDATE ON paper_candidate_decisions "
                         "WHEN json_extract(NEW.payload_json,'$.status')='FILLED' "
                         "BEGIN SELECT RAISE(ABORT,'OFFLINE decision failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate)]})
        failed = self.fixture.store.get_paper_portfolio_report("account", self.fixture.now)
        self.assertEqual(failed["positions"], [])
        self.assertEqual(failed["total_events"], 0)
        self.assertEqual(failed["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(failed["candidate_decisions"][0]["status"], "QUEUED")
        with self.fixture.store.paper_transaction() as conn:
            conn.execute("DROP TRIGGER decision_failure")
        retried = self.coordinator.consume_scan(summary, {candidate.symbol: [self.fixture._bar(candidate)]})
        self.assertEqual(retried["report"]["accounting"]["open_positions"], 1)

    def test_concurrent_coordinators_cannot_spend_the_same_account_capital(self):
        paper = self.fixture._service(account_id="concurrent-forward", fill_policy=FORWARD_FILL_POLICY,
                                      risk_pct=100, max_position_exposure_pct=100)
        other_store = SQLitePersistenceStore(self.fixture.database)
        self.addCleanup(other_store.close)
        other = PaperPortfolio(other_store, paper.config, clock=lambda: self.fixture.now)
        candidates = [self.fixture._candidate(paper, symbol=s) for s in ("RELIANCE", "HDFCBANK")]
        summaries = [self._summary(candidate, run="scan-" + str(i)) for i, candidate in enumerate(candidates)]
        observations = {candidate.symbol: [self.fixture._bar(candidate)] for candidate in candidates}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(ForwardPaperCoordinator(service).consume_scan, summary, observations)
                       for service, summary in zip((paper, other), summaries)]
            for future in futures:
                self.assertEqual(future.result()["status"], "COMPLETED")
        report = self.fixture.store.get_paper_portfolio_report(paper.config.account_id, self.fixture.now)
        self.assertEqual(report["accounting"]["open_positions"], 1)
        self.assertLessEqual(report["accounting"]["reserved_capital_inr"], paper.config.starting_capital_inr)
        self.assertEqual(sorted(d["status"] for d in report["candidate_decisions"]), ["FILLED", "REJECTED"])
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
        candidate = self.fixture._candidate(self.paper)
        self.coordinator._queue(self._summary(candidate))
        with self.fixture.store.paper_transaction(write=False) as conn:
            candidate_id = conn.execute("SELECT candidate_id FROM paper_candidate_decisions").fetchone()[0]
        other_store = SQLitePersistenceStore(self.fixture.database)
        self.addCleanup(other_store.close)
        writer = PaperPortfolio(other_store, self.paper.config, clock=lambda: self.fixture.now)
        original = PaperPortfolio._snapshot
        invoked = []
        def snapshot_then_concurrent_fill(instance, conn, now):
            report = original(instance, conn, now)
            if instance.store is self.fixture.store and not invoked:
                invoked.append(True)
                writer.enter(candidate, self.fixture._bar(candidate), event_key=candidate_id,
                             candidate_decision_id=candidate_id)
            return report
        with patch.object(PaperPortfolio, "_snapshot", new=snapshot_then_concurrent_fill):
            report = self.fixture.store.get_paper_portfolio_report("account", self.fixture.now)
        self.assertTrue(invoked)
        self.assertEqual(report["accounting"]["open_positions"], 0)
        self.assertEqual(report["candidate_decisions"][0]["status"], "QUEUED")
        after = self.fixture.store.get_paper_portfolio_report("account", self.fixture.now)
        self.assertEqual(after["accounting"]["open_positions"], 1)
        self.assertEqual(after["candidate_decisions"][0]["status"], "FILLED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
