# Building-aware address conflation, sprint 1

The implementation is a separate, offline Python pipeline. It reads a versioned
candidate CSV or bounded NAD GeoJSON, and an OSM Overpass JSON or API map XML
extract, and writes only local dry-run
artifacts. It does not import geography into Rails or use the API harness's
write mode. The existing Brazil import and reporting modules remain intact.

1. A strict adapter validates the candidate envelope and retains original
   attributes and license/provenance metadata. An Address Intelligence export
   uses the same envelope; its assessment fields are retained as evidence only.
2. The OSM reader keeps node, way, and relation identity, version, tags, node
   references, relation members, and coordinates. It builds polygons for closed
   building ways and complete multipolygon building relations. Incomplete or
   invalid geometry cannot receive an update.
3. Spatial association uses projected metre distances and an index. Interior
   points, boundary distance, competing buildings, source location semantics,
   and positional accuracy are evaluated independently. A nearby street name
   is supporting evidence. Proximity alone never selects a building.
4. Address semantics compare house number, street, and unit. Existing OSM
   addresses on buildings, entrances, address nodes, and other address-bearing
   objects are checked. Candidate records are grouped by associated building
   before any automatic decision.
5. The decision engine emits one primary decision per source row. Only an
   eligible single building-level address creates an update manifest entry.
   Other decisions enter a JSON and GeoJSON review queue. OSM-only addresses
   are separate observations.
6. The report records counts, source hashes, capture times, thresholds, and
   limitations. Pilot inputs and outputs belong under ignored `reports/runs/`.

An eventual executor must re-fetch every target, verify object version,
geometry, tags, licensing, review approval, and community process before any
OSM API v0.6 modify operation. Sprint 1 contains no executor.
