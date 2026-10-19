import json
import math
import os
import subprocess
import sys
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Offline suites must not consume local credentials or inherit application stores.
# Read only literal defaults from source, retaining the normal production loader.
import ast
from pathlib import Path
_config_tree = ast.parse(Path(__file__).with_name("config.py").read_text(encoding="utf-8"))
_test_config_defaults = {node.args[0].value: ast.literal_eval(node.args[1])
    for node in ast.walk(_config_tree) if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
    and node.func.value.id == "os" and node.func.attr == "getenv" and len(node.args) == 2}
_test_environment = patch.dict(os.environ, _test_config_defaults)
_test_environment.start()
unittest.addModuleCleanup(_test_environment.stop)
_original_exists = os.path.exists
with patch("os.path.exists", side_effect=lambda path: False if Path(path).name == ".env" else _original_exists(path)):
    from config import BotConfig
from brokers import (
    BaseBrokerAdapter,
    BrokerDataError,
    UnsupportedBrokerCapabilityError,
    MultiBrokerScanner,
    SimulatedNSEAdapter,
    AngelOneSmartAPIAdapter,
    DhanHQAdapter,
    UpstoxV2Adapter,
    generate_totp,
)
from strategies import (
    IST,
    TradeSignal,
    calculate_indian_statutory_charges,
    compute_atr,
    compute_ema,
    compute_rsi,
    compute_session_vwap,
    compute_supertrend,
    evaluate_option_apex_oi_shift,
    evaluate_orb_breakout,
    evaluate_order_block_fvg,
    evaluate_supertrend_pullback,
    evaluate_vwap_pullback,
    filter_completed_candles,
    is_within_nse_session,
    parse_ist_timestamp,
    validate_candles,
)
from telegram_bot import TelegramSignalDispatcher
from scanner_engine import IntradayBotEngine, MarketScanScheduler


class _FixtureTriggeredAdapter(BaseBrokerAdapter):
    """
    Test-only adapter that supplies a known valid setup for one symbol and non-triggering
    natural candles for all others, proving that IntradayBotEngine returns signals only
    when input candles genuinely satisfy strategy conditions.
    """
    name = "Fixture Triggered Test Adapter (SIMULATED)"
    is_simulated = True

    def __init__(self, sim: SimulatedNSEAdapter):
        self.sim = sim

    def get_intraday_candles(self, symbol_meta, interval_min=5, pattern=None):
        sym = symbol_meta.get("symbol", "")
        if sym == "RELIANCE":
            return self.sim.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern="order_block_bull")
        if sym == "SBIN":
            return self.sim.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern="supertrend_pullback_bull")
        return self.sim.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern=None)

    def get_option_chain(self, index_symbol, bias=None):
        if index_symbol == "NIFTY":
            return self.sim.get_option_chain(index_symbol, bias="BULLISH")
        return self.sim.get_option_chain(index_symbol, bias=None)


class _FlatCandleAdapter(BaseBrokerAdapter):
    """
    Test-only adapter returning valid flat-price candles that satisfy no breakout/pullback
    strategy, proving that normal scanning never manufactures forced signals.
    """
    name = "Flat Non-Triggering Adapter (SIMULATED)"
    is_simulated = True

    def get_intraday_candles(self, symbol_meta, interval_min=5, pattern=None):
        sim = SimulatedNSEAdapter(seed=42)
        raw = sim.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern=None)
        flat = []
        for c in raw:
            flat.append({
                "timestamp": c["timestamp"],
                "open": 1000.0,
                "high": 1000.5,
                "low": 999.5,
                "close": 1000.0,
                "volume": 50000.0,
                "is_complete": True,
                "is_simulated": True,
            })
        return flat

    def get_option_chain(self, index_symbol, bias=None):
        return {
            "index": index_symbol,
            "expiry": "2026-10-16",
            "spot": 24800.0,
            "atm_strike": 24800,
            "pcr": 0.95,
            "total_ce_oi": 2000000,
            "total_pe_oi": 1900000,
            "strikes": [
                {
                    "strike": 24800,
                    "ce_ltp": 120.0,
                    "ce_oi": 2000000,
                    "ce_oi_change": 50000,
                    "ce_iv": 12.5,
                    "pe_ltp": 115.0,
                    "pe_oi": 1900000,
                    "pe_oi_change": -20000,
                    "pe_iv": 13.0,
                }
            ],
            "is_simulated": True,
            "data_mode": "SIMULATED",
        }


class TestIndianFOSignalBotPhase1A(unittest.TestCase):
    def setUp(self):
        self.fixed_clock = lambda: datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.config = BotConfig(active_broker="paper_sim", telegram_dry_run=True)
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    # ------------------------------------------------------------------------
    # 1. Baseline & TOTP / Statutory Charge Tests
    # ------------------------------------------------------------------------
    def test_totp_generation(self):
        code = generate_totp("JBSWY3DPEHPK3PXP", for_time=1700000000.0)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        # Same timestamp and secret must produce identical RFC 6238 code
        self.assertEqual(code, generate_totp("JBSWY3DPEHPK3PXP", for_time=1700000000.0))
        # Placeholder or invalid base32 secret must raise ValueError
        with self.assertRaises(ValueError):
            generate_totp("your_angel_totp_base32_seed")
        with self.assertRaises(ValueError):
            generate_totp("INVALID_BASE32_999!!!")

    def test_indian_statutory_charges(self):
        eq_cost = calculate_indian_statutory_charges(350000.0, "NSE_EQUITY_INTRADAY")
        fo_cost = calculate_indian_statutory_charges(350000.0, "NSE_FO_INDEX")
        self.assertGreater(eq_cost, 100.0)
        self.assertLess(eq_cost, 200.0)
        self.assertGreater(fo_cost, eq_cost)
        self.assertEqual(calculate_indian_statutory_charges(0.0), 0.0)
        with self.assertRaises(ValueError):
            calculate_indian_statutory_charges(-100.0)

    # ------------------------------------------------------------------------
    # 2. Strategy 1–5 Baseline & Supertrend Pullback Regression Tests
    # ------------------------------------------------------------------------
    def test_strategy_1_order_block_fvg(self):
        candles = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5, pattern="order_block_bull")
        sig = evaluate_order_block_fvg("RELIANCE", candles)
        self.assertIsNotNone(sig, "Strategy 1 (Order Block + BOS/FVG) should trigger on Order Block retest")
        self.assertEqual(sig.strategy_id, "strat_1_order_block")
        self.assertGreater(sig.target_1, sig.entry_price)
        self.assertLess(sig.stop_loss, sig.entry_price)

    def test_strategy_2_vwap_pullback(self):
        candles = self.sim.get_intraday_candles({"symbol": "TCS"}, interval_min=5, pattern="vwap_pullback_bull")
        sig = evaluate_vwap_pullback("TCS", candles)
        self.assertIsNotNone(sig, "Strategy 2 (VWAP Pullback + Volume) should trigger on VWAP reclaim")
        self.assertEqual(sig.strategy_id, "strat_2_vwap_pullback")
        self.assertGreater(sig.target_1, sig.entry_price)

    def test_strategy_3_option_apex_oi_shift_nifty_banknifty_only(self):
        candles = self.sim.get_intraday_candles({"symbol": "NIFTY"}, interval_min=5, pattern="vwap_pullback_bull")
        oc = self.sim.get_option_chain("NIFTY", bias="BULLISH")
        sig = evaluate_option_apex_oi_shift("NIFTY", candles, oc, lot_size=75, capital_inr=500000)
        self.assertIsNotNone(sig, "Strategy 3 (Option Apex OI Shift) should trigger on NIFTY")
        self.assertEqual(sig.segment, "NSE_FO_INDEX")
        self.assertIn("NIFTY", sig.instrument_label)
        self.assertIn("CE", sig.instrument_label)
        self.assertTrue(sig.is_simulated)

        sig_eq = evaluate_option_apex_oi_shift("RELIANCE", candles, oc, lot_size=250, capital_inr=500000)
        self.assertIsNone(sig_eq, "F&O Option Apex must strictly restrict to NIFTY and BANKNIFTY")

    def test_strategy_4_orb_breakout(self):
        candles = self.sim.get_intraday_candles({"symbol": "ICICIBANK"}, interval_min=5, pattern="orb_breakout_bull")
        sig = evaluate_orb_breakout("ICICIBANK", candles)
        self.assertIsNotNone(sig, "Strategy 4 (15m ORB + RVOL) should trigger on high-volume breakout")
        self.assertEqual(sig.strategy_id, "strat_4_orb_filtered")

    def test_strategy_5_supertrend_pullback(self):
        candles = self.sim.get_intraday_candles({"symbol": "SBIN"}, interval_min=5, pattern="supertrend_pullback_bull")
        sig = evaluate_supertrend_pullback("SBIN", candles)
        self.assertIsNotNone(sig, "Strategy 5 (Supertrend 10,3 Pullback + 200 EMA) should trigger in valid session window")
        self.assertEqual(sig.strategy_id, "strat_5_supertrend_pullback")
        self.assertEqual(sig.timestamp, "2026-10-16 10:30:00")

    def test_strategy_5_supertrend_blocks_chop_and_opening_windows(self):
        candles = self.sim.get_intraday_candles({"symbol": "SBIN"}, interval_min=5, pattern="supertrend_pullback_bull")
        # 1) Shift final bar into 11:30–13:30 IST chop window (e.g. 12:00:00) -> must be blocked
        chop_candles = [dict(c) for c in candles]
        chop_candles[-1]["timestamp"] = "2026-10-16 12:00:00"
        self.assertIsNone(evaluate_supertrend_pullback("SBIN", chop_candles))

        # 2) If close is below 200 EMA -> must be blocked
        below_ema = [dict(c) for c in candles]
        below_ema[-1]["close"] = below_ema[-1]["open"] * 0.95
        below_ema[-1]["low"] = below_ema[-1]["close"] * 0.999
        self.assertIsNone(evaluate_supertrend_pullback("SBIN", below_ema))

    # ------------------------------------------------------------------------
    # 3 & 4. Determinism Within Process & Across Separate PYTHONHASHSEED Processes
    # ------------------------------------------------------------------------
    def test_simulated_candles_deterministic_across_repeated_runs(self):
        a1 = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)
        a2 = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)
        for pat in (None, "order_block_bull", "supertrend_pullback_bull"):
            c1 = a1.get_intraday_candles({"symbol": "SBIN"}, interval_min=5, pattern=pat)
            c2 = a2.get_intraday_candles({"symbol": "SBIN"}, interval_min=5, pattern=pat)
            self.assertEqual(c1, c2)
        oc1 = a1.get_option_chain("NIFTY")
        oc2 = a2.get_option_chain("NIFTY")
        self.assertEqual(oc1, oc2)

    def test_cross_process_pythonhashseed_determinism(self):
        """
        Verifies that simulated candles and Strategy 5 evaluation are identical across
        separate subprocesses with different PYTHONHASHSEED values (including seeds 3, 5, 6, 7, 9
        which failed in the baseline project).
        """
        work_dir = os.path.dirname(os.path.abspath(__file__))
        snippet = (
            "import json; import test_bot; "
            "from datetime import datetime; from strategies import IST; from brokers import SimulatedNSEAdapter; "
            "from strategies import evaluate_supertrend_pullback; "
            "sim = SimulatedNSEAdapter(seed=42, clock=lambda: datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)); "
            "c_nat = sim.get_intraday_candles({'symbol': 'SBIN'}, 5, None); "
            "c_st = sim.get_intraday_candles({'symbol': 'SBIN'}, 5, 'supertrend_pullback_bull'); "
            "sig = evaluate_supertrend_pullback('SBIN', c_st); "
            "print(json.dumps({'nat_last': c_nat[-1], 'st_last': c_st[-1], 'sig': sig.to_dict() if sig else None}, sort_keys=True))"
        )
        outputs = []
        for seed in ("0", "1", "3", "5", "6", "7", "9", "42"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=work_dir,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(proc.stdout.strip())
            self.assertIsNotNone(data["sig"], f"Supertrend failed under PYTHONHASHSEED={seed}")
            outputs.append(proc.stdout.strip())
        self.assertEqual(len(set(outputs)), 1, "Outputs differed across PYTHONHASHSEED subprocesses!")

    # ------------------------------------------------------------------------
    # 5. OHLCV Invariants, Warm-Up Continuity, and Chronological Timestamps
    # ------------------------------------------------------------------------
    def test_ohlcv_invariants_and_warmup_continuity(self):
        for sym in ("NIFTY", "BANKNIFTY", "RELIANCE", "SBIN", "TCS", "M&M"):
            for pat in (None, "order_block_bull", "vwap_pullback_bull", "orb_breakout_bull", "supertrend_pullback_bull"):
                candles = self.sim.get_intraday_candles({"symbol": sym}, interval_min=5, pattern=pat)
                validated = validate_candles(candles, deduplicate=False)
                self.assertEqual(len(candles), len(validated))
                for i, c in enumerate(candles):
                    self.assertGreaterEqual(c["high"], max(c["open"], c["close"]))
                    self.assertLessEqual(c["low"], min(c["open"], c["close"]))
                    self.assertGreaterEqual(c["high"], c["low"])
                    self.assertGreater(c["open"], 0)
                    self.assertGreaterEqual(c["volume"], 0)
                    if i > 0:
                        t_prev = parse_ist_timestamp(candles[i - 1]["timestamp"])
                        t_curr = parse_ist_timestamp(c["timestamp"])
                        self.assertGreater(t_curr, t_prev, "Timestamps must be strictly increasing")
                # Check continuity at the warm-up to session transition (index 224 -> 225)
                warmup_last_close = candles[224]["close"]
                session_first_open = candles[225]["open"]
                self.assertAlmostEqual(warmup_last_close, session_first_open, places=2)

    def test_validate_candles_rejects_invalid_ohlcv_and_backward_timestamps(self):
        base_bar = {
            "timestamp": "2026-10-16 09:15:00",
            "open": 100.0,
            "high": 105.0,
            "low": 98.0,
            "close": 102.0,
            "volume": 1000,
        }
        # High < Open
        with self.assertRaises(ValueError):
            validate_candles([dict(base_bar, high=99.0)])
        # Low > Close
        with self.assertRaises(ValueError):
            validate_candles([dict(base_bar, low=103.0)])
        # Negative volume
        with self.assertRaises(ValueError):
            validate_candles([dict(base_bar, volume=-5)])
        # NaN close
        with self.assertRaises(ValueError):
            validate_candles([dict(base_bar, close= float("nan"))])
        # Backward timestamps
        bar2_earlier = dict(base_bar, timestamp="2026-10-16 09:10:00")
        with self.assertRaises(ValueError):
            validate_candles([base_bar, bar2_earlier])
        # Duplicate timestamps deduplicated by default, or rejected when deduplicate=False
        bar2_dup = dict(base_bar, close=104.0)
        deduped = validate_candles([base_bar, bar2_dup], deduplicate=True)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["close"], 104.0)
        with self.assertRaises(ValueError):
            validate_candles([base_bar, bar2_dup], deduplicate=False)

    # ------------------------------------------------------------------------
    # 6 & 7. Timezone Handling, Session Boundaries & Completed-Candle Filtering
    # ------------------------------------------------------------------------
    def test_timezone_and_session_boundaries(self):
        # UTC 03:45Z == 09:15 IST (market open)
        dt_open = parse_ist_timestamp("2026-10-16T03:45:00Z")
        self.assertEqual(dt_open.tzinfo, IST)
        self.assertEqual(dt_open.hour, 9)
        self.assertEqual(dt_open.minute, 15)
        self.assertTrue(is_within_nse_session(dt_open))

        # Before 09:15 IST and after 15:30 IST
        self.assertFalse(is_within_nse_session("2026-10-16 09:10:00"))
        self.assertFalse(is_within_nse_session("2026-10-16 15:35:00"))
        self.assertTrue(is_within_nse_session("2026-10-16 15:30:00"))

    def test_completed_candle_filtering_with_injectable_clock(self):
        candles = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5, pattern="order_block_bull")
        # Last bar starts at 2026-10-16 10:30:00 IST and completes at 10:35:00 IST.
        # 1) If clock is 10:32:00 IST, the 10:30 bar is still forming and must be excluded!
        forming_now = datetime(2026, 10, 16, 10, 32, 0, tzinfo=IST)
        filtered = filter_completed_candles(candles, interval_min=5, now=forming_now)
        self.assertEqual(len(filtered), len(candles) - 1)
        self.assertIsNone(evaluate_order_block_fvg("RELIANCE", candles, now=forming_now))

        # 2) Once clock reaches 10:35:00 IST, the 10:30 bar is complete and triggers!
        completed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.assertIsNotNone(evaluate_order_block_fvg("RELIANCE", candles, now=completed_now))

        # 3) Explicit is_complete=False flag on the final candle must also exclude it
        unclosed = [dict(c) for c in candles]
        unclosed[-1]["is_complete"] = False
        self.assertIsNone(evaluate_order_block_fvg("RELIANCE", unclosed))

    # ------------------------------------------------------------------------
    # 8. Wilder RSI & ATR Reference Cases and Edge Cases
    # ------------------------------------------------------------------------
    def test_wilder_rsi_and_atr_calculations_and_edge_cases(self):
        # Flat prices -> RSI must be 50.0 (never 100.0 or NaN)
        flat_rsi = compute_rsi([100.0] * 20, period=14)
        self.assertEqual(flat_rsi[-1], 50.0)

        # Monotonic gains -> RSI must be 100.0
        up_rsi = compute_rsi([100.0 + i for i in range(20)], period=14)
        self.assertEqual(up_rsi[-1], 100.0)

        # Monotonic losses -> RSI must be 0.0
        down_rsi = compute_rsi([100.0 - i for i in range(20)], period=14)
        self.assertEqual(down_rsi[-1], 0.0)

        # Hand-verified Wilder RMA RSI (period=3):
        # Closes: [100, 103, 106, 103, 106]
        # Deltas: +3, +3, -3, +3
        # At i=3 (seed over first 3 deltas): avg_gain = (3+3+0)/3 = 2.0, avg_loss = (0+0+3)/3 = 1.0 -> RS=2.0 -> RSI=66.67
        # At i=4 (Wilder RMA with gain=3, loss=0):
        #   avg_gain = (2.0 * 2 + 3.0) / 3 = 7/3 = 2.3333
        #   avg_loss = (1.0 * 2 + 0.0) / 3 = 2/3 = 0.6667
        #   RS = 7/2 = 3.5 -> RSI = 100 - 100/4.5 = 77.78
        # (Note: an arithmetic SMA over the last 3 deltas [+3, -3, +3] would have given RS=2.0 -> RSI=66.67)
        rma_rsi = compute_rsi([100.0, 103.0, 106.0, 103.0, 106.0], period=3)
        self.assertEqual(rma_rsi[3], 66.67)
        self.assertEqual(rma_rsi[4], 77.78)

        # Hand-verified Wilder RMA ATR (period=3):
        # TRs: 10, 10, 10, 22 -> seed at idx 2 is 10.0; at idx 3 Wilder ATR = (10*2 + 22)/3 = 14.0 (SMA would be 14.0, next bar with TR=10: Wilder=(14*2+10)/3=12.6667 vs SMA=(10+22+10)/3=14.0)
        bars = [
            {"high": 110.0, "low": 100.0, "close": 105.0},
            {"high": 115.0, "low": 105.0, "close": 110.0},
            {"high": 120.0, "low": 110.0, "close": 115.0},
            {"high": 137.0, "low": 115.0, "close": 130.0},
            {"high": 140.0, "low": 130.0, "close": 135.0},
        ]
        atrs = compute_atr(bars, period=3)
        self.assertAlmostEqual(atrs[2], 10.0, places=4)
        self.assertAlmostEqual(atrs[3], 14.0, places=4)
        self.assertAlmostEqual(atrs[4], (14.0 * 2 + 10.0) / 3.0, places=4)

        # NaN / Inf rejection
        with self.assertRaises(ValueError):
            compute_rsi([100.0, float("nan"), 102.0], period=14)
        with self.assertRaises(ValueError):
            compute_atr([{"high": float("inf"), "low": 100.0, "close": 100.0}], period=10)

    # ------------------------------------------------------------------------
    # 9 & 10. Prevent Silent Live-to-Simulation Fallback & Explicit Sim Mode
    # ------------------------------------------------------------------------
    def test_live_provider_failure_raises_explicit_error_without_silent_fallback(self):
        for broker_key, secret_kw in (
            ("angelone", {"angel_api_key": "SECRET_KEY_123", "angel_client_code": "C1", "angel_pin": "1234", "angel_totp_secret": "JBSWY3DPEHPK3PXP"}),
            ("dhan", {"dhan_client_id": "DHAN_ID", "dhan_access_token": "SECRET_JWT_TOKEN"}),
            ("upstox", {"upstox_api_key": "UP_KEY", "upstox_access_token": "SECRET_OAUTH_TOKEN"}),
        ):
            cfg = BotConfig(active_broker=broker_key, telegram_dry_run=True, **secret_kw)
            scanner = MultiBrokerScanner(cfg)
            self.assertFalse(scanner.get_active_adapter().is_simulated)

            with patch("urllib.request.urlopen", side_effect=OSError("Simulated network failure")):
                with self.assertRaises(BrokerDataError) as ctx:
                    scanner.fetch_candles({"symbol": "RELIANCE", "angel_token": "2885", "dhan_id": "2885", "upstox_key": "NSE_EQ|INE002A01018"})
                # Ensure secret tokens are never leaked in error message
                err_msg = str(ctx.exception)
                for secret_val in secret_kw.values():
                    self.assertNotIn(secret_val, err_msg)

        # Unknown broker name must also raise BrokerDataError
        bad_cfg = BotConfig(active_broker="nonexistent_broker")
        with self.assertRaises(BrokerDataError):
            MultiBrokerScanner(bad_cfg).get_active_adapter()

    def test_explicit_simulation_mode_is_labeled(self):
        engine = IntradayBotEngine(self.config)
        res = engine.run_single_scan()
        self.assertTrue(res["is_simulated"])
        self.assertEqual(res["data_mode"], "SIMULATED")
        self.assertIn("SIMULATED", res["broker"].upper())

    # ------------------------------------------------------------------------
    # 11. Telegram HTML Escaping & Mocked Network Dispatch
    # ------------------------------------------------------------------------
    def test_telegram_html_escaping_and_mocked_send(self):
        dispatcher = TelegramSignalDispatcher(
            BotConfig(telegram_bot_token="999999:FAKE_TOKEN_FOR_TEST", telegram_chat_id="-100999", telegram_dry_run=False)
        )
        sig = TradeSignal(
            symbol="M&M",
            segment="NSE_EQUITY_INTRADAY",
            strategy_id="strat_1_order_block",
            strategy_name="Order Block <BOS & FVG>",
            direction="BULLISH (BUY)",
            instrument_label="M&M EQ <Test & 'Quote'>",
            entry_price=3040.0,
            entry_zone_low=3025.0,
            entry_zone_high=3040.0,
            stop_loss=3010.0,
            target_1=3100.0,
            target_2=3130.0,
            risk_reward="1:2.0 & <1:3.0>",
            confidence_pct=89,
            win_rate_benchmark="58%–64% <OrderBlock & Co>",
            position_qty=50,
            capital_risk_inr=1500.0,
            est_charges_inr=120.5,
            rationale="M&M held <support> & bounced > ₹3,025 with ΔOI 'strong'",
            timestamp="2026-10-16 10:30:00",
            is_simulated=True,
            data_mode="SIMULATED",
        )
        html_msg = dispatcher.format_signal_html(sig, broker_name="Angel One & <Sim>")
        self.assertIn("M&amp;M EQ &lt;Test &amp; &#x27;Quote&#x27;&gt;", html_msg)
        self.assertIn("Order Block &lt;BOS &amp; FVG&gt;", html_msg)
        self.assertIn("M&amp;M held &lt;support&gt; &amp; bounced &gt; ₹3,025", html_msg)
        self.assertIn("[SIMULATED DATA]", html_msg)
        # Intentional HTML tags must remain intact
        self.assertIn("<b>Instrument:</b> <code>", html_msg)

        # Mock network call to verify payload without contacting Telegram
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true, "result": {"message_id": 101}}'
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp) as mocked_open:
            send_res = dispatcher.send_signal(sig, broker_name="Angel One & <Sim>")
            self.assertTrue(send_res["ok"])
            self.assertEqual(mocked_open.call_count, 1)

            # Duplicate call within same candle must be skipped
            dup_res = dispatcher.send_signal(sig, broker_name="Angel One & <Sim>")
            self.assertTrue(dup_res.get("skipped"))

        # Verify network error sanitizes bot token
        sig2 = TradeSignal(**dict(sig.to_dict(), symbol="RELIANCE", timestamp="2026-10-16 10:35:00"))
        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused for https://api.telegram.org/bot999999:FAKE_TOKEN_FOR_TEST/sendMessage")):
            with self.assertRaises(RuntimeError) as ctx:
                dispatcher.send_signal(sig2)
            self.assertNotIn("FAKE_TOKEN_FOR_TEST", str(ctx.exception))

    # ------------------------------------------------------------------------
    # 12. Normal Scanning Does Not Force Signals, Yet Emits Legitimate Signals
    # ------------------------------------------------------------------------
    def test_normal_scan_does_not_force_signals_on_non_triggering_candles(self):
        flat_scanner = MultiBrokerScanner(self.config)
        flat_scanner.adapters["paper_sim"] = _FlatCandleAdapter()
        engine = IntradayBotEngine(self.config, broker_scanner=flat_scanner)
        res = engine.run_single_scan()
        self.assertEqual(res["total_signals"], 0, "Normal scan must not manufacture signals when candles do not trigger")
        self.assertEqual(res["signals"], [])

    def test_full_engine_and_telegram_dispatch(self):
        # 1) Default unforced simulation scan runs cleanly and tags output as SIMULATED
        default_engine = IntradayBotEngine(self.config)
        default_res = default_engine.run_single_scan()
        self.assertEqual(default_res["status"], "ok")
        self.assertTrue(default_res["is_simulated"])
        self.assertEqual(default_res["data_mode"], "SIMULATED")

        # 2) When input candles genuinely contain valid setups (via fixture adapter),
        #    IntradayBotEngine detects them and dispatches formatted alerts to Telegram
        trig_scanner = MultiBrokerScanner(self.config)
        trig_scanner.adapters["paper_sim"] = _FixtureTriggeredAdapter(self.sim)
        trig_engine = IntradayBotEngine(self.config, broker_scanner=trig_scanner)
        res = trig_engine.run_single_scan()
        self.assertGreaterEqual(res["total_signals"], 3)
        self.assertEqual(len(res["telegram_dispatches"]), res["total_signals"])
        first_msg = res["telegram_dispatches"][0]["message_html"]
        self.assertIn("SIMULATED SIGNAL [SIMULATED DATA]", first_msg)
        self.assertIn("Stop-Loss (S1):", first_msg)




class TestIndianFOSignalBotPhase1B(unittest.TestCase):
    """
    Phase 1B Regression & Mocked Provider Integration Test Suite
    Covers items 1–17 in Section 10 of the Phase 1B specification.
    """
    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    # 1. Clock-relative simulation dates & weekend handling (P0)
    def test_p0_clock_relative_simulation_dates_and_weekend_rollover(self):
        from brokers import resolve_nse_session_dates

        # Case A: Friday 2026-10-16 -> Warm-up days Tue Oct 13, Wed Oct 14, Thu Oct 15
        c_fri = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5)
        self.assertTrue(c_fri[0]["timestamp"].startswith("2026-10-13 09:15:00"))
        self.assertTrue(c_fri[224]["timestamp"].startswith("2026-10-15 15:25:00"))
        self.assertTrue(c_fri[225]["timestamp"].startswith("2026-10-16 09:15:00"))
        self.assertTrue(c_fri[-1]["timestamp"].startswith("2026-10-16 10:30:00"))

        # Case B: Monday 2026-11-09 -> Warm-up days must skip weekend (Nov 7–8) and use Wed Nov 4, Thu Nov 5, Fri Nov 6
        mon_clock = lambda: datetime(2026, 11, 9, 11, 0, 0, tzinfo=IST)
        sim_mon = SimulatedNSEAdapter(seed=42, clock=mon_clock)
        c_mon = sim_mon.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5)
        self.assertTrue(c_mon[0]["timestamp"].startswith("2026-11-04 09:15:00"))
        self.assertTrue(c_mon[75]["timestamp"].startswith("2026-11-05 09:15:00"))
        self.assertTrue(c_mon[150]["timestamp"].startswith("2026-11-06 09:15:00"))
        self.assertTrue(c_mon[225]["timestamp"].startswith("2026-11-09 09:15:00"))
        self.assertTrue(c_mon[-1]["timestamp"].startswith("2026-11-09 10:30:00"))

        # Case C: Sunday 2026-11-08 -> Rolls back to Friday 2026-11-06 session with Tue Nov 3, Wed Nov 4, Thu Nov 5 warm-up
        sun_clock = lambda: datetime(2026, 11, 8, 12, 0, 0, tzinfo=IST)
        warmup, session_day = resolve_nse_session_dates(sun_clock(), warmup_sessions=3)
        self.assertEqual(str(session_day), "2026-11-06")
        self.assertEqual([str(d) for d in warmup], ["2026-11-03", "2026-11-04", "2026-11-05"])

    # 2 & 3. Timestamp normalization across provider formats & UTC-to-IST conversion
    def test_p1_timestamp_normalization_and_utc_to_ist_conversion(self):
        # 2026-10-16 09:15:00 IST == 2026-10-16 03:45:00 UTC == epoch 1792122300 sec == 1792122300000 ms
        expected_ist = datetime(2026, 10, 16, 9, 15, 0, tzinfo=IST)
        for raw_ts in (
            "2026-10-16T09:15:00+05:30",     # Upstox / Angel One ISO-8601 with IST offset
            "2026-10-16T03:45:00Z",          # UTC ISO-8601
            "2026-10-16T03:45:00+00:00",     # UTC offset ISO-8601
            1792122300,                      # DhanHQ Unix epoch seconds (int)
            1792122300.0,                    # DhanHQ Unix epoch seconds (float)
            "1792122300",                    # Numeric epoch seconds string
            1792122300000,                   # Unix epoch milliseconds
            "2026-10-16 09:15:00",           # Exchange-local IST string
        ):
            parsed = parse_ist_timestamp(raw_ts)
            self.assertEqual(parsed, expected_ist, f"Failed for input {raw_ts!r}")
            self.assertEqual(parsed.tzinfo, IST)

        for invalid_ts in (None, True, False, -100, float("nan"), float("inf"), "not-a-timestamp"):
            with self.assertRaises(ValueError):
                parse_ist_timestamp(invalid_ts)

    # 4 & 5. Reverse-chronological sorting, duplicate handling & forming-candle detection
    def test_p1_provider_candle_sorting_and_forming_candle_detection(self):
        # Clock at 09:23:00 IST: 09:15 (ends 09:20) is complete; 09:20 (ends 09:25) is still forming!
        now_dt = datetime(2026, 10, 16, 9, 23, 0, tzinfo=IST)
        reverse_bars = [
            {"timestamp": "2026-10-16T09:20:00+05:30", "open": 102.0, "high": 104.0, "low": 101.0, "close": 103.5, "volume": 1200},
            {"timestamp": "2026-10-16T09:15:00+05:30", "open": 100.0, "high": 103.0, "low": 99.5, "close": 102.0, "volume": 1500},
        ]
        norm = validate_candles(reverse_bars, deduplicate=True, sort_chronologically=True, interval_min=5, now=now_dt)
        self.assertEqual(len(norm), 2)
        self.assertEqual(norm[0]["timestamp"], "2026-10-16 09:15:00")
        self.assertTrue(norm[0]["is_complete"])
        self.assertEqual(norm[1]["timestamp"], "2026-10-16 09:20:00")
        self.assertFalse(norm[1]["is_complete"], "09:20 5m candle must be marked incomplete at 09:23 IST")

        completed_only = filter_completed_candles(norm, interval_min=5, now=now_dt)
        self.assertEqual(len(completed_only), 1)
        self.assertEqual(completed_only[0]["timestamp"], "2026-10-16 09:15:00")

    # 6 & 7. Upstox v2 interval handling & 1m -> 5m OHLCV session-aligned aggregation
    def test_p1_upstox_intraday_candles_and_five_minute_aggregation(self):
        cfg = BotConfig(active_broker="upstox", upstox_access_token="VALID_TEST_OAUTH_TOKEN")
        # Clock at 09:25:00 IST -> 09:15..09:19 bucket (5 bars) is complete; 09:20..09:22 (3 bars) is incomplete
        clock = lambda: datetime(2026, 10, 16, 9, 25, 0, tzinfo=IST)
        adapter = UpstoxV2Adapter(cfg, clock=clock)

        # Upstox returns reverse-chronological 1-minute candles
        upstox_1m_payload = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-10-16T09:22:00+05:30", 2955.0, 2958.0, 2954.0, 2957.0, 1000, 0],
                    ["2026-10-16T09:21:00+05:30", 2952.0, 2956.0, 2951.0, 2955.0, 1000, 0],
                    ["2026-10-16T09:20:00+05:30", 2950.0, 2953.0, 2949.0, 2952.0, 1000, 0],
                    # Complete 09:15..09:19 bucket (5 bars):
                    ["2026-10-16T09:19:00+05:30", 2948.0, 2951.0, 2947.0, 2950.0, 5000, 0],
                    ["2026-10-16T09:18:00+05:30", 2946.0, 2954.0, 2945.0, 2948.0, 4000, 0],
                    ["2026-10-16T09:17:00+05:30", 2942.0, 2947.0, 2938.0, 2946.0, 3000, 0],
                    ["2026-10-16T09:16:00+05:30", 2944.0, 2946.0, 2941.0, 2942.0, 2000, 0],
                    ["2026-10-16T09:15:00+05:30", 2940.0, 2945.0, 2939.0, 2944.0, 1000, 0],
                ]
            },
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(upstox_1m_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mocked_get:
            bars_5m = adapter.get_intraday_candles(
                {"symbol": "RELIANCE", "upstox_key": "NSE_EQ|INE002A01018"},
                interval_min=5,
            )
            req_url = mocked_get.call_args[0][0].full_url
            self.assertIn("/1minute", req_url)

        self.assertEqual(len(bars_5m), 2)
        # First 5m bucket (09:15..09:19) has all 5 component bars and elapsed -> complete
        b0 = bars_5m[0]
        self.assertEqual(b0["timestamp"], "2026-10-16 09:15:00")
        self.assertEqual(b0["open"], 2940.0)
        self.assertEqual(b0["high"], 2954.0)
        self.assertEqual(b0["low"], 2938.0)
        self.assertEqual(b0["close"], 2950.0)
        self.assertEqual(b0["volume"], 15000.0)
        self.assertTrue(b0["is_complete"])

        # Second 5m bucket (09:20..09:22) has only 3 of 5 component bars -> must NOT be marked complete
        b1 = bars_5m[1]
        self.assertEqual(b1["timestamp"], "2026-10-16 09:20:00")
        self.assertEqual(b1["component_count"], 3)
        self.assertFalse(b1["is_complete"])

        # Unsupported Upstox interval must raise BrokerDataError
        with self.assertRaises(BrokerDataError):
            adapter.get_intraday_candles({"symbol": "RELIANCE", "upstox_key": "NSE_EQ|INE002A01018"}, interval_min=7)

    # 8 & 16. DhanHQ expiry resolution, option-chain normalization, and Strategy 3 evaluator compatibility
    def test_p1_dhanhq_expiry_and_option_chain_normalization(self):
        cfg = BotConfig(
            active_broker="dhan",
            dhan_client_id="1000000001",
            dhan_access_token="VALID_DHAN_JWT",
        )
        adapter = DhanHQAdapter(cfg, clock=self.fixed_clock)
        adapter._respect_oc_rate_limit = lambda: None  # skip 3s sleep in unit test

        expiry_resp_json = {
            "data": ["2026-10-08", "2026-10-15", "2026-10-22", "2026-10-29"],
            "status": "success",
        }
        oc_resp_json = {
            "data": {
                "last_price": 24820.5,
                "oc": {
                    "24750.000000": {
                        "ce": {"last_price": 168.0, "oi": 1500000, "previous_oi": 1700000, "implied_volatility": 11.8},
                        "pe": {"last_price": 88.5, "oi": 2800000, "previous_oi": 2200000, "implied_volatility": 12.4},
                    },
                    "24800.000000": {
                        "ce": {"last_price": 142.5, "oi": 1850000, "previous_oi": 2270000, "implied_volatility": 12.1},
                        "pe": {"last_price": 112.8, "oi": 3400000, "previous_oi": 2720000, "implied_volatility": 12.9},
                    },
                    "24850.000000": {
                        "ce": {"last_price": 116.0, "oi": 2100000, "previous_oi": 2000000, "implied_volatility": 12.3},
                        "pe": {"last_price": 139.0, "oi": 1900000, "previous_oi": 1800000, "implied_volatility": 13.1},
                    },
                },
            },
            "status": "success",
        }

        responses = [
            json.dumps(expiry_resp_json).encode("utf-8"),
            json.dumps(oc_resp_json).encode("utf-8"),
        ]

        def side_effect(req, timeout=8):
            m = MagicMock()
            m.read.return_value = responses.pop(0)
            m.__enter__.return_value = m
            return m

        with patch("urllib.request.urlopen", side_effect=side_effect) as mocked_post:
            norm_oc = adapter.get_option_chain("NIFTY")
            self.assertEqual(mocked_post.call_count, 2)
            # Verify second request sent 'Expiry': '2026-10-22' (first expiry >= 2026-10-16)
            second_req_body = json.loads(mocked_post.call_args_list[1][0][0].data.decode("utf-8"))
            self.assertEqual(second_req_body["Expiry"], "2026-10-22")
            self.assertEqual(second_req_body["UnderlyingScrip"], 13)
            self.assertEqual(second_req_body["UnderlyingSeg"], "IDX_I")

        self.assertEqual(norm_oc["index"], "NIFTY")
        self.assertEqual(norm_oc["expiry"], "2026-10-22")
        self.assertEqual(norm_oc["spot"], 24820.5)
        self.assertEqual(norm_oc["atm_strike"], 24800)
        self.assertFalse(norm_oc["is_simulated"])
        self.assertEqual(norm_oc["data_mode"], "LIVE")
        atm_row = next(s for s in norm_oc["strikes"] if s["strike"] == 24800)
        self.assertEqual(atm_row["ce_oi_change"], 1850000 - 2270000)  # -420000
        self.assertEqual(atm_row["pe_oi_change"], 3400000 - 2720000)  # +680000

        # Verify normalized DhanHQ option chain works directly with evaluate_option_apex_oi_shift
        candles = self.sim.get_intraday_candles({"symbol": "NIFTY"}, interval_min=5, pattern="vwap_pullback_bull")
        sig = evaluate_option_apex_oi_shift("NIFTY", candles, norm_oc, lot_size=75, capital_inr=500000)
        self.assertIsNotNone(sig)
        self.assertFalse(sig.is_simulated)
        self.assertEqual(sig.data_mode, "LIVE")
        self.assertEqual(sig.entry_price, 142.5)

    # 9 & 16. Upstox option-chain expiry resolution, normalization, and evaluator compatibility
    def test_p1_upstox_expiry_and_option_chain_normalization(self):
        cfg = BotConfig(active_broker="upstox", upstox_access_token="VALID_UPSTOX_TOKEN")
        adapter = UpstoxV2Adapter(cfg, clock=self.fixed_clock)

        contracts_resp = {
            "status": "success",
            "data": [
                {"expiry": "2026-10-15", "strike_price": 24800},
                {"expiry": "2026-10-22", "strike_price": 24800},
                {"expiry": "2026-10-29", "strike_price": 24800},
            ],
        }
        upstox_oc_resp = {
            "status": "success",
            "data": [
                {
                    "expiry": "2026-10-22",
                    "pcr": 1.84,
                    "strike_price": 24800,
                    "underlying_key": "NSE_INDEX|Nifty 50",
                    "underlying_spot_price": 24818.0,
                    "call_options": {
                        "instrument_key": "NSE_FO|51059",
                        "market_data": {"ltp": 140.0, "volume": 120000, "oi": 1800000, "prev_oi": 2250000},
                        "option_greeks": {"iv": 12.2, "delta": 0.52},
                    },
                    "put_options": {
                        "instrument_key": "NSE_FO|51060",
                        "market_data": {"ltp": 110.0, "volume": 140000, "oi": 3300000, "prev_oi": 2600000},
                        "option_greeks": {"iv": 12.8, "delta": -0.48},
                    },
                }
            ],
        }
        responses = [
            json.dumps(contracts_resp).encode("utf-8"),
            json.dumps(upstox_oc_resp).encode("utf-8"),
        ]

        def side_effect(req, timeout=8):
            m = MagicMock()
            m.read.return_value = responses.pop(0)
            m.__enter__.return_value = m
            return m

        with patch("urllib.request.urlopen", side_effect=side_effect) as mocked_get:
            norm_oc = adapter.get_option_chain("NIFTY")
            self.assertEqual(mocked_get.call_count, 2)
            chain_url = mocked_get.call_args_list[1][0][0].full_url
            self.assertIn("expiry_date=2026-10-22", chain_url)

        self.assertEqual(norm_oc["spot"], 24818.0)  # Underlying spot, NOT option LTP 140.0!
        self.assertEqual(norm_oc["atm_strike"], 24800)
        self.assertEqual(norm_oc["strikes"][0]["ce_oi_change"], -450000)
        self.assertEqual(norm_oc["strikes"][0]["pe_oi_change"], 700000)

        candles = self.sim.get_intraday_candles({"symbol": "NIFTY"}, interval_min=5, pattern="vwap_pullback_bull")
        sig = evaluate_option_apex_oi_shift("NIFTY", candles, norm_oc, lot_size=75, capital_inr=500000)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.entry_price, 140.0)

    # 10. Angel One candle normalization & explicit unsupported option-chain error
    def test_p1_angelone_candle_normalization_and_option_chain_explicit_error(self):
        cfg = BotConfig(
            active_broker="angelone",
            angel_api_key="ANGEL_KEY",
            angel_client_code="C100",
            angel_pin="1234",
            angel_totp_secret="JBSWY3DPEHPK3PXP",
        )
        adapter = AngelOneSmartAPIAdapter(cfg, clock=lambda: datetime(2026, 10, 16, 9, 25, tzinfo=IST))
        with self.assertRaises(BrokerDataError) as ctx:
            adapter.get_option_chain("NIFTY")
        self.assertIn("does not provide a single-call option-chain endpoint", str(ctx.exception))

        # Verify Angel One candle normalization with mocked login + getCandleData
        login_resp = {"status": True, "data": {"jwtToken": "MOCK_JWT"}}
        candle_resp = {
            "status": True,
            "data": [
                ["2026-10-16T09:15:00+05:30", 2940.0, 2948.0, 2938.0, 2945.0, 85000],
                ["2026-10-16T09:20:00+05:30", 2945.0, 2952.0, 2944.0, 2950.0, 92000],
            ],
        }
        responses = [json.dumps(login_resp).encode("utf-8"), json.dumps(candle_resp).encode("utf-8")]

        def side_effect(req, timeout=8):
            m = MagicMock()
            m.read.return_value = responses.pop(0)
            m.__enter__.return_value = m
            return m

        with patch("urllib.request.urlopen", side_effect=side_effect):
            bars = adapter.get_intraday_candles({"symbol": "RELIANCE", "angel_token": "2885"}, interval_min=5)
            self.assertEqual(len(bars), 2)
            self.assertTrue(bars[0]["is_complete"])
            self.assertFalse(bars[0]["is_simulated"])

    # 11. Instrument & interval validation (no silent default to RELIANCE / 2885, no index/equity mix-ups)
    def test_p1_instrument_and_interval_validation_prevents_silent_defaults(self):
        from brokers import validate_symbol_meta

        # Missing symbol -> must fail instead of defaulting to RELIANCE
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({}, "angelone")
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": ""}, "paper_sim")
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "UNKNOWN_TICKER_XYZ"}, "paper_sim")

        # Index using equity identifiers -> must fail
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "NIFTY", "dhan_id": "13"}, "dhan")
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "NIFTY", "upstox_key": "NSE_EQ|INE002A01018"}, "upstox")
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "NIFTY", "angel_token": "2885"}, "angelone")

        # Equity using index identifiers -> must fail
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "RELIANCE", "dhan_security_id": "13"}, "dhan")
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "RELIANCE", "upstox_key": "NSE_INDEX|Nifty 50"}, "upstox")
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "RELIANCE", "angel_token": "99926000"}, "angelone")

    # 12 & 13. Empty responses, malformed JSON, and missing option-chain fields rejected
    def test_p1_empty_and_malformed_provider_responses_rejected(self):
        dhan = DhanHQAdapter(
            BotConfig(active_broker="dhan", dhan_client_id="C1", dhan_access_token="T1"),
            clock=self.fixed_clock,
        )
        upstox = UpstoxV2Adapter(
            BotConfig(active_broker="upstox", upstox_access_token="T2"),
            clock=self.fixed_clock,
        )

        # Missing previous_oi in DhanHQ option chain -> must raise BrokerDataError (never fabricate 0)
        bad_dhan_oc = {
            "status": "success",
            "data": {
                "last_price": 24800.0,
                "oc": {
                    "24800.000000": {
                        "ce": {"last_price": 140.0, "oi": 100000},  # missing previous_oi!
                        "pe": {"last_price": 110.0, "oi": 120000, "previous_oi": 100000},
                    }
                },
            },
        }
        with self.assertRaises(BrokerDataError):
            dhan._normalize_option_chain_response("NIFTY", "2026-10-22", bad_dhan_oc)

        # Missing prev_oi in Upstox option chain -> must raise BrokerDataError
        bad_upstox_oc = {
            "status": "success",
            "data": [
                {
                    "strike_price": 24800,
                    "underlying_spot_price": 24800.0,
                    "call_options": {"market_data": {"ltp": 140.0, "oi": 100000}},  # missing prev_oi!
                    "put_options": {"market_data": {"ltp": 110.0, "oi": 120000, "prev_oi": 100000}},
                }
            ],
        }
        with self.assertRaises(BrokerDataError):
            upstox._normalize_option_chain_response("NIFTY", "2026-10-22", bad_upstox_oc)

        # Zero Call OI -> must reject PCR division by zero
        zero_ce_oi_upstox = {
            "status": "success",
            "data": [
                {
                    "strike_price": 24800,
                    "underlying_spot_price": 24800.0,
                    "call_options": {"market_data": {"ltp": 140.0, "oi": 0, "prev_oi": 0}},
                    "put_options": {"market_data": {"ltp": 110.0, "oi": 120000, "prev_oi": 100000}},
                }
            ],
        }
        with self.assertRaises(BrokerDataError):
            upstox._normalize_option_chain_response("NIFTY", "2026-10-22", zero_ce_oi_upstox)

    # 14 & 15. Authentication failures, rate-limiting errors, DhanHQ intraday epoch candles, and no fallback on option chain failure
    def test_p1_dhanhq_intraday_epoch_candles_and_mismatched_arrays(self):
        cfg = BotConfig(active_broker="dhan", dhan_client_id="1001", dhan_access_token="TOKEN_XYZ")
        adapter = DhanHQAdapter(cfg, clock=lambda: datetime(2026, 10, 16, 9, 25, tzinfo=IST))
        # 2026-10-16 09:15:00 IST = 1792122300, 09:20:00 IST = 1792122600
        dhan_candles_payload = {
            "open": [2940.0, 2945.0],
            "high": [2948.0, 2952.0],
            "low": [2938.0, 2943.0],
            "close": [2945.0, 2950.0],
            "volume": [120000, 135000],
            "timestamp": [1792122300, 1792122600],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(dhan_candles_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            bars = adapter.get_intraday_candles({"symbol": "RELIANCE", "dhan_id": "2885"}, interval_min=5)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["timestamp"], "2026-10-16 09:15:00")
        self.assertEqual(bars[1]["timestamp"], "2026-10-16 09:20:00")
        self.assertTrue(bars[0]["is_complete"])
        self.assertFalse(bars[0]["is_simulated"])

        # Mismatched array lengths must raise BrokerDataError
        bad_payload = dict(dhan_candles_payload, close=[2945.0])
        mock_resp.read.return_value = json.dumps(bad_payload).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with self.assertRaises(BrokerDataError):
                adapter.get_intraday_candles({"symbol": "RELIANCE", "dhan_id": "2885"}, interval_min=5)

    def test_p1_auth_failure_rate_limit_and_no_option_chain_fallback(self):
        import urllib.error
        for broker_key, secret_kw in (
            ("angelone", {"angel_api_key": "AK_SECRET", "angel_client_code": "C1", "angel_pin": "9999", "angel_totp_secret": "JBSWY3DPEHPK3PXP"}),
            ("dhan", {"dhan_client_id": "DH_ID", "dhan_access_token": "DH_SECRET_JWT"}),
            ("upstox", {"upstox_api_key": "UP_ID", "upstox_access_token": "UP_SECRET_OAUTH"}),
        ):
            cfg = BotConfig(active_broker=broker_key, telegram_dry_run=True, **secret_kw)
            scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
            with urllib.error.HTTPError(
                url="https://api.example.com",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=None,
            ) as http_429:
                with patch("urllib.request.urlopen", side_effect=http_429):
                    with self.assertRaises(BrokerDataError) as ctx:
                        scanner.fetch_option_chain("NIFTY")
                    for secret_val in secret_kw.values():
                        self.assertNotIn(secret_val, str(ctx.exception))



class _BidirectionalFixtureAdapter(BaseBrokerAdapter):
    name = "Bidirectional Fixture Test Adapter (SIMULATED)"
    is_simulated = True

    def __init__(self, sim: SimulatedNSEAdapter):
        self.sim = sim

    def get_intraday_candles(self, symbol_meta, interval_min=5, pattern=None):
        sym = symbol_meta.get("symbol", "")
        mapping = {
            "RELIANCE": "order_block_bull",
            "BAJFINANCE": "order_block_bear",
            "TCS": "vwap_pullback_bull",
            "INFY": "vwap_pullback_bear",
            "ICICIBANK": "orb_breakout_bull",
            "AXISBANK": "orb_breakout_bear",
            "SBIN": "supertrend_pullback_bull",
            "TATAMOTORS": "supertrend_pullback_bear",
            "NIFTY": "vwap_pullback_bull",
            "BANKNIFTY": "vwap_pullback_bear",
        }
        return self.sim.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern=mapping.get(sym))

    def get_option_chain(self, index_symbol, bias=None, expiry=None):
        if index_symbol == "NIFTY":
            return self.sim.get_option_chain("NIFTY", bias="BULLISH")
        if index_symbol == "BANKNIFTY":
            return self.sim.get_option_chain("BANKNIFTY", bias="BEARISH")
        return self.sim.get_option_chain(index_symbol, bias=None)


class TestIndianFOSignalBotPhase1C(unittest.TestCase):
    """
    Phase 1C Regression & Strategy Improvement Test Suite:
    1. Bidirectional (Bullish & Bearish) evaluation across all 5 strategies.
    2. Order Block mitigation, first-retest tracking, and close-beyond-zone invalidation.
    3. Reproducible evidence-based setup-quality score (RVOL, VWAP distance, ATR displacement, optional breadth).
    4. Strict option-chain field validation and backward compatibility.
    """
    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    # 1. Strategy 1: Bidirectional Order Block + BOS/FVG & Directional Consistency
    def test_p1c_strategy_1_order_block_bidirectional_and_levels(self):
        bull_candles = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5, pattern="order_block_bull")
        sig_bull = evaluate_order_block_fvg("RELIANCE", bull_candles)
        self.assertIsNotNone(sig_bull)
        self.assertEqual(sig_bull.direction, "BULLISH (BUY)")
        self.assertEqual(sig_bull.position_type, "LONG_EQUITY_INTRADAY")
        self.assertLess(sig_bull.stop_loss, sig_bull.invalidation_level)
        self.assertEqual(sig_bull.invalidation_level, sig_bull.entry_zone_low)
        self.assertLessEqual(sig_bull.entry_zone_low, sig_bull.entry_zone_high)
        self.assertLess(sig_bull.stop_loss, sig_bull.entry_price)
        self.assertGreater(sig_bull.target_1, sig_bull.entry_price)
        self.assertGreater(sig_bull.target_2, sig_bull.target_1)

        bear_candles = self.sim.get_intraday_candles({"symbol": "BAJFINANCE"}, interval_min=5, pattern="order_block_bear")
        sig_bear = evaluate_order_block_fvg("BAJFINANCE", bear_candles)
        self.assertIsNotNone(sig_bear)
        self.assertEqual(sig_bear.direction, "BEARISH (SELL)")
        self.assertEqual(sig_bear.position_type, "SHORT_EQUITY_INTRADAY")
        self.assertGreater(sig_bear.stop_loss, sig_bear.invalidation_level)
        self.assertEqual(sig_bear.invalidation_level, sig_bear.entry_zone_high)
        self.assertLessEqual(sig_bear.entry_zone_low, sig_bear.entry_zone_high)
        self.assertGreater(sig_bear.stop_loss, sig_bear.entry_price)
        self.assertLess(sig_bear.target_1, sig_bear.entry_price)
        self.assertLess(sig_bear.target_2, sig_bear.target_1)

        # F&O segment position_type check
        sig_bear_fo = evaluate_order_block_fvg("BANKNIFTY", bear_candles, segment="NSE_FO_INDEX", lot_size=30, capital_inr=500000)
        self.assertIsNotNone(sig_bear_fo)
        self.assertEqual(sig_bear_fo.position_type, "SHORT_INDEX_FUTURE")
        self.assertEqual(sig_bear_fo.instrument_label, "BANKNIFTY FUT")

        # Non-triggering condition: if last candle does not reach the bearish OB zone
        no_touch = [dict(c) for c in bear_candles]
        no_touch[-1]["high"] = no_touch[-1]["open"]
        self.assertIsNone(evaluate_order_block_fvg("BAJFINANCE", no_touch))

    # 2. Task 2: Order Block Mitigation, First Retest, Invalidation & Duplicate Prevention
    def test_p1c_order_block_mitigation_first_retest_and_invalidation(self):
        # --- A. Bullish Order Block Mitigation & Invalidation ---
        bull_candles = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5, pattern="order_block_bull")
        mitigated_set = set()
        sig_first_bull = evaluate_order_block_fvg("RELIANCE", bull_candles, mitigated_zones=mitigated_set)
        self.assertIsNotNone(sig_first_bull, "First unmitigated bullish OB retest must trigger")
        self.assertEqual(len(mitigated_set), 1)

        # Stateful duplicate prevention: calling again with same mitigated_set blocks duplicate signal
        self.assertIsNone(evaluate_order_block_fvg("RELIANCE", bull_candles, mitigated_zones=mitigated_set))

        # Stateless candle-history mitigation: append a subsequent 10:35 candle that retests the exact same zone
        second_retest_bull = [dict(c) for c in bull_candles] + [{
            "timestamp": "2026-10-16 10:35:00",
            "open": bull_candles[-1]["close"],
            "high": bull_candles[-1]["high"],
            "low": bull_candles[-1]["low"],
            "close": bull_candles[-1]["close"],
            "volume": 190000,
            "is_complete": True,
            "is_simulated": True,
        }]
        self.assertIsNone(
            evaluate_order_block_fvg("RELIANCE", second_retest_bull),
            "Second retest of an already-mitigated bullish Order Block must not trigger a duplicate signal",
        )

        # Bullish zone invalidation: if an intermediate post-impulse bar closes below zone_low
        invalidated_bull = [dict(c) for c in bull_candles]
        zone_low_bull = sig_first_bull.entry_zone_low
        invalidated_bull[-3]["close"] = round(zone_low_bull - 5.0, 2)
        invalidated_bull[-3]["low"] = round(zone_low_bull - 6.0, 2)
        self.assertIsNone(
            evaluate_order_block_fvg("RELIANCE", invalidated_bull),
            "Bullish Order Block must be invalidated once a post-impulse candle closes below zone_low",
        )

        # --- B. Bearish Order Block Mitigation & Invalidation ---
        bear_candles = self.sim.get_intraday_candles({"symbol": "BAJFINANCE"}, interval_min=5, pattern="order_block_bear")
        bear_mitigated_set = set()
        sig_first_bear = evaluate_order_block_fvg("BAJFINANCE", bear_candles, mitigated_zones=bear_mitigated_set)
        self.assertIsNotNone(sig_first_bear, "First unmitigated bearish OB retest must trigger")
        self.assertEqual(len(bear_mitigated_set), 1)

        # Stateful duplicate prevention
        self.assertIsNone(evaluate_order_block_fvg("BAJFINANCE", bear_candles, mitigated_zones=bear_mitigated_set))

        # Stateless candle-history mitigation: append a subsequent 10:35 candle that retests the same bearish zone
        second_retest_bear = [dict(c) for c in bear_candles] + [{
            "timestamp": "2026-10-16 10:35:00",
            "open": bear_candles[-1]["close"],
            "high": bear_candles[-1]["high"],
            "low": bear_candles[-1]["low"],
            "close": bear_candles[-1]["close"],
            "volume": 190000,
            "is_complete": True,
            "is_simulated": True,
        }]
        self.assertIsNone(
            evaluate_order_block_fvg("BAJFINANCE", second_retest_bear),
            "Second retest of an already-mitigated bearish Order Block must not trigger a duplicate signal",
        )

        # Bearish zone invalidation: if an intermediate post-impulse bar closes above zone_high
        invalidated_bear = [dict(c) for c in bear_candles]
        zone_high_bear = sig_first_bear.entry_zone_high
        invalidated_bear[-3]["close"] = round(zone_high_bear + 10.0, 2)
        invalidated_bear[-3]["high"] = round(zone_high_bear + 12.0, 2)
        self.assertIsNone(
            evaluate_order_block_fvg("BAJFINANCE", invalidated_bear),
            "Bearish Order Block must be invalidated once a post-impulse candle closes above zone_high",
        )

    # 3. Strategy 2: Bidirectional VWAP Pullback / Rejection & Non-Trigger Conditions
    def test_p1c_strategy_2_vwap_pullback_bidirectional_and_non_trigger(self):
        bull_candles = self.sim.get_intraday_candles({"symbol": "TCS"}, interval_min=5, pattern="vwap_pullback_bull")
        sig_bull = evaluate_vwap_pullback("TCS", bull_candles)
        self.assertIsNotNone(sig_bull)
        self.assertEqual(sig_bull.direction, "BULLISH (BUY)")
        self.assertEqual(sig_bull.position_type, "LONG_EQUITY_INTRADAY")
        self.assertLess(sig_bull.stop_loss, sig_bull.entry_price)
        self.assertGreater(sig_bull.target_1, sig_bull.entry_price)

        bear_candles = self.sim.get_intraday_candles({"symbol": "INFY"}, interval_min=5, pattern="vwap_pullback_bear")
        sig_bear = evaluate_vwap_pullback("INFY", bear_candles)
        self.assertIsNotNone(sig_bear)
        self.assertEqual(sig_bear.direction, "BEARISH (SELL)")
        self.assertEqual(sig_bear.position_type, "SHORT_EQUITY_INTRADAY")
        self.assertGreater(sig_bear.stop_loss, sig_bear.entry_price)
        self.assertLess(sig_bear.target_1, sig_bear.entry_price)
        self.assertLess(sig_bear.target_2, sig_bear.target_1)

        # Non-triggering: insufficient volume (< 1.4x 20-bar average)
        low_vol_bear = [dict(c) for c in bear_candles]
        low_vol_bear[-1]["volume"] = 25000
        self.assertIsNone(evaluate_vwap_pullback("INFY", low_vol_bear))

        # Non-triggering: green candle (close > open) cannot trigger bearish rejection
        green_bar_bear = [dict(c) for c in bear_candles]
        green_bar_bear[-1]["open"] = green_bar_bear[-1]["low"]
        self.assertIsNone(evaluate_vwap_pullback("INFY", green_bar_bear))

    # 4. Strategy 3: Bidirectional Option Apex OI Shift (BUY CE & BUY PE) + Strict Field Validation
    def test_p1c_strategy_3_option_apex_bidirectional_and_strict_field_validation(self):
        from strategies import validate_option_chain_for_strategy

        # Bullish BUY CE
        bull_candles = self.sim.get_intraday_candles({"symbol": "NIFTY"}, interval_min=5, pattern="vwap_pullback_bull")
        oc_bull = self.sim.get_option_chain("NIFTY", bias="BULLISH")
        sig_ce = evaluate_option_apex_oi_shift("NIFTY", bull_candles, oc_bull, lot_size=75, capital_inr=500000)
        self.assertIsNotNone(sig_ce)
        self.assertEqual(sig_ce.direction, "BULLISH (BUY CE)")
        self.assertEqual(sig_ce.position_type, "LONG_CALL_OPTION")
        self.assertIn("CE", sig_ce.instrument_label)
        self.assertLess(sig_ce.stop_loss, sig_ce.entry_price)
        self.assertGreater(sig_ce.target_1, sig_ce.entry_price)

        # Bearish BUY PE on NIFTY and BANKNIFTY
        bear_candles = self.sim.get_intraday_candles({"symbol": "BANKNIFTY"}, interval_min=5, pattern="vwap_pullback_bear")
        oc_bear = self.sim.get_option_chain("BANKNIFTY", bias="BEARISH")
        sig_pe = evaluate_option_apex_oi_shift("BANKNIFTY", bear_candles, oc_bear, lot_size=30, capital_inr=500000)
        self.assertIsNotNone(sig_pe)
        self.assertEqual(sig_pe.direction, "BEARISH (BUY PE)")
        self.assertEqual(sig_pe.position_type, "LONG_PUT_OPTION")
        self.assertIn("BANKNIFTY", sig_pe.instrument_label)
        self.assertIn("PE", sig_pe.instrument_label)
        # Long Put option premium has stop_loss < entry_price < target_1 < target_2
        self.assertLess(sig_pe.stop_loss, sig_pe.entry_price)
        self.assertGreater(sig_pe.target_1, sig_pe.entry_price)
        self.assertGreater(sig_pe.target_2, sig_pe.target_1)

        # Non-triggering: Bearish OI shift but PCR > 0.85 (e.g., PCR = 0.96)
        oc_high_pcr = dict(oc_bear, pcr=0.96)
        self.assertIsNone(evaluate_option_apex_oi_shift("BANKNIFTY", bear_candles, oc_high_pcr, lot_size=30, capital_inr=500000))

        # Non-triggering: Bearish option chain paired with bullish candles way above VWAP
        self.assertIsNone(evaluate_option_apex_oi_shift("NIFTY", bull_candles, self.sim.get_option_chain("NIFTY", bias="BEARISH"), lot_size=75, capital_inr=500000))

        # Strict option-chain field validation: missing or None OI fields must raise ValueError (never default to 0)
        for missing_top in ("pcr", "atm_strike", "strikes"):
            bad_top = dict(oc_bull)
            del bad_top[missing_top]
            with self.assertRaises(ValueError):
                evaluate_option_apex_oi_shift("NIFTY", bull_candles, bad_top, lot_size=75, capital_inr=500000)

        for missing_strike_field in ("ce_ltp", "pe_ltp", "ce_oi", "pe_oi", "ce_oi_change", "pe_oi_change"):
            bad_oc = json.loads(json.dumps(oc_bull))
            for s in bad_oc["strikes"]:
                if s["strike"] == bad_oc["atm_strike"]:
                    del s[missing_strike_field]
            with self.assertRaises(ValueError, msg=f"Missing {missing_strike_field} must raise ValueError"):
                validate_option_chain_for_strategy(bad_oc)
            with self.assertRaises(ValueError):
                evaluate_option_apex_oi_shift("NIFTY", bull_candles, bad_oc, lot_size=75, capital_inr=500000)

    # 5. Strategy 4: Bidirectional 15m ORB Breakout / Breakdown & Non-Trigger Conditions
    def test_p1c_strategy_4_orb_bidirectional_and_non_trigger(self):
        bull_candles = self.sim.get_intraday_candles({"symbol": "ICICIBANK"}, interval_min=5, pattern="orb_breakout_bull")
        sig_bull = evaluate_orb_breakout("ICICIBANK", bull_candles)
        self.assertIsNotNone(sig_bull)
        self.assertEqual(sig_bull.direction, "BULLISH (BUY)")
        self.assertEqual(sig_bull.position_type, "LONG_EQUITY_INTRADAY")
        self.assertLess(sig_bull.stop_loss, sig_bull.entry_price)
        self.assertGreater(sig_bull.target_1, sig_bull.entry_price)

        bear_candles = self.sim.get_intraday_candles({"symbol": "AXISBANK"}, interval_min=5, pattern="orb_breakout_bear")
        sig_bear = evaluate_orb_breakout("AXISBANK", bear_candles)
        self.assertIsNotNone(sig_bear)
        self.assertEqual(sig_bear.direction, "BEARISH (SELL)")
        self.assertEqual(sig_bear.position_type, "SHORT_EQUITY_INTRADAY")
        self.assertGreater(sig_bear.stop_loss, sig_bear.entry_price)
        self.assertLess(sig_bear.target_1, sig_bear.entry_price)
        self.assertLess(sig_bear.target_2, sig_bear.target_1)

        # Non-triggering: if previous bar already closed below ORB low (not a fresh breakdown)
        stale_breakdown = [dict(c) for c in bear_candles]
        stale_breakdown[-2]["close"] = stale_breakdown[-1]["close"]
        stale_breakdown[-2]["low"] = stale_breakdown[-1]["low"]
        self.assertIsNone(evaluate_orb_breakout("AXISBANK", stale_breakdown))

        # Non-triggering: RVOL < 1.6
        low_rvol = [dict(c) for c in bear_candles]
        low_rvol[-1]["volume"] = 50000
        self.assertIsNone(evaluate_orb_breakout("AXISBANK", low_rvol))

    # 6. Strategy 5: Bidirectional Supertrend(10,3) Pullback + 200 EMA & Non-Trigger Conditions
    def test_p1c_strategy_5_supertrend_bidirectional_and_non_trigger(self):
        bull_candles = self.sim.get_intraday_candles({"symbol": "SBIN"}, interval_min=5, pattern="supertrend_pullback_bull")
        sig_bull = evaluate_supertrend_pullback("SBIN", bull_candles)
        self.assertIsNotNone(sig_bull)
        self.assertEqual(sig_bull.direction, "BULLISH (BUY)")
        self.assertEqual(sig_bull.position_type, "LONG_EQUITY_INTRADAY")

        bear_candles = self.sim.get_intraday_candles({"symbol": "TATAMOTORS"}, interval_min=5, pattern="supertrend_pullback_bear")
        sig_bear = evaluate_supertrend_pullback("TATAMOTORS", bear_candles)
        self.assertIsNotNone(sig_bear)
        self.assertEqual(sig_bear.direction, "BEARISH (SELL)")
        self.assertEqual(sig_bear.position_type, "SHORT_EQUITY_INTRADAY")
        self.assertGreater(sig_bear.stop_loss, sig_bear.entry_price)
        self.assertLess(sig_bear.target_1, sig_bear.entry_price)
        self.assertLess(sig_bear.target_2, sig_bear.target_1)

        # Non-triggering: Bearish Supertrend pullback during 11:30–13:30 chop window must be blocked
        chop_bear = [dict(c) for c in bear_candles]
        chop_bear[-1]["timestamp"] = "2026-10-16 12:15:00"
        self.assertIsNone(evaluate_supertrend_pullback("TATAMOTORS", chop_bear))

        # Non-triggering: Bearish Supertrend pullback during 09:15–09:45 opening window must be blocked
        open_bear = [dict(c) for c in bear_candles]
        open_bear[-1]["timestamp"] = "2026-10-16 09:30:00"
        # Adjust timestamps of earlier session bars or slice to keep chronological order
        with self.assertRaises(ValueError):
            # Out-of-order timestamp rejected by validate_candles
            evaluate_supertrend_pullback("TATAMOTORS", open_bear)

    # 7. Task 3: Setup-Quality Score Reproducibility, Boundary Values & Missing-Feature Handling
    def test_p1c_setup_quality_score_reproducibility_boundaries_and_missing_breadth(self):
        from strategies import compute_setup_quality_score

        # 1) Exact reproducibility for identical inputs
        s1, b1 = compute_setup_quality_score(rvol=1.95, vwap_dist_atr=0.45, displacement_atr=1.40, market_breadth=None, is_bullish=True)
        s2, b2 = compute_setup_quality_score(rvol=1.95, vwap_dist_atr=0.45, displacement_atr=1.40, market_breadth=None, is_bullish=True)
        self.assertEqual(s1, s2)
        self.assertEqual(b1, b2)
        self.assertFalse(b1["breadth_available"])
        self.assertIsNone(b1["features_normalized"]["market_breadth"])
        self.assertEqual(b1["effective_weights"]["market_breadth"], 0.0)
        self.assertAlmostEqual(
            b1["effective_weights"]["rvol"] + b1["effective_weights"]["vwap_alignment"] + b1["effective_weights"]["atr_displacement"],
            1.0,
            places=3,
        )

        # 2) Lower boundary (0) and upper boundary (100)
        low_score, _ = compute_setup_quality_score(rvol=0.50, vwap_dist_atr=-0.50, displacement_atr=0.0, market_breadth={"advances": 10, "declines": 90}, is_bullish=True)
        self.assertEqual(low_score, 0)

        high_score, high_bd = compute_setup_quality_score(rvol=3.00, vwap_dist_atr=0.50, displacement_atr=2.50, market_breadth={"advances": 85, "declines": 15}, is_bullish=True)
        self.assertEqual(high_score, 100)
        self.assertTrue(high_bd["breadth_available"])
        self.assertEqual(high_bd["features_normalized"]["market_breadth"], 1.0)

        # 3) Directional breadth alignment symmetry
        bull_with_bull_breadth, _ = compute_setup_quality_score(rvol=1.8, vwap_dist_atr=0.4, displacement_atr=1.2, market_breadth={"advances": 15, "declines": 2}, is_bullish=True)
        bull_with_bear_breadth, _ = compute_setup_quality_score(rvol=1.8, vwap_dist_atr=0.4, displacement_atr=1.2, market_breadth={"advances": 2, "declines": 15}, is_bullish=True)
        self.assertGreater(bull_with_bull_breadth, bull_with_bear_breadth)

        bear_with_bear_breadth, _ = compute_setup_quality_score(rvol=1.8, vwap_dist_atr=0.4, displacement_atr=1.2, market_breadth={"advances": 2, "declines": 15}, is_bullish=False)
        bear_with_bull_breadth, _ = compute_setup_quality_score(rvol=1.8, vwap_dist_atr=0.4, displacement_atr=1.2, market_breadth={"advances": 15, "declines": 2}, is_bullish=False)
        self.assertGreater(bear_with_bear_breadth, bear_with_bull_breadth)
        self.assertEqual(bull_with_bull_breadth, bear_with_bear_breadth)

        # 4) Invalid/malformed inputs rejected explicitly
        with self.assertRaises(ValueError):
            compute_setup_quality_score(rvol=None, vwap_dist_atr=None, displacement_atr=None, market_breadth=None)
        with self.assertRaises(ValueError):
            compute_setup_quality_score(rvol=float("nan"), vwap_dist_atr=0.5, displacement_atr=1.0)
        with self.assertRaises(ValueError):
            compute_setup_quality_score(rvol=-1.0, vwap_dist_atr=0.5, displacement_atr=1.0)
        with self.assertRaises(ValueError):
            compute_setup_quality_score(rvol=1.8, vwap_dist_atr=0.5, displacement_atr=1.0, market_breadth={"advances": 10})

    # 8. Backward Compatibility of Signal Serialization & Scanner Bidirectional Execution
    def test_p1c_backward_compatibility_and_scanner_bidirectional_dispatch(self):
        cfg = BotConfig(active_broker="paper_sim", account_capital_inr=500000, telegram_dry_run=True)
        scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
        scanner.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
        engine = IntradayBotEngine(cfg, clock=self.fixed_clock, broker_scanner=scanner)

        res1 = engine.run_single_scan()
        self.assertEqual(res1["status"], "ok")
        self.assertIsNotNone(res1["market_breadth"])
        self.assertIn("advances", res1["market_breadth"])
        self.assertIn("declines", res1["market_breadth"])

        directions = {s["direction"] for s in res1["signals"]}
        self.assertIn("BULLISH (BUY)", directions)
        self.assertIn("BEARISH (SELL)", directions)
        self.assertIn("BULLISH (BUY CE)", directions)
        self.assertIn("BEARISH (BUY PE)", directions)

        # Verify all legacy Phase 1A/1B keys and new Phase 1C keys exist on serialized signals
        required_keys = {
            "symbol", "segment", "strategy_id", "strategy_name", "direction",
            "instrument_label", "entry_price", "entry_zone_low", "entry_zone_high",
            "stop_loss", "target_1", "target_2", "risk_reward", "confidence_pct",
            "win_rate_benchmark", "position_qty", "capital_risk_inr", "est_charges_inr",
            "rationale", "timestamp", "is_simulated", "data_mode",
            "position_type", "invalidation_level", "quality_score", "score_breakdown",
        }
        for s_dict in res1["signals"]:
            self.assertTrue(required_keys.issubset(s_dict.keys()))
            self.assertEqual(s_dict["confidence_pct"], s_dict["quality_score"])
            self.assertGreaterEqual(s_dict["quality_score"], 0)
            self.assertLessEqual(s_dict["quality_score"], 100)
            self.assertTrue(s_dict["score_breakdown"]["breadth_available"])

        # Running a second scan on the same engine instance must not re-emit already-mitigated Order Blocks
        ob_count_scan1 = sum(1 for s in res1["signals"] if s["strategy_id"] == "strat_1_order_block")
        self.assertGreaterEqual(ob_count_scan1, 2)
        res2 = engine.run_single_scan()
        ob_count_scan2 = sum(1 for s in res2["signals"] if s["strategy_id"] == "strat_1_order_block")
        self.assertEqual(ob_count_scan2, 0, "Mitigated Order Blocks must not re-trigger on subsequent scan in same engine instance")



class TestIndianFOSignalBotPhase1D(unittest.TestCase):
    """
    Phase 1D Backend Operational Readiness Test Suite:
    Covers SQLite persistence across restarts, signal deduplication, OI snapshot history & diffs,
    invalid snapshot rejection, REST API contracts & parameter validation, empty vs failed scans,
    scan overlap prevention, scheduler session/weekend/holiday boundaries, DB error surfacing,
    broker status separation, config validation, and Windows cp1252 console encoding.
    """
    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    # 1. Database Initialization & Persistence Across Application Restarts
    def test_p1d_database_init_and_persistence_across_restarts(self):
        import tempfile
        from storage import SQLitePersistenceStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "tradepulse_restart_test.db")
            db_url = f"sqlite:///{db_file}"

            # --- Process / Instance 1 ---
            cfg1 = BotConfig(active_broker="paper_sim", telegram_dry_run=True, database_url=db_url)
            scanner1 = MultiBrokerScanner(cfg1, clock=self.fixed_clock)
            scanner1.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
            engine1 = IntradayBotEngine(cfg1, clock=self.fixed_clock, broker_scanner=scanner1)

            res1 = engine1.run_single_scan()
            self.assertEqual(res1["status"], "ok")
            self.assertEqual(res1["scan_status"], "COMPLETED")
            self.assertEqual(res1["persistence_status"], "OK")
            self.assertGreater(res1["persisted_signals"], 0)
            self.assertEqual(res1["duplicate_signals"], 0)
            self.assertEqual(res1["oi_snapshots_saved"], 2)  # NIFTY and BANKNIFTY
            first_run_signal_count = res1["persisted_signals"]

            # Destroy engine1 and instantiate a brand-new engine2 pointing to the same SQLite file
            del engine1

            # --- Process / Instance 2 (Simulated Restart) ---
            cfg2 = BotConfig(active_broker="paper_sim", telegram_dry_run=True, database_url=db_url)
            scanner2 = MultiBrokerScanner(cfg2, clock=self.fixed_clock)
            scanner2.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
            engine2 = IntradayBotEngine(cfg2, clock=self.fixed_clock, broker_scanner=scanner2)

            # Verify mitigated Order Blocks were restored from SQLite on startup
            self.assertGreaterEqual(len(engine2.mitigated_order_blocks), 2)

            # Verify historical signals, scan runs, and OI snapshots persisted across restart
            health = engine2.store.check_health()
            self.assertEqual(health["status"], "OK")
            self.assertEqual(health["signals_count"], first_run_signal_count)
            self.assertEqual(health["scan_runs_count"], 1)
            self.assertEqual(health["oi_snapshots_count"], 2)

            # Running the identical scan after restart must deduplicate signals and skip Telegram re-sends
            res2 = engine2.run_single_scan()
            self.assertEqual(res2["persisted_signals"], 0)
            self.assertEqual(res2["duplicate_signals"], res2["total_signals"])
            for td in res2["telegram_dispatches"]:
                self.assertTrue(td.get("skipped"))

    # 2. Signal Deduplication Key & Validation
    def test_p1d_signal_deduplication_and_validation(self):
        from storage import SQLitePersistenceStore, PersistenceValidationError, compute_signal_dedup_key

        store = SQLitePersistenceStore(":memory:")
        candles = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5, pattern="order_block_bull")
        sig = evaluate_order_block_fvg("RELIANCE", candles)
        self.assertIsNotNone(sig)

        inserted1, key1 = store.save_signal(sig, broker="SIMULATED", scan_run_id="run_1")
        self.assertTrue(inserted1)
        self.assertEqual(key1, compute_signal_dedup_key(sig, broker="SIMULATED"))

        # Second insert of identical signal must return False without duplicating row
        inserted2, key2 = store.save_signal(sig, broker="SIMULATED", scan_run_id="run_2")
        self.assertFalse(inserted2)
        self.assertEqual(key1, key2)
        self.assertEqual(store.query_signals()["total_count"], 1)

        # Invalid signal fields must raise PersistenceValidationError
        bad_sig = TradeSignal(**dict(sig.to_dict(), entry_price=-10.0))
        with self.assertRaises(PersistenceValidationError):
            store.save_signal(bad_sig, broker="SIMULATED")

    # 3. OI Snapshot Persistence, Rolling Intraday Diffs, Stale/Mode Isolation & Invalid Rejection
    def test_p1d_oi_snapshot_persistence_rolling_intraday_diff_and_invalid_rejection(self):
        from storage import SQLitePersistenceStore, PersistenceValidationError

        store = SQLitePersistenceStore(":memory:")
        base_oc = self.sim.get_option_chain("NIFTY", bias="BULLISH", expiry="2026-10-22")

        # 1) First snapshot at 10:25:00 IST -> NO_PRIOR_SNAPSHOT
        s1 = store.save_oi_snapshot(base_oc, "2026-10-16 10:25:00", broker="NSE Sim")
        self.assertTrue(s1["inserted"])
        self.assertEqual(s1["intraday_oi_diff"]["comparison_status"], "NO_PRIOR_SNAPSHOT")

        # Duplicate snapshot at same timestamp -> inserted=False, duplicate=True
        s1_dup = store.save_oi_snapshot(base_oc, "2026-10-16 10:25:00", broker="NSE Sim")
        self.assertFalse(s1_dup["inserted"])
        self.assertTrue(s1_dup["duplicate"])

        # 2) Second snapshot 5 minutes later at 10:30:00 IST with updated OI -> VALID_INTRADAY_DIFF
        oc2 = json.loads(json.dumps(base_oc))
        oc2["total_ce_oi"] = base_oc["total_ce_oi"] - 300000
        oc2["total_pe_oi"] = base_oc["total_pe_oi"] + 600000
        oc2["pcr"] = round(oc2["total_pe_oi"] / oc2["total_ce_oi"], 2)
        for row in oc2["strikes"]:
            if row["strike"] == oc2["atm_strike"]:
                row["ce_oi"] -= 150000
                row["pe_oi"] += 250000

        s2 = store.save_oi_snapshot(oc2, "2026-10-16 10:30:00", broker="NSE Sim")
        self.assertTrue(s2["inserted"])
        diff2 = s2["intraday_oi_diff"]
        self.assertEqual(diff2["comparison_status"], "VALID_INTRADAY_DIFF")
        self.assertEqual(diff2["elapsed_minutes"], 5.0)
        self.assertEqual(diff2["total_ce_oi_delta"], -300000)
        self.assertEqual(diff2["total_pe_oi_delta"], 600000)
        self.assertEqual(diff2["atm_ce_oi_delta"], -150000)
        self.assertEqual(diff2["atm_pe_oi_delta"], 250000)

        # 3) Live snapshot at 10:35:00 IST must NOT compare against SIMULATED snapshots
        oc_live = json.loads(json.dumps(oc2))
        oc_live["is_simulated"] = False
        oc_live["data_mode"] = "LIVE"
        s_live = store.save_oi_snapshot(oc_live, "2026-10-16 10:35:00", broker="DhanHQ API v2")
        self.assertEqual(s_live["data_mode"], "LIVE")
        self.assertEqual(s_live["intraday_oi_diff"]["comparison_status"], "NO_PRIOR_SNAPSHOT")

        # 4) Stale snapshot (> 60 minutes later at 12:00:00 IST) -> STALE_PRIOR_SNAPSHOT
        s3_stale = store.save_oi_snapshot(oc2, "2026-10-16 12:00:00", broker="NSE Sim", max_snapshot_age_minutes=60)
        self.assertEqual(s3_stale["intraday_oi_diff"]["comparison_status"], "STALE_PRIOR_SNAPSHOT")
        self.assertIsNone(s3_stale["intraday_oi_diff"]["total_ce_oi_delta"])

        # 5) Invalid snapshots rejected
        with self.assertRaises(PersistenceValidationError):
            store.save_oi_snapshot({}, "2026-10-16 10:40:00", broker="NSE Sim")
        bad_oc_no_expiry = dict(base_oc)
        del bad_oc_no_expiry["expiry"]
        with self.assertRaises(PersistenceValidationError):
            store.save_oi_snapshot(bad_oc_no_expiry, "2026-10-16 10:40:00", broker="NSE Sim")

    # 4. Empty Scan vs Failed Scan & Honest Broker Connectivity Status Separation
    def test_p1d_empty_scan_vs_failed_scan_and_broker_status_separation(self):
        # A. Empty scan (0 signals) -> status=ok, scan_status=COMPLETED_EMPTY
        cfg_sim = BotConfig(active_broker="paper_sim", telegram_dry_run=True, database_url=":memory:")
        flat_scanner = MultiBrokerScanner(cfg_sim, clock=self.fixed_clock)
        flat_scanner.adapters["paper_sim"] = _FlatCandleAdapter()
        empty_engine = IntradayBotEngine(cfg_sim, clock=self.fixed_clock, broker_scanner=flat_scanner)

        empty_res = empty_engine.run_single_scan()
        self.assertEqual(empty_res["status"], "ok")
        self.assertEqual(empty_res["scan_status"], "COMPLETED_EMPTY")
        self.assertEqual(empty_res["total_signals"], 0)
        self.assertEqual(empty_engine.get_broker_status()["connection_state"], "SIMULATED")

        scan_runs = empty_engine.store.query_scan_runs()["items"]
        self.assertEqual(len(scan_runs), 1)
        self.assertEqual(scan_runs[0]["status"], "COMPLETED_EMPTY")

        # B. Live broker with placeholder credentials -> UNAVAILABLE_MISSING_CREDENTIALS
        cfg_unavail = BotConfig(active_broker="angelone", angel_api_key="your_angel_smartapi_key", database_url=":memory:")
        eng_unavail = IntradayBotEngine(cfg_unavail, clock=self.fixed_clock)
        self.assertEqual(eng_unavail.get_broker_status()["connection_state"], "UNAVAILABLE_MISSING_CREDENTIALS")
        self.assertFalse(eng_unavail.get_broker_status()["connectivity_verified"])

        # C. Live broker with configured credentials before any fetch -> CONFIGURED_UNVERIFIED
        cfg_dhan = BotConfig(
            active_broker="dhan",
            dhan_client_id="DHAN_1001",
            dhan_access_token="SECRET_DHAN_JWT",
            database_url=":memory:",
        )
        eng_dhan = IntradayBotEngine(cfg_dhan, clock=self.fixed_clock)
        self.assertEqual(eng_dhan.get_broker_status()["connection_state"], "CONFIGURED_UNVERIFIED")
        self.assertFalse(eng_dhan.get_broker_status()["connectivity_verified"])

        # D. Failed live scan -> raises BrokerDataError, records FAILED scan run, sets broker state to ERROR
        with patch("urllib.request.urlopen", side_effect=OSError("Connection timed out")):
            with self.assertRaises(BrokerDataError):
                eng_dhan.run_single_scan()

        self.assertEqual(eng_dhan.get_broker_status()["connection_state"], "ERROR")
        self.assertFalse(eng_dhan.get_broker_status()["connectivity_verified"])
        failed_runs = eng_dhan.store.query_scan_runs(status="FAILED")["items"]
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0]["error_type"], "BrokerDataError")

    # 5. Scan Overlap Prevention
    def test_p1d_scan_overlap_prevention(self):
        cfg = BotConfig(active_broker="paper_sim", telegram_dry_run=True, database_url=":memory:")
        engine = IntradayBotEngine(cfg, clock=self.fixed_clock)

        # Acquire the scan lock to simulate an in-flight scan
        acquired = engine._scan_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            overlap_res = engine.run_single_scan()
            self.assertEqual(overlap_res["status"], "skipped")
            self.assertEqual(overlap_res["scan_status"], "SKIPPED_OVERLAP")
            self.assertEqual(overlap_res["reason"], "scan_already_in_progress")
        finally:
            engine._scan_lock.release()

        runs = engine.store.query_scan_runs(status="SKIPPED_OVERLAP")["items"]
        self.assertEqual(len(runs), 1)

    # 6. Scheduler Session Boundaries, Weekends, Holidays & Graceful Shutdown
    def test_p1d_scheduler_session_boundaries_weekends_holidays_and_lifecycle(self):
        from scanner_engine import MarketScanScheduler

        cfg = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            session_start_ist="09:15",
            session_end_ist="15:30",
            configured_holidays=["2026-10-20"],
            scan_interval_seconds=5,
            database_url=":memory:",
        )
        engine = IntradayBotEngine(cfg, clock=self.fixed_clock)

        # 1) Before 09:15 IST (09:05 IST) -> skipped
        sched_early = MarketScanScheduler(engine, clock=lambda: datetime(2026, 10, 16, 9, 5, 0, tzinfo=IST))
        is_open, reason = sched_early.is_market_session_open()
        self.assertFalse(is_open)
        self.assertEqual(reason, "before_session_open")
        res_early = sched_early.run_scheduled_cycle()
        self.assertEqual(res_early["scan_status"], "SKIPPED_OUTSIDE_SESSION")

        # 2) After 15:30 IST (15:40 IST) -> skipped
        sched_late = MarketScanScheduler(engine, clock=lambda: datetime(2026, 10, 16, 15, 40, 0, tzinfo=IST))
        self.assertEqual(sched_late.run_scheduled_cycle()["reason"], "after_session_close")

        # 3) Weekend (Saturday 2026-10-17 11:00 IST) -> skipped
        sched_wknd = MarketScanScheduler(engine, clock=lambda: datetime(2026, 10, 17, 11, 0, 0, tzinfo=IST))
        self.assertEqual(sched_wknd.run_scheduled_cycle()["reason"], "weekend")

        # 4) Configured holiday (Tuesday 2026-10-20 11:00 IST) -> skipped
        sched_hol = MarketScanScheduler(engine, clock=lambda: datetime(2026, 10, 20, 11, 0, 0, tzinfo=IST))
        self.assertEqual(sched_hol.run_scheduled_cycle()["reason"], "configured_holiday:2026-10-20")

        # 5) Active weekday session (Friday 2026-10-16 10:35 IST) -> runs scan
        sched_active = MarketScanScheduler(engine, clock=self.fixed_clock)
        res_open = sched_active.run_scheduled_cycle()
        self.assertEqual(res_open["status"], "ok")
        self.assertEqual(sched_active.cycles_executed, 1)

        # 6) Start and stop background thread cleanly
        sched_active.start()
        self.assertTrue(sched_active.get_status()["running"])
        sched_active.stop(timeout=2.0)
        self.assertFalse(sched_active.get_status()["running"])

    # 7. Database Failure Handling Surfaces Explicit Errors
    def test_p1d_database_failure_handling_surfaces_explicit_errors(self):
        from storage import PersistenceError

        cfg = BotConfig(active_broker="paper_sim", telegram_dry_run=True, database_url=":memory:")
        scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
        scanner.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
        engine = IntradayBotEngine(cfg, clock=self.fixed_clock, broker_scanner=scanner)

        with patch.object(engine.store, "save_signal", side_effect=PersistenceError("Simulated disk I/O error")):
            res = engine.run_single_scan()

        # Scan must still return signals in memory, but MUST report persistence_status == ERROR
        self.assertEqual(res["status"], "ok")
        self.assertGreater(res["total_signals"], 0)
        self.assertEqual(res["persistence_status"], "ERROR")
        self.assertIn("Simulated disk I/O error", res["persistence_error"])
        self.assertEqual(engine.last_persistence_status, "ERROR")

    # 8. HTTP API Contracts, Query Parameter Validation, Pagination & Secret Redaction
    def test_p1d_http_api_contracts_validation_pagination_and_secret_redaction(self):
        import io
        from server import DashboardRequestHandler

        cfg = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            angel_api_key="SUPER_SECRET_ANGEL_API_KEY",
            angel_pin="9876",
            angel_totp_secret="JBSWY3DPEHPK3PXP",
            dhan_client_id="DHAN_CLIENT_123",
            dhan_access_token="SUPER_SECRET_DHAN_JWT",
            upstox_access_token="SUPER_SECRET_UPSTOX_OAUTH",
            telegram_bot_token="999999:SUPER_SECRET_TG_TOKEN",
            database_url=":memory:",
        )
        scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
        scanner.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
        engine = IntradayBotEngine(cfg, clock=self.fixed_clock, broker_scanner=scanner)
        scheduler = MarketScanScheduler(engine, clock=self.fixed_clock)

        # Helper to invoke DashboardRequestHandler in-memory without opening a network socket
        def call_api(method: str, path: str) -> tuple:
            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.engine = engine
            handler.scheduler = scheduler
            handler.path = path
            handler.command = method
            handler.request_version = "HTTP/1.1"
            handler.wfile = io.BytesIO()
            status_holder = {}
            handler.send_response = lambda code, msg=None: status_holder.setdefault("code", code)
            handler.send_header = lambda k, v: None
            handler.end_headers = lambda: None
            if method == "GET":
                handler.do_GET()
            else:
                handler.do_POST()
            body = json.loads(handler.wfile.getvalue().decode("utf-8"))
            return status_holder["code"], body

        # 1) GET /api/config -> 200, must redact all secret strings
        code, cfg_body = call_api("GET", "/api/config")
        self.assertEqual(code, 200)
        raw_cfg_json = json.dumps(cfg_body)
        for secret in (
            "SUPER_SECRET_ANGEL_API_KEY",
            "JBSWY3DPEHPK3PXP",
            "SUPER_SECRET_DHAN_JWT",
            "SUPER_SECRET_UPSTOX_OAUTH",
            "SUPER_SECRET_TG_TOKEN",
        ):
            self.assertNotIn(secret, raw_cfg_json)
        self.assertTrue(cfg_body["config"]["brokers_configured"]["dhan"])

        # 2) POST /api/scan -> 200, triggers scan and persists signals + OI snapshots
        code, scan_body = call_api("POST", "/api/scan")
        self.assertEqual(code, 200)
        self.assertEqual(scan_body["scan_status"], "COMPLETED")
        self.assertGreater(scan_body["total_signals"], 5)

        # 3) GET /api/health -> 200, reports database counts and last_scan
        code, health_body = call_api("GET", "/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(health_body["status"], "ok")
        self.assertEqual(health_body["database"]["status"], "OK")
        self.assertGreater(health_body["database"]["signals_count"], 5)
        self.assertIsNotNone(health_body["last_scan"])

        # 4) GET /api/signals with pagination & filters
        code, sig_page = call_api("GET", "/api/signals?limit=3&offset=0&direction=BEARISH")
        self.assertEqual(code, 200)
        self.assertEqual(len(sig_page["items"]), 3)
        for item in sig_page["items"]:
            self.assertIn("BEARISH", item["direction"])

        # Invalid query parameters on /api/signals -> 400 Bad Request
        code_bad1, _ = call_api("GET", "/api/signals?limit=0")
        self.assertEqual(code_bad1, 400)
        code_bad2, _ = call_api("GET", "/api/signals?segment=INVALID_SEGMENT")
        self.assertEqual(code_bad2, 400)
        code_bad3, _ = call_api("GET", "/api/signals?data_mode=INVALID_MODE")
        self.assertEqual(code_bad3, 400)

        # 5) GET /api/scans -> 200
        code, scans_body = call_api("GET", "/api/scans?limit=5&status=COMPLETED")
        self.assertEqual(code, 200)
        self.assertEqual(scans_body["total_count"], 1)

        # 6) GET /api/oi-snapshots -> 200 for NIFTY, 400 for invalid symbol
        code, oi_body = call_api("GET", "/api/oi-snapshots?index_symbol=NIFTY&limit=5")
        self.assertEqual(code, 200)
        self.assertEqual(oi_body["total_count"], 1)
        self.assertEqual(oi_body["items"][0]["index_symbol"], "NIFTY")

        code_bad_oi, _ = call_api("GET", "/api/oi-snapshots?index_symbol=RELIANCE")
        self.assertEqual(code_bad_oi, 400)

        # 7) Unknown route -> 404, unsupported POST route -> 405
        code_404, _ = call_api("GET", "/api/unknown_endpoint")
        self.assertEqual(code_404, 404)
        code_405, _ = call_api("POST", "/api/orders")
        self.assertEqual(code_405, 405)

    # 9. Configuration Validation & Windows Console Encoding Safety
    def test_p1d_config_validation_and_windows_cp1252_console_encoding(self):
        import io
        from config import ConfigValidationError
        from scanner_engine import format_console_text, safe_console_print

        # 1) Config validation tests
        with self.assertRaises(ConfigValidationError):
            BotConfig(active_broker="invalid_broker").validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(account_capital_inr=-5000).validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(max_risk_per_trade_pct=0.0).validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(scan_interval_seconds=2).validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(session_start_ist="15:30", session_end_ist="09:15").validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(configured_holidays=["16-10-2026"]).validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(database_url="postgresql://localhost/db", enable_persistence=True).validate()
        with self.assertRaises(ConfigValidationError):
            BotConfig(active_broker="dhan", dhan_client_id="your_dhan_client_id").validate(require_live_credentials=True)

        # 2) Windows cp1252 and ASCII console encoding tests
        sample_line = " -> [NSE_EQUITY_INTRADAY] RELIANCE EQ | Entry: ₹2950.30 | SL: ₹2931.15 | T1: ₹2988.60"
        # UTF-8 preserves ₹
        utf8_out = format_console_text(sample_line, encoding="utf-8")
        self.assertIn("₹2950.30", utf8_out)

        # Windows cp1252 replaces ₹ with INR without crashing or losing numeric currency data
        cp1252_buf = io.BytesIO()
        cp1252_stream = io.TextIOWrapper(cp1252_buf, encoding="cp1252", errors="strict")
        written = safe_console_print(sample_line, stream=cp1252_stream)
        cp1252_stream.flush()
        decoded_cp1252 = cp1252_buf.getvalue().decode("cp1252")
        self.assertIn("INR 2950.30", decoded_cp1252)
        self.assertIn("INR 2931.15", written)


    # 10. Issue 1 Fix: Critical Static-File Disclosure Blocked Over Real HTTP Server
    def test_p1d_security_private_file_disclosure_blocked_over_real_http(self):
        import threading
        import urllib.request
        import urllib.error
        from http.server import HTTPServer
        from server import DashboardRequestHandler, configure_server_runtime
        import tempfile
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture_root = Path(directory.name)
        (fixture_root / "public").mkdir()
        for name in ("config.py", "storage.py", ".env.example", "README.md"):
            (fixture_root / name).write_text("PRIVATE_FIXTURE", encoding="utf-8")
        root_patch = patch("server.PROJECT_ROOT", str(fixture_root))
        public_patch = patch("server.PUBLIC_WEB_DIR", str(fixture_root / "public"))
        root_patch.start(); self.addCleanup(root_patch.stop)
        public_patch.start(); self.addCleanup(public_patch.stop)
        env_path = str(fixture_root / ".env")
        db_path = str(fixture_root / "tradepulse_phase1d.db")

        cfg = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            angel_api_key="CANARY_SECRET_TOKEN_987654",
            database_url=f"sqlite:///{db_path}",
            enable_background_scheduler=False,
        )
        scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
        scanner.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("ANGEL_API_KEY=CANARY_SECRET_TOKEN_987654\nTELEGRAM_BOT_TOKEN=CANARY_TG_SECRET_987654\n")

            configure_server_runtime(
                config=cfg,
                start_scheduler=False,
                clock=self.fixed_clock,
                broker_scanner=scanner,
            )
            httpd = HTTPServer(("127.0.0.1", 0), DashboardRequestHandler)
            port = httpd.server_address[1]
            srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            srv_thread.start()

            try:
                # 1) Verify legitimate API endpoints work over real HTTP
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/scan", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    scan_data = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(scan_data["status"], "ok")
                    self.assertGreater(scan_data["total_signals"], 0)

                for valid_api in (
                    "/api/health",
                    "/api/v1/health",
                    "/api/config",
                    "/api/signals?limit=3",
                    "/api/scans?limit=3",
                    "/api/oi-snapshots?index_symbol=NIFTY&limit=3",
                ):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{valid_api}", timeout=5) as resp:
                        raw_body = resp.read().decode("utf-8")
                        self.assertEqual(resp.status, 200, f"Expected 200 on {valid_api}")
                        self.assertNotIn("CANARY_SECRET_TOKEN_987654", raw_body)
                        self.assertNotIn("CANARY_TG_SECRET_987654", raw_body)

                # Confirm the SQLite DB file now exists on disk so requesting /tradepulse_phase1d.db tests a real file
                self.assertTrue(os.path.isfile(db_path))

                # 2) Verify private files, source code, database files, reports, and traversal paths return 404
                forbidden_paths = (
                    "/.env",
                    "/.env.example",
                    "/config.py",
                    "/storage.py",
                    "/brokers.py",
                    "/strategies.py",
                    "/scanner_engine.py",
                    "/server.py",
                    "/test_bot.py",
                    "/tradepulse_phase1d.db",
                    "/README.md",
                    "/docs/PHASE_1D_IMPLEMENTATION_REPORT.md",
                    "/../.env",
                    "/%2e%2e/.env",
                    "/%2e%2e/config.py",
                    "/public/../../.env",
                    "/public/%2e%2e/%2e%2e/storage.py",
                    "/..%5c.env",
                    "/..%5cconfig.py",
                )
                for bad_path in forbidden_paths:
                    with self.assertRaises(urllib.error.HTTPError, msg=f"Path {bad_path} must return HTTP 404") as ctx:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{bad_path}", timeout=5):
                            pass
                    with ctx.exception:
                        self.assertEqual(ctx.exception.code, 404, f"Expected 404 for {bad_path}, got {ctx.exception.code}")
                        err_body = ctx.exception.read().decode("utf-8", errors="replace")
                        self.assertNotIn("CANARY_SECRET_TOKEN_987654", err_body)
                        self.assertNotIn("CANARY_TG_SECRET_987654", err_body)
                        self.assertNotIn("class BotConfig", err_body)
                        self.assertNotIn("class SQLitePersistenceStore", err_body)
                        self.assertNotIn("SQLite format 3", err_body)
            finally:
                httpd.shutdown()
                httpd.server_close()
                srv_thread.join(timeout=2.0)
        finally:
            if DashboardRequestHandler.scheduler is not None:
                DashboardRequestHandler.scheduler.stop()
            if DashboardRequestHandler.engine is not None:
                DashboardRequestHandler.engine.close()

    # 11. Issue 2 Fix: Scheduler Configuration Clarity, Startup Modes & Single-Thread Idempotency
    def test_p1d_scheduler_startup_modes_health_visibility_and_single_thread_idempotency(self):
        import io
        import threading
        from server import DashboardRequestHandler, configure_server_runtime

        def get_health_payload() -> dict:
            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.path = "/api/health"
            handler.command = "GET"
            handler.request_version = "HTTP/1.1"
            handler.wfile = io.BytesIO()
            handler.send_response = lambda code, msg=None: None
            handler.send_header = lambda k, v: None
            handler.end_headers = lambda: None
            handler.do_GET()
            return json.loads(handler.wfile.getvalue().decode("utf-8"))

        try:
            # 1) Default opt-in disabled mode (enable_background_scheduler=False)
            cfg_disabled = BotConfig(
                active_broker="paper_sim",
                telegram_dry_run=True,
                database_url=":memory:",
                enable_background_scheduler=False,
            )
            _, sched_disabled = configure_server_runtime(
                config=cfg_disabled,
                start_scheduler=None,
                clock=self.fixed_clock,
            )
            self.assertFalse(sched_disabled.is_running())
            health_disabled = get_health_payload()
            self.assertFalse(health_disabled["scheduler"]["running"])
            self.assertFalse(health_disabled["scheduler"]["enabled_in_config"])

            # 2) Enabled mode (enable_background_scheduler=True) + repeated initialization idempotency
            cfg_enabled = BotConfig(
                active_broker="paper_sim",
                telegram_dry_run=True,
                scan_interval_seconds=10,
                database_url=":memory:",
                enable_background_scheduler=True,
            )
            _, sched_enabled = configure_server_runtime(
                config=cfg_enabled,
                start_scheduler=True,
                clock=self.fixed_clock,
            )
            self.assertTrue(sched_enabled.is_running())

            # Call start() and configure_server_runtime() repeatedly -> must NOT spawn duplicate threads
            for _ in range(5):
                started_new = sched_enabled.start()
                self.assertFalse(started_new, "Repeated start() on running scheduler must return False")
                configure_server_runtime(start_scheduler=True, clock=self.fixed_clock)

            sched_threads = [
                t for t in threading.enumerate()
                if t.name == "TradePulseScanScheduler" and t.is_alive()
            ]
            self.assertEqual(len(sched_threads), 1, "Must never spawn more than 1 TradePulseScanScheduler thread")

            health_enabled = get_health_payload()
            self.assertTrue(health_enabled["scheduler"]["running"])
            self.assertTrue(health_enabled["scheduler"]["enabled_in_config"])

            # 3) Disabling via configure_server_runtime(start_scheduler=False) stops the thread cleanly
            configure_server_runtime(start_scheduler=False, clock=self.fixed_clock)
            self.assertFalse(sched_enabled.is_running())
            health_stopped = get_health_payload()
            self.assertFalse(health_stopped["scheduler"]["running"])
            self.assertFalse(health_stopped["scheduler"]["enabled_in_config"])
        finally:
            if DashboardRequestHandler.scheduler is not None:
                DashboardRequestHandler.scheduler.stop()



class TestIndianFOSignalBotPhase1E(unittest.TestCase):
    """
    Phase 1E Dashboard Integration & Security Regression Test Suite:
    Verifies public/index.html serving, private-file protection, CORS headers,
    removal of obsolete setup tab and client-side secret inputs, and full
    frontend-to-backend integration across all 6 Phase 1D API endpoints.
    """
    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    # 1. Public Dashboard Served at / While Private Files & Traversal Remain Blocked
    def test_p1e_public_dashboard_served_while_private_files_remain_blocked(self):
        import threading
        import urllib.request
        import urllib.error
        from http.server import HTTPServer
        from server import DashboardRequestHandler, configure_server_runtime, PUBLIC_WEB_DIR
        import tempfile
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture_public = Path(directory.name)
        (fixture_public / "index.html").write_bytes((Path(PUBLIC_WEB_DIR) / "index.html").read_bytes())
        public_patch = patch("server.PUBLIC_WEB_DIR", str(fixture_public))
        public_patch.start()
        self.addCleanup(public_patch.stop)

        cfg = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            database_url=":memory:",
            enable_background_scheduler=False,
        )
        configure_server_runtime(config=cfg, start_scheduler=False, clock=self.fixed_clock)

        secret_dotfile = str(fixture_public / ".hidden_secret")
        disallowed_py = str(fixture_public / "leak.py")
        httpd = HTTPServer(("127.0.0.1", 0), DashboardRequestHandler)
        port = httpd.server_address[1]
        srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        srv_thread.start()

        try:
            with open(secret_dotfile, "w", encoding="utf-8") as f:
                f.write("DOTFILE_SECRET_123")
            with open(disallowed_py, "w", encoding="utf-8") as f:
                f.write("SECRET_PY_CODE = 1")

            # 1) GET /, /index.html, and /public/index.html must serve the Phase 1E dashboard HTML
            for pub_route in ("/", "/index.html", "/public/index.html"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{pub_route}", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                    html_body = resp.read().decode("utf-8")
                    self.assertIn("TradePulseApiClient", html_body)
                    self.assertIn("/api/signals", html_body)

            # 2) OPTIONS preflight on /api/scan must return 204 with CORS headers
            opt_req = urllib.request.Request(f"http://127.0.0.1:{port}/api/scan", method="OPTIONS")
            with urllib.request.urlopen(opt_req, timeout=5) as resp:
                self.assertEqual(resp.status, 204)
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods", ""))

            # 3) Private files, dotfiles inside public/, and non-allowlisted extensions inside public/ must return 404
            for forbidden in (
                "/.env",
                "/config.py",
                "/storage.py",
                "/server.py",
                "/tradepulse_phase1d.db",
                "/docs/PHASE_1D_IMPLEMENTATION_REPORT.md",
                "/public/.hidden_secret",
                "/public/leak.py",
                "/public/../.env",
                "/public/%2e%2e/config.py",
            ):
                with self.assertRaises(urllib.error.HTTPError, msg=f"{forbidden} must return 404") as ctx:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{forbidden}", timeout=5):
                        pass
                with ctx.exception:
                    self.assertEqual(ctx.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()
            srv_thread.join(timeout=2.0)
            for p in (secret_dotfile, disallowed_py):
                if os.path.exists(p):
                    os.remove(p)

    # 2. Dashboard HTML Structure, Tab 5 Removal, and Zero Client-Side Secret Inputs
    def test_p1e_dashboard_dom_and_security_contract_verification(self):
        from server import PUBLIC_WEB_DIR
        index_path = os.path.join(PUBLIC_WEB_DIR, "index.html")
        self.assertTrue(os.path.isfile(index_path), "public/index.html must exist")
        with open(index_path, "r", encoding="utf-8") as f:
            html_src = f.read()

        # 1) Obsolete Gemini/Antigravity setup tab and its dedicated handlers must be removed
        self.assertNotIn('id="tab-antigravity"', html_src)
        self.assertNotIn('data-tab="tab-antigravity"', html_src)
        self.assertNotIn("btnCopyCliCmd", html_src)
        self.assertNotIn("btnCopyAiStudioPrompt", html_src)

        # 2) Insecure client-side secret inputs and browser-side Telegram bot URL calls must be removed
        for forbidden_secret_ui in (
            'id="brokerApiKey"',
            'id="brokerAccessToken"',
            'id="tgBotToken"',
            'id="tgChatId"',
            "api.telegram.org/bot",
            "INITIAL_SIGNALS",
            "OPTION_CHAIN_DATA",
        ):
            self.assertNotIn(forbidden_secret_ui, html_src, f"Forbidden legacy token/mock {forbidden_secret_ui} found in HTML")

        # 3) All 4 preserved tabs and Phase 1D API endpoints must be present
        for required_token in (
            'id="tab-terminal"',
            'id="tab-option-apex"',
            'id="tab-strategies"',
            'id="tab-brokers-telegram"',
            'id="btnRefreshDashboard"',
            'id="btnRunLiveScan"',
            "/api/health",
            "/api/config",
            "/api/signals",
            "/api/scans",
            "/api/oi-snapshots",
            "/api/scan",
        ):
            self.assertIn(required_token, html_src)

    # 3. End-to-End API Integration: Refresh Without Scan, Manual Scan, Overlap, Empty/Error States & XSS Safety
    def test_p1e_api_dashboard_workflows_and_xss_safe_payloads(self):
        import threading
        import urllib.request
        import urllib.error
        from http.server import HTTPServer
        from server import DashboardRequestHandler, configure_server_runtime

        cfg = BotConfig(
            active_broker="paper_sim", account_capital_inr=500000,
            telegram_dry_run=True,
            database_url=":memory:",
            enable_background_scheduler=False,
        )
        scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
        scanner.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
        engine, scheduler = configure_server_runtime(
            config=cfg,
            start_scheduler=False,
            clock=self.fixed_clock,
            broker_scanner=scanner,
        )

        httpd = HTTPServer(("127.0.0.1", 0), DashboardRequestHandler)
        port = httpd.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        srv_thread.start()

        def get_json(path: str) -> dict:
            with urllib.request.urlopen(base_url + path, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))

        def post_json(path: str) -> dict:
            req = urllib.request.Request(base_url + path, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))

        try:
            # A. Initial Read-Only Refresh (Before Any Scan): 0 signals, 0 scans, 0 OI snapshots
            #    Refreshing dashboard endpoints must NOT trigger a scan!
            h0 = get_json("/api/health")
            c0 = get_json("/api/config")
            sigs0 = get_json("/api/signals?limit=20&offset=0")
            scans0 = get_json("/api/scans?limit=15&offset=0")
            oi0 = get_json("/api/oi-snapshots?index_symbol=NIFTY&limit=20&offset=0")

            self.assertEqual(h0["broker"]["connection_state"], "SIMULATED")
            self.assertFalse(h0["broker"]["connectivity_verified"])
            self.assertFalse(h0["scheduler"]["running"])
            self.assertFalse(c0["config"]["enable_background_scheduler"])
            self.assertEqual(sigs0["total_count"], 0)
            self.assertEqual(sigs0["items"], [])
            self.assertEqual(scans0["total_count"], 0)
            self.assertEqual(oi0["total_count"], 0)

            # B. Manual Scan Action (POST /api/scan) -> Populates Signals, Scan History & OI Snapshots
            scan_res = post_json("/api/scan")
            self.assertEqual(scan_res["scan_status"], "COMPLETED")
            self.assertGreater(scan_res["total_signals"], 5)

            # C. Signal Pagination & Filtering (GET /api/signals)
            sigs_p1 = get_json("/api/signals?limit=4&offset=0")
            sigs_p2 = get_json("/api/signals?limit=4&offset=4")
            self.assertEqual(len(sigs_p1["items"]), 4)
            self.assertEqual(len(sigs_p2["items"]), 4)
            self.assertNotEqual(sigs_p1["items"][0]["dedup_key"], sigs_p2["items"][0]["dedup_key"])

            bear_fo = get_json("/api/signals?segment=NSE_FO_INDEX&direction=BEARISH&data_mode=SIMULATED")
            self.assertGreaterEqual(bear_fo["total_count"], 1)
            for item in bear_fo["items"]:
                self.assertEqual(item["segment"], "NSE_FO_INDEX")
                self.assertIn("BEARISH", item["direction"])
                self.assertEqual(item["data_mode"], "SIMULATED")

            # D. OI Snapshot History (GET /api/oi-snapshots)
            oi_nifty = get_json("/api/oi-snapshots?index_symbol=NIFTY&data_mode=SIMULATED")
            self.assertEqual(oi_nifty["total_count"], 1)
            snap = oi_nifty["items"][0]
            self.assertEqual(snap["index_symbol"], "NIFTY")
            self.assertEqual(snap["intraday_oi_diff"]["comparison_status"], "NO_PRIOR_SNAPSHOT")
            self.assertGreater(len(snap["strikes"]), 0)

            # E. Scan Overlap Handling (HTTP 409 on POST /api/scan)
            engine._scan_lock.acquire(blocking=False)
            try:
                req_overlap = urllib.request.Request(base_url + "/api/scan", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    with urllib.request.urlopen(req_overlap, timeout=5):
                        pass
                with ctx.exception:
                    self.assertEqual(ctx.exception.code, 409)
                    overlap_payload = json.loads(ctx.exception.read().decode("utf-8"))
                    self.assertEqual(overlap_payload["scan_status"], "SKIPPED_OVERLAP")
            finally:
                engine._scan_lock.release()

            # F. Malicious String Persistence & Safe JSON Round-Trip (For Frontend textContent Rendering)
            xss_sig = TradeSignal(
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                strategy_id="strat_1_order_block",
                strategy_name="<script>window.__xss_strat=1</script>",
                direction="BULLISH (BUY)",
                instrument_label="<img src=x onerror=alert(1)> RELIANCE EQ",
                entry_price=2950.0,
                entry_zone_low=2940.0,
                entry_zone_high=2950.0,
                stop_loss=2925.0,
                target_1=3000.0,
                target_2=3025.0,
                risk_reward="1:2.0 / 1:3.0",
                confidence_pct=85,
                win_rate_benchmark="58%-64%",
                position_qty=60,
                capital_risk_inr=1500.0,
                est_charges_inr=110.0,
                rationale="<svg onload=alert(2)>Tested OB zone",
                timestamp="2026-10-16 11:00:00",
                is_simulated=True,
                data_mode="SIMULATED",
                quality_score=85,
                score_breakdown={},  # Missing optional breakdown subfields
            )
            engine.store.save_signal(xss_sig, broker="SIMULATED", scan_run_id="scan_xss_test")
            xss_query = get_json("/api/signals?symbol=RELIANCE&limit=5")
            matching_xss = [s for s in xss_query["items"] if s["timestamp"] == "2026-10-16 11:00:00"]
            self.assertEqual(len(matching_xss), 1)
            self.assertEqual(matching_xss[0]["instrument_label"], "<img src=x onerror=alert(1)> RELIANCE EQ")
            self.assertEqual(matching_xss[0]["score_breakdown"], {})
        finally:
            httpd.shutdown()
            httpd.server_close()
            srv_thread.join(timeout=2.0)



class TestIndianFOSignalBotPhase1F(unittest.TestCase):
    """
    Phase 1F Regression & Concurrency Test Suite:
    - Verifies server.py uses ThreadingHTTPServer (never single-threaded HTTPServer)
      and DashboardRequestHandler inherits from BaseHTTPRequestHandler (never SimpleHTTPRequestHandler).
    - Reproduces concurrent browser Promise.all() bursts across /api/health, /api/config,
      /api/signals, /api/scans, /api/oi-snapshots, and / on both :memory: and file-backed SQLite.
    - Verifies concurrent GET requests complete rapidly while a slow POST /api/scan is active,
      and overlapping POST /api/scan returns HTTP 409 SKIPPED_OVERLAP without deadlocking SQLite.
    - Confirms private-file disclosure (.env, .py, .db, docs, traversal) remains strictly blocked (HTTP 404).
    """

    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.cfg = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            database_url=":memory:",
            enable_background_scheduler=False,
        )
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    def test_p1f_server_uses_threading_http_server_and_base_request_handler(self):
        import inspect
        from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
        import server as server_mod
        from server import DashboardRequestHandler, TradePulseThreadingHTTPServer, create_http_server, run_server

        self.assertTrue(issubclass(DashboardRequestHandler, BaseHTTPRequestHandler))
        self.assertFalse(
            issubclass(DashboardRequestHandler, SimpleHTTPRequestHandler),
            "DashboardRequestHandler must NEVER inherit from SimpleHTTPRequestHandler",
        )
        self.assertTrue(issubclass(TradePulseThreadingHTTPServer, ThreadingHTTPServer))
        self.assertTrue(ThreadingHTTPServer.daemon_threads)
        self.assertGreaterEqual(ThreadingHTTPServer.request_queue_size, 64)

        run_server_src = inspect.getsource(run_server)
        self.assertIn("ThreadingHTTPServer", run_server_src)

        httpd = create_http_server("127.0.0.1", 0)
        try:
            self.assertIsInstance(httpd, ThreadingHTTPServer)
            self.assertTrue(httpd.daemon_threads)
            self.assertGreaterEqual(httpd.request_queue_size, 64)
        finally:
            httpd.server_close()

    def test_p1f_concurrent_promise_all_burst_across_all_dashboard_endpoints(self):
        import tempfile
        import threading
        import time
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from server import configure_server_runtime, create_http_server

        # Test against both in-memory SQLite (:memory:) and a file-backed SQLite database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_urls = [
                ":memory:",
                f"sqlite:///{os.path.join(tmpdir, 'tradepulse_concurrent.db')}",
            ]
            for db_url in db_urls:
                cfg = BotConfig(
                    active_broker="paper_sim",
                    telegram_dry_run=True,
                    database_url=db_url,
                    enable_background_scheduler=False,
                )
                scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
                scanner.adapters["paper_sim"] = _BidirectionalFixtureAdapter(self.sim)
                engine, _ = configure_server_runtime(
                    config=cfg,
                    start_scheduler=False,
                    clock=self.fixed_clock,
                    broker_scanner=scanner,
                )
                # Seed initial scan data so all endpoints return populated records
                initial_scan = engine.run_single_scan()
                self.assertEqual(initial_scan["scan_status"], "COMPLETED")

                httpd = create_http_server("127.0.0.1", 0)
                port = httpd.server_address[1]
                base_url = f"http://127.0.0.1:{port}"
                srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                srv_thread.start()

                endpoints = [
                    "/api/health",
                    "/api/config",
                    "/api/signals?limit=20&offset=0",
                    "/api/scans?limit=15&offset=0",
                    "/api/oi-snapshots?index_symbol=NIFTY&limit=20&offset=0",
                    "/api/oi-snapshots?index_symbol=BANKNIFTY&limit=20&offset=0",
                ]
                # 6 full dashboard bursts in parallel = 36 simultaneous requests
                all_paths = endpoints * 6
                barrier = threading.Barrier(len(all_paths))

                def fetch_one(path: str):
                    barrier.wait(timeout=5.0)
                    t0 = time.perf_counter()
                    with urllib.request.urlopen(base_url + path, timeout=4.0) as resp:
                        raw = resp.read().decode("utf-8")
                        elapsed = time.perf_counter() - t0
                        return path, resp.status, json.loads(raw), elapsed

                try:
                    with ThreadPoolExecutor(max_workers=len(all_paths)) as pool:
                        futures = [pool.submit(fetch_one, p) for p in all_paths]
                        for fut in as_completed(futures, timeout=6.0):
                            path, status_code, data, elapsed = fut.result(timeout=4.0)
                            self.assertEqual(status_code, 200, f"Unexpected status on {path}")
                            self.assertLess(elapsed, 3.0, f"Request {path} took too long: {elapsed:.2f}s")
                            self.assertEqual(data.get("status"), "ok")
                            if path == "/api/health":
                                self.assertEqual(data["database"]["status"], "OK")
                                self.assertGreaterEqual(data["database"]["signals_count"], 1)
                            elif path == "/api/config":
                                self.assertEqual(data["config"]["active_broker"], "paper_sim")
                            elif path.startswith("/api/signals"):
                                self.assertGreater(data["total_count"], 0)
                                self.assertGreater(len(data["items"]), 0)
                            elif path.startswith("/api/scans"):
                                self.assertGreaterEqual(data["total_count"], 1)
                            elif path.startswith("/api/oi-snapshots"):
                                self.assertEqual(data["total_count"], 1)
                                self.assertGreater(len(data["items"][0]["strikes"]), 0)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    srv_thread.join(timeout=2.0)

    def test_p1f_concurrent_reads_do_not_block_during_active_slow_scan_and_overlap_returns_409(self):
        import threading
        import time
        import urllib.error
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor
        from server import configure_server_runtime, create_http_server

        scan_entered = threading.Event()
        release_scan = threading.Event()

        class _SlowSimAdapter:
            name = "NSE Slow Simulation Adapter (SIMULATED)"
            is_simulated = True

            def __init__(self, inner):
                self._inner = inner
                self._first_call = True

            def get_intraday_candles(self, symbol_meta, interval_min=5, pattern=None):
                if self._first_call:
                    self._first_call = False
                    scan_entered.set()
                    release_scan.wait(timeout=3.0)
                return self._inner.get_intraday_candles(symbol_meta, interval_min=interval_min, pattern=pattern)

            def get_option_chain(self, index_symbol, bias="NEUTRAL"):
                return self._inner.get_option_chain(index_symbol, bias=bias)

        cfg = BotConfig(
            active_broker="paper_sim",
            telegram_dry_run=True,
            database_url=":memory:",
            enable_background_scheduler=False,
        )
        scanner = MultiBrokerScanner(cfg, clock=self.fixed_clock)
        scanner.adapters["paper_sim"] = _SlowSimAdapter(_BidirectionalFixtureAdapter(self.sim))
        configure_server_runtime(
            config=cfg,
            start_scheduler=False,
            clock=self.fixed_clock,
            broker_scanner=scanner,
        )

        httpd = create_http_server("127.0.0.1", 0)
        port = httpd.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        srv_thread.start()

        def trigger_primary_scan():
            req = urllib.request.Request(base_url + "/api/scan", method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))

        def fetch_read_endpoint(path: str):
            t0 = time.perf_counter()
            with urllib.request.urlopen(base_url + path, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return path, resp.status, data, time.perf_counter() - t0

        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                scan_future = pool.submit(trigger_primary_scan)
                self.assertTrue(scan_entered.wait(timeout=2.0), "Primary scan did not start in time")

                # While the primary scan is paused inside get_intraday_candles(), issue concurrent
                # GET requests to all 5 dashboard read endpoints + a second overlapping POST /api/scan
                read_paths = [
                    "/api/health",
                    "/api/config",
                    "/api/signals",
                    "/api/scans",
                    "/api/oi-snapshots?index_symbol=NIFTY",
                ]
                read_futures = [pool.submit(fetch_read_endpoint, p) for p in read_paths]

                for rf in read_futures:
                    path, code, payload, elapsed = rf.result(timeout=2.0)
                    self.assertEqual(code, 200, f"Read endpoint {path} failed while scan was active")
                    self.assertEqual(payload.get("status"), "ok")
                    self.assertLess(elapsed, 1.0, f"Read endpoint {path} blocked behind scan: {elapsed:.2f}s")

                # Overlapping POST /api/scan must immediately return HTTP 409 SKIPPED_OVERLAP
                overlap_req = urllib.request.Request(base_url + "/api/scan", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    with urllib.request.urlopen(overlap_req, timeout=2.0):
                        pass
                with ctx.exception:
                    self.assertEqual(ctx.exception.code, 409)
                    overlap_body = json.loads(ctx.exception.read().decode("utf-8"))
                    self.assertEqual(overlap_body["scan_status"], "SKIPPED_OVERLAP")

                # Release the primary scan and confirm it completes cleanly
                release_scan.set()
                scan_code, scan_payload = scan_future.result(timeout=5.0)
                self.assertEqual(scan_code, 200)
                self.assertEqual(scan_payload["scan_status"], "COMPLETED")
        finally:
            release_scan.set()
            httpd.shutdown()
            httpd.server_close()
            srv_thread.join(timeout=2.0)

    def test_p1f_private_file_disclosure_remains_blocked_under_concurrent_requests(self):
        import threading
        import urllib.error
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor
        from server import configure_server_runtime, create_http_server

        configure_server_runtime(config=self.cfg, start_scheduler=False, clock=self.fixed_clock)
        httpd = create_http_server("127.0.0.1", 0)
        port = httpd.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        srv_thread.start()

        forbidden_paths = [
            "/.env",
            "/.env.example",
            "/config.py",
            "/storage.py",
            "/server.py",
            "/brokers.py",
            "/strategies.py",
            "/scanner_engine.py",
            "/telegram_bot.py",
            "/test_bot.py",
            "/tradepulse_phase1d.db",
            "/README.md",
            "/docs/PHASE_1E_IMPLEMENTATION_REPORT.md",
            "/../.env",
            "/%2e%2e/.env",
            "/public/../.env",
            "/public/..%2fconfig.py",
            "/public/.env",
        ]

        def check_forbidden(path: str):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                with urllib.request.urlopen(base_url + path, timeout=3.0):
                    pass
            with ctx.exception:
                self.assertEqual(ctx.exception.code, 404, f"Expected 404 for {path}")
                err_body = ctx.exception.read().decode("utf-8")
                self.assertNotIn("TELEGRAM_BOT_TOKEN", err_body)
                self.assertNotIn("def configure_server_runtime", err_body)
            return True

        try:
            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(check_forbidden, forbidden_paths))
                self.assertEqual(len(results), len(forbidden_paths))
                self.assertTrue(all(results))

            # Confirm legitimate dashboard HTML and API routes still return 200 OK
            with urllib.request.urlopen(base_url + "/", timeout=3.0) as r_root:
                self.assertEqual(r_root.status, 200)
                self.assertIn("TradePulse", r_root.read().decode("utf-8"))
            with urllib.request.urlopen(base_url + "/api/health", timeout=3.0) as r_health:
                self.assertEqual(r_health.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()
            srv_thread.join(timeout=2.0)



class TestIndianFOSignalBotPhase2A(unittest.TestCase):
    """
    Phase 2A Comprehensive Test Suite — Angel One SmartAPI Read-Only Market Data Integration:
    1. Successful authentication (`loginByPassword`), Bearer token normalization, and `getProfile`.
    2. Missing/placeholder credentials, invalid Base32 TOTP secret, and rejected login (`AB1007`, `AB1050`, `AG8004`).
    3. Session/token expiry (`AG8001`, `AG8002`, `AB1010`, HTTP 401) automatic recovery via `generateTokens` & re-login.
    4. Instrument/token resolution (`resolve_instrument`), Scrip Master (`OpenAPIScripMaster.json`) ingestion,
       paise strike normalization (`2480000.000000` -> `24800`), and `DDMMMYYYY` expiry parsing.
    5. Market quotes (`market/v1/quote/` in `LTP`, `OHLC`, `FULL` modes, >50 token batching, `exchFeedTime` parsing).
    6. Historical/intraday candle parsing, multi-session warm-up dates, duplicate/OHLC validation, and staleness checks.
    7. Empty, malformed, rate-limited (HTTP 429/403), timeout, and temporary server error (`AB1004`, `AB2001`) handling.
    8. Option Greeks (`optionGreek`), PCR (`putCallRatio`), and full Option Chain assembly with Scrip Master + prior OI baseline,
       plus explicit `UnsupportedBrokerCapabilityError` distinction when baseline/Scrip Master is absent.
    9. End-to-end `IntradayBotEngine` & HTTP API health state transitions (`UNAVAILABLE_MISSING_CREDENTIALS`,
       `CONFIGURED_UNVERIFIED`, `CONNECTED_VERIFIED`, `ERROR`) with zero silent fallback to simulation.
    10. Strict secret redaction and read-only enforcement (order/GTT endpoints blocked).
    """

    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.cfg = BotConfig(
            active_broker="angelone",
            angel_api_key="ANGEL_PRIVATE_API_KEY_999",
            angel_client_code="A100200",
            angel_pin="4321",
            angel_totp_secret="JBSWY3DPEHPK3PXP",
            telegram_dry_run=True,
            database_url=":memory:",
            enable_background_scheduler=False,
        )
        self.sim = SimulatedNSEAdapter(seed=42, clock=self.fixed_clock)

    @staticmethod
    def _mock_http_sequence(payloads):
        queue = list(payloads)

        def side_effect(req, timeout=8):
            if not queue:
                raise AssertionError(f"Unexpected extra HTTP call to {req.full_url}")
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            m = MagicMock()
            if isinstance(item, bytes):
                m.read.return_value = item
            elif isinstance(item, str):
                m.read.return_value = item.encode("utf-8")
            else:
                m.read.return_value = json.dumps(item).encode("utf-8")
            m.__enter__.return_value = m
            return m

        return side_effect

    # 1. Successful authentication, Bearer prefix normalization, and getProfile
    def test_p2a_authentication_success_bearer_normalization_and_get_profile(self):
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        login_resp = {
            "status": True,
            "message": "SUCCESS",
            "errorcode": "",
            "data": {
                "jwtToken": "Bearer EY_MOCK_JWT_TOKEN_VALUE",
                "refreshToken": "EY_MOCK_REFRESH_TOKEN_VALUE",
                "feedToken": "FEED_TOKEN_VALUE_123",
            },
        }
        profile_resp = {
            "status": True,
            "message": "SUCCESS",
            "errorcode": "",
            "data": {
                "clientcode": "A100200",
                "name": "TRADEPULSE QA USER",
                "exchanges": ["nse_cm", "nse_fo"],
                "products": ["DELIVERY", "INTRADAY", "CARRYFORWARD"],
            },
        }

        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([login_resp, profile_resp])) as mocked_http:
            ok = adapter.authenticate()
            self.assertTrue(ok)
            self.assertEqual(adapter.jwt_token, "EY_MOCK_JWT_TOKEN_VALUE")
            self.assertEqual(adapter.refresh_token, "EY_MOCK_REFRESH_TOKEN_VALUE")
            self.assertEqual(adapter.feed_token, "FEED_TOKEN_VALUE_123")
            self.assertEqual(adapter.authenticated_at_ist, "2026-10-16 10:35:00")

            prof = adapter.get_profile()
            self.assertEqual(prof["clientcode"], "A100200")
            self.assertIn("nse_fo", prof["exchanges"])
            self.assertFalse(prof["is_simulated"])
            self.assertEqual(prof["data_mode"], "LIVE")

            # Verify Authorization header did NOT double-prefix 'Bearer Bearer '
            prof_req = mocked_http.call_args_list[1][0][0]
            self.assertEqual(prof_req.headers.get("Authorization"), "Bearer EY_MOCK_JWT_TOKEN_VALUE")

    # 2. Missing credentials, invalid Base32 TOTP secret, and rejected login error codes
    def test_p2a_missing_credentials_invalid_totp_and_rejected_authentication(self):
        from config import ConfigValidationError
        # Missing / placeholder credentials
        bad_cfg = BotConfig(
            active_broker="angelone",
            angel_api_key="your_angel_smartapi_key",
            angel_client_code="A100200",
            angel_pin="4321",
            angel_totp_secret="JBSWY3DPEHPK3PXP",
        )
        self.assertFalse(bad_cfg.is_broker_credentials_configured("angelone"))
        with self.assertRaises(ConfigValidationError) as cfg_ctx:
            bad_cfg.validate(require_live_credentials=True)
        self.assertIn("ANGEL_API_KEY", str(cfg_ctx.exception))

        # Invalid Base32 TOTP seed
        bad_totp_cfg = BotConfig(
            active_broker="angelone",
            angel_api_key="VALID_KEY",
            angel_client_code="A100200",
            angel_pin="4321",
            angel_totp_secret="NOT_BASE32_999888!!!",
        )
        self.assertFalse(bad_totp_cfg.is_broker_credentials_configured("angelone"))
        with self.assertRaises(ConfigValidationError):
            bad_totp_cfg.validate(require_live_credentials=True)

        adapter_bad_totp = AngelOneSmartAPIAdapter(bad_totp_cfg, clock=self.fixed_clock)
        with self.assertRaises(BrokerDataError) as totp_ctx:
            adapter_bad_totp.authenticate()
        self.assertIn("TOTP", str(totp_ctx.exception))
        self.assertNotIn("NOT_BASE32_999888!!!", str(totp_ctx.exception))

        # Rejected login from server (AB1050 Invalid TOTP / AB1007 Invalid Password)
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        rejected_resp = {
            "status": False,
            "message": "Invalid totp",
            "errorcode": "AB1050",
            "data": None,
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([rejected_resp])):
            with self.assertRaises(BrokerDataError) as rej_ctx:
                adapter.authenticate()
            self.assertIn("AB1050", str(rej_ctx.exception))
            self.assertIsNone(adapter.jwt_token)

    # 3. Token/session expiry (AG8001 / AB1010) automatic recovery via generateTokens and fallback re-login
    def test_p2a_token_session_expiry_refresh_and_relogin_recovery(self):
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "EXPIRED_JWT_1"
        adapter.refresh_token = "VALID_REFRESH_1"

        expired_ag8001 = {
            "status": False,
            "message": "Invalid Token",
            "errorcode": "AG8001",
            "data": "",
        }
        refresh_ok = {
            "status": True,
            "message": "SUCCESS",
            "errorcode": "",
            "data": {
                "jwtToken": "FRESH_JWT_2",
                "refreshToken": "VALID_REFRESH_2",
                "feedToken": "FEED_2",
            },
        }
        quote_ok = {
            "status": True,
            "message": "SUCCESS",
            "errorcode": "",
            "data": {
                "fetched": [
                    {
                        "exchange": "NSE",
                        "tradingSymbol": "RELIANCE-EQ",
                        "symbolToken": "2885",
                        "ltp": 2952.4,
                        "open": 2940.0,
                        "high": 2960.0,
                        "low": 2938.0,
                        "close": 2945.0,
                        "tradeVolume": 450000,
                        "opnInterest": 0,
                        "exchFeedTime": "16-Oct-2026 10:35:00",
                    }
                ],
                "unfetched": [],
            },
        }

        with patch(
            "urllib.request.urlopen",
            side_effect=self._mock_http_sequence([expired_ag8001, refresh_ok, quote_ok]),
        ) as mocked_http:
            q = adapter.get_quote("RELIANCE", mode="FULL")
            self.assertEqual(q["ltp"], 2952.4)
            self.assertEqual(q["feed_timestamp_ist"], "2026-10-16 10:35:00")
            self.assertEqual(adapter.jwt_token, "FRESH_JWT_2")
            self.assertEqual(mocked_http.call_count, 3)
            self.assertIn("/jwt/v1/generateTokens", mocked_http.call_args_list[1][0][0].full_url)

        # If generateTokens ALSO fails, _recover_session falls back to full loginByPassword
        adapter.jwt_token = "EXPIRED_JWT_2"
        adapter.refresh_token = "EXPIRED_REFRESH_2"
        refresh_fail = {"status": False, "message": "Refresh token expired", "errorcode": "AB1010", "data": None}
        relogin_ok = {"status": True, "data": {"jwtToken": "RELOGIN_JWT_3", "refreshToken": "REF_3"}}
        with patch(
            "urllib.request.urlopen",
            side_effect=self._mock_http_sequence([expired_ag8001, refresh_fail, relogin_ok, quote_ok]),
        ) as mocked_http2:
            q2 = adapter.get_quote("RELIANCE", mode="FULL")
            self.assertEqual(q2["ltp"], 2952.4)
            self.assertEqual(adapter.jwt_token, "RELOGIN_JWT_3")
            self.assertEqual(mocked_http2.call_count, 4)

    # 4. Quote parsing (LTP, OHLC, FULL modes, batching >50 tokens, unfetched errors, and OHLC validation)
    def test_p2a_market_quotes_modes_batching_and_validation(self):
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "ACTIVE_JWT"

        # Batch of 55 tokens -> must split into 2 requests (50 + 5)
        # Explicit synthetic master for transport batching; these are not broker facts.
        adapter.load_scrip_master([dict(token=str(1000+i), symbol=f"SYM{i}-EQ", name=f"SYM{i}",
                                       exch_seg="NSE", instrumenttype="EQ", lotsize="1") for i in range(55)])
        tokens_55 = [str(1000 + i) for i in range(55)]
        batch1_resp = {
            "status": True,
            "data": {
                "fetched": [
                    {"exchange": "NSE", "tradingSymbol": f"SYM{i}", "symbolToken": str(1000 + i), "ltp": 100.0 + i}
                    for i in range(50)
                ],
                "unfetched": [],
            },
        }
        batch2_resp = {
            "status": True,
            "data": {
                "fetched": [
                    {"exchange": "NSE", "tradingSymbol": f"SYM{i}", "symbolToken": str(1000 + i), "ltp": 100.0 + i}
                    for i in range(50, 55)
                ],
                "unfetched": [],
            },
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([batch1_resp, batch2_resp])) as mocked_q:
            res = adapter.get_quotes({"NSE": tokens_55}, mode="LTP")
            self.assertEqual(mocked_q.call_count, 2)
            self.assertEqual(len(res["fetched"]), 55)

        # Invalid OHLC relationship in FULL quote (high < low) -> must raise BrokerDataError
        bad_ohlc_quote = {
            "status": True,
            "data": {
                "fetched": [
                    {
                        "exchange": "NSE",
                        "tradingSymbol": "RELIANCE-EQ",
                        "symbolToken": "2885",
                        "ltp": 2950.0,
                        "open": 2950.0,
                        "high": 2930.0,  # high < low!
                        "low": 2945.0,
                        "close": 2948.0,
                    }
                ],
                "unfetched": [],
            },
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([bad_ohlc_quote])):
            with self.assertRaises(BrokerDataError):
                adapter.get_quote("RELIANCE", mode="FULL")

    # 5. Instrument resolution, Scrip Master parsing, paise strike conversion, and staleness detection
    def test_p2a_instrument_resolution_scrip_master_and_stale_candle_detection(self):
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "ACTIVE_JWT"

        # Resolve built-in equity & index symbols
        rel = adapter.resolve_instrument("RELIANCE")
        self.assertEqual(rel["angel_token"], "2885")
        self.assertEqual(rel["exchange"], "NSE")
        self.assertFalse(rel["is_index"])

        nifty = adapter.resolve_instrument("NIFTY")
        self.assertEqual(nifty["angel_token"], "99926000")
        self.assertTrue(nifty["is_index"])
        self.assertEqual(nifty["lot_size"], 75)

        # Load OpenAPIScripMaster.json sample records with paise strikes ("2480000.000000" -> 24800)
        scrip_records = [
            {
                "token": "58784",
                "symbol": "NIFTY22OCT2624800CE",
                "name": "NIFTY",
                "expiry": "22OCT2026",
                "strike": "2480000.000000",
                "lotsize": "75",
                "instrumenttype": "OPTIDX",
                "exch_seg": "NFO",
                "tick_size": "5.000000",
            },
            {
                "token": "58785",
                "symbol": "NIFTY22OCT2624800PE",
                "name": "NIFTY",
                "expiry": "22OCT2026",
                "strike": "2480000.000000",
                "lotsize": "75",
                "instrumenttype": "OPTIDX",
                "exch_seg": "NFO",
                "tick_size": "5.000000",
            },
        ]
        counts = adapter.load_scrip_master(scrip_records)
        self.assertEqual(counts["index_options_loaded"], 2)
        expiries = adapter.get_expiry_list("NIFTY")
        self.assertEqual(expiries, ["2026-10-22"])

        # Stale candle detection when max_staleness_minutes is specified
        stale_candle_resp = {
            "status": True,
            "data": [
                ["2026-10-15T15:25:00+05:30", 2940.0, 2948.0, 2938.0, 2945.0, 85000],
            ],
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([stale_candle_resp])):
            with self.assertRaises(BrokerDataError) as stale_ctx:
                adapter.get_intraday_candles(
                    {"symbol": "RELIANCE", "angel_token": "2885"},
                    interval_min=5,
                    max_staleness_minutes=30,
                )
            self.assertIn("stale", str(stale_ctx.exception).lower())

    # 6. Option Greeks, Put-Call Ratio, and full Option-Chain Assembly with Scrip Master + Prior OI Baseline
    def test_p2a_option_greeks_pcr_and_option_chain_assembly_with_baseline(self):
        from brokers import UnsupportedBrokerCapabilityError

        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "ACTIVE_JWT"
        adapter.fetch_option_greeks_in_chain = True

        # Without Scrip Master -> raises UnsupportedBrokerCapabilityError (which is also a BrokerDataError)
        with self.assertRaises(UnsupportedBrokerCapabilityError):
            adapter.get_option_chain("NIFTY")

        # Load Scrip Master for 3 NIFTY strikes (24750, 24800, 24850) for expiry 22OCT2026
        scrip_records = []
        tok_counter = 58700
        for strike_val in (24750, 24800, 24850):
            for opt_type in ("CE", "PE"):
                tok_counter += 1
                scrip_records.append({
                    "token": str(tok_counter),
                    "symbol": f"NIFTY22OCT26{strike_val}{opt_type}",
                    "name": "NIFTY",
                    "expiry": "22OCT2026",
                    "strike": f"{strike_val * 100:.6f}",
                    "lotsize": "75",
                    "instrumenttype": "OPTIDX",
                    "exch_seg": "NFO",
                })
        adapter.load_scrip_master(scrip_records)

        # Register verified prior-session OI baseline
        adapter.set_prior_oi_baseline(
            "NIFTY",
            "2026-10-22",
            {
                24750: {"ce_prev_oi": 1600000, "pe_prev_oi": 2100000},
                24800: {"ce_prev_oi": 2270000, "pe_prev_oi": 2720000},
                24850: {"ce_prev_oi": 2000000, "pe_prev_oi": 1800000},
            },
        )

        spot_quote_resp = {
            "status": True,
            "data": {
                "fetched": [{"exchange": "NSE", "tradingSymbol": "NIFTY", "symbolToken": "99926000", "ltp": 24818.5}],
                "unfetched": [],
            },
        }
        nfo_quotes_resp = {
            "status": True,
            "data": {
                "fetched": [
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT2624750CE", "symbolToken": "58701", "ltp": 168.0, "open": 160.0, "high": 175.0, "low": 155.0, "close": 162.0, "opnInterest": 1500000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT2624750PE", "symbolToken": "58702", "ltp": 88.5, "open": 90.0, "high": 95.0, "low": 82.0, "close": 89.0, "opnInterest": 2800000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT2624800CE", "symbolToken": "58703", "ltp": 142.5, "open": 140.0, "high": 150.0, "low": 135.0, "close": 141.0, "opnInterest": 1850000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT2624800PE", "symbolToken": "58704", "ltp": 112.8, "open": 115.0, "high": 120.0, "low": 108.0, "close": 114.0, "opnInterest": 3400000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT2624850CE", "symbolToken": "58705", "ltp": 116.0, "open": 115.0, "high": 125.0, "low": 110.0, "close": 118.0, "opnInterest": 2100000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT2624850PE", "symbolToken": "58706", "ltp": 139.0, "open": 140.0, "high": 148.0, "low": 132.0, "close": 138.0, "opnInterest": 1900000},
                ],
                "unfetched": [],
            },
        }
        greeks_resp = {
            "status": True,
            "data": [
                {"name": "NIFTY", "expiry": "22OCT2026", "strikePrice": "24800.000000", "optionType": "CE", "impliedVolatility": "12.15", "delta": "0.5120", "gamma": "0.0018", "theta": "-8.40", "vega": "11.20", "tradeVolume": "125000"},
                {"name": "NIFTY", "expiry": "22OCT2026", "strikePrice": "24800.000000", "optionType": "PE", "impliedVolatility": "12.85", "delta": "-0.4880", "gamma": "0.0018", "theta": "-8.10", "vega": "11.10", "tradeVolume": "142000"},
            ],
        }
        pcr_resp = {
            "status": True,
            "data": [{"pcr": 1.49, "tradingSymbol": "NIFTY22OCT26FUT"}],
        }

        with patch(
            "urllib.request.urlopen",
            side_effect=self._mock_http_sequence([spot_quote_resp, nfo_quotes_resp, greeks_resp, pcr_resp]),
        ):
            chain = adapter.get_option_chain("NIFTY")
            pcr_list = adapter.get_put_call_ratio()

        self.assertEqual(chain["index"], "NIFTY")
        self.assertEqual(chain["expiry"], "2026-10-22")
        self.assertEqual(chain["spot"], 24818.5)
        self.assertEqual(chain["atm_strike"], 24800)
        self.assertFalse(chain["is_simulated"])
        self.assertEqual(chain["data_mode"], "LIVE")
        atm_row = next(s for s in chain["strikes"] if s["strike"] == 24800)
        self.assertEqual(atm_row["ce_oi_change"], -420000)
        self.assertEqual(atm_row["pe_oi_change"], 680000)
        self.assertEqual(atm_row["ce_iv"], 12.15)
        self.assertEqual(atm_row["pe_iv"], 12.85)
        self.assertEqual(pcr_list[0]["pcr"], 1.49)

        # Verify Strategy 3 consumes the assembled Angel One option chain directly
        candles = self.sim.get_intraday_candles({"symbol": "NIFTY"}, interval_min=5, pattern="vwap_pullback_bull")
        sig = evaluate_option_apex_oi_shift("NIFTY", candles, chain, lot_size=75, capital_inr=500000)
        self.assertIsNotNone(sig)
        self.assertFalse(sig.is_simulated)
        self.assertEqual(sig.data_mode, "LIVE")
        self.assertEqual(sig.entry_price, 142.5)

    # 7. Rate limits, timeouts, temporary server errors (AB1004 / AB2001), secret redaction, and order blocking
    def test_p2a_rate_limits_timeouts_secret_redaction_and_order_blocking(self):
        import socket
        import urllib.error

        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "SECRET_JWT_TOKEN_VALUE"

        # 1) Order placement / GTT endpoints must be blocked before making any network call
        for forbidden_path in (
            "/rest/secure/angelbroking/order/v1/placeOrder",
            "/rest/secure/angelbroking/order/v1/modifyOrder",
            "/rest/secure/angelbroking/order/v1/cancelOrder",
            "/rest/secure/angelbroking/gtt/v1/createRule",
        ):
            with self.assertRaises(BrokerDataError) as ord_ctx:
                adapter._request_json("POST", forbidden_path, payload={"tradingsymbol": "RELIANCE-EQ"})
            self.assertIn("strictly disabled", str(ord_ctx.exception))

        # 2) Temporary server error AB1004 / AB2001 classification
        ab1004_resp = {
            "status": False,
            "message": "Something Went Wrong, Please Try After Sometime",
            "errorcode": "AB1004",
            "data": None,
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([ab1004_resp])):
            with self.assertRaises(BrokerDataError) as ab_ctx:
                adapter.get_intraday_candles({"symbol": "RELIANCE", "angel_token": "2885"}, interval_min=5)
            self.assertIn("AB1004", str(ab_ctx.exception))
            self.assertIn("temporary Angel One server error", str(ab_ctx.exception))

        # 3) Network timeout & secret redaction check
        timeout_err = urllib.error.URLError(
            socket.timeout(f"Timed out with key {self.cfg.angel_api_key} and pin {self.cfg.angel_pin}")
        )
        with patch("urllib.request.urlopen", side_effect=timeout_err):
            with self.assertRaises(BrokerDataError) as net_ctx:
                adapter.get_intraday_candles({"symbol": "RELIANCE", "angel_token": "2885"}, interval_min=5)
            err_str = str(net_ctx.exception)
            self.assertNotIn(self.cfg.angel_api_key, err_str)
            self.assertNotIn(self.cfg.angel_pin, err_str)
            self.assertNotIn(self.cfg.angel_totp_secret, err_str)
            self.assertNotIn("SECRET_JWT_TOKEN_VALUE", err_str)

    # 8. End-to-End Angel One Scanner & Health Status State Transitions (No Silent Fallback)
    def test_p2a_engine_and_health_status_transitions_with_angelone(self):
        # State 1: UNAVAILABLE_MISSING_CREDENTIALS when placeholder credentials are used
        cfg_missing = BotConfig(
            active_broker="angelone",
            angel_api_key="your_angel_smartapi_key",
            database_url=":memory:",
        )
        engine_missing = IntradayBotEngine(cfg_missing, clock=self.fixed_clock)
        self.assertEqual(engine_missing.get_broker_status()["connection_state"], "UNAVAILABLE_MISSING_CREDENTIALS")

        # State 2: CONFIGURED_UNVERIFIED before first scan
        engine = IntradayBotEngine(self.cfg, clock=self.fixed_clock)
        status_pre = engine.get_broker_status()
        self.assertEqual(status_pre["connection_state"], "CONFIGURED_UNVERIFIED")
        self.assertFalse(status_pre["connectivity_verified"])
        self.assertEqual(status_pre["data_mode"], "LIVE")

        # Prepare mocked Angel One candle responses for 2 indices + 15 equities (1 login + 17 candle calls)
        sim_vwap_bars = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5, pattern="vwap_pullback_bull")
        angel_candle_rows = [
            [b["timestamp"].replace(" ", "T") + "+05:30", b["open"], b["high"], b["low"], b["close"], b["volume"]]
            for b in sim_vwap_bars
        ]
        login_ok = {"status": True, "data": {"jwtToken": "LIVE_VERIFIED_JWT", "refreshToken": "LIVE_REF"}}
        candle_ok = {"status": True, "data": angel_candle_rows}
        seq = [login_ok] + [candle_ok for _ in range(17)]

        # State 3: Run scan without Scrip Master -> UnsupportedBrokerCapabilityError on option chain is
        # recorded in instrument_errors, while Strategies 1, 2, 4, 5 succeed on LIVE candles and
        # connection_state transitions to CONNECTED_VERIFIED!
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence(seq)):
            scan_summary = engine.run_single_scan()

        self.assertEqual(scan_summary["scan_status"], "COMPLETED")
        self.assertEqual(scan_summary["data_mode"], "LIVE")
        self.assertFalse(scan_summary["is_simulated"])
        self.assertGreater(scan_summary["total_signals"], 0)
        for sig in scan_summary["signals"]:
            self.assertFalse(sig["is_simulated"])
            self.assertEqual(sig["data_mode"], "LIVE")

        status_post = engine.get_broker_status()
        self.assertEqual(status_post["connection_state"], "CONNECTED_VERIFIED")
        self.assertTrue(status_post["connectivity_verified"])

        # State 4: If Angel One fails on candle fetch -> raises BrokerDataError (NO silent fallback to simulation)
        # and transitions connection_state to ERROR
        fail_resp = {"status": False, "message": "Internal Error", "errorcode": "AB2001", "data": None}
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([fail_resp])):
            with self.assertRaises(BrokerDataError):
                engine.run_single_scan()

        status_err = engine.get_broker_status()
        self.assertEqual(status_err["connection_state"], "ERROR")
        self.assertFalse(status_err["connectivity_verified"])
        self.assertIn("AB2001", status_err["last_error"])


import threading
from storage import SQLitePersistenceStore, PersistenceError, PersistenceValidationError


import urllib.request
import urllib.error

class TestIndianFOSignalBotPhase2B(unittest.TestCase):
    """
    Phase 2B Test Suite — Persistent Option Apex OI Baselines, Scrip Master Hardening,
    Scanner Resilience, and Live-Data Reliability (Deterministic Mocked Tests Only).
    """

    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.cfg = BotConfig(
            active_broker="angelone",
            angel_api_key="TEST_ANGEL_PRIVATE_KEY_99",
            angel_client_code="A1234567",
            angel_pin="4321",
            angel_totp_secret="JBSWY3DPEHPK3PXP",
            angel_request_timeout_seconds=5.0,
            angel_min_request_interval_seconds=0.0,
            angel_scrip_master_max_age_hours=24.0,
            angel_baseline_max_sessions_age=1,
            telegram_dry_run=True,
            database_url=":memory:",
        )
        self.sim = SimulatedNSEAdapter(clock=self.fixed_clock)

    @staticmethod
    def _mock_http_sequence(responses):
        iterator = iter(responses)

        def _urlopen(req, timeout=8):
            item = next(iterator)
            if isinstance(item, Exception):
                raise item
            body_bytes = item if isinstance(item, bytes) else json.dumps(item).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.read.return_value = body_bytes
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        return _urlopen

    @staticmethod
    def _build_scrip_master_fixture(expiry_angel="22OCT2026"):
        records = [
            {
                "token": "99926000",
                "symbol": "NIFTY",
                "name": "NIFTY",
                "expiry": "",
                "strike": "-1.000000",
                "lotsize": "75",
                "instrumenttype": "AMXIDX",
                "exch_seg": "NSE",
            },
            {
                "token": "99926009",
                "symbol": "BANKNIFTY",
                "name": "BANKNIFTY",
                "expiry": "",
                "strike": "-1.000000",
                "lotsize": "30",
                "instrumenttype": "AMXIDX",
                "exch_seg": "NSE",
            },
            {
                "token": "2885",
                "symbol": "RELIANCE-EQ",
                "name": "RELIANCE",
                "expiry": "",
                "strike": "-1.000000",
                "lotsize": "1",
                "instrumenttype": "",
                "exch_seg": "NSE",
            },
        ]
        tok = 58700
        for strike_val in (24750, 24800, 24850):
            for opt_type in ("CE", "PE"):
                tok += 1
                records.append({
                    "token": str(tok),
                    "symbol": f"NIFTY{expiry_angel}{strike_val}{opt_type}",
                    "name": "NIFTY",
                    "expiry": expiry_angel,
                    "strike": f"{strike_val * 100:.6f}",
                    "lotsize": "75",
                    "instrumenttype": "OPTIDX",
                    "exch_seg": "NFO",
                })
        for strike_val in (52400, 52500):
            for opt_type in ("CE", "PE"):
                tok += 1
                records.append({
                    "token": str(tok),
                    "symbol": f"BANKNIFTY{expiry_angel}{strike_val}{opt_type}",
                    "name": "BANKNIFTY",
                    "expiry": expiry_angel,
                    "strike": f"{strike_val * 100:.6f}",
                    "lotsize": "30",
                    "instrumenttype": "OPTIDX",
                    "exch_seg": "NFO",
                })
        return records

    # 1. Persisting and restoring OI baselines across application restart + Option Apex signal generation
    def test_p2b_persist_and_restore_oi_baselines_across_restart_and_option_apex_signal(self):
        import tempfile
        from brokers import UnsupportedBrokerCapabilityError

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "tradepulse_p2b_restart.db")
            db_url = f"sqlite:///{db_file}"
            scrip_file = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            with open(scrip_file, "w", encoding="utf-8") as f:
                json.dump(self._build_scrip_master_fixture("22OCT2026"), f)

            # --- SESSION T-1 (Thursday 2026-10-15 15:25:00 IST) ---
            thursday_now = datetime(2026, 10, 15, 15, 25, 0, tzinfo=IST)
            cfg_t1 = BotConfig(
                active_broker="angelone",
                angel_api_key="TEST_ANGEL_PRIVATE_KEY_99",
                angel_client_code="A1234567",
                angel_pin="4321",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_file,
                database_url=db_url,
                telegram_dry_run=True,
            )
            engine_t1 = IntradayBotEngine(cfg_t1, clock=lambda: thursday_now)
            adapter_t1 = engine_t1.broker.get_active_adapter()
            adapter_t1.jwt_token = "JWT_T1"

            # On Session T-1, no T-2 baseline exists yet. Fetching NIFTY option chain
            # fetches live NFO FULL quotes, persists T-1's OI into `oi_baselines`,
            # and raises UnsupportedBrokerCapabilityError so Option Apex does not invent prev_oi!
            spot_t1 = {
                "status": True,
                "data": {"fetched": [{"exchange": "NSE", "tradingSymbol": "NIFTY", "symbolToken": "99926000", "ltp": 24805.0}], "unfetched": []},
            }
            nfo_t1 = {
                "status": True,
                "data": {
                    "fetched": [
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750CE", "symbolToken": "58701", "ltp": 150.0, "open": 145.0, "high": 155.0, "low": 140.0, "close": 148.0, "opnInterest": 1600000, "exchFeedTime": "15-Oct-2026 15:25:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750PE", "symbolToken": "58702", "ltp": 95.0, "open": 92.0, "high": 98.0, "low": 90.0, "close": 94.0, "opnInterest": 2100000, "exchFeedTime": "15-Oct-2026 15:25:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800CE", "symbolToken": "58703", "ltp": 130.0, "open": 125.0, "high": 135.0, "low": 120.0, "close": 128.0, "opnInterest": 2270000, "exchFeedTime": "15-Oct-2026 15:25:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800PE", "symbolToken": "58704", "ltp": 120.0, "open": 118.0, "high": 125.0, "low": 115.0, "close": 119.0, "opnInterest": 2720000, "exchFeedTime": "15-Oct-2026 15:25:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850CE", "symbolToken": "58705", "ltp": 105.0, "open": 100.0, "high": 110.0, "low": 98.0, "close": 104.0, "opnInterest": 2000000, "exchFeedTime": "15-Oct-2026 15:25:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850PE", "symbolToken": "58706", "ltp": 145.0, "open": 140.0, "high": 150.0, "low": 138.0, "close": 142.0, "opnInterest": 1800000, "exchFeedTime": "15-Oct-2026 15:25:00"},
                    ],
                    "unfetched": [],
                },
            }
            with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([spot_t1, nfo_t1])):
                with self.assertRaises(UnsupportedBrokerCapabilityError):
                    adapter_t1.get_option_chain("NIFTY")

            # Verify T-1 observations were persisted in SQLite `oi_baselines`
            q_t1 = engine_t1.store.query_oi_baselines(index_symbol="NIFTY", session_date="2026-10-15", data_mode="LIVE")
            self.assertEqual(q_t1["total_count"], 6)

            # --- SIMULATE APPLICATION RESTART ON SESSION T (Friday 2026-10-16 10:35:00 IST) ---
            del adapter_t1
            del engine_t1

            cfg_t2 = BotConfig(
                active_broker="angelone",
                angel_api_key="TEST_ANGEL_PRIVATE_KEY_99",
                angel_client_code="A1234567",
                angel_pin="4321",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_file,
                database_url=db_url,
                telegram_dry_run=True,
            )
            engine_t2 = IntradayBotEngine(cfg_t2, clock=self.fixed_clock)
            adapter_t2 = engine_t2.broker.get_active_adapter()
            adapter_t2.jwt_token = "JWT_T2"

            # Verify NIFTY baseline was automatically restored from SQLite on startup!
            status_t2 = engine_t2.get_broker_status()
            self.assertEqual(status_t2["option_apex"]["indices"]["NIFTY"]["status"], "READY")
            self.assertEqual(status_t2["option_apex"]["indices"]["NIFTY"]["baseline_session_date"], "2026-10-15")
            self.assertEqual(status_t2["option_apex"]["indices"]["NIFTY"]["paired_strikes_ready"], 3)
            # BANKNIFTY has no baseline yet -> UNAVAILABLE_NO_PRIOR_BASELINE
            self.assertEqual(status_t2["option_apex"]["indices"]["BANKNIFTY"]["status"], "UNAVAILABLE_NO_PRIOR_BASELINE")
            self.assertEqual(status_t2["option_apex"]["overall_status"], "PARTIAL_READY")

            spot_t2 = {
                "status": True,
                "data": {"fetched": [{"exchange": "NSE", "tradingSymbol": "NIFTY", "symbolToken": "99926000", "ltp": 24818.5}], "unfetched": []},
            }
            nfo_t2 = {
                "status": True,
                "data": {
                    "fetched": [
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750CE", "symbolToken": "58701", "ltp": 168.0, "open": 160.0, "high": 175.0, "low": 155.0, "close": 162.0, "opnInterest": 1500000, "exchFeedTime": "16-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750PE", "symbolToken": "58702", "ltp": 88.5, "open": 90.0, "high": 95.0, "low": 82.0, "close": 89.0, "opnInterest": 2800000, "exchFeedTime": "16-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800CE", "symbolToken": "58703", "ltp": 142.5, "open": 140.0, "high": 150.0, "low": 135.0, "close": 141.0, "opnInterest": 1850000, "exchFeedTime": "16-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800PE", "symbolToken": "58704", "ltp": 112.8, "open": 115.0, "high": 120.0, "low": 108.0, "close": 114.0, "opnInterest": 3400000, "exchFeedTime": "16-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850CE", "symbolToken": "58705", "ltp": 116.0, "open": 115.0, "high": 125.0, "low": 110.0, "close": 118.0, "opnInterest": 2100000, "exchFeedTime": "16-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850PE", "symbolToken": "58706", "ltp": 139.0, "open": 140.0, "high": 148.0, "low": 132.0, "close": 138.0, "opnInterest": 1900000, "exchFeedTime": "16-Oct-2026 10:35:00"},
                    ],
                    "unfetched": [],
                },
            }
            with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([spot_t2, nfo_t2])):
                chain = adapter_t2.get_option_chain("NIFTY")

            self.assertEqual(chain["baseline_session_date"], "2026-10-15")
            self.assertEqual(chain["baseline_source"], "angelone_live_quote")
            atm_row = next(r for r in chain["strikes"] if r["strike"] == 24800)
            self.assertEqual(atm_row["ce_prev_oi"], 2270000)
            self.assertEqual(atm_row["pe_prev_oi"], 2720000)
            self.assertEqual(atm_row["ce_oi_change"], -420000)
            self.assertEqual(atm_row["pe_oi_change"], 680000)

            candles = self.sim.get_intraday_candles({"symbol": "NIFTY"}, interval_min=5, pattern="vwap_pullback_bull")
            sig = evaluate_option_apex_oi_shift("NIFTY", candles, chain, lot_size=75, now=self.fixed_now, capital_inr=500000)
            self.assertIsNotNone(sig)
            self.assertEqual(sig.strategy_id, "strat_3_option_apex_oi")
            self.assertEqual(sig.direction, "BULLISH (BUY CE)")
            self.assertEqual(sig.data_mode, "LIVE")
            self.assertFalse(sig.is_simulated)

    # 2. Idempotent baseline writes, duplicate batch handling, and conflict rejection
    def test_p2b_idempotent_baseline_writes_and_duplicate_conflict_rejection(self):
        store = SQLitePersistenceStore(":memory:")
        base_records = [
            {
                "index_symbol": "NIFTY",
                "expiry": "2026-10-22",
                "strike": 24800,
                "option_type": "CE",
                "open_interest": 2200000,
                "source": "angelone_live_quote",
                "observation_timestamp": "2026-10-15 15:15:00",
                "session_date": "2026-10-15",
                "data_mode": "LIVE",
            },
            {
                "index_symbol": "NIFTY",
                "expiry": "2026-10-22",
                "strike": 24800,
                "option_type": "PE",
                "open_interest": 2700000,
                "source": "angelone_live_quote",
                "observation_timestamp": "2026-10-15 15:15:00",
                "session_date": "2026-10-15",
                "data_mode": "LIVE",
            },
        ]
        r1 = store.save_oi_baseline_records(base_records, now_ist=self.fixed_now)
        self.assertEqual(r1["inserted_count"], 2)
        self.assertEqual(r1["updated_count"], 0)
        self.assertEqual(r1["unchanged_count"], 0)

        # Exact re-submission is idempotent (0 inserted, 0 updated, 2 unchanged)
        r2 = store.save_oi_baseline_records(base_records, now_ist=self.fixed_now)
        self.assertEqual(r2["inserted_count"], 0)
        self.assertEqual(r2["updated_count"], 0)
        self.assertEqual(r2["unchanged_count"], 2)
        self.assertEqual(store.check_health()["oi_baselines_count"], 2)

        # Newer observation timestamp on the same session_date updates closing OI cleanly
        later_records = [
            dict(base_records[0], open_interest=2270000, observation_timestamp="2026-10-15 15:29:00"),
            dict(base_records[1], open_interest=2720000, observation_timestamp="2026-10-15 15:29:00"),
        ]
        r3 = store.save_oi_baseline_records(later_records, now_ist=self.fixed_now)
        self.assertEqual(r3["inserted_count"], 0)
        self.assertEqual(r3["updated_count"], 2)

        # Conflicting record at same or older timestamp with different OI must raise PersistenceValidationError
        conflicting_same_ts = [
            dict(later_records[0], open_interest=9999999),
        ]
        with self.assertRaises(PersistenceValidationError):
            store.save_oi_baseline_records(conflicting_same_ts, now_ist=self.fixed_now)

        # Conflicting duplicate records inside the same batch must raise PersistenceValidationError
        conflicting_batch = [
            {
                "index_symbol": "BANKNIFTY",
                "expiry": "2026-10-22",
                "strike": 52400,
                "option_type": "CE",
                "open_interest": 800000,
                "source": "angelone_live_quote",
                "observation_timestamp": "2026-10-15 15:20:00",
                "session_date": "2026-10-15",
                "data_mode": "LIVE",
            },
            {
                "index_symbol": "BANKNIFTY",
                "expiry": "2026-10-22",
                "strike": 52400,
                "option_type": "CE",
                "open_interest": 950000,
                "source": "angelone_live_quote",
                "observation_timestamp": "2026-10-15 15:20:00",
                "session_date": "2026-10-15",
                "data_mode": "LIVE",
            },
        ]
        with self.assertRaises(PersistenceValidationError):
            store.save_oi_baseline_records(conflicting_batch, now_ist=self.fixed_now)

    # 3. CE/PE pairing validation and expiry mismatch rejection
    def test_p2b_ce_pe_pairing_and_expiry_mismatch_rejection(self):
        from brokers import UnsupportedBrokerCapabilityError

        store = SQLitePersistenceStore(":memory:")
        # Insert only CE leg for strike 24800 (missing PE leg)
        store.save_oi_baseline_records(
            [
                {
                    "index_symbol": "NIFTY",
                    "expiry": "2026-10-22",
                    "strike": 24800,
                    "option_type": "CE",
                    "open_interest": 2100000,
                    "source": "angelone_live_quote",
                    "observation_timestamp": "2026-10-15 15:25:00",
                    "session_date": "2026-10-15",
                    "data_mode": "LIVE",
                }
            ],
            now_ist=self.fixed_now,
        )
        res_unpaired = store.load_prior_session_oi_baseline(
            index_symbol="NIFTY",
            expiry="2026-10-22",
            current_session_date="2026-10-16",
            data_mode="LIVE",
            now_ist=self.fixed_now,
        )
        self.assertFalse(res_unpaired["usable"])
        self.assertEqual(res_unpaired["status"], "INCOMPLETE_CE_PE_PAIRS")
        self.assertEqual(res_unpaired["unpaired_strikes"], [24800])

        # Expiry mismatch: baseline exists for 2026-10-22, but query requests 2026-10-29
        res_mismatch = store.load_prior_session_oi_baseline(
            index_symbol="NIFTY",
            expiry="2026-10-29",
            current_session_date="2026-10-16",
            data_mode="LIVE",
            now_ist=self.fixed_now,
        )
        self.assertFalse(res_mismatch["usable"])
        self.assertEqual(res_mismatch["status"], "EXPIRY_MISMATCH")
        self.assertEqual(res_mismatch["mismatched_baseline_expiry"], "2026-10-22")

        # Verify adapter raises UnsupportedBrokerCapabilityError on incomplete pairs without fabricating 0
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock, persistence_store=store)
        adapter.jwt_token = "ACTIVE_JWT"
        adapter.load_scrip_master(self._build_scrip_master_fixture("22OCT2026"))
        spot_resp = {"status": True, "data": {"fetched": [{"exchange": "NSE", "tradingSymbol": "NIFTY", "symbolToken": "99926000", "ltp": 24800.0}], "unfetched": []}}
        nfo_resp = {
            "status": True,
            "data": {
                "fetched": [
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750CE", "symbolToken": "58701", "ltp": 150.0, "open": 145.0, "high": 155.0, "low": 140.0, "close": 148.0, "opnInterest": 1500000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750PE", "symbolToken": "58702", "ltp": 95.0, "open": 92.0, "high": 98.0, "low": 90.0, "close": 94.0, "opnInterest": 2100000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800CE", "symbolToken": "58703", "ltp": 130.0, "open": 125.0, "high": 135.0, "low": 120.0, "close": 128.0, "opnInterest": 1850000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800PE", "symbolToken": "58704", "ltp": 120.0, "open": 118.0, "high": 125.0, "low": 115.0, "close": 119.0, "opnInterest": 3400000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850CE", "symbolToken": "58705", "ltp": 105.0, "open": 100.0, "high": 110.0, "low": 98.0, "close": 104.0, "opnInterest": 2100000},
                    {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850PE", "symbolToken": "58706", "ltp": 145.0, "open": 140.0, "high": 150.0, "low": 138.0, "close": 142.0, "opnInterest": 1900000},
                ],
                "unfetched": [],
            },
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([spot_resp, nfo_resp])):
            with self.assertRaises(UnsupportedBrokerCapabilityError) as ctx:
                adapter.get_option_chain("NIFTY")
            self.assertIn("INCOMPLETE_CE_PE_PAIRS", str(ctx.exception))

    # 4. Stale, missing, future-dated timestamps, weekends, and market holidays
    def test_p2b_stale_missing_future_dated_and_weekend_holiday_baselines(self):
        store = SQLitePersistenceStore(":memory:")

        # Missing baseline
        missing_res = store.load_prior_session_oi_baseline(
            "NIFTY", "2026-10-22", current_session_date="2026-10-16", data_mode="LIVE", now_ist=self.fixed_now
        )
        self.assertEqual(missing_res["status"], "NO_PRIOR_BASELINE")
        self.assertFalse(missing_res["usable"])

        # Future-dated timestamp rejected on save
        with self.assertRaises(PersistenceValidationError) as fut_ctx:
            store.save_oi_baseline_records(
                [
                    {
                        "index_symbol": "NIFTY",
                        "expiry": "2026-10-22",
                        "strike": 24800,
                        "option_type": "CE",
                        "open_interest": 100000,
                        "source": "angelone_live_quote",
                        "observation_timestamp": "2026-10-16 14:00:00",  # Future relative to 10:35 IST
                        "session_date": "2026-10-16",
                        "data_mode": "LIVE",
                    }
                ],
                now_ist=self.fixed_now,
            )
        self.assertIn("future", str(fut_ctx.exception).lower())

        # Weekend session_date rejected on save
        with self.assertRaises(PersistenceValidationError) as wknd_ctx:
            store.save_oi_baseline_records(
                [
                    {
                        "index_symbol": "NIFTY",
                        "expiry": "2026-10-22",
                        "strike": 24800,
                        "option_type": "CE",
                        "open_interest": 100000,
                        "source": "angelone_live_quote",
                        "observation_timestamp": "2026-10-17 15:00:00",  # Saturday
                        "session_date": "2026-10-17",
                        "data_mode": "LIVE",
                    }
                ],
                now_ist=datetime(2026, 10, 19, 10, 0, 0, tzinfo=IST),
            )
        self.assertIn("weekend", str(wknd_ctx.exception).lower())

        # Save Wednesday 2026-10-14 baseline
        store.save_paired_strike_baselines(
            index_symbol="NIFTY",
            expiry="2026-10-22",
            baseline_by_strike={24800: {"ce_oi": 1900000, "pe_oi": 2400000}},
            session_date="2026-10-14",
            observation_timestamp="2026-10-14 15:29:00",
            source="angelone_live_quote",
            data_mode="LIVE",
            now_ist=self.fixed_now,
        )
        # On Friday 2026-10-16 (when Thursday 2026-10-15 was a trading day), 2026-10-14 is 2 sessions old -> STALE_BASELINE
        stale_res = store.load_prior_session_oi_baseline(
            "NIFTY",
            "2026-10-22",
            current_session_date="2026-10-16",
            data_mode="LIVE",
            max_sessions_age=1,
            now_ist=self.fixed_now,
        )
        self.assertEqual(stale_res["status"], "STALE_BASELINE")
        self.assertFalse(stale_res["usable"])
        self.assertEqual(stale_res["sessions_age"], 2)

        # However, if Thursday 2026-10-15 was a configured NSE market holiday, then 2026-10-14 is 1 trading session prior -> READY!
        holiday_res = store.load_prior_session_oi_baseline(
            "NIFTY",
            "2026-10-22",
            current_session_date="2026-10-16",
            data_mode="LIVE",
            configured_holidays=["2026-10-15"],
            max_sessions_age=1,
            now_ist=self.fixed_now,
        )
        self.assertEqual(holiday_res["status"], "READY")
        self.assertTrue(holiday_res["usable"])
        self.assertEqual(holiday_res["sessions_age"], 1)

        # Save Friday 2026-10-16 baseline and load on Monday 2026-10-19 (across weekend) -> READY (1 session old)
        monday_now = datetime(2026, 10, 19, 9, 30, 0, tzinfo=IST)
        store.save_paired_strike_baselines(
            index_symbol="NIFTY",
            expiry="2026-10-22",
            baseline_by_strike={24800: {"ce_oi": 2150000, "pe_oi": 2650000}},
            session_date="2026-10-16",
            observation_timestamp="2026-10-16 15:29:00",
            source="angelone_live_quote",
            data_mode="LIVE",
            now_ist=monday_now,
        )
        mon_res = store.load_prior_session_oi_baseline(
            "NIFTY",
            "2026-10-22",
            current_session_date="2026-10-19",
            data_mode="LIVE",
            max_sessions_age=1,
            now_ist=monday_now,
        )
        self.assertEqual(mon_res["status"], "READY")
        self.assertTrue(mon_res["usable"])
        self.assertEqual(mon_res["baseline_session_date"], "2026-10-16")
        self.assertEqual(mon_res["sessions_age"], 1)

    # 5. Previous-session vs intraday OI change semantics & SIMULATED/LIVE data-mode isolation
    def test_p2b_previous_session_vs_intraday_oi_semantics_and_mode_isolation(self):
        store = SQLitePersistenceStore(":memory:")

        # 1) Record same-session (2026-10-16) observations only -> must NOT be used as prior-session baseline on 2026-10-16
        store.save_paired_strike_baselines(
            index_symbol="NIFTY",
            expiry="2026-10-22",
            baseline_by_strike={24800: {"ce_oi": 1800000, "pe_oi": 2500000}},
            session_date="2026-10-16",
            observation_timestamp="2026-10-16 09:20:00",
            source="angelone_live_quote",
            data_mode="LIVE",
            now_ist=self.fixed_now,
        )
        same_day_load = store.load_prior_session_oi_baseline(
            "NIFTY",
            "2026-10-22",
            current_session_date="2026-10-16",
            data_mode="LIVE",
            now_ist=self.fixed_now,
        )
        self.assertFalse(same_day_load["usable"])
        self.assertEqual(same_day_load["status"], "NO_PRIOR_BASELINE")
        self.assertEqual(same_day_load["same_session_records_present"], 2)
        self.assertIn("cannot be substituted", same_day_load["reason"])

        # Adapter set_prior_oi_baseline must also reject current-session date
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock, persistence_store=store)
        with self.assertRaises(BrokerDataError) as same_sess_ctx:
            adapter.set_prior_oi_baseline(
                "NIFTY",
                "2026-10-22",
                {24800: {"ce_prev_oi": 1800000, "pe_prev_oi": 2500000}},
                session_date="2026-10-16",
            )
        self.assertIn("strictly earlier", str(same_sess_ctx.exception))

        # 2) SIMULATED baseline on 2026-10-15 must NEVER be loaded for LIVE mode
        store.save_paired_strike_baselines(
            index_symbol="NIFTY",
            expiry="2026-10-22",
            baseline_by_strike={24800: {"ce_oi": 1950000, "pe_oi": 2450000}},
            session_date="2026-10-15",
            observation_timestamp="2026-10-15 15:25:00",
            source="simulated_option_chain",
            data_mode="SIMULATED",
            now_ist=self.fixed_now,
        )
        live_load = store.load_prior_session_oi_baseline(
            "NIFTY",
            "2026-10-22",
            current_session_date="2026-10-16",
            data_mode="LIVE",
            now_ist=self.fixed_now,
        )
        self.assertFalse(live_load["usable"])
        self.assertEqual(live_load["status"], "NO_PRIOR_BASELINE")

        sim_load = store.load_prior_session_oi_baseline(
            "NIFTY",
            "2026-10-22",
            current_session_date="2026-10-16",
            data_mode="SIMULATED",
            now_ist=self.fixed_now,
        )
        self.assertTrue(sim_load["usable"])
        self.assertEqual(sim_load["status"], "READY")
        self.assertEqual(sim_load["data_mode"], "SIMULATED")

        # Attempting to mix simulated source with LIVE data_mode raises PersistenceValidationError
        with self.assertRaises(PersistenceValidationError):
            store.save_paired_strike_baselines(
                index_symbol="NIFTY",
                expiry="2026-10-22",
                baseline_by_strike={24800: {"ce_oi": 1950000, "pe_oi": 2450000}},
                session_date="2026-10-15",
                observation_timestamp="2026-10-15 15:25:00",
                source="simulated_option_chain",
                data_mode="LIVE",
                now_ist=self.fixed_now,
            )

    # 6. Scrip Master corruption, invalid contracts, caching, and safe atomic refresh
    def test_p2b_scrip_master_validation_corruption_caching_and_safe_refresh(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            scrip_path = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            valid_records = self._build_scrip_master_fixture("22OCT2026")
            with open(scrip_path, "w", encoding="utf-8") as f:
                json.dump(valid_records, f)

            cfg = BotConfig(
                active_broker="angelone",
                angel_api_key="TEST_KEY",
                angel_client_code="A123",
                angel_pin="1234",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_path,
                database_url=":memory:",
            )
            adapter = AngelOneSmartAPIAdapter(cfg, clock=self.fixed_clock)
            st0 = adapter.get_scrip_master_status(now_ist=self.fixed_now)
            self.assertEqual(st0["status"], "LOADED")
            self.assertEqual(st0["index_options_loaded"], 10)
            self.assertEqual(st0["paired_strikes_count"]["NIFTY"], 3)

            # Verify ensure_scrip_master_loaded does NOT re-read file if mtime is unchanged
            with patch("builtins.open", side_effect=AssertionError("Should not re-open cached Scrip Master!")):
                adapter.ensure_scrip_master_loaded()

            # Attempt to refresh with corrupt JSON -> must raise BrokerDataError and preserve valid loaded contracts!
            corrupt_path = os.path.join(tmpdir, "corrupt.json")
            with open(corrupt_path, "w", encoding="utf-8") as f:
                f.write("{corrupt_json: [1, 2")
            with self.assertRaises(BrokerDataError):
                adapter.refresh_scrip_master_safely(corrupt_path, target_file_path=scrip_path)

            # Active contracts and target file on disk remain intact!
            self.assertEqual(len(adapter._scrip_master_options), 10)
            with open(scrip_path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertEqual(len(on_disk), len(valid_records))

            # Conflicting duplicate contract token in Scrip Master must be rejected
            conflicting_records = list(valid_records) + [
                {
                    "token": "99999",
                    "symbol": "NIFTY22OCT202624800CE",
                    "name": "NIFTY",
                    "expiry": "22OCT2026",
                    "strike": "2480000.000000",
                    "lotsize": "75",
                    "instrumenttype": "OPTIDX",
                    "exch_seg": "NFO",
                }
            ]
            with self.assertRaises(BrokerDataError):
                adapter.refresh_scrip_master_safely(conflicting_records)
            self.assertEqual(len(adapter._scrip_master_options), 10)

            # Valid refresh with additional expiry atomically updates both file and memory
            updated_records = list(valid_records) + [
                {
                    "token": "68801",
                    "symbol": "NIFTY29OCT202624800CE",
                    "name": "NIFTY",
                    "expiry": "29OCT2026",
                    "strike": "2480000.000000",
                    "lotsize": "75",
                    "instrumenttype": "OPTIDX",
                    "exch_seg": "NFO",
                },
                {
                    "token": "68802",
                    "symbol": "NIFTY29OCT202624800PE",
                    "name": "NIFTY",
                    "expiry": "29OCT2026",
                    "strike": "2480000.000000",
                    "lotsize": "75",
                    "instrumenttype": "OPTIDX",
                    "exch_seg": "NFO",
                },
            ]
            ref_res = adapter.refresh_scrip_master_safely(updated_records, target_file_path=scrip_path)
            self.assertEqual(ref_res["status"], "REFRESHED")
            self.assertEqual(ref_res["index_options_loaded"], 12)
            self.assertEqual(adapter.get_expiry_list("NIFTY"), ["2026-10-22", "2026-10-29"])

    # 7. SQLite transaction rollback on batch error and multi-threaded concurrent access
    def test_p2b_sqlite_transaction_rollback_and_concurrent_baseline_access(self):
        import tempfile
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "concurrent_p2b.db")
            store = SQLitePersistenceStore(f"sqlite:///{db_path}")

            # 1) Transaction rollback: batch with 1 valid record + 1 invalid record (negative OI)
            # must roll back so 0 records are committed
            bad_batch = [
                {
                    "index_symbol": "NIFTY",
                    "expiry": "2026-10-22",
                    "strike": 24800,
                    "option_type": "CE",
                    "open_interest": 2100000,
                    "source": "angelone_live_quote",
                    "observation_timestamp": "2026-10-15 15:25:00",
                    "session_date": "2026-10-15",
                    "data_mode": "LIVE",
                },
                {
                    "index_symbol": "NIFTY",
                    "expiry": "2026-10-22",
                    "strike": 24800,
                    "option_type": "PE",
                    "open_interest": -500,  # Invalid negative OI
                    "source": "angelone_live_quote",
                    "observation_timestamp": "2026-10-15 15:25:00",
                    "session_date": "2026-10-15",
                    "data_mode": "LIVE",
                },
            ]
            with self.assertRaises(PersistenceValidationError):
                store.save_oi_baseline_records(bad_batch, now_ist=self.fixed_now)
            self.assertEqual(store.check_health()["oi_baselines_count"], 0)

            # 2) Seed valid strikes and test 16 concurrent reader/writer threads
            strikes_seed = {
                24700 + i * 50: {"ce_oi": 1500000 + i * 10000, "pe_oi": 2000000 + i * 10000}
                for i in range(6)
            }
            store.save_paired_strike_baselines(
                index_symbol="NIFTY",
                expiry="2026-10-22",
                baseline_by_strike=strikes_seed,
                session_date="2026-10-15",
                observation_timestamp="2026-10-15 15:10:00",
                source="angelone_live_quote",
                data_mode="LIVE",
                now_ist=self.fixed_now,
            )

            def _worker(tid: int):
                if tid % 2 == 0:
                    res = store.load_prior_session_oi_baseline(
                        "NIFTY", "2026-10-22", current_session_date="2026-10-16", data_mode="LIVE", now_ist=self.fixed_now
                    )
                    assert res["usable"] is True
                    assert res["paired_strikes_count"] == 6
                else:
                    # Idempotent re-write at same timestamp
                    store.save_paired_strike_baselines(
                        index_symbol="NIFTY",
                        expiry="2026-10-22",
                        baseline_by_strike=strikes_seed,
                        session_date="2026-10-15",
                        observation_timestamp="2026-10-15 15:10:00",
                        source="angelone_live_quote",
                        data_mode="LIVE",
                        now_ist=self.fixed_now,
                    )
                return True

            with ThreadPoolExecutor(max_workers=16) as pool:
                outcomes = list(pool.map(_worker, range(16)))
            self.assertTrue(all(outcomes))
            self.assertEqual(store.check_health()["oi_baselines_count"], 12)

    # 8. Scanner resilience, dashboard health/capability API reporting, and security protections
    def test_p2b_scanner_resilience_dashboard_health_api_and_security_controls(self):
        import tempfile
        from server import DashboardRequestHandler, configure_server_runtime, create_http_server

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "api_p2b.db")
            scrip_file = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            with open(scrip_file, "w", encoding="utf-8") as f:
                json.dump(self._build_scrip_master_fixture("22OCT2026"), f)

            cfg = BotConfig(
                active_broker="angelone",
                angel_api_key="SECRET_ANGEL_KEY_888",
                angel_client_code="A1234567",
                angel_pin="9876",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_file,
                database_url=f"sqlite:///{db_file}",
                telegram_dry_run=True,
            )
            engine, scheduler = configure_server_runtime(config=cfg, start_scheduler=False, clock=self.fixed_clock)
            httpd = create_http_server("127.0.0.1", 0, DashboardRequestHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            try:
                def _get_json(path):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                        return r.status, json.loads(r.read().decode("utf-8"))

                # 1) Before seeding baselines: health reports CONFIGURED_UNVERIFIED and Option Apex UNAVAILABLE_NO_PRIOR_BASELINE
                code_h1, h1 = _get_json("/api/health")
                self.assertEqual(code_h1, 200)
                self.assertEqual(h1["broker"]["connection_state"], "CONFIGURED_UNVERIFIED")
                self.assertFalse(h1["broker"]["connectivity_verified"])
                self.assertEqual(h1["broker"]["scrip_master"]["status"], "LOADED")
                self.assertEqual(h1["broker"]["option_apex"]["overall_status"], "UNAVAILABLE_NO_PRIOR_BASELINE")
                self.assertFalse(h1["broker"]["option_apex"]["usable"])
                self.assertTrue(h1["broker"]["option_apex"]["other_strategies_operational"])

                # 2) Seed NIFTY & BANKNIFTY prior-session baselines (2026-10-15)
                adapter = engine.broker.get_active_adapter()
                adapter.set_prior_oi_baseline(
                    "NIFTY",
                    "2026-10-22",
                    {
                        24750: {"ce_prev_oi": 1600000, "pe_prev_oi": 2100000},
                        24800: {"ce_prev_oi": 2270000, "pe_prev_oi": 2720000},
                        24850: {"ce_prev_oi": 2000000, "pe_prev_oi": 1800000},
                    },
                    session_date="2026-10-15",
                )
                adapter.set_prior_oi_baseline(
                    "BANKNIFTY",
                    "2026-10-22",
                    {
                        52400: {"ce_prev_oi": 900000, "pe_prev_oi": 1200000},
                        52500: {"ce_prev_oi": 950000, "pe_prev_oi": 1100000},
                    },
                    session_date="2026-10-15",
                )

                # Verify /api/health and /api/oi-baselines
                code_h2, h2 = _get_json("/api/health")
                self.assertEqual(code_h2, 200)
                self.assertEqual(h2["broker"]["option_apex"]["overall_status"], "READY")
                self.assertTrue(h2["broker"]["option_apex"]["usable"])
                # Still CONFIGURED_UNVERIFIED until a live scan completes!
                self.assertFalse(h2["broker"]["option_apex"]["live_verified"])
                self.assertEqual(h2["database"]["oi_baselines_count"], 10)

                code_b, b_payload = _get_json("/api/oi-baselines?index_symbol=NIFTY&data_mode=LIVE")
                self.assertEqual(code_b, 200)
                self.assertEqual(b_payload["total_count"], 6)

                # Verify no secrets in /api/health, /api/config, or /api/oi-baselines
                _, cfg_payload = _get_json("/api/config")
                combined_dump = json.dumps([h2, cfg_payload, b_payload])
                self.assertNotIn("SECRET_ANGEL_KEY_888", combined_dump)
                self.assertNotIn("9876", combined_dump)
                self.assertNotIn("JBSWY3DPEHPK3PXP", combined_dump)

                # Verify private files remain blocked (HTTP 404)
                for priv in ("/.env", "/brokers.py", "/storage.py", "/config.py"):
                    with self.assertRaises(urllib.error.HTTPError) as herr:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{priv}", timeout=5):
                            pass
                    with herr.exception:
                        self.assertEqual(herr.exception.code, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()



from diagnostics import run_angelone_diagnostics, format_diagnostics_report
from brokers import evaluate_candle_freshness, resolve_nse_session_dates


class TestIndianFOSignalBotPhase2C(unittest.TestCase):
    """
    Phase 2C Test Suite — Angel One Live-Data Acceptance, Diagnostic CLI & Redaction,
    Connection-State Honesty, Outside-Session Freshness, and OI Baseline Provenance.
    """

    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 10, 35, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now
        self.cfg = BotConfig(
            active_broker="angelone",
            angel_api_key="ANGEL_SUPER_SECRET_API_KEY_2C",
            angel_client_code="A9876543",
            angel_pin="7531",
            angel_totp_secret="JBSWY3DPEHPK3PXP",
            angel_request_timeout_seconds=5.0,
            angel_min_request_interval_seconds=0.0,
            angel_scrip_master_max_age_hours=24.0,
            angel_baseline_max_sessions_age=1,
            telegram_dry_run=True,
            database_url=":memory:",
        )
        self.sim = SimulatedNSEAdapter(clock=self.fixed_clock)

    @staticmethod
    def _mock_http_sequence(responses):
        iterator = iter(responses)

        def _urlopen(req, timeout=8):
            item = next(iterator)
            if isinstance(item, Exception):
                raise item
            body_bytes = item if isinstance(item, bytes) else json.dumps(item).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.read.return_value = body_bytes
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        return _urlopen

    @staticmethod
    def _build_scrip_master_fixture(expiry_angel="22OCT2026"):
        return TestIndianFOSignalBotPhase2B._build_scrip_master_fixture(expiry_angel=expiry_angel)

    # 1. Safe Local Diagnostic Command: 9 checks, offline/live modes, and strict secret redaction
    def test_p2c_diagnostic_command_checks_and_secret_redaction(self):
        import tempfile
        from brokers import generate_totp

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "diag_p2c.db")
            scrip_path = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            with open(scrip_path, "w", encoding="utf-8") as f:
                json.dump(self._build_scrip_master_fixture("22OCT2026"), f)

            cfg = BotConfig(
                active_broker="angelone",
                angel_api_key="ANGEL_SUPER_SECRET_API_KEY_2C",
                angel_client_code="A9876543",
                angel_pin="7531",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_path,
                database_url=f"sqlite:///{db_path}",
                telegram_dry_run=True,
            )

            # Seed prior-session closing baselines for NIFTY and BANKNIFTY on 2026-10-15 15:29:00 IST
            store = SQLitePersistenceStore(cfg.database_url)
            store.save_paired_strike_baselines(
                index_symbol="NIFTY",
                expiry="2026-10-22",
                baseline_by_strike={
                    24750: {"ce_oi": 1600000, "pe_oi": 2100000},
                    24800: {"ce_oi": 2270000, "pe_oi": 2720000},
                    24850: {"ce_oi": 2000000, "pe_oi": 1800000},
                },
                session_date="2026-10-15",
                observation_timestamp="2026-10-15 15:29:00",
                source="official_nse_bhavcopy_import",
                data_mode="LIVE",
                baseline_kind="CLOSING_BASELINE",
                now_ist=self.fixed_now,
            )
            store.save_paired_strike_baselines(
                index_symbol="BANKNIFTY",
                expiry="2026-10-22",
                baseline_by_strike={
                    52400: {"ce_oi": 900000, "pe_oi": 1200000},
                    52500: {"ce_oi": 950000, "pe_oi": 1100000},
                },
                session_date="2026-10-15",
                observation_timestamp="2026-10-15 15:29:00",
                source="official_nse_bhavcopy_import",
                data_mode="LIVE",
                baseline_kind="CLOSING_BASELINE",
                now_ist=self.fixed_now,
            )

            # Mode A: Offline diagnostic (run_live_requests=False) -> no network calls made
            with patch("urllib.request.urlopen", side_effect=AssertionError("Offline diagnostic must not call urlopen!")):
                report_offline = run_angelone_diagnostics(
                    config=cfg,
                    equity_symbol="RELIANCE",
                    run_live_requests=False,
                    clock=self.fixed_clock,
                )
            self.assertEqual(len(report_offline["checks"]), 9)
            by_id_off = {c["id"]: c for c in report_offline["checks"].values()}
            self.assertEqual(by_id_off[1]["status"], "PASS")
            self.assertEqual(by_id_off[2]["status"], "NOT CHECKED")
            self.assertEqual(by_id_off[3]["status"], "NOT CHECKED")
            self.assertEqual(by_id_off[4]["status"], "NOT CHECKED")
            self.assertEqual(by_id_off[5]["status"], "NOT CHECKED")
            self.assertEqual(by_id_off[6]["status"], "PASS")
            self.assertEqual(by_id_off[7]["status"], "PASS")
            self.assertEqual(by_id_off[8]["status"], "PASS")
            self.assertEqual(by_id_off[9]["status"], "PASS")

            # Mode B: Full live acceptance diagnostic with mocked Angel One responses
            login_resp = {
                "status": True,
                "message": "SUCCESS",
                "errorcode": "",
                "data": {
                    "jwtToken": "Bearer SUPER_SECRET_JWT_ACCESS_TOKEN_2C",
                    "refreshToken": "SUPER_SECRET_REFRESH_TOKEN_2C",
                    "feedToken": "SUPER_SECRET_FEED_TOKEN_2C",
                },
            }
            profile_resp = {
                "status": True,
                "message": "SUCCESS",
                "errorcode": "",
                "data": {
                    "clientcode": "A9876543",
                    "name": "Test Trader",
                    "exchanges": ["nse_cm", "nse_fo"],
                    "products": ["INTRADAY", "DELIVERY"],
                },
            }
            quotes_resp = {
                "status": True,
                "message": "SUCCESS",
                "errorcode": "",
                "data": {
                    "fetched": [
                        {
                            "exchange": "NSE",
                            "tradingSymbol": "NIFTY",
                            "symbolToken": "99926000",
                            "ltp": 24820.5,
                            "open": 24750.0,
                            "high": 24860.0,
                            "low": 24720.0,
                            "close": 24700.0,
                            "tradeVolume": 0,
                            "opnInterest": 0,
                            "exchFeedTime": "16-Oct-2026 10:34:55",
                        },
                        {
                            "exchange": "NSE",
                            "tradingSymbol": "BANKNIFTY",
                            "symbolToken": "99926009",
                            "ltp": 52460.0,
                            "open": 52300.0,
                            "high": 52550.0,
                            "low": 52250.0,
                            "close": 52280.0,
                            "tradeVolume": 0,
                            "opnInterest": 0,
                            "exchFeedTime": "16-Oct-2026 10:34:55",
                        },
                    ],
                    "unfetched": [],
                },
            }
            sim_bars = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, interval_min=5)
            candle_rows = [
                [b["timestamp"].replace(" ", "T") + "+05:30", b["open"], b["high"], b["low"], b["close"], b["volume"]]
                for b in sim_bars
            ]
            candles_resp = {"status": True, "message": "SUCCESS", "errorcode": "", "data": candle_rows}

            with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([login_resp, profile_resp, quotes_resp, candles_resp])):
                report_live = run_angelone_diagnostics(
                    config=cfg,
                    equity_symbol="RELIANCE",
                    run_live_requests=True,
                    clock=self.fixed_clock,
                )

            self.assertEqual(report_live["overall_status"], "PASS")
            self.assertEqual(report_live["connection_state"], "CONNECTED_VERIFIED")
            self.assertTrue(report_live["connectivity_verified"])
            for chk in report_live["checks"].values():
                self.assertEqual(chk["status"], "PASS", f"Expected PASS on check {chk['id']} ({chk['name']}): {chk['summary']}")

            formatted_text = format_diagnostics_report(report_live)
            serialized_json = json.dumps(report_live)
            current_totp = generate_totp(cfg.angel_totp_secret, for_time=self.fixed_now.timestamp())

            # Verify zero secret leakage in both formatted text and JSON report
            for secret_val in (
                cfg.angel_api_key,
                cfg.angel_pin,
                cfg.angel_totp_secret,
                current_totp,
                "SUPER_SECRET_JWT_ACCESS_TOKEN_2C",
                "SUPER_SECRET_REFRESH_TOKEN_2C",
                "SUPER_SECRET_FEED_TOKEN_2C",
            ):
                self.assertNotIn(secret_val, formatted_text)
                self.assertNotIn(secret_val, serialized_json)

            # Mode C: Failure redaction when authentication fails with secret echoed in error message
            auth_fail_resp = {
                "status": False,
                "message": f"Invalid key {cfg.angel_api_key} or pin {cfg.angel_pin} or totp {cfg.angel_totp_secret}",
                "errorcode": "AB1007",
                "data": None,
            }
            with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([auth_fail_resp])):
                report_fail = run_angelone_diagnostics(
                    config=cfg,
                    equity_symbol="RELIANCE",
                    run_live_requests=True,
                    clock=self.fixed_clock,
                )
            self.assertEqual(report_fail["overall_status"], "FAIL")
            by_id_fail = {c["id"]: c for c in report_fail["checks"].values()}
            self.assertEqual(by_id_fail[2]["status"], "FAIL")
            self.assertEqual(by_id_fail[3]["status"], "NOT CHECKED")
            self.assertEqual(by_id_fail[4]["status"], "NOT CHECKED")
            fail_dump = json.dumps(report_fail) + format_diagnostics_report(report_fail)
            self.assertNotIn(cfg.angel_api_key, fail_dump)
            self.assertNotIn(cfg.angel_pin, fail_dump)
            self.assertNotIn(cfg.angel_totp_secret, fail_dump)

    # 2. Connection-State Transitions: Auth/Profile alone never implies CONNECTED_VERIFIED
    def test_p2c_connection_state_transitions_and_auth_alone_not_verified(self):
        engine = IntradayBotEngine(self.cfg, clock=self.fixed_clock)
        adapter = engine.broker.get_active_adapter()

        # Step A: Configured credentials alone -> CONFIGURED_UNVERIFIED
        st0 = engine.get_broker_status()
        self.assertEqual(st0["connection_state"], "CONFIGURED_UNVERIFIED")
        self.assertFalse(st0["connectivity_verified"])
        self.assertFalse(adapter.is_connection_verified())

        # Step B: Successful authenticate() + get_profile() WITHOUT market data -> STILL CONFIGURED_UNVERIFIED!
        login_ok = {"status": True, "data": {"jwtToken": "TOK_1", "refreshToken": "REF_1"}}
        profile_ok = {"status": True, "data": {"clientcode": "A9876543", "name": "User", "exchanges": ["nse_cm"]}}
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([login_ok, profile_ok])):
            adapter.authenticate()
            adapter.get_profile()

        self.assertTrue(bool(adapter.jwt_token))
        self.assertIsNotNone(adapter.authenticated_at_ist)
        self.assertIsNone(adapter.last_market_data_at_ist)
        self.assertFalse(adapter.is_connection_verified())

        st1 = engine.get_broker_status()
        self.assertEqual(st1["connection_state"], "CONFIGURED_UNVERIFIED")
        self.assertFalse(st1["connectivity_verified"])

        # Step C: Actual market-data call (get_quote) succeeds -> transitions to CONNECTED_VERIFIED!
        quote_ok = {
            "status": True,
            "data": {
                "fetched": [
                    {
                        "exchange": "NSE",
                        "tradingSymbol": "NIFTY",
                        "symbolToken": "99926000",
                        "ltp": 24810.0,
                        "exchFeedTime": "16-Oct-2026 10:34:58",
                    }
                ],
                "unfetched": [],
            },
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([quote_ok])):
            q = adapter.get_quote("NIFTY", mode="LTP")
        self.assertEqual(q["ltp"], 24810.0)
        self.assertTrue(adapter.is_connection_verified())
        self.assertEqual(adapter.last_quote_timestamp_ist, "2026-10-16 10:34:58")

        st2 = engine.get_broker_status()
        self.assertEqual(st2["connection_state"], "CONNECTED_VERIFIED")
        self.assertTrue(st2["connectivity_verified"])
        self.assertEqual(st2["last_quote_timestamp_ist"], "2026-10-16 10:34:58")

        # Step D: Subsequent market-data error resets verification and sets honest ERROR state & category
        err_resp = {"status": False, "message": "Invalid Token", "errorcode": "AG8001", "data": None}
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([err_resp, err_resp, err_resp])):
            with self.assertRaises(BrokerDataError):
                adapter.get_quote("NIFTY", mode="LTP")

        self.assertFalse(adapter.is_connection_verified())
        self.assertEqual(adapter.last_error_category, "AUTH_FAILURE")
        st3 = engine.get_broker_status()
        self.assertEqual(st3["connection_state"], "ERROR")
        self.assertFalse(st3["connectivity_verified"])
        self.assertEqual(st3["last_error_category"], "AUTH_FAILURE")

    # 3. Malformed/stale quotes & candles and outside-market-session / holiday freshness semantics
    def test_p2c_malformed_stale_quotes_candles_and_outside_session_holiday_freshness(self):
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "VALID_JWT"

        # 1) Malformed quote (OHLC invariant violation: high < low)
        bad_ohlc_quote = {
            "status": True,
            "data": {
                "fetched": [
                    {
                        "exchange": "NSE",
                        "tradingSymbol": "NIFTY",
                        "symbolToken": "99926000",
                        "ltp": 24800.0,
                        "open": 24800.0,
                        "high": 24700.0,
                        "low": 24750.0,
                        "close": 24780.0,
                    }
                ],
                "unfetched": [],
            },
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([bad_ohlc_quote])):
            with self.assertRaises(BrokerDataError):
                adapter.get_quote("NIFTY", mode="OHLC")

        # 2) Stale candle during active market session (clock=10:35 IST, latest bar=09:15 IST, max_staleness=20m)
        stale_rows = [
            ["2026-10-16T09:15:00+05:30", 2940.0, 2945.0, 2938.0, 2942.0, 15000],
            ["2026-10-16T09:20:00+05:30", 2942.0, 2946.0, 2940.0, 2944.0, 16000],
        ]
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([{"status": True, "data": stale_rows}])):
            with self.assertRaises(BrokerDataError) as st_ctx:
                adapter.get_intraday_candles("RELIANCE", interval_min=5, max_staleness_minutes=20)
            self.assertIn("is stale", str(st_ctx.exception))
        self.assertEqual(adapter.last_error_category, "STALE_MARKET_DATA")
        self.assertEqual(adapter.last_candle_freshness["status"], "STALE")

        # 3) Outside-market-session freshness: On Saturday 2026-10-17 14:00 IST, a Friday 2026-10-16 15:25 IST
        # closing candle is FRESH_PRIOR_SESSION_CLOSE (not rejected as stale!)
        saturday_now = datetime(2026, 10, 17, 14, 0, 0, tzinfo=IST)
        sat_adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: saturday_now)
        sat_adapter.jwt_token = "VALID_JWT"
        friday_close_rows = [
            ["2026-10-16T15:20:00+05:30", 2950.0, 2955.0, 2948.0, 2952.0, 22000],
            ["2026-10-16T15:25:00+05:30", 2952.0, 2958.0, 2950.0, 2956.0, 28000],
        ]
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([{"status": True, "data": friday_close_rows}])):
            sat_candles = sat_adapter.get_intraday_candles("RELIANCE", interval_min=5, max_staleness_minutes=20)
        self.assertEqual(len(sat_candles), 2)
        self.assertEqual(sat_adapter.last_candle_freshness["status"], "FRESH_PRIOR_SESSION_CLOSE")
        self.assertTrue(sat_adapter.last_candle_freshness["is_fresh"])

        # 4) Holiday-aware session date resolution: if Friday 2026-10-16 is a configured holiday,
        # Saturday 2026-10-17 resolves effective session date to Thursday 2026-10-15!
        warmup_days, eff_day = resolve_nse_session_dates(
            saturday_now, warmup_sessions=3, configured_holidays=["2026-10-16"]
        )
        self.assertEqual(eff_day.strftime("%Y-%m-%d"), "2026-10-15")
        self.assertNotIn("2026-10-16", [d.strftime("%Y-%m-%d") for d in warmup_days])

    # 4. Incorrect instrument mappings & Scrip Master contract validation
    def test_p2c_incorrect_instrument_mappings_and_scrip_master_contract_validation(self):
        from brokers import validate_symbol_meta

        # Missing angel_token
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "RELIANCE"}, "angelone")

        # Non-digits angel_token
        with self.assertRaises(BrokerDataError):
            validate_symbol_meta({"symbol": "RELIANCE", "angel_token": "BAD_TOKEN"}, "angelone")

        # Unknown symbol string in resolve_instrument
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        with self.assertRaises(BrokerDataError):
            adapter.resolve_instrument("UNKNOWN_TICKER_XYZ")

        # Expired Scrip Master contracts -> Option Apex reports UNAVAILABLE_EXPIRED_CONTRACT
        expired_records = self._build_scrip_master_fixture("08OCT2026")
        adapter.load_scrip_master(expired_records)
        readiness = adapter.get_option_apex_readiness(now_ist=self.fixed_now)
        self.assertEqual(readiness["indices"]["NIFTY"]["status"], "UNAVAILABLE_EXPIRED_CONTRACTS")
        self.assertFalse(readiness["usable"])

    # 5. Session-expiry recovery, rate limits, and unavailable endpoint handling
    def test_p2c_session_expiry_recovery_and_unavailable_endpoint_handling(self):
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=self.fixed_clock)
        adapter.jwt_token = "EXPIRED_JWT"
        adapter.refresh_token = "EXPIRED_REFRESH"

        # 1) Session expiry AG8001 -> refresh fails -> relogin succeeds -> quote succeeds
        ag8001 = {"status": False, "message": "Invalid Token", "errorcode": "AG8001", "data": None}
        refresh_fail = {"status": False, "message": "Refresh Expired", "errorcode": "AG8002", "data": None}
        relogin_ok = {"status": True, "data": {"jwtToken": "NEW_JWT_2C", "refreshToken": "NEW_REF_2C"}}
        quote_ok = {
            "status": True,
            "data": {
                "fetched": [{"exchange": "NSE", "tradingSymbol": "NIFTY", "symbolToken": "99926000", "ltp": 24830.0}],
                "unfetched": [],
            },
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([ag8001, refresh_fail, relogin_ok, quote_ok])):
            q = adapter.get_quote("NIFTY", mode="LTP")
        self.assertEqual(q["ltp"], 24830.0)
        self.assertEqual(adapter.jwt_token, "NEW_JWT_2C")
        self.assertTrue(adapter.is_connection_verified())

        # 2) Unavailable endpoint / HTTP 503 error -> classified as NETWORK_API_FAILURE and never falls back to simulation
        with urllib.error.HTTPError(
            url="https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=None,
        ) as http_503:
            with patch("urllib.request.urlopen", side_effect=http_503):
                with self.assertRaises(BrokerDataError):
                    adapter.get_quote("NIFTY", mode="LTP")
            self.assertFalse(adapter.is_connection_verified())
            self.assertEqual(adapter.last_error_category, "NETWORK_API_FAILURE")

    # 6. OI Baseline Provenance: Block arbitrary intraday observations from becoming closing baselines
    def test_p2c_oi_baseline_provenance_and_invalid_closing_baseline_promotion_blocked(self):
        import tempfile
        from brokers import UnsupportedBrokerCapabilityError

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "provenance_p2c.db")
            scrip_file = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            with open(scrip_file, "w", encoding="utf-8") as f:
                json.dump(self._build_scrip_master_fixture("22OCT2026"), f)

            # Session T-1 at 10:35:00 IST (mid-day intraday, NOT session close!)
            thursday_intraday = datetime(2026, 10, 15, 10, 35, 0, tzinfo=IST)
            cfg_t1 = BotConfig(
                active_broker="angelone",
                angel_api_key="ANGEL_SUPER_SECRET_API_KEY_2C",
                angel_client_code="A9876543",
                angel_pin="7531",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_file,
                database_url=f"sqlite:///{db_file}",
                telegram_dry_run=True,
            )
            engine_t1 = IntradayBotEngine(cfg_t1, clock=lambda: thursday_intraday)
            adapter_t1 = engine_t1.broker.get_active_adapter()
            adapter_t1.jwt_token = "JWT_T1"

            spot_t1 = {
                "status": True,
                "data": {"fetched": [{"exchange": "NSE", "tradingSymbol": "NIFTY", "symbolToken": "99926000", "ltp": 24805.0}], "unfetched": []},
            }
            nfo_t1_intraday = {
                "status": True,
                "data": {
                    "fetched": [
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750CE", "symbolToken": "58701", "ltp": 150.0, "open": 145.0, "high": 155.0, "low": 140.0, "close": 148.0, "opnInterest": 1600000, "exchFeedTime": "15-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624750PE", "symbolToken": "58702", "ltp": 95.0, "open": 92.0, "high": 98.0, "low": 90.0, "close": 94.0, "opnInterest": 2100000, "exchFeedTime": "15-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800CE", "symbolToken": "58703", "ltp": 130.0, "open": 125.0, "high": 135.0, "low": 120.0, "close": 128.0, "opnInterest": 2270000, "exchFeedTime": "15-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624800PE", "symbolToken": "58704", "ltp": 120.0, "open": 118.0, "high": 125.0, "low": 115.0, "close": 119.0, "opnInterest": 2720000, "exchFeedTime": "15-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850CE", "symbolToken": "58705", "ltp": 105.0, "open": 100.0, "high": 110.0, "low": 98.0, "close": 104.0, "opnInterest": 2000000, "exchFeedTime": "15-Oct-2026 10:35:00"},
                        {"exchange": "NFO", "tradingSymbol": "NIFTY22OCT202624850PE", "symbolToken": "58706", "ltp": 145.0, "open": 140.0, "high": 150.0, "low": 138.0, "close": 142.0, "opnInterest": 1800000, "exchFeedTime": "15-Oct-2026 10:35:00"},
                    ],
                    "unfetched": [],
                },
            }
            with patch("urllib.request.urlopen", side_effect=self._mock_http_sequence([spot_t1, nfo_t1_intraday])):
                with self.assertRaises(UnsupportedBrokerCapabilityError):
                    adapter_t1.get_option_chain("NIFTY")

            # Verify the 10:35:00 IST snapshot was saved strictly as INTRADAY_OBSERVATION, NOT CLOSING_BASELINE!
            q_intra = engine_t1.store.query_oi_baselines(
                index_symbol="NIFTY", session_date="2026-10-15", baseline_kind="INTRADAY_OBSERVATION"
            )
            self.assertEqual(q_intra["total_count"], 6)
            q_closing = engine_t1.store.query_oi_baselines(
                index_symbol="NIFTY", session_date="2026-10-15", baseline_kind="CLOSING_BASELINE"
            )
            self.assertEqual(q_closing["total_count"], 0)

            # Now advance to Friday 2026-10-16 10:35:00 IST:
            # Because Thursday only had an INTRADAY_OBSERVATION (10:35 IST) and NO validated closing baseline,
            # Friday MUST NOT promote Thursday's 10:35 snapshot to a closing baseline!
            engine_t2 = IntradayBotEngine(cfg_t1, clock=self.fixed_clock)
            status_t2 = engine_t2.get_broker_status()
            nifty_ready = status_t2["option_apex"]["indices"]["NIFTY"]
            self.assertEqual(nifty_ready["status"], "UNAVAILABLE_NO_PRIOR_BASELINE")
            self.assertEqual(nifty_ready["sub_status"], "INTRADAY_OBSERVATION_ONLY")
            self.assertEqual(nifty_ready["intraday_only_records_present"], 6)
            self.assertFalse(status_t2["option_apex"]["usable"])

            # Explicitly calling set_prior_oi_baseline with an intraday timestamp (< 15:25 IST) must raise BrokerDataError
            adapter_t2 = engine_t2.broker.get_active_adapter()
            with self.assertRaises(BrokerDataError) as bad_promo_ctx:
                adapter_t2.set_prior_oi_baseline(
                    "NIFTY",
                    "2026-10-22",
                    {24800: {"ce_prev_oi": 2270000, "pe_prev_oi": 2720000}},
                    session_date="2026-10-15",
                    observation_timestamp="2026-10-15 11:15:00",
                    source="angelone_live_quote",
                )
            self.assertIn("15:25:00", str(bad_promo_ctx.exception))

            # Explicitly calling set_prior_oi_baseline with an intraday source must also raise BrokerDataError
            with self.assertRaises(BrokerDataError):
                adapter_t2.set_prior_oi_baseline(
                    "NIFTY",
                    "2026-10-22",
                    {24800: {"ce_prev_oi": 2270000, "pe_prev_oi": 2720000}},
                    session_date="2026-10-15",
                    observation_timestamp="2026-10-15 15:29:00",
                    source="angelone_live_intraday_observation",
                )

    # 7. Validated External Closing-Baseline Import Workflow (JSON & CSV)
    def test_p2c_validated_external_closing_baseline_import_workflow_json_and_csv(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "import_p2c.db")
            scrip_file = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            with open(scrip_file, "w", encoding="utf-8") as f:
                json.dump(self._build_scrip_master_fixture("22OCT2026"), f)

            cfg = BotConfig(
                active_broker="angelone",
                angel_api_key="ANGEL_SUPER_SECRET_API_KEY_2C",
                angel_client_code="A9876543",
                angel_pin="7531",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_file,
                database_url=f"sqlite:///{db_file}",
                telegram_dry_run=True,
            )
            engine = IntradayBotEngine(cfg, clock=self.fixed_clock)
            adapter = engine.broker.get_active_adapter()

            # 1) Import NIFTY closing baseline via JSON file
            nifty_json_path = os.path.join(tmpdir, "nifty_closing_baseline.json")
            nifty_json_payload = {
                "index_symbol": "NIFTY",
                "expiry": "2026-10-22",
                "session_date": "2026-10-15",
                "observation_timestamp": "2026-10-15 15:30:00",
                "source": "official_nse_bhavcopy_import",
                "data_mode": "LIVE",
                "strikes": {
                    "24750": {"ce_oi": 1600000, "pe_oi": 2100000},
                    "24800": {"ce_oi": 2270000, "pe_oi": 2720000},
                    "24850": {"ce_oi": 2000000, "pe_oi": 1800000},
                },
            }
            with open(nifty_json_path, "w", encoding="utf-8") as f:
                json.dump(nifty_json_payload, f)

            imp_json_res = adapter.import_prior_oi_baseline_file(nifty_json_path)
            self.assertEqual(imp_json_res["status"], "IMPORTED")
            self.assertEqual(imp_json_res["baseline_kind"], "CLOSING_BASELINE")
            self.assertEqual(imp_json_res["paired_strikes_count"], 3)

            # 2) Import BANKNIFTY closing baseline via CSV file
            bnf_csv_path = os.path.join(tmpdir, "banknifty_closing_baseline.csv")
            with open(bnf_csv_path, "w", encoding="utf-8") as f:
                f.write("index_symbol,expiry,strike,ce_oi,pe_oi,session_date,observation_timestamp,source\n")
                f.write("BANKNIFTY,2026-10-22,52400,900000,1200000,2026-10-15,2026-10-15 15:30:00,official_nse_bhavcopy_import\n")
                f.write("BANKNIFTY,2026-10-22,52500,950000,1100000,2026-10-15,2026-10-15 15:30:00,official_nse_bhavcopy_import\n")

            imp_csv_res = adapter.import_prior_oi_baseline_file(bnf_csv_path)
            self.assertEqual(imp_csv_res["status"], "IMPORTED")
            self.assertEqual(imp_csv_res["paired_strikes_count"], 2)

            # Verify both NIFTY and BANKNIFTY are now READY for Option Apex!
            readiness = adapter.get_option_apex_readiness(now_ist=self.fixed_now)
            self.assertEqual(readiness["overall_status"], "READY")
            self.assertTrue(readiness["usable"])

            # 3) Verify an intraday observation on 2026-10-15 CANNOT overwrite the imported CLOSING_BASELINE
            with self.assertRaises(PersistenceValidationError):
                engine.store.save_paired_strike_baselines(
                    index_symbol="NIFTY",
                    expiry="2026-10-22",
                    baseline_by_strike={24800: {"ce_oi": 999999, "pe_oi": 888888}},
                    session_date="2026-10-15",
                    observation_timestamp="2026-10-15 15:35:00",
                    source="angelone_live_intraday_observation",
                    data_mode="LIVE",
                    baseline_kind="INTRADAY_OBSERVATION",
                    now_ist=self.fixed_now,
                )

            # 4) Verify importing a same-day or incomplete baseline file is rejected
            bad_import_path = os.path.join(tmpdir, "bad_same_day.json")
            with open(bad_import_path, "w", encoding="utf-8") as f:
                json.dump(dict(nifty_json_payload, session_date="2026-10-16", observation_timestamp="2026-10-16 10:00:00"), f)
            with self.assertRaises(BrokerDataError):
                adapter.import_prior_oi_baseline_file(bad_import_path)

    # 8. Dashboard Health API, Baseline Kind Filtering, HTML Telemetry, and Private-File Security
    def test_p2c_dashboard_health_api_error_categories_and_private_file_protection(self):
        import tempfile
        from server import DashboardRequestHandler, configure_server_runtime, create_http_server

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "dashboard_p2c.db")
            scrip_file = os.path.join(tmpdir, "OpenAPIScripMaster.json")
            with open(scrip_file, "w", encoding="utf-8") as f:
                json.dump(self._build_scrip_master_fixture("22OCT2026"), f)

            cfg = BotConfig(
                active_broker="angelone",
                angel_api_key="ANGEL_SUPER_SECRET_API_KEY_2C",
                angel_client_code="A9876543",
                angel_pin="7531",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                angel_scrip_master_path=scrip_file,
                database_url=f"sqlite:///{db_file}",
                telegram_dry_run=True,
            )
            engine, _ = configure_server_runtime(config=cfg, start_scheduler=False, clock=self.fixed_clock)

            # Save 1 closing baseline pair on 2026-10-15 and 1 intraday observation pair on 2026-10-16
            engine.store.save_paired_strike_baselines(
                index_symbol="NIFTY",
                expiry="2026-10-22",
                baseline_by_strike={24800: {"ce_oi": 2270000, "pe_oi": 2720000}},
                session_date="2026-10-15",
                observation_timestamp="2026-10-15 15:29:00",
                source="angelone_live_closing_snapshot",
                data_mode="LIVE",
                baseline_kind="CLOSING_BASELINE",
                now_ist=self.fixed_now,
            )
            engine.store.save_paired_strike_baselines(
                index_symbol="NIFTY",
                expiry="2026-10-22",
                baseline_by_strike={24800: {"ce_oi": 1850000, "pe_oi": 3400000}},
                session_date="2026-10-16",
                observation_timestamp="2026-10-16 10:30:00",
                source="angelone_live_intraday_observation",
                data_mode="LIVE",
                baseline_kind="INTRADAY_OBSERVATION",
                now_ist=self.fixed_now,
            )

            httpd = create_http_server("127.0.0.1", 0, DashboardRequestHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            try:
                def _get_json(path):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                        return r.status, json.loads(r.read().decode("utf-8"))

                code_h, health = _get_json("/api/health")
                self.assertEqual(code_h, 200)
                self.assertEqual(health["database"]["oi_baselines_count"], 4)
                self.assertEqual(health["database"]["oi_closing_baselines_count"], 2)
                self.assertEqual(health["database"]["oi_intraday_observations_count"], 2)
                self.assertIn("last_market_data_at_ist", health["broker"])
                self.assertIn("candle_freshness", health["broker"])
                self.assertIn("last_error_category", health["broker"])

                # Query /api/oi-baselines filtered by baseline_kind
                _, b_closing = _get_json("/api/oi-baselines?baseline_kind=CLOSING_BASELINE")
                self.assertEqual(b_closing["total_count"], 2)
                _, b_intra = _get_json("/api/oi-baselines?baseline_kind=INTRADAY_OBSERVATION")
                self.assertEqual(b_intra["total_count"], 2)

                # Invalid baseline_kind returns HTTP 400
                with self.assertRaises(urllib.error.HTTPError) as b_err:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/oi-baselines?baseline_kind=INVALID", timeout=5):
                        pass
                with b_err.exception:
                    self.assertEqual(b_err.exception.code, 400)

                # Verify public/index.html contains Phase 2C telemetry fields
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r_html:
                    html_text = r_html.read().decode("utf-8")
                self.assertIn("Source Obs (IST):", html_text)
                self.assertIn("Last Market-Data Time (IST)", html_text)
                self.assertIn("Candle Freshness Status", html_text)
                self.assertIn("Closing Baselines:", html_text)

                # Verify private files including /diagnostics.py are blocked with HTTP 404
                for priv_path in ("/diagnostics.py", "/.env", "/brokers.py", "/storage.py", "/server.py"):
                    with self.assertRaises(urllib.error.HTTPError) as p_err:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{priv_path}", timeout=5):
                            pass
                    with p_err.exception:
                        self.assertEqual(p_err.exception.code, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()



import csv
from datetime import timezone
from historical_data import (
    HistoricalDataError,
    HistoricalDataValidationError,
    LookAheadBiasError,
    STRATEGY_HISTORICAL_DATA_REQUIREMENTS,
    compute_point_in_time_universe_breadth,
    evaluate_phase3a_backtest_readiness,
    generate_nse_session_bar_timestamps,
    get_point_in_time_candle_slice,
    list_expected_nse_trading_sessions,
    validate_and_prepare_historical_dataset,
    validate_bar_timestamp_on_nse_grid,
    verify_no_lookahead_leakage,
)


class TestIndianFOSignalBotPhase3A(unittest.TestCase):
    """
    Phase 3A Test Suite — Historical Market Data Quality, IST Session Grid Boundaries,
    Missing-Bar & Duplicate Detection, Provenance & Data-Mode Isolation, Look-Ahead
    Prevention, Resumable Idempotent Storage/Import, and Strategy 3 Historical Blocking.
    """

    def setUp(self):
        self.fixed_now = datetime(2026, 10, 16, 16, 0, 0, tzinfo=IST)
        self.fixed_clock = lambda: self.fixed_now

    @staticmethod
    def _build_session_bars(
        session_date_str: str,
        base_price: float = 2950.0,
        volume: float = 25000.0,
        data_mode: str = "LIVE",
        interval_min: int = 5,
    ):
        ts_list = generate_nse_session_bar_timestamps(session_date_str, interval_min=interval_min)
        bars = []
        for idx, ts in enumerate(ts_list):
            o = round(base_price + idx * 0.25, 2)
            c = round(o + 0.50, 2)
            h = round(max(o, c) + 0.75, 2)
            l = round(min(o, c) - 0.60, 2)
            bars.append({
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": volume + idx * 100.0,
                "open_interest": 0,
                "is_complete": True,
                "data_mode": data_mode,
                "is_simulated": data_mode == "SIMULATED",
            })
        return bars

    # 1. IST Timestamp Normalization, NSE Session Boundaries, Grid Alignment, Weekends & Holidays
    def test_p3a_timestamp_boundaries_grid_alignment_weekends_and_holidays(self):
        # 75 expected 5-minute bars per NSE session (09:15:00 through 15:25:00 IST)
        ts_list = generate_nse_session_bar_timestamps("2026-10-15", interval_min=5)
        self.assertEqual(len(ts_list), 75)
        self.assertEqual(ts_list[0], "2026-10-15 09:15:00")
        self.assertEqual(ts_list[-1], "2026-10-15 15:25:00")

        # Valid timestamp formats normalize to IST and record transformation tags
        # 2026-10-15 09:15:00 IST == 2026-10-15 03:45:00 UTC
        utc_dt = datetime(2026, 10, 15, 3, 45, 0, tzinfo=timezone.utc)
        epoch_sec = int(utc_dt.timestamp())
        _, ts_from_epoch, tr_epoch = validate_bar_timestamp_on_nse_grid(epoch_sec, interval_min=5)
        self.assertEqual(ts_from_epoch, "2026-10-15 09:15:00")
        self.assertEqual(tr_epoch, "epoch_sec_to_ist")

        _, ts_from_utc_iso, tr_iso = validate_bar_timestamp_on_nse_grid("2026-10-15T03:45:00Z", interval_min=5)
        self.assertEqual(ts_from_utc_iso, "2026-10-15 09:15:00")
        self.assertEqual(tr_iso, "iso8601_utc_to_ist")

        _, ts_from_angel, tr_angel = validate_bar_timestamp_on_nse_grid("15-Oct-2026 15:25:00", interval_min=5)
        self.assertEqual(ts_from_angel, "2026-10-15 15:25:00")
        self.assertEqual(tr_angel, "angel_feed_str_to_ist")

        # Invalid boundary timestamps must raise HistoricalDataValidationError
        invalid_timestamps = [
            "2026-10-15 09:10:00",  # Pre-open (< 09:15)
            "2026-10-15 15:30:00",  # Post-close bar start (15:30-15:35 exceeds 15:30 close)
            "2026-10-15 15:35:00",  # After market close
            "2026-10-15 10:17:00",  # Off 5-minute grid
            "2026-10-15 10:15:30",  # Non-zero seconds
            "2026-10-17 09:15:00",  # Saturday (weekend)
            "2026-10-18 10:00:00",  # Sunday (weekend)
        ]
        for bad_ts in invalid_timestamps:
            with self.assertRaises(HistoricalDataValidationError, msg=f"Should reject {bad_ts}"):
                validate_bar_timestamp_on_nse_grid(bad_ts, interval_min=5)

        # Configured NSE holiday must be rejected
        with self.assertRaises(HistoricalDataValidationError) as hol_ctx:
            validate_bar_timestamp_on_nse_grid(
                "2026-10-15 09:15:00", interval_min=5, configured_holidays=["2026-10-15"]
            )
        self.assertIn("holiday", str(hol_ctx.exception).lower())

    # 2. Missing Bars Audit & Multi-Session Gap Detection (Never Fabricating Missing Values)
    def test_p3a_missing_bars_audit_and_multi_session_gap_detection(self):
        bars_d1 = self._build_session_bars("2026-10-14", base_price=2940.0)
        bars_d2 = self._build_session_bars("2026-10-15", base_price=2960.0)

        # Drop 2 bars from 2026-10-14 (including 09:20:00 inside the 09:15-09:30 opening range) and 1 bar from 2026-10-15
        dropped = {"2026-10-14 09:20:00", "2026-10-14 11:15:00", "2026-10-15 14:00:00"}
        gapped_bars = [b for b in (bars_d1 + bars_d2) if b["timestamp"] not in dropped]
        self.assertEqual(len(gapped_bars), 147)

        res = validate_and_prepare_historical_dataset(
            candles=gapped_bars,
            symbol="RELIANCE",
            segment="NSE_EQUITY_INTRADAY",
            exchange="NSE",
            provider="angelone",
            instrument_token="2885",
            interval_min=5,
            data_mode="LIVE",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
        )
        manifest = res["manifest"]
        self.assertEqual(manifest["quality_status"], "INCOMPLETE_MISSING_BARS")
        self.assertEqual(manifest["bars_count"], 147)  # Never fabricates the 3 missing bars!
        self.assertEqual(manifest["missing_bars_count"], 3)
        self.assertEqual(set(manifest["missing_timestamps"]), dropped)
        self.assertFalse(manifest["sessions_summary"]["2026-10-14"]["opening_range_0915_0930_complete"])
        self.assertTrue(manifest["sessions_summary"]["2026-10-15"]["opening_range_0915_0930_complete"])

        # When require_complete_sessions=True, missing bars raise HistoricalDataValidationError
        with self.assertRaises(HistoricalDataValidationError):
            validate_and_prepare_historical_dataset(
                candles=gapped_bars,
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                exchange="NSE",
                provider="angelone",
                instrument_token="2885",
                interval_min=5,
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
                require_complete_sessions=True,
            )

        # Intermediate missing trading day audit: 2026-10-13 (Tue) + 2026-10-15 (Thu) with 2026-10-14 (Wed) missing
        bars_tue = self._build_session_bars("2026-10-13", base_price=2920.0)
        res_skip_wed = validate_and_prepare_historical_dataset(
            candles=bars_tue + bars_d2,
            symbol="RELIANCE",
            segment="NSE_EQUITY_INTRADAY",
            exchange="NSE",
            provider="angelone",
            instrument_token="2885",
            interval_min=5,
            data_mode="LIVE",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
        )
        self.assertEqual(res_skip_wed["manifest"]["missing_bars_count"], 75)

        # If 2026-10-14 is a configured NSE holiday, then 2026-10-13 + 2026-10-15 has 0 missing bars!
        res_holiday_wed = validate_and_prepare_historical_dataset(
            candles=bars_tue + bars_d2,
            symbol="RELIANCE",
            segment="NSE_EQUITY_INTRADAY",
            exchange="NSE",
            provider="angelone",
            instrument_token="2885",
            interval_min=5,
            data_mode="LIVE",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
            configured_holidays=["2026-10-14"],
        )
        self.assertEqual(res_holiday_wed["manifest"]["missing_bars_count"], 0)
        self.assertEqual(res_holiday_wed["manifest"]["quality_status"], "COMPLETE_VERIFIED")

    # 3. Duplicate Detection (Identical Coalescing vs Conflicting Rejection) & Reverse-Chronological Sorting
    def test_p3a_duplicate_bars_idempotent_coalescing_and_conflict_rejection(self):
        bars = self._build_session_bars("2026-10-15", base_price=2950.0)
        # Reverse order + 2 identical duplicate bars
        reversed_with_dups = list(reversed(bars)) + [dict(bars[0]), dict(bars[10])]

        res = validate_and_prepare_historical_dataset(
            candles=reversed_with_dups,
            symbol="RELIANCE",
            segment="NSE_EQUITY_INTRADAY",
            exchange="NSE",
            provider="angelone",
            instrument_token="2885",
            interval_min=5,
            data_mode="LIVE",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
            allow_identical_duplicates=True,
            sort_chronologically=True,
        )
        self.assertEqual(res["manifest"]["bars_count"], 75)
        self.assertEqual(res["manifest"]["duplicate_bars_coalesced"], 2)
        self.assertIn("sorted_chronologically", res["manifest"]["transformations"])
        self.assertIn("coalesced_identical_duplicates", res["manifest"]["transformations"])

        # Disallowing duplicates raises HistoricalDataValidationError even when identical
        with self.assertRaises(HistoricalDataValidationError):
            validate_and_prepare_historical_dataset(
                candles=bars + [dict(bars[0])],
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                exchange="NSE",
                provider="angelone",
                instrument_token="2885",
                interval_min=5,
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
                allow_identical_duplicates=False,
            )

        # Conflicting duplicate at same timestamp (different close price) ALWAYS raises HistoricalDataValidationError
        conflicting_bar = dict(bars[5], close=bars[5]["close"] + 12.5, high=bars[5]["high"] + 15.0)
        with self.assertRaises(HistoricalDataValidationError) as conf_ctx:
            validate_and_prepare_historical_dataset(
                candles=bars + [conflicting_bar],
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                exchange="NSE",
                provider="angelone",
                instrument_token="2885",
                interval_min=5,
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
                allow_identical_duplicates=True,
            )
        self.assertIn("Conflicting duplicate", str(conf_ctx.exception))

    # 4. Malformed OHLCV Records Rejection & Zero-Volume Index Audit
    def test_p3a_malformed_ohlcv_records_and_zero_volume_index_audit(self):
        base_bars = self._build_session_bars("2026-10-15", base_price=2950.0)

        malformed_mutations = [
            dict(base_bars[0], open=-10.0),
            dict(base_bars[0], high=base_bars[0]["low"] - 1.0),
            dict(base_bars[0], high=base_bars[0]["close"] - 0.5),
            dict(base_bars[0], low=base_bars[0]["open"] + 0.5),
            dict(base_bars[0], volume=-100.0),
            dict(base_bars[0], open_interest=-50),
            dict(base_bars[0], close=float("nan")),
            dict(base_bars[0], close=True),
            dict(base_bars[0], symbol="TCS"),  # Mismatched symbol inside RELIANCE dataset
        ]
        for bad_bar in malformed_mutations:
            with self.assertRaises(HistoricalDataValidationError):
                validate_and_prepare_historical_dataset(
                    candles=[bad_bar] + base_bars[1:],
                    symbol="RELIANCE",
                    segment="NSE_EQUITY_INTRADAY",
                    exchange="NSE",
                    provider="angelone",
                    instrument_token="2885",
                    interval_min=5,
                    data_mode="LIVE",
                    retrieved_at_ist=self.fixed_now,
                    reference_time_ist=self.fixed_now,
                )

        # NIFTY spot index dataset with volume=0 is audited as WARNING_ZERO_VOLUME
        nifty_zero_vol = self._build_session_bars("2026-10-15", base_price=24800.0, volume=0.0)
        for b in nifty_zero_vol:
            b["volume"] = 0.0
        nifty_res = validate_and_prepare_historical_dataset(
            candles=nifty_zero_vol,
            symbol="NIFTY",
            segment="NSE_FO_INDEX",
            exchange="NSE",
            provider="angelone",
            instrument_token="99926000",
            interval_min=5,
            data_mode="LIVE",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
        )
        self.assertEqual(nifty_res["manifest"]["quality_status"], "WARNING_ZERO_VOLUME")
        self.assertEqual(nifty_res["manifest"]["zero_volume_bars_count"], 75)

    # 5. Forming Candles & Strict Point-in-Time Look-Ahead Bias Prevention
    def test_p3a_forming_candles_and_strict_point_in_time_lookahead_prevention(self):
        bars = self._build_session_bars("2026-10-15", base_price=2950.0)
        # At 2026-10-15 10:32:00 IST:
        # - 10:25:00 bar (closes 10:30:00) is COMPLETE
        # - 10:30:00 bar (closes 10:35:00) is FORMING
        # - 10:35:00+ bars are IN THE FUTURE
        mid_session_ref = datetime(2026, 10, 15, 10, 32, 0, tzinfo=IST)

        # 1) reject_forming_candles=True rejects bars closing after 10:32:00 IST
        with self.assertRaises(HistoricalDataValidationError) as form_ctx:
            validate_and_prepare_historical_dataset(
                candles=bars[:16],  # 09:15 through 10:30
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                exchange="NSE",
                provider="angelone",
                instrument_token="2885",
                interval_min=5,
                data_mode="LIVE",
                retrieved_at_ist=mid_session_ref,
                reference_time_ist=mid_session_ref,
                reject_forming_candles=True,
            )
        self.assertIn("Forming or future candle rejected", str(form_ctx.exception))

        # 2) filter_forming_candles=True filters out 10:30:00+ and keeps the 15 completed bars (09:15..10:25)
        filtered_res = validate_and_prepare_historical_dataset(
            candles=bars[:16],
            symbol="RELIANCE",
            segment="NSE_EQUITY_INTRADAY",
            exchange="NSE",
            provider="angelone",
            instrument_token="2885",
            interval_min=5,
            data_mode="LIVE",
            retrieved_at_ist=mid_session_ref,
            reference_time_ist=mid_session_ref,
            reject_forming_candles=False,
            filter_forming_candles=True,
        )
        self.assertEqual(filtered_res["manifest"]["bars_count"], 15)
        self.assertEqual(filtered_res["candles"][-1]["timestamp"], "2026-10-15 10:25:00")
        self.assertIn("filtered_forming_candles", filtered_res["manifest"]["transformations"])

        # 3) get_point_in_time_candle_slice strictly prevents look-ahead bias
        pit_slice = get_point_in_time_candle_slice(
            bars, decision_time_ist="2026-10-15 10:32:00", interval_min=5, expected_data_mode="LIVE"
        )
        self.assertEqual(len(pit_slice), 15)
        self.assertEqual(pit_slice[-1]["timestamp"], "2026-10-15 10:25:00")

        # At exact bar close 10:35:00 IST, the 10:30:00 bar is now complete (16 bars)
        pit_1035 = get_point_in_time_candle_slice(
            bars, decision_time_ist="2026-10-15 10:35:00", interval_min=5, expected_data_mode="LIVE"
        )
        self.assertEqual(len(pit_1035), 16)
        self.assertEqual(pit_1035[-1]["timestamp"], "2026-10-15 10:30:00")

        # Passing an unclosed/forming bar directly to verify_no_lookahead_leakage raises LookAheadBiasError
        with self.assertRaises(LookAheadBiasError):
            verify_no_lookahead_leakage(bars[:16], decision_time_ist="2026-10-15 10:32:00", interval_min=5)

        # 4) Point-in-time universe breadth never peeks at afternoon reversals
        rel_bars = self._build_session_bars("2026-10-15", base_price=2950.0)
        tcs_bars = self._build_session_bars("2026-10-15", base_price=4100.0)
        # Make TCS bearish up to 10:25 IST, then rally strongly after 14:00 IST
        for idx, b in enumerate(tcs_bars):
            if idx < 20:
                b["close"] = round(tcs_bars[0]["open"] - 15.0, 2)
                b["low"] = round(b["close"] - 2.0, 2)
            else:
                b["close"] = round(tcs_bars[0]["open"] + 50.0, 2)
                b["high"] = round(b["close"] + 5.0, 2)

        breadth_morning = compute_point_in_time_universe_breadth(
            {"RELIANCE": rel_bars, "TCS": tcs_bars},
            decision_time_ist="2026-10-15 10:30:00",
            interval_min=5,
            expected_data_mode="LIVE",
        )
        self.assertEqual(breadth_morning["advances"], 1)
        self.assertEqual(breadth_morning["declines"], 1)

        breadth_eod = compute_point_in_time_universe_breadth(
            {"RELIANCE": rel_bars, "TCS": tcs_bars},
            decision_time_ist="2026-10-15 15:30:00",
            interval_min=5,
            expected_data_mode="LIVE",
        )
        self.assertEqual(breadth_eod["advances"], 2)
        self.assertEqual(breadth_eod["declines"], 0)

    # 6. Strict LIVE vs SIMULATED Data-Mode Isolation
    def test_p3a_data_mode_isolation_between_live_and_simulated_datasets(self):
        live_bars = self._build_session_bars("2026-10-15", base_price=2950.0, data_mode="LIVE")
        sim_bars = self._build_session_bars("2026-10-15", base_price=2950.0, data_mode="SIMULATED")

        # 1) Simulated provider rejected in LIVE dataset
        with self.assertRaises(HistoricalDataValidationError):
            validate_and_prepare_historical_dataset(
                candles=live_bars,
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                exchange="NSE",
                provider="paper_sim",
                instrument_token="2885",
                interval_min=5,
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
            )

        # 2) Simulated bar inside LIVE dataset rejected
        mixed_bars = list(live_bars)
        mixed_bars[10] = dict(mixed_bars[10], is_simulated=True, data_mode="SIMULATED")
        with self.assertRaises(HistoricalDataValidationError):
            validate_and_prepare_historical_dataset(
                candles=mixed_bars,
                symbol="RELIANCE",
                segment="NSE_EQUITY_INTRADAY",
                exchange="NSE",
                provider="angelone",
                instrument_token="2885",
                interval_min=5,
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
            )

        # 3) get_point_in_time_candle_slice rejects mixed LIVE + SIMULATED bars
        with self.assertRaises(HistoricalDataValidationError):
            get_point_in_time_candle_slice(
                [live_bars[0], sim_bars[1]], decision_time_ist=self.fixed_now, interval_min=5
            )

        # 4) SQLite storage strictly isolates LIVE and SIMULATED historical candles
        store = SQLitePersistenceStore(":memory:")
        store.save_historical_candle_dataset(
            candles=live_bars,
            symbol="RELIANCE",
            provider="angelone",
            instrument_token="2885",
            data_mode="LIVE",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
        )
        store.save_historical_candle_dataset(
            candles=sim_bars,
            symbol="RELIANCE",
            provider="paper_sim",
            instrument_token="2885",
            data_mode="SIMULATED",
            retrieved_at_ist=self.fixed_now,
            reference_time_ist=self.fixed_now,
        )
        q_live = store.query_historical_candles("RELIANCE", data_mode="LIVE")
        q_sim = store.query_historical_candles("RELIANCE", data_mode="SIMULATED")
        self.assertEqual(q_live["total_count"], 75)
        self.assertEqual(q_sim["total_count"], 75)
        self.assertTrue(all(not b["is_simulated"] and b["data_mode"] == "LIVE" for b in q_live["items"]))
        self.assertTrue(all(b["is_simulated"] and b["data_mode"] == "SIMULATED" for b in q_sim["items"]))

    # 7. Resumable, Idempotent SQLite Storage, JSON/CSV Import Workflow & Watermark Tracking
    def test_p3a_resumable_idempotent_storage_json_csv_import_and_watermark(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "hist_p3a.db")
            store = SQLitePersistenceStore(f"sqlite:///{db_path}")

            bars_s1 = self._build_session_bars("2026-10-14", base_price=2930.0)
            bars_s2 = self._build_session_bars("2026-10-15", base_price=2955.0)

            # Step 1: Import Session 1 via JSON file
            json_path = os.path.join(tmpdir, "rel_s1.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "symbol": "RELIANCE",
                        "segment": "NSE_EQUITY_INTRADAY",
                        "exchange": "NSE",
                        "provider": "angelone",
                        "instrument_token": "2885",
                        "interval_min": 5,
                        "data_mode": "LIVE",
                        "retrieved_at_ist": "2026-10-16 16:00:00",
                        "reference_time_ist": "2026-10-16 16:00:00",
                        "candles": bars_s1,
                    },
                    f,
                )
            imp1 = store.import_historical_candles_file(json_path)
            self.assertEqual(imp1["inserted_count"], 75)
            self.assertEqual(imp1["unchanged_count"], 0)

            wm1 = store.get_historical_ingestion_watermark("RELIANCE", interval_min=5, data_mode="LIVE", provider="angelone")
            self.assertEqual(wm1["stored_bars_count"], 75)
            self.assertEqual(wm1["stored_session_dates"], ["2026-10-14"])
            self.assertEqual(wm1["latest_timestamp_ist"], "2026-10-14 15:25:00")

            # Step 2: Resumable import of overlapping Session 1 + Session 2 via CSV file
            csv_path = os.path.join(tmpdir, "rel_s1_s2.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "open_interest"])
                for b in bars_s1 + bars_s2:
                    writer.writerow([b["timestamp"], b["open"], b["high"], b["low"], b["close"], b["volume"], b["open_interest"]])

            imp2 = store.import_historical_candles_file(
                csv_path,
                default_symbol="RELIANCE",
                default_provider="angelone",
                default_instrument_token="2885",
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
            )
            self.assertEqual(imp2["inserted_count"], 75)
            self.assertEqual(imp2["unchanged_count"], 75)

            wm2 = store.get_historical_ingestion_watermark("RELIANCE", interval_min=5, data_mode="LIVE", provider="angelone")
            self.assertEqual(wm2["stored_bars_count"], 150)
            self.assertEqual(wm2["stored_session_dates"], ["2026-10-14", "2026-10-15"])

            # Step 3: Conflicting bar in a batch rolls back the entire transaction!
            corrupted_s2 = [dict(bars_s2[0], close=bars_s2[0]["close"] + 99.0, high=bars_s2[0]["high"] + 105.0)] + bars_s2[1:]
            with self.assertRaises(PersistenceValidationError):
                store.save_historical_candle_dataset(
                    candles=corrupted_s2,
                    symbol="RELIANCE",
                    provider="angelone",
                    instrument_token="2885",
                    data_mode="LIVE",
                    retrieved_at_ist=self.fixed_now,
                    reference_time_ist=self.fixed_now,
                )
            self.assertEqual(store.check_health()["historical_candles_count"], 150)

            # Step 4: Query with decision_time_ist enforces look-ahead guard at the SQL query layer
            q_pit = store.query_historical_candles(
                "RELIANCE",
                data_mode="LIVE",
                provider="angelone",
                decision_time_ist="2026-10-14 09:30:00",
            )
            # At 09:30:00 IST, only 09:15:00, 09:20:00, and 09:25:00 bars have closed!
            self.assertEqual(q_pit["total_count"], 3)
            self.assertEqual([b["timestamp"] for b in q_pit["items"]], [
                "2026-10-14 09:15:00",
                "2026-10-14 09:20:00",
                "2026-10-14 09:25:00",
            ])

    # 8. Phase 2C Live-Acceptance Gate, Strategy 3 Option Apex Historical Block & HTTP Security
    def test_p3a_phase2c_gate_strategy3_option_apex_blocked_and_http_security(self):
        import tempfile
        from server import DashboardRequestHandler, configure_server_runtime, create_http_server

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "readiness_p3a.db")
            cfg = BotConfig(
                active_broker="angelone",
                angel_api_key="ANGEL_SUPER_SECRET_API_KEY_3A",
                angel_client_code="A9876543",
                angel_pin="7531",
                angel_totp_secret="JBSWY3DPEHPK3PXP",
                database_url=f"sqlite:///{db_file}",
                telegram_dry_run=True,
            )
            engine, _ = configure_server_runtime(config=cfg, start_scheduler=False, clock=self.fixed_clock)

            # Seed 3 full sessions (225 bars >= 200 for 200 EMA) for RELIANCE
            bars_3_sessions = (
                self._build_session_bars("2026-10-13", base_price=2910.0)
                + self._build_session_bars("2026-10-14", base_price=2930.0)
                + self._build_session_bars("2026-10-15", base_price=2950.0)
            )
            engine.store.save_historical_candle_dataset(
                candles=bars_3_sessions,
                symbol="RELIANCE",
                provider="angelone",
                instrument_token="2885",
                data_mode="LIVE",
                retrieved_at_ist=self.fixed_now,
                reference_time_ist=self.fixed_now,
            )

            httpd = create_http_server("127.0.0.1", 0, DashboardRequestHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            try:
                def _get_json(path):
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                        return r.status, json.loads(r.read().decode("utf-8"))

                # 1) Verify /api/historical-datasets returns stored manifest with zero secrets
                code_ds, ds_payload = _get_json("/api/historical-datasets?symbol=RELIANCE&data_mode=LIVE")
                self.assertEqual(code_ds, 200)
                self.assertEqual(ds_payload["total_count"], 1)
                self.assertEqual(ds_payload["items"][0]["bars_count"], 225)
                self.assertEqual(ds_payload["items"][0]["quality_status"], "COMPLETE_VERIFIED")

                # 2) Verify /api/historical-readiness blocks Phase 3 execution when Phase 2C live acceptance is incomplete
                code_rd, rd_payload = _get_json("/api/historical-readiness?data_mode=LIVE")
                self.assertEqual(code_rd, 200)
                self.assertFalse(rd_payload["phase2c_live_accepted"])
                self.assertFalse(rd_payload["phase3_ready_for_execution"])
                self.assertEqual(rd_payload["overall_gate_status"], "BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED")

                # RELIANCE has 225 bars so Strategies 1, 2, 4, 5 report DATA_READY on RELIANCE,
                # while Strategy 3 (Option Apex) is strictly BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN!
                strats = rd_payload["strategies_readiness"]
                self.assertEqual(strats["strat_1_order_block"]["status"], "DATA_READY")
                self.assertEqual(strats["strat_2_vwap_pullback"]["status"], "DATA_READY")
                self.assertEqual(strats["strat_4_orb_filtered"]["status"], "DATA_READY")
                self.assertEqual(strats["strat_5_supertrend_pullback"]["status"], "DATA_READY")
                self.assertEqual(strats["strat_3_option_apex_oi"]["status"], "BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN")

                # 3) Verify /historical_data.py and all private files remain blocked with HTTP 404
                for priv in ("/historical_data.py", "/diagnostics.py", "/.env", "/storage.py", "/brokers.py"):
                    with self.assertRaises(urllib.error.HTTPError) as p_err:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{priv}", timeout=5):
                            pass
                    with p_err.exception:
                        self.assertEqual(p_err.exception.code, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()




from typing import Any, Dict, List, Optional, Tuple


class TestIndianFOSignalBotPhase3B(unittest.TestCase):
    """
    Phase 3B Regression & Verification Suite:
    Covers deterministic point-in-time candle replay, strict no-look-ahead guarantees,
    next-candle open execution, hand-calculated long/short trade accounting, conservative
    same-candle stop/target collision handling, missing-bar and opening gaps, session EOD
    square-off, daily loss/profit limits, position sizing, itemized Indian market costs,
    zero-trade and zero-loss edge cases, Phase 2C/3A readiness gates, LIVE vs SIMULATED
    isolation, Strategy 3 historical option-chain blocking, chronological period splits,
    reproducibility, HTTP API validation, and ResourceWarning-free SQLite cleanup.
    """

    def setUp(self) -> None:
        from brokers import SimulatedNSEAdapter
        from strategies import IST

        self.fixed_now = datetime(2026, 10, 16, 15, 30, tzinfo=IST)
        self.sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.fixed_now)

    def _build_fixture_with_followup_bars(
        self,
        symbol: str,
        pattern: str,
        followup_bars: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        base_bars = self.sim.get_intraday_candles(
            {"symbol": symbol},
            interval_min=5,
            pattern=pattern,
        )
        for fb in followup_bars:
            row = dict(fb)
            row.setdefault("is_complete", True)
            row.setdefault("is_simulated", True)
            row.setdefault("data_mode", "SIMULATED")
            base_bars.append(row)
        return base_bars

    def test_p3b_01_historical_replay_ordering_and_no_lookahead_guarantees(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        # Build a deterministic order_block_bull fixture on RELIANCE (signal at 10:30:00 IST)
        bars_a = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2952.00,
                    "high": 2960.00,
                    "low": 2948.00,
                    "close": 2955.00,
                    "volume": 95000,
                },
                {
                    "timestamp": "2026-10-16 10:40:00",
                    "open": 2955.00,
                    "high": 2995.00,
                    "low": 2950.00,
                    "close": 2990.00,
                    "volume": 110000,
                },
            ],
        )

        # Shuffle input order to verify deterministic chronological sorting before replay
        shuffled_bars = list(reversed(bars_a))

        bt_cfg = BacktestConfig(
            starting_capital_inr=100000.0,
            risk_per_trade_pct=1.0,
            cost_model=IndianCostModel(slippage_bps_per_leg=0.0),
        )
        engine = DeterministicBacktestEngine()
        res_ordered = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_a,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        res_shuffled = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=shuffled_bars,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        self.assertEqual(res_ordered["dataset_checksum"], res_shuffled["dataset_checksum"])
        self.assertEqual(res_ordered["trades"], res_shuffled["trades"])
        self.assertEqual(len(res_ordered["trades"]), 1)

        # Prove no look-ahead bias: mutating a future bar (10:45:00) after the trade exited at 10:40:00
        # cannot alter the signal at 10:30:00, the entry at 10:35:00, or the exit at 10:40:00.
        bars_with_future_crash = list(bars_a) + [
            {
                "timestamp": "2026-10-16 10:45:00",
                "open": 2990.00,
                "high": 2991.00,
                "low": 2500.00,
                "close": 2510.00,
                "volume": 500000,
                "is_complete": True,
                "is_simulated": True,
                "data_mode": "SIMULATED",
            }
        ]
        res_future = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_with_future_crash,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        t_orig = res_ordered["trades"][0]
        t_fut = res_future["trades"][0]
        self.assertEqual(t_orig["signal_timestamp"], "2026-10-16 10:30:00")
        self.assertEqual(t_orig["entry_timestamp"], "2026-10-16 10:35:00")
        self.assertEqual(t_orig["exit_timestamp"], "2026-10-16 10:40:00")
        self.assertEqual(t_orig["entry_price"], t_fut["entry_price"])
        self.assertEqual(t_orig["exit_price"], t_fut["exit_price"])
        self.assertEqual(t_orig["net_pnl_inr"], t_fut["net_pnl_inr"])

    def test_p3b_02_signal_timing_next_candle_open_execution_and_hand_calculated_long_trade(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        # Signal on RELIANCE (order_block_bull) triggers at 10:30:00 close:
        # Verified signal levels on RELIANCE order_block_bull:
        # sig.entry_price = 2955.74, sig.stop_loss = 2937.72, sig.target_1 = 2991.78, sig.target_2 = 3009.80
        # Next bar (10:35:00) opens at 2957.72 -> risk_per_unit = 2957.72 - 2937.72 = 20.00 INR!
        # With starting_capital = 200,000 INR and risk_per_trade_pct = 0.5% (risk_budget = 1,000 INR):
        # 45 shares: raw stop risk 900.00 + 93.86 stop charges = 993.86 <= 1000.
        # 46 shares would require 1014.88, so they are rejected by the same budget.
        # Raw entry/target remain unchanged: (2991.78 - 2957.72) * 45 = 1532.70.
        bars = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2957.72,
                    "high": 2965.00,
                    "low": 2945.00,
                    "close": 2960.00,
                    "volume": 80000,
                },
                {
                    "timestamp": "2026-10-16 10:40:00",
                    "open": 2960.00,
                    "high": 2995.00,
                    "low": 2955.00,
                    "close": 2988.00,
                    "volume": 90000,
                },
            ],
        )

        cost_model = IndianCostModel(
            brokerage_per_order_inr=20.0,
            brokerage_max_pct_per_leg=None,  # flat 20 INR per order leg = 40 INR round-trip
            slippage_bps_per_leg=0.0,
        )
        bt_cfg = BacktestConfig(
            starting_capital_inr=200000.0,
            risk_per_trade_pct=0.5,
            cost_model=cost_model,
        )
        engine = DeterministicBacktestEngine()
        res = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )

        self.assertEqual(len(res["trades"]), 1)
        trade = res["trades"][0]
        self.assertEqual(trade["signal_timestamp"], "2026-10-16 10:30:00")
        self.assertEqual(trade["entry_timestamp"], "2026-10-16 10:35:00")
        self.assertEqual(trade["exit_timestamp"], "2026-10-16 10:40:00")
        self.assertEqual(trade["position_side"], "LONG")
        self.assertEqual(trade["raw_entry_price"], 2957.72)
        self.assertEqual(trade["raw_exit_price"], 2991.78)
        self.assertEqual(trade["quantity"], 45)
        self.assertEqual(trade["exit_reason"], "TARGET_1")
        self.assertFalse(trade["same_candle_collision"])
        self.assertEqual(trade["gross_pnl_inr"], 1532.70)
        self.assertEqual(trade["risk_amount_inr"], 993.86)

        # Independent costs for buy=133097.40, sell=134630.10, total=267727.50:
        # brokerage 40 + STT 33.66 + exchange 7.95 + SEBI .27 + stamp 3.99 + GST 8.68 = 94.55.
        # Net = 1532.70 - 94.55 = 1438.15; R = 1438.15 / 993.86.
        cb = trade["cost_breakdown"]
        self.assertEqual(cb["brokerage_inr"], 40.00)
        self.assertEqual(cb["stt_inr"], 33.66)
        self.assertEqual(cb["exchange_txn_charge_inr"], 7.95)
        self.assertEqual(cb["sebi_charge_inr"], 0.27)
        self.assertEqual(cb["stamp_duty_inr"], 3.99)
        self.assertEqual(cb["gst_inr"], 8.68)
        self.assertEqual(trade["charges_inr"], 94.55)
        self.assertEqual(trade["total_costs_inr"], 94.55)
        self.assertEqual(trade["net_pnl_inr"], 1438.15)
        self.assertEqual(trade["realized_r_multiple"], 1.447)

    def test_p3b_03_hand_calculated_short_trade_entry_target_and_stop_accounting(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel
        from strategies import evaluate_order_block_fvg

        # Inspect exact bearish signal levels on RELIANCE order_block_bear at 10:30:00 IST
        base_bear = self.sim.get_intraday_candles(
            {"symbol": "RELIANCE"},
            interval_min=5,
            pattern="order_block_bear",
        )
        sig_bear = evaluate_order_block_fvg("RELIANCE", base_bear, now=self.fixed_now)
        self.assertIsNotNone(sig_bear)
        assert sig_bear is not None
        self.assertIn("BEARISH", sig_bear.direction)

        # Next bar (10:35:00) opens at sig_bear.stop_loss - 10.00 so risk_per_unit = 10.00 INR -> qty = 100 shares!
        # And on 10:35:00 bar, low reaches sig_bear.target_1 while high stays below sig_bear.stop_loss.
        raw_open = round(sig_bear.stop_loss - 10.0, 2)
        bars = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bear",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": raw_open,
                    "high": round(sig_bear.stop_loss - 2.0, 2),
                    "low": round(sig_bear.target_1 - 5.0, 2),
                    "close": sig_bear.target_1,
                    "volume": 95000,
                },
            ],
        )

        bt_cfg = BacktestConfig(
            starting_capital_inr=500000.0,
            risk_per_trade_pct=0.2,  # risk budget 1000 INR; stop charges reduce the maximum to 86 shares
            cost_model=IndianCostModel(brokerage_max_pct_per_leg=None, slippage_bps_per_leg=0.0),
        )
        engine = DeterministicBacktestEngine()
        res = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )

        self.assertEqual(len(res["trades"]), 1)
        trade = res["trades"][0]
        self.assertEqual(trade["position_side"], "SHORT")
        self.assertEqual(trade["quantity"], 86)
        self.assertEqual(trade["exit_reason"], "TARGET_1")
        expected_gross = round((raw_open - sig_bear.target_1) * 86, 2)
        self.assertEqual(trade["gross_pnl_inr"], expected_gross)
        # Verify STT was charged on the SELL (entry) leg and Stamp Duty on the BUY (exit) leg
        self.assertEqual(trade["cost_breakdown"]["sell_turnover_inr"], round(raw_open * 86, 2))
        self.assertEqual(trade["cost_breakdown"]["buy_turnover_inr"], round(sig_bear.target_1 * 86, 2))
        self.assertEqual(res["metrics"]["long_vs_short_performance"]["SHORT"]["trades"], 1)
        self.assertEqual(res["metrics"]["long_vs_short_performance"]["LONG"]["trades"], 0)

    def test_p3b_04_same_candle_stop_target_collision_conservative_long_and_short(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        engine = DeterministicBacktestEngine()
        bt_cfg = BacktestConfig(
            starting_capital_inr=100000.0,
            risk_per_trade_pct=1.0,
            cost_model=IndianCostModel(slippage_bps_per_leg=0.0),
        )

        # 1. LONG trade where 10:35:00 candle breaches BOTH stop_loss (2931.78) and target_1 (2987.34)
        bars_long_collision = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2995.00,  # >= target_1 (2987.34)
                    "low": 2925.00,   # <= stop_loss (2931.78)
                    "close": 2980.00,
                    "volume": 120000,
                },
            ],
        )
        res_long = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_long_collision,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        self.assertEqual(len(res_long["trades"]), 1)
        t_long = res_long["trades"][0]
        self.assertTrue(t_long["same_candle_collision"])
        self.assertEqual(t_long["exit_reason"], "STOP_LOSS_SAME_CANDLE_CONSERVATIVE")
        self.assertEqual(t_long["raw_exit_price"], t_long["stop_loss"])
        self.assertLess(t_long["net_pnl_inr"], 0.0)

        # 2. SHORT trade where 10:35:00 candle breaches BOTH stop_loss and target_1
        bars_short_collision = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bear",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2930.00,
                    "high": 3050.00,  # >= stop_loss
                    "low": 2800.00,   # <= target_1
                    "close": 2850.00,
                    "volume": 120000,
                },
            ],
        )
        res_short = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_short_collision,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        self.assertEqual(len(res_short["trades"]), 1)
        t_short = res_short["trades"][0]
        self.assertTrue(t_short["same_candle_collision"])
        self.assertEqual(t_short["exit_reason"], "STOP_LOSS_SAME_CANDLE_CONSERVATIVE")
        self.assertEqual(t_short["raw_exit_price"], t_short["stop_loss"])
        self.assertLess(t_short["net_pnl_inr"], 0.0)

    def test_p3b_05_gap_handling_missing_next_candle_and_gap_beyond_stop_or_target(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        engine = DeterministicBacktestEngine()
        bt_cfg = BacktestConfig(
            starting_capital_inr=100000.0,
            risk_per_trade_pct=1.0,
            cost_model=IndianCostModel(slippage_bps_per_leg=0.0),
        )

        # Case A: Missing 10:35:00 bar after 10:30:00 signal (jumps directly to 10:40:00)
        bars_missing_next = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:40:00",
                    "open": 2952.00,
                    "high": 2995.00,
                    "low": 2948.00,
                    "close": 2990.00,
                    "volume": 95000,
                },
            ],
        )
        res_gap_reject = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_missing_next,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        self.assertEqual(len(res_gap_reject["trades"]), 0)
        self.assertEqual(res_gap_reject["metrics"]["rejected_signals_by_reason"].get("MISSING_NEXT_CANDLE_GAP"), 1)

        # Case B: Next bar (10:35:00) opens below stop_loss (2931.78) -> rejected entry
        bars_open_below_sl = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2925.00,
                    "high": 2940.00,
                    "low": 2920.00,
                    "close": 2935.00,
                    "volume": 95000,
                },
            ],
        )
        res_open_sl = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_open_below_sl,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        self.assertEqual(len(res_open_sl["trades"]), 0)
        self.assertEqual(res_open_sl["metrics"]["rejected_signals_by_reason"].get("NEXT_OPEN_GAP_BEYOND_STOP_LOSS"), 1)

        # Case C: Trade opens at 10:35:00 (2951.78), then 10:40:00 gaps down at open (2920.00 < stop_loss 2931.78)
        bars_subsequent_gap_sl = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2958.00,
                    "low": 2945.00,
                    "close": 2948.00,
                    "volume": 80000,
                },
                {
                    "timestamp": "2026-10-16 10:40:00",
                    "open": 2920.00,
                    "high": 2928.00,
                    "low": 2915.00,
                    "close": 2922.00,
                    "volume": 110000,
                },
            ],
        )
        res_sub_gap = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_subsequent_gap_sl,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=bt_cfg,
        )
        self.assertEqual(len(res_sub_gap["trades"]), 1)
        t_gap = res_sub_gap["trades"][0]
        self.assertEqual(t_gap["exit_reason"], "STOP_LOSS_GAP_OPEN")
        self.assertEqual(t_gap["raw_exit_price"], 2920.00)

    def test_p3b_06_session_boundaries_eod_cutoff_and_mandatory_square_off(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        engine = DeterministicBacktestEngine()

        # 1. If last_entry_Cutoff_ist is set to 10:30, a signal attempting to enter at 10:35 is rejected
        bars = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2960.00,
                    "low": 2945.00,
                    "close": 2955.00,
                    "volume": 80000,
                },
            ],
        )
        cfg_early_cutoff = BacktestConfig(
            starting_capital_inr=100000.0,
            last_entry_Cutoff_ist="10:30",
            cost_model=IndianCostModel(slippage_bps_per_leg=0.0),
        )
        res_cutoff = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=cfg_early_cutoff,
        )
        self.assertEqual(len(res_cutoff["trades"]), 0)
        self.assertEqual(
            res_cutoff["metrics"]["rejected_signals_by_reason"].get("SIGNAL_AT_OR_AFTER_EOD_ENTRY_CUTOFF"),
            1,
        )

        # 2. When trade neither hits stop_loss nor target_1 before dataset/session end, it is squared off
        cfg_normal = BacktestConfig(
            starting_capital_inr=100000.0,
            cost_model=IndianCostModel(slippage_bps_per_leg=0.0),
        )
        res_sq = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=cfg_normal,
        )
        self.assertEqual(len(res_sq["trades"]), 1)
        self.assertEqual(res_sq["trades"][0]["exit_reason"], "END_OF_DATASET_SQUARE_OFF")
        self.assertEqual(res_sq["trades"][0]["raw_exit_price"], 2955.00)

    def test_p3b_07_daily_loss_limit_daily_profit_target_and_position_sizing(self) -> None:
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        engine = DeterministicBacktestEngine()

        # 1. Insufficient capital rejection when starting_capital < 1 share price (2951.78 INR)
        bars = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2960.00,
                    "low": 2945.00,
                    "close": 2955.00,
                    "volume": 80000,
                },
            ],
        )
        cfg_tiny_cap = BacktestConfig(
            starting_capital_inr=1500.0,
            enforce_capital_exposure_limit=True,
        )
        tiny_intent = evaluate_order_block_fvg("RELIANCE", bars[:-1], now=self.fixed_now)
        self.assertIsNotNone(tiny_intent)
        with patch.object(engine, "_invoke_strategy_evaluator", side_effect=lambda **kw: (
            tiny_intent if kw["pit_candles"][-1]["timestamp"] == tiny_intent.timestamp else None
        )):
            res_tiny = engine.run_backtest(
                strategy_id="strat_1_order_block",
                symbol="RELIANCE",
                candles=bars,
                provider="paper_sim_fixture",
                data_mode="SIMULATED",
                backtest_config=cfg_tiny_cap,
            )
        self.assertEqual(len(res_tiny["trades"]), 0)
        self.assertEqual(res_tiny["metrics"]["rejected_signals_by_reason"].get("INSUFFICIENT_CAPITAL"), 1)

        # 2. Verify daily profit target trigger when a winning trade exceeds daily_profit_target_inr
        bars_win = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2995.00,
                    "low": 2945.00,
                    "close": 2990.00,
                    "volume": 90000,
                },
            ],
        )
        cfg_profit_cap = BacktestConfig(
            starting_capital_inr=100000.0,
            risk_per_trade_pct=1.0,
            daily_profit_target_inr=1000.0,  # Trade nets +1678.27 INR >= 1000.0 INR
            cost_model=IndianCostModel(brokerage_max_pct_per_leg=None, slippage_bps_per_leg=0.0),
        )
        res_pt = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_win,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=cfg_profit_cap,
        )
        self.assertTrue(
            res_pt["metrics"]["performance_by_day"]["2026-10-16"]["daily_profit_target_triggered"]
        )

        # 3. Verify daily loss limit trigger when a losing trade breaches -max_daily_loss_inr
        bars_loss = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2955.00,
                    "low": 2925.00,  # Hits stop_loss 2931.78 -> -1000 gross - charges < -1000 INR
                    "close": 2930.00,
                    "volume": 90000,
                },
            ],
        )
        cfg_loss_cap = BacktestConfig(
            starting_capital_inr=100000.0,
            risk_per_trade_pct=1.0,
            max_daily_loss_inr=500.0,  # 33 shares capped by 100k capital exposure loses -545.37 INR net <= -500.0 INR
            cost_model=IndianCostModel(brokerage_max_pct_per_leg=None, slippage_bps_per_leg=0.0),
        )
        res_ll = engine.run_backtest(
            strategy_id="strat_1_order_block",
            symbol="RELIANCE",
            candles=bars_loss,
            provider="paper_sim_fixture",
            data_mode="SIMULATED",
            backtest_config=cfg_loss_cap,
        )
        self.assertTrue(
            res_ll["metrics"]["performance_by_day"]["2026-10-16"]["daily_loss_limit_triggered"]
        )

    def test_p3b_08_indian_cost_model_exact_hand_calculated_schedule(self) -> None:
        from backtest_engine import IndianCostModel

        model = IndianCostModel(
            brokerage_per_order_inr=20.0,
            brokerage_max_pct_per_leg=0.0003,
            slippage_bps_per_leg=5.0,  # 0.05% per leg
        )
        # Equity intraday LONG: buy 100 shares @ 1000.0, sell 100 shares @ 1020.0
        # buy_turnover = 100,000, sell_turnover = 102,000, total_turnover = 202,000
        # entry_brok = min(20, 100000 * 0.0003 = 30) = 20.0
        # exit_brok = min(20, 102000 * 0.0003 = 30.6) = 20.0 -> brokerage = 40.0
        # stt (0.025% on sell_turnover 102,000) = 25.50
        # exch_txn (0.00297% on 202,000) = round(5.9994, 2) = 6.00
        # sebi (0.0001% on 202,000) = round(0.202, 2) = 0.20
        # stamp (0.003% on buy_turnover 100,000) = 3.00
        # gst = 18% of (40.0 + 6.00 + 0.20 = 46.20) = round(8.316, 2) = 8.32
        # charges_inr = 40.0 + 25.50 + 6.00 + 0.20 + 3.00 + 8.32 = 83.02
        # entry_slippage = 100,000 * 0.0005 = 50.00, exit_slippage = 102,000 * 0.0005 = 51.00 -> slippage = 101.00
        # total_costs_inr = 83.02 + 101.00 = 184.02
        res_eq = model.compute_trade_costs(
            raw_entry_price=1000.0,
            raw_exit_price=1020.0,
            quantity=100,
            position_side="LONG",
            segment="NSE_EQUITY_INTRADAY",
            instrument_type="EQ",
        )
        self.assertEqual(res_eq["brokerage_inr"], 40.00)
        self.assertEqual(res_eq["stt_inr"], 25.50)
        self.assertEqual(res_eq["exchange_txn_charge_inr"], 6.00)
        self.assertEqual(res_eq["sebi_charge_inr"], 0.20)
        self.assertEqual(res_eq["stamp_duty_inr"], 3.00)
        self.assertEqual(res_eq["gst_inr"], 8.32)
        self.assertEqual(res_eq["charges_inr"], 83.02)
        self.assertEqual(res_eq["slippage_inr"], 101.00)
        self.assertEqual(res_eq["total_costs_inr"], 184.02)
        self.assertEqual(res_eq["effective_entry_price"], 1000.50)
        self.assertEqual(res_eq["effective_exit_price"], 1019.49)

    def test_p3b_09_zero_trades_and_zero_losses_metrics_edge_cases(self) -> None:
        from backtest_engine import compute_backtest_metrics

        # 1. Zero trades edge case
        m_zero = compute_backtest_metrics(
            trades=[],
            starting_capital_inr=100000.0,
            session_dates_evaluated=["2026-10-16"],
            total_bars_evaluated=75,
        )
        self.assertEqual(m_zero["total_trades"], 0)
        self.assertEqual(m_zero["win_rate_pct"], 0.0)
        self.assertIsNone(m_zero["profit_factor"])
        self.assertEqual(m_zero["profit_factor_status"], "NO_TRADES")
        self.assertEqual(m_zero["profit_factor_display"], "N/A (NO_TRADES)")
        self.assertEqual(m_zero["max_drawdown_inr"], 0.0)
        self.assertFalse(m_zero["profitability_claim_justified"])

        # 2. Winning trades with zero losses edge case -> profit_factor MUST be None (not a fake finite float)
        m_win_only = compute_backtest_metrics(
            trades=[
                {
                    "trade_index": 1,
                    "strategy_id": "strat_1_order_block",
                    "position_side": "LONG",
                    "session_date": "2026-10-16",
                    "exit_timestamp": "2026-10-16 10:40:00",
                    "gross_pnl_inr": 1500.0,
                    "charges_inr": 80.0,
                    "slippage_inr": 20.0,
                    "total_costs_inr": 100.0,
                    "net_pnl_inr": 1400.0,
                    "realized_r_multiple": 1.4,
                    "holding_bars": 2,
                    "holding_minutes": 10.0,
                }
            ],
            starting_capital_inr=100000.0,
            session_dates_evaluated=["2026-10-16"],
            total_bars_evaluated=75,
        )
        self.assertEqual(m_win_only["total_trades"], 1)
        self.assertEqual(m_win_only["winning_trades"], 1)
        self.assertEqual(m_win_only["losing_trades"], 0)
        self.assertIsNone(m_win_only["profit_factor"])
        self.assertEqual(m_win_only["profit_factor_status"], "UNDEFINED_ZERO_LOSSES")
        self.assertEqual(m_win_only["profit_factor_display"], "INF_NO_LOSSES")

    def test_p3b_10_live_readiness_gate_live_vs_simulated_isolation_and_strategy_blocking(self) -> None:
        from backtest_engine import (
            BacktestConfig,
            BacktestEligibilityError,
            BacktestReadinessError,
            DeterministicBacktestEngine,
        )

        engine = DeterministicBacktestEngine()
        bars_sim = self._build_fixture_with_followup_bars(
            "RELIANCE",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 2951.78,
                    "high": 2995.00,
                    "low": 2945.00,
                    "close": 2990.00,
                    "volume": 90000,
                },
            ],
        )

        # 1. LIVE backtest blocked when Phase 2C live acceptance is not completed
        with self.assertRaises(BacktestReadinessError) as ctx_live:
            engine.run_backtest(
                strategy_id="strat_1_order_block",
                symbol="RELIANCE",
                candles=bars_sim,
                provider="angelone",
                data_mode="LIVE",
            )
        self.assertIn("BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED", str(ctx_live.exception))

        # 2. Strategy 3 (Option Apex OI Shift) remains strictly blocked without historical option chain
        nifty_bars = self._build_fixture_with_followup_bars(
            "NIFTY",
            "order_block_bull",
            [
                {
                    "timestamp": "2026-10-16 10:35:00",
                    "open": 24850.0,
                    "high": 24900.0,
                    "low": 24820.0,
                    "close": 24880.0,
                    "volume": 100000,
                },
            ],
        )
        with self.assertRaises(BacktestEligibilityError) as ctx_s3:
            engine.run_backtest(
                strategy_id="strat_3_option_apex_oi",
                symbol="NIFTY",
                candles=nifty_bars,
                provider="paper_sim_fixture",
                data_mode="SIMULATED",
            )
        self.assertIn("BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN", str(ctx_s3.exception))

        # 3. Non-executable Index Spot series (NIFTY spot) blocked for OHLCV strategies
        with self.assertRaises(BacktestEligibilityError) as ctx_spot:
            engine.run_backtest(
                strategy_id="strat_1_order_block",
                symbol="NIFTY",
                candles=nifty_bars,
                provider="paper_sim_fixture",
                data_mode="SIMULATED",
                backtest_config=BacktestConfig(instrument_type="INDEX_SPOT"),
            )
        self.assertIn("BLOCKED_NON_EXECUTABLE_INDEX_SPOT", str(ctx_spot.exception))

        # 4. Strategy 5 (Supertrend + 200 EMA) blocked when < 200 completed bars exist
        short_bars = bars_sim[-50:]
        with self.assertRaises(BacktestEligibilityError) as ctx_s5:
            engine.run_backtest(
                strategy_id="strat_5_supertrend_pullback",
                symbol="RELIANCE",
                candles=short_bars,
                provider="paper_sim_fixture",
                data_mode="SIMULATED",
            )
        self.assertIn("BLOCKED_INSUFFICIENT_200_BAR_WARMUP", str(ctx_s5.exception))

    def test_p3b_11_chronological_period_splits_reproducibility_and_all_eligible_strategies(self) -> None:
        from backtest_engine import (
            BacktestConfig,
            DeterministicBacktestEngine,
            IndianCostModel,
            split_sessions_chronologically,
        )

        # 1. Insufficient sessions (< 3) blocked for 3-way split
        split_blocked = split_sessions_chronologically(["2026-10-15", "2026-10-16"])
        self.assertEqual(split_blocked["status"], "BLOCKED_INSUFFICIENT_HISTORICAL_SESSIONS")
        self.assertIsNone(split_blocked["splits"])

        # 2. Valid 5-session chronological split
        split_ok = split_sessions_chronologically(
            ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
        )
        self.assertEqual(split_ok["status"], "READY")
        self.assertEqual(split_ok["splits"]["TRAIN"]["sessions"], ["2026-10-12", "2026-10-13", "2026-10-14"])
        self.assertEqual(split_ok["splits"]["VALIDATION"]["sessions"], ["2026-10-15"])
        self.assertEqual(split_ok["splits"]["OUT_OF_SAMPLE"]["sessions"], ["2026-10-16"])

        # 3. Verify Strategies 2, 4, and 5 execute deterministically on their respective synthetic fixtures
        engine = DeterministicBacktestEngine()
        bt_cfg = BacktestConfig(
            starting_capital_inr=100000.0,
            risk_per_trade_pct=1.0,
            period_type="OUT_OF_SAMPLE",
            evaluation_start_date="2026-10-16",
            evaluation_end_date="2026-10-16",
            cost_model=IndianCostModel(slippage_bps_per_leg=2.0),
        )
        for strat_id, sym, pat in (
            ("strat_2_vwap_pullback", "TCS", "vwap_pullback_bull"),
            ("strat_4_orb_filtered", "ICICIBANK", "orb_breakout_bull"),
            ("strat_5_supertrend_pullback", "SBIN", "supertrend_pullback_bull"),
        ):
            bars = self._build_fixture_with_followup_bars(
                sym,
                pat,
                [
                    {
                        "timestamp": "2026-10-16 10:35:00",
                        "open": 1000.0 if sym != "TCS" else 4135.0,
                        "high": 1050.0 if sym != "TCS" else 4210.0,
                        "low": 990.0 if sym != "TCS" else 4125.0,
                        "close": 1040.0 if sym != "TCS" else 4200.0,
                        "volume": 150000,
                    },
                ],
            )
            # Align 10:35:00 open with 10:30:00 close
            c_1030 = bars[-2]["close"]
            bars[-1]["open"] = c_1030
            bars[-1]["high"] = round(c_1030 * 1.03, 2)
            bars[-1]["low"] = round(c_1030 * 0.998, 2)
            bars[-1]["close"] = round(c_1030 * 1.025, 2)

            r1 = engine.run_backtest(
                strategy_id=strat_id,
                symbol=sym,
                candles=bars,
                provider="paper_sim_fixture",
                data_mode="SIMULATED",
                backtest_config=bt_cfg,
            )
            r2 = engine.run_backtest(
                strategy_id=strat_id,
                symbol=sym,
                candles=bars,
                provider="paper_sim_fixture",
                data_mode="SIMULATED",
                backtest_config=bt_cfg,
            )
            self.assertEqual(r1["run_id"], r2["run_id"])
            self.assertEqual(r1["metrics"]["total_trades"], 1)
            self.assertEqual(r1["trades"], r2["trades"])

    def test_p3b_12_sqlite_persistence_http_api_routes_resource_warnings_and_security(self) -> None:
        import gc
        import tempfile
        import urllib.error
        import urllib.request
        import warnings
        from config import BotConfig
        from server import configure_server_runtime, create_http_server
        from storage import SQLitePersistenceStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_phase3b.db")
            cfg = BotConfig(
                active_broker="paper_sim",
                database_url=f"sqlite:///{db_path}",
                enable_persistence=True,
                enable_background_scheduler=False,
            )
            configure_server_runtime(config=cfg, start_scheduler=False)
            httpd = create_http_server(host="127.0.0.1", port=0)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            try:
                def _req_json(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
                    data = json.dumps(body).encode("utf-8") if body is not None else None
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}{path}",
                        data=data,
                        method=method,
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=5) as r:
                            return r.status, json.loads(r.read().decode("utf-8"))
                    except urllib.error.HTTPError as e:
                        with e:
                            return e.code, json.loads(e.read().decode("utf-8"))

                # 1. GET /api/backtest-eligibility
                code_el, el_payload = _req_json("GET", "/api/backtest-eligibility?data_mode=LIVE")
                self.assertEqual(code_el, 200)
                self.assertEqual(el_payload["implementation_status"], "IMPLEMENTED_VERIFIED")
                self.assertEqual(
                    el_payload["strategies"]["strat_3_option_apex_oi"]["backtest_eligibility"],
                    "BLOCKED_MISSING_HISTORICAL_OPTION_CHAIN",
                )

                # 2. POST /api/backtest with SIMULATED fixture candles -> 200 OK & persisted
                bars = self._build_fixture_with_followup_bars(
                    "RELIANCE",
                    "order_block_bull",
                    [
                        {
                            "timestamp": "2026-10-16 10:35:00",
                            "open": 2951.78,
                            "high": 2995.00,
                            "low": 2945.00,
                            "close": 2990.00,
                            "volume": 90000,
                        },
                    ],
                )
                code_bt, bt_payload = _req_json(
                    "POST",
                    "/api/backtest",
                    {
                        "strategy_id": "strat_1_order_block",
                        "symbol": "RELIANCE",
                        "data_mode": "SIMULATED",
                        "provider": "paper_sim_fixture",
                        "candles": bars,
                        "starting_capital_inr": 100000.0,
                        "risk_per_trade_pct": 1.0,
                        "persist_run": True,
                    },
                )
                self.assertEqual(code_bt, 200)
                run_id = bt_payload["run_id"]
                self.assertEqual(bt_payload["metrics"]["total_trades"], 1)

                # 3. GET /api/backtest-runs and GET /api/backtest-runs/<run_id>
                code_list, list_payload = _req_json("GET", "/api/backtest-runs?symbol=RELIANCE&data_mode=SIMULATED")
                self.assertEqual(code_list, 200)
                self.assertEqual(list_payload["total_count"], 1)

                code_det, det_payload = _req_json("GET", f"/api/backtest-runs/{run_id}")
                self.assertEqual(code_det, 200)
                self.assertEqual(det_payload["backtest_run"]["run_id"], run_id)
                self.assertEqual(len(det_payload["backtest_run"]["trades"]), 1)

                # 4. POST /api/backtest blocked for Strategy 3 (422) and unverified LIVE mode (422)
                code_s3, s3_err = _req_json(
                    "POST",
                    "/api/backtest",
                    {
                        "strategy_id": "strat_3_option_apex_oi",
                        "symbol": "NIFTY",
                        "data_mode": "SIMULATED",
                        "candles": bars,
                    },
                )
                self.assertEqual(code_s3, 422)
                self.assertEqual(s3_err["error_type"], "BacktestEligibilityError")

                code_live_blk, live_err = _req_json(
                    "POST",
                    "/api/backtest",
                    {
                        "strategy_id": "strat_1_order_block",
                        "symbol": "RELIANCE",
                        "data_mode": "LIVE",
                        "candles": bars,
                    },
                )
                self.assertEqual(code_live_blk, 422)
                self.assertEqual(live_err["error_type"], "BacktestReadinessError")

                # 5. Private source files including /backtest_engine.py remain blocked (404)
                for priv in ("/backtest_engine.py", "/historical_data.py", "/storage.py", "/.env"):
                    code_priv, _ = _req_json("GET", priv)
                    self.assertEqual(code_priv, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()
                t.join(timeout=3)

        # 6. Verify deterministic SQLite connection lifecycle & zero ResourceWarnings on GC
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", ResourceWarning)
            for _ in range(10):
                with SQLitePersistenceStore(":memory:") as mem_store:
                    h = mem_store.check_health()
                    self.assertEqual(h["status"], "OK")
            unclosed_store = SQLitePersistenceStore(":memory:")
            unclosed_store.check_health()
            del unclosed_store
            gc.collect()
            res_warnings = [w for w in caught_warnings if issubclass(w.category, ResourceWarning)]
            self.assertEqual(len(res_warnings), 0, f"Unexpected ResourceWarnings: {res_warnings}")


class TestIndianFOSignalBotPhase3B1A(unittest.TestCase):
    """Historical containment and next-open execution; all inputs are offline fixtures."""

    def setUp(self):
        from storage import SQLitePersistenceStore

        self.fixed_now = datetime(2026, 10, 16, 15, 30, tzinfo=IST)
        self.sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.fixed_now)
        self.cfg = BotConfig(
            active_broker="paper_sim", database_url=":memory:",
            telegram_dry_run=True, enable_background_scheduler=False,
        )
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        network_guard = patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden in Phase 3B.1A tests"))
        network_guard.start()
        self.addCleanup(network_guard.stop)

    def _option_inputs(self):
        rows = self.sim.get_intraday_candles({"symbol": "NIFTY"}, pattern="vwap_pullback_bull")
        stamp = rows[-1]["timestamp"]
        return rows, {stamp: self.sim.get_option_chain("NIFTY", bias="BULLISH")}, {
            "SIMULATED_NIFTY_CE": [{
                "timestamp": stamp, "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1000, "is_complete": True,
                "is_simulated": True, "data_mode": "SIMULATED",
            }],
        }

    def _assert_strategy3_rejection(self, rejection):
        self.assertFalse(rejection["eligible"])
        self.assertEqual(rejection["strategy_id"], "strat_3_option_apex_oi")
        self.assertEqual(rejection["reason_code"], "HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED")
        self.assertIn("not supported until validated contract-level", rejection["reason"])
        self.assertIn("contract-candle fills", rejection["required_action"])

    def test_p3b1a_strategy3_eligibility_blocks_all_option_inputs(self):
        from backtest_engine import evaluate_strategy_backtest_eligibility

        rows, chains, contracts = self._option_inputs()
        cases = [
            {},
            {"historical_option_chains_by_timestamp": {}, "historical_option_candles_by_contract": {}},
            {"historical_option_chains_by_timestamp": {"fabricated": {}},
             "historical_option_candles_by_contract": {"fabricated": [{}]}, "historical_lot_size": 25},
            {"historical_option_chains_by_timestamp": chains,
             "historical_option_candles_by_contract": contracts, "historical_lot_size": 75},
        ]
        for inputs in cases:
            with self.subTest(inputs=list(inputs)):
                rejection = evaluate_strategy_backtest_eligibility(
                    "strat_3_option_apex_oi", "NIFTY", "NSE_FO_INDEX", rows,
                    instrument_type="OPTIDX", **inputs,
                )
                self._assert_strategy3_rejection(rejection)
        # Unsupported execution takes precedence even over invalid instrument/timeframe inputs.
        self._assert_strategy3_rejection(evaluate_strategy_backtest_eligibility(
            "strat_3_option_apex_oi", "RELIANCE", "NSE_EQUITY_INTRADAY", [], interval_min=1,
        ))

    def test_p3b1a_strategy3_direct_engine_cannot_bypass_containment(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine

        rows, chains, contracts = self._option_inputs()
        cases = [({}, None), ({"historical_option_chains_by_timestamp": {},
                                 "historical_option_candles_by_contract": {}}, []),
                 ({"historical_option_chains_by_timestamp": {"fabricated": {}},
                   "historical_option_candles_by_contract": {"fabricated": [{}]}}, rows),
                 ({"historical_option_chains_by_timestamp": chains,
                   "historical_option_candles_by_contract": contracts}, rows)]
        for mode in ("SIMULATED", "LIVE"):
            for acceptance_required in (True, False):
                for inputs, candles in cases:
                    with self.subTest(mode=mode, acceptance_required=acceptance_required, inputs=list(inputs)):
                        bt_cfg = BacktestConfig(
                            require_live_acceptance_for_live_mode=acceptance_required,
                            historical_lot_size=75, instrument_type="OPTIDX",
                        )
                        bt_cfg.allow_historical_strategy3 = True
                        engine = DeterministicBacktestEngine(
                            bot_config=self.cfg, store=self.store,
                            broker_status={"connection_state": "CONNECTED_VERIFIED", "connectivity_verified": True},
                        )
                        with patch("backtest_engine.evaluate_phase3a_backtest_readiness") as readiness, \
                             patch.object(engine, "_invoke_strategy_evaluator") as evaluator:
                            with self.assertRaises(BacktestEligibilityError) as caught:
                                engine.run_backtest(
                                    "strat_3_option_apex_oi", "NIFTY", candles=candles,
                                    provider="paper_sim_fixture" if mode == "SIMULATED" else "angelone",
                                    data_mode=mode, backtest_config=bt_cfg, persist_run=True, **inputs,
                                )
                            self._assert_strategy3_rejection(caught.exception.details)
                            readiness.assert_not_called()
                            evaluator.assert_not_called()
        self.assertEqual(self.store.check_health()["backtest_runs_count"], 0)
        self.assertEqual(self.store.check_health()["backtest_trades_count"], 0)

    def test_p3b1a_strategy3_cli_rejection_and_static_listing(self):
        import io
        from backtest_engine import main

        for mode in ("SIMULATED", "LIVE"):
            for json_output in (False, True):
                with self.subTest(mode=mode, json_output=json_output):
                    argv = ["--strategy", "strat_3_option_apex_oi", "--symbol", "NIFTY", "--data-mode", mode]
                    if json_output:
                        argv.append("--json")
                    with patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), \
                         patch("sys.stdout", new_callable=io.StringIO) as output:
                        code = main(argv)
                    self.assertEqual(code, 2)
                    if json_output:
                        payload = json.loads(output.getvalue())
                        self.assertEqual(payload["error_type"], "BacktestEligibilityError")
                        self._assert_strategy3_rejection(payload["rejection"])
                    else:
                        self.assertIn("Historical Strategy 3", output.getvalue())
                        self.assertIn("not supported until", output.getvalue())
        with patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(["--eligibility", "--json"]), 0)
        listing = json.loads(output.getvalue())["strategy_eligibility_matrix"]["strat_3_option_apex_oi"]
        self.assertFalse(listing["historical_execution_supported"])
        self.assertEqual(listing["reason_code"], "HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED")

    def test_p3b1a_strategy3_http_aliases_reject_override_fields(self):
        import io
        from types import SimpleNamespace
        from server import DashboardRequestHandler

        rows, chains, contracts = self._option_inputs()
        for path in ("/api/backtest", "/api/v1/backtest"):
            for mode in ("SIMULATED", "LIVE"):
                with self.subTest(path=path, mode=mode):
                    body = json.dumps({
                        "strategy_id": "strat_3_option_apex_oi", "symbol": "NIFTY", "data_mode": mode,
                        "candles": rows, "historical_lot_size": 75, "instrument_type": "OPTIDX",
                        "historical_option_chains_by_timestamp": chains,
                        "historical_option_candles_by_contract": contracts,
                        "require_live_acceptance_for_live_mode": False, "allow_historical_strategy3": True,
                        "phase3_ready_for_execution": True, "connectivity_verified": True,
                    }).encode("utf-8")
                    handler = object.__new__(DashboardRequestHandler)
                    handler.path = path
                    handler.headers = {"Content-Length": str(len(body))}
                    handler.rfile = io.BytesIO(body)
                    handler.engine = SimpleNamespace(
                        config=self.cfg, store=self.store,
                        get_broker_status=lambda: {"connection_state": "CONNECTED_VERIFIED", "connectivity_verified": True},
                    )
                    handler._ensure_initialized = MagicMock()
                    handler._send_json = MagicMock()
                    handler.do_POST()
                    code, payload = handler._send_json.call_args.args
                    self.assertEqual(code, 422)
                    self.assertEqual(payload["error_type"], "BacktestEligibilityError")
                    self._assert_strategy3_rejection(payload["rejection"])
        self.assertEqual(self.store.check_health()["backtest_runs_count"], 0)
        self.assertEqual(self.store.check_health()["backtest_trades_count"], 0)

    def test_p3b1a_live_option_signal_evaluation_is_preserved(self):
        for symbol, lot_size in (("NIFTY", 75), ("BANKNIFTY", 30)):
            for side, suffix in (("BULLISH", "bull"), ("BEARISH", "bear")):
                with self.subTest(symbol=symbol, side=side):
                    rows = self.sim.get_intraday_candles({"symbol": symbol}, pattern="vwap_pullback_" + suffix)
                    chain = self.sim.get_option_chain(symbol, bias=side)
                    sig = evaluate_option_apex_oi_shift(symbol, rows, chain, lot_size=lot_size, now=self.fixed_now, capital_inr=500000)
                    self.assertIsNotNone(sig)
                    self.assertEqual(sig.position_type, "LONG_CALL_OPTION" if side == "BULLISH" else "LONG_PUT_OPTION")

    def test_p3b1a_supported_strategies_still_execute_valid_fixtures(self):
        from datetime import timedelta
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel

        for strategy_id, pattern in (
            ("strat_1_order_block", "order_block"), ("strat_2_vwap_pullback", "vwap_pullback"),
            ("strat_4_orb_filtered", "orb_breakout"), ("strat_5_supertrend_pullback", "supertrend_pullback"),
        ):
            for side in ("bull", "bear"):
                with self.subTest(strategy=strategy_id, side=side):
                    rows = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern=pattern + "_" + side)
                    last = rows[-1]
                    price = last["close"]
                    rows.append(dict(
                        timestamp=(parse_ist_timestamp(last["timestamp"]) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
                        open=price, high=price * 1.0001, low=price * 0.9999, close=price,
                        volume=100000, is_complete=True, is_simulated=True, data_mode="SIMULATED",
                    ))
                    result = DeterministicBacktestEngine(bot_config=self.cfg).run_backtest(
                        strategy_id, "RELIANCE", candles=rows, provider="paper_sim_fixture", data_mode="SIMULATED",
                        backtest_config=BacktestConfig(cost_model=IndianCostModel(slippage_bps_per_leg=0)),
                    )
                    self.assertGreater(len(result["trades"]), 0)

    def _run_entry(self, side, opening, slippage=0, target_mode="TARGET_1", entry_range=None, followup=None, target_override=None):
        from datetime import timedelta
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel
        from storage import SQLitePersistenceStore

        start = datetime(2026, 10, 16, 9, 15, tzinfo=IST)
        rows = [dict(
            timestamp=(start + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S"),
            open=100.0, high=101.0, low=99.0, close=100.0, volume=1000,
            is_complete=True, is_simulated=True, data_mode="SIMULATED",
        ) for i in range(32)]
        low, high = entry_range or (opening - 0.005, opening + 0.005)
        rows[-1].update(open=opening, high=high, low=low, close=opening)
        if followup is not None:
            rows.append(dict(
                timestamp=(start + timedelta(minutes=160)).strftime("%Y-%m-%d %H:%M:%S"),
                open=followup, high=followup + 0.005, low=followup - 0.005, close=followup,
                volume=1000, is_complete=True, is_simulated=True, data_mode="SIMULATED",
            ))
        sig = TradeSignal(
            symbol="RELIANCE", segment="NSE_EQUITY_INTRADAY", strategy_id="strat_1_order_block",
            strategy_name="Execution-only test fixture", direction="BULLISH (BUY)" if side == "LONG" else "BEARISH (SELL)",
            instrument_label="RELIANCE EQ", entry_price=100, entry_zone_low=99, entry_zone_high=101,
            stop_loss=90 if side == "LONG" else 110, target_1=110 if side == "LONG" else 90,
            target_2=120 if side == "LONG" else 80, risk_reward="test fixture", confidence_pct=0,
            win_rate_benchmark="", position_qty=1, capital_risk_inr=10, est_charges_inr=0,
            rationale="SIMULATED execution regression only", timestamp=rows[30]["timestamp"],
            is_simulated=True, data_mode="SIMULATED",
        )
        if target_override is not None:
            setattr(sig, "target_1" if target_mode == "TARGET_1" else "target_2", target_override)
        store = SQLitePersistenceStore(":memory:")
        self.addCleanup(store.close)
        engine = DeterministicBacktestEngine(bot_config=self.cfg, store=store)
        with patch.object(engine, "_invoke_strategy_evaluator", side_effect=lambda **kw: (
            sig if kw["pit_candles"][-1]["timestamp"] == sig.timestamp else None
        )):
            result = engine.run_backtest(
                "strat_1_order_block", "RELIANCE", candles=rows, provider="paper_sim_fixture", data_mode="SIMULATED",
                backtest_config=BacktestConfig(
                    starting_capital_inr=10000, target_mode=target_mode,
                    cost_model=IndianCostModel(slippage_bps_per_leg=slippage),
                ), persist_run=True,
            )
        return result, store, rows

    def _assert_rejected_entry(self, side, opening, reason, **kwargs):
        result, store, _ = self._run_entry(side, opening, **kwargs)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertEqual(result["metrics"]["gross_pnl_inr"], 0)
        self.assertEqual(result["metrics"]["net_pnl_inr"], 0)
        self.assertEqual(result["metrics"]["total_costs_inr"], 0)
        self.assertEqual(result["metrics"]["rejected_signals_by_reason"], {reason: 1})
        self.assertEqual(store.check_health()["backtest_trades_count"], 0)
        self.assertEqual(store.get_backtest_run_detail(result["run_id"])["trades"], [])
        return result["rejected_signals"][0]

    def test_p3b1a_long_short_target_gaps_and_equality(self):
        for side, prices in (("LONG", (111, 110)), ("SHORT", (89, 90))):
            for price in prices:
                with self.subTest(side=side, opening=price):
                    self._assert_rejected_entry(side, price, "NEXT_OPEN_GAP_BEYOND_TARGET")

    def test_p3b1a_long_short_stop_gaps_and_equality(self):
        for side, prices in (("LONG", (89, 90)), ("SHORT", (111, 110))):
            for price in prices:
                with self.subTest(side=side, opening=price):
                    self._assert_rejected_entry(side, price, "NEXT_OPEN_GAP_BEYOND_STOP_LOSS")
        # Adverse slippage cannot rescue an already invalid raw open through the stop.
        for side, opening in (("LONG", 89.9), ("SHORT", 110.1)):
            with self.subTest(side=side, slippage=100):
                self._assert_rejected_entry(side, opening, "NEXT_OPEN_GAP_BEYOND_STOP_LOSS", slippage=100)

    def test_p3b1a_effective_entry_crossings_and_rounded_boundaries(self):
        for side, opening, slippage in (("LONG", 109, 100), ("SHORT", 91, 200),
                                        ("LONG", 100, 1000), ("SHORT", 100, 1000)):
            with self.subTest(side=side, opening=opening, slippage=slippage):
                rejection = self._assert_rejected_entry(side, opening, "NEXT_OPEN_GAP_BEYOND_TARGET", slippage=slippage)
                self.assertNotEqual(rejection["effective_entry_price"], opening)
        for side, opening, reason in (
            ("LONG", 109.99999, "NEXT_OPEN_GAP_BEYOND_TARGET"),
            ("SHORT", 90.00001, "NEXT_OPEN_GAP_BEYOND_TARGET"),
            ("LONG", 90.00001, "NEXT_OPEN_GAP_BEYOND_STOP_LOSS"),
            ("SHORT", 109.99999, "NEXT_OPEN_GAP_BEYOND_STOP_LOSS"),
        ):
            with self.subTest(side=side, rounded_opening=opening):
                self._assert_rejected_entry(side, opening, reason)

    def test_p3b1a_selected_target_two_controls_entry_boundary(self):
        for side, valid, boundary, beyond in (("LONG", 115, 120, 121), ("SHORT", 85, 80, 79)):
            with self.subTest(side=side, valid=valid):
                result, _, _ = self._run_entry(side, valid, target_mode="TARGET_2")
                self.assertEqual(len(result["trades"]), 1)
                self.assertEqual(result["trades"][0]["target_price"], boundary)
            for opening in (boundary, beyond):
                with self.subTest(side=side, opening=opening):
                    self._assert_rejected_entry(side, opening, "NEXT_OPEN_GAP_BEYOND_TARGET", target_mode="TARGET_2")

    def test_p3b1a_entry_preview_matches_cost_model_half_rounding(self):
        from backtest_engine import IndianCostModel

        # Multiplying by (1 +/- rate) rounds differently for these binary-float ties.
        for side, opening, slippage in (("LONG", 90.01, 50), ("SHORT", 90.1, 5)):
            with self.subTest(side=side):
                costs = IndianCostModel(slippage_bps_per_leg=slippage).compute_trade_costs(
                    opening, opening, 1, side,
                )
                target = costs["effective_entry_price"]
                rejection = self._assert_rejected_entry(
                    side, opening, "NEXT_OPEN_GAP_BEYOND_TARGET", slippage=slippage, target_override=target,
                )
                self.assertEqual(rejection["effective_entry_price"], target)

    def test_p3b1a_valid_entries_preserve_fills_costs_and_ledger(self):
        for side in ("LONG", "SHORT"):
            for slippage in (0, 5):
                with self.subTest(side=side, slippage=slippage):
                    result, store, rows = self._run_entry(side, 100, slippage=slippage)
                    self.assertEqual(len(result["trades"]), 1)
                    trade = result["trades"][0]
                    self.assertEqual(trade["raw_entry_price"], 100)
                    self.assertEqual(trade["entry_price"], 100 + (slippage / 100 if side == "LONG" else -slippage / 100))
                    self.assertLessEqual(rows[31]["low"], trade["raw_exit_price"])
                    self.assertGreaterEqual(rows[31]["high"], trade["raw_exit_price"])
                    self.assertEqual(trade["net_pnl_inr"], round(trade["gross_pnl_inr"] - trade["total_costs_inr"], 2))
                    self.assertEqual(store.check_health()["backtest_trades_count"], 1)
                    self.assertEqual(store.get_backtest_run_detail(result["run_id"])["trades"][0]["net_pnl_inr"], trade["net_pnl_inr"])

    def test_p3b1a_same_candle_collision_remains_stop_first(self):
        for side, stop in (("LONG", 90), ("SHORT", 110)):
            with self.subTest(side=side):
                result, _, _ = self._run_entry(side, 100, entry_range=(85, 115))
                trade = result["trades"][0]
                self.assertEqual(trade["exit_reason"], "STOP_LOSS_SAME_CANDLE_CONSERVATIVE")
                self.assertTrue(trade["same_candle_collision"])
                self.assertEqual(trade["raw_exit_price"], stop)

    def test_p3b1a_open_positions_keep_gap_open_stop_and_target_exits(self):
        for side, stop_gap, target_gap in (("LONG", 85, 115), ("SHORT", 115, 85)):
            for gap, reason in ((stop_gap, "STOP_LOSS_GAP_OPEN"), (target_gap, "TARGET_GAP_OPEN")):
                with self.subTest(side=side, gap=gap):
                    result, _, rows = self._run_entry(side, 100, followup=gap)
                    trade = result["trades"][0]
                    self.assertEqual(trade["entry_timestamp"], rows[31]["timestamp"])
                    self.assertEqual(trade["exit_timestamp"], rows[32]["timestamp"])
                    self.assertEqual(trade["raw_exit_price"], gap)
                    self.assertEqual(trade["exit_reason"], reason)



def offline_equity_master_fixture(provider="angelone", symbol="RELIANCE", token="2885"):
    """Synthetic dated-master evidence for isolated replay tests, never broker acceptance."""
    from instrument_identity import digest
    records = [dict(provider=provider, symbol=symbol, identifier=token, exchange="NSE",
                    instrument_type="EQ", multiplier=1, valid_from="2026-10-01", valid_to="2026-10-31")]
    return dict(source="ARCHIVED_PROVIDER_MASTER", source_reference="OFFLINE_SYNTHETIC_MASTER_FIXTURE",
                records=records, sha256=digest(records))


def offline_ingested_master_fixture():
    """Explicit V1 local source declarations; never authenticated provider evidence."""
    from instrument_archive import SCHEMA
    return dict(offline_equity_master_fixture(), schema_version=SCHEMA, provider="angelone")


class TestIndianFOSignalBotPhase3B1B(unittest.TestCase):
    """Offline acceptance process, durable evidence and scoped execution regressions."""

    def setUp(self):
        from backtest_engine import DeterministicBacktestEngine
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.cfg = BotConfig(
            active_broker="angelone", database_url=":memory:", telegram_dry_run=True,
            angel_api_key="FIXTURE_API_KEY_ONLY", angel_client_code="FIXTURE_CLIENT",
            angel_pin="7531", angel_totp_secret="JBSWY3DPEHPK3PXP",
            angel_min_request_interval_seconds=0.0)
        self.cfg.equity_watchlist = self.cfg.equity_watchlist[:2]
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.engine = DeterministicBacktestEngine(self.cfg, self.store, clock=lambda: self.now)
        self.bars = sum((TestIndianFOSignalBotPhase3A._build_session_bars(day)
                         for day in ("2026-10-13", "2026-10-14", "2026-10-15")), [])
        self.network = patch("urllib.request.urlopen", side_effect=AssertionError("External network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def _history(self, bars=None, symbol="RELIANCE", provider="angelone"):
        return self.store.save_historical_candle_dataset(
            self.bars if bars is None else bars, symbol=symbol, segment="NSE_EQUITY_INTRADAY",
            exchange="NSE", provider=provider, instrument_token="2885" if symbol == "RELIANCE" else "1333",
            data_mode="LIVE", reference_time_ist=self.now)

    def _produce(self, store=None, bad_quotes=False, mutate=None, evidence_mode="LIVE_REQUEST"):
        from diagnostics import run_angelone_diagnostics
        store = store or self.store
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now, persistence_store=store)
        adapter.load_scrip_master(TestIndianFOSignalBotPhase2C._build_scrip_master_fixture())
        for symbol, pairs in (
            ("NIFTY", {24750: {"ce_oi": 1600000, "pe_oi": 2100000},
                       24800: {"ce_oi": 2270000, "pe_oi": 2720000},
                       24850: {"ce_oi": 2000000, "pe_oi": 1800000}}),
            ("BANKNIFTY", {52400: {"ce_oi": 900000, "pe_oi": 1200000},
                           52500: {"ce_oi": 950000, "pe_oi": 1100000}})):
            store.save_paired_strike_baselines(
                index_symbol=symbol, expiry="2026-10-22", baseline_by_strike=pairs,
                session_date="2026-10-15", observation_timestamp="2026-10-15 15:29:00",
                source="official_nse_bhavcopy_import", data_mode="LIVE",
                baseline_kind="CLOSING_BASELINE", now_ist=self.now)
        bars = SimulatedNSEAdapter(clock=lambda: self.now).get_intraday_candles({"symbol": "RELIANCE"})
        responses = [
            {"status": True, "data": {"jwtToken": "FIXTURE_JWT_ONLY", "refreshToken": "FIXTURE_REFRESH_ONLY", "feedToken": "FIXTURE_FEED_ONLY"}},
            {"status": True, "data": {"clientcode": "FIXTURE_CLIENT", "exchanges": ["nse_cm", "nse_fo"], "products": ["INTRADAY"]}},
            {"status": True, "data": {"fetched": [
                {"exchange": "NSE", "tradingSymbol": s, "symbolToken": t, "ltp": p,
                 "open": p, "high": p + 20, "low": p - 20, "close": p,
                 "exchFeedTime": "16-Oct-2026 10:34:55"}
                for s, t, p in (("NIFTY", "99926000", 24820.5), ("BANKNIFTY", "99926009", 52460.0))], "unfetched": []}},
            {"status": True, "data": [[b["timestamp"].replace(" ", "T") + "+05:30", b["open"], b["high"], b["low"], b["close"], b["volume"]] for b in bars]},
        ]
        if bad_quotes:
            responses[2]["data"]["fetched"] = []
        if mutate:
            mutate(responses)
        with patch("urllib.request.urlopen", side_effect=TestIndianFOSignalBotPhase2C._mock_http_sequence(responses)) as transport:
            report = run_angelone_diagnostics(self.cfg, adapter=adapter, store=store, clock=lambda: self.now,
                                             evidence_mode=evidence_mode)
        self.assertEqual(transport.call_count, 4)
        if not bad_quotes and not mutate:
            self.assertEqual(report["overall_status"], "PASS")
            # LIVE_REQUEST here simulates the trusted live producer contract in
            # an isolated fixture store; it is never genuine broker evidence.
            self.assertEqual(report["live_acceptance"]["accepted"], evidence_mode == "LIVE_REQUEST", report["live_acceptance"])
        return report

    def _run(self, scope=None, **kwargs):
        from backtest_engine import BacktestConfig
        return self.engine.run_backtest("strat_1_order_block", "RELIANCE", provider="angelone",
                                        data_mode="LIVE", backtest_config=BacktestConfig(execution_scope=scope,
                                            historical_instrument_identity=offline_ingested_master_fixture()), **kwargs)

    def _report(self, **kwargs):
        from historical_data import evaluate_phase3a_backtest_readiness
        return evaluate_phase3a_backtest_readiness(self.cfg, self.store, provider="angelone", now=self.now, **kwargs)

    def test_missing_receipt_blocks_live(self):
        from backtest_engine import BacktestReadinessError
        self._history()
        with self.assertRaises(BacktestReadinessError) as caught:
            self._run()
        self.assertEqual(caught.exception.details["reason_code"], "BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED")
        self.assertEqual(caught.exception.details["live_acceptance"]["reason_code"], "ACCEPTANCE_EVIDENCE_MISSING")

    def test_legacy_config_bypass_is_neutralized(self):
        from backtest_engine import BacktestConfig, BacktestReadinessError
        self._history()
        with self.assertRaises(BacktestReadinessError):
            self.engine.run_backtest("strat_1_order_block", "RELIANCE", data_mode="LIVE", provider="angelone",
                                     backtest_config=BacktestConfig(require_live_acceptance_for_live_mode=False))

    def test_connection_booleans_cannot_establish_acceptance(self):
        self._history()
        self.engine.broker_status = {"connection_state": "CONNECTED_VERIFIED", "connectivity_verified": True,
                                     "phase2c_live_accepted": True, "phase3_ready_for_execution": True}
        report = self._report(broker_status=self.engine.broker_status)
        self.assertFalse(report["phase2c_live_accepted"])
        self.assertFalse(report["phase3_ready_for_execution"])

    def test_historical_research_does_not_imply_aggregate_or_live_acceptance(self):
        from backtest_engine import BacktestEligibilityError
        self._history()
        with self.assertRaises(BacktestEligibilityError) as caught:
            self._run("HISTORICAL_RESEARCH")
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        report = self._report(symbol="RELIANCE", execution_scope="HISTORICAL_RESEARCH")
        self.assertEqual(report["execution_gate"]["reason_code"], "HISTORICAL_RESEARCH_ONLY_NOT_LIVE_ACCEPTED")
        self.assertTrue(report["execution_gate"]["allowed"])
        self.assertFalse(report["aggregate_coverage_ready"])
        self.assertFalse(report["phase2c_live_accepted"])
        self.assertFalse(report["phase3_ready_for_execution"])

    def test_synthetic_can_never_receive_live_label(self):
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine
        self.cfg.equity_watchlist = self.cfg.equity_watchlist[:1]
        self._produce()
        self.store.save_historical_candle_dataset(
            [dict(b, data_mode="SIMULATED", is_simulated=True) for b in self.bars],
            symbol="RELIANCE", provider="paper_sim", instrument_token="2885", data_mode="SIMULATED",
            reference_time_ist=self.now)
        bars = SimulatedNSEAdapter(clock=lambda: self.now).get_intraday_candles({"symbol": "RELIANCE"})
        result = self.engine.run_backtest("strat_1_order_block", "RELIANCE", candles=bars)
        self.assertEqual(result["data_acceptance_status"], "SIMULATED_TEST_FIXTURE_NOT_LIVE_ACCEPTED")
        report = self._report(target_data_mode="SIMULATED")
        self.assertFalse(report["phase3_ready_for_execution"])
        self.assertFalse(report["phase2c_live_accepted"])

    def test_receipt_producer_and_expiry_boundary(self):
        from datetime import timedelta
        from readiness_policy import live_acceptance
        self._produce()
        for delta, expected in ((timedelta(0), True), (timedelta(minutes=29, seconds=59), True),
                                (timedelta(minutes=30), False), (timedelta(days=1), False)):
            with self.subTest(delta=delta):
                r = live_acceptance(self.cfg, self.store, "angelone", "RELIANCE", self.now + delta)
                self.assertEqual(r["accepted"], expected)

    def test_live_gate_accepts_only_produced_evidence_and_stored_complete_history(self):
        from backtest_engine import BacktestEligibilityError
        self._produce()
        self._history()
        report = self._report(symbol="RELIANCE")
        self.assertEqual(report["execution_gate"]["reason_code"], "LIVE_DIAGNOSTIC_ACCEPTED_RESEARCH")
        self.assertTrue(report["execution_gate"]["live_acceptance"]["accepted"])
        with self.assertRaises(BacktestEligibilityError) as caught:
            self._run()
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        self.assertFalse(self._report()["phase3_ready_for_execution"])

    def test_forged_request_bars_cannot_receive_live_acceptance(self):
        from backtest_engine import BacktestReadinessError
        self._produce()
        with self.assertRaises(BacktestReadinessError) as caught:
            self._run(candles=self.bars)
        self.assertEqual(caught.exception.details["reason_code"], "LIVE_ACCEPTED_REQUIRES_STORED_HISTORY")

    def test_malformed_and_boolean_only_evidence_fails_closed(self):
        from readiness_policy import live_acceptance
        for malformed in ({"accepted": True}, [], {"evidence": {}, "sha256": "fake"}, None):
            with self.subTest(malformed=malformed):
                self.store._save_live_acceptance_evidence("angelone", "RELIANCE", malformed)
                self.assertFalse(live_acceptance(self.cfg, self.store, "angelone", "RELIANCE", self.now)["accepted"])

    def test_inconsistent_observations_even_with_recomputed_digest_fail(self):
        import copy
        from readiness_policy import _digest, live_acceptance
        self._produce()
        original = self.store.load_live_acceptance_evidence("angelone", "RELIANCE")
        for mutation in ("future", "long_expiry", "checks", "synthetic", "stale_quote", "candle_count", "profile", "scope"):
            envelope = copy.deepcopy(original)
            e = envelope["evidence"]
            if mutation == "future": e["observed_at_ist"] = "2026-10-17 10:35:00"
            if mutation == "long_expiry": e["expires_at_ist"] = "2026-10-20 11:05:00"
            if mutation == "checks": e["checks"]["5"] = "NOT CHECKED"
            if mutation == "synthetic": e["candles"][0]["is_simulated"] = True
            if mutation == "stale_quote": e["quotes"]["NIFTY"]["feed_timestamp_ist"] = "2026-10-15 15:29:00"
            if mutation == "candle_count": e["candles"] = e["candles"][-10:]
            if mutation == "profile": e["profile_exchanges"] = []
            if mutation == "scope": e["observed_instrument"]["instrument_token"] = "1333"
            envelope["sha256"] = _digest(e)
            self.store._save_live_acceptance_evidence("angelone", "RELIANCE", envelope)
            with self.subTest(mutation=mutation):
                self.assertFalse(live_acceptance(self.cfg, self.store, "angelone", "RELIANCE", self.now)["accepted"])

    def test_provider_symbol_and_calendar_binding(self):
        from readiness_policy import live_acceptance
        self._produce()
        receipt = self.store.load_live_acceptance_evidence("angelone", "RELIANCE")
        for provider, symbol in (("dhan", "RELIANCE"), ("angelone", "HDFCBANK")):
            self.store._save_live_acceptance_evidence(provider, symbol, receipt)
            self.assertFalse(live_acceptance(self.cfg, self.store, provider, symbol, self.now)["accepted"])
        self.cfg.configured_holidays = ["2026-10-20"]
        self.assertFalse(live_acceptance(self.cfg, self.store, "angelone", "RELIANCE", self.now)["accepted"])

    def test_partial_boundary_missing_bar_and_missing_session_fail_coverage(self):
        from readiness_policy import historical_coverage
        for bars in (self.bars[:-1], self.bars[1:], self.bars[:100] + self.bars[101:], self.bars[:75] + self.bars[150:]):
            with self.subTest(count=len(bars)):
                c = historical_coverage(self.cfg, None, "angelone", "RELIANCE", candles=bars, now=self.now)
                self.assertFalse(c["research_eligible"])

    def test_requested_missing_boundary_session_and_zero_volume_fail(self):
        from readiness_policy import historical_coverage
        for kwargs in ({"start_date": "2026-10-12"}, {"end_date": "2026-10-16"},
                       {"candles": [dict(b, volume=0) for b in self.bars]}):
            c = historical_coverage(self.cfg, None, "angelone", "RELIANCE", now=self.now,
                                    **{"candles": self.bars, **kwargs})
            self.assertFalse(c["research_eligible"])

    def test_manifests_cannot_replace_missing_or_incomplete_rows(self):
        from readiness_policy import historical_coverage
        self._history(self.bars[:-1])
        with patch.object(self.store, "query_historical_datasets", return_value={"items": [{
            "completed_bars_count": 20000, "missing_bars_count": 0, "quality_status": "COMPLETE_VERIFIED"}]}) as manifests:
            report = self._report()
            self.assertFalse(report["aggregate_coverage_ready"])
            self.assertEqual(report["symbol_coverage"]["RELIANCE"]["missing_bars_count"], 1)
            self.assertEqual(report["symbol_coverage"]["RELIANCE"]["completed_bars_count"], 224)
            manifests.assert_not_called()

    def test_truncated_reads_and_storage_errors_fail_closed(self):
        from readiness_policy import historical_coverage, live_acceptance
        with patch.object(self.store, "query_historical_candles", return_value={"total_count": 10001, "items": []}):
            self.assertEqual(historical_coverage(self.cfg, self.store, "angelone", "RELIANCE")["status"], "COVERAGE_UNVERIFIABLE_READ_LIMIT")
        with patch.object(self.store, "load_live_acceptance_evidence", side_effect=OSError("unreadable")):
            self.assertFalse(live_acceptance(self.cfg, self.store, "angelone", "RELIANCE", self.now)["accepted"])

    def test_empty_watchlist_and_complete_watchlist_states(self):
        self.cfg.equity_watchlist = []
        report = self._report()
        self.assertFalse(report["aggregate_coverage_ready"])
        self.assertFalse(report["phase3_ready_for_execution"])
        self.cfg.equity_watchlist = BotConfig().equity_watchlist[:1]
        self._history()
        self.assertTrue(self._report()["aggregate_coverage_ready"])
        self.assertFalse(self._report()["phase3_ready_for_execution"])
        self._produce()
        report = self._report()
        self.assertTrue(report["acceptance_coverage_ready_for_execution"])
        self.assertFalse(report["phase3_ready_for_execution"])
        self.assertFalse(report["historical_source_qualification"]["live_historical_replay_allowed"])

    def test_failed_or_offline_diagnostics_cannot_issue_acceptance(self):
        from diagnostics import run_angelone_diagnostics
        report = run_angelone_diagnostics(self.cfg, store=self.store, clock=lambda: self.now, skip_network=True)
        self.assertFalse(report["live_acceptance"]["accepted"])
        self.assertIsNone(self.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
        self._produce()
        report = self._produce(bad_quotes=True)
        self.assertFalse(report["live_acceptance"]["accepted"])
        self.assertIsNone(self.store.load_live_acceptance_evidence("angelone", "RELIANCE"))

    def test_receipt_is_secret_free(self):
        self._produce()
        text = json.dumps(self.store.load_live_acceptance_evidence("angelone", "RELIANCE"))
        for secret in (self.cfg.angel_api_key, self.cfg.angel_client_code, self.cfg.angel_totp_secret,
                       "FIXTURE_JWT_ONLY", "FIXTURE_REFRESH_ONLY", "FIXTURE_FEED_ONLY"):
            self.assertNotIn(secret, text)

    def test_later_store_instance_revalidates_evidence_and_additive_migration(self):
        import tempfile
        from readiness_policy import live_acceptance
        with tempfile.TemporaryDirectory() as tmp:
            url = "sqlite:///" + os.path.join(tmp, "acceptance.db")
            with SQLitePersistenceStore(url) as first:
                # Simulate the old schema and preserve existing history across reopen.
                first.save_historical_candle_dataset(self.bars, symbol="RELIANCE", provider="angelone",
                                                    instrument_token="2885", reference_time_ist=self.now)
                conn = first._get_connection()
                try:
                    with conn:
                        conn.execute("DROP TABLE live_acceptance_evidence")
                finally:
                    first._close_if_file(conn)
            with SQLitePersistenceStore(url) as migrated:
                self.assertEqual(migrated.check_health()["historical_candles_count"], 225)
                self.assertFalse(live_acceptance(self.cfg, migrated, "angelone", "RELIANCE", self.now)["accepted"])
                self._produce(migrated)
            with SQLitePersistenceStore(url) as later:
                self.assertTrue(live_acceptance(self.cfg, later, "angelone", "RELIANCE", self.now)["accepted"])
                self.assertEqual(later.check_health()["historical_candles_count"], 225)

    def test_history_must_match_receipt_instrument_scope(self):
        from backtest_engine import BacktestReadinessError
        self.cfg.equity_watchlist = self.cfg.equity_watchlist[:1]
        self._produce()
        self.store.save_historical_candle_dataset(self.bars, symbol="RELIANCE", provider="angelone",
                                                instrument_token="1333", reference_time_ist=self.now)
        with self.assertRaises(BacktestReadinessError) as caught:
            self._run()
        self.assertEqual(caught.exception.details["reason_code"], "ACCEPTANCE_EVIDENCE_SCOPE_MISMATCH")
        self.assertTrue(self._report()["aggregate_coverage_ready"])
        self.assertFalse(self._report()["phase3_ready_for_execution"])

    def test_profile_without_exchange_evidence_cannot_issue_receipt(self):
        report = self._produce(mutate=lambda responses: responses[1]["data"].update(exchanges=[]))
        self.assertFalse(report["live_acceptance"]["accepted"])
        self.assertIsNone(self.store.load_live_acceptance_evidence("angelone", "RELIANCE"))

    def test_research_rejects_synthetic_mixed_and_unknown_provenance(self):
        from readiness_policy import historical_coverage
        for provider, bars in (("paper_sim", self.bars), ("unknown_provider", self.bars),
                               ("angelone", [dict(b, is_simulated=True) for b in self.bars]),
                               ("angelone", [dict(b, provider="dhan") for b in self.bars]),
                               ("angelone", [dict(b, instrument_token="1333") for b in self.bars])):
            with self.subTest(provider=provider, metadata=bars[0].get("provider")):
                self.assertFalse(historical_coverage(self.cfg, None, provider, "RELIANCE",
                                                     candles=bars, now=self.now)["research_eligible"])

    def test_valid_live_receipt_api_readiness_and_engine_agree(self):
        import io
        from types import SimpleNamespace
        from server import DashboardRequestHandler
        from backtest_engine import BacktestEligibilityError, DeterministicBacktestEngine, main
        self.cfg.equity_watchlist = self.cfg.equity_watchlist[:1]
        self._produce()
        self._history()
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = SimpleNamespace(config=self.cfg, store=self.store, clock=lambda: self.now,
                                         get_broker_status=lambda: {"connection_state": "CONFIGURED_UNVERIFIED"})
        _, report = handler._handle_historical_readiness({"symbol": ["reliance"]})
        self.assertTrue(report["execution_gate"]["allowed"])
        self.assertFalse(report["phase3_ready_for_execution"])
        self.assertTrue(report["acceptance_coverage_ready_for_execution"])
        _, eligibility = handler._handle_backtest_eligibility({"symbol": ["reliance"]})
        self.assertEqual(eligibility["data_acceptance_status"], "LIVE_DIAGNOSTIC_ACCEPTED_RESEARCH")
        body = json.dumps({"strategy_id": "strat_1_order_block", "symbol": "RELIANCE", "data_mode": "LIVE", "persist_run": False, "historical_instrument_identity": offline_ingested_master_fixture()}).encode()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        code, result = handler._handle_post_backtest()
        self.assertEqual(code, 422, result)
        self.assertEqual(result["rejection"]["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        with self.assertRaises(BacktestEligibilityError) as caught:
            self._run()
        self.assertEqual(result["rejection"]["reason_code"], caught.exception.details["reason_code"])
        output = io.StringIO()
        def with_fixed_clock(**kwargs):
            return DeterministicBacktestEngine(**kwargs, clock=lambda: self.now)
        archive = self.store.ingest_instrument_master_bytes(json.dumps(offline_ingested_master_fixture()).encode(),
            "angelone", "offline-fixture.json", "OFFLINE_SYNTHETIC_SOURCE_DECLARATIONS")
        with patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), \
                patch("backtest_engine.DeterministicBacktestEngine", side_effect=with_fixed_clock), \
                patch("sys.stdout", output):
            code = main(["--data-mode", "LIVE", "--provider", "angelone", "--instrument-archive-id", archive["archive_id"], "--json"])
        self.assertEqual(code, 2, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["rejection"]["reason_code"], result["rejection"]["reason_code"])
        from datetime import timedelta
        self.now += timedelta(minutes=30)
        handler.rfile = io.BytesIO(body)
        code, expired = handler._handle_post_backtest()
        self.assertEqual(code, 422)
        self.assertEqual(expired["rejection"]["live_acceptance"]["reason_code"], "ACCEPTANCE_EVIDENCE_EXPIRED")

    def test_direct_cli_and_api_reject_same_forged_acceptance(self):
        import io
        from types import SimpleNamespace
        from backtest_engine import main, BacktestReadinessError
        from server import DashboardRequestHandler
        self._history()
        with self.assertRaises(BacktestReadinessError) as caught:
            self._run()
        expected = caught.exception.details["reason_code"]
        output = io.StringIO()
        archive = self.store.ingest_instrument_master_bytes(json.dumps(offline_ingested_master_fixture()).encode(),
            "angelone", "offline-fixture.json", "OFFLINE_SYNTHETIC_SOURCE_DECLARATIONS")
        with patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), patch("sys.stdout", output):
            code = main(["--strategy", "strat_1_order_block", "--symbol", "RELIANCE", "--data-mode", "LIVE", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["rejection"]["reason_code"], expected)
        body = json.dumps({"strategy_id": "strat_1_order_block", "symbol": "RELIANCE", "data_mode": "LIVE",
                           "phase2c_live_accepted": True, "connectivity_verified": True,
                           "require_live_acceptance_for_live_mode": False,
                           "acceptance_evidence": {"accepted": True}}).encode()
        handler = object.__new__(DashboardRequestHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.engine = SimpleNamespace(config=self.cfg, store=self.store,
                                         get_broker_status=lambda: {"connection_state": "CONNECTED_VERIFIED", "connectivity_verified": True})
        code, response = handler._handle_post_backtest()
        self.assertEqual(code, 422)
        self.assertEqual(response["rejection"]["reason_code"], expected)
        _, readiness = handler._handle_historical_readiness({"symbol": ["RELIANCE"]})
        self.assertEqual(readiness["execution_gate"]["reason_code"], expected)

    def test_direct_cli_api_research_parity_and_simulated_scope_mismatch(self):
        import io
        from types import SimpleNamespace
        from backtest_engine import main, BacktestConfig, BacktestReadinessError, BacktestEligibilityError
        from server import DashboardRequestHandler
        self._history()
        with self.assertRaises(BacktestEligibilityError) as caught:
            self._run("HISTORICAL_RESEARCH")
        expected = caught.exception.details["reason_code"]
        self.assertEqual(expected, "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        output = io.StringIO()
        archive = self.store.ingest_instrument_master_bytes(json.dumps(offline_ingested_master_fixture()).encode(),
            "angelone", "offline-fixture.json", "OFFLINE_SYNTHETIC_SOURCE_DECLARATIONS")
        with patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), patch("sys.stdout", output):
            code = main(["--data-mode", "LIVE", "--execution-scope", "HISTORICAL_RESEARCH", "--instrument-archive-id", archive["archive_id"], "--json"])
        self.assertEqual(code, 2, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["rejection"]["reason_code"], expected)
        body = json.dumps({"strategy_id": "strat_1_order_block", "symbol": "RELIANCE", "data_mode": "LIVE",
                           "execution_scope": "HISTORICAL_RESEARCH", "persist_run": False, "historical_instrument_identity": offline_ingested_master_fixture()}).encode()
        handler = object.__new__(DashboardRequestHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.engine = SimpleNamespace(config=self.cfg, store=self.store, get_broker_status=lambda: {})
        code, payload = handler._handle_post_backtest()
        self.assertEqual(code, 422, payload)
        self.assertEqual(payload["rejection"]["reason_code"], expected)
        for scope in ("LIVE_ACCEPTED", "HISTORICAL_RESEARCH", "anything"):
            with self.assertRaises(BacktestReadinessError):
                self.engine.run_backtest("strat_1_order_block", "RELIANCE", candles=self.bars,
                                         backtest_config=BacktestConfig(execution_scope=scope))


class TestPositionSizingRiskAccounting(unittest.TestCase):
    """Deterministic sizing, reserves and ledger reconciliation; no external calls."""

    def setUp(self):
        self.now = datetime(2026, 10, 16, 15, 30, tzinfo=IST)
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.guard = patch("urllib.request.urlopen", side_effect=AssertionError("External services forbidden"))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    @staticmethod
    def _zero_model(slippage=0, flat=0):
        from backtest_engine import IndianCostModel
        return IndianCostModel(
            brokerage_per_order_inr=0, slippage_bps_per_leg=slippage, other_cost_per_trade_inr=flat,
            stt_sell_rate_equity_intraday=0, stt_sell_rate_fo_futures=0, stt_sell_rate_fo_options=0,
            exchange_txn_rate_equity_intraday=0, exchange_txn_rate_fo_futures=0, exchange_txn_rate_fo_options=0,
            sebi_turnover_rate=0, stamp_duty_buy_rate_equity_intraday=0,
            stamp_duty_buy_rate_fo_futures=0, stamp_duty_buy_rate_fo_options=0)

    def _size(self, entry=100, stop=90, capital=10000, risk_pct=1, side="LONG", model=None, **kwargs):
        from strategies import size_position
        model = model or self._zero_model()
        return size_position(entry, stop, capital, risk_pct, side,
                             cost_estimator=lambda q: model.compute_trade_costs(entry, stop, q, side), **kwargs)

    def _run(self, side="LONG", entry=100, capital=10000, risk_pct=1, model=None,
             stop=None, lot=None, instrument_type="EQ", direction=None, exit_price=None,
             supplied_quantity=999999999, extra_signals=False, daily_loss=2000, daily_profit=4000):
        from datetime import timedelta
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine
        stop = (90 if side == "LONG" else 110) if stop is None else stop
        target = 120 if side == "LONG" else 80
        start = datetime(2026, 10, 16, 9, 15, tzinfo=IST)
        rows = [dict(timestamp=(start + timedelta(minutes=5*i)).strftime("%Y-%m-%d %H:%M:%S"),
                     open=100.0, high=101.0, low=99.0, close=100.0, volume=1000,
                     is_complete=True, is_simulated=True, data_mode="SIMULATED") for i in range(34)]
        rows[31].update(open=entry, close=entry, high=entry+.001, low=entry-.001)
        out = target if exit_price is None else exit_price
        for row in rows[32:]:
            row.update(open=out, close=out, high=out+.001, low=out-.001)
        segment = "NSE_FO_INDEX" if instrument_type == "FUTIDX" else "NSE_EQUITY_INTRADAY"
        symbol = "NIFTY" if instrument_type == "FUTIDX" else "RELIANCE"
        signal = TradeSignal(
            symbol=symbol, segment=segment, strategy_id="strat_1_order_block", strategy_name="Sizing fixture",
            direction=direction or ("BULLISH (BUY)" if side == "LONG" else "BEARISH (SELL)"),
            instrument_label=symbol, entry_price=100, entry_zone_low=99, entry_zone_high=101,
            stop_loss=stop, target_1=target, target_2=target, risk_reward="fixture", confidence_pct=0,
            win_rate_benchmark="", position_qty=supplied_quantity, capital_risk_inr=1,
            est_charges_inr=0, rationale="Isolated sizing fixture", timestamp=rows[30]["timestamp"],
            is_simulated=True, data_mode="SIMULATED")
        self.last_sizing_signal = signal
        cfg = BacktestConfig(starting_capital_inr=capital, risk_per_trade_pct=risk_pct,
                             max_daily_loss_inr=daily_loss, daily_profit_target_inr=daily_profit,
                             historical_lot_size=lot, instrument_type=instrument_type,
                             cost_model=model or self._zero_model())
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now)
        def evaluate(**kwargs):
            ts = kwargs["pit_candles"][-1]["timestamp"]
            return signal if ts == signal.timestamp or (extra_signals and ts == rows[32]["timestamp"]) else None
        with patch.object(engine, "_invoke_strategy_evaluator", side_effect=evaluate):
            result = engine.run_backtest("strat_1_order_block", symbol, candles=rows,
                                         segment=segment, exchange="NFO" if lot else "NSE",
                                         provider="paper_sim_fixture", backtest_config=cfg, persist_run=True)
        return result

    def test_minimum_share_and_lot_over_budget_are_rejected(self):
        self.assertEqual(self._size(capital=100, risk_pct=.01)["reason_code"], "INSUFFICIENT_RISK_BUDGET")
        decision = self._size(capital=10000, risk_pct=.01, instrument_type="FUTIDX", lot_size=10)
        self.assertEqual(decision["quantity"], 0)
        self.assertEqual(decision["reason_code"], "INSUFFICIENT_RISK_BUDGET")

    def test_long_and_short_exact_risk_boundaries(self):
        for side, stop in (("LONG", 90), ("SHORT", 110)):
            with self.subTest(side=side):
                decision = self._size(side=side, stop=stop)
                self.assertEqual(decision["quantity"], 10)
                self.assertEqual(decision["estimated_risk_inr"], 100)
                self.assertEqual(self._size(side=side, stop=stop, risk_pct=.9999)["quantity"], 9)

    def test_small_stop_distance_and_cent_rounding(self):
        decision = self._size(entry=1, stop=.9999, capital=100, risk_pct=.01)
        self.assertEqual(decision["quantity"], 100)
        self.assertEqual(decision["estimated_risk_inr"], .01)
        self.assertEqual(self._size(entry=1, stop=.9999, capital=100, risk_pct=.0099)["quantity"], 0)

    def test_adverse_slippage_makes_minimum_share_unaffordable(self):
        for side, stop in (("LONG", 90), ("SHORT", 110)):
            d = self._size(capital=100, risk_pct=100, side=side, stop=stop, model=self._zero_model(slippage=100))
            self.assertEqual(d["reason_code"], "INSUFFICIENT_CAPITAL")
            self.assertGreater(d["minimum_capital_required_inr"], 100)

    def test_charge_reserve_capital_boundary(self):
        model = self._zero_model(flat=2)
        self.assertEqual(self._size(capital=101.99, risk_pct=100, model=model)["quantity"], 0)
        decision = self._size(capital=102, risk_pct=100, model=model)
        self.assertEqual(decision["quantity"], 1)
        self.assertEqual(decision["capital_required_inr"], 102)
        self.assertEqual(decision["estimated_risk_inr"], 12)

    def test_costs_are_included_in_maximum_quantity(self):
        from backtest_engine import IndianCostModel
        model = IndianCostModel()
        for side, stop in (("LONG", 90), ("SHORT", 110)):
            d = self._size(side=side, stop=stop, model=model)
            q = d["quantity"]
            costs = model.compute_trade_costs(100, stop, q, side)
            self.assertEqual(d["estimated_risk_inr"], round(10*q+costs["total_costs_inr"], 2))
            self.assertLessEqual(d["estimated_risk_inr"], d["risk_budget_inr"])
            next_costs = model.compute_trade_costs(100, stop, q+1, side)
            self.assertGreater(10*(q+1)+next_costs["total_costs_inr"], d["risk_budget_inr"])

    def test_invalid_inputs_fail_closed(self):
        for field in ("entry", "stop", "capital", "risk_pct"):
            for value in (0, -1, float("nan"), float("inf"), True, "100"):
                with self.subTest(field=field, value=value):
                    self.assertFalse(self._size(**{field: value})["eligible"])
        for kwargs in ({"stop": 100}, {"stop": 101}, {"side": "unknown"},
                       {"contract_multiplier": 0}, {"contract_multiplier": -1},
                       {"contract_multiplier": float("nan")}, {"contract_multiplier": 2},
                       {"risk_pct": 101}, {"instrument_type": "INDEX_SPOT"}):
            self.assertFalse(self._size(**kwargs)["eligible"])

    def test_lots_and_long_option_premiums_use_unit_quantities(self):
        for instrument in ("FUTIDX", "OPTIDX"):
            self.assertEqual(self._size(instrument_type=instrument, lot_size=5)["quantity"], 10)
            for lot in (None, 0, -1, True, 2.5, float("nan")):
                self.assertFalse(self._size(instrument_type=instrument, lot_size=lot)["eligible"])
        self.assertFalse(self._size(side="SHORT", stop=110, instrument_type="OPTIDX", lot_size=5)["eligible"])
        self.assertFalse(self._size(lot_size=5)["eligible"])

    def test_invalid_cost_outputs_cannot_approve_sizing(self):
        from strategies import size_position
        for costs in ({}, {"charges_inr": float("nan")},
                      {"charges_inr": 0, "slippage_inr": -1, "entry_slippage_inr": 0, "effective_entry_price": 100}):
            self.assertFalse(size_position(100, 90, 1000, 1, "LONG", cost_estimator=lambda q: costs)["eligible"])

    def test_replay_recomputes_fabricated_quantity(self):
        result = self._run(supplied_quantity=999999999)
        trade = result["trades"][0]
        self.assertEqual(trade["quantity"], 10)
        self.assertEqual(trade["risk_amount_inr"], 100)
        self.assertEqual(trade["signal_metadata"]["sizing"]["quantity"], 10)

    def test_rejected_entries_have_no_equity_or_ledger_side_effects(self):
        for kwargs, reason in (({"capital": 100, "risk_pct": .01}, "INSUFFICIENT_RISK_BUDGET"),
                               ({"capital": 100, "risk_pct": 100, "model": self._zero_model(slippage=100)}, "INSUFFICIENT_CAPITAL"),
                               ({"capital": 101, "risk_pct": 100, "model": self._zero_model(flat=2)}, "INSUFFICIENT_CAPITAL")):
            with self.subTest(reason=reason):
                result = self._run(**kwargs)
                self.assertEqual(result["trades"], [])
                self.assertEqual(result["metrics"]["net_pnl_inr"], 0)
                self.assertEqual(result["ending_capital_inr"], kwargs["capital"])
                self.assertEqual(result["rejected_signals"][0]["reason"], reason)
                self.assertEqual(self.store.get_backtest_run_detail(result["run_id"])["trades"], [])
        self.assertEqual(self.store.check_health()["backtest_trades_count"], 0)

    def test_shared_helper_and_replay_agree(self):
        from backtest_engine import IndianCostModel
        for side, stop in (("LONG", 90), ("SHORT", 110)):
            model = IndianCostModel(slippage_bps_per_leg=25)
            helper = self._size(side=side, stop=stop, model=model)
            result = self._run(side=side, model=model)
            trade = result["trades"][0]
            self.assertEqual(trade["quantity"], helper["quantity"])
            self.assertEqual(trade["risk_amount_inr"], helper["estimated_risk_inr"])

    def test_trade_and_persisted_summary_reconcile_without_double_costs(self):
        from backtest_engine import IndianCostModel
        for side in ("LONG", "SHORT"):
            result = self._run(side=side, model=IndianCostModel(slippage_bps_per_leg=10))
            trade = result["trades"][0]
            sign = 1 if side == "LONG" else -1
            gross = round(sign*(trade["raw_exit_price"]-trade["raw_entry_price"])*trade["quantity"], 2)
            self.assertEqual(trade["gross_pnl_inr"], gross)
            self.assertEqual(trade["net_pnl_inr"], round(gross-trade["charges_inr"]-trade["slippage_inr"], 2))
            self.assertEqual(result["ending_capital_inr"], round(result["starting_capital_inr"]+trade["net_pnl_inr"], 2))
            saved = self.store.get_backtest_run_detail(result["run_id"])
            for key in ("gross_pnl_inr", "net_pnl_inr", "risk_amount_inr", "quantity", "total_costs_inr"):
                self.assertEqual(saved["trades"][0][key], trade[key])
            self.assertEqual(saved["metrics"]["net_pnl_inr"], trade["net_pnl_inr"])
            self.assertEqual(saved["ending_capital_inr"], result["ending_capital_inr"])

    def test_stop_fill_risk_and_gap_loss_distinction(self):
        from backtest_engine import IndianCostModel
        for side, stop, gap in (("LONG", 90, 85), ("SHORT", 110, 115)):
            stop_result = self._run(side=side, exit_price=stop, model=IndianCostModel())
            trade = stop_result["trades"][0]
            self.assertEqual(-trade["net_pnl_inr"], trade["risk_amount_inr"])
            gap_trade = self._run(side=side, exit_price=gap, model=IndianCostModel())["trades"][0]
            self.assertGreater(-gap_trade["net_pnl_inr"], gap_trade["risk_amount_inr"])

    def test_exposure_flag_invalid_config_and_cost_quantities_rejected(self):
        from backtest_engine import BacktestConfig, BacktestValidationError, IndianCostModel
        for kwargs in ({"enforce_capital_exposure_limit": False}, {"historical_lot_size": 2.5},
                       {"historical_lot_size": True}, {"max_daily_loss_inr": float("nan")},
                       {"daily_profit_target_inr": float("inf")}, {"instrument_type": "MAGIC"}):
            with self.assertRaises(BacktestValidationError): BacktestConfig(**kwargs).validate()
        for quantity in (True, 0, -1, 1.5, float("nan"), float("inf")):
            with self.assertRaises(BacktestValidationError): IndianCostModel().compute_trade_costs(100, 90, quantity, "LONG")

    def test_strategy_risk_rejection_preserves_order_block_zone(self):
        sim = SimulatedNSEAdapter(clock=lambda: self.now)
        bars = sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull")
        zones = set()
        self.assertIsNone(evaluate_order_block_fvg("RELIANCE", bars, capital_inr=1, risk_pct=.001,
                                                 now=self.now, mitigated_zones=zones))
        self.assertEqual(zones, set())
        self.assertIsNotNone(evaluate_order_block_fvg("RELIANCE", bars, now=self.now, mitigated_zones=zones))

    def test_option_minimum_lot_is_not_forced(self):
        sim = SimulatedNSEAdapter(clock=lambda: self.now)
        for symbol, lot in (("NIFTY", 75), ("BANKNIFTY", 30)):
            bars = sim.get_intraday_candles({"symbol": symbol}, pattern="vwap_pullback_bull")
            chain = sim.get_option_chain(symbol, bias="BULLISH")
            self.assertIsNone(evaluate_option_apex_oi_shift(symbol, bars, chain, lot_size=lot,
                                                           capital_inr=1000, risk_pct=1, now=self.now))
            self.assertIsNone(evaluate_option_apex_oi_shift(symbol, bars, chain, capital_inr=1000000, now=self.now))

    def test_futures_use_whole_lots_and_full_notional_without_invented_margin(self):
        accepted = self._run(capital=1000, risk_pct=10, lot=10, instrument_type="FUTIDX")
        self.assertEqual(accepted["trades"][0]["quantity"], 10)
        self.assertEqual(accepted["trades"][0]["signal_metadata"]["sizing"]["capital_required_inr"], 1000)
        rejected = self._run(capital=999.99, risk_pct=100, lot=10, instrument_type="FUTIDX")
        self.assertEqual(rejected["trades"], [])
        self.assertEqual(rejected["rejected_signals"][0]["reason"], "INSUFFICIENT_CAPITAL")

    def test_scanner_recomputes_supplied_quantity_with_its_existing_cost_schedule(self):
        from strategies import size_position
        self._run()
        signal = self.last_sizing_signal
        signal.position_qty = 999999999
        signal.capital_risk_inr = float("nan")
        cfg = BotConfig(active_broker="paper_sim", account_capital_inr=10000,
                        max_risk_per_trade_pct=1, database_url=":memory:", telegram_dry_run=True)
        cfg.equity_watchlist = cfg.equity_watchlist[:1]
        broker = MultiBrokerScanner(cfg, clock=lambda: self.now)
        broker.adapters["paper_sim"] = _FixtureTriggeredAdapter(SimulatedNSEAdapter(clock=lambda: self.now))
        engine = IntradayBotEngine(cfg, clock=lambda: self.now, broker_scanner=broker, store=self.store)
        with patch("scanner_engine.evaluate_order_block_fvg", side_effect=lambda **kw: signal if kw["symbol"] == "RELIANCE" else None), \
             patch("scanner_engine.evaluate_option_apex_oi_shift", return_value=None), \
             patch("scanner_engine.evaluate_vwap_pullback", return_value=None), \
             patch("scanner_engine.evaluate_orb_breakout", return_value=None), \
             patch("scanner_engine.evaluate_supertrend_pullback", return_value=None), \
             patch.object(engine.telegram, "send_signal", return_value={"ok": True}):
            result = engine.run_single_scan()
        expected = size_position(100, 90, 10000, 1, "LONG")
        self.assertEqual(result["total_signals"], 1)
        self.assertEqual(result["signals"][0]["position_qty"], expected["quantity"])
        self.assertEqual(result["signals"][0]["capital_risk_inr"], expected["estimated_risk_inr"])
        self.assertEqual(self.store.query_signals()["items"][0]["position_qty"], expected["quantity"])

    def test_storage_does_not_truncate_or_coerce_quantities(self):
        import copy
        from storage import PersistenceValidationError
        result = self._run()
        for invalid in (True, 0, -1, 2.5, float("nan"), float("inf")):
            with self.subTest(quantity=invalid):
                sig = copy.deepcopy(self.last_sizing_signal)
                sig.position_qty = invalid
                with self.assertRaises(PersistenceValidationError):
                    self.store.save_signal(sig, broker="paper_sim")
                trade = copy.deepcopy(result["trades"][0])
                trade["quantity"] = invalid
                with self.assertRaises(PersistenceValidationError):
                    self.store.save_backtest_run(result, [trade])
        self.assertEqual(self.store.check_health()["signals_count"], 0)
        self.assertEqual(self.store.check_health()["backtest_trades_count"], 1)

    def test_api_rejects_fractional_lots_and_boolean_numeric_controls(self):
        import io
        from types import SimpleNamespace
        from server import DashboardRequestHandler
        cfg = BotConfig(database_url=":memory:")
        for bad in ({"historical_lot_size": 2.5}, {"historical_lot_size": True},
                    {"risk_per_trade_pct": True}, {"starting_capital_inr": True},
                    {"max_concurrent_positions": 2.5}):
            handler = object.__new__(DashboardRequestHandler)
            body = json.dumps({"strategy_id": "strat_1_order_block", "symbol": "RELIANCE", **bad}).encode()
            handler.headers = {"Content-Length": str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.engine = SimpleNamespace(config=cfg, store=self.store, get_broker_status=lambda: {})
            code, payload = handler._handle_post_backtest()
            self.assertEqual(code, 400, payload)
        self.assertEqual(self.store.check_health()["backtest_runs_count"], 0)

    def test_realized_daily_limits_block_subsequent_entries(self):
        for exit_price, reason, kwargs in (
            (90, "DAILY_LOSS_LIMIT_REACHED", {"daily_loss": 50}),
            (120, "DAILY_PROFIT_TARGET_REACHED", {"daily_profit": 50}),
        ):
            result = self._run(exit_price=exit_price, extra_signals=True, **kwargs)
            self.assertEqual(len(result["trades"]), 1)
            self.assertEqual(result["rejected_signals"][0]["reason"], reason)
            self.assertEqual(result["ending_capital_inr"], 10000+result["trades"][0]["net_pnl_inr"])

    def test_default_config_does_not_replace_invalid_budgets_with_fallbacks(self):
        from backtest_engine import DeterministicBacktestEngine, BacktestValidationError
        for field, value in (("account_capital_inr", 0), ("account_capital_inr", True),
                             ("max_risk_per_trade_pct", 0), ("max_risk_per_trade_pct", True),
                             ("max_concurrent_positions", 0)):
            cfg = BotConfig(database_url=":memory:")
            setattr(cfg, field, value)
            engine = DeterministicBacktestEngine(bot_config=cfg, store=self.store)
            with self.assertRaises(BacktestValidationError):
                engine.run_backtest("strat_1_order_block", "RELIANCE")


class TestStateIsolation(unittest.TestCase):
    """State boundaries only; providers and Telegram transports are offline fixtures."""

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.now)
        bars = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull")
        self.signal = evaluate_order_block_fvg("RELIANCE", bars, now=self.now)
        self.assertIsNotNone(self.signal)
        self.signal.provider = "paper_sim"
        self.signal.state_context = "SCANNER"
        self.signal.is_simulated = True
        self.signal.data_mode = "SIMULATED"
        self.zones = {"RELIANCE:OB:BULL:2026-10-16 10:00:00"}
        self.network = patch("urllib.request.urlopen", side_effect=AssertionError("External services forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def _signal(self, **changes):
        from instrument_identity import spot_identity
        data = dict(self.signal.to_dict(), **changes)
        if (data["data_mode"] == "LIVE" and data["state_context"] == "SCANNER"
                and data["provider"] in ("angelone", "dhan", "upstox")):
            data["instrument_identity"] = spot_identity(self.cfg_meta(data["symbol"]), data["provider"])
        return TradeSignal(**data)

    @staticmethod
    def cfg_meta(symbol):
        return next(m for m in BotConfig().equity_watchlist if m["symbol"] == symbol)

    def _scope(self, **changes):
        return dict(dict(provider="paper_sim", data_mode="SIMULATED", state_context="SCANNER",
                         segment="NSE_EQUITY_INTRADAY", interval_min=5), **changes)

    def _engine(self, store=None, provider="paper_sim"):
        cfg = BotConfig(active_broker=provider, account_capital_inr=500000,
                        telegram_dry_run=True, database_url=":memory:")
        scanner = MultiBrokerScanner(cfg, clock=lambda: self.now)
        scanner.adapters[provider] = _BidirectionalFixtureAdapter(self.sim)
        engine = IntradayBotEngine(cfg, clock=lambda: self.now, broker_scanner=scanner,
                                   store=store or self.store)
        self.addCleanup(engine.close)
        return engine

    def test_signal_providers_are_independent_and_same_scope_deduplicates(self):
        for provider in ("angelone", "dhan"):
            sig = self._signal(provider=provider, is_simulated=False, data_mode="LIVE")
            self.assertTrue(self.store.save_signal(sig, broker="Display label")[0])
            self.assertFalse(self.store.save_signal(sig, broker="Renamed display label")[0])
            rows = self.store.query_signals(provider=provider, data_mode="LIVE", state_context="SCANNER")
            self.assertEqual(rows["total_count"], 1)
            self.assertEqual(rows["items"][0]["provider"], provider)
        self.assertEqual(self.store.query_signals()["total_count"], 2)

    def test_signal_scanner_research_and_replay_contexts_are_independent(self):
        cases = [("angelone", "LIVE", "SCANNER"), ("angelone", "LIVE", "HISTORICAL_RESEARCH"),
                 ("angelone", "LIVE", "LIVE_ACCEPTED"), ("angelone", "SIMULATED", "SCANNER"),
                 ("angelone", "SIMULATED", "SIMULATED_TEST"), ("synthetic_fixture", "SIMULATED", "SIMULATED_TEST")]
        keys = set()
        for provider, mode, context in cases:
            sig = self._signal(provider=provider, data_mode=mode, is_simulated=mode == "SIMULATED",
                               state_context=context)
            inserted, key = self.store.save_signal(sig, broker="Offline fixture")
            self.assertTrue(inserted)
            keys.add(key)
            self.assertEqual(self.store.query_signals(provider=provider, data_mode=mode,
                                                     state_context=context)["total_count"], 1)
        self.assertEqual(len(keys), len(cases))

    def test_signal_direction_contract_segment_and_timeframe_are_independent(self):
        signals = [self.signal, self._signal(direction="BEARISH (SELL)"),
                   self._signal(instrument_label="RELIANCE OTHER CONTRACT"),
                   self._signal(segment="NSE_FO_INDEX"), self._signal(interval_min=15),
                   self._signal(timestamp="2026-10-16 10:30:30")]
        for sig in signals:
            self.assertTrue(self.store.save_signal(sig, broker="Fixture")[0])
        self.assertEqual(self.store.query_signals()["total_count"], len(signals))
        self.assertEqual(self.store.query_signals(interval_min=15)["total_count"], 1)

    def test_signal_timestamp_normalization_and_provider_alias_dedup(self):
        first = self._signal(provider="sim", timestamp="2026-10-16T05:00:00+00:00")
        second = self._signal(provider="paper_sim", timestamp="2026-10-16 10:30:00")
        self.assertTrue(self.store.save_signal(first, broker="Fixture")[0])
        self.assertFalse(self.store.save_signal(second, broker="Fixture")[0])
        self.assertEqual(self.store.query_signals(provider="simulated")["total_count"], 1)

    def test_unknown_sources_are_label_partitioned_and_never_promoted(self):
        sig = self._signal(provider="unknown", state_context="UNKNOWN")
        for label in ("Angel One SmartAPI", "DhanHQ API v2"):
            self.assertTrue(self.store.save_signal(sig, broker=label)[0])
        self.assertEqual(self.store.query_signals(provider="angelone")["total_count"], 0)
        self.assertTrue(all(r["provider"] == "unknown" for r in self.store.query_signals()["items"]))

    def test_scoped_provenance_does_not_depend_on_display_label(self):
        sig = self._signal(provider="dhan", data_mode="LIVE", is_simulated=False)
        first = self.store.save_signal(sig, broker="Display label")[1]
        inserted, second = self.store.save_signal(sig, broker="Display label mentions SIMULATED")
        self.assertFalse(inserted)
        self.assertEqual(first, second)
        dispatcher = TelegramSignalDispatcher(BotConfig(telegram_dry_run=True))
        first_alert = dispatcher.send_signal(sig, broker_name="Display label")
        self.assertFalse(first_alert["is_simulated"])
        self.assertNotIn("SIMULATED DATA", first_alert["message_html"])
        self.assertTrue(dispatcher.send_signal(sig, broker_name="Display label mentions SIMULATED")["skipped"])

    def test_invalid_provenance_rejected_without_state_changes(self):
        from storage import PersistenceValidationError
        for change in (dict(data_mode="TYPO", is_simulated=False),
                       dict(data_mode="LIVE", is_simulated=False),
                       dict(state_context="HISTORICAL_RESEARCH"), dict(interval_min=True)):
            with self.assertRaises(PersistenceValidationError):
                self.store.save_signal(self._signal(**change), broker="Fixture")
        self.assertEqual(self.store.query_signals()["total_count"], 0)
        with self.assertRaises(ValueError):
            self.store.load_mitigated_order_blocks(**self._scope(provider="unknown"))
        with self.assertRaises(TypeError):
            self.store.load_mitigated_order_blocks()

    def test_zone_provider_mode_context_segment_timeframe_and_direction_isolation(self):
        variants = [{}, dict(provider="dhan"), dict(provider="dhan", data_mode="LIVE"),
                    dict(provider="dhan", data_mode="LIVE", state_context="HISTORICAL_RESEARCH"),
                    dict(provider="dhan", data_mode="LIVE", state_context="LIVE_ACCEPTED"),
                    dict(state_context="SIMULATED_TEST"), dict(segment="NSE_FO_INDEX"), dict(interval_min=15)]
        for change in variants:
            scope = self._scope(**change)
            self.assertEqual(self.store.load_mitigated_order_blocks(**scope), set())
            self.assertEqual(self.store.save_mitigated_order_blocks(self.zones, **scope), 1)
            self.assertEqual(self.store.save_mitigated_order_blocks(self.zones, **scope), 0)
        bearish = {next(iter(self.zones)).replace(":BULL:", ":BEAR:")}
        self.assertEqual(self.store.save_mitigated_order_blocks(bearish, **self._scope()), 1)
        self.assertEqual(self.store.load_mitigated_order_blocks(**self._scope()), self.zones | bearish)
        self.assertEqual(self.store.load_mitigated_order_blocks(**self._scope(provider="dhan")), self.zones)

    def test_zone_mitigation_affects_only_own_scope(self):
        bars = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull")
        a = self.store.load_mitigated_order_blocks(**self._scope())
        b_scope = self._scope(provider="dhan")
        b = self.store.load_mitigated_order_blocks(**b_scope)
        self.assertIsNotNone(evaluate_order_block_fvg("RELIANCE", bars, now=self.now, mitigated_zones=a))
        self.store.save_mitigated_order_blocks(a, **self._scope())
        self.assertIsNone(evaluate_order_block_fvg("RELIANCE", bars, now=self.now, mitigated_zones=a))
        self.assertEqual(self.store.load_mitigated_order_blocks(**b_scope), set())
        self.assertIsNotNone(evaluate_order_block_fvg("RELIANCE", bars, now=self.now, mitigated_zones=b))
        self.store.save_mitigated_order_blocks(b, **b_scope)
        self.assertEqual(a, b)

    def test_scanner_provider_switch_and_reload_do_not_reuse_zones(self):
        engine = self._engine()
        first = engine.run_single_scan()
        first_ob = sum(s["strategy_id"] == "strat_1_order_block" for s in first["signals"])
        self.assertGreaterEqual(first_ob, 2)
        engine.broker.adapters["dhan"] = _BidirectionalFixtureAdapter(self.sim)
        engine.config.active_broker = "dhan"
        self.assertEqual(engine.mitigated_order_blocks, set())
        second = engine.run_single_scan()
        self.assertEqual(sum(s["strategy_id"] == "strat_1_order_block" for s in second["signals"]), first_ob)
        self.assertEqual(second["duplicate_signals"], 0)
        self.assertTrue(all(s["provider"] == "dhan" and s["state_context"] == "SCANNER" for s in second["signals"]))
        engine.config.active_broker = "paper_sim"
        third = engine.run_single_scan()
        self.assertEqual(sum(s["strategy_id"] == "strat_1_order_block" for s in third["signals"]), 0)
        reloaded = self._engine()
        self.assertGreaterEqual(len(reloaded.mitigated_order_blocks), 2)
        self.assertEqual(reloaded.run_single_scan()["persisted_signals"], 0)

    def test_scanner_provider_aliases_share_the_same_scope(self):
        engine = self._engine()
        fixture = engine.broker.adapters["paper_sim"]
        first = engine.run_single_scan()
        engine.broker.adapters["sim"] = fixture
        engine.config.active_broker = "sim"
        second = engine.run_single_scan()
        self.assertGreater(first["persisted_signals"], 0)
        self.assertEqual(second["persisted_signals"], 0)

    def test_telegram_provider_mode_context_and_direction_isolation(self):
        dispatcher = TelegramSignalDispatcher(BotConfig(telegram_dry_run=True))
        signals = [self.signal, self._signal(provider="dhan"), self._signal(direction="BEARISH (SELL)"),
                   self._signal(state_context="SIMULATED_TEST"),
                   self._signal(provider="dhan", data_mode="LIVE", is_simulated=False)]
        for sig in signals:
            self.assertFalse(dispatcher.send_signal(sig, broker_name="Fixture").get("skipped", False))
            self.assertTrue(dispatcher.send_signal(sig, broker_name="Fixture").get("skipped"))
        self.assertEqual(len(dispatcher.sent_cache), len(signals))

    def test_telegram_full_timestamp_contract_and_timeframe_identity(self):
        dispatcher = TelegramSignalDispatcher(BotConfig(telegram_dry_run=True))
        for sig in (self.signal, self._signal(timestamp="2026-10-16 10:30:30"),
                    self._signal(interval_min=15), self._signal(instrument_label="OTHER CONTRACT")):
            self.assertFalse(dispatcher.send_signal(sig).get("skipped", False))
        self.assertEqual(len(dispatcher.sent_cache), 4)

    def test_telegram_preview_and_destination_changes_do_not_suppress_delivery(self):
        import io
        cfg = BotConfig(telegram_dry_run=True, telegram_bot_token="TEST_ONLY", telegram_chat_id="fixture-one")
        dispatcher = TelegramSignalDispatcher(cfg)
        self.assertTrue(dispatcher.send_signal(self.signal)["dry_run"])
        cfg.telegram_dry_run = False
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(b'{"ok":true}')) as transport:
            self.assertTrue(dispatcher.send_signal(self.signal)["ok"])
            self.assertTrue(dispatcher.send_signal(self.signal)["skipped"])
            cfg.telegram_chat_id = "fixture-two"
            self.assertTrue(dispatcher.send_signal(self.signal)["ok"])
            cfg.telegram_bot_token = "TEST_ONLY_SECOND_DESTINATION"
            self.assertTrue(dispatcher.send_signal(self.signal)["ok"])
            self.assertEqual(transport.call_count, 3)

    def test_telegram_failure_or_format_exception_does_not_poison_cache(self):
        import io
        cfg = BotConfig(telegram_dry_run=False, telegram_bot_token="TEST_ONLY", telegram_chat_id="fixture")
        dispatcher = TelegramSignalDispatcher(cfg)
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(RuntimeError):
                dispatcher.send_signal(self.signal)
        self.assertEqual(dispatcher.sent_cache, set())
        with patch.object(dispatcher, "format_signal_html", side_effect=ValueError("fixture")):
            with self.assertRaises(ValueError):
                dispatcher.send_signal(self.signal)
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(b'{"ok":false}')):
            self.assertFalse(dispatcher.send_signal(self.signal)["ok"])
        self.assertEqual(dispatcher.sent_cache, set())
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(b'{"ok":true}')):
            self.assertTrue(dispatcher.send_signal(self.signal)["ok"])

    def test_telegram_concurrent_duplicate_sends_are_serialized(self):
        import io
        import threading
        from concurrent.futures import ThreadPoolExecutor
        cfg = BotConfig(telegram_dry_run=False, telegram_bot_token="TEST_ONLY", telegram_chat_id="fixture")
        dispatcher = TelegramSignalDispatcher(cfg)
        barrier = threading.Barrier(8)
        def send(_):
            barrier.wait(timeout=10)
            return dispatcher.send_signal(self.signal)
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(b'{"ok":true}')) as transport:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(send, range(8)))
            self.assertEqual(transport.call_count, 1)
        self.assertEqual(sum(bool(r.get("skipped")) for r in results), 7)

    def test_telegram_restart_clears_only_process_cache_and_new_candle_is_independent(self):
        cfg = BotConfig(telegram_dry_run=True)
        dispatcher = TelegramSignalDispatcher(cfg)
        dispatcher.send_signal(self.signal)
        self.assertTrue(dispatcher.send_signal(self.signal)["skipped"])
        self.assertFalse(dispatcher.send_signal(self._signal(timestamp="2026-10-16 10:35:00")).get("skipped", False))
        self.assertFalse(TelegramSignalDispatcher(cfg).send_signal(self.signal).get("skipped", False))

    def test_research_and_unknown_alerts_do_not_claim_live_scanner_evidence(self):
        dispatcher = TelegramSignalDispatcher(BotConfig(telegram_dry_run=True))
        for context in ("HISTORICAL_RESEARCH", "LIVE_ACCEPTED", "UNKNOWN"):
            sig = self._signal(provider="angelone", data_mode="LIVE", is_simulated=False, state_context=context)
            message = dispatcher.format_signal_html(sig, "Offline fixture")
            self.assertNotIn("LIVE SIGNAL", message)
            self.assertIn(context, message)
        unknown = self._signal(provider="unknown", data_mode="LIVE", is_simulated=False)
        self.assertNotIn("LIVE SIGNAL", dispatcher.format_signal_html(unknown, "Angel One SmartAPI"))

    def test_api_signal_filters_keep_scope_and_aggregate_history_explicit(self):
        from types import SimpleNamespace
        from server import DashboardRequestHandler
        for provider in ("paper_sim", "dhan"):
            self.store.save_signal(self._signal(provider=provider), broker="Fixture")
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = SimpleNamespace(store=self.store)
        code, rows = handler._handle_signals({"provider": ["dhan"], "data_mode": ["SIMULATED"],
                                            "state_context": ["SCANNER"]})
        self.assertEqual(code, 200)
        self.assertEqual(rows["total_count"], 1)
        self.assertEqual(rows["items"][0]["provider"], "dhan")
        self.assertEqual(handler._handle_signals({})[1]["total_count"], 2)

    def test_legacy_migration_is_additive_deterministic_and_fails_closed(self):
        import sqlite3
        import tempfile
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "legacy.db")
            with SQLitePersistenceStore(path) as old:
                old.save_signal(self.signal, broker="Legacy broker label")
            # Reconstruct the preceding schema: original columns/key and global zones.
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("DROP INDEX idx_signals_state_scope")
                for column in ("provider", "state_context", "interval_min", "instrument_identity_json"):
                    conn.execute(f"ALTER TABLE signals DROP COLUMN {column}")
                conn.execute("DROP TABLE scoped_mitigated_order_blocks")
                conn.execute("UPDATE signals SET dedup_key='legacy-original-key'")
                conn.execute("INSERT INTO mitigated_order_blocks VALUES (?,?,?,?,?,?)",
                             (next(iter(self.zones)), "RELIANCE", "BULL", "2026-10-16 10:00:00",
                              "2026-10-16 10:30:00", "SIMULATED"))
                before_columns = [r[1] for r in conn.execute("PRAGMA table_info(signals)")]
                before = conn.execute("SELECT * FROM signals").fetchall()
                old_zones = conn.execute("SELECT * FROM mitigated_order_blocks").fetchall()
            for _ in range(2):
                with SQLitePersistenceStore(path) as store:
                    row = store.query_signals()["items"][0]
                    self.assertEqual((row["provider"], row["state_context"], row["interval_min"]),
                                     ("unknown", "LEGACY_UNSCOPED", 0))
                    self.assertEqual(row["instrument_identity"], {})
                    self.assertEqual(store.query_signals(provider="paper_sim")["total_count"], 0)
                    self.assertEqual(store.load_mitigated_order_blocks(**self._scope()), set())
            with SQLitePersistenceStore(path) as store:
                self.assertTrue(store.save_signal(self.signal, broker="Current fixture")[0])
                self.assertEqual(store.save_mitigated_order_blocks(self.zones, **self._scope()), 1)
            with SQLitePersistenceStore(path) as restarted:
                self.assertFalse(restarted.save_signal(self.signal, broker="Current fixture")[0])
                self.assertEqual(restarted.load_mitigated_order_blocks(**self._scope()), self.zones)
                self.assertEqual(restarted.load_mitigated_order_blocks(**self._scope(provider="dhan")), set())
            with closing(sqlite3.connect(path)) as conn:
                columns = ','.join(before_columns)
                self.assertEqual(conn.execute(f"SELECT {columns} FROM signals WHERE dedup_key='legacy-original-key'").fetchall(), before)
                self.assertEqual(conn.execute("SELECT * FROM mitigated_order_blocks").fetchall(), old_zones)

    def test_concurrent_database_writers_dedup_without_cross_scope_mutation(self):
        import tempfile
        import threading
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "concurrent.db")
            with SQLitePersistenceStore(path) as a, SQLitePersistenceStore(path) as b:
                barrier = threading.Barrier(8)
                def save(i):
                    barrier.wait(timeout=10)
                    provider = "dhan" if i % 2 else "paper_sim"
                    store = a if i % 3 else b
                    result = store.save_signal(self._signal(provider=provider), broker="Fixture")[0]
                    count = store.save_mitigated_order_blocks(self.zones, **self._scope(provider=provider))
                    return result, count
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(save, range(8)))
                self.assertEqual(sum(r[0] for r in results), 2)
                self.assertEqual(sum(r[1] for r in results), 2)
                self.assertEqual(a.query_signals()["total_count"], 2)
                for provider in ("paper_sim", "dhan"):
                    self.assertEqual(b.load_mitigated_order_blocks(**self._scope(provider=provider)), self.zones)

    def test_concurrent_schema_initialization_is_safe(self):
        import tempfile
        import threading
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "initialize.db")
            barrier = threading.Barrier(4)
            def initialize(_):
                barrier.wait(timeout=10)
                with SQLitePersistenceStore(path) as store:
                    return store.save_signal(self.signal, broker="Fixture")[0]
            with ThreadPoolExecutor(max_workers=4) as pool:
                inserted = list(pool.map(initialize, range(4)))
            self.assertEqual(sum(inserted), 1)
            with SQLitePersistenceStore(path) as restarted:
                self.assertEqual(restarted.query_signals()["total_count"], 1)

    def test_historical_research_provenance_does_not_leak_into_scanner_state(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        rows = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        stamp = rows[30]["timestamp"]
        sig = self._signal(provider="unknown", state_context="UNKNOWN", timestamp=stamp,
                           entry_price=2958, entry_zone_low=2900, entry_zone_high=3100,
                           stop_loss=2900, invalidation_level=2900, target_1=3100, target_2=3200)
        self.store.save_signal(self.signal, broker="Scanner fixture")
        self.store.save_mitigated_order_blocks(self.zones, **self._scope())
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now)
        def evaluate(**kwargs):
            return sig if kwargs["pit_candles"][-1]["timestamp"] == stamp else None
        before = sig.to_dict()
        with patch.object(engine, "_invoke_strategy_evaluator", side_effect=evaluate) as evaluator, self.assertRaises(BacktestEligibilityError) as caught:
            engine.run_backtest("strat_1_order_block", "RELIANCE", provider="angelone", data_mode="LIVE",
                               candles=rows, backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", historical_instrument_identity=offline_ingested_master_fixture()))
        evaluator.assert_not_called()
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        self.assertEqual(sig.to_dict(), before)
        self.assertEqual(self.store.query_signals()["total_count"], 1)
        self.assertEqual(self.store.query_signals(provider="angelone")["total_count"], 0)
        self.assertEqual(self.store.load_mitigated_order_blocks(**self._scope()), self.zones)

    def test_replay_zones_and_signal_provenance_are_local_to_each_run(self):
        from datetime import timedelta
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel
        rows = self.sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull")
        price = rows[-1]["close"]
        rows.append(dict(timestamp=(parse_ist_timestamp(rows[-1]["timestamp"]) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
                         open=price, high=price*1.0001, low=price*.9999, close=price, volume=100000,
                         is_complete=True, is_simulated=True, data_mode="SIMULATED"))
        self.store.save_mitigated_order_blocks(self.zones, **self._scope())
        initial_count = self.store.query_signals()["total_count"]
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now + timedelta(hours=1))
        results = [engine.run_backtest("strat_1_order_block", "RELIANCE", candles=rows,
                                      provider="synthetic_fixture", data_mode="SIMULATED", persist_run=True,
                                      backtest_config=BacktestConfig(cost_model=IndianCostModel(slippage_bps_per_leg=0)))
                   for _ in range(2)]
        self.assertGreater(len(results[0]["trades"]), 0)
        self.assertEqual(len(results[0]["trades"]), len(results[1]["trades"]))
        for result in results:
            for trade in result["trades"]:
                meta = trade["signal_metadata"]
                self.assertEqual((meta["provider"], meta["data_mode"], meta["state_context"]),
                                 ("synthetic_fixture", "SIMULATED", "SIMULATED_TEST"))
        self.assertEqual(self.store.load_mitigated_order_blocks(**self._scope()), self.zones)
        self.assertEqual(self.store.query_signals()["total_count"], initial_count)


class TestMarketDataFreshness(unittest.TestCase):
    """Deterministic live-policy and normal-entry-path tests; no external services."""

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.cfg = BotConfig(active_broker="dhan", database_url=":memory:", telegram_dry_run=True,
                             dhan_client_id="FIXTURE_CLIENT", dhan_access_token="FIXTURE_TOKEN",
                             upstox_access_token="FIXTURE_TOKEN", angel_api_key="FIXTURE_KEY",
                             angel_client_code="FIXTURE_CLIENT", angel_pin="7531",
                             angel_totp_secret="JBSWY3DPEHPK3PXP")
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.network = patch("urllib.request.urlopen", side_effect=AssertionError("External services forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    @staticmethod
    def _bar(stamp="2026-10-16T10:30:00+05:30", **changes):
        return dict(dict(timestamp=stamp, open=100.0, high=102.0, low=99.0, close=101.0, volume=1000,
                         is_simulated=False, data_mode="LIVE"), **changes)

    def _assess(self, bars=None, **changes):
        from brokers import assess_live_candle_batch
        return assess_live_candle_batch([self._bar()] if bars is None else bars,
                                        **dict(dict(now_ist=self.now, provider="dhan", symbol="RELIANCE",
                                                    context="SCANNER"), **changes))

    def _live_engine(self, rows=None):
        sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.now)
        if rows is None:
            rows = [dict(c, timestamp=c["timestamp"].replace(" ", "T") + "+05:30",
                         data_mode="LIVE", is_simulated=False)
                    for c in sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull")]
        scanner = MultiBrokerScanner(self.cfg, clock=lambda: self.now)
        engine = IntradayBotEngine(self.cfg, clock=lambda: self.now, broker_scanner=scanner, store=self.store)
        self.addCleanup(engine.close)
        # Exercise the engine boundary even when the fetch method is replaced by a test adapter.
        scanner.fetch_candles = MagicMock(side_effect=lambda *a, **k: [dict(c) for c in rows])
        scanner.fetch_option_chain = MagicMock(side_effect=UnsupportedBrokerCapabilityError("Fixture has no option chain"))
        return engine

    def test_fresh_completed_bar_and_configured_age_boundary(self):
        from datetime import timedelta
        for delay, allowed in ((360, True), (361, False)):
            now = datetime(2026, 10, 16, 10, 35, tzinfo=IST) + timedelta(seconds=delay)
            _, report = self._assess(now_ist=now)
            self.assertEqual(report["live_signal_allowed"], allowed)
        normalized, report = self._assess()
        self.assertTrue(report["live_signal_allowed"])
        self.assertEqual(normalized[0]["timestamp_timezone"], "Asia/Kolkata")
        self.assertEqual(report["latest_completed_timestamp_ist"], "2026-10-16 10:30:00")

    def test_provider_delay_is_configurable_and_legacy_override_cannot_relax(self):
        from datetime import timedelta
        now = self.now + timedelta(minutes=7)
        self.assertFalse(self._assess(now_ist=now)[1]["is_fresh"])
        self.assertTrue(self._assess(now_ist=now, max_delay_seconds=120)[1]["is_fresh"])
        self.assertFalse(self._assess(now_ist=now, max_staleness_minutes=10000)[1]["is_fresh"])

    def test_stale_completed_bar_cannot_be_rescued_by_a_forming_bar(self):
        # Consecutive incomplete bars cannot count as freshness evidence, even after elapsed wall time.
        bars = [self._bar("2026-10-16T10:15:00+05:30")]
        bars += [self._bar(f"2026-10-16T10:{m}:00+05:30", is_complete=False) for m in (20, 25, 30, 35)]
        self.assertEqual(self._assess(bars)[1]["status"], "STALE")

    def test_forming_candle_true_flag_cannot_override_completion(self):
        bars = [self._bar(), self._bar("2026-10-16T10:35:00+05:30", is_complete=True)]
        normalized, report = self._assess(bars)
        self.assertTrue(report["is_fresh"])
        self.assertFalse(normalized[-1]["is_complete"])
        self.assertEqual(report["completed_candles"], 1)
        self.assertEqual(self._assess(bars[1:])[1]["status"], "NO_COMPLETED_CANDLES")

    def test_future_skew_is_bounded_and_never_completes_a_candle_early(self):
        from datetime import timedelta
        stamp = "2026-10-16T10:35:00+05:30"
        for seconds, code in ((5, "NO_COMPLETED_CANDLES"), (6, "FUTURE_TIMESTAMP")):
            _, report = self._assess([self._bar(stamp)], now_ist=self.now-timedelta(seconds=seconds))
            self.assertEqual(report["status"], code)

    def test_missing_malformed_and_naive_timestamps_are_rejected(self):
        for stamp in (None, True, "", "bad timestamp", "2026-10-16", "2026-10-16 10:30:00",
                      datetime(2026, 10, 16, 10, 30), float("nan"), float("inf")):
            with self.subTest(stamp=repr(stamp)):
                self.assertEqual(self._assess([self._bar(stamp)])[1]["status"], "INVALID_TIMESTAMP")

    def test_utc_offsets_and_epoch_units_normalize_to_same_instant(self):
        from datetime import timezone
        value = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)
        for stamp in (value, value.isoformat(), "2026-10-16T05:00:00Z", value.timestamp(), value.timestamp()*1000):
            normalized, report = self._assess([self._bar(stamp)])
            self.assertTrue(report["live_signal_allowed"])
            self.assertEqual(normalized[0]["timestamp"], "2026-10-16 10:30:00")

    def test_normalized_local_timestamp_requires_explicit_boundary_convention(self):
        bar = self._bar("2026-10-16 10:30:00")
        self.assertEqual(self._assess([bar])[1]["status"], "INVALID_TIMESTAMP")
        self.assertTrue(self._assess([bar], normalized_ist=True)[1]["live_signal_allowed"])

    def test_order_duplicates_grid_gaps_interval_and_ohlcv_rejections(self):
        cases = [([self._bar(), self._bar()], {}, "DUPLICATE_TIMESTAMP"),
                 ([self._bar(), self._bar("2026-10-16T10:25:00+05:30")], {}, "OUT_OF_ORDER"),
                 ([self._bar("2026-10-16T10:20:00+05:30"), self._bar()], {}, "CANDLE_GAP"),
                 ([self._bar("2026-10-16T10:31:00+05:30")], {}, "INVALID_CANDLE_GRID"),
                 ([self._bar()], dict(interval_min=True), "INVALID_INTERVAL"),
                 ([self._bar(interval_min=15)], {}, "INVALID_INTERVAL"),
                 ([self._bar(high=50)], {}, "MALFORMED_CANDLE"),
                 ([self._bar(is_complete="true")], {}, "INVALID_COMPLETION"),
                 ([], {}, "EMPTY")]
        for bars, kwargs, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self._assess(bars, **kwargs)[1]["status"], expected)

    def test_current_session_open_requires_current_completed_data(self):
        friday_close = [self._bar("2026-10-15T15:25:00+05:30")]
        self.assertEqual(self._assess(friday_close, now_ist=datetime(2026, 10, 16, 9, 15, tzinfo=IST))[1]["status"], "STALE")
        first = [self._bar("2026-10-16T09:15:00+05:30")]
        self.assertEqual(self._assess(first, now_ist=datetime(2026, 10, 16, 9, 19, tzinfo=IST))[1]["status"], "NO_COMPLETED_CANDLES")
        self.assertTrue(self._assess(first, now_ist=datetime(2026, 10, 16, 9, 20, tzinfo=IST))[1]["live_signal_allowed"])

    def test_closed_market_reference_across_close_overnight_weekend_and_holiday(self):
        close = [self._bar("2026-10-16T15:25:00+05:30")]
        clocks = [datetime(2026, 10, 16, 15, 30, tzinfo=IST), datetime(2026, 10, 16, 20, 0, tzinfo=IST),
                  datetime(2026, 10, 17, 14, 0, tzinfo=IST), datetime(2026, 10, 19, 9, 14, tzinfo=IST)]
        for now in clocks:
            _, reference = self._assess(close, now_ist=now, context="REFERENCE")
            self.assertTrue(reference["reference_usable"])
            self.assertFalse(reference["live_signal_allowed"])
            self.assertEqual(self._assess(close, now_ist=now)[1]["status"], "MARKET_CLOSED")
        now = datetime(2026, 10, 19, 12, 0, tzinfo=IST)
        self.assertTrue(self._assess(close, now_ist=now, context="REFERENCE", configured_holidays=["2026-10-19"])[1]["reference_usable"])
        self.assertEqual(self._assess([self._bar("2026-10-16T15:20:00+05:30")], now_ist=clocks[1], context="REFERENCE")[1]["status"], "STALE")

    def test_synthetic_and_unknown_provenance_cannot_gain_live_status(self):
        for change in (dict(is_simulated=True), dict(data_mode="SIMULATED"), dict(data_mode="UNKNOWN")):
            self.assertEqual(self._assess([self._bar(**change)])[1]["status"], "INVALID_PROVENANCE")
        for provider in ("unknown", "synthetic_fixture", "paper_sim"):
            self.assertEqual(self._assess(provider=provider)[1]["status"], "INVALID_PROVENANCE")

    def _read_adapter(self, provider, bars, interval=5):
        import io
        from datetime import timedelta
        self.cfg.active_broker = provider
        meta = dict(self.cfg.equity_watchlist[0])
        if provider == "angelone":
            adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
            adapter.jwt_token = "FIXTURE_JWT"
            payload = {"status": True, "data": [[b["timestamp"], b["open"], b["high"], b["low"], b["close"], b["volume"]] for b in bars]}
        elif provider == "dhan":
            adapter = DhanHQAdapter(self.cfg, clock=lambda: self.now)
            payload = {key: [b[key] for b in bars] for key in ("timestamp", "open", "high", "low", "close", "volume")}
        else:
            adapter = UpstoxV2Adapter(self.cfg, clock=lambda: self.now)
            # Exercise real one-minute source validation and five-minute aggregation.
            source = []
            for bar in bars:
                start = parse_ist_timestamp(bar["timestamp"])
                for i in range(5):
                    source.append(dict(bar, timestamp=(start+timedelta(minutes=i)).isoformat()))
            payload = {"status": "success", "data": {"candles": [[b["timestamp"], b["open"], b["high"], b["low"], b["close"], b["volume"]] for b in reversed(source)]}}
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(json.dumps(payload).encode())):
            try:
                result = adapter.get_intraday_candles(meta, interval_min=interval)
            except BrokerDataError:
                self.last_adapter = adapter
                raise
        self.last_adapter = adapter
        return result

    def test_all_supported_live_adapters_enforce_freshness_without_optional_override(self):
        from brokers import CandleFreshnessError
        for provider in ("angelone", "dhan", "upstox"):
            with self.subTest(provider=provider):
                self.assertEqual(len(self._read_adapter(provider, [self._bar()])), 1)
                self.assertTrue(self.last_adapter.last_candle_freshness["live_signal_allowed"])
                with self.assertRaises(CandleFreshnessError) as caught:
                    self._read_adapter(provider, [self._bar("2026-10-16T10:15:00+05:30")])
                self.assertEqual(caught.exception.freshness["status"], "STALE")

    def test_all_live_adapters_reject_future_and_duplicate_wire_candles(self):
        from brokers import CandleFreshnessError
        for provider in ("angelone", "dhan", "upstox"):
            for rows in ([self._bar("2026-10-16T10:40:00+05:30")], [self._bar(), self._bar()]):
                with self.subTest(provider=provider, rows=len(rows)), self.assertRaises(CandleFreshnessError):
                    self._read_adapter(provider, rows)

    def test_dhan_epoch_wire_timestamps_and_upstox_order_are_explicit(self):
        epoch = parse_ist_timestamp("2026-10-16T10:30:00+05:30").timestamp()
        self.assertEqual(self._read_adapter("dhan", [self._bar(epoch)])[0]["timestamp"], "2026-10-16 10:30:00")
        from brokers import CandleFreshnessError
        for provider in ("angelone", "dhan"):
            with self.assertRaises(CandleFreshnessError):
                self._read_adapter(provider, [self._bar("2026-10-16 10:30:00")])

    def test_closed_market_adapter_reads_are_reference_only(self):
        self.now = datetime(2026, 10, 17, 12, 0, tzinfo=IST)
        for provider in ("angelone", "dhan", "upstox"):
            self._read_adapter(provider, [self._bar("2026-10-16T15:25:00+05:30")])
            self.assertTrue(self.last_adapter.last_candle_freshness["reference_usable"])
            self.assertFalse(self.last_adapter.last_candle_freshness["live_signal_allowed"])

    def test_multi_broker_boundary_validates_even_if_adapter_reader_is_replaced(self):
        from brokers import CandleFreshnessError
        scanner = MultiBrokerScanner(self.cfg, clock=lambda: self.now)
        adapter = scanner.get_active_adapter()
        with patch.object(adapter, "get_intraday_candles", return_value=[self._bar("2026-10-16T10:15:00+05:30")]):
            with self.assertRaises(CandleFreshnessError):
                scanner.fetch_candles(self.cfg.equity_watchlist[0], interval_min=5)

    def test_invalid_live_batch_cannot_evaluate_persist_or_alert(self):
        from brokers import CandleFreshnessError
        engine = self._live_engine([self._bar("2026-10-16T10:15:00+05:30")])
        with patch("scanner_engine.evaluate_order_block_fvg") as evaluator, patch.object(engine.telegram, "send_signal") as alerts:
            with self.assertRaises(CandleFreshnessError):
                engine.run_single_scan()
        evaluator.assert_not_called()
        alerts.assert_not_called()
        self.assertEqual(self.store.query_signals()["total_count"], 0)
        self.assertEqual(self.store.query_scan_runs()["items"][0]["status"], "FAILED")

    def test_manual_api_and_scheduled_scan_paths_share_freshness_rejection(self):
        from server import DashboardRequestHandler
        engine = self._live_engine([self._bar("2026-10-16T10:15:00+05:30")])
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = engine
        code, payload = handler._handle_scan()
        self.assertEqual(code, 502)
        self.assertEqual(payload["freshness"]["status"], "STALE")
        scheduled = MarketScanScheduler(engine, clock=lambda: self.now).run_scheduled_cycle()
        self.assertEqual(scheduled["freshness"]["status"], "STALE")
        self.assertEqual(self.store.query_signals()["total_count"], 0)

    def test_get_and_post_scan_aliases_enforce_the_same_policy(self):
        from server import DashboardRequestHandler
        engine = self._live_engine([self._bar("2026-10-16T10:15:00+05:30")])
        for method in ("do_GET", "do_POST"):
            for route in ("/api/scan", "/api/v1/scan"):
                handler = object.__new__(DashboardRequestHandler)
                handler.engine = engine
                handler.path = route
                handler._ensure_initialized = MagicMock()
                handler._send_json = MagicMock()
                getattr(handler, method)()
                code, payload = handler._send_json.call_args.args
                self.assertEqual(code, 502)
                self.assertEqual(payload["freshness"]["status"], "STALE")
        self.assertEqual(self.store.query_signals()["total_count"], 0)

    def test_market_closed_manual_api_and_scheduler_skip_before_fetching(self):
        from server import DashboardRequestHandler
        self.now = datetime(2026, 10, 16, 15, 30, tzinfo=IST)
        engine = self._live_engine()
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = engine
        code, payload = handler._handle_scan()
        self.assertEqual(code, 200)
        self.assertEqual(payload["scan_status"], "SKIPPED_OUTSIDE_SESSION")
        self.assertEqual(MarketScanScheduler(engine).run_scheduled_cycle()["scan_status"], "SKIPPED_OUTSIDE_SESSION")
        engine.broker.fetch_candles.assert_not_called()

    def test_per_instrument_failure_does_not_mark_unrequested_peers_fresh(self):
        from brokers import CandleFreshnessError
        engine = self._live_engine()
        engine.broker.fetch_candles.side_effect = lambda meta, **k: [self._bar() if meta["symbol"] == "NIFTY" else self._bar("2026-10-16T10:15:00+05:30")]
        with self.assertRaises(CandleFreshnessError):
            engine.run_single_scan()
        status = engine.get_broker_status()["candle_freshness"]
        self.assertFalse(status["live_signal_allowed"])
        self.assertTrue(status["instruments"]["NIFTY"]["is_fresh"])
        self.assertEqual(status["instruments"]["BANKNIFTY"]["status"], "STALE")
        self.assertEqual(status["instruments"]["RELIANCE"]["status"], "NOT_CHECKED")

    def test_health_rechecks_age_and_provider_scope_without_network_calls(self):
        from datetime import timedelta
        engine = self._live_engine()
        result = engine.run_single_scan()
        self.assertGreater(result["total_signals"], 0)
        self.assertTrue(engine.get_broker_status()["live_signals_allowed"])
        self.now += timedelta(minutes=12)
        self.assertFalse(engine.get_broker_status()["live_signals_allowed"])
        self.assertTrue(engine.get_broker_status()["connectivity_verified"])
        self.assertTrue(all(r["status"] == "STALE" for r in engine.get_broker_status()["candle_freshness"]["instruments"].values()))
        engine.config.active_broker = "upstox"
        self.assertTrue(all(r["status"] == "NOT_CHECKED" for r in engine.get_broker_status()["candle_freshness"]["instruments"].values()))
        engine.config.active_broker = "paper_sim"
        self.assertEqual(engine.get_broker_status()["candle_freshness"]["status"], "SIMULATED")
        self.assertFalse(engine.get_broker_status()["live_signals_allowed"])

    def test_a_slow_evaluator_cannot_persist_or_alert_after_data_expires(self):
        from datetime import timedelta
        from brokers import CandleFreshnessError
        engine = self._live_engine()
        original = evaluate_order_block_fvg
        def slow(*args, **kwargs):
            signal = original(*args, **kwargs)
            self.now += timedelta(minutes=12)
            return signal
        with patch("scanner_engine.evaluate_order_block_fvg", side_effect=slow), patch.object(engine.telegram, "send_signal") as alerts:
            with self.assertRaises(CandleFreshnessError):
                engine.run_single_scan()
        self.assertEqual(self.store.query_signals()["total_count"], 0)
        alerts.assert_not_called()
        self.assertEqual(engine.mitigated_order_blocks, set())

    def test_clock_is_sampled_after_fetch_before_live_evaluation(self):
        from datetime import timedelta
        engine = self._live_engine()
        rows = engine.broker.fetch_candles.side_effect({}, interval_min=5)
        def fetch(meta, **kwargs):
            if meta["symbol"] == "NIFTY":
                self.now += timedelta(seconds=10)
            return rows
        engine.broker.fetch_candles.side_effect = fetch
        captured = []
        def evaluate(**kwargs):
            captured.append(kwargs["now"])
            return None
        with patch("scanner_engine.evaluate_order_block_fvg", side_effect=evaluate):
            engine.run_single_scan()
        self.assertTrue(captured)
        self.assertTrue(all(stamp == self.now for stamp in captured))

    def test_current_readiness_status_cannot_bypass_stale_scanner_data(self):
        from brokers import CandleFreshnessError
        engine = self._live_engine([self._bar("2026-10-16T10:15:00+05:30")])
        with patch.object(engine, "get_broker_status", return_value={"connectivity_verified": True, "phase2c_accepted": True}):
            with self.assertRaises(CandleFreshnessError):
                engine.run_single_scan()

    def test_diagnostic_connection_success_does_not_hide_candle_freshness_failure(self):
        # Reuse the established fully mocked diagnostic producer, changing only candle time.
        case = TestIndianFOSignalBotPhase3B1B()
        case.setUp()
        self.addCleanup(case.doCleanups)
        def stale(payload):
            payload[3]["data"] = [["2026-10-16T09:15:00+05:30", 100, 102, 99, 101, 1000]]
        # Supply the existing fixture sequence through its controlled mutation hook.
        report = case._produce(mutate=stale)
        self.assertEqual(report["checks_list"][0]["status"], "PASS")
        self.assertFalse(report["live_candle_signal_allowed"])
        self.assertEqual(report["candle_freshness"]["status"], "STALE")
        self.assertFalse(report["live_acceptance"]["accepted"])

    def test_historical_replay_and_synthetic_scans_keep_their_existing_rules(self):
        # Historic timestamps stay under historical validation, not the raw live parser.
        old = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-13", data_mode="SIMULATED")
        from backtest_engine import DeterministicBacktestEngine, BacktestConfig
        result = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now).run_backtest(
            "strat_1_order_block", "RELIANCE", candles=old, provider="synthetic_fixture", data_mode="SIMULATED",
            backtest_config=BacktestConfig())
        self.assertEqual(result["execution_scope"], "SIMULATED_TEST")
        cfg = BotConfig(active_broker="paper_sim", database_url=":memory:", telegram_dry_run=True)
        engine = IntradayBotEngine(cfg, store=self.store, clock=lambda: self.now)
        self.addCleanup(engine.close)
        self.assertEqual(engine.run_single_scan()["candle_freshness"]["status"], "SIMULATED")
        self.assertFalse(engine.get_broker_status()["option_apex"]["live_verified"])

    def test_diagnostic_rechecks_candles_that_expire_during_other_checks(self):
        from datetime import timedelta
        import diagnostics
        case = TestIndianFOSignalBotPhase3B1B()
        case.setUp()
        self.addCleanup(case.doCleanups)
        original = diagnostics.evaluate_candle_freshness
        calls = []
        def advance(*args, **kwargs):
            report = original(*args, **kwargs)
            calls.append(report)
            if len(calls) == 1:
                case.now += timedelta(minutes=12)
            return report
        with patch("diagnostics.evaluate_candle_freshness", side_effect=advance):
            report = case._produce(mutate=lambda responses: None)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(calls[0]["is_fresh"])
        self.assertEqual(report["candle_freshness"]["status"], "STALE")
        self.assertFalse(report["live_candle_signal_allowed"])
        self.assertFalse(report["live_acceptance"]["accepted"])

    def test_invalid_freshness_configuration_fails_closed(self):
        from config import ConfigValidationError
        for name in ("live_candle_max_delay_seconds", "live_candle_future_skew_seconds"):
            for value in (True, -1, float("nan"), float("inf")):
                setattr(self.cfg, name, value)
                with self.assertRaises(ConfigValidationError):
                    self.cfg.validate()
            setattr(self.cfg, name, 0)
        self.cfg.validate()
        self.assertEqual(self.cfg.to_safe_dict()["live_candle_max_delay_seconds"], 0)


class TestHTTPErrorFixtureCleanup(unittest.TestCase):
    def test_503_fixture_closes_response_even_when_an_assertion_fails(self):
        import io
        import urllib.error

        original_error = urllib.error.HTTPError
        owner = self
        for fail_assertion in (False, True):
            with self.subTest(fail_assertion=fail_assertion):
                streams = []

                class TrackedHTTPError(original_error):
                    def __init__(self, *args, **kwargs):
                        stream = io.BytesIO()
                        kwargs["fp"] = stream
                        super().__init__(*args, **kwargs)
                        streams.append(stream)
                        owner.addCleanup(self.close)

                case = TestIndianFOSignalBotPhase2C(
                    "test_p2c_session_expiry_recovery_and_unavailable_endpoint_handling")
                case.setUp()
                assert_equal = case.assertEqual

                def check_equal(actual, expected, *args, **kwargs):
                    if fail_assertion and expected == "NETWORK_API_FAILURE":
                        raise AssertionError("injected assertion after HTTPError consumption")
                    return assert_equal(actual, expected, *args, **kwargs)

                case.assertEqual = check_equal
                with patch("urllib.error.HTTPError", TrackedHTTPError):
                    if fail_assertion:
                        with self.assertRaisesRegex(AssertionError, "injected assertion"):
                            case.test_p2c_session_expiry_recovery_and_unavailable_endpoint_handling()
                    else:
                        case.test_p2c_session_expiry_recovery_and_unavailable_endpoint_handling()
                self.assertEqual(len(streams), 1)
                self.assertTrue(streams[0].closed, "Fixture must close its response before test cleanup")


class TestInstrumentIdentity(unittest.TestCase):
    """Offline application references and synthetic masters; no operational broker acceptance."""

    def setUp(self):
        self.fixture = TestMarketDataFreshness()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.cfg, self.now, self.store = self.fixture.cfg, self.fixture.now, self.fixture.store

    def test_exact_index_mappings_and_swapped_tokens_all_providers(self):
        from brokers import validate_symbol_meta, BrokerIdentityError
        fields = dict(angelone="angel_token", dhan="dhan_security_id", upstox="upstox_key")
        for provider, field in fields.items():
            good = dict(self.cfg.fo_indices["NIFTY"], symbol="NIFTY")
            with self.subTest(provider=provider):
                self.assertEqual(validate_symbol_meta(good, provider)["symbol"], "NIFTY")
                with self.assertRaises(BrokerIdentityError) as caught:
                    validate_symbol_meta(dict(good, **{field: self.cfg.fo_indices["BANKNIFTY"][field]}), provider)
                self.assertEqual(caught.exception.rejection["reason_code"], "IDENTIFIER_MISMATCH")

    def test_runtime_configuration_cannot_redefine_reference(self):
        from brokers import validate_symbol_meta, BrokerIdentityError
        self.cfg.fo_indices["NIFTY"]["angel_token"] = "99926009"
        with self.assertRaises(BrokerIdentityError):
            validate_symbol_meta(dict(self.cfg.fo_indices["NIFTY"], symbol="NIFTY"), "angelone")

    def test_exchange_segment_and_classification_are_consistent(self):
        from brokers import validate_symbol_meta, BrokerIdentityError
        base = dict(self.cfg.fo_indices["NIFTY"], symbol="NIFTY")
        for change in (dict(exchange="BSE"), dict(exchange="NFO"), dict(segment="NSE_EQUITY_INTRADAY"),
                       dict(exchange_segment="NSE_EQ"), dict(instrument="EQUITY"), dict(is_index=False)):
            with self.subTest(change=change), self.assertRaises(BrokerIdentityError):
                validate_symbol_meta(dict(base, **change), "dhan")

    def test_aliases_resolve_to_one_identity(self):
        from brokers import validate_symbol_meta
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        for alias in ("NIFTY", "nifty 50", " NIFTY 50 "):
            meta = dict(self.cfg.fo_indices["NIFTY"], symbol=alias)
            self.assertEqual(validate_symbol_meta(meta, "angelone")["symbol"], "NIFTY")
            self.assertEqual(adapter.resolve_instrument(alias)["angel_token"], "99926000")
        self.assertEqual(adapter.resolve_instrument("RELIANCE-EQ")["symbol"], "RELIANCE")

    def test_unknown_identifiers_and_provider_leakage_fail_closed(self):
        from brokers import validate_symbol_meta, BrokerIdentityError
        for meta, provider in ((dict(symbol="UNKNOWN", angel_token="1234"), "angelone"),
                               (dict(symbol="NIFTY", angel_token="13"), "angelone"),
                               (dict(symbol="NIFTY", dhan_security_id="99926000"), "dhan"),
                               (dict(symbol="NIFTY", angel_token="99926000"), "upstox")):
            with self.subTest(meta=meta, provider=provider), self.assertRaises(BrokerIdentityError):
                validate_symbol_meta(meta, provider)

    def test_equity_mapping_exchange_and_lot_validation(self):
        from brokers import validate_symbol_meta, BrokerIdentityError
        for provider, field in (("angelone", "angel_token"), ("dhan", "dhan_id"), ("upstox", "upstox_key")):
            good = self.cfg.equity_watchlist[0]
            self.assertEqual(validate_symbol_meta(good, provider)["symbol"], "RELIANCE")
            for change in ({field: self.cfg.equity_watchlist[1][field]}, dict(exchange="BSE"),
                           dict(lot_size=1.5), dict(multiplier=2), dict(lot_size=True)):
                with self.subTest(provider=provider, change=change), self.assertRaises(BrokerIdentityError):
                    validate_symbol_meta(dict(good, **change), provider)

    def test_quote_response_cannot_relabel_token_or_substitute_instrument(self):
        from brokers import BrokerIdentityError
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        for item in (dict(exchange="NSE", symbolToken="2885", tradingSymbol="HDFCBANK-EQ", ltp=100),
                     dict(exchange="NSE", symbolToken="1333", tradingSymbol="HDFCBANK-EQ", ltp=100),
                     dict(exchange="BSE", symbolToken="2885", tradingSymbol="RELIANCE", ltp=100)):
            payload = dict(data=dict(fetched=[item], unfetched=[]))
            with patch.object(adapter, "_request_json", return_value=payload), self.assertRaises(BrokerIdentityError):
                adapter.get_quote("RELIANCE", mode="LTP")

    def test_quote_unknown_request_rejected_before_transport_and_duplicates_rejected(self):
        from brokers import BrokerIdentityError
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        with patch.object(adapter, "_request_json") as transport, self.assertRaises(BrokerIdentityError):
            adapter.get_quotes({"NSE": ["1234567"]}, mode="LTP")
        transport.assert_not_called()
        item = dict(exchange="NSE", symbolToken="2885", tradingSymbol="RELIANCE-EQ", ltp=100)
        with patch.object(adapter, "_request_json", return_value=dict(data=dict(fetched=[item, item]))), self.assertRaises(BrokerIdentityError):
            adapter.get_quote("RELIANCE", mode="LTP")

    def test_candle_response_echoes_checked_all_live_adapters(self):
        import io
        from brokers import BrokerIdentityError
        bar = self.fixture._bar()
        for provider, adapter, payload in (
            ("angelone", AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now),
             dict(status=True, symbol="HDFCBANK", data=[[bar[k] for k in ("timestamp", "open", "high", "low", "close", "volume")]])),
            ("dhan", DhanHQAdapter(self.cfg, clock=lambda: self.now),
             dict({k: [bar[k]] for k in ("timestamp", "open", "high", "low", "close", "volume")}, symbol="HDFCBANK")),
            ("upstox", UpstoxV2Adapter(self.cfg, clock=lambda: self.now),
             dict(status="success", symbol="HDFCBANK", data=dict(candles=[[bar[k] for k in ("timestamp", "open", "high", "low", "close", "volume")]])))):
            if provider == "angelone":
                adapter.jwt_token = "OFFLINE_FIXTURE"
            with self.subTest(provider=provider), patch("urllib.request.urlopen", side_effect=lambda *a, **kw: io.BytesIO(json.dumps(payload).encode())), self.assertRaises(BrokerIdentityError):
                adapter.get_intraday_candles(self.cfg.equity_watchlist[0], interval_min=1)

    def test_bare_candles_are_explicitly_request_bound_and_freshness_still_required(self):
        from brokers import CandleFreshnessError
        for provider in ("angelone", "dhan", "upstox"):
            with self.subTest(provider=provider):
                bars = self.fixture._read_adapter(provider, [self.fixture._bar()])
                self.assertEqual(bars[0]["instrument_identity"]["response_binding"], "REQUEST_BOUND_NO_ECHO")
                with self.assertRaises(CandleFreshnessError):
                    self.fixture._read_adapter(provider, [self.fixture._bar("2026-10-16T10:15:00+05:30")])

    def test_engine_identity_failure_blocks_evaluation_storage_and_dispatch(self):
        from brokers import BrokerIdentityError
        engine = self.fixture._live_engine([self.fixture._bar(symbol="HDFCBANK")])
        with patch("scanner_engine.evaluate_order_block_fvg") as evaluator, patch.object(engine.telegram, "send_signal") as alerts:
            with self.assertRaises(BrokerIdentityError):
                engine.run_single_scan()
        evaluator.assert_not_called()
        alerts.assert_not_called()
        self.assertEqual(self.store.query_signals()["total_count"], 0)
        self.assertEqual(engine.last_scan_summary["rejection"]["reason_code"], "RESPONSE_IDENTITY_MISMATCH")

    def test_multibroker_boundary_checks_replaced_reader_identity(self):
        from brokers import BrokerIdentityError
        scanner = MultiBrokerScanner(self.cfg, clock=lambda: self.now)
        adapter = scanner.get_active_adapter()
        with patch.object(adapter, "get_intraday_candles", return_value=[self.fixture._bar(securityId="1333")]), self.assertRaises(BrokerIdentityError):
            scanner.fetch_candles(self.cfg.equity_watchlist[0])

    def test_master_rejects_ambiguous_and_conflicting_cash_records(self):
        from brokers import BrokerDataError
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        records = TestIndianFOSignalBotPhase2B._build_scrip_master_fixture()
        adapter.load_scrip_master(records)
        old = adapter.resolve_instrument("RELIANCE")
        for change in (dict(token="1333"), dict(name="HDFCBANK"), dict(symbol="HDFCBANK-EQ")):
            bad = [dict(r) for r in records]
            bad[2].update(change)
            with self.subTest(change=change), self.assertRaises(BrokerDataError):
                adapter.load_scrip_master(bad)
            self.assertEqual(adapter.resolve_instrument("RELIANCE"), old)
        unknown = dict(token="1234567", name="FIXTURE", symbol="FIXTURE-EQ", exch_seg="NSE", lotsize="1")
        with self.assertRaises(BrokerDataError):
            adapter.load_scrip_master([unknown, dict(unknown, token="7654321")])

    def test_contract_fields_lots_and_multiplier_reject_conflicts(self):
        from brokers import BrokerDataError
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        for change in (dict(name="BANKNIFTY"), dict(expiry="29OCT2026"), dict(strike="2490000"),
                       dict(option_type="PE"), dict(lotsize="1.5"), dict(lotsize=""), dict(multiplier=2)):
            records = TestIndianFOSignalBotPhase2B._build_scrip_master_fixture()
            records[3].update(change)
            with self.subTest(change=change), self.assertRaises(BrokerDataError):
                adapter.load_scrip_master(records)

    def test_exact_option_contract_roundtrip_and_expired_rejected(self):
        from instrument_identity import option_contract, IdentityValidationError
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        adapter.load_scrip_master(TestIndianFOSignalBotPhase2B._build_scrip_master_fixture())
        contract = adapter._scrip_master_options[0]["instrument_identity"]
        self.assertEqual(option_contract(contract, "NIFTY", "2026-10-22", 24750, "CE", "angelone", self.now), contract)
        for changes in (dict(identifier=""), dict(lot_size=0), dict(multiplier=0), dict(underlying="BANKNIFTY"), dict(option_type="PE")):
            with self.subTest(changes=changes), self.assertRaises(IdentityValidationError):
                option_contract(dict(contract, **changes), "NIFTY", "2026-10-22", 24750, "CE", "angelone", self.now)
        with self.assertRaises(IdentityValidationError):
            option_contract(contract, "NIFTY", "2026-10-22", 24750, "CE", "angelone", "2026-10-23")

    def test_historical_archive_required_dated_and_unambiguous(self):
        from instrument_identity import dated_identity, IdentityValidationError, digest
        archive = offline_equity_master_fixture()
        args = ("RELIANCE", "angelone", "2885", "NSE", "EQ", "2026-10-15", "2026-10-15")
        good = dated_identity(archive, *args)
        self.assertEqual(good["historical_validity"], "ARCHIVE_CONSISTENCY_CHECKED")
        for bad in (None, {}, dict(archive, sha256="wrong"),
                    dict(archive, records=archive["records"]*2, sha256=digest(archive["records"]*2))):
            with self.subTest(bad=bad), self.assertRaises(IdentityValidationError):
                dated_identity(bad, *args)
        with self.assertRaises(IdentityValidationError):
            dated_identity(archive, *args[:-2], "2026-11-01", "2026-11-02")

    def test_historical_future_requires_contract_id_expiry_and_exact_lot(self):
        from instrument_identity import dated_identity, IdentityValidationError, digest
        record = dict(provider="angelone", symbol="NIFTY", underlying="NIFTY", identifier="OFFLINE_FUTURE_ID",
                      exchange="NFO", instrument_type="FUTIDX", expiry="2026-10-29", lot_size=75,
                      multiplier=1, valid_from="2026-10-01", valid_to="2026-10-29")
        args = ("NIFTY", "angelone", "OFFLINE_FUTURE_ID", "NFO", "FUTIDX", "2026-10-15", "2026-10-15", 75)
        for change in ({}, dict(identifier="99926000"), dict(expiry="2026-10-14"), dict(lot_size=1.5), dict(multiplier=2), dict(underlying="BANKNIFTY")):
            r = dict(record, **change)
            archive = dict(source="ARCHIVED_PROVIDER_MASTER", source_reference="OFFLINE_FIXTURE", records=[r], sha256=digest([r]))
            if not change:
                self.assertEqual(dated_identity(archive, *args)["identifier"], record["identifier"])
            else:
                with self.subTest(change=change), self.assertRaises(IdentityValidationError):
                    dated_identity(archive, *args)

    def test_historical_import_does_not_overwrite_mismatched_identity(self):
        from historical_data import validate_and_prepare_historical_dataset, HistoricalDataValidationError
        rows = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        for change in (dict(symbol="HDFCBANK"), dict(instrument_token="1333"), dict(provider="dhan"), dict(exchange="BSE")):
            with self.subTest(change=change), self.assertRaises(HistoricalDataValidationError):
                validate_and_prepare_historical_dataset([dict(r, **change) for r in rows], symbol="RELIANCE",
                    segment="NSE_EQUITY_INTRADAY", exchange="NSE", provider="angelone", instrument_token="2885",
                    data_mode="LIVE", reference_time_ist=self.now)

    def test_live_research_without_archive_cannot_replay(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        rows = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now)
        with patch.object(engine, "_invoke_strategy_evaluator") as evaluator:
            with self.assertRaises(BacktestEligibilityError) as caught:
                engine.run_backtest("strat_1_order_block", "RELIANCE", candles=rows, provider="angelone", data_mode="LIVE",
                                     backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH"))
        evaluator.assert_not_called()
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_IDENTITY_UNVERIFIED")

    def test_signal_identity_persists_and_conflicts_cannot_be_saved(self):
        from instrument_identity import spot_identity
        from storage import PersistenceValidationError
        sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.now)
        sig = evaluate_order_block_fvg("RELIANCE", sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull"), now=self.now)
        self.assertIsNotNone(sig)
        sig.provider, sig.data_mode, sig.is_simulated, sig.state_context = "dhan", "LIVE", False, "SCANNER"
        with self.assertRaises(PersistenceValidationError):
            self.store.save_signal(sig, broker="Offline fixture")
        sig.instrument_identity = spot_identity(self.cfg.equity_watchlist[0], "dhan")
        self.assertTrue(self.store.save_signal(sig, broker="Offline fixture")[0])
        self.assertEqual(self.store.query_signals()["items"][0]["instrument_identity"], sig.instrument_identity)
        sig.instrument_identity = dict(sig.instrument_identity, identifier="1333")
        with self.assertRaises(PersistenceValidationError):
            self.store.save_signal(sig, broker="Offline fixture")
        self.assertEqual(self.store.query_signals()["total_count"], 1)

    def test_live_index_spot_cannot_emit_futures_proposal(self):
        engine = self.fixture._live_engine()
        with patch("scanner_engine.evaluate_order_block_fvg", return_value=None) as evaluator:
            result = engine.run_single_scan()
        self.assertTrue(any(e.get("reason_code") == "UNSUPPORTED_CONTRACT" for e in result["instrument_errors"]))
        self.assertTrue(all(c.kwargs.get("segment") != "NSE_FO_INDEX" for c in evaluator.call_args_list))

    def test_chain_echo_mismatch_rejected_and_missing_contract_not_execution_ready(self):
        from instrument_identity import check_chain_metadata, option_contract, IdentityValidationError
        for payload in (dict(underlying="BANKNIFTY"), dict(expiry="2026-10-29"), dict(underlying_key="WRONG"), dict(option_type="PE")):
            with self.subTest(payload=payload), self.assertRaises(IdentityValidationError):
                check_chain_metadata(payload, "NIFTY", "2026-10-22", "upstox", "NSE_INDEX|Nifty 50", 24800, "CE")
        with self.assertRaises(IdentityValidationError):
            option_contract({}, "NIFTY", "2026-10-22", 24800, "CE", "dhan", self.now)


    def test_angel_master_added_equity_is_bound_and_serialized_without_token_collision(self):
        from brokers import BrokerIdentityError
        adapter = AngelOneSmartAPIAdapter(self.cfg, clock=lambda: self.now)
        row = dict(token="1234567", name="FIXTURE", symbol="FIXTURE-EQ", exch_seg="NSE", instrumenttype="EQ", lotsize="1")
        adapter.load_scrip_master([row])
        identity = adapter.resolve_instrument("FIXTURE")["instrument_identity"]
        self.assertEqual(identity["source"], "LOADED_ANGEL_MASTER")
        from instrument_identity import validate_signal_identity
        validate_signal_identity(dict(provider="angelone", data_mode="LIVE", state_context="SCANNER",
            symbol="FIXTURE", segment="NSE_EQUITY_INTRADAY", instrument_identity=identity,
            instrument_label="FIXTURE EQ", position_type="LONG_EQUITY_INTRADAY"))
        with self.assertRaises(BrokerIdentityError):
            adapter.load_scrip_master([dict(row, token="1333")])

    def test_binding_preserves_echo_evidence_and_does_not_mutate_input(self):
        from instrument_identity import spot_identity, bind_candles, IdentityValidationError
        identity = spot_identity(self.cfg.equity_watchlist[0], "dhan")
        raw = [self.fixture._bar(symbol="RELIANCE")]
        bars = bind_candles(raw, identity)
        self.assertNotIn("instrument_identity", raw[0])
        self.assertEqual(bind_candles(bars, identity)[0]["instrument_identity"]["response_binding"], "ECHO_CHECKED")
        bars[0]["instrument_identity"]["identifier"] = "1333"
        with self.assertRaises(IdentityValidationError):
            bind_candles(bars, identity)

    def test_angel_option_signal_uses_exact_master_contract_label_and_identity(self):
        from copy import deepcopy
        self.cfg.active_broker = "angelone"
        self.cfg.account_capital_inr = 500000
        engine = self.fixture._live_engine()
        adapter = engine.broker.get_active_adapter()
        adapter.load_scrip_master(TestIndianFOSignalBotPhase2B._build_scrip_master_fixture())
        chain = dict(index="NIFTY", expiry="2026-10-22", atm_strike=24750, spot=24760,
                     data_mode="LIVE", is_simulated=False, pcr=1, total_ce_oi=100000, total_pe_oi=100000,
                     strikes=[dict(strike=24750, ce_oi_change=0, pe_oi_change=0)])
        for side in ("CE", "PE"):
            row = chain["strikes"][0]
            row[side.lower()+"_contract"] = next(c["instrument_identity"] for c in adapter._scrip_master_options
                if c["index_symbol"] == "NIFTY" and c["strike"] == 24750 and c["option_type"] == side)
            row.update({side.lower()+"_oi": 100000, side.lower()+"_ltp": 100})
        sim = SimulatedNSEAdapter(seed=42, clock=lambda: self.now)
        signal = evaluate_order_block_fvg("RELIANCE", sim.get_intraday_candles({"symbol": "RELIANCE"}, pattern="order_block_bull"), now=self.now)
        signal = TradeSignal(**dict(signal.to_dict(), symbol="NIFTY", segment="NSE_FO_INDEX",
            strategy_id="strat_3_option_apex_oi", direction="BULLISH (BUY CE)", position_type="LONG_CALL_OPTION",
            entry_price=100, stop_loss=90, target_1=120, target_2=130, instrument_label="NIFTY 24750 CE"))
        with patch.object(engine.broker, "fetch_option_chain", side_effect=lambda sym: deepcopy(chain) if sym == "NIFTY" else None), \
                patch("scanner_engine.evaluate_option_apex_oi_shift", return_value=signal), \
                patch.object(engine.telegram, "send_signal", return_value={"dry_run": True}):
            result = engine.run_single_scan()
        options = [s for s in result["signals"] if s["strategy_id"] == "strat_3_option_apex_oi"]
        self.assertEqual(result["persistence_status"], "OK", result["persistence_error"])
        self.assertEqual(len(options), 1, result["instrument_errors"])
        contract = chain["strikes"][0]["ce_contract"]
        self.assertEqual(options[0]["instrument_label"], contract["symbol"])
        self.assertEqual(options[0]["instrument_identity"], contract)
        stored = self.store.query_signals(strategy_id="strat_3_option_apex_oi")["items"][0]
        self.assertEqual(stored["instrument_identity"], contract)

    def test_dhan_chain_cannot_emit_option_signal_without_master_resolver(self):
        engine = self.fixture._live_engine()
        chain = dict(expiry="2026-10-22", data_mode="LIVE", is_simulated=False, spot=24760, atm_strike=24750,
                     pcr=1, total_ce_oi=100000, total_pe_oi=100000,
                     strikes=[dict(strike=24750, ce_ltp=100, pe_ltp=100, ce_oi=100000, pe_oi=100000, ce_oi_change=0, pe_oi_change=0)])
        with patch.object(engine.broker, "fetch_option_chain", side_effect=lambda sym: dict(chain, index=sym)), \
                patch("scanner_engine.evaluate_option_apex_oi_shift") as evaluator:
            result = engine.run_single_scan()
        evaluator.assert_not_called()
        self.assertEqual(self.store.query_signals(strategy_id="strat_3_option_apex_oi")["total_count"], 0)
        self.assertTrue(any(e.get("reason_code") == "UNSUPPORTED_CONTRACT" and e.get("strategy") == "strat_3_option_apex_oi"
                            for e in result["instrument_errors"]))

    def test_duplicate_and_noncanonical_configurations_cannot_evaluate(self):
        from brokers import BrokerIdentityError
        for alias in ("RELIANCE", "RELIANCE-EQ"):
            with self.subTest(alias=alias):
                self.cfg.equity_watchlist = [dict(self.cfg.equity_watchlist[0]), dict(self.cfg.equity_watchlist[0], symbol=alias)]
                engine = self.fixture._live_engine()
                with patch("scanner_engine.evaluate_order_block_fvg") as evaluator, self.assertRaises(BrokerIdentityError):
                    engine.run_single_scan()
                evaluator.assert_not_called()

    def test_current_index_identifier_cannot_be_archived_as_cash_equity(self):
        from instrument_identity import dated_identity, IdentityValidationError
        archive = offline_equity_master_fixture(symbol="NIFTY", token="99926000")
        with self.assertRaises(IdentityValidationError):
            dated_identity(archive, "NIFTY", "angelone", "99926000", "NSE", "EQ", "2026-10-15", "2026-10-15")


    def test_historical_master_selects_exact_identifier_among_other_contracts(self):
        from instrument_identity import dated_identity, digest
        archive = offline_equity_master_fixture()
        records = archive["records"] + [dict(archive["records"][0], identifier="OFFLINE_OTHER_PERIOD_TOKEN")]
        archive.update(records=records, sha256=digest(records))
        result = dated_identity(archive, "RELIANCE", "angelone", "2885", "NSE", "EQ", "2026-10-15", "2026-10-15")
        self.assertEqual(result["identifier"], "2885")

    def test_historical_cash_lot_and_segment_cannot_be_silently_ignored(self):
        from instrument_identity import dated_identity, digest, IdentityValidationError
        for change in (dict(lot_size=1.5), dict(lot_size=2), dict(segment="NSE_FO_INDEX")):
            archive = offline_equity_master_fixture()
            archive["records"][0].update(change)
            archive["sha256"] = digest(archive["records"])
            with self.subTest(change=change), self.assertRaises(IdentityValidationError):
                dated_identity(archive, "RELIANCE", "angelone", "2885", "NSE", "EQ", "2026-10-15", "2026-10-15")


    def test_signal_scope_case_cannot_bypass_live_identity_requirement(self):
        from instrument_identity import validate_signal_identity, IdentityValidationError
        for mode, context in (("LIVE", "SCANNER"), ("live", "scanner"), (" LIVE ", " SCANNER ")):
            with self.subTest(mode=mode), self.assertRaises(IdentityValidationError):
                validate_signal_identity(dict(provider="angelone", data_mode=mode, state_context=context,
                                               symbol="RELIANCE", segment="NSE_EQUITY_INTRADAY"))


    def test_simulation_retains_required_symbol_and_explicit_custom_base_price(self):
        from brokers import validate_symbol_meta, BrokerDataError
        for missing in (None, "", " ", 123):
            with self.subTest(symbol=missing), self.assertRaises(BrokerDataError):
                validate_symbol_meta(dict(symbol=missing, base_price=100), "paper_sim")
        self.assertEqual(validate_symbol_meta(dict(symbol="CUSTOM_FIXTURE", base_price=100), "paper_sim")["symbol"], "CUSTOM_FIXTURE")


class TestInstrumentArchives(unittest.TestCase):
    """Local source declarations and synthetic fixtures, never real publisher verification."""

    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        guard = patch("urllib.request.urlopen", side_effect=AssertionError("External services forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    @staticmethod
    def _payload(provider="angelone", **record_changes):
        from instrument_archive import SCHEMA
        row = dict(provider=provider, symbol="RELIANCE", identifier="2885", exchange="NSE",
                   instrument_type="EQ", multiplier=1, valid_from="2026-10-01", valid_to="2026-10-31")
        row.update(record_changes)
        return dict(schema_version=SCHEMA, provider=provider, records=[row])

    def _ingest(self, payload=None, *, raw=None, provider="angelone", filename="fixture.json", **metadata):
        return self.store.ingest_instrument_master_bytes(
            json.dumps(self._payload() if payload is None else payload).encode() if raw is None else raw,
            provider, filename, "OFFLINE_SYNTHETIC_SOURCE_DECLARATIONS", **metadata)

    def _resolve(self, **changes):
        args = dict(provider="angelone", symbol="RELIANCE", identifier="2885", exchange="NSE",
                    instrument_type="EQ", first_date="2026-10-15", last_date="2026-10-15")
        args.update(changes)
        view = self.store.inspect_archived_instrument_identity(**args)
        self.assertFalse(view["live_historical_eligible"])
        return view

    def test_valid_ingestion_original_bytes_and_deterministic_normalization(self):
        import hashlib
        payload = self._payload()
        payload["records"].append(dict(payload["records"][0], symbol="HDFCBANK", identifier="1333"))
        raw = json.dumps(payload, indent=4).encode()
        archive = self._ingest(raw=raw)
        other = self._ingest(dict(payload, records=list(reversed(payload["records"]))))
        self.assertEqual(archive["status"], "ELIGIBLE_LOCAL_RESEARCH")
        self.assertEqual(archive["normalized_sha256"], other["normalized_sha256"])
        self.assertEqual(archive["metadata"]["original_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)["original_bytes"], raw)
        self.assertEqual(archive["record_count"], 2)

    def test_invalid_empty_truncated_and_unsupported_files_are_retained_rejected(self):
        for raw, name in ((b"", "empty.json"), (b'{"records":', "truncated.json"), (b'[]', "empty-list.json"),
                          (b'{}', "bad-schema.json"), (b'not-json', "bad.csv"), (b'\xff', "bad-utf8.json")):
            with self.subTest(name=name):
                archive = self._ingest(raw=raw, filename=name)
                self.assertEqual(archive["status"], "REJECTED")
                self.assertEqual(archive["record_count"], 0)
                self.assertEqual(self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)["original_bytes"], raw)
        self.assertEqual(len(self.store.list_instrument_master_archives()), 6)

    def test_missing_required_fields_reject_entire_archive(self):
        for field in ("symbol", "identifier", "exchange", "instrument_type", "multiplier"):
            payload = self._payload()
            del payload["records"][0][field]
            with self.subTest(field=field):
                self.assertEqual(self._ingest(payload)["status"], "REJECTED")

    def test_duplicate_json_keys_and_nonfinite_values_rejected(self):
        for raw in (b'{"provider":"angelone","provider":"dhan"}',
                    json.dumps(self._payload(multiplier=float("nan"))).encode()):
            self.assertEqual(self._ingest(raw=raw)["status"], "REJECTED")

    def test_whitespace_change_changes_original_digest_but_not_normalized_digest(self):
        raw = json.dumps(self._payload()).encode()
        first, second = self._ingest(raw=raw), self._ingest(raw=raw+b"\n")
        self.assertNotEqual(first["metadata"]["original_sha256"], second["metadata"]["original_sha256"])
        self.assertNotEqual(first["archive_id"], second["archive_id"])
        self.assertEqual(first["normalized_sha256"], second["normalized_sha256"])
        self.assertEqual(self._resolve()["historical_validity"], "SOURCE_DECLARED_ARCHIVE_COVERAGE")

    def test_authenticity_claim_and_official_url_do_not_establish_authenticity(self):
        payload = dict(self._payload(), publisher_authenticity="VERIFIED", signature="invented-fixture-claim")
        archive = self._ingest(payload, source_url="https://example.invalid/claimed-provider-master.json")
        self.assertEqual(archive["metadata"]["publisher_authenticity"], "NOT_ESTABLISHED")
        self.assertIn("not been independently established", archive["metadata"]["provenance_limitation"])
        self.assertEqual(self._resolve()["archive_provenance"]["publisher_authenticity"], "NOT_ESTABLISHED")

    def test_capture_publication_ingestion_and_validity_are_separate(self):
        with patch("instrument_archive.local_ingestion_timestamp", return_value="2026-11-02T00:00:00Z"):
            archive = self._ingest(captured_at="2026-11-01T10:00:00+05:30",
                                   publisher_published_at="2026-10-31T20:00:00Z")
        self.assertEqual(archive["metadata"]["captured_at"], "2026-11-01T10:00:00+05:30")
        self.assertEqual(archive["ingested_at"], "2026-11-02T00:00:00+00:00")
        self.assertEqual(self._resolve()["valid_from"], "2026-10-01")
        from instrument_identity import IdentityValidationError
        with self.assertRaises(IdentityValidationError):
            self._resolve(first_date="2026-11-01", last_date="2026-11-01")

    def test_capture_date_does_not_fill_missing_effective_dates(self):
        archive = self._ingest(self._payload(valid_from=None, valid_to=None), captured_at="2026-10-15T12:00:00+05:30")
        self.assertEqual(archive["status"], "INCOMPLETE")
        self.assertIsNone(archive["records"][0]["valid_from"])
        from instrument_identity import IdentityValidationError
        with self.assertRaises(IdentityValidationError):
            self._resolve()

    def test_partial_reversed_and_expired_effective_intervals_rejected(self):
        for changes in (dict(valid_to=None), dict(valid_from="2026-11-01"), dict(valid_from="bad")):
            with self.subTest(changes=changes):
                self.assertEqual(self._ingest(self._payload(**changes))["status"], "REJECTED")

    def test_naive_capture_and_publication_timestamps_rejected(self):
        from instrument_identity import IdentityValidationError
        for fields in (dict(captured_at="2026-10-15T10:00:00"), dict(publisher_published_at="yesterday")):
            with self.subTest(fields=fields), self.assertRaises(IdentityValidationError):
                self._ingest(**fields)

    def test_duplicate_tokens_and_conflicting_symbols_are_rejected(self):
        for change in ({}, dict(symbol="HDFCBANK"), dict(identifier="1333")):
            payload = self._payload()
            payload["records"].append(dict(payload["records"][0], **change))
            with self.subTest(change=change):
                self.assertEqual(self._ingest(payload)["status"], "REJECTED")

    def test_exchange_segment_type_and_lot_conflicts_rejected(self):
        for changes in (dict(exchange="BSE"), dict(segment="NSE_FO_INDEX"), dict(instrument_type="INDEX_SPOT"),
                        dict(lot_size=1.5), dict(lot_size=True), dict(multiplier=2), dict(expiry="2026-10-29")):
            with self.subTest(changes=changes):
                self.assertEqual(self._ingest(self._payload(**changes))["status"], "REJECTED")

    def test_complete_historical_future_and_option_metadata_validated(self):
        from instrument_archive import SCHEMA
        row = dict(provider="angelone", symbol="NIFTY", underlying="NIFTY", identifier="OFFLINE_FUTURE_FIXTURE",
                   exchange="NFO", instrument_type="FUTIDX", multiplier=1, lot_size=75,
                   expiry="2026-10-29", valid_from="2026-10-01", valid_to="2026-10-29")
        archive = self._ingest(dict(schema_version=SCHEMA, provider="angelone", records=[row]))
        self.assertEqual(archive["status"], "ELIGIBLE_LOCAL_RESEARCH")
        self.assertEqual(self._resolve(symbol="NIFTY", identifier=row["identifier"], exchange="NFO",
                                      instrument_type="FUTIDX", lot_size=75)["expiry"], "2026-10-29")
        for change in (dict(underlying="BANKNIFTY"), dict(expiry="2026-10-14"), dict(lot_size=0),
                       dict(instrument_type="OPTIDX", strike=0, option_type="CE"),
                       dict(instrument_type="OPTIDX", strike=24800, option_type="BAD")):
            payload = dict(schema_version=SCHEMA, provider="angelone", records=[dict(row, **change)])
            with self.subTest(change=change):
                self.assertEqual(self._ingest(payload)["status"], "REJECTED")

    def test_repeated_ingestion_is_idempotent_and_keeps_first_ingestion_time(self):
        with patch("instrument_archive.local_ingestion_timestamp", return_value="2026-10-15T12:00:00+05:30"):
            first = self._ingest()
        with patch("instrument_archive.local_ingestion_timestamp", return_value="2026-10-16T12:00:00+05:30"):
            second = self._ingest()
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_instrument_master_archives()), 1)

    def test_rejected_ingestion_does_not_replace_eligible_archive(self):
        good = self._ingest()
        self._ingest(raw=b"truncated")
        self.assertEqual(self._resolve()["archive_id"], good["archive_id"])
        self.assertEqual(len(self.store.list_instrument_master_archives()), 2)

    def test_lookup_selects_only_matching_provider_and_effective_period(self):
        old = self._ingest(self._payload(valid_to="2026-10-10"))
        current = self._ingest(self._payload(valid_from="2026-10-11"))
        self._ingest(self._payload(provider="dhan", identifier="DIFFERENT_PROVIDER_FIXTURE"), provider="dhan")
        self.assertEqual(self._resolve(first_date="2026-10-05", last_date="2026-10-05")["archive_id"], old["archive_id"])
        self.assertEqual(self._resolve()["archive_id"], current["archive_id"])
        from instrument_identity import IdentityValidationError
        with self.assertRaises(IdentityValidationError):
            self._resolve(provider="dhan")

    def test_coverage_gaps_and_multiple_partial_snapshots_cannot_authorize_span(self):
        self._ingest(self._payload(valid_to="2026-10-10"))
        self._ingest(self._payload(valid_from="2026-10-12"))
        from instrument_identity import IdentityValidationError
        for first, last in (("2026-10-11", "2026-10-11"), ("2026-10-05", "2026-10-15")):
            with self.subTest(first=first), self.assertRaises(IdentityValidationError):
                self._resolve(first_date=first, last_date=last)

    def test_conflicting_overlap_rejects_even_when_full_archive_is_pinned(self):
        good = self._ingest()
        self._ingest(self._payload(identifier="OFFLINE_CONFLICT", valid_from="2026-10-15", valid_to="2026-10-15"))
        from instrument_identity import IdentityValidationError
        for pin in (None, good["archive_id"]):
            with self.subTest(pin=pin), self.assertRaises(IdentityValidationError) as caught:
                self._resolve(archive_id=pin)
            self.assertEqual(caught.exception.rejection["reason_code"], "AMBIGUOUS_ARCHIVE_COVERAGE")
        # Outside the conflict's declared date, the original record still resolves.
        self.assertEqual(self._resolve(first_date="2026-10-14", last_date="2026-10-14")["archive_id"], good["archive_id"])

    def test_legacy_envelope_remains_unknown_and_cannot_authorize_live_identity(self):
        archive = self._ingest(offline_equity_master_fixture())
        self.assertEqual(archive["status"], "INCOMPLETE")
        self.assertEqual(archive["metadata"]["source_type"], "LEGACY_UNKNOWN")
        from instrument_identity import IdentityValidationError
        with self.assertRaises(IdentityValidationError):
            self._resolve(archive_id=archive["archive_id"])

    def test_native_angel_master_reuses_parser_but_does_not_infer_effective_dates(self):
        archive = self._ingest(TestIndianFOSignalBotPhase2B._build_scrip_master_fixture(), captured_at="2026-10-15T12:00:00Z")
        self.assertEqual(archive["status"], "INCOMPLETE", archive["validation"])
        self.assertEqual(archive["record_count"], 13)
        self.assertEqual(archive["metadata"]["effective_date_basis"], "UNKNOWN")
        self.assertTrue(all(r["valid_from"] is None for r in archive["records"]))
        self.assertEqual(self._ingest([], provider="dhan")["status"], "REJECTED")

    def test_original_normalized_and_provenance_corruption_fail_closed(self):
        from instrument_identity import IdentityValidationError
        for target in ("bytes", "normalized", "provenance"):
            archive = self._ingest(filename=target+".json")
            conn = self.store._get_connection()
            with conn:
                if target == "bytes":
                    conn.execute("UPDATE instrument_master_archives SET original_bytes=? WHERE archive_id=?", (b"{}", archive["archive_id"]))
                else:
                    corrupted = json.loads(json.dumps(archive))
                    if target == "normalized": corrupted["records"][0]["identifier"] = "CORRUPTED"
                    else: corrupted["metadata"]["captured_at"] = "2026-10-01T00:00:00Z"
                    conn.execute("UPDATE instrument_master_archives SET candidate_json=? WHERE archive_id=?", (json.dumps(corrupted), archive["archive_id"]))
            with self.subTest(target=target), self.assertRaises(IdentityValidationError) as caught:
                self.store.get_instrument_master_archive(archive["archive_id"])
            self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")

    def test_filename_traversal_cannot_escape_or_write_files(self):
        from instrument_identity import IdentityValidationError
        for name in ("../master.json", "a/b.json", "a\\b.json", "C:master.json", ".."):
            with self.subTest(name=name), self.assertRaises(IdentityValidationError):
                self._ingest(filename=name)

    def test_local_file_workflow_preserves_bytes_and_blocks_path_escape(self):
        import tempfile
        from pathlib import Path
        from instrument_identity import IdentityValidationError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'master.json'
            original = json.dumps(self._payload(), indent=2).encode()
            source.write_bytes(original)
            archive = self.store.ingest_instrument_master_file(source, "angelone", "OFFLINE_FIXTURE", import_root=root)
            source.write_bytes(b"{}")
            self.assertEqual(self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)["original_bytes"], original)
            self.assertEqual(self._resolve()["archive_id"], archive["archive_id"])
            for path in ("../master.json", root.parent/'outside.json', "https://example.invalid/master.json"):
                with self.subTest(path=str(path)), self.assertRaises((IdentityValidationError, OSError)):
                    self.store.ingest_instrument_master_file(path, "angelone", "OFFLINE", import_root=root)

    def test_restart_and_additive_migration_preserve_existing_rows_and_archives(self):
        import tempfile
        import sqlite3
        from pathlib import Path
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'archive.db')
            with SQLitePersistenceStore(path) as store:
                store._save_live_acceptance_evidence("angelone", "RELIANCE", {"fixture": "unchanged-not-acceptance"})
            # Simulate the preceding schema: it had no archive table.
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("DROP TABLE instrument_master_archives")
            with SQLitePersistenceStore(path) as store:
                first = store.ingest_instrument_master_bytes(json.dumps(self._payload()).encode(), "angelone", "fixture.json", "OFFLINE_FIXTURE")
            for _ in range(2):
                with SQLitePersistenceStore(path) as store:
                    self.assertEqual(store.get_instrument_master_archive(first["archive_id"]), first)
                    self.assertEqual(store.load_live_acceptance_evidence("angelone", "RELIANCE"), {"fixture": "unchanged-not-acceptance"})
                    self.assertEqual(store.query_signals()["total_count"], 0)

    def test_concurrent_startup_and_idempotent_ingestion_preserve_evidence(self):
        import tempfile
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'concurrent.db')
            raw = json.dumps(self._payload()).encode()
            def ingest(_):
                with SQLitePersistenceStore(path) as store:
                    return store.ingest_instrument_master_bytes(raw, "angelone", "fixture.json", "OFFLINE_FIXTURE")["archive_id"]
            with ThreadPoolExecutor(max_workers=4) as pool:
                ids = list(pool.map(ingest, range(8)))
            self.assertEqual(len(set(ids)), 1)
            with SQLitePersistenceStore(path) as store:
                self.assertEqual(len(store.list_instrument_master_archives()), 1)
                self.assertEqual(store.inspect_archived_instrument_identity("angelone", "RELIANCE", "2885", "NSE", "EQ", "2026-10-15", "2026-10-15")["archive_id"], ids[0])

    def test_cli_ingest_list_and_show_use_local_archive_store(self):
        import tempfile
        import io
        from pathlib import Path
        from instrument_archive import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'fixture.json').write_bytes(json.dumps(self._payload()).encode())
            database = str(root/'cli.db')
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(main(["--database", database, "ingest", "fixture.json", "--import-root", directory,
                    "--provider", "angelone", "--source-reference", "OFFLINE_FIXTURE"]), 0)
            archive = json.loads(output.getvalue())
            for command in (["list"], ["show", archive["archive_id"]]):
                output = io.StringIO()
                with patch("sys.stdout", output):
                    self.assertEqual(main(["--database", database, *command]), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result[0]["archive_id"] if isinstance(result, list) else result["archive_id"], archive["archive_id"])

    def test_live_replay_persists_exact_archive_reference_without_reclassifying_old_runs(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        archive = self._ingest()
        rows = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: now)
        # An existing completed synthetic result is retained verbatim through qualification/import.
        simulated = [dict(r, data_mode="SIMULATED", is_simulated=True) for r in rows]
        prior = engine.run_backtest("strat_1_order_block", "RELIANCE", candles=simulated,
                                    provider="paper_sim_fixture", data_mode="SIMULATED", persist_run=True)
        before = self.store.get_backtest_run_detail(prior["run_id"])
        with self.assertRaises(BacktestEligibilityError) as caught:
            engine.run_backtest("strat_1_order_block", "RELIANCE", candles=rows, provider="angelone", data_mode="LIVE",
                backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", historical_instrument_archive_id=archive["archive_id"]), persist_run=True)
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        self.assertEqual(caught.exception.details["source_qualification"]["archive_id"], archive["archive_id"])
        self._ingest(self._payload(identifier="OFFLINE_CONFLICT"))
        self.assertEqual(self.store.get_backtest_run_detail(prior["run_id"]), before)

    def test_legacy_inline_backtest_cannot_bypass_ingestion_gate(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        rows = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: now)
        with self.assertRaises(BacktestEligibilityError):
            engine.run_backtest("strat_1_order_block", "RELIANCE", candles=rows, provider="angelone", data_mode="LIVE",
                backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", historical_instrument_identity=offline_equity_master_fixture()))
        self.assertEqual(self.store.list_instrument_master_archives()[0]["status"], "INCOMPLETE")

    def test_historical_strategy3_remains_blocked_before_archive_processing(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        engine = DeterministicBacktestEngine(store=self.store)
        for mode in ("LIVE", "SIMULATED"):
            with self.subTest(mode=mode), patch.object(self.store, "ingest_instrument_master_bytes") as ingest:
                with self.assertRaises(BacktestEligibilityError):
                    engine.run_backtest("strat_3_option_apex_oi", "NIFTY", data_mode=mode,
                        backtest_config=BacktestConfig(historical_instrument_identity=self._payload()))
                ingest.assert_not_called()


    def test_ingestion_time_cannot_be_supplied_as_source_evidence(self):
        from instrument_identity import IdentityValidationError
        with self.assertRaises(IdentityValidationError) as caught:
            self._ingest(ingested_at="1900-01-01T00:00:00Z")
        self.assertEqual(caught.exception.rejection["reason_code"], "INGESTION_TIME_IS_LOCAL")

    def test_provider_specific_and_classification_fields_cannot_conflict(self):
        for changes in (dict(angel_token="1333"), dict(is_index=True), dict(exchange_segment="IDX_I")):
            with self.subTest(changes=changes):
                self.assertEqual(self._ingest(self._payload(**changes))["status"], "REJECTED")


    def test_backtest_cli_file_path_preserves_original_bytes_including_bom(self):
        import tempfile
        import io
        import hashlib
        from pathlib import Path
        from backtest_engine import main, DeterministicBacktestEngine
        now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.store.save_historical_candle_dataset(TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15"),
            symbol="RELIANCE", segment="NSE_EQUITY_INTRADAY", exchange="NSE", provider="angelone",
            instrument_token="2885", data_mode="LIVE", reference_time_ist=now)
        with tempfile.TemporaryDirectory() as directory:
            raw = b'\xef\xbb\xbf'+json.dumps(self._payload(), indent=3).encode()+b'\n'
            (Path(directory)/'master.json').write_bytes(raw)
            output = io.StringIO()
            with patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), \
                    patch("backtest_engine.DeterministicBacktestEngine", side_effect=lambda **kw: DeterministicBacktestEngine(**kw, clock=lambda: now)), \
                    patch("sys.stdout", output):
                code = main(["--data-mode", "LIVE", "--provider", "angelone", "--execution-scope", "HISTORICAL_RESEARCH",
                             "--historical-instrument-master", "master.json", "--instrument-import-root", directory, "--json"])
            self.assertEqual(code, 2, output.getvalue())
            error = json.loads(output.getvalue())["rejection"]
            self.assertEqual(error["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
            archive = self.store.list_instrument_master_archives()[0]
            self.assertEqual(archive["metadata"]["original_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(archive["metadata"]["input_kind"], "LOCAL_FILE")

    def test_inline_serialization_is_not_classified_as_an_original_external_file(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: now)
        with self.assertRaises(BacktestEligibilityError) as caught:
            engine.run_backtest("strat_1_order_block", "RELIANCE", provider="angelone", data_mode="LIVE",
                candles=TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15"),
                backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", historical_instrument_identity=self._payload()))
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        self.assertEqual(self.store.list_instrument_master_archives()[0]["metadata"]["input_kind"], "INLINE_SERIALIZATION")

    def test_same_future_contract_with_two_tokens_is_ambiguous_across_archives(self):
        from instrument_archive import SCHEMA
        from instrument_identity import IdentityValidationError
        row = dict(symbol="NIFTY", underlying="NIFTY", identifier="OFFLINE_FUTURE_1", exchange="NFO",
            instrument_type="FUTIDX", multiplier=1, lot_size=75, expiry="2026-10-29", valid_from="2026-10-01", valid_to="2026-10-29")
        self._ingest(dict(schema_version=SCHEMA, provider="angelone", records=[row]))
        self._ingest(dict(schema_version=SCHEMA, provider="angelone", records=[dict(row, identifier="OFFLINE_FUTURE_2")]))
        with self.assertRaises(IdentityValidationError) as caught:
            self._resolve(symbol="NIFTY", identifier="OFFLINE_FUTURE_1", exchange="NFO", instrument_type="FUTIDX", lot_size=75)
        self.assertEqual(caught.exception.rejection["reason_code"], "AMBIGUOUS_ARCHIVE_COVERAGE")


    def test_historical_identifier_is_resolved_from_source_not_current_pin(self):
        archive = self._ingest(self._payload(identifier="OFFLINE_PRIOR_IDENTIFIER"))
        identity = self._resolve(identifier="OFFLINE_PRIOR_IDENTIFIER")
        self.assertEqual(identity["archive_id"], archive["archive_id"])
        self.assertEqual(identity["identifier"], "OFFLINE_PRIOR_IDENTIFIER")

    def test_network_import_roots_reject_before_any_filesystem_resolution(self):
        from pathlib import Path
        from instrument_identity import IdentityValidationError
        with patch.object(Path, "resolve") as resolution, self.assertRaises(IdentityValidationError):
            self.store.ingest_instrument_master_file("master.json", "angelone", "OFFLINE", import_root="//not-a-real-server/share")
        resolution.assert_not_called()


class TestSourceEvidenceQualification(unittest.TestCase):
    """No qualifying publisher/date evidence exists; fixture claims never make it exist."""

    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        guard = patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden in qualification tests"))
        guard.start()
        self.addCleanup(guard.stop)

    def _archive(self, payload=None, provider="angelone", **metadata):
        payload = TestInstrumentArchives._payload(provider) if payload is None else payload
        return self.store.ingest_instrument_master_bytes(json.dumps(payload).encode(), provider, "source-fixture.json",
            "OFFLINE_DECLARATIONS_NOT_AUTHENTICATED_EVIDENCE", **metadata)

    def _resolve(self, archive_id=None, **changes):
        args = dict(provider="angelone", symbol="RELIANCE", identifier="2885", exchange="NSE", instrument_type="EQ",
                    first_date="2026-10-15", last_date="2026-10-15", archive_id=archive_id)
        args.update(changes)
        return self.store.resolve_archived_instrument_identity(**args)

    def test_matching_hash_is_content_integrity_only(self):
        archive = self._archive()
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["content_integrity"]["status"], "MATCHES_RECORDED_DIGESTS")
        self.assertEqual(report["publisher_authenticity"]["status"], "NOT_ESTABLISHED")
        self.assertFalse(report["historical_eligibility"]["allowed"])

    def test_saved_urls_names_and_publication_times_remain_declarations(self):
        archive = self._archive(source_url="https://dhanhq.co/docs/v2/instruments/",
            captured_at="2026-10-15T00:00:00Z", publisher_published_at="2026-10-01T00:00:00Z")
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["source_attribution"]["status"], "USER_DECLARED")
        self.assertEqual(report["capture_time"]["status"], "USER_DECLARED")
        self.assertEqual(report["publication_time"]["status"], "USER_DECLARED")
        self.assertEqual(report["source_attribution"]["archive_source_binding"], "NOT_INDEPENDENTLY_ESTABLISHED")

    def test_missing_source_capture_and_effective_evidence_are_explicit(self):
        payload = TestInstrumentArchives._payload(valid_from=None, valid_to=None)
        archive = self._archive(payload)
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["effective_dates"]["status"], "UNKNOWN")
        self.assertEqual(report["capture_time"]["status"], "UNKNOWN")
        self.assertIn("SOURCE_ATTRIBUTION_NOT_INDEPENDENTLY_ESTABLISHED", report["historical_eligibility"]["missing_evidence"])
        self.assertFalse(report["ingestion_time"]["is_capture_time_evidence"])

    def test_declared_intervals_are_not_authoritative_historical_coverage(self):
        archive = self._archive()
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["effective_dates"]["status"], "DECLARED_ONLY")
        self.assertTrue(report["effective_dates"]["declared_intervals"])
        self.assertEqual(report["effective_dates"]["independently_supported_intervals"], [])
        self.assertIn("EFFECTIVE_DATE_AUTHORITY_NOT_ESTABLISHED", report["historical_eligibility"]["missing_evidence"])

    def test_provider_documentation_is_not_an_archive_authentication_mechanism(self):
        for provider in ("dhan", "upstox"):
            archive = self._archive(provider=provider)
            report = self.store.qualify_instrument_master_archive(archive["archive_id"])
            self.assertEqual(report["source_documentation"]["status"], "PROVIDER_DOCUMENTATION_REVIEWED")
            self.assertEqual(report["source_documentation"]["scope"], "DOCUMENTATION_ONLY_NOT_ARCHIVE_AUTHENTICATION")
            self.assertEqual(report["publisher_authenticity"]["supported_verification_mechanisms"], [])
            self.assertFalse(report["historical_eligibility"]["allowed"])

    def test_claimed_independent_effective_dates_and_verified_flags_are_not_accepted(self):
        payload = dict(TestInstrumentArchives._payload(), verified=True, qualified=True,
            publisher_authenticity="VERIFIED", source_evidence={"mechanism": "UNSUPPORTED_TEST_CLAIM"},
            effective_date_evidence={"status": "INDEPENDENTLY_ESTABLISHED"},
            independently_supported_intervals=[{"valid_from": "2026-10-01", "valid_to": "2026-10-31"}])
        archive = self._archive(payload)
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["submitted_qualification_claims"], "PRESENT_UNVALIDATED")
        self.assertEqual(report["effective_dates"]["independently_supported_intervals"], [])
        self.assertEqual(report["publisher_authenticity"]["status"], "NOT_ESTABLISHED")

    def test_archive_pin_cannot_bypass_insufficient_evidence(self):
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        for pin in (None, archive["archive_id"]):
            with self.subTest(pin=pin), self.assertRaises(IdentityValidationError) as caught:
                self._resolve(pin)
            self.assertEqual(caught.exception.rejection["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
            self.assertFalse(caught.exception.rejection["source_qualification"]["historical_eligibility"]["allowed"])

    def test_coverage_gaps_remain_blocked_before_qualification_can_authorize_anything(self):
        from instrument_identity import IdentityValidationError
        self._archive(TestInstrumentArchives._payload(valid_to="2026-10-10"))
        with self.assertRaises(IdentityValidationError) as caught:
            self._resolve()
        self.assertEqual(caught.exception.rejection["reason_code"], "HISTORICAL_ARCHIVE_COVERAGE_MISSING")

    def test_conflicting_declared_sources_remain_ambiguous_even_with_pin(self):
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        self._archive(TestInstrumentArchives._payload(identifier="CONFLICTING_OFFLINE_DECLARATION"))
        with self.assertRaises(IdentityValidationError) as caught:
            self._resolve(archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "AMBIGUOUS_ARCHIVE_COVERAGE")

    def test_tampered_original_bytes_fail_before_source_assessment(self):
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        conn = self.store._get_connection()
        with conn:
            conn.execute("UPDATE instrument_master_archives SET original_bytes=? WHERE archive_id=?", (b"{}", archive["archive_id"]))
        with self.assertRaises(IdentityValidationError) as caught:
            self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")

    def test_stored_assessment_verdict_cannot_be_edited_to_grant_trust(self):
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        report["historical_eligibility"]["allowed"] = True
        conn = self.store._get_connection()
        with conn:
            conn.execute("UPDATE instrument_source_assessments SET assessment_json=? WHERE archive_id=?", (json.dumps(report), archive["archive_id"]))
        with self.assertRaises(IdentityValidationError) as caught:
            self._resolve(archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "SOURCE_ASSESSMENT_INTEGRITY_FAILURE")

    def test_source_qualification_does_not_rewrite_legacy_archive_classification(self):
        archive = self._archive()
        conn = self.store._get_connection()
        before = conn.execute("SELECT candidate_json,original_bytes FROM instrument_master_archives WHERE archive_id=?", (archive["archive_id"],)).fetchone()
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        after = conn.execute("SELECT candidate_json,original_bytes FROM instrument_master_archives WHERE archive_id=?", (archive["archive_id"],)).fetchone()
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(self.store.get_instrument_master_archive(archive["archive_id"]), archive)
        self.assertEqual(archive["status"], "ELIGIBLE_LOCAL_RESEARCH")
        self.assertFalse(report["historical_eligibility"]["allowed"])

    def test_restart_preserves_versioned_assessment_and_additive_migration(self):
        import tempfile
        import sqlite3
        from pathlib import Path
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'qualification.db')
            raw = json.dumps(TestInstrumentArchives._payload()).encode()
            with SQLitePersistenceStore(path) as store:
                archive = store.ingest_instrument_master_bytes(raw, "angelone", "fixture.json", "OFFLINE_DECLARATIONS")
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("DROP TABLE instrument_source_assessments")
            with SQLitePersistenceStore(path) as store:
                report = store.qualify_instrument_master_archive(archive["archive_id"])
            with SQLitePersistenceStore(path) as store:
                self.assertEqual(store.qualify_instrument_master_archive(archive["archive_id"]), report)
                self.assertEqual(store.get_instrument_master_archive(archive["archive_id"]), archive)
                conn = store._get_connection()
                try:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM instrument_source_assessments").fetchone()[0], 1)
                finally:
                    store._close_if_file(conn)

    def test_declared_synthetic_data_never_becomes_authenticated_external_evidence(self):
        payload = dict(TestInstrumentArchives._payload(), evidence_class="SYNTHETIC_FIXTURE")
        archive = self._archive(payload)
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["artifact_classification"], "DECLARED_SYNTHETIC")
        self.assertFalse(report["historical_eligibility"]["allowed"])
        self.assertEqual(report["publisher_authenticity"]["status"], "NOT_ESTABLISHED")

    def test_legacy_unknown_source_remains_unknown(self):
        archive = self._archive(offline_equity_master_fixture())
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["source_attribution"]["status"], "UNKNOWN")
        self.assertFalse(report["historical_eligibility"]["allowed"])

    def test_cli_qualify_is_offline_reports_missing_evidence_and_returns_failure(self):
        import tempfile
        import io
        from pathlib import Path
        from instrument_archive import main
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'cli.db')
            with SQLitePersistenceStore(path) as store:
                archive = store.ingest_instrument_master_bytes(json.dumps(TestInstrumentArchives._payload()).encode(), "angelone", "fixture.json", "OFFLINE_DECLARATIONS")
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(main(["--database", path, "qualify", archive["archive_id"]]), 1)
            report = json.loads(output.getvalue())
            self.assertFalse(report["historical_eligibility"]["allowed"])
            self.assertIn("PUBLISHER_AUTHENTICITY_NOT_ESTABLISHED", report["historical_eligibility"]["missing_evidence"])

    def test_live_replay_fails_before_strategy_evaluation_with_missing_evidence(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        archive = self._archive()
        now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: now)
        with patch.object(engine, "_invoke_strategy_evaluator") as evaluator, self.assertRaises(BacktestEligibilityError) as caught:
            engine.run_backtest("strat_1_order_block", "RELIANCE", provider="angelone", data_mode="LIVE",
                candles=TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15"),
                backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", historical_instrument_archive_id=archive["archive_id"]))
        evaluator.assert_not_called()
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")

    def test_declaration_inspection_is_explicitly_ineligible(self):
        archive = self._archive()
        view = self.store.inspect_archived_instrument_identity("angelone", "RELIANCE", "2885", "NSE", "EQ", "2026-10-15", "2026-10-15")
        self.assertEqual(view["archive_id"], archive["archive_id"])
        self.assertFalse(view["live_historical_eligible"])

    def test_policy_assessments_are_idempotent_under_concurrent_startup(self):
        import tempfile
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'concurrent.db')
            with SQLitePersistenceStore(path) as store:
                archive = store.ingest_instrument_master_bytes(json.dumps(TestInstrumentArchives._payload()).encode(), "angelone", "fixture.json", "OFFLINE_DECLARATIONS")
            def assess(_):
                with SQLitePersistenceStore(path) as store:
                    return store.qualify_instrument_master_archive(archive["archive_id"])
            with ThreadPoolExecutor(max_workers=4) as pool:
                reports = list(pool.map(assess, range(8)))
            self.assertTrue(all(report == reports[0] for report in reports))
            self.assertFalse(reports[0]["historical_eligibility"]["allowed"])


    def test_readiness_cannot_claim_overall_execution_ready_from_receipts_alone(self):
        from historical_data import evaluate_phase3a_backtest_readiness
        original = dict(phase3_ready_for_execution=True, phase2c_live_accepted=True,
                        execution_gate={"allowed": True, "reason_code": "LIVE_DIAGNOSTIC_ACCEPTED_RESEARCH"})
        for mode in ("LIVE", " live "):
            with self.subTest(mode=mode), patch("readiness_policy.readiness_report", return_value=original):
                report = evaluate_phase3a_backtest_readiness(BotConfig(), self.store, target_data_mode=mode)
            self.assertFalse(report["phase3_ready_for_execution"])
            self.assertTrue(report["acceptance_coverage_ready_for_execution"])
            self.assertTrue(report["phase2c_live_accepted"])
            self.assertTrue(report["execution_gate"]["allowed"])
            self.assertFalse(report["historical_source_qualification"]["live_historical_replay_allowed"])
            self.assertTrue(original["phase3_ready_for_execution"])

    def test_resolver_does_not_trust_forged_qualification_dictionary(self):
        from instrument_archive import resolve_archives
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        source = self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)
        source["source_qualification"] = {"historical_eligibility": {"allowed": True}, "publisher_authenticity": {"status": "VERIFIED"}}
        with self.assertRaises(IdentityValidationError) as caught:
            resolve_archives([source], "angelone", "RELIANCE", "2885", "NSE", "EQ", "2026-10-15", "2026-10-15")
        actual = caught.exception.rejection["source_qualification"]
        self.assertFalse(actual["historical_eligibility"]["allowed"])
        self.assertEqual(actual["publisher_authenticity"]["status"], "NOT_ESTABLISHED")


class TestOfficialSourceFeasibility(unittest.TestCase):
    """Offline containment tests; no fixture represents verified provider evidence."""

    TOKENS = {"angelone": "2885", "dhan": "2885", "upstox": "NSE_EQ|INE002A01018"}

    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        guard = patch("urllib.request.urlopen", side_effect=AssertionError("Broker requests forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def _archive(self, provider="angelone", payload=None, **metadata):
        payload = self._payload(provider) if payload is None else payload
        return self.store.ingest_instrument_master_bytes(json.dumps(payload).encode(), provider,
            "feasibility-fixture.json", "OFFLINE_UNAUTHENTICATED_DECLARATIONS", **metadata)

    def _payload(self, provider="angelone", **changes):
        return TestInstrumentArchives._payload(provider, identifier=self.TOKENS[provider], **changes)

    def _resolve(self, provider="angelone", **changes):
        args = dict(provider=provider, symbol="RELIANCE", identifier=self.TOKENS[provider], exchange="NSE",
                    instrument_type="EQ", first_date="2026-10-15", last_date="2026-10-15")
        args.update(changes)
        return self.store.resolve_archived_instrument_identity(**args)

    def _history(self, provider):
        bars = TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        self.store.save_historical_candle_dataset(bars, symbol="RELIANCE", segment="NSE_EQUITY_INTRADAY",
            exchange="NSE", provider=provider, instrument_token=self.TOKENS[provider], data_mode="LIVE",
            reference_time_ist=self.now)
        return bars

    def test_all_providers_reject_claimed_verifier_success_and_archive_pins(self):
        from instrument_identity import IdentityValidationError
        for provider in self.TOKENS:
            payload = dict(self._payload(provider), verified=True, qualified=True,
                source_evidence={"signature": "UNVERIFIED_FIXTURE", "checksum": "DECLARATION_ONLY",
                                 "authenticated_response": True, "verifier_result": {"valid": True}},
                effective_date_evidence={"status": "VERIFIED", "valid_from": "2026-10-01", "valid_to": "2026-10-31"})
            archive = self._archive(provider, payload)
            report = self.store.qualify_instrument_master_archive(archive["archive_id"])
            self.assertEqual(report["content_integrity"]["status"], "MATCHES_RECORDED_DIGESTS")
            self.assertEqual(report["publisher_authenticity"]["supported_verification_mechanisms"], [])
            self.assertEqual(report["effective_dates"]["independently_supported_intervals"], [])
            for pin in (None, archive["archive_id"]):
                with self.subTest(provider=provider, pin=pin), self.assertRaises(IdentityValidationError) as caught:
                    self._resolve(provider, archive_id=pin)
                self.assertEqual(caught.exception.rejection["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")

    def test_rehashed_original_bytes_cannot_reuse_an_archive_identity(self):
        import hashlib
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        raw = self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)["original_bytes"] + b"\n"
        archive["metadata"]["original_sha256"] = hashlib.sha256(raw).hexdigest()
        conn = self.store._get_connection()
        with conn:
            conn.execute("UPDATE instrument_master_archives SET original_bytes=?,candidate_json=? WHERE archive_id=?",
                         (raw, json.dumps(archive), archive["archive_id"]))
        with self.assertRaises(IdentityValidationError) as caught:
            self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")

    def test_normalized_record_tampering_fails_with_or_without_rehashed_records(self):
        import copy
        from instrument_identity import IdentityValidationError, digest
        archive = self._archive()
        for rehash in (False, True):
            changed = copy.deepcopy(archive)
            changed["records"][0]["identifier"] = "TAMPERED"
            if rehash:
                changed["normalized_sha256"] = digest(changed["records"])
            conn = self.store._get_connection()
            with conn:
                conn.execute("UPDATE instrument_master_archives SET candidate_json=? WHERE archive_id=?",
                             (json.dumps(changed), archive["archive_id"]))
            with self.subTest(rehash=rehash), self.assertRaises(IdentityValidationError) as caught:
                self.store.qualify_instrument_master_archive(archive["archive_id"])
            self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")

    def test_provenance_metadata_changes_cannot_reuse_a_prior_assessment(self):
        import copy
        from instrument_identity import IdentityValidationError
        archive = self._archive()
        before = self.store.qualify_instrument_master_archive(archive["archive_id"])
        for field, value in (("provider", "dhan"), ("source_reference", "REPLACED"),
                             ("source_url", "https://dhanhq.co/docs/v2/instruments/"),
                             ("captured_at", "2026-10-15T12:00:00+05:30"),
                             ("publisher_published_at", "2026-10-14T12:00:00+05:30")):
            changed = copy.deepcopy(archive)
            changed["metadata"][field] = value
            conn = self.store._get_connection()
            with conn:
                conn.execute("UPDATE instrument_master_archives SET candidate_json=? WHERE archive_id=?",
                             (json.dumps(changed), archive["archive_id"]))
            with self.subTest(field=field), self.assertRaises(IdentityValidationError) as caught:
                self.store.qualify_instrument_master_archive(archive["archive_id"])
            self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")
        with conn:
            conn.execute("UPDATE instrument_master_archives SET candidate_json=? WHERE archive_id=?",
                         (json.dumps(archive), archive["archive_id"]))
        self.assertEqual(self.store.qualify_instrument_master_archive(archive["archive_id"]), before)

    def test_provider_segment_and_wire_identity_mismatches_are_rejected(self):
        for provider in self.TOKENS:
            for changes, reason in (({"provider": "OTHER_PROVIDER"}, "ARCHIVE_PROVIDER_MISMATCH"),
                                    ({"segment": "NSE_FO_INDEX"}, "ARCHIVE_SEGMENT_MISMATCH"),
                                    ({"exchange_segment": "NSE_FNO"}, "ARCHIVE_SEGMENT_MISMATCH"),
                                    ({"instrument_type": "FUTIDX"}, "ARCHIVE_SEGMENT_MISMATCH")):
                payload = self._payload(provider)
                payload["records"][0].update(changes)
                with self.subTest(provider=provider, changes=changes):
                    archive = self._archive(provider, payload)
                    self.assertEqual(archive["status"], "REJECTED")
                    self.assertEqual(archive["validation"]["reason_code"], reason)
            key = {"angelone": "angel_token", "dhan": "security_id", "upstox": "instrument_key"}[provider]
            archive = self._archive(provider, self._payload(provider, **{key: "WRONG_IDENTIFIER"}))
            self.assertEqual(archive["validation"]["reason_code"], "ARCHIVE_IDENTITY_MISMATCH")

    def test_missing_and_contradictory_dates_cannot_be_supplied_by_verified_claims(self):
        for provider in self.TOKENS:
            for dates, status in (({"valid_from": None, "valid_to": None}, "INCOMPLETE"),
                                  ({"valid_from": "2026-10-16", "valid_to": "2026-10-01"}, "REJECTED")):
                payload = dict(self._payload(provider, **dates), effective_date_evidence={"verified": True})
                with self.subTest(provider=provider, dates=dates):
                    archive = self._archive(provider, payload)
                    self.assertEqual(archive["status"], status)
                    report = self.store.qualify_instrument_master_archive(archive["archive_id"])
                    self.assertFalse(report["historical_eligibility"]["allowed"])
                    self.assertEqual(report["effective_dates"]["independently_supported_intervals"], [])

    def test_replay_checks_archive_coverage_before_evaluation_start_including_warmup(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        bars = sum((TestIndianFOSignalBotPhase3A._build_session_bars(day)
                    for day in ("2026-10-14", "2026-10-15")), [])
        archive = self._archive(payload=self._payload(valid_from="2026-10-15"))
        engine = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now)
        with patch.object(self.store, "resolve_archived_instrument_identity", wraps=self.store.resolve_archived_instrument_identity) as resolver, \
                patch.object(engine, "_invoke_strategy_evaluator") as evaluator, self.assertRaises(BacktestEligibilityError) as caught:
            engine.run_backtest("strat_1_order_block", "RELIANCE", candles=bars, provider="angelone", data_mode="LIVE",
                backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", evaluation_start_date="2026-10-15",
                                              historical_instrument_archive_id=archive["archive_id"]))
        self.assertEqual(resolver.call_args.args[5:7], ("2026-10-14", "2026-10-15"))
        self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_ARCHIVE_COVERAGE_MISSING")
        evaluator.assert_not_called()

    def test_date_range_change_and_pin_never_reuse_a_coverage_verdict(self):
        from instrument_identity import IdentityValidationError
        archive = self._archive(payload=self._payload(valid_from="2026-10-15", valid_to="2026-10-15"))
        before = self.store.qualify_instrument_master_archive(archive["archive_id"])
        for start, end, reason in (("2026-10-15", "2026-10-15", "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT"),
                                   ("2026-10-14", "2026-10-15", "HISTORICAL_ARCHIVE_COVERAGE_MISSING"),
                                   ("2026-10-15", "2026-10-16", "HISTORICAL_ARCHIVE_COVERAGE_MISSING")):
            with self.subTest(start=start, end=end), self.assertRaises(IdentityValidationError) as caught:
                self._resolve(first_date=start, last_date=end, archive_id=archive["archive_id"])
            self.assertEqual(caught.exception.rejection["reason_code"], reason)
        self.assertEqual(self.store.qualify_instrument_master_archive(archive["archive_id"]), before)

    def test_stale_policy_verdict_is_retained_but_never_consumed(self):
        from instrument_identity import IdentityValidationError
        from source_qualification import POLICY_VERSION
        archive = self._archive()
        stale = json.dumps({"policy_version": "UNSUPPORTED_OLD_POLICY", "historical_eligibility": {"allowed": True}})
        conn = self.store._get_connection()
        with conn:
            conn.execute("INSERT INTO instrument_source_assessments VALUES (?, ?, ?)",
                         (archive["archive_id"], "UNSUPPORTED_OLD_POLICY", stale))
        with self.assertRaises(IdentityValidationError) as caught:
            self._resolve(archive_id=archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        rows = dict(conn.execute("SELECT policy_version,assessment_json FROM instrument_source_assessments"))
        self.assertEqual(rows["UNSUPPORTED_OLD_POLICY"], stale)
        self.assertFalse(json.loads(rows[POLICY_VERSION])["historical_eligibility"]["allowed"])

    def test_reimport_with_changed_provenance_retains_prior_archive_and_assessment(self):
        first = self._archive(captured_at="2026-10-15T12:00:00+05:30")
        report = self.store.qualify_instrument_master_archive(first["archive_id"])
        conn = self.store._get_connection()
        before = tuple(conn.execute("SELECT * FROM instrument_source_assessments WHERE archive_id=?", (first["archive_id"],)).fetchone())
        second = self._archive(captured_at="2026-10-16T12:00:00+05:30")
        self.assertNotEqual(first["archive_id"], second["archive_id"])
        self.assertEqual(first["normalized_sha256"], second["normalized_sha256"])
        self.assertFalse(self.store.qualify_instrument_master_archive(second["archive_id"])["historical_eligibility"]["allowed"])
        self.assertEqual(self.store.get_instrument_master_archive(first["archive_id"]), first)
        self.assertEqual(self.store.qualify_instrument_master_archive(first["archive_id"]), report)
        self.assertEqual(tuple(conn.execute("SELECT * FROM instrument_source_assessments WHERE archive_id=?", (first["archive_id"],)).fetchone()), before)

    def test_direct_inline_pinned_and_sqlite_replay_paths_reject_for_every_provider(self):
        from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
        for provider in self.TOKENS:
            bars = self._history(provider)
            archive = self._archive(provider)
            engine = DeterministicBacktestEngine(store=self.store, clock=lambda: self.now)
            for candles in (bars, None):
                for source in ({"historical_instrument_identity": self._payload(provider)},
                               {"historical_instrument_archive_id": archive["archive_id"]}):
                    with self.subTest(provider=provider, sqlite=candles is None, source=list(source)), \
                            patch.object(engine, "_invoke_strategy_evaluator") as evaluator, \
                            patch.object(self.store, "save_backtest_run") as save, self.assertRaises(BacktestEligibilityError) as caught:
                        engine.run_backtest("strat_1_order_block", "RELIANCE", candles=candles, provider=provider,
                            instrument_token=self.TOKENS[provider], data_mode="LIVE", persist_run=True,
                            backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH", **source))
                    self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
                    evaluator.assert_not_called()
                    save.assert_not_called()

    def test_api_inline_and_pinned_replay_paths_reject_for_every_provider(self):
        import io
        from types import SimpleNamespace
        from backtest_engine import DeterministicBacktestEngine
        from server import DashboardRequestHandler
        for provider in self.TOKENS:
            bars = self._history(provider)
            archive = self._archive(provider)
            for source in ({"historical_instrument_identity": self._payload(provider)},
                           {"historical_instrument_archive_id": archive["archive_id"]}):
                body = json.dumps(dict(strategy_id="strat_1_order_block", symbol="RELIANCE", provider=provider,
                    instrument_token=self.TOKENS[provider], data_mode="LIVE", candles=bars,
                    execution_scope="HISTORICAL_RESEARCH", persist_run=True, **source)).encode()
                handler = object.__new__(DashboardRequestHandler)
                handler.headers = {"Content-Length": str(len(body))}
                handler.rfile = io.BytesIO(body)
                handler.engine = SimpleNamespace(config=BotConfig(), store=self.store, clock=lambda: self.now,
                                                 get_broker_status=lambda: {})
                with self.subTest(provider=provider, source=list(source)), \
                        patch.object(DeterministicBacktestEngine, "_invoke_strategy_evaluator") as evaluator, \
                        patch.object(self.store, "save_backtest_run") as save:
                    code, result = handler._handle_post_backtest()
                self.assertEqual(code, 422, result)
                self.assertEqual(result["rejection"]["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
                evaluator.assert_not_called()
                save.assert_not_called()

    def test_cli_pinned_replay_path_rejects_for_every_provider(self):
        import io
        from backtest_engine import main, DeterministicBacktestEngine
        for provider in self.TOKENS:
            self._history(provider)
            archive = self._archive(provider)
            output = io.StringIO()
            with self.subTest(provider=provider), patch("backtest_engine.SQLitePersistenceStore", return_value=self.store), \
                    patch("backtest_engine.DeterministicBacktestEngine", side_effect=lambda **kw: DeterministicBacktestEngine(**kw, clock=lambda: self.now)), \
                    patch.object(DeterministicBacktestEngine, "_invoke_strategy_evaluator") as evaluator, \
                    patch.object(self.store, "save_backtest_run") as save, patch("sys.stdout", output):
                code = main(["--data-mode", "LIVE", "--provider", provider, "--execution-scope", "HISTORICAL_RESEARCH",
                             "--instrument-archive-id", archive["archive_id"], "--json"])
            self.assertEqual(code, 2, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["rejection"]["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
            evaluator.assert_not_called()
            save.assert_not_called()


class TestUpstoxReadOnlyReadiness(unittest.TestCase):
    """All responses are synthetic fixtures; no credential or broker acceptance evidence."""

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 36, 5, tzinfo=IST)
        self.cfg = BotConfig(active_broker="upstox", upstox_api_key="OFFLINE_API_SECRET",
            upstox_access_token="OFFLINE_ACCESS_SECRET", telegram_dry_run=True,
            enable_background_scheduler=False, enable_persistence=False, database_url=":memory:")
        self.adapter = UpstoxV2Adapter(self.cfg, clock=lambda: self.now)
        self.network = patch("urllib.request.urlopen", side_effect=AssertionError("External transport forbidden"))
        self.transport = self.network.start()
        self.addCleanup(self.network.stop)

    def _quote(self, **changes):
        item = dict(instrument_token="NSE_EQ|INE002A01018", symbol="RELIANCE", last_price=2950,
                    ohlc=dict(open=2940, high=2960, low=2930, close=2900),
                    timestamp="2026-10-16T10:36:04+05:30", last_trade_time=int(self.now.timestamp()*1000)-1000, volume=10000)
        item.update(changes)
        return dict(status="success", data={"NSE_EQ:RELIANCE": item})

    def _candles(self, **changes):
        from datetime import timedelta
        start = datetime(2026, 10, 16, 10, 25, tzinfo=IST)
        rows = [[(start+timedelta(minutes=i)).isoformat(), 2940, 2960, 2930, 2950, 100] for i in range(12)]
        payload = dict(status="success", data=dict(candles=list(reversed(rows))))
        payload.update(changes)
        return payload

    def _responses(self, *responses):
        import io
        queue = list(responses)
        def reply(request, timeout=8):
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(timeout, 8)
            self.assertTrue(request.full_url.startswith("https://api.upstox.com/v2/"))
            value = queue.pop(0)
            if isinstance(value, Exception):
                raise value
            return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.transport.side_effect = reply

    def _diagnostic(self, **changes):
        from upstox_diagnostics import run_upstox_diagnostics
        return run_upstox_diagnostics(self.cfg, self.adapter, symbol=changes.pop("symbol", "RELIANCE"),
                                      clock=lambda: self.now, **changes)

    def test_quote_success_uses_standalone_get_and_preserves_previous_close(self):
        self._responses(self._quote())
        result = MultiBrokerScanner(self.cfg, clock=lambda: self.now).fetch_quote("RELIANCE")
        self.assertEqual(result["ltp"], 2950)
        self.assertEqual(result["close"], 2900)  # Previous close can be outside today's range.
        self.assertEqual(result["instrument_identity"]["response_binding"], "ECHO_CHECKED")
        request = self.transport.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_EQ%7CINE002A01018")

    def test_quote_missing_echo_is_limited_request_bound_evidence(self):
        payload = self._quote()
        item = payload["data"]["NSE_EQ:RELIANCE"]
        del item["instrument_token"], item["symbol"]
        self._responses(payload)
        quote = self.adapter.get_quote("RELIANCE")
        self.assertEqual(quote["instrument_identity"]["response_binding"], "REQUEST_BOUND_NO_ECHO")

    def test_quote_identity_mismatch_unrequested_map_and_multiple_items_fail(self):
        for field, value in (("instrument_token", "NSE_EQ|WRONG"), ("symbol", "HDFCBANK"),
                             ("provider", "dhan"), ("exchange", "BSE")):
            with self.subTest(field=field):
                self._responses(self._quote(**{field: value}))
                with self.assertRaises(BrokerDataError):
                    self.adapter.get_quote("RELIANCE")
        for data in ({"NSE_EQ:HDFCBANK": self._quote()["data"]["NSE_EQ:RELIANCE"]},
                     dict(self._quote()["data"], EXTRA={})):
            self._responses(dict(status="success", data=data))
            with self.assertRaises(BrokerDataError):
                self.adapter.get_quote("RELIANCE")

    def test_quote_malformed_prices_and_ohlc_are_rejected(self):
        for changes in (dict(last_price=True), dict(last_price=None), dict(last_price="NONNUMERIC"),
                        dict(last_price=float("inf")), dict(last_price=0), dict(ohlc=None),
                        dict(ohlc=dict(open=2940, high=2930, low=2960, close=2900)), dict(volume=-1)):
            with self.subTest(changes=changes):
                self._responses(self._quote(**changes))
                with self.assertRaises(BrokerDataError):
                    self.adapter.get_quote("RELIANCE")

    def test_quote_invalid_naive_and_future_timestamps_fail_safely(self):
        for timestamp in ("INVALID", "2026-10-16 10:35:00", "2026-10-16T10:40:00+05:30", True):
            self._responses(self._quote(timestamp=timestamp))
            with self.subTest(timestamp=timestamp), self.assertRaises(BrokerDataError):
                self.adapter.get_quote("RELIANCE")

    def test_supported_index_quote_uses_pinned_spot_identity(self):
        item = self._quote()["data"]["NSE_EQ:RELIANCE"]
        item.update(instrument_token="NSE_INDEX|Nifty 50", symbol="Nifty 50")
        self._responses(dict(status="success", data={"NSE_INDEX:Nifty 50": item}))
        self.assertEqual(self.adapter.get_quote("NIFTY")["instrument_identity"]["instrument_type"], "INDEX_SPOT")

    def test_provider_errors_malformed_json_and_envelopes_do_not_authenticate(self):
        for payload in (b"<html>OFFLINE_ACCESS_SECRET</html>", [], dict(status="error", errors=["OFFLINE_ACCESS_SECRET"]),
                        dict(status="success", data=None)):
            reader = UpstoxV2Adapter(self.cfg, clock=lambda: self.now)
            self._responses(payload)
            with self.assertRaises(BrokerDataError) as caught:
                reader.get_quote("RELIANCE")
            self.assertNotIn(self.cfg.upstox_access_token, str(caught.exception))
            self.assertFalse(reader.is_authentication_verified())

    def test_http_auth_rate_limit_and_server_errors_close_response_resources(self):
        import io
        import urllib.error
        import traceback
        for code, category in ((401, "AUTH_FAILURE"), (403, "FORBIDDEN"), (429, "RATE_LIMIT"), (503, "HTTP_ERROR")):
            body = io.BytesIO(b"Authorization: Bearer OFFLINE_ACCESS_SECRET")
            with urllib.error.HTTPError("https://api.upstox.com", code, "OFFLINE_ACCESS_SECRET", {}, body) as error:
                self._responses(error)
                with self.subTest(code=code), self.assertRaises(BrokerDataError) as caught:
                    self.adapter.get_quote("RELIANCE")
                self.assertEqual(caught.exception.error_category, category)
                self.assertTrue(body.closed)
                rendered = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn(self.cfg.upstox_access_token, rendered)

    def test_timeout_and_unexpected_transport_exception_have_no_raw_cause_output(self):
        import traceback
        for error in (TimeoutError("OFFLINE_ACCESS_SECRET"), RuntimeError("Authorization: Bearer OFFLINE_ACCESS_SECRET")):
            self._responses(error)
            with self.assertRaises(BrokerDataError) as caught:
                self.adapter.get_quote("RELIANCE")
            self.assertEqual(caught.exception.error_category, "NETWORK_API_FAILURE")
            self.assertNotIn(self.cfg.upstox_access_token, "".join(traceback.format_exception(caught.exception)))

    def test_authentication_requires_response_and_is_invalidated_on_token_change_or_401(self):
        import urllib.error
        scanner = MultiBrokerScanner(self.cfg, clock=lambda: self.now)
        engine = IntradayBotEngine(self.cfg, broker_scanner=scanner, clock=lambda: self.now)
        self.addCleanup(engine.close)
        self.assertFalse(engine.get_broker_status()["auth_verified"])
        self.assertEqual(engine.get_broker_status()["connection_state"], "CONFIGURED_UNVERIFIED")
        reader = scanner.get_active_adapter()
        self._responses(self._quote())
        reader.get_quote("RELIANCE")
        self.assertTrue(engine.get_broker_status()["auth_verified"])
        self.assertEqual(engine.get_broker_status()["connection_state"], "CONNECTED_VERIFIED")
        self.cfg.upstox_access_token = "OTHER_OFFLINE_TOKEN"
        self.assertFalse(reader.is_authentication_verified())
        self.assertFalse(engine.get_broker_status()["auth_verified"])
        self._responses(self._quote())
        reader.get_quote("RELIANCE")
        with urllib.error.HTTPError("https://api.upstox.com", 401, "Unauthorized", {}, None) as error:
            self._responses(error)
            with self.assertRaises(BrokerDataError):
                reader.get_quote("RELIANCE")
        self.assertFalse(reader.is_authentication_verified())

    def test_diagnostic_success_has_only_two_read_requests_and_no_side_effects(self):
        from contextlib import ExitStack
        targets = ("scanner_engine.IntradayBotEngine.run_single_scan", "scanner_engine.MarketScanScheduler.start",
                   "telegram_bot.TelegramSignalDispatcher.send_signal", "storage.SQLitePersistenceStore",
                   "readiness_policy._record_completed_diagnostic", "brokers.UpstoxV2Adapter.get_option_chain")
        self._responses(self._quote(), self._candles())
        with ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=AssertionError("Forbidden diagnostic side effect"))) for target in targets]
            report = self._diagnostic()
        self.assertEqual(report["overall_status"], "PASS", report)
        self.assertEqual(report["exit_code"], 0)
        self.assertFalse(report["readiness_receipt_issued"])
        self.assertFalse(report["historical_replay_allowed"])
        self.assertFalse(report["data_persisted"])
        self.assertEqual(self.transport.call_count, 2)
        paths = [call.args[0].full_url for call in self.transport.call_args_list]
        self.assertIn("/market-quote/quotes?", paths[0])
        self.assertIn("/historical-candle/intraday/", paths[1])
        for guard in guards:
            guard.assert_not_called()
        sample = report["checks"]["candles"]["completed_sample"]
        self.assertEqual([b["timestamp"] for b in sample], ["2026-10-16 10:25:00", "2026-10-16 10:30:00"])
        self.assertEqual(report["checks"]["candles"]["incomplete_bars_excluded"], 1)

    def test_diagnostic_missing_credentials_or_unsafe_configuration_never_requests(self):
        for key, value in (("upstox_access_token", "your_token"), ("active_broker", "paper_sim"),
                           ("telegram_dry_run", False), ("enable_background_scheduler", True)):
            original = getattr(self.cfg, key)
            setattr(self.cfg, key, value)
            try:
                report = self._diagnostic()
                self.assertEqual(report["checks"]["configuration"]["status"], "BLOCKED")
                self.assertEqual(report["exit_code"], 1)
            finally:
                setattr(self.cfg, key, original)
        self.transport.assert_not_called()

    def test_diagnostic_untrusted_or_noninitial_instrument_is_blocked_before_network(self):
        self.assertEqual(self._diagnostic(symbol="NIFTY")["checks"]["instrument"]["status"], "BLOCKED")
        self.cfg.equity_watchlist[0] = dict(self.cfg.equity_watchlist[0], upstox_key="NSE_EQ|WRONG")
        self.assertEqual(self._diagnostic()["checks"]["instrument"]["status"], "BLOCKED")
        self.transport.assert_not_called()

    def test_diagnostic_auth_failure_stops_without_candle_request(self):
        import urllib.error
        with urllib.error.HTTPError("https://api.upstox.com", 401, "OFFLINE_ACCESS_SECRET", {}, None) as error:
            self._responses(error)
            report = self._diagnostic()
        self.assertEqual(report["checks"]["authentication"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(self.transport.call_count, 1)

    def test_diagnostic_missing_quote_timestamp_stays_blocked(self):
        quote = self._quote()
        del quote["data"]["NSE_EQ:RELIANCE"]["timestamp"]
        self._responses(quote)
        report = self._diagnostic()
        self.assertEqual(report["checks"]["quote"]["status"], "BLOCKED")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(self.transport.call_count, 1)

    def test_diagnostic_old_quote_timestamp_stops_before_candles(self):
        self._responses(self._quote(timestamp="2026-10-16T09:35:00+05:30"))
        report = self._diagnostic()
        self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(self.transport.call_count, 1)

    def test_diagnostic_invalid_candle_times_gaps_order_prices_and_staleness_fail(self):
        import copy
        for kind in ("timestamp", "naive", "gap", "order", "price", "stale", "incomplete_only"):
            payload = copy.deepcopy(self._candles())
            rows = payload["data"]["candles"]
            if kind == "timestamp": rows[1][0] = "INVALID"
            elif kind == "naive": rows[1][0] = "2026-10-16 10:34:00"
            elif kind == "gap": del rows[3]
            elif kind == "order": rows[2], rows[3] = rows[3], rows[2]
            elif kind == "price": rows[2][2] = -1
            elif kind == "stale":
                payload["data"]["candles"] = [[r[0].replace("10:", "09:"), *r[1:]] for r in rows]
            else: payload["data"]["candles"] = rows[:1]
            self._responses(self._quote(), payload)
            with self.subTest(kind=kind):
                report = self._diagnostic()
                self.assertEqual(report["checks"]["candles"]["status"], "FAIL", report)
                self.assertEqual(report["exit_code"], 1)

    def test_diagnostic_response_identity_mismatch_fails_without_replacing_it(self):
        self._responses(self._quote(), self._candles(instrument_key="NSE_EQ|WRONG"))
        report = self._diagnostic()
        self.assertEqual(report["checks"]["candles"]["status"], "FAIL")

    def test_diagnostic_missing_identity_echo_is_disclosed_without_upgrading_evidence(self):
        quote = self._quote()
        del quote["data"]["NSE_EQ:RELIANCE"]["instrument_token"], quote["data"]["NSE_EQ:RELIANCE"]["symbol"]
        self._responses(quote, self._candles())
        report = self._diagnostic()
        self.assertEqual(report["checks"]["quote"]["response_binding"], "REQUEST_BOUND_NO_ECHO")
        self.assertEqual(report["checks"]["candles"]["response_binding"], "REQUEST_BOUND_NO_ECHO")
        self.assertFalse(report["historical_replay_allowed"])

    def test_diagnostic_does_not_trust_preexisting_authentication_after_failed_read(self):
        self._responses(self._quote())
        self.adapter.get_quote("RELIANCE")
        self._responses(TimeoutError("OFFLINE_ACCESS_SECRET"))
        self.assertEqual(self._diagnostic()["checks"]["authentication"]["status"], "FAIL")

    def test_cli_json_redaction_and_failure_exit_without_diagnostic_persistence(self):
        import io
        from upstox_diagnostics import main, run_upstox_diagnostics
        output = io.StringIO()
        self._responses(TimeoutError("Authorization: Bearer OFFLINE_ACCESS_SECRET OFFLINE_API_SECRET"))
        with patch("upstox_diagnostics.run_upstox_diagnostics", side_effect=lambda **kw: run_upstox_diagnostics(
                self.cfg, self.adapter, clock=lambda: self.now, **kw)), patch("sys.stdout", output), \
                patch.object(SQLitePersistenceStore, "_save_live_acceptance_evidence") as persist, \
                self.assertNoLogs("tradepulse", level="WARNING"):
            code = main(["--symbol", "RELIANCE", "--json"])
        self.assertEqual(code, 1)
        for secret in (self.cfg.upstox_access_token, self.cfg.upstox_api_key):
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(secret, str(self.adapter.last_error_message))
        self.assertFalse(json.loads(output.getvalue())["data_persisted"])
        persist.assert_not_called()

    def test_option_expiry_errors_and_encoded_secret_values_are_sanitized(self):
        from brokers import sanitize_broker_message
        import urllib.parse
        import traceback
        self.cfg.upstox_access_token = "OFFLINE/ACCESS+SECRET"
        self._responses(dict(status="success", data=[dict(expiry=self.cfg.upstox_access_token)]))
        with self.assertRaises(BrokerDataError) as caught:
            self.adapter.get_expiry_list("NIFTY")
        self.assertNotIn(self.cfg.upstox_access_token, "".join(traceback.format_exception(caught.exception)))
        text = sanitize_broker_message(self.cfg, urllib.parse.quote(self.cfg.upstox_access_token, safe=""))
        self.assertEqual(text, "[REDACTED]")

    def test_market_data_transport_rejects_trading_paths_without_network(self):
        for path in ("/order/place", "/order/modify", "/order/cancel", "/gtt", "/user/profile"):
            with self.assertRaises(BrokerDataError):
                self.adapter._request_json(path)
        self.transport.assert_not_called()

    def test_diagnostic_rechecks_quote_age_after_candle_request(self):
        from datetime import timedelta
        original = self.adapter.get_intraday_candles
        def delayed(*args, **kwargs):
            candles = original(*args, **kwargs)
            self.now += timedelta(seconds=70)
            return candles
        self._responses(self._quote(), self._candles())
        with patch.object(self.adapter, "get_intraday_candles", side_effect=delayed):
            report = self._diagnostic()
        self.assertEqual(report["checks"]["quote"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "PASS")

    def test_prior_session_close_does_not_pass_current_session_acceptance(self):
        from datetime import timedelta
        start = datetime(2026, 10, 16, 15, 25, tzinfo=IST)
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=IST)
        rows = [[(start+timedelta(minutes=i)).isoformat(), 2940, 2960, 2930, 2950, 100] for i in range(5)]
        self._responses(self._quote(timestamp=self.now.isoformat()), dict(status="success", data=dict(candles=rows[::-1])))
        report = self._diagnostic()
        self.assertEqual(report["checks"]["candles"]["status"], "BLOCKED")
        self.assertEqual(report["exit_code"], 1)

    def test_cli_success_and_missing_explicit_symbol_exit_codes(self):
        import io
        from upstox_diagnostics import main, run_upstox_diagnostics
        output = io.StringIO()
        self._responses(self._quote(), self._candles())
        with patch("upstox_diagnostics.run_upstox_diagnostics", side_effect=lambda **kw: run_upstox_diagnostics(
                self.cfg, self.adapter, clock=lambda: self.now, **kw)), patch("sys.stdout", output):
            self.assertEqual(main(["--symbol", "RELIANCE", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["overall_status"], "PASS")
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([])
        self.assertEqual(caught.exception.code, 2)

    def test_root_gitignore_excludes_secrets_and_preserves_templates(self):
        import tempfile
        from pathlib import Path
        ignore = Path(__file__).resolve().parent.parent / '.gitignore'
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "--quiet", directory], check=True, capture_output=True)
            (Path(directory)/'.gitignore').write_bytes(ignore.read_bytes())
            cases = [".env", "indian_fo_signal_bot_v1/.env", "nested/.env.production", "nested/.env.local",
                     "nested/config.local.json", "nested/upstox_credentials.json", "nested/.secrets/session.json",
                     "nested/credentials.json", "nested/secrets.json", "nested/private.key",
                     "indian_fo_signal_bot_v1/.env.example", "nested/.env.production.example"]
            response = subprocess.run(["git", "-C", directory, "check-ignore", "--no-index", "-z", "--stdin"],
                input=("\0".join(cases)+"\0").encode(), capture_output=True, check=True)
            self.assertEqual(set(filter(None, response.stdout.decode().split("\0"))), set(cases[:-2]))

    def test_duplicate_json_fields_and_oversized_responses_fail_closed(self):
        for raw in (b'{"status":"error","status":"success","data":{}}', b" " * (8*1024*1024+1)):
            self._responses(raw)
            with self.assertRaises(BrokerDataError):
                self.adapter.get_quote("RELIANCE")
        self.assertFalse(self.adapter.is_authentication_verified())


class TestUpstoxHTTPErrorDetails(unittest.TestCase):
    """Real urllib HTTPError/response lifecycles with synthetic, offline bodies."""

    setUp = TestUpstoxReadOnlyReadiness.setUp
    _quote = TestUpstoxReadOnlyReadiness._quote
    _candles = TestUpstoxReadOnlyReadiness._candles
    _responses = TestUpstoxReadOnlyReadiness._responses
    _diagnostic = TestUpstoxReadOnlyReadiness._diagnostic

    def _body(self, **detail):
        return json.dumps(dict(status="error", errors=[detail]), ensure_ascii=False).encode()

    def _failure(self, body, status=403, *, response=None):
        import io
        import urllib.error
        response = response if response is not None else io.BytesIO(body)
        with urllib.error.HTTPError("https://api.upstox.com/v2/market-quote/quotes",
                                    status, "OFFLINE_ACCESS_SECRET", {}, response) as error:
            self._responses(error)
            with self.assertRaises(BrokerDataError) as caught:
                self.adapter.get_quote("RELIANCE")
            self.assertTrue(response.closed)
        return caught.exception

    def test_all_http_categories_retain_status_and_safe_detail(self):
        for status, category in ((400, "HTTP_ERROR"), (401, "AUTH_FAILURE"), (403, "FORBIDDEN"),
                                 (404, "HTTP_ERROR"), (429, "RATE_LIMIT"), (500, "HTTP_ERROR"),
                                 (418, "HTTP_ERROR")):
            with self.subTest(status=status):
                exc = self._failure(self._body(error_code="UDAPI100050", message="Invalid token used to access API"), status)
                self.assertEqual(exc.error_category, category)
                self.assertEqual(exc.http_status, status)
                self.assertEqual(exc.provider_error_code, "UDAPI100050")
                self.assertEqual(exc.provider_error_message, "Invalid token used to access API")
                self.assertIn(f"HTTP {status}", str(exc))
                self.assertIn("UDAPI100050", self.adapter.last_error_message)
                self.assertEqual(self.adapter._authorized_reads, 0)
                self.assertFalse(self.adapter.is_connection_verified())

    def test_documented_snake_and_deprecated_camel_code_schemas(self):
        for key in ("error_code", "errorCode"):
            with self.subTest(key=key):
                exc = self._failure(self._body(**{key: "UDAPI100067", "message": "Endpoint not permitted"}))
                self.assertEqual(exc.provider_error_code, "UDAPI100067")
                self.assertEqual(exc.provider_error_message, "Endpoint not permitted")

    def test_missing_code_or_message_retains_only_valid_fields(self):
        for detail, expected in ((dict(message="Access denied"), {"provider_error_message": "Access denied"}),
                                 (dict(error_code="UDAPI100050"), {"provider_error_code": "UDAPI100050"}),
                                 ({}, {})):
            with self.subTest(fields=list(detail)):
                exc = self._failure(self._body(**detail))
                actual = {key: getattr(exc, key) for key in ("provider_error_code", "provider_error_message") if hasattr(exc, key)}
                self.assertEqual(actual, expected)

    def test_empty_malformed_html_and_invalid_encoding_keep_original_failure(self):
        for body in (b"", b"not json", b"<html>OFFLINE_ACCESS_SECRET</html>", b"\xff", b"null", b"[]"):
            with self.subTest(body_length=len(body)):
                exc = self._failure(body)
                self.assertEqual(exc.error_category, "FORBIDDEN")
                self.assertEqual(exc.http_status, 403)
                self.assertFalse(hasattr(exc, "provider_error_message"))

    def test_unexpected_nested_and_duplicate_json_fields_are_not_echoed(self):
        payloads = [dict(status="error"), dict(status="error", errors={"message": "PRIVATE"}),
                    dict(status="error", errors=[None]), dict(status="error", errors=[[{"message": "PRIVATE"}]]),
                    dict(status="error", errors=[dict(error_code={}, message=["PRIVATE"])]),
                    dict(status="success", errors=[dict(message="PRIVATE")]),
                    dict(error=dict(error_code="UDAPI100050", message="PRIVATE"))]
        bodies = [json.dumps(p).encode() for p in payloads]
        bodies += [b'{"status":"error","errors":[{"message":"PRIVATE","message":"PRIVATE"}]}',
                   b'{"status":"error","errors":[' + b'['*1100 + b'0' + b']'*1100 + b']}']
        for body in bodies:
            with self.subTest(body_length=len(body)):
                exc = self._failure(body)
                self.assertFalse(hasattr(exc, "provider_error_message"))
                self.assertNotIn("PRIVATE", str(exc))

    def test_unexpected_scalar_types_and_untrusted_codes_are_omitted(self):
        for value in (None, True, 123, [], {}, "", "PRIVATE_CODE", "UDAPI123\nPASS", "UDAPI"+"1"*40):
            with self.subTest(value_type=type(value).__name__):
                exc = self._failure(self._body(error_code=value, message=value if not isinstance(value, str) else None))
                self.assertFalse(hasattr(exc, "provider_error_code"))
                self.assertFalse(hasattr(exc, "provider_error_message"))

    def test_error_body_read_is_bounded_and_oversize_detail_is_discarded(self):
        import io
        class Response(io.BytesIO):
            def read(inner, size=-1):
                self.assertGreater(size, 0)
                self.assertLessEqual(size, 8193)
                return super().read(size)
        response = Response(self._body(error_code="UDAPI100050", message="x"*20000))
        exc = self._failure(b"", response=response)
        self.assertEqual(exc.http_status, 403)
        self.assertFalse(hasattr(exc, "provider_error_message"))

    def test_exact_body_boundary_is_accepted_and_next_byte_is_rejected(self):
        body = self._body(error_code="UDAPI100050", message="Access denied")
        body += b" "*(8192-len(body))
        self.assertEqual(self._failure(body).provider_error_message, "Access denied")
        self.assertFalse(hasattr(self._failure(body+b" "), "provider_error_message"))

    def test_read_failures_close_resources_and_preserve_http_status(self):
        import io
        for failure in (OSError, RuntimeError, UnicodeError):
            class Response(io.BytesIO):
                def read(inner, size=-1):
                    raise failure("OFFLINE_ACCESS_SECRET")
            with self.subTest(failure=failure.__name__):
                exc = self._failure(b"", response=Response(b""))
                self.assertEqual(exc.error_category, "FORBIDDEN")
                self.assertEqual(exc.http_status, 403)
                self.assertNotIn("OFFLINE_ACCESS_SECRET", str(exc))

    def test_close_failure_cannot_replace_http_failure_with_raw_exception(self):
        import io
        import urllib.error
        response = io.BytesIO(self._body(message="Access denied"))
        error = urllib.error.HTTPError("https://api.upstox.com", 403, "Forbidden", {}, response)
        original_close = error.close
        def close_then_fail():
            original_close()
            raise RuntimeError("OFFLINE_ACCESS_SECRET")
        with patch.object(error, "close", side_effect=close_then_fail):
            self._responses(error)
            with self.assertRaises(BrokerDataError) as caught:
                self.adapter.get_quote("RELIANCE")
        error.close()
        self.assertTrue(response.closed)
        self.assertEqual(caught.exception.http_status, 403)
        self.assertNotIn("OFFLINE_ACCESS_SECRET", str(caught.exception))

    def test_configured_secrets_and_encoded_variants_are_absent_everywhere(self):
        import urllib.parse
        import traceback
        fields = ("upstox_access_token", "upstox_api_key", "angel_api_key", "angel_pin", "angel_totp_secret",
                  "dhan_access_token", "telegram_bot_token", "gemini_api_key", "angel_client_code",
                  "dhan_client_id", "telegram_chat_id")
        for index, field in enumerate(fields):
            setattr(self.cfg, field, f"OFFLINE/{index}+SECRET ONLY")
        secrets = [getattr(self.cfg, field) for field in fields]
        variants = [variant for secret in secrets for variant in
                    (secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret))]
        message = "Denied " + " | ".join(variants)
        exc = self._failure(self._body(error_code="UDAPI100050", message=message))
        rendered = "".join(traceback.format_exception(exc)) + str(self.adapter.last_error_message)
        import io
        import urllib.error
        with urllib.error.HTTPError("https://api.upstox.com", 403, "Forbidden", {}, io.BytesIO(self._body(message=message))) as error:
            self._responses(error)
            rendered += json.dumps(self._diagnostic())
        for variant in variants:
            self.assertNotIn(variant, rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_bearer_urls_headers_and_personal_fields_are_not_disclosed(self):
        messages = ("Denied Bearer UNCONFIGURED_BEARER", "Denied https://example.test/?secret=URL_PRIVATE",
                    "Denied contact@private.test 9876543210", "Authorization: Basic PRIVATE_HEADER",
                    "headers: {private: PRIVATE_HEADER}", "client_id=PRIVATE_ACCOUNT", "name: PRIVATE_PERSON",
                    "{'headers': {'x-private': 'PRIVATE_HEADER'}}",
                    "{'Authorization': 'Basic PRIVATE_HEADER'}", "<urllib.request.Request object PRIVATE_HEADER>")
        for message in messages:
            with self.subTest(kind=message.split()[0]):
                exc = self._failure(self._body(message=message, invalid_value="UNRELATED_PRIVATE",
                                                property_path="UNRELATED_PRIVATE", email="UNRELATED_PRIVATE"))
                text = str(exc)
                for private in ("UNCONFIGURED_BEARER", "URL_PRIVATE", "contact@private.test", "9876543210",
                                "PRIVATE_HEADER", "PRIVATE_ACCOUNT", "PRIVATE_PERSON", "UNRELATED_PRIVATE"):
                    self.assertNotIn(private, text)

    def test_unicode_control_characters_and_multiline_spoofing_are_bounded(self):
        import unicodedata
        message = "Access denied \u0939\u093f\u0902\u0926\u0940 \U0001f512 \x1b[31mrestricted\x1b[0m \u202e text\nOVERALL_STATUS: PASS\nAuthorization: SECRET"
        exc = self._failure(self._body(message=message))
        text = exc.provider_error_message
        self.assertIn("\u0939\u093f\u0902\u0926\u0940", text)
        self.assertIn("\U0001f512", text)
        self.assertNotIn("OVERALL_STATUS", text)
        self.assertFalse(any(unicodedata.category(ch).startswith("C") for ch in text))
        self.assertLessEqual(len(text), 240)

    def test_secret_redaction_happens_before_message_length_cap(self):
        self.cfg.upstox_access_token = "OFFLINE_" + "S"*300
        exc = self._failure(self._body(message="Denied " + self.cfg.upstox_access_token + "x"*500))
        self.assertLessEqual(len(exc.provider_error_message), 240)
        self.assertNotIn("OFFLINE_", exc.provider_error_message)
        self.assertIn("[REDACTED]", exc.provider_error_message)

    def test_sanitizer_failures_and_invalid_outputs_fail_closed(self):
        import traceback
        for bad in (None, 123, RuntimeError("OFFLINE_ACCESS_SECRET")):
            options = {"side_effect": bad} if isinstance(bad, Exception) else {"return_value": bad}
            with self.subTest(kind=type(bad).__name__), patch("brokers.sanitize_broker_message", **options):
                exc = self._failure(self._body(error_code="UDAPI100050", message="OFFLINE_ACCESS_SECRET"))
            self.assertEqual(exc.error_category, "FORBIDDEN")
            self.assertEqual(exc.http_status, 403)
            self.assertNotIn("OFFLINE_ACCESS_SECRET", "".join(traceback.format_exception(exc)))
            self.assertFalse(hasattr(exc, "provider_error_message"))

    def test_401_and_403_clear_prior_auth_without_incrementing_reads(self):
        for status in (401, 403):
            self._responses(self._quote())
            self.adapter.get_quote("RELIANCE")
            self.assertTrue(self.adapter.is_connection_verified())
            before = self.adapter._authorized_reads
            exc = self._failure(b"", status)
            self.assertEqual(exc.http_status, status)
            self.assertIsNone(self.adapter.authenticated_at_ist)
            self.assertIsNone(self.adapter._authorized_token_sha256)
            self.assertFalse(self.adapter.is_authentication_verified())
            self.assertFalse(self.adapter.is_connection_verified())
            self.assertEqual(self.adapter._authorized_reads, before)

    def test_other_http_failures_preserve_prior_auth_but_not_connection(self):
        for status in (400, 404, 429, 500, 418):
            self._responses(self._quote())
            self.adapter.get_quote("RELIANCE")
            before = self.adapter._authorized_reads
            self._failure(b"", status)
            self.assertTrue(self.adapter.is_authentication_verified())
            self.assertFalse(self.adapter.is_connection_verified())
            self.assertEqual(self.adapter._authorized_reads, before)

    def test_failed_quote_json_retains_detail_stops_candles_and_keeps_gates(self):
        import io
        import urllib.error
        from upstox_diagnostics import main, run_upstox_diagnostics
        with urllib.error.HTTPError("https://api.upstox.com", 403, "Forbidden", {},
                                    io.BytesIO(self._body(errorCode="UDAPI100067", message="Endpoint not permitted"))) as error:
            self._responses(error)
            out = io.StringIO()
            with patch("upstox_diagnostics.run_upstox_diagnostics", side_effect=lambda **kw: run_upstox_diagnostics(
                    self.cfg, self.adapter, clock=lambda: self.now, **kw)), patch("sys.stdout", out):
                self.assertEqual(main(["--symbol", "RELIANCE", "--json"]), 1)
        report = json.loads(out.getvalue())
        self.assertEqual(report["checks"]["quote"]["http_status"], 403)
        self.assertEqual(report["checks"]["quote"]["provider_error_code"], "UDAPI100067")
        self.assertEqual(report["checks"]["quote"]["provider_error_message"], "Endpoint not permitted")
        self.assertEqual(report["checks"]["authentication"]["status"], "FAIL")
        self.assertEqual(report["checks"]["candles"]["status"], "NOT_TESTED")
        self.assertEqual(self.transport.call_count, 1)
        for flag in ("historical_replay_allowed", "readiness_receipt_issued", "data_persisted"):
            self.assertFalse(report[flag])

    def test_successful_quote_then_http_candle_failure_retains_detail_without_acceptance(self):
        import io
        import urllib.error
        with urllib.error.HTTPError("https://api.upstox.com", 429, "Rate limited", {},
                                    io.BytesIO(self._body(error_code="UDAPI10005", message="Too many requests"))) as error:
            self._responses(self._quote(), error)
            report = self._diagnostic()
        self.assertEqual(report["checks"]["quote"]["status"], "PASS")
        self.assertEqual(report["checks"]["authentication"]["status"], "PASS")
        self.assertEqual(report["checks"]["candles"]["http_status"], 429)
        self.assertEqual(report["checks"]["candles"]["provider_error_code"], "UDAPI10005")
        self.assertEqual(report["overall_status"], "FAIL")
        self.assertEqual(report["exit_code"], 1)
        self.assertFalse(report["historical_replay_allowed"])
        self.assertFalse(report["readiness_receipt_issued"])

    def test_diagnostic_revalidates_exception_fields_without_stringifying_raw_errors(self):
        from upstox_diagnostics import _safe_http_error_details
        exc = BrokerDataError("OFFLINE_ACCESS_SECRET")
        for status in (None, True, "403", {}, 99, 600):
            exc.http_status = status
            self.assertEqual(_safe_http_error_details(self.cfg, exc), {})
        exc.http_status = 403
        exc.provider_error_message = "Denied OFFLINE_ACCESS_SECRET\nOVERALL_STATUS: PASS"
        exc.provider_error_code = {"secret": "OFFLINE_ACCESS_SECRET"}
        detail = _safe_http_error_details(self.cfg, exc)
        self.assertEqual(detail, dict(http_status=403, provider_error_message="Denied [REDACTED]", provider_cause="NOT_ESTABLISHED"))
        with patch("upstox_diagnostics.sanitize_upstox_error_detail", side_effect=RuntimeError("OFFLINE_ACCESS_SECRET")):
            self.assertEqual(_safe_http_error_details(self.cfg, exc), {})

    def test_only_first_error_code_message_are_extracted_not_unrelated_fields(self):
        body = json.dumps(dict(status="error", errors=[dict(error_code="UDAPI100050", message="Access denied",
                    invalid_value="PRIVATE", property_path="PRIVATE", headers="PRIVATE", user={"name": "PRIVATE"}),
                    dict(error_code="UDAPI100016", message="PRIVATE")], data={"token": "PRIVATE"})).encode()
        exc = self._failure(body)
        self.assertEqual(exc.provider_error_code, "UDAPI100050")
        self.assertEqual(exc.provider_error_message, "Access denied")
        self.assertNotIn("PRIVATE", str(exc))
        self.assertFalse(hasattr(exc, "headers"))


class TestConfigurationPreflight(unittest.TestCase):
    """Synthetic dotenv fixtures only; the production loader retains its precedence."""

    def _effective(self, local=None, *, parent=None, overrides=None):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            # Execute a temporary module copy so deterministic discovery never
            # reads the user's real project .env during configuration tests.
            import shutil
            shutil.copyfile(Path(__file__).with_name("config.py"), project / "config.py")
            if parent is not None:
                (root / '.env').write_bytes(parent.encode())
            if local is not None:
                (project / '.env').write_bytes(local.encode())
            env = os.environ.copy()
            for key in _test_config_defaults:
                env.pop(key, None)
            env.update(overrides or {})
            code = ("import sys,json; sys.path.insert(0,sys.argv[1]); from config import BotConfig; "
                    "c=BotConfig(); print(json.dumps({'active_broker':c.active_broker,"
                    "'telegram_dry_run':c.telegram_dry_run,'enable_background_scheduler':c.enable_background_scheduler}))")
            completed = subprocess.run([sys.executable, '-B', '-c', code, str(project)],
                                       cwd=project, env=env, capture_output=True, text=True, check=True)
            return json.loads(completed.stdout)

    def test_project_template_still_selects_paper_sim_until_locally_configured(self):
        example = Path(__file__).with_name('.env.example').read_text(encoding='utf-8')
        effective = self._effective(example)
        self.assertEqual(effective, dict(active_broker="paper_sim", telegram_dry_run=True, enable_background_scheduler=False))

    def test_project_root_values_load_without_parent_fallback(self):
        local = "ACTIVE_BROKER=upstox\nTELEGRAM_DRY_RUN=true\nENABLE_BACKGROUND_SCHEDULER=false\n"
        effective = self._effective(local, parent="ACTIVE_BROKER=angelone\n")
        self.assertEqual(effective, dict(active_broker="upstox", telegram_dry_run=True, enable_background_scheduler=False))

    def test_parent_upstox_file_cannot_override_project_paper_sim_file(self):
        self.assertEqual(self._effective("ACTIVE_BROKER=paper_sim\n", parent="ACTIVE_BROKER=upstox\n")["active_broker"], "paper_sim")

    def test_missing_project_env_does_not_silently_load_parent_credentials(self):
        result = self._effective(parent="ACTIVE_BROKER=upstox\n")
        self.assertEqual(result["active_broker"], "paper_sim")

    def test_process_environment_takes_precedence_over_file(self):
        result = self._effective("ACTIVE_BROKER=upstox\nTELEGRAM_DRY_RUN=true\nENABLE_BACKGROUND_SCHEDULER=false\n",
            overrides={"ACTIVE_BROKER": "paper_sim", "TELEGRAM_DRY_RUN": "false", "ENABLE_BACKGROUND_SCHEDULER": "true"})
        self.assertEqual(result, dict(active_broker="paper_sim", telegram_dry_run=False, enable_background_scheduler=True))

    def test_duplicate_keys_keep_first_value_and_quoted_values_are_supported(self):
        result = self._effective("ACTIVE_BROKER='upstox'\nACTIVE_BROKER=paper_sim\n")
        self.assertEqual(result["active_broker"], "upstox")

    def test_malformed_broker_values_are_not_silently_promoted(self):
        import tempfile
        from config import _load_dotenv, ConfigValidationError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fixture.env'
            path.write_text("# offline fixture\nMALFORMED LINE\nACTIVE_BROKER=upstox # inline comment\n", encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ConfigValidationError):
                    _load_dotenv(str(path))
                self.assertNotIn('ACTIVE_BROKER', os.environ)

    def test_explicit_loader_missing_file_preserves_existing_environment(self):
        import tempfile
        from config import _load_dotenv
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ACTIVE_BROKER': 'dhan'}, clear=True):
            _load_dotenv(str(Path(directory)/'missing.env'))
            self.assertEqual(os.environ['ACTIVE_BROKER'], 'dhan')

    def test_preflight_returns_effective_settings_without_adapter_or_receipt(self):
        from upstox_diagnostics import run_upstox_diagnostics
        cfg = BotConfig(active_broker='upstox', upstox_access_token='OFFLINE_ONLY_TOKEN',
                        telegram_dry_run=True, enable_background_scheduler=False)
        with patch('upstox_diagnostics.UpstoxV2Adapter', side_effect=AssertionError('No adapter in preflight')), \
                patch('urllib.request.urlopen', side_effect=AssertionError('No network in preflight')), \
                patch('storage.SQLitePersistenceStore', side_effect=AssertionError('No diagnostic persistence')), \
                patch('readiness_policy._record_completed_diagnostic', side_effect=AssertionError('No receipt')):
            report = run_upstox_diagnostics(cfg, symbol='RELIANCE', config_only=True)
        self.assertEqual(report['effective_configuration'], dict(active_broker='upstox', telegram_dry_run=True, enable_background_scheduler=False))
        self.assertTrue(report['configuration_ready'])
        self.assertEqual(report['overall_status'], 'NOT_TESTED')
        self.assertEqual(report['exit_code'], 0)
        for name in ('authentication', 'quote', 'candles'):
            self.assertEqual(report['checks'][name]['status'], 'NOT_TESTED')
        self.assertFalse(report['readiness_receipt_issued'])
        self.assertFalse(report['historical_replay_allowed'])

    def test_preflight_cli_refuses_wrong_provider_missing_token_and_unsafe_flags(self):
        import io
        from upstox_diagnostics import main
        base = dict(active_broker='upstox', upstox_access_token='OFFLINE_ONLY_TOKEN',
                    telegram_dry_run=True, enable_background_scheduler=False)
        for changes in (dict(active_broker='paper_sim'), dict(upstox_access_token=''),
                        dict(telegram_dry_run=False), dict(enable_background_scheduler=True)):
            cfg = BotConfig(**dict(base, **changes))
            out = io.StringIO()
            with self.subTest(changes=list(changes)), patch('upstox_diagnostics.BotConfig', return_value=cfg), \
                    patch('sys.stdout', out), patch('urllib.request.urlopen', side_effect=AssertionError('No preflight requests')):
                self.assertEqual(main(['--symbol', 'RELIANCE', '--check-config', '--json']), 1)
            self.assertFalse(json.loads(out.getvalue())['configuration_ready'])
            self.assertNotIn('OFFLINE_ONLY_TOKEN', out.getvalue())

    def test_preflight_cli_success_never_claims_live_success(self):
        import io
        from upstox_diagnostics import main
        cfg = BotConfig(active_broker='upstox', upstox_access_token='OFFLINE_ONLY_TOKEN',
                        telegram_dry_run=True, enable_background_scheduler=False)
        out = io.StringIO()
        with patch('upstox_diagnostics.BotConfig', return_value=cfg), patch('sys.stdout', out), \
                patch('urllib.request.urlopen', side_effect=AssertionError('No requests')):
            self.assertEqual(main(['--symbol', 'RELIANCE', '--check-config', '--json']), 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report['scope'], 'LOCAL_CONFIGURATION_PREFLIGHT')
        self.assertEqual(report['overall_status'], 'NOT_TESTED')
        self.assertFalse(report['data_persisted'])

    def test_invalid_broker_input_is_not_echoed_as_a_secret(self):
        from upstox_diagnostics import run_upstox_diagnostics
        cfg = BotConfig(active_broker='OFFLINE_SECRET_AS_INVALID_BROKER', upstox_access_token='OFFLINE_TOKEN')
        report = run_upstox_diagnostics(cfg, symbol='RELIANCE', config_only=True)
        self.assertEqual(report['effective_configuration']['active_broker'], 'INVALID')
        self.assertNotIn('OFFLINE_SECRET_AS_INVALID_BROKER', json.dumps(report))

    def test_offline_suite_ignores_local_dotenv_and_process_application_configuration(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory)/'.env'
            raw = b'ACTIVE_BROKER=upstox\nUPSTOX_ACCESS_TOKEN=LOCAL_FILE_CANARY\nDATABASE_URL=sqlite:///do_not_create.db\n'
            env_path.write_bytes(raw)
            env = dict(os.environ, ACTIVE_BROKER='upstox', UPSTOX_ACCESS_TOKEN='PROCESS_CANARY',
                       DATABASE_URL='sqlite:///do_not_create.db', ENABLE_BACKGROUND_SCHEDULER='true')
            code = ("import sys,json; sys.path.insert(0,sys.argv[1]); import test_bot; from config import BotConfig; "
                    "c=BotConfig(); print(json.dumps({'provider':c.active_broker,'memory':c.database_url==':memory:',"
                    "'token_empty':not c.upstox_access_token,'scheduler':c.enable_background_scheduler}))")
            result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).resolve().parent)],
                                    cwd=directory, env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), dict(provider='paper_sim', memory=True, token_empty=True, scheduler=False))
            self.assertEqual(env_path.read_bytes(), raw)
            self.assertFalse((Path(directory)/'do_not_create.db').exists())
            self.assertNotIn('PROCESS_CANARY', result.stdout+result.stderr)
            self.assertNotIn('LOCAL_FILE_CANARY', result.stdout+result.stderr)


def load_tests(loader, tests, pattern):
    """Include independent broker/contract regressions in the established command."""
    if pattern is None:  # Discovery loads these files itself; avoid duplicate cases.
        for module in ("test_angel_market_data", "test_market_data_contract", "test_phase4_market_data",
                       "test_phase4_e2e", "test_phase4_strategy", "test_phase5a_contracts",
                       "test_phase5a_provenance", "test_phase5a_paper", "test_phase5a_integration", "test_phase5b_forward",
                       "test_phase5c_recovery", "test_continuous_acceptance", "test_blocker_removal"):
            tests.addTests(loader.loadTestsFromName(module))
    return tests


if __name__ == "__main__":
    unittest.main(verbosity=2)
