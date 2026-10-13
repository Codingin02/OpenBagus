"""Terminal-native ASCII visualization for backtest equity curves and underwater drawdowns.

Renders high-resolution sparklines and multi-level vertical graphs directly in the CLI,
providing instant visual feedback without requiring external graphical windows.
"""

from __future__ import annotations

import math
from typing import Sequence

from openbagus.domains.quant.backtesting import BacktestResult


def _format_val(val: float, currency: str = "IDR") -> str:
    if currency == "IDR":
        if abs(val) >= 1_000_000_000:
            return f"Rp{val / 1_000_000_000:.2f}B"
        if abs(val) >= 1_000_000:
            return f"Rp{val / 1_000_000:.1f}M"
        return f"Rp{val:,.0f}"
    if abs(val) >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if abs(val) >= 1_000:
        return f"${val / 1_000:.1f}k"
    return f"${val:,.2f}"


def render_ascii_equity_curve(
    equity_curve: Sequence[float],
    height: int = 8,
    width: int = 55,
    title: str = "Equity Progression",
    currency: str = "IDR",
) -> str:
    """Renders a multi-level vertical ASCII chart of equity curve for terminal display."""
    if not equity_curve:
        return "[No equity data available]"

    n = len(equity_curve)
    if n == 1:
        return f"Initial: {_format_val(equity_curve[0], currency)}"

    # Downsample or bucket curve into `width` columns
    step = n / width
    sampled: list[float] = []
    for col in range(width):
        idx = min(n - 1, int(col * step))
        sampled.append(equity_curve[idx])

    min_eq = min(equity_curve)
    max_eq = max(equity_curve)
    init_eq = equity_curve[0]
    final_eq = equity_curve[-1]
    net_ret = ((final_eq - init_eq) / init_eq * 100.0) if init_eq > 0 else 0.0

    # Ensure range has non-zero height
    eq_range = max_eq - min_eq
    if eq_range <= 0:
        eq_range = 1.0

    # Unicode vertical block characters
    blocks = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

    lines: list[str] = []
    header = f"--- {title} (Net Return: {net_ret:+.2f}%) ---"
    lines.append(header)

    # Render each row from top (max_eq) to bottom (min_eq)
    for row in range(height, 0, -1):
        threshold_low = min_eq + ((row - 1) / height) * eq_range
        threshold_high = min_eq + (row / height) * eq_range
        row_label = _format_val(threshold_high, currency)
        axis_str = f"{row_label:>11} |"

        row_chars: list[str] = []
        for val in sampled:
            if val >= threshold_high:
                row_chars.append("█")
            elif val > threshold_low:
                # Fractional block level
                frac = (val - threshold_low) / (threshold_high - threshold_low)
                b_idx = min(len(blocks) - 1, int(frac * (len(blocks) - 1)) + 1)
                row_chars.append(blocks[b_idx])
            else:
                row_chars.append(" ")
        lines.append(f"{axis_str}{''.join(row_chars)}")

    # Bottom axis and baseline label
    bottom_label = _format_val(min_eq, currency)
    lines.append(f"{bottom_label:>11} +{'=' * width}")
    lines.append(f"{'':>13}Start ({_format_val(init_eq, currency)}) {' ' * max(1, width - 35)} Final ({_format_val(final_eq, currency)})")
    return "\n".join(lines)


def render_ascii_drawdown_chart(
    drawdown_curve: Sequence[float],
    height: int = 5,
    width: int = 55,
) -> str:
    """Renders an underwater drawdown ASCII chart showing portfolio drawdown depths."""
    if not drawdown_curve:
        return ""

    n = len(drawdown_curve)
    step = n / width
    sampled: list[float] = []
    for col in range(width):
        idx = min(n - 1, int(col * step))
        sampled.append(drawdown_curve[idx])

    max_dd = max(drawdown_curve)
    if max_dd <= 0:
        return "Drawdown: 0.0% (Clean run with no peak retraction)"

    lines: list[str] = []
    lines.append(f"--- Underwater Drawdown (Max Retraction: -{max_dd:.2f}%) ---")

    for row in range(1, height + 1):
        dd_level = (row / height) * max_dd
        axis_str = f"-{dd_level:>5.1f}% |"
        row_chars: list[str] = []
        for val in sampled:
            if val >= dd_level:
                row_chars.append("▼")
            elif val >= (row - 1) / height * max_dd:
                row_chars.append("░")
            else:
                row_chars.append(" ")
        lines.append(f"{axis_str}{''.join(row_chars)}")

    lines.append(f"  0.0% +{'-' * width}")
    return "\n".join(lines)


def format_visual_backtest_summary(
    result: BacktestResult,
    currency: str = "IDR",
    include_drawdown: bool = True,
) -> str:
    """Combines tabular performance report with ASCII equity curve and underwater drawdown."""
    parts = [result.summary_table(), ""]
    if result.equity_curve:
        parts.append(render_ascii_equity_curve(result.equity_curve, title=f"Equity Curve: {result.asset}", currency=currency))
        parts.append("")
    if include_drawdown and result.drawdown_curve:
        parts.append(render_ascii_drawdown_chart(result.drawdown_curve))
        parts.append("")
    return "\n".join(parts).strip()
