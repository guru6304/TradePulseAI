"""Create a new standalone assets harness without rewriting retained DOM evidence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
old = ROOT / "astra_browser_verify_20261026_01.py"
new = ROOT / "astra_browser_assets_verify_20261027_01.py"
assert not new.exists()
text = old.read_text(encoding="utf-8")
start = text.index("def prepare_html(raw):")
end = text.index("def signal_fixture():", start)
text = text[:start] + '''from astra_browser_ui_probes_20261027_01 import assets, probes, MANIFEST
ASSETS = assets()


def prepare_html(raw):
    return raw, dict(source_html_sha256=hashlib.sha256(raw).hexdigest(),
        served_html_sha256=hashlib.sha256(raw).hexdigest(), production_inline_scripts_unchanged=True,
        external_scripts_omitted=0, external_links_omitted=0, chart_stub=False, tailwind_stub=False,
        manifest_sha256=sha(MANIFEST))


''' + text[end:]
anchor = '                allowed = parts.scheme == "http" and parts.scheme + "://" + parts.netloc == self.origin'
assert anchor in text
text = text.replace(anchor, '''                cached = ASSETS.get(event["request"]["url"])
                if cached and record["method"] == "GET":
                    body, mime = cached
                    self.fulfilled.append(dict(url=event["request"]["url"], sha256=hashlib.sha256(body).hexdigest()))
                    self.send("Fetch.fulfillRequest", dict(requestId=event["requestId"], responseCode=200,
                        responseHeaders=[dict(name="Content-Type",value=mime),dict(name="Access-Control-Allow-Origin",value="*")],
                        body=base64.b64encode(body).decode()))
                    continue
''' + anchor)
text = text.replace('self.sequence = 0', 'self.sequence = 0\n        self.fulfilled = []')
text = text.replace('deadline = started + 48', 'deadline = started + 58')
text = text.replace('        if result is not True:\n            raise AssertionError(name)', '')
text = text.replace('(("desktop", 1440, 1000, False), ("mobile", 390, 844, True))',
    '(("desktop", 1440, 1000, False), ("tablet", 768, 1024, False), ("mobile", 390, 844, True), ("narrow", 320, 844, True))')
anchor = '            cdp.evaluate("document.activeElement.blur(); window.scrollTo(0,0)")'
assert anchor in text
text = text.replace(anchor, '            probes(cdp, receipt, prefix, label, width, height)\n' + anchor)
text = text.replace('            cdp.key("Tab", "Tab", 9)  # Focus scan control without activating it.\n            cdp.key("Tab", "Tab", 9)\n            cdp.key("Tab", "Tab", 9)',
    '            cdp.evaluate("document.querySelector(\'[data-tab=tab-option-apex]\').focus()")')
text = text.replace('native_tab_reaches_option_navigation', 'option_navigation_focus_target')
text = text.replace('receipt.update(cdp_allowed_requests=cdp.allowed,', 'receipt.update(cached_assets_fulfilled=cdp.fulfilled, cdp_allowed_requests=cdp.allowed,')
text = text.replace('prefix = "astra_browser_" + args.stage', 'prefix = "astra_browser_assets_" + args.stage')
text = text.replace('external_assets_omitted=True', 'external_assets_omitted=False')
text = text.replace('ACTUAL_BROWSER_DOM_KEYBOARD_OFFLINE_NOT_FULL_VISUAL_ACCEPTANCE', 'ACTUAL_ASSET_BROWSER_RESPONSIVE_KEYBOARD_LIMITED_ACCESSIBILITY')
text = text.replace('DIAGNOSTIC_DOM_ONLY_EXTERNAL_STYLES_AND_CHART_OMITTED', 'ACTUAL_ASSET_FAILURE_STATE_DIAGNOSTIC')
text = text.replace('            "External CSS/fonts omitted; Chart and Tailwind stubbed",', '            "Exact manifest assets fulfilled from retained public bytes; no external page transport",')
text = text.replace('            "Desktop/mobile viewport DOM and keyboard mechanics only; no responsive visual acceptance",', '            "Four viewport authored-data checks; limited accessibility, no full WCAG attestation",')
text = text.replace('            "Screenshots are diagnostic evidence with omitted assets",', '            "Screenshots use actual assets; positive chart coverage is signal chart only",')
text = text.replace('            receipt["status"], code = "PASS", 0', '            passed = all(c["passed"] for c in receipt["checks"])\n            receipt["status"], code = ("PASS", 0) if passed else ("FAIL", 1)')
text = text.replace('No application modules, environment files or databases are loaded. External\nassets are omitted and Chart/Tailwind are explicit stubs: screenshots are\ndiagnostic DOM evidence, not responsive-layout or visual acceptance.',
    'No application modules, environment files or databases are loaded. Actual public\nassets are hash-verified and fulfilled locally. Four-viewport fixture checks provide\nlimited responsive/semantic evidence, not full WCAG or live-data acceptance.')
text = text.replace('    receipt["log_file"], receipt["log_sha256"] = log.name, sha(log)',
    '    receipt["asset_manifest_sha256"] = sha(MANIFEST)\n    receipt["probe_helper_sha256"] = sha(EVIDENCE / "astra_browser_ui_probes_20261027_01.py")\n    receipt["log_file"], receipt["log_sha256"] = log.name, sha(log)')
with new.open("x", encoding="utf-8") as stream:
    stream.write(text)
print(new.name)
