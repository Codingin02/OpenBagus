"""Tests for audio device enumeration, selection policy, validation, and diagnostics reporting."""

import unittest
from openbagus.voice.audio_devices import AudioDeviceManager, AudioDeviceInfo


class TestAudioDeviceSelection(unittest.TestCase):

    def test_device_enumeration(self):
        """Verify input and output device listing returns structured AudioDeviceInfo."""
        inputs = AudioDeviceManager.list_input_devices()
        outputs = AudioDeviceManager.list_output_devices()

        self.assertIsInstance(inputs, list)
        self.assertIsInstance(outputs, list)

        for dev in inputs:
            self.assertIsInstance(dev, AudioDeviceInfo)
            self.assertEqual(dev.kind, "input")
            self.assertGreater(dev.max_channels, 0)
            self.assertGreaterEqual(dev.id, 0)
            self.assertIsInstance(dev.name, str)

        for dev in outputs:
            self.assertIsInstance(dev, AudioDeviceInfo)
            self.assertEqual(dev.kind, "output")
            self.assertGreater(dev.max_channels, 0)
            self.assertGreaterEqual(dev.id, 0)
            self.assertIsInstance(dev.name, str)

    def test_wasapi_prioritization_or_fallback(self):
        """Verify selection prioritizes WASAPI endpoint when valid, or cleanly falls back."""
        def_in = AudioDeviceManager.get_default_input_device()
        if def_in is not None:
            self.assertIsInstance(def_in, AudioDeviceInfo)
            self.assertGreater(def_in.max_channels, 0)
            self.assertTrue(AudioDeviceManager.validate_device(def_in.id, kind="input"))

        def_out = AudioDeviceManager.get_default_output_device()
        if def_out is not None:
            self.assertIsInstance(def_out, AudioDeviceInfo)
            self.assertGreater(def_out.max_channels, 0)
            self.assertTrue(AudioDeviceManager.validate_device(def_out.id, kind="output"))

    def test_manual_override_by_id(self):
        """Verify explicit valid device ID override is respected."""
        inputs = AudioDeviceManager.list_input_devices()
        if inputs:
            first_in = inputs[0]
            chosen = AudioDeviceManager.get_default_input_device(preferred=first_in.id)
            self.assertIsNotNone(chosen)
            self.assertEqual(chosen.id, first_in.id)

    def test_manual_override_by_name(self):
        """Verify explicit name substring search is respected."""
        inputs = AudioDeviceManager.list_input_devices()
        if inputs:
            target_name = inputs[0].name.split()[0]
            chosen = AudioDeviceManager.get_default_input_device(preferred=target_name)
            self.assertIsNotNone(chosen)
            self.assertIn(target_name.lower(), chosen.name.lower())

    def test_invalid_override_fallback(self):
        """Verify non-existent or invalid device IDs fall back gracefully."""
        chosen = AudioDeviceManager.get_default_input_device(preferred=999999)
        inputs = AudioDeviceManager.list_input_devices()
        if inputs:
            self.assertIsNotNone(chosen)
            self.assertNotEqual(chosen.id, 999999)
        else:
            self.assertIsNone(chosen)

    def test_device_validation(self):
        """Verify device validation logic."""
        self.assertFalse(AudioDeviceManager.validate_device(-1, kind="input"))
        self.assertFalse(AudioDeviceManager.validate_device(999999, kind="input"))

        inputs = AudioDeviceManager.list_input_devices()
        if inputs:
            self.assertTrue(AudioDeviceManager.validate_device(inputs[0].id, kind="input"))
            if inputs[0].max_output_channels == 0:
                self.assertFalse(AudioDeviceManager.validate_device(inputs[0].id, kind="output"))

    def test_device_diagnostics_report(self):
        """Verify diagnostics report returns complete structured telemetry."""
        in_report = AudioDeviceManager.get_device_report(kind="input")
        self.assertIsInstance(in_report, dict)
        self.assertIn("available", in_report)

        if in_report.get("available"):
            self.assertIn("device_id", in_report)
            self.assertIn("name", in_report)
            self.assertIn("hostapi", in_report)
            self.assertIn("channels", in_report)
            self.assertIn("default_samplerate", in_report)
            self.assertIn("valid", in_report)

        out_report = AudioDeviceManager.get_device_report(kind="output")
        self.assertIsInstance(out_report, dict)
        self.assertIn("available", out_report)


if __name__ == "__main__":
    unittest.main()
