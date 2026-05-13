# 用户行为分析看板 — BI看板搭建方案

> 生成时间：2026-05-08
> 方案版本：v1.0

---

## 一、看板概述

### 1.1 基本信息
| 项目 | 内容 |
|------|------|
| 看板名称 | 用户行为分析看板 |
| 目标受众 | 产品经理、运营团队、数据分析师 |
| 看板目标 | 全面分析用户行为数据，包括活跃度、访问量、会话时长等核心指标的趋势和分布 |

### 1.2 核心业务问题
- 每日用户活跃度和访问趋势如何？是否有周期性波动？
- 不同模块和页面的访问分布情况如何？哪些页面最受欢迎？
- 关键用户和普通用户的行为差异是什么？
- 用户会话时长和页面停留时长的分布特征？
- 有效访问和无效访问的比例及变化趋势？

### 1.3 数据源
- `iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view`：用户模块页面访问明细表

### 1.4 指标一览
| 指标名称 | 类型 | 口径定义 | 单位 | 口径状态 |
|---------|------|---------|------|----------|
| DAU | 原子指标 | 日活跃用户数，按uid去重计数 | 人 | ⚠️ 口径待确认 |
| 页面访问次数 | 原子指标 | 总页面访问次数，按记录数计数 | 次 | ✅ 口径已确认 |
| 会话数 | 原子指标 | 用户会话总数，按session_id去重计数 | 个 | ✅ 口径已确认 |
| 平均会话时长 | 衍生指标 | 用户平均会话时长，按session_id分组计算时长后取平均 | 秒 | ⚠️ 口径待确认 |
| 关键用户占比 | 复合指标 | 关键用户在总用户中的比例 | % | ⚠️ 口径待确认 |
| 有效访问占比 | 复合指标 | 有效访问在总访问中的比例 | % | ⚠️ 口径待确认 |

> **口径状态说明**：
> - ✅ 口径已确认 = 该指标的口径定义无待确认项，可直接使用
> - ⚠️ 口径待确认 = 该指标的口径定义存在待确认项，请先处理第四章对应确认项后再搭建

---

## 二、语义模型搭建指南

### 2.1 模型：dm_user_behavior_daily（模型ID：505503）

> **注意**：`model_id` 来自 BI 推送 Agent 的输出（`from_bi_push.results` 中对应 `model_name` 的 `model_id`）。

**用途**：用户行为日粒度汇总数据，支持多维度下钻分析

#### SQL 语句

````sql
-- 用户行为分析语义模型
-- 覆盖指标：DAU、页面访问次数、会话数、平均会话时长、关键用户占比、有效访问占比
-- 数据粒度：页面访问记录（按日期和维度聚合）

