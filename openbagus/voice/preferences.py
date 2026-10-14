"""Persistent user preferences and auto-configuration for OpenBagus Voice Subsystem.

Stores microphone and speaker selection, hands-free VAD settings, voice preset (BAGUSMAX_CALM_ID),
audio storage prohibition (strictly zero-disk retention), and auto-start preferences.
Follows atomic write and graceful fallback on corruption.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openbagus.voice.audio_devices import AudioDeviceManager

logger = logging.getLogger(__name__)

DEFAULT_VOICE_CONFIG_PATH = Path("data/local_ai/voice_preferences.json")


@dataclass
class VoicePreferences:
    version: int = 1
    voice_enabled: bool = True
    hands_free: bool = True
    microphone_device_id: int | None = None
    speaker_device_id: int | None = None
    voice_preset: str = "BAGUSMAX_CALM_ID"  # BAGUSMAX_CALM_ID, STANDARD, FAST
    speed: float = 1.0
    volume: float = 1.0
    audio_storage: str = "disabled"  # strictly disabled: zero audio saved to disk
    response_mode: str = "audio_first"  # audio_first (instant voice response), text_and_audio
    barge_in_enabled: bool = True
    echo_cancellation_guard_ms: int = 250
    default_mode: str = "FAST"
    auto_start_on_cli: bool = True

    def sanitize(self) -> VoicePreferences:
        """Sanitizes preferences to valid ranges and safe configurations."""
        self.speed = max(0.5, min(2.0, float(self.speed)))
        self.volume = max(0.0, min(1.0, float(self.volume)))
        if self.voice_preset not in ("BAGUSMAX_CALM_ID", "STANDARD", "FAST"):
            self.voice_preset = "BAGUSMAX_CALM_ID"
        if self.audio_storage != "disabled":
            # Hard enforcement: never allow audio storage on disk
            self.audio_storage = "disabled"
        if self.response_mode not in ("audio_first", "text_and_audio"):
            self.response_mode = "audio_first"
        self.echo_cancellation_guard_ms = max(50, min(1000, int(self.echo_cancellation_guard_ms)))
        if self.default_mode not in ("FAST", "DEEP_REASONING"):
            self.default_mode = "FAST"
        return self

    def resolve_devices(self) -> tuple[int | None, int | None]:
        """Resolves input and output device IDs, falling back to OS defaults if invalid."""
        in_id = self.microphone_device_id
        out_id = self.speaker_device_id

        # Validate input device
        in_devs = {d.id: d for d in AudioDeviceManager.list_input_devices()}
        if in_id is None or in_id not in in_devs:
            def_in = AudioDeviceManager.get_default_input_device()
            in_id = def_in.id if def_in else None

        # Validate output device
        out_devs = {d.id: d for d in AudioDeviceManager.list_output_devices()}
        if out_id is None or out_id not in out_devs:
            def_out = AudioDeviceManager.get_default_output_device()
            out_id = def_out.id if def_out else None

        return in_id, out_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoicePreferences:
        obj = cls()
        if not isinstance(data, dict):
            return obj
        for k, v in data.items():
            if hasattr(obj, k):
                try:
                    field_type = type(getattr(obj, k))
                    if field_type == bool:
                        setattr(obj, k, bool(v))
                    elif field_type == int:
                        setattr(obj, k, int(v))
                    elif field_type == float:
                        setattr(obj, k, float(v))
                    elif field_type == str:
                        setattr(obj, k, str(v))
                    else:
                        setattr(obj, k, v)
                except (ValueError, TypeError):
                    pass
        return obj.sanitize()


def _get_target_path(config_path: Path | str | None = None) -> Path:
    if config_path:
        return Path(config_path)
    # Check local repo directory first
    repo_file = DEFAULT_VOICE_CONFIG_PATH
    if repo_file.parent.exists():
        return repo_file
    # Fallback to local appdata directory
    local_app_data = Path(os.environ.get("LOCALAPPDATA", "C:/Users/bagus/AppData/Local")) / "OpenBagus"
    return local_app_data / "voice_preferences.json"


def load_voice_preferences(config_path: Path | str | None = None) -> VoicePreferences:
    """Loads voice preferences from disk with automatic fallback on missing or corrupt file."""
    path = _get_target_path(config_path)
    if not path.exists():
        return VoicePreferences()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return VoicePreferences.from_dict(data)
    except Exception as e:
        logger.warning("Failed to parse voice preferences from %s: %s (using defaults)", path, e)
        return VoicePreferences()


def save_voice_preferences(
    prefs: VoicePreferences,
    config_path: Path | str | None = None,
) -> bool:
    """Atomically saves voice preferences to disk."""
    path = _get_target_path(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        prefs.sanitize()
        data = json.dumps(prefs.to_dict(), indent=2, ensure_ascii=False)

        with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False, encoding="utf-8") as tf:
            tf.write(data)
            temp_name = tf.name

        os.replace(temp_name, str(path))
        logger.info("Voice preferences saved successfully to %s", path)
        return True
    except Exception as e:
        logger.error("Failed to save voice preferences to %s: %s", path, e)
        return False
