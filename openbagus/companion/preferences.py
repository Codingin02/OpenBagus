"""Persistent user preferences for BAGUSMAX 3D Companion.

Stores window position, dimensions, character scale, 3D rotation (yaw/pitch),
and interactivity modes in data/local_ai/bagusmax_preferences.json.
Provides thread-safe atomic writes and schema validation with fallback.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("data/local_ai/bagusmax_preferences.json")


@dataclass
class CompanionPreferences:
    version: int = 1
    enabled: bool = True
    monitor_index: int = 0
    window_position_x: int = -1
    window_position_y: int = -1
    window_width: int = 480
    window_height: int = 560
    character_scale: float = 1.0
    yaw_degrees: float = 8.0
    pitch_degrees: float = 0.0
    animation_enabled: bool = True
    interactive_mode: bool = True
    always_on_top: bool = True
    placement_policy: str = "CLAMP_TO_VISIBLE_WORKAREA"
    active_fps: int = 60
    idle_fps: int = 30

    def clamp(self) -> CompanionPreferences:
        """Sanitize and clamp values to safe limits."""
        self.character_scale = max(0.5, min(2.0, float(self.character_scale)))
        self.yaw_degrees = float(self.yaw_degrees) % 360.0
        self.pitch_degrees = max(-65.0, min(65.0, float(self.pitch_degrees)))
        self.window_width = max(240, min(1200, int(self.window_width)))
        self.window_height = max(280, min(1400, int(self.window_height)))
        self.monitor_index = max(0, int(self.monitor_index))
        if self.placement_policy not in ("CLAMP_TO_VISIBLE_WORKAREA", "FREE_POSITIONING"):
            self.placement_policy = "CLAMP_TO_VISIBLE_WORKAREA"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanionPreferences:
        obj = cls()
        if not isinstance(data, dict):
            return obj
        for k, v in data.items():
            if hasattr(obj, k):
                try:
                    field_type = type(getattr(obj, k))
                    setattr(obj, k, field_type(v))
                except (ValueError, TypeError):
                    pass
        return obj.clamp()


def _get_target_path(config_path: Path | str | None = None) -> Path:
    if config_path:
        return Path(config_path)
    import sys
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OpenBagus" / "bagusmax_preferences.json"
    try:
        from openbagus.core.env import get_repo_root
        repo_file = get_repo_root() / "data/local_ai/bagusmax_preferences.json"
        if repo_file.parent.exists():
            return repo_file
    except Exception:
        pass
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OpenBagus"
    return local_app_data / "bagusmax_preferences.json"


def load_preferences(config_path: Path | str | None = None) -> CompanionPreferences:
    """Load preferences from disk with automatic fallback on corruption."""
    path = _get_target_path(config_path)
    if not path.exists():
        return CompanionPreferences()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return CompanionPreferences.from_dict(data)
    except Exception as e:
        logger.warning("Failed to parse companion preferences from %s: %s (using defaults)", path, e)
        return CompanionPreferences()


def save_preferences(
    prefs: CompanionPreferences,
    config_path: Path | str | None = None,
) -> bool:
    """Atomically save preferences to disk."""
    path = _get_target_path(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        prefs.clamp()
        data = json.dumps(prefs.to_dict(), indent=2, ensure_ascii=False)

        # Atomic write via temporary file in same directory
        with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False, encoding="utf-8") as tf:
            tf.write(data)
            temp_name = tf.name

        os.replace(temp_name, str(path))
        return True
    except Exception as e:
        logger.error("Failed to save companion preferences to %s: %s", path, e)
        return False


def reset_preferences(config_path: Path | str | None = None) -> CompanionPreferences:
    """Reset preferences to factory defaults and write to disk."""
    default_prefs = CompanionPreferences()
    save_preferences(default_prefs, config_path)
    return default_prefs
