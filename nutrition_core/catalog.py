"""Validated, offline food data and explicit mass/portion conversions."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from .common import ALLERGEN_IDS, NUTRIENT_UNITS, NutritionError, exact_context, number, require_keys

_DEFAULT_PATH = Path(__file__).with_name("data") / "usda-five-foods.json"
_STATUSES = {"reported", "assumed_zero", "missing", "below_loq", "label_rounded"}
_ENERGY_METHODS = {"usda_1008", "atwater_general", "atwater_specific", "usda_1062_kj"}
_MAX_CATALOG_BYTES = 4_000_000


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NutritionError("invalid_catalog", f"{field} must be nonempty text")
    return value


def _enum(value: Any, choices: set | frozenset, field: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise NutritionError("invalid_catalog", f"Invalid {field}")


def _decimal_string(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise NutritionError("invalid_catalog", f"{field} must be a decimal string")
    return number(value, field, positive=positive)


def _validate_evidence(evidence: Any) -> None:
    allowed = {"scope", "source_nutrient_id", "source_nutrient_name", "source_amount",
               "source_unit", "derivation_code", "derivation_description", "data_points",
               "min", "max", "median", "loq", "sub_samples", "reason"}
    require_keys(evidence, {"scope"}, allowed, "nutrient.evidence")
    _enum(evidence["scope"], {"aggregate", "sub_sample", "not_reported"}, "evidence.scope")
    for key in {"source_nutrient_id", "source_nutrient_name", "source_unit",
                "derivation_code", "derivation_description", "reason"} & evidence.keys():
        _text(evidence[key], f"evidence.{key}")
    for key in {"source_amount", "min", "max", "median", "loq"} & evidence.keys():
        _decimal_string(evidence[key], f"evidence.{key}", positive=(key == "loq"))
    if "data_points" in evidence:
        points = evidence["data_points"]
        if isinstance(points, bool) or not isinstance(points, int) or points < 0:
            raise NutritionError("invalid_catalog", "data_points must be a nonnegative integer")
    if "sub_samples" in evidence:
        samples = evidence["sub_samples"]
        if not isinstance(samples, list) or evidence["scope"] != "aggregate":
            raise NutritionError("invalid_catalog", "sub_samples require aggregate scope and a list")
        seen = set()
        for sample in samples:
            require_keys(sample, {"id", "scope", "amount", "status"},
                         {"id", "scope", "amount", "status", "loq"}, "sub_sample")
            sample_id = _text(sample["id"], "sub_sample.id")
            if sample_id in seen:
                raise NutritionError("invalid_catalog", "Duplicate sub_sample id")
            seen.add(sample_id)
            _enum(sample["scope"], {"sub_sample"}, "sub_sample.scope")
            _enum(sample["status"], {"reported", "below_loq"}, "sub_sample.status")
            amount = _decimal_string(sample["amount"], "sub_sample.amount")
            if "loq" in sample:
                _decimal_string(sample["loq"], "sub_sample.loq", positive=True)
            if sample["status"] == "below_loq" and ("loq" not in sample or amount != 0):
                raise NutritionError("invalid_catalog", "Below-LOQ samples preserve source zero and a positive LOQ")


def _validate_nutrient(entry: Any, unit: str, *, energy: bool = False) -> None:
    required = {"amount", "unit", "status"} | ({"method"} if energy else set())
    require_keys(entry, required, required | {"evidence"}, "nutrient")
    if entry["unit"] != unit:
        raise NutritionError("invalid_unit", f"Nutrient unit must be {unit}")
    _enum(entry["status"], _STATUSES, "nutrient.status")
    if "evidence" in entry:
        _validate_evidence(entry["evidence"])
    if entry["status"] in {"missing", "below_loq"}:
        if entry["amount"] is not None:
            raise NutritionError("invalid_catalog", "Missing/below-LOQ values cannot have an exact amount")
        if entry["status"] == "below_loq":
            evidence = entry.get("evidence", {})
            if evidence.get("scope") != "sub_sample" or "loq" not in evidence:
                raise NutritionError("invalid_catalog", "below_loq requires a sub_sample LOQ; aggregates retain reported values")
    else:
        amount = _decimal_string(entry["amount"], "nutrient.amount")
        if entry["status"] == "assumed_zero" and amount != 0:
            raise NutritionError("invalid_catalog", "assumed_zero must have amount 0")
    if energy:
        _enum(entry["method"], _ENERGY_METHODS, "energy method")
        expected_unit = "kJ" if entry["method"] == "usda_1062_kj" else "kcal"
        if unit != expected_unit:
            raise NutritionError("invalid_unit", "Energy method and unit disagree")


def _validate_food(food: Any) -> None:
    required = {"id", "name", "state", "source", "nutrients", "portions", "allergens"}
    require_keys(food, required, required | {"energy_alternatives", "density"}, "food")
    _text(food["id"], "food.id")
    _text(food["name"], "food.name")
    _enum(food["state"], {"raw", "cooked", "processed"}, "food.state")
    fields = {"publisher", "record_id", "url", "published_date", "retrieved_date",
              "license", "response_sha256"}
    source = require_keys(food["source"], fields, fields | {"data_type"}, "food.source")
    for key, value in source.items():
        _text(value, f"source.{key}")
    try:
        for key in ("published_date", "retrieved_date"):
            if date.fromisoformat(source[key]).isoformat() != source[key]:
                raise ValueError("Not canonical ISO date")
        if source["published_date"] > source["retrieved_date"]:
            raise ValueError("Publication cannot follow retrieval")
        parsed_url = urlsplit(source["url"])
        if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password or parsed_url.query:
            raise ValueError("Not a public HTTPS source URL")
    except ValueError:
        raise NutritionError("invalid_catalog", "Source requires ISO dates and an HTTPS URL without credentials/query") from None
    if not re.fullmatch(r"[0-9a-f]{64}", source["response_sha256"]):
        raise NutritionError("invalid_catalog", "response_sha256 must be 64 lowercase hexadecimal characters")
    nutrients = require_keys(food["nutrients"], set(NUTRIENT_UNITS), set(NUTRIENT_UNITS), "nutrients")
    for key, unit in NUTRIENT_UNITS.items():
        _validate_nutrient(nutrients[key], unit, energy=(key == "energy_kcal"))
    alternatives = food.get("energy_alternatives", [])
    if not isinstance(alternatives, list):
        raise NutritionError("invalid_catalog", "energy_alternatives must be a list")
    methods = {nutrients["energy_kcal"]["method"]}
    for entry in alternatives:
        if not isinstance(entry, dict):
            raise NutritionError("invalid_catalog", "Energy alternative must be an object")
        _enum(entry.get("unit"), {"kcal", "kJ"}, "alternative energy unit")
        _validate_nutrient(entry, entry["unit"], energy=True)
        if entry["method"] in methods:
            raise NutritionError("invalid_catalog", "Duplicate selected/alternative energy method")
        methods.add(entry["method"])
    portions = food["portions"]
    if not isinstance(portions, dict):
        raise NutritionError("invalid_catalog", "portions must be an object")
    for portion_id, portion in portions.items():
        _text(portion_id, "portion_id")
        require_keys(portion, {"grams", "label", "source"}, {"grams", "label", "source"}, "portion")
        _decimal_string(portion["grams"], "portion.grams", positive=True)
        _text(portion["label"], "portion.label")
        _text(portion["source"], "portion.source")
    allergens = require_keys(food["allergens"], {"contains", "may_contain", "assessment", "source"},
                             {"contains", "may_contain", "assessment", "source"}, "allergens")
    _enum(allergens["assessment"], {"unknown", "verified"}, "allergens.assessment")
    _text(allergens["source"], "allergens.source")
    for key in ("contains", "may_contain"):
        if not isinstance(allergens[key], list):
            raise NutritionError("invalid_catalog", f"allergens.{key} must be a list")
        seen = set()
        for allergen in allergens[key]:
            if not isinstance(allergen, str) or allergen not in ALLERGEN_IDS:
                raise NutritionError("unknown_allergen", "Unsupported allergen ID")
            if allergen in seen:
                raise NutritionError("invalid_catalog", "Duplicate allergen ID")
            seen.add(allergen)
    if "density" in food:
        density = require_keys(food["density"], {"grams_per_ml", "source"}, {"grams_per_ml", "source"}, "density")
        _decimal_string(density["grams_per_ml"], "density.grams_per_ml", positive=True)
        _text(density["source"], "density.source")


def _validate_catalog(catalog: Any) -> None:
    """Validate even untrusted in-memory catalogs; an empty catalog is valid."""
    require_keys(catalog, {"catalog_version", "foods"}, {"catalog_version", "foods"}, "catalog")
    _text(catalog["catalog_version"], "catalog_version")
    if not isinstance(catalog["foods"], dict):
        raise NutritionError("invalid_catalog", "foods must be an object keyed by food ID")
    for food_id, food in catalog["foods"].items():
        _text(food_id, "food ID")
        _validate_food(food)
        if food["id"] != food_id:
            raise NutritionError("invalid_catalog", "Food ID does not match its catalog key")


def validate_catalog(catalog: dict) -> dict:
    """Validate a catalog without mutation and return the input object."""
    _validate_catalog(catalog)
    return catalog


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise NutritionError("invalid_catalog", f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_number(value: str) -> None:
    raise NutritionError("invalid_number", "JSON decimal numbers must be encoded as strings")


def load_catalog(path: str | Path | None = None) -> dict:
    """Read a bounded UTF-8 JSON catalog from disk; never access the network."""
    try:
        with Path(path if path is not None else _DEFAULT_PATH).open("rb") as handle:
            raw = handle.read(_MAX_CATALOG_BYTES + 1)
        if len(raw) > _MAX_CATALOG_BYTES:
            raise NutritionError("invalid_catalog", "Catalog exceeds the 4 MB input bound")
        catalog = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                             parse_float=_reject_json_number, parse_constant=_reject_json_number)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, NutritionError):
            raise
        raise NutritionError("invalid_catalog", "Cannot read a valid UTF-8 JSON catalog") from None
    _validate_catalog(catalog)
    return catalog


def get_food(catalog: dict, food_id: str) -> dict:
    """Return an independent food record after validating the entire catalog."""
    _validate_catalog(catalog)
    _text(food_id, "food_id")
    if food_id not in catalog["foods"]:
        raise NutritionError("unknown_food", "Food ID is not in this catalog", {"food_id": food_id})
    return deepcopy(catalog["foods"][food_id])


def quantity_to_grams(food: dict, quantity: dict) -> Decimal:
    """Convert only explicit mass, source portions, or sourced food density."""
    _validate_food(food)
    require_keys(quantity, {"amount", "unit"}, {"amount", "unit", "portion_id"}, "quantity")
    if isinstance(quantity["amount"], bool) or not isinstance(quantity["amount"], (str, int)):
        raise NutritionError("invalid_number", "quantity.amount must be a decimal string or integer")
    amount = number(quantity["amount"], "quantity.amount", positive=True)
    unit = quantity["unit"]
    if not isinstance(unit, str) or unit not in {"g", "kg", "mg", "ml", "portion"}:
        raise NutritionError("invalid_unit", "Use g/kg/mg, a named source portion, or ml with a sourced density")
    if unit != "portion" and "portion_id" in quantity:
        raise NutritionError("invalid_fields", "portion_id is only valid for unit portion")
    with exact_context():
        if unit in {"g", "kg", "mg"}:
            return amount * {"g": Decimal(1), "kg": Decimal(1000), "mg": Decimal("0.001")}[unit]
        if unit == "ml":
            if "density" not in food:
                raise NutritionError("density_required", "This food has no sourced grams_per_ml density")
            return amount * number(food["density"]["grams_per_ml"])
        portion_id = quantity.get("portion_id")
        if not isinstance(portion_id, str) or portion_id not in food["portions"]:
            raise NutritionError("unknown_portion", "Select a portion ID from this food record")
        return amount * number(food["portions"][portion_id]["grams"])
