"""Scenario thesis engine driven by runtime market and macro data.

Builds multi-scenario probabilities (bear, base, bull, optimistic) and
explanatory macro overlays.
"""

from __future__ import annotations

from typing import Any, Mapping


ENGINE_VERSION = "openbagus.intelligence.macro.scenario.v1"
SCENARIOS = ("bear", "base", "bull", "optimistic")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _normalize_probabilities(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(value, 0.0) for value in weights.values())
    if total <= 0:
        return {name: 0.0 for name in weights}
    return {name: round(max(value, 0.0) / total, 4) for name, value in weights.items()}


def fundamental_availability() -> dict[str, Any]:
    missing_fields = [
        "eps",
        "revenue",
        "valuation_multiple",
        "roe",
        "der",
        "dividend",
        "corporate_action",
    ]
    return {
        "status": "DATA_MISSING",
        "available_fields": [],
        "missing_fields": missing_fields,
        "note": "Runtime snapshot does not contain issuer fundamentals yet; no dummy assumptions were created.",
    }


def build_macro_overlay(macro_views: Mapping[str, Any], country_overlays: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "global": macro_views.get("GLOBAL", {"status": "SOURCE_NOT_AVAILABLE"}),
        "us": country_overlays.get("US", {"status": "SOURCE_NOT_AVAILABLE"}),
        "china": country_overlays.get("CN", country_overlays.get("China", {"status": "SOURCE_NOT_AVAILABLE"})),
        "japan": country_overlays.get("JP", country_overlays.get("Japan", {"status": "SOURCE_NOT_AVAILABLE"})),
        "russia": country_overlays.get("RU", country_overlays.get("Russia", {"status": "SOURCE_NOT_AVAILABLE"})),
    }


def build_scenario_thesis(
    *,
    symbol: str,
    market_row: Mapping[str, Any] | None,
    analysis_status: str,
    market_structure: Mapping[str, Any],
    risk_metrics: Mapping[str, Any],
    macro_overlay: Mapping[str, Any],
) -> dict[str, Any]:
    price = _to_float((market_row or {}).get("price"))
    fundamentals = fundamental_availability()

    if analysis_status == "STALE_DATA_BLOCKED" or price is None:
        return {
            "engine_version": ENGINE_VERSION,
            "symbol": symbol,
            "status": analysis_status,
            "scenario_probability": {name: None for name in SCENARIOS},
            "scenarios": {
                name: {
                    "probability": None,
                    "thesis_summary": "Blocked until fresh runtime market data is available.",
                    "target_zone": None,
                    "valuation_assumptions": {"status": "DATA_MISSING"},
                }
                for name in SCENARIOS
            },
            "fundamental_context": fundamentals,
            "macro_overlay": macro_overlay,
            "catalysts": [],
            "risk_factors": ["Fresh market data is required before scenario analysis can be used."],
        }

    support_resistance = market_structure.get("support_resistance", {})
    support = _to_float(support_resistance.get("support")) or price * 0.97
    resistance = _to_float(support_resistance.get("resistance")) or price * 1.03
    range_position = _to_float(support_resistance.get("range_position")) or 0.5
    latest_return = _to_float(risk_metrics.get("latest_bar_return")) or 0.0

    weights = {"bear": 0.24, "base": 0.46, "bull": 0.22, "optimistic": 0.08}
    if range_position > 0.65 and latest_return >= 0:
        weights["bull"] += 0.05
        weights["optimistic"] += 0.02
        weights["bear"] -= 0.04
    elif range_position < 0.35 or latest_return < 0:
        weights["bear"] += 0.06
        weights["bull"] -= 0.03
        weights["optimistic"] -= 0.02
    if risk_metrics.get("status") != "OK":
        weights["base"] += 0.04
        weights["optimistic"] -= 0.02

    probabilities = _normalize_probabilities(weights)
    target_padding = max((resistance - support) * 0.20, price * 0.01)

    scenario_defs = {
        "bear": {
            "target_zone": [_round(max(support - target_padding, 0.0)), _round(support)],
            "thesis_summary": "Downside scenario if price loses current support approximation and macro risk worsens.",
        },
        "base": {
            "target_zone": [_round(support), _round(resistance)],
            "thesis_summary": "Range scenario using the latest observed support and resistance approximation.",
        },
        "bull": {
            "target_zone": [_round(resistance), _round(resistance + target_padding)],
            "thesis_summary": "Constructive scenario if price accepts above current resistance with fresh supporting data.",
        },
        "optimistic": {
            "target_zone": [_round(resistance + target_padding), _round(resistance + 2.0 * target_padding)],
            "thesis_summary": "Optimistic scenario requiring follow-through and stronger market breadth or liquidity confirmation.",
        },
    }

    return {
        "engine_version": ENGINE_VERSION,
        "symbol": symbol,
        "status": "OK" if analysis_status == "OK" else "DEGRADED_ANALYSIS",
        "scenario_probability": probabilities,
        "scenarios": {
            name: {
                "probability": probabilities[name],
                "thesis_summary": scenario_defs[name]["thesis_summary"],
                "target_zone": scenario_defs[name]["target_zone"],
                "valuation_assumptions": {
                    "eps": "DATA_MISSING",
                    "revenue": "DATA_MISSING",
                    "multiple": "DATA_MISSING",
                    "status": "DATA_MISSING",
                },
            }
            for name in SCENARIOS
        },
        "fundamental_context": fundamentals,
        "macro_overlay": macro_overlay,
        "catalysts": [
            "Freshness-confirmed price acceptance above VWAP/pivot zone.",
            "Macro proxy improvement if official or market proxy data is available.",
        ],
        "risk_factors": [
            "Freshness degradation can invalidate the view.",
            "Fundamental fields are not yet available in the runtime snapshot.",
        ],
    }
