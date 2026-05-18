# 安装与首次接入

> 这份文档面向**第一次配环境**的人。配完一遍之后，日常使用看 [USAGE.md](USAGE.md)。

## 前置要求

| 项 | 说明 |
|---|---|
| 小米内网 | VPN 或办公网。需访问 `*.mi.com` / `*.mioffice.cn` 系列内网域名（数据平台、LLM 网关、BI 平台） |
| Python | 3.11+ |
| 浏览器 | Chrome / Edge，用于登录 [data.mioffice.cn](https://data.mioffice.cn) 抓 `COPILOT_COOKIE` |
| 飞书账号 | 企业账号，用于创建/管理飞书机器人应用 |

---

## 1. 克隆与依赖

```powershell
# 进项目目录（路径按你本地实际填）
cd C:\Users\Kai\.workbuddy\skills\dashboard-agent\my-dashboard-skills

# 安装 Python 依赖
pip install openai httpx python-dotenv requests lark-oapi curl-cffi
```

依赖清单：

| 包 | 用途 |
|---|---|
| `openai` ≥ 1.0 | LLM API 调用（OpenAI SDK 兼容协议） |
| `httpx` ≥ 0.25 | HTTP 客户端 |
| `python-dotenv` ≥ 1.0 | 加载 `.env` |
| `requests` ≥ 2.28 | 数据平台 / BI 平台 API |
| `lark-oapi` | 飞书长连接 SDK |
| `curl-cffi` | TLS 指纹模拟（编辑助手直连建图需要） |

---

## 2. 配置 `scripts/config.json`

这是**主配置**，所有凭证和默认参数都在这里。配置文件优先级**高于**环境变量。

```json
{
  "data_platform": {
    "base_url": "https://proxy-service-http-cnbj1-dp.api.xiaomi.net",
    "catalog": "iceberg_zjyprc_hadoop",
    "schema": "meta",
    "engine": "Spark",
    "token": "你的数据平台 token"
  },
  "bi_platform": {
    "enabled": "plan",
    "base_url": "https://api-smp.dt.mi.com",
    "api_prefix": "/os",
    "space_id": "11319",
    "creator": "ankaiwen1"
  },
  "llm": {
    "model": "xiaomi/Qwen3-235B-A22B-Instruct-2507",
    "api_key": "你的 LLM API key",
    "base_url": "https://api.llm.mioffice.cn/v1",
    "temperature": 0.1
  },
  "copilot": {
    "enabled": true,
    "base_url": "https://api-whale.data.mioffice.cn",
    "web_origin": "https://data.mioffice.cn",
    "project_id": "10125971",
    "os_data_id": "10125971",
    "owner": "ankaiwen1",
    "parent_menu_id": "375083",
    "base_os_menu_id": "dashboard_1",
    "impersonate": "chrome146"
  },
  "sql_validation": false
}
```

### 字段说明

#### `data_platform`（数据平台 API）

| 字段 | 必填 | 说明 |
|---|---|---|
| `base_url` | ✅ | 默认值即可 |
| `catalog` / `schema` | 否 | SQL 里用三级表名时可省 |
| `engine` | ✅ | **必须 `"Spark"`**，Presto 会触发重写器 400 报错 |
| `token` | ✅ | 数据平台后台申请 |

#### `bi_platform`（BI 推送）

| 字段 | 说明 |
|---|---|
| `enabled` | `"plan"`（默认，仅出方案文档） / `"publish"`（发布到 BI 平台） |
| `space_id` / `creator` | 推送模式必填 |
| `base_url` / `api_prefix` | 默认值即可 |

#### `llm`

| 字段 | 说明 |
|---|---|
| `model` | 默认 `xiaomi/Qwen3-235B-A22B-Instruct-2507`（小米网关）。备选：`xiaomi/deepseek-v3.1`；硅基流动 `deepseek-ai/DeepSeek-V4-Flash` |
| `base_url` | 小米网关 `https://api.llm.mioffice.cn/v1`；硅基流动 `https://api.siliconflow.cn/v1` |
| `api_key` | 对应平台申请 |
| `temperature` | 默认 0.1（建议保持，输出稳定） |

#### `copilot`（BI 编辑助手直连建图，5月15日上线）

| 字段 | 说明 |
|---|---|
| `enabled` | `true` 启用自动建图（Pipeline 跑完后调编辑助手 API 真把看板搭出来）；`false` 跳过 |
| `base_url` | 编辑助手 API（`api-whale.data.mioffice.cn`） |
| `web_origin` | BI 前端域名（用于伪造 Origin/Referer 请求头） |
| `project_id` / `os_data_id` / `owner` | BI 平台空间标识 |
| `parent_menu_id` / `base_os_menu_id` | 自动建图时新看板挂在哪个目录下 |
| `impersonate` | curl_cffi TLS 指纹，固定 `chrome146` |

> 自动建图前置条件：`copilot.enabled=true` **且** 当次运行是 publish 模式 **且** `COPILOT_COOKIE` 有效。否则会自动降级为只发方案文档。

#### `sql_validation`

| 字段 | 说明 |
|---|---|
| `sql_validation` | `true` 启用 SQL 试跑校验；`false` 跳过。也可在自然语言里说"试跑/不试跑"覆盖 |

---

## 3. 配置 `scripts/.env`

`.env` 放飞书凭证 + BI 编辑助手 cookie，**不进 git**。

```powershell
# 首次：从模板复制
Copy-Item scripts\.env.example scripts\.env

# 之后用编辑器打开 scripts\.env 填值
```

### 3.1 飞书凭证

```ini
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

去 [飞书开放平台](https://open.feishu.cn/app) → 你的应用 → **凭证与基础信息** 复制 App ID / App Secret。

### 3.2 `COPILOT_COOKIE`（自动建图必需）

`COPILOT_COOKIE` 是 BI 编辑助手的登录态。**有效期约 1 天**，过期后自动建图会失败（pipeline 仍会出方案文档，但不会真建看板）。

#### 抓取步骤

1. 浏览器打开 [data.mioffice.cn](https://data.mioffice.cn)，**保持登录状态**
2. 按 **F12** 打开 DevTools，切到 **Network**（网络）标签
3. 在 BI 页面里随便点一下（比如打开任意看板），Network 出现一堆请求
4. **任选一个请求**（推荐 host 是 `data.mioffice.cn` 或 `api-whale.data.mioffice.cn` 的）
5. 右侧 **Headers** 标签 → 滚到 **Request Headers** → 找 `Cookie:` 那行
6. 在 Cookie 值上**右键 → Copy value**（不要拖蓝复制，DevTools 视觉换行可能被带进剪贴板）
7. 粘贴到 `.env`：

```ini
COPILOT_COOKIE=粘贴整段，不带 "Cookie:" 前缀，不加引号
```

#### 验证 cookie 是否好用

```powershell
python scripts/check_cookie.py
```

输出含义：

| 输出 | 含义 |
|---|---|
| ✅ Cookie 有效，剩余 X 小时 | 可以用 |
| ⚠️ 即将过期：剩 X 分钟 | 1 小时内会过期，建议现在重抓 |
| ❌ Cookie 已过期 | 重抓 |
| ❌ 没找到 _aegis_cas_p | 复制不全 / 来源不对，重抓 |
| ❌ 中间有换行 | `.env` 里 `COPILOT_COOKIE=` 那行被分成多行了，删掉换行合成一行 |

`check_cookie.py` 完全离线，仅解码 cookie 里 `_aegis_cas_p`（小米 CAS JWT）的 `exp` 时间戳，不发任何 HTTP，无副作用。

---

## 4. 飞书应用接入

> 已经有可用的飞书机器人就跳过这一节。下面是从零创建。

### 4.1 创建自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app)
2. **创建企业自建应用**，填名字（如"看板助手"）+ 简介 + Logo
3. 拿到 **App ID** 和 **App Secret**，填入 `scripts/.env`（见上面 3.1）

### 4.2 配置权限

左侧菜单 → **权限管理**，搜索并开启：

| 权限标识 | 用途 |
|---|---|
| `im:message` | 接收 / 发送消息 |
| `im:chat:readonly` | 读群组信息 |
| `im:resource` | 上传文件 / 图片（HTML 方案文档） |
| `im:message:send_as_bot` | 以机器人身份发消息 |

部分权限需要管理员审批，选「仅管理员可用」可加快通过。

### 4.3 启用机器人能力

左侧菜单 → **添加应用能力** → 启用 **机器人**。

### 4.4 不需要事件订阅 URL

> ⚠️ 与早期版本不同，本项目使用 **lark long connection**（websocket 主动连飞书服务器，由 [scripts/feishu_orchestrator.py:1657](scripts/feishu_orchestrator.py#L1657) 的 `cli.start()` 启动），**不需要 webhook 反向 URL，也不需要 ngrok / Cloudflare Tunnel 内网穿透**。
>
> 飞书后台的"事件订阅 URL"留空即可，但你需要在「事件与回调」里**订阅 `im.message.receive_v1` 事件**——长连接消费的就是这个事件流。

### 4.5 加机器人到测试群

1. 飞书新建一个测试群
2. 群设置 → 机器人 → 添加 → 搜索你的应用名字 → 添加

---

## 5. 验证安装

按顺序跑下面 3 个命令，每一步都通过才算装好。

### 5.1 Cookie 健检

```powershell
python scripts/check_cookie.py
```

应输出 ✅。失败回到 3.2 重抓。

### 5.2 CLI 直跑（无飞书、无试跑、无推送）

```powershell
python scripts/run_pipeline.py --natural-input "测试一个简单看板，数据源 dwd_user_module_page_view" --no-sql-test --mode plan --output ./test_output
```

应在 `./test_output/` 生成 `solution.md` + `solution.html`。

### 5.3 飞书编排服务

```powershell
python scripts/feishu_orchestrator.py
```

控制台应出现：

```
[2026-05-18 ...] 等待连接飞书服务器...
[Lark] [2026-05-18 ...] [DEBUG] ping success [conn_id=...]
[Lark] [2026-05-18 ...] [DEBUG] receive pong [conn_id=...]
```

`ping success` 反复出现就是已连上。这时去测试群 @ 机器人发个简单需求验证端到端：

```
@看板助手 帮我做一个 DAU 趋势看板
```

预期：30 秒内收到「收到！正在生成看板方案...」+ 进度卡片走完 6 步 + 收到方案文档。

---

## 6. 故障排查

| 现象 | 最可能原因 | 解决 |
|---|---|---|
| `ConnectionError` / DNS 解析失败 | 没连小米内网 | 连 VPN |
| `check_cookie.py` 报 ❌ Cookie 已过期 | 真过期了 | 浏览器重新登 [data.mioffice.cn](https://data.mioffice.cn) → 重抓 cookie 写入 `.env` |
| `check_cookie.py` 报中间有换行 | 复制时把 DevTools 视觉换行带进来了 | 用 DevTools 右键 Copy value 而不是拖蓝复制；或编辑器里删掉 `COPILOT_COOKIE=` 那行的所有换行 |
| 编排服务启动报 `import lark` 失败 | 没装 lark-oapi | `pip install lark-oapi` |
| 编排服务起来了但 @ 机器人没反应 | 应用权限没审批 / 机器人没加群 / `FEISHU_APP_SECRET` 配错 | 检查飞书后台权限审批状态、群里有没有机器人、`.env` 拼写 |
| Pipeline 跑到一半"自动建图未启用：缺少 COPILOT_COOKIE" | cookie 失效了 | 重抓 cookie |
| SQL 试跑报 401 / 403 | 数据平台 token 过期 | 申请新 token 改 `config.json` |
| LLM 调用报 401 | LLM api_key 失效 | 极少见，去 mioffice 后台续 |
| Windows 控制台中文乱码 | GBK 编码 | 编排服务和 `check_cookie.py` 已自动 UTF-8。其他脚本可加 `$env:PYTHONIOENCODING="utf-8"` |
| 终端 `Ctrl+C` 后不返回提示符 | lark SDK 非 daemon 线程没退干净 | 再按一次 `Ctrl+C` 强行退出（已知现象） |

---

## 7. 文件清单

| 文件 | 是否进 git |
|---|---|
| `scripts/config.json` | ❌ gitignored（含 token / api_key） |
| `scripts/.env` | ❌ gitignored（含飞书 secret / cookie） |
| `scripts/.env.example` | ✅ 模板 |
| 其他源码 | ✅ |

> 配完之后，日常使用看 [USAGE.md](USAGE.md)。
