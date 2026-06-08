# -*- coding: utf-8 -*-
"""pipeline.api — HTTP, call_model, call_role."""

import json
import os
import re
import sys
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    BASE_DIR, PROMPTS_DIR, CONFIG_DIR, RUNTIME_DIR, MODELS_FILE,
    cli_print, estimate_tokens, load_json, load_models, read_text, write_text,
    role_artifact,
)


def role_config(role: str) -> Dict[str, Any]:
    config = load_models()
    roles = config.get("roles") or {}
    role_cfg = dict(roles.get(role) or {})
    provider_name = role_cfg.get("provider") or config.get("defaultProvider")
    providers = config.get("providers") or {}
    provider_cfg = dict(providers.get(provider_name) or {})
    provider_cfg["name"] = provider_name
    provider_cfg.update(role_cfg)
    return provider_cfg


def get_api_key(cfg: Dict[str, Any], role: str) -> str:
    env_override = os.environ.get(f"NOVEL_{role.upper()}_API_KEY")
    if env_override:
        return env_override
    direct_key = cfg.get("api_key") or cfg.get("apiKey")
    if direct_key:
        return str(direct_key)
    key_env = cfg.get("api_key_env") or cfg.get("apiKeyEnv")
    if key_env and os.environ.get(str(key_env)):
        return os.environ[str(key_env)]
    if cfg.get("type") in ("openai_responses", "openai_chat", "openai_compatible"):
        return os.environ.get("OPENAI_API_KEY", "")
    if cfg.get("type") == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY", "")
    return ""


def join_url(base_url: str, endpoint: str) -> str:
    base = base_url.rstrip("/")
    suffix = endpoint.lstrip("/")
    if base.endswith("/v1") and suffix.startswith("v1/"):
        suffix = suffix[3:]
    return base + "/" + suffix


def configured_base_url(cfg: Dict[str, Any], default: str) -> str:
    return str(cfg.get("base_url") or cfg.get("baseUrl") or default)


def configured_headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    headers = cfg.get("headers") or cfg.get("extra_headers") or cfg.get("extraHeaders") or {}
    if not isinstance(headers, dict):
        return {}
    return {str(key): str(value) for key, value in headers.items()}


def configured_extra_body(cfg: Dict[str, Any]) -> Dict[str, Any]:
    body = cfg.get("extra_body") or cfg.get("extraBody") or {}
    return body if isinstance(body, dict) else {}



class RequestTimeout(RuntimeError):
    """请求总时长超过硬上限仍未返回。偶发性错误，由 call_role 重试。"""


class OutputTruncated(RuntimeError):
    """模型输出在 max_output_tokens 处被硬截断。call_role 会加大预算重试。
    携带已生成的部分文本(partial)，末次重试仍截断时回退使用，行为不劣于旧逻辑。"""

    def __init__(self, message: str, partial: str = "") -> None:
        super().__init__(message)
        self.partial = partial


def _is_truncated_response(provider_type: str, data: Dict[str, Any]) -> bool:
    """识别"因 token 上限被截断"。识别不到一律当未截断(回退旧行为，零回归)。"""
    try:
        if provider_type == "openai_chat":
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                return choices[0].get("finish_reason") == "length"
        elif provider_type == "openai_responses":
            if data.get("status") == "incomplete":
                reason = (data.get("incomplete_details") or {}).get("reason")
                return reason == "max_output_tokens"
        elif provider_type == "anthropic":
            return data.get("stop_reason") == "max_tokens"
    except Exception:
        return False
    return False


