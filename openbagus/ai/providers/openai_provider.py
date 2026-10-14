"""Official OpenAI API Provider with Two-Level Authentication and Model Execution Verification."""

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


class OpenAIProvider(BaseModelProvider):
    """Full-featured OpenAI API provider with level 1 & level 2 verification."""

    BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gpt-4o-mini",
    ) -> None:
        self._custom_key = api_key
        self.default_model = default_model
        self.creds = CredentialManager.get_instance()

    def get_api_key(self) -> str | None:
        return self._custom_key or self.creds.get_credential("openai")

    def get_provider_name(self) -> str:
        return "OPENAI"

    def is_available(self) -> bool:
        key = self.get_api_key()
        return bool(key and len(key) > 10)

    def get_model_info(self) -> dict[str, Any]:
        key = self.get_api_key()
        return {
            "model_name": self.default_model,
            "provider": "OpenAI",
            "base_url": self.BASE_URL,
            "configured": bool(key),
            "masked_key": mask_secret(key) if key else "NOT_SET",
        }

    # -------------------------------------------------------------------------
    # Two-Level Verification
    # -------------------------------------------------------------------------

    def verify_authentication(self, timeout: float = 6.0) -> dict[str, Any]:
        """LEVEL 1 — Authentication Check: Queries models.list without billable generation."""
        key = self.get_api_key()
        if not key:
            return {
                "success": False,
                "status": "NOT_CONFIGURED",
                "message": "OPENAI_API_KEY belum dikonfigurasi.",
                "models_count": 0,
            }

        url = f"{self.BASE_URL}/models"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {key}",
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
            models = [m.get("id") for m in data.get("data", []) if m.get("id")]
            self.creds.update_status("openai", "AUTHENTICATED")
            return {
                "success": True,
                "status": "AUTHENTICATED",
                "message": f"Kredensial OpenAI terverifikasi ({len(models)} model ditemukan).",
                "models_count": len(models),
                "models_sample": models[:10],
                "latency_ms": round(latency, 1),
                "masked_key": mask_secret(key),
            }
        except urllib.error.HTTPError as exc:
            latency = (time.perf_counter() - t_start) * 1000
            err_body = exc.read().decode("utf-8", errors="ignore")
            status = "INVALID_CREDENTIALS" if exc.code == 401 else ("RATE_LIMITED" if exc.code == 429 else f"HTTP_{exc.code}")
            clean_msg = redact_secrets(err_body, [key])
            self.creds.update_status("openai", status, clean_msg[:150])
            return {
                "success": False,
                "status": status,
                "message": f"OpenAI HTTP {exc.code}: {clean_msg[:150]}",
                "latency_ms": round(latency, 1),
                "models_count": 0,
            }
        except Exception as e:
            latency = (time.perf_counter() - t_start) * 1000
            clean_msg = redact_secrets(str(e), [key])
            self.creds.update_status("openai", "NETWORK_ERROR", clean_msg)
            return {
                "success": False,
                "status": "NETWORK_ERROR",
                "message": f"Koneksi jaringan OpenAI gagal: {clean_msg}",
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
        url = f"{self.BASE_URL}/chat/completions"
        payload = {
            "model": target_model,
            "messages": [{"role": "user", "content": test_prompt}],
            "max_tokens": 5,
            "temperature": 0.0,
            "store": False,  # Privacy guarantee
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
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
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "").strip()
            usage = data.get("usage", {})
            self.creds.update_status("openai", "MODEL_ACCESS_VERIFIED")
            return {
                "success": True,
                "status": "MODEL_ACCESS_VERIFIED",
                "model": target_model,
                "reply": content,
                "usage": usage,
                "latency_ms": round(latency, 1),
                "message": "Pengujian eksekusi model OpenAI berhasil.",
            }
        except urllib.error.HTTPError as exc:
            latency = (time.perf_counter() - t_start) * 1000
            err_body = exc.read().decode("utf-8", errors="ignore")
            status = "QUOTA_EXCEEDED" if exc.code == 429 else ("BILLING_REQUIRED" if exc.code == 403 else f"HTTP_{exc.code}")
            clean_msg = redact_secrets(err_body, [key])
            self.creds.update_status("openai", status, clean_msg[:150])
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
            raise RuntimeError("OpenAI API key belum dikonfigurasi.")

        endpoint = f"{self.BASE_URL}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.default_model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
            "store": False,
        }
        if tools:
            payload["tools"] = [t.to_dict() for t in tools]
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
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
            raise RuntimeError(f"OpenAI error (HTTP {exc.code}): {clean_msg}") from exc
        except Exception as e:
            clean_msg = redact_secrets(str(e), [key])
            raise RuntimeError(f"OpenAI network error: {clean_msg}") from e

        latency = (time.perf_counter() - t_start) * 1000
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        tool_calls: list[ToolCall] = []
        for rt in msg.get("tool_calls", []):
            fn = rt.get("function", {})
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except Exception:
                args = {}
            tool_calls.append(ToolCall(
                id=rt.get("id", f"call_{len(tool_calls)}"),
                function_name=fn.get("name", ""),
                arguments=args,
            ))

        return ChatCompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            model=data.get("model", self.default_model),
            usage=data.get("usage", {}),
            provider_name=self.get_provider_name(),
            latency_ms=latency,
        )
