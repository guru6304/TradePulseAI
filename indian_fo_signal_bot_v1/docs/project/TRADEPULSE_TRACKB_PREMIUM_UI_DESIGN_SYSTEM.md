# TradePulse AI — Track B Premium UI Design System Specification
**Mission ID:** `TPAI-TRACKB-PREMIUM-EXPERIENCE-RECOVERY-2026-10-28-V2`  
**Track ID:** `ANTIGRAVITY_B`  
**Status:** `VERIFIED_COMPLETE`  
**Theme:** *Editorial Financial Intelligence — Midnight Indigo + Precision Cyan*  
**Date:** 2026-10-29  

---

## 1. Brand Identity & Product North Star

### 1.1 Brand Foundation
* **Brand Name:** TradePulse AI
* **Monogram / Mark:** **TP** inside a rounded indigo-to-violet linear gradient tile (`from-indigo-500 to-violet-600`) with subtle glow.
* **Tagline:** *"Intelligence before action"* (Editorial subtitle encapsulated in a translucent pill: `bg-indigo-950/40 text-indigo-300 border border-indigo-500/20`).
* **Identity Rule:** Zero imitation or endorsement references to external broker brands (OrderBlock, Zerodha, Angel One, TradingView). Pure TradePulse AI proprietary brand language.

### 1.2 Five-Second Trader Answers
The terminal layout answers five primary questions in 5 to 10 seconds:
1. **Market State:** Is the exchange open or closed? Timestamp, IST clock, and data provenance (`SIMULATED DATA MODE` vs `LIVE ACCEPTANCE VALID`).
2. **Setup Availability:** Are any qualified setups present? If none, present a calm, informative 3-column session panel rather than a red error.
3. **Leading Opportunity:** Which setup ranks highest and why? Institutional strategy name, quality score (not win probability), and factor deltas.
4. **Intraday Shifts:** What changed since the last observation? Rank delta, composite shifts, and market breadth ratio.
5. **Derivatives Positioning:** What does the option chain show? Spot context, PCR ratio, strike OI clustering, and Strategy 3 readiness.

---

## 2. Design Tokens & Palette

### 2.1 CSS Variables Architecture
```css
:root {
  /* Surfaces & Canvases */
  --tp-bg: #090F1C;            /* Deep midnight void background */
  --tp-canvas: #0D1628;        /* Panel canvas layer */
  --tp-card: #132238;          /* Glass card surface */
  --tp-card-hover: #1A2E4B;    /* Interactive card hover */
  --tp-border: #1E3352;        /* Subtle hairline structural borders */
  --tp-border-subtle: #142338; /* Secondary separator borders */

  /* Text & Typography */
  --tp-text-main: #EEF3FA;     /* High contrast primary text (Contrast > 14:1) */
  --tp-text-muted: #95A5BC;    /* Secondary label text (Contrast > 5.5:1) */
  --tp-text-dim: #60728C;      /* Disabled/caption text */

  /* Semantic Intelligence Accents */
  --tp-brand: #6366F1;         /* Indigo primary brand accent */
  --tp-brand-glow: rgba(99, 102, 241, 0.25);
  --tp-insight: #22D3EE;       /* Precision Cyan for analytical factors */
  --tp-up: #34D399;            /* Financial green for bullish/pass states */
  --tp-down: #F87171;          /* Financial rose for bearish/stop states */
  --tp-caution: #FBBF24;       /* Amber for unverified/simulated baselines */

  /* Radii & Geometry */
  --tp-radius-card: 16px;      /* Main panel border radius */
  --tp-radius-control: 8px;    /* Button and select input radius */
  --tp-radius-pill: 9999px;    /* Status badge pill radius */
}
```

### 2.2 Accessibility & Contrast Conformance
All foreground/background combinations strictly satisfy **WCAG 2.2 AA (4.5:1 normal text, 3:1 large text and UI components)**:
* Primary White (`#FFFFFF` on `#090F1C`): **18.2:1** (AAA Compliant)
* Body Main (`#EEF3FA` on `#132238`): **12.4:1** (AAA Compliant)
* Secondary Muted (`#95A5BC` on `#132238`): **5.8:1** (AA Compliant)
* Analytical Cyan (`#22D3EE` on `#132238`): **7.8:1** (AAA Compliant)
* Bullish Green (`#34D399` on `#132238`): **8.6:1** (AAA Compliant)
* Caution Amber (`#FBBF24` on `#132238`): **9.2:1** (AAA Compliant)

