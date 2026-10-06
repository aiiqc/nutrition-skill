"""One offline JSON request/result; persistence only through explicit record operations."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .common import NutritionError, RULE_VERSION, require_keys

MAX_INPUT_BYTES = 1_048_576


def _reject_float(value: str):
    raise NutritionError("invalid_number", "Use decimal strings, not JSON floating point numbers")


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise NutritionError("duplicate_key", "JSON objects must not contain duplicate keys")
        result[key] = value
    return result


def read_request(stream) -> dict:
    raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise NutritionError("input_too_large", "JSON input exceeds 1 MiB")
    try:
        return json.loads(raw, parse_float=_reject_float,
                          parse_constant=_reject_float, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, NutritionError):
            raise
        raise NutritionError("invalid_json", "Input must be one UTF-8 JSON document") from None


def dispatch(request: dict) -> dict:
    from .catalog import load_catalog
    from .nutrition import calculate, check_constraints
    from .plans import (check_day_plan, record_actual, replace_meal, restore_plan,
                        revalidate_plan, summarize_actuals)

    m3_schemas = {
        "assess_profile": ({"profile", "as_of"}, {"profile", "as_of"}),
        "next_meal": ({"profile", "as_of"}, {"profile", "as_of", "meal_id", "excluded_ids"}),
        "weekly_review": ({"profile", "feedback", "as_of"}, {"profile", "feedback", "as_of"}),
        "record_note": ({"document", "note"}, {"document", "note"}),
        "aggregate_shopping": ({"member_meals"}, {"member_meals"}),
        "save_record": ({"data_dir", "member_id", "document", "expected_revision", "consent"},
                        {"data_dir", "member_id", "document", "expected_revision", "consent", "expected_record_id"}),
        "load_record": ({"data_dir", "member_id"}, {"data_dir", "member_id", "version"}),
        "export_record": ({"data_dir", "member_id"}, {"data_dir", "member_id"}),
        "delete_record": ({"data_dir", "member_id", "expected_revision", "confirmed", "expected_record_id"},
                          {"data_dir", "member_id", "expected_revision", "confirmed", "expected_record_id"}),
    }
    allowed = {"operation", "items", "constraints", "state", "meal_id", "actual", "previous_meals", "coverage"}
    for _, fields in m3_schemas.values():
        allowed.update(fields)
    require_keys(request, {"operation"}, allowed, "request")
    operation = request["operation"]
    if not isinstance(operation, str):
        raise NutritionError("invalid_operation", "operation must be a string")
    schemas = {
        "describe": (set(), set()),
        "calculate": ({"items"}, {"items"}),
        "check_constraints": ({"items", "constraints"}, {"items", "constraints"}),
        "replace_meal": ({"state", "meal_id", "items", "constraints"}, {"state", "meal_id", "items", "constraints"}),
        "record_actual": ({"state", "meal_id", "actual"}, {"state", "meal_id", "actual"}),
        "summarize_actuals": ({"state"}, {"state"}),
        "revalidate_plan": ({"state", "constraints"}, {"state", "constraints"}),
        "check_day_plan": ({"state", "constraints", "coverage"}, {"state", "constraints", "coverage"}),
        "restore_plan": ({"state", "previous_meals", "constraints"}, {"state", "previous_meals", "constraints"}),
    }
    if operation in m3_schemas:
        required, allowed = m3_schemas[operation]
        require_keys(request, required | {"operation"}, allowed | {"operation"}, "request")
        if operation in {"assess_profile", "next_meal", "weekly_review"}:
            from .workflow import assess_profile, next_meal, weekly_review
            if operation == "assess_profile":
                return assess_profile(request["profile"], request["as_of"])
            if operation == "next_meal":
                return next_meal(request["profile"], request["as_of"],
                                 request.get("meal_id", "lunch"), request.get("excluded_ids"))
            return weekly_review(request["profile"], request["feedback"], request["as_of"])
        if operation == "record_note":
            from .journal import record_note
            return record_note(request["document"], request["note"])
        if operation == "aggregate_shopping":
            from .shopping import aggregate_shopping
            return aggregate_shopping(request["member_meals"], load_catalog())
        from .storage import save_record, load_record, export_record, delete_record
        if operation == "save_record":
            return save_record(request["data_dir"], request["member_id"], request["document"],
                               request["expected_revision"], request["consent"], request.get("expected_record_id"))
        if operation == "load_record":
            return load_record(request["data_dir"], request["member_id"], request.get("version"))
        if operation == "export_record":
            return export_record(request["data_dir"], request["member_id"])
        return delete_record(request["data_dir"], request["member_id"],
                             request["expected_revision"], request["confirmed"], request["expected_record_id"])
    unsupported = {"automatic_targets", "weekly_adjustment", "fasting", "tcm", "save_profile"}
    if operation in unsupported:
        require_keys(request, {"operation"}, {"operation"}, "request")
        return {"status": "unsupported", "operation": operation,
                "code": "capability_not_enabled", "rule_version": RULE_VERSION,
                "message": "This capability is not enabled; see the supported operations with describe"}
    if operation not in schemas:
        raise NutritionError("invalid_operation", "Unknown operation")
    required, allowed = schemas[operation]
    require_keys(request, required | {"operation"}, allowed | {"operation"}, "request")
    catalog = load_catalog()
    if operation == "describe":
        return {"status": "ok", "version": __version__, "rule_version": RULE_VERSION,
                "catalog_version": catalog["catalog_version"], "food_count": len(catalog["foods"]),
                "operations": list(schemas) + list(m3_schemas), "disabled": sorted(unsupported),
                "network_required": False, "persists_user_data": True,
                "persistence": "explicit opt-in record operations only; chosen directory outside source",
                "storage_platform": "POSIX",
                "limits_scope": "meal", "clinical_targets_generated": False,
                "operation_scopes": {"replace_meal": "meal", "revalidate_plan": "meal",
                                     "restore_plan": "meal", "check_day_plan": "day_plan",
                                     "check_constraints": "supplied_items"}}
    if operation == "calculate":
        return calculate(request["items"], catalog)
    if operation == "check_constraints":
        return check_constraints(request["items"], request["constraints"], catalog)
    if operation == "replace_meal":
        return replace_meal(request["state"], request["meal_id"], request["items"], request["constraints"], catalog)
    if operation == "record_actual":
        return record_actual(request["state"], request["meal_id"], request["actual"], catalog)
    if operation == "summarize_actuals":
        return summarize_actuals(request["state"], catalog)
    if operation == "revalidate_plan":
        return revalidate_plan(request["state"], request["constraints"], catalog)
    if operation == "check_day_plan":
        return check_day_plan(request["state"], request["constraints"], request["coverage"], catalog)
    return restore_plan(request["state"], request["previous_meals"], request["constraints"], catalog)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Read a JSON request from this file instead of stdin")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        if args.input:
            with args.input.open("rb") as stream:
                request = read_request(stream)
        else:
            request = read_request(sys.stdin.buffer)
        result = dispatch(request)
    except NutritionError as exc:
        result = exc.as_dict()
    except OSError:
        result = NutritionError("io_error", "Could not read the requested input or catalog").as_dict()
    # Raw input is never logged. Structured output is deliberately sent only to stdout.
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True, indent=2))
    return {"ok": 0, "error": 1, "needs_information": 2, "conflict": 2, "unsupported": 3}.get(result["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
