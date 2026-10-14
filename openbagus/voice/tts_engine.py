"""Local Indonesian Text-to-Speech (TTS) engine using Piper with sentence-level streaming.

Provides distinctive BAGUSMAX_CALM_ID voice preset (calm, soft, caring demeanor inspired by Baymax)
and zero-disk memory-only audio synthesis.
"""

from __future__ import annotations

import logging
import os
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

# Character voice presets
VOICE_PRESETS: dict[str, dict[str, float]] = {
    "BAGUSMAX_CALM_ID": {
        "length_scale": 1.08,  # Calmer, measured, caring healthcare robot tempo
        "noise_scale": 0.55,   # Softer, gentle articulation with low noise
        "noise_w_scale": 0.70, # Steady phoneme duration
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


class LocalTTSEngine:
    """Ultra-fast local Indonesian voice synthesis engine using Piper ONNX."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        preset: str = "BAGUSMAX_CALM_ID",
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        self.preset = preset if preset in VOICE_PRESETS else "BAGUSMAX_CALM_ID"
        preset_cfg = VOICE_PRESETS[self.preset]
        self.length_scale = preset_cfg["length_scale"]
        self.noise_scale = preset_cfg["noise_scale"]
        self.noise_w_scale = preset_cfg["noise_w_scale"]

        self.speed = speed
        self.volume = max(0.0, min(1.0, volume))
        self._voice: Any = None
        self._sample_rate = 22050
        self._lock = threading.Lock()

        self._model_path, self._config_path = self._resolve_model_paths(model_path, config_path)
        self._init_voice()

    def set_preset(self, preset_name: str) -> bool:
        """Switches the active voice preset."""
        if preset_name in VOICE_PRESETS:
            self.preset = preset_name
            p = VOICE_PRESETS[preset_name]
            self.length_scale = p["length_scale"]
            self.noise_scale = p["noise_scale"]
            self.noise_w_scale = p["noise_w_scale"]
            logger.info("Voice preset set to: %s", preset_name)
            return True
        logger.warning("Unknown voice preset: %s", preset_name)
        return False

    def _resolve_model_paths(self, m_path: str | Path | None, c_path: str | Path | None) -> tuple[Path, Path]:
        base_dir = Path(os.environ.get("LOCALAPPDATA", "C:/Users/bagus/AppData/Local")) / "OpenBagus" / "models" / "tts"
        m = Path(m_path) if m_path else (base_dir / "id_ID-news_tts-medium.onnx")
        c = Path(c_path) if c_path else (base_dir / "id_ID-news_tts-medium.onnx.json")
        return m, c

    def _get_synthesis_config(self) -> Any:
        if SynthesisConfig is not None:
            # Adjust length scale by user speed setting (higher speed -> lower length_scale)
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

        try:
            logger.info("Loading Piper Indonesian voice from %s...", self._model_path)
            self._voice = piper.PiperVoice.load(str(self._model_path), config_path=str(self._config_path))
            self._sample_rate = getattr(self._voice.config, "sample_rate", 22050)
            logger.info("Piper voice loaded successfully (sample rate: %d Hz, preset: %s)", self._sample_rate, self.preset)
            # Warm-up pass so onnxruntime operators and threadpools are initialized
            try:
                syn_cfg = self._get_synthesis_config()
                if syn_cfg:
                    list(self._voice.synthesize("siap", syn_config=syn_cfg))
                else:
                    list(self._voice.synthesize("siap"))
            except Exception:
                pass
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

    def synthesize_sentence(self, sentence: str) -> np.ndarray | None:
        """Synthesizes a single sentence to a float32 audio array in memory with zero disk writes."""
        if not self.is_available() or not sentence.strip():
            return None

        clean = SpeechTextNormalizer.to_spoken_text(sentence)
        if not clean:
            return None

        with self._lock:
            try:
                syn_cfg = self._get_synthesis_config()
                if syn_cfg is not None:
                    chunks = list(self._voice.synthesize(clean, syn_config=syn_cfg))
                else:
                    chunks = list(self._voice.synthesize(clean))

                if not chunks:
                    return None
                # Concatenate in-memory chunk arrays for the sentence
                audio = np.concatenate([c.audio_float_array for c in chunks])
                if syn_cfg is None and self.volume != 1.0:
                    audio = audio * self.volume
                return audio
            except Exception as e:
                logger.error("Sentence synthesis error for '%s': %s", sentence[:30], e)
                return None

    def synthesize_stream(
        self,
        text: str,
        stop_event: threading.Event | None = None,
    ) -> Iterator[tuple[np.ndarray, dict[str, Any]]]:
        """Progressively synthesizes sentences yielding audio chunks as soon as ready.

        Yields:
            (audio_array: np.ndarray, sentence_telemetry: dict)
        """
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
