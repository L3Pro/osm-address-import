# Quality assurance and release gates

## Independent review

- Reviewer sampling must span neighborhoods, geometries, street types and known edge cases.
- Retain the sampling method, random seed, reviewer, disputed findings and corrections.
- Proposed Gate G3 target: **600 randomly sampled Class A candidates with zero confirmed incorrect assignments**, after class and sampling design are frozen. This is a proposed conservative target, not proof of error-free production behavior.
- One critical error stops progression pending root-cause analysis and re-run.

## Sandbox invariants

- No existing tag value may be changed or removed.
- No object geometry may change.
- No existing OSM object may be deleted, recreated, or replaced.
- Object versions are checked; stale versions cause abort.
- Replays must not create duplicates.
- All changes and exceptions must reconcile to the candidate ledger.
- Test interrupted batches and recoverability.

## Go/no-go gates

G0: legal/source/provenance review, sandbox isolation and county rationale.
G1: reproducible data processing and row-count reconciliation.
G2: no-overwrite and duplicate-negative fixtures; deterministic candidates.
G3: independent QA, sandbox-only diff, recovery/replay/version tests.
G4: OSM Wiki plan, local community buy-in, formal import review, documented objections addressed and required review window elapsed.
G5: small conditional live pilot, complete ledger, independent post-upload verification.
G6: human-reviewed MapRoulette exception handling and impact report.

## Immediate stop conditions

Unlicensed provenance, critical QA error, existing-address overwrite, accidental duplicate, unsupported geometry edit, missing rollback, wrong target, unexpected OSM version, stale source, unresolved community concerns or missing reviewer decision.

Never interpret green CI on the repository scaffold as passing G0 through G6.
