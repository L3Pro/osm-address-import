# Project status

**Initial status 2026-10-31; G1 update 2026-11-08 below. This document distinguishes verified repository work from future work.**

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
| Sandbox isolation/rebuild | Disposable G0 restore, synthetic API write, stale-version rejection, and rollback passed; private audit retained locally. The existing Osaka sandbox was not used for G1. |
| NAD loader and normalization | Synthetic-only G1 adapter, comparison rules, and reconciliation implemented on `g1-nad-ingestion`; actual R24 schema and rights remain pending |
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
- [Open execution issues](https://github.com/L3Pro/osm-address-import/issues)

The disposable G0 drill is separate from permission to use the existing Osaka sandbox for new writes.

## G1 engineering update — 2026-11-08

Issue #5 now has an offline synthetic fixture adapter with pinned input hash, lossless source-field retention, conservative normalization, duplicate/conflict reason codes, and deterministic reconciliation. The [G1 ingestion contract](G1_INGESTION.md) records verified publisher facts separately from fixture assumptions. This work does not resolve the source-rights or pilot-county gates, does not load R24, and does not implement OSM indexing, conflation, or uploads. The G0 sandbox results are tracked separately from this branch's ingestion work.
