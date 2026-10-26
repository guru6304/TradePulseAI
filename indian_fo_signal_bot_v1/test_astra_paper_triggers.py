"""OFFLINE SIMULATION: genuine scanner ORB detection and retained future inputs.

The wire payloads are synthetic and establish software behavior only. The
evaluators, qualification, persistence and lineage loaders run unchanged.
"""
import copy
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from strategies import IST, parse_ist_timestamp, signal_state_identity


class ORBScannerFixture:
    """Real scanner with isolated SQLite and fixture-only Angel HTTP responses.

    ``scan`` accepts the ordinary optional PaperPortfolio. ``append_bar`` advances
    the mutable clock to five seconds after that bar completes. ``retained_bar``
    returns the scanner's persisted qualified input, including identity and
    provenance; callers must not substitute raw fixture rows for this contract.
    """
    def __init__(self, owner, side="LONG"):
        if side not in ("LONG", "SHORT"):
            raise ValueError("Fixture side must be LONG or SHORT")
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        self.scenario = TestPhase4OfflineEndToEnd()
        self.scenario.setUp()
        owner.addCleanup(self.scenario.doCleanups)
        owner.addCleanup(self.scenario.tearDown)
        self.side = side
        self.scenario.now = datetime(2026, 10, 16, 11, 45, 5, tzinfo=IST)
        self.engine = self.scenario._engine("angelone", database="orb_trigger.sqlite")
        self.store = self.engine.store
        start = self.now.replace(hour=9, minute=15, second=0)
        self.bars = []
        for index in range(30):
            # Flat warm-up has no Order Block impulse/FVG. The last candle is
            # the first completed opening-range breakout, with 5x prior RVOL.
            row = dict(timestamp=(start + timedelta(minutes=5 * index)).isoformat(),
                open=100.0, high=101.0 if index < 3 else 100.4,
                low=99.0 if index < 3 else 99.6, close=100.0, volume=1000)
            if index == 29:
                row.update(open=100.0, high=102.4, low=99.8, close=102.0, volume=5000)
            if side == "SHORT":
                row.update(open=200 - row["open"], high=200 - row["low"],
                           low=200 - row["high"], close=200 - row["close"])
            self.bars.append(row)
        self.scenario.batches["angelone"] = self.bars

    @property
    def now(self):
        return self.scenario.now

    def scan(self, paper=None):
        return self.engine.run_single_scan(paper_portfolio=paper)

    def append_bar(self, *, open, high, low, close, volume=1000):
        stamp = parse_ist_timestamp(self.bars[-1]["timestamp"]) + timedelta(minutes=5)
        row = dict(timestamp=stamp.isoformat(), open=open, high=high, low=low,
                   close=close, volume=volume)
        self.bars.append(row)
        self.scenario.now = stamp + timedelta(minutes=5, seconds=5)
        return copy.deepcopy(row)

    def work(self, summary):
        return self.store.load_cash_scan(summary["run_id"])

    def retained_bar(self, summary, index=-1):
        return copy.deepcopy(self.work(summary)["snapshot"]["batches"][0]["content"]["candles"][index])

    @staticmethod
    def candidate(summary):
        matches = [s for s in summary["signals"] if s["strategy_id"] == "strat_4_orb_filtered"]
        if len(matches) != 1:
            raise AssertionError("Fixture must produce exactly one evaluated ORB candidate")
        return copy.deepcopy(matches[0])


def ready_orb_trigger(owner, side="LONG", **settings):
    """Qualified retained trigger; no financial ENTRY has occurred yet."""
    from types import SimpleNamespace
    from paper_portfolio import PaperAccountConfig, PaperPortfolio
    from paper_triggers import ORB_FILL_POLICY
    fixture = ORBScannerFixture(owner, side)
    defaults = dict(account_id="orb-prospective", run_id="offline", provider="angelone",
        source_data_mode="LIVE", fill_policy=ORB_FILL_POLICY)
    defaults.update(settings)
    paper = PaperPortfolio(fixture.store, PaperAccountConfig(**defaults), clock=lambda: fixture.now)
    first = fixture.scan(paper)
    candidate = fixture.candidate(first)
    values = dict(open=102, high=102.8, low=101.7, close=102.6) if side == "LONG" else dict(
        open=98, high=98.3, low=97.2, close=97.4)
    fixture.append_bar(**values)
    later = fixture.scan()
    bar = fixture.retained_bar(later)
    decision = paper.snapshot()["candidate_decisions"][0]
    paper.observe_candidate(decision["candidate_id"], bar, later["run_id"])
    guard = lambda: fixture.engine._require_current_scan_data("angelone", now_dt=fixture.now)
    arguments = dict(candidate_decision_id=decision["candidate_id"], source_scan_run_id=later["run_id"], entry_guard=guard)
    return SimpleNamespace(fixture=fixture, paper=paper, first=first, later=later, candidate=candidate,
        bar=bar, decision_id=decision["candidate_id"], arguments=arguments, guard=guard)


