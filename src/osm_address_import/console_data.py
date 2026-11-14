"""Read-only, bounded access to recognized OSM audit reports.

Report filenames are discovered server-side. Browser input is never a filesystem path.
"""

from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from pathlib import Path

from osm_address_import.brazil_reports import CHECK_STATUSES, METRICS, ReportError, validate_city

MAX_REPORT_BYTES = 1_000_000
SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}\Z")
SAFE_STEM = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:-attempt-[1-9][0-9]*)?\Z")
SECRET = re.compile(r"(?i)(bearer\s+[a-z0-9._-]+|(?:password|client_secret|api[_-]?key|authorization|cf-access-token)\s*[=:]\s*\S+|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def slugify(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")


def shown(value, missing="Not recorded"):
    return missing if value is None or value == "" else value


class ReportRepository:
    def __init__(self, root: str | Path, *, require_publication: bool = False):
        self.root = Path(root).resolve()
        self.require_publication = require_publication

    def _publication(self, directory: Path):
        path = directory / "publication.json"
        try:
            if not self._safe_file(path) or path.stat().st_size > 65_536:
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            files = value.get("files")
            if (value.get("schema_version") != "1.0" or value.get("run_id") != directory.name or
                    not isinstance(files, dict) or "summary.json" not in files or "osaka-baseline.json" not in files):
                return None
            if any(not re.fullmatch(r"[a-z0-9-]+\.(?:json|md)", name) or
                   not re.fullmatch(r"[0-9a-f]{64}", digest) for name, digest in files.items()):
                return None
            return files
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            return None

    def _safe_file(self, path: Path) -> bool:
        try:
            return path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root) and path.stat().st_size <= MAX_REPORT_BYTES
        except OSError:
            return False

    def _read(self, path: Path) -> str:
        if not self._safe_file(path):
            raise ReportError("report unavailable or unsafe")
        value = path.read_text(encoding="utf-8")
        if self.require_publication:
            published = self._publication(path.parent)
            if not published or published.get(path.name) != hashlib.sha256(value.encode("utf-8")).hexdigest():
                raise ReportError("report is not in the approved publication manifest")
        if SECRET.search(value):
            raise ReportError("report contains credential-like content")
        return value

    def _json(self, path: Path) -> dict:
        value = json.loads(self._read(path))
        if not isinstance(value, dict):
            raise ReportError("report must be a JSON object")
        return value

    def _run_dirs(self):
        if not self.root.is_dir():
            return
        # v1 adapter: only the existing Brazil report family is recognized.
        family = self.root / "brazil-seven-cities"
        if not family.is_dir() or family.is_symlink():
            return
        for directory in sorted(family.iterdir()):
            if (directory.is_dir() and not directory.is_symlink() and SAFE_ID.fullmatch(directory.name) and
                    (not self.require_publication or self._publication(directory))):
                yield directory

    def _scan(self):
        runs, attempts, baselines, warnings = {}, [], [], []
        for directory in self._run_dirs():
            run_id = directory.name
            published = self._publication(directory) if self.require_publication else None
            summary_path = directory / "summary.json"
            if self._safe_file(summary_path):
                try:
                    summary = self._json(summary_path)
                    if summary.get("schema_version") != "1.0" or summary.get("run_id") != run_id or summary.get("status") not in ("SUCCESS", "PARTIAL", "FAILED", "BLOCKED"):
                        raise ReportError("unsupported or inconsistent summary")
                    required = ("baseline_id", "started_at", "finished_at", "closeout_at", "total_processing_duration_seconds",
                                "retry_processing_duration_seconds", "database_size_before", "database_size_after", "osaka_validation",
                                "osaka_editor_validation", "unique_newly_inserted", "retry_attempts", "cities")
                    if any(key not in summary for key in required) or not isinstance(summary["cities"], list):
                        raise ReportError("incomplete summary")
                    if (not isinstance(summary["unique_newly_inserted"], dict) or
                            any(type(summary["unique_newly_inserted"].get(key)) is not int or
                                summary["unique_newly_inserted"][key] < 0 for key in ("nodes", "ways", "relations")) or
                            not isinstance(summary["retry_attempts"], list) or
                            not isinstance(summary["osaka_editor_validation"], dict) or
                            summary["osaka_editor_validation"].get("status") not in CHECK_STATUSES or
                            any(not isinstance(item, dict) or any(key not in item for key in ("city", "state", "status", "duration_seconds"))
                                for item in summary["cities"]) or
                            any(not isinstance(item, dict) or any(key not in item for key in ("city", "status", "started_at", "duration_seconds"))
                                for item in summary["retry_attempts"])):
                        raise ReportError("malformed summary accounting")
                    runs[run_id] = summary
                except (ReportError, ValueError, TypeError, AttributeError, UnicodeError, OSError) as exc:
                    warnings.append(f"{run_id}: summary unavailable ({exc})")
            for path in sorted(directory.glob("*.json")):
                if published is not None and path.name not in published:
                    continue
                if path.name in ("summary.json", "osaka-baseline.json") or not SAFE_STEM.fullmatch(path.stem):
                    continue
                if (path.stem.startswith(("stage-", "osaka-", "operator-", "closeout-", "rehearsal-", "brazil-")) or
                        path.stem.endswith(("-fixtures", "-source-stats", "-browser-config", "-attestation"))):
                    continue
                try:
                    report = self._json(path)
                    if "city" not in report and not re.search(r"-attempt-[1-9][0-9]*$", path.stem):
                        continue  # operational JSON is never recognized as a city audit
                    validate_city(report)
                    if report["run_id"] != run_id or slugify(report["city"]) != re.sub(r"-attempt-[1-9][0-9]*$", "", path.stem):
                        raise ReportError("city identity does not match report path")
                    attempts.append({"report": report, "run_id": run_id, "stem": path.stem,
                                     "slug": slugify(report["city"]), "archived": bool(re.search(r"-attempt-[1-9][0-9]*$", path.stem))})
                except (ReportError, ValueError, KeyError, TypeError, AttributeError, RecursionError, UnicodeError, OSError) as exc:
                    warnings.append(f"{run_id}/{path.name}: invalid city report ({exc})")
            baseline_path = directory / "osaka-baseline.json"
            if self._safe_file(baseline_path):
                try:
                    baseline = self._json(baseline_path)
                    if (not isinstance(baseline.get("counts"), dict) or not baseline.get("baseline_id") or
                            any(not isinstance(baseline["counts"].get(key), int) for key in ("nodes", "ways", "relations"))):
                        raise ReportError("invalid Osaka baseline")
                    baselines.append({"data": baseline, "run_id": run_id})
                except (ReportError, ValueError, UnicodeError, OSError) as exc:
                    warnings.append(f"{run_id}: Osaka baseline unavailable ({exc})")
        return runs, attempts, baselines, warnings

    def inventory(self):
        runs, attempts, baselines, warnings = self._scan()
        by_identity = {}
        for item in attempts:
            report = item["report"]
            # Schema 1.0 implies Brazil. A future format needs its own country field.
            identity = ("Brazil", report["relation_id"])
            by_identity.setdefault(identity, []).append(item)
        areas = []
        for history in by_identity.values():
            history.sort(key=lambda item: (item["report"].get("finished_at") or "", item["report"].get("started_at") or ""), reverse=True)
            successes = [item for item in history if item["report"]["status"] == "SUCCESS" and not item["archived"]]
            loaded = successes[0] if successes else None
            latest = history[0]
            source = (loaded or latest)["report"]
            areas.append({"name": source["city"], "slug": (loaded or latest)["slug"], "country": "Brazil",
                          "region": source["state"], "relation_id": source["relation_id"],
                          "loaded": loaded, "latest": latest, "history": history,
                          "status": "SUCCESS" if loaded else "NOT VERIFIED",
                          "validation": "PASS" if loaded else "NOT VERIFIED"})
        if baselines:
            baseline = max(baselines, key=lambda item: item["data"].get("captured_at") or "")
            preservation = next((run for run in runs.values() if run.get("baseline_id") == baseline["data"]["baseline_id"]), None)
            areas.insert(0, {"name": "Osaka", "slug": "osaka", "country": "Japan", "region": "Osaka",
                             "relation_id": None, "baseline": baseline, "loaded": None, "latest": None,
                             "history": [], "status": "NOT RECORDED", "validation": (preservation or {}).get("osaka_validation", "NOT VERIFIED"),
                             "preservation": preservation})
        areas.sort(key=lambda item: (item["slug"] != "osaka", item["name"]))
        return {"areas": areas, "runs": runs, "warnings": warnings,
                "failed_attempts": sum(item["report"]["status"] in ("FAILED", "BLOCKED") for item in attempts),
                "successful_cities": sum(area["status"] == "SUCCESS" for area in areas),
                "latest_import": max((item["report"].get("finished_at") or "" for item in attempts), default=None)}

    def city(self, slug: str):
        return next((area for area in self.inventory()["areas"] if area["slug"] == slug), None)

    def run(self, run_id: str):
        inventory = self.inventory()
        if run_id not in inventory["runs"]:
            return None
        return {"summary": inventory["runs"][run_id], "cities": [item for area in inventory["areas"] for item in area["history"] if item["run_id"] == run_id]}

    def artifact(self, run_id: str, stem: str, extension: str) -> str:
        if not SAFE_ID.fullmatch(run_id) or not SAFE_STEM.fullmatch(stem) or extension not in ("json", "md"):
            raise ReportError("unknown artifact")
        runs, attempts, _, _ = self._scan()
        if stem == "summary":
            if run_id not in runs:
                raise ReportError("unknown artifact")
        elif not any(item["run_id"] == run_id and item["stem"] == stem for item in attempts):
            raise ReportError("unknown artifact")
        return self._read(self.root / "brazil-seven-cities" / run_id / f"{stem}.{extension}")
