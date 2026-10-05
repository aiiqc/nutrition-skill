# 三个合成旅程与实际验收

全部人物、健康条件与专业来源均为虚构测试资料。日期语境为2026-10-05，复盘为2026-10-12。这些例子演示软件行为，不是可照用的个人饮食处方。

## 上班族：低负担选餐与未知份量

输入档案是[office-profile.json](office-profile.json)。用户想慢慢减脂，主要吃中式外卖；本例没有自报健康限制，不称食物。

实际调用顺序：assess_profile → next_meal → 排除首推荐后next_meal → record_note午餐与晚餐 → save_record/load_record → weekly_review → save_record/load_record。

结果：先给熟鸡肉、米饭和蔬菜结构；第一推荐缺货后改为熟豆腐、米饭和蔬菜结构。均标qualitative_only，不提供虚构热量或承诺减脂达标。午餐“豆腐蛋饭、米饭约剩三分之一”和晚餐“火锅已吃、份量未知”进入结构化journal，不混入精确营养总量。

用户提供“五天能执行、两天下午饿、称重三次且无前周基线”。实际保存adherent_days=5、hunger_days=2、hunger_times=[afternoon]、weigh_ins_count=3、has_previous_week_baseline=false；没有把五天执行当作观察了五天。未明确的观察天数、精神、训练及近期健康变化保持未知，本次返回needs_information，先补资料并保留正常进餐。没有改变热量、蛋白质或进食窗，没有补偿性禁食。

快速查看菜单结构：

```sh
python3 scripts/nutrition.py --input examples/m3/next-meal-request.json
```

## 训练者：锁定、实吃与计划恢复

输入为[training-profile.json](training-profile.json)，定量演示使用[initial-state.json](../initial-state.json)中的明确份量。示例初始晚餐已锁定；本例后来明确解除晚餐锁定，只保留早餐锁定。此设置变化必须来自明确用户输入，不能为让换餐通过而暗中改动。

实际记录午餐熟鸡胸90g、熟米饭79g，得到所列食物小计251.2 kcal、蛋白质30.0431g。小数位只是算术精度；不是食物测量的同等精确度。早餐和晚餐未记录，因此day_complete=false，不能当作全天总量。

初次更换晚餐正确返回meal_locked。收到明确解锁后，晚餐更改为熟鸡胸140g、熟米饭200g，再恢复原演示140g鸡胸、158g米饭。午餐实际摄入不被恢复覆盖，早餐仍锁定；一次休息日没有自动删掉主食或降低目标。上述食品只是技术演示，不声称符合该训练者的个人增肌需求。

## 家庭成员：专业安排与逐人记录

输入为[family-profile.json](family-profile.json)。获成员同意的家属协助一位58岁、有慢性肾病与花生过敏的虚构父亲。

只有“清淡”时，next_meal不生成个人餐单。提供经确认的虚构专业摘要后，工具只转述其中“按允许做法与个人份量准备清蒸鱼、米饭、西葫芦”的安排，保留来源、签发和复查日期；成分仍未核验，结果保持needs_information。新低钠盐成分和交叉接触未知时不放行，也不编写肾病营养限值。

“父亲吃了一半”仅记入父亲journal，没有个人克数就不编造营养摄入；其他家人没有反馈，不自动记为已吃。食欲下降与不明原因体重下降进入pause_and_review，不视为减脂成功，不下调专业目标。export_record只返回父亲本人和受管历史，不发送给他人。

本例没有其他成员的个人份量，所以没有虚构家庭采购数值。已量化家庭采购的独立验收证明：180g与120g同一生鸡胸合计300g，个人份量分别保留；70g熟鸡胸单列，不推导生熟折算。采购合计本身不证明全家限制已经通过。

## 证据边界与复现

2026-10-05，独立代理实际读取主Skill及参考，并从源码目录之外调用脚本完成上述适用路径。共保留57份合成调用和后置断言证据于开发工作目录；公开源包只保留最小虚构档案与可重跑测试，不打包运行时健康档案。

验收中发现周反馈事实遗漏，已补字段并重跑保存/读取。存储同时升级为nutrition-record-v2；三份最终document在新私有测试目录逐一保存/读取相等，office使用record_id+revision继续更新成功。旧测试证据保留；这是新测试实例，未宣称旧格式全历史迁移。

```sh
python3 -B -m unittest discover -s tests -p test_m3_integration.py -v
python3 -B -m unittest discover -s tests -p test_storage.py -v
```

独立代理的三个旅程没有删除授权，因此未执行删除。删除隔离、重建后旧请求拒绝和失败恢复由专门合成存储测试验证。全局安装/自动发现、真实用户及临床效果不属于这些合成证据；完整状态见[验收记录](../../docs/verification.md)。
