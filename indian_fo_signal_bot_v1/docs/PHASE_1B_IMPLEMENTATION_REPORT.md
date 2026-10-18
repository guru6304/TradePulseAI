# TradePulse AI — Phase 1B Implementation Report (`PHASE_1B_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-16  
**Scope:** Phase 1B — Market Data Adapter Completion, Data Normalization & Integration Reliability  
**Input Artifact:** `indian_fo_signal_bot_phase1a.zip`  
**Output Artifact:** `indian_fo_signal_bot_phase1b.zip`


## A. Baseline Inspection & Phase 1A Test Results

### A.1 Phase 1A Archive File Tree (`indian_fo_signal_bot_phase1a.zip`)
Extracting `indian_fo_signal_bot_phase1a.zip` into `/tmp/phase1b_baseline/indian_fo_signal_bot_v1` verified 11 files (133,610 bytes uncompressed):

```text
indian_fo_signal_bot_v1/
├── .env.example                           (1,330 bytes)
├── AI_STUDIO_PROMPT.md                    (1,614 bytes)
├── README.md                              (2,200 bytes)
├── brokers.py                             (29,809 bytes)
├── config.py                              (6,151 bytes)
├── docs/
│   └── PHASE_1A_IMPLEMENTATION_REPORT.md  (25,427 bytes)
├── scanner_engine.py                      (5,165 bytes)
├── server.py                              (1,456 bytes)
├── strategies.py                          (29,769 bytes)
├── telegram_bot.py                        (4,378 bytes)
└── test_bot.py                            (26,311 bytes)
```

### A.2 Baseline Phase 1A Test Results Before Changes
Executing `python3 /tmp/phase1b_baseline/indian_fo_signal_bot_v1/test_bot.py -v` against the unmodified Phase 1A archive ran all 20 Phase 1A tests with **20 passed, 0 failed, 0 skipped** (`Ran 20 tests in 3.487s — OK`).

### A.3 Confirmed Phase 1A Carry-Over & Adapter Defects
1. **Hardcoded Simulation Dates (`brokers.py` L370–L371):** `SimulatedNSEAdapter.get_intraday_candles()` hardcoded `warmup_days = [date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]` and `session_day = date(2026, 10, 16)` instead of deriving session and warm-up dates from `self.clock`.
2. **Incomplete Timestamp Normalization (`strategies.py` L41–L70; `brokers.py` L214):** `parse_ist_timestamp()` only accepted `datetime` objects and string timestamps, whereas DhanHQ `/v2/charts/intraday` returns Unix epoch integers in `timestamp[]` (`brokers.py` L214 previously converted epoch integers to raw strings `str(timestamps[i])` like `"1328845020"`, which `parse_ist_timestamp()` rejected).
3. **Unconditional `is_complete=True` on Provider Candles (`brokers.py` L138, L220, L301):** Live adapters hardcoded `"is_complete": True` on every row returned by the provider without checking whether `bar_start + interval_min <= now_ist`.
4. **DhanHQ Option-Chain Unnormalized Output & Missing `Expiry` (`brokers.py` L236–L260):** `DhanHQAdapter.get_option_chain()` did not call `/v2/optionchain/expirylist`, omitted the required `"Expiry"` request field on `/v2/optionchain`, and returned raw Dhan JSON (`{"data": {"last_price": ..., "oc": {...}}}`) instead of the normalized strike schema consumed by `evaluate_option_apex_oi_shift()`.
5. **Upstox Invalid `"5minute"` v2 Interval & Missing Option Chain (`brokers.py` L286, L53):** `UpstoxV2Adapter.get_intraday_candles()` requested `/v2/historical-candle/intraday/{key}/5minute`, which fails on Upstox v2 (`UDAPI1020`: only `1minute` and `30minute` are valid on the v2 intraday route), and `UpstoxV2Adapter` did not implement `get_option_chain()`.
6. **Angel One Unvalidated Intervals & Unclear Option-Chain Error (`brokers.py` L53, L111):** `AngelOneSmartAPIAdapter` inherited a raw `NotImplementedError` for `get_option_chain()` and silently defaulted unknown intervals to `"FIVE_MINUTE"` and missing `angel_token` to `"2885"` (`RELIANCE`).
7. **Silent Defaulting to `RELIANCE` (`2885` / `INE002A01018`) Across Adapters (`brokers.py` L117, L189, L285, L366):** Missing instrument keys silently queried `RELIANCE`, and index/equity metadata mix-ups were not validated before sending HTTP requests.


