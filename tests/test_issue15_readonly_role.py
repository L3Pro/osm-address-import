"""Security properties of the Issue #15 preflight credential and grant plan."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLE_SCRIPT = ROOT / "deploy/osaka-rails-production/provision_readonly_role.py"
ENV_SCRIPT = ROOT / "deploy/osaka-rails-production/make_private_env.py"
CUTOVER_ENV_SCRIPT = ROOT / "deploy/osaka-rails-production/make_cutover_env.py"
HBA_SCRIPT = ROOT / "deploy/osaka-rails-production/preflight_hba.py"
spec = importlib.util.spec_from_file_location("readonly_role", ROLE_SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
hba_spec = importlib.util.spec_from_file_location("preflight_hba", HBA_SCRIPT)
hba = importlib.util.module_from_spec(hba_spec)
hba_spec.loader.exec_module(hba)


class ReadonlyRoleTest(unittest.TestCase):
    def test_scram_secret_is_not_plaintext_and_sql_is_bounded(self):
        verifier = module.scram_verifier("synthetic-test-password")
        self.assertTrue(verifier.startswith("SCRAM-SHA-256$4096:"))
        self.assertNotIn("synthetic-test-password", verifier)
        sql = module.sql_for(verifier)
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE", sql)
        self.assertIn("NOREPLICATION NOBYPASSRLS NOINHERIT", sql)
        self.assertIn("REVOKE CREATE ON SCHEMA public FROM PUBLIC", sql)
        self.assertIn("REVOKE TEMPORARY ON DATABASE openstreetmap FROM PUBLIC", sql)
        self.assertIn("public.spatial_ref_sys FROM PUBLIC", sql)
        self.assertIn("GRANT SELECT ON TABLE", sql)
        self.assertIn("CREATE OR REPLACE VIEW issue15_preflight.users", sql)
        self.assertIn("SELECT id, display_name, data_public, creation_time FROM public.users", sql)
        self.assertNotIn("GRANT SELECT ON TABLE public.users", sql)
        self.assertNotIn("oauth_access_tokens", sql)
        self.assertNotIn("GRANT INSERT", sql)

    def test_preflight_credential_is_private_and_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "preflight.env"
            password = Path(directory) / "role.password"
            run = subprocess.run([sys.executable, str(ENV_SCRIPT), str(env), str(password)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual(password.stat().st_mode & 0o777, 0o600)
            self.assertIn("postgresql://osm_rails_preflight_ro:", env.read_text())
            self.assertNotIn("openstreetmap:", env.read_text())
            self.assertNotIn(password.read_text().strip(), run.stdout)
            again = subprocess.run([sys.executable, str(ENV_SCRIPT), str(env), str(password)], capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)

    def test_original_database_requires_explicit_override(self):
        run = subprocess.run(
            [sys.executable, str(ROLE_SCRIPT), "--container", "osm-api-sandbox-db-1",
             "--project", "osm-api-sandbox", "--credential-file", "/nonexistent"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("requires separate approval", run.stderr)

    def test_cutover_credential_has_a_separate_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cutover.env"
            run = subprocess.run(
                [sys.executable, str(CUTOVER_ENV_SCRIPT), str(path)],
                input="synthetic-only-password\n", capture_output=True, text=True,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("postgresql://openstreetmap:synthetic-only-password@db/openstreetmap", path.read_text())
            self.assertNotIn("synthetic-only-password", run.stdout)

    def test_hba_guard_orders_authenticated_role_before_reject(self):
        lines = hba.block("192.0.2.3").splitlines()
        self.assertEqual(lines[1], "host openstreetmap osm_rails_preflight_ro 192.0.2.3/32 scram-sha-256")
        self.assertEqual(lines[2], "host all all 192.0.2.3/32 reject")
        run = subprocess.run(
            [sys.executable, str(HBA_SCRIPT), "install", "--container", "osm-api-sandbox-db-1",
             "--project", "osm-api-sandbox", "--network", "osm-api-sandbox_default",
             "--candidate-ip", "192.0.2.10", "--backup", "/nonexistent"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("requires separate approval", run.stderr)


if __name__ == "__main__":
    unittest.main()
