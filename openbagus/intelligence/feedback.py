"""Opt-in local product feedback; never uploads or retains raw conversation."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from openbagus.delivery.safety import SECRET_PATTERNS


def sanitize_text(text: str) -> str:
    text = str(text)[:12000]
    from openbagus.core.env import RuntimeEnv, get_repo_root
    values = RuntimeEnv(get_repo_root()).subprocess_env()
    for key, value in values.items():
        if re.search(r"KEY|TOKEN|PASSWORD|SECRET|RECIPIENT|EMAIL_|JID|PHONE|TOPIC", key, re.I) and len(value) >= 4:
            text = text.replace(value, "[redacted]")
    for pattern in SECRET_PATTERNS.values():
        text = re.sub(pattern, "[redacted]", text)
    text = re.sub(r"(?i)\b(?:[\w-]*(?:password|token|api[_-]?key|secret)[\w-]*)\s*[:=]\s*[^\s,;]+", "[redacted]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted]", text)
    text = re.sub(r"(?i)(?:[a-z]:[\\/]|/home/|/Users/|/mnt/)[^\s\"<>]+", "[private path]", text)
    text = re.sub(r"\b0x[0-9a-fA-F]{40,}\b|\b(?:bc1|[13])[a-zA-Z0-9]{25,62}\b", "[wallet redacted]", text)
    return text


class FeedbackStore:
    KINDS = {"intent", "interpretation", "asset", "provider", "geometry", "contradiction", "suggestion"}

    def __init__(self, directory: Path | None = None) -> None:
        from openbagus.intelligence.local_language import get_local_appdata_dir
        self.directory = directory or get_local_appdata_dir() / "feedback"
        self.settings = self.directory / "settings.json"
        self.entries = self.directory / "entries.jsonl"

    @property
    def enabled(self) -> bool:
        try:
            return json.loads(self.settings.read_text(encoding="utf-8")).get("enabled") is True
        except (OSError, ValueError, AttributeError):
            return False

    def set_enabled(self, enabled: bool) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")

    def record(self, kind: str, correction: str, asset: str | None = None, timeframe: str = "") -> str:
        if not self.enabled:
            return "FEEDBACK_OFF"
        if kind not in self.KINDS or not correction.strip():
            return "FEEDBACK_INVALID: " + ", ".join(sorted(self.KINDS))
        entry = {"type": kind, "correction": sanitize_text(correction)[:1200],
                 "asset": asset if asset and re.fullmatch(r"[A-Z0-9]{1,20}", asset) else None,
                 "timeframe": timeframe if re.fullmatch(r"[A-Z0-9]{1,8}", timeframe) else "",
                 "recorded_at": datetime.now(timezone.utc).isoformat()}
        with self.entries.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return "FEEDBACK_SAVED_LOCAL"

    def review(self) -> str:
        try:
            return sanitize_text(self.entries.read_text(encoding="utf-8"))
        except OSError:
            return ""

    def export(self, reviewed: bool = False) -> Path | None:
        if not reviewed:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "reviewed-export.jsonl"
        path.write_text(self.review(), encoding="utf-8")
        return path

    def clear(self) -> None:
        self.entries.unlink(missing_ok=True)
        (self.directory / "reviewed-export.jsonl").unlink(missing_ok=True)
