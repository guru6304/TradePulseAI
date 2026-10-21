"""Task 4 OFFLINE fixtures: local lineage is not provider/source acceptance."""
import copy
from datetime import datetime, timedelta
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import test_bot  # established credential-free offline bootstrap
from storage import SQLitePersistenceStore, PersistenceError, PersistenceValidationError
from config import BotConfig
from instrument_identity import bind_candles, spot_identity
from strategies import IST, parse_ist_timestamp
from candle_lineage import make_snapshot, digest, completed_cash_batch, runtime_profile


class TestCashLineage(unittest.TestCase):
    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        guard = patch("urllib.request.urlopen", side_effect=AssertionError("No external transport"))
        guard.start()
        self.addCleanup(guard.stop)

    def fixture(self):
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        scenario = TestPhase4OfflineEndToEnd()
        scenario.now = datetime(2026, 10, 16, 14, 15, 5, tzinfo=IST)
        cfg = BotConfig(active_broker="upstox", upstox_access_token="OFFLINE_ONLY",
                        telegram_dry_run=True, enable_background_scheduler=False)
        cfg.fo_indices = {}
        cfg.equity_watchlist = [m for m in cfg.equity_watchlist if m["symbol"] == "RELIANCE"]
        identity = spot_identity(cfg.equity_watchlist[0], "upstox")
        rows = bind_candles([dict(r, is_simulated=False, data_mode="LIVE", interval_min=5,
                                 is_complete=parse_ist_timestamp(r["timestamp"])+timedelta(minutes=5) <= scenario.now,
                                 timestamp_timezone="Asia/Kolkata") for r in scenario._fixture()], identity)
        return cfg, rows, scenario.now

    def snapshot(self):
        cfg, rows, now = self.fixture()
        return make_snapshot(cfg, {"RELIANCE": rows}, {}, {},
            {"NSE_EQUITY_INTRADAY": set(), "NSE_FO_INDEX": set()}, now)

    def counts(self):
        with self.store.paper_transaction(write=False) as conn:
            return {table: conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    for table in ("cash_candle_facts", "cash_candle_batches", "cash_candle_batch_members",
                                  "cash_candle_scans", "cash_candle_scan_inputs", "signals", "scan_runs")}

    def test_accepted_input_is_completed_only_and_reingestion_is_idempotent(self):
        snapshot = self.snapshot()
        first = self.store.prepare_cash_scan("offline-scan", snapshot)
        before = self.counts()
        second = self.store.prepare_cash_scan("another-attempt", copy.deepcopy(snapshot))
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(self.counts(), before)
        self.assertEqual(before["cash_candle_facts"], 60)
        self.assertEqual(before["cash_candle_scan_inputs"], 1)
        self.assertEqual(before["scan_runs"], 0)
        batch = self.store.load_cash_scan("offline-scan")["snapshot"]["batches"][0]
        self.assertEqual(batch["content"], snapshot["batches"][0]["content"])
        self.assertTrue(all(r["is_complete"] for r in batch["content"]["candles"]))
        self.assertEqual(batch["source_authenticity"], "NOT_ESTABLISHED")

    def test_input_transaction_rolls_back_at_each_actual_write_boundary(self):
        snapshot = self.snapshot()
        for point in ("before_input_transaction", "after_candle_write", "between_batches_and_scan", "before_input_commit"):
            with self.subTest(point=point):
                def fail(boundary):
                    if boundary == point:
                        raise RuntimeError("OFFLINE injected interruption")
                with patch.object(self.store, "_lineage_checkpoint", side_effect=fail), self.assertRaises(RuntimeError):
                    self.store.prepare_cash_scan("retry", snapshot)
                self.assertTrue(all(n == 0 for n in self.counts().values()))
        work = self.store.prepare_cash_scan("retry", snapshot)
        self.assertEqual(work["status"], "PENDING")

    def test_input_commit_before_ack_is_discoverable_and_retry_does_not_duplicate(self):
        snapshot = self.snapshot()
        with patch.object(self.store, "_lineage_checkpoint", side_effect=lambda b: (_ for _ in ()).throw(
                RuntimeError("Lost acknowledgement")) if b == "after_input_commit" else None), self.assertRaises(RuntimeError):
            self.store.prepare_cash_scan("committed-input", snapshot)
        self.assertEqual(self.store.pending_cash_scans()[0]["run_id"], "committed-input")
        before = self.counts()
        self.assertEqual(self.store.prepare_cash_scan("retry", snapshot)["run_id"], "committed-input")
        self.assertEqual(self.counts(), before)

    def test_same_identity_conflicting_content_and_changed_candle_corrections_reject(self):
        snapshot = self.snapshot()
        self.store.prepare_cash_scan("first", snapshot)
        before = self.counts()
        forged = copy.deepcopy(snapshot)
        forged["batches"][0]["content"]["candles"][0]["volume"] += 1
        with self.assertRaises(ValueError):
            self.store.prepare_cash_scan("forged", forged)
        cfg, rows, now = self.fixture()
        rows[0]["volume"] += 1
        revised = make_snapshot(cfg, {"RELIANCE": rows}, {}, {}, snapshot["zones"], now)
        with self.assertRaisesRegex(PersistenceValidationError, "CORRECTION_CONFLICT"):
            self.store.prepare_cash_scan("correction", revised)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.store.load_cash_scan("first")["snapshot"]["batches"][0]["content"],
                         snapshot["batches"][0]["content"])

    def test_duplicate_gap_wrong_identity_stale_future_malformed_and_incomplete_reject(self):
        cfg, rows, now = self.fixture()
        mutations = [lambda r: r.insert(1, copy.deepcopy(r[0])), lambda r: r.pop(1),
            lambda r: r[0]["instrument_identity"].update(identifier="1333"),
            lambda r: r[0].update(open=float("nan")),
            lambda r: [bar.update(is_complete=False) for bar in r],
            lambda r: r[-1].update(timestamp="2026-10-16T14:25:00+05:30"),
            lambda r: r[0].pop("instrument_identity"),
            lambda r: r[0]["instrument_identity"].update(source="FORGED_SOURCE"),
            lambda r: r[0].update(provider="angelone")]
        for mutation in mutations:
            changed = copy.deepcopy(rows)
            mutation(changed)
            with self.subTest(mutation=mutations.index(mutation)), self.assertRaises(ValueError):
                make_snapshot(cfg, {"RELIANCE": changed}, {}, {}, {}, now)
        with self.assertRaises(ValueError):
            make_snapshot(cfg, {"RELIANCE": rows}, {}, {}, {}, now + timedelta(hours=1))
        self.assertTrue(all(n == 0 for n in self.counts().values()))

    def test_candle_and_input_link_tampering_is_detected(self):
        self.store.prepare_cash_scan("scan", self.snapshot())
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE cash_candle_facts SET content_digest='tampered'")
        with self.assertRaisesRegex(PersistenceValidationError, "CANDLE_INTEGRITY"):
            self.store.load_cash_scan("scan")

    def test_legacy_nested_writers_cannot_commit_an_aborted_result(self):
        with self.assertRaises(RuntimeError):
            with self.store.scan_result_transaction():
                self.store.record_scan_run("scan", "2026-10-16 14:15:05", None, None,
                    "COMPLETED_EMPTY", "Offline fixture", "LIVE", False)
                raise RuntimeError("Interruption before result commit")
        self.assertEqual(self.counts()["scan_runs"], 0)

    def test_caught_inner_sql_error_marks_transaction_rollback_only(self):
        with self.assertRaisesRegex(PersistenceError, "NESTED_WRITE_FAILED"):
            with self.store.scan_result_transaction():
                self.store.record_scan_run("scan", "2026-10-16 14:15:05", None, None,
                    "COMPLETED_EMPTY", "Offline fixture", "LIVE", False)
                try:
                    with self.store._get_connection() as conn:
                        conn.execute("INVALID OFFLINE SQL")
                except sqlite3.Error:
                    pass
        self.assertEqual(self.counts()["scan_runs"], 0)

    def test_concurrent_repeated_input_has_one_work_item_and_one_candle_set(self):
        snapshot = self.snapshot()
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda n: self.store.prepare_cash_scan("attempt-"+str(n), snapshot), range(8)))
        self.assertEqual(len({r["run_id"] for r in rows}), 1)
        self.assertEqual(self.counts()["cash_candle_facts"], 60)
        self.assertEqual(self.counts()["cash_candle_scans"], 1)

    def test_missing_explicit_normalized_provenance_is_not_inferred(self):
        cfg, rows, now = self.fixture()
        for field in ("timestamp_timezone", "data_mode", "is_simulated", "interval_min", "is_complete"):
            changed = copy.deepcopy(rows)
            changed[0].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_snapshot(cfg, {"RELIANCE": changed}, {}, {}, {}, now)
        self.assertEqual(self.counts()["cash_candle_facts"], 0)

    def test_supported_quantity_is_retained_and_invalid_quantity_rejected(self):
        cfg, rows, now = self.fixture()
        for row in rows:
            row["traded_quantity"] = row["volume"]
        snapshot = make_snapshot(cfg, {"RELIANCE": rows}, {}, {}, {}, now)
        self.store.prepare_cash_scan("quantity", snapshot)
        loaded = self.store.load_cash_scan("quantity")["snapshot"]["batches"][0]["content"]["candles"]
        self.assertTrue(all(r["traded_quantity"] == r["volume"] for r in loaded))
        rows[0]["traded_quantity"] = -1
        with self.assertRaises(ValueError):
            make_snapshot(cfg, {"RELIANCE": rows}, {}, {}, {}, now)

    def test_metadata_and_input_link_tampering_are_rejected(self):
        for kind in ("metadata", "link"):
            with self.subTest(kind=kind), SQLitePersistenceStore(":memory:") as store:
                store.prepare_cash_scan("scan", self.snapshot())
                with store.paper_transaction() as conn:
                    if kind == "metadata":
                        conn.execute("UPDATE cash_candle_batches SET metadata_json='{}'")
                    else:
                        conn.execute("DELETE FROM cash_candle_scan_inputs")
                with self.assertRaises(PersistenceValidationError):
                    store.load_cash_scan("scan")

    def test_different_pending_work_blocks_and_preserves_original_input(self):
        snapshot = self.snapshot()
        self.store.prepare_cash_scan("original", snapshot)
        before = self.counts()
        cfg, rows, now = self.fixture()
        cfg.max_risk_per_trade_pct *= 0.5
        changed = make_snapshot(cfg, {"RELIANCE": rows}, {}, {}, {}, now)
        with self.assertRaisesRegex(PersistenceValidationError, "PRIOR_SCAN_REQUIRES_RECOVERY"):
            self.store.prepare_cash_scan("later", changed)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.store.pending_cash_scans()[0]["run_id"], "original")

    def test_zone_snapshot_uses_committed_database_state_inside_input_transaction(self):
        snapshot = self.snapshot()  # stale engine view is empty
        zone = "RELIANCE:OB:BULL:2026-10-16 09:20:00"
        self.store.save_mitigated_order_blocks({zone}, provider="upstox", data_mode="LIVE",
            state_context="SCANNER", segment="NSE_EQUITY_INTRADAY", interval_min=5)
        accepted = self.store.prepare_cash_scan("frozen-zone", snapshot)
        self.assertEqual(accepted["snapshot"]["zones"]["NSE_EQUITY_INTRADAY"], [zone])

    def test_nested_transaction_control_cannot_commit_rollback_or_close_outer_connection(self):
        for action in ("commit", "rollback", "close"):
            with self.subTest(action=action), self.assertRaisesRegex(PersistenceError, "OUTER_TRANSACTION"):
                with self.store.scan_result_transaction():
                    self.store.record_scan_run("aborted", "2026-10-16 14:15:05", None, None,
                        "COMPLETED_EMPTY", "Offline fixture", "LIVE", False)
                    getattr(self.store._get_connection(), action)()
            self.assertEqual(self.counts()["scan_runs"], 0)


