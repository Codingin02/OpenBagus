"""SHOW OPENBAGUS — Real-time 3D companion renderer.

Renders an animated 3D cartoon plumber companion using OpenGL (moderngl + glfw).
Character design:
  - Black cap with capital 'B' emblem (white, high-contrast)
  - Black shirt / torso
  - Blue overalls
  - White cartoon gloves
  - Brown cartoon boots
  - Thick moustache, large rounded nose, expressive eyebrows
  - Idle breathing + blinking animations
  - Lip sync via audio amplitude driven mouth open/close

Run as subprocess: python renderer.py --port 7432

IPC: TCP JSON lines on 127.0.0.1:7432
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
import threading
import time
from typing import Any

# Try to import rendering dependencies
try:
    import glfw
    import moderngl
    import numpy as np
    from pyrr import Matrix44, Vector3
    HAS_GL = True
except ImportError as _e:
    HAS_GL = False
    _MISSING = str(_e)


# ---------------------------------------------------------------------------
# Shader programs
# ---------------------------------------------------------------------------

VERT_SHADER = """
#version 330 core
in vec3 in_position;
in vec3 in_normal;
in vec3 in_color;

uniform mat4 model;
uniform mat4 view;
uniform mat4 proj;

out vec3 v_normal;
out vec3 v_color;
out vec3 v_fragpos;

void main() {
    vec4 world_pos = model * vec4(in_position, 1.0);
    gl_Position = proj * view * world_pos;
    v_fragpos = vec3(world_pos);
    v_normal = mat3(transpose(inverse(model))) * in_normal;
    v_color = in_color;
}
"""

FRAG_SHADER = """
#version 330 core
in vec3 v_normal;
in vec3 v_color;
in vec3 v_fragpos;

uniform vec3 light_pos;
uniform vec3 view_pos;
uniform float ambient_strength;

out vec4 out_color;

void main() {
    vec3 norm = normalize(v_normal);
    vec3 light_dir = normalize(light_pos - v_fragpos);
    vec3 view_dir = normalize(view_pos - v_fragpos);

    // Warm key light
    float n_dot_l = dot(norm, light_dir);
    // Crisp cartoon cel shading: lit (1.0), shaded (0.68)
    float cel = smoothstep(-0.02, 0.06, n_dot_l) * 0.32 + 0.68;
    vec3 diffuse = cel * v_color;

    // Rim lighting (Fresnel) — soft edge definition for dark fabrics
    float fresnel = 1.0 - max(dot(view_dir, norm), 0.0);
    float rim = smoothstep(0.72, 0.96, fresnel) * 0.30;
    vec3 rim_color = vec3(0.55, 0.65, 0.85);

    // Subtle fill light from lower opposite side
    vec3 fill_dir = normalize(vec3(-1.5, -1.0, 1.5));
    float fill_dot = max(dot(norm, fill_dir), 0.0) * 0.12;
    vec3 fill = fill_dot * v_color;

    vec3 ambient = (ambient_strength > 0.0 ? ambient_strength * 0.08 : 0.0) * v_color;

    vec3 result = diffuse + fill + ambient + (rim * rim_color * v_color);
    out_color = vec4(result, 1.0);
}
"""

# ---------------------------------------------------------------------------
# 3D geometry helpers
# ---------------------------------------------------------------------------

def _make_sphere(
    cx: float, cy: float, cz: float,
    rx: float, ry: float, rz: float,
    color: tuple[float, float, float],
    lat: int = 14, lon: int = 20,
) -> tuple[list[float], list[int]]:
    """Generate ellipsoid vertices (pos + normal + color) and triangle indices."""
    verts: list[float] = []
    idxs: list[int] = []
    base = 0

    for i in range(lat + 1):
        theta = math.pi * i / lat  # 0 to pi
        for j in range(lon + 1):
            phi = 2 * math.pi * j / lon
            nx = math.sin(theta) * math.cos(phi)
            ny = math.cos(theta)
            nz = math.sin(theta) * math.sin(phi)
            verts.extend([cx + rx * nx, cy + ry * ny, cz + rz * nz,
                           nx, ny, nz, *color])

    for i in range(lat):
        for j in range(lon):
            a = base + i * (lon + 1) + j
            b = a + 1
            c = a + (lon + 1)
            d = c + 1
            idxs.extend([a, c, b, b, c, d])

    return verts, idxs


def _make_cylinder(
    cx: float, cy_bot: float, cy_top: float, cz: float,
    rx: float, rz: float,
    color: tuple[float, float, float],
    segs: int = 18,
) -> tuple[list[float], list[int]]:
    """Generate cylinder vertices and indices."""
    verts: list[float] = []
    idxs: list[int] = []

    # Side wall
    base = 0
    for i in range(segs + 1):
        angle = 2 * math.pi * i / segs
        nx = math.cos(angle)
        nz = math.sin(angle)
        x = cx + rx * nx
        z = cz + rz * nz
        verts.extend([x, cy_bot, z,  nx, 0.0, nz, *color])
        verts.extend([x, cy_top, z,  nx, 0.0, nz, *color])

    for i in range(segs):
        a = base + i * 2
        b = a + 1
        c = a + 2
        d = a + 3
        idxs.extend([a, b, c, b, d, c])

    # Top cap
    cap_center = len(verts) // 9
    verts.extend([cx, cy_top, cz,  0.0, 1.0, 0.0, *color])
    ring_start = base
    for i in range(segs):
        a = ring_start + i * 2 + 1  # top ring vertex index
        b = ring_start + (i + 1) % segs * 2 + 1
        idxs.extend([cap_center, a, b])

    # Bot cap
    bot_center = len(verts) // 9
    verts.extend([cx, cy_bot, cz,  0.0, -1.0, 0.0, *color])
    for i in range(segs):
        a = ring_start + i * 2  # bot ring
        b = ring_start + (i + 1) % segs * 2
        idxs.extend([bot_center, b, a])

    return verts, idxs


def _make_box(
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
    color: tuple[float, float, float],
) -> tuple[list[float], list[int]]:
    """Generate box vertices and indices."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    corners = [
        (cx - hx, cy - hy, cz - hz),
        (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz),
        (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz),
        (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz),
        (cx - hx, cy + hy, cz + hz),
    ]
    faces = [
        ([0, 1, 2, 3], (0, 0, -1)),  # front
        ([5, 4, 7, 6], (0, 0, 1)),   # back
        ([4, 0, 3, 7], (-1, 0, 0)),  # left
        ([1, 5, 6, 2], (1, 0, 0)),   # right
        ([3, 2, 6, 7], (0, 1, 0)),   # top
        ([0, 4, 5, 1], (0, -1, 0)),  # bottom
    ]
    verts: list[float] = []
    idxs: list[int] = []
    base = 0
    for fi, (f_idx, nrm) in enumerate(faces):
        for vi in f_idx:
            verts.extend([*corners[vi], *nrm, *color])
        b = base + fi * 4
        idxs.extend([b, b + 1, b + 2, b, b + 2, b + 3])

    return verts, idxs


