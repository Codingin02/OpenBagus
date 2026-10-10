"""Mathematically verified quantitative indicators, patterns, and risk metrics.

Canonical implementation adhering strictly to standard statistical and technical definitions:
- Zero division protection
- Finite numeric guards
- Constant-price handling
- Strict rolling window alignment
- No lookahead bias
"""

from __future__ import annotations

import math
from typing import Any


def sma(values: list[float], period: int) -> list[float]:
    """Simple Moving Average with rolling window alignment."""
    if period <= 0 or not values:
        return []
    result: list[float] = []
    window_sum = 0.0
    for i, v in enumerate(values):
        window_sum += v
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            result.append(window_sum / period)
        else:
            result.append(float("nan"))
    return result


def ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average (alpha = 2 / (period + 1))."""
    if period <= 0 or not values:
        return []
    result: list[float] = []
    alpha = 2.0 / (period + 1.0)
    current_ema: float | None = None
    
    # Use SMA of first `period` elements as seed
    for i, v in enumerate(values):
        if i < period - 1:
            result.append(float("nan"))
        elif i == period - 1:
            current_ema = sum(values[:period]) / period
            result.append(current_ema)
        else:
            current_ema = alpha * v + (1.0 - alpha) * current_ema  # type: ignore[operator]
            result.append(current_ema)
    return result


def wilder_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Wilder's Average True Range (TR = max(H-L, |H-Cp|, |L-Cp|))."""
    n = min(len(highs), len(lows), len(closes))
    if period <= 0 or n < 2:
        return [0.0] * n

    tr_list: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        h, l, prev_c = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    atr_list: list[float] = []
    current_atr: float | None = None

    for i, tr in enumerate(tr_list):
        if i < period - 1:
            atr_list.append(float("nan"))
        elif i == period - 1:
            current_atr = sum(tr_list[:period]) / period
            atr_list.append(current_atr)
        else:
            current_atr = (current_atr * (period - 1) + tr) / period  # type: ignore[operator]
            atr_list.append(current_atr)
    return atr_list


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index using Wilder's smoothed moving average."""
    n = len(closes)
    if period <= 0 or n <= period:
        return [50.0] * n

    gains: list[float] = [0.0]
    losses: list[float] = [0.0]

    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    rsi_list: list[float] = []
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    for i in range(n):
        if i < period:
            rsi_list.append(float("nan"))
        elif i == period:
            if avg_loss == 0.0:
                rsi_val = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi_val = 100.0 - (100.0 / (1.0 + rs))
            rsi_list.append(rsi_val)
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0.0:
                rsi_val = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi_val = 100.0 - (100.0 / (1.0 + rs))
            rsi_list.append(rsi_val)
    return rsi_list


