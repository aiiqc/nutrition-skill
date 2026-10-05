# USDA 五食物离线样本来源

本目录仅含 5 条真实 USDA FoodData Central 食物记录，用于 M1–M2 的数据契约、份量换算和核心计算验证。它不代表完整中式、西式菜谱或外食目录，也不能由这 5 条记录证明医疗饮食或过敏安全。数据采集日为 **2026-10-05（UTC）**。

运行时只读本地 `nutrition_core/data/usda-five-foods.json`，不联网、不需要 API key。`nutrition_core/data/source-responses/` 保存此次获取的原始响应字节，使下表的 SHA256 可离线复核；它不是另一套运行时目录。原始来源响应保留上游 JSON 数字写法，归一化目录则用十进制字符串保存数值。

## 来源与许可

来源为 [USDA FoodData Central 官方 API](https://fdc.nal.usda.gov/api-guide/) 的 Food Details 端点，使用官方公开示范凭证 `DEMO_KEY`，仅请求下表 5 个 ID，每个请求设置 30 秒超时、响应大小上限 2 MB，无自动重试。未使用或保存私人凭据。源链接和目录中不包含查询参数或 API 凭据。

USDA 在 API 指南中将 FDC 数据置于公共领域并按 **CC0 1.0** 提供。这 5 条原始响应和基于它们整理的归一化数据可按 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) 使用和再分发；USDA 请求注明来源，本说明及每条 `source` 已保留署名。代码许可与食品数据许可分开；本包没有混入 Open Food Facts、TFDA 或其他数据库资料。许可说明不是对任意其他来源的法律结论。

