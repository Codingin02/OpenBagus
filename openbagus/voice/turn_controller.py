"""Stateful conversational voice turn controller managing states, barge-in, and agent bridging."""

from __future__ import annotations

import enum
import logging
import re
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
from openbagus.voice.diagnostics import VoiceDiagnostics, VoiceEventRecord, VoiceTurnMetrics
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


INCOMPLETE_TRAILING_WORDS = {
    "dan", "atau", "untuk", "karena", "tapi", "tetapi", "terus", "kalau",
    "jika", "yaitu", "tentang", "seperti", "dengan", "soal", "saham",
    "analisis", "bagaimana", "kenapa", "apakah", "intinya", "lalu",
    "sebentar", "menurut", "anda", "kamu", "terkait", "secara", "pada",
    "mengenai", "serta", "yang", "itu", "jadi", "maksud", "saya",
    "kira-kira", "energi", "komoditas",
}

INCOMPLETE_PREFIXES = (
    "kalau menurut", "untuk saham", "terus kalau", "saya mau", "jadi intinya",
    "tapi sebentar", "tolong analisis", "analisis saham", "coba tolong",
    "kebijakan pemerintah", "kebijakan pemerintah terkait", "menurut anda",
    "menurut kamu", "saya mau bandingkan", "maksud saya", "apakah kebijakan",
    "jadi terus", "tolong analisis saham",
)


