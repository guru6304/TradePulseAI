"""Offline R2 boundaries through the actual scanner and disposable lineage store."""
import copy
import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]

from brokers import assess_live_candle_batch, CandleFreshnessError, BrokerDataError
from candle_lineage import make_snapshot
from rank_history import read_current
from storage import SQLitePersistenceStore, PersistenceValidationError, PersistenceError
from strategies import parse_ist_timestamp
from test_astra_paper_triggers import ORBScannerFixture


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


class TestR2RankingReliability(unittest.TestCase):
    def setUp(self):
        self.f = ORBScannerFixture(self)
        self.engine, self.store = self.f.engine, self.f.store

    def view(self, **kwargs):
        return read_current(self.store, self.engine.config, self.f.now, **kwargs)

    def first(self):
        scan = self.f.scan()
        self.assertEqual(scan["scan_status"], "COMPLETED")
        self.assertEqual(len(self.view()["current_rows"]), len(self.engine.config.equity_watchlist))
        return scan

    def assert_archived(self, run_id=None):
        view = self.view(run_id=run_id)
        self.assertEqual(view["current_rows"], [])
        self.assertEqual(len(view["historical_rows"]), 1)
        self.assertEqual(view["status"], "ARCHIVED_NON_CURRENT_SCAN")
        self.assertFalse(view["actionable"])
        return view

    def test_scanner_close_clock_cap_and_tighter_configuration(self):
        bar = dict(self.f.bars[-1], data_mode="LIVE", is_simulated=False)
        close = parse_ist_timestamp(bar["timestamp"]) + timedelta(minutes=5)
        for configured, age, allowed in ((60, 60, True), (60, 61, False), (120, 61, False),
                                         (30, 30, True), (30, 31, False), (0, 0, True), (0, 1, False)):
            with self.subTest(configured=configured, age=age):
                _, report = assess_live_candle_batch([bar], now_ist=close+timedelta(seconds=age),
                    provider="angelone", context="SCANNER", max_delay_seconds=configured)
                self.assertEqual(report["live_signal_allowed"], allowed)
                self.assertEqual(report["max_close_lag_seconds"], min(configured, 60))
        for context in ("REFERENCE", "DIAGNOSTIC"):
            _, report = assess_live_candle_batch([bar], now_ist=close+timedelta(seconds=360),
                provider="angelone", context=context)
            self.assertTrue(report["is_fresh"])

    def test_same_second_missing_volume_failure_revokes_default_and_pinned_rows(self):
        first = self.first()
        self.f.bars[-1].pop("volume")
        with self.assertRaises(BrokerDataError):
            self.f.scan()
        self.assert_archived()
        self.assert_archived(first["run_id"])

    def test_generic_preinput_failure_is_durable_across_restart(self):
        first = self.first()
        with patch.object(self.engine.broker, "fetch_candles", side_effect=RuntimeError("OFFLINE acquisition crash")):
            with self.assertRaises(RuntimeError):
                self.f.scan()
        self.assert_archived(first["run_id"])
        with SQLitePersistenceStore(self.store.database_url) as restarted:
            self.assertEqual(read_current(restarted, self.engine.config, self.f.now)["current_rows"], [])

    def test_unresolved_pending_even_older_reference_revokes_current(self):
        first = self.first()
        work = self.f.work(first)["snapshot"]
        bars = copy.deepcopy(work["batches"][0]["content"]["candles"])
        prior = copy.deepcopy(bars[0])
        prior["timestamp"] = "2026-10-15 15:25:00"
        bars.insert(0, prior)
        snapshot = make_snapshot(self.engine.config, {"RELIANCE": bars}, {}, {}, work["zones"],
            self.f.now-timedelta(seconds=1), rank_history_required=True)
        self.store.prepare_cash_scan("offline-pending", snapshot)
        self.assert_archived()
        self.assert_archived(first["run_id"])

    def test_failed_partial_acquisition_does_not_leave_previous_rank_current(self):
        self.engine.config.equity_watchlist.append(next(copy.deepcopy(m) for m in
            _fixtures.BotConfig().equity_watchlist if m["symbol"] == "INFY"))
        self.first()
        original = self.engine._fetch_scan_candles
        def partial(meta, provider):
            if meta["symbol"] == "INFY":
                raise RuntimeError("OFFLINE second instrument unavailable")
            return original(meta, provider)
        with patch.object(self.engine, "_fetch_scan_candles", side_effect=partial):
            with self.assertRaises(RuntimeError):
                self.f.scan()
        self.assertEqual(self.view()["current_rows"], [])

    def test_fresh_empty_result_expires_with_completed_universe_not_read_clock(self):
        self.first()
        self.f.append_bar(open=102, high=102.3, low=101.5, close=102.2)
        empty = self.f.scan()
        self.assertEqual(empty["scan_status"], "COMPLETED_EMPTY")
        close = parse_ist_timestamp(self.f.bars[-1]["timestamp"])+timedelta(minutes=5)
        self.f.scenario.now = close+timedelta(seconds=30)
        view = self.view()
        self.assertEqual(view["status"], "CURRENT_CANDIDATE_PRIORITY")
        self.assertEqual(view["current_rows"], [])
        self.assertEqual(parse_ist_timestamp(view["snapshot"]["valid_until"]), close+timedelta(seconds=60))
        self.assertTrue(view["snapshot"]["coverage"]["complete"])
        self.f.scenario.now = close+timedelta(seconds=61)
        self.assertEqual(self.view()["status"], "STALE_OR_FUTURE_SNAPSHOT")

    def test_delayed_commit_rolls_back_rank_and_recovery_cannot_be_current(self):
        def delay(stage):
            if stage == "after_rank_insert":
                self.f.scenario.now += timedelta(seconds=56)
        with patch.object(self.store, "_lineage_checkpoint", side_effect=delay):
            with self.assertRaises(CandleFreshnessError):
                self.f.scan()
        with self.store.lineage_read() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cash_rank_snapshots").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)
        pending = self.store.pending_cash_scans()[0]["run_id"]
        recovered = self.engine.resume_cash_scan(pending)
        self.assertFalse(recovered["candle_freshness"]["live_signal_allowed"])
        self.assertEqual(self.view()["current_rows"], [])

    def test_forming_tail_and_previous_slot_do_not_rescue_coverage(self):
        self.first()
        self.f.scenario.now += timedelta(minutes=4, seconds=54)
        tail = copy.deepcopy(self.f.bars[-1])
        tail.update(timestamp=(parse_ist_timestamp(tail["timestamp"])+timedelta(minutes=5)).isoformat())
        self.f.bars.append(tail)
        with self.assertRaises(CandleFreshnessError):
            self.f.scan()
        self.assertEqual(self.engine.last_candle_freshness["live_signal_allowed"], False)
        self.assertEqual(self.view()["current_rows"], [])

    def test_missing_cash_evaluator_rolls_back_instead_of_publishing_partial_rank(self):
        def unavailable(**kwargs):
            raise RuntimeError("OFFLINE evaluator interruption")
        with patch("scanner_engine.evaluate_vwap_pullback", new=unavailable):
            with self.assertRaisesRegex(PersistenceValidationError, "RANK_STRATEGY_COVERAGE_INCOMPLETE"):
                self.f.scan()
        self.assertEqual(self.view()["current_rows"], [])
        with self.store.lineage_read() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cash_rank_snapshots").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)
        self.assertEqual(len(self.store.pending_cash_scans()), 1)

    def test_staggered_required_symbols_cannot_use_different_completed_slots(self):
        self.engine.config.equity_watchlist.append(next(copy.deepcopy(m) for m in
            _fixtures.BotConfig().equity_watchlist if m["symbol"] == "INFY"))
        self.engine._assess_scan_candles(self.f.bars, "RELIANCE", "angelone", self.f.now)
        with self.assertRaises(CandleFreshnessError):
            self.engine._assess_scan_candles(self.f.bars[:-1], "INFY", "angelone", self.f.now)
        self.assertFalse(self.engine._freshness_status("angelone", self.f.now)["live_signal_allowed"])

    def test_unrecordable_failure_returns_api_unavailable_without_old_rows(self):
        from server import DashboardRequestHandler
        from types import SimpleNamespace
        self.first()
        with patch.object(self.engine.broker, "fetch_candles", side_effect=RuntimeError("OFFLINE")), \
                patch.object(self.store, "record_scan_run", side_effect=PersistenceError("OFFLINE store unavailable")):
            with self.assertRaises(RuntimeError):
                self.f.scan()
        status, data = DashboardRequestHandler._handle_opportunity_rankings(SimpleNamespace(engine=self.engine), {})
        self.assertEqual(status, 503)
        self.assertNotIn("current_rows", data)

    def test_committed_replay_does_not_clear_newer_failed_attempt(self):
        first = self.first()
        with patch.object(self.engine.broker, "fetch_candles", side_effect=RuntimeError("OFFLINE")):
            with self.assertRaises(RuntimeError):
                self.f.scan()
        self.assertTrue(self.f.scan()["idempotent_replay"])
        self.assert_archived(first["run_id"])

    def test_configuration_failure_before_acquisition_is_retained(self):
        from config import ConfigValidationError
        self.first()
        with patch.object(self.engine.config, "validate", side_effect=ConfigValidationError("OFFLINE invalid config")):
            with self.assertRaises(ConfigValidationError):
                self.f.scan()
        self.assert_archived()

    def test_rejected_committed_recovery_cannot_overwrite_saved_outcome(self):
        from config import ConfigValidationError
        first = self.first()
        with patch.object(self.engine.config, "validate", side_effect=ConfigValidationError("OFFLINE invalid config")):
            with self.assertRaises(ConfigValidationError):
                self.engine.resume_cash_scan(first["run_id"])
        saved = self.store.load_cash_scan(first["run_id"])
        self.assertEqual(saved["status"], "COMMITTED")
        self.assertEqual(saved["result"]["scan_status"], "COMPLETED")
        self.assert_archived(first["run_id"])

    def test_scheduled_cycle_reports_stale_without_starting_background_work(self):
        from scanner_engine import MarketScanScheduler
        self.first()
        self.f.scenario.now += timedelta(seconds=56)
        scheduler = MarketScanScheduler(self.engine, clock=lambda: self.f.now)
        result = scheduler.run_scheduled_cycle()
        self.assertEqual(result["scan_status"], "FAILED")
        self.assertEqual(result["reason_code"], "STALE")
        self.assertEqual(scheduler.cycles_executed, 0)
        self.assertIsNone(scheduler._thread)
        self.assertEqual(self.view()["current_rows"], [])

    def test_new_success_restores_fresh_empty_after_failure(self):
        self.first()
        with patch.object(self.engine.broker, "fetch_candles", side_effect=RuntimeError("OFFLINE")):
            with self.assertRaises(RuntimeError):
                self.f.scan()
        self.assert_archived()
        self.f.append_bar(open=102, high=102.3, low=101.5, close=102.2)
        self.assertEqual(self.f.scan()["scan_status"], "COMPLETED_EMPTY")
        self.assertEqual(self.view()["status"], "CURRENT_CANDIDATE_PRIORITY")

    def test_other_provider_failure_and_skipped_overlap_do_not_revoke_current(self):
        first = self.first()
        self.store.record_scan_run("other", "2026-10-16 11:45:05", "2026-10-16 11:45:05",
            0, "FAILED", "DhanHQ API v2", "LIVE", False)
        self.engine._scan_lock.acquire()
        try:
            self.assertEqual(self.f.scan()["scan_status"], "SKIPPED_OVERLAP")
        finally:
            self.engine._scan_lock.release()
        self.assertEqual(self.view()["snapshot"]["run_id"], first["run_id"])
        self.assertEqual(len(self.view()["current_rows"]), 1)
