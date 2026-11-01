# Codex handoff — Gate G0 repository and sandbox verification

**Status:** Ready to hand to a coding agent running in the actual GitHub checkout / Ubuntu sandbox environment. This is not authorization to use any production OSM endpoint.

## Mission

Complete the **technical evidence collection** for [Issue #1](https://github.com/L3Pro/osm-address-import/issues/1) and [Issue #3](https://github.com/L3Pro/osm-address-import/issues/3), if the required host access exists. Do **not** implement the NAD conflation engine, import uploader, or any unrelated feature.

## Allowed access

- Work from `https://github.com/L3Pro/osm-address-import`, branch `main`, with a fresh feature branch `g0-foundation-sandbox-audit`.
- Read-only inspection of sandbox host configuration is permitted if authorized access is available. Do not print credentials or internal endpoints in public logs.
- Use only an **isolated, independently validated local test sandbox**, never live OSM.
- Do not assume any prior private OSM sandbox still exists, is correctly configured, or is isolated merely because an HTTPS domain responds.

## Task A — Issue #1 (fresh checkout + CI verification)

1. Clone or fetch repo; report base commit and clean working tree.
2. Run `python -m unittest discover -s tests -v` without secrets and network access; report actual results.
3. Inspect `.github/workflows/ci.yml` and Github Actions run result for **main**. Record a link to a successful run, or explicitly record no run/permissions blocker.
4. Review README links, MIT license versus actual dependency licenses, `.gitignore`, and workflow least privileges.
5. Inspect main branch protections/rulesets. Never silently weaken protections.
6. Add a succinct verification entry to `docs/FOUNDATION_VALIDATION.md` with commands and evidence.

## Task B — Issue #3 (safe sandbox discovery and audit)

1. Identify host, runtime, Rails API, database, Docker/Podman topology (if any), network boundaries and OSM-related accounts **without publishing secrets**.
2. Confirm that test API writes cannot route to `api.openstreetmap.org`, even through redirect, env fallback, proxy, DNS alias or Cloudflare Tunnel. Fail closed if any ambiguity.
3. Confirm sandbox is backed by a distinct database and dedicated test identities; record backups and restore mechanism.
4. If safe, create a disposable test environment or restore snapshot. Use **synthetic fixtures only** for test writes. Record readback, stale version rejection, and rollback/rebuild evidence.
5. Do not overwrite or reset existing sandbox data without an approved backup and explicit authorization. Do not alter a live or shared service.
6. Document installation/rebuild and verification procedure in `docs/SANDBOX_AUDIT.md`, with scrubbed results and specific remaining blockers.

## Stop conditions

STOP immediately and report if you find production OSM credentials or routes, cannot confirm database isolation, the checkout differs unexpectedly, destructive operations are required, or any non-public data might be committed.

## Required delivery

- One focused PR against `main`; do not push directly to main.
- Evidence for each checklist item, exact commands and test logs (sanitized).
- Identify closed vs open acceptance criteria separately.
- Update `docs/STATUS.md`, the two GitHub issues and relevant docs.
- Do not claim Gate G0 is complete until source release rights/provenance (#2) and pilot geography (#4) also pass.

**Do not launch parallel coding agents or begin further sprints.** Final response must include PR URL, results, unresolved risks, and the next bounded action.
