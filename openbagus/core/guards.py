"""Guards and compliance policies for OpenBagus.

Includes:
1. ResearchOutputGuard: prevents immediate buy/sell instructions, guaranteed return claims,
   broker order enablement, and accidental secret disclosure.
2. PathPolicyGuard: ensures runtime directories, configs, and reports stay within approved local drives
   and blocks OneDrive for runtime state/secrets.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ENGINE_VERSION = "openbagus.core.guards.v1"

SECRET_PATTERNS: dict[str, str] = {
    "openai_style_secret": r"\bsk-[A-Za-z0-9_\-]{20,}\b",
    "github_token": r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b",
    "generic_bearer_token": r"\bBearer\s+[A-Za-z0-9_\-\.]{25,}\b",
    "whatsapp_group_jid": r"\b\d{10,}@g\.us\b",
    "indonesia_phone": r"\b(?:\+62|62|08)\d{8,13}\b",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}

FORBIDDEN_WORDING_PATTERNS: dict[str, str] = {
    "immediate_buy_instruction": r"(?i)\b(beli\s+sekarang|buy\s+now)\b",
    "immediate_sell_instruction": r"(?i)\b(jual\s+sekarang|sell\s+now)\b",
    "certain_up_claim": r"(?i)\b(pasti\s+naik|guaranteed\s+to\s+rise)\b",
    "certain_down_claim": r"(?i)\b(pasti\s+turun|guaranteed\s+to\s+fall)\b",
    "certain_profit_claim": r"(?i)\b(profit\s+pasti|guaranteed\s+profit)\b",
    "broker_order_enabled": r"(?i)\b(broker|exchange)\s+order\s+enabled\b",
    "execute_order": r"(?i)\bexecute\s+(broker|exchange)\s+order\b",
}


def scan_text(text: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for name, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, text):
            findings.append({"type": "secret_or_private_identifier", "name": name})
    for name, pattern in FORBIDDEN_WORDING_PATTERNS.items():
        if re.search(pattern, text):
            findings.append({"type": "forbidden_wording", "name": name})
    return {
        "engine_version": ENGINE_VERSION,
        "passed": not findings,
        "findings": findings,
        "forbidden_wording_found": any(item["type"] == "forbidden_wording" for item in findings),
        "secret_like_found": any(item["type"] == "secret_or_private_identifier" for item in findings),
    }


def guard_payload(payload: Mapping[str, Any], markdown: str | None = None) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if markdown:
        text += "\n" + markdown
    result = scan_text(text)
    result.update(
        {
            "research_only": True,
            "broker_exchange_order_enabled": False,
            "private_trading_api_connected": False,
            "whatsapp_send_enabled": False,
            "llm_decision_core": False,
            "numeric_decision_core": "Python Quant Engine",
        }
    )
    return result


class ResearchOutputGuard:
    """Validator for research output compliance."""

    @staticmethod
    def validate(payload: Mapping[str, Any], extra_text: str = "") -> dict[str, Any]:
        return guard_payload(payload, extra_text)


class PathPolicyGuard:
    """Ensures runtime execution adheres to local path safety policies."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]

    def evaluate(self) -> dict[str, Any]:
        user_profile = os.environ.get("USERPROFILE", "")
        documents = Path(user_profile) / "OneDrive" / "Documents" / "PowerShell" if user_profile else Path("")
        profile_warning = "onedrive" in str(documents).lower()
        
        checked_paths = {
            "project_root": str(self.repo_root),
            "project_reports": str(self.repo_root / "reports"),
            "project_logs": str(self.repo_root / "logs"),
        }
        forbidden_hits = [
            {"name": name, "path": path}
            for name, path in checked_paths.items()
            if path and "onedrive" in path.lower()
        ]
        status = "BLOCKED_ONEDRIVE_CONFIG_PATH" if forbidden_hits else "PATH_POLICY_READY"
        return {
            "engine_version": ENGINE_VERSION,
            "status": status,
            "project_root": str(self.repo_root),
            "onedrive_runtime_config_allowed": False,
            "onedrive_profile_warning": "ONEDRIVE_PROFILE_WARNING" if profile_warning else "NO_ONEDRIVE_PROFILE_WARNING",
            "forbidden_hits": forbidden_hits,
            "checked_paths": checked_paths,
            "secret_values_logged": False,
        }
