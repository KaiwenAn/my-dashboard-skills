# 看板开发 Agent 使用指南

> 一键生成 BI 看板搭建方案的数据分析师提效工具

## 目录

- [快速开始](#快速开始)
- [核心能力](#核心能力)
- [输入格式详解](#输入格式详解)
- [使用示例](#使用示例)
- [输出说明](#输出说明)
- [配置指南](#配置指南)
- [常见问题](#常见问题)

---

## 快速开始

### 方式一：自然语言触发（推荐）

在 WorkBuddy 中加载 Skill 后，直接用自然语言描述需求：

```
帮我做一个电商运营日报看板，包含GMV、客单价、新老客占比等指标
数据源是 dwd_order_detail 和 dim_user 两张表
```

### 方式二：CLI 执行

```bash
# 进入工作空间
cd c:\Users\Kai\WorkBuddy\20260427134240

# 执行 Pipeline
python main.py --input examples/ecommerce_daily.json --output ./output
```

---

## 核心能力

### 6 个 Agent 流水线

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  需求解析    │───▶│  语义模型    │───▶│   BI推送    │───▶│  图表设计    │───▶│  看板指令    │───▶│  方案生成    │
│ Requirements │    │   SQL Gen   │    │BI Publish   │    │Chart Design │    │Instruction  │    │   Solution  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

| Agent | 职责 | 提效效果 |
|-------|------|----------|
| **需求解析** | 口径守门人，识别歧义，7步推理策略 | 减少返工 |
| **语义模型** | SQL生成，NULLIF防除零，三层过滤 | 核心提效 |
| **BI推送** | 自动创建语义模型到BI平台 | 一键发布 |
| **图表设计** | 12列网格布局，图表类型推荐 | 专业设计 |
| **看板指令** | 标准化JSON指令，可审查可执行 | 接口标准化 |
| **方案生成** | Markdown方案文档 | 即取即用 |

### 提效数据

- **一期（仅方案）**：3-4x 提效
- **二期（打通BI API）**：可达 8-10x 提效
- **语义模型SQL**：直接可用，无需修改

---

## 输入格式详解

### 最小可用输入

```json
{
  "dashboard_meta": {
    "title": "看板标题"
  },
  "data_sources": [
    {
      "table_name": "表名",
      "key_fields": ["字段1", "字段2"]
    }
  ],
  "metrics_requirement": [
    {"name": "指标名称"}
  ]
}
```

### 完整输入格式

```json
{
  "dashboard_meta": {
    "title": "电商运营日报",
    "audience": "运营团队",
    "goal": "监控每日核心经营指标"
  },

  "data_sources": [
    {
      "table_name": "dwd_order_detail",
      "description": "订单明细表，每日增量",
      "table_type": "fact",
      "key_fields": ["order_id", "user_id", "order_amount", "pay_time"],
      "field_mappings": {
        "real_app_id": "app_id"
      },
      "field_descriptions": {
        "order_amount": "订单金额，已扣除退款"
      }
    },
    {
      "table_name": "dim_user",
      "description": "用户维度表",
      "table_type": "dimension",
      "key_fields": ["user_id", "province", "user_type"]
    }
  ],

  "join_hints": [
    {
      "left_table": "dwd_order_detail",
      "right_table": "dim_user",
      "join_on": "dwd_order_detail.user_id = dim_user.user_id",
      "join_type": "LEFT JOIN",
      "notes": "用户维度表作为维度使用"
    }
  ],

  "metrics_requirement": [
    {"name": "GMV", "description": "成交总额"},
    {"name": "客单价", "description": "平均每单金额"}
  ],

  "dimensions_requirement": [
    {"name": "日期"},
    {"name": "地区"}
  ],

  "filters_known": [
    {
      "field": "date",
      "operator": "BETWEEN",
      "value": ["2024-01-01", "2024-01-31"],
      "applies_to_all_tables": true
    }
  ],

  "additional_notes": "时间范围默认最近30天"
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `dashboard_meta.title` | ✅ | 看板标题 |
| `dashboard_meta.audience` | ❌ | 目标受众 |
| `dashboard_meta.goal` | ❌ | 看板目标 |
| `data_sources` | ✅ | 数据源列表，至少1项 |
| `data_sources[].table_name` | ✅ | 表名 |
| `data_sources[].key_fields` | 建议 | 关键字段列表 |
| `data_sources[].table_type` | ❌ | `fact`/`dimension`/`fact_as_dimension` |
| `data_sources[].field_mappings` | ❌ | 字段别名映射 |
| `data_sources[].field_descriptions` | ❌ | 字段含义说明 |
| `join_hints` | 建议 | 多表关联时建议提供 |
| `metrics_requirement` | ✅ | 指标需求列表 |
| `dimensions_requirement` | ❌ | 维度需求列表 |
| `filters_known` | ❌ | 已知过滤条件 |
| `additional_notes` | ❌ | 补充说明 |

### table_type 可选值

| 值 | 说明 | 示例 |
|---|------|------|
| `fact` | 事实表，主表 | 订单明细、事件表 |
| `dimension` | 维度表 | 用户表、商品表 |
| `fact_as_dimension` | 事实表当维度用，需去重 | 国家列表、活动列表 |

---

## 使用示例

### 示例 1：电商运营日报

**需求描述**：
```
帮我做一个电商运营日报看板，包含以下指标：
- GMV（成交总额）
- 客单价（平均每单金额）
- 新老客占比
- 退款率

维度：日期、商品类目、地区
数据源：dwd_order_detail（订单表）、dim_user（用户表）
```

**对应输入 JSON**：

```json
{
  "dashboard_meta": {
    "title": "电商运营日报",
    "audience": "运营团队",
    "goal": "监控每日核心经营指标，及时发现异常波动"
  },
  "data_sources": [
    {
      "table_name": "dwd_order_detail",
      "description": "订单明细表，每日增量",
      "key_fields": ["order_id", "user_id", "order_amount", "order_status", "pay_time", "category_id", "refund_amount"]
    },
    {
      "table_name": "dim_user",
      "description": "用户维度表",
      "key_fields": ["user_id", "register_date", "province", "city", "user_type"]
    }
  ],
  "metrics_requirement": [
    {"name": "GMV", "description": "成交总额"},
    {"name": "客单价", "description": "平均每单金额"},
    {"name": "新客占比", "description": "新客户GMV占比"},
    {"name": "退款率", "description": "退款金额/GMV"}
  ],
  "dimensions_requirement": [
    {"name": "日期"},
    {"name": "商品类目"},
    {"name": "地区"}
  ],
  "filters_known": [],
  "additional_notes": "时间范围默认最近30天，需要区分新老客，退款率要单独看"
}
```

### 示例 2：AB测试分析

**需求描述**：
```
分析AB测试效果，对比实验组和对照组的核心指标：
- 人均点击次数
- 转化率
- 用户留存率（次日、7日）

维度：实验分组、日期、渠道
```

### 示例 3：用户行为分析

**需求描述**：
```
分析用户在APP上的行为路径：
- DAU、WAU、MAU
- 人均使用时长
- 核心功能渗透率

维度：日期、用户类型、操作系统
```

---

## 输出说明

### 目录结构

```
output/
├── solution.md              # 完整搭建方案（Markdown）
├── solution.html            # HTML 可视化版本
├── execution_summary.json   # 执行摘要
└── agent_outputs/           # 中间产物
    ├── 1.requirements_parser.json
    ├── 2.semantic_model.json
    ├── 3.chart_design.json
    ├── 4.instruction_generator.json
    └── confirmation_items.json
```

### 方案文档结构

```
# 看板搭建方案：电商运营日报

## 一、需求解析
### 1.1 核心指标
### 1.2 维度拆解
### 1.3 待确认项

## 二、语义模型
### 2.1 SQL语句
### 2.2 维度配置
### 2.3 指标配置

## 三、图表设计
### 3.1 图表列表
### 3.2 全局筛选器
### 3.3 布局方案

## 四、看板搭建指令
### 4.1 指令详情（JSON格式）

## 五、确认项清单
### 5.1 高优先级
### 5.2 中优先级
### 5.3 低优先级
```

### 确认项说明

Pipeline 会自动识别需要人工确认的事项，按风险排序：

| 风险 | 类别 | 说明 |
|------|------|------|
| 🔴 高 | 指标口径、SQL逻辑 | 必须确认后才能使用 |
| 🟡 中 | JOIN方式、数据源 | 建议确认 |
| 🟢 低 | 图表类型、布局 | 可后续调整 |

---

## 配置指南

### config.json

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
    "base_url": "https://api-smp.dt.mi.com",
    "api_prefix": "/os"
  },
  "llm": {
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "temperature": 0.1
  }
}
```

### 环境变量

| 变量名 | 说明 |
|--------|------|
| `HUNYUAN_API_KEY` | 腾讯混元 API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `LLM_BASE_URL` | LLM API 地址 |

### ⚠️ 注意事项

1. **`data_platform.engine` 必须设为 `"Spark"`**
   - Presto 模式会触发 SparkSqlRewriter，导致 SQL 报 400 错误

2. **BI 推送需要配置 `bi_config`**
   - 只需提供 `space_id` 和 `creator`
   - `datasource_id` 会自动获取

3. **模型选择**
   - 默认：`deepseek-ai/DeepSeek-V4-Flash`（硅基流动）
   - 速度优先：DeepSeek-V3.2（2元/M tokens）
   - 质量优先：DeepSeek-V4-Flash（1元/M tokens）

---

## 常见问题

### Q1: 输入的字段名和实际表字段不一致怎么办？

使用 `field_mappings` 字段别名映射：

```json
{
  "field_mappings": {
    "实际字段名": "别名"
  }
}
```

### Q2: 多表关联怎么描述？

使用 `join_hints`：

```json
{
  "join_hints": [
    {
      "left_table": "订单表",
      "right_table": "用户表",
      "join_on": "订单表.user_id = 用户表.id",
      "join_type": "LEFT JOIN"
    }
  ]
}
```

### Q3: 某些指标需要特殊计算逻辑怎么办？

在 `additional_notes` 中描述：

```json
{
  "additional_notes": "退款率 = 退款金额 / GMV，需要在指标中用 CASE WHEN 过滤已退款订单"
}
```

### Q4: SQL 试跑失败怎么办？

Pipeline 会自动重试（最多3次），如果仍失败：
- 检查字段类型是否正确
- 确认 JOIN 条件是否正确
- 查看 `agent_outputs/2.semantic_model.json` 中的错误信息

### Q5: 生成的图表类型不满意怎么办？

在 `additional_notes` 中指定：

```json
{
  "additional_notes": "趋势用折线图，分布用饼图，对比用柱状图"
}
```

### Q6: 如何局部重新生成？

在方案确认页面点击具体确认项，Pipeline 会智能判断从哪个 Agent 重新开始：
- 指标口径相关 → 从语义模型开始
- 图表布局相关 → 从看板指令开始

---

## 最佳实践

### 1. 输入越详细，输出越准确

推荐提供：
- ✅ 完整的 `field_descriptions`（消除歧义）
- ✅ 明确的 `join_hints`（避免关联错误）
- ✅ 具体的 `additional_notes`（特殊需求说明）

### 2. 逐步确认，不贪多

建议：
- 先生成一个简单版本
- 确认核心指标口径
- 再扩展图表和维度

### 3. 利用中间产物

每个 Agent 的输出都可以单独使用：
- 语义模型 SQL → 直接在数据平台执行
- 图表设计配置 → 手动在 BI 平台配置
- 看板指令 JSON → 后续 API 自动搭建

---

## 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v1.0 | 2026-05-12 | 初始版本，支持 6 Agent 流水线 |
