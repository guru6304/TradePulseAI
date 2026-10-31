"""Actual-browser checks of the existing read-only paper-journal preview."""
import base64
import hashlib
from pathlib import Path
import time

APP = Path(__file__).resolve().parents[2]
JOURNAL = "document.querySelector('[aria-label=\"Stored simulated paper journal\"]')"
STATEMENT = hashlib.sha256(b"AUTHORED_BROWSER_FIXTURE_STATEMENT_NOT_EMPIRICAL").hexdigest()


def probes(cdp, receipt, prefix, label, width, height, mode):
    def check(name, value, details=None):
        receipt["checks"].append(dict(name=label + "." + name, passed=value is True, details=details))
        print(label + "." + name, "PASS" if value is True else "FAIL", flush=True)

    def count():
        return cdp.evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/paper-portfolio')).length")

    def press(identifier):
        cdp.evaluate("document.getElementById('" + identifier + "').focus()")
        cdp.key("Enter", "Enter", 13)

    def text():
        return cdp.evaluate("document.getElementById('storedReportsContainer').textContent")

    def read(kind=None):
        if kind is not None:
            mode["report_kind"] = kind
        before = count()
        press("refreshStoredReports")
        return cdp.wait_for("performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/paper-portfolio')).length>" +
            str(before) + " && !document.getElementById('storedReportsContainer').textContent.includes('Reading retained reports')")

    def health(failed=False):
        mode["fail_health"] = failed
        press("btnRefreshDashboard")
        expected = "API DISCONNECTED" if failed else "OFFLINE FIXTURE"
        return cdp.wait_for("document.getElementById('headerDataModeBadge').textContent==='" + expected +
            "' && document.getElementById('storedReportsContainer').textContent.includes('" +
            ("Reports unavailable" if failed else "Read stored reports for this health snapshot") + "')")

    def held_read():
        mode["hold_portfolio"] = True
        mode["portfolio_waiting"].clear()
        mode["release_portfolio"].clear()
        before = count()
        press("refreshStoredReports")
        until = time.monotonic() + 1.5
        while not mode["portfolio_waiting"].is_set() and time.monotonic() < until:
            cdp.evaluate("true")  # Continue CDP-intercepted requests while waiting.
            time.sleep(.01)
        return before, mode["portfolio_waiting"].is_set()

    def completed(before, additional=1):
        ready = cdp.wait_for("performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/paper-portfolio')).length>=" + str(before + additional))
        cdp.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))")
        return ready

    cdp.evaluate("document.getElementById('selectAutoRefreshSec').value='0';document.getElementById('selectAutoRefreshSec').dispatchEvent(new Event('change',{bubbles:true}));document.getElementById('paperReportSession').value='2026-10-16';document.querySelector('[data-tab=tab-brokers-telegram]').focus()")
    cdp.key("Enter", "Enter", 13)
    initial_capture = len(mode["report_captures"])
    ready = read("normal")
    current = text()
    check("native_refresh_renders_explicit_fixture_journal", ready and "Paper journal" in current and
        "Source SIMULATED | Provider paper_sim | Fill policy AUTHORED_FIXTURE_ONLY" in current and
        "LOCAL STORED EVIDENCE" in current and "live acceptance is separate" in current)
    captures = mode["report_captures"][initial_capture:]
    check("paper_reads_have_explicit_fixture_account_and_session", any(row["path"] == "/api/paper-portfolio" and
        row["account_id"] == "fixture-paper-A" for row in captures) and any(row["path"] == "/api/paper-session" and
        row["account_id"] == "fixture-paper-A" and row["session_date"] == "2026-10-16" for row in captures), captures)
    check("refresh_keeps_native_control_focus", cdp.evaluate("document.activeElement.id==='refreshStoredReports'"))
    check("configured_session_statement_is_fixture_scoped", "EOD statement: FIXTURE_ONLY | SIMULATED_EOD_EXAMPLE | 2026-10-16 | Statement " + STATEMENT in current)
    check("persisted_lifecycle_costs_and_missing_trigger_fields", all(value in current for value in
        ("QUEUED | WAITING_FOR_TRIGGER", "FILLED | PAPER_RISK_APPROVED", "Trigger rule unavailable",
         "Trigger rule fixture-rule", "Strategy version fixture-v1", "Observed trigger time 2026-10-16 10:35:00",
         "Raw entry ₹100.00", "Effective entry ₹100.05", "Closed net P&L ₹-12.50",
         "STOP_FIRST_COLLISION", "Charges ₹2.25", "Modeled slippage ₹0.50", "ENTRY | Event event-0")))
    counts = cdp.evaluate("""(()=>{const j=document.querySelector('[aria-label="Stored simulated paper journal"]');
      return [...j.querySelectorAll('h5')].map(h=>{let n=h.nextElementSibling,rows=0;
        while(n&&n.tagName!=='H5'){if(n.classList.contains('mono'))rows++;n=n.nextElementSibling;}
        return {heading:h.textContent,rows};});})()""")
    expected = ["Setups and decisions — showing 40 of retained total 90", "Positions — showing 40 of retained total 91", "Retained events — showing 40 of retained total 92"]
    check("each_collection_is_bounded_to_40_with_retained_totals", len(counts) == 3 and
        [row["heading"] for row in counts] == expected and all(row["rows"] == 40 for row in counts), counts)
    check("partial_preview_is_explicit_and_excess_rows_absent", current.count("Partial preview;") == 3 and
        "/api/paper-ledger" in current and not any(value in current for value in ("candidate-44", "position-44", "event-44")))
    check("hostile_journal_strings_remain_literal", '<img src=x onerror="window.__journal_xss=1">' in current and
        cdp.evaluate(JOURNAL + ".querySelectorAll('img,script').length===0 && window.__journal_xss===undefined"))
    tree = cdp.command("Accessibility.getFullAXTree")["nodes"]
    check("journal_has_accessibility_region_name", any(not node.get("ignored") and
        node.get("role", {}).get("value") == "region" and node.get("name", {}).get("value") ==
        "Stored simulated paper journal" for node in tree))
    viewport = cdp.evaluate("({innerWidth,clientWidth:document.documentElement.clientWidth,visualWidth:window.visualViewport?window.visualViewport.width:null})")
    # A desktop scrollbar reduces clientWidth; it must never widen the layout.
    check("layout_viewport_matches_configured_width", viewport["innerWidth"] == width and
        0 < viewport["clientWidth"] <= width and viewport["visualWidth"] is not None and
        abs(viewport["visualWidth"] - viewport["clientWidth"]) <= 1, dict(configured_width=width, **viewport))
    geometry = cdp.evaluate("""(()=>{const out=[],root=document.getElementById('storedReportsContainer');
      for(const e of root.querySelectorAll('*')){if(e.children.length||!e.textContent.trim())continue;
        const range=document.createRange();range.selectNodeContents(e);
        const rects=[...range.getClientRects()];const bad=rects.some(r=>r.width>0&&(r.left < -1||r.right>document.documentElement.clientWidth+1));
        if(bad)out.push({tag:e.tagName,text:e.textContent.slice(0,120),blockRight:e.getBoundingClientRect().right,
          clientWidth:e.clientWidth,scrollWidth:e.scrollWidth,textRight:Math.max(...rects.map(r=>r.right))});
      }return out.slice(0,12);})()""")
    check("stored_report_text_stays_within_viewport", not geometry, geometry)
    cdp.evaluate(JOURNAL + ".scrollIntoView({block:'start'});window.scrollBy(0,-20)")
    cdp.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))")
    screenshot = APP / "docs/evidence" / (prefix + "_" + label + ".png")
    body = base64.b64decode(cdp.command("Page.captureScreenshot", dict(format="png", captureBeyondViewport=False))["data"])
    with screenshot.open("xb") as stream:
        stream.write(body)
    receipt["screenshots"].append(dict(file=screenshot.name, sha256=hashlib.sha256(body).hexdigest(),
        viewport=dict(width=width, height=height), scope="AUTHORED_BOUNDED_PAPER_JOURNAL_VIEWPORT"))

    ready = read("stale")
    current = text()
    check("stale_open_marks_withhold_current_equity_and_pnl", ready and
        "Current equity and unrealized P&L unavailable" in current and "Current unrealized P&L unavailable" in current and
        "8,88,881.11" not in current and "9,09,090.09" not in current and "Closed net P&L ₹-12.50" in current)
    ready = read("missing")
    current = text()
    check("missing_open_marks_remain_unavailable", ready and "Current unrealized P&L unavailable" in current and
        "Mark time unavailable" in current and "Retained unrealized net P&L" not in current)
    ready = read("reconciliation")
    current = text()
    check("failed_reconciliation_withholds_journal_and_accounting", ready and
        "RECONCILIATION REQUIRED; accounting unavailable" in current and
        "Journal withheld: reconciliation required." in current and not any(value in current for value in
        ("candidate-0", "position-0", "9,09,090.09", "-12.50")))
    ready = read("empty")
    current = text()
    check("empty_journal_has_explicit_zero_totals", ready and current.count("showing 0 of retained total 0") == 3 and
        current.count("No rows in this retained preview.") == 3 and "Partial preview" not in current)
    ready = read("failure")
    current = text()
    check("failed_portfolio_read_clears_prior_accounting", ready and "Paper ledger: UNAVAILABLE (no cached values retained)" in current and
        "Paper journal" not in current and not any(value in current for value in ("candidate-0", "position-0", "9,09,090.09")))
    mode["fail_session"] = True
    ready = read("normal")
    current = text()
    check("failed_session_read_does_not_reuse_old_statement", ready and "EOD statement: UNAVAILABLE (no cached values retained)" in current and
        STATEMENT not in current and "Paper journal" in current)
    mode["fail_session"] = False

    before, pending = held_read()
    try:
        failed_health = health(True)
        mode["release_portfolio"].set()
        done = completed(before)
        current = text()
        check("held_portfolio_request_really_started", pending)
        check("late_portfolio_cannot_restore_after_failed_health", pending and failed_health and done and
            current == "Reports unavailable: current health request failed.", dict(completed=done, text=current))
    finally:
        mode["hold_portfolio"] = False
        mode["release_portfolio"].set()
    check("health_can_recover_without_financial_mutation", health(False))

    capture_start = len(mode["report_captures"])
    before, pending = held_read()
    try:
        mode["account_id"] = "fixture-paper-B"
        mode["report_kind"] = "empty"
        fresh_health = health(False)
        newer_ready = read()
        observed = [row for row in mode["report_captures"][capture_start:] if row["path"] == "/api/paper-portfolio"]
        distinct = len(observed) == 2 and observed[0]["account_id"] == "fixture-paper-A" and observed[0]["kind"] == "normal" and observed[0]["held"] and observed[1]["account_id"] == "fixture-paper-B" and observed[1]["kind"] == "empty" and not observed[1]["held"]
        check("new_health_account_uses_distinct_report_request", pending and fresh_health and newer_ready and distinct, observed)
        mode["release_portfolio"].set()
        done = completed(before, 2)
        current = text()
        check("late_old_account_cannot_replace_new_empty_journal", done and distinct and
            current.count("showing 0 of retained total 0") == 3 and "candidate-0" not in current and
            cdp.evaluate("document.activeElement.id==='refreshStoredReports'"), dict(completed=done, empty=current.count("showing 0 of retained total 0")))
    finally:
        mode["hold_portfolio"] = False
        mode["release_portfolio"].set()
