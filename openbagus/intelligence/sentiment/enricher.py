"""Source-based news and sentiment notes for OpenBagus.

Never invents news or fills gaps with fake narratives. Explicit DATA GAP
when verified source is not available.
"""

from __future__ import annotations

from typing import Any, Mapping


ENGINE_VERSION = "openbagus.intelligence.sentiment.enricher.v1"


def _source_names(runtime: Mapping[str, Any]) -> list[str]:
    analysis = runtime.get("analysis", {}) or {}
    source_health = analysis.get("source_health_summary", {}) or {}
    sample = source_health.get("sample", []) if isinstance(source_health, Mapping) else []
    names = []
    for row in sample:
        name = row.get("source_name") or row.get("provider")
        if name:
            names.append(str(name))
    return names


def _asset_source(runtime: Mapping[str, Any], symbol: str) -> str | None:
    view = ((runtime.get("analysis", {}) or {}).get("asset_views", {}) or {}).get(symbol, {})
    data_quality = view.get("data_quality", {})
    source = data_quality.get("source_name") or data_quality.get("provider")
    return str(source) if source else None


def sentiment_note(runtime: Mapping[str, Any], symbol: str, domain: str = "crypto") -> dict[str, Any]:
    """Return source-based sentiment note without fabricating news."""
    source = _asset_source(runtime, symbol)
    source_names = _source_names(runtime)

    if domain == "crypto":
        market_sources = [name for name in source_names if any(key in name.lower() for key in ("binance", "coingecko", "defillama"))]
        if market_sources or source:
            return {
                "status": "LOW_CONFIDENCE_MARKET_SOURCE_ONLY",
                "text": (
                    "DATA GAP news; konteks harga/liq memakai source market publik "
                    f"{source or market_sources[0]}."
                ),
                "source_refs": [source] if source else market_sources[:3],
            }
        return {
            "status": "DATA_GAP",
            "text": "DATA GAP: news/sentiment crypto belum tersedia dari source valid.",
            "source_refs": [],
        }

    return {
        "status": "DATA_GAP",
        "text": f"DATA GAP: news/sentiment {domain} belum tersedia dari source valid.",
        "source_refs": [],
    }
