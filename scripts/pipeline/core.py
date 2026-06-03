# -*- coding: utf-8 -*-
"""pipeline.core — constants, paths, IO, progress, config."""

import json
import os
import re
import sys
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Path constants ───

BASE_DIR = Path(os.environ.get("NOVEL_WORKSPACE") or Path(__file__).resolve().parents[2])
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
SCORE_REPORT_DIR = OUTPUT_DIR / "分数表"
WRITER_MODULES_DIR = PROMPTS_DIR / "writer_modules"
VOLUME_DIGESTS_FILE = RUNTIME_DIR / "volume_summaries.json"
BEATS_DIR = BASE_DIR / "beats"
# beat 调试留档目录:每章一个子文件夹,存输入/原始输出/方向校验/归一化 beat。
# 【不在 cleanup_chapter_artifacts 的清理名单内】——artifact_retention=clean 也照样保留,
# 用于回溯"这一章 beat 当时被喂了什么、漏吸收了什么"。文件都是小文本,长跑也只占几 MB。
BEATS_DEBUG_DIR = BEATS_DIR / "_debug"

# ─── Shared non-path constants ───

REALM_ORDER = ["叩门", "通脉", "凝元", "开窍", "化神", "归真", "明心", "通玄", "听道", "御道", "齐物", "忘我"]
REALM_ORDINALS = ["第一境", "第二境", "第三境", "第四境", "第五境", "第六境",
                  "第七境", "第八境", "第九境", "第十境", "第十一境", "第十二境"]

CLIMAX_TENSIONS = ("高", "高潮", "爆")


def load_env_local() -> int:
    """启动时自动加载 BASE_DIR/.env.local 到 os.environ。
    API key 只存在 gitignored 的 .env.local,但 get_api_key 从环境变量读、不自动加载。
    没有它,每个新终端启动管线都得手动 `source .env.local`,忘了就 401。
    规则:① 文件不存在就静默跳过;② 已存在的环境变量优先,不覆盖(手动 export 仍可压过文件);
    ③ 解析 KEY=VALUE,跳过空行/注释行/无等号行;④ 去掉值两端引号;⑤ 绝不打印 key 值。
    返回新注入的变量个数。"""
    env_file = BASE_DIR / ".env.local"
    if not env_file.exists():
        return 0
    injected = 0
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            if not key or key in os.environ:  # 已设的不覆盖
                continue
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value
            injected += 1
    except OSError:
        return injected
    return injected


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


def beat_debug_dir(chapter: int) -> Path:
    """本章 beat 调试留档子目录(不受 cleanup 影响)。"""
    return BEATS_DEBUG_DIR / f"第{chapter:03d}章"


def write_beat_debug(chapter: int, files: Dict[str, str]) -> None:
    """把本章 beat 的调试料(输入/原始输出/方向校验/归一化 beat)写进留档目录。
    files: {文件名: 文本内容}。内容为空的项跳过。失败不影响正文生成。"""
    try:
        folder = beat_debug_dir(chapter)
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            if not content:
                continue
            write_text(folder / name, content)
    except OSError as exc:  # 留档失败不该拖垮正文
        cli_print(f"[beat_debug] 第{chapter}章调试留档写入失败（不影响正文）：{exc}")


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


def estimate_tokens(text: str) -> int:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    non_chinese_chars = max(0, len(text) - chinese_chars)
    return int(chinese_chars * 1.5 + non_chinese_chars / 4)


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def cli_print(message: str) -> None:
    try:
        print(f"[{now_text()}] {message}", flush=True)
    except UnicodeEncodeError:
        print(f"[{now_text()}] {message.encode('utf-8', errors='replace').decode('utf-8')}", flush=True)


def write_progress(data: Dict[str, Any]) -> None:
    payload = {
        **data,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    dump_json(PROGRESS_FILE, payload)


def progress_bar(done: int, total: int, width: int = 20) -> str:
    total = max(1, total)
    done = max(0, min(done, total))
    filled = int(width * done / total)
    pct = int(100 * done / total)
    return "=" * filled + "-" * (width - filled) + f" {pct}%"


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
    cli_print(f"章 {chapter} ({chapter_index}/{total_chapters}) {bar} │ {role}: {action}")
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
    cli_print(f"章 {chapter} {bar} │ {role} 完成 {elapsed:.1f}s")
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
    if sys.platform == "win32":
        # Windows 上 os.kill(pid, 0) 对不存在的 PID 会抛 WinError 87，且 CPython
        # 实现下冒泡成 SystemError 而非可捕获的 OSError——会让陈旧锁清理逻辑崩在启动阶段。
        # 改用 OpenProcess 探活：拿不到句柄(进程不存在/无权限)即视为未运行。
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                # 仍在运行的进程退出码为 STILL_ACTIVE；已退出但句柄残留则不是。
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
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


def extract_json_object(text: str) -> Dict[str, Any]:
    """从模型输出里提取第一个 JSON 对象,容错代码块包裹和 mimo 的未转义引号。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("模型没有返回 JSON 对象。")
    payload = stripped[start:end + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return json.loads(_sanitize_model_json(payload))


