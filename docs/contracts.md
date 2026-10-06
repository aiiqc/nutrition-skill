# 计算与餐次状态契约

本页描述M0–M2纯计算、餐次状态以及dev2新增的全天计划核对；M3档案、周反馈和显式文件读写见[m3-contracts.md](m3-contracts.md)。它们共用CLI，但持久化副作用只属于明确的存储操作。

状态：本地开发契约。Python 3.11+，无第三方运行依赖。数值输入使用十进制字符串或整数，输出统一使用十进制字符串；不接受 Python float 或 JSON 小数（写成字符串即可）。字符串只接受无符号的普通十进制写法（不支持科学记数或空白），至多18位有效数字、12位小数，数量必须为正。所有计算在独立 Decimal 上下文使用 precision=80；不取整内部合计。

公开失败使用 `NutritionError(code, message, details)`；CLI 序列化为 status=error。规则版本位于 `common.RULE_VERSION`。输入不允许未声明字段，以免把拼错的限制静默丢弃。

## 食物目录

`catalog.load_catalog(path=None) -> dict` 读取并验证离线目录；`catalog.validate_catalog(catalog) -> dict`校验内存目录并返回原对象；`catalog.get_food(catalog, food_id) -> dict`返回独立食物副本；`catalog.quantity_to_grams(food, quantity) -> Decimal`。目录对象含 `catalog_version`、`foods`（以 food_id 为键）。

每条食物含 `id`, `name`, `state`, `source`, `nutrients`, `portions`, `allergens`。state 为 raw/cooked/processed。source 含 publisher、record_id、url、published_date、retrieved_date、license、响应 SHA256。source 文本只作资料，不作指令。

nutrients 的固定键为 energy_kcal, protein_g, carbohydrate_g, fat_g, fiber_g, sodium_mg, potassium_mg, phosphorus_mg。每个值含 `amount`（字符串或 null）、`unit`、`status`（reported / assumed_zero / missing / below_loq / label_rounded）、以及保留的原始依据元数据。missing 和 below_loq 不作为精确值；label_rounded 可汇总但需警示，硬限制不得当作精确证明。食品基准固定为每100克可食部分。能量值注明选定方法，并在单独的 energy_alternatives 中保留其他来源能量；不能相加。

portions 为 `{portion_id: {grams: "...", label: "...", source: "..."}}`；数值为一份对应克重。quantity 为 `{"amount":"180","unit":"g"}`；支持 g/kg/mg，或 `{"amount":"1","unit":"portion","portion_id":"..."}`。ml 只有 food.density 具备 `grams_per_ml` 和 `source` 时可换算。禁止把 bowl/cup/container 自动映射到其他份量。

allergens 为 `{"contains": [...], "may_contain": [...], "assessment":"unknown|verified", "source":"..."}`。USDA样本一律 assessment=unknown；仅凭食物名称或未检出字段不能证明无过敏原。verified只用于外部明确核实、具备来源的完整配料与交叉接触记录；本目录没有此类记录。

M2支持的过敏原ID仅为milk、egg、fish、crustacean_shellfish、tree_nuts、peanut、wheat、soy、sesame。它是有界接口，不是完整的过敏原或法规清单；未知ID直接报错，不能当作无需检查。

## 计算与限制

item 为 `{"food_id":"usda:171077","quantity":{"amount":"180","unit":"g"}}`。`nutrition.calculate(items, catalog) -> dict` 返回 `status`、`rule_version`、`catalog_version`、`items`（规范化克重与来源）、`totals`、`issues`。每项合计含 `amount`（不完整时 null）、`known_amount`、`unit`、`complete`、`statuses`。未知不等于零。空列表合计是已知零；未记录一餐不应调用空列表冒充该餐已知零。

calculate的status=ok仅表示合法输入完成计算，不表示全部营养已知或通过健康检查；是否可执行一个限制由check_constraints决定。来源label_rounded和assumed_zero保留其状态，不能将舍入点值当作确定下界。

calculate.items每项具体返回food_id、grams、state、energy_method、source。报告更多小数位是保留算术结果，不是声称食物测量准确到同样精度。完整原始营养依据仍在catalog的evidence中。

