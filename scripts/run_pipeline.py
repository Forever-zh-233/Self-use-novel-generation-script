# -*- coding: utf-8 -*-
r"""
端到端小说流水线（API 版）。

双击 bat 时会读取 config/run.json 和 config/models.json：
  读取卷纲/台账/期待账本 -> Writer 初稿 -> Gate 硬检查
  -> Reviewer 评审 -> Editor 自动修稿 -> Archivist 生成台账更新建议
  -> 保存 final

注意：
  - 每个角色都是一次新的 API 请求，不继承聊天上下文。
  - 不读取 271824.txt。
  - 支持 OpenAI Responses、OpenAI-compatible Chat Completions、Anthropic Messages。
  - beat 文件缺失时，可由 beat_planner 角色自动生成。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(os.environ.get("NOVEL_WORKSPACE") or Path(__file__).resolve().parents[1])
CHUNKS_DIR = BASE_DIR / "chunks"
OUTPUT_DIR = BASE_DIR / "输出"
ARTICLE_DIR = OUTPUT_DIR / "文章"
PROMPTS_DIR = BASE_DIR / "prompts"
CONFIG_DIR = BASE_DIR / "config"
MODELS_FILE = CONFIG_DIR / "models.json"
RUN_FILE = CONFIG_DIR / "run.json"
RUNTIME_DIR = BASE_DIR / "runtime"
LOCK_FILE = RUNTIME_DIR / "novel_pipeline.lock"
PAUSE_FILE = RUNTIME_DIR / "pause.request"
STOP_FILE = RUNTIME_DIR / "stop.request"
PROGRESS_FILE = RUNTIME_DIR / "progress.json"
STATE_FILE = RUNTIME_DIR / "state.json"
ACTIVE_THREADS_FILE = RUNTIME_DIR / "active_threads.json"
STATE_MD_FILE = RUNTIME_DIR / "state.md"
ACTIVE_THREADS_MD_FILE = RUNTIME_DIR / "active_threads.md"
VOLUME_SUMMARY_FILE = RUNTIME_DIR / "volume_summary.md"
LEDGER_FILE = RUNTIME_DIR / "ledger.json"
LEDGER_MD_FILE = RUNTIME_DIR / "ledger.md"
CHARACTER_ARCS_FILE = RUNTIME_DIR / "character_arcs.md"
ANALYST_DIR = RUNTIME_DIR / "analyst"
ACTIVE_ARCS_FILE = RUNTIME_DIR / "active_arcs.json"
STORY_DIRECTOR_FILE = RUNTIME_DIR / "story_director.json"
STORY_DIRECTOR_MD_FILE = RUNTIME_DIR / "story_director.md"
MASTER_OUTLINE_FILE = BASE_DIR / "全书骨架.md"
VOLUME_PLAN_FILE = BASE_DIR / "卷纲" / "10-卷纲.md"
VERSION_DIR = BASE_DIR / "台账版本"
LONG_FORESHADOWING_FILE = BASE_DIR / "15-长线伏笔资产库.md"


def manuscript_path(chapter: int) -> Path:
    return ARTICLE_DIR / f"第{chapter:03d}章.md"


def role_output_dir(role: str) -> Path:
    dirs = {
        "beat": "章纲",
        "writer": "写手",
        "gate": "门禁",
        "reviewer": "评审",
        "editor": "修稿",
        "archivist": "记录员",
        "context": "上下文",
    }
    return OUTPUT_DIR / dirs[role]


def role_artifact(role: str, chapter: int, suffix: str) -> Path:
    return role_output_dir(role) / f"第{chapter:03d}章_{suffix}"


def chapter_artifact_prefix(chapter: int) -> str:
    return f"第{chapter:03d}章_"


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return default


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_text(path)
    separator = "\n\n" if current and not current.endswith("\n\n") else ""
    write_text(path, current + separator + text)


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text = read_text(path).strip()
    if not text:
        return default or {}
    return json.loads(text)


def dump_json(path: Path, data: Dict[str, Any]) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def default_state() -> Dict[str, Any]:
    return {
        "latest_chapter": 0,
        "story_time": "未开始",
        "current_location": "北砚县",
        "characters": {},
        "relationships": {},
        "knowledge": {},
        "used_devices": [],
        "recent_events": [],
    }


def default_active_threads() -> Dict[str, Any]:
    return {
        "foreshadowing": {},
        "open_questions": [],
        "next_id": "F-001",
    }


def default_ledger() -> Dict[str, Any]:
    # 七层正典账本，全量落盘，永不丢。第一步先用：实体/资源/未结清/约束。
    return {
        "entities": {},      # 角色/地点/势力/物件/术语：summary, voice(角色), facts, status, first_chapter, last_seen_chapter
        "resources": {},     # 资源账：名称 -> 当前值（会变，防穿帮）
        "obligations": [],   # 未结清账：承诺/债/因果，带 status(悬空/已结)
        "constraints": [],   # 约束账：已成事实，带 binding(强/弱)
        "relationships": {}, # 关系账：pair -> {current, history:[{chapter,event}]}
    }


def load_ledger() -> Dict[str, Any]:
    data = load_json(LEDGER_FILE, default_ledger())
    for key, value in default_ledger().items():
        data.setdefault(key, value)
    return data


def load_state() -> Dict[str, Any]:
    return load_json(STATE_FILE, default_state())


def load_active_threads() -> Dict[str, Any]:
    return load_json(ACTIVE_THREADS_FILE, default_active_threads())


def render_state_markdown(state: Dict[str, Any]) -> str:
    lines = [
        "# 当前状态",
        "",
        f"- 最新章节：第{state.get('latest_chapter', 0)}章",
        f"- 故事内时间：{state.get('story_time', '未明确')}",
        f"- 当前地点：{state.get('current_location', '未明确')}",
        "",
        "## 人物",
    ]
    characters = state.get("characters") or {}
    if characters:
        for name, info in characters.items():
            if isinstance(info, dict):
                lines.append(f"- {name}：位置={info.get('location', '未明确')}；状态={info.get('status', '未明确')}；情绪={info.get('emotion', '未明确')}")
                knowledge = info.get("knowledge") or []
                if knowledge:
                    lines.append(f"  - 已知：{'；'.join(map(str, knowledge))}")
            else:
                lines.append(f"- {name}：{info}")
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 关系"])
    relationships = state.get("relationships") or {}
    if relationships:
        for key, value in relationships.items():
            lines.append(f"- {key}：{value}")
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 信息差"])
    knowledge = state.get("knowledge") or {}
    if knowledge:
        for name, info in knowledge.items():
            if isinstance(info, dict):
                knows = "；".join(map(str, info.get("knows") or [])) or "未记录"
                unknown = "；".join(map(str, info.get("unknown") or [])) or "未记录"
                lines.append(f"- {name}：已知={knows}；未知={unknown}")
            else:
                lines.append(f"- {name}：{info}")
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 最近事件"])
    for event in state.get("recent_events") or []:
        lines.append(f"- {event}")
    if not state.get("recent_events"):
        lines.append("- 暂无")
    lines.extend(["", "## 已用桥段"])
    for device in state.get("used_devices") or []:
        lines.append(f"- {device}")
    if not state.get("used_devices"):
        lines.append("- 暂无")
    return "\n".join(lines) + "\n"


def render_active_threads_markdown(threads: Dict[str, Any]) -> str:
    lines = [
        "# 活跃线索与期待账本",
        "",
        f"- 下一个建议 ID：{threads.get('next_id', 'F-001')}",
        "",
        "## 伏笔",
    ]
    foreshadowing = threads.get("foreshadowing") or {}
    if foreshadowing:
        for fid, item in foreshadowing.items():
            if isinstance(item, dict):
                lines.append(
                    f"- {fid}：{item.get('status', '未明确')}；类型={item.get('type', '未明确')}；"
                    f"埋设=第{item.get('planted_chapter', '?')}章；计划回收={item.get('planned_resolution', '未明确')}；"
                    f"承诺={item.get('promise', '未记录')}"
                )
                if item.get("resolution"):
                    lines.append(f"  - 回收：{item.get('resolution')}")
                if item.get("notes"):
                    lines.append(f"  - 备注：{item.get('notes')}")
            else:
                lines.append(f"- {fid}：{item}")
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 开放问题"])
    for question in threads.get("open_questions") or []:
        lines.append(f"- {question}")
    if not threads.get("open_questions"):
        lines.append("- 暂无")
    return "\n".join(lines) + "\n"


def write_state_mirrors() -> None:
    state = load_state()
    threads = load_active_threads()
    write_text(STATE_MD_FILE, render_state_markdown(state))
    write_text(ACTIVE_THREADS_MD_FILE, render_active_threads_markdown(threads))


def estimate_tokens(text: str) -> int:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    non_chinese_chars = max(0, len(text) - chinese_chars)
    return int(chinese_chars * 1.5 + non_chinese_chars / 4)


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def cli_print(message: str) -> None:
    print(f"[{now_text()}] {message}", flush=True)


def write_progress(data: Dict[str, Any]) -> None:
    payload = {
        **data,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    dump_json(PROGRESS_FILE, payload)


def progress_bar(done: int, total: int, width: int = 24) -> str:
    total = max(1, total)
    done = max(0, min(done, total))
    filled = int(width * done / total)
    return "[" + "#" * filled + "." * (width - filled) + f"] {done}/{total}"


def poll_keyboard_control() -> None:
    if os.name != "nt":
        return
    try:
        import msvcrt
    except ImportError:
        return
    while msvcrt.kbhit():
        key = msvcrt.getwch().lower()
        if key == "p":
            if PAUSE_FILE.exists():
                PAUSE_FILE.unlink()
                cli_print("继续运行。")
            else:
                write_text(PAUSE_FILE, "pause requested from terminal\n")
                cli_print("已请求暂停；当前 API 调用结束后会停在安全点。再次按 p 继续。")
        elif key == "q":
            write_text(STOP_FILE, "stop requested from terminal\n")
            cli_print("已请求停止；当前章节/步骤结束后停止。")


def wait_if_paused(stage: str = "") -> None:
    poll_keyboard_control()
    if STOP_FILE.exists():
        raise KeyboardInterrupt("用户请求停止")
    if not PAUSE_FILE.exists():
        return
    cli_print(f"已暂停{f'：{stage}' if stage else ''}。按 p 继续，或删除 {PAUSE_FILE}。")
    while PAUSE_FILE.exists():
        poll_keyboard_control()
        if STOP_FILE.exists():
            raise KeyboardInterrupt("用户请求停止")
        time.sleep(0.5)
    cli_print("暂停结束，继续。")


def stage_start(chapter: int, role: str, action: str, step: int, total_steps: int, chapter_index: int, total_chapters: int) -> float:
    bar = progress_bar(step - 1, total_steps)
    cli_print(f"章 {chapter} ({chapter_index}/{total_chapters}) {bar} {role}: {action} ...")
    write_progress({
        "chapter": chapter,
        "chapter_index": chapter_index,
        "total_chapters": total_chapters,
        "role": role,
        "action": action,
        "step": step,
        "total_steps": total_steps,
        "status": "running",
    })
    return time.time()


def stage_done(chapter: int, role: str, action: str, step: int, total_steps: int, started_at: float) -> None:
    elapsed = time.time() - started_at
    bar = progress_bar(step, total_steps)
    cli_print(f"章 {chapter} {bar} {role}: {action} 完成，用时 {elapsed:.1f}s")
    write_progress({
        "chapter": chapter,
        "role": role,
        "action": action,
        "step": step,
        "total_steps": total_steps,
        "status": "done",
        "elapsed_seconds": round(elapsed, 1),
    })


def acquire_lock() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        pid_text = read_text(LOCK_FILE).strip()
        try:
            old_pid = int(pid_text)
        except ValueError:
            old_pid = 0
        if old_pid and is_process_running(old_pid):
            raise RuntimeError(f"检测到流水线可能已在运行：{LOCK_FILE}。如果确认没有运行，可手动删除该锁文件。")
        cli_print(f"检测到陈旧主锁，已自动清理：{LOCK_FILE}")
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def load_models() -> Dict[str, Any]:
    return load_json(MODELS_FILE, {"providers": {}, "roles": {}})


def load_run_config(path: Optional[str]) -> Dict[str, Any]:
    config = load_json(Path(path) if path else RUN_FILE, {})
    run = config.get("run") if "run" in config else config
    if not isinstance(run, dict):
        run = {}
    return run


def artifact_retention_mode(run_cfg: Dict[str, Any]) -> str:
    mode = str(run_cfg.get("artifact_retention") or run_cfg.get("artifactRetention") or "clean").strip().lower()
    aliases = {
        "minimal": "clean",
        "none": "clean",
        "delete": "clean",
        "all": "debug",
        "keep": "debug",
    }
    return aliases.get(mode, mode)


def cleanup_empty_output_dirs() -> None:
    for role in ["beat", "writer", "gate", "reviewer", "editor", "archivist", "context"]:
        path = role_output_dir(role)
        try:
            if path.exists() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass


def cleanup_chapter_artifacts(chapter: int, run_cfg: Dict[str, Any]) -> None:
    """删除后续不会被脚本读取的本章过程产物。失败章节不调用本函数，保留现场排错。"""
    mode = artifact_retention_mode(run_cfg)
    if mode == "debug":
        return

    prefix = chapter_artifact_prefix(chapter)
    keep_when_reports = {
        "review.md",
        "archive_update.md",
        "final_gate.json",
        "final_style_gate.json",
        "final_continuity.json",
    }
    deleted = 0
    for role in ["beat", "writer", "gate", "reviewer", "editor", "archivist", "context"]:
        folder = role_output_dir(role)
        if not folder.exists():
            continue
        for path in folder.iterdir():
            if not path.is_file() or not path.name.startswith(prefix):
                continue
            suffix = path.name[len(prefix):]
            if mode == "reports" and suffix in keep_when_reports:
                continue
            try:
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                pass
    cleanup_empty_output_dirs()
    if deleted:
        cli_print(f"已清理第 {chapter} 章过程副产物 {deleted} 个（artifact_retention={mode}）。")


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


def http_post(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} {url}\n{detail}") from error


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


def call_model(role: str, instructions: str, input_text: str, max_output_tokens: int, timeout: int) -> str:
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
) -> str:
    if input_path:
        write_text(input_path, input_text)
    cfg = role_config(role)
    provider = cfg.get("name") or cfg.get("provider")
    model = cfg.get("model")
    cli_print(f"调用 {role}: provider={provider}, model={model}, input≈{estimate_tokens(input_text)} tokens")
    # 偶发的内容风控拒绝(HTTP 200 但 content 是"request rejected")不能当正文存盘。
    # 偶发性质:同一请求重试通常就过。连续 reject_retries 次才放弃,交由上层停在本章。
    result = ""
    last = ""
    for attempt in range(1, reject_retries + 1):
        result = call_model(role, instructions, input_text, role_max_output_tokens(role, default_max_tokens), timeout)
        if not is_rejection_text(result):
            break
        last = result.strip()[:80]
        cli_print(f"{role} 第 {attempt}/{reject_retries} 次被内容风控拒绝：{last}")
        if attempt < reject_retries:
            time.sleep(min(5 * attempt, 20))
    else:
        raise RuntimeError(f"角色 {role} 连续 {reject_retries} 次被内容风控拒绝（非偶发），停在本章。最后返回：{last}")
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


def make_section(title: str, body: str, priority: str = "normal", compressible: bool = True) -> Dict[str, Any]:
    return {
        "title": title,
        "body": body,
        "priority": priority,
        "compressible": compressible,
        "tokens": estimate_tokens(body),
    }


def _trim_state_for_context(state: Dict[str, Any]) -> Dict[str, Any]:
    """裁剪 state 给上下文用：knowledge 的 knows/unknown 只增不减会爆。
    每角色 knows 只留最近 12 条、unknown 只留最近 8 条；recent_events 留最近 6 条。"""
    import copy
    s = copy.deepcopy(state)
    kn = s.get("knowledge")
    if isinstance(kn, dict):
        for who, info in kn.items():
            if isinstance(info, dict):
                if isinstance(info.get("knows"), list):
                    info["knows"] = info["knows"][-12:]
                if isinstance(info.get("unknown"), list):
                    info["unknown"] = info["unknown"][-8:]
    if isinstance(s.get("recent_events"), list):
        s["recent_events"] = s["recent_events"][-6:]
    return s


def writer_state_digest(beat: Dict[str, Any]) -> str:
    """Writer 专用的精简状态摘要(按需注入)。
    structured_state_text 把整个 state.json + active_threads.json 全量 dump,对 writer 而言
    其中 foreshadowing/relationships/used_devices 全是重复(writer 已另有「长线伏笔安全提醒」
    section、ledger 的「本章相关关系」「角色正典卡」),且 foreshadowing 含暗线真相不该全给 writer。
    这里只保留 writer 真正需要、又没在别处重复的:时间线 + 当前地点 + 本章出场角色的即时状态。"""
    state = load_state()
    cast = set(str(c) for c in (beat.get("出场角色") or []))
    aliases = chunk_aliases()
    cast = {aliases.get(c, c) for c in cast}
    lines: List[str] = []
    # 时间线
    tl = state.get("timeline") or {}
    if tl:
        lines.append(f"【时间线】第{tl.get('absolute_day', '?')}日·{tl.get('time_of_day', '?')}·{tl.get('season', '?')}")
        cur_day = tl.get("absolute_day") or 0
        # 只显示未过期的高紧急计时器(due_day 已过的是陈旧数据,不再提醒)
        urgent = [
            t for t in (tl.get("pending_timers") or [])
            if t.get("urgency") in ("极高", "高") and (t.get("due_day") or 999) >= cur_day
        ]
        for t in urgent[:3]:
            lines.append(f"  ⚠ {t.get('event','')}（截止第{t.get('due_day','?')}日）")
    # 当前地点/故事时刻
    if state.get("current_location"):
        lines.append(f"【当前地点】{state['current_location']}")
    if state.get("story_time"):
        lines.append(f"【此刻】{state['story_time']}")
    # 本章出场角色的即时状态(只给本章相关角色,knowledge 不进——ledger 角色卡的 facts 已覆盖)
    chars = state.get("characters") or {}
    role_lines = []
    for name, info in chars.items():
        if name not in cast or not isinstance(info, dict):
            continue
        bits = []
        if info.get("location"):
            bits.append(f"位置:{info['location']}")
        if info.get("status"):
            bits.append(f"状态:{info['status']}")
        if info.get("emotion") and info["emotion"] != "未出场":
            bits.append(f"情绪:{info['emotion']}")
        if bits:
            role_lines.append(f"- {name}：{'；'.join(bits)}")
    if role_lines:
        lines.append("【本章出场角色·即时状态】")
        lines.extend(role_lines)
    # 卷摘要(若有)——写手需要知道本卷主线走到哪
    summary = read_text(VOLUME_SUMMARY_FILE, "")
    if summary.strip():
        lines.append("\n## 本卷摘要\n" + summary)
    return "\n".join(lines).strip() or "暂无即时状态（开篇章节正常）。"


def structured_state_text() -> str:
    state = _trim_state_for_context(load_state())
    threads = load_active_threads()
    # active_threads 的 foreshadowing 会 append-only：只保留未回收的进上下文，已回收的沉淀在文件里
    fs = threads.get("foreshadowing")
    if isinstance(fs, dict):
        unresolved = {k: v for k, v in fs.items()
                      if not (isinstance(v, dict) and (v.get("status") in ("已回收", "已结") or v.get("resolved_chapter")))}
        threads = {**threads, "foreshadowing": unresolved}
    summary = read_text(VOLUME_SUMMARY_FILE, "")

    lines: List[str] = []
    # Timeline info from state.json
    raw_state = load_state()
    tl = raw_state.get("timeline") or {}
    if tl:
        lines.append(f"【时间线】第{tl.get('absolute_day', '?')}日·{tl.get('time_of_day', '?')}·{tl.get('season', '?')}")
        timers = tl.get("pending_timers") or []
        urgent = [t for t in timers if t.get("urgency") in ("极高", "高")]
        if urgent:
            for t in urgent[:3]:
                lines.append(f"  ⚠ {t.get('event','')}（截止第{t.get('due_day','?')}日）")

    parts = []
    if lines:
        parts.append("\n".join(lines))
    parts.append("## current_state.json\n" + json.dumps(state, ensure_ascii=False, indent=2))
    parts.append("## active_threads.json（仅未回收）\n" + json.dumps(threads, ensure_ascii=False, indent=2))
    if summary.strip():  # 空卷摘要不占位
        parts.append("## volume_summary.md\n" + summary)
    return "\n\n".join(parts)


def ledger_context_for_writer(beat: Dict[str, Any], current_chapter: int = 0) -> str:
    """三档激活 + 有界增长：写到几百章上下文也不爆。
    常驻项（约束/悬空账）按"最近+永久铁律"封顶；索引项只列最近露面的活跃实体。"""
    ledger = load_ledger()
    beat_text = json.dumps(beat, ensure_ascii=False)
    cast = set(str(c) for c in (beat.get("出场角色") or []))
    aliases = chunk_aliases()
    cast = {aliases.get(c, c) for c in cast}
    if not current_chapter:
        current_chapter = int(beat.get("章节编号") or 0)

    lines: List[str] = []

    # —— 常驻：物品清单摘要（替代旧 resources）——
    inventory = ledger.get("inventory") or {}
    inv_lines = []
    # Currency (always show, 1 line)
    currency = inventory.get("currency") or {}
    if currency:
        parts = [f"{k}{v}" for k, v in currency.items() if k != "notes" and v]
        if parts:
            inv_lines.append(f"财产：{'、'.join(parts)}")
    # Techniques (always show - prevents "forgotten ability")
    techniques = inventory.get("techniques") or []
    active_tech = [t for t in techniques if t.get("status") != "过时"]
    if active_tech:
        tech_str = "、".join(f"{t['name']}({t.get('type','')})" for t in active_tech[:10])
        inv_lines.append(f"已习得：{tech_str}")
    # Key items (show items with status=持有)
    key_items = [i for i in (inventory.get("key_items") or []) if i.get("status") == "持有"]
    if key_items:
        items_str = "、".join(f"{i['name']}({i.get('location','随身')})" for i in key_items[:12])
        inv_lines.append(f"关键物品：{items_str}")
    # Consumables with qty > 0
    consumables = [c for c in (inventory.get("consumables") or []) if (c.get("qty") or 0) > 0]
    if consumables:
        cons_str = "、".join(f"{c['name']}×{c['qty']}" for c in consumables[:8])
        inv_lines.append(f"消耗品：{cons_str}")
    if inv_lines:
        lines.append("【物品清单（必须与正文一致，禁止使用未持有物品/未习得技能）】")
        lines.extend(inv_lines)

    # —— 愿录摘要 ——
    ly_log = ledger.get("liaoYuan_log") or []
    if ly_log:
        latest = ly_log[-1]
        lines.append(f"\n【愿录】等级：{latest.get('level_after', '?')} | 累计了愿：{len(ly_log)}次")
        if len(ly_log) >= 2:
            prev = ly_log[-2]
            lines.append(f"  近期：第{prev.get('chapter','?')}章{prev.get('wish','')}→{prev.get('reward','')}")
        lines.append(f"  最近：第{latest.get('chapter','?')}章{latest.get('wish','')}→{latest.get('reward','')}")

    # —— 常驻：悬空未结清账（已结清的自动退出，所以天然有界）——
    open_obs = [o for o in (ledger.get("obligations") or []) if isinstance(o, dict) and o.get("status") != "已结"]
    if open_obs:
        lines.append("\n【未结清账·悬空中（还没还的债/承诺/因果，写作时要记得它们还悬着）】")
        for o in open_obs[-15:]:  # 同时悬空超过15条本身就是剧情问题，硬封顶
            lines.append(f"- {o.get('id','')} {o.get('desc','')}（起于第{o.get('since_chapter','?')}章）")

    # —— 约束账：永久铁律全留 + 情境约束只留最近若干（防 append-only 无限涨）——
    constraints = [c for c in (ledger.get("constraints") or []) if isinstance(c, dict) and c.get("binding") == "强"]
    permanent = [c for c in constraints if c.get("scope") == "永久" or c.get("permanent")]
    situational = [c for c in constraints if c not in permanent]
    # 情境约束：与本章出场角色/地点相关的优先，其余只取最近 8 条
    relevant_sit = [c for c in situational if any(name in (c.get("desc") or "") for name in cast)]
    recent_sit = [c for c in situational if c not in relevant_sit][-8:]
    show_constraints = permanent + relevant_sit + recent_sit
    if show_constraints:
        lines.append("\n【约束账·已成事实（不可推翻，约束本章写作）】")
        for c in show_constraints:
            lines.append(f"- {c.get('desc','')}")

    # —— 实体三档：本章相关给全卡，最近露面的活跃实体给索引，久未露面的沉睡不进 ——
    entities = ledger.get("entities") or {}
    active_cards, index_lines = [], []
    underwater_lines = []  # 冰山水下:secrets 等本章不能写破、但要影响角色反应的信息
    for name, e in entities.items():
        if e.get("status") in ("退场", "沉睡"):
            continue
        in_scene = name in cast or (e.get("type") in ("地点", "势力", "物件") and name in beat_text)
        if in_scene:
            voice = f"\n  声音：{e['voice']}" if e.get("voice") else ""
            facts = "".join(f"\n  - {f}" for f in (e.get("facts") or [])[:6])
            realm = f"\n  境界：{e['realm']}" if e.get("realm") else ""
            skills = ""
            if e.get("skills"):
                active_skills = [s for s in e["skills"] if isinstance(s, dict) and s.get("status") != "过时"]
                sk_list = [f"{s.get('name','')}({s.get('level','')})" for s in active_skills[:8]]
                if sk_list:
                    skills = f"\n  技能：{'、'.join(sk_list)}"
            weapons = f"\n  武器：{'、'.join(str(w) for w in e['weapons'][:3])}" if e.get("weapons") else ""
            injuries = f"\n  伤势：{e['injuries']}" if e.get("injuries") else ""
            goal = f"\n  当前目标：{e['current_goal']}" if e.get("current_goal") else ""
            enemies_str = ""
            if e.get("enemies"):
                en_list = [f"{en.get('name','')}({en.get('intensity','')})" for en in e["enemies"][:4] if isinstance(en, dict)]
                if en_list:
                    enemies_str = f"\n  仇敌：{'、'.join(en_list)}"
            # 秘密归入水下层,不再内联到角色卡(冰山:知道但本章不能说破)
            if e.get("secrets"):
                for s in e["secrets"][:3]:
                    if isinstance(s, dict) and s.get("secret"):
                        known_by = s.get("known_by") or []
                        kb = f"（已知情者：{'、'.join(str(k) for k in known_by)}）" if known_by else "（尚无人知）"
                        underwater_lines.append(f"- {name} 的秘密：{s['secret']}{kb}")
            # 自欺也归入水下层:角色对自己讲的谎,绝不说破,只靠行动反驳
            sd = e.get("self_deception")
            if isinstance(sd, dict) and sd.get("lie") and sd.get("status") != "已破":
                underwater_lines.append(f"- {name} 的自欺：他对自己说「{sd['lie']}」——本章绝不点破，只能让他的行动与这句话矛盾。")
            # 弧线内核:want/need 作可见内驱(指导本章动机),lie/truth 不内联(归水下)
            arc = e.get("arc_core")
            arc_str = ""
            if isinstance(arc, dict) and (arc.get("want") or arc.get("need")):
                drive = []
                if arc.get("want"):
                    drive.append(f"想要={arc['want']}")
                if arc.get("need"):
                    drive.append(f"真正需要={arc['need']}")
                arc_str = f"\n  内驱：{'；'.join(drive)}"
                if arc.get("lie"):
                    underwater_lines.append(f"- {name} 的谎（弧线内核）：「{arc['lie']}」——他要到弧线转折才会看清，本章不说破。")
            active_cards.append(f"- [{e.get('type','?')}] {name}：{e.get('summary','')}{voice}{realm}{skills}{weapons}{injuries}{goal}{arc_str}{enemies_str}{facts}")
        elif e.get("status") == "活跃":
            # 只索引最近 15 章露过面的活跃实体，久未出场的不占位（仍在 ledger.json 里，需要时检索得到）
            last_seen = int(e.get("last_seen_chapter") or 0)
            if current_chapter and (current_chapter - last_seen) <= 15:
                index_lines.append(f"- {name}（{e.get('type','?')}）：{e.get('summary','')}")
    if active_cards:
        lines.append("\n【本章相关实体·正典卡】")
        lines.extend(active_cards)
    if index_lines:
        lines.append("\n【近期在场实体·索引（需要时可一致引用，本章不展开）】")
        lines.extend(index_lines[-20:])  # 索引行硬封顶20条
    if underwater_lines:
        lines.append(
            "\n【冰山水下·你知道但本章绝不能写破】"
            "\n以下是角色的秘密。你知道全貌,但本章一个字都不能把它们写出来。"
            "它们只能影响角色的反应、选择、欲言又止——让读者隐约感觉到水下有东西,但看不清。"
            "除非本章 beat 明确要求揭露,否则永远埋着。"
        )
        lines.extend(underwater_lines)

    # —— 关系：只给本章出场者相关的，每条历史只留最近3步 ——
    rels = ledger.get("relationships") or {}
    rel_lines = []
    for pair, node in rels.items():
        members = re.split(r"[-—~、,，]", pair)
        if any(m.strip() in cast for m in members):
            hist = "；".join(f"第{h.get('chapter','?')}章{h.get('event','')}" for h in (node.get("history") or [])[-3:])
            rel_lines.append(f"- {pair}：{node.get('current','')}" + (f"（{hist}）" if hist else ""))
    if rel_lines:
        lines.append("\n【本章相关关系·当前与近期轨迹】")
        lines.extend(rel_lines)

    # —— 势力账本：给出与本章相关的势力状态 ——
    factions = ledger.get("factions") or {}
    if factions:
        faction_lines = []
        for fname, fdata in factions.items():
            if not isinstance(fdata, dict) or fdata.get("status") == "瓦解":
                continue
            # 本章出场角色属于该势力,或势力本身在 beat 里被提及
            members = fdata.get("members") or []
            relevant = any(m in cast for m in members) or fname in beat_text
            if not relevant:
                last_upd = int(fdata.get("last_updated") or 0)
                if current_chapter and (current_chapter - last_upd) > 20:
                    continue
            rels_str = ""
            f_rels = fdata.get("relationships") or []
            if f_rels:
                rels_str = "；".join(f"{r.get('target','')}={r.get('relation','')}" for r in f_rels[:4] if isinstance(r, dict))
                rels_str = f" 关系:[{rels_str}]"
            faction_lines.append(
                f"- {fname}({fdata.get('type','')}) "
                f"首领:{fdata.get('leader','?')} "
                f"对主角:{fdata.get('stance_to_mc','未知')} "
                f"状态:{fdata.get('status','活跃')}"
                f"{rels_str}"
            )
        if faction_lines:
            lines.append("\n【势力账本·当前格局】")
            lines.extend(faction_lines[:10])

    # —— 主题论辩账本：只在本章 beat 碰主题、或本章出场角色代言了某立场时注入 ——
    stances = ledger.get("thematic_stances") or []
    theme_signal = beat.get("主题折射") or beat.get("主题") or beat.get("困境")
    stance_lines = []
    for s in stances:
        if not isinstance(s, dict) or not s.get("question"):
            continue
        positions = s.get("positions") or []
        cast_holders = [p for p in positions if isinstance(p, dict) and p.get("holder") in cast]
        # 触发条件:本章有出场角色代言这个问题，或 beat 显式标了主题信号
        if not cast_holders and not theme_signal:
            continue
        show_pos = cast_holders or [p for p in positions if isinstance(p, dict)][:3]
        pos_str = "；".join(
            f"{p.get('holder','?')}认为「{p.get('answer','')}」" for p in show_pos[:3]
        )
        stance_lines.append(f"- 问：{s['question']} | {pos_str}")
    if stance_lines:
        lines.append(
            "\n【主题论辩·开放问句（不要让任何人把这些当道理讲出来；只让本章的选择和后果替它发声，本卷内不下结论）】"
        )
        lines.extend(stance_lines[:4])

    return "\n".join(lines).strip() or "暂无正典账本记录（开篇章节正常）。"


def character_arcs_for_writer(beat: Dict[str, Any], max_per_role: int = 3) -> str:
    """血肉：只调本章出场角色最近几条内在笔记。"""
    text = read_text(CHARACTER_ARCS_FILE, "")
    if not text:
        return "暂无人物内在笔记（开篇章节正常）。"
    cast = [str(c) for c in (beat.get("出场角色") or [])]
    aliases = chunk_aliases()
    cast = [aliases.get(c, c) for c in cast]
    # character_arcs.md 是按章追加的自由文字；按出场角色名筛行，取最近的
    relevant = [ln.strip() for ln in text.splitlines() if ln.strip() and any(name in ln for name in cast)]
    if not relevant:
        return "本章出场角色暂无内在笔记记录。"
    return "\n".join(relevant[-(max_per_role * max(1, len(cast))):])



def recent_ledger_tail(max_chars: int = 6000) -> str:
    """分级时效：台账日志只给最近 2 章全文，更早的不进上下文（已在 ledger/state/卷摘要里沉淀）。
    避免 append-only 日志无限膨胀——这是写手上下文最大的 token 黑洞。"""
    text = read_text(BASE_DIR / "07-动态状态台账.md")
    if not text:
        return ""
    # 按 "### 第N章自动更新" 切块，保留最近 2 块
    blocks = re.split(r"(?=### 第\d+章自动更新)", text)
    head = blocks[0] if blocks and not blocks[0].lstrip().startswith("### 第") else ""
    chapter_blocks = [b for b in blocks if b.lstrip().startswith("### 第")]
    recent = chapter_blocks[-2:] if chapter_blocks else []
    result = "\n".join(recent).strip()
    if not result:
        # 没有章节块时（开篇），退回原始头部，但仍设硬上限
        result = (head or text)[:1500]
    elif len(result) > max_chars:
        result = result[-max_chars:]
    return result


def safe_story_core_for_writer() -> str:
    """Writer 只拿明线设定，避免提前知道暗线真相。"""
    text = read_text(BASE_DIR / "09-故事核.md", "")
    if not text:
        return ""
    stop_headings = [
        "弧与弧之间有暗线串联",
        "## 主线冲突",
        "## 读者期待",
    ]
    lines: List[str] = []
    skip_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in stop_headings):
            skip_block = True
            if stripped == "## 读者期待":
                skip_block = False
            if skip_block:
                continue
        if skip_block and stripped.startswith("## "):
            skip_block = False
        if not skip_block:
            lines.append(line)
    safe = "\n".join(lines).strip()
    safe += "\n\n## 写手安全规则\n- 只按明线写系统、修炼、人物目标和本章 beat。\n- 不要主动解释任何尚未在正文公开的根源、来历或终局答案。\n- 暗线只在 beat 明确安排时用表层现象呈现。\n"
    return safe


REALM_ORDER = ["叩门", "通脉", "凝元", "开窍", "化神", "归真", "明心", "通玄", "听道", "御道", "齐物", "忘我"]
REALM_ORDINALS = ["第一境", "第二境", "第三境", "第四境", "第五境", "第六境",
                  "第七境", "第八境", "第九境", "第十境", "第十一境", "第十二境"]


def current_mc_realm() -> str:
    """从 state.json 读 MC 当前境界，缺省叩门。"""
    state = load_state()
    realm = state.get("mc_realm")
    if isinstance(realm, str):
        for name in REALM_ORDER:
            if name in realm:
                return name
    return "叩门"


def safe_cultivation_for_writer() -> str:
    """境界设定跟随 MC 当前进度做滑动窗口：只给[已达境-1, 当前境, 下一境]，
    既不砍过头（修到化神还看不到化神），也不全量塞 7500 token，且永不泄露后期隐藏真相。"""
    text = read_text(BASE_DIR / "02-修炼境界.md", "")
    if not text:
        return ""
    # 隐藏真相段永远砍掉
    hidden_cut = len(text)
    for marker in ["## 隐藏的世界观真相", "## 境界与了愿系统的关系"]:
        idx = text.find(marker)
        if idx >= 0:
            hidden_cut = min(hidden_cut, idx)
    body = text[:hidden_cut]

    realm = current_mc_realm()
    i = REALM_ORDER.index(realm)
    keep = set(range(max(0, i - 1), min(len(REALM_ORDER), i + 2)))  # 已达境-1 ~ 下一境

    # 用「### 第N境：境名」标题切段，只保留窗口内的境
    head_end = body.find("### 第一境")
    head = body[:head_end] if head_end > 0 else ""
    parts = re.split(r"(?=^###\s+第[一二三四五六七八九十]+境)", body, flags=re.MULTILINE)
    chosen = [head.strip()] if head.strip() else []
    for part in parts:
        m = re.match(r"^###\s+(第[一二三四五六七八九十]+境)", part.strip())
        if not m:
            continue
        ordinal = m.group(1)
        if ordinal in REALM_ORDINALS and REALM_ORDINALS.index(ordinal) in keep:
            chosen.append(part.strip())
    safe = "\n\n".join(chosen).strip()
    safe += (
        f"\n\n## 写手安全规则\n"
        f"- 主角当前境界：{realm}（第{i + 1}境）。本节只展示主角已达境界附近的能力表现和升级节奏。\n"
        f"- 不要让主角使用尚未达到的高境能力。\n"
        f"- 不要提前解释任何后期答案或根源设定。\n"
    )
    return safe


def safe_world_bible_for_writer() -> str:
    """Writer 必须知道基础世界观，但不拿后期谜底。"""
    text = read_text(BASE_DIR / "02-世界观设定圣经.md", "")
    if not text:
        return ""
    safe = text.strip()
    safe += "\n\n## 写手安全规则\n- 本文件是硬设定，地名、势力、货币、修炼资源不要自行发明替换。\n- 新增设定必须贴合晏朝、巡夜司、书院、宗门、江湖、荒年、妖祟这些既有框架。\n- 不要把世界观写成说明书，只在场景、对话和行动里自然露出。\n"
    return safe


def safe_outline_for_writer(chapter: int) -> str:
    """Writer 只拿当前章节附近的卷纲，避免提前知道远期反转。"""
    text = read_text(BASE_DIR / "卷纲" / "10-卷纲.md", "")
    if not text:
        return ""
    window = 2
    lines: List[str] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| 章节 "):
            in_table = True
            lines.append(line)
            continue
        if in_table and stripped.startswith("| ---"):
            lines.append(line)
            continue
        if in_table and stripped.startswith("|"):
            numbers = [int(num) for num in re.findall(r"\d+", stripped.split("|")[1])]
            include = any(abs(num - chapter) <= window for num in numbers)
            if include:
                lines.append(line)
            continue
        if in_table and not stripped.startswith("|"):
            in_table = False
        if not in_table:
            if stripped.startswith("## 伏笔规划"):
                break
            lines.append(line)
    lines.append("")
    lines.append("## 写手安全规则")
    lines.append("- 只执行本章 beat 和当前章附近卷纲，不提前铺远期大反转。")
    lines.append("- 卷纲节奏规则不等于长线伏笔按固定章数外显。")
    return "\n".join(lines).strip()


def long_foreshadowing_text(chapter: int, writer_safe: bool = False) -> str:
    text = read_text(LONG_FORESHADOWING_FILE, "")
    if not text:
        return "暂无长线伏笔资产库。"
    if not writer_safe:
        return text
    safe_lines: List[str] = ["# 长线伏笔安全提醒", ""]
    allowed_keys = (
        "- 等级",
        "- 生命周期",
        "- 表层线索",
        "- 外显条件",
        "- 外显方式",
        "- 当前状态",
    )
    safe_index = 1
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### LF-"):
            safe_lines.append(f"### 长线安全线索 {safe_index}")
            safe_index += 1
            continue
        if stripped.startswith(allowed_keys):
            safe_lines.append(line)
    safe_lines.append("")
    safe_lines.append("## 写手使用规则")
    safe_lines.append("- 内部检查窗口不是写作任务，不要机械地每隔若干章提一次。")
    safe_lines.append("- 只有 beat 明确安排且场景自然时，才外显表层线索。")
    safe_lines.append("- 长线伏笔可以沉睡很久；没有自然场景时，宁可不写。")
    safe_lines.append("- 只能外显表层线索，不要解释未公开答案。")
    safe_lines.append("- 没有 beat 明确要求时，不要主动回收长线伏笔。")
    safe_lines.append("- 只有 beat 明确安排时，章末钩子才可以呼应长线伏笔，并且必须落在具体物件、动作或声音上。")
    return "\n".join(safe_lines).strip() + "\n"


def sanitize_beat_for_writer(value: Any) -> Any:
    """Writer 不需要看到内部 LF 编号，避免复制进正文。"""
    if isinstance(value, dict):
        return {key: sanitize_beat_for_writer(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_beat_for_writer(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"\[?LF-\d{3}\]?", "长线线索", value)
    return value


def render_sections(sections: List[Dict[str, Any]]) -> str:
    return "\n\n".join(f"===== {section['title']} =====\n{section['body']}" for section in sections if section.get("body"))


def select_sections_for_budget(sections: List[Dict[str, Any]], threshold: int) -> List[Dict[str, Any]]:
    priority_rank = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    selected: List[Dict[str, Any]] = []
    total = 0
    for section in sorted(sections, key=lambda item: priority_rank.get(str(item.get("priority")), 2)):
        tokens = int(section.get("tokens") or estimate_tokens(str(section.get("body") or "")))
        if total + tokens <= threshold or section.get("priority") in ("critical", "high"):
            selected.append(section)
            total += tokens
    return selected


def compress_sections_if_needed(
    role: str,
    chapter: int,
    sections: List[Dict[str, Any]],
    run_cfg: Dict[str, Any],
    timeout: int,
) -> str:
    full_text = render_sections(sections)
    total_tokens = estimate_tokens(full_text)
    threshold = role_compress_threshold(role, run_cfg)
    if total_tokens <= threshold:
        cli_print(f"{role} 上下文≈{total_tokens} tokens，未触发压缩（阈值 {threshold}）。")
        return full_text

    cli_print(f"{role} 上下文≈{total_tokens} tokens，超过阈值 {threshold}，开始压缩。")
    selected = select_sections_for_budget(sections, threshold)
    selected_text = render_sections(selected)
    if estimate_tokens(selected_text) <= threshold:
        write_text(role_artifact("context", chapter, f"{role}_selected_context.md"), selected_text)
        return selected_text

    critical = [section for section in selected if section.get("priority") == "critical" or not section.get("compressible")]
    compressible = [section for section in selected if section.get("compressible") and section not in critical]
    keep_text = render_sections(critical)
    compress_text = render_sections(compressible)
    if not compress_text:
        write_text(role_artifact("context", chapter, f"{role}_over_budget_context.md"), selected_text)
        return selected_text

    compression_prompt = read_text(PROMPTS_DIR / "compressor.md") or (
        "你是上下文压缩器。保留事实、约束、伏笔、人物状态和写作禁忌，删除重复表达。输出结构化摘要。"
    )
    compression_input = (
        f"目标角色：{role}\n"
        f"目标章节：第{chapter}章\n"
        f"压缩目标：保留后续执行任务所需信息，压到原文的30%以内。\n\n"
        f"{compress_text}"
    )
    if run_cfg.get("dry_run"):
        summary = "dry-run：此处会调用 compressor 生成角色专用摘要。"
    else:
        summary = call_role(
            "compressor",
            compression_prompt,
            compression_input,
            role_artifact("context", chapter, f"{role}_compression_report.md"),
            timeout,
            3000,
            role_artifact("context", chapter, f"{role}_compression_input.md"),
        )
    final_text = keep_text + "\n\n===== 压缩摘要 =====\n" + summary
    write_text(role_artifact("context", chapter, f"{role}_compressed_context.md"), final_text)
    cli_print(f"{role} 压缩后上下文≈{estimate_tokens(final_text)} tokens。")
    return final_text


def load_index() -> Dict[str, Any]:
    return load_json(CHUNKS_DIR / "index.json")


def chunk_aliases() -> Dict[str, str]:
    return {
        "沈归舟": "沈安",
        "阿墨": "黑子",
        "方青瓷": "方绾",
        "打斗": "打斗场景",
        "日常": "日常对话",
        "夜行": "转场",
        "夜行探查": "转场",
        "探查": "转场",
        "调查": "转场",
        "夜间探查": "转场",
        "查案": "转场",
        "追踪": "转场",
    }


def resolve_chunk_key(name: str, index: Dict[str, Any]) -> str:
    if name in index:
        return name
    alias = chunk_aliases().get(name)
    if alias and alias in index:
        return alias
    for part in re.split(r"[/、,，\s]+", name):
        if part in index:
            return part
    return ""


def load_chunk(name: str, index: Optional[Dict[str, Any]] = None) -> str:
    index = index or load_index()
    entry = index.get(name)
    if isinstance(entry, dict) and entry.get("file"):
        return read_text(CHUNKS_DIR / str(entry["file"]))
    return read_text(CHUNKS_DIR / f"chunk_{name}.md")


def select_chunks(beat: Dict[str, Any]) -> Dict[str, str]:
    index = load_index()
    selected: Dict[str, str] = {}
    selected_chunk_keys = set()
    for item in ["黄金法则", "负空间", "AI腔黑名单"]:
        if item in index:
            selected[item] = load_chunk(item, index)
            selected_chunk_keys.add(item)
    # 场景价值转变: 核心技法，始终注入
    scene_value_key = "场景价值转变"
    if scene_value_key in index:
        selected[f"功能_{scene_value_key}"] = load_chunk(scene_value_key, index)
        selected_chunk_keys.add(scene_value_key)
    # 潜台词: 当 beat 标注了潜台词机会时注入
    subtext_key = "潜台词"
    subtext_opp = str(beat.get("潜台词机会") or "无")
    if subtext_key in index and subtext_opp != "无":
        selected[f"功能_{subtext_key}"] = load_chunk(subtext_key, index)
        selected_chunk_keys.add(subtext_key)
    scene = beat.get("场景类型") or "日常对话"
    scene_key = resolve_chunk_key(str(scene), index)
    if scene_key:
        selected[f"场景_{scene_key}"] = load_chunk(scene_key, index)
        selected_chunk_keys.add(scene_key)
    beat_text = json.dumps(beat, ensure_ascii=False)
    keyword_chunks = [
        ("系统面板", ["系统", "面板", "愿录", "奖励", "寿命"]),
        ("章末钩子", ["章末钩子", "钩子", "结尾", "悬念"]),
        ("内心独白", ["内心", "犹豫", "想", "心里", "独白"]),
        ("打斗场景", ["打斗", "战斗", "妖祟", "刀", "危险", "遭遇"]),
        ("情绪爆发", ["情绪", "爆发", "愤怒", "崩溃", "哭", "选择"]),
        ("喜剧缓冲", ["喜剧", "缓冲", "偷吃", "笑点", "阿墨", "黑子"]),
        ("人物初登场", ["登场", "初见", "第一次见", "入局"]),
        ("反派压迫", ["反派", "压迫", "威胁", "逼迫", "站队"]),
        ("群像互动", ["群像", "众人", "县衙", "书院", "多人"]),
        ("景物描写", ["景物", "雪", "雨", "夜色", "荒年", "街", "巷"]),
        ("转场", ["转场", "三日后", "次日", "离开", "进入", "后巷", "路上"]),
        # 分析师产出的深度手法卡:存在才点亮(analyst 跑过后 index 里才有)
        ("情感高潮手法", ["高潮", "情感", "爆发", "揪心", "悲", "生死", "诀别", "重逢", "牺牲"]),
        ("铺垫手法", ["铺垫", "伏笔", "埋", "回收", "暗示", "反常", "线索"]),
        ("节奏控制手法", ["节奏", "紧张", "舒缓", "停顿", "留白", "转折", "推进"]),
        # 情感技法卡(普世craft):情感分量章节按需注入
        ("情感回响手法", ["回响", "重逢", "故地", "多年", "想起", "旧", "当年", "EA-"]),
        ("克制与留白", ["失去", "死", "告别", "诀别", "悲", "哭", "葬", "离别", "情绪裂缝"]),
        ("意难平", ["意难平", "遗憾", "错过", "没说", "本该", "差一点", "来不及"]),
        # 精品逼近手法卡(prose层,先手写以后analyst覆盖):按需点亮
        ("主角能动性", ["冲突", "选择", "决定", "对峙", "出手", "破局", "打脸", "逆转", "代价", "突破", "挫败"]),
        ("具体与投放", ["设定", "解释", "来历", "规矩", "世界观", "境界", "体系", "讲解", "介绍"]),
        ("反讽落差", ["反转", "隐瞒", "误会", "真相", "装", "不知道", "暴露", "识破", "扮", "低估", "误判"]),
        ("后续与微张力", ["噩耗", "打斗", "重大", "冲击", "之后", "缓冲", "独处", "消化", "抉择", "两难"]),
        # 主题/弧线层手法卡(Phase 2,先手写以后analyst覆盖):碰主题/道德/升级时点亮
        ("主题对位", ["主题", "立场", "论辩", "信念", "价值", "对错", "该不该", "慈悲", "代价", "意义", "折射"]),
        ("自欺与道德灰度", ["自欺", "心结", "心病", "矛盾", "灰度", "两难", "道德", "纠结", "嘴硬", "逃避", "回避"]),
        ("升级代价", ["突破", "境界", "变强", "升级", "修为", "面板", "解锁", "提升", "战力", "代价"]),
    ]
    # 关键词功能卡:按命中强度排序取前 N 张,避免 beat 撞多了全点亮把 writer 输入推爆。
    # 必选卡(黄金法则/负空间/AI腔/场景价值转变/潜台词/场景/角色)不在此列,不受 cap 限制。
    MAX_KEYWORD_CHUNKS = 6
    candidates = []
    for chunk_name, keywords in keyword_chunks:
        if chunk_name in index and chunk_name not in selected_chunk_keys:
            hits = sum(1 for word in keywords if word in beat_text)
            if hits > 0:
                candidates.append((hits, chunk_name))
    # 命中数多的优先(更贴合本章);同分按 keyword_chunks 原顺序(稳定)
    candidates.sort(key=lambda x: -x[0])
    for _hits, chunk_name in candidates[:MAX_KEYWORD_CHUNKS]:
        selected[f"功能_{chunk_name}"] = load_chunk(chunk_name, index)
        selected_chunk_keys.add(chunk_name)
    for char in (beat.get("出场角色") or ["沈安"])[:4]:
        char_key = resolve_chunk_key(str(char), index)
        if char_key:
            selected[f"角色_{char}"] = load_chunk(char_key, index)
            selected_chunk_keys.add(char_key)
    return selected


SIGNATURE_PATTERNS = [
    (r"竹杖.{0,4}(?:点|敲|划|顿)", "竹杖点地/敲地/划地"),
    (r"一下[。\n][\s\S]{0,20}两下", "「一下。两下。」节奏"),
    (r"闷闷(?:的|地)", "黑子「闷闷的」叫声"),
    (r"没.{0,2}说话", "「没说话」"),
    (r"顿了顿", "「顿了顿」"),
    (r"耳朵.{0,3}(?:压平|压着|朝.{1,4}压)", "黑子「耳朵压平/压着」"),
    (r"鼻子.{0,3}(?:拱|蹭|抽)", "黑子「鼻子拱/蹭/抽」"),
    (r"安静了.{1,4}息", "「安静了X息」"),
    (r"手.{0,2}(?:抖|颤)", "「手抖/颤」情绪裂缝"),
    (r"指节.{0,2}发白", "「指节发白」情绪裂缝"),
    (r"呼吸.{0,3}(?:断|停|顿)", "「呼吸断/停」情绪裂缝"),
]


def pacing_variety_warnings(chapter: int, lookback: int = 10) -> str:
    """Scan recent beats for scene type distribution. Return warnings."""
    beats_dir = BASE_DIR / "beats"
    scene_types = []
    for ch in range(max(1, chapter - lookback), chapter):
        beat_path = beats_dir / f"chapter_{ch}.json"
        if beat_path.exists():
            beat = load_json(beat_path, {})
            scene_types.append(beat.get("场景类型", "未知"))
    if not scene_types:
        return ""
    warnings = []
    # Consecutive same type
    if len(scene_types) >= 4:
        last_4 = scene_types[-4:]
        if len(set(last_4)) == 1:
            warnings.append(f"节奏警告：连续{len(last_4)}章都是「{last_4[0]}」类型，本章建议切换场景类型")
    # Missing variety
    from collections import Counter
    counts = Counter(scene_types)
    relaxed = sum(counts.get(t, 0) for t in ["日常", "喜剧", "对话", "休息"])
    if lookback >= 8 and relaxed == 0:
        warnings.append("节奏警告：最近8章以上无日常/喜剧/休息场景，读者可能疲劳，建议安排缓冲")
    return "\n".join(warnings)


def emotional_distribution_warnings(chapter: int, lookback: int = 10) -> str:
    """Check emotion variety from recent beats."""
    beats_dir = BASE_DIR / "beats"
    tones = []
    for ch in range(max(1, chapter - lookback), chapter):
        beat_path = beats_dir / f"chapter_{ch}.json"
        if beat_path.exists():
            beat = load_json(beat_path, {})
            conflict = beat.get("本章冲突", "") + beat.get("本章爽点", "")
            if any(w in conflict for w in ["紧张", "危险", "逼迫", "追", "打", "杀", "逃"]):
                tones.append("紧张")
            elif any(w in conflict for w in ["温暖", "感动", "信任", "帮", "救"]):
                tones.append("温暖")
            elif any(w in conflict for w in ["愤怒", "不甘", "屈辱", "恨"]):
                tones.append("愤怒")
            else:
                tones.append("中性")
    if not tones:
        return ""
    from collections import Counter
    counts = Counter(tones)
    dominant = counts.most_common(1)
    if dominant and dominant[0][1] >= len(tones) * 0.7:
        return f"情绪警告：最近{len(tones)}章中「{dominant[0][0]}」情绪占{dominant[0][1]}/{len(tones)}，建议本章调节情绪基调"
    return ""


def chapter_satisfaction_check(text: str, beat: Dict[str, Any]) -> List[str]:
    """Post-write check: did chapter deliver on beat promises?"""
    issues = []
    # Check minimum word count
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    if chinese_chars < 1800:
        issues.append(f"正文过短（{chinese_chars}字），目标2500-3500字")
    # Check if beat's 转折 keywords appear
    turning = beat.get("转折", "")
    if turning and chinese_chars > 1500:
        key_words = [w for w in re.findall(r'[一-鿿]{2,4}', turning) if len(w) >= 2]
        if key_words:
            found = sum(1 for w in key_words if w in text)
            if found < max(1, len(key_words) * 0.2):
                issues.append(f"beat规划的转折「{turning[:30]}」在正文中几乎未体现")
    return issues


def power_scaling_for_chapter() -> str:
    """Return power scaling info for MC's current realm +/- 1."""
    scaling_file = BASE_DIR / "config" / "power_scaling.json"
    if not scaling_file.exists():
        return ""
    scaling = load_json(scaling_file, {})
    ledger = load_ledger()
    mc = (ledger.get("entities") or {}).get("沈安", {})
    mc_realm = mc.get("realm", "叩门")
    REALMS = ["凡人", "叩门", "通脉", "凝元", "开窍", "化神", "归真"]
    idx = REALMS.index(mc_realm) if mc_realm in REALMS else 1
    show_realms = REALMS[max(0, idx-1):idx+2]
    lines = []
    for r in show_realms:
        info = scaling.get(r)
        if not info:
            continue
        marker = "【当前】" if r == mc_realm else ""
        lines.append(f"{r}{marker}：能做={','.join(info.get('can',[])[: 3])}；不能={','.join(info.get('cannot',[])[: 3])}；战力={info.get('combat','')}")
    return "\n".join(lines)


