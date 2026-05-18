"""
图表类型目录 — 单一事实源

BI 平台支持的全部图表类型清单。所有 prompt（chart-design-agent / instruction-generator-agent）
和校验逻辑（ChartDesignAgent.validate_output）都从这里取数据，避免清单在多处分别维护、漂移。

字段说明：
- chinese_name : LLM 输出 chart_type 字段时使用的中文名（与 BI 平台 UI 完全一致）
- english_id   : instruction_generator 翻译为英文标识用，传给编辑助手
- purpose      : 主要用途分类（用于 LLM 选型决策）
- description  : 简介（来自 BI 平台官方文档）

新增 / 删除图表类型时，只改这一份文件，prompt 和校验都会自动跟随。
"""
from typing import Optional


# ============================================================
# 数据：与 BI 平台 UI 完全一致的 21 种图表类型
# ============================================================
SUPPORTED_CHART_TYPES = [
    {
        "chinese_name": "数字卡片",
        "english_id": "metric_card",
        "purpose": "汇总、趋势",
        "description": "用于直观展示核心指标值及其变化趋势（如同比、环比）",
    },
    {
        "chinese_name": "指标趋势卡",
        "english_id": "metric_trend",
        "purpose": "趋势",
        "description": "可以展示多个指标最新日期的数据或阶段汇总数据，以及指标在某一段时间内的变化趋势",
    },
    {
        "chinese_name": "折线图",
        "english_id": "line",
        "purpose": "趋势",
        "description": "展示连续数据的变化趋势",
    },
    {
        "chinese_name": "柱形图",
        "english_id": "bar",
        "purpose": "趋势、比较",
        "description": "展示数据的变化和数据间的比较情况",
    },
    {
        "chinese_name": "组合图",
        "english_id": "dual_axis",
        "purpose": "趋势、比较",
        "description": "比较各组数据之间的差别，也适合那些趋势比单个数据点更重要的指标集（也称双轴图）",
    },
    {
        "chinese_name": "表格",
        "english_id": "table",
        "purpose": "明细",
        "description": "一般由多行多列数据组成，用于展示数据的详细信息或多个具有直接关系数值",
    },
    {
        "chinese_name": "透视表",
        "english_id": "pivot_table",
        "purpose": "汇总、明细",
        "description": "类似表格的形式将数据组织起来，并通过行、列和值的组合来展示数据的交叉和汇总情况",
    },
    {
        "chinese_name": "条形图",
        "english_id": "horizontal_bar",
        "purpose": "比较",
        "description": "柱形图的横向展示方式，方便展示数据之间的比较",
    },
    {
        "chinese_name": "雷达图",
        "english_id": "radar",
        "purpose": "比较",
        "description": "用来进行多指标或多维度对比，一目了然地了解各数据指标的变动情形及其好坏趋向",
    },
    {
        "chinese_name": "饼图",
        "english_id": "pie",
        "purpose": "分布",
        "description": "用于分析数据的占比，用户可通过饼图直观看到每一个部分在整体中所占的比例（建议分类不超过 6 个，否则改用条形图）",
    },
    {
        "chinese_name": "矩形树图",
        "english_id": "treemap",
        "purpose": "分布、占比",
        "description": "用来描述层次结构数据的占比关系",
    },
    {
        "chinese_name": "热力图",
        "english_id": "heatmap",
        "purpose": "分布、相关",
        "description": "适合用于查看总体的情况、发现异常值、显示多个变量之间的差异，以及检测是否存在相关性",
    },
    {
        "chinese_name": "直方图",
        "english_id": "histogram",
        "purpose": "分布",
        "description": "用于显示各组频数或者数量分布的情况，展示各组之间频数或数量的差别",
    },
    {
        "chinese_name": "地图",
        "english_id": "map",
        "purpose": "分布",
        "description": "使用不同深浅的颜色来展示数据的大小和分布范围（适用于有地理维度的数据）",
    },
    {
        "chinese_name": "散点图",
        "english_id": "scatter",
        "purpose": "分布、相关",
        "description": "多用于展示数据的相关性和分布关系，将所有数据以点的形式展现在直角坐标系上",
    },
    {
        "chinese_name": "箱线图",
        "english_id": "boxplot",
        "purpose": "分布",
        "description": "用于显示一组连续型数据分布情况",
    },
    {
        "chinese_name": "词云图",
        "english_id": "word_cloud",
        "purpose": "分布",
        "description": "常用于描述高频样本、突出重点、描述关键字等场景",
    },
    {
        "chinese_name": "漏斗图",
        "english_id": "funnel",
        "purpose": "转化、流向",
        "description": "表现业务过程中的转化情况，适合有顺序、多阶段的流程分析",
    },
    {
        "chinese_name": "桑基图",
        "english_id": "sankey",
        "purpose": "流向",
        "description": "展示一组数据到另一组数据的流动情况；可分析数据/信息的流动关系，或变量间的相互依存关系",
    },
    {
        "chinese_name": "子弹图",
        "english_id": "bullet",
        "purpose": "进度",
        "description": "用于实际与目标完成情况的可视化，可展示实际数值的大小并与目标值比较",
    },
    {
        "chinese_name": "仪表盘",
        "english_id": "gauge",
        "purpose": "进度",
        "description": "直观表现出某个指标的进度或实际情况",
    },
]


