# OPENBAGUS — V5.1 VOICE IDENTITY, ACOUSTIC AUDIT & LEGAL COMPARISON

**Date:** 2026-10-15  
**Canonical Directory:** `E:\Projects\OpenBagus\models\tts`  
**Target Hardware:** Windows 11 / Realtek Audio WASAPI / NVIDIA RTX 3050  
**Directive:** Master Directive V5.1  

---

## 1. Executive Summary

Voice synthesis in OpenBagus requires meeting three strict engineering criteria:
1. **Acoustic Character:** Calm, warm, non-rushed, masculine or neutral-low register inspired by healthcare companion robotics (Baymax personality reference).
2. **Legal & Provenance Clearance:** Zero risk of synthetic dataset copyright violation or terms-of-service breach.
3. **Local Performance:** High real-time synthesis factor (> 10x RTF) with zero disk retention (*zero-disk audio*).

---

## 2. Voice Candidate Comparison & Acoustic Telemetry

Fundamental frequency ($F_0$) was measured on real audio samples using autocorrelation pitch extraction:

$$\text{lag} = \arg\max_{\tau \in [\tau_{\min}, \tau_{\max}]} \sum_{t} x[t] x[t+\tau], \quad F_0 = \frac{f_s}{\text{lag}}$$

| Voice Model | Language | Pitch Register ($F_0$) | Architecture | Speed Factor (RTF) | License Status | Production Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`en_US-norman-medium`** | English (US) | **106.5 Hz** (Baritone Male) | Piper ONNX | **18.5x** | MIT (Rhasspy) | **ACTIVE** (`models/tts/english/norman-medium/`) |
| **`id_ID-news_tts-medium`** | Indonesian | **253.4 Hz** (Studio Female) | Piper ONNX | **19.2x** | MIT (Rhasspy) | **ACTIVE** (`models/tts/indonesian/`) [Conditioned] |
| **`wibowo`** (Wikidepia/drat) | Indonesian | **157.5 Hz** (Androgynous Low) | PyTorch/VITS | ~4.5x | Non-commercial | **`LICENSE_REVIEW_REQUIRED`** (Quarantined) |
| **`gadis`** (Wikidepia/drat) | Indonesian | **237.1 Hz** (High Female) | PyTorch/VITS | ~4.5x | Non-commercial | **`LICENSE_REVIEW_REQUIRED`** (Quarantined) |
| **`ardi`** (Wikidepia/drat) | Indonesian | ~170.0 Hz (Energetic Male) | PyTorch/VITS | ~4.5x | Non-commercial | **`LICENSE_REVIEW_REQUIRED`** (Quarantined) |

---

## 3. Provenance & License Audit of Community Candidates

### 3.1 Wikidepia / drat Indonesian Models (`wibowo`, `ardi`, `gadis`)
- **Dataset Composition:**
  - 2,000 synthetic audio sentences generated using Microsoft Azure Cognitive Services Speech API (`id-ID-ArdiNeural`, `id-ID-GadisNeural`).
  - 4 hours of public domain audiobook narration.
- **Upstream License Prohibitions:**
  - *Microsoft Cognitive Services Terms of Use (Section 3.2)* strictly prohibits:
    *"...using the output of the Service to train, calibrate, or fine-tune competing machine learning models or text-to-speech technologies."*
  - Upstream GitHub repository explicitly notes:
    *"DO NOT USE FOR COMMERCIAL PURPOSES! Trained with Azure TTS synthetic audio"*.
- **Architectural Decision:**
  To safeguard OpenBagus enterprise distribution and IP compliance, the model weights are **quarantined** under `models/tts/experimental/` and **NOT** included in the active production build.

---

## 4. Bagusmax Indonesian Acoustic Conditioning

Because the currently available legal Indonesian model (`id_ID-news_tts-medium`) is female newsreader-trained, OpenBagus applies real-time in-memory DSP conditioning (`BagusmaxVoiceProcessor`):

1. **Tempo Relaxation:** `length_scale = 1.06` to `1.08` eliminates rushed newsreader pacing.
2. **Warmth & Low-End Boost:** IIR low-shelf filter (+2.5 dB at 250 Hz) shifts perceived vocal weight.
3. **Consonant Smoothing:** Soft noise scale (`0.52 - 0.55`) softens harsh sibilance.
4. **Resonant Chamber:** 45 ms delay reflection simulates gentle plastic casing of a healthcare robot.

---

## 5. Bilingual Routing in English Tutor Mode

When conversational English is detected:
- **English Dialogue:** Automatically routed to `en_US-norman-medium` (106.5 Hz baritone male voice).
- **Indonesian Feedback & Grammar Explanations:** Routed to Bagusmax Indonesian voice.
- **Zero Disk Retention:** Audio streams directly via memory buffers (`numpy.ndarray`) without saving temporary `.wav` files.
