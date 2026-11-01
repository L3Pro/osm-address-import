# OSM Address Import — Master Plan v1.0

**Status:** Draft for project and community review  
**Date:** 2026-10-30  
**Proposed repository:** `L3Pro/osm-address-import` (public)  
**First supported data source:** U.S. National Address Database (NAD)  
**Initial pilot:** One Texas county, selected after source and OSM coverage profiling  
**Production OSM editing:** **Not authorized by this plan.** Requires all release gates below.

## 1. Mission

Build an open-source, reproducible, community-accountable pipeline for identifying missing addresses in OpenStreetMap (OSM), safely matching authoritative address points to existing OSM objects, producing reviewable edits, and routing ambiguous cases to human mappers.

NAD is the first data source, not a permanent limit on the architecture. Correctness, preservation of existing OSM contributions, and local community trust matter more than upload volume.

### Primary outcome

Demonstrate an end-to-end **dry-run** for at least **1,000 Class A candidate address matches** in one Texas county, with full lineage, independent QA, sandbox verification, and no unintended changes. Live editing is a separately gated activity.

## 2. Scope

**In scope for v1**
- Ingest a pinned NAD release and current OSM address/building data for a selected county.
- Normalize and profile address fields; report invalid, incomplete, duplicate, and unit/subaddress records.
- Detect existing OSM addresses on nodes, buildings, entrances, POIs, and other relevant objects before creating candidates.
- Produce conservative, explainable **Class A** matches between one authoritative address and one suitable OSM building.
- Exclude conflicting or ambiguous records; never silently overwrite existing `addr:*` values.
- Generate reviewable candidate manifests, QA samples, sandbox-ready proposed changes, and audit reports.
- Develop MapRoulette tasks for human-review categories, subject to appropriate community consultation.
- Document import permissions, community feedback, batch policies, and rollback/stop controls.

**Out of scope for v1**
- Unattended national or statewide imports.
- Automatic edits for apartment/unit addresses, multiple-address buildings, parcels, interpolation, or ambiguous street assignments.
- Building geometry replacement, deleting OSM objects, mass retagging, or overwriting mapper-contributed address data.
- Automatically creating standalone address nodes wherever no building match exists.
- Treating failed Class A matches as proven missing OSM addresses.
- Uploading any changes to production OSM before permission, consultation, and QA gates have been satisfied.
- Incorporating proprietary employer data or code into the public project.

## 3. Guiding principles and non-negotiable invariants

1. **Preserve OSM first:** V1 may only propose adding approved missing address tags to an existing eligible building, without altering geometry, unrelated tags, or history.
2. **Fail closed:** Ambiguity, uncertain coordinates, conflict, missing provenance, or stale OSM objects cause a rejection or manual-review classification.
3. **Duplicate-safe:** Search across relevant OSM address representations, not merely tags on the enclosing building.
4. **Explain every decision:** Persist the rule version, source-record ID, relevant OSM IDs/versions, evidence, and reason codes.
5. **Reproducible:** The same pinned inputs and configuration must produce the same candidate identifiers and classifications.
6. **Idempotent and restartable:** Re-running a batch must not create a second address or repeat an already applied update.
7. **No production default:** The uploader must be disabled for live OSM by default, with explicit environment and human authorization checks.
8. **Community governance:** An internal test or successful match is not permission to perform a live import.

## 4. Proposed technical architecture

```text
Pinned NAD release + metadata ─────┐
                                  ├─> Staging / normalization / profiling
Current OSM snapshot + updates ───┘                 |
                                                    v
                                         Existing-address index
                                                    |
                                                    v
                                         Spatial + semantic conflation
                                                    |
                                    ┌───────────────┴────────────────┐
                                    v                                v
                              Class A candidates               Exception queue
                                    |                                |
                                    v                                v
                           Manual QA + audit samples         MapRoulette / manual review
                                    |
                                    v
                           Sandbox proposal + diff tests
                                    |
                                    v
                          Community & release gates
                                    |
                                    v
                        Controlled live pilot (only if approved)
                                    |
                                    v
                         Reconciliation + monitoring
```

**Proposed stack (validate during foundation spike):** Python 3, PostgreSQL/PostGIS, `osmium`/OSM PBF processing utilities, SQL, `pytest`, Docker Compose, GitHub Actions; JOSM for independent inspection and manual validation. Version-lock all dependencies after proof of concept. Use the existing private OSM API sandbox if its operational state and isolation are reverified; the sandbox infrastructure is not assumed to be part of this repository.

