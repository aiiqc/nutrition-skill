"""Source-linked data invariants and explicit unit conversion behavior."""

from copy import deepcopy
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from nutrition_core.catalog import get_food, load_catalog, quantity_to_grams, validate_catalog
from nutrition_core.common import NUTRIENT_UNITS, NutritionError

DATA_PATH = Path(__file__).resolve().parents[1] / "nutrition_core" / "data"
NUTRIENT_IDS = {"energy_kcal": 1008, "protein_g": 1003, "fat_g": 1004,
                "carbohydrate_g": 1005, "fiber_g": 1079, "sodium_mg": 1093,
                "potassium_mg": 1092, "phosphorus_mg": 1091}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.chicken = get_food(self.catalog, "usda:171077")

    def assert_invalid(self, catalog):
        with self.assertRaises(NutritionError):
            validate_catalog(catalog)

    def test_thirty_real_foods_preserve_original_records_with_unknown_allergen_assessment(self):
        self.assertEqual(len(self.catalog["foods"]), 30)
        self.assertTrue({"usda:171077", "usda:171477", "usda:2512381", "usda:169757", "usda:330137"}
                        <= set(self.catalog["foods"]))
        for food in self.catalog["foods"].values():
            self.assertEqual(food["allergens"]["assessment"], "unknown")
            self.assertEqual(food["source"]["license"], "CC0-1.0")
            self.assertEqual(set(food["nutrients"]), set(NUTRIENT_UNITS))

    def test_hashes_and_selected_amounts_match_preserved_source_bytes(self):
        for food in self.catalog["foods"].values():
            with self.subTest(food=food["id"]):
                raw = (DATA_PATH / "source-responses" / f"{food['source']['record_id']}.json").read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), food["source"]["response_sha256"])
                source = json.loads(raw, parse_float=Decimal)
                self.assertEqual(str(source["fdcId"]), food["source"]["record_id"])
                source_nutrients = {entry["nutrient"]["id"]: entry for entry in source["foodNutrients"]}
                for nutrient, nid in NUTRIENT_IDS.items():
                    if nutrient == "energy_kcal" and food["id"] == "usda:2512381":
                        nid = 2048
                    normalized = food["nutrients"][nutrient]
                    if nid not in source_nutrients:
                        self.assertEqual(normalized["status"], "missing")
                        self.assertIsNone(normalized["amount"])
                    else:
                        self.assertEqual(Decimal(normalized["amount"]), source_nutrients[nid]["amount"])
                source_portions = {str(p["id"]): p for p in source["foodPortions"]}
                for pid, portion in food["portions"].items():
                    original = source_portions[pid.removeprefix("usda:")]
                    self.assertEqual(Decimal(portion["grams"]), original["gramWeight"])
                    self.assertIn(f"foodPortion.id={original['id']}", portion["source"])

    def test_rice_uses_specific_energy_and_preserves_general_energy(self):
        rice = get_food(self.catalog, "usda:2512381")
        self.assertEqual(rice["nutrients"]["energy_kcal"]["method"], "atwater_specific")
        self.assertEqual(rice["nutrients"]["energy_kcal"]["amount"], "369.637321")
        self.assertEqual([(e["method"], e["amount"]) for e in rice["energy_alternatives"]],
                         [("atwater_general", "358.705")])

    def test_assumed_zero_missing_and_aggregate_loq_are_distinct(self):
        self.assertEqual(self.chicken["nutrients"]["fiber_g"]["status"], "assumed_zero")
        self.assertEqual(self.chicken["nutrients"]["fiber_g"]["amount"], "0")
        yogurt = get_food(self.catalog, "usda:330137")
        self.assertEqual(yogurt["nutrients"]["fiber_g"]["status"], "missing")
        self.assertIsNone(yogurt["nutrients"]["fiber_g"]["amount"])
        rice = get_food(self.catalog, "usda:2512381")
        for key, amount, loq in (("fiber_g", "0.1488", "0.75"), ("sodium_mg", "0.4625", "2.5")):
            entry = rice["nutrients"][key]
            self.assertEqual(entry["status"], "reported")
            self.assertEqual(entry["amount"], amount)
            self.assertEqual(entry["evidence"]["scope"], "aggregate")
            self.assertEqual(entry["evidence"]["loq"], loq)
            samples = entry["evidence"]["sub_samples"]
            self.assertEqual(len(samples), 8)
            self.assertEqual(sum(s["status"] == "below_loq" for s in samples), 7)
            self.assertTrue(all(s["scope"] == "sub_sample" for s in samples))

    def test_raw_and_cooked_are_separate_records(self):
        cooked = get_food(self.catalog, "usda:171477")
        self.assertEqual(self.chicken["state"], "raw")
        self.assertEqual(cooked["state"], "cooked")
        self.assertEqual(self.chicken["nutrients"]["energy_kcal"]["amount"], "120")
        self.assertEqual(cooked["nutrients"]["energy_kcal"]["amount"], "165")

    def test_exact_mass_conversions(self):
        for amount, unit, expected in (("0.18", "kg", "180"), ("180000", "mg", "180"),
                                       (180, "g", "180")):
            with self.subTest(unit=unit):
                self.assertEqual(quantity_to_grams(self.chicken, {"amount": amount, "unit": unit}), Decimal(expected))

    def test_source_portion_refers_to_whole_described_amount(self):
        # Source portion 87919 is four ounces together, not one ounce.
        self.assertEqual(quantity_to_grams(self.chicken, {"amount": "2", "unit": "portion", "portion_id": "usda:87919"}), Decimal("226"))
        cooked = get_food(self.catalog, "usda:171477")
        # One source portion is a half breast; do not silently double it.
        self.assertEqual(quantity_to_grams(cooked, {"amount": "1", "unit": "portion", "portion_id": "usda:88819"}), Decimal("86"))
        rice = get_food(self.catalog, "usda:169757")
        self.assertEqual(quantity_to_grams(rice, {"amount": "1", "unit": "portion", "portion_id": "usda:85462"}), Decimal("158"))

    def test_unqualified_cups_bowls_and_foreign_portions_are_rejected(self):
        for unit in ("cup", "bowl", "container", "oz", "G", None, []):
            with self.subTest(unit=unit), self.assertRaises(NutritionError):
                quantity_to_grams(self.chicken, {"amount": "1", "unit": unit})
        with self.assertRaises(NutritionError):
            quantity_to_grams(self.chicken, {"amount": "1", "unit": "portion", "portion_id": "usda:85462"})

    def test_ml_requires_explicit_sourced_density(self):
        with self.assertRaises(NutritionError) as error:
            quantity_to_grams(self.chicken, {"amount": "100", "unit": "ml"})
        self.assertEqual(error.exception.code, "density_required")
        self.chicken["density"] = {"grams_per_ml": "1.25", "source": "Synthetic density for this unit test only"}
        self.assertEqual(quantity_to_grams(self.chicken, {"amount": "100", "unit": "ml"}), Decimal("125"))
        self.chicken["density"]["source"] = ""
        with self.assertRaises(NutritionError):
            quantity_to_grams(self.chicken, {"amount": "100", "unit": "ml"})

    def test_decimal_context_does_not_change_quantity_results(self):
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            result = quantity_to_grams(self.chicken, {"amount": "123.123456789012", "unit": "kg"})
            self.assertEqual(result, Decimal("123123.456789012"))
            self.assertEqual(context.prec, 3)

    def test_nonfinite_float_bool_and_negative_quantities_are_rejected(self):
        for amount in (True, False, 1.0, "NaN", "Infinity", "-1", "1e3", None, "", "0", 0, "0.0000000000001"):
            with self.subTest(amount=amount), self.assertRaises(NutritionError):
                quantity_to_grams(self.chicken, {"amount": amount, "unit": "g"})

    def test_quantity_unknown_fields_and_irrelevant_portion_ids_rejected(self):
        for quantity in ({"amount": "1", "unit": "g", "portion_id": "usda:87919"},
                         {"amount": "1", "unit": "g", "portion": "cup"},
                         {"amount": "1", "unit": "portion"}):
            with self.subTest(quantity=quantity), self.assertRaises(NutritionError):
                quantity_to_grams(self.chicken, quantity)

    def test_query_validates_entire_catalog_and_returns_an_independent_copy(self):
        self.chicken["name"] = "Changed only in the returned copy"
        self.assertNotEqual(self.catalog["foods"]["usda:171077"]["name"], self.chicken["name"])
        self.catalog["foods"]["usda:330137"]["nutrients"]["protien_g"] = {"amount": "5", "unit": "g", "status": "reported"}
        with self.assertRaises(NutritionError):
            get_food(self.catalog, "usda:171077")

    def test_unknown_food_and_empty_catalog(self):
        empty = {"catalog_version": "empty-test", "foods": {}}
        self.assertIs(validate_catalog(empty), empty)
        with self.assertRaises(NutritionError) as error:
            get_food(empty, "no-such-food")
        self.assertEqual(error.exception.code, "unknown_food")

    def test_invalid_food_states_keys_and_nutrient_units(self):
        for field, value in (("state", "raw_or_cooked"), ("id", "another-id"), ("name", " ")):
            catalog = deepcopy(self.catalog)
            catalog["foods"]["usda:171077"][field] = value
            with self.subTest(field=field):
                self.assert_invalid(catalog)
        self.catalog["foods"]["usda:171077"]["nutrients"]["sodium_mg"]["unit"] = "g"
        self.assert_invalid(self.catalog)

    def test_missing_fixed_nutrient_or_extra_fields_are_rejected(self):
        del self.catalog["foods"]["usda:171077"]["nutrients"]["fiber_g"]
        self.assert_invalid(self.catalog)
        self.catalog = load_catalog()
        self.catalog["foods"]["usda:171077"]["nutrients"]["protein_g"]["ammount"] = "25"
        self.assert_invalid(self.catalog)

    def test_invalid_amount_status_combinations(self):
        for status, amount in (("missing", "0"), ("assumed_zero", "1"), ("reported", None),
                               ("below_loq", "0"), ("not_a_status", "1"), ("reported", 2),
                               ("reported", "NaN"), ("reported", True), ("reported", 2.0)):
            catalog = deepcopy(self.catalog)
            catalog["foods"]["usda:171077"]["nutrients"]["protein_g"].update(status=status, amount=amount)
            with self.subTest(status=status, amount=amount):
                self.assert_invalid(catalog)

    def test_aggregate_loq_cannot_be_relabelled_as_single_below_loq(self):
        entry = self.catalog["foods"]["usda:2512381"]["nutrients"]["fiber_g"]
        entry.update(status="below_loq", amount=None)
        self.assert_invalid(self.catalog)

    def test_valid_single_sample_below_loq_retains_no_exact_amount(self):
        entry = self.catalog["foods"]["usda:171077"]["nutrients"]["sodium_mg"]
        entry.update(status="below_loq", amount=None,
                     evidence={"scope": "sub_sample", "source_amount": "0", "loq": "1"})
        self.assertIs(validate_catalog(self.catalog), self.catalog)
        del entry["evidence"]["loq"]
        self.assert_invalid(self.catalog)

    def test_invalid_energy_method_or_duplicate_alternative(self):
        rice = self.catalog["foods"]["usda:2512381"]
        rice["energy_alternatives"].append(deepcopy(rice["nutrients"]["energy_kcal"]))
        self.assert_invalid(self.catalog)
        self.catalog = load_catalog()
        self.catalog["foods"]["usda:171077"]["nutrients"]["energy_kcal"]["method"] = "auto_sum"
        self.assert_invalid(self.catalog)

    def test_invalid_portion_grams_and_allergens(self):
        for grams in ("0", "-1", 1.0, "NaN"):
            catalog = deepcopy(self.catalog)
            catalog["foods"]["usda:171077"]["portions"]["usda:87919"]["grams"] = grams
            self.assert_invalid(catalog)
        self.catalog["foods"]["usda:171077"]["allergens"]["contains"] = ["soy", "soyy"]
        with self.assertRaises(NutritionError) as error:
            validate_catalog(self.catalog)
        self.assertEqual(error.exception.code, "unknown_allergen")

    def test_invalid_provenance_and_evidence(self):
        for key, value in (("published_date", "2019-02-30"), ("retrieved_date", "today"),
                           ("published_date", "2026-10-06"),
                           ("response_sha256", "not-a-hash"), ("url", "https://user:secret@example.com/x"),
                           ("url", "https://example.com/?api_key=private")):
            catalog = deepcopy(self.catalog)
            catalog["foods"]["usda:171077"]["source"][key] = value
            self.assert_invalid(catalog)
        self.catalog["foods"]["usda:2512381"]["nutrients"]["fiber_g"]["evidence"]["loq"] = "0"
        self.assert_invalid(self.catalog)

    def test_json_duplicate_keys_numbers_and_bad_files_are_rejected(self):
        invalid_json = ('{"catalog_version":"a","catalog_version":"b","foods":{}}',
                        '{"catalog_version":"a","foods":{},"extra":1.5}',
                        '{"catalog_version":"a","foods":{},"extra":NaN}', '{broken')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.json"
            for content in invalid_json:
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(NutritionError):
                    load_catalog(path)
            path.write_bytes(b'\xff')
            with self.assertRaises(NutritionError):
                load_catalog(path)
            with self.assertRaises(NutritionError):
                load_catalog(Path(temporary) / "missing.json")


if __name__ == "__main__":
    unittest.main()
