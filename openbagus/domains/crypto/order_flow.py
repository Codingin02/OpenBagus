"""OpenBagus crypto order flow intelligence layer.

Implements local-only crypto microstructure analysis:
Order Flow, order book metrics, funding rate, open interest, BTC dominance,
stablecoin flow, crypto liquidity regime, microstructure divergence, spot futures basis,
exchange flow candidate, and legal free data availability check.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


ENGINE_VERSION = "openbagus.domains.crypto.order_flow.v1"


class CryptoOrderFlowError(ValueError):
    """Raised when crypto order flow input data is invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise CryptoOrderFlowError(f"{field_name} must be numeric") from exc

    if number != number:
        raise CryptoOrderFlowError(f"{field_name} cannot be NaN")

    return number


def _round(value: float, digits: int = 8) -> float:
    return round(float(value), digits)


def normalize_order_book(order_book: Mapping[str, Any]) -> dict[str, Any]:
    if "bids" not in order_book or "asks" not in order_book:
        raise CryptoOrderFlowError("order_book must contain bids and asks")

    bids_raw = list(order_book["bids"])
    asks_raw = list(order_book["asks"])

    if not bids_raw or not asks_raw:
        raise CryptoOrderFlowError("order_book bids and asks cannot be empty")

    bids: list[dict[str, float]] = []
    asks: list[dict[str, float]] = []

    for index, row in enumerate(bids_raw):
        price = _to_float(row[0], f"bids[{index}].price")
        size = _to_float(row[1], f"bids[{index}].size")
        if price <= 0 or size < 0:
            raise CryptoOrderFlowError("bid price must be positive and size non-negative")
        bids.append({"price": price, "size": size})

    for index, row in enumerate(asks_raw):
        price = _to_float(row[0], f"asks[{index}].price")
        size = _to_float(row[1], f"asks[{index}].size")
        if price <= 0 or size < 0:
            raise CryptoOrderFlowError("ask price must be positive and size non-negative")
        asks.append({"price": price, "size": size})

    bids = sorted(bids, key=lambda item: item["price"], reverse=True)
    asks = sorted(asks, key=lambda item: item["price"])

    if bids[0]["price"] >= asks[0]["price"]:
        raise CryptoOrderFlowError("best bid must be below best ask")

    return {
        "exchange": str(order_book.get("exchange", "unknown")),
        "symbol": str(order_book.get("symbol", "UNKNOWN")).upper(),
        "timestamp": str(order_book.get("timestamp", utc_now_iso())),
        "bids": bids,
        "asks": asks,
    }


def calculate_order_book_metrics(
    order_book: Mapping[str, Any],
    *,
    depth_levels: int = 10,
) -> dict[str, Any]:
    normalized = normalize_order_book(order_book)

    bids = normalized["bids"][:depth_levels]
    asks = normalized["asks"][:depth_levels]

    best_bid = bids[0]["price"]
    best_ask = asks[0]["price"]
    mid_price = (best_bid + best_ask) / 2.0
    spread = best_ask - best_bid
    spread_pct = spread / mid_price if mid_price else 0.0

    bid_depth = sum(level["price"] * level["size"] for level in bids)
    ask_depth = sum(level["price"] * level["size"] for level in asks)
    bid_size = sum(level["size"] for level in bids)
    ask_size = sum(level["size"] for level in asks)

    total_depth = bid_depth + ask_depth
    depth_imbalance = (bid_depth - ask_depth) / total_depth if total_depth else 0.0

    if depth_imbalance > 0.12:
        imbalance_bias = "bid_dominant"
    elif depth_imbalance < -0.12:
        imbalance_bias = "ask_dominant"
    else:
        imbalance_bias = "balanced"

    return {
        "exchange": normalized["exchange"],
        "symbol": normalized["symbol"],
        "timestamp": normalized["timestamp"],
        "depth_levels": depth_levels,
        "best_bid": _round(best_bid),
        "best_ask": _round(best_ask),
        "mid_price": _round(mid_price),
        "spread": _round(spread),
        "spread_pct": _round(spread_pct),
        "bid_depth_notional": _round(bid_depth),
        "ask_depth_notional": _round(ask_depth),
        "bid_size": _round(bid_size),
        "ask_size": _round(ask_size),
        "depth_imbalance": _round(depth_imbalance),
        "imbalance_bias": imbalance_bias,
    }


