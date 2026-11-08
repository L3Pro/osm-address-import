"""Pinned synthetic CSV contract. Real NAD R24 columns are not yet verified."""

import csv
import hashlib
import io
import json
from pathlib import Path


SCHEMA_VERSION = "synthetic-address-v1"
REQUIRED_COLUMNS = frozenset({
    "source_record_id", "source_authority", "house_number", "street_name",
    "locality", "state", "county_id", "longitude", "latitude",
})
OPTIONAL_COLUMNS = frozenset({
    "pre_directional", "street_suffix", "post_directional", "unit_type",
    "unit_id", "postcode",
})


class SchemaError(ValueError):
    """Input contract or source pin is invalid."""


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SchemaError("Manifest must be an object")
    for key in ("schema_version", "source_name", "release_id", "sha256",
                "rights_status", "state", "county_id", "bbox", "crs"):
        if key not in manifest:
            raise SchemaError(f"Manifest missing {key}")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise SchemaError("Only the synthetic-address-v1 adapter is implemented")
    if manifest["rights_status"] != "synthetic":
        raise SchemaError("This adapter accepts synthetic data only")
    for key in ("source_name", "release_id", "county_id"):
        if not isinstance(manifest[key], str) or not manifest[key].strip():
            raise SchemaError(f"Manifest {key} must be nonempty text")
    if manifest["state"] != "TX" or manifest["crs"] != "EPSG:4326":
        raise SchemaError("This fixture contract requires TX and EPSG:4326")
    digest = manifest["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise SchemaError("Manifest sha256 must be a lowercase SHA-256 hex digest")
    bbox = manifest["bbox"]
    if (not isinstance(bbox, list) or len(bbox) != 4
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in bbox)
            or not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90)):
        raise SchemaError("Manifest bbox must be [min_lon,min_lat,max_lon,max_lat]")
    return manifest


def read_pinned_csv(path: Path, expected_sha256: str) -> list[dict[str, str]]:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SchemaError("Input SHA-256 does not match the manifest")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SchemaError("Input must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise SchemaError("CSV requires a unique header")
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise SchemaError(f"CSV missing columns: {', '.join(sorted(missing))}")
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise SchemaError("Malformed CSV") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise SchemaError("CSV row has an incorrect number of columns")
    return rows
