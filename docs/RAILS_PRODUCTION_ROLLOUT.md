# Issue #15: reviewed Osaka production-mode Rails candidate

**Preparation on 2026-11-08 CST / 2026-11-09 UTC. No cutover was performed.** This change supplies a separate candidate service and a reversible tunnel-origin switch. It does not change the running `osm-api-sandbox` Compose project, its source, database, storage, or tunnel configuration during preparation. CGImap and OSM API writes are outside this change.

## Evidence and configuration choice

The first read-only Osaka timings are in [PR #16](https://github.com/L3Pro/osm-address-import/pull/16), intended to remain at `docs/RAILS_PERFORMANCE_BASELINE.md`. The isolated mode comparison is in [PR #18](https://github.com/L3Pro/osm-address-import/pull/18), intended to remain at `docs/RAILS_MODE_COMPARISON.md`. Both measurements are retained; this rollout change adds a separate procedure and does not edit either report. Merge **#16, then #18, then #19**; G1 [PR #17](https://github.com/L3Pro/osm-address-import/pull/17) is independent.

The existing web container uses upstream website revision `e87ef1370fc7a9675a6d7df171e15ebcd36b7513`, the local Rails image digest `sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332`, a bind-mounted checkout, `bundle exec rails s`, and loopback port 3002. Its environment defaults to development. The existing database is a separate `db` service on `osm-api-sandbox_default`, and uploaded files use `osm-api-sandbox_web-storage`. The candidate keeps the same source revision, image, database, private application settings, API routes and storage, but uses a clean staged source copy, `RAILS_ENV=production`, `RACK_ENV=production`, precompiled assets, a generated candidate `SECRET_KEY_BASE`, and loopback port 3003. It has a 1 GiB/1 CPU cap. The old web stays on port 3002 until an approved tunnel switch. The base `compose.rollout.yml` mounts the existing storage read-only and requests read-only PostgreSQL transactions. This does not revoke the existing DB role's write privileges; starting a candidate connected to the original DB requires separate approval. The `compose.cutover.yml` override enables database and storage writes only inside an approved cutover window. Neither file recreates the old web or DB.

The upstream production configuration keeps `force_ssl` and `assume_ssl` enabled. The intended tunnel route should terminate HTTPS upstream; its live remote behavior must be verified before cutover. The inspected tunnel config has exactly one origin line for `http://127.0.0.1:3002`; the reviewed route helper changes only that line to 3003 after validating the whole ingress file. The original private `settings.local.yml` is mounted read-only into the candidate, preserving OAuth client IDs and other site settings without committing them. `DATABASE_URL` and `SECRET_KEY_BASE` stay in a mode-600 ignored file. The upstream `config/database.yml` has no production entry, so the staged copy supplies one using `DATABASE_URL`. The original source/config files are never patched.

The website uses an in-process memory session store when memcache is not configured. A new process cannot inherit the old process's session state; users should expect to log in again after cutover, and a rollback may also require re-login after the browser receives a candidate cookie. The new signing key changes cookie validity. User account data and OAuth applications remain in the same database. This is an explicit operational tradeoff, not a tested session migration. The production app uses its upstream Puma server via `rails s`; a separate process-manager review remains appropriate before relying on higher concurrency.

## Isolated candidate result

The candidate was tested on project `issue15-production-candidate-20261108` with a separate 1.5 GiB/1.5 CPU PostgreSQL container, an internal isolated-gateway network, no published ports, and a copied historical archive with a distinct inode. The archive checksum matched the original. Restore counts were **1,865,417 nodes; 364,224 ways; 4,350 relations; 1,146,857 way tags**. Restored OAuth tables were purged only in the disposable DB (2 tokens, 0 grants, 2 applications became 0/0/0); one synthetic user and OAuth application were then created there for login testing. No OSM API write was sent. Disposable settings used the same production SSL settings and a synthetic site identity; `status: online` enabled the editor page. Missing third-party tile/API keys were expected and did not block the test.

The first DB startup exposed a custom-image requirement for the internal database name `openstreetmap`; the disposable definition was corrected and its empty failed volume removed. Asset compilation required the running container's Node dependency tree, `config/example.storage.yml` copied as `config/storage.yml`, then `bundle exec i18n export` before `rails assets:precompile`. These steps are now in the staged preparation and build scripts. `/up` is not a route in this revision, so both Compose health checks use the read-only capabilities JSON route.

| Disposable production check | Result |
| --- | --- |
| Capabilities JSON and HTML root | HTTP 200; candidate healthy |
| Synthetic login with CSRF and session cookie | HTTP 302 to requested editor page; cookie `Secure` and `HttpOnly` |
| Authenticated `/edit?editor=id` and `/id` | HTTP 200; editor iframe, iD asset map, synthetic token marker present |
| iD asset map and representative files | 221 mapped entries and 29 HTML asset URLs existed; JS, CSS, JSON and PNG GETs all HTTP 200 with correct media types |
| User details API | HTTP 401 without token; HTTP 200 with synthetic iD bearer token |
| Box A map, warm sample | 336,634 bytes; 1.445 s then 0.805 s after earlier first request; SHA-256 `5825621a1c170becd85cdbe6db13498bc7d3d3f31400e44c6e9581ccb9155739`, matching the existing Osaka and prior disposable modes |
| Box B map, warm sample | 72,582 bytes; 0.883 s then 0.188 s |
| Candidate resources | 305.5 MiB post-request Rails memory; within 1 GiB cap |
| Browser shell | One isolated headless Firefox root-page screenshot showed the site layout, controls and styling; third-party map tiles could not load across the isolated network |
| Route helper on private config copy | Candidate switch and rollback both validated; restored file SHA-256 matched its original |

The preceding mode-comparison PR has the comparable 1.099 s development and 0.732 s production warm Box A means. This round is a functional candidate smoke test, not a controlled new performance trial. Browser login, interactive iD map editing, remote tile loading, full OAuth authorization, mail, background jobs, uploads, and a sustained load test were **not** exercised. An API save was deliberately not attempted. The already-running Osaka service was not restarted or reconfigured. Its counts before and after were identical (1,865,425 nodes; 364,226 ways; 4,350 relations; 1,146,865 way tags), its loopback capabilities GET returned 200, and the original archive checksum stayed unchanged. After ownership checks, the disposable project's two containers, one volume, one network, staging copy, logs, and synthetic credentials were removed; label-filtered Docker queries returned no project resources.

## Approved rollout procedure (not executed)

**Current status: NO-GO for side-by-side startup and cutover.** The 2026-11-10 authorized preflight stopped before candidate startup because the existing candidate database identity has write privileges; `PGOPTIONS` is only a session default. No candidate or benchmark was run against the original Osaka database. A separately approved, database-restricted credential and a reviewed configuration update are required before these launch commands can be used. The [readiness audit](RAILS_DEPLOYMENT_READINESS.md#2026-11-10-preflight-stop-condition) records the stop condition. The isolated iD test remains a technical GO for the existing upstream CDN path when the browser can reach jsDelivr; the intended Cloudflare Access browser path is still unverified.

The 2026-11-09 fresh-backup audit restored successfully to an isolated database; see [deployment readiness](RAILS_DEPLOYMENT_READINESS.md). Repeat the bounded backup and independent restore if the snapshot is stale at cutover. First confirm host headroom, the active tunnel service manager, and an agreed maintenance/rollback window. **The following commands are draft and must not be run with the current database identity.** The current `make_private_env.py` prompts for that identity's password; revise it to accept only a separately approved, database-restricted candidate credential before any launch. Keep the entire stage private. Do not run any migration, `db:prepare`, seed, or asset task against the existing checkout.

```sh
set -euo pipefail
umask 077
export STAGE="$PWD/reports/runs/issue15-osaka-rollout-$(date +%Y%m%d%H%M%S)"
export SOURCE=/opt/osm-sandbox/osm-api-sandbox/openstreetmap-website
export SETTINGS="$SOURCE/config/settings.local.yml"
export RAILS_IMAGE=sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332
export COMPOSE=deploy/osaka-rails-production/compose.rollout.yml
export CUTOVER_COMPOSE=deploy/osaka-rails-production/compose.cutover.yml
export RESTORE_COMPOSE=deploy/osaka-rails-production/compose.restore.yml
export OSM_DB_IMAGE=sha256:7e04bfcf1b20b7ccd558f1977e9f08f72c5683b4b59b021a127cbe370a7ee574
export PROJECT=issue15-osaka-prod
export RESTORE_PROJECT=issue15-precutover-restore-$(date +%Y%m%d%H%M%S)

docker ps --filter label=com.docker.compose.project=osm-api-sandbox --format '{{.Names}} {{.Status}}'
docker network inspect osm-api-sandbox_default --format '{{index .Labels "com.docker.compose.project"}}'
docker volume inspect osm-api-sandbox_web-storage --format '{{index .Labels "com.docker.compose.project"}}'
sha256sum /opt/osm-sandbox/osm-api-sandbox/backups/imported-osaka-core-test-20260619-212052.dump
test "$(systemctl is-active cloudflared)" = active
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate

bash deploy/osaka-rails-production/prepare_candidate.sh "$SOURCE" "$STAGE" osm-api-sandbox-web-1
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc 'SELECT (SELECT count(*) FROM current_nodes),(SELECT count(*) FROM current_ways),(SELECT count(*) FROM current_relations),(SELECT count(*) FROM current_way_tags)' > "$STAGE/osaka-counts-before.txt"
timeout 600 docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 pg_dump -U openstreetmap -d openstreetmap -Fc --no-owner --no-acl --lock-wait-timeout=5s > "$STAGE/current-precutover.dump"
docker exec -i osm-api-sandbox-db-1 pg_restore --list < "$STAGE/current-precutover.dump" > "$STAGE/current-precutover.list"
test -s "$STAGE/current-precutover.list"
sha256sum "$STAGE/current-precutover.dump" > "$STAGE/current-precutover.sha256"
test -z "$(docker ps -aq --filter label=com.docker.compose.project=$RESTORE_PROJECT)"
docker compose -p "$RESTORE_PROJECT" -f "$RESTORE_COMPOSE" up -d --wait db
timeout 600 docker compose -p "$RESTORE_PROJECT" -f "$RESTORE_COMPOSE" exec -T db pg_restore -U postgres --no-owner --no-acl --exit-on-error -d openstreetmap < "$STAGE/current-precutover.dump"
docker compose -p "$RESTORE_PROJECT" -f "$RESTORE_COMPOSE" exec -T db psql -X -U postgres -d openstreetmap -Atc 'SELECT (SELECT count(*) FROM current_nodes),(SELECT count(*) FROM current_ways),(SELECT count(*) FROM current_relations),(SELECT count(*) FROM current_way_tags)' > "$STAGE/restore-counts.txt"
cmp "$STAGE/osaka-counts-before.txt" "$STAGE/restore-counts.txt"
docker compose -p "$RESTORE_PROJECT" -f "$RESTORE_COMPOSE" down --volumes
python3 deploy/osaka-rails-production/make_private_env.py "$STAGE/private.env"
bash deploy/osaka-rails-production/build_assets.sh "$STAGE" "$RAILS_IMAGE" "$STAGE/private.env" "$SETTINGS" > "$STAGE/assets-build.log" 2>&1
printf 'OSM_RAILS_IMAGE=%s\nOSM_APP_COPY=%s\nOSM_PRIVATE_ENV_FILE=%s\nOSM_SETTINGS_LOCAL_FILE=%s\n' "$RAILS_IMAGE" "$STAGE/app" "$STAGE/private.env" "$SETTINGS" > "$STAGE/compose.env"
chmod 600 "$STAGE/compose.env"
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --quiet
```

If restore fails, inspect ownership and remove only the disposable restore project; do not continue. **Do not run the following side-by-side launch with the current database credential.** It has database-enforced write ability; `PGOPTIONS` is **not** a privilege boundary. This command block is retained as a draft procedure and must be revised and reviewed after separately approved provisioning of a restricted database identity. The existing preflight authorization does not approve that database change. The route must remain on 3002 until a later cutover approval.

```sh
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin)["services"]["candidate"]; v=[v for v in c["volumes"] if v["target"]=="/app/storage"]; assert len(v)==1 and v[0]["read_only"] and c["environment"]["PGOPTIONS"]=="-c default_transaction_read_only=on"'
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" up -d candidate
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" ps
```

Before routing, use only bounded unauthenticated GETs on loopback port 3003. Check that the old service remains healthy at 3002, verify the candidate's capabilities and both map boxes, compare byte counts and streamed hashes, and check post-request memory/CPU. Take new aggregate DB counts and compare to the preflight values using a read-only PostgreSQL session. Do not use a real user login on the candidate before approved cutover, because login and OAuth token creation can write account metadata to the existing database. Review the tunnel origin change and stage ownership before the next step.

```sh
curl --silent --show-error --noproxy '*' --max-time 10 --max-redirs 0 --output /dev/null --write-out 'capabilities=%{http_code}\n' http://127.0.0.1:3003/api/0.6/capabilities.json
curl --silent --show-error --noproxy '*' --max-time 30 --max-redirs 0 --output /dev/null --write-out 'boxA=%{http_code} bytes=%{size_download} ttfb=%{time_starttransfer} total=%{time_total}\n' 'http://127.0.0.1:3003/api/0.6/map.json?bbox=135.4988,34.6652,135.5010,34.6670'
curl --silent --show-error --noproxy '*' --max-time 30 --max-redirs 0 'http://127.0.0.1:3003/api/0.6/map.json?bbox=135.4988,34.6652,135.5010,34.6670' | sha256sum
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' issue15-osaka-prod-candidate-1
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc 'SELECT (SELECT count(*) FROM current_nodes),(SELECT count(*) FROM current_ways),(SELECT count(*) FROM current_relations),(SELECT count(*) FROM current_way_tags)' > "$STAGE/osaka-counts-after.txt"
cmp "$STAGE/osaka-counts-before.txt" "$STAGE/osaka-counts-after.txt"
```

**Cutover approval is a separate boundary from PR review and read-only side-by-side startup.** It authorizes recreating the candidate with write-capable access to the existing Osaka DB and storage, then changing the one tunnel origin and restarting `cloudflared`. First render the two-file Compose configuration and verify that the storage mount is writable and `PGOPTIONS` is cleared. The helper validates a private temporary file, locks cooperating invocations, rejects a concurrent content change, creates a mode-600 backup, and replaces only the expected origin line with mode-600 permissions. It does **not** restart the tunnel. The unit at `/etc/systemd/system/cloudflared.service` was loaded, active, and enabled during the readiness audit; check it again immediately before use. If its restart fails, restore the previous route and retry the old tunnel before leaving the maintenance window.

```sh
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin)["services"]["candidate"]; v=[v for v in c["volumes"] if v["target"]=="/app/storage"]; assert len(v)==1 and not v[0].get("read_only",False) and c["environment"]["PGOPTIONS"]==""'
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" up -d --no-deps --force-recreate candidate
test "$(docker inspect issue15-osaka-prod-candidate-1 --format '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.RW}}{{end}}{{end}}')" = true
docker exec issue15-osaka-prod-candidate-1 sh -c 'test -z "$PGOPTIONS"'
curl --silent --show-error --noproxy '*' --max-time 10 --max-redirs 0 --output /dev/null --write-out 'capabilities=%{http_code}\n' http://127.0.0.1:3003/api/0.6/capabilities.json
test "$(systemctl is-active cloudflared)" = active
sudo python3 deploy/osaka-rails-production/switch_tunnel_route.py candidate /etc/cloudflared/config.yml
if ! sudo systemctl restart cloudflared || ! sudo systemctl is-active --quiet cloudflared; then
  sudo python3 deploy/osaka-rails-production/switch_tunnel_route.py rollback /etc/cloudflared/config.yml
  sudo systemctl restart cloudflared
  exit 1
fi
sudo systemctl is-active cloudflared
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

Use the normal HTTPS sandbox hostname to verify root page, login with a dedicated test account, secure session cookie, `/edit?editor=id`, iD frame, browser console/network asset requests, map data, OAuth-backed user details, and existing read-only API endpoints. Require the actual iD interface, map, zoom, feature selection and tagging controls to render; confirm successful tagging-schema and name-suggestion requests to `cdn.jsdelivr.net` rather than relying on iframe HTML alone. Verify public HTTPS, `Host`/forwarded scheme and CSP behavior. Do not save an OSM edit as part of this rollout. Monitor 5xx, p50/p95 Box A timings, Rails/DB CPU, RSS, and old/new container health for at least ten minutes. Keep the old web running on 3002 during the rollback window.

**Acceptance:** all critical HTML/JS/CSS/iD assets and API checks pass with no unexpected redirects or 404/5xx; Box A digest and 336,634-byte response match; five sequential warm Box A GETs have median at or below 0.85 s and at least 20% lower than five same-condition old-service GETs; candidate stays below its 1 GiB limit without restarts; DB aggregate counts do not change during read-only smoke checks; the tunnel reaches the intended port; dedicated test login and OAuth read succeed after cutover. Treat a 5xx, broken editor, asset miss, insecure cookie/HTTP route, count drift before login, or exceeded latency/memory limit as a rollback trigger. These thresholds are proposed for review, not demonstrated at sustained load.

## Fast rollback

If a trigger fires, restore the exact pre-cutover ingress file and restart the tunnel; the helper refuses rollback if someone has edited that file for another reason. Confirm the old 3002 service through the HTTPS hostname, then stop only the candidate project. Its external storage volume and network are never removed by this Compose file. Keep the private stage until review of logs and the rollback window ends; delete it only after checking ownership and retention requirements.

```sh
sudo python3 deploy/osaka-rails-production/switch_tunnel_route.py rollback /etc/cloudflared/config.yml
sudo systemctl restart cloudflared
sudo systemctl is-active cloudflared
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" down
```

No database migration, schema change, OSM object write, or change to the old web is part of this proposal, so tunnel rollback returns traffic to the old service. Normal user account/session writes after an approved cutover are not undone by a route rollback. Before executing any rollout, confirm the latest source/image still matches the pinned revisions and that the private backup and tunnel manager can be operated on the real host.
