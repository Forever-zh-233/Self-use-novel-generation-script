# -*- coding: utf-8 -*-
"""pipeline.state — state/ledger load/save/render/defaults."""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    BASE_DIR, CHUNKS_DIR, CONFIG_DIR, RUNTIME_DIR,
    STATE_FILE, ACTIVE_THREADS_FILE, STATE_MD_FILE, ACTIVE_THREADS_MD_FILE,
    VOLUME_SUMMARY_FILE, LEDGER_FILE, ACTIVE_ARCS_FILE,
    STORY_DIRECTOR_FILE, STORY_DIRECTOR_MD_FILE, VERSION_DIR,
    VOLUME_DIGESTS_FILE, CLIMAX_TENSIONS,
    read_text, write_text, load_json, dump_json,
)


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


def _trim_state_for_context(state: Dict[str, Any], chapter: int = 0) -> Dict[str, Any]:
    """裁剪 state 给上下文用。按活跃度分层，确保到800章也不爆。"""
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
    if isinstance(s.get("used_devices"), list):
        s["used_devices"] = s["used_devices"][-20:]
    if chapter and isinstance(s.get("characters"), dict):
        trimmed_chars = {}
        for name, data in s["characters"].items():
            if not isinstance(data, dict):
                continue
            last_active = int(data.get("_last_active") or 0)
            gap = (chapter - last_active) if last_active else 0
            if gap <= 10:
                trimmed_chars[name] = data
            elif gap <= 30:
                trimmed_chars[name] = {
                    k: v for k, v in data.items()
                    if k in ("status", "location", "realm", "faction", "_last_active")
                }
        s["characters"] = trimmed_chars
    if chapter and isinstance(s.get("relationships"), dict):
        active_chars = set(s.get("characters", {}).keys())
        trimmed_rels = {}
        for pair, data in s["relationships"].items():
            members = [m.strip() for m in re.split(r"[-—~、,，]", pair)]
            if any(m in active_chars for m in members):
                trimmed_rels[pair] = data
        s["relationships"] = trimmed_rels
    return s


def structured_state_text(chapter: int = 0) -> str:
    state = _trim_state_for_context(load_state(), chapter)
    threads = load_active_threads()
    fs = threads.get("foreshadowing")
    if isinstance(fs, dict):
        unresolved = {k: v for k, v in fs.items()
                      if not (isinstance(v, dict) and (v.get("status") in ("已回收", "已结") or v.get("resolved_chapter")))}
        threads = {**threads, "foreshadowing": unresolved}
    summary = read_text(VOLUME_SUMMARY_FILE, "")

    lines: List[str] = []
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
    if summary.strip():
        parts.append("## volume_summary.md\n" + summary)
    return "\n\n".join(parts)


def structured_state_for_planner(chapter: int) -> str:
    """规划层专用状态视图：角色只给一行摘要，不给 knowledge/emotion/facts。"""
    raw_state = load_state()
    lines: List[str] = []

    tl = raw_state.get("timeline") or {}
    if tl:
        lines.append(f"【时间线】第{tl.get('absolute_day', '?')}日·{tl.get('time_of_day', '?')}·{tl.get('season', '?')}")
        timers = tl.get("pending_timers") or []
        urgent = [t for t in timers if t.get("urgency") in ("极高", "高")]
        for t in urgent[:3]:
            lines.append(f"  ⚠ {t.get('event','')}（截止第{t.get('due_day','?')}日）")

    chars = raw_state.get("characters") or {}
    active_names = []
    char_lines = []
    for name, data in chars.items():
        if not isinstance(data, dict):
            continue
        last_active = int(data.get("_last_active") or 0)
        gap = (chapter - last_active) if last_active else 0
        if gap > 30:
            continue
        active_names.append(name)
        loc = data.get("location", "?")
        status = data.get("status", "?")
        realm = f"·{data['realm']}" if data.get("realm") else ""
        char_lines.append(f"  {name}（{status}）{realm} @ {loc}")
    if char_lines:
        lines.append(f"【在场角色·{len(char_lines)}人】")
        lines.extend(char_lines)

    events = raw_state.get("recent_events") or []
    if events:
        lines.append("【近期事件】")
        for e in events[-6:]:
            lines.append(f"  - {e}")

    strand = raw_state.get("strand_tracker") or {}
    if strand.get("history"):
        recent_strands = strand["history"][-5:]
        strand_str = "、".join(f"第{s.get('chapter','?')}章={s.get('strand','?')}" for s in recent_strands)
        lines.append(f"【三线节奏】{strand_str}")

    threads = load_active_threads()
    fs = threads.get("foreshadowing")
    if isinstance(fs, dict):
        unresolved = {k: v for k, v in fs.items()
                      if isinstance(v, dict) and v.get("status") not in ("已回收", "已结") and not v.get("resolved_chapter")}
        if unresolved:
            lines.append(f"【悬空伏笔·{len(unresolved)}条】")
            for fid, fv in list(unresolved.items())[:10]:
                deadline = fv.get("resolve_by") or fv.get("deadline") or "?"
                lines.append(f"  {fid}: {fv.get('hint', fv.get('content', ''))[:30]}（截止{deadline}）")

    return "\n".join(lines)


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


