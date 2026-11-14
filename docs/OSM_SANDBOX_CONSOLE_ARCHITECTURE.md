# OSM Sandbox Console: Phase 0 audit and Phase 1 design

## Current state and audited evidence

Audited on 2026-11-13 from clean `main` at `86777d756a4adce3a60a9bd9bd2185b18523d633`, after fetching `origin/main`. The private run directory `reports/runs/brazil-seven-cities/20261113-7c4e9a21/` was available on this host and remains Git-ignored. It contains schema-1.0 `summary.json`/`.md`, seven final municipality reports in both formats, an archived `canoas-attempt-1` pair, `osaka-baseline.json`, and additional private operational files. The latter are outside the console download allowlist. The report validator is `brazil_reports.validate_city()`; this console reuses it and does not redefine metrics. `brazil_summary.py`, `brazil_baseline.py`, `brazil_finalize_reports.py`, `brazil_operator.py`, the seven-city config, report schema, and their tests were inspected. No report pipeline or Rails files were changed.

The baseline records Osaka counts of 1,865,425 nodes, 364,226 ways and 4,350 relations at capture time `2026-11-13T14:45:55Z`. It records 72,320 unresolved relation-member references and zero missing way-node references. A later consolidated closeout health artifact records Osaka preservation PASS and unchanged unresolved reference counts; the run summary records Osaka preservation PASS and operator-attested editor PASS. Those do not establish an Osaka import time, extract snapshot, boundary ID or Osaka feature counts. Osaka's source provider, snapshot, import date, boundary, buildings, addresses and highways remain unknown or not recorded in the UI. The capture timestamp is labeled as a capture, not an import.

The seven final Brazil city reports have status SUCCESS, including Atibaia relation **298253**. The archived first Canoas report is BLOCKED; its JSON and Markdown error field says "prepared PBF has unresolved references." PR #21's [audited closeout](BRAZIL_SEVEN_CITY_APPEND.md) identifies the underlying event more specifically as an Osmium output-stream parsing error before SQL was sent. Both descriptions are preserved as provenance; the successful retry remains the loaded record. The consolidated run started `2026-11-13T15:02:56Z`, finished importing at `2026-11-13T19:09:57Z`, and closed out visual validation at `2026-11-13T19:47:34Z`. Source snapshot for the inspected Geofabrik Brazil PBF is `2026-11-12T21:23:05Z`, distinct from its download and import times. The closeout is operator-attested visual inspection; no live write test was recorded. The `closeout-live-health.json` artifact was read for this audit but is deliberately not downloadable through the console.

The host reported eight CPU cores, 7.7 GiB RAM (about 4.0 GiB available), and 825 GiB free on the repository filesystem at audit time. Sandbox restrictions prevented `ss` and a direct socket bind during the first port check; port availability must be checked outside the sandbox before a real server run. Flask was not preinstalled, and the system Python lacked `pip` and `ensurepip`; an ignored `.venv` with Flask 3.1.2 was set up without changing system packages. There is no existing repository web framework convention. Existing Python tests use `unittest` and `PYTHONPATH=src`.

Deployment documentation identifies production Rails on loopback port 3003, original Rails on 3002, PostgreSQL in Compose, and Cloudflare Tunnel/Access at the public sandbox hostname. The production route configuration under `/etc/cloudflared` is private and was not readable here; its current routing and Access policy cannot be directly reverified by this console audit. No Rails, database, Docker, tunnel, Access, backup or rollback state was changed.

## Phase 1 service boundary

```
Browser on host loopback
  → Flask + Jinja console (127.0.0.1:8765)
  → read-only ReportRepository
  → recognized schema-1.0 city JSON, summary JSON, Osaka baseline
  → allowlisted city/summary JSON and Markdown downloads

No database connection, Docker socket, shell execution, OSM API calls or importer access.
```

The console is a small companion application independent of Rails. `console_data.py` discovers run directories under configurable `OSM_CONSOLE_REPORT_ROOT` (default `reports/runs`) using a schema-1.0 adapter for the existing `brazil-seven-cities` report family. It does not hard-code seven city slugs as the complete inventory. New format families require explicit adapters and reviewed geographic identity fields. Paths, sizes, schemas and city identity are checked. Malformed reports are skipped with visible warnings. Reports are parsed per request; discovery is confined to the recognized report family and small JSON files, avoiding the large manifests and PBF data. There is no startup database or geographical computation. A future deployment should mount only a curated read-only report directory, with no database credentials or Docker socket.

Loaded inventory is selected by `(country, verified OSM relation ID)` and the latest successful final city report for that identity. A later BLOCKED or FAILED report stays in history and cannot erase a successful loaded record. Import attempt chronology is separate from loaded state. An area without a successful audit is labeled NOT VERIFIED; the original Osaka import status is NOT RECORDED. A successful city report requires every critical validation to pass under schema 1.0. The city table keeps `source`, `existing_before`, `newly_inserted`, and `final_available` separate. `null` displays Unknown. Feature classes overlap, and shared objects can occur in multiple city extracts; the UI does not sum per-city final counts into a whole-database total. The run page displays only the already-audited `unique_newly_inserted` run value.

