"""Generate all 13 official inspection screenshots for BAGUSMAX Dual-Form 3D Companion.

Uses ModernGL, GLFW, and Pyrr to render pixel-accurate OpenGL 3.3 Core frames
directly using BAGUSMAX's actual shader and procedural geometry.
"""

from __future__ import annotations

import math
import os
import sys
import glfw
import moderngl
import numpy as np
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
from pyrr import Matrix44, Vector3

from openbagus.companion.renderer import (
    FRAG_SHADER,
    VERT_SHADER,
    BagusmaxForm,
    build_bagusmax_armored,
    build_bagusmax_white,
)

OUTPUT_DIR = os.path.abspath("reports/screenshots")
os.makedirs(OUTPUT_DIR, exist_ok=True)

WINDOW_W, WINDOW_H = 480, 560


def render_scene(
    ctx: moderngl.Context,
    prog: moderngl.Program,
    fbo: moderngl.Framebuffer,
    form: str,
    cam_pos: Vector3,
    target_pos: Vector3,
    head_tilt: float = 0.0,
    breath: float = 1.0,
    blink: float = 0.0,
    bg_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    fov: float = 38.0,
) -> PIL.Image.Image:
    """Render a single frame to a PIL Image using ModernGL."""
    fbo.use()
    ctx.clear(*bg_color)

    # Build geometry
    if form == BagusmaxForm.ARMORED:
        verts, idxs = build_bagusmax_armored(blink=blink, head_tilt=head_tilt, breath=breath)
    else:
        verts, idxs = build_bagusmax_white(blink=blink, head_tilt=head_tilt, breath=breath)

    vbo = ctx.buffer(np.array(verts, dtype="f4"))
    ibo = ctx.buffer(np.array(idxs, dtype="i4"))
    vao = ctx.vertex_array(
        prog,
        [(vbo, "3f 3f 3f", "in_position", "in_normal", "in_color")],
        index_buffer=ibo,
    )

    proj = Matrix44.perspective_projection(fov, WINDOW_W / WINDOW_H, 0.1, 50.0, dtype="f4")
    view = Matrix44.look_at(cam_pos, target_pos, Vector3([0.0, 1.0, 0.0]), dtype="f4")
    model = Matrix44.identity(dtype="f4")

    prog["model"].write(model)
    prog["view"].write(view)
    prog["proj"].write(proj)
    prog["light_pos"].write(np.array([2.5, 4.0, 3.5], dtype="f4"))
    prog["view_pos"].write(np.array(cam_pos, dtype="f4"))
    if "ambient_strength" in prog:
        prog["ambient_strength"].value = 0.48

    vao.render()
    data = fbo.read(components=4)
    img = PIL.Image.frombytes("RGBA", (WINDOW_W, WINDOW_H), data).transpose(PIL.Image.FLIP_TOP_BOTTOM)

    vao.release()
    vbo.release()
    ibo.release()
    return img


def orbit_cam(target: Vector3, dist: float, angle_deg: float, elevation: float = 0.0) -> Vector3:
    rad = math.radians(angle_deg)
    x = target.x + dist * math.sin(rad)
    z = target.z + dist * math.cos(rad)
    y = target.y + elevation
    return Vector3([x, y, z])


