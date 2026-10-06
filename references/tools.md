# 实际工具调用

本文件负责调用方式与操作选择；准确字段仍以 [M3契约](../docs/m3-contracts.md)及 [M2契约](../docs/contracts.md)为准。

## 执行入口

使用宿主的本地代码／命令执行工具，调用本 Skill 根目录下的 `scripts/nutrition.py`。脚本按自身位置定位包，可从任意工作目录运行。Python 必须为3.11或更新版本；不为一次使用自动安装依赖或全局 Skill。

若执行工具支持 `argv` 与标准输入，使用参数数组 `python3`, `-B`, 脚本的已解析绝对路径，并把一个 JSON 对象发到标准输入。若只支持 shell，将工作目录明确设为 Skill 根目录，可用下面的无私人数据探测：

```sh
python3 -B scripts/nutrition.py <<'JSON'
{"operation":"describe"}
JSON
```

后续 JSON 由序列化器生成，优先通过执行工具的标准输入传入。只有 shell 工具时，可把序列化后的单行 JSON 放入上面单引号界定的 here-document；确认分隔符没有在内容中独占一行。不把用户原文拼接成 shell、Python 源码或未引用的 here-document。没有安全的标准输入渠道时说明该限制；不得为了调用而把原始健康输入写入临时脚本或日志。命令需要绝对路径时按已发现的真实路径构造，不能照抄另一台电脑的路径。

每次读取退出码和 JSON：0对应 `ok`；1为输入、读取或资料错误；2为 `needs_information`／`conflict`；3为 `unsupported`。返回非零不意味着可以忽略 JSON 中的具体原因。无有效结果时不生成伪成功数据。

## 操作选择

下表列出 `operation` 以外的请求键。不要把 Python 函数参数 `catalog` 放进 CLI：CLI使用随包目录。

| operation | 请求内容 | 结果使用方式 |
|---|---|---|
| `assess_profile` | `profile`, `as_of` | 使用 `route`、缺项与问题；只显示本轮重要问题，不把结果说成医学认证。 |
| `next_meal` | `profile`, `as_of`；可选 `meal_id`, `excluded_ids` | 呈现返回的一份推荐和最多两份候选；保留 `validation` 的含义。 |
| `weekly_review` | `profile`, `feedback`, `as_of` | 使用返回行动与原因；不自行增加热量／蛋白质／断食目标。 |
| `record_note` | `document`, `note` | 使用返回的新文档，未保存到磁盘前只称已在本次整理。 |
| `aggregate_shopping` | `member_meals` | 汇总已量化的可食克重，保留逐人、生熟与来源；不是原料购买毛重。 |
| `calculate` | `items` | 展示已核对食物的计算量；检查各营养素 `complete`、`known_amount` 与状态。 |
| `check_constraints` | `items`, `constraints` | 仅使用明确给定、适用于此次检查的限制；`ok`不是医学安全证明。 |
| `check_day_plan` | `state`, `constraints`, `coverage` | 合计计划而非实吃；`coverage`含`expected_meal_ids`与`confirmed`。以`plan_complete`和状态为准，不把漏餐小计当全天，也不自行生成目标。 |
| `record_actual` | `state`, `meal_id`, `actual` | 只更新实吃；把返回 `state` 放回当前成员对应日期。 |
| `summarize_actuals` | `state` | 未记录餐次单列；`day_complete`只覆盖 `listed_meals`，不是系统知道所有零食和饮料。 |
| `replace_meal` | `state`, `meal_id`, `items`, `constraints` | 只接受成功返回的新计划；锁定和已记录餐受保护。 |
| `revalidate_plan` | `state`, `constraints` | 新限制下逐餐检查，包括锁定餐；结果 `scope=meal`，不是全天目标验证。 |
| `restore_plan` | `state`, `previous_meals`, `constraints` | 只恢复计划，保留当前实吃；餐次ID集合必须不变。 |
| `save_record`／`load_record`／`export_record`／`delete_record` | 见 [保存协议](storage.md) | 先核对成员、路径、操作性质和版本，不能隐式持久化。 |

M3新请求中的数值也按契约使用十进制字符串或整数，不传 JSON 浮点数。省略或 `null` 的含义按字段规定处理，不能用 `false` 或空数组冒充用户已回答。

## 两个可以直接验证的纯请求

以下日期和成员均是虚构例子，实际调用替换成明确的用户日期与对象，不改变其他人档案。

初次资料不足时，先让工具提供有边界的追问：

```json
{"operation":"assess_profile","profile":{"id":"example_adult","goals":["fat_loss"],"storage":"temporary"},"as_of":"2026-10-05"}
```

用户已明确给出下面所有自报资料后，才可以使用这样的完整请求；不要将它当作真实用户的默认档案：

```json
{
  "operation": "next_meal",
  "profile": {
    "id": "example_adult",
    "age": 34,
    "goals": ["fat_loss"],
    "priority": "fat_loss",
    "preferences": {"cuisine":"chinese","effort":"lazy","scenario":"takeaway","dislikes":[]},
    "health": {"allergens":[],"conditions":[],"medications":[],"pregnancy_lactation":false,"eating_disorder_risk":false,"malnutrition_risk":false},
    "storage": "temporary"
  },
  "as_of": "2026-10-05",
  "meal_id": "lunch"
}
```

换餐结构使用实际返回的模板ID填 `excluded_ids`。不要假设不存在的鸡腿、鱼或豆腐都能精确计算；也不要从模板ID推导食品ID。

## 当前精确食品目录

| food_id | 已核对记录 |
|---|---|
| `usda:171077` | 生、去皮去骨鸡胸肉 |
| `usda:171477` | 烤熟鸡胸肉，meat only |
| `usda:2512381` | 生、未强化长粒白米 |
| `usda:169757` | 无盐煮熟、未强化长粒白米 |
| `usda:330137` | 原味脱脂希腊酸奶 |

调用前按实际食物状态匹配。不同记录不是同批原料的生熟配对，不能用两者相除生成烹调换算率。来源的 `cup`、`container`、`RACC`不是用户任意饭碗、商品包装或推荐份量；需要来源指定的 `portion_id` 和适用条件。没有密度时不把毫升当克。所有现有样本的过敏信息均未完成完整配料与交叉接触核实。

现成代码接口执行数值验证；模型只理解、提问和解释。解析失败时查看契约并修正明确输入，不通过绕过校验、直接改文件或改食物资料来完成任务。
