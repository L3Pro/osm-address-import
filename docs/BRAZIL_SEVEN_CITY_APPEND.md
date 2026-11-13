# Seven Brazilian municipalities in the Osaka API sandbox

This run appends OSM objects to the existing Rails API database. It does not use
`osm2pgsql`, replace the database, recreate its volume, or alter Rails deployment,
Cloudflare, accounts, or OAuth configuration. The SQL writes only new OSM current
and history rows and advances current-object ID sequences. It reuses the existing
private Osaka import attribution: changeset `0`, owned by synthetic user `-1`
(`Osmosis Anonymous`). Geofabrik omits original user and changeset metadata; this
attribution must never be presented as the original OSM contributor identity.

## Source and boundaries

The pinned source is [Geofabrik Brazil](https://download.geofabrik.de/south-america/brazil.html),
`brazil-261112.osm.pbf`, replication timestamp `2026-11-12T21:23:05Z`, SHA-256
`8bcb7af1bf98bf29b537ab2d9c8e6471991a7211d9d854141404b3e05b531b9a`.
The source file's completion mtime was `2026-11-13T13:56:45Z`. Geofabrik's MD5
`b4ea925721a7e0b2750c42f2ba3c72d1` matched the downloaded file. The pinned
URL and seven verified relation IDs are in [the city config](../config/brazil_seven_cities.json).

The supplied Atibaia relation `5349573` is a level-9 subarea. The level-8 Atibaia
municipal boundary is relation `298253`, with IBGE code `3504107`. All other
supplied IDs match level-8 municipality names and IBGE codes in the pinned PBF.
Each relation was fetched with `osmium getid -r`, exported as a GeoJSON polygon,
and checked for valid, nonempty geometry. No arbitrary bounding box defines an
extract.

The seven city extracts use Osmium `extract -s smart -S types=multipolygon -p
CITY.geojson`. Osmium retains complete ways and their referenced nodes. Its smart
strategy can leave route and other relations incomplete. `brazil_prepare` retains
only relations whose complete node, way, and relation member graph is present;
it refuses an incomplete municipal boundary. Every excluded relation appears in
the private source manifest with `excluded_incomplete_relation`, and the count
appears in the report. Each prepared PBF must pass `osmium check-refs -r` with
zero missing references. The primary-object classification is: nodes that
intersect the polygon; ways referencing a primary node; and relations with a
primary member. Remaining retained objects are structural dependencies.
Osmium's documented node-based crossing selection is used; it does not infer a
way that crosses a polygon if neither endpoint is inside. This limit is recorded
so later comparisons do not mistake the extract for a geometric clipping result.

## API database append

`brazil_stage` streams prepared PBF objects into eight CSV tables, preserving
real OSM IDs, current versions, UTC timestamps, all tags, and one-based ordered
way and relation members. Node tiles use the deployed `quad_tile` 1.0.1 formula,
verified against an existing Osaka node. `brazil_sql` creates indexed temporary
staging tables, validates every member reference, and compares any pre-existing
ID's current metadata, tags, and ordered references. A mismatched ID aborts the
whole city transaction. Matching shared objects are skipped, including their
history rows, and reported as existing duplicates.

For new objects the transaction inserts current nodes, ways, and relations, all
tags and ordered references, and one historical version with matching metadata.
It verifies existing objects have a corresponding history version. All inserts
and checks run in one city transaction with a 15-minute statement timeout and a
30-second lock timeout. A failed transaction rolls back the city; no existing
objects are updated or deleted. The three current-object sequences are raised
to at least the highest current OSM ID so future Rails-created IDs cannot
collide. The SQL has an exact `openstreetmap` database and synthetic changeset
guard. `brazil_operator` accepts only an exact local Docker DB container name,
checks disk, memory and DB health, and requires an isolated-rehearsal attestation
for live mode. Its API probes only use literal loopback ports `39003` (stage) or
`3003` (live), never the public OSM API.

## Isolated rehearsal

Use a new `osaka-api-harness-YYYYMMDD-8hex` project and the existing
[disposable Compose definition](../deploy/osaka-api-harness/compose.yml). Run
`docker_isolation fresh` before startup. Its DB has a separate project volume
and no host port. Take a consistent `pg_dump -Fc` of the current Osaka database,
restore it only into that disposable DB, and verify Osaka OSM/user/OAuth counts.
The project runs a private copy of the current production Rails source. Clear
copied OAuth records only in the disposable DB before starting its web service.
Provision a short-lived synthetic account/token with
[`provision_stage.rb`](../deploy/brazil-seven-cities/provision_stage.rb), then
verify API reads in Osaka and each Brazilian city and run
`brazil_edit_rehearsal` against one imported Brazilian node. It must create a
changeset, upload a modification, read back the new version and marker, close
the changeset, and read the closed changeset. The live API must never receive
this write test.

## Mandatory reports

Each attempted city gets `CITY.json` and `CITY.md` under
`reports/runs/brazil-seven-cities/RUN_ID/`; the consolidated artifacts are
`summary.json` and `summary.md`. They are atomically written and Git-ignored.
The versioned schema and counting rules are in
[the report schema](BRAZIL_REPORT_SCHEMA.md). Source object manifests and raw
PBF/CSV/dump files remain private and out of Git. A city cannot be `SUCCESS`
while a critical check lacks passing evidence. Browser-only iD rendering must
be marked `NOT_VERIFIED` until an authenticated browser check is done.

## Run-specific outcome

The sanitized outcome and exact per-city figures are added after the staged
and live validations. Private detailed reports remain under `reports/runs/`.
