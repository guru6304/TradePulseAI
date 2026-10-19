"""OFFLINE SIMULATED fixtures: recovery, EOD and bounded ledger reporting.

Large ledgers clone a real service-generated lifecycle graph onto explicit
weekday fixture dates. They test storage/accounting structure, not market prices,
strategy performance, liquidity or authoritative exchange sessions.
"""
import copy
import http.client
import json
import os
import sqlite3
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
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
from paper_portfolio import FORWARD_FILL_POLICY, PaperPortfolio, PaperPortfolioError, _encode, _hash
from server import DashboardRequestHandler, create_http_server
from storage import SQLitePersistenceStore
from strategies import IST, signal_state_identity


class TestPhase5CRecovery(unittest.TestCase):
    def setUp(self):
        from test_phase5b_forward import TestPhase5BForwardPaper
        self.h = TestPhase5BForwardPaper()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.f, self.paper, self.coordinator = self.h.fixture, self.h.paper, self.h.coordinator
        self.store = self.f.store

    def restart(self, paper=None):
        store = SQLitePersistenceStore(self.f.database)
        self.addCleanup(store.close)
        return PaperPortfolio(store, (paper or self.paper).config, clock=lambda: self.f.now)

    def enter(self, paper=None, stamp="10:00"):
        paper = paper or self.paper
        candidate = self.f._candidate(paper, stamp=stamp)
        bar_stamp = (datetime.fromisoformat(candidate.timestamp) + timedelta(minutes=5)).strftime("%H:%M")
        return paper.enter(candidate, self.f._bar(candidate, stamp=bar_stamp), "entry"), candidate

    def eod_entry(self, **config):
        paper = self.f._service(account_id="eod", fill_policy=FORWARD_FILL_POLICY, **config)
        self.f._set_time("15:15")
        result, candidate = self.enter(paper, "15:05")
        return paper, result, candidate, self.f._bar(candidate, stamp="15:15", close=101)

    def assert_code(self, code, action):
        with self.assertRaises(PaperPortfolioError) as caught:
            action()
        self.assertEqual(caught.exception.reason_code, code)

    def test_missing_eod_survives_weekend_restart_without_release_or_next_day_fill(self):
        paper, result, candidate, bar = self.eod_entry(cost_model_json="{}")
        before = paper.snapshot()
        self.f._set_time("10:10", date="2026-10-19")  # supplied Monday fixture, no holiday authority claimed
        paper = self.restart(paper)
        after = paper.snapshot()
        self.assertEqual(after["accounting"]["reserved_capital_inr"], before["accounting"]["reserved_capital_inr"])
        self.assertEqual(after["accounting"]["fees_paid_inr"], 0)
        self.assertEqual(after["accounting"]["closed_positions"], 0)
        self.assertEqual(after["total_events"], before["total_events"])
        self.assertIn("UNRESOLVED_EOD_POSITION", after["entry_blocks"])
        self.assertIn("MISSING_OR_STALE_MARKS", after["entry_blocks"])
        today = dict(bar, timestamp="2026-10-19T10:05:00+05:30")
        self.assert_code("MISSING_OR_OUT_OF_ORDER_POSITION_BAR", lambda: paper.process_bar(result["position_id"], today, "next-day"))
        self.assert_code("INVALID_STALE_OR_UNFINISHED_BAR", lambda: paper.process_bar(result["position_id"], bar, "late-yesterday"))
        new = self.f._candidate(paper).to_dict()
        new["timestamp"] = "2026-10-19 10:00:00"
        with self.assertRaises(PaperPortfolioError):
            paper.enter(new, today, "new-day-entry")
        self.assertEqual(paper.snapshot(), after)

    def test_eod_exact_delay_boundary_incomplete_and_late_bars(self):
        paper, result, candidate, bar = self.eod_entry(cost_model_json="{}")
        before = paper.snapshot()["accounting"]
        self.f.now = datetime(2026, 10, 16, 15, 21, 0, 1, tzinfo=IST)
        self.assert_code("INVALID_STALE_OR_UNFINISHED_BAR", lambda: paper.process_bar(result["position_id"], bar, "late"))
        self.f.now = datetime(2026, 10, 16, 15, 21, tzinfo=IST)  # inclusive configured 60 seconds
        self.assert_code("COMPLETED_SOURCE_BAR_REQUIRED", lambda: paper.process_bar(result["position_id"], dict(bar, is_complete=False), "unfinished"))
        self.assertEqual(paper.snapshot()["accounting"], before)
        closed = paper.process_bar(result["position_id"], bar, "eod")
        self.assertEqual(closed["exit_reason"], "EOD")
        after = paper.snapshot()
        self.f._set_time("10:10", date="2026-10-19")
        self.assertTrue(self.restart(paper).process_bar(result["position_id"], bar, "eod")["idempotent"])
        report = paper.snapshot()
        self.assertEqual(report["accounting"]["fees_paid_inr"], after["accounting"]["fees_paid_inr"])
        self.assertGreater(report["accounting"]["fees_paid_inr"], 0)
        self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
        self.assert_code("POSITION_ALREADY_CLOSED", lambda: paper.process_bar(result["position_id"], bar, "another-exit"))

    def test_realized_daily_loss_resets_at_ist_midnight_lifetime_costs_do_not(self):
        paper = self.f._service(account_id="daily", fill_policy=FORWARD_FILL_POLICY, max_daily_loss_inr=10, cost_model_json="{}")
        result, candidate = self.enter(paper)
        self.f._set_time("10:15")
        paper.process_bar(result["position_id"], self.f._bar(candidate, stamp="10:10", low=85, close=88), "loss")
        before = paper.snapshot()["accounting"]
        self.assertTrue(before["day"]["loss_limit_breached"])
        self.f.now = datetime.fromisoformat("2026-10-16T18:29:59+00:00")  # 23:59:59 IST
        self.assertTrue(paper.snapshot()["accounting"]["day"]["loss_limit_breached"])
        self.f.now += timedelta(seconds=1)
        after = self.restart(paper).snapshot()["accounting"]
        self.assertEqual(after["day"]["date"], "2026-10-17")
        self.assertEqual(after["day"]["entries"], 0)
        self.assertEqual(after["day"]["realized_net_pnl_inr"], 0)
        self.assertFalse(after["day"]["loss_limit_breached"])
        for key in ("realized_net_pnl_inr", "equity_inr", "fees_paid_inr", "slippage_paid_inr"):
            self.assertEqual(after[key], before[key])

    def test_normal_eod_then_next_session_entry_resets_daily_limits_only(self):
        paper, result, candidate, bar = self.eod_entry(max_daily_loss_inr=5, max_entries_per_day=1)
        self.f._set_time("15:20")
        paper.process_bar(result["position_id"], bar, "eod")
        closed = paper.snapshot()
        self.assertIn("DAILY_LOSS_LIMIT", closed["entry_blocks"])
        self.assertIn("DAILY_ENTRY_LIMIT", closed["entry_blocks"])
        self.f._set_time("10:10", date="2026-10-19")
        paper = self.restart(paper)
        fresh = paper.snapshot()
        self.assertEqual(fresh["entry_blocks"], [])
        candidate = self.f._candidate(paper).to_dict()
        candidate["timestamp"] = "2026-10-19 10:00:00"
        bar = self.f._bar(self.f._candidate(paper), timestamp="2026-10-19T10:05:00+05:30")
        paper.enter(candidate, bar, "monday-entry")
        after = paper.snapshot()
        self.assertEqual(after["accounting"]["day"]["entries"], 1)
        self.assertEqual(after["accounting"]["day"]["realized_net_pnl_inr"], 0)
        self.assertEqual(after["accounting"]["closed_positions"], 1)
        self.assertEqual(after["accounting"]["open_positions"], 1)
        self.assertEqual(after["accounting"]["realized_net_pnl_inr"], closed["accounting"]["realized_net_pnl_inr"])
        self.assertEqual(after["reconciliation"]["status"], "OK")

    def test_fresh_later_eod_bar_cannot_replace_missing_required_observation(self):
        paper, result, candidate, bar = self.eod_entry()
        before = paper.snapshot()
        self.f._set_time("15:25")
        self.assert_code("MISSING_OR_OUT_OF_ORDER_POSITION_BAR", lambda: paper.process_bar(result["position_id"],
            dict(bar, timestamp="2026-10-16T15:20:00+05:30"), "skip-eod"))
        after = paper.snapshot()
        self.assertEqual(after["accounting"], before["accounting"])
        self.assertEqual(after["total_events"], before["total_events"])
        self.assertIn("UNRESOLVED_EOD_POSITION", after["entry_blocks"])

    def test_open_loss_is_carried_into_next_ist_day_and_calendar_rejects_fixture_holiday(self):
        paper = self.f._service(account_id="carry", fill_policy=FORWARD_FILL_POLICY, max_daily_loss_inr=10,
                                configured_holidays=("2026-10-19",))
        candidate = self.f._candidate(paper)
        paper.enter(candidate, self.f._bar(candidate, close=100), "entry")
        self.f._set_time("10:15")
        position = paper.snapshot()["positions"][0]
        paper.process_bar(position["position_id"], self.f._bar(candidate, stamp="10:10", low=94, close=95), "mark")
        self.f._set_time("10:10", date="2026-10-19")
        after = self.restart(paper).snapshot()
        self.assertLess(after["accounting"]["day"]["unrealized_net_pnl_inr"], -10)
        self.assertTrue(after["accounting"]["day"]["loss_limit_breached"])
        self.assert_code("INVALID_STALE_OR_UNFINISHED_BAR", lambda: paper.process_bar(position["position_id"],
            self.f._bar(candidate, timestamp="2026-10-19T10:05:00+05:30"), "holiday"))

    def test_restart_before_observation_and_after_receipt_matches_uninterrupted_fill(self):
        candidate = self.f._candidate(self.paper)
        summary = self.h._summary(candidate)
        self.coordinator._queue(summary)
        queued = self.paper.snapshot()
        restarted = self.restart()
        coordinator = ForwardPaperCoordinator(restarted)
        received = self.f._bar(candidate)  # received, not yet durably consumed
        self.assertEqual(restarted.snapshot(), queued)
        coordinator.consume_scan(summary, {candidate.symbol: [received]})
        committed = restarted.snapshot()
        coordinator = ForwardPaperCoordinator(self.restart())
        coordinator.consume_scan(summary, {candidate.symbol: [received]})
        self.assertEqual(coordinator.paper.snapshot(), committed)

    def test_candidate_decision_failure_and_entry_boundaries_roll_back_every_effect(self):
        candidate = self.f._candidate(self.paper)
        summary = self.h._summary(candidate)
        with self.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER phase5c_fault BEFORE INSERT ON paper_candidate_decisions BEGIN SELECT RAISE(ABORT,'OFFLINE fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.coordinator._queue(summary)
        self.assertEqual(self.paper.snapshot()["candidate_decisions"], [])
        with self.store.paper_transaction() as conn:
            conn.execute("DROP TRIGGER phase5c_fault")
        self.coordinator._queue(summary)
        decision = self.paper.snapshot()["candidate_decisions"][0]["candidate_id"]
        stages = (
            "AFTER INSERT ON paper_positions",
            "BEFORE INSERT ON paper_events WHEN NEW.kind='ENTRY'",
            "BEFORE UPDATE ON paper_positions",
            "BEFORE INSERT ON paper_events WHEN NEW.kind='MARK'",
            "BEFORE UPDATE ON paper_candidate_decisions",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                before = self.paper.snapshot()
                with self.store.paper_transaction() as conn:
                    conn.execute("CREATE TRIGGER phase5c_fault " + stage + " BEGIN SELECT RAISE(ABORT,'OFFLINE fault'); END")
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.paper.enter(candidate, self.f._bar(candidate), decision, candidate_decision_id=decision)
                    self.assertEqual(self.restart().snapshot(), before)
                finally:
                    with self.store.paper_transaction() as conn:
                        conn.execute("DROP TRIGGER phase5c_fault")
        self.paper.enter(candidate, self.f._bar(candidate), decision, candidate_decision_id=decision)
        self.assertEqual(self.restart().snapshot()["reconciliation"]["status"], "OK")

    def test_mark_exit_fee_and_eod_failures_preserve_committed_reservation(self):
        paper, result, candidate, eod = self.eod_entry(cost_model_json="{}")
        self.f._set_time("15:20")
        stages = (
            "BEFORE UPDATE ON paper_positions",
            "AFTER UPDATE ON paper_positions WHEN json_extract(NEW.payload_json,'$.status')='CLOSED'",
            "BEFORE INSERT ON paper_events WHEN NEW.kind='EXIT'",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                before = paper.snapshot()
                with self.store.paper_transaction() as conn:
                    conn.execute("CREATE TRIGGER phase5c_fault " + stage + " BEGIN SELECT RAISE(ABORT,'OFFLINE fault'); END")
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        paper.process_bar(result["position_id"], eod, "eod")
                    self.assertEqual(self.restart(paper).snapshot(), before)
                    self.assertGreater(before["accounting"]["reserved_capital_inr"], 0)
                finally:
                    with self.store.paper_transaction() as conn:
                        conn.execute("DROP TRIGGER phase5c_fault")
        original = paper._costs
        def fee_fault(entry, exit_price, quantity, side):
            if exit_price == eod["close"]:
                raise RuntimeError("OFFLINE fee calculation fault")
            return original(entry, exit_price, quantity, side)
        before = paper.snapshot()
        with patch.object(paper, "_costs", side_effect=fee_fault):
            with self.assertRaises(RuntimeError):
                paper.process_bar(result["position_id"], eod, "eod")
        self.assertEqual(paper.snapshot(), before)
        paper.process_bar(result["position_id"], eod, "eod")
        after = paper.snapshot()
        self.assertTrue(self.restart(paper).process_bar(result["position_id"], eod, "eod")["idempotent"])
        self.assertEqual(paper.snapshot(), after)

    def test_postcommit_reporting_exception_recovers_without_double_fill_or_fees(self):
        candidate = self.f._candidate(self.paper)
        summary = self.h._summary(candidate)
        bar = self.f._bar(candidate)
        with patch.object(self.store, "get_paper_portfolio_report", side_effect=RuntimeError("OFFLINE callback fault")):
            with self.assertRaises(RuntimeError):
                self.coordinator.consume_scan(summary, {candidate.symbol: [bar]})
        committed = self.restart().snapshot()
        self.f._set_time("10:20")
        report = ForwardPaperCoordinator(self.restart()).consume_scan(summary, {})["report"]
        self.assertEqual(report["accounting"], committed["accounting"])
        self.assertEqual(report["total_events"], 2)
        self.assertEqual(report["candidate_decisions"][0]["status"], "FILLED")
        for _ in range(2):
            self.assertEqual(self.paper.snapshot(), report)

    def test_mark_event_failure_duplicate_out_of_order_and_conflicting_id(self):
        result, candidate = self.enter()
        self.f._set_time("10:15")
        bar = self.f._bar(candidate, stamp="10:10")
        before = self.paper.snapshot()
        with self.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER phase5c_fault BEFORE INSERT ON paper_events WHEN NEW.kind='MARK' BEGIN SELECT RAISE(ABORT,'OFFLINE fault'); END")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.paper.process_bar(result["position_id"], bar, "mark")
            self.assertEqual(self.restart().snapshot(), before)
        finally:
            with self.store.paper_transaction() as conn:
                conn.execute("DROP TRIGGER phase5c_fault")
        self.paper.process_bar(result["position_id"], bar, "mark")
        after = self.paper.snapshot()
        self.assertTrue(self.restart().process_bar(result["position_id"], bar, "mark")["idempotent"])
        self.assert_code("EVENT_IDEMPOTENCY_CONFLICT", lambda: self.paper.process_bar(result["position_id"], dict(bar, close=101), "mark"))
        self.assert_code("MISSING_OR_OUT_OF_ORDER_POSITION_BAR", lambda: self.paper.process_bar(result["position_id"], bar, "new-id-old-bar"))
        self.assertEqual(self.paper.snapshot(), after)

    def test_concurrent_mark_exit_and_retry_never_resurrect_closed_position(self):
        result, candidate = self.enter()
        other = self.restart()
        self.f._set_time("10:15")
        mark = self.f._bar(candidate, stamp="10:10")
        exit_bar = dict(mark, high=125, low=99, close=121)
        barrier = threading.Barrier(2)
        def apply(service, bar, key):
            barrier.wait(timeout=5)
            try:
                return service.process_bar(result["position_id"], bar, key)["status"]
            except PaperPortfolioError as exc:
                return exc.reason_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(apply, self.paper, mark, "mark"), pool.submit(apply, other, exit_bar, "exit")]
            outcomes = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(s in ("OPEN", "CLOSED") for s in outcomes), 1)
        if self.paper.snapshot()["positions"][0]["status"] == "OPEN":
            self.f._set_time("10:20")
            self.paper.process_bar(result["position_id"], dict(exit_bar, timestamp="2026-10-16T10:15:00+05:30"), "exit-next")
        closed = self.paper.snapshot()
        self.assert_code("POSITION_ALREADY_CLOSED", lambda: other.process_bar(result["position_id"], mark, "resurrect"))
        self.assertEqual(self.restart().snapshot(), closed)
        self.assertEqual(closed["reconciliation"]["status"], "OK")

    def seed_decisions(self, count, account=None, body_size=0):
        account = account or self.paper.config.account_id
        with self.store.paper_transaction() as conn:
            start = conn.execute("SELECT COUNT(*) FROM paper_candidate_decisions WHERE account_id=?", (account,)).fetchone()[0]
            for i in range(start, start + count):
                key = f"{account}:decision:{i}"
                body = dict(candidate_id=key, account_id=account, status="REJECTED", execution_mode="SIMULATED", fixture="X" * body_size)
                conn.execute("INSERT INTO paper_candidate_decisions VALUES(?,?,?,?,?)", (key, account, key, "OFFLINE", _encode(body)))

    def pages(self, collection, limit=17):
        cursor, items = None, []
        while True:
            page = self.store.query_paper_ledger("account", collection, limit, cursor)
            self.assertLess(len(json.dumps(page).encode()), 1024 * 1024)
            self.assertLessEqual(len(page["items"]), limit)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items

    def test_cursor_pages_are_stable_account_scoped_and_pin_append_membership(self):
        self.seed_decisions(215)
        self.f._service(account_id="other")
        self.seed_decisions(5, "other")
        first = self.store.query_paper_ledger("account", "candidate_decisions", 17)
        self.seed_decisions(1, "other")
        with self.store.paper_transaction() as conn:
            conn.execute("INSERT INTO paper_candidate_decisions VALUES(?,?,?,?,?)", ("late", "account", "late", "OFFLINE", '{"status":"REJECTED"}'))
        cursor, seen = first["next_cursor"], first["items"][:]
        while cursor:
            page = self.store.query_paper_ledger("account", "candidate_decisions", 17, cursor)
            seen.extend(page["items"])
            cursor = page["next_cursor"]
        self.assertEqual(len(seen), 215)
        self.assertEqual(len({i["entity_id"] for i in seen}), 215)
        self.assertEqual([i["sequence_id"] for i in seen], sorted(i["sequence_id"] for i in seen))
        self.assertTrue(all(i["payload"]["account_id"] == "account" for i in seen))
        for account, collection in (("other", "candidate_decisions"), ("account", "events")):
            with self.assertRaises(ValueError):
                self.store.query_paper_ledger(account, collection, 17, first["next_cursor"])
        self.assertEqual(len(self.pages("candidate_decisions")), 216)

    def test_page_byte_budget_corruption_and_invalid_queries_fail_closed(self):
        self.seed_decisions(30, body_size=50000)
        self.assertEqual(len(self.pages("candidate_decisions", 200)), 30)
        self.assertTrue(self.store.query_paper_ledger("account", "candidate_decisions", 200)["next_cursor"])
        for limit, cursor in ((0, None), (201, None), (True, None), (5, "bad!"), (5, "x" * 2049)):
            with self.assertRaises(ValueError):
                self.store.query_paper_ledger("account", "candidate_decisions", limit, cursor)
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_candidate_decisions SET payload_json='secret-bearing corrupt body' WHERE candidate_id='account:decision:0'")
        self.assert_code("MALFORMED_OR_OVERSIZED_PAPER_RECORD", lambda: self.store.query_paper_ledger("account", "candidate_decisions"))
        self.assertEqual(self.paper.snapshot()["status"], "RECONCILIATION_REQUIRED")

    def test_corrupt_event_blocks_reconciliation_entry_and_safe_reporting(self):
        result, candidate = self.enter()
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_events SET payload_json='{' WHERE account_id='account'")
        self.assertEqual(self.restart().snapshot()["status"], "RECONCILIATION_REQUIRED")
        self.assert_code("RECONCILIATION_REQUIRED", lambda: self.paper.process_bar(result["position_id"], self.f._bar(candidate), "bad-ledger"))
        another = self.f._candidate(self.paper, symbol="TCS")
        self.assert_code("RECONCILIATION_REQUIRED", lambda: self.paper.enter(another, self.f._bar(another), "new-entry"))

    def test_oversized_or_expanding_persisted_record_never_returns_stuck_empty_cursor(self):
        self.seed_decisions(1)
        for body in ('{"fixture":"' + 'X' * 524288 + '"}', '{"fixture":"' + '\u00e9' * 180000 + '"}'):
            with self.subTest(bytes=len(body.encode())):
                with self.store.paper_transaction() as conn:
                    conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE account_id='account'", (body,))
                self.assert_code("MALFORMED_OR_OVERSIZED_PAPER_RECORD", lambda: self.store.query_paper_ledger("account", "candidate_decisions"))

    def test_coordinator_uses_open_positions_even_when_report_preview_omits_them(self):
        candidate, summary, bar, result = self.h._consume()
        self.f._set_time("10:15")
        exit_bar = self.f._bar(candidate, stamp="10:10", high=125, low=99, close=121)
        with patch.object(PaperPortfolio, "_preview_append", side_effect=lambda items, item, used: used):
            self.assertEqual(self.paper.snapshot()["positions"], [])
            self.coordinator.consume_scan(summary, {candidate.symbol: [exit_bar]})
        report = self.paper.snapshot()
        self.assertEqual(report["accounting"]["closed_positions"], 1)
        self.assertEqual(report["reconciliation"]["status"], "OK")

    def test_order_metadata_migrates_existing_rows_and_survives_restart(self):
        result, candidate = self.enter()
        self.seed_decisions(4)
        with self.store.paper_transaction() as conn:
            for _, table, _ in self.store._paper_collections():
                conn.execute("DROP TRIGGER " + table + "_page_order")
            conn.execute("DROP TABLE paper_ledger_order")
        restarted = self.restart()
        pages = {name: restarted.store.query_paper_ledger("account", name) for name, _, _ in self.store._paper_collections()}
        self.assertEqual([len(pages[name]["items"]) for name in ("events", "positions", "candidate_decisions")], [2, 1, 4])
        recovered = self.restart()
        for name, _, _ in self.store._paper_collections():
            self.assertEqual(recovered.store.query_paper_ledger("account", name), pages[name])
        with closing(sqlite3.connect(self.f.database)) as conn:
            conn.execute("VACUUM")
        for name, _, _ in self.store._paper_collections():
            self.assertEqual(recovered.store.query_paper_ledger("account", name), pages[name])
        self.assertEqual(recovered.snapshot()["reconciliation"]["status"], "OK")

    def test_actual_http_pages_head_validation_and_corruption_are_read_only(self):
        self.seed_decisions(3)
        engine = SimpleNamespace(store=self.store, _now_ist=lambda: self.f.now)
        handler = type("OfflinePhase5CHandler", (DashboardRequestHandler,), {"engine": engine, "scheduler": object()})
        server = create_http_server("127.0.0.1", 0, handler_cls=handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.addCleanup(stop)
        before = self.paper.snapshot()
        with patch("scanner_engine.IntradayBotEngine.run_single_scan", side_effect=AssertionError("No scans")):
            for prefix in ("/api", "/api/v1"):
                for method, suffix, expected in (("GET", "&collection=candidate_decisions&limit=2", 200),
                    ("HEAD", "&collection=candidate_decisions&limit=2", 200), ("GET", "&limit=0", 400),
                    ("GET", "&limit=-1", 400), ("GET", "&limit=2&limit=3", 400), ("GET", "&collection=unknown", 400)):
                    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                    try:
                        connection.request(method, prefix + "/paper-ledger?account_id=account" + suffix)
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(response.status, expected)
                        self.assertEqual(response.getheader("Cache-Control"), "no-store")
                        if method == "HEAD":
                            self.assertEqual(body, b"")
                        elif expected == 200:
                            self.assertEqual(len(json.loads(body)["items"]), 2)
                    finally:
                        connection.close()
        self.assertEqual(self.paper.snapshot(), before)
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_candidate_decisions SET payload_json='{' WHERE account_id='account'")
        instance = handler.__new__(handler)
        code, payload = instance._handle_paper_portfolio({"account_id": ["account"], "collection": ["candidate_decisions"]}, ledger=True)
        self.assertEqual(code, 503)
        self.assertEqual(payload["status"], "RECONCILIATION_REQUIRED")

    def seed_lifecycle(self, paper, event_count):
        """Bounded graph clones, never passed off as replayed strategy results."""
        self.f._set_time("10:10")
        result, candidate = self.enter(paper)
        self.f._set_time("10:15")
        paper.process_bar(result["position_id"], self.f._bar(candidate, stamp="10:10"), "mark")
        self.f._set_time("10:20")
        paper.process_bar(result["position_id"], self.f._bar(candidate, stamp="10:15", high=125, low=99, close=121), "exit")
        with self.store.paper_transaction() as conn:
            template = json.loads(conn.execute("SELECT payload_json FROM paper_positions WHERE position_id=?", (result["position_id"],)).fetchone()[0])
            events = [dict(row) for row in conn.execute("SELECT * FROM paper_events WHERE account_id=? ORDER BY rowid", (paper.config.account_id,))]
            for i in range(1, event_count // 4):
                # Explicit weekday-only fixture sessions; no exchange holiday claims.
                day = datetime(2025, 1, 6) + timedelta(days=(i // 10 // 5) * 7 + (i // 10 % 5))
                delta = day.replace(hour=10) - datetime(2026, 10, 16, 10) + timedelta(minutes=(i % 10) * 20)
                def shift(value):
                    if isinstance(value, dict):
                        return {key: shift(val) for key, val in value.items()}
                    if isinstance(value, list):
                        return [shift(val) for val in value]
                    if isinstance(value, str) and value.startswith("2026-10-16"):
                        return (datetime.fromisoformat(value) + delta).isoformat(sep="T" if "T" in value else " ")
                    return value
                position = shift(copy.deepcopy(template))
                position["candidate_hash"] = _hash(position["candidate"])
                position["entry_key"] = _hash([paper.config.run_id, signal_state_identity(position["candidate"])[0]])
                position["position_id"] = _hash([paper.config.account_id, position["entry_key"]])
                conn.execute("INSERT INTO paper_positions VALUES(?,?,?,?)", (position["position_id"], paper.config.account_id, position["entry_key"], _encode(position)))
                for j, event in enumerate(events):
                    body = shift(json.loads(event["payload_json"]))
                    body["result"]["position_id"] = position["position_id"]
                    if event["kind"] == "ENTRY":
                        body["entry"] = {key: position[key] for key in body["entry"]}
                    key = f"OFFLINE:{i}:{j}"
                    conn.execute("INSERT INTO paper_events VALUES(?,?,?,?,?,?)", (_hash([paper.config.account_id, key]), paper.config.account_id,
                        key, event["kind"], position["position_id"], _encode(body)))
        return template

    def test_increasing_ledgers_measure_recovery_reconciliation_summary_and_pages(self):
        measurements = []  # measurements only: no latency threshold is invented
        for size in (100, 1000, 10000):
            paper = self.f._service(account_id=f"bench{size}", fill_policy=FORWARD_FILL_POLICY, cost_model_json="{}")
            template = self.seed_lifecycle(paper, size)
            self.seed_decisions(size // 4, paper.config.account_id)
            started = time.perf_counter()
            paper = self.restart(paper)
            startup = time.perf_counter() - started
            started = time.perf_counter()
            self.assertEqual(paper.reconcile(), {"status": "OK", "errors": []})
            reconciliation = time.perf_counter() - started
            started = time.perf_counter()
            report = paper.snapshot()
            summary = time.perf_counter() - started
            self.assertEqual(report["total_events"], size)
            self.assertEqual(report["accounting"]["closed_positions"], size // 4)
            self.assertEqual(report["accounting"]["reserved_capital_inr"], 0)
            self.assertAlmostEqual(report["accounting"]["realized_net_pnl_inr"], template["net_pnl_inr"] * (size // 4), places=2)
            self.assertAlmostEqual(report["accounting"]["fees_paid_inr"], template["costs"]["charges_inr"] * (size // 4), places=2)
            response_bytes = len(json.dumps(report).encode())
            self.assertLess(response_bytes, 1024 * 1024)
            started = time.perf_counter()
            page = self.store.query_paper_ledger(paper.config.account_id, "events", 100)
            page_ms = (time.perf_counter() - started) * 1000
            first_page_bytes = len(json.dumps(page).encode())
            seen, cursor = [i["entity_id"] for i in page["items"]], page["next_cursor"]
            while cursor:
                page = self.store.query_paper_ledger(paper.config.account_id, "events", 100, cursor)
                self.assertLess(len(json.dumps(page).encode()), 1024 * 1024)
                seen.extend(i["entity_id"] for i in page["items"])
                cursor = page["next_cursor"]
            self.assertEqual(len(seen), size)
            self.assertEqual(len(set(seen)), size)
            position_ids, cursor = [], None
            while True:
                page = self.store.query_paper_ledger(paper.config.account_id, "positions", 100, cursor)
                position_ids.extend(i["entity_id"] for i in page["items"])
                cursor = page["next_cursor"]
                if not cursor:
                    break
            self.assertEqual(len(set(position_ids)), size // 4)
            started = time.perf_counter()
            page = self.store.query_paper_ledger(paper.config.account_id, "candidate_decisions", 100)
            decision_page_ms = (time.perf_counter() - started) * 1000
            decision_ids, cursor = [i["entity_id"] for i in page["items"]], page["next_cursor"]
            while cursor:
                page = self.store.query_paper_ledger(paper.config.account_id, "candidate_decisions", 100, cursor)
                decision_ids.extend(i["entity_id"] for i in page["items"])
                cursor = page["next_cursor"]
            self.assertEqual(len(set(decision_ids)), size // 4)
            with self.store.paper_transaction(write=False) as conn:
                plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN SELECT o.sequence_id,o.entity_id,t.payload_json FROM paper_ledger_order o "
                    "LEFT JOIN paper_events t ON t.event_id=o.entity_id AND t.account_id=o.account_id "
                    "WHERE o.account_id=? AND o.collection=? AND o.sequence_id>? AND o.sequence_id<=? ORDER BY o.sequence_id LIMIT ?",
                    (paper.config.account_id, "events", 0, 9999999, 100))]
                event_plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN SELECT payload_json FROM paper_events "
                    "WHERE account_id=? AND position_id=? ORDER BY rowid", (paper.config.account_id, template["position_id"]))]
            self.assertTrue(any("idx_paper_ledger_page" in p for p in plan))
            self.assertTrue(any("idx_paper_events_position" in p for p in event_plan))
            measurements.append(dict(events=size, positions=size // 4, startup_ms=round(startup * 1000, 3),
                reconciliation_ms=round(reconciliation * 1000, 3), summary_ms=round(summary * 1000, 3),
                first_page_ms=round(page_ms, 3), first_page_bytes=first_page_bytes,
                candidate_decisions=size // 4, decision_page_ms=round(decision_page_ms, 3),
                summary_bytes=response_bytes, page_plan=plan, reconciliation_plan=event_plan))
        print("PHASE5C_BENCHMARK " + json.dumps(measurements, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
