# -*- coding: utf-8 -*-
"""pipeline.gates — hard_gate, style_gate, reviewer functions."""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    BASE_DIR, PROMPTS_DIR, REALM_ORDER_WITH_MORTAL, _sanitize_model_json,
    cli_print, manuscript_path, read_text, load_json,
)
from pipeline.state import (
    load_active_threads, load_index, load_ledger, load_state,
    load_story_director,
)
from pipeline.context import compress_sections_if_needed, make_section
from pipeline.planning import story_director_context


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
    #    例外:正文自己交代了本章习得来源(系统奖励/师传/顿悟/秘籍)的,不算穿帮——
    #    事实核查跑在记账之前,新习得的技能本就还没进角色卡。语义判断交给 LLM 版,
    #    规则版只做最保守的拦截:正文里该技能名附近出现习得信号词,就跳过不报。
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
        acquire_signals = ("习得", "学会", "学得", "领悟", "顿悟", "参悟", "传授", "授予",
                           "教给", "记下", "记住", "奖励", "获得", "得到", "掌握", "练成", "修成")
        for sk_name in skill_patterns:
            if sk_name in all_known_skills or len(all_known_skills) == 0:
                continue
            # 正文里该技能名出现处的前后窗口若有习得信号词,视为本章新习得,不报
            acquired_in_text = False
            for m in re.finditer(re.escape(sk_name), text):
                window = text[max(0, m.start() - 40):m.end() + 40]
                if any(sig in window for sig in acquire_signals):
                    acquired_in_text = True
                    break
            if not acquired_in_text:
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
    REALM_SEQ = REALM_ORDER_WITH_MORTAL
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
    cur_day = float(tl.get("absolute_day") or 1)
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
    # 标题行 "# 第X章 标题" 是 writer 必须输出的格式(run_pipeline 清洗逻辑靠它当锚点切掉
    # 模型吐在正文前的思考过程),不算泄露。只检测正文内部的"第X章":先剥离 markdown 标题行,再查。
    body_no_heading = re.sub(r"^#+\s*第\d+章[^\n]*$", "", text, flags=re.MULTILINE)
    if re.search(r"第\d+章", body_no_heading):
        issues.append("正文泄露元信息：出现'第X章'系统编号。角色回忆应用'上回/那天/之前'。")
    meta_leaks = ["beat", "台账", "角色卡", "卷纲", "弧线规划", "伏笔编号", "F-0"]
    for leak in meta_leaks:
        if leak in text:
            issues.append(f"正文泄露系统元信息: '{leak}'")
            break
    # "不是A是B"是已验证长期复发的无歧义 AI 腔坏味道；只检测引号外叙述部分。
    narrative_parts = re.sub(r'("[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』)', '', text)
    not_a_is_b = re.findall(r'不是[^，。！？"\n]{1,20}[，—]+\s*是[^。！？"\n]{1,20}', narrative_parts)
    if not_a_is_b:
        issues.append(f"AI腔'不是A是B'句式在叙述中出现{len(not_a_is_b)}次（已全禁）：{'｜'.join(s[:15] for s in not_a_is_b[:3])}")
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
                warnings.append(f"疑似照抄角色伪例（交 reviewer 判断）: {example}")
    paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
    # 长段落/长句/正文偏长 已去牙(style_gate metrics 有中性数字给 reviewer)。
    sentences = [s.strip() for s in re.split(r"[。！？!?\n]+", text) if s.strip()]
    for phrase in filler_phrases:
        if text.count(phrase) >= 1:
            warnings.append(f"疑似注水/AI泛化表达（交 reviewer 判断）: {phrase}")
    dialogue_lines = [line for line in paragraphs if "\"" in line or "“" in line or "”" in line]
    explain_hits = []
    for line in dialogue_lines:
        for pattern in explain_dialogue_patterns:
            if re.search(pattern, line):
                explain_hits.append(line[:80])
                break
    if explain_hits:
        warnings.append(f"疑似解释型对话 {len(explain_hits)} 处（交 reviewer 判断）。")
    last_part = text[-400:]
    if any(phrase in last_part for phrase in empty_hook_phrases):
        warnings.append("章末疑似空钩子：抽象危机词出现在最后400字（交 reviewer 判断）。")
    # 章末钩子：源文统计悬念词收尾0%，靠短句留白。最后200字若靠"突然/竟然"式词收尾，软提醒
    cliche_hook_words = ["突然", "忽然", "竟然", "没想到", "万万没想到", "下一刻", "就在这时", "殊不知"]
    hook_zone = text[-200:]
    hook_hits = [w for w in cliche_hook_words if w in hook_zone]
    if hook_hits:
        warnings.append(f"章末钩子疑似用廉价悬念词收尾（{'/'.join(hook_hits)}）；源文风格靠短句和留白，建议改。")
    # 视觉穿帮：只卡两种真突兀——白天强光场景的精细视觉、装瞎场景却写主角看清
    vision_issues = check_vision_consistency(text)
    warnings.extend(vision_issues)
    short_sentences = [s for s in sentences if len(s) <= 10]
    if sentences and len(short_sentences) / len(sentences) < 0.25:
        warnings.append("超短句比例偏低，文字可能被修得太平滑。")
    sentence_lengths = [len(s) for s in sentences]
    if len(sentence_lengths) >= 20:
        avg = sum(sentence_lengths) / len(sentence_lengths)
        variance = sum((length - avg) ** 2 for length in sentence_lengths) / len(sentence_lengths)
        if variance < 35:
            warnings.append("句长方差偏低，疑似过度工整。")
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
    warnings: List[str] = []
    # 情绪总结词是 AI 腔标志，但属文风审美，降为 warning 交 reviewer；数字已在 metrics 里。
    if metrics["emotion_summary_count"] > 0:
        warnings.append(f"出现情绪总结词 {metrics['emotion_summary_count']} 次（交 reviewer 判断）。")
    return {"passed": not issues, "issues": issues, "warnings": warnings, "metrics": metrics}


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


