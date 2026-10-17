"""High-Performance glTF/GLB Model Loader for BAGUSMAX Codex Assets.

Loads Blender-authored production GLB assets:
  - Form FAST (WHITE): assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb
  - Form DEEP (ARMORED): assets/bagusmax/runtime/bagusmax_armored_v1_1.glb

Preserves full glTF 2.0 structure without mesh collapsing:
  - White V4.1: 11 meshes, 107,307 vertices, 208,032 triangles, 32 joints, 10 morph targets.
  - Armored V1.1: 130 meshes, 108,304 vertices, 200,782 triangles.
Supports sparse accessors, PBR material parameters, and pre-cached neutral geometry
for zero-latency 60 FPS real-time rendering.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from pathlib import Path
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pygltflib

logger = logging.getLogger(__name__)

# Expected SHA-256 digests for authentic Codex Blender production exports
EXPECTED_WHITE_SHA256 = "9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b"
EXPECTED_ARMORED_SHA256 = "6e65c46e5d5d6256a1a67b497db395ce31a56749205860be0be397f2bb052afb"

WHITE_GLB_FILENAME = "bagusmax_white_anatomy_v4_1.glb"
ARMORED_GLB_FILENAME = "bagusmax_armored_v1_1.glb"


class CodexGLBLoadError(RuntimeError):
    """Raised when an authentic Codex GLB asset fails to locate, verify, or parse."""
    pass


def compute_file_sha256(filepath: str) -> str:
    """Compute lowercase hexadecimal SHA-256 digest of a file in streaming chunks."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest().lower()


def resolve_glb_path(form: str) -> tuple[str, str, str]:
    """Resolve absolute path and expected SHA-256 for requested character form.
    
    Resolution search order:
      1. PyInstaller frozen _MEIPASS bundle
      2. PyInstaller frozen executable directory
      3. openbagus.core.env.get_repo_root()
      4. Repository root relative to this file
      5. Canonical workspace path: E:/Projects/OpenBagus
      6. Current working directory
    
    Returns:
      (clean_form, absolute_path, expected_sha256)
    """
    clean = "white" if "white" in form.lower() else "armored"
    filename = WHITE_GLB_FILENAME if clean == "white" else ARMORED_GLB_FILENAME
    expected_hash = EXPECTED_WHITE_SHA256 if clean == "white" else EXPECTED_ARMORED_SHA256

    candidates: list[str] = []

    # 1. PyInstaller frozen temporary bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "assets", "bagusmax", "runtime", filename))

    # 2. PyInstaller frozen executable directory
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "assets", "bagusmax", "runtime", filename))

    # 3. Core repo root resolver
    try:
        from openbagus.core.env import get_repo_root
        candidates.append(str(get_repo_root() / "assets" / "bagusmax" / "runtime" / filename))
    except Exception:
        pass

    # 4. Relative to model_loader.py (openbagus/companion -> repo root)
    rel_repo = Path(__file__).resolve().parents[2]
    candidates.append(str(rel_repo / "assets" / "bagusmax" / "runtime" / filename))

    # 5. Canonical project path
    candidates.append(os.path.abspath(os.path.join("E:/Projects/OpenBagus", "assets", "bagusmax", "runtime", filename)))

    # 6. Current working directory
    candidates.append(os.path.abspath(os.path.join(os.getcwd(), "assets", "bagusmax", "runtime", filename)))

    for path in candidates:
        if os.path.isfile(path):
            return clean, os.path.abspath(path), expected_hash

    raise CodexGLBLoadError(
        f"CODEX_GLB_LOAD_FAILED: {filename} not found in any candidate path: {candidates}"
    )


