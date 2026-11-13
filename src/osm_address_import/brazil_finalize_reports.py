"""Attach staged browser evidence and explicitly attested live editor evidence.

Live visual inspection proves the editor can load and display features. It does
not prove that a live write was accepted. Import timestamps and object accounting
are never changed by this closeout command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from osm_address_import.brazil_reports import CRITICAL_CHECKS, validate_city, write_city

OSAKA_SLUG = "osaka"


def validate_live_attestation(attestation: dict, run_id: str, city_slugs: set[str]):
    if (attestation.get("schema_version") != "1.0"
            or attestation.get("run_id") != run_id
            or attestation.get("evidence_type") != "operator-attested live visual inspection"
            or attestation.get("site") != "https://osm-sandbox.mapviewer.ai"
            or not attestation.get("recorded_at")
            or set(attestation.get("areas", {})) != city_slugs | {OSAKA_SLUG}
            or attestation.get("live_edits_saved") is not False
            or attestation.get("live_write_verified") is not False):
        raise ValueError("live editor attestation is incomplete or mismatched")
    for slug, observation in attestation["areas"].items():
        if (observation.get("status") != "PASS"
                or observation.get("osm_features") is not True
                or observation.get("aerial_imagery") is not True
                or observation.get("editing_controls") is not True):
            raise ValueError(f"live visual attestation is incomplete for {slug}")
    screenshots = attestation.get("screenshots", {})
    if (screenshots.get("reported_by_operator") is not True
            or screenshots.get("files_supplied_to_agent") is not False):
        raise ValueError("screenshot provenance must be explicit")


def finalize_live_editor(run_dir: Path, config: Path, attestation_path: Path):
    spec = json.loads(config.read_text())
    slugs = {city["slug"] for city in spec["cities"]}
    if len(slugs) != 7:
        raise ValueError("expected seven distinct municipalities")
    attestation_bytes = attestation_path.read_bytes()
    attestation = json.loads(attestation_bytes)
    validate_live_attestation(attestation, run_dir.name, slugs)
    digest = hashlib.sha256(attestation_bytes).hexdigest()
    browser = json.loads((run_dir / "stage-browser.json").read_text())
    if (browser.get("status") != "PASS"
            or browser.get("project") != f"osaka-api-harness-{run_dir.name}"
            or set(browser.get("cities", {})) != slugs):
        raise ValueError("seven-city staged editor evidence is incomplete")
    reports = {}
    for slug in sorted(slugs):
        report = json.loads((run_dir / f"{slug}.json").read_text())
        validate_city(report)
        if report["run_id"] != run_dir.name or report["errors"]:
            raise ValueError(f"{slug} import has a mismatched run or unresolved error")
        if report["status"] == "SUCCESS" and report.get("closeout", {}).get("attestation_sha256") == digest:
            continue
        if report["status"] != "PARTIAL" or report["validations"]["editor"]["status"] != "NOT_VERIFIED":
            raise ValueError(f"unexpected pre-closeout state for {slug}")
        if any(report["validations"][key]["status"] != "PASS"
               for key in CRITICAL_CHECKS if key != "editor"):
            raise ValueError(f"{slug} has another unverified or failed critical check")
        stage = browser["cities"][slug]
        if (stage.get("status") != "PASS" or stage["dom"]["mapRequests"] <= 0
                or stage["dom"]["osmPaths"] <= 0):
            raise ValueError(f"{slug} staged editor evidence is incomplete")
        reports[slug] = report
    for slug, report in reports.items():
        prior = report["validations"]["editor"].copy()
        warning = "Editor rendering requires browser verification before SUCCESS"
        resolved = [item for item in report["warnings"] if item == warning]
        report["warnings"] = [item for item in report["warnings"] if item != warning]
        report["closeout"] = {
            "recorded_at": attestation["recorded_at"],
            "evidence_type": attestation["evidence_type"],
            "attestation_file": attestation_path.name,
            "attestation_sha256": digest,
            "previous_editor_validation": prior,
            "resolved_warnings": resolved,
            "live_edits_saved": False,
            "live_write_verified": False,
            "screenshots_reported_by_operator": True,
            "screenshot_files_supplied_to_agent": False,
        }
        report["validations"]["editor"] = {
            "status": "PASS",
            "evidence": (f"{prior['evidence'].split(' Live Cloudflare-authenticated browser session: NOT_VERIFIED.')[0]} "
                         "Operator-attested live visual PASS via "
                         f"Cloudflare Access, received {attestation['recorded_at']}: OSM "
                         "features, aerial imagery, and editing controls visible. "
                         "Screenshots reported by operator; files not supplied to agent. "
                         "No live edit saved; live write NOT_VERIFIED."),
        }
        report["status"] = "SUCCESS" if all(
            report["validations"][key]["status"] == "PASS" for key in CRITICAL_CHECKS
        ) and not report["errors"] else "PARTIAL"
        write_city(run_dir, slug, report)
    from osm_address_import.brazil_summary import summarize
    return summarize(run_dir, config)


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
    parser.add_argument("action", nargs="?", choices=("attach-stage-browser", "finalize-live-editor"),
                        default="attach-stage-browser")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/brazil_seven_cities.json"))
    parser.add_argument("--attestation", type=Path)
    args = parser.parse_args()
    if args.action == "finalize-live-editor":
        if args.attestation is None:
            parser.error("--attestation is required for finalize-live-editor")
        print(finalize_live_editor(args.run_dir, args.config, args.attestation)["status"])
    else:
        attach_stage_browser(args.run_dir, args.config)
        print("Attached isolated iD evidence to seven city reports; live editor remains NOT_VERIFIED")


if __name__ == "__main__":
    main()
