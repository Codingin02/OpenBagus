"""Terminal table renderer for OpenBagus using Rich with plain-text fallback."""

from __future__ import annotations

import io
from typing import Any, Sequence

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


def render_stocks_table(assets: Sequence[Any], title: str = "IDX Listed Universe", limit: int = 50) -> str:
    """Renders a clean, formatted table of listed IDX stocks."""
    if not assets:
        return "Tidak ada instrumen yang cocok dengan kriteria pencarian."

    items = list(assets[:limit])
    headers = ["Ticker", "Nama Perusahaan", "Sektor", "Papan", "Status", "IPO Date"]

    rows = []
    for a in items:
        sym = getattr(a, "symbol", "")
        name = getattr(a, "name", "")
        if len(name) > 32:
            name = name[:29] + "..."
        sec = getattr(a, "sector_or_category", "") or getattr(a, "industry", "")
        if len(sec) > 18:
            sec = sec[:15] + "..."
        board = getattr(a, "board", "UNKNOWN")
        status = getattr(a, "listing_status", "ACTIVE")
        ipo = getattr(a, "listing_date", "") or "-"
        rows.append([sym, name, sec, board, status, ipo])

    if _RICH_AVAILABLE:
        import sys
        is_win_non_utf8 = sys.platform == "win32" and (getattr(sys.stdout, "encoding", None) or "").lower() not in {"utf-8", "utf8"}
        box_style = box.ASCII if is_win_non_utf8 else box.ROUNDED
        console = Console(file=io.StringIO(), force_terminal=False, width=100)
        table = Table(title=f"{title} ({len(items)} dari {len(assets)} instrumen)", box=box_style)
        table.add_column("Ticker", style="bold green", no_wrap=True)
        table.add_column("Nama Perusahaan", style="white")
        table.add_column("Sektor", style="cyan")
        table.add_column("Papan", style="yellow")
        table.add_column("Status", style="magenta")
        table.add_column("IPO Date", style="dim")

        for r in rows:
            table.add_row(*r)

        console.print(table)
        return console.file.getvalue().strip()
    else:
        # Plain text tabular fallback
        col_widths = [8, 34, 20, 12, 10, 12]
        lines = [f"=== {title} ({len(items)}/{len(assets)}) ==="]
        header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        lines.append(header_line)
        lines.append("-" * len(header_line))
        for r in rows:
            lines.append(" | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(r)))
        return "\n".join(lines)


def render_tabular_data(headers: Sequence[str], rows: Sequence[Sequence[Any]], title: str = "") -> str:
    """Renders generic tabular financial data directly in the terminal."""
    if not rows:
        return "Tidak ada baris data untuk ditampilkan."

    if _RICH_AVAILABLE:
        import sys
        is_win_non_utf8 = sys.platform == "win32" and (getattr(sys.stdout, "encoding", None) or "").lower() not in {"utf-8", "utf8"}
        box_style = box.ASCII if is_win_non_utf8 else box.ROUNDED
        console = Console(file=io.StringIO(), force_terminal=False, width=100)
        table = Table(title=title if title else None, box=box_style)
        for h in headers:
            table.add_column(h, style="white")
        for r in rows:
            table.add_row(*[str(cell) for cell in r])
        console.print(table)
        return console.file.getvalue().strip()
    else:
        lines = []
        if title:
            lines.append(f"=== {title} ===")
        header_line = " | ".join(str(h) for h in headers)
        lines.append(header_line)
        lines.append("-" * len(header_line))
        for r in rows:
            lines.append(" | ".join(str(cell) for cell in r))
        return "\n".join(lines)


render_terminal_table = render_tabular_data
