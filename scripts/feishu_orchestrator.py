"""
飞书看板助手 - 编排服务（长连接模式）

完整链路：飞书群 @机器人 → SDK长连接 → 意图识别 → dashboard-agent Pipeline → 结果推回飞书群

优势：无需内网穿透、无需公网URL，SDK通过WebSocket主动连接飞书服务器

启动方式：
    # 方式1：使用 .env 文件（推荐）
    cp .env.example .env    # 编辑 .env 填入凭证
    python feishu_orchestrator.py

    # 方式2：手动设置环境变量
    $env:FEISHU_APP_ID = "cli_a5xxxxxxxxxxxxx"
    $env:FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    python feishu_orchestrator.py

依赖：
    pip install lark-oapi requests
"""

import os
import sys
import json
import time
import re
import tempfile
import threading
import traceback
import atexit
from pathlib import Path
from typing import Optional

# Windows UTF-8 兼容：确保 print() 能输出中文和 emoji
if sys.platform == "win32":
    os.system("")  # 启用 ANSI 转义
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 添加项目根目录到 Python 路径
SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))  # nl_converter.py 在 scripts/ 下

# 自动加载 .env 文件（如果存在）
_env_file = SCRIPTS_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
    print(f"[CONFIG] 已加载 .env 文件: {_env_file}")

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import *
    import requests
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请安装: pip install lark-oapi requests")
    sys.exit(1)


# ============================================================
# 配置
# ============================================================

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# Pipeline 路径
PIPELINE_SCRIPT = str(SCRIPTS_DIR / "run_pipeline.py")
PIPELINE_CWD = str(PROJECT_ROOT)

# 意图识别关键词
DASHBOARD_KEYWORDS = ["看板", "dashboard", "数据看板", "分析看板", "报表看板", "BI看板"]
REVISION_KEYWORDS = ["修改", "改成", "换成", "调整", "增加指标", "删除指标"]

# 飞书 API
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

# HTTP 调用超时（秒）
HTTP_TIMEOUT = int(os.getenv("FEISHU_HTTP_TIMEOUT", "15"))

# Token 缓存（SDK 内部也管理 token，这里用于手动 API 调用）
_token_cache = {"token": "", "expire_at": 0}
_token_lock = threading.Lock()

# 进度卡片更新节流：避免短时间内多次 PATCH 触发飞书频控
PROGRESS_UPDATE_MIN_INTERVAL = float(os.getenv("PROGRESS_UPDATE_MIN_INTERVAL", "1.0"))

# Agent 中文名映射（与 Pipeline.AGENT_DISPLAY_NAMES 保持一致）
AGENT_DISPLAY_NAMES = {
    "requirements_parser": "需求解析",
    "semantic_model": "语义模型",
    "bi_push": "BI 推送",
    "chart_design": "图表设计",
    "instruction_generator": "看板指令",
    "solution_generator": "方案生成",
}

# Agent 执行图标
AGENT_ICONS = {
    "requirements_parser": "📋",
    "semantic_model": "🔧",
    "bi_push": "📤",
    "chart_design": "📊",
    "instruction_generator": "📝",
    "solution_generator": "📄",
}

# Pipeline Agent 执行顺序（与 agents.PIPELINE_ORDER 保持一致）
PIPELINE_ORDER = [
    "requirements_parser",
    "semantic_model",
    "bi_push",
    "chart_design",
    "instruction_generator",
    "solution_generator",
]


# ============================================================
# 飞书鉴权（手动 API 调用用，SDK 调用不需要）
# ============================================================

def get_tenant_token_sync() -> str:
    """同步获取飞书 tenant_access_token（带缓存，线程安全）"""
    with _token_lock:
        now = time.time()
        if _token_cache["token"] and now < _token_cache["expire_at"]:
            return _token_cache["token"]

        resp = requests.post(
            f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=HTTP_TIMEOUT,
        )
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

        _token_cache["token"] = data["tenant_access_token"]
        _token_cache["expire_at"] = now + data.get("expire", 7200) - 300
        print(f"[AUTH] tenant_access_token 获取成功")
        return _token_cache["token"]


# ============================================================
# 飞书消息 API（同步版本，在子线程中使用）
# ============================================================

def reply_text_sync(chat_id: str, text: str):
    """同步发送文本消息到飞书群"""
    try:
        token = get_tenant_token_sync()
        resp = requests.post(
            f"{FEISHU_API_BASE}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=HTTP_TIMEOUT,
        )
        result = resp.json()
        if result.get("code") != 0:
            print(f"[WARN] 发送消息失败: {result}")
        else:
            print(f"[MSG] 消息已发送到群 {chat_id[:8]}...")
        return result
    except requests.RequestException as e:
        print(f"[WARN] 发送消息异常: {e}")
        return {"code": -1, "msg": str(e)}


def send_completion_card_sync(
    chat_id: str,
    title: str,
    duration_ms: int = 0,
    step_count: int = 0,
    confirmation_count: int = 0,
):
    """
    发送看板生成完成的简洁通知卡片（不含完整方案正文）

    Args:
        chat_id: 群聊 ID
        title: 看板方案标题
        duration_ms: Pipeline 总耗时（毫秒）
        step_count: 完成的步骤数
        confirmation_count: 待人工确认项数量
    """
    token = get_tenant_token_sync()

    duration_min = duration_ms / 60000 if duration_ms else 0
    duration_str = f"{duration_min:.1f} 分钟" if duration_min >= 1 else f"{duration_ms / 1000:.1f} 秒"

    lines = [
        f"**📋 看板标题**：{title}",
        "",
        f"**⏱️ 总耗时**：{duration_str}",
    ]
    if step_count:
        lines.append(f"**🔢 完成步骤**：{step_count} / 6")
    if confirmation_count:
        lines.append("")
        lines.append(f"⚠️ **待确认项**：{confirmation_count} 处（详见 Markdown 附件中标注）")
    lines.append("")
    lines.append("📎 完整方案已作为附件发送：")
    lines.append("- **Markdown 文档**：便于复制编辑")
    lines.append("- **HTML 文档**：便于直接浏览")

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "✅ 看板方案生成完成"},
            "template": "green",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"}
                ],
            },
        ],
    }

    try:
        resp = requests.post(
            f"{FEISHU_API_BASE}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card),
            },
            timeout=HTTP_TIMEOUT,
        )
        result = resp.json()
        if result.get("code") != 0:
            print(f"[WARN] 发送卡片失败: {result}")
        else:
            print(f"[MSG] 卡片消息已发送到群 {chat_id[:8]}...")
        return result
    except requests.RequestException as e:
        print(f"[WARN] 发送卡片异常: {e}")
        return {"code": -1, "msg": str(e)}


