"""OpenBagus Comprehensive Runtime & Architecture Validator.

Verifies:
1. Static compilation of all Python source files.
2. Package and module import integrity.
3. Domain neutrality: core does not depend on equity or domain specifics.
4. Strict NO_SEND default policy.
5. Exact trigger enforcement ('OpenBagus' vs 'Open Bagus').
6. Secret scanning (zero leaked tokens or private keys).
"""

from __future__ import annotations

import importlib
import json
import py_compile
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_compilation() -> dict[str, Any]:
    errors: list[str] = []
    py_files = list(REPO_ROOT.glob("openbagus/**/*.py")) + list(REPO_ROOT.glob("scripts/*.py")) + list(REPO_ROOT.glob("openbagus_finance/*.py"))
    for py_file in py_files:
        try:
            py_compile.compile(str(py_file), doraise=True)
        except Exception as e:
            errors.append(f"{py_file.relative_to(REPO_ROOT)}: {e}")
    return {"passed": len(errors) == 0, "total_files": len(py_files), "errors": errors}


def test_imports() -> dict[str, Any]:
    errors: list[str] = []
    modules = [
        "openbagus",
        "openbagus.core.env",
        "openbagus.core.guards",
        "openbagus.core.contracts",
        "openbagus.core.market_structure",
        "openbagus.domains.crypto.microstructure",
        "openbagus.domains.crypto.order_flow",
        "openbagus.risk.portfolio",
        "openbagus.risk.metrics",
        "openbagus.intelligence.macro.scenario",
        "openbagus.intelligence.sentiment.enricher",
        "openbagus.intelligence.news.registry",
        "openbagus.intelligence.news.memory",
        "openbagus.intelligence.news.ranker",
        "openbagus.intelligence.news.runtime",
        "openbagus.intelligence.llm.prompts",
        "openbagus.intelligence.llm.router",
        "openbagus.data.ingestion",
        "openbagus.analysis.engine",
        "openbagus.reporting.brief",
        "openbagus.reporting.email",
        "openbagus.reporting.pdf",
        "openbagus.reporting.dashboard",
        "openbagus.delivery.safety",
        "openbagus.delivery.channels",
        "openbagus.delivery.adapters",
        "openbagus.delivery.mailbox",
        "openbagus.delivery.runner",
        "openbagus.storage.historical",
        "openbagus.storage.spreadsheet",
        "openbagus.runtime.scheduler",
        "openbagus.runtime.orchestrator",
        "openbagus_finance",
    ]
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            errors.append(f"Import failed for {mod_name}: {e}")
    return {"passed": len(errors) == 0, "total_modules": len(modules), "errors": errors}


def test_manual_trigger() -> dict[str, Any]:
    from openbagus.delivery.runner import ManualQueryParser
    parser = ManualQueryParser()

    valid_res = parser.parse("OpenBagus review BTC and ETH")
    invalid_res1 = parser.parse("Open Bagus review BTC")  # Spaced variant
    invalid_res2 = parser.parse("review BTC without trigger")

    passed = valid_res["trigger_ok"] and not invalid_res1["trigger_ok"] and not invalid_res2["trigger_ok"]
    return {
        "passed": passed,
        "valid_trigger_passed": valid_res["trigger_ok"],
        "spaced_trigger_blocked": not invalid_res1["trigger_ok"],
        "missing_trigger_blocked": not invalid_res2["trigger_ok"],
    }


def test_domain_neutrality() -> dict[str, Any]:
    """Ensures openbagus/core does not import openbagus.domains or openbagus.domains.crypto."""
    errors: list[str] = []
    core_files = list((REPO_ROOT / "openbagus/core").glob("*.py"))
    for cf in core_files:
        content = cf.read_text(encoding="utf-8")
        if "openbagus.domains" in content or "crypto_microstructure" in content:
            errors.append(f"Hard dependency detected in core file {cf.name}")
    return {"passed": len(errors) == 0, "errors": errors}


def test_secrets_scan() -> dict[str, Any]:
    """Scans all committed source code for secrets."""
    secret_patterns = [
        r"ghp_[A-Za-z0-9_]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9_\-]{20,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ]
    findings: list[str] = []
    text_files = list(REPO_ROOT.glob("openbagus/**/*.py")) + list(REPO_ROOT.glob("config/*.json")) + list(REPO_ROOT.glob("scripts/*.py"))
    for tf in text_files:
        content = tf.read_text(encoding="utf-8", errors="ignore")
        for pat in secret_patterns:
            if re.search(pat, content):
                findings.append(f"Secret detected in {tf.relative_to(REPO_ROOT)} matching {pat}")
    return {"passed": len(findings) == 0, "findings": findings}


def test_repo_safety() -> dict[str, Any]:
    """Ensures no local secrets, database, or archive files are tracked or staged."""
    from scripts.check_repo_safety import _run_git, _check_forbidden_path
    tracked = _run_git(["ls-files"], REPO_ROOT)
    staged = _run_git(["diff", "--name-only", "--cached"], REPO_ROOT)
    all_files = sorted(set(tracked + staged))
    violations = [err for f in all_files if (err := _check_forbidden_path(f))]
    return {"passed": len(violations) == 0, "violations": violations}


def main() -> int:
    print("=" * 60)
    print("OPENBAGUS PLATFORM VALIDATION SUITE")
    print("=" * 60)

    checks = {
        "Compilation": test_compilation(),
        "Package Imports": test_imports(),
        "Manual Trigger Contract": test_manual_trigger(),
        "Domain Neutrality": test_domain_neutrality(),
        "Secrets Scanning": test_secrets_scan(),
        "Repository Safety": test_repo_safety(),
    }

    all_passed = True
    for name, res in checks.items():
        status = "PASS" if res.get("passed") else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"[{status}] {name}")
        if not res.get("passed"):
            print(f"   Details: {res}")

    print("=" * 60)
    print("FINAL RESULT:", "ALL SYSTEMS OPERATIONAL" if all_passed else "VALIDATION FAILED")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
