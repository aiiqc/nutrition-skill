# Nutrition Skill

[![CI](https://github.com/aiiqc/nutrition-skill/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aiiqc/nutrition-skill/actions/workflows/ci.yml)

可供智能助手使用、也可被未来 App 复用的饮食 Skill 与独立计算核心。当前工作副本为 `0.2.0.dev2` 本地候选，新增按调用者给定目标核对全天计划；GitHub已公开版本仍为 `0.2.0.dev1`。M0–M3已通过当前启用范围的验收；各版本证据和边界见验收记录。

完整产品方向见 [唯一产品规格](docs/product-spec.md)。主入口为[SKILL.md](SKILL.md)，按[Agent Skills格式](https://agentskills.io/specification)组织。精确食品库目前只有五条资料；中西餐建议是项目自编的餐食结构，明确标为qualitative_only，不表示已满足个人热量或临床目标。

首次试用见[项目内安装说明](docs/installation.md)；参与开发见[贡献说明](CONTRIBUTING.md)。本项目已作为开发者预览版公开于[aiiqc/nutrition-skill](https://github.com/aiiqc/nutrition-skill)。[首发CI](https://github.com/aiiqc/nutrition-skill/actions/runs/37304774493)已通过Ubuntu/macOS × Python 3.11/3.14四组检查，每组166项测试及演示通过；[发布记录](docs/release-readiness.md)列出范围与验收边界。顶部徽章显示main的最新检查状态，首发结果以固定链接为准。

## 立即运行

主Skill可以从当前目录显式读取使用，也可按安装说明完整复制到独立项目的`.agents/skills/nutrition-skill`。脚本可从任何工作目录调用：`python3 /绝对路径/nutrition-skill/scripts/nutrition.py`，从stdin接收JSON。确认其真实绝对路径后再执行；单独安装Python wheel只得到核心，不会安装Skill。

需要 Python 3.11 或以上。从本项目目录运行，无需 API Key、安装依赖或联网：

```sh
python3 -m nutrition_core --input examples/calculate.json
python3 scripts/demo.py
python3 -m unittest discover -s tests -v
```

第一条计算180克生鸡胸：216 kcal、40.5克蛋白质。第二条运行虚构状态旅程：记录早餐、替换午餐、拒绝改动锁定晚餐，再用新增过敏限制重新检查。它不是给用户的饮食处方。

```sh
python3 -m nutrition_core --input examples/rice-energy.json
python3 -m nutrition_core --input examples/allergen-unknown.json
python3 -m nutrition_core --input examples/unsupported-target.json
```

后两条分别返回 `needs_information`（退出码2）与 `unsupported`（退出码3），属于预期行为。查看接口能力：

```sh
python3 -m nutrition_core <<'JSON'
{"operation":"describe"}
JSON
```

完整验证记录见 [verification.md](docs/verification.md)。源码目标最低版本为3.11；实际测试的操作系统、Python版本和未运行边界在该记录中单独列出。

## 当前能做什么

| 功能 | 行为 |
|---|---|
| 食物与份量 | 离线读取USDA五条固定样本；生熟分开；g/kg/mg和来源有据的具体份量 |
| 营养计算 | Decimal算术；能量方法明确；缺失、假定零、检测下限、标签舍入分别保留 |
| 候选检查 | 执行调用者给定、有出处的每餐数值约束；过敏资料未知时不能标为通过 |
| 全天计划核对 | `check_day_plan`将各餐相加一次，对照给定的全天约束；餐次或覆盖确认不全时保留未知，不从三餐齐全推断全天完整 |
| 单餐替换 | 只替换指定的未锁定、未有明确实吃记录的餐次；不改变其他餐及历史实吃 |
| 实吃记录 | 计划与已吃分离；支持实际数量、部分食用、明确没吃与未知 |
| 重新检查与恢复 | 新限制覆盖锁定餐；恢复旧计划也按当前限制校验 |

M3工作流：渐进档案分流、下一餐结构建议和缺货替换、非定量实吃、保持总目标的周反馈、逐人采购克重合计，以及显式本地保存/读取/版本导出/单成员删除。接口见[m3-contracts.md](docs/m3-contracts.md)，示例见[三个旅程](examples/m3/journeys.md)。

仍未启用：TDEE、自动增肌盈余或减脂缺口、自动改变热量/蛋白/进食窗、断食策略与中医治疗方案。照片识别依赖宿主并只形成待确认候选。专业要求只能核对和转述已有来源，不等于已验证医学适用性。

## 给接入者

直接调用同一Python接口，无需语言模型：

```python
from nutrition_core.catalog import load_catalog
from nutrition_core.nutrition import calculate, check_constraints

catalog = load_catalog()
items = [{"food_id": "usda:171477", "quantity": {"amount": "180", "unit": "g"}}]
result = calculate(items, catalog)
assert result["totals"]["energy_kcal"]["amount"] == "297"
```

数值使用普通十进制字符串或整数，不用float。`status=ok`只说明当前操作成功；营养完整性看各项`complete`，计划是否满足给定限制看`check_constraints`。缺失营养的总量为null，`known_amount`只是已知部分。空过敏限制表示本次没有检查过敏，不表示已确定食品安全。

接口、全部字段、不确定性及退出码见 [contracts.md](docs/contracts.md)。通过`python -m nutrition_core`的JSON输入输出可供其他语言进程调用；本项目未验证手机端或浏览器内Python运行环境。`pyproject.toml`也提供Python包元数据，开发期可直接从源码运行。

`replace_meal`、`revalidate_plan`与`restore_plan`的限制作用于单餐；`check_day_plan`单独检查全天计划。换餐或恢复后须再次调用全天检查；计划核对不代表实际吃过，也不生成个人目标或确认专业来源真实性。过敏原接口目前只接受九个明确ID；未覆盖的过敏原会报错，不能模糊匹配后当作已验证。手工提供或修改catalog者负责数据真实性，SHA256只是快照标识。

全天接口与可复现的合成例子见[计划核对契约](docs/contracts.md#全天计划核对)。例子只演示算术和覆盖检查，不是推荐菜单。

## 数据、隐私与复用

仅打包USDA CC0五条资料的必要字段与核对依据。样本取舍、主能量字段、LOQ层次与具体份量见 [资料来源](docs/data-provenance.md)。没有将其他开源Skill整个引入运行依赖，没有打包TFDA或Open Food Facts数据库。

核心和CLI不联网、不记录原始输入日志。纯计算不写档案；只有显式save_record/delete_record操作会修改用户选定目录。例子只包含虚构档案和合成餐次状态。接入模型宿主后，用户信息是否发给模型、宿主如何保留聊天，取决于宿主；不能据此宣传整个Skill离线或零留存。

保存前选择仅本次或明确的本地目录，个人资料必须在源码目录之外。local选择允许在既定范围更新结构记录；删除仍需确认准确成员和版本。现有宽松目录权限会被拒绝，不擅自修改系统权限。当前存储支持POSIX（macOS/Linux），Windows返回unsupported。它不提供加密或同一系统账号内的成员访问控制。

保存一个成员的当前与历史版本于同一受管文件，最多50次修订、4MiB。达到上限会明确拒绝新写入，保持原数据，不自动删历史。当前适合开发验收和有限试用；长期使用前需要明确新的容量/保留方案。导出只输出结构化资料，不自动发送给别人；删除仅控制项目受管文件，不能删除宿主聊天或用户另存的副本。

自有代码采用 [MIT](LICENSE)，允许商业和闭源下游使用；数据及第三方材料义务见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。公开源码只包含可分发材料和虚构示例，个人记录应始终保存在源码目录之外。

## 当前进度与下一步

公开的dev1源码与四组远端CI已完成验收。2026-10-06在允许进程启动的当前环境，已通过Codex CLI 0.157.1的app-server实际模型会话，完成自然选用、渐进建档、问餐、缺货替换、非定量实吃、周反馈、本地保存和新会话读取恢复。测试使用虚构资料与项目范围安装副本；桌面GUI、其他宿主、真实用户和营养效果仍需分别验证。详情见[验收记录](docs/verification.md)。

dev2本地候选新增全天计划核对，并修复恢复旧计划可能改变当前锁定餐的问题；锁定组合操作明确区分计划版本与存储版本。下一步是确认本候选的GitHub更新范围，再提交、推送并核对对应远端CI。自动营养目标、食品扩充、断食及长期留存仍按[产品规格中的待定项](docs/product-spec.md#待定项与影响范围)逐项推进；当前版本没有完成全部产品范围。
