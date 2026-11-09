import importlib.util
from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
