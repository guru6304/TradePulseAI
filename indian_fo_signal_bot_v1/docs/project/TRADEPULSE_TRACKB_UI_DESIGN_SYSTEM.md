# TradePulse AI — Track B UI/UX Design System Specification
**Mission ID:** `TPAI-TRACKB-UX-2026-10-28-V1`  
**Track ID:** `ANTIGRAVITY_B`  
**Design System Name:** *Midnight Graphite + Indigo Intelligence*  
**Version:** 1.0.0  

---

## 1. Brand Identity & Visual Language

### 1.1 Brand Positioning
TradePulse AI is an institutional-grade opportunity intelligence terminal for Indian equities and F&O derivatives. The design philosophy is:
> **"Intelligence before action"** — High signal-to-noise ratio, calm financial authority, truthful data provenance, and unambiguous distinction between observational radar and actionable qualified setups.

### 1.2 Brand Assets
* **Monogram / Mark:** **TP** inside an indigo-to-violet gradient container (`#6366F1` to `#7C3AED`) representing changing market rhythm and rising ranked setups.
* **Prohibited Visuals:** Zero imitation of OrderBlock's directional drawings, cards, or logos. Zero TradeFinder terminology clones.

---

## 2. Color Tokens & Palette

### 2.1 Dark Mode (Primary Institutional Default)
```css
:root {
  /* Surfaces & Backgrounds */
  --tp-bg: #090F1C;              /* Deep midnight canvas */
  --tp-surface: #101B2D;         /* Base card & panel container */
  --tp-surface-raised: #152238;  /* Elevated active card & inspector */
  --tp-surface-subtle: #0D1626;  /* Inset metric wells and chart background */
  --tp-border: #27354A;          /* Crisp structural divider */
  --tp-border-subtle: #1C283A;   /* Secondary divider */

  /* Typography */
  --tp-text: #EEF3FA;            /* High-contrast primary reading */
  --tp-muted: #9BACBF;           /* Metric labels & metadata */
  --tp-dim: #607289;             /* Disabled & background timestamps */

  /* Brand Accents */
  --tp-brand: #8B85FF;           /* Primary interactive accent */
  --tp-brand-soft: #24234B;      /* Brand badge fill */
  --tp-cyan: #59C8E7;            /* Informational indicators */

  /* Semantic Trading Statuses (WCAG AA Compliant) */
  --tp-positive: #34C7A1;        /* Bullish / Profit / Verified */
  --tp-positive-soft: rgba(52, 199, 161, 0.12);
  --tp-negative: #F17F90;        /* Bearish / Stop Loss / Rejection */
  --tp-negative-soft: rgba(241, 127, 144, 0.12);
  --tp-caution: #F1C16B;         /* Stale feed / Non-actionable radar */
  --tp-caution-soft: rgba(241, 193, 107, 0.12);

  /* Geometry & Rhythm */
  --tp-radius-card: 16px;
  --tp-radius-control: 10px;
  --tp-radius-badge: 6px;
  --tp-space-unit: 8px;
}
```

### 2.2 Light Mode (Secondary Token Set)
```css
html.light {
  --tp-bg: #F8FAFC;
  --tp-surface: #FFFFFF;
  --tp-surface-raised: #F1F5F9;
  --tp-surface-subtle: #E2E8F0;
  --tp-border: #CBD5E1;
  --tp-border-subtle: #E2E8F0;
  --tp-text: #0F172A;
  --tp-muted: #475569;
  --tp-dim: #94A3B8;
  --tp-brand: #6366F1;
  --tp-brand-soft: #EEF2FF;
  --tp-cyan: #0284C7;
  --tp-positive: #059669;
  --tp-positive-soft: rgba(5, 150, 105, 0.10);
  --tp-negative: #E11D48;
  --tp-negative-soft: rgba(225, 29, 72, 0.10);
  --tp-caution: #D97706;
  --tp-caution-soft: rgba(217, 119, 6, 0.10);
}
```

