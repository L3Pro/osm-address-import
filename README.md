# OSM Address Import

**Status: planning and foundation. No OSM production import is approved or implemented.**

Open-source tooling for carefully evaluating and conflating authoritative address datasets with OpenStreetMap (OSM), starting with the U.S. National Address Database (NAD). The goal is trustworthy, reproducible, reviewable address improvements — not maximum upload volume.

## What this project will do

- Profile and normalize a **pinned** authoritative address release and current OSM data.
- Detect already-mapped addresses and duplicates before proposing anything.
- Identify conservative **Class A** building-level address candidates, with reasons and source evidence.
- Produce inspectable QA samples, candidate manifests, and sandbox-only proposed changes.
- Route suitable ambiguous cases to human mappers (potentially via MapRoulette).
- Document community consultation, live-import gates, changeset audits, and stop/revert procedures.

## Current state

The repository now includes a **synthetic-only G1 ingestion foundation**, not a working NAD importer. The real Release 24 adapter, OSM index, conflation engine, QA results, sandbox uploader, MapRoulette generator, and community authorization **do not yet exist here**. See [Status](docs/STATUS.md), [Master Plan v1](docs/MASTER_PLAN.md), and the open [issues](https://github.com/L3Pro/osm-address-import/issues).

## Non-negotiable safety rules

1. **Never run unattended imports into production OSM.** Production write paths are out of scope for the current scaffold.
2. Preserve existing tags, geometry, object identities, and OSM history; the initial proposed Class A operation is additive address tags only.
3. Reject ambiguous geometry, conflicting or existing address information, multiple addresses/units, uncertain street assignments, stale versions, or unknown provenance.
4. Each candidate must be explainable and reproducible using pinned inputs and stable reason codes.
5. **No live changes before documented source rights, local community buy-in, OSM import review, and an explicit separate go/no-go decision.**

## Starting points

- [Full master plan and milestones](docs/MASTER_PLAN.md)
- [Architecture and artifact boundaries](docs/ARCHITECTURE.md)
- [Class A candidate contract](docs/CLASS_A_RULES.md)
- [Data-source and license verification](docs/DATA_SOURCES.md)
- [Independent QA and stop conditions](docs/QA_PLAN.md)
- [OSM import proposal template — NOT submitted](docs/IMPORT_PROPOSAL.md)
- [Community review status](docs/COMMUNITY_REVIEW.md)
- [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## Repository development

The Python code includes a sandbox endpoint guard and an offline synthetic address staging pipeline. Run its tests without credentials or real datasets:

    python -m unittest discover -s tests -v

No NAD downloads, complete OSM extracts, output address lists, API credentials, or employer-proprietary data belong in this repository. See the [data policy](docs/DATA_SOURCES.md).

To reproduce the synthetic G1 reconciliation:

```sh
PYTHONPATH=src python3 -m osm_address_import.ingest \
  --manifest tests/fixtures/synthetic_manifest.json \
  --input tests/fixtures/synthetic_addresses.csv \
  --output output/g1-synthetic
```

The output reports 14 input rows, 5 accepted, 9 rejected, 1 duplicate, and 2 conflicting-address rows. See the [G1 schema and normalization contract](docs/G1_INGESTION.md) for field assumptions, reason codes, and limits. No actual NAD data has been loaded.

## OSM governance

Read the [OSM Import Guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) and [Automated Edits Code of Conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits/Code_of_Conduct) before proposing an import. Publishing this repository is **not** OSM permission to import.

## License

Software source code is distributed under the [MIT License](LICENSE). Source datasets, OSM data, generated results, and third-party materials carry **their own** rights and obligations; they are not relicensed by this repository.