**Pipeline artifacts:** `source_manifest.json`, profiling reports, `candidate_matches` (Parquet/GeoPackage or database), `candidate_decisions` with reason codes, `review_sample.csv`, `proposed_changes.osc`, `sandbox_validation.json`, `batch_manifest.json`, `reconciliation.json`. Exact formats will be pinned in schemas and tests.

## 5. Class A matching contract (proposed, to be frozen after testing)

A record qualifies for Class A only when **every** applicable condition holds:

- A valid, in-scope source record with a complete house number and street (or documented local equivalent), usable coordinates, source metadata, and no identified source duplicate.
- The source point falls unambiguously within exactly one suitable, valid OSM building footprint, not close enough to an edge/overlap to create a geometry ambiguity under defined tolerances.
- The building and its relevant nearby/contained OSM objects contain no existing same-address representation, conflicting address values, or evidence of multiple addresses/units.
- The building is a plausible recipient of a single building-level address; complex structures and multi-tenant cases are excluded.
- Source street identity is independently credible using available reference data and local naming rules. **Never infer an address solely from the nearest road.**
- There is no competing candidate for the same OSM building or duplicate normalized address elsewhere in the comparison neighborhood.
- Mapping of NAD fields into approved OSM tags is unambiguous; no existing tags would be overwritten or removed.
- Current OSM state/versions are checked again immediately before any approved upload, and the change is aborted if the assumptions no longer hold.

Class A produces a **candidate**, not an automatically approved edit. Maintain explicit classifications such as `A_CANDIDATE`, `ALREADY_MAPPED`, `MULTIPLE_ADDRESSES`, `EXISTING_TAG_CONFLICT`, `GEOMETRY_AMBIGUOUS`, `STREET_UNCERTAIN`, `SOURCE_INCOMPLETE`, and `MANUAL_REVIEW`.

The final tagging contract, including handling of `addr:street`, `addr:housenumber`, optional `addr:city`/`addr:postcode`, and source attribution, is subject to local community review.

## 6. Execution phases and acceptance gates

### Phase 0 — Governance, source verification, and environment baseline

**Deliverables**
- Public repository with README, license choice, contribution/security guidance, CI skeleton, issue templates, and `docs/` structure.
- Record the exact NAD release and file checksum; verify data origin, permission, ODbL compatibility, relevant restrictions, and schema changes.
- Choose a county based on source quality, OSM coverage, manageable scope, and community input (candidates include Brazoria and Galveston).
- Verify the private OSM sandbox can be rebuilt, seeded, isolated from live OSM, and tested.
- Open early dialogue with relevant OSM contributors before committing to an import-specific workflow.

**Gate G0:** Proven source rights/provenance; working isolated sandbox; documented county rationale; no private keys, restricted data, or credentials in the public repository.

### Phase 1 — Reproducible data ingestion and baseline reporting

**Deliverables**
- Versioned NAD schema adapter and OSM extract loader.
- Normalization rules for house number, street, directional/suffix terms, postcode, and units without lossy guessing.
- Existing-address index including standalone nodes, entrances, building/address tags, POIs, and nearby representations where relevant.
- County baseline report: NAD total, valid, duplicates, units, existing OSM addresses, unaddressed buildings, and source-vs-OSM coverage.

**Gate G1:** Exact commands can recreate inputs and reports from pinned sources. Invalid and duplicate cases are demonstrably excluded, and the processing report reconciles to source row counts.

### Phase 2 — Deterministic conflation engine

**Deliverables**
- Spatial candidate matching plus semantic and duplicate guards.
- Class A rule specification with fixture-based unit tests, reason codes, and evidence fields.
- Exception categories separated by cause; traceable per-record decisions.
- At least **1,000 Class A candidates** in the selected county if the available data supports this. If not, report the actual achievable count and whether the county should change.

**Gate G2:** No proposed Class A candidate requires overwriting OSM address tags, editing geometry, or creating a duplicate address in the fixture suite. Pinned reruns produce identical outputs.

### Phase 3 — Independent QA and sandbox proof

