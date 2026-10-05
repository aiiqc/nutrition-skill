"""Behavioral tests for arithmetic, uncertainty, and external constraints."""

from copy import deepcopy
from decimal import Inexact, ROUND_DOWN, localcontext
import unittest

from nutrition_core.catalog import load_catalog
from nutrition_core.common import NUTRIENT_UNITS, NutritionError, RULE_VERSION
from nutrition_core.nutrition import calculate, check_constraints


def fixture_food(food_id="test:a"):
    nutrients = {key: {"amount": "0", "unit": unit, "status": "reported"}
                 for key, unit in NUTRIENT_UNITS.items()}
    nutrients["energy_kcal"]["method"] = "atwater_general"
    return {
        "id": food_id, "name": "Synthetic test fixture, not food data", "state": "raw",
        "source": {"publisher": "Synthetic test fixture", "record_id": food_id,
                   "url": "https://example.invalid/synthetic-fixture",
                   "published_date": "2026-10-05", "retrieved_date": "2026-10-05",
                   "license": "CC0-1.0", "response_sha256": "0" * 64},
        "nutrients": nutrients, "portions": {},
        "allergens": {"contains": [], "may_contain": [], "assessment": "verified",
                      "source": "Synthetic complete assessment for unit tests only"},
    }


def item(food_id="test:a", amount="100", unit="g"):
    return {"food_id": food_id, "quantity": {"amount": amount, "unit": unit}}


def limit(nutrient, **bounds):
    return {"limits": [{"nutrient": nutrient, "source": "Synthetic external limit",
                        **bounds}]}


