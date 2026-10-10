"""Local staging and official external delivery adapters."""

from __future__ import annotations

import json
from html import escape
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus.core.env import RuntimeEnv, get_repo_root


class LocalFileOutboxAdapter:
    """Safely stages messages to local files without external network transmission."""

    def __init__(self, outbox_dir: Path | None = None) -> None:
        self.outbox_dir = outbox_dir or get_repo_root() / "reports/runtime/delivery"
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, channel_name: str, content: str, extension: str = "md") -> dict[str, Any]:
        file_path = self.outbox_dir / f"{channel_name}_latest.{extension}"
        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)
        return {
            "status": "STAGED_LOCAL_FILE",
            "channel": channel_name,
            "path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
        }


def render_research_delivery(quant: Any, packet: Any, *, include_sources: bool = False) -> dict[str, str]:
    def price(value: Any) -> str:
        prefix = "Rp" if getattr(packet, "currency", "USD") == "IDR" else "$"
        return "N/A" if value is None else prefix + f"{float(value):,.8f}".rstrip("0").rstrip(".")

    reason = str(getattr(packet, "decision_reason", "") or getattr(quant, "decision_reason", "") or "Data belum cukup untuk tesis yang lebih kuat.")
    narrative = str(getattr(packet, "narrative", "") or getattr(quant, "narrative", "") or "").strip()
    lines = [
        f"OpenBagus - {quant.asset} - {quant.timeframe}", "",
        f"Decision: {quant.decision}", f"Price: {price(quant.price)}", f"Market: {getattr(packet, 'market', quant.market)}",
        f"Updated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Market data as-of: {getattr(packet, 'price_as_of', '') or 'UNVERIFIED'} | Freshness: {getattr(packet, 'data_freshness', 'UNVERIFIED')}",
        f"Reason: {reason}",
    ]
    if narrative and narrative != reason:
        lines.extend([f"View: {narrative}", ""])
    else:
        lines.append("")
    for label, scenario in (("Bullish", getattr(quant, "bullish_validation", None)), ("Bearish", getattr(quant, "bearish_validation", None))):
        if scenario:
            lines.extend([
                f"{label}: {scenario.trigger_condition}",
                f"Entry {scenario.entry_zone} | Stop {price(scenario.stop_price)} | TP1 {price(scenario.tp1)} | R:R {scenario.reward_risk_str}",
            ])
    if include_sources and getattr(packet, "sources", None):
        lines.extend(["", "Sources: " + ", ".join(packet.sources)])
    lines.extend(["", "Research-only. No broker or exchange order is executed."])
    text = "\n".join(lines)
    html = "<html><body><pre style=\"font-family:Arial,sans-serif;white-space:pre-wrap\">" + escape(text) + "</pre></body></html>"
    whatsapp = "\n".join(line for line in lines if line)[:3500]
    return {
        "subject": f"OpenBagus · {quant.asset} · {quant.timeframe} · {quant.decision}",
        "text": text,
        "html": html,
        "whatsapp": whatsapp,
    }


