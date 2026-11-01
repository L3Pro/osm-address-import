# Class A candidate contract — proposed v0

**Candidate is not permission to edit.** This rule set is subject to fixture-based validation and OSM community review.

## Positive requirements — ALL must hold

1. NAD record in the approved geography; complete house number and credible street; valid coordinate, source identity, provenance, and no source duplicate.
2. Point unambiguously within **exactly one** appropriate and valid OSM building polygon; exclude footprint overlaps and uncertain edge proximity.
3. Building is a credible single-address recipient; exclude apartments, multi-tenant complexes, multiple units, multi-address properties, and complex footprints where address placement is uncertain.
4. No duplicate or conflicting address already mapped on the building, its entrances, contained nodes, nearby address nodes, POIs, or other relevant OSM representations.
5. No other candidate competes for the same building or normalized address in the search neighborhood.
6. Independently credible street identity; **never silently choose nearest road**.
7. Proposed change can add approved missing address tags **without overwriting** any existing tag, changing geometry, replacing objects, or changing history.
8. Live state must later be revalidated using current object version and duplicate scans before any separately approved edit.

## Decision categories

- A_CANDIDATE
- ALREADY_MAPPED
- SOURCE_INCOMPLETE
- SOURCE_DUPLICATE
- EXISTING_TAG_CONFLICT
- MULTIPLE_ADDRESSES
- GEOMETRY_AMBIGUOUS
- STREET_UNCERTAIN
- OSM_STATE_STALE
- MANUAL_REVIEW

Decisions must carry machine-readable reason codes and evidence, not only a binary pass/fail.

## Draft tag policy

Potential tags include addr:housenumber and addr:street; addr:city and addr:postcode only if independently supported and the community approves. Avoid inventing OSM tags for NAD bookkeeping. The final translation, spatial tolerances and duplicate radius remain **TBD**, with tests and local mapper input required.

## Negative fixtures that must exist before Gate G2

- Existing identical address node inside building
- Existing conflicting address tags on building
- Multiple NAD points inside one building
- Shared/overlapping building polygons
- Point exactly on boundary
- Unit/apartment/multi-tenant structure
- Street mismatch or uncertain street designation
- Source duplicates and nearby normalized OSM duplicates
- Stale OSM version or changes to related address objects
- Rerun of identical input (stable candidate IDs and decisions)
