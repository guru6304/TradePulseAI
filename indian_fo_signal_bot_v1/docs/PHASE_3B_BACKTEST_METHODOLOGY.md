# TradePulse AI — Phase 3B Deterministic Backtest Methodology (`PHASE_3B_BACKTEST_METHODOLOGY.md`)

**Date:** 2026-10-17  
**Engine Version:** `phase_3b_v1.0.0` (`backtest_engine.py`)  
**Implementation Status:** `IMPLEMENTED_VERIFIED`  
**Data Acceptance Status:** `BLOCKED_PHASE_2C_LIVE_ACCEPTANCE_NOT_COMPLETED`

## 1. Strict No-Look-Ahead Replay Model

At every historical 5-minute candle index $i$ with bar start timestamp $T_i$ and bar close timestamp $T_{	ext{decision}} = T_i + \Delta t$ ($\Delta t = 5	ext{ minutes}$):

1. **Point-in-Time Slicing (`get_point_in_time_candle_slice`):**
   A bar $k$ with start timestamp $T_k$ is included in the strategy's visible history $\mathcal{H}(T_{	ext{decision}})$ if and only if:
   $$T_k + \Delta t \le T_{	ext{decision}} \quad 	ext{and} \quad 	exttt{is\_complete} = 	exttt{True}$$
2. **Cryptographic & Structural Look-Ahead Guard (`verify_no_lookahead_leakage`):**
   Before invoking the strategy evaluator at $T_{	ext{decision}}$, `verify_no_lookahead_leakage(visible_slice, decision_time_ist, interval_min=5)` verifies that no bar in `visible_slice` closes after $T_{	ext{decision}}$. Any violation immediately aborts the backtest with `LookAheadBiasError`.
3. **Causal Indicator Computation:**
   All indicators (`compute_ema`, `compute_rsi`, `compute_atr`, `compute_session_vwap`, `compute_supertrend`) and `mitigated_zones` sets are computed solely from $\mathcal{H}(T_{	ext{decision}})$. Future bars ($m > i$) are never inspected, backfilled, or used to revise earlier signals.

## 2. Signal Timing, Next-Candle Execution & Gap Rules

1. **Signal Confirmation vs Fill Timing (`NEXT_CANDLE_OPEN`):**
   - Because all 5 strategies confirm signals on a **completed 5-minute candle close** at $T_{	ext{decision}} = T_i + 5	ext{m}$ (bar start $T_i$), the signal price $C_i$ was already in the past before the candle closed.
   - To prevent look-ahead fill bias, a signal confirmed on bar $i$ (stamped $T_i$) can **only** be executed at the open $O_{i+1}$ of the **immediately next 5-minute candle** stamped at $T_{i+1} = T_i + 5	ext{m}$ on the **same NSE trading session**.
2. **Missing Next-Candle Gap Rejection (`MISSING_NEXT_CANDLE_GAP`):**
   - If bar $i+1$ is missing (i.e., $T_{i+1} 
e T_i + 5	ext{m}$) or belongs to a different trading session date, the entry is **rejected** and counted in `rejected_signals_by_reason["MISSING_NEXT_CANDLE_GAP"]`. Missing candles are never interpolated or fabricated.
3. **Opening Gap Beyond Stop-Loss Rejection (`NEXT_OPEN_GAP_BEYOND_STOP_LOSS`):**
   - If the next candle's open $O_{i+1}$ has already gapped to or beyond the signal's stop-loss (`O_{i+1} <= stop_loss` for `LONG`, or `O_{i+1} >= stop_loss` for `SHORT`), the trade is **rejected** (`NEXT_OPEN_GAP_BEYOND_STOP_LOSS`) because its invalidation level is already breached at the moment of entry.
4. **Risk Re-Anchoring on Next-Candle Open:**
   - Position sizing uses the actual fill risk per unit $R_{	ext{unit}} = |P_{	ext{entry,eff}} - 	ext{SL}|$ from the next candle's open rather than assuming the prior close's theoretical risk.

