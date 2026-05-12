# 安装说明

## 前置要求

- Python 3.11+
- pip
- 一个兼容 OpenAI SDK 的 LLM API Key（推荐 DeepSeek / 硅基流动）
- 数据平台访问权限（如需使用字段自动拉取和 SQL 试跑功能）

---

## 目录结构

```
my-dashboard-skills/
├── SKILL.md                      # Skill 描述文件（WorkBuddy 读取入口）
├── USAGE.md                      # 详细使用指南
├── INSTALL.md                    # 本文件
│
├── agents.py                     # Agent 模块（加载 Prompt 并执行）
├── llm.py                        # LLM 调用封装（OpenAI SDK 兼容）
├── pipeline.py                   # 编排引擎（Pipeline / Step / Context）
├── renderer.py                   # Markdown → HTML 渲染器
├── bi_api.py                     # BI 平台推送 API 客户端
├── data_platform_api.py          # 数据平台 API 客户端（DESCRIBE / SQL 执行）
│
├── prompts/                      # Agent System Prompt 模板（与核心模块同级）
│   ├── requirements-parser-agent.md
│   ├── semantic-model-agent.md
│   ├── bi-push-agent.md
│   ├── chart-design-agent.md
│   ├── instruction-generator-agent.md
│   └── solution-generator-agent.md
│
├── scripts/
│   ├── run_pipeline.py           # Pipeline 执行脚本（CLI 入口）
│   ├── nl_converter.py           # 自然语言转换层
│   ├── config.json               # 配置文件（需手动修改）
│   └── temp_describe.py          # 临时调试脚本
│
├── references/
│   ├── prompts/                  # Prompt 参考文档（给 AI Agent 阅读）
│   │   └── ...
│   └── examples/
│       └── ecommerce_daily.json  # 示例输入
│
└── tests/                        # 单元测试（需自行运行）
    └── ...
```

> 所有核心 Python 模块（agents.py、llm.py、pipeline.py 等）与 prompts/ 目录同级。
> 运行 `run_pipeline.py` 时会自动将 `scripts/` 的父目录加入 `sys.path`，无需额外配置。

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
cd scripts && python -c "from llm import LLMClient; from pipeline import Pipeline; from agents import RunMode; print('OK')"

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


