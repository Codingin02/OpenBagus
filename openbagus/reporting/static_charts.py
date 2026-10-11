"""Professional static financial charts using Matplotlib and mplfinance.

Generates high-resolution publication-grade PNG images using the non-interactive
Agg backend for headless local report generation.
"""

from __future__ import annotations

import io
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
matplotlib.use("Agg")  # Strictly headless, no GUI thread required
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from openbagus.domains.equities.ownership import OwnershipStructure
from openbagus.reporting.canonical import CanonicalChartData


def _get_export_dir(root: Path | None = None) -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        p = Path(base) / "OpenBagus" / "exports"
    elif root:
        p = root / "reports" / "exports"
    else:
        p = Path("exports")
    p.mkdir(parents=True, exist_ok=True)
    return p


def render_candlestick_png(
    data: CanonicalChartData | None = None,
    output_path: Path | None = None,
    dpi: int = 150,
    *,
    symbol: str | None = None,
    candles: Sequence[Mapping[str, Any]] | None = None,
    timeframe: str = "1D",
    quant_result: Any = None,
    **kwargs: Any,
) -> Path:
    """Renders professional candlestick + volume PNG using mplfinance/matplotlib."""
    import pandas as pd
    import mplfinance as mpf

    if not isinstance(data, CanonicalChartData):
        sym = symbol or (str(data) if data is not None else "ASSET")
        c_list = candles if candles is not None else (kwargs.get("candles") or [])
        tf = timeframe or kwargs.get("timeframe", "1D")
        q = quant_result or kwargs.get("quant_result")
        levels = []
        if q:
            if getattr(q, "stop_price", None) is not None:
                levels.append({"label": "Stop Loss", "price": float(q.stop_price), "color": "#ef4444"})
            if getattr(q, "tp1", None) is not None:
                levels.append({"label": "Target (TP1)", "price": float(q.tp1), "color": "#22c55e"})
        data = CanonicalChartData(asset=sym, timeframe=tf, candles=c_list, levels=levels)

    data.validate_candles()
    if not data.candles:
        raise ValueError(f"No OHLCV candles available for {data.asset}")

    # Build DataFrame
    records = []
    for c in data.candles:
        dt_raw = c.get("open_at") or c.get("time") or c.get("date")
        if isinstance(dt_raw, (int, float)):
            dt = datetime.fromtimestamp(dt_raw / 1000 if dt_raw > 1e11 else dt_raw, tz=timezone.utc)
        elif isinstance(dt_raw, str):
            dt = pd.to_datetime(dt_raw)
        else:
            dt = datetime.now(timezone.utc)

        records.append({
            "Date": dt,
            "Open": float(c["open"]),
            "High": float(c["high"]),
            "Low": float(c["low"]),
            "Close": float(c["close"]),
            "Volume": float(c.get("volume", 0.0) or 0.0),
        })

    df = pd.DataFrame(records).set_index("Date").sort_index()

    # Style configuration
    mc = mpf.make_marketcolors(
        up="#26a69a", down="#ef5350",
        edge="inherit",
        wick="inherit",
        volume={"up": "#26a69a", "down": "#ef5350"},
    )
    s = mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style="nightclouds",
        rc={
            "font.family": "sans-serif",
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
        },
    )

    dest = output_path or _get_export_dir() / f"{data.asset}_{data.timeframe}_candlestick.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Horizontal level overlays (Entry, Stop, Target)
    hlines = []
    colors = []
    linestyles = []
    q = data.quant_result
    if q:
        entry = getattr(q, "entry_zone", None)
        if isinstance(entry, (int, float)):
            hlines.append(float(entry))
            colors.append("#29b6f6")
            linestyles.append("--")
        if getattr(q, "stop_price", None) is not None:
            hlines.append(float(q.stop_price))
            colors.append("#ef5350")
            linestyles.append("-.")
        if getattr(q, "tp1", None) is not None:
            hlines.append(float(q.tp1))
            colors.append("#66bb6a")
            linestyles.append(":")

    hlines_kwargs = {}
    if hlines:
        hlines_kwargs = dict(hlines=dict(hlines=hlines, colors=colors, linestyle=linestyles, linewidths=1.2))

    fig, _axlist = mpf.plot(
        df,
        type="candle",
        volume=True,
        style=s,
        title=f"\n{data.asset} ({data.timeframe}) - {data.market} [{data.currency}]\nData Freshness: {data.data_freshness}",
        returnfig=True,
        figsize=(11, 6),
        **hlines_kwargs,
    )
    fig.savefig(str(dest), dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return dest


def render_ownership_pie_png(
    ownership: OwnershipStructure | None,
    symbol: str,
    output_path: Path | None = None,
    dpi: int = 150,
) -> Path:
    """Renders a verified, non-overlapping ownership breakdown pie chart.
    
    Refuses to render overlapping classification categories (e.g. mixing foreign
    investor percentage with individual shareholder stakes).
    """
    if ownership is None:
        raise ValueError(f"Tidak ada data kepemilikan terverifikasi untuk {symbol}")

    if not ownership.top_shareholders:
        raise ValueError(f"Rincian pemegang saham {symbol} tidak tersedia; tidak membuat visualisasi buatan.")

    labels = []
    values = []
    total_accounted = 0.0

    # Top shareholders (>= 5% / pengendali)
    for s in ownership.top_shareholders:
        labels.append(f"{s.shareholder[:24]}\n({s.percentage:.1f}%)")
        values.append(s.percentage)
        total_accounted += s.percentage

    # Remainder is public / free float
    free_float = ownership.public_shareholders_pct
    if free_float > 0 and (total_accounted + free_float <= 102.0):
        labels.append(f"Publik / Free Float\n({free_float:.1f}%)")
        values.append(free_float)
        total_accounted += free_float
    elif total_accounted < 99.0:
        remainder = max(0.0, 100.0 - total_accounted)
        labels.append(f"Pemegang Saham Lain\n({remainder:.1f}%)")
        values.append(remainder)

    if sum(values) <= 0:
        raise ValueError("Total kepemilikan bernilai nol atau tidak valid.")

    dest = output_path or _get_export_dir() / f"{symbol}_ownership_pie.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 6), facecolor="#131722")
    ax.set_facecolor("#131722")

    palette = ["#2962ff", "#00bcd4", "#26a69a", "#ab47bc", "#ff9800", "#78909c"]
    colors = palette[:len(values)]
    if len(values) > len(palette):
        colors = plt.cm.tab10(np.linspace(0, 1, len(values)))

    wedges, texts = ax.pie(
        values,
        labels=labels,
        colors=colors,
        startangle=140,
        textprops=dict(color="#d1d4dc", fontsize=9),
        wedgeprops=dict(width=0.45, edgecolor="#131722", linewidth=2),  # Donut
    )

    ax.set_title(
        f"Struktur Kepemilikan Saham: {ownership.issuer} ({symbol})\n"
        f"Periode: {ownership.reporting_date} | Sumber: {ownership.source}",
        color="#ffffff",
        fontsize=11,
        fontweight="bold",
        pad=16,
    )

    fig.savefig(str(dest), dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return dest


def render_equity_curve_png(
    backtest_result: Any,
    symbol: str,
    output_path: Path | None = None,
    dpi: int = 150,
) -> Path:
    """Renders backtest equity curve and underwater drawdown chart."""
    if not backtest_result or not getattr(backtest_result, "equity_curve", None):
        raise ValueError(f"Tidak ada riwayat equity curve backtest untuk {symbol}")

    curve = backtest_result.equity_curve
    dates = []
    equities = []
    initial = getattr(backtest_result, "initial_capital", 100_000_000.0)

    for pt in curve:
        dt_val = pt.get("date") or pt.get("time")
        if isinstance(dt_val, str):
            try:
                d = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
            except ValueError:
                d = datetime.now(timezone.utc)
        elif isinstance(dt_val, datetime):
            d = dt_val
        else:
            d = datetime.now(timezone.utc)
        dates.append(d)
        equities.append(float(pt.get("equity", initial)))

    if len(equities) < 2:
        raise ValueError("Data seri equity curve terlalu sedikit (minimal 2 titik).")

    # Calculate Drawdown
    arr = np.array(equities)
    peak = np.maximum.accumulate(arr)
    drawdowns = (arr - peak) / peak * 100.0

    dest = output_path or _get_export_dir() / f"{symbol}_backtest_equity.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.2]}, facecolor="#131722")
    for ax in (ax1, ax2):
        ax.set_facecolor("#1e222d")
        ax.tick_params(colors="#787b86", labelsize=8)
        ax.grid(True, linestyle="--", alpha=0.2, color="#787b86")

    # Ax1: Equity Curve
    net_pnl = getattr(backtest_result, "total_return_pct", ((equities[-1] - initial) / initial) * 100.0)
    line_color = "#26a69a" if net_pnl >= 0 else "#ef5350"
    ax1.plot(dates, equities, color=line_color, linewidth=1.8, label=f"Portfolio Equity ({net_pnl:+.2f}%)")
    ax1.axhline(initial, color="#787b86", linestyle=":", linewidth=1, label="Modal Awal")
    ax1.set_ylabel("Nilai Portofolio (IDR)", color="#d1d4dc", fontsize=9)
    ax1.legend(loc="upper left", facecolor="#1e222d", edgecolor="#2a2e39", labelcolor="#d1d4dc", fontsize=8)
    ax1.set_title(f"Backtest Equity Curve: {symbol} | Total Return: {net_pnl:+.2f}% | Max Drawdown: {getattr(backtest_result, 'max_drawdown_pct', 0.0):.2f}%",
                  color="#ffffff", fontsize=11, fontweight="bold")

    # Ax2: Drawdown Underwater
    ax2.fill_between(dates, drawdowns, 0, color="#ef5350", alpha=0.4)
    ax2.plot(dates, drawdowns, color="#ef5350", linewidth=1.2)
    ax2.set_ylabel("Drawdown %", color="#d1d4dc", fontsize=8)
    ax2.set_ylim(min(-10.0, min(drawdowns) * 1.15), 1.0)

    fig.autofmt_xdate()
    fig.savefig(str(dest), dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return dest


def render_macro_line_png(
    series: Sequence[Mapping[str, Any]] | None = None,
    title: str = "Macro Series",
    ylabel: str = "Nilai",
    output_path: Path | None = None,
    dpi: int = 150,
    *,
    points: Sequence[Mapping[str, Any]] | None = None,
    series_label: str | None = None,
    currency: str | None = None,
    source: str | None = None,
    **kwargs: Any,
) -> Path:
    """Renders a dated time-series line chart (e.g. USD/IDR JISDOR, Inflation)."""
    import pandas as pd

    actual_series = series if series is not None else (points or kwargs.get("points") or [])
    if len(actual_series) < 2:
        raise ValueError("Seri data historis minimal memiliki 2 observasi.")

    actual_ylabel = series_label or (f"Kurs ({currency})" if currency else ylabel)
    dates = []
    values = []
    for pt in actual_series:
        dt_val = pt.get("date") or pt.get("observation_date") or pt.get("period")
        try:
            d = pd.to_datetime(dt_val)
        except Exception:
            d = datetime.now(timezone.utc)
        dates.append(d)
        values.append(float(pt.get("value") or pt.get("rate") or pt.get("price") or 0.0))

    dest = output_path or _get_export_dir() / "macro_series_chart.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 5), facecolor="#131722")
    ax.set_facecolor("#1e222d")
    ax.tick_params(colors="#787b86", labelsize=8)
    ax.grid(True, linestyle="--", alpha=0.2, color="#787b86")

    ax.plot(dates, values, color="#2962ff", linewidth=2.0)
    ax.fill_between(dates, values, min(values) * 0.99, color="#2962ff", alpha=0.15)
    ax.set_ylabel(actual_ylabel, color="#d1d4dc", fontsize=9)
    full_title = f"{title}\nSumber: {source}" if source else title
    ax.set_title(full_title, color="#ffffff", fontsize=11, fontweight="bold", pad=12)

    fig.autofmt_xdate()
    fig.savefig(str(dest), dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return dest


def render_peer_bar_png(
    peer_data: Mapping[str, Mapping[str, float]],
    metric_name: str,
    title: str,
    output_path: Path | None = None,
    dpi: int = 150,
) -> Path:
    """Renders a comparative horizontal/vertical bar chart for peers (e.g. BMRI vs BBCA)."""
    if not peer_data:
        raise ValueError("Data pembanding emiten kosong.")

    symbols = list(peer_data.keys())
    values = [peer_data[s].get(metric_name, 0.0) for s in symbols]

    dest = output_path or _get_export_dir() / f"peer_compare_{metric_name}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#131722")
    ax.set_facecolor("#1e222d")
    ax.tick_params(colors="#787b86", labelsize=9)
    ax.grid(True, axis="y", linestyle="--", alpha=0.2, color="#787b86")

    bars = ax.bar(symbols, values, color=["#2962ff", "#26a69a", "#ff9800", "#ab47bc"][:len(symbols)], width=0.5)
    ax.set_ylabel(metric_name, color="#d1d4dc", fontsize=9)
    ax.set_title(title, color="#ffffff", fontsize=11, fontweight="bold", pad=12)

    # Bar value labels
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:,.2f}",
                    xy=(bar.get_x() + bar.get_width() / 2, h),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", color="#ffffff", fontsize=8, fontweight="bold")

    fig.savefig(str(dest), dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return dest
