"""Native terminal candlestick and volume chart renderer for OpenBagus.

Renders high-resolution terminal charts with OHLC candles, volume histogram,
price scale, time axis, and quantitative decision levels directly in CLI.
No browser, no web server, no localhost. Pure terminal-resident visualization.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def _format_price(val: float, currency: str = "IDR") -> str:
    if currency == "IDR":
        if val >= 1_000:
            return f"Rp{val:,.0f}"
        return f"Rp{val:,.2f}"
    else:
        if val >= 100:
            return f"${val:,.2f}"
        elif val >= 1:
            return f"${val:.4f}"
        else:
            return f"${val:.6f}"


def _format_volume(val: float) -> str:
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    elif val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return f"{val:.0f}"


def render_terminal_chart(
    symbol: str,
    candles: Sequence[Mapping[str, Any]],
    timeframe: str = "D1",
    currency: str = "IDR",
    quant_result: Any | None = None,
    width: int | None = None,
    height: int = 14,
) -> str:
    """Renders a complete terminal-native candlestick & volume chart.

    Parameters:
    - symbol: asset symbol (e.g. 'BBCA', 'BTC', 'ETH')
    - candles: list of OHLCV dicts with keys (open, high, low, close, volume, open_at or close_at)
    - timeframe: e.g. 'D1', 'H1', 'M15'
    - currency: 'IDR' or 'USD'
    - quant_result: optional QuantDecisionResult for level overlays
    - width: optional width override, defaults to terminal width - 18 for axes
    - height: height of the price candlestick grid in rows
    """
    if not candles:
        return f"[{symbol}] Tidak ada data bar OHLCV untuk menampilkan chart terminal."

    term_cols = shutil.get_terminal_size((80, 24)).columns
    axis_width = 16
    plot_width = max(20, min(100, (width or term_cols) - axis_width - 4))
    use_color = _supports_color()

    # ANSI Colors
    GREEN = "\033[92m" if use_color else ""
    RED = "\033[91m" if use_color else ""
    CYAN = "\033[96m" if use_color else ""
    YELLOW = "\033[93m" if use_color else ""
    GRAY = "\033[90m" if use_color else ""
    BOLD = "\033[1m" if use_color else ""
    RESET = "\033[0m" if use_color else ""

    # Slice recent bars
    bars = list(candles[-plot_width:])
    n_bars = len(bars)

    # Calculate price extents
    highs = [float(c.get("high", 0.0) or 0.0) for c in bars]
    lows = [float(c.get("low", 0.0) or 0.0) for c in bars]
    min_p = min(lows) if lows else 0.0
    max_p = max(highs) if highs else 1.0

    if min_p == max_p:
        max_p += 1.0
        min_p -= 1.0

    # Expand slightly for breathing room
    p_span = max_p - min_p
    min_p -= p_span * 0.02
    max_p += p_span * 0.02
    price_range = max_p - min_p

    # Latest candle metrics for header
    last_c = bars[-1]
    last_o = float(last_c.get("open", 0.0) or 0.0)
    last_h = float(last_c.get("high", 0.0) or 0.0)
    last_l = float(last_c.get("low", 0.0) or 0.0)
    last_cl = float(last_c.get("close", 0.0) or 0.0)
    last_v = float(last_c.get("volume", 0.0) or 0.0)
    first_cl = float(bars[0].get("close", last_cl) or last_cl)

    chg = ((last_cl - last_o) / last_o * 100.0) if last_o > 0 else 0.0
    period_chg = ((last_cl - first_cl) / first_cl * 100.0) if first_cl > 0 else 0.0
    chg_color = GREEN if chg >= 0 else RED
    sign = "+" if chg >= 0 else ""

    # Header Box
    header_lines = [
        f"{BOLD}{CYAN}=== OPENBAGUS TERMINAL CHART: {symbol.upper()} ({timeframe}) ==={RESET}",
        f"Price: {BOLD}{_format_price(last_cl, currency)}{RESET} | "
        f"Chg: {chg_color}{sign}{chg:.2f}%{RESET} | "
        f"O: {_format_price(last_o, currency)}  H: {_format_price(last_h, currency)}  "
        f"L: {_format_price(last_l, currency)}  C: {_format_price(last_cl, currency)} | "
        f"Vol: {_format_volume(last_v)}",
    ]

    # Initialize Candlestick Grid: each cell stores (char, color_code)
    grid = [[(" ", "") for _ in range(n_bars)] for _ in range(height)]

    for x, bar in enumerate(bars):
        o = float(bar.get("open", 0.0) or 0.0)
        h = float(bar.get("high", 0.0) or 0.0)
        l = float(bar.get("low", 0.0) or 0.0)
        cl = float(bar.get("close", 0.0) or 0.0)
        is_bull = cl >= o
        bar_color = GREEN if is_bull else RED

        y_h = int((h - min_p) / price_range * (height - 1))
        y_l = int((l - min_p) / price_range * (height - 1))
        y_o = int((o - min_p) / price_range * (height - 1))
        y_c = int((cl - min_p) / price_range * (height - 1))

        # Clamp row indices
        y_h = max(0, min(height - 1, y_h))
        y_l = max(0, min(height - 1, y_l))
        y_o = max(0, min(height - 1, y_o))
        y_c = max(0, min(height - 1, y_c))

        # Draw wick
        for y in range(min(y_l, y_h), max(y_l, y_h) + 1):
            grid[y][x] = ("│", bar_color)

        # Draw body
        b_bottom = min(y_o, y_c)
        b_top = max(y_o, y_c)
        body_char = "█" if is_bull else "▒"
        if b_bottom == b_top:
            body_char = "┼"

        for y in range(b_bottom, b_top + 1):
            grid[y][x] = (body_char, bar_color)

    # Optional Quant Level Overlays
    quant_levels: list[tuple[str, float, str]] = []
    if quant_result:
        stop_p = getattr(quant_result, "stop_price", None)
        tp1_p = getattr(quant_result, "tp1", None)
        if stop_p and min_p <= stop_p <= max_p:
            quant_levels.append(("SL", float(stop_p), RED))
        if tp1_p and min_p <= tp1_p <= max_p:
            quant_levels.append(("TP1", float(tp1_p), GREEN))

    # Assemble Plot Output
    output_lines: list[str] = list(header_lines)
    output_lines.append("─" * (plot_width + axis_width + 2))

    for y in reversed(range(height)):
        price_at_y = min_p + (y / (height - 1)) * price_range
        row_chars = []
        for ch, col in grid[y]:
            if col:
                row_chars.append(f"{col}{ch}{RESET}")
            else:
                row_chars.append(ch)
        row_body = "".join(row_chars)

        # Check for quant level tag on this row
        level_tag = ""
        for tag, lvl_p, lvl_col in quant_levels:
            if abs(price_at_y - lvl_p) <= (price_range / height * 0.5):
                level_tag = f" {lvl_col}[{tag}]{RESET}"
                break

        price_str = _format_price(price_at_y, currency)
        output_lines.append(f"{row_body} ┤{GRAY}{price_str:>11}{RESET}{level_tag}")

    # Bottom Axis Line
    output_lines.append("─" * n_bars + "┴" + "─" * (axis_width - 1))

    # Volume Subplot (3 rows)
    vols = [float(c.get("volume", 0.0) or 0.0) for c in bars]
    max_v = max(vols) if vols else 1.0
    if max_v <= 0:
        max_v = 1.0

    vol_height = 3
    vol_blocks = [" ", " ", "▂", "▄", "▅", "▆", "▇", "█"]
    vol_grid = [[" " for _ in range(n_bars)] for _ in range(vol_height)]

    for x, v in enumerate(vols):
        is_bull = float(bars[x].get("close", 0.0) or 0.0) >= float(bars[x].get("open", 0.0) or 0.0)
        v_col = GREEN if is_bull else RED
        v_ratio = v / max_v
        v_lines = int(v_ratio * (vol_height * 8 - 1))
        full_cells = v_lines // 8
        remainder = v_lines % 8

        for vy in range(vol_height):
            if vy < full_cells:
                vol_grid[vy][x] = f"{v_col}█{RESET}"
            elif vy == full_cells and remainder > 0:
                vol_grid[vy][x] = f"{v_col}{vol_blocks[remainder]}{RESET}"

    for vy in reversed(range(vol_height)):
        v_scale = (vy + 1) / vol_height * max_v
        v_str = _format_volume(v_scale)
        output_lines.append(f"{''.join(vol_grid[vy])} ┤{GRAY}Vol {v_str:>7}{RESET}")

    output_lines.append("─" * n_bars + "┴" + "─" * (axis_width - 1))

    # Date / Time Labels Axis
    dates_line = [" "] * n_bars
    date_step = max(8, n_bars // 6)
    for x in range(0, n_bars, date_step):
        raw_dt = str(bars[x].get("open_at") or bars[x].get("close_at") or bars[x].get("Date") or "")
        label = ""
        if "T" in raw_dt:
            date_part = raw_dt.split("T")[0]
            label = "-".join(date_part.split("-")[1:])
        elif "-" in raw_dt:
            label = "-".join(raw_dt.split("-")[1:])
        elif len(raw_dt) >= 5:
            label = raw_dt[:5]
        if label and x + len(label) <= n_bars:
            for idx, ch in enumerate(label):
                dates_line[x + idx] = ch

    output_lines.append("".join(dates_line))
    output_lines.append(f"{GRAY}Bars: {n_bars} ({timeframe}) | Period return: {sign}{period_chg:.2f}% | Range: {_format_price(min_p, currency)} - {_format_price(max_p, currency)}{RESET}")

    return "\n".join(output_lines)