## 3. Intrabar Exit Simulation, Conservative Same-Candle Collision & EOD Square-Off

For an open position entered at bar $j = i+1$, each subsequent candle $m \ge j$ on the same trading session is evaluated in strict chronological order:

1. **Gap Beyond Stop-Loss or Target at Bar Open ($m > j$):**
   - **Long:** If $O_m \le 	ext{SL}$, exits immediately at $O_m$ (`STOP_LOSS_GAP_OPEN`). If $O_m \ge 	ext{Target}$, exits at $O_m$ (`TARGET_GAP_OPEN`).
   - **Short:** If $O_m \ge 	ext{SL}$, exits immediately at $O_m$ (`STOP_LOSS_GAP_OPEN`). If $O_m \le 	ext{Target}$, exits at $O_m$ (`TARGET_GAP_OPEN`).
2. **Conservative Same-Candle Stop/Target Collision (`STOP_LOSS_SAME_CANDLE_CONSERVATIVE`):**
   - Within a single 5-minute OHLC bar $m$, if **both** the stop-loss and target are reached inside $[L_m, H_m]$:
     - **Long:** $L_m \le 	ext{SL}$ and $H_m \ge 	ext{Target}$
     - **Short:** $H_m \ge 	ext{SL}$ and $L_m \le 	ext{Target}$
   - Because 5-minute OHLC bars do not reveal intra-candle tick sequence, the engine **always resolves the collision conservatively as a Stop-Loss hit at $	ext{SL}$** (`exit_reason = "STOP_LOSS_SAME_CANDLE_CONSERVATIVE"`, `same_candle_collision = True`). It never assumes the favorable target outcome.
3. **Standard Stop-Loss or Target Hit:**
   - If only $	ext{SL}$ is breached ($L_m \le 	ext{SL}$ for Long; $H_m \ge 	ext{SL}$ for Short), exits at $	ext{SL}$ (`STOP_LOSS`).
   - If only $	ext{Target}$ is breached ($H_m \ge 	ext{Target}$ for Long; $L_m \le 	ext{Target}$ for Short), exits at $	ext{Target}$ (`TARGET_1` or `TARGET_2`).
4. **Mandatory Intraday End-of-Session Square-Off (`EOD_SQUARE_OFF`):**
   - TradePulse AI strategies are strictly intraday (MIS) with no overnight carry-forward (`allow_overnight_carry = False`).
   - New entries are blocked at or after `last_entry_Cutoff_ist` (default `15:00 IST`).
   - Any position still open on a candle with start time $\ge 	exttt{eod\_square\_off\_ist}$ (default `15:20 IST`, or the final bar of the session/dataset) is forcibly squared off at that candle's close (`EOD_SQUARE_OFF`, `SESSION_END_SQUARE_OFF`, or `END_OF_DATASET_SQUARE_OFF`).

## 4. Configurable Indian Market Cost & Slippage Model (`IndianCostModel`)

Every simulated trade distinguishes between **execution slippage** and **itemized Indian statutory & exchange charges** (configured with effective date `2024-10-01` and marked `is_estimated_schedule = True` when historical rate schedules are user-configurable):

1. **Slippage (`slippage_bps_per_leg`, default `5.0 bps` = `0.05%` per leg):**
   - **Long:**
     $$P_{	ext{entry,eff}} = P_{	ext{entry,raw}} 	imes \left(1 + rac{s_{	ext{bps}}}{10000}ight), \quad P_{	ext{exit,eff}} = P_{	ext{exit,raw}} 	imes \left(1 - rac{s_{	ext{bps}}}{10000}ight)$$
   - **Short:**
     $$P_{	ext{entry,eff}} = P_{	ext{entry,raw}} 	imes \left(1 - rac{s_{	ext{bps}}}{10000}ight), \quad P_{	ext{exit,eff}} = P_{	ext{exit,raw}} 	imes \left(1 + rac{s_{	ext{bps}}}{10000}ight)$$
   - Total slippage cost in INR:
     $$	ext{Slippage}_{	ext{INR}} = |P_{	ext{entry,eff}} - P_{	ext{entry,raw}}| \cdot Q + |P_{	ext{exit,eff}} - P_{	ext{exit,raw}}| \cdot Q$$
