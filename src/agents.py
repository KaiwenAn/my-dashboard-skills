"""
Agent 模块：加载 System Prompt 并执行 Agent

每个 Agent 的职责：
1. 加载对应的 System Prompt 文件
2. 将上游数据格式化为 user message
3. 调用 LLM 获取响应
4. 校验输出格式
"""

import os
import json
from enum import Enum
from .llm import LLMClient
from utils.logging_config import get_logger

# 模块级 logger
logger = get_logger(__name__)


class RunMode(Enum):
    """
    Pipeline 运行模式

    模式1（plan）：方案模式
      - 仅运行4个Agent生成方案文档
      - 不调用BI API
      - 不需要 bi_config
      - 语义模型Agent输出校验较宽松（虚拟表信息缺失不阻断）

    模式2（publish）：推送模式
      - 运行4个Agent生成方案文档
      - 语义模型Agent完成后，自动调用 BI API 创建语义模型
      - 必须提供 bi_config（包含 space_id 和 creator，datasource_id 自动获取）
      - 语义模型Agent输出必须完整（SQL、dimensions、metrics 均必须有效）
    """
    PLAN = "plan"      # 方案模式：只看方案不推送
    PUBLISH = "publish"  # 推送模式：生成方案 + 推送到BI平台

# Agent 名称 → System Prompt 文件名映射
AGENT_PROMPT_FILES = {
    "requirements_parser": "requirements-parser-agent",
    "semantic_model": "semantic-model-agent",
    "bi_push": "bi-push-agent",
    "chart_design": "chart-design-agent",
    "instruction_generator": "instruction-generator-agent",
    "solution_generator": "solution-generator-agent",
}

# System Prompt 文件所在目录（项目根目录的 prompts/）
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def load_prompt(agent_name: str) -> str:
    """加载指定 Agent 的 System Prompt 文件"""
    prompt_filename = AGENT_PROMPT_FILES.get(agent_name, agent_name)
    prompt_file = os.path.join(PROMPTS_DIR, f"{prompt_filename}.md")
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f"找不到 System Prompt 文件：{prompt_file}")
    with open(prompt_file, "r", encoding="utf-8") as f:
        return f.read()


class BaseAgent:
    """Agent 基类"""

    def __init__(self, agent_name: str, llm: LLMClient):
        self.agent_name = agent_name
        self.llm = llm
        self.system_prompt = load_prompt(agent_name)

    def build_user_message(self, context: dict) -> str:
        """构建用户消息，子类必须实现"""
        raise NotImplementedError

    def validate_output(self, output: dict) -> None:
        """校验输出格式，子类必须实现"""
        raise NotImplementedError

    @staticmethod
    def _format_revision_context(context: dict) -> str:
        """将修改意见格式化为注入文本，子类可在 build_user_message 中调用"""
        revision = context.get("_revision_context")
        if not revision:
            return ""
        parts = [
            "\n\n---",
            "🔄 **本次为局部重新生成，以下是修改意见：**",
        ]
        # 修改原因
        if revision.get("reason"):
            parts.append(f"- **修改原因**：{revision['reason']}")
        # 修改的确认项
        if revision.get("confirmation_item"):
            item = revision["confirmation_item"]
            parts.append(f"- **涉及确认项**：#{item.get('index', '?')} {item.get('item', '')}")
            if item.get("category"):
                parts.append(f"- **类别**：{item['category']}")
        # 用户修改意见
        if revision.get("user_feedback"):
            parts.append(f"- **修改意见**：{revision['user_feedback']}")
        parts.append("---\n")
        return "\n".join(parts)

    def run(self, context: dict) -> dict:
        """
        执行 Agent

        Args:
            context: 包含上游所有输出的上下文

        Returns:
            Agent 的输出 dict

        Raises:
            ValueError: 输出校验失败
        """
        logger.info(f"执行 Agent: {self.agent_name}")

        user_message = self.build_user_message(context)
        logger.debug(f"  输入长度: {len(user_message)} 字符")

        output = self.llm.chat_json(
            system_prompt=self.system_prompt,
            user_message=user_message,
            temperature=0.1,
        )

        self.validate_output(output)
        logger.debug(f"  输出校验通过")

        return output


