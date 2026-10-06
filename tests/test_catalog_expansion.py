"""Verify expanded choices against the preserved USDA source records."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from nutrition_core.catalog import load_catalog, quantity_to_grams


DATA_PATH = Path(__file__).resolve().parents[1] / "nutrition_core" / "data"
NEW_IDS = {173904, 173424, 172448, 172421, 173735, 171267, 172688, 168928,
           170440, 175168, 171413, 170158, 173944, 171688, 169967, 170394,
           168463, 170420, 170457, 168409, 169252, 168484, 169283, 171284, 169097}


class CatalogExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.choices = json.loads((DATA_PATH / "food-choices.json").read_text())

    def test_every_choice_resolves_to_one_catalog_record_and_its_own_portions(self):
        self.assertEqual(self.choices["schema_version"], "food-choices-v1")
        self.assertEqual(set(self.choices["foods"]), set(self.catalog["foods"]))
        categories = set()
        for fid, choice in self.choices["foods"].items():
            with self.subTest(food=fid):
                food = self.catalog["foods"][fid]
                self.assertTrue(choice["name_zh"].strip())
                self.assertIn(food["name"], choice["aliases"])
                self.assertEqual(len(choice["aliases"]), len(set(choice["aliases"])))
                self.assertTrue(all(isinstance(a, str) and a.strip() for a in choice["aliases"]))
                self.assertEqual(set(choice["portion_ids"]), set(food["portions"]))
                for pid in choice["portion_ids"]:
                    self.assertEqual(quantity_to_grams(food, {"amount": "1", "unit": "portion",
                                                               "portion_id": pid}),
                                     Decimal(food["portions"][pid]["grams"]))
                categories.add(choice["category"])
        self.assertEqual(categories, {"grain", "protein", "dairy", "legume", "vegetable", "fruit", "fat"})

    def test_added_records_are_full_official_records_with_complete_macronutrients(self):
        self.assertTrue({f"usda:{fid}" for fid in NEW_IDS} <= self.catalog["foods"].keys())
        for fid in NEW_IDS:
            with self.subTest(food=fid):
                food = self.catalog["foods"][f"usda:{fid}"]
                raw = (DATA_PATH / "source-responses" / f"{fid}.json").read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), food["source"]["response_sha256"])
                source = json.loads(raw, parse_float=Decimal)
                self.assertEqual(source["fdcId"], fid)
                self.assertEqual(source["description"], food["name"])
                self.assertEqual(source["dataType"], "SR Legacy")
                self.assertEqual(food["source"]["license"], "CC0-1.0")
                self.assertEqual(food["source"]["published_date"], "2019-04-01")
                self.assertEqual(food["source"]["retrieved_date"], "2026-10-06")
                nutrients = {entry["nutrient"]["id"]: entry for entry in source["foodNutrients"]}
                for key, nid in (("energy_kcal", 1008), ("protein_g", 1003),
                                 ("carbohydrate_g", 1005), ("fat_g", 1004)):
                    entry = food["nutrients"][key]
                    self.assertIsNotNone(entry["amount"])
                    self.assertEqual(Decimal(entry["amount"]), nutrients[nid]["amount"])
                    self.assertEqual(entry["evidence"]["source_nutrient_id"], str(nid))

    def test_source_derivations_and_missing_values_are_not_invented(self):
        for fid in NEW_IDS:
            source = json.loads((DATA_PATH / "source-responses" / f"{fid}.json").read_text(),
                                parse_float=Decimal)
            nutrients = {str(n["nutrient"]["id"]): n for n in source["foodNutrients"]}
            for key, entry in self.catalog["foods"][f"usda:{fid}"]["nutrients"].items():
                with self.subTest(food=fid, nutrient=key):
                    original = nutrients.get(entry["evidence"]["source_nutrient_id"])
                    if original is None:
                        self.assertEqual(entry["status"], "missing")
                        self.assertIsNone(entry["amount"])
                    else:
                        assumed = original.get("foodNutrientDerivation", {}).get("code") == "Z"
                        self.assertEqual(entry["status"], "assumed_zero" if assumed else "reported")
                        self.assertEqual(Decimal(entry["amount"]), original["amount"])
                        self.assertEqual(entry["unit"].lower(), original["nutrient"]["unitName"].lower())

    def test_choices_keep_dry_and_cooked_records_distinct(self):
        for fid, state in ((173904, "raw"), (173424, "cooked"), (168928, "cooked"),
                           (169757, "cooked"), (171477, "cooked"), (172448, "processed")):
            self.assertEqual(self.catalog["foods"][f"usda:{fid}"]["state"], state)
        self.assertIn("干重", self.choices["foods"]["usda:173904"]["notes"])
        self.assertIn("购买状态", self.choices["foods"]["usda:172448"]["notes"])
        self.assertEqual(self.catalog["foods"]["usda:172448"]["nutrients"]["energy_kcal"]["amount"], "78")
        self.assertEqual(self.catalog["foods"]["usda:172448"]["nutrients"]["protein_g"]["amount"], "9.04")

    def test_food_metadata_does_not_certify_allergens_or_unverified_density(self):
        for food in self.catalog["foods"].values():
            self.assertEqual(food["allergens"]["assessment"], "unknown")
            self.assertEqual(food["allergens"]["contains"], [])
            self.assertEqual(food["allergens"]["may_contain"], [])
            self.assertNotIn("density", food)
        for choice in self.choices["foods"].values():
            self.assertTrue(set(choice["meal_roles"]) <= {"breakfast", "lunch", "dinner", "snack"})
            self.assertTrue(set(choice["preparation"]) <= {"ready_to_eat", "cook", "reheat"})
            self.assertNotIn("allergen_safe", choice)

    def test_ambiguous_chinese_names_do_not_replace_different_foods(self):
        beans = self.choices["foods"]["usda:173735"]
        almonds = self.choices["foods"]["usda:170158"]
        self.assertIn("黑芸豆", beans["aliases"])
        self.assertNotIn("黑豆", beans["aliases"])
        self.assertIn("扁桃仁", almonds["aliases"])
        self.assertNotIn("杏仁", almonds["aliases"])
        self.assertNotIn("青豆", self.choices["foods"]["usda:170420"]["aliases"])


if __name__ == "__main__":
    unittest.main()
