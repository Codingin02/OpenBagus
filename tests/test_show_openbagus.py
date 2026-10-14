"""Acceptance tests for BAGUSMAX Dual-Form 3D companion character, animator, and controller."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from openbagus.companion.controller import CompanionController, IPC_PORT, IPC_VERSION
from openbagus.companion.renderer import (
    AnimState,
    BagusmaxForm,
    CharacterAnimator,
    build_bagusmax_armored,
    build_bagusmax_white,
    build_character,
)


class TestBagusmaxGeometry(unittest.TestCase):
    """Verifies BAGUSMAX procedural 3D dual-form geometry, proportions, and color palettes."""

    def test_white_form_mesh_generation(self) -> None:
        """BAGUSMAX White must generate a dense, valid 3D mesh."""
        verts, idxs = build_bagusmax_white(blink=0.0, breath=1.0)
        self.assertGreater(len(verts), 10_000)
        self.assertGreater(len(idxs), 10_000)

        stride = 9
        n_verts = len(verts) // stride
        n_tris = len(idxs) // 3
        self.assertGreaterEqual(n_verts, 3_000)
        self.assertGreaterEqual(n_tris, 6_000)

        max_idx = max(idxs)
        self.assertLess(max_idx, n_verts)

    def test_white_form_color_palette_and_no_mario(self) -> None:
        """BAGUSMAX White must feature warm white vinyl and black eyes, with zero Mario geometry."""
        verts, _ = build_bagusmax_white()
        stride = 9
        n_verts = len(verts) // stride

        has_white = False
        has_black_eyes = False
        has_silver_port = False
        has_mario_blue = False
        has_mario_brown = False

        for i in range(n_verts):
            r = verts[i * stride + 6]
            g = verts[i * stride + 7]
            b = verts[i * stride + 8]

            # Warm vinyl white: r, g, b >= 0.90
            if r >= 0.90 and g >= 0.90 and b >= 0.90:
                has_white = True
            # Black eyes / connecting line: r, g, b <= 0.05
            elif r <= 0.05 and g <= 0.05 and b <= 0.05:
                has_black_eyes = True
            # Silver port ring: 0.80 <= r <= 0.90 and 0.80 <= g <= 0.90 and 0.80 <= b <= 0.90
            elif 0.80 <= r <= 0.90 and 0.80 <= g <= 0.90 and 0.80 <= b <= 0.90:
                has_silver_port = True

            # Mario blue overalls: b > 0.6 and r < 0.3
            if b > 0.6 and r < 0.3 and g < 0.4:
                has_mario_blue = True
            # Mario brown boots: r > 0.3, g < 0.3, b < 0.15
            if r > 0.3 and g < 0.3 and b < 0.15:
                has_mario_brown = True

        self.assertTrue(has_white, "BAGUSMAX White must have warm white vinyl body")
        self.assertTrue(has_black_eyes, "BAGUSMAX White must have signature black eyes")
        self.assertTrue(has_silver_port, "BAGUSMAX White must have silver access port on left chest")
        self.assertFalse(has_mario_blue, "BAGUSMAX must NOT contain Mario blue overalls")
        self.assertFalse(has_mario_brown, "BAGUSMAX must NOT contain Mario brown boots")

    def test_armored_form_mesh_generation(self) -> None:
        """BAGUSMAX Armored must generate a complete hero armor 3D mesh."""
        verts, idxs = build_bagusmax_armored(blink=0.0, breath=1.0)
        self.assertGreater(len(verts), 10_000)
        self.assertGreater(len(idxs), 10_000)

        stride = 9
        n_verts = len(verts) // stride
        n_tris = len(idxs) // 3
        self.assertGreaterEqual(n_verts, 3_000)
        self.assertGreaterEqual(n_tris, 6_000)

        max_idx = max(idxs)
        self.assertLess(max_idx, n_verts)

    def test_armored_form_color_palette(self) -> None:
        """BAGUSMAX Armored must feature glossy red armor, purple abdominal insert, graphite joints, white visor."""
        verts, _ = build_bagusmax_armored()
        stride = 9
        n_verts = len(verts) // stride

        has_armor_red = False
        has_purple_abs = False
        has_graphite_joints = False
        has_white_visor = False
        has_black_eyes = False

        for i in range(n_verts):
            r = verts[i * stride + 6]
            g = verts[i * stride + 7]
            b = verts[i * stride + 8]

            # Armor red: r > 0.75, g < 0.25, b < 0.15
            if r > 0.75 and g < 0.25 and b < 0.15:
                has_armor_red = True
            # Purple abdominal insert: 0.25 <= r <= 0.45, 0.10 <= g <= 0.25, 0.40 <= b <= 0.55
            elif 0.25 <= r <= 0.45 and 0.10 <= g <= 0.25 and 0.40 <= b <= 0.55:
                has_purple_abs = True
            # Graphite joints: 0.10 <= r <= 0.18, 0.10 <= g <= 0.18, 0.10 <= b <= 0.18
            elif 0.10 <= r <= 0.18 and 0.10 <= g <= 0.18 and 0.10 <= b <= 0.18:
                has_graphite_joints = True
            # White visor: r >= 0.90, g >= 0.90, b >= 0.90
            elif r >= 0.90 and g >= 0.90 and b >= 0.90:
                has_white_visor = True
            # Black eyes: r <= 0.05, g <= 0.05, b <= 0.05
            elif r <= 0.05 and g <= 0.05 and b <= 0.05:
                has_black_eyes = True

        self.assertTrue(has_armor_red, "BAGUSMAX Armored must have red armor plating")
        self.assertTrue(has_purple_abs, "BAGUSMAX Armored must have segmented purple abdominal insert")
        self.assertTrue(has_graphite_joints, "BAGUSMAX Armored must have dark graphite mechanical joints")
        self.assertTrue(has_white_visor, "BAGUSMAX Armored must have white face visor")
        self.assertTrue(has_black_eyes, "BAGUSMAX Armored must display two black eyes on visor")

    def test_build_character_dispatch(self) -> None:
        """build_character must correctly dispatch to WHITE or ARMORED form."""
        verts_white, _ = build_character(form="WHITE")
        verts_armored, _ = build_character(form="ARMORED")
        self.assertNotEqual(len(verts_white), 0)
        self.assertNotEqual(len(verts_armored), 0)
        # Colors must differ between white and armored forms
        self.assertNotEqual(verts_white[:50], verts_armored[:50])

    def test_blink_variation(self) -> None:
        """Eye geometry changes with blink parameter on both forms."""
        w_open, _ = build_bagusmax_white(blink=0.0)
        w_blink, _ = build_bagusmax_white(blink=1.0)
        self.assertNotEqual(w_open, w_blink)

        a_open, _ = build_bagusmax_armored(blink=0.0)
        a_blink, _ = build_bagusmax_armored(blink=1.0)
        self.assertNotEqual(a_open, a_blink)


class TestCharacterAnimator(unittest.TestCase):
    """Verifies animation states, reasoning mode synchronization, and morph progression."""

    def setUp(self) -> None:
        self.animator = CharacterAnimator()

    def test_animator_states(self) -> None:
        self.assertEqual(self.animator.state, AnimState.IDLE)
        valid_states = [
            AnimState.IDLE,
            AnimState.LISTENING,
            AnimState.HEARD_USER,
            AnimState.THINKING,
            AnimState.DEEP_THINKING,
            AnimState.SPEAKING,
            AnimState.HAPPY,
            AnimState.SURPRISED,
            AnimState.CONFUSED,
            AnimState.WARNING,
            AnimState.TOOL_WORKING,
            AnimState.SUCCESS,
            AnimState.ERROR,
            AnimState.SLEEPING,
        ]
        for st in valid_states:
            self.animator.set_state(st)
            self.assertEqual(self.animator.state, st)

    def test_mode_and_form_synchronization(self) -> None:
        """Setting mode to FAST must select WHITE form; DEEP_REASONING must select ARMORED form."""
        self.animator.set_mode("FAST")
        self.assertEqual(self.animator.target_form, BagusmaxForm.WHITE)

        self.animator.set_mode("DEEP_REASONING")
        self.assertEqual(self.animator.target_form, BagusmaxForm.ARMORED)

        # Update loop morph progression
        self.animator.update(dt=0.5)
        self.assertEqual(self.animator.character_form, BagusmaxForm.ARMORED)

        # Switch back to FAST
        self.animator.set_mode("FAST")
        self.assertEqual(self.animator.target_form, BagusmaxForm.WHITE)
        self.animator.update(dt=0.5)
        self.assertEqual(self.animator.character_form, BagusmaxForm.WHITE)

    def test_speech_synchronization_without_mouth(self) -> None:
        """Mouthless Baymax speech synchronization drives head nod and chest breath scale from amplitude."""
        self.animator.set_state(AnimState.SPEAKING)
        self.animator.amplitude = 0.8
        self.animator.update(dt=0.05)
        params = self.animator.get_params()
        self.assertEqual(params["mouth_open"], 0.0)  # No mouth aperture
        self.assertGreater(params["breath_scale"], 1.0)  # Inflatable chest expansion
        self.assertIn("head_nod", params)


class TestCompanionController(unittest.TestCase):
    """Verifies controller singleton, dual-form status reporting, and IPC command generation."""

    def setUp(self) -> None:
        self.controller = CompanionController.get_instance()

    def test_singleton(self) -> None:
        c2 = CompanionController.get_instance()
        self.assertIs(self.controller, c2)

    def test_status_format(self) -> None:
        st = self.controller.get_status()
        self.assertIn("running", st)
        self.assertIn("connected", st)
        self.assertIn("pid", st)
        self.assertIn("last_state", st)
        self.assertIn("character_form", st)
        self.assertIn("mode", st)
        self.assertIn("ipc_address", st)
        self.assertEqual(st["ipc_version"], IPC_VERSION)
        self.assertEqual(st["ipc_address"], f"127.0.0.1:{IPC_PORT}")

    def test_set_mode_synchronizes_form(self) -> None:
        self.controller.set_mode("FAST")
        self.assertEqual(self.controller.get_form(), "WHITE")
        self.assertEqual(self.controller.get_mode(), "FAST")

        self.controller.set_mode("DEEP_REASONING")
        self.assertEqual(self.controller.get_form(), "ARMORED")
        self.assertEqual(self.controller.get_mode(), "DEEP_REASONING")

    def test_state_change_does_not_crash_when_offline(self) -> None:
        res = self.controller.set_state("LISTENING")
        self.assertIsInstance(res, bool)

    def test_amplitude_does_not_crash_when_offline(self) -> None:
        res = self.controller.speak_amplitude(0.75)
        self.assertIsInstance(res, bool)


class TestCliCompanionCommands(unittest.TestCase):
    """Verifies that interactive CLI commands (/show-openbagus, /bagusmax, /mode) route cleanly."""

    def setUp(self) -> None:
        from openbagus.cli import OpenBagusShell
        self.shell = OpenBagusShell()

    @patch("openbagus.companion.controller.CompanionController.show", return_value=True)
    def test_bare_show_openbagus_command(self, mock_show: MagicMock) -> None:
        """The bare command /show-openbagus MUST immediately trigger show()."""
        with patch("sys.stdout"):
            self.shell.onecmd("/show-openbagus")
        mock_show.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.show", return_value=True)
    def test_bagusmax_alias_command(self, mock_show: MagicMock) -> None:
        """The command /bagusmax MUST immediately invoke show()."""
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax")
        mock_show.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.show", return_value=True)
    def test_explicit_show_command(self, mock_show: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/show-openbagus show")
        mock_show.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.hide", return_value=True)
    def test_hide_command(self, mock_hide: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/show-openbagus hide")
        mock_hide.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.get_status", return_value={"running": True, "connected": True, "pid": 1234, "last_state": "IDLE", "character_form": "WHITE", "mode": "FAST"})
    def test_status_command(self, mock_status: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/show-openbagus status")
        mock_status.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.reset", return_value=True)
    def test_reset_command(self, mock_reset: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/show-openbagus reset")
        mock_reset.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.close", return_value=True)
    def test_close_command(self, mock_close: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/show-openbagus close")
        mock_close.assert_called_once()

    @patch("openbagus.companion.controller.CompanionController.show", return_value=True)
    def test_alias_and_unprefixed_routing(self, mock_show: MagicMock) -> None:
        """Both 'show-openbagus', 'bagusmax', and '/show' must invoke show()."""
        with patch("sys.stdout"):
            self.shell.onecmd("show-openbagus")
            self.shell.onecmd("bagusmax")
            self.shell.onecmd("/show")
        self.assertEqual(mock_show.call_count, 3)

    def test_mode_switch_fast_and_deep(self) -> None:
        """Switching mode to fast and deep must update shell current_mode and sync companion."""
        with patch("sys.stdout"):
            self.shell.onecmd("/mode fast")
            self.assertEqual(self.shell.current_mode, "FAST")
            self.shell.onecmd("/mode deep")
            self.assertEqual(self.shell.current_mode, "DEEP_REASONING")

    def test_voice_status_and_devices(self) -> None:
        """Voice commands /voice status and /voice devices must execute without crashing."""
        with patch("sys.stdout"):
            self.shell.onecmd("/voice status")
            self.shell.onecmd("/voice devices")


class TestAudioDeviceDiagnostics(unittest.TestCase):
    """Verifies AudioDeviceManager diagnostics and status queries."""

    def test_has_input_device(self) -> None:
        from openbagus.voice.audio_devices import AudioDeviceManager
        res = AudioDeviceManager.has_input_device()
        self.assertIsInstance(res, bool)

    def test_get_microphone_status(self) -> None:
        from openbagus.voice.audio_devices import AudioDeviceManager
        code, detail = AudioDeviceManager.get_microphone_status()
        self.assertIn(code, {"READY", "NO_DEVICE", "PERMISSION_REQUIRED", "BACKEND_ERROR", "UNAVAILABLE"})
        self.assertIsInstance(detail, str)


if __name__ == "__main__":
    unittest.main()
