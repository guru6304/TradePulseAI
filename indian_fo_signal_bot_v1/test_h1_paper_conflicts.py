"""Offline account-level contrary-position guards using real disposable ledgers.

The fixture owns temporary SQLite files and forbids provider/Telegram transport.
No synthetic identity declaration establishes real market or data acceptance.
"""
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


import test_phase5a_paper as paper_fixtures
from instrument_identity import spot_identity
from paper_portfolio import PaperPortfolio, PaperPortfolioError
from storage import SQLitePersistenceStore


class TestH1PaperConflicts(unittest.TestCase):
    def setUp(self):
        # Composition avoids rediscovering the older TestCase's test methods.
        self.fixture = paper_fixtures.TestPhase5APaperPortfolio()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def service(self, **settings):
        values = dict(max_open_positions=8, max_entries_per_day=20,
                      max_position_exposure_pct=100, max_total_exposure_pct=100)
        values.update(settings)
        return self.fixture._service(**values)

    def candidate(self, paper, **settings):
        return self.fixture._candidate(paper, **settings)

    def bar(self, candidate, **settings):
        return self.fixture._bar(candidate, **settings)

    @staticmethod
    def ledger(paper):
        with paper.store.paper_transaction(write=False) as connection:
            return tuple(connection.iterdump())

    def assert_conflict_without_effect(self, paper, candidate, bar, event_key):
        before, report = self.ledger(paper), paper.snapshot()
        with self.assertRaises(PaperPortfolioError) as caught:
            paper.enter(candidate, bar, event_key)
        self.assertEqual(caught.exception.reason_code, "CONFLICTING_OPEN_POSITION")
        self.assertEqual(self.ledger(paper), before)
        self.assertEqual(paper.snapshot(), report)
        self.assertEqual(paper.reconcile()["status"], "OK")

    def test_long_and_short_conflict_across_strategies_and_later_candidate_times(self):
        for first_side, next_side in (("LONG", "SHORT"), ("SHORT", "LONG")):
            with self.subTest(first_side=first_side):
                self.fixture._set_time("10:10")
                paper = self.service(account_id="direction-" + first_side)
                first = self.candidate(paper, side=first_side)
                opened = paper.enter(first, self.bar(first), "first")
                self.fixture._set_time("10:15")
                paper.process_bar(opened["position_id"], self.bar(first, stamp="10:10"), "fresh-mark")
                second = self.candidate(paper, strategy="strat_2_vwap_pullback",
                                        side=next_side, stamp="10:05")
                self.assert_conflict_without_effect(paper, second, self.bar(second, stamp="10:10"), "contrary")

    def test_same_side_same_instrument_across_strategies_remains_allowed(self):
        paper = self.service()
        for strategy, event in (("strat_1_order_block", "first"), ("strat_2_vwap_pullback", "second")):
            candidate = self.candidate(paper, strategy=strategy)
            self.assertEqual(paper.enter(candidate, self.bar(candidate), event)["status"], "OPEN")
        report = paper.snapshot()
        self.assertEqual(report["accounting"]["open_positions"], 2)
        self.assertEqual({position["side"] for position in report["positions"]}, {"LONG"})
        self.assertEqual(paper.reconcile()["status"], "OK")

    def test_opposite_side_different_instrument_remains_allowed(self):
        paper = self.service()
        first = self.candidate(paper)
        other = self.candidate(paper, symbol="TCS", side="SHORT")
        paper.enter(first, self.bar(first), "first")
        self.assertEqual(paper.enter(other, self.bar(other), "other-instrument")["status"], "OPEN")
        self.assertEqual(paper.snapshot()["accounting"]["open_positions"], 2)
        self.assertEqual(paper.reconcile()["status"], "OK")

    def test_independent_accounts_keep_independent_directional_exposure(self):
        first, second = self.service(account_id="one"), self.service(account_id="two")
        long = self.candidate(first)
        short = self.candidate(second, side="SHORT")
        first.enter(long, self.bar(long), "first")
        self.assertEqual(second.enter(short, self.bar(short), "independent")["status"], "OPEN")
        self.assertEqual(first.snapshot()["accounting"]["open_positions"], 1)
        self.assertEqual(second.snapshot()["accounting"]["open_positions"], 1)

    def test_revised_master_metadata_and_symbol_do_not_change_exposure_identity(self):
        paper = self.service(provider="angelone")
        candidates = []
        for symbol, revision, side in (("H1FIXTURE_A", "original", "LONG"),
                                      ("H1FIXTURE_B", "renamed", "SHORT")):
            candidate = self.candidate(paper, side=side)
            # An authored rename/master revision preserves the exact token.
            master_record = dict(symbol=symbol, angel_token="99000001", fixture_revision=revision)
            candidate.symbol, candidate.instrument_label = symbol, symbol + " EQ"
            candidate.instrument_identity = spot_identity(
                dict(symbol=symbol, angel_token="99000001"), "angelone", {symbol: master_record})
            candidates.append(candidate)
        first, second = candidates
        self.assertNotEqual(first.instrument_identity["source_revision"], second.instrument_identity["source_revision"])
        paper.enter(first, self.bar(first), "original-name")
        self.assert_conflict_without_effect(paper, second, self.bar(second), "renamed-contract")

    def test_conflict_reads_retained_positions_when_report_previews_are_empty(self):
        paper = self.service()
        first, second = self.candidate(paper), self.candidate(paper, side="SHORT")
        paper.enter(first, self.bar(first), "first")
        # Simulate exhausted preview space; accounting and stored positions stay real.
        with patch.object(PaperPortfolio, "_preview_append", side_effect=lambda items, item, used: used):
            report = paper.snapshot()
            self.assertEqual(report["positions"], [])
            self.assertEqual(report["total_positions"], 1)
            self.assertEqual(len(paper.open_positions()), 1)
            self.assert_conflict_without_effect(paper, second, self.bar(second), "outside-preview")

    def close_first_then_reverse(self):
        paper = self.service()
        first = self.candidate(paper)
        first_bar = self.bar(first)
        opened = paper.enter(first, first_bar, "original-entry")
        self.fixture._set_time("10:15")
        paper.process_bar(opened["position_id"], self.bar(first, stamp="10:10", low=85, close=90), "stop-exit")
        self.fixture._set_time("10:20")
        second = self.candidate(paper, strategy="strat_5_supertrend_pullback", side="SHORT", stamp="10:10")
        reversed_entry = paper.enter(second, self.bar(second, stamp="10:15"), "new-direction")
        return paper, first, first_bar, opened, reversed_entry

    def test_closed_position_releases_the_opposite_direction_guard(self):
        paper, _, _, _, result = self.close_first_then_reverse()
        self.assertEqual(result["status"], "OPEN")
        report = paper.snapshot()
        self.assertEqual(report["accounting"]["closed_positions"], 1)
        self.assertEqual(report["accounting"]["open_positions"], 1)
        self.assertEqual(next(position for position in report["positions"] if position["status"] == "OPEN")["side"], "SHORT")
        self.assertEqual(paper.reconcile()["status"], "OK")

    def test_committed_entry_retry_recovers_before_new_opposite_exposure_check(self):
        paper, first, first_bar, original, _ = self.close_first_then_reverse()
        before, report = self.ledger(paper), paper.snapshot()
        result = paper.enter(first, first_bar, "original-entry")
        self.assertEqual(result, dict(original, idempotent=True))
        self.assertEqual(self.ledger(paper), before)
        self.assertEqual(paper.snapshot(), report)

    def test_restart_enforces_the_retained_open_exposure(self):
        paper = self.service()
        first = self.candidate(paper)
        paper.enter(first, self.bar(first), "first")
        recovered_store = SQLitePersistenceStore(self.fixture.database)
        self.addCleanup(recovered_store.close)
        recovered = PaperPortfolio(recovered_store, paper.config, clock=lambda: self.fixture.now)
        opposite = self.candidate(recovered, strategy="strat_4_orb_filtered", side="SHORT")
        self.assert_conflict_without_effect(recovered, opposite, self.bar(opposite), "after-restart")

    def test_concurrent_opposite_entries_on_independent_connections_commit_only_one(self):
        first = self.service()
        other_store = SQLitePersistenceStore(self.fixture.database)
        self.addCleanup(other_store.close)
        second = PaperPortfolio(other_store, first.config, clock=lambda: self.fixture.now)
        candidates = [self.candidate(first), self.candidate(second, side="SHORT", strategy="strat_2_vwap_pullback")]
        barrier = threading.Barrier(2)

        def attempt(index):
            barrier.wait(timeout=5)
            try:
                return (first if index == 0 else second).enter(
                    candidates[index], self.bar(candidates[index]), "racing-" + str(index))
            except PaperPortfolioError as exc:
                return exc.reason_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(isinstance(outcome, dict) for outcome in outcomes), 1, outcomes)
        self.assertEqual(outcomes.count("CONFLICTING_OPEN_POSITION"), 1, outcomes)
        report = first.snapshot()
        self.assertEqual(report["accounting"]["open_positions"], 1)
        self.assertEqual(report["accounting"]["day"]["entries"], 1)
        self.assertEqual(report["total_events"], 2)
        self.assertEqual(first.reconcile()["status"], "OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
