"""Estimation, eligibility, persisted provenance, and bounded observed changes."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, localcontext
import unittest

from nutrition_core.common import NutritionError
from nutrition_core.targets import derive_targets, review_targets, validate_review, validate_target


def profile(goal="fat_loss"):
    return {"id": "target_trial", "age": 35, "goals": [goal],
            "measurements": {"height_cm": "175", "weight_kg": "80", "measured_on": "2026-10-01"},
            "health": {"allergens": [], "conditions": [], "medications": [],
                       "pregnancy_lactation": False, "eating_disorder_risk": False,
                       "malnutrition_risk": False}}


def inputs(training=False):
    return {"sex_for_equation": "male", "activity": "inactive", "resistance_training": training}


def observations(recent="80", start="2026-10-02"):
    begin = date.fromisoformat(start)
    return {"window_start": start, "window_end": (begin + timedelta(days=13)).isoformat(),
            "weigh_ins": [{"date": (begin + timedelta(days=day)).isoformat(),
                           "weight_kg": "80" if day < 7 else recent} for day in (0, 2, 4, 7, 9, 11)],
            "adherent_days": 14, "comparable_conditions": True,
            "health_changed": False, "appetite_declined": False,
            "unintentional_weight_loss": False, "returning_after_gap": False,
            "activity_changed": False, "energy": "normal", "hunger": "comfortable"}


class DeriveTargetsTests(unittest.TestCase):
    def test_official_eer_equations_for_both_sexes_and_all_activity_categories(self):
        expected = {"male": ("2639.52", "2850.12", "3039.57", "3363.62"),
                    "female": ("2277.35", "2456.62", "2596.6", "2858.53")}
        for sex, values in expected.items():
            for activity, value in zip(("inactive", "low_active", "active", "very_active"), values):
                with self.subTest(sex=sex, activity=activity):
                    chosen = dict(inputs(), sex_for_equation=sex, activity=activity)
                    target = derive_targets(profile(), chosen, "2026-10-01")
                    self.assertEqual(target["status"], "ok")
                    self.assertEqual(target["basis"]["maintenance_energy_kcal"], value)
                    self.assertEqual(validate_target(target, "target_trial"), target)

    def test_three_goals_have_explicit_estimates_and_sources(self):
        for goal, offset, energy in (("fat_loss", "-10", "2380"), ("muscle_gain", "5", "2770"),
                                     ("wellbeing", "0", "2640")):
            with self.subTest(goal=goal):
                target = derive_targets(profile(goal), inputs(goal == "muscle_gain"), "2026-10-01")
                self.assertEqual(target["energy_offset_percent"], offset)
                self.assertEqual(target["energy_kcal"]["target"], energy)
                self.assertEqual(target["protein_g"], {"min": "112", "target": "128", "max": "160"}
                                 if goal == "muscle_gain" else {"min": "96", "target": "112", "max": "128"})
                self.assertIn("nasem-energy-2023", target["source_ids"])
                self.assertTrue(target["notes"])

    def test_missing_information_is_never_inferred(self):
        target = derive_targets({"id": "trial"}, {}, "2026-10-01")
        self.assertEqual(target["status"], "needs_information")
        self.assertIn("inputs.sex_for_equation", target["missing_fields"])
        self.assertIn("inputs.activity", target["missing_fields"])
        self.assertIn("profile.health.conditions", target["missing_fields"])
        self.assertIsNone(target["energy_kcal"])
        validate_target(target, "trial")

    def test_ambiguous_goal_remains_missing(self):
        p = profile()
        p["goals"].append("muscle_gain")
        target = derive_targets(p, inputs(), "2026-10-01")
        self.assertEqual(target["status"], "needs_information")
        self.assertIn("profile.priority", target["missing_fields"])

    def test_age_support_is_narrower_than_adult_equation(self):
        for age in (17, 18, 65, 78):
            p = dict(profile(), age=age)
            self.assertEqual(derive_targets(p, inputs(), "2026-10-01")["status"], "not_eligible")
        for age in (19, 64):
            self.assertEqual(derive_targets(dict(profile(), age=age), inputs(), "2026-10-01")["status"], "ok")

    def test_health_risks_do_not_receive_automatic_targets(self):
        for field, value in (("conditions", ["kidney disease"]), ("medications", ["insulin"]),
                             ("pregnancy_lactation", True), ("eating_disorder_risk", True),
                             ("malnutrition_risk", True)):
            p = profile()
            p["health"][field] = value
            target = derive_targets(p, inputs(), "2026-10-01")
            self.assertEqual(target["status"], "not_eligible")
            self.assertIsNone(target["protein_g"])

    def test_unknown_health_is_not_a_negative_screen(self):
        p = profile()
        p["health"]["medications"] = None
        self.assertEqual(derive_targets(p, inputs(), "2026-10-01")["status"], "needs_information")

    def test_allergy_is_retained_but_not_used_as_an_energy_contraindication(self):
        p = profile()
        p["health"]["allergens"] = ["milk"]
        target = derive_targets(p, inputs(), "2026-10-01")
        self.assertEqual(target["status"], "ok")
        self.assertEqual(p["health"]["allergens"], ["milk"])

    def test_stale_future_and_missing_measurements(self):
        for measured in ("2026-08-31", "2026-10-02"):
            p = profile()
            p["measurements"]["measured_on"] = measured
            target = derive_targets(p, inputs(), "2026-10-01")
            self.assertEqual(target["status"], "needs_information")
            self.assertIn("profile.measurements.measured_on", target["missing_fields"])

    def test_low_bmi_extreme_input_and_no_training_are_explicitly_unsupported(self):
        cases = []
        for weight in ("50", "60", "123", "100000"):
            p = profile()
            p["measurements"]["weight_kg"] = weight
            cases.append((p, inputs()))
        cases.append((profile("muscle_gain"), inputs()))
        for p, chosen in cases:
            with self.subTest(profile=p):
                target = derive_targets(p, chosen, "2026-10-01")
                self.assertEqual(target["status"], "not_eligible")
                self.assertIsNone(target["energy_kcal"])
                validate_target(target, p["id"])

    def test_strict_input_validation(self):
        for chosen in (dict(inputs(), activity="sedentary"), dict(inputs(), extra="ignored"),
                       dict(inputs(), resistance_training=1), dict(inputs(), sex_for_equation=[])):
            with self.assertRaises(NutritionError):
                derive_targets(profile(), chosen, "2026-10-01")
        p = profile()
        p["measurements"]["weight_kg"] = 80.0
        with self.assertRaises(NutritionError):
            derive_targets(p, inputs(), "2026-10-01")

    def test_decimal_context_and_input_immutability(self):
        p, chosen = profile(), inputs()
        original = deepcopy((p, chosen))
        target = derive_targets(p, chosen, "2026-10-01")
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(derive_targets(p, chosen, "2026-10-01"), target)
            self.assertEqual(validate_target(target, p["id"]), target)
        target["inputs"]["activity"] = "active"
        self.assertEqual((p, chosen), original)


class TargetValidationTests(unittest.TestCase):
    def test_member_and_provenance_tampering_is_rejected(self):
        original = derive_targets(profile(), inputs(), "2026-10-01")
        for field, value in (("member_id", "another"), ("policy_version", "future"), ("notes", []),
                             ("energy_offset_percent", "-25"), ("status", []), ("goal", {})):
            target = deepcopy(original)
            target[field] = value
            with self.subTest(field=field), self.assertRaises(NutritionError):
                validate_target(target, "target_trial")

    def test_modified_energy_protein_and_equation_are_rejected(self):
        original = derive_targets(profile(), inputs(), "2026-10-01")
        for section, field, value in (("energy_kcal", "target", "500"), ("protein_g", "max", "400"),
                                      ("basis", "maintenance_energy_kcal", "1000"), ("basis", "bmi", "20")):
            target = deepcopy(original)
            target[section][field] = value
            with self.assertRaises(NutritionError):
                validate_target(target, "target_trial")

    def test_pending_result_cannot_smuggle_active_target(self):
        target = derive_targets({"id": "trial"}, {}, "2026-10-01")
        target["energy_kcal"] = {"min": "500", "target": "600", "max": "700"}
        with self.assertRaises(NutritionError):
            validate_target(target, "trial")

    def test_low_energy_and_extreme_protein_ratio_are_not_silently_clamped(self):
        p = profile()
        p.update(age=64)
        p["measurements"].update(height_cm="120", weight_kg="35")
        target = derive_targets(p, dict(inputs(), sex_for_equation="female"), "2026-10-01")
        self.assertEqual(target["status"], "not_eligible")
        self.assertIn("low_energy_requires_professional_support", target["issues"])
        self.assertIsNone(target["energy_kcal"])
        validate_target(target, p["id"])
        p = profile()
        p["measurements"].update(weight_kg="120")
        p.update(age=64)
        target = derive_targets(p, dict(inputs(True), sex_for_equation="female"), "2026-10-01")
        self.assertEqual(target["status"], "not_eligible")
        self.assertIn("protein_energy_balance_requires_review", target["issues"])

    def test_unsupported_result_basis_still_requires_typed_scalars(self):
        p = profile()
        p["measurements"]["weight_kg"] = "50"
        target = derive_targets(p, inputs(), "2026-10-01")
        target["basis"]["bmi"] = {"pretend": "valid"}
        with self.assertRaises(NutritionError):
            validate_target(target, p["id"])


class ReviewTargetsTests(unittest.TestCase):
    def test_fat_loss_adjustment_direction_and_no_compensation(self):
        p = profile()
        target = derive_targets(p, inputs(), "2026-10-01")
        for weight, action, sign in (("80", "adjust", -1), ("79.6", "maintain", 0), ("79.3", "adjust", 1)):
            result = review_targets(p, target, observations(weight), "2026-10-15")
            self.assertEqual(result["action"], action)
            delta = Decimal(result["change"]["energy_kcal"])
            self.assertEqual((delta > 0) - (delta < 0), sign)
            self.assertLessEqual(abs(delta), 150)
            self.assertFalse(result["change"]["protein_g"])
            self.assertFalse(result["change"]["eating_window"])

    def test_muscle_gain_adjustment_and_maintenance(self):
        p = profile("muscle_gain")
        target = derive_targets(p, inputs(True), "2026-10-01")
        for weight, sign in (("80", 1), ("80.1", 0), ("80.4", -1)):
            result = review_targets(p, target, observations(weight), "2026-10-15")
            delta = Decimal(result["change"]["energy_kcal"])
            self.assertEqual((delta > 0) - (delta < 0), sign)

    def test_wellbeing_never_automatically_chases_weight(self):
        p = profile("wellbeing")
        target = derive_targets(p, inputs(), "2026-10-01")
        result = review_targets(p, target, observations("80.4"), "2026-10-15")
        self.assertEqual(result["action"], "maintain")
        self.assertEqual(result["target"], target)

    def test_adjustment_updates_revision_and_blocks_same_window_replay(self):
        p, f = profile(), observations()
        target = derive_targets(p, inputs(), "2026-10-01")
        adjusted = review_targets(p, target, f, "2026-10-15")["target"]
        self.assertEqual(adjusted["revision"], 1)
        self.assertEqual(adjusted["as_of"], "2026-10-15")
        replay = review_targets(p, adjusted, f, "2026-10-15")
        self.assertEqual(replay["action"], "maintain")
        self.assertEqual(replay["target"], adjusted)
        self.assertIn("fourteen_days_on_current_target_required", replay["issues"])

    def test_target_cap_is_reached_without_unbounded_reductions(self):
        p = profile()
        target = derive_targets(p, inputs(), "2026-10-01")
        for review_number in range(1, 7):
            start = date(2026, 10, 2) + timedelta(days=14 * (review_number - 1))
            end = start + timedelta(days=13)
            p["measurements"]["measured_on"] = end.isoformat()
            result = review_targets(p, target, observations(start=start.isoformat()), end.isoformat())
            target = result["target"]
        self.assertEqual(target["energy_offset_percent"], "-20")
        self.assertEqual(target["revision"], 4)
        self.assertIn("adjustment_limit_reached", result["issues"])

    def test_health_unknown_changed_and_tolerance_pause(self):
        p, target = profile(), derive_targets(profile(), inputs(), "2026-10-01")
        for field, value in (("health_changed", True), ("health_changed", None), ("energy", "low"),
                             ("hunger", "hungry"), ("returning_after_gap", True),
                             ("activity_changed", True), ("unintentional_weight_loss", True)):
            f = observations()
            f[field] = value
            result = review_targets(p, target, f, "2026-10-15")
            self.assertEqual(result["action"], "pause_and_review")
            self.assertEqual(result["target"], target)

    def test_rapid_change_pauses_instead_of_rewarding_loss(self):
        p, target = profile(), derive_targets(profile(), inputs(), "2026-10-01")
        for recent in ("79.1", "81"):
            result = review_targets(p, target, observations(recent), "2026-10-15")
            self.assertEqual(result["action"], "pause_and_review")
            self.assertIn("weight_trend_requires_review", result["issues"])

    def test_missing_observations_short_window_and_low_execution_keep_target(self):
        p, target = profile(), derive_targets(profile(), inputs(), "2026-10-01")
        variants = []
        for key, value in (("adherent_days", 7), ("comparable_conditions", False), ("weigh_ins", []),
                           ("window_end", "2026-10-14")):
            f = observations()
            f[key] = value
            variants.append(f)
        f = observations()
        del f["hunger"]
        variants.append(f)
        for f in variants:
            result = review_targets(p, target, f, "2026-10-15")
            self.assertEqual(result["action"], "maintain")
            self.assertEqual(result["target"], target)

    def test_duplicate_future_outside_and_binary_weight_inputs_rejected(self):
        p, target = profile(), derive_targets(profile(), inputs(), "2026-10-01")
        for update in ({"date": "2026-10-04"}, {"date": "2026-10-16"}, {"date": "2026-10-01"},
                       {"weight_kg": 80.0}, {"weight_kg": "0"}):
            f = observations()
            f["weigh_ins"][0].update(update)
            with self.subTest(update=update), self.assertRaises(NutritionError):
                review_targets(p, target, f, "2026-10-15")

    def test_current_health_goal_and_large_measurement_change_are_rechecked(self):
        target = derive_targets(profile(), inputs(), "2026-10-01")
        variants = []
        p = profile()
        p["health"]["medications"] = ["new medicine"]
        variants.append(p)
        variants.append(profile("wellbeing"))
        p = profile()
        p["measurements"]["weight_kg"] = "88"
        variants.append(p)
        for p in variants:
            self.assertEqual(review_targets(p, target, observations(), "2026-10-15")["action"], "pause_and_review")

    def test_review_is_immutable_and_decimal_context_independent(self):
        p, f = profile(), observations()
        target = derive_targets(p, inputs(), "2026-10-01")
        originals = deepcopy((p, target, f))
        expected = review_targets(p, target, f, "2026-10-15")
        with localcontext() as ctx:
            ctx.prec = 2
            actual = review_targets(p, target, f, "2026-10-15")
        self.assertEqual(actual, expected)
        actual["target"]["energy_kcal"]["target"] = "0"
        self.assertEqual((p, target, f), originals)

    def test_persisted_review_checks_original_target_and_feedback(self):
        p = profile()
        target = derive_targets(p, inputs(), "2026-10-01")
        review = review_targets(p, target, observations(), "2026-10-15")
        self.assertEqual(validate_review(review, p["id"]), review)
        for section, field, value in (("change", "energy_kcal", "-150"),
                                      ("trend", "weekly_change_percent", "-1"),
                                      ("target", "revision", 9),
                                      ("feedback", "health_changed", True)):
            changed = deepcopy(review)
            changed[section][field] = value
            with self.subTest(section=section), self.assertRaises(NutritionError):
                validate_review(changed, p["id"])

    def test_maintain_and_pause_reviews_validate_without_fabricated_trends(self):
        p = profile()
        target = derive_targets(p, inputs(), "2026-10-01")
        for f in (observations("79.6"), {}, dict(observations(), energy="low")):
            review = review_targets(p, target, f, "2026-10-15")
            self.assertEqual(validate_review(review, p["id"]), review)


if __name__ == "__main__":
    unittest.main()


class ReviewedBoundaryRegressionTests(unittest.TestCase):
    def test_observed_bmi_crossing_upper_limit_pauses_adjustment(self):
        p = profile()
        p['measurements']['weight_kg'] = '122'
        target = derive_targets(p, inputs(), '2026-10-01')
        self.assertEqual(target['status'], 'ok')
        feedback = observations()
        for observation in feedback['weigh_ins']:
            observation['weight_kg'] = '122' if observation['date'] < '2026-10-09' else '122.6'
        review = review_targets(p, target, feedback, '2026-10-15')
        self.assertEqual(review['action'], 'pause_and_review')
        self.assertEqual(validate_review(review, p['id']), review)
