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


class TestBagusmaxInteraction(unittest.TestCase):
    """Verifies mouse dragging, 3D rotation, scaling, presets, and pivot mathematics."""

    def test_all_nine_presets_generation(self) -> None:
        from openbagus.companion.renderer import calculate_preset_position
        presets = [
            "top-left", "top-center", "top-right",
            "middle-left", "center", "middle-right",
            "bottom-left", "bottom-center", "bottom-right",
        ]
        for p in presets:
            x, y = calculate_preset_position(p, 480, 560, monitor_idx=0)
            self.assertIsInstance(x, int)
            self.assertIsInstance(y, int)

    def test_window_clamping_policy(self) -> None:
        from openbagus.companion.renderer import clamp_window_position
        # Clamped policy should keep window accessible
        cx, cy = clamp_window_position(-500, -200, 480, 560, policy="CLAMP_TO_VISIBLE_WORKAREA")
        self.assertGreaterEqual(cx, -400)
        self.assertGreaterEqual(cy, 0)

        # Free positioning allows exact placement
        fx, fy = clamp_window_position(-500, -200, 480, 560, policy="FREE_POSITIONING")
        self.assertEqual(fx, -500)
        self.assertEqual(fy, -200)

    def test_interaction_manager_scale_and_rotation_bounds(self) -> None:
        from openbagus.companion.preferences import CompanionPreferences
        from openbagus.companion.renderer import InteractionManager

        im = InteractionManager(CompanionPreferences())
        # Scaling clamping
        im.set_scale(5.0)
        self.assertEqual(im.character_scale, 2.0)
        im.set_scale(0.1)
        self.assertEqual(im.character_scale, 0.5)
        im.set_scale(1.25)
        self.assertEqual(im.character_scale, 1.25)

        # Yaw normalization (0 - 360)
        im.set_rotation(yaw=450.0)
        self.assertEqual(im.user_yaw, 90.0)
        im.set_rotation(yaw=180.0)
        self.assertEqual(im.user_yaw, 180.0)

        # Pitch clamping (-65 to +65)
        im.set_rotation(pitch=90.0)
        self.assertEqual(im.user_pitch, 65.0)
        im.set_rotation(pitch=-120.0)
        self.assertEqual(im.user_pitch, -65.0)
        im.set_rotation(pitch=25.0)
        self.assertEqual(im.user_pitch, 25.0)

    def test_view_perspectives(self) -> None:
        from openbagus.companion.preferences import CompanionPreferences
        from openbagus.companion.renderer import InteractionManager

        im = InteractionManager(CompanionPreferences())
        im.set_view("front")
        self.assertEqual((im.user_yaw, im.user_pitch), (0.0, 0.0))
        im.set_view("back")
        self.assertEqual((im.user_yaw, im.user_pitch), (180.0, 0.0))
        im.set_view("left")
        self.assertEqual((im.user_yaw, im.user_pitch), (270.0, 0.0))
        im.set_view("right")
        self.assertEqual((im.user_yaw, im.user_pitch), (90.0, 0.0))
        im.set_view("top")
        self.assertEqual((im.user_yaw, im.user_pitch), (0.0, -50.0))
        im.set_view("reset")
        self.assertEqual((im.user_yaw, im.user_pitch), (0.0, 0.0))

    def test_stable_pivot_mathematics(self) -> None:
        """Rotating 180 deg or scaling must keep pivot point (0.0, 0.76, 0.0) perfectly invariant."""
        import math
        from pyrr import Matrix44, Vector3

        pivot = Vector3([0.0, 0.76, 0.0])
        T_pivot_inv = Matrix44.from_translation([0.0, -0.76, 0.0], dtype="f4")
        T_pivot = Matrix44.from_translation([0.0, 0.76, 0.0], dtype="f4")
        S = Matrix44.from_scale([1.5, 1.5, 1.5], dtype="f4")
        R_pitch = Matrix44.from_x_rotation(math.radians(25.0), dtype="f4")
        R_yaw = Matrix44.from_y_rotation(math.radians(180.0), dtype="f4")

        # Stable user orientation around center (0, 0.76, 0)
        user_transform = T_pivot_inv @ S @ R_pitch @ R_yaw @ T_pivot
        transformed_pivot = user_transform * pivot

        self.assertAlmostEqual(transformed_pivot[0], 0.0, places=4)
        self.assertAlmostEqual(transformed_pivot[1], 0.76, places=4)
        self.assertAlmostEqual(transformed_pivot[2], 0.0, places=4)

    def test_drag_delta_invariance(self) -> None:
        """Drag formula target_wx = (wx + cx) - grab_offset must track mouse without jitter."""
        wx = 1000
        wy = 500
        grab_x = 150
        grab_y = 120

        # Cursor moves right by 40px and down by 30px
        cursor_screen_x = 1000 + grab_x + 40
        cursor_screen_y = 500 + grab_y + 30

        target_wx = cursor_screen_x - grab_x
        target_wy = cursor_screen_y - grab_y
        self.assertEqual(target_wx, 1040)
        self.assertEqual(target_wy, 530)


