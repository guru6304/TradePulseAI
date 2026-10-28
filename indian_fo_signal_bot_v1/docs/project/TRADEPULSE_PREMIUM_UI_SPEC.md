# TRADEPULSE AI — PREMIUM UI SPECIFICATION
**Terminal Name:** TradePulse Intelligence Terminal  
**Track ID:** `ANTIGRAVITY_B`  
**Baseline ID:** `BASELINE_20261028_ASTRA_ULTRA_CANDIDATE_01`  
**Date:** `2026-10-28`  
**Target Viewports:** Desktop (1440px+), Laptop (1024–1366px), Tablet (768px), Mobile (360–390px), Narrow (320px)  

---

## 1. Visual Identity & Design Tokens

### 1.1 Color Palette (Dark-First Philosophy)
To avoid generic/unattractive aesthetics and avoid imitating competitor visuals, TradePulse uses a custom curated color system:

| Token Name | Hex Code | Role & Usage |
| :--- | :--- | :--- |
| `--bg-base` | `#0b0f19` | Deepest background shell (midnight graphite) |
| `--bg-surface` | `#111827` | Primary card and panel surface (slate charcoal) |
| `--bg-elevated` | `#1f2937` | Hover states, modals, and dropdown overlays |
| `--border-subtle` | `#374151` | Hairline panel borders (1px solid) |
| `--accent-primary` | `#6366f1` | Brand accent: Indigo violet (buttons, active tabs) |
| `--accent-glow` | `rgba(99, 102, 241, 0.15)` | Subtle ambient focus ring (no gratuitous neon) |
| `--bullish` | `#10b981` | Emerald green (positive price action, buy triggers) |
| `--bearish` | `#f43f5e` | Calibrated rose crimson (negative price action, sell triggers) |
| `--warning-amber` | `#f59e0b` | Caution state, data latency, or developing setup |
| `--text-primary` | `#f9fafb` | Primary text high-contrast (WCAG AAA compliant) |
| `--text-secondary` | `#9ca3af` | Secondary labels, metrics, timestamps |
| `--text-muted` | `#6b7280` | Table headers, units, disabled states |

### 1.2 Typography
- **Primary Interface Font:** Inter (`Inter-Regular`, `Inter-Medium`, `Inter-SemiBold`, `Inter-Bold`)
- **Tabular & Numeric Font:** JetBrains Mono (`JetBrainsMono-Regular`, `JetBrainsMono-Bold`) for prices, percentages, strike prices, and timestamps.
- **Font Scale:** `xs` (11px), `sm` (12px), `base` (14px), `lg` (16px), `xl` (20px), `2xl` (24px).

---

## 2. Information Architecture & Layout Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TRADEPULSE AI   NSE: OPEN [09:15-15:30 IST]  Provider: AngelOne   Search 🔍 │
├───────────┬─────────────────────────────────────────────────────────────────┤
│ [Radar]   │ TODAY'S QUALIFIED OPPORTUNITIES (Top 0-3 Actionable)           │
│ [Setups]  │ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐        │
│ [X-Ray]   │ │ #1 RELIANCE    │ │ #2 INFY        │ │ #3 TCS         │        │
│ [Paper]   │ │ OB Retest 88.5 │ │ VWAP Pull 82.0 │ │ ST Pull 76.0   │        │
│ [Data]    │ └────────────────┘ └────────────────┘ └────────────────┘        │
│           ├────────────────────────────┬────────────────────────────────────┤
│           │ MARKET RADAR (1m Cadence)  │ LIVE QUALIFIED BOARD (5m Setups)   │
│           │ • Breadth: 32 Adv / 18 Dec │ Rank Δ │ Symbol │ Strategy │ Net RR│
│           │ • Sector Momentum Leader   │ ▲1     │ RELI   │ OB Retest│ 1:2.4 │
│           │ • Day-Open Norm Movement   │ ▼1     │ INFY   │ VWAP Pull│ 1:2.1 │
│           ├────────────────────────────┴────────────────────────────────────┤
│           │ OPPORTUNITY X-RAY (Interactive Chart Drilldown)                 │
│           │ • Completed 5m Candles with Zone Overlay (OB / FVG / VWAP)      │
│           │ • Limit Entry Line, Invalidation Level, Target 1 & Target 2    │
│           │ • Factor Delta Explanation: "Why #1 Now over #2"                │
│           ├─────────────────────────────────────────────────────────────────┤
│           │ SYSTEM RELIABILITY: Feed Age: 1.2s • DB: OK • Risk Cap: 3/3 Pos │
└───────────┴─────────────────────────────────────────────────────────────────┘
```

---

## 3. Responsive Breakpoint Adaptation
1. **Desktop (1440px+)**: 3-column split view (Nav rail + Radar/Board + X-Ray drilldown side-by-side).
2. **Laptop (1024–1366px)**: Collapsible nav rail, 2-column layout.
3. **Tablet (768px)**: Tabbed navigation with horizontal scrolling cards.
4. **Mobile (360–390px)**: Single-column vertical stack. Top Opportunity pinned at top; X-Ray opens in an accessible bottom sheet modal with touch-friendly targets (minimum 44x44px).
5. **Narrow (320px)**: Zero horizontal overflow; compact numeric typography.

---

## 4. Truthful Market & Data States
- `LIVE_VERIFIED`: Active NSE trading session (09:15–15:30 IST), completed candles authenticated, feed latency < 3.0s.
- `MARKET_CLOSED`: Out-of-session; header badge indicates "NSE: CLOSED"; prices clearly labeled "LAST SESSION CLOSE".
- `DATA_STALE`: Observation age exceeds threshold; scanner revokes live signals and displays amber caution indicator.
- `UNAVAILABLE`: Broker connection down or unconfigured; displays explicit reason code (`OFFLINE_FEED_UNAVAILABLE`).
- `NO_SIGNALS`: Clean market regime with zero qualified setups; clearly displays "NO ACTIONABLE OPPORTUNITY — PRESERVING CAPITAL" rather than forcing trades.

---

## 5. Verification & Test Evidence
- **Browser Automation Suite:** [`docs/evidence/astra_browser_assets_verify_20261027_01.py`](file:///c:/Users/91810/OneDrive/Documents/Trade%20Pulse%20AI/TradePulseAI/indian_fo_signal_bot_v1/docs/evidence/astra_browser_assets_verify_20261027_01.py)
- **Results:** 138 / 138 checks passed across Desktop, Tablet, Mobile, and Narrow viewports with zero horizontal overflow, full ARIA attributes, and local asset resolution ([`docs/evidence/astra_browser_assets_20261028_01.json`](file:///c:/Users/91810/OneDrive/Documents/Trade%20Pulse%20AI/TradePulseAI/indian_fo_signal_bot_v1/docs/evidence/astra_browser_assets_20261028_01.json)).
- **Unit Contract Suite:** 38 / 38 assertions pass in `test_cash_dashboard.js`.
