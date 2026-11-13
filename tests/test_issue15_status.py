import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/osaka-rails-production/status.py"
spec = importlib.util.spec_from_file_location("issue15_status", SCRIPT)
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


class StatusTests(unittest.TestCase):
    def test_route_state_and_preserved_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yml"
            backup = config.with_name("config.yml.issue15-backup")
            config.write_bytes(b"ingress:\n  service: http://127.0.0.1:3003\n  service: http_status:404\n")
            backup.write_bytes(b"ingress:\n  service: http://127.0.0.1:3002\n  service: http_status:404\n")
            config.chmod(0o600)
            backup.chmod(0o600)
            result = status.route_status(config)
            self.assertEqual(result["route_state"], "already_switched")
            self.assertEqual(result["rollback_backup"], "present")
            self.assertEqual(backup.read_bytes().count(b"3002"), 1)

    def test_missing_backup_and_ambiguous_origin_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yml"
            config.write_bytes(b"service: http://127.0.0.1:3003\n")
            config.chmod(0o600)
            self.assertEqual(status.route_status(config)["route_state"], "review_required")
            config.write_bytes(b"service: http://127.0.0.1:3002\nservice: http://127.0.0.1:3003\n")
            self.assertEqual(status.route_status(config)["configured_origin"], "unexpected")

    def test_candidate_summary_excludes_credentials(self):
        item = {"State": {"Running": True, "Health": {"Status": "healthy"}},
                "Config": {"Env": ["RAILS_ENV=production", "RACK_ENV=production",
                                   "DATABASE_URL=postgresql://private-password@db/openstreetmap"]},
                "HostConfig": {"PortBindings": {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3003"}]}}}
        response = type("Response", (), {"returncode": 0, "stdout": json.dumps([item])})()
        with patch.object(status, "_run", return_value=response):
            result = status.container_status(status.CANDIDATE)
        self.assertEqual(result["rails_env"], "production")
        self.assertTrue(result["port_3003_loopback"])
        self.assertNotIn("private-password", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
