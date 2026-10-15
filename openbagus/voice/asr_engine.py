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
    "Percakapan santai, asisten komputer, dan riset pasar modal Indonesia dalam Bahasa Indonesia."
)



_SHARED_WHISPER_MODEL: Any = None
_SHARED_MODEL_KEY: tuple[str, str, str] | None = None


class LocalASREngine:
    """High-performance local Indonesian ASR engine powered by faster-whisper on CUDA."""

    PHANTOM_OUTRO_MARKERS = (
        "terima kasih telah menonton",
        "terima kasih sudah menonton",
        "terima kasih telah menyaksikan",
        "terima kasih sudah menyaksikan",
        "terima kasih banyak telah menonton",
        "terima kasih banyak sudah menonton",
        "terima kasih atas perhatiannya",
        "terima kasih telah mendengarkan",
        "terima kasih atas kunjungannya",
        "terima kasih banyak",
        "terima kasih.",
        "terima kasih!",
        "terima kasih",
        "jangan lupa subscribe",
        "jangan lupa like",
        "jangan lupa share",
        "sampai jumpa di video",
        "sampai jumpa lagi",
        "sampai jumpa",
        "tonton terus video",
        "subtitles by",
        "subtitle by",
        "translated by",
        "thank you for watching",
    )

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

        # Multi-signal acoustic tracking state
        self._noise_floor_rms: float = 0.0010
        self._last_utterance_id: str | None = None
        self._last_result: tuple[NormalizedASRResult, dict[str, Any]] | None = None

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

        global _SHARED_WHISPER_MODEL, _SHARED_MODEL_KEY
        key = (self._model_path, self._device, self._compute_type)
        if _SHARED_WHISPER_MODEL is not None and _SHARED_MODEL_KEY == key:
            self._model = _SHARED_WHISPER_MODEL
            return

        try:
            logger.info("Loading Whisper model from %s on %s (%s)...", self._model_path, self._device, self._compute_type)
            self._model = faster_whisper.WhisperModel(
                self._model_path,
                device=self._device,
                compute_type=self._compute_type,
            )
            logger.info("Whisper model successfully loaded on %s", self._device)
            _SHARED_WHISPER_MODEL = self._model
            _SHARED_MODEL_KEY = key
        except Exception as e:
            logger.warning("Failed to load on CUDA, falling back to CPU int8: %s", e)
            try:
                self._device = "cpu"
                self._compute_type = "int8"
                cpu_key = (self._model_path, "cpu", "int8")
                if _SHARED_WHISPER_MODEL is not None and _SHARED_MODEL_KEY == cpu_key:
                    self._model = _SHARED_WHISPER_MODEL
                    return

                self._model = faster_whisper.WhisperModel(
                    self._model_path,
                    device="cpu",
                    compute_type="int8",
                )
                _SHARED_WHISPER_MODEL = self._model
                _SHARED_MODEL_KEY = cpu_key
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

    @property
    def noise_floor_rms(self) -> float:
        return self._noise_floor_rms

    def update_noise_floor(self, frame_or_rms: float | np.ndarray) -> float:
        """Dynamically updates the estimated ambient noise floor using exponential moving average."""
        if isinstance(frame_or_rms, (float, int)):
            measured_rms = float(frame_or_rms)
        else:
            if len(frame_or_rms) == 0:
                return self._noise_floor_rms
            measured_rms = float(np.sqrt(np.mean(frame_or_rms.astype(np.float32) ** 2)))

        alpha = 0.05
        self._noise_floor_rms = (1.0 - alpha) * self._noise_floor_rms + alpha * measured_rms
        self._noise_floor_rms = max(0.0001, min(0.05, self._noise_floor_rms))
        return self._noise_floor_rms

    def estimate_snr_db(self, audio: np.ndarray) -> float:
        """Estimates Signal-to-Noise Ratio (SNR) in dB relative to current noise floor."""
        if len(audio) == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
        snr = 20.0 * np.log10(max(rms, 1e-6) / max(self._noise_floor_rms, 1e-6))
        return float(snr)

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str | None = None,
        utterance_id: str | None = None,
    ) -> tuple[NormalizedASRResult, dict[str, Any]]:
        """Transcribes float32 16kHz audio with multi-signal acoustic gating.

        Returns:
            (NormalizedASRResult, telemetry: dict)
        """
        # Deduplication check
        if utterance_id is not None and utterance_id == self._last_utterance_id and self._last_result is not None:
            cached_res, cached_tele = self._last_result
            tele = dict(cached_tele)
            tele["deduplicated"] = True
            return cached_res, tele

        if len(audio) == 0:
            empty = NormalizedASRResult("", "", [], None, None, [])
            res = (empty, {"latency_ms": 0.0, "audio_duration_s": 0.0, "device": self._device, "deduplicated": False})
            if utterance_id:
                self._last_utterance_id = utterance_id
                self._last_result = res
            return res

        # Ensure float32 normalized [-1.0, 1.0]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        audio_duration = len(audio) / sample_rate
        t_start = time.perf_counter()

        # Multi-signal acoustic energy metrics
        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
        crest_factor = peak / (rms + 1e-9)
        snr_db = self.estimate_snr_db(audio)

        # Dynamic floor with hysteresis:
        # Rejects pure digital silence or flat noise without energy contrast.
        # But if crest_factor is high (> 3.2) and peak > 0.015, allow quiet speech through.
        dynamic_floor = max(0.0035, self._noise_floor_rms * 1.35)
        is_silence = (rms < 0.0035 and peak < 0.025) or (rms < 0.0018) or (rms < dynamic_floor and snr_db < 3.0 and crest_factor < 3.2)

        if is_silence:
            logger.debug(
                "Audio rejected as silence (rms=%.5f, floor=%.5f, snr=%.1fdB, crest=%.2f)",
                rms, dynamic_floor, snr_db, crest_factor,
            )
            empty = NormalizedASRResult("", "", [], None, None, [])
            res = (empty, {
                "latency_ms": 0.0,
                "audio_duration_s": round(audio_duration, 2),
                "device": self._device,
                "rms": round(rms, 5),
                "snr_db": round(snr_db, 1),
                "crest_factor": round(crest_factor, 2),
                "rejected": "LOW_ENERGY_SILENCE",
                "gate": "acoustic_rms_silence_floor",
                "deduplicated": False,
            })
            if utterance_id:
                self._last_utterance_id = utterance_id
                self._last_result = res
            return res

        if not self.is_available():
            empty = NormalizedASRResult("", "", [], None, None, [])
            res = (empty, {"latency_ms": 0.0, "audio_duration_s": round(audio_duration, 2), "device": self._device, "deduplicated": False})
            if utterance_id:
                self._last_utterance_id = utterance_id
                self._last_result = res
            return res

        valid_segments = []
        try:
            segments, info = self._model.transcribe(
                audio,
                language=language or self.language,
                initial_prompt=self.initial_prompt,
                beam_size=5,
                temperature=0.0,
                vad_filter=False,  # Outer VAD already performed frame endpointing
                no_speech_threshold=0.45,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                condition_on_previous_text=False,
                hallucination_silence_threshold=1.5,
            )
            discarded_segments = 0
            for seg in segments:
                # Filter out segments where Whisper detected silence/no-speech
                if getattr(seg, "no_speech_prob", 0.0) > 0.45:
                    logger.debug("Ignoring segment with high no_speech_prob: %.3f ('%s')", seg.no_speech_prob, seg.text)
                    discarded_segments += 1
                    continue
                if getattr(seg, "avg_logprob", 0.0) < -1.35:
                    logger.debug("Ignoring segment with low avg_logprob: %.3f ('%s')", seg.avg_logprob, seg.text)
                    discarded_segments += 1
                    continue
                valid_segments.append(seg)

            raw_text = " ".join(seg.text for seg in valid_segments).strip()
        except Exception as e:
            logger.error("Transcription error: %s", e)
            raw_text = ""
            discarded_segments = 0

        # YouTube / Outro phantom hallucination gate
        lower_raw = raw_text.lower().strip()
        has_outro_marker = any(marker in lower_raw for marker in self.PHANTOM_OUTRO_MARKERS)
        outro_suppressed = False
        outro_accepted_as_genuine = False

        if has_outro_marker and valid_segments:
            avg_no_speech = float(np.mean([getattr(s, "no_speech_prob", 0.0) for s in valid_segments]))
            avg_logprob = float(np.mean([getattr(s, "avg_logprob", 0.0) for s in valid_segments]))

            # Genuine user speech has:
            # 1. Substantial duration (>= 0.70s)
            # 2. Measurable speech energy (rms >= 0.007 or peak >= 0.035)
            # 3. Confident logprob (>= -0.95) and low no_speech_prob (<= 0.35)
            # 4. Natural crest factor (>= 1.6)
            is_genuine_speech = (
                audio_duration >= 0.70
                and (rms >= 0.007 or peak >= 0.035)
                and avg_no_speech <= 0.35
                and avg_logprob >= -0.95
                and (crest_factor >= 1.2 or rms >= 0.015)
            )

            if is_genuine_speech:
                logger.info(
                    "Outro phrase '%s' verified by genuine acoustic speech evidence (dur=%.2fs, rms=%.4f, snr=%.1fdB, avg_no_speech=%.3f, logprob=%.2f); ACCEPTED",
                    raw_text, audio_duration, rms, snr_db, avg_no_speech, avg_logprob,
                )
                outro_accepted_as_genuine = True
            else:
                logger.info(
                    "Rejected phantom ASR outro hallucination from low-evidence noise: '%s' (dur=%.2fs, rms=%.4f, snr=%.1fdB, avg_no_speech=%.3f, logprob=%.2f)",
                    raw_text, audio_duration, rms, snr_db, avg_no_speech, avg_logprob,
                )
                raw_text = ""
                outro_suppressed = True

        # General acoustic evidence gate:
        # If text was decoded, but the physical audio lacks speech energy (e.g. ambient fan noise / hiss)
        if raw_text and not has_outro_marker:
            if (rms < 0.0035 and snr_db < 3.5 and crest_factor < 2.5) or (audio_duration < 0.35 and rms < 0.006):
                logger.info(
                    "Suppressed acoustic hallucination on low energy noise: '%s' (dur=%.2fs, rms=%.5f, snr=%.1fdB, crest=%.2f)",
                    raw_text, audio_duration, rms, snr_db, crest_factor,
                )
                raw_text = ""
                outro_suppressed = True

        hallucination_suppressed = outro_suppressed or (discarded_segments > 0 and not raw_text)

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        rtf = (latency_ms / 1000.0) / audio_duration if audio_duration > 0 else 0.0

        normalized_res = ASRFinancialNormalizer.normalize(raw_text)
        telemetry = {
            "latency_ms": round(latency_ms, 1),
            "audio_duration_s": round(audio_duration, 2),
            "real_time_factor": round(rtf, 3),
            "device": self._device,
            "compute_type": self._compute_type,
            "rms": round(rms, 5),
            "snr_db": round(snr_db, 1),
            "crest_factor": round(crest_factor, 2),
            "hallucination_suppressed": hallucination_suppressed,
            "outro_accepted_as_genuine": outro_accepted_as_genuine,
            "detected_language": getattr(info, "language", self.language) if "info" in locals() else self.language,
            "deduplicated": False,
        }

        res = (normalized_res, telemetry)
        if utterance_id:
            self._last_utterance_id = utterance_id
            self._last_result = res

        return res

