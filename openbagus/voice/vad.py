"""Local Voice Activity Detection (VAD) using Silero VAD ONNX with adaptive endpointing."""

from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    from faster_whisper.vad import SileroVADModel, get_vad_model
except ImportError:
    SileroVADModel = None
    get_vad_model = None

FRAME_SAMPLES = 512          # 32 ms at 16 kHz
FRAME_DURATION_MS = 32.0


class VoiceActivityDetector:
    """Real-time Voice Activity Detector with silence endpointing and speech start/stop tracking."""

    def __init__(
        self,
        threshold: float = 0.50,
        neg_threshold: float = 0.35,
        silence_timeout_ms: int = 800,
        extended_silence_timeout_ms: int = 1800,
        min_speech_duration_ms: int = 250,
        max_utterance_duration_ms: int = 30000,
        speech_threshold: float | None = None,
        silence_duration_ms: int | None = None,
    ) -> None:
        if speech_threshold is not None:
            threshold = speech_threshold
        if silence_duration_ms is not None:
            silence_timeout_ms = silence_duration_ms

        self.threshold = threshold
        self.neg_threshold = neg_threshold
        self.base_silence_timeout_ms = silence_timeout_ms
        self.extended_silence_timeout_ms = extended_silence_timeout_ms

        self.silence_timeout_chunks = max(1, int(self.base_silence_timeout_ms / FRAME_DURATION_MS))
        self.extended_silence_timeout_chunks = max(1, int(self.extended_silence_timeout_ms / FRAME_DURATION_MS))
        self._current_silence_timeout_chunks = self.silence_timeout_chunks

        self.min_speech_chunks = max(1, int(min_speech_duration_ms / FRAME_DURATION_MS))
        self.max_utterance_chunks = int(max_utterance_duration_ms / FRAME_DURATION_MS)

        self._model: SileroVADModel | None = None
        self._is_speech_active = False
        self._speech_chunks = 0
        self._silence_chunks = 0
        self._total_chunks = 0
        self._energy_floor = 1e-4

        self._init_model()


    def _init_model(self) -> None:
        if get_vad_model is not None:
            try:
                self._model = get_vad_model()
            except Exception as e:
                logger.warning("Failed to initialize Silero VAD model: %s", e)
                self._model = None

    def reset(self) -> None:
        """Resets detector state for a new conversational turn."""
        self._is_speech_active = False
        self._speech_chunks = 0
        self._silence_chunks = 0
        self._total_chunks = 0
        self._current_silence_timeout_chunks = self.silence_timeout_chunks

    def set_extended_silence(self, extended: bool = True) -> None:
        """Dynamically toggles extended silence window for incomplete turns."""
        self._current_silence_timeout_chunks = (
            self.extended_silence_timeout_chunks if extended else self.silence_timeout_chunks
        )

    @property
    def is_extended(self) -> bool:
        """Returns True if detector is currently using the extended silence timeout."""
        return self._current_silence_timeout_chunks == self.extended_silence_timeout_chunks

    @property
    def silence_duration_ms(self) -> float:
        return self._silence_chunks * FRAME_DURATION_MS

    def is_acoustic_pause(self, min_ms: int = 650) -> bool:
        """Returns True if user has paused speaking for at least min_ms."""
        return self._is_speech_active and (self.silence_duration_ms >= min_ms)

    @property
    def is_speech_active(self) -> bool:
        return self._is_speech_active

    def _score_frame(self, frame: np.ndarray, energy: float | None = None) -> float:
        if energy is None:
            energy = float(np.mean(frame ** 2))
        if self._model is not None and energy > self._energy_floor:
            try:
                out = self._model(frame, num_samples=FRAME_SAMPLES)
                return float(out[0]) if len(out) > 0 else 0.0
            except Exception as e:
                logger.debug("VAD inference error: %s", e)
                return 0.5 if energy > 0.001 else 0.0
        return 0.6 if energy > 0.005 else 0.0

    def process_frame(self, frame: np.ndarray) -> tuple[bool, bool, float]:
        """Processes a 512-sample (16kHz float32) frame.

        Returns:
            (is_speech_active: bool, is_endpoint: bool, speech_probability: float)
        """
        # Ensure 512 samples
        if len(frame) != FRAME_SAMPLES:
            if len(frame) > FRAME_SAMPLES:
                frame = frame[:FRAME_SAMPLES]
            else:
                frame = np.pad(frame, (0, FRAME_SAMPLES - len(frame)), mode="constant")

        # Energy threshold check for noise floor
        energy = float(np.mean(frame ** 2))
        prob = self._score_frame(frame, energy)

        is_endpoint = False
        self._total_chunks += 1

        if not self._is_speech_active:
            # Check for speech onset
            if prob >= self.threshold:
                self._speech_chunks += 1
                if self._speech_chunks >= self.min_speech_chunks:
                    self._is_speech_active = True
                    self._silence_chunks = 0
            else:
                self._speech_chunks = max(0, self._speech_chunks - 1)
        else:
            # Currently in active speech
            if prob < self.neg_threshold:
                self._silence_chunks += 1
                # Check for silence timeout endpointing using adaptive chunks
                if self._silence_chunks >= self._current_silence_timeout_chunks:
                    is_endpoint = True
            else:
                self._silence_chunks = max(0, self._silence_chunks - 1)

            # Maximum utterance safeguard
            if self._total_chunks >= self.max_utterance_chunks:
                is_endpoint = True

        return self._is_speech_active, is_endpoint, prob

