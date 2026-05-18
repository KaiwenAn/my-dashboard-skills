"""
check_cookie.py — 快速验证 scripts/.env 里的 COPILOT_COOKIE 是否有效

原理：
- cookie 里 `_aegis_cas_p` 是小米 CAS 单点登录的 JWT token，含 `exp` 过期时间戳
- 离线解码 JWT 即可确定是否过期，不发任何 HTTP 请求，无副作用

用法：
    python scripts/check_cookie.py

输出：
    ✅ Cookie 有效，剩余 12.3 小时
    或
    ❌ Cookie 已过期 (3 小时前)
"""
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 才能输出 emoji 和中文
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    # 1. 加载 .env
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent / ".env"
        if not env_path.exists():
            print(f"❌ 找不到 {env_path}")
            return 1
        load_dotenv(env_path)
    except ImportError:
        print("❌ 缺 python-dotenv 包，先 pip install python-dotenv")
        return 1

    cookie = os.getenv("COPILOT_COOKIE", "").strip()
    if not cookie:
        print("❌ COPILOT_COOKIE 为空 / 未配置")
        return 1

    # 2. 检查整段没换行
    if "\n" in cookie or "\r" in cookie:
        print("❌ COPILOT_COOKIE 中间有换行 — 必须粘成一整行")
        return 1

    print(f"📋 Cookie 长度: {len(cookie)} 字符")

    # 3. 提取关键 cookie 项
    keys_present = []
    for key in ("_aegis_cas_p", "SESSION", "meego_csrf_token"):
        if re.search(rf"\b{re.escape(key)}=", cookie):
            keys_present.append(key)
    print(f"📋 关键项检测: {', '.join(keys_present) if keys_present else '⚠️ 一个都没找到'}")

    # 4. 从 cookie 里抓 _aegis_cas_p
    m = re.search(r"_aegis_cas_p=([^;]+)", cookie)
    if not m:
        print("❌ cookie 里没找到 _aegis_cas_p — 可能没复制全或来源不对")
        return 1
    jwt = m.group(1)

    # 5. 解码 JWT payload（第二段，base64-url）
    parts = jwt.split(".")
    if len(parts) < 2:
        print(f"❌ _aegis_cas_p 不是合法 JWT 格式（segments={len(parts)}）")
        return 1

    payload_b64 = parts[1]
    # base64-url padding 补齐
    payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
    except Exception as e:
        print(f"❌ JWT base64 解码失败: {e}")
        return 1

    # JWT payload 通常是 UTF-8 JSON，但小米 CAS 偶尔在 string 里塞二进制 escape，
    # 用 latin1 兜底（每个字节一个字符，不会失败），仅取 exp/sub 这两个数值/ASCII 字段。
    payload = None
    for encoding in ("utf-8", "latin1"):
        try:
            payload = json.loads(payload_bytes.decode(encoding, errors="replace"))
            break
        except Exception:
            continue
    if payload is None:
        print("❌ JWT payload 既不是合法 UTF-8 JSON 也不是 latin1 JSON")
        return 1

    # 6. 取 exp 时间戳判断
    exp = payload.get("exp")
    if exp is None:
        print("❌ JWT 里没有 exp 字段，无法判断过期时间")
        return 1

    now = int(time.time())
    delta_sec = exp - now
    exp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))

    sub = payload.get("sub", "?")
    print(f"📋 JWT 用户: {sub}")
    print(f"📋 过期时间: {exp_str}")

    if delta_sec <= 0:
        print(f"❌ Cookie 已过期 ({-delta_sec // 3600} 小时 {(-delta_sec % 3600) // 60} 分钟前)")
        print("   → 浏览器重新登录 data.mioffice.cn，重抓 cookie 写入 scripts/.env")
        return 1
    elif delta_sec < 3600:
        print(f"⚠️  Cookie 即将过期：剩 {delta_sec // 60} 分钟")
        print("   → 建议尽快重抓")
        return 0
    else:
        hours = delta_sec / 3600
        print(f"✅ Cookie 有效，剩余 {hours:.1f} 小时")
        return 0


if __name__ == "__main__":
    sys.exit(main())