def recent_signature_warnings(chapter: int, lookback: int = 5) -> str:
    """扫最近 lookback 章,统计签名动作出现频率,生成禁用提醒。"""
    counts: Dict[str, int] = {}
    for ch in range(max(1, chapter - lookback), chapter):
        path = manuscript_path(ch)
        if not path.exists():
            continue
        text = read_text(path)
        for pat, label in SIGNATURE_PATTERNS:
            n = len(re.findall(pat, text))
            if n > 0:
                counts[label] = counts.get(label, 0) + n
    overused = [(label, n) for label, n in counts.items() if n >= 2]
    if not overused:
        return ""
    lines = ["以下动作/句式近5章已反复出现,本章禁止使用(换别的写法):"]
    for label, n in sorted(overused, key=lambda x: -x[1]):
        lines.append(f"- {label}(近5章共{n}次)")
    lines.append("替代:用其他感官(听/触/嗅)、不同肢体动作、或直接留白。")
    return "\n".join(lines)


WRITER_MODULES_DIR = PROMPTS_DIR / "writer_modules"


def writer_focus_modules(beat: Dict[str, Any]) -> str:
    """按 beat 内容选择性注入写作要点模块,避免 writer prompt 过载、注意力分散。
    只注入本章真正相关的规则,没标注的字段不注入对应模块。"""
    beat_blob = json.dumps(beat, ensure_ascii=False)
    cast = [str(c) for c in (beat.get("出场角色") or [])]
    scene = str(beat.get("场景类型") or "")
    selected: List[str] = []

    def add(module_name: str):
        path = WRITER_MODULES_DIR / f"{module_name}.md"
        if path.exists():
            selected.append(read_text(path).strip())

    # 对话:场景类型含对话/日常,或 beat 里有潜台词机会
    has_dialogue = any(k in scene for k in ["对话", "日常", "审", "问"]) or "潜台词" in beat_blob
    if has_dialogue:
        add("对话")
    # 潜台词:仅当 beat 明确标注且不为"无"
    qtc = str(beat.get("潜台词机会") or "")
    if qtc and qtc not in ("无", "", "None"):
        add("潜台词")
    # 黑子:出场才注入
    if "黑子" in cast or "黑子" in beat_blob:
        add("黑子")
    # 视觉:白天/强光/夜里相关,或装瞎相关场景。默认注入(主角核心设定,大部分章节相关)
    add("视觉")
    # 盲感官:主角靠听/触/嗅/温度/空间感知世界。默认注入(本书最独特的画面来源,几乎每章相关)
    add("盲感官")
    # 深度模块:仅当 beat 标注对应字段且不为"无"
    def field_active(key: str) -> bool:
        v = str(beat.get(key) or "")
        return bool(v) and v not in ("无", "", "None", "积累中，未触发", "积累中,未触发")
    if field_active("情绪裂缝"):
        add("情绪裂缝")
    if field_active("内在转变"):
        add("内在转变")
    if field_active("困境/两难") or field_active("主题折射"):
        add("困境主题")

    if not selected:
        return ""
    return "\n\n---\n\n".join(selected)