class TestAstraORBScannerFixture(unittest.TestCase):
    def test_long_and_short_orb_candidates_have_committed_rule_and_input_lineage(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                fixture = ORBScannerFixture(self, side)
                first = fixture.scan()
                self.assertEqual(first["scan_status"], "COMPLETED")
                candidate = fixture.candidate(first)
                self.assertEqual(candidate["position_type"], side + "_EQUITY_INTRADAY")
                work = fixture.work(first)
                self.assertEqual(work["status"], "COMMITTED")
                self.assertIn(candidate, work["result"]["signals"])
                batch = work["snapshot"]["batches"][0]
                self.assertEqual(len(batch["content"]["candles"]), 30)
                self.assertEqual(batch["content"]["identity"], candidate["instrument_identity"])
                self.assertEqual(fixture.retained_bar(first)["close"], candidate["entry_price"])
                evaluation = fixture.store.load_scan_evaluations(first["run_id"])
                record = next(c for c in evaluation["candidate_evaluations"]
                              if c["candidate_id"] == signal_state_identity(candidate)[0])
                self.assertEqual(record["status"], "QUALIFIED")
                self.assertTrue(record["ranking"]["qualified"])
                trace = record["explanation"]["rule_evaluation"]
                self.assertEqual(trace["status"], "DETECTED")
                self.assertIn(trace, evaluation["strategy_evaluations"])
                self.assertEqual(record["source_reference"]["batch_ids"], [batch["batch_id"]])
                self.assertIsNone(fixture.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
                # Close each transport fixture before constructing the next,
                # avoiding nested provider mocks across subtests.
                fixture.scenario.tearDown()
                fixture.scenario.doCleanups()

    def test_later_completed_input_is_a_distinct_committed_scanner_run(self):
        fixture = ORBScannerFixture(self)
        first = fixture.scan()
        candidate = fixture.candidate(first)
        fixture.append_bar(open=102.0, high=102.3, low=101.5, close=102.2)
        second = fixture.scan()
        self.assertEqual(second["scan_status"], "COMPLETED_EMPTY")
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(fixture.work(second)["status"], "COMMITTED")
        bar = fixture.retained_bar(second)
        self.assertEqual(bar["instrument_identity"], candidate["instrument_identity"])
        self.assertTrue(bar["is_complete"])
        self.assertEqual(bar["interval_min"], 5)
        self.assertEqual(parse_ist_timestamp(bar["timestamp"]),
                         parse_ist_timestamp(candidate["timestamp"]) + timedelta(minutes=5))
        self.assertEqual((fixture.now - parse_ist_timestamp(bar["timestamp"])).total_seconds(), 305)


class TestAstraPaperTriggers(unittest.TestCase):
    def _service(self, fixture):
        from paper_portfolio import PaperAccountConfig, PaperPortfolio
        from paper_triggers import ORB_FILL_POLICY
        return PaperPortfolio(fixture.store, PaperAccountConfig(account_id="orb-prospective", run_id="offline",
            provider="angelone", source_data_mode="LIVE", fill_policy=ORB_FILL_POLICY), clock=lambda: fixture.now)

    def _queued(self, side="LONG"):
        fixture = ORBScannerFixture(self, side)
        paper = self._service(fixture)
        first = fixture.scan(paper)
        candidate = fixture.candidate(first)
        report = first["paper_portfolio"]["report"]
        self.assertEqual(report["candidate_decisions"][0]["status"], "QUEUED")
        self.assertNoEntry(report)
        return fixture, paper, first, candidate

    @staticmethod
    def _decision(paper):
        return paper.snapshot()["candidate_decisions"][0]

    def assertNoEntry(self, report):
        self.assertEqual(report["positions"], [])
        self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
        self.assertFalse(any(e["kind"] == "ENTRY" for e in report["events"]))

    def _later(self, fixture, paper=None, *, crossed=False):
        if fixture.side == "LONG":
            values = dict(open=102.2, high=102.8, low=101.7, close=102.6) if crossed else dict(
                open=102, high=102.3, low=101.5, close=102.2)
        else:
            values = dict(open=97.8, high=98.3, low=97.2, close=97.4) if crossed else dict(
                open=98, high=98.5, low=97.7, close=97.8)
        fixture.append_bar(**values)
        return fixture.scan(paper)

    def test_long_waits_for_future_cross_then_fills_once_at_observed_close(self):
        from forward_paper import ForwardPaperCoordinator
        fixture, paper, first, candidate = self._queued()
        waiting = self._later(fixture, paper)
        report = waiting["paper_portfolio"]["report"]
        self.assertNoEntry(report)
        self.assertEqual(self._decision(paper)["trigger_evaluations"][-1]["status"], "WAITING")
        crossed = self._later(fixture, paper, crossed=True)
        report = crossed["paper_portfolio"]["report"]
        decision = self._decision(paper)
        self.assertEqual(decision["status"], "FILLED")
        self.assertEqual([e["status"] for e in decision["trigger_evaluations"]], ["WAITING", "TRIGGERED"])
        self.assertEqual(report["positions"][0]["raw_entry_price"], 102.6)
        self.assertEqual(report["positions"][0]["fill_timestamp_ist"], "2026-10-16 11:55:00")
        self.assertEqual(report["positions"][0]["candidate"], candidate)
        repeated = ForwardPaperCoordinator(paper).consume_scan(crossed, {candidate["symbol"]: [fixture.retained_bar(crossed)]})["report"]
        self.assertEqual(repeated["accounting"], report["accounting"])
        self.assertEqual(repeated["total_events"], report["total_events"])
        self.assertEqual(repeated["reconciliation"]["status"], "OK")

    def test_short_uses_frozen_signal_low_and_strict_future_downward_cross(self):
        fixture, paper, _, _ = self._queued("SHORT")
        self.assertEqual(self._decision(paper)["trigger_contract"]["threshold"], 97.6)
        waiting = self._later(fixture, paper)
        self.assertNoEntry(waiting["paper_portfolio"]["report"])
        crossed = self._later(fixture, paper, crossed=True)
        self.assertEqual(self._decision(paper)["status"], "FILLED")
        self.assertEqual(crossed["paper_portfolio"]["report"]["positions"][0]["raw_entry_price"], 97.4)

    def test_threshold_touch_waits_until_a_later_strict_close_cross(self):
        fixture, paper, _, _ = self._queued()
        fixture.append_bar(open=102, high=102.5, low=101.6, close=102.4)
        waiting = fixture.scan(paper)
        self.assertNoEntry(waiting["paper_portfolio"]["report"])
        self.assertEqual(self._decision(paper)["trigger_evaluations"][-1]["status"], "WAITING")
        crossed = self._later(fixture, paper, crossed=True)
        self.assertEqual(crossed["paper_portfolio"]["report"]["candidate_decisions"][0]["status"], "FILLED")

    def test_four_fresh_nontriggering_bars_do_not_create_an_arbitrary_three_bar_expiry(self):
        fixture, paper, _, _ = self._queued()
        for _ in range(4):
            waiting = self._later(fixture, paper)
            self.assertNoEntry(waiting["paper_portfolio"]["report"])
            self.assertEqual(self._decision(paper)["status"], "QUEUED")
        self.assertEqual(len(self._decision(paper)["trigger_evaluations"]), 4)
        crossed = self._later(fixture, paper, crossed=True)
        self.assertEqual(crossed["paper_portfolio"]["report"]["candidate_decisions"][0]["status"], "FILLED")

    def test_direct_entry_cannot_bypass_durable_observation_even_when_price_crossed(self):
        from paper_portfolio import PaperPortfolioError
        fixture, paper, _, candidate = self._queued()
        later = self._later(fixture, crossed=True)
        bar, decision = fixture.retained_bar(later), self._decision(paper)
        for arguments in ({}, dict(candidate_decision_id=decision["candidate_id"], source_scan_run_id=later["run_id"])):
            with self.subTest(arguments=arguments), self.assertRaises(PaperPortfolioError):
                paper.enter(candidate, bar, decision["candidate_id"], **arguments)
            self.assertNoEntry(paper.snapshot())

    def test_missing_intervening_observation_cannot_jump_directly_to_a_later_cross(self):
        from forward_paper import ForwardPaperCoordinator
        fixture, paper, _, candidate = self._queued()
        self._later(fixture)
        later = self._later(fixture, crossed=True)
        coordinator = ForwardPaperCoordinator(paper, entry_guard=lambda: fixture.engine._require_current_scan_data("angelone", now_dt=fixture.now))
        report = coordinator.consume_scan(later, {candidate["symbol"]: [fixture.retained_bar(later)]})["report"]
        self.assertNoEntry(report)
        self.assertEqual(report["candidate_decisions"][0]["reason_code"], "TRIGGER_REQUIRED_OBSERVATION_WINDOW_EXPIRED")

    def test_stale_crossing_observation_cannot_become_a_historical_fill(self):
        from forward_paper import ForwardPaperCoordinator
        fixture, paper, _, candidate = self._queued()
        later = self._later(fixture, crossed=True)
        fixture.scenario.now += timedelta(minutes=2)
        coordinator = ForwardPaperCoordinator(paper, entry_guard=lambda: fixture.engine._require_current_scan_data("angelone", now_dt=fixture.now))
        report = coordinator.consume_scan(later, {candidate["symbol"]: [fixture.retained_bar(later)]})["report"]
        self.assertNoEntry(report)
        self.assertEqual(report["candidate_decisions"][0]["reason_code"], "TRIGGER_REQUIRED_OBSERVATION_WINDOW_EXPIRED")

    def test_range_invalidation_before_cross_prohibits_entry(self):
        fixture, paper, _, _ = self._queued()
        fixture.append_bar(open=102, high=102.8, low=100.9, close=102.6)
        result = fixture.scan(paper)
        self.assertNoEntry(result["paper_portfolio"]["report"])
        self.assertEqual(self._decision(paper)["status"], "REJECTED")
        self.assertEqual(self._decision(paper)["trigger_evaluations"][-1]["status"], "INVALIDATED")

    def test_target_already_touched_before_close_prohibits_entry(self):
        fixture, paper, _, candidate = self._queued()
        fixture.append_bar(open=102, high=candidate["target_1"] + 0.1, low=101.8, close=102.6)
        result = fixture.scan(paper)
        self.assertNoEntry(result["paper_portfolio"]["report"])
        self.assertEqual(self._decision(paper)["status"], "REJECTED")

    def test_supplied_bar_must_equal_retained_scanner_input(self):
        from paper_portfolio import PaperPortfolioError
        fixture, paper, _, _ = self._queued()
        later = self._later(fixture, crossed=True)
        bar, decision = fixture.retained_bar(later), self._decision(paper)
        bar["close"] += 0.01
        with self.assertRaises(PaperPortfolioError):
            paper.observe_candidate(decision["candidate_id"], bar, later["run_id"])
        self.assertNoEntry(paper.snapshot())

    def test_observation_must_reference_a_real_committed_run(self):
        from paper_portfolio import PaperPortfolioError
        fixture, paper, _, _ = self._queued()
        later = self._later(fixture, crossed=True)
        with self.assertRaises(PaperPortfolioError):
            paper.observe_candidate(self._decision(paper)["candidate_id"], fixture.retained_bar(later), "never-committed-run")
        self.assertNoEntry(paper.snapshot())

    def test_tampered_trigger_contract_cannot_authorize_entry(self):
        from paper_portfolio import PaperPortfolioError
        fixture, paper, _, candidate = self._queued()
        later = self._later(fixture, crossed=True)
        decision = self._decision(paper)
        paper.observe_candidate(decision["candidate_id"], fixture.retained_bar(later), later["run_id"])
        decision = self._decision(paper)
        decision["trigger_contract"]["threshold"] = 100.0
        with fixture.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                         (json.dumps(decision), decision["candidate_id"]))
        with self.assertRaises(PaperPortfolioError):
            paper.enter(candidate, fixture.retained_bar(later), decision["candidate_id"],
                candidate_decision_id=decision["candidate_id"], source_scan_run_id=later["run_id"])
        self.assertNoEntry(paper.snapshot())

    def test_tampered_waiting_observation_is_replayed_before_transactional_entry(self):
        from paper_portfolio import PaperPortfolioError
        fixture, paper, _, candidate = self._queued()
        later = self._later(fixture)
        decision = self._decision(paper)
        paper.observe_candidate(decision["candidate_id"], fixture.retained_bar(later), later["run_id"])
        decision = self._decision(paper)
        decision["trigger_evaluations"][-1]["status"] = "TRIGGERED"
        decision["trigger_evaluations"][-1]["close"] = 103.0
        with fixture.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                         (json.dumps(decision), decision["candidate_id"]))
        with self.assertRaises(PaperPortfolioError):
            paper.enter(candidate, fixture.retained_bar(later), decision["candidate_id"],
                candidate_decision_id=decision["candidate_id"], source_scan_run_id=later["run_id"])
        self.assertNoEntry(paper.snapshot())

    def test_other_genuinely_detected_strategy_has_no_implicit_orb_future_rule(self):
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        scenario = TestPhase4OfflineEndToEnd()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        self.addCleanup(scenario.tearDown)
        engine = scenario._engine("angelone", database="unsupported_orb.sqlite")
        from paper_portfolio import PaperAccountConfig, PaperPortfolio
        from paper_triggers import ORB_FILL_POLICY
        paper = PaperPortfolio(engine.store, PaperAccountConfig(account_id="unsupported-orb", run_id="offline",
            provider="angelone", source_data_mode="LIVE", fill_policy=ORB_FILL_POLICY), clock=lambda: scenario.now)
        result = engine.run_single_scan(paper_portfolio=paper)
        self.assertEqual(result["signals"][0]["strategy_id"], "strat_1_order_block")
        report = result["paper_portfolio"]["report"]
        self.assertNoEntry(report)
        self.assertEqual(report["candidate_decisions"][0]["status"], "REJECTED")
        self.assertEqual(report["candidate_decisions"][0]["reason_code"], "STRATEGY_FUTURE_TRIGGER_UNAVAILABLE")


