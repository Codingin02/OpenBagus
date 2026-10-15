# OPENBAGUS — V5.1 DEFERRED INSTALLATION & REPOSITORY-LOCAL STORAGE REPORT

**Date:** 2026-10-15  
**Execution Mode:** Local-First / Windows 11 Native Terminal / Wi-Fi Active  
**Canonical Model Repository:** `E:\Projects\OpenBagus\models`  
**Target Hardware:** Intel Core i5-13450HX, NVIDIA GeForce RTX 3050 Laptop GPU (6144 MB VRAM), 12 GB RAM  
**Active Worktree:** `E:\Projects\OpenBagus-Voice`  
**Branch:** `feat/openbagus-local-voice-live`  

---

## 1. Executive Summary

Under Master Directive V5.1, all operational machine learning weights, tokenizers, phonetic configs, and cache directories have been permanently relocated from dispersed external locations (`%LOCALAPPDATA%`, `Downloads`, user Hugging Face cache) into the canonical repository:

`E:\Projects\OpenBagus\models`

Key accomplishments:
1. **Migration & Checksum Verification:**
   - 11 operational model files (~5.6 GB) migrated to `E:\Projects\OpenBagus\models` with 100% bit-exact SHA-256 verification.
   - Original weights preserved in `%LOCALAPPDATA%\OpenBagus\models` as immutable rollback backup.
2. **Central Model Resolver (`openbagus.core.model_resolver.ModelResolver`):**
   - Implemented single-source-of-truth resolver across all repository worktrees (`OpenBagus`, `OpenBagus-Voice`, `OpenBagus-Data`).
   - Normalizes paths, enforces path traversal security within repo boundaries, and guarantees zero silent downloads when running offline.
3. **Cache Isolation:**
   - `HF_HOME` and `HF_HUB_CACHE` routed to `E:\Projects\OpenBagus\.cache\huggingface`.
   - `TORCH_HOME` routed to `E:\Projects\OpenBagus\.cache\torch`.
   - `OLLAMA_MODELS` routed to `E:\Projects\OpenBagus\models\ollama`.
4. **Git Tracking & Ignore Policy:**
   - `.gitignore` updated: binary model weights (`*.gguf`, `*.onnx`, `*.bin`, `*.pt`, `blobs/`) are ignored to protect Git performance.
   - Metadata files (`models/manifest.json`, `models/README.md`, configurations) remain strictly tracked by Git.

---

## 2. Operational Model Inventory & Verified Checksums

| Category | Component | File Name | Size (Bytes) | SHA-256 Checksum | Canonical Repo Path | License |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **LLM (Fast/Tutor)** | Qwen3-4B-Q4_K_M | `Qwen3-4B-Q4_K_M.gguf` | 2,497,280,256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | `models/llm/fast/` | Apache-2.0 |
| **TTS (Indonesian)** | Piper ID Newsreader | `id_ID-news_tts-medium.onnx` | 62,950,044 | `ed8f02aa593f7af609bc17215392febe747dbef8602b1307b27ecdb767c9c0b1` | `models/tts/indonesian/` | MIT |
| **TTS (Indonesian)** | Piper ID Config | `id_ID-news_tts-medium.onnx.json` | 5,050 | `1ef677072668a5e11c81ef44280bc8a543881ef126584c563ef34d35e12ec686` | `models/tts/indonesian/` | MIT |
| **TTS (English)** | Piper US Norman | `en_US-norman-medium.onnx` | 63,531,379 | `b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71` | `models/tts/english/norman-medium/` | MIT |
| **TTS (English)** | Piper US Config | `en_US-norman-medium.onnx.json` | 4,968 | `6c2db7f558a4a8ded18eeecbb09bcf69a53818e3845ca462ebcfa9b3ca0f074a` | `models/tts/english/norman-medium/` | MIT |
| **ASR (STT)** | Faster-Whisper | `model.bin` | 3,087,284,237 | `69f74147e333473188ff6a380ce3e970a05a81ca0df51e94146a29d91f42d20d` | `models/asr/faster_whisper/` | Apache-2.0 |
| **ASR (STT)** | Faster-Whisper | `config.json` | 2,394 | `a9306624f5ec1427508ffb0bf120e26ca3d8393aa9cecb1f715aa1f9776f8272` | `models/asr/faster_whisper/` | Apache-2.0 |
| **ASR (STT)** | Faster-Whisper | `tokenizer.json` | 2,480,617 | `6d8cbd7cd0d8d581335025a1fcf15a5f6e80b435ff51206cfd116a4c28f11e9a` | `models/asr/faster_whisper/` | Apache-2.0 |
| **ASR (STT)** | Faster-Whisper | `vocabulary.json` | 1,068,114 | `c69260f2ab26d659adfa5590c6ca8063060fcbbabfef0790d0bda14ecf1624c9` | `models/asr/faster_whisper/` | Apache-2.0 |
| **ASR (STT)** | Faster-Whisper | `preprocessor_config.json` | 340 | `7ccc62c6f2765af14daec8353e6b701d7fc498d9ae48744793f77977eb71b12b` | `models/asr/faster_whisper/` | Apache-2.0 |
| **VAD** | Silero VAD v6 | `silero_vad_v6.onnx` | 1,245,151 | `4cbf549b8326f60f9ddcb2dd2e6fa80ec5e4f479beacae296bf3c162eb05b76b` | `models/vad/silero/` | MIT |

---

## 3. Worktree Boundary Adherence

- `E:\Projects\OpenBagus-3D` (Codex worktree): Strictly untouched.
- `E:\Projects\OpenBagus` (main): Hosts the canonical `models/` directory and `.cache/` directory.
- `E:\Projects\OpenBagus-Voice`: Contains voice engine, turn controller, and acceptance test code, linking to `E:\Projects\OpenBagus\models`.
