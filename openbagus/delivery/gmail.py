"""OpenBagus Official Gmail API Delivery via Google OAuth 2.0 Desktop Flow.

Implements secure, official user-authorized Gmail delivery (Section G):
- Minimum necessary scope: https://www.googleapis.com/auth/gmail.send
- Desktop loopback authorization receiver (http://127.0.0.1:PORT/callback)
- Secure token storage with Windows DPAPI protection
- Automatic token refresh & revocation
- RFC 2822 MIME message formatting & base64url payload delivery
- Zero credentials or tokens exposed in logs
"""

from __future__ import annotations

import base64
import email.message
import http.server
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from openbagus.core.env import get_repo_root
from openbagus.intelligence.local_language import get_local_appdata_dir
from openbagus.storage.data_control import decrypt_secret_dpapi, encrypt_secret_dpapi

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GMAIL_SEND_API = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_PROFILE_API = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


@dataclass
class GmailOAuthConfig:
    client_id: str
    client_secret: str
    configured: bool = True

    @classmethod
    def load(cls, repo_root: Path | None = None) -> GmailOAuthConfig:
        # 1. Environment variables
        cid = os.environ.get("OPENBAGUS_GOOGLE_CLIENT_ID", "").strip()
        csec = os.environ.get("OPENBAGUS_GOOGLE_CLIENT_SECRET", "").strip()
        if cid and csec:
            return cls(client_id=cid, client_secret=csec, configured=True)

        # 2. Local AppData config
        appdata_cfg = get_local_appdata_dir() / "config/gmail_client.json"
        if appdata_cfg.exists():
            try:
                data = json.loads(appdata_cfg.read_text(encoding="utf-8"))
                c = data.get("installed") or data.get("web") or data
                cid = c.get("client_id", "").strip()
                csec = c.get("client_secret", "").strip()
                if cid and csec:
                    return cls(client_id=cid, client_secret=csec, configured=True)
            except Exception:
                pass

        # 3. Repository config
        root = repo_root or get_repo_root()
        repo_cfg = root / "config/openbagus_gmail.json"
        if repo_cfg.exists():
            try:
                data = json.loads(repo_cfg.read_text(encoding="utf-8"))
                c = data.get("installed") or data.get("web") or data
                cid = c.get("client_id", "").strip()
                csec = c.get("client_secret", "").strip()
                if cid and csec:
                    return cls(client_id=cid, client_secret=csec, configured=True)
            except Exception:
                pass

        return cls(client_id="", client_secret="", configured=False)


class GmailTokenStore:
    """Manages DPAPI-protected OAuth tokens in %LOCALAPPDATA%\\OpenBagus\\config\\gmail_token.json."""

    def __init__(self, token_path: Path | None = None) -> None:
        if token_path:
            self.path = Path(token_path)
        else:
            cfg_dir = get_local_appdata_dir() / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            self.path = cfg_dir / "gmail_token.json"

    def save(self, token_data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Encrypt refresh_token and access_token using DPAPI
        protected_data = dict(token_data)
        if "refresh_token" in protected_data and protected_data["refresh_token"]:
            protected_data["refresh_token"] = encrypt_secret_dpapi(str(protected_data["refresh_token"]))
        if "access_token" in protected_data and protected_data["access_token"]:
            protected_data["access_token"] = encrypt_secret_dpapi(str(protected_data["access_token"]))
        self.path.write_text(json.dumps(protected_data, indent=2), encoding="utf-8")

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if "refresh_token" in raw and raw["refresh_token"]:
                raw["refresh_token"] = decrypt_secret_dpapi(str(raw["refresh_token"]))
            if "access_token" in raw and raw["access_token"]:
                raw["access_token"] = decrypt_secret_dpapi(str(raw["access_token"]))
            return raw
        except Exception:
            return None

    def clear(self) -> bool:
        if self.path.exists():
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        return True


class OAuthLoopbackReceiver(http.server.HTTPServer):
    """Temporary local HTTP loopback server to catch OAuth callback."""

    def __init__(self, port: int = 0) -> None:
        self.auth_code: str | None = None
        self.error: str | None = None

        handler = self._make_handler()
        super().__init__(("127.0.0.1", port), handler)

    def _make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Suppress HTTP server logging

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)

                if "code" in params:
                    receiver.auth_code = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    html = (
                        "<html><body style='font-family:sans-serif;text-align:center;padding:40px;'>"
                        "<h2 style='color:#16a34a;'>Otorisasi OpenBagus Berhasil!</h2>"
                        "<p>Akun Gmail Anda telah terhubung. Anda dapat menutup tab ini dan kembali ke terminal OpenBagus.</p>"
                        "</body></html>"
                    )
                    self.wfile.write(html.encode("utf-8"))
                else:
                    receiver.error = params.get("error", ["authorization_denied"])[0]
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    html = (
                        "<html><body style='font-family:sans-serif;text-align:center;padding:40px;'>"
                        "<h2 style='color:#dc2626;'>Otorisasi Gagal atau Dibatalkan</h2>"
                        f"<p>Alasan: {receiver.error}. Anda dapat menutup tab ini.</p>"
                        "</body></html>"
                    )
                    self.wfile.write(html.encode("utf-8"))

        return Handler


