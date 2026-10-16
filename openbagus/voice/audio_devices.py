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
    def has_input_device(cls) -> bool:
        """Return True if at least one audio input device is enumerated."""
        return len(cls.list_input_devices()) > 0

    @classmethod
    def get_microphone_status(cls) -> tuple[str, str]:
        """Return (status_code, description) for microphone readiness.

        Status codes:
        - READY: Input device available and functional
        - NO_DEVICE: No input device detected
        - PERMISSION_REQUIRED: Windows privacy permission required
        - BACKEND_ERROR: PortAudio / driver error
        - UNAVAILABLE: Audio library missing
        """
        if not cls.is_available():
            return "UNAVAILABLE", "sounddevice missing"
        inputs = cls.list_input_devices()
        if not inputs:
            return "NO_DEVICE", "No input device detected"
        def_in = cls.get_default_input_device()
        dev_name = def_in.name if def_in else inputs[0].name
        short_name = dev_name.split("(")[0].strip() if "(" in dev_name else dev_name[:20]
        try:
            sd.check_input_settings(device=def_in.id if def_in else None)
            return "READY", short_name
        except Exception as e:
            err_str = str(e).lower()
            if "permission" in err_str or "access denied" in err_str:
                return "PERMISSION_REQUIRED", "Microphone access blocked in Windows Settings"
            return "BACKEND_ERROR", f"Audio driver error: {e}"

    @classmethod
    def list_input_devices(cls) -> list[AudioDeviceInfo]:
        """Lists all physical and virtual microphone input devices."""
        if not cls.is_available():
            return []
        devices: list[AudioDeviceInfo] = []
        try:
            raw_devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            default_in = sd.default.device[0]

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
            default_out = sd.default.device[1]

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
    def validate_device(cls, device_id: int, kind: str = "input") -> bool:
        """Validates that a device index exists, has positive channels for the given kind, and settings pass."""
        if not cls.is_available() or device_id < 0:
            return False
        try:
            raw_devs = sd.query_devices()
            if device_id >= len(raw_devs):
                return False
            dev = raw_devs[device_id]
            if kind == "input":
                if int(dev.get("max_input_channels", 0)) <= 0:
                    return False
                sd.check_input_settings(device=device_id)
            else:
                if int(dev.get("max_output_channels", 0)) <= 0:
                    return False
                sd.check_output_settings(device=device_id)
            return True
        except Exception:
            return False

    @classmethod
    def get_default_input_device(cls, preferred: int | str | None = None) -> AudioDeviceInfo | None:
        """Finds the optimal input device honoring manual preference, WASAPI endpoint, or system default."""
        inputs = cls.list_input_devices()
        if not inputs:
            return None

        # 1. Honor explicit manual override if provided and valid
        if preferred is not None:
            if isinstance(preferred, int):
                for d in inputs:
                    if d.id == preferred and cls.validate_device(d.id, kind="input"):
                        return d
            elif isinstance(preferred, str) and preferred.strip():
                clean_pref = preferred.strip().lower()
                for d in inputs:
                    if clean_pref in d.name.lower() and cls.validate_device(d.id, kind="input"):
                        return d

        # 2. Prefer Windows WASAPI default input endpoint (lowest latency, bit-perfect, zero blocking)
        try:
            hostapis = sd.query_hostapis()
            for api in hostapis:
                if "wasapi" in str(api.get("name", "")).lower():
                    wasapi_def_in = int(api.get("default_input_device", -1))
                    if wasapi_def_in >= 0 and cls.validate_device(wasapi_def_in, kind="input"):
                        for d in inputs:
                            if d.id == wasapi_def_in:
                                return d
        except Exception as e:
            logger.debug("Error probing WASAPI default input endpoint: %s", e)

        # 3. Prefer Windows system default communication/multimedia endpoint
        try:
            sys_def_in = int(sd.default.device[0])
            if sys_def_in >= 0 and cls.validate_device(sys_def_in, kind="input"):
                for d in inputs:
                    if d.id == sys_def_in:
                        return d
        except Exception as e:
            logger.debug("Error probing system default input endpoint: %s", e)

        # 4. Fallback: First valid DirectSound device, then first valid device of any API
        for d in inputs:
            if "DirectSound" in d.hostapi and cls.validate_device(d.id, kind="input"):
                return d
        for d in inputs:
            if cls.validate_device(d.id, kind="input"):
                return d

        return inputs[0] if inputs else None

    @classmethod
    def get_default_output_device(cls, preferred: int | str | None = None) -> AudioDeviceInfo | None:
        """Finds the optimal output device honoring manual preference, WASAPI endpoint, or system default."""
        outputs = cls.list_output_devices()
        if not outputs:
            return None

        # 1. Honor explicit manual override if provided and valid
        if preferred is not None:
            if isinstance(preferred, int):
                for d in outputs:
                    if d.id == preferred and cls.validate_device(d.id, kind="output"):
                        return d
            elif isinstance(preferred, str) and preferred.strip():
                clean_pref = preferred.strip().lower()
                for d in outputs:
                    if clean_pref in d.name.lower() and cls.validate_device(d.id, kind="output"):
                        return d

        # 2. Prefer Windows WASAPI default output endpoint (lowest latency, no WDM-KS conflict)
        try:
            hostapis = sd.query_hostapis()
            for api in hostapis:
                if "wasapi" in str(api.get("name", "")).lower():
                    wasapi_def_out = int(api.get("default_output_device", -1))
                    if wasapi_def_out >= 0 and cls.validate_device(wasapi_def_out, kind="output"):
                        for d in outputs:
                            if d.id == wasapi_def_out:
                                return d
        except Exception as e:
            logger.debug("Error probing WASAPI default output endpoint: %s", e)

        # 3. Prefer Windows system default communication/multimedia endpoint
        try:
            sys_def_out = int(sd.default.device[1])
            if sys_def_out >= 0 and cls.validate_device(sys_def_out, kind="output"):
                for d in outputs:
                    if d.id == sys_def_out:
                        return d
        except Exception as e:
            logger.debug("Error probing system default output endpoint: %s", e)

        # 4. Fallback: First valid DirectSound device, then first valid device of any API
        for d in outputs:
            if "DirectSound" in d.hostapi and cls.validate_device(d.id, kind="output"):
                return d
        for d in outputs:
            if cls.validate_device(d.id, kind="output"):
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
        if not cls.is_available() or device_id < 0:
            return False
        try:
            info = sd.query_devices(device_id)
            return bool(info)
        except Exception:
            return False

    @classmethod
    def get_device_report(cls, device_id: int | None = None, kind: str = "input") -> dict[str, Any]:
        """Provides a complete diagnostics report for an audio device."""
        if not cls.is_available():
            return {"available": False, "error": "sounddevice unavailable"}
        target_id = device_id
        if target_id is None:
            dev_obj = cls.get_default_input_device() if kind == "input" else cls.get_default_output_device()
            target_id = dev_obj.id if dev_obj else None
        if target_id is None:
            return {"available": False, "device_id": None, "error": "No matching device found"}
        try:
            info = sd.query_devices(target_id)
            hostapis = sd.query_hostapis()
            api_idx = info.get("hostapi", 0)
            api_name = hostapis[api_idx]["name"] if api_idx < len(hostapis) else "Unknown"
            valid = cls.validate_device(target_id, kind=kind)
            return {
                "available": True,
                "device_id": target_id,
                "name": info.get("name", "Unknown"),
                "kind": kind,
                "hostapi": api_name,
                "channels": int(info.get("max_input_channels" if kind == "input" else "max_output_channels", 0)),
                "default_samplerate": float(info.get("default_samplerate", 0.0)),
                "valid": valid,
            }
        except Exception as e:
            return {"available": False, "device_id": target_id, "error": str(e)}

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
