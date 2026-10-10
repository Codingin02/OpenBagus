"""Optional official Puter Node bridge, with explicit consent and local fallback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from openbagus.intelligence.feedback import sanitize_text


class PuterBackend:
    def __init__(self, directory: Path | None = None) -> None:
        from openbagus.intelligence.local_language import get_local_appdata_dir
        self.directory = directory or get_local_appdata_dir() / "cloud"
        self.settings = self.directory / "settings.json"
        self.status = "CLOUD_DISABLED"
        self.retry_after = 0.0

    @property
    def enabled(self) -> bool:
        try:
            settings = json.loads(self.settings.read_text(encoding="utf-8"))
            return settings.get("consent") is True and settings.get("validated") is True
        except (OSError, ValueError, AttributeError):
            return False

    def _call(self, action: str, prompt: str = "", temperature: float = 0.0, max_tokens: int = 128) -> str | None:
        node = shutil.which("node")
        if not node:
            self.status = "CLOUD_NODE_UNAVAILABLE"
            return None
        # Credentials travel neither in argv nor the inherited process environment.
        env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ("KEY", "TOKEN", "PASSWORD", "SECRET", "SMTP", "OBF_", "OPENBAGUS_"))}
        try:
            result = subprocess.run([node, str(Path(__file__).with_name("puter_bridge.cjs")), str(self.directory)],
                                    input=json.dumps({"action": action, "prompt": sanitize_text(prompt),
                                                      "temperature": temperature, "max_tokens": max_tokens}),
                                    capture_output=True, text=True, encoding="utf-8", env=env,
                                    timeout=180 if action == "login" else 20, check=False)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.status = payload.get("status", "CLOUD_FAILED")
            return payload.get("text") if self.status == "CLOUD_OK" else None
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            self.status = "CLOUD_FAILED"
            return None

    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 128) -> str | None:
        if not self.enabled or time.monotonic() < self.retry_after:
            return None
        text = self._call("chat", prompt, temperature, max_tokens)
        if text is None:
            self.retry_after = time.monotonic() + 300
        return text

    def configure(self, consent: bool = False) -> str:
        if not consent:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.settings.write_text(json.dumps({"consent": False, "validated": False}), encoding="utf-8")
            self.status = "CLOUD_DISABLED"
            return self.status
        node, npm = shutil.which("node"), shutil.which("npm.cmd")
        try:
            compatible = node and int(subprocess.check_output([node, "--version"], text=True).lstrip("v").split(".")[0]) >= 24
        except (OSError, ValueError, subprocess.CalledProcessError):
            compatible = False
        if not compatible or not npm or os.name != "nt":
            self.status = "CLOUD_PREREQUISITE_MISSING"
            return self.status
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"consent": True, "validated": False}), encoding="utf-8")
        sdk = self.directory / "node_modules/@heyputer/puter.js/src/init.cjs"
        if not sdk.exists():
            try:
                installed = subprocess.run([npm, "install", "--prefix", str(self.directory), "--ignore-scripts", "--no-audit", "--no-fund", "@heyputer/puter.js@2.6.4"], capture_output=True, timeout=120)
                if installed.returncode:
                    self.status = "CLOUD_SDK_UNAVAILABLE"
                    return self.status
            except (OSError, subprocess.TimeoutExpired):
                self.status = "CLOUD_SDK_UNAVAILABLE"
                return self.status
        self._call("login")
        if self.status == "CLOUD_AUTH_READY":
            response = self._call("chat", "Reply with exactly OPENBAGUS_CLOUD_OK. No market analysis.", max_tokens=24)
            if response and "OPENBAGUS_CLOUD_OK" in response:
                self.settings.write_text(json.dumps({"consent": True, "validated": True}), encoding="utf-8")
                self.status = "CLOUD_ACTIVE"
        return self.status
