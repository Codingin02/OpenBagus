"""Freshness memory for news selection in OpenBagus.

Prevents the same headline/link from being repeated in the same report family
within a retention window. Stores only fingerprints and sanitized metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


ENGINE_VERSION = "openbagus.intelligence.news.memory.v1"
NEWS_DIR = Path("reports/runtime/news")
MEMORY_PATH = NEWS_DIR / "news_freshness_memory_latest.json"
SELECTION_PATH = NEWS_DIR / "email_news_selection_latest.json"
BLOCKED_PATH = NEWS_DIR / "repeated_news_blocked_latest.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _canonical(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = re.sub(r"[^a-z0-9:/._ -]+", "", text)
    return text


def fingerprint(item: Mapping[str, Any], report_type: str) -> str:
    base = "|".join(
        [
            _canonical(report_type),
            _canonical(item.get("title")),
            _canonical(item.get("article_url")),
            _canonical(item.get("source_name")),
            _canonical(item.get("published_at")),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:24]


class NewsFreshnessMemory:
    """Select fresh, non-repeated news for reports."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def select_for_report(
        self,
        *,
        report_type: str,
        items: list[Mapping[str, Any]],
        scopes: set[str],
        retention_hours: int,
        limit: int,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        memory = self._load_memory()
        seen = memory.setdefault("seen", {})
        cutoff = now - timedelta(hours=retention_hours)
        selected: list[Mapping[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        ranked = sorted(
            items,
            key=lambda item: (
                float(item.get("freshness_score") or 0),
                float(item.get("credibility_score") or 0),
                float(item.get("relevance_score") or 0),
            ),
            reverse=True,
        )
        for item in ranked:
            item_scopes = {str(scope).lower() for scope in item.get("asset_scope", []) or []}
            if scopes and not scopes.intersection(item_scopes):
                continue
            fp = fingerprint(item, report_type)
            previous = seen.get(fp, {})
            previous_at = _parse(previous.get("last_used_at")) if isinstance(previous, Mapping) else None
            if previous_at and previous_at >= cutoff:
                blocked.append(
                    {
                        "fingerprint": fp,
                        "title": str(item.get("title", ""))[:220],
                        "source_name": item.get("source_name"),
                        "article_url": item.get("article_url"),
                        "last_used_at": previous.get("last_used_at"),
                        "report_type": report_type,
                    }
                )
                continue
            selected.append(item)
            if commit:
                seen[fp] = {
                    "last_used_at": _iso_now(),
                    "report_type": report_type,
                    "source_name": item.get("source_name"),
                    "article_url": item.get("article_url"),
                    "title": str(item.get("title", ""))[:220],
                }
            if len(selected) >= limit:
                break

        memory.update(
            {
                "engine_version": ENGINE_VERSION,
                "generated_at_utc": _iso_now(),
                "retention_policy": "daily=72h, weekly=14d by report_type",
                "stored_value_type": "fingerprints_and_sanitized_metadata_only",
            }
        )
        if commit:
            self._write_json(self.repo_root / MEMORY_PATH, memory)
        selection_payload = {
            "engine_version": ENGINE_VERSION,
            "generated_at_utc": _iso_now(),
            "report_type": report_type,
            "retention_hours": retention_hours,
            "selected_news_count": len(selected),
            "repeated_news_blocked_count": len(blocked),
            "selected": [
                {
                    "title": item.get("title"),
                    "source_name": item.get("source_name"),
                    "article_url": item.get("article_url"),
                    "published_at": item.get("published_at"),
                    "freshness_score": item.get("freshness_score"),
                    "credibility_score": item.get("credibility_score"),
                }
                for item in selected
            ],
        }
        blocked_payload = {
            "engine_version": ENGINE_VERSION,
            "generated_at_utc": _iso_now(),
            "report_type": report_type,
            "repeated_news_blocked_count": len(blocked),
            "blocked": blocked[:200],
        }
        self._write_json(self.repo_root / SELECTION_PATH, selection_payload)
        self._write_json(self.repo_root / BLOCKED_PATH, blocked_payload)
        return {
            "status": "NEWS_FRESHNESS_SELECTION_READY",
            "selected": list(selected),
            "blocked": blocked,
            "selected_news_count": len(selected),
            "repeated_news_blocked_count": len(blocked),
            "memory_path": str(self.repo_root / MEMORY_PATH),
            "selection_path": str(self.repo_root / SELECTION_PATH),
            "blocked_path": str(self.repo_root / BLOCKED_PATH),
        }

    def _load_memory(self) -> dict[str, Any]:
        path = self.repo_root / MEMORY_PATH
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"seen": {}}

    @staticmethod
    def _write_json(path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
