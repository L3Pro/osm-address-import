"""Publish a minimal, reviewed copy of one private OSM audit run.

This is an offline operator command. It never edits the source run or calls an importer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from osm_address_import.brazil_reports import (
    COUNT_COLUMNS, CRITICAL_CHECKS, METRICS, ReportError, _render_city, validate_city,
)
from osm_address_import.console_data import MAX_REPORT_BYTES, SAFE_ID, SAFE_STEM, SECRET, slugify

OBJECT_FIELDS = (
    "source_primary", "source_dependencies", "already_present", "skipped_duplicates",
    "conflicts", "failed", "rolled_back",
)
OSM_TYPES = ("nodes", "ways", "relations")
SOURCE_FIELDS = ("provider", "url", "snapshot_at", "downloaded_at", "filename", "sha256")
SAFE_EVIDENCE = {
    "source_integrity": "Source integrity result recorded in the private audit.",
    "boundary": "Municipal boundary result recorded in the private audit.",
    "duplicate_conflicts": "Duplicate/conflict result recorded in the private audit.",
    "insertion_integrity": "Insertion integrity result recorded in the private audit.",
    "references": "Reference integrity result recorded in the private audit.",
    "api_nodes": "Read-only OSM API node check recorded in the private audit.",
    "api_ways": "Read-only OSM API way check recorded in the private audit.",
    "api_relations": "Read-only OSM API relation check recorded in the private audit.",
    "api_map": "Read-only OSM API map check recorded in the private audit.",
    "feature_data": "Feature data result recorded in the private audit.",
    "editor": "Visual editor result recorded; no live write test is established.",
    "osaka_preservation": "Osaka preservation result recorded in the private audit.",
    "database_health": "Database health result recorded at import time.",
    "rails_health": "Rails health result recorded at import time.",
}


def _read_json(path: Path) -> tuple[dict, str]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_REPORT_BYTES:
        raise ReportError(f"unsafe source audit file: {path.name}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ReportError(f"invalid source audit object: {path.name}")
    return value, hashlib.sha256(raw).hexdigest()


def _city(source: dict, source_digest: str) -> dict:
    validate_city(source)
    result = {key: source[key] for key in (
        "schema_version", "run_id", "baseline_id", "city", "state", "relation_id",
        "code_commit", "started_at", "finished_at", "duration_seconds", "status",
    )}
    result["source"] = {key: source["source"][key] for key in SOURCE_FIELDS}
    result["tool"] = {"name": source["tool"]["name"], "version": source["tool"]["version"],
                      "command_ref": "Withheld from published report"}
    result["metrics"] = {metric: {column: source["metrics"][metric][column] for column in COUNT_COLUMNS}
                         for metric in METRICS}
    result["objects"] = {field: {typ: source["objects"][field][typ] for typ in OSM_TYPES}
                         for field in OBJECT_FIELDS}
    result["validations"] = {key: {"status": source["validations"][key]["status"],
                                   "evidence": f"{SAFE_EVIDENCE[key]} Source report SHA-256: {source_digest}."}
                             for key in CRITICAL_CHECKS}
    # Free-form operational errors, warnings, commands, fixtures and manifest paths stay private.
    result["errors"] = ["An error was recorded in the private audit; consult the operator closeout."] * len(source["errors"])
    result["warnings"] = ["A warning was recorded in the private audit; consult the operator closeout."] * len(source["warnings"])
    result["retries"] = []
    for entry in source["retries"]:
        if not isinstance(entry, dict):
            continue
        archived_as = entry.get("archived_as")
        if archived_as is not None and (not isinstance(archived_as, str) or
                                        not re.fullmatch(r"[a-z0-9-]+-attempt-[1-9][0-9]*\.json", archived_as)):
            raise ReportError("unsafe retry artifact reference")
        result["retries"].append({key: entry.get(key) for key in ("previous_status", "previous_started_at", "archived_as")})
    result["manifest"] = {}  # The private object manifest is never published.
    result["database"] = {key: source["database"].get(key) for key in ("size_before", "size_after")}
    if isinstance(source.get("closeout"), dict):
        result["closeout"] = {key: source["closeout"].get(key) for key in ("recorded_at", "live_write_verified")}
    validate_city(result)
    return result


def _summary(source: dict, run_id: str) -> dict:
    if source.get("schema_version") != "1.0" or source.get("run_id") != run_id:
        raise ReportError("unsupported or inconsistent summary")
    fields = ("schema_version", "run_id", "baseline_id", "started_at", "finished_at", "closeout_at",
              "status", "total_processing_duration_seconds", "retry_processing_duration_seconds",
              "osaka_validation", "database_size_before", "database_size_after")
    result = {key: source[key] for key in fields}
    result["unique_newly_inserted"] = {key: source["unique_newly_inserted"][key] for key in OSM_TYPES}
    result["totals"] = {key: {typ: source["totals"][key][typ] for typ in OSM_TYPES}
                        for key in ("already_present", "skipped_duplicates", "conflicts", "failed", "rolled_back")}
    result["retry_attempts"] = [{key: item.get(key) for key in ("city", "status", "started_at", "duration_seconds")}
                                for item in source["retry_attempts"]]
    result["cities"] = [{key: item.get(key) for key in ("city", "state", "status", "duration_seconds")}
                        for item in source["cities"]]
    result["osaka_editor_validation"] = {"status": source["osaka_editor_validation"]["status"],
                                         "evidence": "Visual result recorded in the private operator audit; no live write test established."}
    result["live_editor_attestation"] = {"live_write_verified": source.get("live_editor_attestation", {}).get("live_write_verified", False)}
    return result


def _summary_markdown(summary: dict) -> str:
    lines = [f"# OSM sandbox import run {summary['run_id']}", "", f"Status: {summary['status']}",
             f"Started: {summary['started_at']}", f"Finished: {summary['finished_at']}",
             f"Visual closeout: {summary['closeout_at'] or 'Not recorded'}", "",
             "| City | State | Status |", "|---|---|---|"]
    lines.extend(f"| {item['city']} | {item['state']} | {item['status']} |" for item in summary["cities"])
    lines += ["", f"Osaka preservation: {summary['osaka_validation']}",
              "Detailed operational evidence remains in the private source audit.", ""]
    return "\n".join(lines)


def prepare(source_run_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return approved file content and SHA-256 provenance; read no large source data."""
    source_run_dir = Path(source_run_dir)
    if not source_run_dir.is_dir() or source_run_dir.is_symlink() or not SAFE_ID.fullmatch(source_run_dir.name):
        raise ReportError("unsafe source run directory")
    run_id = source_run_dir.name
    original_summary, summary_digest = _read_json(source_run_dir / "summary.json")
    summary = _summary(original_summary, run_id)
    baseline, baseline_digest = _read_json(source_run_dir / "osaka-baseline.json")
    if baseline.get("baseline_id") != summary["baseline_id"]:
        raise ReportError("Osaka baseline does not match summary")
    baseline_public = {key: baseline[key] for key in ("baseline_id", "captured_at")}
    baseline_public["counts"] = {key: baseline["counts"][key] for key in OSM_TYPES}
    baseline_public["reference_missing"] = {key: baseline.get("reference_missing", {}).get(key)
                                            for key in ("way_nodes", "relation_members")}
    files = {"summary.json": json.dumps(summary, indent=2, sort_keys=True) + "\n",
             "summary.md": _summary_markdown(summary),
             "osaka-baseline.json": json.dumps(baseline_public, indent=2, sort_keys=True) + "\n"}
    provenance = {"summary.json": summary_digest, "osaka-baseline.json": baseline_digest}
    cities = 0
    for path in sorted(source_run_dir.glob("*.json")):
        if not SAFE_STEM.fullmatch(path.stem) or path.stem in ("summary", "osaka-baseline"):
            continue
        if (path.stem.startswith(("stage-", "osaka-", "operator-", "closeout-", "rehearsal-", "brazil-")) or
                path.stem.endswith(("-fixtures", "-source-stats", "-browser-config", "-attestation"))):
            continue
        source, digest = _read_json(path)
        if "city" not in source:
            continue
        if source.get("run_id") != run_id or slugify(source["city"]) != re.sub(r"-attempt-[1-9][0-9]*$", "", path.stem):
            raise ReportError(f"inconsistent city identity: {path.name}")
        city = _city(source, digest)
        files[path.name] = json.dumps(city, indent=2, sort_keys=True) + "\n"
        # Reuse the existing report renderer for schema-1.0 Markdown; its input is sanitized.
        files[path.stem + ".md"] = _render_city(city)
        provenance[path.name] = digest
        cities += 1
    if not cities:
        raise ReportError("no valid city reports found")
    if any(len(content.encode("utf-8")) > MAX_REPORT_BYTES or SECRET.search(content)
           for content in files.values()):
        raise ReportError("published report is too large or contains credential-like content")
    return files, provenance