def is_likely_incomplete_utterance(transcript: str) -> bool:
    """Heuristic check to determine if an utterance is syntactically or semantically incomplete."""
    text = transcript.strip().lower()
    if not text:
        return True

    # Trailing punctuation indicating continuation (ellipsis or comma)
    if text.endswith("...") or text.endswith(",") or text.endswith("—"):
        return True

    for prefix in INCOMPLETE_PREFIXES:
        if text.startswith(prefix) and len(text.split()) <= 6:
            return True

    words = text.split()
    if not words:
        return True

    if len(words) <= 2 and words[0] in ("analisis", "tolong", "coba", "kalau", "untuk", "tadi", "jadi", "terus"):
        return True

    last_word = words[-1].rstrip(".,?!")
    if last_word in INCOMPLETE_TRAILING_WORDS:
        if last_word == "lalu" and len(words) >= 2 and words[-2] in ("tahun", "bulan", "minggu", "waktu", "masa"):
            pass
        else:
            return True

    # "Tolong analisis saham RATU" without timeframe/question clause when length is short
    if len(words) <= 4 and words[0] in ("tolong", "coba") and ("saham" in words or "emiten" in words):
        return True

    return False


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
        ask_mode_confirmation: bool = False,
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
        self.capture_stream.on_mute_callback = self._handle_mic_muted
        self.ask_mode_confirmation = ask_mode_confirmation

        self.on_state_change = on_state_change
        self.on_user_transcript = on_user_transcript
        self.on_agent_response = on_agent_response
        self.on_level_meter = on_level_meter

        self.state = VoiceState.IDLE
        self._lock = threading.Lock()
        self._loop_active = False
        self._loop_thread: threading.Thread | None = None
        self._turn_worker: threading.Thread | None = None
        self._barge_in_consecutive_frames: int = 0
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

    def _handle_mic_muted(self) -> None:
        """Called immediately when microphone is muted to cancel any active turn in flight."""
        logger.info("Microphone muted; cancelling any in-flight voice turn")
        self.interruption.trigger_interruption(reason="MICROPHONE_MUTED")
        self.playback_manager.stop_playback(interrupted=True)

    def start_voice_loop(self, hands_free: bool = True) -> bool:
        """Starts real-time microphone capture and voice listening loop."""
        self._hands_free = hands_free
        self.interruption.start_turn("")
        self.vad.reset()
        self._barge_in_consecutive_frames = 0
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
        self.interruption.trigger_interruption(reason="SESSION_STOP")
        self.capture_stream.stop()
        self.playback_manager.stop_playback(interrupted=False)
        self.set_state(VoiceState.IDLE)
        if self._turn_worker and self._turn_worker.is_alive():
            self._turn_worker.join(timeout=0.5)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)

    def _run_loop(self) -> None:
        """Background frame polling loop processing microphone frames, VAD events, and full-duplex barge-in."""
        while self._loop_active:
            # Single-pass frame acquisition from synchronized queue (timeout 30ms)
            frame = self.capture_stream.get_next_frame(timeout=0.03)
            if frame is None:
                continue

            # -------------------------------------------------------------
            # FULL-DUPLEX BARGE-IN: Detect user speech while assistant is
            # SPEAKING, GENERATING_SPEECH, or THINKING.
            # -------------------------------------------------------------
            if self.state in (VoiceState.SPEAKING, VoiceState.GENERATING_SPEECH, VoiceState.THINKING):
                frame_rms = float(np.sqrt(np.mean(np.square(frame))))
                _, _, prob = self.vad.process_frame(frame)

                # During playback, enforce render-reference acoustic tracking
                # to prevent laptop speaker bleed / echo from triggering false barge-in
                if self.state == VoiceState.SPEAKING:
                    render_rms = getattr(self.playback_manager, "get_current_render_energy", lambda: 0.0)()
                    if render_rms > 0.003:
                        # Attenuated echo estimate: laptop microphone picks up ~15-25% of speaker output
                        expected_echo = render_rms * 0.25
                        coupling_thresh = max(0.010, min(0.032, expected_echo + 0.005))
                        is_speech = (prob >= 0.62) and (frame_rms >= coupling_thresh)
                    else:
                        is_speech = (prob >= 0.60) and (frame_rms >= 0.006)
                else:
                    is_speech = (prob >= 0.60) and (frame_rms >= 0.005)

                if is_speech:
                    self._barge_in_consecutive_frames += 1
                    if self._barge_in_consecutive_frames >= 2:  # Sustained over ~64ms
                        logger.info(
                            "Barge-in confirmed during %s (rms=%.4f, prob=%.2f); interrupting turn %s",
                            self.state.value,
                            frame_rms,
                            prob,
                            self._current_turn_id,
                        )
                        self.interruption.trigger_interruption(reason="USER_BARGE_IN")
                        self.playback_manager.stop_playback(interrupted=True)
                        self.vad.reset()
                        self._barge_in_consecutive_frames = 0
                        self._current_turn_id = f"turn_{uuid.uuid4().hex[:8]}"
                        self.set_state(VoiceState.SPEECH_DETECTED)
                        self.capture_stream.start_utterance(self._current_turn_id)
                else:
                    self._barge_in_consecutive_frames = max(0, self._barge_in_consecutive_frames - 1)
                continue

            # -------------------------------------------------------------
            # LISTENING & ENDPOINTING STATES
            # -------------------------------------------------------------
            if self.state in (VoiceState.LISTENING, VoiceState.SPEECH_DETECTED, VoiceState.ENDPOINTING):
                self._barge_in_consecutive_frames = 0

                is_active, is_endpoint, prob = self.vad.process_frame(frame)

                if is_active and self.state == VoiceState.LISTENING:
                    self._current_turn_id = f"turn_{uuid.uuid4().hex[:8]}"
                    self.set_state(VoiceState.SPEECH_DETECTED)
                    self.capture_stream.start_utterance(self._current_turn_id)

                elif self.state in (VoiceState.SPEECH_DETECTED, VoiceState.ENDPOINTING):
                    if is_endpoint:
                        self.set_state(VoiceState.ENDPOINTING)
                        vad_evidence = self.vad.get_utterance_evidence()
                        audio, audio_meta = self.capture_stream.end_utterance_with_meta()
                        self.vad.reset()

                        # Silence Invariant: require verified physical speech evidence before invoking ASR
                        speech_dur = float(vad_evidence.get("speech_duration_s", 0.0))
                        speech_ratio = float(vad_evidence.get("speech_ratio", 0.0))
                        max_prob = float(vad_evidence.get("max_prob", 0.0))

                        if speech_dur < 0.28 or speech_ratio < 0.18 or max_prob < 0.58:
                            logger.debug(
                                "Turn discarded by Silence Invariant (dur=%.2fs, ratio=%.2f, max_prob=%.2f, audio_len=%d)",
                                speech_dur, speech_ratio, max_prob, len(audio),
                            )
                            self.diagnostics.record_event(VoiceEventRecord(
                                session_id=getattr(self.working_context, "session_id", "default"),
                                turn_id=self._current_turn_id,
                                audio_stream_id=audio_meta.get("stream_id", "") if audio_meta else "",
                                device_id=str(self.capture_stream.device_id),
                                event_type="UTTERANCE_REJECTED",
                                sample_rate=16000,
                                frame_count=len(audio),
                                rms=float(np.sqrt(np.mean(audio**2))) if len(audio) > 0 else 0.0,
                                peak=float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0,
                                vad_probability=max_prob,
                                vad_active=False,
                                speech_segment_duration=speech_dur,
                                asr_invoked=False,
                                transcript_accepted=False,
                                rejection_reason="SILENCE_INVARIANT_LOW_SPEECH_EVIDENCE",
                                playback_active=self.playback_manager.is_playing,
                            ))
                            self.set_state(VoiceState.LISTENING)
                        else:
                            self._start_turn_worker(audio, audio_meta, vad_evidence)

                    elif not is_active:
                        self.set_state(VoiceState.ENDPOINTING)
                    else:
                        self.set_state(VoiceState.SPEECH_DETECTED)
                        if self.vad.is_extended and prob >= self.vad.threshold:
                            # User resumed speaking; revert back to base timeout
                            self.vad.set_extended_silence(False)

                        if self._companion is not None:
                            try:
                                frame_rms = float(np.sqrt(np.mean(np.square(frame))))
                                self._companion.user_speech_level(min(1.0, max(0.0, frame_rms * 4.0)), self._current_turn_id)
                            except Exception:
                                pass

    def _start_turn_worker(
        self,
        audio: np.ndarray,
        audio_meta: dict[str, Any] | None = None,
        vad_evidence: dict[str, Any] | None = None,
    ) -> None:
        """Dispatches utterance processing to a separate thread so _run_loop remains responsive."""
        if self._turn_worker is not None and self._turn_worker.is_alive():
            self.interruption.trigger_interruption(reason="SUPERSEDED_BY_NEW_TURN")
            self._turn_worker.join(timeout=0.2)

        self._turn_worker = threading.Thread(
            target=self._process_completed_utterance,
            args=(audio, audio_meta, vad_evidence),
            daemon=True,
            name=f"TurnWorker_{self._current_turn_id}",
        )
        self._turn_worker.start()

    def _process_completed_utterance(
        self,
        audio: np.ndarray,
        audio_meta: dict[str, Any] | None = None,
        vad_evidence: dict[str, Any] | None = None,
    ) -> None:
        """Triggered once silence endpointing confirms the user finished their utterance."""
        turn_id = self._current_turn_id or f"turn_{uuid.uuid4().hex[:8]}"
        self._current_turn_id = turn_id
        self.interruption.start_turn(turn_id)
        cancellation = self.interruption.get_cancellation_event()

        if cancellation.is_set() or self.capture_stream.is_muted:
            logger.info("Turn %s cancelled before ASR start (muted=%s)", turn_id, self.capture_stream.is_muted)
            return

        metrics = VoiceTurnMetrics(turn_id=turn_id, user_speech_duration_s=len(audio) / 16000.0)

        # STEP 1: Speech-to-Text (ASR) with VAD Evidence Validation
        self.set_state(VoiceState.TRANSCRIBING)
        t_asr_start = time.perf_counter()
        normalized_res, asr_telemetry = self.asr_engine.transcribe(
            audio,
            sample_rate=16000,
            utterance_id=turn_id,
            vad_evidence=vad_evidence,
        )
        metrics.asr_latency_ms = asr_telemetry.get("latency_ms", (time.perf_counter() - t_asr_start) * 1000.0)

        if cancellation.is_set() or self.capture_stream.is_muted:
            logger.info("Turn %s cancelled during/after ASR (muted=%s)", turn_id, self.capture_stream.is_muted)
            return

        transcript = normalized_res.normalized_text

        # Record comprehensive telemetry event
        self.diagnostics.record_event(VoiceEventRecord(
            session_id=getattr(self.working_context, "session_id", "default"),
            turn_id=turn_id,
            audio_stream_id=audio_meta.get("stream_id", "") if audio_meta else "",
            device_id=str(self.capture_stream.device_id),
            event_type="ASR_COMPLETED",
            sample_rate=16000,
            frame_count=len(audio),
            rms=float(asr_telemetry.get("rms", 0.0)),
            peak=float(asr_telemetry.get("peak", 0.0)),
            vad_probability=float(vad_evidence.get("max_prob", 0.0)) if vad_evidence else 0.0,
            vad_active=True,
            speech_segment_duration=float(vad_evidence.get("speech_duration_s", 0.0)) if vad_evidence else 0.0,
            asr_invoked=True,
            transcript_accepted=bool(transcript),
            rejection_reason=str(asr_telemetry.get("rejection_reason", asr_telemetry.get("rejected", ""))),
            playback_active=self.playback_manager.is_playing,
        ))

        if not transcript:
            if not cancellation.is_set() and self.state == VoiceState.TRANSCRIBING:
                self.set_state(VoiceState.LISTENING)
            return

        if self.on_user_transcript:
            self.on_user_transcript(transcript, True)

        # STEP 2: Check Contextual Acknowledgments ("Oke", "Baik", "Siap") or Mode Selection
        cleaned_ack = transcript.lower().strip().rstrip(".!?,")

        # STEP 2a: Check Direct Stop Commands ("Berhenti", "Stop", "Cukup", "Diam")
        is_stop_cmd = any(cmd in cleaned_ack for cmd in ("berhenti", "stop", "cukup", "diam", "tutup mulut", "hentikan", "batal"))
        if is_stop_cmd:
            logger.info("Direct voice stop command executed: '%s'", transcript)
            self.playback_manager.stop_playback(interrupted=True)
            self.vad.reset()
            if not cancellation.is_set():
                self.set_state(VoiceState.LISTENING if self._hands_free else VoiceState.IDLE)
            return

        # STEP 2a-2: Check Pause / Hesitation Commands ("Sebentar", "Tunggu sebentar")
        is_pause_cmd = any(cmd in cleaned_ack for cmd in ("tunggu sebentar", "sebentar", "tunggu", "hold on", "wait", "sedang berpikir"))
        if is_pause_cmd:
            logger.info("Direct voice pause/hesitation command received: '%s'", transcript)
            self.playback_manager.stop_playback(interrupted=True)
            self.vad.set_extended_silence(True)
            if not cancellation.is_set():
                self._speak_response("Siap, saya tunggu.", "Siap, saya tunggu.", metrics, turn_id)
            return

        is_simple_ack = cleaned_ack in ("oke", "ok", "oke deh", "baik", "siap", "ya", "iya", "lanjutkan", "silakan")

        if is_simple_ack:
            # Check if there is an active pending action awaiting confirmation in working_context
            pending_action = getattr(self.working_context, "pending_action", None)
            if pending_action and isinstance(pending_action, dict):
                action_type = pending_action.get("action")
                ticker = pending_action.get("ticker", "")
                self.working_context.pending_action = None  # Consume authorization
                logger.info("Contextual acknowledgment '%s' authorized pending action: %s (%s)", transcript, action_type, ticker)
                transcript = pending_action.get("resume_query") or f"Lanjutkan analisis saham {ticker}."
            elif self.mode_controller.has_pending_query():
                resolved_mode, pending = self.mode_controller.resolve_spoken_mode_answer(transcript)
                if pending:
                    transcript = pending.original_query
                    logger.info("Resuming original query '%s' with resolved mode: %s", transcript[:30], resolved_mode)
            else:
                # Standalone acknowledgment without pending confirmation: fast path response
                logger.info("Fast-path acknowledgment for isolated '%s'", transcript)
                if not cancellation.is_set():
                    self._speak_response("Baik.", "Baik.", metrics, turn_id)
                return

        # STEP 2b: Check Conversational Fast-Path Greetings ("Halo Bagusmax", "Hai Bagusmax")
        greeting_reply = self._handle_greeting_utterance(transcript)
        if greeting_reply:
            logger.info("Conversational greeting fast-path triggered for: '%s'", transcript)
            if not cancellation.is_set():
                self._speak_response(greeting_reply, greeting_reply, metrics, turn_id)
            return

        # STEP 2c: Check Voice Preset Commands
        voice_cmd_reply = self._handle_voice_preset_commands(transcript)
        if voice_cmd_reply:
            if not cancellation.is_set():
                self._speak_response(voice_cmd_reply, voice_cmd_reply, metrics, turn_id)
            return

        mode_cmd_reply = self.mode_controller.handle_mode_commands(transcript)
        if mode_cmd_reply:
            if not cancellation.is_set():
                self._speak_response(mode_cmd_reply, mode_cmd_reply, metrics, turn_id)
            return

        # Check if user is answering a pending mode selection question
        if self.mode_controller.has_pending_query():
            resolved_mode, pending = self.mode_controller.resolve_spoken_mode_answer(transcript)
            if pending:
                transcript = pending.original_query
                logger.info("Resuming original query '%s' with resolved mode: %s", transcript[:30], resolved_mode)

        elif self.ask_mode_confirmation and self.mode_controller.should_ask_for_mode(transcript):
            # Ask verbally before expensive analysis only when mode confirmation is explicitly enabled
            prompt_q = self.mode_controller.set_pending_query(
                query=transcript,
                ticker=normalized_res.detected_tickers[0] if normalized_res.detected_tickers else None,
                strategy=normalized_res.detected_strategy,
            )
            self.set_state(VoiceState.MODE_SELECTION)
            if not cancellation.is_set():
                self._speak_response(prompt_q, prompt_q, metrics, turn_id)
            return
        else:
            # Frictionless natural conversation: automatically select mode if user specifies or query needs deep analysis
            low = transcript.lower()
            if any(k in low for k in ("deep reasoning", "mode mendalam", "analisis mendalam", "skenario lengkap", "monte carlo")):
                self.mode_controller.set_mode("DEEP_REASONING")
            elif any(k in low for k in ("mode cepat", "ringkas", "singkat", "cepat")):
                self.mode_controller.set_mode("FAST")

        if cancellation.is_set():
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
            mode=self.mode_controller.current_mode,
            cancellation=cancellation,
        )
        metrics.agent_total_latency_ms = (time.perf_counter() - t_agent_start) * 1000.0
        metrics.tools_executed_count = len(agent_resp.tool_calls_executed)

        if cancellation.is_set():
            logger.info("Turn %s cancelled during/after agent run", turn_id)
            return

        # STEP 4: Compose Spoken Speech and Play
        written_text = agent_resp.content
        spoken_text = SpeechTextNormalizer.to_spoken_text(written_text)

        if self.on_agent_response:
            self.on_agent_response(written_text, spoken_text)

        self._speak_response(written_text, spoken_text, metrics, turn_id)

    def _speak_response(
        self,
        display_text: str,
        spoken_text: str,
        metrics: VoiceTurnMetrics,
        turn_id: str | None = None,
    ) -> None:
        """Synthesizes and progressively streams spoken audio to playback manager with generation tracking."""
        gen_id = self.playback_manager.new_turn()
        self.set_state(VoiceState.GENERATING_SPEECH)
        cancellation = self.interruption.get_cancellation_event()

        t_tts_start = time.perf_counter()
        first_chunk = True

        for audio_chunk, tele in self.tts_engine.synthesize_stream(spoken_text, stop_event=cancellation):
            if cancellation.is_set() or self.playback_manager.current_generation_id != gen_id:
                metrics.interrupted = True
                break

            if first_chunk:
                metrics.tts_ttfa_ms = tele.get("time_to_first_audio_ms", (time.perf_counter() - t_tts_start) * 1000.0)
                metrics.e2e_voice_latency_ms = metrics.asr_latency_ms + metrics.agent_total_latency_ms + metrics.tts_ttfa_ms
                first_chunk = False
                self.set_state(VoiceState.SPEAKING)

            self.playback_manager.enqueue(audio_chunk, samplerate=self.tts_engine.sample_rate, generation_id=gen_id)

        metrics.tts_total_latency_ms = (time.perf_counter() - t_tts_start) * 1000.0
        self.diagnostics.record_turn(metrics)

        # Wait until audio queue drains or interruption occurs
        while self.playback_manager.is_playing:
            if cancellation.is_set() or self.playback_manager.current_generation_id != gen_id:
                break
            time.sleep(0.03)

        # Only transition back to LISTENING if the turn completed naturally and was NOT interrupted
        if not cancellation.is_set() and self.state == VoiceState.SPEAKING:
            self.capture_stream.suppress_input(350)
            self.vad.reset()
            self.set_state(VoiceState.LISTENING if self._hands_free else VoiceState.IDLE)

    def process_direct_utterance(self, audio: np.ndarray) -> tuple[str, str, VoiceTurnMetrics]:
        """Synchronous entry point for testing: takes audio array, returns (written, spoken, metrics)."""
        turn_id = f"test_{uuid.uuid4().hex[:6]}"
        self.interruption.start_turn(turn_id)
        metrics = VoiceTurnMetrics(turn_id=turn_id, user_speech_duration_s=len(audio) / 16000.0)

        # ASR
        t_asr_start = time.perf_counter()
        res, tele = self.asr_engine.transcribe(audio, sample_rate=16000, utterance_id=turn_id)
        metrics.asr_latency_ms = tele.get("latency_ms", (time.perf_counter() - t_asr_start) * 1000.0)
        user_text = res.normalized_text

        # Contextual acknowledgment check
        cleaned_ack = user_text.lower().strip().rstrip(".!?,")
        if cleaned_ack in ("oke", "ok", "oke deh", "baik", "siap", "ya", "iya", "lanjutkan", "silakan"):
            pending_action = getattr(self.working_context, "pending_action", None)
            if pending_action and isinstance(pending_action, dict):
                ticker = pending_action.get("ticker", "")
                self.working_context.pending_action = None
                user_text = pending_action.get("resume_query") or f"Lanjutkan analisis saham {ticker}."
            else:
                metrics.e2e_voice_latency_ms = metrics.asr_latency_ms
                self.diagnostics.record_turn(metrics)
                return "Baik.", "Baik.", metrics

        # Greeting check in direct utterance
        greeting_reply = self._handle_greeting_utterance(user_text)
        if greeting_reply:
            metrics.e2e_voice_latency_ms = metrics.asr_latency_ms
            self.diagnostics.record_turn(metrics)
            return greeting_reply, greeting_reply, metrics

        # Voice preset commands in direct utterance
        voice_cmd_reply = self._handle_voice_preset_commands(user_text)
        if voice_cmd_reply:
            metrics.e2e_voice_latency_ms = metrics.asr_latency_ms
            self.diagnostics.record_turn(metrics)
            return voice_cmd_reply, voice_cmd_reply, metrics

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

    def _handle_greeting_utterance(self, transcript: str) -> str | None:
        """Fast-path handler for conversational greetings without triggering financial tools."""
        cleaned = transcript.lower().strip().rstrip(".!?,")
        greetings = {
            "halo", "hai", "halo bagusmax", "hai bagusmax", "halo halo",
            "selamat pagi", "selamat pagi bagusmax", "selamat siang", "selamat siang bagusmax",
            "selamat sore", "selamat sore bagusmax", "selamat malam", "selamat malam bagusmax",
            "pagi bagusmax", "siang bagusmax", "sore bagusmax", "malam bagusmax",
        }
        if cleaned in greetings:
            return "Halo. Saya di sini. Ada yang ingin kita diskusikan tentang emiten, pasar modal, atau kondisi sistem?"
        return None

    def _handle_voice_preset_commands(self, transcript: str) -> str | None:
        """Handles spoken and slash commands for voice preset switching, timbre introspection, and devices."""
        low = transcript.lower().strip().rstrip(".!?,")
        if not low:
            return None

        # 1. Check timbre / female voice queries with honest explanation
        timbre_queries = (
            "kenapa suara kamu masih perempuan",
            "kenapa suara kamu perempuan",
            "kenapa suaramu perempuan",
            "kenapa suara kamu masih cewek",
            "kenapa suaramu tinggi",
            "kenapa suaranya tinggi",
            "kenapa suaranya wanita",
            "apakah suaramu perempuan",
            "mengapa suara kamu perempuan",
            "kenapa suaramu seperti perempuan",
            "kenapa suara kamu cewek",
        )
        if any(q in low for q in timbre_queries):
            status = self.tts_engine.get_voice_status() if hasattr(self.tts_engine, "get_voice_status") else {}
            curr_p = status.get("active_preset", getattr(self.tts_engine, "preset", "BAGUSMAX_GENTLE_ID"))
            return (
                f"Model dasar TTS lokal saya saat ini menggunakan model open-source bahasa Indonesia berkarakter wanita (id_ID-news_tts-medium). "
                f"Untuk mendekati kepribadian Bagusmax yang tenang dan santun seperti Baymax, sistem menerapkan pemrosesan audio berupa penambahan kehangatan vokal dan resonansi pendamping robotik. "
                f"Preset yang aktif saat ini adalah {curr_p}."
            )

        # 2. Check status inquiries: "suara yang aktif sekarang apa?", "/voice status"
        if low in ("/voice status", "voice status") or any(k in low for k in (
            "suara yang aktif sekarang apa", "status suara sekarang apa", "suara apa yang aktif",
            "suara aktif sekarang apa", "preset suara apa", "status suara"
        )):
            status = self.tts_engine.get_voice_status() if hasattr(self.tts_engine, "get_voice_status") else {}
            preset = status.get("active_preset", getattr(self.tts_engine, "preset", "BAGUSMAX_GENTLE_ID"))
            sr = status.get("sample_rate", getattr(self.tts_engine, "sample_rate", 22050))
            return f"Status suara Bagusmax: Preset aktif adalah {preset}, sample rate {sr} Hz. Semua pemrosesan audio dilakukan di memori tanpa penulisan ke disk."

        # 3. Check audio devices: "/voice devices"
        if low in ("/voice devices", "voice devices") or any(k in low for k in ("perangkat audio apa", "daftar perangkat audio", "audio devices", "perangkat audio")):
            from openbagus.voice.audio_devices import AudioDeviceManager
            in_dev = AudioDeviceManager.get_default_input_device()
            out_dev = AudioDeviceManager.get_default_output_device()
            in_name = in_dev.name if in_dev else "Mikrofon default"
            out_name = out_dev.name if out_dev else "Speaker default"
            return f"Perangkat audio yang aktif: Mikrofon '{in_name}', Speaker '{out_name}'. Penyesuaian sample-rate otomatis aktif."

        # 4. Check voice test: "/voice test"
        if low in ("/voice test", "voice test") or any(k in low for k in ("tes suara", "uji suara", "test suara", "cek suara")):
            return "Halo, saya Bagusmax. Pemeriksaan audio mikrofon dan speaker sistem lokal berjalan normal. Ada yang bisa saya bantu?"

        # 5. Check preset change commands:
        # e.g. "Bagusmax, gunakan suara calm", "Bagusmax, ganti ke suara natural", "Bagusmax, gunakan suara soft", "/voice preset calm"
        m = re.search(r"(?:/voice\s+preset\s+|suara\s+preset\s+|(?:gunakan|ganti\s+ke|pakai|set)\s+suara\s+)(calm|natural|soft|gentle|bagusmax|bagusmax_calm|bagusmax_soft|bagusmax_gentle_id)", low)
        if m:
            raw_target = m.group(1).upper()
            if raw_target in ("GENTLE", "BAGUSMAX", "BAGUSMAX_GENTLE"):
                target = "BAGUSMAX_GENTLE_ID"
            elif raw_target == "CALM":
                target = "BAGUSMAX_CALM"
            elif raw_target == "SOFT":
                target = "BAGUSMAX_SOFT"
            else:
                target = raw_target

            from openbagus.ai.tools.system_tools import SetVoicePresetTool
            tool = SetVoicePresetTool()
            try:
                res, _ = tool.run(preset=target)
                applied = res.get("applied_preset", target)
                if hasattr(self.tts_engine, "set_preset"):
                    self.tts_engine.set_preset(applied)
                return f"Baik, preset suara Bagusmax berhasil diubah ke {applied}."
            except Exception as e:
                return f"Maaf, gagal mengubah preset suara: {e}"

        return None
