"""V5.1 Acceptance Test Runner with detailed per-scenario metrics and timing."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

    print("=" * 70, flush=True)
    print("OPENBAGUS V5.1 REPOSITORY-LOCAL STORAGE & VOICE ACCEPTANCE", flush=True)
    print("=" * 70, flush=True)

    # Load test names and docstrings dynamically from the test class
    from tests.test_voice_runtime_v5 import TestVoiceRuntimeV5

    test_names = [m for m in dir(TestVoiceRuntimeV5) if m.startswith("test_")]
    test_names.sort()

    total_scenarios = len(test_names)
    print(f"Total scenarios discovered: {total_scenarios}\n", flush=True)

    passed = 0
    failed = 0
    t_total_start = time.perf_counter()

    # Run each test with clean native heap and process isolation
    for scenario_idx, test_name in enumerate(test_names, 1):
        method = getattr(TestVoiceRuntimeV5, test_name)
        doc = method.__doc__ or test_name
        short_doc = doc.strip().split("\n")[0]

        print(f"[{scenario_idx:02d}/{total_scenarios:02d}] {test_name} ... ", end="", flush=True)
        t0 = time.perf_counter()

        cmd = [
            sys.executable,
            "-m",
            "unittest",
            f"tests.test_voice_runtime_v5.TestVoiceRuntimeV5.{test_name}",
        ]
        res = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            env=dict(
                os.environ,
                KMP_DUPLICATE_LIB_OK="TRUE",
                PYTHONPATH=str(ROOT_DIR),
            ),
        )
        dt = (time.perf_counter() - t0) * 1000.0

        if res.returncode == 0:
            passed += 1
            print(f"PASS ({dt:.1f} ms)")
            print(f"       -> {short_doc}\n", flush=True)
        else:
            failed += 1
            print(f"FAIL ({dt:.1f} ms)")
            print(f"       -> {short_doc}")
            if res.stderr:
                err_lines = [
                    line for line in res.stderr.splitlines()
                    if "AssertionError" in line or "Error" in line
                ]
                for el in err_lines[:2]:
                    print(f"          ERR: {el.strip()}")
            print("", flush=True)

    total_time = time.perf_counter() - t_total_start
    print("=" * 70, flush=True)
    print(f"ACCEPTANCE AUDIT SUMMARY: {passed} PASSED, {failed} FAILED (Total time: {total_time:.2f}s)", flush=True)
    print("=" * 70, flush=True)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
