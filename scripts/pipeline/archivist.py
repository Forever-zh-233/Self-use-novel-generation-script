# -*- coding: utf-8 -*-
"""pipeline.archivist — merge_state, merge_ledger, write_markdown."""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.core import (
    BASE_DIR, STATE_FILE, ACTIVE_THREADS_FILE, LEDGER_FILE, LEDGER_MD_FILE,
    CHARACTER_ARCS_FILE, VERSION_DIR, REALM_ORDER,
    _sanitize_model_json, append_text, cli_print, dump_json, load_json,
    read_text, write_text,
)
from pipeline.state import (
    load_active_threads, load_ledger, load_state,
    normalize_strand, update_strand_tracker, write_state_mirrors,
)


def extract_markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


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
    chapter_no = update.get("_chapter") or 0
    for key in ["characters", "relationships", "knowledge"]:
        value = update.get(key)
        if isinstance(value, dict):
            target = state.setdefault(key, {})
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict) and isinstance(target.get(sub_key), dict):
                    target[sub_key].update(sub_value)
                else:
                    target[sub_key] = sub_value
                if key == "characters" and chapter_no:
                    entry = target[sub_key] if isinstance(target[sub_key], dict) else {}
                    entry["_last_active"] = int(chapter_no)
                    target[sub_key] = entry
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
    # long_foreshadowing_touches: 长线伏笔本章触碰记录 → 追加到 reveal_ledger 对应条目
    lf_touches = update.get("long_foreshadowing_touches")
    if isinstance(lf_touches, list) and lf_touches:
        ledger = load_ledger()
        reveals = ledger.setdefault("reveal_ledger", [])
        by_id = {r.get("id") or r.get("topic"): r for r in reveals if isinstance(r, dict)}
        for touch in lf_touches:
            if not isinstance(touch, dict):
                continue
            lf_id = touch.get("id") or ""
            node = by_id.get(lf_id)
            if not node:
                continue
            touches_list = node.setdefault("touches", [])
            touches_list.append({
                "chapter": touch.get("chapter") or update.get("_chapter"),
                "touch": touch.get("touch", ""),
                "new_information": touch.get("new_information", ""),
            })
            node["touches"] = touches_list[-10:]
        dump_json(LEDGER_FILE, ledger)
    # 三线节奏:archivist 打的 dominant_strand 标签 → 更新计数器(归一化后)
    dominant_raw = update.get("dominant_strand")
    if dominant_raw and chapter_no:
        update_strand_tracker(state, int(chapter_no), normalize_strand(dominant_raw))
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
            merged_facts = list(dict.fromkeys((cur.get("facts") or []) + (ent.get("facts") or [])))
            cur["facts"] = merged_facts[-8:]
            if not cur.get("voice") and ent.get("voice"):
                cur["voice"] = ent["voice"]
            if not cur.get("appearance") and ent.get("appearance"):
                cur["appearance"] = ent["appearance"]
            if ent.get("mannerisms"):
                merged_man = list(dict.fromkeys((cur.get("mannerisms") or []) + list(ent["mannerisms"])))
                cur["mannerisms"] = merged_man[-6:]
            cur["last_seen_chapter"] = chapter
        else:
            entities[name] = {
                "type": ent.get("type") or "角色",
                "first_chapter": ent.get("first_chapter") or chapter,
                "last_seen_chapter": chapter,
                "summary": ent.get("summary") or "",
                "voice": ent.get("voice") or "",
                "appearance": ent.get("appearance") or "",
                "mannerisms": ent.get("mannerisms") or [],
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
            # 地点类空间字段：仅在提供时写入，不给非地点实体占位
            if ent.get("type") == "地点":
                for sp_key in ("scale", "parent", "bearing_from_parent"):
                    if ent.get(sp_key):
                        entities[name][sp_key] = ent[sp_key]
                if ent.get("landmarks"):
                    entities[name]["landmarks"] = ent["landmarks"]
                if ent.get("layout"):
                    entities[name]["layout"] = ent["layout"]
    for upd in block.get("update_entities") or []:
        if not isinstance(upd, dict):
            continue
        name = upd.get("name")
        if not name or name not in entities:
            continue
        cur = entities[name]
        if upd.get("add_facts"):
            merged = list(dict.fromkeys((cur.get("facts") or []) + list(upd["add_facts"])))
            cur["facts"] = merged[-8:]
        if upd.get("status"):
            cur["status"] = upd["status"]
        if upd.get("voice"):
            cur["voice"] = upd["voice"]
        if upd.get("appearance_update"):
            cur["appearance"] = upd["appearance_update"]
        if upd.get("mannerisms_add"):
            add = upd["mannerisms_add"]
            add = [add] if isinstance(add, str) else add
            merged_man = list(dict.fromkeys((cur.get("mannerisms") or []) + [str(m) for m in add if m]))
            cur["mannerisms"] = merged_man[-6:]
        if upd.get("realm_change"):
            cur["realm"] = upd["realm_change"]
        if upd.get("skills_remove"):
            remove_names = set()
            for sk in upd["skills_remove"]:
                if isinstance(sk, str):
                    remove_names.add(sk)
                elif isinstance(sk, dict) and sk.get("name"):
                    remove_names.add(sk["name"])
            if remove_names:
                cur["skills"] = [s for s in (cur.get("skills") or []) if not (isinstance(s, dict) and s.get("name") in remove_names)]
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
        # 地点空间更新：方位修正 / 新地标追加 / 布局明确
        if upd.get("bearing_update"):
            cur["bearing_from_parent"] = upd["bearing_update"]
        if upd.get("landmarks_add"):
            existing_lm = {lm.get("name") for lm in (cur.get("landmarks") or []) if isinstance(lm, dict)}
            for lm in upd["landmarks_add"]:
                if isinstance(lm, dict) and lm.get("name") and lm["name"] not in existing_lm:
                    cur.setdefault("landmarks", []).append(lm)
                    existing_lm.add(lm["name"])
        if upd.get("layout_update"):
            cur["layout"] = upd["layout_update"]
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

    # impact_seeds：影响种子（POV 章候选）
    seeds = ledger.setdefault("impact_seeds", [])
    seeds_by_id = {s.get("id"): s for s in seeds if isinstance(s, dict) and s.get("id")}
    for new_seed in block.get("impact_seeds") or []:
        if not isinstance(new_seed, dict) or not new_seed.get("id"):
            continue
        new_seed.setdefault("status", "pending")
        new_seed.setdefault("from_chapter", chapter)
        if new_seed["id"] in seeds_by_id:
            seeds_by_id[new_seed["id"]].update(new_seed)
        else:
            seeds.append(new_seed)
            seeds_by_id[new_seed["id"]] = new_seed

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
                # currency 是 dict 桶（由下方 currency_change 维护），不是列表。
                # 模型偶尔把铜钱写进 add 且 category=currency——别往 dict 里 append/遍历，
                # 否则 for x in target 会迭代出字符串键导致 x.get() 崩。交给 currency_change。
                if category == "currency":
                    continue
                target = inventory.setdefault(category, [])
                if not isinstance(target, list):
                    # 该桶不是列表（结构异常或撞了 currency 等特殊键），跳过以防崩库
                    continue
                item.setdefault("last_chapter", chapter)
                existing = next((x for x in target if isinstance(x, dict) and x.get("name") == item["name"]), None)
                if existing:
                    existing.update(item)
                else:
                    target.append(item)
        for item in inv_update.get("consume") or []:
            if isinstance(item, dict) and item.get("name"):
                for cat in ["consumables", "key_items"]:
                    for x in inventory.get(cat, []):
                        if isinstance(x, dict) and x.get("name") == item["name"]:
                            qty = item.get("qty", 1)
                            x["qty"] = max(0, (x.get("qty") or 1) - qty)
                            x["last_chapter"] = chapter
        for item in inv_update.get("destroy") or []:
            name = item.get("name") if isinstance(item, dict) else item
            for cat in ["consumables", "key_items"]:
                for x in inventory.get(cat, []):
                    if isinstance(x, dict) and x.get("name") == name:
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
            if not isinstance(items, list):
                continue
            inventory[cat] = [x for x in items if not isinstance(x, dict) or (not (
                x.get("status") == "已销毁" and chapter - (x.get("last_chapter") or 0) > 10
            ) and not (
                cat == "consumables" and (x.get("qty") or 0) <= 0 and chapter - (x.get("last_chapter") or 0) > 30
            ))]

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
    structured_update["_chapter"] = chapter  # 供 merge_state_update 更新三线计数器
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