class NutritionTests(unittest.TestCase):
    def setUp(self):
        self.food = fixture_food()
        self.catalog = {"catalog_version": "synthetic-test-v1",
                        "foods": {self.food["id"]: self.food}}

    def test_exact_conversion_sum_fixed_keys_and_provenance(self):
        self.food["nutrients"]["protein_g"]["amount"] = "22.5"
        result = calculate([item(amount="180"), item(amount="0.02", unit="kg")], self.catalog)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(set(result["totals"]), set(NUTRIENT_UNITS))
        self.assertEqual(result["totals"]["protein_g"]["amount"], "45")
        self.assertEqual([x["grams"] for x in result["items"]], ["180", "20"])
        self.assertEqual(result["items"][0]["state"], "raw")
        self.assertEqual(result["items"][0]["energy_method"], "atwater_general")
        self.assertEqual(result["items"][0]["source"], self.food["source"])
        self.assertEqual(result["rule_version"], RULE_VERSION)
        self.assertEqual(result["catalog_version"], "synthetic-test-v1")

    def test_source_return_is_independent_and_inputs_unchanged(self):
        items, constraints = [item()], limit("protein_g", min="0", max="1")
        originals = deepcopy((items, constraints, self.catalog))
        result = check_constraints(items, constraints, self.catalog)
        self.assertEqual((items, constraints, self.catalog), originals)
        result["calculation"]["items"][0]["source"]["publisher"] = "changed"
        self.assertEqual((items, constraints, self.catalog), originals)

    def test_missing_keeps_partial_amount_without_claiming_complete(self):
        self.food["nutrients"]["fiber_g"].update(amount=None, status="missing")
        other = fixture_food("test:b")
        other["nutrients"]["fiber_g"]["amount"] = "4"
        self.catalog["foods"][other["id"]] = other
        result = calculate([item(), item("test:b", "50")], self.catalog)
        total = result["totals"]["fiber_g"]
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(total["amount"])
        self.assertEqual(total["known_amount"], "2")
        self.assertFalse(total["complete"])
        self.assertEqual(total["statuses"], ["missing", "reported"])
        self.assertTrue(result["totals"]["protein_g"]["complete"])
        self.assertIn("nutrient_missing", [x["code"] for x in result["issues"]])

    def test_below_loq_is_not_a_reported_zero(self):
        self.food["nutrients"]["sodium_mg"].update(
            amount=None, status="below_loq", evidence={"scope": "sub_sample", "loq": "2.5"})
        total = calculate([item()], self.catalog)["totals"]["sodium_mg"]
        self.assertIsNone(total["amount"])
        self.assertEqual(total["known_amount"], "0")
        self.assertFalse(total["complete"])
        self.assertEqual(check_constraints([item()], limit("sodium_mg", max="100"),
                                           self.catalog)["status"], "needs_information")

    def test_assumed_zero_and_label_rounded_are_summable_but_not_verified(self):
        for status, amount in (("assumed_zero", "0"), ("label_rounded", "5")):
            with self.subTest(status=status):
                self.food["nutrients"]["sodium_mg"].update(amount=amount, status=status)
                result = calculate([item()], self.catalog)
                self.assertEqual(result["totals"]["sodium_mg"]["amount"], amount)
                self.assertTrue(result["totals"]["sodium_mg"]["complete"])
                self.assertIn(f"nutrient_{status}", [x["code"] for x in result["issues"]])
                self.assertEqual(check_constraints([item()], limit("sodium_mg", max="100"),
                                                   self.catalog)["status"], "needs_information")

    def test_label_rounded_point_above_limit_is_not_a_certain_conflict(self):
        self.food["nutrients"]["sodium_mg"].update(amount="5", status="label_rounded")
        result = check_constraints([item()], limit("sodium_mg", max="4.9"), self.catalog)
        self.assertEqual(result["status"], "needs_information")
        self.assertNotIn("nutrient_above_max", [x["code"] for x in result["issues"]])

    def test_aggregate_loq_keeps_reported_amount_but_cannot_verify_limit(self):
        nutrient = self.food["nutrients"]["sodium_mg"]
        for evidence in (
                {"scope": "aggregate", "loq": "2.5"},
                {"scope": "aggregate", "sub_samples": [
                    {"id": "sample-1", "scope": "sub_sample", "amount": "0",
                     "status": "below_loq", "loq": "2.5"}]}):
            with self.subTest(evidence=evidence):
                nutrient.update(amount="0.4625", evidence=evidence)
                result = calculate([item(amount="90")], self.catalog)
                total = result["totals"]["sodium_mg"]
                self.assertEqual(total["amount"], "0.41625")
                self.assertEqual(total["statuses"], ["reported"])
                self.assertTrue(total["complete"])
                self.assertIn("aggregate_loq_uncertainty", [x["code"] for x in result["issues"]])
                self.assertEqual(check_constraints([item()], limit("sodium_mg", max="0.4"),
                                                   self.catalog)["status"], "needs_information")

    def test_known_reported_partial_over_max_is_conflict(self):
        self.food["nutrients"]["sodium_mg"]["amount"] = "10"
        other = fixture_food("test:b")
        other["nutrients"]["sodium_mg"].update(amount=None, status="missing")
        self.catalog["foods"][other["id"]] = other
        result = check_constraints([item(), item("test:b")], limit("sodium_mg", max="9"), self.catalog)
        self.assertEqual(result["status"], "conflict")
        self.assertIn("nutrient_above_max", [x["code"] for x in result["issues"]])
        self.assertIsNone(result["calculation"]["totals"]["sodium_mg"]["amount"])

    def test_partial_below_min_cannot_prove_conflict(self):
        self.food["nutrients"]["protein_g"].update(amount=None, status="missing")
        result = check_constraints([item()], limit("protein_g", min="10"), self.catalog)
        self.assertEqual(result["status"], "needs_information")
        self.assertNotIn("nutrient_below_min", [x["code"] for x in result["issues"]])

    def test_limits_are_inclusive_and_below_min_is_conflict(self):
        self.food["nutrients"]["protein_g"]["amount"] = "10"
        self.assertEqual(check_constraints([item()], limit("protein_g", min="10", max="10"),
                                           self.catalog)["status"], "ok")
        self.assertEqual(check_constraints([item()], limit("protein_g", min="10.01"),
                                           self.catalog)["status"], "conflict")
        self.assertEqual(check_constraints([item()], limit("protein_g", max="9.99"),
                                           self.catalog)["status"], "conflict")

    def test_incompatible_external_limits_conflict_even_when_amount_is_unknown(self):
        self.food["nutrients"]["protein_g"].update(amount=None, status="missing")
        constraints = {"limits": [
            {"nutrient": "protein_g", "min": "10", "source": "Source A"},
            {"nutrient": "protein_g", "max": "5", "source": "Source B"},
        ]}
        result = check_constraints([item()], constraints, self.catalog)
        self.assertEqual(result["status"], "conflict")
        issue = next(x for x in result["issues"] if x["code"] == "constraint_bounds_conflict")
        self.assertEqual((issue["min"], issue["max"]), ("10", "5"))
        self.assertEqual((issue["min_source"], issue["max_source"]), ("Source A", "Source B"))

    def test_compatible_external_limits_include_shared_boundary(self):
        self.food["nutrients"]["protein_g"]["amount"] = "10"
        constraints = {"limits": [
            {"nutrient": "protein_g", "min": "10", "source": "Source A"},
            {"nutrient": "protein_g", "max": "10", "source": "Source B"},
        ]}
        self.assertEqual(check_constraints([item()], constraints, self.catalog)["status"], "ok")

    def test_unrelated_missing_nutrient_does_not_block_other_constraints(self):
        self.food["nutrients"]["fiber_g"].update(amount=None, status="missing")
        for constraints in ({}, {"allergens": [], "limits": []}, limit("protein_g", max="10")):
            with self.subTest(constraints=constraints):
                result = check_constraints([item()], constraints, self.catalog)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["issues"], [])
                self.assertTrue(result["calculation"]["issues"])

    def test_empty_items_are_known_zero_and_catalog_is_still_validated(self):
        result = calculate([], {"catalog_version": "empty-v1", "foods": {}})
        for total in result["totals"].values():
            self.assertEqual(total["amount"], "0")
            self.assertEqual(total["known_amount"], "0")
            self.assertTrue(total["complete"])
            self.assertEqual(total["statuses"], [])
        self.assertEqual(check_constraints([], limit("protein_g", min="1"), self.catalog)["status"],
                         "conflict")
        self.food["nutrients"]["fibre_g"] = self.food["nutrients"].pop("fiber_g")
        with self.assertRaises(NutritionError):
            calculate([], self.catalog)

    def test_unknown_allergen_assessment_cannot_pass(self):
        self.food["allergens"]["assessment"] = "unknown"
        self.assertEqual(check_constraints([item()], {"allergens": ["milk"]}, self.catalog)["status"],
                         "needs_information")

    def test_known_allergen_conflict_wins_over_unknown_assessment(self):
        self.food["allergens"].update(assessment="unknown", contains=["milk"])
        result = check_constraints([item()], {"allergens": ["milk", "egg"]}, self.catalog)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual({x["code"] for x in result["issues"]},
                         {"allergen_conflict", "allergen_information_missing"})

    def test_may_contain_is_conflict_and_verified_absence_can_pass(self):
        self.assertEqual(check_constraints([item()], {"allergens": ["milk"]}, self.catalog)["status"],
                         "ok")
        self.food["allergens"]["may_contain"] = ["milk"]
        self.assertEqual(check_constraints([item()], {"allergens": ["milk"]}, self.catalog)["status"],
                         "conflict")

    def test_unknown_allergen_ids_are_not_silently_ignored(self):
        for allergen in ("mlik", "Milk", "", None, True, [], {}):
            with self.subTest(allergen=allergen), self.assertRaises(NutritionError) as error:
                check_constraints([item()], {"allergens": [allergen]}, self.catalog)
            self.assertEqual(error.exception.code, "unknown_allergen")

    def test_invalid_items_shapes_and_unknown_fields_are_rejected(self):
        bad_items = [None, {}, (), "food", [None], [{"food_id": "test:a"}],
                     [{**item(), "quanity": {"amount": "100", "unit": "g"}}],
                     [{"food_id": "test:a", "quantity": {"amount": "100", "unit": "g", "amout": "1"}}]]
        for items in bad_items:
            with self.subTest(items=items), self.assertRaises(NutritionError):
                calculate(items, self.catalog)
        with self.assertRaises(NutritionError):
            calculate([item("test:absent")], self.catalog)

    def test_amount_nan_float_bool_and_malformed_values_are_rejected(self):
        for amount in ("NaN", "sNaN", "Infinity", "-1", "0", 1.5, True, None, [], {}):
            with self.subTest(amount=amount), self.assertRaises(NutritionError):
                calculate([item(amount=amount)], self.catalog)

    def test_catalog_nutrient_typos_and_invalid_numbers_are_rejected(self):
        for amount in ("NaN", "Infinity", 1.5, True, {}):
            with self.subTest(amount=amount), self.assertRaises(NutritionError):
                catalog = deepcopy(self.catalog)
                catalog["foods"]["test:a"]["nutrients"]["protein_g"]["amount"] = amount
                calculate([item()], catalog)
        self.food["nutrients"]["sodum_mg"] = self.food["nutrients"].pop("sodium_mg")
        with self.assertRaises(NutritionError):
            calculate([item()], self.catalog)

    def test_constraint_shape_unknown_nutrient_and_source_are_validated(self):
        bad = [None, [], {"limit": []}, {"allergens": "milk"}, {"limits": {}},
               {"limits": [None]}, {"limits": [{"nutrient": "protein_g", "max": "1"}]},
               limit("proten_g", max="1"), limit([], max="1"), limit("protein_g"),
               limit("protein_g", min="2", max="1"),
               limit("protein_g", max="1", source=" "),
               limit("protein_g", max="1", source={}),
               limit("protein_g", max="1", maximim="2")]
        for constraints in bad:
            with self.subTest(constraints=constraints), self.assertRaises(NutritionError):
                check_constraints([item()], constraints, self.catalog)

    def test_constraint_numbers_reject_nan_float_bool_and_negative(self):
        for bound in ("min", "max"):
            for amount in ("NaN", "Infinity", "-1", 1.5, True, None, [], {}):
                with self.subTest(bound=bound, amount=amount), self.assertRaises(NutritionError):
                    check_constraints([item()], limit("protein_g", **{bound: amount}), self.catalog)

    def test_item_limit_bounds_work_without_processing_excess_entries(self):
        with self.assertRaises(NutritionError) as error:
            calculate([item()] * 1001, self.catalog)
        self.assertEqual(error.exception.code, "too_many_items")

    def test_constraint_arrays_have_explicit_bounds(self):
        for field, value in (("allergens", "milk"),
                             ("limits", {"nutrient": "protein_g", "max": "1", "source": "Test"})):
            with self.subTest(field=field):
                self.assertEqual(check_constraints([item()], {field: [value] * 1000},
                                                   self.catalog)["status"], "ok")
                with self.assertRaises(NutritionError) as error:
                    check_constraints([item()], {field: [value] * 1001}, self.catalog)
                self.assertEqual(error.exception.code, "too_many_constraints")

    def test_caller_decimal_precision_rounding_and_traps_do_not_change_output(self):
        self.food["nutrients"]["protein_g"]["amount"] = "7.03885"
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            result = calculate([item(amount="90")], self.catalog)
            self.assertEqual(result["totals"]["protein_g"]["amount"], "6.334965")
            self.assertEqual(context.prec, 2)
            self.assertEqual(context.rounding, ROUND_DOWN)
            self.assertTrue(context.traps[Inexact])


class USDAArithmeticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_180g_chicken_keeps_raw_and_cooked_records_distinct(self):
        raw = calculate([item("usda:171077", "180")], self.catalog)["totals"]
        cooked = calculate([item("usda:171477", "180")], self.catalog)["totals"]
        self.assertEqual(raw["protein_g"]["amount"], "40.5")
        self.assertEqual(raw["energy_kcal"]["amount"], "216")
        self.assertEqual(cooked["protein_g"]["amount"], "55.836")
        self.assertEqual(cooked["energy_kcal"]["amount"], "297")

    def test_90g_raw_rice_uses_one_energy_method_and_exact_decimal_amounts(self):
        result = calculate([item("usda:2512381", "90")], self.catalog)
        expected = {"energy_kcal": "332.6735889", "protein_g": "6.334965",
                    "carbohydrate_g": "72.281835", "fat_g": "0.9297",
                    "fiber_g": "0.13392", "sodium_mg": "0.41625"}
        for key, amount in expected.items():
            self.assertEqual(result["totals"][key]["amount"], amount)
        self.assertEqual(result["items"][0]["state"], "raw")
        self.assertEqual(result["items"][0]["energy_method"], "atwater_specific")
        self.assertIn("aggregate_loq_uncertainty", [x["code"] for x in result["issues"]])

    def test_yogurt_missing_fiber_does_not_become_zero(self):
        result = calculate([item("usda:330137", "250")], self.catalog)
        self.assertEqual(result["totals"]["protein_g"]["amount"], "25.75")
        self.assertIsNone(result["totals"]["fiber_g"]["amount"])
        self.assertFalse(result["totals"]["fiber_g"]["complete"])
        self.assertEqual(result["totals"]["fiber_g"]["statuses"], ["missing"])


if __name__ == "__main__":
    unittest.main()