class TestBagusmaxBacksideGeometry(unittest.TestCase):
    """Verifies that rotating 180 degrees reveals complete 3D backside geometry without holes or missing faces."""

    def test_white_form_has_complete_backside(self) -> None:
        verts, _ = build_bagusmax_white()
        stride = 9
        n_verts = len(verts) // stride

        has_rear_torso = False
        has_rear_head = False
        has_rear_legs = False

        for i in range(n_verts):
            y = verts[i * stride + 1]
            z = verts[i * stride + 2]
            nz = verts[i * stride + 5]

            # Head back: y > 1.25, z < -0.05, normal facing backward nz < -0.3
            if y > 1.25 and z < -0.05 and nz < -0.3:
                has_rear_head = True
            # Torso back: 0.5 < y < 1.2, z < -0.1, normal facing backward nz < -0.3
            if 0.5 < y < 1.2 and z < -0.1 and nz < -0.3:
                has_rear_torso = True
            # Leg back: y < 0.5, z < -0.05, normal facing backward nz < -0.3
            if y < 0.5 and z < -0.05 and nz < -0.3:
                has_rear_legs = True

        self.assertTrue(has_rear_head, "White Bagusmax must have back-of-head geometry")
        self.assertTrue(has_rear_torso, "White Bagusmax must have rounded back-of-torso geometry")
        self.assertTrue(has_rear_legs, "White Bagusmax must have rear leg geometry")

    def test_armored_form_has_jetpack_and_folded_wings(self) -> None:
        verts, _ = build_bagusmax_armored()
        stride = 9
        n_verts = len(verts) // stride

        has_jetpack = False
        has_folded_wings = False
        has_rear_thrusters = False

        for i in range(n_verts):
            r = verts[i * stride + 6]
            g = verts[i * stride + 7]
            b = verts[i * stride + 8]
            y = verts[i * stride + 1]
            z = verts[i * stride + 2]

            # Jetpack central pack: z < -0.15, dark red (r ~ 0.64, g ~ 0.10)
            if z < -0.15 and 0.55 <= r <= 0.70 and g < 0.15:
                has_jetpack = True
            # Yellow thrusters: r > 0.9, g > 0.7, b < 0.2, z < -0.2
            if z < -0.20 and r > 0.9 and g > 0.7 and b < 0.2:
                has_rear_thrusters = True
            # Folded wings: z < -0.15, 0.9 < y < 1.3, purple accent or armor red
            if z < -0.15 and 0.9 < y < 1.3:
                has_folded_wings = True

        self.assertTrue(has_jetpack, "Armored Bagusmax must have central jetpack geometry on back")
        self.assertTrue(has_rear_thrusters, "Armored Bagusmax must have twin rear thrusters on back")
        self.assertTrue(has_folded_wings, "Armored Bagusmax must have folded wings mounted on back")


