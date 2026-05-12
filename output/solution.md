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
| 看板目标 | 展示用户行为核心指标（DAU、PV、会话数、有效访问率）的趋势、模块分布、KP用户对比、部门分布及明细数据，支持从总览到细节的下钻分析 |

### 1.2 核心业务问题

1. 过去30天的DAU趋势如何？是否有异常波动？
2. 哪些模块/页面的用户访问量最高？用户偏好是什么？
3. KP用户与非KP用户的行为模式有何差异？
4. 用户留存率如何？次日/7日/30日留存趋势是否健康？
5. 有效访问率是否达标？数据质量是否存在问题？

### 1.3 数据源

| 表名 | 用途 |
|------|------|
| `iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view` | 用户行为事实表，包含所有指标和维度数据 |

### 1.4 指标一览

| 指标名称 | 类型 | 口径定义 | 单位 | 口径状态 |
|---------|------|---------|------|----------|
| DAU | 原子指标 | 每日活跃用户数，基于uid去重统计 | 人 | ✅ 口径已确认 |
| 页面访问次数(PV) | 原子指标 | 用户访问页面的总次数，按行数统计 | 次 | ⚠️ 口径待确认 |
| 会话数 | 原子指标 | 每日或每模块的独立会话数，基于session_id去重 | 次 | ⚠️ 口径待确认 |
| 人均访问页面数 | 复合指标 | 总PV除以DAU，反映用户平均浏览深度 | 页/人 | ✅ 口径已确认 |
| 人均会话数 | 复合指标 | 总会话数除以DAU，反映用户平均访问频次 | 次/人 | ✅ 口径已确认 |
| 模块访问占比 | 复合指标 | 各模块(page_name/module)的PV占总PV的比例 | % | ⚠️ 口径待确认 |
| 用户留存率 | 复合指标 | 基于uid的次日/7日/30日留存率 | % | ⚠️ 口径待确认 |
| 有效访问率 | 复合指标 | is_valid为true的访问次数占总访问次数的比例 | % | ✅ 口径已确认 |

> **口径状态说明**：
> - ✅ 口径已确认 = 该指标的口径定义无待确认项，可直接使用
> - ⚠️ 口径待确认 = 该指标的口径定义存在待确认项，请先处理第四章对应确认项后再搭建

---

## 二、语义模型搭建指南

### 2.1 模型：dm_user_behavior_daily（模型ID：504655）

> **注意**：`model_id` 来自 BI 推送 Agent 的输出，已成功推送至 BI 平台，模型ID为 `504655`。

**用途**：日粒度的用户行为分析模型，覆盖DAU、PV、会话数、人均访问页面数、人均会话数、模块访问占比、用户留存率、有效访问率等核心指标，支持按模块/子模块/页面/部门/KP用户等多维度下钻分析

#### SQL 语句

````sql
-- 用户行为日汇总语义模型
-- 覆盖指标：DAU、PV、会话数、人均访问页面数、人均会话数、模块访问占比、用户留存率、有效访问率
-- 数据粒度：日 + 模块 + 子模块 + 子子模块 + 页面名称 + 页面键名 + 部门层级 + 是否KP用户
-- 数据来源：iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view（单表）

WITH daily_base AS (
    SELECT
        -- 维度字段
        date AS date,                              -- 日期维度
        module AS module,                          -- 模块维度
        sub_module AS sub_module,                  -- 子模块维度
        sub_sub_module AS sub_sub_module,          -- 子子模块维度
        page_name AS page_name,                    -- 页面名称维度
        page_key_name AS page_key_name,            -- 页面键名维度
        dept1_name AS dept1_name,                  -- 一级部门维度
        dept2_name AS dept2_name,                  -- 二级部门维度
        dept3_name AS dept3_name,                  -- 三级部门维度
        dept4_name AS dept4_name,                  -- 四级部门维度
        dept5_name AS dept5_name,                  -- 五级部门维度
        is_kp_user AS is_kp_user,                  -- 是否KP用户维度
        is_valid AS is_valid,                      -- 是否有效维度

        -- 原子指标基础字段
        uid AS uid,                                -- 用户ID（用于去重计数）
        session_id AS session_id,                  -- 会话ID（用于去重计数）
        -- 有效访问标记（用于有效访问率计算）
        CASE WHEN is_valid = 'true' THEN 1 ELSE 0 END AS is_valid_flag

    FROM iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view
    WHERE 1=1
        -- TODO: 需确认时间范围，当前未加硬编码过滤，由BI平台图表筛选器控制
        -- 示例：AND date >= DATE_ADD(CURRENT_DATE(), INTERVAL -30 DAY)
),

