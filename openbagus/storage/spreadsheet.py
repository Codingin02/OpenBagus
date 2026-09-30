"""OpenBagus Spreadsheet Exporter.

Exports clean tabular research summaries into CSV sheets.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root


class SpreadsheetExporter:
    """Exports structured data to CSV files."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.sheets_dir = self.root / "reports/runtime/sheets"
        self.sheets_dir.mkdir(parents=True, exist_ok=True)

    def export_summary(self, analysis_payload: Mapping[str, Any]) -> dict[str, str]:
        asset_csv = self.sheets_dir / "latest_asset_summary.csv"
        macro_csv = self.sheets_dir / "latest_macro_summary.csv"

        # Asset summary
        asset_views = analysis_payload.get("asset_views", {})
        with asset_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Symbol", "Price", "Stance", "Conviction", "Actionability", "Invalidation", "Regime"])
            for sym, view in asset_views.items():
                ms = view.get("market_structure", {})
                writer.writerow([
                    sym,
                    ms.get("current_price", ""),
                    view.get("portfolio_stance", ""),
                    view.get("conviction_score", ""),
                    view.get("actionability_score", ""),
                    view.get("invalidation_level", ""),
                    ms.get("regime", ""),
                ])

        # Macro summary
        macro_views = analysis_payload.get("macro_views", {})
        with macro_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Country", "Indicator", "Value", "Unit", "Status"])
            for country, data in macro_views.items():
                if isinstance(data, dict):
                    for ind in data.get("indicators", []):
                        writer.writerow([
                            country,
                            ind.get("indicator_name", ind.get("indicator_code", "")),
                            ind.get("value", ""),
                            ind.get("unit", ""),
                            ind.get("freshness_status", ""),
                        ])

        return {
            "asset_csv": str(asset_csv),
            "macro_csv": str(macro_csv),
        }
