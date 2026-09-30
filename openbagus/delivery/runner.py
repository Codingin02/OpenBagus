"""OpenBagus Final Delivery Runtime.

Coordinates research outputs, brief rendering, safety scanning, and local outbox staging.
Default operation is strictly NO_SEND_FILE_ONLY.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root
from openbagus.delivery.adapters import LocalFileOutboxAdapter
from openbagus.delivery.channels import write_delivery_status
from openbagus.delivery.safety import scan_payload, scan_text
from openbagus.reporting.brief import render_crypto_brief, render_macro_brief
from openbagus.reporting.dashboard import PwaDashboardRenderer
from openbagus.reporting.email import render_email_report

ENGINE_VERSION = "openbagus.final_delivery_runtime.v2"
CONFIRMATION_PHRASE = "I_UNDERSTAND_THIS_SENDS_REAL_MESSAGES"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ManualQueryParser:
    """Parses manual triggers and validates trigger phrase 'OpenBagus'."""

    def __init__(self) -> None:
        self.crypto_tokens = {"BTC", "ETH", "SOL", "BTC/USD", "ETH/USD", "SOL/USD", "BITCOIN", "ETHEREUM", "SOLANA"}

    def parse(self, text: str) -> dict[str, Any]:
        blocked_reasons: list[str] = []
        if "OpenBagus" not in text:
            blocked_reasons.append("Manual query must contain exact trigger 'OpenBagus'.")
        if "Open Bagus" in text and "OpenBagus" not in text:
            blocked_reasons.append("Spaced trigger variant 'Open Bagus' is not permitted. Use 'OpenBagus'.")

        upper = text.upper()
        found_crypto = [token for token in self.crypto_tokens if token in upper]

        return {
            "trigger_ok": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "crypto_symbols": found_crypto,
            "is_crypto": len(found_crypto) > 0,
        }


class FinalDeliveryRuntime:
    """Coordinates final staging and delivery of OpenBagus intelligence reports."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.outbox = LocalFileOutboxAdapter(self.root / "reports/runtime/delivery")

    def run(
        self,
        *,
        mode: str,
        query: str | None = None,
        dry_run: bool = True,
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        gen_time = _utc_now()
        analysis_path = self.root / "reports/runtime/openbagus_real_analysis_latest.json"

        if not analysis_path.exists():
            status = {
                "engine_version": ENGINE_VERSION,
                "status": "ANALYSIS_MISSING",
                "mode": mode,
                "generated_at_utc": gen_time,
                "error": f"Required analysis file not found: {analysis_path}",
            }
            write_delivery_status(status)
            return status

        with analysis_path.open("r", encoding="utf-8") as f:
            analysis_payload = json.load(f)

        steps: list[dict[str, Any]] = []

        if mode in {"auto-crypto-daily", "crypto-daily"}:
            crypto_brief = render_crypto_brief(analysis_payload)
            safety = scan_text(crypto_brief)
            if not safety["passed"]:
                raise RuntimeError(f"Safety violations detected in crypto brief: {safety['findings']}")

            stage_res = self.outbox.stage("WA_02_AUTO_CRYPTO_DAILY", crypto_brief, extension="md")
            steps.append(stage_res)

        elif mode == "macro-email":
            email_payload = render_email_report(analysis_payload)
            safety = scan_text(email_payload["html"])
            if not safety["passed"]:
                raise RuntimeError(f"Safety violations in email HTML: {safety['findings']}")

            stage_res = self.outbox.stage("EMAIL_MACRO_DAILY", email_payload["html"], extension="html")
            steps.append(stage_res)

        elif mode == "app-alert":
            alert_data = {
                "platform": "OpenBagus",
                "timestamp": gen_time,
                "alert": "OpenBagus daily crypto cycle executed successfully.",
                "status": analysis_payload.get("data_freshness_summary", {}).get("overall_analysis_status", "OK"),
            }
            stage_res = self.outbox.stage("APP_ALERT", json.dumps(alert_data, indent=2), extension="json")
            steps.append(stage_res)

        elif mode in {"app-dashboard", "dashboard"}:
            dash_res = PwaDashboardRenderer(self.root).write(
                runtime={"analysis": analysis_payload},
                reports={},
                delivery_status={"status": "OK", "timestamp": gen_time},
            )
            steps.append(dash_res)

        elif mode in {"manual-crypto", "manual-desk"}:
            parser = ManualQueryParser()
            parse_res = parser.parse(query or "")
            if not parse_res["trigger_ok"]:
                status = {
                    "engine_version": ENGINE_VERSION,
                    "status": "TRIGGER_BLOCKED",
                    "mode": mode,
                    "blocked_reasons": parse_res["blocked_reasons"],
                    "generated_at_utc": gen_time,
                }
                write_delivery_status(status)
                return status

            # Generate responsive crypto manual brief
            brief = render_crypto_brief(analysis_payload)
            stage_res = self.outbox.stage("MANUAL_CRYPTO_RESPONSE", brief, extension="md")
            steps.append(stage_res)

        status_payload = {
            "engine_version": ENGINE_VERSION,
            "status": "DELIVERY_STAGED_SUCCESS",
            "mode": mode,
            "send_mode": "NO_SEND_FILE_ONLY",
            "dry_run": dry_run,
            "generated_at_utc": gen_time,
            "steps": steps,
        }
        write_delivery_status(status_payload)
        return status_payload


def run_final_delivery(
    *,
    mode: str,
    query: str | None = None,
    dry_run: bool = True,
    confirmation: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Convenience functional wrapper for FinalDeliveryRuntime."""
    runner = FinalDeliveryRuntime(repo_root=repo_root)
    return runner.run(mode=mode, query=query, dry_run=dry_run, confirmation=confirmation)
