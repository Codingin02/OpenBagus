"""Test script to generate, render, and inspect the revised Super Mario companion model."""

from __future__ import annotations

import math
import os
import sys

import glfw
import moderngl
import numpy as np
import PIL.Image
from pyrr import Matrix44, Vector3

# Add repo root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openbagus.companion.renderer import (
    VERT_SHADER,
    FRAG_SHADER,
    build_character,
)

def render_angles(output_dir: str = "docs/local_ai/screenshots") -> None:
    os.makedirs(output_dir, exist_ok=True)

    if not glfw.init():
        print("GLFW init failed")
        sys.exit(1)

    W, H = 512, 600
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.SAMPLES, 4)

    win = glfw.create_window(W, H, "Offscreen", None, None)
    glfw.make_context_current(win)

    ctx = moderngl.create_context()
    ctx.enable(moderngl.DEPTH_TEST)

    prog = ctx.program(vertex_shader=VERT_SHADER, fragment_shader=FRAG_SHADER)

    fbo = ctx.simple_framebuffer((W, H))
    fbo.use()

    shots = [
        ("01_front_full_body.png", Vector3([0.0, 0.98, 2.65]), Vector3([0.0, 0.96, 0.0]), 0.0, 0.0),
        ("02_three_quarter_full_body.png", Vector3([2.65 * math.sin(math.radians(24)), 0.98, 2.65 * math.cos(math.radians(24))]), Vector3([0.0, 0.96, 0.0]), 0.0, 0.0),
        ("03_face_close_up.png", Vector3([0.0, 1.28, 1.25]), Vector3([0.0, 1.28, 0.0]), 0.0, 0.0),
        ("04_cap_emblem_b_close_up.png", Vector3([0.0, 1.57, 0.75]), Vector3([0.0, 1.57, 0.35]), 0.0, 0.0),
        ("05_speaking_expression.png", Vector3([1.25 * math.sin(math.radians(16)), 1.24, 1.25 * math.cos(math.radians(16))]), Vector3([0.0, 1.22, 0.0]), 0.85, 0.0),
        ("06_desktop_popup_view.png", Vector3([2.65 * math.sin(math.radians(8)), 0.98, 2.65 * math.cos(math.radians(8))]), Vector3([0.0, 0.96, 0.0]), 0.18, 0.0),
    ]

    for filename, cam_pos, target_pos, mouth_open, blink in shots:
        verts, idxs = build_character(mouth_open=mouth_open, blink=blink)
        vbo = ctx.buffer(np.array(verts, dtype="f4"))
        ibo = ctx.buffer(np.array(idxs, dtype="i4"))
        vao = ctx.vertex_array(
            prog,
            [(vbo, "3f 3f 3f", "in_position", "in_normal", "in_color")],
            index_buffer=ibo,
        )

        proj = Matrix44.perspective_projection(38.0, W / H, 0.1, 50.0, dtype="f4")
        view = Matrix44.look_at(cam_pos, target_pos, Vector3([0.0, 1.0, 0.0]), dtype="f4")
        model = Matrix44.identity(dtype="f4")

        prog["proj"].write(proj)
        prog["view"].write(view)
        prog["model"].write(model)
        prog["light_pos"].write(np.array([2.5, 4.0, 3.5], dtype="f4"))
        prog["view_pos"].write(np.array(cam_pos, dtype="f4"))
        if "ambient_strength" in prog:
            prog["ambient_strength"].value = 0.45

        ctx.clear(0.12, 0.13, 0.16, 1.0)
        vao.render()

        data = fbo.read(components=3)
        img = PIL.Image.frombytes("RGB", (W, H), data).transpose(PIL.Image.FLIP_TOP_BOTTOM)
        out_path = os.path.join(output_dir, filename)
        img.save(out_path)
        print(f"Rendered {filename} ({len(verts)//9} verts, {len(idxs)//3} tris)")

        vao.release()
        vbo.release()
        ibo.release()

    glfw.terminate()
    print("All renders completed successfully!")

if __name__ == "__main__":
    render_angles()