---

## 3. Typography Hierarchy

| Level | Size | Weight | Tracking | Usage |
| :--- | :---: | :---: | :---: | :--- |
| **Page Title** | 24px (1.5rem) | 800 (Extrabold) | -0.025em | Main application header |
| **Section Header** | 18px (1.125rem) | 700 (Bold) | -0.015em | Top Opportunity, Market Radar, Inspector |
| **Subheader / Tab** | 14px (0.875rem) | 600 (Semibold) | Normal | Tab labels, card titles |
| **Body Text** | 14px (0.875rem) | 400 (Regular) | Normal | Setup explanations, rationale |
| **Metric Label** | 12px (0.75rem) | 600 (Semibold) | 0.05em (Caps) | Key-value labels (R:R, ATR50, IST Time) |
| **Tabular Monospace** | 13–15px | 600 (Semibold) | Tabular | Prices, ticks, percentages, delta values |

Font Families:
* Sans: `'Inter', system-ui, -apple-system, sans-serif`
* Monospace: `'JetBrains Mono', monospace` (enforcing `font-variant-numeric: tabular-nums`)

---

## 4. Semantic Status Architecture

| Status Category | Possible States | Visual Presentation |
| :--- | :--- | :--- |
| **Exchange Session** | `NSE: OPEN` (09:15–15:30 IST)<br>`NSE: CLOSED`<br>`HOLIDAY`<br>`SPECIAL_SESSION` | Green dot when open; neutral slate pill when closed. Explicit IST session hours. |
| **Data Provenance** | `LIVE_VERIFIED`<br>`SIMULATED DATA MODE`<br>`REPLAY`<br>`UNAVAILABLE` | Never conflated. `SIMULATED` displayed in distinct amber/violet badge. |
| **Setup Actionability**| `QUALIFIED ACTIONABLE`<br>`DEVELOPING (NON-ACTIONABLE)`<br>`INVALIDATED`<br>`EXPIRED` | Radar is always badged `NON-ACTIONABLE`. Actionable setups require completed 5m bar and passed strategy confirmation gates. |
| **Ranking Transitions**| `RANK #1 LEADER`<br>`PROMOTED (+1)`<br>`DROPOUT (DISQUALIFIED)` | Explicit factor deltas table explaining composite, confluence, and R:R changes. |

---

## 5. Layout & Responsive Composition

### 5.1 Desktop Viewport (1832px & 1440px)
* **First Fold Promise:**
  1. Header Trust Bar (Brand, Exchange State, Data Mode, Clock, Scan Trigger).
  2. Hero Section: Top Qualified Opportunity Spotlight (#1) or calm Purposeful No-Opportunity State.
  3. Market Radar Deck: 1m broad observation layer with Adv/Dec breadth counters and top mover cards.
  4. Interactive Inspector: 5m OHLC chart and Factor Deltas breakdown.
* **Secondary:** Paper Portfolio, Strategy Evidence Backtester, Diagnostics.

### 5.2 Mobile Viewport (390px & 360px)
* Single-column vertical flow with zero horizontal scrolling (`overflow-x: hidden`).
* Touch targets strictly minimum `44 × 44px`.
* Sticky compact header with session state and shortlist access.
* Drilldown charts expand smoothly inside a full-width bottom sheet.

---

## 6. Accessibility & Interaction Standards (WCAG 2.2 AA)
* **Color Contrast:** Minimum 4.5:1 for normal text and 3.0:1 for large graphical elements.
* **Focus States:** High-visibility focus rings (`focus:ring-2 focus:ring-indigo-400 focus:outline-none`).
* **Motion Reduction:** All pulse and glow animations automatically set to `animation: none` under `@media (prefers-reduced-motion: reduce)`.
* **Zero innerHTML:** Complete mitigation of DOM XSS vulnerabilities via safe programmatic DOM creation (`document.createElement`, `textContent`).
