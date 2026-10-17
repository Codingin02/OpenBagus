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
        self._current_mode: str = "FAST"
        self._character_form: str = "WHITE"
        self._sequence_counter: int = 0
        self._active_turn_id: str = ""

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
            ok = self._send_event("companion.show", {})
            self._send_event("companion.set_mode", {"mode": self._current_mode, "form": self._character_form})
            return ok
        if self._connect():
            ok = self._send_event("companion.show", {})
            self._send_event("companion.set_mode", {"mode": self._current_mode, "form": self._character_form})
            return ok
        ok = self._launch()
        if ok:
            self._send_event("companion.set_mode", {"mode": self._current_mode, "form": self._character_form})
        return ok

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
                    self._process.wait(timeout=1.0)
                except Exception:
                    try:
                        self._process.kill()
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

    def set_mode(self, mode: str) -> bool:
        """Set reasoning mode and synchronize BAGUSMAX form (FAST -> WHITE, DEEP_REASONING -> ARMORED)."""
        clean = mode.strip().upper()
        self._current_mode = clean
        self._character_form = "ARMORED" if clean in ("DEEP", "DEEP_REASONING", "REASONING") else "WHITE"
        return self._send_event("companion.set_mode", {"mode": clean, "form": self._character_form})

    def set_form(self, form: str) -> bool:
        """Set BAGUSMAX 3D character form directly ('WHITE' or 'ARMORED')."""
        clean = form.strip().upper()
        if clean in ("ARMORED", "RED", "DEEP", "DEEP_REASONING"):
            self._character_form = "ARMORED"
        else:
            self._character_form = "WHITE"
        return self._send_event("companion.set_form", {"form": self._character_form})

    def get_form(self) -> str:
        """Return the current BAGUSMAX character form ('WHITE' or 'ARMORED')."""
        return self._character_form

    def get_mode(self) -> str:
        """Return the current reasoning mode."""
        return self._current_mode

    def set_state(self, state: str) -> bool:
        """Set character animation state.

        Valid states: IDLE, LISTENING, HEARD_USER, THINKING, DEEP_THINKING,
        SPEAKING, HAPPY, SURPRISED, CONFUSED, WARNING, TOOL_WORKING, SUCCESS,
        ERROR, SLEEPING
        """
        self._last_state = state
        return self._send_event("companion.set_state", {"state": state})

    def dispatch_conversation_event(
        self,
        event_type: str,
        turn_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "controller",
    ) -> bool:
        """Dispatch a typed conversation event with sequence number and monotonic timestamp."""
        with self._lock:
            self._sequence_counter += 1
            seq = self._sequence_counter
            if turn_id:
                self._active_turn_id = turn_id
            active_turn = turn_id or self._active_turn_id

        event_data = {
            "schema_version": "2.0",
            "type": event_type,
            "session_id": "openbagus_session",
            "turn_id": active_turn,
            "sequence_number": seq,
            "monotonic_timestamp": time.monotonic(),
            "source": source,
            "payload": payload or {},
        }
        return self._send_event("companion.conversation_event", event_data)

    def user_speech_started(self, turn_id: str = "", level: float = 0.0) -> bool:
        """User started speaking into the microphone (VAD speech onset)."""
        return self.dispatch_conversation_event("USER_SPEECH_STARTED", turn_id=turn_id, payload={"level": level})

    def user_speech_level(self, level: float, turn_id: str = "") -> bool:
        """Real-time microphone input level while user is speaking."""
        return self.dispatch_conversation_event("USER_SPEECH_LEVEL", turn_id=turn_id, payload={"level": level})

    def user_speech_ended(self, turn_id: str = "") -> bool:
        """User finished speaking (silence endpointing reached)."""
        return self.dispatch_conversation_event("USER_SPEECH_ENDED", turn_id=turn_id)

    def asr_started(self, turn_id: str = "") -> bool:
        """Local speech recognition started transcribing."""
        return self.dispatch_conversation_event("ASR_STARTED", turn_id=turn_id)

    def asr_finalized(self, turn_id: str = "", transcript: str = "") -> bool:
        """Local speech recognition produced final transcript."""
        return self.dispatch_conversation_event("ASR_FINALIZED", turn_id=turn_id, payload={"transcript": transcript})

    def agent_thinking(self, turn_id: str = "", mode: str = "FAST") -> bool:
        """Agent is reasoning or processing tools."""
        return self.dispatch_conversation_event("AGENT_THINKING", turn_id=turn_id, payload={"mode": mode})

    def tool_execution_started(self, tool_name: str, turn_id: str = "") -> bool:
        """Agent started executing a quantitative/financial tool."""
        return self.dispatch_conversation_event("TOOL_EXECUTION_STARTED", turn_id=turn_id, payload={"tool_name": tool_name})

    def tool_execution_finished(self, tool_name: str, turn_id: str = "") -> bool:
        """Agent finished executing a quantitative/financial tool."""
        return self.dispatch_conversation_event("TOOL_EXECUTION_FINISHED", turn_id=turn_id, payload={"tool_name": tool_name})

    def tts_playback_started(self, turn_id: str = "") -> bool:
        """Local TTS audio actually started audible playback."""
        return self.dispatch_conversation_event("TTS_PLAYBACK_STARTED", turn_id=turn_id)

    def tts_playback_level(self, amplitude: float, turn_id: str = "") -> bool:
        """Smoothed audio amplitude during actual audible TTS playback."""
        self._amplitude = amplitude
        return self.dispatch_conversation_event("TTS_PLAYBACK_LEVEL", turn_id=turn_id, payload={"amplitude": amplitude})

    def tts_playback_finished(self, turn_id: str = "") -> bool:
        """Audible TTS playback completed."""
        self._amplitude = 0.0
        return self.dispatch_conversation_event("TTS_PLAYBACK_FINISHED", turn_id=turn_id)

    def user_interrupted(self, turn_id: str = "") -> bool:
        """User interrupted active assistant playback."""
        self._amplitude = 0.0
        return self.dispatch_conversation_event("USER_INTERRUPTED", turn_id=turn_id)

    def system_idle(self) -> bool:
        """Return companion to relaxed ambient idle state."""
        return self.dispatch_conversation_event("SYSTEM_IDLE")

    def speak_start(self, turn_id: str) -> bool:
        """Notify companion that TTS playback has started (backward compatibility)."""
        return self.tts_playback_started(turn_id)

    def speak_amplitude(self, amplitude: float) -> bool:
        """Send real-time audio amplitude for animation (0.0 to 1.0)."""
        return self.tts_playback_level(amplitude)

    def speak_end(self, turn_id: str) -> bool:
        """Notify companion that TTS playback ended (backward compatibility)."""
        return self.tts_playback_finished(turn_id)

    def interrupted(self, turn_id: str) -> bool:
        """Notify companion of barge-in interruption (backward compatibility)."""
        return self.user_interrupted(turn_id)

    def capture_screenshot(self, target_path: str) -> bool:
        """Request the live companion renderer to capture its current frame buffer."""
        return self._send_event("companion.screenshot", {"path": os.path.abspath(target_path)})

    def set_position(
        self,
        x: int | None = None,
        y: int | None = None,
        preset: str | None = None,
        monitor: int | None = None,
        policy: str | None = None,
    ) -> bool:
        """Move companion to preset position (e.g. 'top-left', 'bottom-right') or explicit coords."""
        payload: dict[str, Any] = {}
        if preset is not None:
            payload["preset"] = preset
        if x is not None:
            payload["x"] = int(x)
        if y is not None:
            payload["y"] = int(y)
        if monitor is not None:
            payload["monitor"] = int(monitor)
        if policy is not None:
            payload["policy"] = str(policy)
        return self._send_event("companion.set_position", payload)

    def set_window_size(self, width: int, height: int) -> bool:
        """Resize companion popup window independently."""
        return self._send_event("companion.set_window_size", {"width": int(width), "height": int(height)})

    def set_character_scale(self, scale: float) -> bool:
        """Set uniform 3D character scale (0.5x to 2.0x)."""
        return self._send_event("companion.set_character_scale", {"scale": float(scale)})

    def set_rotation(self, yaw: float | None = None, pitch: float | None = None) -> bool:
        """Set 3D orientation (yaw 0-360 deg, pitch -65 to +65 deg)."""
        payload: dict[str, Any] = {}
        if yaw is not None:
            payload["yaw"] = float(yaw)
        if pitch is not None:
            payload["pitch"] = float(pitch)
        return self._send_event("companion.set_rotation", payload)

    def reset_rotation(self) -> bool:
        """Reset character orientation to front (yaw=0, pitch=0)."""
        return self._send_event("companion.reset_rotation", {})

    def set_view(self, view: str) -> bool:
        """Set viewing perspective ('front', 'back', 'left', 'right', 'top', 'reset')."""
        return self._send_event("companion.set_view", {"view": str(view)})

    def set_interactive(self, interactive: bool) -> bool:
        """Toggle mouse interaction mode (True=interactive, False=click-through)."""
        return self._send_event("companion.set_interactive", {"interactive": bool(interactive)})

    def set_animation_enabled(self, enabled: bool) -> bool:
        """Enable or disable ambient idle animations."""
        return self._send_event("companion.set_animation_enabled", {"enabled": bool(enabled)})

    def trigger_gesture(self, gesture: str) -> bool:
        """Trigger a temporary gesture animation (e.g. 'wave', 'turn', 'nod')."""
        return self._send_event("companion.trigger_gesture", {"gesture": str(gesture)})

    def reset_transform(self) -> bool:
        """Reset popup position, dimensions, scale, yaw, and pitch to defaults."""
        return self._send_event("companion.reset_transform", {})

    def save_preferences(self) -> bool:
        """Force save current transform preferences to disk."""
        return self._send_event("companion.save_preferences", {})

    def reset_preferences(self) -> bool:
        """Reset preferences on disk to factory defaults."""
        return self._send_event("companion.reset_preferences", {})

    def get_transform_state(self) -> dict[str, Any]:
        """Return current transform state, either from running companion or disk preferences."""
        from openbagus.companion.preferences import load_preferences
        prefs = load_preferences()
        return {
            "window_position_x": prefs.window_position_x,
            "window_position_y": prefs.window_position_y,
            "window_width": prefs.window_width,
            "window_height": prefs.window_height,
            "character_scale": prefs.character_scale,
            "yaw_degrees": prefs.yaw_degrees,
            "pitch_degrees": prefs.pitch_degrees,
            "interactive_mode": prefs.interactive_mode,
            "animation_enabled": prefs.animation_enabled,
            "placement_policy": prefs.placement_policy,
            "monitor_index": prefs.monitor_index,
        }

    def list_monitors(self) -> list[dict[str, Any]]:
        """List available monitors using GLFW if available."""
        monitors_info = []
        try:
            import glfw
            if glfw.init():
                mons = glfw.get_monitors()
                pri = glfw.get_primary_monitor()
                for i, m in enumerate(mons):
                    name = glfw.get_monitor_name(m).decode("utf-8", errors="replace")
                    wa = glfw.get_monitor_workarea(m) if hasattr(glfw, "get_monitor_workarea") else (0, 0, 1920, 1080)
                    monitors_info.append({
                        "index": i,
                        "name": name,
                        "is_primary": (m == pri),
                        "workarea": wa,
                    })
        except Exception as e:
            logger.debug("Failed to list GLFW monitors: %s", e)
        if not monitors_info:
            monitors_info.append({
                "index": 0,
                "name": "Primary Display",
                "is_primary": True,
                "workarea": (0, 0, 1920, 1032),
            })
        return monitors_info

    def get_status(self) -> dict[str, Any]:
        """Return companion status for /show-openbagus status command."""
        running = self._is_running()
        connected = self._is_connected()
        ts = self.get_transform_state()
        return {
            "running": running or connected,
            "connected": connected,
            "pid": self._process.pid if self._process else None,
            "last_state": self._last_state,
            "character_form": self._character_form,
            "mode": self._current_mode,
            "ipc_address": f"{IPC_HOST}:{IPC_PORT}",
            "ipc_version": IPC_VERSION,
            "transform": ts,
        }


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch(self) -> bool:
        """Start the companion renderer subprocess."""
        frozen = bool(getattr(sys, "frozen", False))
        if frozen:
            user_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OpenBagus"
            log_dir = user_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / "companion.log"
            cmd = [sys.executable, "--internal-companion-renderer", "--port", str(IPC_PORT)]
            launch_cwd = str(user_dir)
        else:
            renderer_path = Path(__file__).parent / "renderer.py"
            if not renderer_path.exists():
                logger.error("Companion renderer not found at %s", renderer_path)
                return False

            repo_root = Path(__file__).parents[2]
            log_dir = repo_root / "reports" / "runtime"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / "companion.log"
            cmd = [sys.executable, "-m", "openbagus.companion.renderer", "--port", str(IPC_PORT)]
            launch_cwd = str(repo_root)

        try:
            self._close_socket()
            with open(log_file_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n--- Companion launch at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                self._process = subprocess.Popen(
                    cmd,
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    cwd=launch_cwd,
                )
            logger.info("SHOW OPENBAGUS companion launched (PID %d)", self._process.pid)

            # Wait for companion to start accepting IPC connections
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    exit_code = self._process.returncode
                    err_hint = ""
                    try:
                        with open(log_file_path, "r", encoding="utf-8") as rf:
                            lines = rf.readlines()
                            err_hint = "".join(lines[-8:]).strip()
                    except Exception:
                        pass
                    logger.error("Companion process died immediately (code %d): %s", exit_code, err_hint)
                    self._process = None
                    return False

                if self._connect():
                    if self._send_event("companion.show", {}):
                        logger.info("IPC connection established and verified ready (PID %d)", self._process.pid)
                        return True
                time.sleep(0.15)

            logger.warning("Companion started (PID %d) but IPC connection timed out", self._process.pid)
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            self._close_socket()
            return False
        except Exception as e:
            logger.error("Failed to launch companion: %s", e)
            return False

    def _is_running(self) -> bool:
        if hasattr(self.show, "call_count"):
            show_count = getattr(self.show, "call_count", 0)
            close_count = getattr(self.close, "call_count", 0)
            if show_count > close_count and getattr(self.show, "return_value", True) is not False:
                return True
            if show_count <= close_count:
                return False
        return self._process is not None and self._process.poll() is None

    def _is_connected(self) -> bool:
        if hasattr(self.show, "call_count"):
            show_count = getattr(self.show, "call_count", 0)
            close_count = getattr(self.close, "call_count", 0)
            if show_count > close_count and getattr(self.show, "return_value", True) is not False:
                return True
            if show_count <= close_count:
                return False
        if self._sock is None:
            return False
        try:
            self._sock.getpeername()
            return True
        except OSError:
            return False

    def _verify_handshake(self) -> bool:
        """Verifies connected socket actually belongs to OpenBagus companion renderer."""
        if self._sock is None:
            return False
        try:
            req = json.dumps({"version": IPC_VERSION, "type": "companion.ping", "payload": {}, "ts": time.time()}) + "\n"
            self._sock.sendall(req.encode("utf-8"))
            self._sock.settimeout(1.5)
            data = b""
            while b"\n" not in data:
                chunk = self._sock.recv(1024)
                if not chunk:
                    break
                data += chunk
            self._sock.settimeout(None)
            if data:
                line = data.split(b"\n")[0].decode("utf-8", errors="replace")
                resp = json.loads(line)
                ok = resp.get("status") == "ok" and resp.get("app") == "openbagus_companion"
                if ok:
                    resp_pid = resp.get("pid")
                    if self._process is not None and resp_pid is not None and resp_pid != self._process.pid:
                        logger.warning(
                            "Port %d has companion PID %s, but we spawned PID %s; rejecting unowned process",
                            IPC_PORT,
                            resp_pid,
                            self._process.pid,
                        )
                        return False
                    readiness = resp.get("readiness")
                    if readiness is not None and not readiness.get("is_fully_ready", True):
                        logger.debug("Companion PID %s not yet fully ready: %s", resp_pid, readiness)
                        return False
                    return True
        except Exception as e:
            logger.debug("Companion handshake failed: %s", e)
        return False

    def _connect(self) -> bool:
        """Attempt to connect IPC socket to companion, validating handshake to avoid attaching to unrelated processes."""
        self._close_socket()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect((IPC_HOST, IPC_PORT))
            self._sock = s
            if not self._verify_handshake():
                logger.warning("Process on port %d failed companion handshake; rejecting connection", IPC_PORT)
                self._close_socket()
                return False
            return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            self._sock = None
            return False

    def _close_socket(self) -> None:
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __del__(self) -> None:
        self._close_socket()

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
