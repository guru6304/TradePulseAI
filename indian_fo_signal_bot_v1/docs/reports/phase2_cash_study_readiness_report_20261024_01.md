# TRADEPULSE AI — PHASE 2 HISTORICAL CASH STUDY READINESS & QUALIFICATION REPORT

**Stage:** `p2p3_acceptance_20261024_01`  
**Date:** 2026-10-24  
**Workstream:** Workstream B (Phase 2 Historical Cash Study & Validation Protocol)  
**Modules Audited:** `historical_data.py`, `historical_pagination.py`, `research_protocol.py`, `backtest_engine.py`, `historical_study.py`, `performance_acceptance.py`  
**Canonical Tests:** `test_historical_study.py`, `test_historical_pagination.py`, `test_bot.py` (backtest engine tests)  

---

## 1. Executive Summary & Status

The software architecture, data integrity verifiers, backtest execution engine, and walk-forward research protocol for Phase 2 cash equity historical studies are **fully implemented and verified in code**.

However, in accordance with Section 5 of the mission directives:
> *"If authentic data is absent, finish the offline software and orchestration tests, but do not run or publish an empirical cash-equity study using synthetic inputs. Report empirical returns, expectancy, drawdown, win rate and profitability as NOT_ESTABLISHED or the exact status defined by the existing rubric."*

Because no authentic, publisher-signed, licensed multi-month historical cash equity market data is present in the workspace, all empirical strategy metrics remain strictly **`NOT_ESTABLISHED`**.

| Area | Component | Implementation Status | Empirical Acceptance |
| :--- | :--- | :--- | :--- |
| **Data Lineage** | Immutable input archives, cryptographic SHA-256 digests | `IMPLEMENTED_AND_VERIFIED` | `BLOCKED_BY_EXTERNAL_DEPENDENCY` |
| **Research Protocol** | Chronological TRAIN / VALIDATION / OOS Partitioning | `IMPLEMENTED_AND_VERIFIED` | `BLOCKED_BY_EXTERNAL_DEPENDENCY` |
| **Anti-Lookahead** | Next-eligible-bar open fills, strictly bounded information sets | `IMPLEMENTED_AND_VERIFIED` | N/A (Engine mechanic) |
| **Fee & Slippage Model** | Realistic Indian equity cost structures (STT, GST, Exchange, SEBI, stamp duty) | `IMPLEMENTED_AND_VERIFIED` | N/A (Engine mechanic) |
| **Empirical Metrics** | Win rate, profit factor, max drawdown, Sharpe, expectancy | Code complete | **`NOT_ESTABLISHED`** |

---

## 2. Research Protocol & Partitioning Architecture

The backtest engine and research protocol (`research_protocol.py`, `historical_study.py`) implement a deterministic walk-forward evaluation protocol:

### 2.1 Chronological Partitioning Rules
- **No Random K-Fold Splitting:** Time-series market data strictly forbids shuffling or random splits.
- **Strict Chronological Sequence:**
  1. **TRAIN (In-Sample):** 60% of total qualified time interval (used exclusively for hypothesis validation and baseline parameter discovery).
  2. **VALIDATION:** 20% of total qualified time interval (used for parameter freeze and overfitting checks).
  3. **OUT-OF-SAMPLE (OOS / Test):** 20% of total qualified time interval (unseen data for final unbiased performance evaluation).
- **Anti-Overfitting Rule:** Parameters cannot be adjusted or re-tuned after observing OOS performance. Any re-tuning invalidates the run and requires a fresh dataset.

### 2.2 Information Set & Look-Ahead Protection
- A candle closing at `10:35:00 IST` provides market state for evaluation at `10:35:00 IST`.
- The earliest executable fill can occur only at or after `10:35:01 IST` on the **next bar's open price** (`next_bar_open`).
- Current bar high/low/close prices are never used as entry fills for signals generated on that same bar.
- Formed/forming candle separation is enforced by `filter_completed_candles()`.

---

## 3. Indian Cash Equity Cost & Friction Modeling

The backtesting ledger reconciles gross P&L to net realized P&L through an accurate Indian equity transaction cost model (`backtest_engine.py`):

| Cost Component | Intraday Cash Equity Rate | Delivery / Positional Rate |
| :--- | :--- | :--- |
| **STT / CTT** | 0.025% on Sell side | 0.1% on Both Buy & Sell |
| **NSE Turnover Charges** | 0.00325% on Total Turnover | 0.00325% on Total Turnover |
| **SEBI Turnover Fee** | ₹10 per Crore (0.0001%) | ₹10 per Crore (0.0001%) |
| **Stamp Duty** | 0.003% on Buy side | 0.015% on Buy side |
| **GST** | 18% on (Brokerage + Exchange Charges + SEBI) | 18% on (Brokerage + Exchange Charges + SEBI) |
| **Slippage Model** | Configurable tick buffer (default 0.05% or 1 tick minimum) | Configurable tick buffer |

Every simulated trade records: `gross_pnl`, `stt_inr`, `exchange_charges_inr`, `sebi_charges_inr`, `stamp_duty_inr`, `gst_inr`, `brokerage_inr`, and `net_pnl`. The cash ledger asserts that `sum(net_pnl) == ending_cash - starting_cash`.

---

## 4. Empirical Performance Status Table

In compliance with the prohibition against using synthetic fixtures or mock data to authorize empirical performance:

| Metric | Required Benchmark | Synthetic Test Run | Authentic Empirical Result | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Sample Size (Trades)** | >= 100 complete cycles | Fixture only (1–18 trades) | None | **`NOT_ESTABLISHED`** |
| **Win Rate** | >= 50% | Fixture dependent | None | **`NOT_ESTABLISHED`** |
| **Profit Factor** | >= 1.50 | Fixture dependent | None | **`NOT_ESTABLISHED`** |
| **Maximum Drawdown** | <= 10.0% of capital | Fixture dependent | None | **`NOT_ESTABLISHED`** |
| **Expectancy per Trade** | > 0.0 (Positive) | Fixture dependent | None | **`NOT_ESTABLISHED`** |
| **Walk-Forward Consistency**| OOS degradation < 25% | Fixture dependent | None | **`NOT_ESTABLISHED`** |

---

## 5. Workstream B Conclusion

The offline backtesting engine, walk-forward orchestrator, cost model, and fail-closed readiness policies are **fully implemented and verified**. The strategy validation engine correctly rejects synthetic or unqualified datasets from claiming empirical readiness.

To unlock empirical acceptance, the operator must provide an authentic, publisher-signed, multi-month historical dataset accompanied by documented distribution/research rights.
