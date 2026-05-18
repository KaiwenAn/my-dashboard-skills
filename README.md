# Dashboard Agent

> 在飞书 @ 机器人发一句话，自动生成 SQL + 搭建 BI 看板。

数据分析师提效工具：把"想做一个看板"到"看板真出现在 BI 平台"的整条链路用 6 个 Agent 串起来，跑完平均 1-5 分钟。

## 它能做什么

- **飞书机器人入口**：在测试群 @ 机器人发自然语言需求，比如"用推送模式做一个 DAU 趋势看板，数据源是 dwd_user_module_page_view，要试跑"
- **6-Agent Pipeline**：需求解析 → 语义模型 SQL → BI 推送 → 图表设计 → 看板指令 → 方案文档生成
- **4 条主路径**（按需求严谨度选）：

  | 路径 | 触发 | 耗时 | 产出 |
  |---|---|---|---|
  | 推送 + 试跑 | 「用推送模式...要试跑」 | 3-5 min | 方案 + BI 看板（数据已校验） |
  | 推送 + 不试跑 | 「用推送模式...」 | 1-2 min | 方案 + BI 看板（待验证） |
  | 方案 + 试跑 | 「...要试跑」 | 1.5-3 min | 方案 + 校验过的 SQL |
  | 方案 + 不试跑 | 「做一个...」（默认） | 30-60 s | 方案文档（探索性） |

- **失败时自学**：SQL 试跑失败会把 Spark 报错（错列名、候选字段、行号）注入给 LLM，让它自己改对，最多重试 3 次

## 快速链接

| 想干什么 | 看哪儿 |
|---|---|
| 第一次配环境 | [INSTALL.md](INSTALL.md) |
| 日常使用 / 知道怎么发需求 | [USAGE.md](USAGE.md) |
| 开机后服务挂了怎么启 | [USAGE.md](USAGE.md) 「开机 / 长期未用 启动 Checklist」一节 |
| Cookie 是不是过期了 | `python scripts/check_cookie.py` |
| 想读架构 / 历史 | [docs/](docs/) |

## 项目结构

```
my-dashboard-skills/
├── README.md                       # 本文件
├── INSTALL.md                      # 安装与首次接入
├── USAGE.md                        # 日常使用指南
│
├── src/                            # 核心模块
│   ├── agents.py                   # 6 个 Agent 实现 + Pipeline 顺序
│   ├── pipeline.py                 # Pipeline 编排引擎
│   ├── llm.py                      # LLM 客户端封装
│   ├── data_platform_api.py        # 数据平台 HTTP 客户端（DESCRIBE / SQL 试跑）
│   ├── bi_api.py                   # BI 平台推送 API
│   ├── copilot_executor.py         # BI 编辑助手直连建图
│   └── renderer.py                 # Markdown → HTML 渲染
│
├── prompts/                        # Agent system prompt 模板
│   ├── requirements-parser-agent.md
│   ├── semantic-model-agent.md
│   ├── chart-design-agent.md
│   ├── instruction-generator-agent.md
│   ├── solution-generator-agent.md
│   └── bi-push-agent.md
│
├── scripts/                        # 入口与工具脚本
│   ├── feishu_orchestrator.py      # 飞书编排服务（核心，常驻进程）
│   ├── run_pipeline.py             # CLI 入口（绕开飞书，直跑 pipeline）
│   ├── nl_converter.py             # 自然语言 → 结构化输入
│   ├── check_cookie.py             # COPILOT_COOKIE 健检工具
│   ├── config.json                 # 主配置（凭证 / 模式 / 模型）
│   ├── .env                        # 环境变量（飞书凭证 / Cookie，gitignored）
│   └── .env.example                # .env 模板
│
├── docs/                           # 架构 / 历史 / 方案文档
│   ├── 项目价值与使用场景.md         # 4 路径选型指南
│   ├── 需求路径全景.md              # 失败点排查全景图
│   ├── 迭代记录_2026-05-14.md       # 飞书集成 + 端到端 pipeline
│   ├── 迭代记录_2026-05-15.md       # BI 编辑助手直连 + Prompt v0.7
│   ├── 迭代记录_2026-05-18.md       # 错误注入修复 + close API + 文档重写
│   ├── 方案_提高SQL试跑通过率.md     # SQL 通过率优化路线
│   └── PoC_编辑助手直连_2026-05-15.md # 编辑助手 9 endpoint 逆向纪要
│
├── references/examples/            # JSON 输入示例
├── tests/                          # 单元测试
├── output/                         # Pipeline 默认输出目录
└── poc/diag/                       # SQL 试跑失败诊断转储
```

## 当前状态

- **运行环境**：小米内网（VPN 或办公网），Python 3.11+
- **默认 LLM**：`xiaomi/Qwen3-235B-A22B-Instruct-2507`（小米网关）
- **数据平台**：iceberg / Spark
- **BI 平台**：data.mioffice.cn（含编辑助手直连建图）
- **入口**：飞书机器人（默认）/ CLI（高级）

## 维护

ankaiwen1（小米）。问题 / 反馈见 commit log 与 [docs/](docs/) 下的迭代记录。
