"""Model provider discovery, registry and lifecycle manager.

Supports FAST (qwen3.5:2b) and DEEP_REASONING (qwen3.5:4b) Ollama providers
with proper VRAM management — only one large model loaded at a time.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from openbagus.ai.providers.base import BaseModelProvider
from openbagus.ai.providers.fallback import DeterministicFallbackProvider
from openbagus.ai.providers.llama_server import LlamaServerProvider
from openbagus.ai.providers.ollama import (
    OLLAMA_DEEP_MODEL,
    OLLAMA_FAST_MODEL,
    OllamaProvider,
)
from openbagus.ai.providers.openai_compat import OpenAICompatibleProvider
from openbagus.ai.runtime.hardware import HardwareDetector

logger = logging.getLogger(__name__)


class ProviderManager:
    """Manages model provider detection, configuration, and runtime switching.

    VRAM budget on RTX 3050 6GB:
      FAST  : qwen3.5:2b-q4_K_M — 2.47 GB loaded, 92 tok/s
      DEEP  : qwen3.5:4b        — 3.88 GB loaded, 48 tok/s
    Only one can be warm simultaneously.
    """

    _instance: ProviderManager | None = None

    def __init__(self) -> None:
        self._provider: BaseModelProvider | None = None
        self._active_type: str = "AUTO"
        self._current_mode: str = "BALANCED"
        self.detector = HardwareDetector()

        # Typed FAST and DEEP provider instances (lazy)
        self._fast_provider: OllamaProvider | None = None
        self._deep_provider: OllamaProvider | None = None

    @classmethod
    def get_instance(cls) -> ProviderManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Typed FAST / DEEP accessors
    # ------------------------------------------------------------------

    def get_fast_provider(self) -> OllamaProvider:
        """Return the FAST Ollama provider (qwen3.5:2b, think=False, 2K ctx)."""
        if self._fast_provider is None:
            self._fast_provider = OllamaProvider(
                model=OLLAMA_FAST_MODEL,
                think=False,
                keep_alive="30m",
                num_gpu=99,
                context_window=4096,
            )
        return self._fast_provider

    def get_deep_provider(self) -> OllamaProvider:
        """Return the DEEP Ollama provider (qwen3.5:4b, think=True, 4K ctx)."""
        if self._deep_provider is None:
            self._deep_provider = OllamaProvider(
                model=OLLAMA_DEEP_MODEL,
                think=True,
                keep_alive="30m",
                num_gpu=99,
                context_window=4096,
            )
        return self._deep_provider

    def switch_to_fast(self) -> BaseModelProvider:
        """Switch active provider to FAST, unloading DEEP from VRAM first."""
        if self._deep_provider is not None and self._deep_provider.is_model_warm():
            logger.info("Unloading DEEP model from VRAM before switching to FAST")
            self._deep_provider.unload_model()
        fast = self.get_fast_provider()
        self._provider = fast
        self._active_type = "OLLAMA_FAST"
        self._current_mode = "FAST"
        return fast

    def switch_to_deep(self) -> BaseModelProvider:
        """Switch active provider to DEEP, unloading FAST from VRAM first."""
        if self._fast_provider is not None and self._fast_provider.is_model_warm():
            logger.info("Unloading FAST model from VRAM before switching to DEEP")
            self._fast_provider.unload_model()
        deep = self.get_deep_provider()
        self._provider = deep
        self._active_type = "OLLAMA_DEEP"
        self._current_mode = "DEEP_REASONING"
        return deep

    # ------------------------------------------------------------------
    # Generic provider API (backward-compatible)
    # ------------------------------------------------------------------

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

        # 2. Ollama FAST (preferred — 92 tok/s GPU-resident)
        fast = self.get_fast_provider()
        if fast.is_available():
            self._active_type = "OLLAMA_FAST"
            self._current_mode = "FAST"
            return fast

        # 3. Local llama-server with CUDA
        llama_p = LlamaServerProvider()
        if llama_p.is_available():
            self._active_type = "LLAMA_CPP_LOCAL"
            return llama_p

        # 4. Deterministic fallback
        self._active_type = "FALLBACK"
        return DeterministicFallbackProvider()

    def switch_provider(self, provider_type: str, **kwargs: Any) -> BaseModelProvider:
        pt = provider_type.upper().strip()
        if pt in {"FAST", "OLLAMA_FAST"}:
            return self.switch_to_fast()
        elif pt in {"DEEP", "DEEP_REASONING", "OLLAMA_DEEP"}:
            return self.switch_to_deep()
        elif pt in {"LLAMA", "LLAMA_CPP", "LOCAL"}:
            p = LlamaServerProvider(
                server_bin=kwargs.get("server_bin"),
                model_path=kwargs.get("model_path"),
            )
        elif pt in {"OLLAMA"}:
            p = OllamaProvider(
                base_url=kwargs.get("base_url", "http://127.0.0.1:11434"),
                model=kwargs.get("model", OLLAMA_FAST_MODEL),
                think=kwargs.get("think", False),
                keep_alive=kwargs.get("keep_alive", "30m"),
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
        fast = self.get_fast_provider()
        deep = self.get_deep_provider()
        return {
            "active_type": self._active_type,
            "current_mode": self._current_mode,
            "provider_name": p.get_provider_name(),
            "is_available": p.is_available(),
            "model_info": p.get_model_info(),
            "hardware": hw.to_dict(),
            "fast_model": {
                "model": OLLAMA_FAST_MODEL,
                "is_available": fast.is_available(),
                "is_warm": fast.is_model_warm() if fast.is_available() else False,
            },
            "deep_model": {
                "model": OLLAMA_DEEP_MODEL,
                "is_available": deep.is_available(),
                "is_warm": deep.is_model_warm() if deep.is_available() else False,
            },
        }
