"""Deterministic meal portions from named food records and explicit adult targets."""

from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

from .catalog import load_catalog
from .common import NutritionError, decimal_text, exact_context, number, require_keys
from .nutrition import calculate
from .plans import _state, _next_state, check_day_plan, RECORDED_STATUSES
from .targets import derive_targets, validate_target
from .workflow import assess_profile, validate_profile, _date, _strings, _json_only

PLAN_VERSION = "meal-planning-2026-10-06.1"
DATA = Path(__file__).with_name("data")
MEALS = {"breakfast", "lunch", "dinner", "snack"}


def _choices():
    return json.loads((DATA / "food-choices.json").read_text(encoding="utf-8"))["foods"]


def find_foods(query: str) -> dict:
    """Find candidates, never automatically replace an ambiguous description."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise NutritionError("invalid_query", "query must contain 1–200 characters")
    catalog, choices = load_catalog(), _choices()
    needle = query.strip().casefold()
    matches = []
    for food_id, meta in choices.items():
        labels = [food_id, meta["name_zh"], *meta["aliases"]]
        exact = any(needle == text.casefold() for text in labels)
        if exact or any(needle in text.casefold() for text in labels):
            food = catalog["foods"][food_id]
            matches.append({"food_id": food_id, "name": meta["name_zh"], "match": "exact" if exact else "candidate",
                            "state": food["state"], "portions": food["portions"],
                            "notes": meta["notes"], "source": food["source"]["url"]})
    matches.sort(key=lambda entry: (entry["match"] != "exact", entry["food_id"]))
    return {"status": "ok" if matches else "needs_information", "candidates": matches,
            "confirmation_required": True, "automatic_substitution": False}


def _item(food_id, grams):
    return {"food_id": food_id, "quantity": {"amount": decimal_text(grams), "unit": "g"}}


def _nutrients(items, catalog):
    totals = calculate(items, catalog)["totals"]
    fields = ("energy_kcal", "protein_g", "fat_g")
    if any(not totals[key]["complete"] for key in fields):
        raise NutritionError("incomplete_recipe_nutrients", "Portion solving requires known energy, protein and fat")
    return [number(totals[key]["amount"]) for key in fields]


def _solve(recipe, energy, protein, catalog):
    fixed = [_item(entry[0], Decimal(entry[1])) for entry in recipe["fixed"]]
    base = _nutrients(fixed, catalog)
    # 28 percent fat is a menu-composition preference, not a clinical target.
    wanted = [energy, protein, energy * Decimal("0.28") / 9]
    columns = [_nutrients([_item(entry[0], Decimal(100))], catalog) for entry in recipe["variables"]]
    matrix = [[columns[col][row] / 100 for col in range(3)] + [wanted[row] - base[row]] for row in range(3)]
    for pivot in range(3):
        candidate = next((row for row in range(pivot, 3) if matrix[row][pivot] != 0), None)
        if candidate is None:
            return None
        matrix[pivot], matrix[candidate] = matrix[candidate], matrix[pivot]
        divisor = matrix[pivot][pivot]
        matrix[pivot] = [value / divisor for value in matrix[pivot]]
        for row in range(3):
            if row != pivot:
                multiple = matrix[row][pivot]
                matrix[row] = [a - multiple * b for a, b in zip(matrix[row], matrix[pivot])]
    items = list(fixed)
    for index, (food_id, minimum, maximum) in enumerate(recipe["variables"]):
        grams = matrix[index][3]
        if not Decimal(minimum) <= grams <= Decimal(maximum):
            return None
        # Oil is rounded to 1 g; ordinary foods to 5 g. Recheck after rounding.
        step = Decimal(1 if food_id == "usda:171413" else 5)
        grams = (grams / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
        if grams:
            items.append(_item(food_id, grams))
    return items


def target_constraints(target, extra=None):
    limits = [{"nutrient": key, "min": target[key]["min"], "max": target[key]["max"],
               "source": target["policy_version"] + ":" + target["member_id"]}
              for key in ("energy_kcal", "protein_g")]
    result = {"limits": limits, "allergens": []}
    if extra is not None:
        require_keys(extra, set(), {"limits", "allergens"}, "constraints")
        if not isinstance(extra.get("limits", []), list) or not isinstance(extra.get("allergens", []), list):
            raise NutritionError("invalid_input", "Constraint limits and allergens must be arrays")
        result["limits"] += deepcopy(extra.get("limits", []))
        result["allergens"] = deepcopy(extra.get("allergens", []))
    return result


def _options(options):
    _json_only(options)
    require_keys(options, set(), {"meal_ids", "meal_shares", "excluded_food_ids", "excluded_recipe_ids",
                                 "kitchen", "max_prep_minutes", "budget", "available_food_ids", "variant",
                                 "replace_meal_id", "recipe_ids"}, "options")
    ids = options.get("meal_ids", ["breakfast", "lunch", "dinner"])
    _strings(ids, "meal_ids", maximum=4)
    if not 2 <= len(ids) <= 4 or any(entry not in MEALS for entry in ids):
        raise NutritionError("invalid_meal_ids", "Choose two through four supported meals")
    default_shares = {"breakfast": 25, "lunch": 38, "dinner": 37} if ids == ["breakfast", "lunch", "dinner"] else {meal: 1 for meal in ids}
    shares = options.get("meal_shares", default_shares)
    require_keys(shares, set(ids), set(ids), "meal_shares")
    if any(type(v) is not int or not 1 <= v <= 100 for v in shares.values()):
        raise NutritionError("invalid_shares", "Meal shares must be integers from 1 through 100")
    for field in ("excluded_food_ids", "excluded_recipe_ids", "available_food_ids"):
        if field in options:
            _strings(options[field], field, maximum=100)
    if not isinstance(options.get("kitchen", "stove"), str) or options.get("kitchen", "stove") not in {"none", "microwave", "stove"}:
        raise NutritionError("invalid_kitchen", "Use none, microwave or stove")
    if not isinstance(options.get("budget", "ordinary"), str) or options.get("budget", "ordinary") not in {"ordinary", "economy"}:
        raise NutritionError("invalid_budget", "Use ordinary or economy; no local price estimate is made")
    maximum = options.get("max_prep_minutes", 30)
    if type(maximum) is not int or not 1 <= maximum <= 120:
        raise NutritionError("invalid_prep_time", "max_prep_minutes is active time per meal, from 1 to 120")
    variant = options.get("variant", 0)
    if type(variant) is not int or not 0 <= variant <= 100:
        raise NutritionError("invalid_variant", "variant must be an integer from 0 through 100")
    if "replace_meal_id" in options and options["replace_meal_id"] not in ids:
        raise NutritionError("invalid_meal_id", "replace_meal_id must belong to meal_ids")
    recipes = options.get("recipe_ids", {})
    require_keys(recipes, set(), set(ids), "recipe_ids")
    if any(not isinstance(v, str) for v in recipes.values()):
        raise NutritionError("invalid_recipe", "Recipe choices must be recipe IDs")
    return ids, shares


def generate_day_plan(profile, target, as_of, options=None, state=None, constraints=None):
    """Create a checked plan; failures never mutate fixed meals or actual intake."""
    with exact_context():
        return _generate(profile, target, as_of, {} if options is None else options, state, constraints)


def _generate(profile, target, as_of, options, state, constraints):
    profile = validate_profile(profile)
    today = _date(as_of, "as_of")
    target = validate_target(target, profile["id"])
    ids, shares = _options(options)
    catalog, choices = load_catalog(), _choices()
    recipes = json.loads((DATA / "portion-recipes.json").read_text(encoding="utf-8"))["recipes"]
    recipe_by_id = {r["id"]: r for r in recipes}
    for field in ("excluded_food_ids", "available_food_ids"):
        if any(food_id not in catalog["foods"] for food_id in options.get(field, [])):
            raise NutritionError("unknown_food", "Food options must use known catalog IDs")
    if any(rid not in recipe_by_id for rid in options.get("excluded_recipe_ids", [])) or any(
            rid not in recipe_by_id for rid in options.get("recipe_ids", {}).values()):
        raise NutritionError("unknown_recipe", "Recipe options must use known IDs")
    if state is not None:
        by_id = _state(state, catalog)
        if set(by_id) != set(ids):
            raise NutritionError("meal_coverage_changed", "Existing meals must match meal_ids; do not discard a meal")
    else:
        by_id = {}
    result = {"schema_version": "generated-day-plan-v1", "rule_version": PLAN_VERSION,
              "member_id": profile["id"], "as_of": as_of, "status": "needs_information",
              "state": deepcopy(state), "cards": [], "issues": [], "check": None,
              "target_revision": target["revision"], "assumptions": [],
              "scope": "planned_foods_only", "clinical_validation": False}
    assessment = assess_profile(profile, as_of)
    if target["status"] != "ok" or assessment["status"] != "ok" or assessment["route"] != "standard":
        result["issues"] = ["eligible_current_profile_and_target_required"]
        result["assessment"] = assessment
        return result
    fresh = derive_targets(profile, target["inputs"], as_of)
    if (fresh["status"] != "ok" or fresh["goal"] != target["goal"] or profile["age"] != target["basis"]["age"]
            or number(profile["measurements"]["height_cm"]) != number(target["basis"]["height_cm"])
            or abs(number(profile["measurements"]["weight_kg"]) / number(target["basis"]["weight_kg"]) - 1) > Decimal("0.05")
            or today < _date(target["as_of"], "target.as_of") or (today - date.fromisoformat(target["as_of"])).days > 90):
        result["issues"] = ["target_refresh_required"]
        return result
    preferences = profile.get("preferences", {})
    scenario = preferences.get("scenario", "home")
    if scenario == "takeaway":
        from .workflow import next_meal
        result["issues"] = ["takeaway_recipe_and_portions_unknown"]
        result["qualitative_help"] = next_meal(profile, as_of, "lunch")
        result["assumptions"] = ["餐厅配方、油盐和份量未核实；外食用结构建议与粗记录，不套家常食品的精确数值。"]
        return result
    merged = target_constraints(target, constraints)
    # This validates extra constraints even when the plan is empty or infeasible.
    from .nutrition import check_constraints
    check_constraints([], merged, catalog)
    fixed = {}
    for meal_id, meal in by_id.items():
        is_fixed = (meal["locked"] or state["actuals"].get(meal_id, {}).get("status") in RECORDED_STATUSES
                    or ("replace_meal_id" in options and meal_id != options["replace_meal_id"]))
        if is_fixed:
            fixed[meal_id] = deepcopy(meal)
    if "replace_meal_id" in options and (not state or options["replace_meal_id"] in fixed):
        result.update(status="conflict", issues=["replacement_requires_unlocked_unrecorded_meal"])
        return result
    fixed_items = [item for meal in fixed.values() for item in meal["items"]]
    fixed_totals = _nutrients(fixed_items, catalog)
    energy = number(target["energy_kcal"]["target"]) - fixed_totals[0]
    protein = number(target["protein_g"]["target"]) - fixed_totals[1]
    remaining = [meal for meal in ids if meal not in fixed]
    if remaining and (energy <= 0 or protein <= 0):
        result.update(status="conflict", issues=["fixed_meals_leave_no_feasible_budget"])
        return result
    total_share = sum(shares[meal] for meal in remaining)
    excluded = set(options.get("excluded_food_ids", []))
    dislikes = [word.strip().casefold() for word in preferences.get("dislikes", [])]
    for food_id, metadata in choices.items():
        aliases = [metadata["name_zh"], *metadata["aliases"]]
        if any(word in alias.casefold() for word in dislikes for alias in aliases):
            excluded.add(food_id)
    cuisine = preferences.get("cuisine", "mixed")
    kitchen = "none" if scenario == "no_cook" else options.get("kitchen", "stove")
    selected = dict(fixed)
    cards = []
    used = set()
    for meal_id in remaining:
        candidates = []
        for recipe in recipes:
            food_ids = {entry[0] for entry in recipe["fixed"] + recipe["variables"]}
            if meal_id not in recipe["meals"] or excluded & food_ids:
                continue
            if recipe["id"] in options.get("excluded_recipe_ids", []):
                continue
            if cuisine != "mixed" and cuisine not in recipe["cuisines"]:
                continue
            if kitchen not in recipe["kitchens"] or recipe["minutes"] > options.get("max_prep_minutes", 30):
                continue
            if preferences.get("effort", "lazy") == "lazy" and recipe["minutes"] > 15:
                continue
            if options.get("budget", "ordinary") == "economy" and recipe["budget"] != "economy":
                continue
            if "available_food_ids" in options and not food_ids <= set(options["available_food_ids"]):
                continue
            if meal_id in options.get("recipe_ids", {}) and options["recipe_ids"][meal_id] != recipe["id"]:
                continue
            candidates.append(recipe)
        if candidates:
            offset = (today.toordinal() + options.get("variant", 0)) % len(candidates)
            candidates = candidates[offset:] + candidates[:offset]
            candidates.sort(key=lambda recipe: (recipe["id"] in used,
                            cuisine != "mixed" and kitchen != "none" and len(recipe["cuisines"]) > 1))
        found = None
        for recipe in candidates:
            items = _solve(recipe, energy * shares[meal_id] / total_share,
                           protein * shares[meal_id] / total_share, catalog)
            if items is not None:
                found = recipe, items
                break
        if found is None:
            result.update(status="conflict", issues=["no_feasible_portions_under_current_preferences"])
            result["affected_meal"] = meal_id
            result["suggestion"] = "保留硬限制；可调整餐次分配、可用食材或准备条件后重算，不强行放大份量。"
            return result
        recipe, items = found
        used.add(recipe["id"])
        selected[meal_id] = {"id": meal_id, "locked": False, "items": items}
        cards.append({"meal_id": meal_id, "recipe_id": recipe["id"], "title": recipe["title"],
                      "active_minutes": recipe["minutes"], "preparation": recipe["preparation"],
                      "portions": [{"food_id": item["food_id"], "name": choices[item["food_id"]]["name_zh"],
                                    "grams": item["quantity"]["amount"], "state": catalog["foods"][item["food_id"]]["state"],
                                    "source_portions": catalog["foods"][item["food_id"]]["portions"]} for item in items]})
    candidate = (_next_state(state) if state is not None and remaining else deepcopy(state)) or {
        "revision": 0, "meals": [], "actuals": {}}
    candidate["meals"] = [selected[meal] for meal in ids]
    check = check_day_plan(candidate, merged, {"expected_meal_ids": ids, "confirmed": True}, catalog)
    result["check"] = check
    if check["status"] != "ok":
        result.update(status=check["status"], issues=["candidate_does_not_meet_day_constraints"])
        return result
    # Check all fixed foods too: locks do not override new ingredient exclusions.
    if any(item["food_id"] in excluded for meal in candidate["meals"] for item in meal["items"]):
        result.update(status="conflict", issues=["fixed_meal_conflicts_with_current_food_exclusions"])
        return result
    result.update(status="ok", state=candidate, cards=cards)
    result["preserved_meal_ids"] = list(fixed)
    result["assumptions"] = ["食材按所列生熟状态与可食重量称量；包装品牌和餐厅配方不自动等同。",
                             "准备时间为自有菜式的操作估计，不含预先煮饭和批量备餐；免烹饪使用可即食成品。",
                             "油已单列；未列的酱汁、盐、饮料和加餐另行记录并重查。",
                             "预算只筛选食材类别，不预测地区价格；满足能量与蛋白范围不等于全面营养认证。",
                             "本检查核对计划，历史实吃保持原值；偏离计划不触发补偿性少吃。"]
    return result
