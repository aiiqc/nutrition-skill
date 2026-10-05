# Nutrition Skill

可供智能助手使用、也可被未来 App 复用的饮食 Skill 与独立计算核心。当前版本为 `0.2.0.dev1`。M0–M3本地实现已通过当前启用范围的验收，包括主Skill、日常工作流与显式本地保存；具体证据和边界见验收记录。

完整产品方向见 [唯一产品规格](docs/product-spec.md)。主入口为[SKILL.md](SKILL.md)，按[Agent Skills格式](https://agentskills.io/specification)组织。精确食品库目前只有五条资料；中西餐建议是项目自编的餐食结构，明确标为qualitative_only，不表示已满足个人热量或临床目标。

首次试用见[项目内安装说明](docs/installation.md)；参与开发见[贡献说明](CONTRIBUTING.md)。本项目为开发者预览版，公开仓库为[aiiqc/nutrition-skill](https://github.com/aiiqc/nutrition-skill)。[发布检查](docs/release-readiness.md)列出首发范围与验收边界；远端自动检查以对应提交的[GitHub Actions](https://github.com/aiiqc/nutrition-skill/actions)结果为准。

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

限制的作用域为本次传入的一餐；逐餐检查不能冒充全天目标检查。过敏原接口目前只接受九个明确ID；未覆盖的过敏原会报错，不能模糊匹配后当作已验证。手工提供或修改catalog者负责数据真实性，SHA256只是快照标识。

## 数据、隐私与复用

仅打包USDA CC0五条资料的必要字段与核对依据。样本取舍、主能量字段、LOQ层次与具体份量见 [资料来源](docs/data-provenance.md)。没有将其他开源Skill整个引入运行依赖，没有打包TFDA或Open Food Facts数据库。

核心和CLI不联网、不记录原始输入日志。纯计算不写档案；只有显式save_record/delete_record操作会修改用户选定目录。例子只包含虚构档案和合成餐次状态。接入模型宿主后，用户信息是否发给模型、宿主如何保留聊天，取决于宿主；不能据此宣传整个Skill离线或零留存。

保存前选择仅本次或明确的本地目录，个人资料必须在源码目录之外。local选择允许在既定范围更新结构记录；删除仍需确认准确成员和版本。现有宽松目录权限会被拒绝，不擅自修改系统权限。当前存储支持POSIX（macOS/Linux），Windows返回unsupported。它不提供加密或同一系统账号内的成员访问控制。

保存一个成员的当前与历史版本于同一受管文件，最多50次修订、4MiB。达到上限会明确拒绝新写入，保持原数据，不自动删历史。当前适合开发验收和有限试用；长期使用前需要明确新的容量/保留方案。导出只输出结构化资料，不自动发送给别人；删除仅控制项目受管文件，不能删除宿主聊天或用户另存的副本。

自有代码采用 [MIT](LICENSE)，允许商业和闭源下游使用；数据及第三方材料义务见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。公开源码只包含可分发材料和虚构示例，个人记录应始终保存在源码目录之外。

## 下一阶段

M4提供项目范围安装步骤、贡献说明，以及固定官方Action提交的Linux/macOS测试矩阵。Codex目录发现、安装后的完整对话、远端CI和公开发布分别验收，证据见[验收记录](docs/verification.md)。项目名为Nutrition Skill，首发目标为aiiqc/nutrition-skill；首次公开检查包括源文件核对和对应提交的CI运行。营养目标、食品覆盖及长期留存仍按产品规格处理。
