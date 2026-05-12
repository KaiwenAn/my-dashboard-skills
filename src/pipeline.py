"""
编排引擎：Pipeline / Step / Context

负责管理 4 个 Agent 的执行流程、数据传递、错误处理和重试。
支持两种运行模式：
- RunMode.PLAN（方案模式）：仅生成方案文档
- RunMode.PUBLISH（推送模式）：生成方案 + 调用 BI API 推送语义模型
"""

import json
import os
import sys
import time
import traceback  # 用于打印完整错误信息
from dataclasses import dataclass, field
from .llm import LLMClient
from .agents import AGENTS, PIPELINE_ORDER, load_prompt, cross_validate_requirements
from .agents import RunMode
from .renderer import render_html_report
from utils.logging_config import get_logger

# 模块级 logger
logger = get_logger(__name__)

# Windows GBK 兼容
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


@dataclass
class StepResult:
    """单步执行结果"""

    step_id: str
    agent_name: str
    status: str  # completed | failed | skipped
    input: dict
    output: any  # dict 或 str（方案生成 Agent）
    error: str = ""
    duration_ms: int = 0
    retry_count: int = 0


@dataclass
class PipelineResult:
    """Pipeline 执行结果"""

    pipeline_id: str
    status: str  # completed | failed
    solution_document: str = ""
    html_document: str = ""  # HTML 可视化报告
    steps: list = field(default_factory=list)
    all_confirmation_items: list = field(default_factory=list)
    error: str = ""
    total_duration_ms: float = 0.0
    step_durations: dict = field(default_factory=dict)  # {"agent_name": duration_ms}


