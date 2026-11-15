# Private MapViewer export for a dry-run conflation report

The exporter reads a completed run and writes local GeoJSON layers under its
`mapviewer/` directory. It never calls an OSM API or Rails. For the Woodlands
pilot, run from the repository root after installing
`requirements-conflation.txt`:

```bash
export PYTHONPATH=src
python -m osm_address_import.export_conflation_geojson \
  --run-dir reports/runs/woodlands-sprint1
```

The exporter finds the source and OSM inputs in `data/` by the SHA-256 values
in `source_manifest.json`, combines the primary decisions in
`manual_review.json` and `proposed_building_updates.json`, and checks them
against `import_assessment.json`. It does not rerun conflation or change a
decision. The output directory is ignored by Git. Do not commit or publish the
GeoJSON, CSV, ZIP, source records, or review notes; they contain identifiable
addresses.

## Layers

| File | Woodlands features | Meaning |
| --- | ---: | --- |
| `already_mapped.geojson` | 3 | Equivalent OSM address exists |
| `auto_attach_candidates.geojson` | 0 | Eligible dry-run building updates |
| `review_multiple_addresses.geojson` | 2 | Multi-address or unit review |
| `review_no_building.geojson` | 23 | No plausible existing building |
| `review_spatial_ambiguity.geojson` | 193 | Spatial or evidence review |
| `review_conflicts.geojson` | 0 | OSM address conflict |
| `source_duplicates.geojson` | 0 | Duplicate source records |
| `source_invalid.geojson` | 0 | Invalid source records |
| `source_evidence_only.geojson` | 105 | Subset of spatial review, blocked only by source placement or accuracy |
| `osm_buildings.geojson` | 292 | Actual OSM footprints from the buffered extract |
| `osm_addresses.geojson` | 10 | Existing address-bearing OSM objects from the buffered extract |
| `review_sample.geojson` | 20 | Stable stratified validation selection |
| `study_area.geojson` | 1 | Exact pilot bbox |

The eight primary layers sum to 221 input records. The 105 evidence-only
features are repeated from `review_spatial_ambiguity.geojson` for convenient
styling; they are not additional addresses. Empty layers remain valid
FeatureCollections. Address point properties are flat and omit the original
NAD attribute payload. OSM footprints retain Polygon or MultiPolygon geometry,
including interior holes. The exported coordinate system is WGS84/EPSG:4326.

`layers_manifest.json` records each file's description, feature count,
drawable count and size, the input checksums, validation results, and stable
sample IDs. `review_template.csv` has one row per source candidate, including
source-invalid records that cannot be drawn. Human review fields start blank.
Copy the template to a separate working file before entering reviews; the
exporter refuses to overwrite a modified template. `geojson_layers.zip` is a
local convenience bundle of the GeoJSON layers only.

## MapViewer procedure

Open MapViewer and add each desired `.geojson` file as a separate layer. Start
with `study_area.geojson` and `osm_buildings.geojson`, then add
`osm_addresses.geojson` and the primary decision layers. Style each decision
layer with a different color and keep `source_evidence_only.geojson` as a
separate highlight. Load `review_sample.geojson` to inspect the deterministic
sample. Compare each point with the footprint, any entrance or address-bearing
OSM object, the reason codes and source evidence. Record the result in a copy
of `review_template.csv`; reviewer decisions do not alter machine results.

The sample selects up to five IDs from each of five strata: source-evidence
only, near but outside, no building, multi-address, and already mapped. It
orders IDs by a fixed SHA-256 key, then removes repeated selections. The
manifest records the exact selected IDs and criteria for reproduction.

The export validates exact primary counts, the evidence-only subset, source
and OSM checksums, building IDs/versions and geometry, WGS84 coordinates,
unique IDs, empty collections and null-geometry accounting. It emits no API
operations and makes no changes to the Rails sandbox.
