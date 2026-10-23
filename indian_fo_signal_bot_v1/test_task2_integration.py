"""Cross-track guardrails; offline bootstrap never consumes operator secrets."""
import copy
import json
import unittest
from datetime import datetime
from unittest.mock import patch

import test_bot
from brokers import BrokerDataError, DhanHQAdapter
from config import BotConfig, ConfigValidationError
from dhan_feed import FeedError
from dhan_feed_control import preflight, smoke
from scanner_engine import IntradayBotEngine
from strategies import IST


class UnavailableFeed:
    def stop(self):
        self.stopped = True

    def status(self):
        return dict(provider="dhan", status="STALE", live_signal_allowed=False)

    def get_candles(self, *args, **kwargs):
        raise FeedError("STALE")


class TestTask2Integration(unittest.TestCase):
    def config(self, **changes):
        return BotConfig(**dict(dict(active_broker="paper_sim", database_url=":memory:",
            telegram_dry_run=True, enable_background_scheduler=False,
            dhan_client_id="OFFLINE_CLIENT", dhan_access_token="OFFLINE_TOKEN"), **changes))

    def test_bounded_explicit_config_and_preflight_preserve_paper_selection(self):
        cfg = self.config()
        cfg.dhan_feed_instruments = [copy.deepcopy(cfg.equity_watchlist[0])]
        with patch("socket.socket.connect", side_effect=AssertionError("No connection in preflight")):
            result = preflight(cfg)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(cfg.active_broker, "paper_sim")
        self.assertFalse(result["live_requests"])
        self.assertFalse(result["live_feed_accepted"])
        self.assertNotIn("OFFLINE_TOKEN", json.dumps(result))
        cfg.dhan_feed_instruments *= 2
        with self.assertRaises(ConfigValidationError):
            cfg.validate()

    def test_empty_scope_bad_mapping_and_missing_dhan_credentials_block_without_fallback(self):
        cfg = self.config(dhan_client_id="", dhan_access_token="", upstox_access_token="OFFLINE_OTHER")
        with patch("dhan_feed.DhanLiveFeed", side_effect=AssertionError("Must not construct feed")):
            report = smoke(cfg)
        self.assertFalse(report["live_requests"])
        self.assertIn("DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER", report["blockers"])
        self.assertIn("EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED", report["blockers"])
        cfg.dhan_feed_instruments = [dict(cfg.equity_watchlist[0], dhan_id="999")]
        self.assertEqual(preflight(cfg)["blockers"], ["CONFIGURATION_INVALID"])

    def test_smoke_rejects_scope_expansion_unsafe_flags_and_invalid_duration(self):
        cfg = self.config()
        cfg.dhan_feed_instruments = copy.deepcopy(cfg.equity_watchlist[:2])
        with patch("dhan_feed.DhanLiveFeed", side_effect=AssertionError("No transport")):
            self.assertIn("SMOKE_REQUIRES_EXACTLY_ONE_INSTRUMENT", smoke(cfg)["blockers"])
            self.assertFalse(smoke(cfg, 31)["live_requests"])
            cfg.telegram_dry_run = False
            self.assertIn("SAFE_RUNTIME_FLAGS_REQUIRED", preflight(cfg)["blockers"])

    def test_explicit_stream_failure_never_uses_rest_or_simulation(self):
        cfg = self.config(active_broker="dhan")
        adapter = DhanHQAdapter(cfg)
        adapter.attach_live_feed(UnavailableFeed())
        with patch("urllib.request.urlopen", side_effect=AssertionError("No REST fallback")):
            with self.assertRaisesRegex(BrokerDataError, "STALE"):
                adapter.get_intraday_candles(cfg.equity_watchlist[0])
        self.assertFalse(adapter.is_simulated)
        self.assertEqual(adapter.get_feed_status()["status"], "STALE")

    def test_stream_health_overrides_old_verified_connection_and_blocks_signals(self):
        cfg = self.config(active_broker="dhan")
        engine = IntradayBotEngine(cfg, clock=lambda: datetime(2026, 10, 22, 10, 30, tzinfo=IST))
        self.addCleanup(engine.close)
        engine.last_broker_verified_at = "2026-10-22T10:29:00+05:30"
        engine.broker.adapters["dhan"].attach_live_feed(UnavailableFeed())
        with patch("urllib.request.urlopen", side_effect=AssertionError("Status is read-only")):
            result = engine.get_broker_status()
        self.assertEqual(result["connection_state"], "STREAM_UNAVAILABLE")
        self.assertFalse(result["connectivity_verified"])
        self.assertFalse(result["live_signals_allowed"])
        self.assertEqual(result["stream"]["status"], "STALE")

    def test_explicit_shutdown_closes_stream_before_sqlite_store(self):
        engine = IntradayBotEngine(self.config())
        self.addCleanup(engine.close)
        feed = UnavailableFeed()
        engine.broker.adapters["dhan"].attach_live_feed(feed)
        engine.close()
        self.assertTrue(feed.stopped)
        self.assertIsNone(engine.broker.adapters["dhan"].live_feed)


if __name__ == "__main__":
    unittest.main()
