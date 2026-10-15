"""Inspect and operate only the visible OpenBagus installer wizard."""

import argparse
import ctypes
import json
from pathlib import Path
import win32gui
import win32ui
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--click")
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    windows = []
    win32gui.EnumWindows(lambda h, _: windows.append(h) if win32gui.IsWindowVisible(h)
                         and win32gui.GetClassName(h) == "TWizardForm"
                         and win32gui.GetWindowText(h).startswith("Setup - OpenBagus") else None, None)
    if len(windows) != 1:
        raise RuntimeError(f"Expected exactly one OpenBagus setup wizard, got {len(windows)}")
    window = windows[0]
    controls = []
    win32gui.EnumChildWindows(window, lambda h, _: controls.append({"handle": h, "class": win32gui.GetClassName(h),
                             "text": win32gui.GetWindowText(h), "enabled": bool(win32gui.IsWindowEnabled(h))})
                             if win32gui.IsWindowVisible(h) else None, None)
    if args.capture:
        left, top, right, bottom = win32gui.GetWindowRect(window)
        width, height = right-left, bottom-top
        dc = win32gui.GetWindowDC(window)
        source = win32ui.CreateDCFromHandle(dc)
        target = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source, width, height)
        target.SelectObject(bitmap)
        try:
            if not ctypes.windll.user32.PrintWindow(window, target.GetSafeHdc(), 2):
                raise RuntimeError("PrintWindow failed")
            image = Image.frombuffer("RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
            args.capture.parent.mkdir(parents=True, exist_ok=True)
            image.save(args.capture)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            target.DeleteDC()
            source.DeleteDC()
            win32gui.ReleaseDC(window, dc)
    if args.click:
        normalize = lambda text: text.replace("&", "").strip().lower()
        matches = [c for c in controls if normalize(c["text"]) == normalize(args.click) and c["enabled"]]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one enabled control {args.click!r}, got {matches}")
        win32gui.SendMessage(matches[0]["handle"], 0x00F5, 0, 0)
    print(json.dumps(controls, indent=2))


if __name__ == "__main__":
    main()
