# 个人目标与定量餐单接口

当前首版功能候选 0.3.0 使用30条离线USDA食品和17个可求份量的组合；另有13个`next_meal`定性模板。组合是本项目编写的家常/省事准备方式，营养值来自准确食品记录，来源见 [数据说明](data-provenance.md)。菜单计算不是营养完整性、临床安全或减重效果认证。

## 可复现的目标到餐单流程

CLI每次接收一个JSON对象。先发`automatic_targets`，将其**完整返回对象**作为下一次`generate_day_plan.target`，不要手工抄数重建target。以下均为虚构资料，不是给未知用户预填的健康答案：

```json
{
  "operation":"automatic_targets",
  "profile":{
    "id":"example_adult",
    "age":34,
    "goals":["fat_loss"],
    "priority":"fat_loss",
    "preferences":{"cuisine":"chinese","effort":"lazy","scenario":"home","dislikes":[]},
    "measurements":{"height_cm":"175","weight_kg":"75","measured_on":"2026-10-06"},
    "health":{"allergens":[],"conditions":[],"medications":[],"pregnancy_lactation":false,"eating_disorder_risk":false,"malnutrition_risk":false},
    "storage":"temporary"
  },
  "inputs":{"sex_for_equation":"male","activity":"inactive","resistance_training":false},
  "as_of":"2026-10-06"
}
```

在项目根目录执行以下标准库示例，会依次通过实际CLI完成两个请求，不保存资料：

```sh
python3 - <<'PY'
import json
import subprocess
import sys

profile = {
    "id": "example_adult", "age": 34, "goals": ["fat_loss"], "priority": "fat_loss",
    "preferences": {"cuisine": "chinese", "effort": "lazy", "scenario": "home", "dislikes": []},
    "measurements": {"height_cm": "175", "weight_kg": "75", "measured_on": "2026-10-06"},
    "health": {"allergens": [], "conditions": [], "medications": [],
               "pregnancy_lactation": False, "eating_disorder_risk": False, "malnutrition_risk": False},
    "storage": "temporary",
}

def call(request):
    completed = subprocess.run(
        [sys.executable, "-B", "scripts/nutrition.py"],
        input=json.dumps(request), text=True, capture_output=True, timeout=30,
    )
    result = json.loads(completed.stdout)
    if completed.returncode != 0 or result["status"] != "ok":
        raise SystemExit(json.dumps(result, ensure_ascii=False, indent=2))
    return result

target = call({"operation": "automatic_targets", "profile": profile,
               "inputs": {"sex_for_equation": "male", "activity": "inactive", "resistance_training": False},
               "as_of": "2026-10-06"})
plan = call({"operation": "generate_day_plan", "profile": profile, "target": target,
             "as_of": "2026-10-06", "options": {"kitchen": "stove", "max_prep_minutes": 15}})
print(json.dumps({"target": target, "plan": plan}, ensure_ascii=False, indent=2))
PY
```

对真实用户使用明确的当地日期和本人资料，不把例子的日期/健康字段当默认。目标理论、适用范围和数值复盘字段见 [营养规则](nutrition-rules.md)。

## generate_day_plan 请求

必需键为`operation="generate_day_plan"`、`profile`、`target`、`as_of`；可选键为`options`、`state`、`constraints`。Python入口为`generate_day_plan(profile, target, as_of, options=None, state=None, constraints=None)`，同样不改输入、不联网、不写档案。