-- 计算留存率所需的次日活跃用户
-- 留存率计算逻辑：某日活跃用户在次日再次活跃的比例
-- 使用自关联实现，通过uid匹配次日是否存在访问记录
retention_base AS (
    SELECT
        a.date AS base_date,
        a.uid AS base_uid,
        MAX(CASE WHEN b.date = DATE_ADD(a.date, INTERVAL 1 DAY) THEN 1 ELSE 0 END) AS is_retained_next_day
        -- TODO: 需确认是否还需要7日/30日留存，当前仅实现次日留存
        -- MAX(CASE WHEN b.date = DATE_ADD(a.date, INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS is_retained_7day
        -- MAX(CASE WHEN b.date = DATE_ADD(a.date, INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS is_retained_30day
    FROM (
        SELECT DISTINCT date, uid
        FROM iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view
        WHERE is_valid = 'true'
    ) a
    LEFT JOIN (
        SELECT DISTINCT date, uid
        FROM iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view
        WHERE is_valid = 'true'
    ) b ON a.uid = b.uid AND b.date = DATE_ADD(a.date, INTERVAL 1 DAY)
    GROUP BY a.date, a.uid
)

SELECT
    -- 维度
    d.date AS date,
    d.module AS module,
    d.sub_module AS sub_module,
    d.sub_sub_module AS sub_sub_module,
    d.page_name AS page_name,
    d.page_key_name AS page_key_name,
    d.dept1_name AS dept1_name,
    d.dept2_name AS dept2_name,
    d.dept3_name AS dept3_name,
    d.dept4_name AS dept4_name,
    d.dept5_name AS dept5_name,
    d.is_kp_user AS is_kp_user,
    d.is_valid AS is_valid,

    -- 原子指标
    -- DAU: 每日活跃用户数（基于uid去重）
    COUNT(DISTINCT d.uid) AS dau,

    -- PV: 页面访问次数（按行计数）
    -- TODO: 需确认数据源DWD层是否已去重，若存在重复记录PV会被高估
    COUNT(*) AS pv,

    -- 会话数: 独立会话数（基于session_id去重）
    -- TODO: 需确认session_id是否唯一标识一次会话，是否需要考虑超时策略
    COUNT(DISTINCT d.session_id) AS session_cnt,

    -- 有效访问次数: is_valid='true'的访问次数
    SUM(d.is_valid_flag) AS valid_pv,

    -- 衍生指标
    -- 人均访问页面数: 总PV / DAU
    -- 使用NULLIF保护分母，防止除零错误
    COUNT(*) / NULLIF(COUNT(DISTINCT d.uid), 0) AS avg_page_per_user,

    -- 人均会话数: 总会话数 / DAU
    -- 使用NULLIF保护分母，防止除零错误
    COUNT(DISTINCT d.session_id) / NULLIF(COUNT(DISTINCT d.uid), 0) AS avg_session_per_user,

    -- 模块访问占比: 各模块PV / 总PV * 100%
    -- 注意：此指标在GROUP BY模块粒度时才有意义，在GROUP BY其他维度时含义不同
    -- TODO: 需确认模块粒度的定义：使用module还是page_name作为主分析维度
    COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY d.date), 0) AS module_pv_ratio,

    -- 有效访问率: 有效访问次数 / 总访问次数 * 100%
    SUM(d.is_valid_flag) * 100.0 / NULLIF(COUNT(*), 0) AS valid_access_rate,

    -- 用户留存率（次日留存）
    -- 注意：留存率是跨天指标，在按日+其他维度分组时，同一uid可能出现在多个维度组合中
    -- 因此留存率需要在日期粒度计算，其他维度分组时该值可能重复
    -- TODO: 需确认次日/7日/30日留存是否都需要，当前仅实现次日留存
    MAX(r.is_retained_next_day) AS retention_rate_next_day

FROM daily_base d
LEFT JOIN retention_base r ON d.date = r.base_date AND d.uid = r.base_uid

GROUP BY
    d.date,
    d.module,
    d.sub_module,
    d.sub_sub_module,
    d.page_name,
    d.page_key_name,
    d.dept1_name,
    d.dept2_name,
    d.dept3_name,
    d.dept4_name,
    d.dept5_name,
    d.is_kp_user,
    d.is_valid

-- 注意：模块访问占比(module_pv_ratio)使用了窗口函数SUM(COUNT(*)) OVER (PARTITION BY date)
-- 该值在GROUP BY多个维度时，表示当前维度组合的PV占当日总PV的比例
-- 如果只需要模块粒度的占比，建议在BI平台中按module单独聚合
````

> **💡 SQL 说明**：
> 1. **数据来源**：单表 `iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view`，所有指标和维度均来自同一张事实表，无需JOIN
> 2. **CTE结构**：
>    - `daily_base`：基础数据层，提取所有维度字段，并计算有效访问标记（is_valid_flag）
>    - `retention_base`：留存率计算层，通过自关联实现次日留存判断（某日活跃用户在次日是否再次活跃）
> 3. **原子指标**：
>    - DAU：`COUNT(DISTINCT uid)`，基于用户ID去重统计
>    - PV：`COUNT(*)`，按行计数（⚠️ 需确认数据源是否已去重）
>    - 会话数：`COUNT(DISTINCT session_id)`，基于会话ID去重统计（⚠️ 需确认会话定义）
>    - 有效访问次数：`SUM(CASE WHEN is_valid='true' THEN 1 ELSE 0 END)`
> 4. **衍生指标**：
>    - 人均访问页面数：`COUNT(*) / NULLIF(COUNT(DISTINCT uid), 0)`，使用NULLIF防除零
>    - 人均会话数：`COUNT(DISTINCT session_id) / NULLIF(COUNT(DISTINCT uid), 0)`，使用NULLIF防除零
>    - 模块访问占比：`COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY date), 0)`，使用窗口函数计算当日总PV
>    - 有效访问率：`SUM(is_valid_flag) * 100.0 / NULLIF(COUNT(*), 0)`，使用NULLIF防除零
>    - 用户留存率（次日留存）：通过自关联计算，`MAX(r.is_retained_next_day)` 取最大值
> 5. **过滤条件**：当前未在SQL中硬编码时间范围过滤，由BI平台图表筛选器控制（建议默认近30天）
> 6. **数据质量**：所有除法运算均使用NULLIF保护分母，防止除零错误

#### 维度配置

| 字段名 | 来源表 | 数据类型 | 语义类型 | 配置说明 |
|--------|--------|---------|---------|---------|
| date | dwd_user_module_page_view | DATE | 日期 | BI平台自动识别为时间维度，配置为默认按日聚合，支持日期范围筛选 |
| module | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| sub_module | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| sub_sub_module | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| page_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| page_key_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| dept1_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| dept2_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| dept3_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| dept4_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| dept5_name | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持多选筛选器，默认显示全部 |
| is_kp_user | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持单选筛选器（是/否/全部），默认显示全部 |
| is_valid | dwd_user_module_page_view | STRING | 类别 | 配置为类别维度，支持单选筛选器（true/false/全部），建议默认筛选为'true' |

#### 指标配置

| 字段名 | 聚合方式 | SQL 表达式 | 依赖指标 | 单位 | 配置状态 |
|--------|---------|-----------|---------|------|----------|
| dau | COUNT_DISTINCT | COUNT(DISTINCT uid) | 无 | 人 | ✅ 配置已确认 |
| pv | COUNT | COUNT(*) | 无 | 次 | ⚠️ 配置待确认 |
| session_cnt | COUNT_DISTINCT | COUNT(DISTINCT session_id) | 无 | 次 | ⚠️ 配置待确认 |
| valid_pv | SUM | SUM(CASE WHEN is_valid = 'true' THEN 1 ELSE 0 END) | 无 | 次 | ✅ 配置已确认 |
| avg_page_per_user | 自定义 | COUNT(*) / NULLIF(COUNT(DISTINCT uid), 0) | pv, dau | 页/人 | ✅ 配置已确认 |
| avg_session_per_user | 自定义 | COUNT(DISTINCT session_id) / NULLIF(COUNT(DISTINCT uid), 0) | session_cnt, dau | 次/人 | ✅ 配置已确认 |
| module_pv_ratio | 自定义 | COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY date), 0) | pv | % | ⚠️ 配置待确认 |
| valid_access_rate | 自定义 | SUM(CASE WHEN is_valid = 'true' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) | valid_pv, pv | % | ✅ 配置已确认 |
| retention_rate_next_day | 自定义 | MAX(CASE WHEN b.date = DATE_ADD(a.date, INTERVAL 1 DAY) THEN 1 ELSE 0 END) | dau | % | ⚠️ 配置待确认 |

