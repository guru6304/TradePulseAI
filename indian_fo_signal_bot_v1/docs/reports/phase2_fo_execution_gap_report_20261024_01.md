# TRADEPULSE AI — PHASE 2 HISTORICAL F&O & OPTION EXECUTION GAP REPORT

**Stage:** `p2p3_acceptance_20261024_01`  
**Date:** 2026-10-24  
**Workstream:** Workstream C (Phase 2 Historical F&O & Option Execution Mechanics)  
**Modules Audited:** `option_execution.py`, `contract_universe.py`, `backtest_engine.py`, `instrument_identity.py`  
**Canonical Tests:** `test_option_execution.py`, `test_contract_universe.py`  

---

## 1. Executive Summary & Audit of Prior Gaps

Older project handover notes recorded:
> `HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED`

A comprehensive source inspection of the current repository establishes that **this gap has been resolved in software**. The long index-option execution engine (`option_execution.py`, version `option-execution-v1`) is **fully implemented and verified by canonical tests (`test_option_execution.py`)**.

However, **authentic empirical option backtests remain strictly BLOCKED (`BLOCKED_BY_EXTERNAL_DEPENDENCY`)** because genuine, exchange-attributable, tick-level / 1-minute / 5-minute option premium depth datasets for NIFTY / BANKNIFTY weekly and monthly contracts are not present in the workspace.

---

## 2. Option Execution Mechanics Verification

The implemented execution mechanics in `option_execution.py` strictly adhere to professional derivatives modeling and exchange rules:

### 2.1 Exact Dated Contract Resolution
- **Underlying & Index Alignment:** Supported underlying indices are strictly `NIFTY` and `BANKNIFTY`.
- **Contract Identifier Verification:** Every option contract must resolve to an exact instrument record with:
  - `instrument_type`: `OPTIDX`
  - `expiry`: Valid ISO 8601 expiry date
  - `strike`: Numeric strike price
  - `option_type`: `CE` (Call) or `PE` (Put)
  - `lot_size`: Authoritative lot size (e.g., 25 for NIFTY, 15 for BANKNIFTY)
  - `tick_size`: Authoritative tick size (0.05)
  - `multiplier`: 1
- **Alias Rejection:** Any conflicting or ambiguous instrument aliases raise `BacktestEligibilityError("OPTION_ALIASES_OR_WRONG_UNDERLYING")`.

### 2.2 Strict Premium Input (Anti-Substitution Rule)
- **Zero Underlying Substitution:** Underlying cash index candles are strictly prohibited from being used as proxies for option premiums.
- **Separate Observation Streams:** The engine demands two distinct observation arrays:
  1. `underlying_candles`: Used solely for underlying trend and level computation.
  2. `premiums`: Contains contract-specific bid/ask OHLCV depth (`bid_open`, `bid_high`, `bid_low`, `bid_close`, `ask_open`, `ask_high`, `ask_low`, `ask_close`, `bid_size_units`, `ask_size_units`, `volume_units`).
- **Fail-Closed on Missing Premium:** If an option bar is missing or stale at the entry timestamp, the engine rejects execution rather than interpolating or borrowing a theoretical price (`MISSING_OPTION_OBSERVATIONS`).

### 2.3 Chronology & Order Execution Behavior
- **Signal-to-Fill Sequence:** A signal triggered on the `10:25–10:30` candle is known at `10:30:00 IST`. Entry is simulated at the next bar's open (`10:30:00 IST`) on `ask_open`.
- **Adverse Tick Rounding:** Fills are conservatively rounded adversely:
  - Long Entry: Rounded UP to the nearest tick ceiling (`ROUND_CEILING`).
  - Exit: Rounded DOWN to the nearest tick floor (`ROUND_FLOOR`).
- **Depth & Liquidity Constraints:** Orders require `ask_size_units >= requested_quantity`; otherwise, fill rejection occurs.

### 2.4 Risk, Stop/Target Collisions & Expiry Boundaries
- **Stop and Target Collision:** If in the same bar both stop-loss and target are touched, the stop-loss is prioritized conservatively (worst-case assumption).
- **Intraday Boundary:** No overnight option carry is permitted (`allow_overnight_carry=False`). Unclosed positions are mandatorily closed at `15:15:00 IST` on the market session boundary.
- **Option Fees:** Correct Indian F&O statutory levies applied (STT on premium sell side, NSE transaction charges on premium turnover, SEBI charges, stamp duty, and 18% GST).

---

## 3. Software Matrix vs. Empirical Acceptance Matrix

| Requirement | Implementation Module | Test Verification | Empirical Acceptance |
| :--- | :--- | :--- | :--- |
| Exact contract metadata resolution | `option_execution.py:86-94` | `test_contract_token_underlying_strike_side_lot_and_tick_conflicts_fail` | **PASS (SOFTWARE)** |
| Strict premium requirement (no proxy) | `option_execution.py:95-100` | `test_missing_next_open_rejects_instead_of_using_later_observation` | **PASS (SOFTWARE)** |
| Anti-lookahead chronological fills | `option_execution.py:220-250` | `test_no_lookahead_future_option_bar_changes_do_not_change_candidate_or_entry` | **PASS (SOFTWARE)** |
| Tick rounding & spread model | `option_execution.py:160-190` | `test_real_strategy_next_option_open_then_target_and_persistence_are_deterministic` | **PASS (SOFTWARE)** |
| Authentic multi-strike option data | External artifact | None present in repository | **`BLOCKED_BY_EXTERNAL_DEPENDENCY`** |
| Publisher-signed option manifests | External artifact | None present in repository | **`BLOCKED_BY_EXTERNAL_DEPENDENCY`** |
| Empirical strategy profitability | Performance gate | Not authorized with synthetic fixtures | **`NOT_ESTABLISHED`** |

---

## 4. Workstream C Conclusion

The historical option execution engine mechanics are **fully implemented and verified in software**. There are no missing code gaps in `option_execution.py`. The remaining blocker is strictly external: acquisition of authentic publisher-signed historical option premium datasets.
