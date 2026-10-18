"""Phase 4 provider comparisons using synthetic wire responses, never live evidence.

Only urllib transport is replaced. Existing adapters, identity validation, clock,
completion/freshness checks and narrow diagnostics run unchanged in these tests.
"""

import io
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- existing offline environment bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from brokers import AngelOneSmartAPIAdapter, BrokerDataError, UpstoxV2Adapter
from config import BotConfig
from diagnostics import run_angelone_market_data_diagnostics
from instrument_identity import INDICES, IdentityValidationError, option_contract, spot_identity
from strategies import IST, filter_completed_candles
from upstox_diagnostics import run_upstox_diagnostics


class TestPhase4BrokerAcceptance(unittest.TestCase):
    PROVIDERS = ("angelone", "upstox")

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 36, 5, tzinfo=IST)
        self.responses = []
        self.requests = []
        self.streams = []
        transport = patch("urllib.request.urlopen", side_effect=self._open)
        transport.start()
        self.addCleanup(transport.stop)

    def _open(self, request, timeout):
        self.requests.append(request)
        self.assertGreater(timeout, 0)
        if not self.responses:
            raise AssertionError("Unexpected transport request in offline fixture")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        stream = io.BytesIO(response if isinstance(response, bytes) else json.dumps(response).encode())
        self.streams.append(stream)
        return stream

    def _adapter(self, provider):
        cfg = BotConfig(active_broker=provider, upstox_api_key="OFFLINE_PHASE4_KEY",
            upstox_access_token="OFFLINE_PHASE4_TOKEN", angel_api_key="OFFLINE_PHASE4_KEY",
            angel_client_code="OFFLINE_PHASE4_CLIENT", angel_pin="7531",
            angel_totp_secret="JBSWY3DPEHPK3PXP", angel_scrip_master_path="",
            angel_min_request_interval_seconds=0.0, enable_persistence=False,
            database_url=":memory:", telegram_dry_run=True, enable_background_scheduler=False)
        cls = AngelOneSmartAPIAdapter if provider == "angelone" else UpstoxV2Adapter
        adapter = cls(cfg, clock=lambda: self.now)
        if provider == "angelone":
            # A seeded fixture session avoids authentication/account endpoints.
            adapter.jwt_token = "OFFLINE_PHASE4_JWT"
            adapter.authenticated_at_ist = "2026-10-16 10:35:00"
        return adapter

    def _quote(self, provider, timestamp="CURRENT", **changes):
        timestamp = self.now - timedelta(seconds=1) if timestamp == "CURRENT" else timestamp
        if provider == "angelone":
            item = dict(exchange="NSE", symbolToken="2885", tradingSymbol="RELIANCE-EQ",
                ltp=2950, open=2940, high=2960, low=2930, close=2900, tradeVolume=10000)
            if timestamp is not None:
                item["exchFeedTime"] = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
            item.update(changes)
            return dict(status=True, data=dict(fetched=[item], unfetched=[]))
        item = dict(instrument_token="NSE_EQ|INE002A01018", symbol="RELIANCE", last_price=2950,
                    ohlc=dict(open=2940, high=2960, low=2930, close=2900), volume=10000)
        if timestamp is not None:
            item["timestamp"] = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
        item.update(changes)
        return dict(status="success", data={"NSE_EQ:RELIANCE": item})

    def _candles(self, provider, only_forming=False):
        start = self.now.replace(minute=35 if only_forming else 25, second=0)
        count, interval = ((1, 5) if only_forming else (3, 5)) if provider == "angelone" else (
            (1, 1) if only_forming else (12, 1))
        if only_forming and provider == "upstox":
            start = self.now.replace(second=0)
        rows = [[(start + timedelta(minutes=interval*i)).isoformat(), 100, 102, 99, 101, 100]
                for i in range(count)]
        return (dict(status=True, data=rows) if provider == "angelone" else
                dict(status="success", data=dict(candles=list(reversed(rows)))))

    def _run(self, provider, adapter):
        function = run_angelone_market_data_diagnostics if provider == "angelone" else run_upstox_diagnostics
        return function(adapter.config, adapter, symbol="RELIANCE", clock=lambda: self.now)

    def _reset_wire(self, *responses):
        self.responses = list(responses)
        self.requests.clear()

    def _http_error(self, provider, status):
        body = (dict(status=False, errorcode="AB2001", message="Denied") if provider == "angelone" else
                dict(status="error", errors=[dict(error_code="UDAPI1000", message="Denied")]))
        stream = io.BytesIO(json.dumps(body).encode())
        error = urllib.error.HTTPError("https://offline.invalid/?private=URL_CANARY", status,
                                      "REASON_CANARY", {"Authorization": "HEADER_CANARY"}, stream)
        self.addCleanup(error.close)
        return error, stream

    def test_success_uses_only_cash_quote_and_candles_and_preserves_separate_gates(self):
        forbidden = ("brokers.AngelOneSmartAPIAdapter.get_profile", "diagnostics.SQLitePersistenceStore",
                     "scanner_engine.IntradayBotEngine.run_single_scan", "scanner_engine.MarketScanScheduler.start",
                     "telegram_bot.TelegramSignalDispatcher.send_signal", "readiness_policy._record_completed_diagnostic")
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider), ExitStack() as stack:
                guards = [stack.enter_context(patch(target, side_effect=AssertionError("Forbidden acceptance side effect")))
                          for target in forbidden]
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider), self._candles(provider))
                report = self._run(provider, adapter)
                self.assertEqual((report["overall_status"], report["exit_code"]), ("PASS", 0), report)
                self.assertEqual(len(self.requests), 2)
                paths = [urllib.parse.urlsplit(request.full_url).path for request in self.requests]
                self.assertEqual(paths, (["/rest/secure/angelbroking/market/v1/quote/",
                    "/rest/secure/angelbroking/historical/v1/getCandleData"] if provider == "angelone" else
                    ["/v2/market-quote/quotes", "/v2/historical-candle/intraday/NSE_EQ%7CINE002A01018/1minute"]))
                self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
                self.assertEqual(report["authentication_scope"], "AUTHORIZED_MARKET_DATA_READ_ONLY_NO_PROFILE_CHECK")
                self.assertEqual(len(report["checks"]["candles"]["completed_sample"]), 2)
                self.assertEqual(report["checks"]["candles"]["incomplete_bars_excluded"], 1)
                for flag in ("data_persisted", "readiness_receipt_issued", "historical_replay_allowed"):
                    self.assertFalse(report[flag])
                for guard in guards:
                    guard.assert_not_called()
                self.assertTrue(all(stream.closed for stream in self.streams))

    def test_missing_quote_observation_stops_before_candles_without_clock_substitution(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider, timestamp=None))
                report = self._run(provider, adapter)
                self.assertEqual(report["checks"]["quote"]["status"], "BLOCKED")
                self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
                self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
                self.assertEqual(report["exit_code"], 1)
                self.assertEqual(len(self.requests), 1)
                self.assertNotIn("quote_timestamp_ist", report["checks"]["quote"])

    def test_stale_and_previous_day_quotes_stop_before_additional_market_requests(self):
        for provider in self.PROVIDERS:
            for timestamp in (self.now-timedelta(seconds=61), self.now-timedelta(days=1)):
                with self.subTest(provider=provider, timestamp=timestamp):
                    adapter = self._adapter(provider)
                    self._reset_wire(self._quote(provider, timestamp=timestamp))
                    report = self._run(provider, adapter)
                    self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
                    self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
                    self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
                    self.assertEqual(len(self.requests), 1)

    def test_malformed_naive_boolean_and_future_quote_observations_are_not_accepted(self):
        for provider in self.PROVIDERS:
            for timestamp in ("invalid", "2026-10-16 10:36:04", True, self.now+timedelta(seconds=6)):
                with self.subTest(provider=provider, timestamp=timestamp):
                    adapter = self._adapter(provider)
                    self._reset_wire(self._quote(provider, timestamp=timestamp))
                    report = self._run(provider, adapter)
                    self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
                    self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
                    self.assertFalse(adapter.is_connection_verified())
                    self.assertEqual(len(self.requests), 1)

    def test_quote_identity_failure_cannot_request_candles_or_fall_back_to_other_provider(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                changes = {"symbolToken": "1333"} if provider == "angelone" else {"instrument_token": "NSE_EQ|WRONG"}
                self._reset_wire(self._quote(provider, **changes))
                report = self._run(provider, adapter)
                self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
                self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
                self.assertEqual(adapter.config.active_broker, provider)
                self.assertEqual(len(self.requests), 1)

    def test_explicit_nonlive_wire_provenance_is_never_relabelled_live(self):
        for provider in self.PROVIDERS:
            for changes in (dict(data_mode="SIMULATED"), dict(data_mode="UNKNOWN"), dict(is_simulated=True)):
                for kind in ("quote", "candles"):
                    locations = ("envelope", "item") if kind == "quote" else ("envelope",)
                    if ((provider == "angelone" and kind == "quote") or
                            (provider == "upstox" and kind == "candles")):
                        locations += ("data",)
                    for location in locations:
                        with self.subTest(provider=provider, kind=kind, location=location, changes=changes):
                            adapter = self._adapter(provider)
                            response = self._quote(provider) if kind == "quote" else self._candles(provider)
                            if location == "envelope":
                                target = response
                            elif location == "data":
                                target = response["data"]
                            elif provider == "angelone":
                                target = response["data"]["fetched"][0]
                            else:
                                target = next(iter(response["data"].values()))
                            target.update(changes)
                            self._reset_wire(response)
                            meta = next(m for m in adapter.config.equity_watchlist if m["symbol"] == "RELIANCE")
                            with self.assertRaises(BrokerDataError):
                                if kind == "quote":
                                    adapter.get_quote(meta)
                                else:
                                    adapter.get_intraday_candles(meta, interval_min=5)
                            self.assertFalse(adapter.is_connection_verified())
                            self.assertEqual(len(self.requests), 1)

    def test_only_forming_current_bucket_cannot_establish_readiness(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider), self._candles(provider, only_forming=True))
                report = self._run(provider, adapter)
                self.assertEqual(report["checks"]["quote"]["status"], "PASS")
                self.assertEqual(report["checks"]["candles"]["status"], "FAIL")
                self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
                self.assertEqual(report["exit_code"], 1)
                self.assertFalse(adapter.is_connection_verified())
                self.assertFalse(report["readiness_receipt_issued"])

    def test_successful_quote_does_not_authorize_later_failed_candle_response(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider), urllib.error.URLError("OFFLINE_NETWORK_CANARY"))
                report = self._run(provider, adapter)
                self.assertEqual(report["checks"]["quote"]["status"], "PASS")
                self.assertEqual(report["checks"]["candles"]["status"], "FAIL")
                self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
                self.assertEqual(adapter._authorized_reads, 1)
                self.assertFalse(adapter.is_connection_verified())
                self.assertNotIn("OFFLINE_NETWORK_CANARY", json.dumps(report))

    def test_failed_quote_after_valid_data_invalidates_connection_without_reusing_data(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider))
                adapter.get_quote("RELIANCE")
                self.assertTrue(adapter.is_connection_verified())
                before = adapter._authorized_reads
                self._reset_wire(TimeoutError("OFFLINE_TIMEOUT_CANARY"))
                with self.assertRaises(BrokerDataError) as caught:
                    adapter.get_quote("RELIANCE")
                self.assertEqual(adapter._authorized_reads, before)
                self.assertFalse(adapter.is_connection_verified())
                self.assertNotEqual(adapter.last_error_category, "NONE")
                self.assertNotIn("OFFLINE_TIMEOUT_CANARY", str(caught.exception))
                self.assertEqual(len(self.requests), 1)

    def test_schema_failure_after_previous_success_cannot_retain_connection(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._quote(provider))
                adapter.get_quote("RELIANCE")
                changes = {"ltp": -1} if provider == "angelone" else {"last_price": -1}
                self._reset_wire(self._quote(provider, **changes))
                with self.assertRaises(BrokerDataError):
                    adapter.get_quote("RELIANCE")
                # HTTP/envelope authorization succeeds; quote validity is separate.
                self.assertEqual(adapter._authorized_reads, 2)
                self.assertFalse(adapter.is_connection_verified())
                self.assertNotEqual(adapter.last_error_category, "NONE")

    def test_valid_new_response_after_failure_restores_only_current_market_data_proof(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(TimeoutError("offline"))
                with self.assertRaises(BrokerDataError):
                    adapter.get_quote("RELIANCE")
                self._reset_wire(self._quote(provider))
                quote = adapter.get_quote("RELIANCE")
                self.assertTrue(adapter.is_connection_verified())
                self.assertEqual(adapter._authorized_reads, 1)
                self.assertEqual(adapter.last_error_category, "NONE")
                self.assertEqual(quote["instrument_identity"]["historical_validity"], "NOT_ESTABLISHED")
                self.assertFalse(hasattr(adapter, "historical_replay_allowed"))

    def test_http_failures_close_resources_and_never_increment_authorized_read_count(self):
        expected = {"angelone": {401: "SESSION_EXPIRED", 403: "RATE_LIMIT", 429: "RATE_LIMIT"},
                    "upstox": {401: "AUTH_FAILURE", 403: "FORBIDDEN", 429: "RATE_LIMIT"}}
        for provider in self.PROVIDERS:
            for status in (400, 401, 403, 404, 429, 500, 599):
                with self.subTest(provider=provider, status=status):
                    adapter = self._adapter(provider)
                    self._reset_wire(self._quote(provider))
                    adapter.get_quote("RELIANCE")
                    error, stream = self._http_error(provider, status)
                    self._reset_wire(error)
                    with self.assertRaises(BrokerDataError) as caught:
                        if provider == "angelone":
                            adapter._request_json("POST", "/rest/secure/angelbroking/market/v1/quote/",
                                                  payload={}, allow_reauth_retry=False)
                        else:
                            adapter._request_json("/market-quote/quotes")
                    self.assertEqual(adapter._authorized_reads, 1)
                    self.assertTrue(stream.closed)
                    self.assertFalse(adapter.is_connection_verified())
                    fallback = "NETWORK_API_FAILURE" if provider == "angelone" else "HTTP_ERROR"
                    self.assertEqual(adapter.last_error_category, expected[provider].get(status, fallback))
                    if status in (401, 403):
                        self.assertIsNone(adapter.authenticated_at_ist)
                    for canary in ("URL_CANARY", "REASON_CANARY", "HEADER_CANARY"):
                        self.assertNotIn(canary, str(caught.exception))

    def test_forming_candle_metadata_does_not_promote_it_to_completed(self):
        for provider in self.PROVIDERS:
            with self.subTest(provider=provider):
                adapter = self._adapter(provider)
                self._reset_wire(self._candles(provider))
                meta = next(m for m in adapter.config.equity_watchlist if m["symbol"] == "RELIANCE")
                candles = adapter.get_intraday_candles(meta, interval_min=5)
                self.assertFalse(candles[-1]["is_complete"])
                completed = filter_completed_candles(candles, interval_min=5, now=self.now)
                self.assertEqual([bar["timestamp"] for bar in completed],
                                 ["2026-10-16 10:25:00", "2026-10-16 10:30:00"])
                for candle in candles:
                    identity = candle["instrument_identity"]
                    self.assertEqual((identity["provider"], identity["symbol"], identity["exchange"]),
                                     (provider, "RELIANCE", "NSE"))
                    self.assertEqual(identity["historical_validity"], "NOT_ESTABLISHED")
                    self.assertEqual(candle["timestamp_timezone"], "Asia/Kolkata")

    def test_upstox_intraday_allowlist_rejects_malformed_and_traversal_routes_before_transport(self):
        adapter = self._adapter("upstox")
        invalid_paths = ("/historical-candle/intraday/../../order/place",
            "/historical-candle/intraday/NSE_EQ%7CINE002A01018/1minute?private=CANARY",
            "/historical-candle/intraday/NSE_EQ%7CINE002A01018/1minute#fragment",
            "/historical-candle/intraday/NSE_EQ%7CINE002A01018/1minute/extra",
            "/historical-candle/intraday/%2e%2e%2forder/1minute",
            "/historical-candle/intraday/NSE_EQ%7CINE002A01018/5minute")
        for path in invalid_paths:
            with self.subTest(path=path), self.assertRaises(BrokerDataError):
                adapter._request_json(path)
        self.assertEqual(self.requests, [])

    def test_both_index_spot_quote_mappings_are_checked_separately_from_cash_and_contracts(self):
        for provider in self.PROVIDERS:
            for symbol in ("NIFTY", "BANKNIFTY"):
                with self.subTest(provider=provider, symbol=symbol):
                    adapter = self._adapter(provider)
                    mapping = INDICES[symbol]
                    if provider == "angelone":
                        response = self._quote(provider, symbolToken=mapping["angel_token"],
                                               tradingSymbol=mapping["name"])
                    else:
                        response = self._quote(provider, instrument_token=mapping["upstox_key"], symbol=symbol)
                        response["data"] = {mapping["upstox_key"]: next(iter(response["data"].values()))}
                    self._reset_wire(response)
                    quote = adapter.get_quote(symbol)
                    identity = quote["instrument_identity"]
                    self.assertEqual((identity["provider"], identity["symbol"], identity["instrument_type"]),
                                     (provider, symbol, "INDEX_SPOT"))
                    field = "angel_token" if provider == "angelone" else "upstox_key"
                    self.assertEqual(identity["identifier"], mapping[field])
                    self.assertEqual(identity["historical_validity"], "NOT_ESTABLISHED")
                    self.assertEqual(len(self.requests), 1)


class TestPhase4InstrumentScope(unittest.TestCase):
    def test_index_spot_identity_never_implies_executable_futures_or_options(self):
        for provider in ("angelone", "upstox"):
            for symbol in ("NIFTY", "BANKNIFTY"):
                with self.subTest(provider=provider, symbol=symbol):
                    meta = dict(INDICES[symbol], symbol=symbol)
                    identity = spot_identity(meta, provider)
                    self.assertEqual(identity["instrument_type"], "INDEX_SPOT")
                    self.assertEqual(identity["historical_validity"], "NOT_ESTABLISHED")
                    for contract_type in ("FUTIDX", "OPTIDX", "FUTSTK", "OPTSTK"):
                        with self.assertRaises(IdentityValidationError):
                            spot_identity(dict(meta, instrument_type=contract_type), provider)

    def test_cash_instrument_cannot_be_relabelled_as_stock_fo_or_lot_sized(self):
        from instrument_identity import EQUITIES
        for provider in ("angelone", "upstox"):
            for changes in (dict(instrument_type="FUTSTK"), dict(instrument_type="OPTSTK"),
                            dict(exchange="NFO"), dict(lot_size=250)):
                with self.subTest(provider=provider, changes=changes), self.assertRaises(IdentityValidationError):
                    spot_identity(dict(EQUITIES["RELIANCE"], **changes), provider)

    def test_missing_option_lot_expiry_strike_and_source_are_not_inferred(self):
        valid = dict(underlying="NIFTY", expiry="2026-10-20", strike=25000, option_type="CE",
            provider="angelone", exchange="NFO", instrument_type="OPTIDX", identifier="60001",
            source="LOADED_ANGEL_MASTER", source_revision="OFFLINE_FIXTURE_REVISION", lot_size=75, multiplier=1)
        self.assertEqual(option_contract(valid, "NIFTY", "2026-10-20", 25000, "CE", "angelone", "2026-10-16")["lot_size"], 75)
        for field in ("expiry", "strike", "option_type", "identifier", "source", "source_revision", "lot_size", "multiplier"):
            record = dict(valid)
            del record[field]
            with self.subTest(field=field), self.assertRaises(IdentityValidationError):
                option_contract(record, "NIFTY", "2026-10-20", 25000, "CE", "angelone", "2026-10-16")
        for provider in ("upstox", "dhan"):
            with self.subTest(provider=provider), self.assertRaises(IdentityValidationError):
                option_contract(dict(valid, provider=provider), "NIFTY", "2026-10-20", 25000, "CE", provider, "2026-10-16")

    def test_option_contract_rejects_nonfinite_and_nonpositive_matching_strikes(self):
        record = dict(underlying="NIFTY", expiry="2026-10-20", option_type="CE", provider="angelone",
            exchange="NFO", instrument_type="OPTIDX", identifier="60001", source="LOADED_ANGEL_MASTER",
            source_revision="OFFLINE_FIXTURE_REVISION", lot_size=75, multiplier=1)
        for strike in (float("inf"), float("-inf"), float("nan"), True, 0, -1):
            with self.subTest(strike=strike), self.assertRaises(IdentityValidationError):
                option_contract(dict(record, strike=strike), "NIFTY", "2026-10-20", strike,
                                "CE", "angelone", "2026-10-16")


if __name__ == "__main__":
    unittest.main(verbosity=2)
