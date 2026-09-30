"""Deterministic news deduplication and ranking for OpenBagus."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping


ENGINE_VERSION = "openbagus.intelligence.news.ranker.v1"

KEYWORDS_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "crypto": ("bitcoin", "btc", "ethereum", "eth", "solana", "crypto", "stablecoin", "token", "blockchain", "defi"),
    "global_macro": ("gdp", "inflation", "growth", "macro", "central bank", "recession", "global", "fed", "yield"),
    "us": ("fed", "federal reserve", "treasury", "us ", "america", "dollar"),
    "commodities": ("oil", "gold", "commodity", "commodities", "energy"),
    "rates": ("yield", "rate", "rates", "bond", "treasury"),
    "fx": ("fx", "currency", "dollar", "dxy"),
}


def canonical_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return text


def duplicate_group_id(title: str, source_name: str = "") -> str:
    canonical = canonical_text(title)
    if not canonical:
        canonical = canonical_text(source_name)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def freshness_score(published_at: Any, fetched_at: datetime | None = None) -> float:
    fetched = fetched_at or datetime.now(timezone.utc)
    published = parse_datetime(published_at)
    if not published:
        return 0.45
    age_hours = max(0.0, (fetched - published).total_seconds() / 3600.0)
    if age_hours <= 6:
        return 1.0
    if age_hours <= 24:
        return 0.88
    if age_hours <= 72:
        return 0.68
    if age_hours <= 168:
        return 0.48
    return 0.25


def infer_scopes(title: str, summary: str, source_scopes: list[str]) -> list[str]:
    text = f"{title} {summary}".lower()
    inferred = set(source_scopes or [])
    for scope, keywords in KEYWORDS_BY_SCOPE.items():
        if any(keyword in text for keyword in keywords):
            inferred.add(scope)
    return sorted(inferred or {"crypto", "global_macro"})


def relevance_score(item: Mapping[str, Any]) -> float:
    scopes = item.get("asset_scope", []) or []
    text = f"{item.get('title', '')} {item.get('summary_short', '')}".lower()
    hits = 0
    for scope in scopes:
        hits += sum(1 for keyword in KEYWORDS_BY_SCOPE.get(str(scope), ()) if keyword in text)
    base = 0.50 + min(0.35, hits * 0.05)
    if any(scope in {"crypto", "global_macro"} for scope in scopes):
        base += 0.1
    return max(0.0, min(1.0, base))


def deterministic_summary(title: str, snippet: str = "") -> str:
    text = re.sub(r"\s+", " ", (snippet or title or "DATA GAP").strip())
    if len(text) <= 220:
        return text
    cut = text[:220].rsplit(" ", 1)[0].strip()
    return cut + "..."


def dedup_and_rank(items: list[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    best_by_group: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for item in items:
        group = str(item.get("duplicate_group_id") or duplicate_group_id(str(item.get("title", "")), str(item.get("source_name", ""))))
        item["duplicate_group_id"] = group
        item["freshness_score"] = round(float(item.get("freshness_score", freshness_score(item.get("published_at"), now))), 4)
        item["credibility_score"] = round(float(item.get("credibility_score", 0.5) or 0.5), 4)
        item["relevance_score"] = round(float(item.get("relevance_score", relevance_score(item))), 4)
        item["_rank_score"] = round(item["freshness_score"] * 0.35 + item["credibility_score"] * 0.35 + item["relevance_score"] * 0.30, 4)
        previous = best_by_group.get(group)
        if previous is None or item["_rank_score"] > previous.get("_rank_score", 0):
            best_by_group[group] = item
    ranked = sorted(best_by_group.values(), key=lambda row: row.get("_rank_score", 0), reverse=True)
    for item in ranked:
        item.pop("_rank_score", None)
    return ranked[:limit]


class NewsDedupRanker:
    """Wrapper class for news deduplication and ranking."""

    def __init__(self, limit: int = 120) -> None:
        self.limit = limit

    def rank(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return dedup_and_rank(items, self.limit)

    @classmethod
    def dedup_and_rank(cls, items: list[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
        return dedup_and_rank(items, limit)
