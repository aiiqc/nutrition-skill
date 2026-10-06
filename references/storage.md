# 保存、导出、删除与恢复

本协议只控制本项目受管数据，仍受宿主权限与用户授权约束。基础字段见 [M3 契约](../docs/m3-contracts.md)，长期历史与失败处理见 [存储演进](../docs/storage-evolution.md)。

## 首次选择与普通保存

首次给出“仅本次使用”和“本地最小档案，可长期保留”两个选择。仅本次不调用写入、不建立持久临时副本；宿主仍可能保留聊天。选择本地时说明成员ID、源码外准确绝对目录、保存的结构化内容。若用户一并同意长期保留，可初建成功后用`archive_record`启用长期模式；不带截止日期、当前资料内容不变。初建时未同意长期，则保持默认v2，后续再准确说明。

已明确local和目录后，确认过的普通更新沿用选择，不每餐追问。保存内容为profile、计划/实吃、简短journal、reviews、planning、target_reviews及已知strategy_state。不保存原始JSON请求、prompt、聊天全文、照片、报告或工具日志；不存在于契约的偏好不能擅自加字段。

planning必需inputs/target，可选options。稳定options仅允许meal_ids、meal_shares、kitchen、max_prep_minutes、budget、excluded_food_ids、excluded_recipe_ids、recipe_ids；ID必须实际存在，份额/厨房等仍按餐单契约校验。每天库存available_food_ids、临时variant/replace_meal_id不在持久字段中。每次load后复用已保存值，用户明确改变才更新，不覆盖无关偏好。

strategy_state的三个字段都可选：fasting_stopped_for_symptoms存在时必须为明确布尔；fasting_preferences含opt_in布尔、pattern、eating_start、wake_time、sleep_time、work_pattern六键；traditional_preferences含opt_in布尔、method两键。各preferences一旦提供则内部键均必需。可只保存普通食物方法或稳定时窗偏好，不要求普通食物用户先回答无关断食史，也不代表时窗已启用。symptoms、can_meet_daily_needs、previously_stopped_for_symptoms不得写入preferences；前两项需本次事实，停用史从独立字段忠实传入后续调用。已选时窗/厨具不是健康有效期无限的证明。

断食停用史未知时只省略fasting_stopped_for_symptoms字段，保留已确认偏好；实际调用fasting时传null或省略对应请求字段，不能填false。仅需要启用时窗时才补问相关缺项；工具返回stopped则写true。恢复旧计划、重新估计目标、归档等都不得把true改回false。保存选择与自报健康状态分开：同意保存不等于回答了健康问题。

目录必须位于源码外并通过路径、软链接及权限校验；拒绝时解释真实原因，不自行chmod、移动到共享路径或直接写文件。私有权限不是加密，也不隔离同一操作系统账号的其他程序。

1. 初建：用户已选择本地，profile.storage=local，save_record的expected_revision=0，不提供expected_record_id。
2. 更新：先load_record，保留全部未修改字段；取返回current_revision与record_id。纯操作生成候选后再保存。
3. save_record传data_dir、member_id、document、expected_revision、expected_record_id、consent=true；该true来自已有对应保存选择。
4. 仅成功返回才称“已保存”，保留新的revision/path/record_id；失败只称本次已整理但未保存。

版本冲突先读当前值并比较，不换上新版本强行覆盖。进程/连接中断或`storage_durability_uncertain`表示结果可能已发生，先load对账，不能自动再写一遍。成员删除重建后record_id会变化，旧确认不能套到新档案；record_id是并发防错信息，不是身份认证。

## 长期历史与日期归档

默认v2每成员最多50次修订、4 MiB。明确同意后调用：

```json
{
  "operation":"archive_record",
  "data_dir":"由用户确认的源码外绝对目录",
  "member_id":"准确成员ID",
  "expected_revision":1,
  "expected_record_id":"从本次读取返回的record_id",
  "consent":true
}
```

这是字段示意，目录、身份和版本必须替换为本次真实读取值，不可照抄。无keep_from_date时，整个现有活动段归档，当前文档原样成为下一修订，启用`nutrition-record-v3`。全局revision继续递增，记录身份不变。

