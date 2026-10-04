#!/usr/bin/env python3
"""OpenBagus Repository Safety Verification Script.

Inspects tracked and staged files to verify that local secrets, credentials,
databases, virtual environments, and machine-specific archives are never committed.
Uses Python standard library only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Explicitly forbidden path prefixes or exact names
FORBIDDEN_EXACT_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.secrets",
    ".local.env",
}

FORBIDDEN_DIR_PREFIXES = (
    ".local-archive/",
    ".local-archive\\",
    ".venv/",
    ".venv\\",
    "runtime/cache/",
    "runtime\\cache\\",
    ".cache/",
    ".cache\\",
    "reports/runtime/private/",
    "reports\\runtime\\private\\",
)

FORBIDDEN_EXTENSIONS = (
    ".pem",
    ".p12",
    ".pfx",
    ".duckdb",
    ".duckdb.wal",
    ".duckdb.tmp",
    ".sqlite",
    ".sqlite3",
    ".gguf",
    ".safetensors",
)

# Secret pattern signatures (redacted on detection)
SECRET_PATTERNS = [
    ("Private Key Header", re.compile(r"-----BEGIN (?:RSA|EC|DSA|OPENSSH|PGP|ENCRYPTED|PRIVATE) KEY", re.IGNORECASE)),
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub Personal Access Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,255}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9a-zA-Z]{10,48}\b")),
    ("Generic High-Entropy Secret Assignment", re.compile(r"""(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token|smtp[_-]?password)\s*=\s*['"][a-zA-Z0-9_\-]{24,}['"]""")),
]

# Paths allowed to contain test fixtures or documentation examples
EXEMPT_SCAN_PATHS = {
    ".env.example",
    "config/openbagus_runtime_local.env.example",
    "docs/configuration.md",
    "docs/email.md",
    "docs/architecture.md",
    "README.md",
    "SECURITY.md",
}


def _run_git(args: list[str], repo_root: Path) -> list[str]:
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _check_forbidden_path(rel_path: str) -> str | None:
    norm = rel_path.replace("\\", "/")
    base = os.path.basename(norm)

    if norm in FORBIDDEN_EXACT_NAMES:
        return f"Forbidden exact file name: {norm}"

    for pfx in FORBIDDEN_DIR_PREFIXES:
        pfx_norm = pfx.replace("\\", "/")
        if norm.startswith(pfx_norm) or f"/{pfx_norm}" in f"/{norm}":
            return f"Forbidden directory prefix: {pfx_norm}"

    # Database file check (allow empty .gitkeep)
    if any(norm.endswith(ext) for ext in FORBIDDEN_EXTENSIONS):
        return f"Forbidden file extension: {norm}"

    if norm.endswith(".db") and not norm.endswith(".gitkeep"):
        return f"Forbidden database file: {norm}"

    # Secret or credential files
    base_lower = base.lower()
    if base_lower.startswith(("credentials", "secrets", "tokens")) and not base_lower.endswith((".py", ".md", ".example")):
        return f"Forbidden credential file: {norm}"

    return None


def _scan_file_contents(repo_root: Path, rel_path: str) -> list[str]:
    norm = rel_path.replace("\\", "/")
    if norm in EXEMPT_SCAN_PATHS:
        return []
    if norm.startswith("tests/") and "test_" in norm:
        # Test files may test sanitization or dummy data
        return []

    target_path = repo_root / rel_path
    if not target_path.is_file():
        return []

    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    violations: list[str] = []
    for line_num, line in enumerate(content.splitlines(), 1):
        for pattern_name, regex in SECRET_PATTERNS:
            if regex.search(line):
                # Never print the secret itself
                violations.append(f"{norm}:{line_num} contains pattern '{pattern_name}'")
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    tracked_files = _run_git(["ls-files"], repo_root)
    staged_files = _run_git(["diff", "--name-only", "--cached"], repo_root)

    all_target_files = sorted(set(tracked_files + staged_files))
    if not all_target_files:
        print("[WARN] No tracked or staged files found to check.")
        return 0

    violations: list[str] = []

    # 1. Path-based check
    for f in all_target_files:
        err = _check_forbidden_path(f)
        if err:
            violations.append(f"[PATH VIOLATION] {err}")

    # 2. Content scan check
    for f in all_target_files:
        content_errs = _scan_file_contents(repo_root, f)
        for err in content_errs:
            violations.append(f"[SECRET VIOLATION] {err}")

    if violations:
        print("\n[FAIL] Repository safety check FAILED with the following violations:\n")
        for v in violations:
            print(f"  - {v}")
        print("\nPlease remove or unstage the sensitive files/data before proceeding.\n")
        return 1

    print(f"[PASS] Repository safety check passed ({len(all_target_files)} tracked/staged files verified clean).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
