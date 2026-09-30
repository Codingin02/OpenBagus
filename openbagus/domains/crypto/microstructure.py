"""Crypto microstructure analysis from runtime rows.

Evaluates:
- Spot liquidity regime
- Funding rate status
- Open interest status
- Stablecoin liquidity proxy
- Order book / market depth regime
"""

from __future__ import annotations

from typing import Any, Mapping


ENGINE_VERSION = "openbagus.domains.crypto.microstructure.v1"


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


def _round(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _stablecoin_proxy(macro_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    for row in macro_rows:
        if row.get("indicator_code") == "stablecoins_circulating_usd":
            return {
                "status": "DATA_AVAILABLE",
                "value": _round(_to_float(row.get("value")), 2),
                "source_name": row.get("source_name"),
                "freshness_status": row.get("freshness_status"),
            }
    return {
        "status": "SOURCE_NOT_AVAILABLE",
        "reason": "DefiLlama stablecoin row is absent from the latest runtime snapshot.",
    }


def analyze_crypto_microstructure(
    symbol: str,
    market_row: Mapping[str, Any] | None,
    macro_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if market_row is None:
        return {
            "engine_version": ENGINE_VERSION,
            "symbol": symbol,
            "status": "SOURCE_NOT_AVAILABLE",
            "reason": "No runtime crypto market row was available.",
        }

    extra = market_row.get("extra") or {}
    volume = _to_float(market_row.get("volume"))
    price_change_pct = _to_float(extra.get("price_change_percent"))
    stablecoin = _stablecoin_proxy(macro_rows)

    if volume is None:
        liquidity_regime = "DATA_NOT_ENOUGH"
    elif price_change_pct is not None and abs(price_change_pct) > 4.0:
        liquidity_regime = "high_movement_check_depth_before_action"
    elif volume > 0:
        liquidity_regime = "spot_liquidity_observed"
    else:
        liquidity_regime = "thin_or_missing_volume"

    return {
        "engine_version": ENGINE_VERSION,
        "symbol": symbol,
        "status": "OK" if market_row.get("freshness_status") != "STALE" else "STALE_DATA_BLOCKED",
        "funding_rate": {"status": "SOURCE_NOT_AVAILABLE", "value": None},
        "open_interest": {"status": "SOURCE_NOT_AVAILABLE", "value": None},
        "btc_dominance": {"status": "SOURCE_NOT_AVAILABLE", "value": None},
        "stablecoin_liquidity_proxy": stablecoin,
        "order_book_heatmap": {
            "status": "SOURCE_NOT_AVAILABLE",
            "reason": "No legal/free order book or heatmap row is present in the runtime snapshot.",
        },
        "liquidity_regime": liquidity_regime,
        "crypto_microstructure_summary": (
            "Spot market row is available; derivatives and order book context remain source-limited."
            if market_row.get("freshness_status") != "STALE"
            else "Crypto market row is stale and cannot support full microstructure analysis."
        ),
        "observed_volume": _round(volume, 4),
        "price_change_percent": _round(price_change_pct, 6),
        "source_freshness": market_row.get("freshness_status"),
    }


def funding_rate_pressure(funding_rate: float | None) -> str:
    """Classifies perpetual funding rate pressure."""
    if funding_rate is None:
        return "NEUTRAL_OR_UNAVAILABLE"
    if funding_rate > 0.0003:
        return "LONG_CROWDED_OVERHEATED"
    if funding_rate < -0.0001:
        return "SHORT_CROWDED_SQUEEZE_RISK"
    return "BALANCED"


def orderbook_imbalance_proxy(bid_vol: float | None, ask_vol: float | None) -> dict[str, Any]:
    """Computes orderbook depth imbalance ratio."""
    if bid_vol is None or ask_vol is None or (bid_vol + ask_vol) <= 0:
        return {"status": "UNAVAILABLE", "imbalance_ratio": 0.0}
    ratio = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    return {"status": "OK", "imbalance_ratio": round(ratio, 4)}


def liquidation_cluster_estimate(price: float | None, atr: float | None) -> dict[str, Any]:
    """Estimates proximity to high-leverage liquidation clusters."""
    if price is None or atr is None:
        return {"status": "UNAVAILABLE", "upper_cluster": None, "lower_cluster": None}
    return {
        "status": "ESTIMATED",
        "upper_cluster": round(price + (atr * 2.0), 2),
        "lower_cluster": round(price - (atr * 2.0), 2),
    }
