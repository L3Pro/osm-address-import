# Project status

**Updated 2026-11-07. This document distinguishes verified repository work from future work.**

| Workstream | State |
| --- | --- |
| Public repository, master plan, governance docs | Established |
| Offline sandbox URL guard unit tests | 2 tests passed in a fresh clean GitHub checkout with `python3` |
| CI workflow on main | [Successful run 42427648368](https://github.com/L3Pro/osm-address-import/actions/runs/42427648368) verified |
| Main branch protection and clean checkout | Clean checkout verified; review/check policy remains open |
| NAD candidate | **R24, compiled 2026-09-30, publisher identified** |
| NAD file acquired and SHA-256 pinned | Not done |
| Dataset rights/provenance / ODbL review | Pending |
| Pilot county | Brazoria/Galveston candidates; not selected |
| Sandbox isolation/rebuild | Read-only audit performed; write isolation and restore acceptance remain open |
| Rails/iD map performance | Read-only local baseline captured; optimization remains in Issue #15 |
| NAD loader and normalization | Not built |
| OSM address index | Not built |
| Class A engine and guard fixtures | Not built |
| QA and actual candidate counts | Not collected |
| Sandbox changeset exporter | Not built |
| OSM Wiki/community consultation | Not started |
| OSM production upload | Not authorized and not implemented |
| MapRoulette challenge generator | Not built |

- [Foundation validation record](FOUNDATION_VALIDATION.md)
- [Public sandbox audit summary](SANDBOX_AUDIT.md)
- [Rails/iD read-only performance baseline](RAILS_PERFORMANCE_BASELINE.md)
- [Source investigation and release candidate](DATA_SOURCES.md)
- [Pilot county scorecard](PILOT_COUNTY.md)
- [Open execution issues](https://github.com/L3Pro/osm-address-import/issues)

Gate G0 is **open**. Source rights/provenance (#2), pilot geography (#4), repository review policy (#1), and sandbox isolation/restore proof (#3) remain to be completed.
