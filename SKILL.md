---
name: dashboard-agent
description: |
  一键生成 BI 看板搭建方案的数据分析师提效 Agent。当用户需要快速搭建数据看板、分析业务指标、生成 SQL 查询或设计可视化图表时触发。
  适用场景：运营日报、业绩监控、A/B测试分析、用户行为分析等数据看板开发需求。
  This skill should be used when the user needs to generate BI dashboard solutions, analyze business metrics, or create SQL queries for data visualization.
---

# 看板开发 Agent (Dashboard Agent)

一键生成 BI 看板搭建方案的数据分析师提效工具。通过多 Agent 流水线，自动完成从需求解析到方案输出的全流程。

## 核心能力

**6 个 Agent 流水线**：需求解析 → 语义模型 → BI推送 → 图表设计 → 看板指令生成 → 方案生成

| Agent | 职责 | 输出 |
|-------|------|------|
| 需求解析 | 口径守门人，7步推理，置信度评估 | 结构化需求规格 |
| 语义模型 | SQL生成核心，NULLIF防除零，三层过滤 | 可执行的SQL |
| BI推送 | 自动调用BI平台API创建语义模型 | model_id |
| 图表设计 | 12列网格布局，图表类型推荐 | 图表配置 |
| 看板指令 | 标准化结构化指令（JSON） | 可执行的搭建指令 |
| 方案生成 | Markdown方案文档，确认项合并去重 | 完整搭建文档 |

## 输入格式

支持两种输入方式：**自然语言**（推荐）和 **JSON文件**。

### 方式1：自然语言输入（推荐⭐）

最简单的使用方式，直接用中文描述需求：

```bash
# 命令行直接输入
python scripts/run_pipeline.py --natural-input "帮我做一个用户行为分析看板，数据源是iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"

# 或从文件读取
echo "帮我做一个用户行为分析看板，数据源是iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view" > input.txt
python scripts/run_pipeline.py --natural-input-file input.txt
```

**转换层会自动完成以下工作：**
- ✅ 提取看板标题（如"用户行为分析看板"）
- ✅ 识别数据源表名
- ✅ 自动调用数据平台获取表字段信息
- ✅ 推断常见指标（DAU、页面访问次数、会话数等）
- ✅ 推断常见维度（日期、页面名称、模块名称等）
- ✅ 生成确认项清单，标记所有需要用户确认的内容

### 方式2：JSON文件输入

用户需要提供看板需求，格式如下：

```json
{
  "dashboard_meta": {
    "title": "看板标题",
    "audience": "目标受众",
    "goal": "看板目标"
  },
  "data_sources": [
    {
      "table_name": "表名",
      "description": "表用途",
      "table_type": "fact | dimension | fact_as_dimension",
      "key_fields": ["关键字段列表"],
      "field_mappings": {"实际字段名": "别名"},
      "field_descriptions": {"字段名": "含义说明"}
    }
  ],
  "join_hints": [
    {
      "left_table": "左表",
      "right_table": "右表",
      "join_on": "关联条件",
      "join_type": "LEFT JOIN | INNER JOIN"
    }
  ],
  "metrics_requirement": [
    {"name": "指标名称", "description": "指标描述"}
  ],
  "dimensions_requirement": [
    {"name": "维度名称"}
  ],
  "filters_known": [
    {"field": "字段", "operator": "=", "value": ["值"]}
  ],
  "additional_notes": "补充说明"
}
```

## 执行方式

WorkBuddy 调用 `scripts/run_pipeline.py` 执行流水线：

```bash
# 方式1：自然语言输入（新增）
python scripts/run_pipeline.py --natural-input "需求描述"

# 方式2：自然语言文件输入（新增）
python scripts/run_pipeline.py --natural-input-file input.txt --output ./output

# 方式3：JSON文件输入（原有）
python scripts/run_pipeline.py --input <需求JSON文件路径> --output <输出目录>

# 指定运行模式（覆盖配置）
python scripts/run_pipeline.py --natural-input "..." --mode publish   # 强制推送
python scripts/run_pipeline.py --natural-input "..." --mode plan      # 强制方案
```

## 输出结果

Pipeline 执行完成后，会在指定输出目录生成：

1. **`solution.md`** - 完整的看板搭建方案（Markdown格式）
2. **`solution.html`** - HTML 可视化版本
3. **`agent_outputs/`** - 每个 Agent 的中间输出（JSON）
   - `1.requirements_parser.json` - 需求解析结果
   - `2.semantic_model.json` - 语义模型SQL
   - `3.chart_design.json` - 图表设计配置
   - `4.instruction_generator.json` - 看板指令
   - `bi_push_result.json` - BI推送结果（如有）

