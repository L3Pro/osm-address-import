"""Build the consolidated seven-city audit from the per-city execution reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from osm_address_import.brazil_reports import write_summary


def summarize(run_dir: Path, config: Path):
    spec = json.loads(config.read_text())
    reports = [json.loads((run_dir / f"{city['slug']}.json").read_text())
               for city in spec["cities"]]
    baseline = json.loads((run_dir / "osaka-baseline.json").read_text())
    start = min(item["started_at"] for item in reports if item["started_at"])
    finish = max(item["finished_at"] for item in reports if item["finished_at"])
    last_size = next((item["database"]["size_after"] for item in sorted(
                      reports, key=lambda item: item["finished_at"] or "", reverse=True)
                      if item["database"]["size_after"] is not None), None)
    return write_summary(run_dir, reports, started_at=start, finished_at=finish,
                         database_size_before=baseline["counts"]["size"],
                         database_size_after=last_size,
                         baseline_id=baseline["baseline_id"], run_id=run_dir.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    args = parser.parse_args()
    print(summarize(args.run_dir, args.config)["status"])


if __name__ == "__main__":
    main()
