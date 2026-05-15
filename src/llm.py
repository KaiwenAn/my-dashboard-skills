"""
大模型 API 调用封装

支持任意兼容 OpenAI SDK 格式的模型接口，包括：
- 腾讯混元：https://api.hunyuan.cloud.tencent.com/v1
- 硅基流动（MiMo 等）：https://api.siliconflow.cn/v1
- DeepSeek：https://api.deepseek.com/v1
- 其他兼容 OpenAI 的接口
"""

import os
import sys
import json
import re
import time
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# Windows GBK 兼容
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()


class LLMClient:
    """大模型 API 客户端，支持任意兼容 OpenAI 格式的接口"""

    # 不同平台的默认 base_url（当 LLM_BASE_URL 未设置时按模型名前缀自动推断）
    _DEFAULT_BASE_URLS = {
        "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
        "Xiaomi":  "https://api.siliconflow.cn/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "qwen":    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }

    def __init__(self, model=None, api_key=None, base_url=None):
        """
        初始化 LLM 客户端

        Args:
            model: 模型名称（如 "MiniMaxAI/MiniMax-M2.5"）
                       为 None 时读环境变量 HUNYUAN_MODEL
            api_key: API Key，为 None 时读环境变量 HUNYUAN_API_KEY
            base_url: 接口地址，为 None 时读环境变量 LLM_BASE_URL，并按模型名自动推断
        """
        # 优先级：运行时参数 > 环境变量
        self.model = model or os.getenv("HUNYUAN_MODEL", "hunyuan-pro")
        _api_key = api_key if api_key is not None else os.getenv("HUNYUAN_API_KEY", "")

        if not _api_key or _api_key == "your_api_key_here":
            raise ValueError(
                "请先配置 HUNYUAN_API_KEY！\n"
                "在 .env 文件中填入对应平台的 API Key，例如：\n"
                "  腾讯混元：HUNYUAN_API_KEY=sk-xxx  HUNYUAN_MODEL=hunyuan-pro\n"
                "  硅基流动MiMo：HUNYUAN_API_KEY=sk-xxx  HUNYUAN_MODEL=Xiaomi/MiMo-7B-RL  LLM_BASE_URL=https://api.siliconflow.cn/v1\n"
            )

        # base_url 优先级：运行时参数 > 环境变量 > 按模型名自动推断
        if base_url is not None:
            _base_url = base_url
        else:
            _base_url = os.getenv("LLM_BASE_URL", "")
            if not _base_url:
                for prefix, url in self._DEFAULT_BASE_URLS.items():
                    if self.model.startswith(prefix):
                        _base_url = url
                        break
                if not _base_url:
                    # 默认腾讯混元
                    _base_url = "https://api.hunyuan.cloud.tencent.com/v1"

        print(f"  🔌 使用模型: {self.model}  接口: {_base_url}")
        self.client = OpenAI(
            api_key=_api_key,
            base_url=_base_url,
            timeout=httpx.Timeout(1800.0, connect=10.0),  # 读超时30分钟，连接超时10秒
        )

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> str:
        """
        调用大模型，返回纯文本响应

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            temperature: 温度（越低越确定性，0.1 适合结构化输出）
            max_tokens: 最大输出 token 数

        Returns:
            模型的文本响应
        """
        start_time = time.time()
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                # DEBUG: 打印实际发送的模型名和 base_url
                print(f"  [DEBUG] LLMClient.create() → model='{self.model}', base_url='{self.client.base_url}', api_key='{str(self.client.api_key)[:8]}...'")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                break  # 成功则跳出重试循环
            except Exception as e:
                # 网络错误/超时/连接重置等自动重试，非网络错误直接抛出
                err_name = type(e).__name__
                is_network_error = any(
                    kw in err_name.lower()
                    for kw in ["timeout", "connection", "network", "connect"]
                )
                if is_network_error and attempt < max_retries:
                    wait = attempt * 5
                    print(
                        f"  ⚠️ 网络错误({err_name})，{wait}s 后重试 ({attempt}/{max_retries})..."
                    )
                    time.sleep(wait)
                    continue
                raise

        elapsed = time.time() - start_time

        # 防御：API 可能返回空 choices（频率限制、内容过滤、临时异常等）
        if not response.choices:
            raise ValueError(
                f"API 返回了空的 choices 列表，可能是频率限制或临时异常，建议重试。"
                f" 请求耗时={elapsed:.1f}s, 模型={self.model}"
            )

        content = response.choices[0].message.content

        # 打印 token 使用情况
        if hasattr(response, "usage") and response.usage:
            print(
                f"  📊 Token 用量: 输入={response.usage.prompt_tokens}, "
                f"输出={response.usage.completion_tokens}, "
                f"耗时={elapsed:.1f}s"
            )
        else:
            print(f"  ⏱️ 耗时={elapsed:.1f}s")

        return content

    def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> dict:
        """
        调用大模型，返回 JSON 格式响应

        自动解析模型返回的 JSON，如果返回中包含 markdown 代码块会自动提取。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            temperature: 温度
            max_tokens: 最大输出 token 数

        Returns:
            解析后的 dict

        Raises:
            ValueError: 如果模型返回的不是合法 JSON
        """
        raw = self.chat(system_prompt, user_message, temperature, max_tokens)
        return parse_json_response(raw)


def parse_json_response(raw: str) -> dict:
    """
    从模型响应中解析 JSON

    处理以下情况：
    1. 纯 JSON 字符串
    2. ```json ... ``` 包裹的代码块
    3. ``` ... ``` 包裹的代码块
    4. JSON 前后有文字说明
    """
    text = raw.strip()

    # 情况2: ```json ... ```（兼容未闭合的情况，例如被 max_tokens 截断）
    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        if end == -1:
            # 没找到闭合标记：取起始标记之后的全部内容当作 JSON 候选
            text = text[start:].strip()
        else:
            text = text[start:end].strip()

    # 情况3: ``` ... ```（不含 json 标记，同样兼容未闭合）
    elif "```" in text:
        start = text.find("```") + len("```")
        # 跳过可能的语言标记行（如 json、JSON）
        if text[start:start+1] == "\n":
            start += 1
        end = text.find("```", start)
        if end == -1:
            text = text[start:].strip()
        else:
            text = text[start:end].strip()

    # 情况4: 找到第一个 { 和最后一个 }
    elif "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        text = text[start:end]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试修复常见 LLM 输出的 JSON 格式问题
        fixed = _fix_json_string(text)
        if fixed != text:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"模型返回的不是合法 JSON，解析失败\n"
            f"原始响应前200字符：{raw[:200]}"
        )


