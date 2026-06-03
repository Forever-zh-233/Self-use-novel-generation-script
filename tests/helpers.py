# -*- coding: utf-8 -*-
"""Small test helpers with no third-party dependencies."""

from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class TestHarness:
    def __init__(self) -> None:
        self.result = TestResult()

    def section(self, title: str) -> None:
        print(f"\n=== {title} ===")

    def pass_(self, label: str) -> None:
        self.result.passed += 1
        print(f"  OK   {label}")

    def fail(self, label: str, detail: str = "") -> None:
        self.result.failed += 1
        suffix = f": {detail}" if detail else ""
        print(f"  FAIL {label}{suffix}")

    def skip(self, label: str, detail: str = "") -> None:
        self.result.skipped += 1
        suffix = f": {detail}" if detail else ""
        print(f"  SKIP {label}{suffix}")

    def check(self, label: str, condition: Any, detail: str = "") -> None:
        if condition:
            self.pass_(label)
        else:
            self.fail(label, detail)

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, f"expected={expected!r} actual={actual!r}")

    def includes(self, label: str, value: str, needle: str) -> None:
        self.check(label, needle in value, f"missing {needle!r}")

    def not_includes(self, label: str, value: str, needle: str) -> None:
        self.check(label, needle not in value, f"unexpected {needle!r}")

    def raises(self, label: str, func: Callable[[], Any], pattern: Optional[str] = None) -> None:
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - tests intentionally inspect arbitrary exceptions.
            message = str(exc)
            if pattern is None or pattern in message:
                self.pass_(label)
            else:
                self.fail(label, f"raised {message!r}, missing {pattern!r}")
        else:
            self.fail(label, "did not raise")


def ensure_scripts_path() -> None:
    scripts = str(SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def iter_files(*patterns: str) -> Iterable[Path]:
    for pattern in patterns:
        yield from ROOT.glob(pattern)


def clear_pipeline_modules() -> None:
    for name in list(sys.modules):
        if name == "pipeline" or name.startswith("pipeline."):
            del sys.modules[name]


@contextlib.contextmanager
def temp_workspace(prefix: str = "novel-test-") -> Iterator[Path]:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@contextlib.contextmanager
def isolated_workspace() -> Iterator[Path]:
    """Import pipeline modules against a fresh NOVEL_WORKSPACE.

    The production pipeline resolves BASE_DIR at import time. Tests that write
    state must import pipeline modules inside this context, then clear them on
    exit so the real workspace is never used as a write target.
    """
    old_workspace = os.environ.get("NOVEL_WORKSPACE")
    old_path = list(sys.path)
    clear_pipeline_modules()
    with temp_workspace() as tmp:
        os.environ["NOVEL_WORKSPACE"] = str(tmp)
        ensure_scripts_path()
        try:
            yield tmp
        finally:
            clear_pipeline_modules()
            if old_workspace is None:
                os.environ.pop("NOVEL_WORKSPACE", None)
            else:
                os.environ["NOVEL_WORKSPACE"] = old_workspace
            sys.path[:] = old_path


def import_fresh(module_name: str) -> Any:
    clear_pipeline_modules()
    ensure_scripts_path()
    return importlib.import_module(module_name)
