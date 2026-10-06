# 第三方来源与分发边界

自有代码、原创文档和合成测试采用根目录 MIT License。MIT 不重新许可第三方资料。

随项目打包的食物样本来自 USDA FoodData Central，数据为公共领域并以 CC0 提供。归一化和中文说明是本项目的整理；数据来源、记录发布日期、读取日期、原响应 SHA-256 和字段语义见 [data-provenance.md](docs/data-provenance.md) 与每条记录的 source。USDA 建议引用资料来源；本项目保留出处。没有复制其他 Skill 的代码。

- USDA FoodData Central: https://fdc.nal.usda.gov/
- API 与许可说明: https://fdc.nal.usda.gov/api-guide/
- CC0: https://creativecommons.org/publicdomain/zero/1.0/

台湾 FDA 和 Open Food Facts 只出现在规划、调研及来源链接中，未打包其数据库、图片或代码。后续引入时分别核对台湾政府资料开放授权条款、ODbL/DBCL/图片许可等实际义务，不能视为已纳入 MIT。

Lzheng-fitness、health-coach、WellAlly-health 是设计比较的参考，不是项目运行依赖。本项目没有复制 Lzheng-fitness 的 `third_party/dbs-learning` 等非商业授权内容。引用论文不代表转载论文全文，也不代表原作者认可本项目。

当前分发30条USDA记录，含25条新增记录的原始官方API响应或官方SR Legacy档案原文；具体来源和字节哈希见资料来源。`food-choices.json`中文别名及`portion-recipes.json`17个组合为本项目整理与原创内容。wger（AGPL-3.0-or-later）及其MCP接口只用于架构比较，没有复制代码或捆绑服务；不将参考项目的许可混入本项目代码。目标方程系数和健康资料以来源引用、事实和自有实现表达，没有转载论文全文、指南图表或第三方菜谱。
