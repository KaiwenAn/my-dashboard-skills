# 可优化事件成本分析看板 — BI看板搭建方案

> 生成时间：2026-05-08
> 方案版本：v1.0

---

## 一、看板概述

### 1.1 基本信息
| 项目 | 内容 |
|------|------|
| 看板名称 | 可优化事件成本分析看板 |
| 目标受众 | 数据分析师、业务负责人、技术负责人 |
| 看板目标 | 全面分析可优化事件成本，从总览指标到多维度下钻分析，识别成本优化机会 |

### 1.2 核心业务问题
- 近30天可优化成本占总成本的比例是多少？
- 哪些部门/负责人的可优化成本最高？
- 不同应用/地区的可优化成本分布情况如何？
- 可优化事件主要分布在哪些优化类型？
- 可优化成本的趋势变化如何？

### 1.3 数据源
| 表名 | 用途 |
|------|------|
| iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | 事件成本数据，包含所有成本字段 |
| iceberg_zjyprc_hadoop.meta.dwm_bill_optimize_event_v2_df | 可优化事件标识，包含opt_flg字段 |

### 1.4 指标一览
| 指标名称 | 类型 | 口径定义 | 单位 | 口径状态 |
|---------|------|---------|------|----------|
| 总成本 | 原子指标 | 所有事件的成本总和，包括charge_track、charge_use、onetrack_charge、talos_charge、table_src_charge、table_dest_charge、job_charge等成本字段之和 | 元 | ⚠️ 口径待确认 |
| 可优化成本 | 衍生指标 | 标记为可优化事件的总成本 | 元 | ⚠️ 口径待确认 |
| 可优化成本占比 | 复合指标 | 可优化成本 / 总成本 | % | ⚠️ 口径待确认 |
| 事件数量 | 原子指标 | 所有事件的总数量 | 个 | ✅ 口径已确认 |
| 可优化事件数量 | 衍生指标 | 标记为可优化的事件数量 | 个 | ⚠️ 口径待确认 |

> **口径状态说明**：
> - ✅ 口径已确认 = 该指标的口径定义无待确认项，可直接使用
> - ⚠️ 口径待确认 = 该指标的口径定义存在待确认项，请先处理第四章对应确认项后再搭建

---

## 二、语义模型搭建指南

### 2.1 模型：dm_optimizable_event_cost_analysis（模型ID：505505）

> **注意**：`model_id` 来自 BI 推送 Agent 的输出（`from_bi_push.results` 中对应 `model_name` 的 `model_id`）。

**用途**：可优化事件成本分析模型，支持按时间、应用、地区、事件类型、部门层级等多维度分析成本结构和优化机会

#### SQL 语句

````sql
-- 可优化事件成本分析语义模型
-- 覆盖指标：总成本、可优化成本、可优化成本占比、事件数量、可优化事件数量
-- 数据粒度：事件级别（按event_guid去重）
-- 时间范围：最近30天

