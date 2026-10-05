"""Shared errors and exact decimal input for the offline nutrition core."""

from decimal import Context, Decimal, InvalidOperation, localcontext
import re
from typing import Any

RULE_VERSION = "m2-2026-10-05.1"
ALLERGEN_IDS = frozenset({
    "milk", "egg", "fish", "crustacean_shellfish", "tree_nuts",
    "peanut", "wheat", "soy", "sesame",
})
NUTRIENT_UNITS = {
    "energy_kcal": "kcal", "protein_g": "g", "carbohydrate_g": "g",
    "fat_g": "g", "fiber_g": "g", "sodium_mg": "mg",
    "potassium_mg": "mg", "phosphorus_mg": "mg",
}


class NutritionError(ValueError):
    """An expected, serializable input or domain error."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        return {"status": "error", "code": self.code,
                "message": self.message, "details": self.details,
                "rule_version": RULE_VERSION}


def number(value: Any, field: str = "amount", *, positive: bool = False) -> Decimal:
    """Accept finite decimal strings/integers, never bools or binary floats.

    Values are bounded to 18 significant digits and 12 decimal places so
    resource use and arithmetic precision are explicit at the JSON boundary.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise NutritionError("invalid_number", f"{field} must be a decimal string or integer")
    if isinstance(value, str) and (len(value) > 64 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)):
        raise NutritionError("invalid_number", f"{field} is not a bounded decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise NutritionError("invalid_number", f"{field} is not a decimal") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise NutritionError("invalid_number", f"{field} must be finite and {'positive' if positive else 'nonnegative'}")
    if len(result.as_tuple().digits) > 18 or result.as_tuple().exponent < -12 or result.adjusted() > 12:
        raise NutritionError("number_out_of_range", f"{field} exceeds the supported decimal range")
    return result


def decimal_text(value: Decimal) -> str:
    """Canonical plain notation, without context-dependent normalization."""
    if not value.is_finite():
        raise NutritionError("invalid_number", "A non-finite result cannot be serialized")
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def require_keys(obj: Any, required: set[str], allowed: set[str], label: str) -> dict:
    if not isinstance(obj, dict):
        raise NutritionError("invalid_input", f"{label} must be an object")
    if not all(isinstance(key, str) for key in obj):
        raise NutritionError("invalid_fields", f"{label} keys must be strings")
    missing = required - obj.keys()
    unknown = obj.keys() - allowed
    if missing or unknown:
        raise NutritionError("invalid_fields", f"Invalid fields in {label}",
                             {"missing": sorted(missing), "unknown": sorted(unknown)})
    return obj


def exact_context():
    """Use an isolated precision regardless of the caller's Decimal context."""
    return localcontext(Context(prec=80))
