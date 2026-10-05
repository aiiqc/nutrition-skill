"""Aggregate explicit edible food weights while preserving member portions."""

from decimal import Decimal

from .catalog import get_food, validate_catalog
from .common import NutritionError, RULE_VERSION, decimal_text, exact_context, require_keys
from .nutrition import calculate
from .workflow import validate_profile


def aggregate_shopping(member_meals: list, catalog: dict) -> dict:
    if not isinstance(member_meals, list) or len(member_meals) > 100:
        raise NutritionError("invalid_members", "member_meals must be an array of at most 100 members")
    validate_catalog(catalog)
    seen, collected = set(), {}
    item_count = 0
    with exact_context():
        for entry in member_meals:
            require_keys(entry, {"member_id", "items"}, {"member_id", "items"}, "member_meals entry")
            member_id = validate_profile({"id": entry["member_id"]})["id"]
            if member_id in seen:
                raise NutritionError("duplicate_member", "Combine each member's items into one entry")
            seen.add(member_id)
            calculated = calculate(entry["items"], catalog)
            item_count += len(calculated["items"])
            if item_count > 1000:
                raise NutritionError("too_many_items", "Shopping input supports at most 1000 food items in total")
            for item in calculated["items"]:
                food_id = item["food_id"]
                if food_id not in collected:
                    food = get_food(catalog, food_id)
                    collected[food_id] = {"food_id": food_id, "name": food["name"],
                                          "state": food["state"], "source": food["source"],
                                          "grams": Decimal(0), "member_grams": {}}
                target = collected[food_id]
                amount = Decimal(item["grams"])
                target["grams"] += amount
                target["member_grams"][member_id] = target["member_grams"].get(member_id, Decimal(0)) + amount
        items = []
        for food_id in sorted(collected):
            item = collected[food_id]
            item["grams"] = decimal_text(item["grams"])
            item["member_grams"] = {key: decimal_text(value) for key, value in sorted(item["member_grams"].items())}
            items.append(item)
    return {"status": "ok", "rule_version": RULE_VERSION,
            "catalog_version": catalog["catalog_version"], "items": items,
            "basis": "edible_weight", "scope": "provided_items_only",
            "constraints_checked": False,
            "issues": [{"code": "purchase_weight_and_cooking_yield_not_inferred"},
                       {"code": "individual_diet_constraints_require_separate_validation"}]}