**Deliverables**
- Stratified reviewer sample across neighborhoods, building forms, street patterns, and source-record classes.
- Random sample evaluation, with independent human verification of both address assignment and duplicate status.
- Planned quality target for production consideration: **at least 600 randomly sampled Class A candidates with zero confirmed incorrect assignments**. This is a conservative target, not a substitute for community judgment; a confirmed critical error stops advancement until root-cause analysis and rerun.
- Generate a small, reversible sandbox batch of address-tag-only changes.
- Verify unchanged geometry, object IDs, pre-existing tags, and non-target objects; demonstrate version-conflict rejection, replay idempotency, partial-failure recovery, and audit reconstruction.

**Gate G3:** Independent QA signed off; zero critical errors in accepted sample; zero unintended sandbox diffs; repeatability and stop/recovery tests pass. A sandbox pass does not grant permission for live editing.

### Phase 4 — Formal OSM import proposal and community review

**Deliverables**
- OSM Wiki import plan covering dataset and permissions, exact algorithm, sample output, tagging, reviewers, automation level, QA, geographic scope, dedicated account, changesets, source tags, communication, opt-out handling, and revert plan.
- Discussion with relevant Texas/U.S. OSM communities and a formal OSM Community Forum import-review post.
- Resolve objections and update code, process, or scope accordingly.

**Gate G4:** Local community buy-in; compliant import documentation and discussion; current Import Guidelines review period satisfied (the guidelines specify at least **14 days after the formal review post**, with concerns addressed); dedicated import account and audit/rollback procedures ready. Silence or passage of time alone is not approval.

### Phase 5 — Controlled live pilot (conditional)

**Deliverables**
- Explicitly approved batch size and local geographic partitioning; begin with a small, human-inspected batch.
- Check live OSM state immediately before each upload and abort on version, duplicate, or tag conflicts.
- Track changeset IDs, input hashes, object versions, reviewer sign-off, source information, and resulting diffs.
- Monitor community feedback; pause immediately for suspected systematic error, unexpected rejection, opt-out request, or adverse mapping impact.
- Reconcile every attempted record as `applied`, `already_mapped`, `skipped`, `stale`, `rejected`, or `needs_review`.

**Gate G5:** Every live edit is accounted for and independently spot-checked; no unresolved severe issue. Expansion to a second batch or county requires a separate go/no-go decision and any additional community consultation required by scope change.

### Phase 6 — MapRoulette exception review and impact reporting

**Deliverables**
- Group exceptions into actionable categories: plausible missing standalone addresses, multi-address buildings, positional mismatches, OSM conflicts, and low-confidence source records.
- Publish small, clearly instructed MapRoulette challenges only for categories where a human mapper can resolve the task with adequate evidence and appropriate community coordination.
- Provide relevant links to source, OSM feature, and reason for review; allow skip/invalid decisions and prevent regeneration of already resolved tasks.
- Publish an impact report showing address coverage, reviewed and accepted edits, unresolved backlog, false-positive findings, mapper corrections, and future areas.

**Gate G6:** Challenges are tested with mappers, do not describe uncertain candidates as established errors, and can be maintained without reintroducing resolved tasks.

## 7. Suggested repository layout

```text
osm-address-import/
├── README.md
├── LICENSE                      # decide after dependency/license review
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── .gitignore
├── .github/workflows/ci.yml
├── docs/
│   ├── MASTER_PLAN.md
│   ├── DATA_SOURCES.md
│   ├── CLASS_A_RULES.md
│   ├── QA_PLAN.md
│   ├── IMPORT_PROPOSAL.md
│   ├── COMMUNITY_REVIEW.md
│   └── adr/
├── configs/
├── src/osm_address_import/
│   ├── ingest/
│   ├── normalize/
│   ├── conflation/
│   ├── qa/
│   ├── export/
│   └── reconcile/
├── sql/
├── schemas/
├── tests/fixtures/              # synthetic or license-cleared samples only
├── tools/
└── reports/examples/            # small, privacy-reviewed outputs
```

Do not commit full NAD downloads, complete OSM extracts, unreviewed address exports, secrets, database dumps, authentication tokens, or non-public employer material. Document how to fetch public source data reproducibly instead.

## 8. Initial GitHub issue backlog (suggested)

