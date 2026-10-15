# OPENBAGUS — POST-WIFI RESUME CHECKPOINT

**Worktree:** `E:\Projects\OpenBagus-Voice`  
**Active Branch:** `feat/openbagus-local-voice-live`  
**Base Commit:** `36a7de8`  
**Target Architecture:** Windows 11 / RTX 3050 6GB / Local-First Python Runtime  
**Date:** 2026-10-15  

---

## 1. Current State & Verification Summary

Following the completion of the deferred model download and recovery directive:

1. **Local Audio Model Store (`%LOCALAPPDATA%\OpenBagus\models\tts\`):**
   - `id_ID-news_tts-medium.onnx` (62.95 MB, SHA-256: `ed8f02aa...`) — Active Indonesian TTS (Bagusmax-calm profile).
   - `en_US-norman-medium.onnx` (63.53 MB, SHA-256: `b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71`) — Active English Male TTS (Norman baritone profile, $F_0 = 106.5\text{ Hz}$).
   - Both configuration JSON files verified and loaded.

2. **ASR Model (`faster-whisper-large-v3`):**
   - Snapshot active in `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3`.
   - VAD filter, silence rejection, and outro pruning active.

3. **Software Architecture Additions:**
   - `openbagus/domains/english_tutor/`: English learning domain with transfer error diagnostics and pronunciation scoring.
   - `openbagus/ai/memory/working_context.py`: Namespace isolation (`FINANCIAL_RESEARCH` vs `ENGLISH_TUTOR`).
   - `openbagus/voice/tts_engine.py`: Multi-model bilingual streaming synthesis.
   - `openbagus/ai/harness/orchestrator.py`: Context routing and prompt management.

4. **Acceptance Test Status:**
   - Test suite: `tests/run_v5_acceptance.py`.
   - Result: **26 PASSED, 0 FAILED** (Total time: 27.22s).

5. **External Candidate Provenance Status:**
   - Wikidepia / drat (`wibowo`, `ardi`, `gadis`): Tagged **`LICENSE_REVIEW_REQUIRED`** due to Microsoft Cognitive Services non-commercial restriction on training data. Not deployed to production.

---

## 2. Worktree Boundaries & Integrity

- `E:\Projects\OpenBagus` (main): Untouched.
- `E:\Projects\OpenBagus-3D` (Codex assets): Untouched.
- `E:\Projects\OpenBagus-Voice`: Contains all voice runtime and English tutor code.
- Remote Git: No git push executed; no merge into main.

---

## 3. Rollback Instructions

If rollback of deferred installations is ever required:
```powershell
# In E:\Projects\OpenBagus-Voice
git restore openbagus/ tests/
git clean -fd openbagus/domains/english_tutor/
# Optional: remove downloaded English voice model
Remove-Item "$env:LOCALAPPDATA\OpenBagus\models\tts\en_US-norman-medium.*" -Force
```
