"""Scale a user-confirmed package label without pretending it is catalog data."""

from .common import NUTRIENT_UNITS, NutritionError, decimal_text, exact_context, number, require_keys
from .workflow import _json_only, _text


def calculate_label(label, amount_g, confirmed):
    """Require an explicit gram basis and preserve absent and rounded quantities."""
    _json_only(label)
    require_keys(label, {"name", "source_note", "basis_g", "nutrients"},
                 {"name", "source_note", "basis_g", "nutrients"}, "label")
    _text(label["name"], "label.name", maximum=200)
    _text(label["source_note"], "label.source_note", maximum=400)
    if type(confirmed) is not bool:
        raise NutritionError("invalid_confirmation", "confirmed must be boolean")
    basis = number(label["basis_g"], "label.basis_g", positive=True)
    grams = number(amount_g, "amount_g", positive=True)
    if basis > 10000 or grams > 10000:
        raise NutritionError("quantity_out_of_range", "Label basis and consumed amount must be at most 10000 g")
    require_keys(label["nutrients"], set(), set(NUTRIENT_UNITS) | {"energy_kj"}, "label.nutrients")
    entries = {}
    for key, value in label["nutrients"].items():
        if value is not None:
            entries[key] = number(value, "label.nutrients." + key)
    if "energy_kj" in entries and "energy_kcal" in entries:
        raise NutritionError("ambiguous_energy_basis", "Select one printed energy column, kcal or kJ")
    result = {"status": "needs_information", "schema_version": "package-label-v1",
              "name": label["name"], "source_note": label["source_note"],
              "basis_g": decimal_text(basis), "amount_g": decimal_text(grams),
              "confirmation_required": not confirmed, "totals": None,
              "intake_recorded": False, "allergens_verified": False,
              "notes": ["先核对每份、每100克或整包装对应的克数；份量标签不是推荐摄入量。",
                        "数字来自用户确认的包装标签，仍有标签舍入误差；缺项不是零。",
                        "本结果只计算这一包装食品，不写入目录或实吃；目录外整餐用record_note保留标签与份量。"]}
    if not confirmed:
        return result
    with exact_context():
        energy_method = "printed_kcal"
        if "energy_kj" in entries:
            entries["energy_kcal"] = entries.pop("energy_kj") / number("4.184")
            energy_method = "printed_kj_divided_by_4.184"
        result["totals"] = {key: {"amount": decimal_text(entries[key] * grams / basis) if key in entries else None,
                                  "unit": unit, "status": "label_rounded" if key in entries else "missing",
                                  "complete": key in entries} for key, unit in NUTRIENT_UNITS.items()}
    result.update(status="ok", energy_method=energy_method)
    return result
