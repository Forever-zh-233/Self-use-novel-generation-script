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
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add scripts/ to path so pipeline package is importable
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.core import *  # noqa: F401,F403
from pipeline.api import *  # noqa: F401,F403
from pipeline.state import *  # noqa: F401,F403
from pipeline.context import *  # noqa: F401,F403
from pipeline.gates import *  # noqa: F401,F403
from pipeline.planning import *  # noqa: F401,F403
from pipeline.archivist import *  # noqa: F401,F403


REJECTION_PATTERN = re.compile(
    r"the request was rejected because it was considered high risk",
    re.IGNORECASE,
)


def write_score_report(chapter: int, verdict: Dict[str, Any]) -> None:
    """把 reviewer 的本章评分写成简要报告,存到 输出/分数表/ 第NNN章.md。
    这个目录【不在 cleanup_chapter_artifacts 的清理名单内】(那个名单只含
    beat/writer/gate/reviewer/editor/archivist/context),所以无论 clean 还是
    reports 模式都不会被删——专供人事后翻全书质量趋势。
    红线:此文件【只写不读】,任何角色的 build_*_input 都禁止注入它,否则分数变
    KPI、模型为分数写作、污染 reviewer 盲评——这是我们一路在防的 Goodhart 陷阱。"""
    try:
        SCORE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        scores = verdict.get("scores") or {}
        lines = [
            f"# 第{chapter}章 评分简报",
            "",
            f"- 总分：{verdict.get('total', '?')}/60",
            f"- 是否返工：{'是' if verdict.get('needs_revision') else '否'}",
            f"- 判定来源：{verdict.get('source', '?')}（json=结构化主路 / keyword=回退）",
            "",
        ]
        if scores:
            lines.append("## 各项分数")
            for k, v in scores.items():
                lines.append(f"- {k}：{v}")
            lines.append("")
        blockers = verdict.get("blockers") or []
        if blockers:
            lines.append("## 阻断原因")
            for b in blockers:
                lines.append(f"- {b}")
            lines.append("")
        write_text(SCORE_REPORT_DIR / f"第{chapter:03d}章.md", "\n".join(lines))
    except OSError as exc:
        cli_print(f"[score_report] 第{chapter}章评分简报写入失败（不影响正文）：{exc}")



def resolve_beat_path(chapter: int, run_cfg: Dict[str, Any]) -> Path:
    beat_template = run_cfg.get("beat_template") or str(BASE_DIR / "beats" / "chapter_{chapter}.json")
    return Path(str(beat_template).format(chapter=chapter))



