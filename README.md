# Nutrition Skill

[![CI](https://github.com/aiiqc/nutrition-skill/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aiiqc/nutrition-skill/actions/workflows/ci.yml)

一次建档，每天知道怎么吃，每周根据反馈调整。面向中文日常使用的开源 Agent Skill，也提供可供未来 App 复用的 Python / JSON 核心。自有代码 MIT、食物资料 USDA CC0；无需 API Key 或第三方运行依赖。

`0.3.0` 首版功能包括适用一般成人的目标估算、带克数的中西餐与懒人菜单、换餐及锁定保护、实际饮食记录、有限周调整、可选进食时间安排、普通食材传统做法，以及长期本地档案。营养计算和健康效果是不同的证据：本项目没有医学认证或临床效果验证。[产品规格](docs/product-spec.md)保留完整范围，[验收记录](docs/verification.md)逐层列出实际结果。

## 开始使用

将**完整项目**按[安装说明](docs/installation.md)放入宿主发现的 Skill 目录。Codex 项目安装位置为 `.agents/skills/nutrition-skill`；主入口 [SKILL.md](SKILL.md)。安装后可以直接说：

> 我想慢慢减脂，偏好中式、尽量简单。先帮我建档，再告诉我下一餐怎么吃。

助手会逐步补齐必要资料；不会从姓名、照片或缺失回答推断健康状况。支持仅本次使用，或将最小档案保存在源码之外。个人目标、专业要求和家庭成员各自保留。

也可直接从源码运行，需要 Python 3.11+：

```sh
python3 -B scripts/product_demo.py
python3 -B -m nutrition_core --input examples/calculate.json
python3 -B -m unittest discover -s tests -v
```

第一条用虚构人物实际完成目标、三餐、换餐、实吃、14天反馈、调整后菜单、标签计算、策略与保存／归档／读取／导出，临时档案随后清除。它展示软件流程，不是给读者的饮食处方。

## 已实现的使用流程

| 需求 | 实际行为 |
|---|---|
| 减脂、增肌、健康饮食 | 自报资料适用时，以 NASEM 2023 成人能量方程估算；初始偏移和有限调整明确标为产品默认，不冒充研究定论 |
| 今天三餐怎么吃 | 17个自有份量组合、30条有原始来源的食品；求解食材量并在舍入后核对全天能量和蛋白范围，可附明确额外限制 |
| 中式、西式、懒人、免烹饪 | 按菜式、厨具、准备时间、经济型食材及现有食材筛选；可选2–4餐、调整分配 |
| 食材缺货、固定早餐 | 只改指定未来餐次；保留锁定餐、其他餐及已吃记录，换后重新核对全天 |
| 外卖、照片、包装标签 | 外卖未知配方用餐食结构与粗记；图片由宿主提出待确认候选；标签按确认的每份／每100g基准计算，不把缺项当零 |
| 每周反馈 | 信息不足时改善执行；具备可比14天观察且满足规则时生成有限调整，风险信号暂停，断档不补偿性少吃 |
| 断食与传统食物 | 用户明确选择后核对12:12／14:10／16:8作息；不适停止；传统做法只涉及普通食材，不辨证或开药 |
| 家庭备餐 | 菜式可以共用，个人目标、份量和记录分开；采购汇总可食重量，不凭人数放大个人目标 |
| 长期档案 | 显式开启分段历史，保留旧版本；按明确日期归档活动记录，可分页导出或删除准确成员 |

已列计划不等于实际吃过；满足能量和蛋白范围也不等于全部营养、配料或医学适用性均获核验。30条数据覆盖常见基础食材，不是全食品或餐厅品牌库。生熟、份量、未知营养和来源信息贯穿输出。

## 给开发者

核心可独立运行，不依赖语言模型：

```python
from nutrition_core.targets import derive_targets
from nutrition_core.meal_planning import generate_day_plan

# profile / inputs 来自用户明确确认的结构化资料；可参考 scripts/product_demo.py。
# target = derive_targets(profile, inputs, "2026-10-06")
# result = generate_day_plan(profile, target, "2026-10-06")
```

查看全部操作：

```sh
python3 -B -m nutrition_core <<'JSON'
{"operation":"describe"}
JSON
```

- [个人目标与周调整](docs/nutrition-rules.md)、[定量餐单与标签](docs/meal-planning.md)、[进食时间与传统做法](docs/strategies.md)
- [档案及日常流程契约](docs/m3-contracts.md)、[数值和餐次契约](docs/contracts.md)、[长期存储](docs/storage-evolution.md)
- [数据来源](docs/data-provenance.md)、[贡献方式](CONTRIBUTING.md)、[可自助复现的试用指南](docs/developer-pilot.md)
- [发布记录](docs/release-readiness.md)、[分层验收](docs/verification.md)

CLI 从标准输入读取 JSON，输出结构化结果。十进制数使用字符串，`status`、`complete`、范围与缺项必须分别处理。Python wheel 仅安装核心；安装 Skill 请下载完整源码。现有 M2/M3 接口保留，长期 v3 档案需要新版读取器。

## 适用范围与数据控制

自动目标采用保守的一般成人产品范围，具体年龄、BMI、测量时效等见[规则](docs/nutrition-rules.md)。疾病、用药、孕哺、未成年、进食障碍等进入适用的资料整理或专业要求支持路径，不生成通用治疗处方。过敏成分及交叉接触未知时不会称安全。

核心和 CLI 离线运行，不记录原始输入日志。只有显式档案操作会写入用户选择的目录；不会保存原始聊天、图片或报告。模型宿主仍可能接收和保留对话，因此整个 Skill 不能宣称零留存。

档案要求本地 POSIX 私有目录，已测试范围见验收记录。没有加密、跨设备同步或同一系统账号内的家庭成员访问隔离。长期分段没有50次总修订限制，但每文件与活动文档仍有明确容量；不静默删除历史。删除不能控制宿主聊天、外部导出或备份。

项目使用 [MIT](LICENSE)，支持商业和闭源下游复用；[第三方声明](THIRD-PARTY-NOTICES.md)说明数据义务。wger 等开源项目用于设计比较，没有引入其 AGPL 应用代码或服务依赖。后续食品、宿主和专业审阅扩展属于持续维护，不改变当前首版已实现的功能范围。
