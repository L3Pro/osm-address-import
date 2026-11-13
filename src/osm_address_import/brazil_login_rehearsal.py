"""Check isolated website password login and authenticated editor route."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from osm_address_import.brazil_edit_rehearsal import private_env
from osm_address_import.brazil_reports import _atomic_text
from osm_address_import.docker_isolation import verify_isolated_docker


def authenticated_session(project, credentials, base="http://127.0.0.1:39003"):
    verify_isolated_docker(project)
    if base not in ("http://127.0.0.1:39003", "https://127.0.0.1:39004"):
        raise ValueError("login target must be the isolated loopback listener")
    values = private_env(credentials)
    class LoopbackCookiePolicy(http.cookiejar.DefaultCookiePolicy):
        def return_ok_secure(self, cookie, request):
            return request.full_url.startswith(base + "/")

    class LoopbackRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            if base.startswith("http://") and newurl.startswith("https://127.0.0.1:39003/"):
                newurl = "http://" + newurl[len("https://"):]
            if not newurl.startswith(base + "/"):
                return None
            return super().redirect_request(request, fp, code, msg, headers, newurl)

    jar = http.cookiejar.CookieJar(policy=LoopbackCookiePolicy())
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar),
                          HTTPSHandler(context=ssl._create_unverified_context()),
                          LoopbackRedirect())
    with opener.open(base + "/login", timeout=30) as response:
        form = response.read(100_000).decode("utf-8")
    match = re.search(r'name="authenticity_token" value="([^"]+)"', form)
    if not match:
        raise RuntimeError("isolated login form lacks CSRF token")
    data = urlencode({"authenticity_token": match.group(1),
                      "username": values["OSM_API_ACCOUNT"],
                      "password": values["STAGE_LOGIN_PASSWORD"]}).encode()
    request = Request(base + "/login", data=data,
                      headers={"Content-Type": "application/x-www-form-urlencoded",
                               "Referer": base + "/login?cookie_test=true"}, method="POST")
    with opener.open(request, timeout=30) as response:
        login_page = response.read(200_000).decode("utf-8")
        login_url = response.geturl()
    if "/login" in login_url or values["OSM_API_ACCOUNT"] not in login_page:
        raise RuntimeError("synthetic website password login was not confirmed")
    return opener, jar, login_url, base


def check(project, credentials, report):
    opener, _jar, login_url, base = authenticated_session(project, credentials)
    with opener.open(base + "/edit?editor=id", timeout=30) as response:
        editor_html = response.read(500_000).decode("utf-8")
        editor_url = response.geturl()
        editor_status = response.status
    if "/login" in editor_url or editor_status != 200:
        raise RuntimeError("authenticated iD editor route did not open")
    result = {"status": "PASS", "project": project,
              "login_url": login_url.replace(base, ""),
              "editor_url": editor_url.replace(base, ""),
              "editor_http_status": editor_status,
              "editor_html_bytes": len(editor_html.encode()),
              "note": "HTTP route and login verified; rendering requires a browser"}
    _atomic_text(report, json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(check(args.project, args.credentials, args.report)["status"])


if __name__ == "__main__":
    main()
