# Data sources and provenance

**Status: proposed; no release has been pinned or licensed for this project yet.**

## National Address Database (NAD)

Official information: https://www.transportation.gov/gis/national-address-database

Official disclaimer: https://www.transportation.gov/mission/open/gis/national-address-database/national-address-database-nad-disclaimer

USDOT describes the published NAD compilation as available for reuse, but accuracy, source provenance, state-specific restrictions, schema versions, and ODbL compatibility must still be checked for the *exact release and relevant records* before import. The dataset is not suitable for use as a mailing list. This document is not legal clearance.

### Release approval record (complete before downloading for a build)

| Field | Value |
| --- | --- |
| Dataset / release ID | TBD |
| Direct publisher download URL | TBD |
| Date retrieved (UTC) | TBD |
| SHA-256 of original file | TBD |
| Source schema and CRS | TBD |
| Counties / bounds | TBD |
| Provenance or upstream exceptions | TBD |
| Terms, attribution, ODbL review | PENDING |
| Approved by / date | PENDING |

Never infer approval from public availability alone.

## OSM snapshot

Record PBF URL, extract provider, snapshot timestamp, checksum, clipping/buffer policy, and update-diff source. A before-upload comparison must use fresh OSM data and versions, not only a stored extract.

## Data policy for this repository

- **Do not commit** full NAD files, PBFs, raw address tables, database dumps, geocoded personal information, secrets, access tokens, or non-public employer sources.
- Only intentionally small, synthetic or source-permission-cleared QA fixtures may be version-controlled.
- Public example output must be reviewed for licensing, address sensitivity, attribution, and unintended personal detail.
- All computed outputs must be traceable to source hashes, processing version, parameters, OSM extract date, and review decision.
