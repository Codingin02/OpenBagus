"""News intelligence and source registry package for OpenBagus."""

from __future__ import annotations

from openbagus.intelligence.news.registry import NewsSourceRegistry
from openbagus.intelligence.news.memory import NewsFreshnessMemory
from openbagus.intelligence.news.ranker import NewsDedupRanker
from openbagus.intelligence.news.runtime import NewsIntelligenceRuntime

__all__ = [
    "NewsSourceRegistry",
    "NewsFreshnessMemory",
    "NewsDedupRanker",
    "NewsIntelligenceRuntime",
]
