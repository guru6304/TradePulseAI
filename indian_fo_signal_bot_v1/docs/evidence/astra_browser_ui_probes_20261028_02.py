"""Real-asset CDP checks; authored HTTP fixtures, no application imports."""
import base64
import hashlib
import json
from pathlib import Path
import time

APP = Path(__file__).resolve().parents[2]
MANIFEST = APP / "docs/evidence/astra_browser_assets_20261027_02.json"


def assets():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS" and len(manifest["licenses"]) == 4
    result = {}
    for row in manifest["assets"] + manifest["licenses"]:
        path = (APP / row["path"]).resolve()
        assert path.is_relative_to(APP / ".local/astra_browser_assets_20261027_01")
        body = path.read_bytes()
        assert len(body) == row["size_bytes"] and hashlib.sha256(body).hexdigest() == row["sha256"]
        if row in manifest["assets"]:
            assert row["url"] not in result
            result[row["url"]] = (body, row["content_type"])
    return result


def probes(cdp, receipt, prefix, label, width, height, mode):
    def check(name, value, details=None):
        receipt["checks"].append(dict(name=label + "." + name, passed=value is True, details=details))
        print(label + "." + name, "PASS" if value is True else "FAIL", flush=True)

    loaded = cdp.evaluate("document.fonts.ready.then(()=>({chart:Chart.version,tailwind:getComputedStyle(document.body).display,fonts:[...document.fonts].filter(f=>f.status==='loaded').map(f=>({family:f.family,weight:f.weight}))}))")
    check("real_chart_tailwind_fonts", loaded["chart"] == "4.4.1" and loaded["tailwind"] == "flex"
          and {f["family"].strip('"') for f in loaded["fonts"]} >= {"Inter", "JetBrains Mono"}, loaded)
    cdp.evaluate("document.querySelectorAll('.signal-card-item')[1].focus()")
    cdp.key("Enter", "Enter", 13)
    focus = cdp.evaluate("({focused:document.activeElement.classList.contains('signal-card-item')&&document.activeElement.textContent.includes('INFY'),pressed:document.querySelectorAll('.signal-card-item')[1].getAttribute('aria-pressed'),detail:document.getElementById('detailSymbolTitle').textContent})")
    check("card_keyboard_selection_preserves_focus", focus["focused"], focus)
    check("card_selection_semantic", focus["pressed"] == "true", focus)
    check("card_changes_selected_detail", "INFY" in focus["detail"], focus)
    cdp.evaluate("document.querySelector('.signal-card-item').focus()")
    cdp.key(" ", "Space", 32)
    check("space_preserves_selected_card_focus", cdp.evaluate("document.activeElement.classList.contains('signal-card-item')&&document.activeElement.textContent.includes('RELIANCE')&&document.getElementById('detailSymbolTitle').textContent.includes('RELIANCE')"))
    # Exercise the actual asynchronous dashboard refresh listener. A programmatic
    # click leaves initial focus where the user put it, as an automatic refresh
    # would; no application closure hooks or direct render calls are introduced.
    resource_count = "performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/signals')).length"

    def begin_refresh():
        before = cdp.evaluate(resource_count)
        cdp.evaluate("document.getElementById('btnRefreshDashboard').click()")
        return before

    def refreshed(before, expected_count):
        return cdp.wait_for(resource_count + ">" + str(before) +
            " && document.querySelectorAll('.signal-card-item').length===" + str(expected_count) +
            " && !document.getElementById('signalCountBadge').textContent.includes('Loading')")

    cdp.evaluate("document.querySelectorAll('.signal-card-item')[1].focus()")
    original_key = cdp.evaluate("document.activeElement.getAttribute('data-signal-key')")
    before = begin_refresh()
    ready = refreshed(before, 2)
    focus = cdp.evaluate("({id:document.activeElement.id,key:document.activeElement.getAttribute('data-signal-key'),card:document.activeElement.classList.contains('signal-card-item')})")
    check("asynchronous_refresh_restores_same_focused_card", ready and focus["card"] and
        bool(original_key) and focus["key"] == original_key,
        dict(response_completed=ready, original_key=original_key, focus=focus))

    cdp.evaluate("document.getElementById('searchSymbol').focus()")
    before = begin_refresh()
    ready = refreshed(before, 2)
    search_focus = cdp.evaluate("document.activeElement.id")
    check("asynchronous_refresh_does_not_steal_search_focus", ready and search_focus == "searchSymbol",
        dict(response_completed=ready, focused_id=search_focus))

    mode["empty_signals"] = True
    cdp.evaluate("(()=>{const c=document.querySelectorAll('.signal-card-item')[1];c.scrollIntoView({block:'center'});c.focus({preventScroll:true});})()")
    before_scroll = cdp.evaluate("scrollY")
    before = begin_refresh()
    ready = refreshed(before, 0)
    fallback = cdp.evaluate("""(()=>{const e=document.activeElement,r=e.getBoundingClientRect();
      const x=Math.min(innerWidth-1,Math.max(0,r.left+r.width/2)),y=Math.min(innerHeight-1,Math.max(0,r.top+r.height/2));
      const hit=document.elementFromPoint(x,y);return {id:e.id,tag:e.tagName,scrollY,
        top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height,
        visible:r.width>0&&r.height>0&&r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth,
        unobscured:!!hit&&(hit===e||e.contains(hit))};})()""")
    check("empty_refresh_has_visible_read_only_focus_fallback", ready and
        fallback["id"] in ("btnRefreshDashboard", "searchSymbol", "btnResetSignalFilters") and
        fallback["visible"] and fallback["unobscured"],
        dict(response_completed=ready, original_scroll_y=before_scroll, fallback=fallback))
    mode["empty_signals"] = False
    cdp.evaluate("document.getElementById('searchSymbol').focus()")
    before = begin_refresh()
    if not refreshed(before, 2):
        raise RuntimeError("FOCUS_PROBE_SIGNAL_FIXTURE_RESTORE_FAILED")

    mode["delay_signals"] = True
    mode["signals_waiting"].clear()
    mode["release_signals"].clear()
    cdp.evaluate("document.querySelector('.signal-card-item').focus()")
    before = begin_refresh()
    try:
        wait_until = time.monotonic() + 1.5
        while not mode["signals_waiting"].is_set() and time.monotonic() < wait_until:
            cdp.evaluate("true")  # Pump intercepted requests while the server waits.
            time.sleep(.01)
        pending = mode["signals_waiting"].is_set()
        check("delayed_signals_request_is_pending", pending)
        cdp.evaluate("document.getElementById('searchSymbol').focus()")
        mode["release_signals"].set()
        ready = refreshed(before, 2)
        selected = cdp.evaluate("document.activeElement.id")
        check("focus_moved_during_request_is_not_stolen", pending and ready and selected == "searchSymbol",
            dict(response_completed=ready, focused_id=selected))
    finally:
        mode["delay_signals"] = False
        mode["release_signals"].set()
    header = cdp.evaluate("({position:getComputedStyle(document.querySelector('header')).position,height:document.querySelector('header').getBoundingClientRect().height,viewport:innerHeight})")
    check("header_leaves_mobile_reading_space", width >= 1024 or header["position"] != "sticky" or header["height"] < header["viewport"] / 2, header)
    for tab in ("tab-terminal", "tab-option-apex", "tab-strategies", "tab-brokers-telegram"):
        cdp.evaluate("document.querySelector('[data-tab=" + tab + "]').focus()")
        cdp.key("Enter", "Enter", 13)
        cdp.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))")
        semantics = cdp.evaluate("(()=>{const b=document.querySelector('[data-tab=" + tab + "]'),p=document.getElementById('" + tab + "');return {role:b.getAttribute('role'),selected:b.getAttribute('aria-selected'),controls:b.getAttribute('aria-controls'),panelRole:p.getAttribute('role'),labelledby:p.getAttribute('aria-labelledby'),buttonId:b.id,visible:!p.classList.contains('hidden'),selectedCount:document.querySelectorAll('.nav-tab-btn[aria-selected=true]').length};})()")
        check(tab + ".tab_semantics", semantics["role"] == "tab" and semantics["selected"] == "true"
              and semantics["controls"] == tab and semantics["panelRole"] == "tabpanel"
              and semantics["labelledby"] == semantics["buttonId"] and semantics["selectedCount"] == 1, semantics)
        clipping = cdp.evaluate("""(()=>{const out=[];for(const e of document.querySelectorAll('button,input,select,label,h1,h2,h3,p,span,canvas,.signal-card-item')){
          if(!e.getClientRects().length||e.closest('.hidden'))continue; const r=e.getBoundingClientRect();
          let scroll=false;for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){if(['auto','scroll'].includes(getComputedStyle(p).overflowX)){scroll=true;break;}}
          if(!scroll&&(r.left < -1 || r.right > innerWidth+1 || (e.tagName==='SELECT'&&r.width>innerWidth)))out.push({tag:e.tagName,id:e.id,text:e.textContent.slice(0,65),left:r.left,right:r.right});
        }return out.slice(0,30);})()""")
        check(tab + ".controls_within_viewport", not clipping, clipping)
        tree = cdp.command("Accessibility.getFullAXTree")["nodes"]
        selected_tabs = [n for n in tree if not n.get("ignored") and n.get("role", {}).get("value") == "tab"]
        check(tab + ".accessibility_tree_tab_names", len(selected_tabs) == 4 and all(n.get("name", {}).get("value") for n in selected_tabs),
              [{"role": n.get("role"), "name": n.get("name"), "properties": n.get("properties")} for n in selected_tabs])
        cdp.evaluate("window.scrollTo(0,0)")
        screenshot = APP / "docs/evidence" / (prefix + "_" + label + "_" + tab + ".png")
        body = base64.b64decode(cdp.command("Page.captureScreenshot", dict(format="png", captureBeyondViewport=False))["data"])
        with screenshot.open("xb") as stream:
            stream.write(body)
        receipt["screenshots"].append(dict(file=screenshot.name, sha256=hashlib.sha256(body).hexdigest(),
            viewport=dict(width=width, height=height), scope="ACTUAL_PRODUCTION_ASSETS_AUTHORED_API_FIXTURE"))
    labels = cdp.evaluate("({canvases:[...document.querySelectorAll('canvas')].map(c=>({id:c.id,role:c.getAttribute('role'),label:c.getAttribute('aria-label'),fallback:c.textContent.trim()})),refresh:document.getElementById('btnRefreshScans').getAttribute('aria-label')})")
    check("canvas_and_icon_control_names", bool(labels["refresh"]) and all(c["role"] == "img" and c["label"] and c["fallback"] for c in labels["canvases"]), labels)
    descriptions = {row["id"]: ((row["label"] or "") + " " + row["fallback"]).lower() for row in labels["canvases"]}
    backtest = descriptions.get("backtestEquityChart", "")
    check("backtest_canvas_names_hypothetical_gross_net_model", all(word in backtest for word in
        ("hypothetical", "gross", "net", "model")) and "stored research" not in backtest,
        dict(description=backtest, actual_behavior="HYPOTHETICAL_GROSS_NET_MODEL_NOT_STORED_RESEARCH"))
    options = descriptions.get("optionOiChart", "")
    check("option_canvas_names_open_interest_change", "open interest" in options and
        "change" in options and "strike" in options,
        dict(description=options, actual_behavior="CALL_PUT_OPEN_INTEREST_CHANGE_BY_STRIKE"))
    cdp.evaluate("document.querySelector('[data-tab=tab-terminal]').click()")
    inventory_expression = """(()=>{const rows=[];let pulseElements=0;for(const e of document.querySelectorAll('*')){
      if(!e.getClientRects().length)continue;const s=getComputedStyle(e);
      if(s.visibility==='hidden')continue;if(e.classList.contains('pulse-dot'))pulseElements++;
      if(s.animationName!=='none'&&s.animationDuration.split(',').some(d=>parseFloat(d)>0))
        rows.push({tag:e.tagName,id:e.id,animation:s.animationName,duration:s.animationDuration});
      }return {renderedAnimationCount:rows.length,renderedPulseElementCount:pulseElements,animations:rows.slice(0,100)};})()"""
    normal_motion = cdp.evaluate(inventory_expression)
    cdp.command("Emulation.setEmulatedMedia", dict(features=[dict(name="prefers-reduced-motion", value="reduce")]))
    reduced_motion = cdp.evaluate(inventory_expression)
    motion_status = ("NO_RENDERED_ANIMATION" if normal_motion["renderedAnimationCount"] == 0 else
        "RENDERED_ANIMATION_SUPPRESSED" if reduced_motion["renderedAnimationCount"] == 0 else
        "RENDERED_ANIMATION_REMAINS")
    motion = dict(status=motion_status, normal=normal_motion, reduced=reduced_motion,
        scope="RENDERED_CSS_ANIMATION_INVENTORY_ONLY_NO_WCAG_ATTESTATION",
        javascript_canvas_animation_coverage=False)
    receipt.setdefault("rendered_animation_inventory", []).append(dict(viewport=label, **motion))
    check("rendered_animation_inventory", reduced_motion["renderedAnimationCount"] == 0, motion)
    cdp.command("Emulation.setEmulatedMedia", dict(features=[]))
    chart = cdp.evaluate("(()=>{const c=document.getElementById('signalPriceChart'),i=Chart.getChart(c);return {exists:!!i,width:c.width,height:c.height,datasets:i?.data.datasets.length};})()")
    check("real_signal_chart_has_native_canvas", chart["exists"] and chart["width"] > 0 and chart["height"] > 0 and chart["datasets"] > 0, chart)
    cdp.evaluate("document.querySelector('[data-tab=tab-terminal]').focus()")
    cdp.key("ArrowRight", "ArrowRight", 39)
    check("tabs_arrow_navigation", cdp.evaluate("document.activeElement.getAttribute('data-tab')==='tab-option-apex'&&document.activeElement.getAttribute('aria-selected')==='true'"))
    cdp.key("End", "End", 35)
    check("tabs_end_navigation", cdp.evaluate("document.activeElement.getAttribute('data-tab')==='tab-brokers-telegram'"))
    cdp.key("Home", "Home", 36)
    check("tabs_home_navigation", cdp.evaluate("document.activeElement.getAttribute('data-tab')==='tab-terminal'"))
    cdp.evaluate("document.querySelector('[data-tab=tab-terminal]').click()")
    cdp.evaluate("document.activeElement.blur();window.scrollTo(0,0)")
