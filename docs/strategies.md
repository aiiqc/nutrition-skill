# 可选进餐时窗与普通食物文化做法

这两个接口提供实际可执行的时间安排和烹调方法，默认不启用。它们不修改营养目标、不写档案、不联网，也不生成医疗处方。版本为 `nutrition-strategies-2026-10-06.1`，返回 schema 为 `nutrition-strategy-v1`。

## 进餐时窗

`fasting_plan(profile, as_of, request)` 接收现有结构化档案、`YYYY-MM-DD` 评估日期和下列请求。宿主必须保留用户自报的未知项，不能为了得到成功结果而填 `false` 或空数组。

```json
{
  "opt_in": true,
  "pattern": "16:8",
  "eating_start": "09:00",
  "wake_time": "07:00",
  "sleep_time": "23:00",
  "work_pattern": "day",
  "symptoms": [],
  "previously_stopped_for_symptoms": false,
  "can_meet_daily_needs": true
}
```

这是字段示例，不能作为未知用户的预填健康答案。`opt_in` 必须是用户明确同意；`symptoms=[]` 必须是用户明确表示没有当前不适；`previously_stopped_for_symptoms=false` 必须有本人回答或可用历史支持。

| 字段 | 值与含义 |
|---|---|
| `opt_in` | `true/false/null`；缺失或 null 保持未知，false 保持常规进餐 |
| `pattern` | `12:12`、`14:10`、`16:8`，前者是禁食小时，后者是进餐小时；不支持隔日、一天一餐或更长禁食 |
| `eating_start` | 用户选定的当地时间，严格 `HH:MM`，00:00–23:59 |
| `eating_end` | 可省略，由开始时间和模式计算；提供时必须与计算结果一致 |
| `wake_time` / `sleep_time` | 本次作息的起床/入睡时间，严格 `HH:MM`；相同时不能判断清醒区间 |
| `work_pattern` | `day`、`night`、`rotating`；安排必须完全位于用户给定的清醒区间 |
| `symptoms` | 自报不适的文字数组或 null；非空立即返回退出安排 |
| `previously_stopped_for_symptoms` | 是否曾因不适停止；true 不会被新的 opt-in 覆盖 |
| `can_meet_daily_needs` | 能否在时窗内吃够现有全天餐食并适应工作、训练和睡眠；false 不缩餐硬凑 |

启用范围是无特殊饮食要求的一般成人：19–64 岁，身高 120–220 cm、体重 35–200 kg、BMI 18.5 至不足 40，身高体重在 30 天内记录。所有既有健康筛查字段必须已知；疾病、用药、孕哺、进食障碍或营养不良风险、已有专业饮食计划均不走自动时窗安排。范围是本产品保守边界，不是临床研究证明的通用禁忌阈值。已知过敏本身不修改时窗，但原餐食的配料核实仍须完成；时间功能不认证任何食品。

成功时返回 `schedule`：

```json
{
  "pattern": "16:8",
  "eating_minutes": 480,
  "fasting_minutes": 960,
  "start": {"time": "09:00", "day_offset": 0},
  "end": {"time": "17:00", "day_offset": 0},
  "wake": {"time": "07:00", "day_offset": 0},
  "sleep": {"time": "23:00", "day_offset": 0},
  "meal_times": [
    {"time": "09:00", "day_offset": 0},
    {"time": "13:00", "day_offset": 0},
    {"time": "16:30", "day_offset": 0}
  ],
  "clock_basis": "user_local_wall_clock",
  "valid_for": "2026-10-06",
  "automatically_repeats": false,
  "work_pattern": "day"
}
```

`as_of` 是起床发生的当地日历日。跨午夜时 `day_offset=1` 是下一日；例如 20:00 起床、09:00 入睡、22:00 开始的 16:8 时窗结束于下一日 06:00。若开始时间为 00:30，则对应起床后的下一日 00:30。三餐时间是可移动的组织示例，不是必须准点或必须吃三次的医嘱。这里只安排当地钟表时间，不启动计时器或通知，不承诺跨时区/夏令时当天的实际经过分钟数。

轮班只对当前作息返回一次方案，不自动套用昨天时窗。所有模式都维持原有全天食物、能量、蛋白质和饮水，不再扣一餐或扣热量；若无法安排足够餐点、加餐或配合训练，则继续常规进餐。

| status / action | 用户下一步 |
|---|---|
| `ok / optional_eating_window` | 可选择该时窗，保持全天营养安排 |
| `needs_information / keep_regular_meals` | 先按常规吃，补齐 `missing_fields`，不能代填 |
| `not_enabled / keep_regular_meals` | 未选择、范围不符或无法吃够；保持常规进餐 |
| `conflict / choose_feasible_window_or_regular_meals` | 时长不匹配或跨入睡眠；改时间或继续常规进餐 |
| `stopped / stop_and_resume_regular_meals` | 停止限制进餐时间、恢复常规进食并评估不适 |

