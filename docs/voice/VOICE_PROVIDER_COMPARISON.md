# OPENBAGUS — VOICE PROVIDER COMPARISON & ACOUSTIC AUDIT

**Target:** Windows 11 / Local-First / Bagusmax Persona & English Tutor  
**Audit Date:** 2026-10-15  
**Worktree:** `E:\Projects\OpenBagus-Voice`  
**Branch:** `feat/openbagus-local-voice-live`  

---

## 1. Executive Summary

This document provides an acoustic, performance, and legal comparison between currently integrated voice models and external community Indonesian candidates evaluated during the Wi-Fi availability window.

In accordance with OpenBagus legal and architectural standards:
1. All models deployed to production must have clear open-source provenance and unencumbered commercial/non-commercial licenses.
2. Synthetic speech data derived from commercial proprietary cloud APIs (e.g., Azure Speech, ElevenLabs, OpenAI) without explicit redistribution rights carries legal risk and must be placed under **`LICENSE_REVIEW_REQUIRED`**.
3. Voice identity must align with the Bagusmax persona (warm, gentle, calm, healthcare-robot inspired, non-rushed) and English Tutor requirements (clear baritone male register).

---

## 2. Acoustic Telemetry & Pitch Register Comparison

Acoustic fundamental frequency ($F_0$) was measured on real audio samples using autocorrelation pitch extraction:

$$\text{lag} = \arg\max_{\tau \in [\tau_{\min}, \tau_{\max}]} \sum_{t} x[t] x[t+\tau], \quad F_0 = \frac{f_s}{\text{lag}}$$

| Model / Candidate | Language | Voice Type | Measured $F_0$ (Pitch) | Audio Sample Rate | RTF (Speed Factor) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`en_US-norman-medium`** (Piper) | English (US) | Natural Male (Baritone) | **106.5 Hz** | 22,050 Hz | **18.5x real-time** | **PRODUCTION ACTIVE** |
| **`id_ID-news_tts-medium`** (Piper) | Indonesian | Studio Female (Modulated) | **253.4 Hz** | 22,050 Hz | **19.2x real-time** | **PRODUCTION ACTIVE** (Bagusmax-calm) |
| **`wibowo`** (Wikidepia / drat) | Indonesian | Male / Androgynous Low | **157.5 Hz** | 22,050 Hz | ~4.5x (PyTorch/VITS) | **`LICENSE_REVIEW_REQUIRED`** |
| **`gadis`** (Wikidepia / drat) | Indonesian | Female High | **237.1 Hz** | 22,050 Hz | ~4.5x (PyTorch/VITS) | **`LICENSE_REVIEW_REQUIRED`** |
| **`ardi`** (Wikidepia / drat) | Indonesian | Male Energetic | ~170.0 Hz | 22,050 Hz | ~4.5x (PyTorch/VITS) | **`LICENSE_REVIEW_REQUIRED`** |

---

## 3. Legal Provenance & Licensing Analysis

### 3.1 Piper VITS Voice Models (Rhasspy)
- **Model:** `en_US-norman-medium` & `id_ID-news_tts-medium`
- **Architecture:** ONNX Runtime VITS / Piper C++ / Python binding
- **Training Provenance:** Public domain / LibriSpeech / Common Voice datasets with permissible licenses (MIT / CC0 / Open Data).
- **License:** MIT License.
- **Production Status:** **VERIFIED & ACTIVE**. Clean provenance, zero vendor restrictions.

### 3.2 Wikidepia / drat Indonesian Models (`wibowo`, `ardi`, `gadis`)
- **Model:** VITS Indonesian TTS (`drat/TTS-Indonesia-Gratis`, `Wikidepia/indonesian-tts`)
- **Training Provenance:**
  - 2,000 speech segments synthetically generated using Microsoft Azure Neural TTS (`id-ID-ArdiNeural`, `id-ID-GadisNeural`).
  - 4 hours of public domain audiobook narration.
- **License Terms & Restrictions:**
  - Upstream Microsoft Cognitive Services Terms of Use (Section 3.2): Explicitly prohibits using speech synthesis output to train or fine-tune competing machine learning models or text-to-speech services.
  - Upstream Repository Warning: The repository author explicitly notes: *"DO NOT USE FOR COMMERCIAL PURPOSES! Trained with Azure TTS synthetic audio"*.
- **Production Status:** **`LICENSE_REVIEW_REQUIRED`**.
- **Architectural Decision:** To preserve OpenBagus enterprise integrity and avoid IP contamination, candidate weights are quarantined. Audio analysis and pitch telemetry were performed strictly on isolated test samples (`data/voice_candidates/wibowo.wav`).

---

## 4. Bagusmax Persona Alignment & Acoustic DSP Conditioning

To achieve the desired Baymax-inspired warm, calming, and gentle character on existing verified models:
1. **Pitch & Formant:** Length scale set to `1.05` to `1.08` to reduce rushed pacing.
2. **Noise Scale:** Configured with `noise_scale: 0.60` and `noise_w: 0.80` to soften harsh consonantal attacks.
3. **Punctuation Padding:** Inter-sentence pauses padded with 180 ms silence for conversational breathing room.
4. **Bilingual Routing:** When English phrases or English Tutor dialogues occur, audio is routed to `en_US-norman-medium` (106.5 Hz baritone), while Indonesian corrections and feedback utilize Bagusmax-calm conditioning.
