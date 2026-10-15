"""V5.1 Acceptance Test Runner with detailed per-scenario metrics and timing."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from typing import Any
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class FormattedAcceptanceResult(unittest.TextTestResult):
    """Custom TestResult that outputs scenario-by-scenario metrics in real time."""

    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.current_idx = 0
        self.total_count = 31
        self.t_test_start = 0.0
        self.short_doc = ""

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.current_idx += 1
        name = test._testMethodName
        doc = getattr(test, name).__doc__ or ""
        self.short_doc = doc.strip().split("\n")[0] if doc else name
        self.stream.write(f"[{self.current_idx:02d}/{self.total_count:02d}] {name} ... ")
        self.stream.flush()
        self.t_test_start = time.perf_counter()

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        dt = (time.perf_counter() - self.t_test_start) * 1000.0
        self.stream.write(f"PASS ({dt:.1f} ms)\n       -> {self.short_doc}\n\n")
        self.stream.flush()

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        dt = (time.perf_counter() - self.t_test_start) * 1000.0
        self.stream.write(f"FAIL ({dt:.1f} ms)\n       -> {self.short_doc}\n\n")
        self.stream.flush()

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        dt = (time.perf_counter() - self.t_test_start) * 1000.0
        self.stream.write(f"ERROR ({dt:.1f} ms)\n       -> {self.short_doc}\n\n")
        self.stream.flush()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

    print("=" * 70, flush=True)
    print("OPENBAGUS V5.1 REPOSITORY-LOCAL STORAGE & VOICE ACCEPTANCE", flush=True)
    print("=" * 70, flush=True)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_voice_runtime_v5")

    total_scenarios = suite.countTestCases()
    print(f"Total scenarios discovered: {total_scenarios}\n", flush=True)

    class CustomRunner(unittest.TextTestRunner):
        resultclass = FormattedAcceptanceResult

    runner = CustomRunner(stream=sys.stdout, verbosity=0)
    t_start = time.perf_counter()
    result = runner.run(suite)
    total_time = time.perf_counter() - t_start

    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)

    print("=" * 70, flush=True)
    print(f"ACCEPTANCE AUDIT SUMMARY: {passed} PASSED, {failed} FAILED (Total time: {total_time:.2f}s)", flush=True)
    print("=" * 70, flush=True)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    code = main()
    sys.exit(code)
