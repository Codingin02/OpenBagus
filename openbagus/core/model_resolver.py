"""Central Repository Model Resolver for OpenBagus.

Enforces Master Directive V5.1 single-source-of-truth:
All operational weights and runtime caches resolve to the canonical repository:
    E:\\Projects\\OpenBagus\\models

Provides strict path traversal protection, configuration verification,
checksum validation, offline safety, and multi-worktree isolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL_DEFAULT_REPO = Path("E:/Projects/OpenBagus")
CANONICAL_MODELS_DIR = CANONICAL_DEFAULT_REPO / "models"


class ModelResolutionError(FileNotFoundError):
    """Raised when an operational model file or configuration cannot be resolved."""
    pass


class ModelSecurityError(ValueError):
    """Raised when path traversal or unauthorized model resolution is detected."""
    pass


class ModelResolver:
    """Central resolver for all local AI models, configs, and runtime caches."""

    _instance: ModelResolver | None = None

    def __init__(self, override_models_dir: str | Path | None = None) -> None:
        self._models_dir = self._detect_models_dir(override_models_dir)
        self._repo_root = self._models_dir.parent
        self._manifest_cache: dict[str, Any] | None = None

    @classmethod
    def get_instance(cls) -> ModelResolver:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _detect_models_dir(override: str | Path | None = None) -> Path:
        """Determines the canonical operational models directory.

        Precedence:
        1. Explicit override argument
        2. OPENBAGUS_MODEL_DIR environment variable
        3. Canonical default E:/Projects/OpenBagus/models if existing
        4. Sibling repository detection if running in a worktree (e.g. OpenBagus-Voice)
        5. Traverse upward from current file to find OpenBagus repository root
        """
        if override:
            p = Path(override).resolve()
            if p.is_dir():
                return p

        env_dir = os.environ.get("OPENBAGUS_MODEL_DIR")
        if env_dir:
            p = Path(env_dir).resolve()
            if p.is_dir():
                return p

        # Check canonical standard repository
        if CANONICAL_MODELS_DIR.is_dir():
            return CANONICAL_MODELS_DIR.resolve()

        # Worktree sibling detection (e.g. from E:/Projects/OpenBagus-Voice)
        current = Path(__file__).resolve()
        for parent in current.parents:
            sibling = parent.parent / "OpenBagus" / "models"
            if sibling.is_dir():
                return sibling.resolve()
            candidate = parent / "models"
            if candidate.is_dir():
                return candidate.resolve()

        # Fallback to CANONICAL_MODELS_DIR even if pending creation
        return CANONICAL_MODELS_DIR.resolve()

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def get_cache_dir(self) -> Path:
        return (self._repo_root / ".cache").resolve()

    def configure_environment_caches(self) -> dict[str, str]:
        """Configures all AI library cache directories to reside inside the repository."""
        cache_base = self.get_cache_dir()
        hf_dir = cache_base / "huggingface"
        torch_dir = cache_base / "torch"
        downloads_dir = cache_base / "downloads"
        pip_dir = cache_base / "pip"
        ollama_dir = self._models_dir / "ollama"

        for d in (hf_dir, torch_dir, downloads_dir, pip_dir, ollama_dir):
            d.mkdir(parents=True, exist_ok=True)

        env_updates = {
            "OPENBAGUS_MODEL_DIR": str(self._models_dir),
            "HF_HOME": str(hf_dir),
            "HF_HUB_CACHE": str(hf_dir / "hub"),
            "HF_ASSETS_CACHE": str(hf_dir / "assets"),
            "TORCH_HOME": str(torch_dir),
            "OLLAMA_MODELS": str(ollama_dir),
        }

        for k, v in env_updates.items():
            os.environ[k] = v

        return env_updates

    def _validate_safe_path(self, target: Path, must_exist: bool = True) -> Path:
        """Validates that target path is within the allowed repository boundaries and exists."""
        resolved = target.resolve()
        try:
            resolved.relative_to(self._repo_root)
        except ValueError:
            raise ModelSecurityError(f"Path traversal detected: {target} is outside repository {self._repo_root}")

        if must_exist and not resolved.exists():
            raise ModelResolutionError(
                f"Required model or configuration not found at: {resolved}\n"
                f"Ensure models are placed in the canonical directory: {self._models_dir}"
            )
        return resolved

    # -------------------------------------------------------------------------
    # Component Accessors
    # -------------------------------------------------------------------------

    def get_llm_fast_path(self) -> Path:
        """Returns path to the primary local fast GGUF LLM."""
        path = self._models_dir / "llm" / "fast" / "Qwen3-4B-Q4_K_M.gguf"
        return self._validate_safe_path(path)

    def get_llm_tutor_path(self) -> Path:
        """Returns path to the English Tutor LLM (shared weights with fast LLM)."""
        # Shared canonical weights per Section 9 (Zero duplicate weight allocation)
        path = self._models_dir / "llm" / "fast" / "Qwen3-4B-Q4_K_M.gguf"
        return self._validate_safe_path(path)

    def get_indonesian_tts_paths(self) -> tuple[Path, Path]:
        """Returns (model_path, config_path) for Indonesian Piper TTS."""
        m = self._models_dir / "tts" / "indonesian" / "id_ID-news_tts-medium.onnx"
        c = self._models_dir / "tts" / "indonesian" / "id_ID-news_tts-medium.onnx.json"
        return self._validate_safe_path(m), self._validate_safe_path(c)

    def get_english_tts_paths(self) -> tuple[Path, Path]:
        """Returns (model_path, config_path) for English Norman male Piper TTS."""
        m = self._models_dir / "tts" / "english" / "norman-medium" / "en_US-norman-medium.onnx"
        c = self._models_dir / "tts" / "english" / "norman-medium" / "en_US-norman-medium.onnx.json"
        return self._validate_safe_path(m), self._validate_safe_path(c)

    def get_asr_model_dir(self) -> Path:
        """Returns directory containing faster-whisper CTranslate2 model files."""
        d = self._models_dir / "asr" / "faster_whisper"
        resolved_d = self._validate_safe_path(d)
        model_bin = resolved_d / "model.bin"
        config_json = resolved_d / "config.json"
        if not model_bin.is_file() or not config_json.is_file():
            raise ModelResolutionError(f"Incomplete Faster-Whisper weights in: {resolved_d}")
        return resolved_d

    def get_silero_vad_path(self) -> Path:
        """Returns path to the Silero VAD ONNX model."""
        path = self._models_dir / "vad" / "silero" / "silero_vad_v6.onnx"
        return self._validate_safe_path(path)

    # -------------------------------------------------------------------------
    # Verification Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def verify_file_hash(path: Path, expected_sha256: str) -> bool:
        """Verifies bit-exact SHA-256 checksum of the specified model file."""
        if not path.is_file():
            return False
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest().lower() == expected_sha256.lower()

    def load_manifest(self) -> dict[str, Any]:
        """Loads and parses the models manifest.json."""
        if self._manifest_cache is not None:
            return self._manifest_cache
        manifest_file = self._models_dir / "manifest.json"
        if not manifest_file.is_file():
            raise ModelResolutionError(f"Model manifest not found: {manifest_file}")
        self._manifest_cache = json.loads(manifest_file.read_text(encoding="utf-8"))
        return self._manifest_cache


def get_model_resolver() -> ModelResolver:
    """Convenience getter for the central ModelResolver singleton."""
    return ModelResolver.get_instance()
