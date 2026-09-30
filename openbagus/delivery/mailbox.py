"""OpenBagus Mailbox Archive Policy.

Manages retention, cleanup, and indexing of delivered reports and drafts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root


class MailboxArchivePolicy:
    """Enforces retention limit and archives historical delivery reports."""

    def __init__(self, repo_root: Path | None = None, max_retention_days: int = 30) -> None:
        self.root = repo_root or get_repo_root()
        self.max_retention_days = max_retention_days
        self.delivery_dir = self.root / "reports/runtime/delivery"

    def audit(self) -> dict[str, Any]:
        if not self.delivery_dir.exists():
            return {"total_files": 0, "status": "DIRECTORY_EMPTY"}

        files = list(self.delivery_dir.glob("*.*"))
        return {
            "total_files": len(files),
            "directory": str(self.delivery_dir),
            "retention_policy_days": self.max_retention_days,
            "status": "OK",
        }
