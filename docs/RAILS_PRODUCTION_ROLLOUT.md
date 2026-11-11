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

## Restricted database provisioning: completed under database-only approval

The preflight account is `osm_rails_preflight_ro`, with a generated password separate from the current application account. The tested, idempotent [provisioner](../deploy/osaka-rails-production/provision_readonly_role.py) creates it with LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, NOINHERIT and an eight-connection limit; it grants CONNECT, public-schema USAGE and SELECT on exactly nine OSM tables: `changesets`, `current_nodes`, `current_node_tags`, `current_ways`, `current_way_nodes`, `current_way_tags`, `current_relations`, `current_relation_members` and `current_relation_tags`. A separate `issue15_preflight.users` view exposes only `id`, `display_name`, `data_public` and `creation_time` to satisfy Rails' `users.*` map association; the candidate's preflight-only initializer tells ActiveRecord that the view's primary key is `id`. The account has no SELECT on `public.users` or OAuth tables, no sequence/table write privileges and no membership. The provisioner sends only a SCRAM verifier, not plaintext, to PostgreSQL and refuses the original project unless `--allow-osaka` is supplied. This adds a private schema/view to the original DB only after separate approval; cutover disables the initializer and uses the original table.

Three existing PUBLIC ACLs required change to enforce read-only behavior on PostgreSQL 14: revoke CREATE on schema `public`, TEMPORARY on database `openstreetmap`, and SELECT on PostGIS relations `public.geography_columns`, `public.geometry_columns` and `public.spatial_ref_sys`. These changes were applied under the 2026-11-10 database-only authorization after private ACL and client-impact snapshots. The existing web uses a superuser and still serves identical read-only responses. Compare current ACLs with the private before/after snapshots before any rollback.

The original broad host authentication rule did not prevent a candidate from choosing the existing superuser identity. The tested [HBA helper](../deploy/osaka-rails-production/preflight_hba.py) prepended these two rules before any candidate startup, with a fixed address on the approved private network. The live subnet and address are recorded privately:

```text
host openstreetmap osm_rails_preflight_ro <PREFLIGHT_IP>/32 scram-sha-256
host all all <PREFLIGHT_IP>/32 reject
```

The helper checks the project labels, DB network attachment, address/subnet and rule order; it keeps an exact private mode-0600 HBA backup and reloads PostgreSQL configuration without restarting the service. The 2026-11-10 database-only authorization covered the original DB's role, ACL and HBA changes, including `pg_reload_conf()`. The wrong password and a superuser login from the reserved IP were rejected on Osaka. No Rails candidate or tunnel route was changed.

The fixed-IP rules constrain the future candidate at that address. The original HBA's broader trust rule still applies to other network addresses; the restricted role has no write privileges there, but the SCRAM password is not enforced outside the reserved IP. The database has no host port, and only the original web and DB were attached during provisioning. Review any future network attachment or HBA policy expansion separately.

The following reviewed commands were run on Osaka with a generated credential in the private provisioning stage after backup, ownership, ACL, HBA and IP checks. They are retained for audit and disposable tests; **do not run them again as part of the next side-by-side preflight**:

```sh
export PREFLIGHT_IP='<approved-unused-IP-from-private-network-plan>'
python3 deploy/osaka-rails-production/provision_readonly_role.py \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --credential-file "$ROLE_STAGE/preflight-role.password" --allow-osaka
python3 deploy/osaka-rails-production/preflight_hba.py install \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --network osm-api-sandbox_default --candidate-ip "$PREFLIGHT_IP" \
  --backup "$ROLE_STAGE/pg_hba.rollback" --allow-osaka
```

For a failed side-by-side check **before any cutover**, stop only the candidate; leave the installed role, ACLs and HBA guard intact for review. A separately approved database rollback would use the HBA helper's exact-content rollback after the candidate IP is free, then inspect sessions, ownership and grants before dropping the role/view and restoring the prior PUBLIC ACLs. The exact prior Osaka ACLs were PUBLIC CREATE on `public`, PUBLIC TEMPORARY on `openstreetmap` and PUBLIC SELECT on the three named PostGIS relations. A concurrent ACL/HBA change must be reviewed manually rather than overwritten. The old Rails service on port 3002 stays running throughout.