| options字段 | 值/默认 | 行为 |
|---|---|---|
| `meal_ids` | 从breakfast/lunch/dinner/snack中选2–4个不重复ID；默认前三餐 | 这是进餐组，不限制用户一天只能吃这些食品；饮料/加餐需要纳入相关items或另组。 |
| `meal_shares` | 键恰好对应meal_ids，值为1–100整数 | 按相对权重分配可调整餐的剩余能量/蛋白。默认三餐25/38/37；其他餐组默认等权，不要求加总100。 |
| `kitchen` | `none/microwave/stove`，默认stove | 按组合可用设备筛选。scenario=no_cook强制none；不把需煮普通燕麦当无厨具即食食物。 |
| `max_prep_minutes` | 1–120整数，默认30 | 每餐估计主动操作时间；effort=lazy另限不超过15分钟。预先煮饭、批量备餐和采购不在计时内。 |
| `budget` | `ordinary/economy`，默认ordinary | economy筛选自有经济型组合，不估计地区实际价格。 |
| `available_food_ids` | 可选已核对food_id数组 | 每道候选所需食品都必须在列表；省略表示不以库存限制，空数组表示没有可用食品。 |
| `excluded_food_ids` | 默认空数组 | 排除指定食品，并结合profile.preferences.dislikes；硬限制不会被变体覆盖。 |
| `excluded_recipe_ids` | 默认空数组 | 排除指定组合。 |
| `variant` | 0–100整数，默认0 | 与日期共同改变可行候选顺序；不是随机营养、口味或每日不重复保证。 |
| `recipe_ids` | 如`{"lunch":"171477-169757"}`；实际ID以list_recipes为准 | 限定对应餐可用组合，仍须满足口味、设备、库存、份量和全天限制。 |
| `replace_meal_id` | meal_ids内的一个ID | 必须同时提供已有state，只改这一餐，其他餐固定保留；目标餐锁定/已记录时conflict。 |

不要照抄示意recipe ID而跳过发现步骤；请求中的未知食品/组合会报错，不做近名替换。菜式偏好来自profile.preferences.cuisine=chinese/western/mixed，准备负担来自effort=lazy/standard，场景为home/takeaway/no_cook。食物不喜欢的文字用于筛选，但不替代过敏核实。

`state`结构沿用 [核心契约](contracts.md)，meals集合必须与meal_ids完全一致。新增/减少进餐组不能通过重新生成悄悄丢弃现有餐次。`constraints`格式为`{"limits":[...],"allergens":[...]}`，作为额外全天限制，与目标的能量/蛋白范围一起检查；已知但不能表示的临床要求不允许传空绕过。

## 返回结果与符合范围

结果含schema_version=`generated-day-plan-v1`、member_id、as_of、status、state、cards、check、issues、target_revision、scope=`planned_foods_only`、clinical_validation=false。status为ok时才采用state；失败保留输入state，不能将未通过候选写为新计划。

`cards`含meal_id、recipe_id、title、active_minutes、preparation和portions。每个portion提供food_id、中文名、grams十进制字符串、来源state及可选来源份量索引。显示生熟/干重和可食部分，不能把熟鸡胸克数改称生肉采购量，也不把来源cup自动当用户饭碗。

求解器以组合固定食物和三类可调食物计算份量，使用能量、蛋白与约28%脂肪能量的**组合偏好**；变量上下限在组合数据中明确。普通食物取近5g、油取近1g，再核对舍入后的结果。默认通过门是目标能量/蛋白范围及显式extra constraints；不能把组合偏好说成脂肪安全门，或称纤维/钾/微量营养素已自动优化。源数据缺失、LOQ和未知过敏规则仍生效。

