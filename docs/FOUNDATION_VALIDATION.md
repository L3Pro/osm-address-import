# Foundation validation log

## 2026-10-31

- GitHub repository `L3Pro/osm-address-import` exists and is public.
- Foundation commit `fcf32ccb0178f2759a637e58888567a8cf338b06` includes documentation, CI definition, tests, and **no OSM uploader**.
- GitHub `main` source and test files were retrieved for review.
- Reconstructed the two version-controlled `test_safety.py` tests and the matching `safety.py` source in a temporary local directory. Executed `python -m unittest discover -s tests -v` with **2 tests passing**.
- These tests check that explicit HTTP loopback URLs are accepted and common remote/production URLs are rejected. They are **not** proof that a sandbox API is isolated or that every hostile URL is rejected.
- GitHub commit combined status contained no published statuses at the time of this review. The available workflow-run query returned no PR-triggered runs. **GitHub Actions success has not been independently verified.**
- No remote sandbox read/write/restore operation was attempted.
- No production OSM operation was attempted.

## Still required to close Issue #1

1. Check the GitHub Actions tab and confirm an actual successful main-branch run.
2. Perform a clean clone/checkout with the standard test command (beyond reconstructed local files).
3. Check GitHub branch protection/rulesets for main and document maintainers' approval policy.
4. Check README links and repository visibility/permissions.
5. Document accepted license choice and dependence/license compatibility changes as they arise.

See [Issue #1](https://github.com/L3Pro/osm-address-import/issues/1).

## 2026-11-07 — independent G0 checkout and foundation review

Base `main` and clean feature-branch start: `ab6cf7bd0b7e2b812b4fd1eca4514b187218f8e9`. The branch was `g0-foundation-sandbox-audit`; `git status --porcelain=v1` was empty before edits. A fresh public GitHub clone into `/tmp/osm-address-import-g0-fresh-checkout` resolved to the same commit and had an empty porcelain status. The initial sandboxed clone failed DNS resolution; the permitted retry succeeded.

Commands on the fresh checkout:

```text
git clone --branch main --single-branch https://github.com/L3Pro/osm-address-import.git /tmp/osm-address-import-g0-fresh-checkout
git -C /tmp/osm-address-import-g0-fresh-checkout rev-parse HEAD
git -C /tmp/osm-address-import-g0-fresh-checkout status --porcelain=v1
python3 -m unittest discover -s tests -v
```

Result: both `test_explicit_loopback` and `test_production_osm_is_rejected` passed (`Ran 2 tests`, `OK`) in the fresh checkout and on the working branch. The handoff's literal `python -m unittest discover -s tests -v` failed with `python: command not found` on this host; `python3` ran the same suite. The tests need no credentials or network. The guard performs URL validation only; it does not send requests or prove network isolation.

GitHub Actions: [successful `main` run 42427648368](https://github.com/L3Pro/osm-address-import/actions/runs/42427648368), completed against the same base SHA. `.github/workflows/ci.yml` runs the offline unit tests and checks required documents. It sets workflow `contents: read`, with no write permission. Third-party checkout/setup actions use major version tags rather than immutable commit SHAs; pinning is a separate supply-chain hardening item.

Repository review: all 13 relative README links resolve to tracked local files. The external GitHub issues link and both OSM Wiki links were reachable; the [Import Guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) and [Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits/Code_of_Conduct) resolved to their intended pages. The repository contains no uploader, production OSM credential, or production write workflow. Current Python runtime imports use the standard library only, so there is no declared third-party runtime dependency whose license conflicts with the repository's MIT `LICENSE`. This does **not** settle NAD/OSM data rights (Issue #2). `.gitignore` already excludes credential patterns and common data directories; this audit added common flat-file address exports. Ignore rules are a guardrail, not proof that sensitive files cannot be committed.

Branch governance: GitHub's `main` branch response reports `protected: false`; the repository and inherited ruleset lists are empty. The direct protection endpoint returned HTTP 403 (`Resource not accessible by integration`), so detailed protection settings could not be inspected or configured through this connection. A maintainer should require PR review and the `unittest` check through repository settings; no protection was changed during this audit.

**Closed evidence:** fresh clean checkout, offline tests, successful `main` CI, README local links, workflow permissions, software dependency inventory. **Open acceptance:** enforced branch review/check policy and independently confirmed protection settings. Issue #1 should remain open until that policy is enabled or a deliberate manual exception is documented. Gate G0 also depends on Issues #2, #3 and #4.
