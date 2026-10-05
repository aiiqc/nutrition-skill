# M3 实施契约

本阶段在已通过的M2核心上增加主Skill、结构化档案、菜单结构建议、周反馈、家庭汇总及本地保存。产品范围以product-spec.md为唯一总规格；此文件只定义本轮具体接口。没有安装全局Skill、创建远端仓库或发布权限。

## 档案与文档

workflow.validate_profile(profile) -> dict：校验并返回深拷贝。必填id，匹配`[a-z0-9][a-z0-9_-]{0,63}`。其余字段可暂缺，但未知字段拒绝：age（整数1..120），goals（fat_loss/muscle_gain/wellbeing数组），priority（其中一个），preferences（cuisine=chinese/western/mixed，effort=lazy/standard，scenario=home/takeaway/no_cook，dislikes字符串数组），measurements（height_cm/weight_kg十进制字符串及measured_on ISO日期，值必须为正），health（以下字段各可null代表未知：allergens字符串数组、conditions字符串数组、medications字符串数组、pregnancy_lactation布尔、eating_disorder_risk布尔、malnutrition_risk布尔），storage（temporary/local），professional_plan（见下）。所有列表、文本和数字有合理上限，不能以拼错的字段解除限制。

health.allergens允许用户自报的非空食物/过敏原文本；计算核心只认识9个ID。未覆盖或无法核实的过敏原不得因为无法转成ID就忽略。健康状态仅为用户自报，不标为医学安全认证。

professional_plan若存在，包含member_id、source、issued_on、review_on、confirmed布尔、meals（meal_id到用户提供的简短安排文本）、substitutions（简短已允许替换文本数组）。必须匹配profile.id，来源与日期不能为空；保留的是确认后的结构化要求，不保存原报告。当前核心不验证医学适用性，呈现方案时注明仅转述；有过敏或配料缺项时不把转述当作验证通过。

workflow.validate_document(document) -> dict：校验并返回深拷贝。必填schema_version='m3-1'和profile。可选days（ISO日期到M2 state）、journal（date、meal_id、status=confirmed/partial/not_eaten/unknown、quantity_status=known/estimated/unknown、food_summary、quantity_note的简短结构化记录数组）、reviews（weekly_review返回的结构化结果数组）。每个文档只对应一个成员；不得含原始prompt/transcript/照片/报告字段。days每项使用M2验证。定量实吃仍用M2；journal只保留未匹配或份量不明的已知事实，不参与精确营养汇总。status=unknown时quantity_status必须unknown；明确not_eaten时quantity_status必须known。同一日期和餐次不能同时存在非unknown的定量实吃和journal两条真相。

## 纯工作流

workflow.assess_profile(profile, as_of) -> {status,route,missing_fields,questions,issues,...}。as_of是显式ISO日期，结果可复现；最多3个当前高价值问题。缺年龄、关键健康项需补齐；多目标没有priority需确认。未成年及进食障碍/营养不良风险禁用普通成人减脂/断食优化；有疾病、用药、孕哺情况进入专业要求支持。pending/standard/professional/support_only为分流，不能因切懒人/精细而清空限制。专业方案过期或未确认必须提示。M3不生成临床或体重目标。

workflow.next_meal(profile, as_of, meal_id='lunch', excluded_ids=None) -> dict。meal_id仅breakfast/lunch/dinner/snack。按cuisine/effort/scenario筛选项目自编餐食结构，返回1份recommendation和最多2个alternatives。结构有食物名称、实际购买/准备方法、portion_note；明确validation='qualitative_only'，没有精确热量或增减肌效果承诺。有待补筛查/已知过敏/专业方案缺项时不能输出已验证安全替代。合法专业方案可转述已有对应餐次，但标记仅用户提供、当前成分未核验；不发明替换。无候选时解释，不凑数量。支持excluded_ids实现缺货或换餐。

workflow.weekly_review(profile, feedback, as_of) -> dict。feedback字段为days_observed整数0..7、adherence=easy/mixed/hard/unknown、hunger=comfortable/hungry/unknown、energy=normal/low/unknown、training=normal/changed/not_training/unknown、health_changed布尔、appetite_declined布尔、unintentional_weight_loss布尔、returning_after_gap布尔；未填状态保留unknown，不默认无风险。结果action=maintain_and_simplify或pause_and_review，不调整总热量/蛋白/进食窗。输出具体便利性建议与缺项，有不明体重下降/食欲下降等变化建议专业评估，不将其标为减脂成功；断档从下一餐恢复，不补历史。