def analyze_funding_open_interest(
    funding_rate: Any,
    open_interest_now: Any,
    open_interest_previous: Any,
) -> dict[str, Any]:
    funding = _to_float(funding_rate, "funding_rate")
    oi_now = _to_float(open_interest_now, "open_interest_now")
    oi_prev = _to_float(open_interest_previous, "open_interest_previous")

    if oi_now < 0 or oi_prev < 0:
        raise CryptoOrderFlowError("open interest cannot be negative")

    oi_change = (oi_now / oi_prev - 1.0) if oi_prev else 0.0

    if funding > 0.0005 and oi_change > 0.03:
        regime = "long_crowding_risk"
    elif funding < -0.0005 and oi_change > 0.03:
        regime = "short_crowding_risk"
    elif abs(funding) <= 0.0005 and abs(oi_change) <= 0.03:
        regime = "neutral_derivatives"
    elif oi_change < -0.05:
        regime = "deleveraging"
    else:
        regime = "mixed_derivatives"

    return {
        "funding_rate": _round(funding),
        "funding_rate_pct": _round(funding * 100.0, 6),
        "open_interest_now": _round(oi_now),
        "open_interest_previous": _round(oi_prev),
        "open_interest_change": _round(oi_change),
        "open_interest_change_pct": _round(oi_change * 100.0, 6),
        "derivatives_regime": regime,
    }


def calculate_btc_dominance_context(
    btc_dominance_now: Any,
    btc_dominance_previous: Any,
) -> dict[str, Any]:
    now = _to_float(btc_dominance_now, "btc_dominance_now")
    previous = _to_float(btc_dominance_previous, "btc_dominance_previous")

    if now > 1.0:
        now = now / 100.0
    if previous > 1.0:
        previous = previous / 100.0

    if now < 0 or now > 1 or previous < 0 or previous > 1:
        raise CryptoOrderFlowError("BTC dominance must be 0..1 or 0..100")

    change = now - previous

    if change > 0.01:
        context = "btc_dominance_rising_risk_off_for_alts"
    elif change < -0.01:
        context = "btc_dominance_falling_alt_beta_support"
    else:
        context = "btc_dominance_stable"

    return {
        "btc_dominance_now": _round(now),
        "btc_dominance_previous": _round(previous),
        "btc_dominance_change": _round(change),
        "btc_dominance_change_pct_points": _round(change * 100.0, 6),
        "context": context,
    }


def analyze_stablecoin_flow(
    stablecoin_supply_now: Any,
    stablecoin_supply_previous: Any,
    exchange_stablecoin_reserve_now: Any,
    exchange_stablecoin_reserve_previous: Any,
) -> dict[str, Any]:
    supply_now = _to_float(stablecoin_supply_now, "stablecoin_supply_now")
    supply_prev = _to_float(stablecoin_supply_previous, "stablecoin_supply_previous")
    reserve_now = _to_float(exchange_stablecoin_reserve_now, "exchange_stablecoin_reserve_now")
    reserve_prev = _to_float(exchange_stablecoin_reserve_previous, "exchange_stablecoin_reserve_previous")

    if min(supply_now, supply_prev, reserve_now, reserve_prev) < 0:
        raise CryptoOrderFlowError("stablecoin values cannot be negative")

    supply_change = supply_now / supply_prev - 1.0 if supply_prev else 0.0
    reserve_change = reserve_now / reserve_prev - 1.0 if reserve_prev else 0.0

    if supply_change > 0.01 and reserve_change > 0.02:
        regime = "fresh_stablecoin_liquidity_on_exchange"
    elif supply_change > 0.01 and reserve_change <= 0:
        regime = "stablecoin_supply_growth_off_exchange"
    elif supply_change < -0.01:
        regime = "stablecoin_liquidity_contraction"
    else:
        regime = "stablecoin_flow_neutral"

    return {
        "stablecoin_supply_now": _round(supply_now),
        "stablecoin_supply_previous": _round(supply_prev),
        "stablecoin_supply_change": _round(supply_change),
        "stablecoin_supply_change_pct": _round(supply_change * 100.0, 6),
        "exchange_stablecoin_reserve_now": _round(reserve_now),
        "exchange_stablecoin_reserve_previous": _round(reserve_prev),
        "exchange_stablecoin_reserve_change": _round(reserve_change),
        "exchange_stablecoin_reserve_change_pct": _round(reserve_change * 100.0, 6),
        "stablecoin_flow_regime": regime,
    }