def send_progress_card_sync(chat_id: str, title: str, progress_info: dict) -> dict:
    """
    发送/更新进度卡片消息到飞书群

    进度卡片包含：
    - 当前正在执行的 Agent
    - 已完成的 Agent 列表
    - 总体进度条

    Args:
        chat_id: 群聊 ID
        title: 卡片标题
        progress_info: 进度信息，结构：
            {
                "current_agent": "semantic_model",
                "current_display": "语义模型",
                "step_index": 1,
                "total_steps": 6,
                "completed": [{"agent": "requirements_parser", "duration_ms": 12000}],
                "error": None,  # 如果有错误
                "start_time": 1715600000.0,  # Pipeline 开始时间
            }

    Returns:
        飞书 API 响应 dict
    """
    token = get_tenant_token_sync()

    completed = progress_info.get("completed", [])
    step_index = progress_info.get("step_index", 0)
    total_steps = progress_info.get("total_steps", len(PIPELINE_ORDER))
    error = progress_info.get("error")
    start_time = progress_info.get("start_time", time.time())
    elapsed = int(time.time() - start_time)
    elapsed_min = elapsed // 60
    elapsed_sec = elapsed % 60

    # 构建进度条文本
    progress_pct = int((step_index / total_steps) * 100) if total_steps > 0 else 0
    filled = int(progress_pct / 10)
    # 用 emoji 方块代替 unicode 字符，飞书会按 emoji 自带颜色渲染（不会变黑）
    bar = "🟦" * filled + "⬜" * (10 - filled)

    # 构建已完成列表
    completed_lines = []
    for item in completed:
        agent = item.get("agent", "?")
        icon = AGENT_ICONS.get(agent, "✅")
        display = AGENT_DISPLAY_NAMES.get(agent, agent)
        duration_s = item.get("duration_ms", 0) / 1000
        completed_lines.append(f"{icon} ~~{display}~~ ({duration_s:.1f}s)")

    # 当前步骤
    current_agent = progress_info.get("current_agent", "")
    current_display = progress_info.get("current_display", "")
    current_icon = AGENT_ICONS.get(current_agent, "⏳")

    # 构建 markdown 内容
    lines = [f"**进度** {bar} {progress_pct}%"]
    lines.append(f"**耗时** {elapsed_min}分{elapsed_sec:02d}秒")
    lines.append("")

    # 已完成的步骤
    if completed_lines:
        lines.append("**已完成：**")
        lines.extend(completed_lines)
        lines.append("")

    # 当前步骤
    if current_agent and not error:
        lines.append(f"**正在执行：** {current_icon} {current_display} ...")
    elif error:
        lines.append(f"**❌ 执行失败：** {error[:100]}")

    card = {
        "config": {"update_multi": True},  # 必须，否则无法 PATCH 更新
        "header": {
            "title": {"tag": "plain_text", "content": f"🚀 {title}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"更新时间: {time.strftime('%H:%M:%S')}"}
                ],
            },
        ],
    }

    try:
        resp = requests.post(
            f"{FEISHU_API_BASE}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card),
            },
            timeout=HTTP_TIMEOUT,
        )
        result = resp.json()
        if result.get("code") != 0:
            print(f"[WARN] 发送进度卡片失败: {result}")
        else:
            print(f"[MSG] 进度卡片已发送到群 {chat_id[:8]}...")
        return result
    except requests.RequestException as e:
        print(f"[WARN] 发送进度卡片异常: {e}")
        return {"code": -1, "msg": str(e)}


def update_progress_card_sync(message_id: str, title: str, progress_info: dict):
    """
    更新已有的进度卡片消息

    通过 PATCH API 更新卡片内容，避免发新消息刷屏

    Args:
        message_id: 要更新的消息 ID
        title: 卡片标题
        progress_info: 进度信息（同 send_progress_card_sync）
    """
    token = get_tenant_token_sync()

    completed = progress_info.get("completed", [])
    step_index = progress_info.get("step_index", 0)
    total_steps = progress_info.get("total_steps", len(PIPELINE_ORDER))
    error = progress_info.get("error")
    start_time = progress_info.get("start_time", time.time())
    elapsed = int(time.time() - start_time)
    elapsed_min = elapsed // 60
    elapsed_sec = elapsed % 60

    # 构建进度条
    progress_pct = int((step_index / total_steps) * 100) if total_steps > 0 else 0
    filled = int(progress_pct / 10)
    # 用 emoji 方块代替 unicode 字符，飞书会按 emoji 自带颜色渲染（不会变黑）
    bar = "🟦" * filled + "⬜" * (10 - filled)

    # 构建已完成列表
    completed_lines = []
    for item in completed:
        agent = item.get("agent", "?")
        icon = AGENT_ICONS.get(agent, "✅")
        display = AGENT_DISPLAY_NAMES.get(agent, agent)
        duration_s = item.get("duration_ms", 0) / 1000
        completed_lines.append(f"{icon} ~~{display}~~ ({duration_s:.1f}s)")

    # 当前步骤
    current_agent = progress_info.get("current_agent", "")
    current_display = progress_info.get("current_display", "")
    current_icon = AGENT_ICONS.get(current_agent, "⏳")

    # 构建 markdown 内容
    lines = [f"**进度** {bar} {progress_pct}%"]
    lines.append(f"**耗时** {elapsed_min}分{elapsed_sec:02d}秒")
    lines.append("")

    if completed_lines:
        lines.append("**已完成：**")
        lines.extend(completed_lines)
        lines.append("")

    if current_agent and not error:
        lines.append(f"**正在执行：** {current_icon} {current_display} ...")
    elif error:
        lines.append(f"**❌ 执行失败：** {error[:100]}")

    card = {
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🚀 {title}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"更新时间: {time.strftime('%H:%M:%S')}"}
                ],
            },
        ],
    }

    try:
        resp = requests.patch(
            f"{FEISHU_API_BASE}/im/v1/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            json={"content": json.dumps(card)},
            timeout=HTTP_TIMEOUT,
        )
        result = resp.json()
        if result.get("code") != 0:
            print(f"[WARN] 更新进度卡片失败: {result}")
        else:
            print(f"[MSG] 进度卡片已更新: {message_id[:8]}...")
        return result
    except requests.RequestException as e:
        print(f"[WARN] 更新进度卡片异常: {e}")
        return {"code": -1, "msg": str(e)}


def upload_file_to_chat_sync(chat_id: str, file_path: str, file_name: str = None):
    """同步上传文件到飞书群"""
    token = get_tenant_token_sync()
    if not file_name:
        file_name = Path(file_path).name

    # 文件上传需要更长超时（文件可能较大）
    upload_timeout = max(HTTP_TIMEOUT, 60)

    try:
        # Step 1: 上传文件
        # 飞书文件上传 API: file_type=stream 为通用文件流
        # 注意: params 和 files 的格式必须严格符合飞书要求
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{FEISHU_API_BASE}/im/v1/files",
                headers={"Authorization": f"Bearer {token}"},
                data={"file_type": "stream", "file_name": file_name},
                files={"file": (file_name, f, "application/octet-stream")},
                timeout=upload_timeout,
            )
        upload_result = resp.json()

        if upload_result.get("code") != 0:
            print(f"[WARN] 上传文件失败: {upload_result}")
            return

        file_key = upload_result["data"]["file_key"]

        # Step 2: 发送文件消息
        resp = requests.post(
            f"{FEISHU_API_BASE}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}),
            },
            timeout=HTTP_TIMEOUT,
        )
        result = resp.json()
        if result.get("code") != 0:
            print(f"[WARN] 发送文件消息失败: {result}")
        else:
            print(f"[MSG] 文件已发送到群 {chat_id[:8]}...")
    except requests.RequestException as e:
        print(f"[WARN] 上传/发送文件异常: {e}")