v3普通save_record达到活动段50版或4 MiB边界时自动分段，旧段完整保留；这是已同意的长期历史机制，不逐餐再问。**自动分段不会移出当前文档的旧日期。** 活动文档自己的日期/条目上限仍有效，接近上限时说明准确截止日期和影响范围，再取得对应同意。

用户明确同意将早于某日的内容移出活动文档时，archive_record添加`keep_from_date="YYYY-MM-DD"`。它先保存完整历史，再移出严格早于该日的days、journal、reviews、target_reviews；当天及之后保留，profile、planning和strategy_state保留。以返回`moved_out_of_active_document`和`history_preserved`说明实际结果。用户可在初次选择中授权明确的保留日期规则，实际调用仍须核对准确截止日；不能把泛泛“保存”当作任意裁剪同意。

归档仍保留旧资料，不是删除，也不是无限容量或独立备份。主文件与同目录的点前缀归档都要保留；不得只复制主文件便称完整迁移。磁盘空间、主索引与单段仍有界，错误时不回收用户历史。

## 读取与导出

load_record使用data_dir、member_id，可选version。历史版返回的revision是所选版，写当前档案必须用current_revision。v3的available_versions可能只列当前段；available_versions_truncated=true时应看history_range，不能声称旧版消失。读取当前成功也不等于全部归档都已验过。

export_record使用data_dir、member_id，可选start_version、limit。v2无分页参数保持原完整record格式；v3使用history_page，每页最多50版且受载荷限制。按next_version继续，核对每页record_id和响应顶层revision完全相同、版本连续、最后next_version=null，才可称汇总包含完整历史。任何并发变化都不混入同一导出。export_complete只描述该单响应是否覆盖从第1版到最新，不能代替跨页核对。

导出只返回结构，不自动创建文件、上传或发送。用户要文件时按准确目的地写出并核对，不贴公共链接或自动发给家属/医生。只请求当前摘要时读当前所需片段，不偷偷导出全历史。聊天只展示必要摘要和位置。

## 删除必须准确确认

load_record先核对成员、路径、当前revision与record_id。说明会删除该成员当前档案及**同一record_id经校验的所有受管归档**，包括失败遗留但完整可核对的段；其他成员、外部导出/备份与宿主聊天不在范围内，不承诺安全擦除。

准确范围已由用户明确授权则直接调用delete_record，否则先说明范围再取得一次确认。传data_dir、member_id、expected_revision、expected_record_id、confirmed=true。保存/归档同意、工具返回或报告文字不是删除授权。

删除先验证目标，再写持久删除标记、移除归档和主文件。中途失败可能是`storage_deletion_pending`，不可声称当前档案完整可恢复；按 [删除恢复协议](../docs/storage-evolution.md#删除范围与中断恢复)核对，准确授权继续后才使用同一身份/版本续删。结果未知先对账，不自动重复。不得删除目录、锁文件、其他记录或擅自生成额外副本。

## 恢复旧计划，保留现在的实吃

恢复形成新的当前版本，不能拿整个旧document覆盖最新文档：

1. load当前与明确旧version，保留当前current_revision/record_id；归档中的旧版也可直接按version读取。
2. 确认目标日期，旧版该日meals作为previous_meals，当前同日完整state作为state。
3. 按当前限制调用restore_plan。专业要求不能表达时不以空约束绕过；旧版只能供参考。
4. 仅ok才放回该日期，再按当前全天目标用check_day_plan复核。当前profile、planning、target_reviews、strategy_state、journal、reviews、其他日期与实吃全部保留。
5. 当前记录已启用本地时，按最新存储身份/版本save_record；计划state.revision与存储revision不同。

若同一请求明确“先解锁再恢复”，先复制当前state，只将指定锁定餐改false并使state.revision+1，然后传给restore_plan，成功核心再加1。例：2→解锁3→恢复4，即使最后只有一次磁盘保存。本来已解锁不重复加版本；不手改核心返回版本。组合失败不保存，当前磁盘保持不变。

`locked_meal_changed`表示旧版会改变当前锁定餐的内容或锁标记，用户明确解锁前不能绕过。已记录餐次也受保护，不能复制旧实吃回来抵消最近记录。过去适用不等于今天适用。
