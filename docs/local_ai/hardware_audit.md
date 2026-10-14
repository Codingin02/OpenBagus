# OpenBagus — Local AI Hardware Audit Report

**Audit Date:** 2026-10-14T03:35 WIB  
**Branch:** `fix/financial-integrity-recovery` | **Commit:** `921c152`  
**Auditor:** Automated diagnostic via PowerShell + nvidia-smi + Ollama API

---

## 1. GPU

| Property | Value |
|:---|:---|
| GPU | NVIDIA GeForce RTX 3050 6GB Laptop GPU |
| UUID | GPU-a7f4558b-2290-fd4d-bd18-93fac9a9c407 |
| Driver Version | 616.92 (KMD) |
| CUDA UMD Version | 13.4 |
| VRAM Total | 6144 MiB |
| VRAM Used (idle) | 159 MiB (Chrome + ChatGPT) |
| VRAM Free (idle) | ~5,843 MiB |
| GPU Utilization (idle) | 0% |
| Temperature (idle) | 38°C |
| Power Draw (idle) | 3W / 65W TDP |

---

## 2. CPU

| Property | Value |
|:---|:---|
| Model | Intel Core i5-13450HX (13th Gen, HX series) |
| Physical Cores | 10 |
| Logical Processors | 16 |
| Base Clock | 2400 MHz (boost available) |

---

## 3. System Memory

| Property | Value |
|:---|:---|
| Total RAM | 12 GB (12,283,768 KB) |
| Free RAM (idle) | ~2.97 GB (2,975,348 KB) |
| Committed RAM | ~9.0 GB |
| Cause of high usage | Chrome, ChatGPT app, Windows services |

> **Note:** With ~2.97 GB free RAM, model management is critical.  
> Ollama keeps models in VRAM only; CPU RAM is used for OS + application.  
> Do not load two large models simultaneously.

---

## 4. Operating System

| Property | Value |
|:---|:---|
| OS | Windows 11 Home Single Language |
| Build | 10.0.26200 |
| Architecture | AMD64 |

---

## 5. Storage

| Drive | Free | Used |
|:---|---:|---:|
| C: (System) | 112.5 GB | 362.1 GB |
| D: | 37.2 GB | 394.3 GB |
| E: (Projects) | 171.9 GB | 328.1 GB |

> **E: drive** is the preferred location for Godot binaries and 3D assets.

---

## 6. Audio Devices

| Device | Status | Notes |
|:---|:---|:---|
| Microphone Array (Realtek Audio) | OK | Primary laptop microphone |
| Microphone (Realtek USB2.0 Audio) | OK | USB external microphone |
| Speakers (Realtek Audio) | OK | Built-in laptop speakers |
| Headphones (Realtek USB2.0 Audio) | OK | USB headphone output |
| TOZO AeroSound3 devices | Unknown | Bluetooth — not connected at audit time |

---

## 7. Installed Ollama Models

Ollama v0.35.0 is installed and the service is running at `http://127.0.0.1:11434`.

| Model | ID | Size on Disk | Architecture | Parameters | Quantization | Thinking Support |
|:---|:---|---:|:---|---:|:---|:---|
| `qwen3.5:4b` | 2a654d98e6fb | 3.4 GB | qwen35 | 4.7B | Q4_K_M | Yes (`levels: false, true`) |
| `qwen3.5:2b-q4_K_M` | 124a03c34777 | 1.9 GB | qwen35 | 2.3B | Q4_K_M | Yes (`levels: false, true`) |
| `gemma4:e2b-it-qat` | 07ea59a47401 | 4.3 GB | gemma4 | 4.6B | Q4_0 | Yes (`levels: false, true`) |
| `phi4-mini:latest` | 78fad5d182a7 | 2.5 GB | phi3 | 3.8B | Q4_K_M | No |
| `ministral-3:3b` | f04aa1c738f6 | 3.0 GB | — | 3B | — | — |
| `granite4.2:3b-q4_K_M` | 40577dc168a3 | 2.2 GB | — | 3B | Q4_K_M | — |

---

## 8. Existing Local Model Assets

