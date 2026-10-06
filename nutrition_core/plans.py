"""Pure meal-plan operations; a plan never counts as actual intake."""

from copy import deepcopy
from typing import Any

from .common import NutritionError, RULE_VERSION, require_keys
from .nutrition import calculate, check_constraints

MAX_COLLECTION_SIZE = 1000
MAX_REVISION = 9007199254740991
ACTUAL_STATUSES = {"confirmed", "partial", "not_eaten", "unknown"}
RECORDED_STATUSES = {"confirmed", "partial", "not_eaten"}
DAY_PLAN_VERSION = "m5-2026-10-06.1"


def _object(value: Any, required: set[str], allowed: set[str], label: str) -> dict:
    if isinstance(value, dict) and any(not isinstance(key, str) for key in value):
        raise NutritionError("invalid_fields", f"{label} keys must be strings")
    return require_keys(value, required, allowed, label)


def _meal_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_COLLECTION_SIZE:
        raise NutritionError("invalid_meal_id", "meal_id must be a nonempty bounded string")
    return value


def _items(items: Any, catalog: dict, label: str, *, nonempty: bool = False) -> list:
    if not isinstance(items, list) or len(items) > MAX_COLLECTION_SIZE:
        raise NutritionError("invalid_items", f"{label} must be a list of at most 1000 items")
    if nonempty and not items:
        raise NutritionError("invalid_items", f"{label} must contain actual food quantities")
    calculate(items, catalog)
    return items


def _meals(meals: Any, catalog: dict) -> dict[str, dict]:
    if not isinstance(meals, list) or len(meals) > MAX_COLLECTION_SIZE:
        raise NutritionError("invalid_meals", "meals must be a list of at most 1000 meals")
    by_id = {}
    item_count = 0
    for meal in meals:
        _object(meal, {"id", "locked", "items"}, {"id", "locked", "items"}, "meal")
        meal_id = _meal_id(meal["id"])
        if meal_id in by_id:
            raise NutritionError("duplicate_meal_id", "Meal IDs must be unique", {"meal_id": meal_id})
        if not isinstance(meal["locked"], bool):
            raise NutritionError("invalid_locked", "meal.locked must be a boolean")
        _items(meal["items"], catalog, "meal.items")
        item_count += len(meal["items"])
        if item_count > MAX_COLLECTION_SIZE:
            raise NutritionError("too_many_items", "A plan may contain at most 1000 food items")
        by_id[meal_id] = meal
    return by_id


def _actual(actual: Any, catalog: dict) -> dict:
    _object(actual, {"status"}, {"status", "items"}, "actual")
    status = actual["status"]
    if not isinstance(status, str) or status not in ACTUAL_STATUSES:
        raise NutritionError("invalid_actual_status", "Unknown actual-intake status")
    items = actual.get("items", [])
    _items(items, catalog, "actual.items", nonempty=status in {"confirmed", "partial"})
    if status in {"not_eaten", "unknown"} and items:
        raise NutritionError("invalid_actual_items", f"{status} may not contain food items")
    return actual


def _state(state: Any, catalog: dict) -> dict[str, dict]:
    _object(state, {"revision", "meals", "actuals"}, {"revision", "meals", "actuals"}, "state")
    revision = state["revision"]
    if type(revision) is not int or not 0 <= revision <= MAX_REVISION:
        raise NutritionError("invalid_revision", "revision must be an integer from 0 through 9007199254740991")
    by_id = _meals(state["meals"], catalog)
    actuals = state["actuals"]
    if not isinstance(actuals, dict) or len(actuals) > MAX_COLLECTION_SIZE:
        raise NutritionError("invalid_actuals", "actuals must be an object with at most 1000 entries")
    item_count = 0
    for meal_id, actual in actuals.items():
        _meal_id(meal_id)
        if meal_id not in by_id:
            raise NutritionError("orphan_actual", "Actual intake must refer to an existing meal", {"meal_id": meal_id})
        _actual(actual, catalog)
        item_count += len(actual.get("items", []))
        if item_count > MAX_COLLECTION_SIZE:
            raise NutritionError("too_many_items", "Actual intake may contain at most 1000 food items")
    return by_id


def _existing_meal(meal_id: Any, by_id: dict[str, dict]) -> dict:
    _meal_id(meal_id)
    if meal_id not in by_id:
        raise NutritionError("unknown_meal", "The requested meal does not exist", {"meal_id": meal_id})
    return by_id[meal_id]


def _result(state: dict, status: str, issues: list, **extra: Any) -> dict:
    return {"status": status, "state": deepcopy(state), "issues": deepcopy(issues),
            "rule_version": RULE_VERSION, **deepcopy(extra)}


