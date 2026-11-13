"""Versioned, atomic audit reports for the seven-city API database append.

The importer supplies measured values.  This module never estimates missing data.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

SCHEMA_VERSION = "1.0"
STATUSES = {"SUCCESS", "PARTIAL", "FAILED", "BLOCKED"}
CHECK_STATUSES = {"PASS", "FAIL", "SKIPPED", "NOT_VERIFIED"}
METRICS = (
    "nodes", "ways", "relations", "buildings", "addresses", "highway_ways",
    "other_features",
)
COUNT_COLUMNS = ("source", "existing_before", "newly_inserted", "final_available")
CRITICAL_CHECKS = (
    "source_integrity", "boundary", "duplicate_conflicts", "insertion_integrity",
    "references", "api_nodes", "api_ways", "api_relations", "api_map",
    "feature_data", "editor", "osaka_preservation", "database_health",
    "rails_health",
)


class ReportError(ValueError):
    pass


def _nonnegative(value, label):
    if value is not None and (type(value) is not int or value < 0):
        raise ReportError(f"{label} must be a nonnegative integer or null")


def validate_city(report):
    required = (
        "schema_version", "run_id", "baseline_id", "city", "state", "relation_id",
        "source", "tool", "code_commit", "started_at", "finished_at",
        "duration_seconds", "status", "metrics", "objects", "validations",
        "manifest", "errors", "warnings", "retries", "database",
    )
    missing = [key for key in required if key not in report]
    if missing:
        raise ReportError(f"missing city report fields: {missing}")
    if report["schema_version"] != SCHEMA_VERSION:
        raise ReportError("unsupported report schema version")
    if report["status"] not in STATUSES:
        raise ReportError("invalid import status")
    if not isinstance(report["relation_id"], int) or report["relation_id"] <= 0:
        raise ReportError("invalid boundary relation ID")
    for key in ("provider", "url", "snapshot_at", "downloaded_at", "filename", "sha256"):
        if key not in report["source"]:
            raise ReportError(f"missing source.{key}")
    for key in ("name", "version", "command_ref"):
        if key not in report["tool"]:
            raise ReportError(f"missing tool.{key}")
    if report["source"]["sha256"] is not None and not re.fullmatch(
        r"[0-9a-f]{64}", report["source"]["sha256"]
    ):
        raise ReportError("invalid source SHA-256")
    if report["duration_seconds"] is not None and (
        not isinstance(report["duration_seconds"], (int, float))
        or isinstance(report["duration_seconds"], bool)
        or report["duration_seconds"] < 0
    ):
        raise ReportError("invalid duration")
    for metric in METRICS:
        row = report["metrics"].get(metric)
        if not isinstance(row, dict):
            raise ReportError(f"missing metric {metric}")
        for col in COUNT_COLUMNS:
            if col not in row:
                raise ReportError(f"missing metric {metric}.{col}")
            _nonnegative(row[col], f"{metric}.{col}")
        if all(row[col] is not None for col in COUNT_COLUMNS):
            if row["existing_before"] + row["newly_inserted"] != row["final_available"]:
                raise ReportError(f"inconsistent {metric} before/after counts")
            if row["newly_inserted"] > row["source"]:
                raise ReportError(f"inserted {metric} exceeds source")
    for key in ("source_primary", "source_dependencies", "already_present",
                "skipped_duplicates", "conflicts", "failed", "rolled_back"):
        if key not in report["objects"]:
            raise ReportError(f"missing objects.{key}")
        for typ in ("nodes", "ways", "relations"):
            if typ not in report["objects"][key]:
                raise ReportError(f"missing objects.{key}.{typ}")
            _nonnegative(report["objects"][key][typ], f"objects.{key}.{typ}")
    for key in CRITICAL_CHECKS:
        check = report["validations"].get(key)
        if not isinstance(check, dict) or check.get("status") not in CHECK_STATUSES:
            raise ReportError(f"missing or invalid validation {key}")
        if "evidence" not in check:
            raise ReportError(f"missing validation evidence field for {key}")
        if check["status"] == "PASS" and not check["evidence"]:
            raise ReportError(f"PASS lacks evidence for {key}")
    if report["status"] == "SUCCESS" and any(
        report["validations"][key]["status"] != "PASS" for key in CRITICAL_CHECKS
    ):
        raise ReportError("SUCCESS requires every critical validation to PASS")
    if not isinstance(report["errors"], list) or not isinstance(report["warnings"], list):
        raise ReportError("errors and warnings must be lists")
    serialized = json.dumps(report, ensure_ascii=False)
    if re.search(r"(?i)(bearer\s+[a-z0-9._-]+|password\s*[=:]\s*\S+|client_secret\s*[=:]\s*\S+)", serialized):
        raise ReportError("report appears to contain a credential or token")


def _atomic_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".report-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _render_city(report):
    lines = [f"# {report['city']}, {report['state']} — {report['status']}", "",
             f"Run: `{report['run_id']}` · baseline: `{report['baseline_id']}` · schema: `{SCHEMA_VERSION}`", "",
             f"Boundary relation: `{report['relation_id']}`", "",
             f"Source: {report['source']['provider']} — {report['source']['url']}", "",
             f"Snapshot: `{report['source']['snapshot_at']}` · file: `{report['source']['filename']}`", "",
             f"Downloaded: `{report['source']['downloaded_at']}`", "",
             f"SHA-256: `{report['source']['sha256']}`", "",
             f"Tool: {report['tool']['name']} {report['tool']['version']} · command: `{report['tool']['command_ref']}`", "",
             f"Code: `{report['code_commit']}` · start: `{report['started_at']}` · finish: `{report['finished_at']}` · seconds: `{report['duration_seconds']}`", "",
             "| Metric | Source | Existing before | Newly inserted | Final available |", "|---|---:|---:|---:|---:|"]
    for metric in METRICS:
        row = report["metrics"][metric]
        lines.append("| " + metric + " | " + " | ".join(
            "unknown" if row[key] is None else str(row[key]) for key in COUNT_COLUMNS
        ) + " |")
    lines += ["", "## Validation", "", "| Check | Status | Evidence |", "|---|---|---|"]
    for key in CRITICAL_CHECKS:
        check = report["validations"][key]
        evidence = str(check["evidence"] or "unknown").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {key} | {check['status']} | {evidence} |")
    for title, values in (("Errors", report["errors"]), ("Warnings", report["warnings"])):
        lines += ["", f"## {title}", ""]
        lines += [f"- {value}" for value in values] or ["None recorded."]
    lines += ["", "## Object accounting and database state", "", "```json",
              json.dumps({"objects": report["objects"], "manifest": report["manifest"],
                          "database": report["database"], "retries": report["retries"]},
                         ensure_ascii=False, indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def write_city(run_dir: Path, slug: str, report: dict):
    validate_city(report)
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ReportError("unsafe city slug")
    _atomic_text(run_dir / f"{slug}.json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_text(run_dir / f"{slug}.md", _render_city(report))


def write_summary(run_dir: Path, reports: list[dict], *, started_at, finished_at,
                  database_size_before, database_size_after, baseline_id, run_id,
                  retry_attempts=None, osaka_editor_validation=None,
                  live_editor_attestation=None):
    if len(reports) != 7 or len({item["city"] for item in reports}) != 7:
        raise ReportError("summary requires seven distinct city reports")
    for item in reports:
        validate_city(item)
    retry_attempts = retry_attempts or []
    for item in retry_attempts:
        validate_city(item)
    totals = {key: {typ: sum(item["objects"][key][typ] for item in reports)
                    for typ in ("nodes", "ways", "relations")}
              for key in ("already_present", "skipped_duplicates", "conflicts", "failed", "rolled_back")}
    unique_inserted = {typ: sum(item["metrics"][typ]["newly_inserted"] or 0 for item in reports)
                       for typ in ("nodes", "ways", "relations")}
    osaka_editor_validation = osaka_editor_validation or {
        "status": "NOT_VERIFIED", "evidence": "No operator-attested live Osaka editor check recorded"}
    if (osaka_editor_validation.get("status") not in CHECK_STATUSES
            or (osaka_editor_validation["status"] == "PASS"
                and not osaka_editor_validation.get("evidence"))):
        raise ReportError("invalid Osaka editor validation")
    status = "SUCCESS" if (all(item["status"] == "SUCCESS" for item in reports)
                           and osaka_editor_validation["status"] == "PASS") else (
        "FAILED" if any(item["status"] == "FAILED" for item in reports) else "PARTIAL"
    )
    summary = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "baseline_id": baseline_id,
               "started_at": started_at, "finished_at": finished_at,
               "closeout_at": (live_editor_attestation or {}).get("recorded_at"),
               "status": status,
               "total_processing_duration_seconds": round(sum(
                   item["duration_seconds"] or 0 for item in reports + retry_attempts), 3),
               "retry_processing_duration_seconds": round(sum(
                   item["duration_seconds"] or 0 for item in retry_attempts), 3),
               "retry_attempts": [{"city": item["city"], "status": item["status"],
                                   "started_at": item["started_at"],
                                   "duration_seconds": item["duration_seconds"]}
                                  for item in retry_attempts],
               "osaka_validation": "PASS" if all(
                   item["validations"]["osaka_preservation"]["status"] == "PASS"
                   for item in reports) else "NOT_VERIFIED",
               "osaka_editor_validation": osaka_editor_validation,
               "live_editor_attestation": live_editor_attestation,
               "database_size_before": database_size_before,
               "database_size_after": database_size_after,
               "unique_newly_inserted": unique_inserted, "totals": totals,
               "cities": [{"city": item["city"], "state": item["state"],
                            "status": item["status"], "duration_seconds": item["duration_seconds"],
                            "validations": item["validations"]} for item in reports]}
    _atomic_text(run_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lines = [f"# Brazil seven-city import — {status}", "",
             f"Run: `{run_id}` · baseline: `{baseline_id}`", ""]
    if summary["closeout_at"]:
        lines += [f"Operator visual closeout recorded: `{summary['closeout_at']}`", ""]
    lines += ["| City | State | Status | Seconds |", "|---|---|---|---:|"]
    for item in reports:
        lines.append(f"| {item['city']} | {item['state']} | {item['status']} | {item['duration_seconds']} |")
    lines += ["", f"Osaka preservation: **{summary['osaka_validation']}**", "",
              f"Osaka live editor: **{osaka_editor_validation['status']}** — {osaka_editor_validation['evidence']}", "",
              "## Validation status", "",
              "| City | API reads/map | References | Editor | Database/Rails | Import |",
              "|---|---|---|---|---|---|"]
    for item in reports:
        checks = item["validations"]
        api_keys = ("api_nodes", "api_ways", "api_relations", "api_map")
        api_status = "PASS" if all(checks[key]["status"] == "PASS" for key in api_keys) else "NOT_VERIFIED"
        health_status = "PASS" if all(checks[key]["status"] == "PASS" for key in
                                      ("database_health", "rails_health")) else "NOT_VERIFIED"
        lines.append(f"| {item['city']} | {api_status} | {checks['references']['status']} | "
                     f"{checks['editor']['status']} | {health_status} | {item['status']} |")
    lines += ["", f"Unique inserted: `{unique_inserted}`", "",
              f"Database bytes before: `{database_size_before}`; after: `{database_size_after}`.", "",
              f"Total processing seconds: `{summary['total_processing_duration_seconds']}` (retries: `{summary['retry_processing_duration_seconds']}`).", "",
              "## Accounting", "", "```json", json.dumps(totals, indent=2, sort_keys=True), "```", ""]
    _atomic_text(run_dir / "summary.md", "\n".join(lines))
    return summary