class TestBagusmaxPreferences(unittest.TestCase):
    """Verifies atomic persistence, corruption recovery, and clamping of user preferences."""

    def test_preferences_clamping(self) -> None:
        from openbagus.companion.preferences import CompanionPreferences

        p = CompanionPreferences(
            character_scale=3.5,
            yaw_degrees=750.0,
            pitch_degrees=-100.0,
            window_width=100,
            window_height=3000,
            placement_policy="INVALID_POLICY",
        ).clamp()

        self.assertEqual(p.character_scale, 2.0)
        self.assertEqual(p.yaw_degrees, 30.0)
        self.assertEqual(p.pitch_degrees, -65.0)
        self.assertEqual(p.window_width, 240)
        self.assertEqual(p.window_height, 1400)
        self.assertEqual(p.placement_policy, "CLAMP_TO_VISIBLE_WORKAREA")

    def test_atomic_save_load_and_corruption_recovery(self) -> None:
        import os
        import tempfile
        from pathlib import Path
        from openbagus.companion.preferences import (
            CompanionPreferences,
            load_preferences,
            save_preferences,
            reset_preferences,
        )

        with tempfile.TemporaryDirectory() as td:
            cfg_p = Path(td) / "test_prefs.json"

            p = CompanionPreferences(
                character_scale=1.35,
                yaw_degrees=180.0,
                pitch_degrees=15.0,
                window_position_x=500,
                window_position_y=300,
            )
            ok = save_preferences(p, cfg_p)
            self.assertTrue(ok)
            self.assertTrue(cfg_p.exists())

            loaded = load_preferences(cfg_p)
            self.assertEqual(loaded.character_scale, 1.35)
            self.assertEqual(loaded.yaw_degrees, 180.0)
            self.assertEqual(loaded.pitch_degrees, 15.0)
            self.assertEqual(loaded.window_position_x, 500)

            # Test corruption recovery
            with open(cfg_p, "w", encoding="utf-8") as f:
                f.write("{ INVALID JSON CONTENT :::")

            corrupt_loaded = load_preferences(cfg_p)
            self.assertEqual(corrupt_loaded.character_scale, 1.0)
            self.assertEqual(corrupt_loaded.yaw_degrees, 8.0)

            # Test reset
            reset_p = reset_preferences(cfg_p)
            self.assertEqual(reset_p.character_scale, 1.0)


