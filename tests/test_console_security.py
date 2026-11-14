"""Synthetic-key authentication, authorization and curated-publication tests."""

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientConnectionError

from osm_address_import.brazil_reports import write_city
from osm_address_import.console_app import create_app, create_production_app
from osm_address_import.console_auth import CloudflareAccessVerifier, ConsoleAuthorization, RolePolicy
from osm_address_import.console_data import ReportError, ReportRepository
from osm_address_import.console_publish import publish
from test_brazil_reports import report


class ConsoleSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
        cls.jwks = {"keys": [jwk]}
        cls.issuer = "https://test.cloudflareaccess.com"
        cls.audience = "test-console-audience"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / "private" / "run-1"
        self.private.mkdir(parents=True)
        item = report()
        item["validations"]["boundary"]["evidence"] = "<script>alert(1)</script>"
        item["warnings"] = ["<script>operational detail</script>"]
        item["manifest"]["path"] = "private-individual-object-ids.jsonl"
        write_city(self.private, "canoas", item)
        blocked = report(status="BLOCKED")
        blocked["started_at"] = "2026-11-12T00:00:00Z"
        blocked["finished_at"] = "2026-11-12T00:00:01Z"
        blocked["errors"] = ["prepared PBF has unresolved references"]
        write_city(self.private, "canoas-attempt-1", blocked)
        (self.private / "osaka-baseline.json").write_text(json.dumps({
            "baseline_id": "base-1", "captured_at": "2026-11-11T00:00:00Z",
            "container": "private-db", "counts": {"nodes": 10, "ways": 2, "relations": 1},
            "reference_missing": {"way_nodes": 0, "relation_members": 5}}))
        zero = {"nodes": 0, "ways": 0, "relations": 0}
        (self.private / "summary.json").write_text(json.dumps({
            "schema_version": "1.0", "run_id": "run-1", "baseline_id": "base-1", "status": "SUCCESS",
            "started_at": "start", "finished_at": "finish", "closeout_at": None,
            "total_processing_duration_seconds": 2, "retry_processing_duration_seconds": 1,
            "osaka_validation": "PASS", "osaka_editor_validation": {"status": "PASS", "evidence": "private evidence"},
            "database_size_before": 100, "database_size_after": 200,
            "unique_newly_inserted": {"nodes": 8, "ways": 0, "relations": 0},
            "totals": {key: zero for key in ("already_present", "skipped_duplicates", "conflicts", "failed", "rolled_back")},
            "retry_attempts": [{"city": "Canoas", "status": "BLOCKED", "started_at": "old", "duration_seconds": 1}],
            "cities": [{"city": "Canoas", "state": "RS", "status": "SUCCESS", "duration_seconds": 1}],
            "live_editor_attestation": {"live_write_verified": False, "file": "private-attestation.json"},
        }))
        self.published = self.root / "published"
        publish(self.private, self.published, dry_run=False)
        client = jwt.PyJWKClient(self.issuer + "/cdn-cgi/access/certs")
        client.fetch_data = lambda: self.jwks
        self.verifier = CloudflareAccessVerifier(self.issuer, self.audience, jwks_client=client)
        self.auth = ConsoleAuthorization(self.verifier, RolePolicy({"viewer@example.invalid"}, {"admin@example.invalid"}))
        self.app = create_app(self.published, auth=self.auth, published_only=True)
        self.client = self.app.test_client()

    def token(self, email="viewer@example.invalid", *, key=None, algorithm="RS256", **changes):
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": self.audience, "sub": "synthetic-user",
                  "email": email, "iat": now - 5, "exp": now + 300}
        claims.update(changes)
        return jwt.encode(claims, key or self.key, algorithm=algorithm, headers={"kid": "test-key"})

    def get(self, path, token=None, **kwargs):
        headers = {"Cf-Access-Jwt-Assertion": token} if token else {}
        headers.update(kwargs.pop("headers", {}))
        environ = {"REMOTE_ADDR": "127.0.0.1"}
        environ.update(kwargs.pop("environ_overrides", {}))
        return self.client.get(path, headers=headers, environ_overrides=environ, **kwargs)

    def test_valid_signed_jwt_and_explicit_roles(self):
        for email in ("viewer@example.invalid", "admin@example.invalid"):
            token = self.token(email)
            for path in ("/", "/cities/canoas", "/runs/run-1", "/reports/run-1/canoas.json",
                         "/reports/run-1/canoas-attempt-1.md", "/static/console/console.css", "/readyz"):
                response = self.get(path, token)
                self.assertEqual(response.status_code, 200, path)
                response.close()
        self.assertEqual(self.auth.authorize(self.token("admin@example.invalid")), "administrator")
        self.assertEqual(self.auth.authorize(self.token()), "viewer")
        self.assertEqual(self.get("/", self.token("unlisted@example.invalid")).status_code, 403)

    def test_invalid_assertions_fail_closed(self):
        self.assertEqual(self.get("/").status_code, 401)
        self.assertEqual(self.get("/", self.token(key=self.other_key)).status_code, 401)
        self.assertEqual(self.get("/", self.token(aud="other-app")).status_code, 401)
        self.assertEqual(self.get("/", self.token(iss="https://other.cloudflareaccess.com")).status_code, 401)
        self.assertEqual(self.get("/", self.token(exp=int(time.time()) - 60)).status_code, 401)
        self.assertEqual(self.get("/", self.token(nbf=int(time.time()) + 300)).status_code, 401)
        self.assertEqual(self.get("/", self.token(algorithm="HS256", key="synthetic-secret-that-is-long-enough")).status_code, 401)
        self.assertEqual(self.get("/", headers={"Cf-Access-Authenticated-User-Email": "admin@example.invalid"}).status_code, 401)
        self.assertEqual(self.get("/", self.token(), headers={"Cf-Access-Authenticated-User-Email": "admin@example.invalid"}).status_code, 200)
        self.assertEqual(self.get("/", self.token(), environ_overrides={"REMOTE_ADDR": "192.0.2.4"}).status_code, 403)

    def test_unavailable_signing_keys_fail_closed(self):
        def unavailable():
            raise PyJWKClientConnectionError("isolated key source unavailable")
        self.verifier.jwks_client.fetch_data = unavailable
        self.assertEqual(self.get("/", self.token()).status_code, 503)

    def test_roles_only_have_read_only_routes(self):
        for email in ("viewer@example.invalid", "admin@example.invalid"):
            headers = {"Cf-Access-Jwt-Assertion": self.token(email)}
            self.assertEqual(self.client.post("/", headers=headers).status_code, 405)
            self.assertEqual(self.client.post("/imports", headers=headers).status_code, 404)
            self.assertEqual(self.client.get("/imports", headers=headers).status_code, 404)

    def test_publication_strips_operational_content_and_enforces_manifest(self):
        source_digest = hashlib.sha256((self.private / "canoas.json").read_bytes()).hexdigest()
        curated = self.published / "brazil-seven-cities" / "run-1"
        text = (curated / "canoas.json").read_text()
        self.assertNotIn("<script>", text)
        self.assertNotIn("private-individual-object-ids.jsonl", text)
        self.assertNotIn("private-attestation.json", (curated / "summary.json").read_text())
        self.assertIn(source_digest, text)
        self.assertEqual(sorted(path.suffix for path in curated.iterdir()).count(".pbf"), 0)
        repo = ReportRepository(self.published, require_publication=True)
        self.assertEqual(len(repo.inventory()["areas"]), 2)
        self.assertEqual([x["report"]["status"] for x in repo.city("canoas")["history"]], ["SUCCESS", "BLOCKED"])
        self.assertEqual(self.get("/reports/run-1/private-manifest.json", self.token()).status_code, 404)
        self.assertEqual(self.get("/reports/run-1/%2e%2e%2f.env", self.token()).status_code, 404)
        (curated / "canoas.md").unlink()
        (curated / "canoas.md").symlink_to(self.private / "canoas.md")
        self.assertEqual(self.get("/reports/run-1/canoas.md", self.token()).status_code, 404)
        self.assertEqual(hashlib.sha256((self.private / "canoas.json").read_bytes()).hexdigest(), source_digest)

    def test_tampered_published_report_is_unavailable(self):
        curated = self.published / "brazil-seven-cities" / "run-1"
        with (curated / "canoas.json").open("a") as stream:
            stream.write("\n")
        self.assertEqual(self.get("/reports/run-1/canoas.json", self.token()).status_code, 404)
        area = ReportRepository(self.published, require_publication=True).city("canoas")
        self.assertIsNone(area["loaded"])
        self.assertEqual(area["status"], "NOT VERIFIED")
        self.assertEqual(self.get("/readyz", self.token()).status_code, 503)

    def test_authentication_precedes_reports_and_no_execution(self):
        self.assertEqual(self.get("/reports/run-1/canoas.json").status_code, 401)
        self.assertEqual(self.get("/static/console/console.css").status_code, 401)
        self.assertEqual(self.get("/livez").status_code, 204)
        self.assertEqual(self.get("/livez", environ_overrides={"REMOTE_ADDR": "192.0.2.4"}).status_code, 403)
        with patch("subprocess.run", side_effect=AssertionError("shell")), patch("os.system", side_effect=AssertionError("shell")), patch("socket.create_connection", side_effect=AssertionError("db/docker")):
            self.assertEqual(self.get("/", self.token()).status_code, 200)
        self.assertEqual(self.get("/", self.token()).headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(b"<script>", self.get("/cities/canoas", self.token()).data)

    def test_policy_and_production_configuration_fail_closed(self):
        roles = self.root / "roles.json"
        roles.write_text(json.dumps({"viewer": ["Viewer@Example.Invalid"], "administrator": ["admin@example.invalid"]}))
        self.assertEqual(RolePolicy.from_file(roles).role_for("viewer@example.invalid"), "viewer")
        with patch.dict(os.environ, {"OSM_CONSOLE_ENV": "production", "OSM_CONSOLE_DEV_MODE": "1"}):
            with self.assertRaises(ValueError):
                create_production_app()
            with self.assertRaises(ValueError):
                create_app(self.published, development_mode=True)
        self.assertEqual(self.get("/readyz").status_code, 401)
        self.assertEqual(self.get("/readyz", self.token()).json, {"application": "ready", "reports": "available"})


if __name__ == "__main__":
    unittest.main()
