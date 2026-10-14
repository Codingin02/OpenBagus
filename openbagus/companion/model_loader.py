"""High-Performance GLB Model Loader and Articulated Mesh Generator for BAGUSMAX.

Loads Blender-authored production GLB assets (bagusmax_white.glb, bagusmax_armored.glb)
with PBR material parameters (base color, metallic, roughness), extracts discrete articulated parts,
and evaluates real-time rigid pivot transformations for 60 FPS conversational animation.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Any
import numpy as np
import pygltflib

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODELS_DIR = os.path.join(REPO_ROOT, "assets", "models")


@dataclass
class PartGeometry:
    name: str
    positions: np.ndarray  # (N, 3) float32 local positions
    normals: np.ndarray    # (N, 3) float32 local normals
    colors: np.ndarray     # (N, 3) float32 base colors
    materials: np.ndarray  # (N, 2) float32 [metallic, roughness]
    indices: np.ndarray    # (M,) uint32 triangle indices
    pivot: np.ndarray      # (3,) float32 pivot in world coordinates
    is_eyes: np.ndarray    # (N,) bool mask for eye vertices (for blink animation)


class BagusmaxModelAsset:
    """Pre-loaded and cached GLB model asset for one Bagusmax form."""

    def __init__(self, form: str, glb_path: str) -> None:
        self.form = form
        self.glb_path = glb_path
        self.parts: dict[str, PartGeometry] = {}
        self.total_triangles: int = 0
        self.total_vertices: int = 0
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.glb_path):
            raise FileNotFoundError(f"Bagusmax GLB asset not found: {self.glb_path}")

        glb = pygltflib.GLTF2().load(self.glb_path)
        blob = glb.binary_blob()

        def get_accessor_data(acc_id: int) -> np.ndarray:
            acc = glb.accessors[acc_id]
            bv = glb.bufferViews[acc.bufferView]
            offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
            dtype_map = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}
            dtype = dtype_map[acc.componentType]
            shape_map = {"VEC3": 3, "VEC2": 2, "SCALAR": 1, "VEC4": 4}
            n_comp = shape_map.get(acc.type, 1)
            arr = np.frombuffer(blob, dtype=dtype, offset=offset, count=acc.count * n_comp)
            if n_comp > 1:
                arr = arr.reshape(acc.count, n_comp)
            return arr

        materials_cache = []
        for mat in glb.materials:
            pbr = mat.pbrMetallicRoughness
            base_col = np.array(pbr.baseColorFactor[:3], dtype=np.float32) if pbr and pbr.baseColorFactor else np.array([0.9, 0.9, 0.9], dtype=np.float32)
            metal = float(pbr.metallicFactor) if pbr and pbr.metallicFactor is not None else 0.0
            rough = float(pbr.roughnessFactor) if pbr and pbr.roughnessFactor is not None else 0.5
            materials_cache.append((base_col, metal, rough))

        # Standard default pivots in case node translation is None
        default_pivots = {
            "head": np.array([0.0, 1.25, 0.0], dtype=np.float32),
            "torso": np.array([0.0, 0.52, 0.0], dtype=np.float32),
            "arm_l": np.array([-0.38 if "white" in self.form.lower() else -0.44, 1.06 if "white" in self.form.lower() else 1.10, 0.0], dtype=np.float32),
            "arm_r": np.array([0.38 if "white" in self.form.lower() else 0.44, 1.06 if "white" in self.form.lower() else 1.10, 0.0], dtype=np.float32),
            "legs": np.array([0.0, 0.0, 0.0], dtype=np.float32),
            "wings": np.array([0.0, 0.52, 0.0], dtype=np.float32),
        }

        for node in glb.nodes:
            if node.mesh is None:
                continue
            mesh = glb.meshes[node.mesh]
            node_name = node.name.lower()

            part_key = "torso"
            if "head" in node_name:
                part_key = "head"
            elif "arm_l" in node_name:
                part_key = "arm_l"
            elif "arm_r" in node_name:
                part_key = "arm_r"
            elif "leg" in node_name:
                part_key = "legs"
            elif "wing" in node_name:
                part_key = "wings"

            pivot = np.array(node.translation, dtype=np.float32) if node.translation else default_pivots.get(part_key, np.zeros(3, dtype=np.float32))

            part_positions = []
            part_normals = []
            part_colors = []
            part_materials = []
            part_indices = []
            part_is_eyes = []
            vert_offset = 0

            for prim in mesh.primitives:
                pos = get_accessor_data(prim.attributes.POSITION).astype(np.float32)
                norm = get_accessor_data(prim.attributes.NORMAL).astype(np.float32)
                idx = get_accessor_data(prim.indices).astype(np.uint32)

                mat_idx = prim.material if prim.material is not None else 0
                if 0 <= mat_idx < len(materials_cache):
                    base_col, metal, rough = materials_cache[mat_idx]
                else:
                    base_col, metal, rough = np.array([0.9, 0.9, 0.9], dtype=np.float32), 0.0, 0.5

                n_verts = len(pos)
                col_arr = np.tile(base_col, (n_verts, 1))
                mat_arr = np.tile(np.array([metal, rough], dtype=np.float32), (n_verts, 1))

                # Identify eye vertices by dark color
                is_eye = (base_col[0] < 0.05 and base_col[1] < 0.05 and base_col[2] < 0.05)
                eye_mask = np.full(n_verts, is_eye, dtype=bool)

                part_positions.append(pos)
                part_normals.append(norm)
                part_colors.append(col_arr)
                part_materials.append(mat_arr)
                part_indices.append(idx + vert_offset)
                part_is_eyes.append(eye_mask)
                vert_offset += n_verts

            if part_positions:
                merged_pos = np.vstack(part_positions)
                merged_norm = np.vstack(part_normals)
                merged_col = np.vstack(part_colors)
                merged_mat = np.vstack(part_materials)
                merged_idx = np.concatenate(part_indices)
                merged_eyes = np.concatenate(part_is_eyes)

                self.parts[part_key] = PartGeometry(
                    name=part_key,
                    positions=merged_pos,
                    normals=merged_norm,
                    colors=merged_col,
                    materials=merged_mat,
                    indices=merged_idx,
                    pivot=pivot,
                    is_eyes=merged_eyes,
                )
                self.total_vertices += len(merged_pos)
                self.total_triangles += len(merged_idx) // 3


# Cache of loaded models
_MODEL_CACHE: dict[str, BagusmaxModelAsset] = {}


def get_model_asset(form: str) -> BagusmaxModelAsset:
    """Retrieve pre-loaded Bagusmax model asset from cache."""
    clean = "white" if "white" in form.lower() else "armored"
    if clean not in _MODEL_CACHE:
        glb_file = f"bagusmax_{clean}.glb"
        glb_path = os.path.join(MODELS_DIR, glb_file)
        _MODEL_CACHE[clean] = BagusmaxModelAsset(clean, glb_path)
    return _MODEL_CACHE[clean]


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

    Output vertex layout (11 floats per vertex = 44 bytes):
      [0:3] in_position  (vec3)
      [3:6] in_normal    (vec3)
      [6:9] in_color     (vec3)
      [9:11] in_material (vec2: metallic, roughness)
    """
    asset = get_model_asset(form)

    # Extract animation parameters
    head_nod = params.get("head_nod", 0.0)
    head_turn = params.get("head_turn", 0.0)
    head_tilt = params.get("head_tilt", 0.0)
    torso_lean_z = params.get("torso_lean_z", 0.0)
    torso_twist_y = params.get("torso_twist_y", 0.0)
    breath_scale = max(0.85, min(1.25, params.get("breath_scale", 1.0)))
    l_arm_pitch = params.get("l_arm_pitch", 0.0)
    l_arm_roll = params.get("l_arm_roll", 0.0)
    l_arm_yaw = params.get("l_arm_yaw", 0.0)
    r_arm_pitch = params.get("r_arm_pitch", 0.0)
    r_arm_roll = params.get("r_arm_roll", 0.0)
    r_arm_yaw = params.get("r_arm_yaw", 0.0)
    blink = max(0.0, min(1.0, params.get("blink", 0.0)))

    # Compute rotation matrices
    R_head = _euler_rotation_matrix(head_nod, head_turn, head_tilt)
    R_torso = _euler_rotation_matrix(torso_lean_z, torso_twist_y, 0.0)
    R_l_arm = _euler_rotation_matrix(l_arm_pitch, l_arm_yaw, l_arm_roll)
    R_r_arm = _euler_rotation_matrix(r_arm_pitch, r_arm_yaw, r_arm_roll)

    all_verts = []
    all_indices = []
    index_offset = 0

    for part_name, part in asset.parts.items():
        pos = part.positions.copy()
        norm = part.normals.copy()
        pivot = part.pivot

        if part_name == "head":
            # Apply blink squash to eye vertices
            if blink > 0.0 and np.any(part.is_eyes):
                eye_mask = part.is_eyes
                pos[eye_mask, 1] *= (1.0 - blink * 0.85)

            # Rotate around neck pivot
            pos = (pos @ R_head.T) + pivot
            norm = norm @ R_head.T

        elif part_name in ("torso", "wings"):
            # Torso breath expansion (subtle XZ expansion)
            pos[:, 0] *= breath_scale
            pos[:, 2] *= breath_scale
            pos = (pos @ R_torso.T) + pivot
            norm = norm @ R_torso.T

        elif part_name == "arm_l":
            pos = (pos @ R_l_arm.T) + pivot
            norm = norm @ R_l_arm.T

        elif part_name == "arm_r":
            pos = (pos @ R_r_arm.T) + pivot
            norm = norm @ R_r_arm.T

        else:  # legs
            pos = pos + pivot

        # Construct 11-float vertex buffer: [pos(3), norm(3), col(3), mat(2)]
        v_data = np.hstack([pos, norm, part.colors, part.materials]).astype(np.float32)
        all_verts.append(v_data)

        # Append triangle indices with global offset
        all_indices.append(part.indices + index_offset)
        index_offset += len(pos)

    final_vertices = np.vstack(all_verts)
    final_indices = np.concatenate(all_indices)
    return final_vertices, final_indices
