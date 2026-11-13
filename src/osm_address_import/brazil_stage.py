"""Stream a reference-complete OSM PBF into Rails API staging CSV files.

Run only on a city PBF validated by ``brazil_prepare`` and ``osmium check-refs -r``.
CSV contains source versions/timestamps/IDs and synthetic changeset 0, matching
the existing private Osaka import convention. No original contributor is claimed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

TABLES = (
    "nodes", "node_tags", "ways", "way_nodes", "way_tags", "relations",
    "relation_members", "relation_tags",
)


def quad_tile(lat, lon):
    """Port of quad_tile 1.0.1: 16-bit x/y, most-significant-bit interleave."""
    x = math.floor((lon + 180.0) * 65535.0 / 360.0 + 0.5)
    y = math.floor((lat + 90.0) * 65535.0 / 180.0 + 0.5)
    if not (0 <= x <= 65535 and 0 <= y <= 65535):
        raise ValueError("node coordinate is out of QuadTile range")
    tile = 0
    for bit in range(15, -1, -1):
        tile = (tile << 1) | ((x >> bit) & 1)
        tile = (tile << 1) | ((y >> bit) & 1)
    return tile


def stage(source: Path, directory: Path):
    import osmium
    directory.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    with ExitStack() as stack:
        streams = {name: stack.enter_context((directory / f"{name}.tsv").open(
            "w", encoding="utf-8", newline="")) for name in TABLES}
        writers = {name: csv.writer(stream, delimiter="\t", quoting=csv.QUOTE_ALL,
                                    lineterminator="\n") for name, stream in streams.items()}

        def emit(table, row):
            writers[table].writerow(row)
            counts[table] += 1

        class Handler(osmium.SimpleHandler):
            def node(self, obj):
                if not obj.location.valid():
                    raise ValueError(f"node {obj.id} lacks a valid location")
                lat, lon = obj.location.lat, obj.location.lon
                stamp = obj.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                emit("nodes", (obj.id, round(lat * 10_000_000), round(lon * 10_000_000),
                               0, "t", stamp, quad_tile(lat, lon), obj.version))
                for tag in obj.tags:
                    emit("node_tags", (obj.id, tag.k, tag.v))

            def way(self, obj):
                stamp = obj.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                emit("ways", (obj.id, 0, stamp, "t", obj.version))
                for sequence, member in enumerate(obj.nodes, start=1):
                    emit("way_nodes", (obj.id, member.ref, sequence))
                for tag in obj.tags:
                    emit("way_tags", (obj.id, tag.k, tag.v))

            def relation(self, obj):
                stamp = obj.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                emit("relations", (obj.id, 0, stamp, "t", obj.version))
                for sequence, member in enumerate(obj.members, start=1):
                    emit("relation_members", (obj.id, {"n": "Node", "w": "Way",
                                                      "r": "Relation"}[member.type],
                                              member.ref, member.role, sequence))
                for tag in obj.tags:
                    emit("relation_tags", (obj.id, tag.k, tag.v))

        Handler().apply_file(str(source))
    (directory / "stage_counts.json").write_text(json.dumps(
        {name: counts[name] for name in TABLES}, indent=2, sort_keys=True) + "\n")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.directory), sort_keys=True))


if __name__ == "__main__":
    main()