> **配置状态说明**：
> - ✅ 配置已确认 = 该指标的配置无待确认项
> - ⚠️ 配置待确认 = 该指标的配置存在待确认项，详见第四章

> **自定义指标配置**：
> - `avg_page_per_user`：BI平台配置为自定义指标，使用SQL表达式 `COUNT(*) / NULLIF(COUNT(DISTINCT uid), 0)`，显示格式为保留两位小数
> - `avg_session_per_user`：BI平台配置为自定义指标，使用SQL表达式 `COUNT(DISTINCT session_id) / NULLIF(COUNT(DISTINCT uid), 0)`，显示格式为保留两位小数
> - `module_pv_ratio`：BI平台配置为自定义指标，使用SQL表达式 `COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY date), 0)`，显示格式为保留两位小数加百分号
> - `valid_access_rate`：BI平台配置为自定义指标，使用SQL表达式 `SUM(CASE WHEN is_valid = 'true' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0)`，显示格式为保留两位小数加百分号
> - `retention_rate_next_day`：BI平台配置为自定义指标，使用SQL表达式 `MAX(CASE WHEN b.date = DATE_ADD(a.date, INTERVAL 1 DAY) THEN 1 ELSE 0 END)`，显示格式为保留两位小数加百分号。建议在日期粒度单独查看留存率

#### 关联逻辑

| 左表 | 关联方式 | 右表 | 关联条件 | 原因 |
|------|---------|------|---------|------|
| dwd_user_module_page_view (a) | LEFT JOIN | dwd_user_module_page_view (b) | a.uid = b.uid AND b.date = DATE_ADD(a.date, INTERVAL 1 DAY) | 留存率计算需要自关联：a表为基准日活跃用户，b表为次日活跃用户，通过uid匹配判断是否留存 |

#### 过滤条件

**模型级过滤（写入 SQL WHERE）**：
- 无（当前未在SQL中硬编码过滤条件）

**图表级过滤（配置筛选器）**：

| 字段 | 筛选器类型 | 建议默认值 | 原因 |
|------|-----------|-----------|------|
| date | 日期范围 | 近30天 | 时间范围由图表筛选器控制，建议默认近30天，支持自定义日期选择 |
| module | 多选 | 全部 | 模块维度在SELECT中，可在图表筛选器中按需过滤，支持多选对比 |
| sub_module | 多选 | 全部 | 子模块维度在SELECT中，可在图表筛选器中按需过滤，支持多选对比 |
| page_name | 多选 | 全部 | 页面名称维度在SELECT中，可在图表筛选器中按需过滤，支持多选对比 |
| dept1_name | 多选 | 全部 | 一级部门维度在SELECT中，可在图表筛选器中按需过滤，支持多选对比 |
| is_kp_user | 单选 | 全部 | 是否KP用户维度在SELECT中，可在图表筛选器中按需过滤，支持是/否/全部三种选择 |
| is_valid | 单选 | true | 是否有效维度在SELECT中，建议默认筛选为'true'，排除无效数据 |

**指标级过滤（CASE WHEN）**：

| 指标名称 | CASE WHEN 表达式 | 用途 |
|---------|-----------------|------|
| valid_pv | CASE WHEN is_valid = 'true' THEN 1 ELSE 0 END | 通过CASE WHEN实现is_valid过滤，统计有效访问次数 |
| valid_access_rate | SUM(CASE WHEN is_valid = 'true' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) | 有效访问率 = 有效访问次数 / 总访问次数 * 100% |

