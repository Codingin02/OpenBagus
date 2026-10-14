"""BAGUSMAX — Real-time Dual-Form 3D companion renderer.

Renders an animated 3D companion (BAGUSMAX) using OpenGL (moderngl + glfw).
Two official forms synchronized to OpenBagus reasoning modes:
  - Form A: BAGUSMAX WHITE (FAST mode, low latency, non-thinking)
    * Inflatable warm white vinyl robot body (0.96, 0.96, 0.97)
    * Smooth rounded head with two black eyes connected by thin horizontal line
    * Subtle silver healthcare access port on upper left chest
    * Pear-shaped torso, soft shoulders, tapered arms, chubby fingers, columnar legs
  - Form B: BAGUSMAX ARMORED (DEEP_REASONING mode, thinking)
    * Glossy red hero armor suit (0.86, 0.16, 0.08)
    * Red aerodynamic helmet with side ear winglets and white face visor aperture
    * Massive curved red breastplate & segmented 6-plate purple abdominal armor
    * Stowed back wings (folded along upper back, zero window clipping)
    * Heavy red knee guards, greaves, armored boots with heel thrusters

Speech synchronization:
  - Deforms head pitch (gentle nodding), vertical breathing/bobbing, and chest
    expansion proportional to audio amplitude (0.0 to 1.0). Mouthless character.

Run as subprocess: python -m openbagus.companion.renderer --port 7432
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


def _make_cone(
    cx: float, cy_bot: float, cy_top: float, cz: float,
    r_bot_x: float, r_bot_z: float,
    r_top_x: float, r_top_z: float,
    color: tuple[float, float, float],
    segs: int = 16,
) -> tuple[list[float], list[int]]:
    """Generate truncated cone / tapered cylinder vertices and indices."""
    verts: list[float] = []
    idxs: list[int] = []

    base = 0
    dy = cy_top - cy_bot
    dr = r_top_x - r_bot_x
    slant = math.sqrt(dy * dy + dr * dr) if dy != 0 else 1.0
    ny_side = -dr / slant if slant != 0 else 0.0
    nr_side = dy / slant if slant != 0 else 1.0

    for i in range(segs + 1):
        angle = 2 * math.pi * i / segs
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        nx = cos_a * nr_side
        nz = sin_a * nr_side
        verts.extend([cx + r_bot_x * cos_a, cy_bot, cz + r_bot_z * sin_a, nx, ny_side, nz, *color])
        verts.extend([cx + r_top_x * cos_a, cy_top, cz + r_top_z * sin_a, nx, ny_side, nz, *color])

    for i in range(segs):
        a = base + i * 2
        b = a + 1
        c = a + 2
        d = a + 3
        idxs.extend([a, b, c, b, d, c])

    cap_center = len(verts) // 9
    verts.extend([cx, cy_top, cz, 0.0, 1.0, 0.0, *color])
    ring_start = base
    for i in range(segs):
        a = ring_start + i * 2 + 1
        b = ring_start + (i + 1) % segs * 2 + 1
        idxs.extend([cap_center, a, b])

    bot_center = len(verts) // 9
    verts.extend([cx, cy_bot, cz, 0.0, -1.0, 0.0, *color])
    for i in range(segs):
        a = ring_start + i * 2
        b = ring_start + (i + 1) % segs * 2
        idxs.extend([bot_center, b, a])

    return verts, idxs


# ---------------------------------------------------------------------------
# Character geometry builders: BAGUSMAX Dual-Form (White & Armored)
# ---------------------------------------------------------------------------

class BagusmaxForm:
    WHITE = "WHITE"
    ARMORED = "ARMORED"


def build_bagusmax_white(
    blink: float = 0.0,
    head_tilt: float = 0.0,
    breath: float = 1.0,
) -> tuple[list[float], list[int]]:
    """Build BAGUSMAX WHITE Form (FAST Reasoning Mode).

    Inflatable warm white vinyl robot:
    - Smooth rounded head with two black eyes connected by a thin horizontal black line.
    - Subtle silver healthcare access port on upper left chest.
    - Soft shoulders, tapered arms with chubby fingers.
    - Pear-shaped torso with prominent rounded lower belly.
    - Short columnar legs and rounded feet.
    - Warm vinyl white palette: (0.96, 0.96, 0.97).
    """
    VINYL_WHITE  = (0.96, 0.96, 0.97)
    VINYL_SHADOW = (0.88, 0.88, 0.90)
    BLACK_EYES   = (0.04, 0.04, 0.04)
    PORT_SILVER  = (0.84, 0.84, 0.88)
    PORT_INNER   = (0.70, 0.70, 0.75)

    meshes: list[tuple[list[float], list[int]]] = []

    # 1. HEAD (Seated at y = 1.34)
    head_cx = -head_tilt * 0.08
    head_cy = 1.34 - abs(head_tilt) * 0.015
    head_cz = 0.0
    meshes.append(_make_sphere(head_cx, head_cy, head_cz, 0.22, 0.175, 0.185, VINYL_WHITE, lat=16, lon=24))

    # Two black eyes connected by thin line (Baymax signature face)
    eye_y_scale = max(0.1, 1.0 - blink * 0.9)
    # Left eye
    meshes.append(_make_sphere(head_cx - 0.075, head_cy, 0.178, 0.018, 0.018 * eye_y_scale, 0.008, BLACK_EYES, lat=10, lon=14))
    # Right eye
    meshes.append(_make_sphere(head_cx + 0.075, head_cy, 0.178, 0.018, 0.018 * eye_y_scale, 0.008, BLACK_EYES, lat=10, lon=14))
    # Thin connecting line between eyes
    meshes.append(_make_box(head_cx, head_cy, 0.179, 0.145, 0.0035, 0.006, BLACK_EYES))

    # Neck transition
    meshes.append(_make_cylinder(0.0, 1.20, 1.28, 0.0, 0.16, 0.16, VINYL_WHITE, segs=16))

    # 2. PEAR-SHAPED TORSO (Inflatable Vinyl Body)
    bs = max(0.85, min(1.25, breath))
    # Upper chest
    meshes.append(_make_sphere(0.0, 1.05, -0.01, 0.32 * bs, 0.25, 0.28 * bs, VINYL_WHITE, lat=16, lon=24))
    # Pear-shaped belly (fuller, lower, projecting forward)
    meshes.append(_make_sphere(0.0, 0.75, 0.05, 0.42 * bs, 0.30, 0.37 * bs, VINYL_WHITE, lat=18, lon=26))
    # Pelvis
    meshes.append(_make_sphere(0.0, 0.52, 0.01, 0.38, 0.22, 0.33, VINYL_WHITE, lat=14, lon=22))

    # Access Port on Upper Left Chest (Healthcare chip slot)
    meshes.append(_make_torus(-0.13, 1.10, 0.265, 0.034, 0.006, PORT_SILVER, segs_R=16, segs_r=8, axis="z"))
    meshes.append(_make_sphere(-0.13, 1.10, 0.263, 0.028, 0.028, 0.004, PORT_INNER, lat=8, lon=12))

    # 3. ARMS & HANDS
    # Left Arm
    meshes.append(_make_sphere(-0.36, 1.04, 0.0, 0.13, 0.13, 0.13, VINYL_WHITE, lat=12, lon=18))
    meshes.append(_make_cone(-0.40, 0.78, 0.98, 0.01, 0.085, 0.085, 0.100, 0.100, VINYL_WHITE, segs=14))
    meshes.append(_make_sphere(-0.42, 0.76, 0.02, 0.09, 0.09, 0.09, VINYL_WHITE, lat=10, lon=14))
    meshes.append(_make_cone(-0.44, 0.54, 0.74, 0.04, 0.075, 0.075, 0.085, 0.085, VINYL_WHITE, segs=14))
    meshes.append(_make_sphere(-0.45, 0.48, 0.06, 0.070, 0.060, 0.060, VINYL_WHITE, lat=10, lon=14))
    # Left chubby fingers
    meshes.append(_make_sphere(-0.43, 0.41, 0.08, 0.024, 0.034, 0.024, VINYL_WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(-0.46, 0.40, 0.06, 0.024, 0.036, 0.024, VINYL_WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(-0.49, 0.41, 0.04, 0.022, 0.032, 0.022, VINYL_WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(-0.39, 0.47, 0.09, 0.025, 0.025, 0.028, VINYL_WHITE, lat=8, lon=12))

    # Right Arm
    meshes.append(_make_sphere(0.36, 1.04, 0.0, 0.13, 0.13, 0.13, VINYL_WHITE, lat=12, lon=18))
    meshes.append(_make_cone(0.40, 0.78, 0.98, 0.01, 0.085, 0.085, 0.100, 0.100, VINYL_WHITE, segs=14))
    meshes.append(_make_sphere(0.42, 0.76, 0.02, 0.09, 0.09, 0.09, VINYL_WHITE, lat=10, lon=14))
    meshes.append(_make_cone(0.44, 0.54, 0.74, 0.04, 0.075, 0.075, 0.085, 0.085, VINYL_WHITE, segs=14))
    meshes.append(_make_sphere(0.45, 0.48, 0.06, 0.070, 0.060, 0.060, VINYL_WHITE, lat=10, lon=14))
    # Right chubby fingers
    meshes.append(_make_sphere(0.43, 0.41, 0.08, 0.024, 0.034, 0.024, VINYL_WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(0.46, 0.40, 0.06, 0.024, 0.036, 0.024, VINYL_WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(0.49, 0.41, 0.04, 0.022, 0.032, 0.022, VINYL_WHITE, lat=8, lon=12))
    meshes.append(_make_sphere(0.39, 0.47, 0.09, 0.025, 0.025, 0.028, VINYL_WHITE, lat=8, lon=12))

    # 4. LEGS & FEET (Short, columnar, stable)
    # Left leg & foot
    meshes.append(_make_cylinder(-0.18, 0.12, 0.50, 0.0, 0.145, 0.150, VINYL_WHITE, segs=16))
    meshes.append(_make_sphere(-0.18, 0.09, 0.07, 0.160, 0.095, 0.200, VINYL_WHITE, lat=12, lon=18))

    # Right leg & foot
    meshes.append(_make_cylinder(0.18, 0.12, 0.50, 0.0, 0.145, 0.150, VINYL_WHITE, segs=16))
    meshes.append(_make_sphere(0.18, 0.09, 0.07, 0.160, 0.095, 0.200, VINYL_WHITE, lat=12, lon=18))

    return _merge(*meshes)


def build_bagusmax_armored(
    blink: float = 0.0,
    head_tilt: float = 0.0,
    breath: float = 1.0,
) -> tuple[list[float], list[int]]:
    """Build BAGUSMAX ARMORED Form (DEEP_REASONING Mode).

    Red armored hero suit:
    - Red aerodynamic helmet with side ear winglets and central ridge.
    - White visor aperture showing two black eyes connected by thin line.
    - Massive curved red breastplate/chest armor.
    - Segmented 6-plate dark purple abdominal armor insert.
    - Red shoulder pauldrons with purple top panels.
    - Flared red gauntlets with purple thruster ports and graphite mechanical fists.
    - Stowed back wings (folded neatly along back, zero window clipping).
    - Heavy red knee guards, greaves, armored boots with heel thrusters.
    """
    ARMOR_RED       = (0.86, 0.16, 0.08)
    ARMOR_DARK_RED  = (0.64, 0.10, 0.05)
    PURPLE_ACCENT   = (0.34, 0.18, 0.48)
    GRAPHITE_JOINT  = (0.13, 0.13, 0.15)
    VISOR_WHITE     = (0.95, 0.95, 0.96)
    BLACK_EYES      = (0.04, 0.04, 0.04)
    THRUSTER_YELLOW = (0.98, 0.82, 0.12)

    meshes: list[tuple[list[float], list[int]]] = []

    # 1. HELMET & VISOR
    head_cx = -head_tilt * 0.06
    head_cy = 1.38 - abs(head_tilt) * 0.012
    # Main red helmet dome
    meshes.append(_make_sphere(head_cx, head_cy, -0.01, 0.245, 0.20, 0.22, ARMOR_RED, lat=16, lon=24))
    # Top central aerodynamic ridge
    meshes.append(_make_box(head_cx, head_cy + 0.16, -0.02, 0.05, 0.05, 0.26, ARMOR_RED))
    # Side ear winglet fins
    meshes.append(_make_box(head_cx - 0.25, head_cy, -0.03, 0.035, 0.11, 0.13, ARMOR_RED))
    meshes.append(_make_box(head_cx + 0.25, head_cy, -0.03, 0.035, 0.11, 0.13, ARMOR_RED))

    # White Visor Aperture (Face opening showing the Baymax eyes)
    meshes.append(_make_sphere(head_cx, head_cy - 0.03, 0.178, 0.145, 0.105, 0.035, VISOR_WHITE, lat=12, lon=18))
    # Two black eyes on visor
    eye_y_scale = max(0.1, 1.0 - blink * 0.9)
    meshes.append(_make_sphere(head_cx - 0.065, head_cy - 0.03, 0.214, 0.016, 0.016 * eye_y_scale, 0.007, BLACK_EYES, lat=10, lon=14))
    meshes.append(_make_sphere(head_cx + 0.065, head_cy - 0.03, 0.214, 0.016, 0.016 * eye_y_scale, 0.007, BLACK_EYES, lat=10, lon=14))
    meshes.append(_make_box(head_cx, head_cy - 0.03, 0.215, 0.125, 0.0035, 0.006, BLACK_EYES))

    # Helmet chin / collar guard
    meshes.append(_make_box(head_cx, head_cy - 0.13, 0.15, 0.24, 0.06, 0.11, ARMOR_RED))
    # Graphite neck joint
    meshes.append(_make_cylinder(0.0, 1.18, 1.26, 0.0, 0.16, 0.16, GRAPHITE_JOINT, segs=16))

    # 2. CHEST ARMOR & ABDOMINAL PLATES
    # Upper breastplate
    meshes.append(_make_sphere(0.0, 1.08, 0.04, 0.36, 0.22, 0.30, ARMOR_RED, lat=16, lon=24))
    # Pectoral armor plates
    meshes.append(_make_sphere(-0.15, 1.08, 0.22, 0.16, 0.12, 0.10, ARMOR_RED, lat=12, lon=16))
    meshes.append(_make_sphere(0.15, 1.08, 0.22, 0.16, 0.12, 0.10, ARMOR_RED, lat=12, lon=16))
    # Chest chip port emblem (purple accent on left chest)
    meshes.append(_make_sphere(-0.13, 1.11, 0.28, 0.035, 0.035, 0.006, PURPLE_ACCENT, lat=10, lon=14))

    # Segmented 6-plate dark purple abdominal armor insert (2 cols x 3 rows)
    # Row 1 (upper abs)
    meshes.append(_make_box(-0.075, 0.93, 0.28, 0.12, 0.075, 0.05, PURPLE_ACCENT))
    meshes.append(_make_box(0.075, 0.93, 0.28, 0.12, 0.075, 0.05, PURPLE_ACCENT))
    # Row 2 (mid abs)
    meshes.append(_make_box(-0.085, 0.83, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))
    meshes.append(_make_box(0.085, 0.83, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))
    # Row 3 (lower abs)
    meshes.append(_make_box(-0.085, 0.73, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))
    meshes.append(_make_box(0.085, 0.73, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))

    # Flanking red abdominal obliques
    meshes.append(_make_sphere(-0.28, 0.82, 0.10, 0.16, 0.24, 0.24, ARMOR_RED, lat=12, lon=18))
    meshes.append(_make_sphere(0.28, 0.82, 0.10, 0.16, 0.24, 0.24, ARMOR_RED, lat=12, lon=18))

    # Pelvic belt & buckle
    meshes.append(_make_box(0.0, 0.60, 0.02, 0.44, 0.09, 0.36, ARMOR_RED))
    meshes.append(_make_box(0.0, 0.60, 0.20, 0.12, 0.08, 0.04, PURPLE_ACCENT))
    meshes.append(_make_sphere(0.0, 0.52, 0.0, 0.32, 0.16, 0.28, GRAPHITE_JOINT, lat=12, lon=18))

    # 3. SHOULDERS & ARMS
    # Left shoulder pauldron
    meshes.append(_make_sphere(-0.42, 1.10, 0.0, 0.19, 0.19, 0.19, ARMOR_RED, lat=14, lon=20))
    meshes.append(_make_cylinder(-0.42, 1.21, 1.25, 0.0, 0.14, 0.14, PURPLE_ACCENT, segs=14))
    # Left bicep & elbow (graphite)
    meshes.append(_make_cylinder(-0.40, 0.84, 0.98, 0.02, 0.095, 0.095, GRAPHITE_JOINT, segs=14))
    meshes.append(_make_sphere(-0.43, 0.80, 0.03, 0.09, 0.09, 0.09, GRAPHITE_JOINT, lat=10, lon=14))
    # Left armored forearm gauntlet
    meshes.append(_make_cone(-0.46, 0.52, 0.76, 0.05, 0.115, 0.115, 0.100, 0.100, ARMOR_RED, segs=16))
    meshes.append(_make_box(-0.46, 0.72, 0.05, 0.25, 0.05, 0.25, PURPLE_ACCENT))
    # Left mechanical fist
    meshes.append(_make_box(-0.46, 0.44, 0.07, 0.12, 0.11, 0.12, GRAPHITE_JOINT))

    # Right shoulder pauldron
    meshes.append(_make_sphere(0.42, 1.10, 0.0, 0.19, 0.19, 0.19, ARMOR_RED, lat=14, lon=20))
    meshes.append(_make_cylinder(0.42, 1.21, 1.25, 0.0, 0.14, 0.14, PURPLE_ACCENT, segs=14))
    # Right bicep & elbow (graphite)
    meshes.append(_make_cylinder(0.40, 0.84, 0.98, 0.02, 0.095, 0.095, GRAPHITE_JOINT, segs=14))
    meshes.append(_make_sphere(0.42, 0.80, 0.03, 0.09, 0.09, 0.09, GRAPHITE_JOINT, lat=10, lon=14))
    # Right armored forearm gauntlet
    meshes.append(_make_cone(0.46, 0.52, 0.76, 0.05, 0.115, 0.115, 0.100, 0.100, ARMOR_RED, segs=16))
    meshes.append(_make_box(0.46, 0.72, 0.05, 0.25, 0.05, 0.25, PURPLE_ACCENT))
    # Right mechanical fist
    meshes.append(_make_box(0.46, 0.44, 0.07, 0.12, 0.11, 0.12, GRAPHITE_JOINT))

    # 4. STOWED / FOLDED BACK WINGS & JETPACK
    # Jetpack central pack
    meshes.append(_make_box(0.0, 1.05, -0.22, 0.26, 0.30, 0.10, ARMOR_DARK_RED))
    # Twin thruster ports
    meshes.append(_make_cylinder(-0.08, 0.90, 1.06, -0.28, 0.045, 0.045, GRAPHITE_JOINT, segs=12))
    meshes.append(_make_cylinder(-0.08, 0.88, 0.90, -0.28, 0.035, 0.035, THRUSTER_YELLOW, segs=10))
    meshes.append(_make_cylinder(0.08, 0.90, 1.06, -0.28, 0.045, 0.045, GRAPHITE_JOINT, segs=12))
    meshes.append(_make_cylinder(0.08, 0.88, 0.90, -0.28, 0.035, 0.035, THRUSTER_YELLOW, segs=10))
    # Folded wings along back
    meshes.append(_make_box(-0.24, 1.10, -0.19, 0.12, 0.36, 0.04, ARMOR_RED))
    meshes.append(_make_box(-0.30, 1.10, -0.19, 0.02, 0.34, 0.04, PURPLE_ACCENT))
    meshes.append(_make_box(0.24, 1.10, -0.19, 0.12, 0.36, 0.04, ARMOR_RED))
    meshes.append(_make_box(0.30, 1.10, -0.19, 0.02, 0.34, 0.04, PURPLE_ACCENT))

    # 5. LEGS & ARMORED BOOTS
    # Left leg
    meshes.append(_make_cylinder(-0.18, 0.34, 0.54, 0.0, 0.145, 0.150, ARMOR_RED, segs=14))
    meshes.append(_make_box(-0.18, 0.34, 0.16, 0.14, 0.12, 0.06, ARMOR_RED))
    meshes.append(_make_box(-0.18, 0.34, 0.18, 0.08, 0.08, 0.04, PURPLE_ACCENT))
    meshes.append(_make_sphere(-0.18, 0.32, 0.0, 0.12, 0.10, 0.12, GRAPHITE_JOINT, lat=10, lon=14))
    meshes.append(_make_cylinder(-0.18, 0.12, 0.32, 0.0, 0.155, 0.160, ARMOR_RED, segs=14))
    # Left boot
    meshes.append(_make_sphere(-0.18, 0.09, 0.08, 0.165, 0.095, 0.22, ARMOR_RED, lat=12, lon=18))
    meshes.append(_make_box(-0.18, 0.025, 0.07, 0.34, 0.045, 0.44, GRAPHITE_JOINT))
    meshes.append(_make_cylinder(-0.18, 0.04, 0.10, -0.06, 0.04, 0.04, THRUSTER_YELLOW, segs=10))

    # Right leg
    meshes.append(_make_cylinder(0.18, 0.34, 0.54, 0.0, 0.145, 0.150, ARMOR_RED, segs=14))
    meshes.append(_make_box(0.18, 0.34, 0.16, 0.14, 0.12, 0.06, ARMOR_RED))
    meshes.append(_make_box(0.18, 0.34, 0.18, 0.08, 0.08, 0.04, PURPLE_ACCENT))
    meshes.append(_make_sphere(0.18, 0.32, 0.0, 0.12, 0.10, 0.12, GRAPHITE_JOINT, lat=10, lon=14))
    meshes.append(_make_cylinder(0.18, 0.12, 0.32, 0.0, 0.155, 0.160, ARMOR_RED, segs=14))
    # Right boot
    meshes.append(_make_sphere(0.18, 0.09, 0.08, 0.165, 0.095, 0.22, ARMOR_RED, lat=12, lon=18))
    meshes.append(_make_box(0.18, 0.025, 0.07, 0.34, 0.045, 0.44, GRAPHITE_JOINT))
    meshes.append(_make_cylinder(0.18, 0.04, 0.10, -0.06, 0.04, 0.04, THRUSTER_YELLOW, segs=10))

    return _merge(*meshes)



# ---------------------------------------------------------------------------
# Character geometry builder: BAGUSMAX Dual-Form (Dispatch)
# ---------------------------------------------------------------------------

def build_character(
    form: str = "WHITE",
    mouth_open: float = 0.0,
    blink: float = 0.0,
    head_tilt: float = 0.0,
    breath: float = 1.0,
) -> tuple[list[float], list[int]]:
    """Build BAGUSMAX 3D companion character.

    Dispatches to build_bagusmax_armored or build_bagusmax_white based on form.
    """
    if str(form).upper() in (BagusmaxForm.ARMORED, "RED", "DEEP", "DEEP_REASONING"):
        return build_bagusmax_armored(blink=blink, head_tilt=head_tilt, breath=breath)
    return build_bagusmax_white(blink=blink, head_tilt=head_tilt, breath=breath)


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
    """Drives animation parameters from the current state, active form, and elapsed time."""

    def __init__(self) -> None:
        self.state: str = AnimState.IDLE
        self.character_form: str = BagusmaxForm.WHITE
        self.target_form: str = BagusmaxForm.WHITE
        self.reasoning_mode: str = "FAST"
        self.morph_progress: float = 0.0
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

    def set_mode(self, mode: str) -> None:
        """Switch reasoning mode (FAST -> WHITE form, DEEP_REASONING -> ARMORED form)."""
        clean = mode.strip().upper()
        self.reasoning_mode = clean
        if clean in ("DEEP", "DEEP_REASONING", "REASONING"):
            self.set_form(BagusmaxForm.ARMORED)
        else:
            self.set_form(BagusmaxForm.WHITE)

    def set_form(self, form: str) -> None:
        """Set target form directly."""
        clean = form.strip().upper()
        if clean in (BagusmaxForm.ARMORED, "RED", "DEEP", "DEEP_REASONING"):
            self.target_form = BagusmaxForm.ARMORED
        else:
            self.target_form = BagusmaxForm.WHITE

    @property
    def elapsed(self) -> float:
        return self.t

    def update(self, dt: float) -> None:
        self.t += dt

        # Smooth morph/transformation progress between WHITE and ARMORED
        if self.character_form != self.target_form:
            self.morph_progress += dt * 2.5
            if self.morph_progress >= 1.0:
                self.character_form = self.target_form
                self.morph_progress = 1.0
        else:
            if self.morph_progress > 0.0:
                self.morph_progress = max(0.0, self.morph_progress - dt * 2.5)

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

        # Breathing: subtle up-down in IDLE/LISTENING/SLEEPING
        breath_y = 0.0
        if s in (AnimState.IDLE, AnimState.LISTENING, AnimState.SLEEPING):
            speed = 0.35 if s == AnimState.SLEEPING else 0.65
            breath_y = math.sin(t * 2 * math.pi * speed) * 0.012

        # Inflatable chest breath scale
        breath_scale = 1.0 + (math.sin(t * 2 * math.pi * 0.65) * 0.02)
        if s == AnimState.SPEAKING:
            breath_scale += a * 0.04

        # Body bob: bouncy in HAPPY/SUCCESS
        bob_y = 0.0
        if s in (AnimState.HAPPY, AnimState.SUCCESS):
            bob_y = abs(math.sin(t * 2 * math.pi * 2.2)) * 0.05
        elif s == AnimState.SPEAKING:
            bob_y = math.sin(t * 14.0) * a * 0.012

        # Lean forward in LISTENING
        lean_x = 0.0
        if s == AnimState.LISTENING:
            lean_x = 0.035

        # Head tilt / nod:
        head_tilt = 0.0
        if s in (AnimState.THINKING, AnimState.DEEP_THINKING, AnimState.CONFUSED):
            head_tilt = math.sin(t * 2 * math.pi * 0.3) * 0.07
        elif s == AnimState.LISTENING:
            head_tilt = 0.05  # curious Baymax head cock

        # Speech synchronization for mouthless Baymax:
        # Subtle head nod pitch during speaking
        head_nod = 0.0
        if s == AnimState.SPEAKING:
            head_nod = math.sin(t * 18.0) * a * 0.04

        # Eyebrow raise (for UI/state compatibility)
        brow_raise = 0.0

        # Blink: every ~4.2s normally, faster when confused/error
        blink_period = 4.2 if s == AnimState.IDLE else 3.0
        blink_phase = (t % blink_period) / blink_period
        blink = max(0.0, 1.0 - abs(blink_phase - 0.02) / 0.008) if blink_phase < 0.03 else 0.0
        if s == AnimState.SLEEPING:
            blink = 1.0

        # Mouth: Baymax has no mouth; mouth_open kept at 0.0 for interface compatibility
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
            "breath_scale": breath_scale,
            "bob_y": bob_y,
            "lean_x": lean_x,
            "head_tilt": head_tilt,
            "head_nod": head_nod,
            "brow_raise": brow_raise,
            "blink": blink,
            "mouth_open": mouth_open,
            "rot_y_extra": rot_y_extra,
            "morph_progress": self.morph_progress,
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
        elif event == "companion.set_mode":
            mode = payload.get("mode", "FAST")
            self.animator.set_mode(mode)
        elif event == "companion.set_form":
            form = payload.get("form", "WHITE")
            self.animator.set_form(form)
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
    glfw.window_hint(glfw.VISIBLE, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)       # always-on-top
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    glfw.window_hint(glfw.FOCUSED, glfw.FALSE)
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

    window = glfw.create_window(WINDOW_W, WINDOW_H, "BAGUSMAX 3D Companion", None, None)
    if not window and hasattr(glfw, "TRANSPARENT_FRAMEBUFFER"):
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.FALSE)
        window = glfw.create_window(WINDOW_W, WINDOW_H, "BAGUSMAX 3D Companion", None, None)
    if not window:
        glfw.terminate()
        print("[BAGUSMAX] Window creation failed", file=sys.stderr)
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

    # Build geometry for specific form
    def rebuild_mesh(form: str, params: dict[str, float]) -> tuple[moderngl.VertexArray, moderngl.Buffer]:
        verts, idxs = (
            build_bagusmax_armored(
                blink=params.get("blink", 0.0),
                head_tilt=params.get("head_tilt", 0.0),
                breath=params.get("breath_scale", 1.0),
            )
            if form == BagusmaxForm.ARMORED
            else build_bagusmax_white(
                blink=params.get("blink", 0.0),
                head_tilt=params.get("head_tilt", 0.0),
                breath=params.get("breath_scale", 1.0),
            )
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

    params = animator.get_params()
    last_rendered_form = animator.character_form
    vao, ibo = rebuild_mesh(last_rendered_form, params)

    # Camera: centered perfectly on BAGUSMAX body (head to feet)
    cam_pos = Vector3([0.0, 0.76, 2.75])
    proj = Matrix44.perspective_projection(38.0, WINDOW_W / WINDOW_H, 0.1, 50.0, dtype="f4")
    view = Matrix44.look_at(cam_pos, Vector3([0.0, 0.76, 0.0]), Vector3([0.0, 1.0, 0.0]), dtype="f4")

    # Lighting
    prog["light_pos"].write(np.array([2.5, 4.0, 3.5], dtype="f4"))
    prog["view_pos"].write(np.array(cam_pos, dtype="f4"))
    if "ambient_strength" in prog:
        prog["ambient_strength"].value = 0.45
    prog["proj"].write(proj)
    prog["view"].write(view)

    last_time = glfw.get_time()
    mesh_rebuild_timer = 0.0

    print("[BAGUSMAX] Render loop started", file=sys.stderr)

    while not glfw.window_should_close(window) and not ipc.should_close():
        now = glfw.get_time()
        dt = now - last_time
        last_time = now

        animator.update(dt)
        mesh_rebuild_timer += dt

        params = animator.get_params()
        current_form = animator.character_form

        # Rebuild mesh on form switch or every ~33ms for smooth animation
        if mesh_rebuild_timer >= 0.033 or current_form != last_rendered_form:
            mesh_rebuild_timer = 0.0
            last_rendered_form = current_form
            vao.release()
            vao, ibo = rebuild_mesh(current_form, params)

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
                print(f"[BAGUSMAX] Captured live popup to {save_p}", file=sys.stderr)
            except Exception as _err:
                print(f"[BAGUSMAX] Screenshot error: {_err}", file=sys.stderr)

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
    print("[BAGUSMAX] Companion closed", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BAGUSMAX 3D Companion Renderer")
    parser.add_argument("--port", type=int, default=7432, help="IPC TCP port")

    args = parser.parse_args()
    run_renderer(args.port)
