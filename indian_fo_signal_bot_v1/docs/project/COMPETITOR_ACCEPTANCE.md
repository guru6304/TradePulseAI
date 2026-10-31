# Competitor references and product acceptance

Mission: `TPA-MAIN-RECOVERY-TO-RELEASE-20261029-V3`. Public references checked **29 October 2026**. Public competitor research remains source inspection without authenticated competitor access, a usability study or measured superiority. Current TradePulse browser, HTTP and clock evidence is bounded below. Competitor image retrieval was incomplete; no rendered competitor comparison is claimed. No competitor assets, branding, code or proprietary formulas were copied.

## Public claims and transferable patterns

| Official reference | Confirmed published claim | Transferable pattern; limit |
|---|---|---|
| [OrderBlock home](https://order-block.com/) and [About](https://order-block.com/about) | Describes directional F&O strength rankings refreshed every minute, with sector flow and breadth. | Separate market movement from strategy qualification. Rank refresh alone does not distinguish TradePulse. These are publisher descriptions, not independently measured coverage or accuracy. |
| [OrderBlock popup guide](https://order-block.com/blog/read-order-block-popup), dated 8 September 2026 | Explains rank, selection reason, zone, invalidation and reward/risk in a consistent reading sequence. | Make qualification and invalidation easy to locate. Do not copy its layout, terminology, selection formula or illustrative levels. |
| [TradeFinder](https://tradefinder.in/) | Advertises options analysis, market pulse, sector tools, instrument monitoring and research workflows. | Organize around customer tasks rather than an unstructured feature inventory. Marketing claims do not establish predictive performance or internal algorithms. |
| [Linear refresh](https://linear.app/now/behind-the-latest-design-refresh), dated 12 March 2026 | Describes subdued navigation, predictable headers, reduced icon emphasis and softer separators. | Give analytical content visual priority; make controls predictable. This is a design principle, not a screen to reproduce. |
| [TradingView screener heatmap](https://www.tradingview.com/blog/en/heatmap-view-in-screener-60678/) | Documents alternate views preserving the same filters and symbols, with selection opening details or changing chart context. | Preserve filters and instrument selection across views. A heatmap is optional and requires genuine comparable data; no borrowed screenshots. The fetched page displayed September 9 without an explicit year. |
| [Kite product](https://zerodha.com/products/kite/) and [official marketwatch manual](https://kite.trade/docs/kite/marketwatch/) | Describe universal instrument search, keyboard navigation, sorting and explicit market/contract fields. | Make exact instruments searchable and keyboard accessible. Brokerage execution controls and advertised latency are not TradePulse requirements or accepted measurements. |

## Original product direction

**TradePulse AI — Intelligence Terminal** should answer: what is currently qualified, why its rank changed, where the setup becomes invalid, and how fresh the evidence is. Use graphite/navy surfaces, restrained violet identity, teal/coral direction and amber uncertainty; tune contrast through measurement. Quiet desktop sidebar and compact global source header; working mobile navigation and browser history. Replace current co-branding with original TradePulse identity.

The intended journey is Pulse → qualified candidate → Opportunity X-Ray → optional Options contract viability → paper outcome. Market Radar stays observational and separate from qualified rankings. No-signal and unavailable-source states should explain the next useful action without manufacturing a candidate. Five primary destinations plus Health utility follow the V3 master; they are not additional project phases. UI implementation follows consequential B01.5b integrity guardrails.

## Existing API parity map

Paths below describe existing backend contracts and the parity still required from each destination. The bounded browser evidence below does not establish complete API parity. `/api/v1` aliases remain part of backend parity.

| Destination | Existing foundation | Preserve or explicitly qualify |
|---|---|---|
| Pulse | `/api/health`, `/api/opportunity-rankings`, `/api/paper-portfolio` | Current versus archived ranking, source age, unavailable factors, useful no-signal state; no invented breadth. |
| Opportunities | `/api/signals`, rankings, `/api/cash-candles`, `/api/scan-lineage`, context APIs | Pagination and filters, selected identity, rule/context evidence, expiry and stale-response protection. Candle display requires actual retained input. |
| Options Lab | `/api/oi-snapshots`, `/api/oi-baselines`, `/api/contract-masters`, `/api/contract-resolution` | Underlying signal versus exact premium contract; expiry/strike/CE/PE and source timestamps. Missing rights, spread, Greeks or observations remain unavailable. |
| Strategies & Research | Existing strategy/evidence metadata; historical readiness, eligibility and backtest-run APIs | Five existing strategy contracts and maturity; experimental rules separate; authentic result eligibility. |
| Paper Portfolio | `/api/paper-accounts`, `/api/paper-portfolio`, `/api/paper-ledger`, `/api/paper-session` | Bounded cursor pages, rejected/pending decisions, trigger evidence, stale marks, fees, EOD and reconciliation failures. GET/HEAD remain read-only. |
| Health & Settings utility | `/api/health`, `/api/config`, `/api/scans`, `/api/notification-outbox` | Protected operational diagnostics, scan history, sanitized errors and safe flags. No secret values or execution controls. |

Current entry aliases serve `public/terminal.html` with local `terminal.js` and `terminal.css`; the terminal implements hash navigation, mobile More navigation, browser Back and direct Paper links. Retained `public/index.html` is a developer parity reference containing the earlier four-tab application. Existing safe text rendering, async generation guards, rank expiry, pagination and read-only refresh remain required across further work. Explicit `POST /api/scan` remains separate from navigation and refresh and is not blanket provider authorization.

The current terminal X-Ray draws retained OHLC bars only after matching signal identity/time, committed lineage, five-minute metadata and the final watermark. It rejects same-session timing gaps and keeps missing charts unavailable. Legacy `public/index.html` still contains a price-level chart, hardcoded illustrative backtest returns and external dependencies; those retained implementations are not accepted as candle history, empirical results or the served terminal bundle.

## Bounded accepted evidence and remaining acceptance

- [Served HTTP evidence](../evidence/track_a_v3_terminal_http_20261029_01.json): **2/2 tests passed** for exact local entry/script/style bytes, GET/HEAD behavior, CSP/security headers and private-path rejection without initializing application runtime. This static serving proof does not establish production API data correctness.
- [Chrome V4](../evidence/track_a_v3_browser_v4_chrome_clock_20261029_01.json) and [Edge V4](../evidence/track_a_v3_browser_v4_edge_clock_20261029_01.json): **68/68 checks passed per browser** using actual terminal assets and authored loopback HTTP fixtures. Each run retained exactly four selected Pulse screenshots: fresh no-source and explicit synthetic demo at 1440 x 900 and 390 x 844. Checks cover distinct health error/no-source/demo states, synthetic rank reversal, symbol search, exact retained-chart linkage, safe text rendering, Slash/Escape, six route titles, mobile More, Back/direct Paper navigation, expiry clearing, seven viewport overflow probes, named controls and a sampled body-text contrast ratio. External and POST transports were blocked; this is not OS packet-capture evidence.
- [Clock regression evidence](../evidence/track_a_v3_clock_after_20261029_02.json): **2/2 parent suites enforce 18/18 child methods**, nine each under UTC and America/New_York with no failed/cancelled/skipped child methods. V4 independently used CDP timezone overrides for UTC desktop and America/New_York mobile. Backend-format naive IST health/signal/bar timestamps matched an offset-qualified ranking watermark; source, signal and final candle all read **16 Oct, 10:00 IST** in the browser DOM. The mobile global source-time element is hidden by the existing responsive CSS; DOM equality does not prove that header timestamp is visibly available on mobile.

These receipts use authored data and no operational database or provider access. They do not establish current live admission, real-source chart lineage, complete destination parity, accessible focus preservation, human usability, measured latency, competitor superiority or release readiness.

No claim is made that TradePulse exceeds these products in returns, accuracy, speed, usability or coverage. Planned evidence must compare defined tasks and equivalent source/data assumptions, rather than promotional statements.

- W4 must complete Opportunities/X-Ray parity: filtering currently applies only to the loaded ranking page, pagination disappears on a zero-match page, refresh closes X-Ray, and selection/focus preservation across reorder is unestablished. The rank API accepts only run/limit/offset; the retained-signal API separately supports its existing server filters. Entry zones, rule checks, context qualification, strategy maturity and paper-decision details supplied by the backend are not yet fully exposed in X-Ray. Ranking failure, archived evidence, an empty current scan and filter no-match also need distinct customer states.
- Extend the existing browser navigation/chart checks to real pagination/filter contracts, stable selection, delayed/error response races and safe focus restoration. All-destination API parity and those W4 behaviors remain unaccepted.
- Measure keyboard/focus continuity, reduced-motion behavior and full WCAG 2.2 AA criteria. Existing named-control, overflow and body-text contrast samples are limited checks, not accessibility certification.
- Preserve distinct live-verified, simulation/demo, replay, delayed, last-session, closed, no-signals, no-source, no-rights, error and loading states according to actual evidence. Never infer live admission from HTTP200.
- Target a later five-participant study: locate source status, top qualified candidate or none, rank reason, invalidation and freshness in 10–20 seconds. Participant results, task-time improvement and competitor comparison remain **NOT_ESTABLISHED**.
- Selected screenshots and bounded scripted interactions now exist. Render/update latency, human task performance, broad interaction stability and complete mobile parity remain unestablished. Retain private development evidence separately from customer release artifacts.

Official references inform design; they do not establish this application's compliance, source rights, strategy edge, live acceptance or release readiness.
