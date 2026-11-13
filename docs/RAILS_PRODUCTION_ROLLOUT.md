# Issue #15: Osaka production-mode Rails rollout

**Current state: cutover succeeded on 2026-11-12.** Production-mode Rails serves the Osaka sandbox on loopback port 3003 behind Cloudflare Access. The original web remains on port 3002, and the operator preserved the private Issue #15 rollback config selecting 3002. The candidate uses the dedicated restricted writable database role; the original PostgreSQL container was not recreated. The November 8–11 preparation, preflight decisions and measurements below are historical evidence, not current deployment blockers. The operator-assisted switch and accepted browser checks are recorded in the [readiness report](RAILS_DEPLOYMENT_READINESS.md#operator-assisted-cutover-and-acceptance--2026-11-12).

## Read-only current-state diagnostic

Run the [status helper](../deploy/osaka-rails-production/status.py) from this checkout. It only reads the tunnel config and Issue #15 backup, `systemctl` state and Docker inspect data; it prints selected status fields without config contents or credentials. Because the root-owned route files are mode 0600, an operator with interactive sudo must run the complete check. The deployment account can run it without sudo for partial status, but an `unreadable` origin is **not** proof of which port Cloudflare selects.

```sh
sudo python3 deploy/osaka-rails-production/status.py
```

Expected accepted output: `route_state=already_switched`, configured origin 3003, rollback origin 3002, backup present and mode 0600, cloudflared active, candidate healthy with `RAILS_ENV=production`, `RACK_ENV=production` and loopback port 3003. The helper exits nonzero on unknown or unexpected state. If it reports `already_switched`, **do not rerun** `switch_tunnel_route.py candidate`; that helper correctly refuses to overwrite an existing backup. Keep both route files intact. If it reports `rollback_configured`, `missing` backup, unexpected origins or unreadable evidence, investigate with the operator before any route action. Do not delete, rename or overwrite the backup to make a switch command pass.