## Prompt 参考

详细的 Agent System Prompt 存放于 `references/prompts/`：

- `requirements-parser-agent.md` - 需求解析 Agent 提示词
- `semantic-model-agent.md` - 语义模型 Agent 提示词
- `chart-design-agent.md` - 图表设计 Agent 提示词
- `instruction-generator-agent.md` - 看板指令 Agent 提示词
- `solution-generator-agent.md` - 方案生成 Agent 提示词
- `bi-push-agent.md` - BI推送 Agent 提示词

## 配置说明

### 配置文件

编辑 `scripts/config.json` 配置所有参数。**配置文件优先级高于环境变量**。

```json
{
  "data_platform": {
    "base_url": "https://proxy-service-http-cnbj1-dp.api.xiaomi.net",
    "catalog": "iceberg_zjyprc_hadoop",
    "schema": "meta",
    "engine": "Spark",
    "token": "你的数据平台token"
  },
  "bi_platform": {
    "enabled": "plan",
    "base_url": "https://api-smp.dt.mi.com",
    "api_prefix": "/os",
    "space_id": null,
    "creator": null
  },
  "sql_validation": true,
  "llm": {
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "api_key": "你的API Key",
    "base_url": "可选，自定义API地址",
    "temperature": 0.1
  }
}
```

### 优先级说明

| 配置项 | 优先级（高→低） |
|--------|----------------|
| LLM api_key | `config.llm.api_key` > `HUNYUAN_API_KEY` > `DEEPSEEK_API_KEY` |
| LLM base_url | `config.llm.base_url` > `LLM_BASE_URL` > SDK默认 |
| LLM model | `config.llm.model` > 默认值 `deepseek-ai/DeepSeek-V4-Flash` |
| 数据平台 token | `config.data_platform.token` > `DATA_PLATFORM_TOKEN` |
| 数据平台 base_url | `config.data_platform.base_url` > `DATA_PLATFORM_BASE_URL` |
| 数据平台 engine | `config.data_platform.engine` > 默认值 `Spark` |
| **BI 推送模式** | `--mode 参数` > `user_input.bi_config` > `自然语言关键词` > `config.bi_platform.enabled` |
| **SQL 校验开关** | `user_input.enable_sql_test` > `--no-sql-test / 自然语言关键词` > `config.sql_validation` |

**BI 推送模式**有 4 种切换方式，优先级从高到低：

| 优先级 | 方式 | 示例 |
|--------|------|------|
| 1（最高） | `--mode` 命令行参数 | `--mode publish` / `--mode plan` |
| 2 | JSON 中的 `bi_config` | `{"bi_config": {"space_id": 123, "creator": "zhangsan"}}` |
| 3 | 自然语言关键词 | 输入含"推送"/"发布" → PUBLISH，含"方案"/"仅方案" → PLAN |
| 4（最低） | `config.json` 的 `bi_platform.enabled` | `"plan"`（默认）/ `"publish"` |

**SQL 校验开关**有 3 种切换方式，优先级从高到低：

| 优先级 | 方式 | 示例 |
|--------|------|------|
| 1（最高） | JSON 中的 `enable_sql_test` | `{"enable_sql_test": false}` |
| 2 | `--no-sql-test` 参数 或 自然语言关键词 | `--no-sql-test`，或输入含"不校验"/"跳过验证" |
| 3（最低） | `config.json` 的 `sql_validation` | `true`（默认）/ `false` |

默认启用 SQL 校验。三层都是「关闭能力」，不会强制开启。

**⚠️ 重要**：`data_platform.engine` 必须设为 `"Spark"`，不能用 `"Presto"`。

### 配置位置

配置文件路径：`~/.workbuddy/skills/dashboard-agent/scripts/config.json`

## 工作流程

1. **输入需求**：用户描述业务需求和数据源
2. **字段类型自动拉取**：当用户指定表名时，自动调用数据平台接口获取表详情，得到真实字段信息
3. **流水线执行**：6个Agent串联执行，实时展示进度
4. **方案确认**：查看方案文档，逐项确认，可局部重跑
5. **BI推送**：确认后自动推送到BI平台创建语义模型

### 字段自动拉取说明

当用户在 `data_sources` 中指定表名时，语义模型 Agent 会：
1. 自动调用数据平台 `DESCRIBE` 接口获取表结构
2. 获取每个字段的名称、类型、注释
3. 将字段信息注入到 `column_types` 供 LLM 使用
4. LLM 会严格遵循真实字段类型生成 SQL

这样可以避免 LLM 猜测字段名导致的 SQL 错误。

## 示例输入

参考 `references/examples/ecommerce_daily.json` - 电商运营日报的完整输入示例。