SELECT
    -- 维度字段（全部来自上游指定的source_table）
    ec.date AS date,                           -- 日期维度（来自成本表）
    ec.app_id AS app_id,                       -- 应用维度
    ec.region AS region,                       -- 地区维度
    ec.event_name AS event_name,               -- 事件类型维度
    ec.bu_owner AS bu_owner,                   -- 业务负责人
    ec.bu_owner_cn AS bu_owner_cn,             -- 业务负责人中文名
    ec.tech_owner AS tech_owner,               -- 技术负责人
    ec.tech_owner_cn AS tech_owner_cn,         -- 技术负责人中文名
    ec.bu_dept1_name AS bu_dept1_name,         -- 业务一级部门
    ec.bu_dept2_name AS bu_dept2_name,         -- 业务二级部门
    ec.bu_dept3_name AS bu_dept3_name,         -- 业务三级部门
    ec.bu_dept4_name AS bu_dept4_name,         -- 业务四级部门
    ec.bu_dept5_name AS bu_dept5_name,         -- 业务五级部门
    ec.tech_dept1_name AS tech_dept1_name,     -- 技术一级部门
    ec.tech_dept2_name AS tech_dept2_name,     -- 技术二级部门
    ec.tech_dept3_name AS tech_dept3_name,     -- 技术三级部门
    ec.tech_dept4_name AS tech_dept4_name,     -- 技术四级部门
    ec.tech_dept5_name AS tech_dept5_name,     -- 技术五级部门
    oe.opt_flg AS opt_flg,                     -- 可优化类型维度（来自可优化事件表）
    
    -- 原子指标
    -- 总成本：所有成本字段之和
    -- TODO: 需确认是否使用所有成本字段相加
    SUM(COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + 
        COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + 
        COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + 
        COALESCE(ec.job_charge, 0)) AS total_cost,
    
    -- 事件数量：去重计数
    COUNT(DISTINCT ec.event_guid) AS event_count,
    
    -- 衍生指标
    -- 可优化成本：标记为可优化事件的总成本
    -- TODO: 需确认opt_flg字段的具体含义
    SUM(CASE 
        WHEN oe.opt_flg IS NOT NULL AND oe.opt_flg != '' AND oe.opt_flg != 'N' 
        THEN COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + 
             COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + 
             COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + 
             COALESCE(ec.job_charge, 0)
        ELSE 0 
    END) AS optimizable_cost,
    
    -- 可优化事件数量
    -- TODO: 需确认opt_flg字段的具体含义
    COUNT(DISTINCT CASE 
        WHEN oe.opt_flg IS NOT NULL AND oe.opt_flg != '' AND oe.opt_flg != 'N' 
        THEN ec.event_guid 
        ELSE NULL 
    END) AS optimizable_event_count,
    
    -- 复合指标
    -- 可优化成本占比：可优化成本 / 总成本
    -- TODO: 依赖可优化成本和总成本的口径确认
    CASE 
        WHEN SUM(COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + 
                COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + 
                COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + 
                COALESCE(ec.job_charge, 0)) > 0
        THEN (SUM(CASE 
                WHEN oe.opt_flg IS NOT NULL AND oe.opt_flg != '' AND oe.opt_flg != 'N' 
                THEN COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + 
                     COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + 
                     COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + 
                     COALESCE(ec.job_charge, 0)
                ELSE 0 
            END) * 100.0) / 
            NULLIF(SUM(COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + 
                   COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + 
                   COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + 
                   COALESCE(ec.job_charge, 0)), 0)
        ELSE NULL 
    END AS optimizable_cost_ratio

FROM iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df ec
INNER JOIN iceberg_zjyprc_hadoop.meta.dwm_bill_optimize_event_v2_df oe 
    ON ec.event_guid = oe.event_guid
    -- TODO: 需确认是否需要同时关联date字段确保时间一致性
    -- AND ec.date = CAST(oe.date AS INT)  -- 成本表date是INT，可优化事件表date是STRING

WHERE 1=1
    -- 模型级过滤：最近30天
    -- TODO: 需确认时间范围定义（滚动30天包含当天）
    AND ec.date >= CAST(DATE_FORMAT(DATE_ADD(CURRENT_DATE(), INTERVAL -30 DAY), 'yyyyMMdd') AS INT)
    AND ec.date <= CAST(DATE_FORMAT(CURRENT_DATE(), 'yyyyMMdd') AS INT)

GROUP BY
    ec.date, ec.app_id, ec.region, ec.event_name, ec.bu_owner, ec.bu_owner_cn,
    ec.tech_owner, ec.tech_owner_cn, ec.bu_dept1_name, ec.bu_dept2_name, 
    ec.bu_dept3_name, ec.bu_dept4_name, ec.bu_dept5_name, ec.tech_dept1_name,
    ec.tech_dept2_name, ec.tech_dept3_name, ec.tech_dept4_name, ec.tech_dept5_name,
    oe.opt_flg
````

> **💡 SQL 说明**：
> 1. 主表：成本表（dm_bill_event_charge_without_visit_v2_df），INNER JOIN 可优化事件表（dwm_bill_optimize_event_v2_df），通过 event_guid 关联
> 2. 维度字段：全部按照上游指定的 source_table 从对应表中 SELECT，确保来源一致性
> 3. 总成本：使用 COALESCE 处理 NULL 值，将所有成本字段相加
> 4. 可优化成本：通过 CASE WHEN 判断 opt_flg 字段，仅计算可优化事件的成本
> 5. 可优化成本占比：使用 NULLIF 保护除零，乘以 100 转换为百分比
> 6. 时间过滤：将日期转换为 yyyyMMdd 格式的 INT 进行比较，支持滚动30天查询
> 7. 数据粒度：按所有维度字段分组，确保事件级别的分析粒度

