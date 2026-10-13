"""Local Indonesian Text-to-Speech (TTS) engine using Piper with sentence-level streaming."""

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
except ImportError:
    piper = None


class LocalTTSEngine:
    """Ultra-fast local Indonesian voice synthesis engine using Piper ONNX."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        self.speed = speed
        self.volume = max(0.0, min(1.0, volume))
        self._voice: Any = None
        self._sample_rate = 22050
        self._lock = threading.Lock()

        self._model_path, self._config_path = self._resolve_model_paths(model_path, config_path)
        self._init_voice()

    def _resolve_model_paths(self, m_path: str | Path | None, c_path: str | Path | None) -> tuple[Path, Path]:
        base_dir = Path(os.environ.get("LOCALAPPDATA", "C:/Users/bagus/AppData/Local")) / "OpenBagus" / "models" / "tts"
        m = Path(m_path) if m_path else (base_dir / "id_ID-news_tts-medium.onnx")
        c = Path(c_path) if c_path else (base_dir / "id_ID-news_tts-medium.onnx.json")
        return m, c

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
            logger.info("Piper voice loaded successfully (sample rate: %d Hz)", self._sample_rate)
            # Warm-up pass so onnxruntime operators and threadpools are initialized
            try:
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
        """Synthesizes a single sentence to a float32 audio array."""
        if not self.is_available() or not sentence.strip():
            return None

        clean = SpeechTextNormalizer.to_spoken_text(sentence)
        if not clean:
            return None

        with self._lock:
            try:
                chunks = list(self._voice.synthesize(clean))
                if not chunks:
                    return None
                # Concatenate chunk arrays for the sentence
                audio = np.concatenate([c.audio_float_array for c in chunks])
                if self.volume != 1.0:
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
            }

            yield audio, telemetry
