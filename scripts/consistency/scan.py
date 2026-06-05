# -*- coding: utf-8 -*-
"""全量一致性扫描系统 — 入口脚本。

用法:
  双击 bat 或 python scan.py          — 交互菜单
  python scan.py y                   — 全量扫描
  python scan.py clean               — 清除产物
  python scan.py --map               — 只跑 Map
  python scan.py --map --chapters 101-109 --concurrency 6
  python scan.py --check             — 只跑 Check + Report
  python scan.py --dry-run           — 估算成本
"""

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consistency.mapper import run_map_phase, ARTICLE_DIR, FACTS_DIR
from consistency.checker import run_check_phase
from consistency.reporter import run_report_phase, CONSISTENCY_DIR


def detect_chapters() -> list:
    chapters = []
    for p in ARTICLE_DIR.glob("第*章.md"):
        stem = p.stem.replace("第", "").replace("章", "")
        if stem.isdigit():
            chapters.append(int(stem))
    return sorted(chapters)


def parse_chapter_range(spec: str, available: list) -> list:
    if "-" in spec:
        s, e = spec.split("-", 1)
        return [ch for ch in available if int(s) <= ch <= int(e)]
    elif "," in spec:
        targets = {int(x.strip()) for x in spec.split(",")}
        return [ch for ch in available if ch in targets]
    else:
        ch = int(spec)
        return [ch] if ch in available else []


def do_clean():
    if CONSISTENCY_DIR.exists():
        shutil.rmtree(CONSISTENCY_DIR)
        print("已清除 consistency/ 目录。")
    else:
        print("consistency/ 目录不存在，无需清除。")


def run_scan(chapters, concurrency, timeout, dry_run, run_map, run_check, run_report):
    run_all = not (run_map or run_check or run_report)
    t0 = time.time()
    print(f"\n=== 全量一致性扫描 ===")
    print(f"  章节范围: 第{min(chapters)}-{max(chapters)}章 (共{len(chapters)}章)\n")

    if run_all or run_map:
        print("── Phase 1: MAP (提取事实) ──")
        run_map_phase(chapters, concurrency=concurrency, timeout=timeout, dry_run=dry_run)
        print()
        if dry_run:
            return

    if run_all or run_check:
        print("── Phase 2: CHECK (20维度比对) ──")
        run_check_phase()
        print()

    if run_all or run_report:
        print("── Phase 3: REPORT (生成报告) ──")
        run_report_phase()
        print()

    print(f"=== 完成 ({time.time() - t0:.1f}s) ===")


def interactive_menu(available: list) -> str:
    cached = sum(1 for _ in FACTS_DIR.glob("chapter_*.json")) if FACTS_DIR.exists() else 0
    print(f"  已有章节: 第1-{max(available)}章 (共{len(available)}章)")
    print(f"  已缓存 fact sheet: {cached}/{len(available)} 章\n")
    print("  [y]      全量扫描（Map→Check→Report）")
    print("  [map]    只提取 fact sheet")
    print("  [check]  只跑 Check + Report")
    print("  [clean]  清除所有扫描产物")
    print("  [q]      退出\n")
    return input("请输入命令: ").strip().lower()


def main():
    available = detect_chapters()
    if not available:
        print("未找到任何章节文件。")
        return

    # 单词命令（bat 双击或 y/clean/q）
    if len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        cmd = sys.argv[1].strip().lower()
        if cmd == "clean":
            do_clean()
            return
        if cmd == "q":
            return
        if cmd in ("y", "map", "check", "report"):
            run_scan(available, 4, 180, False,
                     run_map=cmd in ("y", "map"),
                     run_check=cmd in ("y", "check"),
                     run_report=cmd in ("y", "check", "report"))
            return

    # 无参数 → 交互菜单
    if len(sys.argv) == 1:
        cmd = interactive_menu(available)
        if cmd == "q":
            return
        if cmd == "clean":
            do_clean()
            return
        if cmd in ("y", "map", "check", "report"):
            run_scan(available, 4, 180, False,
                     run_map=cmd in ("y", "map"),
                     run_check=cmd in ("y", "check"),
                     run_report=cmd in ("y", "check", "report"))
        return

    # argparse 模式（--map / --chapters 等）
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--chapters", type=str, default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chapters = parse_chapter_range(args.chapters, available) if args.chapters else available
    if not chapters:
        print(f"指定范围 '{args.chapters}' 内无章节。")
        return

    run_scan(chapters, args.concurrency, args.timeout, args.dry_run,
             args.map, args.check, args.report)


if __name__ == "__main__":
    main()
