"""OpenBagus Pipeline Orchestrator.

Sequences end-to-end research pipelines: Ingestion -> Analysis -> Storage -> Delivery Staging -> Dashboard Build.
Ensures domain neutrality and modular decoupling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openbagus.analysis.engine import run_real_analysis
from openbagus.core.env import get_repo_root
from openbagus.data.ingestion import run_runtime_ingestion
from openbagus.delivery.runner import run_final_delivery
from openbagus.reporting.dashboard import PwaDashboardRenderer
from openbagus.storage.historical import HistoricalStorageRuntime
from openbagus.storage.spreadsheet import SpreadsheetExporter


class OpenBagusOrchestrator:
    """Master workflow orchestrator for OpenBagus."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()

    def run_pipeline(
        self,
        *,
        mode: str = "crypto-daily",
        assets: list[str] | None = None,
        all_core: bool = True,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {"mode": mode, "dry_run": dry_run, "steps": {}}

        # 1. Ingestion
        ingest_res = run_runtime_ingestion(
            mode="real" if not dry_run else "real",  # Real public fetch is research-safe
            assets=assets,
            all_core=all_core,
            repo_root=self.root,
        )
        results["steps"]["ingestion"] = {
            "status": "OK",
            "run_id": ingest_res.get("run_id"),
            "market_rows": len(ingest_res.get("market_rows", [])),
            "macro_rows": len(ingest_res.get("macro_rows", [])),
        }

        # 2. Quantitative Analysis
        analysis_res = run_real_analysis(
            assets=assets,
            all_core=all_core,
            repo_root=self.root,
        )
        results["steps"]["analysis"] = {
            "status": analysis_res.get("data_freshness_summary", {}).get("overall_analysis_status", "OK"),
            "assets_evaluated": list(analysis_res.get("asset_views", {}).keys()),
        }

        # 3. Storage
        hist = HistoricalStorageRuntime(self.root).record_run(analysis_res)
        sheets = SpreadsheetExporter(self.root).export_summary(analysis_res)
        results["steps"]["storage"] = {
            "history_status": hist["status"],
            "rows_written": hist["rows_written"],
            "sheets_exported": sheets,
        }

        # 4. Delivery Staging (NO_SEND mode)
        delivery_res = run_final_delivery(
            mode=mode,
            dry_run=dry_run,
            repo_root=self.root,
        )
        results["steps"]["delivery"] = delivery_res

        # 5. PWA Dashboard Build
        dash_res = PwaDashboardRenderer(self.root).write(
            runtime={"analysis": analysis_res},
            reports={},
            delivery_status=delivery_res,
        )
        results["steps"]["dashboard"] = dash_res

        results["status"] = "PIPELINE_COMPLETE"
        return results


def run_pipeline(
    *,
    mode: str = "crypto-daily",
    assets: list[str] | None = None,
    all_core: bool = True,
    dry_run: bool = True,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Convenience functional wrapper for OpenBagusOrchestrator."""
    orchestrator = OpenBagusOrchestrator(repo_root=repo_root)
    return orchestrator.run_pipeline(
        mode=mode,
        assets=assets,
        all_core=all_core,
        dry_run=dry_run,
    )
