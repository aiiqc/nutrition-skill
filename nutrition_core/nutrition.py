"""Exact nutrient arithmetic and checks of explicitly supplied constraints."""

from copy import deepcopy
from decimal import Decimal
from typing import Any

from .catalog import get_food, quantity_to_grams, validate_catalog
from .common import (
    ALLERGEN_IDS,
    NUTRIENT_UNITS,
    RULE_VERSION,
    NutritionError,
    decimal_text,
    exact_context,
    number,
    require_keys,
)


def _aggregate_loq_uncertainty(nutrient: dict) -> bool:
    """Keep source aggregates numeric while preserving their LOQ caveat."""
    evidence = nutrient.get("evidence", {})
    if evidence.get("scope") != "aggregate":
        return False
    if evidence.get("loq") is not None and number(evidence["loq"]) > 0:
        return True
    return any(
        sample.get("status") == "below_loq"
        for sample in evidence.get("sub_samples", [])
    )


def _calculate(items: Any, catalog: dict) -> tuple[dict, dict, set, list]:
    if not isinstance(items, list):
        raise NutritionError("invalid_input", "items must be an array")
    if len(items) > 1000:
        raise NutritionError("too_many_items", "items must contain at most 1000 entries")
    validate_catalog(catalog)
    known = {key: Decimal(0) for key in NUTRIENT_UNITS}
    certain = {key: Decimal(0) for key in NUTRIENT_UNITS}
    complete = {key: True for key in NUTRIENT_UNITS}
    statuses = {key: set() for key in NUTRIENT_UNITS}
    uncertain = set()
    normalized = []
    foods = []
    issues = []

    with exact_context():
        for index, item in enumerate(items):
            require_keys(item, {"food_id", "quantity"}, {"food_id", "quantity"},
                         f"items[{index}]")
            food = get_food(catalog, item["food_id"])
            grams = quantity_to_grams(food, item["quantity"])
            foods.append(food)
            normalized.append({"food_id": item["food_id"],
                               "grams": decimal_text(grams),
                               "state": food["state"],
                               "energy_method": food["nutrients"]["energy_kcal"]["method"],
                               "source": deepcopy(food["source"])})
            for key in NUTRIENT_UNITS:
                nutrient = food["nutrients"][key]
                status = nutrient["status"]
                statuses[key].add(status)
                issue_context = {"item_index": index, "food_id": item["food_id"],
                                 "nutrient": key}
                if status in {"missing", "below_loq"}:
                    complete[key] = False
                    uncertain.add(key)
                    issues.append({"code": f"nutrient_{status}", **issue_context})
                    continue
                value = number(nutrient["amount"], f"{key}.amount") * grams / 100
                known[key] += value
                aggregate_uncertain = _aggregate_loq_uncertainty(nutrient)
                if status == "reported" and not aggregate_uncertain:
                    certain[key] += value
                else:
                    uncertain.add(key)
                if status != "reported":
                    issues.append({"code": f"nutrient_{status}", **issue_context})
                if aggregate_uncertain:
                    issues.append({"code": "aggregate_loq_uncertainty",
                                   **issue_context})

        totals = {
            key: {"amount": decimal_text(known[key]) if complete[key] else None,
                  "known_amount": decimal_text(known[key]),
                  "unit": unit, "complete": complete[key],
                  "statuses": sorted(statuses[key])}
            for key, unit in NUTRIENT_UNITS.items()
        }
    calculation = {"status": "ok", "rule_version": RULE_VERSION,
                   "catalog_version": catalog["catalog_version"],
                   "items": normalized, "totals": totals, "issues": issues}
    return calculation, certain, uncertain, foods


def calculate(items: list, catalog: dict) -> dict:
    """Calculate covered amounts without replacing unknown nutrients with zero.

    ``status=ok`` means that the input was valid and arithmetic succeeded.
    Coverage is reported separately by each total's ``complete`` field.
    Source estimates and rounded label values remain estimates after summation.
    """
    return _calculate(items, catalog)[0]


