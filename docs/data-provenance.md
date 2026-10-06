# USDA 日常食物离线目录来源

本目录含 **30 条真实 USDA FoodData Central 食物记录**：2026-10-05 获取的原始 5 条保留原样，2026-10-06 新增 25 条日常食材。它覆盖主食、蛋白质食物、乳品、豆类、蔬菜、水果和油脂，供中式、西式与懒人组合使用；不是完整菜谱或餐厅数据库，也不证明医疗饮食或过敏安全。所有日期按 UTC 记录。

运行时只读本地 `nutrition_core/data/usda-five-foods.json`，不联网、不需要 API key。`nutrition_core/data/source-responses/` 保存原始来源记录，使下表的 SHA256 可离线复核；它不是另一套运行时目录。API 条目保留完整响应字节，官方整档条目保留档案中对应 JSON 对象的原文字节（不是整个下载文件）。两者都保留上游 JSON 数字写法，归一化目录则用十进制字符串保存数值。文件名为兼容既有加载路径而保留，不再表示只有五条。

## 来源与许可

原始 5 条来源为 [USDA FoodData Central 官方 API](https://fdc.nal.usda.gov/api-guide/) 的 Food Details 端点。新增记录先从 [官方 SR Legacy 2018-04 JSON 下载档案](https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_json_2018-04.zip) 定位准确 ID 和描述，再请求详情。使用官方公开示范凭证 `DEMO_KEY`，25 个有界 GET 中 11 个成功，其余遇到 429；未重试、未换凭据，直接采用此前已下载的官方档案中对应的 14 个完整记录。每个详情请求连接超时 5 秒、总时限 35 秒、响应大小上限 2 MB；下载档案总时限 90 秒、大小上限 20 MB。未使用或保存私人凭据。源链接和目录中不包含查询参数或 API 凭据。

USDA 在 API 指南中将 FDC 数据置于公共领域并按 **CC0 1.0** 提供。这 30 条原始来源记录和基于它们整理的归一化数据可按 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) 使用和再分发；USDA 请求注明来源，本说明及每条 `source` 已保留署名。代码许可与食品数据许可分开；本包没有混入 Open Food Facts、TFDA 或其他数据库资料。许可说明不是对任意其他来源的法律结论。

