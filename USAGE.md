# 看板 Agent 使用指南

> 这份文档面向**日常使用**。第一次配环境看 [INSTALL.md](INSTALL.md)。

## 目录

- [快速开始](#快速开始)
- [4 条主路径](#4-条主路径)
- [Cookie 健康检查](#cookie-健康检查)
- [开机 / 长期未用启动 Checklist](#开机--长期未用启动-checklist)
- [进度卡片说明](#进度卡片说明)
- [输出物说明](#输出物说明)
- [常见错误 + 排查](#常见错误--排查)
- [高级用法](#高级用法)
- [更新日志](#更新日志)

---

## 快速开始

> 默认你已按 [INSTALL.md](INSTALL.md) 配置完。下面 30 秒走通：

```powershell
# 1. 连小米内网（VPN）
# 2. 检查 cookie 状态
python scripts/check_cookie.py        # 应输出 ✅ Cookie 有效

# 3. 启动飞书编排服务（常驻进程，不要关）
python scripts/feishu_orchestrator.py
# 看到 "[Lark] ping success" 反复出现就是连上了

# 4. 在飞书测试群 @ 机器人
```

飞书示例消息：

```
@看板助手 用推送模式做一个 DAU 趋势看板，
数据源是 iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view，要试跑
```

预期：30 秒内回「收到！正在生成看板方案...」+ 进度卡片走完 6 步 + 收到方案文档（Markdown + HTML）+ BI 看板链接（如果选了"推送"模式）。

---

## 4 条主路径

按需求严谨度选。**自然语言关键词决定模式**，无需改配置。

| 路径 | 触发关键词 | 耗时 | 产出 | 适合场景 |
|---|---|---|---|---|
| 🅰️ **推送 + 试跑** | 含「推送」+「试跑/校验」 | 3-5 min | 方案 + BI 看板（数据已校验） | 业务复盘看板、对外汇报、不能出错 |
| 🅱️ **推送 + 不试跑** | 含「推送」无「试跑」 | 1-2 min | 方案 + BI 看板（待验证） | 熟悉数据、快速迭代、第 N 次改同一看板 |
| 🅲 **方案 + 试跑** | 含「试跑」无「推送」 | 1.5-3 min | 方案 + 校验过的 SQL（不动 BI 平台） | 给业务方对齐方案 |
| 🅳 **方案 + 不试跑** | 都不含（默认） | 30-60 s | 方案文档 | 头脑风暴、探索 AI 方案空间 |

### 模式关键词识别规则

由 [scripts/nl_converter.py](scripts/nl_converter.py) 处理：

- **推送 vs 方案**：含「推送」/「publish」/「发布」 → 推送；含「方案」/「仅方案」/「不推送」 → 方案；都没说 → 走 `config.json` 的 `bi_platform.enabled`（默认 `"plan"`）
- **试跑 vs 不试跑**：含「试跑」/「校验」/「验证」/「测试」相关肯定句 → 试跑；含「不试跑」/「跳过校验」/「不需要验证」 → 不试跑；都没说 → 走 `config.json` 的 `sql_validation`（默认 `false`）
- 否定优先于肯定：「不要校验」会被识别为不试跑而非试跑

### 路径选型建议

详细决策树见 [docs/项目价值与使用场景.md](docs/项目价值与使用场景.md)。简化版：

- 关心**结果可靠** → 🅰️
- 关心**速度** → 🅱️
- 关心**先对齐再做** → 🅲
- 头脑风暴 → 🅳

---

## Cookie 健康检查

`COPILOT_COOKIE` **约 1 天过期**。过期后自动建图会失败，但 pipeline 仍能跑出方案文档。

### 用法

```powershell
python scripts/check_cookie.py
```

### 输出对照

| 输出 | 行动 |
|---|---|
| ✅ Cookie 有效，剩余 X 小时 | 继续 |
| ⚠️ 即将过期：剩 X 分钟 | 现在重抓，避免跑到一半挂掉 |
| ❌ Cookie 已过期 | 浏览器重登 [data.mioffice.cn](https://data.mioffice.cn) → 重抓 → 写入 `scripts/.env` |
| ❌ 没找到 _aegis_cas_p | 复制不全或来源错，重抓 |
| ❌ 中间有换行 | 删掉 `.env` 里 `COPILOT_COOKIE=` 那行的换行让它合一行 |

### 怎么重抓

详细步骤见 [INSTALL.md - 3.2](INSTALL.md#32-copilot_cookie自动建图必需)。简化版：

1. 浏览器登 [data.mioffice.cn](https://data.mioffice.cn)
2. F12 → Network → 任意请求 → Headers → Request Headers → Cookie
3. **右键 Copy value**（不要拖蓝复制）
4. 粘贴到 `scripts/.env` 的 `COPILOT_COOKIE=` 后面，**确保是单行**
5. 重启编排服务

---

## 开机 / 长期未用启动 Checklist

电脑重启 / 休眠多天后，按下面顺序：

```powershell
# 1. 连小米 VPN（数据平台、LLM 网关、BI 平台都是内网域名）
ping proxy-service-http-cnbj1-dp.api.xiaomi.net

# 2. 进项目目录
cd C:\Users\Kai\.workbuddy\skills\dashboard-agent\my-dashboard-skills

# 3. 检查 cookie（不绿就先重抓再启动）
python scripts/check_cookie.py

# 4. 启动编排服务（常驻进程）
python scripts/feishu_orchestrator.py

# 5. 飞书 @ 机器人发个简单需求验证
```

### 长时间没用后**很可能要刷新**的凭证

按过期概率从高到低：

| 凭证 | 位置 | 有效期 | 怎么刷 |
|---|---|---|---|
| 🔴 `COPILOT_COOKIE` | [scripts/.env](scripts/.env) | **约 1 天** | 浏览器重登 + 重抓（看上面 Cookie 健康检查） |
| 🟡 `data_platform.token` | [scripts/config.json](scripts/config.json) | 数月 / 不定 | 数据平台后台重新申请 |
| 🟢 `FEISHU_APP_ID/SECRET` | [scripts/.env](scripts/.env) | 长期 | 不用动 |
| 🟢 `LLM api_key` | [scripts/config.json](scripts/config.json) | 长期 | 不用动 |

---

## 进度卡片说明

发完需求 ~30 秒后，机器人会发一张进度卡片，**实时 PATCH 更新**（不刷屏）：

```
进度
☑ 需求解析       (12.3s)
☑ 语义模型       (101.9s)   ← 含 SQL 试跑
☐ BI 推送         …         ← 仅推送模式
☐ 图表设计        …
☐ 看板指令        …
☐ 方案生成        …
```

各步典型耗时：

| 步骤 | 耗时 | 说明 |
|---|---|---|
| 需求解析 | 10-30 s | LLM 调用，确认项识别 |
| 语义模型 | **100-200 s** | 整条 pipeline 大头：DESCRIBE 字段 + LLM 生成 SQL + 试跑（如启用） |
| BI 推送 | 5-15 s | HTTP 调用，无 LLM，仅推送模式有 |
| 图表设计 | 30-90 s | LLM 调用 |
| 看板指令 | 20-60 s | LLM 调用 |
| 方案生成 | 30-90 s | LLM 调用，输出 Markdown |

### SQL 试跑失败重试机制

启用试跑时，每个语义模型的 SQL 会在数据平台 dry run。失败有两层重试：

- **内层（[src/agents.py:386-471](src/agents.py#L386-L471)）**：单次试跑失败最多重试 3 次
  - 第 1 次失败：直接重试相同 SQL（兜底临时资源问题）
  - 第 2-3 次失败：把 Spark 报错（错列名、候选字段、行号）注入给 LLM，重新生成 SQL
- **外层（[src/pipeline.py:333](src/pipeline.py#L333)）**：Pipeline 级重试 3 次
- 最坏情况 3×3 = 9 次试跑都失败，才返回错误终止

> 错误注入链路在 2026-05-18 修复（之前注入的"错误信息"实际只有 5 个字符 `"SQL执行失败"`），现在 LLM 能拿到完整 Spark 报错，重试通过率显著提升。详见 [docs/迭代记录_2026-05-18.md](docs/迭代记录_2026-05-18.md)。

---

## 输出物说明

### 飞书机器人的产出

成功时机器人会发：

1. 进度卡片（最终态：6 步全 ☑）
2. **方案 Markdown 文档**（直接贴在群里）
3. **方案 HTML 文件**（上传为附件，可直接预览）
4. **BI 看板链接**（仅推送 + copilot.enabled 模式，且 cookie 有效）

### 本地文件（CLI 模式 / pipeline 内部）

```
output/
├── solution.md                    # 完整方案（Markdown）
├── solution.html                  # HTML 渲染版本
├── execution_summary.json         # 执行摘要（每步耗时、状态）
└── agent_outputs/                 # 每个 Agent 的中间产物
    ├── 1.requirements_parser.json
    ├── 2.semantic_model.json      # 含 SQL
    ├── 3.chart_design.json
    ├── 4.instruction_generator.json
    ├── bi_push_result.json        # 仅推送模式
    └── confirmation_items.json    # 待确认项汇总
```

### 调试转储

SQL 试跑失败时自动写到 `poc/diag/sql_fail_attempt{N}_{timestamp}.json`：

```json
{
  "retry_count": 1,
  "max_retry": 3,
  "failed_models": [{"model_name": "...", "error_message": "...", "sql": "..."}],
  "last_sql_test_error_injected": "..."
}
```

用于复盘"为什么 SQL 反复改不对"。

---

## 常见错误 + 排查

| 现象 | 原因 | 解决 |
|---|---|---|
| 飞书 @ 机器人没反应 | 编排服务没启动 / VPN 没连 | 启动 `feishu_orchestrator.py` + 确认 VPN |
| 终端报 `ConnectionError` / DNS 解析失败 | 没在内网 | 连 VPN |
| 「自动建图未启用：缺少 COPILOT_COOKIE」 | cookie 失效或没配 | `python scripts/check_cookie.py` 看状态，过期就重抓 |
| 「自动建图跳过：当前是方案模式」 | 你的需求里没说"推送" | 这是预期行为；想自动建图就在需求里说"推送模式" |
| 试跑反复失败 | SQL 真有 bug | 看 `poc/diag/sql_fail_attempt*.json` 转储里的 `error_message`（修复后会是真实 Spark 报错），按提示改需求或表选择 |
| SQL 试跑报 `403 / Token invalid` | 数据平台 token 过期 | 申请新 token 改 `config.json` |
| LLM 调用报 `401` | LLM api_key 失效 | 极少见，去 mioffice 后台续 |
| Pipeline 卡在某一步超过 5 分钟 | LLM 网关慢 / 网络抖 | 等待或重试；持续抖动看 LLM 网关状态 |
| 终端 Ctrl+C 后不回提示符 | lark SDK 非 daemon 线程 | 再按一次 Ctrl+C 强行退出（已知现象） |
| Windows 控制台中文乱码 | GBK 编码 | 编排服务和 `check_cookie.py` 已自动 UTF-8；其他脚本设 `$env:PYTHONIOENCODING="utf-8"` |
| 方案文档生成但内容很短 | LLM 4096-token 输出截断 | 看 [src/agents.py:924](src/agents.py#L924) 的 max_tokens 是否够 |

更详细的失败点排查全景图见 [docs/需求路径全景.md](docs/需求路径全景.md)。

---

## 高级用法

### CLI 直跑（绕开飞书）

适合自动化、批跑、调试。

```powershell
# 自然语言输入
python scripts/run_pipeline.py --natural-input "做一个 DAU 趋势看板，数据源 dwd_user_module_page_view"

# 从文件读取需求
python scripts/run_pipeline.py --natural-input-file requirement.txt

# JSON 结构化输入（精确控制）
python scripts/run_pipeline.py --input references/examples/ecommerce_daily.json

# 自定义输出目录
python scripts/run_pipeline.py --natural-input "..." --output ./my_output
```

### CLI 参数

| 参数 | 说明 |
|---|---|
| `--input` / `-i` | JSON 输入文件路径 |
| `--natural-input` / `-n` | 自然语言输入字符串 |
| `--natural-input-file` | 从文件读自然语言输入 |
| `--output` / `-o` | 输出目录（默认 `./output`） |
| `--mode` / `-m` | `plan` / `publish`，强制覆盖所有默认 |
| `--no-sql-test` | 跳过 SQL 试跑 |

### 配置覆盖优先级

#### BI 推送模式（4 层）

```
--mode 参数  >  user_input.bi_config  >  自然语言关键词  >  config.json bi_platform.enabled
```

#### SQL 校验开关（3 层）

```
user_input.enable_sql_test  >  --no-sql-test 或 自然语言关键词  >  config.json sql_validation
```

#### LLM 凭证（3 层）

```
config.json llm.api_key  >  HUNYUAN_API_KEY  >  DEEPSEEK_API_KEY
```

每一层都是「能覆盖低层」，不是「强制开启」。

### 退出编排服务

- **一次 `Ctrl+C`**：触发清理钩子（把进度卡片标为「已中止」，向群里发提示），然后 `sys.exit(0)`
- 终端如果没立即回到提示符 → **再按一次 `Ctrl+C`** 强行退出

> 已知现象：lark SDK 内部启的非 daemon 线程会拖住进程一段时间。详见 [docs/迭代记录_2026-05-18.md](docs/迭代记录_2026-05-18.md)「已知问题」。

### 默认行为切换

如果想让默认就是「推送+试跑」模式，改 [scripts/config.json](scripts/config.json)：

```json
"bi_platform": { "enabled": "publish", ... },
"sql_validation": true
```

之后用户不说"推送/试跑"也会走严谨路径。

---

## 更新日志

| 日期 | 内容 |
|---|---|
| 2026-05-18 | SQL 试跑错误注入修复（拿到真实 Spark 报错） / close API 修复（消 404 噪音） / 飞书需求回显扩到 500 字 / 新增 `check_cookie.py` Cookie 健检工具 / 用户文档全量重写。详见 [docs/迭代记录_2026-05-18.md](docs/迭代记录_2026-05-18.md) |
| 2026-05-15 | BI 编辑助手直连建图（自动搭看板，9 endpoint 逆向） / 飞书 Agent 集成 / 语义模型 Prompt v0.7（Spark SQL 方言 + 嵌套反模式 + column_types 注入） / SQL 失败诊断转储。详见 [docs/迭代记录_2026-05-15.md](docs/迭代记录_2026-05-15.md) |
| 2026-05-14 | 飞书机器人 lark long connection 接入 / 6-Agent pipeline 完整 / 错误信息业务化。详见 [docs/迭代记录_2026-05-14.md](docs/迭代记录_2026-05-14.md) |
| v1.1.1 / 2026-05-12 | SQL 校验开关独立解耦（`--no-sql-test` / 关键词 / `config.sql_validation`） |
| v1.1 / 2026-05-12 | BI 推送模式自动切换（`--mode` / `bi_config` / 关键词 / `config.bi_platform.enabled`） |
| v1.0 / 2026-05-12 | 初始版本，支持 6-Agent 流水线 |
