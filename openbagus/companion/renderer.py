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

IPC_VERSION = "1.0"

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

from openbagus.companion.preferences import (
    CompanionPreferences,
    load_preferences,
    save_preferences,
    reset_preferences,
)
from openbagus.companion.events import (
    ConversationEventType,
    ConversationState,
    AnimState,
    ReasoningMode,
    CompanionEvent,
    ConversationAnimationBridge,
    STATE_PRIORITIES,
)


# ---------------------------------------------------------------------------
# Shader programs
# ---------------------------------------------------------------------------

VERT_SHADER = """
#version 330 core
in vec3 in_position;
in vec3 in_normal;
in vec3 in_color;
in vec2 in_material;

uniform mat4 model;
uniform mat4 view;
uniform mat4 proj;

out vec3 v_world_pos;
out vec3 v_normal;
out vec3 v_color;
out vec2 v_material;

void main() {
    vec4 world_pos = model * vec4(in_position, 1.0);
    gl_Position = proj * view * world_pos;
    v_world_pos = vec3(world_pos);
    v_normal = normalize(mat3(transpose(inverse(model))) * in_normal);
    v_color = in_color;
    v_material = in_material;
}
"""

FRAG_SHADER = """
#version 330 core
in vec3 v_world_pos;
in vec3 v_normal;
in vec3 v_color;
in vec2 v_material;

uniform vec3 view_pos;
uniform float exposure;

// Studio 3-point lights
uniform vec3 light_pos_key;
uniform vec3 light_col_key;
uniform vec3 light_pos_fill;
uniform vec3 light_col_fill;
uniform vec3 light_pos_rim;
uniform vec3 light_col_rim;

// Environment studio colors
uniform vec3 env_sky_color;
uniform vec3 env_ground_color;

out vec4 out_color;

const float PI = 3.14159265359;

float distribution_ggx(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;
    float num = a2;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = PI * denom * denom;
    return num / max(denom, 0.0001);
}

float geometry_schlick_ggx(float NdotV, float roughness) {
    float r = (roughness + 1.0);
    float k = (r * r) / 8.0;
    float num = NdotV;
    float denom = NdotV * (1.0 - k) + k;
    return num / max(denom, 0.0001);
}

float geometry_smith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float ggx2 = geometry_schlick_ggx(NdotV, roughness);
    float ggx1 = geometry_schlick_ggx(NdotL, roughness);
    return ggx1 * ggx2;
}

vec3 fresnel_schlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

float clearcoat_specular(vec3 N, vec3 V, vec3 L, vec3 H) {
    float D = distribution_ggx(N, H, 0.08);
    float F = 0.04 + (1.0 - 0.04) * pow(clamp(1.0 - max(dot(V, H), 0.0), 0.0, 1.0), 5.0);
    float G = geometry_smith(N, V, L, 0.08);
    float NdotV = max(dot(N, V), 0.001);
    float NdotL = max(dot(N, L), 0.001);
    return (D * F * G) / (4.0 * NdotV * NdotL);
}

vec3 tone_map_aces(vec3 x) {
    float a = 2.51;
    float b = 0.03;
    float c = 2.43;
    float d = 0.59;
    float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

vec3 studio_environment_reflection(vec3 R, float roughness, vec3 F0) {
    float up_factor = clamp(R.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 env_diffuse = mix(env_ground_color, env_sky_color, up_factor);
    vec3 key_dir = normalize(light_pos_key - v_world_pos);
    float refl_dot = max(dot(R, key_dir), 0.0);
    float softbox_spec = pow(refl_dot, mix(128.0, 4.0, roughness)) * (1.0 - roughness * 0.7);
    return env_diffuse + vec3(1.0, 0.98, 0.95) * softbox_spec * 1.8;
}

void main() {
    vec3 N = normalize(v_normal);
    vec3 V = normalize(view_pos - v_world_pos);
    vec3 albedo = pow(v_color, vec3(2.2));
    float metallic = clamp(v_material.x, 0.0, 1.0);
    float roughness = clamp(v_material.y, 0.04, 1.0);

    vec3 F0 = mix(vec3(0.04), albedo, metallic);

    vec3 light_positions[3] = vec3[3](light_pos_key, light_pos_fill, light_pos_rim);
    vec3 light_colors[3] = vec3[3](light_col_key, light_col_fill, light_col_rim);

    vec3 Lo = vec3(0.0);
    for (int i = 0; i < 3; ++i) {
        vec3 L = normalize(light_positions[i] - v_world_pos);
        vec3 H = normalize(V + L);
        float dist = length(light_positions[i] - v_world_pos);
        float attenuation = 1.0 / (1.0 + 0.04 * dist + 0.008 * dist * dist);
        vec3 radiance = light_colors[i] * attenuation;

        float NDF = distribution_ggx(N, H, roughness);
        float G = geometry_smith(N, V, L, roughness);
        vec3 F = fresnel_schlick(max(dot(H, V), 0.0), F0);

        vec3 numerator = NDF * G * F;
        float denominator = 4.0 * max(dot(N, V), 0.0) * max(dot(N, L), 0.0) + 0.0001;
        vec3 specular = numerator / denominator;

        vec3 kS = F;
        vec3 kD = (vec3(1.0) - kS) * (1.0 - metallic);

        float NdotL = max(dot(N, L), 0.0);
        vec3 direct = (kD * albedo / PI + specular) * radiance * NdotL;

        if (roughness < 0.25 && albedo.r > 0.4) {
            float coat = clearcoat_specular(N, V, L, H) * NdotL;
            direct += vec3(coat * 0.4);
        }

        Lo += direct;
    }

    vec3 R = reflect(-V, N);
    vec3 F_env = fresnel_schlick(max(dot(N, V), 0.0), F0);
    vec3 kD_env = (1.0 - F_env) * (1.0 - metallic);

    vec3 env_reflection = studio_environment_reflection(R, roughness, F0);
    vec3 ambient_diffuse = mix(env_ground_color, env_sky_color, clamp(N.y * 0.5 + 0.5, 0.0, 1.0)) * albedo;
    vec3 ambient_specular = env_reflection * F_env * (1.0 - roughness * 0.5);

    vec3 ambient = (kD_env * ambient_diffuse + ambient_specular) * 0.85;

    vec3 color = (ambient + Lo) * exposure;
    color = tone_map_aces(color);
    color = pow(color, vec3(1.0 / 2.2));

    out_color = vec4(color, 1.0);
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


def _transform_mesh(
    mesh: tuple[list[float], list[int]],
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> tuple[list[float], list[int]]:
    """Transform vertices and normals around a 3D pivot using rotation, translation, and scale."""
    verts, idxs = mesh
    if not verts:
        return verts, idxs

    v = np.array(verts, dtype=np.float32).reshape(-1, 9)

    cx, sx = math.cos(rot_x), math.sin(rot_x)
    cy, sy = math.cos(rot_y), math.sin(rot_y)
    cz, sz = math.cos(rot_z), math.sin(rot_z)

    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]], dtype=np.float32)
    Ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float32)
    Rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    R = Ry @ Rx @ Rz

    p = np.array(pivot, dtype=np.float32)
    t = np.array(translation, dtype=np.float32)
    s = np.array(scale, dtype=np.float32)

    pos = v[:, 0:3]
    pos_p = (pos - p) * s
    v[:, 0:3] = pos_p @ R.T + p + t

    nrm = v[:, 3:6]
    v[:, 3:6] = nrm @ R.T

    return v.flatten().tolist(), idxs


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
    head_nod: float = 0.0,
    head_turn: float = 0.0,
    l_arm_pitch: float = 0.0,
    l_arm_roll: float = 0.0,
    l_arm_yaw: float = 0.0,
    r_arm_pitch: float = 0.0,
    r_arm_roll: float = 0.0,
    r_arm_yaw: float = 0.0,
    torso_lean_z: float = 0.0,
    torso_twist_y: float = 0.0,
) -> tuple[list[float], list[int]]:
    """Build BAGUSMAX WHITE Form (FAST Reasoning Mode) with articulated 3D joints.

    Inflatable warm white vinyl robot:
    - Independent articulated head (nod, tilt, turn) around neck pivot (0.0, 1.25, 0.0).
    - Inflatable pear-shaped torso (breath expansion, forward lean, twist).
    - Independent left arm (roll, pitch, yaw) around left shoulder pivot (-0.36, 1.04, 0.0).
    - Independent right arm (roll, pitch, yaw) around right shoulder pivot (0.36, 1.04, 0.0).
    - Columnar legs and rounded feet.
    """
    VINYL_WHITE  = (0.96, 0.96, 0.97)
    BLACK_EYES   = (0.04, 0.04, 0.04)
    PORT_SILVER  = (0.84, 0.84, 0.88)
    PORT_INNER   = (0.70, 0.70, 0.75)

    # 1. HEAD & EYES (Seated at y = 1.34, pivot at neck 1.25)
    head_parts: list[tuple[list[float], list[int]]] = []
    head_parts.append(_make_sphere(0.0, 1.34, 0.0, 0.22, 0.175, 0.185, VINYL_WHITE, lat=16, lon=24))

    # Two black eyes connected by thin line (Baymax signature face)
    eye_y_scale = max(0.1, 1.0 - blink * 0.9)
    head_parts.append(_make_sphere(-0.075, 1.34, 0.178, 0.018, 0.018 * eye_y_scale, 0.008, BLACK_EYES, lat=10, lon=14))
    head_parts.append(_make_sphere(0.075, 1.34, 0.178, 0.018, 0.018 * eye_y_scale, 0.008, BLACK_EYES, lat=10, lon=14))
    head_parts.append(_make_box(0.0, 1.34, 0.179, 0.145, 0.0035, 0.006, BLACK_EYES))
    head_parts.append(_make_cylinder(0.0, 1.20, 1.28, 0.0, 0.16, 0.16, VINYL_WHITE, segs=16))

    head_mesh = _transform_mesh(
        _merge(*head_parts),
        pivot=(0.0, 1.25, 0.0),
        rot_x=head_nod,
        rot_y=head_turn,
        rot_z=head_tilt,
    )

    # 2. PEAR-SHAPED TORSO (Inflatable Vinyl Body)
    bs = max(0.85, min(1.25, breath))
    torso_parts: list[tuple[list[float], list[int]]] = []
    torso_parts.append(_make_sphere(0.0, 1.05, -0.01, 0.32 * bs, 0.25, 0.28 * bs, VINYL_WHITE, lat=16, lon=24))
    torso_parts.append(_make_sphere(0.0, 0.75, 0.05, 0.42 * bs, 0.30, 0.37 * bs, VINYL_WHITE, lat=18, lon=26))
    torso_parts.append(_make_sphere(0.0, 0.52, 0.01, 0.38, 0.22, 0.33, VINYL_WHITE, lat=14, lon=22))
    torso_parts.append(_make_torus(-0.13, 1.10, 0.265, 0.034, 0.006, PORT_SILVER, segs_R=16, segs_r=8, axis="z"))
    torso_parts.append(_make_sphere(-0.13, 1.10, 0.263, 0.028, 0.028, 0.004, PORT_INNER, lat=8, lon=12))

    torso_mesh = _transform_mesh(
        _merge(*torso_parts),
        pivot=(0.0, 0.52, 0.0),
        rot_x=torso_lean_z,
        rot_y=torso_twist_y,
    )

    # 3. LEFT ARM & HAND (Pivot at left shoulder: -0.36, 1.04, 0.0)
    l_arm_parts: list[tuple[list[float], list[int]]] = []
    l_arm_parts.append(_make_sphere(-0.36, 1.04, 0.0, 0.13, 0.13, 0.13, VINYL_WHITE, lat=12, lon=18))
    l_arm_parts.append(_make_cone(-0.40, 0.78, 0.98, 0.01, 0.085, 0.085, 0.100, 0.100, VINYL_WHITE, segs=14))
    l_arm_parts.append(_make_sphere(-0.42, 0.76, 0.02, 0.09, 0.09, 0.09, VINYL_WHITE, lat=10, lon=14))
    l_arm_parts.append(_make_cone(-0.44, 0.54, 0.74, 0.04, 0.075, 0.075, 0.085, 0.085, VINYL_WHITE, segs=14))
    l_arm_parts.append(_make_sphere(-0.45, 0.48, 0.06, 0.070, 0.060, 0.060, VINYL_WHITE, lat=10, lon=14))
    l_arm_parts.append(_make_sphere(-0.43, 0.41, 0.08, 0.024, 0.034, 0.024, VINYL_WHITE, lat=8, lon=12))
    l_arm_parts.append(_make_sphere(-0.46, 0.40, 0.06, 0.024, 0.036, 0.024, VINYL_WHITE, lat=8, lon=12))
    l_arm_parts.append(_make_sphere(-0.49, 0.41, 0.04, 0.022, 0.032, 0.022, VINYL_WHITE, lat=8, lon=12))
    l_arm_parts.append(_make_sphere(-0.39, 0.47, 0.09, 0.025, 0.025, 0.028, VINYL_WHITE, lat=8, lon=12))

    l_arm_mesh = _transform_mesh(
        _merge(*l_arm_parts),
        pivot=(-0.36, 1.04, 0.0),
        rot_x=l_arm_pitch,
        rot_y=l_arm_yaw,
        rot_z=l_arm_roll,
    )

    # 4. RIGHT ARM & HAND (Pivot at right shoulder: 0.36, 1.04, 0.0)
    r_arm_parts: list[tuple[list[float], list[int]]] = []
    r_arm_parts.append(_make_sphere(0.36, 1.04, 0.0, 0.13, 0.13, 0.13, VINYL_WHITE, lat=12, lon=18))
    r_arm_parts.append(_make_cone(0.40, 0.78, 0.98, 0.01, 0.085, 0.085, 0.100, 0.100, VINYL_WHITE, segs=14))
    r_arm_parts.append(_make_sphere(0.42, 0.76, 0.02, 0.09, 0.09, 0.09, VINYL_WHITE, lat=10, lon=14))
    r_arm_parts.append(_make_cone(0.44, 0.54, 0.74, 0.04, 0.075, 0.075, 0.085, 0.085, VINYL_WHITE, segs=14))
    r_arm_parts.append(_make_sphere(0.45, 0.48, 0.06, 0.070, 0.060, 0.060, VINYL_WHITE, lat=10, lon=14))
    r_arm_parts.append(_make_sphere(0.43, 0.41, 0.08, 0.024, 0.034, 0.024, VINYL_WHITE, lat=8, lon=12))
    r_arm_parts.append(_make_sphere(0.46, 0.40, 0.06, 0.024, 0.036, 0.024, VINYL_WHITE, lat=8, lon=12))
    r_arm_parts.append(_make_sphere(0.49, 0.41, 0.04, 0.022, 0.032, 0.022, VINYL_WHITE, lat=8, lon=12))
    r_arm_parts.append(_make_sphere(0.39, 0.47, 0.09, 0.025, 0.025, 0.028, VINYL_WHITE, lat=8, lon=12))

    r_arm_mesh = _transform_mesh(
        _merge(*r_arm_parts),
        pivot=(0.36, 1.04, 0.0),
        rot_x=r_arm_pitch,
        rot_y=r_arm_yaw,
        rot_z=r_arm_roll,
    )

    # 5. LEGS & FEET (Short, columnar, stable)
    legs_parts: list[tuple[list[float], list[int]]] = []
    legs_parts.append(_make_cylinder(-0.18, 0.12, 0.50, 0.0, 0.145, 0.150, VINYL_WHITE, segs=16))
    legs_parts.append(_make_sphere(-0.18, 0.09, 0.07, 0.160, 0.095, 0.200, VINYL_WHITE, lat=12, lon=18))
    legs_parts.append(_make_cylinder(0.18, 0.12, 0.50, 0.0, 0.145, 0.150, VINYL_WHITE, segs=16))
    legs_parts.append(_make_sphere(0.18, 0.09, 0.07, 0.160, 0.095, 0.200, VINYL_WHITE, lat=12, lon=18))
    legs_mesh = _merge(*legs_parts)

    return _merge(head_mesh, torso_mesh, l_arm_mesh, r_arm_mesh, legs_mesh)


def build_bagusmax_armored(
    blink: float = 0.0,
    head_tilt: float = 0.0,
    breath: float = 1.0,
    head_nod: float = 0.0,
    head_turn: float = 0.0,
    l_arm_pitch: float = 0.0,
    l_arm_roll: float = 0.0,
    l_arm_yaw: float = 0.0,
    r_arm_pitch: float = 0.0,
    r_arm_roll: float = 0.0,
    r_arm_yaw: float = 0.0,
    torso_lean_z: float = 0.0,
    torso_twist_y: float = 0.0,
) -> tuple[list[float], list[int]]:
    """Build BAGUSMAX ARMORED Form (DEEP_REASONING Mode) with articulated 3D joints.

    Red armored hero suit:
    - Independent aerodynamic helmet with visor aperture around neck pivot (0.0, 1.25, 0.0).
    - Curved breastplate, 6-plate abdominal armor, stowed back wings and thruster jetpack.
    - Independent left shoulder pauldron, gauntlet, fist around shoulder pivot (-0.42, 1.10, 0.0).
    - Independent right shoulder pauldron, gauntlet, fist around shoulder pivot (0.42, 1.10, 0.0).
    - Heavy knee guards, greaves, armored boots with heel thrusters.
    """
    ARMOR_RED       = (0.86, 0.16, 0.08)
    ARMOR_DARK_RED  = (0.64, 0.10, 0.05)
    PURPLE_ACCENT   = (0.34, 0.18, 0.48)
    GRAPHITE_JOINT  = (0.13, 0.13, 0.15)
    VISOR_WHITE     = (0.95, 0.95, 0.96)
    BLACK_EYES      = (0.04, 0.04, 0.04)
    THRUSTER_YELLOW = (0.98, 0.82, 0.12)

    # 1. HELMET & VISOR (Pivot at neck 1.25)
    head_parts: list[tuple[list[float], list[int]]] = []
    head_parts.append(_make_sphere(0.0, 1.38, -0.01, 0.245, 0.20, 0.22, ARMOR_RED, lat=16, lon=24))
    head_parts.append(_make_box(0.0, 1.38 + 0.16, -0.02, 0.05, 0.05, 0.26, ARMOR_RED))
    head_parts.append(_make_box(-0.25, 1.38, -0.03, 0.035, 0.11, 0.13, ARMOR_RED))
    head_parts.append(_make_box(0.25, 1.38, -0.03, 0.035, 0.11, 0.13, ARMOR_RED))
    head_parts.append(_make_sphere(0.0, 1.38 - 0.03, 0.178, 0.145, 0.105, 0.035, VISOR_WHITE, lat=12, lon=18))

    eye_y_scale = max(0.1, 1.0 - blink * 0.9)
    head_parts.append(_make_sphere(-0.065, 1.38 - 0.03, 0.214, 0.016, 0.016 * eye_y_scale, 0.007, BLACK_EYES, lat=10, lon=14))
    head_parts.append(_make_sphere(0.065, 1.38 - 0.03, 0.214, 0.016, 0.016 * eye_y_scale, 0.007, BLACK_EYES, lat=10, lon=14))
    head_parts.append(_make_box(0.0, 1.38 - 0.03, 0.215, 0.125, 0.0035, 0.006, BLACK_EYES))
    head_parts.append(_make_box(0.0, 1.38 - 0.13, 0.15, 0.24, 0.06, 0.11, ARMOR_RED))
    head_parts.append(_make_cylinder(0.0, 1.18, 1.26, 0.0, 0.16, 0.16, GRAPHITE_JOINT, segs=16))

    head_mesh = _transform_mesh(
        _merge(*head_parts),
        pivot=(0.0, 1.25, 0.0),
        rot_x=head_nod,
        rot_y=head_turn,
        rot_z=head_tilt,
    )

    # 2. CHEST ARMOR, ABDOMINAL PLATES, WINGS & JETPACK
    torso_parts: list[tuple[list[float], list[int]]] = []
    torso_parts.append(_make_sphere(0.0, 1.08, 0.04, 0.36, 0.22, 0.30, ARMOR_RED, lat=16, lon=24))
    torso_parts.append(_make_sphere(-0.15, 1.08, 0.22, 0.16, 0.12, 0.10, ARMOR_RED, lat=12, lon=16))
    torso_parts.append(_make_sphere(0.15, 1.08, 0.22, 0.16, 0.12, 0.10, ARMOR_RED, lat=12, lon=16))
    torso_parts.append(_make_sphere(-0.13, 1.11, 0.28, 0.035, 0.035, 0.006, PURPLE_ACCENT, lat=10, lon=14))

    # Segmented abs insert
    torso_parts.append(_make_box(-0.075, 0.93, 0.28, 0.12, 0.075, 0.05, PURPLE_ACCENT))
    torso_parts.append(_make_box(0.075, 0.93, 0.28, 0.12, 0.075, 0.05, PURPLE_ACCENT))
    torso_parts.append(_make_box(-0.085, 0.83, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))
    torso_parts.append(_make_box(0.085, 0.83, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))
    torso_parts.append(_make_box(-0.085, 0.73, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))
    torso_parts.append(_make_box(0.085, 0.73, 0.31, 0.13, 0.075, 0.05, PURPLE_ACCENT))

    torso_parts.append(_make_sphere(-0.28, 0.82, 0.10, 0.16, 0.24, 0.24, ARMOR_RED, lat=12, lon=18))
    torso_parts.append(_make_sphere(0.28, 0.82, 0.10, 0.16, 0.24, 0.24, ARMOR_RED, lat=12, lon=18))
    torso_parts.append(_make_box(0.0, 0.60, 0.02, 0.44, 0.09, 0.36, ARMOR_RED))
    torso_parts.append(_make_box(0.0, 0.60, 0.20, 0.12, 0.08, 0.04, PURPLE_ACCENT))
    torso_parts.append(_make_sphere(0.0, 0.52, 0.0, 0.32, 0.16, 0.28, GRAPHITE_JOINT, lat=12, lon=18))

    # Stowed wings & jetpack
    torso_parts.append(_make_box(0.0, 1.05, -0.22, 0.26, 0.30, 0.10, ARMOR_DARK_RED))
    torso_parts.append(_make_cylinder(-0.08, 0.90, 1.06, -0.28, 0.045, 0.045, GRAPHITE_JOINT, segs=12))
    torso_parts.append(_make_cylinder(-0.08, 0.88, 0.90, -0.28, 0.035, 0.035, THRUSTER_YELLOW, segs=10))
    torso_parts.append(_make_cylinder(0.08, 0.90, 1.06, -0.28, 0.045, 0.045, GRAPHITE_JOINT, segs=12))
    torso_parts.append(_make_cylinder(0.08, 0.88, 0.90, -0.28, 0.035, 0.035, THRUSTER_YELLOW, segs=10))
    torso_parts.append(_make_box(-0.24, 1.10, -0.19, 0.12, 0.36, 0.04, ARMOR_RED))
    torso_parts.append(_make_box(-0.30, 1.10, -0.19, 0.02, 0.34, 0.04, PURPLE_ACCENT))
    torso_parts.append(_make_box(0.24, 1.10, -0.19, 0.12, 0.36, 0.04, ARMOR_RED))
    torso_parts.append(_make_box(0.30, 1.10, -0.19, 0.02, 0.34, 0.04, PURPLE_ACCENT))

    torso_mesh = _transform_mesh(
        _merge(*torso_parts),
        pivot=(0.0, 0.52, 0.0),
        rot_x=torso_lean_z,
        rot_y=torso_twist_y,
    )

    # 3. LEFT ARMORED ARM & GAUNTLET (Pivot at left shoulder: -0.42, 1.10, 0.0)
    l_arm_parts: list[tuple[list[float], list[int]]] = []
    l_arm_parts.append(_make_sphere(-0.42, 1.10, 0.0, 0.19, 0.19, 0.19, ARMOR_RED, lat=14, lon=20))
    l_arm_parts.append(_make_cylinder(-0.42, 1.21, 1.25, 0.0, 0.14, 0.14, PURPLE_ACCENT, segs=14))
    l_arm_parts.append(_make_cylinder(-0.40, 0.84, 0.98, 0.02, 0.095, 0.095, GRAPHITE_JOINT, segs=14))
    l_arm_parts.append(_make_sphere(-0.43, 0.80, 0.03, 0.09, 0.09, 0.09, GRAPHITE_JOINT, lat=10, lon=14))
    l_arm_parts.append(_make_cone(-0.46, 0.52, 0.76, 0.05, 0.115, 0.115, 0.100, 0.100, ARMOR_RED, segs=16))
    l_arm_parts.append(_make_box(-0.46, 0.72, 0.05, 0.25, 0.05, 0.25, PURPLE_ACCENT))
    l_arm_parts.append(_make_box(-0.46, 0.44, 0.07, 0.12, 0.11, 0.12, GRAPHITE_JOINT))

    l_arm_mesh = _transform_mesh(
        _merge(*l_arm_parts),
        pivot=(-0.42, 1.10, 0.0),
        rot_x=l_arm_pitch,
        rot_y=l_arm_yaw,
        rot_z=l_arm_roll,
    )

    # 4. RIGHT ARMORED ARM & GAUNTLET (Pivot at right shoulder: 0.42, 1.10, 0.0)
    r_arm_parts: list[tuple[list[float], list[int]]] = []
    r_arm_parts.append(_make_sphere(0.42, 1.10, 0.0, 0.19, 0.19, 0.19, ARMOR_RED, lat=14, lon=20))
    r_arm_parts.append(_make_cylinder(0.42, 1.21, 1.25, 0.0, 0.14, 0.14, PURPLE_ACCENT, segs=14))
    r_arm_parts.append(_make_cylinder(0.40, 0.84, 0.98, 0.02, 0.095, 0.095, GRAPHITE_JOINT, segs=14))
    r_arm_parts.append(_make_sphere(0.42, 0.80, 0.03, 0.09, 0.09, 0.09, GRAPHITE_JOINT, lat=10, lon=14))
    r_arm_parts.append(_make_cone(0.46, 0.52, 0.76, 0.05, 0.115, 0.115, 0.100, 0.100, ARMOR_RED, segs=16))
    r_arm_parts.append(_make_box(0.46, 0.72, 0.05, 0.25, 0.05, 0.25, PURPLE_ACCENT))
    r_arm_parts.append(_make_box(0.46, 0.44, 0.07, 0.12, 0.11, 0.12, GRAPHITE_JOINT))

    r_arm_mesh = _transform_mesh(
        _merge(*r_arm_parts),
        pivot=(0.42, 1.10, 0.0),
        rot_x=r_arm_pitch,
        rot_y=r_arm_yaw,
        rot_z=r_arm_roll,
    )

    # 5. LEGS & ARMORED BOOTS
    legs_parts: list[tuple[list[float], list[int]]] = []
    legs_parts.append(_make_cylinder(-0.18, 0.34, 0.54, 0.0, 0.145, 0.150, ARMOR_RED, segs=14))
    legs_parts.append(_make_box(-0.18, 0.34, 0.16, 0.14, 0.12, 0.06, ARMOR_RED))
    legs_parts.append(_make_box(-0.18, 0.34, 0.18, 0.08, 0.08, 0.04, PURPLE_ACCENT))
    legs_parts.append(_make_sphere(-0.18, 0.32, 0.0, 0.12, 0.10, 0.12, GRAPHITE_JOINT, lat=10, lon=14))
    legs_parts.append(_make_cylinder(-0.18, 0.12, 0.32, 0.0, 0.155, 0.160, ARMOR_RED, segs=14))
    legs_parts.append(_make_sphere(-0.18, 0.09, 0.08, 0.165, 0.095, 0.22, ARMOR_RED, lat=12, lon=18))
    legs_parts.append(_make_box(-0.18, 0.025, 0.07, 0.34, 0.045, 0.44, GRAPHITE_JOINT))
    legs_parts.append(_make_cylinder(-0.18, 0.04, 0.10, -0.06, 0.04, 0.04, THRUSTER_YELLOW, segs=10))

    legs_parts.append(_make_cylinder(0.18, 0.34, 0.54, 0.0, 0.145, 0.150, ARMOR_RED, segs=14))
    legs_parts.append(_make_box(0.18, 0.34, 0.16, 0.14, 0.12, 0.06, ARMOR_RED))
    legs_parts.append(_make_box(0.18, 0.34, 0.18, 0.08, 0.08, 0.04, PURPLE_ACCENT))
    legs_parts.append(_make_sphere(0.18, 0.32, 0.0, 0.12, 0.10, 0.12, GRAPHITE_JOINT, lat=10, lon=14))
    legs_parts.append(_make_cylinder(0.18, 0.12, 0.32, 0.0, 0.155, 0.160, ARMOR_RED, segs=14))
    legs_parts.append(_make_sphere(0.18, 0.09, 0.08, 0.165, 0.095, 0.22, ARMOR_RED, lat=12, lon=18))
    legs_parts.append(_make_box(0.18, 0.025, 0.07, 0.34, 0.045, 0.44, GRAPHITE_JOINT))
    legs_parts.append(_make_cylinder(0.18, 0.04, 0.10, -0.06, 0.04, 0.04, THRUSTER_YELLOW, segs=10))
    legs_mesh = _merge(*legs_parts)

    return _merge(head_mesh, torso_mesh, l_arm_mesh, r_arm_mesh, legs_mesh)


# ---------------------------------------------------------------------------
# Character geometry builder: BAGUSMAX Dual-Form (Dispatch)
# ---------------------------------------------------------------------------

def build_character(
    form: str = "WHITE",
    mouth_open: float = 0.0,
    blink: float = 0.0,
    head_tilt: float = 0.0,
    breath: float = 1.0,
    head_nod: float = 0.0,
    head_turn: float = 0.0,
    l_arm_pitch: float = 0.0,
    l_arm_roll: float = 0.0,
    l_arm_yaw: float = 0.0,
    r_arm_pitch: float = 0.0,
    r_arm_roll: float = 0.0,
    r_arm_yaw: float = 0.0,
    torso_lean_z: float = 0.0,
    torso_twist_y: float = 0.0,
) -> tuple[list[float], list[int]]:
    """Build BAGUSMAX 3D companion character with articulated joint support.

    Dispatches to build_bagusmax_armored or build_bagusmax_white based on form.
    """
    if str(form).upper() in (BagusmaxForm.ARMORED, "RED", "DEEP", "DEEP_REASONING"):
        return build_bagusmax_armored(
            blink=blink,
            head_tilt=head_tilt,
            breath=breath,
            head_nod=head_nod,
            head_turn=head_turn,
            l_arm_pitch=l_arm_pitch,
            l_arm_roll=l_arm_roll,
            l_arm_yaw=l_arm_yaw,
            r_arm_pitch=r_arm_pitch,
            r_arm_roll=r_arm_roll,
            r_arm_yaw=r_arm_yaw,
            torso_lean_z=torso_lean_z,
            torso_twist_y=torso_twist_y,
        )
    return build_bagusmax_white(
        blink=blink,
        head_tilt=head_tilt,
        breath=breath,
        head_nod=head_nod,
        head_turn=head_turn,
        l_arm_pitch=l_arm_pitch,
        l_arm_roll=l_arm_roll,
        l_arm_yaw=l_arm_yaw,
        r_arm_pitch=r_arm_pitch,
        r_arm_roll=r_arm_roll,
        r_arm_yaw=r_arm_yaw,
        torso_lean_z=torso_lean_z,
        torso_twist_y=torso_twist_y,
    )


# ---------------------------------------------------------------------------
# Animation state machine
# ---------------------------------------------------------------------------

class CharacterAnimator:
    """Drives articulated 3D animation parameters from conversation state, mode, audio RMS, and elapsed time."""

    def __init__(self) -> None:
        self.state: str = AnimState.IDLE_BREATHING.value
        self.character_form: str = BagusmaxForm.WHITE
        self.target_form: str = BagusmaxForm.WHITE
        self.reasoning_mode: str = "FAST"
        self.morph_progress: float = 0.0
        self.t: float = 0.0  # animation clock
        self.amplitude: float = 0.0  # audio amplitude for speech synchronization
        self.hidden: bool = False
        self.animation_enabled: bool = True
        self.gesture: str = "none"
        self.gesture_timer: float = 0.0

        # Conversation bridge for state & priority management
        self.bridge: ConversationAnimationBridge = ConversationAnimationBridge()

        # Articulated joint states (current interpolated values)
        self.head_tilt: float = 0.0
        self.head_nod: float = 0.0
        self.head_turn: float = 0.0
        self.l_arm_pitch: float = 0.0
        self.l_arm_roll: float = 0.0
        self.l_arm_yaw: float = 0.0
        self.r_arm_pitch: float = 0.0
        self.r_arm_roll: float = 0.0
        self.r_arm_yaw: float = 0.0
        self.torso_lean_z: float = 0.0
        self.torso_twist_y: float = 0.0
        self.breath_scale: float = 1.0
        self.breath_y: float = 0.0
        self.bob_y: float = 0.0
        self.lean_x: float = 0.0
        self.wave_bob: float = 0.0

        # Random idle gesture timer
        self._next_idle_gesture: float = 4.0
        self._idle_gesture: str = "none"

    def set_state(self, state: str) -> None:
        """Set animation state safely, respecting legacy aliases."""
        clean = state.strip().upper()
        if hasattr(AnimState, clean):
            self.state = getattr(AnimState, clean).value
        elif clean in ("HEARD_USER",):
            self.state = AnimState.ACKNOWLEDGING.value
        elif clean in ("LISTENING",):
            self.state = AnimState.ACTIVE_LISTENING.value
        elif clean in ("SPEAKING",):
            self.state = AnimState.SPEECH_GESTURE.value
        elif clean in ("TOOL_WORKING",):
            self.state = AnimState.TOOL_GESTURE.value
        elif clean in ("SURPRISED", "INTERRUPTED"):
            self.state = AnimState.INTERRUPTION_RECOVERY.value
        elif clean in ("IDLE", "SLEEPING"):
            self.state = AnimState.IDLE_BREATHING.value
        else:
            self.state = clean

    def set_mode(self, mode: str) -> None:
        """Switch reasoning mode (FAST -> WHITE form, DEEP_REASONING -> ARMORED form)."""
        clean = mode.strip().upper()
        self.reasoning_mode = clean
        if clean in ("DEEP", "DEEP_REASONING", "REASONING"):
            self.set_form(BagusmaxForm.ARMORED)
            self.bridge.reasoning_mode = ReasoningMode.DEEP_REASONING
        else:
            self.set_form(BagusmaxForm.WHITE)
            self.bridge.reasoning_mode = ReasoningMode.FAST

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
        # Smooth morph/transformation progress between WHITE and ARMORED
        if self.character_form != self.target_form:
            self.morph_progress += dt * 2.5
            if self.morph_progress >= 1.0:
                self.character_form = self.target_form
                self.morph_progress = 1.0
        else:
            if self.morph_progress > 0.0:
                self.morph_progress = max(0.0, self.morph_progress - dt * 2.5)

        if not self.animation_enabled:
            return

        self.t += dt

        if self.gesture_timer > 0.0:
            self.gesture_timer -= dt
            if self.gesture_timer <= 0.0:
                self.gesture = "none"

        # Determine target joint values based on active state and audio
        t = self.t
        s = self.state
        a = self.amplitude

        t_head_tilt = 0.0
        t_head_nod = 0.0
        t_head_turn = 0.0
        t_l_arm_pitch = 0.0
        t_l_arm_roll = 0.0
        t_l_arm_yaw = 0.0
        t_r_arm_pitch = 0.0
        t_r_arm_roll = 0.0
        t_r_arm_yaw = 0.0
        t_torso_lean_z = 0.0
        t_torso_twist_y = 0.0
        t_breath_scale = 1.0
        t_breath_y = 0.0
        t_bob_y = 0.0
        t_lean_x = 0.0

        # 1. State-specific targets
        if s in (AnimState.ACTIVE_LISTENING.value, AnimState.ATTENTIVE.value, "LISTENING"):
            t_torso_lean_z = 0.045
            t_head_tilt = 0.065
            t_head_nod = 0.02
            t_l_arm_roll = -0.04
            t_r_arm_roll = 0.04
            t_breath_y = math.sin(t * 2 * math.pi * 0.5) * 0.008

        elif s in (AnimState.ACKNOWLEDGING.value, "HEARD_USER", AnimState.HEARD_USER.value):
            t_head_nod = 0.11 * max(0.0, math.sin(t * 8.0))
            t_torso_lean_z = 0.02

        elif s in (AnimState.THINKING.value, "THINKING"):
            t_head_tilt = math.sin(t * 1.5) * 0.075
            t_head_nod = -0.035
            t_torso_lean_z = 0.015
            t_r_arm_roll = 0.06

        elif s in (AnimState.DEEP_THINKING.value, "DEEP_THINKING"):
            t_head_tilt = 0.04
            t_head_turn = math.sin(t * 1.2) * 0.06
            t_torso_twist_y = math.sin(t * 1.0) * 0.05
            t_r_arm_pitch = 0.20
            t_r_arm_roll = 0.08

        elif s in (AnimState.TOOL_GESTURE.value, AnimState.TOOL_WORKING.value, "TOOL_WORKING"):
            t_r_arm_pitch = 0.32 + math.sin(t * 3.5) * 0.08
            t_r_arm_roll = 0.14
            t_head_nod = 0.03

        elif s in (AnimState.SPEECH_GESTURE.value, AnimState.SPEAKING.value, "SPEAKING"):
            # Synchronized mouthless Baymax speech motion
            t_head_nod = math.sin(t * 15.0) * a * 0.075
            t_breath_scale = 1.0 + a * 0.05
            t_r_arm_pitch = 0.26 + math.sin(t * 4.0) * a * 0.22
            t_r_arm_roll = 0.12 + math.cos(t * 3.5) * a * 0.10
            t_l_arm_roll = -0.04 - a * 0.04
            t_bob_y = math.sin(t * 14.0) * a * 0.012

        elif s in (AnimState.INTERRUPTION_RECOVERY.value, AnimState.SURPRISED.value, "SURPRISED"):
            t_torso_lean_z = 0.05
            t_head_tilt = 0.07
            t_head_nod = -0.02
            t_l_arm_roll = -0.05
            t_r_arm_roll = 0.05

        elif s in (AnimState.HAPPY_REACTION.value, AnimState.HAPPY.value, "HAPPY"):
            t_bob_y = abs(math.sin(t * 2 * math.pi * 2.2)) * 0.04
            t_head_tilt = math.sin(t * 4.0) * 0.05

        elif s in (AnimState.CONFUSED_REACTION.value, AnimState.CONFUSED.value, "CONFUSED"):
            t_head_tilt = 0.09
            t_head_nod = -0.02

        else:  # IDLE_BREATHING / default
            speed = 0.45
            t_breath_y = math.sin(t * 2 * math.pi * speed) * 0.012
            t_breath_scale = 1.0 + math.sin(t * 2 * math.pi * speed) * 0.02
            t_head_tilt = math.sin(t * 0.8) * 0.015

        # 2. Gestural overlays
        if self.gesture == "wave":
            t_l_arm_roll = -1.15
            t_l_arm_pitch = math.sin(t * 9.0) * 0.28
        elif self.gesture == "nod":
            t_head_nod = math.sin(t * 8.0) * 0.10
        elif self.gesture == "turn":
            t_head_turn = math.sin(t * 4.0) * 0.25

        # 3. Smooth delta-time interpolation (lerp)
        blend_spd = 25.0 if s in (AnimState.INTERRUPTION_RECOVERY.value, "SURPRISED") else 8.0
        self.head_tilt += (t_head_tilt - self.head_tilt) * min(1.0, dt * blend_spd)
        self.head_nod += (t_head_nod - self.head_nod) * min(1.0, dt * blend_spd)
        self.head_turn += (t_head_turn - self.head_turn) * min(1.0, dt * blend_spd)
        self.l_arm_pitch += (t_l_arm_pitch - self.l_arm_pitch) * min(1.0, dt * blend_spd)
        self.l_arm_roll += (t_l_arm_roll - self.l_arm_roll) * min(1.0, dt * blend_spd)
        self.l_arm_yaw += (t_l_arm_yaw - self.l_arm_yaw) * min(1.0, dt * blend_spd)
        self.r_arm_pitch += (t_r_arm_pitch - self.r_arm_pitch) * min(1.0, dt * blend_spd)
        self.r_arm_roll += (t_r_arm_roll - self.r_arm_roll) * min(1.0, dt * blend_spd)
        self.r_arm_yaw += (t_r_arm_yaw - self.r_arm_yaw) * min(1.0, dt * blend_spd)
        self.torso_lean_z += (t_torso_lean_z - self.torso_lean_z) * min(1.0, dt * blend_spd)
        self.torso_twist_y += (t_torso_twist_y - self.torso_twist_y) * min(1.0, dt * blend_spd)
        self.breath_scale += (t_breath_scale - self.breath_scale) * min(1.0, dt * 6.0)
        self.breath_y += (t_breath_y - self.breath_y) * min(1.0, dt * 6.0)
        self.bob_y += (t_bob_y - self.bob_y) * min(1.0, dt * 10.0)
        self.lean_x += (t_lean_x - self.lean_x) * min(1.0, dt * blend_spd)

    def get_params(self) -> dict[str, float]:
        """Return animation parameters for this frame."""
        t = self.t
        s = self.state

        if not self.animation_enabled:
            return {
                "head_tilt": 0.0,
                "head_nod": 0.0,
                "head_turn": 0.0,
                "l_arm_pitch": 0.0,
                "l_arm_roll": 0.0,
                "l_arm_yaw": 0.0,
                "r_arm_pitch": 0.0,
                "r_arm_roll": 0.0,
                "r_arm_yaw": 0.0,
                "torso_lean_z": 0.0,
                "torso_twist_y": 0.0,
                "breath_y": 0.0,
                "breath_scale": 1.0,
                "bob_y": 0.0,
                "lean_x": 0.0,
                "brow_raise": 0.0,
                "blink": 0.0,
                "mouth_open": 0.0,
                "rot_y_extra": 0.0,
                "morph_progress": self.morph_progress,
                "wave_bob": 0.0,
                "animation_enabled": 0.0,
            }

        # Blink: every ~4.2s normally, faster when confused
        blink_period = 4.2 if s == AnimState.IDLE_BREATHING.value else 3.0
        blink_phase = (t % blink_period) / blink_period
        blink = max(0.0, 1.0 - abs(blink_phase - 0.02) / 0.008) if blink_phase < 0.03 else 0.0

        # Subtle rotation wiggle in DEEP_THINKING
        rot_y_extra = 0.0
        if s == AnimState.DEEP_THINKING.value:
            rot_y_extra = math.sin(t * 2 * math.pi * 0.5) * 6.0

        return {
            "head_tilt": self.head_tilt,
            "head_nod": self.head_nod,
            "head_turn": self.head_turn,
            "l_arm_pitch": self.l_arm_pitch,
            "l_arm_roll": self.l_arm_roll,
            "l_arm_yaw": self.l_arm_yaw,
            "r_arm_pitch": self.r_arm_pitch,
            "r_arm_roll": self.r_arm_roll,
            "r_arm_yaw": self.r_arm_yaw,
            "torso_lean_z": self.torso_lean_z,
            "torso_twist_y": self.torso_twist_y,
            "breath_y": self.breath_y,
            "breath_scale": self.breath_scale,
            "bob_y": self.bob_y,
            "lean_x": self.lean_x,
            "brow_raise": 0.0,
            "blink": blink,
            "mouth_open": 0.0,
            "rot_y_extra": rot_y_extra,
            "morph_progress": self.morph_progress,
            "wave_bob": self.wave_bob,
            "animation_enabled": 1.0,
        }


# ---------------------------------------------------------------------------
# Monitor and Window Layout Helpers
# ---------------------------------------------------------------------------

def _get_active_monitors() -> list[Any]:
    try:
        if not glfw.init():
            return []
        return glfw.get_monitors() or []
    except Exception:
        return []


def get_monitor_workarea_safe(monitor: Any) -> tuple[int, int, int, int]:
    """Return (wx, wy, ww, wh) for monitor excluding taskbar/dock."""
    if hasattr(glfw, "get_monitor_workarea"):
        try:
            return glfw.get_monitor_workarea(monitor)
        except Exception:
            pass
    try:
        pos = glfw.get_monitor_pos(monitor)
        mode = glfw.get_video_mode(monitor)
        return pos[0], pos[1], mode.size.width, mode.size.height
    except Exception:
        return 0, 0, 1920, 1032


def calculate_preset_position(
    preset: str, win_w: int, win_h: int, monitor_idx: int = 0
) -> tuple[int, int]:
    """Compute screen coordinates for the 9 standard desktop presets."""
    monitors = _get_active_monitors()
    if not monitors:
        wx, wy, ww, wh = 0, 0, 1920, 1032
    else:
        if monitor_idx < 0 or monitor_idx >= len(monitors):
            monitor_idx = 0
        mon = monitors[monitor_idx]
        wx, wy, ww, wh = get_monitor_workarea_safe(mon)

    pad = 20
    p = preset.strip().lower().replace("_", "-")
    if p in ("top-left", "topleft"):
        return wx + pad, wy + pad
    elif p in ("top-center", "topcenter", "top"):
        return wx + (ww - win_w) // 2, wy + pad
    elif p in ("top-right", "topright"):
        return wx + ww - win_w - pad, wy + pad
    elif p in ("middle-left", "middleleft", "left"):
        return wx + pad, wy + (wh - win_h) // 2
    elif p in ("center", "middle", "middle-center"):
        return wx + (ww - win_w) // 2, wy + (wh - win_h) // 2
    elif p in ("middle-right", "middleright", "right"):
        return wx + ww - win_w - pad, wy + (wh - win_h) // 2
    elif p in ("bottom-left", "bottomleft"):
        return wx + pad, wy + wh - win_h - pad
    elif p in ("bottom-center", "bottomcenter", "bottom"):
        return wx + (ww - win_w) // 2, wy + wh - win_h - pad
    else:  # default "bottom-right", "bottomright"
        return wx + ww - win_w - pad, wy + wh - win_h - pad - 20


def clamp_window_position(
    x: int, y: int, win_w: int, win_h: int, policy: str = "CLAMP_TO_VISIBLE_WORKAREA"
) -> tuple[int, int]:
    """Clamp window position so at least 80px remains accessible on screen."""
    if policy == "FREE_POSITIONING":
        return x, y
    monitors = _get_active_monitors()
    if not monitors:
        wx, wy, ww, wh = 0, 0, 1920, 1032
    else:
        # Find monitor closest to window center
        best_mon = monitors[0]
        best_dist = float("inf")
        win_cx = x + win_w // 2
        win_cy = y + win_h // 2
        for m in monitors:
            m_wx, m_wy, m_ww, m_wh = get_monitor_workarea_safe(m)
            cx = m_wx + m_ww // 2
            cy = m_wy + m_wh // 2
            d = math.hypot(win_cx - cx, win_cy - cy)
            if d < best_dist:
                best_dist = d
                best_mon = m
        wx, wy, ww, wh = get_monitor_workarea_safe(best_mon)

    min_x = wx - win_w + 80
    max_x = wx + ww - 80
    min_y = wy
    max_y = wy + wh - 60
    return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))


# ---------------------------------------------------------------------------
# Interaction Manager (Mouse Dragging, 3D Rotation, Scale, Resize, Presets)
# ---------------------------------------------------------------------------

class InteractionManager:
    """Manages mouse interactions, 3D orientation, sizing, presets, and preferences."""

    def __init__(self, prefs: CompanionPreferences | None = None) -> None:
        self.prefs = prefs or CompanionPreferences()
        self.win_x: int = self.prefs.window_position_x
        self.win_y: int = self.prefs.window_position_y
        self.win_w: int = self.prefs.window_width
        self.win_h: int = self.prefs.window_height
        self.user_yaw: float = float(self.prefs.yaw_degrees)
        self.user_pitch: float = float(self.prefs.pitch_degrees)
        self.character_scale: float = float(self.prefs.character_scale)
        self.interactive_mode: bool = self.prefs.interactive_mode
        self.placement_policy: str = self.prefs.placement_policy
        self.monitor_index: int = self.prefs.monitor_index

        self.dirty: bool = False
        self.last_save_time: float = 0.0

        # Mouse dragging state
        self.left_pressed: bool = False
        self.is_left_dragging: bool = False
        self.drag_grab_offset_x: float = 0.0
        self.drag_grab_offset_y: float = 0.0
        self.drag_start_screen_x: float = 0.0
        self.drag_start_screen_y: float = 0.0
        self.last_left_click_time: float = 0.0

        # Mouse 3D rotation state
        self.right_pressed: bool = False
        self.is_right_dragging: bool = False
        self.rot_start_cx: float = 0.0
        self.rot_start_cy: float = 0.0
        self.rot_start_yaw: float = 0.0
        self.rot_start_pitch: float = 0.0

    def handle_mouse_button(self, window: Any, button: int, action: int, mods: int) -> None:
        if not self.interactive_mode:
            return

        cx, cy = glfw.get_cursor_pos(window)
        wx, wy = glfw.get_window_pos(window)

        if button == glfw.MOUSE_BUTTON_LEFT:
            if action == glfw.PRESS:
                self.left_pressed = True
                self.is_left_dragging = False
                self.drag_grab_offset_x = cx
                self.drag_grab_offset_y = cy
                self.drag_start_screen_x = wx + cx
                self.drag_start_screen_y = wy + cy
            elif action == glfw.RELEASE:
                self.left_pressed = False
                if self.is_left_dragging:
                    self.is_left_dragging = False
                    self.save_now()
                else:
                    # Double-click detection to reset orientation to front
                    now = glfw.get_time()
                    if now - self.last_left_click_time < 0.35:
                        self.user_yaw = 0.0
                        self.user_pitch = 0.0
                        self.save_now()
                    self.last_left_click_time = now

        elif button == glfw.MOUSE_BUTTON_RIGHT:
            if action == glfw.PRESS:
                self.right_pressed = True
                self.is_right_dragging = False
                self.rot_start_cx = cx
                self.rot_start_cy = cy
                self.rot_start_yaw = self.user_yaw
                self.rot_start_pitch = self.user_pitch
            elif action == glfw.RELEASE:
                self.right_pressed = False
                if self.is_right_dragging:
                    self.is_right_dragging = False
                    self.save_now()

    def handle_cursor_pos(self, window: Any, xpos: float, ypos: float) -> None:
        if not self.interactive_mode:
            return

        if self.left_pressed:
            wx, wy = glfw.get_window_pos(window)
            screen_x = wx + xpos
            screen_y = wy + ypos
            dist = math.hypot(screen_x - self.drag_start_screen_x, screen_y - self.drag_start_screen_y)
            if dist > 4.0:
                self.is_left_dragging = True
                target_x = int(screen_x - self.drag_grab_offset_x)
                target_y = int(screen_y - self.drag_grab_offset_y)
                clamped_x, clamped_y = clamp_window_position(
                    target_x, target_y, self.win_w, self.win_h, self.placement_policy
                )
                glfw.set_window_pos(window, clamped_x, clamped_y)
                self.win_x = clamped_x
                self.win_y = clamped_y
                self.dirty = True

        elif self.right_pressed:
            dx = xpos - self.rot_start_cx
            dy = ypos - self.rot_start_cy
            if abs(dx) > 2.0 or abs(dy) > 2.0:
                self.is_right_dragging = True
                # Sensitivity: 0.45 degrees per pixel
                self.user_yaw = (self.rot_start_yaw + dx * 0.45) % 360.0
                self.user_pitch = max(-65.0, min(65.0, self.rot_start_pitch + dy * 0.45))
                self.dirty = True

    def handle_scroll(self, window: Any, xoffset: float, yoffset: float) -> None:
        if not self.interactive_mode:
            return

        alt_pressed = (
            glfw.get_key(window, glfw.KEY_LEFT_ALT) == glfw.PRESS
            or glfw.get_key(window, glfw.KEY_RIGHT_ALT) == glfw.PRESS
        )

        if alt_pressed:
            # Alt + scroll: resize popup window proportionally
            if yoffset > 0:
                new_w = min(1200, self.win_w + 24)
            else:
                new_w = max(240, self.win_w - 24)
            new_h = int(new_w * (560 / 480))
            self.set_window_size(new_w, new_h, window)
        else:
            # Normal scroll: scale character body
            if yoffset > 0:
                self.character_scale = min(2.0, self.character_scale + 0.05)
            else:
                self.character_scale = max(0.5, self.character_scale - 0.05)
            self.dirty = True

    def handle_cursor_enter(self, window: Any, entered: int) -> None:
        if not entered:
            # If mouse left window during rapid drag without button release, keep state until released
            pass

    def set_position(self, x: int, y: int, window: Any = None) -> None:
        cx, cy = clamp_window_position(x, y, self.win_w, self.win_h, self.placement_policy)
        self.win_x = cx
        self.win_y = cy
        if window:
            glfw.set_window_pos(window, cx, cy)
        self.save_now()

    def set_preset(self, preset: str, monitor_idx: int = 0, window: Any = None) -> None:
        px, py = calculate_preset_position(preset, self.win_w, self.win_h, monitor_idx)
        self.monitor_index = monitor_idx
        self.set_position(px, py, window)

    def set_window_size(self, w: int, h: int, window: Any = None) -> None:
        self.win_w = max(240, min(1200, int(w)))
        self.win_h = max(280, min(1400, int(h)))
        if window:
            glfw.set_window_size(window, self.win_w, self.win_h)
        self.save_now()

    def set_scale(self, scale: float) -> None:
        self.character_scale = max(0.5, min(2.0, float(scale)))
        self.save_now()

    def set_rotation(self, yaw: float | None = None, pitch: float | None = None) -> None:
        if yaw is not None:
            self.user_yaw = float(yaw) % 360.0
        if pitch is not None:
            self.user_pitch = max(-65.0, min(65.0, float(pitch)))
        self.save_now()

    def reset_rotation(self) -> None:
        self.user_yaw = 0.0
        self.user_pitch = 0.0
        self.save_now()

    def set_view(self, view_name: str) -> None:
        v = view_name.strip().lower()
        if v == "front":
            self.user_yaw = 0.0
            self.user_pitch = 0.0
        elif v in ("back", "rear"):
            self.user_yaw = 180.0
            self.user_pitch = 0.0
        elif v in ("left", "three-quarter-left"):
            self.user_yaw = 270.0
            self.user_pitch = 0.0
        elif v in ("right", "three-quarter-right"):
            self.user_yaw = 90.0
            self.user_pitch = 0.0
        elif v == "top":
            self.user_yaw = 0.0
            self.user_pitch = -50.0
        elif v == "bottom":
            self.user_yaw = 0.0
            self.user_pitch = 45.0
        elif v == "reset":
            self.user_yaw = 0.0
            self.user_pitch = 0.0
        self.save_now()

    def set_interactive(self, interactive: bool, window: Any = None) -> None:
        self.interactive_mode = bool(interactive)
        if window and hasattr(glfw, "MOUSE_PASSTHROUGH"):
            passthrough = glfw.FALSE if self.interactive_mode else glfw.TRUE
            glfw.set_window_attrib(window, glfw.MOUSE_PASSTHROUGH, passthrough)
        self.save_now()

    def reset_all(self, window: Any = None) -> None:
        self.user_yaw = 8.0
        self.user_pitch = 0.0
        self.character_scale = 1.0
        self.win_w = 480
        self.win_h = 560
        self.interactive_mode = True
        self.placement_policy = "CLAMP_TO_VISIBLE_WORKAREA"
        if window:
            glfw.set_window_size(window, self.win_w, self.win_h)
            self.set_preset("bottom-right", 0, window)
            self.set_interactive(True, window)
        self.save_now()

    def flush_save_if_needed(self, force: bool = False) -> None:
        now = time.time()
        if self.dirty and (force or (now - self.last_save_time >= 1.0)):
            self.save_now()

    def save_now(self) -> None:
        self.prefs.window_position_x = self.win_x
        self.prefs.window_position_y = self.win_y
        self.prefs.window_width = self.win_w
        self.prefs.window_height = self.win_h
        self.prefs.character_scale = self.character_scale
        self.prefs.yaw_degrees = self.user_yaw
        self.prefs.pitch_degrees = self.user_pitch
        self.prefs.interactive_mode = self.interactive_mode
        self.prefs.placement_policy = self.placement_policy
        self.prefs.monitor_index = self.monitor_index
        save_preferences(self.prefs)
        self.dirty = False
        self.last_save_time = time.time()

    def get_transform_dict(self) -> dict[str, Any]:
        return {
            "win_x": self.win_x,
            "win_y": self.win_y,
            "win_w": self.win_w,
            "win_h": self.win_h,
            "user_yaw": round(self.user_yaw, 1),
            "user_pitch": round(self.user_pitch, 1),
            "character_scale": round(self.character_scale, 2),
            "interactive_mode": self.interactive_mode,
            "placement_policy": self.placement_policy,
            "monitor_index": self.monitor_index,
        }


# ---------------------------------------------------------------------------
# IPC Server (runs in background thread, feeds command queue to main thread)
# ---------------------------------------------------------------------------

class IPCServer:
    """TCP server that receives companion events from OpenBagus CLI."""

    def __init__(
        self,
        port: int,
        animator: CharacterAnimator,
        running_flag: list[bool] | None = None,
        interaction: InteractionManager | None = None,
    ) -> None:
        self.port = port
        self.animator = animator
        self.running_flag = running_flag if running_flag is not None else [True]
        self.interaction = interaction
        self._window_should_show: bool = True
        self._window_should_hide: bool = False
        self._window_should_close: bool = False
        self._screenshot_queue: list[str] = []
        self._command_queue: list[tuple[str, dict[str, Any]]] = []
        self._queue_lock = threading.Lock()

    def drain_commands(self) -> list[tuple[str, dict[str, Any]]]:
        with self._queue_lock:
            cmds = self._command_queue[:]
            self._command_queue.clear()
            return cmds

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
                    resp = self._dispatch(line.decode("utf-8", errors="replace"))
                    if resp is not None:
                        try:
                            conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
                        except Exception:
                            pass

    def _dispatch(self, raw: str | dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            msg = raw
        else:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None

        event = msg.get("type", "")
        payload = msg.get("payload", {})

        if event == "companion.ping":
            diag = {}
            try:
                from openbagus.companion.model_loader import get_asset_diagnostics
                diag = get_asset_diagnostics(self.animator.character_form)
            except Exception:
                pass
            return {
                "status": "ok",
                "app": "openbagus_companion",
                "version": IPC_VERSION,
                "pid": os.getpid(),
                "model_source": "CODEX_GLB",
                "model_loaded": True,
                "form": self.animator.character_form,
                "diagnostics": diag,
            }

        elif event == "companion.diagnostics":
            diag = {}
            try:
                from openbagus.companion.model_loader import get_asset_diagnostics
                diag = get_asset_diagnostics(self.animator.character_form)
            except Exception as e:
                diag = {"error": str(e)}
            return {"status": "ok", "diagnostics": diag}

        elif event == "companion.conversation_event":
            try:
                ev = CompanionEvent.from_dict(payload)
                cs, anim_st, changed = self.animator.bridge.process_event(ev)
                self.animator.set_state(anim_st.value)
                self.animator.amplitude = self.animator.bridge.audio_amplitude
                if ev.event_type == ConversationEventType.MODE_CONFIRMED.value:
                    m = str(ev.payload.get("mode", "FAST"))
                    self.animator.set_mode(m)
                elif ev.event_type == ConversationEventType.USER_INTERRUPTED.value:
                    self.animator.amplitude = 0.0
                    self.animator.set_state(AnimState.INTERRUPTION_RECOVERY.value)
                elif ev.event_type == ConversationEventType.TTS_PLAYBACK_LEVEL.value:
                    self.animator.amplitude = float(ev.payload.get("amplitude", 0.0))
            except Exception as _err:
                print(f"[CompanionIPC] conversation_event error: {_err}", file=sys.stderr)
            return {"status": "ok"}

        elif event == "companion.set_state":
            state = payload.get("state", "IDLE")
            self.animator.set_state(state)
        elif event == "companion.speak_start":
            self.animator.set_state("SPEAKING")
        elif event == "companion.speak_amplitude":
            self.animator.amplitude = float(payload.get("amplitude", 0.0))
        elif event == "companion.speak_end":
            self.animator.set_state("IDLE")
            self.animator.amplitude = 0.0
        elif event == "companion.interrupted":
            self.animator.set_state("SURPRISED")
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
            self.animator.set_state("IDLE")
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

        # Interactive Transform & Control Events
        elif event == "companion.set_position":
            with self._queue_lock:
                self._command_queue.append(("set_position", payload))
        elif event == "companion.set_window_size":
            with self._queue_lock:
                self._command_queue.append(("set_window_size", payload))
        elif event == "companion.set_character_scale":
            with self._queue_lock:
                self._command_queue.append(("set_character_scale", payload))
        elif event == "companion.set_rotation":
            with self._queue_lock:
                self._command_queue.append(("set_rotation", payload))
        elif event == "companion.reset_rotation":
            with self._queue_lock:
                self._command_queue.append(("reset_rotation", payload))
        elif event == "companion.set_view":
            with self._queue_lock:
                self._command_queue.append(("set_view", payload))
        elif event == "companion.set_interactive":
            with self._queue_lock:
                self._command_queue.append(("set_interactive", payload))
        elif event == "companion.set_animation_enabled":
            with self._queue_lock:
                self._command_queue.append(("set_animation_enabled", payload))
        elif event == "companion.trigger_gesture":
            with self._queue_lock:
                self._command_queue.append(("trigger_gesture", payload))
        elif event == "companion.save_preferences":
            with self._queue_lock:
                self._command_queue.append(("save_preferences", payload))
        elif event == "companion.reset_preferences":
            with self._queue_lock:
                self._command_queue.append(("reset_preferences", payload))
        elif event == "companion.reset_transform":
            with self._queue_lock:
                self._command_queue.append(("reset_transform", payload))

        elif event == "companion.get_transform_state":
            st = self.interaction.get_transform_dict() if self.interaction else {}
            st.update({
                "character_form": self.animator.character_form,
                "reasoning_mode": self.animator.reasoning_mode,
                "animation_enabled": self.animator.animation_enabled,
            })
            return {"status": "ok", "transform": st}

        return None


# ---------------------------------------------------------------------------
# Main render loop
# ---------------------------------------------------------------------------

def run_renderer(port: int) -> None:
    if not HAS_GL:
        print(f"[ShowOpenBagus] Missing dependency: {_MISSING}", file=sys.stderr)
        sys.exit(1)

    if not glfw.init():
        print("[ShowOpenBagus] GLFW init failed", file=sys.stderr)
        sys.exit(1)

    prefs = load_preferences()
    interaction = InteractionManager(prefs)

    # Resolve target monitor and position
    monitors = glfw.get_monitors()
    mon_idx = interaction.monitor_index if 0 <= interaction.monitor_index < len(monitors) else 0
    if interaction.win_x < 0 or interaction.win_y < 0:
        win_x, win_y = calculate_preset_position("bottom-right", interaction.win_w, interaction.win_h, mon_idx)
    else:
        win_x, win_y = clamp_window_position(
            interaction.win_x, interaction.win_y, interaction.win_w, interaction.win_h, interaction.placement_policy
        )
    interaction.win_x, interaction.win_y = win_x, win_y

    # Request OpenGL 3.3 Core (moderngl requirement)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.VISIBLE, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)       # always-on-top
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)     # resizing handled by Alt+scroll / IPC
    glfw.window_hint(glfw.FOCUSED, glfw.FALSE)
    glfw.window_hint(glfw.FOCUS_ON_SHOW, glfw.FALSE)  # don't steal focus
    if hasattr(glfw, "TRANSPARENT_FRAMEBUFFER"):
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    if hasattr(glfw, "MOUSE_PASSTHROUGH") and not interaction.interactive_mode:
        glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)
    glfw.window_hint(glfw.SAMPLES, 4)  # MSAA

    window = glfw.create_window(interaction.win_w, interaction.win_h, "BAGUSMAX 3D Companion", None, None)
    if not window and hasattr(glfw, "TRANSPARENT_FRAMEBUFFER"):
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.FALSE)
        window = glfw.create_window(interaction.win_w, interaction.win_h, "BAGUSMAX 3D Companion", None, None)
    if not window:
        glfw.terminate()
        print("[BAGUSMAX] Window creation failed", file=sys.stderr)
        sys.exit(1)

    glfw.set_window_pos(window, win_x, win_y)
    glfw.make_context_current(window)
    glfw.swap_interval(1)  # vsync

    # Register interaction callbacks
    glfw.set_window_focus_callback(window, lambda w, focused: None)
    glfw.set_mouse_button_callback(window, interaction.handle_mouse_button)
    glfw.set_cursor_pos_callback(window, interaction.handle_cursor_pos)
    glfw.set_scroll_callback(window, interaction.handle_scroll)
    glfw.set_cursor_enter_callback(window, interaction.handle_cursor_enter)

    ctx = moderngl.create_context()
    ctx.enable(moderngl.DEPTH_TEST)

    prog = ctx.program(vertex_shader=VERT_SHADER, fragment_shader=FRAG_SHADER)

    animator = CharacterAnimator()
    running_flag: list[bool] = [True]
    ipc = IPCServer(port=port, animator=animator, running_flag=running_flag, interaction=interaction)
    ipc.start()

    # Build geometry for specific form using authentic Codex GLB assets
    def rebuild_mesh(form: str, params: dict[str, float]) -> tuple[moderngl.VertexArray, moderngl.Buffer]:
        try:
            from openbagus.companion.model_loader import build_articulated_mesh
            v_data, i_data = build_articulated_mesh(form, params)
            vbo = ctx.buffer(v_data.astype("f4").tobytes())
            ibo = ctx.buffer(i_data.astype("i4").tobytes())
            vao = ctx.vertex_array(
                prog,
                [(vbo, "3f 3f 3f 2f", "in_position", "in_normal", "in_color", "in_material")],
                index_buffer=ibo,
            )
            return vao, ibo
        except Exception as exc:
            err_msg = f"CODEX_GLB_LOAD_FAILED: {exc}"
            print(f"[{err_msg}] Form: {form}", file=sys.stderr, flush=True)
            raise RuntimeError(err_msg) from exc

    params = animator.get_params()
    last_rendered_form = animator.character_form
    vao, ibo = rebuild_mesh(last_rendered_form, params)

    # Camera: centered on authentic Codex BAGUSMAX body (center Y=0.85, height 1.68m)
    cam_pos = Vector3([0.0, 0.85, 2.85])
    last_fb_w, last_fb_h = glfw.get_framebuffer_size(window)
    proj = Matrix44.perspective_projection(38.0, last_fb_w / last_fb_h if last_fb_h else 1.0, 0.1, 50.0, dtype="f4")
    view = Matrix44.look_at(cam_pos, Vector3([0.0, 0.85, 0.0]), Vector3([0.0, 1.0, 0.0]), dtype="f4")

    # Studio 3-point lighting & PBR Environment
    prog["proj"].write(proj)
    prog["view"].write(view)
    prog["view_pos"].write(np.array(cam_pos, dtype="f4"))

    if "exposure" in prog:
        prog["exposure"].value = 1.15
    if "light_pos_key" in prog:
        prog["light_pos_key"].write(np.array([2.8, 3.8, 3.2], dtype="f4"))
        prog["light_col_key"].write(np.array([1.0, 0.98, 0.95], dtype="f4") * 3.5)
    if "light_pos_fill" in prog:
        prog["light_pos_fill"].write(np.array([-2.5, 1.5, 2.2], dtype="f4"))
        prog["light_col_fill"].write(np.array([0.85, 0.92, 1.0], dtype="f4") * 1.5)
    if "light_pos_rim" in prog:
        prog["light_pos_rim"].write(np.array([0.0, 4.0, -3.5], dtype="f4"))
        prog["light_col_rim"].write(np.array([1.0, 0.95, 0.9], dtype="f4") * 2.8)
    if "env_sky_color" in prog:
        prog["env_sky_color"].write(np.array([0.35, 0.40, 0.48], dtype="f4"))
    if "env_ground_color" in prog:
        prog["env_ground_color"].write(np.array([0.12, 0.14, 0.18], dtype="f4"))
    if "ambient_strength" in prog:
        prog["ambient_strength"].value = 0.45
    if "light_pos" in prog:
        prog["light_pos"].write(np.array([2.5, 4.0, 3.5], dtype="f4"))

    last_time = glfw.get_time()
    mesh_rebuild_timer = 0.0

    print("[BAGUSMAX] Interactive Render loop started", file=sys.stderr)

    while not glfw.window_should_close(window) and not ipc.should_close():
        now = glfw.get_time()
        dt = now - last_time
        last_time = now

        # Execute queued IPC commands on main render thread
        cmds = ipc.drain_commands()
        for cmd, pld in cmds:
            if cmd == "set_position":
                if "preset" in pld:
                    interaction.set_preset(pld["preset"], pld.get("monitor", interaction.monitor_index), window)
                elif "x" in pld and "y" in pld:
                    interaction.set_position(pld["x"], pld["y"], window)
            elif cmd == "set_window_size":
                interaction.set_window_size(pld.get("width", 480), pld.get("height", 560), window)
            elif cmd == "set_character_scale":
                interaction.set_scale(pld.get("scale", 1.0))
            elif cmd == "set_rotation":
                interaction.set_rotation(pld.get("yaw"), pld.get("pitch"))
            elif cmd == "reset_rotation":
                interaction.reset_rotation()
            elif cmd == "set_view":
                interaction.set_view(pld.get("view", "front"))
            elif cmd == "set_interactive":
                interaction.set_interactive(pld.get("interactive", True), window)
            elif cmd == "set_animation_enabled":
                animator.animation_enabled = bool(pld.get("enabled", True))
            elif cmd == "trigger_gesture":
                animator.gesture = str(pld.get("gesture", "wave"))
                animator.gesture_timer = 2.0
            elif cmd == "save_preferences":
                interaction.save_now()
            elif cmd == "reset_preferences":
                interaction.reset_all(window)
            elif cmd == "reset_transform":
                interaction.reset_all(window)

        # Handle viewport & projection update on framebuffer resize
        fb_w, fb_h = glfw.get_framebuffer_size(window)
        if fb_w > 0 and fb_h > 0 and (fb_w != last_fb_w or fb_h != last_fb_h):
            last_fb_w, last_fb_h = fb_w, fb_h
            ctx.viewport = (0, 0, fb_w, fb_h)
            proj = Matrix44.perspective_projection(38.0, fb_w / fb_h, 0.1, 50.0, dtype="f4")
            prog["proj"].write(proj)

        # Throttled preferences save
        interaction.flush_save_if_needed()

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

        # Decouple User Transform (scale, yaw, pitch around body center) from Local Animation Transform
        T_pivot_inv = Matrix44.from_translation([0.0, -0.85, 0.0], dtype="f4")
        T_pivot = Matrix44.from_translation([0.0, 0.85, 0.0], dtype="f4")
        S_user = Matrix44.from_scale(
            [interaction.character_scale, interaction.character_scale, interaction.character_scale], dtype="f4"
        )
        R_pitch = Matrix44.from_x_rotation(math.radians(interaction.user_pitch), dtype="f4")
        R_yaw = Matrix44.from_y_rotation(math.radians(interaction.user_yaw), dtype="f4")

        # Stable user orientation around center (0, 0.85, 0)
        user_transform = T_pivot_inv @ S_user @ R_pitch @ R_yaw @ T_pivot

        # Local animation pose (breath, bob, lean, subtle ambient rotation)
        rot_anim = params.get("rot_y_extra", 0.0) if animator.animation_enabled else 0.0
        anim_y = (params["breath_y"] + params["bob_y"] + params.get("wave_bob", 0.0)) if animator.animation_enabled else 0.0
        anim_lean = params["lean_x"] if animator.animation_enabled else 0.0

        anim_transform = (
            Matrix44.from_translation([anim_lean, anim_y, 0.0], dtype="f4")
            @ Matrix44.from_y_rotation(math.radians(rot_anim), dtype="f4")
        )

        model = anim_transform @ user_transform
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
                shot_img = PIL.Image.frombytes("RGBA", (fb_w, fb_h), data).transpose(PIL.Image.FLIP_TOP_BOTTOM)
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

    # Flush final preferences before exit
    interaction.save_now()
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

