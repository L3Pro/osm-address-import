"""Prepare reference-complete city PBFs and private source object manifests.

Requires PyOsmium and Shapely. The input PBF is an Osmium smart polygon extract.
Only relations whose complete member graph is present are retained. Exclusions
are recorded in the manifest and stats, never silently ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def feature_classes(tags, kind):
    result = []
    if tags.get("building") not in (None, "no"):
        result.append("buildings")
    if any(key.startswith("addr:") for key in tags):
        result.append("addresses")
    if kind == "ways" and tags.get("highway") not in (None, "no"):
        result.append("highway_ways")
    if any(key in tags for key in ("amenity", "shop", "landuse", "natural",
                                    "waterway", "railway")):
        result.append("other_features")
    return result


def prepare(source, polygon_path, relation_id, expected_name, expected_ibge,
            output, manifest_path, stats_path):
    import osmium
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    polygon = shape(json.loads(Path(polygon_path).read_text())["geometry"])
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("municipal boundary geometry is empty or invalid")
    spatial = prep(polygon)
    west, south, east, north = polygon.bounds
    nodes, primary_nodes, ways, relations = set(), set(), {}, {}
    boundary_tags = None

    class Index(osmium.SimpleHandler):
        def node(self, obj):
            nodes.add(obj.id)
            if obj.location.valid():
                lon, lat = obj.location.lon, obj.location.lat
                if west <= lon <= east and south <= lat <= north and spatial.intersects(Point(lon, lat)):
                    primary_nodes.add(obj.id)

        def way(self, obj):
            refs = [member.ref for member in obj.nodes]
            missing = [ref for ref in refs if ref not in nodes]
            if missing:
                raise ValueError(f"way {obj.id} has {len(missing)} missing node references")
            ways[obj.id] = any(ref in primary_nodes for ref in refs)

        def relation(self, obj):
            nonlocal boundary_tags
            members = [(member.type, member.ref) for member in obj.members]
            relations[obj.id] = members
            if obj.id == relation_id:
                boundary_tags = dict(obj.tags)

    Index().apply_file(str(source))
    if not boundary_tags:
        raise ValueError(f"municipal boundary relation {relation_id} absent from extract")
    if (boundary_tags.get("name") != expected_name
            or boundary_tags.get("boundary") != "administrative"
            or boundary_tags.get("admin_level") != "8"
            or boundary_tags.get("IBGE:GEOCODIGO") != expected_ibge):
        raise ValueError(f"relation {relation_id} is not the expected level-8 municipality")

    kept = set(relations)
    while True:
        bad = {rid for rid in kept if any(
            (typ == "n" and ref not in nodes)
            or (typ == "w" and ref not in ways)
            or (typ == "r" and ref not in kept)
            for typ, ref in relations[rid]
        )}
        if not bad:
            break
        kept -= bad
    if relation_id not in kept:
        raise ValueError(f"municipal boundary relation {relation_id} has missing members")

    primary_relations = set()
    while True:
        grown = {rid for rid in kept if rid not in primary_relations and any(
            (typ == "n" and ref in primary_nodes)
            or (typ == "w" and ways.get(ref, False))
            or (typ == "r" and ref in primary_relations)
            for typ, ref in relations[rid]
        )}
        if not grown:
            break
        primary_relations |= grown

    output = Path(output)
    manifest_path = Path(manifest_path)
    stats_path = Path(stats_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    counts, role_counts = Counter(), Counter()
    excluded = Counter()
    writer = osmium.SimpleWriter(str(output))
    with manifest_path.open("w", encoding="utf-8") as manifest:
        class Emit(osmium.SimpleHandler):
            def emit(self, obj, kind, primary, retain=True):
                tags = dict(obj.tags)
                classes = feature_classes(tags, kind)
                counts[kind] += 1
                for label in classes:
                    counts[label] += 1
                role = "primary" if primary else "dependency"
                role_counts[f"{role}_{kind}"] += 1
                if not retain:
                    excluded[kind] += 1
                manifest.write(json.dumps({"type": kind[:-1], "id": obj.id,
                                           "version": obj.version, "role": role,
                                           "classes": classes,
                                           "selection": "retained" if retain else "excluded_incomplete_relation"},
                                          ensure_ascii=False) + "\n")

            def node(self, obj):
                self.emit(obj, "nodes", obj.id in primary_nodes)
                writer.add_node(obj)

            def way(self, obj):
                self.emit(obj, "ways", ways[obj.id])
                writer.add_way(obj)

            def relation(self, obj):
                retain = obj.id in kept
                self.emit(obj, "relations", obj.id in primary_relations, retain)
                if retain:
                    writer.add_relation(obj)

        Emit().apply_file(str(source))
    writer.close()
    stats = {"boundary_relation_id": relation_id, "boundary_name": expected_name,
             "boundary_ibge_code": expected_ibge, "boundary_bounds": [west, south, east, north],
             "boundary_area_square_degrees": polygon.area,
             "source_counts": dict(counts), "role_counts": dict(role_counts),
             "excluded_incomplete": dict(excluded), "retained_relations": len(kept),
             "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("polygon", type=Path)
    parser.add_argument("relation_id", type=int)
    parser.add_argument("expected_name")
    parser.add_argument("expected_ibge")
    parser.add_argument("output", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("stats", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.polygon, args.relation_id,
                             args.expected_name, args.expected_ibge, args.output,
                             args.manifest, args.stats), ensure_ascii=False))


if __name__ == "__main__":
    main()
