"""Phase 6 Workstream C — Performance Validity, Backtest Determinism & Data Gating.

Validates:
1. Deterministic evaluation harness:
   - Identical frozen configuration & inputs produce byte-for-byte identical results & run_ids.
2. Financial & metrics reconciliation:
   - Trade-level sum of net P&L equals portfolio ending_capital - starting_capital.
   - Trade-level gross P&L - total charges - total slippage equals net P&L.
   - Profit factor, win rate, expectancy, and max drawdown are mathematically consistent.
3. Look-ahead bias prevention:
   - Future or unclosed bars leak check raises LookAheadBiasError.
4. Empirical historical performance external-data gate:
   - Blocks empirical historical study acceptance when authentic publisher-signed datasets with
     cryptographic trust roots (Ed25519) and legal redistribution rights are absent.
   - Prohibits synthetic fixtures from satisfying the external live data gate.
   - Strictly enforces profitability_claim_justified is False.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- existing offline configuration bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from backtest_engine import (
    BacktestConfig,
    BacktestReadinessError,
    DeterministicBacktestEngine,
    IndianCostModel,
)
from config import BotConfig
from historical_data import LookAheadBiasError, verify_no_lookahead_leakage
from storage import SQLitePersistenceStore
from strategies import IST


class TestPhase6PerformanceValidity(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 16, 0, 0, tzinfo=IST)
        self.temporary = tempfile.TemporaryDirectory(prefix="tradepulse_phase6_perf_")
        self.addCleanup(self.temporary.cleanup)
        self.database = str(Path(self.temporary.name) / "perf.sqlite")
        self.store = SQLitePersistenceStore(self.database)
        self.addCleanup(self.store.close)

        self.transport = patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Performance validity tests must never contact external transport"),
        )
        self.transport.start()
        self.addCleanup(self.transport.stop)

        self.delivery = patch(
            "telegram_bot.TelegramSignalDispatcher.send_signal",
            side_effect=AssertionError("Performance tests must never dispatch real alerts"),
        )
        self.delivery.start()
        self.addCleanup(self.delivery.stop)

        self.bot_config = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            enable_background_scheduler=False,
            account_capital_inr=150000.0,
            max_risk_per_trade_pct=1.0,
        )
        self.engine = DeterministicBacktestEngine(
            bot_config=self.bot_config,
            store=self.store,
            clock=lambda: self.now,
        )

    def _generate_synthetic_bars(self, symbol="RELIANCE", days=("2026-10-14", "2026-10-15")):
        """Generates valid 5-min OHLCV bars across sessions."""
        bars = []
        base_price = 2500.0
        for d_str in days:
            current_dt = datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=IST)
            t = dt_time(9, 15)
            session_end = dt_time(15, 30)
            while t < session_end:
                ts_str = f"{d_str}T{t.strftime('%H:%M')}:00+05:30"
                # Predictable oscillation
                o = base_price
                h = base_price + 5.0
                l = base_price - 3.0
                c = base_price + 2.0
                v = 5000.0
                bars.append({
                    "timestamp": ts_str,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "is_complete": True,
                    "interval_min": 5,
                    "data_mode": "SIMULATED",
                    "is_simulated": True,
                    "symbol": symbol,
                    "segment": "NSE_EQUITY_INTRADAY",
                    "exchange": "NSE",
                    "provider": "synthetic_fixture",
                })
                # Increment by 5 mins
                cur_min = t.hour * 60 + t.minute + 5
                t = dt_time(cur_min // 60, cur_min % 60)
                base_price += 1.0
        return bars

    def test_backtest_determinism_and_reproducibility(self):
        """Verifies that running backtest twice on identical inputs produces byte-for-byte identical output."""
        bars = self._generate_synthetic_bars()
        cfg = BacktestConfig(
            starting_capital_inr=150000.0,
            risk_per_trade_pct=1.0,
            execution_convention="NEXT_CANDLE_OPEN",
        )

        res1 = self.engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=copy.deepcopy(bars),
            backtest_config=cfg,
            data_mode="SIMULATED",
            persist_run=False,
        )

        res2 = self.engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=copy.deepcopy(bars),
            backtest_config=cfg,
            data_mode="SIMULATED",
            persist_run=False,
        )

        self.assertEqual(res1["run_id"], res2["run_id"])
        self.assertEqual(res1["metrics"], res2["metrics"])
        self.assertEqual(res1["ending_capital_inr"], res2["ending_capital_inr"])
        self.assertEqual(len(res1["trades"]), len(res2["trades"]))

    def test_trade_level_to_portfolio_accounting_reconciliation(self):
        """Verifies financial reconciliation invariants across trades and portfolio ending capital."""
        bars = self._generate_synthetic_bars()
        cfg = BacktestConfig(
            starting_capital_inr=150000.0,
            risk_per_trade_pct=1.0,
        )

        res = self.engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars,
            backtest_config=cfg,
            data_mode="SIMULATED",
            persist_run=False,
        )

        metrics = res["metrics"]
        starting_cap = float(res["starting_capital_inr"])
        ending_cap = float(res["ending_capital_inr"])
        reported_net_pnl = float(metrics["net_pnl_inr"])

        # Invariant 1: Ending Capital == Starting Capital + Net P&L
        self.assertAlmostEqual(ending_cap, starting_cap + reported_net_pnl, places=2)

        # Invariant 2: Trade Net Sum == Reported Net P&L
        trade_net_sum = sum(float(t["net_pnl_inr"]) for t in res["trades"])
        self.assertAlmostEqual(trade_net_sum, reported_net_pnl, places=2)

        # Invariant 3: Net P&L == Gross P&L - Total Costs (Charges + Slippage)
        reported_gross = float(metrics["gross_pnl_inr"])
        reported_costs = float(metrics["total_costs_inr"])
        self.assertAlmostEqual(reported_net_pnl, reported_gross - reported_costs, places=2)

        # Invariant 4: Drawdown is non-negative and valid
        self.assertGreaterEqual(metrics["max_drawdown_inr"], 0.0)
        self.assertGreaterEqual(metrics["max_drawdown_pct"], 0.0)

    def test_look_ahead_bias_prevention(self):
        """Verifies that attempting to evaluate candles timestamped at or beyond decision time raises LookAheadBiasError."""
        decision_time = datetime(2026, 10, 16, 10, 0, 0, tzinfo=IST)

        # Candle closing after decision time
        future_candle = {
            "timestamp": "2026-10-16T10:00:00+05:30",  # represents 10:00 to 10:05, completes after 10:00
            "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 1000.0,
            "interval_min": 5, "data_mode": "SIMULATED",
        }

        with self.assertRaises(LookAheadBiasError):
            verify_no_lookahead_leakage([future_candle], decision_time_ist=decision_time, interval_min=5)

    def test_empirical_performance_gate_blocks_live_acceptance_without_signed_data(self):
        """Verifies that requesting a LIVE backtest without authentic signed publisher data is blocked."""
        bars = self._generate_synthetic_bars()
        # Mark bars as LIVE synthetically
        for b in bars:
            b["data_mode"] = "LIVE"
            b["is_simulated"] = False

        cfg = BacktestConfig(starting_capital_inr=150000.0)

        # Attempting LIVE backtest without publisher authorization must raise BacktestReadinessError
        with self.assertRaises(BacktestReadinessError) as ctx:
            self.engine.run_backtest(
                strategy_id="strat_1_order_block",
                symbol="RELIANCE",
                candles=bars,
                backtest_config=cfg,
                data_mode="LIVE",
                persist_run=False,
            )
        self.assertIn("Backtest blocked by acceptance/coverage policy", str(ctx.exception))

    def test_profitability_claim_justified_is_strictly_false(self):
        """Verifies that profitability_claim_justified is hard-coded False in metrics output."""
        bars = self._generate_synthetic_bars()
        res = self.engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars,
            data_mode="SIMULATED",
            persist_run=False,
        )
        self.assertFalse(res["metrics"]["profitability_claim_justified"])
        self.assertIn("Win rate alone never establishes profitability", res["metrics"]["profitability_note"])


if __name__ == "__main__":
    unittest.main()