def _fix_json_string(text: str) -> str:
    """
    修复 LLM 输出中常见的 JSON 格式问题：
    1. 字符串值内的原始换行符 → 转义为 \\n
    2. 尾随逗号（数组/对象最后一项后多余的逗号）
    """
    fixed = text

    # 修复1：字符串值内的原始换行符
    # 策略：在 JSON 字符串值内部（引号之间）的换行符替换为 \\n
    # 用状态机逐字符处理，区分"在字符串内"和"在字符串外"
    result = []
    in_string = False
    i = 0
    while i < len(fixed):
        ch = fixed[i]
        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
        else:
            if ch == '\\' and i + 1 < len(fixed):
                # 转义序列，保留原样
                result.append(ch)
                result.append(fixed[i + 1])
                i += 2
                continue
            elif ch == '"':
                result.append(ch)
                in_string = False
            elif ch in ('\r', '\n'):
                # 字符串内的原始换行 → 转义
                result.append('\\n')
                if ch == '\r' and i + 1 < len(fixed) and fixed[i + 1] == '\n':
                    i += 1  # 跳过 \r\n 中的 \n
            else:
                result.append(ch)
        i += 1
    fixed = ''.join(result)

    # 修复2：尾随逗号（} 或 ] 前的逗号）
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)

    return fixed
