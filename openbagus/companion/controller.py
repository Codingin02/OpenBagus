"""SHOW OPENBAGUS companion controller.

CLI-facing interface that manages the companion subprocess and IPC connection.
If the companion process crashes, this controller catches it and CLI continues.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# IPC protocol version
IPC_VERSION = "1.0"
IPC_HOST = "127.0.0.1"
IPC_PORT = 7432


class CompanionController:
    """Manages the Show OpenBagus 3D companion window lifecycle and IPC.

    The companion runs as a separate subprocess (openbagus/companion/renderer.py).
    CLI survives companion crashes gracefully.
    """

    _instance: CompanionController | None = None

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._last_state: str = "IDLE"
        self._amplitude: float = 0.0

    @classmethod
    def get_instance(cls) -> CompanionController:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Public API (called from CLI commands)
    # ------------------------------------------------------------------

    def show(self) -> bool:
        """Launch the companion window if not running, or show if hidden."""
        if self._is_running():
            return self._send_event("companion.show", {})
        return self._launch()

    def hide(self) -> bool:
        """Hide the companion window without closing the process."""
        return self._send_event("companion.hide", {})

    def close(self) -> bool:
        """Close the companion window and terminate the process."""
        if self._is_running():
            self._send_event("companion.shutdown", {})
            time.sleep(0.3)
            if self._process and self._process.poll() is None:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            self._process = None
        self._close_socket()
        logger.info("SHOW OPENBAGUS companion closed")
        return True

    def reset(self) -> bool:
        """Close and relaunch the companion."""
        self.close()
        time.sleep(0.5)
        return self._launch()

    def set_state(self, state: str) -> bool:
        """Set character animation state.

        Valid states: IDLE, LISTENING, HEARD_USER, THINKING, DEEP_THINKING,
        SPEAKING, HAPPY, SURPRISED, CONFUSED, WARNING, TOOL_WORKING, SUCCESS,
        ERROR, SLEEPING
        """
        self._last_state = state
        return self._send_event("companion.set_state", {"state": state})

    def speak_start(self, turn_id: str) -> bool:
        """Notify companion that TTS playback has started."""
        return self._send_event("companion.speak_start", {"turn_id": turn_id})

    def speak_amplitude(self, amplitude: float) -> bool:
        """Send real-time audio amplitude for lip sync animation (0.0 to 1.0)."""
        self._amplitude = amplitude
        return self._send_event("companion.speak_amplitude", {"amplitude": amplitude})

    def speak_end(self, turn_id: str) -> bool:
        """Notify companion that TTS playback ended."""
        return self._send_event("companion.speak_end", {"turn_id": turn_id})

    def interrupted(self, turn_id: str) -> bool:
        """Notify companion of barge-in interruption."""
        return self._send_event("companion.interrupted", {"turn_id": turn_id})

    def get_status(self) -> dict[str, Any]:
        """Return companion status for /show-openbagus status command."""
        running = self._is_running()
        connected = self._is_connected()
        return {
            "running": running,
            "connected": connected,
            "pid": self._process.pid if self._process else None,
            "last_state": self._last_state,
            "ipc_address": f"{IPC_HOST}:{IPC_PORT}",
            "ipc_version": IPC_VERSION,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch(self) -> bool:
        """Start the companion renderer subprocess."""
        renderer_path = Path(__file__).parent / "renderer.py"
        if not renderer_path.exists():
            logger.error("Companion renderer not found at %s", renderer_path)
            return False

        try:
            self._process = subprocess.Popen(
                [sys.executable, str(renderer_path), "--port", str(IPC_PORT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "SHOW OPENBAGUS companion launched (PID %d)", self._process.pid
            )

            # Wait for companion to start accepting IPC connections
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if self._connect():
                    logger.info("IPC connection established to companion")
                    return True
                time.sleep(0.15)

            logger.warning("Companion started but IPC connection timed out")
            return False
        except Exception as e:
            logger.error("Failed to launch companion: %s", e)
            return False

    def _is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _is_connected(self) -> bool:
        if self._sock is None:
            return False
        try:
            self._sock.getpeername()
            return True
        except OSError:
            return False

    def _connect(self) -> bool:
        """Attempt to connect IPC socket to companion."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect((IPC_HOST, IPC_PORT))
            s.settimeout(None)
            self._sock = s
            return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            return False

    def _close_socket(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send_event(self, event_type: str, payload: dict[str, Any]) -> bool:
        """Send a typed IPC event to the companion renderer."""
        msg = {
            "version": IPC_VERSION,
            "type": event_type,
            "payload": payload,
            "ts": time.time(),
        }
        raw = json.dumps(msg, ensure_ascii=False) + "\n"

        with self._lock:
            # Reconnect if needed
            if not self._is_connected() and self._is_running():
                self._connect()

            if self._sock is None:
                return False

            try:
                self._sock.sendall(raw.encode("utf-8"))
                return True
            except OSError as e:
                logger.debug("IPC send failed: %s — reconnecting", e)
                self._close_socket()
                if self._connect():
                    try:
                        self._sock.sendall(raw.encode("utf-8"))  # type: ignore[union-attr]
                        return True
                    except Exception:
                        pass
                return False