#### ⚠️ 数据质量注意事项

| 类型 | 描述 | SQL位置 | 建议 |
|------|------|--------|------|
| NULL处理 | 部门维度（dept1_name~dept5_name）可能存在NULL值 | d.dept1_name AS dept1_name, ... | BI平台中可将NULL显示为'未知'或'未归属' |
| NULL处理 | is_kp_user字段可能存在NULL值 | d.is_kp_user AS is_kp_user | BI平台中可将NULL显示为'未知' |
| 除零保护 | 人均访问页面数、人均会话数、模块访问占比、有效访问率均使用NULLIF保护分母 | NULLIF(COUNT(DISTINCT uid), 0), ... | 所有除法运算均已使用NULLIF保护，无需额外处理 |
| 数据重复 | PV按行计数(COUNT(*))，若数据源DWD层存在重复记录，PV会被高估 | COUNT(*) AS pv | ⚠️ 需确认数据源DWD层是否已清洗去重 |
| 数据重复 | 留存率计算使用自关联，通过uid匹配。DISTINCT可确保去重 | SELECT DISTINCT date, uid FROM ... | 留存率计算中已使用DISTINCT去重，确保每个用户每天只计一次 |
| 性能提示 | 留存率计算使用自关联，需要扫描同一张表两次 | retention_base CTE | 如果数据量大，建议在ETL阶段预计算留存率，或使用窗口函数LAG优化 |
| 性能提示 | GROUP BY包含13个维度字段，分组粒度较细 | GROUP BY d.date, d.module, ... | 建议在BI平台中根据实际分析需求选择需要的维度，避免一次性查询所有维度组合 |
| 其他 | 模块访问占比(module_pv_ratio)使用了窗口函数，多维度分组时含义不同 | COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY d.date), 0) | 如果只需要模块粒度的占比，建议在BI平台中按module单独聚合 |
| 其他 | 留存率(retention_rate_next_day)在按多维度分组时，同一uid可能出现在多个维度组合中 | MAX(r.is_retained_next_day) AS retention_rate_next_day | 建议在日期粒度单独查看留存率，或在BI平台中按date单独聚合 |

---

## 三、看板布局方案

### 3.1 整体布局

布局从上到下：第1行4个KPI卡片（各占3列），第2行核心指标趋势折线图（占满12列），第3行人均指标+留存率（各占6列），第4行模块PV排名+模块访问占比（各占6列），第5行子模块PV分布（占满12列），第6行KP用户对比（各占6列），第7行部门分布（各占6列），第8行明细表格（占满12列）。视线从KPI→趋势→人均/留存→模块下钻→KP对比→部门分布→明细，符合总览到细节的信息流。

```
布局示意（12列网格）：
┌────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
│ chart_01 (3列)  │ chart_02 (3列)  │ chart_03 (3列)  │ chart_04 (3列)  │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_05 (12列 - 核心指标趋势)                                                                              │
├────────┬────────┬────────┬────────┬────────┬────────┼────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_06 (6列 - 人均指标趋势)                              │ chart_07 (6列 - 留存率趋势)                              │
├────────┬────────┬────────┬────────┬────────┬────────┼────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_08 (6列 - 模块PV排名)                                │ chart_09 (6列 - 模块访问占比)                            │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_10 (12列 - 子模块PV分布)                                                                             │
├────────┬────────┬────────┬────────┬────────┬────────┼────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_11 (6列 - KP用户DAU对比)                            │ chart_12 (6列 - KP用户人均页面数对比)                    │
├────────┬────────┬────────┬────────┬────────┬────────┼────────┬────────┬────────┬────────┬────────┬────────┤
│ chart_13 (6列 - 部门用户分布)                              │ chart_14 (6列 - 部门PV分布)                              │
├────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┤
│ chart_15 (12列 - 用户行为明细)                                                                             │
└────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
```

### 3.2 图表配置明细

#### chart_01：DAU

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | dau（格式：#,##0） |
| 排序 | date ASC |
| 位置 | 第1行 第1列，占1行3列 |

**交互**：点击日期联动 chart_05、chart_06、chart_07（联动维度：date）

**设计说明**：DAU为核心指标，放在左上第一位，附带30天趋势迷你线，点击日期可联动下钻层图表

---

#### chart_02：页面访问次数(PV)

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | pv（格式：#,##0） |
| 排序 | date ASC |
| 位置 | 第1行 第4列，占1行3列 |

**交互**：点击日期联动 chart_05、chart_06、chart_07（联动维度：date）

**设计说明**：PV为第二核心指标，紧跟DAU，附带趋势迷你线

---

#### chart_03：会话数

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | session_cnt（格式：#,##0） |
| 排序 | date ASC |
| 位置 | 第1行 第7列，占1行3列 |

**交互**：点击日期联动 chart_05、chart_06、chart_07（联动维度：date）

**设计说明**：会话数为第三核心指标，附带趋势迷你线

---

#### chart_04：有效访问率

| 项目 | 配置 |
|------|------|
| 图表类型 | 指标趋势图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | valid_access_rate（格式：0.00%） |
| 排序 | date ASC |
| 位置 | 第1行 第10列，占1行3列 |

**交互**：点击日期联动 chart_05、chart_06、chart_07（联动维度：date）

**设计说明**：有效访问率反映数据质量，放在KPI卡片行最右侧，附带趋势迷你线

---

#### chart_05：核心指标趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | dau（格式：#,##0，主值）、pv（格式：#,##0，对比值）、session_cnt（格式：#,##0，辅助值） |
| 排序 | date ASC |
| 位置 | 第2行 第1列，占1行12列 |

