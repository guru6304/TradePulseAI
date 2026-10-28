# TRADEPULSE AI — DUAL-TRACK ACCEPTANCE MATRIX
**Mission Version:** `TRADEPULSE-SHARED-DUAL-TRACK-2026-10-26-V1`  
**Track ID:** `ANTIGRAVITY_B`  
**Baseline ID:** `BASELINE_20261028_ASTRA_ULTRA_CANDIDATE_01`  
**Updated:** `2026-10-28T22:15:00+05:30`  

---

| Phase / Scenario | Scope Description | Status | Code Location | Test Module / Command | Evidence & Proof |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **Phase 1: Foundation & Security** | Ed25519 publisher trust, credential isolation, SQLite WAL schema, no secret leakage in logs. | `PASS` | `publisher_trust.py`, `storage.py`, `config.py` | `test_bot.py`, `test_security.py` | 100% offline; zero secrets; 44 tests pass. |
| **Phase 2: Historical Provenance** | Immutable market data lineage, archive validation, RFC 8032 signature verification. | `PASS` (Schema) / `BLOCKED` (Empirical) | `historical_data.py`, `source_qualification.py` | `test_phase5a_provenance.py` | Structural validation passes; empirical claims marked `BLOCKED_EXTERNAL`. |
| **Phase 3: Live Ingestion** | Angel One, Upstox, DhanHQ adapters, preflight checks, websocket sync runtime 15/16. | `PASS` (Offline) / `PENDING` (Live) | `brokers.py`, `dhan_feed.py`, `angel_feed.py` | `test_task2_integration.py`, `test_phase3_angel_integration.py` | All mocks & preflight pass (18 tests); live session pending market open. |
| **Phase 4: Scanner & Ranking** | 5 strategies, completed 5m candle requirement, dynamic opportunity ranking, confluence scoring, 1m Market Radar comparator (`market_radar.py`), factor deltas (`rank_transitions.py`). | `PASS` | `scanner_engine.py`, `opportunity_ranking.py`, `market_radar.py`, `rank_transitions.py` | `test_astra_ranking.py`, `test_astra_wave1_radar_and_transitions.py` | 35 tests pass; multi-strategy confluence verified; 2-pass ranking; 1m radar normalized baseline. |
| **Phase 5: Context, UI & Alerts** | WAI-ARIA accessible web UI, Market Radar breadth section, Opportunity X-Ray factor-delta drilldown, offline cached fonts/Tailwind/Chart.js, Telegram dry-run. | `PASS` | `public/index.html`, `server.py`, `telegram_bot.py` | `docs/evidence/astra_browser_assets_verify_20261027_01.py`, `test_cash_dashboard.js`, `test_astra_wave2_server_and_ui.py` | 138/138 browser CDP checks pass; 40/40 Node.js checks pass; 10/10 server UI tests pass. |
| **Phase 6: Paper Portfolio & Release** | Prospective trigger policies for 5 strategies, bracket preservation, no premature fills, release packager. | `PASS` | `paper_triggers.py`, `forward_paper.py`, `paper_portfolio.py`, `release_management.py` | `test_astra_multi_strategy_triggers.py`, `test_release_operations.py` | 19 tests pass; manifest verified; zero premature fills; rollback drills pass. |
| **Scenario: Future-Trigger Entry** | Limit entry touch requirement; aborts if T1 or SL hit before entry. | `PASS` | `paper_triggers.py:100-240` | `test_astra_multi_strategy_triggers.py` | Verified for ORB, Order Block, VWAP, Supertrend, Option Apex. |
| **Scenario: Stale / Out-of-Order Feed** | Rejection of stale timestamps, out-of-order sequence, negative spreads. | `PASS` | `dhan_feed.py`, `angel_feed.py` | `test_market_data_contract.py` | Fails closed; live signals revoked immediately. |
| **Scenario: 5m Rank Reversal** | Deterministic rank transition (e.g. TCS #1 at 10:00 → INFY #1 at 10:10 on fresh data). | `PASS` | `opportunity_ranking.py`, `rank_transitions.py` | `test_astra_wave1_radar_and_transitions.py` | SHA-256 authenticated rank snapshots; factor deltas recorded. |
| **Scenario: Disqualified Setup Removal** | Previous leader dropping out immediately tagged with reason code. | `PASS` | `opportunity_ranking.py`, `rank_transitions.py` | `test_astra_wave1_radar_and_transitions.py` | Tagged `NO_LINGERING_LEADER`; no lingering leaders. |
| **Scenario: Sentinel Broker Order Check** | Asserts no live broker order endpoint (place/modify/cancel) is ever called. | `PASS` | `brokers.py` | `test_release_operations.py`, `test_bot.py` | Verified through mock assertion sentinels. |
