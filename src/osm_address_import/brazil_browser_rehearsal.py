"""Headless Firefox check of all seven iD editor centers in the isolated copy."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from osm_address_import.brazil_login_rehearsal import authenticated_session
from osm_address_import.brazil_reports import _atomic_text


def webdriver(opener, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request("http://127.0.0.1:4444" + path, data=data,
                      headers={"Content-Type": "application/json"}, method=method)
    with opener.open(request, timeout=60) as response:
        result = json.load(response)
    if "value" not in result:
        raise RuntimeError(f"invalid WebDriver result for {path}")
    value = result["value"]
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"WebDriver {value['error']}: {value.get('message', '')[:300]}")
    return value


def run(project, credentials, run_dir, config, geckodriver):
    _opener, jar, _login_url, _base = authenticated_session(
        project, credentials, base="https://127.0.0.1:39004")
    session_cookie = next((cookie for cookie in jar if cookie.name == "_osm_session"), None)
    if session_cookie is None:
        raise RuntimeError("authenticated session cookie is missing")
    spec = json.loads(config.read_text())
    opener = build_opener(ProxyHandler({}))
    process = subprocess.Popen([geckodriver, "--port", "4444", "--log", "fatal"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError("geckodriver exited before browser session started")
            try:
                status = webdriver(opener, "GET", "/status")
                if status.get("ready"):
                    break
            except (URLError, TimeoutError):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("geckodriver did not become ready")
        capabilities = {"capabilities": {"alwaysMatch": {
            "browserName": "firefox", "pageLoadStrategy": "eager",
            "acceptInsecureCerts": True,
            "moz:firefoxOptions": {"args": ["-headless"], "prefs": {
                "network.proxy.type": 1, "network.proxy.http": "127.0.0.1",
                "network.proxy.http_port": 39005, "network.proxy.ssl": "127.0.0.1",
                "network.proxy.ssl_port": 39005,
                "network.proxy.no_proxies_on": "127.0.0.1,localhost",
            }}}}}
        created = webdriver(opener, "POST", "/session", capabilities)
        session = created["sessionId"]
        prefix = f"/session/{session}"
        webdriver(opener, "POST", prefix + "/url", {"url": "https://127.0.0.1:39004/"})
        webdriver(opener, "POST", prefix + "/cookie", {"cookie": {
            "name": "_osm_session", "value": session_cookie.value,
            "path": "/", "secure": True, "sameSite": "Lax"}})
        results = {}
        for city in spec["cities"]:
            slug = city["slug"]
            fixture = json.loads((run_dir / f"{slug}-fixtures.json").read_text())
            lon, lat = fixture["editor_center"]["lon"], fixture["editor_center"]["lat"]
            url = f"https://127.0.0.1:39004/edit?editor=id#map=17/{lat}/{lon}"
            webdriver(opener, "POST", prefix + "/url", {"url": url})
            time.sleep(8)
            webdriver(opener, "POST", prefix + "/execute/sync", {"script": "const f=document.querySelector('#id-embed');const d=f&&f.contentDocument;const b=d&&Array.from(d.querySelectorAll('button')).find(x=>x.textContent.includes('Edit now'));if(b)b.click();return !!b", "args": []})
            time.sleep(3)
            current = webdriver(opener, "GET", prefix + "/url")
            dom = webdriver(opener, "POST", prefix + "/execute/sync", {"script": "const f=document.querySelector('#id-embed');const d=f&&f.contentDocument;const p=d&&d.defaultView&&d.defaultView.performance;return {title:document.title,iframe:!!f,idRoot:!!(d&&d.querySelector('#id-container')),osmPaths:d?d.querySelectorAll('path.osm, path.line, path.area').length:0,mapRequests:p?p.getEntriesByType('resource').filter(x=>x.name.includes('/api/0.6/map')).length:0,iframeBodyLength:d&&d.body?d.body.innerHTML.length:0,bodyLength:document.body.innerHTML.length,errorDialog:document.body.innerText.includes('iD has not been configured')}", "args": []})
            screenshot = webdriver(opener, "GET", prefix + "/screenshot")
            screenshot_path = run_dir / f"stage-editor-{slug}.png"
            screenshot_path.write_bytes(base64.b64decode(screenshot))
            results[slug] = {"url": current, "dom": dom,
                             "screenshot": screenshot_path.name,
                             "status": "PASS" if "/edit" in current and dom["idRoot"] and dom["mapRequests"] > 0 and dom["osmPaths"] > 0 and not dom["errorDialog"] else "FAIL"}
        report = {"project": project, "browser": "Firefox headless",
                  "external_network": "only cdn.jsdelivr.net allowed by browser proxy; loopback allowed",
                  "cities": results,
                  "status": "PASS" if all(item["status"] == "PASS" for item in results.values()) else "FAIL"}
        _atomic_text(run_dir / "stage-browser.json",
                     json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return report
    finally:
        if session is not None:
            try:
                webdriver(opener, "DELETE", f"/session/{session}")
            except Exception:
                pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    args = parser.parse_args()
    print(run(args.project, args.credentials, args.run_dir, args.config,
              args.geckodriver)["status"])


if __name__ == "__main__":
    main()