## B. Official Broker API Verification

### B.1 DhanHQ API v2
- **Official Documentation URLs:**
  - Option Chain & Expiry List: [https://dhanhq.co/docs/v2/option-chain/](https://dhanhq.co/docs/v2/option-chain/)
  - Historical & Intraday Data: [https://dhanhq.co/docs/v2/historical-data/](https://dhanhq.co/docs/v2/historical-data/)
- **Authentication:** HTTP headers `access-token: <JWT>`, `client-id: <client_id>`, `Content-Type: application/json`, `Accept: application/json`.
- **Verified Endpoints & Intervals:**
  1. `POST /v2/charts/intraday`:
     - **Supported `interval` values:** `"1"`, `"5"`, `"15"`, `"25"`, `"60"` (minute intervals; max 90 days per poll).
     - **Request fields:** `securityId` (string), `exchangeSegment` (`"IDX_I"` for Nifty/BankNifty index, `"NSE_EQ"` for NSE cash equities), `instrument` (`"INDEX"` or `"EQUITY"`), `interval` (`"1"`, `"5"`, `"15"`, `"25"`, `"60"`), `oi` (boolean), `fromDate` (`"YYYY-MM-DD HH:MM:SS"`), `toDate` (`"YYYY-MM-DD HH:MM:SS"`).
     - **Response fields:** Parallel arrays `open[]`, `high[]`, `low[]`, `close[]`, `volume[]`, `timestamp[]` (Unix epoch seconds), `open_interest[]`.
  2. `POST /v2/optionchain/expirylist`:
     - **Request fields:** `{"UnderlyingScrip": int, "UnderlyingSeg": "IDX_I"}` (`13` for NIFTY 50, `25` for BANK NIFTY).
     - **Response fields:** `{"data": ["YYYY-MM-DD", ...], "status": "success"}`.
  3. `POST /v2/optionchain`:
     - **Rate limit:** 1 unique request every 3 seconds (`3.05s` guard enforced).
     - **Request fields:** `{"UnderlyingScrip": int, "UnderlyingSeg": "IDX_I", "Expiry": "YYYY-MM-DD"}`.
     - **Response fields:** `data.last_price` (float underlying spot price), `data.oc["<strike>.000000"].ce` and `.pe` containing `last_price` (float option LTP), `oi` (int current open interest), `previous_oi` (int previous day closing open interest), `implied_volatility` (float), `volume` (int), and `greeks` (`delta`, `theta`, `gamma`, `vega`).
- **OI Change Measure Distinction:** DhanHQ reports `oi` (current session OI) and `previous_oi` (**previous trading day's closing OI**). Therefore, `ce_oi_change = oi - previous_oi` and `pe_oi_change = pe_oi - pe_prev_oi` represent **net session/day OI change from the prior day's close** (labeled `"oi_change_measure": "net_change_from_previous_day_close"`). Computing 5m/15m rolling intraday OI deltas requires persisted snapshots (scheduled for the database phase).

### B.2 Upstox Developer API (v2 & v3)
- **Official Documentation URLs:**
  - Intraday Candle Data v2: [https://upstox.com/developer/api-documentation/get-intra-day-candle-data/](https://upstox.com/developer/api-documentation/get-intra-day-candle-data/)
  - Intraday Candle Data v3: [https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)
  - Option Contracts v2: [https://upstox.com/developer/api-documentation/get-option-contracts/](https://upstox.com/developer/api-documentation/get-option-contracts/)
  - Put/Call Option Chain v2: [https://upstox.com/developer/api-documentation/get-pc-option-chain/](https://upstox.com/developer/api-documentation/get-pc-option-chain/)
- **Authentication:** HTTP header `Authorization: Bearer {access_token}`, `Accept: application/json`.
- **Verified Endpoints & Intervals:**
  1. `GET /v2/historical-candle/intraday/{instrument_key}/{interval}`:
     - **Supported `interval` values on v2:** Strictly `"1minute"` and `"30minute"` (passing `"5minute"` returns error `UDAPI1020: Interval accepts one of (1minute,30minute,day,week,month)`). Note: Upstox v3 (`/v3/historical-candle/intraday/{instrument_key}/minutes/{1..300}`) supports custom minute intervals, while on v2 our adapter fetches `"1minute"` candles and deterministically aggregates completed 5-minute and 15-minute buckets aligned to the `09:15 IST` NSE market open.
     - **Response fields:** `data.candles[]` returned in **reverse-chronological order**, where each element is `[timestamp_iso_str, open, high, low, close, volume, oi]`.
  2. `GET /v2/option/contract?instrument_key={instrument_key}`:
     - **Response fields:** `data[]` array of option contract objects containing `"expiry": "YYYY-MM-DD"`.
  3. `GET /v2/option/chain?instrument_key={instrument_key}&expiry_date={YYYY-MM-DD}`:
     - **Response fields:** `data[]` array of strike objects containing `strike_price` (number), `underlying_spot_price` (number), `pcr` (number), `call_options.market_data.{ltp, oi, prev_oi, volume, close_price, bid_price, ask_price}`, `call_options.option_greeks.{iv, delta, theta, gamma, vega}`, and `put_options.{market_data, option_greeks}`.
- **OI Change Measure Distinction:** Upstox provides `market_data.oi` and `market_data.prev_oi` (previous day's closing OI). Thus `ce_oi_change = oi - prev_oi` and `pe_oi_change = oi - prev_oi` measure **net day OI change relative to previous day's close**.

### B.3 Angel One SmartAPI
- **Official Documentation URLs:**
  - Historical Candle API: [https://smartapi.angelbroking.com/docs/Historical](https://smartapi.angelbroking.com/docs/Historical)
  - Market Data Quote API: [https://smartapi.angelbroking.com/docs/MarketData](https://smartapi.angelbroking.com/docs/MarketData)
  - Option Greeks API Announcement: [https://smartapi.angelone.in/smartapi/forum/topic/4254/announcing-option-greeks-api-for-smartapi-users](https://smartapi.angelone.in/smartapi/forum/topic/4254/announcing-option-greeks-api-for-smartapi-users)
- **Authentication:** `POST /rest/auth/angelbroking/user/v1/loginByPassword` with `clientcode`, `password` (MPIN), `totp` (RFC 6238), and header `X-PrivateKey: <api_key>`, returning `data.jwtToken`.
- **Verified Endpoints & Intervals:**
  1. `POST /rest/secure/angelbroking/historical/v1/getCandleData`:
     - **Supported `interval` values:** `ONE_MINUTE` (1), `THREE_MINUTE` (3), `FIVE_MINUTE` (5), `TEN_MINUTE` (10), `FIFTEEN_MINUTE` (15), `THIRTY_MINUTE` (30), `ONE_HOUR` (60), `ONE_DAY`.
     - **Response fields:** `data[]` rows `[timestamp_iso_str, open, high, low, close, volume]`.
  2. **Option-Chain Feasibility Findings:**
     - Angel One SmartAPI does **not** provide a single-call Put/Call Option Chain endpoint returning strike-wise LTP, current OI, and previous-day OI (`prev_oi`).
     - Its `/rest/secure/angelbroking/marketData/v1/optionGreek` endpoint returns only Greeks (`delta`, `gamma`, `theta`, `vega`, `impliedVolatility`) and `tradeVolume`, omitting strike LTP, current OI, and previous OI.
     - Its `/rest/secure/angelbroking/market/v1/quote` (`FULL` mode, max 50 tokens/call) returns point-in-time `ltp` and `opnInterest`, but requires downloading the ~100MB daily Scrip Master JSON to resolve NFO option contract tokens and still does **not** provide `prev_oi` (`ce_oi_change` / `pe_oi_change`).
     - Accordingly, `AngelOneSmartAPIAdapter.get_option_chain()` fails safely with a clear, sanitized `BrokerDataError` explaining this exact limitation rather than fabricating OI changes.


## C. Implementation Changes by File

### C.1 `strategies.py`
- **Root Cause:** `parse_ist_timestamp()` did not support Unix epoch seconds/milliseconds (required by DhanHQ `/v2/charts/intraday`), `validate_candles()` did not sort reverse-chronological provider arrays or compute `is_complete` from `interval_min` and `now`, and no session-aligned 1m $ightarrow$ 5m/15m candle aggregator existed for Upstox v2.
- **Exact Behavior Changed:**
  - Extended `parse_ist_timestamp()` to convert Unix epoch seconds (`< 1e11`) and milliseconds (`>= 1e11`) from UTC (`timezone.utc`) to `Asia/Kolkata` (`IST`), alongside ISO-8601 strings (`Z`, `+00:00`, `+05:30`) and exchange-local strings.
  - Upgraded `validate_candles()` with `sort_chronologically: bool = False`, `interval_min: Optional[int] = None`, `now: Optional[Any] = None`, and `default_is_simulated: bool = False` so provider candles are sorted chronologically, deduplicated, validated for OHLCV invariants, and marked `is_complete = (bar_start + interval_min <= now_ist)`.
  - Added `aggregate_intraday_candles(source_candles, target_interval_min=5, source_interval_min=1, now=None)` which groups completed 1-minute bars into NSE `09:15 IST`-aligned buckets (`09:15–09:19`, `09:20–09:24`, etc.), computes exact OHLCV (`open=first`, `high=max`, `low=min`, `close=last`, `volume=sum`), and marks a bucket `is_complete=True` only when all `target_interval_min` constituent 1-minute bars are present and `bucket_end <= now_ist`.
- **Compatibility Impact:** 100% backward-compatible with all 5 existing strategy evaluators and Phase 1A tests.

### C.2 `brokers.py`
- **Root Cause:** Hardcoded simulation dates (`2026-10-13..16`), silent fallback defaults to `RELIANCE` (`2885`), unnormalized DhanHQ option chain, unsupported `"5minute"` Upstox v2 intraday path, and missing Upstox option chain.
- **Exact Behavior Changed:**
  - Added `resolve_nse_session_dates(ref_dt, warmup_sessions=3)` and updated `SimulatedNSEAdapter` to derive `session_day` and the 3 prior weekday `warmup_days` dynamically from `self.clock()` in `Asia/Kolkata` (rolling Saturday/Sunday back to Friday).
  - Added `validate_symbol_meta(symbol_meta, broker_key)` enforcing presence of `symbol` and broker-specific keys (`angel_token`, `dhan_id` vs `dhan_security_id`, `upstox_key` prefix `NSE_EQ|` vs `NSE_INDEX|`), preventing silent defaults to `RELIANCE` and preventing index/equity mix-ups.
  - Implemented `DhanHQAdapter.get_expiry_list()` (`POST /v2/optionchain/expirylist`), `DhanHQAdapter.get_option_chain()` (`POST /v2/optionchain` with `"Expiry"`), and `_normalize_option_chain_response()`.
  - Updated `UpstoxV2Adapter.get_intraday_candles()` to fetch `/1minute` (for 1m, 5m, 15m) or `/30minute` (for 30m) and aggregate 5m/15m buckets via `aggregate_intraday_candles()`.
  - Implemented `UpstoxV2Adapter.get_expiry_list()` (`GET /v2/option/contract`) and `UpstoxV2Adapter.get_option_chain()` (`GET /v2/option/chain`) with `_normalize_option_chain_response()`.
  - Updated `AngelOneSmartAPIAdapter.get_intraday_candles()` with strict interval/token validation and `get_option_chain()` with an explicit, sanitized `BrokerDataError`.

### C.3 `test_bot.py` & `README.md`
- Preserved all 20 Phase 1A tests in `TestIndianFOSignalBotPhase1A` (supplying a deterministic fixed clock `2026-10-16 10:35:00+05:30` in `setUp`) and added `TestIndianFOSignalBotPhase1B` (11 comprehensive test methods covering all 17 items in Section 10).


## D. Test Evidence

### D.1 Exact Command Executed
```bash
python3 test_bot.py -v
```

### D.2 Actual Test Counts & Execution Output
- **Total Tests Executed:** `31` (`20` Phase 1A tests + `11` Phase 1B test suites)
- **Passed:** `31`
- **Failed:** `0`
- **Skipped:** `0`
- **Mocked HTTP Calls:** All external HTTP calls (`urllib.request.urlopen`) to DhanHQ (`/v2/charts/intraday`, `/v2/optionchain/expirylist`, `/v2/optionchain`), Upstox (`/v2/historical-candle/intraday/.../1minute`, `/v2/option/contract`, `/v2/option/chain`), Angel One (`/rest/auth/angelbroking/user/v1/loginByPassword`, `/rest/secure/angelbroking/historical/v1/getCandleData`), and Telegram (`/bot<TOKEN>/sendMessage`) were mocked using `unittest.mock.patch("urllib.request.urlopen")`.
- **Real External API Requests Performed:** `0` (outbound internet access is disabled in the sandbox VM and no live credentials are used).


## E. Live Integration Status Matrix

| Adapter & Capability | Status Classification | Notes |
| :--- | :--- | :--- |
| **`SimulatedNSEAdapter` (Intraday Candles & Option Chain)** | `Implemented and unit-tested with mocked responses` | Clock-relative session/warm-up dates, SHA-256 deterministic seeding, explicit `SIMULATED` labeling. |
| **`DhanHQAdapter.get_intraday_candles()`** | `Official API schema verified` / `Implemented and unit-tested with mocked responses` / `Requires credentials for live verification` | Verified against `/v2/charts/intraday` (intervals `1, 5, 15, 25, 60`, Unix epoch timestamps). |
| **`DhanHQAdapter.get_option_chain()` & `get_expiry_list()`** | `Official API schema verified` / `Implemented and unit-tested with mocked responses` / `Requires credentials for live verification` | Verified against `/v2/optionchain/expirylist` and `/v2/optionchain` with 3s rate-limit guard and `oi - previous_oi` normalization. |
| **`UpstoxV2Adapter.get_intraday_candles()`** | `Official API schema verified` / `Implemented and unit-tested with mocked responses` / `Requires credentials for live verification` | Verified against `/v2/historical-candle/intraday/{key}/{1minute|30minute}` with tested 1m $ightarrow$ 5m/15m session-aligned bucket aggregation. |
| **`UpstoxV2Adapter.get_option_chain()` & `get_expiry_list()`** | `Official API schema verified` / `Implemented and unit-tested with mocked responses` / `Requires credentials for live verification` | Verified against `/v2/option/contract` and `/v2/option/chain` with `oi - prev_oi` and `underlying_spot_price` normalization. |
| **`AngelOneSmartAPIAdapter.get_intraday_candles()`** | `Official API schema verified` / `Implemented and unit-tested with mocked responses` / `Requires credentials for live verification` | Verified against `loginByPassword` (RFC 6238 TOTP) and `getCandleData` (`ONE_MINUTE`..`ONE_HOUR`). |
| **`AngelOneSmartAPIAdapter.get_option_chain()`** | `Unsupported or incomplete` (Fails safely with explicit `BrokerDataError`) | Angel One SmartAPI lacks a single-call option-chain endpoint with `prev_oi` baselines; requires NFO Scrip Master ingestion + persisted OI snapshots. |


## F. Remaining Limitations

1. **Previous-Day OI Baseline vs Rolling Intraday OI Delta:** Both DhanHQ (`previous_oi`) and Upstox (`prev_oi`) report previous trading day's closing OI. Until timestamped option-chain snapshots are persisted in a database and diffed across 5m/15m intervals, `ce_oi_change` and `pe_oi_change` reflect full-session cumulative OI change from prior close.
2. **Upstox v2 Single-Session Intraday Window:** Upstox `/v2/historical-candle/intraday/` returns candles for the current trading day only. Strategies requiring multi-day warm-up (such as the 200-bar EMA in Strategy 5) require combining `/v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}` with `/v2/historical-candle/intraday/` or persisting historical candles in a database.
3. **Angel One Option Chain Deferred:** Requires dynamic NFO Scrip Master ingestion (`OpenAPIScripMaster.json`) and persisted prior-session/intraday OI baselines.
4. **Weekday-Only Calendar Approximation:** `resolve_nse_session_dates()` skips weekends (Saturday/Sunday) but does not yet load an official NSE exchange holiday calendar.


## G. Phase 1C Readiness (Recommended Next Tasks — Not Yet Implemented)

1. **Bidirectional (Bullish & Bearish) Strategy Engine (`strategies.py`):** Implement symmetric bearish (`SELL` / `BUY PE`) rules across all 5 strategies (Bearish Order Block + BOS/FVG, Bearish VWAP rejection, Bearish Option Apex Put buying on Put unwinding + Call writing + `PCR <= 0.85`, Bearish 15m ORB breakdown, and Bearish Supertrend pullback below 200 EMA).
2. **Order Block Mitigation & First-Retest Tracking (`strategies.py`):** Ensure an Order Block zone that was already retested on an earlier bar in the lookback window does not re-trigger repeatedly.
3. **Reproducible Multi-Factor Setup Quality Score (`strategies.py`):** Replace static `confidence_pct` integers (`82%–91%`) with a deterministic quality score derived from RVOL, VWAP distance, displacement ATR multiple, and market breadth.