def _make_torus(
    cx: float, cy: float, cz: float,
    R: float, r: float,
    color: tuple[float, float, float],
    segs_R: int = 16, segs_r: int = 10,
    angle_start: float = 0.0, angle_end: float = 2 * math.pi,
    axis: str = "y",
) -> tuple[list[float], list[int]]:
    """Generate torus or curved torus-arc vertices and indices."""
    verts: list[float] = []
    idxs: list[int] = []
    is_closed = abs(angle_end - angle_start - 2 * math.pi) < 1e-4

    n_rings = segs_R if is_closed else segs_R + 1
    for i in range(n_rings):
        u = angle_start + (angle_end - angle_start) * i / segs_R
        cos_u = math.cos(u)
        sin_u = math.sin(u)
        for j in range(segs_r + 1):
            v = 2 * math.pi * j / segs_r
            cos_v = math.cos(v)
            sin_v = math.sin(v)

            if axis == "y":
                px = cx + (R + r * cos_v) * cos_u
                py = cy + r * sin_v
                pz = cz + (R + r * cos_v) * sin_u
                nx = cos_v * cos_u
                ny = sin_v
                nz = cos_v * sin_u
            elif axis == "z":
                px = cx + (R + r * cos_v) * cos_u
                py = cy + (R + r * cos_v) * sin_u
                pz = cz + r * sin_v
                nx = cos_v * cos_u
                ny = cos_v * sin_u
                nz = sin_v
            else:
                px = cx + r * sin_v
                py = cy + (R + r * cos_v) * cos_u
                pz = cz + (R + r * cos_v) * sin_u
                nx = sin_v
                ny = cos_v * cos_u
                nz = cos_v * sin_u

            verts.extend([px, py, pz, nx, ny, nz, *color])

    for i in range(segs_R):
        i_next = (i + 1) % n_rings if is_closed else i + 1
        for j in range(segs_r):
            a = i * (segs_r + 1) + j
            b = a + 1
            c = i_next * (segs_r + 1) + j
            d = c + 1
            idxs.extend([a, c, b, b, c, d])

    return verts, idxs


def _merge(*meshes: tuple[list[float], list[int]]) -> tuple[list[float], list[int]]:
    all_verts: list[float] = []
    all_idxs: list[int] = []
    offset = 0
    stride = 9  # 3 pos + 3 norm + 3 color
    for verts, idxs in meshes:
        n_verts = len(verts) // stride
        all_verts.extend(verts)
        all_idxs.extend(i + offset for i in idxs)
        offset += n_verts
    return all_verts, all_idxs


# ---------------------------------------------------------------------------
# Character geometry builder: Classic Super Mario (Black Cap & Shirt, B Emblem)
# ---------------------------------------------------------------------------

