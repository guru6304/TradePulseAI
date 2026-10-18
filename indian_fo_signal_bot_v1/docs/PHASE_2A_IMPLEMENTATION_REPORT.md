# TradePulse AI — Phase 2A Implementation Report (`PHASE_2A_IMPLEMENTATION_REPORT.md`)

**Date:** 2026-10-16  
**Scope:** Phase 2A — Angel One SmartAPI Read-Only Market Data Integration  
**Baseline Artifact:** `indian_fo_signal_bot_phase1f.zip` (57/57 tests passing)  
**Output Artifact:** `indian_fo_signal_bot_phase2a.zip` (65/65 tests passing)


## 1. Step 1 — Pre-Implementation Audit of Phase 1F Baseline

### 1.1 Baseline Inspection & Test Verification
Extracting `indian_fo_signal_bot_phase1f.zip` and running `python3 test_bot.py -v` confirmed **57 passing tests (`0` failed, `0` skipped)** across `config.py`, `brokers.py`, `strategies.py`, `storage.py`, `scanner_engine.py`, `telegram_bot.py`, `server.py`, and `test_bot.py`.

### 1.2 Audit of Existing Angel One Implementation vs Phase 2A Requirements

| Component / Capability | Existing Phase 1F Baseline State | Phase 2A Gap Identified & Addressed |
| :--- | :--- | :--- |
| **Credential & TOTP Validation (`config.py`, `brokers.py`)** | `BotConfig` loaded `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET`; `generate_totp()` computed RFC 6238 6-digit codes. | `BotConfig.is_broker_credentials_configured("angelone")` and `validate(require_live_credentials=True)` did not validate Base32 decoding of `ANGEL_TOTP_SECRET` upfront or report specific missing `ANGEL_*` variable names. Added `_is_valid_base32_secret()`, explicit per-field validation, `ANGEL_SCRIP_MASTER_PATH`, `ANGEL_REQUEST_TIMEOUT_SECONDS`, and `ANGEL_MIN_REQUEST_INTERVAL_SECONDS`. |
| **Authentication & Session Lifecycle (`AngelOneSmartAPIAdapter`)** | `authenticate()` called `POST /rest/auth/angelbroking/user/v1/loginByPassword` and stored `self.jwt_token`. | Did not normalize `"Bearer "` prefixes on `jwtToken`, did not store `refreshToken` or `feedToken`, did not implement `POST /rest/auth/angelbroking/jwt/v1/generateTokens` (`refresh_access_token()`) or `GET /rest/secure/angelbroking/user/v1/getProfile` (`get_profile()`), and did not auto-recover on `AG8001` / `AG8002` / `AB1010` session expiry. |
| **Instrument & Scrip Master Resolution (`brokers.py`)** | `validate_symbol_meta()` validated static `angel_token` strings (`99926000` for `NIFTY`, `99926009` for `BANKNIFTY`, and 15 NSE equities). | Lacked `resolve_instrument(symbol_or_meta)` and `load_scrip_master()` to ingest Angel One `OpenAPIScripMaster.json` records (normalizing `DDMMMYYYY` option expiries to `YYYY-MM-DD` and paise strikes `2480000.000000` $\rightarrow$ `24800`). |
| **Market Quotes / Snapshots (`market/v1/quote/`)** | Not implemented in `AngelOneSmartAPIAdapter`. | Implemented `get_quotes(exchange_tokens, mode)` and `get_quote(symbol_or_meta, mode)` for `LTP`, `OHLC`, and `FULL` modes with automatic 50-token batching, OHLC invariant validation, `exchFeedTime` (`DD-MMM-YYYY HH:MM:SS`) IST parsing, and `unfetched` error reporting. |
| **Historical / Intraday Candles (`getCandleData`)** | Implemented for `1, 3, 5, 10, 15, 30, 60` minute intervals using a naive 5-calendar-day lookback. | Upgraded `get_intraday_candles()` to use `resolve_nse_session_dates(now_ist, warmup_sessions=5)` so `fromdate < todate` holds even on weekends/pre-open and provides $\ge 200$ completed 5m bars for Strategy 5's 200 EMA, plus optional `max_staleness_minutes` validation. |
| **NIFTY & BANKNIFTY Options Data & Scanner Integration** | `get_option_chain()` unconditionally raised `BrokerDataError`, which caused `IntradayBotEngine.run_single_scan()` to abort the entire scan (`status="FAILED"`) when `ACTIVE_BROKER=angelone`. | Added `UnsupportedBrokerCapabilityError(BrokerDataError)`, implemented `get_option_greeks()`, `get_put_call_ratio()`, `set_prior_oi_baseline()`, and full NFO option-chain assembly when Scrip Master + prior OI baseline are provided. Updated `IntradayBotEngine.run_single_scan()` to catch `UnsupportedBrokerCapabilityError` on option-chain fetch so Strategies 1, 2, 4, and 5 still evaluate `NIFTY`, `BANKNIFTY`, and all 15 NSE equities when single-call option-chain baselines are absent. |
| **Secret Redaction & Read-Only Guardrails** | Basic error messages in `authenticate()` and `get_intraday_candles()`. | Added `_redact_secrets()` across all error paths and explicitly blocked `/rest/secure/angelbroking/order/*` and `/rest/secure/angelbroking/gtt/*` in `_request_json()`. |


