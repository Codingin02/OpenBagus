"""SHOW OPENBAGUS — Local 3D companion package.

Renders an animated 3D cartoon plumber companion using OpenGL via moderngl + glfw.
- Black cap with capital 'B' emblem (NOT M)
- Black shirt, blue overalls, white gloves, brown boots
- Animates to: IDLE, LISTENING, THINKING, DEEP_THINKING, SPEAKING, HAPPY, ERROR
- Communicates with OpenBagus CLI via local WebSocket on 127.0.0.1:7432
- Runs as a subprocess; CLI survives companion crash
"""

from openbagus.companion.controller import CompanionController

__all__ = ["CompanionController"]
