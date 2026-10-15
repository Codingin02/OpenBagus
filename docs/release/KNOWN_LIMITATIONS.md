# OPENBAGUS — KNOWN LIMITATIONS & SCOPE BOUNDARIES
**Date:** 2026-10-16  
**Execution Context:** Codex Ultra Consolidation  

---

## 1. 3D Character Pipeline & Armored V1.2
- **Status:** `REVIEW_REQUIRED` (Unfinished Art Checkpoint).
- **Detail:** In accordance with non-negotiable consolidation instructions, no 3D asset redesign or rig rewriting was performed. The Armored V1.2 mechanical collision prototype is preserved as a diagnostic artifact under `reports/bagusmax_3d/armored_v1_2/` and `assets/bagusmax/armor/`. It is not marked production-ready.
- **Companion CLI Decoupling:** The unfinished 3D visual companion does not block or impair core conversational CLI or voice functions.

## 2. Voice Hardware Edge Cases
- **Acoustic Environment:** In extremely quiet environments with sensitive microphones, Faster-Whisper Large-v3 may occasionally produce hallucinated outro tokens if background noise floor calibration is bypassed. Adaptive RMS floor gating (<0.0035 RMS) and outro suppression filters are active to prevent this in standard operation.
- **Microphone Hardware Mismatch:** If a USB microphone is physically unplugged during an active voice session, Windows WASAPI stream recovery re-initializes on the default communication device; however, audio frames captured during the exact disconnect millisecond are dropped.

## 3. Windows Installer Packaging
- **Code Signing:** `OpenBagus-Setup.exe` is unsigned (self-built trial). Windows Defender SmartScreen may display an unknown publisher notification upon first execution. No system security bypass or global policy modifications have been made.
- **Model Dependencies:** The installer installs the core binary application and bundled Python runtime (1.10 GB), but assumes the canonical models directory exists at `E:\Projects\OpenBagus\models`. It is an offline/local-first trial installer, not a cloud auto-downloader.
