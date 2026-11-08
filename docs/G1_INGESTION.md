# G1 synthetic address ingestion contract

This is an **offline foundation for Issue #5**, not a parser for the uninspected NAD Release 24 archive. It makes no OSM request and produces no OSM edits. The CLI requires a manifest marked `synthetic`; it cannot prove that a caller's data is synthetic, so callers must use synthetic or explicitly cleared fixtures only. Source rights and the Texas pilot county remain open in Issues #2 and #4.

## Verified publisher facts and unresolved schema

The [USDOT R24 text dataset page](https://data.transportation.gov/dataset/National-Address-Database-NAD-Text-File/fc2s-wawr) identifies a `TXT.zip` resource, compilation date September 30, 2026, and a sample attachment. It says `OID_` values are unique but the physical row order is not numeric. The [USDOT minimum content requirements](https://www.transportation.gov/gis/national-address-database/minimum-content-requirements) describe address number, street, subaddress, city/place, county, state, ZIP, geolocation, unique ID, authority/source, and date as desired content. They do **not** establish the exact R24 TXT column names, types, delimiter, encoding, null representations, coordinate order, or release-specific provenance. No R24 bytes were acquired for this work.

The synthetic contract below uses *assumed* field names and CSV encoding so the decisions can be tested now. It does **not** map `OID_` or any other R24 field. After rights review, inspect the exact archive and sample, pin SHA-256 and extracted-file hashes, verify CRS and county attribution, then implement a separately versioned R24 adapter. Never label a copied or changed file as approved based on a release name alone.

## Input contract (`synthetic-address-v1`)

`--input` is UTF-8 CSV with a unique header. Required columns are `source_record_id`, `source_authority`, `house_number`, `street_name`, `locality`, `state`, `county_id`, `longitude`, and `latitude`. Optional columns are `pre_directional`, `street_suffix`, `post_directional`, `unit_type`, `unit_id`, and `postcode`. Extra columns are preserved verbatim in `original`; they do not affect comparisons. A required column must exist in the header; blank required values receive a row-level rejection. `source_record_id` is an opaque source-local ID, not an ordering key.

`--manifest` is JSON with `schema_version`, `source_name`, `release_id`, lowercase `sha256` of the exact CSV bytes, `rights_status: "synthetic"`, `state: "TX"`, `county_id`, `crs: "EPSG:4326"`, and `bbox: [min_lon,min_lat,max_lon,max_lat]`. The file hash must match before any row is processed. The bbox and county ID in the fixture are synthetic; a bbox is **not** a county polygon. A future real adapter needs an approved county boundary source, timestamp, hash, and explicit point-in-boundary policy. A matching county label alone is not a geographic proof.

Each row needs source ID, authority, house number, street name, locality, state, county ID, and numeric WGS84 longitude/latitude. The postcode is optional but checked if present. A unit type and unit ID must be supplied together. The `source_authority` field records a row's stated authority; it does not prove legal rights or accuracy. Future R24 ingestion must also retain upstream authority/source/date/placement metadata where the verified schema provides them.

## Comparison rules

Original CSV strings are kept in every output record. Comparison fields collapse whitespace and fold **ASCII** case. They retain punctuation, diacritics, house-number leading zeros, street-name words, and unit-ID leading zeros. No street name is parsed, expanded, transliterated, or inferred from a nearby road. Thus `North` and `N` are equivalent only in a dedicated directional column; `Road` and `RD` only in the suffix column; `Apartment` and `APT` only in the unit-type column. `St John` and `Saint John`, `0012` and `12`, and unit `01` and `1` remain distinct. Unknown direction, suffix, and unit-type values are retained literally for later review rather than guessed.

Postcodes are either five digits or five plus four separated by a hyphen; the comparison value retains the full string. A postcode difference for the same address identity is a conflict. The address identity key is state, county, locality, house number, directional components, street name, suffix, and unit type/ID. It deliberately excludes postcode and coordinate, which are compared as conflicting evidence. Identical address identity, postcode, and coordinate values from different source IDs yield one accepted record and `SOURCE_DUPLICATE` for the rest, with a stable lexical source-ID tie-break. Different coordinates or postcodes reject the entire identity group as `ADDRESS_CONFLICT`. Repeated source IDs with different raw rows reject the entire ID group as `SOURCE_ID_CONFLICT`; exact repeated rows retain the first and reject later copies as `SOURCE_DUPLICATE`.

Accepted unit records remain separate and carry `unit_present: true` and `class_a_source_exclusion: "UNIT_PRESENT"`. A non-unit record carries `class_a_source_exclusion: null`; this **does not** mean it qualifies for Class A. Geometry, OSM address coverage, street credibility, local rules, and community review are outside this sprint.

## Rejection codes and output

| Code | Meaning |
| --- | --- |
| `SOURCE_ID_MISSING` | No source-local identifier |
| `PROVENANCE_MISSING` | No stated source authority |
| `SOURCE_INCOMPLETE` | Required address or scope field blank |
| `INVALID_HOUSE_NUMBER` | House number does not begin with a digit or has unsupported characters |
| `INVALID_POSTCODE` | Supplied postcode does not match the explicit U.S. fixture format |
| `UNIT_INCOMPLETE` | Only one of unit type and ID is present |
| `INVALID_COORDINATES` | Unparseable, non-finite, or out-of-world coordinate |
| `OUT_OF_SCOPE` | State/county mismatch or coordinate outside configured bbox |
| `SOURCE_DUPLICATE` | Repeated source row or same normalized address and evidence |
| `SOURCE_ID_CONFLICT` | One source-local ID represents different raw rows |
| `ADDRESS_CONFLICT` | Same normalized address has competing coordinate/postcode evidence |

The command writes sorted `accepted.jsonl`, `rejected.jsonl`, and `reconciliation.json`. Each decision has a SHA-256 `record_id`, original field map, release/source ID, authority, input hash, logical CSV row number, and rule version. Accepted rows also carry normalized fields and coordinates for future conflation. Rejected rows carry a reason code; rows that passed field validation also retain their normalized form. The record ID hashes source name, release, input hash, logical row number, and raw row. It is stable for **identical pinned input bytes and configuration**; a changed or reordered input intentionally changes IDs. Reconciliation enforces `input = accepted + rejected`; `duplicates` and `conflicts` are subsets of rejected, not extra rows.

Run from the repository root:

```sh
PYTHONPATH=src python3 -m osm_address_import.ingest \
  --manifest tests/fixtures/synthetic_manifest.json \
  --input tests/fixtures/synthetic_addresses.csv \
  --output output/g1-synthetic
python3 -m unittest discover -s tests -v
```

`output/` is Git-ignored. The checked-in example contains fictional addresses only. Do not commit real-address output, NAD archives, OSM extracts, or operational secrets.

## Dependencies before real R24 loading

Issue #2 must establish the exact archive URL, bytes and checksum, actual TXT schema and CRS, Texas upstream provenance, redistribution terms, and an ODbL compatibility decision. Issue #4 must select an approved pilot county and pin its boundary and OSM baseline. A real R24 adapter then needs schema-specific parsing, authoritative geographic filtering, source/date/placement fields, and fixture tests derived from a rights-cleared sample. The OSM address index and Class A engine belong to later issues; this G1 foundation does not certify the full Gate G1.
