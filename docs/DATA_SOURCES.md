# Data sources, licensing, and reproducibility

**Status (2026-10-31): NAD Release 24 is the candidate first dataset, not yet acquired, checksum-pinned, or approved for OSM import. No data has been downloaded into this repository.**

## NAD Release 24: confirmed publisher facts

The U.S. Department of Transportation data portal lists a National Address Database dataset compiled **September 30, 2026**. The official portals currently label these archives:

| Asset | Official dataset landing page | Published filename |
| --- | --- | --- |
| Flat text | https://data.transportation.gov/dataset/National-Address-Database-NAD-Text-File/fc2s-wawr | `TXT.zip` (Release 24) |
| File geodatabase | https://data.transportation.gov/dataset/National-Address-Database-NAD-File-Geodatabase/yw36-suxr | `NAD_r24.gdb.zip` |
| Schema/template | https://data.transportation.gov/dataset/National-Address-Database-NAD-FGDB-Template/ep8g-siwv | `NAD_Template_202310.zip` |
| USDOT terms / download gateway | https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer | Official disclaimer |

Choose the official **TXT** ZIP for the first loader, subject to inspecting the exact data and verifying consistent column types; retain the geodatabase as an independent geospatial/attribute reference if necessary. Do not assume the portal has an immutable URL: capture the exact download response, archive name, bytes and SHA-256 at acquisition time. Do not use the previously profiled **Release 22** figures as current Release 24 coverage counts.

### Release 24 parsing note

USDOT's TXT dataset page explicitly states that `OID_` identifiers are unique but records are stored in optimized physical/database order, **not ordered by OID_**. Do not assume monotonic OID, chronological order, or contiguous IDs. Record IDs should be treated as source-local; the candidate ID must also be scoped to a pinned source release and stable source lineage. A copied file or rerun cannot inherit source approval without hash validation.

### Release approval record — pending

| Field | Value / status |
| --- | --- |
| Candidate release | NAD Release 24; compilation date September 30, 2026 |
| Source download archive | `TXT.zip` from USDOT's linked portal; full final URL to capture |
| Data acquired? | **No** |
| Retrieved date (UTC) | PENDING |
| Source ZIP SHA-256 | PENDING |
| Internal extracted file names / hashes | PENDING |
| Actual column names, encoding, delimiter, null rules | PENDING (inspect publisher's sample/technical note and full files) |
| Coordinate reference system / coordinate order | PENDING verification against actual file |
| Texas-specific provenance and upstream rights | PENDING |
| NAD disclaimer and publisher rights | Reviewed as preliminary evidence only |
| ODbL compatibility for exact dataset | PENDING |
| County boundary and OSM extraction source | PENDING |
| Independent approval and date | PENDING |

## Rights / suitability evidence, not legal clearance

The USDOT [official NAD disclaimer](https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer) calls the release open data and says the federal work is available for reuse, while warning of incomplete coverage and no warranty and saying addresses are not intended for use as a mailing list. Some individual state statutes restrict mailing-list use.

The older [data.gov NAD catalog entry](https://catalog.data.gov/dataset/national-address-database-nad) lists CC0 but was last checked before Release 24. Third-party attribution catalogs may use a separate NAD 'Access and Usage License' label. **Do not silently equate these metadata statements with a legal opinion or permission for OSM's ODbL.** Review the exact release's source permissions and Texas contributors; seek authoritative guidance if any ambiguity remains.

OSM's [Import Guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) require a compatible permission basis, public import plan, local community consultation and formal review. Publisher openness **does not** itself authorize importing into OSM.

## Data and manifests

Never commit full NAD downloads, extracts, OSM PBFs, real-address tables, database dumps, credentials, unreviewed exports, or employer-restricted material. Keep small synthetic/test-only records in version control.

Record, for each pipeline run:
- Publisher URL(s), download time, release ID, SHA-256 and full provenance.
- Schema version, CRS, field map, file sizes/row counts, license decision.
- OSM PBF provider, snapshot UTC, extent/buffer, hash, object versions and update policy.
- Pilot county geometry source, timestamp and hash.
- Code commit, configuration/rule version, rejection counts and run manifest.
- Review and authorization links; status cannot silently transition from pending to approved.

**Next action:** Acquire publisher R24 TXT locally in a quarantined data directory; calculate SHA-256 and inspect sample/header/CRS before designing the ingestion adapter. See [Issue #2](https://github.com/L3Pro/osm-address-import/issues/2).
