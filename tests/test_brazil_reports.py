"""Audit artifact invariants for the seven-city append."""

import json
import tempfile
import unittest
from pathlib import Path

from osm_address_import.brazil_reports import (
    COUNT_COLUMNS, CRITICAL_CHECKS, METRICS, ReportError, SCHEMA_VERSION,
    validate_city, write_city, write_summary,
)
from osm_address_import.brazil_finalize_reports import (
    attach_stage_browser, finalize_live_editor, validate_live_attestation,
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
        retry = report(name="city-0", status="BLOCKED")
        retry["duration_seconds"] = 2.5
        with tempfile.TemporaryDirectory() as temporary:
            summary = write_summary(Path(temporary), cities, started_at="now", finished_at="later",
                                    database_size_before=100, database_size_after=200,
                                    baseline_id="base-1", run_id="run-1",
                                    retry_attempts=[retry])
            markdown = (Path(temporary) / "summary.md").read_text()
        self.assertEqual(summary["unique_newly_inserted"]["nodes"], 56)
        self.assertEqual(summary["totals"]["skipped_duplicates"]["nodes"], 14)
        self.assertEqual(summary["total_processing_duration_seconds"], 9.5)
        self.assertEqual(summary["retry_processing_duration_seconds"], 2.5)
        self.assertIn("## Validation status", markdown)
        self.assertIn("Osaka preservation: **PASS**", markdown)

    def test_credentials_are_rejected(self):
        value = report()
        value["warnings"] = ["Authorization: Bearer abc.secret.token"]
        with self.assertRaises(ReportError):
            validate_city(value)

    def test_staged_browser_evidence_does_not_claim_live_success(self):
        slugs = ["manaus", "natal", "canoas", "novo-hamburgo", "itu", "jundiai", "atibaia"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "20261113-7c4e9a21"
            root.mkdir()
            config = root / "cities-config.json"
            config.write_text(json.dumps({"cities": [{"slug": slug} for slug in slugs]}))
            browser = {"status": "PASS", "project": "osaka-api-harness-20261113-7c4e9a21",
                       "cities": {slug: {"status": "PASS", "dom": {
                           "mapRequests": 2, "osmPaths": 5, "idRoot": True}} for slug in slugs}}
            (root / "stage-browser.json").write_text(json.dumps(browser))
            for slug in slugs:
                item = report(name=slug, status="PARTIAL")
                item["validations"]["editor"] = {"status": "NOT_VERIFIED", "evidence": None}
                write_city(root, slug, item)
            attach_stage_browser(root, config)
            for slug in slugs:
                item = json.loads((root / f"{slug}.json").read_text())
                self.assertEqual(item["status"], "PARTIAL")
                self.assertEqual(item["validations"]["editor"]["status"], "NOT_VERIFIED")
                self.assertIn("Live Cloudflare-authenticated browser session: NOT_VERIFIED",
                              item["validations"]["editor"]["evidence"])

    def test_explicit_operator_attestation_closes_visual_checks_without_live_write_claim(self):
        slugs = ["manaus", "natal", "canoas", "novo-hamburgo", "itu", "jundiai", "atibaia"]
        observation = {"status": "PASS", "osm_features": True,
                       "aerial_imagery": True, "editing_controls": True}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "20261113-7c4e9a21"
            root.mkdir()
            config = root / "cities-config.json"
            config.write_text(json.dumps({"cities": [{"slug": slug} for slug in slugs]}))
            (root / "osaka-baseline.json").write_text(json.dumps({
                "baseline_id": "base-1", "counts": {"size": 100}}))
            (root / "stage-browser.json").write_text(json.dumps({
                "status": "PASS", "project": "osaka-api-harness-20261113-7c4e9a21",
                "cities": {slug: {"status": "PASS", "dom": {
                    "mapRequests": 2, "osmPaths": 5}} for slug in slugs}}))
            for slug in slugs:
                item = report(name=slug, status="PARTIAL")
                item["run_id"] = root.name
                item["validations"]["editor"] = {"status": "NOT_VERIFIED", "evidence":
                    "Authenticated isolated Firefox iD: PASS. Live Cloudflare-authenticated browser session: NOT_VERIFIED."}
                write_city(root, slug, item)
            attestation = {"schema_version": "1.0", "run_id": root.name,
                           "evidence_type": "operator-attested live visual inspection",
                           "site": "https://osm-sandbox.mapviewer.ai",
                           "recorded_at": "2026-11-13T19:45:14Z",
                           "areas": {slug: observation.copy() for slug in slugs + ["osaka"]},
                           "live_edits_saved": False, "live_write_verified": False,
                           "screenshots": {"reported_by_operator": True,
                                           "files_supplied_to_agent": False}}
            attestation_path = root / "operator-live-editor-attestation.json"
            attestation_path.write_text(json.dumps(attestation))
            summary = finalize_live_editor(root, config, attestation_path)
            self.assertEqual(summary["status"], "SUCCESS")
            self.assertEqual(summary["osaka_editor_validation"]["status"], "PASS")
            self.assertIs(summary["live_editor_attestation"]["live_write_verified"], False)
            item = json.loads((root / "manaus.json").read_text())
            self.assertEqual(item["status"], "SUCCESS")
            self.assertEqual(item["started_at"], "2026-11-13T00:00:00Z")
            self.assertEqual(item["closeout"]["previous_editor_validation"]["status"], "NOT_VERIFIED")
            self.assertIn("live write NOT_VERIFIED", item["validations"]["editor"]["evidence"])
            self.assertEqual(finalize_live_editor(root, config, attestation_path)["status"], "SUCCESS")
            attestation["live_write_verified"] = True
            with self.assertRaises(ValueError):
                validate_live_attestation(attestation, root.name, set(slugs))

    def test_other_unverified_check_prevents_closeout(self):
        attestation = {"schema_version": "1.0", "run_id": "run-1",
                       "evidence_type": "operator-attested live visual inspection",
                       "site": "https://osm-sandbox.mapviewer.ai",
                       "recorded_at": "2026-11-13T19:45:14Z", "areas": {},
                       "live_edits_saved": False, "live_write_verified": False,
                       "screenshots": {"reported_by_operator": True,
                                       "files_supplied_to_agent": False}}
        with self.assertRaises(ValueError):
            validate_live_attestation(attestation, "run-1", {"manaus"})


if __name__ == "__main__":
    unittest.main()
