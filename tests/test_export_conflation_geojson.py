"""Offline exporter checks using synthetic run artifacts only."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import shape

from osm_address_import.building_conflation import read_osm, run, write_artifacts
from osm_address_import.export_conflation_geojson import ExportError, PRIMARY_FILES, export
from tests.test_building_conflation import LAT, LON, candidate, osm_data, square


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "run"
        data_dir = self.run_dir / "data"
        data_dir.mkdir(parents=True)
        self.source_path = data_dir / "candidates.csv"
        self.osm_path = data_dir / "osm-overpass.json"
        elements = osm_data()["elements"]
        elements += square(20, west=LON+.0009, east=LON+.0011)
        elements += square(30, tags={"addr:housenumber": "131", "addr:street": "Main Street"},
                           west=LON+.0019, east=LON+.0021)
        elements += square(40, west=LON+.0029, east=LON+.0031)
        self.osm_path.write_text(json.dumps({"elements": elements,
                                             "osm3s": {"timestamp_osm_base": "2026-11-15T00:00:00Z"}}))
        self.rows = [
            candidate("123"),
            candidate("125", longitude=LON+.001, source_location_type="unknown", positional_accuracy_m=None),
            candidate("131", longitude=LON+.002),
            candidate("141", longitude=LON+.003),
            candidate("143", longitude=LON+.00302),
            candidate("151", longitude=LON+.00012),
            candidate("161", longitude=LON+.01),
            candidate("171", longitude="bad"),
        ]
        with self.source_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.rows[0])
            writer.writeheader()
            for row in self.rows:
                writer.writerow({**row,
                                 "original_source_attributes": json.dumps(row["original_source_attributes"]),
                                 "upstream_assessment": json.dumps(row["upstream_assessment"])})
        self.osm = read_osm(self.osm_path)
        results = run(self.rows, self.osm)
        write_artifacts(self.run_dir, self.rows, self.osm, *results,
                        self.source_path, self.osm_path, .01, "synthetic box",
                        scope_bbox=[LON-.01, LAT-.01, LON+.02, LAT+.01])

    def layer(self, filename):
        return json.loads((self.run_dir / "mapviewer" / filename).read_text())

    def test_primary_counts_subset_and_flat_properties(self):
        source_before = self.source_path.read_bytes()
        osm_before = self.osm_path.read_bytes()
        report = export(self.run_dir)
        self.assertEqual(report["primary_feature_count"], 8)
        self.assertEqual(sum(report["layers"][filename]["feature_count"]
                             for filename, _ in PRIMARY_FILES.values()), 8)
        self.assertEqual(report["source_evidence_only_count"], 1)
        self.assertEqual(report["layers"]["osm_buildings.geojson"]["feature_count"], 4)
        self.assertEqual(report["layers"]["osm_addresses.geojson"]["feature_count"], 1)
        self.assertEqual(report["source_invalid_without_drawable_geometry"], 1)
        self.assertEqual(report["review_template_rows"], 8)
        self.assertEqual(self.layer("source_invalid.geojson")["features"][0]["geometry"], None)
        self.assertEqual(self.layer("source_evidence_only.geojson")["features"][0]["properties"]["primary_decision"],
                         "REVIEW_SPATIAL_AMBIGUITY")
        feature = self.layer("auto_attach_candidates.geojson")["features"][0]
        self.assertEqual(feature["properties"]["review_status"], "UNREVIEWED")
        self.assertIsInstance(feature["properties"]["reason_codes"], str)
        self.assertIsInstance(feature["properties"]["associated_osm_building"], str)
        self.assertNotIn("original_source_attributes", feature["properties"])
        for filename in ("review_conflicts.geojson", "source_duplicates.geojson"):
            self.assertEqual(self.layer(filename), {"type": "FeatureCollection", "features": []})
        self.assertEqual(self.source_path.read_bytes(), source_before)
        self.assertEqual(self.osm_path.read_bytes(), osm_before)
        with (self.run_dir / "mapviewer/review_template.csv").open(newline="") as stream:
            worksheet = list(csv.DictReader(stream))
        self.assertEqual(len(worksheet), 8)
        self.assertTrue(all(not row["final_reviewer_decision"] for row in worksheet))
        self.assertIn("test:171", {row["candidate_id"] for row in worksheet})

    def test_sample_is_stable_and_covers_required_strata(self):
        first = export(self.run_dir)
        ids = [f["id"] for f in self.layer("review_sample.geojson")["features"]]
        second = export(self.run_dir)
        self.assertEqual(ids, [f["id"] for f in self.layer("review_sample.geojson")["features"]])
        self.assertEqual(first["sample_strata"], second["sample_strata"])
        self.assertEqual(len(ids), 6)
        self.assertTrue(all(s["selected_candidate_ids"] for s in first["sample_strata"].values()))
        self.assertTrue((self.run_dir / "mapviewer/geojson_layers.zip").is_file())

    def test_building_identity_geometry_and_study_bbox(self):
        export(self.run_dir)
        buildings = self.layer("osm_buildings.geojson")["features"]
        by_id = {b["key"]: b for b in self.osm["buildings"]}
        self.assertEqual({f["id"] for f in buildings}, set(by_id))
        for feature in buildings:
            original = by_id[feature["id"]]
            self.assertEqual(feature["properties"]["osm_version"], original["object"]["version"])
            self.assertTrue(shape(feature["geometry"]).equals_exact(original["geometry"], 0))
        study = self.layer("study_area.geojson")["features"][0]
        self.assertEqual(list(shape(study["geometry"]).bounds), [LON-.01, LAT-.01, LON+.02, LAT+.01])

    def test_complex_relation_hole_is_preserved(self):
        # Replace the synthetic data with one relation whose inner ring is a hole.
        elements = osm_data()["elements"]
        for obj in elements:
            if obj["type"] == "way" and obj["id"] == 10:
                obj["tags"] = {}
        elements += square(20, tags={}, west=LON-.00002, south=LAT-.00002,
                           east=LON+.00002, north=LAT+.00002)
        elements.append({"type": "relation", "id": 55, "version": 4,
                         "tags": {"type": "multipolygon", "building": "yes"},
                         "members": [{"type": "way", "ref": 10, "role": "outer"},
                                     {"type": "way", "ref": 20, "role": "inner"}]})
        self.osm_path.write_text(json.dumps({"elements": elements}))
        row = candidate(longitude=LON+.00006)
        self.rows = [row]
        with self.source_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=row)
            writer.writeheader()
            writer.writerow({**row, "original_source_attributes": json.dumps(row["original_source_attributes"]),
                             "upstream_assessment": json.dumps(row["upstream_assessment"])})
        osm = read_osm(self.osm_path)
        write_artifacts(self.run_dir, self.rows, osm, *run(self.rows, osm),
                        self.source_path, self.osm_path, .01, "synthetic relation",
                        scope_bbox=[LON-.01, LAT-.01, LON+.01, LAT+.01])
        export(self.run_dir)
        feature = self.layer("osm_buildings.geojson")["features"][0]
        self.assertEqual(feature["id"], "relation/55")
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertEqual(len(feature["geometry"]["coordinates"]), 2)
        self.assertTrue(shape(feature["geometry"]).equals_exact(osm["buildings"][0]["geometry"], 0))

    def test_tampered_count_and_review_worksheet_are_rejected(self):
        assessment_path = self.run_dir / "import_assessment.json"
        assessment = json.loads(assessment_path.read_text())
        assessment["decisions"]["REVIEW_NO_BUILDING"] += 1
        assessment_path.write_text(json.dumps(assessment))
        with self.assertRaisesRegex(ExportError, "decision counts"):
            export(self.run_dir)
        assessment["decisions"]["REVIEW_NO_BUILDING"] -= 1
        assessment_path.write_text(json.dumps(assessment))
        export(self.run_dir)
        worksheet = self.run_dir / "mapviewer/review_template.csv"
        worksheet.write_text(worksheet.read_text() + "reviewer edit\n")
        with self.assertRaisesRegex(ExportError, "preserve reviewer edits"):
            export(self.run_dir)

    def test_output_symlink_is_rejected(self):
        out = self.run_dir / "mapviewer"
        out.mkdir()
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("unchanged")
        (out / "layers_manifest.json").symlink_to(outside)
        with self.assertRaisesRegex(ExportError, "symlink"):
            export(self.run_dir)
        self.assertEqual(outside.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
