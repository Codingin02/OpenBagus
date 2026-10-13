"""Low-latency audio playback manager with instant barge-in abort and volume control."""

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
    """Manages audio playback queue with instant interruption/barge-in cancellation."""

    def __init__(
        self,
        device_id: int | None = None,
        default_samplerate: int = 22050,  # Piper default
        volume: float = 1.0,
        on_start: Callable[[], None] | None = None,
        on_finish: Callable[[], None] | None = None,
        on_interrupted: Callable[[], None] | None = None,
    ) -> None:
        self.device_id = device_id
        self.default_samplerate = default_samplerate
        self.volume = max(0.0, min(1.0, volume))
        self.on_start = on_start
        self.on_finish = on_finish
        self.on_interrupted = on_interrupted

        self._queue: queue.Queue[tuple[np.ndarray, int]] = queue.Queue()
        self._is_playing = False
        self._is_muted = False
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current_stream: Any = None

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def set_muted(self, muted: bool) -> None:
        self._is_muted = muted
        if muted:
            self.stop_playback(interrupted=False)

    def enqueue(self, audio: np.ndarray, samplerate: int | None = None) -> None:
        """Enqueues audio data for sequential playback."""
        sr = samplerate or self.default_samplerate
        # Ensure float32 format normalized to [-1.0, 1.0]
        if audio.dtype == np.int16:
            audio_f = (audio.astype(np.float32) / 32768.0) * self.volume
        else:
            audio_f = audio.astype(np.float32) * self.volume

        self._queue.put((audio_f, sr))
        self._ensure_worker_running()

    def _ensure_worker_running(self) -> None:
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._stop_event.clear()
                self._worker_thread = threading.Thread(target=self._playback_loop, daemon=True, name="AudioPlaybackWorker")
                self._worker_thread.start()

    def _playback_loop(self) -> None:
        """Sequential playback loop processing audio chunks."""
        while not self._stop_event.is_set():
            try:
                audio, sr = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._is_playing:
                    self._is_playing = False
                    if self.on_finish:
                        try:
                            self.on_finish()
                        except Exception:
                            pass
                continue

            if self._stop_event.is_set() or self._is_muted:
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
                # Play using sounddevice OutputStream or sd.play with event check
                dev_out = self.device_id
                if dev_out is None:
                    d = AudioDeviceManager.get_default_output_device()
                    dev_out = d.id if d else None

                sd.play(audio, samplerate=sr, device=dev_out)
                
                # Check stop event during chunk duration
                chunk_dur = len(audio) / sr
                deadline = time.time() + chunk_dur
                while time.time() < deadline:
                    if self._stop_event.is_set():
                        sd.stop()
                        break
                    time.sleep(0.01)

            except Exception as e:
                logger.warning("Error during audio chunk playback: %s", e)
            finally:
                self._queue.task_done()

        self._is_playing = False

    def stop_playback(self, interrupted: bool = True) -> None:
        """Instantly aborts audio playback and drains queue (Barge-In support)."""
        with self._lock:
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

            if was_playing and interrupted and self.on_interrupted:
                try:
                    self.on_interrupted()
                except Exception:
                    pass
