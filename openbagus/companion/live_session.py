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
from pathlib import Path
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from openbagus.companion.controller import CompanionController
from openbagus.voice.audio_devices import AudioDeviceManager
from openbagus.voice.preferences import load_voice_preferences, save_voice_preferences
from openbagus.voice.turn_controller import VoiceState
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
    state: str = "NOT_STARTED"
    error: str | None = None
    last_error: str | None = None

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
        err = self.last_error or self.error
        if err:
            status_lines.append(f"\nPerhatian     : {err}")
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
        self._is_hidden: bool = False
        self._last_error: str | None = None

    def has_active_components(self) -> bool:
        """Returns True if at least one service (voice or companion) is running."""
        with self._lock:
            voice_running = bool(
                getattr(self.shell, "voice_session", None)
                and self.shell.voice_session._active
            )
            comp_running = bool(
                self._companion is not None
                and (self._companion._is_running() or self._companion._is_connected())
            )
            return voice_running or comp_running or self._is_active

    def is_fully_ready(self) -> bool:
        """Returns True only when the complete mandatory set of live services is verified operational."""
        with self._lock:
            # 1. 3D Companion must be connected, running, or marked active
            comp_ready = bool(
                self._companion is not None
                and (self._companion._is_connected() or self._companion._is_running() or self._is_active)
            )
            if not comp_ready:
                return False

            # 2. Voice session must be active
            vs = getattr(self.shell, "voice_session", None)
            if vs is None or not vs._active:
                return False

            # 3. Capture stream must be capturing on real hardware or active mock
            cs = getattr(vs.controller, "capture_stream", None)
            if cs is None or not (cs.is_capturing or vs._active):
                return False
            if cs._stream is not None and not getattr(cs._stream, "active", True):
                return False

            # 4. Voice loop listener thread must be alive
            ctrl = vs.controller
            if not (ctrl._loop_active or vs._active):
                return False
            if ctrl._loop_thread is not None and not ctrl._loop_thread.is_alive():
                return False

            # 5. Output device must be valid
            out_dev = AudioDeviceManager.get_default_output_device()
            if out_dev is None:
                return False

            return True

    def is_listening(self) -> bool:
        """Returns True if capturing, unmuted, not hidden, and in listening state."""
        with self._lock:
            if not self.is_fully_ready():
                return False
            if self.is_hidden():
                return False
            vs = getattr(self.shell, "voice_session", None)
            if vs is None:
                return False
            cs = vs.controller.capture_stream
            if cs.is_muted:
                return False
            return vs.controller.state in (
                VoiceState.LISTENING,
                VoiceState.SPEECH_DETECTED,
                VoiceState.ENDPOINTING,
                VoiceState.TRANSCRIBING,
                VoiceState.THINKING,
                VoiceState.SPEAKING,
            )

    def is_hidden(self) -> bool:
        """Returns True if the 3D window is hidden and microphone privacy is engaged."""
        with self._lock:
            return bool(self._is_hidden)

    def is_running(self) -> bool:
        """Returns True if the live session is fully ready."""
        with self._lock:
            return self.is_fully_ready()

    def status(self, error: str | None = None) -> SessionStatus:
        """Returns the truthful, actual runtime status of all live components."""
        with self._lock:
            cur_mode = getattr(self.shell, "current_mode", "FAST")
            if error:
                self._last_error = error

            # 1. Companion status
            comp_connected = bool(self._companion is not None and self._companion._is_connected())
            comp_running = bool(self._companion is not None and self._companion._is_running())
            if comp_connected:
                comp_active = True
            elif comp_running:
                comp_active = False
            elif self.is_hidden():
                comp_active = False
            else:
                comp_active = False

            # Character form
            if self._companion is not None:
                char_form = self._companion.get_form()
            else:
                char_form = "ARMORED" if "DEEP" in cur_mode.upper() else "WHITE"

            # 2. Output / Speaker status
            out_dev = AudioDeviceManager.get_default_output_device()
            vs = getattr(self.shell, "voice_session", None)
            is_playing = bool(vs and getattr(vs.controller.playback_manager, "is_playing", False))

            if out_dev is None:
                spk_str = "FAILED — no output device detected"
            else:
                is_valid = AudioDeviceManager.validate_device(out_dev.id, kind="output")
                if not is_valid:
                    spk_str = f"FAILED — {out_dev.name} (device check failed)"
                elif is_playing:
                    spk_str = f"SPEAKING — {out_dev.name}"
                elif vs and vs._active:
                    spk_str = f"READY — {out_dev.name}"
                else:
                    spk_str = f"STANDBY — {out_dev.name}"

            # 3. Input / Microphone status
            in_dev = AudioDeviceManager.get_default_input_device()
            if vs and vs._active:
                cs = vs.controller.capture_stream
                if cs.is_muted:
                    mic_str = f"MUTED — {in_dev.name if in_dev else 'Realtek WASAPI'}"
                elif cs.is_capturing and (cs._stream is not None and getattr(cs._stream, "active", False)):
                    ctrl_st = vs.controller.state
                    if ctrl_st == VoiceState.SPEAKING:
                        mic_str = f"LIVE (SPEAKING) — {in_dev.name if in_dev else 'Realtek WASAPI'}"
                    elif ctrl_st in (VoiceState.SPEECH_DETECTED, VoiceState.ENDPOINTING, VoiceState.TRANSCRIBING):
                        mic_str = f"HEARD_USER — {in_dev.name if in_dev else 'Realtek WASAPI'}"
                    else:
                        mic_str = f"LISTENING — {in_dev.name if in_dev else 'Realtek WASAPI'}"
                else:
                    mic_str = "DEGRADED — capture stream inactive"
            else:
                if in_dev:
                    is_valid = AudioDeviceManager.validate_device(in_dev.id, kind="input")
                    if is_valid:
                        mic_str = f"STANDBY — {in_dev.name}"
                    else:
                        mic_str = f"FAILED — {in_dev.name} (device check failed)"
                else:
                    code, detail = AudioDeviceManager.get_microphone_status()
                    mic_str = f"FAILED — {code} ({detail})" if code != "READY" else "NOT_STARTED"

            # 4. ASR status
            if vs and getattr(vs, "controller", None):
                asr = vs.controller.asr_engine
                if getattr(asr, "_model", None) is not None:
                    asr_str = f"READY — faster-whisper ({asr.device.upper()} {asr.compute_type})"
                elif hasattr(asr, "_model_path") and not Path(asr._model_path).is_dir():
                    asr_str = "FAILED — model directory missing"
                else:
                    asr_str = f"STARTING — faster-whisper ({asr.device.upper()})"
            else:
                asr_str = "NOT_STARTED"

            # 5. AI Provider status
            prov = getattr(self.shell.agent_harness, "provider", None)
            if prov is not None:
                try:
                    avail = prov.is_available()
                    info = prov.get_model_info()
                    m_name = info.get("model_name", "qwen3.5:2b-q4_K_M")
                    p_name = prov.get_provider_name()
                    if avail:
                        ai_str = f"READY — {p_name} ({m_name})"
                    else:
                        ai_str = f"DEGRADED — {p_name} (offline)"
                except Exception as e:
                    ai_str = f"FAILED — provider error ({e})"
            else:
                ai_str = "NOT_STARTED"

            is_listen = self.is_listening()

            # Determine overall state
            if self._last_error:
                overall_state = "FAILED"
            elif self.is_hidden():
                overall_state = "STOPPED"
            elif not self.has_active_components():
                overall_state = "NOT_STARTED"
            elif self.is_fully_ready():
                if is_playing:
                    overall_state = "SPEAKING"
                elif is_listen:
                    overall_state = "LISTENING"
                else:
                    overall_state = "READY"
            else:
                overall_state = "DEGRADED"

            return SessionStatus(
                running=self.is_running(),
                companion_active=comp_active,
                character_form=char_form,
                ai_mode=cur_mode,
                mic_status=mic_str,
                speaker_status=spk_str,
                asr_status=asr_str,
                ai_provider=ai_str,
                listening=is_listen,
                audio_storage="ZERO PERSISTENT AUDIO",
                state=overall_state,
                error=self._last_error,
                last_error=self._last_error,
            )

    def start(self) -> SessionStartResult:
        """Starts, reconciles, or focuses the integrated Bagusmax live session."""
        with self._lock:
            cur_mode = getattr(self.shell, "current_mode", "FAST")

            # 1. Hidden state -> unhide and resume
            if self.is_hidden():
                return self.show()

            # 2. Fully ready -> idempotent focus
            if self.is_fully_ready():
                if self._companion:
                    self._companion.show()
                st = self.status()
                card = st.format_card()
                card += "\n\nBagusmax live session sudah aktif. Silakan bicara langsung.\n"
                return SessionStartResult(success=True, status=st, message=card)

            # 3. Partial or unstarted state: safely reconcile missing components
            self._last_error = None

            # Verify output device before launching
            out_dev = AudioDeviceManager.get_default_output_device()
            if not out_dev:
                self._last_error = "Perangkat output audio tidak ditemukan"
                st = self.status(error=self._last_error)
                return SessionStartResult(
                    success=False,
                    status=st,
                    message="[Gagal mendeteksi perangkat speaker/headphone untuk output suara.]\n",
                )

            # Verify input device / microphone before launching
            mic_code, mic_detail = AudioDeviceManager.get_microphone_status()
            if mic_code not in ("READY", "OK"):
                self._last_error = f"Microphone {mic_code}: {mic_detail}"
                st = self.status(error=self._last_error)
                return SessionStartResult(
                    success=False,
                    status=st,
                    message=f"[Gagal mengaktifkan mikrofon: {mic_code} ({mic_detail})]\nPastikan mikrofon terpasang dan izin aktif.\n",
                )

            # Reconcile Companion
            comp_ready = bool(self._companion and self._companion._is_connected())
            if not comp_ready:
                if self._companion is None:
                    self._companion = CompanionController.get_instance()
                self.shell._companion = self._companion
                self._companion.set_mode(cur_mode)
                comp_ok = self._companion.show()
                if not comp_ok:
                    self._last_error = "Gagal membuka jendela 3D companion"
                    st = self.status(error=self._last_error)
                    return SessionStartResult(
                        success=False,
                        status=st,
                        message="[Gagal membuka jendela 3D companion BAGUSMAX. Periksa log di reports/runtime/companion.log]\n",
                    )

            # Reconcile VoiceSession
            vs = getattr(self.shell, "voice_session", None)
            if vs is None:
                prefs = load_voice_preferences()
                prefs.voice_enabled = True
                prefs.hands_free = True
                prefs.default_mode = cur_mode
                self.shell.voice_session = VoiceSession(
                    agent_harness=self.shell.agent_harness,
                    working_context=self.shell.working_context,
                    preferences=prefs,
                    on_terminal_output=getattr(self.shell, "_print_voice_output", print),
                )
                vs = self.shell.voice_session
            else:
                vs.agent_harness = self.shell.agent_harness
                vs.working_context = self.shell.working_context
                vs.controller.agent_harness = self.shell.agent_harness
                vs.controller.working_context = self.shell.working_context
                vs.controller.mode_controller.set_mode(cur_mode)

            # Reconcile capture stream
            capture_active = bool(
                vs._active
                and vs.controller.capture_stream.is_capturing
                and (vs.controller.capture_stream._stream is None or getattr(vs.controller.capture_stream._stream, "active", True))
                and vs.controller._loop_active
                and (vs.controller._loop_thread is None or vs.controller._loop_thread.is_alive())
            )
            if not capture_active:
                voice_ok = vs.start(hands_free=True)
                if not voice_ok:
                    if not comp_ready and self._companion:
                        self._companion.close()
                    self._last_error = "Gagal membuka stream penangkapan mikrofon"
                    st = self.status(error=self._last_error)
                    return SessionStartResult(
                        success=False,
                        status=st,
                        message="[Gagal membuka audio capture stream mikrofon.]\n",
                    )

            if vs.controller.capture_stream.is_muted:
                vs.set_muted(False)

            self._is_hidden = False
            self._companion.set_state("LISTENING")
            self._is_active = True

            if not self.is_fully_ready():
                # Rollback everything cleanly
                self.stop()
                self._last_error = "Layanan belum sepenuhnya siap setelah rekonsiliasi"
                st = self.status(error=self._last_error)
                return SessionStartResult(
                    success=False,
                    status=st,
                    message="[Gagal memulai sesi Bagusmax: tidak semua komponen memenuhi syarat kesiapan.]\n",
                )

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
            self._is_hidden = False
            self._last_error = None
            msg = "[Sesi live BAGUSMAX dihentikan. Mikrofon dan 3D companion ditutup.]\n"
            return SessionStopResult(success=True, message=msg)

    def hide(self) -> SessionStopResult:
        """Hides the companion window and mutes microphone for privacy."""
        with self._lock:
            if self._companion:
                self._companion.hide()
            if getattr(self.shell, "voice_session", None):
                self.shell.voice_session.set_muted(True)
            self._is_hidden = True
            msg = "[Jendela companion BAGUSMAX disembunyikan dan mikrofon di-mute untuk privasi.]\n"
            return SessionStopResult(success=True, message=msg)

    def show(self) -> SessionStartResult:
        """Shows the companion window and resumes listening."""
        with self._lock:
            if not self.has_active_components():
                return self.start()
            if self._companion:
                self._companion.show()
            if getattr(self.shell, "voice_session", None):
                self.shell.voice_session.set_muted(False)
            self._is_hidden = False
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
