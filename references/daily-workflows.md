# 日常使用与状态

## 建档与选餐

先明确成员；不要求真实姓名或证件。每份文档只服务一个稳定 member id，沿用已回答资料。目标可同时含增肌、减脂、健康饮食，但需确认当前优先方向，不许诺同时快速达标。

把已知事实放进最小 `profile`，调用 `assess_profile`。每轮最多问 1–3 个当前关键问题，可以把相关健康项合并成一问。未知不是“无”；缺资料时先提供适用的普通结构帮助。用户只想下一餐结构时，不强迫填体脂、腰围或照片。

用户需要个人份量时，再收集年龄、近期身高/体重/测量日期、方程所需性别、工作生活活动和阻力训练情况。公式性别与活动类别不能从姓名、照片或每周训练次数直接猜。`inputs`仅含`sex_for_equation`、`activity`、`resistance_training`。按 [营养规则](../docs/nutrition-rules.md)调用`automatic_targets`；展示估计范围与依据，不把BMI当诊断，不保证代谢精度。

目标成功后把完整返回值放入`document.planning={"inputs":目标.inputs,"target":完整目标}`。不要手工构造“看起来差不多”的目标或修改数值绕过规则；目标未成功则保留已知资料，先处理缺项或专业支持。

`preferences`的菜式、省事程度和场景独立，例如中式＋懒人＋外卖。已确认的稳定餐单设置可保存到`planning.options`：meal_ids、meal_shares、kitchen、max_prep_minutes、budget、excluded_food_ids、excluded_recipe_ids、recipe_ids。使用真实目录/组合ID，每次load后复用，用户明确改变才更新，不重复问厨具和预算。当天available_food_ids、variant、replace_meal_id只用于本次请求，不持久成稳定偏好；也不给profile随意加键。字段见 [餐单接口](../docs/meal-planning.md)。

## 每天安排与受保护换餐

有成功且仍适用的目标时，调用`generate_day_plan`。可以安排 2–4 个进餐组，不机械强制三餐。已有当天state就一并传入，锁定和已经记录的餐不得被重新生成覆盖。外卖配方/油盐/份量未知时使用`next_meal`的定性组合，并保留粗记能力，不能将外卖店的同名菜直接套成精确家常食物。

日常卡片优先显示：

1. 这餐实际食物与可食克重、生熟状态，以及怎么买/准备。
2. 操作时间和需预先备好的食物；时间估计不含事先煮饭或批量备餐。
3. 为什么这样分配及可用替换；需要时再展开营养算数与来源。

`find_foods`返回候选后核对真实食物；`list_recipes`发现真实组合ID。缺货时可排除食物/组合，或指定`recipe_ids`。只换午餐时传当前state及`options.replace_meal_id="lunch"`；早餐、晚餐也会固定保留，即使未锁定。失败时保留原state，解释可调整的软条件，不删除过敏/专业要求、不放大食物到不可行份量。

工具合计的是列出的计划食品，默认核对能量和蛋白范围，并检查显式传入的额外限制。求解时的脂肪比例是组合偏好，不是完整膳食认证。`cards`只列此次生成的餐；固定餐仍在返回state，需要显示全天时一起呈现。

生成器内部`check`覆盖其构造的餐次/食物，**不能代替用户确认没有其他饮料、加餐、酱汁或用油**。用户声明全天完整时，用`check_day_plan`显式核对`coverage.expected_meal_ids`和`confirmed=true`；未确认或有未知食物就保留false，说明当前只是列出食品的小计。不得删掉未知食物后称全天符合。

已有专业或自定全天限制时，先核对来源、适用成员与日期，不把source字符串当医学授权。`replace_meal`/`restore_plan`的限制按单餐解释，全天限制另用`check_day_plan`；固定餐也接受新限制复查。当前输入与限制无法表达时保留方案供参考，不能绕过。

## 计划和实际记录

先判断是打算吃，还是已经吃。确定日期、成员和餐次后按整餐证据分流：

| 用户陈述 | 操作 |
|---|---|
| 已按可量化计划吃完，食品和份量都明确 | `record_actual`，status=`confirmed`，写实际items。 |
| 明确全部食物只吃一半 | 按实际数量调用`record_actual`，status=`partial`；不重复记录原全量。 |
| 只说明饭吃八成，其他食物未说明 | 精细用户补关键缺项，或整餐粗记；不假设其他都吃完。 |
| 目录外外卖、火锅、未知克数的一碗饭 | `record_note`保存已知事实，quantity_status=`unknown`或有依据的`estimated`。 |
| 明确这餐没吃 | `not_eaten`；只代表这一餐，不能抹掉其他摄入。 |
| 未提该餐或只发尚未确认图片 | 未记录/待确认；不记零、不自动confirmed。 |

清楚陈述本身即为一次确认。照片由具备视觉能力的宿主提出食物/份量候选，用户确认后才匹配目录或粗记；不声称本核心做了图像识别或已完成图片实测。看图不能确认所有油盐、配料和过敏交叉接触。

