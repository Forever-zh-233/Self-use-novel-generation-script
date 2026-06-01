# -*- coding: utf-8 -*-
"""清除所有章节级生成物，保留配置/提示词/设定文档/源码/骨架/卷纲。"""

import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUTPUT = BASE / "输出"
RUNTIME = BASE / "runtime"

deleted_count = 0


def rm_contents(folder: Path, label: str):
    """删除文件夹内所有内容，保留文件夹本身。"""
    global deleted_count
    if not folder.exists():
        return
    count = 0
    for item in list(folder.iterdir()):
        if item.is_dir():
            shutil.rmtree(item)
            count += 1
        else:
            item.unlink()
            count += 1
    if count:
        print(f"  {label}: {count} items")
        deleted_count += count


def rm_file(path: Path, label: str = ""):
    """删除单个文件。"""
    global deleted_count
    if path.exists():
        path.unlink()
        print(f"  {label or path.name}")
        deleted_count += 1


def reset_file(path: Path, content: str, label: str = ""):
    """重置文件为初始内容。"""
    if path.exists():
        path.write_text(content, encoding="utf-8")
        print(f"  {label or path.name} (reset)")


print("Cleaning chapter artifacts...\n")

# === 输出目录下所有子文件夹的内容 ===
output_subdirs = ["文章", "分数表", "章纲存档", "写手", "评审", "修稿", "门禁", "章纲", "上下文"]
for sub in output_subdirs:
    rm_contents(OUTPUT / sub, f"输出/{sub}")

# === beats/ ===
rm_contents(BASE / "beats", "beats")

# === 台账版本/ ===
rm_contents(BASE / "台账版本", "台账版本")

# === runtime 章节记忆文件 ===
print("  runtime:")
runtime_files = [
    "ledger.json", "ledger.md",
    "state.json", "state.md",
    "active_threads.json", "active_threads.md",
    "active_arcs.json",
    "character_arcs.md",
    "story_director.json", "story_director.md",
    "story_director_input.md", "story_director_raw.md",
    "progress.json",
    "arc_planner_output.md",
    "volume_summaries.json",
    "arc_history.json",
]
for name in runtime_files:
    rm_file(RUNTIME / name, f"    {name}")

# runtime/analyst/ 内容
rm_contents(RUNTIME / "analyst", "  runtime/analyst")

# 锁和停止文件（残留的）
for lock in ["novel_pipeline.lock", "novel_pipeline.bat.lock", "stop.request"]:
    rm_file(RUNTIME / lock, f"    {lock}")

# === 07/08 动态文档重置为空模板 ===
reset_file(BASE / "07-动态状态台账.md", "# 动态状态台账\n\n（由管线自动生成）\n", "07-动态状态台账.md")
reset_file(BASE / "08-期待账本.md", "# 期待账本\n\n| ID | 类型 | 埋设章 | 强度 | 承诺的回报 | 计划回收章 | 状态 |\n| --- | --- | --- | --- | --- | --- | --- |\n\n（由管线自动生成）\n", "08-期待账本.md")

# === 根目录临时文件 ===
rm_file(BASE / ".last_backup_dir.tmp", ".last_backup_dir.tmp")

print(f"\nDone. {deleted_count} items deleted.")
