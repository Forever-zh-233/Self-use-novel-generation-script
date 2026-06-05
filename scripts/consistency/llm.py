# -*- coding: utf-8 -*-
"""独立 LLM 调用层 — 零依赖 pipeline 包。

只支持 openai_chat 类型（标准 OpenAI chat completions 格式）。
读 config/models.json 获取配置，读 .env.local 获取 API key。
纯标准库实现（urllib + json + os + time）。
"""

import json
import os
import random
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # E:\Novel 1

_config_cache = None


def _load_env_local():
    """从 .env.local 注入环境变量（不覆盖已有）。"""
    env_file = BASE_DIR / ".env.local"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_config():
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    _load_env_local()
    config_path = BASE_DIR / "config" / "models.json"
    with open(config_path, encoding="utf-8") as f:
        _config_cache = json.load(f)
    return _config_cache


def _resolve_role(role: str):
    """解析角色配置，返回 (base_url, api_key, model, extra_body)。"""
    config = _load_config()
    providers = config.get("providers", {})
    roles = config.get("roles", {})
    role_cfg = roles.get(role, {})
    provider_name = role_cfg.get("provider") or config.get("defaultProvider", "")
    provider = providers.get(provider_name, {})
    base_url = provider.get("base_url", "").rstrip("/")
    model = role_cfg.get("model") or provider.get("model", "")

    # API key: 先看 provider 里的 api_key，再看 api_key_env 指向的环境变量
    api_key = provider.get("api_key", "")
    if not api_key:
        env_name = provider.get("api_key_env", "")
        if env_name:
            api_key = os.environ.get(env_name, "")

    extra_body = provider.get("extra_body", {})
    max_tokens_field = provider.get("max_tokens_field", "max_tokens")

    return base_url, api_key, model, extra_body, max_tokens_field


def call_llm(role: str, system: str, user: str, max_tokens: int = 3000, timeout: int = 120,
             return_finish_reason: bool = False):
    """调用 LLM，返回文本响应。内置 3 次重试。

    return_finish_reason=True 时返回 (content, finish_reason)，便于上层检测截断。
    finish_reason == "length" 表示输出被 max_tokens 截断。
    """
    base_url, api_key, model, extra_body, max_tokens_field = _resolve_role(role)

    if not base_url or not api_key or not model:
        raise RuntimeError(f"角色 '{role}' 配置不完整: base_url={bool(base_url)}, key={bool(api_key)}, model={bool(model)}")

    url = f"{base_url}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens_field: max_tokens,
    }
    body.update(extra_body)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error = None
    for attempt in range(3):
        if attempt > 0:
            wait = min(5 * (2 ** attempt), 30) + random.uniform(0, 3)
            time.sleep(wait)
        try:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            choices = result.get("choices", [])
            if not choices:
                raise RuntimeError("API 返回空 choices")
            content = choices[0].get("message", {}).get("content", "")
            finish_reason = choices[0].get("finish_reason", "")
            if not content.strip():
                raise RuntimeError("API 返回空内容")
            return (content, finish_reason) if return_finish_reason else content
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as e:
            last_error = e
            err_str = str(e).lower()
            if "429" in err_str or "rate" in err_str or "too many" in err_str:
                # 429 用指数退避: 30s / 60s / 120s
                wait = min(30 * (2 ** attempt), 120) + random.uniform(0, 5)
                time.sleep(wait)
            else:
                time.sleep(min(5 * (2 ** attempt), 30))

    raise RuntimeError(f"LLM 调用失败（3次重试后）: {last_error}")


def parse_json_response(text: str) -> dict:
    """从 LLM 输出中提取 JSON。容错：去围栏、尾逗号、修复截断。"""
    text = text.strip()
    # 去 markdown 围栏（贪婪匹配到最后一个 ```，应对内部含 ``` 的情况）
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        # 去掉开头的 ```json 残留（截断时结尾的 ``` 不存在）
        text = re.sub(r"^```(?:json)?\s*", "", text)
        start = text.find("{")
        if start >= 0:
            text = text[start:]
        # 找到最后一个 } 作为结尾；若没有（被截断），后面尝试修复
        end = text.rfind("}")
        if end > 0:
            text = text[:end + 1]

    # 去尾逗号
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)

    # 修复裸中文值（模型有时写 "quantity": 三天量 而不是 "quantity": "三天量"）
    # 匹配冒号后紧跟未加引号的中文/汉字词
    cleaned = re.sub(r':\s*([^\s",\[\]{}][^,\]\n}]*[^\s",\]\[{}])\s*([,\}\]])',
                     lambda m: f': "{m.group(1).strip()}"{m.group(2)}'
                     if re.search(r'[一-鿿]', m.group(1)) and not m.group(1).strip().startswith('"')
                     else m.group(0),
                     cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 截断修复：补齐未闭合的引号/括号
    repaired = _repair_truncated_json(cleaned)
    return json.loads(repaired)  # 仍失败则抛出，由上层 fallback 处理


def _repair_truncated_json(text: str) -> str:
    """修复被截断的 JSON：去掉最后一个不完整的字段，补齐括号。"""
    # 去掉末尾可能不完整的部分：截到最后一个完整的 } 或 ]
    # 逐字符扫描，记录括号栈，在栈能闭合处截断
    depth_stack = []
    in_string = False
    escape = False
    last_safe = -1  # 最后一个"键值对完整结束"的位置

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth_stack.append(ch)
        elif ch in "}]":
            if depth_stack:
                depth_stack.pop()
        elif ch == "," and len(depth_stack) >= 1:
            last_safe = i  # 顶层/次层逗号处是安全截断点

    # 如果还在字符串中或有未闭合括号，从 last_safe 截断并补齐
    if last_safe > 0:
        text = text[:last_safe]
    # 补齐未闭合的括号（按栈逆序）
    # 重新计算栈
    depth_stack = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth_stack.append(ch)
        elif ch in "}]":
            if depth_stack:
                depth_stack.pop()
    if in_string:
        text += '"'
    closer = {"{": "}", "[": "]"}
    for opener in reversed(depth_stack):
        text += closer[opener]
    return text