def build_writer_sections(beat: Dict[str, Any]) -> List[Dict[str, Any]]:
    chapter = int(beat.get("章节编号") or 0)
    sections = [
        make_section("故事核安全版", safe_story_core_for_writer(), "critical", False),
        make_section("世界观设定安全版", safe_world_bible_for_writer(), "critical", False),
        make_section("修炼境界安全版", safe_cultivation_for_writer(), "normal", True),
        make_section("卷纲安全版", safe_outline_for_writer(chapter), "high", True),
        make_section("长线伏笔安全提醒", long_foreshadowing_text(chapter, writer_safe=True), "high", True),
        make_section("即时状态（时间线/地点/本章角色状态）", writer_state_digest(beat), "high", True),
        # 正典账本：悬空账/强约束/资源常驻不可压缩，是防穿帮和逻辑崩坏的命门
        make_section("正典账本（资源/未结清账/约束/本章相关实体与关系）", ledger_context_for_writer(beat), "critical", False),
        # 血肉：本章出场角色的内在演变笔记
        make_section("本章出场角色·内在笔记", character_arcs_for_writer(beat), "high", True),
        make_section("最近台账日志摘录", recent_ledger_tail(), "low", True),
    ]
    for name, content in select_chunks(beat).items():
        priority = "critical" if name in ("黄金法则", "负空间", "AI腔黑名单") else "normal"
        sections.append(make_section(name, content, priority, priority != "critical"))
    sections.append(make_section("本章 beat", json.dumps(sanitize_beat_for_writer(beat), ensure_ascii=False, indent=2), "critical", False))
    # 按需注入写作要点模块(对话/潜台词/黑子/视觉/情绪裂缝/内在转变/困境主题)
    focus = writer_focus_modules(beat)
    if focus:
        sections.append(make_section("本章写作要点（只针对本章，没列的规则不用强行套用）", focus, "critical", False))
    sig_warn = recent_signature_warnings(chapter)
    if sig_warn:
        sections.append(make_section("近期重复动作禁用清单", sig_warn, "critical", False))
    # Pacing + emotion warnings (Change 11)
    pacing_warn = pacing_variety_warnings(chapter)
    if pacing_warn:
        sections.append(make_section("节奏多样性警告", pacing_warn, "high", False))
    emotion_warn = emotional_distribution_warnings(chapter)
    if emotion_warn:
        sections.append(make_section("情绪分布警告", emotion_warn, "high", False))
    # Motifs relevant to this chapter (Change 5)
    ledger_data = load_ledger()
    motifs = ledger_data.get("motifs") or []
    beat_text_str = json.dumps(beat, ensure_ascii=False)
    relevant_motifs = [m for m in motifs if m.get("symbol", "") in beat_text_str or (chapter - m.get("last_chapter", 0)) <= 5]
    if relevant_motifs:
        motif_lines = []
        for m in relevant_motifs[:4]:
            evol = m.get("evolution", [])
            evol_str = f"（演变：{'→'.join(evol[-3:])}）" if evol else ""
            motif_lines.append(f"- {m['symbol']}：{m.get('meaning','')}{evol_str}")
        sections.append(make_section("意象·本章可用", "\n".join(motif_lines), "normal", True))
    # 情感回响:beat 标注了"回响[EA-XXX]"时,注入该锚点内容+冰山回响指令
    echo_ids = re.findall(r"回响\s*\[?(EA-\d+)\]?", beat_text_str)
    if echo_ids:
        anchors = {a.get("id"): a for a in (ledger_data.get("emotional_anchors") or []) if isinstance(a, dict)}
        echo_lines = []
        for eid in echo_ids:
            a = anchors.get(eid)
            if a:
                obj = f"可用的物件/动作：{a.get('object')}" if a.get("object") else ""
                echo_lines.append(f"- {eid}（第{a.get('chapter')}章埋下）：{a.get('content','')}\n  {obj}")
        if echo_lines:
            echo_text = (
                "本章要回响以下早期埋下的情感锚点。回响的写法（务必遵守）：\n"
                "1. 绝对不要直接提那件旧事、不要让角色说\"我想起了当年……\"。\n"
                "2. 用一个物件、一个动作、一个相似的情境，让旧事自己浮上来——读者会想起，不需要你点破。\n"
                "3. 力量来自\"东西没变，人变了\"的落差。克制，留白，点到为止。\n\n"
                + "\n".join(echo_lines)
            )
            sections.append(make_section("情感回响·本章任务", echo_text, "critical", False))
    # Power scaling (Change 6)
    ps_text = power_scaling_for_chapter()
    if ps_text:
        sections.append(make_section("境界能力参考(本阶段)", ps_text, "normal", True))
    # Travel matrix - only when travel-related (Change 7)
    beat_str = json.dumps(beat, ensure_ascii=False)
    travel_keywords = ["赶路", "出发", "到达", "时辰", "路上", "步行", "骑"]
    if any(kw in beat_str for kw in travel_keywords):
        travel_file = BASE_DIR / "config" / "travel_matrix.json"
        if travel_file.exists():
            travel_data = load_json(travel_file, {"distances": [], "rules": []})
            rules = "\n".join(travel_data.get("rules", [])[:4])
            # Find relevant distances based on current location
            current_loc = (load_state().get("current_location") or "")[:10]
            relevant = [d for d in travel_data.get("distances", []) if current_loc and (current_loc in d.get("from", "") or current_loc in d.get("to", ""))]
            if relevant:
                dist_str = "\n".join(f"- {d['from']}→{d['to']}：{d['time']}" for d in relevant[:5])
                sections.append(make_section("旅行距离参考", f"{rules}\n{dist_str}", "normal", True))
    # Economy - only when transaction-related (Change 7)
    econ_keywords = ["银子", "铜钱", "买", "卖", "付", "花了", "价"]
    if any(kw in beat_str for kw in econ_keywords):
        econ_file = BASE_DIR / "config" / "economy.json"
        if econ_file.exists():
            econ = load_json(econ_file, {})
            prices = econ.get("prices", {})
            # Flatten relevant prices
            price_lines = []
            for cat, items in prices.items():
                if isinstance(items, dict):
                    for k, v in list(items.items())[:3]:
                        price_lines.append(f"- {k}：{v}")
            if price_lines:
                currency_info = econ.get("currency", {}).get("换算", "")
                sections.append(make_section("经济物价参考", f"{currency_info}\n" + "\n".join(price_lines[:8]), "normal", True))
    return sections


