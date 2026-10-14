"""Real-time voice profile processor providing gentle styling, warmth, smoothing, and peak limiting.

Designed for Bagusmax's film-inspired gentle robot delivery without introducing heavy vocoder
distortion, phase artifacts, or audio delay.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/voices/bagusmax_calm_id.json")


@dataclass
class VoiceStyleParameters:
    length_scale: float = 1.08
    noise_scale: float = 0.55
    noise_w_scale: float = 0.70
    pitch_shift_semitones: float = 0.0
    warmth_gain_db: float = 0.8
    smoothing_enabled: bool = True
    peak_limiting: bool = True
    volume: float = 1.0


class VoiceProfileProcessor:
    """Applies lightweight real-time acoustic styling to synthesized voice chunks."""

    def __init__(
        self,
        config_path: Path | str | None = None,
        preset: str = "BAGUSMAX_CALM",
    ) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.preset_name = preset
        self.params = VoiceStyleParameters()
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.debug("Voice config not found at %s; using default parameters", self.config_path)
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            presets = data.get("presets", {})
            if self.preset_name in presets:
                p = presets[self.preset_name]
                self.params.length_scale = float(p.get("length_scale", 1.08))
                self.params.noise_scale = float(p.get("noise_scale", 0.55))
                self.params.noise_w_scale = float(p.get("noise_w_scale", 0.70))
                self.params.pitch_shift_semitones = float(p.get("pitch_shift_semitones", 0.0))
                self.params.warmth_gain_db = float(p.get("warmth_gain_db", 0.8))
                self.params.smoothing_enabled = bool(p.get("smoothing_enabled", True))
            else:
                self.params.length_scale = float(data.get("length_scale", 1.08))
                self.params.noise_scale = float(data.get("noise_scale", 0.55))
                self.params.noise_w_scale = float(data.get("noise_w_scale", 0.70))
                self.params.pitch_shift_semitones = float(data.get("pitch_shift_semitones", 0.0))
                self.params.warmth_gain_db = float(data.get("warmth_gain_db", 0.8))
                self.params.smoothing_enabled = bool(data.get("smoothing_enabled", True))

            self.params.peak_limiting = bool(data.get("peak_limiting", True))
            self.params.volume = float(data.get("volume", 1.0))
        except Exception as e:
            logger.warning("Error reading voice profile config from %s: %s", self.config_path, e)

    def set_preset(self, preset_name: str) -> bool:
        """Switches active voice style preset."""
        self.preset_name = preset_name
        self._load_config()
        return True

    def process(self, audio: np.ndarray, sample_rate: int = 22050) -> np.ndarray:
        """Processes audio array in-place or via lightweight vectorized NumPy operations."""
        if audio is None or len(audio) == 0:
            return np.empty(0, dtype=np.float32)

        out = audio.astype(np.float32)

        # 1. Conservative pitch shift via linear resampling if configured
        if abs(self.params.pitch_shift_semitones) >= 0.1:
            factor = 2.0 ** (self.params.pitch_shift_semitones / 12.0)
            new_len = int(len(out) / factor)
            if new_len > 0:
                out = np.interp(
                    np.linspace(0, len(out), new_len, endpoint=False),
                    np.arange(len(out)),
                    out,
                ).astype(np.float32)

        # 2. High-frequency smoothing filter (gentle 3-tap zero-phase smoother)
        # Eliminates harsh digital sibilance above ~7 kHz for soft robot warmth
        if self.params.smoothing_enabled and len(out) > 4:
            alpha = 0.06
            smoothed = np.empty_like(out)
            smoothed[0] = out[0]
            smoothed[-1] = out[-1]
            smoothed[1:-1] = alpha * out[:-2] + (1.0 - 2.0 * alpha) * out[1:-1] + alpha * out[2:]
            out = smoothed

        # 3. Low-mid warmth (gentle bass presence)
        if self.params.warmth_gain_db > 0.1 and len(out) > 4:
            # Subtle low-frequency enhancement by adding slight low-pass component
            warmth_factor = (10.0 ** (self.params.warmth_gain_db / 20.0)) - 1.0
            lp = np.convolve(out, [0.25, 0.5, 0.25], mode="same")
            out = out + (warmth_factor * 0.4) * lp

        # 4. Soft peak limiter to prevent digital clipping
        if self.params.peak_limiting and len(out) > 0:
            peak = float(np.max(np.abs(out)))
            if peak > 0.95:
                # Smooth tanh compression for samples exceeding 0.95
                out = np.tanh(out * 0.95) * 0.98

        if self.params.volume != 1.0:
            out = out * self.params.volume

        return out.astype(np.float32)
