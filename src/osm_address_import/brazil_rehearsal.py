"""Attest the isolated seven-city Rails rehearsal before any live append."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from osm_address_import.brazil_operator import OSAKA_SAMPLE_SQL, api_xml, db_baseline, db_sql, reference_missing, utc_now
from osm_address_import.brazil_reports import _atomic_text
from osm_address_import.docker_isolation import verify_isolated_docker


def attest(run_dir: Path, config: Path):
    spec = json.loads(config.read_text())
    project = "osaka-api-harness-" + run_dir.name
    verify_isolated_docker(project)
    container = project + "-db-1"
    baseline = json.loads((run_dir / "osaka-baseline.json").read_text())
    edit = json.loads((run_dir / "brazil-edit-rehearsal.json").read_text())
    if edit.get("state") != "PASS" or edit.get("project") != project:
        raise RuntimeError("Brazilian-object edit rehearsal has not passed")
    counts = db_baseline(container)
    if any(counts[key] <= baseline["counts"][key] for key in ("nodes", "ways", "relations")):
        raise RuntimeError("isolated database did not gain all OSM object types")
    observed = dict(line.split("|") for line in db_sql(container, OSAKA_SAMPLE_SQL).splitlines())
    if observed != baseline["hashes"]:
        raise RuntimeError("Osaka sample contents changed in isolated rehearsal")
    if (counts["users"] != baseline["counts"]["users"] + 1
            or counts["oauth_applications"] != 1
            or counts["changesets"] != baseline["counts"]["changesets"] + 1):
        raise RuntimeError("isolated account/OAuth/changeset accounting mismatch")
    missing = reference_missing(container)
    if missing != baseline["reference_missing"]:
        raise RuntimeError(f"isolated database added unresolved references: {missing}")
    base = "http://127.0.0.1:39003"
    api_xml(base, "/api/0.6/capabilities")
    passed = []
    evidence = {}
    for city in spec["cities"]:
        slug = city["slug"]
        fixture = json.loads((run_dir / f"{slug}-fixtures.json").read_text())
        city_evidence = {}
        for typ, key in (("node", "node_id"), ("way", "way_id"),
                         ("relation", "relation_id")):
            obj_id = fixture[key]
            obj = api_xml(base, f"/api/0.6/{typ}/{obj_id}").find(typ)
            if obj is None or obj.get("id") != str(obj_id):
                raise RuntimeError(f"isolated {slug} {typ} readback mismatch")
            city_evidence[typ] = obj_id
        map_root = api_xml(base, f"/api/0.6/map?bbox={fixture['bbox']}")
        if len(map_root) == 0:
            raise RuntimeError(f"isolated {slug} map bbox is empty")
        city_evidence["map_objects"] = len(map_root)
        evidence[slug] = city_evidence
        passed.append(slug)
    result = {"status": "PASS", "run_id": run_dir.name, "stage_project": project,
              "verified_at": utc_now(), "api_cities_pass": passed,
              "api_evidence": evidence, "brazil_edit_state": edit["state"],
              "brazil_edit_node_id": edit["node_id"],
              "brazil_edit_old_version": edit["old_version"],
              "brazil_edit_new_version": edit["new_version"],
              "brazil_edit_changeset_id": edit["changeset_id"],
              "osaka_hashes_match": True, "reference_missing": missing,
              "database_counts": counts}
    _atomic_text(run_dir / "rehearsal-attestation.json",
                 json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    args = parser.parse_args()
    print(attest(args.run_dir, args.config)["status"])


if __name__ == "__main__":
    main()
