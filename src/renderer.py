"""
方案文档 HTML 渲染器

将 Agent 输出的 Markdown 方案文档渲染为可视化 HTML 报告。
不依赖外部库，纯 Python + 正则解析。

设计思路：
- Markdown 文档的结构是固定的（一～六章）
- 通过正则解析各章节内容
- 用 HTML/CSS 渲染为可视化报告
"""

import re
import html as html_module
from datetime import datetime


def escape(text: str) -> str:
    """HTML 转义"""
    return html_module.escape(text)


def render_html_report(markdown_text: str, dashboard_title: str = "") -> str:
    """
    将 Markdown 方案文档渲染为完整的 HTML 报告

    Args:
        markdown_text: Agent 输出的完整 Markdown 文档
        dashboard_title: 看板标题（如未提供则从文档中提取）

    Returns:
        完整的 HTML 字符串
    """
    if not dashboard_title:
        dashboard_title = _extract_title(markdown_text)

    # 提取各章节
    sections = _parse_sections(markdown_text)

    html_body = f"""
<div class="report-header">
  <div class="report-badge">Agent 自动生成</div>
  <h1 class="report-title">{escape(dashboard_title)}</h1>
  <p class="report-subtitle">BI 看板搭建方案 · {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</div>

<div class="report-toc">
  <h2 class="toc-title">目录</h2>
  <nav class="toc-links">
    <a href="#sec-overview">一、看板概述</a>
    <a href="#sec-semantic">二、语义模型搭建指南</a>
    <a href="#sec-layout">三、看板布局方案</a>
    <a href="#sec-confirm">四、待确认项清单</a>
    <a href="#sec-steps">五、搭建步骤建议</a>
    <a href="#sec-instruction">六、看板搭建指令</a>
  </nav>
</div>

{_render_overview_section(sections.get('overview', ''))}

{_render_semantic_section(sections.get('semantic', ''))}

{_render_layout_section(sections.get('layout', ''))}

{_render_confirm_section(sections.get('confirm', ''))}

{_render_steps_section(sections.get('steps', ''))}

{_render_instruction_section(sections.get('instruction', ''))}

<div class="report-footer">
  <p>本文档由看板开发 Agent 自动生成 · 人机协作 · 请审核确认项后执行搭建</p>
</div>
"""

    return _wrap_in_html_template(html_body)


def _extract_title(text: str) -> str:
    """从 Markdown 中提取标题"""
    m = re.search(r'^#\s+(.+)', text, re.MULTILINE)
    return m.group(1).replace(' — BI看板搭建方案', '').strip() if m else "看板搭建方案"


def _parse_sections(text: str) -> dict:
    """将 Markdown 文本按章节拆分"""
    sections = {}

    # 按一级标题拆分
    parts = re.split(r'^##\s+', text, flags=re.MULTILINE)

    for part in parts[1:]:  # 跳过第一个（标题之前的内容）
        lines = part.split('\n', 1)
        heading = lines[0].strip()
        content = lines[1] if len(lines) > 1 else ""

        if '看板概述' in heading:
            sections['overview'] = content
        elif '语义模型' in heading:
            sections['semantic'] = content
        elif '布局' in heading:
            sections['layout'] = content
        elif '待确认' in heading or '确认项' in heading:
            sections['confirm'] = content
        elif '搭建步骤' in heading:
            sections['steps'] = content
        elif '看板搭建指令' in heading or '看板指令' in heading:
            sections['instruction'] = content

    return sections


# ==================== 章节渲染器 ====================

def _render_overview_section(text: str) -> str:
    """渲染看板概述"""
    if not text:
        return '<section id="sec-overview"><h2>一、看板概述</h2><p>（暂无数据）</p></section>'

    # 提取基本信息表格
    info_table = _extract_first_md_table(text)
    info_html = _render_info_cards(info_table) if info_table else ""

    # 提取核心业务问题
    questions = _extract_bullet_list(text, start_after="核心业务问题")
    questions_html = ""
    if questions:
        items_html = "".join(f"<li>{escape(q)}</li>" for q in questions)
        questions_html = f"""
        <div class="section-block">
          <h3>核心业务问题</h3>
          <ul class="question-list">{items_html}</ul>
        </div>"""

    # 提取数据源
    sources = _extract_bullet_list(text, start_after="数据源")
    sources_html = ""
    if sources:
        tags_html = "".join(
            f'<span class="data-source-tag">{_highlight_sql(s)}</span>'
            for s in sources
        )
        sources_html = f"""
        <div class="section-block">
          <h3>数据源</h3>
          <div class="tag-list">{tags_html}</div>
        </div>"""

    # 提取指标一览
    metrics_table = _extract_md_table_by_header(text, ["指标名称", "类型", "口径定义"])
    metrics_html = ""
    if metrics_table:
        metrics_html = f"""
        <div class="section-block">
          <h3>指标一览</h3>
          <div class="table-wrapper">
            <table class="styled-table metrics-table">
              <thead>
                <tr>
                  <th>指标名称</th>
                  <th>类型</th>
                  <th>口径定义</th>
                  <th>单位</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {_render_metrics_table_body(metrics_table)}
              </tbody>
            </table>
          </div>
        </div>"""

    return f"""
<section id="sec-overview" class="report-section">
  <h2 class="section-heading"><span class="heading-num">一</span> 看板概述</h2>
  {info_html}
  {questions_html}
  {sources_html}
  {metrics_html}
</section>"""


def _render_semantic_section(text: str) -> str:
    """渲染语义模型搭建指南"""
    if not text:
        return '<section id="sec-semantic"><h2>二、语义模型搭建指南</h2><p>（暂无数据）</p></section>'

    # 查找所有语义模型（三级标题：2.1 模型：xxx）
    model_sections = re.split(r'^###\s+\d+\.\d+\s+', text, flags=re.MULTILINE)

    models_html = ""
    for section in model_sections[1:]:  # 跳过第一个
        lines = section.split('\n', 1)
        model_title = lines[0].strip()
        model_content = lines[1] if len(lines) > 1 else ""
        models_html += _render_single_model(model_title, model_content)

    return f"""
<section id="sec-semantic" class="report-section">
  <h2 class="section-heading"><span class="heading-num">二</span> 语义模型搭建指南</h2>
  {models_html}
</section>"""