#### 维度配置

| 字段名 | 来源表 | 数据类型 | 语义类型 | 配置说明 |
|--------|--------|---------|---------|---------|
| date | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | INT | 日期 | 配置为时间维度，格式为 yyyyMMdd，支持日期筛选和趋势分析 |
| app_id | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 类别 | 配置为类别维度，支持按应用筛选和分组 |
| region | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 地理 | 配置为地理维度，支持地域分布分析 |
| event_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 类别 | 配置为类别维度，支持按事件类型分析 |
| bu_owner | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，与 bu_owner_cn 建立层级关系 |
| bu_owner_cn | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 bu_owner 的子层级 |
| tech_owner | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，与 tech_owner_cn 建立层级关系 |
| tech_owner_cn | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 tech_owner 的子层级 |
| bu_dept1_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为业务部门层级分析的起点 |
| bu_dept2_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 bu_dept1_name 的子层级 |
| bu_dept3_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 bu_dept2_name 的子层级 |
| bu_dept4_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 bu_dept3_name 的子层级 |
| bu_dept5_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 bu_dept4_name 的子层级 |
| tech_dept1_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为技术部门层级分析的起点 |
| tech_dept2_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 tech_dept1_name 的子层级 |
| tech_dept3_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 tech_dept2_name 的子层级 |
| tech_dept4_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 tech_dept3_name 的子层级 |
| tech_dept5_name | iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | STRING | 层级 | 配置为层级维度，作为 tech_dept4_name 的子层级 |
| opt_flg | iceberg_zjyprc_hadoop.meta.dwm_bill_optimize_event_v2_df | STRING | 类别 | 配置为类别维度，支持按可优化类型筛选和分析 |

#### 指标配置

| 字段名 | 聚合方式 | SQL 表达式 | 依赖指标 | 单位 | 配置状态 |
|--------|---------|-----------|---------|------|----------|
| total_cost | SUM | SUM(COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + COALESCE(ec.job_charge, 0)) |  | 元 | ⚠️ 配置待确认 |
| event_count | COUNT_DISTINCT | COUNT(DISTINCT ec.event_guid) |  | 个 | ✅ 配置已确认 |
| optimizable_cost | 自定义 | SUM(CASE WHEN oe.opt_flg IS NOT NULL AND oe.opt_flg != '' AND oe.opt_flg != 'N' THEN COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + COALESCE(ec.job_charge, 0) ELSE 0 END) | total_cost | 元 | ⚠️ 配置待确认 |
| optimizable_event_count | COUNT_DISTINCT | COUNT(DISTINCT CASE WHEN oe.opt_flg IS NOT NULL AND oe.opt_flg != '' AND oe.opt_flg != 'N' THEN ec.event_guid ELSE NULL END) | event_count | 个 | ⚠️ 配置待确认 |
| optimizable_cost_ratio | 自定义 | CASE WHEN SUM(COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + COALESCE(ec.job_charge, 0)) > 0 THEN (SUM(CASE WHEN oe.opt_flg IS NOT NULL AND oe.opt_flg != '' AND oe.opt_flg != 'N' THEN COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + COALESCE(ec.job_charge, 0) ELSE 0 END) * 100.0) / NULLIF(SUM(COALESCE(ec.charge_track, 0) + COALESCE(ec.charge_use, 0) + COALESCE(ec.onetrack_charge, 0) + COALESCE(ec.talos_charge, 0) + COALESCE(ec.table_src_charge, 0) + COALESCE(ec.table_dest_charge, 0) + COALESCE(ec.job_charge, 0)), 0) ELSE NULL END | total_cost, optimizable_cost | % | ⚠️ 配置待确认 |

> **配置状态说明**：
> - ✅ 配置已确认 = 该指标的配置无待确认项
> - ⚠️ 配置待确认 = 该指标的配置存在待确认项，详见第四章

> **自定义指标配置**：配置为聚合指标，SUM 聚合方式；配置为自定义指标，使用 CASE WHEN 表达式实现条件聚合；配置为自定义指标，使用 CASE WHEN 和 NULLIF 实现安全除法

#### 关联逻辑

