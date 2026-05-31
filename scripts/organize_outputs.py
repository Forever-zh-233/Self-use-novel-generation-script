# -*- coding: utf-8 -*-
"""
整理输出目录为按职责分区。

目标结构：
  输出/文章/第001章.md
  输出/章纲/第001章_beat_input.md
  输出/写手/第001章_draft.md
  输出/门禁/第001章_gate.json
  输出/评审/第001章_review.md
  输出/修稿/第001章_edited.md
  输出/记录员/第001章_archive_update.md
  输出/上下文/第001章_writer_compressed_context.md
"""

import re
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "输出"
ARTICLE_DIR = OUTPUT_DIR / "文章"


ROLE_MAP = {
    "beat_input": ("章纲", "beat_input.md"),
    "beat_prompt": ("章纲", "beat_prompt.md"),
    "beat_raw": ("章纲", "beat_raw.md"),
    "writer_input": ("写手", "writer_input.md"),
    "writer_prompt": ("写手", "writer_prompt.md"),
    "draft": ("写手", "draft.md"),
    "final": ("写手", "final.md"),
    "gate": ("门禁", "gate.json"),
    "style_gate": ("门禁", "style_gate.json"),
    "continuity": ("门禁", "continuity.json"),
    "final_gate": ("门禁", "final_gate.json"),
    "final_style_gate": ("门禁", "final_style_gate.json"),
    "final_continuity": ("门禁", "final_continuity.json"),
    "review": ("评审", "review.md"),
    "review_input": ("评审", "review_input.md"),
    "edited": ("修稿", "edited.md"),
    "editor_input": ("修稿", "editor_input.md"),
    "archive_input": ("记录员", "archive_input.md"),
    "archive_update": ("记录员", "archive_update.md"),
}


CHAPTER_DIR_MAP = {
    "beat_input.md": ("章纲", "beat_input.md"),
    "beat_prompt.md": ("章纲", "beat_prompt.md"),
    "beat_raw.md": ("章纲", "beat_raw.md"),
    "writer_input.md": ("写手", "writer_input.md"),
    "writer_prompt.md": ("写手", "writer_prompt.md"),
    "draft.md": ("写手", "draft.md"),
    "final.md": ("写手", "final.md"),
    "gate.json": ("门禁", "gate.json"),
    "style_gate.json": ("门禁", "style_gate.json"),
    "continuity.json": ("门禁", "continuity.json"),
    "final_gate.json": ("门禁", "final_gate.json"),
    "final_style_gate.json": ("门禁", "final_style_gate.json"),
    "final_continuity.json": ("门禁", "final_continuity.json"),
    "review.md": ("评审", "review.md"),
    "review_input.md": ("评审", "review_input.md"),
    "edited.md": ("修稿", "edited.md"),
    "editor_input.md": ("修稿", "editor_input.md"),
    "archive_input.md": ("记录员", "archive_input.md"),
    "archive_update.md": ("记录员", "archive_update.md"),
}


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    return path.parent / f"{path.stem}.legacy{path.suffix}"


def move_file(path: Path, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    target = unique_path(target)
    shutil.move(str(path), str(target))
    return True


def move_flat_file(path: Path) -> bool:
    match = re.match(r"chapter_(\d+)_(.+?)(\.[^.]+)$", path.name)
    if not match:
        return False
    chapter = int(match.group(1))
    stem = match.group(2)
    mapped = ROLE_MAP.get(stem)
    if not mapped:
        return False
    folder, filename = mapped
    target = OUTPUT_DIR / folder / f"第{chapter:03d}章_{filename}"
    moved = move_file(path, target)
    if stem == "final":
        ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(target), str(ARTICLE_DIR / f"第{chapter:03d}章.md"))
    return moved


def move_chapter_dir(path: Path) -> int:
    match = re.match(r"第(\d+)章$", path.name)
    if not match or not path.is_dir():
        return 0
    chapter = int(match.group(1))
    moved = 0
    for child in list(path.iterdir()):
        if child.is_dir() and child.name == "context":
            for context_file in child.iterdir():
                target = OUTPUT_DIR / "上下文" / f"第{chapter:03d}章_{context_file.name}"
                if move_file(context_file, target):
                    moved += 1
            try:
                child.rmdir()
            except OSError:
                pass
            continue
        if not child.is_file():
            continue
        mapped = CHAPTER_DIR_MAP.get(child.name)
        if not mapped:
            continue
        folder, filename = mapped
        target = OUTPUT_DIR / folder / f"第{chapter:03d}章_{filename}"
        if move_file(child, target):
            moved += 1
            if child.name == "final.md":
                ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(target), str(ARTICLE_DIR / f"第{chapter:03d}章.md"))
    try:
        path.rmdir()
    except OSError:
        pass
    return moved


def copy_old_manuscripts() -> int:
    copied = 0
    for folder in ["成稿"]:
        old_dir = OUTPUT_DIR / folder
        if not old_dir.exists():
            continue
        ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
        for path in old_dir.iterdir():
            if not path.is_file():
                continue
            match = re.match(r"第(\d+)章\.md$", path.name)
            if not match:
                continue
            target = ARTICLE_DIR / f"第{int(match.group(1)):03d}章.md"
            if not target.exists():
                shutil.copy2(str(path), str(target))
                copied += 1
            path.unlink()
        try:
            old_dir.rmdir()
        except OSError:
            pass
    return copied


def main() -> None:
    if not OUTPUT_DIR.exists():
        print(f"output dir missing: {OUTPUT_DIR}")
        return
    moved = 0
    copied = copy_old_manuscripts()
    for path in list(OUTPUT_DIR.iterdir()):
        if path.is_file() and move_flat_file(path):
            moved += 1
    for path in list(OUTPUT_DIR.iterdir()):
        if path.is_dir():
            moved += move_chapter_dir(path)
    print(f"moved files: {moved}")
    print(f"articles copied: {copied}")


if __name__ == "__main__":
    main()
