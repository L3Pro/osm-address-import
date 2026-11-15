"""Export an existing dry-run conflation report to private MapViewer layers.

Reads only local run artifacts. No OSM API client or Rails connection exists here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import Point, box, mapping, shape

from osm_address_import.building_conflation import (
    SOURCE_EVIDENCE_REASONS, read_candidates, read_osm, sha256,
)

PRIMARY_FILES = {
    "ALREADY_MAPPED": ("already_mapped.geojson", "Equivalent OSM address exists"),
    "AUTO_ATTACH_CANDIDATE": ("auto_attach_candidates.geojson", "Dry-run eligible existing-building updates"),
    "REVIEW_MULTIPLE_ADDRESSES": ("review_multiple_addresses.geojson", "Multiple addresses or units per building"),
    "REVIEW_NO_BUILDING": ("review_no_building.geojson", "No plausible existing building"),
    "REVIEW_SPATIAL_AMBIGUITY": ("review_spatial_ambiguity.geojson", "Ambiguous association or insufficient evidence"),
    "REVIEW_CONFLICT": ("review_conflicts.geojson", "Conflicting OSM address information"),
    "SOURCE_DUPLICATE": ("source_duplicates.geojson", "Duplicate authoritative source record"),
    "SOURCE_INVALID": ("source_invalid.geojson", "Invalid authoritative source record"),
}
SAMPLE_STRATA = {
    "SOURCE_EVIDENCE_ONLY": "Single building; blocked only by source placement or accuracy",
    "NEAR_OUTSIDE_BUILDING": "Near a building but outside its footprint",
    "NO_PLAUSIBLE_BUILDING": "No plausible building",
    "REVIEW_MULTIPLE_ADDRESSES": "Multiple addresses or units",
    "ALREADY_MAPPED": "Equivalent OSM address already present",
}
REVIEW_COLUMNS = (
    "candidate_id", "machine_decision", "sample_stratum", "reviewer", "review_date",
    "address_verified", "building_association_correct", "already_represented_in_osm",
    "multi_unit_or_multi_address_concern", "evidence_source", "final_reviewer_decision", "notes",
)


class ExportError(ValueError):
    pass


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError(f"cannot read {path.name}: {exc}") from exc


def _find_pinned_input(data_dir, digest, suffixes):
    matches = [p for p in sorted(data_dir.iterdir()) if p.is_file() and p.suffix in suffixes
               and sha256(p) == digest]
    if len(matches) != 1:
        raise ExportError(f"expected exactly one checksum-matched input with suffix {suffixes}")
    return matches[0]


def _point(coordinates):
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return None
    try:
        lon, lat = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return {"type": "Point", "coordinates": [lon, lat]}


def _feature(identifier, geometry, properties):
    return {"type": "Feature", "id": identifier, "geometry": geometry, "properties": properties}


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


def _all_coordinates(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value[:2]
    ):
        yield value
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _all_coordinates(child)


def _validate_geojson(name, collection, *, allow_null=False, building=False):
    if collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list):
        raise ExportError(f"{name}: invalid FeatureCollection")
    ids, undrawable = set(), 0
    for feature in collection["features"]:
        if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise ExportError(f"{name}: invalid feature")
        identifier = feature.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ExportError(f"{name}: missing or duplicate feature ID")
        ids.add(identifier)
        geometry = feature.get("geometry")
        if geometry is None:
            if not allow_null:
                raise ExportError(f"{name}: null geometry is not permitted")
            undrawable += 1
            continue
        if geometry.get("type") not in ("Point", "LineString", "Polygon", "MultiPolygon"):
            raise ExportError(f"{name}: unsupported geometry type")
        if building and geometry["type"] not in ("Polygon", "MultiPolygon"):
            raise ExportError(f"{name}: building is not a polygon")
        if not all(-180 <= p[0] <= 180 and -90 <= p[1] <= 90 and
                   all(math.isfinite(v) for v in p[:2]) for p in _all_coordinates(geometry.get("coordinates"))):
            raise ExportError(f"{name}: geometry outside WGS84 coordinate bounds")
        try:
            geom = shape(geometry)
        except (TypeError, ValueError) as exc:
            raise ExportError(f"{name}: invalid GeoJSON geometry") from exc
        if geom.is_empty or not geom.is_valid:
            raise ExportError(f"{name}: invalid or empty geometry")
    return undrawable


def _source_evidence_only(record):
    reasons = record.get("reason_codes") or []
    return (record.get("primary_decision") == "REVIEW_SPATIAL_AMBIGUITY"
            and record.get("spatial_relationship") == "INSIDE_ONE_BUILDING"
            and bool(reasons) and set(reasons) <= SOURCE_EVIDENCE_REASONS)


def _address_feature(record, source):
    address = record.get("source_address") or {}
    house = str(address.get("house_number") or source.get("house_number") or "")
    street = str(address.get("street_name") or source.get("street_name") or "")
    unit = str(address.get("unit") or source.get("unit") or "")
    displayed = " ".join(x for x in (house, street) if x).strip()
    if unit:
        displayed += " Unit " + unit
    near = record.get("competing_candidate_buildings") or []
    associated = record.get("associated_osm_buildings") or []
    if not associated and record.get("spatial_relationship") == "INSIDE_MULTIPLE_BUILDINGS":
        associated = [b["osm_object"] for b in near if b.get("contains_point")]
    evidence = record.get("match_evidence") or {}
    clearance = evidence.get("boundary_clearance_m")
    if clearance is None and near:
        clearance = near[0].get("boundary_clearance_m")
    provenance = record.get("source_provenance") or {}
    location = record.get("source_location") or {}
    source_point = _point([source.get("longitude"), source.get("latitude")])
    report_point = _point(location.get("coordinates"))
    if source_point != report_point:
        raise ExportError(f"candidate {record['candidate_id']}: report/source coordinates differ")
    return _feature(record["candidate_id"], source_point, {
        "candidate_id": record["candidate_id"], "source_record_id": record.get("source_record_id"),
        "address": displayed, "house_number": house, "street_name": street, "unit": unit,
        "primary_decision": record["primary_decision"],
        "spatial_relationship": record.get("spatial_relationship") or "NOT_EVALUATED",
        "reason_codes": "; ".join(record.get("reason_codes") or []),
        "associated_osm_building": "; ".join(associated),
        "candidate_osm_buildings": "; ".join(b.get("osm_object", "") for b in near),
        "source_location_type": provenance.get("source_location_type") or source.get("source_location_type"),
        "positional_accuracy_m": provenance.get("positional_accuracy_m"),
        "boundary_clearance_m": clearance,
        "review_status": "UNREVIEWED",
    })


def _sample(records, limit=5):
    by_stratum = {
        "SOURCE_EVIDENCE_ONLY": [r for r in records if _source_evidence_only(r)],
        "NEAR_OUTSIDE_BUILDING": [r for r in records if r.get("spatial_relationship") == "NEAR_OUTSIDE_BUILDING"
                                  and r.get("primary_decision") == "REVIEW_SPATIAL_AMBIGUITY"],
        "NO_PLAUSIBLE_BUILDING": [r for r in records if r.get("spatial_relationship") == "NO_PLAUSIBLE_BUILDING"],
        "REVIEW_MULTIPLE_ADDRESSES": [r for r in records if r["primary_decision"] == "REVIEW_MULTIPLE_ADDRESSES"],
        "ALREADY_MAPPED": [r for r in records if r["primary_decision"] == "ALREADY_MAPPED"],
    }
    selected = defaultdict(list)
    manifest = {}
    for stratum, members in by_stratum.items():
        ordered = sorted(members, key=lambda r: (
            hashlib.sha256(("mapviewer-review-v1:" + r["candidate_id"]).encode()).hexdigest(),
            r["candidate_id"]))
        chosen = ordered[:limit]
        manifest[stratum] = {"description": SAMPLE_STRATA[stratum],
                             "eligible_count": len(members), "selected_candidate_ids": [r["candidate_id"] for r in chosen]}
        for record in chosen:
            selected[record["candidate_id"]].append(stratum)
    return selected, manifest


def export(run_dir):
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise ExportError("run directory does not exist")
    out_dir = run_dir / "mapviewer"
    if out_dir.is_symlink():
        raise ExportError("mapviewer output cannot be a symlink")
    assessment = _read_json(run_dir / "import_assessment.json")
    manifest = _read_json(run_dir / "source_manifest.json")
    review = _read_json(run_dir / "manual_review.json")
    updates = _read_json(run_dir / "proposed_building_updates.json")
    if any(x.get("schema_version") != "1.0" for x in (assessment, manifest, review, updates)):
        raise ExportError("unsupported run artifact schema")
    data_dir = run_dir / "data"
    if not data_dir.is_dir():
        raise ExportError("run data directory does not exist")
    source_path = _find_pinned_input(data_dir, manifest["source_file_sha256"], {".geojson", ".csv"})
    osm_path = _find_pinned_input(data_dir, manifest["osm_file_sha256"], {".osm", ".json"})
    candidates = read_candidates(source_path, "nad-geojson" if source_path.suffix == ".geojson" else "candidate-csv")
    osm = read_osm(osm_path)
    if len(candidates) != assessment["total_input_records"] or len(osm["buildings"]) != assessment["building_count"]:
        raise ExportError("source or building count differs from assessment")
    source_by_id = {}
    for row in candidates:
        candidate_id = str(row.get("candidate_id"))
        if candidate_id in source_by_id:
            raise ExportError("duplicate candidate ID in source data")
        source_by_id[candidate_id] = row
    records = list(review.get("records") or [])
    for update in updates.get("updates") or []:
        if update.get("execution_authorized") is not False:
            raise ExportError("update manifest is not a dry run")
        source = source_by_id.get(update.get("candidate_id"))
        if source is None:
            raise ExportError("update candidate missing from source")
        records.append({"candidate_id": update["candidate_id"],
                        "source_record_id": update["source_record_id"],
                        "source_address": {k: source.get(k) for k in
                                           ("house_number", "street_name", "unit", "city", "state", "zip_code")},
                        "source_location": {"type": "Point", "coordinates":
                                            [source.get("longitude"), source.get("latitude")]},
                        "primary_decision": "AUTO_ATTACH_CANDIDATE",
                        "spatial_relationship": "INSIDE_ONE_BUILDING",
                        "reason_codes": update.get("reason_codes") or [],
                        "associated_osm_buildings": [f"{update['target_osm_type']}/{update['target_osm_id']}"],
                        "competing_candidate_buildings": [],
                        "source_provenance": update.get("source_provenance") or {},
                        "match_evidence": update.get("match_evidence") or {}})
    if len(records) != len(candidates):
        raise ExportError("primary records do not reconcile to source count")
    decisions = Counter()
    seen = set()
    for record in records:
        candidate_id = record.get("candidate_id")
        if candidate_id not in source_by_id or candidate_id in seen:
            raise ExportError("missing or duplicate candidate ID in primary records")
        seen.add(candidate_id)
        decision = record.get("primary_decision")
        if decision not in PRIMARY_FILES:
            raise ExportError("unknown primary decision")
        if str(record.get("source_record_id")) != str(source_by_id[candidate_id].get("source_record_id")):
            raise ExportError("source record ID mismatch")
        decisions[decision] += 1
    if seen != set(source_by_id) or any(decisions[d] != n for d, n in assessment["decisions"].items()):
        raise ExportError("primary decision counts differ from assessment")
    evidence_only = [r for r in records if _source_evidence_only(r)]
    if len(evidence_only) != assessment["inside_one_blocked_only_by_source_position_or_accuracy"]:
        raise ExportError("source-evidence-only count differs from assessment")
    bbox = manifest.get("scope_bbox_wgs84")
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        raise ExportError("source manifest lacks study bbox")
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ExportError("invalid study bbox")

    layers = {}
    records_by_id = {r["candidate_id"]: r for r in records}
    for decision, (filename, _) in PRIMARY_FILES.items():
        layers[filename] = _collection([_address_feature(r, source_by_id[r["candidate_id"]])
                                        for r in records if r["primary_decision"] == decision])
    layers["source_evidence_only.geojson"] = _collection([
        _address_feature(r, source_by_id[r["candidate_id"]]) for r in evidence_only])
    selected, strata = _sample(records)
    sample_features = []
    for candidate_id in sorted(selected):
        feature = _address_feature(records_by_id[candidate_id], source_by_id[candidate_id])
        feature["properties"]["selection_criteria"] = "; ".join(selected[candidate_id])
        sample_features.append(feature)
    layers["review_sample.geojson"] = _collection(sample_features)
    counts_by_building = Counter()
    for record in records:
        if record.get("spatial_relationship") not in ("INSIDE_ONE_BUILDING", "INSIDE_MULTIPLE_BUILDINGS"):
            continue
        building_ids = record.get("associated_osm_buildings") or [
            b["osm_object"] for b in record.get("competing_candidate_buildings") or [] if b.get("contains_point")]
        counts_by_building.update(set(building_ids))
    building_features = []
    for building in osm["buildings"]:
        obj = building["object"]
        tags = obj.get("tags", {})
        building_features.append(_feature(building["key"], mapping(building["geometry"]), {
            "osm_type": obj["type"], "osm_id": obj["id"], "osm_version": obj["version"],
            "building_type": tags.get("building"), "addr_housenumber": tags.get("addr:housenumber"),
            "addr_street": tags.get("addr:street"),
            "associated_candidate_count": counts_by_building[building["key"]],
        }))
    layers["osm_buildings.geojson"] = _collection(building_features)
    address_features = []
    for address in osm["addresses"]:
        obj = address["object"]
        tags = obj.get("tags", {})
        address_features.append(_feature(address["key"], mapping(address["geometry"]), {
            "osm_type": obj["type"], "osm_id": obj["id"], "osm_version": obj["version"],
            "address": " ".join((tags.get("addr:housenumber", ""), tags.get("addr:street", ""))).strip(),
            "addr_housenumber": tags.get("addr:housenumber"), "addr_street": tags.get("addr:street"),
            "addr_unit": tags.get("addr:unit"), "entrance": tags.get("entrance"),
        }))
    layers["osm_addresses.geojson"] = _collection(address_features)
    layers["study_area.geojson"] = _collection([_feature("study-area", mapping(box(*bbox)), {
        "name": manifest.get("study_area") or assessment.get("study_area"),
        "west": west, "south": south, "east": east, "north": north,
    })])
    null_counts = {}
    for filename, layer in layers.items():
        null_counts[filename] = _validate_geojson(filename, layer,
            allow_null=filename == PRIMARY_FILES["SOURCE_INVALID"][0],
            building=filename in ("osm_buildings.geojson", "study_area.geojson"))
    if len(building_features) != assessment["building_count"]:
        raise ExportError("building export count differs from assessment")
    by_osm_id = {b["key"]: b for b in osm["buildings"]}
    for feature in building_features:
        original = by_osm_id[feature["id"]]
        if (feature["properties"]["osm_id"] != original["object"]["id"]
                or feature["properties"]["osm_version"] != original["object"]["version"]
                or not shape(feature["geometry"]).equals_exact(original["geometry"], 0)):
            raise ExportError("OSM building identity or geometry changed")
    if set(f["id"] for f in layers["source_evidence_only.geojson"]["features"]) - set(
        f["id"] for f in layers["review_spatial_ambiguity.geojson"]["features"]
    ):
        raise ExportError("source-evidence layer is not a review subset")

    output_bytes = {name: (json.dumps(layer, ensure_ascii=False, separators=(",", ":"),
                                      allow_nan=False) + "\n").encode("utf-8")
                    for name, layer in layers.items()}
    worksheet = io.StringIO(newline="")
    writer = csv.DictWriter(worksheet, fieldnames=REVIEW_COLUMNS)
    writer.writeheader()
    for candidate_id in sorted(source_by_id):
        writer.writerow({"candidate_id": candidate_id,
                         "machine_decision": records_by_id[candidate_id]["primary_decision"],
                         "sample_stratum": "; ".join(selected.get(candidate_id, [])),
                         **{k: "" for k in REVIEW_COLUMNS[3:]}})
    worksheet_bytes = worksheet.getvalue().encode("utf-8")
    for filename in (*output_bytes, "review_template.csv", "geojson_layers.zip", "layers_manifest.json"):
        if (out_dir / filename).is_symlink():
            raise ExportError("output file cannot be a symlink")
    if out_dir.exists() and (out_dir / "review_template.csv").exists() and (
        (out_dir / "review_template.csv").read_bytes() != worksheet_bytes
    ):
        raise ExportError("existing review_template.csv differs; preserve reviewer edits separately")
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in output_bytes.items():
        (out_dir / filename).write_bytes(content)
    (out_dir / "review_template.csv").write_bytes(worksheet_bytes)
    with zipfile.ZipFile(out_dir / "geojson_layers.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in sorted(output_bytes):
            archive.writestr(filename, output_bytes[filename])
    if sha256(source_path) != manifest["source_file_sha256"] or sha256(osm_path) != manifest["osm_file_sha256"]:
        raise ExportError("source or OSM input changed during export")
    layer_descriptions = {filename: description for filename, description in PRIMARY_FILES.values()}
    layer_descriptions.update({
        "source_evidence_only.geojson": "Subset of spatial reviews blocked only by source placement or accuracy",
        "osm_buildings.geojson": "Actual OSM building footprint geometry from the buffered extract",
        "osm_addresses.geojson": "Existing address-bearing OSM objects from the buffered extract",
        "review_sample.geojson": "Stable stratified manual-review sample",
        "study_area.geojson": "Exact source study-area bbox",
    })
    layer_manifest = {
        "schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "coordinate_system": "WGS84 / EPSG:4326", "run_dir": run_dir.name,
        "source_sha256": manifest["source_file_sha256"], "osm_sha256": manifest["osm_file_sha256"],
        "total_source_records": len(candidates),
        "primary_feature_count": sum(len(layers[name]["features"]) for name, _ in PRIMARY_FILES.values()),
        "source_evidence_only_count": len(evidence_only),
        "source_invalid_without_drawable_geometry": null_counts["source_invalid.geojson"],
        "review_template_rows": len(candidates),
        "sample_method": "First five per stratum by SHA-256 of 'mapviewer-review-v1:' plus candidate ID; duplicate selections collapse",
        "sample_strata": strata,
        "layers": {filename: {"description": layer_descriptions[filename],
                              "feature_count": len(layer["features"]),
                              "drawable_count": len(layer["features"]) - null_counts[filename],
                              "file_size_bytes": len(output_bytes[filename]),
                              "subset_of": "review_spatial_ambiguity.geojson" if filename == "source_evidence_only.geojson" else None}
                   for filename, layer in layers.items()},
        "total_geojson_bytes": sum(map(len, output_bytes.values())),
        "review_template_bytes": len(worksheet_bytes),
        "zip_bundle": {"filename": "geojson_layers.zip",
                       "file_size_bytes": (out_dir / "geojson_layers.zip").stat().st_size},
        "validation": {"primary_counts_reconciled": True, "source_subset_reconciled": True,
                       "building_geometry_preserved": True, "wgs84_geometry_valid": True,
                       "source_invalid_accounted_for": True, "candidate_ids_unique": True,
                       "empty_layers_valid": True, "inputs_unchanged": True},
    }
    (out_dir / "layers_manifest.json").write_text(json.dumps(layer_manifest, indent=2, ensure_ascii=False) + "\n")
    return layer_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    report = export(args.run_dir)
    print(json.dumps({"mapviewer_dir": str(args.run_dir / "mapviewer"),
                      "primary_feature_count": report["primary_feature_count"],
                      "source_evidence_only_count": report["source_evidence_only_count"],
                      "total_geojson_bytes": report["total_geojson_bytes"]}))


if __name__ == "__main__":
    main()
