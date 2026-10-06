"""Bounded structured profiles and qualitative, non-clinical meal workflows."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

from .catalog import load_catalog
from .common import NutritionError, number, require_keys
from .plans import revalidate_plan

WORKFLOW_VERSION = "m3-2026-10-05.2"
MEAL_IDS = frozenset({"breakfast", "lunch", "dinner", "snack"})
GOALS = frozenset({"fat_loss", "muscle_gain", "wellbeing"})
HEALTH_FIELDS = frozenset({"allergens", "conditions", "medications", "pregnancy_lactation",
                           "eating_disorder_risk", "malnutrition_risk"})
FEEDBACK_STATES = {"adherence": {"easy", "mixed", "hard", "unknown"},
                   "hunger": {"comfortable", "hungry", "unknown"},
                   "energy": {"normal", "low", "unknown"},
                   "training": {"normal", "changed", "not_training", "unknown"}}
FEEDBACK_FLAGS = frozenset({"health_changed", "appetite_declined",
                            "unintentional_weight_loss", "returning_after_gap"})
FEEDBACK_REQUIRED_FIELDS = frozenset({"days_observed", *FEEDBACK_STATES, *FEEDBACK_FLAGS})
FEEDBACK_OBSERVATION_FIELDS = frozenset({"adherent_days", "hunger_days", "hunger_times",
                                        "weigh_ins_count", "has_previous_week_baseline"})
FEEDBACK_FIELDS = FEEDBACK_REQUIRED_FIELDS | FEEDBACK_OBSERVATION_FIELDS
_TEMPLATE_PATH = Path(__file__).with_name("data") / "meal-templates.json"


def _json_only(value: Any) -> None:
    """Reject non-JSON objects, binary floats, cycles, and unbounded nesting."""
    count = 0
    active = set()

    def visit(current: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > 20 or count > 100000:
            raise NutritionError("input_capacity_exceeded", "Structured input is too large or deeply nested")
        if current is None or type(current) is bool:
            return
        if type(current) is int:
            if abs(current) > 9007199254740991:
                raise NutritionError("invalid_number", "Integer exceeds the supported range")
            return
        if type(current) is str:
            if len(current) > 4096:
                raise NutritionError("input_capacity_exceeded", "Text exceeds 4096 characters")
            return
        if type(current) not in {list, dict}:
            raise NutritionError("invalid_input", "Only JSON objects, arrays, and bounded scalar values are accepted")
        if id(current) in active:
            raise NutritionError("invalid_input", "Cyclic objects are not JSON data")
        active.add(id(current))
        if isinstance(current, dict):
            for key, child in current.items():
                if not isinstance(key, str):
                    raise NutritionError("invalid_fields", "Object keys must be strings")
                visit(key, depth + 1)
                visit(child, depth + 1)
        else:
            for child in current:
                visit(child, depth + 1)
        active.remove(id(current))

    visit(value, 0)


def _text(value: Any, field: str, *, maximum: int = 400, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise NutritionError("invalid_input", f"{field} must be bounded {'optional' if empty else 'nonempty'} text")
    return value


def _enum(value: Any, choices: set | frozenset, field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise NutritionError("invalid_input", f"Unsupported {field}")
    return value


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise NutritionError("invalid_date", f"{field} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
    except ValueError:
        raise NutritionError("invalid_date", f"{field} must use YYYY-MM-DD") from None
    return parsed


def _strings(value: Any, field: str, *, maximum: int = 64, text_maximum: int = 200) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise NutritionError("input_capacity_exceeded", f"{field} must be an array of at most {maximum} entries")
    for entry in value:
        _text(entry, field, maximum=text_maximum)
    if len(set(value)) != len(value):
        raise NutritionError("invalid_input", f"{field} contains duplicates")
    return value


def _profile_plan(plan: Any, member_id: str) -> None:
    fields = {"member_id", "source", "issued_on", "review_on", "confirmed", "meals", "substitutions"}
    require_keys(plan, fields, fields, "professional_plan")
    if plan["member_id"] != member_id:
        raise NutritionError("member_mismatch", "Professional requirements belong to a different member")
    _text(plan["source"], "professional_plan.source", maximum=400)
    issued = _date(plan["issued_on"], "professional_plan.issued_on")
    review = _date(plan["review_on"], "professional_plan.review_on")
    if review < issued:
        raise NutritionError("invalid_date_range", "review_on must not precede issued_on")
    if type(plan["confirmed"]) is not bool:
        raise NutritionError("invalid_input", "professional_plan.confirmed must be boolean")
    require_keys(plan["meals"], set(), set(MEAL_IDS), "professional_plan.meals")
    for meal_id, arrangement in plan["meals"].items():
        _text(arrangement, f"professional_plan.meals.{meal_id}", maximum=500)
    _strings(plan["substitutions"], "professional_plan.substitutions", maximum=20, text_maximum=300)


def validate_profile(profile: Any) -> dict:
    """Validate self-reported fields without interpreting missing health data as false."""
    _json_only(profile)
    fields = {"id", "age", "goals", "priority", "preferences", "measurements", "health",
              "storage", "professional_plan"}
    require_keys(profile, {"id"}, fields, "profile")
    if not isinstance(profile["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile["id"]):
        raise NutritionError("invalid_member_id", "Use a bounded lowercase member ID")
    if "age" in profile and (type(profile["age"]) is not int or not 1 <= profile["age"] <= 120):
        raise NutritionError("invalid_input", "age must be an integer from 1 through 120")
    if "goals" in profile:
        for goal in _strings(profile["goals"], "goals", maximum=3):
            _enum(goal, GOALS, "goal")
    if "priority" in profile:
        _enum(profile["priority"], GOALS, "priority")
        if profile["priority"] not in profile.get("goals", []):
            raise NutritionError("invalid_priority", "priority must be one of the selected goals")
    if "preferences" in profile:
        preferences = require_keys(profile["preferences"], set(),
                                   {"cuisine", "effort", "scenario", "dislikes"}, "preferences")
        for key, choices in {"cuisine": {"chinese", "western", "mixed"},
                             "effort": {"lazy", "standard"},
                             "scenario": {"home", "takeaway", "no_cook"}}.items():
            if key in preferences:
                _enum(preferences[key], choices, f"preferences.{key}")
        if "dislikes" in preferences:
            _strings(preferences["dislikes"], "preferences.dislikes")
    if "measurements" in profile:
        measurements = require_keys(profile["measurements"], set(),
                                    {"height_cm", "weight_kg", "measured_on"}, "measurements")
        for key in ("height_cm", "weight_kg"):
            if key in measurements:
                if not isinstance(measurements[key], str):
                    raise NutritionError("invalid_number", f"{key} must be a decimal string")
                number(measurements[key], key, positive=True)
        if "measured_on" in measurements:
            _date(measurements["measured_on"], "measurements.measured_on")
    if "health" in profile:
        health = require_keys(profile["health"], set(), set(HEALTH_FIELDS), "health")
        for field, value in health.items():
            if value is None:
                continue
            if field in {"allergens", "conditions", "medications"}:
                _strings(value, f"health.{field}")
            elif type(value) is not bool:
                raise NutritionError("invalid_input", f"health.{field} must be boolean or null")
    if "storage" in profile:
        _enum(profile["storage"], {"temporary", "local"}, "storage")
    if "professional_plan" in profile:
        _profile_plan(profile["professional_plan"], profile["id"])
    return deepcopy(profile)


def _feedback(feedback: Any, *, complete: bool = False) -> dict:
    require_keys(feedback, set(FEEDBACK_REQUIRED_FIELDS) if complete else set(),
                 set(FEEDBACK_FIELDS), "feedback")
    normalized = {"days_observed": feedback.get("days_observed")}
    days = normalized["days_observed"]
    if days is not None and (type(days) is not int or not 0 <= days <= 7):
        raise NutritionError("invalid_input", "days_observed must be an integer from 0 through 7, or null")
    for field, choices in FEEDBACK_STATES.items():
        normalized[field] = _enum(feedback.get(field, "unknown"), choices, f"feedback.{field}")
    for field in sorted(FEEDBACK_FLAGS):
        value = feedback.get(field)
        if value is not None and type(value) is not bool:
            raise NutritionError("invalid_input", f"feedback.{field} must be boolean or null")
        normalized[field] = value
    for field, maximum in (("adherent_days", 7), ("hunger_days", 7), ("weigh_ins_count", 100)):
        value = feedback.get(field)
        if value is not None and (type(value) is not int or not 0 <= value <= maximum):
            raise NutritionError("invalid_input", f"{field} must be an integer from 0 through {maximum}, or null")
        normalized[field] = value
    hunger_times = feedback.get("hunger_times")
    if hunger_times is not None:
        for hunger_time in _strings(hunger_times, "feedback.hunger_times", maximum=4):
            _enum(hunger_time, {"morning", "afternoon", "evening", "overnight"}, "feedback.hunger_times")
    normalized["hunger_times"] = deepcopy(hunger_times)
    baseline = feedback.get("has_previous_week_baseline")
    if baseline is not None and type(baseline) is not bool:
        raise NutritionError("invalid_input", "has_previous_week_baseline must be boolean or null")
    normalized["has_previous_week_baseline"] = baseline
    return normalized


def _validate_note(note: Any) -> None:
    fields = {"date", "meal_id", "status", "food_summary", "quantity_note", "quantity_status"}
    require_keys(note, fields, fields, "journal entry")
    _date(note["date"], "journal.date")
    _enum(note["meal_id"], MEAL_IDS, "journal.meal_id")
    _enum(note["status"], {"confirmed", "partial", "not_eaten", "unknown"}, "journal.status")
    _enum(note["quantity_status"], {"known", "estimated", "unknown"}, "journal.quantity_status")
    _text(note["food_summary"], "journal.food_summary", maximum=400,
          empty=note["status"] in {"not_eaten", "unknown"})
    _text(note["quantity_note"], "journal.quantity_note", maximum=200, empty=True)
    if note["status"] == "unknown" and note["quantity_status"] != "unknown":
        raise NutritionError("invalid_journal_quantity", "Unknown intake cannot have a known quantity")
    if note["status"] == "not_eaten" and note["quantity_status"] != "known":
        raise NutritionError("invalid_journal_quantity", "not_eaten explicitly records zero intake")


def _validate_review(review: Any, member_id: str) -> None:
    fields = {"schema_version", "rule_version", "member_id", "as_of", "status", "route", "action",
              "feedback", "missing_fields", "issues", "suggestions", "adjustments", "recovery_mode"}
    require_keys(review, fields, fields, "review")
    if review["schema_version"] != "m3-review-1":
        raise NutritionError("unsupported_schema", "Unsupported review schema")
    _text(review["rule_version"], "review.rule_version", maximum=64)
    if review["member_id"] != member_id:
        raise NutritionError("member_mismatch", "Review belongs to a different member")
    _date(review["as_of"], "review.as_of")
    _enum(review["status"], {"ok", "needs_information"}, "review.status")
    _enum(review["route"], {"pending", "standard", "professional", "support_only"}, "review.route")
    _enum(review["action"], {"maintain_and_simplify", "pause_and_review"}, "review.action")
    _feedback(review["feedback"], complete=True)
    _strings(review["missing_fields"], "review.missing_fields", maximum=64)
    for field, allowed, maximum in (("issues", {"code", "field", "message"}, 64),
                                     ("suggestions", {"code", "text"}, 20)):
        entries = review[field]
        if not isinstance(entries, list) or len(entries) > maximum:
            raise NutritionError("input_capacity_exceeded", f"review.{field} exceeds its capacity")
        for entry in entries:
            require_keys(entry, {"code"} | ({"text"} if field == "suggestions" else set()),
                         allowed, f"review.{field}")
            for key, value in entry.items():
                _text(value, f"review.{field}.{key}", maximum=500 if key in {"text", "message"} else 160)
    adjustments = require_keys(review["adjustments"], {"energy_kcal", "protein_g", "eating_window"},
                               {"energy_kcal", "protein_g", "eating_window"}, "review.adjustments")
    if any(value is not False for value in adjustments.values()):
        raise NutritionError("unsupported_adjustment", "M3 reviews cannot adjust clinical or quantitative targets")
    _enum(review["recovery_mode"], {"next_meal_only", "none"}, "review.recovery_mode")
    feedback = review["feedback"]
    requires_pause = (any(feedback[field] is not False for field in
                          ("health_changed", "appetite_declined", "unintentional_weight_loss"))
                      or feedback["energy"] == "low" or review["route"] == "support_only")
    if requires_pause and review["action"] != "pause_and_review":
        raise NutritionError("inconsistent_review", "Recorded risk feedback cannot claim routine optimization")
    if review["status"] == "ok" and (review["missing_fields"] or review["action"] == "pause_and_review"):
        raise NutritionError("inconsistent_review", "A pending review cannot claim complete status")
    recovery = "next_meal_only" if feedback["returning_after_gap"] is True else "none"
    if review["recovery_mode"] != recovery:
        raise NutritionError("inconsistent_review", "Recovery mode must preserve the recorded gap feedback")


def validate_document(document: Any) -> dict:
    """Validate one member's managed records, excluding unstructured chat/media."""
    _json_only(document)
    require_keys(document, {"schema_version", "profile"},
                 {"schema_version", "profile", "days", "journal", "reviews", "planning", "target_reviews", "strategy_state"}, "document")
    if document["schema_version"] != "m3-1":
        raise NutritionError("unsupported_schema", "Unsupported document schema")
    profile = validate_profile(document["profile"])
    days = document.get("days", {})
    if not isinstance(days, dict) or len(days) > 366:
        raise NutritionError("input_capacity_exceeded", "days must be an object with at most 366 dates")
    catalog = load_catalog() if days else None
    for day, state in days.items():
        _date(day, "days date")
        revalidate_plan(state, {}, catalog)
    journal = document.get("journal", [])
    if not isinstance(journal, list) or len(journal) > 1000:
        raise NutritionError("input_capacity_exceeded", "journal must contain at most 1000 entries")
    seen = set()
    for note in journal:
        _validate_note(note)
        key = (note["date"], note["meal_id"])
        if key in seen:
            raise NutritionError("duplicate_intake_record", "Only one journal entry is permitted per date and meal")
        seen.add(key)
        actual = days.get(note["date"], {}).get("actuals", {}).get(note["meal_id"], {})
        if actual.get("status") in {"confirmed", "partial", "not_eaten"}:
            raise NutritionError("duplicate_intake_record", "The same meal already has a quantitative actual-intake record")
    reviews = document.get("reviews", [])
    if not isinstance(reviews, list) or len(reviews) > 52:
        raise NutritionError("input_capacity_exceeded", "reviews must contain at most 52 entries")
    for review in reviews:
        _validate_review(review, profile["id"])
    if "planning" in document:
        from .targets import validate_target
        planning = require_keys(document["planning"], {"inputs", "target"}, {"inputs", "target", "options"}, "planning")
        target = validate_target(planning["target"], profile["id"])
        if planning["inputs"] != target["inputs"]:
            raise NutritionError("inconsistent_planning", "Saved inputs must match the target inputs")
    if "strategy_state" in document:
        state = require_keys(document["strategy_state"], set(),
                             {"fasting_stopped_for_symptoms", "fasting_preferences", "traditional_preferences"}, "strategy_state")
        if "fasting_stopped_for_symptoms" in state and type(state["fasting_stopped_for_symptoms"]) is not bool:
            raise NutritionError("invalid_strategy_state", "Fasting stop history must be explicit boolean")
        if "fasting_preferences" in state:
            from .strategies import _clock, PATTERNS
            preferences = require_keys(state["fasting_preferences"],
                                       {"opt_in", "pattern", "eating_start", "wake_time", "sleep_time", "work_pattern"},
                                       {"opt_in", "pattern", "eating_start", "wake_time", "sleep_time", "work_pattern"},
                                       "fasting_preferences")
            if type(preferences["opt_in"]) is not bool:
                raise NutritionError("invalid_strategy_state", "Stored opt-in must be boolean")
            _enum(preferences["pattern"], set(PATTERNS), "fasting pattern")
            _enum(preferences["work_pattern"], {"day", "night", "rotating"}, "work pattern")
            for key in ("eating_start", "wake_time", "sleep_time"):
                _clock(preferences[key], key)
        if "traditional_preferences" in state:
            preferences = require_keys(state["traditional_preferences"], {"opt_in", "method"},
                                       {"opt_in", "method"}, "traditional_preferences")
            if type(preferences["opt_in"]) is not bool:
                raise NutritionError("invalid_strategy_state", "Stored opt-in must be boolean")
            _enum(preferences["method"], {"porridge", "boil", "steam"}, "traditional method")
    if "planning" in document and "options" in document["planning"]:
        from .meal_planning import _options
        options = document["planning"]["options"]
        require_keys(options, set(), {"meal_ids", "meal_shares", "kitchen", "max_prep_minutes", "budget",
                                     "excluded_food_ids", "excluded_recipe_ids", "recipe_ids"}, "planning.options")
        _options(options)
        catalog = load_catalog()
        if any(food_id not in catalog["foods"] for food_id in options.get("excluded_food_ids", [])):
            raise NutritionError("unknown_food", "Saved exclusions must refer to catalog foods")
        recipe_ids = {recipe["id"] for recipe in json.loads(
            (Path(__file__).with_name("data") / "portion-recipes.json").read_text(encoding="utf-8"))["recipes"]}
        if any(rid not in recipe_ids for rid in options.get("excluded_recipe_ids", [])) or any(
                rid not in recipe_ids for rid in options.get("recipe_ids", {}).values()):
            raise NutritionError("unknown_recipe", "Saved recipe choices must refer to known recipes")
    target_reviews = document.get("target_reviews", [])
    if not isinstance(target_reviews, list) or len(target_reviews) > 52:
        raise NutritionError("input_capacity_exceeded", "target_reviews must contain at most 52 entries; archive older entries explicitly")
    if target_reviews:
        from .targets import validate_review
        for review in target_reviews:
            validate_review(review, profile["id"])
    return deepcopy(document)