class TestAstraPaperTriggerBoundaries(unittest.TestCase):
    def assertNoFinancialEffect(self, paper):
        report = paper.snapshot()
        self.assertEqual(report["positions"], [])
        self.assertEqual(report["events"], [])
        self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(report["candidate_decisions"][0]["status"], "QUEUED")

    def test_decision_identity_fields_cannot_be_rebound_to_a_valid_trigger(self):
        from paper_portfolio import PaperPortfolioError
        ready = ready_orb_trigger(self)
        original = ready.paper.snapshot()["candidate_decisions"][0]
        for field in ("candidate_id", "signal_key", "run_id"):
            with self.subTest(field=field):
                altered = dict(original, **{field: "wrong-identity"})
                with ready.fixture.store.paper_transaction() as conn:
                    conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                                 (json.dumps(altered), ready.decision_id))
                with self.assertRaises(PaperPortfolioError) as caught:
                    ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
                self.assertIn(caught.exception.reason_code,
                              ("PAPER_DECISION_NOT_ELIGIBLE", "PAPER_TRIGGER_DECISION_IDENTITY_MISMATCH"))
                self.assertNoFinancialEffect(ready.paper)

    def test_current_code_mismatch_blocks_a_retained_prospective_trigger(self):
        from paper_portfolio import PaperPortfolioError
        ready = ready_orb_trigger(self)
        with patch("paper_triggers.code_fingerprint", return_value="new-code"), self.assertRaises(PaperPortfolioError) as caught:
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(caught.exception.reason_code, "TRIGGER_DETECTION_CODE_CHANGED")
        self.assertNoFinancialEffect(ready.paper)

    def test_valid_durable_trigger_still_requires_current_scanner_guard(self):
        from paper_portfolio import PaperPortfolioError
        ready = ready_orb_trigger(self)
        with self.assertRaises(PaperPortfolioError) as caught:
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id,
                             **dict(ready.arguments, entry_guard=None))
        self.assertEqual(caught.exception.reason_code, "CURRENT_SCANNER_GUARD_REQUIRED")
        self.assertNoFinancialEffect(ready.paper)

    def test_stream_degradation_between_observation_and_entry_blocks_effect(self):
        from brokers import CandleFreshnessError
        ready = ready_orb_trigger(self)
        adapter = ready.fixture.engine.broker.get_active_adapter()
        with patch.object(adapter, "live_feed", object()), patch.object(adapter, "get_feed_status",
                return_value={"live_signal_allowed": False}), self.assertRaises(CandleFreshnessError):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertNoFinancialEffect(ready.paper)

    def test_stream_degradation_after_staged_mark_rolls_back_entire_entry(self):
        from brokers import CandleFreshnessError
        ready = ready_orb_trigger(self)
        adapter = ready.fixture.engine.broker.get_active_adapter()
        status = {"live_signal_allowed": True}
        original = ready.paper._event
        def degrade_after_mark(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[2] == "MARK":
                status["live_signal_allowed"] = False
            return result
        with patch.object(adapter, "live_feed", object()), patch.object(adapter, "get_feed_status", side_effect=lambda: dict(status)), \
                patch.object(ready.paper, "_event", side_effect=degrade_after_mark), self.assertRaises(CandleFreshnessError):
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertFalse(status["live_signal_allowed"])
        self.assertNoFinancialEffect(ready.paper)

    def test_clock_expiry_after_staged_mark_rolls_back_entire_entry(self):
        from paper_portfolio import PaperPortfolioError
        ready = ready_orb_trigger(self)
        original = ready.paper._event
        def advance_after_mark(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[2] == "MARK":
                ready.fixture.scenario.now += timedelta(minutes=2)
            return result
        with patch.object(ready.paper, "_event", side_effect=advance_after_mark), self.assertRaises(PaperPortfolioError) as caught:
            ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(caught.exception.reason_code, "INVALID_STALE_OR_UNFINISHED_BAR")
        self.assertNoFinancialEffect(ready.paper)

    def test_recovery_rejects_trigger_timestamp_tamper_without_replaying_effect(self):
        from forward_paper import ForwardPaperCoordinator
        from paper_portfolio import PaperPortfolioError
        ready = ready_orb_trigger(self)
        ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        before = ready.paper.snapshot()
        decision = copy.deepcopy(before["candidate_decisions"][0])
        decision["trigger_timestamp_ist"] = "2026-10-16 11:55:00"
        with ready.fixture.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                         (json.dumps(decision), ready.decision_id))
        with self.assertRaises(PaperPortfolioError) as caught:
            ForwardPaperCoordinator(ready.paper)._transition(ready.decision_id, "FILLED", "RETRY")
        self.assertEqual(caught.exception.reason_code, "PAPER_RECOVERY_TRIGGER_CONFLICT")
        after = ready.paper.snapshot()
        self.assertEqual(after["events"], before["events"])
        self.assertEqual(after["accounting"], before["accounting"])

    def test_recovery_rejects_corrupted_decision_identity_even_with_committed_entry(self):
        from forward_paper import ForwardPaperCoordinator
        from paper_portfolio import PaperPortfolioError
        ready = ready_orb_trigger(self)
        ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        before = ready.paper.snapshot()
        original = before["candidate_decisions"][0]
        for field in ("candidate_id", "signal_key", "run_id", "account_id", "config_hash", "candidate_hash"):
            with self.subTest(field=field):
                changed = dict(original, **{field: "corrupted"})
                with ready.fixture.store.paper_transaction() as conn:
                    conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE candidate_id=?",
                                 (json.dumps(changed), ready.decision_id))
                with self.assertRaises(PaperPortfolioError) as caught:
                    ForwardPaperCoordinator(ready.paper)._transition(ready.decision_id, "FILLED", "RETRY")
                self.assertEqual(caught.exception.reason_code, "PAPER_RECOVERY_DECISION_CONFLICT")
                after = ready.paper.snapshot()
                self.assertEqual(after["events"], before["events"])
                self.assertEqual(after["accounting"], before["accounting"])

    def test_concurrent_coordinators_consume_one_trigger_without_duplicate_entry(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from forward_paper import ForwardPaperCoordinator
        from paper_portfolio import PaperPortfolio
        from storage import SQLitePersistenceStore
        ready = ready_orb_trigger(self)
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
            results = [executor.submit(consume) for _ in range(2)]
            for result in results:
                self.assertEqual(result.result(timeout=30)["status"], "COMPLETED")
        after = ready.paper.snapshot()
        self.assertEqual(len(after["positions"]), 1)
        self.assertEqual(sum(event["kind"] == "ENTRY" for event in after["events"]), 1)
        self.assertEqual(after["candidate_decisions"][0]["status"], "FILLED")
        self.assertEqual(after["accounting"]["reserved_capital_inr"], after["positions"][0]["reserved_capital_inr"])
        self.assertEqual(after["reconciliation"]["status"], "OK")

    def test_legacy_automatic_policy_rejects_new_decisions_and_direct_decision_entry(self):
        from paper_portfolio import FORWARD_FILL_POLICY, PaperAccountConfig, PaperPortfolio, PaperPortfolioError
        fixture = ORBScannerFixture(self)
        paper = PaperPortfolio(fixture.store, PaperAccountConfig(account_id="legacy-automatic", run_id="offline",
            provider="angelone", source_data_mode="LIVE", fill_policy=FORWARD_FILL_POLICY), clock=lambda: fixture.now)
        first = fixture.scan(paper)
        decision = paper.snapshot()["candidate_decisions"][0]
        self.assertEqual(decision["status"], "REJECTED")
        self.assertEqual(decision["reason_code"], "LEGACY_AUTOMATIC_TRIGGER_UNSUPPORTED")
        fixture.append_bar(open=102, high=102.3, low=101.5, close=102.2)
        later = fixture.scan(paper)
        self.assertEqual(later["paper_portfolio"]["report"]["positions"], [])
        with self.assertRaises(PaperPortfolioError) as caught:
            paper.enter(fixture.candidate(first), fixture.retained_bar(later), decision["candidate_id"],
                        candidate_decision_id=decision["candidate_id"])
        self.assertEqual(caught.exception.reason_code, "LEGACY_AUTOMATIC_TRIGGER_UNSUPPORTED")
        self.assertEqual(paper.snapshot()["events"], [])

    def test_confirmed_trigger_restarts_before_entry_and_recovers_committed_effect_after_code_change(self):
        from forward_paper import ForwardPaperCoordinator
        from paper_portfolio import PaperPortfolio
        from storage import SQLitePersistenceStore
        ready = ready_orb_trigger(self)
        store = SQLitePersistenceStore(ready.fixture.engine.store.db_path)
        self.addCleanup(store.close)
        restarted = PaperPortfolio(store, ready.paper.config, clock=lambda: ready.fixture.now)
        restarted.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        before = restarted.snapshot()
        self.assertEqual(sum(event["kind"] == "ENTRY" for event in before["events"]), 1)
        ready.fixture.scenario.now += timedelta(days=3)
        with patch("paper_triggers.code_fingerprint", return_value="new-code"):
            decision = ForwardPaperCoordinator(restarted)._transition(ready.decision_id, "FILLED", "RETRY")
        self.assertEqual(decision["status"], "FILLED")
        self.assertEqual(restarted.snapshot()["events"], before["events"])

    def test_post_entry_collision_uses_stop_first_and_never_replays_entry_bar_extremes(self):
        ready = ready_orb_trigger(self)
        result = ready.paper.enter(ready.candidate, ready.bar, ready.decision_id, **ready.arguments)
        self.assertEqual(result["status"], "OPEN")
        ready.fixture.append_bar(open=102.6, high=ready.candidate["target_1"] + 1,
                                 low=ready.candidate["stop_loss"] - 1, close=102)
        later = ready.fixture.scan()
        closed = ready.paper.process_bar(result["position_id"], ready.fixture.retained_bar(later), "collision")
        self.assertEqual(closed["status"], "CLOSED")
        self.assertIn("STOP", closed["exit_reason"])
        report = ready.paper.snapshot()
        self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(report["reconciliation"]["status"], "OK")


if __name__ == "__main__":
    unittest.main()
