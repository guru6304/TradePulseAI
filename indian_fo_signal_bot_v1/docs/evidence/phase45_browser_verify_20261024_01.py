"""Bounded actual-Chrome DOM check, using loopback memory fixtures only.

No visual/CDN/provider/source-rights or external delivery acceptance is claimed.
The served production HTML retains its actual inline renderers. External assets
are removed, Chart/Tailwind have explicit test stubs, and renderer hooks are added.
"""
import argparse
import copy
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import timedelta, datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from unittest.mock import patch

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CDP:
    def __init__(self, ws, origin):
        self.ws, self.origin, self.sequence = ws, origin, 0
        self.allowed, self.blocked, self.exceptions = [], [], []

    def send(self, method, params=None):
        self.sequence += 1
        self.ws.send(json.dumps(dict(id=self.sequence, method=method, params=params or {})))
        return self.sequence

    def command(self, method, params=None, timeout=5):
        request = self.send(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = json.loads(self.ws.recv(timeout=max(.05, deadline - time.monotonic())))
            if response.get("method") == "Fetch.requestPaused":
                event = response["params"]
                url = urllib.parse.urlsplit(event["request"]["url"])
                allowed = url.scheme == "http" and (url.scheme + "://" + url.netloc) == self.origin
                allowed = allowed and event["request"]["method"] in ("GET", "HEAD")
                record = dict(scheme=url.scheme, host=url.hostname, path=url.path,
                              method=event["request"]["method"])
                if allowed:
                    self.allowed.append(record)
                    self.send("Fetch.continueRequest", dict(requestId=event["requestId"]))
                else:
                    self.blocked.append(record)
                    self.send("Fetch.failRequest", dict(requestId=event["requestId"], errorReason="BlockedByClient"))
            elif response.get("method") == "Runtime.exceptionThrown":
                details = response["params"]["exceptionDetails"]
                self.exceptions.append(dict(text=details.get("text"), line=details.get("lineNumber")))
            elif response.get("id") == request:
                if "error" in response:
                    raise RuntimeError("CDP_COMMAND_FAILED_" + method)
                return response.get("result", {})
        raise RuntimeError("CDP_TIMEOUT_" + method)

    def evaluate(self, expression):
        result = self.command("Runtime.evaluate", dict(expression=expression, awaitPromise=True,
                                                        returnByValue=True), timeout=8)
        if result.get("exceptionDetails"):
            raise RuntimeError("BROWSER_EVALUATION_EXCEPTION")
        return result.get("result", {}).get("value")


def instrument_html(original):
    scripts = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"'][^\"']+[\"'][^>]*>.*?</script\s*>", re.I | re.S)
    links = re.compile(r"<link\b[^>]*\bhref\s*=\s*[\"']https?://[^\"']+[\"'][^>]*>", re.I)
    body, script_count = scripts.subn("<!-- external script omitted in offline browser fixture -->", original)
    body, link_count = links.subn("<!-- external link omitted in offline browser fixture -->", body)
    stubs = """<script>window.tailwind={}; window.Chart=class OfflineChartStub {
      constructor(ctx,config){this.data=config.data;this.options=config.options||{};}
      destroy(){} update(){} };</script>"""
    body = body.replace("<head>", "<head>" + stubs, 1)
    marker = "      window.addEventListener('DOMContentLoaded', function() {"
    if body.count(marker) != 1:
        raise RuntimeError("BROWSER_HOOK_BOUNDARY_CHANGED")
    hooks = """      window.__tradepulseBrowserTest={state:state,loadSignals:loadSignals,
        renderSelectedSignalInspector:renderSelectedSignalInspector,
        configureAutoRefreshTimer:configureAutoRefreshTimer};
"""
    return body.replace(marker, hooks + marker, 1).encode(), dict(external_scripts_omitted=script_count,
        external_links_omitted=link_count, chart_stub=True, tailwind_stub=True,
        inline_renderer_implementations_changed=False, test_hooks_added=True)


