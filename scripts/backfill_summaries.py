# -*- coding: utf-8 -*-
"""为已有章节批量补生成写手摘要。

用法: python scripts/backfill_summaries.py [start] [end]
默认: 补最近10章。

每章调一次 LLM，约 500 token 输出，成本极低。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.core import BASE_DIR, cli_print, manuscript_path, read_text
from pipeline.summarizer import generate_chapter_summary, summary_path


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else None
    end = int(sys.argv[2]) if len(sys.argv) > 2 else None

    # 自动检测最新章节
    articles_dir = BASE_DIR / "输出" / "文章"
    existing = sorted(
        int(p.stem.replace("第", "").replace("章", ""))
        for p in articles_dir.glob("第*章.md")
        if p.stem.replace("第", "").replace("章", "").isdigit()
    )
    if not existing:
        print("没有找到已有章节。")
        return

    latest = existing[-1]
    if start is None:
        start = max(1, latest - 9)
    if end is None:
        end = latest

    print(f"将为第 {start}-{end} 章补生成摘要...")
    generated = 0
    skipped = 0

    for ch in range(start, end + 1):
        if summary_path(ch).exists():
            skipped += 1
            continue
        ms = manuscript_path(ch)
        if not ms.exists():
            continue
        text = read_text(ms)
        if len(text) < 200:
            continue
        try:
            generate_chapter_summary(ch, text, timeout=120)
            generated += 1
            print(f"  [OK] 第{ch}章")
            time.sleep(1)
        except Exception as exc:
            print(f"  [FAIL] 第{ch}章: {exc}")

    print(f"\n完成: 生成 {generated} 章, 跳过 {skipped} 章(已有摘要)")


if __name__ == "__main__":
    main()
