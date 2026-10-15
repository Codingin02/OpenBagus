"""Voice session manager providing high-level lifecycle, terminal UI formatting, and controls."""

from __future__ import annotations

import logging
import shutil
from typing import Any, Callable

from openbagus.ai.harness.orchestrator import AgentHarness
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.voice.audio_capture import AudioCaptureStream
from openbagus.voice.audio_devices import AudioDeviceManager
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.gpu_scheduler import GPUScheduler
from openbagus.voice.preferences import VoicePreferences, load_voice_preferences, save_voice_preferences
from openbagus.voice.tts_engine import LocalTTSEngine
from openbagus.voice.turn_controller import VoiceState, VoiceTurnController

logger = logging.getLogger(__name__)


class VoiceSession:
    """Manages interactive voice session lifecycle, terminal layout, and audio controls."""

    def __init__(
        self,
        agent_harness: AgentHarness | None = None,
        working_context: WorkingContext | None = None,
        preferences: VoicePreferences | None = None,
        on_terminal_output: Callable[[str], None] | None = None,
    ) -> None:
        self.working_context = working_context or WorkingContext()
        self.agent_harness = agent_harness or AgentHarness()
        self.on_terminal_output = on_terminal_output or print
        self.gpu_scheduler = GPUScheduler.get_instance()
        self.preferences = preferences or load_voice_preferences()

        try:
            from openbagus.core.model_resolver import get_model_resolver
            get_model_resolver().configure_environment_caches()
        except Exception as e:
            logger.debug("ModelResolver cache configuration notice: %s", e)

        in_dev, out_dev = self.preferences.resolve_devices()
        capture_stream = AudioCaptureStream(
            device_id=in_dev,
            level_callback=self._on_level_meter,
        )
        playback_manager = AudioPlaybackManager(
            device_id=out_dev,
            volume=self.preferences.volume,
        )
        tts_engine = LocalTTSEngine(
            preset=self.preferences.voice_preset,
            speed=self.preferences.speed,
            volume=self.preferences.volume,
        )

        self.controller = VoiceTurnController(
            agent_harness=self.agent_harness,
            working_context=self.working_context,
            tts_engine=tts_engine,
            capture_stream=capture_stream,
            playback_manager=playback_manager,
            ask_mode_confirmation=False,  # Frictionless natural two-way conversation
            on_state_change=self._on_state_change,
            on_user_transcript=self._on_user_transcript,
            on_agent_response=self._on_agent_response,
            on_level_meter=self._on_level_meter,
        )

        self._active = False
        self._terminal_width = 80
        self._update_terminal_size()

    def _update_terminal_size(self) -> None:
        try:
            self._terminal_width = min(120, max(60, shutil.get_terminal_size().columns))
        except Exception:
            self._terminal_width = 80

    def start(self, hands_free: bool | None = None) -> bool:
        """Starts the voice session."""
        self._update_terminal_size()
        hf = hands_free if hands_free is not None else self.preferences.hands_free
        success = self.controller.start_voice_loop(hands_free=hf)
        if success:
            self._active = True
            dev_in = AudioDeviceManager.get_default_input_device()
            dev_out = AudioDeviceManager.get_default_output_device()
            gpu_st = self.gpu_scheduler.query_gpu_status()

            self.on_terminal_output("\n" + "=" * self._terminal_width)
            self.on_terminal_output("=== OpenBagus Local Native Voice Assistant ===".center(self._terminal_width))
            self.on_terminal_output(f"Mode          : {self.controller.mode_controller.current_mode} (NVIDIA RTX CUDA)")
            self.on_terminal_output(f"Voice Preset  : {self.preferences.voice_preset} (Baymax Demeanor)")
            self.on_terminal_output(f"Interaksi     : {'Hands-Free (VAD Aktif)' if hf else 'Push-to-Talk'}")
            self.on_terminal_output(f"Mikrofon      : {dev_in.name if dev_in else 'Default'}")
            self.on_terminal_output(f"Speaker       : {dev_out.name if dev_out else 'Default'}")
            self.on_terminal_output(f"Audio Storage : STRICTLY ZERO-DISK (Ephemeral Memory Only)")
            self.on_terminal_output(f"GPU Akselerasi: {gpu_st.device_name} (VRAM: {gpu_st.vram_used_mb:.0f}/{gpu_st.vram_total_mb:.0f} MB)")
            self.on_terminal_output("Silakan bicara langsung dalam Bahasa Indonesia. Tekan Ctrl+C untuk keluar.")
            self.on_terminal_output("=" * self._terminal_width + "\n")
        return success

    def stop(self) -> None:
        """Stops the voice session."""
        self._active = False
        self.controller.stop_voice_loop()
        self.on_terminal_output("\n[Sesi Suara OpenBagus Dihentikan]\n")

    def stop_speaking(self) -> None:
        """Immediate barge-in / mute assistant speech."""
        self.controller.playback_manager.stop_playback(interrupted=True)

    def set_muted(self, muted: bool) -> None:
        self.controller.capture_stream.set_muted(muted)
        self.on_terminal_output(f"[Mikrofon: {'NONAKTIF (Muted)' if muted else 'AKTIF'}]")

    def set_mode(self, mode: str) -> None:
        self.controller.mode_controller.set_mode(mode)
        self.on_terminal_output(f"[Mode penalaran dialihkan ke: {self.controller.mode_controller.current_mode}]")

    def set_preset(self, preset_name: str) -> bool:
        """Switches voice preset and persists preference."""
        ok = self.controller.tts_engine.set_preset(preset_name)
        if ok:
            self.preferences.voice_preset = preset_name
            save_voice_preferences(self.preferences)
            self.on_terminal_output(f"[Voice preset diubah ke: {preset_name}]")
        return ok

    def save_preferences(self) -> bool:
        return save_voice_preferences(self.preferences)

    def _on_state_change(self, old: VoiceState, new: VoiceState) -> None:
        pass

    def _on_level_meter(self, db: float) -> None:
        pass

    def _on_user_transcript(self, transcript: str, is_final: bool) -> None:
        """Renders user transcript with right-aligned layout."""
        self._update_terminal_size()
        prefix = "User: "
        bubble = f"{prefix}\"{transcript}\""
        pad = max(0, self._terminal_width - len(bubble) - 4)
        formatted = " " * pad + f"[Suara] 💬 {transcript}"
        self.on_terminal_output("\n" + formatted + "\n")

    def _on_agent_response(self, display_text: str, spoken_text: str) -> None:
        """Renders assistant response with clear opposing left-aligned layout."""
        self.on_terminal_output(f"OpenBagus 🤖 ({self.controller.mode_controller.current_mode}):")
        self.on_terminal_output(display_text)
        self.on_terminal_output("-" * min(80, self._terminal_width))

    def get_status_summary(self) -> dict[str, Any]:
        gpu = self.gpu_scheduler.query_gpu_status()
        diag = self.controller.diagnostics.get_summary_statistics()
        return {
            "active": self._active,
            "state": self.controller.state.value,
            "mode": self.controller.mode_controller.current_mode,
            "preset": self.preferences.voice_preset,
            "gpu": gpu.to_dict(),
            "diagnostics": diag,
            "mic_muted": self.controller.capture_stream.is_muted,
            "playback_playing": self.controller.playback_manager.is_playing,
            "audio_storage": self.preferences.audio_storage,
        }
