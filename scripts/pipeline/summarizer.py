# -*- coding: utf-8 -*-
"""pipeline.summarizer — 写手摘要系统。

每章定稿后生成一份结构化摘要，记录本章使用的动作/句式/意象/情绪手段。
后续 writer 和 reviewer 读取最近N章摘要，避免表达重复。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    RUNTIME_DIR, cli_print, dump_json, load_json, read_text, manuscript_path,
)

SUMMARIES_DIR = RUNTIME_DIR / "summaries"

SUMMARIZER_PROMPT = (
    "你是写作日志员。读完一章定稿后，提取以下信息，输出纯 JSON（无围栏无解释）：\n"
    "{\n"
    '  "chapter": 章节号(int),\n'
    '  "signature_actions": 本章独特的动作描写，最多5条(string[]),\n'
    '  "recurring_verbs": 每个出场角色使用频率最高的动词，每人最多6个({角色名: string[]}),\n'
    '  "sentence_patterns": 本章反复使用的句式模板，如"X没Y""一X。两X。"，最多5条(string[]),\n'
    '  "imagery_used": 比喻/通感意象，最多5条(string[]),\n'
    '  "emotional_moves": 情绪推进手段，最多3条(string[]),\n'
    '  "plot_digest": 一句话概括本章事件(string)\n'
    "}\n"
    "不要评价好坏，只记录事实。不要输出 JSON 以外的任何内容。"
)

def summary_path(chapter: int) -> Path:
    return SUMMARIES_DIR / f"chapter_{chapter:03d}.json"


def generate_chapter_summary(
    chapter: int, final_text: str, timeout: int = 120
) -> Dict[str, Any]:
    """调用 LLM 为一章定稿生成写手摘要，落盘并返回。"""
    from pipeline.api import call_role

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    user_input = f"以下是第{chapter}章定稿正文，请提取写作日志：\n\n{final_text}"
    raw = call_role(
        "summarizer",
        SUMMARIZER_PROMPT,
        user_input,
        SUMMARIES_DIR / f"_raw_{chapter:03d}.txt",
        timeout,
        1500,
    )

    data = _parse_summary(raw, chapter)
    dump_json(summary_path(chapter), data)
    # 清理原始输出文件
    raw_path = SUMMARIES_DIR / f"_raw_{chapter:03d}.txt"
    if raw_path.exists():
        raw_path.unlink()
    return data


def _parse_summary(raw: str, chapter: int) -> Dict[str, Any]:
    """从 LLM 输出中提取 JSON。容错：去围栏、尾逗号。"""
    text = raw.strip()
    # 去 markdown 围栏
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        # 找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

    # 去尾逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        cli_print(f"[summarizer] 第{chapter}章摘要 JSON 解析失败，使用空摘要。")
        data = {}

    data.setdefault("chapter", chapter)
    data.setdefault("signature_actions", [])
    data.setdefault("recurring_verbs", {})
    data.setdefault("sentence_patterns", [])
    data.setdefault("imagery_used", [])
    data.setdefault("emotional_moves", [])
    data.setdefault("plot_digest", "")
    return data


def load_summary(chapter: int) -> Optional[Dict[str, Any]]:
    """读取单章摘要，不存在返回 None。"""
    p = summary_path(chapter)
    if not p.exists():
        return None
    return load_json(p, {})


def load_recent_summaries(chapter: int, lookback: int = 5) -> List[Dict[str, Any]]:
    """读取最近 lookback 章的摘要（不含当前章）。"""
    results = []
    for ch in range(max(1, chapter - lookback), chapter):
        s = load_summary(ch)
        if s:
            results.append(s)
    return results


def anti_repeat_for_writer(chapter: int, lookback: int = 5) -> str:
    """生成给 writer 的防重复注入文本。基于最近N章摘要。"""
    summaries = load_recent_summaries(chapter, lookback)
    if not summaries:
        return ""

    patterns_seen: List[str] = []
    verbs_by_char: Dict[str, List[str]] = {}
    actions_seen: List[str] = []

    for s in summaries:
        patterns_seen.extend(s.get("sentence_patterns") or [])
        actions_seen.extend(s.get("signature_actions") or [])
        for char, verbs in (s.get("recurring_verbs") or {}).items():
            verbs_by_char.setdefault(char, []).extend(verbs)

    lines: List[str] = []

    # 句式模板：出现2次以上的才警告
    from collections import Counter
    pat_counts = Counter(patterns_seen)
    overused_pats = [p for p, c in pat_counts.items() if c >= 2]
    if overused_pats:
        lines.append("【近5章高频句式·本章禁用或限用1次】")
        for p in overused_pats[:6]:
            lines.append(f"  - {p}（近{pat_counts[p]}章使用）")

    # 角色动词：出现3次以上的
    for char, verbs in verbs_by_char.items():
        verb_counts = Counter(verbs)
        overused = [v for v, c in verb_counts.items() if c >= 3]
        if overused:
            lines.append(f"【{char}·近5章高频动词·换别的】{'、'.join(overused[:5])}")

    # 最近2章的独特动作（避免连续章节重复同一个标志性画面）
    recent_actions = []
    for s in summaries[-2:]:
        recent_actions.extend(s.get("signature_actions") or [])
    if recent_actions:
        lines.append("【前2章已用动作·本章不要重复】")
        for a in recent_actions[:6]:
            lines.append(f"  - {a}")

    if not lines:
        return ""
    lines.insert(0, "以下是基于最近章节摘要的防重复提醒：")
    lines.append("替代方案：换感官通道、换肢体部位、换节奏结构、或直接留白。")
    return "\n".join(lines)


def repetition_context_for_reviewer(chapter: int, lookback: int = 5) -> str:
    """生成给 reviewer 的重复检测参考。"""
    summaries = load_recent_summaries(chapter, lookback)
    if not summaries:
        return ""

    lines = ["以下是最近章节的写作摘要，评审时请注意新章是否重复了这些表达："]
    for s in summaries[-3:]:
        ch = s.get("chapter", "?")
        pats = s.get("sentence_patterns") or []
        acts = s.get("signature_actions") or []
        digest = s.get("plot_digest", "")
        lines.append(f"\n第{ch}章：{digest}")
        if pats:
            lines.append(f"  句式：{'；'.join(pats[:3])}")
        if acts:
            lines.append(f"  动作：{'；'.join(acts[:3])}")

    return "\n".join(lines)