def build_character(mouth_open: float = 0.0, blink: float = 0.0) -> tuple[list[float], list[int]]:
    """Build the high-fidelity SHOW OPENBAGUS 3D companion character.

    Features:
        - Classic Super Mario facial anatomy: big bulbous nose, signature 6-scallop curved moustache,
          expressive oval blue eyes with glints, rounded cheeks with blush, arched dark brows.
        - Cap: Black cartoon baker's cap with forward curved visor and circular white front badge.
        - Emblem: Crisp, high-contrast capital 'B' on the white badge (never M or ambiguous shapes).
        - Clothing: Black shirt, classic denim-blue overalls with shoulder straps and TWO BRIGHT YELLOW BUTTONS.
        - Accessories: White cartoon gloves with flared wrist cuffs, oversized brown boots with dark soles.
        - Dynamic features: Audio-driven mouth open (lip sync) and eyelid blink deformation.
    """
    BLACK      = (0.07, 0.07, 0.08)
    BLUE       = (0.10, 0.28, 0.75)
    SKIN       = (0.98, 0.75, 0.58)
    BLUSH      = (0.96, 0.68, 0.55)
    WHITE      = (0.96, 0.96, 0.96)
    YELLOW     = (0.98, 0.82, 0.10)
    BROWN      = (0.42, 0.22, 0.08)
    DARK_BROWN = (0.16, 0.10, 0.06)
    IRIS_BLUE  = (0.10, 0.45, 0.88)
    PUPIL      = (0.04, 0.04, 0.04)
    MOUTH_DARK = (0.18, 0.04, 0.04)
    TONGUE_RED = (0.85, 0.25, 0.25)
    GLINT      = (1.00, 1.00, 1.00)

    meshes: list[tuple[list[float], list[int]]] = []

    # =========================================================================
    # 1. HEAD & CHUBBY CHEEKS (Seated at y = 1.25)
    # =========================================================================
    # Main head sphere
    meshes.append(_make_sphere(0.0, 1.25, 0.0, 0.35, 0.34, 0.33, SKIN, lat=16, lon=24))

    # Chubby cheeks
    meshes.append(_make_sphere(-0.18, 1.20, 0.16, 0.15, 0.13, 0.15, BLUSH, lat=12, lon=18))
    meshes.append(_make_sphere(0.18, 1.20, 0.16, 0.15, 0.13, 0.15, BLUSH, lat=12, lon=18))

    # Round chin
    meshes.append(_make_sphere(0.0, 1.06, 0.18, 0.12, 0.09, 0.12, SKIN, lat=10, lon=16))

    # Big bulbous round cartoon nose
    meshes.append(_make_sphere(0.0, 1.24, 0.31, 0.125, 0.115, 0.110, SKIN, lat=14, lon=20))

    # Ears (placed realistically on sides of head)
    meshes.append(_make_sphere(-0.35, 1.24, -0.02, 0.050, 0.070, 0.055, SKIN, lat=10, lon=14))
    meshes.append(_make_sphere(0.35, 1.24, -0.02, 0.050, 0.070, 0.055, SKIN, lat=10, lon=14))
    meshes.append(_make_sphere(-0.345, 1.24, -0.01, 0.030, 0.045, 0.030, (0.86, 0.62, 0.46), lat=8, lon=12))
    meshes.append(_make_sphere(0.345, 1.24, -0.01, 0.030, 0.045, 0.030, (0.86, 0.62, 0.46), lat=8, lon=12))

    # Sideburns & back hair
    meshes.append(_make_sphere(-0.31, 1.27, 0.05, 0.045, 0.070, 0.050, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(0.31, 1.27, 0.05, 0.045, 0.070, 0.050, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(0.0, 1.14, -0.25, 0.18, 0.12, 0.12, DARK_BROWN, lat=8, lon=14))
    meshes.append(_make_sphere(-0.16, 1.13, -0.22, 0.13, 0.10, 0.12, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(0.16, 1.13, -0.22, 0.13, 0.10, 0.12, DARK_BROWN, lat=8, lon=12))

    # =========================================================================
    # 2. SIGNATURE 6-SCALLOP MARIO MOUSTACHE
    # =========================================================================
    meshes.append(_make_sphere(0.0, 1.17, 0.32, 0.080, 0.048, 0.055, DARK_BROWN, lat=10, lon=16))
    # Left scallops
    meshes.append(_make_sphere(-0.075, 1.14, 0.310, 0.060, 0.050, 0.055, DARK_BROWN, lat=10, lon=14))
    meshes.append(_make_sphere(-0.145, 1.16, 0.280, 0.065, 0.055, 0.055, DARK_BROWN, lat=10, lon=14))
    meshes.append(_make_sphere(-0.210, 1.19, 0.235, 0.058, 0.050, 0.045, DARK_BROWN, lat=10, lon=14))
    # Right scallops
    meshes.append(_make_sphere(0.075, 1.14, 0.310, 0.060, 0.050, 0.055, DARK_BROWN, lat=10, lon=14))
    meshes.append(_make_sphere(0.145, 1.16, 0.280, 0.065, 0.055, 0.055, DARK_BROWN, lat=10, lon=14))
    meshes.append(_make_sphere(0.210, 1.19, 0.235, 0.058, 0.050, 0.045, DARK_BROWN, lat=10, lon=14))
    # Back fill to face
    meshes.append(_make_sphere(-0.10, 1.16, 0.25, 0.09, 0.05, 0.06, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(0.10, 1.16, 0.25, 0.09, 0.05, 0.06, DARK_BROWN, lat=8, lon=12))

    # =========================================================================
    # 3. EYES, CURVED EYEBROWS & MOUTH
    # =========================================================================
    # Eye whites
    meshes.append(_make_sphere(-0.11, 1.34, 0.26, 0.062, 0.082, 0.050, WHITE, lat=10, lon=16))
    meshes.append(_make_sphere(0.11, 1.34, 0.26, 0.062, 0.082, 0.050, WHITE, lat=10, lon=16))
    # Blue irises
    meshes.append(_make_sphere(-0.105, 1.34, 0.300, 0.042, 0.060, 0.022, IRIS_BLUE, lat=8, lon=14))
    meshes.append(_make_sphere(0.105, 1.34, 0.300, 0.042, 0.060, 0.022, IRIS_BLUE, lat=8, lon=14))
    # Pupils
    meshes.append(_make_sphere(-0.105, 1.34, 0.316, 0.025, 0.038, 0.015, PUPIL, lat=6, lon=12))
    meshes.append(_make_sphere(0.105, 1.34, 0.316, 0.025, 0.038, 0.015, PUPIL, lat=6, lon=12))
    # Eye highlights
    meshes.append(_make_sphere(-0.092, 1.362, 0.326, 0.012, 0.016, 0.010, GLINT, lat=5, lon=8))
    meshes.append(_make_sphere(0.118, 1.362, 0.326, 0.012, 0.016, 0.010, GLINT, lat=5, lon=8))
    # Eyelids (blink)
    if blink > 0.05:
        lid_h = 0.075 * blink + 0.01
        meshes.append(_make_sphere(-0.11, 1.38 - 0.07 * blink, 0.275, 0.066, lid_h, 0.052, SKIN, lat=8, lon=14))
        meshes.append(_make_sphere(0.11, 1.38 - 0.07 * blink, 0.275, 0.066, lid_h, 0.052, SKIN, lat=8, lon=14))

    # CURVED CARTOON EYEBROWS (Thick, rounded arches curving OVER the eyes)
    # Left eyebrow arch (inner, mid, outer)
    meshes.append(_make_sphere(-0.065, 1.425, 0.310, 0.040, 0.028, 0.028, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(-0.115, 1.455, 0.315, 0.048, 0.032, 0.028, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(-0.165, 1.430, 0.295, 0.040, 0.028, 0.028, DARK_BROWN, lat=8, lon=12))
    # Right eyebrow arch
    meshes.append(_make_sphere(0.065, 1.425, 0.310, 0.040, 0.028, 0.028, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(0.115, 1.455, 0.315, 0.048, 0.032, 0.028, DARK_BROWN, lat=8, lon=12))
    meshes.append(_make_sphere(0.165, 1.430, 0.295, 0.040, 0.028, 0.028, DARK_BROWN, lat=8, lon=12))

    # Mouth (under moustache)
    m_h = 0.012 + 0.055 * mouth_open
    meshes.append(_make_sphere(0.0, 1.09, 0.27, 0.070, m_h, 0.045, MOUTH_DARK, lat=8, lon=14))
    meshes.append(_make_sphere(0.0, 1.11, 0.29, 0.050, 0.010, 0.022, WHITE, lat=6, lon=10))
    if mouth_open > 0.15:
        meshes.append(_make_sphere(0.0, 1.08, 0.285, 0.040, 0.018, 0.025, TONGUE_RED, lat=6, lon=10))

    # =========================================================================
    # 4. BLACK CAP & CAPITAL "B" EMBLEM (HIGH-CONTRAST BADGE)
    # =========================================================================
    # Cap visor / brim: thick crescent projecting forward directly over forehead
    meshes.append(_make_sphere(0.0, 1.43, 0.32, 0.28, 0.032, 0.22, BLACK, lat=12, lon=20))
    meshes.append(_make_torus(0.0, 1.425, 0.26, 0.24, 0.020, BLACK, segs_R=16, segs_r=8,
                              angle_start=-0.2 * math.pi, angle_end=1.2 * math.pi, axis="y"))

    # Cap crown base band
    meshes.append(_make_sphere(0.0, 1.48, 0.01, 0.38, 0.12, 0.38, BLACK, lat=12, lon=20))
    # Puffed newsboy dome
    meshes.append(_make_sphere(0.0, 1.58, -0.04, 0.44, 0.19, 0.43, BLACK, lat=14, lon=22))
    # Front puffed lobe
    meshes.append(_make_sphere(0.0, 1.54, 0.14, 0.27, 0.15, 0.16, BLACK, lat=12, lon=18))
    # Side puffed lobes
    meshes.append(_make_sphere(-0.24, 1.56, -0.01, 0.21, 0.15, 0.21, BLACK, lat=10, lon=16))
    meshes.append(_make_sphere(0.24, 1.56, -0.01, 0.21, 0.15, 0.21, BLACK, lat=10, lon=16))

    # Circular white badge plate (oriented forward on the cap front)
    ey = 1.570
    ez = 0.395
    meshes.append(_make_sphere(0.0, ey, ez, 0.095, 0.095, 0.018, WHITE, lat=16, lon=24))
    meshes.append(_make_torus(0.0, ey, ez + 0.002, 0.092, 0.008, (0.84, 0.84, 0.86), segs_R=24, segs_r=8, axis="z"))

    # 3D CAPITAL LETTER "B" (Precision Typographic Geometry)
    bz = ez + 0.016
    # Left vertical spine
    meshes.append(_make_box(-0.032, ey, bz, 0.020, 0.118, 0.012, BLACK))
    # Top horizontal bar
    meshes.append(_make_box(-0.008, ey + 0.050, bz, 0.036, 0.018, 0.012, BLACK))
    # Middle horizontal bar
    meshes.append(_make_box(-0.006, ey, bz, 0.040, 0.018, 0.012, BLACK))
    # Bottom horizontal bar
    meshes.append(_make_box(-0.006, ey - 0.050, bz, 0.040, 0.018, 0.012, BLACK))
    # Top right curved loop
    meshes.append(_make_torus(0.006, ey + 0.025, bz, 0.026, 0.008, BLACK,
                             segs_R=14, segs_r=6, angle_start=-math.pi/2, angle_end=math.pi/2, axis="z"))
    # Bottom right curved loop
    meshes.append(_make_torus(0.008, ey - 0.025, bz, 0.028, 0.008, BLACK,
                             segs_R=14, segs_r=6, angle_start=-math.pi/2, angle_end=math.pi/2, axis="z"))

    # =========================================================================
    # 5. TORSO, BLACK SHIRT & BLUE OVERALLS (WITH TWO YELLOW BUTTONS)
    # =========================================================================
    # Black shirt chest & collar
    meshes.append(_make_sphere(0.0, 0.98, 0.0, 0.28, 0.18, 0.24, BLACK, lat=12, lon=18))

    # Overalls main body (chubby belly)
    meshes.append(_make_sphere(0.0, 0.80, 0.0, 0.34, 0.28, 0.28, BLUE, lat=14, lon=20))

    # Front chest bib (curved smoothly over belly)
    meshes.append(_make_sphere(0.0, 0.88, 0.15, 0.24, 0.16, 0.14, BLUE, lat=12, lon=16))
    # Back bib
    meshes.append(_make_sphere(0.0, 0.88, -0.15, 0.24, 0.16, 0.14, BLUE, lat=12, lon=16))

    # Overalls shoulder straps
    meshes.append(_make_box(-0.13, 0.98, 0.01, 0.065, 0.18, 0.38, BLUE))
    meshes.append(_make_box(0.13, 0.98, 0.01, 0.065, 0.18, 0.38, BLUE))

    # --- THE TWO BRIGHT YELLOW BUTTONS ---
    meshes.append(_make_sphere(-0.13, 0.87, 0.265, 0.034, 0.034, 0.015, YELLOW, lat=8, lon=14))
    meshes.append(_make_sphere(0.13, 0.87, 0.265, 0.034, 0.034, 0.015, YELLOW, lat=8, lon=14))

    # Puffy black shirt sleeves at shoulders
    meshes.append(_make_sphere(-0.28, 0.88, 0.0, 0.12, 0.12, 0.12, BLACK, lat=10, lon=14))
    meshes.append(_make_sphere(0.28, 0.88, 0.0, 0.12, 0.12, 0.12, BLACK, lat=10, lon=14))

    # Connected cartoon arms (upper arm -> elbow -> forearm)
    # Left arm:
    meshes.append(_make_cylinder(-0.29, 0.70, 0.86, 0.02, 0.082, 0.082, BLACK, segs=12))
    meshes.append(_make_sphere(-0.31, 0.69, 0.03, 0.082, 0.082, 0.082, BLACK, lat=8, lon=12))
    meshes.append(_make_cylinder(-0.32, 0.52, 0.69, 0.04, 0.076, 0.076, BLACK, segs=12))

    # Right arm:
    meshes.append(_make_cylinder(0.29, 0.70, 0.86, 0.02, 0.082, 0.082, BLACK, segs=12))
    meshes.append(_make_sphere(0.31, 0.69, 0.03, 0.082, 0.082, 0.082, BLACK, lat=8, lon=12))
    meshes.append(_make_cylinder(0.32, 0.52, 0.69, 0.04, 0.076, 0.076, BLACK, segs=12))

    # =========================================================================
    # 6. WHITE CARTOON GLOVES
    # =========================================================================
    # Left glove
    meshes.append(_make_torus(-0.33, 0.51, 0.05, 0.075, 0.025, WHITE, segs_R=14, segs_r=8, axis="y"))
    meshes.append(_make_sphere(-0.34, 0.42, 0.06, 0.095, 0.085, 0.085, WHITE, lat=10, lon=16))
    meshes.append(_make_sphere(-0.27, 0.43, 0.11, 0.040, 0.040, 0.050, WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(-0.34, 0.33, 0.06, 0.080, 0.065, 0.075, WHITE, lat=8, lon=12))

    # Right glove
    meshes.append(_make_torus(0.33, 0.51, 0.05, 0.075, 0.025, WHITE, segs_R=14, segs_r=8, axis="y"))
    meshes.append(_make_sphere(0.34, 0.42, 0.06, 0.095, 0.085, 0.085, WHITE, lat=10, lon=16))
    meshes.append(_make_sphere(0.27, 0.43, 0.11, 0.040, 0.040, 0.050, WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(0.34, 0.33, 0.06, 0.080, 0.065, 0.075, WHITE, lat=8, lon=12))

    # =========================================================================
    # 7. LOWER OVERALLS & BROWN BOOTS
    # =========================================================================
    # Pelvis
    meshes.append(_make_sphere(0.0, 0.58, 0.0, 0.28, 0.16, 0.25, BLUE, lat=12, lon=18))

    # Legs (short and stocky)
    meshes.append(_make_cylinder(-0.13, 0.19, 0.56, 0.0, 0.110, 0.110, BLUE, segs=14))
    meshes.append(_make_torus(-0.13, 0.19, 0.0, 0.105, 0.025, BLUE, segs_R=14, segs_r=8, axis="y"))
    meshes.append(_make_cylinder(0.13, 0.19, 0.56, 0.0, 0.110, 0.110, BLUE, segs=14))
    meshes.append(_make_torus(0.13, 0.19, 0.0, 0.105, 0.025, BLUE, segs_R=14, segs_r=8, axis="y"))

    # Left boot
    meshes.append(_make_sphere(-0.13, 0.11, -0.03, 0.115, 0.090, 0.115, BROWN, lat=10, lon=16))
    meshes.append(_make_sphere(-0.13, 0.12, 0.12, 0.130, 0.100, 0.130, BROWN, lat=12, lon=18))
    meshes.append(_make_box(-0.13, 0.030, 0.05, 0.24, 0.045, 0.34, DARK_BROWN))

    # Right boot
    meshes.append(_make_sphere(0.13, 0.11, -0.03, 0.115, 0.090, 0.115, BROWN, lat=10, lon=16))
    meshes.append(_make_sphere(0.13, 0.12, 0.12, 0.130, 0.100, 0.130, BROWN, lat=12, lon=18))
    meshes.append(_make_box(0.13, 0.030, 0.05, 0.24, 0.045, 0.34, DARK_BROWN))

    return _merge(*meshes)


# ---------------------------------------------------------------------------
# Animation state machine
# ---------------------------------------------------------------------------

class AnimState:
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    HEARD_USER = "HEARD_USER"
    THINKING = "THINKING"
    DEEP_THINKING = "DEEP_THINKING"
    SPEAKING = "SPEAKING"
    HAPPY = "HAPPY"
    SURPRISED = "SURPRISED"
    CONFUSED = "CONFUSED"
    WARNING = "WARNING"
    TOOL_WORKING = "TOOL_WORKING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    SLEEPING = "SLEEPING"


class CharacterAnimator:
    """Drives animation parameters from the current state and elapsed time."""

    def __init__(self) -> None:
        self.state: str = AnimState.IDLE
        self.t: float = 0.0  # animation clock
        self.amplitude: float = 0.0  # audio amplitude for lip sync
        self.hidden: bool = False

        # Random idle gesture timer
        self._next_idle_gesture: float = 3.0
        self._idle_gesture: str = "none"

    def set_state(self, state: str) -> None:
        """Set animation state safely."""
        if hasattr(AnimState, state):
            self.state = state

    @property
    def elapsed(self) -> float:
        return self.t

    def update(self, dt: float) -> None:
        self.t += dt
        if self.t > self._next_idle_gesture and self.state == AnimState.IDLE:
            import random
            self._idle_gesture = random.choice(
                ["brow_raise", "wink", "head_tilt", "bounce", "wave", "none"]
            )
            self._next_idle_gesture = self.t + random.uniform(4.0, 8.0)

    def get_params(self) -> dict[str, float]:
        """Return animation parameters for this frame."""
        t = self.t
        s = self.state
        a = self.amplitude

        # Breathing: subtle up-down in IDLE/LISTENING
        breath_y = 0.0
        if s in (AnimState.IDLE, AnimState.LISTENING, AnimState.SLEEPING):
            speed = 0.4 if s == AnimState.SLEEPING else 0.7
            breath_y = math.sin(t * 2 * math.pi * speed) * 0.010

        # Body bob: bouncy in HAPPY/SUCCESS
        bob_y = 0.0
        if s in (AnimState.HAPPY, AnimState.SUCCESS):
            bob_y = abs(math.sin(t * 2 * math.pi * 2.5)) * 0.06

        # Lean forward in LISTENING
        lean_x = 0.0
        if s == AnimState.LISTENING:
            lean_x = 0.04

        # Head tilt in THINKING
        head_tilt = 0.0
        if s in (AnimState.THINKING, AnimState.DEEP_THINKING, AnimState.CONFUSED):
            head_tilt = math.sin(t * 2 * math.pi * 0.3) * 0.08

        # Eyebrow raise in SURPRISED / HAPPY
        brow_raise = 0.0
        if s in (AnimState.SURPRISED, AnimState.HAPPY, AnimState.SUCCESS):
            brow_raise = 0.06
        elif s == AnimState.DEEP_THINKING:
            brow_raise = -0.03  # furrowed brows

        # Blink: every ~4s normally, faster when confused/error
        blink_period = 4.0 if s == AnimState.IDLE else 3.2
        blink_phase = (t % blink_period) / blink_period
        blink = max(0.0, 1.0 - abs(blink_phase - 0.02) / 0.008) if blink_phase < 0.03 else 0.0

        # Mouth: driven by amplitude during SPEAKING, smile during HAPPY
        if s == AnimState.SPEAKING:
            mouth_open = min(1.0, a * 2.5 + 0.15)
        elif s in (AnimState.HAPPY, AnimState.SUCCESS):
            mouth_open = 0.35 + math.sin(t * 6) * 0.05
        elif s == AnimState.SURPRISED:
            mouth_open = 0.6
        elif s == AnimState.ERROR:
            mouth_open = 0.25
        else:
            mouth_open = 0.0

        # Rotation (y-axis wiggle in DEEP_THINKING)
        rot_y_extra = 0.0
        if s == AnimState.DEEP_THINKING:
            rot_y_extra = math.sin(t * 2 * math.pi * 0.5) * 8.0  # degrees

        # TOOL_WORKING: spin
        if s == AnimState.TOOL_WORKING:
            rot_y_extra = (t * 90.0) % 360.0

        # SLEEPING: slow sway
        if s == AnimState.SLEEPING:
            rot_y_extra = math.sin(t * 2 * math.pi * 0.15) * 5.0

        return {
            "breath_y": breath_y,
            "bob_y": bob_y,
            "lean_x": lean_x,
            "head_tilt": head_tilt,
            "brow_raise": brow_raise,
            "blink": blink,
            "mouth_open": mouth_open,
            "rot_y_extra": rot_y_extra,
        }


# ---------------------------------------------------------------------------
# IPC Server (runs in background thread)
# ---------------------------------------------------------------------------

class IPCServer:
    """TCP server that receives companion events from OpenBagus CLI."""

    def __init__(self, port: int, animator: CharacterAnimator, running_flag: list[bool]) -> None:
        self.port = port
        self.animator = animator
        self.running_flag = running_flag
        self._window_should_show: bool = True
        self._window_should_hide: bool = False
        self._window_should_close: bool = False
        self._screenshot_queue: list[str] = []

    def should_hide(self) -> bool:
        r = self._window_should_hide
        self._window_should_hide = False
        return r

    def should_show(self) -> bool:
        r = self._window_should_show
        self._window_should_show = False
        return r

    def should_close(self) -> bool:
        return self._window_should_close

    def start(self) -> None:
        t = threading.Thread(target=self._serve, daemon=True, name="CompanionIPC")
        t.start()

    def _serve(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self.port))
        except OSError as e:
            print(f"[CompanionIPC] Cannot bind port {self.port}: {e}", file=sys.stderr)
            return
        srv.listen(4)
        srv.settimeout(1.0)
        print(f"[CompanionIPC] Listening on 127.0.0.1:{self.port}", file=sys.stderr)

        while self.running_flag[0]:
            try:
                conn, addr = srv.accept()
            except TimeoutError:
                continue
            threading.Thread(
                target=self._handle_conn, args=(conn,), daemon=True
            ).start()

        srv.close()

    def _handle_conn(self, conn: socket.socket) -> None:
        buf = b""
        with conn:
            conn.settimeout(60.0)
            while self.running_flag[0]:
                try:
                    data = conn.recv(4096)
                except (ConnectionResetError, TimeoutError, OSError):
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._dispatch(line.decode("utf-8", errors="replace"))

    def _dispatch(self, raw: str) -> None:
        try:
            msg: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            return

        event = msg.get("type", "")
        payload = msg.get("payload", {})

        if event == "companion.set_state":
            state = payload.get("state", "IDLE")
            if hasattr(AnimState, state):
                self.animator.state = state
        elif event == "companion.speak_start":
            self.animator.state = AnimState.SPEAKING
        elif event == "companion.speak_amplitude":
            self.animator.amplitude = float(payload.get("amplitude", 0.0))
        elif event == "companion.speak_end":
            self.animator.state = AnimState.IDLE
            self.animator.amplitude = 0.0
        elif event == "companion.interrupted":
            self.animator.state = AnimState.LISTENING
            self.animator.amplitude = 0.0
        elif event == "companion.show":
            self._window_should_show = True
            self.animator.hidden = False
        elif event == "companion.hide":
            self._window_should_hide = True
            self.animator.hidden = True
        elif event == "companion.shutdown":
            self._window_should_close = True
        elif event == "companion.reset":
            self.animator.state = AnimState.IDLE
            self.animator.t = 0.0
        elif event == "companion.screenshot":
            path = payload.get("path", "")
            if path:
                self._screenshot_queue.append(path)


# ---------------------------------------------------------------------------
# Main render loop
# ---------------------------------------------------------------------------

def run_renderer(port: int) -> None:
    if not HAS_GL:
        print(f"[ShowOpenBagus] Missing dependency: {_MISSING}", file=sys.stderr)
        sys.exit(1)

    WINDOW_W, WINDOW_H = 480, 560

    if not glfw.init():
        print("[ShowOpenBagus] GLFW init failed", file=sys.stderr)
        sys.exit(1)

    # Request OpenGL 3.3 Core (moderngl requirement)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)       # always-on-top
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    glfw.window_hint(glfw.FOCUS_ON_SHOW, glfw.FALSE)  # don't steal focus
    if hasattr(glfw, "TRANSPARENT_FRAMEBUFFER"):
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.SAMPLES, 4)  # MSAA

    monitor = glfw.get_primary_monitor()
    mode = glfw.get_video_mode(monitor)
    screen_w, screen_h = mode.size.width, mode.size.height

    # Position: lower-right of screen
    win_x = screen_w - WINDOW_W - 30
    win_y = screen_h - WINDOW_H - 60

    window = glfw.create_window(WINDOW_W, WINDOW_H, "SHOW OPENBAGUS", None, None)
    if not window and hasattr(glfw, "TRANSPARENT_FRAMEBUFFER"):
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.FALSE)
        window = glfw.create_window(WINDOW_W, WINDOW_H, "SHOW OPENBAGUS", None, None)
    if not window:
        glfw.terminate()
        print("[ShowOpenBagus] Window creation failed", file=sys.stderr)
        sys.exit(1)

    glfw.set_window_pos(window, win_x, win_y)
    glfw.make_context_current(window)
    glfw.swap_interval(1)  # vsync

    # Disable focus stealing on click
    glfw.set_window_focus_callback(window, lambda w, focused: None)

    ctx = moderngl.create_context()
    ctx.enable(moderngl.DEPTH_TEST)

    prog = ctx.program(vertex_shader=VERT_SHADER, fragment_shader=FRAG_SHADER)

    animator = CharacterAnimator()
    running_flag: list[bool] = [True]
    ipc = IPCServer(port=port, animator=animator, running_flag=running_flag)
    ipc.start()

    # Build initial geometry
    def rebuild_mesh(params: dict[str, float]) -> tuple[moderngl.VertexArray, moderngl.Buffer]:
        verts, idxs = build_character(
            mouth_open=params.get("mouth_open", 0.0),
            blink=params.get("blink", 0.0),
        )
        v_data = np.array(verts, dtype="f4")
        i_data = np.array(idxs, dtype="i4")
        vbo = ctx.buffer(v_data)
        ibo = ctx.buffer(i_data)
        stride = 9 * 4  # 9 floats * 4 bytes
        vao = ctx.vertex_array(
            prog,
            [(vbo, "3f 3f 3f", "in_position", "in_normal", "in_color")],
            index_buffer=ibo,
        )
        return vao, ibo

    last_params: dict[str, float] = {}
    params = animator.get_params()
    vao, ibo = rebuild_mesh(params)
    n_indices = len(build_character()[1])

    # Camera
    cam_pos = Vector3([0.0, 0.98, 2.65])
    proj = Matrix44.perspective_projection(38.0, WINDOW_W / WINDOW_H, 0.1, 50.0, dtype="f4")
    view = Matrix44.look_at(cam_pos, Vector3([0.0, 0.96, 0.0]), Vector3([0.0, 1.0, 0.0]), dtype="f4")

    # Lighting
    prog["light_pos"].write(np.array([2.5, 4.0, 3.5], dtype="f4"))
    prog["view_pos"].write(np.array(cam_pos, dtype="f4"))
    if "ambient_strength" in prog:
        prog["ambient_strength"].value = 0.45
    prog["proj"].write(proj)
    prog["view"].write(view)

    last_time = glfw.get_time()
    mesh_rebuild_timer = 0.0

    print("[ShowOpenBagus] Render loop started", file=sys.stderr)

    while not glfw.window_should_close(window) and not ipc.should_close():
        now = glfw.get_time()
        dt = now - last_time
        last_time = now

        animator.update(dt)
        mesh_rebuild_timer += dt

        params = animator.get_params()

        # Rebuild mesh every ~33ms (30fps geometry update for mouth/blink)
        if mesh_rebuild_timer >= 0.033:
            mesh_rebuild_timer = 0.0
            vao.release()
            vao, ibo = rebuild_mesh(params)
            n_indices = len(build_character(
                mouth_open=params["mouth_open"], blink=params["blink"]
            )[1])

        # Model matrix: breath + bob + lean + slight rotation
        rot_y_base = 8.0  # slight camera angle
        rot_y = rot_y_base + params.get("rot_y_extra", 0.0)
        translate_y = params["breath_y"] + params["bob_y"]

        model = (
            Matrix44.from_translation([params["lean_x"], translate_y, 0.0], dtype="f4")
            @ Matrix44.from_eulers([0.0, math.radians(rot_y), 0.0], dtype="f4")
        )
        prog["model"].write(model)

        # Render
        ctx.clear(0.0, 0.0, 0.0, 0.0)  # transparent desktop background
        vao.render()

        # Capture live popup screenshot if requested via IPC
        if ipc._screenshot_queue:
            try:
                import PIL.Image
                save_p = ipc._screenshot_queue.pop(0)
                data = ctx.screen.read(components=4)
                shot_img = PIL.Image.frombytes("RGBA", (WINDOW_W, WINDOW_H), data).transpose(PIL.Image.FLIP_TOP_BOTTOM)
                os.makedirs(os.path.dirname(os.path.abspath(save_p)), exist_ok=True)
                shot_img.save(save_p)
                print(f"[ShowOpenBagus] Captured live popup to {save_p}", file=sys.stderr)
            except Exception as _err:
                print(f"[ShowOpenBagus] Screenshot error: {_err}", file=sys.stderr)

        glfw.swap_buffers(window)

        # Handle IPC-driven show/hide
        if ipc.should_hide():
            glfw.hide_window(window)
        if ipc.should_show():
            glfw.show_window(window)

        glfw.poll_events()

    running_flag[0] = False
    vao.release()
    ctx.release()
    glfw.terminate()
    print("[ShowOpenBagus] Companion closed", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SHOW OPENBAGUS 3D Companion Renderer")
    parser.add_argument("--port", type=int, default=7432, help="IPC TCP port")
    args = parser.parse_args()
    run_renderer(args.port)
