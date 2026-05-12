"""
看板开发 Agent Pipeline 执行脚本

用法：
    # 方式1：JSON文件输入（原有方式）
    python run_pipeline.py --input <需求JSON文件> --output <输出目录>

    # 方式2：自然语言输入（新增）
    python run_pipeline.py --natural-input "帮我做一个用户行为分析看板，数据源是iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"

    # 方式3：从文件读取自然语言
    python run_pipeline.py --natural-input-file input.txt --output ./output

    # 指定运行模式（覆盖配置）
    python run_pipeline.py --natural-input "..." --mode publish   # 强制推送模式
    python run_pipeline.py --natural-input "..." --mode plan      # 强制方案模式

依赖：
    pip install openai python-dotenv

配置：
    修改同目录下的 config.json 或设置环境变量
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

# 添加skill目录到Python路径
SKILL_DIR = Path(__file__).parent

# 确定工作空间目录
# 默认：脚本所在目录的父目录（即项目根目录）
# 可通过环境变量 WORKSPACE_DIR 覆盖
_default_workspace = str(SKILL_DIR.parent)
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", _default_workspace))

# 尝试从工作空间加载依赖模块
sys.path.insert(0, str(WORKSPACE_DIR))

try:
    from src.llm import LLMClient
    from src.pipeline import Pipeline
    from src.agents import RunMode
except ImportError as e:
    print(f"[WARN] 无法导入依赖模块: {e}")
    print(f"请确保工作空间 ({WORKSPACE_DIR}) 包含完整的 Agent 实现")
    sys.exit(1)

# Logger 初始化（延迟导入避免循环）
logger = None


def _init_logger():
    global logger
    if logger is not None:
        return
    try:
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


def save_outputs(output_dir: Path, pipeline_result):
    """保存Pipeline输出到文件"""
    _init_logger()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存方案文档
    if pipeline_result.solution_document:
        (output_dir / "solution.md").write_text(
            pipeline_result.solution_document,
            encoding="utf-8"
        )
        logger.info(f"方案文档已保存: {output_dir / 'solution.md'}")

    # 保存HTML版本
    if pipeline_result.html_document:
        (output_dir / "solution.html").write_text(
            pipeline_result.html_document,
            encoding="utf-8"
        )
        logger.info(f"HTML版本已保存: {output_dir / 'solution.html'}")

    # 保存Agent中间输出
    agent_outputs_dir = output_dir / "agent_outputs"
    agent_outputs_dir.mkdir(exist_ok=True)

    agent_output_names = [
        "requirements_parser_output",
        "semantic_model_output",
        "chart_design_output",
        "instruction_generator_output",
        "solution_generator_output",
    ]

    agent_display_names = [
        "1.requirements_parser",
        "2.semantic_model",
        "3.chart_design",
        "4.instruction_generator",
        "5.solution_generator",
    ]

    for key, name in zip(agent_output_names, agent_display_names):
        output = pipeline_result.context.get(key) if hasattr(pipeline_result, 'context') else None
        if output:
            output_file = agent_outputs_dir / f"{name}.json"
            if isinstance(output, str):
                output_file.write_text(output, encoding="utf-8")
            else:
                output_file.write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            logger.info(f"  {name} 输出已保存: {output_file}")

    # 保存确认项
    if pipeline_result.all_confirmation_items:
        (agent_outputs_dir / "confirmation_items.json").write_text(
            json.dumps(pipeline_result.all_confirmation_items, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # 保存执行摘要
    summary = {
        "pipeline_id": pipeline_result.pipeline_id,
        "status": pipeline_result.status,
        "total_duration_ms": pipeline_result.total_duration_ms,
        "total_duration_min": pipeline_result.total_duration_ms / 60000,
        "step_durations": {
            s.agent_name: s.duration_ms
            for s in pipeline_result.steps
        },
        "confirmation_items_count": len(pipeline_result.all_confirmation_items),
    }
    (output_dir / "execution_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"执行摘要已保存: {output_dir / 'execution_summary.json'}")


def main():
    _init_logger()

    parser = argparse.ArgumentParser(description="看板开发 Agent Pipeline")
    parser.add_argument("--input", "-i", help="需求JSON文件路径（原有方式）")
    parser.add_argument("--output", "-o", default="./output", help="输出目录")
    # 新增：自然语言输入参数
    parser.add_argument("--natural-input", "-n", help="自然语言输入（新增方式）")
    parser.add_argument("--natural-input-file", help="从文件读取自然语言输入")
    parser.add_argument("--mode", "-m", choices=["plan", "publish"], help="运行模式：plan（仅方案）/ publish（推送），覆盖所有默认配置")
    parser.add_argument("--no-sql-test", action="store_true", help="跳过 SQL 试跑校验")

    args = parser.parse_args()

    # 决定输入模式
    user_input = None
    input_source = ""

    if args.natural_input:
        # 模式1：命令行自然语言输入
        input_source = "自然语言输入"
        logger.info(f"自然语言输入模式")
        logger.debug(f"  [INPUT] {args.natural_input[:80]}...")

        # 使用NLConverter转换
        from nl_converter import NLConverter
        config = load_config()
        llm_config = config.get("llm", {})
        dp_config = config.get("data_platform", {})

        converter = NLConverter(llm_config, dp_config)
        user_input = converter.convert(args.natural_input)

    elif args.natural_input_file:
        # 模式2：从文件读取自然语言
        input_source = f"文件: {args.natural_input_file}"
        input_path = Path(args.natural_input_file)
        if not input_path.exists():
            print(f"❌ 输入文件不存在: {input_path}")
            sys.exit(1)

        with open(input_path, "r", encoding="utf-8") as f:
            natural_language = f.read()

        logger.info(f"自然语言文件输入模式")
        logger.debug(f"  [INPUT] {input_path}")

        # 使用NLConverter转换
        from nl_converter import NLConverter
        config = load_config()
        llm_config = config.get("llm", {})
        dp_config = config.get("data_platform", {})

        converter = NLConverter(llm_config, dp_config)
        user_input = converter.convert(natural_language)

    elif args.input:
        # 模式3：JSON文件输入（原有方式）
        input_source = f"文件: {args.input}"
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"❌ 输入文件不存在: {input_path}")
            sys.exit(1)

        with open(input_path, "r", encoding="utf-8") as f:
            user_input = json.load(f)

    else:
        print("❌ 请提供输入：")
        print("   --input <JSON文件>          # 原有方式")
        print("   --natural-input <自然语言>   # 新增：自然语言方式")
        print("   --natural-input-file <文件>  # 新增：从文件读取自然语言")
        print("   --mode plan|publish          # 可选：指定运行模式")
        parser.print_help()
        sys.exit(1)

    logger.info(f"启动看板开发 Agent Pipeline")
    logger.info(f"  输入: {input_source}, 输出: {args.output}")

    # 加载配置（配置文件优先于环境变量）
    config = load_config()
    llm_config = config.get("llm", {})
    dp_config = config.get("data_platform", {})

    # 初始化Pipeline
    # 优先级：配置文件 > 环境变量 > 默认值
    model_config = {
        "model": llm_config.get("model") or "deepseek-ai/DeepSeek-V4-Flash",
        # api_key: 配置文件 > HUNYUAN_API_KEY > DEEPSEEK_API_KEY
        "api_key": llm_config.get("api_key") or os.getenv("HUNYUAN_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        # base_url: 配置文件 > 环境变量 > 默认值（不设置则使用SDK默认）
        "base_url": llm_config.get("base_url") or os.getenv("LLM_BASE_URL") or None,
    }

    # 数据平台配置（用于 user_input 传递）
    data_platform_config = {
        "base_url": dp_config.get("base_url") or os.getenv("DATA_PLATFORM_BASE_URL") or "",
        "catalog": dp_config.get("catalog") or "",
        "schema": dp_config.get("schema") or "",
        "engine": dp_config.get("engine") or "Spark",
        "token": dp_config.get("token") or os.getenv("DATA_PLATFORM_TOKEN") or "",
    }

    # 合并到 user_input（user_input 中的配置优先级最高）
    if "data_platform_config" not in user_input:
        user_input["data_platform_config"] = data_platform_config
    else:
        # 合并：user_input > 配置文件 > 环境变量
        for key in data_platform_config:
            if not user_input["data_platform_config"].get(key):
                user_input["data_platform_config"][key] = data_platform_config[key]

    # ---- BI 推送模式判断（四层优先级） ----
    # 优先级（高→低）：--mode 参数 > user_input["bi_config"] > NLConverter _mode_hint > config.json bi_platform.enabled

    bi_config = user_input.get("bi_config")
    mode_source = ""

    # P1: --mode 命令行参数（最高优先级）
    if args.mode:
        if args.mode == "publish":
            bi_platform = config.get("bi_platform", {})
            bi_config = {
                "base_url": bi_platform.get("base_url"),
                "space_id": bi_platform.get("space_id"),
                "creator": bi_platform.get("creator"),
            }
            # 去除 None 值
            bi_config = {k: v for k, v in bi_config.items() if v is not None}
            if bi_config:
                user_input["bi_config"] = bi_config
            mode_source = f"命令行参数 --mode {args.mode}"
        else:  # plan
            bi_config = None
            mode_source = f"命令行参数 --mode {args.mode}"

    elif bi_config is not None:
        # P2: 用户输入中的 bi_config（JSON 文件中显式提供）
        # bi_config 已经在 user_input 中，直接使用
        mode_source = "用户输入 bi_config"

    else:
        # P3: NLConverter 的 _mode_hint（自然语言关键词）
        mode_hint = user_input.pop("_mode_hint", None)
        if mode_hint:
            if mode_hint == "publish":
                bi_platform = config.get("bi_platform", {})
                bi_config = {
                    "base_url": bi_platform.get("base_url"),
                    "space_id": bi_platform.get("space_id"),
                    "creator": bi_platform.get("creator"),
                }
                bi_config = {k: v for k, v in bi_config.items() if v is not None}
                if bi_config:
                    user_input["bi_config"] = bi_config
                    mode_source = f"自然语言关键词（推送），config.json bi_platform"
            else:  # plan
                bi_config = None
                mode_source = "自然语言关键词（方案）"

        else:
            # P4: config.json bi_platform.enabled 开关（兜底）
            bi_platform = config.get("bi_platform", {})
            enabled = bi_platform.get("enabled", "plan")
            if enabled == "publish":
                bi_config = {
                    "base_url": bi_platform.get("base_url"),
                    "space_id": bi_platform.get("space_id"),
                    "creator": bi_platform.get("creator"),
                }
                bi_config = {k: v for k, v in bi_config.items() if v is not None}
                if bi_config:
                    user_input["bi_config"] = bi_config
                    mode_source = "config.json bi_platform.enabled = publish"
                else:
                    mode_source = "config.json bi_platform.enabled = publish（但 space_id/creator 未配置，回退 PLAN）"
            else:
                mode_source = "默认模式（plan）"

    # 清除残留的 _mode_hint（安全兜底）
    user_input.pop("_mode_hint", None)

    run_mode = RunMode.PUBLISH if user_input.get("bi_config") else RunMode.PLAN
    logger.info(f"运行模式: {run_mode.name}（来源：{mode_source}）")

    # ---- SQL 校验开关（三级优先级） ----
    # 优先级（高→低）：user_input["enable_sql_test"] > --no-sql-test / NLConverter 关键词 > config.json sql_validation
    # 默认启用（True），三层都是「关闭能力」
    sql_test_source = ""
    enable_sql_test_final = True  # 默认启用

    # 最高优先级：user_input 中显式指定（JSON 文件输入场景）
    if "enable_sql_test" in user_input:
        enable_sql_test_final = bool(user_input["enable_sql_test"])
        sql_test_source = "user_input 显式指定"
    elif args.no_sql_test:
        # P1: --no-sql-test 命令行参数
        enable_sql_test_final = False
        sql_test_source = "命令行参数 --no-sql-test"
    else:
        # P2: NLConverter 关键词检测
        sql_test_hint = user_input.pop("_sql_test_hint", None)
        if sql_test_hint is False:
            enable_sql_test_final = False
            sql_test_source = "自然语言关键词（跳过校验）"
        else:
            # P3: config.json sql_validation 兜底
            enable_sql_test_final = bool(config.get("sql_validation", True))
            sql_test_source = f"config.json sql_validation = {enable_sql_test_final}"

    # 清除残留的 _sql_test_hint（安全兜底）
    user_input.pop("_sql_test_hint", None)

    # 写入最终值到 user_input（Pipeline 会从这里读取）
    user_input["enable_sql_test"] = enable_sql_test_final
    logger.info(f"SQL校验: {'启用' if enable_sql_test_final else '跳过'}（来源：{sql_test_source}）")

    pipeline = Pipeline(
        model_config=model_config,
        run_mode=run_mode,
    )

    # 执行Pipeline
    start_time = time.time()
    try:
        result = pipeline.run(user_input)
    except Exception as e:
        logger.error(f"Pipeline 执行失败: {e}")
        sys.exit(1)

    # 保存输出
    output_dir = Path(args.output)
    save_outputs(output_dir, result)

    # 打印结果摘要
    duration_min = result.total_duration_ms / 60000
    logger.info(f"Pipeline 完成!")
    logger.info(f"  总耗时: {duration_min:.1f} 分钟")
    logger.info(f"  确认项: {len(result.all_confirmation_items)} 项")
    logger.info(f"  输出目录: {output_dir.absolute()}")


if __name__ == "__main__":
    main()