def http_post(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """带总时长硬超时的 POST (daemon thread + Event.wait)。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    result_box: Dict[str, Any] = {}
    done = threading.Event()
    def _do_request() -> None:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result_box["ok"] = json.loads(response.read().decode("utf-8"))
        except BaseException as exc:
            result_box["err"] = exc
        finally:
            done.set()
    hard_timeout = int(timeout * 1.5) + 30
    worker = threading.Thread(target=_do_request, daemon=True)
    worker.start()
    if not done.wait(hard_timeout):
        raise RequestTimeout(f"请求总时长超过 {hard_timeout}s 仍未返回 {url}")
    if "err" in result_box:
        error = result_box["err"]
        if isinstance(error, urllib.error.HTTPError):
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {error.code} {url}\n{detail}") from error
        raise error
    return result_box["ok"]

def extract_usage(data: Dict[str, Any]) -> Dict[str, int]:
    """从 API 返回里提取真实 token 用量，兼容三种 provider 的字段命名。
    openai_chat(mimo): prompt_tokens/completion_tokens, 缓存命中在 prompt_tokens_details.cached_tokens。
    openai_responses/anthropic: input_tokens/output_tokens, 缓存在 cache_read_input_tokens 或 input_tokens_details.cached_tokens。
    返回 {input, output, cached, total}，取不到的字段为 0。"""
    u = data.get("usage") or {}
    if not isinstance(u, dict):
        return {"input": 0, "output": 0, "cached": 0, "total": 0}
    inp = u.get("prompt_tokens") or u.get("input_tokens") or 0
    out = u.get("completion_tokens") or u.get("output_tokens") or 0
    # 缓存命中:各家字段不同,挨个试
    cached = (
        u.get("cache_read_input_tokens")
        or (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        or (u.get("input_tokens_details") or {}).get("cached_tokens")
        or u.get("cached_tokens")
        or 0
    )
    total = u.get("total_tokens") or (int(inp) + int(out))
    return {"input": int(inp), "output": int(out), "cached": int(cached), "total": int(total)}


# 全程 token 用量累加器:{role: {input, output, cached, total, calls}}。
# 只读统计,不影响任何业务逻辑。run_pipeline 可在每章末/收尾打印汇总。
USAGE_TALLY: Dict[str, Dict[str, int]] = {}


def _accumulate_usage(role: str, usage: Dict[str, int]) -> None:
    slot = USAGE_TALLY.setdefault(role, {"input": 0, "output": 0, "cached": 0, "total": 0, "calls": 0})
    slot["input"] += usage["input"]
    slot["output"] += usage["output"]
    slot["cached"] += usage["cached"]
    slot["total"] += usage["total"]
    slot["calls"] += 1


def usage_summary(reset: bool = False) -> Dict[str, Any]:
    """汇总当前累加的 token 用量。reset=True 时清零(用于按章统计)。
    返回 {by_role, totals}。"""
    by_role = {r: dict(v) for r, v in USAGE_TALLY.items()}
    totals = {"input": 0, "output": 0, "cached": 0, "total": 0, "calls": 0}
    for v in USAGE_TALLY.values():
        for k in totals:
            totals[k] += v.get(k, 0)
    if reset:
        USAGE_TALLY.clear()
    return {"by_role": by_role, "totals": totals}


def extract_responses_text(data: Dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: List[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def extract_chat_text(data: Dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).strip()
    return ""


def extract_anthropic_text(data: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in data.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts).strip()


def call_model(role: str, instructions: str, input_text: str, max_output_tokens: int, timeout: int,
               raise_on_truncate: bool = False) -> str:
    cfg = role_config(role)
    provider_type = cfg.get("type") or cfg.get("provider_type") or cfg.get("provider") or "openai_responses"
    model = os.environ.get(f"NOVEL_{role.upper()}_MODEL") or cfg.get("model")
    if not model:
        raise RuntimeError(f"角色 {role} 未配置 model。")
    api_key = get_api_key(cfg, role)
    if not api_key:
        raise RuntimeError(f"角色 {role} 缺少 API key。请在 config/models.json 的 api_key 填入，或设置 api_key_env 对应环境变量。")

    if provider_type == "openai":
        provider_type = "openai_responses"
    if provider_type == "openai_compatible":
        provider_type = "openai_chat"

    if provider_type == "openai_responses":
        base_url = configured_base_url(cfg, "https://api.openai.com/v1")
        body = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
            "max_output_tokens": max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **configured_headers(cfg),
        }
        data = http_post(
            join_url(str(base_url), "/responses"),
            headers,
            body,
            timeout,
        )
        text = extract_responses_text(data)
    elif provider_type == "openai_chat":
        base_url = configured_base_url(cfg, "https://api.openai.com/v1")
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ]
        }
        token_field = str(cfg.get("max_tokens_field") or cfg.get("maxTokensField") or "max_tokens")
        body[token_field] = max_output_tokens
        body.update(configured_extra_body(cfg))
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **configured_headers(cfg),
        }
        data = http_post(
            join_url(str(base_url), "/chat/completions"),
            headers,
            body,
            timeout,
        )
        text = extract_chat_text(data)
    elif provider_type == "anthropic":
        base_url = configured_base_url(cfg, "https://api.anthropic.com")
        body = {
            "model": model,
            "system": instructions,
            "messages": [{"role": "user", "content": input_text}],
            "max_tokens": max_output_tokens,
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": str(cfg.get("anthropic_version") or cfg.get("anthropicVersion") or "2023-06-01"),
            "Content-Type": "application/json",
            **configured_headers(cfg),
        }
        data = http_post(
            join_url(str(base_url), "/v1/messages"),
            headers,
            body,
            timeout,
        )
        text = extract_anthropic_text(data)
    else:
        raise RuntimeError(f"角色 {role} 使用了未知 provider type: {provider_type}")

    if not text:
        raise RuntimeError(f"角色 {role} 的 API 返回为空。")
    if raise_on_truncate and _is_truncated_response(provider_type, data):
        raise OutputTruncated(
            f"角色 {role} 输出在 {max_output_tokens} token 上限处被截断。", partial=text
        )
    # 真实 token 用量(只读旁路,不影响返回):打印本次 + 累加到本章/全程计数器
    usage = extract_usage(data)
    if usage["total"]:
        cached_str = f" │ 缓存命中 {usage['cached']:,}" if usage["cached"] else ""
        cli_print(f"  ← {role} │ 实耗 输入 {usage['input']:,} / 输出 {usage['output']:,} = {usage['total']:,} tok{cached_str}")
        _accumulate_usage(role, usage)
    return text


def role_max_output_tokens(role: str, default: int) -> int:
    return int(role_config(role).get("max_output_tokens") or default)


def call_role(
    role: str,
    instructions: str,
    input_text: str,
    output_path: Path,
    timeout: int,
    default_max_tokens: int,
    input_path: Optional[Path] = None,
    reject_retries: int = 3,
    truncate_escalations: int = 2,
) -> str:
    if input_path:
        write_text(input_path, input_text)
    cfg = role_config(role)
    provider = cfg.get("name") or cfg.get("provider")
    model = cfg.get("model")
    input_tokens = estimate_tokens(input_text)
    cli_print(f"  → {role} │ {input_tokens:,} tok │ {model}")
    # 偶发故障(风控拒绝 + 请求超时)在这里重试,连续 reject_retries 次才停章。
    # 输出截断是另一类失败:同预算重试必然再撞上限,所以加倍预算重试(escalations 次),
    # 末次仍截断则回退用已生成的部分文本(不劣于旧的静默截断行为)。
    result = ""
    last = ""
    budget = role_max_output_tokens(role, default_max_tokens)
    escalated = 0
    max_attempts = reject_retries + truncate_escalations
    reject_count = 0
    for attempt in range(1, max_attempts + 1):
        try:
            result = call_model(role, instructions, input_text, budget, timeout, raise_on_truncate=True)
        except RequestTimeout as exc:
            last = str(exc)[:120]
            cli_print(f"{role} 第 {attempt} 次请求超时：{last}")
            reject_count += 1
            if reject_count < reject_retries:
                time.sleep(min(5 * attempt, 20))
                continue
            raise RuntimeError(f"角色 {role} 连续 {reject_retries} 次请求超时，停在本章。") from exc
        except OutputTruncated as exc:
            if escalated < truncate_escalations:
                escalated += 1
                budget *= 2
                cli_print(f"{role} 输出被截断，第 {escalated} 次加大预算到 {budget} token 重试。")
                continue
            # 预算已加到上限仍截断:回退用部分文本，让上层校验/净化去兜底。
            cli_print(f"{role} 加大预算 {escalated} 次后仍被截断，回退使用部分输出({len(exc.partial)} 字)。")
            result = exc.partial
            break
        if not is_rejection_text(result):
            break
        last = result.strip()[:80]
        reject_count += 1
        cli_print(f"{role} 第 {reject_count}/{reject_retries} 次被内容风控拒绝：{last}")
        if reject_count < reject_retries:
            time.sleep(min(5 * attempt, 20))
            continue
        raise RuntimeError(f"角色 {role} 连续 {reject_retries} 次被内容风控拒绝，停在本章。")
    write_text(output_path, result)
    return result


def role_context_window(role: str, run_cfg: Dict[str, Any]) -> int:
    cfg = role_config(role)
    value = cfg.get("context_window_tokens") or cfg.get("contextWindowTokens")
    if value:
        return int(value)
    defaults = run_cfg.get("context_windows") or {}
    if isinstance(defaults, dict) and defaults.get(role):
        return int(defaults[role])
    return int(run_cfg.get("default_context_window_tokens") or 200000)


def role_compress_threshold(role: str, run_cfg: Dict[str, Any]) -> int:
    cfg = role_config(role)
    ratio = cfg.get("compress_at_ratio") or cfg.get("compressAtRatio") or run_cfg.get("compress_at_ratio") or 0.8
    threshold = int(role_context_window(role, run_cfg) * float(ratio))
    max_inputs = run_cfg.get("max_input_tokens") or {}
    if isinstance(max_inputs, dict) and max_inputs.get(role):
        threshold = min(threshold, int(max_inputs[role]))
    return threshold


REJECTION_PATTERN = re.compile(
    r"the request was rejected because it was considered high risk",
    re.IGNORECASE,
)


def is_rejection_text(text: str) -> bool:
    if not text or not text.strip():
        return True
    s = text.strip()
    if len(s) > 500:
        return False
    return bool(REJECTION_PATTERN.search(s))

