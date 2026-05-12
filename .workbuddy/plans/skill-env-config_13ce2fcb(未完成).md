---
name: skill-env-config
overview: 为 dashboard-agent skill 添加本地配置文件支持，让用户可以手动编辑 config.json 来配置所有环境变量，配置项优先于环境变量生效。
todos:
  - id: update-config-json
    content: 更新 config.json，增加 llm.api_key、llm.base_url、data_platform.token 等缺失字段，保留现有字段
    status: pending
  - id: update-run-pipeline
    content: 修改 run_pipeline.py 配置加载逻辑，实现配置文件 > 环境变量 > 默认值的优先级策略
    status: pending
    dependencies:
      - update-config-json
  - id: update-skill-md
    content: 更新 SKILL.md 配置说明章节，说明配置文件的使用方法和优先级
    status: pending
    dependencies:
      - update-config-json
      - update-run-pipeline
---

## 用户需求

运行 dashboard-agent skill 时，支持通过本地配置文件手动上传配置，不再依赖系统环境变量。需要支持全部配置项（LLM、数据平台等），且配置文件优先级高于环境变量。

## 核心功能

1. **LLM 配置**：支持 api_key、model、base_url、temperature 等全部 LLM 相关配置
2. **数据平台配置**：支持 base_url、token、engine、catalog、schema 等全部数据平台配置
3. **配置优先级**：配置文件 > 环境变量 > 默认值
4. **静默回退**：配置文件缺失时自动回退到环境变量，保证向后兼容

## 技术方案

### 改动文件

1. **`scripts/config.json`** - 扩展配置文件模板，增加 llm.api_key、llm.base_url 等缺失字段
2. **`scripts/run_pipeline.py`** - 修改配置加载逻辑，实现配置文件 > 环境变量 > 默认值优先级
3. **`SKILL.md`** - 更新配置说明文档，说明配置方式和使用方法

### 实现策略

采用「先读取配置文件，再按需回退到环境变量」的策略，保证：

- 配置文件存在时优先使用（显式配置）
- 配置文件缺失时静默回退到环境变量（向后兼容）
- 所有配置项统一使用相同的优先级策略

### 配置结构

```
{
  "llm": {
    "api_key": "",        // 新增：支持配置文件指定 API Key
    "base_url": "",       // 新增：支持配置文件指定 LLM 服务地址
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "temperature": 0.1
  },
  "data_platform": {
    "base_url": "https://proxy-service-http-cnbj1-dp.api.xiaomi.net",
    "token": "",          // 扩展：支持配置文件指定 Token
    "engine": "Spark",
    "catalog": "iceberg_zjyprc_hadoop",
    "schema": "meta"
  },
  "bi_platform": {
    "base_url": "https://api-smp.dt.mi.com",
    "api_prefix": "/os"
  }
}
```

### 优先级逻辑

```python
# LLM 配置
api_key = config_llm.get("api_key") or os.getenv("HUNYUAN_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
base_url = config_llm.get("base_url") or os.getenv("LLM_BASE_URL")
model = config_llm.get("model", "deepseek-ai/DeepSeek-V4-Flash")

# 数据平台配置
base_url = config_dp.get("base_url") or os.getenv("DATA_PLATFORM_BASE_URL")
token = config_dp.get("token") or os.getenv("DATA_PLATFORM_TOKEN")
engine = config_dp.get("engine", "Spark")
```