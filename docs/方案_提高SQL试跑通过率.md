# 方案：提高 SQL 试跑通过率

> 创建日期：2026-05-14
> 状态：**✅ P1 + P2 已完成（2026-05-15），错误反馈链路修复已完成（2026-05-18）**
> 范围：仅做必做项 P1 + P2
>
> **2026-05-18 补充**：原方案聚焦 P1（column_types 注入）+ P2（Spark 方言 prompt），均已落地。但实战发现错误反馈链路还有一个关键漏洞——注入给 LLM 的"错误信息"实际只是 5 个字符 `"SQL执行失败"`（默认值），真正的 Spark 报错（在 `exceptionMsg` 字段）从未传给 LLM。这个 bug 让 [src/agents.py:286-299](../src/agents.py#L286-L299) 已经写好的两条「定向修复指引」永远不触发。已在 2026-05-18 修复，详见 [迭代记录_2026-05-18.md](迭代记录_2026-05-18.md)。

---

## Context

**为什么改**：用户已经保证了数据源准确（表名 + 字段名），但 SQL 试跑仍然频繁失败。调研发现两处明显的"漏洞"：

1. **代码层漏注入**：[src/agents.py:415-493](src/agents.py#L415-L493) `_fetch_table_columns()` 已经从数据平台拉取了完整字段类型信息（含 `data_type`、`comment`、`is_key_field`）并写入 `context["column_types"]`，但下游 [src/agents.py:253-270](src/agents.py#L253-L270) `build_user_message()` **完全没有读取这个字段注入 LLM**。LLM 只能从上游 `requirements_parser_output` 推断字段类型，难免猜错（如对 STRING 字段用 SUM）。

2. **Prompt 漏 Spark 方言**：[scripts/config.json](scripts/config.json) 配置 `engine: "Spark"`，[src/agents.py:482](src/agents.py#L482) 也强制用 Spark 引擎跑 DESCRIBE，但 [prompts/semantic-model-agent.md](prompts/semantic-model-agent.md) 全文不提"Spark"。LLM 容易生成 Presto/MySQL 特有语法（如 `TO_DATE`、`DATE_TRUNC` 调用方式不同），试跑必然失败。

**目标**：让 LLM 在生成 SQL 前**直接看到准确的字段类型**和**目标方言的明确指引**，把试跑失败率显著降下来。

**范围**：本次只做这两项最直接的修复（P1+P2），不动重试机制、错误反馈结构等其他可优化点。

---

## 改动 1（P1）：把 column_types 注入 LLM user_message

### 文件
[src/agents.py](src/agents.py) 的 `SemanticModelAgent.build_user_message()` 方法（第 253-270 行）

### 现状

```python
def build_user_message(self, context: dict) -> str:
    req_output = context.get("requirements_parser_output", {})
    msg = f"请基于以下需求解析结果，生成语义模型 SQL 和配置：\n\n```json\n{json.dumps(req_output, ...)}\n```"

    # 注入交叉校验警告
    warnings = context.get("_cross_validate_warnings", [])
    if warnings: ...

    # 注入试跑错误信息
    sql_test_error = context.get("_sql_test_error")
    if sql_test_error: ...

    msg += self._format_revision_context(context)
    return msg
```

### 改动方案

在 `build_user_message` 里在"需求解析结果"之后、"交叉校验警告"之前，新增一段 **数据源字段清单**：

```python
# 注入数据源字段类型信息（_fetch_table_columns 已经写入 context["column_types"]）
column_types = context.get("column_types", {})
if column_types:
    msg += "\n\n---\n**数据源字段清单（请严格按此类型生成 SQL，不要凭名称猜类型）：**\n"
    for table_name, fields in column_types.items():
        msg += f"\n**`{table_name}`**\n"
        for field_name, field_info in fields.items():
            data_type = field_info.get("data_type", "UNKNOWN")
            comment = field_info.get("comment", "")
            is_key = " 🔑" if field_info.get("is_key_field") else ""
            line = f"- `{field_name}` ({data_type}){is_key}"
            if comment:
                line += f" — {comment}"
            msg += line + "\n"
```

### 关键点
- `column_types` 由 [src/agents.py:415-493](src/agents.py#L415-L493) 在 `run()` 入口已经填好（不需要新增任何拉取逻辑）
- 数据结构是 `{table_name: {field_name: {data_type, comment, is_key_field}}}`
- 用 `🔑` 标注 key_fields（需求里指定的关键字段），帮助 LLM 优先关注核心字段
- 不限制字段数量（让 LLM 看到全表字段，便于 JOIN 字段推断）；后续若超长再考虑只展示 `is_key_field=True` 的

### 预期效果
- 字段类型不匹配类错误（对 STRING 用 SUM、对 INT 用 SUBSTRING）显著降低
- LLM 能利用 `comment` 更准确地理解字段业务含义

---

## 改动 2（P2）：Prompt 加 Spark SQL 方言指引

### 文件
[prompts/semantic-model-agent.md](prompts/semantic-model-agent.md)

### 现状
全文没有"Spark"字样，LLM 不知道目标方言；NULLIF / JOIN 等通用约束有，但缺方言层面的约束。

### 改动方案

**插入位置**：在 `## 3. 约束（一期边界）` 之后、`## 4. 输入规范` 之前（约第 33 行后），新增一节 `## 3.5 SQL 方言与平台约束`：

```markdown
## 3.5 SQL 方言与平台约束（重要）

你生成的 SQL 会在 **Spark SQL** 引擎上试跑（数据平台基于 Spark）。请遵守以下方言规则：

### 必须遵守

- **表名**：必须使用完整三级格式 `catalog.schema.table`（如 `iceberg_zjyprc_hadoop.meta.xxx`），不能省略前缀
- **日期函数**：用 `date_format(date_col, 'yyyy-MM-dd')`、`date_trunc('month', date_col)`、`date_add(date_col, n)`、`date_sub(date_col, n)`、`datediff(end, start)`；不要用 `TO_DATE(...)`（Spark 中行为与 Presto/Oracle 不同）
- **字符串函数**：用 `substring`、`concat`、`trim`、`upper`、`lower`、`regexp_extract`、`regexp_replace`
- **类型转换**：用 `CAST(x AS BIGINT)` 或 `CAST(x AS STRING)`，而不是 `::` 语法（PostgreSQL 风格）
- **NULL 处理**：`COALESCE(a, b)` / `NULLIF(a, b)` / `IFNULL(a, b)` 都支持
- **窗口函数**：`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` 等标准写法
- **CASE WHEN**：标准 SQL，无差异

### 禁止使用（Presto / MySQL 特有，Spark 不支持或行为不同）

- ❌ `LIMIT n OFFSET m`（Spark 用 `LIMIT m, n` 或 `LIMIT n` + 分页方式）
- ❌ `INTERVAL '1' DAY` 风格（Spark 用 `INTERVAL 1 DAY`，不带引号）
- ❌ `||` 字符串拼接（Spark 用 `concat(a, b)` 或 `CONCAT(a, b)`）
- ❌ `DATE 'YYYY-MM-DD'` 字面量（Spark 直接用字符串 `'2024-01-01'` 后做 `CAST` 或 `date_format`）

### 性能与质量提示

- 多 JOIN 时事实表用 `INNER JOIN`、维度表用 `LEFT JOIN`
- 涉及除法的衍生指标，分母必须用 `NULLIF(denom, 0)` 包裹
- 对 `dt`、`event_date` 等分区字段做范围过滤时，**不要**对字段套函数（避免分区裁剪失效），如写 `dt >= '2024-01-01'` 而不是 `date(dt) >= '2024-01-01'`
- 对字符串字段不要用 `SUM/AVG`；对数值字段不要用字符串函数

**违反以上规则会导致试跑失败。**
```

### 关键点
- **明确声明方言** —— 当前 prompt 完全没说，是最大盲点
- **正/反对照** —— 既给"必须用什么"，也给"禁止用什么"，约束更清晰
- **结合性能** —— 顺便把 Iceberg 分区裁剪这种 Spark + Iceberg 特性提一下
- 不动版本号；最后的"## 9. 版本变更日志"由后续提交时再加一行 v0.7

### 预期效果
- LLM 不再生成 Presto/MySQL 特有语法
- LLM 主动用 Spark 风格的日期/字符串/类型转换函数

---

## 关键文件改动清单

| 文件 | 改动类型 | 影响范围 |
|---|---|---|
| [src/agents.py](src/agents.py) | 在 `SemanticModelAgent.build_user_message()` 第 257 行前后插入 ~10 行 | 仅语义模型 Agent |
| [prompts/semantic-model-agent.md](prompts/semantic-model-agent.md) | 第 33 行后新增 `## 3.5` 一整节（约 30 行 markdown） | LLM 行为 |

无需新增依赖、无需改 config、无需改 `_fetch_table_columns`（已经在做正确的事，只是输出没被消费）。

---

## 复用的已有工具 / 数据

- [src/agents.py:415-493](src/agents.py#L415-L493) `_fetch_table_columns()` —— 已经把 `column_types` 写入 context，**直接读取使用**
- [src/data_platform_api.py:455-529](src/data_platform_api.py#L455-L529) `describe_table()` —— 上游已经在用，返回结构稳定（`column_name` / `data_type` / `comment`）
- [scripts/config.json](scripts/config.json) `engine: "Spark"` —— 配置里已经声明，跟 prompt 改动一致

---

## 验证方式

### 单元层
1. `python -m py_compile src/agents.py` 语法检查通过
2. 临时打印调试：在 `build_user_message` 末尾加一行 `print(msg)`，观察 user_message 里**确实出现了"数据源字段清单"**这一段，且包含 data_type 和 key_field 标记

### 端到端
1. 重启服务 `python scripts/feishu_orchestrator.py`
2. 群里 `@看板助手 帮我做个用户行为看板，数据来自 iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view，要校验语义模型`
3. 观察 `logs/feishu_orchestrator_<时间戳>.log`：
   - `[PIPELINE]` 阶段进入语义模型 Agent
   - 应该看到 `column_types` 被拉取（已有日志）
   - **试跑日志不再出现 `cannot resolve` / `data type mismatch` / `TO_DATE not found` 等方言性错误**
   - Pipeline 整体能跑通 6 步（不再卡在第 ②步）

### 对比指标
跑同一份需求 3-5 次，看：
- 改前：`SQL试跑失败` 出现的次数
- 改后：同样错误出现的次数

预期改后能看到：
- 字段类型类错误 ↓（来自 P1）
- 方言语法类错误 ↓（来自 P2）
- LLM 单次生成就通过试跑的概率 ↑

### 回滚
两处改动都是**纯增量**（加代码、加 prompt 段落，不改既有逻辑），任何一处出问题都可以单独 revert，不影响 Pipeline 其他环节。

---

## 后续可考虑（本次未做）

| 编号 | 描述 | 原因暂缓 |
|---|---|---|
| P3 | 错误诊断结构化（`_format_test_errors` 按错误类型分类输出建议） | 需要看实际错误样本积累 |
| P4 | 把"重试次数"传给 LLM，让它在最后一次尝试时降档 | 改动有限收益 |
| P5 | 第 1 次失败时按错误类型决定重试 vs 重生成 | 需要先有 P3 的分类 |

---

## 参考材料

- 项目总览见：[迭代记录_2026-05-14.md](迭代记录_2026-05-14.md)
- Phase 1 调研详细发现：保存在本次会话，必要时可重新调研
