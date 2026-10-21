# TradePulse AI — Task 2 Cash Data Acceptance Matrix
**Task ID:** `20261020_TASK2_CONFIG_AND_CASH_DATA_ACCEPTANCE`  
**Date:** `2026-10-19`  
**Workspace:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`  
**Scope:** Indian Cash-Equity Market Data Pipeline (NSE Equity Intraday)  
**Rule:** Fixture-only and mocked evidence must NEVER be classified as live acceptance.

---

## 1. Evidence Classification Taxonomy

- **`OFFLINE_VERIFIED`**: Deterministic software behavior verified via passing unit/integration tests with synthetic fixtures or mocked transport. Does not prove live broker communication.
- **`FIXTURE_ONLY`**: Behavior demonstrated exclusively against synthetic wire fixtures or static JSON snapshots.
- **`LIVE_UNVERIFIED`**: Real provider format is targeted, but live endpoint connectivity is unverified or blocked in this environment.
- **`EXTERNALLY_BLOCKED`**: Progress requires external action on a third-party developer portal (e.g. IP binding, API subscription, or auth token).
- **`ACCEPTED`**: Fully evidenced with verified software logic AND live operational confirmation.

---

## 2. Cash-Equity Market Data Pipeline Audit Matrix

| Pipeline Stage / Control | Required Safety Behavior | Source Path & Implementation Evidence | Test Regression Evidence | Evidence Classification | Operational Status & Remaining Gate |
|---|---|---|---|---|---|
| **1. Instrument Identity** | Canonical symbol, token, exchange, tick size, and lot size. Ambiguous mappings or token mismatches rejected. | `instrument_identity.py:spot_identity`, `check_echo`, `validate_symbol_meta` | `test_phase4_market_data.py:TestPhase4InstrumentScope`, `test_market_data_contract.py` | `OFFLINE_VERIFIED` | Pinned mappings and response echo checks verified offline. Live exchange token echo requires live broker response. |
| **2. Source Provenance** | Provider identity, observation timestamps, retrieval timestamps, and data mode (`LIVE` vs `SIMULATED`) preserved. | `instrument_identity.py:bind_candles`, `source_qualification.py:assess_source_evidence` | `test_angel_market_data.py:TestAngelMarketDataSafety`, `test_blocker_removal.py` | `OFFLINE_VERIFIED` | Provenance markers attached to every candle batch. Untrusted external files cannot bypass provenance gates. |
| **3. Candle Integrity** | Valid OHLCV floats, $H \ge L$, $H \ge \max(O,C)$, $L \le \min(O,C)$, volume $\ge 0$, monotonic timestamps, zero duplicates. | `brokers.py:assess_live_candle_batch`, `enforce_live_candle_batch` | `test_market_data_contract.py:TestSharedMarketDataContract` | `OFFLINE_VERIFIED` | Comprehensive numeric and integrity checks pass on all synthetic fixtures. |
| **4. Freshness & Session** | Candle timestamps must be within current IST trading session (09:15–15:30 IST weekdays), non-future, not stale ($< 15\text{m}$). | `brokers.py:assess_live_candle_batch`, `scanner_engine.py:_assess_scan_candles` | `test_phase4_strategy.py`, `test_phase4_market_data.py` | `OFFLINE_VERIFIED` | Out-of-session, weekend, and stale candles are rejected deterministically before evaluation. |
| **5. Gap Detection** | Detect missing intervals (e.g. 5m intervals) and classify explicitly; never fabricate or interpolate synthetic bars. | `brokers.py:assess_live_candle_batch`, `historical_data.py:validate_and_prepare_historical_dataset` | `test_market_data_contract.py`, `test_bot.py:TestMarketDataFreshness` | `OFFLINE_VERIFIED` | Gaps trigger explicit `BrokerDataError` or `CandleFreshnessError`; interpolation is strictly prohibited. |
| **6. Persistence** | Stored records preserve deduplication keys, instrument labels, prices, risk fields, and provenance. Idempotent storage. | `storage.py:SQLitePersistenceStore.save_signal`, `validate_signal_identity` | `test_completion_engineering.py:test_storage_cannot_persist_invalid_target_geometry`, `test_phase4_e2e.py` | `OFFLINE_VERIFIED` | Signals table in SQLite preserves complete record geometry; invalid targets or duplicate keys are rejected. |
| **7. Scanner Handoff** | Only complete, validated candles reach strategy evaluators; insufficient warmup or malformed bars yield no signal. | `scanner_engine.py:IntradayBotEngine.run_single_scan`, `strategies.py:filter_completed_candles` | `test_phase4_strategy.py:TestPhase4StrategyRequiredData`, `test_completion_engineering.py` | `OFFLINE_VERIFIED` | Incomplete (forming) bars stripped; strategy warmup requirements strictly enforced before evaluation. |
| **8. Dashboard / API** | Accurately distinguish stored live signals from simulated/fixture records. Health failure clears stale cards. | `server.py:DashboardRequestHandler`, `public/index.html` | `test_cash_dashboard.js` (6 DOM tests pass) | `OFFLINE_VERIFIED` | Cards display `SIMULATED`, `MOCKED`, or `LIVE_UNVERIFIED`. Fixtures are never presented as live acceptance. |
| **9. Provider Isolation** | Offline tests make zero network calls; error in one provider adapter never silently swaps active broker. | `brokers.py:MultiBrokerScanner.get_active_adapter`, `config.py:BotConfig` | `test_blocker_removal.py:TestDiagnosticLifecycle`, `test_completion_engineering.py` | `OFFLINE_VERIFIED` | Provider errors raise explicit exceptions; fallback to `paper_sim` is prevented during live scans. |
| **10. Risk Boundaries** | Geometry ($T_1 > \text{Entry} > SL$ for Long), statutory Indian cost model, position sizing, capital reservation. | `strategies.py:validate_trade_signal`, `size_position`, `backtest_engine.py:IndianCostModel` | `test_completion_engineering.py:TestCandidateValidationAndRanking`, `test_phase4_e2e.py` | `OFFLINE_VERIFIED` | Inverted stops/targets or invalid sizes raise `ValueError`; paper accounts reserve capital atomically. |

---

## 3. Operational Acceptance Status by Scope

| Scope | Ingestion Status | Verification Status | Blockers to Live Operational Sign-off |
|---|---|---|---|
| **NSE Cash Spot Quote** | Genuine live quote received in Task 1 (RELIANCE LTP `1220.3`, age `0.622s`). | `LIVE_ACCEPTED_SINGLE` | Standalone quote passes, but does not provide candles or scanner input. |
| **NSE Cash 5-Minute Candles** | Offline fixture parsing verified across Angel One & Upstox. | `EXTERNALLY_BLOCKED` | Angel One `/historical/v1/getCandleData` returned HTTP 403 `ACCESS_DENIED`. Upstox v2 intraday candle endpoint deprecated. |
| **NIFTY / BANKNIFTY Spot Candles** | Pinned tokens and offline contract parser verified. | `OFFLINE_VERIFIED` | Live index spot feed requires live provider session. |
| **NFO Stock & Index Derivatives** | Contract models, parser, and option Greeks implemented offline. | `EXTERNALLY_BLOCKED` | Live contract master and derivative option chains blocked on broker credentials. |
| **Historical Replay** | Split protocol and point-in-time slices verified offline. | `EXTERNALLY_BLOCKED` | Source qualification gate requires authoritative publisher digital signatures. |

---

## 4. Summary & Conclusion

The cash-equity market-data pipeline implementation is **100% complete and verified offline**. Every required integrity control (identity, provenance, candle validation, freshness, session, gaps, persistence, scanner gating, UI labeling, provider isolation, and risk geometry) has deterministic regression test coverage.

However, in strict adherence to the project safety and scoring rubric:
- Synthetic fixtures and mocked tests provide **software verification**, not **live acceptance**.
- Live operational candle ingestion remains **EXTERNALLY BLOCKED** pending resolution of the Angel One Historical Data API permission / Static IP on the SmartAPI portal.


## Task 3 correction notice - 2026-10-21

The statement that the cash pipeline is 100% complete is withdrawn. Signal persistence does not establish durable ingestion of every accepted candle. Freshness uses the implemented interval/publication-delay policy, not a universal 15-minute threshold. Live quote acceptance is not independently established by the retained machine-readable evidence; permission/IP root causes remain unknown.

The original report body above is retained as historical evidence. Current authority: [Task 3 forensic, stability and readiness report](TRADEPULSE_TASK3_FORENSIC_STABILITY_AND_READINESS_REPORT.md).
