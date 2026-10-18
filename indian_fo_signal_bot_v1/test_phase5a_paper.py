"""Offline paper-account lifecycle, accounting and failure-boundary regressions."""

import copy
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
from instrument_identity import spot_identity
from paper_portfolio import PaperAccountConfig, PaperPortfolio, PaperPortfolioError
from storage import SQLitePersistenceStore
from strategies import IST, TradeSignal, evaluate_order_block_fvg
from brokers import SimulatedNSEAdapter


class TestPhase5APaperPortfolio(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 10, 5, tzinfo=IST)
        self.temporary = tempfile.TemporaryDirectory(prefix="tradepulse_paper_offline_")
        self.addCleanup(self.temporary.cleanup)
        self.database = str(Path(self.temporary.name) / "paper.sqlite")
        self.store = SQLitePersistenceStore(self.database)
        self.addCleanup(self.store.close)
        self.transport = patch("urllib.request.urlopen", side_effect=AssertionError("Paper service must never contact transport"))
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.delivery = patch("telegram_bot.TelegramSignalDispatcher.send_signal",
                              side_effect=AssertionError("Paper accounting must never dispatch alerts"))
        self.delivery.start()
        self.addCleanup(self.delivery.stop)

    @staticmethod
    def _zero_costs():
        model = IndianCostModel()
        for name, value in model.to_dict().items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(model, name, 0.0)
        return json.dumps(model.to_dict())

    def _config(self, **values):
        return PaperAccountConfig(**dict(dict(account_id="account", run_id="run", provider="upstox",
            source_data_mode="SIMULATED", starting_capital_inr=10000, risk_pct=1,
            max_daily_loss_inr=1000, max_position_exposure_pct=100,
            cost_model_json=self._zero_costs()), **values))

    def _service(self, **values):
        return PaperPortfolio(self.store, self._config(**values), clock=lambda: self.now)

    def _candidate(self, service=None, *, symbol="RELIANCE", strategy="strat_1_order_block", side="LONG", stamp="10:00"):
        cfg = service.config if service else self._config()
        meta = next(m for m in BotConfig.__dataclass_fields__["equity_watchlist"].default_factory() if m["symbol"] == symbol)
        identity = spot_identity(meta, cfg.provider)
        return TradeSignal(symbol=symbol, segment="NSE_EQUITY_INTRADAY", strategy_id=strategy,
            strategy_name="Offline deterministic paper candidate", direction="BULLISH (BUY)" if side == "LONG" else "BEARISH (SELL)",
            instrument_label=symbol + " EQ", entry_price=100, entry_zone_low=99, entry_zone_high=101,
            stop_loss=90 if side == "LONG" else 110, target_1=120 if side == "LONG" else 80,
            target_2=130 if side == "LONG" else 70, risk_reward="fixture", confidence_pct=0,
            win_rate_benchmark="", position_qty=999999, capital_risk_inr=999999, est_charges_inr=0,
            rationale="Offline fixture; no profitability or live acceptance evidence",
            timestamp="2026-10-16 " + stamp + ":00", is_simulated=cfg.source_data_mode == "SIMULATED",
            data_mode=cfg.source_data_mode, position_type="LONG_EQUITY_INTRADAY" if side == "LONG" else "SHORT_EQUITY_INTRADAY",
            invalidation_level=90 if side == "LONG" else 110, provider=cfg.provider,
            state_context="SIMULATED_TEST" if cfg.source_data_mode == "SIMULATED" else "SCANNER",
            interval_min=5, instrument_identity=identity)

    def _bar(self, candidate, stamp="10:05", **values):
        return dict(dict(timestamp="2026-10-16T" + stamp + ":00+05:30", open=100.0, high=105.0,
            low=95.0, close=102.0, volume=1000.0, is_complete=True, interval_min=5,
            data_mode=candidate.data_mode, is_simulated=candidate.is_simulated,
            instrument_identity=copy.deepcopy(candidate.instrument_identity)), **values)

    def _enter(self, service, **changes):
        candidate = self._candidate(service)
        return service.enter(candidate, self._bar(candidate, **changes), "entry"), candidate

    def _set_time(self, stamp, date="2026-10-16"):
        self.now = datetime.fromisoformat(date + "T" + stamp + ":05+05:30")

    def assertRejected(self, expected, action):
        with self.assertRaises(PaperPortfolioError) as caught:
            action()
        self.assertEqual(caught.exception.reason_code, expected)

    def test_real_strategy_candidate_enters_explicit_paper_service_without_altering_source(self):
        self.now = datetime(2026, 10, 16, 10, 35, 5, tzinfo=IST)
        bars = SimulatedNSEAdapter(seed=42, clock=lambda: self.now).get_intraday_candles(
            {"symbol": "RELIANCE"}, pattern="order_block_bull")
        candidate = evaluate_order_block_fvg("RELIANCE", bars, now=self.now)
        self.assertIsNotNone(candidate)
        service = self._service(starting_capital_inr=150000)
        candidate.provider, candidate.state_context = "upstox", "SIMULATED_TEST"
        candidate.data_mode, candidate.is_simulated = "SIMULATED", True
        candidate.instrument_identity = self._candidate(service).instrument_identity
        before = candidate.to_dict()
        self._set_time("10:40")
        result = service.enter(candidate, self._bar(candidate, stamp="10:35", open=2955.8,
            high=2957, low=2955, close=2956), "actual-candidate")
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(candidate.to_dict(), before)
        self.assertEqual(service.snapshot()["positions"][0]["strategy_id"], candidate.strategy_id)
        self.assertEqual(self.store.load_live_acceptance_evidence("upstox", "RELIANCE"), None)

    def test_entry_mark_capital_and_full_exit_reconcile_exactly(self):
        service = self._service()
        result, candidate = self._enter(service)
        snapshot = service.snapshot()
        self.assertEqual(snapshot["accounting"]["reserved_capital_inr"], 1000)
        self.assertEqual(snapshot["accounting"]["available_capital_inr"], 9000)
        self.assertEqual(snapshot["accounting"]["unrealized_net_pnl_inr"], 20)
        self.assertEqual(snapshot["positions"][0]["quantity"], 10)
        self.assertEqual(snapshot["accounting"]["fees_paid_inr"], 0)
        self._set_time("10:15")
        closed = service.process_bar(result["position_id"], self._bar(candidate, stamp="10:10", high=125,
            low=99, close=121), "target")
        self.assertEqual(closed["exit_reason"], "TARGET")
        snapshot = service.snapshot()
        self.assertEqual(snapshot["accounting"]["realized_net_pnl_inr"], 200)
        self.assertEqual(snapshot["accounting"]["equity_inr"], 10200)
        self.assertEqual(snapshot["accounting"]["available_capital_inr"], 10200)
        self.assertEqual(snapshot["accounting"]["reserved_capital_inr"], 0)
        self.assertEqual(service.reconcile(), dict(status="OK", errors=[]))

    def test_default_indian_fees_and_slippage_are_posted_once_on_exit(self):
        service = self._service(cost_model_json="{}")
        result, candidate = self._enter(service)
        self._set_time("10:15")
        bar = self._bar(candidate, stamp="10:10", high=125, low=99, close=121)
        service.process_bar(result["position_id"], bar, "exit")
        before = service.snapshot()
        position = before["positions"][0]
        expected = IndianCostModel().compute_trade_costs(100, 120, position["quantity"], "LONG")
        self.assertEqual(position["costs"], expected)
        self.assertEqual(position["net_pnl_inr"], round(20 * position["quantity"] - expected["total_costs_inr"], 2))
        self.assertEqual(before["accounting"]["fees_paid_inr"], expected["charges_inr"])
        self.assertTrue(service.process_bar(result["position_id"], bar, "exit")["idempotent"])
        self.assertEqual(service.snapshot(), before)

    def test_entry_retry_and_changed_event_or_candidate_conflicts_do_not_reserve_twice(self):
        service = self._service()
        result, candidate = self._enter(service)
        before = service.snapshot()
        self.assertTrue(service.enter(candidate, self._bar(candidate), "entry")["idempotent"])
        self.assertTrue(service.enter(candidate, self._bar(candidate), "entry-again")["idempotent"])
        changed = copy.deepcopy(candidate)
        changed.stop_loss = 91
        changed.invalidation_level = 91
        self.assertRejected("EVENT_IDEMPOTENCY_CONFLICT", lambda: service.enter(changed, self._bar(changed), "entry"))
        self.assertRejected("CANDIDATE_IDEMPOTENCY_CONFLICT", lambda: service.enter(changed, self._bar(changed), "different"))
        self.assertEqual(service.snapshot(), before)
        self.assertEqual(result["execution_mode"], "SIMULATED")

    def test_entry_bar_collision_and_later_collision_choose_stop(self):
        for same_bar in (True, False):
            with self.subTest(same_bar=same_bar):
                service = self._service(account_id="same" if same_bar else "later")
                candidate = self._candidate(service)
                first = self._bar(candidate, high=125 if same_bar else 105, low=85 if same_bar else 95)
                result = service.enter(candidate, first, "entry")
                if not same_bar:
                    self._set_time("10:15")
                    result = service.process_bar(result["position_id"], self._bar(candidate, stamp="10:10",
                        high=125, low=85, close=100), "collision")
                self.assertEqual(result["exit_reason"], "STOP_FIRST_COLLISION")
                self.assertEqual(service.snapshot()["accounting"]["realized_net_pnl_inr"], -100)
                self.assertEqual(service.reconcile()["status"], "OK")
                self._set_time("10:10")

    def test_adverse_stop_gap_and_target_gap_cap_both_directions(self):
        for side in ("LONG", "SHORT"):
            for favorable in (False, True):
                with self.subTest(side=side, favorable=favorable):
                    service = self._service(account_id=side + str(favorable))
                    candidate = self._candidate(service, side=side)
                    result = service.enter(candidate, self._bar(candidate), "entry")
                    self._set_time("10:15")
                    opening = (125 if favorable else 80) if side == "LONG" else (70 if favorable else 125)
                    bar = self._bar(candidate, stamp="10:10", open=opening, high=opening+2,
                                    low=opening-2, close=opening)
                    closed = service.process_bar(result["position_id"], bar, "gap")
                    position = service.snapshot()["positions"][0]
                    self.assertEqual(closed["exit_reason"], "TARGET_GAP_CAPPED" if favorable else "STOP_GAP")
                    self.assertEqual(position["raw_exit_price"], candidate.target_1 if favorable else opening)
                    if not favorable:
                        self.assertGreater(-position["net_pnl_inr"], position["estimated_stop_risk_inr"])
                    self._set_time("10:10")

    def test_eod_closes_at_completed_bar_close_and_missing_eod_is_explicitly_unresolved(self):
        self._set_time("15:15")
        service = self._service()
        candidate = self._candidate(service, stamp="15:05")
        result = service.enter(candidate, self._bar(candidate, stamp="15:10"), "entry")
        self._set_time("15:20")
        self.assertIn("UNRESOLVED_EOD_POSITION", service.snapshot()["entry_blocks"])
        closed = service.process_bar(result["position_id"], self._bar(candidate, stamp="15:15", close=103), "eod")
        self.assertEqual(closed["exit_reason"], "EOD")
        self.assertEqual(service.snapshot()["positions"][0]["raw_exit_price"], 103)
        self._set_time("10:10", date="2026-10-19")
        self.assertEqual(service.snapshot()["entry_blocks"], [])
        self.assertEqual(service.snapshot()["accounting"]["day"]["entries"], 0)

    def test_missing_stale_future_incomplete_and_invalid_marks_never_refresh_or_unlock_entry(self):
        service = self._service()
        result, candidate = self._enter(service)
        before_position = service.snapshot()["positions"][0]
        self._set_time("10:20")
        self.assertIn("MISSING_OR_STALE_MARKS", service.snapshot()["entry_blocks"])
        for update in (dict(), dict(is_complete=False), dict(high=1), dict(data_mode="LIVE", is_simulated=False),
                       dict(timestamp="2026-10-16T10:25:00+05:30")):
            with self.subTest(update=update), self.assertRaises(PaperPortfolioError):
                service.process_bar(result["position_id"], self._bar(candidate, stamp="10:10", **update), "invalid")
        self.assertEqual(service.snapshot()["positions"][0], before_position)
        next_candidate = self._candidate(service, symbol="TCS", stamp="10:10")
        self.assertRejected("MISSING_OR_STALE_MARKS", lambda: service.enter(next_candidate,
            self._bar(next_candidate, stamp="10:15"), "new-entry"))

    def test_bar_gap_and_out_of_order_input_freeze_without_invented_marks(self):
        service = self._service()
        result, candidate = self._enter(service)
        self._set_time("10:20")
        self.assertRejected("MISSING_OR_OUT_OF_ORDER_POSITION_BAR", lambda: service.process_bar(result["position_id"],
            self._bar(candidate, stamp="10:15"), "gap"))
        self.assertEqual(service.snapshot()["positions"][0]["mark_timestamp_ist"], "2026-10-16 10:05:00")

    def test_daily_loss_uses_realized_plus_open_unrealized_net(self):
        service = self._service(max_daily_loss_inr=40)
        result, candidate = self._enter(service, close=95)
        snapshot = service.snapshot()
        self.assertEqual(snapshot["accounting"]["day"]["net_pnl_inr"], -50)
        self.assertTrue(snapshot["accounting"]["day"]["loss_limit_breached"])
        other = self._candidate(service, symbol="TCS")
        self.assertRejected("DAILY_LOSS_LIMIT", lambda: service.enter(other, self._bar(other), "second"))
        self._set_time("10:15")
        service.process_bar(result["position_id"], self._bar(candidate, stamp="10:10", low=85, close=90), "loss")
        self.assertEqual(service.snapshot()["accounting"]["day"]["net_pnl_inr"], -100)
        self.assertEqual(service.snapshot()["accounting"]["unrealized_net_pnl_inr"], 0)

    def test_configured_open_and_daily_entry_counts_are_account_wide(self):
        for setting, reason in ((dict(max_open_positions=1), "OPEN_POSITION_LIMIT"),
                                (dict(max_entries_per_day=1), "DAILY_ENTRY_LIMIT")):
            with self.subTest(setting=setting):
                service = self._service(account_id=reason, **setting)
                self._enter(service)
                other = self._candidate(service, symbol="TCS", strategy="strat_2_vwap_pullback")
                self.assertRejected(reason, lambda: service.enter(other, self._bar(other), "other-strategy"))
                self.assertEqual(service.snapshot()["accounting"]["day"]["entries"], 1)

    def test_exposure_caps_bound_shared_reservations_and_reject_subshare_room(self):
        service = self._service(risk_pct=100, max_position_exposure_pct=20, max_total_exposure_pct=30)
        self._enter(service)
        first = service.snapshot()
        self.assertEqual(first["accounting"]["gross_exposure_inr"], 2000)
        other = self._candidate(service, symbol="TCS")
        service.enter(other, self._bar(other), "second")
        self.assertEqual(service.snapshot()["accounting"]["gross_exposure_inr"], 3000)
        third = self._candidate(service, symbol="SBIN")
        self.assertRejected("EXPOSURE_LIMIT", lambda: service.enter(third, self._bar(third), "third"))
        self.assertLessEqual(service.snapshot()["accounting"]["reserved_capital_inr"], 10000)

    def test_concurrent_services_compete_transactionally_for_same_shared_capital(self):
        cfg = self._config(risk_pct=100, max_open_positions=10)
        first = PaperPortfolio(self.store, cfg, clock=lambda: self.now)
        other_store = SQLitePersistenceStore(self.database)
        self.addCleanup(other_store.close)
        second = PaperPortfolio(other_store, cfg, clock=lambda: self.now)
        candidates = [self._candidate(first), self._candidate(second, symbol="TCS")]
        def entry(index):
            try:
                return (first if index == 0 else second).enter(candidates[index], self._bar(candidates[index]), "entry" + str(index))
            except PaperPortfolioError as exc:
                return exc.reason_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(entry, range(2)))
        self.assertEqual(sum(isinstance(outcome, dict) for outcome in outcomes), 1)
        snapshot = first.snapshot()
        self.assertEqual(snapshot["accounting"]["open_positions"], 1)
        self.assertEqual(snapshot["accounting"]["available_capital_inr"], 0)
        self.assertEqual(first.reconcile()["status"], "OK")

    def test_concurrent_duplicate_entries_commit_one_position_and_event_pair(self):
        service = self._service()
        candidate = self._candidate(service)
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: service.enter(candidate, self._bar(candidate), "same-entry"), range(8)))
        self.assertEqual(sum(not result.get("idempotent", False) for result in outcomes), 1)
        self.assertEqual(service.snapshot()["accounting"]["open_positions"], 1)
        self.assertEqual(service.snapshot()["total_events"], 2)

    def test_failed_event_insert_rolls_back_position_reservation_and_mark_together(self):
        service = self._service()
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("CREATE TRIGGER paper_test_failure BEFORE INSERT ON paper_events BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
        with self.assertRaises(Exception):
            self._enter(service)
        snapshot = service.snapshot()
        self.assertEqual(snapshot["positions"], [])
        self.assertEqual(snapshot["total_events"], 0)
        self.assertEqual(snapshot["accounting"]["available_capital_inr"], 10000)
        self.assertEqual(snapshot["reconciliation"]["status"], "OK")

    def test_restart_keeps_immutable_configuration_ledger_and_freshness(self):
        service = self._service()
        self._enter(service)
        before = service.snapshot()
        self.store.close()
        replacement = SQLitePersistenceStore(self.database)
        self.addCleanup(replacement.close)
        restarted = PaperPortfolio(replacement, service.config, clock=lambda: self.now)
        self.assertEqual(restarted.snapshot(), before)
        self.assertRejected("IMMUTABLE_ACCOUNT_CONFIG_CONFLICT", lambda: PaperPortfolio(replacement,
            replace(service.config, run_id="different-run"), clock=lambda: self.now))
        self.assertRejected("IMMUTABLE_ACCOUNT_CONFIG_CONFLICT", lambda: PaperPortfolio(replacement,
            replace(service.config, risk_pct=2), clock=lambda: self.now))
        self.assertEqual(restarted.reconcile()["status"], "OK")

    def test_recovery_detects_position_tampering_and_blocks_new_entry(self):
        service = self._service()
        result, _ = self._enter(service)
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM paper_positions WHERE position_id=?", (result["position_id"],)).fetchone()
            position = json.loads(row["payload_json"])
            position["quantity"] += 1
            conn.execute("UPDATE paper_positions SET payload_json=? WHERE position_id=?", (json.dumps(position), result["position_id"]))
        self.assertEqual(service.reconcile()["status"], "RECONCILIATION_REQUIRED")
        candidate = self._candidate(service, symbol="TCS")
        self.assertRejected("RECONCILIATION_REQUIRED", lambda: service.enter(candidate, self._bar(candidate), "after-corruption"))

    def test_provider_source_mode_account_strategy_and_run_scopes_are_explicit(self):
        hashes = set()
        for index, (provider, mode, strategy) in enumerate((
                ("upstox", "SIMULATED", "strat_1_order_block"), ("upstox", "LIVE", "strat_1_order_block"),
                ("angelone", "SIMULATED", "strat_1_order_block"), ("upstox", "SIMULATED", "strat_2_vwap_pullback"))):
            service = self._service(account_id="account" + str(index), run_id="run" + str(index),
                                    provider=provider, source_data_mode=mode)
            candidate = self._candidate(service, strategy=strategy)
            service.enter(candidate, self._bar(candidate), "same-external-key")
            snapshot = service.snapshot()
            hashes.add(snapshot["config_hash"])
            self.assertEqual(snapshot["accounting"]["open_positions"], 1)
            self.assertEqual(snapshot["positions"][0]["strategy_id"], strategy)
            self.assertEqual(snapshot["execution_mode"], "SIMULATED")
            self.assertEqual(snapshot["source_data_mode"], mode)
            self.assertIsNone(self.store.load_live_acceptance_evidence(provider, "RELIANCE"))
        self.assertEqual(len(hashes), 4)

    def test_conflicting_candidate_and_bar_identity_or_source_never_consume_capital(self):
        service = self._service()
        candidate = self._candidate(service)
        for key, value in (("provider", "angelone"), ("data_mode", "LIVE"), ("strategy_id", "strat_3_option_apex_oi"),
                           ("segment", "NSE_FO_INDEX"), ("stop_loss", True), ("target_1", float("inf"))):
            with self.subTest(field=key), self.assertRaises((PaperPortfolioError, ValueError)):
                modified = copy.deepcopy(candidate)
                setattr(modified, key, value)
                service.enter(modified, self._bar(candidate), "invalid-candidate")
        bar = self._bar(candidate)
        bar["instrument_identity"]["identifier"] = "WRONG"
        self.assertRejected("BAR_INSTRUMENT_IDENTITY_MISMATCH", lambda: service.enter(candidate, bar, "wrong-identity"))
        self.assertEqual(service.snapshot()["positions"], [])

    def test_only_exact_next_completed_bar_with_valid_entry_bracket_can_fill(self):
        for side in ("LONG", "SHORT"):
            service = self._service(account_id=side)
            candidate = self._candidate(service, side=side)
            adverse = candidate.stop_loss-10 if side == "LONG" else candidate.stop_loss+10
            favorable = candidate.target_1+10 if side == "LONG" else candidate.target_1-10
            for price in (candidate.stop_loss, candidate.target_1, adverse, favorable):
                with self.subTest(side=side, price=price):
                    bar = self._bar(candidate, open=price, high=max(price, 130), low=min(price, 70), close=price)
                    self.assertRejected("ENTRY_GAP_OUTSIDE_VALID_BRACKET", lambda: service.enter(candidate, bar, "bad-open"))
            candidate.timestamp = "2026-10-16 09:55:00"
            self.assertRejected("NEXT_COMPLETED_SAME_SESSION_BAR_REQUIRED", lambda: service.enter(candidate,
                self._bar(candidate), "missing-next"))
            self.assertEqual(service.snapshot()["positions"], [])

    def test_empty_day_reporting_is_read_only_and_missing_account_never_created(self):
        missing = PaperPortfolio.report_existing(self.store, "missing", as_of=self.now)
        self.assertEqual(missing["status"], "NOT_CONFIGURED")
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM paper_accounts").fetchone()[0], 0)
            with self.assertRaises(Exception):
                conn.execute("INSERT INTO paper_accounts VALUES('forbidden','x','{}','x')")
        service = self._service()
        report = PaperPortfolio.report_existing(self.store, "account", as_of=self.now)
        self.assertEqual(report, service.snapshot())
        self.assertEqual(report["accounting"]["equity_inr"], 10000)
        self.assertEqual(report["total_events"], 0)

    def test_nonfinite_mutable_or_unsupported_configuration_is_rejected(self):
        for values in (dict(risk_pct=True), dict(starting_capital_inr=float("nan")), dict(max_daily_loss_inr=-1),
                       dict(max_open_positions=True), dict(max_mark_age_seconds=61), dict(interval_min=True),
                       dict(source_data_mode="UNKNOWN"), dict(provider="unknown"), dict(account_id="bad account"),
                       dict(allowed_strategies=("strat_3_option_apex_oi",)), dict(configured_holidays="2026-10-16"),
                       dict(cost_model_json='{"slippage_bps_per_leg":-1}'), dict(cost_model_json="[]"),
                       dict(square_off_ist="16:00")):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self._config(**values)
        config = self._config(allowed_strategies=["strat_1_order_block"])
        self.assertIsInstance(config.allowed_strategies, tuple)
        with self.assertRaises(Exception):
            config.risk_pct = 50

    def test_explicit_top_level_identity_echo_conflicts_reject_for_each_source_mode(self):
        for mode in ("LIVE", "SIMULATED"):
            service = self._service(account_id=mode, source_data_mode=mode)
            candidate = self._candidate(service)
            for field, value in (("symbol", "TCS"), ("provider", "angelone"), ("exchange", "BSE"),
                                 ("instrument_token", "WRONG"), ("symbolToken", "WRONG")):
                with self.subTest(mode=mode, field=field):
                    bar = self._bar(candidate, **{field: value})
                    self.assertRejected("BAR_INSTRUMENT_IDENTITY_MISMATCH", lambda: service.enter(candidate, bar, "echo"))
            self.assertEqual(service.snapshot()["positions"], [])

    def test_reconciliation_recalculates_costs_after_position_and_exit_copy_tampering(self):
        service = self._service(cost_model_json="{}")
        result, candidate = self._enter(service)
        self._set_time("10:15")
        service.process_bar(result["position_id"], self._bar(candidate, stamp="10:10", high=125, close=121), "exit")
        with self.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM paper_positions WHERE position_id=?", (result["position_id"],)).fetchone()
            position = json.loads(row["payload_json"])
            position["costs"]["charges_inr"] = 0
            conn.execute("UPDATE paper_positions SET payload_json=? WHERE position_id=?", (json.dumps(position), result["position_id"]))
            row = conn.execute("SELECT payload_json FROM paper_events WHERE account_id=? AND kind='EXIT'", (service.config.account_id,)).fetchone()
            payload = json.loads(row["payload_json"])
            payload["exit"]["costs"]["charges_inr"] = 0
            conn.execute("UPDATE paper_events SET payload_json=? WHERE account_id=? AND kind='EXIT'", (json.dumps(payload), service.config.account_id))
        self.assertIn("RECALCULATED_EXIT_ACCOUNTING_MISMATCH", service.reconcile()["errors"])

    def test_failed_exit_transaction_keeps_prior_mark_and_reservation_recoverable(self):
        service = self._service()
        result, candidate = self._enter(service)
        before = service.snapshot()["positions"][0]
        with self.store.paper_transaction(write=True) as conn:
            conn.execute("CREATE TRIGGER paper_exit_failure BEFORE INSERT ON paper_events WHEN NEW.kind='EXIT' BEGIN SELECT RAISE(ABORT,'fixture exit rollback'); END")
        self._set_time("10:15")
        with self.assertRaises(Exception):
            service.process_bar(result["position_id"], self._bar(candidate, stamp="10:10", high=125, close=121), "exit")
        self.assertEqual(service.snapshot()["positions"][0], before)
        self.assertEqual(service.snapshot()["accounting"]["reserved_capital_inr"], 1000)
        self.assertEqual(service.reconcile()["status"], "OK")

    def test_mark_event_retry_is_idempotent_and_reusing_key_for_new_bar_conflicts(self):
        service = self._service()
        result, candidate = self._enter(service)
        self._set_time("10:15")
        bar = self._bar(candidate, stamp="10:10", close=103)
        service.process_bar(result["position_id"], bar, "mark")
        before = service.snapshot()
        self.assertTrue(service.process_bar(result["position_id"], bar, "mark")["idempotent"])
        self.assertEqual(service.snapshot(), before)
        self._set_time("10:20")
        self.assertRejected("EVENT_IDEMPOTENCY_CONFLICT", lambda: service.process_bar(result["position_id"],
            self._bar(candidate, stamp="10:15"), "mark"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
