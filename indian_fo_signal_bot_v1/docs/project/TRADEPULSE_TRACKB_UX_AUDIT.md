# TradePulse AI — Track B Premium UI/UX Senior Design Audit
**Mission ID:** `TPAI-TRACKB-UX-2026-10-28-V1`  
**Track ID:** `ANTIGRAVITY_B`  
**Baseline Git Revision:** `0eca20fdd03029f37104047f95d59906884244b0`  
**Evaluation Viewport:** 1832 × 917 Desktop Reference  
**Timestamp:** 2026-10-28T23:30:00+05:30  

---

## 1. Executive Summary & Objective

This document records an independent senior design audit of the TradePulse AI Track B terminal as captured in the owner's desktop screenshot (1832 × 917 resolution) and verified against `public/index.html`, `server.py`, and the client-side JavaScript runtime.

The core goal of this audit is to identify every friction point, visual weakness, and cognitive gap in the current interface, establishing a disciplined roadmap to transform TradePulse AI into an original, institutional-grade trading intelligence terminal that commands immediate user trust.

---

## 2. Evaluation Scorecard (1–10 Scale)

| Evaluation Dimension | Score (1–10) | Key Finding / Rationale | Target Score |
| :--- | :---: | :--- | :---: |
| **Visual Identity** | **4 / 10** | Legacy "OB" badge and "TradePulse × OrderBlock AI" branding created derivative confusion. Developer-facing "PHASE 1E INTEGRATED" text weakened institutional feel. | **9 / 10** |
| **Information Hierarchy** | **4 / 10** | Uniformly dark bordered containers give equal visual weight to diagnostics, filters, radar, and priority cards. Primary answers are not immediately distinguishable. | **9 / 10** |
| **Information Density** | **5 / 10** | Prime screen real estate is consumed by raw technical strings (`DB: OK`, `Scheduler: DISABLED`) while candidate setup details are pushed below the first fold. | **9 / 10** |
| **Navigation & Flow** | **6 / 10** | Four main tabs are structurally sound, but stacked sub-ribbons and crowded action buttons compete for user focus. | **9 / 10** |
| **Trading Clarity** | **5 / 10** | The first 5 seconds fail to answer: *"Is there an actionable trade right now, and if not, why?"* | **9 / 10** |
| **Trust & Provenance** | **6 / 10** | Backend data provenance is honest, but UI labels like "NSE Live Simulation / Paper Engine (SIMULATED)" combine conflicting keywords (Live vs Simulation vs Paper). | **9 / 10** |
| **Data Lineage Presentation**| **7 / 10** | Backend maintains clean timestamps and source watermarks, but UI displays them in cramped microtext. | **9 / 10** |
| **Responsive Composition** | **7 / 10** | Layout handles viewports down to 320px via CSS flex/grid, but desktop first-fold experience is poorly prioritized. | **9 / 10** |
| **Accessibility (WCAG AA)** | **6 / 10** | High color contrast passes, but small font sizes (10–11px) on status badges and tight tap targets need improvement. | **9 / 10** |
| **Perceived Performance** | **7 / 10** | Zero layout shifts, but frequent UI polling text updates create visual noise. | **9 / 10** |
| **Empty-State Utility** | **3 / 10** | "Candidate priority unavailable: no qualified retained ranking for this source and universe" reads like an unhandled software exception rather than a calm, valid market reality. | **9 / 10** |
| **Interaction Quality** | **6 / 10** | Filter dropdowns and refresh buttons work, but lack clear interactive affordances and state transitions. | **9 / 10** |

**Overall Baseline Weighted Score:** **5.3 / 10**  
**Post-Transformation Target:** **9.0+ / 10**

---

## 3. Detailed Finding Inventory

### Finding 1: Derivative & Developer-First Branding (P0)
* **Observed UI:** Header logo displayed "OB" with title "TradePulse × OrderBlock AI" and badge "PHASE 1E INTEGRATED".
* **Impact:** Implies an unauthorized white-label clone of competitor OrderBlock. Developer phase numbers alienate traders.
* **Remediation:** Replace with original "TP" monogram in indigo/violet brand gradient, title "TradePulse AI Terminal", and subtle tagline "Intelligence before action". Move phase metadata into System Health diagnostics.

