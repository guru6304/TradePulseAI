# TRADEPULSE AI — COMPETITIVE GAP MATRIX
**Mission ID:** `TRADEPULSE-POST-MASTER-COMPETITORS-AND-UX-2026-10-26-V1`  
**Track ID:** `ANTIGRAVITY_B`  
**Baseline ID:** `BASELINE_20261028_ASTRA_ULTRA_CANDIDATE_01`  
**Date:** `2026-10-28`  

---

## 1. Competitive Landscape Overview

TradePulse AI is evaluated against two primary Indian equity & F&O intelligence platforms:
1. **TradeFinder** (`https://tradefinder.in/`): Broad scanner suite (Option Apex, Option Clock, Market Pulse, Sector Scope, Insider Strategy). High feature breadth; exact OOS empirical performance not publicly disclosed.
2. **OrderBlock by Options Oracle** (`https://order-block.com/`): 200+ F&O stocks, 1m normalized movement strength rank (daily open movement vs. ~50-day average daily range), top-20 bullish/bearish boards, 5m structure-breaking OB zones, mini candlestick cards, trade journal with P&L heatmap.

---

## 2. Feature-by-Feature Competitive Matrix

| Feature / Capability | TradeFinder (Claim / UI) | OrderBlock (Claim / UI) | TradePulse AI (Status & Code Proof) | Measurable Customer Advantage | Risk / Data Rights | Effort | Phase | Priority | Acceptance Test |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **Dynamic Opportunity Ranking** | Broad multi-strategy list without explicit rank formula. | 1m normalized open move / 50d ATR; one direction > 2× other; minute rank changes. | **VERIFIED_CURRENT_SOURCE_AND_TEST**: 2-pass confluence evaluation, composite scoring (capped at 100), factor weights (`opportunity_ranking.py:120-250`). | Eliminates noisy single-stock momentum; rewards multi-strategy confluence (+15% per setup). | Offline safe; uses cash OHLCV inputs. | Medium | Phase 4 | **P0** | `test_astra_ranking.py` (12 tests pass) |
| **Prospective Paper Trigger Execution** | N/A (Manual alert / broker webhook). | Displays entry, invalidation, targets; no automated future limit-touch verification in public docs. | **VERIFIED_CURRENT_SOURCE_AND_TEST**: Strict limit touch requirement across all 5 strategies; pre-entry target/stop hit aborts trade (`paper_triggers.py:100-240`). | Completely eliminates premature fills; verifies trade viability before paper capital allocation. | Paper simulation only; zero broker execution. | Medium | Phase 6 | **P0** | `test_astra_multi_strategy_triggers.py` (14 tests pass) |
| **Rank Reversal Explanations (Factor Deltas)** | Static lists; no transition explanation. | Visual rank change markers (▲ / ▼) and top-10 entrant badge; no mathematical delta breakdown. | **IMPLEMENTED_NOT_VERIFIED (Wave 1)**: SHA-256 rank snapshots with factor deltas (`prior_rank`, `new_rank`, score breakdown, invalidation reason). | Trader immediately understands *why* TCS was overtaken by INFY rather than staring at an unprompted arrow. | Deterministic local SQLite storage. | Medium | Phase 4 | **P0** | Wave 1 dedicated test |
| **Immediate Stale / Invalid Setup Removal** | Unknown update cadence. | Re-ranked every minute. | **VERIFIED_CURRENT_SOURCE_AND_TEST**: Expired setups (candle + 5m + 60s) or invalidated stops dropped with `REDUNDANT_SYMBOL_SETUP` / `EXPIRED`. | Zero lingering "phantom #1" setups on the screen. | Session clock bounds. | Low | Phase 4 | **P0** | `test_astra_rank_history.py` (15 tests pass) |
| **Market Radar vs. Qualified Setup Separation** | Mixed scanner boards. | High-frequency 1m strength rank mixed with 5m OB zones. | **PROPOSED_EXPERIMENT (Wave 1)**: Layer A (Market Radar: 1m broad breadth/movement) cleanly separated from Layer B (5m Qualified Actionable Setups). | Prevents chasing 1m spikes that lack 5m structural confirmation. | Requires 1m feeds. | Medium | Phase 4 | **P1** | Wave 1 Market Radar test |
| **F&O Contract Exactness & Cost Drag** | Option Greeks & OI indicators displayed. | Mentions F&O universe; strike selection criteria undisclosed. | **VERIFIED_CURRENT_SOURCE_AND_TEST**: Explicit lot multiplier, strike, expiry, and statutory STT/exchange fee calculations (`paper_portfolio.py`, `strategies.py`). | True realistic after-cost expectancy, preventing illusory gross profits. | Requires official NFO scrip master. | Medium | Phase 5A | **P1** | `test_phase5a_contracts.py` |
| **Terminal UI & Accessibility** | Bright dashboard visuals; accessibility status unstated. | Dark/light theme, card popovers, mini charts, promotional pricing ₹7,999/yr. | **VERIFIED_CURRENT_SOURCE_AND_TEST**: WAI-ARIA tab navigation, canvas fallback text, active card focus preservation, 16 offline cached assets (`public/index.html`). | Distinct graphite/deep navy design; keyboard accessible; zero CDN dependency during offline reviews. | Fully local static assets. | Low | Phase 5 | **P1** | `astra_browser_assets_verify_20261027_01.py` (138 checks pass) |
| **Empirical Out-of-Sample Performance** | Marketing claims of strategy utility. | Sample journal illustrations (not audited customer statements). | **BLOCKED_EXTERNAL**: Strategy 3 OOS metrics held as `BLOCKED_EXTERNAL` until authentic publisher-signed tick data is licensed. | Institutional honesty; zero fabricated win rates or overfitted claims. | SEBI RA compliance & NSE non-display data licensing. | High | Phase 2 | **P2** | `test_phase5a_provenance.py` |

---

## 3. Key Findings & Differentiation Strategy
1. **Never copy OrderBlock's UI or formulas**: Build a distinct "TradePulse Intelligence Terminal" with original visual identity (graphite/deep navy shell, indigo/violet accent).
2. **Quality over quantity**: Few high-confluence actionable signals is strictly superior to forced daily alerts. Zero signals on choppy/unclear days is an intentional, defensible feature.
3. **Auditability**: Every rank position and every paper trade has an immutable cryptographic audit trail tying it to source candles and execution events.