class GmailOAuthTransport:
    """Official Gmail API transport with OAuth 2.0 loopback authorization."""

    def __init__(
        self,
        config: GmailOAuthConfig | None = None,
        token_store: GmailTokenStore | None = None,
        http_fetcher: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or GmailOAuthConfig.load()
        self.token_store = token_store or GmailTokenStore()
        self._fetcher = http_fetcher

    def _http_post_json(self, url: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        if self._fetcher is not None:
            return self._fetcher("POST", url, data, headers or {})

        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded_data, headers=headers or {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = {}
            return exc.code, body
        except (urllib.error.URLError, OSError) as exc:
            return 503, {"error": "network_error", "detail": str(exc)}

    def _http_get_json(self, url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if self._fetcher is not None:
            return self._fetcher("GET", url, None, headers)

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = {}
            return exc.code, body
        except (urllib.error.URLError, OSError) as exc:
            return 503, {"error": "network_error", "detail": str(exc)}

    def is_configured(self) -> bool:
        return self.config.configured and bool(self.config.client_id and self.config.client_secret)

    def is_connected(self) -> bool:
        tokens = self.token_store.load()
        return bool(tokens and (tokens.get("refresh_token") or tokens.get("access_token")))

    def get_status(self) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "status": "NOT_CONFIGURED",
                "client_configured": False,
                "connected": False,
                "email": None,
                "scope": GMAIL_SEND_SCOPE,
                "detail": (
                    "Google OAuth 2.0 Client credentials not configured. "
                    "Set OPENBAGUS_GOOGLE_CLIENT_ID and OPENBAGUS_GOOGLE_CLIENT_SECRET or place in config/openbagus_gmail.json."
                ),
            }

        tokens = self.token_store.load()
        if not tokens:
            return {
                "status": "DISCONNECTED",
                "client_configured": True,
                "connected": False,
                "email": None,
                "scope": GMAIL_SEND_SCOPE,
                "detail": "No authorized account. Run '/gmail connect' to authorize.",
            }

        expires_at = tokens.get("expires_at", 0)
        now = time.time()
        is_token_expired = now >= expires_at
        user_email = tokens.get("email") or "Connected User"

        return {
            "status": "CONNECTED",
            "client_configured": True,
            "connected": True,
            "email": user_email,
            "scope": tokens.get("scope", GMAIL_SEND_SCOPE),
            "access_token_expired": is_token_expired,
            "expires_in_seconds": max(0, int(expires_at - now)),
            "detail": f"Account {user_email} connected with {GMAIL_SEND_SCOPE} permission.",
        }

    def connect(self, open_browser: bool = True, timeout_seconds: float = 120.0) -> dict[str, Any]:
        """Runs desktop OAuth loopback authorization flow."""
        if not self.is_configured():
            return {
                "status": "FAILED",
                "reason": "SETUP_DEPENDENCY_REQUIRED",
                "detail": (
                    "Google OAuth Client ID & Secret are required. "
                    "Set OPENBAGUS_GOOGLE_CLIENT_ID & OPENBAGUS_GOOGLE_CLIENT_SECRET in environment or config/openbagus_gmail.json."
                ),
            }

        server = OAuthLoopbackReceiver(port=0)
        port = server.server_port
        redirect_uri = f"http://127.0.0.1:{port}/callback"

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SEND_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

        if open_browser:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass

        # Run loopback server in separate thread
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.daemon = True
        server_thread.start()

        # Wait for callback
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if server.auth_code or server.error:
                break
            time.sleep(0.5)

        try:
            server.server_close()
        except Exception:
            pass

        if server.error:
            return {"status": "FAILED", "reason": "USER_DENIED", "detail": f"Authorization error: {server.error}"}

        if not server.auth_code:
            return {"status": "FAILED", "reason": "TIMEOUT", "detail": f"Authorization timed out after {timeout_seconds}s."}

        # Exchange code for tokens
        token_payload = {
            "code": server.auth_code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        status_code, token_resp = self._http_post_json(GOOGLE_TOKEN_ENDPOINT, token_payload)
        if status_code != 200 or "access_token" not in token_resp:
            err = token_resp.get("error_description") or token_resp.get("error") or f"HTTP {status_code}"
            return {"status": "FAILED", "reason": "TOKEN_EXCHANGE_FAILED", "detail": str(err)}

        access_token = token_resp["access_token"]
        refresh_token = token_resp.get("refresh_token")
        expires_in = token_resp.get("expires_in", 3600)
        expires_at = time.time() + float(expires_in)

        # Retrieve verified email address via profile endpoint
        user_email = ""
        p_status, p_body = self._http_get_json(GMAIL_PROFILE_API, {"Authorization": f"Bearer {access_token}"})
        if p_status == 200 and "emailAddress" in p_body:
            user_email = p_body["emailAddress"]

        token_record = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "email": user_email,
            "scope": token_resp.get("scope", GMAIL_SEND_SCOPE),
            "authorized_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.token_store.save(token_record)

        return {
            "status": "SUCCESS",
            "email": user_email,
            "scope": GMAIL_SEND_SCOPE,
            "detail": f"Successfully authorized account {user_email or 'Gmail'} with scope {GMAIL_SEND_SCOPE}.",
        }

    def ensure_access_token(self) -> str | None:
        """Returns a valid access token, automatically refreshing via refresh_token if expired."""
        tokens = self.token_store.load()
        if not tokens:
            return None

        now = time.time()
        access_token = tokens.get("access_token")
        expires_at = tokens.get("expires_at", 0)

        # Buffer: refresh if expiring within 60 seconds
        if access_token and (expires_at - now > 60.0):
            return access_token

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            return access_token if access_token else None

        # Request new token using refresh_token
        refresh_payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        status_code, token_resp = self._http_post_json(GOOGLE_TOKEN_ENDPOINT, refresh_payload)
        if status_code == 200 and "access_token" in token_resp:
            new_access_token = token_resp["access_token"]
            expires_in = token_resp.get("expires_in", 3600)
            tokens["access_token"] = new_access_token
            tokens["expires_at"] = now + float(expires_in)
            if "refresh_token" in token_resp:
                tokens["refresh_token"] = token_resp["refresh_token"]
            self.token_store.save(tokens)
            return new_access_token

        return None

    def disconnect(self) -> dict[str, Any]:
        """Revokes token and clears local token store."""
        tokens = self.token_store.load()
        user_email = tokens.get("email") if tokens else None
        if tokens:
            tok = tokens.get("refresh_token") or tokens.get("access_token")
            if tok:
                try:
                    self._http_post_json(GOOGLE_REVOKE_ENDPOINT, {"token": tok})
                except Exception:
                    pass
        self.token_store.clear()
        return {"status": "DISCONNECTED", "email": user_email, "detail": "Gmail authorization revoked and local credentials deleted."}

    def send_message(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        attachments: list[Path] | None = None,
    ) -> dict[str, Any]:
        """Sends an email via Gmail REST API using the user-authorized access token."""
        token = self.ensure_access_token()
        if not token:
            return {
                "status": "FAILED",
                "error": "NOT_AUTHORIZED",
                "detail": "Gmail is not connected or token refresh failed. Run '/gmail connect'.",
            }

        # Build RFC 2822 / MIME Message
        msg = email.message.EmailMessage()
        msg["Subject"] = subject
        tokens = self.token_store.load() or {}
        sender = tokens.get("email") or "me"
        msg["From"] = sender
        msg["To"] = recipient

        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        # Attachments
        if attachments:
            for att_path in attachments:
                if att_path.exists():
                    try:
                        data = att_path.read_bytes()
                        msg.add_attachment(
                            data,
                            maintype="application",
                            subtype="octet-stream",
                            filename=att_path.name,
                        )
                    except OSError:
                        pass

        raw_bytes = msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

        payload = {"raw": raw_b64}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        if self._fetcher is not None:
            status_code, resp_body = self._fetcher("POST", GMAIL_SEND_API, payload, headers)
        else:
            req = urllib.request.Request(
                GMAIL_SEND_API,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20.0) as resp:
                    resp_body = json.loads(resp.read().decode("utf-8"))
                    status_code = resp.status
            except urllib.error.HTTPError as exc:
                try:
                    resp_body = json.loads(exc.read().decode("utf-8"))
                except Exception:
                    resp_body = {}
                status_code = exc.code
            except (urllib.error.URLError, OSError) as exc:
                return {"status": "FAILED", "error": "NETWORK_ERROR", "detail": str(exc)}

        if status_code in (200, 201) and "id" in resp_body:
            return {
                "status": "SENT",
                "provider": "Google Gmail API",
                "message_id": resp_body["id"],
                "thread_id": resp_body.get("threadId"),
                "recipient": recipient,
                "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        err = resp_body.get("error", {})
        err_msg = err.get("message") if isinstance(err, dict) else str(resp_body)
        return {
            "status": "FAILED",
            "error": "GMAIL_API_ERROR",
            "http_status": status_code,
            "detail": err_msg,
        }
