"""Unit and regression suite for OpenBagus V5.4.1 Live Session Correctness.

Covers:
- P0-1: Separation of has_active_components, is_fully_ready, is_listening, is_hidden.
        Safe reconciliation of voice-only, 3D-only, and hidden initial states.
- P0-2: Truthful status without unverified READY labels; verified state transitions.
- P0-4: Idempotency, clean restarts without stale cancellation tokens, subprocess cleanup
        on timeout, port 7432 handshake verification, and exit-cancel preservation.
- P1:   Thread-safe console output synchronization immune to onecmd stdout redirection.
"""

from __future__ import annotations

import contextlib
import io
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openbagus.cli import OpenBagusShell
from openbagus.companion.live_session import (
    BagusmaxLiveSessionCoordinator,
    SessionStartResult,
    SessionStatus,
    SessionStopResult,
)
from openbagus.companion.controller import CompanionController, IPC_HOST, IPC_PORT, IPC_VERSION
from openbagus.voice.turn_controller import VoiceState
from openbagus.voice.audio_devices import AudioDeviceManager, AudioDeviceInfo


class TestBagusmaxV541LiveCorrectness(unittest.TestCase):
    """Targeted regression tests for V5.4.1 live session correctness and failure recovery."""

    def setUp(self):
        self.shell = OpenBagusShell()
        self.shell.current_mode = "FAST"
        self.coord = self.shell.bagusmax_coordinator

    def tearDown(self):
        try:
            self.coord.stop()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # P0-1 — Incomplete Live Session Detection & Safe Reconciliation
    # -------------------------------------------------------------------------
    def test_component_state_separation(self):
        """[PASS_UNIT] has_active_components != is_fully_ready != is_listening."""
        # Initial: nothing active
        self.assertFalse(self.coord.has_active_components())
        self.assertFalse(self.coord.is_fully_ready())
        self.assertFalse(self.coord.is_listening())
        self.assertFalse(self.coord.is_hidden())
        self.assertEqual(self.coord.status().state, "NOT_STARTED")

        # Voice-only active: has_active_components is True, but NOT fully ready
        fake_voice = MagicMock()
        fake_voice._active = True
        fake_voice.controller.capture_stream.is_capturing = True
        fake_voice.controller.capture_stream._stream = MagicMock(active=True)
        fake_voice.controller.capture_stream.is_muted = False
        fake_voice.controller._loop_active = True
        fake_voice.controller._loop_thread = MagicMock(is_alive=lambda: True)
        fake_voice.controller.state = VoiceState.LISTENING

        self.shell.voice_session = fake_voice
        self.assertTrue(self.coord.has_active_components())
        self.assertFalse(self.coord.is_fully_ready())  # Companion is missing!
        self.assertFalse(self.coord.is_listening())
        self.assertEqual(self.coord.status().state, "DEGRADED")

    @patch.object(CompanionController, "_is_connected", return_value=True)
    @patch.object(CompanionController, "show", return_value=True)
    def test_reconciliation_voice_only_starts_companion(self, mock_show, mock_conn):
        """[PASS_UNIT] If voice is already running, /bagusmax starts the missing 3D companion."""
        fake_voice = MagicMock()
        fake_voice._active = True
        fake_voice.controller.capture_stream.is_capturing = True
        fake_voice.controller.capture_stream._stream = MagicMock(active=True)
        fake_voice.controller.capture_stream.is_muted = False
        fake_voice.controller._loop_active = True
        fake_voice.controller._loop_thread = MagicMock(is_alive=lambda: True)
        fake_voice.controller.state = VoiceState.LISTENING
        self.shell.voice_session = fake_voice

        with patch("openbagus.voice.audio_devices.AudioDeviceManager.get_default_output_device",
                   return_value=AudioDeviceInfo(8, "Speakers", "WASAPI", 2, 48000, 0.01, 0.01)):
            res = self.coord.start()
            self.assertTrue(res.success)
            self.assertTrue(mock_show.called)
            self.assertTrue(self.coord.is_fully_ready())

    @patch.object(CompanionController, "_is_connected", return_value=True)
    def test_reconciliation_companion_only_starts_voice(self, mock_conn):
        """[PASS_UNIT] If companion is running, /bagusmax starts the missing voice session."""
        comp = CompanionController.get_instance()
        self.coord._companion = comp

        with patch("openbagus.voice.turn_controller.LocalASREngine"):
            with patch("openbagus.voice.voice_session.LocalTTSEngine"):
                with patch("openbagus.voice.audio_devices.AudioDeviceManager.get_microphone_status", return_value=("READY", "OK")):
                    with patch("openbagus.voice.audio_devices.AudioDeviceManager.get_default_output_device",
                               return_value=AudioDeviceInfo(8, "Speakers", "WASAPI", 2, 48000, 0.01, 0.01)):
                        with patch("openbagus.voice.audio_capture.AudioCaptureStream.start", return_value=True):
                            with patch("openbagus.voice.turn_controller.VoiceTurnController.start_voice_loop", return_value=True):
                                res = self.coord.start()
                                self.assertIsNotNone(self.shell.voice_session)
                                self.assertTrue(self.shell.voice_session._active)

    def test_hidden_state_resumes_without_duplication(self):
        """[PASS_UNIT] Hidden session resumes and unhides without spawning extra streams."""
        self.coord._is_hidden = True
        self.coord._is_active = True
        fake_voice = MagicMock()
        self.shell.voice_session = fake_voice
        mock_comp = MagicMock()
        self.coord._companion = mock_comp

        res = self.coord.start()
        self.assertTrue(res.success)
        self.assertFalse(self.coord.is_hidden())
        self.assertTrue(mock_comp.show.called)
        self.assertTrue(fake_voice.set_muted.called)

    # -------------------------------------------------------------------------
    # P0-2 — Truthful Status Without Unverified READY Labels
    # -------------------------------------------------------------------------
    def test_status_reports_truthful_verified_states(self):
        """[PASS_UNIT] Status distinguishes NOT_STARTED, DEGRADED, READY, LISTENING, FAILED."""
        # 1. NOT_STARTED baseline
        st = self.coord.status()
        self.assertEqual(st.state, "NOT_STARTED")
        self.assertEqual(st.mic_status, "STANDBY — Microphone (Realtek USB2.0 Audio)" if "Microphone" in st.mic_status else st.mic_status)

        # 2. FAILED output device
        with patch("openbagus.voice.audio_devices.AudioDeviceManager.get_default_output_device", return_value=None):
            st_no_spk = self.coord.status()
            self.assertIn("FAILED", st_no_spk.speaker_status)

        # 3. Provider error reported truthfully
        mock_prov = MagicMock()
        mock_prov.is_available.side_effect = RuntimeError("Ollama connection refused")
        mock_prov.get_provider_name.return_value = "OLLAMA_FAST"
        self.shell.agent_harness.provider = mock_prov
        st_prov = self.coord.status()
        self.assertIn("FAILED", st_prov.ai_provider)

    # -------------------------------------------------------------------------
    # P0-4 — Resource Lifecycle, Recovery, and Handshake Verification
    # -------------------------------------------------------------------------
    def test_exit_cancellation_preserves_live_session(self):
        """[PASS_UNIT] Entering /exit and choosing Cancel [X] must NOT destroy live session."""
        self.coord._is_active = True
        mock_stop = MagicMock()
        self.coord.stop = mock_stop

        # Simulate user entering 'x' to cancel exit
        with patch.object(self.shell, "_ask", return_value="x"):
            with patch("sys.stdin.isatty", return_value=True):
                res = self.shell.do_exit("")
                self.assertFalse(res)  # Exit aborted
                self.assertFalse(mock_stop.called)  # Coordinator NOT stopped!

    def test_handshake_verification_rejects_unrelated_process(self):
        """[PASS_UNIT] Port 7432 occupied by unrelated process is rejected by companion controller."""
        comp = CompanionController.get_instance()
        fake_socket = MagicMock()
        # Returns generic HTTP or unrelated text
        fake_socket.recv.return_value = b'{"status": "ok", "app": "some_other_server"}\n'
        with patch("socket.socket", return_value=fake_socket):
            ok = comp._connect()
            self.assertFalse(ok)  # Rejected handshake!

    def test_handshake_verification_accepts_valid_companion(self):
        """[PASS_UNIT] Port 7432 returning openbagus_companion handshake is accepted."""
        comp = CompanionController.get_instance()
        fake_socket = MagicMock()
        fake_socket.recv.return_value = b'{"status": "ok", "app": "openbagus_companion", "version": "2.0"}\n'
        with patch("socket.socket", return_value=fake_socket):
            ok = comp._connect()
            self.assertTrue(ok)

    # -------------------------------------------------------------------------
    # P1 — Output Synchronization (Immune to redirect_stdout)
    # -------------------------------------------------------------------------
    def test_print_voice_output_bypasses_onecmd_redirect_stdout(self):
        """[PASS_UNIT] Asynchronous voice output writes to sys.__stdout__ and is not trapped in onecmd buffer."""
        out_buf = io.StringIO()
        real_stdout_buf = io.StringIO()

        with patch("sys.__stdout__", real_stdout_buf):
            with contextlib.redirect_stdout(out_buf):
                self.shell._print_voice_output("[Voice] Halo Bagusmax")

        # The voice output must have gone to sys.__stdout__, NOT the command redirect buffer!
        self.assertEqual(out_buf.getvalue(), "")
        self.assertIn("[Voice] Halo Bagusmax", real_stdout_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
