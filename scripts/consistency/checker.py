# -*- coding: utf-8 -*-
"""Phase 2: CHECK — 20 维度跨章一致性比对。

大部分维度为纯 Python 结构化比对，不需要 LLM。
只有少数边界模糊的问题会调用 LLM 辅助判断。
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from .llm import BASE_DIR
from .mapper import FACTS_DIR, load_fact

RUNTIME_DIR = BASE_DIR / "runtime"
BEATS_DIR = BASE_DIR / "beats"

# 时段顺序（用于判断接续合理性）
PERIOD_ORDER = ["凌晨", "清晨", "早", "上午", "正午", "午后", "下午", "傍晚", "入夜", "夜", "深夜", "子时"]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def _all_fact_chapters() -> List[int]:
    """扫磁盘上所有已生成的 fact sheet，返回章节号列表（全局视野）。"""
    chapters = []
    if not FACTS_DIR.exists():
        return chapters
    for p in FACTS_DIR.glob("chapter_*.json"):
        stem = p.stem.replace("chapter_", "")
        if stem.isdigit():
            chapters.append(int(stem))
    return sorted(chapters)


def _load_all_facts() -> Dict[int, dict]:
    """加载磁盘上全部 fact sheets（不受 --chapters 范围限制）。

    跨章检测必须有全局视野：第125章用了第50章丢的银针，只有同时加载
    50 和 125 才能发现。所以 Check 永远基于全部 fact sheet 跑。
    """
    facts = {}
    for ch in _all_fact_chapters():
        f = load_fact(ch)
        if f:
            facts[ch] = f
    return facts


def _issue(severity: str, category: str, dimension: str, chapters: List[int],
           description: str, evidence: dict = None) -> dict:
    return {
        "severity": severity,
        "category": category,
        "dimension": dimension,
        "chapters": chapters,
        "description": description,
        "evidence": evidence or {},
    }


# ==================== 第一类：硬事实穿帮 ====================

def check_timeline(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度1: 时间线连续性 — day 单调递增、period 接续合理。"""
    issues = []
    prev_day = None
    prev_period = None
    prev_ch = None

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        t = f.get("time") or {}
        day = t.get("day")
        period = t.get("period", "")
        mode = f.get("narrative_mode", "顺叙")

        if mode != "顺叙":
            prev_day = day
            prev_period = period
            prev_ch = ch
            continue

        if day is not None and prev_day is not None:
            try:
                if float(day) < float(prev_day):
                    issues.append(_issue(
                        "critical", "硬事实", "时间线连续性", [prev_ch, ch],
                        f"时间倒退: 第{prev_ch}章 day={prev_day}, 第{ch}章 day={day}",
                        {"prev": {"ch": prev_ch, "day": prev_day}, "curr": {"ch": ch, "day": day}}
                    ))
            except (ValueError, TypeError):
                pass

        prev_day = day
        prev_period = period
        prev_ch = ch
    return issues


