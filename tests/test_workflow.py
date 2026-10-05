"""Observable M3 routing, qualitative meals, reviews, and record invariants."""

from copy import deepcopy
from decimal import Decimal
from itertools import product
import unittest

from nutrition_core.common import NutritionError
from nutrition_core.workflow import (
    assess_profile, next_meal, validate_document, validate_profile, weekly_review,
)


AS_OF = "2026-10-05"


def profile():
    return {"id": "alice", "age": 30, "goals": ["wellbeing"],
            "preferences": {"cuisine": "chinese", "effort": "lazy", "scenario": "home", "dislikes": []},
            "health": {"allergens": [], "conditions": [], "medications": [],
                       "pregnancy_lactation": False, "eating_disorder_risk": False,
                       "malnutrition_risk": False}, "storage": "temporary"}


def feedback():
    return {"days_observed": 7, "adherence": "easy", "hunger": "comfortable",
            "energy": "normal", "training": "normal", "health_changed": False,
            "appetite_declined": False, "unintentional_weight_loss": False,
            "returning_after_gap": False}


def professional_plan():
    return {"member_id": "alice", "source": "Fictional confirmed clinician instructions",
            "issued_on": "2026-10-01", "review_on": "2026-11-01", "confirmed": True,
            "meals": {"lunch": "沿用已确认的午餐安排和个人份量。"},
            "substitutions": ["替换前联系原计划制定者确认。"]}


def document():
    return {"schema_version": "m3-1", "profile": profile()}


def note(status="confirmed", quantity_status="estimated"):
    return {"date": AS_OF, "meal_id": "lunch", "status": status,
            "food_summary": "已吃便当，食材未匹配目录", "quantity_note": "约半盒",
            "quantity_status": quantity_status}


def day(actual_status="unknown"):
    actual = {"status": actual_status}
    if actual_status in {"confirmed", "partial"}:
        actual["items"] = [{"food_id": "usda:171077", "quantity": {"amount": "100", "unit": "g"}}]
    return {"revision": 0, "meals": [{"id": "lunch", "locked": True, "items": []}],
            "actuals": {"lunch": actual}}


