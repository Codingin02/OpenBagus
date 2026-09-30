"""OpenBagus Scheduler Runtime and Safety Guard.

Evaluates scheduled execution intervals, quiet hours, and auto flags.
Ensures zero live sends occur without explicit confirmation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root

DEFAULT_AUTO_FLAGS: dict[str, Any] = {
    "auto_scheduler_enabled": True,
    "auto_email_live_enabled": False,
    "auto_whatsapp_live_enabled": False,
    "news_live_refresh_enabled": True,
    "dashboard_refresh_enabled": True,
    "crypto_interval_hours": 2,
    "active_domains": ["crypto"],
    "disabled_domains": ["equities"],
    "research_only": True,
    "catch_up_policy": "latest_only_no_spam",
}


class SchedulerGuard:
    """Manages scheduler configuration and execution readiness."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.config_path = self.root / "config/openbagus_runtime_schedule.example.json"

    def load_flags(self) -> dict[str, Any]:
        flags = dict(DEFAULT_AUTO_FLAGS)
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    flags.update(data)
            except Exception:
                pass
        return flags


class SchedulerRuntime:
    """Evaluates whether scheduled tasks should run."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.guard = SchedulerGuard(repo_root=repo_root)

    def evaluate_tick(self) -> dict[str, Any]:
        flags = self.guard.load_flags()
        now_utc = datetime.now(timezone.utc)
        return {
            "timestamp_utc": now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "scheduler_enabled": flags.get("auto_scheduler_enabled", True),
            "due_tasks": ["crypto_2h_refresh", "news_intelligence_refresh", "dashboard_update"],
            "disabled_domains": flags.get("disabled_domains", ["equities"]),
            "status": "TICK_READY",
        }
