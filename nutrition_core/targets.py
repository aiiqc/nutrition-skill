"""Explicit estimates and bounded, evidence-labelled general-adult product rules.

These functions do not diagnose health or implement clinician prescriptions.
See docs/nutrition-rules.md for sources and the narrower product eligibility.
"""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
import re

from .common import NutritionError, decimal_text, exact_context, number, require_keys

POLICY_VERSION = "nutrition-policy-2026-10-06.1"
TARGET_SCHEMA = "nutrition-target-v1"
REVIEW_SCHEMA = "nutrition-target-review-v1"
ACTIVITIES = {"inactive", "low_active", "active", "very_active"}
GOALS = {"fat_loss", "muscle_gain", "wellbeing"}
# NASEM 2023 adult EER: intercept - age coefficient*A + height coefficient*H + weight coefficient*W.
EER = {
    "male": {"inactive": ("753.07", "10.83", "6.50", "14.10"),
             "low_active": ("581.47", "10.83", "8.30", "14.94"),
             "active": ("1004.82", "10.83", "6.52", "15.91"),
             "very_active": ("-517.88", "10.83", "15.61", "19.11")},
    "female": {"inactive": ("584.90", "7.01", "5.72", "11.71"),
               "low_active": ("575.77", "7.01", "6.60", "12.14"),
               "active": ("710.25", "7.01", "6.54", "12.34"),
               "very_active": ("511.83", "7.01", "9.07", "12.56")},
}
SOURCE_IDS = ["nasem-energy-2023", "dga-protein-2025-2030", "issn-protein-2017",
              "nice-ng246-2026", "energy-surplus-2023"]
NOTES = ["能量是群体方程初估，活动类别来自自报，不能诊断代谢或保证个体准确。",
         "目标及菜单容差是可追溯的产品默认，不是临床处方、统计置信区间或安全保证。",
         "蛋白质按当前实测体重计算；运动者范围不用于疾病、孕哺或其他特殊人群。",
         "单凭能量和蛋白质不能证明膳食营养完整；常规食物多样性与身体感受仍需核对。"]
TARGET_FIELDS = {"schema_version", "policy_version", "member_id", "as_of", "revision", "status",
                 "route", "goal", "inputs", "basis", "energy_offset_percent", "energy_kcal",
                 "protein_g", "missing_fields", "issues", "source_ids", "notes"}
HEALTH_FLAGS = {"health_changed", "appetite_declined", "unintentional_weight_loss",
                "returning_after_gap", "activity_changed"}
FEEDBACK_FIELDS = {"window_start", "window_end", "weigh_ins", "adherent_days",
                   "comparable_conditions", "energy", "hunger", *HEALTH_FLAGS}


def _exact(function):
    @wraps(function)
    def call(*args, **kwargs):
        with exact_context():
            return function(*args, **kwargs)
    return call


def _json(value):
    from .workflow import _json_only
    _json_only(value)


