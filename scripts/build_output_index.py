# -*- coding: utf-8 -*-
"""生成输出目录索引，方便阅读和定位各职责产物。"""

import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "输出"
ARTICLE_DIR = OUTPUT_DIR / "文章"
INDEX_FILE = OUTPUT_DIR / "目录.md"


ROLE_LINKS = [
    ("章纲", "beat_raw.md", "章纲原始输出"),
    ("章纲", "beat_input.md", "章纲输入"),
    ("写手", "draft.md", "初稿"),
    ("写手", "final.md", "终稿备份"),
    ("门禁", "gate.json", "初稿门禁"),
    ("门禁", "final_gate.json", "终稿门禁"),
    ("评审", "review.md", "评审"),
    ("修稿", "edited.md", "修稿"),
    ("记录员", "archive_update.md", "台账更新"),
]


def read_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
    except FileNotFoundError:
        return ""
    return path.stem


def main() -> None:
    chapters = []
    if ARTICLE_DIR.exists():
        for path in ARTICLE_DIR.iterdir():
            match = re.match(r"第(\d+)章\.md$", path.name)
            if match:
                chapters.append((int(match.group(1)), path))
    chapters.sort()
    lines = [
        "# 输出目录",
        "",
        "## 文章",
        "",
    ]
    if not chapters:
        lines.append("- 暂无文章。")
    for chapter, path in chapters:
        title = read_title(path)
        lines.append(f"- 第{chapter:03d}章：[{title}](文章/{path.name})")
    lines.extend(["", "## 职责产物", ""])
    for chapter, _ in chapters:
        bits = []
        for folder, suffix, label in ROLE_LINKS:
            path = OUTPUT_DIR / folder / f"第{chapter:03d}章_{suffix}"
            if path.exists():
                bits.append(f"[{label}]({folder}/{path.name})")
        lines.append(f"- 第{chapter:03d}章：{' | '.join(bits) if bits else '无'}")
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"index written: {INDEX_FILE}")


if __name__ == "__main__":
    main()