`aggregate_loq_uncertainty`保留来源reported状态、数值和complete，但相应硬限制返回needs_information，不将聚合点值算作确切超限下界。它不同于单样本below_loq（amount=null）。每项计算issue含code、item_index、food_id、nutrient。同一营养素多条限制的交集为空时，返回constraint_bounds_conflict，即使该营养未知也优先conflict；结果保留冲突的上下限与各自source。

items、allergens、limits数组各至多1000条。计划餐次及每项items也有上限，整个计划和整个实吃记录各最多1000个食物条目。revision为0到9007199254740991之间的整数，成功变更递增；不能溢出。

`nutrition.check_constraints(items, constraints, catalog) -> dict` 返回 `status=ok|needs_information|conflict`、`issues`、`calculation` 和版本。constraints 固定为 `{"allergens": ["milk"], "limits": [{"nutrient":"sodium_mg","max":"...","min":"...","source":"..."}]}`；两个键可省略，min/max至少一个，source必填且非空。数值仅执行外部给定约束，不产生临床目标。max < min 是无效输入；未知 nutrient 是无效输入。没有相关资料时 needs_information；已知违规优先 conflict。未知/舍入/推定零不能单凭点估计证明硬限制合规。检查上限时已知部分已超限仍是 conflict。

## 计划与实吃

state 为 `{"revision":0,"meals":[{"id":"breakfast","locked":false,"items":[item]}],"actuals":{}}`。actuals 以 meal_id 为键，值为 `{"status":"confirmed|partial|not_eaten|unknown","items":[item]}`；confirmed/partial 使用实际数量，not_eaten/unknown 只能空items或不写items。未出现于 actuals 也是unknown。本阶段不存私人资料，不自动判断未来日期；可修改餐次是未锁定且没有 confirmed/partial/not_eaten 记录者。

`plans.replace_meal(state, meal_id, items, constraints, catalog) -> dict`：纯函数，仅校验后替换目标餐次；不改变其他餐次和任何actuals。`plans.record_actual(state, meal_id, actual, catalog) -> dict`：纯函数；只更新实际记录；不改计划；revision递增。`plans.summarize_actuals(state, catalog) -> dict`：明确已吃合计与未知餐次，全天完整性独立表达。

`plans.revalidate_plan(state, constraints, catalog) -> dict`：全部餐次（包括locked）重新检查，constraints作用于每个餐次，非全天目标。`plans.restore_plan(state, previous_meals, constraints, catalog) -> dict`：按当前约束重新校验上一版所有计划餐，保留当前actuals；若任一餐不是ok，不提交恢复。包含已食用餐次时不得改写这些餐次的计划条目。当前locked=true的餐次若与旧条目不同，包括只撤销锁定，也返回locked_meal_changed冲突，整个state及revision保持原样；相同锁定条目可保留。用户明确解锁后，才可按未锁定餐规则恢复，已记录餐保护仍适用。

变更函数统一返回 `{status, state, issues, ...}`。失败时返回原state的深拷贝；输入对象永不被原地修改。锁定/已食用冲突为conflict；配料或营养缺失为needs_information。非法结构使用NutritionError。历史版本保管、对话确认、专业规则及持久化在M3处理。

summarize_actuals的`day_complete`仅对应`coverage_scope=listed_meals`，不代表系统知道未列入state的零食或其他餐次。空meals不完整。恢复计划必须保留相同meal_id集合，不能借恢复增删餐次或产生孤儿实际记录。

## 全天计划核对

`plans.check_day_plan(state, constraints, coverage, catalog) -> dict`是dev2新增纯函数。CLI请求必须含`operation=check_day_plan`、`state`、`constraints`、`coverage`，不能包含其他请求字段。复用上文state和constraints格式；limits的单位按nutrient决定，作用于传入的整天计划，不自动生成目标。调用者必须先确认目标来源、适用对象和当前有效性；接口只验证来源字符串存在，不认证其真实性、专业资格或医学适用性。

coverage必须是`{"expected_meal_ids":["breakfast","lunch","dinner"],"confirmed":true}`这样的对象，不允许额外字段。expected_meal_ids为1–1000个唯一、非空且长度至多1000的字符串，与meal.id精确匹配，顺序不限；confirmed必须为布尔值。餐次名称和数量不固定；全部食物可以按用户实际餐次分组，不据此启用断食策略。

