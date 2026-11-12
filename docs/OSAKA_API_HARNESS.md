# Osaka OSM API regression harness

The dependency-free Python harness checks OSM API 0.6 on the Osaka sandbox. It uses the pinned Box A bbox and existing way `658187857` only for GETs. No existing OSM object is edited. Reports are JSON with each request's method, endpoint, status, elapsed milliseconds, parse/validation result, failure, and any created IDs.

## SMOKE: routine read-only run

From the repository root:

```sh
PYTHONPATH=src python3 -m osm_address_import.api_harness smoke \
  --report reports/runs/osaka-api-smoke.json
python3 -m unittest discover -s tests -v
```

SMOKE defaults to `http://127.0.0.1:3003`, sends only GETs, and needs no credentials. It checks both XML capability routes, JSON capabilities, a known way, a small map, a missing way, a malformed ID, and a malformed bbox. A report is written even when a check fails. `reports/runs/` is ignored by Git. Ordinary CI runs unit tests only; a runner with access to the Osaka loopback port can schedule SMOKE separately.

## WRITE_E2E: separately authorized synthetic edit

The write run requires a dedicated sandbox test account and its OAuth bearer token with `read_prefs` and `write_api` scopes. Provision these outside Git and export them from a private local credential store; never place them in command arguments, reports, commits, logs, or a public shell history. The harness checks that `/api/0.6/user/details` returns the configured dedicated account before creating a changeset.

```sh
export OSM_API_TEST_ACCOUNT='your-dedicated-sandbox-test-account'
export OSM_API_TEST_TOKEN='token-from-private-store'
export OSM_API_WRITE_E2E=I_APPROVE_SYNTHETIC_WRITE
PYTHONPATH=src python3 -m osm_address_import.api_harness write-e2e \
  --allow-write --isolated --base-url http://127.0.0.1:39003 \
  --report reports/runs/osaka-api-isolated-write.json
```

Port 39003 is reserved for an isolated disposable Rails/database copy. The command above must be used only after confirming that port is backed by that copy. The harness itself cannot establish database isolation from an HTTP response. For a **separately authorized live Osaka run**, replace `--isolated --base-url http://127.0.0.1:39003` with `--live-sandbox-approved --base-url http://127.0.0.1:3003`. Never put that live command in ordinary CI. The confirmation environment value, `--allow-write`, and exactly one target approval flag are all required. No live WRITE_E2E run is part of developing this harness.

WRITE_E2E sends two expected-to-fail authentication requests, verifies the dedicated account, creates one changeset, uploads exactly one new synthetic node with a UUID marker, reads and validates the node, closes the changeset, and reads the closed changeset. If the upload/readback fails after changeset creation, the harness still attempts to close the changeset. Closing a changeset **does not roll back its edits**; the synthetic node and history can remain in the disposable sandbox. The JSON report records the changeset and node IDs for audit. Keep private reports if they are needed for follow-up.

The target guard rejects public OpenStreetMap API hosts, all non-loopback hosts, URL credentials, proxy use, redirects, and ports other than 3003 for Osaka or 39003 for isolated runs. Public-hostname/Cloudflare Access testing is intentionally disabled until the exact Osaka hostname is reviewed and added to a fixed allowlist. Do not send Access service tokens or cookies to the loopback harness, and do not treat an Access login redirect as a successful API response.

## Reading failures

The process exits nonzero on any failed check. Look at `failure`, then the final entry in `requests` for the endpoint, method, status and duration. A 401/403 during the authenticated account check usually means an absent, expired or incorrectly scoped OAuth token; an account-name mismatch means the token belongs to another user. A 3xx is an unexpected Rails/Access redirect and is never followed. Any 5xx is an immediate server failure. A 200 with a validation failure means the response was parseable or structurally different from the expected OSM XML/JSON. A timeout/transport error is reported separately from HTTP status. `created` IDs may be present even when a later step fails; inspect those IDs before retrying to avoid losing track of synthetic history.

## Validation on 2026-11-12

The corrected GET-only SMOKE run passed 8/8 on Osaka loopback port 3003. An isolated project restored the archived Osaka database (1,865,425 nodes and 364,226 ways), cleared copied OAuth records only in that copy, and ran production-mode Rails with a synthetic account and scoped token on port 39003. WRITE_E2E passed 8/8, including the expected 401s, node readback and closed changeset readback. Its disposable database had exactly one new node (1,865,426 total), node ID 9 and closed changeset ID 5. The project-labeled containers, volumes, networks, staging copy and synthetic credential were removed. The live Osaka database still had 1,865,425 nodes and 364,226 ways afterward. The run reports remain ignored under `reports/runs/`. This validates readiness for review of a **separately authorized** live sandbox write run; no live WRITE_E2E run occurred.