def _date(value, label):
    if not isinstance(value, str) or len(value) != 10:
        raise NutritionError("invalid_date", f"{label} must use YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise NutritionError("invalid_date", f"{label} must use YYYY-MM-DD") from None
    if result.isoformat() != value:
        raise NutritionError("invalid_date", f"{label} must use YYYY-MM-DD")
    return result


def _inputs(inputs):
    _json(inputs)
    require_keys(inputs, set(), {"sex_for_equation", "activity", "resistance_training"}, "inputs")
    result = {"sex_for_equation": inputs.get("sex_for_equation", "unknown"),
              "activity": inputs.get("activity", "unknown"),
              "resistance_training": inputs.get("resistance_training")}
    for key, choices in (("sex_for_equation", {"male", "female", "unknown"}),
                         ("activity", ACTIVITIES | {"unknown"})):
        if not isinstance(result[key], str) or result[key] not in choices:
            raise NutritionError("invalid_input", f"Unsupported inputs.{key}")
    if result["resistance_training"] is not None and type(result["resistance_training"]) is not bool:
        raise NutritionError("invalid_input", "inputs.resistance_training must be boolean or null")
    return result


def _round(value, step="1"):
    increment = Decimal(step)
    return (value / increment).quantize(Decimal(1), rounding=ROUND_HALF_UP) * increment


def _offset(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
        raise NutritionError("invalid_target", "energy_offset_percent must be a decimal string")
    number(value.lstrip("-"), "energy_offset_percent")
    return Decimal(value)


def _estimates(age, height, weight, inputs):
    with exact_context():
        a, b, c, d = map(Decimal, EER[inputs["sex_for_equation"]][inputs["activity"]])
        return a - b * age + c * height + d * weight, weight / (height / 100) ** 2


def _ranges(maintenance, weight, inputs, offset):
    with exact_context():
        energy = _round(maintenance * (1 + offset / 100), "10")
        # This is menu flexibility, not an estimate of physiological uncertainty.
        energy_range = {"min": decimal_text(_round(energy * Decimal("0.95"), "10")),
                        "target": decimal_text(energy),
                        "max": decimal_text(_round(energy * Decimal("1.05"), "10"))}
        coefficients = ("1.4", "1.6", "2") if inputs["resistance_training"] else ("1.2", "1.4", "1.6")
        protein_range = {key: decimal_text(_round(weight * Decimal(coefficient)))
                         for key, coefficient in zip(("min", "target", "max"), coefficients)}
        return energy_range, protein_range


def _product_limits(goal, age, height, weight, bmi, maintenance, inputs, energy, protein):
    issues = []
    if not 19 <= age <= 64:
        issues.append("outside_supported_age")
    if not Decimal("120") <= height <= Decimal("220") or not Decimal("35") <= weight <= Decimal("200"):
        issues.append("measurements_outside_product_range")
    if bmi < Decimal("18.5") or bmi >= 40:
        issues.append("outside_supported_bmi")
    if goal == "fat_loss" and bmi < 20:
        issues.append("fat_loss_near_lower_bmi")
    if goal == "muscle_gain" and inputs["resistance_training"] is not True:
        issues.append("resistance_training_required")
    if maintenance < 1400 or maintenance > 5000:
        issues.append("energy_estimate_outside_product_range")
    if number(energy["min"]) <= 1200:
        issues.append("low_energy_requires_professional_support")
    if number(protein["max"]) * 4 > number(energy["min"]) * Decimal("0.35"):
        issues.append("protein_energy_balance_requires_review")
    return issues


@_exact
def derive_targets(profile: dict, inputs: dict, as_of: str) -> dict:
    """Return an estimate or explicit missing/unsupported result without guessing fields."""
    from .workflow import assess_profile, validate_profile
    profile = validate_profile(profile)
    today = _date(as_of, "as_of")
    inputs = _inputs(inputs)
    assessment = assess_profile(profile, as_of)
    # Ingredient verification belongs to meal choice, not to an energy equation.
    missing = [f"profile.{field}" for field in assessment["missing_fields"]
               if field not in {"allergen_ingredient_verification", "professional_plan"}
               and not field.startswith("professional_plan.")]
    issues = []
    goal = profile.get("priority") or (profile.get("goals") or [None])[0]
    measurements = profile.get("measurements", {})
    for field in ("height_cm", "weight_kg", "measured_on"):
        if field not in measurements:
            missing.append(f"profile.measurements.{field}")
    if "measured_on" in measurements:
        measured = _date(measurements["measured_on"], "measured_on")
        if measured > today or (today - measured).days > 30:
            missing.append("profile.measurements.measured_on")
            issues.append("current_measurements_needed")
    for field, value in inputs.items():
        if value is None or value == "unknown":
            missing.append(f"inputs.{field}")
    route = assessment["route"]
    if route in {"professional", "support_only"} or "professional_plan" in profile:
        issues.append("automatic_targets_not_for_special_requirements")
    age = profile.get("age")
    if age is not None and not 19 <= age <= 64:
        issues.append("outside_supported_age")
    result = {"schema_version": TARGET_SCHEMA, "policy_version": POLICY_VERSION,
              "member_id": profile["id"], "as_of": as_of, "revision": 0,
              "status": "needs_information", "route": route, "goal": goal, "inputs": inputs,
              "basis": {}, "energy_offset_percent": None, "energy_kcal": None, "protein_g": None,
              "missing_fields": sorted(set(missing)), "issues": issues,
              "source_ids": SOURCE_IDS.copy(), "notes": NOTES.copy()}
    if issues and ("automatic_targets_not_for_special_requirements" in issues or "outside_supported_age" in issues):
        result["status"] = "not_eligible"
        return result
    if missing:
        return result
    height = number(measurements["height_cm"], "height_cm", positive=True)
    weight = number(measurements["weight_kg"], "weight_kg", positive=True)
    if not Decimal("120") <= height <= Decimal("220") or not Decimal("35") <= weight <= Decimal("200"):
        result.update(status="not_eligible", issues=["measurements_outside_product_range"])
        return result
    maintenance, bmi = _estimates(age, height, weight, inputs)
    offset = Decimal({"fat_loss": "-10", "muscle_gain": "5", "wellbeing": "0"}[goal])
    energy, protein = _ranges(maintenance, weight, inputs, offset)
    result["basis"] = {"age": age, "height_cm": decimal_text(height), "weight_kg": decimal_text(weight),
                       "measured_on": measurements["measured_on"], "bmi": decimal_text(_round(bmi, "0.01")),
                       "maintenance_energy_kcal": decimal_text(maintenance)}
    result["issues"].extend(_product_limits(goal, age, height, weight, bmi, maintenance, inputs, energy, protein))
    if result["issues"]:
        result["status"] = "not_eligible"
        return result
    result.update(status="ok", route="standard", energy_offset_percent=decimal_text(offset),
                  energy_kcal=energy, protein_g=protein)
    return result


@_exact
def validate_target(target: dict, member_id: str) -> dict:
    """Validate persisted estimates, member binding, product bounds, and arithmetic.

    This checks an artifact, not current health. Consumers must also reassess the
    current profile before using an otherwise valid target for a meal or review.
    """
    _json(target)
    require_keys(target, TARGET_FIELDS, TARGET_FIELDS, "target")
    if target["schema_version"] != TARGET_SCHEMA or target["policy_version"] != POLICY_VERSION:
        raise NutritionError("unsupported_target_policy", "Unsupported nutrition target version")
    if target["member_id"] != member_id:
        raise NutritionError("member_mismatch", "Nutrition target belongs to another member")
    today = _date(target["as_of"], "target.as_of")
    if type(target["revision"]) is not int or not 0 <= target["revision"] <= 100000:
        raise NutritionError("invalid_target", "Invalid target revision")
    if not isinstance(target["status"], str) or target["status"] not in {"ok", "needs_information", "not_eligible"}:
        raise NutritionError("invalid_target", "Invalid target status")
    if not isinstance(target["route"], str) or target["route"] not in {"standard", "pending", "professional", "support_only"}:
        raise NutritionError("invalid_target", "Invalid target route")
    if target["goal"] is not None and (not isinstance(target["goal"], str) or target["goal"] not in GOALS):
        raise NutritionError("invalid_target", "Invalid target goal")
    inputs = _inputs(target["inputs"])
    if inputs != target["inputs"]:
        raise NutritionError("invalid_target", "Stored inputs must contain explicit unknown values")
    for key in ("missing_fields", "issues", "source_ids", "notes"):
        values = target[key]
        if not isinstance(values, list) or len(values) > 64 or any(not isinstance(v, str) or not v or len(v) > 500 for v in values):
            raise NutritionError("invalid_target", f"Invalid target.{key}")
    if target["source_ids"] != SOURCE_IDS or target["notes"] != NOTES:
        raise NutritionError("invalid_target", "Target provenance or qualification was changed")
    basis_fields = {"age", "height_cm", "weight_kg", "measured_on", "bmi", "maintenance_energy_kcal"}
    require_keys(target["basis"], set(), basis_fields, "target.basis")
    if target["basis"]:
        require_keys(target["basis"], basis_fields, basis_fields, "target.basis")
        basis = target["basis"]
        if type(basis["age"]) is not int or not 1 <= basis["age"] <= 120:
            raise NutritionError("invalid_target", "Invalid target age")
        _date(basis["measured_on"], "target.measured_on")
        for field in ("height_cm", "weight_kg", "bmi", "maintenance_energy_kcal"):
            if not isinstance(basis[field], str):
                raise NutritionError("invalid_target", f"target.basis.{field} must be a decimal string")
            number(basis[field], field, positive=True)
    if target["status"] != "ok":
        if any(target[key] is not None for key in ("energy_offset_percent", "energy_kcal", "protein_g")):
            raise NutritionError("invalid_target", "Unavailable targets cannot contain active numeric goals")
        if not target["missing_fields"] and not target["issues"]:
            raise NutritionError("invalid_target", "Unavailable target needs a reason")
        return deepcopy(target)
    require_keys(target["basis"], basis_fields, basis_fields, "target.basis")
    if target["route"] != "standard" or target["goal"] is None or target["missing_fields"] or target["issues"]:
        raise NutritionError("invalid_target", "Active target has unresolved eligibility")
    if inputs["sex_for_equation"] == "unknown" or inputs["activity"] == "unknown" or inputs["resistance_training"] is None:
        raise NutritionError("invalid_target", "Active target inputs are incomplete")
    basis = target["basis"]
    if type(basis["age"]) is not int or not 19 <= basis["age"] <= 64:
        raise NutritionError("invalid_target", "Unsupported target age")
    if _date(basis["measured_on"], "target.measured_on") > today:
        raise NutritionError("invalid_target", "Target measurements are in the future")
    height, weight = number(basis["height_cm"], positive=True), number(basis["weight_kg"], positive=True)
    maintenance, bmi = _estimates(basis["age"], height, weight, inputs)
    if basis["maintenance_energy_kcal"] != decimal_text(maintenance) or basis["bmi"] != decimal_text(_round(bmi, "0.01")):
        raise NutritionError("invalid_target", "Stored equation result differs from its inputs")
    offset = _offset(target["energy_offset_percent"])
    if target["revision"] == 0 and offset != Decimal({"fat_loss": "-10", "muscle_gain": "5", "wellbeing": "0"}[target["goal"]]):
        raise NutritionError("invalid_target", "An initial target must use its declared starting policy")
    lower, upper = {"fat_loss": (-20, 0), "muscle_gain": (0, 10), "wellbeing": (0, 0)}[target["goal"]]
    if not lower <= offset <= upper or offset % Decimal("2.5") != 0:
        raise NutritionError("invalid_target", "Energy adjustment exceeds product bounds")
    energy, protein = _ranges(maintenance, weight, inputs, offset)
    if target["energy_kcal"] != energy or target["protein_g"] != protein:
        raise NutritionError("invalid_target", "Target quantities differ from their declared policy")
    if _product_limits(target["goal"], basis["age"], height, weight, bmi, maintenance, inputs, energy, protein):
        raise NutritionError("invalid_target", "Target lies outside product eligibility")
    return deepcopy(target)


def _feedback(feedback, as_of):
    _json(feedback)
    require_keys(feedback, set(), FEEDBACK_FIELDS, "target feedback")
    result = deepcopy(feedback)
    today = _date(as_of, "as_of")
    for key in ("window_start", "window_end"):
        if key in result:
            _date(result[key], f"feedback.{key}")
    if "window_end" in result and _date(result["window_end"], "window_end") > today:
        raise NutritionError("invalid_date_range", "Observation window cannot end in the future")
    if {"window_start", "window_end"} <= result.keys() and result["window_start"] > result["window_end"]:
        raise NutritionError("invalid_date_range", "Observation window is reversed")
    for key in HEALTH_FLAGS | {"comparable_conditions"}:
        if key in result and result[key] is not None and type(result[key]) is not bool:
            raise NutritionError("invalid_input", f"feedback.{key} must be boolean or null")
    for key, choices in (("energy", {"normal", "low", "unknown"}), ("hunger", {"comfortable", "hungry", "unknown"})):
        if key in result and (not isinstance(result[key], str) or result[key] not in choices):
            raise NutritionError("invalid_input", f"Unsupported feedback.{key}")
    days = result.get("adherent_days")
    if days is not None and (type(days) is not int or not 0 <= days <= 14):
        raise NutritionError("invalid_input", "adherent_days must be an integer from 0 through 14")
    records = result.get("weigh_ins", [])
    if not isinstance(records, list) or len(records) > 14:
        raise NutritionError("invalid_input", "weigh_ins must contain at most 14 daily records")
    seen = set()
    for record in records:
        require_keys(record, {"date", "weight_kg"}, {"date", "weight_kg"}, "weigh-in")
        recorded = _date(record["date"], "weigh-in.date")
        if recorded > today or record["date"] in seen:
            raise NutritionError("invalid_weigh_ins", "Weight dates must be distinct and not in the future")
        if not isinstance(record["weight_kg"], str):
            raise NutritionError("invalid_number", "Weight must be a decimal string")
        if not 20 <= number(record["weight_kg"], positive=True) <= 300:
            raise NutritionError("invalid_weigh_ins", "Weight is outside the supported input range")
        if "window_start" in result and record["date"] < result["window_start"] or "window_end" in result and record["date"] > result["window_end"]:
            raise NutritionError("invalid_weigh_ins", "Weight date lies outside the observation window")
        seen.add(record["date"])
    return result


@_exact
def review_targets(profile: dict, current_target: dict, feedback: dict, as_of: str) -> dict:
    """Review comparable multi-day observations; never compensate for missed meals."""
    from .workflow import validate_profile
    profile = validate_profile(profile)
    current = validate_target(current_target, profile["id"])
    today = _date(as_of, "as_of")
    if _date(current["as_of"], "target.as_of") > today:
        raise NutritionError("invalid_date_range", "Review cannot precede the target")
    feedback = _feedback(feedback, as_of)
    fresh = derive_targets(profile, current["inputs"], as_of)
    missing = [f"feedback.{field}" for field in sorted(FEEDBACK_FIELDS)
               if field not in feedback or feedback[field] is None or feedback[field] == "unknown"]
    result = {"schema_version": REVIEW_SCHEMA, "policy_version": POLICY_VERSION,
              "member_id": profile["id"], "as_of": as_of, "status": "ok", "action": "maintain",
              "target": current, "previous_target": deepcopy(current), "feedback": feedback,
              "missing_fields": missing, "issues": [], "trend": None,
              "change": {"energy_kcal": "0", "protein_g": False, "eating_window": False}}
    flags_unknown = any(feedback.get(field) is None for field in HEALTH_FLAGS)
    risk = any(feedback.get(field) is True for field in HEALTH_FLAGS) or feedback.get("energy") == "low" or feedback.get("hunger") == "hungry"
    if current["status"] != "ok" or fresh["status"] != "ok" or flags_unknown or risk:
        result.update(status="needs_information", action="pause_and_review")
        result["missing_fields"] += fresh["missing_fields"]
        result["issues"] = sorted(set(fresh["issues"] + (["health_or_tolerance_review"] if risk or flags_unknown else []) + (["active_target_required"] if current["status"] != "ok" else [])))
        return result
    if (fresh["goal"] != current["goal"] or profile["age"] != current["basis"]["age"]
            or number(profile["measurements"]["height_cm"]) != number(current["basis"]["height_cm"])
            or abs(number(profile["measurements"]["weight_kg"]) / number(current["basis"]["weight_kg"]) - 1) > Decimal("0.05")):
        result.update(status="needs_information", action="pause_and_review", issues=["profile_basis_changed_rederive"])
        return result
    if missing:
        result["status"] = "needs_information"
        return result
    start, end = _date(feedback["window_start"], "window_start"), _date(feedback["window_end"], "window_end")
    if (end - start).days != 13 or (today - end).days > 2 or start <= _date(current["as_of"], "target.as_of") or (today - _date(current["as_of"], "target.as_of")).days < 14:
        result.update(status="needs_information", issues=["fourteen_days_on_current_target_required"])
        return result
    if feedback["adherent_days"] < 12 or feedback["comparable_conditions"] is not True:
        result["issues"] = ["improve_execution_or_measurement_first"]
        return result
    weeks = [[entry for entry in feedback["weigh_ins"] if low <= _date(entry["date"], "weight date") <= high]
             for low, high in ((start, start + timedelta(days=6)), (start + timedelta(days=7), end))]
    if any(len(week) < 3 for week in weeks):
        result.update(status="needs_information", issues=["three_distinct_weigh_ins_per_week_required"])
        return result
    with exact_context():
        means = [sum(number(entry["weight_kg"]) for entry in week) / len(week) for week in weeks]
        mean_dates = [sum(Decimal((_date(entry["date"], "date") - start).days) for entry in week) / len(week) for week in weeks]
        gap = mean_dates[1] - mean_dates[0]
        weekly_change = (means[1] - means[0]) / means[0] * 100 * 7 / gap
        result["trend"] = {"previous_mean_kg": decimal_text(_round(means[0], "0.001")),
                           "recent_mean_kg": decimal_text(_round(means[1], "0.001")),
                           "mean_interval_days": decimal_text(_round(gap, "0.001")),
                           "weekly_change_percent": decimal_text(_round(weekly_change, "0.001")),
                           "counts": [len(week) for week in weeks]}
        latest_bmi = means[1] / (number(current["basis"]["height_cm"]) / 100) ** 2
        basis_weight = number(current["basis"]["weight_kg"])
        if abs(weekly_change) > 1 or latest_bmi < Decimal("18.5") or latest_bmi >= 40 or (current["goal"] == "fat_loss" and latest_bmi < 20) or abs(means[1] / basis_weight - 1) > Decimal("0.05"):
            result.update(status="needs_information", action="pause_and_review", issues=["weight_trend_requires_review"])
            return result
        direction = 0
        goal = current["goal"]
        if goal == "fat_loss":
            direction = -1 if weekly_change > Decimal("-0.25") else 1 if weekly_change < Decimal("-0.75") else 0
        elif goal == "muscle_gain":
            direction = 1 if weekly_change < Decimal("0.1") else -1 if weekly_change > Decimal("0.25") else 0
        if direction == 0:
            result["issues"] = ["maintain_current_target"]
            return result
        offset = _offset(current["energy_offset_percent"]) + Decimal("2.5") * direction
        lower, upper = {"fat_loss": (-20, 0), "muscle_gain": (0, 10)}[goal]
        if not lower <= offset <= upper:
            result["issues"] = ["adjustment_limit_reached"]
            return result
        candidate = deepcopy(current)
        candidate["energy_offset_percent"] = decimal_text(offset)
        candidate["energy_kcal"], candidate["protein_g"] = _ranges(number(current["basis"]["maintenance_energy_kcal"]), basis_weight, current["inputs"], offset)
        # A smaller observed deficit is preferable to another reduction when a bound is reached.
        if number(candidate["energy_kcal"]["min"]) <= 1200 or number(candidate["protein_g"]["max"]) * 4 > number(candidate["energy_kcal"]["min"]) * Decimal("0.35"):
            result.update(status="needs_information", action="pause_and_review", issues=["adjustment_requires_professional_support"])
            return result
        delta = number(candidate["energy_kcal"]["target"]) - number(current["energy_kcal"]["target"])
        if abs(delta) > 150:
            raise NutritionError("invalid_adjustment", "Adjustment exceeds the absolute product limit")
        candidate["as_of"] = as_of
        candidate["revision"] += 1
        validate_target(candidate, profile["id"])
        result.update(action="adjust", target=candidate, issues=["bounded_product_adjustment"])
        result["change"]["energy_kcal"] = decimal_text(delta)
        return result


@_exact
def validate_review(review: dict, member_id: str) -> dict:
    """Check a persisted review's member, structured feedback, and transition.

    Health facts outside the recorded feedback still require a fresh profile
    assessment when generating the next plan; serialization is not clearance.
    """
    _json(review)
    fields = {"schema_version", "policy_version", "member_id", "as_of", "status", "action",
              "target", "previous_target", "feedback", "missing_fields", "issues", "trend", "change"}
    require_keys(review, fields, fields, "target review")
    if review["schema_version"] != REVIEW_SCHEMA or review["policy_version"] != POLICY_VERSION:
        raise NutritionError("unsupported_target_policy", "Unsupported nutrition review version")
    if review["member_id"] != member_id:
        raise NutritionError("member_mismatch", "Nutrition review belongs to another member")
    today = _date(review["as_of"], "review.as_of")
    if not isinstance(review["status"], str) or review["status"] not in {"ok", "needs_information"}:
        raise NutritionError("invalid_target_review", "Invalid review status")
    if not isinstance(review["action"], str) or review["action"] not in {"maintain", "adjust", "pause_and_review"}:
        raise NutritionError("invalid_target_review", "Invalid review action")
    for key in ("missing_fields", "issues"):
        if not isinstance(review[key], list) or len(review[key]) > 64 or any(not isinstance(v, str) or not v or len(v) > 500 for v in review[key]):
            raise NutritionError("invalid_target_review", f"Invalid review.{key}")
    feedback = _feedback(review["feedback"], review["as_of"])
    previous = validate_target(review["previous_target"], member_id)
    target = validate_target(review["target"], member_id)
    if _date(previous["as_of"], "previous target date") > today or _date(target["as_of"], "target date") > today:
        raise NutritionError("invalid_target_review", "Review precedes its target")
    change = require_keys(review["change"], {"energy_kcal", "protein_g", "eating_window"},
                          {"energy_kcal", "protein_g", "eating_window"}, "target review change")
    if change["protein_g"] is not False or change["eating_window"] is not False:
        raise NutritionError("invalid_target_review", "Review cannot change protein or eating windows")
    delta = _offset(change["energy_kcal"])
    risk = (any(feedback.get(field) is not False for field in HEALTH_FLAGS)
            or feedback.get("energy") == "low" or feedback.get("hunger") == "hungry")
    if risk and review["action"] != "pause_and_review":
        raise NutritionError("invalid_target_review", "Risk feedback requires a paused review")
    if review["action"] == "pause_and_review" and review["status"] != "needs_information":
        raise NutritionError("invalid_target_review", "Paused review cannot claim complete status")
    trend = review["trend"]
    if trend is not None:
        fields = {"previous_mean_kg", "recent_mean_kg", "mean_interval_days", "weekly_change_percent", "counts"}
        require_keys(trend, fields, fields, "review.trend")
        if "window_start" not in feedback:
            raise NutritionError("invalid_target_review", "Trend needs an observation window")
        start = _date(feedback["window_start"], "window_start")
        weeks = [[entry for entry in feedback.get("weigh_ins", []) if low <= _date(entry["date"], "date") <= high]
                 for low, high in ((start, start + timedelta(days=6)), (start + timedelta(days=7), start + timedelta(days=13)))]
        if any(len(week) < 3 for week in weeks):
            raise NutritionError("invalid_target_review", "Trend needs at least three measurements per week")
        means = [sum(number(entry["weight_kg"]) for entry in week) / len(week) for week in weeks]
        dates = [sum(Decimal((_date(entry["date"], "date") - start).days) for entry in week) / len(week) for week in weeks]
        gap = dates[1] - dates[0]
        weekly_change = (means[1] - means[0]) / means[0] * 100 * 7 / gap
        expected = {"previous_mean_kg": decimal_text(_round(means[0], "0.001")),
                    "recent_mean_kg": decimal_text(_round(means[1], "0.001")),
                    "mean_interval_days": decimal_text(_round(gap, "0.001")),
                    "weekly_change_percent": decimal_text(_round(weekly_change, "0.001")),
                    "counts": [len(week) for week in weeks]}
        if trend != expected:
            raise NutritionError("invalid_target_review", "Trend differs from recorded observations")
        if previous["status"] == "ok":
            latest_bmi = means[1] / (number(previous["basis"]["height_cm"]) / 100) ** 2
            outside_baseline = abs(means[1] / number(previous["basis"]["weight_kg"]) - 1) > Decimal("0.05")
            outside_bmi = latest_bmi < Decimal("18.5") or latest_bmi >= 40 or (previous["goal"] == "fat_loss" and latest_bmi < 20)
        else:
            outside_baseline, outside_bmi = False, False
        if (abs(weekly_change) > 1 or outside_baseline or outside_bmi) and review["action"] != "pause_and_review":
            raise NutritionError("invalid_target_review", "Unsupported weight trend must pause adjustment")
    if review["action"] != "adjust":
        if target != previous or delta != 0:
            raise NutritionError("invalid_target_review", "Non-adjusting review must preserve its target")
        return deepcopy(review)
    if review["status"] != "ok" or review["missing_fields"] or trend is None or target["status"] != "ok" or previous["status"] != "ok":
        raise NutritionError("invalid_target_review", "An adjustment needs complete eligible targets and evidence")
    if any(field not in feedback or feedback[field] is None or feedback[field] == "unknown" for field in FEEDBACK_FIELDS):
        raise NutritionError("invalid_target_review", "Adjustment feedback is incomplete")
    start, end = _date(feedback["window_start"], "window_start"), _date(feedback["window_end"], "window_end")
    if ((end - start).days != 13 or (today - end).days > 2 or start <= _date(previous["as_of"], "target.as_of")
            or (today - _date(previous["as_of"], "target.as_of")).days < 14
            or feedback["adherent_days"] < 12 or feedback["comparable_conditions"] is not True):
        raise NutritionError("invalid_target_review", "Adjustment lacks a complete comparable current-target window")
    immutable = TARGET_FIELDS - {"energy_offset_percent", "energy_kcal", "revision", "as_of"}
    if any(target[key] != previous[key] for key in immutable) or target["revision"] != previous["revision"] + 1 or target["as_of"] != review["as_of"]:
        raise NutritionError("invalid_target_review", "Adjustment changed an unrelated target field")
    shift = _offset(target["energy_offset_percent"]) - _offset(previous["energy_offset_percent"])
    goal = previous["goal"]
    direction = (-1 if weekly_change > Decimal("-0.25") else 1 if weekly_change < Decimal("-0.75") else 0) if goal == "fat_loss" else (1 if weekly_change < Decimal("0.1") else -1 if weekly_change > Decimal("0.25") else 0) if goal == "muscle_gain" else 0
    if shift != Decimal("2.5") * direction or direction == 0 or abs(delta) > 150 or delta != number(target["energy_kcal"]["target"]) - number(previous["energy_kcal"]["target"]):
        raise NutritionError("invalid_target_review", "Energy change differs from the bounded trend rule")
    return deepcopy(review)