def decode_accessor(glb: pygltflib.GLTF2, blob: bytes, acc_id: int | None) -> np.ndarray | None:
    """Decode a glTF accessor bufferView, handling sparse accessors for morph targets."""
    if acc_id is None:
        return None

    acc = glb.accessors[acc_id]
    dtype_map = {
        5126: np.float32,
        5123: np.uint16,
        5125: np.uint32,
        5121: np.uint8,
        5120: np.int8,
        5122: np.int16,
    }
    shape_map = {"VEC3": 3, "VEC2": 2, "SCALAR": 1, "VEC4": 4, "MAT4": (4, 4)}
    n_comp = shape_map.get(acc.type, 1)
    comp_size = n_comp if isinstance(n_comp, int) else (n_comp[0] * n_comp[1])
    dtype = dtype_map[acc.componentType]

    if acc.bufferView is not None:
        bv = glb.bufferViews[acc.bufferView]
        offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
        base = np.frombuffer(blob, dtype=dtype, offset=offset, count=acc.count * comp_size).copy()
        if isinstance(n_comp, int) and n_comp > 1:
            base = base.reshape((acc.count, n_comp))
        elif isinstance(n_comp, tuple):
            base = base.reshape((acc.count, n_comp[1], n_comp[0]))  # column-major
    else:
        shape = (acc.count, n_comp) if isinstance(n_comp, int) and n_comp > 1 else (acc.count,)
        base = np.zeros(shape, dtype=dtype)

    # Apply glTF sparse accessors (used by Blender for morph targets deltas)
    if acc.sparse is not None:
        sp = acc.sparse
        idx_bv = glb.bufferViews[sp.indices.bufferView]
        idx_offset = (idx_bv.byteOffset or 0) + (sp.indices.byteOffset or 0)
        idx_dtype = dtype_map[sp.indices.componentType]
        indices = np.frombuffer(blob, dtype=idx_dtype, offset=idx_offset, count=sp.count)

        val_bv = glb.bufferViews[sp.values.bufferView]
        val_offset = (val_bv.byteOffset or 0) + (sp.values.byteOffset or 0)
        values = np.frombuffer(blob, dtype=dtype, offset=val_offset, count=sp.count * comp_size)
        if isinstance(n_comp, int) and n_comp > 1:
            values = values.reshape((sp.count, n_comp))
        base[indices] = values

    return base


@dataclass
class PrimitiveData:
    mesh_name: str
    node_name: str
    positions: np.ndarray          # (N, 3) float32
    normals: np.ndarray            # (N, 3) float32
    colors: np.ndarray             # (N, 3) float32
    materials: np.ndarray          # (N, 2) float32 [metallic, roughness]
    indices: np.ndarray            # (M,) uint32
    joints: np.ndarray | None      # (N, 4) uint16 or None
    weights: np.ndarray | None     # (N, 4) float32 or None
    targets_pos: list[np.ndarray] = field(default_factory=list)  # list of (N, 3) float32
    targets_norm: list[np.ndarray] = field(default_factory=list) # list of (N, 3) float32
    is_eyes: np.ndarray | None = None  # (N,) bool
    world_matrix: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float32))


