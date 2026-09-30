"""OpenBagus canonical data structures and output contracts.

Research-only output contracts and normalization of legacy signals into
quantitative research terminology (conviction score, actionability score,
portfolio stance, invalidation level, evidence stack).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "openbagus.contract.v1"

APPROVED_OUTPUT_TYPES: tuple[str, ...] = (
    "research_view",
    "trade_setup_review",
    "portfolio_stance",
    "conviction_score",
    "actionability_score",
    "market_intelligence_brief",
    "entry_zone_review",
    "target_zone_review",
    "invalidation_level",
    "scenario_probability",
    "evidence_stack",
)

ALLOWED_PORTFOLIO_STANCES: tuple[str, ...] = (
    "Accumulate-on-weakness",
    "Hold",
    "Reduce",
    "Trim Review",
    "Avoid",
    "Watchlist",
    "Long Bias",
    "Exit Review",
)

LEGACY_OUTPUT_ALIASES: dict[str, str] = {
    "signal": "research_view",
    "daily_signal": "research_view",
    "market_signal": "research_view",
    "trade_signal": "trade_setup_review",
    "buy_signal": "trade_setup_review",
    "sell_signal": "trade_setup_review",
    "recommendation": "portfolio_stance",
    "decision": "portfolio_stance",
    "confidence": "conviction_score",
    "confidence_level": "conviction_score",
    "action_score": "actionability_score",
    "brief": "market_intelligence_brief",
    "entry_zone": "entry_zone_review",
    "target_zone": "target_zone_review",
    "stop_loss": "invalidation_level",
}

BLOCKED_ABSOLUTE_PHRASES: tuple[str, ...] = (
    "BELI SEKARANG",
    "JUAL SEKARANG",
    "PASTI NAIK",
    "PASTI TURUN",
    "AUTO PROFIT",
    "GUARANTEED PROFIT",
    "EXECUTE BROKER ORDER",
)

DISCLAIMER_TEXT = (
    "Research View / Educational Only. Tidak ada rekomendasi beli/jual langsung. "
    "Validasi data, likuiditas, dan rencana risiko sebelum pengambilan keputusan."
)


def normalize_terminology(raw_key: str) -> str:
    cleaned = raw_key.strip().lower()
    return LEGACY_OUTPUT_ALIASES.get(cleaned, raw_key)


def build_research_contract(
    *,
    symbol: str,
    asset_class: str,
    portfolio_stance: str,
    conviction_score: int,
    actionability_score: int,
    invalidation_level: float | None,
    target_zone: list[float] | None,
    summary: str,
    evidence_stack: list[dict[str, Any]],
    risk_notes: list[str],
    data_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "asset_class": asset_class,
        "as_of_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "portfolio_stance": portfolio_stance if portfolio_stance in ALLOWED_PORTFOLIO_STANCES else "Watchlist",
        "conviction_score": max(0, min(100, conviction_score)),
        "actionability_score": max(0, min(100, actionability_score)),
        "invalidation_level": invalidation_level,
        "target_zone": target_zone,
        "summary": summary,
        "evidence_stack": evidence_stack,
        "risk_notes": risk_notes,
        "data_quality": dict(data_quality) if data_quality else {},
        "safety_disclaimer": DISCLAIMER_TEXT,
    }
