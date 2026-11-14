# OSM Sandbox Console: secure deployment preparation

This document prepares a separate, read-only console origin at `127.0.0.1:8765` for a future Access-protected `osm-console.mapviewer.ai` hostname. **No external route, Access policy, system account or persistent service is installed by this change.** PR #22 and PR #23 were merged in order; the integrated console code is at `50e9a09a25a5b4c67b43f5fca55f7be84d676de2` on `main`.

## Host audit and boundary

Read-only audit on 2026-11-13 found `main` at `86777d7`, PR #22 open at `f8c7553`, a clean worktree before this branch, and the prior 62-test suite passing. Rails API capabilities returned HTTP 200 on both 127.0.0.1:3002 (rollback) and :3003 (production). `cloudflared.service` was active. Port 8765 had no listener; 3001, 3002 and 3003 were in use. The host had eight cores, about 4 GiB available RAM and 825 GiB free repository disk space. The live `/etc/cloudflared/config.yml` is mode 0600 and unreadable by this account, so its contents and the current Access application/policy cannot be verified here. The host uses systemd units, including cloudflared; no console account exists. Existing unrelated unit configuration should not be copied as a credential-storage pattern.

Phase 1.7 rechecked the merged PRs and found the host account and `/opt/osm-console`, `/etc/osm-console`, and `/var/lib/osm-console/reports` still absent. Noninteractive `sudo` requires an operator password. The existing sandbox redirects unauthenticated requests to `blocnav.cloudflareaccess.com`; that team's public JWKS endpoint returned two RSA keys. This identifies the observed sandbox Access team, **not** a verified issuer or AUD for a new console application. The private tunnel file, Access policies and approved identities remain unavailable to this account. The proposed console hostname does not resolve yet.

