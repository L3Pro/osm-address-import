import importlib.util
import fcntl
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "deploy/osaka-rails-production/switch_tunnel_route.py"
)
spec = importlib.util.spec_from_file_location("issue15_route", SCRIPT)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


class RouteChangeTest(unittest.TestCase):
    def test_changes_only_the_intended_service_line(self):
        original = (
            b"ingress:\n"
            b"  - hostname: private.example\n"
            b"    service: http://127.0.0.1:3002\n"
            b"  - service: http_status:404\n"
        )
        changed = route.replace_origin(original, route.OLD, route.NEW)
        self.assertEqual(changed.count(route.NEW), 1)
        self.assertEqual(route.replace_origin(changed, route.NEW, route.OLD), original)

    def test_refuses_missing_ambiguous_or_already_switched_route(self):
        for config in (
            b"ingress:\n  - service: http_status:404\n",
            b"service: http://127.0.0.1:3002\nservice: http://127.0.0.1:3002\n",
            b"service: http://127.0.0.1:3002\nservice: http://127.0.0.1:3003\n",
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                route.replace_origin(config, route.OLD, route.NEW)

    def test_refuses_a_non_live_target_without_test_flag(self):
        with patch.object(sys, "argv", ["switch", "candidate", "/tmp/unrelated.yml"]):
            with self.assertRaises(ValueError):
                route.main()

    def test_test_flag_cannot_target_live_config(self):
        with patch.object(sys, "argv", ["switch", "candidate", str(route.LIVE_CONFIG), "--test-config"]):
            with self.assertRaises(ValueError):
                route.main()

    def test_atomic_write_restricts_config_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_bytes(b"old")
            os.chmod(path, 0o644)
            with patch.object(route, "validate"):
                route.write_atomically(path, b"new", path.stat(), b"old")
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_atomic_write_refuses_a_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_bytes(b"old")
            def external_edit(_temporary):
                path.write_bytes(b"unrelated change")
            with patch.object(route, "validate", side_effect=external_edit):
                with self.assertRaises(RuntimeError):
                    route.write_atomically(path, b"new", path.stat(), b"old")
            self.assertEqual(path.read_bytes(), b"unrelated change")

    def test_locked_route_refuses_a_second_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            original = b"ingress:\n  - hostname: example.invalid\n    service: http://127.0.0.1:3002\n"
            path.write_bytes(original)
            descriptor = os.open(str(path) + ".issue15.lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(sys, "argv", ["switch", "candidate", str(path), "--test-config"]):
                    with self.assertRaises(BlockingIOError):
                        route.main()
                self.assertEqual(path.read_bytes(), original)
            finally:
                os.close(descriptor)

    def test_failed_validation_leaves_route_and_no_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            original = b"ingress:\n  - hostname: example.invalid\n    service: http://127.0.0.1:3002\n"
            path.write_bytes(original)
            with patch.object(sys, "argv", ["switch", "candidate", str(path), "--test-config"]):
                with patch.object(route, "validate", side_effect=[None, RuntimeError("rejected")]):
                    with self.assertRaises(RuntimeError):
                        route.main()
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(Path(str(path) + ".issue15-backup").exists())


if __name__ == "__main__":
    unittest.main()