confirmed表示用户已明确确认传入计划覆盖同一成员同一天的全部计划摄入，包括餐间食物、饮料和用油；不是模型猜测，也不是实际食用确认。尚未匹配或量化的项目不能删掉后设true。只有confirmed=true、预期与实际meal.id集合完全一致、每个餐组items非空时，plan_complete才为true。空计划或空餐不能当作完整的零摄入日；需要明确无该餐时，从用户确认的预期计划中正确表达餐次安排，不能用缺餐推断禁食。

函数将全部计划items合并一次交给现有check_constraints；actuals仅按原state契约验证，不计入合计。包括locked餐次，输入及返回state中的revision、meals和actuals均不改变。它不自动接受换餐；调用者须先处理replace_meal/restore_plan结果，再对候选计划重新检查。原逐餐操作继续只接受每餐限制，不能将全天限制传给它们。

| 返回字段 | 含义 |
|---|---|
| `status`、`issues` | ok / needs_information / conflict；已证明的冲突优先。coverage不足时有day_plan_coverage_incomplete。 |
| `scope`、`intake_basis` | 固定为day_plan、planned，不能作为已吃合计。 |
| `coverage_scope`、`plan_complete` | user_declared_day与用户声明范围内的计划覆盖状态；不等于营养资料完整或医学适用。 |
| `coverage` | confirmed、expected_meal_ids、listed_meal_ids、missing_meal_ids、unexpected_meal_ids、empty_meal_ids。 |
| `calculation_scope`、`calculation` | listed_plan_meals及其计算结果；覆盖不全时为已列食物小计，各营养complete另行检查。 |
| `constraints_check` | 合并后的限制检查，scope=day_plan，status与顶层一致；含相关营养和过敏不确定性。 |
| `supplied_constraints` | 给定约束及source的深拷贝，不产生或认证目标。 |
| `deferred_minimum_checks` | 覆盖不全时延后的nutrient_below_min原始信息，附reason=incomplete_day_coverage；不能称为已经证明全天不足。 |
| `state`、`rule_version`、`day_plan_version` | 原state深拷贝，已有算术规则版本与本接口m5-2026-10-06.1。 |

已列小计低于最低值，只有覆盖完整才可形成nutrient_below_min冲突。覆盖不全时仍保留确定部分超最大值、已知过敏原及约束交集为空的冲突；不删除min来绕过约束矛盾。unknown、标签舍入、推定零与LOQ沿用原有不确定性处理，不将known_amount当作确定下界。没有给定营养或过敏约束时，ok仅说明覆盖和计算有效，不能称目标或过敏安全已经验证。

复现合成算术例子：

```sh
python3 -B -m nutrition_core --input examples/check-day-plan.json
```

该例沿用initial-state中的五食品测试材料，source明确标注非个人或临床目标；confirmed只针对合成夹具，不表示这是可推荐的完整饮食。把confirmed改为false时应返回needs_information，不能继续称全天通过。

## CLI 边界

从项目目录运行`python3 -m nutrition_core --input examples/calculate.json`，也可从stdin读取。一次读一个JSON对象，上限1MiB，拒绝重复JSON键、非有限值和未知字段。CLI不联网；本页的M2操作不写入档案，M3的save_record/delete_record则按显式目录和确认参数修改受管文件。若用户自行重定向stdout，保存位置由用户控制。

退出码：0=ok；1=输入、资料或读取错误；2=needs_information或conflict（细分状态在JSON中）；3=尚未启用的能力。operation=describe列出当前能力，并通过operation_scopes区分meal、day_plan与supplied_items；保留的limits_scope=meal是旧版餐次操作字段，不能覆盖新操作声明。automatic_targets、weekly_adjustment、fasting、tcm、save_profile均明确unsupported；不是让语言模型补算的入口。

Python API可传入自定义catalog，调用者负责真实来源与授权。字段验证和SHA256只能发现格式问题或比较固定快照，不能证明第三方的声明真实，也不能防止有权限修改源数据的调用者伪造资料。