# ============================================================
# 错误信息友好化（业务用户视角）
# ============================================================

# Agent 名 → 业务环节中文（用于错误时定位"哪一步失败"）
_FAILED_STEP_DESCRIPTIONS = {
    "requirements_parser": "需求解析",
    "semantic_model": "语义模型 / SQL 校验",
    "bi_push": "BI 推送",
    "chart_design": "图表设计",
    "instruction_generator": "看板指令",
    "solution_generator": "方案文档生成",
}

# 错误模式 → (短摘要, 友好详细提示)
# 短摘要用于进度卡片（≤30 字），详细提示用于飞书文本消息
# 占位符 {tgt} 表示从原始错误中捕获的对象（如表名、字段名）
_ERROR_PATTERNS = [
    # ---- 数据平台相关 ----
    (
        re.compile(r"(?:Table or view not found|表\s*\S*\s*不存在|relation\s+\S+\s+does not exist|无法找到表)[:\s]*([^\s,，（()。]+)?", re.I),
        "找不到数据表",
        (
            "📍 **找不到数据表 {tgt}**\n"
            "可能原因：\n"
            "• 表名拼写错误\n"
            "• 表不在配置的 catalog/schema 下\n"
            "• 没有该表的访问权限\n"
            "建议：\n"
            "• 在需求里使用完整的三段式表名（如 `catalog.schema.table`）\n"
            "• 联系数据 owner 确认权限"
        ),
    ),
    (
        re.compile(r"(?:cannot resolve|column\s+\S*\s*does not exist|Unknown column|找不到列|无法识别字段)[\s'`\"]*([A-Za-z_][\w\.]*)?", re.I),
        "字段不存在",
        (
            "📍 **字段 {tgt} 不存在**\n"
            "可能原因：\n"
            "• 字段名拼写错误\n"
            "• 字段不在所选表里\n"
            "• 字段在 JOIN 之后才出现，引用时需带表别名\n"
            "建议：\n"
            "• 在需求里明确指定要使用的字段及其所属表\n"
            "• 提供准确的字段清单"
        ),
    ),
    (
        re.compile(r"(?:mismatched input|Syntax error|Parse error|cannot parse|SQL\s*syntax)", re.I),
        "SQL 语法错误",
        (
            "📍 **生成的 SQL 语法不规范**\n"
            "原因：LLM 多次生成的 SQL 都未通过语法校验。\n"
            "建议：\n"
            "• 简化业务需求描述后重试\n"
            "• 在需求里明确字段、过滤条件、分组维度\n"
            "• 多次失败请联系研发"
        ),
    ),
    (
        re.compile(r"(?:data type mismatch|cannot be cast|type.*mismatch|类型.*不匹配)", re.I),
        "字段类型不匹配",
        (
            "📍 **字段类型不匹配**\n"
            "可能原因：\n"
            "• 对字符串字段使用了 SUM/AVG 等数值聚合\n"
            "• JOIN 字段的类型不一致（如 string 关联 bigint）\n"
            "建议：\n"
            "• 在需求里明确指标字段的数据类型\n"
            "• 提示哪些字段是金额/数量、哪些是分类标签"
        ),
    ),
    (
        re.compile(r"(?:错误码[:：\s]*4007402|AuthenticationError|认证失败|unauthorized|access denied)", re.I),
        "数据平台认证失败",
        (
            "🔒 **数据平台认证失败**\n"
            "原因：token 失效或权限不足。\n"
            "建议：\n"
            "• 联系管理员检查 `config.json` 中的 `data_platform.token`\n"
            "• 确认应用账号已被授予对应库表的查询权限"
        ),
    ),
    (
        re.compile(r"(?:错误码[:：\s]*CONNECTION|网络连接异常|connection.*(?:refused|timeout)|无法连接)", re.I),
        "数据平台连接失败",
        (
            "🌐 **数据平台连接失败**\n"
            "请稍后重试。多次失败请联系运维确认数据平台可用性。"
        ),
    ),
    (
        re.compile(r"(?:错误码[:：\s]*TIMEOUT|查询超时|timed?\s*out)", re.I),
        "SQL 执行超时",
        (
            "⏱️ **SQL 执行超时**\n"
            "可能原因：数据量过大或集群繁忙。\n"
            "建议：\n"
            "• 在需求里限定时间范围（如近 7 天）\n"
            "• 缩小分析维度的粒度\n"
            "• 稍后重试"
        ),
    ),
    # ---- LLM 相关 ----
    (
        re.compile(r"(?:rate.?limit|429\b|too many requests|频率限制)", re.I),
        "LLM 调用被限流",
        (
            "⚡ **LLM 调用被限流**\n"
            "原因：短时间内请求过多。\n"
            "建议：\n"
            "• 等几分钟后重试\n"
            "• 多次失败请联系研发调整配额"
        ),
    ),
    (
        re.compile(r"(?:JSON.*decode|invalid json|json.*parse|输出格式不正确)", re.I),
        "模型输出格式错误",
        (
            "📦 **模型输出 JSON 格式错误**\n"
            "原因：LLM 返回了不符合 schema 的内容。\n"
            "建议：\n"
            "• 重试一次（多数情况是模型偶发抖动）\n"
            "• 多次失败请联系研发更换或调整模型"
        ),
    ),
    # ---- 业务 schema 校验失败（语义模型 Agent.validate_output） ----
    (
        re.compile(
            r"(?:衍生指标.*必须有\s*depends_on|缺少\s*sql\s*字段|"
            r"至少需要\s*\d*\s*个\s*(?:维度|指标|semantic_model)|"
            r"维度和指标.*重复字段)",
            re.I,
        ),
        "模型输出 schema 不规范",
        (
            "📐 **模型输出的语义模型缺字段或字段重复**\n"
            "原因：LLM 多次生成的 JSON 都没完全遵循输出规范，可能漏掉了如 `depends_on`、`sql`、`metrics` 等必填字段，或维度/指标字段名互相冲突。\n"
            "建议：\n"
            "• 重试一次（模型偶发抖动，多数情况下能恢复）\n"
            "• 简化需求或减少同一看板里的指标数量\n"
            "• 多次失败请联系研发更换更稳定的模型"
        ),
    ),
]


