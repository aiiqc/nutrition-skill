# GitHub 开发者预览发布准备

日期：2026-10-05。软件版本0.2.0.dev1；项目名Nutrition Skill，已确认的公开目标为[aiiqc/nutrition-skill](https://github.com/aiiqc/nutrition-skill)。本文件是首次公开检查与发布文案，不替代[唯一产品规格](product-spec.md)中的需求和当前状态。

首发范围：0.2.0.dev1的59个已检查项目文件、初始源代码提交与CI验证。已核对aiiqc/nutrition-skill的Public仓库创建成功；源文件首次提交和CI结果仍待实际验证。tag与GitHub Release尚未创建。

## 建议的首发定位

定位为“可复用的日常饮食Agent Skill与确定性计算核心，开发者预览版”。提供清晰交互、可追溯数据、独立核心、结构化契约与真实可重跑的例子，让其他开发者能继续扩充数据或接入App。

首发的价值是可检查和可扩展的实现，不使用“医学认证”“自动个性化处方”“全食品库”“零留存”或“已适合长期生产使用”等未获证据支持的描述。已确认的完整产品方向继续保留；预览版限制不代表取消功能。

建议GitHub About：

> Reusable nutrition agent skill with Chinese and Western meal workflows, traceable food calculations, and explicit local records. Developer preview.

建议Topics：`agent-skills`、`nutrition`、`meal-planning`、`python`、`codex`。以上为首发页面材料，最终展示以仓库页面为准。

## 可以随源代码公开的内容

| 内容 | 当前处理 |
|---|---|
| Skill与核心 | SKILL.md、references、agents元数据、Python核心及脚本，完整源包分发 |
| 食品与菜单 | 五条USDA CC0固定资料与出处、十三个自编定性模板，不混同精确营养处方 |
| 示例和测试 | 仅合成档案和可重跑用例，不包含真实健康资料或开发时的私有运行记录 |
| 使用与接入 | README、安装步骤、M2/M3契约、三旅程说明和验收边界 |
| 贡献与自动检查 | CONTRIBUTING与GitHub Actions配置；Actions实际运行结果须在首次远端执行后记录 |
| 来源与许可 | MIT自有代码、THIRD-PARTY-NOTICES、数据provenance；未复制其他Skill作为产品代码 |

CI采用GitHub官方checkout/setup-python及现有unittest，避免额外测试框架。官方配置入口：[checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)。Actions只做检查，不创建Release、提交代码、发送通知或运行定时任务。

## 首发前的剩余项

| 项目 | 当前结论 | 完成条件 |
|---|---|---|
| 本地核心与源包 | 已有M3证据，本轮检查可移植安装材料 | 见verification，不把本机结果外推为远端CI |
| Codex完整宿主旅程 | 项目目录发现和显式安装副本的合成代理旅程PASS；模型自然选择及桌面UI未验收 | 不把显式指定路径、缺项反馈和工具调用替代为自然触发、完整信息或UI证据 |
| Python 3.11、Linux/macOS CI | 已准备工作流，首发前快照中远端运行NOT RUN | 首次上传后核对对应提交的[Actions结果](https://github.com/aiiqc/nutrition-skill/actions)，不由本地结果推断 |
| 长期记录 | 每成员50次修订、4MiB上限，有限试用 | 持续日常使用前确定容量、历史保留与迁移，不静默删历史 |
| 仓库创建与目标核对 | PASS：已在Chrome创建并核对aiiqc/nutrition-skill，Public | 首次源码上传前为空仓库；创建成功不代表源文件或CI通过 |
| 首次源代码提交与公开发布 | 源文件上传和对应CI检查待执行 | 在上述已创建仓库上传已核对源文件并提交初始版本；核对远端文件及CI |

当前推进首次源代码公开发布与对应提交验证。该文档保留首发前检查快照；远端运行状态以[Actions页](https://github.com/aiiqc/nutrition-skill/actions)的具体提交为准。缺少宿主完整验收时，即使源码公开且CI通过，也不标记M4全通过或正式稳定版。

## Release 文案草稿

标题建议：`Nutrition Skill 0.2.0.dev1 — Developer Preview`。这只是草稿，未创建tag或Release。

包含：渐进建档、普通/专业支持分流、中西餐与低负担选餐、已吃和计划分开记录、周反馈整理、家庭逐人采购、本地版本化记录及导出/删除。Python核心可独立运行，也可供未来App通过JSON或Python接口复用。

验证：修复后的两套本地Python各166项测试，独立代理三条合成旅程，离线wheel安装；后续检查详见随包verification。不要把“配置已写好”写成“GitHub CI已通过”。

限制：精确计算仅五条食品；十三个模板为定性结构。自动营养目标、数值周调整、断食策略与中医处方未启用。无加密、无共享系统账号内的家庭访问隔离；记录容量有限。没有真实用户试用、营养专业审核或临床效果证据。

附件建议：完整源ZIP及SHA256；Python wheel可另外提供给仅接入核心的开发者，不能替代完整Skill源包。公开之前核对所有附件与同一版本来源，不附带work目录、真实档案或账号信息。
