# -*- coding: utf-8 -*-
"""清除所有章节级生成物，保留配置/提示词/设定文档/源码/骨架/卷纲。"""

import os
import shutil
from pathlib import Path

# 与 pipeline.core 一致:优先认 NOVEL_WORKSPACE,缺省才用脚本相对路径。
# 这样测试能指向隔离临时工作区,绝不误删真实工作区。
BASE = Path(os.environ.get("NOVEL_WORKSPACE") or Path(__file__).resolve().parents[1])
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

# === 写手摘要 runtime/summaries/（summarizer 每章生成，章节级动态产物） ===
# 必须清:残留旧章摘要会污染下一轮 anti_repeat_for_writer / reviewer 的防重复参照。
rm_contents(RUNTIME / "summaries", "runtime/summaries")

# === 卷纲（由 volume_planner 生成，重跑会重新生成） ===
rm_file(BASE / "卷纲" / "10-卷纲.md", "卷纲/10-卷纲.md")

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
    "arc_planner_output.md", "arc_planner_dryrun.md",
    "volume_summary.md", "volume_summaries.json",
    "volume_planner_output.md", "volume_planner_dryrun.md",
    "volume_digest_raw.md",
    "master_outline_raw.md", "master_outline_dryrun.md",
    "arc_history.json",
]
for name in runtime_files:
    rm_file(RUNTIME / name, f"    {name}")

# === 残留运行日志 ===
for log in RUNTIME.glob("*.log"):
    rm_file(log, f"    {log.name}")

# 注意：绝不删 runtime/analyst/（全文扫读产物）和 chunks/ 里的手法卡。
# 全量分析是独立的一次性重活（烧 $几、跑几小时），由「一键全量分析.bat」
# 的 Clean/redo-MAP/PROSE/STRUCT 选项单独管理。清小说和清分析是两个脚本，
# 各干各的——重跑小说不该让你白烧整本书的分析。

# 锁和停止文件（残留的）
for lock in ["novel_pipeline.lock", "novel_pipeline.bat.lock", "stop.request", "pause.request"]:
    rm_file(RUNTIME / lock, f"    {lock}")

# === 07/08 动态文档重置为空模板 ===
reset_file(BASE / "07-动态状态台账.md", "# 动态状态台账\n\n（由管线自动生成）\n", "07-动态状态台账.md")
reset_file(BASE / "08-期待账本.md", "# 期待账本\n\n| ID | 类型 | 埋设章 | 强度 | 承诺的回报 | 计划回收章 | 状态 |\n| --- | --- | --- | --- | --- | --- | --- |\n\n（由管线自动生成）\n", "08-期待账本.md")

# === 根目录临时文件 ===
rm_file(BASE / ".last_backup_dir.tmp", ".last_backup_dir.tmp")

print(f"\nDone. {deleted_count} items deleted.")
