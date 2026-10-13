"""Model provider discovery, registry and lifecycle manager."""

from __future__ import annotations

import os
from typing import Any

from openbagus.ai.providers.base import BaseModelProvider
from openbagus.ai.providers.fallback import DeterministicFallbackProvider
from openbagus.ai.providers.llama_server import LlamaServerProvider
from openbagus.ai.providers.ollama import OllamaProvider
from openbagus.ai.providers.openai_compat import OpenAICompatibleProvider
from openbagus.ai.runtime.hardware import HardwareDetector


class ProviderManager:
    """Manages model provider detection, configuration, and runtime switching."""

    _instance: ProviderManager | None = None

    def __init__(self) -> None:
        self._provider: BaseModelProvider | None = None
        self._active_type: str = "AUTO"
        self.detector = HardwareDetector()

    @classmethod
    def get_instance(cls) -> ProviderManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_provider(self) -> BaseModelProvider:
        if self._provider is None:
            self._provider = self._auto_discover()
        return self._provider

    def _auto_discover(self) -> BaseModelProvider:
        # 1. Custom Endpoint via environment
        custom_endpoint = os.environ.get("OPENBAGUS_LLM_ENDPOINT")
        if custom_endpoint:
            p = OpenAICompatibleProvider(
                base_url=custom_endpoint,
                model=os.environ.get("OPENBAGUS_LLM_MODEL", "default"),
                api_key=os.environ.get("OPENBAGUS_LLM_KEY"),
                provider_label="CUSTOM_REMOTE_ENDPOINT",
            )
            if p.is_available():
                self._active_type = "CUSTOM_REMOTE"
                return p

        # 2. Local llama-server with CUDA
        llama_p = LlamaServerProvider()
        if llama_p.is_available():
            self._active_type = "LLAMA_CPP_LOCAL"
            return llama_p

        # 3. Local Ollama instance
        ollama_p = OllamaProvider()
        if ollama_p.is_available():
            self._active_type = "OLLAMA_LOCAL"
            return ollama_p

        # 4. Deterministic fallback
        self._active_type = "FALLBACK"
        return DeterministicFallbackProvider()

    def switch_provider(self, provider_type: str, **kwargs: Any) -> BaseModelProvider:
        pt = provider_type.upper().strip()
        if pt in {"LLAMA", "LLAMA_CPP", "LOCAL"}:
            p = LlamaServerProvider(
                server_bin=kwargs.get("server_bin"),
                model_path=kwargs.get("model_path"),
            )
        elif pt in {"OLLAMA"}:
            p = OllamaProvider(
                base_url=kwargs.get("base_url", "http://127.0.0.1:11434"),
                model=kwargs.get("model", "qwen2.5:3b"),
            )
        elif pt in {"OPENAI", "REMOTE", "CUSTOM"}:
            p = OpenAICompatibleProvider(
                base_url=kwargs.get("base_url", "http://127.0.0.1:8000/v1"),
                model=kwargs.get("model", "default"),
                api_key=kwargs.get("api_key"),
            )
        elif pt in {"FALLBACK", "DETERMINISTIC"}:
            p = DeterministicFallbackProvider()
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")

        self._provider = p
        self._active_type = pt
        return p

    def get_status(self) -> dict[str, Any]:
        p = self.get_provider()
        hw = self.detector.detect()
        return {
            "active_type": self._active_type,
            "provider_name": p.get_provider_name(),
            "is_available": p.is_available(),
            "model_info": p.get_model_info(),
            "hardware": hw.to_dict(),
        }
