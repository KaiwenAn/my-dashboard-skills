# 安装说明

## 前置要求

- Python 3.11+
- pip
- 一个兼容 OpenAI SDK 的 LLM API Key（推荐 DeepSeek / 硅基流动）
- 数据平台访问权限（如需使用字段自动拉取和 SQL 试跑功能）

---

## 安装步骤

### 1. 放置 Skill 文件

将 `my-dashboard-skills/` 整个文件夹放到 WorkBuddy 的 skills 目录下：

```
~/.workbuddy/skills/dashboard-agent/my-dashboard-skills/
```

放置后的目录结构应为：

```
~/.workbuddy/skills/dashboard-agent/
└── my-dashboard-skills/
    ├── SKILL.md              # Skill 描述文件（WorkBuddy 读取入口）
    ├── USAGE.md              # 详细使用指南
    ├── INSTALL.md            # 本文件
    ├── scripts/
    │   ├── run_pipeline.py   # Pipeline 执行脚本
    │   ├── nl_converter.py   # 自然语言转换层
    │   └── config.json       # 配置文件（需手动修改）
    └── references/
        ├── prompts/          # Agent System Prompt 模板
        │   ├── requirements-parser-agent.md
        │   ├── semantic-model-agent.md
        │   ├── bi-push-agent.md
        │   ├── chart-design-agent.md
        │   ├── instruction-generator-agent.md
        │   └── solution-generator-agent.md
        └── examples/
            └── ecommerce_daily.json
```

### 2. 放置核心依赖模块（必须）

Pipeline 脚本依赖以下 Python 模块，它们位于独立的工作空间中，需要一并复制：

```
# 源目录（这些文件当前所在位置，例如你的开发环境）
# 例如：c:\Users\YourName\WorkBuddy\20260427134240\

# 需要复制的文件：
llm.py                 # LLM 调用封装（OpenAI SDK 兼容）
pipeline.py            # 编排引擎（Pipeline / Step / Context）
agents.py              # Agent 模块（加载 Prompt 并执行）
renderer.py            # Markdown → HTML 渲染器
bi_api.py              # BI 平台推送 API 客户端
data_platform_api.py   # 数据平台 API 客户端（DESCRIBE / SQL 执行）
```

**将这些文件复制到 Pipeline 的 `sys.path` 可达的目录**，有两种方式：

#### 方式 A：放到 Skill 的 scripts 目录（推荐）

```
my-dashboard-skills/scripts/
├── run_pipeline.py
├── nl_converter.py
├── config.json
├── llm.py                 ← 复制
├── pipeline.py            ← 复制
├── agents.py              ← 复制
├── renderer.py            ← 复制
├── bi_api.py              ← 复制
└── data_platform_api.py   ← 复制
```

然后修改 `run_pipeline.py` 中的 `WORKSPACE_DIR` 指向 `scripts/` 目录：

```python
# 原代码（第34行）：
_default_workspace = str(Path.home() / "WorkBuddy" / "20260427134240")

# 改为：
_default_workspace = str(Path(__file__).parent)
```

#### 方式 B：通过环境变量指定

将依赖模块放到任意目录，然后设置环境变量：

```bash
# Windows PowerShell
$env:WORKSPACE_DIR = "C:\path\to\your\modules"

# Linux/macOS
export WORKSPACE_DIR="/path/to/your/modules"
```

### 3. 复制 Prompt 文件（必须）

`agents.py` 在运行时会从 `prompts/` 目录加载 System Prompt 文件。确保以下文件与 `agents.py` 同级：

```
<你的模块目录>/
├── agents.py
└── prompts/
    ├── requirements-parser-agent.md
    ├── semantic-model-agent.md
    ├── bi-push-agent.md
    ├── chart-design-agent.md
    ├── instruction-generator-agent.md
    └── solution-generator-agent.md
```

> 注意：Skill 的 `references/prompts/` 是给 AI Agent 阅读的参考文档，`agents.py` 实际加载的是模块目录下的 `prompts/` 文件夹。两者内容应保持一致。

### 4. 安装 Python 依赖

```bash
pip install openai httpx python-dotenv requests
```

完整的依赖清单：

| 包名 | 最低版本 | 用途 |
|------|---------|------|
| `openai` | ≥1.0.0 | LLM API 调用（OpenAI SDK 兼容） |
| `httpx` | ≥0.25.0 | HTTP 客户端（LLM / BI / 数据平台） |
| `python-dotenv` | ≥1.0.0 | 环境变量加载 |
| `requests` | ≥2.28.0 | HTTP 请求（BI API / 数据平台 API） |

> 如果不需要 BI 推送功能，`requests` 可选。

### 5. 配置凭证

编辑 `scripts/config.json`，填入你自己的凭证：

