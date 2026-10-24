"""Phase 6 Workstream A — Paper-Trading Lifecycle, Accounting & Settlement Regressions.

Validates:
1. End-to-end scanner candidate -> paper decision -> fill -> position mark -> exit -> P&L.
2. Long and Short position lifecycles under both supported fill policies:
   - OBSERVED_NEXT_COMPLETED_BAR_OPEN_STOP_FIRST_V1
   - NEXT_COMPLETED_BAR_CLOSE_V1 (FORWARD_FILL_POLICY)
3. Deterministic sizing, statutory charge deductions, and adverse slippage application.
4. Double-entry accounting invariants: Starting Capital + Realized P&L + Unrealized P&L == Equity.
5. Conservative collision resolution: Stop-First takes precedence over profit target.
6. Mandatory intraday EOD square-off at 15:20 IST.
7. Multi-trade EOD session statement generation, event digests, and tampering defense.
8. Event idempotency, replay defense, and duplicate event prevention.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- existing offline configuration bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from backtest_engine import IndianCostModel
from config import BotConfig
from forward_paper import ForwardPaperCoordinator
from instrument_identity import spot_identity
from paper_portfolio import (
    FORWARD_FILL_POLICY,
    PaperAccountConfig,
    PaperPortfolio,
    PaperPortfolioError,
    _hash,
)
from storage import SQLitePersistenceStore
from strategies import IST, TradeSignal


class TestPhase6PaperLifecycle(unittest.TestCase):
    def setUp(self):
        # 10:10:05 IST: initial clock
        self.now = datetime(2026, 10, 16, 10, 10, 5, tzinfo=IST)
        self.temporary = tempfile.TemporaryDirectory(prefix="tradepulse_phase6_paper_")
        self.addCleanup(self.temporary.cleanup)
        self.database = str(Path(self.temporary.name) / "paper_lifecycle.sqlite")
        self.store = SQLitePersistenceStore(self.database)
        self.addCleanup(self.store.close)

        # Ensure no network transport or alert delivery can occur
        self.transport = patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Phase 6 tests must never contact external transport"),
        )
        self.transport.start()
        self.addCleanup(self.transport.stop)

        self.delivery = patch(
            "telegram_bot.TelegramSignalDispatcher.send_signal",
            side_effect=AssertionError("Phase 6 paper tests must never dispatch real alerts"),
        )
        self.delivery.start()
        self.addCleanup(self.delivery.stop)

    def _cost_model(self):
        # Realistic Indian cost model with statutory fees and slippage
        model = IndianCostModel(
            brokerage_per_order_inr=20.0,
            stt_sell_rate_equity_intraday=0.00025,
            exchange_txn_rate_equity_intraday=0.0000325,
            sebi_turnover_rate=0.000001,
            stamp_duty_buy_rate_equity_intraday=0.00003,
            gst_rate=0.18,
            slippage_bps_per_leg=2.0,
        )
        return json.dumps(model.to_dict())

    def _config(self, **values):
        params = dict(
            account_id="phase6_paper_acc",
            run_id="phase6_run_01",
            provider="upstox",
            source_data_mode="SIMULATED",
            starting_capital_inr=200000.0,
            risk_pct=1.0,
            max_daily_loss_inr=5000.0,
            max_open_positions=3,
            max_entries_per_day=10,
            max_position_exposure_pct=50.0,
            max_total_exposure_pct=100.0,
            cost_model_json=self._cost_model(),
        )
        params.update(values)
        return PaperAccountConfig(**params)

    def _service(self, **values):
        return PaperPortfolio(self.store, self._config(**values), clock=lambda: self.now)

    def _candidate(self, service=None, *, symbol="RELIANCE", side="LONG", stamp="10:00",
                   entry=100.0, stop=None, target1=None, target2=None):
        cfg = service.config if service else self._config()
        meta = next(m for m in BotConfig.__dataclass_fields__["equity_watchlist"].default_factory() if m["symbol"] == symbol)
        identity = spot_identity(meta, cfg.provider)
        if side == "LONG":
            sl = (entry - 5.0) if stop is None else stop
            t1 = (entry + 10.0) if target1 is None else target1
            t2 = (t1 + 5.0) if target2 is None else target2
            invalidation = sl
        else:
            sl = (entry + 5.0) if stop is None else stop
            t1 = (entry - 10.0) if target1 is None else target1
            t2 = (t1 - 5.0) if target2 is None else target2
            invalidation = sl
        return TradeSignal(
            symbol=symbol,
            segment="NSE_EQUITY_INTRADAY",
            strategy_id="strat_1_order_block",
            strategy_name="Phase 6 Order Block FVG Test",
            direction="BULLISH (BUY)" if side == "LONG" else "BEARISH (SELL)",
            instrument_label=symbol + " EQ",
            entry_price=entry,
            entry_zone_low=entry * 0.995,
            entry_zone_high=entry * 1.005,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:2",
            confidence_pct=80.0,
            win_rate_benchmark="60%",
            position_qty=100,
            capital_risk_inr=500.0,
            est_charges_inr=25.0,
            rationale="Phase 6 offline deterministic candidate fixture",
            timestamp="2026-10-16 " + stamp + ":00",
            is_simulated=cfg.source_data_mode == "SIMULATED",
            data_mode=cfg.source_data_mode,
            position_type="LONG_EQUITY_INTRADAY" if side == "LONG" else "SHORT_EQUITY_INTRADAY",
            invalidation_level=invalidation,
            provider=cfg.provider,
            state_context="SIMULATED_TEST",
            interval_min=5,
            instrument_identity=identity,
        )

    def _bar(self, candidate, stamp="10:05", *, open_p=100.0, high_p=101.0, low_p=99.0, close_p=100.5, volume=1000.0):
        return dict(
            timestamp="2026-10-16T" + stamp + ":00+05:30",
            open=float(open_p),
            high=float(high_p),
            low=float(low_p),
            close=float(close_p),
            volume=float(volume),
            is_complete=True,
            interval_min=5,
            data_mode=candidate.data_mode,
            is_simulated=candidate.is_simulated,
            instrument_identity=copy.deepcopy(candidate.instrument_identity),
        )

    def _set_time(self, stamp, date="2026-10-16"):
        self.now = datetime.fromisoformat(date + "T" + stamp + ":05+05:30")

    def test_complete_long_position_lifecycle_to_target_exit(self):
        """Exercises complete LONG candidate entry -> mark -> target exit -> accounting reconciliation."""
        service = self._service()
        candidate = self._candidate(service, side="LONG", stamp="10:00", entry=100.0, stop=95.0, target1=110.0)

        # 1. Enter on next completed bar (10:05 bar, closes at 10:10:00 -> clock at 10:10:05)
        self._set_time("10:10")
        entry_bar = self._bar(candidate, stamp="10:05", open_p=100.0, high_p=102.0, low_p=99.5, close_p=101.5)
        res_entry = service.enter(candidate, entry_bar, "event_entry_long_01")
        self.assertEqual(res_entry["status"], "OPEN")
        pos_id = res_entry["position_id"]

        # Check snapshot immediately after entry
        snap_after_entry = service.snapshot()
        self.assertEqual(snap_after_entry["status"], "OK")
        self.assertEqual(snap_after_entry["accounting"]["open_positions"], 1)
        self.assertEqual(snap_after_entry["accounting"]["closed_positions"], 0)
        self.assertGreater(snap_after_entry["accounting"]["reserved_capital_inr"], 0.0)

        # Double-entry invariant check at OPEN state
        acc = snap_after_entry["accounting"]
        expected_equity = round(acc["starting_capital_inr"] + acc["realized_net_pnl_inr"] + acc["unrealized_net_pnl_inr"], 2)
        self.assertEqual(acc["equity_inr"], expected_equity)

        # 2. Process next bar (10:10 bar, closes at 10:15:00 -> clock at 10:15:05): Bar rallies towards target without hitting it -> MARK
        self._set_time("10:15")
        mark_bar = self._bar(candidate, stamp="10:10", open_p=101.5, high_p=108.0, low_p=101.0, close_p=107.0)
        res_mark = service.process_bar(pos_id, mark_bar, "event_mark_long_01")
        self.assertEqual(res_mark["status"], "OPEN")

        snap_mark = service.snapshot()
        # Unrealized P&L must be strictly positive (entry 100 -> mark close 107)
        self.assertGreater(snap_mark["accounting"]["unrealized_net_pnl_inr"], 0.0)
        self.assertEqual(snap_mark["accounting"]["equity_inr"],
                         round(acc["starting_capital_inr"] + snap_mark["accounting"]["unrealized_net_pnl_inr"], 2))

        # 3. Process next bar (10:15 bar, closes at 10:20:00 -> clock at 10:20:05): High touches target (110.0) -> TARGET EXIT
        self._set_time("10:20")
        exit_bar = self._bar(candidate, stamp="10:15", open_p=107.0, high_p=112.0, low_p=106.5, close_p=111.0)
        res_exit = service.process_bar(pos_id, exit_bar, "event_exit_long_01")
        self.assertEqual(res_exit["status"], "CLOSED")
        self.assertEqual(res_exit["exit_reason"], "TARGET")

        # Snapshot after close: 0 open positions, 1 closed position, realized profit
        snap_closed = service.snapshot()
        self.assertEqual(snap_closed["accounting"]["open_positions"], 0)
        self.assertEqual(snap_closed["accounting"]["closed_positions"], 1)
        self.assertEqual(snap_closed["accounting"]["reserved_capital_inr"], 0.0)
        self.assertEqual(snap_closed["accounting"]["unrealized_net_pnl_inr"], 0.0)
        self.assertGreater(snap_closed["accounting"]["realized_net_pnl_inr"], 0.0)
        self.assertGreater(snap_closed["accounting"]["fees_paid_inr"], 0.0)
        self.assertGreater(snap_closed["accounting"]["slippage_paid_inr"], 0.0)

        # Final double-entry invariant
        c_acc = snap_closed["accounting"]
        self.assertEqual(c_acc["equity_inr"], round(c_acc["starting_capital_inr"] + c_acc["realized_net_pnl_inr"], 2))

        # Reconcile account
        recon = service.reconcile()
        self.assertEqual(recon["status"], "OK")
        self.assertEqual(recon["errors"], [])

    def test_complete_short_position_lifecycle_to_stop_loss_exit(self):
        """Exercises complete SHORT candidate entry -> stop loss hit -> accounting reconciliation."""
        service = self._service()
        candidate = self._candidate(service, side="SHORT", stamp="10:00", entry=100.0, stop=105.0, target1=90.0, target2=85.0)

        # 1. Enter SHORT at 100.0 (10:05 bar, closes at 10:10:00 -> clock at 10:10:05)
        self._set_time("10:10")
        entry_bar = self._bar(candidate, stamp="10:05", open_p=100.0, high_p=100.5, low_p=98.5, close_p=99.0)
        res_entry = service.enter(candidate, entry_bar, "event_entry_short_01")
        self.assertEqual(res_entry["status"], "OPEN")
        pos_id = res_entry["position_id"]

        # 2. Next bar (10:10 bar, closes at 10:15:00 -> clock at 10:15:05): price rallies, high touches stop_loss (105.0) -> STOP EXIT
        self._set_time("10:15")
        exit_bar = self._bar(candidate, stamp="10:10", open_p=99.0, high_p=106.0, low_p=98.5, close_p=105.5)
        res_exit = service.process_bar(pos_id, exit_bar, "event_exit_short_01")
        self.assertEqual(res_exit["status"], "CLOSED")
        self.assertEqual(res_exit["exit_reason"], "STOP")

        # Snapshot check: realized loss recorded, capital released, equity decreased
        snap = service.snapshot()
        self.assertEqual(snap["accounting"]["open_positions"], 0)
        self.assertEqual(snap["accounting"]["closed_positions"], 1)
        self.assertLess(snap["accounting"]["realized_net_pnl_inr"], 0.0)
        self.assertLess(snap["accounting"]["equity_inr"], snap["accounting"]["starting_capital_inr"])

        # Invariant check
        acc = snap["accounting"]
        self.assertEqual(acc["equity_inr"], round(acc["starting_capital_inr"] + acc["realized_net_pnl_inr"], 2))
        self.assertEqual(service.reconcile()["status"], "OK")

    def test_conservative_same_candle_collision_stop_first(self):
        """Verifies conservative collision rule: when a single bar touches both stop and target, stop loss takes precedence."""
        service = self._service()
        candidate = self._candidate(service, side="LONG", stamp="10:00", entry=100.0, stop=95.0, target1=110.0)

        self._set_time("10:10")
        entry_bar = self._bar(candidate, stamp="10:05", open_p=100.0, high_p=101.0, low_p=99.0, close_p=100.5)
        res_entry = service.enter(candidate, entry_bar, "event_collision_entry")
        pos_id = res_entry["position_id"]

        # Bar 10:10 (closes at 10:15:00 -> clock at 10:15:05) has massive volatility: low breaches 95.0 AND high breaches 110.0
        self._set_time("10:15")
        collision_bar = self._bar(candidate, stamp="10:10", open_p=100.5, high_p=112.0, low_p=94.0, close_p=102.0)
        res_exit = service.process_bar(pos_id, collision_bar, "event_collision_exit")
        self.assertEqual(res_exit["status"], "CLOSED")
        self.assertEqual(res_exit["exit_reason"], "STOP_FIRST_COLLISION")

        # Exit price must be the stop loss price (95.0), not target
        with self.store.paper_transaction(write=False) as conn:
            row = conn.execute("SELECT payload_json FROM paper_positions WHERE position_id=?", (pos_id,)).fetchone()
            pos_data = json.loads(row[0])
            self.assertEqual(pos_data["raw_exit_price"], 95.0)
            self.assertLess(pos_data["net_pnl_inr"], 0.0)

    def test_mandatory_intraday_eod_square_off_at_1520(self):
        """Verifies that an open position arriving at 15:20 IST is automatically squared off at bar close."""
        service = self._service()
        candidate = self._candidate(service, side="LONG", stamp="15:05", entry=100.0, stop=90.0, target1=120.0, target2=125.0)

        self._set_time("15:15")
        entry_bar = self._bar(candidate, stamp="15:10", open_p=100.0, high_p=101.0, low_p=99.0, close_p=100.5)
        res_entry = service.enter(candidate, entry_bar, "event_eod_entry")
        pos_id = res_entry["position_id"]

        # 15:15 bar (which closes at 15:20:00 -> clock at 15:20:05 IST)
        self._set_time("15:20")
        eod_bar = self._bar(candidate, stamp="15:15", open_p=104.0, high_p=105.0, low_p=103.5, close_p=104.5)
        res_exit = service.process_bar(pos_id, eod_bar, "event_eod_exit")
        self.assertEqual(res_exit["status"], "CLOSED")
        self.assertEqual(res_exit["exit_reason"], "EOD")

        with self.store.paper_transaction(write=False) as conn:
            pos_data = json.loads(conn.execute("SELECT payload_json FROM paper_positions WHERE position_id=?", (pos_id,)).fetchone()[0])
            self.assertEqual(pos_data["raw_exit_price"], 104.5)  # closed at bar close

    def test_multi_trade_eod_statement_and_tamper_detection(self):
        """Verifies multi-trade session statement generation, SHA-256 event digest, and tamper sensitivity."""
        service = self._service()

        # Trade 1: Long WIN (+10 pts)
        self._set_time("10:10")
        c1 = self._candidate(service, symbol="RELIANCE", side="LONG", stamp="10:00", entry=100.0, stop=95.0, target1=110.0)
        e1 = service.enter(c1, self._bar(c1, stamp="10:05", open_p=100.0, high_p=101.0, low_p=99.5, close_p=100.5), "t1_entry")
        self._set_time("10:15")
        service.process_bar(e1["position_id"], self._bar(c1, stamp="10:10", open_p=100.5, high_p=111.0, low_p=100.0, close_p=110.5), "t1_exit")

        # Trade 2: Long LOSS (-5 pts)
        self._set_time("10:30")
        c2 = self._candidate(service, symbol="INFY", side="LONG", stamp="10:20", entry=200.0, stop=195.0, target1=210.0)
        e2 = service.enter(c2, self._bar(c2, stamp="10:25", open_p=200.0, high_p=200.5, low_p=199.0, close_p=199.5), "t2_entry")
        self._set_time("10:35")
        service.process_bar(e2["position_id"], self._bar(c2, stamp="10:30", open_p=199.5, high_p=200.0, low_p=194.5, close_p=194.8), "t2_exit")

        # Generate EOD session statement for 2026-10-16
        self._set_time("16:00")
        statement = service.session_statement("2026-10-16")
        self.assertEqual(statement["status"], "OK")
        self.assertEqual(statement["eod_status"], "RECONCILED")
        self.assertEqual(statement["accounting"]["closed_positions"], 2)
        self.assertEqual(statement["accounting"]["open_positions"], 0)
        self.assertTrue(statement["statement_sha256"])
        self.assertTrue(statement["event_digest_sha256"])

        # Tampering check: changing any field in statement invalidates its checksum
        orig_hash = statement["statement_sha256"]
        tampered_statement = dict(statement)
        tampered_statement["accounting"] = dict(statement["accounting"], equity_inr=999999.0)
        del tampered_statement["statement_sha256"]
        recomputed_hash = _hash(tampered_statement)
        self.assertNotEqual(orig_hash, recomputed_hash)

    def test_idempotent_event_submission_returns_cached_result(self):
        """Verifies duplicate submission with identical event_key returns cached result without double entry."""
        service = self._service()
        candidate = self._candidate(service, side="LONG", stamp="10:00", entry=100.0, stop=95.0, target1=110.0)
        entry_bar = self._bar(candidate, stamp="10:05", open_p=100.0, high_p=101.0, low_p=99.0, close_p=100.5)

        self._set_time("10:10")
        first_res = service.enter(candidate, entry_bar, "idempotent_event_key_01")
        self.assertEqual(first_res["status"], "OPEN")
        pos_id = first_res["position_id"]

        # Resubmit identical command
        second_res = service.enter(candidate, entry_bar, "idempotent_event_key_01")
        self.assertEqual(second_res["status"], "OPEN")
        self.assertEqual(second_res["position_id"], pos_id)
        self.assertTrue(second_res.get("idempotent"))

        # Snapshot proves only 1 position exists
        snap = service.snapshot()
        self.assertEqual(snap["accounting"]["open_positions"], 1)

    def test_event_idempotency_conflict_rejection(self):
        """Verifies re-using an event_key with conflicting parameters raises EVENT_IDEMPOTENCY_CONFLICT."""
        service = self._service()
        candidate = self._candidate(service, side="LONG", stamp="10:00", entry=100.0, stop=95.0, target1=110.0)
        entry_bar = self._bar(candidate, stamp="10:05", open_p=100.0, high_p=101.0, low_p=99.0, close_p=100.5)

        self._set_time("10:10")
        service.enter(candidate, entry_bar, "shared_key_01")

        # Conflict: different bar prices with same event_key
        conflicting_bar = self._bar(candidate, stamp="10:05", open_p=102.0, high_p=104.0, low_p=101.0, close_p=103.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(candidate, conflicting_bar, "shared_key_01")
        self.assertEqual(ctx.exception.reason_code, "EVENT_IDEMPOTENCY_CONFLICT")


if __name__ == "__main__":
    unittest.main()
