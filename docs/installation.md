# 安装与首次试用

当前是开发者预览版，工作名Nutrition Skill，Skill ID为`nutrition-skill`。建议先在独立项目中试用，再决定是否个人全局安装。本页面向macOS/Linux；已公开的0.2.0.dev2在Ubuntu/macOS的Python 3.11/3.14[四组CI](https://github.com/aiiqc/nutrition-skill/actions/runs/37435684685)各187项测试及演示通过，项目安装布局在macOS实测。另已在Codex CLI 0.157.1的app-server项目副本完成实际模型旅程，桌面GUI与其他宿主未验证。需要Python 3.11+和能够执行Python、读取本地文件的宿主。Windows持久存储尚不支持。

## 两种使用方式

| 方式 | 适用情况 | 能证明什么 |
|---|---|---|
| 显式读取源目录的SKILL.md | 先看流程，不配置宿主发现目录 | Agent能按文件说明调用核心；不等于自动发现 |
| 完整文件夹放入项目的.agents/skills/nutrition-skill | 在一个指定项目里通过技能列表选用 | Codex项目范围发现；是否正确选择和执行仍需实际旅程验收 |

官方当前支持项目`.agents/skills`以及个人`~/.agents/skills`，还支持技能文件夹符号链接。为保持本项目可独立复制和便于撤销，以下示例使用完整目录副本。路径规则核对日期2026-10-05，来源：[官方Build skills](https://learn.chatgpt.com/docs/build-skills)。本页不写用户全局配置，不安装MCP、插件或后台服务。

## 在独立项目试用

从可信的本项目源包解压得到`nutrition-skill`文件夹。核对随包校验值后，先在终端进入该文件夹，执行：

```sh
python3 --version
python3 -B scripts/nutrition.py --input examples/calculate.json
python3 -B -m unittest discover -s tests -q
```

第一条实际计算应是180g生鸡胸216 kcal、40.5g蛋白质；这只是计算例子。确认可运行后，在同一目录执行下面的复制命令。它会在源目录旁新建`nutrition-skill-playground`项目；目标已经存在则退出，不覆盖原文件。

```sh
python3 - <<'PY'
from pathlib import Path
import shutil

source = Path.cwd().resolve()
for required in ("SKILL.md", "scripts/nutrition.py", "nutrition_core", "references"):
    if not (source / required).exists():
        raise SystemExit("请先进入解压后的完整 nutrition-skill 源目录。")
project = source.parent / "nutrition-skill-playground"
if project.exists() or project.is_symlink():
    raise SystemExit("试用项目已存在；请复用已核对的副本，不自动覆盖。")
target = project / ".agents" / "skills" / "nutrition-skill"
shutil.copytree(source, target, ignore=shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "*.pyo", ".venv", "build", "dist",
    "*.egg-info", ".DS_Store", ".env", ".env.*", "private-data"
))
print("试用项目：", project)
print("Skill入口：", target / "SKILL.md")
PY
```

从打印出的试用项目目录启动Codex，使用技能列表或`$nutrition-skill`明确调用。在Codex CLI中可从刚才源目录执行：

```sh
codex -C ../nutrition-skill-playground
```

首次验证只使用虚构输入：

> 使用 $nutrition-skill。这是虚构试用：成年人，只想了解懒人中式午餐怎么选，先仅本次使用。先检查当前能力；缺少健康信息请指出，不要猜测没有疾病或过敏，也不要保存我的档案。

再分别尝试“某个推荐缺货”“份量未知但已经吃了”“断档一周，从下一餐恢复”。对照[三条合成旅程](../examples/m3/journeys.md)检查行为。技能列表可见只说明发现成功，不能替代上述对话和工具执行验收。

## 如何确认实际调用

正常使用时，Agent应解析Skill本身的绝对路径，再执行`scripts/nutrition.py`并检查JSON结果。CLI的`describe`只报告能力；实际完成需有相应操作结果。无代码执行能力时不得把语言模型估算称为核心计算结果。

若技能未出现，先核对完整目录、SKILL.md frontmatter和项目启动位置，检查是否有重复同名副本；按官方建议重新启动Codex后再看技能列表。不要通过放宽系统权限、全局安装额外服务或修改模型账号来排查。

## 保存、更新与退出试用

默认仅本次使用。选择本地保存时，另选源码和安装副本之外的专用私有目录，保存成功应返回准确成员、record_id和revision。当前每成员最多50次修订、4MiB；达到上限拒绝新写入，不自动删历史。数据不能跟随源码提交到GitHub。详见[存储契约](m3-contracts.md)及[数据管理说明](../references/storage.md)。

升级前保留可恢复的旧源包，核对新版本的格式说明；先用合成档案验证，不直接覆盖仍在使用的副本。现有v2档案规则见接口契约；未公开的v1测试文件不自动迁移。0.2.0.dev1可以读取原有反馈，但包含新not_training状态的记录不能交给旧dev0读取；降级必须同时使用匹配的历史数据副本，不能只换旧代码。

停止试用可关闭试用项目，并将该Skill副本移出该项目的`.agents/skills`发现目录；保留健康档案目录。若需要删除健康档案，必须单独核对成员、路径和版本，再使用delete_record，不随卸载或更新一并清理。

## 验证状态与分发选择

本轮实际证据见[验收记录](verification.md)。本地文件夹发现、安装后模型选择、完整对话、GitHub CI、其他平台分别记录，不把其中一项PASS外推为其他项通过。

公开GitHub源代码与提交到官方插件目录是两个动作。官方目前推荐用插件分发可安装技能；本项目当前交付可复用Skill源包和独立Python核心，插件包装属于可选后续适配，不是本轮安装的依赖。[官方分发说明](https://learn.chatgpt.com/docs/build-skills#distribute-skills-with-plugins)