| 左表 | 关联方式 | 右表 | 关联条件 | 原因 |
|------|---------|------|---------|------|
| iceberg_zjyprc_hadoop.meta.dm_bill_event_charge_without_visit_v2_df | INNER JOIN | iceberg_zjyprc_hadoop.meta.dwm_bill_optimize_event_v2_df | ec.event_guid = oe.event_guid | 按照上游 join_hints 要求，通过 event_guid 关联成本表和可优化事件表，获取完整的可优化事件成本信息 |

#### 过滤条件

**模型级过滤（写入 SQL WHERE）**：
- field: date, condition_sql: ec.date >= CAST(DATE_FORMAT(DATE_ADD(CURRENT_DATE(), INTERVAL -30 DAY), 'yyyyMMdd') AS INT) AND ec.date <= CAST(DATE_FORMAT(CURRENT_DATE(), 'yyyyMMdd') AS INT), reason: 时间范围过滤，硬编码在模型层，确保所有图表的数据范围一致（最近30天）

**图表级过滤（配置筛选器）**：
- field: app_id, filter_type: 多选, suggested_default: 全部, reason: 应用维度在 SELECT 中，可在图表筛选器中按需过滤
- field: region, filter_type: 多选, suggested_default: 全部, reason: 地区维度在 SELECT 中，可在图表筛选器中按需过滤
- field: event_name, filter_type: 多选, suggested_default: 全部, reason: 事件类型维度在 SELECT 中，可在图表筛选器中按需过滤
- field: bu_owner, filter_type: 多选, suggested_default: 全部, reason: 业务负责人维度在 SELECT 中，可在图表筛选器中按需过滤
- field: tech_owner, filter_type: 多选, suggested_default: 全部, reason: 技术负责人维度在 SELECT 中，可在图表筛选器中按需过滤
- field: bu_dept1_name, filter_type: 多选, suggested_default: 全部, reason: 业务一级部门维度在 SELECT 中，可在图表筛选器中按需过滤
- field: tech_dept1_name, filter_type: 多选, suggested_default: 全部, reason: 技术一级部门维度在 SELECT 中，可在图表筛选器中按需过滤
- field: opt_flg, filter_type: 多选, suggested_default: 全部, reason: 可优化类型维度在 SELECT 中，可在图表筛选器中按需过滤

**指标级过滤（CASE WHEN）**：
- metric_name: optimizable_cost, purpose: 通过 CASE WHEN 实现 opt_flg 过滤，仅计算可优化事件的成本
- metric_name: optimizable_event_count, purpose: 通过 CASE WHEN 实现 opt_flg 过滤，仅统计可优化事件的数量

#### ⚠️ 数据质量注意事项

- **NULL处理**：所有成本字段使用 COALESCE 处理 NULL 值，避免 NULL 影响聚合计算（SQL位置：COALESCE(ec.charge_track, 0) 等成本字段处理）
- **除零保护**：可优化成本占比计算使用 NULLIF 保护，分母为 0 时返回 NULL 而非报错（SQL位置：NULLIF(SUM(...), 0)）
- **数据重复**：使用 COUNT(DISTINCT event_guid) 确保事件数量统计准确，避免重复计数（SQL位置：COUNT(DISTINCT ec.event_guid)）
- **性能提示**：GROUP BY 包含较多维度字段，在大数据量下可能影响查询性能，建议建立合适的索引（SQL位置：GROUP BY 子句包含20个维度字段）
- **类型转换**：成本表的 date 字段为 INT 类型（yyyyMMdd），需要与日期函数结果进行类型转换匹配（SQL位置：CAST(DATE_FORMAT(...) AS INT)）
- **JOIN校验**：已完整实现上游 join_hints 中的关联条件：通过 event_guid 关联成本表和可优化事件表（SQL位置：INNER JOIN ... ON ec.event_guid = oe.event_guid）

---

## 三、看板布局方案

### 3.1 整体布局

布局采用从上到下信息流：第1行4个KPI卡片（各占3列），第2行趋势分析（总成本和可优化成本各占6列），第3行部门排名分析（各占6列），第4行多维度分布分析（环形图4列+应用分布4列+地图4列），第5行明细表格（占满12列）。视线从核心指标→趋势→部门下钻→多维度分布→明细，符合总览到细节的分析逻辑

