"""Local Indonesian Text-to-Speech (TTS) engine using Piper with sentence-level streaming.

Provides distinctive BAGUSMAX_GENTLE_ID voice preset (calm, measured, caring demeanor inspired by Baymax)
and zero-disk memory-only audio synthesis.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator
import numpy as np

from openbagus.voice.speech_normalizer import SpeechTextNormalizer

logger = logging.getLogger(__name__)

try:
    import piper
    from piper.config import SynthesisConfig
except ImportError:
    piper = None
    SynthesisConfig = None  # type: ignore

_SHARED_PIPER_VOICE: Any = None
_SHARED_PIPER_SAMPLE_RATE: int = 22050
_SHARED_PIPER_KEY: Any = None

_SHARED_PIPER_EN_VOICE: Any = None
_SHARED_PIPER_EN_KEY: Any = None

# Canonical voice presets and aliases
VOICE_PRESETS: dict[str, dict[str, float]] = {
    "BAGUSMAX_GENTLE_ID": {
        "length_scale": 1.06,  # Calmer, measured, caring healthcare robot tempo
        "noise_scale": 0.52,   # Softer, gentle articulation with low noise
        "noise_w_scale": 0.70, # Steady phoneme duration
    },
    "BAGUSMAX_CALM": {
        "length_scale": 1.08,
        "noise_scale": 0.55,
        "noise_w_scale": 0.70,
    },
    "BAGUSMAX_CALM_ID": {
        "length_scale": 1.06,
        "noise_scale": 0.52,
        "noise_w_scale": 0.70,
    },
    "BAGUSMAX_SOFT": {
        "length_scale": 1.10,  # Warmer lower register with gentle delivery
        "noise_scale": 0.50,
        "noise_w_scale": 0.70,
    },
    "NATURAL": {
        "length_scale": 1.00,  # Standard baseline newsreader speed
        "noise_scale": 0.667,
        "noise_w_scale": 0.80,
    },
    "STANDARD": {
        "length_scale": 1.00,
        "noise_scale": 0.667,
        "noise_w_scale": 0.80,
    },
    "FAST": {
        "length_scale": 0.90,
        "noise_scale": 0.667,
        "noise_w_scale": 0.80,
    },
}

PRESET_ALIASES: dict[str, str] = {
    "BAGUSMAX": "BAGUSMAX_GENTLE_ID",
    "GENTLE": "BAGUSMAX_GENTLE_ID",
    "DEFAULT": "BAGUSMAX_GENTLE_ID",
    "BAGUSMAX_GENTLE": "BAGUSMAX_GENTLE_ID",
    "CALM": "BAGUSMAX_CALM",
    "SOFT": "BAGUSMAX_SOFT",
    "NATURAL": "NATURAL",
    "STANDARD": "NATURAL",
    "NORMAL": "NATURAL",
}


class LocalTTSEngine:
    """Ultra-fast local Indonesian voice synthesis engine using Piper ONNX."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        preset: str = "BAGUSMAX_GENTLE_ID",
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        self.preset = self._resolve_preset_name(preset)
        preset_cfg = VOICE_PRESETS[self.preset]
        self.length_scale = preset_cfg["length_scale"]
        self.noise_scale = preset_cfg["noise_scale"]
        self.noise_w_scale = preset_cfg["noise_w_scale"]

        self.speed = speed
        self.volume = max(0.0, min(1.0, volume))
        self._voice: Any = None
        self._sample_rate = 22050
        self._lock = threading.Lock()

        self.active_language: str = "id-ID"
        self._en_voice: Any = None
        self._en_sample_rate: int = 22050
        
        try:
            from openbagus.core.model_resolver import get_model_resolver
            self._en_model_path, self._en_config_path = get_model_resolver().get_english_tts_paths()
        except Exception:
            base_dir = Path(os.environ.get("OPENBAGUS_MODEL_DIR", "E:/Projects/OpenBagus/models")) / "tts" / "english" / "norman-medium"
            self._en_model_path = base_dir / "en_US-norman-medium.onnx"
            self._en_config_path = base_dir / "en_US-norman-medium.onnx.json"

        # Real-time voice profile processor (gentle warmth, high smoothing, robot resonance)
        from openbagus.voice.voice_processor import VoiceProfileProcessor
        self.processor = VoiceProfileProcessor(preset=self.preset)

        self._model_path, self._config_path = self._resolve_model_paths(model_path, config_path)
        self._init_voice()
        self._init_english_voice()

    @staticmethod
    def _resolve_preset_name(name: str) -> str:
        clean = name.upper().strip()
        if clean in VOICE_PRESETS:
            return clean
        if clean in PRESET_ALIASES:
            return PRESET_ALIASES[clean]
        return "BAGUSMAX_GENTLE_ID"

    def set_active_language(self, lang: str) -> None:
        """Sets the active voice output language (e.g. 'en-US' or 'id-ID')."""
        clean = lang.strip().lower()
        if "en" in clean:
            self.active_language = "en-US"
        else:
            self.active_language = "id-ID"
        logger.info("Active TTS language set to: %s", self.active_language)

    def is_english_available(self) -> bool:
        return self._en_voice is not None

    def _init_english_voice(self) -> None:
        if piper is None:
            return
        if not self._en_model_path.exists() or not self._en_config_path.exists():
            return
        global _SHARED_PIPER_EN_VOICE, _SHARED_PIPER_EN_KEY, _SHARED_PIPER_VOICE, _SHARED_PIPER_KEY
        key = (str(self._en_model_path), str(self._en_config_path))
        if _SHARED_PIPER_EN_VOICE is not None and _SHARED_PIPER_EN_KEY == key:
            self._en_voice = _SHARED_PIPER_EN_VOICE
            return
        if _SHARED_PIPER_VOICE is not None and _SHARED_PIPER_KEY == key:
            self._en_voice = _SHARED_PIPER_VOICE
            return
        try:
            self._en_voice = piper.PiperVoice.load(str(self._en_model_path), config_path=str(self._en_config_path))
            _SHARED_PIPER_EN_VOICE = self._en_voice
            _SHARED_PIPER_EN_KEY = key
            logger.info("Piper English male voice (Norman) loaded successfully")
        except Exception as e:
            logger.warning("Could not load Piper English voice: %s", e)
            self._en_voice = None

    def detect_sentence_language(self, text: str) -> str:
        low = text.lower()
        id_markers = ("karena", "kata", "kalimat", "menggunakan", "adalah", "sebaiknya", "tata bahasa", "koreksi", "penjelasan", "artinya", "dalam", "bukan", "sudah", "ini", "itu", "catatan")
        if any(re.search(r"\b" + m + r"\b", low) for m in id_markers) or "[koreksi" in low:
            return "id-ID"
        en_markers = ("hello", "the", "is", "are", "you", "your", "would", "what", "how", "great", "good", "thank", "i", "can", "to", "in", "it", "we")
        if any(re.search(r"\b" + m + r"\b", low) for m in en_markers):
            return "en-US"
        return self.active_language

    def set_preset(self, preset_name: str) -> bool:
        """Switches the active voice preset safely across engine and processor."""
        canonical = self._resolve_preset_name(preset_name)
        if canonical in VOICE_PRESETS:
            self.preset = canonical
            p = VOICE_PRESETS[canonical]
            self.length_scale = p["length_scale"]
            self.noise_scale = p["noise_scale"]
            self.noise_w_scale = p["noise_w_scale"]
            if hasattr(self, "processor") and self.processor is not None:
                self.processor.set_preset(canonical)
            logger.info("Voice preset set to: %s", canonical)
            return True
        logger.warning("Unknown voice preset: %s", preset_name)
        return False

    def get_voice_status(self) -> dict[str, Any]:
        """Returns structured introspection of current TTS engine status."""
        return {
            "active_preset": self.preset,
            "active_language": self.active_language,
            "length_scale": self.length_scale,
            "noise_scale": self.noise_scale,
            "noise_w_scale": self.noise_w_scale,
            "sample_rate": self._sample_rate,
            "volume": self.volume,
            "model_path": str(self._model_path),
            "is_available": self.is_available(),
            "is_english_available": self.is_english_available(),
            "english_model_id": "rhasspy/piper-voices/en/en_US/norman/medium",
            "model_architecture": "Piper VITS/ONNX",
            "is_single_speaker": True,
            "base_model_id": "rhasspy/piper-voices/id/id_ID/news_tts/medium",
            "base_speaker_timbre": "FEMALE_NEWSREADER",
            "character_styling": "BAGUSMAX_GENTLE_ROBOT",
            "available_presets": ["BAGUSMAX_GENTLE_ID", "NATURAL", "BAGUSMAX_CALM", "BAGUSMAX_SOFT"],
        }

    def _resolve_model_paths(self, m_path: str | Path | None, c_path: str | Path | None) -> tuple[Path, Path]:
        if m_path and c_path:
            return Path(m_path), Path(c_path)
        try:
            from openbagus.core.model_resolver import get_model_resolver
            canon_m, canon_c = get_model_resolver().get_indonesian_tts_paths()
            m = Path(m_path) if m_path else canon_m
            c = Path(c_path) if c_path else canon_c
            return m, c
        except Exception:
            base_dir = Path(os.environ.get("OPENBAGUS_MODEL_DIR", "E:/Projects/OpenBagus/models")) / "tts" / "indonesian"
            m = Path(m_path) if m_path else (base_dir / "id_ID-news_tts-medium.onnx")
            c = Path(c_path) if c_path else (base_dir / "id_ID-news_tts-medium.onnx.json")
            return m, c

    def _get_synthesis_config(self) -> Any:
        if SynthesisConfig is not None:
            eff_length_scale = self.length_scale / max(0.5, self.speed)
            return SynthesisConfig(
                length_scale=eff_length_scale,
                noise_scale=self.noise_scale,
                noise_w_scale=self.noise_w_scale,
                volume=self.volume,
            )
        return None

    def _init_voice(self) -> None:
        if piper is None:
            logger.warning("piper-tts is not installed")
            return

        if not self._model_path.exists() or not self._config_path.exists():
            logger.warning("Piper voice files not found at %s", self._model_path)
            return

        global _SHARED_PIPER_VOICE, _SHARED_PIPER_SAMPLE_RATE, _SHARED_PIPER_KEY, _SHARED_PIPER_EN_VOICE, _SHARED_PIPER_EN_KEY
        key = (str(self._model_path), str(self._config_path))
        if _SHARED_PIPER_VOICE is not None and _SHARED_PIPER_KEY == key:
            self._voice = _SHARED_PIPER_VOICE
            self._sample_rate = _SHARED_PIPER_SAMPLE_RATE
            return
        if _SHARED_PIPER_EN_VOICE is not None and _SHARED_PIPER_EN_KEY == key:
            self._voice = _SHARED_PIPER_EN_VOICE
            self._sample_rate = getattr(self._voice.config, "sample_rate", 22050)
            return

        try:
            logger.info("Loading Piper Indonesian voice from %s...", self._model_path)
            self._voice = piper.PiperVoice.load(str(self._model_path), config_path=str(self._config_path))
            self._sample_rate = getattr(self._voice.config, "sample_rate", 22050)
            logger.info("Piper voice loaded successfully (sample rate: %d Hz, preset: %s)", self._sample_rate, self.preset)
            try:
                syn_cfg = self._get_synthesis_config()
                if syn_cfg:
                    list(self._voice.synthesize("siap", syn_config=syn_cfg))
                else:
                    list(self._voice.synthesize("siap"))
            except Exception:
                pass
            _SHARED_PIPER_VOICE = self._voice
            _SHARED_PIPER_SAMPLE_RATE = self._sample_rate
            _SHARED_PIPER_KEY = key
        except Exception as e:
            logger.error("Failed to load Piper voice: %s", e)
            self._voice = None

    def is_available(self) -> bool:
        return self._voice is not None

    @property
    def model_path(self) -> Path:
        return self._model_path

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def synthesize_sentence(self, sentence: str, lang: str | None = None) -> np.ndarray | None:
        """Synthesizes a single sentence to a float32 audio array in memory with zero disk writes.

        Supports bilingual switching:
        - If target language is English ('en-US') and English model is available, routes to Piper Norman.
        - Otherwise, routes to Indonesian Bagusmax with length-preserving DSP.
        """
        if not self.is_available() and not self.is_english_available():
            return None
        if not sentence.strip():
            return None

        clean = SpeechTextNormalizer.to_spoken_text(sentence)
        if not clean:
            return None

        target_lang = lang or self.detect_sentence_language(clean)
        use_english = (target_lang == "en-US" or "en" in target_lang) and self._en_voice is not None

        with self._lock:
            try:
                voice_obj = self._en_voice if use_english else self._voice
                if voice_obj is None:
                    return None

                syn_cfg = self._get_synthesis_config()
                if syn_cfg is not None:
                    chunks = list(voice_obj.synthesize(clean, syn_config=syn_cfg))
                else:
                    chunks = list(voice_obj.synthesize(clean))

                if not chunks:
                    return None
                audio = np.concatenate([c.audio_float_array for c in chunks])
                if syn_cfg is None and self.volume != 1.0:
                    audio = audio * self.volume

                # Only apply Indonesian chest warmth/de-essing DSP to the Indonesian newsreader model
                if not use_english and hasattr(self, "processor") and self.processor is not None:
                    audio = self.processor.process(audio, sample_rate=self._sample_rate)
                return audio
            except Exception as e:
                logger.error("Sentence synthesis error for '%s' (lang=%s): %s", sentence[:30], target_lang, e)
                return None

    def synthesize_stream(
        self,
        text: str,
        stop_event: threading.Event | None = None,
    ) -> Iterator[tuple[np.ndarray, dict[str, Any]]]:
        """Progressively synthesizes sentences yielding audio chunks as soon as ready."""
        if not self.is_available() or not text.strip():
            return

        spoken_text = SpeechTextNormalizer.to_spoken_text(text)
        sentences = SpeechTextNormalizer.split_sentences(spoken_text)
        if not sentences and spoken_text:
            sentences = [spoken_text]

        t_start = time.perf_counter()
        first_chunk_sent = False

        for idx, sent in enumerate(sentences):
            if stop_event and stop_event.is_set():
                logger.info("Speech synthesis cancelled mid-stream")
                break

            t_s = time.perf_counter()
            audio = self.synthesize_sentence(sent)
            if audio is None or len(audio) == 0:
                continue

            dt_sent = (time.perf_counter() - t_s) * 1000.0
            ttfa = (time.perf_counter() - t_start) * 1000.0 if not first_chunk_sent else dt_sent
            first_chunk_sent = True

            telemetry = {
                "sentence_index": idx,
                "total_sentences": len(sentences),
                "sentence_text": sent,
                "latency_ms": round(dt_sent, 1),
                "time_to_first_audio_ms": round(ttfa, 1),
                "audio_duration_s": round(len(audio) / self._sample_rate, 2),
                "sample_rate": self._sample_rate,
                "preset": self.preset,
            }

            yield audio, telemetry
