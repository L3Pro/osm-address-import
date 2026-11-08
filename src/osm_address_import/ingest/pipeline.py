"""Validation, source deduplication, and deterministic reconciliation."""

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from .normalize import address_key, normalize_row
from .schema import load_manifest, read_pinned_csv


RULE_VERSION = "g1-synthetic-v1"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_id(manifest: dict, row_number: int, row: dict[str, str]) -> str:
    lineage = [manifest["source_name"], manifest["release_id"], manifest["sha256"], row_number, row]
    return hashlib.sha256(_canonical(lineage).encode("utf-8")).hexdigest()


def _coordinates(row: dict[str, str], manifest: dict) -> dict[str, float]:
    try:
        lon = float(row["longitude"])
        lat = float(row["latitude"])
    except ValueError as exc:
        raise ValueError("INVALID_COORDINATES") from exc
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("INVALID_COORDINATES")
    west, south, east, north = manifest["bbox"]
    if not (west <= lon <= east and south <= lat <= north):
        raise ValueError("OUT_OF_SCOPE")
    return {"longitude": lon, "latitude": lat}


def _validate(row: dict[str, str], manifest: dict) -> tuple[dict, dict]:
    if not row["source_record_id"].strip():
        raise ValueError("SOURCE_ID_MISSING")
    if not row["source_authority"].strip():
        raise ValueError("PROVENANCE_MISSING")
    if any(not row[key].strip() for key in ("state", "county_id")):
        raise ValueError("SOURCE_INCOMPLETE")
    normalized = normalize_row(row)
    if normalized["state"] != manifest["state"] or normalized["county_id"] != manifest["county_id"]:
        raise ValueError("OUT_OF_SCOPE")
    return normalized, _coordinates(row, manifest)


def ingest(rows: list[dict[str, str]], manifest: dict) -> tuple[list[dict], list[dict], dict]:
    records = []
    for row_number, row in enumerate(rows, start=2):
        record = {
            "record_id": _record_id(manifest, row_number, row),
            "source": {
                "source_name": manifest["source_name"],
                "release_id": manifest["release_id"],
                "input_sha256": manifest["sha256"],
                "source_record_id": row["source_record_id"],
                "source_authority": row["source_authority"],
                "csv_row_number": row_number,
            },
            "original": row,
            "rule_version": RULE_VERSION,
        }
        try:
            record["normalized"], record["coordinates"] = _validate(row, manifest)
        except ValueError as exc:
            record["reason_code"] = str(exc)
        records.append(record)

    valid = [record for record in records if "reason_code" not in record]
    by_source_id = defaultdict(list)
    for record in valid:
        by_source_id[record["source"]["source_record_id"]].append(record)
    for group in by_source_id.values():
        if len(group) < 2:
            continue
        if len({_canonical(item["original"]) for item in group}) > 1:
            for item in group:
                item["reason_code"] = "SOURCE_ID_CONFLICT"
        else:
            for item in group[1:]:
                item["reason_code"] = "SOURCE_DUPLICATE"

    by_address = defaultdict(list)
    for record in valid:
        if "reason_code" not in record:
            by_address[address_key(record["normalized"])].append(record)
    for group in by_address.values():
        if len(group) < 2:
            continue
        evidence = {(_canonical(item["coordinates"]), item["normalized"]["postcode"]) for item in group}
        if len(evidence) > 1:
            for item in group:
                item["reason_code"] = "ADDRESS_CONFLICT"
        else:
            winner = min(group, key=lambda item: (item["source"]["source_record_id"], item["record_id"]))
            for item in group:
                if item is not winner:
                    item["reason_code"] = "SOURCE_DUPLICATE"

    accepted = sorted((item for item in records if "reason_code" not in item), key=lambda item: item["record_id"])
    rejected = sorted((item for item in records if "reason_code" in item), key=lambda item: item["record_id"])
    for item in accepted:
        item["unit_present"] = bool(item["normalized"]["unit_id"])
        item["class_a_source_exclusion"] = "UNIT_PRESENT" if item["unit_present"] else None
    reasons = dict(sorted(Counter(item["reason_code"] for item in rejected).items()))
    report = {
        "schema_version": manifest["schema_version"],
        "rule_version": RULE_VERSION,
        "source_name": manifest["source_name"],
        "release_id": manifest["release_id"],
        "input_sha256": manifest["sha256"],
        "input": len(records),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "duplicates": reasons.get("SOURCE_DUPLICATE", 0),
        "conflicts": reasons.get("SOURCE_ID_CONFLICT", 0) + reasons.get("ADDRESS_CONFLICT", 0),
        "units_accepted": sum(bool(item["normalized"]["unit_id"]) for item in accepted),
        "rejection_reasons": reasons,
    }
    if report["input"] != report["accepted"] + report["rejected"] or report["rejected"] != sum(reasons.values()):
        raise RuntimeError("Internal reconciliation failure")
    return accepted, rejected, report


def run(manifest_path: Path, input_path: Path, output_dir: Path) -> dict:
    manifest = load_manifest(manifest_path)
    rows = read_pinned_csv(input_path, manifest["sha256"])
    accepted, rejected, report = ingest(rows, manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, records in (("accepted.jsonl", accepted), ("rejected.jsonl", rejected)):
        (output_dir / name).write_text("".join(_canonical(record) + "\n" for record in records), encoding="utf-8")
    (output_dir / "reconciliation.json").write_text(_canonical(report) + "\n", encoding="utf-8")
    return report
