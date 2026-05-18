"""
自然语言 → 结构化JSON 转换层

让用户可以用自然语言描述需求，无需手写 JSON 输入文件。
转换后的 JSON 直接喂给现有 Pipeline。

用法：
    # 方式1：直接输入自然语言
    python run_pipeline.py --natural-input "帮我做一个用户行为分析看板，数据源是iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"

    # 方式2：从文件读取自然语言
    python run_pipeline.py --natural-input-file input.txt --output ./output
"""

import os
import json
import re
import time
import argparse
import sys
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional

import httpx

# 添加skill目录到Python路径
SKILL_DIR = Path(__file__).parent
SKILL_ROOT = SKILL_DIR.parent

# 确定工作空间目录
_default_workspace = str(Path.home() / "WorkBuddy" / "20260427134240")
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", _default_workspace))

# 尝试从工作空间加载依赖模块
sys.path.insert(0, str(WORKSPACE_DIR))

try:
    from src.data_platform_api import DataPlatformClient
except ImportError as e:
    print(f"[WARN] 无法导入 data_platform_api: {e}")
    DataPlatformClient = None

# Logger
logger = None


def _init_logger():
    """延迟初始化 logger（避免导入顺序问题）"""
    global logger
    if logger is not None:
        return
    try:
        sys.path.insert(0, str(SKILL_ROOT))
        from utils.logging_config import get_logger, setup_logging
        setup_logging()
        logger = get_logger(__name__)
    except Exception:
        import logging
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logger = logging.getLogger(__name__)


