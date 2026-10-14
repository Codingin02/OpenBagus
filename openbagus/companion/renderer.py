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
    // Ambient
    vec3 ambient = ambient_strength * v_color;

    // Diffuse (cartoon: clamped for toon shading)
    vec3 norm = normalize(v_normal);
    vec3 light_dir = normalize(light_pos - v_fragpos);
    float diff_raw = max(dot(norm, light_dir), 0.0);
    // Quantize diffuse for cartoon look
    float diff = step(0.3, diff_raw) * 0.5 + step(0.7, diff_raw) * 0.5;
    vec3 diffuse = diff * v_color;

    // Specular (soft, cartoon)
    vec3 view_dir = normalize(view_pos - v_fragpos);
    vec3 reflect_dir = reflect(-light_dir, norm);
    float spec = pow(max(dot(view_dir, reflect_dir), 0.0), 16.0);
    vec3 specular = spec * 0.3 * vec3(1.0, 1.0, 1.0);

    vec3 result = ambient + diffuse + specular;
    // Gamma correction
    result = pow(result, vec3(1.0 / 2.2));
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
    """Generate rounded-ish box (actually a box) vertices and indices."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    # 8 corners
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
# Character geometry builder
# ---------------------------------------------------------------------------

def build_character(mouth_open: float = 0.0, blink: float = 0.0) -> tuple[list[float], list[int]]:
    """Build the full SHOW OPENBAGUS character geometry.

    Args:
        mouth_open: 0.0=closed, 1.0=fully open (for lip sync)
        blink: 0.0=open, 1.0=fully closed (for blink animation)

    Colors (RGB 0-1):
        - Black: (0.05, 0.05, 0.05) — cap, shirt
        - Blue: (0.15, 0.30, 0.75) — overalls
        - Skin: (0.95, 0.75, 0.55) — face, hands
        - White: (0.95, 0.95, 0.95) — gloves, eyes, teeth
        - Brown: (0.40, 0.22, 0.08) — boots, moustache
        - Gold/Yellow: (0.95, 0.80, 0.10) — cap B emblem (white for contrast)
        - Red sclera: (0.85, 0.20, 0.20) — not used (eyes are white/blue)
    """
    BLACK  = (0.05, 0.05, 0.05)
    BLUE   = (0.15, 0.30, 0.75)
    SKIN   = (0.95, 0.75, 0.55)
    WHITE  = (0.95, 0.95, 0.95)
    BROWN  = (0.40, 0.22, 0.08)
    EYE_B  = (0.10, 0.35, 0.80)  # iris blue
    PUPIL  = (0.05, 0.05, 0.05)
    EMBLEM = (0.95, 0.95, 0.95)  # white B emblem on black cap

    meshes = []

    # --- Head (large rounded sphere, slightly flattened) ---
    meshes.append(_make_sphere(0, 1.40, 0, 0.38, 0.36, 0.35, SKIN, lat=16, lon=24))

    # --- Nose (big round cartoon nose centered) ---
    meshes.append(_make_sphere(0, 1.38, 0.32, 0.10, 0.10, 0.09, SKIN, lat=10, lon=16))

    # --- Left eye white ---
    meshes.append(_make_sphere(-0.13, 1.50, 0.29, 0.085, 0.085, 0.06, WHITE, lat=8, lon=14))
    # --- Left iris ---
    meshes.append(_make_sphere(-0.13, 1.50, 0.345, 0.055, 0.055, 0.03, EYE_B, lat=6, lon=12))
    # --- Left pupil ---
    meshes.append(_make_sphere(-0.13, 1.50, 0.37, 0.030, 0.030, 0.020, PUPIL, lat=5, lon=10))
    # --- Left eyelid (blink) ---
    if blink > 0.05:
        lid_ry = 0.085 * blink * 0.5 + 0.01
        meshes.append(_make_sphere(-0.13, 1.50 + 0.04 * (1 - blink), 0.33, 0.085, lid_ry, 0.06, SKIN))

    # --- Right eye white ---
    meshes.append(_make_sphere(0.13, 1.50, 0.29, 0.085, 0.085, 0.06, WHITE, lat=8, lon=14))
    # --- Right iris ---
    meshes.append(_make_sphere(0.13, 1.50, 0.345, 0.055, 0.055, 0.03, EYE_B, lat=6, lon=12))
    # --- Right pupil ---
    meshes.append(_make_sphere(0.13, 1.50, 0.37, 0.030, 0.030, 0.020, PUPIL, lat=5, lon=10))
    # --- Right eyelid (blink) ---
    if blink > 0.05:
        meshes.append(_make_sphere(0.13, 1.50 + 0.04 * (1 - blink), 0.33, 0.085, 0.085 * blink * 0.5 + 0.01, 0.06, SKIN))

    # --- Left eyebrow (thick brown arch) ---
    meshes.append(_make_sphere(-0.13, 1.60, 0.28, 0.095, 0.020, 0.025, BROWN))
    # --- Right eyebrow ---
    meshes.append(_make_sphere(0.13, 1.60, 0.28, 0.095, 0.020, 0.025, BROWN))

    # --- Moustache (thick, two-lobed) ---
    meshes.append(_make_sphere(-0.10, 1.28, 0.30, 0.10, 0.045, 0.06, BROWN))
    meshes.append(_make_sphere(0.10, 1.28, 0.30, 0.10, 0.045, 0.06, BROWN))

    # --- Mouth (simple — opened oval when mouth_open > 0) ---
    mouth_ry = 0.015 + mouth_open * 0.055
    meshes.append(_make_sphere(0, 1.215, 0.32, 0.07, mouth_ry, 0.05, (0.15, 0.05, 0.05)))
    if mouth_open > 0.2:
        # Teeth glimpse
        meshes.append(_make_sphere(0, 1.22, 0.34, 0.05, mouth_ry * 0.4, 0.035, WHITE))

    # --- Round cheeks (slight pink blush) ---
    BLUSH = (0.97, 0.72, 0.62)
    meshes.append(_make_sphere(-0.26, 1.36, 0.22, 0.08, 0.05, 0.04, BLUSH))
    meshes.append(_make_sphere(0.26, 1.36, 0.22, 0.08, 0.05, 0.04, BLUSH))

    # --- Ears ---
    meshes.append(_make_sphere(-0.37, 1.40, 0.0, 0.055, 0.065, 0.04, SKIN))
    meshes.append(_make_sphere(0.37, 1.40, 0.0, 0.055, 0.065, 0.04, SKIN))

    # ===== CAP (black with white B emblem) =====
    # Cap body — flattened sphere on top of head
    meshes.append(_make_sphere(0, 1.70, 0, 0.42, 0.10, 0.42, BLACK))
    # Cap brim — flat cylinder in front
    meshes.append(_make_cylinder(-0.25, 1.61, 1.62, 0.30, 0.25, 0.10, BLACK, segs=20))
    # Cap crown dome
    meshes.append(_make_sphere(0, 1.73, 0, 0.38, 0.14, 0.38, BLACK))

    # Cap emblem: white 'B' represented as two bumped circles on a white plate
    # Emblem plate (white rectangle on cap front)
    meshes.append(_make_box(0, 1.72, 0.38, 0.14, 0.12, 0.01, EMBLEM))
    # B letter: left vertical bar
    meshes.append(_make_box(-0.04, 1.72, 0.395, 0.035, 0.11, 0.02, BLACK))
    # B letter: top bump
    meshes.append(_make_sphere(0.02, 1.78, 0.395, 0.055, 0.035, 0.02, EMBLEM))
    # B letter: bottom bump
    meshes.append(_make_sphere(0.025, 1.72, 0.395, 0.060, 0.035, 0.02, EMBLEM))

    # ===== NECK =====
    meshes.append(_make_cylinder(0, 1.20, 1.28, 0, 0.10, 0.10, SKIN))

    # ===== TORSO (black shirt) =====
    meshes.append(_make_sphere(0, 0.90, 0, 0.30, 0.32, 0.25, BLACK))

    # ===== OVERALLS (blue) — front bib =====
    meshes.append(_make_box(0, 0.98, 0.20, 0.35, 0.38, 0.05, BLUE))
    # Straps
    meshes.append(_make_box(-0.12, 1.12, 0.12, 0.06, 0.25, 0.04, BLUE))
    meshes.append(_make_box(0.12, 1.12, 0.12, 0.06, 0.25, 0.04, BLUE))

    # ===== ARMS =====
    # Left upper arm (black)
    meshes.append(_make_cylinder(-0.33, 0.72, 1.02, -0.15, 0.09, 0.09, BLACK, segs=14))
    # Left forearm (black)
    meshes.append(_make_cylinder(-0.38, 0.48, 0.72, -0.12, 0.08, 0.08, BLACK, segs=14))
    # Left glove (white sphere)
    meshes.append(_make_sphere(-0.42, 0.40, -0.10, 0.12, 0.12, 0.11, WHITE, lat=10, lon=16))

    # Right upper arm (black)
    meshes.append(_make_cylinder(0.33, 0.72, 1.02, 0.15, 0.09, 0.09, BLACK, segs=14))
    # Right forearm (black)
    meshes.append(_make_cylinder(0.38, 0.48, 0.72, 0.12, 0.08, 0.08, BLACK, segs=14))
    # Right glove (white)
    meshes.append(_make_sphere(0.42, 0.40, -0.10, 0.12, 0.12, 0.11, WHITE, lat=10, lon=16))

    # ===== LOWER BODY =====
    # Hips / trousers (blue overalls lower)
    meshes.append(_make_sphere(0, 0.58, 0, 0.28, 0.18, 0.24, BLUE))
    # Left leg (blue overalls)
    meshes.append(_make_cylinder(-0.14, 0.18, 0.58, 0, 0.10, 0.10, BLUE, segs=14))
    # Right leg (blue overalls)
    meshes.append(_make_cylinder(0.14, 0.18, 0.58, 0, 0.10, 0.10, BLUE, segs=14))
    # Left boot (brown, large)
    meshes.append(_make_sphere(-0.16, 0.10, 0.06, 0.14, 0.10, 0.18, BROWN, lat=10, lon=16))
    # Right boot (brown, large)
    meshes.append(_make_sphere(0.16, 0.10, 0.06, 0.14, 0.10, 0.18, BROWN, lat=10, lon=16))

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
    glfw.window_hint(glfw.SAMPLES, 4)  # MSAA

    monitor = glfw.get_primary_monitor()
    mode = glfw.get_video_mode(monitor)
    screen_w, screen_h = mode.size.width, mode.size.height

    # Position: lower-right of screen
    win_x = screen_w - WINDOW_W - 30
    win_y = screen_h - WINDOW_H - 60

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
    ctx.enable(moderngl.CULL_FACE)

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
    cam_pos = Vector3([0.0, 1.1, 2.8])
    proj = Matrix44.perspective_projection(38.0, WINDOW_W / WINDOW_H, 0.1, 50.0, dtype="f4")
    view = Matrix44.look_at(cam_pos, Vector3([0.0, 1.0, 0.0]), Vector3([0.0, 1.0, 0.0]), dtype="f4")

    # Lighting
    prog["light_pos"].write(np.array([2.0, 4.0, 3.0], dtype="f4"))
    prog["view_pos"].write(np.array(cam_pos, dtype="f4"))
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
        ctx.clear(0.10, 0.11, 0.13, 1.0)  # dark gray background
        vao.render()

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