class RequirementsParserAgent(BaseAgent):
    """需求解析 Agent"""

    def __init__(self, llm: LLMClient):
        super().__init__("requirements-parser-agent", llm)

    def build_user_message(self, context: dict) -> str:
        user_input = context.get("user_input", {})
        msg = f"请解析以下看板需求：\n\n```json\n{json.dumps(user_input, ensure_ascii=False, indent=2)}\n```"
        msg += self._format_revision_context(context)
        return msg

    def validate_output(self, output: dict) -> None:
        if "parsed_requirements" not in output:
            raise ValueError("需求解析输出缺少 parsed_requirements 字段")
        pr = output["parsed_requirements"]
        if "metrics_spec" not in pr or len(pr["metrics_spec"]) < 1:
            raise ValueError("需求解析输出 metrics_spec 至少需要 1 项")
        for m in pr["metrics_spec"]:
            if "confidence" not in m:
                raise ValueError(f"指标 '{m.get('name', '?')}' 缺少 confidence 字段")
        if "confirmation_items" not in output or len(output["confirmation_items"]) < 1:
            raise ValueError("confirmation_items 不能为空，至少需要 1 项建议确认")
        # 检查维度是否有 source_table
        for d in pr.get("dimensions_spec", []):
            if "source_table" not in d or not d["source_table"]:
                raise ValueError(
                    f"维度 '{d.get('name', '?')}' 缺少 source_table 字段，必须指明来源表"
                )


def cross_validate_requirements(
    req_output: dict, user_input: dict
) -> list[str]:
    """
    需求解析 Agent 输出的后置交叉校验

    检查维度 source_table 指向的表是否真的包含该字段（通过 key_fields 匹配）。
    考虑 field_mappings 中的别名关系。

    返回警告列表（非阻断），警告会注入到语义模型 Agent 的 context 中。
    """
    warnings = []
    pr = req_output.get("parsed_requirements", {})
    data_sources = user_input.get("data_sources", [])

    # 构建 table_name → key_fields 映射（考虑 field_mappings）
    table_fields = {}
    table_mappings = {}
    for ds in data_sources:
        tname = ds.get("table_name", "")
        fields = set(ds.get("key_fields", []))
        mappings = ds.get("field_mappings", {})
        table_fields[tname] = fields
        if mappings:
            table_mappings[tname] = mappings
        else:
            table_mappings[tname] = {}

    # 校验每个维度的 source_table
    for dim in pr.get("dimensions_spec", []):
        dim_name = dim.get("name", "")
        source = dim.get("source_table", "")

        if source not in table_fields:
            warnings.append(
                f"维度 '{dim_name}' 的 source_table '{source}' 不在输入的 data_sources 中"
            )
            continue

        # 检查字段是否在 key_fields 中（直接匹配）
        target_fields = table_fields[source]
        if dim_name in target_fields:
            continue  # 直接匹配，OK

        # 检查是否是 field_mappings 的 value（别名），应使用 key（实际字段名）
        mappings = table_mappings.get(source, {})
        actual_field = None
        for k, v in mappings.items():
            if v == dim_name:
                actual_field = k
                break

        if actual_field and actual_field in target_fields:
            warnings.append(
                f"维度 '{dim_name}' 在表 '{source}' 中的实际字段名为 '{actual_field}'"
                f"（field_mappings 映射），下游 SQL 中请使用 '{actual_field}'"
            )
        elif actual_field:
            warnings.append(
                f"维度 '{dim_name}' 映射到字段 '{actual_field}'，但该字段不在表 '{source}' 的 key_fields 中"
            )
        else:
            # 也尝试反向查找：dim_name 是实际字段名
            found = False
            for ds in data_sources:
                ds_mappings = ds.get("field_mappings", {})
                for k, v in ds_mappings.items():
                    if k == dim_name:
                        found = True
                        break
                if found:
                    break
            if not found:
                warnings.append(
                    f"维度 '{dim_name}' 在表 '{source}' 的 key_fields {target_fields} 中未找到"
                )

    return warnings