def check_location_continuity(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度2: 角色位置连续性 — 离场后无交代重现。"""
    issues = []
    last_location: Dict[str, Tuple[str, int]] = {}  # {角色: (地点, 章节)}

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        cast = f.get("cast") or {}
        trace = f.get("location_trace") or []
        current_loc = trace[0]["where"] if trace else ""

        for dep in cast.get("departed", []):
            who = dep.get("who", "")
            if who:
                last_location[who] = ("离场", ch)

        for who in cast.get("present", []):
            if who in last_location:
                status, dep_ch = last_location[who]
                if status == "离场" and (ch - dep_ch) > 1:
                    arrived = [a for a in cast.get("arrived", []) if a.get("who") == who]
                    if not arrived:
                        issues.append(_issue(
                            "warning", "硬事实", "角色位置连续性", [dep_ch, ch],
                            f"{who}在第{dep_ch}章离场，第{ch}章在场但无到达交代",
                        ))
                del last_location[who]
    return issues


def check_items(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度3: 物件轨迹 — 丢了又出现、数量负数。"""
    issues = []
    item_state: Dict[str, Tuple[str, int]] = {}  # {物品: (最后状态, 章节)}

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for item_info in f.get("items") or []:
            name = item_info.get("item", "")
            change = item_info.get("change")
            state = item_info.get("state", "")
            if not name:
                continue

            if change in ("失去", "丢了", "丢失", "扔掉", "给出"):
                item_state[name] = ("lost", ch)
            elif change in ("获得", "拾取", "得到"):
                item_state[name] = ("have", ch)
            elif name in item_state and item_state[name][0] == "lost":
                # 物品之前丢了，现在又出现且没有"获得"交代
                if change is None and "使用" not in (state or ""):
                    pass  # 只是提及，不算使用
                elif change == "使用" or "使用" in (state or ""):
                    lost_ch = item_state[name][1]
                    issues.append(_issue(
                        "critical", "硬事实", "物件轨迹", [lost_ch, ch],
                        f"'{name}'在第{lost_ch}章丢失/给出，第{ch}章使用但无重新获得交代",
                        {"lost_at": lost_ch, "used_at": ch, "item": name}
                    ))
    return issues


def check_knowledge(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度4: 角色知识边界 — 不该知道的事表现出知道了。"""
    issues = []
    ledger = _load_json(RUNTIME_DIR / "ledger.json")
    entities = ledger.get("entities") or {}

    # 建立"谁知道什么"的索引
    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for k in f.get("knowledge") or []:
            who = k.get("who", "")
            knows = k.get("knows", "")
            if not who or not knows:
                continue

            entity = entities.get(who) or {}
            secrets = entity.get("secrets") or []
            for secret in secrets:
                secret_text = secret.get("secret", "") if isinstance(secret, dict) else str(secret)
                known_by = secret.get("known_by", []) if isinstance(secret, dict) else []
                # 检查：正文显示角色知道某事，但该事是另一角色的秘密且 known_by 里没有这个角色
                if who not in known_by and _text_similar(knows, secret_text):
                    # 额外检查：是否在该章正文里才刚获知
                    how = k.get("how_learned", "")
                    if how and ("本章" in how or f"第{ch}章" in how):
                        continue
                    issues.append(_issue(
                        "warning", "硬事实", "角色知识边界", [ch],
                        f"第{ch}章: {who}表现出知道'{knows}'，但此信息的 known_by 不含{who}",
                        {"who": who, "knows": knows, "secret": secret_text}
                    ))
    return issues


def _text_similar(a: str, b: str) -> bool:
    """简单文本相似度判断（关键词重叠）。"""
    a_chars = set(re.findall(r'[一-鿿]+', a))
    b_chars = set(re.findall(r'[一-鿿]+', b))
    if not a_chars or not b_chars:
        return False
    overlap = len(a_chars & b_chars)
    return overlap >= 2 or overlap / max(len(a_chars), 1) > 0.5


def check_foreshadowing(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度5: 伏笔时序 — planted 之前就暗示了。"""
    issues = []
    threads = _load_json(RUNTIME_DIR / "active_threads.json")
    foreshadowing = threads.get("foreshadowing") or {}

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for fs in f.get("foreshadowing") or []:
            content = fs.get("id_or_content", "")
            action = fs.get("action", "")
            # 检查是否引用了 F-XXX 编号
            fid_match = re.search(r"F-\d{3}", content)
            if fid_match:
                fid = fid_match.group()
                thread = foreshadowing.get(fid)
                if thread:
                    planted = thread.get("planted_chapter", 0)
                    if ch < planted and action != "新埋":
                        issues.append(_issue(
                            "critical", "硬事实", "伏笔时序", [ch],
                            f"第{ch}章引用伏笔{fid}，但该伏笔在第{planted}章才埋下（时序倒挂）",
                        ))
    return issues


def check_skills(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度6: 技能/境界越界。"""
    issues = []
    ledger = _load_json(RUNTIME_DIR / "ledger.json")
    entities = ledger.get("entities") or {}

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for su in f.get("skills_used") or []:
            who = su.get("who", "")
            skill = su.get("skill", "")
            if not who or not skill:
                continue
            entity = entities.get(who) or {}
            known_skills = [s.get("name", "") for s in entity.get("skills") or []]
            if known_skills and not any(skill in ks or ks in skill for ks in known_skills):
                issues.append(_issue(
                    "warning", "硬事实", "技能/境界越界", [ch],
                    f"第{ch}章: {who}使用技能'{skill}'，但角色卡 skills 中无匹配记录",
                    {"who": who, "skill": skill, "known": known_skills[:5]}
                ))
    return issues


def check_injuries(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度7: 伤势连续性 — 重伤无交代痊愈。"""
    issues = []
    injury_track: Dict[str, List[Tuple[int, str, str]]] = defaultdict(list)

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for inj in f.get("injuries_state") or []:
            who = inj.get("who", "")
            injury = inj.get("injury", "")
            status = inj.get("status", "")
            if who and injury:
                injury_track[f"{who}:{injury}"].append((ch, injury, status))

    for key, records in injury_track.items():
        for i in range(1, len(records)):
            prev_ch, prev_inj, prev_status = records[i - 1]
            curr_ch, curr_inj, curr_status = records[i]
            if "重伤" in prev_status or "严重" in prev_status:
                if "愈合" in curr_status or "无" in curr_status or "正常" in curr_status:
                    if (curr_ch - prev_ch) <= 3:
                        issues.append(_issue(
                            "warning", "硬事实", "伤势连续性", [prev_ch, curr_ch],
                            f"{key.split(':')[0]}在第{prev_ch}章'{prev_inj}'状态为'{prev_status}'，"
                            f"第{curr_ch}章仅隔{curr_ch - prev_ch}章就变为'{curr_status}'",
                        ))
    return issues


def check_sensory(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度8: 感官穿帮 — 盲人白天看见精细细节。"""
    issues = []
    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        pov = f.get("pov", "沈安")
        if pov != "沈安":
            continue
        for s in f.get("sensory") or []:
            if s.get("type") != "visual":
                continue
            context = s.get("context", "")
            # 夜里/月光下沈安有特殊视力，排除
            if any(k in context for k in ["夜", "月光", "暗", "火光"]):
                continue
            # 白天+视觉 = 穿帮
            if any(k in context for k in ["白天", "正午", "上午", "下午", "日光"]):
                issues.append(_issue(
                    "critical", "硬事实", "感官穿帮", [ch],
                    f"第{ch}章 L{s.get('line','?')}: 盲人沈安在'{context}'有视觉描写: \"{s.get('text','')}\"",
                    {"line": s.get("line"), "text": s.get("text"), "context": context}
                ))
    return issues


def check_spatial(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度9: 空间布局矛盾 — 同地方物理描述前后不一致。"""
    issues = []
    spatial_by_location: Dict[str, List[Tuple[int, List[str]]]] = defaultdict(list)

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for sp in f.get("spatial") or []:
            loc = sp.get("location", "")
            claims = sp.get("layout_claims") or []
            if loc and claims:
                spatial_by_location[loc].append((ch, claims))

    # 检查同一地点的描述是否有明显矛盾
    direction_pairs = [("东", "西"), ("南", "北"), ("左", "右")]
    for loc, records in spatial_by_location.items():
        if len(records) < 2:
            continue
        all_claims = []
        for ch, claims in records:
            for claim in claims:
                all_claims.append((ch, claim))
        # 简单检测：同一物件在不同章出现了相反方位
        for i, (ch_a, claim_a) in enumerate(all_claims):
            for ch_b, claim_b in all_claims[i + 1:]:
                if ch_a == ch_b:
                    continue
                for d1, d2 in direction_pairs:
                    if d1 in claim_a and d2 in claim_b:
                        # 检查是否描述同一物件
                        common = set(claim_a) & set(claim_b) - set(d1 + d2 + "朝向在靠")
                        if len(common) >= 2:
                            issues.append(_issue(
                                "warning", "硬事实", "空间布局矛盾", [ch_a, ch_b],
                                f"'{loc}'布局矛盾: 第{ch_a}章'{claim_a}' vs 第{ch_b}章'{claim_b}'",
                            ))
    return issues


def check_existence(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度10: 角色存在性 — 已死/离场角色无交代重现。"""
    issues = []
    ledger = _load_json(RUNTIME_DIR / "ledger.json")
    entities = ledger.get("entities") or {}

    dead_chars = set()
    for name, entity in entities.items():
        if isinstance(entity, dict):
            status = entity.get("status", "")
            if "死" in status or "亡" in status:
                dead_chars.add(name)

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        present = set(f.get("cast", {}).get("present", []))
        for who in present & dead_chars:
            issues.append(_issue(
                "critical", "硬事实", "角色存在性", [ch],
                f"第{ch}章: 已死角色'{who}'出现在场",
            ))
    return issues


# ==================== 第二类：角色一致性 ====================

def check_voice(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度11: 语音 — 话多的突然沉默，沉默的突然话多。"""
    issues = []
    ledger = _load_json(RUNTIME_DIR / "ledger.json")
    entities = ledger.get("entities") or {}

    char_dialogue: Dict[str, List[Tuple[int, int, str]]] = defaultdict(list)
    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for char_name, sample in (f.get("voice_sample") or {}).items():
            count = sample.get("dialogue_count", 0)
            longest = sample.get("longest_line", "")
            char_dialogue[char_name].append((ch, count, longest))

    for char_name, records in char_dialogue.items():
        if len(records) < 5:
            continue
        counts = [r[1] for r in records]
        avg = sum(counts) / len(counts)
        if avg == 0:
            continue

        entity = entities.get(char_name) or {}
        voice = entity.get("voice", "")
        is_quiet = any(k in voice for k in ["沉默", "寡言", "简短", "话少"])

        for ch, count, longest in records:
            if is_quiet and len(longest) > 40:
                issues.append(_issue(
                    "warning", "角色一致性", "语音", [ch],
                    f"第{ch}章: {char_name}(voice='{voice[:20]}')说了超长台词({len(longest)}字): \"{longest[:30]}...\"",
                ))
            if count > avg * 3 and count > 8:
                issues.append(_issue(
                    "note", "角色一致性", "语音", [ch],
                    f"第{ch}章: {char_name}说话{count}次，历史均值{avg:.1f}次/章",
                ))
    return issues


def check_mannerisms(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度12: 行为习惯 — 出现 ledger 没记录的全新习惯。"""
    issues = []
    ledger = _load_json(RUNTIME_DIR / "ledger.json")
    entities = ledger.get("entities") or {}

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for m in f.get("mannerisms_observed") or []:
            who = m.get("who", "")
            action = m.get("action", "")
            if not who or not action:
                continue
            entity = entities.get(who) or {}
            known = entity.get("mannerisms") or []
            if known and not any(_text_similar(action, km) for km in known):
                # 只是备注，不一定是穿帮（可能是新发展）
                pass  # 不报 — 新习惯太常见，会产生大量噪音
    return issues


def check_appearance(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度13: 外貌特征 — 同一角色描述前后矛盾。"""
    issues = []
    appearance_by_char: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for ap in f.get("appearance_mentions") or []:
            who = ap.get("who", "")
            detail = ap.get("detail", "")
            if who and detail:
                appearance_by_char[who].append((ch, detail))

    # 检查矛盾：同一角色出现了互斥的描述
    contradictions = [
        ("白净", "粗糙"), ("白净", "血痂"), ("挺直", "弯"), ("瘦", "胖"),
        ("高", "矮"), ("年轻", "老"), ("光滑", "疤"),
    ]
    for who, records in appearance_by_char.items():
        for i, (ch_a, det_a) in enumerate(records):
            for ch_b, det_b in records[i + 1:]:
                for word_a, word_b in contradictions:
                    if (word_a in det_a and word_b in det_b) or (word_b in det_a and word_a in det_b):
                        issues.append(_issue(
                            "warning", "角色一致性", "外貌特征", [ch_a, ch_b],
                            f"{who}外貌矛盾: 第{ch_a}章'{det_a}' vs 第{ch_b}章'{det_b}'",
                        ))
    return issues


def check_dialogue_volume(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度14: 台词量 — 偏离均值 2 倍标准差。"""
    issues = []
    char_counts: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for char_name, sample in (f.get("voice_sample") or {}).items():
            char_counts[char_name].append((ch, sample.get("dialogue_count", 0)))

    for char_name, records in char_counts.items():
        if len(records) < 10:
            continue
        counts = [r[1] for r in records]
        avg = sum(counts) / len(counts)
        if avg < 1:
            continue
        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        std = variance ** 0.5
        if std < 1:
            continue
        for ch, count in records:
            if count > avg + 2 * std and count > 10:
                issues.append(_issue(
                    "note", "角色一致性", "台词量", [ch],
                    f"第{ch}章: {char_name}说话{count}次，均值{avg:.1f}±{std:.1f}",
                ))
    return issues


def check_emotion_drift(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度15: 情绪漂移 — 无 trigger 突变。"""
    issues = []
    pov_emotions: List[Tuple[int, str, str]] = []

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        pov = f.get("pov", "沈安")
        for em in f.get("emotional_state") or []:
            if em.get("who") == pov:
                pov_emotions.append((ch, em.get("state", ""), em.get("trigger", "")))
                break

    # 检测连续的情绪极性翻转（无 trigger）
    positive = ["愉快", "轻松", "开心", "兴奋", "松弛"]
    negative = ["压抑", "沉默", "克制", "焦急", "紧张", "疲惫"]

    for i in range(1, len(pov_emotions)):
        prev_ch, prev_state, _ = pov_emotions[i - 1]
        curr_ch, curr_state, trigger = pov_emotions[i]
        prev_pos = any(p in prev_state for p in positive)
        prev_neg = any(n in prev_state for n in negative)
        curr_pos = any(p in curr_state for p in positive)
        curr_neg = any(n in curr_state for n in negative)

        if (prev_neg and curr_pos) or (prev_pos and curr_neg):
            if not trigger or trigger == "null":
                issues.append(_issue(
                    "note", "角色一致性", "情绪漂移", [prev_ch, curr_ch],
                    f"情绪突变无触发: 第{prev_ch}章'{prev_state}' → 第{curr_ch}章'{curr_state}'",
                ))
    return issues


def check_internal_progress(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度16: 心路断裂 — 已推进过的认知退回原点。"""
    issues = []
    progress_chain: List[Tuple[int, str, str]] = []

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for ip in f.get("internal_progress") or []:
            who = ip.get("who", "")
            if who == f.get("pov", "沈安"):
                progress_chain.append((ch, ip.get("from", ""), ip.get("to", "")))

    # 检测: "to" 和后续某章的 "from" 是否矛盾（从已接受退回不接受）
    # 这个检测比较粗糙，主要靠关键词
    for i in range(len(progress_chain)):
        _, _, to_state = progress_chain[i]
        for j in range(i + 1, min(i + 10, len(progress_chain))):
            later_ch, from_state, _ = progress_chain[j]
            if to_state and from_state and _text_similar(to_state, from_state):
                # "to" 和后续的 "from" 一样 → 没退回，正常
                pass
            # 退回检测需要更复杂的语义理解，这里先留简单版
    return issues


def check_relationships(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度17: 关系演变合理性。"""
    issues = []
    rel_trace: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        for r in f.get("relationships_displayed") or []:
            a, b = r.get("a", ""), r.get("b", "")
            tone = r.get("tone", "")
            if a and b and tone:
                key = f"{min(a,b)}-{max(a,b)}"
                rel_trace[key].append((ch, tone))

    hostile = ["敌对", "决裂", "仇", "恨", "不信任"]
    friendly = ["信任", "亲近", "合作", "温和"]

    for key, records in rel_trace.items():
        for i in range(1, len(records)):
            prev_ch, prev_tone = records[i - 1]
            curr_ch, curr_tone = records[i]
            was_hostile = any(h in prev_tone for h in hostile)
            now_friendly = any(f in curr_tone for f in friendly)
            if was_hostile and now_friendly and (curr_ch - prev_ch) <= 5:
                issues.append(_issue(
                    "warning", "角色一致性", "关系演变", [prev_ch, curr_ch],
                    f"{key}: 第{prev_ch}章'{prev_tone}' → 第{curr_ch}章'{curr_tone}'（仅隔{curr_ch-prev_ch}章）",
                ))
    return issues


# ==================== 第三类：叙事一致性 ====================

def check_naming(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度18: 命名一致性 — 同一地点/人前后章用不同名字。"""
    issues = []
    # 已知的别名对
    known_aliases = {
        "济安堂": "济安堂", "济春堂": "济春堂",
        "沈安": "沈安", "沈归舟": "沈归舟",
    }
    location_names: Dict[int, set] = {}

    for ch in sorted(chapters):
        f = facts.get(ch)
        if not f:
            continue
        locs = set()
        for lt in f.get("location_trace") or []:
            locs.add(lt.get("where", ""))
        location_names[ch] = locs

    # 检测："济安堂"和"济春堂"是否混用（已知问题）
    tang_a = [ch for ch, locs in location_names.items() if any("济安" in l for l in locs)]
    tang_b = [ch for ch, locs in location_names.items() if any("济春" in l for l in locs)]
    if tang_a and tang_b:
        issues.append(_issue(
            "critical", "叙事一致性", "命名一致性",
            [tang_a[0], tang_b[0]],
            f"药铺名混用: '济安堂'(第{tang_a[0]}章等) vs '济春堂'(第{tang_b[0]}章等)",
        ))
    return issues


def check_world_rules(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度19: 世界观矛盾（需要更多数据才能有效检测，目前为占位）。"""
    return []


def check_distance(facts: Dict[int, dict], chapters: List[int]) -> List[dict]:
    """维度20: 度量衡/距离矛盾（需要更多数据才能有效检测，目前为占位）。"""
    return []


# ==================== 主入口 ====================

WATERMARK_PATH = BASE_DIR / "consistency" / "watermark.json"


def _load_watermark() -> int:
    """读取上次扫描的水位线（最高章节号）。首次扫描返回 0。"""
    data = _load_json(WATERMARK_PATH)
    return int(data.get("last_scanned", 0) or 0)


def _save_watermark(last_scanned: int):
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK_PATH.write_text(
        json.dumps({
            "last_scanned": last_scanned,
            "last_scan_time": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_check_phase(update_watermark: bool = True) -> Dict[str, Any]:
    """运行全部 20 维度检测，返回结构化结果。

    基于磁盘上全部 fact sheet 做全局比对（不受 Map 的 --chapters 范围限制），
    因为跨章检测需要全局视野。

    每条问题打 is_new 标记：涉及章节中有任意一章 > 上次水位线 → 本次新增。
    这样新写章节引入的所有矛盾（哪怕牵连很老的章）都会冒到"新增"栏。
    """
    facts = _load_all_facts()
    if not facts:
        print("  [CHECK] 未找到 fact sheets，请先运行 --map")
        return {"scan_time": "", "chapters_scanned": [], "issues": [], "watermark_prev": 0}

    chapters = sorted(facts.keys())
    watermark_prev = _load_watermark()

    all_issues: List[dict] = []
    checkers = [
        ("时间线连续性", check_timeline),
        ("角色位置连续性", check_location_continuity),
        ("物件轨迹", check_items),
        ("角色知识边界", check_knowledge),
        ("伏笔时序", check_foreshadowing),
        ("技能/境界越界", check_skills),
        ("伤势连续性", check_injuries),
        ("感官穿帮", check_sensory),
        ("空间布局矛盾", check_spatial),
        ("角色存在性", check_existence),
        ("语音", check_voice),
        ("行为习惯", check_mannerisms),
        ("外貌特征", check_appearance),
        ("台词量", check_dialogue_volume),
        ("情绪漂移", check_emotion_drift),
        ("心路断裂", check_internal_progress),
        ("关系演变", check_relationships),
        ("命名一致性", check_naming),
        ("世界观矛盾", check_world_rules),
        ("度量衡/距离", check_distance),
    ]

    for name, checker in checkers:
        try:
            results = checker(facts, chapters)
            if results:
                print(f"  [{name}] 发现 {len(results)} 条问题")
            all_issues.extend(results)
        except Exception as e:
            print(f"  [{name}] 检测出错: {e}")

    # 标记新增 + 编号
    for i, issue in enumerate(all_issues, 1):
        issue["id"] = f"ISS-{i:03d}"
        chs = issue.get("chapters") or []
        issue["is_new"] = any(c > watermark_prev for c in chs) if chs else False

    new_count = sum(1 for it in all_issues if it["is_new"])
    scanned_max = max(chapters)

    result = {
        "scan_time": datetime.now().isoformat(timespec="seconds"),
        "chapters_scanned": [min(chapters), scanned_max],
        "watermark_prev": watermark_prev,
        "issues": all_issues,
    }

    # 落盘最新全量快照（供下次对比/报告读取）
    output_path = BASE_DIR / "consistency" / "issues_raw.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 推进水位线（只升不降；--chapters 局部扫描不应回退全局水位线）
    if update_watermark and scanned_max > watermark_prev:
        _save_watermark(scanned_max)

    print(f"\n  Check 完成: 共 {len(all_issues)} 条问题（其中本次新增 {new_count} 条，上次水位线=第{watermark_prev}章）")
    print(f"  已写入 {output_path.name}")
    return result

