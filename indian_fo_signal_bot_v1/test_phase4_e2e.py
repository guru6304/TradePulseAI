"""OFFLINE SIMULATION: real cash-data pipeline with provider-shaped wire fixtures.

These fixtures establish implementation behavior, never live acceptance. Real
adapters intentionally retain their LIVE validation/state semantics in temporary
stores; no synthetic rows or receipts are written to an application database.
"""

import copy
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
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


from brokers import BrokerDataError, MultiBrokerScanner, SimulatedNSEAdapter
from config import BotConfig
from readiness_policy import execution_gate
from scanner_engine import IntradayBotEngine
from storage import SQLitePersistenceStore
from strategies import IST, TradeSignal, evaluate_order_block_fvg, parse_ist_timestamp, size_position


class TestPhase4OfflineEndToEnd(unittest.TestCase):
    PROVIDERS = ("angelone", "upstox")
    ANGEL_LOGIN = "/rest/auth/angelbroking/user/v1/loginByPassword"
    ANGEL_QUOTE = "/rest/secure/angelbroking/market/v1/quote/"
    ANGEL_CANDLES = "/rest/secure/angelbroking/historical/v1/getCandleData"

    def setUp(self):
        self.now = datetime(2026, 10, 16, 14, 15, 5, tzinfo=IST)
        self.temp = tempfile.TemporaryDirectory(prefix="tradepulse_offline_phase4_")
        self.addCleanup(self.temp.cleanup)
        self.responses = []
        self.requests = []
        self.forbidden_requests = []
        self.failures = {}
        self.batches = {}
        self.transport = patch("urllib.request.urlopen", side_effect=self._open)
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def tearDown(self):
        self.assertEqual(self.forbidden_requests, [], "Unexpected transport/delivery endpoint")
        self.assertTrue(all(stream.closed for stream in self.responses), "Response resource was not closed")

    def _fixture(self):
        # Reuse the existing trigger generator. Relocate its last 60 price bars to
        # one complete NSE session, respecting Upstox's intraday-only endpoint.
        # No evaluator or validator is replaced to make this fixture trigger.
        bars = SimulatedNSEAdapter(seed=42, clock=lambda: self.now).get_intraday_candles(
            {"symbol": "RELIANCE"}, interval_min=5, pattern="order_block_bull")[-60:]
        opening = self.now.replace(hour=9, minute=15, second=0)
        for index, bar in enumerate(bars):
            bar["timestamp"] = (opening + timedelta(minutes=5 * index)).isoformat()
        # A deliberately extreme unfinished candle must never determine a signal.
        bars.append(dict(timestamp=self.now.replace(second=0).isoformat(), open=9990,
                         high=10020, low=9980, close=10000, volume=999999))
        return bars

    @staticmethod
    def _wire_rows(bars, interval):
        rows = []
        for bar in bars:
            stamp = parse_ist_timestamp(bar["timestamp"])
            if interval == 5 or stamp.minute == 15 and stamp.hour == 14:
                rows.append([stamp.isoformat(), *(bar[key] for key in ("open", "high", "low", "close", "volume"))])
                continue
            # Expand the original 5m OHLCV to five 1m observations whose real
            # adapter aggregation exactly reconstructs the original fixture bar.
            for minute in range(5):
                prices = ([bar["open"]] * 4 if minute < 4 else
                          [bar[key] for key in ("open", "high", "low", "close")])
                rows.append([(stamp + timedelta(minutes=minute)).isoformat(), *prices, bar["volume"] / 5])
        return rows

    def _quote_payload(self, provider):
        stamp = (self.now - timedelta(seconds=1)).isoformat()
        if provider == "angelone":
            return dict(status=True, data=dict(fetched=[dict(exchange="NSE", symbolToken="2885",
                tradingSymbol="RELIANCE-EQ", ltp=2950, open=2940, high=2960, low=2930,
                close=2900, tradeVolume=10000, exchFeedTime=stamp)], unfetched=[]))
        return dict(status="success", data={"NSE_EQ:RELIANCE": dict(
            instrument_token="NSE_EQ|INE002A01018", symbol="RELIANCE", last_price=2950,
            ohlc=dict(open=2940, high=2960, low=2930, close=2900), volume=10000, timestamp=stamp)})

    def _open(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        provider = {"apiconnect.angelone.in": "angelone", "api.upstox.com": "upstox"}.get(url.hostname)
        path = url.path
        self.requests.append((provider, request.get_method(), path))
        expected = ((provider == "angelone" and request.get_method() == "POST" and
                     path in (self.ANGEL_LOGIN, self.ANGEL_QUOTE, self.ANGEL_CANDLES)) or
                    (provider == "upstox" and request.get_method() == "GET" and
                     (path == "/v2/market-quote/quotes" or
                      path == "/v3/historical-candle/intraday/NSE_EQ%7CINE002A01018/minutes/1")))
        if not expected:
            self.forbidden_requests.append((provider, request.get_method(), path))
            raise AssertionError("Only explicitly fixture-backed read endpoints are permitted")
        self.assertEqual(timeout, 8)
        if path == self.ANGEL_LOGIN:
            body = dict(status=True, data=dict(jwtToken="OFFLINE_JWT", refreshToken="OFFLINE_REFRESH",
                                              feedToken="OFFLINE_FEED"))
        elif path in (self.ANGEL_QUOTE, "/v2/market-quote/quotes"):
            body = self._quote_payload(provider)
        else:
            failure = self.failures.get(provider)
            if failure == "transport":
                raise urllib.error.URLError("OFFLINE SIMULATION transport unavailable")
            rows = self._wire_rows(self.batches[provider], 5 if provider == "angelone" else 1)
            body = (dict(status=True, data=rows) if provider == "angelone" else
                    dict(status="success", data=dict(candles=list(reversed(rows)))))
            if failure == "identity":
                body["symbol"] = "HDFCBANK"
        stream = io.BytesIO(json.dumps(body).encode("utf-8"))
        self.responses.append(stream)
        self.addCleanup(stream.close)
        return stream

    def _engine(self, provider, database="e2e.sqlite", **settings):
        self.failures.pop(provider, None)
        cfg = BotConfig(active_broker=provider, angel_api_key="OFFLINE_KEY",
            angel_client_code="OFFLINE_CLIENT", angel_pin="7531", angel_totp_secret="JBSWY3DPEHPK3PXP",
            angel_scrip_master_path="", angel_min_request_interval_seconds=0,
            upstox_api_key="OFFLINE_KEY", upstox_access_token="OFFLINE_TOKEN",
            telegram_bot_token="OFFLINE_TELEGRAM_TOKEN", telegram_chat_id="OFFLINE_CHAT",
            telegram_dry_run=True, enable_background_scheduler=False, enable_persistence=True,
            database_url=str(Path(self.temp.name) / database), **settings)
        cfg.fo_indices = {}
        cfg.equity_watchlist = [copy.deepcopy(next(m for m in cfg.equity_watchlist if m["symbol"] == "RELIANCE"))]
        self.batches[provider] = self._fixture()
        scanner = MultiBrokerScanner(cfg, clock=lambda: self.now)
        store = SQLitePersistenceStore(cfg.database_url)
        self.addCleanup(store.close)
        engine = IntradayBotEngine(cfg, clock=lambda: self.now, broker_scanner=scanner, store=store)
        self.addCleanup(engine.close)
        return engine

    def _scan(self, engine):
        # Wrapping observes genuine evaluator calls and boundary sizing; both
        # functions execute their original implementation without altered output.
        with patch("scanner_engine.evaluate_order_block_fvg", wraps=evaluate_order_block_fvg) as evaluator, \
             patch("scanner_engine.size_position", wraps=size_position) as sizing:
            result = engine.run_single_scan()
        return result, evaluator, sizing

    def _assert_candidate(self, engine, result, evaluator, sizing):
        provider = engine.config.active_broker
        self.assertEqual(result["scan_status"], "COMPLETED")
        self.assertEqual(result["total_signals"], 1)
        self.assertEqual(result["persisted_signals"], 1)
        self.assertEqual(result["persistence_status"], "OK")
        self.assertEqual(result["instrument_errors"], [])
        evaluator.assert_called_once()
        sizing.assert_called_once()
        signal = result["signals"][0]
        self.assertEqual((signal["symbol"], signal["strategy_id"], signal["timestamp"]),
                         ("RELIANCE", "strat_1_order_block", "2026-10-16 14:10:00"))
        self.assertEqual(signal["entry_price"], 2955.74)
        self.assertLess(signal["stop_loss"], signal["invalidation_level"])
        self.assertLess(signal["invalidation_level"], signal["entry_price"])
        self.assertLess(signal["entry_price"], signal["target_1"])
        self.assertEqual((signal["provider"], signal["state_context"], signal["data_mode"]),
                         (provider, "SCANNER", "LIVE"))
        identity = signal["instrument_identity"]
        self.assertEqual((identity["provider"], identity["symbol"], identity["historical_validity"]),
                         (provider, "RELIANCE", "NOT_ESTABLISHED"))
        self.assertEqual(identity["identifier"], "2885" if provider == "angelone" else "NSE_EQ|INE002A01018")
        decision = size_position(signal["entry_price"], signal["stop_loss"],
            engine.config.account_capital_inr, engine.config.max_risk_per_trade_pct, "LONG", instrument_type="EQ", lot_size=1)
        self.assertTrue(decision["eligible"])
        for field, key in (("position_qty", "quantity"), ("capital_risk_inr", "estimated_risk_inr"),
                           ("est_charges_inr", "estimated_charges_inr")):
            self.assertEqual(signal[field], decision[key])
        self.assertLessEqual(decision["estimated_risk_inr"], decision["risk_budget_inr"])
        self.assertLessEqual(decision["capital_required_inr"], decision["available_capital_inr"])
        self.assertTrue(result["candle_freshness"]["live_signal_allowed"])
        report = result["candle_freshness"]["instruments"]["RELIANCE"]
        self.assertEqual(report["latest_completed_timestamp_ist"], signal["timestamp"])
        persisted = engine.store.query_signals(provider=provider, data_mode="LIVE", state_context="SCANNER")
        self.assertEqual(persisted["total_count"], 1)
        self.assertEqual(persisted["items"][0]["instrument_identity"], identity)
        self.assertEqual(engine.store.query_signals(data_mode="SIMULATED")["total_count"], 0)
        dispatch = result["telegram_dispatches"][0]
        self.assertTrue(dispatch["ok"])
        self.assertTrue(dispatch["dry_run"])
        self.assertIn("RELIANCE", dispatch["message_html"])
        self.assertIn("14:10:00", dispatch["message_html"])
        self.assertNotIn("10000.00", dispatch["message_html"])
        self.assertEqual(engine.store.load_live_acceptance_evidence(provider, "RELIANCE"), None)

    def test_both_wire_adapters_produce_real_candidate_risk_persistence_and_dry_run(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite")
                quote = engine.broker.fetch_quote(engine.config.equity_watchlist[0])
                self.assertEqual(quote["instrument_identity"]["provider"], provider)
                self.assertEqual(quote["quote_timestamp_ist"], "2026-10-16 14:15:04")
                result, evaluator, sizing = self._scan(engine)
                self._assert_candidate(engine, result, evaluator, sizing)
                self.assertTrue(engine.broker.get_active_adapter().is_connection_verified())

    def test_same_scope_dedup_and_restart_preserve_real_mitigated_zone(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite")
                result, _, _ = self._scan(engine)
                self.assertEqual(result["persisted_signals"], 1)
                signal = TradeSignal(**result["signals"][0])
                inserted, _ = engine.store.save_signal(signal, broker=engine.broker.get_active_adapter().name,
                    now_ist=self.now)
                self.assertFalse(inserted)
                zones = engine.mitigated_order_blocks
                self.assertTrue(zones)
                second, _, _ = self._scan(engine)
                self.assertEqual(second["total_signals"], 0)
                self.assertEqual(second["telegram_dispatches"], [])
                engine.close()
                restarted = self._engine(provider, database=provider + ".sqlite")
                self.assertEqual(restarted.mitigated_order_blocks, zones)
                third, _, _ = self._scan(restarted)
                self.assertEqual(third["total_signals"], 0)
                self.assertEqual(restarted.store.query_signals(provider=provider)["total_count"], 1)

    def test_provider_scopes_never_suppress_each_others_actual_candidates(self):
        for provider in self.PROVIDERS:
            engine = self._engine(provider)
            result, evaluator, sizing = self._scan(engine)
            self._assert_candidate(engine, result, evaluator, sizing)
        rows = engine.store.query_signals()["items"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["provider"] for row in rows}, set(self.PROVIDERS))
        self.assertEqual(len({row["dedup_key"] for row in rows}), 2)

    def test_real_risk_budget_rejects_fixture_without_consuming_its_zone(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite",
                    account_capital_inr=1, max_risk_per_trade_pct=.001)
                decisions = []
                def observe(*args, **kwargs):
                    decision = size_position(*args, **kwargs)
                    decisions.append(decision)
                    return decision
                with patch("strategies.size_position", wraps=observe):
                    result, evaluator, sizing = self._scan(engine)
                evaluator.assert_called_once()
                sizing.assert_not_called()
                self.assertTrue(any(not d["eligible"] for d in decisions))
                self.assertEqual(result["total_signals"], 0)
                self.assertEqual(result["telegram_dispatches"], [])
                self.assertEqual(engine.store.query_signals()["total_count"], 0)
                self.assertFalse(engine.mitigated_order_blocks)

    def test_price_invalidation_rejects_setup_without_fabricating_an_alternate_signal(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite")
                completed = self.batches[provider][-2]
                completed.update(open=2935, high=2937, low=2925, close=2930)
                result, evaluator, sizing = self._scan(engine)
                evaluator.assert_called_once()
                sizing.assert_not_called()
                self.assertEqual(result["total_signals"], 0)
                self.assertEqual(result["telegram_dispatches"], [])
                self.assertEqual(engine.store.query_signals()["total_count"], 0)

    def test_transport_failure_after_candidate_never_reuses_success_summary_or_dispatch(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite")
                first, _, _ = self._scan(engine)
                self.assertEqual(first["persisted_signals"], 1)
                self.failures[provider] = "transport"
                sent_before = set(engine.telegram.sent_cache)
                with patch("scanner_engine.evaluate_order_block_fvg", wraps=evaluate_order_block_fvg) as evaluator:
                    with self.assertRaises(BrokerDataError):
                        engine.run_single_scan()
                evaluator.assert_not_called()
                self.assertEqual(engine.telegram.sent_cache, sent_before)
                self.assertEqual(engine.store.query_signals()["total_count"], 1)
                self.assertEqual(engine.store.query_scan_runs(status="FAILED")["total_count"], 1)
                self.assertFalse(engine.get_broker_status()["live_signals_allowed"])
                self.assertEqual(engine.last_scan_summary["scan_status"], "FAILED")
                self.assertEqual(engine.last_scan_summary["signals"], [])

    def test_invalid_ohlcv_identity_or_stale_second_batch_never_reuses_prior_candidate(self):
        for failure in ("ohlcv", "identity", "stale"):
            for provider in self.PROVIDERS:
                with self.subTest(provider=provider, failure=failure):
                    engine = self._engine(provider, database=provider + failure + ".sqlite")
                    first, _, _ = self._scan(engine)
                    self.assertEqual(first["persisted_signals"], 1)
                    if failure == "identity":
                        self.failures[provider] = failure
                    elif failure == "ohlcv":
                        self.batches[provider][-2]["high"] = 1
                    else:
                        self.batches[provider] = self.batches[provider][:-4]
                    with patch("scanner_engine.evaluate_order_block_fvg", wraps=evaluate_order_block_fvg) as evaluator:
                        with self.assertRaises(BrokerDataError):
                            engine.run_single_scan()
                    evaluator.assert_not_called()
                    self.assertEqual(engine.store.query_signals()["total_count"], 1)
                    self.assertEqual(engine.store.query_scan_runs(status="FAILED")["total_count"], 1)
                    self.assertFalse(engine.get_broker_status()["live_signals_allowed"])
                    self.assertEqual(engine.last_scan_summary["scan_status"], "FAILED")
                    self.assertEqual(engine.last_scan_summary["telegram_dispatches"], [])

    def test_independent_broker_failure_revokes_signal_status_despite_fresh_scan_evidence(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite")
                result, _, _ = self._scan(engine)
                self.assertEqual(result["persisted_signals"], 1)
                self.assertTrue(engine.get_broker_status()["live_signals_allowed"])
                with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("OFFLINE unavailable")):
                    with self.assertRaises(BrokerDataError):
                        engine.broker.fetch_quote(engine.config.equity_watchlist[0])
                status = engine.get_broker_status()
                self.assertEqual(status["connection_state"], "ERROR")
                self.assertTrue(status["candle_freshness"]["live_signal_allowed"])
                self.assertFalse(status["live_signals_allowed"])
                self.assertEqual(engine.store.query_signals()["total_count"], 1)

    def test_offline_candidate_never_grants_historical_acceptance_or_strategy3_execution(self):
        from backtest_engine import BacktestReadinessError, DeterministicBacktestEngine
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                engine = self._engine(provider, database=provider + ".sqlite")
                result, _, _ = self._scan(engine)
                self.assertEqual(result["persisted_signals"], 1)
                for strategy in ("strat_1_order_block", "strat_3_option_apex_oi"):
                    gate = execution_gate(engine.config, engine.store, provider, "RELIANCE", strategy,
                                          data_mode="LIVE", now=self.now)
                    self.assertFalse(gate["allowed"])
                historical = DeterministicBacktestEngine(engine.config, engine.store,
                    broker_status=engine.get_broker_status(), clock=lambda: self.now)
                with self.assertRaises(BacktestReadinessError) as rejected:
                    historical.run_backtest("strat_1_order_block", "RELIANCE", provider=provider,
                        data_mode="LIVE", persist_run=False)
                self.assertEqual(rejected.exception.details["reason_code"],
                                 "BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED")
                self.assertEqual(engine.store.check_health()["backtest_runs_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