class BagusmaxModelAsset:
    """Loaded and verified authentic Codex Blender glTF asset."""

    def __init__(self, form: str) -> None:
        clean, glb_path, expected_hash = resolve_glb_path(form)
        self.form = clean
        self.glb_path = glb_path
        self.expected_hash = expected_hash
        self.actual_hash = compute_file_sha256(glb_path)

        if self.actual_hash != self.expected_hash:
            raise CodexGLBLoadError(
                f"CODEX_GLB_LOAD_FAILED: SHA256 checksum mismatch for {glb_path}!\n"
                f"  Actual:   {self.actual_hash}\n"
                f"  Expected: {self.expected_hash}"
            )

        self.primitives: list[PrimitiveData] = []
        self.total_vertices: int = 0
        self.total_triangles: int = 0
        self.mesh_names: list[str] = []
        self.joints_count: int = 0
        self.morph_targets_count: int = 0
        self.inv_bind_matrices: np.ndarray | None = None
        self.joint_node_indices: list[int] = []
        self.joint_names: list[str] = []

        # Pre-computed cached neutral buffers for 60 FPS zero-latency rendering
        self._neutral_vdata: np.ndarray | None = None
        self._neutral_idata: np.ndarray | None = None
        self._eye_vert_mask: np.ndarray | None = None
        self._head_vert_mask: np.ndarray | None = None
        self._neck_pivot: np.ndarray = np.array([0.0, 1.37, 0.0], dtype=np.float32)

        self._load()

    def _load(self) -> None:
        logger.info("Loading authentic Codex GLB asset: %s (form=%s)", self.glb_path, self.form)
        glb = pygltflib.GLTF2().load(self.glb_path)
        blob = glb.binary_blob()

        # 1. Decode materials
        materials_cache: list[tuple[np.ndarray, float, float]] = []
        for mat in glb.materials:
            pbr = mat.pbrMetallicRoughness
            base_col = (
                np.array(pbr.baseColorFactor[:3], dtype=np.float32)
                if pbr and pbr.baseColorFactor
                else np.array([0.9, 0.9, 0.9], dtype=np.float32)
            )
            metal = float(pbr.metallicFactor) if pbr and pbr.metallicFactor is not None else 0.0
            rough = float(pbr.roughnessFactor) if pbr and pbr.roughnessFactor is not None else 0.5
            materials_cache.append((base_col, metal, rough))

        # 2. Decode skins
        if glb.skins:
            skin = glb.skins[0]
            self.joints_count = len(skin.joints)
            self.joint_node_indices = list(skin.joints)
            self.joint_names = [glb.nodes[j].name for j in skin.joints]
            raw_inv = decode_accessor(glb, blob, skin.inverseBindMatrices)
            if raw_inv is not None:
                self.inv_bind_matrices = np.array([m.T for m in raw_inv], dtype=np.float32)
                # Compute rest neck pivot if Neck joint exists in skeleton
                if "Neck" in self.joint_names:
                    neck_idx = self.joint_names.index("Neck")
                    try:
                        self._neck_pivot = np.linalg.inv(self.inv_bind_matrices[neck_idx])[:3, 3]
                    except Exception:
                        self._neck_pivot = np.array([0.0, 1.37, 0.0], dtype=np.float32)

        # Helper to compute local node transform
        def get_node_local_transform(node: pygltflib.Node) -> np.ndarray:
            T = np.eye(4, dtype=np.float32)
            if node.translation:
                T[:3, 3] = node.translation
            R = np.eye(4, dtype=np.float32)
            if node.rotation:
                qx, qy, qz, qw = node.rotation
                R[:3, :3] = np.array([
                    [1 - 2*qy*qy - 2*qz*qz, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
                    [2*qx*qy + 2*qz*qw, 1 - 2*qx*qx - 2*qz*qz, 2*qy*qz - 2*qx*qw],
                    [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx*qx - 2*qy*qy]
                ], dtype=np.float32)
            S = np.eye(4, dtype=np.float32)
            if node.scale:
                S[0, 0], S[1, 1], S[2, 2] = node.scale
            return T @ R @ S

        # Traverse node hierarchy to accumulate world matrices for rigid nodes
        node_world_transforms: dict[int, np.ndarray] = {}

        def traverse_node(node_idx: int, parent_mat: np.ndarray) -> None:
            node = glb.nodes[node_idx]
            local_m = get_node_local_transform(node)
            world_m = parent_mat @ local_m
            node_world_transforms[node_idx] = world_m
            if node.children:
                for c in node.children:
                    traverse_node(c, world_m)

        scene = glb.scenes[glb.scene or 0]
        for root_n in scene.nodes:
            traverse_node(root_n, np.eye(4, dtype=np.float32))

        # 3. Decode all meshes and primitives without collapsing
        for node_idx, node in enumerate(glb.nodes):
            if node.mesh is None:
                continue
            mesh = glb.meshes[node.mesh]
            self.mesh_names.append(mesh.name)
            node_world = node_world_transforms.get(node_idx, np.eye(4, dtype=np.float32))

            for prim in mesh.primitives:
                pos = decode_accessor(glb, blob, prim.attributes.POSITION).astype(np.float32)
                norm = decode_accessor(glb, blob, prim.attributes.NORMAL).astype(np.float32)
                idx = decode_accessor(glb, blob, prim.indices).astype(np.uint32)

                # Materials & Vertex Colors
                mat_idx = prim.material if prim.material is not None else 0
                if 0 <= mat_idx < len(materials_cache):
                    base_col, metal, rough = materials_cache[mat_idx]
                else:
                    base_col, metal, rough = np.array([0.9, 0.9, 0.9], dtype=np.float32), 0.0, 0.5

                n_verts = len(pos)
                if prim.attributes.COLOR_0 is not None:
                    raw_c = decode_accessor(glb, blob, prim.attributes.COLOR_0)
                    vert_colors = raw_c[:, :3].astype(np.float32) if raw_c.ndim > 1 else np.tile(base_col, (n_verts, 1))
                else:
                    vert_colors = np.tile(base_col, (n_verts, 1)).astype(np.float32)

                mat_arr = np.tile(np.array([metal, rough], dtype=np.float32), (n_verts, 1))

                # Skinning
                joints = decode_accessor(glb, blob, prim.attributes.JOINTS_0) if prim.attributes.JOINTS_0 is not None else None
                weights = decode_accessor(glb, blob, prim.attributes.WEIGHTS_0) if prim.attributes.WEIGHTS_0 is not None else None
                if weights is not None:
                    w_sum = weights.sum(axis=1, keepdims=True)
                    w_sum[w_sum == 0] = 1.0
                    weights = weights / w_sum

                # Morph targets (deltas)
                t_pos_list = []
                t_norm_list = []
                if prim.targets:
                    self.morph_targets_count = max(self.morph_targets_count, len(prim.targets))
                    for t in prim.targets:
                        t_p_id = t["POSITION"] if isinstance(t, dict) else t.POSITION
                        t_n_id = t["NORMAL"] if isinstance(t, dict) else t.NORMAL
                        t_p = decode_accessor(glb, blob, t_p_id).astype(np.float32) if t_p_id is not None else np.zeros_like(pos)
                        t_n = decode_accessor(glb, blob, t_n_id).astype(np.float32) if t_n_id is not None else np.zeros_like(norm)
                        t_pos_list.append(t_p)
                        t_norm_list.append(t_n)

                # Eye vertices identification
                is_eye = (
                    ("eye" in node.name.lower() or "eye" in mesh.name.lower())
                    or (base_col[0] < 0.05 and base_col[1] < 0.05 and base_col[2] < 0.05 and pos[:, 1].mean() > 1.35)
                )
                eye_mask = np.full(n_verts, is_eye, dtype=bool)

                p_data = PrimitiveData(
                    mesh_name=mesh.name,
                    node_name=node.name,
                    positions=pos,
                    normals=norm,
                    colors=vert_colors,
                    materials=mat_arr,
                    indices=idx,
                    joints=joints,
                    weights=weights,
                    targets_pos=t_pos_list,
                    targets_norm=t_norm_list,
                    is_eyes=eye_mask,
                    world_matrix=node_world,
                )
                self.primitives.append(p_data)
                self.total_vertices += n_verts
                self.total_triangles += len(idx) // 3

        logger.info(
            "Codex GLB %s successfully loaded: %d verts, %d tris, %d meshes, %d joints, %d morphs",
            self.glb_path,
            self.total_vertices,
            self.total_triangles,
            len(self.mesh_names),
            self.joints_count,
            self.morph_targets_count,
        )

        self._build_neutral_buffers()

    def _build_neutral_buffers(self) -> None:
        """Construct concatenated neutral vertex and index buffers at rest pose."""
        all_v = []
        all_i = []
        all_eyes = []
        all_heads = []
        v_offset = 0

        for p in self.primitives:
            # For unskinned/rigid nodes, apply node world transform
            if p.weights is None:
                pos_h = np.hstack([p.positions, np.ones((len(p.positions), 1), dtype=np.float32)])
                pos = (pos_h @ p.world_matrix.T)[:, :3]
                norm = p.normals @ p.world_matrix[:3, :3].T
                norm_len = np.linalg.norm(norm, axis=1, keepdims=True)
                norm_len[norm_len == 0] = 1.0
                norm = norm / norm_len
            else:
                pos = p.positions.copy()
                norm = p.normals.copy()

            v_comb = np.hstack([pos, norm, p.colors, p.materials]).astype(np.float32)
            all_v.append(v_comb)
            all_i.append(p.indices + v_offset)

            # Eye vertices
            if p.is_eyes is not None:
                all_eyes.append(p.is_eyes)
            else:
                all_eyes.append(np.zeros(len(pos), dtype=bool))

            # Head vertices identification for restrained head attention
            name_lower = (p.node_name + " " + p.mesh_name).lower()
            if self.form == "white":
                is_head = p.mesh_name in ("White_Head", "Eye_ContourBridge", "Eye_L", "Eye_R")
            else:
                is_head = any(
                    k in name_lower
                    for k in (
                        "helmet",
                        "visor",
                        "chin",
                        "crown",
                        "ear_l",
                        "ear_r",
                        "fin_l",
                        "fin_r",
                        "gasket",
                        "face_frame",
                    )
                ) or (pos[:, 1].min() > 1.35 and p.weights is None and "arm" not in name_lower)

            head_mask = np.full(len(pos), is_head, dtype=bool)
            all_heads.append(head_mask)

            v_offset += len(pos)

        self._neutral_vdata = np.vstack(all_v)
        self._neutral_idata = np.concatenate(all_i)
        self._eye_vert_mask = np.concatenate(all_eyes)
        self._head_vert_mask = np.concatenate(all_heads)


# Model cache for runtime reuse
_MODEL_CACHE: dict[str, BagusmaxModelAsset] = {}


def get_model_asset(form: str) -> BagusmaxModelAsset:
    """Retrieve or load cached authentic Bagusmax model asset."""
    clean = "white" if "white" in form.lower() else "armored"
    if clean not in _MODEL_CACHE:
        _MODEL_CACHE[clean] = BagusmaxModelAsset(clean)
    return _MODEL_CACHE[clean]


def get_asset_diagnostics(form: str = "white") -> dict[str, Any]:
    """Provide verified runtime diagnostics for the active Codex GLB asset."""
    asset = get_model_asset(form)
    return {
        "model_source": "CODEX_GLB",
        "form": asset.form.upper(),
        "asset_filename": os.path.basename(asset.glb_path),
        "resolved_asset": asset.glb_path,
        "asset_exists": True,
        "asset_sha256": asset.actual_hash,
        "expected_sha256": asset.expected_hash,
        "sha256_verified": (asset.actual_hash == asset.expected_hash),
        "renderer": "OPENGL",
        "procedural_fallback": "DISABLED",
        "total_vertices": asset.total_vertices,
        "total_triangles": asset.total_triangles,
        "mesh_count": len(asset.mesh_names),
        "mesh_names": asset.mesh_names,
        "joints_count": asset.joints_count,
        "morph_targets_count": asset.morph_targets_count,
    }


def _euler_rotation_matrix(rot_x: float, rot_y: float, rot_z: float) -> np.ndarray:
    """Build 3x3 Euler rotation matrix (YXZ order)."""
    cx, sx = math.cos(rot_x), math.sin(rot_x)
    cy, sy = math.cos(rot_y), math.sin(rot_y)
    cz, sz = math.cos(rot_z), math.sin(rot_z)

    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]], dtype=np.float32)
    Ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float32)
    Rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    return Ry @ Rx @ Rz


