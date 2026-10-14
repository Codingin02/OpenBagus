"""Conversational agent tool for interactive control of BAGUSMAX 3D companion."""

from __future__ import annotations

from typing import Any

from openbagus.ai.tools.base import BaseFinancialTool
from openbagus.companion.controller import CompanionController


class ControlBagusmaxTool(BaseFinancialTool):
    """Tool allowing the conversational agent to interactively control BAGUSMAX 3D companion."""

    name = "control_bagusmax"
    description = (
        "Mengontrol posisi, rotasi 3D 360°, ukuran karakter, ukuran jendela, "
        "perspektif pandang, atau gestur animasi 3D companion BAGUSMAX di desktop Windows."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["move", "rotate", "scale", "resize", "view", "reset", "interactive", "gesture", "status"],
                "description": "Aksi yang diinginkan: move, rotate, scale, resize, view, reset, interactive, gesture, status",
            },
            "position_preset": {
                "type": "string",
                "enum": ["top-left", "top-center", "top-right", "middle-left", "center", "middle-right", "bottom-left", "bottom-center", "bottom-right"],
                "description": "Preset posisi layar (misal: 'top-left', 'top-right', 'bottom-right', 'center')",
            },
            "x": {"type": "integer", "description": "Koordinat horizontal desktop (opsional jika menggunakan preset)"},
            "y": {"type": "integer", "description": "Koordinat vertikal desktop (opsional jika menggunakan preset)"},
            "yaw": {"type": "number", "description": "Derajat rotasi horizontal (0=depan, 90=samping kanan, 180=belakang, 270=samping kiri)"},
            "pitch": {"type": "number", "description": "Derajat kemiringan vertikal (-65 sampai +65)"},
            "scale": {"type": "number", "description": "Skala ukuran tubuh karakter (0.5 sampai 2.0, default 1.0)"},
            "view": {
                "type": "string",
                "enum": ["front", "back", "left", "right", "top", "reset"],
                "description": "Arah pandang preset (front, back, left, right, top, reset)",
            },
            "gesture": {
                "type": "string",
                "enum": ["wave", "turn", "idle"],
                "description": "Gestur animasi untuk dimainkan (misal: 'wave')",
            },
            "interactive": {"type": "boolean", "description": "True untuk mode interaktif mouse, False untuk mode click-through"},
        },
        "required": ["action"],
    }

    def run(self, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        action = str(kwargs.get("action", "status")).lower()
        comp = CompanionController.get_instance()

        if action == "move":
            preset = kwargs.get("position_preset")
            x = kwargs.get("x")
            y = kwargs.get("y")
            ok = comp.set_position(x=x, y=y, preset=preset)
            return {
                "status": "success" if ok else "failed",
                "message": f"Posisi Bagusmax dipindahkan ke {preset or f'x={x}, y={y}'}",
                "preset": preset,
                "x": x,
                "y": y,
            }, {"action": "move"}

        elif action == "rotate":
            yaw = kwargs.get("yaw")
            pitch = kwargs.get("pitch")
            ok = comp.set_rotation(yaw=yaw, pitch=pitch)
            return {
                "status": "success" if ok else "failed",
                "message": f"Rotasi Bagusmax diatur ke yaw={yaw}°, pitch={pitch}°",
                "yaw": yaw,
                "pitch": pitch,
            }, {"action": "rotate"}

        elif action == "view":
            v = str(kwargs.get("view", "front")).lower()
            ok = comp.set_view(v)
            return {
                "status": "success" if ok else "failed",
                "message": f"Perspektif pandang Bagusmax diubah ke '{v}'",
                "view": v,
            }, {"action": "view"}

        elif action == "scale":
            sc = float(kwargs.get("scale", 1.0))
            ok = comp.set_character_scale(sc)
            return {
                "status": "success" if ok else "failed",
                "message": f"Ukuran Bagusmax diubah menjadi {sc*100:.0f}%",
                "scale": sc,
            }, {"action": "scale"}

        elif action == "resize":
            w = int(kwargs.get("width", 480))
            h = int(kwargs.get("height", 560))
            ok = comp.set_window_size(w, h)
            return {
                "status": "success" if ok else "failed",
                "message": f"Dimensi jendela popup diubah menjadi {w}x{h} px",
                "width": w,
                "height": h,
            }, {"action": "resize"}

        elif action == "gesture":
            g = str(kwargs.get("gesture", "wave"))
            ok = comp.trigger_gesture(g)
            return {
                "status": "success" if ok else "failed",
                "message": f"Bagusmax memainkan gestur '{g}'",
                "gesture": g,
            }, {"action": "gesture"}

        elif action == "interactive":
            inter = bool(kwargs.get("interactive", True))
            ok = comp.set_interactive(inter)
            return {
                "status": "success" if ok else "failed",
                "message": f"Mode interaksi mouse diatur ke: {'Aktif' if inter else 'Click-Through'}",
                "interactive": inter,
            }, {"action": "interactive"}

        elif action == "reset":
            ok = comp.reset_transform()
            return {
                "status": "success" if ok else "failed",
                "message": "Orientasi dan posisi Bagusmax telah di-reset ke nilai default.",
            }, {"action": "reset"}

        # default status
        st = comp.get_status()
        ts = comp.get_transform_state()
        return {
            "status": "success",
            "companion_status": st,
            "transform_state": ts,
        }, {"action": "status"}
