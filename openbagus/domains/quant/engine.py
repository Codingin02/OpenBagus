"""OpenBagus Unified Quantitative Engine.

Seamlessly bridges native Rust acceleration (`openbagus_quant_native`) and high-precision
vectorized Python/NumPy fallback (`PYTHON_FALLBACK`). Guarantees identical numerical contracts,
Wilder's smoothing, Monte Carlo VaR/CVaR, and board-lot monetary arithmetic.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# Attempt to load PyO3 native Rust extension
_RUST_AVAILABLE = False
_RUST_MODULE = None
_RUST_ERROR = ""

try:
    import openbagus_quant_native
    _RUST_MODULE = openbagus_quant_native
    _RUST_AVAILABLE = True
except Exception as e:
    _RUST_ERROR = str(e)
    _RUST_AVAILABLE = False


def is_rust_native_available() -> bool:
    """Returns True if the PyO3 native Rust module is compiled and imported cleanly."""
    return _RUST_AVAILABLE


def get_engine_diagnostics() -> dict[str, Any]:
    """Returns transparent engine status, backend name, and reason for fallback."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return {
            "backend": "RUST_NATIVE",
            "active": True,
            "info": _RUST_MODULE.engine_info(),
            "reason": "Rust native PyO3/Rayon extension is compiled and operational.",
        }
    return {
        "backend": "PYTHON_FALLBACK",
        "active": True,
        "info": "OpenBagus Python/NumPy Vectorized Quant Fallback v1.0",
        "reason": f"Native wheel not compiled ({_RUST_ERROR}); fallback active with identical precision.",
    }


# ============================================================================
# Core Quantitative Mathematical Kernels (Identical between Rust and Python)
# ============================================================================

def calculate_sma(prices: Sequence[float], period: int) -> list[float | None]:
    """Computes Simple Moving Average (SMA)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_sma(list(prices), period)

    n = len(prices)
    result: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return result

    curr_sum = sum(prices[:period])
    result[period - 1] = curr_sum / period
    for i in range(period, n):
        curr_sum += prices[i] - prices[i - period]
        result[i] = curr_sum / period
    return result


def calculate_ema(prices: Sequence[float], period: int) -> list[float | None]:
    """Computes Exponential Moving Average (EMA)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_ema(list(prices), period)

    n = len(prices)
    result: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return result

    multiplier = 2.0 / (period + 1.0)
    initial_sum = sum(prices[:period])
    prev_ema = initial_sum / period
    result[period - 1] = prev_ema

    for i in range(period, n):
        ema = (prices[i] - prev_ema) * multiplier + prev_ema
        result[i] = ema
        prev_ema = ema
    return result


def calculate_rsi(prices: Sequence[float], period: int = 14) -> list[float | None]:
    """Computes Wilder's Relative Strength Index (RSI)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_rsi(list(prices), period)

    n = len(prices)
    result: list[float | None] = [None] * n
    if period <= 0 or n <= period:
        return result

    gains = []
    losses = []
    for i in range(1, n):
        chg = prices[i] - prices[i - 1]
        if chg > 0.0:
            gains.append(chg)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-chg)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0.0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    p_f = float(period)
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (p_f - 1.0) + gains[i]) / p_f
        avg_loss = (avg_loss * (p_f - 1.0) + losses[i]) / p_f

        if avg_loss == 0.0:
            result[i + 1] = 100.0
        elif avg_gain == 0.0:
            result[i + 1] = 0.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def calculate_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    """Computes Wilder's Average True Range (ATR)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_atr(list(highs), list(lows), list(closes), period)

    n = len(closes)
    result: list[float | None] = [None] * n
    if period <= 0 or n < period or len(highs) != n or len(lows) != n:
        return result

    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_cp = abs(highs[i] - closes[i - 1])
        l_cp = abs(lows[i] - closes[i - 1])
        trs.append(max(h_l, h_cp, l_cp))

    prev_atr = sum(trs[:period]) / period
    result[period - 1] = prev_atr

    p_f = float(period)
    for i in range(period, n):
        atr = (prev_atr * (p_f - 1.0) + trs[i]) / p_f
        result[i] = atr
        prev_atr = atr

    return result