def build_writer_input(beat: Dict[str, Any], chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    return compress_sections_if_needed("writer", chapter, build_writer_sections(beat), run_cfg, timeout)


def check_vision_consistency(text: str) -> List[str]:
    """主角是盲人（白天视线发白、夜里看得清，装瞎时不能露）。
    这是玄幻，主角靠夜视/灵觉'看'是允许的，绝大多数'看'都放行。
    只卡两种真突兀：①白天强光场景里主角精细视觉；②装瞎场景里叙事却写主角看清。"""
    issues = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # 主角主动精细视觉的词（看清细节级别，不含泛用的"看"）
    fine_vision = ["看清", "看见", "看到", "回头看", "看了一眼", "定睛", "瞧清", "尽收眼底"]
    # 白天/强光信号
    daylight = ["白天", "正午", "晌午", "日头", "烈日", "阳光", "日光", "白日", "大太阳", "晒"]
    # 装瞎信号
    feign = ["装作看不见", "装瞎", "装出摸索", "假装看不见", "摸索着", "故作失明", "扮作盲人"]

    has_daylight = any(d in text for d in daylight)
    has_feign = any(f in text for f in feign)

    for i, l in enumerate(lines):
        # 只看与主角相关的视觉行（含"沈安"或承接其动作的短行）
        if not any(v in l for v in fine_vision):
            continue
        if "沈安" not in l and "他" not in l[:6]:
            continue
        # 情况1：本行/邻近出现白天信号 + 精细视觉
        window = "".join(lines[max(0, i - 2):i + 1])
        if any(d in window for d in daylight) and not any(n in window for n in ["夜", "月光", "灯", "黑", "暗"]):
            issues.append(f"视觉穿帮（白天强光下主角精细视觉）：{l[:30]}")
    # 情况2：全章有装瞎信号，又出现主角"看清"细节
    if has_feign:
        for l in lines:
            if ("看清" in l or "尽收眼底" in l or "定睛" in l) and "沈安" in l:
                issues.append(f"视觉穿帮（装瞎时叙事却写主角看清）：{l[:30]}")
                break
    return issues


def fact_check_against_ledger(text: str) -> List[str]:
    """用 ledger 角色卡核对正文,抓 LLM 幻觉穿帮。
    只查能用规则检测的硬事实,语义级的留给 reviewer。
    返回 warnings(不阻断,提醒 reviewer/editor 注意)。"""
    warnings: List[str] = []
    ledger = load_ledger()
    entities = ledger.get("entities") or {}

    # 1. 技能核查:正文里"使出/施展/运起/催动 XX术/功/诀"但角色卡 skills 里没有
    skill_patterns = re.findall(r"(?:使出|施展|运起|催动|祭出|打出)\s*[「""]?([一-鿿]{2,6}(?:术|功|诀|法|拳|掌|剑|指|步|阵|丹|散|符))", text)
    if skill_patterns:
        # 收集所有已知技能名
        all_known_skills = set()
        for e in entities.values():
            for sk in (e.get("skills") or []):
                if isinstance(sk, dict) and sk.get("name"):
                    all_known_skills.add(sk["name"])
                elif isinstance(sk, str):
                    all_known_skills.add(sk)
        for sk_name in skill_patterns:
            if sk_name not in all_known_skills and len(all_known_skills) > 0:
                warnings.append(f"事实核查·技能：正文使用了'{sk_name}'但角色卡中无此技能记录")

    # 2. 伤势核查:角色卡有伤但正文里该角色做了剧烈动作(粗检)
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        injury = e.get("injuries") or ""
        if not injury or injury in ("无", ""):
            continue
        # 有伤的角色,检查正文里是否有该角色的剧烈动作且没提到伤
        if name in text:
            # 只在伤势严重时检查(含"骨折""重伤""断""瘫")
            severe = any(w in injury for w in ["骨折", "重伤", "断", "瘫", "昏迷", "中毒"])
            if severe:
                # 检查正文里该角色是否有剧烈动作
                action_words = ["飞身", "纵身", "挥刀", "拔剑", "冲上", "跃起", "翻墙", "狂奔"]
                for aw in action_words:
                    # 简单检查:动作词附近(前后50字)有角色名
                    for m in re.finditer(re.escape(aw), text):
                        window = text[max(0, m.start()-50):m.end()+50]
                        if name in window:
                            warnings.append(f"事实核查·伤势：{name}当前'{injury}'但正文有剧烈动作'{aw}'")
                            break

    # 3. 秘密核查:某秘密已被某人知道,但正文里还在对该人隐瞒
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        for secret in (e.get("secrets") or []):
            if not isinstance(secret, dict):
                continue
            known_by = secret.get("known_by") or []
            secret_content = secret.get("secret") or ""
            if not secret_content or not known_by:
                continue
            # 检查:正文里是否有"对已知者隐瞒"的信号
            hide_words = ["瞒着", "不让.*知道", "装作.*不知", "隐瞒"]
            for person in known_by:
                if person in text:
                    for hw in hide_words:
                        pattern = f"{person}.*{hw}.*{secret_content[:4]}"
                        if re.search(pattern, text[:3000]):
                            warnings.append(f"事实核查·秘密：'{secret_content}'已被{person}知道,但正文疑似还在对其隐瞒")
                            break

    # 4. 资源核查:ledger 里资源为0/无但正文里还在使用
    resources = ledger.get("resources") or {}
    for res_name, res_value in resources.items():
        if not res_value:
            continue
        # 检查"已耗尽"的资源是否还在用
        exhausted_signals = ["0", "无", "耗尽", "用完", "花光"]
        is_exhausted = any(str(res_value).strip() == s or s in str(res_value) for s in exhausted_signals)
        if is_exhausted and res_name in text:
            # 正文提到了已耗尽的资源,可能穿帮
            use_words = ["掏出", "拿出", "使用", "服下", "贴上", "取出"]
            for uw in use_words:
                if uw in text and res_name in text[max(0, text.find(uw)-30):text.find(uw)+30]:
                    warnings.append(f"事实核查·资源：'{res_name}'当前为'{res_value}'但正文疑似还在使用")
                    break

    # 5. Dead character resurrection check
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        if e.get("status") in ("死亡", "已死") and name in text:
            # Allow in memory/flashback context
            name_pos = text.find(name)
            context_window = text[max(0, name_pos - 30):name_pos + len(name) + 30]
            memory_words = ["回忆", "想起", "当年", "曾经", "生前", "以前", "那时"]
            if not any(mw in context_window for mw in memory_words):
                warnings.append(f"死亡角色复活（{name}已死亡但在正文中非回忆语境出现）：{context_window[:40]}")

    # 6. Temporal 穿帮·境界倒退：正文写到某角色处于比账本记录更低的境界（修为只升不降，除非有跌境设定）
    REALM_SEQ = ["凡人", "叩门", "通脉", "凝元", "开窍", "化神", "归真", "明心", "通玄", "听道", "御道", "齐物", "忘我"]
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        cur_realm = e.get("realm") or ""
        cur_idx = REALM_SEQ.index(cur_realm) if cur_realm in REALM_SEQ else -1
        if cur_idx <= 0 or name not in text:
            continue
        # 正文若把该角色明确写成更低的境界（"突破到X""X境的Y"），且X低于账本当前境，提示穿帮
        for lower in REALM_SEQ[:cur_idx]:
            for verb in ["突破到", "晋入", "刚到", "还停在", "尚在"]:
                pat = f"{verb}{lower}"
                if pat in text:
                    win = text[max(0, text.find(pat) - 20):text.find(pat) + 20]
                    if name in win:
                        warnings.append(f"事实核查·境界倒退：{name}账本已是'{cur_realm}'，正文疑似写成更低的'{lower}'（{win[:30]}）")
                        break

    # 7. Temporal 穿帮·过期计时器：正文把一个早已到期的悬置事件当作"还没发生/还来得及"
    state = load_state()
    tl = state.get("timeline") or {}
    cur_day = tl.get("absolute_day", 1)
    for timer in tl.get("pending_timers") or []:
        if not isinstance(timer, dict):
            continue
        due = timer.get("due_day")
        ev = timer.get("event") or ""
        if due is not None and isinstance(due, (int, float)) and due < cur_day - 1 and ev:
            # 这个计时事件已过期但仍悬置——抽取事件关键词，看正文是否还把它当"未来还会发生"
            key = re.findall(r"[一-鿿]{2,5}", ev)
            future_words = ["还没", "尚未", "来得及", "还有时间", "之前要", "得赶在"]
            for k in key[:3]:
                if k in text:
                    seg_pos = text.find(k)
                    win = text[max(0, seg_pos - 25):seg_pos + 25]
                    if any(fw in win for fw in future_words):
                        warnings.append(f"事实核查·时间穿帮：计时事件'{ev}'已于第{due}日到期(当前第{cur_day}日)，正文疑似仍当作未来未发生")
                        break

    return warnings


def hard_gate(text: str) -> Dict[str, Any]:
    issues = []
    warnings = []
    forbidden = ["李平安", "大隋", "安北四镇", "怀麓书院", "蜀山", "二泉映月", "老牛", "猫猫仙子"]
    pseudo_examples = [
        "走。",
        "这事不对。",
        "先活过今晚。",
        "价钱另算。",
        "我没有偷吃。",
        "这是先尝尝。",
        "大人都是这么走的。",
        "姓名。",
        "你昨夜在哪？",
        "这话，留到堂上再说。",
    ]
    empty_hook_phrases = [
        "更大的危机",
        "真正的麻烦",
        "一切才刚刚开始",
        "风暴即将来临",
        "命运的齿轮",
        "没有人知道",
        "他还不知道",
    ]
    filler_phrases = [
        "他想起了很多",
        "一时之间",
        "复杂情绪",
        "无法言喻",
        "这一切都意味着",
        "仿佛有什么东西",
        "似乎有什么东西",
    ]
    explain_dialogue_patterns = [
        r"你也知道",
        r"正如你所知",
        r"我再说一遍",
        r"这意味着",
        r"也就是说",
        r"换句话说",
        r"原因很简单",
    ]
    for word in forbidden:
        if word in text:
            issues.append(f"疑似源文专名污染: {word}")
    if re.search(r"LF-\d{3}", text):
        issues.append("正文泄露长线伏笔内部编号 LF-XXX。")
    for group in [["沈安", "沈归舟"], ["黑子", "阿墨"], ["方绾", "方青瓷"]]:
        found = [name for name in group if name in text]
        if len(found) > 1:
            issues.append(f"角色名不一致：同时出现{'/'.join(found)}。")
    for example in pseudo_examples:
        if example in text:
            bare = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", example)
            if len(bare) <= 2:
                warnings.append(f"短伪例命中，需人工/评审确认是否只是自然短句: {example}")
            else:
                issues.append(f"疑似照抄角色伪例: {example}")
    paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
    long_paragraphs = [p for p in paragraphs if len(p) > 60]
    if len(long_paragraphs) > max(3, len(paragraphs) * 0.15):
        issues.append("长段落偏多，可能不符合短段落风格。")
    sentences = [s.strip() for s in re.split(r"[。！？!?\n]+", text) if s.strip()]
    long_sentences = [s for s in sentences if len(s) > 35]
    if len(long_sentences) > max(5, len(sentences) * 0.2):
        issues.append("长句偏多，建议压短。")
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_count > 4200:
        issues.append("正文偏长，可能为了字数填充。")
    for phrase in filler_phrases:
        if text.count(phrase) >= 1:
            issues.append(f"疑似注水/AI泛化表达: {phrase}")
    dialogue_lines = [line for line in paragraphs if "\"" in line or "“" in line or "”" in line]
    explain_hits = []
    for line in dialogue_lines:
        for pattern in explain_dialogue_patterns:
            if re.search(pattern, line):
                explain_hits.append(line[:80])
                break
    if explain_hits:
        issues.append(f"疑似解释型对话 {len(explain_hits)} 处。")
    last_part = text[-400:]
    if any(phrase in last_part for phrase in empty_hook_phrases):
        issues.append("章末疑似空钩子：抽象危机词出现在最后400字。")
    # 章末钩子：源文统计悬念词收尾0%，靠短句留白。最后200字若靠"突然/竟然"式词收尾，软提醒
    cliche_hook_words = ["突然", "忽然", "竟然", "没想到", "万万没想到", "下一刻", "就在这时", "殊不知"]
    hook_zone = text[-200:]
    hook_hits = [w for w in cliche_hook_words if w in hook_zone]
    if hook_hits:
        warnings.append(f"章末钩子疑似用廉价悬念词收尾（{'/'.join(hook_hits)}）；源文风格靠短句和留白，建议改。")
    # 视觉穿帮：只卡两种真突兀——白天强光场景的精细视觉、装瞎场景却写主角看清
    vision_issues = check_vision_consistency(text)
    issues.extend(vision_issues)
    short_sentences = [s for s in sentences if len(s) <= 10]
    if sentences and len(short_sentences) / len(sentences) < 0.25:
        issues.append("超短句比例偏低，文字可能被修得太平滑。")
    sentence_lengths = [len(s) for s in sentences]
    if len(sentence_lengths) >= 20:
        avg = sum(sentence_lengths) / len(sentence_lengths)
        variance = sum((length - avg) ** 2 for length in sentence_lengths) / len(sentence_lengths)
        if variance < 35:
            issues.append("句长方差偏低，疑似过度工整。")
    return {"passed": not issues, "issues": issues, "warnings": warnings}


def style_gate(text: str) -> Dict[str, Any]:
    issues = []
    paragraphs = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    sentences = [s.strip() for s in re.split(r"[。！？!?\n]+", text) if s.strip()]
    if not paragraphs or not sentences:
        return {"passed": False, "issues": ["正文为空或无法分句。"], "metrics": {}}
    para_lengths = [len(p) for p in paragraphs]
    sentence_lengths = [len(s) for s in sentences]
    metrics = {
        "paragraph_count": len(paragraphs),
        "avg_paragraph_length": round(sum(para_lengths) / len(para_lengths), 1),
        "long_paragraph_ratio": round(sum(1 for item in para_lengths if item > 60) / len(para_lengths), 3),
        "sentence_count": len(sentences),
        "avg_sentence_length": round(sum(sentence_lengths) / len(sentence_lengths), 1),
        "long_sentence_ratio": round(sum(1 for item in sentence_lengths if item > 35) / len(sentence_lengths), 3),
        "short_sentence_ratio": round(sum(1 for item in sentence_lengths if item <= 10) / len(sentence_lengths), 3),
        "hedge_count": sum(text.count(word) for word in ["仿佛", "似乎", "好像"]),
        "emotion_summary_count": sum(text.count(word) for word in ["复杂情绪", "无法言喻", "心中一震", "心里五味杂陈"]),
        "said_count": sum(text.count(word) for word in ["说道", "说着", "开口道"]),
        "repetitive_action_count": max(
            len(re.findall(r"竹杖.{0,4}(?:点|敲|划|顿)", text)),
            len(re.findall(r"一下[。\n].*?两下", text, re.DOTALL)),
        ),
        "ear_flat_count": len(re.findall(r"耳朵.{0,3}(?:压平|压着|朝.{1,4}压)", text)),
        "nose_action_count": len(re.findall(r"鼻子.{0,3}(?:拱|蹭|抽)", text)),
        "silence_count": len(re.findall(r"没.{0,2}(?:说话|动|接话|应)", text)),
        "mc_subject_start_ratio": round(
            sum(1 for s in sentences if re.match(r"^沈安", s)) / max(len(sentences), 1), 3
        ),
        "breath_count": len(re.findall(r"\d+息", text)),
    }
    if metrics["repetitive_action_count"] > 3:
        issues.append(f"签名动作重复过多（竹杖点地等出现{metrics['repetitive_action_count']}次）,换其他感官细节。")
    if metrics["ear_flat_count"] > 3:
        issues.append(f"黑子耳朵压平/压着出现{metrics['ear_flat_count']}次,一章最多2次。")
    if metrics["nose_action_count"] > 3:
        issues.append(f"黑子鼻子拱/蹭/抽出现{metrics['nose_action_count']}次,一章最多2次。")
    if metrics["silence_count"] > 5:
        issues.append(f"「没说话/没动/没接话」出现{metrics['silence_count']}次,沉默表达一次够了。")
    if metrics["mc_subject_start_ratio"] > 0.25:
        issues.append(f"「沈安」开头的句子占{metrics['mc_subject_start_ratio']*100:.0f}%,主语开头太单一,用动作/环境/对话开头替代。")
    if metrics["breath_count"] > 4:
        issues.append(f"「X息」计时出现{metrics['breath_count']}次,换其他时间表达(一会儿/片刻/半盏茶)。")
    if metrics["avg_paragraph_length"] > 35:
        issues.append("平均段落偏长。")
    if metrics["long_paragraph_ratio"] > 0.12:
        issues.append("长段落比例偏高。")
    if metrics["long_sentence_ratio"] > 0.18:
        issues.append("长句比例偏高。")
    if metrics["short_sentence_ratio"] < 0.25:
        issues.append("短句比例偏低。")
    if metrics["hedge_count"] > 4:
        issues.append("仿佛/似乎/好像频率偏高。")
    if metrics["emotion_summary_count"] > 0:
        issues.append("出现情绪总结词。")
    if metrics["said_count"] > max(4, len(sentences) * 0.08):
        issues.append("说道类标识密度偏高。")
    return {"passed": not issues, "issues": issues, "metrics": metrics}


def continuity_check(text: str, chapter: int) -> Dict[str, Any]:
    issues = []
    state = load_state()
    threads = load_active_threads()
    known_characters = set((state.get("characters") or {}).keys())
    known_characters.update(project_character_names())
    character_mentions = extract_character_mentions(text)
    ignored_roles = {"中年人", "衙役", "孩子", "小孩"}
    unknown = sorted(name for name in character_mentions if known_characters and name not in known_characters and name not in ignored_roles)
    if unknown:
        issues.append(f"出现未登记角色：{', '.join(unknown)}")
    for group in [["沈安", "沈归舟"], ["黑子", "阿墨"], ["方绾", "方青瓷"]]:
        found = [name for name in group if name in character_mentions]
        if len(found) > 1:
            issues.append(f"角色名混用：{'/'.join(found)}。")
    ids = re.findall(r"F-\d{3}", text)
    known_ids = set((threads.get("foreshadowing") or {}).keys())
    missing_ids = sorted(set(fid for fid in ids if known_ids and fid not in known_ids))
    if missing_ids:
        issues.append(f"引用了不存在的伏笔 ID：{', '.join(missing_ids)}")
    if len(ids) != len(set(ids)) and "新增伏笔" in text:
        issues.append("正文/报告中疑似重复伏笔 ID。")
    if chapter < int(state.get("latest_chapter") or 0):
        issues.append("章节号小于结构化状态最新章节，可能时间倒退。")
    if "已死" in text and "又" in text and "出现" in text:
        issues.append("疑似已死亡角色再次出现。")
    return {"passed": not issues, "issues": issues}


def project_character_names() -> set:
    names = {
        "沈安",
        "沈归舟",
        "黑子",
        "阿墨",
        "张寡妇",
        "神秘小孩",
        "方绾",
        "方青瓷",
        "裴照",
        "小满",
        "中年人",
        "衙役",
    }
    try:
        index = load_index()
        for key, value in index.items():
            if isinstance(value, dict) and value.get("category") == "角色" and key != "通用规则":
                names.add(str(key))
    except Exception:
        pass
    role_text = read_text(BASE_DIR / "03-角色声音表.md")
    for match in re.findall(r"^##\s+(.+?)\s*$", role_text, re.MULTILINE):
        name = re.sub(r"（.*?）|\(.*?\)", "", match).strip()
        if name and name != "通用规则":
            names.add(name)
    return names


def extract_character_mentions(text: str) -> set:
    names = sorted(project_character_names(), key=len, reverse=True)
    return {name for name in names if name and name in text}


def combine_checks(checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []
    metrics: Dict[str, Any] = {}
    for name, result in checks.items():
        for issue in result.get("issues") or []:
            issues.append(f"{name}: {issue}")
        for warning in result.get("warnings") or []:
            warnings.append(f"{name}: {warning}")
        if result.get("metrics"):
            metrics[name] = result["metrics"]
    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "metrics": metrics,
        "checks": checks,
    }


def make_review_input(
    text: str,
    chapter: int,
    run_cfg: Dict[str, Any],
    timeout: int,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
    sections = [
        make_section("故事总监批注", story_director_context(chapter), "critical", False),
        make_section("风格指南", read_text(BASE_DIR / "01-风格指南.md"), "critical", False),
        make_section("打分表", read_text(BASE_DIR / "06-验证打分表.md"), "critical", False),
        make_section("AI腔黑名单", read_text(BASE_DIR / "12-AI腔黑名单.md"), "critical", False),
        make_section(
            "脚本硬检查结果",
            json.dumps(diagnostics or {}, ensure_ascii=False, indent=2),
            "high",
            False,
        ),
        make_section("待评审正文", text, "high", True),
    ]
    return compress_sections_if_needed("reviewer", chapter, sections, run_cfg, timeout)


def parse_score_needs_revision(review: str) -> bool:
    return any(flag in review for flag in [
        "必须修改",
        "不合格",
        "建议重写",
        "低于3分",
        "读者体验低于4分",
        "明显注水",
        "空钩子",
        "伪例照抄",
        "解释型对话",
        "过度工整",
    ])


def needs_revision(gate: Dict[str, Any], review: str) -> bool:
    return (not gate.get("passed")) or parse_score_needs_revision(review)


def resolve_beat_path(chapter: int, run_cfg: Dict[str, Any]) -> Path:
    beat_template = run_cfg.get("beat_template") or str(BASE_DIR / "beats" / "chapter_{chapter}.json")
    return Path(str(beat_template).format(chapter=chapter))


def previous_final_excerpt(chapter: int, max_chars: int = 3500) -> str:
    if chapter <= 1:
        return ""
    path = manuscript_path(chapter - 1)
    if not path.exists():
        path = role_artifact("writer", chapter - 1, "final.md")
    if not path.exists():
        path = OUTPUT_DIR / f"chapter_{chapter - 1}_final.md"
    text = read_text(path)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


# ========================= 故事总监 / 类型纠偏 =========================
# 只管方向,不写正文:检测短线是否偏离卷纲主类型,给 arc_planner/beat_planner 硬约束。

def recent_text_blob(chapter: int, lookback: int = 3, max_chars_per_chapter: int = 2200) -> str:
    parts: List[str] = []
    for ch in range(max(1, chapter - lookback), chapter):
        path = manuscript_path(ch)
        if path.exists():
            text = read_text(path)
            parts.append(f"第{ch}章摘录:\n{text[-max_chars_per_chapter:]}")
    return "\n\n".join(parts)


def extract_volume_stage_for_chapter(volume_text: str, chapter: int) -> str:
    """从卷纲阶段表里取当前章节所在行,用于判断是否长时间偏离阶段目标。"""
    for line in volume_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not re.search(r"\d", cells[0]):
            continue
        numbers = [int(num) for num in re.findall(r"\d+", cells[0])]
        if not numbers:
            continue
        start, end = (numbers[0], numbers[-1])
        if start <= chapter <= end:
            return " | ".join(cells)
    return ""


def default_story_director_state(chapter: int) -> Dict[str, Any]:
    return {
        "chapter": chapter,
        "status": "正常",
        "severity": 0,
        "expires_after_chapter": chapter + 3,
        "reason": "尚未触发故事总监审核。由 arc_planner/beat_planner 按卷纲正常推进。",
        "correction_action": "continue",
        "arc_instruction": "按卷纲、活跃弧线、当前状态自然推进。",
        "priority": [],
        "tidy_threads": [],
        "background_threads": [],
        "avoid_new_debt": [],
        "watch_repetition": [],
        "beat_priority": "按卷纲推进",
        "restraint_note": "保持自然阅读感。没有充分证据时让故事按卷纲继续流动。",
        "generated_by": "script",
    }


def render_story_director_markdown(data: Dict[str, Any]) -> str:
    lines = [
        "# 故事总监批注",
        "",
        f"- 章节: 第{data.get('chapter', '?')}章",
        f"- 状态: {data.get('status', '正常')}",
        f"- 严重度: {data.get('severity', 0)}",
        f"- 动作: {data.get('correction_action', 'continue')}",
        f"- 原因: {data.get('reason', '')}",
        "",
        "## 弧线指令",
        str(data.get("arc_instruction") or "继续遵守卷纲。"),
        "",
        "## 优先方向",
    ]
    priority = data.get("priority") or []
    for item in priority:
        lines.append(f"- {item}")
    if not priority:
        lines.append("- 无")
    tidy_threads = data.get("tidy_threads") or []
    lines.extend(["", "## 可整理债务"])
    for item in tidy_threads:
        lines.append(f"- {item}")
    if not tidy_threads:
        lines.append("- 无")
    background_threads = data.get("background_threads") or []
    lines.extend(["", "## 后台线索"])
    for item in background_threads:
        lines.append(f"- {item}")
    if not background_threads:
        lines.append("- 无")
    avoid_hooks = data.get("avoid_new_debt") or []
    lines.extend(["", "## 短期降噪"])
    for item in avoid_hooks:
        lines.append(f"- {item}")
    if not avoid_hooks:
        lines.append("- 无")
    watch_repetition = data.get("watch_repetition") or []
    lines.extend(["", "## 已发现的重复模式（后续必须避开）"])
    for item in watch_repetition:
        lines.append(f"- {item}")
    if not watch_repetition:
        lines.append("- 无")
    lines.extend(["", f"## Beat 优先级\n{data.get('beat_priority', '按卷纲推进')}"])
    lines.extend(["", f"## 克制备注\n{data.get('restraint_note') or '保持自然阅读感。'}"])
    if data.get("expires_after_chapter"):
        lines.extend(["", f"## 有效期\n本批注到第{data.get('expires_after_chapter')}章后自动重新评估。"])
    return "\n".join(lines).strip() + "\n"


def load_story_director() -> Dict[str, Any]:
    return load_json(STORY_DIRECTOR_FILE, {})


def save_story_director(data: Dict[str, Any]) -> None:
    dump_json(STORY_DIRECTOR_FILE, data)
    write_text(STORY_DIRECTOR_MD_FILE, render_story_director_markdown(data))


def story_director_prompt() -> str:
    return read_text(PROMPTS_DIR / "story_director.md") or (
        "你是故事总监。只输出 JSON。你的职责是防止小说偏离卷纲主类型。"
        "不要写正文,不要扩写剧情,只给未来3章的纠偏指令。"
    )


def threads_digest_for_director(chapter: int) -> str:
    """给 story_director 看的线索/揭示台账摘要（不进 writer，避免 token 膨胀）。
    专供"有无线索休眠过久/开出去的线有无收束计划/世界观揭示是否超配额"维度判断。"""
    ledger = load_ledger()
    lines: List[str] = []
    threads = [t for t in (ledger.get("threads") or []) if isinstance(t, dict)]
    if threads:
        active = [t for t in threads if t.get("status") == "活跃"]
        dormant = [t for t in threads if t.get("status") == "休眠"]
        lines.append(f"【线索台账】活跃{len(active)}条 / 休眠{len(dormant)}条")
        for t in sorted(active, key=lambda x: x.get("last_advanced", 0))[:12]:
            gap = chapter - int(t.get("last_advanced") or chapter)
            stale = f"⚠已{gap}章没推进" if gap >= 6 else ""
            plan = f"，计划{t['plan_resolve_by']}收" if t.get("plan_resolve_by") else "，⚠无收束计划"
            lines.append(f"- {t.get('id','')} {t.get('desc','')}（{t.get('owner','?')}{plan}）{stale}")
        for t in dormant[:5]:
            lines.append(f"- [休眠] {t.get('id','')} {t.get('desc','')}")
    reveals = [r for r in (ledger.get("reveal_ledger") or []) if isinstance(r, dict)]
    if reveals:
        lines.append("\n【揭示台账】（世界观大设定揭到第几层 / 下一层计划）")
        for r in reveals[:10]:
            lines.append(f"- {r.get('topic','')}：已揭L{r.get('revealed_level',0)}，下一层计划{r.get('plan_next_level_in','') or '未定'}")
    return "\n".join(lines).strip()


def build_story_director_input(chapter: int, detected: Dict[str, Any], run_cfg: Dict[str, Any], timeout: int) -> str:
    previous = load_story_director()
    prev_note = ""
    if previous and previous.get("generated_by") == "model":
        prev_note = (
            f"上次审核(第{previous.get('chapter','?')}章)结论:{previous.get('status','正常')}, "
            f"原因:{previous.get('reason','')}; "
            f"曾点名的重复模式:{previous.get('watch_repetition') or '无'}。"
            "如果上次的问题已经改善,就别再揪着不放;如果依然存在,可以升级严重度。"
        )
    sections = [
        make_section("当前章节", f"第{chapter}章", "critical", False),
        make_section("任务", "请自由审核当前故事方向。不要依赖关键词打分,按卷纲兑现度、核心叙事模式(治心病)、推进vs打转、重复模式、节奏冷热五个维度判断。默认放行,只在反复出现明确问题时纠偏。", "critical", False),
        make_section("故事核(注意核心叙事模式:治心病)", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("全书骨架", read_text(MASTER_OUTLINE_FILE), "critical", True),
        make_section("卷纲", read_text(VOLUME_PLAN_FILE), "critical", False),
        make_section("当前活跃弧线", json.dumps(load_active_arcs(), ensure_ascii=False, indent=2), "high", True),
        make_section("期待账本", read_text(BASE_DIR / "08-期待账本.md"), "high", True),
        make_section("结构化当前状态", structured_state_text(), "high", True),
        make_section("线索与揭示台账", threads_digest_for_director(chapter) or "（暂无线索台账记录）", "high", True),
        make_section("最近章节正文摘录", recent_text_blob(chapter, lookback=3), "normal", True),
        make_section("最近 beat 摘要", recent_beats_summary(chapter, lookback=5), "normal", True),
    ]
    if prev_note:
        sections.insert(2, make_section("上次审核结论", prev_note, "high", False))
    return compress_sections_if_needed("story_director", chapter, sections, run_cfg, timeout)


def run_story_director(chapter: int, run_cfg: Dict[str, Any], timeout: int, force: bool = False) -> Dict[str, Any]:
    cfg = run_cfg.get("story_director") or {}
    if cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
        data = default_story_director_state(chapter)
        save_story_director(data)
        return data
    previous = load_story_director()
    if previous and int(previous.get("expires_after_chapter") or 0) < chapter:
        previous = {}
    interval = int((cfg.get("interval_chapters") if isinstance(cfg, dict) else 5) or 5)
    last_chapter = int(previous.get("chapter") or 0) if previous else 0
    should_call_model = (
        force
        or not previous
        or chapter - last_chapter >= interval
        or needs_arc_planning(chapter)
    )
    if not should_call_model:
        data = dict(previous)
        data["chapter"] = chapter
        save_story_director(data)
        return data
    if run_cfg.get("dry_run"):
        data = default_story_director_state(chapter)
        save_story_director(data)
        return data
    cli_print(f"[story_director] 第{chapter}章:回看最近{interval}章方向,审核中…")
    try:
        director_input = build_story_director_input(chapter, {}, run_cfg, timeout)
        raw = call_role(
            "story_director",
            story_director_prompt(),
            director_input,
            RUNTIME_DIR / "story_director_raw.md",
            timeout,
            2000,
            RUNTIME_DIR / "story_director_input.md",
        )
        data = extract_json_object(raw)
        if not isinstance(data, dict):
            data = default_story_director_state(chapter)
        data.setdefault("chapter", chapter)
        data.setdefault("generated_by", "model")
        data.setdefault("severity", 0)
        data.setdefault("status", "正常")
        data.setdefault("reason", "")
        data.setdefault("expires_after_chapter", chapter + 3)
        data.setdefault("correction_action", "continue")
        data.setdefault("priority", [])
        data.setdefault("tidy_threads", [])
        data.setdefault("background_threads", [])
        data.setdefault("avoid_new_debt", [])
        data.setdefault("watch_repetition", [])
        data.setdefault("beat_priority", "按卷纲推进")
        data.setdefault("restraint_note", "保持自然阅读感。")
        # status 与 severity 一致性校验:以 severity 为准反推 status,防止模型给出矛盾值
        sev = int(data.get("severity") or 0)
        sev = max(0, min(3, sev))
        data["severity"] = sev
        data["status"] = {0: "正常", 1: "轻微偏航", 2: "偏航", 3: "严重偏航"}[sev]
        # severity=0 时纠偏动作强制为 continue,避免模型在"正常"时还给纠偏
        if sev == 0:
            data["correction_action"] = "continue"
        # 终端可视化:把判断结论简要显示出来
        if sev == 0:
            cli_print(f"[story_director] 第{chapter}章:方向正常,继续推进。")
        else:
            cli_print(f"[story_director] 第{chapter}章:{data['status']}(严重度{sev})→ {data.get('correction_action')}")
            if data.get("reason"):
                cli_print(f"  原因:{str(data['reason'])[:80]}")
            for rep in (data.get("watch_repetition") or [])[:3]:
                cli_print(f"  重复模式:{str(rep)[:70]}")
            if data.get("arc_instruction"):
                cli_print(f"  方向批注:{str(data['arc_instruction'])[:80]}")
    except Exception as exc:  # noqa: BLE001
        cli_print(f"[story_director] 模型审核失败,沿用默认方向:{exc}")
        data = default_story_director_state(chapter)
    save_story_director(data)
    return data


def story_director_context(chapter: int) -> str:
    data = load_story_director()
    if not data or int(data.get("expires_after_chapter") or 0) < chapter:
        data = default_story_director_state(chapter)
    return render_story_director_markdown(data)


def emotional_anchors_for_planner(chapter: int, max_items: int = 12) -> str:
    """给 beat_planner 看的可回响情感锚点列表。让规划师在合适时机安排回响。"""
    ledger = load_ledger()
    anchors = [a for a in (ledger.get("emotional_anchors") or []) if isinstance(a, dict)]
    if not anchors:
        return ""
    # 活跃的、且不是本章刚埋的(至少隔3章才适合回响)
    candidates = [
        a for a in anchors
        if a.get("echo_status") == "活跃" and (chapter - int(a.get("chapter") or 0)) >= 3
    ]
    # 意难平优先展示
    candidates.sort(key=lambda a: (a.get("type") != "意难平", -(int(a.get("chapter") or 0))))
    if not candidates:
        return ""
    lines = [
        "以下是前文埋下的情感锚点。如果本章出现合适的自然时机(故地重游/相似情境/时间跳跃/物件重现),"
        "可以安排一次回响——但必须自然,不能硬塞。没有合适时机就不回响。回响时在 beat 写 \"回响[EA-XXX]\"。"
    ]
    for a in candidates[:max_items]:
        echoed = f" [已回响{a.get('echo_count')}次]" if a.get("echo_count") else ""
        obj = f" 可用物件:{a.get('object')}" if a.get("object") else ""
        lines.append(f"- {a.get('id')}（{a.get('type')},第{a.get('chapter')}章）：{a.get('content','')}{obj}{echoed}")
    return "\n".join(lines)


# ========================= 全书骨架 & 卷纲规划师 =========================
# 全书骨架:开书时一次性生成,是所有规划的北极星。
# 卷纲规划师:每卷自动触发,从骨架里拆出当前卷的详细规划。

def generate_master_outline(run_cfg: Dict[str, Any], dry_run: bool) -> None:
    """一次性生成全书骨架。开书时跑一次,产出 全书骨架.md。"""
    if MASTER_OUTLINE_FILE.exists() and len(read_text(MASTER_OUTLINE_FILE).strip()) > 100:
        cli_print("[master_outline] 全书骨架已存在,跳过。如需重新生成,请先删除 全书骨架.md。")
        return
    timeout = int(run_cfg.get("request_timeout_seconds") or 240)
    prompt = read_text(PROMPTS_DIR / "master_outline.md")
    sections = [
        make_section("故事核", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("世界观设定圣经", read_text(BASE_DIR / "02-世界观设定圣经.md"), "critical", False),
        make_section("修炼境界体系", read_text(BASE_DIR / "02-修炼境界.md"), "critical", False),
        make_section("长线伏笔资产库", read_text(LONG_FORESHADOWING_FILE), "high", True),
    ]
    input_text = render_sections(sections)
    if dry_run:
        write_text(RUNTIME_DIR / "master_outline_dryrun.md", f"<<SYSTEM>>\n{prompt}\n\n<<INPUT>>\n{input_text}")
        cli_print("[master_outline] dry-run: prompt 已保存,未调用 API。")
        return
    cli_print("[master_outline] 生成全书骨架(一次性)…")
    result = call_role("master_outline", prompt, input_text, RUNTIME_DIR / "master_outline_raw.md", timeout, 7000)
    write_text(MASTER_OUTLINE_FILE, result)
    cli_print(f"[master_outline] 全书骨架已生成 → {MASTER_OUTLINE_FILE}")


def current_volume_info() -> Dict[str, Any]:
    """从卷纲里解析当前卷的信息:卷号、章节范围。"""
    text = read_text(VOLUME_PLAN_FILE)
    if not text.strip():
        return {}
    # 尝试从卷纲里提取章节范围
    m = re.search(r"章节范围[：:]\s*第(\d+)章\s*[-–—]\s*第(\d+)章", text)
    if m:
        return {"start": int(m.group(1)), "end": int(m.group(2)), "text": text}
    # 兜底:从阶段规划表格里找最大章节号
    chapters = [int(x) for x in re.findall(r"第(\d+)章", text)]
    if chapters:
        return {"start": min(chapters), "end": max(chapters), "text": text}
    return {"text": text}


def needs_volume_planning(chapter: int) -> bool:
    """判断是否需要生成下一卷卷纲:
    - 没有卷纲(首次)
    - 当前章已接近或超过卷纲的结束章节"""
    if not MASTER_OUTLINE_FILE.exists():
        return False  # 没有全书骨架就没法生成卷纲
    vol = current_volume_info()
    if not vol or not vol.get("text", "").strip():
        return True  # 卷纲为空
    end = vol.get("end", 0)
    if end <= 0:
        return False  # 解析不出范围,不乱动
    # 当前章距离卷末 ≤ 5 章时触发
    return chapter >= end - 5


def volume_summary(chapter: int) -> str:
    """压缩'上一卷/已写内容'的摘要给卷纲规划师看。
    从台账日志里取最近的更新,不是原文。"""
    log = read_text(BASE_DIR / "07-动态状态台账.md")
    # 取最后 3000 字符(最近的章节更新)
    if len(log) > 3000:
        log = log[-3000:]
    return log


def run_volume_planner(chapter: int, run_cfg: Dict[str, Any], timeout: int) -> None:
    """调用卷纲规划师,生成下一卷的卷纲,直接覆盖 10-卷纲.md。"""
    outline = read_text(MASTER_OUTLINE_FILE)
    if not outline.strip():
        cli_print("[volume_planner] 全书骨架为空,无法生成卷纲。请先运行 --outline。")
        return
    prompt = read_text(PROMPTS_DIR / "volume_planner.md")
    # 喂给规划师的上下文:全书骨架 + 角色关系网 + 伏笔状态 + 上卷回顾
    sections = [
        make_section("全书骨架(北极星,不可违背)", outline, "critical", False),
        make_section("当前章节号", f"第{chapter}章。请为接下来的卷生成卷纲。", "critical", False),
        make_section("正典账本(角色关系网/资源/约束/实体)", read_text(LEDGER_MD_FILE, "暂无。"), "high", False),
        make_section("结构化当前状态", structured_state_text(), "high", True),
        make_section("期待账本(未回收伏笔)", read_text(BASE_DIR / "08-期待账本.md"), "high", True),
        make_section("长线伏笔资产库", read_text(LONG_FORESHADOWING_FILE), "high", True),
        make_section("上卷/已写内容回顾", volume_summary(chapter), "normal", True),
    ]
    input_text = render_sections(sections)
    if run_cfg.get("dry_run"):
        write_text(RUNTIME_DIR / "volume_planner_dryrun.md", f"<<SYSTEM>>\n{prompt}\n\n<<INPUT>>\n{input_text}")
        cli_print("[volume_planner] dry-run: prompt 已保存,未调用 API。")
        return
    cli_print(f"[volume_planner] 第{chapter}章:卷纲即将用完,自动生成下一卷卷纲…")
    result = call_role("volume_planner", prompt, input_text, RUNTIME_DIR / "volume_planner_output.md", timeout, 5000)
    # 备份旧卷纲
    old = read_text(VOLUME_PLAN_FILE)
    if old.strip():
        backup = VERSION_DIR / f"卷纲_截至第{chapter}章.md"
        write_text(backup, old)
        cli_print(f"[volume_planner] 旧卷纲已备份 → {backup}")
    write_text(VOLUME_PLAN_FILE, result)
    # 弧线也要清空,让 arc_planner 在新卷纲下重新规划
    save_active_arcs([])
    cli_print("[volume_planner] 新卷纲已生成,活跃弧线已清空(arc_planner 会重新规划)。")


# ========================= 弧线规划师(Arc Planner) =========================
# 管"3-10章的短线弧":副线起承转合、冲突酿到爆发、角色关系经几个节点建立。
# 不是每章都跑,只在没有活跃弧线或弧线即将收束时触发。

def load_active_arcs() -> List[Dict[str, Any]]:
    data = load_json(ACTIVE_ARCS_FILE, {})
    arcs = data.get("arcs") if isinstance(data, dict) else data
    return arcs if isinstance(arcs, list) else []


def save_active_arcs(arcs: List[Dict[str, Any]]) -> None:
    dump_json(ACTIVE_ARCS_FILE, {"arcs": arcs})


def needs_arc_planning(chapter: int) -> bool:
    """判断是否需要调用弧线规划师:
    - 没有活跃弧线(首次或全部收束)
    - 所有活跃弧线的最后一个节点 <= 当前章+1(即将用完)"""
    arcs = load_active_arcs()
    if not arcs:
        return True
    for arc in arcs:
        nodes = arc.get("nodes") or []
        if nodes:
            last_chapter = max(n.get("chapter", 0) for n in nodes)
            if last_chapter > chapter + 1:
                return False
    return True


def recent_beats_summary(chapter: int, lookback: int = 5) -> str:
    """最近几章的 beat 摘要,给 arc_planner 看"已经发生了什么"。"""
    lines = []
    for ch in range(max(1, chapter - lookback), chapter):
        beat_path = BASE_DIR / "beats" / f"chapter_{ch}.json"
        if beat_path.exists():
            beat = load_json(beat_path, {})
            title = beat.get("标题", "")
            conflict = beat.get("本章冲突", "")
            hook = beat.get("章末钩子", "")
            lines.append(f"第{ch}章「{title}」冲突:{conflict} | 钩子:{hook}")
    return "\n".join(lines) if lines else "无最近 beat 记录"


def previous_arcs_summary() -> str:
    """上一批弧线的收束摘要:怎么结的、留了什么尾巴。给新弧线承上启下用。"""
    arcs = load_active_arcs()
    if not arcs:
        return "无上一批弧线记录。"
    lines = ["上一批弧线收束情况(新弧线应承接这些尾巴):"]
    for arc in arcs:
        title = arc.get("title", "?")
        res = arc.get("resolution_condition", "未明确")
        nodes = arc.get("nodes") or []
        last_hint = nodes[-1].get("beat_hint", "") if nodes else ""
        lines.append(f"- {title}: 收束条件={res}; 最后节点={last_hint}")
    return "\n".join(lines)


def build_arc_input(chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    sections = [
        make_section("当前章节号", f"第{chapter}章,请从此章开始规划弧线节点。注意:弧线必须在卷纲当前阶段的范围内,不要跑到后面阶段去。", "critical", False),
        make_section("故事总监批注(方向参考，保持自然阅读感)", story_director_context(chapter), "critical", False),
        make_section("上一批弧线收束摘要(承上启下)", previous_arcs_summary(), "high", False),
        make_section("故事核", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("卷纲(你的弧线必须在卷纲的当前阶段内)", read_text(BASE_DIR / "卷纲" / "10-卷纲.md"), "high", True),
        make_section("结构化当前状态", structured_state_text(), "high", True),
        make_section("正典账本快照", read_text(LEDGER_MD_FILE, "暂无。"), "high", True),
        make_section("期待账本(未回收伏笔)", read_text(BASE_DIR / "08-期待账本.md"), "normal", True),
        make_section("最近章节 beat 回顾", recent_beats_summary(chapter), "normal", True),
    ]
    return compress_sections_if_needed("arc_planner", chapter, sections, run_cfg, timeout)


def run_arc_planner(chapter: int, run_cfg: Dict[str, Any], timeout: int) -> None:
    """调用弧线规划师,生成新的短线弧骨架。"""
    cli_print(f"[arc_planner] 第{chapter}章:需要新弧线,调用弧线规划师…")
    arc_prompt = read_text(PROMPTS_DIR / "arc_planner.md")
    arc_input = build_arc_input(chapter, run_cfg, timeout)
    if run_cfg.get("dry_run"):
        write_text(RUNTIME_DIR / "arc_planner_dryrun.md", f"<<SYSTEM>>\n{arc_prompt}\n\n<<INPUT>>\n{arc_input}")
        cli_print("[arc_planner] dry-run: prompt 已保存,未调用 API。")
        return
    result = call_role(
        "arc_planner",
        arc_prompt,
        arc_input,
        RUNTIME_DIR / "arc_planner_output.md",
        timeout,
        4000,
    )
    try:
        arcs = json.loads(result.strip() if result.strip().startswith("[") else
                          result[result.find("["):result.rfind("]") + 1])
    except (json.JSONDecodeError, ValueError) as exc:
        cli_print(f"[arc_planner] JSON 解析失败:{exc}。弧线未更新,beat_planner 将无弧线指引。")
        return
    if not isinstance(arcs, list):
        arcs = [arcs] if isinstance(arcs, dict) else []
    save_active_arcs(arcs)
    arc_names = [a.get("title", "?") for a in arcs]
    cli_print(f"[arc_planner] 生成 {len(arcs)} 条弧线:{', '.join(arc_names)}")


def active_arcs_for_beat(chapter: int) -> str:
    """格式化当前活跃弧线给 beat_planner 看:只展示与当前章相关的节点。"""
    arcs = load_active_arcs()
    if not arcs:
        return ""
    lines = ["以下是当前活跃的短线弧(3-10章跨度),你的 beat 应该推进其中某条弧的下一个节点:"]
    for arc in arcs:
        nodes = arc.get("nodes") or []
        relevant = [n for n in nodes if n.get("chapter", 0) >= chapter - 1]
        if not relevant:
            continue
        lines.append(f"\n### {arc.get('title', '?')}({arc.get('type', '?')}) [{arc.get('arc_id', '')}]")
        lines.append(f"目标:{arc.get('summary', '')}")
        lines.append(f"收束条件:{arc.get('resolution_condition', '未明确')}")
        lines.append("节点:")
        for n in relevant[:4]:
            marker = "→" if n.get("chapter") == chapter else " "
            lines.append(f"  {marker} 第{n.get('chapter', '?')}章 [{n.get('tension', '?')}] {n.get('beat_hint', '')}")
    return "\n".join(lines)


def build_beat_input(chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    sections = [
        make_section("目标章节", f"第{chapter}章", "critical", False),
        make_section("故事总监批注(方向参考，保持自然阅读感)", story_director_context(chapter), "critical", False),
        make_section("故事核", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("世界观设定圣经", read_text(BASE_DIR / "02-世界观设定圣经.md"), "critical", False),
        make_section("修炼境界安全参考", safe_cultivation_for_writer(), "high", True),
        make_section("卷纲", read_text(BASE_DIR / "卷纲" / "10-卷纲.md"), "high", True),
        make_section("长线伏笔资产库", long_foreshadowing_text(chapter, writer_safe=False), "critical", True),
        make_section("结构化当前状态", structured_state_text(), "high", True),
        make_section("最近台账日志摘录", recent_ledger_tail(), "low", True),
        make_section("正典账本快照", read_text(LEDGER_MD_FILE, "暂无正典账本。"), "high", True),
        make_section("最近一章正文片段", previous_final_excerpt(chapter) or "无", "normal", True),
    ]
    arc_text = active_arcs_for_beat(chapter)
    if arc_text:
        sections.insert(4, make_section("当前活跃弧线(短线剧情骨架)", arc_text, "high", False))
    # 节奏/情绪警告 + 威胁阶梯
    pacing_warn = pacing_variety_warnings(chapter)
    if pacing_warn:
        sections.append(make_section("节奏多样性警告", pacing_warn, "high", False))
    emotion_warn = emotional_distribution_warnings(chapter)
    if emotion_warn:
        sections.append(make_section("情绪分布警告", emotion_warn, "high", False))
    # 可回响的情感锚点(让规划师在合适时机安排回响)
    ea_text = emotional_anchors_for_planner(chapter)
    if ea_text:
        sections.append(make_section("可回响的情感锚点(草蛇灰线)", ea_text, "normal", True))
    threat_file = BASE_DIR / "config" / "threat_ladder.json"
    if threat_file.exists():
        threat_data = load_json(threat_file, {})
        ladder = threat_data.get("ladder") or []
        # Find current volume entry
        current_entry = next((e for e in ladder if chapter <= int(str(e.get("chapters", "0-0")).split("-")[-1])), None)
        if current_entry:
            rules = "\n".join(threat_data.get("escalation_rules", [])[:4])
            entry_str = f"主角境界：{current_entry.get('mc_realm','?')} | 敌人上限：{current_entry.get('enemy_ceiling','?')} | BOSS：{current_entry.get('boss','?')}"
            sections.append(make_section("威胁升级阶梯(本卷)", f"{entry_str}\n{rules}", "normal", True))
    return compress_sections_if_needed("beat_planner", chapter, sections, run_cfg, timeout)


def extract_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("beat_planner 没有返回 JSON 对象。")
    payload = stripped[start:end + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return json.loads(_sanitize_model_json(payload))


def normalize_beat(chapter: int, beat: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "章节编号": int(beat.get("章节编号") or chapter),
        "标题": str(beat.get("标题") or f"第{chapter}章"),
        "期待循环位置": str(beat.get("期待循环位置") or "酿"),
        "场景类型": str(beat.get("场景类型") or "日常对话"),
        "本章冲突": str(beat.get("本章冲突") or "推进主线冲突。"),
        "具体物件": beat.get("具体物件") or [],
        "具体动作": beat.get("具体动作") or [],
        "信息差": str(beat.get("信息差") or "未明确"),
        "转折": str(beat.get("转折") or "中段出现新的线索或代价。"),
        "本章爽点": str(beat.get("本章爽点") or "小幅兑现一个读者期待。"),
        "章末钩子": str(beat.get("章末钩子") or "留下下一章问题。"),
        "推进的线": str(beat.get("推进的线") or "主线"),
        "伏笔操作": str(beat.get("伏笔操作") or "无"),
        "出场角色": beat.get("出场角色") or ["沈安", "黑子"],
    }
    if not isinstance(normalized["出场角色"], list):
        normalized["出场角色"] = [str(normalized["出场角色"])]
    normalized["出场角色"] = [str(item) for item in normalized["出场角色"][:5]]
    for key in ["具体物件", "具体动作"]:
        if not isinstance(normalized[key], list):
            normalized[key] = [str(normalized[key])]
        normalized[key] = [str(item) for item in normalized[key][:6]]
    for key in [
        "主题折射",
        "内在转变",
        "困境/两难",
        "潜台词机会",
        "意外处理",
        "矛盾触发",
        "情绪裂缝",
        "情绪弧线",
    ]:
        if key in beat:
            normalized[key] = str(beat.get(key) or "无")
    return normalized


def beat_direction_check(beat: Dict[str, Any], chapter: int) -> Dict[str, Any]:
    """检查 beat 是否吸收了故事总监的纠偏指令。
    只在总监明确标记偏航(severity>=2)时才做硬检查,否则放行。"""
    director = load_story_director()
    sev = int(director.get("severity") or 0)
    issues: List[str] = []
    warnings: List[str] = []
    if sev >= 2:
        if not director.get("arc_instruction"):
            warnings.append("故事总监标记偏航但没有给出 arc_instruction。")
        # 总监点名的重复模式,beat 不能再撞上去
        beat_blob = json.dumps(beat, ensure_ascii=False)
        for rep in (director.get("watch_repetition") or []):
            # 取重复模式描述里的关键名词(去掉"连续N章""总是"等修饰),看 beat 是否还在用
            core = re.sub(r"连续\d+章|总是|又|反复|重复", "", str(rep)).strip()
            # 提取2-4字的中文词做粗匹配
            keywords = [w for w in re.findall(r"[一-鿿]{2,4}", core) if len(w) >= 2][:3]
            hit = sum(1 for kw in keywords if kw in beat_blob)
            if keywords and hit >= max(2, len(keywords)):
                issues.append(f"本章 beat 疑似重复了总监点名的模式:{rep}")
    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "metrics": {"director_severity": sev},
    }


def type_guard_check(text: str, chapter: int) -> Dict[str, Any]:
    director = load_story_director()
    warnings: List[str] = []
    if int(director.get("severity") or 0) >= 2:
        warnings.append("故事总监标记当前短线存在偏航风险；具体是否需要修改交给 Reviewer 按剧情功能判断。")
    return {
        "passed": True,
        "issues": [],
        "warnings": warnings,
        "metrics": {"director_severity": director.get("severity", 0)},
    }


def extract_markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _sanitize_model_json(payload: str) -> str:
    """修复 mimo 在生成 JSON 时的结构性毛病,不改语义:
    核心问题:mimo 在 JSON 字符串值内部放未转义的引号(中文对话里的引号直接用 ASCII 0x22),
    导致 JSON 解析器提前截断字符串。
    修法:识别"不该出现在字符串外"的引号(前后紧邻中文/标点),补反斜杠转义。"""
    s = payload.strip()
    # 第一步:修复字符串内部的未转义引号。
    # 正常 JSON 里,一个 " 如果是字符串边界,它前面/后面应该是:
    #   结构字符 : , { } [ ] 或空白
    # 如果一个 " 的前面是中文/中文标点,且后面也是中文/中文标点,那它是字符串内容里的引号,需要转义。
    # 模式:中文字符 + " + 中文字符 → 中文字符 + \" + 中文字符
    s = re.sub(
        r'([一-鿿　-〿＀-￯])"([一-鿿　-〿＀-￯])',
        r'\1\\"\2',
        s,
    )
    # 也处理:中文标点 + " + 中文(如 ，"小山)
    s = re.sub(
        r'([，。！？、；：])"([一-鿿])',
        r'\1\\"\2',
        s,
    )
    # 以及:中文 + " + 中文标点(如 有数"，)
    s = re.sub(
        r'([一-鿿])"([，。！？、；：　-〿])',
        r'\1\\"\2',
        s,
    )
    # 第二步:去掉对象/数组的尾逗号
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    return s


def _prune_empty(obj: Any) -> Any:
    """递归剔除全空的噪声:空串 key、值全为空的对象、纯空串数组项。
    mimo 爱把模板原样抄回来填一堆空串,这些既无意义又增加出错面。"""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if not str(k).strip():  # 空串 key 直接丢
                continue
            pv = _prune_empty(v)
            if pv in ("", [], {}, None):
                continue
            cleaned[k] = pv
        return cleaned
    if isinstance(obj, list):
        out = [_prune_empty(x) for x in obj]
        return [x for x in out if x not in ("", [], {}, None)]
    return obj


def _parse_structured_payload(payload: str) -> Dict[str, Any]:
    """解析 STRUCTURED_UPDATE 的 JSON:先直解,失败则净化再解,最后剔除空噪声。"""
    for candidate in (payload.strip(), _sanitize_model_json(payload)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return _prune_empty(data)
        except json.JSONDecodeError:
            continue
    return {}


def extract_structured_update(text: str) -> Dict[str, Any]:
    section = extract_markdown_section(text, "STRUCTURED_UPDATE")
    if not section:
        return {}
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", section)
    payload = fenced.group(1) if fenced else section
    data = _parse_structured_payload(payload)
    if not data:
        cli_print("STRUCTURED_UPDATE JSON 解析失败（净化后仍无法解析）。")
    return data


def merge_state_update(update: Dict[str, Any]) -> None:
    if not update:
        return
    state = load_state()
    threads = load_active_threads()
    # 注意：latest_chapter 不在这里设。它是"提交标记"，只在所有记忆写完后由
    # apply_archivist_update 最后一步推进，确保中断时对账能识别并重建本章。
    for key in ["story_time", "current_location", "mc_realm"]:
        if key in update:
            state[key] = update[key]
    for key in ["characters", "relationships", "knowledge"]:
        value = update.get(key)
        if isinstance(value, dict):
            target = state.setdefault(key, {})
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict) and isinstance(target.get(sub_key), dict):
                    target[sub_key].update(sub_value)
                else:
                    target[sub_key] = sub_value
    for key in ["recent_events", "used_devices"]:
        value = update.get(key)
        if isinstance(value, list):
            existing = state.setdefault(key, [])
            existing.extend(str(item) for item in value)
            state[key] = existing[-30:]
    foreshadowing = update.get("foreshadowing")
    if isinstance(foreshadowing, dict):
        table = threads.setdefault("foreshadowing", {})
        for item in foreshadowing.get("upsert") or []:
            if isinstance(item, dict) and item.get("id"):
                table[str(item["id"])] = item
        for item in foreshadowing.get("resolve") or []:
            if isinstance(item, dict) and item.get("id"):
                fid = str(item["id"])
                current = table.setdefault(fid, {"id": fid})
                current.update(item)
        if foreshadowing.get("next_id"):
            threads["next_id"] = foreshadowing["next_id"]
    open_questions = update.get("open_questions")
    if isinstance(open_questions, list):
        existing = threads.setdefault("open_questions", [])
        existing.extend(str(item) for item in open_questions)
        threads["open_questions"] = existing[-30:]
    dump_json(STATE_FILE, state)
    dump_json(ACTIVE_THREADS_FILE, threads)
    write_state_mirrors()


def merge_ledger_update(update: Dict[str, Any], chapter: int) -> None:
    """把 archivist 的 canon/ledger delta 并进 ledger.json。已存在实体只补充不覆盖。"""
    block = update.get("canon") or update.get("ledger")
    if not isinstance(block, dict):
        return
    ledger = load_ledger()

    # 实体：新建则全量建卡,已存在则只补充/更新变化的字段
    entities = ledger.setdefault("entities", {})
    for ent in block.get("new_entities") or []:
        if not isinstance(ent, dict):
            continue
        name = ent.get("name")
        if not name:
            continue
        if name in entities:
            cur = entities[name]
            cur["facts"] = list(dict.fromkeys((cur.get("facts") or []) + (ent.get("facts") or [])))
            if not cur.get("voice") and ent.get("voice"):
                cur["voice"] = ent["voice"]
            cur["last_seen_chapter"] = chapter
        else:
            entities[name] = {
                "type": ent.get("type") or "角色",
                "first_chapter": ent.get("first_chapter") or chapter,
                "last_seen_chapter": chapter,
                "summary": ent.get("summary") or "",
                "voice": ent.get("voice") or "",
                "realm": ent.get("realm") or "",
                "skills": ent.get("skills") or [],
                "weapons": ent.get("weapons") or [],
                "faction": ent.get("faction") or "",
                "injuries": ent.get("injuries") or "",
                "secrets": ent.get("secrets") or [],
                "enemies": ent.get("enemies") or [],
                "debts": ent.get("debts") or [],
                "current_goal": ent.get("current_goal") or "",
                "reputation": ent.get("reputation") or "",
                "facts": ent.get("facts") or [],
                "status": ent.get("status") or "活跃",
            }
            # 弧线内核 / 自欺：存在才建，缺省不占位（多数配角不填）
            if ent.get("arc_core") and isinstance(ent["arc_core"], dict):
                entities[name]["arc_core"] = {
                    "want": ent["arc_core"].get("want", ""),
                    "need": ent["arc_core"].get("need", ""),
                    "lie": ent["arc_core"].get("lie", ""),
                    "truth": ent["arc_core"].get("truth", ""),
                    "turning_points": ent["arc_core"].get("turning_points") or [],
                }
            if ent.get("self_deception") and isinstance(ent["self_deception"], dict):
                entities[name]["self_deception"] = {
                    "lie": ent["self_deception"].get("lie", ""),
                    "contradicted_by": ent["self_deception"].get("contradicted_by") or [],
                    "status": ent["self_deception"].get("status") or "活跃",
                }
    for upd in block.get("update_entities") or []:
        if not isinstance(upd, dict):
            continue
        name = upd.get("name")
        if not name or name not in entities:
            continue
        cur = entities[name]
        if upd.get("add_facts"):
            cur["facts"] = list(dict.fromkeys((cur.get("facts") or []) + list(upd["add_facts"])))
        if upd.get("status"):
            cur["status"] = upd["status"]
        if upd.get("voice"):
            cur["voice"] = upd["voice"]
        if upd.get("realm_change"):
            cur["realm"] = upd["realm_change"]
        if upd.get("skills_add"):
            existing = {s.get("name") for s in (cur.get("skills") or []) if isinstance(s, dict)}
            for sk in upd["skills_add"]:
                if isinstance(sk, dict) and sk.get("name"):
                    if sk["name"] in existing:
                        for s in cur.get("skills", []):
                            if isinstance(s, dict) and s.get("name") == sk["name"]:
                                s["level"] = sk.get("level") or s.get("level")
                    else:
                        cur.setdefault("skills", []).append(sk)
                        existing.add(sk["name"])
        if upd.get("weapons_change"):
            cur["weapons"] = upd["weapons_change"] if isinstance(upd["weapons_change"], list) else [upd["weapons_change"]]
        if upd.get("injuries_change"):
            cur["injuries"] = upd["injuries_change"]
        if upd.get("secrets_add"):
            cur.setdefault("secrets", []).extend(upd["secrets_add"])
        if upd.get("enemies_add"):
            cur.setdefault("enemies", []).extend(upd["enemies_add"])
        if upd.get("debts_add"):
            cur.setdefault("debts", []).extend(upd["debts_add"])
        if upd.get("debts_resolve"):
            resolved_ids = {d.get("id") for d in upd["debts_resolve"] if isinstance(d, dict)}
            for d in cur.get("debts", []):
                if isinstance(d, dict) and d.get("id") in resolved_ids:
                    d["status"] = "已还"
        if upd.get("goal_change"):
            cur["current_goal"] = upd["goal_change"]
        if upd.get("reputation_change"):
            rep = cur.get("reputation")
            if isinstance(rep, dict) and isinstance(upd["reputation_change"], dict):
                rep.update(upd["reputation_change"])
            else:
                cur["reputation"] = upd["reputation_change"]
        if upd.get("faction_change"):
            cur["faction"] = upd["faction_change"]
        # 弧线内核更新：只补变化字段；转折点追加（封顶6条）
        if upd.get("arc_core_update") and isinstance(upd["arc_core_update"], dict):
            ac = cur.setdefault("arc_core", {"want": "", "need": "", "lie": "", "truth": "", "turning_points": []})
            for k in ("want", "need", "lie", "truth"):
                if upd["arc_core_update"].get(k):
                    ac[k] = upd["arc_core_update"][k]
            tp = upd["arc_core_update"].get("turning_point_add")
            if tp:
                tps = ac.setdefault("turning_points", [])
                tps.append({"chapter": chapter, "shift": tp} if isinstance(tp, str) else tp)
                ac["turning_points"] = tps[-6:]
        # 自欺更新：lie 可更新；contradicted_by 追加本章行动反证（封顶6条）；status 推进
        if upd.get("self_deception_update") and isinstance(upd["self_deception_update"], dict):
            sd = cur.setdefault("self_deception", {"lie": "", "contradicted_by": [], "status": "活跃"})
            sdu = upd["self_deception_update"]
            if sdu.get("lie"):
                sd["lie"] = sdu["lie"]
            if sdu.get("contradicted_by_add"):
                cb = sd.setdefault("contradicted_by", [])
                add = sdu["contradicted_by_add"]
                add = [add] if isinstance(add, str) else add
                for a in add:
                    cb.append({"chapter": chapter, "action": a} if isinstance(a, str) else a)
                sd["contradicted_by"] = cb[-6:]
            if sdu.get("status"):
                sd["status"] = sdu["status"]
        cur["last_seen_chapter"] = chapter

    # 技能过时机制:低于当前境界两阶以上的技能自动标"过时",写手看不到。
    # 不封顶数量,靠境界差自然淘汰。
    REALM_ORDER = ["凡人", "叩门", "通脉", "凝元", "开窍", "化神", "归真", "明心", "通玄", "听道", "御道", "齐物", "忘我"]
    realm_idx = {r: i for i, r in enumerate(REALM_ORDER)}
    for e in entities.values():
        if not isinstance(e, dict):
            continue
        mc_realm = e.get("realm") or ""
        mc_rank = realm_idx.get(mc_realm, -1)
        if mc_rank < 0:
            continue
        for sk in (e.get("skills") or []):
            if not isinstance(sk, dict):
                continue
            sk_realm = sk.get("learned_at_realm") or ""
            sk_rank = realm_idx.get(sk_realm, -1)
            if sk_rank >= 0 and mc_rank - sk_rank >= 3:
                sk["status"] = "过时"
    # 仇敌:已了结的只保留最近3个作为历史,其余删除(防无限增长)
    for e in entities.values():
        if not isinstance(e, dict):
            continue
        enemies = e.get("enemies") or []
        resolved = [en for en in enemies if isinstance(en, dict) and en.get("status") == "已了结"]
        if len(resolved) > 3:
            active = [en for en in enemies if isinstance(en, dict) and en.get("status") != "已了结"]
            e["enemies"] = active + resolved[-3:]

    # 资源账：直接覆盖当前值（资源就是会变的数）
    resources = ledger.setdefault("resources", {})
    for key, value in (block.get("resources") or {}).items():
        resources[key] = value

    # 未结清账：新增 obligation / 结清已有
    obligations = ledger.setdefault("obligations", [])
    by_id = {o.get("id"): o for o in obligations if isinstance(o, dict) and o.get("id")}
    for ob in block.get("obligations_new") or []:
        if isinstance(ob, dict) and ob.get("id"):
            ob.setdefault("status", "悬空")
            ob.setdefault("since_chapter", chapter)
            if ob["id"] in by_id:
                by_id[ob["id"]].update(ob)
            else:
                obligations.append(ob)
                by_id[ob["id"]] = ob
    for done in block.get("obligations_resolve") or []:
        if isinstance(done, dict) and done.get("id") in by_id:
            by_id[done["id"]]["status"] = "已结"
            by_id[done["id"]]["resolved_chapter"] = chapter
            if done.get("resolution"):
                by_id[done["id"]]["resolution"] = done["resolution"]

    # 约束账：追加已成事实
    constraints = ledger.setdefault("constraints", [])
    known = {c.get("desc") for c in constraints if isinstance(c, dict)}
    for con in block.get("constraints_new") or []:
        if isinstance(con, dict) and con.get("desc") and con["desc"] not in known:
            con.setdefault("binding", "强")
            con.setdefault("since_chapter", chapter)
            constraints.append(con)

    # 关系账：往 history 追加一步
    relationships = ledger.setdefault("relationships", {})
    for rel in block.get("relationships") or []:
        if not isinstance(rel, dict) or not rel.get("pair"):
            continue
        node = relationships.setdefault(rel["pair"], {"current": "", "history": []})
        if rel.get("current"):
            node["current"] = rel["current"]
        if rel.get("event"):
            node["history"].append({"chapter": chapter, "event": rel["event"]})
            node["history"] = node["history"][-20:]

    # 势力账本：动态追踪势力状态
    factions_update = block.get("factions_update")
    if factions_update and isinstance(factions_update, dict):
        factions = ledger.setdefault("factions", {})
        for nf in factions_update.get("new_factions") or []:
            if isinstance(nf, dict) and nf.get("name"):
                name = nf["name"]
                factions[name] = {
                    "type": nf.get("type", "其他"),
                    "leader": nf.get("leader", ""),
                    "members": nf.get("members", []),
                    "power_level": nf.get("power_level", ""),
                    "territory": nf.get("territory", ""),
                    "stance_to_mc": nf.get("stance_to_mc", "未知"),
                    "relationships": nf.get("relationships", []),
                    "goal": nf.get("goal", ""),
                    "first_chapter": chapter,
                    "last_updated": chapter,
                    "status": "活跃",
                    "history": [],
                }
        for uf in factions_update.get("update_factions") or []:
            if not isinstance(uf, dict) or not uf.get("name"):
                continue
            name = uf["name"]
            if name not in factions:
                factions[name] = {"type": "其他", "members": [], "relationships": [], "history": [], "first_chapter": chapter, "status": "活跃"}
            f = factions[name]
            f["last_updated"] = chapter
            if uf.get("member_join"):
                members = f.setdefault("members", [])
                for m in uf["member_join"]:
                    if m not in members:
                        members.append(m)
            if uf.get("member_leave"):
                members = f.setdefault("members", [])
                for ml in uf["member_leave"]:
                    leave_name = ml.get("name") if isinstance(ml, dict) else ml
                    if leave_name in members:
                        members.remove(leave_name)
            if uf.get("leader_change"):
                f["leader"] = uf["leader_change"]
            if uf.get("stance_change"):
                f["stance_to_mc"] = uf["stance_change"]
            if uf.get("power_change"):
                f["power_level"] = uf["power_change"]
            if uf.get("status"):
                f["status"] = uf["status"]
            if uf.get("relationship_change"):
                rels = f.setdefault("relationships", [])
                for rc in uf["relationship_change"]:
                    if not isinstance(rc, dict) or not rc.get("target"):
                        continue
                    existing = next((r for r in rels if isinstance(r, dict) and r.get("target") == rc["target"]), None)
                    if existing:
                        existing["relation"] = rc.get("new", rc.get("relation", ""))
                    else:
                        rels.append({"target": rc["target"], "relation": rc.get("new", "")})
            if uf.get("event"):
                history = f.setdefault("history", [])
                history.append({"chapter": chapter, "event": uf["event"]})
                history[:] = history[-15:]

    # inventory_update: structured item tracking (replaces old freeform resources)
    inv_update = block.get("inventory_update")
    if inv_update and isinstance(inv_update, dict):
        inventory = ledger.setdefault("inventory", {"consumables": [], "key_items": [], "techniques": [], "currency": {}})
        for item in inv_update.get("add") or []:
            if isinstance(item, dict) and item.get("name"):
                category = item.pop("category", "key_items")
                target = inventory.setdefault(category, [])
                item.setdefault("last_chapter", chapter)
                existing = next((x for x in target if x.get("name") == item["name"]), None)
                if existing:
                    existing.update(item)
                else:
                    target.append(item)
        for item in inv_update.get("consume") or []:
            if isinstance(item, dict) and item.get("name"):
                for cat in ["consumables", "key_items"]:
                    for x in inventory.get(cat, []):
                        if x.get("name") == item["name"]:
                            qty = item.get("qty", 1)
                            x["qty"] = max(0, (x.get("qty") or 1) - qty)
                            x["last_chapter"] = chapter
        for item in inv_update.get("destroy") or []:
            name = item.get("name") if isinstance(item, dict) else item
            for cat in ["consumables", "key_items"]:
                for x in inventory.get(cat, []):
                    if x.get("name") == name:
                        x["status"] = "已销毁"
                        x["last_chapter"] = chapter
        if inv_update.get("currency_change") and isinstance(inv_update["currency_change"], dict):
            currency = inventory.setdefault("currency", {})
            for k, v in inv_update["currency_change"].items():
                if k == "notes":
                    currency["notes"] = v
                elif isinstance(v, (int, float)):
                    currency[k] = (currency.get(k) or 0) + v
        # Prune: remove consumables at qty=0 for >30 chapters
        for cat in ["consumables", "key_items"]:
            items = inventory.get(cat, [])
            inventory[cat] = [x for x in items if not (
                x.get("status") == "已销毁" and chapter - (x.get("last_chapter") or 0) > 10
            ) and not (
                cat == "consumables" and (x.get("qty") or 0) <= 0 and chapter - (x.get("last_chapter") or 0) > 30
            )]

    # liaoYuan_event: 愿录事件追踪
    ly_event = block.get("liaoYuan_event")
    if ly_event and isinstance(ly_event, dict) and ly_event.get("wish"):
        log = ledger.setdefault("liaoYuan_log", [])
        ly_event["chapter"] = chapter
        log.append(ly_event)

    # motifs_update: 意象追踪
    motifs_update = block.get("motifs_update")
    if motifs_update and isinstance(motifs_update, list):
        motifs = ledger.setdefault("motifs", [])
        for mu in motifs_update:
            if not isinstance(mu, dict) or not mu.get("symbol"):
                continue
            existing = next((m for m in motifs if m.get("symbol") == mu["symbol"]), None)
            if existing:
                if mu.get("evolution_add"):
                    evol = existing.setdefault("evolution", [])
                    evol.append(mu["evolution_add"])
                    evol[:] = evol[-6:]
                # 主题意象复用时，meaning 必须增量生长（不是覆盖，是叠加新含义）
                if mu.get("kind"):
                    existing["kind"] = mu["kind"]
                if mu.get("meaning_add"):
                    cur_mean = existing.get("meaning", "")
                    existing["meaning"] = (cur_mean + " → " + mu["meaning_add"]) if cur_mean else mu["meaning_add"]
                elif mu.get("meaning") and not existing.get("meaning"):
                    existing["meaning"] = mu["meaning"]
                existing["last_chapter"] = chapter
                existing["count"] = existing.get("count", 0) + mu.get("count_add", 1)
            else:
                motifs.append({
                    "symbol": mu["symbol"],
                    "kind": mu.get("kind", "线索"),
                    "meaning": mu.get("meaning", "") or mu.get("meaning_add", ""),
                    "first_chapter": chapter,
                    "last_chapter": chapter,
                    "count": 1,
                    "evolution": [mu.get("evolution_add", "")] if mu.get("evolution_add") else []
                })
        # Cap at 15 active motifs，但"主题意象"永不淘汰（它们是全书骨架）
        if len(motifs) > 15:
            theme_motifs = [m for m in motifs if m.get("kind") == "主题意象"]
            clue_motifs = [m for m in motifs if m.get("kind") != "主题意象"]
            clue_motifs.sort(key=lambda m: m.get("last_chapter", 0))
            keep_clues = clue_motifs[-(max(0, 15 - len(theme_motifs))):]
            ledger["motifs"] = theme_motifs + keep_clues

    # thematic_stances: 主题论辩账本（开放问句 + 各角色代言的立场，多数本卷不裁决）
    ts_update = block.get("thematic_stances_update")
    if ts_update and isinstance(ts_update, dict):
        stances = ledger.setdefault("thematic_stances", [])
        by_q = {s.get("question"): s for s in stances if isinstance(s, dict)}
        for nq in ts_update.get("new_questions") or []:
            if isinstance(nq, dict) and nq.get("question") and nq["question"] not in by_q:
                node = {
                    "question": nq["question"],
                    "positions": nq.get("positions") or [],
                    "verdict": nq.get("verdict") or "NEVER_RESOLVE",
                    "first_chapter": chapter,
                    "last_tested": chapter,
                }
                stances.append(node)
                by_q[nq["question"]] = node
        for uq in ts_update.get("update_questions") or []:
            if not isinstance(uq, dict) or not uq.get("question"):
                continue
            node = by_q.get(uq["question"])
            if not node:
                continue
            node["last_tested"] = chapter
            # 新立场加入（某角色第一次代言一个答案）
            for pos in uq.get("positions_add") or []:
                if isinstance(pos, dict) and pos.get("holder"):
                    existing = next((p for p in node["positions"] if isinstance(p, dict) and p.get("holder") == pos["holder"]), None)
                    if existing:
                        existing.update({k: v for k, v in pos.items() if v})
                    else:
                        pos.setdefault("dignity", "中")
                        pos.setdefault("tested_in", [])
                        node["positions"].append(pos)
            # 本章这个问题被哪一章/哪件事掂量了（记在相关立场的 tested_in 上）
            if uq.get("tested_note"):
                for p in node["positions"]:
                    if isinstance(p, dict):
                        ti = p.setdefault("tested_in", [])
                        ti.append({"chapter": chapter, "note": uq["tested_note"]})
                        p["tested_in"] = ti[-5:]
            if uq.get("verdict"):
                node["verdict"] = uq["verdict"]
        # 增长有界：核心问句本就稀少，硬封顶 8 个（多了说明主题发散）
        if len(stances) > 8:
            stances.sort(key=lambda s: s.get("last_tested", 0))
            ledger["thematic_stances"] = stances[-8:]

    # threads_update: 线索/支线台账（防 800 章断线、开出去的线无人收）
    threads_update = block.get("threads_update")
    if threads_update and isinstance(threads_update, dict):
        threads = ledger.setdefault("threads", [])
        by_id = {t.get("id"): t for t in threads if isinstance(t, dict) and t.get("id")}
        for nt in threads_update.get("new") or []:
            if not isinstance(nt, dict) or not nt.get("id"):
                continue
            if nt["id"] in by_id:
                by_id[nt["id"]].update(nt)
                by_id[nt["id"]]["last_advanced"] = chapter
            else:
                node = {
                    "id": nt["id"],
                    "desc": nt.get("desc", ""),
                    "status": nt.get("status", "活跃"),  # 活跃/休眠/已收
                    "owner": nt.get("owner", ""),
                    "opened_chapter": chapter,
                    "last_advanced": chapter,
                    "plan_resolve_by": nt.get("plan_resolve_by", ""),
                }
                threads.append(node)
                by_id[nt["id"]] = node
        for ut in threads_update.get("update") or []:
            if not isinstance(ut, dict) or ut.get("id") not in by_id:
                continue
            node = by_id[ut["id"]]
            if ut.get("status"):
                node["status"] = ut["status"]
                if ut["status"] == "已收":
                    node["resolved_chapter"] = chapter
            if ut.get("advanced"):
                node["last_advanced"] = chapter
            if ut.get("plan_resolve_by"):
                node["plan_resolve_by"] = ut["plan_resolve_by"]
            if ut.get("owner"):
                node["owner"] = ut["owner"]
        # 已收线在 5 章后退出（不再占位，仍留在文件历史里靠版本快照可查）
        threads[:] = [t for t in threads if not (
            t.get("status") == "已收" and chapter - (t.get("resolved_chapter") or chapter) > 5
        )]
        # 活跃+休眠硬封顶 40 条（超了说明线开太多，按最久没推进的丢最旧的休眠线）
        if len(threads) > 40:
            dormant = sorted(
                [t for t in threads if t.get("status") == "休眠"],
                key=lambda t: t.get("last_advanced", 0),
            )
            drop = len(threads) - 40
            drop_ids = {id(t) for t in dormant[:drop]}
            threads[:] = [t for t in threads if id(t) not in drop_ids]

    # reveal_ledger_update: 世界观揭示节奏台账（防神秘感提前破产/设定一次性倒完）
    rl_update = block.get("reveal_ledger_update")
    if rl_update and isinstance(rl_update, dict):
        reveals = ledger.setdefault("reveal_ledger", [])
        by_topic = {r.get("topic"): r for r in reveals if isinstance(r, dict)}
        for nr in rl_update.get("new") or []:
            if isinstance(nr, dict) and nr.get("topic") and nr["topic"] not in by_topic:
                node = {
                    "topic": nr["topic"],
                    "revealed_level": int(nr.get("revealed_level", 0)),  # 已揭示到第几层
                    "plan_next_level_in": nr.get("plan_next_level_in", ""),  # 计划在哪卷揭下一层
                    "first_chapter": chapter,
                    "last_reveal_chapter": chapter,
                }
                reveals.append(node)
                by_topic[nr["topic"]] = node
        for ur in rl_update.get("update") or []:
            if not isinstance(ur, dict) or ur.get("topic") not in by_topic:
                continue
            node = by_topic[ur["topic"]]
            if ur.get("revealed_level") is not None:
                node["revealed_level"] = int(ur["revealed_level"])
                node["last_reveal_chapter"] = chapter
            if ur.get("plan_next_level_in"):
                node["plan_next_level_in"] = ur["plan_next_level_in"]
        # 大设定数量天然有限，硬封顶 20 条
        if len(reveals) > 20:
            ledger["reveal_ledger"] = reveals[-20:]

    # emotional_anchor_event: 本章产生的情感分量时刻(告别/承诺/失去/牵挂/意难平)
    ea_events = block.get("emotional_anchor_event") or block.get("emotional_anchors_new")
    if ea_events:
        if isinstance(ea_events, dict):
            ea_events = [ea_events]
        anchors = ledger.setdefault("emotional_anchors", [])
        # 生成下一个 EA 编号
        existing_ids = [int(re.search(r"\d+", a.get("id", "EA-0")).group()) for a in anchors if isinstance(a, dict) and re.search(r"\d+", a.get("id", ""))]
        next_id = max(existing_ids, default=0) + 1
        for ev in ea_events:
            if not isinstance(ev, dict) or not ev.get("content"):
                continue
            anchors.append({
                "id": f"EA-{next_id:03d}",
                "type": ev.get("type", "牵挂"),
                "chapter": chapter,
                "content": ev.get("content", ""),
                "object": ev.get("object", ""),
                "emotional_target": ev.get("emotional_target", ""),
                "echo_status": "活跃",
                "last_echo_chapter": None,
                "echo_count": 0,
                "note": ev.get("note", ""),
            })
            next_id += 1
        # 回响登记:本章回响了哪些旧锚点
        for echoed_id in (block.get("emotional_anchor_echoed") or []):
            for a in anchors:
                if isinstance(a, dict) and a.get("id") == echoed_id:
                    a["echo_count"] = a.get("echo_count", 0) + 1
                    a["last_echo_chapter"] = chapter
                    if a["echo_count"] >= 2 and a.get("type") != "意难平":
                        a["echo_status"] = "已回响"
        # 增长控制:活跃非意难平锚点超30,把最久没回响的转沉睡(意难平永久保留)
        active = [a for a in anchors if isinstance(a, dict) and a.get("echo_status") == "活跃" and a.get("type") != "意难平"]
        if len(active) > 30:
            active.sort(key=lambda a: a.get("last_echo_chapter") or a.get("chapter") or 0)
            for a in active[: len(active) - 30]:
                a["echo_status"] = "沉睡"

    # timeline_update: updates state.json timeline
    timeline_update = block.get("timeline_update")
    if timeline_update and isinstance(timeline_update, dict):
        state = load_state()
        tl = state.setdefault("timeline", {"absolute_day": 1, "time_of_day": "未知", "season": "未知", "pending_timers": []})
        if timeline_update.get("day_advance"):
            tl["absolute_day"] = tl.get("absolute_day", 1) + timeline_update["day_advance"]
        if timeline_update.get("time_of_day"):
            tl["time_of_day"] = timeline_update["time_of_day"]
        if timeline_update.get("season_change"):
            tl["season"] = timeline_update["season_change"]
        for timer in timeline_update.get("timers_add") or []:
            if isinstance(timer, dict) and timer.get("event"):
                timer.setdefault("chapter_set", chapter)
                tl.setdefault("pending_timers", []).append(timer)
        for tid in timeline_update.get("timers_resolve") or []:
            tl["pending_timers"] = [t for t in tl.get("pending_timers", []) if t.get("event") != tid]
        # Auto-expire timers past due
        current_day = tl.get("absolute_day", 1)
        tl["pending_timers"] = [t for t in tl.get("pending_timers", []) if t.get("due_day", 999) >= current_day - 5]
        # Cap at 10
        tl["pending_timers"] = tl["pending_timers"][-10:]
        dump_json(STATE_FILE, state)

    # travel_update: appends to config/travel_matrix.json
    travel_update = block.get("travel_update")
    if travel_update and isinstance(travel_update, dict) and travel_update.get("from"):
        travel_file = BASE_DIR / "config" / "travel_matrix.json"
        if travel_file.exists():
            travel_data = load_json(travel_file, {"distances": [], "rules": []})
            distances = travel_data.setdefault("distances", [])
            # Dedupe by from+to
            key = (travel_update["from"], travel_update.get("to", ""))
            if not any(d.get("from") == key[0] and d.get("to") == key[1] for d in distances):
                distances.append(travel_update)
                # Cap at 80 entries
                if len(distances) > 80:
                    distances[:] = distances[-80:]
                dump_json(travel_file, travel_data)

    dump_json(LEDGER_FILE, ledger)
    write_ledger_markdown(ledger)


def write_ledger_markdown(ledger: Dict[str, Any]) -> None:
    lines = ["# 正典账本（可读快照，真值在 ledger.json）", ""]
    lines.append("## 实体")
    ents = ledger.get("entities") or {}
    if ents:
        for name, e in ents.items():
            voice = f"；声音={e['voice']}" if e.get("voice") else ""
            lines.append(f"- [{e.get('type','?')}] {name}（{e.get('status','?')}，首见第{e.get('first_chapter','?')}章）：{e.get('summary','')}{voice}")
            ac = e.get("arc_core")
            if isinstance(ac, dict) and (ac.get("want") or ac.get("lie")):
                lines.append(f"  - 弧线内核：想要={ac.get('want','')}／真正需要={ac.get('need','')}／谎={ac.get('lie','')}／真相={ac.get('truth','')}")
            sd = e.get("self_deception")
            if isinstance(sd, dict) and sd.get("lie"):
                lines.append(f"  - 自欺（{sd.get('status','活跃')}）：「{sd['lie']}」")
            for f in e.get("facts") or []:
                lines.append(f"  - {f}")
    else:
        lines.append("- 暂无")
    lines += ["", "## 物品清单（inventory）"]
    inventory = ledger.get("inventory") or {}
    currency = inventory.get("currency") or {}
    if currency:
        cur_parts = [f"{k}={v}" for k, v in currency.items() if k != "notes"]
        lines.append(f"- 财产：{'、'.join(cur_parts)}" if cur_parts else "- 财产：无")
    techniques = inventory.get("techniques") or []
    if techniques:
        lines.append(f"- 已习得：{'、'.join(t.get('name','?') for t in techniques[:15])}")
    key_items = inventory.get("key_items") or []
    if key_items:
        for ki in key_items:
            lines.append(f"- [关键物品] {ki.get('name','')}（{ki.get('status','?')}）最后第{ki.get('last_chapter','?')}章")
    consumables = inventory.get("consumables") or []
    if consumables:
        for c in consumables:
            lines.append(f"- [消耗品] {c.get('name','')} ×{c.get('qty',0)} 最后第{c.get('last_chapter','?')}章")
    if not inventory:
        lines.append("- 暂无")
    lines += ["", "## 资源账（旧格式兼容）"]
    res = ledger.get("resources") or {}
    lines += [f"- {k}：{v}" for k, v in res.items()] or ["- 暂无"]
    lines += ["", "## 愿录"]
    ly_log = ledger.get("liaoYuan_log") or []
    if ly_log:
        for entry in ly_log[-10:]:
            lines.append(f"- 第{entry.get('chapter','?')}章：{entry.get('wish','')}→{entry.get('reward','')}（等级→{entry.get('level_after','?')}）")
    else:
        lines.append("- 暂无")
    lines += ["", "## 意象（motifs）"]
    motifs = ledger.get("motifs") or []
    if motifs:
        for m in motifs:
            evol = m.get("evolution") or []
            evol_str = f" 演变：{'→'.join(evol[-3:])}" if evol else ""
            kind = m.get("kind", "线索")
            lines.append(f"- [{kind}] {m.get('symbol','')}：{m.get('meaning','')}（出现{m.get('count',0)}次，首见第{m.get('first_chapter','?')}章）{evol_str}")
    else:
        lines.append("- 暂无")
    lines += ["", "## 主题论辩账本（thematic_stances）"]
    stances = ledger.get("thematic_stances") or []
    if stances:
        for s in stances:
            if not isinstance(s, dict):
                continue
            lines.append(f"- 问：{s.get('question','')}（裁决：{s.get('verdict','NEVER_RESOLVE')}）")
            for p in s.get("positions") or []:
                if isinstance(p, dict):
                    lines.append(f"  - {p.get('holder','?')}（分量{p.get('dignity','中')}）：{p.get('answer','')}")
    else:
        lines.append("- 暂无")
    lines += ["", "## 线索/支线台账（threads）"]
    threads = ledger.get("threads") or []
    if threads:
        for t in threads:
            if not isinstance(t, dict):
                continue
            plan = f"，计划{t['plan_resolve_by']}收" if t.get("plan_resolve_by") else ""
            lines.append(f"- [{t.get('status','?')}] {t.get('id','')} {t.get('desc','')}（{t.get('owner','?')}{plan}，开于第{t.get('opened_chapter','?')}章，上次推进第{t.get('last_advanced','?')}章）")
    else:
        lines.append("- 暂无")
    lines += ["", "## 揭示节奏台账（reveal_ledger）"]
    reveals = ledger.get("reveal_ledger") or []
    if reveals:
        for r in reveals:
            if isinstance(r, dict):
                lines.append(f"- {r.get('topic','')}：已揭L{r.get('revealed_level',0)}，下一层计划{r.get('plan_next_level_in','') or '未定'}")
    else:
        lines.append("- 暂无")
    lines += ["", "## 未结清账（悬空=未还）"]
    obs = [o for o in (ledger.get("obligations") or [])]
    if obs:
        for o in obs:
            lines.append(f"- [{o.get('status','?')}] {o.get('id','')} {o.get('desc','')}（起于第{o.get('since_chapter','?')}章）")
    else:
        lines.append("- 暂无")
    lines += ["", "## 约束账（已成事实）"]
    cons = ledger.get("constraints") or []
    if cons:
        for c in cons:
            lines.append(f"- [{c.get('binding','?')}约束] {c.get('desc','')}（起于第{c.get('since_chapter','?')}章）")
    else:
        lines.append("- 暂无")
    lines += ["", "## 关系账"]
    rels = ledger.get("relationships") or {}
    if rels:
        for pair, node in rels.items():
            lines.append(f"- {pair}：{node.get('current','')}")
            for h in node.get("history") or []:
                lines.append(f"  - 第{h.get('chapter','?')}章：{h.get('event','')}")
    else:
        lines.append("- 暂无")
    lines += ["", "## 势力账本"]
    factions = ledger.get("factions") or {}
    if factions:
        for fname, fdata in factions.items():
            if not isinstance(fdata, dict):
                continue
            rels_str = ""
            f_rels = fdata.get("relationships") or []
            if f_rels:
                rels_str = " | " + "；".join(f"{r.get('target','')}={r.get('relation','')}" for r in f_rels[:5] if isinstance(r, dict))
            lines.append(f"- [{fdata.get('status','?')}] {fname}({fdata.get('type','')}) 首领:{fdata.get('leader','?')} 对主角:{fdata.get('stance_to_mc','未知')}{rels_str}")
            for h in (fdata.get("history") or [])[-3:]:
                lines.append(f"  - 第{h.get('chapter','?')}章：{h.get('event','')}")
    else:
        lines.append("- 暂无")
    write_text(LEDGER_MD_FILE, "\n".join(lines) + "\n")


def apply_character_arc_note(chapter: int, archive_report: str) -> None:
    """抽取 archivist 的「人物内在笔记」自由文字，追加进 character_arcs.md。血肉记忆。"""
    note = extract_markdown_section(archive_report, "人物内在笔记")
    if not note:
        return
    append_text(CHARACTER_ARCS_FILE, f"## 第{chapter}章\n\n{note}\n")


def validate_archivist_report(chapter: int, archive_report: str) -> List[str]:
    """记忆写入前校验报告完整性。返回问题列表，空列表=通过。
    挡住 token 截断、JSON 坏掉、必填段缺失——这些若放过，本章记忆会静默丢失。"""
    problems: List[str] = []
    if not archive_report or len(archive_report.strip()) < 30:
        problems.append("记录员报告为空或过短，疑似 API 截断/失败。")
        return problems
    # STRUCTURED_UPDATE 段必须存在且 JSON 能解析（走与写入相同的净化逻辑,
    # 这样 mimo 可修复的小毛病不会被误判成"截断"而整章重跑）
    section = extract_markdown_section(archive_report, "STRUCTURED_UPDATE")
    if not section:
        problems.append("缺少 STRUCTURED_UPDATE 段。")
    else:
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", section)
        payload = fenced.group(1) if fenced else section
        if not _parse_structured_payload(payload):
            problems.append("STRUCTURED_UPDATE JSON 解析失败（净化后仍无法解析，疑似被截断）。")
    # 报告尾部完整性：只在报告极短时才怀疑截断(token 已给够,正常不会截断)
    if len(archive_report.strip()) < 200:
        problems.append("report too short (<200 chars), possibly truncated")
    return problems


def apply_archivist_update(chapter: int, archive_report: str) -> None:
    """事务性写入：先校验，再写全部记忆，最后才推进 latest_chapter（提交标记）。
    任何一步抛错都不会推进 latest_chapter，下次启动对账会用正文重建本章。"""
    problems = validate_archivist_report(chapter, archive_report)
    if problems:
        # 不提交、不推进 latest_chapter，抛错让上层决定（恢复流程会重调 archivist）
        raise RuntimeError(
            f"第 {chapter} 章记录员报告未通过完整性校验，拒绝写入记忆以防污染："
            + "；".join(problems)
        )

    structured_update = extract_structured_update(archive_report)
    # 1. 各层记忆写入（latest_chapter 已从 merge_state_update 剥离）
    merge_state_update(structured_update)
    merge_ledger_update(structured_update, chapter)
    apply_character_arc_note(chapter, archive_report)

    status_delta = extract_markdown_section(archive_report, "状态台账增量") or archive_report.strip()
    expectation_delta = extract_markdown_section(archive_report, "期待账本增量")
    append_text(
        BASE_DIR / "07-动态状态台账.md",
        f"### 第{chapter}章自动更新\n\n{status_delta}\n",
    )
    if expectation_delta:
        append_text(
            BASE_DIR / "08-期待账本.md",
            f"### 第{chapter}章自动更新\n\n{expectation_delta}\n",
        )

    VERSION_DIR.mkdir(parents=True, exist_ok=True)
    write_text(VERSION_DIR / f"chapter_{chapter}_台账.md", read_text(BASE_DIR / "07-动态状态台账.md"))
    write_text(VERSION_DIR / f"chapter_{chapter}_期待账本.md", read_text(BASE_DIR / "08-期待账本.md"))

    # 2. 最后一步：推进提交标记。到这里说明本章所有记忆都已落盘。
    state = load_state()
    if int(state.get("latest_chapter") or 0) < chapter:
        state["latest_chapter"] = chapter
        dump_json(STATE_FILE, state)
        write_state_mirrors()


def completed_article_chapters() -> List[int]:
    chapters: List[int] = []
    manuscript_pattern = re.compile(r"第(\d+)章\.md$")
    if ARTICLE_DIR.exists():
        for path in ARTICLE_DIR.iterdir():
            if not path.is_file():
                continue
            match = manuscript_pattern.match(path.name)
            if match:
                chapters.append(int(match.group(1)))
    return sorted(set(chapters))


def recover_state_from_completed_articles(run_cfg: Dict[str, Any]) -> None:
    if run_cfg.get("dry_run") or not run_cfg.get("auto_recover_on_start", True):
        return
    state = load_state()
    latest_state = int(state.get("latest_chapter") or 0)
    missing = [chapter for chapter in completed_article_chapters() if chapter > latest_state]
    if not missing:
        return

    timeout = int(run_cfg.get("request_timeout_seconds") or 240)
    archivist_prompt = read_text(PROMPTS_DIR / "archivist.md")
    cli_print(
        "检测到正文已落盘但结构化状态落后："
        + ", ".join(f"第{chapter}章" for chapter in missing)
        + "。先自动补台账。"
    )
    for chapter in missing:
        final = read_text(manuscript_path(chapter)).strip()
        min_chars = int(run_cfg.get("min_recover_article_chars") or 1000)
        if len(final) < min_chars:
            raise RuntimeError(
                f"第 {chapter} 章正文长度只有 {len(final)} 字符，疑似死机时写坏。"
                f"请人工检查 {manuscript_path(chapter)} 后再继续。"
            )

        archive_path = role_artifact("archivist", chapter, "archive_update.md")
        archive_report = read_text(archive_path).strip()
        # 已存在的报告也要过完整性校验：上次可能正是崩在写入前、报告本身就是坏的
        if archive_report and not validate_archivist_report(chapter, archive_report):
            cli_print(f"第 {chapter} 章使用已存在且完整的记录员报告恢复台账。")
        else:
            if archive_report:
                cli_print(f"第 {chapter} 章已存在的记录员报告不完整，重新调用 Archivist。")
            else:
                cli_print(f"第 {chapter} 章缺少记录员报告，调用 Archivist 补台账。")
            archive_input = make_archive_input(final, chapter, run_cfg, timeout)
            archive_report = ""
            last_error = ""
            for attempt in range(2):
                archive_report = call_role(
                    "archivist",
                    archivist_prompt,
                    archive_input,
                    archive_path,
                    timeout,
                    3000,
                    role_artifact("archivist", chapter, "archive_input.md"),
                )
                if not validate_archivist_report(chapter, archive_report):
                    break
                last_error = "；".join(validate_archivist_report(chapter, archive_report))
                cli_print(f"第 {chapter} 章恢复时报告仍不完整（第 {attempt + 1} 次）：{last_error}")
                time.sleep(1)
        if run_cfg.get("apply_archivist_updates", True):
            apply_archivist_update(chapter, archive_report)
        cleanup_chapter_artifacts(chapter, run_cfg)
    cli_print("断点恢复完成。")


def detect_next_chapter() -> int:
    highest = 0
    flat_pattern = re.compile(r"chapter_(\d+)_final\.md$")
    manuscript_pattern = re.compile(r"第(\d+)章\.md$")
    if OUTPUT_DIR.exists():
        for path in OUTPUT_DIR.iterdir():
            match = flat_pattern.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    if ARTICLE_DIR.exists():
        for path in ARTICLE_DIR.iterdir():
            match = manuscript_pattern.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def determine_start_chapter(args_chapter: Optional[int], run_cfg: Dict[str, Any]) -> int:
    if args_chapter:
        return int(args_chapter)
    configured = run_cfg.get("start_chapter", "auto")
    if isinstance(configured, str) and configured.strip().lower() in ("auto", "next", ""):
        return detect_next_chapter()
    return int(configured)


def ensure_beat(chapter: int, beat_path: Path, run_cfg: Dict[str, Any], timeout: int) -> Optional[Path]:
    if beat_path.exists():
        return beat_path
    if not run_cfg.get("auto_generate_beat", True):
        raise RuntimeError(f"beat 文件不存在：{beat_path}")

    beat_input = build_beat_input(chapter, run_cfg, timeout)
    beat_prompt = read_text(PROMPTS_DIR / "beat_planner.md") or (
        "你是章节 beat 规划师。只输出一个 JSON 对象，不要 Markdown。"
    )
    write_text(role_artifact("beat", chapter, "beat_prompt.md"), beat_input)
    if run_cfg.get("dry_run"):
        print(f"dry-run: beat prompt saved for chapter {chapter}; beat 文件不存在，未调用 API。")
        return None

    print(f"[chapter {chapter}] Beat planner...")
    raw = call_role(
        "beat_planner",
        beat_prompt,
        beat_input,
        role_artifact("beat", chapter, "beat_raw.md"),
        timeout,
        1800,
        role_artifact("beat", chapter, "beat_input.md"),
    )
    beat = normalize_beat(chapter, extract_json_object(raw))
    direction = beat_direction_check(beat, chapter)
    dump_json(role_artifact("gate", chapter, "beat_direction.json"), direction)
    if not direction.get("passed") and not run_cfg.get("dry_run"):
        cli_print(f"[story_director] 第{chapter}章 beat 未充分吸收故事总监批注,重生成一次。")
        retry_input = beat_input + "\n\n===== 上一次 beat 的方向问题 =====\n" + json.dumps(direction, ensure_ascii=False, indent=2)
        raw = call_role(
            "beat_planner",
            beat_prompt,
            retry_input,
            role_artifact("beat", chapter, "beat_raw_retry.md"),
            timeout,
            1800,
            role_artifact("beat", chapter, "beat_input_retry.md"),
        )
        beat = normalize_beat(chapter, extract_json_object(raw))
        direction = beat_direction_check(beat, chapter)
        dump_json(role_artifact("gate", chapter, "beat_direction_retry.json"), direction)
    dump_json(beat_path, beat)
    return beat_path


def make_archive_input(final: str, chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    # Build compact inventory + motifs snapshot for archivist to compute deltas
    ledger = load_ledger()
    inv = ledger.get("inventory") or {}
    inv_lines = []
    currency = inv.get("currency") or {}
    if currency:
        inv_lines.append(f"财产：{json.dumps(currency, ensure_ascii=False)}")
    for t in (inv.get("techniques") or []):
        if t.get("status") != "过时":
            inv_lines.append(f"技能：{t.get('name','')}({t.get('type','')})")
    for i in (inv.get("key_items") or []):
        if i.get("status") == "持有":
            inv_lines.append(f"物品：{i.get('name','')} @{i.get('location','随身')}")
    for c in (inv.get("consumables") or []):
        if (c.get("qty") or 0) > 0:
            inv_lines.append(f"消耗品：{c.get('name','')}×{c.get('qty')}")
    inv_snapshot = "\n".join(inv_lines) if inv_lines else "无"
    motifs = ledger.get("motifs") or []
    motif_snapshot = "\n".join(f"- {m.get('symbol','')}: {m.get('meaning','')} (演变:{'→'.join(m.get('evolution',[])[-3:])})" for m in motifs[:10]) if motifs else "无"
    ly_log = ledger.get("liaoYuan_log") or []
    ly_snapshot = f"愿录：{ly_log[-1].get('level_after','?')} 累计{len(ly_log)}次" if ly_log else "愿录：LV1(0/10)"

    sections = [
        make_section("结构化当前状态", structured_state_text(), "high", True),
        make_section("当前物品清单(计算delta用)", inv_snapshot, "high", False),
        make_section("当前意象注册(计算delta用)", motif_snapshot, "normal", True),
        make_section("愿录状态", ly_snapshot, "normal", True),
        make_section("最近台账日志摘录", recent_ledger_tail(), "low", True),
        make_section("本章正文", final, "critical", False),
    ]
    return compress_sections_if_needed("archivist", chapter, sections, run_cfg, timeout)


def run_fact_checker(final: str, beat: Dict[str, Any], chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    """调用 LLM 事实核查员:拿角色卡+状态核对正文,抓穿帮。"""
    ledger = load_ledger()
    cast = set(str(c) for c in (beat.get("出场角色") or []))
    entities = ledger.get("entities") or {}
    # 只给本章出场角色的完整卡(控制 token)
    cards: List[str] = []
    for name in cast:
        e = entities.get(name)
        if not e or not isinstance(e, dict):
            continue
        card_lines = [f"【{name}】"]
        for field in ["realm", "skills", "weapons", "injuries", "secrets", "enemies", "current_goal", "faction", "reputation"]:
            v = e.get(field)
            if v:
                card_lines.append(f"  {field}: {json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v}")
        cards.append("\n".join(card_lines))
    # 物品清单(替代旧资源账)
    inventory = ledger.get("inventory") or {}
    inv_parts = []
    currency = inventory.get("currency") or {}
    if currency:
        c_parts = [f"{k}{v}" for k, v in currency.items() if k != "notes" and v]
        if c_parts:
            inv_parts.append(f"财产：{'、'.join(c_parts)}")
    techniques = [t for t in (inventory.get("techniques") or []) if t.get("status") != "过时"]
    if techniques:
        inv_parts.append(f"技能：{'、'.join(t.get('name','') for t in techniques[:8])}")
    key_items = [i for i in (inventory.get("key_items") or []) if i.get("status") == "持有"]
    if key_items:
        inv_parts.append(f"关键物品：{'、'.join(i.get('name','') for i in key_items[:10])}")
    consumables = [c for c in (inventory.get("consumables") or []) if (c.get("qty") or 0) > 0]
    if consumables:
        cons_strs = [f"{c['name']}×{c['qty']}" for c in consumables[:6]]
        inv_parts.append(f"消耗品：{'、'.join(cons_strs)}")
    res_text = "\n".join(f"- {p}" for p in inv_parts) if inv_parts else "无"
    # 约束账
    constraints = ledger.get("constraints") or []
    con_text = "\n".join(f"- {c.get('desc', '')}" for c in constraints if isinstance(c, dict)) if constraints else "无"
    # 关系账(只给出场角色相关的)
    relationships = ledger.get("relationships") or {}
    rel_lines = []
    for pair, info in relationships.items():
        if any(name in pair for name in cast):
            rel_lines.append(f"- {pair}: {info.get('current', '未知')}")
    rel_text = "\n".join(rel_lines) if rel_lines else "无"
    # 全部已登记角色名单(用于检测"凭空冒出来的人")
    all_known_names = [name for name, e in entities.items() if isinstance(e, dict) and e.get("type") == "角色"]

    input_sections = [
        f"## 本章 beat 规划的出场角色\n{', '.join(cast) if cast else '未指定'}",
        f"## 本章出场角色卡(详细)\n" + ("\n\n".join(cards) if cards else "无角色卡记录"),
        f"## 全部已登记角色名单(正文出现不在此名单里的角色名=可疑,可能是幻觉)\n" + "、".join(all_known_names) if all_known_names else "暂无登记",
        f"## 资源账\n{res_text}",
        f"## 约束账(不可推翻的事实)\n{con_text}",
        f"## 关系账\n{rel_text}",
        f"## 本章正文\n{final}",
    ]
    input_text = "\n\n".join(input_sections)
    prompt = read_text(PROMPTS_DIR / "fact_checker.md")
    cli_print(f"[fact_checker] 核查第{chapter}章,输入≈{estimate_tokens(input_text)} tokens")
    return call_role("fact_checker", prompt, input_text, role_artifact("gate", chapter, "fact_check.md"), timeout, 3000)


def _ngram_set(text: str, n: int = 4) -> set:
    """正文 4-gram 集合（去标点空白），用于估候选与已写章节的情节/措辞相似度。"""
    clean = re.sub(r"[\s，。、！？；：「」『』（）()…—\-·\n]", "", text)
    return {clean[i:i + n] for i in range(max(0, len(clean) - n + 1))}


def self_repetition_penalty(text: str, chapter: int, lookback: int = 5) -> float:
    """候选与最近 lookback 章正文的最大 4-gram Jaccard 相似度（0~1）。
    越高说明越像之前写过的（自我重复），作为 Best-of-N 的惩罚项。"""
    cand = _ngram_set(text)
    if not cand:
        return 0.0
    worst = 0.0
    for ch in range(max(1, chapter - lookback), chapter):
        path = manuscript_path(ch)
        if not path.exists():
            continue
        prev = _ngram_set(read_text(path))
        if not prev:
            continue
        inter = len(cand & prev)
        union = len(cand | prev)
        if union:
            worst = max(worst, inter / union)
    return worst


def score_candidate(text: str, beat: Dict[str, Any], chapter: int) -> Dict[str, Any]:
    """给一份候选打分（全部用免费的 code 检查，不烧 reviewer token）。
    分数越高越好。综合：硬门禁 + 风格门禁 + 满足度 + 反自我重复 + 篇幅达标。"""
    hard = hard_gate(text)
    style = style_gate(text)
    satisfaction = chapter_satisfaction_check(text, beat)
    rep = self_repetition_penalty(text, chapter)
    chinese = len(re.findall(r"[一-鿿]", text))
    score = 100.0
    if not hard.get("passed", True):
        score -= 40 + 8 * len(hard.get("issues") or [])   # 硬伤最重罚
    score -= 5 * len(style.get("issues") or [])           # 每条风格问题
    score -= 6 * len(satisfaction or [])                  # beat 承诺没兑现
    score -= 60 * rep                                     # 自我重复惩罚（Sui Generis）
    if chinese < 2000:
        score -= 15                                       # 篇幅不足
    return {
        "score": round(score, 1),
        "rep_similarity": round(rep, 3),
        "hard_passed": hard.get("passed", True),
        "style_issue_count": len(style.get("issues") or []),
        "satisfaction_issue_count": len(satisfaction or []),
        "chinese_chars": chinese,
    }


def best_of_n_enabled(beat: Dict[str, Any], run_cfg: Dict[str, Any]) -> int:
    """决定本章 writer 采样几份。默认 1（关闭）。
    仅当 run.json 开启 best_of_n 且本章是关键/高潮章（beat 标注或 run.json 配置）才 >1。
    费 token，故默认只在关键章开启。"""
    cfg = run_cfg.get("best_of_n")
    if not cfg or not isinstance(cfg, dict) or not cfg.get("enabled"):
        return 1
    n = int(cfg.get("n") or 3)
    # 触发条件：beat 显式标注，或本章号在 run.json 的关键章清单里
    beat_flag = bool(beat.get("关键章") or beat.get("高潮章") or beat.get("best_of_n"))
    key_chapters = set(int(c) for c in (cfg.get("key_chapters") or []) if str(c).isdigit())
    ch = int(beat.get("章节编号") or 0)
    if beat_flag or ch in key_chapters:
        return max(2, min(n, 5))   # 安全区间 2~5
    return 1


def write_best_of_n(chapter: int, beat: Dict[str, Any], writer_prompt: str, writer_input: str,
                    n: int, timeout: int) -> str:
    """采样 N 份初稿，用 score_candidate 排序选 top-1。只有 writer 这步 ×N，
    打分全用免费 code 检查，reviewer/editor 仍只对赢家跑一次。"""
    candidates = []
    for i in range(1, n + 1):
        wait_if_paused(f"Best-of-{n} 候选 {i}/{n}")
        cli_print(f"[best_of_n] 第{chapter}章 候选 {i}/{n} 生成中…")
        draft_i = call_role(
            "writer",
            writer_prompt,
            writer_input,
            role_artifact("writer", chapter, f"draft_cand_{i}.md"),
            timeout,
            7000,
        )
        sc = score_candidate(draft_i, beat, chapter)
        candidates.append((sc["score"], i, draft_i, sc))
        cli_print(f"[best_of_n]   候选{i}: 分={sc['score']} 重复度={sc['rep_similarity']} "
                  f"硬伤={'无' if sc['hard_passed'] else '有'} 风格问题={sc['style_issue_count']} 字数={sc['chinese_chars']}")
    candidates.sort(key=lambda x: -x[0])
    best_score, best_i, best_draft, best_sc = candidates[0]
    cli_print(f"[best_of_n] 第{chapter}章 选中候选{best_i}（分={best_score}）")
    dump_json(role_artifact("gate", chapter, "best_of_n.json"), {
        "n": n, "winner": best_i, "winner_score": best_score,
        "all_scores": [{"cand": i, "score": s, **sc} for s, i, _d, sc in candidates],
    })
    # 赢家落到标准 draft.md，后续流程无感知
    write_text(role_artifact("writer", chapter, "draft.md"), best_draft)
    return best_draft


def run_one_chapter(chapter: int, beat_path: Path, run_cfg: Dict[str, Any], chapter_index: int, total_chapters: int) -> None:
    timeout = int(run_cfg.get("request_timeout_seconds") or 240)
    max_revisions = int(run_cfg.get("max_revisions") or 1)
    sleep_seconds = float(run_cfg.get("sleep_seconds_between_calls") or 1)
    total_steps = 7

    wait_if_paused("读取 beat")
    beat = json.loads(read_text(beat_path))
    started = stage_start(chapter, "writer", "构建上下文", 1, total_steps, chapter_index, total_chapters)
    writer_input = build_writer_input(beat, chapter, run_cfg, timeout)
    writer_prompt = read_text(PROMPTS_DIR / "writer.md")
    reviewer_prompt = read_text(PROMPTS_DIR / "reviewer.md")
    archivist_prompt = read_text(PROMPTS_DIR / "archivist.md")

    write_text(role_artifact("writer", chapter, "writer_prompt.md"), writer_input)
    stage_done(chapter, "writer", "构建上下文", 1, total_steps, started)
    if run_cfg.get("dry_run"):
        print(f"dry-run: writer prompt saved for chapter {chapter}")
        return

    wait_if_paused("Writer 写初稿前")
    started = stage_start(chapter, "writer", "写初稿", 2, total_steps, chapter_index, total_chapters)
    n_candidates = best_of_n_enabled(beat, run_cfg)
    if n_candidates > 1:
        cli_print(f"[best_of_n] 第{chapter}章为关键章，采样 {n_candidates} 份择优（writer×{n_candidates}，费 token）")
        draft = write_best_of_n(chapter, beat, writer_prompt, writer_input, n_candidates, timeout)
    else:
        draft = call_role(
            "writer",
            writer_prompt,
            writer_input,
            role_artifact("writer", chapter, "draft.md"),
            timeout,
            7000,
            role_artifact("writer", chapter, "writer_input.md"),
        )
    stage_done(chapter, "writer", "写初稿", 2, total_steps, started)
    time.sleep(sleep_seconds)

    wait_if_paused("Gate 硬检查前")
    started = stage_start(chapter, "gate", "硬检查", 3, total_steps, chapter_index, total_chapters)
    hard = hard_gate(draft)
    style = style_gate(draft)
    continuity = continuity_check(draft, chapter)
    type_guard = type_guard_check(draft, chapter)
    satisfaction = chapter_satisfaction_check(draft, beat)
    gate = combine_checks({
        "hard_gate": hard,
        "style_gate": style,
        "continuity_check": continuity,
        "type_guard": type_guard,
        "satisfaction_check": {"passed": not satisfaction, "issues": [], "warnings": satisfaction},
    })
    dump_json(role_artifact("gate", chapter, "gate.json"), gate)
    dump_json(role_artifact("gate", chapter, "style_gate.json"), style)
    dump_json(role_artifact("gate", chapter, "continuity.json"), continuity)
    dump_json(role_artifact("gate", chapter, "type_guard.json"), type_guard)
    stage_done(chapter, "gate", "硬检查", 3, total_steps, started)

    wait_if_paused("Reviewer 评审前")
    started = stage_start(chapter, "reviewer", "评审", 4, total_steps, chapter_index, total_chapters)
    review_input = make_review_input(draft, chapter, run_cfg, timeout, gate)
    review = call_role(
        "reviewer",
        reviewer_prompt,
        review_input,
        role_artifact("reviewer", chapter, "review.md"),
        timeout,
        3000,
        role_artifact("reviewer", chapter, "review_input.md"),
    )
    stage_done(chapter, "reviewer", "评审", 4, total_steps, started)
    time.sleep(sleep_seconds)

    final = draft
    if max_revisions > 0 and needs_revision(gate, review):
        wait_if_paused("Editor 修稿前")
        started = stage_start(chapter, "editor", "修稿", 5, total_steps, chapter_index, total_chapters)
        editor_prompt = (
            "你是修稿手。只做局部手术，不做全文润色。只根据评审意见修正文，不新增世界观，不改变本章核心事件。"
            "优先消除AI腔、专名污染、注水、解释型对话、空钩子、长句长段和节奏问题。"
            "禁止把文字修得更工整、更对称、更像作文。保留短句、残句、沉默、口语毛刺和人物不完美反应。"
            "如果评审指出方向偏航，只做一个最小修正动作，让它读起来像原本就该这样发展。"
            "输出完整修订正文。"
        )
        editor_sections = [
            make_section("初稿", draft, "critical", False),
            make_section("硬检查/风格检查/连续性检查", json.dumps(gate, ensure_ascii=False, indent=2), "high", False),
            make_section("评审", review, "high", True),
        ]
        editor_input = compress_sections_if_needed("editor", chapter, editor_sections, run_cfg, timeout)
        final = call_role(
            "editor",
            editor_prompt,
            editor_input,
            role_artifact("editor", chapter, "edited.md"),
            timeout,
            7000,
            role_artifact("editor", chapter, "editor_input.md"),
        )
        stage_done(chapter, "editor", "修稿", 5, total_steps, started)
        time.sleep(sleep_seconds)
    else:
        started = stage_start(chapter, "editor", "无需修稿", 5, total_steps, chapter_index, total_chapters)
        stage_done(chapter, "editor", "无需修稿", 5, total_steps, started)

    final_hard = hard_gate(final)
    final_style = style_gate(final)
    final_continuity = continuity_check(final, chapter)
    final_type_guard = type_guard_check(final, chapter)
    final_satisfaction = chapter_satisfaction_check(final, beat)
    final_gate = combine_checks({
        "hard_gate": final_hard,
        "style_gate": final_style,
        "continuity_check": final_continuity,
        "type_guard": final_type_guard,
        "satisfaction_check": {"passed": not final_satisfaction, "issues": [], "warnings": final_satisfaction},
    })
    dump_json(role_artifact("gate", chapter, "final_gate.json"), final_gate)
    dump_json(role_artifact("gate", chapter, "final_style_gate.json"), final_style)
    dump_json(role_artifact("gate", chapter, "final_continuity.json"), final_continuity)
    dump_json(role_artifact("gate", chapter, "final_type_guard.json"), final_type_guard)
    if not final_gate.get("passed"):
        cli_print(f"第 {chapter} 章 final 仍有硬检查问题：{'; '.join(final_gate.get('issues') or [])}")
        if run_cfg.get("fail_on_final_gate", False):
            raise RuntimeError(f"第 {chapter} 章 final_gate 未通过")

    # 事实核查员(LLM):拿角色卡逐项核对正文,抓幻觉穿帮
    # 策略:两轮点对点小修改,第三轮还不过才整章重写。到此为止不循环。
    if not run_cfg.get("skip_fact_check"):
        ledger = load_ledger()
        entities = ledger.get("entities") or {}
        has_substance = any(
            isinstance(e, dict) and (e.get("skills") or e.get("enemies") or e.get("injuries"))
            for e in entities.values()
        )
        if not has_substance:
            cli_print(f"第 {chapter} 章:角色卡尚无实质数据,跳过事实核查。")
        else:
            started = stage_start(chapter, "fact_checker", "事实核查", 6, total_steps, chapter_index, total_chapters)
            original_len = len(re.findall(r'[一-鿿]', final))
            # 第1轮:查全文穿帮
            fact_check_result = run_fact_checker(final, beat, chapter, run_cfg, timeout)
            real_issues = len(re.findall(r"^\d+\.\s*\[", fact_check_result, re.MULTILINE)) if fact_check_result else 0
            if real_issues > 0:
                issue_lines = re.findall(r"^\d+\.\s*\[.*", fact_check_result, re.MULTILINE)
                cli_print(f"第 {chapter} 章事实核查第1轮:{real_issues} 处穿帮,点对点修改…")
                for il in issue_lines[:5]:
                    cli_print(f"  穿帮: {il[:80]}")
                # 第2轮:writer修改,要求附修改说明
                fix_input = (
                    "事实核查发现以下穿帮,请只修改穿帮所在的句子或段落,其他内容一字不动地保留。\n"
                    f"输出完整正文(包含未修改的部分),确保字数不少于{original_len}字。\n"
                    "修改完成后,在正文末尾另起一行写 ## 修改说明,逐条列出你改了第几段、原文是什么、改成了什么。\n\n"
                    f"## 穿帮报告\n{fact_check_result}\n\n## 正文(请在此基础上只改穿帮处)\n{final}"
                )
                fix_result = call_role(
                    "writer", writer_prompt, fix_input,
                    role_artifact("writer", chapter, "fact_fix_1.md"),
                    timeout, 7000,
                )
                # 分离正文和修改说明
                fix_parts = re.split(r"^## 修改说明", fix_result, maxsplit=1, flags=re.MULTILINE)
                fix_body = fix_parts[0].strip()
                fix_changelog = fix_parts[1].strip() if len(fix_parts) > 1 else "未提供修改说明"
                if len(fix_body) > len(final) * 0.6:
                    final = fix_body
                    # 第3轮:轻量验证(只看穿帮报告+修改说明,不查全文)
                    verify_input = (
                        "你是事实核查员。上一轮发现了以下穿帮,写手已经修改。请验证修改是否解决了问题。\n"
                        "只检查以下穿帮是否被正确修复,不要查找新问题。\n"
                        "如果全部修好,输出'全部修复,通过'。如果仍有问题,按原格式输出未修复的条目。\n\n"
                        f"## 原始穿帮报告\n{fact_check_result}\n\n"
                        f"## 写手修改说明\n{fix_changelog}\n\n"
                        f"## 修改后的相关段落\n{fix_body[:3000]}"
                    )
                    verify_result = call_role(
                        "fact_checker", read_text(PROMPTS_DIR / "fact_checker.md"), verify_input,
                        role_artifact("gate", chapter, "verify_1.md"),
                        timeout, 2000,
                    )
                    verify_issues = len(re.findall(r"^\d+\.\s*\[", verify_result, re.MULTILINE)) if verify_result else 0
                    if verify_issues > 0:
                        cli_print(f"第 {chapter} 章验证:仍有 {verify_issues} 处未修复,再次修改…")
                        for il in re.findall(r"^\d+\.\s*\[.*", verify_result, re.MULTILINE)[:3]:
                            cli_print(f"  未修复: {il[:80]}")
                        # 第4轮:writer再改一次
                        fix_input_2 = (
                            "验证发现以下穿帮仍未修复,请再次修改对应段落,其他内容不动。\n"
                            f"输出完整正文,确保字数不少于{original_len}字。\n"
                            "修改完成后在末尾写 ## 修改说明。\n\n"
                            f"## 未修复的穿帮\n{verify_result}\n\n## 正文\n{final}"
                        )
                        fix_result_2 = call_role(
                            "writer", writer_prompt, fix_input_2,
                            role_artifact("writer", chapter, "fact_fix_2.md"),
                            timeout, 7000,
                        )
                        fix_parts_2 = re.split(r"^## 修改说明", fix_result_2, maxsplit=1, flags=re.MULTILINE)
                        fix_body_2 = fix_parts_2[0].strip()
                        fix_changelog_2 = fix_parts_2[1].strip() if len(fix_parts_2) > 1 else "未提供修改说明"
                        if len(fix_body_2) > len(final) * 0.6:
                            final = fix_body_2
                            # 第5轮:最终验证
                            verify_input_2 = (
                                "你是事实核查员。请验证以下穿帮是否被修复。只检查这些,不查新问题。\n"
                                "如果修好输出'全部修复,通过'。否则输出未修复条目。\n\n"
                                f"## 穿帮\n{verify_result}\n\n## 修改说明\n{fix_changelog_2}"
                            )
                            verify_2 = call_role(
                                "fact_checker", read_text(PROMPTS_DIR / "fact_checker.md"), verify_input_2,
                                role_artifact("gate", chapter, "verify_2.md"),
                                timeout, 2000,
                            )
                            residual = len(re.findall(r"^\d+\.\s*\[", verify_2, re.MULTILINE)) if verify_2 else 0
                            if residual > 0:
                                cli_print(f"第 {chapter} 章最终验证:仍有 {residual} 处,接受现状。")
                                write_text(role_artifact("gate", chapter, "residual_issues.md"),
                                           f"# 第{chapter}章 残留穿帮\n\n{verify_2}")
                            else:
                                cli_print(f"第 {chapter} 章最终验证:通过。")
                        else:
                            cli_print(f"第 {chapter} 章第2轮修复输出过短,保留上一版。")
                    else:
                        cli_print(f"第 {chapter} 章验证:修复通过。")
                else:
                    cli_print(f"第 {chapter} 章第1轮修复输出过短,保留原版。")
            else:
                cli_print(f"第 {chapter} 章事实核查:无穿帮,通过。")
            stage_done(chapter, "fact_checker", "事实核查", 6, total_steps, started)

    # 清洗:mimo 有时会把思考过程吐到正文前面,只保留 "# 第X章" 开始的内容
    chapter_heading = re.search(r"^#\s*第\d+章", final, re.MULTILINE)
    if chapter_heading:
        final = final[chapter_heading.start():]

    write_text(role_artifact("writer", chapter, "final.md"), final)
    write_text(manuscript_path(chapter), final)

    wait_if_paused("Archivist 更新台账前")
    started = stage_start(chapter, "archivist", "更新台账", 7, total_steps, chapter_index, total_chapters)
    archive_input = make_archive_input(final, chapter, run_cfg, timeout)
    if run_cfg.get("apply_archivist_updates", True):
        # 记忆是唯一入口，必须写成功。报告不完整就重试一次；仍失败则停在本章，
        # 不推进 latest_chapter，正文已落盘，下次启动对账会用正文重建本章记忆。
        last_error = ""
        committed = False
        for attempt in range(2):
            archive_report = call_role(
                "archivist",
                archivist_prompt,
                archive_input,
                role_artifact("archivist", chapter, "archive_update.md"),
                timeout,
                3000,
                role_artifact("archivist", chapter, "archive_input.md"),
            )
            try:
                apply_archivist_update(chapter, archive_report)
                committed = True
                break
            except RuntimeError as exc:
                last_error = str(exc)
                cli_print(f"第 {chapter} 章记忆写入失败（第 {attempt + 1} 次）：{last_error}")
                time.sleep(sleep_seconds)
        if not committed:
            raise RuntimeError(
                f"第 {chapter} 章正文已保存，但记忆连续两次写入失败：{last_error}。"
                f"已停止以防记忆污染。修复后重跑会自动用正文重建本章记忆。"
            )
    else:
        call_role(
            "archivist",
            archivist_prompt,
            archive_input,
            role_artifact("archivist", chapter, "archive_update.md"),
            timeout,
            3000,
            role_artifact("archivist", chapter, "archive_input.md"),
        )
    stage_done(chapter, "archivist", "更新台账", 7, total_steps, started)
    cleanup_chapter_artifacts(chapter, run_cfg)
    cli_print(f"第 {chapter} 章完成：{manuscript_path(chapter)}")


# ========================= 分析师·全量扫读管线(一劳永逸) =========================
# 多次调用 LLM 分批通读全文,提炼纯写作手法 → 归并成手法 chunk。
# 设计:map-reduce、断点续跑、崩溃安全。每批结果落盘,跑挂了重跑只补缺批。
# 只在第一次开新书时用一次,后期写章节完全不碰它。

def source_text_path() -> Path:
    """源文路径。优先读 book.config.json 的 source_text,回落到 271824.txt。"""
    cfg = load_json(BASE_DIR / "book.config.json")
    name = (cfg or {}).get("source_text") or "271824.txt"
    return BASE_DIR / str(name)


REJECTION_PATTERN = re.compile(
    r"the request was rejected because it was considered high risk",
    re.IGNORECASE,
)


def is_rejection_text(text: str) -> bool:
    """识别 mimo 供应商的内容风控拒绝返回(HTTP 200,但 content 整段就是这句固定拒绝语)。
    mimo 不给结构化的 finish_reason=content_filter,只能精确匹配它这句特定串。
    精确匹配 → 误判率几乎为零:正文里角色就算说'违反''风险'也绝不会命中整句。
    仍保留 >500 字放行的兜底闸:真拒绝就是这一句(几十字),正文/JSON 远超此长度。"""
    if not text or not text.strip():
        return True
    s = text.strip()
    if len(s) > 500:
        return False
    return bool(REJECTION_PATTERN.search(s))


def split_source_into_batches(text: str, batch_token_budget: int) -> List[str]:
    """按 `第N章` 边界把全文切成批,每批累计到 token 预算才断。
    切在章边界,绝不切碎一个场景。源文无章标记时按行兜底。"""
    parts = re.split(r"(?=第\d+章)", text)
    parts = [p for p in parts if p.strip()]
    if len(parts) <= 1:
        lines = text.split("\n")
        parts, buf = [], []
        for ln in lines:
            buf.append(ln)
            if len(buf) >= 400:
                parts.append("\n".join(buf))
                buf = []
        if buf:
            parts.append("\n".join(buf))
    batches: List[str] = []
    cur: List[str] = []
    cur_tok = 0
    for p in parts:
        ptok = estimate_tokens(p)
        if cur and cur_tok + ptok > batch_token_budget:
            batches.append("\n".join(cur))
            cur, cur_tok = [], 0
        cur.append(p)
        cur_tok += ptok
    if cur:
        batches.append("\n".join(cur))
    return batches


def analyst_batch_path(idx: int) -> Path:
    return ANALYST_DIR / f"map_{idx:04d}.md"


def run_analyst(run_cfg: Dict[str, Any], dry_run: bool) -> None:
    """全量扫读管线入口。dry_run=True 只切批、估成本、写第一批 prompt,不调 API。"""
    ANALYST_DIR.mkdir(parents=True, exist_ok=True)
    src_path = source_text_path()
    if not src_path.exists():
        cli_print(f"[analyst] 源文不存在：{src_path}")
        return
    text = read_text(src_path)
    timeout = int(run_cfg.get("request_timeout_seconds") or 240)
    batch_budget = int((run_cfg.get("analyst") or {}).get("batch_token_budget") or 24000)
    batches = split_source_into_batches(text, batch_budget)
    map_prompt = read_text(PROMPTS_DIR / "analyst_map.md")
    reduce_prompt = read_text(PROMPTS_DIR / "analyst_reduce.md")
    total_in = sum(estimate_tokens(b) for b in batches) + len(batches) * estimate_tokens(map_prompt)
    cli_print(f"[analyst] 源文 {estimate_tokens(text)} tokens，切成 {len(batches)} 批（每批≤{batch_budget}）。")
    cli_print(f"[analyst] MAP 阶段预计输入≈{total_in} tokens（不含模型输出）。")

    if dry_run:
        preview = ANALYST_DIR / "_dryrun_batch0_prompt.md"
        if batches:
            write_text(preview, f"<<SYSTEM>>\n{map_prompt}\n\n<<INPUT(第1批)>>\n{batches[0]}")
        cli_print(f"[analyst] dry-run：已写第1批 prompt 预览 → {preview}")
        cli_print(f"[analyst] dry-run：未调用任何 API。去掉 --dry-run 才真正跑 {len(batches)} 批 MAP + 1 次 REDUCE。")
        return

    # ---- MAP：逐批扫读,已完成的批跳过(断点续跑) ----
    # 被风控拒的批写成 SKIP 标记,既不污染归并、又不会重跑时无限重试。
    done = 0
    rejected = 0
    for i, batch in enumerate(batches):
        out_path = analyst_batch_path(i)
        if out_path.exists():
            existing = read_text(out_path).strip()
            if existing.startswith("<<SKIP"):
                rejected += 1
                continue
            if len(existing) > 50 and not is_rejection_text(existing):
                done += 1
                continue
        wait_if_paused(f"[analyst] MAP 第 {i+1}/{len(batches)} 批前")
        if STOP_FILE.exists():
            cli_print("[analyst] 检测到停止请求，已跑的批已落盘，重跑会续上。")
            return
        cli_print(f"[analyst] MAP {i+1}/{len(batches)} 批，输入≈{estimate_tokens(batch)} tokens")
        result = ""
        ok = False
        for attempt in range(3):
            try:
                result = call_model("analyst", map_prompt, batch, role_max_output_tokens("analyst", 7000), timeout)
            except Exception as exc:  # noqa: BLE001
                cli_print(f"[analyst] 第 {i+1} 批调用异常(第{attempt+1}/3次)：{exc}")
                time.sleep(min(5 * (attempt + 1), 20))
                continue
            if is_rejection_text(result):
                cli_print(f"[analyst] 第 {i+1} 批被风控拒(第{attempt+1}/3次)：{result.strip()[:60]}")
                time.sleep(min(5 * (attempt + 1), 20))
                continue
            ok = True
            break
        if ok:
            write_text(out_path, result)
            done += 1
        else:
            # 拒绝是确定性的(源文该段内容触发),不再无限重试:标记跳过,不喂进归并
            write_text(out_path, "<<SKIP: 本批被内容风控拒绝，已跳过，不参与归并>>")
            rejected += 1
            cli_print(f"[analyst] 第 {i+1} 批两次失败/被拒,已标记跳过。")

    if rejected:
        cli_print(f"[analyst] 注意：{rejected}/{len(batches)} 批被风控跳过(玄幻打斗/死亡段易触发)。手法高度冗余,丢几批不致命。")

    # ---- REDUCE：分层归并,任何环节都不把全部批堆给模型 ----
    observations = []
    for i in range(len(batches)):
        p = analyst_batch_path(i)
        if p.exists():
            content = read_text(p).strip()
            if content and not content.startswith("<<SKIP") and not is_rejection_text(content):
                observations.append(content)
    if not observations:
        cli_print("[analyst] 没有可归并的 MAP 结果。")
        return
    merge_prompt = read_text(PROMPTS_DIR / "analyst_merge.md")
    group_size = int((run_cfg.get("analyst") or {}).get("merge_group_size") or 10)
    reduce_out = hierarchical_reduce(
        observations, merge_prompt, reduce_prompt, group_size, batch_budget, timeout
    )
    write_text(ANALYST_DIR / "_reduce_output.md", reduce_out)
    written = split_and_write_technique_chunks(reduce_out)
    cli_print(f"[analyst] 完成。写入手法 chunk：{', '.join(written) if written else '（无,检查 _reduce_output.md 分隔符）'}")
    cli_print("[analyst] chunk 已登记 index.json，写手检索表已预接好关键词。")


def hierarchical_reduce(
    observations: List[str],
    merge_prompt: str,
    reduce_prompt: str,
    group_size: int,
    batch_budget: int,
    timeout: int,
) -> str:
    """分层归并:把观察按 token 预算打包成组,每组合并成一份中间稿,反复合并到能一次喂下,
    再做最终归并。任何一次调用的输入都不超过 batch_budget,绝不把全部观察堆给模型。
    中间稿落盘 runtime/analyst/merge_LN_GN.md,断点续跑可复用。"""
    # 单次合并输入预算:留足 system prompt 和模型输出余量,取 batch_budget 的 0.7
    merge_input_budget = max(4000, int(batch_budget * 0.7))

    def pack_groups(items: List[str]) -> List[List[str]]:
        groups: List[List[str]] = []
        cur: List[str] = []
        cur_tok = 0
        for it in items:
            t = estimate_tokens(it)
            # 单份就超预算时也得自成一组(模型会自己截,但至少不和别人叠加)
            if cur and (cur_tok + t > merge_input_budget or len(cur) >= group_size):
                groups.append(cur)
                cur, cur_tok = [], 0
            cur.append(it)
            cur_tok += t
        if cur:
            groups.append(cur)
        return groups

    level = 0
    layer = list(observations)
    while len(pack_groups(layer)) > 1:
        level += 1
        groups = pack_groups(layer)
        cli_print(f"[analyst] MERGE 第 {level} 层：{len(layer)} 份 → {len(groups)} 组（每组≤{merge_input_budget} tokens）")
        next_layer: List[str] = []
        for gi, group in enumerate(groups):
            cache = ANALYST_DIR / f"merge_L{level}_G{gi:03d}.md"
            if cache.exists() and len(read_text(cache).strip()) > 50:
                next_layer.append(read_text(cache))
                continue
            wait_if_paused(f"[analyst] MERGE L{level} G{gi+1}/{len(groups)} 前")
            if STOP_FILE.exists():
                cli_print("[analyst] 停止请求；已合并的组已落盘,重跑续上。")
                raise KeyboardInterrupt("analyst stopped during merge")
            merged_in = "\n\n=== 下一份 ===\n".join(group)
            merged = call_model("analyst", merge_prompt, merged_in, role_max_output_tokens("analyst", 7000), timeout)
            write_text(cache, merged)
            next_layer.append(merged)
        layer = next_layer

    final_in = "\n\n=== 下一份 ===\n".join(layer)
    cli_print(f"[analyst] REDUCE 最终归并：{len(layer)} 份,输入≈{estimate_tokens(final_in)} tokens")
    return call_model("analyst", reduce_prompt, final_in, role_max_output_tokens("analyst", 7000), timeout)


def scan_chunk_for_contamination(body: str) -> List[str]:
    """扫手法卡是否漏进了源文专名/作者旁白污染。命中只警告不阻断,留给人工核。
    源文专名从 分析草稿/style_metrics.json 的高频词里取(出现≥80次且像名字的词)。
    作者旁白污染:把'作者和读者场外互动'当成可模仿手法,这是明确禁止的。"""
    hits: List[str] = []
    metrics = load_json(BASE_DIR / "分析草稿" / "style_metrics.json")
    freq = (metrics or {}).get("high_freq_words") or []
    # 取高频里像专名的(2-4字、非常见虚词),作为污染探针
    stop = {"什么", "这时", "起来", "一声", "点头", "于是", "不过", "然而", "很快",
            "出来", "过来", "下来", "一下", "来了", "事情", "口气", "的人", "一笑",
            "说道", "了笑", "这时候", "的时候", "起头", "一口气"}
    probes = []
    for item in freq:
        if isinstance(item, list) and len(item) == 2:
            w, c = item
            if isinstance(w, str) and isinstance(c, int) and c >= 80 and 2 <= len(w) <= 4 and w not in stop:
                # 去掉粘连主角名的(如"李平安和"),只留纯名字部分由模型判断,这里粗筛
                probes.append(w)
    for p in probes:
        if p in body:
            hits.append(p)
    # 作者旁白污染探针:这类词出现说明把"作者与读者场外互动"当成了手法
    aside_markers = ["作者与读者", "场外互动", "作者身份", "读者互动", "个人近况",
                     "作者第一人称", "作者口吻", "催更", "求票", "分享近况"]
    for m in aside_markers:
        if m in body:
            hits.append(f"[作者旁白:{m}]")
    return sorted(set(hits))


def split_and_write_technique_chunks(reduce_text: str) -> List[str]:
    """把 REDUCE 输出按 `=== FILE: chunk_xxx.md ===` 切成文件,写进 chunks/ 并登记 index.json。
    写入前扫一遍污染(源文专名),命中则警告——手法卡绝不该出现源文专名或原句。"""
    blocks = re.split(r"===\s*FILE:\s*(chunk_[^\s=]+\.md)\s*===", reduce_text)
    written: List[str] = []
    if len(blocks) < 3:
        return written
    index = load_index() or {}
    it = iter(blocks[1:])
    for fname, content in zip(it, it):
        fname = fname.strip()
        body = content.strip()
        if not body:
            continue
        contam = scan_chunk_for_contamination(body)
        if contam:
            cli_print(f"[analyst] ⚠ {fname} 疑似含源文专名:{', '.join(contam)} —— 已写入但请人工核查删除!")
        (CHUNKS_DIR / fname).write_text(body, encoding="utf-8")
        key = fname[len("chunk_"):-len(".md")] if fname.startswith("chunk_") and fname.endswith(".md") else fname
        index[key] = {"file": fname, "tokens": estimate_tokens(body), "category": "手法"}
        written.append(fname)
    if written:
        dump_json(CHUNKS_DIR / "index.json", index)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="端到端小说流水线（API版）")
    parser.add_argument("--config", help="运行配置 JSON，默认 config/run.json")
    parser.add_argument("--chapter", type=int, help="覆盖 run.json 的 start_chapter")
    parser.add_argument("--count", type=int, help="覆盖 run.json 的 chapter_count")
    parser.add_argument("--beat", help="覆盖 run.json 的 beat_template，仅生成单章时使用")
    parser.add_argument("--dry-run", action="store_true", help="只生成 writer prompt，不调用 API")
    parser.add_argument("--analyst", action="store_true", help="一次性：全量扫读源文,提炼手法 chunk（开新书时跑一次,配 --dry-run 只搭管线不烧 API）")
    parser.add_argument("--outline", action="store_true", help="一次性：生成全书骨架（开新书时跑一次）")
    parser.add_argument("--no-cli", action="store_true", help="减少终端提示")
    args = parser.parse_args()

    run_cfg = load_run_config(args.config)
    if args.dry_run:
        run_cfg["dry_run"] = True

    if args.analyst:
        acquire_lock()
        try:
            run_analyst(run_cfg, dry_run=bool(args.dry_run))
        except KeyboardInterrupt as exc:
            cli_print(f"[analyst] 已停止：{exc}（已完成的批/中间稿已落盘，重跑会续上）")
        finally:
            release_lock()
        return
    if getattr(args, "outline", False):
        acquire_lock()
        try:
            generate_master_outline(run_cfg, dry_run=bool(args.dry_run))
        finally:
            release_lock()
        return
    if args.count is not None:
        run_cfg["chapter_count"] = args.count
        run_cfg["max_chapters_per_run"] = max(int(run_cfg.get("max_chapters_per_run") or 1), args.count)

    acquire_lock()
    try:
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        recover_state_from_completed_articles(run_cfg)
        start_chapter = determine_start_chapter(args.chapter, run_cfg)
        chapter_count = int(run_cfg.get("chapter_count") or 1)
        max_per_run = int(run_cfg.get("max_chapters_per_run") or 1)
        # 通宵跑:不再硬卡 5 章。上限由 run.json 的 max_chapters_per_run 决定(默认放开到很大)。
        chapter_count = max(1, min(chapter_count, max_per_run))
        if args.beat:
            run_cfg["beat_template"] = args.beat
            chapter_count = 1
        # 小说强顺序:某章重试仍失败就"停在该章",绝不跳过、绝不前进。
        # 跳过会让后续章建在缺失记忆的地基上,且正文/台账文件已动态改动,无从 debug。
        # 修复后重跑会从断点(该章)自动续上(正文超前于 latest_chapter 时先补台账)。
        per_chapter_retries = int(run_cfg.get("per_chapter_retries") or 2)
        retry_backoff = float(run_cfg.get("retry_backoff_seconds") or 30)
        completed = 0
        cli_print("小说自动流水线已启动。按 p 请求暂停/继续，按 q 请求停止；也可创建 runtime/pause.request 暂停。")
        cli_print(f"计划章节：从第 {start_chapter} 章开始，共 {chapter_count} 章。")
        for offset in range(chapter_count):
            chapter = start_chapter + offset
            chapter_index = offset + 1
            wait_if_paused(f"第 {chapter} 章开始前")
            if STOP_FILE.exists():
                cli_print("检测到停止请求，退出。")
                break
            timeout = int(run_cfg.get("request_timeout_seconds") or 240)
            # 单章用重试+退避包裹:一次网络抖动不该让整夜任务全死。
            chapter_ok = False
            last_error = ""
            for attempt in range(1, per_chapter_retries + 1):
                try:
                    # 卷纲规划:卷纲快用完时自动生成下一卷(不停不等,全自动)
                    if attempt == 1 and needs_volume_planning(chapter):
                        run_volume_planner(chapter, run_cfg, timeout)
                    if attempt == 1:
                        run_story_director(chapter, run_cfg, timeout)
                    # 弧线规划:没有活跃弧线或弧线即将用完时,先规划新弧线再生成 beat
                    if attempt == 1 and needs_arc_planning(chapter):
                        run_arc_planner(chapter, run_cfg, timeout)
                    beat_path = resolve_beat_path(chapter, run_cfg)
                    if not beat_path.exists():
                        started = stage_start(chapter, "beat_planner", "生成 beat", 0, 7, chapter_index, chapter_count)
                    else:
                        started = None
                    ready_beat_path = ensure_beat(chapter, beat_path, run_cfg, timeout)
                    if started:
                        stage_done(chapter, "beat_planner", "生成 beat", 0, 7, started)
                    if ready_beat_path is None:
                        if run_cfg.get("dry_run"):
                            chapter_ok = True  # dry-run 下 beat 无需 API，是正常空操作
                            break
                        raise RuntimeError("beat 生成失败")
                    run_one_chapter(chapter, ready_beat_path, run_cfg, chapter_index, chapter_count)
                    chapter_ok = True
                    break
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    cli_print(f"第 {chapter} 章第 {attempt}/{per_chapter_retries} 次尝试失败：{exc}")
                    write_progress({"status": "chapter_error", "chapter": chapter, "attempt": attempt, "reason": str(exc)})
                    if attempt < per_chapter_retries and not STOP_FILE.exists():
                        wait = retry_backoff * attempt
                        cli_print(f"第 {chapter} 章 {wait:.0f}s 后重试…")
                        time.sleep(wait)
            if not chapter_ok:
                # 强顺序:停在本章,不前进。正文若已落盘,重跑时 recover 会先补台账。
                cli_print(
                    f"第 {chapter} 章重试 {per_chapter_retries} 次仍失败，停机（不跳过）。"
                    f"原因：{last_error}。修复后重跑会从第 {chapter} 章续上。"
                )
                write_progress({"status": "halted_on_chapter", "chapter": chapter, "reason": last_error})
                break
            completed += 1
        else:
            write_progress({"status": "finished", "completed": completed})
        cli_print(f"流水线结束，本次完成 {completed} 章。")
    except KeyboardInterrupt as exc:
        write_progress({"status": "stopped", "reason": str(exc)})
        cli_print(f"已停止：{exc}")
    finally:
        release_lock()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
