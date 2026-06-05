# -*- coding: utf-8 -*-
"""pipeline.planning — story_director, volume, arc, beat planners."""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    BASE_DIR, OUTPUT_DIR, PROMPTS_DIR, RUNTIME_DIR,
    LEDGER_MD_FILE, MASTER_OUTLINE_FILE, VOLUME_PLAN_FILE, VERSION_DIR,
    LONG_FORESHADOWING_FILE, VOLUME_DIGESTS_FILE, CLIMAX_TENSIONS,
    cli_print, dump_json, load_json, manuscript_path, read_text,
    role_artifact, write_text, extract_json_object,
)
from pipeline.api import call_role
from pipeline.state import (
    load_active_arcs, load_ledger, load_state, load_story_director,
    render_story_director_markdown, save_active_arcs, save_story_director,
    structured_state_text, structured_state_for_planner, volume_summary, load_active_threads,
)
from pipeline.context import (
    compress_sections_if_needed, emotional_distribution_warnings,
    ledger_context_for_planner, long_foreshadowing_text, make_section,
    pacing_variety_warnings, recent_expectation_tail, recent_ledger_tail, render_sections,
    safe_cultivation_for_writer, strand_digest_for_director, strand_pacing_warnings,
    realm_progress_digest, planner_craft_chunks,
    spatial_digest_for_arc, layout_for_beat,
)


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

def recent_text_blob(chapter: int, lookback: int = 5, max_chars_per_chapter: int = 2200) -> str:
    """给 story_director 的最近章节摘要：用 state.json 的 recent_events + beat 标题，
    不注入原文。每章一行重点，总量极小。"""
    state = load_state()
    events = state.get("recent_events") or []
    # recent_events 是最近30条，取最近 lookback*3 条（每章约2-3条事件）
    relevant = events[-(lookback * 3):]
    if not relevant:
        return "(暂无近期事件记录)"
    lines = []
    for i, ev in enumerate(relevant):
        lines.append(f"- {ev}")
    return "最近发生的事（按时间顺序）：\n" + "\n".join(lines)


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


def story_director_prompt() -> str:
    return read_text(PROMPTS_DIR / "story_director.md") or (
        "你是故事总监。只输出 JSON。你的职责是防止小说偏离卷纲主类型。"
        "不要写正文,不要扩写剧情,只给未来3章的纠偏指令。"
    )


def obligations_due_digest(chapter: int, stale_threshold: int = 10) -> str:
    """给规划层看的『人物债账』到期摘要(债/承诺/因果——沈安欠的、还没兑现的)。
    与 threads(剧情线索)是两个维度:thread 问'这条线何时给读者交代',obligation 问
    '沈安何时兑现他的良心'。代码只算 chapter - since_chapter 报到期(纯计数零语义),
    该不该还、怎么还由规划师 LLM 判断剧情时机。软提示防 KPI 化。"""
    ledger = load_ledger()
    open_obs = [
        o for o in (ledger.get("obligations") or [])
        if isinstance(o, dict) and o.get("status") != "已结"
    ]
    if not open_obs:
        return ""
    lines = [f"【人物债账】悬空 {len(open_obs)} 笔(沈安欠的债/承诺/因果，还没兑现的)"]
    # 挂得越久越靠前,让规划师一眼看到老债
    for o in sorted(open_obs, key=lambda x: int(x.get("since_chapter") or chapter))[:12]:
        gap = chapter - int(o.get("since_chapter") or chapter)
        stale = f" ⚠已挂{gap}章" if gap >= stale_threshold else ""
        lines.append(f"- {o.get('id','')} {o.get('desc','')}（起于第{o.get('since_chapter','?')}章）{stale}")
    lines.append(
        "（有合适契机可考虑了结挂得久的债，没契机继续挂着也行——还债的时机、代价、方式"
        "比『还没还』本身更要紧。债的兑现往往是人物最重的戏，别为清账而清账。）"
    )
    return "\n".join(lines)


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
    # 人物债账并入(与剧情线索并列两本账,让 story_director 一处看全)
    obs_digest = obligations_due_digest(chapter)
    if obs_digest:
        lines.append("\n" + obs_digest)
    return "\n".join(lines).strip()



