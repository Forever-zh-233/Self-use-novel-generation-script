# -*- coding: utf-8 -*-
"""Syntax, repository, and structure guard tests."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Iterable, List

from .helpers import ROOT, TestHarness, read_text


PYTHON_GLOBS = [
    "scripts/*.py",
    "scripts/pipeline/*.py",
    "tests/*.py",
]

REQUIRED_FILES = [
    "agent.md",
    "README-使用说明.md",
    "01-风格指南.md",
    "02-世界观设定圣经.md",
    "02-修炼境界.md",
    "03-角色声音表.md",
    "05-章节生成协议.md",
    "06-验证打分表.md",
    "09-故事核.md",
    "11-负空间.md",
    "12-AI腔黑名单.md",
    "15-长线伏笔资产库.md",
    "卷纲/10-卷纲.md",
    "config/models.json",
    "config/run.json",
    "chunks/index.json",
    "scripts/run_pipeline.py",
    "scripts/pipeline/core.py",
    "scripts/pipeline/api.py",
    "scripts/pipeline/state.py",
    "scripts/pipeline/context.py",
    "scripts/pipeline/gates.py",
    "scripts/pipeline/planning.py",
    "scripts/pipeline/archivist.py",
]

REQUIRED_PROMPTS = [
    "analyst.md",
    "archivist.md",
    "arc_planner.md",
    "beat_planner.md",
    "compressor.md",
    "fact_checker.md",
    "master_outline.md",
    "reviewer.md",
    "story_director.md",
    "volume_planner.md",
    "writer.md",
    "writer_pov.md",
]

GITIGNORED_PRIVATE_OR_RUNTIME = [
    ".env.local",
    "271824.txt",
    "runtime",
    "输出",
    "beats",
    "分析草稿",
    "台账版本",
]

SOURCE_TEXT_NAMES = {"271824.txt"}
RUNTIME_DIR_NAMES = {"runtime", "输出", "beats", "分析草稿", "台账版本"}


def _python_files() -> List[Path]:
    files: List[Path] = []
    for pattern in PYTHON_GLOBS:
        files.extend(ROOT.glob(pattern))
    return sorted({path for path in files if path.is_file()})


def _load_json(path: Path):
    return json.loads(read_text(path))


def _git(args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run(h: TestHarness) -> None:
    h.section("check: python syntax")
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            source = read_text(path)
            compile(source, str(path), "exec")
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            h.fail(f"python syntax: {rel}", f"{exc.msg} line {exc.lineno}")
        else:
            h.pass_(f"python syntax: {rel}")

    h.section("check: required project files")
    for rel in REQUIRED_FILES:
        h.check(f"required file exists: {rel}", (ROOT / rel).is_file())
    for rel in REQUIRED_PROMPTS:
        h.check(f"required prompt exists: prompts/{rel}", (ROOT / "prompts" / rel).is_file())

    h.section("check: json config")
    for rel in ["config/models.json", "config/run.json", "chunks/index.json"]:
        try:
            data = _load_json(ROOT / rel)
        except Exception as exc:  # noqa: BLE001 - test reports exact parse failure.
            h.fail(f"json parses: {rel}", str(exc))
        else:
            h.check(f"json parses: {rel}", isinstance(data, dict), "top level must be object")

    models = _load_json(ROOT / "config/models.json")
    providers = models.get("providers") or {}
    roles = models.get("roles") or {}
    h.check("models has providers", isinstance(providers, dict) and bool(providers))
    h.check("models has roles", isinstance(roles, dict) and bool(roles))
    for role in [
        "arc_planner",
        "story_director",
        "fact_checker",
        "volume_planner",
        "master_outline",
        "analyst",
        "beat_planner",
        "writer",
        "reviewer",
        "editor",
        "archivist",
        "compressor",
    ]:
        cfg = roles.get(role) or {}
        h.check(f"role configured: {role}", isinstance(cfg, dict) and bool(cfg))
        provider_name = cfg.get("provider") or models.get("defaultProvider")
        h.check(f"role provider exists: {role}", provider_name in providers, str(provider_name))
        h.check(f"role model set: {role}", bool(cfg.get("model")), str(cfg))

    run_cfg = _load_json(ROOT / "config/run.json").get("run") or {}
    h.check("run config has max_input_tokens", isinstance(run_cfg.get("max_input_tokens"), dict))
    h.check("run config has context_windows", isinstance(run_cfg.get("context_windows"), dict))
    h.check("run config limits chapters per run", int(run_cfg.get("max_chapters_per_run") or 0) > 0)

    h.section("check: chunk index")
    index = _load_json(ROOT / "chunks/index.json")
    h.check("chunk index is non-empty", bool(index))
    categories = {str(value.get("category")) for value in index.values() if isinstance(value, dict)}
    for category in ["必选", "角色", "场景", "故事核", "卷纲"]:
        h.check(f"chunk index includes category: {category}", category in categories, str(sorted(categories)))
    for key, value in sorted(index.items()):
        if not isinstance(value, dict):
            h.fail(f"chunk entry object: {key}", repr(value))
            continue
        file_name = value.get("file")
        h.check(f"chunk file declared: {key}", bool(file_name), repr(value))
        if file_name:
            h.check(f"chunk file exists: {key}", (ROOT / "chunks" / str(file_name)).is_file(), str(file_name))
        tokens = value.get("tokens")
        h.check(f"chunk token count numeric: {key}", isinstance(tokens, int) and tokens >= 0, repr(tokens))

    h.section("check: gitignore privacy and runtime boundaries")
    tracked = _git(["ls-files"])
    tracked_files = set(tracked.stdout.splitlines())
    for rel in SOURCE_TEXT_NAMES:
        h.check(f"source text is not tracked: {rel}", rel not in tracked_files)
    for rel in GITIGNORED_PRIVATE_OR_RUNTIME:
        result = _git(["check-ignore", "-q", rel])
        h.check(f"gitignored: {rel}", result.returncode == 0, result.stderr.strip())
    for rel in RUNTIME_DIR_NAMES:
        tracked_under = [item for item in tracked_files if item == rel or item.startswith(rel + "/")]
        h.check(f"runtime/generated path not tracked: {rel}", not tracked_under, ", ".join(tracked_under[:5]))

    h.section("check: agent guardrails are documented")
    agent = read_text(ROOT / "agent.md")
    for needle in [
        "反 Goodhart",
        "代码**绝不**做创意/风格判断",
        "有牙齿的代码检查只允许",
        "分数表（输出/分数表/）是 WRITE-ONLY",
        "MIMO_API_KEY",
    ]:
        h.includes(f"agent guardrail: {needle}", agent, needle)
