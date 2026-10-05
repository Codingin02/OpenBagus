"""OpenBagus Lightweight Terminal Candlestick Chart Renderer.

Native Python standard library implementation of a compact, high-legibility
OHLC candlestick chart with entry, stop, and target markers. Zero external TUI frameworks.
"""

from __future__ import annotations

import math
import shutil
import sys
from typing import Any


def render_terminal_chart(
    klines: list[dict[str, Any]],
    symbol: str,
    timeframe: str = "H1",
    entry: float | None = None,
    stop: float | None = None,
    tp: float | None = None,
    height: int = 12,
    max_candles: int = 40,
    term_width: int | None = None,
) -> str:
    """Renders a compact terminal OHLC candlestick chart with entry/stop/TP markers."""
    if not klines or len(klines) < 5:
        return "[Chart unavailable: insufficient candle data]"

    width = term_width or shutil.get_terminal_size((80, 24)).columns
    if width < 50:
        return "[Chart unavailable: terminal width < 50 columns]"

    use_utf8 = bool(sys.stdout.encoding and "utf" in sys.stdout.encoding.lower())
    ch_sep = " · " if use_utf8 else " | "
    ch_wick = "│" if use_utf8 else "|"
    ch_bull = "▲" if use_utf8 else "#"
    ch_bear = "▼" if use_utf8 else "*"
    ch_axis = "│" if use_utf8 else "|"
    ch_base = "─" if use_utf8 else "-"
    ch_corner = "└" if use_utf8 else "+"
    ch_marker = "──" if use_utf8 else "--"

    candles = klines[-max_candles:]
    highs = [float(c["high"]) for c in candles if "high" in c]
    lows = [float(c["low"]) for c in candles if "low" in c]
    if not highs or not lows:
        return "[Chart unavailable: invalid OHLC structure]"

    min_p = min(lows)
    max_p = max(highs)
    if entry:
        min_p = min(min_p, entry)
        max_p = max(max_p, entry)
    if stop:
        min_p = min(min_p, stop)
        max_p = max(max_p, stop)
    if tp:
        min_p = min(min_p, tp)
        max_p = max(max_p, tp)

    if max_p <= min_p:
        max_p = min_p + 1.0

    p_range = max_p - min_p
    axis_width = max(len(f"{max_p:,.2f}"), len(f"{min_p:,.2f}")) + 2

    # Available chart columns for candles
    chart_cols = min(len(candles), width - axis_width - 24)
    if chart_cols < 10:
        return "[Chart hidden: terminal width too narrow]"

    plot_candles = candles[-chart_cols:]

    def price_to_row(p: float) -> int:
        norm = (p - min_p) / p_range
        row = int(norm * (height - 1))
        return max(0, min(height - 1, row))

    grid = [[" " for _ in range(chart_cols)] for _ in range(height)]

    for col, c in enumerate(plot_candles):
        o = float(c.get("open", c["close"]))
        cl = float(c["close"])
        hi = float(c["high"])
        lo = float(c["low"])

        row_hi = price_to_row(hi)
        row_lo = price_to_row(lo)
        row_top = price_to_row(max(o, cl))
        row_bot = price_to_row(min(o, cl))

        # Wick
        for r in range(row_lo, row_hi + 1):
            grid[r][col] = ch_wick

        # Body
        body_char = ch_bull if cl >= o else ch_bear
        for r in range(row_bot, row_top + 1):
            grid[r][col] = body_char

    lines = []
    lines.append(f"{symbol}{ch_sep}{timeframe}{ch_sep}{len(plot_candles)} Candles{ch_sep}Range: ${min_p:,.2f} - ${max_p:,.2f}")
    lines.append("-" * min(width - 2, 70))

    tol = p_range / (height * 2)
    for row_idx in range(height - 1, -1, -1):
        row_price = min_p + (row_idx / (height - 1)) * p_range
        p_str = f"${row_price:,.2f}".rjust(axis_width)
        row_chars = "".join(grid[row_idx])

        marker = ""
        if entry and abs(row_price - entry) <= tol:
            marker = f" {ch_marker} Entry ${entry:,.2f}"
        elif stop and abs(row_price - stop) <= tol:
            marker = f" {ch_marker} Stop  ${stop:,.2f}"
        elif tp and abs(row_price - tp) <= tol:
            marker = f" {ch_marker} Target ${tp:,.2f}"

        lines.append(f"{p_str} {ch_axis} {row_chars}{marker}")

    lines.append(" " * axis_width + f" {ch_corner}" + ch_base * chart_cols)
    return "\n".join(lines)