def _validate_constraints(constraints: Any) -> tuple[list, list]:
    require_keys(constraints, set(), {"allergens", "limits"}, "constraints")
    allergens = constraints.get("allergens", [])
    limits = constraints.get("limits", [])
    if not isinstance(allergens, list):
        raise NutritionError("invalid_input", "constraints.allergens must be an array")
    if len(allergens) > 1000:
        raise NutritionError("too_many_constraints", "allergens must contain at most 1000 entries")
    for allergen in allergens:
        if not isinstance(allergen, str) or allergen not in ALLERGEN_IDS:
            raise NutritionError("unknown_allergen", "Unsupported allergen ID",
                                 {"allergen": allergen})
    if not isinstance(limits, list):
        raise NutritionError("invalid_input", "constraints.limits must be an array")
    if len(limits) > 1000:
        raise NutritionError("too_many_constraints", "limits must contain at most 1000 entries")
    normalized_limits = []
    for index, limit in enumerate(limits):
        require_keys(limit, {"nutrient", "source"},
                     {"nutrient", "min", "max", "source"},
                     f"constraints.limits[{index}]")
        key = limit["nutrient"]
        if not isinstance(key, str) or key not in NUTRIENT_UNITS:
            raise NutritionError("unknown_nutrient", "Unsupported nutrient ID",
                                 {"nutrient": key})
        if not isinstance(limit["source"], str) or not limit["source"].strip():
            raise NutritionError("invalid_constraint_source",
                                 "Every numeric constraint needs a nonempty source")
        if "min" not in limit and "max" not in limit:
            raise NutritionError("invalid_constraint", "A limit requires min or max")
        normalized = {"nutrient": key, "source": limit["source"]}
        for bound in ("min", "max"):
            if bound in limit:
                normalized[bound] = number(limit[bound], f"limits[{index}].{bound}")
        if ("min" in normalized and "max" in normalized
                and normalized["max"] < normalized["min"]):
            raise NutritionError("invalid_constraint", "max must be greater than or equal to min")
        normalized_limits.append(normalized)
    return list(dict.fromkeys(allergens)), normalized_limits


def check_constraints(items: list, constraints: dict, catalog: dict) -> dict:
    """Check external limits without inventing clinical targets or missing data."""
    allergens, limits = _validate_constraints(constraints)
    calculation, certain, uncertain, foods = _calculate(items, catalog)
    issues = []
    conflict = False
    needs_information = False

    for key in NUTRIENT_UNITS:
        lower_limits = [entry for entry in limits if entry["nutrient"] == key and "min" in entry]
        upper_limits = [entry for entry in limits if entry["nutrient"] == key and "max" in entry]
        if lower_limits and upper_limits:
            lower = max(lower_limits, key=lambda entry: entry["min"])
            upper = min(upper_limits, key=lambda entry: entry["max"])
            if lower["min"] > upper["max"]:
                conflict = True
                issues.append({"code": "constraint_bounds_conflict", "nutrient": key,
                               "unit": NUTRIENT_UNITS[key],
                               "min": decimal_text(lower["min"]),
                               "max": decimal_text(upper["max"]),
                               "min_source": lower["source"], "max_source": upper["source"]})

    for index, food in enumerate(foods):
        assessment = food["allergens"]
        for allergen in allergens:
            matching = [field for field in ("contains", "may_contain")
                        if allergen in assessment[field]]
            if matching:
                conflict = True
                issues.append({"code": "allergen_conflict", "item_index": index,
                               "food_id": food["id"], "allergen": allergen,
                               "evidence": matching, "source": assessment["source"]})
            elif assessment["assessment"] != "verified":
                needs_information = True
                issues.append({"code": "allergen_information_missing", "item_index": index,
                               "food_id": food["id"], "allergen": allergen})

    for limit in limits:
        key = limit["nutrient"]
        context = {"nutrient": key, "unit": NUTRIENT_UNITS[key],
                   "source": limit["source"]}
        above_max = "max" in limit and certain[key] > limit["max"]
        if above_max:
            conflict = True
            issues.append({"code": "nutrient_above_max", **context,
                           "reported_amount": decimal_text(certain[key]),
                           "max": decimal_text(limit["max"])})
        if key in uncertain:
            needs_information = True
            issues.append({"code": "constraint_nutrient_uncertain", **context,
                           "statuses": calculation["totals"][key]["statuses"]})
        elif "min" in limit and certain[key] < limit["min"]:
            conflict = True
            issues.append({"code": "nutrient_below_min", **context,
                           "reported_amount": decimal_text(certain[key]),
                           "min": decimal_text(limit["min"])})

    return {"status": "conflict" if conflict else
            "needs_information" if needs_information else "ok",
            "rule_version": RULE_VERSION,
            "catalog_version": catalog["catalog_version"],
            "issues": issues, "calculation": calculation}