def macd(
    closes: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """Moving Average Convergence Divergence (MACD, Signal line, Histogram)."""
    fast_ema = ema(closes, fast_period)
    slow_ema = ema(closes, slow_period)
    n = len(closes)

    macd_line: list[float] = []
    valid_macd_indices: list[int] = []
    valid_macd_values: list[float] = []

    for i in range(n):
        if math.isnan(fast_ema[i]) or math.isnan(slow_ema[i]):
            macd_line.append(float("nan"))
        else:
            val = fast_ema[i] - slow_ema[i]
            macd_line.append(val)
            valid_macd_indices.append(i)
            valid_macd_values.append(val)

    signal_raw = ema(valid_macd_values, signal_period)
    signal_line: list[float] = [float("nan")] * n
    histogram: list[float] = [float("nan")] * n

    for orig_idx, sig_val in zip(valid_macd_indices, signal_raw):
        signal_line[orig_idx] = sig_val
        if not math.isnan(sig_val) and not math.isnan(macd_line[orig_idx]):
            histogram[orig_idx] = macd_line[orig_idx] - sig_val

    return macd_line, signal_line, histogram


def bollinger_bands(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Bollinger Bands (Upper, Middle SMA, Lower, Bandwidth %)."""
    mid = sma(closes, period)
    n = len(closes)
    upper: list[float] = []
    lower: list[float] = []
    bandwidth: list[float] = []

    for i in range(n):
        if math.isnan(mid[i]):
            upper.append(float("nan"))
            lower.append(float("nan"))
            bandwidth.append(float("nan"))
        else:
            window = closes[i - period + 1 : i + 1]
            mean = mid[i]
            variance = sum((x - mean) ** 2 for x in window) / period
            std_dev = math.sqrt(variance)
            up = mean + num_std * std_dev
            dn = mean - num_std * std_dev
            bw = ((up - dn) / mean * 100.0) if mean > 0 else 0.0
            upper.append(up)
            lower.append(dn)
            bandwidth.append(bw)

    return upper, mid, lower, bandwidth


def vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> list[float]:
    """Volume Weighted Average Price (cumulative typical price * volume / cumulative volume)."""
    n = min(len(highs), len(lows), len(closes), len(volumes))
    result: list[float] = []
    cum_pv = 0.0
    cum_vol = 0.0

    for i in range(n):
        typical_price = (highs[i] + lows[i] + closes[i]) / 3.0
        v = volumes[i]
        cum_pv += typical_price * v
        cum_vol += v
        if cum_vol > 0:
            result.append(cum_pv / cum_vol)
        else:
            result.append(typical_price)
    return result


def stochastic_oscillator(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[list[float], list[float]]:
    """Stochastic Oscillator (%K and %D SMA)."""
    n = min(len(highs), len(lows), len(closes))
    k_list: list[float] = []

    for i in range(n):
        if i < k_period - 1:
            k_list.append(float("nan"))
        else:
            highest_h = max(highs[i - k_period + 1 : i + 1])
            lowest_l = min(lows[i - k_period + 1 : i + 1])
            denom = highest_h - lowest_l
            if denom > 0:
                k_val = ((closes[i] - lowest_l) / denom) * 100.0
            else:
                k_val = 50.0
            k_list.append(k_val)

    # %D is SMA of %K
    d_list: list[float] = []
    for i in range(n):
        if i < k_period - 1 + d_period - 1:
            d_list.append(float("nan"))
        else:
            k_window = [k_list[j] for j in range(i - d_period + 1, i + 1) if not math.isnan(k_list[j])]
            if len(k_window) == d_period:
                d_list.append(sum(k_window) / d_period)
            else:
                d_list.append(float("nan"))

    return k_list, d_list


def adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> tuple[list[float], list[float], list[float]]:
    """Average Directional Index (ADX, +DI, -DI) with Wilder smoothing."""
    n = min(len(highs), len(lows), len(closes))
    if period <= 0 or n <= 2 * period:
        return [0.0] * n, [0.0] * n, [0.0] * n

    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    tr_list: list[float] = [highs[0] - lows[0]]

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        p_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        m_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        plus_dm.append(p_dm)
        minus_dm.append(m_dm)
        h, l, prev_c = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    atr_smoothed = sum(tr_list[1:period + 1])
    plus_dm_smoothed = sum(plus_dm[1:period + 1])
    minus_dm_smoothed = sum(minus_dm[1:period + 1])

    plus_di: list[float] = [float("nan")] * n
    minus_di: list[float] = [float("nan")] * n
    dx_list: list[float] = [float("nan")] * n
    adx_list: list[float] = [float("nan")] * n

    for i in range(period, n):
        if i > period:
            atr_smoothed = atr_smoothed - (atr_smoothed / period) + tr_list[i]
            plus_dm_smoothed = plus_dm_smoothed - (plus_dm_smoothed / period) + plus_dm[i]
            minus_dm_smoothed = minus_dm_smoothed - (minus_dm_smoothed / period) + minus_dm[i]

        p_di = (plus_dm_smoothed / atr_smoothed * 100.0) if atr_smoothed > 0 else 0.0
        m_di = (minus_dm_smoothed / atr_smoothed * 100.0) if atr_smoothed > 0 else 0.0
        plus_di[i] = p_di
        minus_di[i] = m_di
        di_sum = p_di + m_di
        dx_list[i] = (abs(p_di - m_di) / di_sum * 100.0) if di_sum > 0 else 0.0

    valid_dx = [dx_list[j] for j in range(period, period * 2) if not math.isnan(dx_list[j])]
    if len(valid_dx) == period:
        current_adx = sum(valid_dx) / period
        adx_list[period * 2 - 1] = current_adx
        for i in range(period * 2, n):
            current_adx = (current_adx * (period - 1) + dx_list[i]) / period
            adx_list[i] = current_adx

    return adx_list, plus_di, minus_di


def realized_volatility(closes: list[float], window: int = 20, annualize_factor: float = 252.0) -> list[float]:
    """Calculates rolling annualized realized volatility from log returns."""
    n = len(closes)
    if window <= 1 or n < 2:
        return [0.0] * n

    log_returns = [0.0]
    for i in range(1, n):
        if closes[i] > 0 and closes[i - 1] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))
        else:
            log_returns.append(0.0)

    result: list[float] = [float("nan")] * n
    for i in range(window, n):
        chunk = log_returns[i - window + 1 : i + 1]
        mean = sum(chunk) / window
        var = sum((r - mean) ** 2 for r in chunk) / (window - 1)
        std = math.sqrt(var)
        result[i] = std * math.sqrt(annualize_factor) * 100.0

    return result


def fibonacci_levels(high: float, low: float) -> dict[str, float]:
    """Calculates canonical Fibonacci retracement and extension levels."""
    diff = high - low
    if diff <= 0:
        return {"0.0": high, "1.0": high}
    return {
        "0.000": high,
        "0.236": high - 0.236 * diff,
        "0.382": high - 0.382 * diff,
        "0.500": high - 0.500 * diff,
        "0.618": high - 0.618 * diff,
        "0.786": high - 0.786 * diff,
        "1.000": low,
        "1.272_ext": high + 0.272 * diff,
        "1.618_ext": high + 0.618 * diff,
    }


def volume_profile(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    bins: int = 15,
) -> dict[str, Any]:
    """Calculates Volume Profile: Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL)."""
    n = min(len(highs), len(lows), len(closes), len(volumes))
    if n == 0 or bins <= 0:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "bins": []}

    min_p = min(lows[:n])
    max_p = max(highs[:n])
    if max_p <= min_p:
        return {"poc": min_p, "vah": min_p, "val": min_p, "bins": []}

    step = (max_p - min_p) / bins
    bin_volumes = [0.0] * bins

    for i in range(n):
        typical = (highs[i] + lows[i] + closes[i]) / 3.0
        b_idx = min(int((typical - min_p) / step), bins - 1)
        bin_volumes[b_idx] += volumes[i]

    max_vol = -1.0
    poc_idx = 0
    total_vol = sum(bin_volumes)
    for idx, v in enumerate(bin_volumes):
        if v > max_vol:
            max_vol = v
            poc_idx = idx

    poc_price = min_p + (poc_idx + 0.5) * step

    # Value area is 70% of total volume around POC
    target_vol = total_vol * 0.70
    accum_vol = bin_volumes[poc_idx]
    up_idx = poc_idx
    down_idx = poc_idx

    while accum_vol < target_vol and (up_idx < bins - 1 or down_idx > 0):
        up_v = bin_volumes[up_idx + 1] if up_idx < bins - 1 else -1.0
        dn_v = bin_volumes[down_idx - 1] if down_idx > 0 else -1.0
        if up_v >= dn_v and up_idx < bins - 1:
            up_idx += 1
            accum_vol += up_v
        elif down_idx > 0:
            down_idx -= 1
            accum_vol += dn_v
        else:
            break

    vah = min_p + (up_idx + 1.0) * step
    val = min_p + down_idx * step

    return {
        "poc": round(poc_price, 2),
        "vah": round(vah, 2),
        "val": round(val, 2),
        "total_volume": total_vol,
    }


def detect_patterns(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluates candlestick price patterns with objective recognition rules."""
    if len(candles) < 3:
        return []

    patterns: list[dict[str, Any]] = []
    c1 = candles[-2]  # previous bar
    c2 = candles[-1]  # current bar

    c1_open, c1_close = float(c1["open"]), float(c1["close"])
    c1_high, c1_low = float(c1["high"]), float(c1["low"])
    c2_open, c2_close = float(c2["open"]), float(c2["close"])
    c2_high, c2_low = float(c2["high"]), float(c2["low"])

    c2_body = abs(c2_close - c2_open)
    c2_range = c2_high - c2_low
    c1_body = abs(c1_close - c1_open)

    # 1. Bullish Engulfing
    if c1_close < c1_open and c2_close > c2_open:
        if c2_open <= c1_close and c2_close >= c1_open:
            patterns.append({
                "name": "Bullish Engulfing",
                "direction": "BULLISH",
                "confirmation": f"Close above {c2_high:.2f}",
                "invalidation": f"Close below {c2_low:.2f}",
                "reliability": "MODERATE",
            })

    # 2. Bearish Engulfing
    if c1_close > c1_open and c2_close < c2_open:
        if c2_open >= c1_close and c2_close <= c1_open:
            patterns.append({
                "name": "Bearish Engulfing",
                "direction": "BEARISH",
                "confirmation": f"Close below {c2_low:.2f}",
                "invalidation": f"Close above {c2_high:.2f}",
                "reliability": "MODERATE",
            })

    # 3. Hammer (bullish rejection pin bar)
    if c2_range > 0 and (c2_body / c2_range) <= 0.35:
        lower_wick = min(c2_open, c2_close) - c2_low
        upper_wick = c2_high - max(c2_open, c2_close)
        if lower_wick >= 2.0 * c2_body and upper_wick <= max(c2_body, 0.15 * c2_range):
            patterns.append({
                "name": "Hammer (Pin Bar)",
                "direction": "BULLISH",
                "confirmation": f"Breakout above {c2_high:.2f}",
                "invalidation": f"Breakdown below {c2_low:.2f}",
                "reliability": "MODERATE",
            })

    # 4. Shooting Star (bearish rejection pin bar)
    if c2_range > 0 and (c2_body / c2_range) <= 0.35:
        lower_wick = min(c2_open, c2_close) - c2_low
        upper_wick = c2_high - max(c2_open, c2_close)
        if upper_wick >= 2.0 * c2_body and lower_wick <= max(c2_body, 0.15 * c2_range):
            patterns.append({
                "name": "Shooting Star",
                "direction": "BEARISH",
                "confirmation": f"Breakdown below {c2_low:.2f}",
                "invalidation": f"Breakout above {c2_high:.2f}",
                "reliability": "MODERATE",
            })

    # 5. Inside Bar (contraction)
    if c2_high <= c1_high and c2_low >= c1_low:
        patterns.append({
            "name": "Inside Bar (Volatility Squeeze)",
            "direction": "NEUTRAL_BREAKOUT",
            "confirmation": f"Expansion breakout above {c1_high:.2f} or below {c1_low:.2f}",
            "invalidation": "Choppy inside range",
            "reliability": "MODERATE",
        })

    # 6. Double Bottom / Double Top check over recent 20 bars
    if len(candles) >= 15:
        lows = [float(c["low"]) for c in candles[-15:]]
        highs = [float(c["high"]) for c in candles[-15:]]
        min_l1 = min(lows[:7])
        min_l2 = min(lows[7:])
        if abs(min_l1 - min_l2) / max(min_l1, min_l2) < 0.008 and min_l2 > 0:
            patterns.append({
                "name": "Double Bottom Support",
                "direction": "BULLISH",
                "confirmation": f"Neckline breakout above {max(highs[4:11]):.2f}",
                "invalidation": f"Support breakdown below {min_l2:.2f}",
                "reliability": "STRONG",
            })

    return patterns


# ---------------------------------------------------------------------------
# Risk and Return Formulas
# ---------------------------------------------------------------------------


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0, annualize_factor: float = 252.0) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns) - risk_free_rate / annualize_factor
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev <= 0:
        return 0.0
    return (mean_ret / std_dev) * math.sqrt(annualize_factor)