class Pipeline:
    """看板生成 Pipeline"""

    MAX_RETRY = 3

    # Agent 中文名映射（用于进度展示）
    AGENT_DISPLAY_NAMES = {
        "requirements_parser": "需求解析",
        "semantic_model": "语义模型",
        "bi_push": "BI 推送",
        "chart_design": "图表设计",
        "instruction_generator": "看板指令",
        "solution_generator": "方案生成",
    }

    # 确认项类别 → 需要重跑的起始Agent映射
    # 规则：不管改哪个确认项，方案生成Agent始终要重跑
    CATEGORY_TO_START_AGENT = {
        "指标口径": "semantic_model",
        "SQL逻辑": "semantic_model",
        "JOIN方式": "semantic_model",
        "数据源": "semantic_model",
        "数据质量": "semantic_model",
        "维度粒度": "semantic_model",
        "过滤条件": "semantic_model",
        "图表类型": "instruction_generator",
        "布局": "instruction_generator",
        "交互": "instruction_generator",
        "维度选择": "instruction_generator",
        "其他": "semantic_model",  # 默认从语义模型开始
    }

    def __init__(self, llm: LLMClient = None, on_progress=None, run_mode: RunMode = RunMode.PLAN, model_config: dict = None):
        """
        Args:
            llm: 大模型客户端，为 None 时自动初始化
            on_progress: 进度回调函数，签名 on_progress(event_type, data)
                event_type: step_start | step_complete | step_retry | pipeline_done | pipeline_error | bi_push_*
                data: dict，包含事件相关的详情
            run_mode: 运行模式，方案模式（PLAN）或推送模式（PUBLISH）
            model_config: 模型配置 dict，格式：
                {"model": "xxx", "api_key": "sk-xxx", "base_url": "https://..."}
                为 None 时，使用 llm 参数或自动从环境变量初始化
                优先级：llm > model_config > 环境变量
        """
        # LLM 客户端初始化优先级：llm 参数 > model_config > 环境变量
        if llm is not None:
            self.llm = llm
        elif model_config:
            self.llm = LLMClient(**model_config)
        else:
            self.llm = LLMClient()
        self.context = {}
        self.steps = []
        self._confirmation_items_buffer = []
        self._on_progress = on_progress
        self._run_mode = run_mode
        self._cancelled = False  # 取消标志
        self._model_config = model_config  # 保存 model_config，用于日志

    def cancel(self):
        """请求取消执行"""
        self._cancelled = True

    def _check_cancelled(self):
        """检查是否已取消，若已取消则抛出 InterruptedError"""
        if self._cancelled:
            raise InterruptedError("用户取消了执行")

    def _emit(self, event_type: str, data: dict):
        """触发进度回调"""
        if self._on_progress:
            try:
                self._on_progress(event_type, data)
            except Exception:
                pass  # 回调异常不影响主流程


    def run(self, user_input: dict) -> PipelineResult:
        """
        执行完整的看板生成流程

        Args:
            user_input: 人工输入的看板需求 JSON

        Returns:
            PipelineResult
        """
        pipeline_id = f"pipe_{int(time.time())}"
        start_time = time.time()  # ⏱️ 开始计时
        logger.info(f"启动 Pipeline: {pipeline_id}")

        self.context["user_input"] = user_input
        self._confirmation_items_buffer = []

        # 提取 data_platform_config 和 enable_sql_test 到 context
        # 优先级：user_input > config.json 默认值
        dp_config = user_input.get("data_platform_config", {})
        if not dp_config:
            # 尝试从 config.json 读取默认值
            try:
                import json
                config_path = os.path.join(os.path.dirname(__file__), "config.json")
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        dp_config = config.get("data_platform", {})
            except Exception:
                pass

        if dp_config:
            self.context["data_platform_config"] = dp_config

        # enable_sql_test：默认启用（有token时）
        enable_sql_test = user_input.get("enable_sql_test", True)
        self.context["enable_sql_test"] = enable_sql_test

        # 注入 sql_test 进度回调函数（供 SemanticModelAgent 调用）
        def _sql_test_callback(event_type: str, data: dict):
            self._emit(event_type, data)
        self.context["_sql_test_callback"] = _sql_test_callback

        for agent_name in PIPELINE_ORDER:
            # 取消检查点
            self._check_cancelled()

            # 推送 step_start 事件
            self._emit("step_start", {
                "agent_name": agent_name,
                "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                "step_index": PIPELINE_ORDER.index(agent_name),
                "total_steps": len(PIPELINE_ORDER),
            })

            step_start = time.time()  # ⏱️ Step开始计时
            step_result = self._run_step(agent_name)
            step_duration = int((time.time() - step_start) * 1000)  # ⏱️ Step耗时
            self.steps.append(step_result)

            # ⏱️ 打印Step耗时
            duration_s = step_duration / 1000
            logger.info(f"{self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name)} 耗时: {duration_s:.1f}s")

            if step_result.status == "failed":
                # 推送 pipeline_error 事件
                self._emit("pipeline_error", {
                    "agent_name": agent_name,
                    "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                    "error": step_result.error,
                    "completed_steps": len(self.steps),
                    "total_steps": len(PIPELINE_ORDER),
                })
                return PipelineResult(
                    pipeline_id=pipeline_id,
                    status="failed",
                    steps=self.steps,
                    error=step_result.error,
                )

            # 将输出写入 context
            context_key = f"{agent_name}_output"
            self.context[context_key] = step_result.output

            # 推送 step_complete 事件
            self._emit("step_complete", {
                "agent_name": agent_name,
                "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                "step_index": PIPELINE_ORDER.index(agent_name),
                "total_steps": len(PIPELINE_ORDER),
                "duration_ms": step_result.duration_ms,
                "retry_count": step_result.retry_count,
            })

            # 需求解析 Agent 执行后，做后置交叉校验
            if agent_name == "requirements_parser" and step_result.status == "completed":
                warnings = cross_validate_requirements(
                    step_result.output, user_input
                )
                if warnings:
                    logger.warning(f"交叉校验发现 {len(warnings)} 个警告：")
                    for w in warnings:
                        logger.warning(f"  - {w}")
                    # 将警告注入到语义模型 Agent 的 context
                    self.context["_cross_validate_warnings"] = warnings

        # 合并所有确认项
        all_confirms = self._merge_confirmation_items()

        # 获取最终方案文档
        solution_doc = ""
        html_doc = ""
        if self.context.get("solution_generator_output"):
            solution_doc = self.context["solution_generator_output"]

            # 渲染 HTML 报告
            try:
                dashboard_title = user_input.get("dashboard_meta", {}).get("title", "")
                html_doc = render_html_report(solution_doc, dashboard_title)
                logger.info(f"HTML 报告渲染完成")
            except Exception as e:
                logger.warning(f"HTML 报告渲染失败（不影响 Markdown 输出）: {e}")
                html_doc = ""

        # ⏱️ 计算总耗时
        total_duration_ms = int((time.time() - start_time) * 1000)
        total_duration_min = total_duration_ms / 60000
        step_durations = {s.agent_name: s.duration_ms for s in self.steps}

        logger.info(f"Pipeline 完成: {pipeline_id}")
        logger.info(f"总耗时: {total_duration_ms/1000:.1f}s ({total_duration_min:.1f}min)")

        # ⏱️ 打印每个Step的耗时和占比
        logger.info(f"耗时分析：")
        for step in self.steps:
            step_duration_s = step.duration_ms / 1000
            percentage = (step.duration_ms / total_duration_ms) * 100 if total_duration_ms > 0 else 0
            retry_info = f" (重试{step.retry_count}次)" if step.retry_count > 0 else ""
            logger.info(f"  - {self.AGENT_DISPLAY_NAMES.get(step.agent_name, step.agent_name)}: "
                  f"{step_duration_s:.1f}s ({percentage:.1f}%){retry_info}")

        # 推送 pipeline_done 事件
        self._emit("pipeline_done", {
            "pipeline_id": pipeline_id,
            "solution_document": solution_doc,
            "html_document": html_doc,
            "total_confirmation_items": len(all_confirms),
            "steps_summary": [
                {
                    "agent_name": s.agent_name,
                    "display_name": self.AGENT_DISPLAY_NAMES.get(s.agent_name, s.agent_name),
                    "status": s.status,
                    "duration_ms": s.duration_ms,
                    "retry_count": s.retry_count,
                }
                for s in self.steps
            ],
            "timing": {
                "total_duration_ms": total_duration_ms,
                "step_durations": step_durations,
            },
        })

        return PipelineResult(
            pipeline_id=pipeline_id,
            status="completed",
            solution_document=solution_doc,
            html_document=html_doc,
            steps=self.steps,
            all_confirmation_items=all_confirms,
            total_duration_ms=total_duration_ms,
            step_durations=step_durations,
        )

    def _run_step(self, agent_name: str) -> StepResult:
        """执行单个 Agent Step（含重试）"""
        step_id = f"{agent_name}_step"
        agent_class = AGENTS.get(agent_name)

        if not agent_class:
            return StepResult(
                step_id=step_id,
                agent_name=agent_name,
                status="failed",
                input={},
                output=None,
                error=f"未知的 Agent: {agent_name}",
            )

        agent = agent_class(self.llm)
        last_error = ""

        for attempt in range(1, self.MAX_RETRY + 1):
            # 取消检查点（每次重试前检查）
            self._check_cancelled()

            try:
                start_time = time.time()

                output = agent.run(self.context)

                duration = int((time.time() - start_time) * 1000)

                # 收集确认项
                self._collect_confirmation_items(agent_name, output)

                return StepResult(
                    step_id=step_id,
                    agent_name=agent_name,
                    status="completed",
                    input=self.context,
                    output=output,
                    duration_ms=duration,
                    retry_count=attempt - 1,
                )

            except ValueError as e:
                last_error = str(e)
                logger.warning(f"第 {attempt} 次尝试失败: {e}")
                # 推送重试事件
                self._emit("step_retry", {
                    "agent_name": agent_name,
                    "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                    "attempt": attempt,
                    "max_retry": self.MAX_RETRY,
                    "error": str(e),
                })
                if attempt < self.MAX_RETRY:
                    logger.info(f"重试中... ({attempt}/{self.MAX_RETRY})")
                    # 重试时在 context 中追加错误提示
                    self.context[f"_retry_hint_{agent_name}"] = f"上次输出校验失败：{e}"
                else:
                    logger.error(f"已达最大重试次数，放弃")

            except Exception as e:
                last_error = str(e)
                logger.error(f"未预期的错误: {e}")
                logger.debug(f"完整错误信息：{traceback.format_exc()}")
                self._emit("step_retry", {
                    "agent_name": agent_name,
                    "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                    "attempt": attempt,
                    "max_retry": self.MAX_RETRY,
                    "error": str(e),
                    "traceback": traceback.format_exc(),  # 也把traceback传给前端
                })
                if attempt < self.MAX_RETRY:
                    logger.info(f"重试中... ({attempt}/{self.MAX_RETRY})")
                    self.context[f"_retry_hint_{agent_name}"] = f"上次执行异常：{e}"
                else:
                    logger.error(f"已达最大重试次数，放弃")

        return StepResult(
            step_id=step_id,
            agent_name=agent_name,
            status="failed",
            input={},
            output=None,
            error=last_error,
        )

    def _collect_confirmation_items(self, agent_name: str, output) -> None:
        """从 Agent 输出中收集确认项"""
        if not isinstance(output, dict):
            return

        items = []

        # 继承的确认项
        inherited = output.get("inherit_confirmation_items", [])
        items.extend(inherited)

        # 新增的确认项
        new_items = output.get("new_confirmation_items", [])
        items.extend(new_items)

        # 需求解析 Agent 的 confirmation_items
        if "confirmation_items" in output:
            items.extend(output["confirmation_items"])

        for item in items:
            if isinstance(item, dict) and "item" in item:
                item["_source_agent"] = agent_name
                self._confirmation_items_buffer.append(item)


    def _merge_confirmation_items(self) -> list:
        """合并去重所有确认项"""
        seen = set()
        unique_items = []

        for item in self._confirmation_items_buffer:
            key = f"{item.get('category', '')}:{item.get('item', '')}"
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        # 按风险排序：指标口径 > JOIN方式 > 数据质量 > 过滤条件 > 图表类型 > 其他
        risk_order = {
            "指标口径": 0,
            "SQL逻辑": 1,
            "JOIN方式": 2,
            "数据源": 3,
            "数据质量": 4,
            "维度粒度": 5,
            "过滤条件": 6,
            "图表类型": 7,
            "布局": 8,
            "交互": 9,
            "维度选择": 10,
            "其他": 99,
        }

        unique_items.sort(
            key=lambda x: risk_order.get(x.get("category", "其他"), 99)
        )

        return unique_items

    @staticmethod
    def get_start_agent_for_category(category: str) -> str:
        """根据确认项类别判断应从哪个Agent开始重跑"""
        return Pipeline.CATEGORY_TO_START_AGENT.get(category, "semantic_model")

    def run_from_step(
        self,
        start_agent: str,
        context: dict,
        revision_context: dict = None,
        run_mode: RunMode = RunMode.PLAN,
    ) -> PipelineResult:
        """
        从指定步骤开始执行 Pipeline（局部重新生成）

        Args:
            start_agent: 从哪个Agent开始重跑（含该Agent本身）
            context: 包含前序Agent输出的上下文
                     必须包含：user_input + start_agent之前的所有 *_output
            revision_context: 修改意见，结构：
                {
                    "reason": "用户修改意见摘要",
                    "confirmation_item": {"index": 1, "item": "...", "category": "指标口径"},
                    "user_feedback": "GMV应包含退款"
                }
            run_mode: 运行模式，方案模式（PLAN）或推送模式（PUBLISH）

        Returns:
            PipelineResult
        """
        self._run_mode = run_mode
        pipeline_id = f"pipe_{int(time.time())}_rev"
        start_time = time.time()
        logger.info(f"启动局部重新生成: {pipeline_id}")
        logger.info(f"从 {start_agent} 开始，模式: {run_mode.value}")

        # 注入修改意见到context
        if revision_context:
            context["_revision_context"] = revision_context
            logger.debug(f"修改意见: {revision_context.get('user_feedback', '')}")

        self.context = context
        self._confirmation_items_buffer = []

        # 确定起始Agent在PIPELINE_ORDER中的索引
        if start_agent not in PIPELINE_ORDER:
            return PipelineResult(
                pipeline_id=pipeline_id,
                status="failed",
                error=f"未知的 Agent: {start_agent}",
            )

        start_idx = PIPELINE_ORDER.index(start_agent)

        # 从起始Agent开始执行
        for agent_name in PIPELINE_ORDER[start_idx:]:
            # 取消检查点
            self._check_cancelled()

            self._emit("step_start", {
                "agent_name": agent_name,
                "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                "step_index": PIPELINE_ORDER.index(agent_name),
                "total_steps": len(PIPELINE_ORDER),
                "is_revision": True,
            })

            step_result = self._run_step(agent_name)
            self.steps.append(step_result)

            if step_result.status == "failed":
                self._emit("pipeline_error", {
                    "agent_name": agent_name,
                    "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                    "error": step_result.error,
                    "completed_steps": len(self.steps),
                    "total_steps": len(PIPELINE_ORDER),
                })
                return PipelineResult(
                    pipeline_id=pipeline_id,
                    status="failed",
                    steps=self.steps,
                    error=step_result.error,
                )

            context_key = f"{agent_name}_output"
            self.context[context_key] = step_result.output

            self._emit("step_complete", {
                "agent_name": agent_name,
                "display_name": self.AGENT_DISPLAY_NAMES.get(agent_name, agent_name),
                "step_index": PIPELINE_ORDER.index(agent_name),
                "total_steps": len(PIPELINE_ORDER),
                "duration_ms": step_result.duration_ms,
                "retry_count": step_result.retry_count,
                "is_revision": True,
            })

            # 需求解析 Agent 执行后，做后置交叉校验
            if agent_name == "requirements_parser" and step_result.status == "completed":
                warnings = cross_validate_requirements(
                    step_result.output, self.context.get("user_input", {})
                )
                if warnings:
                    logger.warning(f"交叉校验发现 {len(warnings)} 个警告：")
                    for w in warnings:
                        logger.warning(f"  - {w}")
                    self.context["_cross_validate_warnings"] = warnings

        # 合并所有确认项
        all_confirms = self._merge_confirmation_items()

        # 获取最终方案文档
        solution_doc = ""
        html_doc = ""
        if self.context.get("solution_generator_output"):
            solution_doc = self.context["solution_generator_output"]

            try:
                dashboard_title = self.context.get("user_input", {}).get(
                    "dashboard_meta", {}
                ).get("title", "")
                html_doc = render_html_report(solution_doc, dashboard_title)
                logger.info(f"HTML 报告渲染完成")
            except Exception as e:
                logger.warning(f"HTML 报告渲染失败（不影响 Markdown 输出）: {e}")
                html_doc = ""

        # 计算耗时
        total_duration_ms = int((time.time() - start_time) * 1000)
        step_durations = {s.agent_name: s.duration_ms for s in self.steps}

        logger.info(f"局部重新生成完成: {pipeline_id}")

        self._emit("pipeline_done", {
            "pipeline_id": pipeline_id,
            "solution_document": solution_doc,
            "html_document": html_doc,
            "total_confirmation_items": len(all_confirms),
            "is_revision": True,
            "steps_summary": [
                {
                    "agent_name": s.agent_name,
                    "display_name": self.AGENT_DISPLAY_NAMES.get(s.agent_name, s.agent_name),
                    "status": s.status,
                    "duration_ms": s.duration_ms,
                    "retry_count": s.retry_count,
                }
                for s in self.steps
            ],
            "timing": {
                "total_duration_ms": total_duration_ms,
                "step_durations": step_durations,
            },
        })

        return PipelineResult(
            pipeline_id=pipeline_id,
            status="completed",
            solution_document=solution_doc,
            html_document=html_doc,
            steps=self.steps,
            all_confirmation_items=all_confirms,
            total_duration_ms=total_duration_ms,
            step_durations=step_durations,
        )