```
布局示意（12列网格）：
┌────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
│ chart_01 (3列)  │ chart_02 (3列)  │ chart_03 (3列)  │ chart_04 (3列)  │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_05 (6列 - 总成本趋势)                                 │ chart_06 (6列 - 可优化成本趋势)                                 │
├────────┬────────┬────────┬────────┬────────┬────────┼────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_07 (6列 - 各部门总成本排名)                                 │ chart_08 (6列 - 各部门可优化成本排名)                                 │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_09 (4列 - 可优化成本占比分布) │ chart_10 (4列 - 应用可优化成本分布) │ chart_11 (4列 - 地区可优化成本分布) │
├────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_12 (12列 - 可优化事件明细)                                                                                │
└────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
```

### 3.2 图表配置明细

#### chart_01：总成本

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标卡片 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | overview |
| 维度 | 无 |
| 指标 | total_cost（格式：¥#,##0） |
| 排序 | 无 |
| 位置 | 第1行 第1列，占1行3列 |

**交互**：支持点击联动趋势和下钻图表（chart_05, chart_07），联动维度：date

**设计说明**：核心KPI指标，放在左上角首要位置，支持点击联动趋势和下钻图表

#### chart_02：可优化成本

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标卡片 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | overview |
| 维度 | 无 |
| 指标 | optimizable_cost（格式：¥#,##0） |
| 排序 | 无 |
| 位置 | 第1行 第4列，占1行3列 |

**交互**：支持点击联动趋势和下钻图表（chart_06, chart_08），联动维度：date

**设计说明**：关键优化指标，紧邻总成本，突出显示可优化空间

#### chart_03：可优化成本占比

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标卡片 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | overview |
| 维度 | 无 |
| 指标 | optimizable_cost_ratio（格式：0.00%） |
| 排序 | 无 |
| 位置 | 第1行 第7列，占1行3列 |

**交互**：支持点击联动趋势和下钻图表（chart_09），联动维度：date

**设计说明**：核心比例指标，用百分比格式突出优化潜力

#### chart_04：可优化事件数量

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标卡片 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | overview |
| 维度 | 无 |
| 指标 | optimizable_event_count（格式：#,##0） |
| 排序 | 无 |
| 位置 | 第1行 第10列，占1行3列 |

**交互**：支持点击联动趋势和下钻图表（chart_10），联动维度：date

**设计说明**：事件数量指标，展示可优化事件规模

#### chart_05：总成本趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | total_cost（格式：¥#,##0） |
| 排序 | date ASC |
| 位置 | 第2行 第1列，占1行6列 |

**交互**：支持下钻维度：bu_dept1_name, tech_dept1_name, app_id

**设计说明**：总成本30天趋势分析，支持按部门、应用下钻

#### chart_06：可优化成本趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | optimizable_cost（格式：¥#,##0） |
| 排序 | date ASC |
| 位置 | 第2行 第7列，占1行6列 |

**交互**：支持下钻维度：bu_dept1_name, tech_dept1_name, app_id

**设计说明**：可优化成本30天趋势，与总成本趋势并列对比

#### chart_07：各部门总成本排名

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | drilldown |
| 维度 | bu_dept1_name（y轴） |
| 指标 | total_cost（格式：¥#,##0） |
| 排序 | total_cost DESC，限制10条 |
| 位置 | 第3行 第1列，占1行6列 |

**交互**：支持联动图表（chart_08, chart_11），联动维度：bu_dept1_name；支持下钻维度：bu_dept2_name, bu_dept3_name

**设计说明**：业务部门成本排名Top10，支持下钻到二级、三级部门

#### chart_08：各部门可优化成本排名

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | drilldown |
| 维度 | bu_dept1_name（y轴） |
| 指标 | optimizable_cost（格式：¥#,##0） |
| 排序 | optimizable_cost DESC，限制10条 |
| 位置 | 第3行 第7列，占1行6列 |

**交互**：支持联动图表（chart_07, chart_11），联动维度：bu_dept1_name；支持下钻维度：bu_dept2_name, bu_dept3_name

**设计说明**：业务部门可优化成本排名，与总成本排名联动分析

#### chart_09：可优化成本占比分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 环形图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | drilldown |
| 维度 | opt_flg（颜色分组） |
| 指标 | optimizable_cost（格式：¥#,##0） |
| 排序 | optimizable_cost DESC，限制6条 |
| 位置 | 第4行 第1列，占1行4列 |

**交互**：支持联动图表（chart_12），联动维度：opt_flg

**设计说明**：按可优化类型展示成本构成，环形图适合展示占比分布

#### chart_10：应用可优化成本分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | drilldown |
| 维度 | app_id（y轴） |
| 指标 | optimizable_cost（格式：¥#,##0） |
| 排序 | optimizable_cost DESC，限制10条 |
| 位置 | 第4行 第5列，占1行4列 |

