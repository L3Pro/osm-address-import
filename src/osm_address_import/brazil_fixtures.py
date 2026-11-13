"""Choose reproducible API fixtures from a prepared municipal PBF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fixtures(source: Path, polygon_path: Path, relation_id: int):
    import osmium
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    polygon = shape(json.loads(polygon_path.read_text())["geometry"])
    spatial = prep(polygon)
    nodes = {}
    sample_node = None
    sample_way = None
    anchor = None

    class Handler(osmium.SimpleHandler):
        def node(self, obj):
            nonlocal sample_node
            nodes[obj.id] = (obj.location.lon, obj.location.lat)
            if sample_node is None and obj.location.valid() and obj.tags and spatial.intersects(
                Point(obj.location.lon, obj.location.lat)
            ):
                sample_node = (obj.id, obj.version)

        def way(self, obj):
            nonlocal sample_way, anchor
            if sample_way is not None or obj.tags.get("highway") in (None, "no"):
                return
            for member in obj.nodes:
                if member.ref in nodes and spatial.intersects(Point(*nodes[member.ref])):
                    sample_way = (obj.id, obj.version)
                    anchor = nodes[member.ref]
                    break

    Handler().apply_file(str(source))
    if not sample_node or not sample_way or not anchor:
        raise ValueError("city lacks a tagged node or in-boundary highway way fixture")
    lon, lat = anchor
    return {"node_id": sample_node[0], "node_version": sample_node[1],
            "way_id": sample_way[0], "way_version": sample_way[1],
            "relation_id": relation_id,
            "bbox": ",".join(f"{value:.7f}" for value in (
                lon - 0.001, lat - 0.001, lon + 0.001, lat + 0.001
            )), "editor_center": {"lon": lon, "lat": lat}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("polygon", type=Path)
    parser.add_argument("relation_id", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(fixtures(args.source, args.polygon,
                                               args.relation_id), indent=2) + "\n")


if __name__ == "__main__":
    main()
