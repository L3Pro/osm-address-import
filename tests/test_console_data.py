"""Report discovery, accounting, and artifact boundary tests."""

import json
import tempfile
import unittest
from pathlib import Path

from osm_address_import.brazil_reports import write_city
from osm_address_import.console_data import ReportError, ReportRepository
from test_brazil_reports import report


class ConsoleDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "brazil-seven-cities" / "run-1"
        self.run.mkdir(parents=True)
        self.repo = ReportRepository(self.root)

    def save(self, name="canoas", status="SUCCESS", started="2026-11-13T00:00:00Z"):
        item = report(status=status)
        item["started_at"] = started
        item["finished_at"] = started
        write_city(self.run, name, item)
        return item

    def test_valid_city_and_distinct_metric_columns(self):
        self.save()
        area = self.repo.city("canoas")
        self.assertEqual(area["status"], "SUCCESS")
        self.assertEqual(area["loaded"]["report"]["metrics"]["nodes"],
                         {"source": 10, "existing_before": 2, "newly_inserted": 8, "final_available": 10})
        self.assertEqual(self.repo.artifact("run-1", "canoas", "json")[:1], "{")
        self.assertIn("# Canoas", self.repo.artifact("run-1", "canoas", "md"))

    def test_blocked_later_attempt_keeps_loaded_success(self):
        self.save()
        self.save("canoas-attempt-1", "BLOCKED", "2027-02-01T00:00:00Z")
        area = self.repo.city("canoas")
        self.assertEqual(area["loaded"]["report"]["status"], "SUCCESS")
        self.assertEqual(area["latest"]["report"]["status"], "BLOCKED")
        self.assertEqual([item["report"]["status"] for item in area["history"]], ["BLOCKED", "SUCCESS"])
        self.assertEqual(self.repo.inventory()["failed_attempts"], 1)

    def test_osaka_is_baseline_with_unknown_features(self):
        (self.run / "osaka-baseline.json").write_text(json.dumps({"baseline_id": "base-1", "captured_at": "now",
                                                               "counts": {"nodes": 123, "ways": 45, "relations": 6}}))
        area = self.repo.city("osaka")
        self.assertIsNone(area["relation_id"])
        self.assertEqual(area["baseline"]["data"]["counts"]["nodes"], 123)
        self.assertNotIn("buildings", area["baseline"]["data"]["counts"])
        self.assertEqual(area["status"], "NOT RECORDED")

    def test_malformed_and_unsupported_city_reports_do_not_break_inventory(self):
        self.save()
        (self.run / "bad.json").write_text('{"schema_version":"1.0","city":"Bad","metrics":[]}')
        unsupported = report(name="Other")
        unsupported["schema_version"] = "2.0"
        (self.run / "other.json").write_text(json.dumps(unsupported))
        inventory = self.repo.inventory()
        self.assertEqual(inventory["successful_cities"], 1)
        self.assertEqual(len(inventory["warnings"]), 2)

    def test_artifact_allowlist_paths_symlinks_and_secrets(self):
        self.save()
        (self.run / "private-manifest.json").write_text("secret")
        (self.run / ".env").write_text("password=abc")
        for stem in ("../.env", "/etc/passwd", "private-manifest", "canoas-source-stats"):
            with self.assertRaises(ReportError):
                self.repo.artifact("run-1", stem, "json")
        outside = self.root / "outside.md"
        outside.write_text("outside")
        (self.run / "canoas.md").unlink()
        (self.run / "canoas.md").symlink_to(outside)
        with self.assertRaises(ReportError):
            self.repo.artifact("run-1", "canoas", "md")
        (self.run / "canoas.md").unlink()
        (self.run / "canoas.md").write_text("Bearer abc.secret.token")
        with self.assertRaises(ReportError):
            self.repo.artifact("run-1", "canoas", "md")


if __name__ == "__main__":
    unittest.main()
