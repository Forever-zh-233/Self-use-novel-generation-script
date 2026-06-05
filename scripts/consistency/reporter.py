# -*- coding: utf-8 -*-
"""Phase 3: REPORT — 将 issues_raw.json 生成人可读的 markdown 报告。

每次扫描留一份带时间戳的新报告（不覆盖历史），并更新 latest.md。
报告按"本次新增" / "存量"分栏，让你只需看新增部分。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .llm import BASE_DIR

CONSISTENCY_DIR = BASE_DIR / "consistency"
REPORTS_DIR = CONSISTENCY_DIR / "reports"

SEV_LABEL = {"critical": "🔴 严重", "warning": "🟡 警告", "note": "🟢 备注"}
SEV_ORDER = ["critical", "warning", "note"]


def run_report_phase() -> str:
    """读取 issues_raw.json，生成带时间戳的报告 + latest.md，返回报告内容。"""
    raw_path = CONSISTENCY_DIR / "issues_raw.json"
    if not raw_path.exists():
        print("  [REPORT] issues_raw.json 不存在，请先运行 --check")
        return ""

    data = json.loads(raw_path.read_text(encoding="utf-8"))
    issues = data.get("issues", [])
    scan_time = data.get("scan_time", "?")
    ch_range = data.get("chapters_scanned", [0, 0])
    watermark_prev = data.get("watermark_prev", 0)

    new_issues = [i for i in issues if i.get("is_new")]
    old_issues = [i for i in issues if not i.get("is_new")]

    lines = [
        "# 全量一致性扫描报告",
        f"- 扫描范围: 第{ch_range[0]}-{ch_range[1]}章",
        f"- 生成时间: {scan_time}",
        f"- 上次水位线: 第{watermark_prev}章" + ("（首次扫描）" if watermark_prev == 0 else ""),
        f"- 总问题数: {len(issues)}（🆕 本次新增 {len(new_issues)} / 📋 存量 {len(old_issues)}）",
        "",
        "> 🆕 新增 = 涉及章节中有任意一章超过上次水位线（含新章与旧章的交叉矛盾）。",
        "> 优先看新增部分；存量问题是上次扫描已存在、尚未处理的。",
        "",
    ]

    # ===== 本次新增 =====
    lines.append("---")
    lines.append("")
    lines.append(f"# 🆕 本次新增（{len(new_issues)} 条）")
    lines.append("")
    if new_issues:
        lines.extend(_render_by_severity(new_issues))
    else:
        lines.append("本次扫描没有新增问题。")
        lines.append("")

    # ===== 存量问题 =====
    if old_issues:
        lines.append("---")
        lines.append("")
        lines.append(f"# 📋 存量问题（{len(old_issues)} 条，上次扫描范围内）")
        lines.append("")
        lines.extend(_render_by_severity(old_issues))

    report = "\n".join(lines)

    # 写带时间戳的报告文件（不覆盖历史）
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d_%H%M")
    range_tag = f"{ch_range[0]:03d}-{ch_range[1]:03d}"
    report_file = REPORTS_DIR / f"report_{range_tag}_{date_tag}.md"
    report_file.write_text(report, encoding="utf-8")

    # 更新 latest.md（始终指向最新一份）
    latest_file = REPORTS_DIR / "latest.md"
    latest_file.write_text(report, encoding="utf-8")

    print(f"  报告已生成: {report_file.relative_to(BASE_DIR)}")
    print(f"  最新副本: {latest_file.relative_to(BASE_DIR)}")
    return report


def _render_by_severity(issues: List[dict]) -> List[str]:
    """按严重程度分组渲染。"""
    lines = []
    for sev in SEV_ORDER:
        bucket = [i for i in issues if i.get("severity") == sev]
        if not bucket:
            continue
        lines.append(f"## {SEV_LABEL[sev]}（{len(bucket)} 条）")
        lines.append("")
        for idx, issue in enumerate(bucket, 1):
            lines.extend(_format_issue(idx, issue))
    return lines


def _format_issue(index: int, issue: dict) -> List[str]:
    """格式化单条问题。"""
    dim = issue.get("dimension", "?")
    desc = issue.get("description", "")
    chapters = issue.get("chapters", [])
    evidence = issue.get("evidence") or {}
    category = issue.get("category", "")

    title = desc.split(":", 1)[-1].strip() if ":" in desc else desc[:50]
    lines = [f"### {index}. [{dim}] {title}"]

    ch_str = "、".join(f"第{ch}章" for ch in chapters)
    lines.append(f"- 涉及章节: {ch_str}")
    lines.append(f"- 类别: {category}")
    lines.append(f"- 描述: {desc}")

    if evidence:
        lines.append("- 证据:")
        for key, val in evidence.items():
            if isinstance(val, dict):
                lines.append(f"  - {key}: {json.dumps(val, ensure_ascii=False)}")
            else:
                lines.append(f"  - {key}: {val}")

    lines.append("")
    return lines
