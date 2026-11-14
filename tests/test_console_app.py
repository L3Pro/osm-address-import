"""Browser, authorization, and escaped rendering tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from osm_address_import.brazil_reports import write_city
from osm_address_import.console_app import create_app
from test_brazil_reports import report


class ConsoleAppTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "brazil-seven-cities" / "run-1"
        self.run.mkdir(parents=True)
        item = report()
        item["warnings"] = ["<script>alert(1)</script>"]
        write_city(self.run, "canoas", item)
        (self.run / "summary.json").write_text(json.dumps({"schema_version": "1.0", "run_id": "run-1", "status": "SUCCESS",
            "baseline_id": "base-1", "started_at": "start", "finished_at": "finish", "closeout_at": None,
            "total_processing_duration_seconds": 1, "retry_processing_duration_seconds": 0,
            "database_size_before": 100, "database_size_after": 200, "osaka_validation": "PASS",
            "osaka_editor_validation": {"status": "PASS"}, "unique_newly_inserted": {"nodes": 8, "ways": 0, "relations": 0},
            "retry_attempts": [], "cities": []}))
        (self.run / "summary.md").write_text("# safe summary")
        self.client = create_app(self.temporary.name, development_mode=True).test_client()

    def get(self, path, remote="127.0.0.1", **kwargs):
        return self.client.get(path, environ_overrides={"REMOTE_ADDR": remote}, **kwargs)

    def test_default_and_nonlocal_access_fail_closed(self):
        closed = create_app(self.temporary.name).test_client()
        self.assertEqual(closed.get("/").status_code, 403)
        self.assertEqual(self.get("/", "192.0.2.4").status_code, 403)
        self.assertEqual(self.get("/cities/canoas", "192.0.2.4", headers={"Cf-Access-Authenticated-User-Email": "admin@example.com"}).status_code, 403)
        self.assertEqual(self.get("/", headers={"X-Forwarded-For": "192.0.2.4"}).status_code, 403)
        self.assertEqual(self.get("/reports/run-1/canoas.json", "192.0.2.4").status_code, 403)
        with patch.dict("os.environ", {"OSM_CONSOLE_ENV": "production"}):
            with self.assertRaises(ValueError):
                create_app(self.temporary.name, development_mode=True)

    def test_inventory_detail_run_and_safe_rendering(self):
        for path in ("/", "/cities/canoas", "/runs/run-1"):
            response = self.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(b"Canoas", response.data)
            self.assertNotIn(b"<script>alert(1)</script>", response.data)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        detail = self.get("/cities/canoas").data
        for value in (b"Source", b"Existing Before", b"Newly Inserted", b"Final Available", b"10", b"8"):
            self.assertIn(value, detail)

    def test_approved_downloads_and_rejected_paths(self):
        for name in ("canoas.json", "canoas.md", "summary.json", "summary.md"):
            response = self.get(f"/reports/run-1/{name}?download=1")
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
        for path in ("/reports/run-1/.env", "/reports/run-1/private-manifest.json", "/reports/run-1/canoas.pbf",
                     "/reports/run-1/%2e%2e%2f.env", "/reports/%2e%2e/canoas.json"):
            self.assertNotEqual(self.get(path).status_code, 200, path)
        self.assertEqual(self.get("/reports/run-1/canoas.md").mimetype, "text/plain")

    def test_routes_never_execute_shell_or_open_database(self):
        with patch("subprocess.run", side_effect=AssertionError("shell")), patch("os.system", side_effect=AssertionError("shell")), patch("socket.create_connection", side_effect=AssertionError("network")):
            for path in ("/", "/cities/canoas", "/runs/run-1", "/reports/run-1/canoas.json"):
                self.assertEqual(self.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main()
