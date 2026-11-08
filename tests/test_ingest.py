import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from osm_address_import.ingest.normalize import address_key, normalize_row
from osm_address_import.ingest.pipeline import ingest, run
from osm_address_import.ingest.schema import SchemaError, load_manifest, read_pinned_csv


FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_addresses.csv"
MANIFEST = ROOT / "tests" / "fixtures" / "synthetic_manifest.json"


def row(**changes):
    result = {
        "source_record_id": "X1", "source_authority": "Synthetic Fixture Authority",
        "house_number": "100", "pre_directional": "", "street_name": "Fiction",
        "street_suffix": "Street", "post_directional": "", "unit_type": "",
        "unit_id": "", "locality": "Example Town", "state": "TX",
        "county_id": "SYN-TX-001", "postcode": "77001",
        "longitude": "-95.5", "latitude": "29.5",
    }
    result.update(changes)
    return result


class NormalizationTests(unittest.TestCase):
    def test_direction_and_suffix_equivalence_in_dedicated_fields(self):
        a = normalize_row(row(pre_directional="North", street_suffix="Road"))
        b = normalize_row(row(pre_directional="N", street_suffix="RD"))
        self.assertEqual(address_key(a), address_key(b))

    def test_street_name_is_not_parsed_or_guessed(self):
        self.assertNotEqual(address_key(normalize_row(row(street_name="North Fiction"))),
                            address_key(normalize_row(row(street_name="N Fiction"))))
        self.assertNotEqual(address_key(normalize_row(row(street_name="St John"))),
                            address_key(normalize_row(row(street_name="Saint John"))))
        self.assertNotEqual(address_key(normalize_row(row(street_name="Straße"))),
                            address_key(normalize_row(row(street_name="STRASSE"))))

    def test_house_number_punctuation_and_zeroes_remain(self):
        self.assertEqual(normalize_row(row(house_number=" 0012-14 "))["house_number"], "0012-14")
        self.assertNotEqual(normalize_row(row(house_number="0012"))["house_number"],
                            normalize_row(row(house_number="12"))["house_number"])

    def test_unit_type_equivalence_but_unit_id_distinction(self):
        a = normalize_row(row(unit_type="Apartment", unit_id="01"))
        b = normalize_row(row(unit_type="APT", unit_id="01"))
        c = normalize_row(row(unit_type="APT", unit_id="1"))
        self.assertEqual(address_key(a), address_key(b))
        self.assertNotEqual(address_key(a), address_key(c))

    def test_postcode_is_preserved_as_comparison_value(self):
        self.assertEqual(normalize_row(row(postcode="77001-1234"))["postcode"], "77001-1234")
        with self.assertRaisesRegex(ValueError, "INVALID_POSTCODE"):
            normalize_row(row(postcode="770011234"))

    def test_partial_unit_is_rejected(self):
        for changes in ({"unit_type": "APT"}, {"unit_id": "2"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "UNIT_INCOMPLETE"):
                normalize_row(row(**changes))

    def test_house_number_must_not_be_invented(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_INCOMPLETE"):
            normalize_row(row(house_number=""))
        with self.assertRaisesRegex(ValueError, "INVALID_HOUSE_NUMBER"):
            normalize_row(row(house_number="unknown"))


class IngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_manifest(MANIFEST)

    def test_fixture_reconciles_and_preserves_original_values(self):
        accepted, rejected, report = ingest(read_pinned_csv(FIXTURE, self.manifest["sha256"]), self.manifest)
        self.assertEqual((report["input"], report["accepted"], report["rejected"]), (14, 5, 9))
        self.assertEqual((report["duplicates"], report["conflicts"], report["units_accepted"]), (1, 2, 2))
        self.assertEqual(sum(report["rejection_reasons"].values()), report["rejected"])
        self.assertEqual({item["source"]["source_record_id"] for item in accepted}, {"S1", "S3", "S4", "S12", "S13"})
        self.assertEqual(next(item for item in accepted if item["source"]["source_record_id"] == "S1")["original"]["pre_directional"], "North")
        self.assertTrue(all(item["source"]["input_sha256"] == self.manifest["sha256"] for item in accepted + rejected))

    def test_unit_rows_remain_separate_and_flagged(self):
        accepted, _, _ = ingest([row(source_record_id="A", unit_type="APT", unit_id="1"),
                                 row(source_record_id="B", unit_type="APT", unit_id="2")], self.manifest)
        self.assertEqual(len(accepted), 2)
        self.assertEqual({item["normalized"]["unit_id"] for item in accepted}, {"1", "2"})
        self.assertTrue(all(item["class_a_source_exclusion"] == "UNIT_PRESENT" for item in accepted))

    def test_duplicate_address_selects_stable_source_id(self):
        accepted, rejected, report = ingest([row(source_record_id="Z"), row(source_record_id="A", street_suffix="ST")], self.manifest)
        self.assertEqual(accepted[0]["source"]["source_record_id"], "A")
        self.assertEqual(rejected[0]["reason_code"], "SOURCE_DUPLICATE")
        self.assertEqual(report["duplicates"], 1)

    def test_same_source_id_conflict_rejects_both(self):
        accepted, rejected, _ = ingest([row(), row(street_name="Other")], self.manifest)
        self.assertEqual(len(accepted), 0)
        self.assertEqual([item["reason_code"] for item in rejected], ["SOURCE_ID_CONFLICT"] * 2)

    def test_address_coordinate_conflict_rejects_both(self):
        accepted, rejected, _ = ingest([row(source_record_id="A"), row(source_record_id="B", latitude="29.5001")], self.manifest)
        self.assertEqual(len(accepted), 0)
        self.assertEqual([item["reason_code"] for item in rejected], ["ADDRESS_CONFLICT"] * 2)

    def test_address_postcode_conflict_rejects_both(self):
        accepted, rejected, _ = ingest([row(source_record_id="A"), row(source_record_id="B", postcode="77002")], self.manifest)
        self.assertEqual(len(accepted), 0)
        self.assertEqual({item["reason_code"] for item in rejected}, {"ADDRESS_CONFLICT"})

    def test_same_street_address_in_different_localities_is_not_merged(self):
        accepted, rejected, _ = ingest([row(source_record_id="A"),
                                        row(source_record_id="B", locality="Other Town")], self.manifest)
        self.assertEqual(len(accepted), 2)
        self.assertFalse(rejected)

    def test_exact_duplicate_source_row(self):
        accepted, rejected, _ = ingest([row(), row()], self.manifest)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected[0]["reason_code"], "SOURCE_DUPLICATE")

    def test_invalid_coordinates(self):
        for value in ("", "nan", "inf", "181", "wrong"):
            with self.subTest(value=value):
                _, rejected, _ = ingest([row(longitude=value)], self.manifest)
                self.assertEqual(rejected[0]["reason_code"], "INVALID_COORDINATES")

    def test_scope_checks_county_state_and_bbox(self):
        for changes in ({"county_id": "OTHER"}, {"state": "OK"}, {"longitude": "-94"}):
            with self.subTest(changes=changes):
                _, rejected, _ = ingest([row(**changes)], self.manifest)
                self.assertEqual(rejected[0]["reason_code"], "OUT_OF_SCOPE")

    def test_missing_required_values_and_provenance(self):
        for changes, reason in (({"source_record_id": ""}, "SOURCE_ID_MISSING"),
                                ({"source_authority": ""}, "PROVENANCE_MISSING"),
                                ({"street_name": ""}, "SOURCE_INCOMPLETE"),
                                ({"county_id": ""}, "SOURCE_INCOMPLETE")):
            with self.subTest(changes=changes):
                _, rejected, _ = ingest([row(**changes)], self.manifest)
                self.assertEqual(rejected[0]["reason_code"], reason)

    def test_input_hash_is_required(self):
        with self.assertRaisesRegex(SchemaError, "SHA-256"):
            read_pinned_csv(FIXTURE, "0" * 64)

    def test_extra_source_fields_are_preserved(self):
        accepted, _, _ = ingest([row(upstream_date="synthetic-date")], self.manifest)
        self.assertEqual(accepted[0]["original"]["upstream_date"], "synthetic-date")

    def test_duplicate_csv_columns_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "bad.csv"
            data = FIXTURE.read_bytes().replace(b"source_record_id,source_authority,",
                                                b"source_record_id,source_record_id,", 1)
            path.write_bytes(data)
            with self.assertRaisesRegex(SchemaError, "unique header"):
                read_pinned_csv(path, hashlib.sha256(data).hexdigest())

    def test_non_synthetic_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = copy.deepcopy(self.manifest)
            manifest["rights_status"] = "unreviewed"
            path = pathlib.Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(SchemaError, "synthetic data only"):
                load_manifest(path)

    def test_output_bytes_and_ids_are_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            first = pathlib.Path(directory) / "first"
            second = pathlib.Path(directory) / "second"
            self.assertEqual(run(MANIFEST, FIXTURE, first), run(MANIFEST, FIXTURE, second))
            for name in ("accepted.jsonl", "rejected.jsonl", "reconciliation.json"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            accepted = [json.loads(line) for line in (first / "accepted.jsonl").read_text().splitlines()]
            self.assertEqual(len({item["record_id"] for item in accepted}), len(accepted))


if __name__ == "__main__":
    unittest.main()