**交互**：支持联动图表（chart_12），联动维度：app_id

**设计说明**：按应用维度分析可优化成本分布，识别重点应用

#### chart_11：地区可优化成本分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 地图 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | drilldown |
| 维度 | region（地理维度） |
| 指标 | optimizable_cost（格式：¥#,##0） |
| 排序 | 无 |
| 位置 | 第4行 第9列，占1行4列 |

**交互**：支持联动图表（chart_12），联动维度：region

**设计说明**：地域分布分析，地图直观展示各地区可优化成本

#### chart_12：可优化事件明细

| 项目 | 配置 |
|------|------|
| 图表类型 | 数据表格 |
| 关联模型 | dm_optimizable_event_cost_analysis |
| 分析层级 | detail |
| 维度 | date, bu_dept1_name, app_id, region, opt_flg（列维度） |
| 指标 | total_cost（¥#,##0）, optimizable_cost（¥#,##0）, optimizable_cost_ratio（0.00%） |
| 排序 | optimizable_cost DESC |
| 位置 | 第5行 第1列，占1行12列 |

**交互**：无

**设计说明**：明细数据表格，支持排序和翻页，展示完整可优化事件信息

### 3.3 全局筛选器

| 筛选器 | 字段 | 类型 | 默认值 | 作用范围 |
|--------|------|------|--------|---------|
| 日期范围 | date | 日期范围 | 最近30天 | 所有图表 |
| 应用 | app_id | 多选 | 全部 | 所有图表 |
| 地区 | region | 多选 | 全部 | 所有图表 |
| 业务部门 | bu_dept1_name | 多选 | 全部 | 所有图表 |
| 技术部门 | tech_dept1_name | 多选 | 全部 | 所有图表 |
| 可优化类型 | opt_flg | 多选 | 全部 | 所有图表 |

---

## 四、待确认项清单

> ⚠️ 以下项目需要在搭建前完成确认，按风险从高到低排列。

| # | 类别 | 确认内容 | 风险 | 建议值 |
|---|------|---------|------|--------|
| 1 | 指标口径 | 成本的计算方式：是否使用所有成本字段（charge_track、charge_use等）相加作为总成本？ | 如果错误理解成本字段，会导致所有成本相关指标计算错误 | 确认使用所有成本字段相加作为总成本 |
| 2 | 指标口径 | 可优化事件的判断标准：opt_flg字段的具体含义和可优化事件的判断条件是什么？ | 如果可优化事件识别错误，会导致优化机会分析完全偏离 | 确认opt_flg字段的含义和可优化事件的判断标准 |
| 3 | 数据源 | 两个表的关联方式：是否通过event_guid字段进行INNER JOIN关联？是否需要同时关联date字段？ | 关联错误会导致数据不匹配，分析结果失真 | 确认通过event_guid字段关联，建议同时关联date字段确保时间一致性 |
| 4 | JOIN方式 | 是否需要同时关联date字段确保时间一致性？当前仅通过event_guid关联，可能存在跨日期数据关联风险 | 如果两个表的日期不匹配，会导致成本数据与可优化标识错位 | 建议在ON条件中增加日期关联：AND ec.date = CAST(oe.date AS INT) |
| 5 | 数据质量 | opt_flg字段的可优化判断条件是否准确？当前使用 IS NOT NULL AND != '' AND != 'N' 作为可优化条件 | 如果可优化条件判断错误，会导致可优化成本计算不准确 | 确认opt_flg字段的具体取值含义和可优化判断标准 |
| 6 | SQL逻辑 | 成本字段的COALESCE处理是否合理？当前将所有NULL值转为0，可能影响成本计算的准确性 | 如果某些成本字段NULL表示无成本，转为0是正确的；如果NULL表示数据缺失，转为0会导致计算错误 | 确认各成本字段NULL值的业务含义 |
| 7 | 时间范围 | 近30天的具体时间范围定义：是否包含当天？使用滚动30天还是固定时间段？ | 时间范围错误会导致数据量不准确 | 确认使用滚动30天（包含当天） |
| 8 | 维度粒度 | 部门层级字段的描述可能存在错误：bu_dept1_name到bu_dept5_name的描述都是'业务归属一级部门'，需要确认正确的层级关系 | 部门层级关系错误会影响下钻分析的准确性 | 确认bu_dept1_name到bu_dept5_name的正确层级关系描述 |
| 9 | 数据质量 | 两个表的date字段类型不同：成本表是int类型，可优化事件表是string类型，需要确认如何处理类型转换 | 类型不匹配会导致关联失败或数据错误 | 建议统一date字段类型或进行类型转换 |
| 10 | 图表类型 | 可优化成本占比分布使用环形图展示，如果opt_flg分类超过6个，是否需要改用条形图？ | 环形图分类过多会导致可读性下降，难以识别主要优化类型 | 建议根据实际分类数量决定，超过6个分类时改用条形图 |
| 11 | 布局 | 总成本和可优化成本趋势图并列展示，是否需要增加对比图表（如双轴图）直接展示占比趋势？ | 并列展示需要用户自行对比，可能不够直观 | 可考虑增加一个占比趋势折线图作为补充 |
| 12 | 交互设计 | 部门排名图表支持下钻到二级、三级部门，是否需要限制下钻深度避免数据过于分散？ | 下钻过深可能导致单个部门数据量过少，分析价值降低 | 建议限制下钻到三级部门，确保每个层级都有足够的数据支撑 |
| 13 | 维度选择 | 业务部门和技术部门分析分开展示，是否需要增加交叉分析图表（如桑基图）展示部门间关系？ | 分开分析可能无法体现业务部门与技术部门之间的关联关系 | 可根据用户需求考虑增加部门关联分析图表 |

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