def cast_checklist_for_reviewer(text: str) -> str:
    """从 ledger 提取正文中出现的角色/实体的核实清单,供 reviewer 校验一致性。
    每条只含:名字、类型/物种、voice、关键标识。极精简,通常 < 200 tokens。"""
    ledger = load_ledger()
    entities = ledger.get("entities") or {}
    mentioned = extract_character_mentions(text)
    lines = []
    for name in sorted(mentioned):
        e = entities.get(name)
        if not e or not isinstance(e, dict):
            continue
        etype = e.get("type", "?")
        summary_short = (e.get("summary") or "")[:40]
        voice = e.get("voice") or ""
        parts = [f"[{etype}] {name}：{summary_short}"]
        if voice:
            parts.append(f"  语言：{voice[:60]}")
        lines.append("\n".join(parts))
    if not lines:
        return ""
    return "以下是本章出场角色/实体的台账信息,请核对正文是否与之矛盾（名称、物种、身份、语言特征等）：\n" + "\n".join(lines)


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
    beat: Optional[Dict[str, Any]] = None,
) -> str:
    from pipeline.summarizer import repetition_context_for_reviewer
    checklist = cast_checklist_for_reviewer(text)
    rep_ctx = repetition_context_for_reviewer(chapter)
    # prompt 缓存优化:静态评判标准(风格指南/AI腔黑名单,跨章不变)排最前建缓存前缀;
    # 故事总监批注每5章变一次(半静态)居中;每章变的(beat/硬检查/正文/清单)排后面。
    sections = [
        make_section("风格指南", read_text(BASE_DIR / "01-风格指南.md"), "critical", False),
        make_section("AI腔黑名单", read_text(BASE_DIR / "12-AI腔黑名单.md"), "critical", False),
        make_section("故事总监批注", story_director_context(chapter), "critical", False),
        make_section("本章 beat（评判基准：写手是否忠实执行了这个规划）",
                     json.dumps(beat, ensure_ascii=False, indent=2) if beat else "无",
                     "critical", False) if beat else None,
        make_section(
            "脚本硬检查结果",
            json.dumps(diagnostics or {}, ensure_ascii=False, indent=2),
            "high",
            False,
        ),
        make_section("出场角色核实清单", checklist, "high", False) if checklist else None,
        make_section("近期章节表达摘要（检查本章是否重复）", rep_ctx, "high", True) if rep_ctx else None,
        make_section("待评审正文", text, "critical", False),
    ]
    sections = [s for s in sections if s]
    return compress_sections_if_needed("reviewer", chapter, sections, run_cfg, timeout)


def _parse_review_keywords(review: str) -> bool:
    """关键词 fallback:JSON 解析失败时,从文字报告里捞硬性必修信号。
    这是 #6 之前唯一在跑的机制,现降级为兜底第二条腿。"""
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


def parse_review_verdict(review: str) -> Dict[str, Any]:
    """解析 reviewer 双轨输出:优先读结构化 JSON 判定块,失败则回退关键词匹配。
    边界处理(主链,已与用户敲定):
      ① JSON 合法 → 读 needs_revision/total/blockers
      ② markdown包裹/尾逗号 → 复用 _sanitize_model_json 代码洗一遍(不重调模型)
      ③ 洗完仍失败 → fallback 关键词匹配(_parse_review_keywords)
      ④ 关键词也没命中 → 默认放行(needs_revision=False),靠后续 final_gate 兜硬伤
    返回 {needs_revision, total, blockers, source}。source 标明判定来自 json/keyword,便于排查。"""
    # 优先抓第一个 ```json 围栏块(reviewer 输出 JSON 在前、markdown 在后,不能用 first{..last})
    block = None
    m = re.search(r"```json\s*(\{.*?\})\s*```", review, re.DOTALL)
    if m:
        block = m.group(1)
    else:
        # 没围栏:退而求其次,抓第一个 { 到与之匹配的 }(粗取,靠 sanitize 兜)
        start = review.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(review)):
                if review[i] == "{":
                    depth += 1
                elif review[i] == "}":
                    depth -= 1
                    if depth == 0:
                        block = review[start:i + 1]
                        break
    if block:
        for candidate in (block, _sanitize_model_json(block)):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and "needs_revision" in data:
                    return {
                        "needs_revision": bool(data.get("needs_revision")),
                        "total": data.get("total"),
                        "scores": data.get("scores") or {},
                        "blockers": data.get("blockers") or [],
                        "source": "json",
                    }
            except (json.JSONDecodeError, ValueError):
                continue
    # ③④ 解析失败:回退关键词;命中=必修,没命中=默认放行
    kw = _parse_review_keywords(review)
    return {"needs_revision": kw, "total": None, "scores": {}, "blockers": [], "source": "keyword"}