**交互**：支持下钻维度：module、is_kp_user

**设计说明**：DAU、PV、会话数三条趋势线叠加，占满整行突出趋势，支持按模块和KP用户下钻

---

#### chart_06：人均访问页面数与人均会话数趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | avg_page_per_user（格式：0.00，主值）、avg_session_per_user（格式：0.00，对比值） |
| 排序 | date ASC |
| 位置 | 第3行 第1列，占1行6列 |

**交互**：支持下钻维度：is_kp_user

**设计说明**：人均访问页面数和人均会话数双线趋势，反映用户粘性变化，支持按KP用户分组下钻

---

#### chart_07：用户留存率趋势

| 项目 | 配置 |
|------|------|
| 图表类型 | 折线图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | overview |
| 维度 | date（x轴） |
| 指标 | retention_rate_next_day（格式：0.00%，主值） |
| 排序 | date ASC |
| 位置 | 第3行 第7列，占1行6列 |

**交互**：无

**设计说明**：次日留存率趋势，与人均指标左右并列，反映用户粘性的两个维度

---

#### chart_08：各模块PV排名

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | module（y轴） |
| 指标 | pv（格式：#,##0，主值） |
| 排序 | pv DESC，取Top15 |
| 位置 | 第4行 第1列，占1行6列 |

**交互**：点击模块联动 chart_09、chart_10（联动维度：module），支持下钻维度：sub_module、page_name

**设计说明**：模块PV排名用条形图（项多时优于柱状图），Top15，点击模块可联动子模块和页面明细

---

#### chart_09：各模块访问占比

| 项目 | 配置 |
|------|------|
| 图表类型 | 环形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | module（颜色分组） |
| 指标 | module_pv_ratio（格式：0.00%，主值） |
| 排序 | module_pv_ratio DESC，取Top6 |
| 位置 | 第4行 第7列，占1行6列 |

**交互**：点击模块联动 chart_08、chart_10（联动维度：module），支持下钻维度：sub_module

**设计说明**：模块访问占比用环形图展示构成，限制Top6模块，其余归为'其他'，与PV排名左右并列

---

#### chart_10：子模块PV分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 柱状图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | sub_module（x轴）、module（颜色分组） |
| 指标 | pv（格式：#,##0，主值） |
| 排序 | pv DESC，取Top20 |
| 位置 | 第5行 第1列，占1行12列 |

**交互**：支持下钻维度：page_name

**设计说明**：子模块PV分布柱状图，按模块颜色分组，支持下钻到页面名称，占满整行

---

#### chart_11：KP用户与非KP用户DAU对比

| 项目 | 配置 |
|------|------|
| 图表类型 | 堆叠柱状图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | date（x轴）、is_kp_user（颜色分组） |
| 指标 | dau（格式：#,##0，主值） |
| 排序 | date ASC |
| 位置 | 第6行 第1列，占1行6列 |

**交互**：支持下钻维度：module

**设计说明**：KP用户与非KP用户DAU堆叠柱状图，直观对比两组用户活跃度差异，支持按模块下钻

---

#### chart_12：KP用户与非KP用户人均访问页面数对比

| 项目 | 配置 |
|------|------|
| 图表类型 | 柱状图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | is_kp_user（x轴） |
| 指标 | avg_page_per_user（格式：0.00，主值） |
| 排序 | 无 |
| 位置 | 第6行 第7列，占1行6列 |

**交互**：无

**设计说明**：KP用户与非KP用户人均访问页面数对比柱状图，与DAU对比左右并列，反映行为深度差异

---

#### chart_13：部门用户分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | dept1_name（y轴） |
| 指标 | dau（格式：#,##0，主值） |
| 排序 | dau DESC，取Top15 |
| 位置 | 第7行 第1列，占1行6列 |

**交互**：支持下钻维度：dept2_name、dept3_name

**设计说明**：一级部门DAU排名条形图，Top15，支持下钻到二级、三级部门

---

#### chart_14：部门PV分布

| 项目 | 配置 |
|------|------|
| 图表类型 | 条形图 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | drilldown |
| 维度 | dept1_name（y轴） |
| 指标 | pv（格式：#,##0，主值） |
| 排序 | pv DESC，取Top15 |
| 位置 | 第7行 第7列，占1行6列 |

**交互**：支持下钻维度：dept2_name、dept3_name

**设计说明**：一级部门PV排名条形图，Top15，与部门DAU左右并列，支持下钻

---

#### chart_15：用户行为明细

| 项目 | 配置 |
|------|------|
| 图表类型 | 数据表格 |
| 关联模型 | dm_user_behavior_daily |
| 分析层级 | detail |
| 维度 | date、module、sub_module、page_name、is_kp_user、dept1_name（列维度） |
| 指标 | dau（格式：#,##0，主值）、pv（格式：#,##0，辅助值）、session_cnt（格式：#,##0，辅助值）、avg_page_per_user（格式：0.00，辅助值）、avg_session_per_user（格式：0.00，辅助值）、valid_access_rate（格式：0.00%，辅助值） |
| 排序 | date DESC |
| 位置 | 第8行 第1列，占1行12列 |

**交互**：无

**设计说明**：明细数据表格，展示日期、模块、子模块、页面名称、是否KP用户、一级部门等维度，以及DAU、PV、会话数、人均指标、有效访问率等指标，支持排序和翻页，放在最底部

---

### 3.3 全局筛选器

