# OPENBAGUS — V5.1 RESUME CHECKPOINT & REPOSITORY INTEGRITY

**Canonical Repository:** `E:\Projects\OpenBagus`  
**Active Worktree:** `E:\Projects\OpenBagus-Voice`  
**Active Branch:** `feat/openbagus-local-voice-live`  
**Base Commit:** `66abcdf`  
**Date:** 2026-10-15  
**Execution Context:** Master Directive V5.1  

---

## 1. Verified Repository State

### 1.1 Canonical Model Store (`E:\Projects\OpenBagus\models`)
All operational AI weights and models have been migrated to the main repository:
- `models/llm/fast/Qwen3-4B-Q4_K_M.gguf` (2,497,280,256 bytes, SHA-256: `7485fe6f...`)
- `models/tts/indonesian/id_ID-news_tts-medium.onnx` (62,950,044 bytes, SHA-256: `ed8f02aa...`)
- `models/tts/indonesian/id_ID-news_tts-medium.onnx.json` (5,050 bytes, SHA-256: `1ef67707...`)
- `models/tts/english/norman-medium/en_US-norman-medium.onnx` (63,531,379 bytes, SHA-256: `b9739443...`)
- `models/tts/english/norman-medium/en_US-norman-medium.onnx.json` (4,968 bytes, SHA-256: `6c2db7f5...`)
- `models/vad/silero/silero_vad_v6.onnx` (1,245,151 bytes, SHA-256: `4cbf549b...`)
- `models/asr/faster_whisper/model.bin` (3,087,284,237 bytes, SHA-256: `69f74147...`)
- `models/asr/faster_whisper/config.json`, `preprocessor_config.json`, `tokenizer.json`, `vocabulary.json`
- `models/manifest.json` (Bit-exact SHA-256 manifest)
- `models/README.md` (Repository documentation)

### 1.2 Central Model Resolver
- File: `openbagus/core/model_resolver.py`
- Enforces single-source-of-truth from `E:\Projects\OpenBagus\models`.
- Configures environment caches:
  - `HF_HOME`: `E:\Projects\OpenBagus\.cache\huggingface`
  - `HF_HUB_CACHE`: `E:\Projects\OpenBagus\.cache\huggingface\hub`
  - `TORCH_HOME`: `E:\Projects\OpenBagus\.cache\torch`
  - `OLLAMA_MODELS`: `E:\Projects\OpenBagus\models\ollama`
  - `OPENBAGUS_MODEL_DIR`: `E:\Projects\OpenBagus\models`
- Prevents path traversal and guarantees offline execution (`local_files_only=True`).

### 1.3 Worktree Boundaries
- `E:\Projects\OpenBagus` (main): Hosts `models/`, `.cache/`, and `config/local_ai/models.json`.
- `E:\Projects\OpenBagus-3D` (Codex assets): **Strictly untouched**.
- `E:\Projects\OpenBagus-Voice`: Contains voice runtime, English tutor module, and acceptance test suite.
- Remote Git: Zero auto-pushes; zero unapproved merges to main.

---

## 2. Rollback & Recovery Guide

If rolling back V5.1 changes:
```powershell
# In E:\Projects\OpenBagus-Voice
git restore openbagus/ tests/
# Note: Original weights remain intact in %LOCALAPPDATA%\OpenBagus\models and %USERPROFILE%\.cache
```
To remove the repository-local models copy if needed:
```powershell
Remove-Item -Recurse -Force "E:\Projects\OpenBagus\models"
Remove-Item -Recurse -Force "E:\Projects\OpenBagus\.cache"
```
