"""OpenBagus Delivery Channels and Status Tracker.

Defines channels, recipient mappings, and delivery status serialization.
Ensures default operation is strictly NO_SEND_FILE_ONLY.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root


def write_delivery_status(status_payload: Mapping[str, Any], path: Path | None = None) -> Path:
    """Writes the delivery status payload to reports/runtime/delivery/delivery_status_latest.json."""
    root = get_repo_root()
    target = path or root / "reports/runtime/delivery/delivery_status_latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(status_payload, f, indent=2)
    return target


class DeliveryChannels:
    """Manages channel targets and outbox status."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.channels_cfg = self._load_cfg()

    def _load_cfg(self) -> dict[str, Any]:
        p = self.root / "config/openbagus_delivery_local.example.json"
        if p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "mode": "NO_SEND_FILE_ONLY",
            "channels": {
                "WA_02_AUTO_CRYPTO_DAILY": {"enabled": True, "type": "outbox_file"},
                "EMAIL_MACRO_DAILY": {"enabled": True, "type": "outbox_file"},
                "APP_ALERT": {"enabled": True, "type": "outbox_file"},
            }
        }
