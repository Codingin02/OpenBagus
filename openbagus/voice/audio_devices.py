"""Audio device enumeration, default detection, and capability inspection for Windows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
except ImportError:
    sd = None


@dataclass
class AudioDeviceInfo:
    id: int
    name: str
    kind: str  # "input" | "output"
    hostapi: str
    max_channels: int
    default_samplerate: float
    is_default: bool = False

    @property
    def index(self) -> int:
        return self.id

    @property
    def host_api(self) -> str:
        return self.hostapi

    @property
    def max_input_channels(self) -> int:
        return self.max_channels if self.kind == "input" else 0

    @property
    def max_output_channels(self) -> int:
        return self.max_channels if self.kind == "output" else 0

    @property
    def default_sample_rate(self) -> float:
        return self.default_samplerate

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "hostapi": self.hostapi,
            "max_channels": self.max_channels,
            "default_samplerate": self.default_samplerate,
            "is_default": self.is_default,
        }


class AudioDeviceManager:
    """Manages audio device enumeration, selection, and health checks on Windows."""

    @classmethod
    def is_available(cls) -> bool:
        return sd is not None

    @classmethod
    def list_input_devices(cls) -> list[AudioDeviceInfo]:
        """Lists all physical and virtual microphone input devices."""
        if not cls.is_available():
            return []
        devices: list[AudioDeviceInfo] = []
        try:
            raw_devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else -1

            for idx, dev in enumerate(raw_devices):
                if dev.get("max_input_channels", 0) > 0:
                    api_idx = dev.get("hostapi", 0)
                    api_name = hostapis[api_idx]["name"] if api_idx < len(hostapis) else "Unknown"
                    devices.append(AudioDeviceInfo(
                        id=idx,
                        name=str(dev.get("name", f"Microphone {idx}")),
                        kind="input",
                        hostapi=api_name,
                        max_channels=int(dev.get("max_input_channels", 1)),
                        default_samplerate=float(dev.get("default_samplerate", 16000.0)),
                        is_default=(idx == default_in),
                    ))
        except Exception as e:
            logger.warning("Error querying audio input devices: %s", e)
        return devices

    @classmethod
    def list_output_devices(cls) -> list[AudioDeviceInfo]:
        """Lists all physical and virtual speakers/headphones output devices."""
        if not cls.is_available():
            return []
        devices: list[AudioDeviceInfo] = []
        try:
            raw_devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            default_out = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else -1

            for idx, dev in enumerate(raw_devices):
                if dev.get("max_output_channels", 0) > 0:
                    api_idx = dev.get("hostapi", 0)
                    api_name = hostapis[api_idx]["name"] if api_idx < len(hostapis) else "Unknown"
                    devices.append(AudioDeviceInfo(
                        id=idx,
                        name=str(dev.get("name", f"Speaker {idx}")),
                        kind="output",
                        hostapi=api_name,
                        max_channels=int(dev.get("max_output_channels", 2)),
                        default_samplerate=float(dev.get("default_samplerate", 44100.0)),
                        is_default=(idx == default_out),
                    ))
        except Exception as e:
            logger.warning("Error querying audio output devices: %s", e)
        return devices

    @classmethod
    def get_default_input_device(cls) -> AudioDeviceInfo | None:
        inputs = cls.list_input_devices()
        for d in inputs:
            if d.is_default:
                return d
        # Fallback to prefer WASAPI or DirectSound default
        for d in inputs:
            if "WASAPI" in d.hostapi or "DirectSound" in d.hostapi:
                return d
        return inputs[0] if inputs else None

    @classmethod
    def get_default_output_device(cls) -> AudioDeviceInfo | None:
        outputs = cls.list_output_devices()
        for d in outputs:
            if d.is_default:
                return d
        for d in outputs:
            if "WASAPI" in d.hostapi or "DirectSound" in d.hostapi:
                return d
        return outputs[0] if outputs else None

    @classmethod
    def find_device_by_name(cls, query: str, kind: str = "input") -> AudioDeviceInfo | None:
        devices = cls.list_input_devices() if kind == "input" else cls.list_output_devices()
        clean = query.strip().lower()
        for d in devices:
            if clean in d.name.lower():
                return d
        return None

    @classmethod
    def check_device_available(cls, device_id: int) -> bool:
        if not cls.is_available():
            return False
        try:
            info = sd.query_devices(device_id)
            return bool(info)
        except Exception:
            return False

    @classmethod
    def get_audio_system_summary(cls) -> dict[str, Any]:
        default_in = cls.get_default_input_device()
        default_out = cls.get_default_output_device()
        inputs = cls.list_input_devices()
        outputs = cls.list_output_devices()
        return {
            "available": cls.is_available(),
            "inputs_count": len(inputs),
            "outputs_count": len(outputs),
            "default_input": default_in.to_dict() if default_in else None,
            "default_output": default_out.to_dict() if default_out else None,
        }