def load_config():
    """加载配置文件"""
    config_path = SKILL_DIR / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class NLConverter:
    """
    自然语言转结构化JSON转换器

    职责：
    1. 从自然语言提取 dashboard_meta（title/audience/goal）
    2. 提取数据源表名
    3. 自动调用 describe_table 获取字段信息
    4. 基于表名、字段名、业务常识推断 metrics_requirement 和 dimensions_requirement
    5. 所有推断内容标记为 need_confirm，生成 confirmation_items
    6. 输出符合现有规范的JSON，直接传给 Pipeline
    """

    def __init__(
        self,
        llm_config: Dict[str, Any],
        dp_config: Dict[str, Any]
    ):
        """
        初始化转换器

        Args:
            llm_config: LLM配置（model/api_key/base_url）
            dp_config: 数据平台配置（base_url/token/catalog/schema/engine）
        """
        self.llm_config = llm_config
        self.dp_config = dp_config
        self.llm_client = None
        self.dp_client = None

        # 初始化LLM客户端
        self._init_llm()

        # 初始化数据平台客户端
        self._init_data_platform()

    def _init_llm(self):
        """初始化LLM客户端"""
        try:
            import openai
            self.llm_client = openai.OpenAI(
                api_key=self.llm_config.get("api_key"),
                base_url=self.llm_config.get("base_url"),
                timeout=httpx.Timeout(300.0, connect=10.0),  # 读超时5分钟，连接超时10秒
            )
            self.model = self.llm_config.get("model", "deepseek-ai/DeepSeek-V4-Flash")
            self.temperature = self.llm_config.get("temperature", 0.1)
        except ImportError:
            print("[WARN] openai 包未安装，将使用模拟模式")
            self.llm_client = None

    def _init_data_platform(self):
        """初始化数据平台客户端"""
        if DataPlatformClient is None:
            print("[WARN] DataPlatformClient 不可用，跳过字段自动获取")
            return

        base_url = self.dp_config.get("base_url")
        token = self.dp_config.get("token")

        if not base_url or not token:
            print("[WARN] 数据平台配置不完整，跳过字段自动获取")
            return

        try:
            self.dp_client = DataPlatformClient(
                base_url=base_url,
                token=token,
                catalog=self.dp_config.get("catalog"),
                schema=self.dp_config.get("schema"),
                engine=self.dp_config.get("engine", "Spark")
            )
        except Exception as e:
            print(f"[WARN] 数据平台客户端初始化失败: {e}")
            self.dp_client = None

    def _llm_chat(self, prompt: str, temperature: float = 0.1) -> str:
        """
        调用 LLM，统一封装超时+重试逻辑

        - 把 HTTP 请求放在独立线程中执行，支持 Ctrl+C 中断
        - 每次调用有独立超时（读超时 5 分钟），超时后自动重试
        - 最多重试 3 次，渐进等待 10s/20s/30s
        - Ctrl+C 随时可终止

        Args:
            prompt: 用户 prompt（不含 system role）
            temperature: 温度参数

        Returns:
            模型返回的文本内容

        Raises:
            Exception: 重试耗尽后仍失败则抛出
            KeyboardInterrupt: 用户按 Ctrl+C 时抛出
        """
        if self.llm_client is None:
            raise RuntimeError("LLM 客户端未初始化")

        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                return self._llm_chat_once(prompt, temperature)
            except KeyboardInterrupt:
                _init_logger()
                logger.warning("  ⛔ 用户中断，退出")
                raise
            except Exception as e:
                err_name = type(e).__name__
                is_network_error = any(
                    kw in err_name.lower()
                    for kw in ["timeout", "connection", "network", "connect", "read"]
                )
                if is_network_error and attempt < max_retries:
                    wait = attempt * 10
                    _init_logger()
                    logger.warning(
                        f"  ⚠️ LLM 调用网络错误({err_name})，{wait}s 后重试 ({attempt}/{max_retries})，"
                        f"随时可按 Ctrl+C 终止..."
                    )
                    # 可中断的 sleep：每 1 秒检查一次中断标志
                    for _ in range(wait):
                        time.sleep(1)
                else:
                    raise

    def _llm_chat_once(self, prompt: str, temperature: float) -> str:
        """
        单次 LLM 调用，运行在独立线程中，支持 Ctrl+C 中断。
        读超时 5 分钟，超时后抛出 TimeoutError。
        """
        result_container = {}
        exc_container = {}

        def _call():
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                )
                result_container["content"] = response.choices[0].message.content.strip()
            except Exception as e:
                exc_container["exc"] = e

        thread = threading.Thread(target=_call, daemon=True)
        thread.start()

        # 等待线程完成，最多等 5 分钟（读超时）
        thread.join(timeout=300)

        if thread.is_alive():
            # 线程还在跑（读超时），强制结束
            _init_logger()
            logger.warning("  ⏱️ LLM 调用读超时（5分钟），视为网络错误")
            raise TimeoutError("LLM 调用读超时（5分钟）")

        if exc_container:
            raise exc_container["exc"]

        return result_container["content"]

    def convert(self, natural_language: str) -> Dict[str, Any]:
        """
        将自然语言转换为结构化JSON

        Args:
            natural_language: 用户的自然语言描述

        Returns:
            符合现有输入规范的结构化JSON
        """
        _init_logger()
        logger.info("开始转换自然语言输入...")
        logger.debug(f"  输入: {natural_language[:100]}...")

        # Step 1: 使用LLM从自然语言中提取基本信息
        logger.info("[Step 1/5] 提取看板元信息...")
        meta_info = self._extract_meta_info(natural_language)

        # Step 2: 提取数据源表名
        logger.info("[Step 2/5] 提取数据源表名...")
        table_names = self._extract_table_names(natural_language, meta_info)

        # Step 3: 获取表字段信息
        logger.info("[Step 3/5] 获取表字段信息...")
        data_sources = self._fetch_table_info(table_names, natural_language)

        # Step 3.5: 推断多表关联关系（仅 >= 2 张表时）
        join_hints = []
        join_confirmations = []
        if len(data_sources) >= 2:
            logger.info("[Step 3.5/5] 推断多表关联关系...")
            join_hints, join_confirmations = self._infer_join_hints(
                data_sources, natural_language, meta_info
            )
        else:
            logger.debug("[Step 3.5/5] 单表场景，跳过关联推断")

        # Step 4: 推断指标和维度
        logger.info("[Step 4/5] 推断指标和维度...")
        metrics, dimensions, confirmation_items = self._infer_metrics_and_dimensions(
            natural_language, meta_info, data_sources
        )

        # 合并关联推断的确认项
        confirmation_items.extend(join_confirmations)

        # 构建最终输出
        result = self._build_output(
            meta_info, data_sources, metrics, dimensions, confirmation_items,
            join_hints=join_hints
        )

        # 检测自然语言中的模式关键词
        mode_hint = self._detect_mode_hint(natural_language)
        if mode_hint:
            result["_mode_hint"] = mode_hint
            logger.debug(f"  [MODE] 检测到模式关键词: {mode_hint}")

        # 检测自然语言中的 SQL 校验关键词
        sql_test_hint = self._detect_sql_test_hint(natural_language)
        if sql_test_hint is not None:
            result["_sql_test_hint"] = sql_test_hint
            logger.debug(f"  [SQL_TEST] 检测到SQL校验关键词: enable={sql_test_hint}")

        logger.info("[NLConverter] 转换完成!")
        logger.info(f"  看板标题: {result['dashboard_meta']['title']}")
        logger.info(f"  数据源: {len(result['data_sources'])} 张表, 关联关系: {len(join_hints)} 组")
        logger.info(f"  指标: {len(result['metrics_requirement'])} 个, 维度: {len(result['dimensions_requirement'])} 个")
        logger.info(f"  确认项: {len(result.get('confirmation_items', []))} 项")

        return result

    def _detect_mode_hint(self, text: str) -> Optional[str]:
        """
        检测自然语言中的运行模式关键词

        识别两种意图：
            - publish：要把方案推送到 BI 平台
            - plan：只生成方案文档，不推送

        匹配优先级：disable → plan 优先（避免"不要推送"被误判为 publish）

        Returns:
            "publish" / "plan" / None
        """
        text_lower = text.lower()

        # 推送动作词（中英文）
        push_verb = r"(?:推送|发布|上传|上线|publish|push|deploy)"
        # 推送对象（用于句中模式，避免"推送失败"被误识别）
        push_target = r"(?:bi|平台|看板|dashboard|空间)"
        # 前缀和动词之间允许 0-5 个非标点字（排除标点防止跨子句串联）
        glue = r"(?:[^，。！？；,.!?;]{0,5})?"

        # ============ disable → plan ============
        # 1. 否定前缀 + 推送动作（"不要推送"、"别发布"、"跳过推送"）
        if re.search(
            rf"(?:不|不要|不需|不需要|不用|别|无需|跳过){glue}{push_verb}",
            text_lower,
        ):
            return "plan"
        # 2. 明确的 plan 关键词
        if re.search(
            r"仅方案|只方案|只生成方案|仅生成方案|方案模式|\bplan\b",
            text_lower,
        ):
            return "plan"

        # ============ enable → publish ============
        # 0. 明确的 publish 关键词（与 plan 的"方案模式"对称,优先匹配）
        if re.search(r"推送模式|发布模式|publish\s*mode", text_lower):
            return "publish"
        # 1. 肯定前缀 + 推送动作（"要推送"、"请发布"）
        if re.search(
            rf"(?:要|需要|开启|启用|打开|请|麻烦){glue}{push_verb}",
            text_lower,
        ):
            return "publish"
        # 2. 推送动作 + 目标（"推送到 BI"、"发布看板"）—— 比裸"推送失败"更精确
        if re.search(
            rf"{push_verb}\s*(?:到|至|去|向)?\s*{push_target}",
            text_lower,
        ):
            return "publish"
        # 3. 英文 publish 单词
        if re.search(r"\bpublish\b", text_lower):
            return "publish"

        return None

    def _detect_sql_test_hint(self, text: str) -> Optional[bool]:
        """
        检测自然语言中是否明确要求开启 / 关闭 SQL 校验

        说明：在本项目语境下，"SQL 校验"和"语义模型校验"是同一件事
        （语义模型 Agent 内部会调度 SQL 试跑）。两种说法都被识别：
            - "要校验 SQL" / "要校验语义模型"          → True
            - "不校验 SQL" / "跳过语义模型校验"        → False
            - "校验语义模型" / "语义模型校验"          → True
            - "不要语义模型校验"                       → False

        匹配优先级：disable（否定）> enable（肯定），避免"不要校验"被误判为"校验"。

        Returns:
            True  - 用户明确要求开启
            False - 用户明确要求关闭
            None  - 未检测到，由配置决定
        """
        text_lower = text.lower()

        # 校验"对象"（可选）：sql / 语义模型 / 语义 / model
        target = r"(?:sql|语义模型|语义|model)"
        # 校验"动作"：必须出现完整的动词词
        verb = r"(?:校验|验证|试跑|测试)"
        # 前缀和动词之间允许 0-5 个非标点字（排除标点防止跨子句串联：
        # "不要推送，要校验"不应让"不要"+"，要校"被识别为否定校验）
        glue = r"(?:[^，。！？；,.!?;]{0,5})?"

        disable_pattern = re.compile(
            rf"(?:不|不要|不需|不需要|不用|别|无需|跳过)"
            rf"{glue}(?:{target})?\s*{verb}"
        )
        enable_pattern = re.compile(
            rf"(?:要|需要|开启|启用|打开|请|麻烦)"
            rf"{glue}(?:{target})?\s*{verb}"
        )
        # 句首裸命令式："校验语义模型" / "语义模型校验" / "校验 SQL"
        direct_enable_pattern = re.compile(
            rf"^\s*(?:{verb}\s*{target}|{target}\s*{verb})"
        )
        # 序列描述：用户用"先 X 再 Y" / "X 后再 Y" / "X 成功后..." 等连接词描述意图
        # 例："语义模型校验成功后再推送"、"先校验 SQL"、"校验通过后..."
        sequence_enable_pattern = re.compile(
            # ① "先 + (target?) + verb"：先校验 / 先做 SQL 校验
            rf"先\s*(?:{target}\s*)?{verb}|"
            # ② "(target?) + verb + (成功/通过/完成/结束)? + (之?后|再)"：
            #    校验后再... / 语义模型校验成功后... / 校验完成再...
            rf"(?:{target}\s*)?{verb}\s*(?:成功|通过|完成|结束)?\s*(?:之?后|再)"
        )

        # disable 优先（"不要校验"必须先于"校验"匹配）
        if disable_pattern.search(text_lower):
            return False
        if enable_pattern.search(text_lower):
            return True
        if direct_enable_pattern.search(text_lower):
            return True
        if sequence_enable_pattern.search(text_lower):
            return True

        # 英文兜底
        if re.search(r"no\s*sql\s*test|skip\s*sql", text_lower):
            return False
        if re.search(r"validate\s*sql|test\s*sql", text_lower):
            return True

        return None

    def _extract_meta_info(self, text: str) -> Dict[str, Any]:
        """
        使用LLM从自然语言中提取看板元信息

        Returns:
            {
                "title": "看板标题",
                "audience": "目标受众（推断）",
                "goal": "看板目标（推断）",
                "dashboard_type": "看板类型（推断，如：用户行为分析、销售分析等）"
            }
        """
        if self.llm_client is None:
            # 模拟模式：简单规则提取
            return self._extract_meta_info_fallback(text)

        prompt = f"""你是一位数据分析专家，需要从用户的自然语言描述中提取看板元信息。

用户输入：
{text}

请提取以下信息（以JSON格式输出，不要附加任何解释）：
{{
  "title": "看板标题（从用户输入中提取或生成，要简洁准确）",
  "audience": "目标受众（如：产品经理、运营团队、数据分析师等，如果用户输入未提及则根据看板内容推断）",
  "goal": "看板目标（一句话描述这个看板要解决什么问题，如果用户输入未提及则根据看板内容推断）"
}}

注意：
- title 要简洁，不超过20个字
- audience 和 goal 如果无法准确推断，可以填写"待确认"
- 只输出JSON，不要输出其他内容"""

        try:
            content = self._llm_chat(prompt)
            # 提取JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
            else:
                raise ValueError("LLM返回内容无法解析为JSON")

        except Exception as e:
            logger.warning(f"LLM提取元信息失败: {e}，使用规则提取")
            return self._extract_meta_info_fallback(text)

    def _extract_meta_info_fallback(self, text: str) -> Dict[str, Any]:
        """规则提取元信息（备用）"""
        # 尝试从文本中提取标题
        title_match = re.search(r'(.+?)(看板|仪表盘|dashboard)', text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip() + "看板"
        else:
            title = "数据分析看板"

        return {
            "title": title,
            "audience": "待确认",
            "goal": "待确认"
        }

    def _extract_table_names(self, text: str, meta_info: Dict[str, Any]) -> List[str]:
        """
        从自然语言中提取数据源表名

        支持多种格式：
        - 完整三级表名：iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view
        - 两级表名：meta.dwd_user_module_page_view
        - 用引号包裹的表名："dwd_user_module_page_view"
        """
        table_names = []

        # 模式1：完整三级表名（catalog.schema.table）
        pattern_full = r'([a-z0-9_]+)\.([a-z0-9_]+)\.([a-z0-9_]+)'
        matches = re.findall(pattern_full, text)
        for match in matches:
            full_name = f"{match[0]}.{match[1]}.{match[2]}"
            if full_name not in table_names:
                table_names.append(full_name)

        # 模式2：两级表名（schema.table）
        if not table_names:
            pattern_two = r'([a-z0-9_]+)\.([a-z0-9_]+)'
            matches = re.findall(pattern_two, text)
            for match in matches:
                full_name = f"{meta_info.get('catalog', 'iceberg_zjyprc_hadoop')}.{match[0]}.{match[1]}"
                if full_name not in table_names:
                    table_names.append(full_name)

        # 模式3：引号包裹的表名
        if not table_names:
            pattern_quoted = r'[\'"`]([a-z0-9_]+)[\'"`]'
            matches = re.findall(pattern_quoted, text)
            for table_name in matches:
                # 假设是完整表名的一部分
                if '.' not in table_name:
                    full_name = f"{meta_info.get('catalog', 'iceberg_zjyprc_hadoop')}.{meta_info.get('schema', 'meta')}.{table_name}"
                    if full_name not in table_names:
                        table_names.append(full_name)

        logger.debug(f"  提取到 {len(table_names)} 张表: {table_names}")
        return table_names

    def _fetch_table_info(self, table_names: List[str], user_input: str) -> List[Dict[str, Any]]:
        """
        获取表的字段信息

        Args:
            table_names: 表名列表
            user_input: 原始用户输入（用于推断表用途）

        Returns:
            data_sources 列表，每项包含 table_name, description, key_fields, field_descriptions
        """
        # 延迟 import：和文件顶部 `from src.data_platform_api import DataPlatformClient`
        # 保持同款路径前缀（带 src.）。早前曾误写成 `from data_platform_api import ...` 导致
        # ImportError 被吞 → 永远走 LLM 脑补 fallback，fail-fast 机制失效。
        try:
            from src.data_platform_api import TableNotFoundError
        except ImportError as _e:  # pragma: no cover - 兜底，正常路径不会走到
            print(f"[WARN] 无法 import TableNotFoundError，fail-fast 失效: {_e}")
            TableNotFoundError = None  # type: ignore[assignment]

        data_sources = []
        invalid_tables: list[str] = []  # 收集所有"表不存在"的输入，循环结束后一并报错

        for table_name in table_names:
            logger.info(f"  正在获取表 {table_name} 的字段信息...")

            data_source = {
                "table_name": table_name,
                "description": "",
                "table_type": "fact",  # 默认事实表
                "key_fields": [],
                "field_mappings": {},
                "field_descriptions": {}
            }

            # 尝试从数据平台获取字段信息
            if self.dp_client:
                try:
                    columns = self.dp_client.describe_table(table_name)
                    logger.info(f"    获取到 {len(columns)} 个字段")

                    # 提取字段名和类型
                    key_fields = []
                    field_descriptions = {}

                    for col in columns:
                        col_name = col.get("column_name", "")
                        col_type = col.get("data_type", "")
                        col_comment = col.get("comment", "")

                        key_fields.append(col_name)

                        # 构建字段描述
                        desc = f"{col_type}"
                        if col_comment:
                            desc += f" - {col_comment}"
                        field_descriptions[col_name] = desc

                    data_source["key_fields"] = key_fields
                    data_source["field_descriptions"] = field_descriptions

                except Exception as e:
                    # 表不存在 → 记下来，**不要走 LLM 脑补**
                    # （之前的 fallback 会让 LLM 凭空编字段，用户全程不知道，
                    #  最终走完 5 分钟 pipeline 才在 SQL 试跑阶段报错。）
                    if TableNotFoundError is not None and isinstance(e, TableNotFoundError):
                        logger.warning(f"  表 {table_name} 不存在")
                        invalid_tables.append(table_name)
                        continue
                    logger.warning(f"获取字段信息失败: {e}")
                    # 其他失败（权限 / 网络等）保留旧行为：LLM 推断
                    data_source = self._infer_table_info_with_llm(data_source, user_input)
            else:
                # 无数据平台客户端，使用LLM推断
                data_source = self._infer_table_info_with_llm(data_source, user_input)

            # 推断表用途和类型
            data_source["description"] = self._infer_table_description(table_name, user_input)
            data_source["table_type"] = self._infer_table_type(table_name)

            data_sources.append(data_source)

        # 有任何不存在的表就 fail-fast，让飞书层立刻把准确的错误回给用户
        if invalid_tables and TableNotFoundError is not None:
            raise TableNotFoundError(
                ", ".join(invalid_tables),
                f"Table or view not found: {', '.join(invalid_tables)}",
            )

        return data_sources

    def _infer_join_hints(
        self,
        data_sources: List[Dict[str, Any]],
        user_input: str,
        meta_info: Dict[str, Any]
    ) -> tuple:
        """
        使用 LLM 推断多表之间的 JOIN 关系

        Args:
            data_sources: 已获取字段信息的数据源列表
            user_input: 原始用户输入
            meta_info: 看板元信息

        Returns:
            (join_hints, confirmation_items)
            join_hints 格式: [{left_table, right_table, join_on, join_type, notes}]
        """
        join_hints = []
        extra_confirmations = []

        if self.llm_client is None:
            # 无 LLM 时跳过推断
            logger.debug("  [INFO] LLM 不可用，跳过 JOIN 关系推断")
            return join_hints, extra_confirmations

        # 构建每张表的字段信息摘要
        tables_info = []
        for ds in data_sources:
            table_info = {
                "table_name": ds["table_name"],
                "table_type": ds.get("table_type", "fact"),
                "description": ds.get("description", ""),
                "key_fields": ds.get("key_fields", []),
                "field_descriptions": ds.get("field_descriptions", {})
            }
            # 只取前 30 个字段避免 prompt 过长
            if len(table_info["key_fields"]) > 30:
                table_info["key_fields"] = table_info["key_fields"][:30]
                table_info["field_descriptions"] = {
                    k: v for k, v in list(table_info["field_descriptions"].items())[:30]
                }
            tables_info.append(table_info)

        tables_json = json.dumps(tables_info, ensure_ascii=False, indent=2)

        prompt = f"""你是一位数据分析专家，需要根据多张表的字段信息，推断表之间的 JOIN（关联）关系。

用户需求：{user_input}
看板标题：{meta_info.get('title', '数据分析看板')}

表信息：
{tables_json}

请推断这些表之间如何关联（以JSON格式输出，不要附加任何解释）：
{{
  "join_hints": [
    {{
      "left_table": "完整表名（作为主表/左表）",
      "right_table": "完整表名（作为关联表/右表）",
      "join_on": "关联字段，如 user_id = user_id 或 a.user_id = b.user_id",
      "join_type": "LEFT JOIN 或 INNER JOIN",
      "notes": "简要说明为什么这样关联"
    }}
  ],
  "unjoinable_tables": ["无法确定关联关系的表名（如有）"]
}}

推断规则：
1. 优先通过同名字段（尤其是 id 类字段如 user_id, order_id, device_id）推断关联关系
2. 主表（fact 表）放左边，维度表（dim 表）放右边
3. 事实表与维度表：默认使用 LEFT JOIN
4. 事实表与事实表：默认使用 INNER JOIN
5. 如果两张表之间没有明显的关联字段，不要强行关联，放入 unjoinable_tables
6. join_on 字段优先使用精确的字段名匹配，如 "user_id = user_id"
7. 只输出 JSON，不要输出其他内容"""

        try:
            content = self._llm_chat(prompt)

            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                join_hints = result.get("join_hints", [])
                unjoinable = result.get("unjoinable_tables", [])

                # 过滤：确保表名在 data_sources 中存在
                valid_tables = {ds["table_name"] for ds in data_sources}
                filtered_hints = []
                for hint in join_hints:
                    lt = hint.get("left_table", "")
                    rt = hint.get("right_table", "")
                    if lt in valid_tables and rt in valid_tables:
                        filtered_hints.append(hint)

                join_hints = filtered_hints

                if join_hints:
                    logger.info(f"  推断到 {len(join_hints)} 组关联关系")
                    for h in join_hints:
                        logger.debug(f"    - {h['left_table']} --{h.get('join_type', 'JOIN')}--> {h['right_table']} ON {h.get('join_on', '?')}")

                if unjoinable:
                    logger.warning(f"  {len(unjoinable)} 张表无法确定关联关系: {unjoinable}")
                    extra_confirmations.append({
                        "category": "数据源",
                        "item": f"以下表之间未发现明显关联字段，可能需要手动确认关联关系：{', '.join(unjoinable)}",
                        "risk_if_wrong": "未关联的表数据将独立分析，无法实现跨表联合查询",
                        "suggested_value": "请确认这些表是否需要关联，以及关联条件"
                    })

                # 所有推断结果都加入确认项
                if join_hints:
                    relations_desc = "; ".join(
                        f"{h['left_table']} 与 {h['right_table']} 通过 {h.get('join_on', '?')} ({h.get('join_type', 'JOIN')})"
                        for h in join_hints
                    )
                    extra_confirmations.append({
                        "category": "数据源",
                        "item": f"表关联关系已自动推断：{relations_desc}",
                        "risk_if_wrong": "关联关系错误会导致数据重复或遗漏",
                        "suggested_value": "请确认关联字段和关联类型是否正确"
                    })

        except Exception as e:
            logger.warning(f"LLM 推断 JOIN 关系失败: {e}")

        return join_hints, extra_confirmations

    def _infer_table_info_with_llm(self, data_source: Dict, user_input: str) -> Dict:
        """使用LLM推断表的字段信息"""
        if self.llm_client is None:
            return data_source

        table_name = data_source["table_name"]

        prompt = f"""你是一位数据分析专家，需要根据表名和用户输入推断表的字段信息。

表名：{table_name}
用户输入：{user_input}

请推断该表可能包含的字段（以JSON格式输出，不要附加任何解释）：
{{
  "key_fields": ["字段1", "字段2", "字段3", ...],
  "field_descriptions": {{
    "字段1": "字段1的含义",
    "字段2": "字段2的含义",
    ...
  }}
}}

注意：
- key_fields 是表的主要字段列表
- field_descriptions 是字段的详细含义说明
- 根据表名推断常见字段即可，不需要完全准确
- 只输出JSON，不要输出其他内容"""

        try:
            content = self._llm_chat(prompt)
            # 提取JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                data_source["key_fields"] = result.get("key_fields", data_source["key_fields"])
                data_source["field_descriptions"] = result.get("field_descriptions", data_source["field_descriptions"])

        except Exception as e:
            logger.warning(f"LLM推断字段信息失败: {e}")

        return data_source

    def _infer_table_description(self, table_name: str, user_input: str) -> str:
        """推断表的用途描述"""
        # 从表名推断
        table_name_lower = table_name.lower()

        if "user" in table_name_lower and "page" in table_name_lower:
            return "用户页面访问行为表，记录用户每次页面访问"
        elif "user" in table_name_lower and "module" in table_name_lower:
            return "用户模块访问行为表，记录用户每次模块曝光和点击"
        elif "order" in table_name_lower:
            return "订单事实表"
        elif "user" in table_name_lower and "info" in table_name_lower:
            return "用户维度表"
        else:
            return f"数据源表 {table_name}"

    def _infer_table_type(self, table_name: str) -> str:
        """推断表的类型"""
        table_name_lower = table_name.lower()

        if "dim_" in table_name_lower or "_dim_" in table_name_lower:
            return "dimension"
        elif "fact_as_dim" in table_name_lower:
            return "fact_as_dimension"
        else:
            return "fact"

    def _infer_metrics_and_dimensions(
        self,
        user_input: str,
        meta_info: Dict[str, Any],
        data_sources: List[Dict[str, Any]]
    ) -> tuple:
        """
        使用LLM推断指标和维度

        Returns:
            (metrics, dimensions, confirmation_items)
        """
        if self.llm_client is None:
            # 模拟模式：返回常见指标和维度
            return self._infer_metrics_and_dimensions_fallback(meta_info, data_sources)

        # 构建字段信息描述
        fields_desc = []
        for ds in data_sources:
            fields_desc.append(f"表 {ds['table_name']} 的字段：{', '.join(ds['key_fields'][:20])}")

        prompt = f"""你是一位数据分析专家，需要根据用户的自然语言描述和表结构，推断需要分析的指标和维度。

用户输入：
{user_input}

看板信息：
- 标题：{meta_info['title']}
- 目标：{meta_info['goal']}

数据源字段信息：
{chr(10).join(fields_desc)}

请推断需要分析的指标和维度（以JSON格式输出，不要附加任何解释）：
{{
  "metrics": [
    {{
      "name": "指标名称",
      "description": "指标描述"
    }}
  ],
  "dimensions": [
    {{
      "name": "维度名称"
    }}
  ],
  "confirmation_items": [
    {{
      "category": "指标口径 | 维度粒度 | 数据源 | 其他",
      "item": "需要确认的具体内容",
      "risk_if_wrong": "如果搞错会有什么后果",
      "suggested_value": "建议的值或方向（可选）"
    }}
  ]
}}

注意：
- metrics 是根据用户输入和表字段推断的可能需要计算的指标
- dimensions 是根据表字段推断的可能的分析维度
- confirmation_items 是所有需要用户确认的内容（包括推断出的指标、维度、时间范围等）
- 指标示例：DAU、页面访问次数、会话数、转化率等
- 维度示例：日期、页面名称、模块名称、用户类型等
- 只输出JSON，不要输出其他内容"""

        try:
            content = self._llm_chat(prompt)
            # 提取JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                metrics = result.get("metrics", [])
                dimensions = result.get("dimensions", [])
                confirmation_items = result.get("confirmation_items", [])

                logger.info(f"  推断到 {len(metrics)} 个指标, {len(dimensions)} 个维度")
                return metrics, dimensions, confirmation_items

        except Exception as e:
            logger.warning(f"LLM推断指标维度失败: {e}")

        # 失败时使用备用方案
        return self._infer_metrics_and_dimensions_fallback(meta_info, data_sources)

    def _infer_metrics_and_dimensions_fallback(
        self,
        meta_info: Dict[str, Any],
        data_sources: List[Dict[str, Any]]
    ) -> tuple:
        """备用：基于规则推断指标和维度"""
        metrics = []
        dimensions = []
        confirmation_items = []

        # 根据看板类型推断常见指标
        title = meta_info.get("title", "")

        if "用户行为" in title or "用户分析" in title:
            metrics = [
                {"name": "DAU", "description": "日活跃用户数"},
                {"name": "页面访问次数", "description": "用户访问页面的总次数"},
                {"name": "会话数", "description": "用户会话总数"}
            ]
            dimensions = [
                {"name": "日期"},
                {"name": "页面名称"},
                {"name": "模块名称"}
            ]
            confirmation_items.append({
                "category": "指标口径",
                "item": "DAU的定义（去重uid？去重device_id？）",
                "risk_if_wrong": "口径不一致会导致数据不可比",
                "suggested_value": "建议按 uid 去重"
            })

        elif "销售" in title or "运营" in title:
            metrics = [
                {"name": "GMV", "description": "成交总额"},
                {"name": "订单数", "description": "订单总数"},
                {"name": "客单价", "description": "平均订单金额"}
            ]
            dimensions = [
                {"name": "日期"},
                {"name": "商品类目"}
            ]

        else:
            # 通用指标
            metrics = [
                {"name": "数据量", "description": "记录总数"}
            ]
            dimensions = [
                {"name": "日期"}
            ]

        # 添加通用确认项
        confirmation_items.append({
            "category": "其他",
            "item": "时间范围（默认最近30天？）",
            "risk_if_wrong": "时间范围不符合预期会影响分析结论",
            "suggested_value": "建议默认最近30天"
        })

        confirmation_items.append({
            "category": "数据源",
            "item": "表类型判断（事实表/维度表）",
            "risk_if_wrong": "表类型错误会导致JOIN逻辑错误",
            "suggested_value": "已根据表名自动推断，请确认"
        })

        return metrics, dimensions, confirmation_items

    def _build_output(
        self,
        meta_info: Dict[str, Any],
        data_sources: List[Dict[str, Any]],
        metrics: List[Dict],
        dimensions: List[Dict],
        confirmation_items: List[Dict],
        join_hints: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        构建最终的输出JSON

        符合现有输入规范：
        - dashboard_meta
        - data_sources
        - join_hints（多表关联关系，可选）
        - metrics_requirement
        - dimensions_requirement
        - filters_known
        - additional_notes
        """
        output = {
            "dashboard_meta": {
                "title": meta_info.get("title", "数据分析看板"),
                "audience": meta_info.get("audience", ""),
                "goal": meta_info.get("goal", "")
            },
            "data_sources": data_sources,
            "metrics_requirement": metrics,
            "dimensions_requirement": dimensions,
            "filters_known": [],
            "additional_notes": "由自然语言自动转换生成，请确认各项内容是否正确。",
            "confirmation_items": confirmation_items  # 额外添加确认项（Pipeline会处理）
        }

        # 多表时写入 join_hints
        if join_hints:
            output["join_hints"] = join_hints

        return output

    def save_output(self, output: Dict[str, Any], output_path: str):
        """保存转换结果到文件"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"转换结果已保存: {output_path}")


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="自然语言转结构化JSON")
    parser.add_argument("--input", "-i", help="自然语言输入文本")
    parser.add_argument("--input-file", "-f", help="从文件读取自然语言输入")
    parser.add_argument("--output", "-o", default="./output/nl_output.json", help="输出JSON文件路径")

    args = parser.parse_args()

    # 读取输入
    if args.input_file:
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"❌ 输入文件不存在: {input_path}")
            sys.exit(1)
        with open(input_path, "r", encoding="utf-8") as f:
            natural_language = f.read()
    elif args.input:
        natural_language = args.input
    else:
        print("❌ 请提供输入（--input 或 --input-file）")
        parser.print_help()
        sys.exit(1)

    # 加载配置
    config = load_config()
    llm_config = config.get("llm", {})
    dp_config = config.get("data_platform", {})

    # 创建转换器
    converter = NLConverter(llm_config, dp_config)

    # 执行转换
    result = converter.convert(natural_language)

    # 保存结果
    converter.save_output(result, args.output)

    print(f"\n✅ 转换完成！可以使用以下命令继续：")
    print(f"   python run_pipeline.py --input {args.output}")


if __name__ == "__main__":
    main()