def assess_profile(profile: dict, as_of: str) -> dict:
    """Route self-reported information without generating medical targets."""
    profile = validate_profile(profile)
    today = _date(as_of, "as_of")
    health = profile.get("health", {})
    missing, issues = [], []
    if "age" not in profile:
        missing.append("age")
    if not profile.get("goals"):
        missing.append("goals")
    elif len(profile["goals"]) > 1 and "priority" not in profile:
        missing.append("priority")
    for key in sorted(HEALTH_FIELDS):
        if health.get(key) is None:
            missing.append(f"health.{key}")
    measurements = profile.get("measurements", {})
    if any(key in measurements for key in ("height_cm", "weight_kg")) and "measured_on" not in measurements:
        missing.append("measurements.measured_on")
    if "measured_on" in measurements and _date(measurements["measured_on"], "measured_on") > today:
        missing.append("measurements.measured_on")
        issues.append({"code": "measurement_in_future", "field": "measurements.measured_on"})

    support = (profile.get("age", 120) < 18 or health.get("eating_disorder_risk") is True
               or health.get("malnutrition_risk") is True)
    professional = (bool(health.get("conditions")) or bool(health.get("medications"))
                    or health.get("pregnancy_lactation") is True)
    route = "support_only" if support else "professional" if professional else "pending" if missing else "standard"
    if support:
        issues.append({"code": "adult_optimization_disabled",
                       "message": "仅支持既定进餐安排与资料整理，不生成普通成人减脂或断食优化。"})
    elif professional:
        issues.append({"code": "professional_requirements_needed",
                       "message": "帮助落实已确认的专业要求，不自行制定治疗性营养目标。"})

    plan = profile.get("professional_plan")
    plan_usable = plan is not None
    if plan is not None:
        if not plan["confirmed"]:
            plan_usable = False
            missing.append("professional_plan.confirmed")
            issues.append({"code": "professional_plan_unconfirmed", "field": "professional_plan.confirmed"})
        if _date(plan["issued_on"], "issued_on") > today:
            plan_usable = False
            missing.append("professional_plan.issued_on")
            issues.append({"code": "professional_plan_not_yet_issued", "field": "professional_plan.issued_on"})
        if _date(plan["review_on"], "review_on") < today:
            plan_usable = False
            missing.append("professional_plan.review_on")
            issues.append({"code": "professional_plan_expired", "field": "professional_plan.review_on"})
        elif _date(plan["review_on"], "review_on") == today:
            issues.append({"code": "professional_plan_review_due", "field": "professional_plan.review_on"})
        if not plan["meals"]:
            plan_usable = False
            missing.append("professional_plan.meals")
    elif route in {"professional", "support_only"}:
        missing.append("professional_plan")

    if health.get("allergens"):
        missing.append("allergen_ingredient_verification")
        issues.append({"code": "allergen_verification_required", "field": "health.allergens",
                       "message": "保留全部自报过敏原；未完成配料及交叉接触核实，不给已验证安全替代。"})
    missing = list(dict.fromkeys(missing))
    questions = []
    if "age" in missing:
        questions.append({"fields": ["age"], "text": "你目前多少岁？这会决定适用的建议范围。"})
    missing_health = [field for field in missing if field.startswith("health.")]
    if missing_health:
        questions.append({"fields": missing_health,
                          "text": "请补齐仍未知的过敏、疾病、用药、孕哺及进食障碍或营养不良风险；不确定可以保留未知。"})
    for field, text in (("priority", "多个目标中，目前最优先处理哪一个？"),
                         ("goals", "目前主要想改善饮食、增肌，还是减脂？"),
                         ("professional_plan", "是否有适用于本人、仍有效且已确认的专业饮食安排？"),
                         ("allergen_ingredient_verification", "这餐能否核实全部配料及交叉接触信息？不能确认时先保留待核实。")):
        if field in missing and len(questions) < 3:
            questions.append({"fields": [field], "text": text})
    if len(questions) < 3:
        remaining = [field for field in missing
                     if not any(field in question["fields"] for question in questions)]
        if remaining:
            questions.append({"fields": remaining, "text": "请核对这些资料的日期、确认状态或适用安排。"})
    return {"status": "needs_information" if missing else "ok", "route": route,
            "member_id": profile["id"], "as_of": as_of, "rule_version": WORKFLOW_VERSION,
            "health_basis": "self_reported", "missing_fields": missing,
            "questions": questions[:3], "issues": issues, "professional_plan_usable": plan_usable,
            "clinical_targets_generated": False}


