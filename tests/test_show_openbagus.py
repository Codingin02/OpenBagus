"""Acceptance tests for SHOW OPENBAGUS 3D companion character, animator, and controller."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from openbagus.companion.controller import CompanionController, IPC_PORT, IPC_VERSION
from openbagus.companion.renderer import (
    AnimState,
    CharacterAnimator,
    build_character,
)


class TestShowOpenBagusGeometry(unittest.TestCase):
    """Verifies the procedural 3D cartoon plumber companion geometry and styling."""

    def test_character_mesh_generation(self) -> None:
        verts, idxs = build_character(mouth_open=0.0, blink=0.0)
        self.assertGreater(len(verts), 10_000)
        self.assertGreater(len(idxs), 10_000)

        # 9 floats per vertex: px, py, pz, nx, ny, nz, r, g, b
        n_verts = len(verts) // 9
        n_tris = len(idxs) // 3
        self.assertGreaterEqual(n_verts, 5_000)
        self.assertGreaterEqual(n_tris, 10_000)

        # Max index must be within vertex bounds
        max_idx = max(idxs)
        self.assertLess(max_idx, n_verts)

    def test_character_color_palette(self) -> None:
        """Character must feature black cap/shirt, blue overalls, brown boots, white gloves."""
        verts, _ = build_character()
        stride = 9
        n_verts = len(verts) // stride

        has_black = False
        has_blue = False
        has_brown = False
        has_white = False

        for i in range(n_verts):
            r = verts[i * stride + 6]
            g = verts[i * stride + 7]
            b = verts[i * stride + 8]

            # Black: r,g,b <= 0.1
            if r <= 0.1 and g <= 0.1 and b <= 0.1:
                has_black = True
            # Blue: b > 0.6 and r < 0.3
            elif b > 0.6 and r < 0.3 and g < 0.4:
                has_blue = True
            # Brown: r > 0.3, g < 0.3, b < 0.15
            elif r > 0.3 and g < 0.3 and b < 0.15:
                has_brown = True
            # White: r,g,b >= 0.9
            elif r >= 0.9 and g >= 0.9 and b >= 0.9:
                has_white = True

        self.assertTrue(has_black, "Character must have black clothing/cap")
        self.assertTrue(has_blue, "Character must have blue overalls")
        self.assertTrue(has_brown, "Character must have brown boots")
        self.assertTrue(has_white, "Character must have white gloves / emblem plate")

    def test_mouth_open_lip_sync_variation(self) -> None:
        """Mouth geometry must change when mouth_open parameter varies."""
        verts_closed, _ = build_character(mouth_open=0.0)
        verts_open, _ = build_character(mouth_open=1.0)
        # Coordinates must differ due to lip-sync mouth aperture
        self.assertNotEqual(verts_closed, verts_open)

    def test_blink_variation(self) -> None:
        """Eyelid geometry must change when blink parameter varies."""
        verts_open, _ = build_character(blink=0.0)
        verts_blink, _ = build_character(blink=1.0)
        self.assertNotEqual(verts_open, verts_blink)


class TestCharacterAnimator(unittest.TestCase):
    """Verifies animation states and parameter transitions."""

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

    def test_animator_tick(self) -> None:
        self.animator.set_state(AnimState.THINKING)
        self.animator.update(dt=0.1)
        self.assertGreater(self.animator.elapsed, 0.0)


class TestCompanionController(unittest.TestCase):
    """Verifies controller singleton, status reporting, and IPC command generation."""

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
        self.assertIn("ipc_address", st)
        self.assertEqual(st["ipc_version"], IPC_VERSION)
        self.assertEqual(st["ipc_address"], f"127.0.0.1:{IPC_PORT}")

    def test_state_change_does_not_crash_when_offline(self) -> None:
        # If renderer subprocess is not running, set_state must return False gracefully
        res = self.controller.set_state("LISTENING")
        self.assertIsInstance(res, bool)

    def test_amplitude_does_not_crash_when_offline(self) -> None:
        res = self.controller.speak_amplitude(0.75)
        self.assertIsInstance(res, bool)


if __name__ == "__main__":
    unittest.main()