2. **Turnover Definitions (Zero Double-Counting Across Entry & Exit Legs):**
   - For a `LONG` trade: $T_{	ext{buy}} = P_{	ext{entry,eff}} \cdot Q$, $T_{	ext{sell}} = P_{	ext{exit,eff}} \cdot Q$.
   - For a `SHORT` trade: $T_{	ext{sell}} = P_{	ext{entry,eff}} \cdot Q$, $T_{	ext{buy}} = P_{	ext{exit,eff}} \cdot Q$.
   - Total round-trip turnover: $T_{	ext{total}} = T_{	ext{buy}} + T_{	ext{sell}}$.
3. **Itemized Statutory & Exchange Schedule (Default NSE Cash Intraday `EQ`):**
   - **Brokerage (`brokerage_inr`):** Computed separately on the entry leg and exit leg with no double counting:
     $$B_{	ext{leg}} = \min\left(	exttt{brokerage\_per\_order\_inr},\; T_{	ext{leg}} 	imes 	exttt{brokerage\_max\_pct\_per\_leg}ight)$$
     Default: $\min(₹20.00,\; 0.03\% 	imes T_{	ext{leg}})$ per leg ($\le ₹40.00$ round-trip).
   - **Securities Transaction Tax (`stt_inr`):** Charged **only on the sell leg** ($T_{	ext{sell}}$):
     - Intraday Equity (`EQ`): $0.025\%$ ($0.00025 	imes T_{	ext{sell}}$)
     - Index/Stock Futures (`FUTIDX`/`FUTSTK`): $0.02\%$ ($0.0002 	imes T_{	ext{sell}}$)
     - Index/Stock Options (`OPTIDX`/`OPTSTK`): $0.10\%$ on sell premium ($0.001 	imes T_{	ext{sell}}$)
   - **NSE Exchange Transaction Charges (`exchange_txn_charge_inr`):** Applied to $T_{	ext{total}}$:
     - Cash Equity (`EQ`): $0.00297\%$ ($0.0000297 	imes T_{	ext{total}}$)
     - Futures (`FUTIDX`/`FUTSTK`): $0.00173\%$ ($0.0000173 	imes T_{	ext{total}}$)
     - Options (`OPTIDX`/`OPTSTK`): $0.03503\%$ ($0.0003503 	imes T_{	ext{total}}$)
   - **SEBI Turnover Fees (`sebi_charge_inr`):** ₹10 per crore ($0.0001\% = 0.000001 	imes T_{	ext{total}}$).
   - **Stamp Duty (`stamp_duty_inr`):** Charged **only on the buy leg** ($T_{	ext{buy}}$):
     - Intraday Equity (`EQ`): $0.003\%$ ($0.00003 	imes T_{	ext{buy}}$)
     - Futures (`FUTIDX`/`FUTSTK`): $0.002\%$ ($0.00002 	imes T_{	ext{buy}}$)
     - Options (`OPTIDX`/`OPTSTK`): $0.003\%$ ($0.00003 	imes T_{	ext{buy}}$)
   - **GST (`gst_inr`):** $18\%$ on $(	ext{Brokerage} + 	ext{Exchange Transaction Charges} + 	ext{SEBI Fees})$.
4. **Gross P&L, Total Costs & Net P&L Accounting Identity:**
   To avoid double-counting slippage in both price and charges:
   - $	ext{Gross P\&L}_{	ext{INR}}$ is computed from **raw unslipped fill prices**:
     $$	ext{Gross P\&L}_{	ext{INR}} = egin{cases} (P_{	ext{exit,raw}} - P_{	ext{entry,raw}}) \cdot Q & 	ext{if LONG} \ (P_{	ext{entry,raw}} - P_{	ext{exit,raw}}) \cdot Q & 	ext{if SHORT} \end{cases}$$
   - $	ext{Total Costs}_{	ext{INR}} = 	ext{Charges}_{	ext{INR}} + 	ext{Slippage}_{	ext{INR}}$
   - $	ext{Net P\&L}_{	ext{INR}} = 	ext{Gross P\&L}_{	ext{INR}} - 	ext{Total Costs}_{	ext{INR}}$

