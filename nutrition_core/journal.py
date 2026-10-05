"""Store confirmed, structured meal facts without inventing nutrient values."""

from copy import deepcopy

from .workflow import validate_document


def record_note(document: dict, note: dict) -> dict:
    """Correct one dated qualitative record, leaving all quantified days intact."""
    original = validate_document(document)
    # Validate the note in isolation before inspecting its keys or replacing data.
    candidate = {"schema_version": "m3-1", "profile": original["profile"], "journal": [note]}
    checked = validate_document(candidate)["journal"][0]
    updated = deepcopy(original)
    notes = updated.setdefault("journal", [])
    key = (checked["date"], checked["meal_id"])
    replacement = [entry for entry in notes if (entry["date"], entry["meal_id"]) != key]
    replacement.append(checked)
    updated["journal"] = replacement
    updated = validate_document(updated)
    return {"status": "ok", "member_id": updated["profile"]["id"],
            "document": updated, "persisted": False,
            "nutrition_totals_updated": False,
            "issues": [{"code": "qualitative_record_not_in_nutrient_totals"}]}