shopping.aggregate_shopping(member_meals,catalog) -> dict，输入数组每项{member_id,items}；同food_id按可食克重相加并保留逐人份量、生熟、来源，不能推导购买毛重/营养保留率或家庭安全合规。独立成员ID不可重复。仅已验证M2 item参与，未量化菜式需另列待确认，不填0。

journal.record_note(document, note) -> dict：校验上述document及note，仅更新该成员同(date,meal_id)记录，不改days内计划或实吃。显式确认由调用宿主依据清楚用户陈述完成；unknown数量不会转成精确值。结构记录不是聊天归档。

## 本地持久化（storage.py）

save_record(data_dir,member_id,document,expected_revision,consent,expected_record_id=None) -> dict。
load_record(data_dir,member_id,version=None) -> dict。
export_record(data_dir,member_id) -> dict（完整受管结构化版本返回stdout，不写另一目的地）。
delete_record(data_dir,member_id,expected_revision,confirmed,expected_record_id=None) -> dict。

data_dir必须显式给定绝对路径、位于源码外，不接受根目录、用户home本身或源码祖先；禁止软链接根/路径/记录。每成员仅管理一个`<id>.json`文件。保存须consent=true且profile.storage=local；首次expected_revision=0且expected_record_id为空，创建随机且不可复用的record_id。后续保存及删除必须同时提供准确的expected_record_id与expected_revision，冲突不得覆盖；成员同名不等于同一档案实例，删除后重建不会接受旧请求。保存原子替换；当前与既有版本存同一受管文件，最多50次修订，达上限明确拒绝，不静默删除历史。单文件上限4MiB。目标文件已有但不是本格式拒绝覆盖。

存储结果包含status、member_id、record_id、revision、path；受管格式nutrition-record-v2。record_id是并发校验标识，不是鉴权凭据。load返回document深拷贝及available_versions；export含完整受管历史、schema和版本信息。delete需confirmed=true、准确record_id与revision，只移除此成员受管文件及其中历史，不删除目录或其他成员。一次保存许可不代替未来删除的准确确认。保存失败不得报成功；并发冲突、无权限、畸形文件均返回NutritionError。CLI及storage不记录原始JSON。

目录新建mode0700、文件新建mode0600，已有目录/文件若超出私有权限应拒绝并说明，不能擅自改系统权限。不承诺加密或同一OS账号内隔离。存储锁必须有界且释放，不自动清理别人或旧进程的锁。

## 主入口与验收

主Skill位于项目根SKILL.md，references按需加载；入口脚本scripts/nutrition.py接受与python -m nutrition_core相同JSON，从任意工作目录可运行。新CLI operations：assess_profile、next_meal、weekly_review、record_note、aggregate_shopping、save_record、load_record、export_record、delete_record。所有写入均是显式操作，不随计算隐式保存。旧M2 operations保留。

验收：保留74项基线；新增纯流程与存储真实行为测试；三个合成旅程经过独立代理按主Skill实际操作；宿主自动发现/全局安装、临床效果、远端发布单独标记未运行，不能把代理读取Skill模拟成用户已安装。

## M3 实测后补充的边界

weekly_review.feedback另有五个可选观测字段：adherent_days（0..7）、hunger_days（0..7）、hunger_times（morning/afternoon/evening/overnight数组）、weigh_ins_count（0..100）、has_previous_week_baseline（布尔）。未提供时为null，不从执行天数或称重次数推断days_observed，也不触发定量目标调整。原m3-review-1的9字段历史结果继续原样接受；新增字段缺失本身不阻断已完整的基本反馈。

文档上限：366个days、1000个journal、52个reviews，JSON树最多100000节点、深度20、单文本最多4096字符；字段还各有更小上限。数据限额不代表医学合理范围。

存储替换或删除完成后若目录同步失败，返回storage_durability_uncertain及可见变更标志；必须先读取核对再决定后续，不自动重试。保存使用nutrition-record-v2，本轮未发布过的v1合成存储证据不会自动迁移或覆盖。

工作流版本m3-2026-10-05.2起，明确没有训练使用not_training，不产生训练缺项或隐含数值调整。原normal/changed/unknown反馈继续兼容；旧unknown不会自动改写为没有训练。执行天数与执行难度分别保留。
旧0.2.0.dev0不识别新的not_training值；包含该值的记录至少需要dev1读取，不保证新记录可由旧版本打开。