## 5. Position Sizing, Exposure & Daily Risk Controls (`BacktestConfig`)

1. **Configurable Capital & Daily Risk Defaults:**
   - `starting_capital_inr`: Default `₹1,00,000.00` (configurable via `BacktestConfig` or `BotConfig`).
   - `max_daily_loss_inr`: Default `₹2,000.00` (`MAX_DAILY_LOSS_INR` in `config.py`).
   - `daily_profit_target_inr`: Default `₹4,000.00` (`DAILY_PROFIT_TARGET_INR` in `config.py`).
   - `max_concurrent_positions`: Default `1` (`MAX_CONCURRENT_POSITIONS` in `config.py`).
2. **Position Sizing & Capital Exposure Cap:**
   - Risk budget per trade: $R_{	ext{budget}} = 	ext{Starting Capital} 	imes rac{	exttt{risk\_per\_trade\_pct}}{100}$.
   - Per-unit stop distance: $R_{	ext{unit}} = |P_{	ext{entry,eff}} - 	ext{SL}|$.
   - Raw risk-based quantity: $Q_{	ext{raw}} = \lfloor R_{	ext{budget}} / R_{	ext{unit}} floor$.
   - When `enforce_capital_exposure_limit = True` (default for cash equities), quantity is capped by available account equity:
     $$Q = \min\left(Q_{	ext{raw}},\; \lfloor 	ext{Current Equity} / P_{	ext{entry,eff}} flooright)$$
     If $Q < 1$, the trade is rejected with `INSUFFICIENT_CAPITAL`.
   - For derivatives (`FUTIDX`, `OPTIDX`), if `historical_lot_size` is not provided in validated metadata, the engine refuses to invent a lot size and blocks/rejects the trade (`MISSING_HISTORICAL_LOT_SIZE`).
3. **Daily Loss Limit & Daily Profit Target Accounting Convention:**
   - Daily P&L for session date $d$ is tracked net of all realized statutory charges and slippage:
     $$	ext{Daily Net P\&L}(d) = \sum_{k \in 	ext{Trades}(d)} 	ext{Net P\&L}_k$$
   - Because `max_concurrent_positions = 1`, while a trade is open its intrabar risk is bounded by its active stop-loss; once closed, $	ext{Daily Net P\&L}(d)$ is updated immediately.
   - If $	ext{Daily Net P\&L}(d) \le -	exttt{max\_daily\_loss\_inr}$, `daily_loss_limit_triggered` is set to `True` for session $d$ and all subsequent signals on session $d$ are rejected (`DAILY_LOSS_LIMIT_REACHED`).
   - If $	ext{Daily Net P\&L}(d) \ge +	exttt{daily\_profit\_target\_inr}$, `daily_profit_target_triggered` is set to `True` for session $d$ and all subsequent signals on session $d$ are rejected (`DAILY_PROFIT_TARGET_REACHED`).

## 6. Mathematical Definitions of Performance Metrics

Let $\mathcal{T} = \{1, \dots, N\}$ be the sequence of completed trades with net P&L $p_k = 	ext{Net P\&L}_k$, gross P&L $g_k = 	ext{Gross P\&L}_k$, total costs $c_k = 	ext{Total Costs}_k$, initial risk $r_k = R_{	ext{unit},k} \cdot Q_k$, and realized R-multiple $R_k = p_k / r_k$.

- **Winning, Losing, and Breakeven Trades:**
  $$N_{	ext{win}} = |\{k : p_k > 0\}|, \quad N_{	ext{loss}} = |\{k : p_k < 0\}|, \quad N_{	ext{flat}} = |\{k : p_k = 0\}|$$