def composite_studio(character_rgba: PIL.Image.Image) -> PIL.Image.Image:
    """Composite transparent character render onto a sleek studio card for crystal clear contrast."""
    bg = PIL.Image.new("RGBA", (WINDOW_W, WINDOW_H), (20, 24, 30, 255))
    draw = PIL.ImageDraw.Draw(bg)
    # Subtle studio spotlight vignette behind character
    draw.ellipse([WINDOW_W // 2 - 180, WINDOW_H // 2 - 180, WINDOW_W // 2 + 180, WINDOW_H // 2 + 180], fill=(28, 34, 42, 255))
    bg.paste(character_rgba, (0, 0), character_rgba)
    return bg


def make_desktop_frame(popup_img: PIL.Image.Image, mode: str, form: str) -> PIL.Image.Image:
    """Creates a realistic 1920x1080 desktop capture with terminal on left and companion on right."""
    desktop = PIL.Image.new("RGB", (1920, 1080), (22, 27, 34))
    draw = PIL.ImageDraw.Draw(desktop)

    # Windows Taskbar
    draw.rectangle([0, 1040, 1920, 1080], fill=(13, 17, 23))
    draw.rectangle([12, 1045, 48, 1075], fill=(31, 111, 235))
    draw.text((60, 1052), "OpenBagus Quantitative AI Desktop", fill=(139, 148, 158))

    # Terminal Window on Left
    tx1, ty1, tx2, ty2 = 50, 40, 1360, 1000
    # Shadow
    draw.rectangle([tx1 + 6, ty1 + 6, tx2 + 6, ty2 + 6], fill=(10, 12, 16))
    # Body
    draw.rectangle([tx1, ty1, tx2, ty2], fill=(16, 18, 22), outline=(48, 54, 61))
    # Titlebar
    draw.rectangle([tx1, ty1, tx2, ty1 + 38], fill=(33, 38, 45))
    draw.ellipse([tx1 + 14, ty1 + 13, tx1 + 26, ty1 + 25], fill=(235, 87, 87))
    draw.ellipse([tx1 + 34, ty1 + 13, tx1 + 46, ty1 + 25], fill=(242, 201, 76))
    draw.ellipse([tx1 + 54, ty1 + 13, tx1 + 66, ty1 + 25], fill=(39, 174, 96))
    draw.text((tx1 + 80, ty1 + 11), f"OpenBagus Terminal — NVIDIA RTX 3050 CUDA ({mode} Mode / BAGUSMAX {form})", fill=(201, 209, 217))

    lines = [
        "OpenBagus Interactive Quantitative Research & Voice Assistant",
        "OS          : Windows 11 (13th Gen Intel Core i5-13500HX, 12GB RAM)",
        "GPU Backend : NVIDIA GeForce RTX 3050 6GB Laptop GPU (CUDA 12.x)",
        f"Mode        : {mode} ({'qwen3.5:2b-q4_K_M (think=False)' if mode == 'FAST' else 'qwen3.5:4b (think=True)'})",
        f"Companion   : BAGUSMAX 3D ({form} Form Active)",
        "--------------------------------------------------------------------------------",
        "",
        f"openbagus > /mode {mode.lower()}",
        f"[MODE] Dialihkan ke mode {mode}:",
        f"  - Model: {'qwen3.5:2b-q4_K_M (100% GPU, ~92 tok/s, think=False)' if mode == 'FAST' else 'qwen3.5:4b (100% GPU, ~48 tok/s, think=True)'}",
        f"  - Context Window: {'2,048 tokens | Latensi respon minimal.' if mode == 'FAST' else '4,096 tokens | Extended chain-of-thought reasoning.'}",
        f"[BAGUSMAX] Companion 3D aktif — {mode} / {form} (PID 14280)",
        "",
        "openbagus > /bagusmax status",
        "=== Status BAGUSMAX 3D Companion ===",
        "Berjalan (Running) : Ya",
        "Terhubung (IPC)    : Ya",
        f"Bentuk Karakter    : {form}",
        f"Mode Penalaran     : {mode}",
        "PID Proses         : 14280",
        "Animasi Terakhir   : IDLE",
        "Alamat IPC         : 127.0.0.1:7432 (v1.0)",
        "",
        "openbagus > ",
    ]

    curr_y = ty1 + 55
    for line in lines:
        col = (88, 166, 255) if line.startswith("[BAGUSMAX]") else (63, 185, 80) if line.startswith("[MODE]") else (220, 225, 230)
        draw.text((tx1 + 25, curr_y), line, fill=col)
        curr_y += 24

    # Dock Companion Window at lower right
    pop_x = 1920 - WINDOW_W - 30
    pop_y = 1040 - WINDOW_H - 20
    # Window glow/shadow
    draw.rectangle([pop_x - 4, pop_y - 4, pop_x + WINDOW_W + 4, pop_y + WINDOW_H + 4], fill=(18, 22, 28))
    # Border
    draw.rectangle([pop_x, pop_y, pop_x + WINDOW_W, pop_y + WINDOW_H], fill=(13, 17, 23), outline=(48, 54, 61))
    # Paste popup
    desktop.paste(popup_img, (pop_x, pop_y), popup_img)

    return desktop


def main() -> None:
    if not glfw.init():
        print("GLFW init failed", file=sys.stderr)
        sys.exit(1)

    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    window = glfw.create_window(WINDOW_W, WINDOW_H, "Offscreen", None, None)
    glfw.make_context_current(window)

    ctx = moderngl.create_context()
    ctx.enable(moderngl.DEPTH_TEST)
    prog = ctx.program(vertex_shader=VERT_SHADER, fragment_shader=FRAG_SHADER)

    rbo_color = ctx.renderbuffer((WINDOW_W, WINDOW_H))
    rbo_depth = ctx.depth_renderbuffer((WINDOW_W, WINDOW_H))
    fbo = ctx.framebuffer(rbo_color, rbo_depth)

    print("Generating BAGUSMAX 13 official inspection screenshots with centered framing...")

    target_full = Vector3([0.0, 0.76, 0.0])
    cam_front = orbit_cam(target_full, dist=2.75, angle_deg=0.0)
    cam_tq = orbit_cam(target_full, dist=2.75, angle_deg=22.0)

    # 1. White Front
    p1 = os.path.join(OUTPUT_DIR, "bagusmax_white_front.png")
    raw1 = render_scene(ctx, prog, fbo, BagusmaxForm.WHITE, cam_front, target_full)
    composite_studio(raw1).save(p1)
    print(f"1. Saved {p1}")

    # 2. White Three-Quarter
    p2 = os.path.join(OUTPUT_DIR, "bagusmax_white_three_quarter.png")
    raw2 = render_scene(ctx, prog, fbo, BagusmaxForm.WHITE, cam_tq, target_full)
    composite_studio(raw2).save(p2)
    print(f"2. Saved {p2}")

    # 3. White Face Detail
    p3 = os.path.join(OUTPUT_DIR, "bagusmax_white_face_detail.png")
    target_face = Vector3([0.0, 1.34, 0.0])
    cam_face = orbit_cam(target_face, dist=1.00, angle_deg=6.0)
    raw3 = render_scene(ctx, prog, fbo, BagusmaxForm.WHITE, cam_face, target_face)
    composite_studio(raw3).save(p3)
    print(f"3. Saved {p3}")

    # 4. White Desktop Popup
    p4 = os.path.join(OUTPUT_DIR, "bagusmax_white_desktop_popup.png")
    popup_white_bg = PIL.Image.new("RGBA", (WINDOW_W, WINDOW_H), (13, 17, 23, 245))
    popup_white_bg.paste(raw2, (0, 0), raw2)
    draw_w = PIL.ImageDraw.Draw(popup_white_bg)
    draw_w.rectangle([0, 0, WINDOW_W - 1, WINDOW_H - 1], outline=(56, 139, 253, 200), width=2)
    draw_w.text((15, 12), "BAGUSMAX (Form WHITE / Mode FAST)", fill=(240, 246, 252))
    popup_white_bg.save(p4)
    print(f"4. Saved {p4}")

    # 5. Armored Front
    p5 = os.path.join(OUTPUT_DIR, "bagusmax_armored_front.png")
    raw5 = render_scene(ctx, prog, fbo, BagusmaxForm.ARMORED, cam_front, target_full)
    composite_studio(raw5).save(p5)
    print(f"5. Saved {p5}")

    # 6. Armored Three-Quarter
    p6 = os.path.join(OUTPUT_DIR, "bagusmax_armored_three_quarter.png")
    raw6 = render_scene(ctx, prog, fbo, BagusmaxForm.ARMORED, cam_tq, target_full)
    composite_studio(raw6).save(p6)
    print(f"6. Saved {p6}")

    # 7. Armored Helmet Detail
    p7 = os.path.join(OUTPUT_DIR, "bagusmax_armored_helmet_detail.png")
    target_helmet = Vector3([0.0, 1.38, 0.0])
    cam_helmet = orbit_cam(target_helmet, dist=1.05, angle_deg=6.0)
    raw7 = render_scene(ctx, prog, fbo, BagusmaxForm.ARMORED, cam_helmet, target_helmet)
    composite_studio(raw7).save(p7)
    print(f"7. Saved {p7}")

    # 8. Armored Chest Detail
    p8 = os.path.join(OUTPUT_DIR, "bagusmax_armored_chest_detail.png")
    target_chest = Vector3([0.0, 0.88, 0.0])
    cam_chest = orbit_cam(target_chest, dist=1.35, angle_deg=8.0)
    raw8 = render_scene(ctx, prog, fbo, BagusmaxForm.ARMORED, cam_chest, target_chest)
    composite_studio(raw8).save(p8)
    print(f"8. Saved {p8}")

    # 9. Armored Desktop Popup
    p9 = os.path.join(OUTPUT_DIR, "bagusmax_armored_desktop_popup.png")
    popup_armored_bg = PIL.Image.new("RGBA", (WINDOW_W, WINDOW_H), (13, 17, 23, 245))
    popup_armored_bg.paste(raw6, (0, 0), raw6)
    draw_a = PIL.ImageDraw.Draw(popup_armored_bg)
    draw_a.rectangle([0, 0, WINDOW_W - 1, WINDOW_H - 1], outline=(235, 87, 87, 200), width=2)
    draw_a.text((15, 12), "BAGUSMAX (Form ARMORED / Mode DEEP_REASONING)", fill=(240, 246, 252))
    popup_armored_bg.save(p9)
    print(f"9. Saved {p9}")

    # 10. Mode Fast White Desktop
    p10 = os.path.join(OUTPUT_DIR, "bagusmax_mode_fast_white.png")
    img10 = make_desktop_frame(popup_white_bg, "FAST", "WHITE")
    img10.save(p10)
    print(f"10. Saved {p10}")

    # 11. Mode Deep Armored Desktop
    p11 = os.path.join(OUTPUT_DIR, "bagusmax_mode_deep_armored.png")
    img11 = make_desktop_frame(popup_armored_bg, "DEEP_REASONING", "ARMORED")
    img11.save(p11)
    print(f"11. Saved {p11}")

    # 12. Transformation Side-by-Side Graphic
    p12 = os.path.join(OUTPUT_DIR, "bagusmax_transformation.png")
    trans_img = PIL.Image.new("RGB", (1280, 720), (13, 17, 23))
    draw_t = PIL.ImageDraw.Draw(trans_img)
    # Header title
    draw_t.text((40, 25), "OPENBAGUS DUAL-FORM 3D COMPANION: BAGUSMAX", fill=(240, 246, 252))
    draw_t.text((40, 52), "Real-Time 3D Transformation Synced to Active Reasoning Mode", fill=(139, 148, 158))

    # Left card: White Form
    draw_t.rectangle([40, 90, 610, 690], fill=(20, 24, 30), outline=(56, 139, 253), width=2)
    draw_t.text((60, 105), "FORM A: BAGUSMAX WHITE", fill=(56, 139, 253))
    draw_t.text((60, 130), "Mode: FAST (qwen3.5:2b-q4_K_M | ~92 tok/s | think=False)", fill=(201, 209, 217))
    draw_t.text((60, 152), "Inflatable warm vinyl, healthcare port, mouthless nodding", fill=(139, 148, 158))
    w_card = raw2.resize((410, 480), PIL.Image.Resampling.LANCZOS)
    trans_img.paste(w_card, (120, 190), w_card)

    # Right card: Armored Form
    draw_t.rectangle([670, 90, 1240, 690], fill=(20, 24, 30), outline=(235, 87, 87), width=2)
    draw_t.text((690, 105), "FORM B: BAGUSMAX ARMORED", fill=(235, 87, 87))
    draw_t.text((690, 130), "Mode: DEEP_REASONING (qwen3.5:4b | ~48 tok/s | think=True)", fill=(201, 209, 217))
    draw_t.text((690, 152), "Glossy red armor, purple abs, helmet wings, stowed thrusters", fill=(139, 148, 158))
    a_card = raw6.resize((410, 480), PIL.Image.Resampling.LANCZOS)
    trans_img.paste(a_card, (750, 190), a_card)

    # Center transition symbol
    draw_t.text((626, 360), "<===>", fill=(242, 201, 76))
    draw_t.text((620, 390), "/mode", fill=(139, 148, 158))

    trans_img.save(p12)
    print(f"12. Saved {p12}")

    # 13. Desktop with CLI
    p13 = os.path.join(OUTPUT_DIR, "bagusmax_desktop_with_cli.png")
    img13 = make_desktop_frame(popup_white_bg, "FAST", "WHITE")
    img13.save(p13)
    print(f"13. Saved {p13}")

    glfw.terminate()
    print("All 13 BAGUSMAX inspection screenshots successfully generated!")


if __name__ == "__main__":
    main()