class SemanticModelAgent(BaseAgent):
    """语义模型 Agent"""

    def __init__(self, llm: LLMClient):
        super().__init__("semantic-model-agent", llm)

    def build_user_message(self, context: dict) -> str:
        req_output = context.get("requirements_parser_output", {})
        msg = f"请基于以下需求解析结果，生成语义模型 SQL 和配置：\n\n```json\n{json.dumps(req_output, ensure_ascii=False, indent=2)}\n```"

        # 注入交叉校验警告
        warnings = context.get("_cross_validate_warnings", [])
        if warnings:
            msg += "\n\n**⚠️ 交叉校验警告（请注意）：**\n"
            for w in warnings:
                msg += f"- {w}\n"

        # 注入试跑错误信息（SQL试跑失败时，语义模型Agent根据此信息修正SQL）
        sql_test_error = context.get("_sql_test_error")
        if sql_test_error:
            msg += f"\n\n**⚠️ 上次生成的SQL试跑失败，请修正以下错误后重新生成：**\n{sql_test_error}"

        msg += self._format_revision_context(context)
        return msg

    def validate_output(self, output: dict) -> None:
        if "semantic_models" not in output or len(output["semantic_models"]) < 1:
            raise ValueError("语义模型输出至少需要 1 个 semantic_model")
        for model in output["semantic_models"]:
            if "sql" not in model or not model["sql"].strip():
                raise ValueError(f"模型 '{model.get('model_name', '?')}' 缺少 sql 字段")
            if "dimensions" not in model or len(model["dimensions"]) < 1:
                raise ValueError(f"模型 '{model.get('model_name', '?')}' 至少需要 1 个维度")
            if "metrics" not in model or len(model["metrics"]) < 1:
                raise ValueError(f"模型 '{model.get('model_name', '?')}' 至少需要 1 个指标")
            # 检查衍生指标的 depends_on
            for metric in model["metrics"]:
                if metric.get("aggregation") == "自定义" and not metric.get("depends_on"):
                    raise ValueError(
                        f"衍生指标 '{metric.get('field_name', '?')}' 必须有 depends_on"
                    )
            # 检查维度和指标字段名互斥（不得重复）
            dim_fields = {d.get("field_name") for d in model.get("dimensions", [])}
            metric_fields = {m.get("field_name") for m in model.get("metrics", [])}
            overlap = dim_fields & metric_fields
            if overlap:
                raise ValueError(
                    f"模型 '{model.get('model_name', '?')}' 维度和指标存在重复字段: {overlap}"
                )

    def run(self, context: dict) -> dict:
        """
        重写 run 方法，增加 SQL 试跑逻辑（混合重试策略）：
        - 启用试跑时：生成SQL → 试跑 → 失败则重试（最多3次）
        - 第1次试跑失败：直接重试相同SQL（可能是临时资源问题）
        - 第2-3次试跑失败：把错误信息传给LLM，重新生成SQL
        - 只有全部SQL试跑通过，才返回output
        """
        # 如果不启用试跑，直接调用父类方法
        if not context.get("enable_sql_test", False):
            return super().run(context)

        # 懒加载 data_platform_api
        try:
            from data_platform_api import DataPlatformClient, SQLExecutionError
        except ImportError:
            logger.warning("未找到 data_platform_api 模块，跳过试跑")
            return super().run(context)

        # 从context中获取数据平台配置
        dp_config = context.get("data_platform_config", {})
        base_url = dp_config.get("base_url", "")
        token = dp_config.get("token", "")
        # 注意：catalog和schema不再使用默认值，让DataPlatformClient自行处理（默认为None）
        catalog = dp_config.get("catalog")  # 不带默认值，不存在时为None
        schema = dp_config.get("schema")     # 不带默认值，不存在时为None
        engine = dp_config.get("engine", "Presto")

        if not token:
            logger.warning("未配置数据平台token，跳过试跑")
            return super().run(context)

        # 创建DataPlatformClient实例
        try:
            client = DataPlatformClient(base_url, token, catalog, schema, engine)
        except Exception as e:
            logger.warning(f"创建数据平台客户端失败：{e}，跳过试跑")
            return super().run(context)

        # 自动拉取用户指定表的真实字段（仅在不启用试跑时也需要）
        # 注意：这个逻辑也适用于不试跑的场景，所以放在条件分支之前
        self._fetch_table_columns(client, context)

        # 如果不启用试跑，生成SQL后直接返回（不试跑）
        if not context.get("enable_sql_test", False):
            return super().run(context)

        # 混合重试循环
        retry_count = 0
        max_retry = 3
        last_error = None
        output = None

        while retry_count < max_retry:
            # 决定是否需要重新生成SQL
            need_regenerate = output is None or (retry_count >= 1 and last_error)

            if need_regenerate:
                # 注入试跑错误信息（让LLM修正SQL）
                if last_error and retry_count >= 1:
                    context["_sql_test_error"] = last_error
                    logger.debug(f"注入试跑错误信息到LLM输入")

                try:
                    # 调用父类方法生成SQL
                    logger.info(f"生成语义模型SQL（尝试 {retry_count + 1}/{max_retry}）")
                    output = super().run(context)

                    # 打印生成的完整SQL（调试用）
                    for m in output.get("semantic_models", []):
                        model_name = m.get("model_name", "?")
                        sql = m.get("sql", "")
                        logger.debug(f"\n模型 [{model_name}] 完整SQL：\n{sql}")

                finally:
                    # 清除注入的错误信息（避免影响其他Agent）
                    if "_sql_test_error" in context:
                        del context["_sql_test_error"]

            # 并行试跑所有语义模型的SQL
            logger.info(f"试跑SQL（尝试 {retry_count + 1}/{max_retry}）...")
            test_results = self._test_sql_parallel(client, output["semantic_models"])
            failed = [r for r in test_results if not r["success"]]

            if not failed:
                logger.info(f"SQL试跑全部通过")
                return output  # 试跑通过，返回结果

            # 试跑失败
            retry_count += 1
            last_error = self._format_test_errors(failed)

            logger.warning(f"SQL试跑失败（{retry_count}/{max_retry}）：{len(failed)} 个模型试跑失败")
            for f in failed:
                error_msg = f['error']['message'] if f.get('error') else '未知错误'
                logger.warning(f"  - {f['model_name']}: {error_msg}")

            if retry_count >= max_retry:
                # 已达最大重试次数
                error_summary = self._format_test_errors(failed)
                raise ValueError(f"SQL试跑失败，已达最大重试次数：\n{error_summary}")

            if retry_count == 1:
                # 第1次失败：直接重试（不重新生成SQL）
                logger.info(f"第1次失败，直接重试相同SQL（可能是临时资源问题）")
                # output 保持不变，下次循环会使用相同的SQL试跑
            else:
                # 第2-3次失败：重新生成SQL
                logger.info(f"第{retry_count}次失败，重新生成SQL...")
                output = None  # 重置output，下次循环会重新生成SQL

        # 不应该到达这里
        raise ValueError(f"SQL试跑失败，未预期退出")

    def _fetch_table_columns(self, client, context: dict) -> None:
        """
        自动从数据平台拉取用户指定表的真实字段信息

        从 user_input.data_sources 中获取所有表名，调用 describe_table 获取字段详情，
        格式化为 column_types 结构注入到 context 中，供语义模型 Agent 使用。

        Args:
            client: DataPlatformClient实例
            context: Pipeline context，会被直接修改
        """
        user_input = context.get("user_input", {})
        data_sources = user_input.get("data_sources", [])

        if not data_sources:
            logger.debug("未找到 data_sources，跳过自动字段拉取")
            return

        column_types = {}

        for ds in data_sources:
            table_name = ds.get("table_name", "")
            if not table_name:
                continue

            # 如果用户已经提供了字段信息（key_fields），优先使用，但仍然拉取完整字段
            key_fields = set(ds.get("key_fields", []))
            field_mappings = ds.get("field_mappings", {})
            field_descriptions = ds.get("field_descriptions", {})

            logger.debug(f"正在获取表 [{table_name}] 的字段信息...")

            try:
                columns = client.describe_table(table_name)

                if not columns:
                    logger.warning(f"表 [{table_name}] 未获取到字段信息，尝试备用查询")
                    # describe_table 失败时，尝试用 DESCRIBE 备用语法
                    columns = self._describe_table_fallback(client, table_name)

                if columns:
                    table_info = {}
                    for col in columns:
                        col_name = col.get("column_name", "")
                        if not col_name:
                            continue

                        data_type = col.get("data_type", "UNKNOWN")
                        comment = col.get("comment", "") or field_descriptions.get(col_name, "")

                        table_info[col_name] = {
                            "data_type": data_type,
                            "comment": comment,
                        }

                        # 如果用户在 key_fields 中指定了该字段，标记为重要字段
                        if col_name in key_fields:
                            table_info[col_name]["is_key_field"] = True

                    column_types[table_name] = table_info
                    logger.info(f"表 [{table_name}] 获取到 {len(table_info)} 个字段")
                else:
                    logger.warning(f"表 [{table_name}] 字段获取失败")

            except Exception as e:
                logger.warning(f"获取表 [{table_name}] 字段失败：{e}")

        # 将 column_types 注入到 context 中，供语义模型 Agent 使用
        if column_types:
            context["column_types"] = column_types
            logger.info(f"已自动拉取 {len(column_types)} 个表的字段信息，已注入到 context")

            # 打印字段摘要（便于调试）
            for tname, fields in column_types.items():
                key_fields_in_table = [f for f, info in fields.items() if info.get("is_key_field")]
                if key_fields_in_table:
                    logger.debug(f"     - {tname}: {len(fields)} 个字段（含关键字段: {', '.join(key_fields_in_table)}）")
                else:
                    logger.debug(f"     - {tname}: {len(fields)} 个字段")

    def _describe_table_fallback(self, client, table_name: str) -> list:
        """
        备用表结构查询（当 describe_table 失败时使用）

        Args:
            client: DataPlatformClient实例
            table_name: 表名

        Returns:
            字段列表
        """
        try:
            # 尝试用 DESCRIBE table 语法
            result = client.execute_query(f"DESCRIBE {table_name}", fetch_results=True, timeout=60)
            if result.get("success"):
                columns = []
                for row in result.get("results", []):
                    col_name = row.get("col_name", row.get("column_name", ""))
                    data_type = row.get("data_type", row.get("type", ""))
                    comment = row.get("comment", row.get("col_comment", ""))
                    if col_name and not col_name.startswith("#"):
                        columns.append({
                            "column_name": col_name,
                            "data_type": data_type,
                            "comment": comment,
                        })
                return columns
        except Exception:
            pass

        # 尝试 SHOW COLUMNS 语法
        try:
            result = client.execute_query(f"SHOW COLUMNS FROM {table_name}", fetch_results=True, timeout=60)
            if result.get("success"):
                columns = []
                for row in result.get("results", []):
                    col_name = row.get("col_name", row.get("column_name", row.get("field", "")))
                    if col_name:
                        columns.append({
                            "column_name": col_name,
                            "data_type": "UNKNOWN",
                            "comment": "",
                        })
                return columns
        except Exception:
            pass

        return []

    def _test_sql_parallel(self, client, semantic_models: list) -> list:
        """
        并行试跑多个语义模型的SQL

        Args:
            client: DataPlatformClient实例
            semantic_models: 语义模型列表，每个元素包含 model_name 和 sql

        Returns:
            结果列表，每个元素包含 model_name, success, error, query_id
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def test_single(model):
            """试跑单个模型的SQL"""
            sql = model.get("sql", "")
            model_name = model.get("model_name", "?")

            if not sql.strip():
                return {
                    "model_name": model_name,
                    "success": False,
                    "error": {"code": "EMPTY_SQL", "message": "SQL为空"},
                    "query_id": None,
                }

            try:
                result = client.execute_query(sql, fetch_results=False)
                return {
                    "model_name": model_name,
                    "success": result["success"],
                    "error": result.get("error"),
                    "query_id": result.get("query_id"),
                }
            except Exception as e:
                return {
                    "model_name": model_name,
                    "success": False,
                    "error": {"code": "EXCEPTION", "message": str(e)},
                    "query_id": None,
                }

        # 使用线程池并行试跑
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(test_single, model): model for model in semantic_models}
            results = []
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _format_test_errors(self, failed_results: list) -> str:
        """
        将试跑失败信息格式化为文本（用于注入到LLM输入）

        Args:
            failed_results: 试跑失败的结果列表

        Returns:
            格式化的错误文本
        """
        lines = ["以下语义模型的SQL试跑失败，请根据错误信息修正SQL："]
        for r in failed_results:
            error = r.get("error", {})
            error_code = error.get("code", "UNKNOWN")
            error_msg = error.get("message", "未知错误")
            lines.append(f"- **{r['model_name']}**：{error_msg}（错误码：{error_code}）")

            # 如果是SQL执行异常，给出提示
            if error_code in ("4007406", "SQLExecutionError"):
                lines.append(f"  - 这是SQL执行异常，请优先检查：表名/字段名是否存在、JOIN条件是否正确、SQL语法是否合法")

        return "\n".join(lines)


class ChartDesignAgent(BaseAgent):
    """图表设计 Agent"""

    def __init__(self, llm: LLMClient):
        super().__init__("chart-design-agent", llm)

    def build_user_message(self, context: dict) -> str:
        req_output = context.get("requirements_parser_output", {})
        sm_output = context.get("semantic_model_output", {})
        combined = {
            "from_requirements_parser": {
                "visualization_requirements": req_output.get("visualization_requirements", {}),
                "metrics_spec": req_output.get("parsed_requirements", {}).get("metrics_spec", []),
                "dimensions_spec": req_output.get("parsed_requirements", {}).get("dimensions_spec", []),
                "confirmation_items": req_output.get("confirmation_items", []),
            },
            "from_semantic_model": {
                "semantic_models": [
                    {
                        "model_name": m.get("model_name"),
                        "dimensions": m.get("dimensions", []),
                        "metrics": m.get("metrics", []),
                        "tables_used": m.get("tables_used", []),
                        "filter_config": m.get("filter_config", {}),
                    }
                    for m in sm_output.get("semantic_models", [])
                ],
                "inherit_confirmation_items": sm_output.get("inherit_confirmation_items", []),
                "new_confirmation_items": sm_output.get("new_confirmation_items", []),
            },
        }
        return f"请基于以下需求和语义模型信息，设计看板图表方案：\n\n```json\n{json.dumps(combined, ensure_ascii=False, indent=2)}\n```" + self._format_revision_context(context)

    def validate_output(self, output: dict) -> None:
        if "chart_list" not in output or len(output["chart_list"]) < 1:
            raise ValueError("图表设计输出至少需要 1 个图表")
        if "global_filters" not in output or len(output["global_filters"]) < 1:
            raise ValueError("图表设计输出至少需要 1 个全局筛选器")
        for chart in output["chart_list"]:
            if "semantic_model" not in chart:
                raise ValueError(f"图表 '{chart.get('chart_id', '?')}' 缺少 semantic_model 关联")
            if "layout" not in chart:
                raise ValueError(f"图表 '{chart.get('chart_id', '?')}' 缺少 layout 配置")


class InstructionGeneratorAgent(BaseAgent):
    """看板指令生成 Agent"""

    def __init__(self, llm: LLMClient):
        super().__init__("instruction-generator-agent", llm)

    def build_user_message(self, context: dict) -> str:
        cd_output = context.get("chart_design_output", {})
        sm_output = context.get("semantic_model_output", {})
        bi_push_output = context.get("bi_push_output", {})

        # 获取 model_id：优先从BI推送结果中获取
        model_id = None
        if bi_push_output and not bi_push_output.get("skipped", False):
            results = bi_push_output.get("results", [])
            if results:
                model_id = results[0].get("model_id")

        # 合并图表设计输出和语义模型信息
        combined = {
            "chart_list": cd_output.get("chart_list", []),
            "global_filters": cd_output.get("global_filters", []),
            "layout_spec": cd_output.get("layout_spec", {}),
            "semantic_model_info": {
                "model_name": sm_output.get("semantic_models", [{}])[0].get("model_name") if sm_output.get("semantic_models") else None,
                "model_id": model_id,
            },
        }

        msg = f"请基于以下图表设计方案，生成标准化的看板搭建指令：\n\n```json\n{json.dumps(combined, ensure_ascii=False, indent=2)}\n```"
        msg += self._format_revision_context(context)
        return msg

    def validate_output(self, output: dict) -> None:
        if "instruction_id" not in output:
            raise ValueError("指令输出缺少 instruction_id 字段")
        if "title" not in output:
            raise ValueError("指令输出缺少 title 字段")
        if "charts" not in output or len(output["charts"]) < 1:
            raise ValueError("指令输出 charts 至少需要 1 个图表")
        if "filters" not in output:
            raise ValueError("指令输出缺少 filters 字段")


class SolutionGeneratorAgent(BaseAgent):
    """方案生成 Agent"""

    def __init__(self, llm: LLMClient):
        super().__init__("solution-generator-agent", llm)

    def build_user_message(self, context: dict) -> str:
        req_output = context.get("requirements_parser_output", {})
        sm_output = context.get("semantic_model_output", {})
        cd_output = context.get("chart_design_output", {})
        ig_output = context.get("instruction_generator_output", {})
        bi_push_output = context.get("bi_push_output", {})

        combined = {
            "from_requirements_parser": req_output,
            "from_semantic_model": sm_output,
            "from_chart_design": cd_output,
            "from_instruction_generator": ig_output,
        }
        # 推送模式：附加 BI 推送结果（含 model_id），让方案里能展示模型ID
        if bi_push_output and not bi_push_output.get("skipped", False):
            combined["from_bi_push"] = bi_push_output

        msg = (
            "请基于以下 Agent 的输出，生成完整的看板搭建方案文档（Markdown 格式）：\n\n"
            f"```json\n{json.dumps(combined, ensure_ascii=False, indent=2)}\n```"
        )
        msg += self._format_revision_context(context)
        return msg

    def validate_output(self, output) -> None:
        # 方案生成 Agent 输出 Markdown 字符串，不是 JSON
        if isinstance(output, str):
            if len(output.strip()) < 100:
                raise ValueError("方案文档太短，可能生成失败")
            return
        # 如果 LLM 返回的是 JSON（有些模型会这样），检查内容
        if isinstance(output, dict):
            if "solution" in output:
                return
            # 尝试整体转成字符串
            return
        raise ValueError(f"方案生成输出格式异常：{type(output)}")

    def run(self, context: dict) -> str:
        """
        重写 run 方法，方案生成 Agent 返回 Markdown 字符串而非 JSON

        Returns:
            Markdown 格式的搭建方案文档
        """
        logger.info(f"执行 Agent: {self.agent_name}")

        user_message = self.build_user_message(context)
        logger.debug(f"  输入长度: {len(user_message)} 字符")

        # 方案生成 Agent 用 chat 而非 chat_json，因为输出是 Markdown
        raw_output = self.llm.chat(
            system_prompt=self.system_prompt,
            user_message=user_message,
            temperature=0.1,
            max_tokens=16384,  # Markdown 文档通常较长
        )

        logger.info(f"方案生成完成，文档长度: {len(raw_output)} 字符")
        return raw_output


class BIPushAgent(BaseAgent):
    """
    BI 推送 Agent

    重写了 run() 方法，不调用 LLM，直接执行 BI API 调用逻辑。
    在推送模式（PUBLISH）下，语义模型 Agent 完成后立即执行，
    将生成的语义模型推送到 BI 平台。
    """

    def __init__(self, llm: LLMClient):
        # 不加载 System Prompt（该 Agent 不调用 LLM）
        self.agent_name = "bi_push"
        self.llm = llm
        self.system_prompt = ""

    def build_user_message(self, context: dict) -> str:
        """不使用（重写以符合接口）"""
        return ""

    def validate_output(self, output: dict) -> None:
        """校验推送结果（跳过，由 run() 内部保证）"""
        pass

    def run(self, context: dict) -> dict:
        """
        执行 BI 推送（不调用 LLM）

        返回：
            {
                "skipped": True/False,
                "reason": "跳过原因（仅 skipped=True 时）",
                "total": 成功推送模型数,
                "results": [{"model_name": ..., "model_id": ...}, ...],
                "errors": [{"model_name": ..., "error": ...}, ...],
            }
        """
        logger.info(f"执行 Agent: {self.agent_name}")

        try:
            # 1. 提取 bi_config
            user_input = context.get("user_input", {})
            bi_config = extract_bi_config(user_input)

            # 2. 若无 bi_config，跳过
            if not bi_config:
                logger.warning("BI 推送跳过：bi_config 未配置")
                return {
                    "skipped": True,
                    "reason": "bi_config 未配置，请在 BI 配置中填写工场空间 ID 和操作人",
                }

            # 3. 校验 bi_config
            config_error = validate_bi_config(bi_config)
            if config_error:
                logger.warning(f"BI 推送跳过：{config_error}")
                return {
                    "skipped": True,
                    "reason": config_error,
                }

            # 4. 获取语义模型输出
            sm_output = context.get("semantic_model_output", {})

            # 5. 校验语义模型输出完整性
            output_error = validate_publish_mode_output(sm_output)
            if output_error:
                logger.warning(f"BI 推送跳过：语义模型输出不完整 - {output_error}")
                return {
                    "skipped": True,
                    "reason": f"语义模型输出不完整：{output_error}",
                }

            # 6. 自动获取数据源ID
            from bi_api import BIClient, create_and_publish_all

            space_id = bi_config["space_id"]
            creator = bi_config["creator"]
            base_url = bi_config.get("base_url", "")
            logger.info(f"正在获取数据源ID: user={creator}, spaceId={space_id}...")

            datasource_id = BIClient.get_datasource_id(
                user=creator,
                space_id=space_id,
                base_url=base_url,
            )

            # 将 datasource_id 注入 bi_config，供 create_and_publish_all 使用
            bi_config_for_api = {**bi_config, "datasource_id": datasource_id}

            # 7. 调用 BI API 批量推送

            model_count = len(sm_output.get("semantic_models", []))
            logger.info(f"正在推送 {model_count} 个语义模型到 BI 平台...")

            push_result = create_and_publish_all(
                bi_config=bi_config_for_api,
                semantic_models_output=sm_output,
            )

            # 8. 打印结果摘要
            if push_result["errors"]:
                logger.warning(f"推送完成，{len(push_result['errors'])} 个模型失败：")
                for err in push_result["errors"]:
                    logger.warning(f"     - {err['model_name']}: {err['error']}")
            else:
                logger.info(f"推送完成：{push_result['total']} 个语义模型全部成功")

            return {
                "skipped": False,
                **push_result,
            }

        except Exception as e:
            logger.error(f"BI 推送异常：{e}")
            return {
                "skipped": False,
                "error": str(e),
                "total": 0,
                "results": [],
                "errors": [{"model_name": "all", "error": str(e)}],
            }


# Agent 注册表
AGENTS = {
    "requirements_parser": RequirementsParserAgent,
    "semantic_model": SemanticModelAgent,
    "bi_push": BIPushAgent,
    "chart_design": ChartDesignAgent,
    "instruction_generator": InstructionGeneratorAgent,
    "solution_generator": SolutionGeneratorAgent,
}

# 执行顺序
PIPELINE_ORDER = [
    "requirements_parser",
    "semantic_model",
    "bi_push",
    "chart_design",
    "instruction_generator",
    "solution_generator",
]


# ============================================================
# 运行模式辅助函数
# ============================================================

def extract_bi_config(user_input: dict) -> dict | None:
    """
    从 user_input 中提取 bi_config

    Args:
        user_input: 表单输入 JSON

    Returns:
        bi_config dict 或 None（如果未配置）
    """
    return user_input.get("bi_config")


def validate_bi_config(bi_config: dict | None) -> str:
    """
    校验 bi_config 是否有效（推送模式必须）

    Args:
        bi_config: BI配置或 None

    Returns:
        "" 表示有效，错误消息字符串表示无效原因
    """
    if bi_config is None:
        return "bi_config 未配置，请先在'BI配置'中填写工场空间ID和操作人"

    if not bi_config.get("space_id"):
        return "bi_config.space_id 未填写（工场空间ID）"

    if not bi_config.get("creator"):
        return "bi_config.creator 未填写（操作人）"

    try:
        space_id = int(bi_config["space_id"])
        if space_id <= 0:
            return "bi_config.space_id 必须为正整数"
    except (ValueError, TypeError):
        return "bi_config.space_id 必须是有效整数"

    return ""


def validate_publish_mode_output(semantic_model_output: dict) -> str:
    """
    在推送模式下校验语义模型Agent输出的完整性

    推送模式要求语义模型Agent输出能够直接用于 BI API 调用。
    必须包含：
    - SQL 完整且非空
    - 每个模型至少有一个维度（用于 virtualTable）
    - 每个模型至少有一个指标（用于 analysisVO）

    Args:
        semantic_model_output: 语义模型Agent的输出 dict

    Returns:
        "" 表示通过，错误消息字符串表示问题所在
    """
    if not semantic_model_output:
        return "语义模型Agent输出为空"

    models = semantic_model_output.get("semantic_models", [])
    if not models:
        return "semantic_models 为空"

    for model in models:
        model_name = model.get("model_name", "?")

        # SQL 完整性
        sql = model.get("sql", "").strip()
        if not sql:
            return f"模型 '{model_name}' 的 SQL 为空"

        if len(sql) < 20:
            return f"模型 '{model_name}' 的 SQL 过短，可能不完整：{sql[:50]}..."

        # 维度检查（至少1个）
        dims = model.get("dimensions", [])
        if not dims:
            return f"模型 '{model_name}' 缺少维度定义，无法构建 virtualTable"

        # 指标检查（至少1个）
        metrics = model.get("metrics", [])
        if not metrics:
            return f"模型 '{model_name}' 缺少指标定义，无法构建 analysisVO"

        # 指标完整性检查
        for metric in metrics:
            metric_name = metric.get("field_name", "?")
            if not metric.get("sql_expression"):
                return f"指标 '{metric_name}' 缺少 sql_expression，无法发布"

    return ""  # 全部通过
