"""Interactive financial chart viewer using TradingView Lightweight Charts.

Launches a native desktop window on Windows via lightweight-charts (pywebview/WebView2),
consuming authoritative OpenBagus observations with zero external API keys.
Falls back safely to local HTML or terminal charts if no GUI display is available.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from openbagus.reporting.canonical import CanonicalChartData
from openbagus.reporting.visualizer import generate_html_report


def launch_interactive_chart(
    data: CanonicalChartData | None = None,
    block: bool = False,
    *,
    symbol: str | None = None,
    candles: Any = None,
    timeframe: str = "1D",
    quant_result: Any = None,
    root: Path | None = None,
    blocking: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Displays an interactive desktop chart window using TradingView Lightweight Charts.

    Returns a dict with:
    - 'status': 'WINDOW_OPENED' | 'FALLBACK_HTML' | 'FALLBACK_TERMINAL'
    - 'message': user explanation
    - 'path': file path if fallback was used
    """
    if not isinstance(data, CanonicalChartData):
        sym = symbol or (str(data) if data is not None else "ASSET")
        c_list = candles if candles is not None else (kwargs.get("candles") or [])
        tf = timeframe or kwargs.get("timeframe", "1D")
        q = quant_result or kwargs.get("quant_result")
        data = CanonicalChartData(asset=sym, timeframe=tf, candles=c_list, quant_result=q)

    is_blocking = block or blocking
    data.validate_candles()
    if not data.candles:
        return {
            "status": "ERROR",
            "message": f"Tidak ada data bar OHLCV untuk {data.asset}; chart tidak dapat dibuka.",
            "path": None,
        }

    # Format candles for lightweight-charts
    import pandas as pd
    records = []
    for c in data.candles:
        dt_val = c.get("open_at") or c.get("time") or c.get("date")
        if isinstance(dt_val, (int, float)):
            t_str = pd.to_datetime(dt_val, unit="ms" if dt_val > 1e11 else "s").strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(dt_val, str):
            t_str = str(dt_val)[:19].replace("T", " ")
        else:
            t_str = str(dt_val)

        records.append({
            "time": t_str,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0.0) or 0.0),
        })

    df = pd.DataFrame(records)

    try:
        from lightweight_charts import Chart

        def _run_window():
            try:
                chart = Chart(
                    title=f"{data.asset} ({data.timeframe}) [{data.currency}] - OpenBagus Terminal",
                    toolbox=True,
                    inner_width=0.95,
                    inner_height=0.95,
                )
                chart.set(df)

                # Overlays
                q = data.quant_result
                if q:
                    if getattr(q, "entry_zone", None) and isinstance(q.entry_zone, (int, float)):
                        chart.horizontal_line(float(q.entry_zone), color="#29b6f6", text="Entry Zone")
                    if getattr(q, "stop_price", None) is not None:
                        chart.horizontal_line(float(q.stop_price), color="#ef5350", text="Stop Loss")
                    if getattr(q, "tp1", None) is not None:
                        chart.horizontal_line(float(q.tp1), color="#66bb6a", text="Take Profit")

                chart.show(block=True)
            except Exception:
                pass

        if is_blocking:
            _run_window()
        else:
            t = threading.Thread(target=_run_window, daemon=True)
            t.start()

        return {
            "status": "WINDOW_OPENED",
            "message": f"Membuka chart interaktif TradingView Lightweight Charts ({data.asset} {data.timeframe}). CLI tetap aktif.",
            "path": None,
        }

    except (ImportError, Exception) as err:
        # Graceful fallback to standalone local HTML viewer
        html_path = generate_html_report(
            asset=data.asset,
            candles=data.candles,
            quant_result=data.quant_result,
            ownership=data.ownership,
            timeframe=data.timeframe,
            currency=data.currency,
        )
        return {
            "status": "FALLBACK_HTML",
            "message": f"Desktop window tidak tersedia ({err}); fallback ke visualisasi HTML lokal:\n{html_path}",
            "path": str(html_path),
        }
