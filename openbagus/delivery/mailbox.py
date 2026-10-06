"""Provider-neutral SMTP configuration, message construction, and transport."""

from __future__ import annotations

import mimetypes
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, getaddresses, make_msgid, parseaddr
from pathlib import Path
from typing import Any, Iterable

from openbagus.core.env import RuntimeEnv


EMAIL_CONFIRMATION_PHRASE = "I_UNDERSTAND_THIS_SENDS_REAL_EMAIL"
TRUE_VALUES = {"1", "true", "yes", "on"}
SECURITY_MODES = {"starttls", "ssl", "none"}


def _parse_recipients(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    addresses = []
    for _name, address in getaddresses([value.replace(";", ",")]):
        if "@" in address and address not in addresses:
            addresses.append(address)
    return tuple(addresses)


@dataclass(frozen=True)
class SmtpConfig:
    host: str | None
    port: int | None
    security: str
    username: str | None
    password: str | None
    sender: str | None
    recipients: tuple[str, ...]
    errors: tuple[str, ...] = ()

    @classmethod
    def from_runtime_env(cls, runtime_env: RuntimeEnv) -> "SmtpConfig":
        return cls.from_values(
            host=runtime_env.get("OPENBAGUS_EMAIL_SMTP_HOST"),
            port_text=runtime_env.get("OPENBAGUS_EMAIL_SMTP_PORT"),
            security=runtime_env.get("OPENBAGUS_EMAIL_SECURITY"),
            username=runtime_env.get("OPENBAGUS_EMAIL_SMTP_USERNAME"),
            password=runtime_env.get("OPENBAGUS_EMAIL_SMTP_PASSWORD"),
            sender=runtime_env.get("OPENBAGUS_EMAIL_FROM"),
            recipient_text=(
                runtime_env.get("OPENBAGUS_EMAIL_TO")
                or runtime_env.get("OPENBAGUS_EMAIL_TO_MACRO")
                or runtime_env.get("OPENBAGUS_EMAIL_TO_OPERATOR")
            ),
            use_tls=runtime_env.get("OPENBAGUS_EMAIL_USE_TLS", "true"),
        )

    @classmethod
    def from_values(cls, *, host: str | None, port_text: str | None, security: str | None,
                    username: str | None, password: str | None, sender: str | None,
                    recipient_text: str | None, use_tls: str | None = "true") -> "SmtpConfig":
        recipients = _parse_recipients(recipient_text)

        security = (security or "").strip().lower()
        if not security:
            security = "starttls" if (use_tls or "true").strip().lower() in TRUE_VALUES else "none"

        errors: list[str] = []
        port: int | None = None
        if port_text:
            try:
                port = int(port_text)
                if not 1 <= port <= 65535:
                    raise ValueError
            except ValueError:
                errors.append("OPENBAGUS_EMAIL_SMTP_PORT must be an integer from 1 to 65535")
        if security not in SECURITY_MODES:
            errors.append("OPENBAGUS_EMAIL_SECURITY must be starttls, ssl, or none")
        if bool(username) != bool(password):
            errors.append("SMTP username and password must be configured together")
        if sender and ("\r" in sender or "\n" in sender or "@" not in parseaddr(sender)[1]):
            errors.append("OPENBAGUS_EMAIL_FROM must be a valid email address")
        if recipient_text and ("\r" in recipient_text or "\n" in recipient_text):
            errors.append("OPENBAGUS_EMAIL_TO must not contain line breaks")
        if username and security == "none":
            errors.append("Authenticated SMTP requires starttls or ssl")

        return cls(host, port, security, username, password, sender, recipients, tuple(errors))

    @property
    def missing(self) -> tuple[str, ...]:
        missing = []
        if not self.host:
            missing.append("OPENBAGUS_EMAIL_SMTP_HOST")
        if self.port is None:
            missing.append("OPENBAGUS_EMAIL_SMTP_PORT")
        if not self.sender:
            missing.append("OPENBAGUS_EMAIL_FROM")
        if not self.recipients:
            missing.append("OPENBAGUS_EMAIL_TO")
        return tuple(missing)

    @property
    def ready(self) -> bool:
        return not self.missing and not self.errors

    def status(self) -> dict[str, Any]:
        return {
            "status": "EMAIL_CONFIG_READY" if self.ready else "EMAIL_CONFIG_MISSING",
            "host_present": bool(self.host),
            "port": self.port,
            "security": self.security,
            "username_present": bool(self.username),
            "password_present": bool(self.password),
            "sender_present": bool(self.sender),
            "recipient_count": len(self.recipients),
            "missing": list(self.missing),
            "errors": list(self.errors),
            "secret_values_logged": False,
        }


def build_email_message(
    *,
    subject: str,
    text: str,
    html: str,
    config: SmtpConfig,
    attachments: Iterable[Path] = (),
) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject.replace("\r", " ").replace("\n", " ").strip()
    message["From"] = config.sender or "noreply@openbagus.local"
    message["To"] = ", ".join(config.recipients or ("operator@openbagus.local",))
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid(domain="openbagus.local")
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    for path in attachments:
        content_type, _encoding = mimetypes.guess_type(path.name)
        maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return message


def write_eml(message: EmailMessage, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(message.as_bytes(policy=SMTP))
    return path


class SmtpTransport:
    def __init__(self, config: SmtpConfig, timeout: float = 15.0) -> None:
        if not config.ready:
            raise ValueError("Email configuration is incomplete or invalid")
        self.config = config
        self.timeout = timeout

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.config.security == "ssl":
            client = smtplib.SMTP_SSL(self.config.host, self.config.port, timeout=self.timeout, context=context)
        else:
            client = smtplib.SMTP(self.config.host, self.config.port, timeout=self.timeout)
            client.ehlo()
            if self.config.security == "starttls":
                client.starttls(context=context)
                client.ehlo()
        return client

    def check(self) -> dict[str, Any]:
        with self._connect() as client:
            if self.config.username:
                client.login(self.config.username, self.config.password or "")
            client.noop()
        return {"status": "EMAIL_SMTP_READY", "message_sent": False}

    def send(self, message: EmailMessage) -> dict[str, Any]:
        with self._connect() as client:
            if self.config.username:
                client.login(self.config.username, self.config.password or "")
            client.send_message(message)
        return {"status": "EMAIL_SENT", "message_sent": True}
