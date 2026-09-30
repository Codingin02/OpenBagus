"""OpenBagus Final Delivery Runtime.

Coordinates research outputs, brief rendering, safety scanning, and local outbox staging.
Default operation is strictly NO_SEND_FILE_ONLY.
"""

from __future__ import annotations

import json
import re
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import RuntimeEnv, get_repo_root
from openbagus.delivery.adapters import LocalFileOutboxAdapter
from openbagus.delivery.channels import write_delivery_status
from openbagus.delivery.mailbox import (
    EMAIL_CONFIRMATION_PHRASE,
    SmtpConfig,
    SmtpTransport,
    build_email_message,
    write_eml,
)
from openbagus.delivery.safety import scan_payload, scan_text
from openbagus.reporting.brief import render_crypto_brief
from openbagus.reporting.dashboard import PwaDashboardRenderer
from openbagus.reporting.email import render_email_report
from openbagus.reporting.pdf import render_pdf_report

ENGINE_VERSION = "openbagus.final_delivery_runtime.v2"
CONFIRMATION_PHRASE = EMAIL_CONFIRMATION_PHRASE


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ManualQueryParser:
    """Parses manual triggers and validates trigger phrase 'OpenBagus'."""

    def __init__(self) -> None:
        self.crypto_tokens = {"BTC", "ETH", "SOL", "BTC/USD", "ETH/USD", "SOL/USD", "BITCOIN", "ETHEREUM", "SOLANA"}

    def parse(self, text: str) -> dict[str, Any]:
        blocked_reasons: list[str] = []
        if not re.search(r"(?<!\w)OpenBagus(?!\w)", text):
            blocked_reasons.append("Manual query must contain exact trigger 'OpenBagus'.")
        if "Open Bagus" in text and not re.search(r"(?<!\w)OpenBagus(?!\w)", text):
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
        email_action: str = "draft",
        network_check: bool = False,
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
            write_delivery_status(status, self.root / "reports/runtime/delivery/delivery_status_latest.json")
            return status

        with analysis_path.open("r", encoding="utf-8") as f:
            analysis_payload = json.load(f)

        steps: list[dict[str, Any]] = []

        if mode in {"auto-crypto-daily", "crypto-daily"}:
            crypto_brief = render_crypto_brief(analysis_payload)
            safety = scan_text(crypto_brief)
            if not safety["passed"]:
                raise RuntimeError(f"Safety violations detected in crypto brief: {safety['findings']}")

            stage_res = self.outbox.stage("CRYPTO_DAILY_BRIEF", crypto_brief, extension="md")
            steps.append(stage_res)

        elif mode in {"macro-email", "email"}:
            return self._run_email(
                analysis_payload,
                action=email_action,
                confirmation=confirmation,
                network_check=network_check,
                dry_run=dry_run,
                generated_at=gen_time,
            )

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
                write_delivery_status(status, self.root / "reports/runtime/delivery/delivery_status_latest.json")
                return status

            # Generate responsive crypto manual brief
            brief = render_crypto_brief(analysis_payload)
            stage_res = self.outbox.stage("MANUAL_CRYPTO_RESPONSE", brief, extension="md")
            steps.append(stage_res)

        else:
            status = {
                "engine_version": ENGINE_VERSION,
                "status": "UNSUPPORTED_MODE",
                "mode": mode,
                "generated_at_utc": gen_time,
            }
            write_delivery_status(status, self.root / "reports/runtime/delivery/delivery_status_latest.json")
            return status

        status_payload = {
            "engine_version": ENGINE_VERSION,
            "status": "DELIVERY_STAGED_SUCCESS",
            "mode": mode,
            "send_mode": "NO_SEND_FILE_ONLY",
            "dry_run": dry_run,
            "generated_at_utc": gen_time,
            "steps": steps,
        }
        write_delivery_status(status_payload, self.root / "reports/runtime/delivery/delivery_status_latest.json")
        return status_payload

    def _run_email(
        self,
        analysis_payload: Mapping[str, Any],
        *,
        action: str,
        confirmation: str | None,
        network_check: bool,
        dry_run: bool,
        generated_at: str,
    ) -> dict[str, Any]:
        if action not in {"draft", "check", "send"}:
            return self._write_email_status("EMAIL_ACTION_INVALID", action, generated_at)

        rendered = render_email_report(analysis_payload)
        safety = scan_payload(rendered)
        if not safety["passed"]:
            return self._write_email_status("BLOCKED_COMPLIANCE", action, generated_at, findings=safety["findings"])

        attachment = render_pdf_report(
            analysis_payload,
            self.outbox.outbox_dir / "EMAIL_MACRO_DAILY_report_latest.html",
        )
        runtime_env = RuntimeEnv(self.root)
        config = SmtpConfig.from_runtime_env(runtime_env)
        message = build_email_message(
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            config=config,
            attachments=(attachment,),
        )

        text_result = self.outbox.stage("EMAIL_MACRO_DAILY", rendered["text"], extension="txt")
        html_result = self.outbox.stage("EMAIL_MACRO_DAILY", rendered["html"], extension="html")
        eml_path = write_eml(message, self.outbox.outbox_dir / "EMAIL_MACRO_DAILY_latest.eml")
        artifacts = {
            "text": text_result["path"],
            "html": html_result["path"],
            "eml": str(eml_path),
            "attachment": str(attachment),
            "attachment_type": "text/html",
        }

        if action == "draft":
            return self._write_email_status(
                "EMAIL_DRAFT_READY",
                action,
                generated_at,
                config=config.status(),
                artifacts=artifacts,
            )

        if action == "send" and dry_run:
            return self._write_email_status(
                "BLOCKED_DRY_RUN", action, generated_at, config=config.status(), artifacts=artifacts
            )

        if not config.ready:
            return self._write_email_status(
                "EMAIL_CONFIG_MISSING",
                action,
                generated_at,
                config=config.status(),
                artifacts=artifacts,
            )

        if action == "check" and not network_check:
            return self._write_email_status(
                "EMAIL_CONFIG_READY",
                action,
                generated_at,
                config=config.status(),
                artifacts=artifacts,
                message_sent=False,
            )

        try:
            transport = SmtpTransport(config)
            if action == "check":
                result = transport.check()
            else:
                live_enabled = (runtime_env.get("OPENBAGUS_EMAIL_LIVE_ENABLED", "false") or "false").lower() in {
                    "1", "true", "yes", "on"
                }
                if not live_enabled:
                    return self._write_email_status(
                        "BLOCKED_LIVE_EMAIL_NOT_ENABLED", action, generated_at, config=config.status(), artifacts=artifacts
                    )
                if confirmation != EMAIL_CONFIRMATION_PHRASE:
                    return self._write_email_status(
                        "BLOCKED_MISSING_CONFIRMATION", action, generated_at, config=config.status(), artifacts=artifacts
                    )
                result = transport.send(message)
        except smtplib.SMTPAuthenticationError:
            return self._write_email_status(
                "SEND_FAILED_EMAIL_AUTH", action, generated_at, config=config.status(), artifacts=artifacts
            )
        except (OSError, smtplib.SMTPException) as exc:
            return self._write_email_status(
                "SEND_FAILED_EMAIL_NETWORK",
                action,
                generated_at,
                config=config.status(),
                artifacts=artifacts,
                error_type=type(exc).__name__,
            )

        return self._write_email_status(
            result["status"],
            action,
            generated_at,
            config=config.status(),
            artifacts=artifacts,
            message_sent=result["message_sent"],
        )

    def _write_email_status(self, status: str, action: str, generated_at: str, **details: Any) -> dict[str, Any]:
        payload = {
            "engine_version": ENGINE_VERSION,
            "status": status,
            "mode": "email",
            "action": action,
            "send_mode": "LIVE_EMAIL" if status == "EMAIL_SENT" else "NO_SEND_FILE_ONLY",
            "generated_at_utc": generated_at,
            **details,
        }
        write_delivery_status(payload, self.root / "reports/runtime/delivery/delivery_status_latest.json")
        return payload


def run_final_delivery(
    *,
    mode: str,
    query: str | None = None,
    dry_run: bool = True,
    confirmation: str | None = None,
    email_action: str = "draft",
    network_check: bool = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Convenience functional wrapper for FinalDeliveryRuntime."""
    runner = FinalDeliveryRuntime(repo_root=repo_root)
    return runner.run(
        mode=mode,
        query=query,
        dry_run=dry_run,
        confirmation=confirmation,
        email_action=email_action,
        network_check=network_check,
    )