## 2. Official Angel One SmartAPI Endpoints Verified & Implemented

| Capability | HTTP Method & Official SmartAPI Endpoint | Request / Header Contract | Response & Error Handling |
| :--- | :--- | :--- | :--- |
| **Login by Password + TOTP** | `POST https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1/loginByPassword` | JSON `{"clientcode", "password", "totp"}` + headers `X-PrivateKey`, `X-UserType: USER`, `X-SourceID: WEB`, `X-ClientLocalIP`, `X-ClientPublicIP`, `X-MACAddress` | Validates `status is True` and non-empty `data.jwtToken`; strips optional `"Bearer "` prefix; stores `jwt_token`, `refresh_token`, `feed_token`, `authenticated_at_ist`. Maps `AB1000`, `AB1007`, `AB1050`, `AG8004`. |
| **Token Refresh** | `POST https://apiconnect.angelbroking.com/rest/auth/angelbroking/jwt/v1/generateTokens` | JSON `{"refreshToken": "..."}` + `Authorization: Bearer <jwt>` + `X-PrivateKey` | Updates `jwt_token`, `refresh_token`, `feed_token`. Automatically invoked by `_recover_session()` when `AG8001` / `AG8002` / `AB1010` / HTTP `401` occurs. |
| **User Profile (Session Check)** | `GET https://apiconnect.angelbroking.com/rest/secure/angelbroking/user/v1/getProfile` | `Authorization: Bearer <jwt>` + `X-PrivateKey` | Verifies active session and returns sanitized `{"clientcode", "name", "exchanges", "products", "is_simulated": False, "data_mode": "LIVE"}`. |
| **Market Data Quotes** | `POST https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/` | JSON `{"mode": "LTP" \| "OHLC" \| "FULL", "exchangeTokens": {"NSE": [...], "NFO": [...]}}` (batched $\le 50$ tokens/call) | Validates `data.fetched` (`ltp > 0`, OHLC invariants in `OHLC`/`FULL` mode, `tradeVolume >= 0`, `opnInterest >= 0`, `exchFeedTime` $\rightarrow$ IST) and surfaces `data.unfetched` errors. |
| **Historical / Intraday Candles** | `POST https://apiconnect.angelbroking.com/rest/secure/angelbroking/historical/v1/getCandleData` | JSON `{"exchange", "symboltoken", "interval", "fromdate", "todate"}` (`ONE_MINUTE`..`ONE_HOUR`) | Sorts chronologically, deduplicates timestamps, validates OHLCV invariants, computes `is_complete` against `Asia/Kolkata` clock, and enforces optional `max_staleness_minutes`. |
| **Option Greeks & IV** | `POST https://apiconnect.angelbroking.com/rest/secure/angelbroking/marketData/v1/optionGreek` | JSON `{"name": "NIFTY" \| "BANKNIFTY", "expirydate": "DDMMMYYYY"}` | Validates and normalizes `strikePrice`, `optionType` (`CE`/`PE`), `impliedVolatility`, `delta`, `gamma`, `theta`, `vega`, `tradeVolume`. |
| **Put-Call Ratio (PCR)** | `GET https://apiconnect.angelbroking.com/rest/secure/angelbroking/marketData/v1/putCallRatio` | `Authorization: Bearer <jwt>` + `X-PrivateKey` | Validates positive `pcr` and `tradingSymbol` rows. |