内部check的confirmed=true只描述生成器已列出的计划食品，不表示用户已经确认没有其他摄入。显示时说明未列饮料、加餐、酱汁、盐或油需加入并重查；实际使用`check_day_plan`的全天完整确认按 [日常流程](../references/daily-workflows.md#每天安排与受保护换餐)执行。

## 固定餐、替换与目标兼容

有当前state时，锁定餐、actuals中confirmed/partial/not_eaten餐，以及replace_meal_id以外的餐都原样保留。生成器从目标中扣除这些**计划食品**的能量/蛋白后分配可修改餐；actuals始终保留、不参与这个计划求解。实际偏离计划不能触发补偿性少吃。

成功修改已有state时计划revision加1，新建state从0开始；全固定而无修改不增加版本。cards只列本次生成餐，preserved_meal_ids标出固定餐。失败不会清空实际记录或放松锁。新排除食物与固定餐冲突仍会报告，锁定不能屏蔽新的过敏/限制问题。

目标必须属于当前成员、status=ok、与当前健康/目标/年龄/身高相容，体重相对原基线变化不能超过5%，生效日期不得在未来且距本次不超过90天；当前测量仍受30天规则约束。健康、目标或基线变化导致target_refresh_required等结果时，先核对并重新估计，不借另一个人的目标、不修改target字段蒙混通过。周调整产生的新target按完整返回值使用，不重置其revision。

若没有符合当前条件的组合，会返回conflict和affected_meal。可以和用户调整餐次份额、库存、偏好或准备条件后再算；不自动删除过敏限制、不把份量放大到组合上限外。特定厨房、两餐/四餐、目标组合不保证永远存在可行解；明确不可行也是有效结果。

## 发现、外食、标签与照片

```json
{"operation":"find_foods","query":"米饭"}
```

```json
{"operation":"list_recipes"}
```

find_foods返回candidates、confirmation_required=true和automatic_substitution=false。名称exact只是索引相符，仍要核对用户实际食品；不明确就保留候选，不能自动等同外卖店配方或任意品牌。

scenario=takeaway的定量请求返回needs_information与qualitative_help，继续提供next_meal结构帮助及record_note粗记，不伪造整餐热量。照片由宿主识别候选，用户确认食品及份量后才走目录算数；不确认就粗记或待确认。本核心不含图片识别，也未因提供文字流程而证明图片实测通过。

包装标签可独立核算，不用创建伪USDA条目：

```json
{
  "operation":"calculate_label",
  "label":{
    "name":"虚构包装酸奶",
    "source_note":"用户确认的包装每100g营养标签；合成算数示例",
    "basis_g":"100",
    "nutrients":{"energy_kcal":"60","protein_g":"4","carbohydrate_g":"6","fat_g":"2"}
  },
  "amount_g":"150",
  "confirmed":true
}
```

basis_g对应标签实际的每份/每100g/每包克重。能量只用energy_kcal或energy_kj其中一个；其他允许键为protein_g/carbohydrate_g/fat_g/fiber_g/sodium_mg/potassium_mg/phosphorus_mg，值为十进制字符串或null。未确认时totals=null且needs_information；确认后值仍标label_rounded，未提供营养项保持missing。结果无过敏认证、不写实际记录，不因换算成功将一包当全天完整。整餐含目录外食品时可record_note保留标签来源和克数，不造food_id混进state。[FDA标签份量说明](https://www.fda.gov/food/nutrition-facts-label/serving-size-nutrition-facts-label)

## 保存连接

`document.planning`必需`inputs`和完整target，inputs须与target.inputs一致；可选`options`保存用户已确认的稳定设置：

```json
{
  "meal_ids":["breakfast","lunch","dinner"],
  "meal_shares":{"breakfast":25,"lunch":38,"dinner":37},
  "kitchen":"stove",
  "max_prep_minutes":15,
  "budget":"economy",
  "excluded_food_ids":[],
  "excluded_recipe_ids":[],
  "recipe_ids":{}
}
```

这是planning.options的独立内容示例，不能用它替代完整planning。其键均可按已知情况省略；不保存用户未回答的偏好，也不把例子的空排除列表当真实答案。ID必须来自实际发现，其他类型/范围沿用上表。每次load后复制这些稳定设置为本次options，再加入当天明确的available_food_ids、variant或replace_meal_id；这三个瞬时字段不得写回planning.options。用户只改午餐，不代表长期清空其他偏好。

`document.days[date]`放成功state，数值复盘完整结果放target_reviews，简短执行反馈放reviews。它们互不覆盖。strategy_state还可保存已确认时窗/普通食物方法偏好，准确字段见 [保存协议](../references/storage.md#首次选择与普通保存)；当前症状、当天营养可行性仍需本次资料，停用史独立保留。更改后按已选方式真正保存；本接口自身不保存、归档、导出或发送资料。
