# The Woodlands dry-run pilot, 2026-11-14 CST

The study box is `-95.486,30.158,-95.476,30.168` (west, south, east,
north), in The Woodlands, Montgomery County, Texas. The OSM map query used a
0.0005-degree buffer. No Texas geography was inserted into Rails. The existing
sandbox inventory only verifies Osaka and seven Brazilian cities; it provides
no verified Woodlands baseline. The read-only OSM API map endpoint supplied a
current independent extract with object IDs, versions, node references and
relation members.

## Source selection and rights

The pilot uses a bounded query from the [USDOT NAD public feature layer](https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services/Address_Points_from_National_Address_Database_view/FeatureServer/0),
whose description says the data were compiled on 2026-09-30 (Release 24).
The 221 queried records identify `NAD_Source=State of Texas` and
`AddAuth=Houston-Galveston Area Council`. All 221 report
`Placement=Unknown`; none supply a numeric positional accuracy field in this
query. The query response uses EPSG:4326 coordinates. The bounded response was
309,552 bytes with SHA-256
`ff2a8d79f1d2e53bda75b187e852a7ba7e0d1a9fe72d961518dc5629d3898ce1`.
This is a service query, not a checksum of USDOT's full TXT release archive.

The [TNRIS Montgomery County service](https://services5.arcgis.com/31BCS2lamGqYG8ea/arcgis/rest/services/Montgomery_County_Address_Points/FeatureServer)
describes a July 2023 acquisition from H-GAC, so it is older than the NAD
service used here. The [MCECD address view](https://www.arcgis.com/home/item.html?id=cf0e391af4fb490ba99bb75dde1a92db)
describes monthly updates but restricts access to authorized public-safety
stakeholders. Neither was used to fill missing NAD placement evidence.

USDOT's [NAD disclaimer](https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer)
describes the compiled federal work as open and reusable, while explaining
that state and local providers contribute data and warning about completeness.
Texas contributor rights and ODbL compatibility have not been independently
approved for an OSM upload. The source permission status in this run is
`PENDING_OSM_REVIEW`; this sprint performs analysis only.

## OSM extract and reproducibility

The [OSM API v0.6 map](https://wiki.openstreetmap.org/wiki/OpenStreetMap_API)
was fetched from:

`https://api.openstreetmap.org/api/0.6/map?bbox=-95.4865,30.1575,-95.4755,30.1685`

Its local capture timestamp is `2026-11-15T05:30:54Z` UTC. The XML response
was 1,701,207 bytes, SHA-256
`cc69cf2b269a2930b6ea0396c607ceb239606d45972c6bbe1f25316203729001`.
Individual object timestamps differ from this extract capture time. Current
OSM content may change after capture; an executor must re-fetch it.

To reproduce, query the NAD layer for the study envelope with
`geometryType=esriGeometryEnvelope`, `inSR=4326`,
`spatialRel=esriSpatialRelIntersects`, `outFields=*`, `outSR=4326`, and
`f=geojson`. Save the response under ignored `reports/runs/woodlands-sprint1/data/nad-source.geojson`.
Save the OSM map response under ignored
`reports/runs/woodlands-sprint1/data/osm-map.osm`. Then run:

```bash
PYTHONPATH=src .venv/bin/python -m osm_address_import.building_conflation \
  --candidates reports/runs/woodlands-sprint1/data/nad-source.geojson \
  --input-format nad-geojson \
  --osm reports/runs/woodlands-sprint1/data/osm-map.osm \
  --output reports/runs/woodlands-sprint1 \
  --study-area 'The Woodlands, Montgomery County, TX' \
  --bbox=-95.486,30.158,-95.476,30.168
```

The run's ignored `source_manifest.json` records the actual URLs, hashes,
timestamps and thresholds. The report and review artifacts are also ignored
because they contain identifiable address records. Do not commit them.

## Measured findings

| Measure | Count |
| --- | ---: |
| Source records / valid addresses | 221 / 221 |
| Already mapped | 3 |
| Automatic building attachments | 0 |
| Multi-address building review | 2 |
| No-building review | 23 |
| Conflict review | 0 |
| Spatial-ambiguity review | 193 |
| Source duplicates / invalid | 0 / 0 |
| Valid OSM buildings in buffered extract | 292 |
| Existing address-bearing buildings | 10 |
| Invalid OSM building geometry | 1 |
| OSM-only address observations inside study box | 2 |
| Proposed OSM modifications | 0 |

The two multi-address records refer to one building. The spatial categories
below are mutually exclusive and sum to all 221 source rows:

| Spatial relationship | Records |
| --- | ---: |
| Inside exactly one building | 167 |
| Inside multiple buildings | 0 |
| On a building boundary | 0 |
| Near a building but outside its footprint | 31 |
| No plausible building within 4 m | 23 |
| Not spatially evaluated | 0 |

Of the 167 inside one building, **105** were blocked only by unknown source
placement and missing numeric positional accuracy. Another 58 interior
records had additional spatial review conditions, mainly boundary clearance
or street context; two were already mapped and two required multi-address
review. The 193 spatial
reviews include unknown placement, boundary proximity, outside points, and
competing building candidates. No point was promoted from
`Placement=Unknown` to rooftop based on containment alone. The prior pilot
count of 20 with no plausible building rose to 23 after an exact distance
filter fixed spatial-index bounding-box hits near interior holes and other
nonintersecting geometry; those three records moved from spatial review to
no-building review. Source and OSM input checksums did not change.

The 0/218 automatic candidate fraction is a **proxy among unmapped valid unique
source addresses**, not the requested percentage of verified genuinely missing
addresses. That verified percentage is unknown until a human reviews a sample.
No automated accuracy rate is claimed. The report's
`validation_sample.json` selects up to three records per observed decision,
sorted by candidate ID. In QGIS or JOSM, load the review GeoJSON and the OSM
XML, inspect each point against the building and source attributes, and record
whether the address and representation are correct. Synthetic tests cover
automatic, conflict and duplicate decisions absent from this small real box.

## Sprint 2 prerequisites

Obtain source-specific placement or accuracy evidence for a bounded subset;
review Texas contributor rights and OSM community requirements; manually
validate representative decisions; then build a separately authorized executor
that re-fetches targets and tests API modify operations in an isolated sandbox.
