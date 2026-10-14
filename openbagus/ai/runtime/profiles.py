"""Execution quality and resource profiles for OpenBagus agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    description: str
    max_tokens: int
    temperature: float
    max_tool_iterations: int
    deep_reasoning: bool
    allow_external_api: bool
    timeout_seconds: float
    stream: bool = True
    context_window: int = 4096
    think: bool = False  # Ollama thinking mode (DEEP_REASONING only)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "max_tool_iterations": self.max_tool_iterations,
            "deep_reasoning": self.deep_reasoning,
            "allow_external_api": self.allow_external_api,
            "timeout_seconds": self.timeout_seconds,
            "stream": self.stream,
            "context_window": self.context_window,
            "think": self.think,
        }


PROFILES: dict[str, RuntimeProfile] = {
    "FAST": RuntimeProfile(
        name="FAST",
        description="Jawaban percakapan cepat, pemeriksaan kuotasi tunggal, dan pertanyaan sederhana dengan latensi minimal.",
        max_tokens=512,
        temperature=0.1,
        max_tool_iterations=2,
        deep_reasoning=False,
        allow_external_api=False,
        timeout_seconds=20.0,
        stream=True,
        context_window=2048,
        think=False,
    ),
    "BALANCED": RuntimeProfile(
        name="BALANCED",
        description="Profil default riset interaktif seimbang dengan multi-step tool verification dan sintesis keputusan.",
        max_tokens=1536,
        temperature=0.2,
        max_tool_iterations=4,
        deep_reasoning=True,
        allow_external_api=False,
        timeout_seconds=60.0,
        stream=True,
        context_window=4096,
        think=False,
    ),
    "DEEP_REASONING": RuntimeProfile(
        name="DEEP_REASONING",
        description="Analisis mendalam multi-dokumen, evaluasi laporan keuangan, perbandingan multi-emiten dengan model thinking aktif.",
        max_tokens=2048,
        temperature=0.2,
        max_tool_iterations=6,
        deep_reasoning=True,
        allow_external_api=True,
        timeout_seconds=90.0,
        stream=True,
        context_window=4096,
        think=True,
    ),
    # Alias for backward compatibility
    "DEEP_RESEARCH": RuntimeProfile(
        name="DEEP_RESEARCH",
        description="Alias dari DEEP_REASONING — analisis multi-dokumen mendalam.",
        max_tokens=3072,
        temperature=0.2,
        max_tool_iterations=8,
        deep_reasoning=True,
        allow_external_api=True,
        timeout_seconds=120.0,
        stream=True,
        context_window=8192,
        think=True,
    ),
    "LOCAL_PRIVATE": RuntimeProfile(
        name="LOCAL_PRIVATE",
        description="Mode ketat 100% loopback offline tanpa akses jaringan eksternal ke model pihak ketiga manapun.",
        max_tokens=1536,
        temperature=0.15,
        max_tool_iterations=4,
        deep_reasoning=True,
        allow_external_api=False,
        timeout_seconds=60.0,
        stream=True,
        context_window=4096,
        think=False,
    ),
    "CUSTOM": RuntimeProfile(
        name="CUSTOM",
        description="Pengaturan profil yang dikonfigurasi kustom oleh pengguna.",
        max_tokens=2048,
        temperature=0.3,
        max_tool_iterations=6,
        deep_reasoning=True,
        allow_external_api=False,
        timeout_seconds=90.0,
        stream=True,
        context_window=4096,
        think=False,
    ),
}


def get_profile(name: str = "BALANCED") -> RuntimeProfile:
    upper = name.upper().strip()
    return PROFILES.get(upper, PROFILES["BALANCED"])


def list_profiles() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PROFILES.values()]
