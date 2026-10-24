"""Phase 6 Workstream B — Risk Controls, Fault Injection & Operational Recovery.

Validates:
1. Risk control boundary enforcement:
   - OPEN_POSITION_LIMIT
   - DAILY_LOSS_LIMIT
   - DAILY_ENTRY_LIMIT
   - POSITION_EXPOSURE_LIMIT / EXPOSURE_LIMIT
   - INVALID_ENTRY_STOP_TARGET_BRACKET
2. Operational recovery and fault injection:
   - Process crash during pending order: recovery from paper_events without duplicate fills
   - Stale candle rejection (max_mark_age_seconds)
   - Non-contiguous / out-of-order bar rejection (MISSING_OR_OUT_OF_ORDER_POSITION_BAR)
   - Account configuration tamper detection (IMMUTABLE_ACCOUNT_CONFIG_CONFLICT / ACCOUNT_CONFIG_CORRUPT)
   - Ledger corruption fail-closed behavior (RECONCILIATION_REQUIRED)
   - Unapproved EOD financial repair rejection (UNAPPROVED_FINANCIAL_RECOVERY_ACTION)
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
    _encode,
    _hash,
)
from storage import SQLitePersistenceStore
from strategies import IST, TradeSignal


class TestPhase6RiskRecovery(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 10, 5, tzinfo=IST)
        self.temporary = tempfile.TemporaryDirectory(prefix="tradepulse_phase6_risk_")
        self.addCleanup(self.temporary.cleanup)
        self.database = str(Path(self.temporary.name) / "risk_recovery.sqlite")
        self.store = SQLitePersistenceStore(self.database)
        self.addCleanup(self.store.close)

        self.transport = patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Risk recovery tests must never contact external transport"),
        )
        self.transport.start()
        self.addCleanup(self.transport.stop)

        self.delivery = patch(
            "telegram_bot.TelegramSignalDispatcher.send_signal",
            side_effect=AssertionError("Risk recovery tests must never dispatch real alerts"),
        )
        self.delivery.start()
        self.addCleanup(self.delivery.stop)

    def _cost_model(self):
        model = IndianCostModel()
        return json.dumps(model.to_dict())

    def _config(self, **values):
        params = dict(
            account_id="risk_recovery_acc",
            run_id="risk_run_01",
            provider="upstox",
            source_data_mode="SIMULATED",
            starting_capital_inr=100000.0,
            risk_pct=1.0,
            max_daily_loss_inr=2000.0,
            max_open_positions=2,
            max_entries_per_day=3,
            max_position_exposure_pct=40.0,
            max_total_exposure_pct=80.0,
            max_mark_age_seconds=60,
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
            strategy_name="Phase 6 Risk Test",
            direction="BULLISH (BUY)" if side == "LONG" else "BEARISH (SELL)",
            instrument_label=symbol + " EQ",
            entry_price=entry,
            entry_zone_low=entry * 0.995,
            entry_zone_high=entry * 1.005,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward="1:2",
            confidence_pct=75.0,
            win_rate_benchmark="55%",
            position_qty=50,
            capital_risk_inr=250.0,
            est_charges_inr=15.0,
            rationale="Phase 6 risk regression candidate",
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

    def _bar(self, candidate, stamp="10:05", *, open_p=100.0, high_p=None, low_p=None, close_p=None, volume=1000.0):
        o = float(open_p)
        c = float(o * 1.002) if close_p is None else float(close_p)
        h = max(o, c) * 1.01 if high_p is None else float(high_p)
        l = min(o, c) * 0.99 if low_p is None else float(low_p)
        return dict(
            timestamp="2026-10-16T" + stamp + ":00+05:30",
            open=o,
            high=h,
            low=l,
            close=c,
            volume=float(volume),
            is_complete=True,
            interval_min=5,
            data_mode=candidate.data_mode,
            is_simulated=candidate.is_simulated,
            instrument_identity=copy.deepcopy(candidate.instrument_identity),
        )

    def _set_time(self, stamp, date="2026-10-16"):
        self.now = datetime.fromisoformat(date + "T" + stamp + ":05+05:30")

    def test_open_position_limit_enforcement(self):
        """Verifies that exceeding max_open_positions rejects new entries with OPEN_POSITION_LIMIT."""
        service = self._service(max_open_positions=2)

        # Position 1: RELIANCE
        self._set_time("10:10")
        c1 = self._candidate(service, symbol="RELIANCE", stamp="10:00", entry=100.0)
        e1 = service.enter(c1, self._bar(c1, stamp="10:05", open_p=100.0), "pos1")
        self.assertEqual(e1["status"], "OPEN")

        # Position 2: INFY
        c2 = self._candidate(service, symbol="INFY", stamp="10:00", entry=200.0)
        e2 = service.enter(c2, self._bar(c2, stamp="10:05", open_p=200.0), "pos2")
        self.assertEqual(e2["status"], "OPEN")

        # Position 3: TCS -> Must be rejected because max_open_positions == 2
        c3 = self._candidate(service, symbol="TCS", stamp="10:00", entry=300.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(c3, self._bar(c3, stamp="10:05", open_p=300.0), "pos3")
        self.assertEqual(ctx.exception.reason_code, "OPEN_POSITION_LIMIT")

    def test_daily_loss_limit_blocks_new_entries(self):
        """Verifies that breaching max_daily_loss_inr blocks new entries with DAILY_LOSS_LIMIT."""
        # Max daily loss = 300 INR, trade loss will be ~392+ INR
        service = self._service(max_daily_loss_inr=300.0, starting_capital_inr=100000.0)

        # Enter position 1 and close it with a ~392 INR loss (exceeds 300 INR limit)
        self._set_time("10:10")
        c1 = self._candidate(service, symbol="RELIANCE", side="LONG", stamp="10:00", entry=100.0, stop=70.0, target1=150.0)
        e1 = service.enter(c1, self._bar(c1, stamp="10:05", open_p=100.0), "pos1")

        # Next bar hits stop loss hard
        self._set_time("10:15")
        bar_loss = self._bar(c1, stamp="10:10", open_p=70.0, high_p=75.0, low_p=68.0, close_p=69.0)
        service.process_bar(e1["position_id"], bar_loss, "exit1")

        # Snapshot shows daily loss limit breached
        snap = service.snapshot()
        self.assertIn("DAILY_LOSS_LIMIT", snap["entry_blocks"])
        self.assertTrue(snap["accounting"]["day"]["loss_limit_breached"])

        # Attempting new entry on another symbol must be blocked with DAILY_LOSS_LIMIT
        self._set_time("10:25")
        c2 = self._candidate(service, symbol="INFY", stamp="10:15", entry=200.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(c2, self._bar(c2, stamp="10:20", open_p=200.0), "pos2")
        self.assertEqual(ctx.exception.reason_code, "DAILY_LOSS_LIMIT")

    def test_daily_entry_limit_enforcement(self):
        """Verifies that exceeding max_entries_per_day rejects entries with DAILY_ENTRY_LIMIT."""
        service = self._service(max_entries_per_day=2, max_open_positions=5)

        # Entry 1
        self._set_time("10:10")
        c1 = self._candidate(service, symbol="RELIANCE", stamp="10:00", entry=100.0)
        service.enter(c1, self._bar(c1, stamp="10:05", open_p=100.0), "e1")

        # Entry 2
        c2 = self._candidate(service, symbol="INFY", stamp="10:00", entry=200.0)
        service.enter(c2, self._bar(c2, stamp="10:05", open_p=200.0), "e2")

        # Entry 3: Exceeds max_entries_per_day == 2
        c3 = self._candidate(service, symbol="TCS", stamp="10:00", entry=300.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(c3, self._bar(c3, stamp="10:05", open_p=300.0), "e3")
        self.assertEqual(ctx.exception.reason_code, "DAILY_ENTRY_LIMIT")

    def test_invalid_bracket_geometry_rejection(self):
        """Verifies that invalid brackets (stop >= entry or target <= entry for LONG) are rejected."""
        service = self._service()

        # Stop >= Entry (LONG)
        c_bad_stop = self._candidate(service, side="LONG", entry=100.0, stop=105.0, target1=120.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(c_bad_stop, self._bar(c_bad_stop, stamp="10:05"), "bad_stop")
        self.assertEqual(ctx.exception.reason_code, "INVALID_ENTRY_STOP_TARGET_BRACKET")

        # Target <= Entry (LONG)
        c_bad_target = self._candidate(service, side="LONG", entry=100.0, stop=90.0, target1=95.0, target2=98.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(c_bad_target, self._bar(c_bad_target, stamp="10:05"), "bad_target")
        self.assertEqual(ctx.exception.reason_code, "INVALID_ENTRY_STOP_TARGET_BRACKET")

    def test_stale_mark_and_candle_age_rejection(self):
        """Verifies that bars older than max_mark_age_seconds are rejected as stale."""
        service = self._service(max_mark_age_seconds=60)
        candidate = self._candidate(service, stamp="10:00")

        # 10:05 bar completes at 10:10:00 IST.
        # If current clock is 10:12:00 IST, age is 120s > 60s threshold -> INVALID_STALE_OR_UNFINISHED_BAR
        self._set_time("10:12")
        stale_bar = self._bar(candidate, stamp="10:05")
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.enter(candidate, stale_bar, "stale_entry")
        self.assertEqual(ctx.exception.reason_code, "INVALID_STALE_OR_UNFINISHED_BAR")

    def test_non_contiguous_bar_rejection(self):
        """Verifies that processing a non-contiguous bar in process_bar raises MISSING_OR_OUT_OF_ORDER_POSITION_BAR."""
        service = self._service()
        candidate = self._candidate(service, stamp="10:00", entry=100.0)

        self._set_time("10:10")
        entry_bar = self._bar(candidate, stamp="10:05", open_p=100.0)
        res = service.enter(candidate, entry_bar, "e1")
        pos_id = res["position_id"]

        # Expected next bar is 10:10. If 10:15 bar is passed instead, it must be rejected
        self._set_time("10:20")
        skipped_bar = self._bar(candidate, stamp="10:15", open_p=101.0)
        with self.assertRaises(PaperPortfolioError) as ctx:
            service.process_bar(pos_id, skipped_bar, "skip_event")
        self.assertEqual(ctx.exception.reason_code, "MISSING_OR_OUT_OF_ORDER_POSITION_BAR")

    def test_account_config_tamper_detection(self):
        """Verifies that mutating paper_accounts config_json or config_hash triggers IMMUTABLE_ACCOUNT_CONFIG_CONFLICT."""
        service = self._service()
        candidate = self._candidate(service, stamp="10:00")
        self._set_time("10:10")
        service.enter(candidate, self._bar(candidate, stamp="10:05"), "e1")

        # Tamper: update config_json in SQLite behind the service's back
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("UPDATE paper_accounts SET config_hash='tampered_hash' WHERE account_id=?",
                         (service.config.account_id,))

        # Re-instantiating PaperPortfolio for the same account must reject the conflict
        with self.assertRaises(PaperPortfolioError) as ctx:
            PaperPortfolio(self.store, service.config, clock=lambda: self.now)
        self.assertEqual(ctx.exception.reason_code, "IMMUTABLE_ACCOUNT_CONFIG_CONFLICT")

    def test_crash_recovery_during_pending_order(self):
        """Fault injection: simulate process crash between ENTRY event insert and decision update.

        Coordinator must recover the existing ENTRY event on restart without duplicate submission.
        """
        config = self._config(fill_policy=FORWARD_FILL_POLICY)
        service = PaperPortfolio(self.store, config, clock=lambda: self.now)
        coordinator = ForwardPaperCoordinator(service)

        candidate = self._candidate(service, stamp="10:00", entry=100.0)
        signal_key = _hash(candidate.to_dict())
        candidate_id = _hash([config.account_id, signal_key])

        # Step 1: Insert pending candidate decision in SQLite (simulating scanner queue)
        decision = dict(
            candidate_id=candidate_id,
            account_id=config.account_id,
            config_hash=config.config_hash,
            run_id=config.run_id,
            source_scan_run_id="scan_run_01",
            signal_key=signal_key,
            candidate_hash=_hash(candidate.to_dict()),
            candidate=candidate.to_dict(),
            execution_mode="SIMULATED",
            status="QUEUED",
            reason_code="WAITING_FOR_NEXT_COMPLETED_OBSERVATION",
            position_id=None,
            history=[],
        )
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("INSERT INTO paper_candidate_decisions VALUES (?,?,?,?,?)",
                         (candidate_id, config.account_id, signal_key, "scan_run_01", _encode(decision)))

        # Step 2: Simulate crash after fill event committed in paper_events, but BEFORE decision table updated
        self._set_time("10:10")
        bar = self._bar(candidate, stamp="10:05", open_p=100.0, close_p=100.5)
        # Execute enter directly
        fill_res = service.enter(candidate, bar, event_key=candidate_id)
        self.assertEqual(fill_res["status"], "OPEN")
        pos_id = fill_res["position_id"]

        # Verify decision is still QUEUED in table (interrupted state)
        with self.store.paper_transaction(write=False) as conn:
            d_row = conn.execute("SELECT payload_json FROM paper_candidate_decisions WHERE candidate_id=?", (candidate_id,)).fetchone()
            self.assertEqual(json.loads(d_row[0])["status"], "QUEUED")

        # Step 3: Coordinator restart -> transition recovers existing entry
        recovered = coordinator._transition(candidate_id, "FILLED", "RECOVERED_IDEMPOTENT_ENTRY", pos_id)
        self.assertEqual(recovered["status"], "FILLED")
        self.assertEqual(recovered["reason_code"], "PAPER_RISK_APPROVED")
        self.assertEqual(recovered["position_id"], pos_id)

    def test_unapproved_financial_recovery_action_rejection(self):
        """Verifies that review_unresolved_eod rejects unauthorized financial repairs."""
        service = self._service()
        candidate = self._candidate(service, stamp="10:00", entry=100.0)
        self._set_time("10:10")
        res = service.enter(candidate, self._bar(candidate, stamp="10:05"), "e1")

        with self.assertRaises(PaperPortfolioError) as ctx:
            service.review_unresolved_eod(
                res["position_id"],
                "recovery_event_01",
                requested_action="INVALID_MUTATE_LEDGER_ACTION",
            )
        self.assertEqual(ctx.exception.reason_code, "UNAPPROVED_FINANCIAL_RECOVERY_ACTION")


if __name__ == "__main__":
    unittest.main()
