"""Observable eligibility, timing, exit, and ordinary-food strategy boundaries."""

from copy import deepcopy
from decimal import Inexact, localcontext
import unittest

from nutrition_core.catalog import load_catalog
from nutrition_core.common import NutritionError
from nutrition_core.strategies import fasting_plan, traditional_foods


def profile():
    return {"id": "strategy_test", "age": 34, "goals": ["wellbeing"],
            "measurements": {"height_cm": "175", "weight_kg": "75", "measured_on": "2026-10-06"},
            "health": {"allergens": [], "conditions": [], "medications": [],
                       "pregnancy_lactation": False, "eating_disorder_risk": False,
                       "malnutrition_risk": False},
            "preferences": {"cuisine": "chinese", "effort": "lazy", "scenario": "home", "dislikes": []}}


def fasting_request():
    return {"opt_in": True, "pattern": "16:8", "eating_start": "09:00",
            "wake_time": "07:00", "sleep_time": "23:00", "work_pattern": "day",
            "symptoms": [], "previously_stopped_for_symptoms": False, "can_meet_daily_needs": True}


class FastingStrategyTests(unittest.TestCase):
    def test_all_three_patterns_preserve_nutrition_and_offer_meal_times(self):
        for pattern, end, minutes in (("12:12", "21:00", 720), ("14:10", "19:00", 600), ("16:8", "17:00", 480)):
            request = fasting_request() | {"pattern": pattern}
            result = fasting_plan(profile(), "2026-10-06", request)
            with self.subTest(pattern=pattern):
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["schedule"]["end"], {"time": end, "day_offset": 0})
                self.assertEqual(result["schedule"]["eating_minutes"], minutes)
                self.assertEqual(result["schedule"]["fasting_minutes"], 1440 - minutes)
                self.assertEqual(len(result["schedule"]["meal_times"]), 3)
                self.assertFalse(result["changes_daily_nutrition_targets"])
                self.assertFalse(result["clinical_prescription"])

    def test_unknown_or_missing_opt_in_never_enables(self):
        for value in (None, False):
            result = fasting_plan(profile(), "2026-10-06", fasting_request() | {"opt_in": value})
            self.assertIsNone(result["schedule"])
            self.assertEqual(result["status"], "needs_information" if value is None else "not_enabled")
        request = fasting_request()
        del request["opt_in"]
        self.assertIn("request.opt_in", fasting_plan(profile(), "2026-10-06", request)["missing_fields"])

    def test_each_unknown_health_or_exit_input_remains_unknown(self):
        for field in profile()["health"]:
            p = profile()
            p["health"][field] = None
            result = fasting_plan(p, "2026-10-06", fasting_request())
            with self.subTest(field=field):
                self.assertIsNone(result["schedule"])
                self.assertIn(f"profile.health.{field}", result["missing_fields"])
        for field in ("symptoms", "previously_stopped_for_symptoms", "can_meet_daily_needs"):
            result = fasting_plan(profile(), "2026-10-06", fasting_request() | {field: None})
            self.assertEqual(result["status"], "needs_information")
            self.assertIn(f"request.{field}", result["missing_fields"])

    def test_special_populations_and_low_bmi_are_not_enabled(self):
        for key, value in (("conditions", ["diabetes"]), ("medications", ["insulin"]),
                           ("pregnancy_lactation", True), ("eating_disorder_risk", True), ("malnutrition_risk", True)):
            p = profile(); p["health"][key] = value
            self.assertEqual(fasting_plan(p, "2026-10-06", fasting_request())["status"], "not_enabled")
        for age in (18, 65):
            p = profile(); p["age"] = age
            self.assertEqual(fasting_plan(p, "2026-10-06", fasting_request())["status"], "not_enabled")
        for weight in ("50", "130"):
            p = profile(); p["measurements"]["weight_kg"] = weight
            result = fasting_plan(p, "2026-10-06", fasting_request())
            self.assertEqual(result["status"], "not_enabled")
            self.assertIn("outside_supported_bmi", result["issues"])

    def test_measurements_require_current_known_date_and_bounded_values(self):
        for date in ("2026-09-01", "2026-10-07"):
            p = profile(); p["measurements"]["measured_on"] = date
            self.assertEqual(fasting_plan(p, "2026-10-06", fasting_request())["status"], "needs_information")
        p = profile(); del p["measurements"]
        result = fasting_plan(p, "2026-10-06", fasting_request())
        self.assertIn("profile.measurements.height_cm", result["missing_fields"])
        p = profile(); p["measurements"]["height_cm"] = "100"
        self.assertEqual(fasting_plan(p, "2026-10-06", fasting_request())["status"], "not_enabled")

    def test_current_symptoms_or_prior_symptom_stop_prevents_restart(self):
        for change in ({"symptoms": ["头晕"]}, {"previously_stopped_for_symptoms": True},
                       {"symptoms": ["nausea"], "opt_in": False}):
            result = fasting_plan({"id": "strategy_test"}, "2026-10-06", fasting_request() | change)
            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["action"], "stop_and_resume_regular_meals")
            self.assertFalse(result["restart_allowed"])
            self.assertIsNone(result["schedule"])

    def test_night_shift_and_rotating_shift_have_explicit_day_offsets(self):
        request = fasting_request() | {"work_pattern": "night", "wake_time": "20:00", "sleep_time": "09:00", "eating_start": "22:00"}
        result = fasting_plan(profile(), "2026-10-06", request)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["schedule"]["end"], {"time": "06:00", "day_offset": 1})
        request.update(work_pattern="rotating", eating_start="00:30")
        result = fasting_plan(profile(), "2026-10-06", request)
        self.assertEqual(result["schedule"]["start"], {"time": "00:30", "day_offset": 1})
        self.assertEqual(result["schedule"]["end"], {"time": "08:30", "day_offset": 1})
        self.assertFalse(result["schedule"]["automatically_repeats"])
        self.assertEqual(result["schedule"]["valid_for"], "2026-10-06")

    def test_sleep_conflict_and_explicit_end_mismatch_do_not_emit_schedule(self):
        for changes, issue in (({"eating_start": "18:00"}, "window_outside_awake_period"),
                                ({"sleep_time": "07:00"}, "window_outside_awake_period"),
                                ({"eating_end": "18:00"}, "eating_window_duration_mismatch")):
            result = fasting_plan(profile(), "2026-10-06", fasting_request() | changes)
            self.assertEqual(result["status"], "conflict")
            self.assertIsNone(result["schedule"])
            self.assertIn(issue, result["issues"])
        self.assertEqual(fasting_plan(profile(), "2026-10-06", fasting_request() | {"eating_end": "17:00"})["status"], "ok")

    def test_cannot_meet_daily_nutrition_does_not_compress_meals(self):
        result = fasting_plan(profile(), "2026-10-06", fasting_request() | {"can_meet_daily_needs": False})
        self.assertEqual(result["status"], "not_enabled")
        self.assertIsNone(result["schedule"])

    def test_invalid_times_patterns_unknown_fields_and_wrong_types_raise_domain_errors(self):
        for field, value in (("eating_start", "24:00"), ("wake_time", "7:00"), ("sleep_time", "20:60"),
                             ("pattern", "20:4"), ("pattern", []), ("work_pattern", []),
                             ("opt_in", 1), ("symptoms", "none"), ("symptoms", [""])):
            with self.subTest(field=field, value=value), self.assertRaises(NutritionError):
                fasting_plan(profile(), "2026-10-06", fasting_request() | {field: value})
        with self.assertRaises(NutritionError):
            fasting_plan(profile(), "2026-10-06", fasting_request() | {"fast_for_days": 3})

    def test_inputs_are_immutable_and_decimal_context_isolated(self):
        p, request = profile(), fasting_request()
        before = deepcopy((p, request))
        with localcontext() as context:
            context.prec = 3; context.traps[Inexact] = True
            result = fasting_plan(p, "2026-10-06", request)
            self.assertEqual(context.prec, 3)
        result["request"]["symptoms"].append("changed output")
        self.assertEqual((p, request), before)


