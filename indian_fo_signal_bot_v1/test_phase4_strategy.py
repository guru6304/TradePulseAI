"""Offline mandatory-opening-range regressions using explicitly synthetic bars."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- reuse the existing offline configuration bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from brokers import SimulatedNSEAdapter, assess_live_candle_batch
from strategies import IST, evaluate_orb_breakout, parse_ist_timestamp


class TestPhase4StrategyRequiredData(unittest.TestCase):
    """General freshness cannot substitute for the actual 09:15 opening bars."""

    CASES = (
        ("ICICIBANK", "orb_breakout_bull", "BULLISH (BUY)"),
        ("AXISBANK", "orb_breakout_bear", "BEARISH (SELL)"),
    )

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        transport = patch("urllib.request.urlopen", side_effect=AssertionError("External transport forbidden"))
        transport.start()
        self.addCleanup(transport.stop)

    def _bars(self, symbol, pattern):
        return SimulatedNSEAdapter(seed=42, clock=lambda: self.now).get_intraday_candles(
            {"symbol": symbol}, interval_min=5, pattern=pattern)

    def test_full_opening_range_preserves_bullish_and_bearish_controls(self):
        for symbol, pattern, direction in self.CASES:
            with self.subTest(symbol=symbol):
                bars = self._bars(symbol, pattern)
                signal = evaluate_orb_breakout(symbol, bars, now=self.now)
                self.assertIsNotNone(signal)
                self.assertEqual(signal.direction, direction)
                self.assertEqual(signal.timestamp, bars[-1]["timestamp"])
                self.assertTrue(all(bar["is_simulated"] for bar in bars))

    def test_fresh_later_session_window_cannot_become_the_opening_range(self):
        for symbol, pattern, _ in self.CASES:
            with self.subTest(symbol=symbol):
                shifted = []
                for bar in self._bars(symbol, pattern):
                    stamp = parse_ist_timestamp(bar["timestamp"])
                    if stamp.date() == self.now.date():
                        stamp += timedelta(minutes=45)
                    # Exercise the real LIVE candle policy with synthetic input;
                    # this is a mocked validation path, never provider evidence.
                    shifted.append(dict(bar, timestamp=stamp.isoformat(), data_mode="LIVE", is_simulated=False))
                reference = self.now + timedelta(minutes=45)
                normalized, report = assess_live_candle_batch(
                    shifted, interval_min=5, now_ist=reference, provider="upstox",
                    symbol=symbol, context="SCANNER")
                self.assertEqual(report["status"], "FRESH_IN_SESSION")
                self.assertTrue(report["live_signal_allowed"])
                current = [bar for bar in normalized
                           if parse_ist_timestamp(bar["timestamp"]).date() == self.now.date()]
                self.assertEqual(parse_ist_timestamp(current[0]["timestamp"]).strftime("%H:%M"), "10:00")
                self.assertIsNone(evaluate_orb_breakout(symbol, normalized, now=reference))

    def test_each_missing_opening_bar_blocks_despite_sufficient_warmup(self):
        for symbol, pattern, _ in self.CASES:
            bars = self._bars(symbol, pattern)
            for missing in ("09:15", "09:20", "09:25"):
                with self.subTest(symbol=symbol, missing=missing):
                    truncated = [bar for bar in bars if not (
                        parse_ist_timestamp(bar["timestamp"]).date() == self.now.date()
                        and parse_ist_timestamp(bar["timestamp"]).strftime("%H:%M") == missing)]
                    self.assertEqual(len(truncated), len(bars) - 1)
                    self.assertGreater(len(truncated), 30)
                    self.assertIsNone(evaluate_orb_breakout(symbol, truncated, now=self.now))

    def test_incomplete_opening_bar_cannot_be_replaced_by_a_later_bar(self):
        for symbol, pattern, _ in self.CASES:
            with self.subTest(symbol=symbol):
                bars = self._bars(symbol, pattern)
                changed = 0
                for bar in bars:
                    stamp = parse_ist_timestamp(bar["timestamp"])
                    if stamp.date() == self.now.date() and stamp.strftime("%H:%M") == "09:20":
                        bar["is_complete"] = False
                        changed += 1
                self.assertEqual(changed, 1)
                self.assertIsNone(evaluate_orb_breakout(symbol, bars, now=self.now))


if __name__ == "__main__":
    unittest.main()
