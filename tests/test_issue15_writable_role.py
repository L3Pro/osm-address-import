"""Static safety checks for the approval-only writable candidate path."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/osaka-rails-production"
sys.path.insert(0, str(DEPLOY))


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


role = load("writable_role", "provision_writable_role.py")
hba = load("cutover_hba", "cutover_hba.py")


class WritableRoleTest(unittest.TestCase):
    def test_grants_exclude_superuser_ddl_and_migrations(self):
        sql = role.sql_for(role.scram_verifier("synthetic-test-password"))
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE", sql)
        self.assertIn("NOREPLICATION NOBYPASSRLS NOINHERIT", sql)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES", sql)
        self.assertIn("REVOKE INSERT, UPDATE, DELETE ON TABLE public.ar_internal_metadata", sql)
        self.assertIn("public.schema_migrations", sql)
        self.assertIn("GRANT USAGE, SELECT ON ALL SEQUENCES", sql)
        self.assertNotIn("GRANT CREATE", sql)
        self.assertNotIn("GRANT UPDATE ON ALL SEQUENCES", sql)
        self.assertIn("PUBLIC CREATE or TEMP privilege remains", sql)

    def test_cutover_hba_and_live_guard(self):
        lines = hba.block("192.0.2.5").splitlines()
        self.assertEqual(lines[1], "host openstreetmap osm_rails_cutover_rw 192.0.2.5/32 scram-sha-256")
        self.assertEqual(lines[2], "host all all 192.0.2.5/32 reject")
        for script, args in (
            ("cutover_hba.py", ["install", "--container", "osm-api-sandbox-db-1", "--project", "osm-api-sandbox", "--network", "osm-api-sandbox_default", "--candidate-ip", "192.0.2.5", "--backup", "/nonexistent"]),
            ("provision_writable_role.py", ["--container", "osm-api-sandbox-db-1", "--project", "osm-api-sandbox", "--credential-file", "/nonexistent"]),
        ):
            run = subprocess.run([sys.executable, str(DEPLOY / script), *args], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("requires separate approval", run.stderr)


if __name__ == "__main__":
    unittest.main()
