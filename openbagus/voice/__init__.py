"""OpenBagus Local Native Voice Conversation Subsystem."""

import os
import sys
from pathlib import Path

if os.name == "nt":
    _base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if _base.exists():
        for _bin_dir in _base.glob("*/bin"):
            if _bin_dir.is_dir():
                try:
                    os.add_dll_directory(str(_bin_dir))
                except Exception:
                    pass
                _p_str = str(_bin_dir)
                if _p_str not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = _p_str + os.pathsep + os.environ.get("PATH", "")

from openbagus.voice.audio_capture import AudioCaptureStream
from openbagus.voice.audio_devices import AudioDeviceInfo, AudioDeviceManager
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.asr_engine import LocalASREngine
from openbagus.voice.asr_normalizer import ASRFinancialNormalizer, NormalizedASRResult
from openbagus.voice.diagnostics import VoiceDiagnostics, VoiceTurnMetrics
from openbagus.voice.gpu_scheduler import GPUScheduler, GPUStatus
from openbagus.voice.interruption import InterruptionCoordinator
from openbagus.voice.mode_controller import VoiceModeController
from openbagus.voice.preferences import VoicePreferences, load_voice_preferences, save_voice_preferences
from openbagus.voice.privacy import PrivacyGuard, PrivacyStatus
from openbagus.voice.speech_normalizer import SpeechTextNormalizer
from openbagus.voice.tts_engine import LocalTTSEngine
from openbagus.voice.turn_controller import VoiceState, VoiceTurnController
from openbagus.voice.vad import VoiceActivityDetector
from openbagus.voice.voice_session import VoiceSession

__all__ = [
    "AudioCaptureStream",
    "AudioDeviceInfo",
    "AudioDeviceManager",
    "AudioPlaybackManager",
    "LocalASREngine",
    "ASRFinancialNormalizer",
    "NormalizedASRResult",
    "VoiceDiagnostics",
    "VoiceTurnMetrics",
    "GPUScheduler",
    "GPUStatus",
    "InterruptionCoordinator",
    "VoiceModeController",
    "VoicePreferences",
    "load_voice_preferences",
    "save_voice_preferences",
    "PrivacyGuard",
    "PrivacyStatus",
    "SpeechTextNormalizer",
    "LocalTTSEngine",
    "VoiceState",
    "VoiceTurnController",
    "VoiceActivityDetector",
    "VoiceSession",
]
