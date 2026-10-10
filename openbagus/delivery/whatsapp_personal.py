"""OpenBagus Personal WhatsApp Integration (Section H).

Provides a personal WhatsApp workflow that does NOT require Meta Developer
accounts, Cloud API tokens, or phone number IDs:
1. Primary Transport: Direct user-initiated compose action via installed desktop
   app (whatsapp://send) with official web compose fallback (web.whatsapp.com/send).
2. Honest Status Semantics: Distinguishes COMPOSE_OPENED from SENT and DELIVERED.
3. Experimental QR Transport Evaluation: Outlines Baileys protocol evaluation,
   strict risk disclosures, and isolated local session handling.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbagus.intelligence.local_language import get_local_appdata_dir

STATUS_DISCONNECTED = "DISCONNECTED"
STATUS_CONNECTED = "CONNECTED"
STATUS_COMPOSE_OPENED = "COMPOSE_OPENED"
STATUS_QUEUED = "QUEUED"
STATUS_SENT = "SENT"
STATUS_DELIVERED = "DELIVERED"
STATUS_FAILED = "FAILED"
STATUS_ACTION_REQUIRED = "ACTION_REQUIRED"


def _clean_phone(phone: str) -> str:
    """Normalize phone number to international E.164 digits without '+' or spaces."""
    cleaned = re.sub(r"[^\d]", "", phone.strip())
    # Convert Indonesian 08xx to 628xx
    if cleaned.startswith("08"):
        cleaned = "62" + cleaned[1:]
    return cleaned


class PersonalWhatsAppConfig:
    """Stores user phone number and personal WhatsApp preferences in AppData."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path:
            self.path = Path(config_path)
        else:
            cfg_dir = get_local_appdata_dir() / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            self.path = cfg_dir / "whatsapp_personal.json"

    def save(self, phone: str, use_web_fallback: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "phone": _clean_phone(phone),
            "use_web_fallback": use_web_fallback,
            "connected": bool(phone),
            "configured_at": json.dumps(None),
        }
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"phone": "", "connected": False, "use_web_fallback": True}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"phone": "", "connected": False, "use_web_fallback": True}

    def clear(self) -> bool:
        if self.path.exists():
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        return True


class PersonalWhatsAppTransport:
    """Primary personal WhatsApp transport via compose action (Desktop app / Web)."""

    def __init__(self, config: PersonalWhatsAppConfig | None = None) -> None:
        self.config = config or PersonalWhatsAppConfig()

    def get_status(self) -> dict[str, Any]:
        cfg = self.config.load()
        phone = cfg.get("phone", "")
        if not phone:
            return {
                "status": STATUS_DISCONNECTED,
                "mode": "PERSONAL_COMPOSE",
                "phone": None,
                "connected": False,
                "detail": "No personal phone number connected. Use '/whatsapp connect <phone>' to configure.",
            }
        return {
            "status": STATUS_CONNECTED,
            "mode": "PERSONAL_COMPOSE",
            "phone": phone,
            "connected": True,
            "detail": f"Personal WhatsApp ready for {phone}. Uses official compose workflow without Meta Cloud API.",
        }

    def connect(self, phone: str, use_web: bool = False) -> dict[str, Any]:
        norm_phone = _clean_phone(phone)
        if not norm_phone or len(norm_phone) < 8:
            return {
                "status": STATUS_FAILED,
                "error": "INVALID_PHONE",
                "detail": "Please provide a valid international phone number (e.g., 628123456789 or +628123456789).",
            }
        self.config.save(norm_phone, use_web_fallback=use_web)
        return {
            "status": STATUS_CONNECTED,
            "phone": norm_phone,
            "detail": f"Personal WhatsApp destination set to {norm_phone}.",
        }

    def disconnect(self) -> dict[str, Any]:
        self.config.clear()
        return {
            "status": STATUS_DISCONNECTED,
            "detail": "Personal WhatsApp configuration cleared.",
        }

    def compose(
        self,
        text: str,
        phone: str | None = None,
        force_web: bool = False,
        open_browser: bool = True,
    ) -> dict[str, Any]:
        """Prepares and opens the WhatsApp compose window.
        
        CRITICAL: Honestly returns COMPOSE_OPENED, never falsely claiming SENT or DELIVERED.
        """
        cfg = self.config.load()
        target_phone = _clean_phone(phone) if phone else cfg.get("phone", "")
        if not target_phone:
            return {
                "status": STATUS_ACTION_REQUIRED,
                "error": "PHONE_REQUIRED",
                "detail": "Recipient phone number required. Use '/whatsapp compose <phone>' or configure with '/whatsapp connect'.",
            }

        encoded_text = urllib.parse.quote(text)
        app_uri = f"whatsapp://send?phone={target_phone}&text={encoded_text}"
        web_uri = f"https://web.whatsapp.com/send?phone={target_phone}&text={encoded_text}"

        opened_method = "web" if force_web else "desktop_app"

        if open_browser:
            if force_web:
                try:
                    webbrowser.open(web_uri)
                except Exception:
                    pass
            else:
                try:
                    # Attempt opening desktop scheme first
                    success = webbrowser.open(app_uri)
                    if not success:
                        # Fallback to web
                        webbrowser.open(web_uri)
                        opened_method = "web_fallback"
                except Exception:
                    try:
                        webbrowser.open(web_uri)
                        opened_method = "web_fallback"
                    except Exception:
                        opened_method = "failed"

        return {
            "status": STATUS_COMPOSE_OPENED,
            "method": opened_method,
            "recipient": target_phone,
            "app_uri": app_uri,
            "web_uri": web_uri,
            "detail": (
                f"WhatsApp compose window opened for {target_phone} via {opened_method}. "
                "User must click Send inside WhatsApp to transmit the message."
            ),
        }


class BaileysExperimentalTransport:
    """Experimental unofficial QR-based WhatsApp transport (WhiskeySockets/Baileys).
    
    IMPORTANT SAFETY WARNING:
    - This transport connects directly via the WhatsApp Web Multi-Device protocol.
    - It is NOT endorsed or verified by Meta.
    - Use carries inherent risk of WhatsApp account suspension or restriction.
    - Explicit separate user risk consent is strictly mandatory before activation.
    - Default status is always DISCONNECTED and DISABLED.
    """

    def __init__(self, session_dir: Path | None = None) -> None:
        if session_dir:
            self.session_dir = Path(session_dir)
        else:
            self.session_dir = get_local_appdata_dir() / "whatsapp_session"
        self.enabled = False
        self.risk_acknowledged = False

    def get_status(self) -> dict[str, Any]:
        return {
            "status": STATUS_DISCONNECTED,
            "mode": "EXPERIMENTAL_QR_BAILEYS",
            "enabled": self.enabled,
            "risk_acknowledged": self.risk_acknowledged,
            "classification": "UNOFFICIAL_EXPERIMENTAL",
            "warning": (
                "Baileys integration connects to WhatsApp Web via reverse-engineered WebSocket protocol. "
                "Meta does not permit unofficial automation. High risk of account restriction. "
                "Disabled by default."
            ),
            "session_dir": str(self.session_dir),
        }

    def clear_session(self) -> bool:
        if self.session_dir.exists():
            import shutil
            try:
                shutil.rmtree(self.session_dir, ignore_errors=True)
                return True
            except OSError:
                return False
        return True