def _templates() -> dict:
    try:
        with _TEMPLATE_PATH.open("rb") as handle:
            raw = handle.read(1_000_001)
        if len(raw) > 1_000_000:
            raise NutritionError("invalid_templates", "Template data exceeds its size bound")
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise NutritionError("invalid_templates", "Cannot read project meal templates") from None
    _json_only(data)
    require_keys(data, {"schema_version", "source", "templates"},
                 {"schema_version", "source", "templates"}, "templates")
    if data["schema_version"] != "m3-templates-1":
        raise NutritionError("invalid_templates", "Unsupported meal-template schema")
    require_keys(data["source"], {"title", "url", "authorship", "scope"},
                 {"title", "url", "authorship", "scope"}, "template source")
    for value in data["source"].values():
        _text(value, "template source", maximum=500)
    if not isinstance(data["templates"], list) or len(data["templates"]) > 200:
        raise NutritionError("invalid_templates", "Invalid template collection")
    seen = set()
    fields = {"id", "title", "cuisines", "efforts", "scenarios", "meal_ids", "foods",
              "aliases", "preparation", "portion_note"}
    for entry in data["templates"]:
        require_keys(entry, fields, fields, "meal template")
        _text(entry["id"], "template.id", maximum=64)
        if entry["id"] in seen:
            raise NutritionError("invalid_templates", "Duplicate template ID")
        seen.add(entry["id"])
        for field, choices in (("cuisines", {"chinese", "western", "mixed"}),
                                ("efforts", {"lazy", "standard"}),
                                ("scenarios", {"home", "takeaway", "no_cook"}),
                                ("meal_ids", MEAL_IDS)):
            if not _strings(entry[field], f"template.{field}", maximum=4):
                raise NutritionError("invalid_templates", "Template selector arrays cannot be empty")
            for choice in entry[field]:
                _enum(choice, choices, f"template.{field}")
        if not _strings(entry["foods"], "template.foods", maximum=8):
            raise NutritionError("invalid_templates", "A meal structure needs actual food names")
        _strings(entry["aliases"], "template.aliases", maximum=40)
        for field in ("title", "preparation", "portion_note"):
            _text(entry[field], f"template.{field}", maximum=500)
    return data