SELECT
    -- 时间维度
    date AS analysis_date,
    
    -- 模块层级维度
    module,
    sub_module,
    sub_sub_module,
    sub_sub_sub_module,
    
    -- 页面维度
    page_name,
    page_key_name,
    
    -- 部门层级维度
    dept1_name,
    dept2_name,
    dept3_name,
    dept4_name,
    dept5_name,
    
    -- 用户类型维度
    is_kp_user,
    is_valid,
    
    -- 原子指标
    -- DAU: 日活跃用户数（按uid去重计数）
    -- TODO: 需确认DAU口径
    COUNT(DISTINCT uid) AS dau,
    
    -- 页面访问次数（总记录数）
    COUNT(*) AS page_view_count,
    
    -- 会话数（按session_id去重计数）
    COUNT(DISTINCT session_id) AS session_count,
    
    -- 衍生指标
    -- 平均会话时长：按session_id分组计算时长后取平均
    -- TODO: 需确认e_ts时间单位和会话时长计算逻辑
    AVG(
        CASE 
            WHEN session_id IS NOT NULL THEN 
                (MAX(e_ts) OVER (PARTITION BY session_id) - MIN(e_ts) OVER (PARTITION BY session_id))
            ELSE NULL
        END
    ) AS avg_session_duration,
    
    -- 关键用户占比：关键用户在总用户中的比例
    -- TODO: 需确认is_kp_user字段取值
    COUNT(DISTINCT CASE WHEN is_kp_user = '是' THEN uid END) * 100.0 / NULLIF(COUNT(DISTINCT uid), 0) AS kp_user_ratio,
    
    -- 有效访问占比：有效访问在总访问中的比例
    -- TODO: 需确认is_valid字段取值
    COUNT(CASE WHEN is_valid = '是' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS valid_visit_ratio,
    
    -- 辅助指标（用于计算衍生指标）
    COUNT(DISTINCT CASE WHEN is_kp_user = '是' THEN uid END) AS kp_user_count,
    COUNT(CASE WHEN is_valid = '是' THEN 1 END) AS valid_visit_count

FROM iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view

-- 当前无模型级过滤条件，所有过滤在图表层实现
WHERE 1=1

GROUP BY
    date,
    module,
    sub_module,
    sub_sub_module,
    sub_sub_sub_module,
    page_name,
    page_key_name,
    dept1_name,
    dept2_name,
    dept3_name,
    dept4_name,
    dept5_name,
    is_kp_user,
    is_valid
````

> **💡 SQL 说明**：
> 1. 单表模型：基于 iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view 构建
> 2. 维度设计：包含时间、模块层级、页面、部门层级、用户类型等多维度
> 3. 指标计算：
>    - DAU：按uid去重计数（需确认口径）
>    - 页面访问次数：直接计数
>    - 会话数：按session_id去重计数
>    - 平均会话时长：使用窗口函数计算session_id内的时长差异（需确认e_ts时间单位）
>    - 关键用户占比：使用CASE WHEN + NULLIF防除零
>    - 有效访问占比：使用CASE WHEN + NULLIF防除零
> 4. 过滤策略：所有过滤条件在图表层实现，模型层无硬编码过滤
> 5. 数据质量：所有除法运算使用NULLIF保护，避免除零错误

#### 维度配置

| 字段名 | 来源表 | 数据类型 | 语义类型 | 配置说明 |
|--------|--------|---------|---------|---------|
| analysis_date | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | DATE | 日期 | 配置为时间维度，支持按日、周、月聚合 |
| module | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为层级维度第一级，支持下钻到子模块 |
| sub_module | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为层级维度第二级，parent为module |
| sub_sub_module | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为层级维度第三级，parent为sub_module |
| sub_sub_sub_module | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为层级维度第四级，parent为sub_sub_module |
| page_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持按页面名称筛选 |
| page_key_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持按页面关键标识筛选 |
| dept1_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为部门层级第一级，支持下钻到下级部门 |
| dept2_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为部门层级第二级，parent为dept1_name |
| dept3_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为部门层级第三级，parent为dept2_name |
| dept4_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为部门层级第四级，parent为dept3_name |
| dept5_name | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 层级 | 配置为部门层级第五级，parent为dept4_name |
| is_kp_user | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持按关键用户标识筛选 |
| is_valid | iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持按访问有效性筛选 |

#### 指标配置

| 字段名 | 聚合方式 | SQL 表达式 | 依赖指标 | 单位 | 配置状态 |
|--------|---------|-----------|---------|------|----------|
| dau | COUNT_DISTINCT | COUNT(DISTINCT uid) | 无 | 人 | ⚠️ 配置待确认 |
| page_view_count | COUNT | COUNT(*) | 无 | 次 | ✅ 配置已确认 |
| session_count | COUNT_DISTINCT | COUNT(DISTINCT session_id) | 无 | 个 | ✅ 配置已确认 |
| avg_session_duration | AVG | AVG(CASE WHEN session_id IS NOT NULL THEN (MAX(e_ts) OVER (PARTITION BY session_id) - MIN(e_ts) OVER (PARTITION BY session_id)) ELSE NULL END) | 无 | 秒 | ⚠️ 配置待确认 |
| kp_user_ratio | 自定义 | COUNT(DISTINCT CASE WHEN is_kp_user = '是' THEN uid END) * 100.0 / NULLIF(COUNT(DISTINCT uid), 0) | dau | % | ⚠️ 配置待确认 |
| valid_visit_ratio | 自定义 | COUNT(CASE WHEN is_valid = '是' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) | page_view_count | % | ⚠️ 配置待确认 |
| kp_user_count | COUNT_DISTINCT | COUNT(DISTINCT CASE WHEN is_kp_user = '是' THEN uid END) | 无 | 人 | ⚠️ 配置待确认 |
| valid_visit_count | COUNT | COUNT(CASE WHEN is_valid = '是' THEN 1 END) | 无 | 次 | ⚠️ 配置待确认 |

> **配置状态说明**：
> - ✅ 配置已确认 = 该指标的配置无待确认项
> - ⚠️ 配置待确认 = 该指标的配置存在待确认项，详见第四章

> **自定义指标配置**：在BI平台添加为自定义指标，使用百分比格式显示

#### 关联逻辑

| 左表 | 关联方式 | 右表 | 关联条件 | 原因 |
|------|---------|------|---------|------|
| iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view | 无 | 无 | 无 | 单表模型，所有字段均来自同一张表，无需JOIN |

#### 过滤条件

**模型级过滤（写入 SQL WHERE）**：
- 无模型级过滤条件，所有过滤在图表层实现

**图表级过滤（配置筛选器）**：
- date：日期范围，默认"最近30天"
- module：多选，默认"全部"
- sub_module：多选，默认"全部"
- sub_sub_module：多选，默认"全部"
- sub_sub_sub_module：多选，默认"全部"
- page_name：多选，默认"全部"
- page_key_name：多选，默认"全部"
- dept1_name：多选，默认"全部"
- dept2_name：多选，默认"全部"
- dept3_name：多选，默认"全部"
- dept4_name：多选，默认"全部"
- dept5_name：多选，默认"全部"
- is_kp_user：单选，默认"全部"
- is_valid：单选，默认"全部"

**指标级过滤（CASE WHEN）**：
- kp_user_ratio：通过CASE WHEN实现关键用户筛选逻辑
- valid_visit_ratio：通过CASE WHEN实现有效访问筛选逻辑

#### ⚠️ 数据质量注意事项

- **NULL处理**：维度字段可能存在NULL值，BI平台需配置NULL值的显示方式（建议将NULL显示为'未知'或'未分类'）
- **除零保护**：关键用户占比和有效访问占比使用NULLIF保护分母为0的情况（分母为0时返回NULL，BI平台可配置为显示0%或'-'）
- **数据重复**：平均会话时长使用窗口函数计算，需确保session_id分组逻辑正确（建议验证session_id的唯一性和完整性）
- **性能提示**：窗口函数在大数据量下可能影响性能，建议监控查询效率（如性能不佳，可考虑预计算会话时长）
- **计算限制**：页面平均停留时长在当前表结构下无法准确计算，需要页面跳转序列数据（建议补充页面跳转时间戳字段或使用专门的页面流表）

---

## 三、看板布局方案

### 3.1 整体布局

布局采用从上到下、从左到右的信息流：第1行4个核心指标卡片（各占3列），第2行趋势分析图表（各占6列），第3行模块分布和会话时长分析（4+4+4列），第4行用户类型和页面排名分析（3+3+6列），第5行明细表格（占满12列）。视线从核心指标→趋势分析→模块下钻→用户分层→明细数据，符合总览到细节的分析逻辑

```
布局示意（12列网格）：
┌────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
│ chart_01 (3列)  │ chart_02 (3列)  │ chart_03 (3列)  │ chart_04 (3列)  │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_05 (6列 - DAU趋势分析)                                 │ chart_06 (6列 - 页面访问趋势)                                 │
├────────┬────────┬────────┬────────┬────────┬────────┼────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_07 (4列 - 模块DAU分布) │ chart_08 (4列 - 模块访问量分布) │ chart_09 (4列 - 会话时长趋势) │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_10 (3列 - 用户类型分布) │ chart_11 (3列 - 访问有效性分析) │ chart_12 (6列 - 热门页面排名) │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_13 (12列 - 用户行为明细)                                                                              │
└────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
```

### 3.2 图表配置明细

#### chart_01：DAU

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | analysis_date |
| 指标 | dau（格式：#,##0） |
| 排序 | analysis_date ASC |
| 位置 | 第1行 第1列，占1行3列 |

**交互**：联动chart_05、chart_07，通过analysis_date维度联动

**设计说明**：核心活跃指标，放在左上第一位，附带趋势线展示周期性波动

---

#### chart_02：页面访问次数

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | analysis_date |
| 指标 | page_view_count（格式：#,##0） |
| 排序 | analysis_date ASC |
| 位置 | 第1行 第4列，占1行3列 |

**交互**：联动chart_06、chart_08，通过analysis_date维度联动

**设计说明**：访问量核心指标，紧跟DAU，展示整体访问趋势

---

#### chart_03：会话数

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | analysis_date |
| 指标 | session_count（格式：#,##0） |
| 排序 | analysis_date ASC |
| 位置 | 第1行 第7列，占1行3列 |

**交互**：联动chart_09，通过analysis_date维度联动

**设计说明**：会话数量指标，反映用户访问频次

---

#### chart_04：关键用户占比

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | analysis_date |
| 指标 | kp_user_ratio（格式：0.00%） |
| 排序 | analysis_date ASC |
| 位置 | 第1行 第10列，占1行3列 |

**交互**：联动chart_10，通过analysis_date维度联动

**设计说明**：用户分层分析，展示关键用户占比趋势

---

#### chart_05：DAU趋势分析

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | analysis_date |
| 指标 | dau（格式：#,##0） |
| 排序 | analysis_date ASC |
| 位置 | 第2行 第1列，占1行6列 |

**交互**：支持按module、dept1_name、is_kp_user维度下钻

**设计说明**：DAU详细趋势分析，支持按模块、部门、用户类型下钻

---

#### chart_06：页面访问趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | analysis_date |
| 指标 | page_view_count（格式：#,##0） |
| 排序 | analysis_date ASC |
| 位置 | 第2行 第7列，占1行6列 |

**交互**：支持按module、page_name、is_valid维度下钻

**设计说明**：页面访问量趋势分析，支持按模块、页面、有效性下钻

---

#### chart_07：各模块DAU分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | module |
| 指标 | dau（格式：#,##0） |
| 排序 | dau DESC，限制10条 |
| 位置 | 第3行 第1列，占1行4列 |

**交互**：联动chart_08、chart_11，通过module维度联动；支持按sub_module、sub_sub_module下钻

**设计说明**：模块活跃度排名，条形图适合多分类对比，支持模块层级下钻

---

#### chart_08：各模块访问量分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | module |
| 指标 | page_view_count（格式：#,##0） |
| 排序 | page_view_count DESC，限制10条 |
| 位置 | 第3行 第5列，占1行4列 |

**交互**：联动chart_07、chart_11，通过module维度联动；支持按sub_module、sub_sub_module下钻

**设计说明**：模块访问量排名，与DAU分布并列分析，支持联动

---

#### chart_09：平均会话时长趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | analysis_date |
| 指标 | avg_session_duration（格式：#,##0） |
| 排序 | analysis_date ASC |
| 位置 | 第3行 第9列，占1行4列 |

**交互**：支持按module、is_kp_user维度下钻

**设计说明**：用户会话时长分析，展示用户粘性变化趋势

---

#### chart_10：用户类型分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 环形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | is_kp_user |
| 指标 | kp_user_count（格式：#,##0） |
| 排序 | 无 |
| 位置 | 第4行 第1列，占1行3列 |

**交互**：联动chart_11，通过is_kp_user维度联动

**设计说明**：关键用户与普通用户构成分析，环形图适合展示占比

---

#### chart_11：访问有效性分析

| 项目 | 配置 |
|------|------|
| 图表类型 | 环形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | is_valid |
| 指标 | valid_visit_count（格式：#,##0） |
| 排序 | 无 |
| 位置 | 第4行 第4列，占1行3列 |

**交互**：联动chart_10，通过is_valid维度联动

**设计说明**：有效访问与无效访问构成分析，评估访问质量

---

#### chart_12：热门页面访问排名

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | page_name |
| 指标 | page_view_count（格式：#,##0） |
| 排序 | page_view_count DESC，限制15条 |
| 位置 | 第4行 第7列，占1行6列 |

**交互**：支持按module、sub_module维度下钻

**设计说明**：页面受欢迎程度分析，条形图适合多页面排名展示

---

#### chart_13：用户行为明细

| 项目 | 配置 |
|------|------|
| 图表类型 | 数据表格 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | detail |
| 维度 | analysis_date、module、sub_module、page_name、dept1_name、is_kp_user、is_valid |
| 指标 | dau、page_view_count、session_count、avg_session_duration |
| 排序 | analysis_date DESC |
| 位置 | 第5行 第1列，占1行12列 |

**交互**：无特殊交互

**设计说明**：明细数据表格，支持多维度组合查看和排序

---

### 3.3 全局筛选器

| 筛选器 | 字段 | 类型 | 默认值 | 作用范围 |
|--------|------|------|--------|---------|
| 分析日期 | analysis_date | 日期范围 | 最近30天 | 所有图表 |
| 模块 | module | 多选 | 全部 | 所有图表 |
| 一级部门 | dept1_name | 多选 | 全部 | 所有图表 |
| 用户类型 | is_kp_user | 单选 | 全部 | 所有图表 |
| 访问有效性 | is_valid | 单选 | 全部 | 所有图表 |

---

## 四、待确认项清单

> ⚠️ 以下项目需要在搭建前完成确认，按风险从高到低排列。

| # | 类别 | 确认内容 | 风险 | 建议值 |
|---|------|---------|------|--------|
| 1 | 指标口径 | DAU的计算口径：按uid去重计数还是按session_id去重计数 | 如果口径不一致会导致活跃用户数统计偏差 | 建议按uid去重计数 |
| 2 | 指标口径 | 会话时长的计算逻辑：如何通过e_ts字段计算会话时长 | 会话时长计算错误会影响用户行为分析的准确性 | 建议按session_id分组，计算最大e_ts与最小e_ts的差值，需要确认e_ts的时间单位 |
| 3 | 指标口径 | 关键用户(is_kp_user)的具体定义标准 | 关键用户定义不清晰会影响用户分层分析的准确性 | 需要明确is_kp_user字段的取值含义（如'是'/'否'或其他编码） |
| 4 | 指标口径 | 有效访问(is_valid)的具体判定标准 | 无效访问过滤不准确会影响数据分析质量 | 需要明确is_valid字段的取值含义和判定逻辑 |
| 5 | 指标口径 | 页面停留时长的计算逻辑：是否需要考虑页面跳转时间差 | 停留时长计算不准确会影响页面效果评估 | 当前表结构可能无法准确计算页面停留时长，建议确认计算可行性 |
| 6 | SQL逻辑 | 平均会话时长的窗口函数实现方式是否正确 | 窗口函数使用不当可能导致会话时长计算错误 | 建议验证窗口函数在聚合场景下的正确性 |
| 7 | 数据质量 | session_id字段的完整性和唯一性 | session_id不完整或重复会影响会话相关指标的准确性 | 建议验证session_id的数据质量 |
| 8 | 其他 | e_ts字段的时间单位（秒/毫秒/微秒） | 时间单位错误会导致时长计算严重偏差 | 需要确认e_ts的时间单位以便正确计算会话时长 |
| 9 | 维度粒度 | 时间分析粒度：按天、周、月还是其他时间维度 | 时间粒度选择不当会影响趋势分析的准确性 | 建议默认按天分析，支持按周、月聚合 |
| 10 | 维度粒度 | 模块层级分析深度：需要分析到哪一级模块（sub_sub_sub_module） | 层级过深或过浅都会影响分析效果 | 建议支持多级钻取分析，但默认展示到合理层级 |
| 11 | 数据源 | 数据时间范围：需要分析哪个时间段的数据 | 时间范围选择不当会影响分析结论的时效性 | 建议默认最近30天 |
| 12 | 数据源 | Part 0字段的具体含义和用途 | 不了解该字段含义可能导致数据使用错误 | 需要明确Part 0字段的业务含义 |
| 13 | 过滤条件 | 是否需要添加默认的时间范围过滤 | 无时间过滤可能导致查询数据量过大 | 建议在图表层设置默认时间范围（如最近30天） |
| 14 | 图表类型 | 平均会话时长展示方式：当前用折线图展示趋势，是否需要增加分布直方图展示时长分布特征 | 仅展示平均值可能掩盖极端值影响，无法反映真实分布情况 | 建议增加会话时长分布直方图，与趋势图配合分析 |
| 15 | 布局设计 | 模块层级下钻深度：当前设计支持到三级模块，是否需要支持四级模块下钻 | 层级过深可能导致图表过于复杂，层级过浅可能无法满足深度分析需求 | 建议默认展示到二级模块，支持手动下钻到更细粒度 |
| 16 | 交互设计 | 用户类型与模块的交叉分析：当前为独立图表，是否需要增加交叉分析图表 | 独立分析可能无法发现关键用户在不同模块的行为差异 | 建议增加关键用户在各模块的访问行为对比图表 |
| 17 | 维度选择 | 部门层级分析深度：当前使用一级部门，是否需要支持多级部门下钻分析 | 一级部门粒度可能过粗，无法满足精细化部门分析需求 | 建议支持部门层级下钻，但默认展示一级部门聚合数据 |

---

## 五、搭建步骤建议

1. **确认待确认项**：先完成第四章的所有确认项，特别是指标口径相关
2. **创建语义模型**：按第二章顺序，在 BI 平台创建语义模型，粘贴 SQL，验证字段解析
3. **调整维度/指标**：检查 BI 平台自动解析的维度和指标，按配置说明手动调整
4. **创建看板**：选择语义模型，按第三章顺序添加图表
5. **配置筛选器**：添加全局筛选器，按配置设置默认值
6. **配置交互**：设置图表联动和下钻
7. **验证数据**：用已知数据验证关键指标的准确性

---

## 六、看板搭建指令

> **说明**：以下是标准化的看板搭建指令，可作为编辑助手 API 的入参。指令由看板指令生成 Agent 自动生成，供人工审查和未来自动化使用。

### 6.1 可读摘要

**看板标题**：用户行为分析看板
**语义模型**：dm_user_behavior_daily（ID: 505503）
**图表**：
  - 1. DAU — 指标趋势图，展示日活跃用户趋势
  - 2. 页面访问次数 — 指标趋势图，展示访问量趋势
  - 3. 会话数 — 指标趋势图，展示用户访问频次
  - 4. 关键用户占比 — 指标趋势图，展示用户分层占比
  - 5. DAU趋势分析 — 折线图，支持多维度下钻
  - 6. 页面访问趋势 — 折线图，支持多维度下钻
  - 7. 各模块DAU分布 — 条形图，模块活跃度排名
  - 8. 各模块访问量分布 — 条形图，模块访问量排名
  - 9. 平均会话时长趋势 — 折线图，用户粘性分析
  - 10. 用户类型分布 — 环形图，关键用户构成
  - 11. 访问有效性分析 — 环形图，访问质量评估
  - 12. 热门页面访问排名 — 条形图，页面受欢迎程度
  - 13. 用户行为明细 — 数据表格，多维度明细数据
**筛选器**：5个全局筛选器（日期范围、模块、部门、用户类型、访问有效性），联动所有图表

### 6.2 结构化指令（JSON）

```json
{
  "instruction_id": "20260508_114500",
  "title": "用户行为分析看板",
  "semantic_model": {
    "id": 505503,
    "name": "dm_user_behavior_daily"
  },
  "description": "全面分析用户行为数据，包括活跃度、访问量、会话时长等核心指标的趋势和分布",
  "charts": [
    {
      "chart_id": "chart_01",
      "title": "DAU",
      "position": {
        "row": 1,
        "col": 1,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "dau",
          "alias": "DAU"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "核心活跃指标趋势分析"
    },
    {
      "chart_id": "chart_02",
      "title": "页面访问次数",
      "position": {
        "row": 1,
        "col": 4,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "page_view_count",
          "alias": "页面访问次数"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "访问量核心指标趋势分析"
    },
    {
      "chart_id": "chart_03",
      "title": "会话数",
      "position": {
        "row": 1,
        "col": 7,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "session_count",
          "alias": "会话数"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "用户访问频次分析"
    },
    {
      "chart_id": "chart_04",
      "title": "关键用户占比",
      "position": {
        "row": 1,
        "col": 10,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "kp_user_ratio",
          "alias": "关键用户占比"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "用户分层占比趋势分析"
    },
    {
      "chart_id": "chart_05",
      "title": "DAU趋势分析",
      "position": {
        "row": 2,
        "col": 1,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "dau",
          "alias": "DAU"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "line",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "DAU详细趋势分析，支持多维度下钻"
    },
    {
      "chart_id": "chart_06",
      "title": "页面访问趋势",
      "position": {
        "row": 2,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "page_view_count",
          "alias": "页面访问次数"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "line",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "页面访问量趋势分析，支持多维度下钻"
    },
    {
      "chart_id": "chart_07",
      "title": "各模块DAU分布",
      "position": {
        "row": 3,
        "col": 1,
        "width": 4,
        "height": 1
      },
      "metrics": [
        {
          "field": "dau",
          "alias": "DAU"
        }
      ],
      "dimensions": [
        {
          "field": "module",
          "alias": "模块"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "dau",
        "order": "desc"
      },
      "limit": 10,
      "sql_hint": "模块活跃度排名分析"
    },
    {
      "chart_id": "chart_08",
      "title": "各模块访问量分布",
      "position": {
        "row": 3,
        "col": 5,
        "width": 4,
        "height": 1
      },
      "metrics": [
        {
          "field": "page_view_count",
          "alias": "页面访问次数"
        }
      ],
      "dimensions": [
        {
          "field": "module",
          "alias": "模块"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "page_view_count",
        "order": "desc"
      },
      "limit": 10,
      "sql_hint": "模块访问量排名分析"
    },
    {
      "chart_id": "chart_09",
      "title": "平均会话时长趋势",
      "position": {
        "row": 3,
        "col": 9,
        "width": 4,
        "height": 1
      },
      "metrics": [
        {
          "field": "avg_session_duration",
          "alias": "平均会话时长"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        }
      ],
      "chart_type": "line",
      "sort": {
        "field": "analysis_date",
        "order": "asc"
      },
      "limit": null,
      "sql_hint": "用户会话时长趋势分析"
    },
    {
      "chart_id": "chart_10",
      "title": "用户类型分布",
      "position": {
        "row": 4,
        "col": 1,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "kp_user_count",
          "alias": "关键用户数量"
        }
      ],
      "dimensions": [
        {
          "field": "is_kp_user",
          "alias": "是否关键用户"
        }
      ],
      "chart_type": "donut",
      "sort": null,
      "limit": null,
      "sql_hint": "关键用户与普通用户构成分析"
    },
    {
      "chart_id": "chart_11",
      "title": "访问有效性分析",
      "position": {
        "row": 4,
        "col": 4,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "valid_visit_count",
          "alias": "有效访问次数"
        }
      ],
      "dimensions": [
        {
          "field": "is_valid",
          "alias": "是否有效"
        }
      ],
      "chart_type": "donut",
      "sort": null,
      "limit": null,
      "sql_hint": "有效访问与无效访问构成分析"
    },
    {
      "chart_id": "chart_12",
      "title": "热门页面访问排名",
      "position": {
        "row": 4,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "page_view_count",
          "alias": "页面访问次数"
        }
      ],
      "dimensions": [
        {
          "field": "page_name",
          "alias": "页面名称"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "page_view_count",
        "order": "desc"
      },
      "limit": 15,
      "sql_hint": "页面受欢迎程度排名分析"
    },
    {
      "chart_id": "chart_13",
      "title": "用户行为明细",
      "position": {
        "row": 5,
        "col": 1,
        "width": 12,
        "height": 1
      },
      "metrics": [
        {
          "field": "dau",
          "alias": "DAU"
        },
        {
          "field": "page_view_count",
          "alias": "页面访问次数"
        },
        {
          "field": "session_count",
          "alias": "会话数"
        },
        {
          "field": "avg_session_duration",
          "alias": "平均会话时长"
        }
      ],
      "dimensions": [
        {
          "field": "analysis_date",
          "alias": "分析日期"
        },
        {
          "field": "module",
          "alias": "模块"
        },
        {
          "field": "sub_module",
          "alias": "子模块"
        },
        {
          "field": "page_name",
          "alias": "页面名称"
        },
        {
          "field": "dept1_name",
          "alias": "一级部门"
        },
        {
          "field": "is_kp_user",
          "alias": "是否关键用户"
        },
        {
          "field": "is_valid",
          "alias": "是否有效"
        }
      ],
      "chart_type": "table",
      "sort": {
        "field": "analysis_date",
        "order": "desc"
      },
      "limit": null,
      "sql_hint": "用户行为明细数据表格"
    }
  ],
  "filters": [
    {
      "filter_id": "filter_01",
      "title": "分析日期",
      "field": "analysis_date",
      "type": "date_range",
      "default": "最近30天",
      "linked_charts": []
    },
    {
      "filter_id": "filter_02",
      "title": "模块",
      "field": "module",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_03",
      "title": "一级部门",
      "field": "dept1_name",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_04",
      "title": "用户类型",
      "field": "is_kp_user",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_05",
      "title": "访问有效性",
      "field": "is_valid",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    }
  ],
  "layout": {
    "columns": 12,
    "row_height": 80,
    "charts": [
      {
        "chart_id": "chart_01",
        "x": 0,
        "y": 0,
        "w": 3,
        "h": 1
      },
      {
        "chart_id": "chart_02",
        "x": 3,
        "y": 0,
        "w": 3,
        "h": 1
      },
      {
        "chart_id": "chart_03",
        "x": 6,
        "y": 0,
        "w": 3,
        "h": 1
      },
      {
        "chart_id": "chart_04",
        "x": 9,
        "y": 0,
        "w": 3,
        "h": 1
      },
      {
        "chart_id": "chart_05",
        "x": 0,
        "y": 80,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_06",
        "x": 6,
        "y": 80,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_07",
        "x": 0,
        "y": 160,
        "w": 4,
        "h": 1
      },
      {
        "chart_id": "chart_08",
        "x": 4,
        "y": 160,
        "w": 4,
        "h": 1
      },
      {
        "chart_id": "chart_09",
        "x": 8,
        "y": 160,
        "w": 4,
        "h": 1
      },
      {
        "chart_id": "chart_10",
        "x": 0,
        "y": 240,
        "w": 3,
        "h": 1
      },
      {
        "chart_id": "chart_11",
        "x": 3,
        "y": 240,
        "w": 3,
        "h": 1
      },
      {
        "chart_id": "chart_12",
        "x": 6,
        "y": 240,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_13",
        "x": 0,
        "y": 320,
        "w": 12,
        "h": 1
      }
    ]
  },
  "summary": "**看板标题**：用户行为分析看板\n**语义模型**：dm_user_behavior_daily（ID: 505503）\n**图表**：\n  - 1. DAU — 指标趋势图，展示日活跃用户趋势\n  - 2. 页面访问次数 — 指标趋势图，展示访问量趋势\n  - 3. 会话数 — 指标趋势图，展示用户访问频次\n  - 4. 关键用户占比 — 指标趋势图，展示用户分层占比\n  - 5. DAU趋势分析 — 折线图，支持多维度下钻\n  - 6. 页面访问趋势 — 折线图，支持多维度下钻\n  - 7. 各模块DAU分布 — 条形图，模块活跃度排名\n  - 8. 各模块访问量分布 — 条形图，模块访问量排名\n  - 9. 平均会话时长趋势 — 折线图，用户粘性分析\n  - 10. 用户类型分布 — 环形图，关键用户构成\n  - 11. 访问有效性分析 — 环形图，访问质量评估\n  - 12. 热门页面访问排名 — 条形图，页面受欢迎程度\n  - 13. 用户行为明细 — 数据表格，多维度明细数据\n**筛选器**：5个全局筛选器（日期范围、模块、部门、用户类型、访问有效性），联动所有图表"
}
```

> 💡 **使用提示**：复制上方 JSON 可直接作为 BI 平台编辑助手 API 的入参，实现看板的自动搭建。

---

*本文档由看板开发 Agent 自动生成，如有疑问请联系数据团队*