- **Win Rate (%):**
  $$	ext{Win Rate (\%)} = egin{cases} rac{100 \cdot N_{	ext{win}}}{N} & 	ext{if } N > 0 \ 0.0 & 	ext{if } N = 0 \end{cases}$$
- **Gross P&L, Total Costs, and Net P&L:**
  $$	ext{Gross P\&L} = \sum_{k=1}^N g_k, \quad 	ext{Total Costs} = \sum_{k=1}^N c_k, \quad 	ext{Net P\&L} = \sum_{k=1}^N p_k$$
- **Average Win & Average Loss:**
  $$\overline{W} = egin{cases} rac{1}{N_{	ext{win}}} \sum_{p_k > 0} p_k & 	ext{if } N_{	ext{win}} > 0 \ 0.0 & 	ext{if } N_{	ext{win}} = 0 \end{cases}, \qquad \overline{L} = egin{cases} rac{1}{N_{	ext{loss}}} \sum_{p_k < 0} p_k & 	ext{if } N_{	ext{loss}} > 0 \ 0.0 & 	ext{if } N_{	ext{loss}} = 0 \end{cases}$$
- **Expectancy per Trade (INR):**
  $$E = egin{cases} rac{	ext{Net P\&L}}{N} & 	ext{if } N > 0 \ 0.0 & 	ext{if } N = 0 \end{cases}$$
- **Profit Factor & Safe Zero-Denominator Convention:**
  Let $W_{	ext{sum}} = \sum_{p_k > 0} p_k$ and $L_{	ext{sum}} = \sum_{p_k < 0} |p_k|$.
  - If $N = 0$ (or $W_{	ext{sum}} = 0$ and $L_{	ext{sum}} = 0$): `profit_factor = None`, `profit_factor_status = "UNDEFINED_ZERO_TRADES"`, `profit_factor_display = "N/A (0 trades)"`.
  - If $L_{	ext{sum}} = 0$ and $W_{	ext{sum}} > 0$: `profit_factor = None` (never a fabricated finite float), `profit_factor_status = "INFINITE_NO_LOSSES"`, `profit_factor_display = "INF_NO_LOSSES"`.
  - If $L_{	ext{sum}} > 0$: $	ext{PF} = 	ext{round}(W_{	ext{sum}} / L_{	ext{sum}}, 4)$, `profit_factor_status = "FINITE"`.
- **Maximum Drawdown (INR and %):**
  Let $E_0 = 	ext{Starting Capital}$ and $E_k = E_0 + \sum_{j=1}^k p_j$, with running peak $M_k = \max_{0 \le j \le k} E_j$.
  $$	ext{DD}_k = M_k - E_k, \quad 	ext{MaxDD}_{	ext{INR}} = \max_{0 \le k \le N} 	ext{DD}_k, \quad 	ext{MaxDD}_{\%} = \max_{0 \le k \le N} \left(rac{100 \cdot 	ext{DD}_k}{M_k}ight)$$
- **Return on Starting Capital (%):**
  $$	ext{ROI (\%)} = rac{100 \cdot 	ext{Net P\&L}}{E_0}$$
- **Average R-Multiple:**
  $$\overline{R} = egin{cases} rac{1}{N} \sum_{k=1}^N rac{p_k}{r_k} & 	ext{if } N > 0 \ 0.0 & 	ext{if } N = 0 \end{cases}$$

## 7. Chronological Train / Validation / Out-of-Sample Period Splitting

`split_sessions_chronologically(session_dates, train_ratio=0.60, validation_ratio=0.20)` partitions ordered trading sessions $S_1 < S_2 < \dots < S_D$ into strictly non-overlapping chronological segments:
- Requires $D \ge 3$ distinct trading sessions; if $D < 3$, reports `split_status = "INSUFFICIENT_SESSIONS_FOR_3WAY_SPLIT"` (`out_of_sample_possible = False`).
- When evaluating a target sub-period (`VALIDATION` or `OUT_OF_SAMPLE`), prior sessions are used strictly for causal indicator warm-up (such as the 200-bar EMA in Strategy 5), while trade entries and metrics are restricted to `[eval_start_date, eval_end_date]`.
