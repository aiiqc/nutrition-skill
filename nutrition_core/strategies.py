"""Optional meal timing and ordinary-food culture without clinical prescriptions."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import re

from .common import NutritionError, decimal_text, exact_context, number, require_keys
from .workflow import assess_profile, validate_profile, _json_only

STRATEGY_VERSION = "nutrition-strategies-2026-10-06.1"
FASTING_SOURCE = "https://www.hopkinsmedicine.org/health/expert-qa/intermittent-fasting-what-is-it-and-how-does-it-work"
TCM_SOURCE = "https://www.nccih.nih.gov/health/traditional-chinese-medicine-what-you-need-to-know"
PATTERNS = {"12:12": 720, "14:10": 600, "16:8": 480}
_FASTING_FIELDS = {"opt_in", "pattern", "eating_start", "eating_end", "wake_time", "sleep_time",
                   "work_pattern", "symptoms", "previously_stopped_for_symptoms", "can_meet_daily_needs"}
_FOOD_METHODS = {
    "porridge": {
        "id": "ordinary-oat-porridge", "title": "原味燕麦粥配水煮蛋",
        "foods": [{"food_id": "usda:173904", "name": "未强化干燕麦", "weight_basis": "dry_input",
                   "aliases": ["燕麦", "燕麥", "oat"]},
                  {"food_id": "usda:173424", "name": "水煮熟全蛋", "weight_basis": "cooked_edible",
                   "aliases": ["鸡蛋", "雞蛋", "蛋", "egg"]}],
        "steps": ["从既有全天餐单取出本餐的燕麦份量，按干重称量。",
                  "加饮用水煮至喜欢的软度，不把加水后的粥重当成干燕麦克数。",
                  "搭配餐单内的水煮蛋；不因改成粥而取消蛋白质食物或重复加一份主食。"],
    },
    "boil": {
        "id": "ordinary-boiled-vegetables", "title": "水煮西兰花与胡萝卜",
        "foods": [{"food_id": "usda:169967", "name": "无盐水煮沥干西兰花", "weight_basis": "cooked_drained",
                   "aliases": ["西兰花", "綠花椰菜", "broccoli"]},
                  {"food_id": "usda:170394", "name": "无盐水煮沥干胡萝卜", "weight_basis": "cooked_drained",
                   "aliases": ["胡萝卜", "紅蘿蔔", "carrot"]}],
        "steps": ["将清洗好的蔬菜分别煮熟、沥干，再按既有餐单的熟食份量称重。",
                  "若添加油、酱汁或盐，单独记录，不把它们藏进无盐蔬菜条目。",
                  "这是一道配菜，保留该餐原有主食和蛋白质食物。"],
    },
    "steam": {
        "id": "ordinary-steamed-reheat", "title": "蒸热米饭配熟胡萝卜与水煮蛋",
        "foods": [{"food_id": "usda:169757", "name": "无盐熟白米饭", "weight_basis": "cooked_input",
                   "aliases": ["米饭", "米飯", "白飯", "rice"]},
                  {"food_id": "usda:170394", "name": "无盐水煮沥干胡萝卜", "weight_basis": "cooked_input",
                   "aliases": ["胡萝卜", "紅蘿蔔", "carrot"]},
                  {"food_id": "usda:173424", "name": "水煮熟全蛋", "weight_basis": "cooked_edible",
                   "aliases": ["鸡蛋", "雞蛋", "蛋", "egg"]}],
        "steps": ["取既有餐单内、妥善保存的熟米饭与熟胡萝卜份量，分开蒸热。",
                  "水煮蛋作为配餐；不会把水煮蛋来源改称蒸蛋营养数据。",
                  "来源克数指上述食物状态；蒸热后吸水或失水不建立固定换算率。"],
    },
}


def _day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise NutritionError("invalid_date", "as_of must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise NutritionError("invalid_date", "as_of must use YYYY-MM-DD") from None


def _clock(value: str, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise NutritionError("invalid_time", f"{field} must use 24-hour HH:MM")
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _time_point(minutes: int) -> dict:
    return {"time": f"{minutes % 1440 // 60:02d}:{minutes % 60:02d}",
            "day_offset": minutes // 1440}


def _boolean(value, field):
    if value is not None and type(value) is not bool:
        raise NutritionError("invalid_input", f"{field} must be boolean or null")


def _text_list(value, field):
    if not isinstance(value, list) or len(value) > 64:
        raise NutritionError("invalid_input", f"{field} must be a bounded text array")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 200 for item in value):
        raise NutritionError("invalid_input", f"{field} requires nonempty bounded text")
    if len(set(value)) != len(value):
        raise NutritionError("invalid_input", f"{field} contains duplicates")


def _result(profile: dict, as_of: str, strategy: str, request: dict) -> dict:
    assessment = assess_profile(profile, as_of)
    return {"schema_version": "nutrition-strategy-v1", "strategy_version": STRATEGY_VERSION,
            "strategy": strategy, "member_id": profile["id"], "as_of": as_of,
            "status": "needs_information", "action": "keep_regular_meals",
            "assessment": assessment, "request": deepcopy(request), "schedule": None,
            "recommendations": [], "missing_fields": [], "issues": [],
            "changes_daily_nutrition_targets": False, "clinical_prescription": False,
            "evidence": {}, "notes": []}


def fasting_plan(profile: dict, as_of: str, request: dict) -> dict:
    """Arrange an opted-in eating window; never reduce targets or restart after symptoms."""
    profile = validate_profile(profile)
    today = _day(as_of)
    _json_only(request)
    require_keys(request, set(), _FASTING_FIELDS, "fasting request")
    for field in ("opt_in", "previously_stopped_for_symptoms", "can_meet_daily_needs"):
        _boolean(request.get(field), field)
    for field in ("eating_start", "eating_end", "wake_time", "sleep_time"):
        if request.get(field) is not None:
            _clock(request[field], field)
    if request.get("pattern") is not None and (not isinstance(request["pattern"], str) or request["pattern"] not in PATTERNS):
        raise NutritionError("invalid_pattern", "Use 12:12, 14:10 or 16:8; no prolonged fasting")
    if request.get("work_pattern") is not None and (not isinstance(request["work_pattern"], str) or request["work_pattern"] not in {"day", "night", "rotating"}):
        raise NutritionError("invalid_input", "work_pattern must be day, night or rotating")
    if request.get("symptoms") is not None:
        _text_list(request["symptoms"], "symptoms")
    result = _result(profile, as_of, "fasting", request)
    result["restart_allowed"] = False
    result["evidence"] = {"level": "optional_timing_with_mixed_outcome_evidence",
                          "source_url": FASTING_SOURCE,
                          "text": "时窗是可选进餐安排，不能保证额外减脂或治疗疾病；12/12、14/10和本产品准入界限是保守产品规则。"}
    result["notes"] = ["维持原有全天食物、能量、蛋白质与饮水安排，不再因为时窗扣一餐或扣热量。",
                       "开始前可与医疗人员讨论适用性；工作、训练或睡眠不适配时继续常规进餐。",
                       "任何新增不适都优先退出时窗；不以坚持断食为理由推迟进食或求助。"]
    if request.get("symptoms") or request.get("previously_stopped_for_symptoms") is True:
        result.update(status="stopped", action="stop_and_resume_regular_meals")
        result["issues"].append("symptoms_or_previous_symptom_stop")
        result["notes"].append("停止限制进餐时间并恢复常规进食，联系医疗人员评估不适；昏厥、意识混乱或其他严重症状应立即就医。本模块不自动重新启用。")
        return result
    if request.get("opt_in") is False:
        result.update(status="not_enabled", action="keep_regular_meals")
        return result
    missing = [f"profile.{field}" for field in result["assessment"]["missing_fields"]
               if field != "allergen_ingredient_verification"]
    for field in _FASTING_FIELDS - {"eating_end"}:
        if request.get(field) is None:
            missing.append(f"request.{field}")
    measurements = profile.get("measurements", {})
    for field in ("height_cm", "weight_kg", "measured_on"):
        if field not in measurements:
            missing.append(f"profile.measurements.{field}")
    if "measured_on" in measurements:
        measured = date.fromisoformat(measurements["measured_on"])
        if measured > today or (today - measured).days > 30:
            missing.append("profile.measurements.measured_on")
            result["issues"].append("current_measurements_needed")
    if profile.get("age") is not None and not 19 <= profile["age"] <= 64:
        result["issues"].append("outside_supported_age")
    if result["assessment"]["route"] in {"professional", "support_only"} or "professional_plan" in profile:
        result["issues"].append("special_requirements_keep_regular_meals")
    if "height_cm" in measurements and "weight_kg" in measurements:
        with exact_context():
            height = number(measurements["height_cm"])
            weight = number(measurements["weight_kg"])
            bmi = weight / (height / 100) ** 2
            result["bmi"] = decimal_text(bmi)
            if not 120 <= height <= 220 or not 35 <= weight <= 200:
                result["issues"].append("measurements_outside_product_range")
            if bmi < Decimal("18.5") or bmi >= 40:
                result["issues"].append("outside_supported_bmi")
    if request.get("can_meet_daily_needs") is False:
        result["issues"].append("daily_nutrition_or_schedule_not_feasible")
    result["missing_fields"] = sorted(set(missing))
    blockers = set(result["issues"]) - {"current_measurements_needed"}
    if blockers:
        result.update(status="not_enabled", action="keep_regular_meals")
        return result
    if missing:
        return result
    duration = PATTERNS[request["pattern"]]
    wake = _clock(request["wake_time"], "wake_time")
    sleep = _clock(request["sleep_time"], "sleep_time")
    if sleep <= wake:
        sleep += 1440
    start = _clock(request["eating_start"], "eating_start")
    if start < wake:
        start += 1440
    end = start + duration
    if request.get("eating_end") is not None and _clock(request["eating_end"], "eating_end") != end % 1440:
        result.update(status="conflict", action="choose_feasible_window_or_regular_meals")
        result["issues"].append("eating_window_duration_mismatch")
        return result
    if request["wake_time"] == request["sleep_time"] or end > sleep:
        result.update(status="conflict", action="choose_feasible_window_or_regular_meals")
        result["issues"].append("window_outside_awake_period")
        return result
    result.update(status="ok", action="optional_eating_window")
    result["schedule"] = {"pattern": request["pattern"], "eating_minutes": duration,
                          "fasting_minutes": 1440 - duration, "start": _time_point(start),
                          "end": _time_point(end), "wake": _time_point(wake), "sleep": _time_point(sleep),
                          "meal_times": [_time_point(start), _time_point(start + duration // 2), _time_point(end - 30)],
                          "clock_basis": "user_local_wall_clock", "valid_for": as_of,
                          "automatically_repeats": False, "work_pattern": request["work_pattern"]}
    result["notes"].append("三次进餐时间是可移动的组织示例；先确保所有餐点与加餐能吃够，不能做到就恢复常规进餐。")
    if request["work_pattern"] == "rotating":
        result["notes"].append("轮班安排仅对应本次起床后的清醒时段；换班后重新确认，不能自动沿用昨天时窗。")
    return result


def traditional_foods(profile: dict, as_of: str, request: dict) -> dict:
    """Offer optional ordinary-food methods, never constitutions, herbs, or treatment."""
    profile = validate_profile(profile)
    _day(as_of)
    _json_only(request)
    require_keys(request, set(), {"opt_in", "purpose", "method", "exclude_food_ids"}, "traditional food request")
    _boolean(request.get("opt_in"), "opt_in")
    purpose = request.get("purpose")
    method = request.get("method")
    if purpose is not None and (not isinstance(purpose, str) or purpose not in {"ordinary_food", "treatment", "constitution", "herbal"}):
        raise NutritionError("invalid_input", "Unsupported traditional food purpose")
    if method is not None and (not isinstance(method, str) or method not in _FOOD_METHODS):
        raise NutritionError("invalid_input", "Choose porridge, boil or steam")
    exclusions = request.get("exclude_food_ids", [])
    _text_list(exclusions, "exclude_food_ids")
    result = _result(profile, as_of, "traditional_foods", request)
    result["evidence"] = {"level": "ordinary_food_cultural_practice_no_therapeutic_claim",
                          "source_url": TCM_SOURCE,
                          "text": "下列做法是普通食材的烹调与文化偏好，不代表中医体质诊断；没有据此宣称祛湿、补肾、排毒或治疗疾病的临床结论。"}
    result["notes"] = ["普通食物也可能过敏。USDA记录未核实完整配料与交叉接触，不宣称过敏安全。",
                       "不用药材、药膳剂量或保健品替代正餐、处方药或就医。",
                       "这些做法不改变已核对的全天份量；若烹调方式或配料变化，重新核对，不捏造整碗粥或蒸制成品的营养值。"]
    if request.get("opt_in") is False:
        result.update(status="not_enabled", action="keep_regular_meals")
        return result
    if purpose in {"treatment", "constitution", "herbal"}:
        result.update(status="education_only", action="ordinary_food_education_not_prescription")
        result["issues"].append("clinical_or_herbal_request_not_prescribed")
        result["notes"].append("治疗、辨体质或药材问题应由合格专业人员评估；如只想使用普通食物，可改选普通食物模式。")
        return result
    missing = [f"profile.{field}" for field in result["assessment"]["missing_fields"]]
    for field in ("opt_in", "purpose", "method"):
        if request.get(field) is None:
            missing.append(f"request.{field}")
    result["missing_fields"] = sorted(set(missing))
    if result["assessment"]["route"] in {"professional", "support_only"} or "professional_plan" in profile:
        result.update(status="education_only", action="keep_existing_professional_meals")
        result["issues"].append("ordinary_methods_must_not_override_special_requirements")
        return result
    if missing:
        return result
    recipe = deepcopy(_FOOD_METHODS[method])
    dislikes = [value.casefold() for value in profile.get("preferences", {}).get("dislikes", [])]
    conflicts = []
    for food in recipe["foods"]:
        terms = [food["name"].casefold(), *(alias.casefold() for alias in food["aliases"])]
        if food["food_id"] in exclusions or any(dislike in term or term in dislike for dislike in dislikes for term in terms):
            conflicts.append(food["food_id"])
        del food["aliases"]
    if conflicts:
        result.update(status="conflict", action="choose_another_ordinary_method")
        result["issues"].append("excluded_or_disliked_foods")
        result["conflicting_food_ids"] = conflicts
        return result
    recipe.update(nutrition_calculation="not_calculated", portion_source="existing_meal_plan_only",
                  ingredients_verified=False, clinical_claims=[])
    result.update(status="ok", action="ordinary_food_method", recommendations=[recipe])
    return result
