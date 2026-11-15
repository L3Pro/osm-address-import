"""Synthetic deterministic tests; no network, API, or sandbox access."""

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from osm_address_import.building_conflation import (
    address_key, candidate_address, normalized_street, read_candidates, read_osm,
    run, validate_candidate, write_artifacts,
)

LON, LAT = -95.0, 30.0


def candidate(number="123", street="Main Street", **overrides):
    row = {"schema_version": "1.0", "candidate_id": "test:" + number,
           "source_dataset": "Synthetic government", "source_record_id": number,
           "source_dataset_version": "2026-01-01", "source_license": "test permission",
           "source_permission_status": "PENDING_OSM_REVIEW", "house_number": number,
           "street_name": street, "street_prefix": "", "street_suffix": "",
           "unit": "", "city": "Test", "state": "TX", "zip_code": "77380",
           "latitude": LAT, "longitude": LON, "crs": "EPSG:4326",
           "source_location_type": "rooftop", "positional_accuracy_m": 2,
           "original_source_attributes": {"raw": "preserved"},
           "upstream_assessment": {"classification": "missing"}}
    row.update(overrides)
    return row


def square(way_id=10, tags=None, west=LON - .0001, south=LAT - .0001,
           east=LON + .0001, north=LAT + .0001):
    pts = [(west, south), (east, south), (east, north), (west, north)]
    nodes = [{"type": "node", "id": way_id * 10 + i,
              "version": 1, "lon": x, "lat": y, "tags": {}} for i, (x, y) in enumerate(pts)]
    way = {"type": "way", "id": way_id, "version": 7,
           "nodes": [n["id"] for n in nodes] + [nodes[0]["id"]],
           "tags": {"building": "yes", "name": "Original", **(tags or {})}}
    return nodes + [way]


def osm_data(extra=None, base_tags=None):
    elements = square(tags=base_tags) + [{"type": "way", "id": 77, "version": 1,
                             "tags": {"highway": "residential", "name": "Main Street"},
                             "nodes": [100, 101]}] + (extra or [])
    return {"elements": elements, "osm3s": {"timestamp_osm_base": "2026-11-14T00:00:00Z"}}


class ConflationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def osm(self, extra=None, base_tags=None):
        path = self.path / "osm.json"
        path.write_text(json.dumps(osm_data(extra, base_tags)))
        return read_osm(path), path

    def decide(self, rows, extra=None, base_tags=None):
        return run(rows, self.osm(extra, base_tags)[0])

    def test_street_number_unit_semantics(self):
        self.assertEqual(normalized_street("N. Main St"), normalized_street("North Main Street"))
        self.assertEqual(address_key("123 A", "Main St"), address_key("123A", "MAIN STREET"))
        self.assertNotEqual(address_key("123", "Main St", "2"), address_key("123", "Main St", "3"))
        self.assertNotEqual(address_key("123A", "Main St"), address_key("123B", "Main St"))

    def test_single_building_update_preserves_identity_tags_and_refs(self):
        osm, path = self.osm()
        before = path.read_bytes()
        results, updates, review, _, _ = run([candidate()], osm)
        self.assertEqual(results[0]["primary_decision"], "AUTO_ATTACH_CANDIDATE")
        self.assertEqual(len(updates), 1)
        update = updates[0]
        self.assertEqual((update["target_osm_type"], update["target_osm_id"], update["target_osm_version"]), ("way", 10, 7))
        self.assertEqual(update["proposed_tags"]["name"], "Original")
        self.assertEqual(update["original_tags"], {"building": "yes", "name": "Original"})
        self.assertEqual(update["added_tags"], {"addr:housenumber": "123", "addr:street": "Main Street"})
        self.assertEqual(update["preserved_geometry"]["node_references"], [100, 101, 102, 103, 100])
        self.assertFalse(update["execution_authorized"])
        self.assertEqual(update["source_provenance"]["original_source_attributes"], {"raw": "preserved"})
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(review)

    def test_multiple_distinct_addresses_review_all(self):
        rows = [candidate(), candidate("125", longitude=LON + .00002)]
        results, updates, _, _, _ = self.decide(rows)
        self.assertEqual([r["primary_decision"] for r in results], ["REVIEW_MULTIPLE_ADDRESSES"] * 2)
        self.assertEqual(updates, [])

    def test_units_review_all(self):
        rows = [candidate(candidate_id="a", source_record_id="a", unit="1"),
                candidate(candidate_id="b", source_record_id="b", unit="2")]
        results, updates, _, _, _ = self.decide(rows)
        self.assertEqual([r["primary_decision"] for r in results], ["REVIEW_MULTIPLE_ADDRESSES"] * 2)
        self.assertEqual(updates, [])

    def test_source_duplicates_and_inconsistent_id(self):
        rows = [candidate(), candidate(candidate_id="new", source_record_id="new"),
                candidate("125", candidate_id="test:123")]
        results, updates, _, _, _ = self.decide(rows)
        self.assertEqual([r["primary_decision"] for r in results],
                         ["SOURCE_INVALID", "SOURCE_DUPLICATE", "SOURCE_INVALID"])
        self.assertEqual(len(updates), 0)

    def test_inconsistent_duplicate_geometry_invalidates_both(self):
        rows = [candidate(), candidate(candidate_id="second", source_record_id="second", longitude=LON + .01)]
        results, updates, _, _, _ = self.decide(rows)
        self.assertEqual([r["primary_decision"] for r in results], ["SOURCE_INVALID"] * 2)
        self.assertFalse(updates)

    def test_candidate_csv_adapter_uses_same_interface(self):
        row = candidate()
        path = self.path / "candidates.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=row)
            writer.writeheader()
            writer.writerow({**row, "original_source_attributes": json.dumps(row["original_source_attributes"]),
                             "upstream_assessment": json.dumps(row["upstream_assessment"])})
        loaded = read_candidates(path, "candidate-csv")
        self.assertEqual(loaded[0]["original_source_attributes"], {"raw": "preserved"})
        self.assertEqual(run(loaded, self.osm()[0])[0][0]["primary_decision"], "AUTO_ATTACH_CANDIDATE")

    def test_osm_api_xml_adapter_keeps_versions_and_refs(self):
        path = self.path / "map.osm"
        nodes = "".join(f'<node id="{100+i}" version="1" lon="{x}" lat="{y}" />' for i, (x, y) in
                        enumerate(((LON-.0001,LAT-.0001),(LON+.0001,LAT-.0001),
                                   (LON+.0001,LAT+.0001),(LON-.0001,LAT+.0001))))
        path.write_text('<osm version="0.6">' + nodes +
                        '<way id="10" version="7"><nd ref="100"/><nd ref="101"/><nd ref="102"/><nd ref="103"/><nd ref="100"/>'
                        '<tag k="building" v="yes"/></way>'
                        '<way id="77" version="1"><tag k="highway" v="residential"/><tag k="name" v="Main Street"/></way></osm>')
        osm = read_osm(path)
        result, updates, _, _, _ = run([candidate()], osm)
        self.assertEqual(result[0]["primary_decision"], "AUTO_ATTACH_CANDIDATE")
        self.assertEqual(updates[0]["preserved_geometry"]["node_references"], [100,101,102,103,100])

    def test_osm_unit_evidence_blocks_attachment(self):
        marker = {"type": "node", "id": 901, "version": 1, "lon": LON, "lat": LAT,
                  "tags": {"entrance": "yes", "addr:unit": "A"}}
        results, updates, _, _, _ = self.decide([candidate()], [marker])
        self.assertEqual(results[0]["primary_decision"], "REVIEW_MULTIPLE_ADDRESSES")
        self.assertFalse(updates)

    def test_existing_building_address(self):
        results, updates, _, _, _ = self.decide([candidate()], base_tags={"addr:housenumber": "123", "addr:street": "Main St"})
        self.assertEqual(results[0]["primary_decision"], "ALREADY_MAPPED")
        self.assertEqual(updates, [])

    def test_existing_entrance_and_standalone_node(self):
        for tags in ({"entrance": "yes", "addr:housenumber": "123", "addr:street": "Main Street"},
                     {"addr:housenumber": "123", "addr:street": "Main Street"}):
            with self.subTest(tags=tags):
                node = {"type": "node", "id": 900, "version": 2, "lon": LON,
                        "lat": LAT, "tags": tags}
                results, updates, _, _, _ = self.decide([candidate()], [node])
                self.assertEqual(results[0]["primary_decision"], "ALREADY_MAPPED")
                self.assertIn("node/900", results[0]["existing_osm_addresses"])
                self.assertEqual(updates, [])

    def test_conflict_preserves_existing(self):
        results, updates, _, _, _ = self.decide([candidate()], base_tags={"addr:housenumber": "125", "addr:street": "Main Street"})
        self.assertEqual(results[0]["primary_decision"], "REVIEW_CONFLICT")
        self.assertTrue(results[0]["conflicting_values"])
        self.assertEqual(updates, [])
        results, updates, _, _, _ = self.decide([candidate()], base_tags={"addr:place": "Village"})
        self.assertEqual(results[0]["primary_decision"], "REVIEW_CONFLICT")
        self.assertEqual(updates, [])

    def test_boundary_and_competing_buildings(self):
        r, updates, _, _, _ = self.decide([candidate(longitude=LON + .000099)])
        self.assertEqual(r[0]["primary_decision"], "REVIEW_SPATIAL_AMBIGUITY")
        self.assertIn("NEAR_BUILDING_BOUNDARY", r[0]["reason_codes"])
        self.assertEqual(updates, [])
        other = square(way_id=20, west=LON - .00006, east=LON + .00006)
        r, updates, _, _, _ = self.decide([candidate()], other)
        self.assertEqual(r[0]["primary_decision"], "REVIEW_SPATIAL_AMBIGUITY")
        self.assertIn("OVERLAPPING_BUILDINGS", r[0]["reason_codes"])

    def test_outside_building_never_nearest_auto(self):
        r, updates, _, _, _ = self.decide([candidate(longitude=LON + .00012)])
        self.assertEqual(r[0]["primary_decision"], "REVIEW_SPATIAL_AMBIGUITY")
        self.assertEqual(updates, [])
        r, updates, _, _, _ = self.decide([candidate(longitude=LON + .01)])
        self.assertEqual(r[0]["primary_decision"], "REVIEW_NO_BUILDING")

    def test_invalid_geometry(self):
        elements = osm_data()["elements"]
        for obj in elements:
            if obj["type"] == "way" and obj["id"] == 10:
                obj["nodes"] = [100, 102, 101, 103, 100]
        path = self.path / "invalid.json"
        path.write_text(json.dumps({"elements": elements}))
        osm = read_osm(path)
        self.assertIn("way/10", osm["invalid_buildings"])
        r, updates, _, _, _ = run([candidate()], osm)
        self.assertEqual(r[0]["primary_decision"], "REVIEW_NO_BUILDING")
        self.assertFalse(updates)

    def test_multipolygon_relation_update(self):
        elements = osm_data()["elements"]
        for x in elements:
            if x["type"] == "way" and x["id"] == 10:
                x["tags"] = {}
        elements.append({"type": "relation", "id": 55, "version": 4,
                         "tags": {"type": "multipolygon", "building": "yes", "name": "Hall"},
                         "members": [{"type": "way", "ref": 10, "role": "outer"}]})
        path = self.path / "relation.json"
        path.write_text(json.dumps({"elements": elements}))
        r, updates, _, _, _ = run([candidate()], read_osm(path))
        self.assertEqual(r[0]["primary_decision"], "AUTO_ATTACH_CANDIDATE")
        self.assertEqual((updates[0]["target_osm_type"], updates[0]["target_osm_id"], updates[0]["target_osm_version"]),
                         ("relation", 55, 4))
        self.assertEqual(updates[0]["preserved_geometry"]["relation_members"],
                         [{"type": "way", "ref": 10, "role": "outer"}])

    def test_non_rooftop_and_missing_evidence(self):
        for changes in ({"source_location_type": "parcel"}, {"source_location_type": "unknown"},
                        {"positional_accuracy_m": None}, {"positional_accuracy_m": 20},
                        {"source_license": ""}):
            with self.subTest(changes=changes):
                r, updates, _, _, _ = self.decide([candidate(**changes)])
                self.assertNotEqual(r[0]["primary_decision"], "AUTO_ATTACH_CANDIDATE")
                self.assertEqual(updates, [])

    def test_invalid_coordinates_crs_and_schema(self):
        for changes in ({"longitude": 200}, {"latitude": "n/a"}, {"crs": "EPSG:3857"},
                        {"schema_version": "2.0"}, {"original_source_attributes": None}):
            with self.subTest(changes=changes):
                self.assertTrue(validate_candidate(candidate(**changes)))

    def test_osm_only_separate_observation(self):
        node = {"type": "node", "id": 900, "version": 2, "lon": LON, "lat": LAT,
                "tags": {"addr:housenumber": "999", "addr:street": "Main Street"}}
        results, _, _, osm_only, _ = self.decide([candidate()], [node])
        self.assertEqual(len(results), 1)
        self.assertEqual(osm_only[0]["osm_object"], "node/900")

    def test_artifacts_and_exclusive_counts(self):
        osm, osm_path = self.osm()
        source_path = self.path / "candidates.csv"
        source_path.write_text("synthetic input checksum only\n")
        rows = [candidate(), candidate(candidate_id="duplicate", source_record_id="duplicate")]
        parts = run(rows, osm)
        assessment = write_artifacts(self.path / "output", rows, osm, *parts,
                                     source_path, osm_path, .01, "synthetic area")
        self.assertEqual(sum(assessment["decisions"].values()), 2)
        self.assertEqual(assessment["proposed_osm_modifications"], 1)
        self.assertEqual(json.loads((self.path / "output/manual_review.geojson").read_text())["type"],
                         "FeatureCollection")
        self.assertFalse(json.loads((self.path / "output/proposed_building_updates.json").read_text())["updates"][0]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