**看板标题**：可优化事件成本分析看板
**语义模型**：dm_optimizable_event_cost_analysis（ID: 505505）
**图表**：
  - 1. 总成本 — 指标卡片，核心KPI指标
  - 2. 可优化成本 — 指标卡片，关键优化指标
  - 3. 可优化成本占比 — 指标卡片，百分比格式展示优化潜力
  - 4. 可优化事件数量 — 指标卡片，展示可优化事件规模
  - 5. 总成本趋势 — 折线图，30天趋势分析
  - 6. 可优化成本趋势 — 折线图，与总成本趋势对比
  - 7. 各部门总成本排名 — 条形图，Top10业务部门排名
  - 8. 各部门可优化成本排名 — 条形图，Top10可优化成本排名
  - 9. 可优化成本占比分布 — 环形图，按可优化类型展示成本构成
  - 10. 应用可优化成本分布 — 条形图，Top10应用分布
  - 11. 地区可优化成本分布 — 地图，地域分布分析
  - 12. 可优化事件明细 — 数据表格，完整明细信息
**筛选器**：6个全局筛选器（日期范围、应用、地区、业务部门、技术部门、可优化类型），联动所有图表

### 6.2 结构化指令（JSON）

```json
{
  "instruction_id": "20260508_114500",
  "title": "可优化事件成本分析看板",
  "semantic_model": {
    "id": 505505,
    "name": "dm_optimizable_event_cost_analysis"
  },
  "description": "全面分析可优化事件成本，从总览指标到多维度下钻分析，识别成本优化机会",
  "charts": [
    {
      "chart_id": "chart_01",
      "title": "总成本",
      "position": {
        "row": 1,
        "col": 1,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "total_cost",
          "alias": "总成本"
        }
      ],
      "dimensions": [],
      "chart_type": "metric_card",
      "sort": null,
      "limit": null
    },
    {
      "chart_id": "chart_02",
      "title": "可优化成本",
      "position": {
        "row": 1,
        "col": 4,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        }
      ],
      "dimensions": [],
      "chart_type": "metric_card",
      "sort": null,
      "limit": null
    },
    {
      "chart_id": "chart_03",
      "title": "可优化成本占比",
      "position": {
        "row": 1,
        "col": 7,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost_ratio",
          "alias": "可优化成本占比"
        }
      ],
      "dimensions": [],
      "chart_type": "metric_card",
      "sort": null,
      "limit": null
    },
    {
      "chart_id": "chart_04",
      "title": "可优化事件数量",
      "position": {
        "row": 1,
        "col": 10,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_event_count",
          "alias": "可优化事件数量"
        }
      ],
      "dimensions": [],
      "chart_type": "metric_card",
      "sort": null,
      "limit": null
    },
    {
      "chart_id": "chart_05",
      "title": "总成本趋势",
      "position": {
        "row": 2,
        "col": 1,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "total_cost",
          "alias": "总成本"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
        }
      ],
      "chart_type": "line",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
    },
    {
      "chart_id": "chart_06",
      "title": "可优化成本趋势",
      "position": {
        "row": 2,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
        }
      ],
      "chart_type": "line",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
    },
    {
      "chart_id": "chart_07",
      "title": "各部门总成本排名",
      "position": {
        "row": 3,
        "col": 1,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "total_cost",
          "alias": "总成本"
        }
      ],
      "dimensions": [
        {
          "field": "bu_dept1_name",
          "alias": "业务部门"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "total_cost",
        "order": "desc"
      },
      "limit": 10
    },
    {
      "chart_id": "chart_08",
      "title": "各部门可优化成本排名",
      "position": {
        "row": 3,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        }
      ],
      "dimensions": [
        {
          "field": "bu_dept1_name",
          "alias": "业务部门"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "optimizable_cost",
        "order": "desc"
      },
      "limit": 10
    },
    {
      "chart_id": "chart_09",
      "title": "可优化成本占比分布",
      "position": {
        "row": 4,
        "col": 1,
        "width": 4,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        }
      ],
      "dimensions": [
        {
          "field": "opt_flg",
          "alias": "可优化类型"
        }
      ],
      "chart_type": "donut",
      "sort": {
        "field": "optimizable_cost",
        "order": "desc"
      },
      "limit": 6
    },
    {
      "chart_id": "chart_10",
      "title": "应用可优化成本分布",
      "position": {
        "row": 4,
        "col": 5,
        "width": 4,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        }
      ],
      "dimensions": [
        {
          "field": "app_id",
          "alias": "应用"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "optimizable_cost",
        "order": "desc"
      },
      "limit": 10
    },
    {
      "chart_id": "chart_11",
      "title": "地区可优化成本分布",
      "position": {
        "row": 4,
        "col": 9,
        "width": 4,
        "height": 1
      },
      "metrics": [
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        }
      ],
      "dimensions": [
        {
          "field": "region",
          "alias": "地区"
        }
      ],
      "chart_type": "map",
      "sort": null,
      "limit": null
    },
    {
      "chart_id": "chart_12",
      "title": "可优化事件明细",
      "position": {
        "row": 5,
        "col": 1,
        "width": 12,
        "height": 1
      },
      "metrics": [
        {
          "field": "total_cost",
          "alias": "总成本"
        },
        {
          "field": "optimizable_cost",
          "alias": "可优化成本"
        },
        {
          "field": "optimizable_cost_ratio",
          "alias": "可优化成本占比"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
        },
        {
          "field": "bu_dept1_name",
          "alias": "业务部门"
        },
        {
          "field": "app_id",
          "alias": "应用"
        },
        {
          "field": "region",
          "alias": "地区"
        },
        {
          "field": "opt_flg",
          "alias": "可优化类型"
        }
      ],
      "chart_type": "table",
      "sort": {
        "field": "optimizable_cost",
        "order": "desc"
      },
      "limit": null
    }
  ],
  "filters": [
    {
      "filter_id": "filter_01",
      "title": "日期范围",
      "field": "date",
      "type": "date_range",
      "default": "最近30天",
      "linked_charts": []
    },
    {
      "filter_id": "filter_02",
      "title": "应用",
      "field": "app_id",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_03",
      "title": "地区",
      "field": "region",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_04",
      "title": "业务部门",
      "field": "bu_dept1_name",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_05",
      "title": "技术部门",
      "field": "tech_dept1_name",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": []
    },
    {
      "filter_id": "filter_06",
      "title": "可优化类型",
      "field": "opt_flg",
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
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_08",
        "x": 6,
        "y": 160,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_09",
        "x": 0,
        "y": 240,
        "w": 4,
        "h": 1
      },
      {
        "chart_id": "chart_10",
        "x": 4,
        "y": 240,
        "w": 4,
        "h": 1
      },
      {
        "chart_id": "chart_11",
        "x": 8,
        "y": 240,
        "w": 4,
        "h": 1
      },
      {
        "chart_id": "chart_12",
        "x": 0,
        "y": 320,
        "w": 12,
        "h": 1
      }
    ]
  }
}
```

> 💡 **使用提示**：复制上方 JSON 可直接作为 BI 平台编辑助手 API 的入参，实现看板的自动搭建。

---

*本文档由看板开发 Agent 自动生成，如有疑问请联系数据团队*