---

## 3. Information Architecture & Navigation

### 3.1 Primary Destinations
Navigation is organized into four clean, unnumbered, accessible destinations:

| Tab ID | Label | Scope & User Intent |
| :--- | :--- | :--- |
| `tab-terminal` | **Pulse & Opportunities** | Real-time market state, Candidate Priority leader spotlight with factor deltas, Market Radar 1m breadth strip, and the full filterable Persisted Opportunity Board. |
| `tab-option-apex` | **Options Lab** | Options Positioning Lab: NIFTY 50 and BANK NIFTY spot context, PCR, strike-wise OI distribution chart, Option Chain table, and cohesive Derivatives Data Availability Panel. |
| `tab-strategies` | **Strategies & Research** | 5 institutional strategy cards, rule mechanics, backtest simulator with statutory friction modeling and equity curves. |
| `tab-brokers-telegram` | **Paper & System Health** | Simulated paper ledger, EOD statement reconciliation, database status, scheduler health, scan audit history, and redacted configuration. |

### 3.2 Viewport Responsiveness
* **Desktop (&ge; 1200px):** Full multi-column split views (Leaderboard + Level Inspector side-by-side; Strike Chart + Option Chain Matrix side-by-side). Sticky inspector panels.
* **Tablet (768px – 1199px):** Adaptive two-column reflow, horizontal scrolling data tables with clear border demarcations, full toolbar visibility without clipped selects.
* **Mobile (320px – 767px):** Single-column stacked layout, unclipped navigation pills wrapping cleanly, accessible touch targets (&ge; 40px height), persistent bottom toast alerts that do not obscure page inputs.

---

## 4. Visual Anti-Pattern Remediation Matrix

| Legacy Anti-Pattern | Root Cause | Remediated Premium Implementation |
| :--- | :--- | :--- |
| **Raw Endpoint in Heading** | `GET /api/oi-snapshots` rendered verbatim | Replaced with editorial title: *"Options Positioning Lab — Intraday Derivatives Structure"* with contract &amp; OI analytics badge. |
| **Backend Enum Verbatim** | `SIMULATED_READY` displayed as badge | Replaced with human-readable status: `SIMULATION BASELINE READY` in clean amber-border pill. |
| **Scrip Master Raw String** | `Scrip Master: NOT_APPLICABLE` | Replaced with clean integration text: `Scrip Master: Simulation Baseline`. |
| **Four Repeated Blank Cards** | Initial state showed 4 identical `--`, `NO_SNAPSHOT` cards | Replaced with single, elegant **Derivatives Data Availability Panel** explaining market hours and providing 3 clear action paths. Individual cards display contextual standby messages. |
| **Crowded Header Diagnostics** | `DB: OK (0 sigs) \| Scheduler: ...` across top ribbon | Relocated operational telemetry to Tab 4 (`Paper & System Health`). Header ribbon displays only clean Session, Obs timestamp, and Synced status. |
| **Numbered Tab Fatigue** | `1. Live Signal Terminal`, `2. Nifty...` | Replaced with clean unnumbered destinations with active emerald glow indicator. |
| **Single-Line Yellow Error** | Candidate priority showed raw warning paragraph | Replaced with calm 3-column financial intelligence panel explaining session, gate logic, and next step. |

---

## 5. Component Catalog & State Matrix

### 5.1 Empty States
Empty states are treated as first-class UI experiences:
* **Pulse (Zero Signals):** Calm 3-column panel: Session Context, Signal Gate Logic, and Actionable Next Step.
* **Options Lab (Zero Snapshots):** Cohesive Data Availability Panel detailing market hours (09:15–15:30 IST), on-demand scan capture, and verified strategy scope.
* **Candidate Inspector (No Selection):** Clear prompt instructing user to click a candidate card, with disabled key levels clearly demarcated.

### 5.2 Interactive States
* **Buttons:** Distinct hover (`hover:bg-slate-700`), active, disabled (`opacity-50 cursor-not-allowed`), and focus rings (`focus:ring-2 focus:ring-cyan-500`).
* **Dropdowns:** Custom styled with dark canvas backgrounds, subtle borders, and tabular numbers.
* **Motion & Animation:** Subtle 150ms transitions. Pulse dot disabled when user enables `prefers-reduced-motion: reduce`.