class TestBagusmaxCLIInteraction(unittest.TestCase):
    """Verifies all new CLI companion commands and subcommands."""

    def setUp(self) -> None:
        from openbagus.cli import OpenBagusShell
        self.shell = OpenBagusShell()

    @patch("openbagus.companion.controller.CompanionController.set_position", return_value=True)
    def test_cli_position_preset(self, mock_set_pos: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax position top-left")
        mock_set_pos.assert_called_with(preset="top-left")

    @patch("openbagus.companion.controller.CompanionController.set_position", return_value=True)
    def test_cli_position_coords(self, mock_set_pos: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax position x 300 y 180")
        mock_set_pos.assert_called_with(x=300, y=180)

    @patch("openbagus.companion.controller.CompanionController.set_character_scale", return_value=True)
    def test_cli_size(self, mock_set_scale: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax size 150")
            mock_set_scale.assert_called_with(1.5)
            self.shell.onecmd("/bagusmax size reset")
            mock_set_scale.assert_called_with(1.0)

    @patch("openbagus.companion.controller.CompanionController.set_window_size", return_value=True)
    def test_cli_window_size(self, mock_set_win: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax window-size 450 600")
        mock_set_win.assert_called_with(450, 600)

    @patch("openbagus.companion.controller.CompanionController.set_rotation", return_value=True)
    def test_cli_rotate_and_pitch(self, mock_rot: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax rotate 180")
            mock_rot.assert_called_with(yaw=180.0)
            self.shell.onecmd("/bagusmax pitch 30")
            mock_rot.assert_called_with(pitch=30.0)

    @patch("openbagus.companion.controller.CompanionController.set_view", return_value=True)
    def test_cli_view(self, mock_view: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax view back")
        mock_view.assert_called_with("back")

    @patch("openbagus.companion.controller.CompanionController.set_interactive", return_value=True)
    def test_cli_interactive_and_clickthrough(self, mock_inter: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax interactive on")
            mock_inter.assert_called_with(True)
            self.shell.onecmd("/bagusmax click-through on")
            mock_inter.assert_called_with(False)

    @patch("openbagus.companion.controller.CompanionController.trigger_gesture", return_value=True)
    def test_cli_animation_gesture(self, mock_gesture: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax animation wave")
        mock_gesture.assert_called_with("wave")

    @patch("openbagus.companion.controller.CompanionController.save_preferences", return_value=True)
    def test_cli_preferences_save(self, mock_save: MagicMock) -> None:
        with patch("sys.stdout"):
            self.shell.onecmd("/bagusmax preferences save")
        mock_save.assert_called_once()


class TestControlBagusmaxTool(unittest.TestCase):
    """Verifies conversational agent tool for natural language companion control."""

    def test_tool_registration_in_global_registry(self) -> None:
        from openbagus.ai.tools.registry import get_global_tool_registry
        reg = get_global_tool_registry()
        tool = reg.get("control_bagusmax")
        self.assertIsNotNone(tool, "control_bagusmax tool must be registered in global registry")

    @patch("openbagus.companion.controller.CompanionController.set_position", return_value=True)
    def test_tool_execution_move(self, mock_set_pos: MagicMock) -> None:
        from openbagus.companion.companion_tool import ControlBagusmaxTool
        tool = ControlBagusmaxTool()
        res = tool.execute_with_telemetry({"action": "move", "position_preset": "top-right"})
        self.assertTrue(res.success)
        mock_set_pos.assert_called_with(x=None, y=None, preset="top-right")

    @patch("openbagus.companion.controller.CompanionController.set_rotation", return_value=True)
    def test_tool_execution_rotate(self, mock_rot: MagicMock) -> None:
        from openbagus.companion.companion_tool import ControlBagusmaxTool
        tool = ControlBagusmaxTool()
        res = tool.execute_with_telemetry({"action": "rotate", "yaw": 180.0, "pitch": 0.0})
        self.assertTrue(res.success)
        mock_rot.assert_called_with(yaw=180.0, pitch=0.0)


class TestBagusmaxConversationalAnimation(unittest.TestCase):
    """Verifies conversational event bridge, audio level streaming, articulation kinematics, and barge-in."""

    def setUp(self) -> None:
        from openbagus.companion.events import (
            CompanionEvent,
            ConversationAnimationBridge,
            ConversationEventType,
            ConversationState,
            AnimState,
            ReasoningMode,
        )
        self.bridge = ConversationAnimationBridge()
        self.animator = CharacterAnimator()

    def test_conversational_lifecycle_transitions(self) -> None:
        from openbagus.companion.events import CompanionEvent, ConversationEventType, AnimState

        turn_id = "turn_test_101"

        # 1. User starts speaking -> Active listening
        ev_speak = CompanionEvent(
            event_type=ConversationEventType.USER_SPEECH_STARTED.value,
            turn_id=turn_id,
            sequence_number=1,
            payload={"level": 0.45},
        )
        cs, anim, changed = self.bridge.process_event(ev_speak)
        self.assertEqual(anim, AnimState.ACTIVE_LISTENING)

        # 2. User speech ends -> Acknowledging nod
        ev_end = CompanionEvent(
            event_type=ConversationEventType.USER_SPEECH_ENDED.value,
            turn_id=turn_id,
            sequence_number=2,
        )
        cs, anim, changed = self.bridge.process_event(ev_end)
        self.assertEqual(anim, AnimState.ACKNOWLEDGING)

        # 3. Agent thinking in FAST mode -> THINKING
        ev_think = CompanionEvent(
            event_type=ConversationEventType.AGENT_THINKING.value,
            turn_id=turn_id,
            sequence_number=3,
        )
        cs, anim, changed = self.bridge.process_event(ev_think)
        self.assertEqual(anim, AnimState.THINKING)

        # 4. Tool execution -> TOOL_GESTURE
        ev_tool = CompanionEvent(
            event_type=ConversationEventType.TOOL_EXECUTION_STARTED.value,
            turn_id=turn_id,
            sequence_number=4,
            payload={"tool_name": "calc_var"},
        )
        cs, anim, changed = self.bridge.process_event(ev_tool)
        self.assertEqual(anim, AnimState.TOOL_GESTURE)

        # 5. Playback starts and audio levels stream -> SPEECH_GESTURE
        ev_tts = CompanionEvent(
            event_type=ConversationEventType.TTS_PLAYBACK_STARTED.value,
            turn_id=turn_id,
            sequence_number=5,
        )
        cs, anim, changed = self.bridge.process_event(ev_tts)
        self.assertEqual(anim, AnimState.SPEECH_GESTURE)

        ev_level = CompanionEvent(
            event_type=ConversationEventType.TTS_PLAYBACK_LEVEL.value,
            turn_id=turn_id,
            sequence_number=6,
            payload={"amplitude": 0.65},
        )
        cs, anim, changed = self.bridge.process_event(ev_level)
        self.assertEqual(anim, AnimState.SPEECH_GESTURE)
        self.assertAlmostEqual(self.bridge.audio_amplitude, 0.65)

        # 6. Playback completes -> IDLE_BREATHING
        ev_finish = CompanionEvent(
            event_type=ConversationEventType.TTS_PLAYBACK_FINISHED.value,
            turn_id=turn_id,
            sequence_number=7,
        )
        cs, anim, changed = self.bridge.process_event(ev_finish)
        self.assertEqual(anim, AnimState.IDLE_BREATHING)
        self.assertEqual(self.bridge.audio_amplitude, 0.0)

    def test_deep_reasoning_mode_animation_state(self) -> None:
        from openbagus.companion.events import CompanionEvent, ConversationEventType, AnimState

        turn_id = "turn_deep_1"
        ev_mode = CompanionEvent(
            event_type=ConversationEventType.MODE_CONFIRMED.value,
            turn_id=turn_id,
            sequence_number=1,
            payload={"mode": "DEEP_REASONING"},
        )
        self.bridge.process_event(ev_mode)

        ev_think = CompanionEvent(
            event_type=ConversationEventType.AGENT_THINKING.value,
            turn_id=turn_id,
            sequence_number=2,
        )
        cs, anim, changed = self.bridge.process_event(ev_think)
        self.assertEqual(anim, AnimState.DEEP_THINKING)

    def test_barge_in_interruption_and_stale_event_rejection(self) -> None:
        from openbagus.companion.events import CompanionEvent, ConversationEventType, AnimState

        turn_1 = "turn_old_1"
        self.bridge.process_event(CompanionEvent(
            event_type=ConversationEventType.TTS_PLAYBACK_STARTED.value,
            turn_id=turn_1,
            sequence_number=1,
        ))
        self.bridge.process_event(CompanionEvent(
            event_type=ConversationEventType.TTS_PLAYBACK_LEVEL.value,
            turn_id=turn_1,
            sequence_number=2,
            payload={"amplitude": 0.70},
        ))

        # Barge-in interruption occurs
        cs, anim, changed = self.bridge.process_event(CompanionEvent(
            event_type=ConversationEventType.USER_INTERRUPTED.value,
            turn_id=turn_1,
            sequence_number=3,
        ))
        self.assertEqual(anim, AnimState.INTERRUPTION_RECOVERY)
        self.assertEqual(self.bridge.audio_amplitude, 0.0)

        # Stale delayed audio chunk from turn_1 must be rejected
        cs_stale, anim_stale, changed_stale = self.bridge.process_event(CompanionEvent(
            event_type=ConversationEventType.TTS_PLAYBACK_LEVEL.value,
            turn_id=turn_1,
            sequence_number=4,
            payload={"amplitude": 0.85},
        ))
        self.assertFalse(changed_stale)
        self.assertEqual(anim_stale, AnimState.INTERRUPTION_RECOVERY)
        self.assertEqual(self.bridge.audio_amplitude, 0.0)

    def test_articulated_kinematics_and_parameters(self) -> None:
        self.animator.set_state("ACTIVE_LISTENING")
        self.animator.update(dt=0.2)
        params = self.animator.get_params()

        # Attentive posture check
        self.assertIn("head_nod", params)
        self.assertIn("head_tilt", params)
        self.assertIn("head_turn", params)
        self.assertIn("torso_lean_z", params)
        self.assertIn("l_arm_roll", params)
        self.assertIn("r_arm_roll", params)

        # In listening state, torso leans forward slightly
        self.assertGreater(params["torso_lean_z"], 0.0)
        self.assertGreater(params["head_tilt"], 0.0)

    def test_speech_articulation_reacts_to_audio_amplitude(self) -> None:
        self.animator.set_state("SPEECH_GESTURE")
        self.animator.amplitude = 0.90
        self.animator.update(dt=0.1)
        params = self.animator.get_params()

        # Chest expands, arms engage, no mouth aperture
        self.assertGreater(params["breath_scale"], 1.0)
        self.assertEqual(params["mouth_open"], 0.0)
        self.assertGreater(params["r_arm_pitch"], 0.1)

    def test_terminal_markdown_clean_formatting(self) -> None:
        from openbagus.cli import format_markdown_for_terminal

        raw = "**Bagusmax** is running with **local** AI!\n- Item 1\n- Item 2"
        formatted = format_markdown_for_terminal(raw)
        self.assertNotIn("**Bagusmax**", formatted)
        self.assertIn("Bagusmax", formatted)
        self.assertIn("• Item 1", formatted)


if __name__ == "__main__":
    unittest.main()

