"""
飞书 Webhook 本地开发辅助工具

使用 ngrok 暴露本地服务到公网，方便飞书事件回调。

使用前：
    1. 安装 ngrok: https://ngrok.com/download
    2. 注册 ngrok 账号并配置 authtoken: ngrok authtoken <your_token>

启动方式：
    python dev_webhook.py

启动后会自动：
    1. 启动 feishu_orchestrator 服务 (localhost:8080)
    2. 启动 ngrok 隧道
    3. 打印飞书事件订阅需要填写的 URL
"""

import subprocess
import sys
import time
import json
import httpx
from pathlib import Path

ORCHESTRATOR_SCRIPT = Path(__file__).parent / "feishu_orchestrator.py"
NGROK_API = "http://127.0.0.1:4040/api"


def check_ngrok():
    """检查 ngrok 是否已安装"""
    try:
        result = subprocess.run(
            ["ngrok", "version"],
            capture_output=True, text=True, timeout=5
        )
        print(f"✅ ngrok 已安装: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        print("❌ ngrok 未安装")
        print("   请访问 https://ngrok.com/download 下载安装")
        print("   安装后运行: ngrok authtoken <your_token>")
        return False


def get_ngrok_url():
    """获取 ngrok 隧道的公网 URL"""
    try:
        resp = httpx.get(f"{NGROK_API}/tunnels", timeout=5)
        data = resp.json()
        for tunnel in data.get("tunnels", []):
            if tunnel.get("proto") == "https":
                return tunnel["public_url"]
    except Exception:
        pass
    return None


def main():
    print("=" * 60)
    print("  飞书看板助手 - 本地开发环境")
    print("=" * 60)
    print()

    # 检查 ngrok
    if not check_ngrok():
        sys.exit(1)

    # 检查编排服务脚本
    if not ORCHESTRATOR_SCRIPT.exists():
        print(f"❌ 编排服务脚本不存在: {ORCHESTRATOR_SCRIPT}")
        sys.exit(1)

    print()
    print("启动步骤：")
    print()
    print("1️⃣  先启动编排服务（新终端）：")
    print(f"    python {ORCHESTRATOR_SCRIPT.name}")
    print()
    print("2️⃣  再启动 ngrok 隧道（新终端）：")
    print("    ngrok http 8080")
    print()
    print("3️⃣  复制 ngrok 给出的 Forwarding URL，格式如：")
    print("    https://xxxx-xxxx.ngrok-free.app")
    print()
    print("4️⃣  在飞书开放平台配置事件订阅 URL：")
    print("    https://xxxx-xxxx.ngrok-free.app/webhook/feishu")
    print()
    print("=" * 60)
    print()
    print("⚠️  注意：")
    print("   - ngrok 免费版每次重启 URL 会变，需要重新配置飞书")
    print("   - 小米内网可能无法直接使用 ngrok，需要公司 VPN 或其他穿透方案")
    print("   - 生产环境建议部署到小米内网服务器")
    print()

    # 检查环境变量
    import os
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")

    if not app_id or not app_secret:
        print("⚠️  飞书凭证未设置，请先设置环境变量：")
        print()
        if sys.platform == "win32":
            print("    # PowerShell")
            print(f'    $env:FEISHU_APP_ID = "cli_a5xxxxxxxxxxxxx"')
            print(f'    $env:FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"')
            print()
            print("    # CMD")
            print(f'    set FEISHU_APP_ID=cli_a5xxxxxxxxxxxxx')
            print(f'    set FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
        else:
            print("    export FEISHU_APP_ID=cli_a5xxxxxxxxxxxxx")
            print("    export FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    else:
        print(f"✅ 飞书凭证已配置: App ID = {app_id[:8]}...")


if __name__ == "__main__":
    main()
