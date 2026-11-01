# Texas pilot county selection — decision pending

**Status:** Brazoria and Galveston are candidates, not an approved county. Historical Release 22 counts are not Release 24 evidence.

Select the county *after* Release 24 profiling and an up-to-date OSM extract. Start with a small geographically representative subarea for manual QA and sandbox diffs; do not equate county choice with community permission.

## Selection scorecard (proposed; use measured scores)

| Criterion | Weight | Evidence required |
| --- | ---: | --- |
| Source accuracy and address placement metadata | 25% | R24 Texas county profile, source lineage, coordinate anomalies |
| Already-mapped OSM addresses and building inventory | 20% | Pinned OSM extract and point/way/entrance index |
| Plausible one-address / one-building yield | 20% | Conservative non-editing dry-run sample |
| Multi-unit and irregular geometry rate | 15% | R24 unit counts, OSM building complexity |
| Local community context and existing imports | 10% | OSM wiki, community discussion and review feedback |
| Manageability, inspectability and repeatability | 10% | Extract size, review workload, script/test reproducibility |

## Candidate comparison

| County | R24 source profile | Current OSM baseline | Rights/provenance checked | Local feedback | Decision |
| --- | --- | --- | --- | --- | --- |
| Brazoria | PENDING | PENDING | PENDING | PENDING | Not selected |
| Galveston | PENDING | PENDING | PENDING | PENDING | Not selected |
| Other suitable Texas county | PENDING | PENDING | PENDING | PENDING | Not selected |

## Deliverable for Issue #4

One dated, reproducible decision memo with county boundary source, ZIP/PBF checksums, NAD/OSM counts, exclusion estimates, documented uncertainty, local community research, and the selected pilot subarea. Do not publish point-level address contents or claim import authorization.