class TraditionalFoodStrategyTests(unittest.TestCase):
    def test_each_method_has_real_food_ids_and_actionable_nonclinical_steps(self):
        catalog = load_catalog()
        for method in ("porridge", "boil", "steam"):
            result = traditional_foods(profile(), "2026-10-06", {"opt_in": True, "purpose": "ordinary_food", "method": method})
            self.assertEqual(result["status"], "ok")
            recipe = result["recommendations"][0]
            self.assertGreaterEqual(len(recipe["steps"]), 3)
            self.assertTrue(all(food["food_id"] in catalog["foods"] for food in recipe["foods"]))
            self.assertEqual(recipe["nutrition_calculation"], "not_calculated")
            self.assertFalse(recipe["ingredients_verified"])
            self.assertEqual(recipe["clinical_claims"], [])
            self.assertFalse(result["changes_daily_nutrition_targets"])

    def test_treatment_constitution_and_herbs_do_not_produce_prescriptions(self):
        for purpose in ("treatment", "constitution", "herbal"):
            result = traditional_foods(profile(), "2026-10-06", {"opt_in": True, "purpose": purpose})
            self.assertEqual(result["status"], "education_only")
            self.assertEqual(result["recommendations"], [])
            self.assertFalse(result["clinical_prescription"])

    def test_unknown_allergy_and_known_allergy_do_not_claim_safe_foods(self):
        for allergens in (None, ["egg"]):
            p = profile(); p["health"]["allergens"] = allergens
            result = traditional_foods(p, "2026-10-06", {"opt_in": True, "purpose": "ordinary_food", "method": "porridge"})
            self.assertEqual(result["status"], "needs_information")
            self.assertEqual(result["recommendations"], [])
            self.assertTrue(result["missing_fields"])

    def test_special_requirements_keep_existing_meals(self):
        p = profile(); p["health"]["conditions"] = ["kidney disease"]
        result = traditional_foods(p, "2026-10-06", {"opt_in": True, "purpose": "ordinary_food", "method": "boil"})
        self.assertEqual(result["status"], "education_only")
        self.assertEqual(result["recommendations"], [])

    def test_dislikes_and_explicit_exclusions_are_respected(self):
        request = {"opt_in": True, "purpose": "ordinary_food", "method": "porridge"}
        p = profile(); p["preferences"]["dislikes"] = ["燕麥"]
        self.assertEqual(traditional_foods(p, "2026-10-06", request)["status"], "conflict")
        result = traditional_foods(profile(), "2026-10-06", request | {"exclude_food_ids": ["usda:173424"]})
        self.assertEqual(result["conflicting_food_ids"], ["usda:173424"])
        self.assertEqual(result["recommendations"], [])

    def test_opt_in_missing_and_false_are_not_inferred(self):
        for request in ({}, {"opt_in": None}, {"opt_in": False}):
            self.assertEqual(traditional_foods(profile(), "2026-10-06", request)["recommendations"], [])

    def test_invalid_values_and_mutation_are_handled(self):
        for field, value in (("method", "detox"), ("method", []), ("purpose", []),
                             ("opt_in", "yes"), ("exclude_food_ids", [1])):
            with self.assertRaises(NutritionError):
                traditional_foods(profile(), "2026-10-06", {field: value})
        p = profile(); request = {"opt_in": True, "purpose": "ordinary_food", "method": "boil"}
        before = deepcopy((p, request))
        result = traditional_foods(p, "2026-10-06", request)
        result["recommendations"][0]["steps"].append("changed output")
        self.assertEqual((p, request), before)
        self.assertEqual(len(traditional_foods(p, "2026-10-06", request)["recommendations"][0]["steps"]), 3)


if __name__ == "__main__":
    unittest.main()