def _next_state(state: dict) -> dict:
    if state["revision"] == MAX_REVISION:
        raise NutritionError("revision_overflow", "The next revision exceeds the supported range")
    updated = deepcopy(state)
    updated["revision"] += 1
    return updated


def _meal_check(meal: dict, constraints: dict, catalog: dict) -> dict:
    result = check_constraints(meal["items"], constraints, catalog)
    return {**result, "meal_id": meal["id"], "scope": "meal"}


def _checks(meals: list, constraints: dict, catalog: dict) -> tuple[str, list, list]:
    if not meals:
        # Validate the constraints even when there is no meal to assess.
        check_constraints([], constraints, catalog)
    checks = [_meal_check(meal, constraints, catalog) for meal in meals]
    statuses = {check["status"] for check in checks}
    status = "conflict" if "conflict" in statuses else "needs_information" if "needs_information" in statuses else "ok"
    issues = [{**issue, "meal_id": check["meal_id"], "scope": "meal"}
              for check in checks for issue in check["issues"]]
    return status, checks, issues


def replace_meal(state: dict, meal_id: str, items: list, constraints: dict, catalog: dict) -> dict:
    """Replace one unlocked, unrecorded meal after its current constraints pass."""
    by_id = _state(state, catalog)
    meal = _existing_meal(meal_id, by_id)
    _items(items, catalog, "replacement.items")
    if sum(len(entry["items"]) for entry in state["meals"]) - len(meal["items"]) + len(items) > MAX_COLLECTION_SIZE:
        raise NutritionError("too_many_items", "A plan may contain at most 1000 food items")
    candidate = {**meal, "items": items}
    check = _meal_check(candidate, constraints, catalog)
    if meal["locked"]:
        return _result(state, "conflict", [{"code": "meal_locked", "meal_id": meal_id,
                        "message": "The requested meal is locked", "scope": "meal"}], scope="meal")
    if state["actuals"].get(meal_id, {}).get("status") in RECORDED_STATUSES:
        return _result(state, "conflict", [{"code": "meal_already_recorded", "meal_id": meal_id,
                        "message": "A recorded meal cannot be replaced", "scope": "meal"}], scope="meal")
    if check["status"] != "ok":
        return _result(state, check["status"], check["issues"], checks=[check], scope="meal")
    updated = _next_state(state)
    for entry in updated["meals"]:
        if entry["id"] == meal_id:
            entry["items"] = deepcopy(items)
    return _result(updated, "ok", check["issues"], checks=[check], scope="meal")


def record_actual(state: dict, meal_id: str, actual: dict, catalog: dict) -> dict:
    """Record or correct actual intake without changing the planned foods."""
    by_id = _state(state, catalog)
    _existing_meal(meal_id, by_id)
    _actual(actual, catalog)
    count = sum(len(value.get("items", [])) for key, value in state["actuals"].items() if key != meal_id)
    if count + len(actual.get("items", [])) > MAX_COLLECTION_SIZE:
        raise NutritionError("too_many_items", "Actual intake may contain at most 1000 food items")
    updated = _next_state(state)
    updated["actuals"][meal_id] = deepcopy(actual)
    return _result(updated, "ok", [], meal_id=meal_id)


def summarize_actuals(state: dict, catalog: dict) -> dict:
    """Sum actual quantities, exposing missing meals separately from nutrients."""
    _state(state, catalog)
    items, unknown, recorded, not_eaten = [], [], [], []
    for meal in state["meals"]:
        meal_id = meal["id"]
        actual = state["actuals"].get(meal_id, {"status": "unknown"})
        if actual["status"] == "unknown":
            unknown.append(meal_id)
        else:
            recorded.append(meal_id)
            if actual["status"] == "not_eaten":
                not_eaten.append(meal_id)
            else:
                items.extend(actual["items"])
    calculation = calculate(items, catalog)
    day_complete = bool(state["meals"]) and not unknown
    issues = list(calculation["issues"])
    if not day_complete:
        issues.append({"code": "incomplete_intake", "message": "Actual intake is not complete for the listed meals",
                       "unknown_meal_ids": unknown, "scope": "listed_meals"})
    status = calculation["status"] if day_complete else "needs_information"
    return _result(state, status, issues, calculation=calculation, unknown_meal_ids=unknown,
                   recorded_meal_ids=recorded, not_eaten_meal_ids=not_eaten,
                   day_complete=day_complete, coverage_scope="listed_meals")


