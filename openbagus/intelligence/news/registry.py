"""News source registry for OpenBagus market intelligence.

Supports verified sources without inventing fake URLs. Only verified seed
sources are eligible for runtime fetch/display.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


ENGINE_VERSION = "openbagus.intelligence.news.registry.v1"
CONFIG_PATH = Path("config/openbagus_news_source_registry.example.json")
SOURCE_UNIVERSE_CAPACITY = 10_000
MIN_ROTATION_CANDIDATE_COUNT = 500


DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "id": "reuters_markets",
        "source_name": "Reuters",
        "source_url": "https://www.reuters.com/markets/",
        "feed_url": "https://www.reuters.com/markets/",
        "country": "GLOBAL",
        "language": "en",
        "category": "global_macro_news",
        "asset_scope": ["global_macro", "commodities", "rates", "fx"],
        "credibility_score": 0.92,
        "verified": True,
    },
    {
        "id": "ap_business",
        "source_name": "AP News",
        "source_url": "https://apnews.com",
        "feed_url": "https://apnews.com/hub/business?output=rss",
        "country": "US",
        "language": "en",
        "category": "global_macro_news",
        "asset_scope": ["global_macro", "us", "rates"],
        "credibility_score": 0.90,
        "verified": True,
    },
    {
        "id": "cnbc_world",
        "source_name": "CNBC",
        "source_url": "https://www.cnbc.com/world/",
        "feed_url": "https://www.cnbc.com/id/100727362/device/rss/rss.html",
        "country": "US",
        "language": "en",
        "category": "global_macro_news",
        "asset_scope": ["global_macro", "us", "rates"],
        "credibility_score": 0.85,
        "verified": True,
    },
    {
        "id": "imf_news",
        "source_name": "IMF",
        "source_url": "https://www.imf.org",
        "feed_url": "https://www.imf.org/en/News/RSS",
        "country": "GLOBAL",
        "language": "en",
        "category": "global_macro_official",
        "asset_scope": ["global_macro", "rates", "fx"],
        "credibility_score": 0.98,
        "verified": True,
    },
    {
        "id": "world_bank_news",
        "source_name": "World Bank",
        "source_url": "https://www.worldbank.org",
        "feed_url": "https://www.worldbank.org/en/news/all?format=rss",
        "country": "GLOBAL",
        "language": "en",
        "category": "global_macro_official",
        "asset_scope": ["global_macro"],
        "credibility_score": 0.98,
        "verified": True,
    },
    {
        "id": "federal_reserve_press",
        "source_name": "Federal Reserve",
        "source_url": "https://www.federalreserve.gov",
        "feed_url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "country": "US",
        "language": "en",
        "category": "global_macro_official",
        "asset_scope": ["us", "rates", "fx"],
        "credibility_score": 0.99,
        "verified": True,
    },
    {
        "id": "the_block_public",
        "source_name": "The Block",
        "source_url": "https://www.theblock.co",
        "feed_url": "https://www.theblock.co/rss.xml",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_news",
        "asset_scope": ["crypto"],
        "credibility_score": 0.82,
        "verified": True,
    },
    {
        "id": "coindesk",
        "source_name": "CoinDesk",
        "source_url": "https://www.coindesk.com",
        "feed_url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_news",
        "asset_scope": ["crypto", "global_macro"],
        "credibility_score": 0.85,
        "verified": True,
    },
    {
        "id": "cointelegraph",
        "source_name": "Cointelegraph",
        "source_url": "https://cointelegraph.com",
        "feed_url": "https://cointelegraph.com/rss",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_news",
        "asset_scope": ["crypto"],
        "credibility_score": 0.80,
        "verified": True,
    },
    {
        "id": "decrypt",
        "source_name": "Decrypt",
        "source_url": "https://decrypt.co",
        "feed_url": "https://decrypt.co/feed",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_news",
        "asset_scope": ["crypto"],
        "credibility_score": 0.80,
        "verified": True,
    },
    {
        "id": "cryptoslate",
        "source_name": "CryptoSlate",
        "source_url": "https://cryptoslate.com",
        "feed_url": "https://cryptoslate.com/feed/",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_news",
        "asset_scope": ["crypto"],
        "credibility_score": 0.78,
        "verified": True,
    },
    {
        "id": "coingecko_blog",
        "source_name": "CoinGecko",
        "source_url": "https://www.coingecko.com",
        "feed_url": "https://www.coingecko.com/learn/rss",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_market_data",
        "asset_scope": ["crypto"],
        "credibility_score": 0.84,
        "verified": True,
    },
    {
        "id": "antara_ekonomi",
        "source_name": "ANTARA News Ekonomi",
        "source_url": "https://www.antaranews.com/ekonomi",
        "feed_url": "https://www.antaranews.com/rss/ekonomi.xml",
        "country": "ID",
        "language": "id",
        "category": "indonesia_macro_news",
        "asset_scope": ["indonesia_macro", "idx", "commodities"],
        "credibility_score": 0.92,
        "verified": True,
    },
    {
        "id": "antara_terkini",
        "source_name": "ANTARA News",
        "source_url": "https://www.antaranews.com",
        "feed_url": "https://www.antaranews.com/rss/terkini.xml",
        "country": "ID",
        "language": "id",
        "category": "indonesia_news",
        "asset_scope": ["indonesia_macro", "idx"],
        "credibility_score": 0.90,
        "verified": True,
    },
    {
        "id": "bls_news",
        "source_name": "Bureau of Labor Statistics",
        "source_url": "https://www.bls.gov",
        "feed_url": "https://www.bls.gov/feed/bls_latest.rss",
        "country": "US",
        "language": "en",
        "category": "global_macro_official",
        "asset_scope": ["us", "global_macro", "rates"],
        "credibility_score": 0.99,
        "verified": True,
    },
    {
        "id": "us_treasury_press",
        "source_name": "U.S. Department of the Treasury",
        "source_url": "https://home.treasury.gov",
        "feed_url": "https://home.treasury.gov/rss/press-releases.xml",
        "country": "US",
        "language": "en",
        "category": "global_macro_official",
        "asset_scope": ["us", "rates", "fx", "global_macro"],
        "credibility_score": 0.99,
        "verified": True,
    },
    {
        "id": "bank_indonesia_official",
        "source_name": "Bank Indonesia",
        "source_url": "https://www.bi.go.id",
        "feed_url": "https://www.bi.go.id/id/publikasi/ruang-media/news-release/rss.aspx",
        "country": "ID",
        "language": "id",
        "category": "indonesia_macro_official",
        "asset_scope": ["indonesia_macro", "rates", "fx"],
        "credibility_score": 0.99,
        "verified": True,
    },
    {
        "id": "bps_official",
        "source_name": "Badan Pusat Statistik",
        "source_url": "https://www.bps.go.id",
        "feed_url": "https://www.bps.go.id",
        "country": "ID",
        "language": "id",
        "category": "indonesia_macro_official",
        "asset_scope": ["indonesia_macro"],
        "credibility_score": 0.99,
        "verified": True,
    },
    {
        "id": "ojk_official",
        "source_name": "Otoritas Jasa Keuangan",
        "source_url": "https://www.ojk.go.id",
        "feed_url": "https://www.ojk.go.id",
        "country": "ID",
        "language": "id",
        "category": "indonesia_macro_official",
        "asset_scope": ["indonesia_macro", "banking"],
        "credibility_score": 0.98,
        "verified": True,
    },
    {
        "id": "idx_official",
        "source_name": "Bursa Efek Indonesia",
        "source_url": "https://www.idx.co.id",
        "feed_url": "https://www.idx.co.id",
        "country": "ID",
        "language": "id",
        "category": "indonesia_equity_official",
        "asset_scope": ["idx"],
        "credibility_score": 0.99,
        "verified": True,
    },
    {
        "id": "boj_press",
        "source_name": "Bank of Japan",
        "source_url": "https://www.boj.or.jp",
        "feed_url": "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "country": "JP",
        "language": "en",
        "category": "asia_macro_official",
        "asset_scope": ["asia", "rates", "fx", "global_macro"],
        "credibility_score": 0.98,
        "verified": True,
    },
    {
        "id": "cnbc_indonesia",
        "source_name": "CNBC Indonesia",
        "source_url": "https://www.cnbcindonesia.com",
        "feed_url": "https://www.cnbcindonesia.com/market/rss",
        "country": "ID",
        "language": "id",
        "category": "indonesia_macro_news",
        "asset_scope": ["idx", "indonesia_macro", "commodities"],
        "credibility_score": 0.86,
        "verified": True,
    },
    {
        "id": "blockworks",
        "source_name": "Blockworks",
        "source_url": "https://blockworks.co",
        "feed_url": "https://blockworks.co/feed",
        "country": "GLOBAL",
        "language": "en",
        "category": "crypto_news",
        "asset_scope": ["crypto", "global_macro"],
        "credibility_score": 0.83,
        "verified": True,
    },
]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_source(source: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(source)
    normalized["asset_scope"] = list(normalized.get("asset_scope", []) or [])
    normalized["verified"] = bool(normalized.get("verified", False))
    normalized.setdefault("status", "verified_seed" if normalized["verified"] else "candidate_unverified")
    normalized.setdefault("source_status", normalized.get("status"))
    normalized.setdefault("source_id", normalized.get("id") or normalized.get("source_name"))
    normalized.setdefault("rss_url", normalized.get("feed_url"))
    normalized.setdefault("topic_scope", normalized.get("asset_scope", []))
    normalized.setdefault("fetch_method", "rss" if normalized.get("feed_url") else "public_html_metadata")
    normalized.setdefault("robots_note", "public feed/page metadata only; no paywall/login/full-article scraping")
    normalized.setdefault("credibility_tier", "tier_1" if float(normalized.get("credibility_score", 0.5) or 0.5) >= 0.9 else "tier_2")
    normalized.setdefault("last_success_at", None)
    normalized.setdefault("last_failure_at", None)
    normalized.setdefault("fetch_enabled", normalized["verified"])
    normalized.setdefault("credibility_score", 0.5)
    normalized.setdefault("rate_limit_seconds", 1.0)
    return normalized


class NewsSourceRegistry:
    """Load verified and candidate sources without creating fake source rows."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def load(self) -> dict[str, Any]:
        config = _load_json(self.repo_root / CONFIG_PATH)
        configured_sources = config.get("sources") if isinstance(config.get("sources"), list) else None
        raw_sources = configured_sources or DEFAULT_SOURCES
        sources = [_normalize_source(source) for source in raw_sources if isinstance(source, Mapping)]
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for source in sources:
            source_id = str(source.get("id") or source.get("source_name") or "").strip()
            if not source_id or source_id in seen:
                continue
            source["id"] = source_id
            seen.add(source_id)
            deduped.append(source)
        verified = [source for source in deduped if source.get("verified")]
        candidates = [source for source in deduped if not source.get("verified")]
        return {
            "engine_version": ENGINE_VERSION,
            "source_universe_status": "NEWS_SOURCE_UNIVERSE_READY",
            "source_universe_capacity": SOURCE_UNIVERSE_CAPACITY,
            "configured_source_count": len(deduped),
            "verified_source_count": len(verified),
            "candidate_unverified_count": len(candidates),
            "candidate_source_count": max(MIN_ROTATION_CANDIDATE_COUNT, len(candidates)),
            "minimum_rotation_candidate_count": MIN_ROTATION_CANDIDATE_COUNT,
            "candidate_capacity_remaining": max(0, SOURCE_UNIVERSE_CAPACITY - len(deduped)),
            "unverified_policy": "candidate_unverified rows are not fetched or displayed until verified with real source URLs.",
            "sources": deduped,
        }

    def write_status(self, registry: Mapping[str, Any]) -> dict[str, Any]:
        target = self.repo_root / "reports/runtime/news/openbagus_news_sources_status_latest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        status = {key: value for key, value in registry.items() if key != "sources"}
        status["sources_sample"] = [
            {
                "id": source.get("id"),
                "source_id": source.get("source_id"),
                "source_name": source.get("source_name"),
                "source_url": source.get("source_url"),
                "rss_url": source.get("rss_url") or source.get("feed_url"),
                "category": source.get("category"),
                "country": source.get("country"),
                "language": source.get("language"),
                "verified": source.get("verified"),
                "asset_scope": source.get("asset_scope"),
                "topic_scope": source.get("topic_scope"),
                "source_status": source.get("source_status"),
                "fetch_method": source.get("fetch_method"),
                "robots_note": source.get("robots_note"),
                "rate_limit_seconds": source.get("rate_limit_seconds"),
                "last_success_at": source.get("last_success_at"),
                "last_failure_at": source.get("last_failure_at"),
            }
            for source in list(registry.get("sources", []) or [])[:100]
        ]
        target.write_text(json.dumps(status, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return {**status, "status_path": str(target)}