def normalize_beat(chapter: int, beat: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "章节编号": int(beat.get("章节编号") or chapter),
        "标题": str(beat.get("标题") or f"第{chapter}章"),
        "视角角色": str(beat.get("视角角色") or "沈安"),
        "时间锚点": str(beat.get("时间锚点") or ""),
        "叙事手法": str(beat.get("叙事手法") or "顺叙"),
        "戏剧目的": str(beat.get("戏剧目的") or ""),
        "期待循环位置": str(beat.get("期待循环位置") or "酿"),
        "场景类型": str(beat.get("场景类型") or "日常对话"),
        "空间布局": str(beat.get("空间布局") or ""),
        "本章冲突": str(beat.get("本章冲突") or "推进主线冲突。"),
        "具体物件": beat.get("具体物件") or [],
        "具体动作": beat.get("具体动作") or [],
        "信息差": str(beat.get("信息差") or "未明确"),
        "转折": str(beat.get("转折") or "中段出现新的线索或代价。"),
        "本章张力": str(beat.get("本章张力") or "平"),
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
        "情绪基调",
        "钩子型",
        "关键章",
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

    raw = call_role(
        "beat_planner",
        beat_prompt,
        beat_input,
        role_artifact("beat", chapter, "beat_raw.md"),
        timeout,
        1800,
        role_artifact("beat", chapter, "beat_input.md"),
    )
    raw_first = raw
    raw_retry = ""
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
        raw_retry = raw
        beat = normalize_beat(chapter, extract_json_object(raw))
        direction = beat_direction_check(beat, chapter)
        dump_json(role_artifact("gate", chapter, "beat_direction_retry.json"), direction)
    dump_json(beat_path, beat)
    # 调试留档(不受 cleanup 影响):每章一个子文件夹,存它当时被喂了什么、原样吐了什么、方向校验、最终 beat。
    write_beat_debug(chapter, {
        "beat_input.md": beat_input,
        "beat_raw.md": raw_first,
        "beat_raw_retry.md": raw_retry,
        "direction.json": json.dumps(direction, ensure_ascii=False, indent=2),
        "beat.json": json.dumps(beat, ensure_ascii=False, indent=2),
    })
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
    触发机制(用户设计,2026-06-01):
      - beat_planner 是决策者:它每章跑、在 writer 前跑、最清楚这章是铺垫还是引爆。
        它在 beat 里标 `关键章: true` 表示"这章该全力以赴"。
      - arc 窗口是护栏:beat_planner 标了关键章,但只有同时落在 arc 高潮节点 ±1 章
        窗口内才认——窗口外标了不算,防止 beat_planner 为换资源乱标(Goodhart 防护)。
      - story_director 是建议者:它的"临近高潮"建议供 beat_planner 参考,不做门禁。
      - run.json key_chapters 手动白名单保留作后门(特殊章节人工指定)。
    费 token(writer×N),故默认只在关键章开启。"""
    cfg = run_cfg.get("best_of_n")
    if not cfg or not isinstance(cfg, dict) or not cfg.get("enabled"):
        return 1
    n = int(cfg.get("n") or 3)
    ch = int(beat.get("章节编号") or 0)
    # 路1:beat_planner 标了关键章 + 必须在 arc 高潮窗口内(护栏)
    beat_flag = bool(beat.get("关键章") or beat.get("高潮章") or beat.get("best_of_n"))
    if beat_flag and in_climax_window(ch):
        return max(2, min(n, 5))
    # 路2:run.json 手动白名单(后门,不受窗口限制——人工指定说明你知道自己在干什么)
    key_chapters = set(int(c) for c in (cfg.get("key_chapters") or []) if str(c).isdigit())
    if ch in key_chapters:
        return max(2, min(n, 5))
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



def read_cached_artifact(path: Path, min_len: int = 50) -> str:
    """续跑用：读已落盘的阶段产物。非空且达最小长度才算有效缓存，否则返回 ''。
    依据：call_role 只在成功时落盘；cleanup 只在整章成功后执行，失败章的产物得以保留。"""
    txt = read_text(path).strip()
    return txt if len(txt) >= min_len else ""


def resume_verdict(chapter: int) -> Dict[str, Any]:
    """续跑时重建 verdict：① review_verdict.json → ② 解析 review.md → ③ 默认放行。"""
    raw = read_text(role_artifact("reviewer", chapter, "review_verdict.json")).strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    review = read_text(role_artifact("reviewer", chapter, "review.md")).strip()
    if review:
        return parse_review_verdict(review)
    return {"needs_revision": False, "total": None, "blockers": [], "source": "resume_default"}


def generate_chapter_final(
    chapter: int, beat: Dict[str, Any], pov_character: str, run_cfg: Dict[str, Any],
    chapter_index: int, total_chapters: int, timeout: int, sleep_seconds: float,
):
    """生成本章定稿（writer→gate→reviewer→editor→fact_check），返回 (final, verdict)。
    dry_run 返回 None。正文与 manuscript 在本函数内落盘；台账由调用方负责。
    续跑：draft/review/edited 已落盘则复用，断哪续哪，不整章推倒重来。"""
    max_revisions = int(run_cfg.get("max_revisions") or 1)
    # dry_run 只为导出 writer prompt，强制不走续跑缓存，避免误命中旧 draft 直接跳过
    resume = bool(run_cfg.get("resume_partial_chapter", True)) and not run_cfg.get("dry_run")
    total_steps = 7
    started = stage_start(chapter, "writer", "构建上下文", 1, total_steps, chapter_index, total_chapters)

    # POV 路由：视角角色非沈安时走 POV 分支
    pov_character = beat.get("视角角色", "沈安")
    writer_prompt = read_text(PROMPTS_DIR / ("writer_pov.md" if pov_character != "沈安" else "writer.md"))
    reviewer_prompt = read_text(PROMPTS_DIR / "reviewer.md")
    if pov_character != "沈安":
        cli_print(f"[POV] 第{chapter}章为 POV 章，视角角色：{pov_character}")

    # 续跑：初稿已落盘则跳过最贵的 writer 步，连带跳过构建上下文（可能触发压缩 LLM 调用）
    cached_draft = read_cached_artifact(role_artifact("writer", chapter, "draft.md")) if resume else ""

    if cached_draft:
        stage_done(chapter, "writer", "构建上下文", 1, total_steps, started)
    else:
        if pov_character != "沈安":
            writer_input = build_pov_writer_input(beat, chapter, run_cfg, timeout)
        else:
            writer_input = build_writer_input(beat, chapter, run_cfg, timeout)
        write_text(role_artifact("writer", chapter, "writer_prompt.md"), writer_input)
        stage_done(chapter, "writer", "构建上下文", 1, total_steps, started)
        if run_cfg.get("dry_run"):
            print(f"dry-run: writer prompt saved for chapter {chapter}")
            return None

    wait_if_paused("Writer 写初稿前")
    started = stage_start(chapter, "writer", "写初稿", 2, total_steps, chapter_index, total_chapters)
    if cached_draft:
        # 续跑：初稿已落盘（含 best_of_n 赢家也写在 draft.md），跳过最贵的 writer 步
        draft = cached_draft
        cli_print(f"[续跑] 第{chapter}章复用已有初稿，跳过 writer 写初稿。")
    else:
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
    adjacent = continuity_check_adjacent(chapter, draft, beat)
    type_guard = type_guard_check(draft, chapter)
    satisfaction = chapter_satisfaction_check(draft, beat)
    gate = combine_checks({
        "hard_gate": hard,
        "style_gate": style,
        "continuity_check": continuity,
        "adjacent_continuity": {"passed": not adjacent, "issues": adjacent, "warnings": []},
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
    cached_review = read_cached_artifact(role_artifact("reviewer", chapter, "review.md")) if resume else ""
    if cached_review:
        review = cached_review
        cli_print(f"[续跑] 第{chapter}章复用已有评审，跳过 reviewer。")
    else:
        review_input = make_review_input(draft, chapter, run_cfg, timeout, gate, beat)
        # POV 章授权声明注入
        if pov_character != "沈安":
            pov_auth = (
                f"\n\n【授权 POV 章】本章是授权的 POV 章（视角角色：{pov_character}）。\n"
                f"评判视角一致性时按【{pov_character}】的感知，不按沈安。\n"
                f"该角色能看见颜色/光线/表情（非盲人），这不是穿帮。\n"
                f"检查该角色是否泄露了不该知道的信息——泄露才是真穿帮。"
            )
            review_input = pov_auth + "\n\n" + review_input
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

    # #6:解析 reviewer 双轨输出的结构化判定块,落盘存档(纯诊断,不回灌任何角色)。
    verdict = parse_review_verdict(review)
    dump_json(role_artifact("reviewer", chapter, "review_verdict.json"), verdict)
    if verdict.get("source") == "keyword":
        cli_print(f"[reviewer] 第{chapter}章:JSON判定块解析失败,已回退关键词匹配(needs_revision={verdict['needs_revision']})。")
    else:
        total = verdict.get("total")
        cli_print(f"[reviewer] 第{chapter}章:总分{total if total is not None else '?'}/60,needs_revision={verdict['needs_revision']}。")
        for b in (verdict.get("blockers") or [])[:5]:
            cli_print(f"  阻断:{b}")

    final = draft
    cached_edited = read_cached_artifact(role_artifact("editor", chapter, "edited.md")) if resume else ""
    if max_revisions > 0 and ((not gate.get("passed")) or verdict.get("needs_revision")):
        if cached_edited:
            final = cached_edited
            started = stage_start(chapter, "editor", "修稿", 5, total_steps, chapter_index, total_chapters)
            cli_print(f"[续跑] 第{chapter}章复用已有修稿，跳过 editor。")
            stage_done(chapter, "editor", "修稿", 5, total_steps, started)
        else:
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
    final_adjacent = continuity_check_adjacent(chapter, final, beat)
    final_type_guard = type_guard_check(final, chapter)
    final_satisfaction = chapter_satisfaction_check(final, beat)
    final_gate = combine_checks({
        "hard_gate": final_hard,
        "style_gate": final_style,
        "continuity_check": final_continuity,
        "adjacent_continuity": {"passed": not final_adjacent, "issues": final_adjacent, "warnings": []},
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
            # 只数"穿帮问题"section里的条目,忽略"疑似问题"
            real_issues = 0
            if fact_check_result:
                breach_section = re.split(r"###\s*疑似", fact_check_result, maxsplit=1)[0]
                real_issues = len(re.findall(r"^\d+\.\s*\[", breach_section, re.MULTILINE))
            if real_issues > 0:
                issue_lines = re.findall(r"^\d+\.\s*\[.*", breach_section, re.MULTILINE)
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
    # 也匹配模型原样复制模板占位符的情况 (# 第{N}章)
    chapter_heading = re.search(r"^#\s*第(?:\d+|\{N\})章", final, re.MULTILINE)
    if chapter_heading:
        final = final[chapter_heading.start():]
    # 强制修正标题行：模型可能输出模板占位符或漏掉标题
    title = beat.get("标题") or ""
    correct_heading = f"# 第{chapter}章 {title}".rstrip()
    final = re.sub(r"^#\s*第(?:\d+|\{N\})章[^\n]*", correct_heading, final, count=1, flags=re.MULTILINE)

    write_text(role_artifact("writer", chapter, "final.md"), final)
    write_text(manuscript_path(chapter), final)
    return final, verdict


def run_one_chapter(chapter: int, beat_path: Path, run_cfg: Dict[str, Any], chapter_index: int, total_chapters: int) -> None:
    timeout = int(run_cfg.get("request_timeout_seconds") or 240)
    sleep_seconds = float(run_cfg.get("sleep_seconds_between_calls") or 1)
    resume = bool(run_cfg.get("resume_partial_chapter", True)) and not run_cfg.get("dry_run")
    total_steps = 7
    chapter_t0 = time.time()

    wait_if_paused("读取 beat")
    beat = json.loads(read_text(beat_path))
    pov_character = beat.get("视角角色", "沈安")
    archivist_prompt = read_text(PROMPTS_DIR / "archivist.md")

    # A1 续跑：正文已落盘(失败只发生在 archivist 步)则跳过整个生成段，直奔补台账，
    # 省掉 writer/reviewer/editor/fact_check 的全部重复生成（第26章式失败的零浪费续跑）。
    min_chars = int(run_cfg.get("min_recover_article_chars") or 1000)
    manuscript = manuscript_path(chapter)
    final = read_text(manuscript).strip() if manuscript.exists() else ""
    have_final = resume and len(re.findall(r'[一-鿿]', final)) >= min_chars
    if have_final:
        cli_print(f"[续跑] 第{chapter}章正文已存在，跳过生成阶段，直接补台账。")
        verdict = resume_verdict(chapter)
    else:
        result = generate_chapter_final(
            chapter, beat, pov_character, run_cfg,
            chapter_index, total_chapters, timeout, sleep_seconds,
        )
        if result is None:  # dry_run
            return
        final, verdict = result

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

    # POV 章完成后标记 seed 为 deployed
    if pov_character != "沈安":
        ledger = load_ledger()
        for s in ledger.get("impact_seeds") or []:
            if s.get("who") == pov_character and s.get("status") == "pending":
                s["status"] = "deployed"
                s["deployed_chapter"] = chapter
                break
        dump_json(LEDGER_FILE, ledger)

    # 超过 best_window 上限 10 章仍为 pending 的 seed 自动标记 dropped
    ledger = load_ledger()
    seeds_changed = False
    for s in ledger.get("impact_seeds") or []:
        if s.get("status") != "pending":
            continue
        window = s.get("best_window", "")
        nums = re.findall(r"\d+", str(window))
        if len(nums) >= 2:
            window_end = int(nums[-1])
            if chapter > window_end + 10:
                s["status"] = "dropped"
                s["dropped_chapter"] = chapter
                seeds_changed = True
    if seeds_changed:
        dump_json(LEDGER_FILE, ledger)

    write_score_report(chapter, verdict)
    cleanup_chapter_artifacts(chapter, run_cfg)
    elapsed_total = time.time() - chapter_t0
    minutes = int(elapsed_total // 60)
    seconds = int(elapsed_total % 60)
    score = verdict.get("total", "?")
    cli_print(f"═══ 章 {chapter} 完成 │ {minutes}m{seconds:02d}s │ 评分 {score}/60 │ {manuscript_path(chapter).name} ═══")


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
    # 最先加载 .env.local 到环境变量(API key 在此),否则新终端启动会因 key 缺失 401。
    n_env = load_env_local()
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
    if n_env and not getattr(args, "no_cli", False):
        cli_print(f"已从 .env.local 加载 {n_env} 个环境变量（含 API key，值不显示）。")

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
        per_chapter_retries = int(run_cfg.get("per_chapter_retries") or 3)
        retry_backoff = float(run_cfg.get("retry_backoff_seconds") or 45)
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
