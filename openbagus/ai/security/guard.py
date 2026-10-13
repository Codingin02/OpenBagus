"""Security guard, prompt-injection defense, and dangerous action approval."""

from __future__ import annotations

import re
from typing import Any

INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    r"system\s+override",
    r"you\s+are\s+now\s+in\s+developer\s+mode",
    r"disregard\s+all\s+(?:rules|policies)",
    r"bypass\s+all\s+safety",
    r"forget\s+your\s+role",
    r"print\s+system\s+prompt",
    r"show\s+secret\s+keys",
    r"reveal\s+(?:all\s+)?api\s*keys",
    r"format\s+c:",
    r"drop\s+table",
    r"rm\s+-rf",
]

SENSITIVE_REDACTION_PATTERNS = [
    (r"(?i)(api[_-]?key|bearer\s+|secret[_-]?token|password)\s*[:=]\s*([a-zA-Z0-9_\-\.]{8,})", r"\1: [REDACTED_SECRET]"),
]


class SecurityGuard:
    """Monitors incoming user queries, tool arguments, and external text for injection and risk."""

    @classmethod
    def sanitize_untrusted_text(cls, text: str) -> str:
        """Sanitizes text originating from external PDFs, disclosures, or web scrapes."""
        if not text:
            return ""

        sanitized = text
        for pat in INJECTION_PATTERNS:
            sanitized = re.sub(pat, "[BLOCKED_INJECTION_PATTERN]", sanitized, flags=re.IGNORECASE)

        for pat, repl in SENSITIVE_REDACTION_PATTERNS:
            sanitized = re.sub(pat, repl, sanitized)

        return sanitized

    @classmethod
    def check_prompt_injection(cls, query: str) -> bool:
        """Returns True if a prompt injection attempt is detected in user input."""
        q = query.lower()
        for pat in INJECTION_PATTERNS:
            if re.search(pat, q):
                return True
        return False

    @classmethod
    def is_dangerous_action(cls, action_name: str, arguments: dict[str, Any]) -> bool:
        """Returns True if action requires explicit user confirmation before executing."""
        act = action_name.lower()
        if any(w in act for w in ["delete", "drop", "wipe", "format", "clear_all_databases", "real_trade_execution"]):
            return True
        if "order_placement" in act or "broker_execute" in act:
            return True
        return False

    @classmethod
    def validate_tool_arguments(cls, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str | None]:
        """Validates arguments against path traversal and unauthorized system access."""
        for k, v in arguments.items():
            if isinstance(v, str):
                if ".." in v or v.startswith("/") or v.startswith("\\"):
                    if not any(k.endswith(x) for x in ["ticker", "symbol", "query", "board"]):
                        return False, f"Potensi path traversal terdeteksi pada argumen '{k}'."
        return True, None
