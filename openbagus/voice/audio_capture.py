"""Real-time microphone capture with sample-rate conversion, pre-roll buffering, and level metering."""

from __future__ import annotations

import collections
import logging
import math
import queue
import threading
import time
from typing import Callable
import numpy as np

from openbagus.voice.audio_devices import AudioDeviceManager

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
except ImportError:
    sd = None

TARGET_SAMPLE_RATE = 16000  # 16 kHz standard for Whisper and Silero VAD
CHUNK_DURATION_MS = 32      # 32 ms frame (512 samples at 16 kHz)
TARGET_CHUNK_SAMPLES = int(TARGET_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 512 samples


class AudioCaptureStream:
    """Manages low-latency native microphone capture, resampling, and audio queueing."""

    def __init__(
        self,
        device_id: int | None = None,
        target_sample_rate: int = TARGET_SAMPLE_RATE,
        pre_roll_ms: int = 300,
        level_callback: Callable[[float], None] | None = None,
    ) -> None:
        self.target_sample_rate = target_sample_rate
        self.pre_roll_chunks = max(1, int(pre_roll_ms / CHUNK_DURATION_MS))
        self.level_callback = level_callback
        self.device_id = device_id

        self._stream: Any = None
        self._is_capturing = False
        self._is_muted = False
        self._lock = threading.Lock()

        # Circular buffer for pre-roll to prevent clipping the first syllable
        self._pre_roll_buffer: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_chunks)

        # Synchronized frame queue to prevent duplicate frame processing in turn controller loop
        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=120)

        # Active speech frames buffer for current utterance
        self._active_utterance_frames: list[np.ndarray] = []
        self._is_utterance_active = False

        self._device_sample_rate = 16000
        self._device_channels = 1
        self._current_level_db = -100.0
        self._suppress_until: float = 0.0

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    def set_muted(self, muted: bool) -> None:
        self._is_muted = muted

    def suppress_input(self, duration_ms: int = 250) -> None:
        """Temporarily suppresses microphone capture to guard against acoustic echo and room reverberation."""
        import time as _time
        with self._lock:
            self._suppress_until = _time.monotonic() + (duration_ms / 1000.0)
            self._pre_roll_buffer.clear()
            self._active_utterance_frames.clear()
            self._is_utterance_active = False
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                except Exception:
                    break

    @staticmethod
    def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
        if audio.ndim > 1 and audio.shape[1] > 1:
            mono = np.mean(audio, axis=1, dtype=np.float32)
        else:
            mono = audio.flatten().astype(np.float32)
        if orig_sr == target_sr:
            return mono
        target_len = int(len(mono) * target_sr / orig_sr)
        if target_len <= 0:
            return np.empty(0, dtype=np.float32)
        return np.interp(
            np.linspace(0, len(mono), target_len, endpoint=False),
            np.arange(len(mono)),
            mono,
        ).astype(np.float32)

    @staticmethod
    def calculate_rms_db(audio: np.ndarray) -> float:
        if len(audio) == 0:
            return -100.0
        rms = float(np.sqrt(np.mean(audio ** 2)))
        db = 20.0 * math.log10(rms + 1e-9)
        return max(-100.0, min(0.0, db))

    def get_current_level_db(self) -> float:
        return self._current_level_db

    def start(self) -> bool:
        """Starts real-time microphone stream."""
        if not AudioDeviceManager.is_available():
            logger.error("Sounddevice not available for audio capture")
            return False

        with self._lock:
            if self._is_capturing:
                return True

            dev = None
            if self.device_id is not None:
                try:
                    dev = sd.query_devices(self.device_id)
                except Exception:
                    dev = None
            if not dev:
                default_in = AudioDeviceManager.get_default_input_device()
                self.device_id = default_in.id if default_in else None
                if self.device_id is not None:
                    dev = sd.query_devices(self.device_id)

            if not dev:
                logger.error("No valid microphone input device found")
                return False

            self._device_sample_rate = int(dev.get("default_samplerate", 44100))
            self._device_channels = min(2, max(1, int(dev.get("max_input_channels", 1))))

            # Buffer size matching ~32ms on native device
            blocksize = int(self._device_sample_rate * CHUNK_DURATION_MS / 1000)

            try:
                self._stream = sd.InputStream(
                    device=self.device_id,
                    channels=self._device_channels,
                    samplerate=self._device_sample_rate,
                    blocksize=blocksize,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._is_capturing = True
                logger.info("Microphone stream started on device %s (%d Hz)", self.device_id, self._device_sample_rate)
                return True
            except Exception as e:
                logger.error("Failed to start microphone stream: %s", e)
                self._stream = None
                self._is_capturing = False
                return False

    def stop(self) -> None:
        """Stops microphone stream safely."""
        with self._lock:
            if not self._is_capturing:
                return
            self._is_capturing = False
            stream = self._stream
            self._stream = None

        # PortAudio waits for callbacks, which also acquire self._lock.
        if stream:
            try:
                stream.stop()
            except Exception as e:
                logger.debug("Error stopping audio input stream: %s", e)
            finally:
                try:
                    stream.close()
                except Exception as e:
                    logger.debug("Error closing audio input stream: %s", e)

        with self._lock:
            self._pre_roll_buffer.clear()
            self._active_utterance_frames.clear()
            self._is_utterance_active = False
            while not self._frame_queue.empty():
                try:
                    self._frame_queue.get_nowait()
                except Exception:
                    break

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """PortAudio real-time callback processing incoming microphone audio."""
        if not self._is_capturing or self._is_muted or time.monotonic() < self._suppress_until:
            return

        # Convert to mono if multi-channel
        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = np.mean(indata, axis=1, dtype=np.float32)
        else:
            mono = indata.flatten().astype(np.float32)

        # Compute RMS and peak level for meter
        rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) > 0 else 0.0
        db = 20.0 * math.log10(rms + 1e-9)
        self._current_level_db = max(-100.0, min(0.0, db))
        if self.level_callback:
            try:
                self.level_callback(self._current_level_db)
            except Exception:
                pass

        # Resample to target 16 kHz if device sample rate differs
        if self._device_sample_rate != self.target_sample_rate:
            target_len = int(len(mono) * self.target_sample_rate / self._device_sample_rate)
            if target_len <= 0:
                return
            resampled = np.interp(
                np.linspace(0, len(mono), target_len, endpoint=False),
                np.arange(len(mono)),
                mono,
            ).astype(np.float32)
        else:
            resampled = mono

        # Normalise size to exact TARGET_CHUNK_SAMPLES (512 samples)
        if len(resampled) != TARGET_CHUNK_SAMPLES:
            if len(resampled) > TARGET_CHUNK_SAMPLES:
                resampled = resampled[:TARGET_CHUNK_SAMPLES]
            else:
                resampled = np.pad(resampled, (0, TARGET_CHUNK_SAMPLES - len(resampled)), mode="constant")

        # Update buffers
        with self._lock:
            self._pre_roll_buffer.append(resampled)
            if self._is_utterance_active:
                self._active_utterance_frames.append(resampled)

        # Enqueue to synchronized frame queue for single-pass consumption
        try:
            self._frame_queue.put_nowait(resampled)
        except queue.Full:
            try:
                self._frame_queue.get_nowait()
            except Exception:
                pass
            try:
                self._frame_queue.put_nowait(resampled)
            except Exception:
                pass

    def start_utterance(self) -> None:
        """Triggered when VAD detects speech onset. Includes pre-roll buffer."""
        with self._lock:
            self._active_utterance_frames = list(self._pre_roll_buffer)
            self._is_utterance_active = True

    def append_speech_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            if self._is_utterance_active:
                self._active_utterance_frames.append(frame)

    def peek_current_utterance_audio(self) -> np.ndarray:
        """Returns the current utterance audio accumulated so far without ending the utterance."""
        with self._lock:
            if not self._active_utterance_frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._active_utterance_frames)

    def end_utterance(self) -> np.ndarray:

        """Triggered when VAD detects speech end. Returns contiguous float32 16kHz audio."""
        with self._lock:
            self._is_utterance_active = False
            if not self._active_utterance_frames:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._active_utterance_frames)
            self._active_utterance_frames.clear()
            return audio

    def get_next_frame(self, timeout: float = 0.05) -> np.ndarray | None:
        """Pulls the next unique audio frame from the synchronized queue (blocking up to timeout)."""
        try:
            return self._frame_queue.get(timeout=timeout)
        except (queue.Empty, Exception):
            return None

    def get_latest_frame(self) -> np.ndarray | None:
        """Gets the most recent frame from the circular buffer for VAD processing."""
        with self._lock:
            if self._pre_roll_buffer:
                return self._pre_roll_buffer[-1]
            return None