def publish(source_run_dir: Path, destination_root: Path, *, dry_run: bool = True) -> dict:
    source_run_dir = Path(source_run_dir)
    if source_run_dir.is_symlink():
        raise ReportError("source run must not be a symlink")
    source_run_dir = source_run_dir.resolve()
    destination_root = Path(destination_root).resolve()
    if destination_root.is_relative_to(source_run_dir) or source_run_dir.is_relative_to(destination_root):
        raise ReportError("publication must be separate from the private source directory")
    files, provenance = prepare(source_run_dir)
    run_id = source_run_dir.name
    manifest = {"schema_version": "1.0", "run_id": run_id, "source_run_id": run_id,
                "source_sha256": provenance,
                "files": {name: hashlib.sha256(content.encode("utf-8")).hexdigest()
                          for name, content in files.items()}}
    if dry_run:
        return manifest
    family = destination_root / "brazil-seven-cities"
    family.mkdir(parents=True, exist_ok=True)
    target = family / run_id
    if target.exists() or target.is_symlink():
        raise FileExistsError("published run already exists; review changes before replacing")
    stage = Path(tempfile.mkdtemp(prefix=".console-stage-", dir=family))
    try:
        for name, content in files.items():
            path = stage / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
        (stage / "publication.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (stage / "publication.json").chmod(0o600)
        os.replace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="write a new curated run after reviewing dry-run output")
    args = parser.parse_args()
    result = publish(args.source_run_dir, args.destination_root, dry_run=not args.publish)
    print(json.dumps({"run_id": result["run_id"], "files": sorted(result["files"]),
                      "source_sha256": result["source_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
