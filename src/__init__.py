"""
看板开发 Agent 核心模块

包含：
- llm: LLM 调用封装
- pipeline: 编排引擎
- agents: Agent 模块
- renderer: HTML 渲染
- bi_api: BI 平台 API
- data_platform_api: 数据平台 API
"""

from .llm import LLMClient
from .pipeline import Pipeline
from .agents import (
    RequirementsParserAgent,
    SemanticModelAgent,
    BIPushAgent,
    ChartDesignAgent,
    InstructionGeneratorAgent,
    SolutionGeneratorAgent,
    RunMode,
)

__version__ = "1.0.0"
