# Dry-run building conflation contract

## Inputs

Install `requirements-conflation.txt` into an isolated Python environment and
run `PYTHONPATH=src python -m osm_address_import.building_conflation --help`.
The engine accepts either:

- `--input-format candidate-csv`: UTF-8 CSV, one row per candidate, with the
  version 1.0 columns below. This is the common interface for an Address
  Intelligence export or a direct government adapter. The upstream assessment
  is evidence only; the engine independently checks current OSM objects.
- `--input-format nad-geojson`: a bounded GeoJSON query from the official NAD
  feature layer. The adapter maps NAD Release 24 fields to the same internal
  candidate envelope. It does not assume a NAD point is a rooftop.

Required columns: `schema_version`, `candidate_id`, `source_dataset`,
`source_record_id`, `source_dataset_version`, `source_license`,
`source_permission_status`, `house_number`, `street_name`, `city`, `state`,
`zip_code`, `latitude`, `longitude`, `crs`, `source_location_type`,
`positional_accuracy_m`, `original_source_attributes`.

Optional columns: `street_prefix`, `street_suffix`, `unit`,
`upstream_assessment`. The final two JSON-valued columns are
`original_source_attributes` (required object) and `upstream_assessment`
(optional object). Empty optional values remain empty. `crs` must be
`EPSG:4326`; coordinates are longitude and latitude in separate fields.
The house number may include a suffix. Unit is a separate field and is part of
address identity. Source license and permission status must be recorded even
when approval is pending. A `PENDING_OSM_REVIEW` status never authorizes an
upload.

OSM input is an Overpass `out meta` JSON extract with complete referenced
nodes and relation member ways, or an OSM API v0.6 `map` XML response. The
extract is read only. Capture it at the time of the run; the map API's bounded
response includes IDs, versions, tags and references. A missing or invalid
building geometry is excluded from update eligibility.

## Decisions

Each source row has exactly one primary decision. Invalid input and repeated
or inconsistent source addresses are handled first. Equivalent OSM addresses
are matched by normalized house number, street, and unit and must be on the
associated building or at effectively the same location. Remaining candidates
are grouped by building. A group with distinct addresses or units enters
review. Existing conflicting OSM address values enter conflict review. Only a
single, distinct, building-level address with an unambiguous interior point,
boundary clearance, appropriate source placement, known accuracy, nearby OSM
street context, complete versioned building geometry, and no conflicting
tags can receive `AUTO_ATTACH_CANDIDATE`.

Default distances are 4 m for association search, 3 m minimum interior
boundary clearance, 5 m maximum source accuracy, and 20 m maximum duplicate
search radius. Duplicate acceptance additionally requires the equivalent OSM
object to belong to the building or be within 4 m of the source point. These
thresholds are arguments to the Python `run` function and are recorded in the
report. No percentage score or nearest-building selection is used.

## Outputs

All six required files are produced in `--output`:

- `source_manifest.json`: source and OSM hashes, providers, dates, source URL,
  OSM URL, study bounds, and thresholds.
- `import_assessment.json` and `.md`: mutually exclusive row counts,
  building and OSM-only counts, processing time, warnings and limitations.
- `proposed_building_updates.json`: dry-run update records. Each stores the
  candidate and source lineage, target OSM type/ID/version, original and
  proposed tag dictionaries, added tags, geometry and references, OSM metadata,
  match evidence, reason codes, validation and license status, and
  `execution_authorized: false`.
- `manual_review.json` and `.geojson`: one record per nonautomatic source row,
  with its point, decision, reasons, candidate buildings, OSM addresses,
  conflicts, and recommended review action. Invalid coordinates produce null
  GeoJSON geometry.

`validation_sample.json` is an additional reproducible sample: up to three
rows per decision, sorted by candidate ID. `OSM_ONLY` is an observation about
OSM features in the selected study scope, not a source row decision.

All real source and OSM files and all generated run artifacts belong under
ignored `reports/runs/`, `data/`, or `downloads/`; do not commit addresses or
bulk extracts. Only synthetic examples and code belong in the public Git tree.

## Review and eventual execution

Load `manual_review.geojson` and the OSM XML in QGIS or JOSM. For each sampled
row, inspect the source metadata and point semantics, building footprint,
nearby street, existing address-bearing nodes and ways, and any units or
entrances. Record a reviewer decision separately. The sample is unreviewed
until a person completes that check.

A later executor must re-fetch the exact OSM type and ID, verify current
version, tags and geometry, re-check duplicates, confirm source permissions,
review and community gates, then construct an API v0.6 modify operation.
This module has no API execution path.