| ID | Issue | Milestone | Acceptance summary |
|---|---|---|---|
| 01 | Bootstrap public repo, docs, CI and safety defaults | G0 | Clean checkout/tests; no live write path enabled |
| 02 | Record NAD release, permission, checksum and schema | G0 | Source manifest and rights memo reviewed |
| 03 | Audit and isolate OSM sandbox | G0 | Rebuild/read/write/rollback tests documented |
| 04 | Select Texas pilot county and create baseline | G0–G1 | County decision and source/OSM coverage report |
| 05 | Build NAD adapter and field-normalization fixtures | G1 | Deterministic normalization; rejection codes |
| 06 | Build OSM address/geometry index | G1 | Addresses on all relevant OSM object types identified |
| 07 | Implement Class A matching engine | G2 | Explainable candidates; deterministic tests |
| 08 | Implement conflicts, duplicate and ambiguity guards | G2 | Negative fixtures cover no-overwrite invariants |
| 09 | Generate review manifest and QA sampling | G3 | Auditable review and error-rate report |
| 10 | Sandbox diff exporter, dry-run and revalidation | G3 | No unauthorized diffs; stale-version/replay tests |
| 11 | Write OSM Wiki import plan and conduct review | G4 | Documented feedback and all objections addressed |
| 12 | Create controlled pilot upload/reconciliation workflow | G5 | Disabled by default; stop/rollback/run ledger |
| 13 | Generate MapRoulette exception challenges | G6 | Human-tested tasks and deduplication |
| 14 | Publish pilot impact dashboard/report | G6 | Reconciled metrics and known limitations |

**Execution order:** 01–04 in parallel where independent, then 05–06, then 07–08, then 09–10. Community outreach begins during Phase 0; Issue 11 formalizes review when technical evidence is ready. Issue 12 cannot be enabled on production before G4. Issues 13–14 follow the dry-run and community input.

## 9. Metrics and decision dashboard

Report both counts and error rates for every run:
- Source records loaded, rejected, and deduplicated.
- Existing-address coverage in the pilot county.
- Class A count and share of total source records.
- Matches by rejection/exception code.
- Independent QA sample size and confirmed incorrect-match count.
- Number of proposed object modifications, existing tags touched, and geometry modifications (expected geometry changes: **zero**).
- Sandbox batch pass/fail, stale-object conflicts, retries, and idempotency failures.
- For a permitted live pilot: actual applied/skipped/rejected objects, changeset links, mapper feedback, and repairs.
- MapRoulette completed/invalid/skipped tasks and outstanding backlog.

### Stop conditions

Any unlicensed or restricted data, evidence of accidental duplicate creation, overwrite of existing address values, unacceptable false-positive pattern, unreconciled sandbox behavior, production configuration uncertainty, credible community objection, or missing rollback capability blocks progression immediately.

## 10. Decisions still open

1. Exact pilot county (Brazoria vs Galveston or another candidate).
2. Final NAD release/schema and compatible attribution/rights treatment.
3. Tagging policy, including building tags versus address-node cases (v1 proposes building-only Class A).
4. Final spatial tolerances, geometry exclusions, and street-name equivalence rules.
5. Acceptance sampling design and independent-review ownership.
6. Community-agreed production batch sizes, rate limits, and communication plan.
7. Software license (MIT or Apache-2.0 are candidates; verify dependency compatibility before selecting).
8. Whether and how to operate the existing sandbox as reusable public project infrastructure.

## 11. Definition of project success

The **engineering MVP** is successful when a third party can clone the repo, reproduce a county-level analysis, inspect 1,000 explainable high-confidence candidates (if the geography supports that volume), validate a safe proposed OSM change against an isolated sandbox, and understand why every excluded record was excluded.

The **OSM pilot** is successful only if the community-reviewed process leads to a small, auditable live contribution without unintended changes or unresolved adverse effects. A decision **not** to upload because source data or match quality is insufficient is also a responsible outcome.

## References

- OpenStreetMap Import Guidelines: https://wiki.openstreetmap.org/wiki/Import/Guidelines
- OpenStreetMap Automated Edits Code of Conduct: https://wiki.openstreetmap.org/wiki/Automated_Edits/Code_of_Conduct
- OSM address modeling: https://wiki.openstreetmap.org/wiki/Addresses
- U.S. DOT NAD information: https://www.transportation.gov/gis/national-address-database
- U.S. DOT NAD disclaimer: https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer
- MapRoulette challenge creation: https://learn.maproulette.org/en-US/documentation/creating-a-challenge/
- MapRoulette cooperative challenges: https://learn.maproulette.org/en-US/documentation/creating-cooperative-challenges/

---

**Next authorized task:** Issue 01 (repository foundation), followed immediately by Issue 02 (pin source and rights) and Issue 03 (sandbox audit). Do not initiate a production OSM import on the basis of this document alone.