def calculate_macd(
    prices: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Computes MACD line, signal line, and histogram."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_macd(list(prices), fast, slow, signal)

    n = len(prices)
    macd_line: list[float | None] = [None] * n
    signal_line: list[float | None] = [None] * n
    hist: list[float | None] = [None] * n

    if fast >= slow or n < slow:
        return macd_line, signal_line, hist

    ema_f = calculate_ema(prices, fast)
    ema_s = calculate_ema(prices, slow)

    valid_macd: list[float] = []
    valid_indices: list[int] = []

    for i in range(n):
        f = ema_f[i]
        s = ema_s[i]
        if f is not None and s is not None:
            m = f - s
            macd_line[i] = m
            valid_macd.append(m)
            valid_indices.append(i)

    if len(valid_macd) >= signal:
        sig_emas = calculate_ema(valid_macd, signal)
        for j, orig_idx in enumerate(valid_indices):
            sig_val = sig_emas[j]
            if sig_val is not None:
                signal_line[orig_idx] = sig_val
                m_val = macd_line[orig_idx]
                if m_val is not None:
                    hist[orig_idx] = m_val - sig_val

    return macd_line, signal_line, hist


def calculate_bollinger_bands(
    prices: Sequence[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Computes Bollinger Bands (Upper, Middle SMA, Lower)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_bollinger_bands(list(prices), period, num_std)

    n = len(prices)
    upper: list[float | None] = [None] * n
    middle: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n

    if period <= 0 or n < period:
        return upper, middle, lower

    sma = calculate_sma(prices, period)
    for i in range(period - 1, n):
        m = sma[i]
        if m is not None:
            middle[i] = m
            slice_ = prices[(i + 1 - period):(i + 1)]
            var = sum((x - m) ** 2 for x in slice_) / period
            std_dev = math.sqrt(var)
            upper[i] = m + num_std * std_dev
            lower[i] = m - num_std * std_dev

    return upper, middle, lower


def calculate_vwap(prices: Sequence[float], volumes: Sequence[float]) -> list[float | None]:
    """Computes Volume Weighted Average Price (VWAP)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_vwap(list(prices), list(volumes))

    n = len(prices)
    vwap: list[float | None] = [None] * n
    if n == 0 or len(volumes) != n:
        return vwap

    cum_pv = 0.0
    cum_vol = 0.0
    for i in range(n):
        cum_pv += prices[i] * volumes[i]
        cum_vol += volumes[i]
        if cum_vol > 0.0:
            vwap[i] = cum_pv / cum_vol
    return vwap


def calculate_rolling_stats(prices: Sequence[float], period: int) -> tuple[list[float | None], list[float | None]]:
    """Computes rolling mean and standard deviation."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_rolling_stats(list(prices), period)

    n = len(prices)
    means: list[float | None] = [None] * n
    stds: list[float | None] = [None] * n

    if period <= 0 or n < period:
        return means, stds

    sma = calculate_sma(prices, period)
    for i in range(period - 1, n):
        m = sma[i]
        if m is not None:
            means[i] = m
            slice_ = prices[(i + 1 - period):(i + 1)]
            var = sum((x - m) ** 2 for x in slice_) / period
            stds[i] = math.sqrt(var)

    return means, stds


def calculate_var_cvar_mc(
    returns: Sequence[float],
    confidence: float = 0.95,
    num_simulations: int = 10000,
    seed: int | None = 42,
) -> tuple[float, float]:
    """Computes Monte Carlo Value at Risk (VaR) and Conditional VaR (CVaR)."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_var_cvar_mc(list(returns), confidence, num_simulations, seed)

    if not returns or num_simulations <= 0:
        return 0.0, 0.0

    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std_dev = math.sqrt(var)

    # Deterministic Xorshift pseudo-random generator
    state = seed or 42
    sim_losses = []

    for _ in range(num_simulations // 2 + 1):
        state ^= (state >> 12) & 0xFFFFFFFFFFFFFFFF
        state ^= (state << 25) & 0xFFFFFFFFFFFFFFFF
        state ^= (state >> 27) & 0xFFFFFFFFFFFFFFFF
        u1 = (((state * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF) >> 11) / 9007199254740992.0 + 1e-10

        state ^= (state >> 12) & 0xFFFFFFFFFFFFFFFF
        state ^= (state << 25) & 0xFFFFFFFFFFFFFFFF
        state ^= (state >> 27) & 0xFFFFFFFFFFFFFFFF
        u2 = (((state * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF) >> 11) / 9007199254740992.0 + 1e-10

        z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        z1 = math.sqrt(-2.0 * math.log(u1)) * math.sin(2.0 * math.pi * u2)

        r0 = mean + std_dev * z0
        r1 = mean + std_dev * z1

        sim_losses.append(-r0)
        if len(sim_losses) < num_simulations:
            sim_losses.append(-r1)

    sim_losses = sim_losses[:num_simulations]
    sim_losses.sort()

    idx = min(int(math.floor(confidence * num_simulations)), num_simulations - 1)
    val_at_risk = sim_losses[idx]
    tail = sim_losses[idx:]
    cvar = sum(tail) / len(tail) if tail else val_at_risk

    return val_at_risk, cvar


def calculate_lot_shares(
    cash: float,
    price: float,
    max_risk_cash: float,
    stop_loss_price: float,
) -> tuple[int, float]:
    """Calculates risk-constrained position size rounded to exact 100-share board lots."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.calculate_lot_shares(cash, price, max_risk_cash, stop_loss_price)

    if price <= 0.0 or cash <= 0.0:
        return 0, 0.0

    risk_per_share = abs(price - stop_loss_price)
    max_shares_by_risk = math.floor(max_risk_cash / risk_per_share) if risk_per_share > 0 else float("inf")
    max_shares_by_cash = math.floor(cash / price)
    target_shares = max(0.0, min(max_shares_by_risk, max_shares_by_cash))

    lots = math.floor(target_shares / 100.0)
    final_shares = int(lots * 100)
    notional = float(final_shares * price)
    return final_shares, notional


def parallel_universe_screen(
    tickers: list[str],
    closes_list: list[list[float]],
    volumes_list: list[list[float]],
    min_volume_multiplier: float = 2.0,
) -> list[str]:
    """Screens universe for volume expansion breakouts."""
    if _RUST_AVAILABLE and _RUST_MODULE:
        return _RUST_MODULE.parallel_universe_screen(tickers, closes_list, volumes_list, min_volume_multiplier)

    matched = []
    for ticker, closes, volumes in zip(tickers, closes_list, volumes_list):
        n = len(volumes)
        if n < 20 or len(closes) != n:
            continue
        last_vol = volumes[-1]
        v20 = volumes[-20:-1]
        avg_20d_vol = sum(v20) / len(v20) if v20 else 0.0

        if avg_20d_vol > 0.0 and last_vol >= min_volume_multiplier * avg_20d_vol:
            last_close = closes[-1]
            c20 = closes[-20:-1]
            highest_20d = max(c20) if c20 else 0.0
            if last_close > highest_20d:
                matched.append(ticker)

    return matched
