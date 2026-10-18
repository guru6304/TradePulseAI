# Prompt for Google AI Studio Build Mode (`https://aistudio.google.com/apps`)

Copy and paste the prompt below into Google AI Studio Build Mode if you want the AI Studio Antigravity agent to extend or customize the web app in the cloud:

```text
Build a full-stack Indian Stock Market Intraday & F&O Trading Terminal inspired by TradeFinder.in and Order-Block.com with live Telegram Bot integration.
Target Universe:
1. Intraday Equity Cash/F&O NSE Stocks (RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS, SBIN, BAJFINANCE, LT, TATAMOTORS, AXISBANK, M&M, BHARTIARTL, TRENT, HAL, TATASTEEL).
2. F&O Index Derivatives strictly limited to NIFTY 50 (Lot size 75) and BANK NIFTY (Lot size 30).

Include 5 verified intraday strategies:
1. Order Block + BOS & Fair Value Gap (FVG) Retest (5m closed candles, S1 invalidation, T1/T2 liquidity targets)
2. Institutional VWAP Pullback + 20 EMA & Relative Volume Surge
3. Option Apex OI Shift Trap + PCR (Exclusively for NIFTY 50 & BANK NIFTY ATM/ITM Call/Put options)
4. 15-Minute Opening Range Breakout (ORB) + RVOL >= 1.6x & RSI Filter
5. Filtered Supertrend (10,3) Pullback + 200 EMA (blocking 09:15-09:45 and 11:30-13:30 IST chop zones)

Provide interactive tabs for:
- Live Signal Terminal (Bullish & Bearish boards + interactive 5m Order Block / VWAP chart)
- Nifty 50 & Bank Nifty F&O Option Apex (Live Option Chain OI buildup, PCR gauge, strike unwinding)
- Top 5 Strategy Comparison & Indian Statutory Friction Backtester (STT, NSE fees, GST, Brokerage)
- Broker API Hub (Angel One SmartAPI TOTP, DhanHQ v2 static token, Upstox v2 OAuth) & Live Telegram Bot Dispatcher
```
