import pathlib
import sys
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from osm_address_import.api_harness import (
    Harness, HarnessError, NoRedirect, checked_base_url, checked_bbox, checked_way_id, xml_root,
)
from osm_address_import.docker_isolation import IsolationError


class TargetGuardTests(unittest.TestCase):
    def test_smoke_sends_only_get(self):
        harness = Harness("http://127.0.0.1:3003")
        with patch.object(harness, "request") as request:
            harness.smoke()
        self.assertEqual(request.call_count, 8)
        self.assertTrue(all(call.args[0] == "GET" for call in request.call_args_list))

    def test_custom_smoke_fixtures_are_bounded_and_reported(self):
        harness = Harness("http://127.0.0.1:3003", known_way_id="123456",
                          bbox="-46.6400,-23.5600,-46.6390,-23.5590")
        with patch.object(harness, "request") as request:
            harness.smoke()
        endpoints = [call.args[1] for call in request.call_args_list]
        self.assertIn("/api/0.6/way/123456", endpoints)
        self.assertTrue(any("bbox=-46.6400%2C-23.5600%2C-46.6390%2C-23.5590" in x for x in endpoints))
        self.assertEqual(harness.report("smoke")["fixtures"]["known_way_id"], 123456)

    def test_seven_city_fixtures_add_only_bounded_reads(self):
        import json
        fixtures = json.loads((pathlib.Path(__file__).resolve().parents[1] /
                               "config/brazil_api_fixtures.json").read_text())
        harness = Harness("http://127.0.0.1:3003")
        with patch.object(harness, "request") as request:
            harness.smoke()
            harness.brazil_smoke(fixtures)
        self.assertEqual(request.call_count, 36)
        self.assertTrue(all(call.args[0] == "GET" for call in request.call_args_list))
        self.assertEqual(sum("/api/0.6/map?" in call.args[1] for call in request.call_args_list), 9)

    def test_malformed_or_large_fixtures_fail_before_network(self):
        for value in ("0", "-1", "1/2", "99999999999999999999", "1e3"):
            with self.subTest(way=value), self.assertRaises(HarnessError):
                checked_way_id(value)
        for value in ("not-a-bbox", "0,0,1,1", "181,0,182,1", "0,0,0,1",
                      "0,0,0.01,NaN", "0,0,0.01,0.01?x=1", "0,0,0.2,0.01"):
            with self.subTest(bbox=value), self.assertRaises(HarnessError):
                checked_bbox(value)

    def test_approved_loopback_only(self):
        self.assertEqual(checked_base_url("http://127.0.0.1:3003"), "http://127.0.0.1:3003")
        self.assertEqual(checked_base_url("http://127.0.0.1:39003", isolated=True), "http://127.0.0.1:39003")
        for url in (
            "https://api.openstreetmap.org", "http://www.openstreetmap.org:3003",
            "http://127.0.0.1:3002", "http://127.0.0.1:39003",
            "http://127.0.0.1:3003@api.openstreetmap.org",
            "http://127.0.0.1:3003/api", "http://127.0.0.1:3003?x=1",
            "http://user:pass@127.0.0.1:3003", "http://127.0.0.1:3003#x",
            "https://osm-sandbox.mapviewer.ai", "http://localhost:3003.evil.test",
            "http://localhost:39003", "http://[::1]:39003",
            "http://127.0.0.1:3003/", "http://127.0.0.1:\n3003",
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

    def test_smoke_transport_rejects_non_get(self):
        harness = Harness("http://127.0.0.1:3003")
        with self.assertRaisesRegex(HarnessError, "writes and OAuth requests"):
            harness.request("PUT", "/api/0.6/changeset/create", {200}, lambda body, ct: "valid")
        self.assertEqual(harness.results, [])

    def test_authenticated_get_checks_isolation_before_http(self):
        harness = Harness("http://127.0.0.1:39003", token="synthetic-token", isolated=True,
                          isolated_project="osaka-api-harness-20261112-deadbeef", write_enabled=True)
        opener = type("Opener", (), {"open": lambda *args, **kwargs: self.fail("HTTP request was sent")})()
        harness.opener = opener
        with patch("osm_address_import.api_harness.verify_isolated_docker",
                   side_effect=IsolationError("container mismatch")) as verify:
            with self.assertRaisesRegex(IsolationError, "container mismatch"):
                harness.request("GET", "/api/0.6/user/details", {200},
                                lambda body, ct: "valid", auth=True)
        verify.assert_called_once_with("osaka-api-harness-20261112-deadbeef")
        self.assertEqual(harness.results, [])

    def test_oauth_get_cannot_target_live_loopback(self):
        harness = Harness("http://127.0.0.1:3003", token="synthetic-token")
        with self.assertRaisesRegex(HarnessError, "writes and OAuth requests"):
            harness.request("GET", "/api/0.6/user/details", {200},
                            lambda body, ct: "valid", auth=True)

    def test_direct_write_constructor_cannot_target_live_loopback(self):
        with self.assertRaisesRegex(HarnessError, "isolated target"):
            Harness("http://127.0.0.1:3003", isolated_project="osaka-api-harness-20261112-deadbeef",
                    write_enabled=True)

    def test_isolated_write_checks_docker_before_http(self):
        harness = Harness("http://127.0.0.1:39003", isolated=True,
                          isolated_project="osaka-api-harness-20261112-deadbeef",
                          write_enabled=True)

        class Response:
            status = 401
            headers = {"Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b"Unauthorized"

        harness.opener = type("Opener", (), {"open": lambda *args, **kwargs: Response()})()
        with patch("osm_address_import.api_harness.verify_isolated_docker") as verify:
            harness.request("PUT", "/api/0.6/changeset/create", {401},
                            lambda body, ct: "rejected", body=b"<osm/>")
        verify.assert_called_once_with("osaka-api-harness-20261112-deadbeef")

    def test_upload_failure_keeps_marker_id_and_close_state(self):
        harness = Harness("http://127.0.0.1:39003", token="test-token",
                          account="dedicated_test", isolated=True,
                          isolated_project="osaka-api-harness-20261112-deadbeef",
                          write_enabled=True)

        def fake_request(method, path, expected, validate, body=None, auth=False):
            if path == "/api/0.6/user/details":
                validate(b'<osm><user display_name="dedicated_test"/></osm>', "application/xml")
            elif path == "/api/0.6/changeset/create" and expected == {200}:
                validate(b"123", "text/plain")
            elif path.endswith("/upload"):
                raise HarnessError("diffResult response lost")
            elif method == "GET" and path == "/api/0.6/changeset/123":
                xml = ('<osm><changeset id="123" open="false"><tag k="test:marker" v="'
                       + harness.created["marker"] + '"/></changeset></osm>')
                validate(xml.encode(), "application/xml")

        with patch.dict("os.environ", {"OSM_API_WRITE_E2E": "I_APPROVE_SYNTHETIC_WRITE"}), \
             patch.object(harness, "request", side_effect=fake_request) as request:
            with self.assertRaisesRegex(HarnessError, "diffResult response lost"):
                harness.write_e2e()
        self.assertEqual(harness.created["changeset_id"], 123)
        self.assertTrue(harness.created["marker"].startswith("osm-address-import-api-harness-"))
        self.assertEqual(harness.report("write-e2e")["changeset_state"], "verified_closed")
        self.assertEqual(harness.report("write-e2e")["upload_state"], "outcome_unknown")
        self.assertTrue(any(call.args[1].endswith("/close") for call in request.call_args_list))

    def test_report_redacts_token_even_on_unexpected_exception(self):
        secret = "test-secret-that-must-not-appear"
        harness = Harness("http://127.0.0.1:3003", token=secret)

        def fails(*args, **kwargs):
            raise RuntimeError("failure containing " + secret)

        harness.opener = type("Opener", (), {"open": fails})()
        with self.assertRaises(RuntimeError):
            harness.request("GET", "/api/capabilities", {200}, lambda body, ct: "valid")
        self.assertNotIn(secret, str(harness.report("smoke")))

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
