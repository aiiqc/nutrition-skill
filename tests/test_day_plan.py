"""Daily planned-intake checks keep coverage, targets, and actuals distinct."""

from copy import deepcopy
import unittest

from nutrition_core.catalog import load_catalog
from nutrition_core.common import NutritionError
from nutrition_core.plans import check_day_plan, replace_meal, revalidate_plan


def item(amount="100"):
    return {"food_id": "usda:171077", "quantity": {"amount": amount, "unit": "g"}}


def day():
    return {"revision": 4, "meals": [
        {"id": name, "locked": False, "items": [item()]}
        for name in ("breakfast", "lunch", "dinner")
    ], "actuals": {}}


def coverage(confirmed=True):
    return {"expected_meal_ids": ["breakfast", "lunch", "dinner"], "confirmed": confirmed}


def limits(**bounds):
    return {"limits": [{"nutrient": "protein_g", "source": "Synthetic user-supplied daily target", **bounds}]}


class DayPlanTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def check(self, state=None, constraints=None, declared=None):
        return check_day_plan(day() if state is None else state,
                              {} if constraints is None else constraints,
                              coverage() if declared is None else declared, self.catalog)

    def test_totals_checked_once_for_day_not_repeated_as_meal_minima(self):
        state, constraints = day(), limits(min="50", max="80")
        result = self.check(state, constraints)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["plan_complete"])
        self.assertEqual(result["calculation"]["totals"]["protein_g"]["amount"], "67.5")
        self.assertEqual(len(result["calculation"]["items"]), 3)
        self.assertEqual(result["scope"], "day_plan")
        self.assertEqual(result["constraints_check"]["scope"], "day_plan")
        self.assertEqual(result["intake_basis"], "planned")
        self.assertEqual(result["calculation_scope"], "listed_plan_meals")
        self.assertEqual(result["coverage_scope"], "user_declared_day")
        self.assertEqual(result["supplied_constraints"], constraints)
        self.assertEqual(result["deferred_minimum_checks"], [])
        self.assertEqual(revalidate_plan(state, constraints, self.catalog)["status"], "conflict")

    def test_daily_maximum_is_not_checked_individually_per_meal(self):
        constraints = limits(max="30")
        self.assertEqual(revalidate_plan(day(), constraints, self.catalog)["status"], "ok")
        result = self.check(constraints=constraints)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["issues"][0]["code"], "nutrient_above_max")

    def test_minimum_shortfall_requires_complete_coverage(self):
        constraints = limits(min="70")
        complete = self.check(constraints=constraints)
        self.assertEqual(complete["status"], "conflict")
        self.assertEqual(complete["issues"][0]["code"], "nutrient_below_min")
        incomplete = self.check(constraints=constraints, declared=coverage(False))
        self.assertEqual(incomplete["status"], "needs_information")
        self.assertEqual(incomplete["constraints_check"]["status"], "needs_information")
        self.assertNotIn("nutrient_below_min", [entry["code"] for entry in incomplete["issues"]])
        deferred = incomplete["deferred_minimum_checks"][0]
        self.assertEqual((deferred["min"], deferred["reported_amount"]), ("70", "67.5"))
        self.assertEqual(deferred["source"], constraints["limits"][0]["source"])
        self.assertEqual(deferred["reason"], "incomplete_day_coverage")

    def test_partial_day_preserves_proven_excess_and_allergen_conflicts(self):
        state = day()
        state["meals"] = state["meals"][:1]
        self.catalog["foods"]["usda:171077"]["allergens"]["contains"] = ["milk"]
        constraints = {**limits(min="30", max="40"), "allergens": ["milk"]}
        constraints["limits"].append({"nutrient": "energy_kcal", "max": "100", "source": "Synthetic bound"})
        result = self.check(state, constraints)
        codes = {entry["code"] for entry in result["issues"]}
        self.assertEqual(result["status"], "conflict")
        self.assertFalse(result["plan_complete"])
        self.assertTrue({"nutrient_above_max", "allergen_conflict", "day_plan_coverage_incomplete"} <= codes)
        self.assertNotIn("nutrient_below_min", codes)

    def test_missing_unexpected_and_empty_groups_are_explicit(self):
        state = day()
        state["meals"][1]["id"] = "snack"
        state["meals"][2]["items"] = []
        result = self.check(state, limits(min="70"))
        self.assertEqual(result["status"], "needs_information")
        self.assertFalse(result["plan_complete"])
        self.assertEqual(result["coverage"]["missing_meal_ids"], ["lunch"])
        self.assertEqual(result["coverage"]["unexpected_meal_ids"], ["snack"])
        self.assertEqual(result["coverage"]["empty_meal_ids"], ["dinner"])

    def test_empty_plan_is_not_known_zero_day_or_minimum_failure(self):
        result = self.check({"revision": 0, "meals": [], "actuals": {}}, limits(min="1"))
        self.assertEqual(result["status"], "needs_information")
        self.assertFalse(result["plan_complete"])
        self.assertEqual(result["coverage"]["missing_meal_ids"], coverage()["expected_meal_ids"])
        self.assertEqual(result["calculation"]["totals"]["protein_g"]["known_amount"], "0")
        self.assertNotIn("nutrient_below_min", [entry["code"] for entry in result["issues"]])

    def test_coverage_is_not_inferred_from_three_meals_and_allows_other_schedules(self):
        self.assertEqual(self.check(declared=coverage(False))["status"], "needs_information")
        state = day()
        state["meals"] = [{"id": "all_planned_intake", "locked": False, "items": [item("300")]}]
        result = self.check(state, limits(min="67.5", max="67.5"),
                            {"expected_meal_ids": ["all_planned_intake"], "confirmed": True})
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["plan_complete"])

    def test_coverage_matching_uses_exact_ids_not_order(self):
        declared = coverage()
        declared["expected_meal_ids"].reverse()
        self.assertEqual(self.check(declared=declared)["status"], "ok")
        declared["expected_meal_ids"][0] = "Dinner"
        result = self.check(declared=declared)
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(result["coverage"]["missing_meal_ids"], ["Dinner"])

    def test_locked_foods_are_included_and_missing_other_nutrients_stay_visible(self):
        state = day()
        state["meals"][2]["locked"] = True
        self.catalog["foods"]["usda:171077"]["nutrients"]["fiber_g"].update(amount=None, status="missing")
        result = self.check(state, limits(min="50", max="80"))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["plan_complete"])
        self.assertEqual(result["calculation"]["totals"]["protein_g"]["amount"], "67.5")
        self.assertFalse(result["calculation"]["totals"]["fiber_g"]["complete"])
        self.assertTrue(result["calculation"]["issues"])
        self.assertEqual(result["state"], state)

    def test_zero_quantity_cannot_be_used_to_fake_a_nonempty_meal(self):
        state = day()
        state["meals"][0]["items"] = [item("0")]
        with self.assertRaises(NutritionError):
            self.check(state)

    def test_unknown_and_estimated_target_nutrients_never_pass(self):
        nutrient = self.catalog["foods"]["usda:171077"]["nutrients"]["protein_g"]
        for status, amount in (("missing", None), ("label_rounded", "22.5"), ("assumed_zero", "0")):
            with self.subTest(status=status):
                nutrient.update(status=status, amount=amount)
                for confirmed in (True, False):
                    result = self.check(constraints=limits(min="1", max="100"), declared=coverage(confirmed))
                    self.assertEqual(result["status"], "needs_information")
                    self.assertIn("constraint_nutrient_uncertain", [entry["code"] for entry in result["issues"]])
                    self.assertNotIn("nutrient_below_min", [entry["code"] for entry in result["issues"]])
                    self.assertEqual(result["plan_complete"], confirmed)

    def test_incomplete_day_still_detects_incompatible_targets(self):
        constraints = limits(min="100")
        constraints["limits"].append({"nutrient": "protein_g", "max": "90", "source": "Other synthetic target"})
        result = self.check({"revision": 0, "meals": [], "actuals": {}}, constraints)
        self.assertEqual(result["status"], "conflict")
        self.assertIn("constraint_bounds_conflict", [entry["code"] for entry in result["issues"]])
        self.assertNotIn("nutrient_below_min", [entry["code"] for entry in result["issues"]])

    def test_actuals_excluded_and_all_inputs_results_independent(self):
        state, constraints, declared = day(), limits(min="50", max="80"), coverage()
        state["actuals"]["breakfast"] = {"status": "confirmed", "items": [item("1000")]}
        before = deepcopy((state, constraints, declared, self.catalog))
        result = self.check(state, constraints, declared)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["calculation"]["totals"]["protein_g"]["amount"], "67.5")
        self.assertEqual(result["state"], state)
        result["state"]["actuals"]["breakfast"]["items"][0]["quantity"]["amount"] = "1"
        result["state"]["revision"] = 5
        result["coverage"]["expected_meal_ids"].append("snack")
        result["supplied_constraints"]["limits"][0]["source"] = "Changed"
        result["calculation"]["items"][0]["source"]["publisher"] = "Changed"
        self.assertEqual((state, constraints, declared, self.catalog), before)

    def test_replacement_is_resummed_without_stale_daily_result(self):
        state, constraints = day(), limits(max="80")
        self.assertEqual(self.check(state, constraints)["status"], "ok")
        updated = replace_meal(state, "lunch", [item("300")], {}, self.catalog)["state"]
        result = self.check(updated, constraints)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["calculation"]["totals"]["protein_g"]["amount"], "112.5")
        self.assertEqual(result["state"]["revision"], 5)
        self.assertEqual(state, day())

    def test_bad_coverage_rejected_without_mutation(self):
        invalid = [None, [], {}, {"expected_meal_ids": [], "confirmed": True}]
        for value in (None, "breakfast", ["breakfast", "breakfast"], [True], [" "], ["x" * 1001], ["a"] * 1001):
            invalid.append({"expected_meal_ids": value, "confirmed": True})
        for value in (None, 1, "true", []):
            invalid.append({**coverage(), "confirmed": value})
        invalid.append({**coverage(), "extra": True})
        state = day()
        for index, declared in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(NutritionError):
                check_day_plan(state, {}, declared, self.catalog)
            self.assertEqual(state, day())

    def test_incomplete_day_does_not_bypass_constraint_validation(self):
        for constraints in ({"invalid": True}, limits(min="5", max="1"),
                            {"limits": [{"nutrient": "protein_g", "min": "5"}]},
                            {"allergens": ["unknown"]}):
            with self.subTest(constraints=constraints), self.assertRaises(NutritionError):
                self.check({"revision": 0, "meals": [], "actuals": {}}, constraints)


if __name__ == "__main__":
    unittest.main()