营养含义参考 [Foundation Foods Documentation](https://fdc.nal.usda.gov/Foundation_Foods_Documentation/) 和 [FoodData Central 数据类型说明](https://fdc.nal.usda.gov/data-documentation/)。`reported` 表示来源报告了该数值，不等同于全部是实测值；分析、计算和假定零的来源依据另外保留。

## 本次快照

| FDC ID / 官方记录 | 发布日期 | 数据类型 / 生熟状态 | 选定能量，kcal / 100 g |
|---|---|---|---:|
| [171077 生去皮去骨鸡胸](https://fdc.nal.usda.gov/food-details/171077/nutrients) | 2019-04-01 | SR Legacy / raw | 120，营养 ID 1008 |
| [171477 烤熟鸡胸肉](https://fdc.nal.usda.gov/food-details/171477/nutrients) | 2019-04-01 | SR Legacy / cooked | 165，营养 ID 1008 |
| [2512381 生长粒白米](https://fdc.nal.usda.gov/food-details/2512381/nutrients) | 2023-04-20 | Foundation / raw | 369.637321，2048 Atwater specific |
| [169757 无盐熟白米饭](https://fdc.nal.usda.gov/food-details/169757/nutrients) | 2019-04-01 | SR Legacy / cooked | 130，营养 ID 1008 |
| [330137 原味脱脂希腊酸奶](https://fdc.nal.usda.gov/food-details/330137/nutrients) | 2019-04-01 | Foundation / processed | 61，营养 ID 1008 |

发布时间是 USDA 记录的 `publicationDate`，不等于样本采集日或本次查询日。生熟鸡胸及生熟米是各自独立来源记录，不是同一批食物烹调前后的配对数据；不从它们推导烹调失水比例。

| 原始响应文件 | SHA256 |
|---|---|
| `171077.json` | `2769a87322b6ddb2bc7ceb6b450bc440055cf85dbde9d17b4118db49f525de7c` |
| `171477.json` | `8622491a1759d96b371d087e9d75fa1efc60f45c1b3a7a8c93434944a7e6e7fa` |
| `2512381.json` | `5379f31ce8989845cc56034ccbea9d99942f1334c6c5828d7e8eb9ebac832f3a` |
| `169757.json` | `d51327b8af6d7d4acb8579118aadecb72cef1e56e040bf5730eb6e8ddb625639` |
| `330137.json` | `93ffa33e41d0aca4dba57569efa2d852a165f9d5831f6aa69d4c515ae7e80990` |

以后再次获取同一个 ID 可能得到不同字节或更新后的资料；新响应必须重新记录日期、哈希并审核差异，不能改写本次快照的证据。

## 归一化规则与关键差异

每条食物的固定营养字段为能量、蛋白质、碳水、脂肪、纤维、钠、钾、磷，基准一律是 **每 100 g 可食部分**。ID 对应为 1008/2048、1003、1005、1004、1079、1093、1092、1091，单位分别为 kcal、g、g、g、g、mg、mg、mg。原始营养 ID、名称、来源数值/单位、派生代码、统计值、样本数及子样本的必要证据保存在 `evidence`；没有这些元数据时不补造。

- 生米主能量明确选用 **2048 Atwater specific = 369.637321 kcal**；2047 Atwater general = 358.705 kcal 保留在 `energy_alternatives`。其他 4 条主能量选择 1008。来源中若有 1062 kJ，也作为独立备选值保留，不参与 kcal 合计。`usda_1008` 只标识所选来源字段，不假定所有 1008 都使用相同 Atwater 方法。能量不相加，也不按 4/9/4 重算覆盖上游。
- 两条鸡胸的碳水与纤维保留来源 `Z / Assumed zero`，状态为 `assumed_zero`，数值为 `"0"`。这是来源假定零，不是检测确认零。
- 酸奶没有 1079 纤维条目，状态为 `missing`，数值为 `null`；不能补成零。
- 生米纤维的来源汇总值为 **0.1488 g**、汇总层 LOQ 字段为 **0.75 g**；8 个子样本中 7 个来源数值为 0 且有 LOQ，1 个为 1.19 g。钠的来源汇总值为 **0.4625 mg**、汇总层 LOQ 字段为 **2.5 mg**；同样有 7 个来源零加 LOQ 的子样本，另一个报告 3.7 mg。汇总保持 `status=reported`、`evidence.scope=aggregate`，子样本各自保留 `scope=sub_sample`、来源 amount、LOQ 和 `below_loq/reported` 状态。不得把整个汇总值直接改成“小于 LOQ”，也不得把这些子样本的来源零当作精确零。硬限制校验需表达受 LOQ 影响的精度不足。
- `below_loq` 作为主营养状态时要求单样本 LOQ 证据，精确 `amount` 为 `null`。本目录 5 条记录没有这种主营养状态；该分支仅通过明确标注的合成测试验证。
- 所有 USDA 样本 `allergens.assessment=unknown`。空 `contains`/`may_contain` 列表只表示这里没有录入经核实的成分与交叉接触判断。9 个支持的过敏原 ID 是本阶段输入词表，不是完整过敏原库。

## 份量和换算边界

目录只使用该记录的 `foodPortions`，以其来源 ID 建立 `usda:<portion ID>`。**一次 portion 是来源 label 描述的整个量**，`grams` 直接对应来源 `gramWeight`：例如生鸡胸 `usda:87919` 是 **4 oz 共 113 g**，烤鸡胸 `usda:88819` 是 **半个去骨去皮鸡胸共 86 g**；不是单个 oz 或一整个鸡胸的克数。

熟米 `usda:85462` 的来源为 1 cup = 158 g，只有明确选择这个份量 ID 才可换算。它不能自动等同“一碗”；酸奶 156 g container 不能推到任意包装；生米 45 g RACC 不是推荐摄入量或用户常用饭碗。

直接单位只支持 g/kg/mg，数量必须大于零；明确未吃由计划模块的 `not_eaten` 表示，不通过 0 g 条目冒充进食记录。ml 必须有该食物独立、非空来源的 `density.grams_per_ml`，本目录没有任何密度，所以 5 个食物直接输入 ml 会要求补充资料。cup、bowl、oz、container 等裸单位会被拒绝；需要选择实际来源 portion。

## 本地校验接口与证据范围

`load_catalog(path=None)` 读取默认或指定的本地 UTF-8 JSON，拒绝重复 JSON 键、JSON 小数/非有限数字、超出 4 MB 的目录和非法结构。归一化营养数值必须为十进制字符串，缺失为 null。`validate_catalog(catalog)` 校验内存对象并返回原对象，不修改它；空 `foods` 允许。`get_food(catalog, food_id)` 先校验整个目录，再返回目标记录的独立副本。`quantity_to_grams(food, quantity)` 再校验食物和数量，使用独立 precision=80 Decimal 上下文返回克数。

食物与来源的固定字段、状态/数值关系、单位、份量、SHA256 形状、ISO 日期、能量方法和过敏原 ID 都经过结构校验。通过结构校验不等于重新审计了来源真实性、完整配料或医学适用性；调用者提供的 `verified` 字样仍需外部证据，程序不能凭文字制造认证。

在项目根目录执行 `python3 -m unittest discover -s tests -p test_catalog.py -v` 可离线核对上述来源字节与核心数据不变量、单位与份量换算、LOQ 层次、非法输入和上下文隔离。这证明这份本地快照和实现的相应行为，不证明整库质量、营养建议的临床有效性、真实用户流程或任何宿主兼容性。
