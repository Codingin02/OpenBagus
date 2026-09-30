"""Market structure analysis over runtime market rows.

Computes:
- Typical price, VWAP, Anchored VWAP
- Volume profile: POC, VAH, VAL, HVN, LVN
- Support & Resistance, Pivot points
- Breakout / fakeout / liquidity sweep
- Supply & Demand approximation / order block candidates
"""

from __future__ import annotations

from typing import Any, Mapping


ENGINE_VERSION = "openbagus.core.market_structure.v1"


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


def _row_to_bar(row: Mapping[str, Any]) -> dict[str, Any] | None:
    close = _to_float(row.get("price"))
    open_price = _to_float(row.get("open"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    volume = _to_float(row.get("volume"))
    timestamp = row.get("observed_at_utc")

    if close is None or high is None or low is None or timestamp is None:
        return None
    if open_price is None:
        open_price = close
    if volume is None:
        volume = 0.0
    if high < low:
        return None
    if close <= 0 or open_price <= 0:
        return None

    return {
        "timestamp": str(timestamp),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": max(volume, 0.0),
    }


def _typical_price(bar: Mapping[str, Any]) -> float:
    return (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0


def _volume_profile(bars: list[dict[str, Any]], bin_count: int = 12) -> dict[str, Any]:
    low_price = min(float(bar["low"]) for bar in bars)
    high_price = max(float(bar["high"]) for bar in bars)
    if high_price <= low_price:
        high_price = low_price + max(abs(low_price) * 0.001, 1.0)

    bin_count = max(4, min(bin_count, 24))
    bin_size = (high_price - low_price) / bin_count
    buckets = []
    for index in range(bin_count):
        bucket_low = low_price + index * bin_size
        bucket_high = bucket_low + bin_size
        buckets.append(
            {
                "low": bucket_low,
                "high": bucket_high,
                "mid": (bucket_low + bucket_high) / 2.0,
                "volume": 0.0,
            }
        )

    for bar in bars:
        price = _typical_price(bar)
        bucket_index = int((price - low_price) / bin_size) if bin_size else 0
        bucket_index = max(0, min(bin_count - 1, bucket_index))
        buckets[bucket_index]["volume"] += float(bar["volume"])

    total_volume = sum(bucket["volume"] for bucket in buckets)
    sorted_by_volume = sorted(buckets, key=lambda item: item["volume"], reverse=True)
    poc_bucket = sorted_by_volume[0]

    selected = []
    selected_volume = 0.0
    for bucket in sorted_by_volume:
        selected.append(bucket)
        selected_volume += bucket["volume"]
        if total_volume <= 0 or selected_volume >= total_volume * 0.70:
            break

    vah = max(bucket["high"] for bucket in selected)
    val = min(bucket["low"] for bucket in selected)
    hvn = [bucket["mid"] for bucket in sorted_by_volume[: min(3, len(sorted_by_volume))]]
    lvn = [bucket["mid"] for bucket in sorted(buckets, key=lambda item: item["volume"])[: min(3, len(buckets))]]

    return {
        "bin_count": bin_count,
        "poc": _round(poc_bucket["mid"]),
        "vah": _round(vah),
        "val": _round(val),
        "hvn": [_round(value) for value in hvn],
        "lvn": [_round(value) for value in lvn],
        "total_profile_volume": _round(total_volume),
        "method": "typical_price_volume_bucket",
    }


def _vwap(bars: list[dict[str, Any]]) -> float | None:
    total_pv = sum(_typical_price(bar) * float(bar["volume"]) for bar in bars)
    total_volume = sum(float(bar["volume"]) for bar in bars)
    if total_volume <= 0:
        return _typical_price(bars[-1])
    return total_pv / total_volume


def _anchored_vwap(bars: list[dict[str, Any]]) -> dict[str, Any]:
    anchor_index = 0
    if len(bars) > 1:
        anchor_index = min(range(len(bars)), key=lambda index: float(bars[index]["low"]))
    anchored = bars[anchor_index:]
    return {
        "anchor_timestamp": anchored[0]["timestamp"],
        "anchor_reason": "lowest_available_bar",
        "anchored_vwap": _round(_vwap(anchored)),
    }


def _classic_pivots(bar: Mapping[str, Any]) -> dict[str, float | None]:
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    pivot = (high + low + close) / 3.0
    return {
        "pivot": _round(pivot),
        "r1": _round((2.0 * pivot) - low),
        "s1": _round((2.0 * pivot) - high),
        "r2": _round(pivot + (high - low)),
        "s2": _round(pivot - (high - low)),
    }


def _breakout_context(bars: list[dict[str, Any]]) -> dict[str, Any]:
    latest = bars[-1]
    if len(bars) < 2:
        return {
            "breakout_status": "DATA_NOT_ENOUGH",
            "fakeout_status": "DATA_NOT_ENOUGH",
            "liquidity_sweep": "DATA_NOT_ENOUGH",
        }

    prior_high = max(float(bar["high"]) for bar in bars[:-1])
    prior_low = min(float(bar["low"]) for bar in bars[:-1])
    close = float(latest["close"])
    high = float(latest["high"])
    low = float(latest["low"])

    breakout_status = "no_confirmed_breakout"
    if close > prior_high:
        breakout_status = "upside_breakout_confirmed"
    elif close < prior_low:
        breakout_status = "downside_breakout_confirmed"

    fakeout_status = "no_basic_fakeout"
    if high > prior_high and close <= prior_high:
        fakeout_status = "upside_fakeout_candidate"
    elif low < prior_low and close >= prior_low:
        fakeout_status = "downside_fakeout_candidate"

    liquidity_sweep = "no_basic_sweep"
    if low < prior_low and close > prior_low:
        liquidity_sweep = "sell_side_liquidity_sweep_candidate"
    elif high > prior_high and close < prior_high:
        liquidity_sweep = "buy_side_liquidity_sweep_candidate"

    return {
        "prior_high": _round(prior_high),
        "prior_low": _round(prior_low),
        "breakout_status": breakout_status,
        "fakeout_status": fakeout_status,
        "liquidity_sweep": liquidity_sweep,
    }


def _supply_demand(latest: Mapping[str, Any], pivots: Mapping[str, Any]) -> dict[str, Any]:
    open_price = float(latest["open"])
    close = float(latest["close"])
    high = float(latest["high"])
    low = float(latest["low"])
    pivot = float(pivots["pivot"])
    bullish = close >= open_price

    if bullish:
        demand_zone = {"low": _round(low), "high": _round(min(open_price, pivot))}
        supply_zone = {"low": _round(max(close, pivot)), "high": _round(high)}
        order_block = "daily_bullish_order_block_candidate"
    else:
        demand_zone = {"low": _round(low), "high": _round(min(close, pivot))}
        supply_zone = {"low": _round(max(open_price, pivot)), "high": _round(high)}
        order_block = "daily_bearish_order_block_candidate"

    return {
        "demand_zone": demand_zone,
        "supply_zone": supply_zone,
        "order_block_basic": order_block,
        "method": "daily_ohlc_body_and_wick_approximation",
    }


def analyze_market_structure(market_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    bars = []
    for row in market_rows:
        bar = _row_to_bar(row)
        if bar:
            bars.append(bar)

    if not bars:
        return {
            "engine_version": ENGINE_VERSION,
            "status": "DATA_NOT_ENOUGH",
            "calculation_scope": "none",
            "reason": "No usable OHLCV rows were available from runtime ingestion.",
        }

    bars = sorted(bars, key=lambda item: item["timestamp"])
    latest = bars[-1]
    data_mode = "DAILY_APPROXIMATION" if len(bars) < 5 else "MULTI_BAR_ANALYSIS"
    pivots = _classic_pivots(latest)
    volume_profile = _volume_profile(bars)
    close = float(latest["close"])
    low = float(latest["low"])
    high = float(latest["high"])
    range_width = max(high - low, 0.0)
    range_position = ((close - low) / range_width) if range_width else 0.5

    return {
        "engine_version": ENGINE_VERSION,
        "status": "OK" if data_mode == "MULTI_BAR_ANALYSIS" else "DAILY_APPROXIMATION",
        "calculation_scope": data_mode,
        "bar_count": len(bars),
        "latest_timestamp": latest["timestamp"],
        "vwap": _round(_vwap(bars)),
        "anchored_vwap": _anchored_vwap(bars),
        "volume_profile_basic": volume_profile,
        "poc": volume_profile["poc"],
        "vah": volume_profile["vah"],
        "val": volume_profile["val"],
        "hvn": volume_profile["hvn"],
        "lvn": volume_profile["lvn"],
        "support_resistance": {
            "support": _round(low),
            "resistance": _round(high),
            "latest_close": _round(close),
            "range_position": _round(range_position),
        },
        "pivot": pivots,
        "breakout_fakeout_liquidity": _breakout_context(bars),
        "supply_demand_order_block_basic": _supply_demand(latest, pivots),
        "note": "Computed from runtime OHLCV rows only; daily approximation is used when intraday bars are unavailable.",
    }


def calculate_vwap(prices: list[float], volumes: list[float]) -> float | None:
    """Calculate Volume-Weighted Average Price from price and volume series."""
    if not prices or not volumes or len(prices) != len(volumes):
        return None
    tot_vol = sum(volumes)
    if tot_vol <= 0:
        return sum(prices) / len(prices)
    return sum(p * v for p, v in zip(prices, volumes)) / tot_vol


def calculate_volume_profile(prices: list[float], volumes: list[float], bins: int = 12) -> dict[str, Any]:
    """Calculate Volume Profile (POC, VAH, VAL, HVN, LVN) from price and volume series."""
    bars = [{"timestamp": "2026-01-01T00:00:00Z", "open": p, "high": p, "low": p, "close": p, "volume": v} for p, v in zip(prices, volumes)]
    return _volume_profile(bars, bin_count=bins)


def detect_support_resistance(prices: list[float]) -> dict[str, float]:
    """Detect dynamic support and resistance levels from a price series."""
    if not prices:
        return {"support": 0.0, "resistance": 0.0}
    return {"support": min(prices), "resistance": max(prices)}