包装资料可用`calculate_label`：先确认用户转录/照片识别的食品、每份/每100g/每包基准与实际克数，未确认不计算为已知摄入。标签四舍五入结果不加入USDA目录，不能伪造新food_id塞进state。整餐含无法匹配目录的包装食物时，用`record_note`保留食品、来源和实际克数；标签算过一包不等于整餐或全天完整。

**同一成员、日期、餐次不得有两份冲突实吃。** 定量confirmed/partial/not_eaten与同餐journal不能并存。定量纠正用`record_actual`；粗细记录互转前查 [契约](../docs/m3-contracts.md)，不支持的转换不得手删旧记录绕过。journal不参与精确合计。

定量更新取`document.days[date]`，将操作返回的新state放回该日期。`state.revision`与文件存储revision、目标revision相互独立。普通确认过的本地保存沿用已选方式，真正执行`save_record`后才称保存。

## 每周反馈与断档

先问执行难度、饥饿/精神、健康与活动变化，重用已经明确记录的事实。`weekly_review`负责简短执行建议，保存到`reviews`；没有训练用`training=not_training`。执行天数不等于难度，三次称重不等于已有趋势，未知保持unknown。

已有数值目标时可调用`weekly_adjustment`，将完整返回保存到`target_reviews`。数值变化要求同一目标下完整连续14天及两周各至少3个不同日期的可比称重，并满足 [营养规则](../docs/nutrition-rules.md#每周问候与数值调整)的执行和健康条件。可复用前一次结构化反馈中的已确认日期/体重，不让用户反复输入；不能伪造缺失值、健康未变或测量可比性。

- `maintain`：沿用返回目标，不改版本/生效日；资料不足时说明为什么先保持。
- `adjust`：仅用返回target替换`planning.target`，同时保持`planning.inputs=target.inputs`，保留完整前后复盘；按新目标重新生成未锁定、未记录的后续餐。
- `pause_and_review`：暂停自动优化、核对情况；不是停止正常吃饭，也不是补偿性少吃。

14天不足、称重不可比或执行困难时，先简化准备方式，不盲目减热量。健康变化、低精神、明显食欲下降或不明原因变轻时先处理适用性。断档回来设置`returning_after_gap`，核对当前目标与生活条件，从下一餐恢复，不要求补齐历史。没有提醒工具就由用户主动发起复盘，不声称后台自动执行。

## 可选时窗与普通食物文化做法

用户明确要求后才读 [策略契约](../docs/strategies.md)，调用`fasting`或`tcm`。时窗保留原有全天餐食，不自动扣量；三次时间只是组织例子，不能以完成断食为理由忍受不适。

明确选择后可在strategy_state保存fasting_preferences（opt_in、pattern、eating_start、wake_time、sleep_time、work_pattern六键）或traditional_preferences（opt_in、method两键）。strategy_state三个顶层字段都可选，未知停用史留缺，不为只用普通食物方法的人增加断食问卷。新会话load后沿用已选时间/方法，用户改变时才更新；症状和当前能否在时窗内吃够仍按本次事实填写，不因昨天成功就填无不适/可行。保存时窗偏好不代表通过启用条件。

`fasting`返回stopped时，在当前strategy_state只更新fasting_stopped_for_symptoms=true，保留其他已存偏好，按正常流程保存；后续request.previously_stopped_for_symptoms沿用true。未知时先问或保留null，不能默认false；新opt-in不清除既往停用。字段中false只允许明确自报未发生，且不能把symptoms、can_meet_daily_needs或previously_stopped_for_symptoms写进preferences。治疗、体质或药材请求不产处方；普通粥、煮、蒸做法遵守已有份量/过敏/专业要求。

## 家庭共餐与采购

确认操作者有权代管相关成员，只载入本次需要的档案。每个人分别分流、算目标和份量；专业支持也可以简洁呈现，不因此清空限制。家庭共同菜式不意味着统一热量或按人数平均；无法兼容的过敏/烹调要求分开准备。

把各成员目录内、量化后的items交给`aggregate_shopping`，member_id不可重复，同一成员多个餐次先合成一份items。汇总保留生熟和逐人可食克重，不把生鸡胸与熟鸡胸并成一个采购量，不猜含骨毛重、烹调损失或整包数。目录外食物列待确认，不填零。采购不自动下单、发消息或共享健康资料。

## 锁定与解锁的明确更改

用户明确固定/解锁某餐时，读取当前document，仅在内存改变指定日指定餐的locked，并把该state.revision加1；已经是所需状态不重复加版本。不改items、actuals或其他餐锁定。当前没有独立lock命令，使用受管`save_record`校验与record_id/当前存储revision保存，不能直接改文件。

用户只说换餐但原餐锁定，先解释冲突，不能自动解锁。组合操作按顺序使用最新state：换餐成功revision=4，再锁定得到5；当前revision=5，先解锁到6，再restore_plan得到7。一次磁盘保存只增加一次存储revision，不合并上述计划变化。失败不保存组合候选；详见 [保存与恢复](storage.md)。
