"""Offline contract checks applied to the existing Angel One and Upstox adapters.

Fixtures are provider-shaped wire payloads, never evidence of live acceptance.
The main suite owns configuration isolation; standalone execution reuses it.
"""

import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- reuse its offline configuration bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)

from config import BotConfig
from brokers import (
    AngelOneSmartAPIAdapter,
    BrokerDataError,
    CandleFreshnessError,
    MultiBrokerScanner,
    UpstoxV2Adapter,
    assess_live_candle_batch,
)
from scanner_engine import IntradayBotEngine
from strategies import IST, filter_completed_candles, parse_ist_timestamp


class TestSharedMarketDataContract(unittest.TestCase):
    PROVIDERS = ("angelone", "upstox")

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 36, 5, tzinfo=IST)
        self.network = patch("urllib.request.urlopen", side_effect=AssertionError("External transport forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_independent_modules_ignore_process_configuration_and_discovery_has_no_duplicates(self):
        import subprocess
        from pathlib import Path
        code = (
            "import unittest,test_bot; "
            "loader=unittest.TestLoader(); suite=loader.discover('.')\n"
            "def flatten(suite):\n"
            " for item in suite:\n"
            "  if isinstance(item,unittest.TestSuite): yield from flatten(item)\n"
            "  else: yield item.id()\n"
            "ids=list(flatten(suite)); assert len(ids)==len(set(ids)); test_bot._test_environment.stop(); "
            "suite=loader.loadTestsFromNames(['test_angel_market_data.TestAngelMarketDataSafety.test_completed_candles_are_bound_and_fresh_without_profile_calls',"
            "'test_market_data_contract.TestSharedMarketDataContract.test_five_minute_adapters_agree_on_completed_prices_and_volume']); "
            "result=unittest.TextTestRunner().run(suite); raise SystemExit(not result.wasSuccessful())")
        env = dict(os.environ, SESSION_START_IST="13:15", TELEGRAM_DRY_RUN="false",
                   ACTIVE_BROKER="invalid_terminal_override", ENABLE_BACKGROUND_SCHEDULER="true")
        completed = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", "-c", code],
            cwd=Path(__file__).resolve().parent, env=env, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def _adapter(self, provider):
        cfg = BotConfig(
            active_broker=provider, angel_api_key="OFFLINE_CONTRACT_KEY",
            angel_client_code="OFFLINE_CONTRACT_CLIENT", angel_pin="1234",
            angel_totp_secret="JBSWY3DPEHPK3PXP", angel_scrip_master_path="",
            upstox_api_key="OFFLINE_CONTRACT_KEY", upstox_access_token="OFFLINE_CONTRACT_TOKEN",
            telegram_bot_token="", telegram_chat_id="", telegram_dry_run=True,
            enable_background_scheduler=False, enable_persistence=False, database_url=":memory:",
        )
        cfg.fo_indices = {}
        cfg.equity_watchlist = [copy.deepcopy(next(m for m in cfg.equity_watchlist if m["symbol"] == "RELIANCE"))]
        cls = AngelOneSmartAPIAdapter if provider == "angelone" else UpstoxV2Adapter
        return cls(cfg, clock=lambda: self.now), cfg.equity_watchlist[0]

    def _rows(self, start=None, count=12, interval=1):
        start = start or datetime(2026, 10, 16, 10, 25, tzinfo=IST)
        return [[(start + timedelta(minutes=interval*i)).isoformat(), 100, 102, 99, 101, 100]
                for i in range(count)]

    def _payload(self, broker, rows, **envelope):
        provider = broker
        result = (dict(status=True, data=copy.deepcopy(rows)) if provider == "angelone" else
                  dict(status="success", data=dict(candles=list(reversed(copy.deepcopy(rows))))))
        result.update(envelope)
        return result

    def _fetch(self, broker, rows, interval=1, **envelope):
        provider = broker
        adapter, meta = self._adapter(provider)
        with patch.object(adapter, "_request_json", return_value=self._payload(provider, rows, **envelope)) as transport:
            candles = adapter.get_intraday_candles(meta, interval_min=interval)
        self.assertEqual(transport.call_count, 1)
        if provider == "angelone":
            self.assertEqual(transport.call_args.args[:2],
                             ("POST", "/rest/secure/angelbroking/historical/v1/getCandleData"))
            self.assertEqual(transport.call_args.kwargs["payload"]["symboltoken"], meta["angel_token"])
        else:
            self.assertTrue(transport.call_args.args[0].startswith("/historical-candle/intraday/NSE_EQ%7CINE002A01018/"))
        return candles, adapter

    def test_both_adapters_preserve_live_identity_source_and_normalized_ohlcv(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                bars, adapter = self._fetch(provider, self._rows())
                self.assertEqual(len(bars), 12)
                for bar in bars:
                    self.assertEqual([bar[k] for k in ("open", "high", "low", "close", "volume")],
                                     [100.0, 102.0, 99.0, 101.0, 100.0])
                    self.assertEqual(bar["timestamp_timezone"], "Asia/Kolkata")
                    self.assertEqual(bar["interval_min"], 1)
                    self.assertFalse(bar["is_simulated"])
                    self.assertEqual(bar["data_mode"], "LIVE")
                    identity = bar["instrument_identity"]
                    self.assertEqual((identity["provider"], identity["symbol"], identity["exchange"]),
                                     (provider, "RELIANCE", "NSE"))
                    self.assertEqual(identity["historical_validity"], "NOT_ESTABLISHED")
                    self.assertEqual(identity["response_binding"], "REQUEST_BOUND_NO_ECHO")
                    self.assertTrue(identity["source_revision"])
                self.assertEqual(adapter.last_candle_freshness["status"], "FRESH_IN_SESSION")
                self.assertEqual(bars[-1]["timestamp"], "2026-10-16 10:36:00")
                self.assertFalse(bars[-1]["is_complete"])
                completed = filter_completed_candles(bars, interval_min=1, now=self.now)
                self.assertEqual(completed[-1]["timestamp"], "2026-10-16 10:35:00")

    def test_provider_utc_observation_times_normalize_without_using_request_clock(self):
        rows = self._rows()
        for row in rows:
            row[0] = parse_ist_timestamp(row[0]).astimezone(timezone.utc).isoformat()
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                bars, _ = self._fetch(provider, rows)
                self.assertEqual(bars[0]["timestamp"], "2026-10-16 10:25:00")
                self.assertNotEqual(bars[-1]["timestamp"], self.now.strftime("%Y-%m-%d %H:%M:%S"))

    def test_missing_naive_malformed_and_boolean_source_timestamps_reject(self):
        for timestamp in (None, "", "2026-10-16 10:25:00", "invalid", True):
            for provider in self.PROVIDERS:
                with self.subTest(provider=provider, timestamp=timestamp):
                    rows = self._rows()
                    rows[0][0] = timestamp
                    with self.assertRaises(BrokerDataError):
                        self._fetch(provider, rows)

    def test_future_source_timestamp_rejects(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                rows = self._rows(start=self.now.replace(second=0)+timedelta(minutes=1), count=1)
                with self.assertRaises(BrokerDataError):
                    self._fetch(provider, rows)

    def test_duplicates_are_rejected_before_any_normalization_can_hide_them(self):
        rows = self._rows()
        rows.insert(3, copy.deepcopy(rows[2]))
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider), self.assertRaises(BrokerDataError):
                self._fetch(provider, rows)

    def test_wire_order_violations_reject_instead_of_silent_sorting(self):
        rows = self._rows()
        rows[2], rows[3] = rows[3], rows[2]
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider), self.assertRaises(BrokerDataError):
                self._fetch(provider, rows)

    def test_missing_intraday_interval_rejects(self):
        rows = self._rows()
        del rows[3]
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider), self.assertRaises(BrokerDataError):
                self._fetch(provider, rows)

    def test_off_grid_and_outside_session_rows_reject(self):
        for timestamp in ("2026-10-16T10:25:01+05:30", "2026-10-16T09:14:00+05:30",
                          "2026-10-16T15:30:00+05:30", "2026-10-17T10:25:00+05:30"):
            for provider in self.PROVIDERS:
                with self.subTest(provider=provider, timestamp=timestamp):
                    rows = self._rows()
                    rows[0][0] = timestamp
                    with self.assertRaises(BrokerDataError):
                        self._fetch(provider, rows)

    def test_invalid_ohlcv_rows_reject_for_both_providers(self):
        for column, value in ((1, 0), (2, 98), (3, 103), (4, float("nan")),
                              (5, -1), (5, float("inf")), (5, True), (1, "bad")):
            for provider in self.PROVIDERS:
                with self.subTest(provider=provider, column=column, value=value):
                    rows = self._rows()
                    rows[0][column] = value
                    with self.assertRaises(BrokerDataError):
                        self._fetch(provider, rows)

    def test_stale_and_only_forming_batches_cannot_establish_readiness(self):
        batches = (self._rows(start=datetime(2026, 10, 16, 9, 15, tzinfo=IST)),
                   self._rows(start=self.now.replace(second=0), count=1))
        for rows in batches:
            for provider in self.PROVIDERS:
                with self.subTest(provider=provider, timestamp=rows[0][0]):
                    adapter, meta = self._adapter(provider)
                    with patch.object(adapter, "_request_json", return_value=self._payload(provider, rows)):
                        with self.assertRaises(BrokerDataError):
                            adapter.get_intraday_candles(meta, interval_min=1)
                    self.assertFalse(adapter.last_candle_freshness["live_signal_allowed"])

    def test_conflicting_provider_response_identity_rejects(self):
        for provider in self.PROVIDERS:
            for conflict in (dict(symbol="HDFCBANK"), dict(provider="dhan"), dict(exchange="BSE")):
                with self.subTest(provider=provider, conflict=conflict), self.assertRaises(BrokerDataError):
                    self._fetch(provider, self._rows(), **conflict)

    def test_wrong_configured_instrument_rejects_before_transport(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter, meta = self._adapter(provider)
                meta = dict(meta)
                meta["angel_token" if provider == "angelone" else "upstox_key"] = "WRONG"
                with patch.object(adapter, "_request_json") as transport, self.assertRaises(BrokerDataError):
                    adapter.get_intraday_candles(meta, interval_min=1)
                transport.assert_not_called()

    def test_echo_checked_identity_does_not_imply_historical_source_qualification(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                bars, _ = self._fetch(provider, self._rows(), symbol="RELIANCE", provider=provider)
                for bar in bars:
                    self.assertEqual(bar["instrument_identity"]["response_binding"], "ECHO_CHECKED")
                    self.assertEqual(bar["instrument_identity"]["historical_validity"], "NOT_ESTABLISHED")

    def test_five_minute_adapters_agree_on_completed_prices_and_volume(self):
        angel_rows = self._rows(count=3, interval=5)
        for row in angel_rows:
            row[5] = 500
        angel, _ = self._fetch("angelone", angel_rows, interval=5)
        upstox, _ = self._fetch("upstox", self._rows(), interval=5)
        keys = ("timestamp", "open", "high", "low", "close", "volume", "is_complete")
        angel_completed = filter_completed_candles(angel, now=self.now)
        upstox_completed = filter_completed_candles(upstox, now=self.now)
        self.assertEqual([[c[k] for k in keys] for c in angel_completed],
                         [[c[k] for k in keys] for c in upstox_completed])
        self.assertFalse(angel[-1]["is_complete"])
        self.assertFalse(upstox[-1]["is_complete"])

    def test_synthetic_and_cross_provider_candles_never_authorize_live_scanner_data(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                bars, _ = self._fetch(provider, self._rows())
                for changes in (dict(is_simulated=True), dict(data_mode="SIMULATED"), dict(data_mode="UNKNOWN")):
                    polluted = [dict(bar, **changes) for bar in bars]
                    _, report = assess_live_candle_batch(polluted, 1, self.now, provider=provider,
                                                        context="SCANNER", normalized_ist=True)
                    self.assertEqual(report["status"], "INVALID_PROVENANCE")
                    self.assertFalse(report["live_signal_allowed"])
                other = "upstox" if provider == "angelone" else "angelone"
                manager = MultiBrokerScanner(BotConfig(active_broker=other, telegram_dry_run=True,
                    enable_persistence=False, enable_background_scheduler=False, angel_scrip_master_path=""), clock=lambda: self.now)
                with patch.object(manager.get_active_adapter(), "get_intraday_candles", return_value=bars):
                    with self.assertRaises(BrokerDataError):
                        manager.fetch_candles(dict(self._adapter(other)[1]), interval_min=1)

    def _engine(self, provider, rows):
        adapter, meta = self._adapter(provider)
        manager = MultiBrokerScanner(adapter.config, clock=lambda: self.now)
        manager.adapters[provider] = adapter
        engine = IntradayBotEngine(adapter.config, clock=lambda: self.now, broker_scanner=manager)
        self.addCleanup(engine.close)
        transport = patch.object(adapter, "_request_json", return_value=self._payload(provider, rows))
        transport.start()
        self.addCleanup(transport.stop)
        return engine, adapter, meta

    def test_scanner_rejects_stale_or_gapped_data_before_strategy_or_dispatch(self):
        for provider in self.PROVIDERS:
            rows = (self._rows(start=datetime(2026, 10, 16, 9, 15, tzinfo=IST), count=3, interval=5)
                    if provider == "angelone" else self._rows(start=datetime(2026, 10, 16, 9, 15, tzinfo=IST)))
            with self.subTest(provider=provider):
                engine, _, _ = self._engine(provider, rows)
                with patch("scanner_engine.evaluate_order_block_fvg") as evaluator, \
                     patch.object(engine.telegram, "send_signal") as dispatch:
                    with self.assertRaises(BrokerDataError):
                        engine.run_single_scan()
                evaluator.assert_not_called()
                dispatch.assert_not_called()
                self.assertEqual(engine.last_scan_summary["signals"], [])
                self.assertIsNone(engine.store)

    def test_valid_current_cash_scan_uses_real_evaluators_without_receipt_or_delivery(self):
        import scanner_engine
        names = ("evaluate_order_block_fvg", "evaluate_vwap_pullback", "evaluate_orb_breakout", "evaluate_supertrend_pullback")
        from contextlib import ExitStack
        for provider in self.PROVIDERS:
            rows = (self._rows(count=3, interval=5) if provider == "angelone" else self._rows())
            with self.subTest(provider=provider):
                engine, _, _ = self._engine(provider, rows)
                with ExitStack() as stack:
                    evaluators = [stack.enter_context(patch.object(scanner_engine, name, wraps=getattr(scanner_engine, name)))
                                  for name in names]
                    dispatch = stack.enter_context(patch.object(engine.telegram, "send_signal"))
                    report = engine.run_single_scan()
                self.assertEqual(report["scan_status"], "COMPLETED_EMPTY")
                self.assertEqual(report["total_signals"], 0)
                self.assertTrue(report["candle_freshness"]["live_signal_allowed"])
                self.assertEqual(report["data_mode"], "LIVE")
                self.assertTrue(all(evaluator.call_count == 1 for evaluator in evaluators))
                dispatch.assert_not_called()
                self.assertFalse(engine.config.enable_background_scheduler)
                self.assertTrue(engine.config.telegram_dry_run)
                self.assertIsNone(engine.store)

    def test_scan_evidence_expires_before_later_dispatch_and_is_provider_scoped(self):
        for provider in self.PROVIDERS:
            rows = self._rows(count=3, interval=5) if provider == "angelone" else self._rows()
            with self.subTest(provider=provider):
                engine, _, _ = self._engine(provider, rows)
                engine._fetch_scan_candles(engine.config.equity_watchlist[0], provider)
                engine._require_current_scan_data(provider)
                other = "upstox" if provider == "angelone" else "angelone"
                self.assertFalse(engine._freshness_status(other, self.now)["live_signal_allowed"])
                self.now += timedelta(minutes=7)
                with self.assertRaises(CandleFreshnessError):
                    engine._require_current_scan_data(provider)
                self.now -= timedelta(minutes=7)

    def _cash_dashboard_handler(self, engine):
        """Use real handlers/store without binding a socket or starting a service."""
        from scanner_engine import MarketScanScheduler
        from server import DashboardRequestHandler
        from storage import SQLitePersistenceStore
        engine.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(engine.store.close)
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = engine
        handler.scheduler = MarketScanScheduler(engine, clock=lambda: self.now)
        return handler

    def test_cash_dashboard_missing_angel_credentials_is_unavailable_without_transport(self):
        adapter, _ = self._adapter("angelone")
        adapter.config.angel_api_key = ""
        adapter.config.angel_client_code = ""
        adapter.config.angel_pin = ""
        adapter.config.angel_totp_secret = ""
        manager = MultiBrokerScanner(adapter.config, clock=lambda: self.now)
        manager.adapters["angelone"] = adapter
        engine = IntradayBotEngine(adapter.config, clock=lambda: self.now, broker_scanner=manager)
        self.addCleanup(engine.close)
        handler = self._cash_dashboard_handler(engine)
        with patch("scanner_engine.evaluate_order_block_fvg") as evaluator, \
             patch.object(engine.telegram, "send_signal") as delivery, \
             patch("urllib.request.urlopen", side_effect=AssertionError("No transport allowed")) as wire:
            code, rejected = handler._handle_scan()
        self.assertEqual(code, 502)
        self.assertEqual(rejected["scan_status"], "FAILED")
        evaluator.assert_not_called()
        delivery.assert_not_called()
        wire.assert_not_called()
        code, health = handler._handle_health()
        self.assertEqual(code, 200)
        self.assertEqual(health["broker"]["connection_state"], "UNAVAILABLE_MISSING_CREDENTIALS")
        self.assertFalse(health["broker"]["live_signals_allowed"])
        self.assertFalse(health["live_acceptance"]["accepted"])
        self.assertFalse(health["scheduler"]["running"])
        self.assertEqual(handler._handle_signals({})[1]["items"], [])
        self.assertEqual(handler._handle_scans({})[1]["items"][0]["status"], "FAILED")

    def test_cash_dashboard_stale_mock_wire_rejects_before_evaluation_and_persists_failure(self):
        rows = self._rows(start=datetime(2026, 10, 16, 9, 15, tzinfo=IST), count=3, interval=5)
        engine, _, _ = self._engine("angelone", rows)
        handler = self._cash_dashboard_handler(engine)
        with patch("scanner_engine.evaluate_order_block_fvg") as evaluator, \
             patch.object(engine.telegram, "send_signal") as delivery:
            code, rejected = handler._handle_scan()
        self.assertEqual(code, 502)
        self.assertEqual(rejected["scan_status"], "FAILED")
        self.assertFalse(rejected["freshness"]["live_signal_allowed"])
        evaluator.assert_not_called()
        delivery.assert_not_called()
        _, health = handler._handle_health()
        self.assertEqual(health["broker"]["connection_state"], "ERROR")
        self.assertFalse(health["broker"]["live_signals_allowed"])
        self.assertFalse(health["live_acceptance"]["accepted"])
        self.assertEqual(health["last_scan"]["scan_status"], "FAILED")
        self.assertEqual(handler._handle_signals({})[1]["items"], [])
        self.assertEqual(handler._handle_scans({})[1]["items"][0]["status"], "FAILED")

    def test_cash_dashboard_fresh_mock_wire_no_signal_uses_actual_evaluators_and_store(self):
        import scanner_engine
        from contextlib import ExitStack
        # Three complete fixture sessions plus the current partial session exceed
        # every evaluator's warmup, including Supertrend's 200 completed candles.
        rows = []
        for day in (13, 14, 15):
            rows.extend(self._rows(start=datetime(2026, 10, day, 9, 15, tzinfo=IST), count=75, interval=5))
        rows.extend(self._rows(start=datetime(2026, 10, 16, 9, 15, tzinfo=IST), count=17, interval=5))
        engine, _, _ = self._engine("angelone", rows)
        handler = self._cash_dashboard_handler(engine)
        names = ("evaluate_order_block_fvg", "evaluate_vwap_pullback", "evaluate_orb_breakout", "evaluate_supertrend_pullback")
        with ExitStack() as stack:
            evaluated = [stack.enter_context(patch.object(scanner_engine, name, wraps=getattr(scanner_engine, name)))
                         for name in names]
            delivery = stack.enter_context(patch.object(engine.telegram, "send_signal"))
            code, result = handler._handle_scan()
        self.assertEqual(code, 200)
        self.assertEqual(result["scan_status"], "COMPLETED_EMPTY")
        self.assertEqual(result["total_signals"], 0)
        self.assertTrue(all(item.call_count == 1 for item in evaluated))
        for item in evaluated:
            candles = item.call_args.kwargs["candles"]
            self.assertEqual(len(filter_completed_candles(candles, interval_min=5, now=self.now)), 241)
        self.assertEqual(result["instrument_errors"], [])
        delivery.assert_not_called()
        self.assertTrue(result["candle_freshness"]["live_signal_allowed"])
        _, health = handler._handle_health()
        self.assertEqual(health["broker"]["active_broker"], "angelone")
        self.assertFalse(health["live_acceptance"]["accepted"])
        self.assertFalse(health["scheduler"]["running"])
        self.assertEqual(health["last_scan"]["scan_status"], "COMPLETED_EMPTY")
        self.assertEqual(handler._handle_signals({})[1]["items"], [])
        stored = handler._handle_scans({})[1]["items"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["status"], "COMPLETED_EMPTY")
        self.assertEqual(stored[0]["data_mode"], "LIVE")  # Mock wire provenance, not live acceptance.


if __name__ == "__main__":
    unittest.main()
