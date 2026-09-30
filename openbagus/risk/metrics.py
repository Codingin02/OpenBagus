"""Asset-level quantitative risk metrics for OpenBagus."""

from __future__ import annotations

import math
import random
from typing import Any, Iterable

from openbagus.risk.portfolio import calculate_risk_metrics

ENGINE_VERSION = "openbagus.risk.metrics.v2"
TRADING_DAYS_PER_YEAR = 252


def calculate_volatility(returns: Iterable[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    ret_list = list(returns)
    if len(ret_list) < 2:
        return 0.0
    mean_val = sum(ret_list) / len(ret_list)
    variance = sum((r - mean_val) ** 2 for r in ret_list) / (len(ret_list) - 1)
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def returns_from_prices(prices: Iterable[float]) -> list[float]:
    price_list = list(prices)
    if len(price_list) < 2:
        return []
    returns: list[float] = []
    for prev, curr in zip(price_list, price_list[1:]):
        if prev > 0:
            returns.append((curr / prev) - 1.0)
    return returns


def calculate_sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.045,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    if len(returns) < 2:
        return 0.0
    rf_daily = (1.0 + risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    excess = [r - rf_daily for r in returns]
    avg = sum(excess) / len(excess)
    variance = sum((r - avg) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(max(0.0, variance))
    return (avg / std) * math.sqrt(periods_per_year) if std > 0 else 0.0


def calculate_sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.045,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    if len(returns) < 2:
        return 0.0
    rf_daily = (1.0 + risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    excess = [r - rf_daily for r in returns]
    avg = sum(excess) / len(excess)
    downside = [min(0.0, r) for r in excess]
    downside_var = sum(r * r for r in downside) / len(downside)
    downside_dev = math.sqrt(max(0.0, downside_var))
    return (avg / downside_dev) * math.sqrt(periods_per_year) if downside_dev > 0 else 0.0


def calculate_max_drawdown(prices: list[float]) -> float:
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        dd = (peak - p) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def calculate_var_cvar(returns: list[float], confidence: float = 0.95) -> tuple[float | None, float | None]:
    if len(returns) < 2:
        return None, None
    ordered = sorted(returns)
    idx = max(0, int((1.0 - confidence) * len(ordered)))
    var = ordered[idx]
    tail = ordered[: idx + 1]
    cvar = sum(tail) / len(tail) if tail else var
    return round(var, 6), round(cvar, 6)


def monte_carlo_drawdown_simulation(
    returns: list[float],
    paths: int = 100,
    horizon: int = 30,
    seed: int = 42,
) -> dict[str, Any]:
    if len(returns) < 2:
        return {"status": "DATA_NOT_ENOUGH", "paths": 0}
    rng = random.Random(seed)
    max_drawdowns: list[float] = []
    for _ in range(paths):
        sample = [rng.choice(returns) for _ in range(horizon)]
        cum = 1.0
        peak = 1.0
        dd = 0.0
        for r in sample:
            cum *= 1.0 + r
            if cum > peak:
                peak = cum
            cur_dd = (peak - cum) / peak
            if cur_dd > dd:
                dd = cur_dd
        max_drawdowns.append(dd)

    max_drawdowns.sort()
    return {
        "status": "OK",
        "paths": paths,
        "horizon_days": horizon,
        "median_max_dd": round(max_drawdowns[paths // 2], 6),
        "worst_max_dd": round(max(max_drawdowns), 6),
    }


__all__ = [
    "calculate_volatility",
    "returns_from_prices",
    "calculate_risk_metrics",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_max_drawdown",
    "calculate_var_cvar",
    "monte_carlo_drawdown_simulation",
]