def parse_score_needs_revision(review: str) -> bool:
    return parse_review_verdict(review)["needs_revision"]


def needs_revision(gate: Dict[str, Any], review: str) -> bool:
    return (not gate.get("passed")) or parse_score_needs_revision(review)


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


def continuity_check_adjacent(chapter: int, draft_text: str, beat: Optional[Dict[str, Any]] = None) -> List[str]:
    """对比上一章末尾 vs 本章开头，用正则检查衔接断裂。
    零 token 成本的轻量版，只抓明显矛盾。返回问题列表（空=通过）。
    POV 章（插叙/补叙）跳过——时间线本来就不连续。"""
    # POV 插叙/补叙章跳过衔接检查
    if beat:
        pov_char = beat.get("视角角色", "沈安")
        narrative_method = beat.get("叙事手法", "顺叙")
        if pov_char != "沈安" and narrative_method in ("插叙", "补叙"):
            return []

    prev_path = manuscript_path(chapter - 1)
    if not prev_path.exists():
        return []
    prev_text = read_text(prev_path)
    if not prev_text.strip():
        return []

    prev_tail = prev_text[-600:] if len(prev_text) > 600 else prev_text
    curr_head = draft_text[:600] if len(draft_text) > 600 else draft_text
    issues = []

    # 时间信号词
    night_words = ["夜里", "夜间", "夜色", "月光", "月色", "星光", "黑夜", "暗夜", "灯火", "烛光", "几更天", "三更", "二更", "四更", "五更"]
    day_words = ["清晨", "早晨", "日头", "阳光", "晌午", "正午", "白天", "天亮", "天明", "日光", "烈日", "大太阳"]

    prev_night = any(w in prev_tail for w in night_words)
    prev_day = any(w in prev_tail for w in day_words)
    curr_night = any(w in curr_head for w in night_words)
    curr_day = any(w in curr_head for w in day_words)

    # 上章末尾明确是夜，本章开头明确是白天（没有过渡词）
    transition_words = ["翌日", "次日", "第二天", "天亮", "天明", "醒来", "一夜", "清晨"]
    has_transition = any(w in curr_head for w in transition_words)
    if prev_night and not prev_day and curr_day and not curr_night and not has_transition:
        issues.append("[时间] 上章末尾是夜间，本章开头直接变白天，缺少过渡（翌日/天亮/醒来等）")

    # 地点连续性：提取上章末尾的地点词，检查本章开头是否无故换地方
    location_patterns = [
        r"(回到|走进|来到|进了|到了|坐在|站在|躺在)([一-鿿]{2,6})",
        r"(在)([一-鿿]{2,4})(里|中|内|外|旁|边|前|后)",
    ]
    prev_locations = set()
    for pat in location_patterns:
        for m in re.finditer(pat, prev_tail[-200:]):
            prev_locations.add(m.group(2) if len(m.groups()) >= 2 else m.group(0))

    # 动作连续性：上章末尾角色在做什么
    departure_words = ["离开", "走了", "离去", "转身走", "远去", "消失在"]
    sleep_words = ["睡下", "入睡", "闭眼", "沉沉睡去", "合眼"]

    prev_departed = any(w in prev_tail[-150:] for w in departure_words)
    prev_sleeping = any(w in prev_tail[-150:] for w in sleep_words)

    # 如果上章末尾主角已经离开/走了，本章开头又在同一个地方做事（没有"回来"）
    if prev_departed:
        return_words = ["回来", "折返", "又回到", "返回", "回到"]
        has_return = any(w in curr_head for w in return_words)
        re_depart = any(w in curr_head[:100] for w in departure_words)
        if re_depart and not has_return:
            issues.append("[动作] 上章末尾角色已离开，本章开头又重复离开动作，疑似衔接断裂")

    # 如果上章末尾角色入睡，本章开头没有醒来过渡就直接行动
    if prev_sleeping:
        wake_words = ["醒", "睁眼", "起身", "天亮", "翌日", "清晨"]
        action_words = ["走", "跑", "说", "问", "答", "拿", "推", "拉"]
        has_wake = any(w in curr_head[:150] for w in wake_words)
        immediate_action = any(w in curr_head[:50] for w in action_words)
        if immediate_action and not has_wake:
            issues.append("[动作] 上章末尾角色入睡，本章开头直接行动，缺少醒来过渡")

    return issues


