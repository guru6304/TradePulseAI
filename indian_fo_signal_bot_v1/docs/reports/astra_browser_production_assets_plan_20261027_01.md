# E01.2b exact next implementation, 2026-10-27

Status: READ_ONLY_PREPARATION; no new browser, download, visual or accessibility
acceptance. Prepared by rank_ui from current public/index.html and the retained
astra_browser_verify_20261026_01.py harness; coordinator retained this handoff.
Do not repeat the completed D01 or C03 audit to begin this next unit.

Production dependencies at index.html lines7–11:

- Google Fonts CSS: Inter400/500/600/700/800 and JetBrains Mono400/500/600/700,
  fonts.googleapis.com plus returned fonts.gstatic.com font assets.
- https://cdn.tailwindcss.com/3.4.17
- https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js

No vendored assets were found under public. Chrome155.0.8059.80 and Edge156.0.4314.42
and the Python websockets/CDP harness support isolated headless execution, viewport
emulation, screenshots and native keyboard input. Earlier36/36 runs in each browser
used omitted CSS/fonts and Chart/Tailwind substitutes; they remain valid only for
their stated DOM/keyboard scope.

Single next implementation: retain the exact production dependency bytes in a
separate local evidence cache with original/resolved URL, acquisition time, version,
SHA256, MIME and license/reference. Record font stylesheet retrieval user agent,
exact font hashes and family/weight coverage because Google CSS varies by client.
Do not replace the shipped dashboard or silently accept system-font fallback.

Extend the existing CDP harness as a new uniquely named evidence helper. Serve
production HTML byte-for-byte. Fulfill only exact manifest-matched external asset
URLs from verified local bytes using CDP Fetch interception; block all other external
traffic before transport. Remove stub/script replacements only in the new harness.
Mock only local API JSON and continue blocking provider access and mutation methods.
Any public asset acquisition is a separate recorded read-only download, not a broker
call. Missing licensed/dependency/font evidence keeps the corresponding gate open.

Check actual Chart.version4.4.1 and absence of OfflineChartStub, expected Tailwind
computed style/breakpoints, document.fonts.ready plus loaded-face coverage, and
visible tabs/inspector at1440/768/390/320 widths. Measure individual visible elements
against viewport and scroll containers: body overflow-x:hidden can conceal clipping.
Check actual canvas dimensions/rendering and capture screenshots. Exercise native
Tab/Shift+Tab/Enter/Space through refresh, tabs, cards and filters, including focus
after rerender and failure/out-of-order cases. Inspect accessibility-tree names,
selection/current state, hidden-panel exclusion and canvas descriptions. Sample
computed contrast/reduced-motion checks can support limited UI review, not full
WCAG conformance or a general accessibility certification.

Static candidates to reproduce before repair: tab selection uses visual classes
without aria-selected/controls; renderSignalCards replaces a selected/focused card;
card selected state lacks semantic exposure; three canvases lack labels/fallback
association; btnRefreshScans is symbol-only without an accessible label. These are
source observations, not new runtime defect reproductions or visual acceptance.

Preserve source and provider boundaries. First capture concrete failing evidence,
then make minimal fixes and run focused browser/Node checks followed by appropriate
canonical verification. Existing rank/actionability semantics must remain intact.
