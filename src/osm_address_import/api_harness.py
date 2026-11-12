"""Bounded, fail-closed OSM API 0.6 regression checks for the Osaka sandbox."""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from osm_address_import.docker_isolation import verify_isolated_docker


BBOX = "135.4988,34.6652,135.5010,34.6670"
KNOWN_WAY_ID = 658187857
MAX_BODY = 2_000_000
WRITE_CONFIRMATION = "I_APPROVE_SYNTHETIC_WRITE"


class HarnessError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def checked_base_url(value, isolated=False):
    """Accept one exact numeric loopback URL per mode, with no DNS lookup."""
    expected = "http://127.0.0.1:39003" if isolated else "http://127.0.0.1:3003"
    if value != expected:
        raise HarnessError(f"target must exactly equal the approved {'isolated' if isolated else 'smoke'} loopback URL")
    return expected


def xml_root(body, expected="osm"):
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise HarnessError(f"invalid XML: {exc}") from exc
    if root.tag != expected:
        raise HarnessError(f"expected XML <{expected}>, got <{root.tag}>")
    return root


def positive_id(value, label):
    if not re.fullmatch(r"[1-9][0-9]*", value or ""):
        raise HarnessError(f"invalid {label}: {value!r}")
    return int(value)


def safe_error(exc, token=None):
    message = str(exc)
    return message.replace(token, "[REDACTED]") if token else message


