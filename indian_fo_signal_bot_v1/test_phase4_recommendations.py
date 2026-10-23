"""Independent Phase 4 QA: deterministic fixtures, memory SQLite, forbidden network.

Provider-shaped candle provenance below exercises existing LIVE validation contracts
only. Every feed here is an explicit test double; no receipt or operational market
acceptance can be obtained from this module.
"""
import copy
import hashlib
import itertools
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import test_bot  # established credential-free process configuration bootstrap

from brokers import BrokerDataError, MultiBrokerScanner, SimulatedNSEAdapter
from config import BotConfig
from instrument_identity import bind_candles, spot_identity
from scanner_engine import IntradayBotEngine
from storage import SQLitePersistenceStore
from strategies import IST, evaluate_order_block_fvg, parse_ist_timestamp, rank_signal_candidates


class _OfflineFeed:
    """No transport; status can change independently of cached completed candles."""
    provider = "angelone"

    def __init__(self, rows):
        self.rows = rows
        self.state = "LIVE"
        self.allowed = True
        self.stopped = False

    def status(self):
        return dict(provider=self.provider, status=self.state,
                    live_signal_allowed=self.allowed,
                    evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE")

    def get_candles(self, meta, interval, *, now):
        if self.state != "LIVE" or not self.allowed:
            raise ValueError("OFFLINE unavailable feed")
        return copy.deepcopy(self.rows)

    def stop(self):
        self.stopped = True


class TestPhase4IndependentRecommendations(unittest.TestCase):
    def setUp(self):
        self.clock_value = datetime(2026, 10, 16, 14, 15, 5, tzinfo=IST)
        for target in ("urllib.request.urlopen", "socket.create_connection", "socket.socket.connect"):
            guard = patch(target, side_effect=AssertionError("Independent QA forbids network"))
            guard.start()
            self.addCleanup(guard.stop)

    def engine(self, *, rows=None, symbol="RELIANCE"):
        cfg = BotConfig(active_broker="angelone", angel_api_key="OFFLINE_KEY",
            angel_client_code="OFFLINE_CLIENT", angel_pin="7531",
            angel_totp_secret="JBSWY3DPEHPK3PXP", angel_scrip_master_path="",
            angel_min_request_interval_seconds=0, database_url=":memory:",
            telegram_dry_run=True, enable_background_scheduler=False, enable_persistence=True)
        cfg.fo_indices = {}
        cfg.equity_watchlist = [copy.deepcopy(m) for m in cfg.equity_watchlist if m["symbol"] == symbol]
        if rows is None:
            bars = SimulatedNSEAdapter(seed=42, clock=lambda: self.clock_value).get_intraday_candles(
            {"symbol": symbol}, interval_min=5, pattern="order_block_bull")[-60:]
            opening = self.clock_value.replace(hour=9, minute=15, second=0)
            rows = [dict(timestamp=(opening+timedelta(minutes=5*i)).isoformat(),
                         **{field: bar[field] for field in ("open", "high", "low", "close", "volume")})
                    for i, bar in enumerate(bars)]
            rows.append(dict(timestamp=self.clock_value.replace(second=0).isoformat(),
                open=9990, high=10020, low=9980, close=10000, volume=999999))
        canonical = bind_candles([dict(row, timestamp=parse_ist_timestamp(row["timestamp"]).isoformat(),
            is_simulated=False, data_mode="LIVE", interval_min=5,
            is_complete=parse_ist_timestamp(row["timestamp"])+timedelta(minutes=5) <= self.clock_value,
            timestamp_timezone="Asia/Kolkata") for row in rows], spot_identity(cfg.equity_watchlist[0], "angelone"))
        feed = _OfflineFeed(canonical)
        scanner = MultiBrokerScanner(cfg, clock=lambda: self.clock_value)
        scanner.adapters["angelone"].attach_live_feed(feed)
        store = SQLitePersistenceStore(":memory:")
        self.addCleanup(store.close)
        engine = IntradayBotEngine(cfg, clock=lambda: self.clock_value, broker_scanner=scanner, store=store)
        self.addCleanup(engine.close)
        return engine, feed

    def test_disconnect_after_actual_evaluation_blocks_commit_and_notification(self):
        engine, feed = self.engine()
        actual = evaluate_order_block_fvg
        def disconnect_after_evaluation(*args, **kwargs):
            result = actual(*args, **kwargs)
            self.assertIsNotNone(result, "The unchanged real evaluator must detect the fixture setup")
            feed.state, feed.allowed = "DISCONNECTED", False
            return result
        with (patch("scanner_engine.evaluate_order_block_fvg", side_effect=disconnect_after_evaluation),
              patch.object(engine.telegram, "send_signal") as delivery,
              self.assertRaises(BrokerDataError)):
            engine.run_single_scan()
        delivery.assert_not_called()
        self.assertEqual(engine.store.query_signals()["total_count"], 0)
        self.assertEqual(engine.store.list_notification_outbox()["items"], [])
        self.assertEqual(engine.last_scan_summary["total_signals"], 0)

    def test_quality_degradation_after_evaluation_blocks_even_while_stream_is_connected(self):
        engine, feed = self.engine()
        def degrade_after_detection(*args, **kwargs):
            signal = evaluate_order_block_fvg(*args, **kwargs)
            self.assertIsNotNone(signal)
            feed.allowed = False
            self.assertEqual(feed.state, "LIVE")
            return signal
        with (patch("scanner_engine.evaluate_order_block_fvg", side_effect=degrade_after_detection),
              patch.object(engine.telegram, "send_signal") as delivery,
              self.assertRaises(BrokerDataError)):
            engine.run_single_scan()
        delivery.assert_not_called()
        self.assertEqual(engine.store.query_signals()["total_count"], 0)
        self.assertEqual(engine.store.list_notification_outbox()["items"], [])

    def test_disconnect_after_staged_write_or_last_commit_checkpoint_rolls_back(self):
        for checkpoint in ("after_signal_write", "before_result_commit"):
            with self.subTest(checkpoint=checkpoint):
                engine, feed = self.engine()
                def disconnect(boundary):
                    if boundary == checkpoint:
                        feed.state, feed.allowed = "DISCONNECTED", False
                with (patch.object(engine.store, "_lineage_checkpoint", side_effect=disconnect),
                      patch.object(engine.store, "preview_notification") as preview,
                      self.assertRaises(BrokerDataError)):
                    engine.run_single_scan()
                preview.assert_not_called()
                self.assertEqual(engine.store.query_signals()["total_count"], 0)
                self.assertEqual(engine.store.query_scan_runs()["total_count"], 0)
                self.assertEqual(engine.store.list_notification_outbox()["items"], [])
                self.assertEqual(engine.last_scan_summary["total_signals"], 0)

    def test_disconnect_after_commit_keeps_history_but_revokes_current_readiness_and_preview(self):
        engine, feed = self.engine()
        def disconnect(boundary):
            if boundary == "after_result_commit":
                feed.state, feed.allowed = "DISCONNECTED", False
        with (patch.object(engine.store, "_lineage_checkpoint", side_effect=disconnect),
              patch.object(engine.store, "preview_notification") as preview):
            summary = engine.run_single_scan()
        preview.assert_not_called()
        self.assertEqual(engine.store.query_signals()["total_count"], 1)
        self.assertEqual(summary["candidate_evaluations"][0]["status"], "QUALIFIED")
        self.assertFalse(summary["candidate_evaluations"][0]["actionable"])
        self.assertFalse(summary["candle_freshness"]["live_signal_allowed"])
        self.assertTrue(summary["telegram_dispatches"][0]["skipped"])

    def test_ranking_all_permutations_and_exact_identity_ties_are_reproducible(self):
        from test_completion_engineering import signal_fixture
        first = signal_fixture(rationale="A", risk_reward="untrusted display label")
        second = signal_fixture(rationale="B", risk_reward="untrusted display label")
        third = signal_fixture(symbol="INFY", instrument_label="INFY EQ", quality_score=80)
        expected = [s.to_dict() for s in rank_signal_candidates([first, second, third])]
        for order in itertools.permutations([first, second, third]):
            before = copy.deepcopy([s.to_dict() for s in order])
            self.assertEqual([s.to_dict() for s in rank_signal_candidates(list(order))], expected)
            self.assertEqual([s.to_dict() for s in order], before)
        self.assertEqual(expected[0]["symbol"], "INFY")
        self.assertEqual([s["rationale"] for s in expected[1:]], ["A", "B"])

    def test_attractive_quality_cannot_admit_invalid_risk_geometry(self):
        from test_completion_engineering import signal_fixture
        for changes in (dict(stop_loss=100), dict(stop_loss=101), dict(target_1=99),
                        dict(invalidation_level=101), dict(target_2=103),
                        dict(entry_price=float("nan")), dict(stop_loss=0)):
            bad = signal_fixture(quality_score=100, **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rank_signal_candidates([signal_fixture(), bad])

    def test_valid_fixture_uses_actual_scanner_and_excludes_forming_tail_from_lineage(self):
        engine, feed = self.engine()
        summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 1)
        self.assertEqual(summary["signals"][0]["entry_price"], 2955.74)
        self.assertNotEqual(summary["signals"][0]["entry_price"], feed.rows[-1]["close"])
        work = engine.store.load_cash_scan(summary["run_id"])
        retained = work["snapshot"]["batches"][0]["content"]["candles"]
        self.assertEqual(len(retained), 60)
        self.assertTrue(all(row["is_complete"] for row in retained))
        self.assertTrue(all(row["close"] != 10000 for row in retained))
        self.assertEqual(engine.store.query_signals()["total_count"], 1)
        self.assertEqual(engine.store.load_live_acceptance_evidence("angelone", "RELIANCE"), None)

    def test_invalid_candle_inputs_never_reach_actual_strategy_or_outputs(self):
        mutations = (
            ("wrong_identifier", lambda rows: rows[0]["instrument_identity"].update(identifier="999")),
            ("wrong_exchange", lambda rows: rows[0]["instrument_identity"].update(exchange="BSE")),
            ("gap", lambda rows: rows.pop(15)),
            ("duplicate", lambda rows: rows.insert(1, copy.deepcopy(rows[0]))),
            ("disorder", lambda rows: rows.reverse()),
            ("missing_volume", lambda rows: rows[0].pop("volume")),
            ("negative_volume", lambda rows: rows[0].update(volume=-1)),
            ("future", lambda rows: rows[-1].update(timestamp="2026-10-16T14:25:00+05:30")),
            ("out_of_session", lambda rows: rows[0].update(timestamp="2026-10-16T08:55:00+05:30")),
            ("ambiguous_timezone", lambda rows: (rows[0].pop("timestamp_timezone"),
                 rows[0].update(timestamp="2026-10-16 09:15:00"))),
        )
        for name, mutate in mutations:
            with self.subTest(case=name):
                engine, feed = self.engine()
                mutate(feed.rows)
                with (patch("scanner_engine.evaluate_order_block_fvg") as evaluator,
                      patch.object(engine.telegram, "send_signal") as delivery,
                      self.assertRaises(BrokerDataError)):
                    engine.run_single_scan()
                evaluator.assert_not_called()
                delivery.assert_not_called()
                self.assertEqual(engine.store.query_signals()["total_count"], 0)

    def test_real_scanner_candidate_has_numeric_risk_rank_and_supported_rule_explanations(self):
        engine, _ = self.engine()
        summary = engine.run_single_scan()
        records = summary["strategy_evaluations"]
        self.assertEqual({r["strategy_id"] for r in records}, {
            "strat_1_order_block", "strat_2_vwap_pullback",
            "strat_4_orb_filtered", "strat_5_supertrend_pullback"})
        detected = next(r for r in records if r["strategy_id"] == "strat_1_order_block")
        self.assertEqual(detected["status"], "DETECTED")
        self.assertTrue(detected["reason_codes"])
        self.assertTrue(detected["rule_checks"])
        warmup = next(r for r in records if r["strategy_id"] == "strat_5_supertrend_pullback")
        self.assertEqual(warmup["status"], "UNAVAILABLE")
        self.assertTrue(warmup["reason_codes"])
        self.assertIsInstance(warmup["warmup"], dict)
        candidates = summary["candidate_evaluations"]
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual((candidate["status"], candidate["symbol"], candidate["strategy_id"]),
                         ("QUALIFIED", "RELIANCE", "strat_1_order_block"))
        self.assertFalse(candidate["actionable"])
        self.assertTrue(candidate["candidate_id"])
        self.assertEqual(candidate["ranking"]["rank"], 1)
        self.assertTrue(candidate["ranking"]["qualified"])
        self.assertEqual(candidate["ranking"]["policy"],
                         "QUALITY_THEN_TARGET1_REWARD_RISK_THEN_IDENTITY_V1")
        signal = summary["signals"][0]
        numeric = candidate["risk_reward"]
        # Independent arithmetic over persisted candidate prices, not a display ratio.
        self.assertAlmostEqual(numeric["risk_per_unit"], signal["entry_price"]-signal["stop_loss"])
        self.assertAlmostEqual(numeric["reward_t1_per_unit"], signal["target_1"]-signal["entry_price"])
        self.assertAlmostEqual(numeric["reward_t2_per_unit"], signal["target_2"]-signal["entry_price"])
        self.assertAlmostEqual(numeric["target1_ratio"], numeric["reward_t1_per_unit"]/numeric["risk_per_unit"])
        self.assertAlmostEqual(numeric["target2_ratio"], numeric["reward_t2_per_unit"]/numeric["risk_per_unit"])
        source = candidate["source_reference"]
        self.assertEqual(source["batch_ids"], summary["input_lineage"]["batch_ids"])
        self.assertEqual(source["run_id"], summary["run_id"])
        self.assertEqual(source["provider"], "angelone")
        self.assertEqual(source["instrument_identity"], signal["instrument_identity"])
        self.assertTrue(source["candle_timestamps"])
        self.assertTrue(all(parse_ist_timestamp(stamp)+timedelta(minutes=5) <= self.clock_value
                            for stamp in source["candle_timestamps"]))
        self.assertIsNone(candidate.get("win_probability"))
        self.assertTrue({"LIQUIDITY_NOT_ESTABLISHED", "FILL_AND_SLIPPAGE_NOT_ESTABLISHED",
                         "EMPIRICAL_PERFORMANCE_UNAVAILABLE", "NET_TARGET_RR_UNAVAILABLE"}
                        <= set(candidate["warnings"]))

    def test_explanation_persistence_and_idempotent_retry_keep_same_source_and_candidate(self):
        engine, _ = self.engine()
        first = engine.run_single_scan()
        retained = engine.store.load_cash_scan(first["run_id"])["result"]
        self.assertEqual(retained["strategy_evaluations"], first["strategy_evaluations"])
        self.assertEqual(retained["candidate_evaluations"], first["candidate_evaluations"])
        repeated = engine.run_single_scan()
        self.assertTrue(repeated["idempotent_replay"])
        self.assertEqual(repeated["candidate_evaluations"], first["candidate_evaluations"])
        self.assertEqual(repeated["strategy_evaluations"], first["strategy_evaluations"])
        self.assertEqual(repeated["signals"], [])
        self.assertEqual(engine.store.query_signals()["total_count"], 1)
        self.assertEqual(engine.store.query_scan_runs()["total_count"], 1)

    def test_existing_api_history_and_scan_routes_expose_same_reconciled_candidate(self):
        from server import DashboardRequestHandler
        engine, _ = self.engine()
        summary = engine.run_single_scan()
        # Invoke the real route handlers without creating any listening socket.
        handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
        handler.engine = engine
        handler.paper_portfolio = None
        handler.evidence_scope = "OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE"
        code, payload = handler._handle_signals({})
        self.assertEqual(code, 200)
        item = payload["items"][0]
        self.assertEqual(item["candidate_evaluation"], summary["candidate_evaluations"][0])
        self.assertFalse(item["actionable"])
        self.assertEqual(item["recommendation_status"], "CANDIDATE_ONLY")
        self.assertFalse(item["lineage"]["current_live_acceptance"])
        code, scans = handler._handle_scans({})
        self.assertEqual(code, 200)
        evaluation = scans["items"][0]["evaluation"]
        self.assertEqual(evaluation["strategy_evaluations"], summary["strategy_evaluations"])
        self.assertEqual(evaluation["candidate_evaluations"], summary["candidate_evaluations"])

    def test_corrupt_or_rehashed_inconsistent_explanations_fail_both_existing_read_routes(self):
        from server import DashboardRequestHandler
        for rehash in (False, True):
            with self.subTest(recompute_checksum=rehash):
                engine, _ = self.engine()
                summary = engine.run_single_scan()
                with engine.store.paper_transaction(write=True) as conn:
                    row = conn.execute("SELECT payload_json FROM scan_evaluations WHERE run_id=?",
                                       (summary["run_id"],)).fetchone()
                    payload = json.loads(row[0])
                    payload["candidate_evaluations"][0]["risk_reward"]["target1_ratio"] = 999
                    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    if rehash:
                        checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
                        conn.execute("UPDATE scan_evaluations SET payload_json=?,payload_sha256=? WHERE run_id=?",
                                     (body, checksum, summary["run_id"]))
                    else:
                        conn.execute("UPDATE scan_evaluations SET payload_json=? WHERE run_id=?",
                                     (body, summary["run_id"]))
                handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
                handler.engine, handler.paper_portfolio = engine, None
                handler.evidence_scope = "OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE"
                for method in (handler._handle_signals, handler._handle_scans):
                    code, response = method({})
                    self.assertEqual(code, 503)
                    self.assertNotIn("items", response)
                    self.assertNotIn("999", json.dumps(response))

    def test_shutdown_stops_attached_fixture_and_preserves_safe_configuration(self):
        engine, feed = self.engine()
        self.assertEqual(engine.config.database_url, ":memory:")
        engine.close()
        self.assertTrue(feed.stopped)
        self.assertIsNone(engine.broker.adapters["angelone"].live_feed)
        self.assertEqual(engine.config.active_broker, "angelone")
        self.assertTrue(engine.config.telegram_dry_run)
        self.assertFalse(engine.config.enable_background_scheduler)

    def test_insufficient_completed_history_is_explicit_nonactionable_not_silent_setup(self):
        engine, feed = self.engine()
        feed.rows = feed.rows[-21:]  # 20 completed observations plus forming tail.
        summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 0)
        self.assertEqual(summary["candidate_evaluations"], [])
        by_strategy = {item["strategy_id"]: item for item in summary["strategy_evaluations"]}
        for strategy in ("strat_1_order_block", "strat_5_supertrend_pullback"):
            item = by_strategy[strategy]
            self.assertEqual(item["status"], "UNAVAILABLE")
            self.assertTrue(item["reason_codes"])
            self.assertTrue(item["warmup"])
        work = engine.store.load_cash_scan(summary["run_id"])
        self.assertEqual(work["result"]["strategy_evaluations"], summary["strategy_evaluations"])
        self.assertEqual(engine.store.query_signals()["total_count"], 0)

    def test_fresh_partial_session_cannot_invent_session_vwap_or_qualify_original_setup(self):
        engine, feed = self.engine()
        self.assertEqual(parse_ist_timestamp(feed.rows[0]["timestamp"]).strftime("%H:%M"), "09:15")
        feed.rows.pop(0)
        self.assertEqual(parse_ist_timestamp(feed.rows[0]["timestamp"]).strftime("%H:%M"), "09:20")
        # This is a contiguous, fresh tail with enough flat warm-up. It cannot
        # establish the missing full-session VWAP required by the actual rules.
        summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 0)
        self.assertEqual(summary["candidate_evaluations"], [])
        for strategy in ("strat_1_order_block", "strat_2_vwap_pullback"):
            trace = next(row for row in summary["strategy_evaluations"] if row["strategy_id"] == strategy)
            self.assertEqual(trace["status"], "UNAVAILABLE")
            self.assertIn("SESSION_START_COVERAGE_MISSING", trace["reason_codes"])
        self.assertEqual(engine.store.query_signals()["total_count"], 0)

    def test_partial_session_peer_cannot_contribute_invented_vwap_breadth(self):
        now = self.clock_value.replace(hour=9, minute=25)
        full = [
            dict(timestamp="2026-10-16T09:15:00+05:30", open=100, high=104,
                 low=99, close=103, volume=1000, is_complete=True, is_simulated=True),
            dict(timestamp="2026-10-16T09:20:00+05:30", open=103, high=111,
                 low=102, close=110, volume=1000, is_complete=True, is_simulated=True),
        ]
        partial = [copy.deepcopy(full[-1])]
        # A complete opening-to-current comparator still supplies genuine fixture
        # breadth; a lone later peer has no session VWAP baseline to contribute.
        self.assertEqual(IntradayBotEngine._compute_universe_breadth({"FULL": full}, now),
                         {"advances": 1, "declines": 0})
        self.assertEqual(IntradayBotEngine._compute_universe_breadth(
            {"FULL": full, "PARTIAL": partial}, now), {"advances": 1, "declines": 0})
        self.assertIsNone(IntradayBotEngine._compute_universe_breadth({"PARTIAL": partial}, now))

    def test_fully_warmed_supertrend_reaches_actual_scanner_without_relaxing_lookback(self):
        self.clock_value = self.clock_value.replace(hour=10, minute=35)
        bars = SimulatedNSEAdapter(seed=42, clock=lambda: self.clock_value).get_intraday_candles(
            {"symbol": "SBIN"}, interval_min=5, pattern="supertrend_pullback_bull")
        # Preserve all original fixture session timestamps; no missing history is filled.
        rows = [{name: row[name] for name in ("timestamp", "open", "high", "low", "close", "volume")}
                for row in bars]
        engine, _ = self.engine(rows=rows, symbol="SBIN")
        summary = engine.run_single_scan()
        detailed = next(item for item in summary["strategy_evaluations"]
                        if item["strategy_id"] == "strat_5_supertrend_pullback")
        self.assertEqual(detailed["status"], "DETECTED")
        candidate = next(item for item in summary["candidate_evaluations"]
                         if item["strategy_id"] == "strat_5_supertrend_pullback")
        self.assertEqual(candidate["status"], "QUALIFIED")
        self.assertFalse(candidate["actionable"])
        retained = engine.store.load_cash_scan(summary["run_id"])["snapshot"]["batches"][0]
        self.assertGreaterEqual(len(retained["content"]["candles"]), 200)

    def test_existing_vwap_and_orb_fixtures_are_explained_through_actual_scanner(self):
        self.clock_value = self.clock_value.replace(hour=10, minute=35)
        for symbol, pattern, strategy in (
            ("TCS", "vwap_pullback_bull", "strat_2_vwap_pullback"),
            ("ICICIBANK", "orb_breakout_bull", "strat_4_orb_filtered"),
        ):
            with self.subTest(strategy=strategy):
                bars = SimulatedNSEAdapter(seed=42, clock=lambda: self.clock_value).get_intraday_candles(
                    {"symbol": symbol}, interval_min=5, pattern=pattern)
                rows = [{key: row[key] for key in ("timestamp", "open", "high", "low", "close", "volume")}
                        for row in bars]
                engine, _ = self.engine(rows=rows, symbol=symbol)
                summary = engine.run_single_scan()
                trace = next(row for row in summary["strategy_evaluations"] if row["strategy_id"] == strategy)
                self.assertEqual(trace["status"], "DETECTED")
                self.assertTrue(trace["rule_checks"])
                candidate = next(row for row in summary["candidate_evaluations"] if row["strategy_id"] == strategy)
                self.assertEqual(candidate["status"], "QUALIFIED")
                self.assertFalse(candidate["actionable"])
                self.assertEqual(candidate["source_reference"]["instrument_identity"]["symbol"], symbol)

    def test_detected_setup_with_invalid_target_is_preserved_as_rejected_not_ranked(self):
        engine, _ = self.engine()
        def corrupt_after_actual_detection(*args, **kwargs):
            signal = evaluate_order_block_fvg(*args, **kwargs)
            self.assertIsNotNone(signal)
            signal.target_1 = signal.entry_price
            signal.quality_score = 100
            return signal
        with patch("scanner_engine.evaluate_order_block_fvg", side_effect=corrupt_after_actual_detection):
            summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 0)
        rejected = next(item for item in summary["candidate_evaluations"]
                        if item["strategy_id"] == "strat_1_order_block")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertFalse(rejected["actionable"])
        self.assertFalse(rejected["ranking"]["qualified"])
        self.assertIsNone(rejected["ranking"]["rank"])
        self.assertTrue(rejected["reason_codes"])
        self.assertEqual(engine.store.query_signals()["total_count"], 0)
        self.assertEqual(engine.store.load_cash_scan(summary["run_id"])["result"]["candidate_evaluations"],
                         summary["candidate_evaluations"])

    def test_stale_and_forming_only_inputs_never_publish_candidates(self):
        for case in ("stale", "forming_only"):
            with self.subTest(case=case):
                engine, feed = self.engine()
                if case == "stale":
                    self.clock_value += timedelta(minutes=15)
                else:
                    feed.rows = feed.rows[-1:]
                with (patch.object(engine.telegram, "send_signal") as delivery,
                      self.assertRaises(BrokerDataError)):
                    engine.run_single_scan()
                delivery.assert_not_called()
                self.assertEqual(engine.store.query_signals()["total_count"], 0)


if __name__ == "__main__":
    unittest.main()
