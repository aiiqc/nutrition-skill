# 实际工具调用

数值、餐次与限制见 [核心契约](../docs/contracts.md)，基础档案见 [M3 契约](../docs/m3-contracts.md)，新增目标、餐单、策略和长期历史分别见 [营养规则](../docs/nutrition-rules.md)、[餐单接口](../docs/meal-planning.md)、[策略接口](../docs/strategies.md)、[存储演进](../docs/storage-evolution.md)。

## 执行入口

解析本 Skill 根目录下 `scripts/nutrition.py`的真实绝对位置，使用 Python 3.11+。脚本按自身位置定位包，可从任意工作目录调用，不为一次使用安装依赖或全局 Skill。

支持 argv/标准输入的工具优先用参数数组 `python3`, `-B`, 脚本绝对路径，将序列化 JSON 发到 stdin。只有 shell 时可在明确 Skill 根目录下探测：

```sh
python3 -B scripts/nutrition.py <<'JSON'
{"operation":"describe"}
JSON
```

使用序列化器生成 JSON，不把用户原文拼进 shell/Python 代码。here-document 分隔符须单引号引用且不能在输入中独占一行。没有安全输入渠道就说明限制，不把健康输入写入临时脚本或日志。读取退出码和 JSON 状态；非零既可能是输入错误，也可能是缺项、冲突或主动停用，不能忽略具体原因。只有真实成功结果才可声称完成。

## 操作选择

下表列出 `operation`之外的键；CLI 使用随包目录，不能增加 Python 函数专用 `catalog`参数。

| operation | 请求键 | 处理原则 |
|---|---|---|
| `describe` | 无 | 查看版本、食品数量、操作与平台边界。 |
| `assess_profile` | `profile`,`as_of` | 使用分流、缺项和问题；不是医学认证。 |
| `automatic_targets` | `profile`,`inputs`,`as_of` | 返回完整目标；仅 status=ok 可进入定量生成，不手工重算或改字段。 |
| `generate_day_plan` | `profile`,`target`,`as_of`；可选 `options`,`state`,`constraints` | 按生活条件生成/替换；成功后取返回 state，失败保持原计划。 |
| `find_foods` | `query` | 返回待确认候选、状态和来源份量；即使 exact 也不是用户食物自动确认。 |
| `list_recipes` | 无 | 发现真实组合 ID、餐次、厨房和准备条件，不从标题猜 ID。 |
| `next_meal` | `profile`,`as_of`；可选 `meal_id`,`excluded_ids` | 外卖/定性结构或专业要求转述，不附未算出的热量。 |
| `weekly_review` | `profile`,`feedback`,`as_of` | 简短执行反馈，保存到 reviews；不自行改变数值目标。 |
| `weekly_adjustment` | `profile`,`target`,`feedback`,`as_of` | 有足够可比 14 天资料才可能 adjust；完整结果保存到 target_reviews。 |
| `fasting` / `tcm` | `profile`,`as_of`,`request` | 明确选择后按策略契约调用；退出及缺项不能变成推荐。 |
| `record_note` | `document`,`note` | 未量化整餐的确认事实；返回新文档，不自动写磁盘。 |
| `calculate` | `items` | 看各营养素 complete/known_amount，不把部分算数说成营养完整。 |
| `calculate_label` | `label`,`amount_g`,`confirmed` | 用户确认的包装标签换算；保留label_rounded/missing，不造目录ID、实吃或过敏结论。 |
| `check_constraints` | `items`,`constraints` | 只核对明确的本次限制；成功不是医学安全证明。 |
| `check_day_plan` | `state`,`constraints`,`coverage` | 核对计划；coverage含expected_meal_ids/confirmed，漏项不算全日。 |
| `record_actual` | `state`,`meal_id`,`actual` | 仅更新已确认实吃，放回对应成员与日期。 |
| `summarize_actuals` | `state` | 缺餐单列；listed_meals不等于已知所有饮料和零食。 |
| `replace_meal` | `state`,`meal_id`,`items`,`constraints` | 核心逐餐替换；成功后还要核对全天。自动配份量优先用generate_day_plan的replace_meal_id。 |
| `revalidate_plan` | `state`,`constraints` | 新单餐限制下逐餐核对，包括锁定餐；不是全天目标。 |
| `restore_plan` | `state`,`previous_meals`,`constraints` | 恢复计划、保护已记录/锁定餐，保留当前实吃。 |
| `aggregate_shopping` | `member_meals` | 分人汇总可食克重，不是带骨毛重或购买包数。 |
| `save_record` | `data_dir`,`member_id`,`document`,`expected_revision`,`consent`；更新时`expected_record_id` | 已选择本地后正常保存沿用同意；结果成功才称已保存。 |
| `load_record` | `data_dir`,`member_id`；可选`version` | 当前或历史读取；写入使用current_revision。 |
| `archive_record` | `data_dir`,`member_id`,`expected_revision`,`expected_record_id`,`consent`；可选`keep_from_date` | 明确启用长期及准确日期移出范围，旧资料仍在历史。 |
| `export_record` | `data_dir`,`member_id`；可选`start_version`,`limit` | v3分页；核对所有页身份和版本，不自动写文件或发送。 |
| `delete_record` | `data_dir`,`member_id`,`expected_revision`,`expected_record_id`,`confirmed` | 准确授权后删除该记录及其受管归档。 |

JSON 数值遵守具体接口；营养与测量小数使用十进制字符串，不传浮点。省略、null、unknown、false和空数组不是同义词。所有存储操作详见 [保存协议](storage.md)。

已有档案时先load_record，从planning.options取已确认的稳定餐单设置；本次明确变化覆盖对应键，其余保留。strategy_state中的fasting_preferences/traditional_preferences可复用已选方法和时间，但调用fasting仍须补本次symptoms/can_meet_daily_needs，并将已知停用史独立映射到previously_stopped_for_symptoms。不得把这三个安全字段写进preferences以代替当前判断。

## 最小发现与食物匹配

```json
{"operation":"assess_profile","profile":{"id":"example_adult","goals":["fat_loss"],"storage":"temporary"},"as_of":"2026-10-06"}
```

```json
{"operation":"find_foods","query":"熟鸡胸"}
```

```json
{"operation":"list_recipes"}
```

以上日期和成员只是虚构例子。完整可复現的自动目标到餐单请求见 [餐单接口](../docs/meal-planning.md#可复现的目标到餐单流程)。

当前 30 条食品及中英文索引覆盖常见主食、蛋奶、豆类、鱼鸡肉、果蔬和油脂；准确清单及证据见 [来源说明](../docs/data-provenance.md)。现有 17 个可求份量组合和 13 个定性模板是两种不同产物，模板 ID 不是食物 ID。

包装标签的label含name/source_note/basis_g/nutrients，amount_g是实际可食克数，confirmed来自用户核对。nutrients只允许能量kcal或kJ二选一及现有蛋白/碳水/脂肪/纤维/钠/钾/磷字段，值用十进制字符串或null。完整JSON例子和边界见 [标签算数](../docs/meal-planning.md#发现外食标签与照片)。

匹配时核对生熟状态、凝固剂、乳脂含量、品牌差异与可食部分。黑芸豆不等于黑大豆，巴旦木/扁桃仁不等于杏核仁。来源cup/container不是任意碗或包装；须选对应portion_id。没有密度不把ml当g。所有目录过敏判断仍为unknown。解析失败按契约修正明确输入，不改来源或绕过校验。
