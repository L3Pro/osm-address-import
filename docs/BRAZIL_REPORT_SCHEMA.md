# Brazil seven-city import report schema v1.0

`brazil_reports.py` validates and atomically writes JSON and Markdown reports.
JSON `schema_version` is `1.0`. Each city report contains run and baseline IDs,
city/state/relation, source provider/URL/snapshot/download time/file/SHA-256,
tool name/version/command reference, code commit, UTC start/finish, duration,
status, metrics, object accounting, manifest reference and SHA-256, validations,
database sizes, errors, warnings, and retries. `null` means unmeasured or
unavailable, and should have an explanation in the check evidence or warning.

Every metric row has `source`, `existing_before`, `newly_inserted`, and
`final_available`. Raw OSM types are nodes, ways, and relations. Building
features are objects with `building=*` other than `no`, across all three object
types. Address features are objects with at least one `addr:*` tag, across all
three types. Highway features are ways with `highway=*` other than `no`.
`other_features` counts unique objects with any `amenity`, `shop`, `landuse`,
`natural`, `waterway`, or `railway` key. One object can contribute to several
feature rows. Source counts are from the polygon extract before incomplete
relation exclusion; final availability counts only retained objects. Existing
and newly inserted counts are based on the SQL stage at the start of that city's
transaction. Thus `existing_before + newly_inserted = final_available`.

`source_primary` and `source_dependencies` count spatially selected objects and
reference dependencies separately. `already_present` and
`skipped_duplicates` count matching IDs encountered in that city's transaction;
the same global object can be counted as a duplicate in multiple city reports.
`conflicts` count mismatched IDs. A conflict aborts the batch and is never
automatically overwritten. `failed` and `rolled_back` record known object
counts or `null` when the process cannot measure them. The private manifest
contains object type, real OSM ID, version, role, feature classes, and whether
an incomplete relation was excluded.

The critical validation keys are source integrity, boundary, duplicate
conflicts, insertion integrity, references, API node/way/relation reads, a
representative map bbox, feature data, editor, Osaka preservation, database
health, and Rails health. Each has `status` (`PASS`, `FAIL`, `SKIPPED`, or
`NOT_VERIFIED`) and supporting `evidence`. `SUCCESS` requires every critical
check to be `PASS`. Failed imports still produce both file formats.

An explicit operator live-editor attestation may close an editor
`NOT_VERIFIED` check. The private attestation names all eight areas, identifies
its evidence as operator-attested visual inspection, records its receipt time,
and states whether screenshots were supplied to the agent. The closeout keeps
the previous editor validation and resolved warning under `closeout`, changes
only the editor validation and derived city status, and retains import counts,
timestamps, retry history, and staging evidence. Editor `PASS` means features,
aerial imagery, and editing controls were visually available through the live
authenticated site. It does **not** mean a live API write was tested. City
`SUCCESS` still requires every critical check to pass with evidence and no
unresolved error.

The summary includes all seven city statuses, total unique newly inserted
objects, existing/duplicate/conflict/failed/rolled-back totals, cumulative
processing duration, database sizes before/after, Osaka validation status, and
overall status. Global new-object totals sum committed per-city new IDs;
previously inserted shared IDs become duplicates in later cities and are not
counted again. The processing duration includes archived retry attempts; their
statuses and durations appear separately in `retry_attempts`. Secrets, bearer
tokens, passwords, dumps, extracts, and raw
manifests must not be committed or embedded in reports.
The consolidated status becomes `SUCCESS` only when all seven city statuses,
Osaka preservation, and the operator-attested Osaka live editor check pass.
`osaka_editor_validation` and `live_editor_attestation` record that evidence
and explicitly preserve `live_write_verified: false`. `finished_at` remains the
import finish time; `closeout_at` records when the later visual attestation was
received.