class TestCashScannerRecovery(unittest.TestCase):
    def setUp(self):
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        self.scenario = TestPhase4OfflineEndToEnd()
        self.scenario.setUp()
        self.addCleanup(self.scenario.doCleanups)

    def engine(self, database="lineage.sqlite", provider="upstox"):
        return self.scenario._engine(provider, database=database)

    def state(self, store):
        with store.paper_transaction(write=False) as conn:
            return {name: conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in
                ("cash_candle_facts", "cash_candle_scans", "cash_candle_scan_inputs", "cash_candle_signal_inputs",
                 "signals", "scan_runs", "scoped_mitigated_order_blocks", "paper_positions", "paper_events")}

    def test_each_result_write_failure_rolls_back_and_restart_replays_without_transport(self):
        for point in ("after_signal_write", "after_zone_write", "after_scan_result_write", "before_result_commit"):
            with self.subTest(boundary=point):
                engine = self.engine(point+".sqlite")
                def fail(boundary):
                    if boundary == point:
                        raise RuntimeError("OFFLINE write interruption")
                with patch.object(engine.store, "_lineage_checkpoint", side_effect=fail), \
                        patch.object(engine.telegram, "send_signal") as delivery, self.assertRaises((RuntimeError, PersistenceError)):
                    engine.run_single_scan()
                delivery.assert_not_called()
                state = self.state(engine.store)
                self.assertEqual(state["signals"], 0)
                self.assertEqual(state["scan_runs"], 0)
                self.assertEqual(state["scoped_mitigated_order_blocks"], 0)
                self.assertEqual(state["cash_candle_facts"], 60)
                run_id = engine.store.pending_cash_scans()[0]["run_id"]
                original = engine.store.load_cash_scan(run_id)["snapshot"]["batches"][0]["content"]
                engine.close()
                restarted = self.engine(point+".sqlite")
                # Explicit recovery is allowed to inspect old accepted inputs; it
                # cannot claim that they establish current live freshness/delivery.
                self.scenario.now += timedelta(days=1)
                with patch.object(restarted.broker, "fetch_candles", side_effect=AssertionError("No acquisition in recovery")), \
                        patch.object(restarted.broker, "fetch_option_chain", side_effect=AssertionError("No chain in recovery")), \
                        patch.object(restarted.telegram, "send_signal", side_effect=AssertionError("No replay delivery")):
                    result = restarted.resume_cash_scan(run_id)
                    again = restarted.resume_cash_scan(run_id)
                self.assertEqual(result["total_signals"], 1)
                self.assertFalse(result["candle_freshness"]["live_signal_allowed"])
                self.assertTrue(result["input_lineage"]["recovery_mode"])
                self.assertTrue(again["idempotent_replay"])
                self.assertEqual(again["signals"], [])
                self.assertEqual(self.state(restarted.store)["signals"], 1)
                self.assertEqual(self.state(restarted.store)["scan_runs"], 1)
                self.assertEqual(self.state(restarted.store)["cash_candle_signal_inputs"], 1)
                retained = restarted.store.load_cash_scan(run_id)
                self.assertEqual(retained["snapshot"]["batches"][0]["content"], original)
                self.assertEqual(retained["result"]["signals"], result["signals"])
                self.scenario.now -= timedelta(days=1)

    def test_postcommit_acknowledgement_loss_keeps_result_and_suppresses_repeat_delivery(self):
        engine = self.engine()
        def fail(boundary):
            if boundary == "after_result_commit":
                raise RuntimeError("OFFLINE lost caller acknowledgement")
        with patch.object(engine.store, "_lineage_checkpoint", side_effect=fail), \
                patch.object(engine.telegram, "send_signal") as delivery, self.assertRaises(RuntimeError):
            engine.run_single_scan()
        delivery.assert_not_called()
        self.assertEqual(self.state(engine.store)["signals"], 1)
        with engine.store.paper_transaction(write=False) as conn:
            run_id = conn.execute("SELECT run_id FROM cash_candle_scans").fetchone()[0]
        before = self.state(engine.store)
        engine.close()
        restarted = self.engine()
        with patch.object(restarted.broker, "fetch_candles", side_effect=AssertionError("No replay acquisition")), \
                patch.object(restarted.telegram, "send_signal") as replay_delivery:
            result = restarted.resume_cash_scan(run_id)
        replay_delivery.assert_not_called()
        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["original_total_signals"], 1)
        self.assertEqual(self.state(restarted.store), before)
        self.assertEqual(restarted.store.load_cash_scan(run_id)["status"], "COMMITTED")

    def test_no_signal_scan_keeps_inputs_outcome_and_idempotent_links(self):
        engine = self.engine()
        for row in self.scenario.batches["upstox"]:
            row.update(open=100.0, high=100.0, low=100.0, close=100.0, volume=1000)
        result = engine.run_single_scan()
        self.assertEqual(result["scan_status"], "COMPLETED_EMPTY")
        self.assertEqual(result["total_signals"], 0)
        before = self.state(engine.store)
        self.assertEqual(before["cash_candle_facts"], 60)
        self.assertEqual(before["scan_runs"], 1)
        loaded = engine.store.load_cash_scan(result["run_id"])
        self.assertEqual(loaded["result"]["scan_status"], "COMPLETED_EMPTY")
        repeated = engine.run_single_scan()
        self.assertTrue(repeated["idempotent_replay"])
        self.assertEqual(self.state(engine.store), before)

    def test_unavailable_required_store_fails_before_any_acquisition(self):
        from scanner_engine import IntradayBotEngine
        engine = self.engine()
        cfg, broker = engine.config, engine.broker
        with patch("scanner_engine.SQLitePersistenceStore", side_effect=PersistenceError("OFFLINE unavailable")):
            broken = IntradayBotEngine(cfg, clock=lambda: self.scenario.now, broker_scanner=broker)
        self.addCleanup(broken.close)
        with patch.object(broker, "fetch_candles", side_effect=AssertionError("No acquisition without storage")) as acquisition, \
                self.assertRaises(PersistenceError):
            broken.run_single_scan()
        acquisition.assert_not_called()
        self.assertEqual(broken.last_scan_summary["persisted_signals"], 0)

    def test_configuration_or_code_change_blocks_recovery_without_writes(self):
        engine = self.engine()
        result = engine.run_single_scan()
        before = self.state(engine.store)
        engine.config.max_risk_per_trade_pct *= 0.5
        with self.assertRaisesRegex(PersistenceValidationError, "CONFIGURATION_OR_CODE_CHANGED"):
            engine.resume_cash_scan(result["run_id"])
        engine.config.max_risk_per_trade_pct *= 2
        with patch("candle_lineage.code_fingerprint", return_value="changed-offline-code"), \
                self.assertRaises(PersistenceValidationError):
            engine.resume_cash_scan(result["run_id"])
        self.assertEqual(self.state(engine.store), before)

    def test_concurrent_scanners_commit_one_outcome_and_one_signal(self):
        first, second = self.engine(), self.engine()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda e: e.run_single_scan(), (first, second)))
        self.assertEqual(sum(r["persisted_signals"] for r in results), 1)
        self.assertEqual(sum(bool(r.get("idempotent_replay")) for r in results), 1)
        state = self.state(first.store)
        self.assertEqual((state["cash_candle_facts"], state["cash_candle_scans"], state["scan_runs"], state["signals"]),
                         (60, 1, 1, 1))

    def test_paper_handoff_failure_recovers_existing_effect_without_duplicate_ledger(self):
        from paper_portfolio import PaperPortfolio, PaperAccountConfig, FORWARD_FILL_POLICY
        from forward_paper import ForwardPaperCoordinator
        engine = self.engine(provider="angelone")
        paper_config = PaperAccountConfig(account_id="lineage-paper", run_id="offline-task4",
            provider="angelone", source_data_mode="LIVE", fill_policy=FORWARD_FILL_POLICY)
        paper = PaperPortfolio(engine.store, paper_config, clock=lambda: self.scenario.now)
        first = engine.run_single_scan(paper_portfolio=paper)
        candidate = first["signals"][0]
        price = candidate["entry_price"]
        self.scenario.batches["angelone"][-1].update(open=price, high=price+.2, low=price-.2, close=price+.1, volume=10000)
        self.scenario.now += timedelta(minutes=5)
        with patch.object(ForwardPaperCoordinator, "_transition", side_effect=RuntimeError("OFFLINE interrupted decision update")):
            second = engine.run_single_scan(paper_portfolio=paper)
        self.assertEqual(second["paper_portfolio"]["status"], "UNAVAILABLE")
        before = self.state(engine.store)
        self.assertEqual(before["paper_positions"], 1)
        engine.close()
        restarted = self.engine(provider="angelone")
        restored_paper = PaperPortfolio(restarted.store, paper_config, clock=lambda: self.scenario.now)
        with patch.object(restarted.broker, "fetch_candles", side_effect=AssertionError("No recovery transport")), \
                patch.object(restarted.telegram, "send_signal", side_effect=AssertionError("No recovery delivery")):
            recovered = restarted.resume_cash_scan(second["run_id"], paper_portfolio=restored_paper)
            again = restarted.resume_cash_scan(second["run_id"], paper_portfolio=restored_paper)
        self.assertEqual(recovered["paper_portfolio"]["status"], "COMPLETED")
        self.assertEqual(recovered["paper_portfolio"]["report"]["reconciliation"]["status"], "OK")
        self.assertEqual(self.state(restarted.store)["paper_events"], before["paper_events"])
        self.assertEqual(self.state(restarted.store)["paper_positions"], 1)
        self.assertEqual(recovered["paper_portfolio"]["report"]["accounting"], again["paper_portfolio"]["report"]["accounting"])

    def test_missing_or_tampered_committed_outcome_signal_and_links_fail_closed(self):
        mutations = ("DELETE FROM scan_runs", "DELETE FROM signals", "DELETE FROM cash_candle_signal_inputs",
                     "UPDATE signals SET entry_price=entry_price+1", "UPDATE scan_runs SET total_signals=99",
                     "UPDATE cash_candle_scans SET result_digest='tampered'")
        for number, sql in enumerate(mutations):
            with self.subTest(sql=sql):
                engine = self.engine("tamper"+str(number)+".sqlite")
                result = engine.run_single_scan()
                with engine.store.paper_transaction() as conn:
                    conn.execute(sql)
                with patch.object(engine.telegram, "send_signal") as delivery, self.assertRaises(PersistenceValidationError):
                    engine.resume_cash_scan(result["run_id"])
                delivery.assert_not_called()

    def test_storage_unavailable_mid_scan_preserves_pending_input_and_blocks_delivery(self):
        engine = self.engine()
        with patch.object(engine.store, "save_signal", side_effect=PersistenceError("OFFLINE storage unavailable")), \
                patch.object(engine.telegram, "send_signal") as delivery, self.assertRaises(PersistenceError):
            engine.run_single_scan()
        delivery.assert_not_called()
        state = self.state(engine.store)
        self.assertEqual((state["cash_candle_facts"], state["signals"], state["scan_runs"]), (60, 0, 0))
        self.assertEqual(engine.last_scan_summary["persisted_signals"], 0)
        run_id = engine.store.pending_cash_scans()[0]["run_id"]
        with patch.object(engine.broker, "fetch_candles", side_effect=AssertionError("No recovery transport")):
            recovered = engine.resume_cash_scan(run_id)
        self.assertEqual(recovered["persisted_signals"], 1)
        self.assertEqual(self.state(engine.store)["signals"], 1)

    def test_later_work_proceeds_after_pending_scan_recovery_with_committed_zone_state(self):
        engine = self.engine()
        def fail(boundary):
            if boundary == "after_input_commit":
                raise RuntimeError("OFFLINE input acknowledgement lost")
        with patch.object(engine.store, "_lineage_checkpoint", side_effect=fail), self.assertRaises(RuntimeError):
            engine.run_single_scan()
        pending = engine.store.pending_cash_scans()[0]["run_id"]
        risk = engine.config.max_risk_per_trade_pct
        engine.config.max_risk_per_trade_pct = risk * 0.5
        with self.assertRaisesRegex(PersistenceValidationError, "PRIOR_SCAN_REQUIRES_RECOVERY"):
            engine.run_single_scan()
        engine.config.max_risk_per_trade_pct = risk
        first = engine.resume_cash_scan(pending)
        self.assertEqual(first["persisted_signals"], 1)
        engine.config.max_risk_per_trade_pct = risk * 0.5
        later = engine.run_single_scan()
        self.assertNotEqual(later["run_id"], pending)
        self.assertEqual(engine.store.load_cash_scan(later["run_id"])["status"], "COMMITTED")
        self.assertEqual(self.state(engine.store)["cash_candle_facts"], 60)
        self.assertEqual(self.state(engine.store)["signals"], 1)

    def test_expiry_after_staged_signal_rolls_back_and_reports_zero_committed_signals(self):
        from brokers import CandleFreshnessError
        engine = self.engine()
        def expire(boundary):
            if boundary == "after_signal_write":
                self.scenario.now += timedelta(minutes=12)
        with patch.object(engine.store, "_lineage_checkpoint", side_effect=expire), \
                patch.object(engine.telegram, "send_signal") as delivery, self.assertRaises(CandleFreshnessError):
            engine.run_single_scan()
        delivery.assert_not_called()
        self.assertEqual(engine.last_scan_summary["persisted_signals"], 0)
        state = self.state(engine.store)
        self.assertEqual((state["signals"], state["scan_runs"], state["scoped_mitigated_order_blocks"]), (0, 0, 0))
        self.assertEqual(engine.store.pending_cash_scans()[0]["status"], "PENDING")

    def test_overlapping_recovery_cannot_replace_original_committed_scan_outcome(self):
        engine = self.engine()
        result = engine.run_single_scan()
        original = engine.store.load_cash_scan(result["run_id"])
        engine._scan_lock.acquire()
        try:
            skipped = engine.resume_cash_scan(result["run_id"])
        finally:
            engine._scan_lock.release()
        self.assertEqual(skipped["scan_status"], "SKIPPED_OVERLAP")
        self.assertEqual(engine.store.load_cash_scan(result["run_id"]), original)
        self.assertTrue(engine.resume_cash_scan(result["run_id"])["idempotent_replay"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
