"""Offline, deterministic candidate-to-existing-building dry-run conflation.

There is deliberately no API client, database connector, or write operation here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box, mapping
from shapely.ops import polygonize_full, transform, unary_union
from shapely.strtree import STRtree

SCHEMA = "1.0"
DECISIONS = ("SOURCE_INVALID", "SOURCE_DUPLICATE", "ALREADY_MAPPED",
             "REVIEW_CONFLICT", "REVIEW_MULTIPLE_ADDRESSES",
             "REVIEW_SPATIAL_AMBIGUITY", "REVIEW_NO_BUILDING",
             "AUTO_ATTACH_CANDIDATE")
SPATIAL_RELATIONSHIPS = ("INSIDE_ONE_BUILDING", "INSIDE_MULTIPLE_BUILDINGS",
                         "ON_BUILDING_BOUNDARY", "NEAR_OUTSIDE_BUILDING",
                         "NO_PLAUSIBLE_BUILDING", "NOT_EVALUATED")
SOURCE_EVIDENCE_REASONS = {"UNSUPPORTED_SOURCE_POSITION_TYPE",
                           "INSUFFICIENT_POSITIONAL_ACCURACY"}
REQUIRED = ("schema_version", "candidate_id", "source_dataset", "source_record_id",
            "source_dataset_version", "source_license", "source_permission_status",
            "house_number", "street_name", "city", "state", "zip_code",
            "latitude", "longitude", "crs", "source_location_type",
            "positional_accuracy_m", "original_source_attributes")
DEFAULTS = {"boundary_clearance_m": 3.0, "association_buffer_m": 4.0,
            "osm_duplicate_radius_m": 20.0, "max_accuracy_m": 5.0}
STREET_TYPES = {"ST": "STREET", "RD": "ROAD", "DR": "DRIVE", "AVE": "AVENUE",
                "BLVD": "BOULEVARD", "PL": "PLACE", "CT": "COURT", "LN": "LANE",
                "CIR": "CIRCLE", "PKWY": "PARKWAY", "TRL": "TRAIL"}
DIRECTIONS = {"N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
              "NE": "NORTHEAST", "NW": "NORTHWEST", "SE": "SOUTHEAST", "SW": "SOUTHWEST"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_street(value):
    words = re.findall(r"[A-Z0-9]+", (value or "").upper())
    return " ".join(STREET_TYPES.get(DIRECTIONS.get(w, w), DIRECTIONS.get(w, w)) for w in words)


def normalized_number(value):
    return re.sub(r"\s+", "", str(value or "").upper()).replace("-", "-")


def address_key(number, street, unit=None):
    return (normalized_number(number), normalized_street(street),
            re.sub(r"[^A-Z0-9]", "", str(unit or "").upper()))


def candidate_address(row):
    return address_key(row.get("house_number"), " ".join(str(row.get(k) or "") for k in
                       ("street_prefix", "street_name", "street_suffix")), row.get("unit"))


def osm_address(tags):
    return address_key(tags.get("addr:housenumber"), tags.get("addr:street"),
                       tags.get("addr:unit"))


def candidate_from_nad(feature):
    """Map one official NAD GeoJSON feature to the public candidate contract."""
    p = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]
    rid = str(p.get("UUID") or p.get("OBJECTID") or feature.get("id"))
    street = p.get("St_Name") or ""
    # NAD StNam_Full already contains directions and type. Keep components in
    # original attributes, but use the full label for OSM addr:street.
    full_street = p.get("StNam_Full") or street
    return {"schema_version": SCHEMA, "candidate_id": "nad-r24:" + rid,
            "source_dataset": "USDOT NAD", "source_record_id": rid,
            "source_dataset_version": "release-24:2026-09-30",
            "source_license": "USDOT NAD disclaimer; Texas contributor rights unverified",
            "source_permission_status": "PENDING_OSM_REVIEW",
            "house_number": str(p.get("AddNo_Full") or p.get("Add_Number") or ""),
            "street_name": str(full_street), "street_prefix": "", "street_suffix": "",
            "unit": str(p.get("Unit") or p.get("SubAddress") or ""),
            "city": str(p.get("Post_City") or p.get("Inc_Muni") or ""),
            "state": str(p.get("State") or ""), "zip_code": str(p.get("Zip_Code") or ""),
            "latitude": lat, "longitude": lon, "crs": "EPSG:4326",
            "source_location_type": str(p.get("Placement") or "unknown").lower(),
            "positional_accuracy_m": None, "original_source_attributes": p,
            "upstream_assessment": None}


def read_candidates(path, input_format):
    if input_format == "nad-geojson":
        data = json.loads(Path(path).read_text())
        if data.get("type") != "FeatureCollection":
            raise ValueError("NAD input must be a GeoJSON FeatureCollection")
        return [candidate_from_nad(f) for f in data["features"]]
    if input_format != "candidate-csv":
        raise ValueError("unsupported candidate format")
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or set(REQUIRED) - set(reader.fieldnames):
            raise ValueError("candidate CSV lacks required columns")
        rows = list(reader)
    for row in rows:
        for key in ("original_source_attributes", "upstream_assessment"):
            if row.get(key):
                row[key] = json.loads(row[key])
        for key in ("latitude", "longitude", "positional_accuracy_m"):
            if row.get(key) not in (None, ""):
                try:
                    row[key] = float(row[key])
                except ValueError:
                    pass
    return rows


def validate_candidate(row):
    missing = [k for k in REQUIRED if k not in row]
    if missing:
        return ["SCHEMA_MISSING_FIELDS:" + ",".join(sorted(missing))]
    if row["schema_version"] != SCHEMA:
        return ["UNSUPPORTED_SCHEMA"]
    if any(not str(row.get(k) or "").strip() for k in
           ("candidate_id", "source_dataset", "source_record_id", "source_dataset_version",
            "source_license", "source_permission_status", "house_number", "street_name", "city", "state")):
        return ["REQUIRED_VALUE_MISSING"]
    if row["crs"] != "EPSG:4326":
        return ["UNSUPPORTED_CRS"]
    if not isinstance(row["original_source_attributes"], dict):
        return ["INVALID_ORIGINAL_ATTRIBUTES"]
    try:
        lon, lat = float(row["longitude"]), float(row["latitude"])
    except (TypeError, ValueError):
        return ["INVALID_COORDINATE"]
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return ["INVALID_COORDINATE"]
    if not normalized_number(row["house_number"]) or not normalized_street(row["street_name"]):
        return ["INVALID_ADDRESS"]
    accuracy = row.get("positional_accuracy_m")
    if accuracy not in (None, ""):
        try:
            if not math.isfinite(float(accuracy)) or float(accuracy) < 0:
                return ["INVALID_ACCURACY"]
        except (TypeError, ValueError):
            return ["INVALID_ACCURACY"]
    return []


def local_xy(lon0, lat0):
    coslat = math.cos(math.radians(lat0))
    return lambda x, y, z=None: ((x - lon0) * 111320 * coslat, (y - lat0) * 111320)


def read_osm(path):
    """Read Overpass JSON or OSM API 0.6 map XML with object metadata."""
    path = Path(path)
    if path.suffix == ".osm":
        root = ET.parse(path).getroot()
        if root.tag != "osm":
            raise ValueError("expected OSM API 0.6 XML")
        elements = []
        for elem in root:
            if elem.tag not in ("node", "way", "relation"):
                continue
            obj = {"type": elem.tag, "id": int(elem.attrib["id"]),
                   "version": int(elem.attrib["version"]),
                   "tags": {t.attrib["k"]: t.attrib["v"] for t in elem.findall("tag")}}
            for key in ("timestamp", "changeset", "uid", "user"):
                if key in elem.attrib:
                    obj[key] = int(elem.attrib[key]) if key in ("changeset", "uid") else elem.attrib[key]
            if elem.tag == "node":
                obj.update(lat=float(elem.attrib["lat"]), lon=float(elem.attrib["lon"]))
            elif elem.tag == "way":
                obj["nodes"] = [int(n.attrib["ref"]) for n in elem.findall("nd")]
            else:
                obj["members"] = [{"type": m.attrib["type"], "ref": int(m.attrib["ref"]),
                                   "role": m.attrib.get("role", "")} for m in elem.findall("member")]
            elements.append(obj)
        data = {"elements": elements, "osm3s": {"timestamp_osm_base":
                datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")}}
    else:
        data = json.loads(path.read_text())
    if "elements" not in data:
        raise ValueError("OSM extract lacks elements")
    objects = {(x["type"], x["id"]): x for x in data["elements"]}
    nodes = {oid: x for (typ, oid), x in objects.items() if typ == "node"}
    ways = {oid: x for (typ, oid), x in objects.items() if typ == "way"}
    relation_member_ways = {m["ref"] for x in data["elements"] if x["type"] == "relation"
                            and x.get("tags", {}).get("building")
                            for m in x.get("members", []) if m["type"] == "way"}
    buildings, invalid = [], []

    def way_line(w):
        coords = [(nodes[n]["lon"], nodes[n]["lat"]) for n in w.get("nodes", []) if n in nodes]
        if len(coords) != len(w.get("nodes", [])) or len(coords) < 2:
            return None
        return LineString(coords)

    def relation_polygon(obj):
        members = obj.get("members", [])
        if not members or any(m["type"] != "way" or m.get("role") not in ("outer", "inner")
                              or m["ref"] not in ways for m in members):
            return None
        outer = [way_line(ways[m["ref"]]) for m in members if m["role"] == "outer"]
        inner = [way_line(ways[m["ref"]]) for m in members if m["role"] == "inner"]
        if not outer or any(line is None for line in outer + inner):
            return None
        shells, dangles, cuts, invalid = polygonize_full(outer)
        if not dangles.is_empty or not cuts.is_empty or not invalid.is_empty:
            return None
        shells = list(shells.geoms)
        if not shells:
            return None
        geom = unary_union(shells)
        if inner:
            holes, dangles, cuts, invalid = polygonize_full(inner)
            if not dangles.is_empty or not cuts.is_empty or not invalid.is_empty:
                return None
            holes = list(holes.geoms)
            if not holes:
                return None
            hole_geom = unary_union(holes)
            if not geom.covers(hole_geom):
                return None
            geom = geom.difference(hole_geom)
        return geom

    for x in data["elements"]:
        tags = x.get("tags", {})
        if not tags.get("building") or tags.get("building") == "no":
            continue
        geom = None
        if x["type"] == "way":
            if x["id"] in relation_member_ways:
                continue
            line = way_line(x)
            if line is not None and line.is_ring:
                geom = Polygon(line)
        elif x["type"] == "relation" and tags.get("type") == "multipolygon":
            geom = relation_polygon(x)
        if geom is None or geom.is_empty or not geom.is_valid or geom.area == 0 or not x.get("version"):
            invalid.append(f"{x['type']}/{x['id']}")
            continue
        buildings.append({"object": x, "geometry": geom, "key": f"{x['type']}/{x['id']}"})
    addresses = []
    unit_markers = []
    for x in data["elements"]:
        tags = x.get("tags", {})
        if not (tags.get("addr:housenumber") and tags.get("addr:street")) and not any(
            tags.get(k) for k in ("addr:unit", "addr:flats", "building:units")
        ):
            continue
        geom = None
        if x["type"] == "node":
            geom = Point(x["lon"], x["lat"])
        elif x["type"] == "way":
            line = way_line(x)
            if line is not None:
                geom = Polygon(line) if line.is_ring else line
        else:
            b = next((b for b in buildings if b["object"] is x), None)
            geom = b["geometry"] if b else relation_polygon(x)
        if geom is not None and geom.is_valid and not geom.is_empty:
            if tags.get("addr:housenumber") and tags.get("addr:street"):
                addresses.append({"object": x, "geometry": geom,
                                  "key": f"{x['type']}/{x['id']}", "address": osm_address(tags)})
            if any(tags.get(k) for k in ("addr:unit", "addr:flats", "building:units")):
                unit_markers.append({"key": f"{x['type']}/{x['id']}", "geometry": geom})
    streets = {normalized_street(x.get("tags", {}).get("name")) for x in data["elements"]
               if x.get("tags", {}).get("highway") and x.get("tags", {}).get("name")}
    return {"buildings": buildings, "addresses": addresses, "unit_markers": unit_markers,
            "streets": streets,
            "invalid_buildings": invalid, "timestamp": data.get("osm3s", {}).get("timestamp_osm_base")}


def run(candidates, osm, *, thresholds=None, scope_bbox=None):
    """Return decisions, updates, review records, and independently counted OSM-only objects."""
    t = dict(DEFAULTS)
    if thresholds:
        t.update(thresholds)
    if any(not isinstance(v, (int, float)) or v < 0 for v in t.values()):
        raise ValueError("thresholds must be nonnegative numbers")
    buildings = osm["buildings"]
    if buildings:
        center = unary_union([b["geometry"].centroid for b in buildings]).centroid
        project = local_xy(center.x, center.y)
    else:
        project = local_xy(0, 0)
    bmetres = [transform(project, b["geometry"]) for b in buildings]
    index = STRtree(bmetres) if buildings else None
    am = [(a, transform(project, a["geometry"])) for a in osm["addresses"]]
    results = []
    seen_id, seen_address = {}, {}
    for row in candidates:
        cid = str(row.get("candidate_id", ""))
        result = {"candidate_id": cid, "source_record_id": row.get("source_record_id"),
                  "source_address": {k: row.get(k) for k in ("house_number", "street_name", "unit", "city", "state", "zip_code")},
                  "source_location": {"type": "Point", "coordinates": [row.get("longitude"), row.get("latitude")]},
                  "primary_decision": None, "reason_codes": [], "associated_osm_buildings": [],
                  "competing_candidate_buildings": [], "existing_osm_addresses": [],
                  "spatial_relationship": "NOT_EVALUATED",
                  "existing_osm_address_details": [],
                  "conflicting_values": [], "recommended_review_action": None,
                  "source_provenance": {k: row.get(k) for k in
                                        ("source_dataset", "source_dataset_version", "source_license",
                                         "source_permission_status", "source_location_type", "positional_accuracy_m",
                                         "original_source_attributes", "upstream_assessment")},
                  "match_evidence": {}, "_row": row, "_building": None}
        errors = validate_candidate(row)
        if errors:
            result.update(primary_decision="SOURCE_INVALID", reason_codes=errors)
            results.append(result)
            continue
        key = candidate_address(row)
        source_key = (normalized_street(row["city"]), str(row["state"]).upper(), key)
        prior = seen_id.get(("candidate", cid))
        if prior is None:
            prior = seen_id.get(("record", str(row["source_record_id"])))
        if prior is None:
            prior = seen_address.get(source_key)
        if prior is not None:
            first = results[prior]
            previous = first["_row"]
            metres = transform(local_xy(float(row["longitude"]), float(row["latitude"])),
                               Point(float(previous["longitude"]), float(previous["latitude"]))).distance(Point(0, 0))
            inconsistent = (first["primary_decision"] == "SOURCE_INVALID"
                            or source_key != (normalized_street(previous["city"]), str(previous["state"]).upper(), candidate_address(previous))
                            or str(row.get("zip_code") or "") != str(previous.get("zip_code") or "")
                            or metres > 20)
            if inconsistent:
                first.update(primary_decision="SOURCE_INVALID", reason_codes=["INCONSISTENT_SOURCE_DUPLICATE"])
                result.update(primary_decision="SOURCE_INVALID", reason_codes=["INCONSISTENT_SOURCE_DUPLICATE"])
            else:
                result.update(primary_decision="SOURCE_DUPLICATE",
                              reason_codes=["EQUIVALENT_SOURCE_ADDRESS", "FIRST:" + first["candidate_id"]])
            results.append(result)
            continue
        seen_id[("candidate", cid)] = len(results)
        seen_id[("record", str(row["source_record_id"]))] = len(results)
        seen_address[source_key] = len(results)
        point = transform(project, Point(float(row["longitude"]), float(row["latitude"])))
        nearby = []
        for i in index.query(point.buffer(t["association_buffer_m"])) if index else []:
            i = int(i)
            distance = point.distance(bmetres[i])
            if distance > t["association_buffer_m"]:
                continue
            clearance = point.distance(bmetres[i].boundary)
            nearby.append((i, distance, clearance, bmetres[i].contains(point),
                           bmetres[i].touches(point)))
        nearby.sort(key=lambda v: (v[1], buildings[v[0]]["key"]))
        result["competing_candidate_buildings"] = [
            {"osm_object": buildings[i]["key"], "distance_m": round(d, 2),
             "boundary_clearance_m": round(c, 2), "contains_point": inside,
             "touches_boundary": touches} for i, d, c, inside, touches in nearby]
        containing = [v for v in nearby if v[3]]
        touching = [v for v in nearby if v[4]]
        if len(containing) == 1:
            i, d, clearance, _, _ = containing[0]
            result["spatial_relationship"] = "INSIDE_ONE_BUILDING"
            result["_building"] = i
            result["associated_osm_buildings"] = [buildings[i]["key"]]
            result["match_evidence"] = {"point_inside": True, "boundary_clearance_m": clearance,
                                        "source_location_type": row["source_location_type"],
                                        "positional_accuracy_m": row.get("positional_accuracy_m"),
                                        "nearby_named_street": key[1] in osm["streets"]}
        elif len(containing) > 1:
            result["spatial_relationship"] = "INSIDE_MULTIPLE_BUILDINGS"
            result.update(primary_decision="REVIEW_SPATIAL_AMBIGUITY",
                          reason_codes=["OVERLAPPING_BUILDINGS"])
        elif touching:
            result["spatial_relationship"] = "ON_BUILDING_BOUNDARY"
            result.update(primary_decision="REVIEW_SPATIAL_AMBIGUITY",
                          reason_codes=["SHARED_BUILDING_BOUNDARY" if len(touching) > 1
                                        else "ON_BUILDING_BOUNDARY"])
        elif nearby:
            result["spatial_relationship"] = "NEAR_OUTSIDE_BUILDING"
            result.update(primary_decision="REVIEW_SPATIAL_AMBIGUITY",
                          reason_codes=["NEAR_BUILDING_OUTSIDE"])
        else:
            result["spatial_relationship"] = "NO_PLAUSIBLE_BUILDING"
            result.update(primary_decision="REVIEW_NO_BUILDING", reason_codes=["NO_ELIGIBLE_BUILDING"])
        matches = []
        for a, geom in am:
            same_building = result["_building"] is not None and geom.distance(bmetres[result["_building"]]) <= 2
            same_location = point.distance(geom) <= min(t["osm_duplicate_radius_m"], 4.0)
            if a["address"] == key and (same_building or same_location):
                matches.append(a)
        if matches:
            result["existing_osm_addresses"] = [a["key"] for a in matches]
            result["existing_osm_address_details"] = [
                {"osm_object": a["key"], "address": a["address"]} for a in matches]
            result.update(primary_decision="ALREADY_MAPPED", reason_codes=["EQUIVALENT_OSM_ADDRESS"])
        results.append(result)
    # Group all distinct valid source addresses by building before final decisions.
    groups = defaultdict(list)
    for r in results:
        if r["_building"] is not None and r["primary_decision"] not in ("SOURCE_INVALID", "SOURCE_DUPLICATE"):
            groups[r["_building"]].append(r)
    for i, group in groups.items():
        building = buildings[i]
        existing = [a for a, geom in am if geom.intersects(bmetres[i]) or geom.distance(bmetres[i]) <= 2]
        unit_evidence = [m["key"] for m in osm.get("unit_markers", [])
                         if transform(project, m["geometry"]).distance(bmetres[i]) <= 2]
        distinct = {candidate_address(r["_row"]) for r in group}
        for r in group:
            if r["primary_decision"] == "ALREADY_MAPPED":
                continue
            row = r["_row"]
            key = candidate_address(row)
            conflicting = []
            existing_unit_addresses = []
            tags = building["object"].get("tags", {})
            for field, proposed in (("addr:housenumber", row["house_number"]),
                                    ("addr:street", row["street_name"]),
                                    ("addr:city", row["city"]),
                                    ("addr:postcode", row["zip_code"])):
                if tags.get(field) and (normalized_number(tags[field]) if field.endswith("housenumber") else normalized_street(tags[field])) != (normalized_number(proposed) if field.endswith("housenumber") else normalized_street(proposed)):
                    conflicting.append({"field": field, "existing": tags[field], "proposed": proposed})
            if tags.get("addr:place"):
                conflicting.append({"field": "addr:place", "existing": tags["addr:place"],
                                    "proposed": None})
            for a in existing:
                if a["address"] != key and a["key"] != building["key"]:
                    if a["address"][:2] == key[:2] and (a["address"][2] or key[2]):
                        existing_unit_addresses.append(a["key"])
                    else:
                        conflicting.append({"osm_object": a["key"], "existing_address": a["address"], "proposed_address": key})
            if conflicting:
                r.update(primary_decision="REVIEW_CONFLICT", reason_codes=["CONFLICTING_OSM_ADDRESS"],
                         conflicting_values=conflicting,
                         existing_osm_addresses=sorted(set(r["existing_osm_addresses"] + [a["key"] for a in existing])),
                         existing_osm_address_details=[{"osm_object": a["key"], "address": a["address"]} for a in existing])
            elif len(distinct) > 1 or key[2] or unit_evidence or existing_unit_addresses or any(candidate_address(x["_row"])[2] for x in group):
                r.update(primary_decision="REVIEW_MULTIPLE_ADDRESSES",
                         reason_codes=["MULTIPLE_BUILDING_ADDRESSES" if len(distinct) > 1 else "UNIT_EVIDENCE"],
                         match_evidence={**r["match_evidence"], "building_source_addresses": sorted(distinct),
                                         "osm_unit_markers": unit_evidence,
                                         "existing_osm_unit_addresses": existing_unit_addresses,
                                         "building_tags": tags})
            else:
                blockers = []
                if len(r["competing_candidate_buildings"]) > 1:
                    blockers.append("COMPETING_BUILDINGS")
                if r["match_evidence"].get("boundary_clearance_m", 0) < t["boundary_clearance_m"]:
                    blockers.append("NEAR_BUILDING_BOUNDARY")
                if str(row["source_location_type"]).lower() not in ("rooftop", "building", "structure"):
                    blockers.append("UNSUPPORTED_SOURCE_POSITION_TYPE")
                if row.get("positional_accuracy_m") in (None, "") or float(row["positional_accuracy_m"]) > t["max_accuracy_m"]:
                    blockers.append("INSUFFICIENT_POSITIONAL_ACCURACY")
                if not r["match_evidence"]["nearby_named_street"]:
                    blockers.append("STREET_NOT_IN_OSM_CONTEXT")
                if not building["object"].get("version"):
                    blockers.append("MISSING_OSM_VERSION")
                if blockers:
                    r.update(primary_decision="REVIEW_SPATIAL_AMBIGUITY", reason_codes=blockers)
                else:
                    r.update(primary_decision="AUTO_ATTACH_CANDIDATE", reason_codes=["SINGLE_BUILDING_ADDRESS"])
    updates, review = [], []
    recommendations = {"ALREADY_MAPPED": "Inspect equivalent OSM address; no edit",
                       "REVIEW_CONFLICT": "Verify source and OSM address; preserve existing tags",
                       "REVIEW_MULTIPLE_ADDRESSES": "Inspect units and entrances; choose representation manually",
                       "REVIEW_SPATIAL_AMBIGUITY": "Inspect imagery, location semantics and building association",
                       "REVIEW_NO_BUILDING": "Inspect source point and missing footprint",
                       "SOURCE_DUPLICATE": "Confirm duplicate source lineage",
                       "SOURCE_INVALID": "Correct or exclude invalid source row"}
    for r in results:
        if r["primary_decision"] is None:
            r.update(primary_decision="REVIEW_SPATIAL_AMBIGUITY", reason_codes=["UNRESOLVED_ASSOCIATION"])
        if r["primary_decision"] == "AUTO_ATTACH_CANDIDATE":
            b = buildings[r["_building"]]
            obj = b["object"]
            original = dict(obj.get("tags", {}))
            added = {"addr:housenumber": str(r["_row"]["house_number"]),
                     "addr:street": str(r["_row"]["street_name"])}
            updates.append({"candidate_id": r["candidate_id"], "source_record_id": r["source_record_id"],
                            "source_provenance": {k: r["_row"][k] for k in
                                                  ("source_dataset", "source_dataset_version", "source_license", "source_permission_status",
                                                   "source_location_type", "positional_accuracy_m", "original_source_attributes")},
                            "target_osm_type": obj["type"], "target_osm_id": obj["id"],
                            "target_osm_version": obj["version"], "original_tags": original,
                            "proposed_tags": {**original, **added}, "added_tags": added,
                            "preserved_geometry": {"geometry": mapping(b["geometry"]),
                                                   "node_references": obj.get("nodes", []),
                                                   "relation_members": obj.get("members", [])},
                            "osm_metadata": {k: obj.get(k) for k in ("timestamp", "changeset", "uid", "user")},
                            "match_evidence": r["match_evidence"], "reason_codes": r["reason_codes"],
                            "validation_status": "DRY_RUN_UNREVIEWED",
                            "license_status": r["_row"]["source_permission_status"],
                            "execution_authorized": False})
        else:
            r["recommended_review_action"] = recommendations[r["primary_decision"]]
            review.append({k: v for k, v in r.items() if not k.startswith("_")})
    mapped = {candidate_address(r["_row"]) for r in results if r["primary_decision"] not in ("SOURCE_INVALID", "SOURCE_DUPLICATE")}
    scope = box(*scope_bbox) if scope_bbox is not None else None
    osm_only = [{"osm_object": a["key"], "address": a["address"]} for a in osm["addresses"]
                if a["address"] not in mapped and (scope is None or a["geometry"].intersects(scope))]
    clean_results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    assert len(clean_results) == len(candidates) and all(r["primary_decision"] in DECISIONS for r in clean_results)
    assert len({(u["target_osm_type"], u["target_osm_id"]) for u in updates}) == len(updates)
    return clean_results, updates, review, osm_only, t


def write_artifacts(out_dir, candidates, osm, results, updates, review, osm_only, thresholds,
                    source_path, osm_path, duration, study_area, source_url=None, osm_url=None,
                    scope_bbox=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    def write(name, obj):
        (out / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=list) + "\n")
    counts = Counter(r["primary_decision"] for r in results)
    spatial_counts = Counter(r["spatial_relationship"] for r in results)
    if set(spatial_counts) - set(SPATIAL_RELATIONSHIPS) or sum(spatial_counts.values()) != len(results):
        raise ValueError("inconsistent spatial relationship counts")
    source_only = sum(r["spatial_relationship"] == "INSIDE_ONE_BUILDING"
                      and r["primary_decision"] == "REVIEW_SPATIAL_AMBIGUITY"
                      and bool(r["reason_codes"])
                      and set(r["reason_codes"]) <= SOURCE_EVIDENCE_REASONS
                      for r in results)
    source = {"schema_version": SCHEMA, "source_file_sha256": sha256(source_path),
              "osm_file_sha256": sha256(osm_path), "source_provider": sorted({c.get("source_dataset") for c in candidates}),
              "source_versions": sorted({c.get("source_dataset_version") for c in candidates}),
              "license_status": sorted({c.get("source_permission_status") for c in candidates}),
              "osm_extract_timestamp": osm["timestamp"], "study_area": study_area,
              "scope_bbox_wgs84": scope_bbox, "source_url": source_url, "osm_url": osm_url,
              "generated_at": utc_now(), "thresholds_m": thresholds}
    write("source_manifest.json", source)
    write("proposed_building_updates.json", {"schema_version": SCHEMA, "dry_run": True, "updates": updates})
    write("manual_review.json", {"schema_version": SCHEMA, "records": review})
    write("manual_review.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": r["source_location"] if isinstance(r["source_location"]["coordinates"][0], (int, float)) else None,
         "properties": {k: v for k, v in r.items() if k != "source_location"}} for r in review]})
    eligible_denominator = sum(counts[x] for x in ("AUTO_ATTACH_CANDIDATE", "REVIEW_MULTIPLE_ADDRESSES",
                                                "REVIEW_NO_BUILDING", "REVIEW_CONFLICT", "REVIEW_SPATIAL_AMBIGUITY"))
    assessment = {"schema_version": SCHEMA, "study_area": study_area, "generated_at": utc_now(),
                  "total_input_records": len(candidates), "valid_input_addresses": len(candidates) - counts["SOURCE_INVALID"],
                  "decisions": {d: counts[d] for d in DECISIONS},
                  "unique_source_addresses": len({candidate_address(c) for c, r in zip(candidates, results)
                                                  if r["primary_decision"] not in ("SOURCE_INVALID", "SOURCE_DUPLICATE")}),
                  "building_count": len(osm["buildings"]),
                  "address_bearing_building_count": sum(bool(b["object"].get("tags", {}).get("addr:housenumber")) for b in osm["buildings"]),
                  "invalid_osm_buildings": osm["invalid_buildings"],
                  "unique_osm_buildings_affected": len({(u["target_osm_type"], u["target_osm_id"]) for u in updates}),
                  "proposed_osm_modifications": len(updates), "osm_only_observations": len(osm_only),
                  "osm_only_objects": osm_only,
                  "candidate_to_building_relationships": {k: spatial_counts[k] for k in SPATIAL_RELATIONSHIPS},
                  "inside_one_blocked_only_by_source_position_or_accuracy": source_only,
                  "source_evidence_blocker_counts": {
                      code: sum(code in r["reason_codes"] for r in results)
                      for code in sorted(SOURCE_EVIDENCE_REASONS)},
                  "validation_findings": {
                      "source_location_types": dict(Counter(str(c.get("source_location_type")) for c in candidates)),
                      "missing_positional_accuracy": sum(c.get("positional_accuracy_m") in (None, "") for c in candidates),
                      "invalid_osm_buildings": len(osm["invalid_buildings"])},
                  "automatic_candidate_fraction_of_unmapped_valid_unique":
                      round(counts["AUTO_ATTACH_CANDIDATE"] / eligible_denominator, 4) if eligible_denominator else None,
                  "metric_denominator": eligible_denominator,
                  "percentage_of_verified_genuinely_missing_eligible": None,
                  "manual_accuracy_verified": False,
                  "processing_duration_seconds": round(duration, 3), "source_manifest": source,
                  "warnings": ["Unknown source placement does not qualify for automatic attachment",
                               "Source permission for public OSM import is pending independent review"],
                  "unresolved_questions": ["Texas contributor permission for ODbL", "NAD positional accuracy for selected records"]}
    write("import_assessment.json", assessment)
    sample, sampled = [], set()
    def add_sample(records):
        for record in sorted(records, key=lambda r: r["candidate_id"])[:3]:
            if id(record) not in sampled:
                sampled.add(id(record))
                sample.append(record)
    for decision in DECISIONS:
        add_sample(r for r in results if r["primary_decision"] == decision)
    for relationship in SPATIAL_RELATIONSHIPS:
        add_sample(r for r in results if r["spatial_relationship"] == relationship)
    add_sample(r for r in results if r["spatial_relationship"] == "INSIDE_ONE_BUILDING"
               and r["primary_decision"] == "REVIEW_SPATIAL_AMBIGUITY"
               and r["reason_codes"] and set(r["reason_codes"]) <= SOURCE_EVIDENCE_REASONS)
    write("validation_sample.json", {"schema_version": SCHEMA, "records": sample})
    lines = ["# Building-aware import assessment", "", f"Study area: {study_area}.",
             f"Source: {', '.join(source['source_provider'])}; {', '.join(source['source_versions'])}.",
             f"OSM extract timestamp: {osm['timestamp'] or 'not reported'}.",
             f"Source SHA-256: `{source['source_file_sha256']}`.",
             f"OSM SHA-256: `{source['osm_file_sha256']}`.", "",
             "| Metric | Value |", "| --- | ---: |",
             f"| Total input records | {len(candidates)} |",
             f"| Valid input addresses | {assessment['valid_input_addresses']} |"]
    labels = {"ALREADY_MAPPED": "Already mapped", "AUTO_ATTACH_CANDIDATE": "Auto-attach candidates",
              "REVIEW_MULTIPLE_ADDRESSES": "Multiple-address review", "REVIEW_NO_BUILDING": "No-building review",
              "REVIEW_CONFLICT": "Conflict review", "REVIEW_SPATIAL_AMBIGUITY": "Spatial-ambiguity review",
              "SOURCE_DUPLICATE": "Source duplicates", "SOURCE_INVALID": "Source invalid"}
    lines += [f"| {labels[d]} | {counts[d]} |" for d in labels]
    lines += [f"| Unique OSM buildings affected | {assessment['unique_osm_buildings_affected']} |",
              f"| Proposed OSM modifications | {len(updates)} |",
              f"| OSM-only observations | {len(osm_only)} |", "",
              f"Buildings in extract: {len(osm['buildings'])}; address-bearing buildings: {assessment['address_bearing_building_count']}.", "",
              "## Spatial relationships", "",
              "These categories are mutually exclusive across all source rows. Boundary points are separate from interior and outside points.",
              "", "| Relationship | Records |", "| --- | ---: |"]
    lines += [f"| {key} | {spatial_counts[key]} |" for key in SPATIAL_RELATIONSHIPS]
    lines += ["",
              f"Inside one building and blocked only by source position or accuracy: {source_only}.",
              f"Source evidence blocker counts (overlapping): {assessment['source_evidence_blocker_counts']}.",
              f"Thresholds (metres): {thresholds}.",
              f"Validation findings: {assessment['validation_findings']}.",
              f"Processing duration: {duration:.3f} seconds.", "",
              "The automatic candidate fraction uses unmapped, valid, unique source addresses as its denominator; it is algorithmic eligibility, not verified correctness. Source rows, unique addresses, buildings, and proposed object modifications have different counts because duplicate rows and multiple records per building do not imply separate edits.",
              "", "## Validation and limitations", "",
              "No manual sample has been verified. Review `validation_sample.json` with the source point and OSM extract in QGIS or JOSM; check footprint, imagery, street, unit, existing tags, and source metadata. Record corrections outside these unreviewed artifacts.",
              "", "NAD placement and accuracy may be unknown. Unknown placement cannot qualify for automatic attachment. Public OSM import permission remains pending Texas contributor and OSM community review.",
              "", "## Warnings and unresolved questions", ""]
    lines += ["- " + x for x in assessment["warnings"] + assessment["unresolved_questions"]]
    (out / "import_assessment.md").write_text("\n".join(lines) + "\n")
    return assessment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--input-format", choices=("candidate-csv", "nad-geojson"), required=True)
    parser.add_argument("--osm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--study-area", required=True)
    parser.add_argument("--bbox", help="Study scope west,south,east,north; bounds OSM-only observations")
    parser.add_argument("--source-url")
    parser.add_argument("--osm-url")
    args = parser.parse_args()
    started = time.monotonic()
    candidates = read_candidates(args.candidates, args.input_format)
    osm = read_osm(args.osm)
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None
    if bbox and (len(bbox) != 4 or not -180 <= bbox[0] < bbox[2] <= 180 or not -90 <= bbox[1] < bbox[3] <= 90):
        parser.error("--bbox must be west,south,east,north")
    result = run(candidates, osm, scope_bbox=bbox)
    assessment = write_artifacts(args.output, candidates, osm, *result,
                                 args.candidates, args.osm, time.monotonic() - started,
                                 args.study_area, args.source_url, args.osm_url, bbox)
    print(json.dumps({"decisions": assessment["decisions"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