| 筛选器 | 字段 | 类型 | 默认值 | 作用范围 |
|--------|------|------|--------|---------|
| 日期 | date | 日期范围 | 近30天 | 所有图表 |
| 模块 | module | 多选 | 全部 | 所有图表 |
| 子模块 | sub_module | 多选 | 全部 | 所有图表 |
| 页面名称 | page_name | 多选 | 全部 | 所有图表 |
| 一级部门 | dept1_name | 多选 | 全部 | 所有图表 |
| 是否KP用户 | is_kp_user | 单选 | 全部 | 所有图表 |
| 是否有效 | is_valid | 单选 | true | 所有图表 |

---

## 四、待确认项清单

> ⚠️ 以下项目需要在搭建前完成确认，按风险从高到低排列。

| # | 类别 | 确认内容 | 风险 | 建议值 |
|---|------|---------|------|--------|
| 1 | 指标口径 | 用户留存率需要跨天计算，单表自关联实现，需确认次日/7日/30日留存是否都需要 | 留存率是用户行为分析的核心指标，口径错误会导致用户粘性判断失准 | 建议先实现次日留存，后续扩展7日和30日留存 |
| 2 | 指标口径 | PV统计方式：按行计数 vs 按e_ts去重计数 | 若数据源存在重复记录，按行计数会导致PV虚高 | 建议按行计数，但需确认数据源DWD层是否已去重 |
| 3 | 指标口径 | 会话数定义：session_id是否唯一标识一次会话，是否需要考虑超时策略（如30分钟无操作算新会话） | 会话数统计偏差，影响人均会话数和用户粘性分析 | 按session_id去重，建议确认会话超时策略 |
| 4 | 维度粒度 | 模块层级分析时，使用module还是page_name作为主分析维度 | 粒度选择不当会导致分析结果过于粗放或细碎 | 建议先按module做总览分析，再下钻到page_name |
| 5 | 维度粒度 | 部门维度(dept1_name~dept5_name)是用户所属部门还是页面归属部门 | 若混淆用户属性与页面属性，部门维度分析逻辑错误 | 需确认字段含义，建议查看数据字典或咨询数据负责人 |
| 6 | 数据源 | 数据源DWD层是否已清洗去重，是否包含所有用户行为 | 数据质量问题会导致分析结果失真 | 确认数据质量及数据覆盖范围 |
| 7 | 过滤条件 | 分析的时间范围（如近7天、近30天、自定义） | 时间范围不明确会导致看板数据不一致 | 建议默认近30天，支持自定义日期选择 |
| 8 | 其他 | 是否需要对is_kp_user进行对比分析 | 若忽略KP用户与非KP用户的差异，可能遗漏关键用户群体的行为模式 | 建议作为分组维度纳入看板，支持对比分析 |
| 9 | SQL逻辑 | 留存率计算使用自关联，当前仅实现次日留存。SQL中已预留7日和30日留存的注释代码，需确认是否需要启用 | 若仅实现次日留存，7日和30日留存分析将无法进行 | 建议先实现次日留存，后续根据需求扩展7日和30日留存 |
| 10 | SQL逻辑 | 模块访问占比(module_pv_ratio)使用了窗口函数SUM(COUNT(*)) OVER (PARTITION BY date)，在GROUP BY多维度时，该值表示当前维度组合的PV占当日总PV的比例，而非模块粒度的占比 | 若用户期望的是模块粒度的占比，多维度分组会导致占比含义混淆 | 建议在BI平台中按module单独聚合查看模块访问占比 |
| 11 | SQL逻辑 | 留存率(retention_rate_next_day)在按多维度分组时，同一uid可能出现在多个维度组合中，留存率值会重复 | 多维度分组下留存率含义不清晰，可能导致分析误导 | 建议在日期粒度单独查看留存率，或在BI平台中按date单独聚合 |
| 12 | 数据质量 | 部门维度(dept1_name~dept5_name)可能存在NULL值，需确认NULL值的处理方式 | NULL值会导致部门维度分析时数据缺失 | 建议将NULL显示为'未知'或'未归属' |
| 13 | 数据质量 | is_kp_user字段可能存在NULL值，需确认NULL值的处理方式 | NULL值会导致KP用户与非KP用户对比分析时数据不完整 | 建议将NULL显示为'未知' |
| 14 | 性能提示 | GROUP BY包含13个维度字段，分组粒度极细，可能导致大量小分组，影响查询性能 | 查询性能下降，影响看板加载速度 | 建议在BI平台中根据实际分析需求选择需要的维度，避免一次性查询所有维度组合 |
| 15 | 图表类型 | 模块访问占比展示方式：当前使用环形图展示Top6模块的占比，其余归为'其他'。若模块数量超过6个，是否接受此处理方式？ | 若用户期望看到所有模块的占比，环形图超过6个分类会难以阅读 | 建议使用环形图展示Top6模块，其余归为'其他'，同时条形图展示所有模块的PV排名作为补充 |
| 16 | 图表类型 | 部门用户分布和PV分布展示方式：当前使用条形图展示Top15一级部门。若部门数量超过15个，是否接受此处理方式？ | 若用户期望看到所有部门的分布，条形图超过15个分类会难以阅读 | 建议使用条形图展示Top15部门，其余归为'其他'，同时支持通过筛选器选择特定部门 |
| 17 | 布局 | 看板总览层包含6个图表（4个KPI卡片+2个趋势折线图），是否满足一屏可见的要求？ | 若用户屏幕分辨率较低，总览层可能无法一屏完全展示 | 建议将人均指标和留存率趋势放在总览层，若需要精简，可将留存率趋势移至下钻层 |
| 18 | 交互 | KPI卡片（chart_01~chart_04）点击日期联动下钻层图表，是否所有KPI卡片都需要联动？ | 若联动过多，可能导致交互逻辑复杂，用户难以理解 | 建议仅DAU和PV卡片支持联动，会话数和有效访问率卡片暂不联动 |
| 19 | 维度选择 | 部门维度(dept1_name~dept5_name)是用户所属部门还是页面归属部门？当前设计按一级部门展示DAU和PV分布 | 若混淆用户属性与页面属性，部门维度分析逻辑错误 | 需确认字段含义，建议查看数据字典或咨询数据负责人 |

