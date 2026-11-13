"""Reproduce seven polygon extracts, complete relations, manifests, and CSV stages.

Run with a pinned Geofabrik Brazil PBF and the versioned city configuration.
The work directory must be private and Git-ignored; extraction is sequential to
bound memory. No database is accessed by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from osm_address_import.brazil_fixtures import fixtures
from osm_address_import.brazil_prepare import prepare
from osm_address_import.brazil_stage import stage


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def call(args):
    subprocess.run(args, check=True)


def run(source: Path, config: Path, work_dir: Path, run_dir: Path, osmium_bin: str):
    import osmium
    from shapely.geometry import shape

    spec = json.loads(config.read_text())
    if sha256(source) != spec["source_sha256"]:
        raise ValueError("pinned Geofabrik source SHA-256 mismatch")
    header = subprocess.run([osmium_bin, "fileinfo", str(source)],
                            capture_output=True, text=True, check=True).stdout
    if spec["source_snapshot_at"] not in header:
        raise ValueError("PBF replication timestamp differs from city configuration")
    work_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    boundary_file = work_dir / "seven-boundaries.osm.pbf"
    call([osmium_bin, "getid", "-r", str(source),
          *(f"r{city['relation_id']}" for city in spec["cities"]),
          "-o", str(boundary_file), "--overwrite"])
    observed = {}

    class Boundaries(osmium.SimpleHandler):
        def relation(self, obj):
            observed[obj.id] = {"tags": dict(obj.tags), "version": obj.version,
                                "timestamp": str(obj.timestamp)}

    Boundaries().apply_file(str(boundary_file))
    for city in spec["cities"]:
        info = observed.get(city["relation_id"])
        if not info or any(info["tags"].get(key) != expected for key, expected in (
            ("name", city["name"]), ("boundary", "administrative"),
            ("admin_level", "8"), ("IBGE:GEOCODIGO", city["ibge_code"])
        )):
            raise ValueError(f"invalid municipal boundary relation for {city['slug']}")
    geometry_file = work_dir / "seven-boundaries.geojsonseq"
    call([osmium_bin, "export", str(boundary_file), "--geometry-types=polygon",
          "--add-unique-id=type_id", "-o", str(geometry_file), "--overwrite",
          "--stop-on-error"])
    features = {}
    for line in geometry_file.read_text().splitlines():
        if line.strip():
            feature = json.loads(line.lstrip("\x1e"))
            features[feature["id"]] = feature
    receipts = []
    for city in spec["cities"]:
        slug = city["slug"]
        area_id = f"a{2 * city['relation_id'] + 1}"
        feature = features.get(area_id)
        if feature is None or not shape(feature["geometry"]).is_valid:
            raise ValueError(f"missing or invalid polygon geometry for {slug}")
        polygon = work_dir / f"{slug}.geojson"
        polygon.write_text(json.dumps(feature, ensure_ascii=False) + "\n")
        raw = work_dir / f"{slug}.osm.pbf"
        complete = work_dir / f"{slug}-complete.osm.pbf"
        call([osmium_bin, "extract", "-s", "smart", "-S", "types=multipolygon",
              "-p", str(polygon), str(source), "-o", str(raw), "--overwrite"])
        stats = prepare(raw, polygon, city["relation_id"], city["name"],
                        city["ibge_code"], complete,
                        run_dir / f"{slug}-manifest.jsonl",
                        run_dir / f"{slug}-source-stats.json")
        call([osmium_bin, "check-refs", "-r", str(complete)])
        counts = stage(complete, work_dir / f"{slug}-stage")
        fixture = fixtures(complete, polygon, city["relation_id"])
        (run_dir / f"{slug}-fixtures.json").write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
        receipts.append({"city": slug, "relation_version": observed[city["relation_id"]]["version"],
                         "relation_timestamp": observed[city["relation_id"]]["timestamp"],
                         "source_counts": stats["source_counts"],
                         "excluded_incomplete": stats["excluded_incomplete"],
                         "stage_counts": dict(counts)})
    (run_dir / "extraction-receipts.json").write_text(
        json.dumps({"source_sha256": spec["source_sha256"], "cities": receipts},
                   indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--osmium", default="osmium")
    args = parser.parse_args()
    run(args.source, args.config, args.work_dir, args.run_dir, args.osmium)


if __name__ == "__main__":
    main()
