import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from nutrition_core.__main__ import dispatch

ROOT = Path(__file__).resolve().parents[1]


def invoke(raw):
    run = subprocess.run([sys.executable, "-m", "nutrition_core"], input=raw,
                         capture_output=True, cwd=ROOT, timeout=15)
    return run.returncode, json.loads(run.stdout), run.stderr


class CommandLineTests(unittest.TestCase):
    def test_real_catalog_calculation_through_process(self):
        code, result, stderr = invoke((ROOT / "examples" / "calculate.json").read_bytes())
        self.assertEqual(code, 0)
        self.assertEqual(result["totals"]["energy_kcal"]["amount"], "216")
        self.assertEqual(result["totals"]["protein_g"]["amount"], "40.5")
        self.assertEqual(stderr, b"")

    def test_invalid_json_and_duplicate_keys(self):
        for raw in (b'{', b'{"operation":"describe","operation":"calculate"}',
                    b'{"operation":"describe","items":NaN}',
                    b'{"operation":"describe","items":0.1}', b'\xff', b'[]',
                    b'{"operation":[]}', b'{"operation":"describe","constraint":{}}'):
            with self.subTest(raw=raw):
                code, result, stderr = invoke(raw)
                self.assertEqual((code, result["status"], stderr), (1, "error", b""))

    def test_request_size_and_disabled_capability(self):
        self.assertEqual(invoke(b' ' * 1_048_577)[1]["code"], "input_too_large")
        code, result, stderr = invoke(b'{"operation":"automatic_targets"}')
        self.assertEqual((code, result["status"], stderr), (3, "unsupported", b""))

    def test_unpaired_surrogate_cannot_break_error_serialization(self):
        raw = json.dumps({"operation": "calculate", "items": [
            {"food_id": "\ud800", "quantity": {"amount": "1", "unit": "g"}}]}).encode("ascii")
        code, result, stderr = invoke(raw)
        self.assertEqual((code, result["status"], stderr), (1, "error", b""))
        self.assertEqual(result["code"], "unknown_food")

    def test_allergy_information_is_not_a_pass(self):
        code, result, stderr = invoke((ROOT / "examples" / "allergen-unknown.json").read_bytes())
        self.assertEqual((code, result["status"], stderr), (2, "needs_information", b""))

    def test_only_breakfast_eaten_swap_lunch_keep_dinner_and_actuals(self):
        initial = json.loads((ROOT / "examples" / "initial-state.json").read_text())
        initial_copy = copy.deepcopy(initial)
        recorded = dispatch({"operation": "record_actual", "state": initial,
                             "meal_id": "breakfast", "actual": {
                                 "status": "confirmed", "items": initial["meals"][0]["items"]}})
        self.assertEqual(initial, initial_copy)
        state = recorded["state"]
        old_state = copy.deepcopy(state)
        swap_items = [{"food_id": "usda:171477", "quantity": {"amount": "140", "unit": "g"}}]
        changed = dispatch({"operation": "replace_meal", "state": state, "meal_id": "lunch",
                            "items": swap_items, "constraints": {}})
        self.assertEqual(changed["status"], "ok")
        self.assertEqual(state, old_state)
        self.assertEqual(changed["state"]["actuals"], old_state["actuals"])
        self.assertEqual(changed["state"]["meals"][2], old_state["meals"][2])
        summary = dispatch({"operation": "summarize_actuals", "state": changed["state"]})
        self.assertFalse(summary["day_complete"])
        self.assertEqual(set(summary["unknown_meal_ids"]), {"lunch", "dinner"})
        self.assertEqual(summary["calculation"]["totals"]["energy_kcal"]["amount"], "95.16")
        rollback = dispatch({"operation": "restore_plan", "state": changed["state"],
                             "previous_meals": initial["meals"], "constraints": {"allergens": ["milk"]}})
        self.assertEqual(rollback["status"], "needs_information")
        self.assertEqual(rollback["state"], changed["state"])

    def test_limits_are_explicit_and_sourced(self):
        bad = json.loads((ROOT / "examples" / "check-meal.json").read_text())
        bad["constraints"]["limits"][0].pop("source")
        code, result, _ = invoke(json.dumps(bad).encode())
        self.assertEqual((code, result["status"]), (1, "error"))

    def test_day_plan_process_exit_codes_and_scopes(self):
        state = json.loads((ROOT / "examples" / "initial-state.json").read_text())
        request = {"operation": "check_day_plan", "state": state, "constraints": {},
                   "coverage": {"expected_meal_ids": [meal["id"] for meal in state["meals"]], "confirmed": True}}
        code, result, stderr = invoke(json.dumps(request).encode())
        self.assertEqual((code, result["status"], stderr), (0, "ok", b""))
        self.assertEqual(result["scope"], "day_plan")
        self.assertEqual(result["state"], state)
        request["coverage"]["confirmed"] = False
        code, result, stderr = invoke(json.dumps(request).encode())
        self.assertEqual((code, result["status"], stderr), (2, "needs_information", b""))
        request["constraints"] = {"limits": [{"nutrient": "energy_kcal", "max": "1", "source": "Synthetic limit"}]}
        code, result, stderr = invoke(json.dumps(request).encode())
        self.assertEqual((code, result["status"], stderr), (2, "conflict", b""))
        description = dispatch({"operation": "describe"})
        self.assertIn("check_day_plan", description["operations"])
        self.assertEqual(description["limits_scope"], "meal")
        self.assertEqual(description["operation_scopes"]["check_day_plan"], "day_plan")

    def test_day_plan_missing_and_invalid_fields_rejected(self):
        state = json.loads((ROOT / "examples" / "initial-state.json").read_text())
        request = {"operation": "check_day_plan", "state": state, "constraints": {},
                   "coverage": {"expected_meal_ids": ["breakfast", "lunch", "dinner"], "confirmed": True}}
        bad_requests = []
        for key in ("state", "constraints", "coverage"):
            bad = copy.deepcopy(request)
            del bad[key]
            bad_requests.append(bad)
        bad_requests.append({**request, "items": []})
        bad_requests.append({**request, "coverage": {**request["coverage"], "confirm": True}})
        bad_requests.append({**request, "coverage": {**request["coverage"], "confirmed": "true"}})
        for bad in bad_requests:
            with self.subTest(bad=bad):
                code, result, stderr = invoke(json.dumps(bad).encode())
                self.assertEqual((code, result["status"], stderr), (1, "error", b""))
