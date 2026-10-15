"""Real-time user interruption (Barge-In) coordinator and cancellation token manager."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


class InterruptionCoordinator:
    """Manages real-time barge-in detection, speech cancellation tokens, and safe recovery."""

    def __init__(
        self,
        on_interruption_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.on_interruption_callback = on_interruption_callback
        self._cancellation_event = threading.Event()
        self._current_turn_id: str = ""
        self._lock = threading.Lock()
        self._interruption_count = 0
        self._last_interruption_time = 0.0

    @property
    def is_cancelled(self) -> bool:
        return self._cancellation_event.is_set()

    @property
    def is_interrupted(self) -> bool:
        return self._cancellation_event.is_set()

    def get_cancellation_event(self) -> threading.Event:
        return self._cancellation_event

    def start_turn(self, turn_id: str) -> None:
        """Initializes a new conversational assistant turn with a fresh cancellation token."""
        with self._lock:
            self._current_turn_id = turn_id
            self._cancellation_event = threading.Event()

    def trigger_interruption(self, reason: str = "USER_BARGE_IN") -> bool:
        """Triggers immediate speech cancellation and signals all generators to abort."""
        with self._lock:
            if self._cancellation_event.is_set():
                return False  # Already cancelled

            t_now = time.perf_counter()
            self._cancellation_event.set()
            self._interruption_count += 1
            self._last_interruption_time = t_now

            logger.info("Barge-in interruption triggered for turn '%s' (reason: %s)", self._current_turn_id, reason)

            if self.on_interruption_callback:
                try:
                    self.on_interruption_callback(self._current_turn_id)
                except Exception as e:
                    logger.warning("Error in interruption callback: %s", e)

            return True

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_interruptions": self._interruption_count,
            "last_turn_id": self._current_turn_id,
            "is_currently_cancelled": self._cancellation_event.is_set(),
        }