@dataclass(frozen=True)
class WhatsAppCloudConfig:
    enabled: bool
    access_token: str | None
    phone_number_id: str | None
    recipient: str | None
    graph_version: str = "v26.0"
    waba_id: str | None = None
    template_name: str | None = None
    template_language: str = "en_US"

    @classmethod
    def from_runtime_env(cls, runtime_env: RuntimeEnv) -> "WhatsAppCloudConfig":
        enabled = (runtime_env.get("OPENBAGUS_WHATSAPP_ENABLED", "false") or "false").lower() in {"1", "true", "yes", "on"}
        return cls(
            enabled=enabled,
            access_token=runtime_env.get("OPENBAGUS_WHATSAPP_ACCESS_TOKEN"),
            phone_number_id=runtime_env.get("OPENBAGUS_WHATSAPP_PHONE_NUMBER_ID"),
            recipient=runtime_env.get("OPENBAGUS_WHATSAPP_RECIPIENT"),
            graph_version=runtime_env.get("OPENBAGUS_WHATSAPP_GRAPH_VERSION", "v26.0") or "v26.0",
            waba_id=runtime_env.get("OPENBAGUS_WHATSAPP_WABA_ID"),
            template_name=runtime_env.get("OPENBAGUS_WHATSAPP_TEMPLATE_NAME"),
            template_language=runtime_env.get("OPENBAGUS_WHATSAPP_TEMPLATE_LANGUAGE", "en_US") or "en_US",
        )

    @property
    def errors(self) -> tuple[str, ...]:
        errors = []
        if not self.graph_version.startswith("v") or not self.graph_version[1:].replace(".", "").isdigit():
            errors.append("OPENBAGUS_WHATSAPP_GRAPH_VERSION is invalid")
        if self.phone_number_id and not self.phone_number_id.isdigit():
            errors.append("OPENBAGUS_WHATSAPP_PHONE_NUMBER_ID must be numeric")
        if self.recipient and not self.recipient.lstrip("+").isdigit():
            errors.append("OPENBAGUS_WHATSAPP_RECIPIENT must be an international phone number")
        return tuple(errors)

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.access_token and self.phone_number_id and self.recipient) and not self.errors

    def status(self) -> dict[str, Any]:
        return {
            "status": "READY" if self.ready else "INVALID" if self.errors else "NOT_CONFIGURED",
            "enabled": self.enabled,
            "token_present": bool(self.access_token),
            "phone_number_id_present": bool(self.phone_number_id),
            "recipient_present": bool(self.recipient),
            "graph_version": self.graph_version,
            "template_present": bool(self.template_name),
            "errors": list(self.errors),
        }


class WhatsAppCloudTransport:
    """Official Meta WhatsApp Cloud API transport."""

    def __init__(self, config: WhatsAppCloudConfig, timeout: float = 15.0) -> None:
        self.config = config
        self.timeout = timeout

    def _request(self, url: str, *, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.config.access_token}", "Content-Type": "application/json"}
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers=headers, method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                body = {}
            return exc.code, body

    def validate(self) -> dict[str, Any]:
        if not self.config.access_token or not self.config.phone_number_id or self.config.errors:
            return {"status": "INVALID"}
        url = f"https://graph.facebook.com/{self.config.graph_version}/{self.config.phone_number_id}?fields=id,display_phone_number,verified_name"
        try:
            status, body = self._request(url)
        except (OSError, urllib.error.URLError):
            return {"status": "UNREACHABLE"}
        return {"status": "VALID" if status == 200 and str(body.get("id")) == self.config.phone_number_id else "INVALID"}

    def send(self, text: str, *, use_template: bool = False) -> dict[str, Any]:
        if not self.config.ready:
            return {"status": "WHATSAPP_NOT_CONFIGURED"}
        if use_template:
            if not self.config.template_name:
                return {"status": "WHATSAPP_TEMPLATE_REQUIRED"}
            message = {
                "messaging_product": "whatsapp", "to": self.config.recipient, "type": "template",
                "template": {"name": self.config.template_name, "language": {"code": self.config.template_language}},
            }
        else:
            message = {"messaging_product": "whatsapp", "to": self.config.recipient, "type": "text", "text": {"body": text}}
        url = f"https://graph.facebook.com/{self.config.graph_version}/{self.config.phone_number_id}/messages"
        try:
            status, body = self._request(url, payload=message)
        except (OSError, urllib.error.URLError):
            return {"status": "WHATSAPP_SEND_FAILED", "error_type": "NetworkError"}
        if status in {200, 201} and body.get("messages"):
            return {"status": "WHATSAPP_SENT"}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if error.get("code") in {131047, 131051, 132001}:
            return {"status": "WHATSAPP_TEMPLATE_REQUIRED"}
        return {"status": "WHATSAPP_SEND_FAILED", "error_type": "HTTPError", "http_status": status}
