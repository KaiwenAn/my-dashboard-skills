"""
看板开发 Agent Pipeline 执行脚本

用法：
    # 方式1：JSON文件输入（原有方式）
    python run_pipeline.py --input <需求JSON文件> --output <输出目录>

    # 方式2：自然语言输入（新增）
    python run_pipeline.py --natural-input "帮我做一个用户行为分析看板，数据源是iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"

    # 方式3：从文件读取自然语言
    python run_pipeline.py --natural-input-file input.txt --output ./output

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
# 默认：C:\Users\Kai\WorkBuddy\20260427134240
# 可通过环境变量 WORKSPACE_DIR 覆盖
_default_workspace = str(Path.home() / "WorkBuddy" / "20260427134240")
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", _default_workspace))

# 尝试从工作空间加载依赖模块
sys.path.insert(0, str(WORKSPACE_DIR))

try:
    from llm import LLMClient
    from pipeline import Pipeline
    from agents import RunMode
except ImportError as e:
    print(f"[WARN] 无法导入依赖模块: {e}")
    print(f"请确保工作空间 ({WORKSPACE_DIR}) 包含完整的 Agent 实现")
    sys.exit(1)


def load_config():
    """加载配置文件"""
    config_path = SKILL_DIR / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_outputs(output_dir: Path, pipeline_result):
    """保存Pipeline输出到文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存方案文档
    if pipeline_result.solution_document:
        (output_dir / "solution.md").write_text(
            pipeline_result.solution_document,
            encoding="utf-8"
        )
        print(f"  [SAVE] 方案文档已保存: {output_dir / 'solution.md'}")

    # 保存HTML版本
    if pipeline_result.html_document:
        (output_dir / "solution.html").write_text(
            pipeline_result.html_document,
            encoding="utf-8"
        )
        print(f"  [HTML] HTML版本已保存: {output_dir / 'solution.html'}")

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
            print(f"  [AGENT] {name} 输出已保存: {output_file}")

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
    print(f"  [SUMMARY] 执行摘要已保存: {output_dir / 'execution_summary.json'}")


def main():
    parser = argparse.ArgumentParser(description="看板开发 Agent Pipeline")
    parser.add_argument("--input", "-i", help="需求JSON文件路径（原有方式）")
    parser.add_argument("--output", "-o", default="./output", help="输出目录")
    # 新增：自然语言输入参数
    parser.add_argument("--natural-input", "-n", help="自然语言输入（新增方式）")
    parser.add_argument("--natural-input-file", help="从文件读取自然语言输入")

    args = parser.parse_args()

    # 决定输入模式
    user_input = None
    input_source = ""

    if args.natural_input:
        # 模式1：命令行自然语言输入
        input_source = "自然语言输入"
        print(f"\n{'#'*60}")
        print(f"[MODE] 自然语言输入模式")
        print(f"  [INPUT] {args.natural_input[:80]}...")
        print(f"{'#'*60}\n")

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

        print(f"\n{'#'*60}")
        print(f"[MODE] 自然语言文件输入模式")
        print(f"  [INPUT] {input_path}")
        print(f"{'#'*60}\n")

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
        parser.print_help()
        sys.exit(1)

    print(f"\n{'#'*60}")
    print(f"[START] 启动看板开发 Agent Pipeline")
    print(f"  [INPUT] 输入: {input_source}")
    print(f"  [OUTPUT] 输出: {args.output}")
    print(f"{'#'*60}\n")

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

    # 确定运行模式
    bi_config = user_input.get("bi_config")
    run_mode = RunMode.PUBLISH if bi_config else RunMode.PLAN

    pipeline = Pipeline(
        model_config=model_config,
        run_mode=run_mode,
    )

    # 执行Pipeline
    start_time = time.time()
    try:
        result = pipeline.run(user_input)
    except Exception as e:
        print(f"\n❌ Pipeline 执行失败: {e}")
        sys.exit(1)

    # 保存输出
    output_dir = Path(args.output)
    save_outputs(output_dir, result)

    # 打印结果摘要
    duration_min = result.total_duration_ms / 60000
    print(f"\n{'#'*60}")
    print(f"[DONE] Pipeline 完成!")
    print(f"  总耗时: {duration_min:.1f} 分钟")
    print(f"  确认项: {len(result.all_confirmation_items)} 项")
    print(f"  输出目录: {output_dir.absolute()}")
    print(f"{'#'*60}")


if __name__ == "__main__":
    main()
