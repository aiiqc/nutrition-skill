import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nutrition_core.__main__ import dispatch
from nutrition_core.common import NutritionError

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-05"


def profile(name="office"):
    return json.loads((ROOT / "examples" / "m3" / f"{name}-profile.json").read_text())


def food(food_id, amount):
    return {"food_id": f"usda:{food_id}", "quantity": {"amount": amount, "unit": "g"}}


def note(status="partial", quantity_status="estimated"):
    return {"date": AS_OF, "meal_id": "lunch", "status": status,
            "quantity_status": quantity_status, "food_summary": "豆腐、鸡蛋、米饭",
            "quantity_note": "米饭约吃三分之二；用户估量"}


class M3IntegrationTests(unittest.TestCase):
    def test_lazy_meal_selection_and_shortage(self):
        request = json.loads((ROOT / "examples" / "m3" / "next-meal-request.json").read_text())
        result = dispatch(request)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["recommendation"]["validation"], "qualitative_only")
        excluded = result["recommendation"]["id"]
        changed = dispatch(dict(request, excluded_ids=[excluded]))
        self.assertEqual(changed["status"], "ok")
        self.assertNotEqual(changed["recommendation"]["id"], excluded)
        self.assertNotIn(excluded, [item["id"] for item in changed["alternatives"]])

    def test_qualitative_intake_is_correctable_and_does_not_fabricate_totals(self):
        document = {"schema_version": "m3-1", "profile": profile()}
        before = copy.deepcopy(document)
        result = dispatch({"operation": "record_note", "document": document, "note": note()})
        self.assertEqual(document, before)
        self.assertFalse(result["nutrition_totals_updated"])
        self.assertFalse(result["persisted"])
        corrected = note("confirmed", "unknown")
        corrected["quantity_note"] = "吃了这餐，实际份量未知"
        result = dispatch({"operation": "record_note", "document": result["document"], "note": corrected})
        self.assertEqual(len(result["document"]["journal"]), 1)
        self.assertEqual(result["document"]["journal"][0]["quantity_status"], "unknown")

    def test_quantified_and_qualitative_actuals_cannot_contradict_each_other(self):
        state = {"revision": 0, "meals": [{"id": "lunch", "locked": False, "items": [food(171477, "100")]}],
                 "actuals": {"lunch": {"status": "confirmed", "items": [food(171477, "100")]}}}
        document = {"schema_version": "m3-1", "profile": profile(), "days": {AS_OF: state}}
        with self.assertRaises(NutritionError):
            dispatch({"operation": "record_note", "document": document, "note": note()})

    def test_household_totals_preserve_individual_portions_and_raw_cooked_distinction(self):
        request = {"operation": "aggregate_shopping", "member_meals": [
            {"member_id": "person-a", "items": [food(171077, "180"), food(169757, "100")]},
            {"member_id": "person-b", "items": [food(171077, "120"), food(171477, "70")]},
        ]}
        before = copy.deepcopy(request)
        result = dispatch(request)
        self.assertEqual(request, before)
        rows = {item["food_id"]: item for item in result["items"]}
        self.assertEqual(rows["usda:171077"]["grams"], "300")
        self.assertEqual(rows["usda:171077"]["member_grams"], {"person-a": "180", "person-b": "120"})
        self.assertEqual(rows["usda:171477"]["grams"], "70")
        self.assertFalse(result["constraints_checked"])
        self.assertEqual(result["basis"], "edible_weight")
        request["member_meals"][1]["member_id"] = "person-a"
        with self.assertRaises(NutritionError):
            dispatch(request)

    def test_weekly_feedback_keeps_numeric_targets_and_protects_clinical_path(self):
        request = json.loads((ROOT / "examples" / "m3" / "weekly-review-request.json").read_text())
        result = dispatch(request)
        self.assertEqual(result["action"], "maintain_and_simplify")
        self.assertFalse(any(result["adjustments"].values()))
        document = {"schema_version": "m3-1", "profile": profile(), "reviews": [result]}
        from nutrition_core.workflow import validate_document
        self.assertEqual(validate_document(document)["reviews"], [result])
        request["profile"] = profile("family")
        request["feedback"].update(appetite_declined=True, unintentional_weight_loss=True)
        clinical = dispatch(request)
        self.assertEqual(clinical["action"], "pause_and_review")
        self.assertFalse(any(clinical["adjustments"].values()))
        meal = dispatch({"operation": "next_meal", "profile": profile("family"), "as_of": AS_OF})
        self.assertNotEqual(meal["status"], "ok")

    def test_cli_save_load_export_and_scoped_delete(self):
        with tempfile.TemporaryDirectory(prefix="nutrition-m3-cli-") as temporary:
            data_dir = str(Path(temporary).resolve())
            def call(request):
                run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "nutrition.py")],
                                     input=json.dumps(request).encode(), capture_output=True,
                                     cwd=data_dir, timeout=15)
                self.assertEqual(run.stderr, b"")
                return run.returncode, json.loads(run.stdout)
            for who in ("office", "training"):
                person = profile(who)
                code, saved = call({"operation": "save_record", "data_dir": data_dir,
                                    "member_id": person["id"], "document": {"schema_version": "m3-1", "profile": person},
                                    "expected_revision": 0, "consent": True})
                self.assertEqual((code, saved["status"], saved["revision"]), (0, "ok", 1))
            code, loaded = call({"operation": "load_record", "data_dir": data_dir, "member_id": "demo-office"})
            self.assertEqual((code, loaded["document"]["profile"]["id"]), (0, "demo-office"))
            code, exported = call({"operation": "export_record", "data_dir": data_dir, "member_id": "demo-office"})
            self.assertEqual(code, 0)
            self.assertNotIn("demo-training", json.dumps(exported))
            code, denied = call({"operation": "delete_record", "data_dir": data_dir, "member_id": "demo-office",
                                 "expected_revision": 1, "confirmed": False, "expected_record_id": loaded["record_id"]})
            self.assertEqual(code, 1)
            self.assertEqual(denied["status"], "error")
            code, deleted = call({"operation": "delete_record", "data_dir": data_dir, "member_id": "demo-office",
                                  "expected_revision": 1, "confirmed": True, "expected_record_id": loaded["record_id"]})
            self.assertEqual((code, deleted["status"]), (0, "ok"))
            self.assertTrue((Path(data_dir) / "demo-training.json").is_file())
            self.assertFalse((Path(data_dir) / "demo-office.json").exists())

    def test_generic_cli_entrypoint_works_outside_source_directory(self):
        run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "nutrition.py"),
                              "--input", str(ROOT / "examples" / "m3" / "next-meal-request.json")],
                             cwd=ROOT.parent, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        self.assertEqual(json.loads(run.stdout)["recommendation"]["validation"], "qualitative_only")