def run(receipt):
    # Save primitives before existing fixtures install their stricter no-network
    # guards; the replacement below permits only this task's literal loopback.
    original_connect, original_create = socket.socket.connect, socket.create_connection
    original_lookup, original_urlopen = socket.getaddrinfo, urllib.request.urlopen
    from websockets.sync.client import connect
    from test_phase45_integration import TestPhase45IndependentIntegration
    from scanner_engine import MarketScanScheduler
    from server import DashboardRequestHandler, create_http_server

    if not CHROME.is_file():
        raise RuntimeError("INSTALLED_CHROME_NOT_FOUND")
    fixture = TestPhase45IndependentIntegration()
    fixture.setUp()
    process, server, server_thread, websocket, temp = None, None, None, None, None
    cdp = None
    checks = receipt["checks"]
    def check(name, value):
        checks.append(dict(name=name, passed=value is True))
        if value is not True:
            raise AssertionError(name)
    def literal_loopback(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    def guarded_connect(sock, address):
        if not isinstance(address, tuple) or not literal_loopback(address[0]):
            raise AssertionError("NON_LOOPBACK_NETWORK_FORBIDDEN")
        return original_connect(sock, address)
    def guarded_lookup(host, *args, **kwargs):
        if not literal_loopback(host):
            raise AssertionError("NON_LOOPBACK_DNS_FORBIDDEN")
        return original_lookup(host, *args, **kwargs)
    def local_urlopen(url, *args, **kwargs):
        value = url.full_url if isinstance(url, urllib.request.Request) else url
        parts = urllib.parse.urlsplit(value)
        if parts.scheme != "http" or not literal_loopback(parts.hostname):
            raise AssertionError("NON_LOOPBACK_HTTP_FORBIDDEN")
        return original_urlopen(url, *args, **kwargs)
    try:
        fixture.source.row.update(title='OFFLINE_SOURCE_TEXT <img src=x onerror="window.__tpXss=1">',
            summary='Literal untrusted source markup <script>window.__tpXss=2</script>')
        engine, _, raw = fixture.engine()
        fixture.import_source(engine, raw)
        summary = engine.run_single_scan()
        check("actual_memory_candidate_and_qualified_signed_fixture", summary["total_signals"] == 1
              and summary["context"]["status"] == "QUALIFIED")
        original = (APP / "public/index.html").read_text(encoding="utf-8")
        html, preparation = instrument_html(original)
        receipt["html_fixture_preparation"] = preparation
        mode, api_requests = dict(fail_signals=False), []
        class FixtureHandler(DashboardRequestHandler):
            def log_message(self, *args):
                pass
            def _try_serve_approved_public_asset(self, raw_path, send_body=True):
                if raw_path in ("/", "/index.html", "/public/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    if send_body:
                        self.wfile.write(html)
                    return True
                return super()._try_serve_approved_public_asset(raw_path, send_body)
            def _handle_signals(self, query):
                if mode["fail_signals"]:
                    return 503, dict(status="UNAVAILABLE", message="OFFLINE fixture source read failure")
                return super()._handle_signals(query)
            def do_GET(self):
                api_requests.append(urllib.parse.urlsplit(self.path).path)
                return super().do_GET()
            def do_POST(self):
                self._send_json(405, dict(status="OFFLINE_BROWSER_GET_ONLY"))
                raise AssertionError("BROWSER_MUTATION_FORBIDDEN")
        FixtureHandler.engine = engine
        FixtureHandler.scheduler = MarketScanScheduler(engine)
        FixtureHandler.evidence_scope = "OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE"
        server = create_http_server("127.0.0.1", 0, FixtureHandler)
        origin = "http://127.0.0.1:" + str(server.server_address[1])
        server_thread = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=.05), daemon=True)
        server_thread.start()
        with ExitStack() as stack:
            stack.enter_context(patch("socket.socket.connect", new=guarded_connect))
            stack.enter_context(patch("socket.getaddrinfo", new=guarded_lookup))
            stack.enter_context(patch("socket.create_connection", new=original_create))
            stack.enter_context(patch("urllib.request.urlopen", new=local_urlopen))
            temp = tempfile.TemporaryDirectory(prefix="tradepulse-browser-fixture-")
            profile = Path(temp.name).resolve()
            if profile.parent != Path(tempfile.gettempdir()).resolve() or not profile.name.startswith("tradepulse-browser-fixture-"):
                raise RuntimeError("UNSAFE_TEMP_PROFILE_PATH")
            args = [str(CHROME), "--headless=new", "--disable-gpu", "--disable-background-networking",
                "--disable-component-update", "--disable-default-apps", "--disable-extensions", "--disable-sync",
                "--disable-domain-reliability", "--disable-client-side-phishing-detection", "--disable-breakpad",
                "--disable-crash-reporter", "--disable-pings", "--safebrowsing-disable-auto-update",
                "--metrics-recording-only", "--no-first-run", "--no-default-browser-check",
                "--password-store=basic", "--use-mock-keychain", "--disable-search-engine-choice-screen",
                "--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication,Translate,NetworkTimeServiceQuerying",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                "--user-data-dir=" + str(profile), "about:blank"]
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            debugger = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 12
            while not debugger.is_file():
                if process.poll() is not None:
                    raise RuntimeError("CHROME_EXIT_BEFORE_DEBUGGER")
                if time.monotonic() >= deadline:
                    raise RuntimeError("CHROME_DEBUGGER_START_TIMEOUT")
                time.sleep(.05)
            port = int(debugger.read_text().splitlines()[0])
            with local_urlopen("http://127.0.0.1:" + str(port) + "/json/list", timeout=3) as response:
                targets = json.loads(response.read(1024 * 1024))
            target = next(row for row in targets if row.get("type") == "page")
            target_url = urllib.parse.urlsplit(target["webSocketDebuggerUrl"])
            if target_url.scheme != "ws" or target_url.hostname != "127.0.0.1":
                raise RuntimeError("NON_LOOPBACK_DEBUGGER_TARGET")
            websocket = connect(target["webSocketDebuggerUrl"], open_timeout=3, close_timeout=2,
                                max_size=4 * 1024 * 1024, proxy=None)
            cdp = CDP(websocket, origin)
            receipt["browser"] = cdp.command("Browser.getVersion")
            cdp.command("Runtime.enable")
            cdp.command("Page.enable")
            cdp.command("Fetch.enable", dict(patterns=[dict(urlPattern="*", requestStage="Request")]))
            cdp.command("Page.navigate", dict(url=origin + "/"))
            deadline = time.monotonic() + 15
            ready = False
            while time.monotonic() < deadline:
                ready = cdp.evaluate("Boolean(window.__tradepulseBrowserTest && window.__tradepulseBrowserTest.state.signals.length===1 && document.getElementById('detailContext').textContent.includes('OFFLINE_SOURCE_TEXT'))")
                if ready:
                    break
                time.sleep(.05)
            check("actual_dashboard_loaded_real_signals_api_and_rendered_context", ready)
            cdp.evaluate("window.__tradepulseBrowserTest.configureAutoRefreshTimer(0)")
            check("source_markup_is_literal_text_not_executable_dom", cdp.evaluate("document.getElementById('detailContext').textContent.includes('<img src=x onerror=') && document.querySelectorAll('#detailContext img,#detailContext script').length===0 && window.__tpXss===undefined"))
            check("safe_https_source_link_has_blank_noopener_noreferrer", cdp.evaluate("(()=>{const a=document.querySelector('#detailContext a');return Boolean(a&&a.href==='https://issuer.example/notice/123'&&a.target==='_blank'&&a.relList.contains('noopener')&&a.relList.contains('noreferrer'));})()"))
            check("decision_time_and_source_authority_limits_rendered", cdp.evaluate("(()=>{const t=document.getElementById('detailContext').textContent;return t.includes('DECISION_TIME')&&t.includes('As of')&&t.includes('Original decision')&&t.includes('independent authority/rights not established')&&t.includes('Published:')&&t.includes('Collected:');})()"))
            fixture.market.clock_value += timedelta(seconds=10)
            engine.enrich_context(summary["run_id"], evaluation_mode="CURRENT_INFORMATION")
            cdp.evaluate("window.__tradepulseBrowserTest.loadSignals()")
            check("actual_api_current_information_scope_is_explicit", cdp.evaluate("(()=>{const t=document.getElementById('detailContext').textContent;return t.includes('CURRENT_INFORMATION')&&t.includes('Current information for a stored candidate; no current recommendation');})()"))
            fixture.market.clock_value += timedelta(days=2)
            engine.enrich_context(summary["run_id"], evaluation_mode="CURRENT_INFORMATION")
            cdp.evaluate("window.__tradepulseBrowserTest.loadSignals()")
            check("actual_api_stale_context_and_suppression_rendered", cdp.evaluate("(()=>{const t=document.getElementById('detailContext').textContent;return t.includes('WARNING_ONLY')&&t.includes('CONTEXT_STALE')&&t.includes('Context alert SUPPRESSED');})()"))
            cdp.evaluate("(()=>{const h=window.__tradepulseBrowserTest;const s=structuredClone(h.state.signals[0]);s.context.status='QUALIFIED';s.context.records[0].freshness.status='FRESH';s.context.records[0].instrument_identity.symbol='SBIN';h.renderSelectedSignalInspector(s);})()")
            check("inconsistent_mapping_clears_prior_source_text", cdp.evaluate("document.getElementById('detailContext').textContent.includes('Context UNAVAILABLE')&&!document.getElementById('detailContext').textContent.includes('OFFLINE_SOURCE_TEXT')"))
            cdp.evaluate("(()=>{const h=window.__tradepulseBrowserTest;const s=structuredClone(h.state.signals[0]);s.context={status:'MISSING',candidate_id:s.candidate_evaluation.candidate_id,records:[],reason_codes:['CONTEXT_MISSING'],actionable:false,affects_ranking:false};h.renderSelectedSignalInspector(s);})()")
            check("missing_context_replaces_old_source_without_neutral_claim", cdp.evaluate("(()=>{const t=document.getElementById('detailContext').textContent;return t.includes('Context MISSING')&&t.includes('No context record available')&&!t.includes('OFFLINE_SOURCE_TEXT');})()"))
            mode["fail_signals"] = True
            cdp.evaluate("window.__tradepulseBrowserTest.loadSignals()")
            check("actual_503_api_failure_clears_old_context_and_signals", cdp.evaluate("window.__tradepulseBrowserTest.state.signals.length===0&&document.getElementById('detailSymbolTitle').textContent==='API Error'&&!document.getElementById('detailContext').textContent.includes('OFFLINE_SOURCE_TEXT')"))
            cdp.evaluate("fetch('https://blocked.example/offline-interception-probe').then(()=>false).catch(()=>true)")
            check("external_probe_blocked_before_request_transport", any(row["host"] == "blocked.example" for row in cdp.blocked))
            check("no_browser_javascript_runtime_exception", not cdp.exceptions)
            check("only_get_head_requests_reached_loopback_application", all(row["method"] in ("GET", "HEAD") for row in cdp.allowed))
            receipt["requests"] = dict(allowed_same_origin=len(cdp.allowed), blocked_external=len(cdp.blocked),
                blocked=cdp.blocked, actual_api_paths=sorted(set(api_requests)))
            receipt["runtime_exceptions"] = cdp.exceptions
    finally:
        if cdp:
            try:
                cdp.send("Browser.close")
            except Exception:
                pass
        if websocket:
            websocket.close()
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                process.wait(timeout=3)
            receipt["chrome_exit_code"] = process.returncode
        if server:
            server.shutdown()
            server.server_close()
        if server_thread:
            server_thread.join(timeout=3)
            receipt["server_thread_stopped"] = not server_thread.is_alive()
        fixture.doCleanups()
        if temp:
            temp.cleanup()
            receipt["temporary_profile_removed"] = not Path(temp.name).exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="01")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{2}", args.stage):
        parser.error("stage must be two digits")
    prefix = "phase45_browser_20261024_" + args.stage
    output, log = APP / "docs/evidence" / (prefix + ".json"), APP / "docs/evidence" / (prefix + ".txt")
    if output.exists() or log.exists():
        parser.error("unique stage required; prior evidence is immutable")
    sources = ("public/index.html", "server.py", "scanner_engine.py", "context_data.py", "context_workflow.py",
               "notification_outbox.py", "telegram_bot.py", "test_phase45_integration.py")
    receipt = dict(schema_version="tradepulse.actual-browser-check.v1", status="FAILED", checks=[],
        started_at=datetime.now(timezone.utc).isoformat(), fixture_scope="OFFLINE_AUTHORED_MEMORY_ONLY",
        command=[str(Path(sys.executable)), "-B", str(Path(__file__).relative_to(APP)), "--stage", args.stage],
        source_before={name: sha(APP / name) for name in sources}, helper_sha256=sha(Path(__file__)),
        limitations=["CDN/CSS dependencies omitted", "Chart rendering stubbed", "No full visual/browser compatibility claim",
                     "No genuine source authority/rights or LIVE acceptance", "No provider/network/message/order requests"])
    started = time.monotonic()
    code = 1
    with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream):
        try:
            run(receipt)
            receipt["status"], code = "PASS", 0
        except Exception as exc:
            receipt["error_type"], receipt["error_code"] = type(exc).__name__, str(exc)[:160]
            print(type(exc).__name__, str(exc)[:160])
        receipt["source_after"] = {name: sha(APP / name) for name in sources}
        receipt["source_unchanged"] = receipt["source_before"] == receipt["source_after"]
        if not receipt["source_unchanged"]:
            receipt["status"], code = "SOURCE_CHANGED_DURING_CHECK", 1
        receipt["duration_seconds"] = round(time.monotonic() - started, 3)
        receipt["exit_code"] = code
        print(json.dumps(dict(status=receipt["status"], checks=len(receipt["checks"]), exit_code=code)))
    receipt["log_file"], receipt["log_sha256"] = log.name, sha(log)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    print(json.dumps(dict(status=receipt["status"], checks=len(receipt["checks"]), receipt=output.name, exit_code=code)))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
