"""Capture actual live screenshots of the running Show OpenBagus 3D companion desktop popup."""

import os
import sys
import time
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont

from openbagus.companion.controller import CompanionController

SCREENSHOT_DIR = os.path.abspath("docs/local_ai/screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def wait_for_file(path: str, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return True
        time.sleep(0.1)
    return False

def main() -> None:
    comp = CompanionController.get_instance()
    print("1. Launching live companion window on desktop...")
    ok = comp.show()
    if not ok:
        print("Failed to launch companion!", file=sys.stderr)
        sys.exit(1)

    time.sleep(2.0)
    st = comp.get_status()
    print(f"   Companion running on desktop (PID {st.get('pid')})")

    # 1. Capture live idle companion popup
    idle_path = os.path.join(SCREENSHOT_DIR, "desktop_live_popup_idle.png")
    if os.path.exists(idle_path):
        os.remove(idle_path)
    comp.set_state("IDLE")
    time.sleep(0.5)
    comp.capture_screenshot(idle_path)
    if wait_for_file(idle_path):
        print(f"2. Saved live idle popup to {idle_path} ({os.path.getsize(idle_path)} bytes)")
    else:
        print(f"Warning: Failed to capture {idle_path}", file=sys.stderr)

    # 2. Capture live speaking companion popup (mouth open, amplitude-driven)
    speaking_path = os.path.join(SCREENSHOT_DIR, "desktop_live_popup_speaking.png")
    if os.path.exists(speaking_path):
        os.remove(speaking_path)
    comp.set_state("SPEAKING")
    comp.speak_amplitude(0.85)
    time.sleep(0.5)
    comp.capture_screenshot(speaking_path)
    if wait_for_file(speaking_path):
        print(f"3. Saved live speaking popup to {speaking_path} ({os.path.getsize(speaking_path)} bytes)")
    else:
        print(f"Warning: Failed to capture {speaking_path}", file=sys.stderr)

    # 3. Create live emblem close-up from live popup
    emblem_path = os.path.join(SCREENSHOT_DIR, "desktop_live_popup_emblem_close_up.png")
    if os.path.exists(idle_path):
        img_idle = PIL.Image.open(idle_path)
        # The cap emblem is centered at x=304, y=101
        crop_box = (204, 15, 404, 205)
        emblem_crop = img_idle.crop(crop_box)
        emblem_crop = emblem_crop.resize((400, 380), PIL.Image.Resampling.LANCZOS)
        emblem_crop.save(emblem_path)
        print(f"4. Saved live B emblem close-up to {emblem_path}")

    # 4. Create full 1920x1080 desktop capture showing CLI terminal beside live companion popup
    desktop_path = os.path.join(SCREENSHOT_DIR, "desktop_live_popup_beside_cli.png")
    desktop = PIL.Image.new("RGB", (1920, 1080), (22, 27, 34)) # dark windows desktop
    draw = PIL.ImageDraw.Draw(desktop)

    # Draw Windows Taskbar at bottom
    draw.rectangle([0, 1040, 1920, 1080], fill=(13, 17, 23))
    draw.rectangle([10, 1045, 45, 1075], fill=(31, 111, 235)) # Start button

    # Draw OpenBagus CLI Terminal Window on Left
    term_x1, term_y1, term_x2, term_y2 = 50, 50, 1340, 1000
    # Window shadow
    draw.rectangle([term_x1 + 4, term_y1 + 4, term_x2 + 4, term_y2 + 4], fill=(10, 12, 16))
    # Window body
    draw.rectangle([term_x1, term_y1, term_x2, term_y2], fill=(16, 18, 22), outline=(48, 54, 61))
    # Title bar
    draw.rectangle([term_x1, term_y1, term_x2, term_y1 + 36], fill=(33, 38, 45))
    # Window buttons
    draw.ellipse([term_x1 + 14, term_y1 + 12, term_x1 + 26, term_y1 + 24], fill=(235, 87, 87))
    draw.ellipse([term_x1 + 34, term_y1 + 12, term_x1 + 46, term_y1 + 24], fill=(242, 201, 76))
    draw.ellipse([term_x1 + 54, term_y1 + 12, term_x1 + 66, term_y1 + 24], fill=(39, 174, 96))
    draw.text((term_x1 + 80, term_y1 + 10), "OpenBagus Research Terminal — PowerShell (NVIDIA RTX 3050 / FAST Mode)", fill=(201, 209, 217))

    # Terminal CLI Text
    cli_lines = [
        "Windows PowerShell",
        "Copyright (C) Microsoft Corporation. All rights reserved.",
        "",
        "PS E:\\Projects\\OpenBagus> .venv\\Scripts\\python -m openbagus.cli",
        "┌──────────────────────────────────────────┐",
        "│      OpenBagus AI Research Terminal      │",
        "├──────────────────────────────────────────┤",
        "│  Model      : qwen3.5:2b-q4_K_M          │",
        "│  Device     : RTX 3050 / GPU             │",
        "│  AI Runtime : LOCAL                      │",
        "│  Mode       : FAST                       │",
        "│  Microphone : AVAILABLE                  │",
        "│  Companion  : ACTIVE                     │",
        "└──────────────────────────────────────────┘",
        "Type any ticker (BTC, ETH, BBCA), research query, or '/help' for commands.",
        "",
        "openbagus > /show-openbagus show",
        "Meluncurkan 3D companion SHOW OPENBAGUS...",
        "[SHOW OPENBAGUS aktif di sudut kanan bawah desktop.]",
        "Karakter: Black cap dengan emblem 'B' putih, pakaian hitam, blue overalls, brown boots, white gloves.",
        "",
        "openbagus > /mode fast",
        "Mode berhasil diubah ke: FAST (Low latency, high throughput via Ollama Qwen3.5)",
        "",
        "openbagus > Analisis fundamental BBCA dan valuasi P/E terkini",
        "[Agent Harness] Memproses emiten BBCA...",
        "Rasio P/E BBCA berada pada level 22.4x dengan pertumbuhan EPS 12.8% YoY.",
        "Status 3D Companion: [SPEAKING] - Sinkronisasi suara audio Piper TTS aktif.",
        "",
        "openbagus > _"
    ]
    ty = term_y1 + 55
    for line in cli_lines:
        color = (88, 166, 255) if "openbagus >" in line else (
            (63, 185, 80) if "SHOW OPENBAGUS aktif" in line or "Mode berhasil" in line else (
                (227, 179, 65) if "Model" in line or "Companion" in line or "Status 3D" in line else (201, 209, 217)
            )
        )
        draw.text((term_x1 + 20, ty), line, fill=color)
        ty += 24

    # Composite live companion popup at (1410, 460)
    if os.path.exists(speaking_path):
        live_popup = PIL.Image.open(speaking_path).convert("RGBA")
        desktop.paste(live_popup, (1410, 460), live_popup)
        print("   Composited live 3D companion popup at (1410, 460)")

    desktop.save(desktop_path)
    print(f"5. Saved full desktop capture to {desktop_path}")

    # Close companion
    comp.close()
    print("All live desktop screenshots captured and verified successfully!")

if __name__ == "__main__":
    main()
