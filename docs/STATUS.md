# Project status

**Initial snapshot 2026-10-31; Issue #15 update 2026-11-08. This document distinguishes verified repository work from future work.**

| Workstream | State |
| --- | --- |
| Public repository, master plan, governance docs | Established |
| Offline sandbox URL guard unit tests | 2 tests passed in locally reconstructed source; CI not yet independently verified |
| CI workflow on main | Workflow committed; **run result not verified** |
| Main branch protection and clean checkout | PENDING |
| NAD candidate | **R24, compiled 2026-09-30, publisher identified** |
| NAD file acquired and SHA-256 pinned | Not done |
| Dataset rights/provenance / ODbL review | Pending |
| Pilot county | Brazoria/Galveston candidates; not selected |
| Sandbox isolation/rebuild | Disposable G0 historical restore, API edit, stale-version rejection, and rollback passed; current backup freshness remains open |
| Rails/iD map performance | Issue #15 disposable development/production mode comparison documented; no Osaka configuration change or CGImap deployment |
| NAD loader and normalization | Not built |
| OSM address index | Not built |
| Class A engine and guard fixtures | Not built |
| QA and actual candidate counts | Not collected |
| Sandbox changeset exporter | Not built |
| OSM Wiki/community consultation | Not started |
| OSM production upload | Not authorized and not implemented |
| MapRoulette challenge generator | Not built |

- [Foundation validation record](FOUNDATION_VALIDATION.md)
- [Source investigation and release candidate](DATA_SOURCES.md)
- [Pilot county scorecard](PILOT_COUNTY.md)
- [Rails/iD map performance investigation](RAILS_PERFORMANCE_BASELINE.md)
- [Open execution issues](https://github.com/L3Pro/osm-address-import/issues)

The Issue #15 performance investigation did not modify the existing Osaka services. A disposable G0 pass is not permission for an OSM production import.
