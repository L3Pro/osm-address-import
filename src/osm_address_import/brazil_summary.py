"""Build the consolidated seven-city audit from the per-city execution reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from osm_address_import.brazil_reports import write_summary
from osm_address_import.brazil_finalize_reports import validate_live_attestation


def summarize(run_dir: Path, config: Path):
    spec = json.loads(config.read_text())
    reports = [json.loads((run_dir / f"{city['slug']}.json").read_text())
               for city in spec["cities"]]
    retry_attempts = [json.loads(path.read_text()) for path in sorted(
        run_dir.glob("*-attempt-*.json"))]
    attestation_path = run_dir / "operator-live-editor-attestation.json"
    attestation = None
    osaka_editor = None
    if attestation_path.exists():
        attestation = json.loads(attestation_path.read_text())
        validate_live_attestation(attestation, run_dir.name,
                                  {city["slug"] for city in spec["cities"]})
        osaka_editor = {"status": "PASS", "evidence": (
            f"Operator-attested authenticated iD visual inspection via Cloudflare Access, "
            f"received {attestation['recorded_at']}; OSM features, aerial imagery, and "
            "editing controls visible. Screenshot files not supplied to agent; no live edit saved."
        )}
    baseline = json.loads((run_dir / "osaka-baseline.json").read_text())
    start = min(item["started_at"] for item in reports + retry_attempts if item["started_at"])
    finish = max(item["finished_at"] for item in reports if item["finished_at"])
    last_size = next((item["database"]["size_after"] for item in sorted(
                      reports, key=lambda item: item["finished_at"] or "", reverse=True)
                      if item["database"]["size_after"] is not None), None)
    return write_summary(run_dir, reports, started_at=start, finished_at=finish,
                         database_size_before=baseline["counts"]["size"],
                         database_size_after=last_size,
                         baseline_id=baseline["baseline_id"], run_id=run_dir.name,
                         retry_attempts=retry_attempts,
                         osaka_editor_validation=osaka_editor,
                         live_editor_attestation={"recorded_at": attestation["recorded_at"],
                                                  "evidence_type": attestation["evidence_type"],
                                                  "file": attestation_path.name,
                                                  "live_write_verified": False}
                         if attestation else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    args = parser.parse_args()
    print(summarize(args.run_dir, args.config)["status"])


if __name__ == "__main__":
    main()
