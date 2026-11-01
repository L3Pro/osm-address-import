import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from osm_address_import.safety import UnsafeTargetError, require_local_sandbox_url


class SandboxTargetTests(unittest.TestCase):
    def test_explicit_loopback(self):
        self.assertEqual(require_local_sandbox_url("http://127.0.0.1:3002"), "http://127.0.0.1:3002")
        self.assertEqual(require_local_sandbox_url("http://localhost:3002/api/0.6"), "http://localhost:3002/api/0.6")

    def test_production_osm_is_rejected(self):
        for url in [
            "https://api.openstreetmap.org/api/0.6",
            "https://www.openstreetmap.org",
            "http://api.openstreetmap.org:80/api/0.6",
            "https://osm-sandbox.mapviewer.ai",
            "http://127.0.0.1",
            "http://localhost:0",
            "http://127.0.0.1:3002?api=write",
            "http://user:password@localhost:3002",
            "http://127.0.0.1:3002/#item",
            "http://127.0.0.1:invalid",
            "ftp://localhost:3002",
            "",
            " http://127.0.0.1:3002",
        ]:
            with self.subTest(url=url), self.assertRaises(UnsafeTargetError):
                require_local_sandbox_url(url)


if __name__ == "__main__":
    unittest.main()
