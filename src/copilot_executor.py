"""
编辑助手直连执行器：把 instruction_generator_output 自动建成 BI 看板。

完整链路（详见 docs/PoC_编辑助手直连_2026-05-15.md）：
    1. POST menu/update.do?operationType=create   → 新建空白看板
    2. GET  sse/connect.do                        → 建立 SSE 长连接
    3. POST agent/messages/send.do                → 提交自然语言指令
    4. SSE  query.page.json
       POST agent/save/pageJson.do                → 反向 RPC：发当前页面状态
    5. SSE  push.message phase=completed
       POST agent/query/chunkData.do              → 拉 AI 生成的看板配置
       POST agent/page/save.do (before/after)     → AI 上下文档案
       POST page/updatePageDraft.do  ⭐           → 真正写盘

依赖：curl_cffi（必需，用于绕过 Aegis TLS 指纹检测）
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Optional

from curl_cffi import requests as cffi_requests


# ============================================================
# 数据结构
# ============================================================


@dataclass
class CopilotConfig:
    """编辑助手直连配置"""
    base_url: str           # 如 https://api-whale.data.mioffice.cn
    cookie: str             # 整段 Cookie 字符串
    project_id: str         # 如 "10125971"
    os_data_id: str         # 如 "10125971"
    impersonate: str = "chrome146"   # curl_cffi 模拟的浏览器版本
    owner: str = "ankaiwen1"          # 看板 owner / creator
    parent_menu_id: str = "375083"    # 新建看板时的菜单父节点 ID
    web_origin: str = "https://data.mioffice.cn"  # 用于 Origin/Referer 头
    timeout: int = 300       # SSE 长连接超时（秒）

    def dashboard_url(self, dashboard_id: str) -> str:
        """根据 dashboardId 拼出用户可点击的看板 URL"""
        return (
            f"{self.web_origin}/whale/?pid={self.project_id}"
            f"#/data-bi/dashboard/{dashboard_id}?projectId={self.project_id}"
        )


@dataclass
class ExecutionResult:
    """端到端执行结果"""
    success: bool
    dashboard_id: str = ""
    os_menu_id: str = ""
    dashboard_url: str = ""
    ai_message: str = ""
    error: str = ""
    events: list = field(default_factory=list)  # SSE 事件序列，调试用


# ============================================================
# SSE 协议解析
# ============================================================


@dataclass
class SSEEvent:
    event: Optional[str] = None
    data: list = field(default_factory=list)
    id: Optional[str] = None
    retry: Optional[int] = None

    def is_empty(self) -> bool:
        return self.event is None and not self.data and self.id is None

    def data_text(self) -> str:
        return "\n".join(self.data) if self.data else ""


def parse_sse_lines(line_iter: Iterable):
    """标准 SSE 协议解析：累积字段，空行触发事件"""
    current = SSEEvent()
    for raw in line_iter:
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        line = raw.rstrip("\r\n")
        if line == "":
            if not current.is_empty():
                yield current
                current = SSEEvent()
            continue
        if line.startswith(":"):
            continue  # SSE 注释/心跳
        if ":" in line:
            field_name, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
        else:
            field_name, value = line, ""
        if field_name == "event":
            current.event = value
        elif field_name == "data":
            current.data.append(value)
        elif field_name == "id":
            current.id = value
        elif field_name == "retry":
            try:
                current.retry = int(value)
            except ValueError:
                pass
    if not current.is_empty():
        yield current


# ============================================================
# pageJson 模板
# ============================================================


def build_empty_page_json(dashboard_id: str, name: str, owner: str, project_id: str) -> dict:
    """生成空白看板的 pageJson 结构（供 save/pageJson.do 和 page/save.do 使用）"""
    return {
        "componentList": [],
        "menuConfVO": {
            "globalFilters": [],
            "hasAuth": False,
            "owner": owner,
            "type": 1,
            "version": "0",
            "menuShowType": 0,
            "parentId": None,
            "isRelease": 1,
            "name": name,
            "shareDisabled": False,
            "isMobile": 0,
            "projectId": project_id,
            "key": dashboard_id,
            "isFavorite": False,
            "nameI18n": {"zh": name},
            "showGrid": True,
            "theme": "coldTheme",
        },
        "pageSetting": {
            "linkage": True, "drilldown": True, "abnormalAnalyze": True,
            "rootCauseAnalysis": True, "influenceFactor": True,
            "dimensionAnalysis": True, "timingPredict": True,
            "intelligentInsight": True, "settingVersion": 6,
            "enhanceAnalysis": {
                "linkage": True, "drilldown": True, "abnormalAnalyze": True,
                "rootCauseAnalysis": True, "influenceFactor": True,
                "dimensionAnalysis": True, "timingPredict": True,
                "intelligentInsight": True,
            },
            "showGrid": True, "dashboardMaxWidth": 1920,
            "filterLocalStorage": True, "language": "zh",
        },
        "scheduleInfo": {"scheduleTime": ""},
        "creator": owner,
        "owner": owner,
        "dashboardId": dashboard_id,
        "modelAnalysisMap": {},
        "whaleVersion": 0,
        "menuShowType": 0,
        "isMobile": 0,
    }


# ============================================================
# 自然语言指令模板化
# ============================================================


_CHART_TYPE_ZH = {
    "bar": "条形图", "horizontal_bar": "条形图",
    "stacked_bar": "堆叠柱状图", "column": "柱状图",
    "line": "折线图", "area": "面积图",
    "pie": "饼图", "donut": "环形图",
    "metric_card": "指标卡片", "metric_trend": "指标趋势图",
    "scatter": "散点图", "map": "地图", "funnel": "漏斗图",
    "table": "数据表格", "sankey": "桑基图",
}


def _chart_type_zh(t: str) -> str:
    return _CHART_TYPE_ZH.get(t, t or "")


def render_natural_language_instruction(instruction_output: dict) -> str:
    """
    把 instruction_generator_output（结构化 JSON）模板化为自然语言指令字符串。

    输入示例（关键字段）：
      { "title", "semantic_model": {id, name}, "charts": [...], "filters": [...], "summary" }

    输出示例：
      看板标题：销售分析看板
      语义模型：销售分析（ID: model_12345）
      筛选器：月份、产品线
      图表：
        - 月度签单金额 — 条形图，按 sign_amount 降序展示 Top10
        ...
      布局（12 列网格）：
        - 月度签单金额：行 1 列 1，宽 6 高 4
        ...
    """
    parts: list[str] = []

    title = instruction_output.get("title") or "未命名看板"
    parts.append(f"看板标题：{title}")

    sm = instruction_output.get("semantic_model") or {}
    sm_name = sm.get("name") or ""
    sm_id = sm.get("id") or ""
    if sm_name and sm_id:
        parts.append(f"语义模型：{sm_name}（ID: {sm_id}）")
    elif sm_name:
        parts.append(f"语义模型：{sm_name}")

    filters = instruction_output.get("filters") or []
    if filters:
        names = "、".join(f.get("title") or f.get("field") or "" for f in filters)
        parts.append(f"筛选器：{names}")

    charts = instruction_output.get("charts") or []
    if charts:
        parts.append("图表：")
        for c in charts:
            chart_title = c.get("title") or c.get("chart_id") or "未命名图表"
            chart_type = _chart_type_zh(c.get("chart_type") or "")
            metrics = c.get("metrics") or []
            dimensions = c.get("dimensions") or []
            sort = c.get("sort") or {}
            limit = c.get("limit")

            metric_str = "、".join(m.get("alias") or m.get("field") or "" for m in metrics)
            dim_str = "、".join(d.get("alias") or d.get("field") or "" for d in dimensions)

            extras: list[str] = []
            if dim_str:
                extras.append(f"按 {dim_str}")
            if metric_str:
                extras.append(f"展示 {metric_str}")
            if sort.get("field"):
                order = "降序" if sort.get("order") == "desc" else "升序"
                extras.append(f"按 {sort['field']} {order}")
            if limit:
                extras.append(f"Top{limit}")
            extras_str = "，".join(extras)

            line = f"  - {chart_title}"
            if chart_type:
                line += f" — {chart_type}"
            if extras_str:
                line += f"，{extras_str}"
            parts.append(line)

    # 布局：把每个图表的位置 / 大小告诉编辑助手，避免它按图表数量自动猜放置
    #
    # ⚠️ instruction_generator 的输出里两套坐标并存：
    #   - chart.position：{row, col, width, height} —— 全部是网格单位（1-indexed）
    #   - layout.charts[]：{x, y, w, h} —— x/y 是像素（(col-1)*row_height），w/h 才是网格跨度
    # 后者单位不一致（位置像素+尺寸网格），输出会出现"列 241、列 481"这种像素值，
    # 既迷惑用户也容易让编辑助手 LLM 误判。所以优先取 chart.position（全网格），
    # 实在没有再回落到 layout.charts[]。
    layout = instruction_output.get("layout") or {}
    layout_charts_raw = layout.get("charts") or []
    row_height = int(layout.get("row_height") or 80)
    total_cols = layout.get("columns")

    layout_lines: list[str] = []
    if charts and any(c.get("position") for c in charts):
        # 优先：每张图自带的 position（全网格单位）
        for c in charts:
            pos = c.get("position") or {}
            if not pos:
                continue
            title = c.get("title") or c.get("chart_id") or "未命名图表"
            row = int(pos.get("row", 1) or 1)
            col = int(pos.get("col", 1) or 1)
            w = int(pos.get("width", 1) or 1)
            h = int(pos.get("height", 1) or 1)
            layout_lines.append(f"  - {title}：行 {row} 列 {col}，宽 {w} 高 {h}")
    elif layout_charts_raw:
        # 回落：layout.charts[]，把像素 x/y 反推回网格 col/row
        chart_title_map = {
            c.get("chart_id"): (c.get("title") or c.get("chart_id") or "未命名图表")
            for c in charts
        }
        for lc in layout_charts_raw:
            cid = lc.get("chart_id", "?")
            title = chart_title_map.get(cid, cid)
            x_px = int(lc.get("x", 0) or 0)
            y_px = int(lc.get("y", 0) or 0)
            w = int(lc.get("w", 1) or 1)
            h = int(lc.get("h", 1) or 1)
            # 像素 → 网格：col = x_px / row_height + 1（row_height 同时被用作列宽单位）
            col = x_px // row_height + 1 if row_height else x_px + 1
            row = y_px // row_height + 1 if row_height else y_px + 1
            layout_lines.append(f"  - {title}：行 {row} 列 {col}，宽 {w} 高 {h}")

    if layout_lines:
        header = f"布局（{total_cols} 列网格）：" if total_cols else "布局："
        parts.append(header)
        parts.extend(layout_lines)

    # 不附加 summary：它由上游 instruction-generator-agent 让 LLM 自己写,
    # 实测内容会与上述结构化部分重叠 80%+（标题、图表列表都重复一遍),
    # 既污染发给编辑助手的 prompt,也让用户看到的"搭建指令.txt"显得是写两遍。
    # 业务描述用户可以从 solution.md 里读。

    return "\n".join(parts)


# ============================================================
# CopilotExecutor — 主类
# ============================================================


class CopilotExecutor:
    """编辑助手直连执行器，单次执行模式（一次实例一次任务）"""

    def __init__(self, config: CopilotConfig, logger=print):
        self.cfg = config
        self.log = logger
        self.client_id = uuid.uuid4().hex[:11]
        self.window_id = self.client_id

    # -------- 公共 headers --------

    def _headers(self, accept: str) -> dict:
        """业务头，TLS/UA/sec-ch-ua 等指纹相关由 curl_cffi 自动模拟"""
        return {
            "accept": accept,
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "origin": self.cfg.web_origin,
            "referer": self.cfg.web_origin + "/",
            "cookie": self.cfg.cookie,
        }

    def _post_json(self, path: str, params: dict, body: dict, *, timeout: int = 30):
        url = f"{self.cfg.base_url}{path}"
        headers = self._headers("application/json")
        headers["content-type"] = "application/json;charset=UTF-8"
        headers["x-requested-with"] = "xmlhttprequest"
        return cffi_requests.post(
            url, params=params, headers=headers, json=body,
            impersonate=self.cfg.impersonate, timeout=timeout,
        )

    # -------- 步骤 1：新建空白看板 --------

    def create_blank_dashboard(self, name: str, *, base_os_menu_id: str = "dashboard_1") -> dict:
        """
        调 menu/update.do?operationType=create 新建一个空白看板。

        Args:
            name: 新看板的名字
            base_os_menu_id: 调用时 URL 上的 osMenuId（"父上下文"，任选一个已存在的）

        Returns:
            { "dashboard_id": "<新ID>", "os_menu_id": "<沿用的>", "version": "<返回的版本号>" }
        """
        params = {
            "operationType": "create",
            "catalogType": "1",
            "osDataId": self.cfg.os_data_id,
            "projectId": self.cfg.project_id,
            "osMenuId": base_os_menu_id,
        }
        body = {
            "type": 1,
            "name": name,
            "parentId": self.cfg.parent_menu_id,
            "menuShowType": 0,
            "isMobile": 0,
            "isRelease": 1,
            "projectId": self.cfg.project_id,
        }
        self.log(f"[copilot] POST menu/update.do?operationType=create name={name!r}")
        r = self._post_json("/api/bigbi/os/menu/update.do", params, body, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"创建看板失败 status={r.status_code} body={r.text[:300]}")

        try:
            body_json = r.json()
        except Exception as e:
            raise RuntimeError(f"创建看板响应非 JSON: {r.text[:300]}") from e

        # 业务层失败检查：success!='true' 或 code!=0 都视为业务失败
        success = str(body_json.get("success", "")).lower()
        code = body_json.get("code")
        if success != "true" or (code is not None and code != 0):
            msg = body_json.get("msg") or body_json.get("result") or "未知"
            raise RuntimeError(f"创建看板业务失败 code={code} success={success} msg={msg!r} 原始响应={r.text[:500]}")

        # 正常情况下 result 应是 dict（含 key/version/name 等）
        result = body_json.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(
                f"创建看板响应 result 不是 dict（实际类型={type(result).__name__}, 值={result!r}）"
                f" 原始响应={r.text[:500]}"
            )
        new_id = result.get("key")
        if not new_id:
            raise RuntimeError(f"创建看板成功但响应缺 key,原始响应：{r.text[:500]}")
        self.log(f"[copilot] ✓ 新看板 dashboardId={new_id} version={result.get('version')}")
        # ⚠️ osMenuId 不在响应里，沿用我们传入的
        return {
            "dashboard_id": str(new_id),
            "os_menu_id": base_os_menu_id,
            "version": result.get("version"),
            "name": result.get("name") or name,
        }

    # -------- 步骤 2-N：完整 SSE + 反向 RPC + 持久化 --------

    def execute(
        self,
        instruction_text: str,
        dashboard_id: str,
        os_menu_id: str,
        model_id: str,
        dashboard_name: str = "未命名报表",
    ) -> ExecutionResult:
        """
        在指定的（已存在的）空白看板上执行一次自然语言建图。
        调用方需先调 create_blank_dashboard 拿到 dashboard_id 和 os_menu_id。
        """
        result = ExecutionResult(
            success=False,
            dashboard_id=dashboard_id,
            os_menu_id=os_menu_id,
            dashboard_url=self.cfg.dashboard_url(dashboard_id),
        )

        common_params = {
            "projectId": self.cfg.project_id,
            "osDataId": self.cfg.os_data_id,
            "osMenuId": os_menu_id,
        }
        empty_template = build_empty_page_json(
            dashboard_id, dashboard_name, self.cfg.owner, self.cfg.project_id,
        )

        # SSE 监听状态（在闭包里被 listener 线程更新）
        state = {
            "connection_id": None,
            "trace_id": None,
            "completed_message": None,
            "chunk_data_result": None,
            "stop": False,
            "error": None,
            "conversation_id": None,
            "events": [],
        }

        def reverse_save_page_json(conv_id: str, trace_id: str):
            self.log(f"[copilot] reverse-rpc: save/pageJson.do (conv={conv_id[:8]}…)")
            try:
                r = self._post_json(
                    "/api/bigbi/os/agent/save/pageJson.do",
                    common_params,
                    {
                        "pageJson": json.dumps(empty_template, ensure_ascii=False),
                        "conversationId": conv_id,
                        "traceId": trace_id,
                        "projectId": self.cfg.project_id,
                    },
                    timeout=15,
                )
                if r.status_code != 200:
                    self.log(f"[copilot] save/pageJson.do failed: {r.status_code} {r.text[:200]}")
            except Exception as e:
                self.log(f"[copilot] save/pageJson.do exception: {e}")

        def on_event(ev: SSEEvent):
            try:
                data = json.loads(ev.data_text()) if ev.data else {}
            except json.JSONDecodeError:
                data = {"_raw": ev.data_text()}
            state["events"].append((ev.event, data))

            if ev.event == "connection.established":
                state["connection_id"] = data.get("connectionId")
                self.log(f"[copilot] SSE connection.established id={state['connection_id']}")

            elif ev.event == "query.page.json":
                conv = data.get("conversationId") or state["conversation_id"]
                tid = data.get("traceId") or data.get("payload", {}).get("ext", {}).get("originTraceId")
                if tid and not state["trace_id"]:
                    state["trace_id"] = tid
                if conv and tid:
                    threading.Thread(
                        target=reverse_save_page_json, args=(conv, tid), daemon=True,
                    ).start()

            elif ev.event == "push.message" and data.get("phase") == "completed":
                state["completed_message"] = data
                state["stop"] = True

        def listen_sse():
            url = f"{self.cfg.base_url}/api/bigbi/os/sse/connect.do"
            params = {"clientId": self.client_id, "clientVersion": "1.0.0", "windowId": self.window_id}
            headers = self._headers("text/event-stream")
            try:
                r = cffi_requests.get(
                    url, params=params, headers=headers,
                    impersonate=self.cfg.impersonate, stream=True, timeout=self.cfg.timeout,
                )
                if r.status_code != 200:
                    state["error"] = f"SSE status {r.status_code}"
                    return
                for ev in parse_sse_lines(r.iter_lines()):
                    if state["stop"]:
                        break
                    on_event(ev)
            except Exception as e:
                if state["completed_message"] is None:
                    state["error"] = f"SSE 异常: {type(e).__name__}: {e}"

        # 启动 SSE
        listener = threading.Thread(target=listen_sse, daemon=True)
        listener.start()

        # 等连接建立（最多 15s）
        for _ in range(150):
            if state["connection_id"] or state["error"]:
                break
            time.sleep(0.1)
        if state["error"]:
            result.error = state["error"]
            return result
        if not state["connection_id"]:
            result.error = "SSE 连上但未收到 connection.established"
            return result

        # 发指令
        self.log(f"[copilot] send.do POST instruction (len={len(instruction_text)})")
        send_resp = self._post_json(
            "/api/bigbi/os/agent/messages/send.do",
            common_params,
            {
                "input": {"messageType": "string", "content": instruction_text},
                "context": [
                    {"type": "all", "uuid": "sys-all", "params": {"componentList": []}},
                    {
                        "type": "model",
                        "uuid": f"sys-model_{model_id}",
                        "params": {"modelId": model_id},
                    },
                ],
                "clientId": self.client_id,
                "windowId": self.window_id,
                "conversationId": None,
                "projectId": self.cfg.project_id,
            },
            timeout=30,
        )
        if send_resp.status_code != 200:
            result.error = f"send.do 失败 status={send_resp.status_code} body={send_resp.text[:200]}"
            return result
        send_body = send_resp.json()
        state["conversation_id"] = send_body.get("result", {}).get("conversationId")

        # 等 push.message completed（最多 180s）
        listener.join(timeout=180)
        if state["error"] and not state["completed_message"]:
            result.error = state["error"]
            return result
        if not state["completed_message"]:
            result.error = "等待 AI 完成超时（180s）"
            result.events = state["events"]
            return result

        completed = state["completed_message"]
        result.ai_message = completed.get("message") or ""
        result.events = state["events"]

        # AI 报错（缺字段、数据超时等）
        if completed.get("interactionType") != "normal":
            result.error = f"AI 返回错误：{result.ai_message}"
            return result

        # 拉 chunkData.do 拿生成的看板配置
        msg_id = completed.get("messageId")
        conv = completed.get("conversationId") or state["conversation_id"]
        tid = state["trace_id"] or completed.get("traceId")
        if not (msg_id and conv and tid):
            result.error = f"持久化字段缺失 msg={msg_id} conv={conv} tid={tid}"
            return result

        self.log(f"[copilot] chunkData.do (msg={msg_id})")
        chunk_resp = self._post_json(
            "/api/bigbi/os/agent/query/chunkData.do",
            common_params,
            {"conversationId": conv, "messageId": msg_id, "traceId": tid, "projectId": self.cfg.project_id},
            timeout=30,
        )
        if chunk_resp.status_code != 200:
            result.error = f"chunkData.do 失败 status={chunk_resp.status_code}"
            return result
        chunk_body = chunk_resp.json()
        state["chunk_data_result"] = chunk_body
        chunk_result_str = chunk_body.get("result") or ""
        if not chunk_result_str:
            result.error = "chunkData.do 返回 result 为空"
            return result

        try:
            ai_page = json.loads(chunk_result_str)
        except Exception as e:
            result.error = f"解析 chunkData.result 失败: {e}"
            return result

        new_components = ai_page.get("componentList") or []
        if not new_components:
            result.error = "AI 生成的 componentList 为空"
            return result

        # AI 上下文档案（before/after）—— 即使省略也能写盘，但保留以贴合浏览器行为
        empty_str = json.dumps(empty_template, ensure_ascii=False)
        new_menu_conf = {**empty_template["menuConfVO"], **(ai_page.get("menuConfVO") or {})}
        new_page_setting = {**empty_template["pageSetting"], **(ai_page.get("pageSetting") or {})}
        new_page_dict = {
            **empty_template,
            "componentList": new_components,
            "menuConfVO": new_menu_conf,
            "pageSetting": new_page_setting,
        }
        new_page_str = json.dumps(new_page_dict, ensure_ascii=False)
        for position, page_str in (("before", empty_str), ("after", new_page_str)):
            self._post_json(
                "/api/bigbi/os/agent/page/save.do",
                common_params,
                {
                    "pageJson": page_str,
                    "traceId": tid,
                    "position": position,
                    "cmd": "{}",
                    "projectId": self.cfg.project_id,
                },
                timeout=30,
            )

        # ⭐ 真正写盘
        self.log(f"[copilot] updatePageDraft.do (componentList n={len(new_components)})")
        draft_resp = self._post_json(
            "/api/bigbi/os/page/updatePageDraft.do",
            common_params,
            {
                "menuConfVO": new_menu_conf,
                "pageSetting": new_page_setting,
                "creator": self.cfg.owner,
                "owner": self.cfg.owner,
                "dashboardId": dashboard_id,
                "modelAnalysisMap": {},
                "whaleVersion": 0,
                "menuShowType": 0,
                "isMobile": 0,
                "scheduleInfo": {"scheduleTime": ""},
                "componentList": new_components,
                "cardList": [],
                "projectId": self.cfg.project_id,
            },
            timeout=30,
        )
        if draft_resp.status_code != 200:
            result.error = f"updatePageDraft.do 失败 status={draft_resp.status_code} body={draft_resp.text[:200]}"
            return result
        draft_body = draft_resp.json()
        if str(draft_body.get("success", "")).lower() != "true" and draft_body.get("code") != 0:
            result.error = f"updatePageDraft.do 业务失败 body={draft_resp.text[:200]}"
            return result

        self.log(f"[copilot] ✅ 看板已写入（version={draft_body.get('result')}）")
        result.success = True
        return result

    # -------- 便捷入口 --------

    def execute_full(
        self,
        instruction_text: str,
        model_id: str,
        dashboard_name: str = "未命名报表",
        base_os_menu_id: str = "dashboard_1",
    ) -> ExecutionResult:
        """先创建空白看板，再执行——一站式入口"""
        # 加时间戳防同名（BI 服务端 errorCode=3053：同一目录下名称重复）
        from datetime import datetime
        ts_suffix = datetime.now().strftime("%m-%d %H:%M:%S")
        unique_name = f"{dashboard_name} · {ts_suffix}"
        try:
            new = self.create_blank_dashboard(unique_name, base_os_menu_id=base_os_menu_id)
        except Exception as e:
            return ExecutionResult(success=False, error=f"创建空白看板失败: {e}")

        return self.execute(
            instruction_text=instruction_text,
            dashboard_id=new["dashboard_id"],
            os_menu_id=new["os_menu_id"],
            model_id=model_id,
            dashboard_name=new["name"],
        )


# ============================================================
# 自检入口（开发用）
# ============================================================


def _self_test():
    """开发自检：从 .env / 环境变量读 cookie，跑一次最简调用"""
    cookie = os.getenv("COPILOT_COOKIE", "").strip()
    if not cookie:
        sys.exit("⚠️ 没设 COPILOT_COOKIE 环境变量")

    cfg = CopilotConfig(
        base_url="https://api-whale.data.mioffice.cn",
        cookie=cookie,
        project_id="10125971",
        os_data_id="10125971",
    )
    executor = CopilotExecutor(cfg)

    instruction = (
        "看板标题：自测看板\n"
        "语义模型：dm_user_module_behavior（ID: 502723）\n"
        "图表：\n"
        "  - DAU 趋势 — 折线图，按 module 展示 uv\n"
    )
    result = executor.execute_full(
        instruction_text=instruction,
        model_id="502723",
        dashboard_name=f"自测看板_{int(time.time())}",
    )

    print("\n" + "=" * 60)
    print(f"success      = {result.success}")
    print(f"dashboard_id = {result.dashboard_id}")
    print(f"os_menu_id   = {result.os_menu_id}")
    print(f"dashboard_url= {result.dashboard_url}")
    print(f"ai_message   = {(result.ai_message or '')[:200]}")
    if result.error:
        print(f"error        = {result.error}")
    print(f"events ({len(result.events)}):")
    for e, _ in result.events:
        print(f"  - {e}")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
