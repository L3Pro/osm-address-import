# Issue #15: reviewed Osaka production-mode Rails candidate

**Preparation on 2026-11-08 CST / 2026-11-09 UTC. No cutover was performed.** This change supplies a separate candidate service and a reversible tunnel-origin switch. It does not change the running `osm-api-sandbox` Compose project, its source, database, storage, or tunnel configuration during preparation. CGImap and OSM API writes are outside this change.

## Evidence and configuration choice

The first read-only Osaka timings are in [PR #16](https://github.com/L3Pro/osm-address-import/pull/16), intended to remain at `docs/RAILS_PERFORMANCE_BASELINE.md`. The isolated mode comparison is in [PR #18](https://github.com/L3Pro/osm-address-import/pull/18), intended to remain at `docs/RAILS_MODE_COMPARISON.md`. Both measurements are retained; this rollout change adds a separate procedure and does not edit either report. Merge **#16, then #18, then #19**; G1 [PR #17](https://github.com/L3Pro/osm-address-import/pull/17) is independent.

The existing web container uses upstream website revision `e87ef1370fc7a9675a6d7df171e15ebcd36b7513`, the local Rails image digest `sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332`, a bind-mounted checkout, `bundle exec rails s`, and loopback port 3002. Its environment defaults to development. The existing database is a separate `db` service on `osm-api-sandbox_default`, and uploaded files use `osm-api-sandbox_web-storage`. The candidate keeps the same source revision, image, database, private application settings, API routes and storage, but uses a clean staged source copy, `RAILS_ENV=production`, `RACK_ENV=production`, precompiled assets, a generated candidate `SECRET_KEY_BASE`, and loopback port 3003. It has a 1 GiB/1 CPU cap. The old web stays on port 3002 until an approved tunnel switch. The base `compose.rollout.yml` now requires a separate restricted DB URL, a fixed candidate IP with a PostgreSQL SCRAM/reject guard, read-only storage and a read-only transaction default. A separate `compose.cutover.yml` and credential file are needed for future writable traffic. Neither file recreates the old web or DB.

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

## Restricted database provisioning requires separate approval

The preflight account is `osm_rails_preflight_ro`, with a generated password separate from the current application account. The tested, idempotent [provisioner](../deploy/osaka-rails-production/provision_readonly_role.py) creates it with LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, NOINHERIT and an eight-connection limit; it grants CONNECT, public-schema USAGE and SELECT on exactly nine OSM tables: `changesets`, `current_nodes`, `current_node_tags`, `current_ways`, `current_way_nodes`, `current_way_tags`, `current_relations`, `current_relation_members` and `current_relation_tags`. A separate `issue15_preflight.users` view exposes only `id`, `display_name`, `data_public` and `creation_time` to satisfy Rails' `users.*` map association; the candidate's preflight-only initializer tells ActiveRecord that the view's primary key is `id`. The account has no SELECT on `public.users` or OAuth tables, no sequence/table write privileges and no membership. The provisioner sends only a SCRAM verifier, not plaintext, to PostgreSQL and refuses the original project unless `--allow-osaka` is supplied. This adds a private schema/view to the original DB only after separate approval; cutover disables the initializer and uses the original table.

Three existing PUBLIC ACLs also require change to enforce read-only behavior on PostgreSQL 14: revoke CREATE on schema `public`, TEMPORARY on database `openstreetmap`, and SELECT on PostGIS relations `public.geography_columns`, `public.geometry_columns` and `public.spatial_ref_sys`. These are **database changes** beyond creating the role. The original web uses a superuser and was unaffected by these ACL changes in the isolated test; the original database has **not** been changed. Capture the original database/schema/relation ACLs privately before approved provisioning, and compare them before any rollback.

The current original host authentication does not prevent a candidate from choosing the existing superuser identity. The tested [HBA helper](../deploy/osaka-rails-production/preflight_hba.py) must prepend these two rules before any candidate starts, with a fixed, unassigned address on the approved private network. The live subnet and proposed address are recorded privately:

```text
host openstreetmap osm_rails_preflight_ro <PREFLIGHT_IP>/32 scram-sha-256
host all all <PREFLIGHT_IP>/32 reject
```

The helper checks the project labels, DB network attachment, address/subnet and rule order; it keeps an exact private mode-0600 HBA backup and reloads PostgreSQL configuration without restarting the service. The original DB's HBA and ACL changes, including `pg_reload_conf()`, **require explicit separate approval**. The reviewed isolated test proved the wrong password and a superuser login from the candidate IP were rejected. No actual Osaka IP or route was changed.

After that database-change approval, provision only with a fresh backup, private `STAGE` created by the procedure below, unchanged ownership/ACL snapshot and an unassigned candidate IP. The following commands show the *exact planned changes*; they have **not** been run on Osaka:

```sh
export PREFLIGHT_IP='<approved-unused-IP-from-private-network-plan>'
python3 deploy/osaka-rails-production/provision_readonly_role.py \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --credential-file "$STAGE/preflight-role.password" --allow-osaka
python3 deploy/osaka-rails-production/preflight_hba.py install \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --network osm-api-sandbox_default --candidate-ip "$PREFLIGHT_IP" \
  --backup "$STAGE/pg_hba.before" --allow-osaka
```

For rollback **before any cutover**, stop only the candidate if it exists, then run the HBA helper's `rollback` with the same arguments and backup. It refuses rollback if the file changed since installation. After confirming no preflight-role sessions, ownership or unexpected grants, revoke its grants and drop it; restore the three PUBLIC ACLs only if they still match the captured pre-provisioning state. The exact prior Osaka ACLs inspected for this design were PUBLIC CREATE on `public`, PUBLIC TEMPORARY on `openstreetmap` and PUBLIC SELECT on the three named PostGIS relations. A concurrent ACL/HBA change must be reviewed manually rather than overwritten. The old Rails service on port 3002 stays running throughout.

## Approved rollout procedure (not executed)

**Current status: technical GO for the restricted role on an isolated restore; NO-GO for original-DB provisioning, side-by-side startup or cutover.** The 2026-11-10 authorized preflight stopped before candidate startup because its database identity could write and the original host authentication policy did not bind it to a restricted role. The new role, fixed-IP HBA guard and production Rails read routes passed only on a disposable restored database; see the [readiness audit](RAILS_DEPLOYMENT_READINESS.md#2026-11-10-restricted-role-isolated-validation). The isolated iD test remains a technical GO for the upstream CDN path when the browser can reach jsDelivr. The intended Cloudflare Access browser path is still unverified.

The 2026-11-09 fresh-backup audit restored successfully to an isolated database; see [deployment readiness](RAILS_DEPLOYMENT_READINESS.md). Repeat the bounded backup and independent restore if the snapshot is stale at cutover. First confirm host headroom, the active tunnel service manager, and an agreed maintenance/rollback window. **The following Osaka commands remain unexecuted and require the approval boundaries below.** `make_private_env.py` now generates a distinct preflight role password and Rails env in a mode-0700 stage; it does not prompt for the existing application-role password. Keep the entire stage private. Do not run any migration, `db:prepare`, seed, or asset task against the existing checkout.

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
export PREFLIGHT_IP='<approved-unused-IP-from-private-network-plan>'

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
python3 deploy/osaka-rails-production/make_private_env.py "$STAGE/preflight.env" "$STAGE/preflight-role.password"
bash deploy/osaka-rails-production/build_assets.sh "$STAGE" "$RAILS_IMAGE" "$STAGE/preflight.env" "$SETTINGS" > "$STAGE/assets-build.log" 2>&1
printf 'OSM_RAILS_IMAGE=%s\nOSM_APP_COPY=%s\nOSM_PRIVATE_ENV_FILE=%s\nOSM_SETTINGS_LOCAL_FILE=%s\nOSM_PREFLIGHT_IP=%s\n' "$RAILS_IMAGE" "$STAGE/app" "$STAGE/preflight.env" "$SETTINGS" "$PREFLIGHT_IP" > "$STAGE/compose.env"
chmod 600 "$STAGE/compose.env"
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --quiet
```

If restore fails, inspect ownership and remove only the disposable restore project; do not continue. After separate approval for the original-DB changes, capture current ACLs privately, run the [role and HBA provisioning commands](#restricted-database-provisioning-requires-separate-approval), and verify the candidate IP is still unassigned. The role and HBA helper each refuse original Osaka use unless their explicit `--allow-osaka` flag is supplied. These changes are **not** authorized by PR review or the prior stopped preflight. Record the ACL snapshot before provisioning:

```sh
{
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc "SELECT 'database|'||coalesce(datacl::text,'NULL') FROM pg_database WHERE datname='openstreetmap'"
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc "SELECT 'schema|'||coalesce(nspacl::text,'NULL') FROM pg_namespace WHERE nspname='public'"
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc "SELECT c.relname||'|'||coalesce(c.relacl::text,'NULL') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname IN ('geography_columns','geometry_columns','spatial_ref_sys') ORDER BY c.relname"
} > "$STAGE/acl.before"
chmod 600 "$STAGE/acl.before"
```

After that provisioning and a **renewed side-by-side startup approval**, render and check the restricted identity, fixed IP, loopback port, read-only storage and transaction default before `up`. The route remains on 3002. `PGOPTIONS` is defense in depth; the database grants and fixed-IP HBA rules are the actual write boundary.

```sh
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --format json | python3 -c 'import json,sys,os,urllib.parse; c=json.load(sys.stdin)["services"]["candidate"]; v=[v for v in c["volumes"] if v["target"]=="/app/storage"]; assert len(v)==1 and v[0]["read_only"] and c["environment"]["PGOPTIONS"]=="-c default_transaction_read_only=on" and urllib.parse.urlparse(c["environment"]["DATABASE_URL"]).username=="osm_rails_preflight_ro" and c["networks"]["osaka"]["ipv4_address"]==os.environ["PREFLIGHT_IP"] and c["ports"][0]["host_ip"]=="127.0.0.1"'
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

If the side-by-side checks fail **before any cutover**, stop only this candidate project. The old service remains on 3002. Then, under the same approved database-change scope, restore the exact HBA backup after confirming the fixed preflight IP is unassigned:

```sh
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" down
python3 deploy/osaka-rails-production/preflight_hba.py rollback \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --network osm-api-sandbox_default --candidate-ip "$PREFLIGHT_IP" \
  --backup "$STAGE/pg_hba.before" --allow-osaka
```

After reviewing the pre-provisioning ACL snapshot, confirming no candidate sessions or preflight-role ownership, and confirming the private schema still contains only the provisioned view, run this rollback in one transaction as a database administrator. It restores only the PUBLIC grants observed before provisioning; stop if the snapshot differs. The HBA helper separately refuses an exact rollback after any unrelated HBA edit.

```sql
BEGIN;
DROP SCHEMA issue15_preflight CASCADE;
DROP OWNED BY osm_rails_preflight_ro;
DROP ROLE osm_rails_preflight_ro;
GRANT CREATE ON SCHEMA public TO PUBLIC;
GRANT TEMPORARY ON DATABASE openstreetmap TO PUBLIC;
GRANT SELECT ON TABLE public.geography_columns, public.geometry_columns,
  public.spatial_ref_sys TO PUBLIC;
COMMIT;
```

**Cutover approval is separate from DB provisioning, PR review and read-only side-by-side startup.** It would authorize a separate writable credential file, a different unused candidate IP, writable storage/DB access, and then a tunnel-origin change. Review the writable cutover IP's authentication policy as part of that approval. The following remains an unexecuted draft. First render both Compose files and verify the cutover URL, distinct IP, writable storage and cleared `PGOPTIONS`. The tunnel helper validates a private temporary file, locks cooperating invocations, rejects a concurrent content change, creates a mode-600 backup, and replaces only the expected origin line with mode-600 permissions. It does **not** restart the tunnel. If the tunnel restart fails, restore the prior route and retry the old tunnel before leaving the maintenance window.

```sh
export CUTOVER_IP='<approved-distinct-unused-cutover-IP>'
python3 deploy/osaka-rails-production/make_cutover_env.py "$STAGE/cutover.env"
printf 'OSM_RAILS_IMAGE=%s\nOSM_APP_COPY=%s\nOSM_PRIVATE_ENV_FILE=%s\nOSM_SETTINGS_LOCAL_FILE=%s\nOSM_PREFLIGHT_IP=%s\nOSM_CUTOVER_IP=%s\n' "$RAILS_IMAGE" "$STAGE/app" "$STAGE/cutover.env" "$SETTINGS" "$PREFLIGHT_IP" "$CUTOVER_IP" > "$STAGE/compose.cutover.env"
chmod 600 "$STAGE/compose.cutover.env"
docker compose --env-file "$STAGE/compose.cutover.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" config --format json | python3 -c 'import json,sys,os,urllib.parse; c=json.load(sys.stdin)["services"]["candidate"]; v=[v for v in c["volumes"] if v["target"]=="/app/storage"]; assert len(v)==1 and not v[0].get("read_only",False) and c["environment"]["PGOPTIONS"]=="" and urllib.parse.urlparse(c["environment"]["DATABASE_URL"]).username=="openstreetmap" and c["networks"]["osaka"]["ipv4_address"]==os.environ["CUTOVER_IP"] and os.environ["CUTOVER_IP"]!=os.environ["PREFLIGHT_IP"]'
docker compose --env-file "$STAGE/compose.cutover.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" up -d --no-deps --force-recreate candidate
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