---

## 五、搭建步骤建议

1. **确认待确认项**：先完成第四章的所有确认项，特别是指标口径相关（PV统计方式、会话数定义、留存率范围等）
2. **创建语义模型**：在 BI 平台创建语义模型 `dm_user_behavior_daily`（模型ID：504655），粘贴完整SQL，验证字段解析
3. **调整维度/指标**：检查 BI 平台自动解析的维度和指标，按配置说明手动调整：
   - 将 `dau`、`session_cnt` 配置为 COUNT_DISTINCT 聚合
   - 将 `avg_page_per_user`、`avg_session_per_user` 等配置为自定义指标
   - 将 `module_pv_ratio`、`valid_access_rate`、`retention_rate_next_day` 配置为自定义指标
4. **创建看板**：选择语义模型 `dm_user_behavior_daily`，按第三章顺序添加15个图表
5. **配置筛选器**：添加7个全局筛选器（日期、模块、子模块、页面名称、一级部门、是否KP用户、是否有效），按配置设置默认值
6. **配置交互**：
   - 设置 chart_01~chart_04 点击日期联动 chart_05、chart_06、chart_07
   - 设置 chart_08 点击模块联动 chart_09、chart_10
   - 设置 chart_09 点击模块联动 chart_08、chart_10
   - 设置 chart_05、chart_08、chart_10、chart_11、chart_13、chart_14 的下钻维度
7. **验证数据**：用已知数据验证关键指标的准确性（如DAU、PV、有效访问率）

---

## 六、看板搭建指令

> **说明**：以下是标准化的看板搭建指令，可作为编辑助手 API 的入参。指令由看板指令生成 Agent 自动生成，供人工审查和未来自动化使用。

### 6.1 可读摘要

**看板标题**：用户行为分析看板
**语义模型**：dm_user_behavior_daily（ID: 504655）
**图表**：
  - 1. DAU — 指标趋势图，附带日期维度
  - 2. 页面访问次数(PV) — 指标趋势图，附带日期维度
  - 3. 会话数 — 指标趋势图，附带日期维度
  - 4. 有效访问率 — 指标趋势图，附带日期维度
  - 5. 核心指标趋势 — 折线图，展示DAU、PV、会话数三条趋势线
  - 6. 人均访问页面数与人均会话数趋势 — 折线图，展示人均指标双线趋势
  - 7. 用户留存率趋势 — 折线图，展示次日留存率趋势
  - 8. 各模块PV排名 — 条形图，Top15模块PV排名
  - 9. 各模块访问占比 — 环形图，Top6模块PV占比
  - 10. 子模块PV分布 — 柱状图，按模块颜色分组，Top20子模块
  - 11. KP用户与非KP用户DAU对比 — 堆叠柱状图，对比两组用户DAU
  - 12. KP用户与非KP用户人均访问页面数对比 — 柱状图，对比两组用户行为深度
  - 13. 部门用户分布 — 条形图，Top15一级部门DAU排名
  - 14. 部门PV分布 — 条形图，Top15一级部门PV排名
  - 15. 用户行为明细 — 数据表格，展示多维度明细数据
**筛选器**：日期筛选器（联动所有图表）、模块筛选器（联动所有图表）、子模块筛选器（联动所有图表）、页面名称筛选器（联动所有图表）、一级部门筛选器（联动所有图表）、是否KP用户筛选器（联动所有图表）、是否有效筛选器（联动所有图表）

### 6.2 结构化指令（JSON）