def _render_single_model(title: str, content: str) -> str:
    """渲染单个语义模型"""
    # 提取用途
    purpose = ""
    m = re.search(r'\*\*用途\*\*[：:]\s*(.+)', content)
    if m:
        purpose = m.group(1).strip()

    # 提取 SQL
    sql_blocks = _extract_sql_blocks(content)

    sql_html = ""
    if sql_blocks:
        sql_parts = ""
        for i, sql in enumerate(sql_blocks):
            highlighted = _highlight_sql(sql)
            sql_id = f"sql_{i}"
            sql_parts += f"""
            <div class="sql-block">
              <div class="sql-header">
                <span class="sql-icon">{{}} SQL</span>
                <button class="copy-btn" onclick="copySql('{sql_id}')">复制</button>
              </div>
              <pre class="sql-code" id="{sql_id}"><code>{highlighted}</code></pre>
            </div>"""

        # 提取 SQL 说明
        sql_notes = _extract_blockquote(content)
        notes_html = ""
        if sql_notes:
            notes_html = f'<div class="sql-notes">{_markdown_to_inline_html(sql_notes)}</div>'

        sql_html = f"""
        <div class="model-sql-area">
          {sql_parts}
          {notes_html}
        </div>"""

    # 维度配置表 — 用锚点限定只在"维度配置"标题之后搜索
    dim_table = _extract_md_table_by_header(content, ["字段名", "数据类型", "语义类型"], after_marker="维度配置")
    dim_html = _render_config_table("维度配置", dim_table, ["字段名", "来源表", "数据类型", "语义类型", "配置说明"])

    # 指标配置表 — 用锚点限定只在"指标配置"标题之后搜索
    metric_table = _extract_md_table_by_header(content, ["字段名", "聚合方式"], after_marker="指标配置")
    metric_html = _render_config_table("指标配置", metric_table, ["字段名", "聚合方式", "SQL 表达式", "依赖指标", "单位", "状态"])

    # 关联逻辑表
    join_table = _extract_md_table_by_header(content, ["左表", "关联方式"])
    join_html = ""
    if join_table:
        join_html = _render_config_table("关联逻辑", join_table, ["左表", "关联方式", "右表", "关联条件", "原因"])

    # 过滤条件
    filter_html = _render_filter_section(content)

    # 数据质量注意事项
    quality_table = _extract_md_table_by_header(content, ["类型", "描述"])
    quality_html = ""
    if quality_table:
        quality_items = ""
        for row in quality_table[1:]:  # 跳过表头
            if len(row) >= 2:
                qtype = escape(row[0])
                qdesc = _markdown_to_inline_html(row[1])
                qlocation = escape(row[2]) if len(row) >= 3 else ""
                qsuggest = _markdown_to_inline_html(row[3]) if len(row) >= 4 else ""
                quality_items += f"""
                <div class="quality-item">
                  <span class="quality-type">{_quality_type_badge(qtype)}</span>
                  <div class="quality-detail">
                    <p>{qdesc}</p>
                    {"<p class='quality-suggest'>" + qsuggest + "</p>" if qsuggest else ""}
                  </div>
                </div>"""
        quality_html = f"""
        <div class="subsection">
          <h4>⚠️ 数据质量注意事项</h4>
          <div class="quality-list">{quality_items}</div>
        </div>"""

    return f"""
<div class="model-card">
  <div class="model-header">
    <div class="model-icon">{_chart_icon('sql')}</div>
    <div class="model-info">
      <h3>{escape(title)}</h3>
      {f'<p class="model-purpose">{escape(purpose)}</p>' if purpose else ""}
    </div>
  </div>

  {sql_html}
  {dim_html}
  {metric_html}
  {join_html}
  {filter_html}
  {quality_html}
</div>"""


def _render_layout_section(text: str) -> str:
    """渲染看板布局方案"""
    if not text:
        return '<section id="sec-layout"><h2>三、看板布局方案</h2><p>（暂无数据）</p></section>'

    # 提取布局说明文字
    layout_notes = ""
    m = re.search(r'###\s+3\.1\s+整体布局\s*\n(.+?)(?=```|\n###)', text, re.DOTALL)
    if m:
        layout_notes = escape(m.group(1).strip())

    # 提取图表配置
    chart_sections = re.split(r'^####\s+(chart_\d+[：:]?\s*.+)', text, flags=re.MULTILINE)

    charts_html = ""
    chart_configs = []  # 收集布局信息用于绘制布局预览

    for i in range(1, len(chart_sections), 2):
        chart_title = chart_sections[i].strip()
        chart_content = chart_sections[i + 1] if i + 1 < len(chart_sections) else ""

        # 提取配置表格
        config = {}
        config_table = _extract_first_md_table(chart_content)
        if config_table:
            for row in config_table[1:]:  # 跳过表头
                if len(row) >= 2:
                    config[row[0]] = row[1]

        chart_configs.append({
            'id': re.search(r'chart_\d+', chart_title).group(0) if re.search(r'chart_\d+', chart_title) else f'chart_{i}',
            'name': re.sub(r'^chart_\d+\s*[：:]\s*', '', chart_title).strip(),
            'type': config.get('图表类型', ''),
            'model': config.get('关联模型', ''),
            'dimensions': config.get('维度', ''),
            'metrics': config.get('指标', ''),
            'position': config.get('位置', ''),
        })

        # 提取设计说明
        design_notes = ""
        dm = re.search(r'\*\*设计说明\*\*[：:]\s*(.+)', chart_content)
        if dm:
            design_notes = dm.group(1).strip()

        # 提取交互
        interaction = ""
        im = re.search(r'\*\*交互\*\*[：:]\s*(.+)', chart_content)
        if im:
            interaction = im.group(1).strip()

        charts_html += f"""
        <div class="chart-card">
          <div class="chart-card-header">
            <span class="chart-type-badge">{_chart_icon(config.get('图表类型', ''))} {escape(config.get('图表类型', '未知'))}</span>
            <h4>{escape(chart_title)}</h4>
          </div>
          <div class="chart-card-body">
            <div class="chart-meta-grid">
              <div class="chart-meta-item">
                <span class="meta-label">关联模型</span>
                <span class="meta-value code">{escape(config.get('关联模型', '-'))}</span>
              </div>
              <div class="chart-meta-item">
                <span class="meta-label">维度</span>
                <span class="meta-value">{_highlight_sql(config.get('维度', '-'))}</span>
              </div>
              <div class="chart-meta-item">
                <span class="meta-label">指标</span>
                <span class="meta-value">{_highlight_sql(config.get('指标', '-'))}</span>
              </div>
              <div class="chart-meta-item">
                <span class="meta-label">位置</span>
                <span class="meta-value">{escape(config.get('位置', '-'))}</span>
              </div>
            </div>
            {"<div class='chart-interaction'><span class='interaction-tag'>交互</span> " + escape(interaction) + "</div>" if interaction else ""}
            {"<div class='chart-design-notes'>" + _markdown_to_inline_html(design_notes) + "</div>" if design_notes else ""}
          </div>
        </div>"""

    # 提取全局筛选器
    filter_table = _extract_md_table_by_header(text, ["筛选器", "字段", "类型"])
    filter_html = ""
    if filter_table:
        filter_rows = ""
        for row in filter_table[1:]:
            if len(row) >= 3:
                filter_rows += f"""
                <div class="filter-tag">
                  <span class="filter-name">{escape(row[0])}</span>
                  <span class="filter-type">{escape(row[2])}</span>
                </div>"""
        filter_html = f"""
        <div class="subsection">
          <h3>全局筛选器</h3>
          <div class="filter-list">{filter_rows}</div>
        </div>"""

    # 渲染布局预览图
    layout_preview = _render_layout_preview(chart_configs)

    return f"""
<section id="sec-layout" class="report-section">
  <h2 class="section-heading"><span class="heading-num">三</span> 看板布局方案</h2>

  <div class="subsection">
    <h3>布局预览</h3>
    <div class="layout-description">{layout_notes}</div>
    {layout_preview}
  </div>

  <div class="subsection">
    <h3>图表配置明细</h3>
    <div class="chart-cards-grid">{charts_html}</div>
  </div>

  {filter_html}
</section>"""


