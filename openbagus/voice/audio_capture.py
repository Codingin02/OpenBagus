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


class AudioStreamResampler:
    """Continuous streaming resampler with anti-aliasing low-pass FIR filter and sample accumulator."""

    def __init__(self, in_rate: int, out_rate: int = TARGET_SAMPLE_RATE, chunk_size: int = TARGET_CHUNK_SAMPLES) -> None:
        self.in_rate = in_rate
        self.out_rate = out_rate
        self.chunk_size = chunk_size
        self._raw_buffer = np.zeros(0, dtype=np.float32)

        if in_rate > out_rate:
            cutoff = (out_rate * 0.45) / in_rate
            taps = 27
            n = np.arange(taps) - (taps - 1) / 2
            h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(taps)
            self._fir = (h / np.sum(h)).astype(np.float32)
            self._overlap = np.zeros(taps - 1, dtype=np.float32)
        else:
            self._fir = None
            self._overlap = None

        self._ratio = in_rate / out_rate

    def reset(self) -> None:
        self._raw_buffer = np.zeros(0, dtype=np.float32)
        if self._overlap is not None:
            self._overlap.fill(0.0)

    def feed(self, incoming: np.ndarray) -> list[np.ndarray]:
        if self.in_rate == self.out_rate:
            self._raw_buffer = np.concatenate([self._raw_buffer, incoming])
            chunks = []
            while len(self._raw_buffer) >= self.chunk_size:
                chunks.append(self._raw_buffer[:self.chunk_size])
                self._raw_buffer = self._raw_buffer[self.chunk_size:]
            return chunks

        if self._fir is not None:
            ext = np.concatenate([self._overlap, incoming])
            self._overlap = ext[-(len(self._fir) - 1):].copy()
            filtered = np.convolve(ext, self._fir, mode="valid").astype(np.float32)
        else:
            filtered = incoming

        self._raw_buffer = np.concatenate([self._raw_buffer, filtered])

        chunks = []
        needed = self.chunk_size * self._ratio
        while len(self._raw_buffer) >= needed + 1:
            idx = np.arange(self.chunk_size) * self._ratio
            idx_floor = idx.astype(int)
            frac = (idx - idx_floor).astype(np.float32)
            resampled = self._raw_buffer[idx_floor] * (1.0 - frac) + self._raw_buffer[idx_floor + 1] * frac
            chunks.append(resampled.astype(np.float32))
            advance = int(np.floor(needed))
            self._raw_buffer = self._raw_buffer[advance:]
        return chunks


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
        self._lock = threading.RLock()
        self._resampler: AudioStreamResampler | None = None

        # Circular buffer for pre-roll to prevent clipping the first syllable
        self._pre_roll_buffer: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_chunks)

        # Queues and metrics
        self._raw_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=120)
        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=120)
        self._overflow_count: int = 0
        self._dropped_frames_count: int = 0

        self._worker_thread: threading.Thread | None = None
        self._stop_worker_event = threading.Event()

        # Active speech frames buffer for current utterance
        self._active_utterance_frames: list[np.ndarray] = []
        self._is_utterance_active = False

        self._device_sample_rate = 16000
        self._device_channels = 1
        self._current_level_db = -100.0
        self._suppress_until: float = 0.0

        self.stream_id: str = ""
        self._active_utterance_id: str = ""
        self.on_mute_callback: Callable[[], None] | None = None

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    def _clear_buffers_unlocked(self) -> None:
        """Internal buffer purge without locking."""
        self._pre_roll_buffer.clear()
        self._active_utterance_frames.clear()
        self._is_utterance_active = False
        if self._resampler is not None:
            self._resampler.reset()
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except Exception:
                break
        while not self._raw_queue.empty():
            try:
                self._raw_queue.get_nowait()
            except Exception:
                break

    def clear_buffers(self) -> None:
        """Purges pre-roll, active utterance frames, and drains queues."""
        with self._lock:
            self._clear_buffers_unlocked()

    def set_muted(self, muted: bool) -> None:
        self._is_muted = muted
        if muted:
            self.clear_buffers()
            if self.on_mute_callback:
                try:
                    self.on_mute_callback()
                except Exception as e:
                    logger.debug("Mute callback error: %s", e)

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
            while not self._raw_queue.empty():
                try:
                    self._raw_queue.get_nowait()
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
        target_len = int(round(len(mono) * target_sr / orig_sr))
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

    def get_telemetry(self) -> dict[str, Any]:
        """Returns real-time audio capture health metrics."""
        return {
            "device_id": self.device_id,
            "device_sample_rate": self._device_sample_rate,
            "device_channels": self._device_channels,
            "target_sample_rate": self.target_sample_rate,
            "is_capturing": self._is_capturing,
            "is_muted": self._is_muted,
            "overflow_count": self._overflow_count,
            "dropped_frames_count": self._dropped_frames_count,
            "raw_queue_size": self._raw_queue.qsize(),
            "frame_queue_size": self._frame_queue.qsize(),
            "current_level_db": round(self._current_level_db, 2),
        }

    def start(self) -> bool:
        """Starts real-time microphone stream with decoupled worker thread."""
        if not AudioDeviceManager.is_available():
            logger.error("Sounddevice not available for audio capture")
            return False

        with self._lock:
            if self._is_capturing:
                return True

            import uuid
            self.stream_id = f"stream_{uuid.uuid4().hex[:8]}"
            self._clear_buffers_unlocked()

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

            # Initialize streaming resampler for exact 512-sample continuous frame delivery
            self._resampler = AudioStreamResampler(
                self._device_sample_rate,
                self.target_sample_rate,
                TARGET_CHUNK_SAMPLES,
            )

            # Start background processing worker thread
            self._stop_worker_event.clear()
            self._worker_thread = threading.Thread(
                target=self._processing_worker,
                daemon=True,
                name="AudioCaptureWorker",
            )
            self._worker_thread.start()

            try:
                stream = sd.InputStream(
                    device=self.device_id,
                    channels=self._device_channels,
                    samplerate=self._device_sample_rate,
                    blocksize=blocksize,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self._stream = stream
                self._is_capturing = True
            except Exception as e:
                logger.error("Failed to create microphone stream: %s", e)
                self._stream = None
                self._is_capturing = False
                self._stop_worker_event.set()
                return False

        # Start stream outside self._lock to avoid deadlock with PortAudio callback thread
        try:
            stream.start()
            logger.info("Microphone stream started on device %s (%d Hz)", self.device_id, self._device_sample_rate)
            return True
        except Exception as e:
            logger.error("Failed to start microphone stream: %s", e)
            with self._lock:
                self._stream = None
                self._is_capturing = False
            self._stop_worker_event.set()
            try:
                stream.close()
            except Exception:
                pass
            return False

    def stop(self) -> None:
        """Stops microphone stream safely."""
        with self._lock:
            if not self._is_capturing:
                return
            self._is_capturing = False
            stream = self._stream
            self._stream = None

        self._stop_worker_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
        self._worker_thread = None

        # PortAudio waits for callbacks, which acquire no locks.
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
            self._clear_buffers_unlocked()

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Ultra-fast real-time callback (<100 µs): non-blocking push only, zero locks, zero resampling."""
        if status and status.input_overflow:
            self._overflow_count += 1

        if not self._is_capturing or self._is_muted:
            return

        try:
            self._raw_queue.put_nowait(indata.copy())
        except queue.Full:
            self._dropped_frames_count += 1

    def _processing_worker(self) -> None:
        """Offloads resampling, level metering, and frame queuing from the PortAudio audio callback thread."""
        import ctypes
        co_initialized = False
        try:
            if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "ole32"):
                ctypes.windll.ole32.CoInitialize(None)
                co_initialized = True
        except Exception:
            pass

        try:
            while not self._stop_worker_event.is_set():
                try:
                    raw_chunk = self._raw_queue.get(timeout=0.05)
                except queue.Empty:
                    continue

                if self._is_muted or time.monotonic() < self._suppress_until:
                    self._raw_queue.task_done()
                    continue

                # Convert to mono if multi-channel
                if raw_chunk.ndim > 1 and raw_chunk.shape[1] > 1:
                    mono = np.mean(raw_chunk, axis=1, dtype=np.float32)
                else:
                    mono = raw_chunk.flatten().astype(np.float32)

                # Compute RMS and peak level for meter
                rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) > 0 else 0.0
                db = 20.0 * math.log10(rms + 1e-9)
                self._current_level_db = max(-100.0, min(0.0, db))
                if self.level_callback:
                    try:
                        self.level_callback(self._current_level_db)
                    except Exception:
                        pass

                # Continuous stream resampling and exact 512-sample chunk emission
                if self._resampler is None:
                    self._resampler = AudioStreamResampler(self._device_sample_rate, self.target_sample_rate, TARGET_CHUNK_SAMPLES)

                resampled_chunks = self._resampler.feed(mono)

                for resampled in resampled_chunks:
                    # Update buffers atomically
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

                self._raw_queue.task_done()
        finally:
            if co_initialized:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

    def start_utterance(self, utterance_id: str = "") -> None:
        """Triggered when VAD detects speech onset. Includes pre-roll buffer."""
        with self._lock:
            self._active_utterance_id = utterance_id
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

    def end_utterance_with_meta(self) -> tuple[np.ndarray, dict[str, Any]]:
        """Returns contiguous float32 16kHz audio along with stream and utterance provenance metadata."""
        with self._lock:
            self._is_utterance_active = False
            if not self._active_utterance_frames:
                return np.zeros(0, dtype=np.float32), {
                    "stream_id": self.stream_id,
                    "utterance_id": self._active_utterance_id,
                    "duration_s": 0.0,
                }
            audio = np.concatenate(self._active_utterance_frames)
            self._active_utterance_frames.clear()
            meta = {
                "stream_id": self.stream_id,
                "utterance_id": self._active_utterance_id,
                "duration_s": round(len(audio) / self.target_sample_rate, 3),
            }
            return audio, meta

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