def next_meal(profile: dict, as_of: str, meal_id: str = "lunch", excluded_ids: list | None = None) -> dict:
    """Suggest food structures or faithfully relay a current professional plan."""
    profile = validate_profile(profile)
    _enum(meal_id, MEAL_IDS, "meal_id")
    excluded_ids = [] if excluded_ids is None else _strings(excluded_ids, "excluded_ids", maximum=200,
                                                          text_maximum=100)
    assessment = assess_profile(profile, as_of)
    result = {"status": "needs_information", "member_id": profile["id"], "as_of": as_of,
              "meal_id": meal_id, "rule_version": WORKFLOW_VERSION,
              "route": assessment["route"], "validation": "qualitative_only",
              "recommendation": None, "alternatives": [], "assessment": assessment,
              "issues": deepcopy(assessment["issues"]), "assumptions": []}
    plan = profile.get("professional_plan")
    if plan is not None:
        if not assessment["professional_plan_usable"]:
            return result
        if meal_id not in plan["meals"]:
            result["issues"].append({"code": "professional_meal_missing", "field": meal_id})
            return result
        plan_id = f"professional:{profile['id']}:{meal_id}"
        if excluded_ids:
            result["issues"].append({"code": "professional_substitution_not_verified",
                                     "message": "替换需核对原有专业要求及配料，本轮不自行生成替代。"})
            return result
        result["recommendation"] = {
            "id": plan_id, "kind": "professional_plan_transcription", "meal_id": meal_id,
            "arrangement": plan["meals"][meal_id], "source": plan["source"],
            "issued_on": plan["issued_on"], "review_on": plan["review_on"],
            "portion_note": "仅转述当前计划已有安排和份量，不补充、推算或改变专业要求。",
            "validation": "qualitative_only", "ingredients_verified": False,
        }
        result["issues"].append({"code": "professional_plan_transcription_only",
                                 "message": "这是已确认的用户提供要求；成分与医学适用性未由本核心核验。"})
        return result
    if assessment["status"] != "ok" or assessment["route"] != "standard":
        return result

    data = _templates()
    known_ids = {entry["id"] for entry in data["templates"]}
    if any(template_id not in known_ids for template_id in excluded_ids):
        raise NutritionError("unknown_template", "excluded_ids must refer to known project templates")
    preferences = profile.get("preferences", {})
    selectors = {}
    for field, default in (("cuisine", "mixed"), ("effort", "lazy"), ("scenario", "home")):
        selectors[field] = preferences.get(field, default)
        if field not in preferences:
            result["assumptions"].append({"field": f"preferences.{field}", "value": default})
    dislikes = [value.strip().casefold() for value in preferences.get("dislikes", [])]
    candidates = []
    for entry in data["templates"]:
        if (entry["id"] in excluded_ids or meal_id not in entry["meal_ids"]
                or selectors["cuisine"] not in entry["cuisines"]
                or selectors["effort"] not in entry["efforts"]
                or selectors["scenario"] not in entry["scenarios"]):
            continue
        searchable = [value.casefold() for value in [*entry["foods"], *entry["aliases"]]]
        if any(dislike in value or value in dislike for dislike in dislikes for value in searchable):
            continue
        candidates.append({"id": entry["id"], "kind": "meal_structure", "title": entry["title"],
                           "foods": deepcopy(entry["foods"]), "preparation": entry["preparation"],
                           "portion_note": entry["portion_note"], "validation": "qualitative_only",
                           "source": deepcopy(data["source"])})
    result["selection"] = selectors
    if not candidates:
        result["issues"].append({"code": "no_matching_template",
                                 "message": "现有模板无法同时满足当前场景、偏好与排除条件；不凑数量或放宽限制。"})
        return result
    result["status"] = "ok"
    result["recommendation"] = candidates[0]
    result["alternatives"] = candidates[1:3]
    result["issues"].append({"code": "portion_confirmation_required",
                             "message": "这些是食物结构。份量沿用已确认且适用的计划，否则需补充份量安排。"})
    return result


