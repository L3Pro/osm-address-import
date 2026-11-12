import pathlib
import sys
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from osm_address_import.api_harness import Harness, HarnessError, NoRedirect, checked_base_url, xml_root


class TargetGuardTests(unittest.TestCase):
    def test_smoke_sends_only_get(self):
        harness = Harness("http://127.0.0.1:3003")
        with patch.object(harness, "request") as request:
            harness.smoke()
        self.assertEqual(request.call_count, 8)
        self.assertTrue(all(call.args[0] == "GET" for call in request.call_args_list))

    def test_approved_loopback_only(self):
        self.assertEqual(checked_base_url("http://127.0.0.1:3003"), "http://127.0.0.1:3003")
        self.assertEqual(checked_base_url("http://localhost:39003", isolated=True), "http://localhost:39003")
        for url in (
            "https://api.openstreetmap.org", "http://www.openstreetmap.org:3003",
            "http://127.0.0.1:3002", "http://127.0.0.1:39003",
            "http://127.0.0.1:3003@api.openstreetmap.org",
            "http://127.0.0.1:3003/api", "http://127.0.0.1:3003?x=1",
            "http://user:pass@127.0.0.1:3003", "http://127.0.0.1:3003#x",
            "https://osm-sandbox.mapviewer.ai", "http://localhost:3003.evil.test",
        ):
            with self.subTest(url=url), self.assertRaises(HarnessError):
                checked_base_url(url)

    def test_parse_rejects_wrong_xml(self):
        with self.assertRaises(HarnessError):
            xml_root(b"<html></html>")
        with self.assertRaises(HarnessError):
            xml_root(b"<osm>")

    def test_write_gate_fails_before_network(self):
        with patch.dict("os.environ", {}, clear=True):
            # The CLI must reject a write even if the endpoint and report are supplied.
            from osm_address_import.api_harness import main
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                report = pathlib.Path(directory) / "report.json"
                self.assertEqual(main(["write-e2e", "--report", str(report)]), 1)
                self.assertIn("write requires", report.read_text())

    def test_server_error_is_reported_with_status_and_duration(self):
        class Response:
            status = 503
            headers = {"Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b"unavailable"

        harness = Harness("http://127.0.0.1:3003")
        harness.opener = type("Opener", (), {"open": lambda *args, **kwargs: Response()})()
        with self.assertRaisesRegex(HarnessError, "server error HTTP 503"):
            harness.request("GET", "/api/capabilities", {200}, lambda body, ct: "valid")
        self.assertEqual(harness.results[0]["status"], 503)
        self.assertIsNotNone(harness.results[0]["duration_ms"])
        self.assertEqual(harness.results[0]["result"], "fail")

    def test_redirect_is_rejected(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.org/login"))
        harness = Harness("http://127.0.0.1:3003")

        def redirect(*args, **kwargs):
            raise HTTPError("http://127.0.0.1:3003/api/capabilities", 302, "Found", {}, BytesIO(b""))

        harness.opener = type("Opener", (), {"open": redirect})()
        with self.assertRaisesRegex(HarnessError, "unexpected HTTP 302 redirect"):
            harness.request("GET", "/api/capabilities", {200}, lambda body, ct: "valid")
        self.assertEqual(harness.results[0]["status"], 302)


if __name__ == "__main__":
    unittest.main()