def humanize_pipeline_error(raw_error: str, failed_step: str = "") -> tuple[str, str]:
    """
    把 Pipeline 抛出的技术错误信息翻译成对业务用户友好的语言。

    Args:
        raw_error: Pipeline 原始错误字符串（含错误码、堆栈、SQL 错误等）
        failed_step: 失败的 Agent 名（如 "semantic_model"），用于定位环节

    Returns:
        (short, full):
          - short：≤30 字的简短摘要，用于进度卡片
          - full：多行的完整建议，用于飞书文本消息
    """
    if not raw_error:
        return ("生成失败，原因未知", "❌ 看板生成失败，原因未知。请稍后重试。")

    step_label = _FAILED_STEP_DESCRIPTIONS.get(failed_step, "")
    matched = []  # [(short, full_with_target)]
    seen_shorts = set()

    for pattern, short, advice_tpl in _ERROR_PATTERNS:
        m = pattern.search(raw_error)
        if not m:
            continue
        if short in seen_shorts:
            continue
        seen_shorts.add(short)
        captured = ""
        if m.lastindex:
            captured = (m.group(1) or "").strip("\"'`，。()（）;,； ")
        tgt_str = f"`{captured}`" if captured else "（未识别到具体名称）"
        full = advice_tpl.replace("{tgt}", tgt_str)
        matched.append((short, full))

    if matched:
        # 短摘要：取第一条（最先匹配）；多个错误用 "+ N" 标注
        first_short = matched[0][0]
        if len(matched) > 1:
            short_summary = f"{first_short} 等 {len(matched)} 类错误"
        else:
            short_summary = first_short

        # 完整建议：拼接所有匹配的建议
        full_lines = ["❌ **看板生成失败**"]
        if step_label:
            full_lines.append(f"失败环节：**{step_label}**")
        full_lines.append("")
        for _, full in matched:
            full_lines.append(full)
            full_lines.append("")
        full_lines.append("💡 调整后可重新发起需求；多次失败请联系研发。")
        full_text = "\n".join(full_lines).strip()
        return (short_summary, full_text)

    # 未匹配到已知模式：保留原始错误，但加业务化外壳
    safe_raw = raw_error.strip()
    if len(safe_raw) > 400:
        safe_raw = safe_raw[:400] + "..."
    short_summary = f"{step_label}失败" if step_label else "生成失败"
    full_text = (
        f"❌ **看板生成失败**\n"
        + (f"失败环节：**{step_label}**\n" if step_label else "")
        + "\n"
        + f"原始错误：\n```\n{safe_raw}\n```\n\n"
        + "💡 你可以尝试：\n"
        + "• 调整需求描述后重试\n"
        + "• 多次失败请联系研发"
    )
    return (short_summary, full_text)


# ============================================================
# 意图识别
# ============================================================

def classify_intent(text: str) -> str:
    """分类用户意图"""
    if any(kw in text for kw in DASHBOARD_KEYWORDS):
        if any(kw in text for kw in REVISION_KEYWORDS):
            return "revise"
        return "dashboard"
    return "unknown"


# ============================================================
# Pipeline 进程内调用（带实时进度推送）
# ============================================================

# 运行中的群（同一群同时只允许一个任务）
_running_chats: set = set()
_tasks_lock = threading.Lock()

# 已处理的 message_id（防止飞书事件重发重复触发）
_processed_message_ids: set = set()
_processed_message_lock = threading.Lock()
_PROCESSED_MAX_SIZE = 1000

# 当前进行中的进度卡片（chat_id → {message_id, natural_input, progress_info, progress_card_id}）
# 退出钩子会用它把停留在中间状态的卡片改为"已中止"，避免飞书侧卡片永远停留
_active_progress_cards: dict = {}
_active_cards_lock = threading.Lock()


def _prepare_user_input(natural_input: str, mode: str) -> dict:
    """
    准备 Pipeline 输入数据

    复用 run_pipeline.py 中的逻辑：NLConverter 转换 + 配置合并 + 模式判断
    """
    from nl_converter import NLConverter

    # 加载配置
    config_path = SCRIPTS_DIR / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    llm_config = config.get("llm", {})
    dp_config = config.get("data_platform", {})

    # NLConverter 转换
    converter = NLConverter(llm_config, dp_config)
    user_input = converter.convert(natural_input)

    # 数据平台配置合并
    data_platform_config = {
        "base_url": dp_config.get("base_url") or os.getenv("DATA_PLATFORM_BASE_URL") or "",
        "catalog": dp_config.get("catalog") or "",
        "schema": dp_config.get("schema") or "",
        "engine": dp_config.get("engine") or "Spark",
        "token": dp_config.get("token") or os.getenv("DATA_PLATFORM_TOKEN") or "",
    }

    if "data_platform_config" not in user_input:
        user_input["data_platform_config"] = data_platform_config
    else:
        for key in data_platform_config:
            if not user_input["data_platform_config"].get(key):
                user_input["data_platform_config"][key] = data_platform_config[key]

    # BI 推送模式判断
    bi_config = user_input.get("bi_config")

    # 检查 NLConverter 的 _mode_hint
    mode_hint = user_input.pop("_mode_hint", None)

    if mode == "publish":
        bi_platform = config.get("bi_platform", {})
        bi_config = {
            "base_url": bi_platform.get("base_url"),
            "space_id": bi_platform.get("space_id"),
            "creator": bi_platform.get("creator"),
        }
        bi_config = {k: v for k, v in bi_config.items() if v is not None}
        if bi_config:
            user_input["bi_config"] = bi_config
    elif mode == "plan":
        bi_config = None
    else:
        # 自动模式：优先 mode_hint，其次 config
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
            else:
                bi_config = None
        else:
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
                else:
                    bi_config = None
            else:
                bi_config = None

    # 清除残留字段（mode_hint 已在上面用过；sql_test_hint 在下面用）
    user_input.pop("_mode_hint", None)
    sql_test_hint = user_input.pop("_sql_test_hint", None)

    # SQL 校验优先级：用户结构化输入 > 自然语言 hint > config > 默认 True
    # NLConverter 当前只识别"关闭"关键词（如"不校验"），返回 False；不识别"开启"
    if "enable_sql_test" not in user_input:
        if sql_test_hint is not None:
            user_input["enable_sql_test"] = bool(sql_test_hint)
            print(f"[CONFIG] SQL 校验：用户需求覆盖 → {sql_test_hint}")
        else:
            sql_validation = config.get("sql_validation", True)
            user_input["enable_sql_test"] = bool(sql_validation)

    return user_input


