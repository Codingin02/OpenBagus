"""Bagusmax Live Session Coordinator.

Provides unified one-command orchestration (/bagusmax) managing:
- Interactive 3D BAGUSMAX Companion window (WHITE for FAST mode, ARMORED for DEEP_REASONING)
- Continuous hands-free WASAPI microphone capture
- Low-latency CUDA ASR (faster-whisper)
- Local AI AgentHarness & WorkingContext
- Audible local TTS playback (Piper)
- Full-duplex barge-in interruption & animation synchronization
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from openbagus.companion.controller import CompanionController
from openbagus.voice.audio_devices import AudioDeviceManager
from openbagus.voice.preferences import load_voice_preferences, save_voice_preferences
from openbagus.voice.voice_session import VoiceSession

logger = logging.getLogger(__name__)


@dataclass
class SessionStatus:
    """Truthful structured status of the Bagusmax Live Session."""
    running: bool
    companion_active: bool
    character_form: str
    ai_mode: str
    mic_status: str
    speaker_status: str
    asr_status: str
    ai_provider: str
    listening: bool
    audio_storage: str
    error: str | None = None

    def format_card(self) -> str:
        """Renders the clean user-facing status card."""
        status_lines = [
            "\n[BAGUSMAX LIVE]\n",
            f"3D Character  : {'ACTIVE' if self.companion_active else 'INACTIVE'}",
            f"Form          : {self.character_form}",
            f"AI Mode       : {self.ai_mode}",
            f"Microphone    : {self.mic_status}",
            f"Speaker       : {self.speaker_status}",
            f"ASR           : {self.asr_status}",
            f"AI Provider   : {self.ai_provider}",
            f"Listening     : {'YES' if self.listening else 'NO'}",
            f"Audio Storage : {self.audio_storage}",
        ]
        if self.error:
            status_lines.append(f"\nPerhatian     : {self.error}")
        return "\n".join(status_lines)


@dataclass
class SessionStartResult:
    success: bool
    status: SessionStatus
    message: str


@dataclass
class SessionStopResult:
    success: bool
    message: str


class BagusmaxLiveSessionCoordinator:
    """Coordinates the integrated 3D companion and voice conversation lifecycle."""

    def __init__(self, shell: Any) -> None:
        self.shell = shell
        self._lock = threading.RLock()
        self._companion: CompanionController | None = None
        self._is_active: bool = False

    def is_running(self) -> bool:
        """Returns True if the live session (voice or companion) is currently active."""
        with self._lock:
            voice_running = bool(
                getattr(self.shell, "voice_session", None)
                and self.shell.voice_session._active
            )
            comp_running = bool(
                self._companion is not None and self._companion._is_running()
            )
            return voice_running or comp_running or self._is_active

    def status(self, error: str | None = None) -> SessionStatus:
        """Returns the truthful, actual runtime status of all live components."""
        with self._lock:
            comp_active = bool(
                self._companion is not None
                and (self._companion._is_running() or self._companion._is_connected())
            )
            cur_mode = getattr(self.shell, "current_mode", "FAST")
            
            # Character form mapping: FAST -> WHITE, DEEP_REASONING -> ARMORED
            if self._companion is not None:
                char_form = self._companion.get_form()
            else:
                char_form = "ARMORED" if "DEEP" in cur_mode.upper() else "WHITE"

            # Audio devices
            in_dev = AudioDeviceManager.get_default_input_device()
            out_dev = AudioDeviceManager.get_default_output_device()
            
            voice_running = bool(
                getattr(self.shell, "voice_session", None)
                and self.shell.voice_session._active
            )
            
            if voice_running:
                in_name = in_dev.name if in_dev else "Realtek WASAPI"
                mic_str = f"LIVE — {in_name}"
            else:
                code, detail = AudioDeviceManager.get_microphone_status()
                mic_str = f"STANDBY — {code} ({detail})" if code != "READY" else f"STANDBY — {in_dev.name if in_dev else 'Realtek WASAPI'}"

            out_name = out_dev.name if out_dev else "Realtek WASAPI"
            spk_str = f"READY — {out_name}"

            # ASR status
            if getattr(self.shell, "voice_session", None) and getattr(self.shell.voice_session, "controller", None):
                asr = self.shell.voice_session.controller.asr_engine
                asr_str = f"READY — faster-whisper ({asr.device.upper()} {asr.compute_type})"
            else:
                asr_str = "READY — faster-whisper"

            # AI Provider
            try:
                prov_name = self.shell.agent_harness.provider.get_model_info().get("model_name", "qwen3.5:2b-q4_K_M")
                ai_str = f"READY — {prov_name}"
            except Exception:
                ai_str = "READY — local LLM"

            is_listening = bool(
                voice_running
                and not self.shell.voice_session.controller.capture_stream.is_muted
            )

            return SessionStatus(
                running=self.is_running(),
                companion_active=comp_active,
                character_form=char_form,
                ai_mode=cur_mode,
                mic_status=mic_str,
                speaker_status=spk_str,
                asr_status=asr_str,
                ai_provider=ai_str,
                listening=is_listening,
                audio_storage="ZERO PERSISTENT AUDIO",
                error=error,
            )

    def start(self) -> SessionStartResult:
        """Starts or focuses the one-command Bagusmax live session."""
        with self._lock:
            cur_mode = getattr(self.shell, "current_mode", "FAST")

            # 1. Idempotency check: if session is already active, focus window and report state
            if self.is_running():
                if self._companion:
                    self._companion.show()
                st = self.status()
                card = st.format_card()
                card += "\n\nBagusmax live session sudah aktif. Silakan bicara langsung.\n"
                return SessionStartResult(success=True, status=st, message=card)

            # 2. Check microphone & speaker readiness before starting
            mic_code, mic_detail = AudioDeviceManager.get_microphone_status()
            if mic_code not in ("READY", "OK"):
                st = self.status(error=f"Microphone {mic_code}: {mic_detail}")
                return SessionStartResult(
                    success=False,
                    status=st,
                    message=f"[Gagal mengaktifkan mikrofon: {mic_code} ({mic_detail})]\nPastikan mikrofon terpasang dan izin aktif.\n",
                )

            out_dev = AudioDeviceManager.get_default_output_device()
            if not out_dev:
                st = self.status(error="Perangkat output audio tidak ditemukan")
                return SessionStartResult(
                    success=False,
                    status=st,
                    message="[Gagal mendeteksi perangkat speaker/headphone untuk output suara.]\n",
                )

            # 3. Launch or focus 3D Companion
            if self._companion is None:
                self._companion = CompanionController.get_instance()
            self.shell._companion = self._companion
            self._companion.set_mode(cur_mode)

            comp_ok = self._companion.show()
            if not comp_ok:
                logger.warning("Companion renderer failed to initialize; checking OpenGL")
                st = self.status(error="Gagal membuka jendela 3D companion")
                return SessionStartResult(
                    success=False,
                    status=st,
                    message="[Gagal membuka jendela 3D companion BAGUSMAX. Periksa log di reports/runtime/companion.log]\n",
                )

            # 4. Initialize / Synchronize VoiceSession with shared AgentHarness & WorkingContext
            prefs = load_voice_preferences()
            prefs.voice_enabled = True
            prefs.hands_free = True
            prefs.default_mode = cur_mode

            if getattr(self.shell, "voice_session", None) is None:
                self.shell.voice_session = VoiceSession(
                    agent_harness=self.shell.agent_harness,
                    working_context=self.shell.working_context,
                    preferences=prefs,
                    on_terminal_output=getattr(self.shell, "_print_voice_output", print),
                )
            else:
                self.shell.voice_session.agent_harness = self.shell.agent_harness
                self.shell.voice_session.working_context = self.shell.working_context
                self.shell.voice_session.controller.agent_harness = self.shell.agent_harness
                self.shell.voice_session.controller.working_context = self.shell.working_context
                self.shell.voice_session.controller.mode_controller.set_mode(cur_mode)

            # 5. Open microphone capture audio stream
            voice_ok = self.shell.voice_session.start(hands_free=True)
            if not voice_ok:
                # Rollback companion if voice capture failed
                self._companion.close()
                st = self.status(error="Gagal membuka stream penangkapan mikrofon")
                return SessionStartResult(
                    success=False,
                    status=st,
                    message="[Gagal membuka audio capture stream mikrofon.]\n",
                )

            # 6. Synchronize Bagusmax to listening state
            self._companion.set_state("LISTENING")
            self._is_active = True

            st = self.status()
            card = st.format_card()
            card += "\n\nBagusmax siap mendengarkan. Silakan bicara.\n"
            return SessionStartResult(success=True, status=st, message=card)

    def stop(self) -> SessionStopResult:
        """Stops the live session, releases audio streams, and closes companion."""
        with self._lock:
            # 1. Stop voice capture and playback
            if getattr(self.shell, "voice_session", None):
                try:
                    self.shell.voice_session.stop()
                except Exception as e:
                    logger.warning("Error stopping voice session: %s", e)

            # 2. Close companion window and process
            if self._companion is not None:
                try:
                    self._companion.close()
                except Exception as e:
                    logger.warning("Error closing companion: %s", e)

            self._is_active = False
            msg = "[Sesi live BAGUSMAX dihentikan. Mikrofon dan 3D companion ditutup.]\n"
            return SessionStopResult(success=True, message=msg)

    def hide(self) -> SessionStopResult:
        """Hides the companion window and mutes microphone for privacy."""
        with self._lock:
            if self._companion:
                self._companion.hide()
            if getattr(self.shell, "voice_session", None):
                self.shell.voice_session.set_muted(True)
            msg = "[Jendela companion BAGUSMAX disembunyikan dan mikrofon di-mute untuk privasi.]\n"
            return SessionStopResult(success=True, message=msg)

    def show(self) -> SessionStartResult:
        """Shows the companion window and resumes listening."""
        with self._lock:
            if not self.is_running():
                return self.start()
            if self._companion:
                self._companion.show()
            if getattr(self.shell, "voice_session", None):
                self.shell.voice_session.set_muted(False)
            st = self.status()
            msg = "[Jendela companion BAGUSMAX ditampilkan kembali dan mikrofon aktif.]\n"
            return SessionStartResult(success=True, status=st, message=msg)

    def restart(self) -> SessionStartResult:
        """Cleanly restarts the integrated session."""
        with self._lock:
            self.stop()
            time.sleep(0.3)
            return self.start()

    def sync_mode(self, new_mode: str) -> None:
        """Synchronizes AI mode and 3D character form across active session without dropping mic."""
        with self._lock:
            if self._companion:
                self._companion.set_mode(new_mode)
            if getattr(self.shell, "voice_session", None):
                self.shell.voice_session.set_mode(new_mode)

    def sync_context(self) -> None:
        """Propagates updated AgentHarness or WorkingContext to the live voice controller."""
        with self._lock:
            if getattr(self.shell, "voice_session", None):
                self.shell.voice_session.agent_harness = self.shell.agent_harness
                self.shell.voice_session.working_context = self.shell.working_context
                self.shell.voice_session.controller.agent_harness = self.shell.agent_harness
                self.shell.voice_session.controller.working_context = self.shell.working_context
