"""Audit artifact invariants for the seven-city append."""

import json
import tempfile
import unittest
from pathlib import Path

from osm_address_import.brazil_reports import (
    COUNT_COLUMNS, CRITICAL_CHECKS, METRICS, ReportError, SCHEMA_VERSION,
    validate_city, write_city, write_summary,
)


def report(name="Canoas", status="SUCCESS"):
    metrics = {key: {col: 0 for col in COUNT_COLUMNS} for key in METRICS}
    metrics["nodes"] = {"source": 10, "existing_before": 2,
                        "newly_inserted": 8, "final_available": 10}
    zero_types = {typ: 0 for typ in ("nodes", "ways", "relations")}
    objects = {key: zero_types.copy() for key in (
        "source_primary", "source_dependencies", "already_present",
        "skipped_duplicates", "conflicts", "failed", "rolled_back"
    )}
    objects["already_present"]["nodes"] = 2
    objects["skipped_duplicates"]["nodes"] = 2
    return {
        "schema_version": SCHEMA_VERSION, "run_id": "run-1", "baseline_id": "base-1",
        "city": name, "state": "RS", "relation_id": 242574,
        "source": {"provider": "Geofabrik", "url": "https://example.org/source.pbf",
                   "snapshot_at": "2026-11-12T21:23:05Z", "downloaded_at": "2026-11-13T13:56:45Z", "filename": "source.pbf",
                   "sha256": "a" * 64},
        "tool": {"name": "brazil_sql", "version": "1", "command_ref": "cmd-1"},
        "code_commit": "abc123", "started_at": "2026-11-13T00:00:00Z",
        "finished_at": "2026-11-13T00:00:01Z", "duration_seconds": 1.0,
        "status": status, "metrics": metrics, "objects": objects,
        "validations": {key: {"status": "PASS", "evidence": "verified"}
                        for key in CRITICAL_CHECKS},
        "manifest": {"path": "private.jsonl", "sha256": "b" * 64},
        "errors": [], "warnings": [], "retries": [],
        "database": {"size_before": 100, "size_after": 200},
    }


class BrazilReportsTest(unittest.TestCase):
    def test_required_fields_and_nonnegative_counts(self):
        value = report()
        del value["source"]
        with self.assertRaises(ReportError):
            validate_city(value)
        value = report()
        value["metrics"]["nodes"]["source"] = -1
        with self.assertRaises(ReportError):
            validate_city(value)

    def test_count_consistency_and_success_evidence(self):
        value = report()
        value["metrics"]["nodes"]["final_available"] = 9
        with self.assertRaises(ReportError):
            validate_city(value)
        value = report()
        value["validations"]["editor"] = {"status": "NOT_VERIFIED", "evidence": None}
        with self.assertRaises(ReportError):
            validate_city(value)

    def test_failed_report_still_writes_json_and_markdown(self):
        value = report(status="FAILED")
        value["validations"]["api_nodes"] = {"status": "FAIL", "evidence": "HTTP 500"}
        value["errors"] = ["isolated API returned HTTP 500"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_city(root, "canoas", value)
            self.assertEqual(json.loads((root / "canoas.json").read_text())["status"], "FAILED")
            self.assertIn("HTTP 500", (root / "canoas.md").read_text())

    def test_summary_counts_unique_insertions_separately_from_duplicates(self):
        cities = [report(name=f"city-{i}") for i in range(7)]
        with tempfile.TemporaryDirectory() as temporary:
            summary = write_summary(Path(temporary), cities, started_at="now", finished_at="later",
                                    database_size_before=100, database_size_after=200,
                                    baseline_id="base-1", run_id="run-1")
        self.assertEqual(summary["unique_newly_inserted"]["nodes"], 56)
        self.assertEqual(summary["totals"]["skipped_duplicates"]["nodes"], 14)

    def test_credentials_are_rejected(self):
        value = report()
        value["warnings"] = ["Authorization: Bearer abc.secret.token"]
        with self.assertRaises(ReportError):
            validate_city(value)


if __name__ == "__main__":
    unittest.main()
