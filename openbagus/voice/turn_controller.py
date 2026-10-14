"""Stateful conversational voice turn controller managing states, barge-in, and agent bridging."""

from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from typing import Any, Callable
import numpy as np

from openbagus.ai.harness.orchestrator import AgentHarness, AgentResponse
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.voice.audio_capture import AudioCaptureStream
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.asr_engine import LocalASREngine
from openbagus.voice.diagnostics import VoiceDiagnostics, VoiceTurnMetrics
from openbagus.voice.interruption import InterruptionCoordinator
from openbagus.voice.mode_controller import VoiceModeController
from openbagus.voice.speech_normalizer import SpeechTextNormalizer
from openbagus.voice.tts_engine import LocalTTSEngine
from openbagus.voice.vad import VoiceActivityDetector

try:
    from openbagus.companion.controller import CompanionController
except ImportError:
    CompanionController = None  # type: ignore

logger = logging.getLogger(__name__)


class VoiceState(str, enum.Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    SPEECH_DETECTED = "SPEECH_DETECTED"
    ENDPOINTING = "ENDPOINTING"
    TRANSCRIBING = "TRANSCRIBING"
    MODE_SELECTION = "MODE_SELECTION"
    THINKING = "THINKING"
    GENERATING_SPEECH = "GENERATING_SPEECH"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class VoiceTurnController:
    """Orchestrates two-way spoken conversation turns, mode selection, and agent integration."""

    def __init__(
        self,
        agent_harness: AgentHarness | None = None,
        working_context: WorkingContext | None = None,
        asr_engine: LocalASREngine | None = None,
        tts_engine: LocalTTSEngine | None = None,
        capture_stream: AudioCaptureStream | None = None,
        playback_manager: AudioPlaybackManager | None = None,
        mode_controller: VoiceModeController | None = None,
        on_state_change: Callable[[VoiceState, VoiceState], None] | None = None,
        on_user_transcript: Callable[[str, bool], None] | None = None,
        on_agent_response: Callable[[str, str], None] | None = None,
        on_level_meter: Callable[[float], None] | None = None,
    ) -> None:
        self.agent_harness = agent_harness or AgentHarness()
        self.working_context = working_context or WorkingContext()
        self.asr_engine = asr_engine or LocalASREngine()
        self.tts_engine = tts_engine or LocalTTSEngine()
        self.capture_stream = capture_stream or AudioCaptureStream(level_callback=on_level_meter)
        self.playback_manager = playback_manager or AudioPlaybackManager()
        self.mode_controller = mode_controller or VoiceModeController()
        self.vad = VoiceActivityDetector()
        self.diagnostics = VoiceDiagnostics()
        self.interruption = InterruptionCoordinator(on_interruption_callback=self._handle_interruption)

        self.on_state_change = on_state_change
        self.on_user_transcript = on_user_transcript
        self.on_agent_response = on_agent_response
        self.on_level_meter = on_level_meter

        self.state = VoiceState.IDLE
        self._lock = threading.Lock()
        self._loop_active = False
        self._loop_thread: threading.Thread | None = None
        self._hands_free = True
        self._current_turn_id: str = ""
        self._companion = None
        if CompanionController is not None:
            try:
                self._companion = CompanionController.get_instance()
            except Exception:
                self._companion = None

        # Wire synchronized audio playback callbacks to companion
        self._setup_playback_companion_callbacks()

    def _setup_playback_companion_callbacks(self) -> None:
        """Wire real-time audio playback events to the companion controller."""
        if not hasattr(self.playback_manager, "on_playback_level"):
            return

        def _on_start() -> None:
            if self._companion is not None:
                try:
                    self._companion.tts_playback_started(self._current_turn_id)
                except Exception:
                    pass

        def _on_finish() -> None:
            if self._companion is not None:
                try:
                    self._companion.tts_playback_finished(self._current_turn_id)
                except Exception:
                    pass

        def _on_level(amp: float) -> None:
            if self._companion is not None:
                try:
                    self._companion.tts_playback_level(amp, turn_id=self._current_turn_id)
                except Exception:
                    pass

        def _on_interrupted() -> None:
            if self._companion is not None:
                try:
                    self._companion.user_interrupted(self._current_turn_id)
                except Exception:
                    pass

        self.playback_manager.on_start = _on_start
        self.playback_manager.on_finish = _on_finish
        self.playback_manager.on_playback_level = _on_level
        self.playback_manager.on_interrupted = _on_interrupted

    def set_state(self, new_state: VoiceState) -> None:
        with self._lock:
            old = self.state
            if old != new_state:
                self.state = new_state
                logger.debug("VoiceState changed: %s -> %s", old.value, new_state.value)
                if self.on_state_change:
                    try:
                        self.on_state_change(old, new_state)
                    except Exception as e:
                        logger.warning("Error in on_state_change: %s", e)

                if self._companion is not None:
                    try:
                        # Typed lifecycle events
                        if new_state == VoiceState.SPEECH_DETECTED:
                            self._companion.user_speech_started(self._current_turn_id)
                        elif new_state == VoiceState.ENDPOINTING:
                            self._companion.user_speech_ended(self._current_turn_id)
                        elif new_state == VoiceState.TRANSCRIBING:
                            self._companion.asr_started(self._current_turn_id)
                        elif new_state in (VoiceState.THINKING, VoiceState.MODE_SELECTION, VoiceState.GENERATING_SPEECH):
                            mode_name = getattr(self.mode_controller, "current_mode", "FAST")
                            self._companion.agent_thinking(self._current_turn_id, mode=mode_name)
                        elif new_state == VoiceState.INTERRUPTED:
                            self._companion.user_interrupted(self._current_turn_id)
                        elif new_state in (VoiceState.IDLE, VoiceState.CANCELLED):
                            self._companion.system_idle()
                        elif new_state == VoiceState.LISTENING:
                            self._companion.set_state("LISTENING")
                    except Exception:
                        pass

    def _handle_interruption(self, turn_id: str) -> None:
        """Called immediately when barge-in is triggered."""
        self.playback_manager.stop_playback(interrupted=True)
        if self._companion is not None:
            try:
                self._companion.user_interrupted(turn_id)
            except Exception:
                pass
        self.set_state(VoiceState.INTERRUPTED)

    def start_voice_loop(self, hands_free: bool = True) -> bool:
        """Starts real-time microphone capture and voice listening loop."""
        self._hands_free = hands_free
        if not self.capture_stream.start():
            self.set_state(VoiceState.ERROR)
            return False

        self._loop_active = True
        self.set_state(VoiceState.LISTENING)
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True, name="VoiceControllerLoop")
        self._loop_thread.start()
        return True

    def stop_voice_loop(self) -> None:
        """Stops voice session cleanly."""
        self._loop_active = False
        self.capture_stream.stop()
        self.playback_manager.stop_playback(interrupted=False)
        self.set_state(VoiceState.IDLE)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)

    def _run_loop(self) -> None:
        """Background frame polling loop processing microphone frames and VAD events."""
        while self._loop_active:
            time.sleep(0.015)  # Polling interval matching ~16ms half-frame

            # Handle Barge-In when assistant is currently speaking
            if self.state == VoiceState.SPEAKING:
                frame = self.capture_stream.get_latest_frame()
                if frame is not None:
                    is_active, _, prob = self.vad.process_frame(frame)
                    # Barge-in confirmed if user speaks with sufficient confidence while assistant speaks
                    if is_active and prob > 0.65:
                        self.interruption.trigger_interruption(reason="USER_SPOKE_DURING_ASSISTANT_PLAYBACK")
                        self.capture_stream.start_utterance()
                        self.set_state(VoiceState.SPEECH_DETECTED)
                continue

            # Standard listening states
            if self.state in (VoiceState.LISTENING, VoiceState.SPEECH_DETECTED, VoiceState.ENDPOINTING):
                frame = self.capture_stream.get_latest_frame()
                if frame is None:
                    continue

                is_active, is_endpoint, prob = self.vad.process_frame(frame)

                if is_active and self.state == VoiceState.LISTENING:
                    self._current_turn_id = f"turn_{uuid.uuid4().hex[:8]}"
                    self.set_state(VoiceState.SPEECH_DETECTED)
                    self.capture_stream.start_utterance()

                elif self.state in (VoiceState.SPEECH_DETECTED, VoiceState.ENDPOINTING):
                    if is_endpoint:
                        self.set_state(VoiceState.ENDPOINTING)
                        self._process_completed_utterance()
                    elif not is_active:
                        self.set_state(VoiceState.ENDPOINTING)
                    else:
                        self.set_state(VoiceState.SPEECH_DETECTED)
                        if self._companion is not None:
                            try:
                                frame_rms = float(np.sqrt(np.mean(np.square(frame))))
                                self._companion.user_speech_level(min(1.0, max(0.0, frame_rms * 4.0)), self._current_turn_id)
                            except Exception:
                                pass

    def _process_completed_utterance(self) -> None:
        """Triggered once silence endpointing confirms the user finished their utterance."""
        audio = self.capture_stream.end_utterance()
        self.vad.reset()

        if len(audio) < 16000 * 0.4:  # Ignore clicks / noise shorter than 400ms
            self.set_state(VoiceState.LISTENING)
            return

        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        self._current_turn_id = turn_id
        self.interruption.start_turn(turn_id)
        metrics = VoiceTurnMetrics(turn_id=turn_id, user_speech_duration_s=len(audio) / 16000.0)

        # STEP 1: Speech-to-Text (ASR)
        self.set_state(VoiceState.TRANSCRIBING)
        t_asr_start = time.perf_counter()
        normalized_res, asr_telemetry = self.asr_engine.transcribe(audio, sample_rate=16000)
        metrics.asr_latency_ms = asr_telemetry.get("latency_ms", (time.perf_counter() - t_asr_start) * 1000.0)

        transcript = normalized_res.normalized_text
        if not transcript:
            self.set_state(VoiceState.LISTENING)
            return

        if self.on_user_transcript:
            self.on_user_transcript(transcript, True)

        # STEP 2: Check Mode Selection Commands or Pending Queries
        mode_cmd_reply = self.mode_controller.handle_mode_commands(transcript)
        if mode_cmd_reply:
            self._speak_response(mode_cmd_reply, mode_cmd_reply, metrics)
            return

        # Check if user is answering a pending mode selection question
        if self.mode_controller.has_pending_query():
            resolved_mode, pending = self.mode_controller.resolve_spoken_mode_answer(transcript)
            if pending:
                transcript = pending.original_query
                logger.info("Resuming original query '%s' with resolved mode: %s", transcript[:30], resolved_mode)

        elif self.mode_controller.should_ask_for_mode(transcript):
            # Ask verbally before expensive analysis
            prompt_q = self.mode_controller.set_pending_query(
                query=transcript,
                ticker=normalized_res.detected_tickers[0] if normalized_res.detected_tickers else None,
                strategy=normalized_res.detected_strategy,
            )
            self.set_state(VoiceState.MODE_SELECTION)
            self._speak_response(prompt_q, prompt_q, metrics)
            return

        # STEP 3: Execute Agent Harness
        self.set_state(VoiceState.THINKING)
        t_agent_start = time.perf_counter()
        active_profile = self.mode_controller.get_profile()
        metrics.mode = self.mode_controller.current_mode

        agent_resp = self.agent_harness.run(
            user_query=transcript,
            context=self.working_context,
            profile=active_profile,
        )
        metrics.agent_total_latency_ms = (time.perf_counter() - t_agent_start) * 1000.0
        metrics.tools_executed_count = len(agent_resp.tool_calls_executed)

        # STEP 4: Compose Spoken Speech and Play
        written_text = agent_resp.content
        spoken_text = SpeechTextNormalizer.to_spoken_text(written_text)

        if self.on_agent_response:
            self.on_agent_response(written_text, spoken_text)

        self._speak_response(written_text, spoken_text, metrics)

    def _speak_response(self, display_text: str, spoken_text: str, metrics: VoiceTurnMetrics) -> None:
        """Synthesizes and progressively streams spoken audio to playback manager."""
        self.set_state(VoiceState.GENERATING_SPEECH)
        cancellation = self.interruption.get_cancellation_event()

        t_tts_start = time.perf_counter()
        first_chunk = True

        for audio_chunk, tele in self.tts_engine.synthesize_stream(spoken_text, stop_event=cancellation):
            if cancellation.is_set():
                metrics.interrupted = True
                break

            if first_chunk:
                metrics.tts_ttfa_ms = tele.get("time_to_first_audio_ms", (time.perf_counter() - t_tts_start) * 1000.0)
                metrics.e2e_voice_latency_ms = metrics.asr_latency_ms + metrics.agent_total_latency_ms + metrics.tts_ttfa_ms
                first_chunk = False

            self.playback_manager.enqueue(audio_chunk, samplerate=self.tts_engine.sample_rate)

        metrics.tts_total_latency_ms = (time.perf_counter() - t_tts_start) * 1000.0
        self.diagnostics.record_turn(metrics)

        # Wait until audio queue drains or interruption occurs
        while self.playback_manager.is_playing:
            if cancellation.is_set():
                break
            time.sleep(0.04)

        self.set_state(VoiceState.LISTENING if self._hands_free else VoiceState.IDLE)

    def process_direct_utterance(self, audio: np.ndarray) -> tuple[str, str, VoiceTurnMetrics]:
        """Synchronous entry point for testing: takes audio array, returns (written, spoken, metrics)."""
        turn_id = f"test_{uuid.uuid4().hex[:6]}"
        self.interruption.start_turn(turn_id)
        metrics = VoiceTurnMetrics(turn_id=turn_id, user_speech_duration_s=len(audio) / 16000.0)

        # ASR
        t_asr_start = time.perf_counter()
        res, tele = self.asr_engine.transcribe(audio, sample_rate=16000)
        metrics.asr_latency_ms = tele.get("latency_ms", (time.perf_counter() - t_asr_start) * 1000.0)
        user_text = res.normalized_text

        # Agent
        t_ag = time.perf_counter()
        prof = self.mode_controller.get_profile()
        metrics.mode = self.mode_controller.current_mode
        resp = self.agent_harness.run(user_query=user_text, context=self.working_context, profile=prof)
        metrics.agent_total_latency_ms = (time.perf_counter() - t_ag) * 1000.0
        metrics.tools_executed_count = len(resp.tool_calls_executed)

        # TTS
        t_tts = time.perf_counter()
        spoken_text = SpeechTextNormalizer.to_spoken_text(resp.content)
        # Synthesize first sentence
        sentences = SpeechTextNormalizer.split_sentences(spoken_text)
        first_sent = sentences[0] if sentences else spoken_text
        chunk = self.tts_engine.synthesize_sentence(first_sent)
        metrics.tts_ttfa_ms = (time.perf_counter() - t_tts) * 1000.0
        metrics.e2e_voice_latency_ms = metrics.asr_latency_ms + metrics.agent_total_latency_ms + metrics.tts_ttfa_ms

        self.diagnostics.record_turn(metrics)
        return resp.content, spoken_text, metrics
