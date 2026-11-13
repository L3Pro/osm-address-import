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

After the append, run the original eight-check read-only smoke and the optional
seven-city fixture extension with `python -m osm_address_import.api_harness
smoke --report REPORT.json --brazil-fixtures config/brazil_api_fixtures.json`.
The extension adds four GET checks per municipality and keeps the Osaka way and
bbox fixtures in the original eight checks. Never enable live `write-e2e`.

## Run-specific outcome

Run `20261113-7c4e9a21` appended all seven cities to the existing live
`openstreetmap` API database. The isolated rehearsal restored a consistent
snapshot of the Osaka database and passed an authenticated Brazilian node edit:
changeset create, upload, version readback, and closure. Authenticated Firefox
opened iD and rendered OSM paths at all seven city centers. This synthetic edit
was confined to the disposable database; no live write test ran.

The following counts are per municipal extract after exclusion of incomplete
relations. The Osaka object counts are the captured pre-import database baseline.
Osaka building and address counts were derived from measured post-import global
feature totals minus the audited unique Brazilian feature insertions; because
the baseline database contained Osaka alone, these equal its preserved feature
counts. The private per-city JSON reports also include raw source counts,
primary versus dependency counts, existing-before and newly-inserted counts,
highway and other feature counts, and manifest checksums.

| Area | Nodes | Ways | Relations | Buildings | Address objects | API | Editor |
|---|---:|---:|---:|---:|---:|---|---|
| Osaka | 1,865,425 | 364,226 | 4,350 | 282,770 | 5,042 | PASS | Staged PASS; live session pending |
| Manaus | 708,993 | 88,005 | 649 | 47,436 | 2,064 | PASS | Staged PASS; live session pending |
| Natal | 214,170 | 43,422 | 1,546 | 10,995 | 3,583 | PASS | Staged PASS; live session pending |
| Canoas | 103,940 | 20,387 | 789 | 8,647 | 963 | PASS | Staged PASS; live session pending |
| Novo Hamburgo | 54,963 | 9,603 | 212 | 1,559 | 1,609 | PASS | Staged PASS; live session pending |
| Itu | 363,107 | 15,720 | 216 | 2,922 | 474 | PASS | Staged PASS; live session pending |
| Jundiaí | 316,759 | 29,437 | 351 | 5,331 | 697 | PASS | Staged PASS; live session pending |
| Atibaia | 278,516 | 14,278 | 156 | 4,408 | 562 | PASS | Staged PASS; live session pending |

The seven transactions added **2,039,406 unique nodes, 220,848 unique ways,
and 3,919 unique relations**. They skipped 1,042 node and four way duplicate
encounters; all matched version and content. There were zero conflicts and zero
failed or rolled-back SQL records. Database size grew from 1,539,599,707 to
3,111,963,995 bytes at the final city audit. Each city report records its own
duration; the consolidated report totals 1,061.512 seconds including a 22.572
second pre-SQL Canoas attempt. That first attempt stopped on an Osmium output
stream parsing error before any SQL was sent. Its `BLOCKED` JSON and Markdown
reports remain archived as `canoas-attempt-1.*`; the corrected city report
records the retry.

Post-import live counts are 3,904,831 current nodes, 585,074 current ways,
and 8,269 current relations. The original 35 users, four OAuth applications,
and nine changesets remain. Three sampled Osaka object content hashes matched
the pre-import baseline after every batch. Current-object sequences equal the
maximum OSM ID in each table, so Rails will allocate above imported IDs.
`osmium check-refs -r` found no missing references in any prepared Brazilian
extract. The live database retained its pre-existing Osaka count of zero
missing way-node references and 72,320 missing relation-member references;
the Brazilian append introduced no additional unresolved references.

The original read-only Osaka smoke passed **8/8** after import. The expanded
Osaka plus seven-city read-only suite passed **36/36**. Live Rails on loopback
port 3003 returned capabilities, representative maps, and sampled node, way,
and relation XML for every city. The public hostname returned the expected
Cloudflare Access authentication redirect. The per-city and consolidated final
audit statuses are `PARTIAL` because a browser authenticated through the live
Cloudflare Access site has not yet been checked. Staged authenticated iD
rendering is recorded with map-request and rendered-path counts in each city
report. A human browser session should verify live login and iD display at the
eight centers before upgrading those editor validations to `PASS`.

Private detailed JSON, Markdown, manifests, screenshots, logs and source
artifacts remain under `reports/runs/brazil-seven-cities/20261113-7c4e9a21/`
and are excluded from Git.

## Completion gate

All seven municipalities must have completed Markdown and JSON import reports
with source provenance, object and feature statistics, before/after comparison,
validation results, timing, and final status. A consolidated seven-city report
must also be generated and verified. This run has those artifacts. Final
`SUCCESS` remains pending a browser session authenticated through the live
Cloudflare Access site for Osaka and the seven city editors.
