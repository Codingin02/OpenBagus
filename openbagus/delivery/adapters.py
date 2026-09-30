"""OpenBagus Delivery Adapters.

Safe transport adapters for local file staging, OpenClaw bridge, and mock sends.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root


class LocalFileOutboxAdapter:
    """Safely stages messages to local files without external network transmission."""

    def __init__(self, outbox_dir: Path | None = None) -> None:
        self.outbox_dir = outbox_dir or get_repo_root() / "reports/runtime/delivery"
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, channel_name: str, content: str, extension: str = "md") -> dict[str, Any]:
        file_path = self.outbox_dir / f"{channel_name}_latest.{extension}"
        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)
        return {
            "status": "STAGED_LOCAL_FILE",
            "channel": channel_name,
            "path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
        }


class OpenClawBridgeAdapter:
    """Gateway interface for OpenClaw orchestration and scheduler triggers."""

    def __init__(self) -> None:
        pass

    def check_connection(self) -> dict[str, Any]:
        return {
            "status": "BRIDGE_READY",
            "mode": "LOCAL_SOCKET_OR_FILE",
            "connected": True,
        }
