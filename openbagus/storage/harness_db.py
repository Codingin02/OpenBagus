"""OpenBagus Unlimited Local Harness Storage.

Provides durable, disk-backed conversation persistence via SQLite.
Decouples unbounded long-term local storage from bounded in-memory LLM context.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from openbagus.intelligence.local_language import get_local_appdata_dir


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


class HarnessStorage:
    """SQLite-backed conversation archive for OpenBagus multi-turn interactions."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is not None:
            self.db_path = db_path
        else:
            self.db_path = get_local_appdata_dir() / "harness" / "harness_history.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    asset TEXT,
                    market TEXT,
                    timeframe TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    asset TEXT,
                    market TEXT,
                    intent TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_harness_turns_session_time ON turns(session_id, created_at);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_harness_turns_created_at ON turns(created_at);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_harness_turns_asset ON turns(asset);"
            )

    def save_turn(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        asset: str | None = None,
        market: str | None = None,
        intent: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> int:
        now_iso = timestamp or datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {})
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO turns (session_id, created_at, user_text, assistant_text, asset, market, intent, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (session_id, now_iso, user_text, assistant_text, asset, market, intent, meta_str),
            )
            turn_id = cur.lastrowid or 0
            cur.execute(
                """
                INSERT INTO sessions (session_id, created_at, last_active_at, asset, market, timeframe, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_active_at=excluded.last_active_at,
                    asset=COALESCE(excluded.asset, sessions.asset),
                    market=COALESCE(excluded.market, sessions.market);
                """,
                (session_id, now_iso, now_iso, asset, market, None, meta_str),
            )
            return turn_id

    def save_session_meta(
        self,
        session_id: str,
        asset: str | None = None,
        market: str | None = None,
        timeframe: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {})
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, created_at, last_active_at, asset, market, timeframe, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_active_at=excluded.last_active_at,
                    asset=COALESCE(excluded.asset, sessions.asset),
                    market=COALESCE(excluded.market, sessions.market),
                    timeframe=COALESCE(excluded.timeframe, sessions.timeframe),
                    metadata_json=excluded.metadata_json;
                """,
                (session_id, now_iso, now_iso, asset, market, timeframe, meta_str),
            )

    def get_recent_turns(
        self, session_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            if session_id:
                cur = conn.execute(
                    """
                    SELECT id, session_id, created_at, user_text, assistant_text, asset, market, intent, metadata_json
                    FROM turns
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    (session_id, limit),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, session_id, created_at, user_text, assistant_text, asset, market, intent, metadata_json
                    FROM turns
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
            result = []
            for r in reversed(rows):
                result.append({
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "at": r["created_at"],
                    "user": r["user_text"],
                    "assistant": r["assistant_text"],
                    "asset": r["asset"],
                    "market": r["market"],
                    "intent": r["intent"],
                })
            return result

    def get_history(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute(
                """
                SELECT id, session_id, created_at, user_text, assistant_text, asset, market, intent
                FROM turns
                ORDER BY id DESC
                LIMIT ? OFFSET ?;
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "at": r["created_at"],
                    "user": r["user_text"],
                    "assistant": r["assistant_text"],
                    "asset": r["asset"],
                    "market": r["market"],
                    "intent": r["intent"],
                }
                for r in rows
            ]

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        q = f"%{query.strip().lower()}%"
        with self._connection() as conn:
            cur = conn.execute(
                """
                SELECT id, session_id, created_at, user_text, assistant_text, asset, market, intent
                FROM turns
                WHERE lower(user_text) LIKE ?
                   OR lower(assistant_text) LIKE ?
                   OR lower(COALESCE(asset, '')) LIKE ?
                   OR lower(COALESCE(intent, '')) LIKE ?
                ORDER BY id DESC
                LIMIT ?;
                """,
                (q, q, q, q, limit),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "at": r["created_at"],
                    "user": r["user_text"],
                    "assistant": r["assistant_text"],
                    "asset": r["asset"],
                    "market": r["market"],
                    "intent": r["intent"],
                }
                for r in rows
            ]

    def get_stats(self) -> dict[str, Any]:
        size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        with self._connection() as conn:
            t_row = conn.execute("SELECT COUNT(*) as c, MIN(created_at) as oldest, MAX(created_at) as newest FROM turns;").fetchone()
            s_row = conn.execute("SELECT COUNT(*) as c FROM sessions;").fetchone()
            total_turns = t_row["c"] if t_row else 0
            oldest = t_row["oldest"] if t_row else None
            newest = t_row["newest"] if t_row else None
            total_sessions = s_row["c"] if s_row else 0
        return {
            "total_turns": total_turns,
            "total_sessions": total_sessions,
            "db_size_bytes": size_bytes,
            "db_size_str": _format_size(size_bytes),
            "oldest_turn_at": oldest,
            "newest_turn_at": newest,
            "db_path": str(self.db_path),
        }

    def migrate_from_json(self, json_path: Path | None = None) -> int:
        target = json_path or (self.db_path.parent / "session_context.json")
        if not target.exists():
            return 0
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return 0
        turns = data.get("conversational_turns", [])
        if not isinstance(turns, list) or not turns:
            return 0

        inserted = 0
        with self._connection() as conn:
            for t in turns:
                user_text = t.get("user", "")
                assistant_text = t.get("assistant", "")
                at = t.get("at", datetime.now(timezone.utc).isoformat())
                if not user_text and not assistant_text:
                    continue
                cur = conn.execute(
                    "SELECT 1 FROM turns WHERE created_at = ? AND user_text = ? LIMIT 1;",
                    (at, user_text[:1000]),
                )
                if not cur.fetchone():
                    conn.execute(
                        """
                        INSERT INTO turns (session_id, created_at, user_text, assistant_text, asset, market, intent, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            "migrated_legacy",
                            at,
                            user_text,
                            assistant_text,
                            data.get("last_asset"),
                            data.get("market_type"),
                            data.get("last_intent"),
                            json.dumps({"source": "json_migration"}),
                        ),
                    )
                    inserted += 1
        return inserted

    def clear(self, all_history: bool = True, session_id: str | None = None) -> None:
        with self._connection() as conn:
            if all_history:
                conn.execute("DELETE FROM turns;")
                conn.execute("DELETE FROM sessions;")
            elif session_id:
                conn.execute("DELETE FROM turns WHERE session_id = ?;", (session_id,))
                conn.execute("DELETE FROM sessions WHERE session_id = ?;", (session_id,))
            conn.execute("VACUUM;")
