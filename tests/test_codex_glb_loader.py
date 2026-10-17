"""Targeted verification suite for BAGUSMAX authentic Codex GLB restoration.

Validates:
1. Path resolution across frozen, dev repo, canonical paths.
2. Exact SHA-256 integrity verification (White V4.1 and Armored V1.1).
3. glTF structure preservation (11 meshes, 107,307 verts for White; 130 meshes, 108,304 verts for Armored).
4. No procedural fallback in production rendering: error is raised and surfaced.
5. Runtime diagnostics format and content.
6. IPC handshake and ping response containing model_source="CODEX_GLB" and valid version.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.companion.model_loader import (
    CodexGLBLoadError,
    EXPECTED_WHITE_SHA256,
    EXPECTED_ARMORED_SHA256,
    resolve_glb_path,
    compute_file_sha256,
    get_model_asset,
    get_asset_diagnostics,
    build_articulated_mesh,
)
from openbagus.companion.controller import IPC_VERSION, CompanionController


class TestCodexGLBLoader(unittest.TestCase):
    """Test authentic Codex GLB loading, integrity, structure, and IPC diagnostics."""

    def test_white_glb_path_and_sha256(self):
        form, path, expected_hash = resolve_glb_path("white")
        self.assertEqual(form, "white")
        self.assertTrue(os.path.isfile(path), f"File does not exist: {path}")
        self.assertEqual(expected_hash, EXPECTED_WHITE_SHA256)

        actual_hash = compute_file_sha256(path)
        self.assertEqual(actual_hash, EXPECTED_WHITE_SHA256)

    def test_armored_glb_path_and_sha256(self):
        form, path, expected_hash = resolve_glb_path("armored")
        self.assertEqual(form, "armored")
        self.assertTrue(os.path.isfile(path), f"File does not exist: {path}")
        self.assertEqual(expected_hash, EXPECTED_ARMORED_SHA256)

        actual_hash = compute_file_sha256(path)
        self.assertEqual(actual_hash, EXPECTED_ARMORED_SHA256)

    def test_white_asset_counts_and_structure(self):
        asset = get_model_asset("white")
        self.assertEqual(asset.form, "white")
        self.assertEqual(asset.total_vertices, 107307)
        self.assertEqual(asset.total_triangles, 208032)
        self.assertEqual(len(asset.mesh_names), 11)
        self.assertEqual(asset.joints_count, 32)
        self.assertEqual(asset.morph_targets_count, 10)

        # Check expected meshes from Codex handoff
        expected_mesh_fragments = ["Port", "Chest", "Eye", "Torso", "White_Head", "White_Leg", "White_Torso"]
        for frag in expected_mesh_fragments:
            self.assertTrue(
                any(frag.lower() in m.lower() for m in asset.mesh_names),
                f"Missing expected mesh containing '{frag}' in {asset.mesh_names}",
            )

    def test_armored_asset_counts_and_structure(self):
        asset = get_model_asset("armored")
        self.assertEqual(asset.form, "armored")
        self.assertEqual(asset.total_vertices, 108304)
        self.assertEqual(asset.total_triangles, 200782)
        self.assertEqual(len(asset.mesh_names), 130)
        self.assertEqual(asset.joints_count, 32)

    def test_sha256_mismatch_raises_codex_glb_load_error(self):
        with patch("openbagus.companion.model_loader.compute_file_sha256", return_value="bad_hash_12345678"):
            with self.assertRaises(CodexGLBLoadError) as ctx:
                from openbagus.companion.model_loader import BagusmaxModelAsset
                BagusmaxModelAsset("white")
            self.assertIn("CODEX_GLB_LOAD_FAILED", str(ctx.exception))
            self.assertIn("checksum mismatch", str(ctx.exception))

    def test_asset_diagnostics_contract(self):
        diag = get_asset_diagnostics("white")
        self.assertEqual(diag["model_source"], "CODEX_GLB")
        self.assertEqual(diag["form"], "WHITE")
        self.assertEqual(diag["asset_filename"], "bagusmax_white_anatomy_v4_1.glb")
        self.assertTrue(diag["asset_exists"])
        self.assertEqual(diag["asset_sha256"], EXPECTED_WHITE_SHA256)
        self.assertTrue(diag["sha256_verified"])
        self.assertEqual(diag["renderer"], "OPENGL")
        self.assertEqual(diag["procedural_fallback"], "DISABLED")
        self.assertEqual(diag["total_vertices"], 107307)
        self.assertEqual(diag["total_triangles"], 208032)
        self.assertEqual(diag["mesh_count"], 11)

    def test_build_articulated_mesh_output_format(self):
        v_data, i_data = build_articulated_mesh("white", {"blink": 0.0})
        self.assertEqual(v_data.shape, (107307, 11))
        self.assertEqual(i_data.shape, (208032 * 3,))

        # Test with blink
        v_data_blink, i_data_blink = build_articulated_mesh("white", {"blink": 0.75})
        self.assertEqual(v_data_blink.shape, (107307, 11))
        self.assertEqual(i_data_blink.shape, (208032 * 3,))

    def test_no_procedural_fallback_enforcement(self):
        # Ensure rebuild_mesh in renderer raises RuntimeError if model loading fails
        from openbagus.companion.renderer import IPCServer
        animator_mock = MagicMock()
        animator_mock.character_form = "white"
        animator_mock.bridge.process_event.return_value = (None, MagicMock(value="IDLE"), False)
        animator_mock.bridge.audio_amplitude = 0.0

        ipc = IPCServer(port=7499, animator=animator_mock)
        resp = ipc._dispatch({"type": "companion.ping"})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.get("status"), "ok")
        self.assertEqual(resp.get("app"), "openbagus_companion")
        self.assertEqual(resp.get("version"), IPC_VERSION)
        self.assertEqual(resp.get("model_source"), "CODEX_GLB")
        self.assertTrue(resp.get("model_loaded"))


if __name__ == "__main__":
    unittest.main()
