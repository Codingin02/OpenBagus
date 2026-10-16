"""Low-latency audio playback manager with instant barge-in abort and generation tracking."""

from __future__ import annotations

import logging
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


class AudioPlaybackManager:
    """Manages audio playback queue with instant interruption/barge-in cancellation and generation tracking."""

    def __init__(
        self,
        device_id: int | None = None,
        default_samplerate: int = 22050,  # Piper default
        volume: float = 1.0,
        on_start: Callable[[], None] | None = None,
        on_finish: Callable[[], None] | None = None,
        on_interrupted: Callable[[], None] | None = None,
        on_playback_level: Callable[[float], None] | None = None,
    ) -> None:
        self.device_id = device_id
        self.default_samplerate = default_samplerate
        self.volume = max(0.0, min(1.0, volume))
        self.on_start = on_start
        self.on_finish = on_finish
        self.on_interrupted = on_interrupted
        self.on_playback_level = on_playback_level

        # Queue items: tuple[np.ndarray, int, int] (audio, samplerate, generation_id)
        self._queue: queue.Queue[tuple[np.ndarray, int, int]] = queue.Queue()
        self._current_generation_id: int = 1
        self._is_playing = False
        self._is_muted = False
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current_stream: Any = None

        # Render-reference tracking for echo suppression / full-duplex double-talk
        self._current_render_rms: float = 0.0
        self._render_energy_timestamp: float = 0.0

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def current_generation_id(self) -> int:
        return self._current_generation_id

    def get_current_render_energy(self) -> float:
        """Returns the RMS energy of audio actively rendering to speakers (0.0 if not rendering)."""
        if not self._is_playing or (time.time() - self._render_energy_timestamp > 0.15):
            return 0.0
        return self._current_render_rms

    def new_turn(self) -> int:
        """Starts a new generation turn, invalidating any previous turn's pending audio."""
        with self._lock:
            self._current_generation_id += 1
            self._stop_event.clear()
            return self._current_generation_id

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def set_muted(self, muted: bool) -> None:
        self._is_muted = muted
        if muted:
            self.stop_playback(interrupted=False)

    def enqueue(
        self,
        audio: np.ndarray,
        samplerate: int | None = None,
        generation_id: int | None = None,
    ) -> None:
        """Enqueues audio data for sequential playback with generation validation."""
        target_gen = generation_id if generation_id is not None else self._current_generation_id
        with self._lock:
            # If generation already expired due to barge-in, drop immediately
            if target_gen != self._current_generation_id:
                logger.debug("Discarding stale audio chunk (chunk gen %d != current gen %d)", target_gen, self._current_generation_id)
                return

        sr = samplerate or self.default_samplerate
        # Ensure float32 format normalized to [-1.0, 1.0]
        if audio.dtype == np.int16:
            audio_f = (audio.astype(np.float32) / 32768.0) * self.volume
        else:
            audio_f = audio.astype(np.float32) * self.volume

        self._queue.put((audio_f, sr, target_gen))
        self._ensure_worker_running()

    def _ensure_worker_running(self) -> None:
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._stop_event.clear()
                self._worker_thread = threading.Thread(target=self._playback_loop, daemon=True, name="AudioPlaybackWorker")
                self._worker_thread.start()

    @staticmethod
    def _resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        if orig_sr == target_sr or len(audio) == 0:
            return audio
        target_len = int(round(len(audio) * target_sr / orig_sr))
        if target_len <= 0:
            return np.empty(0, dtype=np.float32)
        return np.interp(
            np.linspace(0, len(audio), target_len, endpoint=False),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    def _playback_loop(self) -> None:
        """Sequential playback loop processing audio chunks with sample-rate negotiation and Windows COM safety."""
        import ctypes
        co_initialized = False
        try:
            if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "ole32"):
                ctypes.windll.ole32.CoInitialize(None)
                co_initialized = True
        except Exception:
            pass

        try:
            while not self._stop_event.is_set():
                try:
                    audio, sr, chunk_gen = self._queue.get(timeout=0.1)
                except queue.Empty:
                    if self._is_playing:
                        self._is_playing = False
                        if self.on_finish:
                            try:
                                self.on_finish()
                            except Exception:
                                pass
                    continue

                # Drop chunk if invalidated by barge-in or stop
                if self._stop_event.is_set() or self._is_muted or chunk_gen != self._current_generation_id:
                    self._queue.task_done()
                    continue

                if not self._is_playing:
                    self._is_playing = True
                    if self.on_start:
                        try:
                            self.on_start()
                        except Exception:
                            pass

                try:
                    dev_out = self.device_id
                    if dev_out is None:
                        d = AudioDeviceManager.get_default_output_device()
                        dev_out = d.id if d else None

                    play_audio = audio
                    play_sr = sr

                    # Safe sample-rate and channel negotiation with output device (WASAPI/DirectSound compatibility)
                    if dev_out is not None and sd is not None:
                        try:
                            info = sd.query_devices(dev_out)
                            native_sr = int(info.get("default_samplerate", 48000))
                            max_ch = int(info.get("max_output_channels", 2))
                            if native_sr != sr:
                                play_audio = self._resample_audio(audio, sr, native_sr)
                                play_sr = native_sr
                            # Convert mono 1D array to 2D multi-channel array matching device capability
                            if play_audio.ndim == 1 and max_ch >= 2:
                                play_audio = np.column_stack([play_audio] * min(2, max_ch))
                        except Exception as e_negotiate:
                            logger.debug("Playback sample rate/channel negotiation fallback: %s", e_negotiate)

                    sd.play(play_audio, samplerate=play_sr, device=dev_out)

                    # Check stop event during chunk duration and emit synchronized playback levels
                    chunk_dur = len(play_audio) / play_sr
                    chunk_start = time.time()
                    deadline = chunk_start + chunk_dur
                    last_level_emit = 0.0
                    last_rms = 0.0

                    while time.time() < deadline:
                        if self._stop_event.is_set() or chunk_gen != self._current_generation_id:
                            sd.stop()
                            break
                        now = time.time()
                        if self.on_playback_level and (now - last_level_emit >= 0.033):
                            last_level_emit = now
                            elapsed = now - chunk_start
                            curr_s = int(elapsed * play_sr)
                            w_len = int(0.04 * play_sr)
                            start_i = max(0, min(len(play_audio) - 1, curr_s))
                            end_i = max(0, min(len(play_audio), start_i + w_len))
                            if end_i > start_i:
                                sub = play_audio[start_i:end_i]
                                curr_rms = float(np.sqrt(np.mean(np.square(sub))))
                                self._current_render_rms = curr_rms
                                self._render_energy_timestamp = now
                                smoothed = 0.60 * last_rms + 0.40 * curr_rms
                                last_rms = smoothed
                                amp = min(1.0, max(0.0, smoothed * 3.5))
                                try:
                                    self.on_playback_level(amp)
                                except Exception:
                                    pass
                        time.sleep(0.01)

                    self._current_render_rms = 0.0
                    self._render_energy_timestamp = 0.0
                    if self.on_playback_level:
                        try:
                            self.on_playback_level(0.0)
                        except Exception:
                            pass

                except Exception as e:
                    logger.warning("Error during audio chunk playback: %s", e)
                finally:
                    self._current_render_rms = 0.0
                    self._render_energy_timestamp = 0.0
                    self._queue.task_done()

            self._is_playing = False
            self._current_render_rms = 0.0
            self._render_energy_timestamp = 0.0
            if self.on_playback_level:
                try:
                    self.on_playback_level(0.0)
                except Exception:
                    pass
        finally:
            if co_initialized:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

    def stop_playback(self, interrupted: bool = True) -> None:
        """Instantly aborts audio playback, bumps generation, and drains queue (Barge-In support)."""
        with self._lock:
            self._current_generation_id += 1
            self._stop_event.set()
            # Drain queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except (queue.Empty, ValueError):
                    break

            # Immediately stop sounddevice driver
            if AudioDeviceManager.is_available():
                try:
                    sd.stop()
                except Exception:
                    pass

            was_playing = self._is_playing
            self._is_playing = False
            self._current_render_rms = 0.0
            self._render_energy_timestamp = 0.0

            if self.on_playback_level:
                try:
                    self.on_playback_level(0.0)
                except Exception:
                    pass

            if was_playing and interrupted and self.on_interrupted:
                try:
                    self.on_interrupted()
                except Exception:
                    pass