The switch/rollback helper changes the file only after exact-content checks; an operator performs the separate `systemctl restart cloudflared` and ingress validation. For an actual rollback, use the [fast rollback](#fast-rollback) procedure with interactive sudo, then confirm the old 3002 service through the public hostname. A route rollback does not undo shared database or storage writes. The three-of-four Cloudflare HA connection result is a **separate monitoring concern** from origin selection and Rails health; investigate tunnel/edge connectivity if it persists or users see failures, without changing the route during this closeout.

## Evidence and configuration choice

The first read-only Osaka timings are in [PR #16](https://github.com/L3Pro/osm-address-import/pull/16), at `docs/RAILS_PERFORMANCE_BASELINE.md`. The isolated mode comparison is in [PR #18](https://github.com/L3Pro/osm-address-import/pull/18), at `docs/RAILS_MODE_COMPARISON.md`. Both measurements remain historical evidence. Merge **#16, then #18, then #19**; G1 [PR #17](https://github.com/L3Pro/osm-address-import/pull/17) is independent.

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

## Historical read-only side-by-side preflight

**Historical result from 2026-11-10:** the approved read-only side-by-side preflight passed. The candidate then used read-only storage and a restricted role on loopback port 3003, while the original service ran on port 3002. Ten sequential warm requests per service showed Box A median 1.083 s on 3002 versus 0.663 s on 3003 (38.8% faster), and Box B 0.393 s versus 0.254 s (35.4% faster), with identical response bytes. No original OSM/user/OAuth count, container identity or HBA change occurred. See the [readiness audit](RAILS_DEPLOYMENT_READINESS.md#2026-11-10-production-rails-side-by-side-result) for methodology, p95, CPU and memory. Later operator-assisted cutover and public browser results are recorded below.

The 2026-11-09 backup and restore audit remains historical evidence; see [deployment readiness](RAILS_DEPLOYMENT_READINESS.md#osaka-sandbox-recovery-policy--2026-11-11). Under the owner's disposable-sandbox policy, no fresh backup, off-host copy or independent restore was required for this deployment. Preserve existing backups. The source preparation, asset build and candidate start steps below were executed in a separate private stage for the approved preflight; they are retained as a repeatable reference, **not instructions to recreate the running candidate**. The tunnel and writable cutover commands were later executed with operator assistance on November 12; do not rerun them. The restricted role password was already generated and installed. Reuse its existing private `preflight.env`; generating a new one without rotating the database role would break authentication. Keep the entire stage private. Do not run any migration, `db:prepare`, seed, or asset task against the existing checkout.

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
export PROJECT=issue15-osaka-prod
export PREFLIGHT_IP='<approved-unused-IP-from-private-network-plan>'

docker ps --filter label=com.docker.compose.project=osm-api-sandbox --format '{{.Names}} {{.Status}}'
docker network inspect osm-api-sandbox_default --format '{{index .Labels "com.docker.compose.project"}}'
docker volume inspect osm-api-sandbox_web-storage --format '{{index .Labels "com.docker.compose.project"}}'
test "$(systemctl is-active cloudflared)" = active
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate

bash deploy/osaka-rails-production/prepare_candidate.sh "$SOURCE" "$STAGE" osm-api-sandbox-web-1
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' osm-api-sandbox-db-1 psql -X -U openstreetmap -d openstreetmap -Atc 'SELECT (SELECT count(*) FROM current_nodes),(SELECT count(*) FROM current_ways),(SELECT count(*) FROM current_relations),(SELECT count(*) FROM current_way_tags)' > "$STAGE/osaka-counts-before.txt"
test -f "$ROLE_STAGE/preflight.env" && test -f "$ROLE_STAGE/pg_hba.rollback"
cp "$ROLE_STAGE/preflight.env" "$STAGE/preflight.env"
chmod 600 "$STAGE/preflight.env"
bash deploy/osaka-rails-production/build_assets.sh "$STAGE" "$RAILS_IMAGE" "$STAGE/preflight.env" "$SETTINGS" > "$STAGE/assets-build.log" 2>&1
printf 'OSM_RAILS_IMAGE=%s\nOSM_APP_COPY=%s\nOSM_PRIVATE_ENV_FILE=%s\nOSM_SETTINGS_LOCAL_FILE=%s\nOSM_PREFLIGHT_IP=%s\n' "$RAILS_IMAGE" "$STAGE/app" "$STAGE/preflight.env" "$SETTINGS" "$PREFLIGHT_IP" > "$STAGE/compose.env"
chmod 600 "$STAGE/compose.env"
docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --quiet
```

The database-only read-only role/HBA changes have already been approved and applied. Before a separately approved candidate startup, compare the installed grants and HBA guard with the private after-state snapshot, confirm the reserved IP is unassigned, and stop if they differ. Record a fresh ACL snapshot for the side-by-side audit:

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

**This sequence was executed with interactive operator privileges on 2026-11-12; do not rerun it.** The reviewed writable candidate is running in production mode on loopback 3003, Cloudflare selects 3003, and the original web remains on 3002 for rollback. The private mode-0600 tunnel backup selects 3002. The deployment account cannot run the privileged switch or rollback non-interactively; an operator with interactive sudo must perform any traffic rollback. The 2026-11-11 isolated production Rails test used the dedicated `osm_rails_cutover_rw` role and passed CSRF login, secure session, authenticated editor/iD routes, OAuth bearer read, changeset and synthetic node creation/readback/closure, and writable storage. Unauthorized DDL, migrations, role escalation and reads outside the grants failed. Osaka is a disposable sandbox: the owner accepts loss of sandbox-only data on rebuild, and no fresh backup, off-host copy or independent restore is required for this deployment. Preserve existing backups. Exact HBA and Rails traffic rollback remain required.

The writable override retains only the candidate service, loopback port 3003 and 1 GiB/1 CPU cap. It requires the provisioned `osm_rails_cutover_rw` role, the reserved writable IP with SCRAM and role-wide IPv4/IPv6/local reject rules ahead of legacy `trust`, and writable original storage; it disables the preflight-only initializer and `PGOPTIONS`. Other roles from the candidate IP are rejected. The old web and DB are absent from the rendered Compose and remain on their existing project. The legacy `trust` rule remains unchanged for existing clients; the new role cannot fall through to it from another IP. The existing `openstreetmap` superuser and its password are not used for the writable candidate. The role and HBA guard were installed under separate authorization on 2026-11-11; see the private `reports/runs/issue15-osaka-writable-role-20261111` audit. Candidate recreation and the operator-assisted tunnel switch were completed on 2026-11-12.

The executed preflight verified pinned source/image, current candidate and old-service health, original counts, volume/network ownership and installed HBA policy. The private operator audit holds the exact stage and addresses; keep credentials, rendered Compose and HBA rollback files out of Git. **Reuse the installed writable role and its existing private credential; do not provision the role or generate a replacement password.** The 2026-11-11 live audit verified correct/wrong passwords from the candidate IP, superuser rejection there, and the new role's rejection from another IP and local socket. The tunnel helper validates a private temporary config, locks cooperating invocations, rejects concurrent edits, creates a mode-0600 backup and changes only the expected origin line. It does not restart the tunnel.

```sh
set -euo pipefail
umask 077
export STAGE="$PWD/reports/runs/issue15-osaka-sidebyside-20261110/candidate"
export PROJECT=issue15-osaka-prod
export COMPOSE=deploy/osaka-rails-production/compose.rollout.yml
export CUTOVER_COMPOSE=deploy/osaka-rails-production/compose.cutover.yml
export RW_ROLE_STAGE="$PWD/reports/runs/issue15-osaka-writable-role-20261111"
export SETTINGS=/opt/osm-sandbox/osm-api-sandbox/openstreetmap-website/config/settings.local.yml
export RAILS_IMAGE=sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332
export PREFLIGHT_IP='<existing-private-guarded-IP>'
export CUTOVER_IP='<reviewed-distinct-unused-IP>'
export OTHER_TEST_IP='<reviewed-second-unused-IP-for-auth-test>'
export OSAKA_SUBNET="$(docker network inspect osm-api-sandbox_default --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
python3 - "$PREFLIGHT_IP" "$CUTOVER_IP" "$OTHER_TEST_IP" "$OSAKA_SUBNET" <<'PY'
import ipaddress, sys
preflight, cutover, other = (ipaddress.IPv4Address(value) for value in sys.argv[1:4])
assert len({preflight, cutover, other}) == 3
subnet = ipaddress.IPv4Network(sys.argv[4])
assert all(address in subnet for address in (preflight, cutover, other))
PY
test "$(docker inspect issue15-osaka-prod-candidate-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')" = "$PREFLIGHT_IP"
test "$(docker compose --env-file "$STAGE/compose.env" -p "$PROJECT" -f "$COMPOSE" config --services)" = candidate
test -z "$(docker network inspect osm-api-sandbox_default --format '{{range $id,$c := .Containers}}{{println $c.IPv4Address}}{{end}}' | rg -F "$CUTOVER_IP/")"
test -z "$(docker network inspect osm-api-sandbox_default --format '{{range $id,$c := .Containers}}{{println $c.IPv4Address}}{{end}}' | rg -F "$OTHER_TEST_IP/")"
```

The executed sequence rechecked and snapshotted the seven original OSM/user/OAuth counts and both original container identities immediately before candidate recreation. The candidate paused briefly on port 3003 during recreation, while the old public service continued on port 3002.

Live provisioning was completed under the separate 2026-11-11 approval. **Do not rerun the credential generator, role provisioner or HBA installer.** The private audit records the exact commands and rollback file. Before candidate recreation, the executed check verified the existing role, private credential and HBA guard matched the approved state.

```sh
python3 - "$RW_ROLE_STAGE" "$CUTOVER_IP" <<'PY'
from pathlib import Path
import importlib.util, stat, subprocess, sys
stage, ip = Path(sys.argv[1]), sys.argv[2]
for name in ('role.password', 'pg_hba.rollback'):
    path = stage / name
    assert path.is_file() and not path.is_symlink()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
spec = importlib.util.spec_from_file_location('cutover_hba', 'deploy/osaka-rails-production/cutover_hba.py')
hba = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hba)
hba.verify_rules('osm-api-sandbox-db-1', ip)
actual = subprocess.run(['docker', 'exec', '-u', 'postgres', 'osm-api-sandbox-db-1', 'cat', hba.HBA], capture_output=True, text=True, check=True).stdout
assert actual == hba.block(ip) + (stage / 'pg_hba.rollback').read_text()
PY
test "$(docker exec osm-api-sandbox-db-1 psql -X -U postgres -d openstreetmap -Atc \
  "SELECT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls FROM pg_roles WHERE rolname='osm_rails_cutover_rw'")" = t
docker exec -i osm-api-sandbox-db-1 psql -X -U postgres -d openstreetmap -At <<'SQL' | python3 -c 'import sys; assert sys.stdin.read().splitlines()==["55", "35", "f|f|f|f|f|f|f"]'
SELECT count(*) FILTER (WHERE has_table_privilege('osm_rails_cutover_rw',format('%I.%I',schemaname,tablename),'SELECT') AND has_table_privilege('osm_rails_cutover_rw',format('%I.%I',schemaname,tablename),'INSERT') AND has_table_privilege('osm_rails_cutover_rw',format('%I.%I',schemaname,tablename),'UPDATE') AND has_table_privilege('osm_rails_cutover_rw',format('%I.%I',schemaname,tablename),'DELETE')) FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','ar_internal_metadata','spatial_ref_sys');
SELECT count(*) FILTER (WHERE has_sequence_privilege('osm_rails_cutover_rw',format('%I.%I',schemaname,sequencename),'USAGE') AND has_sequence_privilege('osm_rails_cutover_rw',format('%I.%I',schemaname,sequencename),'SELECT')) FROM pg_sequences WHERE schemaname='public';
SELECT has_database_privilege('osm_rails_cutover_rw','openstreetmap','TEMP'),has_schema_privilege('osm_rails_cutover_rw','public','CREATE'),has_table_privilege('osm_rails_cutover_rw','public.schema_migrations','INSERT'),has_table_privilege('osm_rails_cutover_rw','public.ar_internal_metadata','INSERT'),has_table_privilege('osm_rails_cutover_rw','public.spatial_ref_sys','INSERT'),has_table_privilege('osm_rails_cutover_rw','public.geography_columns','INSERT'),has_table_privilege('osm_rails_cutover_rw','public.geometry_columns','INSERT');
SQL
```

The existing `openstreetmap` login and HBA paths stay unchanged. The new role grants broad application DML on 55 current tables, read-only access to five metadata/reference tables and views, and USAGE/SELECT on 35 sequences. The initial live provisioner also granted DML on two PostGIS metadata views; those grants were immediately revoked and the corrected provisioner was reapplied with the existing credential. All five are now read-only. The role cannot own objects or run migrations. The complete login/OAuth/API edit and storage flow passed on a disposable restore with this exact role; no such test has been run against Osaka.

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

If a trigger fires, the operator restores the exact pre-cutover ingress file and restarts the tunnel in an interactive SSH terminal; the helper refuses rollback if someone has edited that file for another reason. Confirm the old 3002 service through the HTTPS hostname. Keep the candidate available until the failure is reviewed; stopping it is a separate candidate-only action. Preserve the private tunnel backup and candidate stage through the rollback window. Traffic rollback does not remove the dedicated database role or HBA guard.

```sh
set -euo pipefail
sudo python3 /home/ljlambert2/projects/osm-address-import/deploy/osaka-rails-production/switch_tunnel_route.py rollback /etc/cloudflared/config.yml
sudo systemctl restart cloudflared
sudo systemctl is-active --quiet cloudflared
sudo cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

No database migration, schema change or change to the old web was part of the cutover, so tunnel rollback returns traffic to the old service. Two manual sandbox iD edits were observed after the switch; route rollback will not undo them or later account, OAuth and OSM edits. Before any later rollout, confirm the source/image revisions, HBA and tunnel rollback files and service-manager access on the real host. Existing database backups remain preserved but are not a deployment gate.
