"""Tests for real-time audio capture callback safety, worker decoupling, and stress resilience."""

import time
import unittest
import numpy as np
from openbagus.voice.audio_capture import AudioCaptureStream
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.audio_devices import AudioDeviceManager


class TestAudioCaptureRealtime(unittest.TestCase):

    def test_audio_capture_lifecycle_and_telemetry(self):
        """Verify audio capture starts, captures frames, updates telemetry, and stops cleanly."""
        if not AudioDeviceManager.has_input_device():
            self.skipTest("No physical microphone detected")

        stream = AudioCaptureStream()
        started = stream.start()
        self.assertTrue(started)
        self.assertTrue(stream.is_capturing)

        time.sleep(0.25)

        telemetry = stream.get_telemetry()
        self.assertIsInstance(telemetry, dict)
        self.assertTrue(telemetry["is_capturing"])
        self.assertGreaterEqual(telemetry["overflow_count"], 0)
        self.assertGreaterEqual(telemetry["dropped_frames_count"], 0)

        frame = stream.get_next_frame(timeout=0.2)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (512,))
        self.assertEqual(frame.dtype, np.float32)

        stream.stop()
        self.assertFalse(stream.is_capturing)

    def test_rapid_start_stop_stress(self):
        """Verify stream handles rapid start/stop cycles without thread leaks or deadlocks."""
        if not AudioDeviceManager.has_input_device():
            self.skipTest("No physical microphone detected")

        stream = AudioCaptureStream()
        for _ in range(5):
            self.assertTrue(stream.start())
            time.sleep(0.05)
            stream.stop()
            self.assertFalse(stream.is_capturing)

    def test_rapid_mute_unmute_during_capture(self):
        """Verify stream handles rapid mute/unmute toggling under active capture without deadlock."""
        if not AudioDeviceManager.has_input_device():
            self.skipTest("No physical microphone detected")

        stream = AudioCaptureStream()
        self.assertTrue(stream.start())

        for _ in range(5):
            stream.set_muted(True)
            self.assertTrue(stream.is_muted)
            time.sleep(0.02)
            stream.set_muted(False)
            self.assertFalse(stream.is_muted)
            time.sleep(0.02)

        stream.stop()
        self.assertFalse(stream.is_capturing)

    def test_playback_instant_barge_in(self):
        """Verify AudioPlaybackManager immediately aborts playback and bumps generation on stop."""
        interrupted_called = []
        manager = AudioPlaybackManager(
            on_interrupted=lambda: interrupted_called.append(True)
        )

        sr = 22050
        audio = (0.05 * np.sin(2 * np.pi * 440 * np.linspace(0, 1.0, sr))).astype(np.float32)

        initial_gen = manager.current_generation_id
        manager.enqueue(audio, samplerate=sr)

        time.sleep(0.05)

        manager.stop_playback(interrupted=True)

        self.assertFalse(manager.is_playing)
        self.assertEqual(manager.queue_size, 0)
        self.assertGreater(manager.current_generation_id, initial_gen)
        self.assertGreaterEqual(len(interrupted_called), 1)


if __name__ == "__main__":
    unittest.main()