def build_articulated_mesh(
    form: str,
    params: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Generate transformed vertex and index buffers for the active frame.

    Applies restrained, safe gestures (breathing, head attention nod/tilt/turn,
    and eye blink) using the authentic Codex glTF joint/mesh structure.

    Output vertex layout (11 floats per vertex = 44 bytes):
      [0:3] in_position  (vec3)
      [3:6] in_normal    (vec3)
      [6:9] in_color     (vec3)
      [9:11] in_material (vec2: metallic, roughness)
    """
    asset = get_model_asset(form)

    head_nod = float(params.get("head_nod", 0.0))
    head_turn = float(params.get("head_turn", 0.0))
    head_tilt = float(params.get("head_tilt", 0.0))
    blink = max(0.0, min(1.0, float(params.get("blink", 0.0))))

    has_head_rot = abs(head_nod) > 1e-4 or abs(head_turn) > 1e-4 or abs(head_tilt) > 1e-4
    has_blink = blink > 1e-4 and asset._eye_vert_mask is not None and np.any(asset._eye_vert_mask)

    # Zero-latency fast path: neutral rest pose (zero copy, returns cached array)
    if not has_head_rot and not has_blink:
        return asset._neutral_vdata, asset._neutral_idata

    vdata = asset._neutral_vdata.copy()

    # 1. Restrained Head Attention (nod, turn, tilt pivoting around authentic Neck joint)
    if has_head_rot and asset._head_vert_mask is not None and np.any(asset._head_vert_mask):
        R_head = _euler_rotation_matrix(head_nod, head_turn, head_tilt)
        mask = asset._head_vert_mask
        p_head = vdata[mask, 0:3]
        vdata[mask, 0:3] = (p_head - asset._neck_pivot) @ R_head.T + asset._neck_pivot
        vdata[mask, 3:6] = vdata[mask, 3:6] @ R_head.T

    # 2. Eye blink squash
    if has_blink:
        eye_mask = asset._eye_vert_mask
        squash = 1.0 - (blink * 0.85)
        # Eye center Y is ~1.46m
        eye_center_y = 1.46
        vdata[eye_mask, 1] = (vdata[eye_mask, 1] - eye_center_y) * squash + eye_center_y

    return vdata, asset._neutral_idata

