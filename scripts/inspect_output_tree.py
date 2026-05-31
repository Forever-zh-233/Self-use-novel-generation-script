# -*- coding: utf-8 -*-
"""用 ASCII 转义打印输出目录，避免终端编码把中文路径显示坏。"""

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "输出"


def names(path: Path):
    if not path.exists():
        return []
    return [item.name for item in path.iterdir()]


def main() -> None:
    payload = {"root": names(OUTPUT_DIR)}
    for dirname in ["文章", "写手", "门禁", "评审", "修稿", "记录员", "章纲", "上下文", "成稿", "context"]:
        path = OUTPUT_DIR / dirname
        if path.exists():
            payload[dirname] = names(path)
    print(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