def _render_confirm_section(text: str) -> str:
    """渲染待确认项清单"""
    if not text:
        return '<section id="sec-confirm"><h2>四、待确认项清单</h2><p>（暂无确认项）</p></section>'

    # 提取确认项表格
    table = _extract_md_table_by_header(text, ["#", "类别", "确认内容"])
    if not table:
        table = _extract_first_md_table(text)

    if not table:
        return f"""
<section id="sec-confirm" class="report-section">
  <h2 class="section-heading"><span class="heading-num">四</span> 待确认项清单</h2>
  <pre>{escape(text[:500])}</pre>
</section>"""

    cards_html = ""
    for i, row in enumerate(table[1:], 1):
        if len(row) < 3:
            continue
        idx = row[0] if row[0] else str(i)
        category = row[1] if row[1] else "其他"
        content = row[2] if len(row) > 2 else ""
        risk = row[3] if len(row) > 3 else ""
        suggestion = row[4] if len(row) > 4 else ""

        cat_color = _category_color(category)

        cards_html += f"""
        <div class="confirm-card" style="border-left-color: var(--{cat_color});">
          <div class="confirm-card-top">
            <span class="confirm-index">#{escape(idx)}</span>
            <span class="confirm-category" style="background: rgba(var(--{cat_color}-rgb), 0.12); color: var(--{cat_color});">{escape(category)}</span>
          </div>
          <p class="confirm-content">{escape(content)}</p>
          {f'<p class="confirm-risk">{escape(risk)}</p>' if risk else ""}
          {f'<div class="confirm-suggestion">{_markdown_to_inline_html(suggestion)}</div>' if suggestion else ""}
          <label class="confirm-check">
            <input type="checkbox" />
            <span>已确认</span>
          </label>
        </div>"""

    # 统计
    total = len(table) - 1  # 减去表头
    stats = _count_categories(table)

    return f"""
<section id="sec-confirm" class="report-section confirm-section">
  <h2 class="section-heading"><span class="heading-num">四</span> 待确认项清单</h2>

  <div class="confirm-stats">
    <div class="stat-card">
      <div class="stat-number">{total}</div>
      <div class="stat-label">待确认项</div>
    </div>
    {"".join(f'<div class="stat-card stat-{_category_color(k).replace("-", "")}"><div class="stat-number">{v}</div><div class="stat-label">{escape(k)}</div></div>' for k, v in stats.items())}
  </div>

  <div class="confirm-tip">
    以下项目需要在搭建前完成确认，按风险从高到低排列。确认后请勾选复选框。
  </div>

  <div class="confirm-cards-grid">{cards_html}</div>
</section>"""


def _render_steps_section(text: str) -> str:
    """渲染搭建步骤建议"""
    if not text:
        return '<section id="sec-steps"><h2>五、搭建步骤建议</h2><p>（暂无数据）</p></section>'

    # 提取有序列表
    steps = re.findall(r'^\d+\.\s+\*\*(.+?)\*\*[：:]?\s*(.+)$', text, re.MULTILINE)
    if not steps:
        steps = re.findall(r'^\d+\.\s+(.+)$', text, re.MULTILINE)
        steps = [(s, "") for s in steps]

    steps_html = ""
    for i, (title, desc) in enumerate(steps, 1):
        steps_html += f"""
        <div class="step-item">
          <div class="step-num">{i}</div>
          <div class="step-content">
            <strong>{escape(title)}</strong>
            {f'<p>{_markdown_to_inline_html(desc)}</p>' if desc else ""}
          </div>
        </div>"""

    return f"""
<section id="sec-steps" class="report-section">
  <h2 class="section-heading"><span class="heading-num">五</span> 搭建步骤建议</h2>
  <div class="steps-timeline">{steps_html}</div>
</section>"""