| File | Location | Size |
|:---|:---|---:|
| Qwen3-4B-Q4_K_M.gguf | `%LOCALAPPDATA%\OpenBagus\models\` | 2,381 MB |
| id_ID-news_tts-medium.onnx | `%LOCALAPPDATA%\OpenBagus\models\tts\` | 60 MB |
| llama-server-impl.dll | `%LOCALAPPDATA%\OpenBagus\bin\` | 8.75 MB |
| ggml-cuda.dll | `%LOCALAPPDATA%\OpenBagus\bin\` | 141 MB |
| cublas64_13.dll | `%LOCALAPPDATA%\OpenBagus\bin\` | 52 MB |
| cublasLt64_13.dll | `%LOCALAPPDATA%\OpenBagus\bin\` | 470 MB |

> The existing `llama-server` with `Qwen3-4B-Q4_K_M.gguf` remains as backup provider.

---

## 9. Benchmark Results (Ollama, 100% GPU, RTX 3050)

### 9.1 qwen3.5:2b-q4_K_M (FAST candidate)

| Metric | Result |
|:---|---:|
| VRAM usage (loaded) | 1,500 MB (~2.5 GB with overhead + KV cache) |
| Cold load latency | 4,991 ms |
| Warm TTFT (32 tokens) | **499 ms** |
| Generation throughput | **92.1 tok/s** (non-thinking) |
| DEEP mode TTFT (think=true) | 8,815 ms (256 token budget) |
| DEEP mode throughput | 57.9 tok/s |
| Context used | 2,048 (FAST) / 4,096 (DEEP) |
| GPU placement | 100% GPU ✅ |

### 9.2 qwen3.5:4b (DEEP candidate)

| Metric | Result |
|:---|---:|
| VRAM usage (loaded) | 3,000 MB (~3.9 GB with overhead + KV cache) |
| Cold load latency | 7,301 ms |
| Warm TTFT (32 tokens) | **676 ms** |
| Generation throughput | **48.5 tok/s** (non-thinking) |
| GPU placement | 100% GPU ✅ |

---

## 10. Model Selection Decisions

### FAST Mode: `qwen3.5:2b-q4_K_M`

**Rationale:**
- 499ms warm TTFT provides snappy, responsive conversation.
- 92 tok/s generates 512 tokens in ~5.5 seconds — suitable for concise answers.
- Uses 2.47 GB VRAM loaded — leaves 3.5 GB for ASR, TTS, Godot companion.
- Indonesian language support confirmed.
- Tool calling supported.
- `think: false` confirmed in Ollama API.

### DEEP_REASONING Mode: `qwen3.5:4b`

**Rationale:**
- Higher parameter count (4.7B vs 2.3B) provides materially better reasoning quality.
- 676ms warm TTFT acceptable for an explicitly requested deep analysis workflow.
- `think: true` enables Ollama's supported extended thinking mode.
- Uses 3.88 GB VRAM loaded — manageable if FAST model is unloaded first.
- Thinking traces are separated from user-facing content (verified via API response inspection).

### VRAM Allocation Plan

| Component | FAST Mode | DEEP Mode |
|:---|---:|---:|
| Windows + Chrome baseline | 159 MB | 159 MB |
| qwen3.5:2b (FAST) | 2,470 MB | — |
| qwen3.5:4b (DEEP) | — | 3,888 MB |
| Whisper ASR (CPU offloaded) | 0 MB | 0 MB |
| Piper TTS ONNX (CPU) | 0 MB | 0 MB |
| Godot companion (3D renderer) | ~200 MB | ~200 MB |
| **Total** | **~2,830 MB** | **~4,247 MB** |
| **Free headroom** | **~3,314 MB** | **~1,897 MB** |

> ASR (Whisper) runs on **CPU** to reserve VRAM for the LLM. The i5-13450HX has sufficient threads.
> Godot uses the **Compatibility** renderer (OpenGL) to minimize VRAM consumption.

---

## 11. Tool Availability

| Tool | Installed | Version | Notes |
|:---|:---|:---|:---|
| Ollama | ✅ | 0.35.0 | Running at port 11434 |
| Python | ✅ | 3.14.7 | Virtual env at `.venv` |
| Cargo (Rust) | ✅ | — | `C:\Users\bagus\.cargo\bin\cargo.exe` |
| Godot 4 | ❌ | Not installed | Download required |
| Blender | ❌ | Not installed | Not required — procedural 3D |
| CUDA 12 DLLs | ✅ | 13.4 | In `%LOCALAPPDATA%\OpenBagus\bin\` |

---

## 12. Configuration Decisions

| Decision | Choice | Justification |
|:---|:---|:---|
| Primary FAST model | `qwen3.5:2b-q4_K_M` | 92 tok/s, 499ms TTFT, 2.47GB VRAM |
| Primary DEEP model | `qwen3.5:4b` | Better reasoning, supports think=true, 676ms TTFT |
| Model switching | Sequential (not concurrent) | 6GB VRAM cannot hold both simultaneously |
| ASR execution | **CPU** (i5-13450HX) | Reserves VRAM for LLM |
| TTS execution | CPU (ONNX, ~160ms/sentence) | Already verified in voice system |
| Companion renderer | Godot 4 Compatibility (OpenGL) | Minimal VRAM, good Windows support |
| IPC protocol | **Local WebSocket** (127.0.0.1:7432) | Simple, versioned, typed messages |
| Ollama keep_alive | `30m` | Model stays warm during active session |
| Context window FAST | 2,048 tokens | Bounding RAM and inference cost |
| Context window DEEP | 4,096 tokens | Sufficient for multi-document research |
