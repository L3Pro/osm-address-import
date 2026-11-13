"""Capture the fresh, read-only Osaka preservation baseline before live append."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from osm_address_import.brazil_operator import (
    LIVE_CONTAINER, OSAKA_SAMPLE_SQL, db_baseline, db_sql, reference_missing, utc_now,
)
from osm_address_import.brazil_reports import _atomic_text


def capture(output: Path):
    counts = db_baseline(LIVE_CONTAINER)
    hashes = dict(line.split("|") for line in db_sql(
        LIVE_CONTAINER, OSAKA_SAMPLE_SQL).splitlines())
    if set(hashes) != {"node", "way", "relation"} or any(not value for value in hashes.values()):
        raise RuntimeError("an Osaka preservation fixture is missing")
    result = {"captured_at": utc_now(), "container": LIVE_CONTAINER,
              "counts": counts, "hashes": hashes,
              "reference_missing": reference_missing(LIVE_CONTAINER),
              "sample_ids": {"node": 13950191959, "way": 658187857,
                             "relation": 20979587}}
    canonical = json.dumps(result, sort_keys=True).encode()
    result["baseline_id"] = "osaka-" + hashlib.sha256(canonical).hexdigest()[:16]
    _atomic_text(output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result["baseline_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(capture(args.output))


if __name__ == "__main__":
    main()
