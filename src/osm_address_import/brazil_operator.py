"""Guarded city-batch execution and mandatory audit artifact generation.

This command targets one exact local Docker database container. The SQL itself
provides all-or-nothing current/history insertion and refuses content collisions.
Use only after restoring and validating an isolated rehearsal. Live mode requires
an explicit operator flag and a completed rehearsal attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

from osm_address_import.brazil_reports import CRITICAL_CHECKS, METRICS, write_city
from osm_address_import.brazil_sql import render

LIVE_CONTAINER = "osm-api-sandbox-db-1"
OSAKA_SAMPLE_SQL = """SELECT 'node',md5(jsonb_build_object('obj',(SELECT to_jsonb(n) FROM current_nodes n WHERE id=13950191959),'tags',(SELECT jsonb_object_agg(k,v) FROM current_node_tags WHERE node_id=13950191959))::text) UNION ALL SELECT 'way',md5(jsonb_build_object('obj',(SELECT to_jsonb(w) FROM current_ways w WHERE id=658187857),'tags',(SELECT jsonb_object_agg(k,v) FROM current_way_tags WHERE way_id=658187857),'refs',(SELECT jsonb_agg(jsonb_build_array(node_id,sequence_id) ORDER BY sequence_id) FROM current_way_nodes WHERE way_id=658187857))::text) UNION ALL SELECT 'relation',md5(jsonb_build_object('obj',(SELECT to_jsonb(r) FROM current_relations r WHERE id=20979587),'tags',(SELECT jsonb_object_agg(k,v) FROM current_relation_tags WHERE relation_id=20979587),'members',(SELECT jsonb_agg(jsonb_build_array(member_type::text,member_id,member_role,sequence_id) ORDER BY sequence_id) FROM current_relation_members WHERE relation_id=20979587))::text);"""
REFERENCE_MISSING_SQL = """SELECT (SELECT count(*) FROM current_way_nodes m WHERE NOT EXISTS (SELECT 1 FROM current_nodes n WHERE n.id=m.node_id)),(SELECT count(*) FROM current_relation_members m WHERE (m.member_type='Node' AND NOT EXISTS (SELECT 1 FROM current_nodes n WHERE n.id=m.member_id)) OR (m.member_type='Way' AND NOT EXISTS (SELECT 1 FROM current_ways w WHERE w.id=m.member_id)) OR (m.member_type='Relation' AND NOT EXISTS (SELECT 1 FROM current_relations r WHERE r.id=m.member_id)));"""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command(args, *, timeout=1200):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"command {args[0]} failed ({result.returncode}): {result.stderr[-1200:]}")
    return result.stdout


def db_sql(container, sql):
    return command(["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
                    container, "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                    "-U", "openstreetmap", "-d", "openstreetmap", "-c", sql], timeout=60).strip()


def db_baseline(container):
    text = db_sql(container, "SELECT current_database(),pg_database_size(current_database()),"
                  "(SELECT count(*) FROM current_nodes),(SELECT count(*) FROM current_ways),"
                  "(SELECT count(*) FROM current_relations),(SELECT count(*) FROM users),"
                  "(SELECT count(*) FROM oauth_applications),(SELECT count(*) FROM changesets);")
    fields = text.split("|")
    if len(fields) != 8 or fields[0] != "openstreetmap":
        raise RuntimeError("unexpected database identity or baseline result")
    return dict(zip(("database", "size", "nodes", "ways", "relations", "users",
                     "oauth_applications", "changesets"),
                    [fields[0]] + [int(value) for value in fields[1:]]))


def reference_missing(container):
    values = [int(value) for value in db_sql(container, REFERENCE_MISSING_SQL).split("|")]
    if len(values) != 2:
        raise RuntimeError("unexpected reference-integrity result")
    return {"way_nodes": values[0], "relation_members": values[1]}


def check_osaka(container, baseline):
    now = db_baseline(container)
    for key in ("nodes", "ways", "relations"):
        if now[key] < baseline["counts"][key]:
            raise RuntimeError(f"Osaka baseline {key} decreased")
    for key in ("users", "oauth_applications", "changesets"):
        if now[key] != baseline["counts"][key]:
            raise RuntimeError(f"account or changeset baseline drift: {key}")
    actual = dict(line.split("|") for line in db_sql(container, OSAKA_SAMPLE_SQL).splitlines())
    if actual != baseline["hashes"]:
        raise RuntimeError("sampled Osaka node, way, or relation content changed")
    return f"baseline counts retained; 3 sampled content hashes match; users={now['users']}, OAuth apps={now['oauth_applications']}, changesets={now['changesets']}"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def api_xml(base, path):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(Request(base + path, headers={"Accept": "application/xml"}), timeout=30)
    except HTTPError as exc:
        raise RuntimeError(f"API {path} returned HTTP {exc.code}") from exc
    with response:
        if response.status != 200:
            raise RuntimeError(f"API {path} returned HTTP {response.status}")
        body = response.read(10_000_001)
    if len(body) > 10_000_000:
        raise RuntimeError(f"API {path} exceeded 10 MB")
    root = ET.fromstring(body)
    if root.tag != "osm":
        raise RuntimeError(f"API {path} did not return OSM XML")
    return root


def _check(status, evidence):
    return {"status": status, "evidence": evidence}


def blank_report(city, spec, stats, fixture, run_id, baseline_id, code_commit):
    source_counts = stats["source_counts"]
    metrics = {metric: {"source": source_counts.get(metric, 0),
                        "existing_before": None, "newly_inserted": None,
                        "final_available": None} for metric in METRICS}
    unknown_types = {typ: None for typ in ("nodes", "ways", "relations")}
    objects = {key: unknown_types.copy() for key in (
        "source_primary", "source_dependencies", "already_present",
        "skipped_duplicates", "conflicts", "failed", "rolled_back")}
    for typ in ("nodes", "ways", "relations"):
        objects["source_primary"][typ] = stats["role_counts"].get("primary_" + typ, 0)
        objects["source_dependencies"][typ] = stats["role_counts"].get("dependency_" + typ, 0)
    return {"schema_version": "1.0", "run_id": run_id, "baseline_id": baseline_id,
            "city": city["name"], "state": city["state"], "relation_id": city["relation_id"],
            "source": {"provider": spec["source_provider"], "url": spec["source_url"],
                       "snapshot_at": spec["source_snapshot_at"],
                       "downloaded_at": spec["download_completed_at"],
                       "filename": Path(spec["source_url"]).name,
                       "sha256": spec["source_sha256"]},
            "tool": {"name": "PyOsmium/Osmium/PostgreSQL", "version": "3.2.0/1.14.0/14",
                     "command_ref": "python -m osm_address_import.brazil_operator run-city"},
            "code_commit": code_commit, "started_at": None, "finished_at": None,
            "duration_seconds": None, "status": "BLOCKED", "metrics": metrics,
            "objects": objects,
            "validations": {key: _check("NOT_VERIFIED", None) for key in CRITICAL_CHECKS},
            "manifest": {"path": f"{city['slug']}-manifest.jsonl",
                         "sha256": stats["manifest_sha256"],
                         "boundary_geometry": stats["boundary_bounds"],
                         "selection_method": "Osmium smart polygon extract; complete ways; reference-complete relations retained; primary nodes intersect polygon; primary ways reference primary nodes",
                         "excluded_incomplete_relations": stats["excluded_incomplete"].get("relations", 0)},
            "fixture": fixture, "errors": [], "warnings": [], "retries": [],
            "database": {"size_before": None, "size_after": None}}


def run_city(args):
    spec = json.loads(args.config.read_text())
    city = next((entry for entry in spec["cities"] if entry["slug"] == args.city), None)
    if city is None:
        raise ValueError("unknown city slug")
    container = (LIVE_CONTAINER if args.target == "live" else
                 f"osaka-api-harness-{args.run_dir.name}-db-1")
    if args.target == "stage" and not re.fullmatch(
        r"osaka-api-harness-[0-9]{8}-[0-9a-f]{8}-db-1", container
    ):
        raise ValueError("invalid disposable database container name")
    base = "http://127.0.0.1:3003" if args.target == "live" else "http://127.0.0.1:39003"
    stats = json.loads((args.run_dir / f"{args.city}-source-stats.json").read_text())
    fixture = json.loads((args.run_dir / f"{args.city}-fixtures.json").read_text())
    baseline = json.loads((args.run_dir / "osaka-baseline.json").read_text())
    code_commit = command(["git", "rev-parse", "HEAD"]).strip()
    report = blank_report(city, spec, stats, fixture, args.run_dir.name,
                          args.baseline_id, code_commit)
    prior_path = args.run_dir / f"{args.city}.json"
    if prior_path.exists():
        prior = json.loads(prior_path.read_text())
        if any((prior["metrics"][typ]["newly_inserted"] or 0) > 0
               for typ in ("nodes", "ways", "relations")):
            raise RuntimeError("previous city attempt committed objects; inspect it before any manual retry")
        attempt = 1 + len(list(args.run_dir.glob(f"{args.city}-attempt-*.json")))
        shutil.copy2(prior_path, args.run_dir / f"{args.city}-attempt-{attempt}.json")
        shutil.copy2(args.run_dir / f"{args.city}.md",
                     args.run_dir / f"{args.city}-attempt-{attempt}.md")
        report["retries"].append({"previous_status": prior["status"],
                                  "previous_started_at": prior["started_at"],
                                  "previous_errors": prior["errors"],
                                  "archived_as": f"{args.city}-attempt-{attempt}.json"})
    started = time.monotonic()
    attempted_sql = False
    committed = False
    report["started_at"] = utc_now()
    try:
        if baseline.get("baseline_id") != args.baseline_id:
            raise RuntimeError("baseline identifier does not match captured Osaka file")
        if args.target == "live":
            if not args.allow_live:
                raise RuntimeError("live mode requires --allow-live after isolated rehearsal")
            if not args.rehearsal_attestation.is_file():
                raise RuntimeError("live mode requires a completed rehearsal attestation")
            attestation = json.loads(args.rehearsal_attestation.read_text())
            if (attestation.get("status") != "PASS"
                    or attestation.get("run_id") != args.run_dir.name
                    or attestation.get("stage_project") != f"osaka-api-harness-{args.run_dir.name}"
                    or attestation.get("brazil_edit_state") != "PASS"
                    or set(attestation.get("api_cities_pass", [])) != {
                        item["slug"] for item in spec["cities"]
                    }):
                raise RuntimeError("rehearsal attestation is incomplete or mismatched")
        if shutil.disk_usage(args.run_dir).free < 20_000_000_000:
            raise RuntimeError("less than 20 GB free disk")
        mem = Path("/proc/meminfo").read_text()
        available_kb = int(re.search(r"MemAvailable:\s+(\d+) kB", mem).group(1))
        if available_kb < 1_500_000:
            raise RuntimeError("less than 1.5 GB available memory")
        command(["docker", "exec", container, "pg_isready", "-U", "openstreetmap",
                 "-d", "openstreetmap"], timeout=20)
        before = db_baseline(container)
        report["database"]["size_before"] = before["size"]
        check_osaka(container, baseline)
        source_file = args.source_file
        if file_sha256(source_file) != spec["source_sha256"]:
            raise RuntimeError("source SHA-256 mismatch")
        report["validations"]["source_integrity"] = _check(
            "PASS", f"SHA-256 {spec['source_sha256']}; source snapshot {spec['source_snapshot_at']}")
        if stats["boundary_relation_id"] != city["relation_id"] or stats["boundary_ibge_code"] != city["ibge_code"]:
            raise RuntimeError("municipal relation/IBGE mismatch")
        report["validations"]["boundary"] = _check(
            "PASS", f"relation {city['relation_id']}, admin_level=8, IBGE {city['ibge_code']}; polygon bounds {stats['boundary_bounds']}")
        prepared = args.work_dir / f"{args.city}-complete.osm.pbf"
        refs_proc = subprocess.run([args.osmium_bin, "check-refs", "-r", str(prepared)],
                                   capture_output=True, text=True, timeout=120, check=False)
        refs_output = refs_proc.stdout + refs_proc.stderr
        if refs_proc.returncode:
            raise RuntimeError(f"osmium check-refs failed: {refs_output[-1000:]}")
        if len(re.findall(r"missing:\s*0", refs_output)) != 4:
            raise RuntimeError("prepared PBF has unresolved references")
        staged = args.work_dir / f"{args.city}-stage"
        if not staged.is_dir():
            raise RuntimeError("missing city staging CSV directory")
        stage_counts = json.loads((staged / "stage_counts.json").read_text())
        remote_stage = f"/tmp/brazil-stage-{args.city}"
        remote_sql = f"/tmp/brazil-append-{args.city}.sql"
        exists = subprocess.run(["docker", "exec", container, "test", "-e", remote_stage],
                                capture_output=True, check=False)
        if exists.returncode == 0:
            raise RuntimeError("remote staging path already exists; inspect and remove the exact stale path before a manual retry")
        if exists.returncode != 1:
            raise RuntimeError("could not verify remote staging path is absent")
        sql_file = args.run_dir / f"{args.city}-append.sql"
        sql_file.write_text(render(f"/tmp/brazil-stage-{args.city}"))
        command(["docker", "cp", str(staged), f"{container}:{remote_stage}"], timeout=120)
        command(["docker", "cp", str(sql_file), f"{container}:{remote_sql}"], timeout=30)
        attempted_sql = True
        proc = subprocess.run(["docker", "exec", container, "psql", "-X", "-A", "-t", "-q",
                               "-v", "ON_ERROR_STOP=1", "-U", "openstreetmap", "-d", "openstreetmap",
                               "-f", f"/tmp/brazil-append-{args.city}.sql"],
                              capture_output=True, text=True, timeout=1200, check=False)
        (args.run_dir / f"{args.city}-sql.log").write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            report["validations"]["insertion_integrity"] = _check(
                "FAIL", "single city transaction failed and rolled back; inspect private SQL log")
            raise RuntimeError(f"atomic SQL batch rolled back: {proc.stderr[-1000:]}")
        committed = True
        match = re.search(r"IMPORT_AUDIT=(\{.*\})", proc.stdout)
        if not match:
            raise RuntimeError("SQL committed without an import audit row; inspect transaction before retry")
        audit = json.loads(match.group(1))
        report["validations"]["duplicate_conflicts"] = _check("PASS", "all existing IDs matched version, geometry, tags, timestamp, and ordered references; no collision")
        for typ in ("nodes", "ways", "relations"):
            retained = audit[typ]["source_retained"]
            if retained != stage_counts[typ]:
                raise RuntimeError(f"SQL/source count mismatch for {typ}")
            row = report["metrics"][typ]
            row["existing_before"] = audit[typ]["existing_before"]
            row["newly_inserted"] = audit[typ]["newly_inserted"]
            row["final_available"] = retained
            for field in ("already_present", "skipped_duplicates"):
                report["objects"][field][typ] = audit[typ]["existing_before"]
            for field in ("conflicts", "failed", "rolled_back"):
                report["objects"][field][typ] = 0
        for metric in ("buildings", "addresses", "highway_ways", "other_features"):
            item = (audit.get("features") or {}).get(metric, {"existing_before": 0,
                                                               "newly_inserted": 0,
                                                               "source_retained": 0})
            row = report["metrics"][metric]
            row["existing_before"] = item["existing_before"]
            row["newly_inserted"] = item["newly_inserted"]
            row["final_available"] = item["source_retained"]
        after = db_baseline(container)
        report["database"]["size_after"] = after["size"]
        for typ in ("nodes", "ways", "relations"):
            if after[typ] - before[typ] != audit[typ]["newly_inserted"]:
                raise RuntimeError(f"database count delta does not match audit: {typ}")
        report["validations"]["insertion_integrity"] = _check("PASS", f"transaction committed; exact database count deltas match SQL audit; size {before['size']} → {after['size']} bytes")
        missing_after = reference_missing(container)
        if missing_after != baseline["reference_missing"]:
            raise RuntimeError(f"unresolved reference count changed from baseline: {missing_after}")
        report["validations"]["references"] = _check("PASS", f"prepared PBF: zero missing; SQL member checks and way-node FKs passed; database unresolved counts unchanged from inherited Osaka baseline: {missing_after}")
        report["validations"]["database_health"] = _check("PASS", f"pg_isready; database=openstreetmap; counts={after['nodes']}/{after['ways']}/{after['relations']}")
        report["validations"]["osaka_preservation"] = _check("PASS", check_osaka(container, baseline))
        for typ, key in (("node", "node_id"), ("way", "way_id"), ("relation", "relation_id")):
            obj_id = fixture[key]
            root = api_xml(base, f"/api/0.6/{typ}/{obj_id}")
            found = root.find(typ)
            if found is None or found.get("id") != str(obj_id):
                raise RuntimeError(f"API {typ} readback ID mismatch")
            report["validations"][f"api_{typ}s"] = _check("PASS", f"GET /api/0.6/{typ}/{obj_id}: HTTP 200, matching OSM XML")
        root = api_xml(base, f"/api/0.6/map?bbox={fixture['bbox']}")
        if len(root) == 0:
            raise RuntimeError("representative map bbox returned no OSM objects")
        report["validations"]["api_map"] = _check("PASS", f"GET /api/0.6/map?bbox={fixture['bbox']}: HTTP 200, {len(root)} objects")
        if all(report["metrics"][key]["final_available"] > 0 for key in (
            "buildings", "addresses", "highway_ways"
        )):
            report["validations"]["feature_data"] = _check("PASS", "building, address, and highway features present in committed source manifest and SQL audit")
        else:
            raise RuntimeError("building, address, or highway feature count is zero")
        api_xml(base, "/api/0.6/capabilities")
        report["validations"]["rails_health"] = _check("PASS", "Rails API capabilities returned HTTP 200 XML")
        report["validations"]["editor"] = _check("NOT_VERIFIED", "iD browser rendering and login require an authenticated browser session")
        report["status"] = "PARTIAL"
        report["warnings"].append("Editor rendering requires browser verification before SUCCESS")
    except Exception as exc:
        report["errors"].append(str(exc))
        report["status"] = "PARTIAL" if committed else ("FAILED" if attempted_sql else "BLOCKED")
        if committed:
            report["warnings"].append("SQL committed before a later validation failed; inspect audit and database state before retry")
        elif attempted_sql:
            report["warnings"].append("SQL transaction is atomic; zero rows from the failed city batch were committed")
        try:
            report["database"]["size_after"] = db_baseline(container)["size"]
        except Exception:
            pass
    finally:
        report["finished_at"] = utc_now()
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        write_city(args.run_dir, args.city, report)
    return report["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run-city",))
    parser.add_argument("--target", choices=("stage", "live"), required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--osmium-bin", default="osmium")
    parser.add_argument("--baseline-id", required=True)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--rehearsal-attestation", type=Path,
                        default=Path("/nonexistent-rehearsal-attestation"))
    args = parser.parse_args()
    print(run_city(args))


if __name__ == "__main__":
    main()
