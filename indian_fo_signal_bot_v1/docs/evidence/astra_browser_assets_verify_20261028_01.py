"""Bounded headless browser DOM/keyboard checks against authored HTTP fixtures.

No application modules, environment files or databases are loaded. Actual public
assets are hash-verified and fulfilled locally. Four-viewport fixture checks provide
limited responsive/semantic evidence, not full WCAG or live-data acceptance.
"""
import argparse
import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit
from urllib.request import urlopen

from websockets.sync.client import connect

APP = Path(__file__).resolve().parents[2]
EVIDENCE = APP / "docs/evidence"
BROWSERS = {
    "chrome": Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    "edge": Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
}
SCOPE = "OFFLINE_AUTHORED_HTTP_FIXTURE_NOT_LIVE_ACCEPTANCE"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


from astra_browser_ui_probes_20261028_01 import assets, probes, MANIFEST
ASSETS = assets()


def prepare_html(raw):
    return raw, dict(source_html_sha256=hashlib.sha256(raw).hexdigest(),
        served_html_sha256=hashlib.sha256(raw).hexdigest(), production_inline_scripts_unchanged=True,
        external_scripts_omitted=0, external_links_omitted=0, chart_stub=False, tailwind_stub=False,
        manifest_sha256=sha(MANIFEST))


def signal_fixture():
    return dict(id=1, symbol="RELIANCE", segment="NSE_EQUITY_INTRADAY", direction="BULLISH",
        strategy_id="strat_4_orb_filtered", strategy_name='<img src=x onerror="window.__xss=1">',
        timestamp="2026-10-23 11:40:00", entry_price=102, stop_loss=99.3,
        target_1=106.32, target_2=108.48, position_qty=None, quality_score=0,
        invalidation_level=None, data_mode="LIVE", is_simulated=False,
        provider="angelone", state_context="SCANNER", broker="OFFLINE FIXTURE",
        evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE", actionable=False,
        recommendation_status="STORED_CANDIDATE", rationale="Authored offline browser fixture")


def ranking_fixture(lifetime=30):
    now = datetime.now(timezone.utc)
    row = dict(rank=1, previous_rank=None, symbol='<script>window.__xss=2</script>',
        strategy_id="strat_4_orb_filtered", direction="BULLISH", actionable=False,
        score_components=dict(rule_quality=0, actual_target1_rr=None),
        component_changes=dict(rule_quality=dict(previous=None, current=0)),
        rank_change_reason="NEWLY_QUALIFIED", source_data_watermark=now.isoformat(),
        missing_components=["NET_EXECUTABLE_REWARD", "RELATIVE_STRENGTH", "EMPIRICAL_EDGE"])
    return dict(status="CURRENT_CANDIDATE_PRIORITY", actionable=False, scope=SCOPE,
        as_of=now.isoformat(), current_rows=[row], historical_rows=[row],
        pagination=dict(offset=0, limit=20, total=1),
        snapshot=dict(reference=now.isoformat(), valid_until=(now + timedelta(seconds=lifetime)).isoformat(),
            scope=dict(provider="authored-offline-fixture"), removals=[], exclusions=[],
            rank_version="authored-browser-fixture", evidence_scope=SCOPE))


