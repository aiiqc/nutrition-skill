# GitHub 发布记录

0.3.0为本轮首版功能交付，目标仓库仍为[aiiqc/nutrition-skill](https://github.com/aiiqc/nutrition-skill)。本文件前段保留dev1/dev2的公开历史；0.3.0的范围与核对结果见文末，不将旧测试结果或旧制品当作当前版本。唯一需求正文仍为[产品规格](product-spec.md)。

首发已完成：0.2.0.dev1的59个项目文件已公开到main，初始提交为[91ab29f03a20208f406e4a05e55b22543956ab4a](https://github.com/aiiqc/nutrition-skill/commit/91ab29f03a20208f406e4a05e55b22543956ab4a)。远端59个文件的Git blob SHA与本地发布树逐项一致；[首次CI运行](https://github.com/aiiqc/nutrition-skill/actions/runs/37304774493)为completed/success，Ubuntu/macOS × Python 3.11/3.14四组各166项测试与演示步骤全部成功。当时未创建tag或GitHub Release。

## dev1首发定位（历史）

定位为“可复用的日常饮食Agent Skill与确定性计算核心，开发者预览版”。提供清晰交互、可追溯数据、独立核心、结构化契约与真实可重跑的例子，让其他开发者能继续扩充数据或接入App。

首发的价值是可检查和可扩展的实现，不使用“医学认证”“自动个性化处方”“全食品库”“零留存”或“已适合长期生产使用”等未获证据支持的描述。已确认的完整产品方向继续保留；预览版限制不代表取消功能。

dev1当时的GitHub About：

> Reusable nutrition agent skill with Chinese and Western meal workflows, traceable food calculations, and explicit local records. Developer preview.

当前Topics：`agent-skills`、`nutrition`、`meal-planning`、`python`、`codex`。

## dev1公开内容（历史）

| 内容 | 当前处理 |
|---|---|
| Skill与核心 | SKILL.md、references、agents元数据、Python核心及脚本，完整源包分发 |
| 食品与菜单 | 五条USDA CC0固定资料与出处、十三个自编定性模板，不混同精确营养处方 |
| 示例和测试 | 仅合成档案和可重跑用例，不包含真实健康资料或开发时的私有运行记录 |
| 使用与接入 | README、安装步骤、M2/M3契约、三旅程说明和验收边界 |
| 贡献与自动检查 | CONTRIBUTING与GitHub Actions配置；[首次远端四组检查](https://github.com/aiiqc/nutrition-skill/actions/runs/37304774493)全部成功 |
| 来源与许可 | MIT自有代码、THIRD-PARTY-NOTICES、数据provenance；未复制其他Skill作为产品代码 |

CI采用GitHub官方checkout/setup-python及现有unittest，避免额外测试框架。官方配置入口：[checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)。Actions只做检查，不创建Release、提交代码、发送通知或运行定时任务。

## 首发当时的验证与边界

| 项目 | 当前结论 | 完成条件 |
|---|---|---|
| 本地核心与源包 | 已有M3证据，本轮检查可移植安装材料 | 见verification，不把本机结果外推为远端CI |
| Codex完整宿主旅程 | 项目目录发现和显式安装副本的合成代理旅程PASS；模型自然选择及桌面UI未验收 | 不把显式指定路径、缺项反馈和工具调用替代为自然触发、完整信息或UI证据 |
| Python 3.11/3.14、Ubuntu/macOS CI | PASS：四组远端运行全部成功 | 已核对[首发提交的Actions结果](https://github.com/aiiqc/nutrition-skill/actions/runs/37304774493)；不外推其他操作系统或宿主 |
| 长期记录 | 每成员50次修订、4MiB上限，有限试用 | 持续日常使用前确定容量、历史保留与迁移，不静默删历史 |
| 仓库创建与目标核对 | PASS：已在Chrome创建并核对aiiqc/nutrition-skill，Public | 首发源文件与CI另行核对，结果见下项及验收记录 |
| 首次源代码提交与公开发布 | PASS：main初始提交已公开，59文件逐项一致 | 固定证据为[91ab29f](https://github.com/aiiqc/nutrition-skill/commit/91ab29f03a20208f406e4a05e55b22543956ab4a)及上述首次CI运行 |

首次公开源码预览及对应提交验证已完成。上表保留首发时的验收范围，后续提交的运行状态以[Actions页](https://github.com/aiiqc/nutrition-skill/actions)为准。

## 2026-10-06 dev2公开更新

新增按调用者给定约束核对全天计划，修复恢复旧计划可能改变当前锁定餐，并明确组合锁定操作的计划版本递增。两套本地Python各187项测试通过；Codex CLI 0.157.1 app-server的实际模型主旅程完成自然选用、建档、选餐、记录、周反馈及新会话读取恢复。最初启动受阻的历史与修复复验细节见[验收记录](verification.md)。

用户确认后，功能提交[4ff03c0](https://github.com/aiiqc/nutrition-skill/commit/4ff03c044af3bea44572672cd8088d2a913c93cf)已公开到现有main，61个源文件与远端逐项一致；[对应CI](https://github.com/aiiqc/nutrition-skill/actions/runs/37435684685)四组各187项测试与演示通过。随后同步发布状态文档；后续main运行以仓库Actions为准。没有创建tag或GitHub Release。桌面GUI、其他宿主、专业审核、真实用户与健康效果仍未验证；长期容量等能力边界保持不变。

## dev1首发时的Release文案草稿（历史）

标题建议：`Nutrition Skill 0.2.0.dev1 — Developer Preview`。这只是草稿，未创建tag或Release。

包含：渐进建档、普通/专业支持分流、中西餐与低负担选餐、已吃和计划分开记录、周反馈整理、家庭逐人采购、本地版本化记录及导出/删除。Python核心可独立运行，也可供未来App通过JSON或Python接口复用。

验证：修复后的两套本地Python各166项测试，独立代理三条合成旅程，离线wheel安装；首发四组Ubuntu/macOS与Python 3.11/3.14远端CI各166项测试及演示已通过。具体证据及未覆盖范围见随包verification。

限制：精确计算仅五条食品；十三个模板为定性结构。自动营养目标、数值周调整、断食策略与中医处方未启用。无加密、无共享系统账号内的家庭访问隔离；记录容量有限。没有真实用户试用、营养专业审核或临床效果证据。

附件建议：完整源ZIP及SHA256；Python wheel可另外提供给仅接入核心的开发者，不能替代完整Skill源包。公开之前核对所有附件与同一版本来源，不附带work目录、真实档案或账号信息。

## 0.3.0首版功能交付

本轮用户明确授权完成并发布到现有仓库。版本0.3.0交付的是可复用Skill与独立核心，没有转为App、账号服务或健康数据采集平台。

新增一般成人目标估算、有限周调整、30条USDA食品、17个定量组合、带克数与用油的全天餐单、替换后的全天核对、包装标签计算、可选进食时窗和普通食物传统做法。长期v3分段历史保留v2兼容，支持显式日期归档、分页导出和准确删除。临床处方、药材治疗、真实健康效果及未实测宿主不在发布声明中。

本地Python3.12/3.14各286测试与两个演示通过；独立审查发现的5个P2均已修复并复验。标准wheel构建/安装无需网络及运行依赖，48个核心/数据文件一致，禁用网络socket后完整合成流程通过。Codex CLI实际宿主完成6轮主流程与最终副本4轮复验，偏好保存缺口已修复；发布对应的远端证据补入下方，详见[verification](verification.md)。

本轮发布顺序：核对仅项目源文件与许可 → 完成实际宿主验收 → 提交并推送main → 核对该提交四组远端CI → 固定v0.3.0 tag → 创建GitHub Release → 上传完整源码ZIP、Python wheel和SHA256 → 下载核对附件和远端源树。未知结果先查询，不盲目重试写操作。

源码ZIP用于安装完整Skill；wheel仅安装可独立调用的核心。不会附带开发工作目录、模型会话、合成试用档案或标签图片、账号配置与凭据。轮次中的开发证据保留在私有工作目录，公开记录只包含事实摘要。
