"""Run a synthetic M2 journey in memory and emit a compact JSON trace."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nutrition_core.catalog import load_catalog
from nutrition_core.plans import (record_actual, replace_meal, revalidate_plan,
                                  summarize_actuals)


def run_demo() -> dict:
    catalog = load_catalog()
    example = Path(__file__).resolve().parents[1] / "examples" / "initial-state.json"
    state = json.loads(example.read_text(encoding="utf-8"))
    breakfast = state["meals"][0]["items"]
    state = record_actual(state, "breakfast", {"status": "confirmed", "items": breakfast}, catalog)["state"]
    replacement = [
        {"food_id": "usda:171477", "quantity": {"amount": "140", "unit": "g"}},
        {"food_id": "usda:169757", "quantity": {"amount": "200", "unit": "g"}},
    ]
    constraints = {"limits": [{"nutrient": "sodium_mg", "max": "300",
                                "source": "Synthetic QA limit only; not a clinical target"}]}
    swapped = replace_meal(state, "lunch", replacement, constraints, catalog)
    state = swapped["state"]
    locked_attempt = replace_meal(state, "dinner", replacement, constraints, catalog)
    actuals = summarize_actuals(state, catalog)
    changed_constraints = revalidate_plan(state, {"allergens": ["milk"]}, catalog)
    return {"synthetic_demo": True, "meal_replacement": swapped["status"],
            "locked_dinner_attempt": locked_attempt["status"],
            "actual_summary": actuals,
            "new_allergy_revalidation": changed_constraints["status"],
            "note": "These five-food arithmetic fixtures are not a complete diet or a clinical plan"}


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, sort_keys=True, indent=2))