```json
{
  "instruction_id": "20260508_114500",
  "title": "用户行为分析看板",
  "semantic_model": {
    "id": 504655,
    "name": "dm_user_behavior_daily"
  },
  "description": "展示用户行为核心指标（DAU、PV、会话数、有效访问率）的趋势、模块分布、KP用户对比、部门分布及明细数据，支持从总览到细节的下钻分析",
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
          "field": "date",
          "alias": "日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
    },
    {
      "chart_id": "chart_02",
      "title": "页面访问次数(PV)",
      "position": {
        "row": 1,
        "col": 4,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "pv",
          "alias": "PV"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
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
          "field": "session_cnt",
          "alias": "会话数"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
    },
    {
      "chart_id": "chart_04",
      "title": "有效访问率",
      "position": {
        "row": 1,
        "col": 10,
        "width": 3,
        "height": 1
      },
      "metrics": [
        {
          "field": "valid_access_rate",
          "alias": "有效访问率"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
        }
      ],
      "chart_type": "metric_trend",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
    },
    {
      "chart_id": "chart_05",
      "title": "核心指标趋势",
      "position": {
        "row": 2,
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
          "field": "pv",
          "alias": "PV"
        },
        {
          "field": "session_cnt",
          "alias": "会话数"
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
      "title": "人均访问页面数与人均会话数趋势",
      "position": {
        "row": 3,
        "col": 1,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "avg_page_per_user",
          "alias": "人均访问页面数"
        },
        {
          "field": "avg_session_per_user",
          "alias": "人均会话数"
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
      "title": "用户留存率趋势",
      "position": {
        "row": 3,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "retention_rate_next_day",
          "alias": "次日留存率"
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
      "chart_id": "chart_08",
      "title": "各模块PV排名",
      "position": {
        "row": 4,
        "col": 1,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "pv",
          "alias": "PV"
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
        "field": "pv",
        "order": "desc"
      },
      "limit": 15
    },
    {
      "chart_id": "chart_09",
      "title": "各模块访问占比",
      "position": {
        "row": 4,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "module_pv_ratio",
          "alias": "模块PV占比"
        }
      ],
      "dimensions": [
        {
          "field": "module",
          "alias": "模块"
        }
      ],
      "chart_type": "donut",
      "sort": {
        "field": "module_pv_ratio",
        "order": "desc"
      },
      "limit": 6
    },
    {
      "chart_id": "chart_10",
      "title": "子模块PV分布",
      "position": {
        "row": 5,
        "col": 1,
        "width": 12,
        "height": 1
      },
      "metrics": [
        {
          "field": "pv",
          "alias": "PV"
        }
      ],
      "dimensions": [
        {
          "field": "sub_module",
          "alias": "子模块"
        },
        {
          "field": "module",
          "alias": "模块"
        }
      ],
      "chart_type": "bar",
      "sort": {
        "field": "pv",
        "order": "desc"
      },
      "limit": 20
    },
    {
      "chart_id": "chart_11",
      "title": "KP用户与非KP用户DAU对比",
      "position": {
        "row": 6,
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
          "field": "date",
          "alias": "日期"
        },
        {
          "field": "is_kp_user",
          "alias": "是否KP用户"
        }
      ],
      "chart_type": "stacked_bar",
      "sort": {
        "field": "date",
        "order": "asc"
      },
      "limit": null
    },
    {
      "chart_id": "chart_12",
      "title": "KP用户与非KP用户人均访问页面数对比",
      "position": {
        "row": 6,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "avg_page_per_user",
          "alias": "人均访问页面数"
        }
      ],
      "dimensions": [
        {
          "field": "is_kp_user",
          "alias": "是否KP用户"
        }
      ],
      "chart_type": "bar",
      "sort": null,
      "limit": null
    },
    {
      "chart_id": "chart_13",
      "title": "部门用户分布",
      "position": {
        "row": 7,
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
          "field": "dept1_name",
          "alias": "一级部门"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "dau",
        "order": "desc"
      },
      "limit": 15
    },
    {
      "chart_id": "chart_14",
      "title": "部门PV分布",
      "position": {
        "row": 7,
        "col": 7,
        "width": 6,
        "height": 1
      },
      "metrics": [
        {
          "field": "pv",
          "alias": "PV"
        }
      ],
      "dimensions": [
        {
          "field": "dept1_name",
          "alias": "一级部门"
        }
      ],
      "chart_type": "horizontal_bar",
      "sort": {
        "field": "pv",
        "order": "desc"
      },
      "limit": 15
    },
    {
      "chart_id": "chart_15",
      "title": "用户行为明细",
      "position": {
        "row": 8,
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
          "field": "pv",
          "alias": "PV"
        },
        {
          "field": "session_cnt",
          "alias": "会话数"
        },
        {
          "field": "avg_page_per_user",
          "alias": "人均访问页面数"
        },
        {
          "field": "avg_session_per_user",
          "alias": "人均会话数"
        },
        {
          "field": "valid_access_rate",
          "alias": "有效访问率"
        }
      ],
      "dimensions": [
        {
          "field": "date",
          "alias": "日期"
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
          "field": "is_kp_user",
          "alias": "是否KP用户"
        },
        {
          "field": "dept1_name",
          "alias": "一级部门"
        }
      ],
      "chart_type": "table",
      "sort": {
        "field": "date",
        "order": "desc"
      },
      "limit": null
    }
  ],
  "filters": [
    {
      "filter_id": "filter_01",
      "title": "日期",
      "field": "date",
      "type": "date_range",
      "default": "近30天",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
    },
    {
      "filter_id": "filter_02",
      "title": "模块",
      "field": "module",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
    },
    {
      "filter_id": "filter_03",
      "title": "子模块",
      "field": "sub_module",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
    },
    {
      "filter_id": "filter_04",
      "title": "页面名称",
      "field": "page_name",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
    },
    {
      "filter_id": "filter_05",
      "title": "一级部门",
      "field": "dept1_name",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
    },
    {
      "filter_id": "filter_06",
      "title": "是否KP用户",
      "field": "is_kp_user",
      "type": "dropdown",
      "default": "全部",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
    },
    {
      "filter_id": "filter_07",
      "title": "是否有效",
      "field": "is_valid",
      "type": "dropdown",
      "default": "true",
      "linked_charts": [
        "chart_01",
        "chart_02",
        "chart_03",
        "chart_04",
        "chart_05",
        "chart_06",
        "chart_07",
        "chart_08",
        "chart_09",
        "chart_10",
        "chart_11",
        "chart_12",
        "chart_13",
        "chart_14",
        "chart_15"
      ]
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
        "w": 12,
        "h": 1
      },
      {
        "chart_id": "chart_06",
        "x": 0,
        "y": 160,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_07",
        "x": 6,
        "y": 160,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_08",
        "x": 0,
        "y": 240,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_09",
        "x": 6,
        "y": 240,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_10",
        "x": 0,
        "y": 320,
        "w": 12,
        "h": 1
      },
      {
        "chart_id": "chart_11",
        "x": 0,
        "y": 400,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_12",
        "x": 6,
        "y": 400,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_13",
        "x": 0,
        "y": 480,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_14",
        "x": 6,
        "y": 480,
        "w": 6,
        "h": 1
      },
      {
        "chart_id": "chart_15",
        "x": 0,
        "y": 560,
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