def revalidate_plan(state: dict, constraints: dict, catalog: dict) -> dict:
    """Check each meal, including locked meals, against current meal limits."""
    _state(state, catalog)
    status, checks, issues = _checks(state["meals"], constraints, catalog)
    return _result(state, status, issues, checks=checks, scope="meal")


def check_day_plan(state: dict, constraints: dict, coverage: dict, catalog: dict) -> dict:
    """Check supplied daily limits against planned intake, never actual intake.

    Coverage is complete only when the caller explicitly confirms that the
    expected meal groups include the whole day, including drinks and snacks.
    An incomplete list can prove an excess or allergen conflict, but cannot
    prove that the entire day falls short of a minimum.
    """
    by_id = _state(state, catalog)
    _object(coverage, {"expected_meal_ids", "confirmed"},
            {"expected_meal_ids", "confirmed"}, "coverage")
    expected = coverage["expected_meal_ids"]
    if not isinstance(expected, list) or not 1 <= len(expected) <= MAX_COLLECTION_SIZE:
        raise NutritionError("invalid_coverage", "expected_meal_ids must contain 1 through 1000 meal IDs")
    for meal_id in expected:
        _meal_id(meal_id)
    if len(set(expected)) != len(expected):
        raise NutritionError("duplicate_meal_id", "Expected meal IDs must be unique")
    if not isinstance(coverage["confirmed"], bool):
        raise NutritionError("invalid_coverage", "coverage.confirmed must be a boolean")

    expected_set = set(expected)
    missing = [meal_id for meal_id in expected if meal_id not in by_id]
    unexpected = [meal_id for meal_id in by_id if meal_id not in expected_set]
    empty = [meal_id for meal_id, meal in by_id.items() if not meal["items"]]
    complete = coverage["confirmed"] and not missing and not unexpected and not empty
    details = {"confirmed": coverage["confirmed"], "expected_meal_ids": expected,
               "listed_meal_ids": list(by_id), "missing_meal_ids": missing,
               "unexpected_meal_ids": unexpected, "empty_meal_ids": empty}

    items = [item for meal in state["meals"] for item in meal["items"]]
    check = check_constraints(items, constraints, catalog)
    issues = check["issues"]
    deferred = []
    if not complete:
        deferred = [{**issue, "reason": "incomplete_day_coverage"}
                    for issue in issues if issue["code"] == "nutrient_below_min"]
        issues = [issue for issue in issues if issue["code"] != "nutrient_below_min"]
        issues.append({"code": "day_plan_coverage_incomplete", "scope": "day_plan",
                       "message": "Confirm all planned intake, including drinks and snacks, and provide every expected meal group",
                       **details})
        conflict_codes = {"nutrient_above_max", "allergen_conflict", "constraint_bounds_conflict"}
        check["status"] = "conflict" if any(issue["code"] in conflict_codes for issue in issues) else "needs_information"
    check = {**check, "issues": issues, "scope": "day_plan"}
    return _result(state, check["status"], issues, scope="day_plan", intake_basis="planned",
                   coverage_scope="user_declared_day", plan_complete=complete, coverage=details,
                   calculation_scope="listed_plan_meals", calculation=check["calculation"], constraints_check=check,
                   supplied_constraints=constraints, deferred_minimum_checks=deferred,
                   day_plan_version=DAY_PLAN_VERSION)


def restore_plan(state: dict, previous_meals: list, constraints: dict, catalog: dict) -> dict:
    """Restore atomically, preserving currently locked and recorded meals."""
    current = _state(state, catalog)
    previous = _meals(previous_meals, catalog)
    if current.keys() != previous.keys():
        raise NutritionError("meal_set_mismatch", "Restoration must retain the current meal IDs")
    status, checks, issues = _checks(previous_meals, constraints, catalog)
    for meal_id, meal in current.items():
        if meal["locked"] and previous[meal_id] != meal:
            status = "conflict"
            issues.append({"code": "locked_meal_changed", "meal_id": meal_id, "scope": "meal",
                           "message": "Restoration cannot change a currently locked meal's plan entry"})
    for meal_id, actual in state["actuals"].items():
        if actual["status"] in RECORDED_STATUSES and previous[meal_id] != current[meal_id]:
            status = "conflict"
            issues.append({"code": "recorded_meal_changed", "meal_id": meal_id, "scope": "meal",
                           "message": "Restoration cannot change a recorded meal's plan entry"})
    if status != "ok":
        return _result(state, status, issues, checks=checks, scope="meal")
    updated = _next_state(state)
    updated["meals"] = deepcopy(previous_meals)
    return _result(updated, "ok", issues, checks=checks, scope="meal")
