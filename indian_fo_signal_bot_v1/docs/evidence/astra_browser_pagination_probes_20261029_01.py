"""Browser probes of existing signal/scan pages using explicitly authored rows."""
import base64
import hashlib
from pathlib import Path
import time

APP = Path(__file__).resolve().parents[2]


def probes(cdp, receipt, prefix, label, width, height, mode):
    def check(name, value, details=None):
        receipt["checks"].append(dict(name=label + "." + name, passed=value is True, details=details))
        print(label + "." + name, "PASS" if value is True else "FAIL", flush=True)

    def count(route):
        return "performance.getEntriesByType('resource').filter(r=>r.name.includes('" + route + "')).length"

    def start(route, action):
        previous = cdp.evaluate(count(route))
        action()
        return previous

    def finish(route, previous, extra="true"):
        return cdp.wait_for(count(route) + ">" + str(previous) + " && (" + extra + ")")

    def press(button):
        cdp.evaluate("document.getElementById('" + button + "').focus()")
        cdp.key("Enter", "Enter", 13)

    def select(control, value):
        # Run the actual change listener; navigation buttons below use native keys.
        cdp.evaluate("(()=>{const e=document.getElementById('" + control + "');e.focus();e.value='" + value + "';e.dispatchEvent(new Event('change',{bubbles:true}));})()")

    def signal_state():
        return cdp.evaluate("({ids:[...document.querySelectorAll('.signal-card-item')].map(e=>Number(e.getAttribute('data-signal-key'))),info:document.getElementById('signalsPaginationInfo').textContent,previous:document.getElementById('btnPrevSignalsPage').disabled,next:document.getElementById('btnNextSignalsPage').disabled,focus:document.activeElement.id,badge:document.getElementById('signalCountBadge').textContent})")

    def signals(name, expected_ids, start_index, total, previous_disabled, next_disabled, ready=True):
        result = signal_state()
        expected_info = ("Showing " + str(start_index) + "–" + str(start_index + len(expected_ids) - 1) + " of " + str(total)) if total else "0 results"
        check(name, ready and result["ids"] == expected_ids and result["info"] == expected_info and
            result["previous"] is previous_disabled and result["next"] is next_disabled, result)

    def signal_read(action):
        before = start("/api/signals", action)
        return finish("/api/signals", before, "!document.getElementById('signalCountBadge').textContent.includes('Loading')")

    def scan_state():
        return cdp.evaluate("({ids:[...document.querySelectorAll('#scanRunsTableBody tr')].map(e=>e.firstChild.textContent.split(' • ')[0]),info:document.getElementById('scansPaginationInfo').textContent,previous:document.getElementById('btnPrevScansPage').disabled,next:document.getElementById('btnNextScansPage').disabled,focus:document.activeElement.id})")

    def scans(name, expected_numbers, start_index, total, previous_disabled, next_disabled, ready=True):
        result = scan_state()
        ids = ["fixture-scan-" + str(n).zfill(3) for n in expected_numbers]
        expected_info = ("Showing " + str(start_index) + "–" + str(start_index + len(ids) - 1) + " of " + str(total) + " scan runs") if total else "0 scan runs recorded"
        if total == 0:
            ids = ["No scan runs recorded matching this filter."]
        check(name, ready and result["ids"] == ids and result["info"] == expected_info and
            result["previous"] is previous_disabled and result["next"] is next_disabled, result)

    def scan_read(action):
        before = start("/api/scans", action)
        return finish("/api/scans", before, "!document.getElementById('scansPaginationInfo').textContent.includes('Loading')")

    # The fixture is frozen at45 signals and31 scan runs until explicitly shrunk.
    signals("signals_first_page", list(range(1, 21)), 1, 45, True, False)
    ready = signal_read(lambda: press("btnNextSignalsPage"))
    signals("signals_middle_page_native_next", list(range(21, 41)), 21, 45, False, False, ready)
    ready = signal_read(lambda: press("btnNextSignalsPage"))
    signals("signals_last_page_native_next", list(range(41, 46)), 41, 45, False, True, ready)
    ready = signal_read(lambda: press("btnPrevSignalsPage"))
    signals("signals_previous_page_native_key", list(range(21, 41)), 21, 45, False, False, ready)
    ready = signal_read(lambda: select("selectPageLimit", "10"))
    signals("signals_page_size_10_resets_offset", list(range(1, 11)), 1, 45, True, False, ready)
    check("signal_page_size_change_keeps_control_focus", cdp.evaluate("document.activeElement.id==='selectPageLimit'"))
    ready = signal_read(lambda: select("selectPageLimit", "50"))
    signals("signals_page_size_50_resets_offset", list(range(1, 46)), 1, 45, True, True, ready)
    signal_read(lambda: select("selectPageLimit", "10"))
    signal_read(lambda: press("btnNextSignalsPage"))

    def type_symbol(symbol):
        cdp.evaluate("document.getElementById('searchSymbol').value='';document.getElementById('searchSymbol').focus()")
        cdp.command("Input.insertText", dict(text=symbol))

    ready = signal_read(lambda: type_symbol("RELIANCE"))
    signals("symbol_filter_resets_later_page_offset", list(range(3, 31, 3)), 1, 15, True, False, ready)
    check("symbol_filter_response_keeps_search_focus", cdp.evaluate("document.activeElement.id==='searchSymbol'"))
    ready = signal_read(lambda: type_symbol("NOMATCH"))
    signals("empty_symbol_filter_truthful_range", [], 0, 0, True, True, ready)
    signal_read(lambda: press("btnResetSignalFilters"))

    # A newer filter request has a genuinely distinct URL from the held page read.
    mode["delay_signals"] = True
    mode["signals_waiting"].clear()
    mode["release_signals"].clear()
    capture_start = len(mode["signal_captures"])
    previous = start("/api/signals", lambda: press("btnNextSignalsPage"))
    try:
        wait_until = time.monotonic() + 1.5
        while not mode["signals_waiting"].is_set() and time.monotonic() < wait_until:
            cdp.evaluate("true")
            time.sleep(.01)
        pending = mode["signals_waiting"].is_set()
        ready = signal_read(lambda: type_symbol("RELIANCE"))
        captures = [dict(row) for row in mode["signal_captures"][capture_start:]]
        distinct = len(captures) == 2 and captures[0]["held"] and not captures[1]["held"] and captures[0]["query"] != captures[1]["query"]
        check("pagination_overlap_uses_distinct_filter_reads", pending and ready and distinct, captures)
        mode["release_signals"].set()
        both_done = cdp.wait_for(count("/api/signals") + ">=" + str(previous + 2))
        cdp.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))")
        signals("late_page_cannot_replace_new_filter", list(range(3, 31, 3)), 1, 15, True, False, both_done and distinct)
        check("late_page_cannot_steal_search_focus", cdp.evaluate("document.activeElement.id==='searchSymbol'"))
    finally:
        mode["delay_signals"] = False
        mode["release_signals"].set()
    signal_read(lambda: press("btnResetSignalFilters"))
    signal_read(lambda: select("selectPageLimit", "20"))
    signal_read(lambda: press("btnNextSignalsPage"))
    mode["signal_total"] = 5
    ready = signal_read(lambda: press("btnRefreshDashboard"))
    range_result = cdp.evaluate("(()=>{const e=document.getElementById('signalsPaginationInfo'),text=e.textContent,m=text.match(/^Showing (\\d+)–(\\d+) of (\\d+)$/);return {text,valid:text==='0 results'||!!m&&Number(m[1])<=Number(m[2])&&Number(m[2])<=Number(m[3])};})()")
    check("shrinking_signal_total_never_shows_inverted_range", ready and range_result["valid"], dict(range=range_result, last_response=mode["signal_captures"][-1]))
    mode["signal_total"] = 45
    signal_read(lambda: press("btnResetSignalFilters"))
    mode["fail_signals"] = True
    ready = signal_read(lambda: press("btnNextSignalsPage"))
    failed = signal_state()
    check("failed_signal_page_withholds_old_range_and_cards", ready and failed["badge"] == "Error" and not failed["ids"] and "Showing" not in failed["info"], failed)
    mode["fail_signals"] = False
    signal_read(lambda: press("btnResetSignalFilters"))

    # Existing scan pages have their own request guard and15-row contract.
    cdp.evaluate("document.querySelector('[data-tab=tab-brokers-telegram]').focus()")
    cdp.key("Enter", "Enter", 13)
    scans("scans_first_page", list(range(1, 16)), 1, 31, True, False)
    ready = scan_read(lambda: press("btnNextScansPage"))
    scans("scans_middle_page_native_next", list(range(16, 31)), 16, 31, False, False, ready)
    ready = scan_read(lambda: press("btnNextScansPage"))
    scans("scans_last_page_native_next", [31], 31, 31, False, True, ready)
    ready = scan_read(lambda: press("btnPrevScansPage"))
    scans("scans_previous_page_native_key", list(range(16, 31)), 16, 31, False, False, ready)
    ready = scan_read(lambda: select("filterScanStatus", "COMPLETED"))
    scans("scan_status_filter_resets_later_offset", list(range(1, 30, 2)), 1, 16, True, False, ready)
    check("scan_filter_change_keeps_control_focus", cdp.evaluate("document.activeElement.id==='filterScanStatus'"))
    ready = scan_read(lambda: select("filterScanStatus", "SKIPPED_OVERLAP"))
    scans("empty_scan_filter_truthful_range", [], 0, 0, True, True, ready)
    scan_read(lambda: select("filterScanStatus", "ALL"))
    scan_read(lambda: press("btnNextScansPage"))
    mode["scan_total"] = 5
    ready = scan_read(lambda: press("btnRefreshScans"))
    range_result = cdp.evaluate("(()=>{const text=document.getElementById('scansPaginationInfo').textContent,m=text.match(/^Showing (\\d+)–(\\d+) of (\\d+) scan runs$/);return {text,valid:text==='0 scan runs recorded'||!!m&&Number(m[1])<=Number(m[2])&&Number(m[2])<=Number(m[3])};})()")
    check("shrinking_scan_total_never_shows_inverted_range", ready and range_result["valid"], dict(range=range_result, last_response=mode["scan_captures"][-1]))
    mode["scan_total"] = 31
    scan_read(lambda: select("filterScanStatus", "ALL"))
    mode["fail_scans"] = True
    ready = scan_read(lambda: press("btnNextScansPage"))
    failed = scan_state()
    check("failed_scan_page_withholds_old_range_and_rows", ready and failed["info"] == "Error loading scan runs" and not any(row.startswith("fixture-scan-") for row in failed["ids"]), failed)
    mode["fail_scans"] = False
    scan_read(lambda: select("filterScanStatus", "ALL"))
    cdp.evaluate("window.scrollTo(0,0)")
    screenshot = APP / "docs/evidence" / (prefix + "_" + label + ".png")
    body = base64.b64decode(cdp.command("Page.captureScreenshot", dict(format="png", captureBeyondViewport=False))["data"])
    with screenshot.open("xb") as stream:
        stream.write(body)
    receipt["screenshots"].append(dict(file=screenshot.name, sha256=hashlib.sha256(body).hexdigest(), viewport=dict(width=width, height=height), scope="EXISTING_PAGINATION_AUTHORED_FIXTURE"))