def weekly_review(profile: dict, feedback: dict, as_of: str) -> dict:
    """Adjust convenience suggestions, never energy, protein, or fasting targets."""
    profile = validate_profile(profile)
    _json_only(feedback)
    feedback = _feedback(feedback)
    assessment = assess_profile(profile, as_of)
    missing = [f"profile.{field}" for field in assessment["missing_fields"]]
    for field, value in feedback.items():
        if field in FEEDBACK_REQUIRED_FIELDS and (value is None or value == "unknown"):
            missing.append(f"feedback.{field}")
    issues = deepcopy(assessment["issues"])
    suggestions = [{"code": "regular_meals_no_compensation",
                    "text": "保持正常进餐安排，不用补偿性禁食抵消聚餐、漏记或中断。"}]
    health_flags = ("health_changed", "appetite_declined", "unintentional_weight_loss")
    health_change = any(feedback[field] is True for field in health_flags)
    health_unknown = any(feedback[field] is None for field in health_flags)
    pause = (assessment["status"] != "ok" or assessment["route"] == "support_only"
             or health_change or health_unknown or feedback["energy"] == "low")
    route = assessment["route"]
    if health_change:
        route = "support_only" if route == "support_only" else "professional"
        for field in health_flags:
            if feedback[field] is True:
                issues.append({"code": field, "field": f"feedback.{field}"})
        suggestions.append({"code": "professional_review",
                            "text": "先暂停进一步减脂、断食或自行改目标，核对新的健康情况并寻求专业评估；不明体重下降不记为减脂成功。"})
    if health_unknown:
        issues.append({"code": "feedback_health_unknown", "field": "feedback"})
    if feedback["hunger"] == "hungry" or feedback["energy"] == "low":
        issues.append({"code": "tolerance_review_needed", "field": "feedback"})
        suggestions.append({"code": "review_tolerance",
                            "text": "核对是否漏餐及现有加餐安排，在保持既定日目标的前提下改善进餐时间和准备方式；不自动增减热量或延长空腹时间。"})
    if feedback["adherence"] in {"hard", "mixed"}:
        suggestions.append({"code": "simplify_preparation",
                            "text": "保留你愿意重复吃的固定餐，把最费事的一餐改为同场景可购买或提前准备的组合；替换仍需经过原有限制检查。"})
    elif feedback["adherence"] == "easy":
        suggestions.append({"code": "keep_working_routine", "text": "继续使用容易执行的固定餐和采购清单，避免为了变化把整周菜单全部换掉。"})
    if feedback["training"] == "changed":
        suggestions.append({"code": "review_schedule", "text": "按新的训练时间调整准备和用餐便利性，不因临时休息自动砍掉主食或改变摄入目标。"})
    if feedback["returning_after_gap"] is True:
        suggestions.append({"code": "resume_next_meal", "text": "从下一餐恢复正常安排；不补写漏掉的历史，也不通过少吃补偿。"})
    if feedback["days_observed"] is None or feedback["days_observed"] == 0:
        issues.append({"code": "no_observation_window", "field": "feedback.days_observed"})
        suggestions.append({"code": "start_brief_observation", "text": "从现在记录执行难度、食欲和精神状态，资料不足时不宣称已识别体重或营养趋势。"})
    if missing:
        suggestions.append({"code": "complete_current_feedback", "text": "补齐列出的当前缺项；未知信息保持未知，不要求补写整段历史。"})
    result = {"schema_version": "m3-review-1", "rule_version": WORKFLOW_VERSION,
              "member_id": profile["id"], "as_of": as_of,
              "status": "needs_information" if missing or pause else "ok", "route": route,
              "action": "pause_and_review" if pause else "maintain_and_simplify",
              "feedback": feedback, "missing_fields": missing, "issues": issues,
              "suggestions": suggestions,
              "adjustments": {"energy_kcal": False, "protein_g": False, "eating_window": False},
              "recovery_mode": "next_meal_only" if feedback["returning_after_gap"] is True else "none"}
    _validate_review(result, profile["id"])
    return result
