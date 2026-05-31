# -*- coding: utf-8 -*-
"""
整理当前状态层。

用途：
  python compact_state.py

输出：
  runtime/state.json
  runtime/state.md
  runtime/active_threads.json
  runtime/active_threads.md
  runtime/volume_summary.md

说明：
  这是保守整理脚本，只做能可靠抽取的结构化信息。
  深度整理可交给 Archivist/continuity 模型生成 STRUCTURED_UPDATE 后再由 run_pipeline.py 合并。
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict


BASE_DIR = Path(os.environ.get("NOVEL_WORKSPACE") or Path(__file__).resolve().parents[1])
RUNTIME_DIR = BASE_DIR / "runtime"
STATE_FILE = RUNTIME_DIR / "state.json"
STATE_MD_FILE = RUNTIME_DIR / "state.md"
ACTIVE_THREADS_FILE = RUNTIME_DIR / "active_threads.json"
ACTIVE_THREADS_MD_FILE = RUNTIME_DIR / "active_threads.md"
LONG_FORESHADOWING_FILE = RUNTIME_DIR / "long_foreshadowing.json"
LONG_FORESHADOWING_MD_FILE = RUNTIME_DIR / "long_foreshadowing.md"
VOLUME_SUMMARY_FILE = RUNTIME_DIR / "volume_summary.md"
SOURCE_LONG_FORESHADOWING_FILE = BASE_DIR / "15-长线伏笔资产库.md"


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return default


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dump_json(path: Path, data: Dict[str, Any]) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    text = read_text(path).strip()
    return json.loads(text) if text else default


def default_state() -> Dict[str, Any]:
    return {
        "latest_chapter": 0,
        "story_time": "未明确",
        "current_location": "未明确",
        "characters": {},
        "relationships": {},
        "knowledge": {},
        "used_devices": [],
        "recent_events": [],
    }


def default_threads() -> Dict[str, Any]:
    return {
        "foreshadowing": {},
        "open_questions": [],
        "next_id": "F-001",
    }


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
    for name, info in (state.get("characters") or {}).items():
        if isinstance(info, dict):
            lines.append(f"- {name}：位置={info.get('location', '未明确')}；状态={info.get('status', '未明确')}；情绪={info.get('emotion', '未明确')}")
        else:
            lines.append(f"- {name}：{info}")
    if not state.get("characters"):
        lines.append("- 暂无")
    lines.extend(["", "## 关系"])
    for key, value in (state.get("relationships") or {}).items():
        lines.append(f"- {key}：{value}")
    if not state.get("relationships"):
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


def render_threads_markdown(threads: Dict[str, Any]) -> str:
    lines = ["# 活跃线索与期待账本", "", f"- 下一个建议 ID：{threads.get('next_id', 'F-001')}", "", "## 伏笔"]
    for fid, item in (threads.get("foreshadowing") or {}).items():
        if isinstance(item, dict):
            lines.append(
                f"- {fid}：{item.get('status', '未明确')}；类型={item.get('type', '未明确')}；"
                f"埋设={item.get('planted_chapter', '未明确')}；承诺={item.get('promise', '未记录')}；"
                f"计划回收={item.get('planned_resolution', '未明确')}"
            )
        else:
            lines.append(f"- {fid}：{item}")
    if not threads.get("foreshadowing"):
        lines.append("- 暂无")
    lines.extend(["", "## 开放问题"])
    for question in threads.get("open_questions") or []:
        lines.append(f"- {question}")
    if not threads.get("open_questions"):
        lines.append("- 暂无")
    return "\n".join(lines) + "\n"


def infer_latest_chapter(text: str) -> int:
    matches = [int(item) for item in re.findall(r"第(\d+)章", text)]
    return max(matches) if matches else 0


def clean(value: str) -> str:
    value = re.sub(r"[*_`]+", "", value)
    value = value.replace("：", ":")
    return value.strip(" -\t\r\n")


def normalize_aliases(value: str) -> str:
    return (
        value.replace("沈归舟", "沈安")
        .replace("黑子", "阿墨")
        .replace("方绾", "方青瓷")
    )


def canonical_name(name: str) -> str:
    aliases = {
        "沈归舟": "沈安",
        "黑子": "阿墨",
        "方绾": "方青瓷",
    }
    return aliases.get(clean(name), clean(name))


def split_updates(ledger: str) -> Dict[int, str]:
    updates: Dict[int, str] = {}
    pattern = re.compile(r"### 第(\d+)章更新\s*([\s\S]*?)(?=\n### 第\d+章(?:自动)?更新|\Z)")
    for match in pattern.finditer(ledger):
        updates[int(match.group(1))] = match.group(2).strip()
    return updates


def subsection(text: str, title: str) -> str:
    headings = "|".join([
        "时间推进",
        "位置变化",
        "关系变化",
        "新增信息差",
        "新增伏笔",
        "回收伏笔",
        "新增已用桥段",
        "角色情绪变化",
    ])
    pattern = re.compile(
        rf"^\s*-\s*(?:\*\*)?{re.escape(title)}(?:\*\*)?\s*[：:]\s*([\s\S]*?)(?=^\s*-\s*(?:\*\*)?(?:{headings})(?:\*\*)?\s*[：:]|\Z)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def infer_time(update: str) -> str:
    match = re.search(r"^\s*-\s*(?:\*\*)?时间推进(?:\*\*)?\s*[：:]\s*(.+)$", update, re.MULTILINE)
    return clean(match.group(1)) if match else ""


def last_location(value: str) -> str:
    value = clean(value)
    detail = re.search(r"（([^）]+)）", value)
    if "→" in value:
        tail = clean(value.split("→")[-1])
        if detail and ("附近" in tail or "返回" in tail):
            return clean(detail.group(1))
        return clean(tail.split("（")[0])
    if "->" in value:
        tail = clean(value.split("->")[-1])
        if detail and ("附近" in tail or "返回" in tail):
            return clean(detail.group(1))
        return clean(tail.split("（")[0])
    if "返回" in value:
        if detail:
            return clean(detail.group(1))
        return clean(value.split("返回", 1)[-1].split("（")[0])
    if "在" in value and "，" in value:
        return clean(value.split("，")[0])
    return value


def parse_colon_items(block: str) -> Dict[str, str]:
    items: Dict[str, str] = {}
    for line in block.splitlines():
        stripped = clean(line)
        if not stripped or stripped.startswith("#") or stripped.lower().startswith("step "):
            continue
        match = re.match(r"([^:：]+)[：:]\s*(.+)", stripped)
        if match:
            key = clean(match.group(1))
            value = normalize_aliases(clean(match.group(2)))
            if key and value:
                items[key] = value
    return items


def infer_state_from_updates(ledger: str, state: Dict[str, Any]) -> Dict[str, Any]:
    updates = split_updates(ledger)
    if not updates:
        return state
    state["latest_chapter"] = max(int(state.get("latest_chapter") or 0), max(updates))
    characters = {}
    relationships = {}
    knowledge = {}
    used_devices = []
    recent_events = []
    for chapter in sorted(updates):
        update = updates[chapter]
        time_text = infer_time(update)
        if time_text:
            state["story_time"] = time_text
        location_items = parse_colon_items(subsection(update, "位置变化"))
        for name, value in location_items.items():
            name = canonical_name(name)
            info = characters.setdefault(name, {})
            if isinstance(info, dict):
                location = last_location(value)
                info["location"] = location or value
                info.setdefault("status", "已登场")
                if name == "沈安" and location:
                    state["current_location"] = location
        relation_items = parse_colon_items(subsection(update, "关系变化"))
        for key, value in relation_items.items():
            parts = [canonical_name(part) for part in re.split(r"[-—]", key, maxsplit=1)]
            relationships["-".join(parts) if len(parts) == 2 else key] = value
        info_items = parse_colon_items(subsection(update, "新增信息差"))
        for name, value in info_items.items():
            if "不知道" in name:
                base_name = canonical_name(name.replace("不知道", ""))
                person = knowledge.setdefault(base_name, {"knows": [], "unknown": []})
                person.setdefault("unknown", []).append(value)
            elif "知道了" in name or "知道" in name:
                base_name = canonical_name(name.replace("知道了", "").replace("知道", ""))
                person = knowledge.setdefault(base_name, {"knows": [], "unknown": []})
                person.setdefault("knows", []).append(value)
            else:
                base_name = canonical_name(name)
                person = knowledge.setdefault(base_name, {"knows": [], "unknown": []})
                person.setdefault("knows", []).append(value)
        device_block = subsection(update, "新增已用桥段")
        for line in device_block.splitlines():
            item = clean(line)
            if item and item not in used_devices:
                used_devices.append(item)
        emotion_items = parse_colon_items(subsection(update, "角色情绪变化"))
        for name, value in emotion_items.items():
            name = canonical_name(name)
            info = characters.setdefault(name, {})
            if isinstance(info, dict):
                info["emotion"] = value
                info.setdefault("status", "已登场")
        first_fact = ""
        for candidate in [time_text, *location_items.values()]:
            if candidate:
                first_fact = clean(candidate)
                break
        if first_fact:
            recent_events.append(f"第{chapter}章：{first_fact}")
    state["used_devices"] = used_devices[-30:]
    state["characters"] = characters
    state["relationships"] = relationships
    state["knowledge"] = knowledge
    if recent_events:
        state["recent_events"] = recent_events[-10:]
    return state


def infer_threads(expectation_text: str) -> Dict[str, Any]:
    threads = default_threads()
    for line in expectation_text.splitlines():
        if not line.strip().startswith("| F-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        fid = cells[0]
        threads["foreshadowing"][fid] = {
            "id": fid,
            "type": cells[1],
            "planted_chapter": cells[2],
            "strength": cells[3],
            "promise": cells[4],
            "planned_resolution": cells[5],
            "status": cells[6],
        }
    ids = []
    for fid in threads["foreshadowing"]:
        match = re.search(r"F-(\d+)", fid)
        if match:
            ids.append(int(match.group(1)))
    if ids:
        threads["next_id"] = f"F-{max(ids) + 1:03d}"
    return threads


def infer_long_foreshadowing(text: str) -> Dict[str, Any]:
    cards = {}
    current_id = ""
    for line in text.splitlines():
        heading = re.match(r"^###\s+(LF-\d+)\s+(.+)$", line.strip())
        if heading:
            current_id = heading.group(1)
            cards[current_id] = {"id": current_id, "title": heading.group(2).strip()}
            continue
        if re.match(r"^###\s+LF-", line.strip()):
            current_id = ""
            continue
        if not current_id:
            continue
        item = re.match(r"^-\s*([^：:]+)[：:]\s*(.+)$", line.strip())
        if item:
            key = clean(item.group(1))
            value = clean(item.group(2))
            cards[current_id][key] = value
    return {"cards": cards}


def render_long_foreshadowing_markdown(data: Dict[str, Any]) -> str:
    lines = [
        "# 长线伏笔安全索引",
        "",
        "本文件是给 Writer/手写 agent 的安全版，只保留表层线索和外显条件。",
        "完整后台版只给 Planner/Archivist/Continuity 使用，Writer 不读取。",
        "",
    ]
    cards = data.get("cards") or {}
    if not cards:
        lines.append("- 暂无")
    for index, (_fid, card) in enumerate(cards.items(), start=1):
        lines.append(f"## 长线安全线索 {index} {card.get('title', '')}".strip())
        for key in ["等级", "生命周期", "首次埋设", "表层线索", "外显条件", "外显方式", "当前状态"]:
            if card.get(key):
                lines.append(f"- {key}：{card[key]}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    ledger = read_text(BASE_DIR / "07-动态状态台账.md")
    expectations = read_text(BASE_DIR / "08-期待账本.md")
    previous_state = load_json(STATE_FILE, default_state())
    state = default_state()
    state["latest_chapter"] = max(int(previous_state.get("latest_chapter") or 0), infer_latest_chapter(ledger))
    state = infer_state_from_updates(ledger, state)
    threads = infer_threads(expectations)
    long_foreshadowing = infer_long_foreshadowing(read_text(SOURCE_LONG_FORESHADOWING_FILE))
    dump_json(STATE_FILE, state)
    dump_json(ACTIVE_THREADS_FILE, threads)
    dump_json(LONG_FORESHADOWING_FILE, long_foreshadowing)
    write_text(STATE_MD_FILE, render_state_markdown(state))
    write_text(ACTIVE_THREADS_MD_FILE, render_threads_markdown(threads))
    write_text(LONG_FORESHADOWING_MD_FILE, render_long_foreshadowing_markdown(long_foreshadowing))
    if not VOLUME_SUMMARY_FILE.exists():
        write_text(VOLUME_SUMMARY_FILE, "# 卷总结\n\n暂无。第10章或第20章整理时更新。\n")
    print(f"state written: {STATE_FILE}")
    print(f"threads written: {ACTIVE_THREADS_FILE}")


if __name__ == "__main__":
    main()
