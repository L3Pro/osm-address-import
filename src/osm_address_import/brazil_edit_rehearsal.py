"""Authenticated edit of one imported Brazilian node in the disposable Rails copy."""

from __future__ import annotations

import argparse
import json
import os
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from osm_address_import.api_harness import Harness, HarnessError, positive_id, xml_root
from osm_address_import.brazil_reports import _atomic_text


def private_env(path):
    if path.stat().st_mode & 0o077:
        raise HarnessError("credential file must be mode 0600")
    values = {}
    for line in path.read_text().splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


def run(project, credentials, node_id, report_path):
    if os.getenv("BRAZIL_STAGE_EDIT") != "I_APPROVE_DISPOSABLE_STAGE":
        raise HarnessError("disposable stage edit flag is required")
    values = private_env(credentials)
    token = values["OSM_API_TOKEN"]
    account = values["OSM_API_ACCOUNT"]
    h = Harness("http://127.0.0.1:39003", token=token, account=account,
                isolated=True, isolated_project=project, write_enabled=True)
    receipt = {"target": "disposable", "project": project, "node_id": node_id,
               "account": account, "changeset_id": None, "old_version": None,
               "new_version": None, "state": "not_started", "requests": h.results,
               "error": None}
    cid = None
    try:
        def check_user(body, _content_type):
            user = xml_root(body).find("user")
            if user is None or user.get("display_name") != account:
                raise HarnessError("scoped OAuth token belongs to wrong account")
            return "synthetic account authenticated"
        h.request("GET", "/api/0.6/user/details", {200}, check_user, auth=True)
        original = h.request("GET", f"/api/0.6/node/{node_id}", {200},
                             lambda body, _ct: "Brazilian node read", auth=False)
        node = xml_root(original).find("node")
        if node is None or positive_id(node.get("id"), "node ID") != node_id:
            raise HarnessError("Brazilian edit node missing")
        old_version = positive_id(node.get("version"), "node version")
        receipt["old_version"] = old_version
        marker = "brazil-stage-" + uuid.uuid4().hex
        changeset = ET.Element("osm", version="0.6", generator="osm-address-import-brazil-stage")
        item = ET.SubElement(changeset, "changeset")
        for k, v in (("comment", "Disposable Brazilian object editability rehearsal"),
                     ("created_by", "osm-address-import-brazil-stage"),
                     ("test:marker", marker)):
            ET.SubElement(item, "tag", k=k, v=v)
        def check_created(body, _ct):
            nonlocal cid
            cid = positive_id(body.decode().strip(), "changeset ID")
            receipt["changeset_id"] = cid
            receipt["state"] = "changeset_open"
            return "changeset created"
        h.request("PUT", "/api/0.6/changeset/create", {200}, check_created,
                  body=ET.tostring(changeset), auth=True)
        change = ET.Element("osmChange", version="0.6", generator="osm-address-import-brazil-stage")
        modify = ET.SubElement(change, "modify")
        edited = ET.SubElement(modify, "node", id=str(node_id), version=str(old_version),
                               changeset=str(cid), lat=node.get("lat"), lon=node.get("lon"))
        for tag in node.findall("tag"):
            ET.SubElement(edited, "tag", k=tag.get("k"), v=tag.get("v"))
        ET.SubElement(edited, "tag", k="test:marker", v=marker)
        def check_diff(body, _ct):
            mapped = xml_root(body, "diffResult").find("node")
            if (mapped is None or mapped.get("old_id") != str(node_id)
                    or mapped.get("new_id") != str(node_id)
                    or mapped.get("new_version") != str(old_version + 1)):
                raise HarnessError("diffResult did not advance Brazilian node version")
            receipt["state"] = "upload_confirmed"
            return "Brazilian node modification uploaded"
        h.request("POST", f"/api/0.6/changeset/{cid}/upload", {200}, check_diff,
                  body=ET.tostring(change), auth=True)
        saved = h.request("GET", f"/api/0.6/node/{node_id}", {200},
                          lambda body, _ct: "modified node read back")
        new_node = xml_root(saved).find("node")
        tags = {tag.get("k"): tag.get("v") for tag in new_node.findall("tag")}
        if (new_node.get("version") != str(old_version + 1)
                or new_node.get("changeset") != str(cid)
                or tags.get("test:marker") != marker):
            raise HarnessError("Brazilian node edit readback mismatch")
        receipt["new_version"] = old_version + 1
        receipt["state"] = "readback_verified"
        h.request("PUT", f"/api/0.6/changeset/{cid}/close", {200},
                  lambda body, _ct: "changeset closed", body=b"", auth=True)
        closed = h.request("GET", f"/api/0.6/changeset/{cid}", {200},
                           lambda body, _ct: "closed changeset read")
        changeset_item = xml_root(closed).find("changeset")
        if changeset_item is None or changeset_item.get("open") != "false":
            raise HarnessError("changeset did not close")
        receipt["state"] = "PASS"
    except Exception as exc:
        receipt["error"] = str(exc).replace(token, "[REDACTED]")
        receipt["state"] = "FAIL"
        if cid is not None:
            try:
                h.request("PUT", f"/api/0.6/changeset/{cid}/close", {200},
                          lambda body, _ct: "best-effort close", body=b"", auth=True)
            except Exception:
                pass
    _atomic_text(report_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt["state"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--node-id", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.project, args.credentials, args.node_id, args.report))


if __name__ == "__main__":
    main()
