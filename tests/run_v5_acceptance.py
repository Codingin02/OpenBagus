"""V5.0 Acceptance Test Runner with detailed per-scenario metrics and timing."""

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


def main() -> int:
    print("=" * 70)
    print("OPENBAGUS V5.0 VOICE QUALITY RECOVERY - 20 SCENARIOS ACCEPTANCE")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_voice_runtime_v5")

    def flatten(s: Any) -> list[unittest.TestCase]:
        res: list[unittest.TestCase] = []
        for item in s:
            if isinstance(item, unittest.TestSuite):
                res.extend(flatten(item))
            else:
                res.append(item)
        return res

    all_tests = flatten(suite)
    print(f"Total scenarios discovered: {len(all_tests)}\n")

    passed_count = 0
    failed_count = 0
    t_suite_start = time.perf_counter()

    for idx, test_case in enumerate(all_tests, start=1):
        name = test_case._testMethodName
        doc = getattr(test_case, name).__doc__ or ""
        short_doc = doc.strip().split("\n")[0] if doc else name

        print(f"[{idx:02d}/20] {name} ... ", end="", flush=True)
        t_start = time.perf_counter()
        result = unittest.TestResult()
        test_case.run(result)
        dt = (time.perf_counter() - t_start) * 1000.0

        if result.wasSuccessful():
            passed_count += 1
            print(f"PASS ({dt:.1f} ms)")
            print(f"       -> {short_doc}")
        else:
            failed_count += 1
            print(f"FAIL ({dt:.1f} ms)")
            print(f"       -> {short_doc}")
            if result.failures:
                for _, tb in result.failures:
                    for line in tb.strip().split("\n"):
                        print(f"          | {line}")
            if result.errors:
                for _, tb in result.errors:
                    for line in tb.strip().split("\n"):
                        print(f"          | {line}")
        print()

    total_time = time.perf_counter() - t_suite_start
    print("=" * 70)
    print(f"ACCEPTANCE AUDIT SUMMARY: {passed_count} PASSED, {failed_count} FAILED (Total time: {total_time:.2f}s)")
    print("=" * 70)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    import os
    os._exit(code)
