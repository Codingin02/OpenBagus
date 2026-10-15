"""Secure Credential Management and Secret Redaction for OpenBagus.

Stores and manages optional API keys with OS-scoped isolation,
strict masking (sk-...1234), redaction from logs/exceptions,
and detailed provider authentication status taxonomy.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_CREDENTIAL_STATUSES = (
    "NOT_CONFIGURED",
    "CONFIGURED_UNVERIFIED",
    "AUTHENTICATED",
    "MODEL_ACCESS_VERIFIED",
    "INVALID_CREDENTIALS",
    "PERMISSION_DENIED",
    "MODEL_UNAVAILABLE",
    "BILLING_REQUIRED",
    "QUOTA_EXCEEDED",
    "RATE_LIMITED",
    "NETWORK_ERROR",
    "PROVIDER_UNAVAILABLE",
    "DISABLED",
)


def mask_secret(secret: str | None) -> str:
    """Masks a secret key preserving only prefix and last 4 characters: e.g. sk-...a1b2."""
    if not secret:
        return ""
    s = secret.strip()
    if len(s) <= 8:
        return "********"
    if s.startswith("sk-"):
        return f"sk-...{s[-4:]}"
    if s.startswith("AIza"):
        return f"AIza...{s[-4:]}"
    return f"{s[:3]}...{s[-4:]}"


def redact_secrets(text: str, secrets: list[str]) -> str:
    """Removes literal secret occurrences from error strings or logs."""
    res = text
    for sec in secrets:
        if sec and len(sec) > 5 and sec in res:
            res = res.replace(sec, mask_secret(sec))
    return res


class CredentialManager:
    """Manages provider API keys using user-scoped storage with environment fallback."""

    _instance: CredentialManager | None = None

    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is not None:
            self.base_dir = storage_dir
        else:
            user_home = Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "~"))).expanduser()
            self.base_dir = user_home / ".openbagus"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.creds_file = self.base_dir / "credentials.json"
        self._cache: dict[str, dict[str, Any]] = self._load()

    @classmethod
    def get_instance(cls, storage_dir: Path | None = None) -> "CredentialManager":
        if cls._instance is None:
            cls._instance = cls(storage_dir)
        return cls._instance

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.creds_file.exists():
            return {}
        try:
            return json.loads(self.creds_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Gagal membaca credentials file: %s", e)
            return {}

    def _save(self) -> None:
        try:
            self.creds_file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Gagal menyimpan credentials: %s", e)

    def set_credential(self, provider: str, key: str, status: str = "CONFIGURED_UNVERIFIED") -> dict[str, Any]:
        """Saves a credential record securely with masked display."""
        clean_p = provider.lower().strip()
        clean_k = key.strip()
        record = {
            "provider": clean_p,
            "masked_key": mask_secret(clean_k),
            "key": clean_k,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._cache[clean_p] = record
        self._save()
        return {
            "provider": clean_p,
            "masked_key": record["masked_key"],
            "status": record["status"],
            "updated_at": record["updated_at"],
        }

    def get_credential(self, provider: str) -> str | None:
        """Retrieves plaintext key checking local storage, then environment variables."""
        clean_p = provider.lower().strip()
        rec = self._cache.get(clean_p)
        if rec and rec.get("key"):
            return str(rec["key"])

        env_map = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "bps": "BPS_API_KEY",
            "eodhd": "EODHD_API_KEY",
            "binance": "BINANCE_API_KEY",
        }
        env_var = env_map.get(clean_p)
        if env_var:
            val = os.environ.get(env_var)
            if val and val.strip():
                return val.strip()

        return None

    def get_status(self, provider: str) -> str:
        clean_p = provider.lower().strip()
        rec = self._cache.get(clean_p)
        if rec and rec.get("status"):
            return str(rec["status"])
        if self.get_credential(clean_p):
            return "CONFIGURED_UNVERIFIED"
        return "NOT_CONFIGURED"

    def update_status(self, provider: str, status: str, error_message: str | None = None) -> None:
        clean_p = provider.lower().strip()
        if clean_p in self._cache:
            self._cache[clean_p]["status"] = status
            if error_message:
                self._cache[clean_p]["last_error"] = error_message
            self._cache[clean_p]["verified_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def remove_credential(self, provider: str) -> bool:
        clean_p = provider.lower().strip()
        if clean_p in self._cache:
            del self._cache[clean_p]
            self._save()
            return True
        return False

    def list_credentials(self) -> list[dict[str, Any]]:
        """Returns metadata list of all configured credentials with strictly masked secrets."""
        results = []
        for p in ["openai", "gemini", "bps", "eodhd", "binance"]:
            key = self.get_credential(p)
            st = self.get_status(p)
            results.append({
                "provider": p.upper(),
                "configured": bool(key),
                "masked_key": mask_secret(key) if key else "NOT_SET",
                "status": st,
            })
        return results