def calculate_spot_futures_basis(
    spot_price: Any,
    futures_price: Any,
) -> dict[str, Any]:
    spot = _to_float(spot_price, "spot_price")
    futures = _to_float(futures_price, "futures_price")

    if spot <= 0 or futures <= 0:
        raise CryptoOrderFlowError("spot and futures price must be positive")

    basis = futures / spot - 1.0

    if basis > 0.01:
        regime = "contango_risk_on_or_carry_demand"
    elif basis < -0.01:
        regime = "backwardation_stress_or_spot_demand"
    else:
        regime = "basis_neutral"

    return {
        "spot_price": _round(spot),
        "futures_price": _round(futures),
        "basis": _round(basis),
        "basis_pct": _round(basis * 100.0, 6),
        "basis_regime": regime,
    }


def evaluate_exchange_flow_candidate(
    exchange_inflow: Any,
    exchange_outflow: Any,
) -> dict[str, Any]:
    inflow = _to_float(exchange_inflow, "exchange_inflow")
    outflow = _to_float(exchange_outflow, "exchange_outflow")

    if inflow < 0 or outflow < 0:
        raise CryptoOrderFlowError("exchange flow values cannot be negative")

    netflow = inflow - outflow
    total = inflow + outflow
    netflow_ratio = netflow / total if total else 0.0

    if netflow_ratio > 0.15:
        regime = "net_exchange_inflow_distribution_risk"
    elif netflow_ratio < -0.15:
        regime = "net_exchange_outflow_accumulation_candidate"
    else:
        regime = "exchange_flow_neutral"

    return {
        "exchange_inflow": _round(inflow),
        "exchange_outflow": _round(outflow),
        "netflow": _round(netflow),
        "netflow_ratio": _round(netflow_ratio),
        "netflow_regime": regime,
    }


def detect_liquidity_regime(
    *,
    order_book_metrics: Mapping[str, Any],
    stablecoin_flow: Mapping[str, Any],
    basis: Mapping[str, Any],
) -> dict[str, Any]:
    score = 50
    notes: list[str] = []

    spread_pct = float(order_book_metrics["spread_pct"])
    imbalance = float(order_book_metrics["depth_imbalance"])

    if spread_pct <= 0.0005:
        score += 10
        notes.append("Order book spread is tight.")
    elif spread_pct >= 0.002:
        score -= 15
        notes.append("Order book spread is wide.")

    if abs(imbalance) >= 0.20:
        score -= 8
        notes.append("Order book imbalance is elevated.")
    else:
        notes.append("Order book imbalance is moderate.")

    stablecoin_regime = str(stablecoin_flow["stablecoin_flow_regime"])
    if "fresh_stablecoin_liquidity" in stablecoin_regime:
        score += 12
        notes.append("Stablecoin flow supports liquidity.")
    elif "contraction" in stablecoin_regime:
        score -= 12
        notes.append("Stablecoin flow shows liquidity contraction.")

    basis_regime = str(basis["basis_regime"])
    if "contango" in basis_regime:
        score += 5
        notes.append("Spot-futures basis shows risk-on or carry demand.")
    elif "backwardation" in basis_regime:
        score -= 6
        notes.append("Spot-futures basis shows stress or spot pressure.")

    score = max(0, min(100, score))

    if score >= 70:
        regime = "high_liquidity"
    elif score >= 45:
        regime = "normal_liquidity"
    else:
        regime = "thin_or_stressed_liquidity"

    return {
        "liquidity_score": int(score),
        "crypto_liquidity_regime": regime,
        "notes": notes,
    }


