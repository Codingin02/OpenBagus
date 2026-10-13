"""Persistent session checkpoint store for conversational threads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openbagus.ai.memory.working_context import WorkingContext
from openbagus.intelligence.local_language import LOCAL_RUNTIME_DIR


class SessionStore:
    """Saves and restores versioned conversational session states."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self.dir = storage_dir or (LOCAL_RUNTIME_DIR / "sessions")
        self.dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, session_id: str) -> Path:
        clean_id = "".join(c for c in session_id if c.isalnum() or c in "-_") or "default"
        return self.dir / f"{clean_id}.json"

    def save(self, context: WorkingContext) -> None:
        p = self._file_path(context.session_id)
        data = context.to_dict()
        data["turns"] = context.turns  # full turns
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, session_id: str) -> WorkingContext:
        p = self._file_path(session_id)
        if not p.is_file():
            return WorkingContext(session_id=session_id)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return WorkingContext.from_dict(data)
        except Exception:
            return WorkingContext(session_id=session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for f in self.dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "active_ticker": data.get("active_ticker"),
                    "strategy": data.get("strategy"),
                    "turns_count": len(data.get("turns", [])),
                    "updated_at": data.get("updated_at", "-"),
                })
            except Exception:
                continue
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        p = self._file_path(session_id)
        if p.is_file():
            p.unlink()
            return True
        return False