def _render_instruction_section(text: str) -> str:
    """渲染第六章 看板搭建指令"""
    if not text:
        return '<section id="sec-instruction"><h2>六、看板搭建指令</h2><p>（暂无数据）</p></section>'

    # 尝试提取 JSON 代码块
    json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if json_match:
        json_text = json_match.group(1).strip()
    else:
        # 没有代码块，整体作为 markdown 文本渲染
        return f"""
<section id="sec-instruction" class="report-section">
  <h2 class="section-heading"><span class="heading-num">六</span> 看板搭建指令</h2>
  <div class="markdown-body">{_render_markdown(text)}</div>
</section>"""

    # 解析 JSON
    import json as json_lib
    try:
        data = json_lib.loads(json_text)
    except Exception:
        return f"""
<section id="sec-instruction" class="report-section">
  <h2 class="section-heading"><span class="heading-num">六</span> 看板搭建指令</h2>
  <pre class="sql-block"><code>{escape(json_text)}</code></pre>
</section>"""

    # 渲染 JSON 为结构化卡片
    title = escape(data.get('title', '未命名指令'))

    # 基本信息行
    info_items = ""
    for key in ['instruction_id', 'title']:
        if key in data and key != 'title':
            info_items += f'<span class="info-tag">{escape(key)}：{escape(str(data[key]))}</span>'
    info_items += f'<span class="info-tag primary">标题：{title}</span>'

    # 图表配置
    charts_html = ""
    charts = data.get('charts', [])
    for i, chart in enumerate(charts, 1):
        chart_title = escape(chart.get('title', f'图表{i}'))
        chart_type = escape(chart.get('type', '-'))
        semantic_model = escape(chart.get('semantic_model', '-'))
        x_field = escape(chart.get('x_field', '-'))
        y_field = escape(chart.get('y_field', '-'))

        # 量纲/格式
        extra = ""
        if chart.get('format'):
            extra += f'<span class="chart-extra">格式：{escape(chart["format"])}</span>'
        if chart.get('aggregation'):
            extra += f'<span class="chart-extra">聚合：{escape(chart["aggregation"])}</span>'
        if chart.get('filters'):
            filters_str = '; '.join([f'{escape(f["field"])}={escape(f["value"])}' for f in chart['filters']])
            extra += f'<span class="chart-extra">过滤：{filters_str}</span>'

        charts_html += f"""
        <div class="chart-card">
          <div class="chart-header">
            <span class="chart-num">{i}</span>
            <span class="chart-title">{chart_title}</span>
            <span class="chart-type-badge">{chart_type}</span>
          </div>
          <div class="chart-body">
            <div class="chart-row"><span class="chart-label">语义模型</span><span class="chart-value">{semantic_model}</span></div>
            <div class="chart-row"><span class="chart-label">X轴字段</span><span class="chart-value">{x_field}</span></div>
            <div class="chart-row"><span class="chart-label">Y轴字段</span><span class="chart-value">{y_field}</span></div>
            {extra}
          </div>
        </div>"""

    # 布局
    layout_html = ""
    layout = data.get('layout', {})
    if layout:
        cols = layout.get('columns', '-')
        rows = layout.get('rows', '-')
        layout_desc = layout.get('description', '')
        layout_html = f"""
        <div class="layout-block">
          <div class="layout-row"><span class="layout-label">列数</span><span class="layout-value">{cols}</span></div>
          <div class="layout-row"><span class="layout-label">行数</span><span class="layout-value">{rows}</span></div>
          {f'<div class="layout-desc">{escape(layout_desc)}</div>' if layout_desc else ''}
        </div>"""

    # 过滤器
    filters_html = ""
    filters = data.get('filters', [])
    if filters:
        for f in filters:
            field = escape(f.get('field', '-'))
            op = escape(f.get('operator', '='))
            val = escape(f.get('value', '-'))
            filters_html += f'<span class="filter-tag">{field} {op} {val}</span>'

    # 摘要/说明
    summary_html = ""
    summary = data.get('summary', '')
    if summary:
        summary_html = f'<div class="instruction-summary">{_markdown_to_inline_html(summary)}</div>'

    return f"""
<section id="sec-instruction" class="report-section">
  <h2 class="section-heading"><span class="heading-num">六</span> 看板搭建指令</h2>
  <div class="instruction-header">{info_items}</div>
  {summary_html}
  {f'<div class="charts-grid">{charts_html}</div>' if charts_html else ''}
  {f'<div class="filters-row">{filters_html}</div>' if filters_html else ''}
  {f'<div class="layout-section">{layout_html}</div>' if layout_html else ''}
  <div class="json-source">
    <details>
      <summary>查看原始 JSON</summary>
      <pre><code>{escape(json_text)}</code></pre>
    </details>
  </div>
</section>"""


# ==================== 辅助渲染函数 ====================

def _render_info_cards(table_data: list) -> str:
    """将基本信息表格渲染为卡片组，根据标签名自动匹配不同样式"""
    if not table_data or len(table_data) < 2:
        return ""

    # 标签名 → 卡片样式类名的映射
    # 只要标签里包含关键字就匹配（支持"看板名称"/"名称"等变体）
    label_style_map = [
        (["看板名称", "名称"], "info-card-blue"),
        (["目标受众", "受众"], "info-card-purple"),
        (["看板目标", "目标"], "info-card-green"),
    ]

    cards = ""
    for row in table_data[1:]:
        if len(row) < 2:
            continue
        label = row[0]
        # 确定样式类名
        card_style = "info-card-default"
        for keywords, style in label_style_map:
            if any(kw in label for kw in keywords):
                card_style = style
                break
        cards += f"""
            <div class="info-card {card_style}">
              <div class="info-label">{escape(row[0])}</div>
              <div class="info-value">{_markdown_to_inline_html(row[1])}</div>
            </div>"""
    return f'<div class="info-cards-grid">{cards}</div>'


def _render_config_table(title: str, table_data: list, headers: list) -> str:
    """渲染配置表格"""
    if not table_data or len(table_data) < 2:
        return ""
    header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_html = ""
    for row in table_data[1:]:
        if len(row) >= 1:
            cells = ""
            for j, h in enumerate(headers):
                val = row[j] if j < len(row) else ""
                cell_class = "code-cell" if h in ["字段名", "SQL 表达式"] else ""
                cells += f'<td class="{cell_class}">{_highlight_sql(escape(val))}</td>'
            body_html += f"<tr>{cells}</tr>"
    return f"""
    <div class="subsection">
      <h4>{escape(title)}</h4>
      <div class="table-wrapper">
        <table class="styled-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{body_html}</tbody>
        </table>
      </div>
    </div>"""


def _render_metrics_table_body(table_data: list) -> str:
    """渲染指标一览表（带状态颜色）"""
    rows = ""
    for row in table_data[1:]:
        if len(row) < 5:
            continue
        status = row[4] if len(row) > 4 else ""
        status_class = "status-ok" if "✅" in status or "已确认" in status else "status-warn"
        rows += f"""
        <tr>
          <td><strong>{escape(row[0])}</strong></td>
          <td><span class="type-badge">{escape(row[1])}</span></td>
          <td>{escape(row[2])}</td>
          <td>{escape(row[3])}</td>
          <td><span class="status-badge {status_class}">{escape(status)}</span></td>
        </tr>"""
    return rows