class Harness:
    def __init__(self, base_url, token=None, account=None, isolated=False,
                 isolated_project=None, write_enabled=False):
        if write_enabled and (not isolated or not isolated_project):
            raise HarnessError("writes require an isolated target and project")
        self.base_url = checked_base_url(base_url, isolated)
        self.token = token
        self.account = account
        self.isolated_project = isolated_project
        self.write_enabled = write_enabled
        self.results = []
        self.created = {"changeset_id": None, "node_id": None, "marker": None}
        self.changeset_state = "not_started"
        self.upload_state = "not_started"
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, expected, validate, body=None, auth=False):
        if not path.startswith("/") or path.startswith("//"):
            raise HarnessError("path must be relative to the approved API origin")
        if method != "GET":
            if (not self.write_enabled or not self.isolated_project
                    or self.base_url != "http://127.0.0.1:39003"):
                raise HarnessError("non-GET request requires isolated WRITE_E2E mode")
            verify_isolated_docker(self.isolated_project)
        headers = {"Accept": "application/json" if path.endswith(".json") else "application/xml",
                   "User-Agent": "osm-address-import-osaka-harness/1"}
        if body is not None:
            headers["Content-Type"] = "text/xml; charset=utf-8"
        if auth:
            if not self.token:
                raise HarnessError("dedicated OAuth bearer token required")
            headers["Authorization"] = f"Bearer {self.token}"
        entry = {"method": method, "endpoint": path, "result": "fail", "status": None,
                 "duration_ms": None, "validation": None, "failure": None}
        started = time.monotonic()
        try:
            req = Request(self.base_url + path, data=body, headers=headers, method=method)
            try:
                response = self.opener.open(req, timeout=30)
            except HTTPError as exc:
                response = exc
            with response:
                entry["status"] = response.status
                payload = response.read(MAX_BODY + 1)
                if len(payload) > MAX_BODY:
                    raise HarnessError("response exceeds 2 MB limit")
                if 300 <= response.status < 400:
                    raise HarnessError(f"unexpected HTTP {response.status} redirect")
                if response.status >= 500:
                    raise HarnessError(f"server error HTTP {response.status}")
                if response.status not in expected:
                    raise HarnessError(f"expected HTTP {sorted(expected)}, got {response.status}")
                entry["validation"] = validate(payload, response.headers.get("Content-Type", ""))
                entry["result"] = "pass"
                return payload
        except (URLError, TimeoutError) as exc:
            entry["failure"] = "transport error: " + safe_error(
                exc.reason if isinstance(exc, URLError) else exc, self.token)
            raise HarnessError(entry["failure"]) from exc
        except Exception as exc:
            entry["failure"] = safe_error(exc, self.token)
            raise
        finally:
            entry["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
            self.results.append(entry)

    def smoke(self):
        for path in ("/api/capabilities", "/api/0.6/capabilities"):
            def check_capabilities(body, content_type):
                root = xml_root(body)
                api = root.find("api")
                if root.get("version") != "0.6" or api is None or api.find("version") is None:
                    raise HarnessError("missing OSM API 0.6 capability fields")
                if "xml" not in content_type:
                    raise HarnessError(f"unexpected content type: {content_type}")
                return "OSM XML capabilities, API version 0.6"
            self.request("GET", path, {200}, check_capabilities)

        def check_json(body, content_type):
            if "json" not in content_type:
                raise HarnessError(f"unexpected content type: {content_type}")
            data = json.loads(body)
            if data.get("version") != "0.6" or data.get("api", {}).get("status", {}).get("api") != "online":
                raise HarnessError("JSON capabilities version/status mismatch")
            return "JSON capabilities parsed; API online"
        self.request("GET", "/api/0.6/capabilities.json", {200}, check_json)

        def check_way(body, content_type):
            root = xml_root(body)
            way = root.find("way")
            if way is None or positive_id(way.get("id"), "way ID") != KNOWN_WAY_ID or not way.findall("nd"):
                raise HarnessError("known way ID or node references missing")
            if "xml" not in content_type:
                raise HarnessError(f"unexpected content type: {content_type}")
            return f"way {KNOWN_WAY_ID}, {len(way.findall('nd'))} node references"
        self.request("GET", f"/api/0.6/way/{KNOWN_WAY_ID}", {200}, check_way)

        def check_map(body, content_type):
            root = xml_root(body)
            if "xml" not in content_type or root.find("bounds") is None or not root.findall("node") or not root.findall("way"):
                raise HarnessError("map bounds/nodes/ways or XML content type missing")
            return f"map XML parsed: {len(root.findall('node'))} nodes, {len(root.findall('way'))} ways"
        self.request("GET", f"/api/0.6/map?{urlencode({'bbox': BBOX})}", {200}, check_map)

        self.request("GET", "/api/0.6/way/999999999999999999", {404},
                     lambda body, ct: "missing way rejected")
        self.request("GET", "/api/0.6/way/not-an-id", {400, 404},
                     lambda body, ct: "malformed ID rejected")
        self.request("GET", "/api/0.6/map?bbox=not-a-bbox", {400},
                     lambda body, ct: "malformed bbox rejected")
    def write_e2e(self):
        if (not self.write_enabled or not self.isolated_project
                or os.getenv("OSM_API_WRITE_E2E") != WRITE_CONFIRMATION
                or not self.token or not self.account):
            raise HarnessError("isolated write approval, dedicated account and scoped token required")
        self.request("PUT", "/api/0.6/changeset/create", {401, 403},
                     lambda body, ct: "missing OAuth token rejected", body=b"<osm><changeset/></osm>")
        previous = self.token
        try:
            self.token = "invalid-harness-token"
            self.request("PUT", "/api/0.6/changeset/create", {401, 403},
                         lambda body, ct: "invalid OAuth token rejected", body=b"<osm><changeset/></osm>", auth=True)
        finally:
            self.token = previous
        def check_user(body, content_type):
            root = xml_root(body)
            user = root.find("user")
            if user is None or user.get("display_name") != self.account:
                raise HarnessError("OAuth token does not belong to the dedicated test account")
            return f"authenticated dedicated account {self.account}"
        self.request("GET", "/api/0.6/user/details", {200}, check_user, auth=True)

        marker = "osm-address-import-api-harness-" + uuid.uuid4().hex
        self.created["marker"] = marker
        self.changeset_state = "create_outcome_unknown"
        changeset = ET.Element("osm", version="0.6", generator="osm-address-import-api-harness")
        item = ET.SubElement(changeset, "changeset")
        for k, v in (("comment", "Synthetic Osaka sandbox API regression test"),
                     ("created_by", "osm-address-import-api-harness"), ("test:marker", marker)):
            ET.SubElement(item, "tag", k=k, v=v)
        def check_created(body, content_type):
            self.created["changeset_id"] = positive_id(body.decode().strip(), "created changeset ID")
            self.changeset_state = "open"
            return f"changeset {self.created['changeset_id']} created"
        self.request("PUT", "/api/0.6/changeset/create", {200}, check_created,
                     body=ET.tostring(changeset), auth=True)
        cid = self.created["changeset_id"]
        primary_error = None
        try:
            change = ET.Element("osmChange", version="0.6", generator="osm-address-import-api-harness")
            create = ET.SubElement(change, "create")
            node = ET.SubElement(create, "node", id="-1", version="0", changeset=str(cid),
                                 lat="34.6661000", lon="135.4999000")
            ET.SubElement(node, "tag", k="test:marker", v=marker)
            ET.SubElement(node, "tag", k="fixme", v="Synthetic sandbox test object; disposable data")
            def check_diff(body, content_type):
                root = xml_root(body, "diffResult")
                mapped = root.find("node")
                if mapped is None or mapped.get("old_id") != "-1" or mapped.get("new_version") != "1":
                    raise HarnessError("diffResult did not map synthetic node -1 to version 1")
                self.created["node_id"] = positive_id(mapped.get("new_id"), "new node ID")
                return f"node -1 mapped to {self.created['node_id']} v1"
            self.upload_state = "outcome_unknown"
            self.request("POST", f"/api/0.6/changeset/{cid}/upload", {200}, check_diff,
                         body=ET.tostring(change), auth=True)
            self.upload_state = "diff_confirmed"
            nid = self.created["node_id"]
            def check_node(body, content_type):
                root = xml_root(body)
                saved = root.find("node")
                if saved is None or positive_id(saved.get("id"), "node ID") != nid:
                    raise HarnessError("created node missing on readback")
                tags = {t.get("k"): t.get("v") for t in saved.findall("tag")}
                if (saved.get("version") != "1" or saved.get("changeset") != str(cid)
                        or abs(float(saved.get("lat")) - 34.6661) > 1e-7
                        or abs(float(saved.get("lon")) - 135.4999) > 1e-7
                        or tags.get("test:marker") != marker):
                    raise HarnessError("node version, changeset, coordinates or marker mismatch")
                return f"node {nid} coordinates/tags/version/changeset verified"
            self.request("GET", f"/api/0.6/node/{nid}", {200}, check_node)
            self.upload_state = "readback_verified"
        except Exception as exc:
            primary_error = exc
        self.changeset_state = "close_outcome_unknown"
        try:
            self.request("PUT", f"/api/0.6/changeset/{cid}/close", {200},
                         lambda body, ct: "changeset close accepted", body=b"", auth=True)
            self.changeset_state = "close_accepted"
        except Exception as exc:
            if primary_error:
                raise HarnessError("upload/readback failed: " + safe_error(primary_error, self.token)
                                   + "; close also failed: " + safe_error(exc, self.token)) from primary_error
            raise

        def check_closed(body, content_type):
            root = xml_root(body)
            saved = root.find("changeset")
            if saved is None or positive_id(saved.get("id"), "changeset ID") != cid or saved.get("open") != "false":
                raise HarnessError("closed changeset not persisted")
            tags = {t.get("k"): t.get("v") for t in saved.findall("tag")}
            if tags.get("test:marker") != marker:
                raise HarnessError("changeset marker not persisted")
            return f"changeset {cid} closed with marker persisted"
        self.request("GET", f"/api/0.6/changeset/{cid}", {200}, check_closed)
        self.changeset_state = "verified_closed"
        if primary_error:
            raise primary_error

    def report(self, mode):
        return {"schema_version": 1, "mode": mode, "target": self.base_url,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "summary": {"passed": sum(x["result"] == "pass" for x in self.results),
                            "failed": sum(x["result"] == "fail" for x in self.results)},
                "requests": self.results, "created": self.created,
                "changeset_state": self.changeset_state,
                "upload_state": self.upload_state}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("smoke", "write-e2e"))
    parser.add_argument("--base-url", default="http://127.0.0.1:3003")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--isolated", action="store_true", help="only port 39003 on loopback")
    parser.add_argument("--isolated-project", help="unique disposable Docker Compose project")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args(argv)
    harness = None
    error = None
    try:
        if args.mode == "write-e2e":
            if (not args.allow_write or os.getenv("OSM_API_WRITE_E2E") != WRITE_CONFIRMATION
                    or not args.isolated or not args.isolated_project):
                raise HarnessError("write requires --allow-write, confirmation environment value, --isolated and --isolated-project")
        elif args.allow_write or args.isolated_project:
            raise HarnessError("write flags are invalid in smoke mode")
        harness = Harness(args.base_url, os.getenv("OSM_API_TEST_TOKEN"),
                          os.getenv("OSM_API_TEST_ACCOUNT"), isolated=args.isolated,
                          isolated_project=args.isolated_project,
                          write_enabled=args.mode == "write-e2e")
        if args.mode == "smoke":
            harness.smoke()
        else:
            harness.write_e2e()
    except Exception as exc:
        error = safe_error(exc, harness.token if harness else os.getenv("OSM_API_TEST_TOKEN"))
    report = harness.report(args.mode) if harness else {
        "schema_version": 1, "mode": args.mode, "target": "rejected",
        "summary": {"passed": 0, "failed": 1}, "requests": [],
        "created": {"changeset_id": None, "node_id": None, "marker": None},
        "changeset_state": "not_started", "upload_state": "not_started"}
    if error:
        report["failure"] = error
        if report["summary"]["failed"] == 0:
            report["summary"]["failed"] = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".osm-api-report-", dir=args.report.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, args.report)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"{args.mode}: {report['summary']['passed']} passed, {report['summary']['failed']} failed; report {args.report}")
    if error:
        print(error, file=sys.stderr)
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
