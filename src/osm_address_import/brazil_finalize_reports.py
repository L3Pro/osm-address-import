"""Attach measured isolated-browser evidence to live city audit reports.

The live editor status remains NOT_VERIFIED until a browser session authenticated
through the public sandbox is checked. This command never upgrades a city to
SUCCESS based solely on staging evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from osm_address_import.brazil_reports import write_city


def attach_stage_browser(run_dir: Path, config: Path):
    browser = json.loads((run_dir / "stage-browser.json").read_text())
    spec = json.loads(config.read_text())
    expected = {city["slug"] for city in spec["cities"]}
    if (browser.get("status") != "PASS"
            or browser.get("project") != f"osaka-api-harness-{run_dir.name}"
            or set(browser.get("cities", {})) != expected):
        raise ValueError("isolated browser report is missing or mismatched")
    for slug in sorted(expected):
        result = browser["cities"][slug]
        dom = result["dom"]
        if (result["status"] != "PASS" or dom["mapRequests"] <= 0
                or dom["osmPaths"] <= 0 or not dom["idRoot"]):
            raise ValueError(f"isolated editor evidence failed for {slug}")
        report = json.loads((run_dir / f"{slug}.json").read_text())
        if report["status"] != "PARTIAL" or report["validations"]["editor"]["status"] != "NOT_VERIFIED":
            raise ValueError(f"unexpected live report state for {slug}")
        report["validations"]["editor"]["evidence"] = (
            f"Authenticated isolated Firefox iD: PASS; {dom['mapRequests']} API map requests "
            f"and {dom['osmPaths']} OSM paths rendered at city center. "
            "Live Cloudflare-authenticated browser session: NOT_VERIFIED."
        )
        write_city(run_dir, slug, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    args = parser.parse_args()
    attach_stage_browser(args.run_dir, args.config)
    print("Attached isolated iD evidence to seven city reports; live editor remains NOT_VERIFIED")


if __name__ == "__main__":
    main()