def _render_filter_section(content: str) -> str:
    """渲染过滤条件区域（三层过滤）"""
    result = ""

    # 模型级过滤
    model_filters = _extract_bold_list(content, "模型级过滤")
    if model_filters:
        items = "".join(f"<li>{_highlight_sql(_markdown_to_inline_html(f))}</li>" for f in model_filters)
        result += f"""
        <div class="subsection">
          <h4>过滤条件 <span class="filter-level-badge level-sql">SQL WHERE · 模型级</span></h4>
          <ul class="filter-list-text">{items}</ul>
        </div>"""

    # 图表级过滤
    chart_filters = _extract_bold_list(content, "图表级过滤")
    if chart_filters:
        items = "".join(f"<li>{_highlight_sql(_markdown_to_inline_html(f))}</li>" for f in chart_filters)
        result += f"""
        <div class="subsection">
          <h4><span class="filter-level-badge level-chart">筛选器 · 图表级</span></h4>
          <ul class="filter-list-text">{items}</ul>
        </div>"""

    # 指标级过滤
    metric_filters = _extract_bold_list(content, "指标级过滤")
    if metric_filters:
        items = "".join(f"<li>{_highlight_sql(_markdown_to_inline_html(f))}</li>" for f in metric_filters)
        result += f"""
        <div class="subsection">
          <h4><span class="filter-level-badge level-metric">CASE WHEN · 指标级</span></h4>
          <ul class="filter-list-text">{items}</ul>
        </div>"""

    return result


def _render_layout_preview(charts: list) -> str:
    """根据图表配置渲染可视化布局预览"""
    if not charts:
        return ""

    # 解析位置信息
    grid_cells = {}
    for chart in charts:
        position = chart.get('position', '')
        # 匹配 "第X行 第Y列，占M行N列"
        m = re.search(r'第(\d+)行\s+第(\d+)列.*?占(\d+)行(\d+)列', position)
        if m:
            row = int(m.group(1))
            col = int(m.group(2))
            row_span = int(m.group(3))
            col_span = int(m.group(4))
            grid_cells[chart['id']] = {
                'name': chart['name'],
                'type': chart['type'],
                'row': row, 'col': col,
                'row_span': row_span, 'col_span': col_span,
            }

    if not grid_cells:
        return ""

    # 计算总行数
    max_row = max(c['row'] + c['row_span'] - 1 for c in grid_cells.values())
    cols = 12

    # 用 CSS Grid 渲染
    cells_html = ""
    for cid, cfg in grid_cells.items():
        color = _chart_type_color(cfg['type'])
        icon = _chart_icon(cfg['type'])
        grid_col = cfg['col']
        grid_row = cfg['row']
        width = cfg['col_span']
        height = cfg['row_span']
        cells_html += f"""
        <div class="layout-cell" style="
            grid-column: {grid_col} / span {width};
            grid-row: {grid_row} / span {height};
            border-color: {color};
            background: {color}11;
        ">
          <div class="layout-cell-icon">{icon}</div>
          <div class="layout-cell-name">{escape(cfg['name'])}</div>
          <div class="layout-cell-type">{escape(cfg['type'])}</div>
          <div class="layout-cell-size">{width}x{height}</div>
        </div>"""

    return f"""
    <div class="layout-preview" style="grid-template-columns: repeat(12, 1fr); grid-template-rows: repeat({max_row}, 100px);">
      <div class="layout-grid-label">12 列网格布局</div>
      {cells_html}
    </div>"""


# ==================== Markdown 解析工具 ====================

def _extract_first_md_table(text: str) -> list:
    """提取第一个 Markdown 表格，返回二维列表"""
    tables = re.findall(r'(\|.+\|[\r\n]+\|[-| :]+\|[\r\n]+((?:\|.+\|[\r\n]*)+))', text)
    if not tables:
        return []
    return _parse_md_table(tables[0][0])


def _extract_md_table_by_header(text: str, required_headers: list, after_marker: str = "") -> list:
    """提取包含指定表头的 Markdown 表格
    
    Args:
        text: 待搜索的 Markdown 文本
        required_headers: 必须全部匹配的表头关键字列表
        after_marker: 可选的上下文锚点，只在此标记之后的文本中搜索
    """
    # 如果有锚点，先截取锚点之后的文本
    search_text = text
    if after_marker:
        marker_pos = text.find(after_marker)
        if marker_pos >= 0:
            search_text = text[marker_pos:]
    
    tables = re.findall(r'(\|.+\|[\r\n]+\|[-| :]+\|[\r\n]+((?:\|.+\|[\r\n]*)+))', search_text)
    for table_text in tables:
        parsed = _parse_md_table(table_text[0])
        if parsed and parsed[0]:
            header_lower = [h.lower().strip() for h in parsed[0]]
            # 改为 all 匹配：所有 required_headers 都必须在表头中
            if all(h.lower().strip() in header_lower for h in required_headers):
                return parsed
    return []


def _parse_md_table(text: str) -> list:
    """解析 Markdown 表格为二维列表"""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return []

    rows = []
    for line in lines:
        if re.match(r'^\|[-| :]+\|$', line):
            continue  # 跳过分隔行
        cells = [c.strip() for c in line.split('|')[1:-1]]  # 去掉首尾空元素
        rows.append(cells)
    return rows


def _extract_sql_blocks(text: str) -> list:
    """提取 SQL 代码块"""
    # 匹配 ````sql ... ```` 或 ```sql ... ```
    blocks = re.findall(r'```+sql\s*\n(.+?)```+', text, re.DOTALL)
    return [b.strip() for b in blocks]


