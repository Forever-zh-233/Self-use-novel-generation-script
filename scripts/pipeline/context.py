# -*- coding: utf-8 -*-
"""pipeline.context — all context builders for writer/reviewer/planner."""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    BASE_DIR, PROMPTS_DIR, CONFIG_DIR, RUNTIME_DIR,
    VOLUME_SUMMARY_FILE, CHARACTER_ARCS_FILE, LONG_FORESHADOWING_FILE,
    WRITER_MODULES_DIR, REALM_ORDER, REALM_ORDER_WITH_MORTAL, REALM_ORDINALS,
    cli_print, estimate_tokens, load_json, manuscript_path, read_text,
    role_artifact, write_text,
)
from pipeline.api import call_role, role_compress_threshold
from pipeline.state import (
    chunk_aliases, load_chunk, load_index, load_ledger, load_state,
    load_strand_config, normalize_strand, resolve_chunk_key,
)

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


def make_section(title: str, body: str, priority: str = "normal", compressible: bool = True) -> Dict[str, Any]:
    return {
        "title": title,
        "body": body,
        "priority": priority,
        "compressible": compressible,
        "tokens": estimate_tokens(body),
    }


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
        cur_day = float(tl.get("absolute_day") or 0)
        # 只显示未过期的高紧急计时器(due_day 已过的是陈旧数据,不再提醒)
        urgent = [
            t for t in (tl.get("pending_timers") or [])
            if t.get("urgency") in ("极高", "高") and float(t.get("due_day") or 999) >= cur_day
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


# ========================= 分层空间系统（防穿帮·小地图）=========================
# 每层只取自己尺度的空间感：弧线拿聚落级方位，章节/写手拿场景级布局。
# 静默原则：没有空间数据就返回空串，下游不注入。复用 ledger entities(type=地点)。

def _location_entities() -> Dict[str, Any]:
    ledger = load_ledger()
    entities = ledger.get("entities") or {}
    return {n: e for n, e in entities.items()
            if isinstance(e, dict) and e.get("type") == "地点" and e.get("status") not in ("退场", "沉睡")}


def spatial_digest_for_arc(chapter: int) -> str:
    """弧线规划师专用：聚落级地点方位摘要。
    给弧线规划师看"这片区域有哪些地方、相对位置"，让它规划场景群时不写错方位。
    只给方位骨架，不给场景内布局（那是章节/写手的尺度）。"""
    locs = _location_entities()
    if not locs:
        return ""
    lines: List[str] = []
    for name, e in locs.items():
        bits = []
        if e.get("bearing_from_parent"):
            parent = e.get("parent") or ""
            bits.append(f"{parent}{('·' if parent else '')}{e['bearing_from_parent']}")
        landmarks = e.get("landmarks") or []
        if landmarks:
            lm_str = "、".join(f"{lm.get('name','')}({lm.get('bearing','')})" for lm in landmarks[:6] if isinstance(lm, dict))
            if lm_str:
                bits.append(f"内含：{lm_str}")
        if bits:
            lines.append(f"- {name}：{'；'.join(bits)}")
    if not lines:
        return ""
    return "已登记地点的相对方位（规划场景群时遵守，别把镇东的写到镇西）：\n" + "\n".join(lines)


def _layout_for_locations(loc_names: set) -> str:
    """从 ledger 调出指定地点的场景内布局，给章节/写手用。"""
    locs = _location_entities()
    lines: List[str] = []
    for name in loc_names:
        e = locs.get(name)
        if not e:
            continue
        if e.get("layout"):
            lines.append(f"- {name}：{e['layout']}")
        # 内部地标也带上（场景内方位）
        landmarks = e.get("landmarks") or []
        if landmarks:
            lm_str = "、".join(f"{lm.get('name','')}({lm.get('bearing','')})" for lm in landmarks[:6] if isinstance(lm, dict))
            if lm_str:
                lines.append(f"  {name}内部：{lm_str}")
    return "\n".join(lines)


def _beat_location_names(beat: Dict[str, Any]) -> set:
    """从 beat 里提取本章涉及的地点名（匹配已登记地点）。"""
    locs = _location_entities()
    if not locs:
        return set()
    beat_text = json.dumps(beat, ensure_ascii=False)
    hit = {name for name in locs if name in beat_text}
    # 也算上当前地点
    cur = (load_state().get("current_location") or "")
    if cur and cur in locs:
        hit.add(cur)
    return hit


def layout_for_beat(beat: Dict[str, Any]) -> str:
    """章节规划师专用：本章相关地点的既有布局。
    让 beat_planner 安排走位时，知道这个场景长什么样，不凭空改陈设。"""
    names = _beat_location_names(beat)
    if not names:
        return ""
    body = _layout_for_locations(names)
    if not body:
        return ""
    return "本章涉及地点的既有布局（安排场景和走位时遵守，不要改动已确立的方位/陈设）：\n" + body


def layout_for_writer(beat: Dict[str, Any]) -> str:
    """写手专用：本章空间布局。
    合并 beat 的「空间布局」字段（章节规划师定的）+ ledger 既有 layout（前几章确立的）。
    写手落笔时严格遵守。"""
    parts: List[str] = []
    beat_layout = beat.get("空间布局")
    if beat_layout:
        if isinstance(beat_layout, (list, dict)):
            beat_layout = json.dumps(beat_layout, ensure_ascii=False)
        parts.append(f"【本章布局指令（章节规划师定，必须落实）】\n{beat_layout}")
    names = _beat_location_names(beat)
    existing = _layout_for_locations(names) if names else ""
    if existing:
        parts.append(f"【既有布局（前文确立，不能矛盾）】\n{existing}")
    return "\n\n".join(parts)


def ledger_context_for_planner(chapter: int) -> str:
    """规划层专用账本视图：只给摘要级信息，不给全量 facts/secrets/skills。
    到800章也稳定在 ~3000-4000 tokens。"""
    ledger = load_ledger()
    lines: List[str] = []

    # 物品一行摘要
    inventory = ledger.get("inventory") or {}
    inv_parts = []
    currency = inventory.get("currency") or {}
    if currency:
        inv_parts.extend(f"{k}{v}" for k, v in currency.items() if k != "notes" and v)
    key_items = [i.get("name", "") for i in (inventory.get("key_items") or []) if isinstance(i, dict) and i.get("status") == "持有"]
    if key_items:
        inv_parts.append(f"持有：{'、'.join(key_items[:8])}")
    if inv_parts:
        lines.append(f"【物品】{'；'.join(inv_parts)}")

    # 未结清账（本来就有界）
    open_obs = [o for o in (ledger.get("obligations") or []) if isinstance(o, dict) and o.get("status") != "已结"]
    if open_obs:
        lines.append(f"【未结清账·{len(open_obs)}笔】")
        for o in open_obs:
            lines.append(f"  - {o.get('id','')} {o.get('desc','')}（起于第{o.get('since_chapter','?')}章）")

    # 约束：永久铁律全留 + 情境约束最近 10 条
    constraints = [c for c in (ledger.get("constraints") or []) if isinstance(c, dict) and c.get("binding") == "强"]
    permanent = [c for c in constraints if c.get("scope") == "永久" or c.get("permanent")]
    situational = [c for c in constraints if c not in permanent][-10:]
    show_constraints = permanent + situational
    if show_constraints:
        lines.append(f"【约束·{len(show_constraints)}条】")
        for c in show_constraints:
            lines.append(f"  - {c.get('desc','')}")

    # 实体索引：活跃实体一行摘要
    entities = ledger.get("entities") or {}
    entity_lines = []
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        if e.get("status") in ("退场", "沉睡"):
            continue
        last_seen = int(e.get("last_seen_chapter") or 0)
        if chapter and last_seen and (chapter - last_seen) > 30:
            continue
        realm = f"·{e['realm']}" if e.get("realm") else ""
        entity_lines.append(f"  {name}（{e.get('type','?')}{realm}）：{(e.get('summary') or '')[:40]}")
    if entity_lines:
        lines.append(f"【实体索引·{len(entity_lines)}个活跃】")
        lines.extend(entity_lines[:25])

    # 关系：只给最近有变动的
    rels = ledger.get("relationships") or {}
    rel_lines = []
    for pair, node in rels.items():
        if not isinstance(node, dict):
            continue
        history = node.get("history") or []
        recent = [h for h in history if isinstance(h, dict) and int(h.get("chapter") or 0) >= chapter - 5]
        if recent or not history:
            rel_lines.append(f"  {pair}：{node.get('current','')}")
    if rel_lines:
        lines.append(f"【近期关系变动·{len(rel_lines)}对】")
        lines.extend(rel_lines[:15])

    return "\n".join(lines) or "暂无正典账本。"


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
        lines.append("【物品清单（硬事实——正文提到数量时必须与此一致，不可凭感觉改数字）】")
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
    # 与约束账同款过滤：本章出场角色相关的债优先全留(防穿帮——别把有债的人写成陌生人/写得像已还),
    # 其余不相关的债只取最近若干降噪。"该不该还"的决策在规划层(obligations_due_digest),不在此。
    open_obs = [o for o in (ledger.get("obligations") or []) if isinstance(o, dict) and o.get("status") != "已结"]
    if open_obs:
        relevant_obs = [o for o in open_obs if any(name in (o.get("desc") or "") for name in cast)]
        recent_obs = [o for o in open_obs if o not in relevant_obs][-8:]
        show_obs = relevant_obs + recent_obs
        lines.append("\n【未结清账·悬空中（还没还的债/承诺/因果，写作时要记得它们还悬着）】")
        for o in show_obs:
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
            appearance = f"\n  外貌：{e['appearance']}" if e.get("appearance") else ""
            mannerisms = ""
            if e.get("mannerisms"):
                man_list = [str(m) for m in e["mannerisms"] if m][:5]
                if man_list:
                    mannerisms = f"\n  习惯动作：{'、'.join(man_list)}（这是固定习惯，可有意识地用一两处保持人物一致，但别每章原样照搬同一个动作当填充）"
            # 过滤 facts 中提到已消耗物品的旧条目（防止 qty=0 的东西通过 facts 泄露给 writer）
            depleted_items = set()
            for cat in ("consumables", "key_items"):
                for item in (inventory.get(cat) or []):
                    if (isinstance(item, dict) and (item.get("qty") == 0 or item.get("status") in ("已销毁", "已丢失"))):
                        depleted_items.add(item.get("name", ""))
            raw_facts = (e.get("facts") or [])[:6]
            if depleted_items:
                raw_facts = [f for f in raw_facts if not any(d in f for d in depleted_items if d)]
            facts = "".join(f"\n  - {f}" for f in raw_facts)
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
            active_cards.append(f"- [{e.get('type','?')}] {name}：{e.get('summary','')}{voice}{appearance}{mannerisms}{realm}{skills}{weapons}{injuries}{goal}{arc_str}{enemies_str}{facts}")
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

    # —— 技能库：beat 里提到的技能/针法/功法注入完整卡,保证写手知道已确立的细节 ——
    tech_lib = ledger.get("technique_library") or {}
    if tech_lib:
        matched_techs = []
        for tech_name, tech_data in tech_lib.items():
            # 匹配策略:技能全名、名字里的2+字子串、type 拆词
            candidates = [tech_name]
            for n in range(2, len(tech_name) + 1):
                for i in range(len(tech_name) - n + 1):
                    frag = tech_name[i:i + n]
                    if len(frag) >= 2:
                        candidates.append(frag)
            if tech_data.get("type"):
                candidates.extend(t for t in tech_data["type"].split("/") if len(t) >= 2)
            if any(c in beat_text for c in candidates):
                matched_techs.append((tech_name, tech_data))
        if matched_techs:
            lines.append("\n【技能详情·已确立的操作细节（写到该技能时保持一致,但不限制你发展新细节）】")
            for tech_name, td in matched_techs[:5]:
                details = td.get("core_details") or {}
                detail_str = "；".join(f"{k}={v}" for k, v in details.items() if v)
                evol = td.get("evolution") or []
                last_evol = evol[-1]["note"] if evol else ""
                lines.append(f"- 【{tech_name}】({td.get('type','')}) {detail_str}")
                if last_evol:
                    lines.append(f"  最新进展：{last_evol}")

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


def recent_expectation_tail(lookback: int = 6, max_chars: int = 6000) -> str:
    """期待账本（08-期待账本.md）有界读取，同 recent_ledger_tail 的思路。
    病根：archivist 每章 append「### 第N章自动更新」块，到136章已 136 块 / 近3万 token，
    却被 story_director/volume_planner/arc_planner 三处全量 read_text 注入。
    它本是 append-only 人类可读账本，全量注入纯属冗余——规划层要的「当前还有哪些
    未回收伏笔」已由 structured_state_text 的有界伏笔摘要 + overdue_foreshadowing_digest
    覆盖。这里只给表头 + 最近 lookback 章的增量块。"""
    text = read_text(BASE_DIR / "08-期待账本.md")
    if not text:
        return ""
    blocks = re.split(r"(?=### 第\d+章自动更新)", text)
    head = blocks[0] if blocks and not blocks[0].lstrip().startswith("### 第") else ""
    chapter_blocks = [b for b in blocks if b.lstrip().startswith("### 第")]
    recent = chapter_blocks[-lookback:] if chapter_blocks else []
    result = (head.strip() + "\n\n" + "\n".join(recent).strip()).strip()
    if not result:
        result = (head or text)[:1500]
    if len(result) > max_chars:
        result = result[:len(head) + 200] + "\n…（更早增量已省略，未回收全貌见结构化状态的伏笔摘要）\n" + result[-max_chars:]
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


def current_mc_realm() -> str:
    """MC 当前境界。权威源是 ledger.entities.沈安.realm（archivist 维护、gate/power_scaling
    都读它）；state.mc_realm 只是旧的兜底镜像，长期从没被写过（=None），导致这里以前永远
    返回 fallback「叩门」，而 ledger 记的却是「凡人」——两个数据源各说各话，是 realm 卡死
    bug 的一半根因。改为：ledger.realm 优先，其次 state.mc_realm，最后才 fallback。"""
    ledger = load_ledger()
    mc = (ledger.get("entities") or {}).get("沈安", {})
    led_realm = mc.get("realm") if isinstance(mc, dict) else None
    state = load_state()
    for src in (led_realm, state.get("mc_realm")):
        if isinstance(src, str) and src.strip():
            for name in REALM_ORDER:
                if name in src:
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
        return full_text

    cli_print(f"  [!] {role} {total_tokens:,} tok > {threshold:,}，压缩中...")
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


def planner_craft_chunks() -> str:
    """给规划层(arc_planner)看的原书手法卡:多视角切换/三线交织/修炼线编织/配角塑造。
    这几张是 analyst 从原书学的【规划层该懂的编织手法】,不同于 writer 的句法卡。
    存在才注入(C 阶段 analyst 重跑产出后 index 里才有),不存在静默返回空串——
    先接好这根管子,等 C 的料产出自动生效(先接管子后灌料)。"""
    index = load_index()
    if not index:
        return ""
    planner_cards = ["多视角切换", "三线交织", "修炼线编织", "配角塑造"]
    parts = []
    for key in planner_cards:
        if key in index:
            body = load_chunk(key, index)
            if body.strip():
                parts.append(f"### {key}\n{body.strip()}")
    if not parts:
        return ""
    return ("以下是分析师从原书提炼的编织手法（学它的做法，不是套公式；"
            "原书怎么切视角/编三线/写修炼/塑配角，借鉴其节奏与轻重缓急）：\n\n"
            + "\n\n".join(parts))


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
        # analyst 五维度新卡(C 阶段重跑后 index 才有;没跑前 chunk_name not in index 不点亮)
        ("信息差经营", ["信息差", "隐瞒", "瞒", "不知道", "识破", "暴露", "装", "潜台词", "试探", "盘算", "秘密"]),
        ("配角塑造", ["配角", "出场角色", "议程", "盘算", "他自己的", "旁人", "路人", "其他角色"]),
        ("多视角切换", ["视角", "POV", "切视角", "他的眼睛", "换视角", "另一个人"]),
        ("修炼线编织", ["修炼", "境界", "真气", "瓶颈", "突破", "灵气", "修为", "运气", "丹田", "经脉", "修炼锚点"]),
        ("三线交织", ["三线", "道途", "情义", "天地", "交织", "缠绕", "并行", "多线"]),
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
    # 命中数多的优先选入(更贴合本章);同分按 keyword_chunks 原顺序(稳定)
    candidates.sort(key=lambda x: -x[0])
    chosen = candidates[:MAX_KEYWORD_CHUNKS]
    # 缓存优化:选出哪几张由命中数决定,但「输出顺序」固定按 keyword_chunks 定义序,
    # 不按命中数排。否则同一组卡因命中数逐章波动而顺序抖动,破 prompt 缓存前缀。
    chunk_order = {name: i for i, (name, _kw) in enumerate(keyword_chunks)}
    chosen.sort(key=lambda x: chunk_order.get(x[1], 999))
    for _hits, chunk_name in chosen:
        selected[f"功能_{chunk_name}"] = load_chunk(chunk_name, index)
        selected_chunk_keys.add(chunk_name)
    for char in (beat.get("出场角色") or ["沈安"])[:4]:
        char_key = resolve_chunk_key(str(char), index)
        if char_key:
            selected[f"角色_{char}"] = load_chunk(char_key, index)
            selected_chunk_keys.add(char_key)
    return selected


# ──────────────────────────────────────────────────────────────────────
# 三线节奏(Strand Weave)。机制思路抄自竞品,按本书玄幻长生内核重定义为
# 道途/情义/天地三线。阈值全在 config/strand_weave.json,代码不写死配比。
# 关键:"本章主导哪条线"由 archivist(LLM)打 dominant_strand 标签,代码只
# 维护计数器、比配比、报断档——零文风/剧情硬编码,符合反 gaming 原则。
# ──────────────────────────────────────────────────────────────────────
def strand_pacing_warnings(chapter: int) -> str:
    """读 strand_tracker + config,生成三线节奏警告(连续主导/断档/配比失衡)。
    纯代码、只警告不阻断,与 pacing_variety_warnings 同款模式。给 writer 看。"""
    cfg = load_strand_config()
    if not cfg or cfg.get("enabled") is False:
        return ""
    strands = cfg.get("strands") or {}
    state = load_state()
    tracker = state.get("strand_tracker") or {}
    history = [h for h in (tracker.get("history") or []) if isinstance(h, dict)]
    if not history:
        return ""
    ramp_up = int(cfg.get("ramp_up_chapters") or 0)
    cooldown = max(1, int(cfg.get("nag_cooldown") or 1))
    warnings: List[str] = []
    # 1. 连续主导(只对设了 max_consecutive 的线,通常是道途线)。软提示:给契机不下命令。
    cur = tracker.get("current_dominant")
    consec = int(tracker.get("consecutive") or 0)
    cur_info = strands.get(cur) or {}
    max_consec = cur_info.get("max_consecutive")
    if max_consec and consec >= int(max_consec) and chapter > ramp_up:
        # 冷却:跨线后第1章喊,之后每隔 cooldown 章才再喊,避免连环催
        over = consec - int(max_consec)
        if over % cooldown == 0:
            other = [s for s in strands.keys() if s != cur]
            warnings.append(
                f"三线提示:已连续{consec}章以「{cur}」为主导。若本章有自然契机,可让{'/'.join(other)}承重换口气;"
                f"没有合适契机就别硬转,顺其自然。"
            )
    # 2. 断档(对设了 max_gap 的线)。同样软化+冷却,绝不要求每章硬塞。
    key_map = {"道途线": "last_道途", "情义线": "last_情义", "天地线": "last_天地"}
    for canon, info in strands.items():
        max_gap = info.get("max_gap")
        if not max_gap:
            continue
        last = tracker.get(key_map.get(canon, ""))
        gap = (chapter - int(last)) if last else chapter
        if gap > int(max_gap) and chapter > ramp_up:
            # 冷却:跨红线后第1章喊,之后每 cooldown 章才再喊一次
            over = gap - int(max_gap) - 1
            if over % cooldown == 0:
                warnings.append(
                    f"三线提示:「{canon}」已{gap}章没作为主导出现({info.get('desc','')[:16]})。"
                    f"如后续有合适契机不妨带入一笔,不必为凑配比硬塞——契机比配比重要。"
                )
    if warnings:
        warnings.insert(0, "（三线是几十章自然摊平的节奏参考,不是每章KPI;一章只主推一条很正常,下面只是提个醒,有契机才用。）")
    return "\n".join(warnings)


def strand_digest_for_director(chapter: int) -> str:
    """给 story_director 看的三线配比摘要,比 writer 警告更全(含实际占比)。"""
    cfg = load_strand_config()
    if not cfg or cfg.get("enabled") is False:
        return ""
    strands = cfg.get("strands") or {}
    state = load_state()
    tracker = state.get("strand_tracker") or {}
    history = [h for h in (tracker.get("history") or []) if isinstance(h, dict)]
    if not history:
        return ""
    lookback = int(cfg.get("ratio_lookback") or 20)
    window = [h for h in history if int(h.get("chapter", 0)) > chapter - lookback]
    total = len(window) or 1
    from collections import Counter
    counts = Counter(normalize_strand(h.get("dominant")) for h in window)
    lines = [f"【三线配比】最近{len(window)}章:"]
    for canon, info in strands.items():
        n = counts.get(canon, 0)
        ratio = n / total
        lo = info.get("target_ratio_min", 0)
        hi = info.get("target_ratio_max", 1)
        flag = ""
        if ratio < lo:
            flag = f" ⚠偏低(目标{int(lo*100)}-{int(hi*100)}%)"
        elif ratio > hi:
            flag = f" ⚠偏高(目标{int(lo*100)}-{int(hi*100)}%)"
        lines.append(f"- {canon}:{n}/{total}={int(ratio*100)}%{flag}")
    consec = int(tracker.get("consecutive") or 0)
    cur = tracker.get("current_dominant") or "?"
    lines.append(f"当前连续主导:「{cur}」×{consec}章")

    # 道途线混合袋拆解:在道途线主导的章里,有多少是真有修炼实质(active),
    # 多少只是行医/治心病。暴露空洞给 story_director 定性判断,不设硬阈值。
    cult_cfg = cfg.get("cultivation_sub_tag") or {}
    if cult_cfg.get("enabled"):
        dao_window = [h for h in window if normalize_strand(h.get("dominant")) == "道途线"]
        if dao_window:
            from collections import Counter as _C
            cc = _C(h.get("cultivation") or "none" for h in dao_window)
            active = cc.get("active", 0)
            trace = cc.get("trace", 0)
            none_n = cc.get("none", 0)
            nd = len(dao_window)
            # 全局看:最近一次有修炼实质(active)是第几章
            last_active = max((int(h.get("chapter", 0)) for h in history
                               if h.get("cultivation") == "active"), default=0)
            gap_note = f"，距上次修炼实质已 {chapter - last_active} 章" if last_active else "，窗口内从无修炼实质"
            lines.append(
                f"【道途线含修炼实质】道途线 {nd} 章中:实质修炼 {active}、夹缝带过 {trace}、纯行医无修炼 {none_n}"
                f"（修炼实质占道途线 {int(active/nd*100)}%{gap_note}）"
            )
            lines.append("  （供定性判断:道途线达标不代表修炼有存在感。若长期纯行医、修炼实质为零,说明'修行'名存实亡。是否该让境界往前啃由你判断,不是必须每章修炼。）")
    return "\n".join(lines)


def realm_progress_digest(chapter: int) -> str:
    """给 story_director 看的主角境界进度·停滞观察(定性,不设硬阈值)。
    realm 卡死曾是 bug(archivist 从不推进 realm,卡'凡人'到130章)。修复后这里暴露:
    当前境界、进入该境界多少章了、距上次跨境多久——让 director 定性判断'修行是否停摆',
    而不是机械要求'每 N 章必须突破'(那会诱发注水突破)。"""
    ledger = load_ledger()
    mc = (ledger.get("entities") or {}).get("沈安", {})
    if not isinstance(mc, dict):
        return ""
    realm = mc.get("realm") or "凡人"
    hist = (ledger.get("realm_progress") or {}).get("沈安") or []
    lines = [f"【主角境界】当前:{realm}"]
    if hist:
        last = hist[-1]
        last_ch = int(last.get("chapter") or 0)
        gap = chapter - last_ch
        lines.append(f"  上次跨境:第{last_ch}章 {last.get('from','?')}→{last.get('to','?')}（已 {gap} 章未再跨境）")
        path = "→".join([hist[0].get("from", "?")] + [h.get("to", "?") for h in hist])
        lines.append(f"  境界轨迹:{path}")
    else:
        lines.append(f"  ⚠ 账本中无任何跨境记录。若正文里主角早已会运气/用术法,说明 realm 落后于剧情(历史欠账),archivist 应主动补正。")
    lines.append("  （定性参考:修炼是脊梁线。若境界长期停滞且正文也无'啃瓶颈'的实质过程,可考虑让修行往前走一步——但何时突破由剧情决定,不强求节奏。）")
    return "\n".join(lines)


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
    """检测最近 lookback 章的情绪基调是否过度单调。
    架构与三线占比/场景类型一致:语义判断归 LLM(beat_planner 在 beat 里写「情绪基调」),
    代码只数标签、不做任何关键词语义猜测。只警告不阻断,只给规划层(beat_planner)看。"""
    beats_dir = BASE_DIR / "beats"
    tones = []
    for ch in range(max(1, chapter - lookback), chapter):
        beat_path = beats_dir / f"chapter_{ch}.json"
        if beat_path.exists():
            beat = load_json(beat_path, {})
            tone = str(beat.get("情绪基调") or "").strip()
            # 没写情绪基调的章节(旧 beat 或留空)直接跳过,不替它猜
            if tone and tone != "无":
                tones.append(tone)
    if len(tones) < 4:  # 样本太少不警告,避免开局就纠偏
        return ""
    from collections import Counter
    counts = Counter(tones)
    dominant = counts.most_common(1)
    if dominant and dominant[0][1] >= len(tones) * 0.7:
        return (
            f"情绪基调提示:最近{len(tones)}章里「{dominant[0][0]}」占了{dominant[0][1]}/{len(tones)}。"
            "若后续仍顺其自然偏这个基调也无妨,但有合适契机时可调一调冷热,别让读者长期绷在同一种情绪上。"
        )
    return ""


def chapter_satisfaction_check(text: str, beat: Dict[str, Any]) -> List[str]:
    """正文客观下限检查。转折/承诺落地是创作判断，属 reviewer 职责。"""
    issues = []
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    if chinese_chars < 1800:
        issues.append(f"正文过短（{chinese_chars}字），疑似被截断")
    return issues


def power_scaling_for_chapter() -> str:
    """Return power scaling info for MC's current realm +/- 1."""
    scaling_file = BASE_DIR / "config" / "power_scaling.json"
    if not scaling_file.exists():
        return ""
    scaling = load_json(scaling_file, {})
    ledger = load_ledger()
    mc = (ledger.get("entities") or {}).get("沈安", {})
    mc_realm = mc.get("realm") or "叩门"
    REALMS = REALM_ORDER_WITH_MORTAL[:7]  # 凡人..归真，power_scaling.json 只配到前段
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


def writer_focus_modules(beat: Dict[str, Any], include_protagonist_sensory: bool = True) -> str:
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

    # 对话:场景类型含对话/日常,或 beat 里有潜台词机会(值不为"无")
    qtc = str(beat.get("潜台词机会") or "")
    qtc_active = bool(qtc) and not qtc.startswith("无")
    has_dialogue = any(k in scene for k in ["对话", "日常", "审", "问"]) or qtc_active
    if has_dialogue:
        add("对话")
    # 潜台词:仅当 beat 明确标注且不为"无"
    if qtc_active:
        add("潜台词")
    # 黑子:出场才注入
    if "黑子" in cast or "黑子" in beat_blob:
        add("黑子")
    if include_protagonist_sensory:
        # 主角核心感官规则；POV 章不默认注入，避免非盲人视角被写成沈安。
        add("视觉")
        add("盲感官")
    # 深度模块:仅当 beat 标注对应字段且不为"无"
    def field_active(key: str) -> bool:
        v = str(beat.get(key) or "").strip()
        if not v or v.startswith("无") or v in ("None", "积累中，未触发", "积累中,未触发"):
            return False
        return True
    if field_active("情绪裂缝"):
        add("情绪裂缝")
    if field_active("内在转变"):
        add("内在转变")
    if field_active("困境/两难") or field_active("主题折射"):
        add("困境主题")
    # 张力:beat 把本章标成"小起伏/小高潮"时,提醒写手给爆点足够分量,别写平
    tension = str(beat.get("本章张力") or "").strip()
    if any(k in tension for k in ("小起伏", "小高潮", "高潮")):
        add("张力")

    if not selected:
        return ""
    return "\n\n---\n\n".join(selected)


def style_metrics_digest_for_writer() -> str:
    """把 analyst 量化风格指标压成 writer 可执行的短摘要。
    只取数字特征，不注入 high_freq_words、源文专名或原句。"""
    metrics = load_json(BASE_DIR / "分析草稿" / "style_metrics.json")
    if not isinstance(metrics, dict) or not metrics:
        return ""

    def val(mapping: Dict[str, Any], key: str) -> str:
        value = mapping.get(key)
        if isinstance(value, float):
            return f"{value:.1f}"
        return str(value) if value is not None else "?"

    lines: List[str] = ["这是从源文本量化出的风格参考，只当执行校准，不当 KPI 硬凑。"]
    sentence = metrics.get("sentence") or {}
    if isinstance(sentence, dict) and sentence:
        lines.append(
            f"- 句长：均值 {val(sentence, 'mean')}，中位 {val(sentence, 'median')}，"
            f"p10/p90={val(sentence, 'p10')}/{val(sentence, 'p90')}；长短句要交替，别整章同一节拍。"
        )
    paragraph = metrics.get("paragraph") or {}
    single = metrics.get("single_sentence_paragraph") or {}
    if isinstance(paragraph, dict) and paragraph:
        ratio = val(single if isinstance(single, dict) else {}, "single_sentence_ratio_percent")
        lines.append(
            f"- 段落：均值 {val(paragraph, 'mean')} 字，中位 {val(paragraph, 'median')} 字；"
            f"单句成段约 {ratio}%，只在动作/反应/钩子处使用，别把每句都拆成 PPT。"
        )
    dialogue = metrics.get("dialogue_style") or {}
    if isinstance(dialogue, dict) and dialogue:
        lines.append(
            f"- 对话：纯引号约 {val(dialogue, 'pure_quote_ratio_percent')}%，"
            f"说话标签约 {val(dialogue, 'with_speaker_tag_ratio_percent')}%，"
            f"动作尾巴约 {val(dialogue, 'with_action_tail_ratio_percent')}%；少解释，多让动作和停顿承载潜台词。"
        )
    endings = metrics.get("chapter_endings") or {}
    if isinstance(endings, dict) and endings:
        lines.append(
            f"- 章末：末行均长约 {val(endings, 'avg_last_line_length')} 字，"
            f"短收束占比 {val(endings, 'short_ending_ratio_percent')}%，避免用抽象悬念词硬吊胃口。"
        )
    return "\n".join(lines[:5])


def append_selected_chunk_sections(
    sections: List[Dict[str, Any]],
    beat: Dict[str, Any],
    skip_role_names: Optional[List[str]] = None,
    only: Optional[str] = None,
) -> None:
    """把 select_chunks 选出的手法/角色卡注入 sections。
    only 参数控制注入哪一类(用于 prompt 缓存优化的分段排序):
      - "static": 只注入每章必出且内容不变的卡(黄金法则/负空间/AI腔黑名单/场景价值转变)
      - "dynamic": 只注入随 beat 变化的卡(其余功能卡 + 角色卡)
      - None(默认): 全注入,保持旧行为(其他角色复用此函数时不受影响)
    分段是为了让静态卡排进缓存前缀、动态卡排后面,不影响选卡逻辑本身。"""
    STATIC_CHUNK_NAMES = {"黄金法则", "负空间", "AI腔黑名单", "功能_场景价值转变"}
    skip_role_names = skip_role_names or []
    for name, content in select_chunks(beat).items():
        if any(name == f"角色_{role}" for role in skip_role_names):
            continue
        is_static = name in STATIC_CHUNK_NAMES
        if only == "static" and not is_static:
            continue
        if only == "dynamic" and is_static:
            continue
        priority = "critical" if name in ("黄金法则", "负空间", "AI腔黑名单") else "normal"
        sections.append(make_section(name, content, priority, priority != "critical"))


def build_writer_sections(beat: Dict[str, Any]) -> List[Dict[str, Any]]:
    chapter = int(beat.get("章节编号") or 0)
    # ── prompt 缓存优化:section 按「真静态→半静态→每章必变」物理排序。 ──
    # mimo 缓存按请求公共前缀命中,前缀遇第一个变化字节即全部失效。把跨章不变的
    # section 全排最前,最大化可缓存前缀;每章变的全排最后。语义不变,只换排列。
    #
    # 各 section 的 volatility(已逐函数核实,2026-06-09):
    #   真静态(纯文件读,只在改设定文档时变):故事核 / 世界观 / 4张固定手法卡
    #   半静态(罕变,变了才断后缀,平时蹭前缀):修炼境界(境界突破才变,~数十章一次)
    #     / 长线伏笔(archivist touch 才变)
    #   每章必变:卷纲窗口(逐章滑窗) / 台账日志(最近2章) / 其余按beat点亮的卡 / 状态/账本/beat/...
    # 旧顺序把每章变的卷纲、台账排在静态手法卡之前,导致4张纯静态卡常年丢缓存——这是命中率低的根。

    # 段1·真静态前缀(改设定文档才变,常年命中):故事核 / 世界观 / 固定手法卡(黄金法则/负空间/AI腔/场景价值转变)。
    sections: List[Dict[str, Any]] = [
        make_section("故事核安全版", safe_story_core_for_writer(), "critical", False),
        make_section("世界观设定安全版", safe_world_bible_for_writer(), "critical", False),
    ]
    append_selected_chunk_sections(sections, beat, only="static")
    # 段2·半静态(罕变,蹭段1缓存):修炼境界(境界突破才变) / 长线伏笔(archivist touch 才变)。
    sections.append(make_section("修炼境界安全版", safe_cultivation_for_writer(), "normal", True))
    sections.append(make_section("长线伏笔安全提醒", long_foreshadowing_text(chapter, writer_safe=True), "high", True))
    # 段3·每章必变(全排最后,不污染前缀):卷纲滑窗 / 台账日志 / beat点亮的动态卡 + 角色卡。
    sections.append(make_section("卷纲安全版", safe_outline_for_writer(chapter), "high", True))
    sections.append(make_section("最近台账日志摘录", recent_ledger_tail(), "low", True))
    append_selected_chunk_sections(sections, beat, only="dynamic")
    # 段3·每章必变:状态/账本/beat/写作要点/空间/意象/回响/境界/旅行/经济/防重复。
    # 正典账本：悬空账/强约束/资源常驻不可压缩，是防穿帮和逻辑崩坏的命门
    sections.append(make_section("即时状态（时间线/地点/本章角色状态）", writer_state_digest(beat), "high", True))
    sections.append(make_section("正典账本（资源/未结清账/约束/本章相关实体与关系）", ledger_context_for_writer(beat), "critical", False))
    # 血肉：本章出场角色的内在演变笔记
    sections.append(make_section("本章出场角色·内在笔记", character_arcs_for_writer(beat), "high", True))
    style_digest = style_metrics_digest_for_writer()
    if style_digest:
        sections.append(make_section("源文风格指标执行摘要", style_digest, "normal", True))
    sections.append(make_section("本章 beat", json.dumps(sanitize_beat_for_writer(beat), ensure_ascii=False, indent=2), "critical", False))
    # 按需注入写作要点模块(对话/潜台词/黑子/视觉/情绪裂缝/内在转变/困境主题)
    focus = writer_focus_modules(beat)
    if focus:
        sections.append(make_section("本章写作要点（只针对本章，没列的规则不用强行套用）", focus, "critical", False))
    sig_warn = recent_signature_warnings(chapter)
    if sig_warn:
        sections.append(make_section("近期重复动作禁用清单", sig_warn, "critical", False))
    # 写手摘要防重复（基于最近章节的 LLM 生成摘要，比硬编码正则覆盖面更广）
    from pipeline.summarizer import anti_repeat_for_writer
    summary_warn = anti_repeat_for_writer(chapter)
    if summary_warn:
        sections.append(make_section("近期章节表达摘要·避免重复", summary_warn, "high", True))
    # 空间布局（防穿帮·按需）：本章有布局指令或本章地点有既有布局时才注入，否则静默
    spatial = layout_for_writer(beat)
    if spatial:
        sections.append(make_section("本章空间布局（防穿帮·严格遵守地标方位和场景陈设）", spatial, "high", True))
    # 注:节奏多样性/情绪分布警告"曾"在此注入,现已移除——它们统计的是「场景类型/情绪基调」
    # 这类由 beat 决定、跨几十章摊平的分布属性,属规划层(beat_planner)的活。给单章视角的
    # writer 看会逼它硬切场景/硬调情绪(与三线占比同款矫枉过正)。信号只保留在 beat_planner。
    # writer 仍保留 recent_signature_warnings,因为那是正文字句层的重复,确属 writer 掌控。
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


def build_pov_writer_input(beat: Dict[str, Any], chapter: int, run_cfg: Dict[str, Any], timeout: int) -> str:
    """构建 POV 章的 writer 上下文（知识隔离版）。
    不注入沈安的秘密/内心/arc_core/self_deception。"""
    pov_char = beat.get("视角角色", "沈安")
    ledger = load_ledger()
    entities = ledger.get("entities") or {}
    entity = entities.get(pov_char) or {}

    # 从 impact_seeds 找到对应 seed 获取 ignorant_of 和 voice
    seeds = ledger.get("impact_seeds") or []
    seed = next((s for s in seeds if s.get("who") == pov_char), None)
    ignorant_of = (seed.get("ignorant_of") if seed else []) or []
    pov_voice = (seed.get("pov_voice") if seed else "") or entity.get("voice", "")

    # 角色信息（不含沈安的秘密）
    entity_lines = [f"角色：{pov_char}"]
    if pov_voice:
        entity_lines.append(f"语气/世界观：{pov_voice}")
    if entity.get("summary"):
        entity_lines.append(f"简介：{entity['summary']}")
    if entity.get("facts"):
        entity_lines.append(f"已知事实：{'；'.join(entity['facts'][:8])}")
    if entity.get("current_goal"):
        entity_lines.append(f"当前目标：{entity['current_goal']}")
    if entity.get("status"):
        entity_lines.append(f"状态：{entity['status']}")
    entity_text = "\n".join(entity_lines)

    # 知识边界
    ignorant_lines = ["以下信息该角色**不知道**，正文中绝不能出现（哪怕暗示也不行）："]
    for item in ignorant_of:
        ignorant_lines.append(f"- {item}")
    if not ignorant_of:
        ignorant_lines.append("- （无特殊限制）")
    ignorant_text = "\n".join(ignorant_lines)

    # 公开事件摘要（不含沈安内心）
    state = load_state()
    recent = state.get("recent_events") or []
    public_events = "\n".join(f"- {e}" for e in recent[-6:]) if recent else "（暂无）"

    # 世界观设定（通用）
    world_bible = read_text(BASE_DIR / "02-世界观设定圣经.md")

    # 时间锚点
    time_anchor = beat.get("时间锚点", "")
    narrative_method = beat.get("叙事手法", "顺叙")
    time_section = ""
    if time_anchor:
        time_section = f"本章时间定位：{narrative_method}。时间锚点：{time_anchor}\n章首第一段必须用一句话定位时间。"

    sections = [
        make_section("你的视角角色", f"本章从【{pov_char}】的视角写整章。这个人不是主角，有自己的生活和内心世界。", "critical", False),
        make_section("角色信息", entity_text, "critical", False),
        make_section("知识边界（铁律，违反=穿帮）", ignorant_text, "critical", False),
    ]
    append_selected_chunk_sections(sections, beat, skip_role_names=["沈安"])
    style_digest = style_metrics_digest_for_writer()
    if style_digest:
        sections.append(make_section("源文风格指标执行摘要", style_digest, "normal", True))
    sections.append(make_section("本章 beat", json.dumps(beat, ensure_ascii=False, indent=2), "critical", False))
    focus = writer_focus_modules(beat, include_protagonist_sensory=False)
    if focus:
        sections.append(make_section("本章写作要点（POV章适用，未列规则不用强行套用）", focus, "critical", False))
    if time_section:
        sections.append(make_section("时间定位指令", time_section, "critical", False))
    sections.extend([
        make_section("最近公开事件（非沈安内心）", public_events, "high", True),
        make_section("世界观设定", world_bible[:3000] if len(world_bible) > 3000 else world_bible, "normal", True),
    ])
    spatial = layout_for_writer(beat)
    if spatial:
        sections.append(make_section("本章空间布局（防穿帮·严格遵守地标方位和场景陈设）", spatial, "high", True))
    return compress_sections_if_needed("writer", chapter, sections, run_cfg, timeout)