def _save_pipeline_outputs(output_dir: str, pipeline_result, pipeline_context: dict):
    """保存 Pipeline 输出到文件"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 保存方案文档
    if pipeline_result.solution_document:
        (out_path / "solution.md").write_text(
            pipeline_result.solution_document, encoding="utf-8"
        )

    # 保存 HTML 版本
    if pipeline_result.html_document:
        (out_path / "solution.html").write_text(
            pipeline_result.html_document, encoding="utf-8"
        )

    # 保存 Agent 中间输出
    agent_outputs_dir = out_path / "agent_outputs"
    agent_outputs_dir.mkdir(exist_ok=True)

    agent_output_keys = [
        ("1.requirements_parser", "requirements_parser_output"),
        ("2.semantic_model", "semantic_model_output"),
        ("3.chart_design", "chart_design_output"),
        ("4.instruction_generator", "instruction_generator_output"),
        ("5.solution_generator", "solution_generator_output"),
    ]

    for display_name, key in agent_output_keys:
        output = pipeline_context.get(key)
        if output:
            output_file = agent_outputs_dir / f"{display_name}.json"
            if isinstance(output, str):
                output_file.write_text(output, encoding="utf-8")
            else:
                output_file.write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    # 保存确认项
    if pipeline_result.all_confirmation_items:
        (agent_outputs_dir / "confirmation_items.json").write_text(
            json.dumps(pipeline_result.all_confirmation_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 保存执行摘要
    summary = {
        "pipeline_id": pipeline_result.pipeline_id,
        "status": pipeline_result.status,
        "total_duration_ms": pipeline_result.total_duration_ms,
        "total_duration_min": pipeline_result.total_duration_ms / 60000,
        "step_durations": {
            s.agent_name: s.duration_ms for s in pipeline_result.steps
        },
        "confirmation_items_count": len(pipeline_result.all_confirmation_items),
    }
    (out_path / "execution_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_pipeline_in_process(chat_id: str, natural_input: str, output_dir: str, mode: str) -> dict:
    """
    进程内执行 Pipeline（替代 subprocess.run）

    优势：
    1. 无超时限制（Pipeline 自身有重试控制）
    2. 可通过 on_progress 回调实时推送进度到飞书
    3. 无需序列化/反序列化，直接访问 Pipeline 结果

    Args:
        chat_id: 飞书群聊 ID（用于推送进度）
        natural_input: 自然语言输入
        output_dir: 输出目录
        mode: 运行模式（plan/publish）

    Returns:
        结果 dict，包含 success, solution_md, solution_html_path, output_dir 等
    """
    from src.llm import LLMClient
    from src.pipeline import Pipeline
    from src.agents import RunMode

    # 加载配置
    config_path = SCRIPTS_DIR / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    llm_config = config.get("llm", {})

    # ---- 准备用户输入 ----
    print(f"[PIPELINE] 准备输入...")
    try:
        user_input = _prepare_user_input(natural_input, mode)
    except Exception as e:
        # 主要场景：NLConverter 检测到用户提到的表不存在 → TableNotFoundError
        # 直接返回结构化失败结果，让 humanize_pipeline_error 把 "Table or view not found"
        # 翻成对用户友好的提示（"找不到数据表 xxx_typo" + 排查建议）
        print(f"[PIPELINE] 准备输入失败: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "failed_step": "requirements_parser",  # 走需求解析阶段的失败模板
            "solution_md": "",
            "solution_html_path": "",
            "output_dir": output_dir,
        }

    # ---- 确定 RunMode ----
    run_mode = RunMode.PUBLISH if user_input.get("bi_config") else RunMode.PLAN
    print(f"[PIPELINE] 运行模式: {run_mode.name}")

    # ---- 准备 LLM 配置 ----
    model_config = {
        "model": llm_config.get("model") or os.getenv("LLM_MODEL") or "deepseek-chat",
        "api_key": llm_config.get("api_key") or os.getenv("HUNYUAN_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        "base_url": llm_config.get("base_url") or os.getenv("LLM_BASE_URL") or None,
    }

    # ---- 进度跟踪状态 ----
    progress_info = {
        "current_agent": "",
        "current_display": "",
        "step_index": 0,
        "total_steps": len(PIPELINE_ORDER),
        "completed": [],
        "error": None,
        "start_time": time.time(),
    }
    progress_card_id = {"message_id": None, "last_update_ts": 0.0}  # 用 dict 以便闭包修改

    # 注册到全局活跃卡片表，供退出钩子在 Ctrl+C 时把卡片标为"已中止"
    with _active_cards_lock:
        _active_progress_cards[chat_id] = {
            "natural_input": natural_input,
            "progress_info": progress_info,        # 共享引用，自动跟随进度更新
            "progress_card_id": progress_card_id,  # 共享引用，包含最新 message_id
        }

    def on_progress(event_type: str, data: dict):
        """Pipeline 进度回调 → 更新飞书进度卡片"""
        try:
            if event_type == "step_start":
                agent_name = data.get("agent_name", "")
                display_name = data.get("display_name", agent_name)
                step_index = data.get("step_index", 0)

                progress_info["current_agent"] = agent_name
                progress_info["current_display"] = display_name
                progress_info["step_index"] = step_index

                print(f"[PROGRESS] ▶ {display_name} 开始执行 ({step_index + 1}/{progress_info['total_steps']})")

                # 更新飞书卡片
                _update_progress_card(chat_id, progress_card_id, progress_info, natural_input)

            elif event_type == "step_complete":
                agent_name = data.get("agent_name", "")
                step_index = data.get("step_index", 0)
                duration_ms = data.get("duration_ms", 0)

                progress_info["completed"].append({
                    "agent": agent_name,
                    "duration_ms": duration_ms,
                })
                next_index = step_index + 1
                progress_info["step_index"] = next_index

                # 把"正在执行"提前切到下一步——否则下一次 step_start 触发前，
                # 卡片会把刚完成的步骤当作"正在执行"显示（与"已完成"列表自相矛盾）
                if next_index < len(PIPELINE_ORDER):
                    next_agent = PIPELINE_ORDER[next_index]
                    progress_info["current_agent"] = next_agent
                    progress_info["current_display"] = AGENT_DISPLAY_NAMES.get(next_agent, next_agent)
                else:
                    # 已经是最后一步——清空"正在执行"，渲染层会自动隐藏该行
                    progress_info["current_agent"] = None
                    progress_info["current_display"] = None

                display_name = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
                duration_s = duration_ms / 1000
                print(f"[PROGRESS] ✅ {display_name} 完成 ({duration_s:.1f}s)")

                # 关键状态：强制更新，绕过节流
                _update_progress_card(chat_id, progress_card_id, progress_info, natural_input, force=True)

            elif event_type == "step_retry":
                agent_name = data.get("agent_name", "")
                attempt = data.get("attempt", 0)
                max_retry = data.get("max_retry", 3)
                error_msg = data.get("error", "")

                display_name = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
                print(f"[PROGRESS] 🔄 {display_name} 重试 ({attempt}/{max_retry}): {error_msg[:80]}")

                # 重试也更新卡片（让用户知道在重试）
                progress_info["retry_info"] = f"{display_name} 重试中 ({attempt}/{max_retry})"
                _update_progress_card(chat_id, progress_card_id, progress_info, natural_input)
                # 清除重试信息
                progress_info.pop("retry_info", None)

            elif event_type == "pipeline_error":
                error_msg = data.get("error", "未知错误")
                failed_agent = data.get("agent_name", "")
                # 进度卡片只展示短摘要，完整建议留给最终的文本消息
                short, _ = humanize_pipeline_error(error_msg, failed_agent)
                progress_info["error"] = short
                # 关键状态：强制更新，确保用户能看到错误
                _update_progress_card(chat_id, progress_card_id, progress_info, natural_input, force=True)

            elif event_type == "pipeline_done":
                print(f"[PROGRESS] 🎉 Pipeline 完成!")
                # 最终卡片由 handle_dashboard_request_sync 发送，这里不再更新

        except Exception as e:
            print(f"[WARN] 进度回调异常: {e}")

    # ---- 创建 Pipeline ----
    pipeline = Pipeline(
        model_config=model_config,
        run_mode=run_mode,
        on_progress=on_progress,
    )

    # ---- 执行 Pipeline ----
    print(f"[PIPELINE] 开始执行...")
    try:
        try:
            result = pipeline.run(user_input)
        except Exception as e:
            print(f"[PIPELINE] 执行失败: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "solution_md": "",
                "solution_html_path": "",
                "output_dir": output_dir,
            }

        # ---- 保存输出 ----
        _save_pipeline_outputs(output_dir, result, pipeline.context)

        # 读取方案文档
        solution_md = result.solution_document
        solution_html_path = ""
        html_file = Path(output_dir) / "solution.html"
        if html_file.exists():
            solution_html_path = str(html_file)

        print(f"[PIPELINE] 完成! 状态: {result.status}, 耗时: {result.total_duration_ms/1000:.1f}s")

        return {
            "success": result.status == "completed",
            "solution_md": solution_md,
            "solution_html_path": solution_html_path,
            "solution_md_path": str(Path(output_dir) / "solution.md") if solution_md else "",
            "output_dir": output_dir,
            "total_duration_ms": result.total_duration_ms,
            "step_count": len(result.steps),
            "confirmation_count": len(result.all_confirmation_items) if result.all_confirmation_items else 0,
            # 失败时把 PipelineResult.error 透传出来；之前缺失这个字段，外层只能拿到"未知错误"
            "error": result.error if result.status == "failed" else "",
            "failed_step": _find_failed_step(result.steps) if result.status == "failed" else "",
            # 把关键 agent 输出透传出来，给 copilot_executor 自动建图用
            "instruction_generator_output": pipeline.context.get("instruction_generator_output"),
            "bi_push_output": pipeline.context.get("bi_push_output"),
        }
    finally:
        # 无论成功 / 失败 / 异常，都从全局活跃表注销，避免退出钩子误清理
        with _active_cards_lock:
            _active_progress_cards.pop(chat_id, None)


def _find_failed_step(steps) -> str:
    """从 Pipeline 步骤列表里找出失败的 Agent 名（用于错误友好化时定位上下文）。"""
    for s in steps:
        if getattr(s, "status", "") == "failed":
            return s.agent_name
    return ""


def _extract_dashboard_label(natural_input: str) -> str:
    """
    从用户自然语言里提取"xx 看板"前缀，用作进度卡片标题。

    匹配规则：找"做/生成/创建/出/要 + 一个/份/张(可选) + xxx + 看板"模式。
    匹配不到时返回空字符串，由调用方 fallback。

    示例：
        "帮我做一个销售看板" → "销售"
        "做个用户活跃度看板" → "用户活跃度"
        "随便做个看板" → ""
    """
    m = re.search(r"(?:做|生成|创建|出|要|搞)(?:一)?(?:个|份|张)?\s*([一-龥A-Za-z0-9]{1,20}?)\s*看板", natural_input)
    if m:
        label = m.group(1).strip()
        # 过滤明显是停用词的情况（如"一个"被部分匹配残留）
        if label and label not in ("个", "一个", "份", "张"):
            return label
    return ""


def _update_progress_card(
    chat_id: str,
    progress_card_id: dict,
    progress_info: dict,
    natural_input: str,
    force: bool = False,
):
    """
    更新或创建进度卡片

    首次调用时创建卡片，后续调用更新已有卡片（避免刷屏）。
    非 force 调用之间会按 PROGRESS_UPDATE_MIN_INTERVAL 节流，避免触发飞书消息频控。

    Args:
        chat_id: 群聊 ID
        progress_card_id: 保存 message_id 和 last_update_ts 的 dict（可变引用）
        progress_info: 进度信息
        natural_input: 用户原始输入（用于卡片标题）
        force: 是否强制更新（关键步骤如完成/失败应传 True）
    """
    label = _extract_dashboard_label(natural_input)
    title = f"{label}看板生成中" if label else "看板生成中"

    # 节流：非强制更新时，距上次更新不足 PROGRESS_UPDATE_MIN_INTERVAL 则跳过
    if not force and progress_card_id.get("message_id") is not None:
        last_ts = progress_card_id.get("last_update_ts", 0.0)
        if time.time() - last_ts < PROGRESS_UPDATE_MIN_INTERVAL:
            return

    # 如果有重试信息，追加到 current_display
    retry_info = progress_info.get("retry_info")
    if retry_info:
        display = progress_info.get("current_display", "")
        progress_info = dict(progress_info)  # 浅拷贝，不修改原始数据
        progress_info["current_display"] = f"{display}（{retry_info}）"

    if progress_card_id.get("message_id") is None:
        # 首次：创建进度卡片
        resp = send_progress_card_sync(chat_id, title, progress_info)
        if resp.get("code") == 0:
            msg_id = resp.get("data", {}).get("message_id", "")
            if msg_id:
                progress_card_id["message_id"] = msg_id
                progress_card_id["last_update_ts"] = time.time()
                print(f"[PROGRESS] 进度卡片已创建: {msg_id[:8]}...")
    else:
        # 后续：更新进度卡片
        update_progress_card_sync(progress_card_id["message_id"], title, progress_info)
        progress_card_id["last_update_ts"] = time.time()


def _cleanup_active_progress_cards(reason: str = "服务已中止（Ctrl+C），任务被中断"):
    """
    退出前把所有正在跑的进度卡片标记为"已中止"，并给群里发提示。

    避免飞书侧的卡片永远停留在"正在执行：xxx ..." 中间状态，
    给用户错觉以为机器人卡死了。

    本函数对网络异常容错，单个卡片清理失败不会阻塞其他卡片。
    """
    with _active_cards_lock:
        snapshot = list(_active_progress_cards.items())
        _active_progress_cards.clear()

    if not snapshot:
        return

    print(f"[SHUTDOWN] 清理 {len(snapshot)} 个进行中的进度卡片...")
    for chat_id, info in snapshot:
        try:
            pcid = info.get("progress_card_id", {})
            msg_id = pcid.get("message_id")
            if not msg_id:
                # 卡片还没创建出来，只发文本提示
                reply_text_sync(chat_id, f"⚠️ {reason}\n请重启服务后重新发起需求。")
                continue

            # 把进度卡片改成"已中止"
            progress_info = dict(info.get("progress_info", {}))
            progress_info["error"] = reason
            label = _extract_dashboard_label(info.get("natural_input", ""))
            title = f"{label}看板生成中" if label else "看板生成中"
            update_progress_card_sync(msg_id, title, progress_info)

            # 同时发一条文本消息，确保用户一定能看到提示
            reply_text_sync(chat_id, f"⚠️ {reason}\n请重启服务后重新发起需求。")
        except Exception as e:
            print(f"[SHUTDOWN] 清理 chat={chat_id[:8]}... 卡片失败: {e}")


def _try_auto_build_via_copilot(
    chat_id: str,
    instruction_output: dict,
    bi_push_output: dict,
    title: str,
) -> None:
    """
    Pipeline 跑完后,自动调编辑助手把看板真搭出来。
    任何失败都吞掉(只发飞书消息),不影响外层。
    """
    try:
        # 加载配置
        config_path = SCRIPTS_DIR / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            full_config = json.load(f)
        copilot_cfg_dict = full_config.get("copilot") or {}

        if not copilot_cfg_dict.get("enabled"):
            print("[COPILOT] config.copilot.enabled=false,跳过自动建图")
            return

        cookie = os.getenv("COPILOT_COOKIE", "").strip()
        if not cookie:
            reply_text_sync(
                chat_id,
                "ℹ️ 自动建图未启用：缺少 COPILOT_COOKIE（管理员从浏览器抓 Cookie 填到 .env 即可）。"
                "你仍可按上方方案文档手动操作。",
            )
            return

        # model_id 从 BI 推送结果里拿（语义模型已发布到 BI 才能用）
        if not bi_push_output or bi_push_output.get("skipped"):
            reply_text_sync(
                chat_id,
                "ℹ️ 自动建图跳过：当前是「方案模式」（未发布语义模型到 BI），无可用 model_id。"
                "如需自动建图，请在需求里明确「推送/publish」模式。",
            )
            return
        results = bi_push_output.get("results") or []
        model_id = (results[0] or {}).get("model_id") if results else None
        if not model_id:
            reply_text_sync(chat_id, "ℹ️ 自动建图跳过：bi_push 结果里没拿到 model_id。")
            return

        # 导入执行器（按需导入，避免启动期 import curl_cffi）
        from src.copilot_executor import (
            CopilotConfig,
            CopilotExecutor,
            render_natural_language_instruction,
        )

        cfg = CopilotConfig(
            base_url=copilot_cfg_dict.get("base_url", ""),
            cookie=cookie,
            project_id=str(copilot_cfg_dict.get("project_id", "")),
            os_data_id=str(copilot_cfg_dict.get("os_data_id", "")),
            impersonate=copilot_cfg_dict.get("impersonate", "chrome146"),
            owner=copilot_cfg_dict.get("owner", "ankaiwen1"),
            parent_menu_id=str(copilot_cfg_dict.get("parent_menu_id", "")),
            web_origin=copilot_cfg_dict.get("web_origin", "https://data.mioffice.cn"),
        )
        base_os_menu_id = copilot_cfg_dict.get("base_os_menu_id", "dashboard_1")

        # 构造自然语言指令
        instruction_text = render_natural_language_instruction(instruction_output or {})
        if not instruction_text.strip():
            reply_text_sync(chat_id, "ℹ️ 自动建图跳过：instruction_generator 输出为空,无法转自然语言。")
            return

        reply_text_sync(chat_id, f"🚧 正在自动搭建看板「{title}」(预计 30-60 秒)...")

        executor = CopilotExecutor(cfg, logger=lambda m: print(f"  {m}"))
        exec_result = executor.execute_full(
            instruction_text=instruction_text,
            model_id=str(model_id),
            dashboard_name=title,
            base_os_menu_id=base_os_menu_id,
        )

        if exec_result.success:
            reply_text_sync(
                chat_id,
                f"✅ 看板已自动搭建完成！\n\n"
                f"📊 {title}\n"
                f"🔗 {exec_result.dashboard_url}",
            )
        else:
            reply_text_sync(
                chat_id,
                f"⚠️ 自动建图未完成：{exec_result.error}\n"
                f"请按上方方案文档手动操作。",
            )
    except Exception as e:
        print(f"[COPILOT-ERROR] 自动建图异常: {e}")
        traceback.print_exc()
        try:
            reply_text_sync(chat_id, f"⚠️ 自动建图遇到异常：{str(e)[:200]}\n请按方案文档手动操作。")
        except Exception:
            pass


def handle_dashboard_request_sync(chat_id: str, text: str):
    """处理看板生成请求的完整工作流（同步，在子线程中运行）"""
    print(f"[HANDLE] 开始处理看板请求: chat_id={chat_id[:8]}..., text='{text[:50]}...'")

    # 防重复：同一群同时只允许一个任务在跑
    with _tasks_lock:
        if chat_id in _running_chats:
            reply_text_sync(chat_id, "正在生成中，请稍等当前任务完成后再发起新需求 ⏳")
            return
        _running_chats.add(chat_id)

    try:
        # 先回复确认
        echo_text = text if len(text) <= 500 else text[:500] + "..."
        reply_text_sync(chat_id, f"收到！正在生成看板方案...\n\n需求：{echo_text}\n\n我会实时推送进度，请稍候 ⏳")

        # 执行 pipeline（进程内调用，带进度推送）
        # mode="auto"：让 NLConverter 提取的 mode_hint 和 config.bi_platform.enabled 生效
        # 写死 "publish" 会覆盖用户在需求里的"方案模式"声明，是错误行为
        output_dir = tempfile.mkdtemp(prefix="dashboard_feishu_")
        result = run_pipeline_in_process(chat_id, text, output_dir, mode="auto")

        if not result["success"]:
            raw_error = result.get("error", "")
            failed_step = result.get("failed_step", "")
            _, friendly = humanize_pipeline_error(raw_error, failed_step)
            reply_text_sync(chat_id, friendly)
            return

        # 生成成功 → 发送简洁通知卡片 + 上传方案附件
        solution_md = result.get("solution_md", "")
        if not solution_md:
            reply_text_sync(chat_id, "❌ 方案内容为空，请重试")
            return

        # 提取标题
        title = "数据看板方案"
        for line in solution_md.split("\n"):
            if line.startswith("#"):
                title = line.lstrip("# ").strip()
                break

        # 发送完成通知卡片（简洁版，不含正文）
        send_completion_card_sync(
            chat_id,
            title,
            duration_ms=result.get("total_duration_ms", 0),
            step_count=result.get("step_count", 0),
            confirmation_count=result.get("confirmation_count", 0),
        )

        # 上传 Markdown 附件（便于复制编辑）
        md_path = result.get("solution_md_path", "")
        if md_path and Path(md_path).exists():
            upload_file_to_chat_sync(chat_id, md_path, f"{title}.md")

        # 上传 HTML 附件（便于直接浏览）
        html_path = result.get("solution_html_path", "")
        if html_path and Path(html_path).exists():
            upload_file_to_chat_sync(chat_id, html_path, f"{title}.html")

        # 上传"看板搭建指令"附件 —— 这是发给编辑助手的自然语言文本,
        # 不论自动建图是否触发/成功,都让用户能看到完整指令(便于核对/手动 fallback)
        ig_output = result.get("instruction_generator_output") or {}
        if ig_output:
            try:
                from src.copilot_executor import render_natural_language_instruction
                instruction_text = render_natural_language_instruction(ig_output)
                if instruction_text.strip():
                    output_dir = result.get("output_dir") or tempfile.mkdtemp(prefix="dashboard_instr_")
                    instr_path = Path(output_dir) / "看板搭建指令.txt"
                    instr_path.write_text(instruction_text, encoding="utf-8")
                    upload_file_to_chat_sync(chat_id, str(instr_path), f"{title}_搭建指令.txt")
            except Exception as e:
                print(f"[INSTRUCTION] 上传搭建指令附件失败: {e}")
                traceback.print_exc()

        # 自动建图（异常吞掉,不影响主流程）
        _try_auto_build_via_copilot(
            chat_id=chat_id,
            instruction_output=ig_output,
            bi_push_output=result.get("bi_push_output") or {},
            title=title,
        )

    except Exception as e:
        print(f"[ERROR] handle_dashboard_request 异常: {e}")
        traceback.print_exc()
        reply_text_sync(chat_id, f"❌ 处理异常：{str(e)[:200]}")

    finally:
        with _tasks_lock:
            _running_chats.discard(chat_id)


# ============================================================
# 飞书长连接事件处理
# ============================================================

def _is_message_processed(msg_id: str) -> bool:
    """检查 message_id 是否已处理过（防止飞书事件重发）。"""
    if not msg_id:
        return False
    with _processed_message_lock:
        if msg_id in _processed_message_ids:
            return True
        _processed_message_ids.add(msg_id)
        # 简单的 LRU：超出上限时清空一半最早的
        if len(_processed_message_ids) > _PROCESSED_MAX_SIZE:
            keep = list(_processed_message_ids)[_PROCESSED_MAX_SIZE // 2:]
            _processed_message_ids.clear()
            _processed_message_ids.update(keep)
        return False


def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    """处理接收到的飞书消息事件（v2.0）"""
    try:
        event = data.event
        if not event:
            return

        message = event.message

        if not message:
            return

        chat_id = message.chat_id or ""
        chat_type = message.chat_type or ""
        msg_type = message.message_type or ""
        msg_id = message.message_id or ""

        # 幂等性：同一 message_id 只处理一次（飞书事件可能重发）
        if _is_message_processed(msg_id):
            print(f"[SKIP] 重复事件，忽略 message_id={msg_id[:8]}...")
            return

        # 只处理文本和富文本消息
        if msg_type not in ("text", "post"):
            print(f"[SKIP] 忽略非文本消息类型: {msg_type}")
            return

        # 提取文本内容
        content_str = message.content or "{}"
        print(f"[DEBUG] 原始消息内容: {content_str[:500]}")

        try:
            content = json.loads(content_str) if isinstance(content_str, str) else content_str
        except json.JSONDecodeError:
            print(f"[SKIP] 消息内容 JSON 解析失败")
            if chat_id:
                reply_text_sync(chat_id, "❌ 抱歉，无法解析你的消息内容，请用纯文本重试。")
            return

        text = ""
        if "text" in content:
            text = content["text"].strip()
        elif "rich_text" in content:
            texts = []
            for block in content.get("rich_text", []):
                for elem in block.get("content", []):
                    if elem.get("tag") == "text":
                        texts.append(elem.get("text", ""))
            text = "".join(texts).strip()

        if not text:
            print(f"[SKIP] 消息文本为空")
            return

        print(f"[DEBUG] 提取的原始文本: {text[:200]}")

        # 去掉开头的 @机器人 标记（只处理消息开头连续的 @ 标记，避免误删正文里的邮箱等）
        # 飞书 @ 格式：@_user_xxx / @user_xxx / @机器人名
        original_text = text
        text = re.sub(r'^(?:@_user_\d+|@user_\d+|@[\w一-龥]+)[\s ]*', '', text).strip()
        # 可能存在多个 @（@所有人 + @机器人），再剥一次开头的
        text = re.sub(r'^(?:@_user_\d+|@user_\d+|@[\w一-龥]+)[\s ]*', '', text).strip()

        print(f"[DEBUG] @标记处理后: '{text[:100]}...' (原始: '{original_text[:100]}...')")

        if not text:
            print(f"[SKIP] 去除 @ 标记后文本为空")
            return

        print(f"[MSG] chat={chat_id[:8]}..., type={chat_type}, text={text[:80]}")

        # 意图识别
        intent = classify_intent(text)
        print(f"[INTENT] 意图识别结果: {intent}, 文本: '{text[:50]}...'")

        if intent == "dashboard":
            print(f"[HANDLE] 启动看板生成线程, 文本: '{text[:50]}...'")
            # 在子线程中处理（避免阻塞长连接事件处理）
            t = threading.Thread(
                target=handle_dashboard_request_sync,
                args=(chat_id, text),
                daemon=True,
            )
            t.start()

        elif intent == "revise":
            reply_text_sync(chat_id, "修改功能开发中，敬请期待 🚧")

        else:
            # 未识别意图：给用户友好提示，避免静默
            reply_text_sync(
                chat_id,
                "👋 抱歉，没有理解你的需求。\n"
                "\n"
                "我可以帮你生成数据看板，最少需要这两项：\n"
                "\n"
                "✅ 看板用途（含「看板」二字）\n"
                "    例：销售业绩看板、用户活跃度看板\n"
                "\n"
                "✅ 数据源（表名 + 关键字段）\n"
                "    例：数据来自 ods.sales_order，关键字段 order_id / user_id / amount / dt\n"
                "\n"
                "📋 完整示例：\n"
                "    帮我做一个销售看板，数据来自 ods.sales_order 表，\n"
                "    关键字段：order_id、user_id、amount、create_time、region。\n"
                "\n"
                "💡 信息越完整方案越精准，可以补充时间范围、核心指标、分析维度等。"
            )

    except Exception as e:
        print(f"[ERROR] on_message_receive 异常: {e}")
        traceback.print_exc()


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    # 启动前检查
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("未设置飞书凭证，请设置环境变量或编辑 scripts/.env 文件：")
        print("   FEISHU_APP_ID=cli_a5xxxxxxxxxxxxx")
        print("   FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        sys.exit(1)

    if not Path(PIPELINE_SCRIPT).exists():
        print(f"Pipeline 脚本不存在: {PIPELINE_SCRIPT}")
        sys.exit(1)

    # 日志文件
    LOG_DIR = Path(PROJECT_ROOT) / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    LOG_FILE = LOG_DIR / f"feishu_orchestrator_{time.strftime('%Y%m%d_%H%M%S')}.log"

    # 重定向 stdout/stderr 到日志文件 + 控制台
    class TeeLogger:
        def __init__(self, filepath, stream):
            self.file = open(filepath, "a", encoding="utf-8")
            self.stream = stream
        def write(self, data):
            self.file.write(data)
            self.file.flush()
            self.stream.write(data)
            self.stream.flush()
        def flush(self):
            self.file.flush()
            self.stream.flush()
        def close(self):
            try:
                self.file.flush()
                self.file.close()
            except Exception:
                pass

    _stdout_tee = TeeLogger(LOG_FILE, sys.stdout)
    _stderr_tee = TeeLogger(LOG_FILE, sys.stderr)
    sys.stdout = _stdout_tee
    sys.stderr = _stderr_tee
    # 注意 atexit 是 LIFO：先注册的最后执行
    # 所以 TeeLogger.close 应该在最后（保证 cleanup 时 stdout 还在）
    atexit.register(_stdout_tee.close)
    atexit.register(_stderr_tee.close)
    # 进度卡片清理钩子：放在 TeeLogger 之后注册，这样会先执行（LIFO）
    atexit.register(_cleanup_active_progress_cards)

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 飞书看板助手启动中（长连接模式）...")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 日志文件: {LOG_FILE}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] App ID: {FEISHU_APP_ID[:8]}...")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pipeline: {PIPELINE_SCRIPT}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 模式: WebSocket 长连接（无需内网穿透）")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] HTTP 超时: {HTTP_TIMEOUT}s | 进度卡片节流: {PROGRESS_UPDATE_MIN_INTERVAL}s")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 进度推送: 已启用（卡片实时更新）")
    print()

    # 注册事件处理器
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message_receive) \
        .build()

    # 创建长连接客户端
    cli = lark.ws.Client(
        FEISHU_APP_ID,
        FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 等待连接飞书服务器...")

    # 启动长连接（阻塞主线程）
    # 包一层 try/except 显式处理 Ctrl+C：在退出前主动把进度卡片标为"已中止"
    # （atexit 钩子也注册了同样的清理逻辑，作为双保险）
    try:
        cli.start()
    except KeyboardInterrupt:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 收到 Ctrl+C，正在清理进行中的任务...")
        _cleanup_active_progress_cards()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 清理完成，退出。")
        sys.exit(0)