### Finding 2: Unhelpful Zero-Signal Hero State (P0)
* **Observed UI:** Large card titled "Candidate priority" displaying single yellow line: `"Candidate priority unavailable: no qualified retained ranking for this source and universe."`
* **Impact:** Makes the application appear broken or empty during non-market hours or when zero setups qualify.
* **Remediation:** Build a purposeful, calm **No Qualified Opportunities** hero state explaining:
  1. *Exact Reason:* Market session closed / awaiting next completed 5m bar / no candidate passed all 5 strategy gates.
  2. *Developing Watch Count:* Number of setups currently in radar or early formation.
  3. *Last Evaluated Bar:* Timestamp of last completed candle.
  4. *Next Action:* Next scheduled evaluation window during market hours.

### Finding 3: Operational Diagnostics Polluting First Fold (P1)
* **Observed UI:** Second header ribbon displayed: `DB: OK (0 sigs) | Source Obs (IST): None | Scheduler: DISABLED (Opt-In) | Session: after_session_close | Last Scan: No scan in current process | UI Poll: 23:11:00`.
* **Impact:** Pushes actionable market content down by ~50px and displays low-level database health to business users.
* **Remediation:** Relocate raw database, scheduler, and polling logs into Tab 4 ("System Health & Diagnostics"). Keep only essential session status (`NSE: CLOSED` / `OPEN`) and data mode (`SIMULATED DATA MODE` / `LIVE`) in the top navigation bar.

### Finding 4: Filter Controls Above Content (P1)
* **Observed UI:** Five filter dropdowns (Market Segment, Strategy Engine, Direction, Data Mode, Symbol Filter) take full width above the fold, before any candidates are visible.
* **Impact:** Inverted hierarchy. Users must filter before seeing if any opportunities exist.
* **Remediation:** Anchor filters alongside or directly above the opportunity grid with compact pill selectors, preserving selection across background polling.

### Finding 5: Market Radar Identical Data & Non-Actionable Boundary (P1)
* **Observed UI:** Market Radar cards show identical simulated numbers (+1.20% and 30.0/100 move).
* **Impact:** Looks like hardcoded placeholder cards rather than an analytical engine.
* **Remediation:** Render diverse realistic benchmark fixtures when in simulated mode, showing distinct bullish/bearish ATR50 normalized metrics, accompanied by a tooltip explaining the formula and confirming that 1m radar is strictly non-actionable.

### Finding 6: Monochromatic "Dark Rectangle" Surface Fatigue (P2)
* **Observed UI:** Every section uses the identical `#0f172a` slate-900 background with thin border, creating a flat wall of dark boxes without clear depth.
* **Impact:** High cognitive strain; hard to quickly spot the #1 ranked opportunity.
* **Remediation:** Implement a 3-tier surface elevation system (`--tp-bg: #090F1C;`, `--tp-surface: #101B2D;`, `--tp-surface-raised: #152238;`) with restrained indigo accents and luminous green/coral indicators.

---

## 4. Prioritized Implementation Backlog

| Wave | Focus Area | Deliverables |
| :---: | :--- | :--- |
| **Wave 1** | **Design System Foundation** | Design tokens, typography hierarchy, Midnight Graphite + Indigo theme, header trust bar, session clock. |
| **Wave 2** | **High-Value First Screen** | Purposeful No-Opportunity calm hero state, Top Opportunity (#1) spotlight card, compact #2/#3 rows, Market Radar observation leaderboard. |
| **Wave 3** | **Opportunity X-Ray & Interactive Depth** | 5m OHLC chart levels, factor deltas table, plain-English "Why #1 Now" badge, F&O contract subpanel, diagnostics drawer. |
| **Wave 4** | **Usability, Accessibility & Polish** | 4-viewport responsive validation (1832px down to 320px), WCAG 2.2 AA contrast, keyboard navigation, touch targets. |
| **Wave 5** | **Verification & Proof** | Node.js DOM tests (40+), Python unit tests (1,210+), headless Chrome CDP probes, before/after screenshot captures. |
