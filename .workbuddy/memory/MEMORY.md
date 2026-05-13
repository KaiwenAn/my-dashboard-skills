# 看板开发 Agent 记忆档案

## 项目信息
- **工作空间路径**: `C:\Users\Kai\WorkBuddy\20260427134240\`
- **Skill 路径**: `C:\Users\Kai\.workbuddy\skills\dashboard-agent\`
- **核心模块**: `agents.py`, `pipeline.py`, `llm.py`, `data_platform_api.py`, `bi_api.py`

## 技术架构

### Pipeline 流程
6个Agent串联: requirements_parser → semantic_model → bi_push → chart_design → instruction_generator → solution_generator

### 数据平台
- **API**: `DataPlatformClient` 类封装数据平台SQL查询接口
- **引擎**: 必须使用 Spark（Presto 某些语法不支持）
- **表结构获取**: `describe_table()` 方法可获取表字段

## 近期优化

### 2026-05-12: 自然语言输入转换层（新增）

**问题**: 用户需要手写复杂的 JSON 文件才能使用 pipeline，门槛高

**解决方案**: 创建 `nl_converter.py`，支持自然语言直接输入

**新增文件**:
- `scripts/nl_converter.py` - 自然语言转结构化JSON转换器

**修改文件**:
- `scripts/run_pipeline.py` - 增加 `--natural-input` 和 `--natural-input-file` 参数
- `SKILL.md` - 添加自然语言输入方式说明

**使用方式**:
```bash
# 方式1：命令行直接输入
python run_pipeline.py --natural-input "帮我做一个用户行为分析看板，数据源是iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"

# 方式2：从文件读取
python run_pipeline.py --natural-input-file input.txt --output ./output
```

**转换层能力**:
- ✅ 提取看板标题（从自然语言中提取）
- ✅ 识别数据源表名（支持多种格式）
- ✅ 自动调用 describe_table 获取字段信息
- ✅ 推断常见指标和维度（基于表名+字段+业务常识）
- ✅ 生成 confirmation_items 确认清单

**NLConverter 类设计**:
- `_extract_meta_info()` - LLM提取元信息
- `_extract_table_names()` - 正则提取表名
- `_fetch_table_info()` - 调用数据平台获取字段
- `_infer_metrics_and_dimensions()` - LLM推断指标维度
- `_build_output()` - 构建标准JSON输出

### 2026-05-13: requirements-parser v0.4 — field_name 字段
**问题**: dimensions_spec 只有 name（业务名如"日期"、"地区"），下游语义模型Agent需要实际字段名（如"pay_time"、"province"）才能生成 SQL

**解决方案**: dimensions_spec 增加 `field_name` 字段（必填），要求从 key_fields/field_descriptions 映射得出

**修改**: `prompts/requirements-parser-agent.md` v0.3→v0.4
- 输出规范 dimensions_spec 增加 field_name 字段
- 输出约束要求 field_name 必须包含且可映射
- Step3 增加"业务名→字段名映射"规则及示例
- 示例更新：日期→pay_time、商品类目→category_id、地区→province
- 质量守则增加 field_name 无法映射时的标记规则

**设计原则**: name=业务维度名（中文展示用），field_name=实际表字段名（SQL生成用），两者解耦

### 2026-05-12: 表字段自动拉取功能
**问题**: LLM 生成 SQL 时自己猜字段名，容易出错

**解决方案**:
1. 在 `SemanticModelAgent.run()` 开始时，调用 `_fetch_table_columns()` 方法
2. 从 `user_input.data_sources` 获取所有表名
3. 调用 `DataPlatformClient.describe_table()` 获取真实字段信息
4. 格式化为 `column_types` 结构注入 context
5. `semantic-model-agent.md` 的 prompt 已支持 `column_types` 输入

**关键代码位置**: `C:\Users\Kai\WorkBuddy\20260427134240\agents.py`
- 新增方法: `_fetch_table_columns()`, `_describe_table_fallback()`
- 修改方法: `SemanticModelAgent.run()` - 在生成SQL前自动拉取字段

### 2026-04-28: v0.3 里程碑
语义模型 SQL 直接可用，无需修改。关键成功因素：
- 输入结构显式化（field_mappings/join_hints/table_type/field_descriptions）
- Prompt 规则收紧（join_hints优先、CTE去重、多表同步过滤）
- 模型能力匹配（DeepSeek-V4-Flash替代Qwen3-8B）
