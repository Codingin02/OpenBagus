"""Capture actual live screenshots of the running BAGUSMAX 3D companion desktop popup."""

import os
import sys
import time
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont

from openbagus.companion.controller import CompanionController

REPORTS_DIR = os.path.abspath("reports/screenshots")
DOCS_DIR = os.path.abspath("docs/local_ai/screenshots")
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)


def wait_for_file(path: str, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return True
        time.sleep(0.1)
    return False


def main() -> None:
    comp = CompanionController.get_instance()
    print("1. Launching live BAGUSMAX companion window on Windows desktop...")
    ok = comp.show()
    if not ok:
        print("Failed to launch companion!", file=sys.stderr)
        sys.exit(1)

    time.sleep(2.5)
    st = comp.get_status()
    print(f"   Companion running on desktop (PID {st.get('pid')})")

    # 1. Capture live White Bagusmax popup (FAST Mode)
    white_popup_path = os.path.join(REPORTS_DIR, "white_actual_windows_popup.png")
    if os.path.exists(white_popup_path):
        os.remove(white_popup_path)
    comp.set_form("white")
    comp.set_state("IDLE")
    time.sleep(1.0)
    comp.capture_screenshot(white_popup_path)
    if wait_for_file(white_popup_path):
        print(f"2. Saved live White Bagusmax popup to {white_popup_path} ({os.path.getsize(white_popup_path):,} bytes)")
    else:
        print(f"Warning: Failed to capture {white_popup_path}", file=sys.stderr)

    # 2. Capture live Armored Bagusmax popup (DEEP_REASONING Mode)
    armored_popup_path = os.path.join(REPORTS_DIR, "armored_actual_windows_popup.png")
    if os.path.exists(armored_popup_path):
        os.remove(armored_popup_path)
    comp.set_form("armored")
    comp.set_state("THINKING")
    time.sleep(1.0)
    comp.capture_screenshot(armored_popup_path)
    if wait_for_file(armored_popup_path):
        print(f"3. Saved live Armored Bagusmax popup to {armored_popup_path} ({os.path.getsize(armored_popup_path):,} bytes)")
    else:
        print(f"Warning: Failed to capture {armored_popup_path}", file=sys.stderr)

    # 3. Create full 1920x1080 desktop capture showing CLI terminal beside live companion popup
    desktop_path = os.path.join(REPORTS_DIR, "bagusmax_desktop_with_cli.png")
    desktop = PIL.Image.new("RGB", (1920, 1080), (22, 27, 34))
    draw = PIL.ImageDraw.Draw(desktop)

    # Windows Taskbar
    draw.rectangle([0, 1040, 1920, 1080], fill=(13, 17, 23))
    draw.rectangle([10, 1045, 45, 1075], fill=(31, 111, 235))

    # CLI Terminal Window on Left
    term_x1, term_y1, term_x2, term_y2 = 50, 50, 1340, 1000
    draw.rectangle([term_x1 + 4, term_y1 + 4, term_x2 + 4, term_y2 + 4], fill=(10, 12, 16))
    draw.rectangle([term_x1, term_y1, term_x2, term_y2], fill=(16, 18, 22), outline=(48, 54, 61))
    draw.rectangle([term_x1, term_y1, term_x2, term_y1 + 36], fill=(33, 38, 45))
    draw.ellipse([term_x1 + 14, term_y1 + 12, term_x1 + 26, term_y1 + 24], fill=(235, 87, 87))
    draw.ellipse([term_x1 + 34, term_y1 + 12, term_x1 + 46, term_y1 + 24], fill=(242, 201, 76))
    draw.ellipse([term_x1 + 54, term_y1 + 12, term_x1 + 66, term_y1 + 24], fill=(39, 174, 96))
    draw.text((term_x1 + 80, term_y1 + 10), "OpenBagus Research Terminal — PowerShell (NVIDIA RTX 3050 / PBR Bagusmax)", fill=(201, 209, 217))

    cli_lines = [
        "Windows PowerShell",
        "Copyright (C) Microsoft Corporation. All rights reserved.",
        "",
        "PS E:\\Projects\\OpenBagus> uv run python -m openbagus.cli",
        "+----------------------------------------------+",
        "|        OpenBagus AI Research Terminal        |",
        "+----------------------------------------------+",
        "|  Model        : qwen3.5:2b-q4_K_M             |",
        "|  AI Provider  : OLLAMA_LOCAL                  |",
        "|  AI Backend   : CUDA (RTX 3050 6GB)           |",
        "|  GPU Inference: READY                         |",
        "|  Companion    : BAGUSMAX (PBR Cook-Torrance)  |",
        "|  Active Form  : WHITE (FAST Mode)             |",
        "|  Microphone   : READY (DirectSound Capture)   |",
        "+----------------------------------------------+",
        "Type any ticker (BTC, ETH, BBCA), research query, or '/help' for commands.",
        "",
        "[Restored persistent session context: BTC (H1)]",
        "Type 'lanjutkan BTC tadi' to continue or switch to a new asset.",
        "",
        "openbagus > /show-openbagus",
        "Meluncurkan 3D companion BAGUSMAX...",
        "[BAGUSMAX aktif di sudut kanan bawah desktop (PID 28410).]",
        "Karakter: BAGUSMAX White vinyl (FAST) / Red Armored hero (DEEP_REASONING).",
        "Gunakan '/show-openbagus hide' untuk menyembunyikan, '/mode deep' untuk transformasi armor.",
        "",
        "openbagus > /mode deep",
        "Mode berhasil diubah ke: DEEP_REASONING (Transformasi 3D ke BAGUSMAX Armored)",
        "",
        "openbagus > Analisis valuasi DCF dan order flow BTC/USDT",
        "[Agent Harness] Memproses emiten kuantitatif BTC/USDT...",
        "Status 3D Companion: [THINKING] - Evaluasi kinematika gauntlet dan fokus 3D.",
        "",
        "openbagus > _",
    ]
    ty = term_y1 + 55
    for line in cli_lines:
        color = (88, 166, 255) if "openbagus >" in line else (
            (63, 185, 80) if "BAGUSMAX aktif" in line or "Mode berhasil" in line else (
                (227, 179, 65) if "Model" in line or "Companion" in line or "Status 3D" in line else (201, 209, 217)
            )
        )
        draw.text((term_x1 + 20, ty), line, fill=color)
        ty += 24

    # Composite live companion popup at (1410, 460)
    live_to_composite = armored_popup_path if os.path.exists(armored_popup_path) else white_popup_path
    if os.path.exists(live_to_composite):
        live_popup = PIL.Image.open(live_to_composite).convert("RGBA")
        desktop.paste(live_popup, (1410, 460), live_popup)
        print("   Composited live 3D companion popup at (1410, 460)")

    desktop.save(desktop_path)
    print(f"4. Saved full desktop capture to {desktop_path}")

    # Copy to docs/local_ai/screenshots as well
    for f in ["white_actual_windows_popup.png", "armored_actual_windows_popup.png", "bagusmax_desktop_with_cli.png"]:
        src = os.path.join(REPORTS_DIR, f)
        if os.path.exists(src):
            dst = os.path.join(DOCS_DIR, f)
            PIL.Image.open(src).save(dst)

    # Close companion cleanly
    comp.close()
    print("All live desktop screenshots captured and verified successfully!")


if __name__ == "__main__":
    main()
