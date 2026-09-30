"""OpenBagus Delivery Safety Guard.

Scans outbound payloads and messages for secrets, prohibited trading instructions,
and regulatory violations before any adapter is allowed to stage or deliver.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

ENGINE_VERSION = "openbagus.delivery_safety_guard.v2"

FORBIDDEN_LITERAL_TERMS: tuple[str, ...] = (
    "BELI SEKARANG",
    "JUAL SEKARANG",
    "PASTI NAIK",
    "PASTI TURUN",
    "BUY NOW",
    "SELL NOW",
    "GUARANTEED TO RISE",
    "GUARANTEED TO FALL",
    "guaranteed profit",
    "profit pasti",
    "auto order enabled",
    "broker order enabled",
    "exchange order enabled",
    "execute broker order",
    "execute exchange order",
    "place broker order",
    "place exchange order",
    "private key",
    "seed phrase",
    "recovery phrase",
)

SECRET_PATTERNS: dict[str, str] = {
    "openai_style_secret": r"\bsk-[A-Za-z0-9_\-]{20,}\b",
    "github_token": r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b",
    "generic_bearer_token": r"\bBearer\s+[A-Za-z0-9_\-\.]{25,}\b",
    "long_api_token_like": r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{16,}",
    "whatsapp_group_jid": r"\b\d{10,}@g\.us\b",
    "indonesia_phone": r"\b(?:\+62|62|08)\d{8,13}\b",
    "smtp_password_assignment": r"(?i)\bsmtp[_-]?password\s*[:=]\s*['\"]?[^'\"\s]{8,}",
    "ntfy_token_assignment": r"(?i)\bntfy[_-]?token\s*[:=]\s*['\"]?[^'\"\s]{8,}",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt_like_token": r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\b",
}

POLICY_PATTERNS: dict[str, str] = {
    "broker_exchange_execution": r"(?i)\b(execute|place|submit|kirim)\b.{0,40}\b(broker|exchange|order)\b",
}


def scan_text(text: str) -> dict[str, Any]:
    """Scans plain text for safety violations."""
    findings: list[dict[str, str]] = []
    lowered = text.lower()

    for term in FORBIDDEN_LITERAL_TERMS:
        if term.lower() in lowered:
            findings.append({"type": "forbidden_literal", "name": term})

    for name, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, text):
            findings.append({"type": "secret_or_private_identifier", "name": name})

    for name, pattern in POLICY_PATTERNS.items():
        if re.search(pattern, text):
            findings.append({"type": "policy_violation", "name": name})

    return {
        "engine_version": ENGINE_VERSION,
        "passed": not findings,
        "findings": findings,
    }


def scan_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Serializes a mapping and scans the representation."""
    text = json.dumps(payload, ensure_ascii=False)
    return scan_text(text)
