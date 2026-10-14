"""Typed event bridge and schema for conversational AI to 3D companion animation."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class ConversationEventType(str, enum.Enum):
    # Microphone / VAD
    MIC_ENABLED = "MIC_ENABLED"
    MIC_DISABLED = "MIC_DISABLED"
    USER_SPEECH_STARTED = "USER_SPEECH_STARTED"
    USER_SPEECH_LEVEL = "USER_SPEECH_LEVEL"
    USER_SPEECH_ENDED = "USER_SPEECH_ENDED"

    # ASR
    ASR_STARTED = "ASR_STARTED"
    ASR_FINALIZED = "ASR_FINALIZED"
    ASR_FAILED = "ASR_FAILED"

    # Mode
    MODE_SELECTION_REQUESTED = "MODE_SELECTION_REQUESTED"
    MODE_CONFIRMED = "MODE_CONFIRMED"

    # Agent & Tool
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_THINKING = "AGENT_THINKING"
    TOOL_EXECUTION_STARTED = "TOOL_EXECUTION_STARTED"
    TOOL_EXECUTION_FINISHED = "TOOL_EXECUTION_FINISHED"

    # LLM
    LLM_GENERATION_STARTED = "LLM_GENERATION_STARTED"
    LLM_FIRST_OUTPUT = "LLM_FIRST_OUTPUT"
    LLM_GENERATION_COMPLETED = "LLM_GENERATION_COMPLETED"

    # TTS & Playback
    TTS_GENERATION_STARTED = "TTS_GENERATION_STARTED"
    TTS_AUDIO_QUEUED = "TTS_AUDIO_QUEUED"
    TTS_PLAYBACK_STARTED = "TTS_PLAYBACK_STARTED"
    TTS_PLAYBACK_LEVEL = "TTS_PLAYBACK_LEVEL"
    TTS_PLAYBACK_FINISHED = "TTS_PLAYBACK_FINISHED"

    # Interruption & Cancellation
    USER_INTERRUPTED = "USER_INTERRUPTED"
    TURN_CANCELLED = "TURN_CANCELLED"

    # Lifecycle & System
    AGENT_ERROR = "AGENT_ERROR"
    SYSTEM_IDLE = "SYSTEM_IDLE"


class ConversationState(str, enum.Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    USER_SPEAKING = "USER_SPEAKING"
    TRANSCRIBING = "TRANSCRIBING"
    MODE_SELECTION = "MODE_SELECTION"
    PLANNING = "PLANNING"
    TOOL_WORKING = "TOOL_WORKING"
    GENERATING = "GENERATING"
    AUDIO_READY = "AUDIO_READY"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


class AnimState(str, enum.Enum):
    IDLE_BREATHING = "IDLE_BREATHING"
    ATTENTIVE = "ATTENTIVE"
    ACTIVE_LISTENING = "ACTIVE_LISTENING"
    ACKNOWLEDGING = "ACKNOWLEDGING"
    THINKING = "THINKING"
    DEEP_THINKING = "DEEP_THINKING"
    TOOL_GESTURE = "TOOL_GESTURE"
    SPEECH_GESTURE = "SPEECH_GESTURE"
    HAPPY_REACTION = "HAPPY_REACTION"
    CONFUSED_REACTION = "CONFUSED_REACTION"
    INTERRUPTION_RECOVERY = "INTERRUPTION_RECOVERY"
    ERROR_RECOVERY = "ERROR_RECOVERY"

    # Compatibility aliases for legacy controller calls
    IDLE = "IDLE_BREATHING"
    LISTENING = "ACTIVE_LISTENING"
    SPEAKING = "SPEECH_GESTURE"
    TOOL_WORKING = "TOOL_GESTURE"
    HAPPY = "HAPPY_REACTION"
    CONFUSED = "CONFUSED_REACTION"
    SURPRISED = "INTERRUPTION_RECOVERY"
    ERROR = "ERROR_RECOVERY"
    SLEEPING = "IDLE_BREATHING"
    HEARD_USER = "ACKNOWLEDGING"
    WARNING = "CONFUSED_REACTION"
    SUCCESS = "HAPPY_REACTION"


class ReasoningMode(str, enum.Enum):
    FAST = "FAST"
    DEEP_REASONING = "DEEP_REASONING"


# Priority levels for animation states (higher number = higher priority)
STATE_PRIORITIES: dict[AnimState, int] = {
    AnimState.INTERRUPTION_RECOVERY: 100,
    AnimState.ERROR_RECOVERY: 90,
    AnimState.ACTIVE_LISTENING: 80,
    AnimState.ATTENTIVE: 75,
    AnimState.ACKNOWLEDGING: 70,
    AnimState.SPEECH_GESTURE: 60,
    AnimState.TOOL_GESTURE: 50,
    AnimState.DEEP_THINKING: 40,
    AnimState.THINKING: 30,
    AnimState.HAPPY_REACTION: 25,
    AnimState.CONFUSED_REACTION: 25,
    AnimState.IDLE_BREATHING: 10,
}


@dataclass
class CompanionEvent:
    event_type: str
    turn_id: str
    sequence_number: int
    monotonic_timestamp: float = field(default_factory=time.monotonic)
    session_id: str = "default_session"
    source: str = "voice_turn_controller"
    schema_version: str = "2.0"
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.event_type,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "sequence_number": self.sequence_number,
            "monotonic_timestamp": self.monotonic_timestamp,
            "source": self.source,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanionEvent:
        return cls(
            event_type=data.get("type", data.get("event_type", ConversationEventType.SYSTEM_IDLE.value)),
            turn_id=data.get("turn_id", ""),
            sequence_number=data.get("sequence_number", 0),
            monotonic_timestamp=data.get("monotonic_timestamp", time.monotonic()),
            session_id=data.get("session_id", "default_session"),
            source=data.get("source", "unknown"),
            schema_version=data.get("schema_version", "2.0"),
            payload=data.get("payload", {}),
        )


class ConversationAnimationBridge:
    """Stateful bridge managing turn lifecycles, stale event rejection, and animation resolution."""

    def __init__(self) -> None:
        self.reasoning_mode: ReasoningMode = ReasoningMode.FAST
        self.conversation_state: ConversationState = ConversationState.IDLE
        self.animation_state: AnimState = AnimState.IDLE_BREATHING
        self.current_turn_id: str = ""
        self.cancelled_turns: set[str] = set()
        self.last_sequence_number: int = -1
        self.audio_amplitude: float = 0.0

    def start_new_turn(self, turn_id: str) -> None:
        """Mark a new turn as active and clear old sequence counter."""
        self.current_turn_id = turn_id
        self.last_sequence_number = -1

    def cancel_turn(self, turn_id: str) -> None:
        """Record turn as cancelled so delayed asynchronous events are rejected."""
        self.cancelled_turns.add(turn_id)
        if self.current_turn_id == turn_id:
            self.conversation_state = ConversationState.INTERRUPTED
            self.animation_state = AnimState.INTERRUPTION_RECOVERY
            self.audio_amplitude = 0.0

    def is_stale_event(self, event: CompanionEvent) -> bool:
        """Check whether an event belongs to an obsolete or cancelled turn."""
        if not event.turn_id:
            return False
        if event.turn_id in self.cancelled_turns:
            return True
        # If this event belongs to a different turn and is not a new turn start event
        if self.current_turn_id and event.turn_id != self.current_turn_id:
            if event.event_type in (
                ConversationEventType.USER_SPEECH_STARTED.value,
                ConversationEventType.ASR_STARTED.value,
            ):
                return False  # Allowed to initiate turn switch
            return True
        if event.sequence_number < self.last_sequence_number:
            return True
        return False

    def process_event(self, event: CompanionEvent) -> tuple[ConversationState, AnimState, bool]:
        """Process an incoming event and return (new_conv_state, new_anim_state, changed)."""
        if self.is_stale_event(event):
            return self.conversation_state, self.animation_state, False

        self.last_sequence_number = max(self.last_sequence_number, event.sequence_number)
        ev_type = event.event_type
        old_anim = self.animation_state

        # Update reasoning mode if specified
        if ev_type == ConversationEventType.MODE_CONFIRMED.value:
            m = str(event.payload.get("mode", "FAST")).upper()
            self.reasoning_mode = (
                ReasoningMode.DEEP_REASONING if "DEEP" in m else ReasoningMode.FAST
            )

        # Map Event -> ConversationState
        if ev_type in (ConversationEventType.MIC_ENABLED.value, ConversationEventType.SYSTEM_IDLE.value):
            self.conversation_state = ConversationState.IDLE
        elif ev_type == ConversationEventType.USER_SPEECH_STARTED.value:
            if event.turn_id:
                self.current_turn_id = event.turn_id
            self.conversation_state = ConversationState.USER_SPEAKING
        elif ev_type == ConversationEventType.USER_SPEECH_ENDED.value:
            self.conversation_state = ConversationState.TRANSCRIBING
        elif ev_type == ConversationEventType.ASR_STARTED.value:
            self.conversation_state = ConversationState.TRANSCRIBING
        elif ev_type == ConversationEventType.ASR_FINALIZED.value:
            self.conversation_state = ConversationState.PLANNING
        elif ev_type in (ConversationEventType.AGENT_STARTED.value, ConversationEventType.AGENT_THINKING.value):
            self.conversation_state = ConversationState.PLANNING
        elif ev_type == ConversationEventType.TOOL_EXECUTION_STARTED.value:
            self.conversation_state = ConversationState.TOOL_WORKING
        elif ev_type == ConversationEventType.TOOL_EXECUTION_FINISHED.value:
            self.conversation_state = ConversationState.GENERATING
        elif ev_type == ConversationEventType.LLM_GENERATION_STARTED.value:
            self.conversation_state = ConversationState.GENERATING
        elif ev_type in (ConversationEventType.TTS_GENERATION_STARTED.value, ConversationEventType.TTS_AUDIO_QUEUED.value):
            self.conversation_state = ConversationState.AUDIO_READY
        elif ev_type == ConversationEventType.TTS_PLAYBACK_STARTED.value:
            self.conversation_state = ConversationState.SPEAKING
        elif ev_type == ConversationEventType.TTS_PLAYBACK_LEVEL.value:
            self.audio_amplitude = float(event.payload.get("amplitude", 0.0))
            if self.conversation_state != ConversationState.SPEAKING:
                self.conversation_state = ConversationState.SPEAKING
        elif ev_type == ConversationEventType.TTS_PLAYBACK_FINISHED.value:
            self.audio_amplitude = 0.0
            self.conversation_state = ConversationState.IDLE
        elif ev_type in (ConversationEventType.USER_INTERRUPTED.value, ConversationEventType.TURN_CANCELLED.value):
            if event.turn_id:
                self.cancel_turn(event.turn_id)
            self.conversation_state = ConversationState.INTERRUPTED
            self.audio_amplitude = 0.0
        elif ev_type == ConversationEventType.AGENT_ERROR.value:
            self.conversation_state = ConversationState.ERROR

        # Derive AnimationState from (ConversationState, ReasoningMode)
        self.animation_state = self.resolve_animation_state()
        return self.conversation_state, self.animation_state, (self.animation_state != old_anim)

    def resolve_animation_state(self) -> AnimState:
        """Deterministically resolve animation state from current conversation state & mode."""
        cs = self.conversation_state
        mode = self.reasoning_mode

        if cs == ConversationState.INTERRUPTED:
            return AnimState.INTERRUPTION_RECOVERY
        elif cs == ConversationState.ERROR:
            return AnimState.ERROR_RECOVERY
        elif cs == ConversationState.USER_SPEAKING:
            return AnimState.ACTIVE_LISTENING
        elif cs == ConversationState.LISTENING:
            return AnimState.ATTENTIVE
        elif cs == ConversationState.TRANSCRIBING:
            return AnimState.ACKNOWLEDGING
        elif cs == ConversationState.TOOL_WORKING:
            return AnimState.TOOL_GESTURE
        elif cs in (ConversationState.PLANNING, ConversationState.GENERATING):
            return AnimState.DEEP_THINKING if mode == ReasoningMode.DEEP_REASONING else AnimState.THINKING
        elif cs == ConversationState.AUDIO_READY:
            return AnimState.DEEP_THINKING if mode == ReasoningMode.DEEP_REASONING else AnimState.THINKING
        elif cs == ConversationState.SPEAKING:
            return AnimState.SPEECH_GESTURE
        else:
            return AnimState.IDLE_BREATHING
