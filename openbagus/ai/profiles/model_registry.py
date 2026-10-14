"""Model Profile Registry for multi-domain runtime scaffolding (General, Finance, Crypto, and Future English Tutor)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModelProfile:
    """Defines an isolated runtime model profile for a specific conversational domain."""

    profile_id: str
    domain: str  # "GENERAL", "FINANCE", "CRYPTO", "ENGLISH_TUTOR"
    model_path: str | None
    provider_type: str  # "LLAMA_CPP_LOCAL", "OLLAMA", "FUTURE_DEFERRED"
    language: str
    system_prompt: str
    resource_budget: dict[str, Any]
    inference_options: dict[str, Any]
    tool_permissions: list[str]
    load_status: str  # "LOADED", "UNLOADED", "NOT_INSTALLED"
    availability_status: str  # "AVAILABLE_LOCAL", "DOWNLOAD_DEFERRED", "USER_APPROVAL_REQUIRED"
    requires_user_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "domain": self.domain,
            "model_path": self.model_path,
            "provider_type": self.provider_type,
            "language": self.language,
            "load_status": self.load_status,
            "availability_status": self.availability_status,
            "requires_user_approval": self.requires_user_approval,
            "tool_permissions": self.tool_permissions,
        }


class ModelProfileRegistry:
    """Central registry managing domain-specific model profiles without performing unauthorized downloads."""

    _instance: ModelProfileRegistry | None = None

    def __init__(self) -> None:
        self._profiles: dict[str, ModelProfile] = {}
        self._active_profile_id: str = "GENERAL_CONVERSATION"
        self._init_profiles()

    @classmethod
    def get_instance(cls) -> ModelProfileRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_profiles(self) -> None:
        # Profile 1: General Everyday Conversation (Local Qwen3-4B on CUDA)
        self._profiles["GENERAL_CONVERSATION"] = ModelProfile(
            profile_id="GENERAL_CONVERSATION",
            domain="GENERAL",
            model_path="C:/Users/bagus/AppData/Local/OpenBagus/models/Qwen3-4B-Q4_K_M.gguf",
            provider_type="LLAMA_CPP_LOCAL",
            language="id",
            system_prompt=(
                "Anda adalah Bagusmax, asisten AI desktop pribadi yang ramah, santun, tenang, dan cerdas. "
                "Berkomunikasilah secara ringkas dan alami dalam Bahasa Indonesia. "
                "Gunakan tools sistem terverifikasi jika ditanya mengenai laptop atau telemetri."
            ),
            resource_budget={"vram_target_mb": 2500, "threads": 4},
            inference_options={"temperature": 0.3, "max_tokens": 512},
            tool_permissions=["get_runtime_capabilities", "get_system_diagnostics", "get_voice_runtime_status", "set_voice_preset"],
            load_status="LOADED",
            availability_status="AVAILABLE_LOCAL",
            requires_user_approval=False,
        )

        # Profile 2: Quantitative Finance & IDX Research (Local Qwen3-4B on CUDA with Financial Tools)
        self._profiles["FINANCE_RESEARCH"] = ModelProfile(
            profile_id="FINANCE_RESEARCH",
            domain="FINANCE",
            model_path="C:/Users/bagus/AppData/Local/OpenBagus/models/Qwen3-4B-Q4_K_M.gguf",
            provider_type="LLAMA_CPP_LOCAL",
            language="id",
            system_prompt=(
                "Anda adalah OpenBagus, asisten riset finansial kuantitatif untuk 951 emiten IDX BEI. "
                "Wajib memverifikasi seluruh fakta, rasio, dan harga melalui tools terdaftar. "
                "Jangan pernah memalsukan harga atau metrik jika berstatus DATA_GAP."
            ),
            resource_budget={"vram_target_mb": 3500, "threads": 6},
            inference_options={"temperature": 0.15, "max_tokens": 1536},
            tool_permissions=["*"],
            load_status="LOADED",
            availability_status="AVAILABLE_LOCAL",
            requires_user_approval=False,
        )

        # Profile 3: Multi-Asset & Crypto Research (Local Qwen3-4B on CUDA)
        self._profiles["CRYPTO_RESEARCH"] = ModelProfile(
            profile_id="CRYPTO_RESEARCH",
            domain="CRYPTO",
            model_path="C:/Users/bagus/AppData/Local/OpenBagus/models/Qwen3-4B-Q4_K_M.gguf",
            provider_type="LLAMA_CPP_LOCAL",
            language="id",
            system_prompt="Anda adalah asisten riset pasar cryptocurrency dan analisis multi-aset kuantitatif OpenBagus.",
            resource_budget={"vram_target_mb": 3000, "threads": 4},
            inference_options={"temperature": 0.2, "max_tokens": 1024},
            tool_permissions=["*"],
            load_status="LOADED",
            availability_status="AVAILABLE_LOCAL",
            requires_user_approval=False,
        )

        # Profile 4: Future English Tutor Architecture (Strictly Scaffolded — ZERO DOWNLOADS)
        self._profiles["ENGLISH_TUTOR"] = ModelProfile(
            profile_id="ENGLISH_TUTOR",
            domain="ENGLISH_TUTOR",
            model_path=None,  # Intentionally None: No file downloaded
            provider_type="FUTURE_DEFERRED",
            language="en-US",
            system_prompt=(
                "You are Bagusmax English Tutor, an encouraging and patient language instructor. "
                "Help the user practice conversational English, correct grammar mistakes gently, "
                "and explain linguistic concepts with bilingual Indonesian support when helpful."
            ),
            resource_budget={"vram_target_mb": 2500, "threads": 4},
            inference_options={"temperature": 0.25, "max_tokens": 768},
            tool_permissions=[],  # Stock tools disabled by default in English learning mode
            load_status="NOT_INSTALLED",
            availability_status="DOWNLOAD_DEFERRED",
            requires_user_approval=True,
        )

    def get_profile(self, profile_id: str) -> ModelProfile | None:
        return self._profiles.get(profile_id)

    def list_profiles(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._profiles.values()]

    def request_english_tutor_activation(self) -> str:
        """Returns the truthful explanation regarding English Tutor activation status."""
        p = self._profiles["ENGLISH_TUTOR"]
        return (
            "Mode belajar bahasa Inggris sudah disiapkan dalam arsitektur sistem, "
            "tetapi model khususnya belum dipasang (DOWNLOAD_DEFERRED). "
            "Sesuai kebijakan offline, unduhan model baru tidak dilakukan secara otomatis. "
            "Kita bisa mengaktifkannya setelah Anda memberikan izin unduhan saat koneksi Wi-Fi tersedia."
        )