营养含义参考 [Foundation Foods Documentation](https://fdc.nal.usda.gov/Foundation_Foods_Documentation/) 和 [FoodData Central 数据类型说明](https://fdc.nal.usda.gov/data-documentation/)。`reported` 表示来源报告了该数值，不等同于全部是实测值；分析、计算和假定零的来源依据另外保留。

## 原始五条快照

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

## 日常食物扩充快照

新增 25 条全部为 **SR Legacy**，官方 `publicationDate` 为 **2019-04-01**；下载包标为 2018-04 是 SR Legacy 发布批次，不能把它误写成记录的 `publicationDate`。新增来源记录获取日为 **2026-10-06**。表内能量单位均为 kcal / 100 g 可食部分，选用营养 ID 1008，保留原始派生代码和其他能量值。

| FDC ID / 精确食物范围 | 状态 | 主能量 | 保存来源 |
|---|---|---:|---|
| [173904 普通/快熟未强化干燕麦](https://fdc.nal.usda.gov/food-details/173904/nutrients) | raw | 379 | API 响应 |
| [173424 水煮熟全蛋](https://fdc.nal.usda.gov/food-details/173424/nutrients) | cooked | 155 | API 响应 |
| [172448 硫酸钙与卤水凝固硬豆腐](https://fdc.nal.usda.gov/food-details/172448/nutrients) | processed | 78 | API 响应 |
| [172421 无盐煮熟小扁豆](https://fdc.nal.usda.gov/food-details/172421/nutrients) | cooked | 116 | API 响应 |
| [173735 无盐煮熟黑芸豆](https://fdc.nal.usda.gov/food-details/173735/nutrients) | cooked | 132 | API 响应 |
| [171267 2%脂肪牛奶（添加维生素A和D）](https://fdc.nal.usda.gov/food-details/171267/nutrients) | processed | 50 | API 响应 |
| [172688 商业制作全麦面包](https://fdc.nal.usda.gov/food-details/172688/nutrients) | processed | 252 | API 响应 |
| [168928 无盐未强化熟意大利面](https://fdc.nal.usda.gov/food-details/168928/nutrients) | cooked | 158 | API 响应 |
| [170440 去皮无盐水煮土豆](https://fdc.nal.usda.gov/food-details/170440/nutrients) | cooked | 86 | API 响应 |
| [175168 干热熟制养殖大西洋鲑](https://fdc.nal.usda.gov/food-details/175168/nutrients) | cooked | 206 | API 响应 |
| [171413 橄榄油](https://fdc.nal.usda.gov/food-details/171413/nutrients) | processed | 884 | 官方档案对象 |
| [170158 无盐干烤巴旦木（扁桃仁）](https://fdc.nal.usda.gov/food-details/170158/nutrients) | processed | 598 | API 响应 |
| [173944 生香蕉（可食部分）](https://fdc.nal.usda.gov/food-details/173944/nutrients) | raw | 89 | 官方档案对象 |
| [171688 带皮生苹果（可食部分）](https://fdc.nal.usda.gov/food-details/171688/nutrients) | raw | 52 | 官方档案对象 |
| [169967 无盐水煮沥干西兰花](https://fdc.nal.usda.gov/food-details/169967/nutrients) | cooked | 35 | 官方档案对象 |
| [170394 无盐水煮沥干胡萝卜](https://fdc.nal.usda.gov/food-details/170394/nutrients) | cooked | 35 | 官方档案对象 |
| [168463 无盐水煮沥干菠菜](https://fdc.nal.usda.gov/food-details/168463/nutrients) | cooked | 23 | 官方档案对象 |
| [170420 无盐水煮沥干豌豆](https://fdc.nal.usda.gov/food-details/170420/nutrients) | cooked | 84 | 官方档案对象 |
| [170457 生红番茄](https://fdc.nal.usda.gov/food-details/170457/nutrients) | raw | 18 | 官方档案对象 |
| [168409 带皮生黄瓜](https://fdc.nal.usda.gov/food-details/168409/nutrients) | raw | 15 | 官方档案对象 |
| [169252 无盐水煮沥干白蘑菇](https://fdc.nal.usda.gov/food-details/169252/nutrients) | cooked | 28 | 官方档案对象 |
| [168484 去皮水煮红薯](https://fdc.nal.usda.gov/food-details/168484/nutrients) | cooked | 76 | 官方档案对象 |
| [169283 无盐煮熟沥干青大豆](https://fdc.nal.usda.gov/food-details/169283/nutrients) | cooked | 141 | 官方档案对象 |
| [171284 原味全脂酸奶](https://fdc.nal.usda.gov/food-details/171284/nutrients) | processed | 61 | 官方档案对象 |
| [169097 生橙（可食部分）](https://fdc.nal.usda.gov/food-details/169097/nutrients) | raw | 47 | 官方档案对象 |

官方档案的可复现锚点：

- 文件 `FoodData_Central_sr_legacy_food_json_2018-04.zip`，13,456,312 字节；SHA256 `0fe8ae486a2c8eb42cb96413f058deb51863a46c8fb8eeb4b1fb45006dd338ef`。
- 内档 `FoodData_Central_sr_legacy_food_json_2018-04.json`，210,758,826 字节；SHA256 `70d4235ae3a2bdf48a7b9eaa1286a83fa67b6f3270436c9ce8b008213f500129`。
- 在 JSON 数组中按 `fdcId` 找到记录，保留从其开 `{` 到闭 `}` 的完整原文字节，不重新序列化；下表哈希对应保存的对象，不是完整下载响应。软件包仅分发选定对象，不包含 210 MB 整档。

| 新增来源文件 | SHA256 |
|---|---|
| `173904.json` | `895a32c1c48916ac3a07ddd1b7860e7f9a4e7d8b25560c1698e75182a3fb2f15` |
| `173424.json` | `8be047fdca236bf4495a2e465fc292428ce0d766a35f3ad961974fa1475c0629` |
| `172448.json` | `63383d08fa996926e8381bd0e00e860f410f516c013ee92fb8567e13a0ad621d` |
| `172421.json` | `2c20c19a32cf921f7d5a29b34467bcc5723e4a7a95d685cbc11edfee35bd4307` |
| `173735.json` | `dada61a807b2071b86e44dacbef540b9841afd75252f178f2c57527867df5dae` |
| `171267.json` | `54587021b5469189a2d35d4900748b5e9d7664c415477ab8620cf645a679644a` |
| `172688.json` | `8dd0ea91560ea4115b52cc1cda1c08e56d1cedea1ab91d218f2a7625a28894f2` |
| `168928.json` | `fe272c1fb9bd670cad64b8495bebdc63c793a6da67ab1a3abe1a458a3b58679c` |
| `170440.json` | `a705a87252a95f4390756ea7a60807b4de005d9453f84db67079a44345547e17` |
| `175168.json` | `63026b81ec735e188e5187c186994d167dfe49b290550309820cc24c517f3678` |
| `171413.json` | `d8069208067752bfdd0aa01d1bc3689c6017bea827ca2bbd9a0c2d1ac594cb1f` |
| `170158.json` | `ce62c625f1758793a93a2d269cd86eaf6d2b9e24e8add3649de1f4f9f198f05f` |
| `173944.json` | `0560cf4300cf614fddaad217644bb93c8d7824c9379f4b4959afa356111cbf97` |
| `171688.json` | `a3bad2e84eb59f63f542844cb9447f58ede21ea6bd60cde26d20287f329f220c` |
| `169967.json` | `b61e9b04194e2bdea01473528aa51361935f113aef6be4a5ac1ccaaed9ca36d8` |
| `170394.json` | `1a30a4174244480a1999d160475059a751ab767b46f7bf87813b29b8121c3408` |
| `168463.json` | `0137c9e569f1fa61fb01461e5df8925dc52333a53867eb0bb50d943c8ba5526a` |
| `170420.json` | `b5eccc42218e3a2b0a91e357fba319f9ded37048f0bc30969cb382bf4792ced4` |
| `170457.json` | `99ec481dfb1b1ca565564287be378b33c4ec980cfd5cc9f9e4a5211e971c5e93` |
| `168409.json` | `4ae41920a37b5604c3a97ce604076eed47464a878900067208a2fefc31de7d59` |
| `169252.json` | `b4e0376df2902b943951b2cb4ff50114bc9d7e44899c158195fac33a123cb660` |
| `168484.json` | `2eaa91fe4731ee1ff94bfe635012c999157d063adfb384a5351ec0664b3cd4b9` |
| `169283.json` | `b90d55119e9843b58e9806e40cb06f65f723dceea7f5e16d44a00943f0259f5c` |
| `171284.json` | `c5af75b5416d5d03ff85bf811cae846df2a43ed8badb1c97719a3cc7f4b8fd62` |
| `169097.json` | `d95d4741cab4ab29b6f91062b4f4769e73e81260b476fcf8e21bfe3c80b3da38` |

### 食物选择元数据

`nutrition_core/data/food-choices.json` 为项目自行整理的中文名称、简繁/英文检索词、食物类别、餐次用途、准备方式与来源份量 ID 索引，按项目 MIT 许可分发；它不新增营养值。`category` 仅用于菜单组合，固定为 `grain/protein/dairy/legume/vegetable/fruit/fat`。例如土豆和红薯归入主食，豌豆归入豆类；这些是产品分类，不是 USDA 食品类别翻译。`budget=ordinary` 是粗略使用场景标签，不承诺当地价格。`preparation` 是使用前需要的准备方式，不代表烹调时长、食物保存期限或加热后重量换算。

`portion_ids` 只指向同一条 USDA 记录已经提供的份量，实际 label 与克数以营养目录为准。中文别名帮助查找，但不会把不同生熟状态、品牌、凝固剂或乳脂含量自动视为等价。燕麦按干重，水果按可食部分；鸡胸、意面、米饭和熟蔬菜按条目指定状态。硬豆腐 172448 是特定凝固剂的加工豆腐，不能套用其他豆腐的营养值；牛奶 171267 是 2% 脂肪且添加维生素 A/D 的特定参考，不能替代植物饮品或把 ml 当作 g。黑芸豆（black beans）与黑大豆、扁桃仁（almonds）与杏核仁分别处理，不用常见但歧义的“黑豆”“杏仁”直接匹配。未核实的外食仍只能给定性方案。

本轮复用选择核对了 [USDA 官方 issue #102](https://github.com/USDA/USDA-APIs/issues/102) 的搜索/详情 schema 差异及 [metonym/fooddata-central](https://github.com/metonym/fooddata-central) 的详情客户端。继续采用本项目既有无依赖 Decimal 归一化器和官方详情/下载记录，不引入 Node 客户端、数据库服务或第三方营养数据；不把搜索摘要当作完整营养来源。

## 归一化规则与关键差异

每条食物的固定营养字段为能量、蛋白质、碳水、脂肪、纤维、钠、钾、磷，基准一律是 **每 100 g 可食部分**。ID 对应为 1008/2048、1003、1005、1004、1079、1093、1092、1091，单位分别为 kcal、g、g、g、g、mg、mg、mg。原始营养 ID、名称、来源数值/单位、派生代码、统计值、样本数及子样本的必要证据保存在 `evidence`；没有这些元数据时不补造。

- 生米主能量明确选用 **2048 Atwater specific = 369.637321 kcal**；2047 Atwater general = 358.705 kcal 保留在 `energy_alternatives`。其余 29 条主能量选择 1008。来源中若有 1062 kJ，也作为独立备选值保留，不参与 kcal 合计。`usda_1008` 只标识所选来源字段，不假定所有 1008 都使用相同 Atwater 方法。能量不相加，也不按 4/9/4 重算覆盖上游。
- 两条鸡胸的碳水与纤维保留来源 `Z / Assumed zero`，状态为 `assumed_zero`，数值为 `"0"`。这是来源假定零，不是检测确认零。
- 酸奶没有 1079 纤维条目，状态为 `missing`，数值为 `null`；不能补成零。
- 生米纤维的来源汇总值为 **0.1488 g**、汇总层 LOQ 字段为 **0.75 g**；8 个子样本中 7 个来源数值为 0 且有 LOQ，1 个为 1.19 g。钠的来源汇总值为 **0.4625 mg**、汇总层 LOQ 字段为 **2.5 mg**；同样有 7 个来源零加 LOQ 的子样本，另一个报告 3.7 mg。汇总保持 `status=reported`、`evidence.scope=aggregate`，子样本各自保留 `scope=sub_sample`、来源 amount、LOQ 和 `below_loq/reported` 状态。不得把整个汇总值直接改成“小于 LOQ”，也不得把这些子样本的来源零当作精确零。硬限制校验需表达受 LOQ 影响的精度不足。
- `below_loq` 作为主营养状态时要求单样本 LOQ 证据，精确 `amount` 为 `null`。本目录 30 条记录没有这种主营养状态；该分支仅通过明确标注的合成测试验证。
- 所有 USDA 样本 `allergens.assessment=unknown`。空 `contains`/`may_contain` 列表只表示这里没有录入经核实的成分与交叉接触判断。9 个支持的过敏原 ID 是本阶段输入词表，不是完整过敏原库。

## 份量和换算边界

目录只使用该记录的 `foodPortions`，以其来源 ID 建立 `usda:<portion ID>`。**一次 portion 是来源 label 描述的整个量**，`grams` 直接对应来源 `gramWeight`：例如生鸡胸 `usda:87919` 是 **4 oz 共 113 g**，烤鸡胸 `usda:88819` 是 **半个去骨去皮鸡胸共 86 g**；不是单个 oz 或一整个鸡胸的克数。

熟米 `usda:85462` 的来源为 1 cup = 158 g，只有明确选择这个份量 ID 才可换算。它不能自动等同“一碗”；酸奶 156 g container 不能推到任意包装；生米 45 g RACC 不是推荐摄入量或用户常用饭碗。

直接单位只支持 g/kg/mg，数量必须大于零；明确未吃由计划模块的 `not_eaten` 表示，不通过 0 g 条目冒充进食记录。ml 必须有该食物独立、非空来源的 `density.grams_per_ml`，本目录没有任何密度，所以这 30 个食物直接输入 ml 都会要求补充资料。cup、bowl、oz、container 等裸单位会被拒绝；需要选择实际来源 portion。

## 本地校验接口与证据范围

`load_catalog(path=None)` 读取默认或指定的本地 UTF-8 JSON，拒绝重复 JSON 键、JSON 小数/非有限数字、超出 4 MB 的目录和非法结构。归一化营养数值必须为十进制字符串，缺失为 null。`validate_catalog(catalog)` 校验内存对象并返回原对象，不修改它；空 `foods` 允许。`get_food(catalog, food_id)` 先校验整个目录，再返回目标记录的独立副本。`quantity_to_grams(food, quantity)` 再校验食物和数量，使用独立 precision=80 Decimal 上下文返回克数。

食物与来源的固定字段、状态/数值关系、单位、份量、SHA256 形状、ISO 日期、能量方法和过敏原 ID 都经过结构校验。通过结构校验不等于重新审计了来源真实性、完整配料或医学适用性；调用者提供的 `verified` 字样仍需外部证据，程序不能凭文字制造认证。

在项目根目录执行 `python3 -m unittest discover -s tests -p 'test_catalog*.py' -v` 可离线核对上述来源字节与核心数据不变量、单位与份量换算、LOQ 层次、非法输入和上下文隔离。这证明这份本地快照和实现的相应行为，不证明整库质量、营养建议的临床有效性、真实用户流程或任何宿主兼容性。
