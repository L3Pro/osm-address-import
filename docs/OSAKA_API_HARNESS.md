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
set -a
. /path/to/private/osaka-api-harness.env
set +a
export OSM_API_WRITE_E2E=I_APPROVE_SYNTHETIC_WRITE
PYTHONPATH=src python3 -m osm_address_import.api_harness write-e2e \
  --allow-write --isolated --isolated-project osaka-api-harness-YYYYMMDD-8hex \
  --base-url http://127.0.0.1:39003 \
  --report reports/runs/osaka-api-isolated-write.json
```

Replace `YYYYMMDD-8hex` with the exact project name used for the disposable Compose instance. Port 39003 is reserved for that isolated Rails/database copy. Before every PUT or POST, the harness verifies the project-owned web and DB containers, the loopback port binding, the separate DB and storage volumes, exact network membership, and a `DATABASE_URL` pointing only to `db/openstreetmap` inside the isolated network. Docker access is required; missing or contradictory evidence stops the write. This does not defend against a host administrator replacing Docker resources between inspection and a request. Live WRITE_E2E is disabled in this review and requires a separate code change and authorization. Never run WRITE_E2E in ordinary CI.

WRITE_E2E sends two expected-to-fail authentication requests, verifies the dedicated account, creates one changeset, uploads exactly one new synthetic node with a UUID marker, reads and validates the node, closes the changeset, and reads the closed changeset. If the upload/readback fails after changeset creation, the harness still attempts to close the changeset. Closing a changeset **does not roll back its edits**; the synthetic node and history can remain in the disposable sandbox. The JSON report records the changeset and node IDs for audit. Keep private reports if they are needed for follow-up.

The target guard accepts only literal `127.0.0.1`, so DNS aliases and `localhost` resolution cannot choose a different host. It rejects public OpenStreetMap API hosts, URL credentials, proxy use, redirects, and ports other than 3003 for SMOKE or 39003 for isolated WRITE_E2E. Public-hostname/Cloudflare Access testing is disabled; do not send Access service tokens or cookies to the loopback harness, and do not treat an Access login redirect as a successful API response.

## Repeatable isolated setup and cleanup

Use a new project name matching `osaka-api-harness-YYYYMMDD-8hex`, with a fresh random eight-character hex suffix. Stage a private production-mode OpenStreetMap Rails source copy with precompiled assets at `reports/runs/$PROJECT/app`; its `config/database.yml` must read `ENV.fetch("DATABASE_URL")`. Place a mode-0600 private environment file outside Git containing only synthetic `SECRET_KEY_BASE` and `DATABASE_URL=postgresql://openstreetmap@db/openstreetmap`. Set `OSM_RAILS_IMAGE` to local digest `sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332` and `OSM_DB_IMAGE` to `sha256:7e04bfcf1b20b7ccd558f1977e9f08f72c5683b4b59b021a127cbe370a7ee574`; the guard rejects other image identities. Set `OSM_APP_COPY` and `OSM_PRIVATE_ENV_FILE` to the staged absolute paths. Use the [isolated Compose definition](../deploy/osaka-api-harness/compose.yml), which declares only project-owned volumes and networks and publishes only the web port to `127.0.0.1:39003`.

Before `docker compose up`, run `PYTHONPATH=src python3 -m osm_address_import.docker_isolation fresh "$PROJECT"`; it refuses a name already used by any container, volume or network. Start the disposable DB with `docker compose -p "$PROJECT" -f deploy/osaka-api-harness/compose.yml up -d db`, restore a verified archive **only into that project's DB container**, and check counts. Clear copied OAuth tokens, grants, applications and OpenID requests **only in the disposable DB** before starting the web service. Start web with the same `-p` and Compose file. Run `PYTHONPATH=src python3 -m osm_address_import.docker_isolation verify "$PROJECT"` before provisioning credentials or invoking WRITE_E2E.

Create a synthetic user in the disposable Rails console with a unique display name/email, a generated password, `data_public: true`, `email_valid: true`, `creation_time`, `terms_agreed`, `tou_agreed`, and **`terms_seen: true`**. Do not assign `status` directly: create the pending user, then call `user.activate!`. Create a user-owned `Oauth2Application` with `read_prefs write_api` scopes, then create a `Doorkeeper::AccessToken` for that user and application with the same scopes and a short expiry. Store the **returned `token.token`**, not a separately generated candidate token, in a mode-0600 private file. The 2026-11-12 isolated trial first got 403 because `terms_seen` was false; the API's contributor-terms check requires it even when `terms_agreed` is present. No copied live OAuth token should be used.

Before cleanup, preserve the redacted JSON report and run `PYTHONPATH=src python3 -m osm_address_import.docker_isolation cleanup-check "$PROJECT"`. It refuses any extra project container, volume or network. Then use `docker compose -p "$PROJECT" -f deploy/osaka-api-harness/compose.yml down --volumes`, verify all three project-labeled resource lists are empty, and remove only that project's private staging directory and synthetic credential. Never use a broad Docker prune or an existing Compose project name.

## Reading failures

The process exits nonzero on any failed check. Look at `failure`, then the final entry in `requests` for the endpoint, method, status and duration. A 401/403 during the authenticated account check usually means an absent, expired or incorrectly scoped OAuth token; an account-name mismatch means the token belongs to another user. A 3xx is an unexpected Rails/Access redirect and is never followed. Any 5xx is an immediate server failure. A 200 with a validation failure means the response was parseable or structurally different from the expected OSM XML/JSON. A timeout/transport error is reported separately from HTTP status. `created.marker`, `created.changeset_id`, `created.node_id`, `changeset_state`, and `upload_state` identify an incomplete or ambiguous edit. If creation or upload may have committed before the response was lost, search the disposable database by the UUID marker before retrying. The harness attempts to close a known changeset after an upload/readback failure; closing never rolls back edits.

## Validation on 2026-11-12

The corrected GET-only SMOKE run passed 8/8 on Osaka loopback port 3003. An isolated project restored the archived Osaka database (1,865,425 nodes and 364,226 ways), cleared copied OAuth records only in that copy, and ran production-mode Rails with a synthetic account and scoped token on port 39003. WRITE_E2E passed 8/8, including the expected 401s, node readback and closed changeset readback. Its disposable database had exactly one new node (1,865,426 total), node ID 9 and closed changeset ID 5. The project-labeled containers, volumes, networks, staging copy and synthetic credential were removed; a later read-only listing found no remaining project resources. The live Osaka database still had 1,865,425 nodes and 364,226 ways afterward. The run reports remain ignored under `reports/runs/`. This validation preceded the stricter Docker identity guard; the hardened guard has offline unit coverage and needs a new isolated trial before any future write authorization. No live WRITE_E2E run occurred.
