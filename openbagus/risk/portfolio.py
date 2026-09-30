"""Risk and portfolio metrics over runtime market rows.

Calculates:
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Maximum drawdown
- Beta & covariance vs benchmark
- Value at Risk (VaR 95%) and Conditional VaR (CVaR 95%)
- Monte Carlo multi-path simulations
- Expectancy and profit factor
"""

from __future__ import annotations

import math
import random
from typing import Any, Mapping


ENGINE_VERSION = "openbagus.risk.portfolio.v1"
TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.045


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


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _returns_from_rows(rows: list[Mapping[str, Any]]) -> tuple[list[float], float | None]:
    sorted_rows = sorted(rows, key=lambda item: str(item.get("observed_at_utc", "")))
    closes = [_to_float(row.get("price")) for row in sorted_rows]
    closes = [value for value in closes if value is not None and value > 0]
    returns: list[float] = []
    for previous, current in zip(closes, closes[1:]):
        returns.append((current / previous) - 1.0)

    latest_bar_return = None
    latest = sorted_rows[-1] if sorted_rows else None
    if latest:
        open_price = _to_float(latest.get("open"))
        close = _to_float(latest.get("price"))
        if open_price and close and open_price > 0:
            latest_bar_return = (close / open_price) - 1.0

    return returns, latest_bar_return


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, (equity / peak) - 1.0)
    return max_drawdown


def _beta(returns: list[float], benchmark_returns: list[float] | None) -> float | None:
    if not benchmark_returns or len(returns) < 2:
        return None
    count = min(len(returns), len(benchmark_returns))
    asset = returns[-count:]
    benchmark = benchmark_returns[-count:]
    benchmark_mean = _mean(benchmark)
    asset_mean = _mean(asset)
    covariance = sum((asset[index] - asset_mean) * (benchmark[index] - benchmark_mean) for index in range(count))
    variance = sum((value - benchmark_mean) ** 2 for value in benchmark)
    if variance == 0:
        return None
    return covariance / variance


def _monte_carlo(returns: list[float], seed_text: str) -> dict[str, Any]:
    if len(returns) < 2:
        return {"status": "DATA_NOT_ENOUGH", "paths": 0}
    avg = _mean(returns)
    std = _sample_std(returns)
    rng = random.Random(seed_text)
    path_returns = []
    for _ in range(500):
        equity = 1.0
        for _ in range(20):
            equity *= 1.0 + rng.gauss(avg, std)
        path_returns.append(equity - 1.0)
    return {
        "status": "OK",
        "paths": 500,
        "horizon_bars": 20,
        "p05": _round(_percentile(path_returns, 0.05), 6),
        "p50": _round(_percentile(path_returns, 0.50), 6),
        "p95": _round(_percentile(path_returns, 0.95), 6),
    }


def resolve_risk_free_rate(macro_rows: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    macro_rows = macro_rows or []
    for row in macro_rows:
        code = str(row.get("indicator_code", "")).lower()
        name = str(row.get("indicator_name", "")).lower()
        value = _to_float(row.get("value"))
        if value is not None and ("us10y" in code or "tnx" in code or "treasury" in name):
            annual_rate = value / 100.0 if value > 1.0 else value
            return {
                "annual_rate": _round(annual_rate, 6),
                "status": "DATA_AVAILABLE",
                "source_name": row.get("source_name", "US10Y"),
            }
    return {
        "annual_rate": DEFAULT_RISK_FREE_RATE,
        "status": "FALLBACK_RISK_FREE_RATE",
        "source_name": "config_default_risk_free_rate",
    }


# Backward-compatible alias
risk_free_rate_indonesia = resolve_risk_free_rate


def calculate_risk_metrics(
    symbol: str,
    market_rows: list[Mapping[str, Any]],
    *,
    benchmark_rows: list[Mapping[str, Any]] | None = None,
    macro_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    returns, latest_bar_return = _returns_from_rows(market_rows)
    benchmark_returns, _ = _returns_from_rows(benchmark_rows or [])
    rf = resolve_risk_free_rate(macro_rows)
    rf_daily = (1.0 + float(rf["annual_rate"])) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0

    base = {
        "engine_version": ENGINE_VERSION,
        "symbol": symbol,
        "risk_free_rate": rf,
        "available_return_observations": len(returns),
        "latest_bar_return": _round(latest_bar_return, 8),
    }

    if len(returns) < 2:
        base.update(
            {
                "status": "DATA_NOT_ENOUGH",
                "reason": "At least two realized return observations are required for portfolio risk metrics.",
                "sharpe": None,
                "sortino": None,
                "calmar": None,
                "max_drawdown": None,
                "beta": None,
                "var_95": None,
                "cvar_95": None,
                "monte_carlo": {"status": "DATA_NOT_ENOUGH", "paths": 0},
                "expectancy": None,
                "profit_factor": None,
            }
        )
        return base

    excess = [value - rf_daily for value in returns]
    std = _sample_std(excess)
    downside = [min(0.0, value) for value in excess]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside)) if downside else 0.0
    annualized_return = ((1.0 + _mean(returns)) ** TRADING_DAYS_PER_YEAR) - 1.0
    max_dd = _max_drawdown(returns)
    losses = [value for value in returns if value < 0]
    gains = [value for value in returns if value > 0]
    var_95 = _percentile(returns, 0.05)
    cvar_values = [value for value in returns if value <= var_95]

    base.update(
        {
            "status": "OK",
            "sharpe": _round((_mean(excess) / std) * math.sqrt(TRADING_DAYS_PER_YEAR) if std else 0.0, 6),
            "sortino": _round((_mean(excess) / downside_deviation) * math.sqrt(TRADING_DAYS_PER_YEAR) if downside_deviation else 0.0, 6),
            "calmar": _round(annualized_return / abs(max_dd) if max_dd < 0 else 0.0, 6),
            "max_drawdown": _round(max_dd, 6),
            "beta": _round(_beta(returns, benchmark_returns), 6),
            "var_95": _round(var_95, 6),
            "cvar_95": _round(_mean(cvar_values), 6) if cvar_values else None,
            "monte_carlo": _monte_carlo(returns, symbol),
            "expectancy": _round(_mean(returns), 8),
            "profit_factor": _round(sum(gains) / abs(sum(losses)), 6) if losses else None,
        }
    )
    return base
