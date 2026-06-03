# -*- coding: utf-8 -*-
"""Novel 1 test runner.

Usage:
  python scripts/run_tests.py check
  python scripts/run_tests.py quick
  python scripts/run_tests.py scenario
  python scripts/run_tests.py all
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers import TestHarness  # noqa: E402


SUITES = {
    "check": ["tests.checks_test"],
    "quick": ["tests.quick_test"],
    "scenario": ["tests.scenario_test"],
    "all": ["tests.checks_test", "tests.quick_test", "tests.scenario_test"],
}


def run_suites(names: Iterable[str]) -> TestHarness:
    harness = TestHarness()
    for name in names:
        module = importlib.import_module(name)
        module.run(harness)
    return harness


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Novel 1 tests.")
    parser.add_argument(
        "suite",
        nargs="?",
        default="all",
        choices=sorted(SUITES.keys()),
        help="test suite to run",
    )
    args = parser.parse_args(argv)

    harness = run_suites(SUITES[args.suite])
    harness.section("summary")
    print(f"  passed: {harness.result.passed}")
    print(f"  failed: {harness.result.failed}")
    print(f"  skipped: {harness.result.skipped}")
    return 1 if harness.result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
