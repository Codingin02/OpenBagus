"""OpenBagus Historical Storage Runtime.

Appends structured runs to local CSV and JSON storage files under reports/runtime/sheets.
Authoritative mode is purely local file-based.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root

ENGINE_VERSION = "openbagus.historical_storage.v2"
SHEETS_DIR = Path("reports/runtime/sheets")

HISTORY_FIELDS = [
    "run_id",
    "generated_at_utc",
    "domain",
    "asset",
    "portfolio_stance",
    "conviction_score",
    "actionability_score",
    "invalidation",
    "target_zone",
    "freshness_status",
    "analysis_status",
    "price",
    "risk_note",
]


class HistoricalStorageRuntime:
    """Manages append-only history for OpenBagus research runs."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.sheets_dir = self.root / SHEETS_DIR
        self.sheets_dir.mkdir(parents=True, exist_ok=True)

    def record_run(self, analysis_payload: Mapping[str, Any]) -> dict[str, Any]:
        run_id = analysis_payload.get("runtime_input", {}).get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        gen_time = analysis_payload.get("generated_at_utc", "N/A")
        asset_views = analysis_payload.get("asset_views", {})

        csv_path = self.sheets_dir / "openbagus_history.csv"
        file_exists = csv_path.exists()

        rows_written = 0
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
            if not file_exists:
                writer.writeheader()

            for sym, view in asset_views.items():
                ms = view.get("market_structure", {})
                dq = view.get("data_quality", {})
                row = {
                    "run_id": run_id,
                    "generated_at_utc": gen_time,
                    "domain": "crypto",
                    "asset": sym,
                    "portfolio_stance": view.get("portfolio_stance"),
                    "conviction_score": view.get("conviction_score"),
                    "actionability_score": view.get("actionability_score"),
                    "invalidation": view.get("invalidation_level"),
                    "target_zone": json.dumps(view.get("target_zone")),
                    "freshness_status": dq.get("freshness_status"),
                    "analysis_status": dq.get("analysis_status"),
                    "price": ms.get("current_price"),
                    "risk_note": view.get("risk_note"),
                }
                writer.writerow(row)
                rows_written += 1

        return {
            "status": "RECORDED_HISTORY",
            "csv_path": str(csv_path),
            "rows_written": rows_written,
        }
