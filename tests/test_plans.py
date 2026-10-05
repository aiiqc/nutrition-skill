"""Behavioral checks for plans, actual intake, and atomic restoration."""

from copy import deepcopy
import unittest

from nutrition_core.catalog import load_catalog
from nutrition_core.common import NutritionError
from nutrition_core.plans import (
    MAX_REVISION, record_actual, replace_meal, restore_plan,
    revalidate_plan, summarize_actuals,
)


def item(amount="100", food_id="usda:171077"):
    return {"food_id": food_id, "quantity": {"amount": amount, "unit": "g"}}


def day():
    return {"revision": 0, "meals": [
        {"id": "breakfast", "locked": False, "items": [item()]},
        {"id": "lunch", "locked": False, "items": [item("200")]},
        {"id": "dinner", "locked": True, "items": [item("150")]},
    ], "actuals": {}}


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_eaten_breakfast_replace_lunch_and_locked_dinner(self):
        original = day()
        recorded = record_actual(original, "breakfast", {"status": "confirmed", "items": [item()]}, self.catalog)
        state = recorded["state"]
        before = deepcopy(state)
        replacement = [item("180", "usda:171477")]
        result = replace_meal(state, "lunch", replacement, {}, self.catalog)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "meal")
        self.assertEqual(result["state"]["revision"], 2)
        self.assertEqual(result["state"]["meals"][0], state["meals"][0])
        self.assertEqual(result["state"]["meals"][2], state["meals"][2])
        self.assertEqual(result["state"]["actuals"], state["actuals"])
        self.assertEqual(result["state"]["meals"][1]["items"], replacement)
        self.assertEqual(state, before)
        for meal_id in ("breakfast", "dinner"):
            rejected = replace_meal(state, meal_id, replacement, {}, self.catalog)
            self.assertEqual(rejected["status"], "conflict")
            self.assertEqual(rejected["state"], state)
            self.assertIsNot(rejected["state"], state)
            rejected["state"]["meals"][0]["items"][0]["quantity"]["amount"] = "1"
            self.assertEqual(state, before)
        result["state"]["actuals"]["breakfast"]["items"][0]["quantity"]["amount"] = "1"
        replacement[0]["quantity"]["amount"] = "2"
        self.assertEqual(state, before)
        self.assertEqual(original, day())

    def test_unknown_partial_and_explicit_not_eaten_stay_distinct(self):
        state = day()
        state = record_actual(state, "breakfast", {"status": "partial", "items": [item("50")]}, self.catalog)["state"]
        state = record_actual(state, "lunch", {"status": "not_eaten"}, self.catalog)["state"]
        before = deepcopy(state)
        summary = summarize_actuals(state, self.catalog)
        self.assertFalse(summary["day_complete"])
        self.assertEqual(summary["coverage_scope"], "listed_meals")
        self.assertEqual(summary["unknown_meal_ids"], ["dinner"])
        self.assertEqual(summary["not_eaten_meal_ids"], ["lunch"])
        self.assertEqual(summary["calculation"]["totals"]["energy_kcal"]["known_amount"], "60")
        self.assertEqual(state, before)
        blocked = replace_meal(state, "lunch", [item("50")], {}, self.catalog)
        self.assertEqual(blocked["status"], "conflict")
        self.assertEqual(blocked["state"], state)
        state = record_actual(state, "dinner", {"status": "not_eaten", "items": []}, self.catalog)["state"]
        self.assertTrue(summarize_actuals(state, self.catalog)["day_complete"])

    def test_unrecorded_and_explicit_unknown_do_not_count_planned_food(self):
        state = day()
        state["actuals"]["lunch"] = {"status": "unknown"}
        summary = summarize_actuals(state, self.catalog)
        self.assertEqual(summary["unknown_meal_ids"], ["breakfast", "lunch", "dinner"])
        self.assertFalse(summary["day_complete"])
        self.assertEqual(summary["status"], "needs_information")
        self.assertEqual(summary["calculation"]["totals"]["energy_kcal"]["known_amount"], "0")
        self.assertEqual(summary["recorded_meal_ids"], [])
        self.assertEqual(replace_meal(state, "lunch", [item("80")], {}, self.catalog)["status"], "ok")
        empty = summarize_actuals({"revision": 0, "meals": [], "actuals": {}}, self.catalog)
        self.assertFalse(empty["day_complete"])

    def test_recording_is_a_correction_without_rewriting_the_plan(self):
        state = day()
        before = deepcopy(state)
        first = record_actual(state, "dinner", {"status": "not_eaten"}, self.catalog)["state"]
        actual = {"status": "confirmed", "items": [item("80")]}
        second = record_actual(first, "dinner", actual, self.catalog)["state"]
        self.assertEqual(second["meals"], state["meals"])
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["actuals"]["dinner"], actual)
        actual["items"][0]["quantity"]["amount"] = "1"
        self.assertEqual(second["actuals"]["dinner"]["items"][0]["quantity"]["amount"], "80")
        self.assertEqual(state, before)

    def test_constraint_change_rechecks_locked_meals_and_blocks_restore(self):
        state = day()
        state["meals"][0]["items"] = [item("1")]
        state["meals"][1]["items"] = [item("1")]
        before = deepcopy(state)
        constraints = {"limits": [{"nutrient": "energy_kcal", "max": "100", "source": "fictional meal limit"}]}
        result = revalidate_plan(state, constraints, self.catalog)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["scope"], "meal")
        self.assertEqual([entry["meal_id"] for entry in result["checks"]], ["breakfast", "lunch", "dinner"])
        self.assertEqual(result["checks"][2]["status"], "conflict")
        self.assertTrue(all(check["scope"] == "meal" for check in result["checks"]))
        failed = restore_plan(state, deepcopy(state["meals"]), constraints, self.catalog)
        self.assertEqual(failed["status"], "conflict")
        self.assertEqual(failed["state"], before)
        self.assertEqual(state, before)

    def test_restore_preserves_actuals_and_rejects_changes_to_recorded_meals(self):
        for actual_status in ("confirmed", "partial", "not_eaten"):
            with self.subTest(actual_status=actual_status):
                state = day()
                actual = {"status": actual_status}
                if actual_status != "not_eaten":
                    actual["items"] = [item("50")]
                state = record_actual(state, "breakfast", actual, self.catalog)["state"]
                before = deepcopy(state)
                previous = deepcopy(state["meals"])
                previous[1]["items"] = [item("125")]
                restored = restore_plan(state, previous, {}, self.catalog)
                self.assertEqual(restored["status"], "ok")
                self.assertEqual(restored["state"]["actuals"], state["actuals"])
                self.assertEqual(restored["state"]["meals"][0], state["meals"][0])
                self.assertEqual(restored["state"]["meals"][1], previous[1])
                self.assertEqual(restored["state"]["revision"], state["revision"] + 1)
                previous[0]["items"] = [item("110")]
                failed = restore_plan(state, previous, {}, self.catalog)
                self.assertEqual(failed["status"], "conflict")
                self.assertEqual(failed["state"], state)
                self.assertEqual(state, before)

    def test_unknown_allergen_evidence_cannot_commit_replacement_or_restore(self):
        state = day()
        before = deepcopy(state)
        constraints = {"allergens": ["milk"]}
        replaced = replace_meal(state, "lunch", [item("80")], constraints, self.catalog)
        restored = restore_plan(state, deepcopy(state["meals"]), constraints, self.catalog)
        for result in (replaced, restored):
            self.assertEqual(result["status"], "needs_information")
            self.assertEqual(result["state"], before)
        self.assertEqual(state, before)

    def test_constraints_are_per_meal_not_a_daily_limit(self):
        state = day()
        for meal in state["meals"]:
            meal["items"] = [item("50")]
        result = revalidate_plan(state, {"limits": [{"nutrient": "energy_kcal", "max": "100", "source": "fictional meal limit"}]}, self.catalog)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "meal")
        self.assertEqual(len(result["checks"]), 3)

    def test_invalid_state_shapes_fail_without_mutation(self):
        invalid_states = []
        for revision in (True, -1, "1", 1.0, MAX_REVISION + 1):
            state = day(); state["revision"] = revision; invalid_states.append(state)
        state = day(); state["extra"] = 1; invalid_states.append(state)
        state = day(); state["meals"].append(deepcopy(state["meals"][0])); invalid_states.append(state)
        state = day(); state["meals"][0]["locked"] = 1; invalid_states.append(state)
        state = day(); state["meals"][0]["id"] = " "; invalid_states.append(state)
        state = day(); state["meals"][0]["items"][0]["qty"] = "1"; invalid_states.append(state)
        state = day(); state["actuals"]["missing"] = {"status": "unknown"}; invalid_states.append(state)
        state = day(); state["actuals"]["lunch"] = {"status": "confirmed", "items": []}; invalid_states.append(state)
        state = day(); state["actuals"]["lunch"] = {"status": "unknown", "items": [item()]}; invalid_states.append(state)
        state = day(); state["actuals"]["lunch"] = {"status": []}; invalid_states.append(state)
        for index, state in enumerate(invalid_states):
            with self.subTest(index=index):
                before = deepcopy(state)
                with self.assertRaises(NutritionError):
                    summarize_actuals(state, self.catalog)
                self.assertEqual(state, before)

    def test_invalid_changes_are_not_committed(self):
        state = day()
        before = deepcopy(state)
        cases = [
            lambda: record_actual(state, "missing", {"status": "unknown"}, self.catalog),
            lambda: record_actual(state, "lunch", {"status": "partial"}, self.catalog),
            lambda: record_actual(state, "lunch", {"status": "not_eaten", "items": [item()]}, self.catalog),
            lambda: record_actual(state, "lunch", {"status": "unknown", "extra": True}, self.catalog),
            lambda: replace_meal(state, "lunch", [{"food_id": "unknown", "quantity": {"amount": "1", "unit": "g"}}], {}, self.catalog),
            lambda: replace_meal(state, "lunch", [item()], {"unknown_limit": 1}, self.catalog),
            lambda: restore_plan(state, state["meals"][:-1], {}, self.catalog),
            lambda: restore_plan(state, [state["meals"][0]] * 3, {}, self.catalog),
        ]
        for index, operation in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(NutritionError):
                operation()
            self.assertEqual(state, before)

    def test_revision_and_collection_bounds(self):
        state = day()
        state["revision"] = MAX_REVISION
        before = deepcopy(state)
        for operation in (
            lambda: record_actual(state, "lunch", {"status": "unknown"}, self.catalog),
            lambda: replace_meal(state, "lunch", [item()], {}, self.catalog),
            lambda: restore_plan(state, deepcopy(state["meals"]), {}, self.catalog),
        ):
            with self.assertRaises(NutritionError):
                operation()
            self.assertEqual(state, before)
        state = day()
        state["meals"][0]["items"] = [item()] * 1001
        with self.assertRaises(NutritionError):
            summarize_actuals(state, self.catalog)
        state = day()
        state["meals"][0]["items"] = [item()] * 999
        with self.assertRaises(NutritionError):
            revalidate_plan(state, {}, self.catalog)


if __name__ == "__main__":
    unittest.main()