def _outline_digest_for_director() -> str:
    """从全书骨架 JSON 里只提取 story_director 需要的全局定位信息,
    从 13000+ token 压到几百 token。卷纲已给当前卷详细规划,骨架只补全局视野。"""
    raw = read_text(MASTER_OUTLINE_FILE)
    if not raw.strip():
        return "（全书骨架尚未生成）"
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return raw[:800] + "\n...(骨架过长已截断)"
    parts = []
    if data.get("core_arc"):
        parts.append(f"全书主线弧线：{data['core_arc']}")
    if data.get("ending"):
        parts.append(f"结局走向：{str(data['ending'])[:200]}")
    evol = data.get("world_evolution") or []
    if evol:
        parts.append("世界演变阶段：")
        for stage in evol:
            vols = stage.get("volumes", [])
            parts.append(f"  卷{'/'.join(str(v) for v in vols)}：{stage.get('summary','')}")
    return "\n".join(parts)


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
    # 全书骨架摘要:story_director 只需要全书主线定位 + 当前卷在全书中的位置,
    # 不需要 800 章的逐卷详细规划(那是 13000+ token,占满预算挤掉正文摘录和 beat 摘要)。
    # 卷纲已经给了当前卷的详细规划,骨架只补"全局视野"。
    outline_digest = _outline_digest_for_director()
    sections = [
        make_section("当前章节", f"第{chapter}章", "critical", False),
        make_section("任务", "请自由审核当前故事方向。不要依赖关键词打分,按卷纲兑现度、核心叙事模式(以故事核为准)、推进vs打转、重复模式、节奏冷热五个维度判断。默认放行,只在反复出现明确问题时纠偏。", "critical", False),
        make_section("故事核", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("全书骨架摘要(全局定位,详细规划见卷纲)", outline_digest, "high", True),
        make_section("卷纲", read_text(VOLUME_PLAN_FILE), "critical", False),
        make_section("当前活跃弧线", json.dumps(load_active_arcs(), ensure_ascii=False, indent=2), "high", True),
        make_section("期待账本", recent_expectation_tail(), "high", True),
        make_section("结构化当前状态", structured_state_text(), "high", True),
        make_section("线索与揭示台账", threads_digest_for_director(chapter) or "（暂无线索台账记录）", "high", True),
        make_section("三线节奏配比", strand_digest_for_director(chapter) or "（暂无三线记录）", "high", True),
        make_section("主角境界进度(停滞观察,定性参考)", realm_progress_digest(chapter), "high", True),
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


def long_foreshadowing_progress(chapter: int) -> str:
    """长线伏笔进度表:从 reveal_ledger + 长线伏笔资产库自动生成,
    告诉卷纲/弧线规划师每条长线伏笔当前揭到第几层、该不该在本卷推进。
    每条一行,几百 token,不爆预算。"""
    ledger = load_json(RUNTIME_DIR / "ledger.json", {})
    reveals = ledger.get("reveal_ledger") or []
    if not reveals:
        return ""
    lines = ["长线伏笔进度表（规划时参考,决定本卷/本弧该推进哪几条）:\n"]
    lines.append("| 主题 | 已揭层级 | 上次外显章 | 计划下次揭示 | 本卷建议 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in reveals:
        topic = r.get("topic", "?")
        level = r.get("revealed_level", 0)
        last_ch = r.get("last_reveal_chapter", "?")
        plan_next = r.get("plan_next_level_in", "未定")
        # 判断"本卷建议":如果 plan_next 包含当前卷的关键词,标"该推进"
        suggestion = "按计划推进" if any(k in str(plan_next) for k in ["本卷", "第一卷", "第二卷"]) else "不急/按骨架节奏"
        # 如果距上次外显超过 30 章,提醒别忘了
        gap = chapter - int(last_ch) if isinstance(last_ch, int) else 0
        if gap > 30:
            suggestion = f"⚠已{gap}章未外显,考虑推进"
        lines.append(f"| {topic} | 第{level}层 | 第{last_ch}章 | {plan_next} | {suggestion} |")
    lines.append("\n注:「该推进」不是必须本章就做,而是本卷内找合适时机安排。规划时在阶段表/弧线节点里标注即可。")
    return "\n".join(lines)


def impact_seeds_digest(chapter: int) -> str:
    """给 arc_planner 看 pending 的影响种子（POV 章候选）。"""
    ledger = load_ledger()
    seeds = [s for s in (ledger.get("impact_seeds") or []) if s.get("status") == "pending"]
    if not seeds:
        return ""
    lines = ["可部署的影响种子（按剧情需要挑选，不是每个都要用）："]
    for s in seeds:
        lines.append(f"- [{s.get('id','?')}] {s.get('who','?')}（第{s.get('from_chapter','?')}章）：{s.get('what','')}")
        dirs = s.get("directions") or []
        if dirs:
            lines.append(f"  方向：{'; '.join(dirs)}")
        lines.append(f"  建议窗口：{s.get('best_window', '未指定')}")
    return "\n".join(lines)


def overdue_foreshadowing_digest(chapter: int, long_term_only: bool = False) -> str:
    """从期待账本提取过期/临期伏笔，生成警告文本。
    long_term_only=True 时只筛选长线伏笔（给卷纲规划师）；
    False 时返回全部（给弧线规划师）。"""
    threads = load_active_threads()
    foreshadowing = threads.get("foreshadowing") or {}

    long_ids = set()
    if long_term_only:
        lf_text = read_text(LONG_FORESHADOWING_FILE)
        for m in re.findall(r"(LF-\d+|F-\d+)", lf_text):
            long_ids.add(m)

    overdue = []
    due_soon = []

    for fid, item in foreshadowing.items():
        if not isinstance(item, dict):
            continue
        status = item.get("status", "")
        if status in ("已回收", "已结"):
            continue
        if item.get("resolved_chapter"):
            continue
        if long_term_only and fid not in long_ids:
            continue
        planned = item.get("planned_resolution") or ""
        deadline_match = re.search(r"(\d+)", str(planned))
        if not deadline_match:
            continue
        deadline = int(deadline_match.group(1))
        if chapter > deadline:
            overdue.append((fid, item, chapter - deadline))
        elif chapter >= deadline - 3:
            due_soon.append((fid, item, deadline - chapter))

    if not overdue and not due_soon:
        return ""

    scope = "长线" if long_term_only else "全部"
    lines = []
    if overdue:
        lines.append(f"⚠ 已过期未回收的伏笔（{scope}，必须安排回收）：")
        for fid, item, gap in sorted(overdue, key=lambda x: -x[2]):
            desc = item.get("promise") or item.get("type") or fid
            lines.append(f"- [{fid}] {desc} — 过期{gap}章（埋设第{item.get('planted_chapter', '?')}章）")
    if due_soon:
        lines.append(f"⏰ 即将到期的伏笔（{scope}，本弧线/本卷内安排回收）：")
        for fid, item, remain in due_soon:
            desc = item.get("promise") or item.get("type") or fid
            lines.append(f"- [{fid}] {desc} — 还剩{remain}章")

    lines.append("")
    lines.append("回收要求：(1)回报值得等待 (2)有代价 (3)方式出乎意料。")
    lines.append("如果判断当前剧情确实不适合回收，必须写明延期理由并给出新 deadline——不能无视。")
    return "\n".join(lines)


VOLUME_DIGESTS_FILE = RUNTIME_DIR / "volume_summaries.json"


def _generate_volume_digest(chapter: int, old_arcs: List[Dict[str, Any]]) -> None:
    """卷纲切换时调 compressor 生成本卷发展摘要。"""
    outline_digest = _outline_digest_for_director()
    old_plan = ""
    if VERSION_DIR.exists():
        backups = sorted(VERSION_DIR.glob("卷纲_截至第*章.md"), key=lambda p: p.stat().st_mtime)
        if backups:
            old_plan = read_text(backups[-1])[:2000]
    arc_text = ""
    if old_arcs:
        arc_lines = []
        for a in old_arcs:
            arc_lines.append(f"{a.get('title','?')}: {a.get('summary','')[:100]}")
            for n in (a.get("nodes") or []):
                arc_lines.append(f"  第{n.get('chapter','?')}章: {n.get('beat_hint','')[:60]}")
        arc_text = "\n".join(arc_lines)
    char_arcs = ""
    arcs_file = RUNTIME_DIR / "character_arcs.md"
    if arcs_file.exists():
        char_arcs = read_text(arcs_file)[-1500:]
    input_parts = []
    if outline_digest:
        input_parts.append(f"## 全书方向\n{outline_digest[:500]}")
    if old_plan:
        input_parts.append(f"## 本卷卷纲\n{old_plan}")
    if arc_text:
        input_parts.append(f"## 本卷弧线\n{arc_text}")
    if char_arcs:
        input_parts.append(f"## 角色内在变化\n{char_arcs}")
    input_text = "\n\n".join(input_parts)
    prompt = (
        "你是摘要员。为刚结束的这一卷生成发展摘要,供下一卷规划师参考。\n"
        "要求:只记关键转折/不可逆变化/第一次;对照全书方向标注本卷推进到哪一步;\n"
        "角色只记内在转变;关系只记质变;标注必须接住的尾巴。200-300字。\n"
        "格式:卷结束章/本卷位置/关键转折/角色变化/关系质变/世界状态/必须接住的尾巴"
    )
    try:
        result = call_role(
            "compressor", prompt, input_text,
            RUNTIME_DIR / "volume_digest_raw.md", 240, 1000,
        )
    except Exception as exc:
        cli_print(f"[volume_digest] 摘要生成失败({exc})")
        result = f"卷结束章:第{chapter}章\n(摘要生成失败)"
    summaries = load_json(VOLUME_DIGESTS_FILE, {"volumes": []})
    summaries["volumes"].append({"volume_end_chapter": chapter, "digest": result.strip()})
    dump_json(VOLUME_DIGESTS_FILE, summaries)
    cli_print("[volume_planner] 本卷发展摘要已生成")


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
        make_section("期待账本(未回收伏笔)", recent_expectation_tail(), "high", True),
        make_section("长线伏笔资产库", read_text(LONG_FORESHADOWING_FILE), "high", True),
        make_section("长线伏笔进度表(本卷该推进哪几条)", long_foreshadowing_progress(chapter), "critical", False),
        make_section("上卷结构化回顾(承上启下的关键依据)", volume_summary(chapter), "high", False),
    ]
    growth_file = BASE_DIR / "config" / "growth_arcs.md"
    if growth_file.exists():
        sections.append(make_section("角色成长轨迹(本卷需展开成长里程碑)", read_text(growth_file), "high", True))
    # 长线伏笔过期警告（只看长线的）
    overdue_long = overdue_foreshadowing_digest(chapter, long_term_only=True)
    if overdue_long:
        sections.append(make_section(
            "⚠ 长线伏笔过期警告（本卷必须安排回收）",
            overdue_long,
            "critical", False,
        ))
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
    # 弧线存档:清空前把完整弧线数据追加到历史文件,供下次卷纲规划时回顾"上一卷实际走了什么"
    old_arcs = load_active_arcs()
    # === 生成本卷发展摘要(纯代码从结构化数据提取,不调 API) ===
    _generate_volume_digest(chapter, old_arcs)
    if old_arcs:
        arc_history_file = RUNTIME_DIR / "arc_history.json"
        history = load_json(arc_history_file, {"volumes": []})
        history["volumes"].append({
            "archived_at_chapter": chapter,
            "arcs": old_arcs,
        })
        dump_json(arc_history_file, history)
        cli_print(f"[volume_planner] 上一卷弧线已存档({len(old_arcs)}条) → arc_history.json")
    # 未收束的弧线(最后节点 > 当前章)保留到新卷,标记跨卷延续
    continuing = [a for a in old_arcs if a.get("nodes") and
                  max(int(n.get("chapter", 0) or 0) for n in a["nodes"]) > chapter]
    if continuing:
        for a in continuing:
            a["cross_volume"] = True
        save_active_arcs(continuing)
        cli_print(f"[volume_planner] {len(continuing)}条未收束弧线保留跨卷延续。")
    else:
        save_active_arcs([])
    cli_print("[volume_planner] 新卷纲已生成,arc_planner 会在需要时规划新弧线。")


# ========================= 弧线规划师(Arc Planner) =========================
# 管"3-10章的短线弧":副线起承转合、冲突酿到爆发、角色关系经几个节点建立。
# 不是每章都跑,只在没有活跃弧线或弧线即将收束时触发。

def in_climax_window(chapter: int, window: int = 1) -> bool:
    """本章是否落在某条活跃弧的『高潮节点章 ± window』窗口内。
    高潮节点 = arc_planner 给节点标的 tension 命中 CLIMAX_TENSIONS。
    这是『结构意图』层:arc 统筹几十章定的,不是单章自报,难通胀。
    注意:节点章号是计划值会漂移,所以这只用来圈一个『可能要爆』的窗口,
    真正『此刻是否爆』由 story_director 带实际正文进度实时确认(双签机制)。"""
    for arc in load_active_arcs():
        for n in arc.get("nodes") or []:
            tension = str(n.get("tension") or "")
            if not any(t in tension for t in CLIMAX_TENSIONS):
                continue
            node_ch = int(n.get("chapter", 0) or 0)
            if node_ch and abs(chapter - node_ch) <= window:
                return True
    return False


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


def recent_hooks_digest(chapter: int, lookback: int = 4) -> str:
    """给 beat_planner 看最近几章的章末钩子(型+内容)，并对重复做一级预警。
    钩子是单章职责，归 beat_planner 管——它必须看见前几章用了什么，才不会原地重复。
    检测两种重复：连续同型、连续指向同一对象。命中就给醒目警告，宁可平淡也别重复。"""
    items = []  # [(ch, 型, 钩子文本)]
    for ch in range(max(1, chapter - lookback), chapter):
        beat_path = BASE_DIR / "beats" / f"chapter_{ch}.json"
        if not beat_path.exists():
            continue
        beat = load_json(beat_path, {})
        hook = (beat.get("章末钩子") or "").strip()
        if not hook:
            continue
        htype = (beat.get("钩子型") or "未标").strip()
        items.append((ch, htype, hook))
    if not items:
        return ""
    lines = ["最近几章的章末钩子（本章必须换型或换指向，不要重复）："]
    for ch, htype, hook in items:
        lines.append(f"- 第{ch}章[{htype}]：{hook[:50]}")
    # —— 一级预警：连续同型 ——
    warnings = []
    types = [t for _, t, _ in items if t != "未标"]
    if len(types) >= 2 and types[-1] == types[-2]:
        run = 1
        for i in range(len(types) - 1, 0, -1):
            if types[i] == types[i - 1]:
                run += 1
            else:
                break
        warnings.append(f"⚠ 已连续 {run} 章用「{types[-1]}」型钩子。本章换一型。")
    # —— 一级预警：连续指向同一对象（取钩子里出现的高频名词性短语，做粗匹配）——
    if len(items) >= 2:
        recent_hooks = [h for _, _, h in items[-3:]]
        # 粗略共指检测：任意 2-4 字片段在最近多条钩子里反复出现
        from collections import Counter
        frag_counter: Counter = Counter()
        for h in recent_hooks:
            seen = set()
            for n in (3, 4):
                for i in range(len(h) - n + 1):
                    frag = h[i:i + n]
                    if frag not in seen and "，" not in frag and "。" not in frag:
                        seen.add(frag)
                        frag_counter[frag] += 1
        # 在最近钩子里出现 ≥2 次的片段视为重复指向（同一悬念被反复吊）
        repeated = [f for f, c in frag_counter.items() if c >= 2]
        # 过滤无意义虚词片段
        repeated = [f for f in repeated if not any(stop in f for stop in ("沈安", "黑子", "他", "的", "了", "在", "着", "一阵", "起来", "突然", "忽然"))]
        if repeated:
            # 取最长且包含信息量的片段作为代表
            longest = max(repeated, key=len)
            warnings.append(f"⚠ 最近多章钩子反复指向「{longest}」。本章换个指向，或宁可用平淡/留白收尾，也别再吊同一个东西。")
    if warnings:
        lines.append("")
        lines.extend(warnings)
    return "\n".join(lines)


def recent_scene_devices_digest(chapter: int, lookback: int = 10) -> str:
    """给 beat_planner 看最近 N 章反复出现的「场景结构 / 具体动作 / 具体物件」,
    专治"原地打转"——同一组装置(摸纸条、问人给断语、递东西…)被反复演而无人察觉。

    与 recent_hooks_digest(只看章末钩子)、pacing_variety_warnings(只数场景类型标签)互补:
    这里数的是 beat 里写实的「具体动作 + 具体物件 + 场景类型」三类装置在多章里的复发频次。
    代码只统计标签复发、不做语义猜测;命中阈值就醒目提示,beat_planner 自己判断要不要换。"""
    from collections import Counter
    items: List[tuple] = []  # [(ch, [装置标签...])]
    for ch in range(max(1, chapter - lookback), chapter):
        beat_path = BASE_DIR / "beats" / f"chapter_{ch}.json"
        if not beat_path.exists():
            continue
        beat = load_json(beat_path, {})
        tags: List[str] = []
        scene = str(beat.get("场景类型") or "").strip()
        if scene:
            tags.append(f"场景:{scene}")
        for act in (beat.get("具体动作") or []):
            a = str(act).strip()
            if a:
                tags.append(f"动作:{a}")
        for obj in (beat.get("具体物件") or []):
            o = str(obj).strip()
            if o:
                tags.append(f"物件:{o}")
        if tags:
            items.append((ch, tags))
    if len(items) < 3:
        return ""
    # 统计每个装置标签在多少不同章里出现(按章去重,避免同章重复计数)
    chap_count: Counter = Counter()
    last_chaps: Dict[str, List[int]] = {}
    for ch, tags in items:
        for t in set(tags):
            chap_count[t] += 1
            last_chaps.setdefault(t, []).append(ch)
    span = len(items)
    # 阈值:动作/物件类——10章窗里出现 ≥4 次,或近 5 章里 ≥3 次,判为"反复用同一招"
    flagged: List[tuple] = []  # (标签, 出现章数, 章号列表)
    for t, cnt in chap_count.items():
        chs = sorted(last_chaps[t])
        recent5 = [c for c in chs if c >= chapter - 5]
        if cnt >= max(4, span // 2) or len(recent5) >= 3:
            flagged.append((t, cnt, chs))
    if not flagged:
        return ""
    flagged.sort(key=lambda x: x[1], reverse=True)
    lines = [
        f"最近 {span} 章反复出现的场景装置(同一招连用是读者最敏感的『水章/原地打转』信号,本章换一种推进方式):",
    ]
    for t, cnt, chs in flagged[:6]:
        ch_str = "、".join(f"第{c}章" for c in chs[-6:])
        lines.append(f"⚠ 「{t}」已在 {cnt} 章出现({ch_str})。本章别再用它当主要手段。")
    return "\n".join(lines)


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


def _fmt_range(v: Any) -> str:
    """[3,8] → '3-8章';字符串原样;数字 → 'N章'。"""
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return f"{v[0]}-{v[1]}章"
    if isinstance(v, (int, float)):
        return f"{v}章"
    return str(v)


def structure_norms_digest(scope: str = "arc") -> str:
    """把 config/structure_norms.json 的"本书结构参考分布"格式化成可注入文本。
    这些数字是从本书原文(analyst 校准报告)数出的【参考分布,非 KPI】——换书时只换这个 JSON,
    arc_planner.md/beat_planner.md 的原理一字不改。文件不存在则返回空串(优雅跳过,不破坏未配置的书)。
    scope='arc' 给弧线规划师全量;scope='beat' 只给 beat_planner 它用得上的「呼吸cadence」。"""
    norms = load_json(BASE_DIR / "config" / "structure_norms.json")
    if not norms:
        return ""
    lines: List[str] = [
        "以下是从本书原文数出的结构【参考分布】(典型值,不是红线/KPI——别凑数字,按剧情自然需要,数字只供参考):"
    ]

    def emit_group(title: str, key: str) -> None:
        data = norms.get(key)
        if not isinstance(data, dict):
            return
        parts = []
        for k, v in data.items():
            if k.startswith("_"):  # 下划线开头是给人看的说明,不注入
                continue
            parts.append(f"{k}={_fmt_range(v)}")
        if parts:
            lines.append(f"- {title}:" + "; ".join(parts))

    if scope == "beat":
        emit_group("呼吸节奏 cadence", "呼吸cadence")
        body = "\n".join(lines)
        return body if len(lines) > 1 else ""

    # arc 全量
    emit_group("弧长分级(按类型)", "弧长分级章数")
    emit_group("节点间距(随进程)", "节点间距随进程章数")
    emit_group("伏笔回收窗口(按类型)", "伏笔回收窗口章数")
    emit_group("憋占比(按弧型)", "憋占比按弧型")
    emit_group("反差窗口", "反差窗口章数")
    emit_group("物件复现间距", "物件复现间距章数")
    emit_group("闭环率分布", "闭环率分布")
    emit_group("呼吸节奏 cadence", "呼吸cadence")
    body = "\n".join(lines)
    return body if len(lines) > 1 else ""


def build_arc_input(chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    growth_file = BASE_DIR / "config" / "growth_arcs.md"
    growth_text = read_text(growth_file) if growth_file.exists() else ""
    sections = [
        make_section("当前章节号", f"第{chapter}章,请从此章开始规划弧线节点。注意:弧线必须在卷纲当前阶段的范围内,不要跑到后面阶段去。", "critical", False),
        make_section("故事总监批注(方向参考，保持自然阅读感)", story_director_context(chapter), "critical", False),
        make_section("上一批弧线收束摘要(承上启下)", previous_arcs_summary(), "high", False),
        make_section("故事核", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("【硬约束】卷纲(弧线必须在此框架内,不可违背事件顺序和结局)", read_text(BASE_DIR / "卷纲" / "10-卷纲.md"), "critical", False),
        make_section("当前状态摘要", structured_state_for_planner(chapter), "high", True),
        make_section("正典账本摘要", ledger_context_for_planner(chapter), "high", True),
        make_section("期待账本(未回收伏笔)", recent_expectation_tail(), "normal", True),
        make_section("长线伏笔资产库(卷纲交代的长线伏笔全貌,你负责战术落地)", read_text(LONG_FORESHADOWING_FILE), "high", True),
        make_section("长线伏笔进度表(本弧该顺手推进哪几条)", long_foreshadowing_progress(chapter), "high", False),
        make_section("最近章节 beat 回顾", recent_beats_summary(chapter), "normal", True),
    ]
    if growth_text:
        sections.append(make_section("角色成长轨迹(规划弧线时标注本弧的成长阶段和心态变化)", growth_text, "high", True))
    # 本书结构参考分布(项目三 D:数字与原理分离,原理在 arc_planner.md,数字在 config/structure_norms.json)
    norms_text = structure_norms_digest("arc")
    if norms_text:
        sections.append(make_section("本书结构参考分布(弧长/节点间距/伏笔窗口/反差/物件/闭环——参考非KPI)", norms_text, "high", True))
    # 空间方位摘要（防穿帮·按需）：已登记地点的相对方位，规划场景群时遵守
    spatial = spatial_digest_for_arc(chapter)
    if spatial:
        sections.append(make_section("地点方位摘要(规划本弧场景群时遵守,别把地标方位写错)", spatial, "normal", True))
    # 过期伏笔警告（全部伏笔，含长线+短线）
    overdue_text = overdue_foreshadowing_digest(chapter, long_term_only=False)
    if overdue_text:
        sections.append(make_section(
            "⚠ 过期/临期伏笔警告（必须在本弧线安排回收）",
            overdue_text,
            "critical", False,
        ))
    # 影响种子（POV 章候选）
    seeds_text = impact_seeds_digest(chapter)
    if seeds_text:
        sections.append(make_section(
            "可部署的影响种子（POV 章候选，按需挑选）",
            seeds_text,
            "normal", True,
        ))
    # 三线配比给中期规划师:规划这一弧(几十章)时,决定该弧要补情义/天地,平衡道途独大
    strand_digest = strand_digest_for_director(chapter)
    if strand_digest:
        sections.append(make_section(
            "三线节奏配比(规划弧线时统筹道途/情义/天地的平衡)",
            strand_digest,
            "normal", True,
        ))
    # 主角境界进度(停滞观察):规划本弧修炼线时参考,决定该不该安排实质推进
    realm_digest = realm_progress_digest(chapter)
    if realm_digest:
        sections.append(make_section(
            "主角境界进度(规划修炼线时参考,停滞观察非KPI)",
            realm_digest,
            "normal", True,
        ))
    # 原书编织手法卡(C 阶段 analyst 产出后才有,存在才注入):多视角/三线/修炼/配角
    craft = planner_craft_chunks()
    if craft:
        sections.append(make_section(
            "原书编织手法(借鉴其切视角/编三线/写修炼/塑配角的做法,非套公式)",
            craft,
            "normal", True,
        ))
    # 人物债账到期:规划整条弧(几十章)时,把挂久的老债编进弧线节点了结
    obs_due = obligations_due_digest(chapter)
    if obs_due:
        sections.append(make_section(
            "人物债账·到期参考(规划弧线时,把挂久的老债安排进合适节点了结)",
            obs_due,
            "normal", True,
        ))
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
        10000,  # 放宽:弧线现在带 pacing_shape + approach_to_next + chapter_drift(逐章走向)走向,内容更长;arc_planner 非每章跑,放宽无每章成本
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
    """格式化当前活跃弧线给 beat_planner 看:展示当前所处区段的走向(approach_to_next)
    + 进度定位(距下个节点几章),让 beat_planner 顺着走向细化本章,不跑偏不打转。"""
    arcs = load_active_arcs()
    if not arcs:
        return ""
    lines = ["以下是当前活跃的短线弧。你要顺着弧线的『走向』细化本章,既不能跳步抢节点,也不能原地打转——你在为某个节点做铺垫,要朝那个方向推进:"]
    for arc in arcs:
        nodes = arc.get("nodes") or []
        if not nodes:
            continue
        # 找出当前章落在哪两个节点之间(所处区段)
        sorted_nodes = sorted(nodes, key=lambda n: int(n.get("chapter", 0) or 0))
        prev_node = None
        next_node = None
        for n in sorted_nodes:
            nch = int(n.get("chapter", 0) or 0)
            if nch <= chapter:
                prev_node = n
            elif next_node is None:
                next_node = n
        relevant = [n for n in sorted_nodes if int(n.get("chapter", 0) or 0) >= chapter - 1]
        if not relevant and not prev_node:
            continue
        lines.append(f"\n### {arc.get('title', '?')}({arc.get('type', '?')}) [{arc.get('arc_id', '')}]")
        lines.append(f"目标:{arc.get('summary', '')}")
        shape = arc.get("pacing_shape")
        if shape:
            lines.append(f"整弧呼吸:{shape}")
        lines.append(f"收束条件:{arc.get('resolution_condition', '未明确')}")
        # 进度定位 + 本段走向(核心:让 beat_planner 知道自己在哪、该往哪走)
        if next_node is not None:
            gap = int(next_node.get("chapter", 0) or 0) - chapter
            lines.append(
                f"▶ 本章进度:你正处在「{(prev_node or {}).get('beat_hint','起点')[:18]}」之后、"
                f"下一个节点「{next_node.get('beat_hint','?')[:24]}」(第{next_node.get('chapter','?')}章[{next_node.get('tension','?')}])之前,还差约{gap}章到下个节点。"
            )
            approach = (prev_node or {}).get("approach_to_next")
            if approach:
                lines.append(f"★ 本段走向(顺着它铺,别跳步别打转):{approach}")
            elif gap >= 2:
                lines.append("★ 本段走向:弧线未给明确走向,按整弧呼吸自行把握铺垫节奏,循序逼近下个节点。")
            # 逐章走向(治"原地打转"):从所属段的 prev_node.chapter_drift 里拎出本章那一格,
            # 并附上下两章的格子,让 beat_planner 看清"本章该挪到哪一格、和邻章有何不同"。
            drift = (prev_node or {}).get("chapter_drift") or []
            if isinstance(drift, list) and drift:
                cur_gist = next((d for d in drift if isinstance(d, dict)
                                 and int(d.get("ch", 0) or 0) == chapter), None)
                if cur_gist:
                    lines.append(f"◆ 本章走向格子(弧线已切好,顺着写,别和邻章重样):{cur_gist.get('gist','')}")
                    nxt = [d for d in drift if isinstance(d, dict) and int(d.get("ch", 0) or 0) in (chapter + 1, chapter + 2)]
                    if nxt:
                        peek = "；".join(f"第{d.get('ch')}章→{d.get('gist','')[:24]}" for d in nxt)
                        lines.append(f"  (下一两章去向,本章别提前写到那:{peek})")
        else:
            lines.append(f"▶ 本章已到/越过本弧最后节点「{(prev_node or {}).get('beat_hint','?')[:24]}」,准备收束。")
        lines.append("节点:")
        for n in relevant[:4]:
            marker = "→" if int(n.get("chapter", 0) or 0) == chapter else " "
            lines.append(f"  {marker} 第{n.get('chapter', '?')}章 [{n.get('tension', '?')}] {n.get('beat_hint', '')}")
        # narrative_ops：把当前节点（或最近的下一个节点）的叙事指令传给 beat_planner
        current_node = next_node if next_node and int(next_node.get("chapter", 0) or 0) == chapter else None
        if not current_node and prev_node and int(prev_node.get("chapter", 0) or 0) == chapter:
            current_node = prev_node
        if current_node:
            nops = current_node.get("narrative_ops")
            if nops:
                lines.append(f"\n**本章叙事指令 narrative_ops（必须执行）：**")
                pov = nops.get("pov")
                if pov:
                    lines.append(f"  POV 章：视角角色={pov.get('character','?')}，类型={pov.get('type','?')}，时间={pov.get('time_relation','顺叙')}，锚点={pov.get('time_anchor','')}，目的={pov.get('purpose','')}")
                fs_list = nops.get("foreshadowing") or []
                if fs_list:
                    for fs in fs_list:
                        lines.append(f"  伏笔[{fs.get('op','?')}][{fs.get('id','?')}]：载体={fs.get('carrier','?')}，可见度={fs.get('visibility','?')}，读者感受={fs.get('reader_should_feel','')}")
                dt = nops.get("dark_thread")
                if dt:
                    lines.append(f"  暗线推进[{dt.get('thread_id','?')}]：{dt.get('action','?')} — {dt.get('how','')}")
        else:
            # 非节点章：从所有节点收集本弧线的伏笔操作供参考
            all_fs = []
            for n in sorted_nodes:
                for fs in (n.get("narrative_ops") or {}).get("foreshadowing") or []:
                    all_fs.append(f"{fs.get('op','?')}[{fs.get('id','?')}]")
            if all_fs:
                lines.append(f"伏笔操作(本弧线规划的,找合适章节安排):{'; '.join(all_fs)}")
            # 兼容旧格式
            fops = arc.get("foreshadowing_ops") or []
            if fops and not all_fs:
                lines.append(f"伏笔操作(本弧线规划的,找合适章节安排):{'; '.join(str(f) for f in fops)}")
    return "\n".join(lines)


def build_beat_input(chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    sections = [
        make_section("目标章节", f"第{chapter}章", "critical", False),
        make_section("故事总监批注(severity≥2时其点名的纠偏动作是【硬约束】必须本章执行；执行要自然，忌打卡式生硬纠偏)", story_director_context(chapter), "critical", False),
        make_section("故事核", read_text(BASE_DIR / "09-故事核.md"), "critical", False),
        make_section("修炼境界安全参考", safe_cultivation_for_writer(), "normal", True),
        make_section("卷纲", read_text(BASE_DIR / "卷纲" / "10-卷纲.md"), "high", True),
        make_section("当前状态摘要", structured_state_for_planner(chapter), "high", True),
        make_section("最近台账日志摘录", recent_ledger_tail(), "low", True),
        make_section("正典账本摘要", ledger_context_for_planner(chapter), "high", True),
        make_section("最近一章正文片段", previous_final_excerpt(chapter) or "无", "normal", True),
    ]
    arc_text = active_arcs_for_beat(chapter)
    if arc_text:
        sections.insert(1, make_section("【硬约束】当前弧线走向(必须遵循,不可自行另起剧情)", arc_text, "critical", False))
    # 节奏/情绪警告 + 威胁阶梯
    pacing_warn = pacing_variety_warnings(chapter)
    if pacing_warn:
        sections.append(make_section("节奏多样性警告", pacing_warn, "high", False))
    emotion_warn = emotional_distribution_warnings(chapter)
    if emotion_warn:
        sections.append(make_section("情绪分布警告", emotion_warn, "high", False))
    # 本书呼吸节奏参考(项目三 D:数字进 JSON,beat_planner.md 只留原理)。给 beat_planner 它用得上的那条。
    norms_text = structure_norms_digest("beat")
    if norms_text:
        sections.append(make_section("本书呼吸节奏参考(连续高强度/缓冲/连续低强度上限——参考非KPI)", norms_text, "normal", True))
    # 钩子去重(单章职责):给 beat_planner 看最近几章的章末钩子+型，连续重复时一级预警。
    # 不可压缩——重复钩子是读者最敏感的"原地打转"信号。
    hooks_digest = recent_hooks_digest(chapter)
    if hooks_digest:
        sections.append(make_section("最近章末钩子(本章不要重复型/指向)", hooks_digest, "high", False))
    # 场景装置去重(单章职责):给 beat_planner 看最近 N 章反复出现的场景结构/动作/物件。
    # 钩子去重只盯章末一句,这里盯整章的"招式"——同一组装置(摸纸条/问人给断语/递东西)反复演
    # 是读者最敏感的"水章"信号,而 beat 原本只看得见前一章正文片段,看不见跨章的招式复发。
    # 不可压缩——和钩子去重同等重要。
    scene_devices = recent_scene_devices_digest(chapter)
    if scene_devices:
        sections.append(make_section("最近场景装置去重(本章别再用同一招推进)", scene_devices, "high", False))
    # 三线节奏(道途/情义/天地):给规划师看配比+断档,决定本章「推进的线」该走哪条。
    # 关键:信号只给规划层(此处+arc_planner),不给writer——节奏平衡是规划的活,
    # 给writer会导致单章视角硬塞。规划师统筹几十章,会安排到合适章节而非挤进本章。
    strand_digest = strand_digest_for_director(chapter)
    strand_warn = strand_pacing_warnings(chapter)
    strand_parts = [p for p in [strand_digest, strand_warn] if p]
    if strand_parts:
        sections.append(make_section(
            "三线节奏配比(规划本章「推进的线」时参考)",
            "\n".join(strand_parts),
            "high", True,
        ))
    # 可回响的情感锚点(让规划师在合适时机安排回响)
    ea_text = emotional_anchors_for_planner(chapter)
    if ea_text:
        sections.append(make_section("可回响的情感锚点(草蛇灰线)", ea_text, "normal", True))
    # 人物债账到期(债/承诺/因果):给规划层定本章有无契机了结老债。
    # 只给规划层不给writer:writer只需知道债"还悬着"(防穿帮,已在ledger_context_for_writer),
    # "该还了"是规划决策,塞给writer单章视角会逼它硬还=打乱节奏。
    obs_due = obligations_due_digest(chapter)
    if obs_due:
        sections.append(make_section("人物债账·到期参考(本章有契机可了结哪笔债)", obs_due, "normal", True))
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
    # 当前地点的既有布局（防穿帮·按需）：让 beat_planner 安排走位时知道场景长什么样
    layout = layout_for_beat({"出场角色": [], "当前地点": load_state().get("current_location", "")})
    if layout:
        sections.append(make_section("当前地点既有布局(安排场景走位时遵守,不要改已确立的方位陈设)", layout, "normal", True))
    return compress_sections_if_needed("beat_planner", chapter, sections, run_cfg, timeout)