## Completed side-by-side preflight and unapproved cutover procedure

**Current status: the approved read-only side-by-side preflight passed; Cloudflare cutover remains unapproved.** The production candidate is healthy on loopback port 3003 with the restricted role and read-only storage, while the original service remains on port 3002. Ten sequential warm requests per service showed Box A median 1.083 s on 3002 versus 0.663 s on 3003 (38.8% faster), and Box B 0.393 s versus 0.254 s (35.4% faster), with identical response bytes. No original OSM/user/OAuth count, container identity or HBA change occurred. See the [readiness audit](RAILS_DEPLOYMENT_READINESS.md#2026-11-10-production-rails-side-by-side-result) for methodology, p95, CPU and memory. The intended Cloudflare Access browser path is still unverified.

The 2026-11-09 fresh-backup audit restored successfully to an isolated database; see [deployment readiness](RAILS_DEPLOYMENT_READINESS.md). Repeat the bounded backup and independent restore if the snapshot is stale at cutover. The source preparation, asset build and candidate start steps below were executed in a separate private stage for the approved preflight; they are retained as a repeatable reference, **not instructions to recreate the running candidate**. The tunnel and writable cutover commands remain unexecuted and require separate approval. The restricted role password was already generated and installed. Reuse its existing private `preflight.env`; generating a new one without rotating the database role would break authentication. Keep the entire stage private. Do not run any migration, `db:prepare`, seed, or asset task against the existing checkout.

```sh
set -euo pipefail
umask 077
export STAGE="$PWD/reports/runs/issue15-osaka-rollout-$(date +%Y%m%d%H%M%S)"
export ROLE_STAGE='<existing-private-provisioning-stage>'
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
test -f "$ROLE_STAGE/preflight.env" && test -f "$ROLE_STAGE/pg_hba.rollback"
cp "$ROLE_STAGE/preflight.env" "$STAGE/preflight.env"
chmod 600 "$STAGE/preflight.env"
bash deploy/osaka-rails-production/build_assets.sh "$STAGE" "$RAILS_IMAGE" "$STAGE/preflight.env" "$SETTINGS" > "$STAGE/assets-build.log" 2>&1
printf 'OSM_RAILS_IMAGE=%s\nOSM_APP_COPY=%s\nOSM_PRIVATE_ENV_FILE=%s\nOSM_SETTINGS_LOCAL_FILE=%s\nOSM_PREFLIGHT_IP=%s\n' "$RAILS_IMAGE" "$STAGE/app" "$STAGE/preflight.env" "$SETTINGS" "$PREFLIGHT_IP" > "$STAGE/compose.env"
chmod 600 "$STAGE/compose.env"
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --quiet
```

If restore fails, inspect ownership and remove only the disposable restore project; do not continue. The database-only role/HBA changes have already been approved and applied. Before a separately approved candidate startup, compare the installed grants and HBA guard with the private after-state snapshot, confirm the reserved IP is unassigned, and stop if they differ. Record a fresh ACL snapshot for the side-by-side audit:

```sh
{
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc "SELECT 'database|'||coalesce(datacl::text,'NULL') FROM pg_database WHERE datname='openstreetmap'"
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc "SELECT 'schema|'||coalesce(nspacl::text,'NULL') FROM pg_namespace WHERE nspname='public'"
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc "SELECT c.relname||'|'||coalesce(c.relacl::text,'NULL') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname IN ('geography_columns','geometry_columns','spatial_ref_sys') ORDER BY c.relname"
} > "$STAGE/acl.before"
chmod 600 "$STAGE/acl.before"
```

The bounded side-by-side startup approval covered this step, which was executed after the restricted identity, fixed IP, loopback port, read-only storage and transaction default passed rendered and runtime checks. The route remains on 3002. `PGOPTIONS` is defense in depth; the database grants and fixed-IP HBA rules are the actual write boundary. Do not rerun `up` against the healthy candidate unless a separately reviewed recovery calls for it.

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

If a side-by-side check fails **before any cutover**, stop only this candidate project. The old service remains on 3002. The current preflight authorization does not include changing HBA or grants. Preserve the installed database guard for review; any later database rollback requires checking the private before/after snapshots and its own approval boundary.

```sh
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" down
```

If a separate database rollback is approved, confirm the candidate is stopped, the reserved IP is unassigned and the HBA file still equals the installed snapshot before using the exact private rollback file:

```sh
python3 deploy/osaka-rails-production/preflight_hba.py rollback \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --network osm-api-sandbox_default --candidate-ip "$PREFLIGHT_IP" \
  --backup "$ROLE_STAGE/pg_hba.rollback" --allow-osaka
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

## Exact cutover sequence for the running candidate

**This sequence is prepared but not authorized or executed.** The existing read-only candidate on port 3003 uses the private stage created during the successful side-by-side preflight. Reuse that stage; do not rerun source preparation or read-only role provisioning. The 2026-11-10 bounded backup (81,594,313 bytes) restored independently with exact original counts, and a disposable production Rails instance passed synthetic login, secure session, OAuth bearer read, one changeset/node API write and writable storage. A later isolated restore proved the new restricted writable role's authentication, grants, DML, DDL denial, Rails boot/map and rolled-back Rails write. The complete browser/OAuth/API write flow has not been repeated with that role. The backup is still on the same host; no approved off-host destination was found. Refresh its backup/restore evidence if cutover is delayed and explicitly decide whether same-host-only recovery is acceptable.

The writable override retains only the candidate service, loopback port 3003 and 1 GiB/1 CPU cap. It requires the separately provisioned `osm_rails_cutover_rw` role, a distinct currently unassigned IP with a candidate-specific SCRAM/reject HBA guard, and writable original storage; it disables the preflight-only initializer and `PGOPTIONS`. The old web and DB are absent from the rendered Compose and remain on their existing project. The legacy `trust` rule remains unchanged behind the new guard. The existing `openstreetmap` superuser and its password are not used for the writable candidate. No live database grant, credential or HBA change was made during this audit.

Before a separately approved cutover, verify the pinned source/image, current candidate and old-service health, original counts, fresh backup, volume/network ownership, HBA policy and unused distinct IP. The private operator audit holds the exact current stage and addresses; keep password, rendered Compose and backup files out of Git. **Live writable-role provisioning and HBA installation require their own explicit approval before candidate recreation.** Generate a new role password in a private 0700 stage; provision the role and fixed-IP guard only after comparing current roles, grants, HBA and clients with the reviewed baseline. Test right/wrong password and another-role rejection from the reserved IP before proceeding. The tunnel helper validates a private temporary config, locks cooperating invocations, rejects concurrent edits, creates a mode-0600 backup and changes only the expected origin line. It does not restart the tunnel.

```sh
export STAGE="$PWD/reports/runs/issue15-osaka-sidebyside-20261110/candidate"
export BACKUP_STAGE="$PWD/reports/runs/issue15-cutover-readiness-20261110"
export PROJECT=issue15-osaka-prod
export COMPOSE=deploy/osaka-rails-production/compose.rollout.yml
export CUTOVER_COMPOSE=deploy/osaka-rails-production/compose.cutover.yml
export SETTINGS=/opt/osm-sandbox/osm-api-sandbox/openstreetmap-website/config/settings.local.yml
export RAILS_IMAGE=sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332
export PREFLIGHT_IP='<existing-private-guarded-IP>'
export CUTOVER_IP='<reviewed-distinct-unused-IP>'
export OSAKA_SUBNET="$(docker network inspect osm-api-sandbox_default --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
python3 - "$PREFLIGHT_IP" "$CUTOVER_IP" "$OSAKA_SUBNET" <<'PY'
import ipaddress, sys
preflight, cutover = (ipaddress.IPv4Address(value) for value in sys.argv[1:3])
assert preflight != cutover
subnet = ipaddress.IPv4Network(sys.argv[3])
assert preflight in subnet and cutover in subnet
PY
test "$(docker inspect issue15-osaka-prod-candidate-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')" = "$PREFLIGHT_IP"
sha256sum -c "$BACKUP_STAGE/archive.sha256"
test "$(docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --services)" = candidate
test -z "$(docker network inspect osm-api-sandbox_default --format '{{range $id,$c := .Containers}}{{println $c.IPv4Address}}{{end}}' | rg "^$CUTOVER_IP/")"
```

Recheck and snapshot the seven original OSM/user/OAuth counts and both original container identities immediately before the next block. If any prerequisite differs, stop before candidate recreation. The current candidate will pause on port 3003 during recreation, while the old public service continues on port 3002.

Under a **separate live database provisioning approval**, create a new private role credential and apply only the reviewed role and cutover-IP HBA guard. The provisioner refuses schema drift, PUBLIC CREATE/TEMP privileges, unexpected role ownership or membership, and an existing unmarked role. The HBA helper refuses a used IP, a mismatched project/network or an unexpected HBA backup. It prepends SCRAM/reject rules before the existing read-only guard and legacy trust. The database is reloaded, not restarted. Verify role flags/grants and a successful password-authenticated connection, plus wrong-password and other-role rejection, from a short-lived client at the reserved IP; compare the original web health/counts after the reload. Do not proceed if any check fails. Roll back only the exact HBA backup after checking for unrelated changes; the new role can remain unused pending review.

```sh
export RW_ROLE_STAGE="$PWD/reports/runs/issue15-osaka-writable-role-APPROVED-DATE"
install -d -m 700 "$RW_ROLE_STAGE"
python3 deploy/osaka-rails-production/make_writable_credential.py "$RW_ROLE_STAGE/role.password"
python3 deploy/osaka-rails-production/provision_writable_role.py \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --credential-file "$RW_ROLE_STAGE/role.password" --allow-osaka
python3 deploy/osaka-rails-production/cutover_hba.py install \
  --container osm-api-sandbox-db-1 --project osm-api-sandbox \
  --network osm-api-sandbox_default --candidate-ip "$CUTOVER_IP" \
  --backup "$RW_ROLE_STAGE/pg_hba.rollback" --allow-osaka
test "$(docker exec osm-api-sandbox-db-1 psql -X -U postgres -d openstreetmap -Atc \
  "SELECT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls FROM pg_roles WHERE rolname='osm_rails_cutover_rw'")" = t
python3 - "$RW_ROLE_STAGE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); f=p/'pg-client.env'
f.write_text('PGPASSWORD='+(p/'role.password').read_text().strip()+'\n')
f.chmod(0o600)
PY
export DB_IMAGE=sha256:7e04bfcf1b20b7ccd558f1977e9f08f72c5683b4b59b021a127cbe370a7ee574
test "$(docker run --rm --network osm-api-sandbox_default --ip "$CUTOVER_IP" \
  --env-file "$RW_ROLE_STAGE/pg-client.env" --entrypoint psql "$DB_IMAGE" \
  -X -h db -U osm_rails_cutover_rw -d openstreetmap -Atc 'SELECT current_user')" = osm_rails_cutover_rw
if docker run --rm --network osm-api-sandbox_default --ip "$CUTOVER_IP" \
  -e PGPASSWORD=wrong --entrypoint psql "$DB_IMAGE" \
  -X -h db -U osm_rails_cutover_rw -d openstreetmap -Atc 'SELECT 1'; then exit 1; fi
if docker run --rm --network osm-api-sandbox_default --ip "$CUTOVER_IP" \
  --entrypoint psql "$DB_IMAGE" \
  -X -h db -U postgres -d openstreetmap -Atc 'SELECT 1'; then exit 1; fi
# Recheck 3002, 3003, original counts and container restart counts here.
# Retain the private role password and HBA backup for rollback/review.
```

The existing `openstreetmap` login and HBA paths stay unchanged. The new role grants broad application DML on the current 58 tables, excluding writes to Rails migration metadata and PostGIS reference data, and USAGE/SELECT on 35 sequences. It cannot own objects or run migrations. If complete login/OAuth/API write compatibility under the restricted role is made a hard gate, repeat that test on an isolated restore before authorizing this live provisioning phase.

```sh
python3 deploy/osaka-rails-production/make_cutover_env.py "$RW_ROLE_STAGE/role.password" "$STAGE/cutover.env"
printf 'OSM_RAILS_IMAGE=%s\nOSM_APP_COPY=%s\nOSM_PRIVATE_ENV_FILE=%s\nOSM_SETTINGS_LOCAL_FILE=%s\nOSM_PREFLIGHT_IP=%s\nOSM_CUTOVER_IP=%s\n' "$RAILS_IMAGE" "$STAGE/app" "$STAGE/cutover.env" "$SETTINGS" "$PREFLIGHT_IP" "$CUTOVER_IP" > "$STAGE/compose.cutover.env"
chmod 600 "$STAGE/compose.cutover.env"
test "$(docker compose --env-file "$STAGE/compose.cutover.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" config --services)" = candidate
docker compose --env-file "$STAGE/compose.cutover.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" config --format json | python3 -c 'import json,sys,os,urllib.parse; c=json.load(sys.stdin)["services"]["candidate"]; v=[v for v in c["volumes"] if v["target"]=="/app/storage"]; assert len(v)==1 and not v[0].get("read_only",False) and c["environment"]["PGOPTIONS"]=="" and urllib.parse.urlparse(c["environment"]["DATABASE_URL"]).username=="osm_rails_cutover_rw" and c["networks"]["osaka"]["ipv4_address"]==os.environ["CUTOVER_IP"] and os.environ["CUTOVER_IP"]!=os.environ["PREFLIGHT_IP"]'
docker compose --env-file "$STAGE/compose.cutover.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" up -d --no-deps --force-recreate --wait --wait-timeout 180 candidate
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

Use the normal HTTPS sandbox hostname to verify root page, login with a dedicated test account, secure session cookie, `/edit?editor=id`, iD frame, browser console/network asset requests, map data, OAuth-backed user details, and existing read-only API endpoints. Require the actual iD interface, map, zoom, feature selection and tagging controls to render; confirm successful tagging-schema and name-suggestion requests to `cdn.jsdelivr.net` rather than relying on iframe HTML alone. Verify public HTTPS, `Host`/forwarded scheme and CSP behavior. Do not save an OSM edit as part of this rollout. Monitor 5xx, p50/p95 Box A timings, Rails/DB CPU, RSS, and old/new container health for at least ten minutes. Keep the old web running on 3002 during the rollback window. The tunnel restart causes a brief, unmeasured public interruption. The new process and signing key require session re-login; a route rollback may require another login.

**Acceptance:** all critical HTML/JS/CSS/iD assets and API checks pass with no unexpected redirects or 404/5xx; Box A digest and 336,634-byte response match; five sequential warm Box A GETs have median at or below 0.85 s and at least 20% lower than five same-condition old-service GETs; candidate stays below its 1 GiB limit without restarts; DB aggregate counts do not change during read-only smoke checks; the tunnel reaches the intended port; dedicated test login and OAuth read succeed after cutover. Treat a 5xx, broken editor, asset miss, insecure cookie/HTTP route, count drift before login, or exceeded latency/memory limit as a rollback trigger. These thresholds are proposed for review, not demonstrated at sustained load.

## Fast rollback

If a trigger fires, restore the exact pre-cutover ingress file and restart the tunnel; the helper refuses rollback if someone has edited that file for another reason. Confirm the old 3002 service through the HTTPS hostname, then stop only the candidate project. Its external storage volume and network are never removed by this Compose file. Keep the private stage until review of logs and the rollback window ends; delete it only after checking ownership and retention requirements.

```sh
sudo python3 deploy/osaka-rails-production/switch_tunnel_route.py rollback /etc/cloudflared/config.yml
sudo systemctl restart cloudflared
sudo systemctl is-active cloudflared
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
docker compose --env-file "$STAGE/compose.cutover.env" -p "$PROJECT" -f "$COMPOSE" -f "$CUTOVER_COMPOSE" down
```

No database migration, schema change, planned OSM API edit, or change to the old web is part of this procedure, so tunnel rollback returns traffic to the old service. Normal user account, OAuth and OSM edits after an approved cutover are not undone by a route rollback. Before executing any rollout, confirm the latest source/image still matches the pinned revisions and that the private backup and tunnel manager can be operated on the real host.