## 3. Changed Files Summary

| File Path | Action | Summary of Changes |
| :--- | :--- | :--- |
| `config.py` | **Updated** | Added `_is_valid_base32_secret()`, `angel_scrip_master_path`, `angel_request_timeout_seconds`, and `angel_min_request_interval_seconds`; enhanced `validate(require_live_credentials=True)` to report missing `ANGEL_*` fields and invalid Base32 TOTP seeds without exposing secrets; exposed `angel_scrip_master_configured` boolean in `to_safe_dict()`. |
| `strategies.py` | **Updated** | Extended `parse_ist_timestamp()` to parse Angel One `exchFeedTime` / `exchTradeTime` strings (`"%d-%b-%Y %H:%M:%S"` and `"%d-%b-%Y %H:%M"`, e.g. `"16-Oct-2026 10:35:00"`) into timezone-aware `Asia/Kolkata` (`IST`) datetimes. |
| `brokers.py` | **Updated** | Added `UnsupportedBrokerCapabilityError(BrokerDataError)` and `_redact_secrets()`; upgraded `AngelOneSmartAPIAdapter` with token refresh (`generateTokens`), session recovery (`_recover_session`), profile check (`get_profile`), Scrip Master ingestion (`load_scrip_master`), instrument resolution (`resolve_instrument`), quotes (`get_quotes`, `get_quote`), multi-session candle warm-up + staleness check (`get_intraday_candles`), Option Greeks (`get_option_greeks`), PCR (`get_put_call_ratio`), NFO option-chain assembly (`get_option_chain`, `set_prior_oi_baseline`), and order-endpoint blocking. |
| `scanner_engine.py` | **Updated** | Updated `IntradayBotEngine.run_single_scan()` to catch `UnsupportedBrokerCapabilityError` when an adapter lacks single-call option-chain baselines, recording the capability notice in `instrument_errors` while continuing to evaluate Strategies 1, 2, 4, and 5 on live Angel One candles. |
| `.env.example` | **Updated** | Documented `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET` (Base32 seed vs 6-digit code), `ANGEL_SCRIP_MASTER_PATH`, `ANGEL_REQUEST_TIMEOUT_SECONDS`, and `ANGEL_MIN_REQUEST_INTERVAL_SECONDS` using safe placeholders only. |
| `test_bot.py` | **Updated** | Preserved all 57 Phase 1A–1F tests and added `TestIndianFOSignalBotPhase2A` (8 new test suites, bringing total to **65 passing tests**). |
| `README.md` | **Updated** | Added Phase 2A Angel One setup and local PowerShell verification commands. |
| `docs/PHASE_2A_IMPLEMENTATION_REPORT.md` | **Added** | Complete Phase 2A audit, official endpoint matrix, capability verification status separation, test results, and manual verification guide. |


## 4. Verification Status Separation Matrix

In accordance with Step 6 of the Phase 2A specification, each capability is classified across four strict verification levels:
- **Implemented in code**
- **Verified by mocked tests**
- **Verified against the real broker API**
- **Not verified**