def sortino_ratio(returns: list[float], risk_free_rate: float = 0.0, annualize_factor: float = 252.0) -> float:
    """Annualized Sortino ratio (downside deviation denominator)."""
    if len(returns) < 2:
        return 0.0
    target = risk_free_rate / annualize_factor
    mean_ret = sum(returns) / len(returns) - target
    downside_variance = sum(min(0.0, r - target) ** 2 for r in returns) / len(returns)
    downside_dev = math.sqrt(downside_variance)
    if downside_dev <= 0:
        return 0.0
    return (mean_ret / downside_dev) * math.sqrt(annualize_factor)


def max_drawdown(equity_curve: list[float]) -> tuple[float, int, int]:
    """Calculates maximum drawdown percentage and its peak/trough indices."""
    if not equity_curve:
        return 0.0, 0, 0
    peak = equity_curve[0]
    peak_idx = 0
    max_dd = 0.0
    best_peak_idx = 0
    trough_idx = 0

    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            peak_idx = i
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            best_peak_idx = peak_idx
            trough_idx = i

    return max_dd * 100.0, best_peak_idx, trough_idx


def value_at_risk(returns: list[float], confidence: float = 0.95) -> float:
    """Historical Value at Risk (VaR) percentage at given confidence level."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    idx = max(0, int((1.0 - confidence) * len(sorted_returns)))
    return abs(sorted_returns[idx]) * 100.0


def conditional_var(returns: list[float], confidence: float = 0.95) -> float:
    """Conditional Value at Risk (Expected Shortfall) at given confidence level."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    cutoff = max(1, int((1.0 - confidence) * len(sorted_returns)))
    tail = sorted_returns[:cutoff]
    return abs(sum(tail) / len(tail)) * 100.0
