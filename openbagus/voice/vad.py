"""Local Voice Activity Detection (VAD) using stateful Silero VAD ONNX with adaptive endpointing."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort
except ImportError:
    ort = None

try:
    from faster_whisper.vad import SileroVADModel, get_vad_model
except ImportError:
    SileroVADModel = None
    get_vad_model = None

FRAME_SAMPLES = 512          # 32 ms at 16 kHz
FRAME_DURATION_MS = 32.0
CONTEXT_SIZE_SAMPLES = 64    # Required input context for Silero VAD (512 + 64 = 576 samples)


class VoiceActivityDetector:
    """Real-time stateful Voice Activity Detector with silence endpointing, recurrent hidden states, and speech evidence tracking."""

    def __init__(
        self,
        threshold: float = 0.55,
        neg_threshold: float = 0.35,
        silence_timeout_ms: int = 1300,
        extended_silence_timeout_ms: int = 2500,
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

        self._session: ort.InferenceSession | None = None
        self._fallback_model: Any = None
        self._degraded = False

        # Persistent recurrent state for streaming ONNX inference
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SIZE_SAMPLES), dtype=np.float32)

        self._is_speech_active = False
        self._speech_chunks = 0
        self._silence_chunks = 0
        self._total_chunks = 0
        self._noise_floor_rms = 0.0015

        # Detailed utterance speech provenance tracking
        self._utterance_speech_frames = 0
        self._utterance_total_frames = 0
        self._utterance_probs: list[float] = []

        self._model: Any = None
        self._audio_context: deque[np.ndarray] = deque(maxlen=32)

        self._init_model()

    def _init_model(self) -> None:
        """Initializes stateful ONNX session with the local Silero VAD model."""
        try:
            from openbagus.core.model_resolver import get_model_resolver
            vad_path = get_model_resolver().get_silero_vad_path()
            if ort is not None and vad_path.is_file():
                opts = ort.SessionOptions()
                opts.inter_op_num_threads = 1
                opts.intra_op_num_threads = 1
                opts.enable_cpu_mem_arena = False
                opts.log_severity_level = 4
                self._session = ort.InferenceSession(
                    str(vad_path),
                    providers=["CPUExecutionProvider"],
                    sess_options=opts,
                )
                logger.info("Stateful Silero VAD ONNX session initialized from: %s", vad_path)
                return
        except Exception as e:
            logger.debug("Silero VAD direct ONNX initialization notice: %s", e)

        # Fallback to faster_whisper wrapper if direct ONNX unavailable
        if SileroVADModel is not None:
            try:
                from openbagus.core.model_resolver import get_model_resolver
                vad_path = get_model_resolver().get_silero_vad_path()
                if vad_path.is_file():
                    self._fallback_model = SileroVADModel(str(vad_path))
                    logger.info("Silero VAD loaded via fallback SileroVADModel: %s", vad_path)
                    return
            except Exception as e_fb:
                logger.debug("Fallback model error: %s", e_fb)

        if get_vad_model is not None:
            try:
                self._fallback_model = get_vad_model()
                logger.info("Silero VAD initialized via default get_vad_model")
                return
            except Exception as e_gvm:
                logger.warning("Failed to initialize default VAD model: %s", e_gvm)

        self._degraded = True
        logger.warning("VAD_DEGRADED: Silero VAD neural model unavailable; voice activity detector in degraded mode")

    @property
    def degraded(self) -> bool:
        return self._degraded

    def reset(self) -> None:
        """Resets detector state and recurrent hidden memory for a new conversational turn."""
        self._is_speech_active = False
        self._speech_chunks = 0
        self._silence_chunks = 0
        self._total_chunks = 0
        self._current_silence_timeout_chunks = self.silence_timeout_chunks

        # Zero recurrent memory across stream boundaries
        self._h.fill(0.0)
        self._c.fill(0.0)
        self._context.fill(0.0)

        # Reset utterance evidence accumulators
        self._utterance_speech_frames = 0
        self._utterance_total_frames = 0
        self._utterance_probs.clear()

    def set_extended_silence(self, extended: bool = True) -> None:
        """Dynamically toggles extended silence window for incomplete turns."""
        self._current_silence_timeout_chunks = (
            self.extended_silence_timeout_chunks if extended else self.silence_timeout_chunks
        )

    @property
    def current_silence_timeout_ms(self) -> int:
        return int(self._current_silence_timeout_chunks * FRAME_DURATION_MS)

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

    def update_noise_floor(self, frame_rms: float) -> float:
        """Adapts background noise floor estimate using exponential moving average."""
        alpha = 0.05
        self._noise_floor_rms = (1.0 - alpha) * self._noise_floor_rms + alpha * max(0.0005, frame_rms)
        self._noise_floor_rms = max(0.0005, min(0.04, self._noise_floor_rms))
        return self._noise_floor_rms

    def get_utterance_evidence(self) -> dict[str, Any]:
        """Returns acoustic and VAD evidence accumulated for the current completed utterance."""
        total = max(1, self._utterance_total_frames)
        speech_frames = self._utterance_speech_frames
        ratio = speech_frames / total
        max_prob = max(self._utterance_probs) if self._utterance_probs else 0.0
        active_probs = [p for p in self._utterance_probs if p >= self.threshold]
        mean_prob = float(np.mean(active_probs)) if active_probs else 0.0

        return {
            "speech_frames": speech_frames,
            "total_frames": total,
            "speech_ratio": round(ratio, 3),
            "max_prob": round(max_prob, 3),
            "mean_speech_prob": round(mean_prob, 3),
            "speech_duration_s": round(speech_frames * (FRAME_DURATION_MS / 1000.0), 3),
            "total_duration_s": round(total * (FRAME_DURATION_MS / 1000.0), 3),
            "noise_floor_rms": round(self._noise_floor_rms, 5),
            "is_degraded": self._degraded,
        }

    def _score_frame(self, frame: np.ndarray, energy: float | None = None) -> float:
        """Scores a single 512-sample frame using persistent recurrent state."""
        if energy is None:
            energy = float(np.mean(frame ** 2))
        frame_rms = float(np.sqrt(max(0.0, energy)))

        # Dynamic ambient noise floor gate: reject frames below ambient room/fan envelope
        dynamic_floor = max(0.0018, self._noise_floor_rms * 1.30)
        if frame_rms < dynamic_floor:
            if not self._is_speech_active:
                self.update_noise_floor(frame_rms)
            return 0.0

        # Injected or mocked _model support (for tests and custom pipelines)
        if self._model is not None:
            self._audio_context.append(frame.copy())
            try:
                out = self._model(np.concatenate(self._audio_context), num_samples=FRAME_SAMPLES)
                return float(np.asarray(out).reshape(-1)[-1]) if len(out) > 0 else 0.0
            except Exception as e:
                logger.debug("VAD _model error: %s", e)
                return 0.0

        # Stateful direct ONNX streaming inference (official 576-sample format: 64 context + 512 frame)
        if self._session is not None:
            try:
                inp = np.concatenate([self._context, frame.reshape(1, FRAME_SAMPLES)], axis=1)
                out, hn, cn = self._session.run(
                    None,
                    {"input": inp, "h": self._h, "c": self._c},
                )
                self._h = hn
                self._c = cn
                self._context = frame[-CONTEXT_SIZE_SAMPLES:].reshape(1, CONTEXT_SIZE_SAMPLES)
                return float(out[0]) if len(out) > 0 else 0.0
            except Exception as e:
                logger.debug("Stateful VAD ONNX error: %s", e)
                return 0.0

        # Fallback wrapper if direct session is unavailable
        if self._fallback_model is not None:
            try:
                out = self._fallback_model(frame, num_samples=FRAME_SAMPLES)
                return float(np.asarray(out).reshape(-1)[-1]) if len(out) > 0 else 0.0
            except Exception as e_fb:
                logger.debug("Fallback VAD inference error: %s", e_fb)
                return 0.0

        return 0.0

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
                    self._total_chunks = self._speech_chunks
                    self._silence_chunks = 0
                    self._utterance_speech_frames = self._speech_chunks
                    self._utterance_total_frames = self._speech_chunks
                    self._utterance_probs = [prob] * self._speech_chunks
            else:
                self._speech_chunks = max(0, self._speech_chunks - 1)
        else:
            # Currently in active speech
            self._utterance_total_frames += 1
            self._utterance_probs.append(prob)
            if prob >= self.threshold:
                self._utterance_speech_frames += 1

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