任何当前不适或既往因不适停止都会优先返回 `stopped`，即使其他资料缺失。`restart_allowed=false` 表示本模块不执行“因症状停用后的重新启用”。宿主须保留停用事实并在后续调用中忠实传回；不能用一条新的“想继续”擦去历史。严重症状应立即就医，不以完成时窗为目标拖延处理。该函数是无状态的决定函数，调用者抹掉或伪造历史无法被它自行发现。

## 普通食物文化做法

`traditional_foods(profile, as_of, request)` 接收：

```json
{
  "opt_in": true,
  "purpose": "ordinary_food",
  "method": "porridge",
  "exclude_food_ids": []
}
```

`purpose` 允许 `ordinary_food/treatment/constitution/herbal`。只有明确选择普通食物模式、资料完整、没有需要沿用专业要求的情况时，才给食材做法。其余模式返回 `education_only`，不会辨体质、生成药材剂量或把普通食品宣传为治疗。

| method | 实际做法 | 来源状态 |
|---|---|---|
| `porridge` | 原味燕麦粥，配原餐单水煮蛋 | 燕麦 `usda:173904` 按干重，鸡蛋 `usda:173424` 按熟可食部分 |
| `boil` | 水煮西兰花和胡萝卜，作为原餐单配菜 | `usda:169967`、`usda:170394` 按无盐水煮沥干状态 |
| `steam` | 将原餐单熟米饭与熟胡萝卜蒸热，配水煮蛋 | `usda:169757`、`usda:170394` 指对应熟食输入状态，鸡蛋仍是水煮蛋 |

成功结果 `recommendations` 含做法 ID、中文标题、食物 ID/重量基准和三个步骤。份量只能来自既有餐单，`portion_source=existing_meal_plan_only`；本接口不新增克数、不算整碗粥、不把煮熟与蒸熟营养值直接等同。`nutrition_calculation=not_calculated`、`ingredients_verified=false`、`clinical_claims=[]` 明确保留边界。这些做法不能独立证明一餐或全天营养充足。

`exclude_food_ids` 和已知不喜欢的食物会引起 `conflict`，提示换另一普通做法，不默默塞回去。过敏未知或已知过敏但配料/交叉接触尚未核实，会返回 `needs_information` 且没有个人食材推荐。普通食物并不自动等于过敏安全。

## 证据与复用选择

- [Johns Hopkins：间歇性断食说明，2026-04-07 更新](https://www.hopkinsmedicine.org/health/expert-qa/intermittent-fasting-what-is-it-and-how-does-it-work)：提供 16/8 的时间含义，提醒孕哺、进食障碍史及相关糖尿病情形不宜自行采用，并提示不适时咨询。这里采用更窄的产品准入与直接退出规则；12/12、14/10 不标作已证实优于常规饮食的方案。
- [Johns Hopkins：2026-09-14 研究报道](https://www.hopkinsmedicine.org/news/newsroom/news-releases/2026/09/time-restricted-eating-provides-modest-weight-loss-benefits-for-adults-with-obesity-and-prediabetes)：该特定研究的 10 小时限时进餐组和常规组都发生有限减重，不能据此保证独特全身健康获益，也不把研究人群扩成自动糖尿病饮食处方。
- [NCCIH：Traditional Chinese Medicine](https://www.nccih.nih.gov/health/traditional-chinese-medicine-what-you-need-to-know)：不同方法的证据并不一致，药材制品存在质量与安全问题，不应替代或延误常规诊疗。本模块仅用普通食物与文化烹调偏好，NCCIH 页面不构成三种菜式的临床疗效证据。
- [T1113/16-8-fasting-tracker](https://github.com/T1113/16-8-fasting-tracker)：已检索其 MIT、无依赖 Python、多端共享时窗做法。它是计时器，未满足本项目未知健康资料、症状退出、营养量不变和无状态契约，因此复用既有 Python 校验/Decimal 工具实现小范围决定函数，不引入计时器、通知服务或其他包，也没有复制第三方代码。

来源核对日：2026-10-06。运行 `python3 -m unittest discover -s tests -p test_strategies.py -v`，验证启用/未知/退出、夜班跨日、睡眠冲突、输入隔离、真实食物 ID、过敏和非处方边界。测试证明实现的这些行为，不证明临床疗效、真实用户长期依从性或宿主调用时忠实保留历史。
