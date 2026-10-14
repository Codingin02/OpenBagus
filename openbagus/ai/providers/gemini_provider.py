"""Official Google Gemini Developer API Provider with Level 1 & Level 2 Verification."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from openbagus.ai.credentials import CredentialManager, mask_secret, redact_secrets
from openbagus.ai.providers.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class GeminiProvider(BaseModelProvider):
    """Google Gemini Developer API provider using official x-goog-api-key authorization."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gemini-1.5-flash",
    ) -> None:
        self._custom_key = api_key
        self.default_model = default_model
        self.creds = CredentialManager.get_instance()

    def get_api_key(self) -> str | None:
        return self._custom_key or self.creds.get_credential("gemini")

    def get_provider_name(self) -> str:
        return "GEMINI"

    def is_available(self) -> bool:
        key = self.get_api_key()
        return bool(key and len(key) > 10)

    def get_model_info(self) -> dict[str, Any]:
        key = self.get_api_key()
        return {
            "model_name": self.default_model,
            "provider": "Google Gemini",
            "base_url": self.BASE_URL,
            "configured": bool(key),
            "masked_key": mask_secret(key) if key else "NOT_SET",
        }

    # -------------------------------------------------------------------------
    # Two-Level Verification
    # -------------------------------------------------------------------------

    def verify_authentication(self, timeout: float = 6.0) -> dict[str, Any]:
        """LEVEL 1 — Authentication Check: Queries /v1beta/models using x-goog-api-key."""
        key = self.get_api_key()
        if not key:
            return {
                "success": False,
                "status": "NOT_CONFIGURED",
                "message": "GEMINI_API_KEY belum dikonfigurasi.",
                "models_count": 0,
            }

        url = f"{self.BASE_URL}/models"
        req = urllib.request.Request(
            url,
            headers={
                "x-goog-api-key": key,
                "User-Agent": "OpenBagus-Research/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )

        t_start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latency = (time.perf_counter() - t_start) * 1000
            raw_models = data.get("models", [])
            models = [m.get("name", "").replace("models/", "") for m in raw_models if m.get("name")]
            self.creds.update_status("gemini", "AUTHENTICATED")
            return {
                "success": True,
                "status": "AUTHENTICATED",
                "message": f"Kredensial Google Gemini terverifikasi ({len(models)} model ditemukan).",
                "models_count": len(models),
                "models_sample": models[:10],
                "latency_ms": round(latency, 1),
                "masked_key": mask_secret(key),
            }
        except urllib.error.HTTPError as exc:
            latency = (time.perf_counter() - t_start) * 1000
            err_body = exc.read().decode("utf-8", errors="ignore")
            status = "INVALID_CREDENTIALS" if exc.code in (400, 401, 403) else ("RATE_LIMITED" if exc.code == 429 else f"HTTP_{exc.code}")
            clean_msg = redact_secrets(err_body, [key])
            self.creds.update_status("gemini", status, clean_msg[:150])
            return {
                "success": False,
                "status": status,
                "message": f"Gemini HTTP {exc.code}: {clean_msg[:150]}",
                "latency_ms": round(latency, 1),
                "models_count": 0,
            }
        except Exception as e:
            latency = (time.perf_counter() - t_start) * 1000
            clean_msg = redact_secrets(str(e), [key])
            self.creds.update_status("gemini", "NETWORK_ERROR", clean_msg)
            return {
                "success": False,
                "status": "NETWORK_ERROR",
                "message": f"Koneksi jaringan Gemini gagal: {clean_msg}",
                "latency_ms": round(latency, 1),
                "models_count": 0,
            }

    def verify_model_execution(
        self,
        model: str | None = None,
        test_prompt: str = "Respon dengan satu kata: OK.",
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """LEVEL 2 — Model Execution Check: Harmless minimal generation with small token budget."""
        key = self.get_api_key()
        if not key:
            return {"success": False, "status": "NOT_CONFIGURED", "message": "API key belum dikonfigurasi."}

        target_model = model or self.default_model
        norm_model = target_model.replace("models/", "")
        url = f"{self.BASE_URL}/models/{norm_model}:generateContent"

        payload = {
            "contents": [{"parts": [{"text": test_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 5,
                "temperature": 0.0,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
                "User-Agent": "OpenBagus-Research/1.0",
            },
            method="POST",
        )

        t_start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latency = (time.perf_counter() - t_start) * 1000
            candidates = data.get("candidates", [{}])
            parts = candidates[0].get("content", {}).get("parts", [{}])
            reply = parts[0].get("text", "").strip() if parts else ""
            self.creds.update_status("gemini", "MODEL_ACCESS_VERIFIED")
            return {
                "success": True,
                "status": "MODEL_ACCESS_VERIFIED",
                "model": norm_model,
                "reply": reply,
                "latency_ms": round(latency, 1),
                "message": "Pengujian eksekusi model Google Gemini berhasil.",
            }
        except urllib.error.HTTPError as exc:
            latency = (time.perf_counter() - t_start) * 1000
            err_body = exc.read().decode("utf-8", errors="ignore")
            status = "QUOTA_EXCEEDED" if exc.code == 429 else f"HTTP_{exc.code}"
            clean_msg = redact_secrets(err_body, [key])
            self.creds.update_status("gemini", status, clean_msg[:150])
            return {
                "success": False,
                "status": status,
                "message": f"Pengujian eksekusi gagal (HTTP {exc.code}): {clean_msg[:150]}",
                "latency_ms": round(latency, 1),
            }
        except Exception as e:
            latency = (time.perf_counter() - t_start) * 1000
            clean_msg = redact_secrets(str(e), [key])
            return {
                "success": False,
                "status": "NETWORK_ERROR",
                "message": f"Koneksi gagal: {clean_msg}",
                "latency_ms": round(latency, 1),
            }

    def verify_level_1(self, timeout: float = 6.0) -> tuple[bool, str]:
        """Convenience method returning (success, message) for Level 1 check."""
        res = self.verify_authentication(timeout=timeout)
        return res.get("success", False), res.get("message", "")

    def verify_level_2(self, timeout: float = 10.0) -> tuple[bool, str]:
        """Convenience method returning (success, message) for Level 2 check."""
        res = self.verify_model_execution(timeout=timeout)
        return res.get("success", False), res.get("message", "")

    # -------------------------------------------------------------------------
    # Core Chat Completion Method
    # -------------------------------------------------------------------------

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> ChatCompletionResponse | Iterator[ChatCompletionChunk]:
        key = self.get_api_key()
        if not key:
            raise RuntimeError("Gemini API key belum dikonfigurasi.")

        norm_model = self.default_model.replace("models/", "")
        endpoint = f"{self.BASE_URL}/models/{norm_model}:generateContent"

        # Translate messages to Gemini contents
        contents = []
        system_instruction = None
        for m in messages:
            if m.role == "system":
                system_instruction = {"parts": [{"text": m.content}]}
            else:
                role = "user" if m.role in ("user", "tool") else "model"
                contents.append({"role": role, "parts": [{"text": m.content}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
                "User-Agent": "OpenBagus-Research/1.0",
            },
            method="POST",
        )

        t_start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            clean_msg = redact_secrets(err_body, [key])
            raise RuntimeError(f"Gemini error (HTTP {exc.code}): {clean_msg}") from exc
        except Exception as e:
            clean_msg = redact_secrets(str(e), [key])
            raise RuntimeError(f"Gemini network error: {clean_msg}") from e

        latency = (time.perf_counter() - t_start) * 1000
        candidates = data.get("candidates", [{}])
        parts = candidates[0].get("content", {}).get("parts", [{}]) if candidates else [{}]
        reply = parts[0].get("text", "") if parts else ""

        return ChatCompletionResponse(
            content=reply,
            tool_calls=[],
            finish_reason=candidates[0].get("finishReason", "stop") if candidates else "stop",
            model=norm_model,
            provider_name=self.get_provider_name(),
            latency_ms=latency,
        )
