# Technical architecture (planned)

## Components

1. Source adapters: pinned NAD and OSM snapshots with metadata/checksums.
2. Staging & normalization: lossless source retention, standardized comparison fields, explicit rejects.
3. Existing OSM address index: nodes, buildings, entrances, POIs and relevant other OSM address representations.
4. Conflation: spatial and street/duplicate checks; deterministic decision records.
5. QA: stratified samples, reviewer decisions, audit manifest.
6. Sandbox exporter: ADDITIVE tag changes to eligible existing building objects only; diff validation and stale-state checks.
7. Community-governed import: **future and separately authorized**; disabled and unimplemented now.
8. Exception queue: MapRoulette-compatible reviews after mapper testing.

## Data flow

    NAD + provenance ----+
                         +--> normalized staged records --> address index --> Class A / exceptions
    OSM PBF + timestamp -+                                           |
                                                                    v
                                                    independent QA and review manifests
                                                                    |
                                                                    v
                                                       isolated sandbox verification
                                                                    |
                                                                    v
                                                community & release gates (NO auto upload)

## Suggested technologies — not yet locked

Python, PostgreSQL/PostGIS, osmium/PBF tools, pytest, JOSM review, GitHub Actions. Versions and external dependencies should be decided in focused issues with reproducible installation instructions.

## Planned output contracts

- source_manifest.json: input URLs, hashes, schema, timestamp, rights checks
- decisions: stable candidate/reason IDs, evidence and exact processing version
- review_sample.csv: sample selection seed and reviewer outcomes
- proposed_changes.osc: sandbox-only at G3
- sandbox_validation.json: tag/geometry/version identity assertions
- reconciliation.json: future approved pilot ledger with counts and changeset references

Schemas must be documented and tested before any implementation claims production readiness.

## Isolation

The existing separately hosted OSM API sandbox is a historical starting point, **not validated by this repository**. Do not point local tests at live OSM, and do not treat a URL alone as proof of sandbox isolation. Verify endpoint, authentication, independent database and destructive-test rollback during Gate G0.