class CDP:
    def __init__(self, ws, origin, deadline):
        self.ws, self.origin, self.deadline = ws, origin, deadline
        self.sequence = 0
        self.fulfilled = []
        self.allowed, self.blocked, self.exceptions, self.crashes = [], [], [], []

    def send(self, method, params=None):
        self.sequence += 1
        self.ws.send(json.dumps(dict(id=self.sequence, method=method, params=params or {})))
        return self.sequence

    def command(self, method, params=None, timeout=5):
        request = self.send(method, params)
        deadline = min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            response = json.loads(self.ws.recv(timeout=max(.01, deadline - time.monotonic())))
            kind = response.get("method")
            if kind == "Fetch.requestPaused":
                event = response["params"]
                parts = urlsplit(event["request"]["url"])
                record = dict(method=event["request"]["method"], scheme=parts.scheme,
                              host=parts.hostname, path=parts.path)
                cached = ASSETS.get(event["request"]["url"])
                if cached and record["method"] == "GET":
                    body, mime = cached
                    self.fulfilled.append(dict(url=event["request"]["url"], sha256=hashlib.sha256(body).hexdigest()))
                    self.send("Fetch.fulfillRequest", dict(requestId=event["requestId"], responseCode=200,
                        responseHeaders=[dict(name="Content-Type",value=mime),dict(name="Access-Control-Allow-Origin",value="*")],
                        body=base64.b64encode(body).decode()))
                    continue
                allowed = parts.scheme == "http" and parts.scheme + "://" + parts.netloc == self.origin
                allowed = allowed and record["method"] in ("GET", "HEAD")
                (self.allowed if allowed else self.blocked).append(record)
                self.send("Fetch.continueRequest" if allowed else "Fetch.failRequest",
                    dict(requestId=event["requestId"]) if allowed else
                    dict(requestId=event["requestId"], errorReason="BlockedByClient"))
            elif kind == "Runtime.exceptionThrown":
                self.exceptions.append(response["params"]["exceptionDetails"])
            elif kind in ("Inspector.targetCrashed", "Target.targetCrashed"):
                self.crashes.append(response)
            elif response.get("id") == request:
                if "error" in response:
                    raise RuntimeError("CDP_COMMAND_FAILED_" + method + ": " + str(response["error"]))
                return response.get("result", {})
        raise TimeoutError("CDP_TIMEOUT_" + method)

    def evaluate(self, expression):
        result = self.command("Runtime.evaluate", dict(expression=expression, awaitPromise=True, returnByValue=True))
        if result.get("exceptionDetails"):
            raise RuntimeError("BROWSER_EVALUATION_EXCEPTION: " + str(result["exceptionDetails"]))
        return result.get("result", {}).get("value")

    def wait_for(self, expression, timeout=5):
        deadline = min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            if self.evaluate(expression) is True:
                return True
            time.sleep(.025)
        return False

    def key(self, key, code, virtual):
        down = dict(type="keyDown", key=key, code=code,
            windowsVirtualKeyCode=virtual, nativeVirtualKeyCode=virtual)
        if key == "Enter":
            down.update(text="\r", unmodifiedText="\r")
        self.command("Input.dispatchKeyEvent", down)
        self.command("Input.dispatchKeyEvent", dict(type="keyUp", key=key, code=code,
            windowsVirtualKeyCode=virtual, nativeVirtualKeyCode=virtual))