## Access and report security

Phase 1 has only an explicit loopback development mode. The CLI refuses a non-`127.0.0.1` bind, requires `OSM_CONSOLE_DEV_MODE=1`, and rejects `OSM_CONSOLE_ENV=production`. Every browser route checks that the mode is enabled and `REMOTE_ADDR` is loopback. Default application construction fails closed with HTTP 403. Browser-supplied Cloudflare identity headers are not trusted. No production authentication is implemented, so this version must not be publicly routed.

Artifacts use server-resolved run and report identifiers, not browser paths. Only validated city reports (including archived attempts) and recognized summary JSON/Markdown are downloadable. Files must be inside the configured root, regular, not symlinks, at most 1 MB, and free of credential-like content. Markdown is served as `text/plain`, with no Markdown-to-HTML rendering. HTML uses Jinja autoescaping. Responses use `no-store`, `nosniff`, a restrictive Content Security Policy, frame denial, and no referrer. Private manifests, `.env`, logs, dumps, extracts, staging files and operational attestation sources are never registered as artifacts. The service should run as a dedicated unprivileged account with read access only to approved reports in any later hosting plan.

## Local operation

From repository root, install the optional dependency in an ignored virtual environment and check port 8765 is free:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-console.txt
OSM_CONSOLE_DEV_MODE=1 PYTHONPATH=src .venv/bin/python -m osm_address_import.console_app \
  --host 127.0.0.1 --port 8765 --reports-root reports/runs
```

Open `http://127.0.0.1:8765/` on the same host. On Ubuntu systems lacking `python3-venv`, install that system package through normal host administration before creating the venv. For this audit, the venv was created with `--without-pip` and bootstrapped locally because system Python lacked `ensurepip`. No background service is installed. If reports are unavailable, the inventory is empty; HTTP routes do not fall back to live Rails or PostgreSQL.

## Future hosting and authentication decision

Prefer a separate `osm-console.mapviewer.ai` hostname behind a separate Cloudflare Access application over `/admin/imports` on the Rails hostname. It separates origin routing, policy, cookies, and operational failure domains. Deployment requires separate review and approval; no tunnel or Access policy changed in Phase 1.

The future production service must verify Cloudflare Access JWT assertions server-side using pinned expected issuer, audience, signature keys and algorithm, expiration and not-before checks. It must reject untrusted identity headers and fail closed if keys or policy are unavailable. An OSM Rails account alone must grant no console access. Application authorization should map verified identity to at least **Viewer** (inventory/history/approved reports) and **Administrator** (future import approval and execution permission management). Phase 1 implements neither production JWT verification nor Administrator powers. A deployment task must test proxy boundary and direct-origin rejection before exposure.

## Limitations and Phase 2 backlog

The reports establish historical audited state, not current live health or whether data changed after the run. A Phase 1 page can be stale if reports are missing or newer unreported changes occurred. Summary schema validation is narrower than city schema validation; add an upstream summary validator before new report families are supported. Osaka has no independently recorded import provenance or feature counts. The existing consolidated editor attestation reports visual availability and explicitly lacks a live write test. This console does not independently verify production Access policy, current tunnel config, or current database contents.

Proposed self-service workflow state sequence: `requested → previewing → awaiting_approval → queued → executing → verifying → reporting → completed`. Validation failures should enter `blocked` or `failed`; cancellation is allowed before execution and requires a controlled stop during execution; recovery after restart must reconcile the durable job state against audit and database evidence before retry. A partial commit must never be silently retried. Future refreshes require non-destructive impact checks. This is design only: no forms, job tables, workers or queues exist in Phase 1.

Independently reviewable follow-up tasks:

1. Curate and mount approved report artifacts read-only under a dedicated account; add a report publication manifest and a summary schema validator.
2. Add production Cloudflare Access JWT verification, explicit Viewer/Administrator role mapping, direct-origin rejection and deployment tests.
3. Deploy the companion service at a separate Access-protected hostname with resource limits and observability; retain a loopback-only origin.
4. Add municipality request and boundary preview with source attribution and resource estimation, without execution.
5. Add durable job records, idempotency and duplicate protection, approval and cancellation transitions.
6. Add a restricted sequential worker with disk/RAM/time/object-count limits, restart reconciliation and existing-pipeline audit output.
7. Add notification delivery and non-destructive refresh impact checks.

The long-term console remains separate from commercial address comparison, conflation and import-product logic.

## Phase 1.5 addendum

The dependent [secure deployment preparation](OSM_CONSOLE_SECURE_DEPLOYMENT.md) adds production Cloudflare Access JWT verification, explicit read-only roles, curated report publication, a Gunicorn/systemd proposal and a deployment approval gate. The Phase 1 local-mode description above remains the historical architecture of PR #22; the separate Phase 1.5 runbook describes current production preparation. External routing and live Access policy changes remain unexecuted.
