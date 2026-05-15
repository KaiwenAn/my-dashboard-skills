# 飞书机器人接入指南

从零开始，将飞书群消息接入 dashboard-agent pipeline。

## 架构概览

```
飞书群 @看板助手 → 飞书事件订阅 → Orchestrator(FastAPI) → dashboard-agent Pipeline → 飞书群回传
```

核心组件：
- **feishu_orchestrator.py** — 编排服务，接收飞书消息、调用 pipeline、推回结果
- **dev_webhook.py** — 本地开发辅助工具
- **.env** — 环境变量配置（从 .env.example 复制）

---

## 📋 当前进度 & 审批后操作清单

### ✅ 已完成
1. ~~创建飞书自建应用~~ — App ID / App Secret 已获取
2. ~~编写编排服务~~ — `feishu_orchestrator.py` 已完成并本地测试通过
3. ~~修复 Windows GBK 编码问题~~ — 自动 UTF-8 输出
4. ~~添加 .env 文件支持~~ — 无需每次手动设置环境变量

### ⏳ 等待审批通过
- 飞书应用审批中

### 🔲 审批通过后立即操作（按顺序）

#### A. 开启机器人能力
1. 打开 https://open.feishu.cn/app → 进入你的应用
2. 左侧菜单 → 「添加应用能力」→ 开启「机器人」

#### B. 配置权限
左侧菜单 → 「权限管理」，搜索并开启以下权限：

| 权限 | 权限标识 | 用途 |
|------|----------|------|
| 获取与发送单聊、群组消息 | im:message | 收发消息 |
| 获取群组信息 | im:chat:readonly | 获取群信息 |
| 上传文件/图片 | im:resource | 上传HTML文件 |
| 获取与发送单聊消息 | im:message:send_as_bot | 机器人发消息 |

> ⚠️ 部分权限可能需要审批，选择「仅管理员可用」可加快审批

#### C. 配置事件订阅
1. 左侧菜单 → 「事件订阅」
2. 添加事件：`im.message.receive_v1`（接收消息）
3. 配置请求地址（见下方「内网穿透」章节）
4. 记录 **Verification Token**（可选，用于安全校验）

#### D. 配置 .env 文件
```bash
cd scripts/
cp .env.example .env
# 编辑 .env，填入实际的 App ID 和 App Secret
```

#### E. 启动编排服务 + 内网穿透
```bash
# 终端1：启动编排服务
python scripts/feishu_orchestrator.py

# 终端2：启动内网穿透（见下方方案选择）
ngrok http 8080
```

#### F. 填写事件订阅 URL
复制穿透工具给出的公网 URL，拼上 `/webhook/feishu`，填入飞书事件订阅。
飞书会发 challenge 验证，编排服务已自动处理。

#### G. 添加机器人到测试群
1. 飞书创建测试群
2. 群设置 → 添加机器人 → 搜索「看板助手」→ 添加

#### H. 端到端测试
在群里 @看板助手 发送：
```
@看板助手 帮我做一个用户行为分析看板
```
预期：收到确认 → 等待2-5分钟 → 收到方案卡片 + HTML文件

---

## 内网穿透方案

### 方案1：ngrok（最简单，但小米内网可能受限）

```bash
# 安装
# 从 https://ngrok.com/download 下载
ngrok authtoken <your_token>

# 使用
ngrok http 8080
# 复制 Forwarding URL: https://xxxx.ngrok-free.app
```

⚠️ 免费版每次重启 URL 会变，需重新配置飞书事件订阅

### 方案2：Cloudflare Tunnel（推荐，免费稳定）

```bash
# 安装
winget install Cloudflare.cloudflared

# 使用（无需注册）
cloudflared tunnel --url http://localhost:8080
# 复制给出的 https://xxx.trycloudflare.com URL
```

优点：无需注册、URL 相对稳定、企业网一般不封

### 方案3：部署到小米内网服务器

如果有可用的内网服务器（如 DT 平台提供的），直接部署，URL 填内网地址即可。
无需穿透工具，最稳定。

---

## 启动编排服务

### 方式1：使用 .env 文件（推荐）

```bash
cd scripts/
cp .env.example .env    # 首次：复制并编辑 .env
python feishu_orchestrator.py
```

### 方式2：手动设置环境变量

**PowerShell：**
```powershell
$env:FEISHU_APP_ID = "cli_a5xxxxxxxxxxxxx"
$env:FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
python scripts/feishu_orchestrator.py
```

**CMD：**
```cmd
set FEISHU_APP_ID=cli_a5xxxxxxxxxxxxx
set FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
python scripts/feishu_orchestrator.py
```

### 健康检查

启动后浏览器访问 http://localhost:8080/health

---

## 测试完整链路

### 端到端测试步骤

1. 确认编排服务已启动（health 返回 ok）
2. 确认内网穿透在运行
3. 飞书事件订阅 URL 已配置且验证通过
4. 在测试群 @看板助手 发消息
5. 观察编排服务日志输出

### 预期流程

```
用户发送 → 编排服务收到 → 意图识别 → 回复"收到！正在生成..." 
→ 调用 pipeline(2-5min) → 发送卡片消息 → 上传HTML文件
```

### 排查问题

| 问题 | 排查方向 |
|------|----------|
| 服务没收到消息 | 检查事件订阅 URL 是否正确、穿透是否正常 |
| 消息收到了但不回复 | 检查 App ID / Secret 是否正确、权限是否已审批 |
| Pipeline 执行失败 | 检查 scripts/config.json 中的 LLM 配置 |
| 卡片消息发送失败 | 检查 im:message 权限是否已开启并审批通过 |
| Windows 编码报错 | 已修复：自动 UTF-8 输出，确保使用最新版编排服务 |

---

## 生产部署

### Docker 部署（推荐）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn httpx openai
CMD ["python", "scripts/feishu_orchestrator.py", "--host", "0.0.0.0", "--port", "8080"]
```

```bash
docker build -t dashboard-feishu .
docker run -d \
  -p 8080:8080 \
  -e FEISHU_APP_ID=cli_a5xxx \
  -e FEISHU_APP_SECRET=xxx \
  dashboard-feishu
```

### 更新飞书事件订阅 URL

将生产服务器的地址填入飞书事件订阅配置。

---

## 文件清单

| 文件 | 用途 |
|------|------|
| `scripts/feishu_orchestrator.py` | 编排服务（核心） |
| `scripts/dev_webhook.py` | 本地开发辅助 |
| `scripts/.env.example` | 环境变量模板 |
| `scripts/.env` | 环境变量（需自行创建，已 gitignore） |
| `scripts/run_pipeline.py` | Pipeline 执行脚本 |
| `scripts/config.json` | Pipeline 配置 |
| `FEISHU_SETUP.md` | 本文档 |

---

## 常见问题

### Q: 飞书事件验证失败？
A: 确保编排服务已启动，穿透工具正在运行，URL 拼写正确（`/webhook/feishu`）。

### Q: 小米内网无法使用 ngrok？
A: 推荐用 Cloudflare Tunnel（`cloudflared tunnel --url http://localhost:8080`），无需注册，一般不被封。或部署到小米内网服务器。

### Q: Pipeline 执行超时？
A: 默认超时 10 分钟，可以在 `feishu_orchestrator.py` 中修改 `timeout=600`。

### Q: Windows 下 print 报 UnicodeEncodeError？
A: 已修复。编排服务会自动设置 UTF-8 输出编码。如果仍有问题，启动前设置：
```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### Q: .env 文件在哪里？
A: 放在 `scripts/` 目录下，和 `feishu_orchestrator.py` 同级。从 `.env.example` 复制后填入实际值即可。