| Capability / Component | Implemented in Code | Verified by Mocked Tests (`test_bot.py`) | Verified Against Real Broker API | Not Verified / Limitation |
| :--- | :---: | :---: | :---: | :--- |
| **RFC 6238 TOTP Generation (`generate_totp`) & Base32 Validation** | Yes | Yes (`test_totp_generation`, `test_p2a_missing_credentials_invalid_totp_and_rejected_authentication`) | No | Live account TOTP acceptance requires user's local `ANGEL_TOTP_SECRET` in `.env`. |
| **SmartAPI Login (`loginByPassword`) & Bearer Prefix Normalization** | Yes | Yes (`test_p2a_authentication_success_bearer_normalization_and_get_profile`) | No | Outbound internet is disabled in the VM sandbox; not verified against live `apiconnect.angelbroking.com`. |
| **JWT Refresh (`generateTokens`) & Session Expiry Auto-Recovery (`AG8001` / `AB1010` / HTTP 401)** | Yes | Yes (`test_p2a_token_session_expiry_refresh_and_relogin_recovery`) | No | Not verified against live Angel One servers. |
| **Session Profile Verification (`getProfile`)** | Yes | Yes (`test_p2a_authentication_success_bearer_normalization_and_get_profile`) | No | Not verified against live Angel One servers. |
| **Instrument Resolution (`resolve_instrument`) & Scrip Master (`OpenAPIScripMaster.json`) Parsing** | Yes | Yes (`test_p2a_instrument_resolution_scrip_master_and_stale_candle_detection`) | No | Live download of `OpenAPIScripMaster.json` (~100 MB) must be performed on the user's local machine. |
| **Market Quotes (`market/v1/quote/` in `LTP`, `OHLC`, `FULL` Modes + >50 Token Batching)** | Yes | Yes (`test_p2a_market_quotes_modes_batching_and_validation`) | No | Not verified against live Angel One servers. |
| **Intraday / Historical OHLCV Candles (`getCandleData`) + Warm-Up & Staleness Validation** | Yes | Yes (`test_p1_angelone_candle_normalization_and_option_chain_explicit_error`, `test_p2a_instrument_resolution_scrip_master_and_stale_candle_detection`) | No | Not verified against live Angel One servers. |
| **Option Greeks (`optionGreek`), PCR (`putCallRatio`) & Option-Chain Assembly with Baseline** | Yes | Yes (`test_p2a_option_greeks_pcr_and_option_chain_assembly_with_baseline`) | No | Angel One does not provide `prev_oi` in `market/v1/quote`; assembling `ce_oi_change`/`pe_oi_change` requires `OpenAPIScripMaster.json` + a prior OI baseline snapshot. |
| **Scanner & Health State Transitions (`UNAVAILABLE_MISSING_CREDENTIALS`, `CONFIGURED_UNVERIFIED`, `CONNECTED_VERIFIED`, `ERROR`)** | Yes | Yes (`test_p2a_engine_and_health_status_transitions_with_angelone`) | No | Live `CONNECTED_VERIFIED` state requires running a scan with real Angel One credentials locally. |
| **Secret Redaction & Order-Placement Blocking (`/order/*`, `/gtt/*`)** | Yes | Yes (`test_p2a_rate_limits_timeouts_secret_redaction_and_order_blocking`) | N/A (Local Security Control) | Verified deterministically in code and tests. |


## 5. Compilation & Test Suite Execution Results

### 5.1 Python Bytecode Compilation Check
```bash
python3 -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py test_bot.py
```
Result: **Exit code `0`** across all 8 Python modules.

### 5.2 Complete 65-Test Suite Execution (`test_bot.py`)
```bash
python3 test_bot.py -v
```
- **Total Tests Executed:** `65` (`20` Phase 1A + `11` Phase 1B + `8` Phase 1C + `11` Phase 1D + `3` Phase 1E + `4` Phase 1F + `8` Phase 2A)
- **Passed:** `65`
- **Failed:** `0`
- **Skipped:** `0`
- **Execution Time:** `20.336s` (`OK`)