```json
{
  "_comment": "配置文件 - 请填入你自己的token和api_key",
  "data_platform": {
    "base_url": "https://proxy-service-http-cnbj1-dp.api.xiaomi.net",
    "catalog": "iceberg_zjyprc_hadoop",
    "schema": "meta",
    "engine": "Spark",
    "token": "你的数据平台token"
  },
  "bi_platform": {
    "base_url": "https://api-smp.dt.mi.com",
    "api_prefix": "/os"
  },
  "llm": {
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "api_key": "你的LLM API Key",
    "base_url": "https://api.siliconflow.cn/v1",
    "temperature": 0.1
  }
}
```

**凭证说明：**

| 配置项 | 必填 | 说明 | 获取方式 |
|--------|------|------|----------|
| `llm.api_key` | 是 | LLM 服务 API Key | [硅基流动](https://siliconflow.cn) 注册获取 |
| `llm.model` | 否 | 默认 `deepseek-ai/DeepSeek-V4-Flash` | 可更换为其他兼容模型 |
| `llm.base_url` | 否 | LLM API 地址 | 默认硅基流动，可改为 DeepSeek 官方等 |
| `data_platform.token` | 推荐 | 数据平台访问 Token | 内部数据平台获取 |
| `bi_platform.base_url` | 否 | BI 平台 API 地址 | 默认小米 BI 平台 |

**也可使用环境变量（优先级低于 config.json）：**

| 环境变量 | 对应配置项 |
|----------|-----------|
| `DEEPSEEK_API_KEY` | `llm.api_key` |
| `HUNYUAN_API_KEY` | `llm.api_key`（备选） |
| `LLM_BASE_URL` | `llm.base_url` |
| `DATA_PLATFORM_TOKEN` | `data_platform.token` |
| `DATA_PLATFORM_BASE_URL` | `data_platform.base_url` |

---

## 验证安装

```bash
# 1. 确认模块导入正常
python -c "import sys; sys.path.insert(0, 'scripts'); from llm import LLMClient; from pipeline import Pipeline; from agents import RunMode; print('OK')"

# 2. 使用示例文件运行一次完整 Pipeline
python scripts/run_pipeline.py --input references/examples/ecommerce_daily.json --output ./test_output
```

如果看到 `Pipeline 完成!` 提示，说明安装成功。

---

## 配置优先级

```
config.json > 环境变量 > 代码默认值
```

| 配置项 | config.json | 环境变量 | 默认值 |
|--------|------------|---------|--------|
| LLM api_key | `llm.api_key` | `HUNYUAN_API_KEY` → `DEEPSEEK_API_KEY` | 无 |
| LLM base_url | `llm.base_url` | `LLM_BASE_URL` | SDK 默认 |
| LLM model | `llm.model` | - | `deepseek-ai/DeepSeek-V4-Flash` |
| 数据平台 token | `data_platform.token` | `DATA_PLATFORM_TOKEN` | 无 |
| 数据平台 engine | `data_platform.engine` | - | `Spark` |

---

## 注意事项

1. **`data_platform.engine` 必须设为 `"Spark"`**，使用 Presto 会报错
2. **Prompt 文件需与 `agents.py` 同级**：`agents.py` 使用 `os.path.dirname(__file__)` 定位 `prompts/` 目录
3. **LLM 模型需兼容 OpenAI SDK 格式**：支持硅基流动、DeepSeek、腾讯混元等
4. **BI 推送功能**：需要在输入 JSON 中提供 `bi_config`（含 `space_id` 和 `creator`），`datasource_id` 会自动获取

---

## 文件清单

分享 Skill 时需要包含的完整文件列表：

```
my-dashboard-skills/
├── SKILL.md                                          # Skill 描述
├── USAGE.md                                          # 使用指南
├── INSTALL.md                                        # 安装说明（本文件）
├── scripts/
│   ├── run_pipeline.py                               # Pipeline 入口
│   ├── nl_converter.py                               # 自然语言转换
│   ├── config.json                                   # 配置模板（敏感值已替换）
│   ├── llm.py                                        # [必须] LLM 封装
│   ├── pipeline.py                                   # [必须] 编排引擎
│   ├── agents.py                                     # [必须] Agent 模块
│   ├── renderer.py                                   # [必须] HTML 渲染
│   ├── bi_api.py                                     # [必须] BI 推送
│   ├── data_platform_api.py                          # [必须] 数据平台
│   └── prompts/                                      # [必须] Agent Prompt
│       ├── requirements-parser-agent.md
│       ├── semantic-model-agent.md
│       ├── bi-push-agent.md
│       ├── chart-design-agent.md
│       ├── instruction-generator-agent.md
│       └── solution-generator-agent.md
└── references/
    ├── prompts/                                      # 参考用 Prompt 副本
    │   ├── requirements-parser-agent.md
    │   ├── semantic-model-agent.md
    │   ├── bi-push-agent.md
    │   ├── chart-design-agent.md
    │   ├── instruction-generator-agent.md
    │   └── solution-generator-agent.md
    └── examples/
        └── ecommerce_daily.json                      # 示例输入
```

> 标注 `[必须]` 的文件当前位于外部工作空间 `WorkBuddy/20260427134240/`，分享前需复制到 `scripts/` 目录并修改路径引用。