def run(receipt, browser, prefix):
    started = time.monotonic()
    deadline = started + 58
    html, receipt["html_preparation"] = prepare_html((APP / "public/index.html").read_bytes())
    requests, failures = [], []
    mode = dict(fail_health=False, fail_signals=False, fail_ranks=False, delay_rank=False, lifetime=30)
    rank_waiting, release_rank = threading.Event(), threading.Event()
    process = websocket = cdp = server = worker = profile_temp = None
    profile = None

    def check(name, result, details=None):
        receipt["checks"].append(dict(name=name, passed=result is True, details=details))
        print(name, "PASS" if result is True else "FAIL", flush=True)


    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            status, body, content_type = 200, b"", "application/json"
            if path in ("/", "/index.html"):
                body, content_type = html, "text/html; charset=utf-8"
            elif path == "/api/health":
                status = 503 if mode["fail_health"] else 200
                body = encoded(dict(status="ok", evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE",
                    broker=dict(data_mode="SIMULATED", connection_state="SIMULATED", is_simulated=True),
                    database=dict(status="OFFLINE_FIXTURE_NO_DATABASE"),
                    scheduler=dict(running=False, enabled_in_config=False)))
            elif path == "/api/config":
                body = encoded(dict(config=dict(telegram_dry_run=True, telegram_configured=False)))
            elif path == "/api/signals":
                status = 503 if mode["fail_signals"] else 200
                body = encoded(dict(items=[signal_fixture(), dict(signal_fixture(), id=2, symbol="INFY")], total_count=2, evidence_scope=SCOPE))
            elif path == "/api/opportunity-rankings":
                status = 503 if mode["fail_ranks"] else 200
                body = encoded(ranking_fixture(mode["lifetime"]))
                if mode["delay_rank"]:
                    mode["delay_rank"] = False
                    rank_waiting.set()
                    if not release_rank.wait(timeout=5):
                        failures.append("DELAYED_RANK_RELEASE_TIMEOUT")
            elif path in ("/api/scans", "/api/oi-snapshots", "/api/oi-baselines", "/api/backtest-runs"):
                body = encoded(dict(items=[], total_count=0))
            elif path == "/api/notification-outbox":
                body = encoded(dict(items=[], counts={}))
            elif path == "/favicon.ico":
                status = 204
            else:
                status, body = 404, encoded(dict(status="FIXTURE_ROUTE_NOT_DEFINED"))
                failures.append("UNEXPECTED_GET_" + path)
            requests.append(dict(method="GET", path=path, status=status))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                failures.append("CLIENT_DISCONNECTED_DURING_RESPONSE")

        def do_POST(self):
            requests.append(dict(method="POST", path=urlsplit(self.path).path, status=405))
            failures.append("MUTATION_REACHED_FIXTURE_SERVER")
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        origin = "http://127.0.0.1:" + str(server.server_address[1])
        worker = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=.025), daemon=True)
        worker.start()
        profile_temp = tempfile.TemporaryDirectory(prefix="astra-browser-fixture-")
        profile = Path(profile_temp.name).resolve()
        if profile.parent != Path(tempfile.gettempdir()).resolve() or not profile.name.startswith("astra-browser-fixture-"):
            raise RuntimeError("UNSAFE_TEMP_PROFILE_PATH")
        args = [str(BROWSERS[browser]), "--headless=new", "--disable-gpu", "--disable-background-networking",
            "--disable-component-update", "--disable-default-apps", "--disable-extensions", "--disable-sync",
            "--disable-domain-reliability", "--disable-client-side-phishing-detection", "--disable-breakpad",
            "--disable-crash-reporter", "--disable-pings", "--safebrowsing-disable-auto-update",
            "--metrics-recording-only", "--no-first-run", "--no-default-browser-check",
            "--password-store=basic", "--use-mock-keychain", "--disable-search-engine-choice-screen",
            "--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication,Translate,NetworkTimeServiceQuerying",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
            "--user-data-dir=" + str(profile), "about:blank"]
        receipt["browser_arguments"] = [a if not a.startswith("--user-data-dir=") else "--user-data-dir=<new-isolated-temporary-profile>" for a in args]
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        debugger = profile / "DevToolsActivePort"
        start_limit = time.monotonic() + 10
        while not debugger.is_file():
            if process.poll() is not None or time.monotonic() >= start_limit:
                raise RuntimeError("BROWSER_DEBUGGER_START_FAILED")
            time.sleep(.025)
        port = int(debugger.read_text().splitlines()[0])
        with urlopen("http://127.0.0.1:" + str(port) + "/json/list", timeout=3) as response:
            targets = json.loads(response.read(1024 * 1024))
        target = next(row for row in targets if row.get("type") == "page")
        parsed = urlsplit(target["webSocketDebuggerUrl"])
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1":
            raise RuntimeError("NON_LOOPBACK_DEBUGGER_TARGET")
        websocket = connect(target["webSocketDebuggerUrl"], open_timeout=3, close_timeout=2,
            max_size=8 * 1024 * 1024, proxy=None)
        cdp = CDP(websocket, origin, deadline)
        receipt["browser_version"] = cdp.command("Browser.getVersion")
        cdp.command("Runtime.enable")
        cdp.command("Page.enable")
        cdp.command("Inspector.enable")
        cdp.command("Fetch.enable", dict(patterns=[dict(urlPattern="*", requestStage="Request")]))
        receipt["screenshots"] = []
        for label, width, height, mobile in (("desktop", 1440, 1000, False), ("tablet", 768, 1024, False), ("mobile", 390, 844, True), ("narrow", 320, 844, True)):
            mode.update(fail_health=False, fail_signals=False, fail_ranks=False, delay_rank=False, lifetime=30)
            cdp.command("Emulation.setDeviceMetricsOverride", dict(width=width, height=height,
                deviceScaleFactor=1, mobile=mobile))
            cdp.command("Page.navigate", dict(url=origin + "/?viewport=" + label))
            check(label + ".production_dom_content_loaded_and_fixture_gets", cdp.wait_for(
                "document.getElementById('opportunityRankingsContainer')?.textContent.includes('Current candidate priority') && document.getElementById('signalCardsContainer').textContent.includes('RELIANCE')"))
            check(label + ".literal_hostile_text_no_executable_dom", cdp.evaluate(
                "document.getElementById('opportunityRankingsContainer').textContent.includes('<script>window.__xss=2</script>') && document.querySelectorAll('#opportunityRankingsContainer script,#signalCardsContainer img').length===0 && window.__xss===undefined"))
            check(label + ".zero_and_unavailable_values_preserved", cdp.evaluate(
                "(()=>{const t=document.getElementById('opportunityRankingsContainer').textContent;return t.includes('Quality 0')&&t.includes('Gross T1 reward/risk unavailable')&&t.includes('Previous rank unavailable')&&t.includes('NET_EXECUTABLE_REWARD')&&t.includes('RELATIVE_STRENGTH')&&t.includes('not an entry instruction or win probability');})()"))
            check(label + ".fixture_scope_and_no_invented_quantity", cdp.evaluate(
                "document.getElementById('headerDataModeBadge').textContent==='OFFLINE FIXTURE' && document.getElementById('signalCardsContainer').textContent.includes('Persisted Qty: unavailable')"))
            probes(cdp, receipt, prefix, label, width, height)
            cdp.evaluate("document.body.setAttribute('tabindex','-1');document.body.focus();document.body.removeAttribute('tabindex');window.scrollTo(0,0)")
            cdp.key("Tab", "Tab", 9)
            check(label + ".native_tab_reaches_read_only_refresh", cdp.evaluate(
                "document.activeElement.id==='btnRefreshDashboard'"))
            before = len(requests)
            prior_rank_reads = cdp.evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/opportunity-rankings')).length")
            cdp.key("Enter", "Enter", 13)
            check(label + ".native_enter_refreshes_retained_ranking", cdp.wait_for(
                "document.getElementById('opportunityRankingsContainer').textContent.includes('Current candidate priority') && performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/opportunity-rankings')).length>" + str(prior_rank_reads)))
            check(label + ".refresh_made_new_get_requests", len(requests) > before)
            cdp.evaluate("document.querySelector('[data-tab=tab-option-apex]').focus()")
            check(label + ".option_navigation_focus_target", cdp.evaluate(
                "document.activeElement.getAttribute('data-tab')==='tab-option-apex'"))
            cdp.key("Enter", "Enter", 13)
            check(label + ".native_enter_changes_tab_state", cdp.evaluate(
                "!document.getElementById('tab-option-apex').classList.contains('hidden') && document.getElementById('tab-terminal').classList.contains('hidden')"))
            cdp.evaluate("document.querySelector('[data-tab=\"tab-terminal\"]').focus()")
            cdp.key("Enter", "Enter", 13)
            mode["lifetime"] = 1.0
            cdp.evaluate("document.getElementById('btnRefreshDashboard').focus()")
            cdp.key("Enter", "Enter", 13)
            check(label + ".short_lived_rank_initially_current", cdp.wait_for(
                "document.getElementById('opportunityRankingsContainer').textContent.includes('Current candidate priority')"))
            check(label + ".real_timer_expires_to_historical_rows", cdp.wait_for(
                "document.getElementById('opportunityRankingsContainer').textContent.includes('Historical priority only') && document.getElementById('opportunityRankingsContainer').textContent.includes('Historical rank 1')", timeout=3))
            mode.update(fail_signals=True, fail_ranks=True)
            cdp.key("Enter", "Enter", 13)
            check(label + ".http_503_clears_cached_ranks_and_signal_prices", cdp.wait_for(
                "document.getElementById('opportunityRankingsContainer').textContent.includes('No cached ranks retained') && document.getElementById('detailSymbolTitle').textContent==='API Error' && document.getElementById('detailEntryPrice').textContent==='--' && !document.getElementById('signalCardsContainer').textContent.includes('RELIANCE')"))
            mode.update(fail_signals=False, fail_ranks=False, lifetime=30, delay_rank=True)
            rank_waiting.clear()
            release_rank.clear()
            cdp.key("Enter", "Enter", 13)
            check(label + ".delayed_rank_request_started", cdp.wait_for(
                "document.getElementById('opportunityRankingsContainer').textContent.includes('Reading stored candidate priority')") and rank_waiting.wait(timeout=.5))
            mode["fail_health"] = True
            cdp.key("Enter", "Enter", 13)
            check(label + ".newer_health_failure_clears_rank_panel", cdp.wait_for(
                "document.getElementById('headerDataModeBadge').textContent==='API DISCONNECTED' && document.getElementById('opportunityRankingsContainer').textContent.includes('unavailable')"))
            release_rank.set()
            # Drain delayed response and all Promise callbacks using the real event loop.
            cdp.evaluate("new Promise(resolve=>setTimeout(()=>resolve(true),150))")
            check(label + ".late_rank_response_cannot_restore_old_current_state", cdp.evaluate(
                "!document.getElementById('opportunityRankingsContainer').textContent.includes('Current candidate priority') && !document.getElementById('opportunityRankingsContainer').textContent.includes('Historical rank 1')"))
            cdp.evaluate("window.scrollTo(0,0)")
            screenshot = EVIDENCE / (prefix + "_" + label + ".png")
            image = cdp.command("Page.captureScreenshot", dict(format="png", captureBeyondViewport=False))
            with screenshot.open("xb") as stream:
                stream.write(base64.b64decode(image["data"]))
            receipt["screenshots"].append(dict(file=screenshot.name, sha256=sha(screenshot),
                viewport=dict(width=width, height=height, mobile=mobile),
                scope="ACTUAL_ASSET_FAILURE_STATE_DIAGNOSTIC"))
        check("external_fetch_blocked_before_transport", cdp.evaluate(
            "fetch('https://blocked.example/offline-interception-probe').then(()=>false).catch(()=>true)") is True
            and any(row["host"] == "blocked.example" for row in cdp.blocked))
        check("post_scan_probe_blocked_before_fixture_server", cdp.evaluate(
            "fetch('/api/scan',{method:'POST'}).then(()=>false).catch(()=>true)") is True
            and any(row["method"] == "POST" and row["path"] == "/api/scan" for row in cdp.blocked))
        check("only_get_head_reached_exact_fixture_origin", all(row["method"] in ("GET", "HEAD") for row in cdp.allowed)
            and all(row["method"] == "GET" for row in requests))
        check("no_scan_or_mutation_reached_server", not any(row["path"] == "/api/scan" for row in requests))
        check("no_javascript_exceptions_or_browser_crashes", not cdp.exceptions and not cdp.crashes)
        check("no_fixture_server_failures", not failures, failures)
    finally:
        release_rank.set()
        if cdp:
            receipt.update(cached_assets_fulfilled=cdp.fulfilled, cdp_allowed_requests=cdp.allowed, cdp_blocked_requests=cdp.blocked,
                javascript_exceptions=cdp.exceptions, browser_crashes=cdp.crashes)
            try:
                cdp.send("Browser.close")
            except Exception:
                pass
        if websocket:
            websocket.close()
        if process:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], timeout=4,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                process.wait(timeout=2)
            receipt["browser_exit_code"] = process.returncode
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join(timeout=2)
            receipt["server_thread_stopped"] = not worker.is_alive()
        if profile_temp:
            profile_temp.cleanup()
            receipt["temporary_profile_removed"] = not profile.exists()
        receipt.update(actual_fixture_requests=requests, fixture_server_failures=failures,
            browser_run_seconds=round(time.monotonic() - started, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--browser", choices=sorted(BROWSERS), default="chrome")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]{2,60}", args.stage):
        parser.error("stage must use 2-60 lower-case letters/digits/underscores")
    prefix = "astra_browser_assets_" + args.stage
    output, log = EVIDENCE / (prefix + ".json"), EVIDENCE / (prefix + ".txt")
    if list(EVIDENCE.glob(prefix + ".*")) or list(EVIDENCE.glob(prefix + "_*.png")):
        parser.error("unique stage required; prior receipts are immutable")
    sources = ["public/index.html", "test_cash_dashboard.js"]
    receipt = dict(schema_version="tradepulse.astra-browser-dom-keyboard.v1", status="FAIL",
        checks=[], started_at=datetime.now(timezone.utc).isoformat(), browser=args.browser,
        command=[str(Path(sys.executable)), "-B", "-W", "error::ResourceWarning",
            str(Path(__file__).relative_to(APP)), "--stage", args.stage, "--browser", args.browser],
        fixture_scope=SCOPE, helper_sha256=sha(Path(__file__)), external_assets_omitted=False,
        scope="ACTUAL_ASSET_BROWSER_RESPONSIVE_KEYBOARD_LIMITED_ACCESSIBILITY",
        source_before={name: sha(APP / name) for name in sources},
        application_modules_imported=False, operational_database_accessed=False, environment_files_read=False,
        limitations=["Authored HTTP fixtures do not establish actual backend or LIVE integration",
            "Exact manifest assets fulfilled from retained public bytes; no external page transport",
            "Four viewport authored-data checks; limited accessibility, no full WCAG attestation",
            "Screenshots use actual assets; positive chart coverage is signal chart only",
            "CDP blocks external requests and all methods except exact-origin GET/HEAD",
            "Browser background-networking suppression is configuration, not OS packet capture"])
    code = 1
    with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream):
        try:
            run(receipt, args.browser, prefix)
            passed = all(c["passed"] for c in receipt["checks"])
            receipt["status"], code = ("PASS", 0) if passed else ("FAIL", 1)
        except Exception as exc:
            receipt.update(error_type=type(exc).__name__, error_code=str(exc)[:500])
            traceback.print_exc()
        receipt["source_after"] = {name: sha(APP / name) for name in sources}
        receipt["source_unchanged"] = receipt["source_before"] == receipt["source_after"]
        if not receipt["source_unchanged"]:
            receipt["status"], code = "FAIL", 1
            receipt["closeout_failure"] = "SOURCE_CHANGED_DURING_CHECK"
        if code == 0 and (receipt.get("browser_exit_code") != 0 or not receipt.get("server_thread_stopped")
                or not receipt.get("temporary_profile_removed") or receipt.get("browser_run_seconds", 60) >= 60):
            receipt["status"], code = "FAIL", 1
            receipt["closeout_failure"] = "CLEANUP_OR_DURATION_FAILURE"
        receipt["exit_code"] = code
        print(json.dumps(dict(status=receipt["status"], checks=len(receipt["checks"]), exit_code=code)))
    receipt["asset_manifest_sha256"] = sha(MANIFEST)
    receipt["probe_helper_sha256"] = sha(EVIDENCE / "astra_browser_ui_probes_20261028_01.py")
    receipt["log_file"], receipt["log_sha256"] = log.name, sha(log)
    receipt["source_sha256"] = receipt["source_before"]
    receipt["cases"] = receipt["checks"]
    receipt["assertions"] = dict(total=len(receipt["checks"]),
        passed=sum(item["passed"] for item in receipt["checks"]))
    receipt["artifacts"] = [dict(file=log.name, sha256=sha(log)),
        dict(file=Path(__file__).name, sha256=sha(Path(__file__)))] + receipt.get("screenshots", [])
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    print(json.dumps(dict(status=receipt["status"], checks=len(receipt["checks"]), receipt=output.name,
        seconds=receipt.get("browser_run_seconds"), error=receipt.get("error_code"), exit_code=code)))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