class ProfileValidationTests(unittest.TestCase):
    def test_minimal_profile_is_valid_and_returns_independent_copy(self):
        source = {"id": "alice"}
        self.assertEqual(validate_profile(source), source)
        full = profile()
        result = validate_profile(full)
        result["health"]["allergens"].append("milk")
        self.assertEqual(full["health"]["allergens"], [])

    def test_unknown_fields_and_private_raw_payloads_are_rejected(self):
        for field in ("prompt", "transcript", "photo", "report", "heath"):
            with self.subTest(field=field), self.assertRaises(NutritionError):
                validate_profile({**profile(), field: "unstructured data"})
        p = profile()
        p["health"]["pregnant"] = False
        with self.assertRaises(NutritionError):
            validate_profile(p)

    def test_non_json_values_and_cycles_are_rejected(self):
        for value in ({1, 2}, (1, 2), Decimal("1"), 1.5, b"secret"):
            with self.subTest(value=value), self.assertRaises(NutritionError):
                validate_profile({"id": "alice", "age": value})
        p = {"id": "alice"}
        p["health"] = p
        with self.assertRaises(NutritionError):
            validate_profile(p)

    def test_member_age_goal_and_priority_validation(self):
        invalid = [{"id": "../alice"}, {"id": "Alice"}, {"id": "a" * 65},
                   {"id": "alice", "age": True}, {"id": "alice", "age": 0},
                   {"id": "alice", "age": 121}, {"id": "alice", "goals": ["fasting"]},
                   {"id": "alice", "goals": ["wellbeing"], "priority": "muscle_gain"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(NutritionError):
                validate_profile(value)

    def test_measurements_are_positive_decimal_strings_with_canonical_dates(self):
        for value in ("0", "NaN", "-2", 74, True, 74.1):
            with self.subTest(value=value), self.assertRaises(NutritionError):
                validate_profile({"id": "alice", "measurements": {"weight_kg": value}})
        for value in ("2026-2-3", "2026-02-30", "20261005"):
            with self.subTest(value=value), self.assertRaises(NutritionError):
                validate_profile({"id": "alice", "measurements": {"measured_on": value}})
        p = {"id": "alice", "measurements": {"height_cm": "170", "weight_kg": "60.5", "measured_on": AS_OF}}
        self.assertEqual(validate_profile(p), p)

    def test_self_reported_allergens_keep_unmapped_names(self):
        p = profile()
        p["health"]["allergens"] = ["芥末", "mustard"]
        self.assertEqual(validate_profile(p)["health"]["allergens"], ["芥末", "mustard"])

    def test_capacity_and_health_types(self):
        p = profile()
        p["health"]["conditions"] = [f"condition-{i}" for i in range(65)]
        with self.assertRaises(NutritionError):
            validate_profile(p)
        p = profile()
        p["health"]["pregnancy_lactation"] = "false"
        with self.assertRaises(NutritionError):
            validate_profile(p)

    def test_professional_plan_is_member_bound_and_structured(self):
        for change in ({"member_id": "bob"}, {"confirmed": "true"},
                       {"review_on": "2026-09-01"}, {"source": " "}, {"report": "raw report"}):
            with self.subTest(change=change), self.assertRaises(NutritionError):
                p = profile()
                p["professional_plan"] = {**professional_plan(), **change}
                validate_profile(p)


class ProfileAssessmentTests(unittest.TestCase):
    def test_complete_standard_profile_does_not_generate_targets(self):
        result = assess_profile(profile(), AS_OF)
        self.assertEqual((result["status"], result["route"]), ("ok", "standard"))
        self.assertFalse(result["clinical_targets_generated"])
        self.assertEqual(result["health_basis"], "self_reported")

    def test_missing_health_is_not_assumed_false_and_questions_are_bounded(self):
        result = assess_profile({"id": "alice"}, AS_OF)
        self.assertEqual((result["status"], result["route"]), ("needs_information", "pending"))
        self.assertIn("health.medications", result["missing_fields"])
        self.assertLessEqual(len(result["questions"]), 3)
        p = profile()
        p["health"]["malnutrition_risk"] = None
        self.assertEqual(assess_profile(p, AS_OF)["route"], "pending")

    def test_multiple_goals_require_a_selected_priority(self):
        p = profile()
        p["goals"] = ["muscle_gain", "fat_loss"]
        self.assertIn("priority", assess_profile(p, AS_OF)["missing_fields"])
        p["priority"] = "muscle_gain"
        self.assertEqual(assess_profile(p, AS_OF)["route"], "standard")

    def test_underage_and_reported_nutrition_risks_use_support_only(self):
        cases = []
        p = profile()
        p["age"] = 17
        cases.append(p)
        for field in ("eating_disorder_risk", "malnutrition_risk"):
            p = profile()
            p["health"][field] = True
            cases.append(p)
        for p in cases:
            with self.subTest(profile=p):
                result = assess_profile(p, AS_OF)
                self.assertEqual(result["route"], "support_only")
                self.assertIsNone(next_meal(p, AS_OF)["recommendation"])

    def test_conditions_medications_and_pregnancy_use_professional_route(self):
        for field, value in (("conditions", ["User-reported condition"]),
                             ("medications", ["User-reported medication"]),
                             ("pregnancy_lactation", True)):
            with self.subTest(field=field):
                p = profile()
                p["health"][field] = value
                result = assess_profile(p, AS_OF)
                self.assertEqual(result["route"], "professional")
                self.assertIn("professional_plan", result["missing_fields"])

    def test_professional_plan_confirmation_expiry_and_future_issue_date(self):
        cases = [({"confirmed": False}, "professional_plan_unconfirmed"),
                 ({"review_on": "2026-10-04"}, "professional_plan_expired"),
                 ({"issued_on": "2026-10-06"}, "professional_plan_not_yet_issued")]
        for change, code in cases:
            with self.subTest(change=change):
                p = profile()
                p["professional_plan"] = {**professional_plan(), **change}
                result = assess_profile(p, AS_OF)
                self.assertFalse(result["professional_plan_usable"])
                self.assertIn(code, [x["code"] for x in result["issues"]])
                self.assertIsNone(next_meal(p, AS_OF)["recommendation"])

    def test_measurement_dates_and_review_due_boundary_are_explicit(self):
        p = profile()
        p["measurements"] = {"weight_kg": "60", "measured_on": "2026-10-06"}
        self.assertIn("measurement_in_future", [x["code"] for x in assess_profile(p, AS_OF)["issues"]])
        p = profile()
        p["professional_plan"] = {**professional_plan(), "review_on": AS_OF}
        self.assertTrue(assess_profile(p, AS_OF)["professional_plan_usable"])
        self.assertIn("professional_plan_review_due", [x["code"] for x in assess_profile(p, AS_OF)["issues"]])


class MealWorkflowTests(unittest.TestCase):
    def test_cuisine_effort_scenario_and_meal_combinations_have_qualitative_candidates(self):
        for cuisine, effort, scenario, meal in product(
                ("chinese", "western", "mixed"), ("lazy", "standard"),
                ("home", "takeaway", "no_cook"), ("breakfast", "lunch", "dinner", "snack")):
            with self.subTest(cuisine=cuisine, effort=effort, scenario=scenario, meal=meal):
                p = profile()
                p["preferences"].update(cuisine=cuisine, effort=effort, scenario=scenario)
                result = next_meal(p, AS_OF, meal)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["recommendation"]["validation"], "qualitative_only")
                self.assertTrue(result["recommendation"]["foods"])
                self.assertTrue(result["recommendation"]["portion_note"])
                self.assertNotIn("energy_kcal", result["recommendation"])
                self.assertLessEqual(len(result["alternatives"]), 2)

    def test_excluded_food_template_is_replaced_without_mutating_profile(self):
        p = profile()
        before = deepcopy(p)
        first = next_meal(p, AS_OF)
        excluded = [first["recommendation"]["id"]]
        replacement = next_meal(p, AS_OF, excluded_ids=excluded)
        self.assertNotIn(replacement["recommendation"]["id"], excluded)
        self.assertEqual(p, before)
        self.assertEqual(excluded, [first["recommendation"]["id"]])

    def test_explicit_dislikes_filter_foods_and_aliases(self):
        p = profile()
        p["preferences"]["dislikes"] = ["chicken"]
        result = next_meal(p, AS_OF)
        ids = [x["id"] for x in [result["recommendation"], *result["alternatives"]]]
        self.assertNotIn("cn-chicken-rice", ids)
        self.assertNotIn("west-chicken-sandwich", ids)

    def test_all_candidates_can_be_excluded_without_inventing_a_replacement(self):
        p, excluded = profile(), []
        for _ in range(20):
            result = next_meal(p, AS_OF, excluded_ids=excluded)
            if result["recommendation"] is None:
                break
            excluded.append(result["recommendation"]["id"])
        self.assertEqual(result["status"], "needs_information")
        self.assertIsNone(result["recommendation"])
        self.assertEqual(result["alternatives"], [])
        self.assertIn("no_matching_template", [x["code"] for x in result["issues"]])

    def test_unknown_health_or_unmapped_allergen_never_yields_standard_substitution(self):
        p = profile()
        p["health"]["allergens"] = ["芥末"]
        self.assertIsNone(next_meal(p, AS_OF)["recommendation"])
        p["health"]["allergens"] = None
        self.assertIsNone(next_meal(p, AS_OF)["recommendation"])

    def test_professional_transcription_is_exact_and_never_a_verified_substitution(self):
        p = profile()
        p["health"]["conditions"] = ["User-reported kidney disease"]
        p["health"]["allergens"] = ["milk"]
        p["professional_plan"] = professional_plan()
        result = next_meal(p, AS_OF)
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(result["recommendation"]["arrangement"], p["professional_plan"]["meals"]["lunch"])
        self.assertEqual(result["recommendation"]["kind"], "professional_plan_transcription")
        self.assertFalse(result["recommendation"]["ingredients_verified"])
        self.assertEqual(result["alternatives"], [])
        self.assertIsNone(next_meal(p, AS_OF, meal_id="dinner")["recommendation"])
        self.assertIsNone(next_meal(p, AS_OF, excluded_ids=[result["recommendation"]["id"]])["recommendation"])

    def test_missing_preferences_are_explicit_assumptions(self):
        p = profile()
        del p["preferences"]
        result = next_meal(p, AS_OF)
        self.assertEqual(result["selection"], {"cuisine": "mixed", "effort": "lazy", "scenario": "home"})
        self.assertEqual(len(result["assumptions"]), 3)

    def test_unknown_meal_template_and_noncanonical_dates_fail(self):
        for kwargs in ({"meal_id": "luch"}, {"excluded_ids": ["no-such-template"]},
                       {"excluded_ids": "cn-chicken-rice"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(NutritionError):
                next_meal(profile(), AS_OF, **kwargs)
        with self.assertRaises(NutritionError):
            next_meal(profile(), "2026-2-2")


class WeeklyReviewTests(unittest.TestCase):
    def test_no_training_is_known_and_survives_document_validation(self):
        f = {**feedback(), "training": "not_training", "adherence": "unknown",
             "adherent_days": 5}
        result = weekly_review(profile(), f, AS_OF)
        self.assertEqual(result["feedback"]["training"], "not_training")
        self.assertNotIn("feedback.training", result["missing_fields"])
        self.assertIn("feedback.adherence", result["missing_fields"])
        self.assertFalse(any(result["adjustments"].values()))
        self.assertNotIn("review_schedule", [x["code"] for x in result["suggestions"]])
        doc = {"schema_version": "m3-1", "profile": profile(), "reviews": [result]}
        self.assertEqual(validate_document(doc), doc)
        for training in ("normal", "changed", "unknown"):
            with self.subTest(training=training):
                old = weekly_review(profile(), {**feedback(), "training": training}, AS_OF)
                self.assertEqual(old["feedback"]["training"], training)
                self.assertEqual("feedback.training" in old["missing_fields"], training == "unknown")

    def test_stable_feedback_keeps_targets_and_adjusts_only_convenience(self):
        p, f = profile(), feedback()
        originals = deepcopy((p, f))
        result = weekly_review(p, f, AS_OF)
        self.assertEqual((result["status"], result["action"]), ("ok", "maintain_and_simplify"))
        self.assertEqual(result["adjustments"], {"energy_kcal": False, "protein_g": False, "eating_window": False})
        self.assertEqual((p, f), originals)

    def test_hunger_alone_keeps_targets_with_tolerance_review(self):
        f = {**feedback(), "hunger": "hungry", "adherence": "hard"}
        result = weekly_review(profile(), f, AS_OF)
        self.assertEqual(result["action"], "maintain_and_simplify")
        self.assertIn("review_tolerance", [x["code"] for x in result["suggestions"]])
        self.assertIn("simplify_preparation", [x["code"] for x in result["suggestions"]])

    def test_weekly_observation_facts_are_preserved_without_inventing_observed_days(self):
        facts = {"adherent_days": 5, "hunger_days": 2, "hunger_times": ["afternoon"],
                 "weigh_ins_count": 3, "has_previous_week_baseline": False}
        f = {**feedback(), **facts, "hunger": "hungry"}
        del f["days_observed"]
        original = deepcopy(f)
        result = weekly_review(profile(), f, AS_OF)
        for field, value in facts.items():
            self.assertEqual(result["feedback"][field], value)
        self.assertIsNone(result["feedback"]["days_observed"])
        self.assertEqual(result["action"], "maintain_and_simplify")
        self.assertFalse(any(result["adjustments"].values()))
        self.assertEqual(f, original)

    def test_optional_observations_default_to_unknown_without_blocking_qualitative_review(self):
        result = weekly_review(profile(), feedback(), AS_OF)
        for field in ("adherent_days", "hunger_days", "hunger_times", "weigh_ins_count",
                      "has_previous_week_baseline"):
            self.assertIsNone(result["feedback"][field])
            self.assertNotIn(f"feedback.{field}", result["missing_fields"])
        self.assertEqual(result["status"], "ok")

    def test_observation_fields_have_strict_types_ranges_and_enums(self):
        invalid = [{"adherent_days": value} for value in (-1, 8, True, 5.0, "5")]
        invalid += [{"hunger_days": value} for value in (-1, 8, True)]
        invalid += [{"weigh_ins_count": value} for value in (-1, 101, True, "3")]
        invalid += [{"hunger_times": value} for value in
                    ("afternoon", ["after_lunch"], ["afternoon", "afternoon"], [None])]
        invalid += [{"has_previous_week_baseline": value} for value in (0, 1, "false")]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(NutritionError):
                weekly_review(profile(), {**feedback(), **change}, AS_OF)

    def test_health_changes_appetite_decline_and_unintentional_loss_take_priority(self):
        for field in ("health_changed", "appetite_declined", "unintentional_weight_loss"):
            with self.subTest(field=field):
                result = weekly_review(profile(), {**feedback(), field: True}, AS_OF)
                self.assertEqual(result["action"], "pause_and_review")
                self.assertEqual(result["route"], "professional")
                self.assertIn("professional_review", [x["code"] for x in result["suggestions"]])

    def test_unknown_risk_flags_remain_unknown_and_pause_optimization(self):
        result = weekly_review(profile(), {}, AS_OF)
        self.assertIsNone(result["feedback"]["health_changed"])
        self.assertEqual(result["feedback"]["hunger"], "unknown")
        self.assertIn("feedback.health_changed", result["missing_fields"])
        self.assertEqual(result["action"], "pause_and_review")

    def test_low_energy_pauses_and_schedule_change_does_not_reduce_food(self):
        self.assertEqual(weekly_review(profile(), {**feedback(), "energy": "low"}, AS_OF)["action"],
                         "pause_and_review")
        changed = weekly_review(profile(), {**feedback(), "training": "changed"}, AS_OF)
        self.assertEqual(changed["action"], "maintain_and_simplify")
        self.assertFalse(changed["adjustments"]["energy_kcal"])
        self.assertIn("review_schedule", [x["code"] for x in changed["suggestions"]])

    def test_return_after_gap_resumes_next_meal_without_backfill(self):
        result = weekly_review(profile(), {**feedback(), "returning_after_gap": True}, AS_OF)
        self.assertEqual(result["recovery_mode"], "next_meal_only")
        self.assertIn("resume_next_meal", [x["code"] for x in result["suggestions"]])
        self.assertIn("regular_meals_no_compensation", [x["code"] for x in result["suggestions"]])

    def test_invalid_feedback_cannot_clear_restrictions(self):
        for change in ({"days_observed": 8}, {"days_observed": True}, {"health_changed": "false"},
                       {"hunger": "no"}, {"health_chagned": False}, {"target_calories": "1200"}):
            with self.subTest(change=change), self.assertRaises(NutritionError):
                weekly_review(profile(), {**feedback(), **change}, AS_OF)


class DocumentValidationTests(unittest.TestCase):
    def test_document_copy_and_allowed_structured_records(self):
        doc = document()
        doc["journal"] = [note()]
        doc["reviews"] = [weekly_review(profile(), feedback(), AS_OF)]
        result = validate_document(doc)
        result["journal"][0]["food_summary"] = "changed"
        self.assertNotEqual(result, doc)

    def test_unknown_media_transcript_and_schema_fields_are_rejected(self):
        for field in ("prompt", "transcript", "photos", "reports", "raw_json"):
            with self.subTest(field=field), self.assertRaises(NutritionError):
                validate_document({**document(), field: "raw data"})
        with self.assertRaises(NutritionError):
            validate_document({**document(), "schema_version": "m9"})

    def test_days_use_actual_m2_validation_and_can_hold_future_plans(self):
        doc = {**document(), "days": {"2027-01-01": day()}}
        self.assertEqual(validate_document(doc), doc)
        doc["days"]["2027-01-01"]["meals"][0]["locked"] = "false"
        with self.assertRaises(NutritionError):
            validate_document(doc)

    def test_journal_duplicate_or_conflicting_quantitative_intake_is_rejected(self):
        with self.assertRaises(NutritionError) as error:
            validate_document({**document(), "journal": [note(), note()]})
        self.assertEqual(error.exception.code, "duplicate_intake_record")
        for status in ("confirmed", "partial", "not_eaten"):
            with self.subTest(status=status), self.assertRaises(NutritionError) as error:
                validate_document({**document(), "days": {AS_OF: day(status)}, "journal": [note()]})
            self.assertEqual(error.exception.code, "duplicate_intake_record")
        doc = {**document(), "days": {AS_OF: day("unknown")}, "journal": [note()]}
        self.assertEqual(validate_document(doc), doc)

    def test_journal_quantity_uncertainty_is_structured_not_assumed_zero(self):
        for status, quantity_status in (("unknown", "known"), ("not_eaten", "unknown")):
            with self.subTest(status=status), self.assertRaises(NutritionError):
                validate_document({**document(), "journal": [note(status, quantity_status)]})
        for status, quantity_status in (("confirmed", "unknown"), ("partial", "estimated"),
                                        ("unknown", "unknown"), ("not_eaten", "known")):
            with self.subTest(status=status):
                doc = {**document(), "journal": [note(status, quantity_status)]}
                self.assertEqual(validate_document(doc), doc)

    def test_review_is_member_bound_but_not_recomputed_against_later_profile(self):
        review = weekly_review(profile(), feedback(), AS_OF)
        later = profile()
        later["health"]["conditions"] = ["Newly reported condition"]
        doc = {"schema_version": "m3-1", "profile": later, "reviews": [review]}
        self.assertEqual(validate_document(doc)["reviews"][0], review)
        review["member_id"] = "bob"
        with self.assertRaises(NutritionError):
            validate_document(doc)

    def test_legacy_nine_field_review_loads_without_rewriting_its_feedback(self):
        review = weekly_review(profile(), feedback(), AS_OF)
        for field in ("adherent_days", "hunger_days", "hunger_times", "weigh_ins_count",
                      "has_previous_week_baseline"):
            del review["feedback"][field]
        self.assertEqual(len(review["feedback"]), 9)
        doc = {**document(), "reviews": [review]}
        original = deepcopy(doc)
        validated = validate_document(doc)
        self.assertEqual(doc, original)
        self.assertEqual(validated, original)
        self.assertEqual(len(validated["reviews"][0]["feedback"]), 9)

    def test_review_unknown_fields_and_quantitative_adjustments_are_rejected(self):
        for change in ({"prompt": "raw"}, {"adjustments": {"energy_kcal": True, "protein_g": False, "eating_window": False}}):
            with self.subTest(change=change), self.assertRaises(NutritionError):
                review = {**weekly_review(profile(), feedback(), AS_OF), **change}
                validate_document({**document(), "reviews": [review]})

    def test_saved_review_cannot_contradict_its_own_risk_or_recovery_feedback(self):
        risky = weekly_review(profile(), {**feedback(), "health_changed": True}, AS_OF)
        risky["action"] = "maintain_and_simplify"
        gap = weekly_review(profile(), {**feedback(), "returning_after_gap": True}, AS_OF)
        gap["recovery_mode"] = "none"
        incomplete = weekly_review(profile(), feedback(), AS_OF)
        incomplete["missing_fields"] = ["feedback.hunger"]
        for review in (risky, gap, incomplete):
            with self.subTest(review=review), self.assertRaises(NutritionError) as error:
                validate_document({**document(), "reviews": [review]})
            self.assertEqual(error.exception.code, "inconsistent_review")

    def test_document_collection_capacities_are_explicit(self):
        for change in ({"journal": [note()] * 1001},
                       {"reviews": [weekly_review(profile(), feedback(), AS_OF)] * 53},
                       {"days": {str(i): {} for i in range(367)}}):
            with self.subTest(field=next(iter(change))), self.assertRaises(NutritionError) as error:
                validate_document({**document(), **change})
            self.assertEqual(error.exception.code, "input_capacity_exceeded")


if __name__ == "__main__":
    unittest.main()