## 6. Manual Local Verification Procedure (Without Sharing Secrets)

1. **Extract the archive and configure `.env` locally in Windows PowerShell:**
   ```powershell
   Expand-Archive -Path .\indian_fo_signal_bot_phase2a.zip -DestinationPath .\tradepulse_phase2a -Force
   Set-Location .\tradepulse_phase2a\indian_fo_signal_bot_v1
   Copy-Item .\.env.example .\.env -Force
   ```
2. **Edit `.env` locally on your machine** (never paste real credentials into chat):
   - Set `ACTIVE_BROKER=angelone`
   - Set `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN` (your 4-digit MPIN), and `ANGEL_TOTP_SECRET` (the Base32 seed from Angel One SmartAPI's **Enable TOTP** page).
   - Optionally download `OpenAPIScripMaster.json` locally and set `ANGEL_SCRIP_MASTER_PATH=C:\path\to\OpenAPIScripMaster.json`.
3. **Run the offline test suite first (uses mocked responses only):**
   ```powershell
   python -m py_compile config.py brokers.py strategies.py storage.py scanner_engine.py telegram_bot.py server.py test_bot.py
   python .\test_bot.py -v
   ```
4. **Run a read-only live connectivity & market-data smoke test from PowerShell:**
   ```powershell
   python -c "from config import BotConfig; from brokers import AngelOneSmartAPIAdapter; cfg = BotConfig(); cfg.validate(require_live_credentials=True); a = AngelOneSmartAPIAdapter(cfg); a.authenticate(); print('Verified Profile:', a.get_profile()['clientcode']); print('NIFTY Spot Quote:', a.get_quote('NIFTY', mode='LTP')); print('RELIANCE 5m Candles:', len(a.get_intraday_candles('RELIANCE', interval_min=5)))"
   ```
5. **Launch the dashboard server and verify in Chrome (`http://127.0.0.1:8080/`):**
   ```powershell
   python .\server.py
   ```
   - Open `http://127.0.0.1:8080/`. Before running a scan, confirm the header badge shows **`LIVE CONFIG (CONFIGURED_UNVERIFIED)`**.
   - Click **`⚡ Scan Market Now`** during or after NSE market hours. Confirm that once Angel One returns valid candles, the header transitions to **`LIVE VERIFIED DATA MODE`** (`CONNECTED_VERIFIED`) and generated signals carry `LIVE` badges.


## 7. Remaining Limitations

1. **No Real Broker Network Calls Executed in Sandbox VM:** Outbound internet access is disabled in the sandbox VM and no real broker credentials are included. All Angel One SmartAPI paths are verified by deterministic mocked HTTP tests (`TestIndianFOSignalBotPhase2A`) and are **not verified against the real broker API** inside this environment.
2. **Angel One Single-Call Option-Chain Previous-Day OI Limitation:** Unlike DhanHQ (`/v2/optionchain`) and Upstox (`/v2/option/chain`), Angel One SmartAPI does not provide a single-call option-chain endpoint with `previous_oi` (`ce_oi_change` / `pe_oi_change`). Evaluating Strategy 3 (`Option Apex OI Shift`) under `ACTIVE_BROKER=angelone` requires loading `OpenAPIScripMaster.json` (`ANGEL_SCRIP_MASTER_PATH`) plus a prior OI baseline snapshot (`set_prior_oi_baseline()`). When those are not provided, `IntradayBotEngine` cleanly logs `UnsupportedBrokerCapabilityError` for Strategy 3 and evaluates Strategies 1, 2, 4, and 5 across `NIFTY`, `BANKNIFTY`, and all 15 NSE equities.
3. **Read-Only Market Data Only:** Order placement, modification, cancellation, and GTT rule mutation are strictly disabled.
