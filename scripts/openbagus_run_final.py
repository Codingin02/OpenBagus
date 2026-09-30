"""OpenBagus Final Runtime Runner.

Master execution script for the OpenBagus intelligence platform.
Active domain: CRYPTO (BTC, ETH, SOL) + shared cross-asset macro overlay.
Equities domain is deactivated.

Safety: NO_SEND_FILE_ONLY mode enforced by default.
Manual trigger: Requires exact trigger 'OpenBagus'. Spaced variant 'Open Bagus' is rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.analysis.engine import run_real_analysis
from openbagus.data.ingestion import run_runtime_ingestion
from openbagus.delivery.runner import CONFIRMATION_PHRASE, run_final_delivery
from openbagus.reporting.dashboard import PwaDashboardRenderer
from openbagus.storage.historical import HistoricalStorageRuntime
from openbagus.storage.spreadsheet import SpreadsheetExporter

STATUS_PATH = REPO_ROOT / "reports/runtime/delivery/openbagus_final_run_status_latest.json"
DELIVERY_STATUS_PATH = REPO_ROOT / "reports/runtime/delivery/delivery_status_latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mode_delivery_plan(mode: str, query: str | None) -> list[dict[str, Any]]:
    if mode == "daily-brief":
        # Equity delivery removed; active domain is crypto + shared macro
        return [
            {"name": "crypto_daily_delivery", "mode": "auto-crypto-daily", "wa": True, "email": False, "ntfy": False},
            {"name": "macro_email_delivery", "mode": "macro-email", "wa": False, "email": True, "ntfy": False},
            {"name": "app_alert_delivery", "mode": "app-alert", "wa": False, "email": False, "ntfy": True},
            {"name": "dashboard_update", "mode": "app-dashboard", "wa": False, "email": False, "ntfy": False},
        ]
    if mode == "crypto-daily":
        return [
            {"name": "crypto_daily_delivery", "mode": "auto-crypto-daily", "wa": True, "email": False, "ntfy": False},
            {"name": "dashboard_update", "mode": "app-dashboard", "wa": False, "email": False, "ntfy": False},
        ]
    if mode == "idx-daily":
        print(json.dumps({
            "status": "EQUITY_DOMAIN_DISABLED",
            "message": "Equities subsystem is temporarily deactivated in OpenBagus. Active domain is crypto.",
        }, indent=2))
        sys.exit(0)
    if mode == "macro-email":
        return [
            {"name": "macro_email_delivery", "mode": "macro-email", "wa": False, "email": True, "ntfy": False},
            {"name": "dashboard_update", "mode": "app-dashboard", "wa": False, "email": False, "ntfy": False},
        ]
    if mode == "app-alert":
        return [
            {"name": "app_alert_delivery", "mode": "app-alert", "wa": False, "email": False, "ntfy": True},
            {"name": "dashboard_update", "mode": "app-dashboard", "wa": False, "email": False, "ntfy": False},
        ]
    if mode == "dashboard":
        return [{"name": "dashboard_update", "mode": "app-dashboard", "wa": False, "email": False, "ntfy": False}]
    if mode == "manual-desk":
        return [
            {"name": "manual_crypto_delivery", "mode": "manual-crypto", "wa": True, "email": False, "ntfy": False, "query": query},
            {"name": "dashboard_update", "mode": "app-dashboard", "wa": False, "email": False, "ntfy": False},
        ]
    raise ValueError(f"Unsupported mode: {mode}")


def _should_refresh(mode: str) -> bool:
    return mode in {"daily-brief", "crypto-daily", "manual-desk"}


def _run_refresh_and_analysis(mode: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if not _should_refresh(mode):
        steps.append({"step": "data_refresh", "status": "SKIPPED", "reason": "mode uses latest existing runtime input"})
        steps.append({"step": "analysis", "status": "SKIPPED", "reason": "mode uses latest existing analysis output"})
        return steps

    try:
        ingestion = run_runtime_ingestion(mode="real", assets=[], all_core=True, repo_root=REPO_ROOT)
        steps.append({
            "step": "data_refresh",
            "status": "OK",
            "run_id": ingestion.get("run_id"),
            "market_rows": len(ingestion.get("market_rows", [])),
            "macro_rows": len(ingestion.get("macro_rows", [])),
        })
    except Exception as exc:
        steps.append({"step": "data_refresh", "status": "FAILED_STOP", "error": str(exc)[:220]})
        return steps

    try:
        analysis = run_real_analysis(assets=[], all_core=True, repo_root=REPO_ROOT)
        steps.append({
            "step": "analysis",
            "status": "OK",
            "overall_status": analysis.get("data_freshness_summary", {}).get("overall_analysis_status"),
            "assets_evaluated": list(analysis.get("asset_views", {}).keys()),
        })
    except Exception as exc:
        steps.append({"step": "analysis", "status": "FAILED_STOP", "error": str(exc)[:220]})
        return steps

    try:
        hist = HistoricalStorageRuntime(REPO_ROOT).record_run(analysis)
        sheets = SpreadsheetExporter(REPO_ROOT).export_summary(analysis)
        steps.append({
            "step": "storage",
            "status": "OK",
            "history_rows": hist.get("rows_written", 0),
            "sheets": sheets,
        })
    except Exception as exc:
        steps.append({"step": "storage", "status": "FAILED_CONTINUE", "error": str(exc)[:220]})

    return steps


def _run_delivery_plan(args: argparse.Namespace, plan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    aggregate: dict[str, Any] = {}

    for item in plan:
        try:
            res = run_final_delivery(
                mode=item["mode"],
                query=item.get("query") or args.query,
                dry_run=True,  # Default safe execution
                confirmation=args.confirm_live_send,
                repo_root=REPO_ROOT,
            )
            steps.append({"step": item["name"], "status": res.get("status", "OK"), "mode": item["mode"]})
            aggregate[item["name"]] = res
        except Exception as exc:
            steps.append({"step": item["name"], "status": "FAILED_PARTIAL_CONTINUE", "mode": item["mode"], "error": str(exc)[:220]})

    return steps, aggregate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenBagus master runtime delivery and dashboard orchestration.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["daily-brief", "crypto-daily", "idx-daily", "macro-email", "app-alert", "dashboard", "manual-desk"],
    )
    parser.add_argument("--query", default=None, help="Required for manual-desk; must contain exact trigger 'OpenBagus'.")
    parser.add_argument("--send-wa", action="store_true", help="Staged file outbox mode by default.")
    parser.add_argument("--send-email", action="store_true", help="Staged file outbox mode by default.")
    parser.add_argument("--send-ntfy", action="store_true", help="Staged file outbox mode by default.")
    parser.add_argument("--update-dashboard", action="store_true", help="Update static PWA dashboard.")
    parser.add_argument("--update-sheets", action="store_true", help="Update CSV spreadsheets.")
    parser.add_argument("--confirm-live-send", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.mode == "manual-desk":
        if not args.query or "OpenBagus" not in args.query:
            print(json.dumps({
                "status": "BLOCKED_MANUAL_TRIGGER",
                "reason": "manual-desk requires query with exact trigger 'OpenBagus'. Note: 'Open Bagus' is rejected.",
            }, indent=2))
            return 2

    started = _utc_now()
    steps = _run_refresh_and_analysis(args.mode)

    # Check if early step failed
    if any(s.get("status") == "FAILED_STOP" for s in steps):
        print(json.dumps({"status": "PIPELINE_FAILED", "steps": steps}, indent=2))
        return 1

    plan = _mode_delivery_plan(args.mode, args.query)
    delivery_steps, aggregate_delivery = _run_delivery_plan(args, plan)
    steps.extend(delivery_steps)

    # Build PWA dashboard if requested or in brief/dashboard mode
    if args.update_dashboard or args.mode in {"daily-brief", "dashboard", "crypto-daily"}:
        try:
            dash_res = PwaDashboardRenderer(REPO_ROOT).write()
            steps.append({"step": "dashboard_build", "status": dash_res.get("status", "OK")})
        except Exception as exc:
            steps.append({"step": "dashboard_build", "status": "FAILED_CONTINUE", "error": str(exc)[:220]})

    consolidated = {
        "platform": "OpenBagus",
        "engine_version": "openbagus.final_runner.v2",
        "active_domain": "crypto",
        "disabled_domains": ["equities"],
        "generated_at_utc": _utc_now(),
        "started_at_utc": started,
        "mode": args.mode,
        "query": args.query,
        "manual_trigger": "OpenBagus",
        "research_only": True,
        "send_mode": "NO_SEND_FILE_ONLY",
        "numeric_decision_core": "Python Quant Engine",
        "steps": steps,
        "delivery_status": aggregate_delivery,
        "dashboard_path": str(REPO_ROOT / "reports/runtime/app/index.html"),
    }

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_PATH.open("w", encoding="utf-8") as f:
        json.dump(consolidated, f, indent=2)

    with DELIVERY_STATUS_PATH.open("w", encoding="utf-8") as f:
        json.dump(consolidated, f, indent=2)

    summary = {
        "platform": "OpenBagus",
        "active_domain": "crypto",
        "generated_at_utc": consolidated["generated_at_utc"],
        "mode": consolidated["mode"],
        "steps": {step["step"]: step.get("status") for step in steps},
        "status_path": str(STATUS_PATH),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
