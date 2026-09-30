"""Canonical OpenBagus CLI for crypto research, email, and diagnostics."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.analysis.engine import run_real_analysis
from openbagus.data.ingestion import run_runtime_ingestion
from openbagus.core.env import RuntimeEnv
from openbagus.delivery.mailbox import SmtpConfig, SmtpTransport
from openbagus.delivery.runner import run_final_delivery
from openbagus.storage.historical import HistoricalStorageRuntime
from openbagus.storage.spreadsheet import SpreadsheetExporter

STATUS_PATH = REPO_ROOT / "reports/runtime/delivery/openbagus_final_run_status_latest.json"
DELIVERY_STATUS_PATH = REPO_ROOT / "reports/runtime/delivery/delivery_status_latest.json"
MODES = ("crypto-daily", "manual-desk", "email", "macro-email", "doctor", "idx-daily")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _should_refresh(mode: str) -> bool:
    return mode in {"crypto-daily", "manual-desk"}


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenBagus crypto research, email, and diagnostics.")
    parser.add_argument("command", nargs="?", choices=MODES, help="Operation to run.")
    parser.add_argument(
        "--mode",
        choices=MODES,
        help="Legacy-compatible alternative to the positional command.",
    )
    parser.add_argument("--query", default=None, help="Required for manual-desk; must contain exact trigger 'OpenBagus'.")
    parser.add_argument("--email-action", choices=["draft", "check", "send"], default="draft")
    parser.add_argument("--network", action="store_true", help="Allow an explicit network-only diagnostic; never sends email.")
    parser.add_argument("--confirm-live-send", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="Print doctor output as JSON.")
    args = parser.parse_args(argv)
    if args.command and args.mode and args.command != args.mode:
        parser.error("command and --mode must match when both are supplied")
    args.mode = args.command or args.mode
    if not args.mode:
        parser.error("a command or --mode is required")
    if args.email_action != "draft" and args.mode not in {"email", "macro-email"}:
        parser.error("--email-action is valid only for email")
    return args


def _run_doctor(*, network: bool, as_json: bool) -> int:
    checks: list[dict[str, str]] = []

    def add(status: str, name: str, detail: str) -> None:
        checks.append({"status": status, "name": name, "detail": detail})

    add("PASS" if sys.version_info >= (3, 11) else "FAIL", "python", sys.version.split()[0])
    try:
        for module in ("openbagus.analysis.engine", "openbagus.data.ingestion", "openbagus.delivery.runner"):
            importlib.import_module(module)
        add("PASS", "imports", "core runtime modules import successfully")
    except ImportError as exc:
        add("FAIL", "imports", str(exc))

    try:
        platform_config = json.loads((REPO_ROOT / "config/openbagus.example.json").read_text(encoding="utf-8"))
        active = platform_config.get("active_domains")
        disabled = platform_config.get("disabled_domains")
        valid = active == ["crypto"] and "equities" in disabled
        add("PASS" if valid else "FAIL", "domains", f"active={active}, disabled={disabled}")
    except (OSError, json.JSONDecodeError) as exc:
        add("FAIL", "domains", f"invalid config: {exc}")

    try:
        source_config = json.loads((REPO_ROOT / "config/openbagus_data_sources.json").read_text(encoding="utf-8"))
        assets = sorted(source_config["core_assets"]["crypto"])
        add("PASS" if assets == ["BTC/USD", "ETH/USD", "SOL/USD"] else "FAIL", "data-sources", ", ".join(assets))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        add("FAIL", "data-sources", f"invalid config: {exc}")

    email_config = SmtpConfig.from_runtime_env(RuntimeEnv(REPO_ROOT))
    email_status = email_config.status()
    add("PASS" if email_config.ready else "WARN", "email", email_status["status"])

    output_dir = REPO_ROOT / "reports/runtime/delivery"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix="doctor-", delete=True):
            pass
        add("PASS", "runtime-output", str(output_dir))
    except OSError as exc:
        add("FAIL", "runtime-output", str(exc))

    if network:
        if not email_config.ready:
            add("FAIL", "smtp-network", "email configuration is incomplete")
        else:
            try:
                result = SmtpTransport(email_config).check()
                add("PASS", "smtp-network", result["status"])
            except Exception as exc:
                add("FAIL", "smtp-network", type(exc).__name__)

    final = "FAIL" if any(item["status"] == "FAIL" for item in checks) else (
        "WARN" if any(item["status"] == "WARN" for item in checks) else "PASS"
    )
    if as_json:
        print(json.dumps({"status": final, "checks": checks}, indent=2))
    else:
        for item in checks:
            print(f"{item['status']:<4} {item['name']}: {item['detail']}")
        print(f"RESULT {final}")
    return 1 if final == "FAIL" else 0


def _delivery_exit_code(steps: list[dict[str, Any]]) -> int:
    statuses = {str(step.get("status", "")) for step in steps}
    if any(status.startswith(("FAILED", "RUNTIME_FAILED", "SEND_FAILED")) or status in {"ANALYSIS_MISSING", "UNSUPPORTED_MODE"} for status in statuses):
        return 1
    if any(status.startswith("BLOCKED") or status in {"EMAIL_CONFIG_MISSING", "EMAIL_ACTION_INVALID"} for status in statuses):
        return 2
    return 0


def main() -> int:
    args = parse_args()

    if args.mode == "doctor":
        return _run_doctor(network=args.network, as_json=args.json)

    if args.mode == "idx-daily":
        print("EQUITY_DOMAIN_DISABLED: active domain is crypto")
        return 2

    if args.mode == "manual-desk":
        if not args.query or not re.search(r"(?<!\w)OpenBagus(?!\w)", args.query):
            print(json.dumps({
                "status": "BLOCKED_MANUAL_TRIGGER",
                "reason": "manual-desk requires query with exact trigger 'OpenBagus'. Note: 'Open Bagus' is rejected.",
            }, indent=2))
            return 2

    started = _utc_now()
    steps = _run_refresh_and_analysis(args.mode)

    if any(s.get("status") == "FAILED_STOP" for s in steps):
        print(json.dumps({"status": "PIPELINE_FAILED", "steps": steps}, indent=2))
        return 1

    delivery_mode = "email" if args.mode in {"email", "macro-email"} else args.mode
    delivery_name = {
        "crypto-daily": "crypto_daily_report",
        "manual-desk": "manual_crypto_report",
        "email": "email_report",
    }[delivery_mode]
    try:
        delivery = run_final_delivery(
            mode=delivery_mode,
            query=args.query,
            dry_run=args.email_action != "send",
            confirmation=args.confirm_live_send,
            email_action=args.email_action,
            network_check=args.network,
            repo_root=REPO_ROOT,
        )
        steps.append({"step": delivery_name, "status": delivery.get("status", "OK"), "mode": delivery_mode})
        aggregate_delivery = {delivery_name: delivery}
    except Exception as exc:
        steps.append({"step": delivery_name, "status": "RUNTIME_FAILED", "mode": delivery_mode, "error": str(exc)[:220]})
        aggregate_delivery = {}

    live_email_sent = any(result.get("status") == "EMAIL_SENT" for result in aggregate_delivery.values())
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
        "send_mode": "LIVE_EMAIL" if live_email_sent else "NO_SEND_FILE_ONLY",
        "numeric_decision_core": "Python Quant Engine",
        "steps": steps,
        "delivery_status": aggregate_delivery,
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
    return _delivery_exit_code(steps)


if __name__ == "__main__":
    sys.exit(main())