# ============================================================
# 派生数据
# ============================================================

# 中文名集合（用于校验 chart_type 是否合法）
SUPPORTED_CHINESE_NAMES = frozenset(item["chinese_name"] for item in SUPPORTED_CHART_TYPES)

# 中文名 → 英文 ID 映射
CHINESE_TO_ENGLISH = {item["chinese_name"]: item["english_id"] for item in SUPPORTED_CHART_TYPES}

# 兼容历史 prompt 输出的别名（如果哪天 LLM 仍然吐出旧名字，先 alias 到新名字再校验）
LEGACY_ALIAS = {
    "指标卡片": "数字卡片",     # 旧 chart-design prompt 用 "指标卡片"
    "柱状图": "柱形图",         # 旧 prompt 用 "柱状图"
    "数据表格": "表格",         # 旧 prompt 用 "数据表格"
    "环形图": "饼图",           # BI 不单独区分
    "面积图": "折线图",         # BI 不支持，归到折线图
    "堆叠柱状图": "柱形图",     # BI 不单独区分
    "指标趋势图": "指标趋势卡", # 命名漂移
    "双轴图": "组合图",         # 同义词
}


def normalize_chart_type(name: str) -> Optional[str]:
    """
    把 LLM 输出的 chart_type（可能是旧别名）规范化成 BI 支持的中文名。

    Returns:
        规范化后的中文名（在 SUPPORTED_CHINESE_NAMES 中），或 None 表示无法规范化
    """
    if not name:
        return None
    name = name.strip()
    if name in SUPPORTED_CHINESE_NAMES:
        return name
    if name in LEGACY_ALIAS:
        return LEGACY_ALIAS[name]
    return None


def is_valid_chart_type(name: str) -> bool:
    """chart_type 是否是 BI 支持（含历史别名）的合法值"""
    return normalize_chart_type(name) is not None


def get_english_id(chinese_name: str) -> Optional[str]:
    """中文名 → 英文 ID（先做规范化，旧别名也能查到）"""
    canonical = normalize_chart_type(chinese_name)
    if canonical is None:
        return None
    return CHINESE_TO_ENGLISH.get(canonical)


# ============================================================
# Prompt 注入：渲染成 markdown 表格
# ============================================================

def render_for_design_prompt() -> str:
    """
    给 chart-design-agent prompt 用：列出所有可选图表类型 + 用途 + 简介，
    LLM 据此挑选最合适的 chart_type。
    """
    lines = [
        "| 图表类型 | 主要用途 | 简介 |",
        "|---|---|---|",
    ]
    for item in SUPPORTED_CHART_TYPES:
        lines.append(
            f"| `{item['chinese_name']}` | {item['purpose']} | {item['description']} |"
        )
    return "\n".join(lines)


def render_chart_type_enum() -> str:
    """给 prompt 内嵌的 JSON 示例用，pipe 分隔的枚举字符串"""
    return " | ".join(item["chinese_name"] for item in SUPPORTED_CHART_TYPES)


def render_mapping_for_instruction_prompt() -> str:
    """
    给 instruction-generator-agent prompt 用：中文名 → 英文 ID 映射表，
    instruction_generator 在输出时按这张表把中文 chart_type 翻译成英文 ID。
    """
    lines = [
        "| 中文名（chart_design 输出） | 英文 ID（instruction 输出） |",
        "|---|---|",
    ]
    for item in SUPPORTED_CHART_TYPES:
        lines.append(f"| {item['chinese_name']} | {item['english_id']} |")
    return "\n".join(lines)