# ──────────────────────────────────────────────────────────────────────
# 三线节奏(Strand Weave)。机制思路抄自竞品,按本书玄幻长生内核重定义为
# 道途/情义/天地三线。阈值全在 config/strand_weave.json,代码不写死配比。
# 关键:"本章主导哪条线"由 archivist(LLM)打 dominant_strand 标签,代码只
# 维护计数器、比配比、报断档——零文风/剧情硬编码,符合反 gaming 原则。
# ──────────────────────────────────────────────────────────────────────
def load_strand_config() -> Dict[str, Any]:
    return load_json(CONFIG_DIR / "strand_weave.json", {}) or {}


def normalize_strand(label: Any) -> str:
    """把 archivist 给的标签(可能用别名)归一到三条正式线名之一。无法归类返回 ''。"""
    if not label:
        return ""
    text = str(label).strip()
    cfg = load_strand_config()
    strands = cfg.get("strands") or {}
    for canon, info in strands.items():
        if text == canon:
            return canon
        for alias in (info.get("aliases") or []):
            if alias and alias in text:
                return canon
    # 兜底:正式名直接子串命中
    for canon in strands.keys():
        if canon in text:
            return canon
    return ""


def update_strand_tracker(state: Dict[str, Any], chapter: int, dominant: str) -> None:
    """把本章 dominant_strand 记进 state['strand_tracker']。dominant 已归一化。
    无法识别的标签不污染计数器(只记 history,不更新 last_*),保证崩溃重建安全。"""
    if not dominant:
        return
    tracker = state.setdefault("strand_tracker", {})
    history = tracker.setdefault("history", [])
    # 去重:同章重复提交只保留最后一次(崩溃重建可能重跑本章)
    history[:] = [h for h in history if int(h.get("chapter", -1)) != chapter]
    history.append({"chapter": chapter, "dominant": dominant})
    history.sort(key=lambda h: int(h.get("chapter", 0)))
    tracker["history"] = history[-60:]  # 有界:只留最近 60 章
    key_map = {"道途线": "last_道途", "情义线": "last_情义", "天地线": "last_天地"}
    field = key_map.get(dominant)
    if field:
        tracker[field] = chapter
    prev_dominant = tracker.get("current_dominant")
    if prev_dominant == dominant:
        tracker["consecutive"] = int(tracker.get("consecutive") or 0) + 1
    else:
        tracker["consecutive"] = 1
    tracker["current_dominant"] = dominant


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


def volume_summary(chapter: int) -> str:
    """给卷纲规划师的发展历程:全书卷摘要(远期) + 上一卷详细弧线(近期)。"""
    parts = []
    digests = load_json(VOLUME_DIGESTS_FILE, {"volumes": []})
    if digests.get("volumes"):
        parts.append("## 全书发展历程")
        for i, vol in enumerate(digests["volumes"], 1):
            ch = vol.get("volume_end_chapter", "?")
            parts.append(f"### 第{i}卷(截至第{ch}章)")
            parts.append(vol.get("digest", "(无摘要)"))
            parts.append("")
    arc_history_file = RUNTIME_DIR / "arc_history.json"
    if arc_history_file.exists():
        history = load_json(arc_history_file, {"volumes": []})
        volumes = history.get("volumes") or []
        if volumes:
            last_vol = volumes[-1]
            arcs = last_vol.get("arcs") or []
            if arcs:
                arc_lines = [f"## 上一卷弧线详情({len(arcs)}条)"]
                for arc in arcs:
                    arc_lines.append(f"**{arc.get('title','?')}**: {arc.get('summary','')[:120]}")
                    arc_lines.append(f"  收束条件: {arc.get('resolution_condition','')}")
                    for node in (arc.get("nodes") or []):
                        arc_lines.append(f"  第{node.get('chapter','?')}章[{node.get('tension','?')}]: {node.get('beat_hint','')[:60]}")
                    arc_lines.append("")
                parts.append("\n".join(arc_lines))
    if VERSION_DIR.exists():
        backups = sorted(VERSION_DIR.glob("卷纲_截至第*章.md"), key=lambda p: p.stat().st_mtime)
        if backups:
            old_plan = read_text(backups[-1])
            if old_plan.strip():
                parts.append(f"## 上一卷卷纲\n\n{old_plan[:2000]}")
    if not parts:
        return "(首卷,无历史回顾)"
    return "\n\n".join(parts)


def load_active_arcs() -> List[Dict[str, Any]]:
    data = load_json(ACTIVE_ARCS_FILE, {})
    arcs = data.get("arcs") if isinstance(data, dict) else data
    return arcs if isinstance(arcs, list) else []


def save_active_arcs(arcs: List[Dict[str, Any]]) -> None:
    dump_json(ACTIVE_ARCS_FILE, {"arcs": arcs})