def _extract_blockquote(text: str) -> str:
    """提取第一个 blockquote"""
    m = re.search(r'^>\s+(.+?)(?=\n[^>]|\Z)', text, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def _extract_bullet_list(text: str, start_after: str = "") -> list:
    """提取无序列表"""
    if start_after:
        m = re.search(rf'{re.escape(start_after)}\s*\n((?:[-*]\s+.+\n?)+)', text)
        if m:
            text = m.group(1)
        else:
            return []

    items = re.findall(r'^[-*]\s+(.+)$', text, re.MULTILINE)
    return [i.strip() for i in items]


def _extract_bold_list(text: str, bold_header: str) -> list:
    """提取粗体标题下的列表"""
    m = re.search(
        rf'\*\*{re.escape(bold_header)}\*\*[：:]?\s*\n((?:[-*]\s+.+\n?)+)',
        text
    )
    if not m:
        return []
    return re.findall(r'^[-*]\s+(.+)$', m.group(1), re.MULTILINE)


def _count_categories(table_data: list) -> dict:
    """统计各类别确认项数量"""
    counts = {}
    for row in table_data[1:]:
        if len(row) >= 2:
            cat = row[1]
            counts[cat] = counts.get(cat, 0) + 1
    return counts


# ==================== 文本格式化 ====================

def _highlight_sql(text: str) -> str:
    """简单的 SQL 语法高亮（在 HTML 上下文中使用）"""
    if not text:
        return ""
    # 转义后高亮
    text = escape(text)
    # SQL 关键字
    keywords = ['SELECT', 'FROM', 'WHERE', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN',
                'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT', 'ON', 'AND', 'OR', 'NOT',
                'AS', 'IN', 'BETWEEN', 'LIKE', 'IS', 'NULL', 'CASE', 'WHEN', 'THEN',
                'ELSE', 'END', 'SUM', 'COUNT', 'AVG', 'MAX', 'MIN', 'DISTINCT',
                'DATE', 'CURRENT_DATE', 'INTERVAL', 'DATE_ADD', 'LAG', 'NULLIF',
                'DESC', 'ASC', 'TOP', 'UNION', 'EXISTS']
    for kw in keywords:
        text = re.sub(rf'\b({kw})\b', rf'<span class="sql-kw">{kw}</span>', text)
    # 反引号包裹的字段名
    text = re.sub(r'`([^`]+)`', r'<span class="sql-field">`\1`</span>', text)
    return text


def _markdown_to_inline_html(text: str) -> str:
    """将简单的 Markdown 行内格式转为 HTML"""
    if not text:
        return ""
    text = escape(text)
    # 粗体
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 行内代码
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # 链接
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def _category_color(category: str) -> str:
    """根据确认项类别返回颜色变量名"""
    cat_map = {
        '指标口径': 'color-red',
        'SQL逻辑': 'color-orange',
        'JOIN方式': 'color-orange',
        '数据源': 'color-orange',
        '数据质量': 'color-yellow',
        '维度粒度': 'color-yellow',
        '过滤条件': 'color-blue',
        '图表类型': 'color-teal',
        '布局': 'color-teal',
        '交互': 'color-teal',
        '维度选择': 'color-yellow',
        '其他': 'color-gray',
    }
    return cat_map.get(category, 'color-gray')


def _chart_type_color(chart_type: str) -> str:
    """根据图表类型返回颜色"""
    type_map = {
        '指标卡片': '#a78bfa',
        '折线图': '#34d399',
        '柱状图': '#60a5fa',
        '条形图': '#38bdf8',
        '饼图': '#fb923c',
        '环形图': '#fb923c',
        '地图': '#4ade80',
        '数据表格': '#94a3b8',
        '矩形树图': '#f472b6',
    }
    return type_map.get(chart_type, '#94a3b8')


def _chart_icon(chart_type: str) -> str:
    """根据图表类型返回图标"""
    type_map = {
        '指标卡片': '🔢',
        '折线图': '📈',
        '柱状图': '📊',
        '条形图': '📊',
        '饼图': '🥧',
        '环形图': '🍩',
        '地图': '🗺️',
        '数据表格': '📋',
        '矩形树图': '🧩',
        'sql': '🏗️',
    }
    return type_map.get(chart_type, '📊')


def _quality_type_badge(qtype: str) -> str:
    """数据质量类型徽章"""
    type_map = {
        'NULL处理': '💡',
        '除零保护': '🛡️',
        '性能提示': '⚡',
        '数据重复': '🔄',
    }
    icon = type_map.get(qtype, '⚠️')
    return f'{icon} {escape(qtype)}'


# ==================== HTML 模板 ====================

def _wrap_in_html_template(body_html: str) -> str:
    """将渲染内容包裹在完整的 HTML 模板中"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>看板搭建方案</title>
<style>
{CSS_TEMPLATE}
</style>
</head>
<body>
<div class="report-container">
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="sidebar-logo">Agent</div>
      <div class="sidebar-title">看板搭建</div>
    </div>
    <nav class="sidebar-nav">
      <a href="#sec-overview" class="nav-item active">看板概述</a>
      <a href="#sec-semantic" class="nav-item">语义模型</a>
      <a href="#sec-layout" class="nav-item">布局方案</a>
      <a href="#sec-confirm" class="nav-item nav-warn">待确认项</a>
      <a href="#sec-steps" class="nav-item">搭建步骤</a>
      <a href="#sec-instruction" class="nav-item">看板指令</a>
    </nav>
    <div class="sidebar-footer">
      <p>人机协作</p>
      <p class="sidebar-footer-sub">Agent 生成 · 人工审核</p>
    </div>
  </aside>
  <main class="main-content">
    {body_html}
  </main>
</div>
<script>
{JS_TEMPLATE}
</script>
</body>
</html>"""


# ==================== CSS ====================

CSS_TEMPLATE = r"""
:root {
  --color-red: #f85149;
  --color-red-rgb: 248, 81, 73;
  --color-orange: #d29922;
  --color-orange-rgb: 210, 153, 34;
  --color-yellow: #e3b341;
  --color-yellow-rgb: 227, 179, 65;
  --color-blue: #58a6ff;
  --color-blue-rgb: 88, 166, 255;
  --color-teal: #3fb950;
  --color-teal-rgb: 63, 185, 80;
  --color-gray: #8b949e;
  --color-gray-rgb: 139, 148, 158;

  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #1c2333;
  --bg-card: #21262d;
  --border-default: #30363d;
  --border-muted: #21262d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --text-muted: #6e7681;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.6;
}

/* Layout */
.report-container {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 220px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-default);
  padding: 24px 0;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 0 20px 24px;
  border-bottom: 1px solid var(--border-default);
}
.sidebar-logo {
  display: inline-block;
  background: linear-gradient(135deg, #58a6ff, #3fb950);
  color: #fff;
  font-weight: 700;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 6px;
  margin-bottom: 8px;
  letter-spacing: 1px;
}
.sidebar-title {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
}

.sidebar-nav {
  padding: 16px 12px;
  flex: 1;
}
.nav-item {
  display: block;
  padding: 8px 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 4px;
  transition: all 0.2s;
}
.nav-item:hover {
  background: rgba(88, 166, 255, 0.08);
  color: var(--text-primary);
}
.nav-item.active {
  background: rgba(88, 166, 255, 0.12);
  color: #58a6ff;
}
.nav-warn {
  position: relative;
}
.nav-warn::after {
  content: '';
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-orange);
}

.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border-default);
  font-size: 12px;
  color: var(--text-muted);
}
.sidebar-footer-sub {
  font-size: 11px;
  margin-top: 2px;
}

.main-content {
  margin-left: 220px;
  flex: 1;
  padding: 40px 48px;
  max-width: 1100px;
}

/* Header */
.report-header {
  text-align: center;
  margin-bottom: 40px;
  padding-bottom: 32px;
  border-bottom: 1px solid var(--border-default);
}
.report-badge {
  display: inline-block;
  background: rgba(63, 185, 80, 0.1);
  color: var(--color-teal);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 20px;
  margin-bottom: 16px;
  border: 1px solid rgba(63, 185, 80, 0.2);
}
.report-title {
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
}
.report-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
}

/* TOC */
.report-toc {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 40px;
}
.toc-title {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  font-weight: 600;
}
.toc-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.toc-links a {
  color: #58a6ff;
  text-decoration: none;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 8px;
  background: rgba(88, 166, 255, 0.06);
  border: 1px solid rgba(88, 166, 255, 0.15);
  transition: all 0.2s;
}
.toc-links a:hover {
  background: rgba(88, 166, 255, 0.15);
}

/* Sections */
.report-section {
  margin-bottom: 48px;
}
.section-heading {
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--border-default);
  display: flex;
  align-items: center;
  gap: 12px;
}
.heading-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(88, 166, 255, 0.12);
  color: #58a6ff;
  font-size: 16px;
  font-weight: 700;
}

/* Info cards */
.info-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.info-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 16px 20px;
}
/* 信息卡片颜色变体（根据标签名自动匹配） */
.info-card-default { border-left: 3px solid var(--text-muted); }
.info-card-blue {
  border-left: 3px solid #58a6ff;
  background: rgba(88, 166, 255, 0.05);
}
.info-card-purple {
  border-left: 3px solid #d2a8ff;
  background: rgba(210, 168, 255, 0.05);
}
.info-card-green {
  border-left: 3px solid #3fb950;
  background: rgba(63, 185, 80, 0.05);
}
.info-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.info-value {
  font-size: 15px;
  color: var(--text-primary);
  font-weight: 500;
}

/* Question list */
.question-list {
  list-style: none;
  padding: 0;
}
.question-list li {
  padding: 8px 0 8px 20px;
  position: relative;
  font-size: 14px;
  color: var(--text-secondary);
}
.question-list li::before {
  content: '?';
  position: absolute;
  left: 0;
  color: #58a6ff;
  font-weight: 700;
  font-size: 12px;
}

/* Tags */
.tag-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.data-source-tag {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 8px;
  background: rgba(88, 166, 255, 0.08);
  border: 1px solid rgba(88, 166, 255, 0.2);
  color: #79c0ff;
  font-size: 13px;
}

/* Tables */
.table-wrapper {
  overflow-x: auto;
  border-radius: 10px;
  border: 1px solid var(--border-default);
}
.styled-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.styled-table th {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}
.styled-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-muted);
  color: var(--text-primary);
  vertical-align: top;
}
.styled-table tbody tr:hover {
  background: rgba(88, 166, 255, 0.04);
}
.styled-table tbody tr:last-child td {
  border-bottom: none;
}
.code-cell {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  color: #d2a8ff;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Type/Status badges */
.type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(88, 166, 255, 0.1);
  color: #79c0ff;
}
.type-badge:contains("复合") {
  background: rgba(210, 153, 34, 0.1);
  color: #e3b341;
}
.status-ok {
  color: var(--color-teal) !important;
}
.status-warn {
  color: var(--color-orange) !important;
}
.status-badge {
  font-weight: 600;
}

/* Subsections */
.section-block {
  margin-bottom: 24px;
}
.section-block h3, .subsection h3, .subsection h4 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

/* Model card */
.model-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 16px;
  overflow: hidden;
  margin-bottom: 24px;
}
.model-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-default);
}
.model-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  background: rgba(63, 185, 80, 0.1);
  flex-shrink: 0;
}
.model-header h3 {
  font-size: 16px;
  color: #fff;
  font-weight: 700;
}
.model-purpose {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.model-sql-area {
  padding: 20px 24px;
}

/* SQL block */
.sql-block {
  margin-bottom: 16px;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  overflow: hidden;
}
.sql-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
}
.sql-icon {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 600;
}
.copy-btn {
  background: none;
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.copy-btn:hover {
  background: rgba(88, 166, 255, 0.1);
  color: #58a6ff;
  border-color: rgba(88, 166, 255, 0.3);
}
.sql-code {
  background: var(--bg-primary);
  padding: 16px 18px;
  overflow-x: auto;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12.5px;
  line-height: 1.7;
  color: #c9d1d9;
  margin: 0;
}
.sql-kw { color: #ff7b72; font-weight: 600; }
.sql-field { color: #d2a8ff; }
.sql-notes {
  background: rgba(88, 166, 255, 0.06);
  border: 1px solid rgba(88, 166, 255, 0.12);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 8px;
}
.sql-notes strong {
  color: var(--text-primary);
}

/* Filter section */
.filter-level-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  margin-left: 8px;
  vertical-align: middle;
}
.level-sql {
  background: rgba(255, 123, 114, 0.1);
  color: #ff7b72;
}
.level-chart {
  background: rgba(88, 166, 255, 0.1);
  color: #58a6ff;
}
.level-metric {
  background: rgba(210, 153, 34, 0.1);
  color: #d29922;
}
.filter-list-text {
  list-style: none;
  padding: 0;
}
.filter-list-text li {
  padding: 6px 0 6px 16px;
  font-size: 13px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-muted);
}
.filter-list-text li:last-child {
  border-bottom: none;
}

/* Quality list */
.quality-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.quality-item {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-tertiary);
  border-radius: 8px;
}
.quality-type {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  padding-top: 2px;
}
.quality-detail {
  flex: 1;
  font-size: 13px;
  color: var(--text-secondary);
}
.quality-detail p {
  margin-bottom: 4px;
}
.quality-suggest {
  font-size: 12px;
  color: var(--text-muted);
}

/* Layout preview */
.layout-description {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}
.layout-preview {
  display: grid;
  gap: 8px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  margin-bottom: 8px;
  position: relative;
}
.layout-grid-label {
  grid-column: 1 / -1;
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  padding-top: 4px;
}
.layout-cell {
  border: 2px dashed;
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 4px;
  transition: all 0.2s;
  min-height: 0;
}
.layout-cell:hover {
  transform: scale(1.02);
  z-index: 1;
}
.layout-cell-icon {
  font-size: 20px;
}
.layout-cell-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.layout-cell-type {
  font-size: 11px;
  color: var(--text-muted);
}
.layout-cell-size {
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.6;
}

/* Chart cards */
.chart-cards-grid {
  display: grid;
  gap: 16px;
}
.chart-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.2s;
}
.chart-card:hover {
  border-color: rgba(63, 185, 80, 0.3);
}
.chart-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-default);
}
.chart-type-badge {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.chart-card-header h4 {
  font-size: 14px;
  color: #fff;
  font-weight: 600;
}
.chart-card-body {
  padding: 16px 18px;
}
.chart-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.chart-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.meta-label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.meta-value {
  font-size: 13px;
  color: var(--text-secondary);
}
.meta-value.code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  color: #d2a8ff;
}
.chart-interaction {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.interaction-tag {
  background: rgba(63, 185, 80, 0.1);
  color: var(--color-teal);
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 11px;
}
.chart-design-notes {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 6px;
}

/* Global filters */
.filter-list {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.filter-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-default);
}
.filter-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.filter-type {
  font-size: 11px;
  color: var(--text-muted);
}

/* Confirm section */
.confirm-section {
  background: rgba(248, 81, 73, 0.02);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid rgba(248, 81, 73, 0.1);
}
.confirm-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 14px 20px;
  text-align: center;
  min-width: 80px;
}
.stat-number {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-orange);
}
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.confirm-tip {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 20px;
  padding: 10px 14px;
  background: rgba(210, 153, 34, 0.06);
  border-radius: 8px;
  border-left: 3px solid var(--color-orange);
}
.confirm-cards-grid {
  display: grid;
  gap: 12px;
}
.confirm-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-left: 4px solid;
  border-radius: 0 10px 10px 0;
  padding: 16px 18px;
  transition: all 0.2s;
}
.confirm-card:hover {
  transform: translateX(4px);
}
.confirm-card-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.confirm-index {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
}
.confirm-category {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 4px;
}
.confirm-content {
  font-size: 14px;
  color: var(--text-primary);
  margin-bottom: 6px;
  font-weight: 500;
}
.confirm-risk {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.confirm-suggest {
  font-size: 12px;
  color: var(--text-muted);
  padding: 6px 10px;
  background: rgba(63, 185, 80, 0.06);
  border-radius: 6px;
  margin-bottom: 8px;
}
.confirm-suggest strong {
  color: var(--color-teal);
}
.confirm-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px 0;
}
.confirm-check input[type="checkbox"] {
  accent-color: var(--color-teal);
}

/* Steps timeline */
.steps-timeline {
  position: relative;
  padding-left: 40px;
}
.steps-timeline::before {
  content: '';
  position: absolute;
  left: 16px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--border-default);
}
.step-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
  position: relative;
}
.step-item:last-child {
  margin-bottom: 0;
}
.step-num {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(88, 166, 255, 0.12);
  color: #58a6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  flex-shrink: 0;
  position: absolute;
  left: -40px;
}
.step-content {
  flex: 1;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 14px 18px;
}
.step-content strong {
  color: var(--text-primary);
  font-size: 14px;
}
.step-content p {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* Instruction section */
.instruction-header {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.info-tag {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
}
.info-tag.primary {
  background: rgba(88, 166, 255, 0.1);
  border-color: rgba(88, 166, 255, 0.3);
  color: #58a6ff;
}
.instruction-summary {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 20px;
  font-size: 13px;
  color: var(--text-secondary);
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.chart-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  overflow: hidden;
}
.chart-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(88, 166, 255, 0.06);
  border-bottom: 1px solid var(--border-default);
}
.chart-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(88, 166, 255, 0.15);
  color: #58a6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.chart-title {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.chart-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(139, 148, 158, 0.15);
  color: var(--text-muted);
}
.chart-body {
  padding: 10px 14px;
}
.chart-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 4px;
}
.chart-label {
  color: var(--text-muted);
  min-width: 60px;
  flex-shrink: 0;
}
.chart-value {
  color: var(--text-secondary);
  word-break: break-all;
}
.chart-extra {
  display: inline-block;
  margin: 4px 4px 0 0;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-muted);
}
.filters-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.filter-tag {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 12px;
  background: rgba(255, 166, 88, 0.1);
  border: 1px solid rgba(255, 166, 88, 0.3);
  color: #ffa658;
}
.layout-section {
  margin-top: 16px;
}
.layout-block {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.layout-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  font-size: 12px;
}
.layout-label {
  color: var(--text-muted);
}
.layout-value {
  color: var(--text-primary);
  font-weight: 600;
}
.layout-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 6px;
}
.json-source {
  margin-top: 16px;
}
.json-source details {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  overflow: hidden;
}
.json-source summary {
  padding: 8px 14px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-muted);
}
.json-source pre {
  margin: 0;
  padding: 12px 14px;
  border-top: 1px solid var(--border-default);
  overflow-x: auto;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-primary);
}
.json-source pre code {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11px;
  background: none;
  padding: 0;
  color: var(--text-secondary);
}

/* Footer */
.report-footer {
  text-align: center;
  padding: 32px 0;
  border-top: 1px solid var(--border-default);
  color: var(--text-muted);
  font-size: 13px;
}

/* Responsive */
@media (max-width: 900px) {
  .sidebar { display: none; }
  .main-content { margin-left: 0; padding: 24px 16px; }
  .confirm-stats { flex-wrap: wrap; }
  .info-cards-grid { grid-template-columns: 1fr; }
}
"""


# ==================== JavaScript ====================

JS_TEMPLATE = r"""
// Copy SQL
function copySql(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.textContent || el.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = el.closest('.sql-block').querySelector('.copy-btn');
    const orig = btn.textContent;
    btn.textContent = '已复制';
    btn.style.color = '#3fb950';
    btn.style.borderColor = 'rgba(63, 185, 80, 0.3)';
    setTimeout(() => {
      btn.textContent = orig;
      btn.style.color = '';
      btn.style.borderColor = '';
    }, 2000);
  });
}

// Sidebar active state on scroll
const sections = document.querySelectorAll('.report-section');
const navItems = document.querySelectorAll('.nav-item');

const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      navItems.forEach(item => item.classList.remove('active'));
      const id = entry.target.id;
      const activeNav = document.querySelector(`.nav-item[href="#${id}"]`);
      if (activeNav) activeNav.classList.add('active');
    }
  });
}, { rootMargin: '-20% 0px -70% 0px' });

sections.forEach(section => observer.observe(section));

// Smooth scroll
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function(e) {
    e.preventDefault();
    const target = document.querySelector(this.getAttribute('href'));
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});
"""
