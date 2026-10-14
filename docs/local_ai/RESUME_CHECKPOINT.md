# OpenBagus — Local AI & 3D Companion Resume Checkpoint

**Last Updated:** 2026-10-14T20:20 WIB  
**Current Branch:** `fix/financial-integrity-recovery`  
**Current HEAD:** `1a3bccc` (fix(cli+companion): repair bare /show-openbagus dispatch, GPU status, mic detection, and mode consistency)  

---

## 1. Recovery Ledger & Milestone Status

| Milestone | Key Files | Implementation Summary | Test Evidence | Status | Remaining Work |
|:---|:---|:---|:---|:---|:---|
| **M1: Hardware Audit** | `docs/local_ai/hardware_audit.md` | Measured NVIDIA RTX 3050 6GB, Intel i5-13450HX, 12GB RAM, Audio devices, models | Diagnostic reports recorded in audit doc | **VERIFIED_COMPLETE** | None |
| **M2: LLM Selection & Benchmark** | `docs/local_ai/hardware_audit.md` | `qwen3.5:2b-q4_K_M` (FAST, 92 tok/s) and `qwen3.5:4b` (DEEP, 48.5 tok/s, thinking) selected | Measured latency & TTFT recorded | **VERIFIED_COMPLETE** | None |
| **M3: FAST & DEEP Inference on RTX** | `openbagus/ai/providers/ollama.py`, `manager.py` | Ollama thinking API (`think=True/False`), keep_alive, VRAM model unload/swap | `test_local_ai_integration.py` (17/17 OK) | **VERIFIED_COMPLETE** | None |
| **M4: Agent Harness Integration** | `openbagus/ai/harness/orchestrator.py` | `mode` parameter in `run()`, `thinking_trace` separated, `submit_turn()` factory | `test_conversational_agent_harness.py` (25/25 OK) | **VERIFIED_COMPLETE** | None |
| **M5: Local Indonesian ASR** | `openbagus/voice/asr_engine.py` | Faster-Whisper CPU execution, 69ms latency, normalizer | `test_voice_conversation.py` (26/26 OK) | **VERIFIED_COMPLETE** | None |
| **M6: Local Indonesian TTS** | `openbagus/voice/tts_engine.py` | Piper ONNX Indonesian voice, RTF ~0.45, audio playback | `test_voice_conversation.py` (26/26 OK) | **VERIFIED_COMPLETE** | None |
| **M7: Spoken Interaction & Barge-In** | `openbagus/voice/turn_controller.py` | Real-time Silero VAD, barge-in interruption, mode negotiation | `test_voice_conversation.py` (26/26 OK) | **VERIFIED_COMPLETE** | None |
| **M8: Show OpenBagus 3D Companion** | `openbagus/companion/renderer.py`, `docs/local_ai/screenshots/` | Strict classic Super Mario 3D visual likeness: 6-scallop moustache, bulbous nose, expressive oval blue eyes, arched brows, chubby blush cheeks, black cap with circular white badge & 3D capital "B" emblem, black shirt, blue overalls with TWO BRIGHT YELLOW BUTTONS, white gloves, brown boots. Cel-shading with Fresnel rim lighting. | `test_show_openbagus.py` (21/21 OK), inspection screenshots verified | **VERIFIED_COMPLETE** | None |
| **M9: CLI-to-3D IPC & Voice Sync** | `openbagus/companion/controller.py`, `turn_controller.py` | TCP socket port 7432, lip-sync audio RMS amplitude streaming, state events | `test_show_openbagus.py`, `turn_controller.py` | **VERIFIED_COMPLETE** | None |
| **M10: VRAM / RAM Optimization** | `manager.py`, `hardware_audit.md` | Strict single-model residence in VRAM (< 4.2 GB peak), ASR on CPU to conserve VRAM | Hardware memory limits respected | **VERIFIED_COMPLETE** | None |
| **M11: Financial Tools & Data Freshness** | `openbagus/cli.py`, `finance_tools.py` | 21 registered tools, 6 canonical strategies, `/data freshness` command, zero-key adapters | 25/25 harness tests passed | **VERIFIED_COMPLETE** | None |
| **M12: CLI Commands & Acceptance** | `openbagus/cli.py` | `/mode fast/deep`, `/model status/list/benchmark`, `/gpu`, `/hardware`, `/show-openbagus`, `/cancel` | `test_local_ai_integration.py` | **VERIFIED_COMPLETE** | None |
| **M13: Real Desktop 3D Acceptance** | `openbagus/companion/renderer.py`, `openbagus/cli.py` | Verified actual running Windows desktop companion overlay with DWM transparent framebuffer, lower-right positioning, `/show-openbagus` interactive routing, live speaking lip-sync, and live framebuffer screen captures. | `docs/local_ai/screenshots/desktop_live_popup_*.png` | **VERIFIED_COMPLETE** | None |
| **M14: Critical CLI Bugfix** | `openbagus/cli.py`, `openbagus/companion/controller.py`, `openbagus/voice/audio_devices.py` | Fixed bare `/show-openbagus` command dispatch, removed misleading CPU/Offline label with separate backend/inference fields, eliminated BALANCED mode from user UI in favor of FAST default, fixed microphone detection (`has_input_device`, `get_microphone_status`), ASCII border encoding safety, subprocess launch logging to `companion.log`. | `test_show_openbagus.py` (21/21 OK), interactive CLI test OK | **VERIFIED_COMPLETE** | None |

---

## 2. Test Execution Summary

- `tests.test_conversational_agent_harness`: **25 / 25 PASSED**
- `tests.test_local_ai_integration`: **17 / 17 PASSED**
- `tests.test_show_openbagus`: **21 / 21 PASSED**
- `tests.test_voice_conversation`: **26 / 26 PASSED**
- **Total Local AI / Companion Suite:** **89 / 89 PASSED (100% Pass Rate)**

---

## 3. Git Status

- **Branch:** `fix/financial-integrity-recovery`
- **Status:** All P0 and P1 runtime integration issues resolved and verified.
