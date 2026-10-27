"""Explicit public UI dependency acquisition. No application/broker imports."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

APP = Path(__file__).resolve().parents[2]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com", "cdn.tailwindcss.com", "cdn.jsdelivr.net", "raw.githubusercontent.com"}
CACHE = APP / ".local/astra_browser_assets_20261027_01"


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("ASSET_HOST_NOT_PERMITTED")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def acquire(item):
    url, role = item
    validate_url(url)
    opener = build_opener(SafeRedirect())
    with opener.open(Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"}), timeout=20) as response:
        body = response.read(8 * 1024 * 1024 + 1)
        if response.status != 200 or not body or len(body) > 8 * 1024 * 1024:
            raise ValueError("INVALID_ASSET_RESPONSE")
        final_url = validate_url(response.url)
        content_type = response.headers.get("Content-Type", "application/octet-stream")
    digest = hashlib.sha256(body).hexdigest()
    path = CACHE / digest
    if path.exists():
        assert path.read_bytes() == body
    else:
        with path.open("xb") as stream:
            stream.write(body)
    return dict(url=url, final_url=final_url, role=role, sha256=digest, size_bytes=len(body),
                path=path.relative_to(APP).as_posix(), content_type=content_type,
                retrieved_at=datetime.now(timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9_]+", args.stage)
    target = APP / "docs/evidence" / ("astra_browser_assets_" + args.stage + ".json")
    assert not target.exists()
    CACHE.mkdir(parents=True, exist_ok=True)
    source = (APP / "public/index.html").read_bytes()
    text = source.decode("utf-8")
    fonts = html.unescape(re.search(r'href="(https://fonts.googleapis.com/css2[^\"]+)"', text)[1])
    initial = [(fonts, "font_stylesheet"), ("https://cdn.tailwindcss.com/3.4.17", "tailwind_3.4.17"),
               ("https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js", "chart_4.4.1")]
    licenses = [("https://raw.githubusercontent.com/tailwindlabs/tailwindcss/v3.4.17/LICENSE", "tailwind_MIT"),
        ("https://raw.githubusercontent.com/chartjs/Chart.js/v4.4.1/LICENSE.md", "chart_MIT"),
        ("https://raw.githubusercontent.com/google/fonts/main/ofl/inter/OFL.txt", "inter_OFL"),
        ("https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/OFL.txt", "jetbrainsmono_OFL")]
    receipt = dict(schema_version="tradepulse.public-ui-assets.v1", status="FAIL", user_agent=UA,
        html_sha256=hashlib.sha256(source).hexdigest(), assets=[], licenses=[], errors=[],
        helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope="PUBLIC_UI_ASSETS_ONLY_NO_PROVIDER_REQUESTS", started_at=datetime.now(timezone.utc).isoformat())
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(role, url, pool.submit(acquire, (url, role))) for url, role in initial + licenses]
        for role, url, future in futures:
            try:
                result = future.result()
                receipt["assets" if (url, role) in initial else "licenses"].append(result)
            except Exception as exc:
                receipt["errors"].append(dict(url=url, role=role, error_type=type(exc).__name__))
        css = next((row for row in receipt["assets"] if row["role"] == "font_stylesheet"), None)
        if css:
            stylesheet = (APP / css["path"]).read_text(encoding="utf-8")
            urls = sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", stylesheet)))
            if not 1 <= len(urls) <= 100:
                raise ValueError("INVALID_FONT_URL_COUNT")
            receipt["font_faces"] = [dict(family=re.search(r"font-family:\s*([^;]+)", block)[1],
                weight=re.search(r"font-weight:\s*([^;]+)", block)[1],
                url=re.search(r"url\(([^)]+)\)", block)[1]) for block in re.findall(r"@font-face\s*\{([^}]+)\}", stylesheet)]
            for url, future in [(url, pool.submit(acquire, (url, "font"))) for url in urls]:
                try:
                    receipt["assets"].append(future.result())
                except Exception as exc:
                    receipt["errors"].append(dict(url=url, role="font", error_type=type(exc).__name__))
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    receipt["status"] = "PASS" if not receipt["errors"] and len(receipt["licenses"]) == 4 else "FAIL"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(dict(status=receipt["status"], assets=len(receipt["assets"]), licenses=len(receipt["licenses"]),
                         errors=receipt["errors"], manifest=target.name)))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