An authorized operator can inspect the live ingress without printing credentials or editing it:

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
cloudflared tunnel --config /etc/cloudflared/config.yml ingress rule https://osm-sandbox.mapviewer.ai
cloudflared tunnel --config /etc/cloudflared/config.yml ingress rule https://osm-console.mapviewer.ai
```

Review the existing Access application and policy in the Cloudflare account separately; tunnel ingress does not establish the console application's AUD or allowed identities. Keep the existing sandbox route unchanged and add the proposed console hostname only after separate external-routing approval.

The original Canoas attempt's archived JSON/Markdown error text says "prepared PBF has unresolved references." PR #21's [audited closeout](BRAZIL_SEVEN_CITY_APPEND.md) states that an Osmium output-stream parsing error stopped the attempt before SQL. The architecture document now distinguishes the artifact text from the closeout root cause. Historical files were not edited.

## Authentication and authorization

Production reads the `Cf-Access-Jwt-Assertion` header and verifies its RS256 signature against the configured team's rotating JWKS at `<issuer>/cdn-cgi/access/certs`. The configured issuer must be an HTTPS `*.cloudflareaccess.com` team domain; the configured application AUD tag must match. Signature, issuer, audience, expiry, issued-at, not-before when present, subject and a user email are checked. Missing/invalid assertions return 401; unavailable signing keys return 503; valid identities absent from the role file return 403. Error bodies do not echo tokens. The JWT header can select a key ID but cannot select the algorithm or JWKS URL. Browser-provided email/role headers are ignored. OSM Rails identity is unrelated to this policy. Cloudflare [documents the assertion header, JWKS and key rotation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/); [PyJWT](https://pyjwt.readthedocs.io/en/stable/usage.html) performs the cryptographic and claim checks.

`/etc/osm-console/roles.json` is an explicit server-side allowlist with `viewer` and `administrator` email arrays, loaded at startup. Viewer and Administrator currently have the same GET-only routes. There are no import, request or approval routes. Changes to roles require review and service restart. The `console.env.example` and `roles.example.json` files contain placeholders only. The production WSGI entry point requires `OSM_CONSOLE_ENV=production`, an absolute curated report root, issuer, audience and role file; it rejects `OSM_CONSOLE_DEV_MODE=1`. The old local CLI still requires explicit development mode and loopback binding. Production also checks that the immediate client is loopback, matching the planned local tunnel origin. It does not trust proxy-forwarded identity headers.

`/livez` returns 204 only on loopback and reveals no report details. Authenticated `/readyz` returns only `application: ready` and `reports: available|unavailable`; an absent curated run returns 503. Every other route, including static CSS and downloads, requires an authorized role. The service should not be reachable directly from another host because Gunicorn binds only to 127.0.0.1.

## Curated report publication

The production service must read **only** `/var/lib/osm-console/reports`, never the original `reports/runs` tree. The offline `console_publish` command validates the existing schema-1.0 reports, creates a new run directory, and writes only:

- Sanitized city and historical-attempt JSON/Markdown, with metrics, object accounting, statuses, source metadata, timestamps and code commit retained.
- Sanitized consolidated summary JSON/Markdown.
- Minimal Osaka baseline JSON (counts, capture time and inherited reference-count summary).
- `publication.json`, a local integrity manifest with published-file and source-report SHA-256 values plus the original run ID. The browser cannot download it.

The publisher reconstructs JSON from an explicit field list and regenerates Markdown from that projection. Private manifest paths/content, fixtures, commands, free-form validation evidence, operational logs, PBFs, staging CSVs, dumps and attestation source files are not copied. Published validation evidence is a controlled summary tied to the original report hash; detailed evidence stays in the private audit. Free-form error and warning text becomes a generic notice while counts and statuses remain. This deliberately limits the production UI's failure detail; an operator can consult the private audit for the exact cause. The original source reports stay in place. The command refuses overwriting a published run; a new revision needs review rather than silent replacement. The production repository requires a valid `publication.json` and checks each served file against its hash, as well as the existing path, symlink, size and schema checks.

The source and destination must be separate. Run the command first without `--publish` to review the proposed filename list and source digests, then with `--publish` after approval of those artifacts. The service account receives only read permission on the curated copy. Publication is a human-triggered offline operation, not a worker or sync daemon.

## Prepared service configuration

The proposed [systemd unit](../deploy/osm-console/osm-console.service) runs [Gunicorn](https://gunicorn.org/reference/settings/) as dedicated `osm-console:osm-console` from a root-owned release under `/opt/osm-console/current`, with one worker and two threads. It binds 127.0.0.1:8765, restarts on failure, uses journal logging, caps memory at 256 MiB and CPU at 50%, and uses systemd filesystem/capability restrictions. `ProtectHome=yes` prevents reading the private reports under the home directory. The curated report directory and role file should be root-owned and group-readable by `osm-console`; the service should have no Docker group, database credential, writable source tree, root privileges or import command path. JWKS verification requires outbound HTTPS to the configured team domain. A separate role file and environment file replace inline credentials in the unit.

## Local production-mode verification before any public route

For isolated tests, use a temporary curated copy and synthetic RSA keys, issuer, audience and identities. The test suite covers signature, issuer, AUD, expiry, not-before, unsupported algorithm, missing token, no-role identity, forged headers, roles, downloads, traversal, symlinks and escaped HTML. Start Gunicorn locally on a free loopback port using the same production app factory with a test-only JWKS client; do not use a real Access token. Check:

1. `ss -ltnp` shows only a 127.0.0.1 listener for that process.
2. `/livez` is 204 on loopback; `/` and `/readyz` without an assertion are 401.
3. A signed synthetic Viewer assertion returns 200 for inventory, city, run and approved reports; an unlisted identity returns 403.
4. The curated real run still shows eight areas, seven final Brazil SUCCESS reports, archived Canoas BLOCKED and Atibaia relation 298253.
5. Operational artifacts and traversal paths return 404 after authentication.

This isolated verification is **not** a live Cloudflare end-to-end test. Before production use, the operator must verify that the dedicated service account can start the staged unit and can read only the curated directory; the present development account cannot create that system account or install a unit.

### Executed isolated check on 2026-11-13

The local publisher produced 19 approved JSON/Markdown artifacts plus its private publication manifest from run `20261113-7c4e9a21`. Its strict reader showed eight areas, seven successful final Brazil reports, the archived Canoas BLOCKED attempt and Atibaia relation 298253, with zero warnings. Gunicorn 27.0.1 ran the production app factory on 127.0.0.1:8766 with a synthetic JWKS override confined to a temporary test module. The process ran as unprivileged UID 1000 because `osm-console` does not yet exist; `setpriv` could not switch to UID 65534 (`setresuid` denied). `ss` showed only the loopback listener. HTTP checks returned 204 for local `/livez`, 401 for missing assertions, 200 for signed Viewer inventory/readiness/city/run/approved downloads, 403 for a signed unlisted identity, and 404 for operational artifacts and traversal paths. All eight names, Atibaia relation and Canoas history appeared in authenticated responses. The Gunicorn test process was stopped. This verifies the local production-mode application, **not** the dedicated systemd identity or real Cloudflare authentication.

The full repository suite passed 70 tests after these changes. The proposed unit was checked with `systemd-analyze verify`; it reported the expected missing `/opt/osm-console/venv/bin/gunicorn` executable because no host release has been installed, plus unrelated host unit warnings. Unit installation and restricted-account startup remain explicit operator gates.

## Deployment procedure — operator execution only

Complete the following on the Ubuntu host after reviewing both PRs and choosing an exact release SHA. Commands are examples to review for the host; none are run by this PR.

### Staged local installation helper

After the console code is merged, [the root-only helper](../deploy/osm-console/operator-local-install.sh) implements the local portions of steps 1–5 without touching Cloudflare, Rails or PostgreSQL. It has four separate phases so an operator can review the publication list before copying reports and configure Access values before starting the unit. It never asks for or stores a password. Run it from an operator-controlled root session (do not put secrets on the command line):

```bash
repo=/home/ljlambert2/projects/osm-address-import
sha=50e9a09a25a5b4c67b43f5fca55f7be84d676de2
run="$repo/reports/runs/brazil-seven-cities/20261113-7c4e9a21"
bash "$repo/deploy/osm-console/operator-local-install.sh" prepare "$repo" "$sha" "$run"
# Review the printed filename list and source hashes before the next command.
bash "$repo/deploy/osm-console/operator-local-install.sh" publish "$repo" "$sha" "$run"
```

The helper refuses to overwrite an existing release, virtual environment or curated run. If preparation stops partway through, inspect the partial paths rather than removing them blindly. It confirms that the `osm-console` account has no supplementary groups and cannot read the private source run. It archives only reviewed Git-tracked files, installs pinned console dependencies in a root-owned virtual environment, and verifies every published artifact hash as the service account. The expected current publication is 19 approved artifacts plus a private manifest, eight areas, seven final successes and one archived blocked attempt.

After the operator verifies the actual console Access issuer, audience and approved identities, create `/etc/osm-console/console.env` and `roles.json` from the examples, edit them with an operator-controlled editor, and set both files to `root:osm-console` mode `0640`. Then run:

```bash
bash "$repo/deploy/osm-console/operator-local-install.sh" start "$repo" "$sha" "$run"
bash "$repo/deploy/osm-console/operator-local-install.sh" verify "$repo" "$sha" "$run"
```

The start phase rejects development mode and placeholders, validates the role allowlist, installs only `osm-console.service`, and checks loopback liveness and missing-token rejection. Real Access authentication and a signed authorized Viewer request remain separate acceptance checks. The helper does not configure the external hostname or tunnel.

1. **Release and dependencies.** Create root-owned `/opt/osm-console/releases/<SHA>` from the reviewed Git tree and a `current` symlink. Create `/opt/osm-console/venv` and install `requirements-console.txt` there. Provision `python3-venv` through normal host administration if needed. Keep release and venv non-writable by the service user.
2. **Identity and paths.** Create system account `osm-console` with no login shell or supplementary Docker group. Create `/etc/osm-console` and `/var/lib/osm-console/reports` as root-owned directories. The service account needs traversal/read access only to its role file and curated reports; recommended modes are 0750 for directories and 0640 for files with group `osm-console`. Do not grant access to `/home/ljlambert2/projects/osm-address-import/reports/runs`.
3. **Publication.** From the reviewed release, run `PYTHONPATH=src python3 -m osm_address_import.console_publish --source-run-dir reports/runs/brazil-seven-cities/20261113-7c4e9a21 --destination-root /var/lib/osm-console/reports` as an operator who can read the private source. Review the filenames and source hashes. After reviewing output content, repeat with `--publish`, then set root ownership/group-read modes on the curated run. Do not overwrite the original run or publish the entire `reports/runs` directory.
4. **Configuration.** Copy the placeholder [environment file](../deploy/osm-console/console.env.example) and [roles file](../deploy/osm-console/roles.example.json) to `/etc/osm-console`, insert the *new console Access application* team issuer, audience and exact Viewer/Administrator emails, set root ownership and group-readable mode, and review the files without placing values in Git or a shell command log.
5. **Local service.** Install the [unit](../deploy/osm-console/osm-console.service) as `/etc/systemd/system/osm-console.service`, `systemctl daemon-reload`, then start only `osm-console.service`. Check `systemctl status`, `ss -ltnp`, `curl --noproxy '*' http://127.0.0.1:8765/livez`, memory use and journal output. Confirm Rails 3002/3003 remain healthy. Missing-token requests to inventory must return 401. Validate signed Viewer, Administrator and unlisted-identity cases through the isolated/local authentication procedure before proceeding.
6. **Approval gate.** Stop here. The operator must inspect the existing private tunnel config and Access policies; confirm the intended authorized Administrator and Viewer identities, the new application AUD and issuer, direct-origin binding, rollback backup path, and all local tests. Obtain explicit approval for the external hostname, Access application/policy and tunnel route before changing any of them.
7. **External routing after approval only.** Create a dedicated Cloudflare Access self-hosted application for `osm-console.mapviewer.ai` with explicit allow policy and no bypass rule. Make a mode-0600 backup of the current tunnel config, add only the new hostname route to `http://127.0.0.1:8765` above any catchall, validate ingress, then restart cloudflared during an agreed window. Do not modify the existing Rails hostname route. Test unauthorized edge access, authorized Viewer/Administrator browser access, allowed downloads, and both Rails API ports. Do not send production JWTs to logs or test artifacts.

## Rollback

If local startup or authorization fails before routing, stop and disable only `osm-console.service`; leave cloudflared and Rails unchanged. If the approved external route is live and fails, restore the exact saved tunnel config, validate it, restart only cloudflared and verify the existing Rails hostname/API. Then stop the console unit or leave it loopback-only for diagnosis. Revoke or disable the new Access application if required by the operator; do not touch the existing sandbox Access policy. Preserve the curated reports and audit trail for review. Rollback of console routing never changes geographic data.

## Remaining gates

This PR cannot verify the private live tunnel file, the actual Access application/policy, real Access JWTs or a new `osm-console` system account. Those are operator checks at the approval gate. The console is historical audit state, not a live database monitor. No public route should be enabled until both PRs are reviewed, the local restricted-user service starts successfully, and live Access settings are inspected.
