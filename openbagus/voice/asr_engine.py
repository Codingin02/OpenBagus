"""Local multilingual speech recognition engine using faster-whisper with NVIDIA RTX CUDA acceleration."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
import numpy as np

from openbagus.voice.asr_normalizer import ASRFinancialNormalizer, NormalizedASRResult

logger = logging.getLogger(__name__)

def _register_nvidia_dll_paths() -> None:
    if os.name != "nt":
        return
    import sys
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if base.exists():
        for bin_dir in base.glob("*/bin"):
            if bin_dir.is_dir():
                try:
                    os.add_dll_directory(str(bin_dir))
                except Exception:
                    pass
                p_str = str(bin_dir)
                if p_str not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = p_str + os.pathsep + os.environ.get("PATH", "")

_register_nvidia_dll_paths()

try:
    import faster_whisper
except ImportError:
    faster_whisper = None

DEFAULT_INITIAL_PROMPT = (
    "Percakapan pasar modal Indonesia IDX BEI. "
    "Membahas saham emiten BBCA, BBRI, BMRI, TLKM, ASII, HGII, YOII, "
    "analisis teknikal, swing breakout, indikator RSI ATR VWAP, "
    "laporan keuangan, valuasi DCF, dividen, rasio PER, PBV, ROE, ROIC, DER, ADTV."
)


class LocalASREngine:
    """High-performance local Indonesian ASR engine powered by faster-whisper on CUDA."""

    def __init__(
        self,
        model_size_or_path: str | Path | None = None,
        device: str = "auto",
        compute_type: str = "float16",
        language: str = "id",
        initial_prompt: str = DEFAULT_INITIAL_PROMPT,
    ) -> None:
        self.language = language
        self.initial_prompt = initial_prompt
        self._model: Any = None
        self._device = device
        self._compute_type = compute_type
        self._model_path = self._resolve_model_path(model_size_or_path)

        self._init_model()

    def _resolve_model_path(self, custom: str | Path | None) -> str:
        if custom:
            return str(custom)

        # Check local huggingface snapshot first (offline guarantee)
        hf_base = Path(os.environ.get("USERPROFILE", "C:/Users/bagus")) / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-large-v3" / "snapshots"
        if hf_base.exists():
            snapshots = list(hf_base.glob("*"))
            if snapshots:
                return str(snapshots[0])

        return "large-v3"

    def _init_model(self) -> None:
        if faster_whisper is None:
            logger.warning("faster-whisper is not installed")
            return

        # Determine target device (CUDA preferred if available)
        if self._device == "auto":
            try:
                import ctranslate2
                cuda_count = ctranslate2.get_cuda_device_count()
                self._device = "cuda" if cuda_count > 0 else "cpu"
            except Exception:
                self._device = "cpu"

        if self._device == "cpu":
            self._compute_type = "int8"

        try:
            logger.info("Loading Whisper model from %s on %s (%s)...", self._model_path, self._device, self._compute_type)
            self._model = faster_whisper.WhisperModel(
                self._model_path,
                device=self._device,
                compute_type=self._compute_type,
            )
            logger.info("Whisper model successfully loaded on %s", self._device)
        except Exception as e:
            logger.warning("Failed to load on CUDA, falling back to CPU int8: %s", e)
            try:
                self._device = "cpu"
                self._compute_type = "int8"
                self._model = faster_whisper.WhisperModel(
                    self._model_path,
                    device="cpu",
                    compute_type="int8",
                )
            except Exception as e_cpu:
                logger.error("Failed to load Whisper model on CPU: %s", e_cpu)
                self._model = None

    def is_available(self) -> bool:
        return self._model is not None

    @property
    def model_path(self) -> str:
        return self._model_path

    @property
    def model_size_or_path(self) -> str:
        return self._model_path

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str | None = None,
    ) -> tuple[NormalizedASRResult, dict[str, Any]]:
        """Transcribes float32 16kHz audio into normalized financial text.

        Returns:
            (NormalizedASRResult, telemetry: dict)
        """
        if not self.is_available() or len(audio) == 0:
            empty = NormalizedASRResult("", "", [], None, None, [])
            return empty, {"latency_ms": 0.0, "audio_duration_s": 0.0, "device": self._device}

        # Ensure float32 normalized [-1.0, 1.0]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        audio_duration = len(audio) / sample_rate
        t_start = time.perf_counter()

        try:
            segments, info = self._model.transcribe(
                audio,
                language=language or self.language,
                initial_prompt=self.initial_prompt,
                beam_size=5,
                temperature=0.0,
                vad_filter=False,  # Outer VAD already performed frame endpointing
            )
            raw_text = " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            logger.error("Transcription error: %s", e)
            raw_text = ""

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        rtf = (latency_ms / 1000.0) / audio_duration if audio_duration > 0 else 0.0

        normalized_res = ASRFinancialNormalizer.normalize(raw_text)
        telemetry = {
            "latency_ms": round(latency_ms, 1),
            "audio_duration_s": round(audio_duration, 2),
            "real_time_factor": round(rtf, 3),
            "device": self._device,
            "compute_type": self._compute_type,
            "detected_language": getattr(info, "language", self.language) if "info" in locals() else self.language,
        }

        return normalized_res, telemetry
