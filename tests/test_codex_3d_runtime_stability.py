"""Targeted test suite for CODEX 3D Runtime Stability & GPU Resource Ownership.

Validates:
1. GPU buffer ownership (persistent dynamic VBO, static IBO, VAO, no leaks).
2. Restrained skeletal articulation (head attention pivot at neck Y=1.37m, eye blink squash, rest pose zero-copy).
3. Truthful renderer readiness tracking (context, GLB hash, buffers, first frame).
4. CompanionController handshake integrity (rejection of unowned PID, rejection of incomplete readiness).
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from openbagus.companion.model_loader import (
    build_articulated_mesh,
    get_model_asset,
    _euler_rotation_matrix,
)
from openbagus.companion.renderer import (
    GPUModelBuffers,
    RendererReadiness,
    IPCServer,
    IPC_VERSION,
)
from openbagus.companion.controller import CompanionController, IPC_PORT


class TestCodex3DRuntimeStability(unittest.TestCase):
    """Test suite for 3D runtime stability, buffer persistence, and truthful readiness."""

    def test_euler_rotation_matrix_properties(self):
        """Verify Euler rotation matrix is orthogonal (R @ R.T == I) and det(R) == 1."""
        R = _euler_rotation_matrix(0.1, -0.2, 0.15)
        np.testing.assert_allclose(R @ R.T, np.eye(3, dtype=np.float32), atol=1e-6)
        self.assertAlmostEqual(float(np.linalg.det(R)), 1.0, places=5)

    def test_restrained_head_articulation_white(self):
        """Verify head attention rotates head vertices while leaving lower body unchanged."""
        asset = get_model_asset("white")
        v_neutral, i_neutral = build_articulated_mesh("white", {})

        # Apply head nod (X-rotation)
        v_nod, _ = build_articulated_mesh("white", {"head_nod": 0.2})

        head_mask = asset._head_vert_mask
        self.assertIsNotNone(head_mask)
        self.assertTrue(np.any(head_mask))
        self.assertGreater(np.sum(head_mask), 5000)

        # Head vertices must have moved
        diff_head = np.linalg.norm(v_nod[head_mask, 0:3] - v_neutral[head_mask, 0:3], axis=1)
        self.assertGreater(float(np.max(diff_head)), 0.01)

        # Body/leg vertices (outside head mask) must NOT move
        body_mask = ~head_mask
        diff_body = np.linalg.norm(v_nod[body_mask, 0:3] - v_neutral[body_mask, 0:3], axis=1)
        np.testing.assert_allclose(diff_body, 0.0, atol=1e-6)

    def test_restrained_head_articulation_armored(self):
        """Verify helmet/head rotates for Armored Hero model without moving body/wings."""
        asset = get_model_asset("armored")
        v_neutral, _ = build_articulated_mesh("armored", {})
        v_turn, _ = build_articulated_mesh("armored", {"head_turn": 0.15})

        head_mask = asset._head_vert_mask
        self.assertIsNotNone(head_mask)
        self.assertTrue(np.any(head_mask))

        diff_head = np.linalg.norm(v_turn[head_mask, 0:3] - v_neutral[head_mask, 0:3], axis=1)
        self.assertGreater(float(np.max(diff_head)), 0.005)

        body_mask = ~head_mask
        diff_body = np.linalg.norm(v_turn[body_mask, 0:3] - v_neutral[body_mask, 0:3], axis=1)
        np.testing.assert_allclose(diff_body, 0.0, atol=1e-6)

    def test_zero_latency_neutral_pose_fast_path(self):
        """Verify rest pose returns neutral array reference without unnecessary copy."""
        asset = get_model_asset("white")
        v_data, i_data = build_articulated_mesh("white", {"blink": 0.0, "head_nod": 0.0})
        self.assertIs(v_data, asset._neutral_vdata)
        self.assertIs(i_data, asset._neutral_idata)

    def test_renderer_readiness_lifecycle(self):
        """Verify truthful readiness requires all 4 subsystems operational and no error."""
        r = RendererReadiness()
        self.assertFalse(r.is_fully_ready)

        r.gl_context_operational = True
        self.assertFalse(r.is_fully_ready)

        r.glb_hash_verified = True
        self.assertFalse(r.is_fully_ready)

        r.buffers_created = True
        self.assertFalse(r.is_fully_ready)

        r.first_frame_rendered = True
        self.assertTrue(r.is_fully_ready)

        # An error invalidates readiness immediately
        r.error = "GPU device lost"
        self.assertFalse(r.is_fully_ready)

    def test_gpu_model_buffers_allocation_and_release(self):
        """Verify persistent buffer lifecycle without buffer reallocation."""
        mock_ctx = MagicMock()
        mock_prog = MagicMock()
        mock_vbo = MagicMock()
        mock_ibo = MagicMock()
        mock_vao = MagicMock()

        mock_ctx.buffer.side_effect = [mock_ibo, mock_vbo]
        mock_ctx.vertex_array.return_value = mock_vao

        buffers = GPUModelBuffers(mock_ctx, mock_prog, "white")
        self.assertIs(buffers.vbo, mock_vbo)
        self.assertIs(buffers.ibo, mock_ibo)
        self.assertIs(buffers.vao, mock_vao)

        # Dynamic update on eye blink: writes to existing VBO, NO new buffers allocated
        mock_ctx.buffer.reset_mock()
        mock_ctx.vertex_array.reset_mock()

        buffers.update_if_needed({"blink": 0.8})
        mock_vbo.write.assert_called_once()
        mock_ctx.buffer.assert_not_called()
        mock_ctx.vertex_array.assert_not_called()

        # Repeated unchanged blink: zero writes
        mock_vbo.write.reset_mock()
        buffers.update_if_needed({"blink": 0.8})
        mock_vbo.write.assert_not_called()

        # Return to rest pose: writes neutral pose once
        mock_vbo.write.reset_mock()
        buffers.update_if_needed({"blink": 0.0})
        mock_vbo.write.assert_called_once()

        # Subsequent rest pose frames: zero writes
        mock_vbo.write.reset_mock()
        buffers.update_if_needed({"blink": 0.0})
        mock_vbo.write.assert_not_called()

        # Render calls vao.render()
        buffers.render()
        mock_vao.render.assert_called_once()

        # Explicit release frees all 3 resources
        buffers.release()
        mock_vao.release.assert_called_once()
        mock_vbo.release.assert_called_once()
        mock_ibo.release.assert_called_once()
        self.assertIsNone(buffers.vao)
        self.assertIsNone(buffers.vbo)
        self.assertIsNone(buffers.ibo)

    def test_controller_handshake_rejects_unowned_pid(self):
        """Verify CompanionController strictly rejects connection if port has different PID."""
        controller = CompanionController()
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        controller._process = mock_proc

        mock_sock = MagicMock()
        # Ping response reports foreign PID 1234
        foreign_response = json.dumps({
            "status": "ok",
            "app": "openbagus_companion",
            "pid": 1234,
            "readiness": {"is_fully_ready": True},
        }).encode("utf-8") + b"\n"
        mock_sock.recv.return_value = foreign_response
        controller._sock = mock_sock

        self.assertFalse(controller._verify_handshake())

    def test_controller_handshake_rejects_unready_state(self):
        """Verify CompanionController rejects connection if companion reports not yet ready."""
        controller = CompanionController()
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        controller._process = mock_proc

        mock_sock = MagicMock()
        unready_response = json.dumps({
            "status": "initializing",
            "app": "openbagus_companion",
            "pid": 9999,
            "readiness": {"is_fully_ready": False},
        }).encode("utf-8") + b"\n"
        mock_sock.recv.return_value = unready_response
        controller._sock = mock_sock

        self.assertFalse(controller._verify_handshake())

    def test_controller_handshake_accepts_verified_ready_owned_process(self):
        """Verify CompanionController accepts connection when PID matches and fully ready."""
        controller = CompanionController()
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        controller._process = mock_proc

        mock_sock = MagicMock()
        ready_response = json.dumps({
            "status": "ok",
            "app": "openbagus_companion",
            "pid": 9999,
            "readiness": {"is_fully_ready": True},
        }).encode("utf-8") + b"\n"
        mock_sock.recv.return_value = ready_response
        controller._sock = mock_sock

        self.assertTrue(controller._verify_handshake())


if __name__ == "__main__":
    unittest.main()