def detect_microstructure_divergence(
    *,
    price_change: Any,
    open_interest_change: Any,
    depth_imbalance: Any,
    funding_rate: Any,
) -> dict[str, Any]:
    price = _to_float(price_change, "price_change")
    oi_change = _to_float(open_interest_change, "open_interest_change")
    imbalance = _to_float(depth_imbalance, "depth_imbalance")
    funding = _to_float(funding_rate, "funding_rate")

    divergences: list[str] = []

    if price > 0.02 and oi_change < -0.03:
        divergences.append("price_up_open_interest_down_short_covering_candidate")

    if price < -0.02 and oi_change < -0.03:
        divergences.append("price_down_open_interest_down_long_liquidation_candidate")

    if price > 0.02 and imbalance < -0.15:
        divergences.append("price_up_against_ask_dominant_book")

    if price < -0.02 and imbalance > 0.15:
        divergences.append("price_down_against_bid_dominant_book")

    if price > 0.02 and funding > 0.0008:
        divergences.append("price_up_with_positive_funding_long_crowding_watch")

    if price < -0.02 and funding < -0.0008:
        divergences.append("price_down_with_negative_funding_short_crowding_watch")

    if not divergences:
        regime = "no_major_microstructure_divergence"
    elif len(divergences) <= 2:
        regime = "moderate_microstructure_divergence"
    else:
        regime = "high_microstructure_divergence"

    return {
        "price_change": _round(price),
        "price_change_pct": _round(price * 100.0, 6),
        "open_interest_change": _round(oi_change),
        "open_interest_change_pct": _round(oi_change * 100.0, 6),
        "depth_imbalance": _round(imbalance),
        "funding_rate": _round(funding),
        "divergences": divergences,
        "microstructure_divergence_regime": regime,
    }


def evaluate_legal_free_data_availability(
    sources: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    source_list = list(sources)
    if not source_list:
        raise CryptoOrderFlowError("at least one data source candidate is required")

    evaluated: list[dict[str, Any]] = []
    usable_count = 0

    for source in source_list:
        name = str(source.get("name", "")).strip()
        public_access = bool(source.get("public_access", False))
        terms_allow_research = bool(source.get("terms_allow_research", False))
        requires_login = bool(source.get("requires_login", False))
        requires_paid_plan = bool(source.get("requires_paid_plan", False))
        provides_order_book = bool(source.get("provides_order_book", False))
        provides_funding = bool(source.get("provides_funding", False))
        provides_open_interest = bool(source.get("provides_open_interest", False))

        if not name:
            raise CryptoOrderFlowError("source name cannot be empty")

        usable = (
            public_access
            and terms_allow_research
            and not requires_login
            and not requires_paid_plan
            and (provides_order_book or provides_funding or provides_open_interest)
        )
        if usable:
            usable_count += 1

        evaluated.append(
            {
                "name": name,
                "public_access": public_access,
                "terms_allow_research": terms_allow_research,
                "requires_login": requires_login,
                "requires_paid_plan": requires_paid_plan,
                "provides_order_book": provides_order_book,
                "provides_funding": provides_funding,
                "provides_open_interest": provides_open_interest,
                "usable_for_local_research_candidate": usable,
            }
        )

    return {
        "source_count": len(evaluated),
        "usable_candidate_count": usable_count,
        "legal_free_data_availability_check": "candidate_available" if usable_count else "no_safe_candidate_yet",
        "sources": evaluated,
    }
