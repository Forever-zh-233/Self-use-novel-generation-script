# -*- coding: utf-8 -*-
"""替换 volume_summary 和修复编码问题"""
import re

path = 'scripts/run_pipeline.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 volume_summary 函数(可能已经被搞坏了),从 def volume_summary 到下一个 def
pattern = r'def volume_summary\(chapter: int\) -> str:.*?(?=\ndef [a-z_])'
match = re.search(pattern, content, re.DOTALL)
if not match:
    print("ERROR: volume_summary not found")
    exit(1)

print(f"Found volume_summary at chars {match.start()}-{match.end()}")

new_func = '''def volume_summary(chapter: int) -> str:
    """给卷纲规划师的发展历程:全书卷摘要(远期) + 上一卷详细弧线(近期)。"""
    parts = []
    # 1. 所有历史卷的 LLM 生成摘要(远期,每卷 200-300 字)
    digests = load_json(VOLUME_DIGESTS_FILE, {"volumes": []})
    if digests.get("volumes"):
        parts.append("## 全书发展历程\\n")
        for i, vol in enumerate(digests["volumes"], 1):
            parts.append(f"### 第{i}卷(截至第{vol.get('volume_end_chapter','?')}章)")
            parts.append(vol.get("digest", "(无摘要)"))
            parts.append("")
    # 2. 上一卷详细弧线(近期衔接)
    arc_history_file = RUNTIME_DIR / "arc_history.json"
    if arc_history_file.exists():
        history = load_json(arc_history_file, {"volumes": []})
        volumes = history.get("volumes") or []
        if volumes:
            last_vol = volumes[-1]
            arcs = last_vol.get("arcs") or []
            if arcs:
                arc_lines = [f"## 上一卷弧线详情({len(arcs)}条)\\n"]
                for arc in arcs:
                    arc_lines.append(f"**{arc.get('title','?')}**: {arc.get('summary','')[:120]}")
                    arc_lines.append(f"  收束条件: {arc.get('resolution_condition','')}")
                    for node in (arc.get("nodes") or []):
                        arc_lines.append(f"  第{node.get('chapter','?')}章[{node.get('tension','?')}]: {node.get('beat_hint','')[:60]}")
                    arc_lines.append("")
                parts.append("\\n".join(arc_lines))
    # 3. 上一卷卷纲(规划了什么)
    if VERSION_DIR.exists():
        backups = sorted(VERSION_DIR.glob("卷纲_截至第*章.md"), key=lambda p: p.stat().st_mtime)
        if backups:
            old_plan = read_text(backups[-1])
            if old_plan.strip():
                parts.append(f"## 上一卷卷纲\\n\\n{old_plan[:2000]}")
    if not parts:
        return "(首卷,无历史回顾)"
    return "\\n\\n".join(parts)


'''

content = content[:match.start()] + new_func + content[match.end():]

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
