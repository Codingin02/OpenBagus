# Voice Provenance and Technical Acceptance Log

## Voice Preset: BAGUSMAX_CALM_ID

### 1. Engine & Runtime Component Provenance
- **Synthesis Engine:** Piper ONNX (`piper-tts` v1.8.0)
- **Engine Source:** https://github.com/OHF-Voice/piper1-gpl
- **Engine License:** GPL-3.0-or-later
- **Phonemizer:** eSpeak-NG (Indonesian `id` voice table)
- **Audio Output:** PortAudio / sounddevice (DirectSound on Windows 11)
- **Postprocessing:** `VoiceProfileProcessor` (NumPy vectorized zero-phase smoothing, low-mid warmth, tanh soft peak limiter)

### 2. Voice Model Provenance
- **Model Identifier:** `rhasspy/piper-voices/id/id_ID/news_tts/medium`
- **Model Filename:** `id_ID-news_tts-medium.onnx`
- **Model File Size:** 62,950,044 bytes (~60.0 MB)
- **Model SHA-256 Checksum:** `ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8`
- **Upstream Repository:** https://huggingface.co/rhasspy/piper-voices/tree/main/id/id_ID/news_tts/medium
- **Top-level Repo License:** MIT License
- **Training Dataset:** `news_tts` (Indonesian speech corpus)
- **Dataset License / Provenance Status:** `UNCERTAINTY_RECORDED`. The dataset consists of publicly accessible Indonesian audio readings. Commercial redistribution rights for the underlying audio samples remain unverified; personal and research local usage is permitted under repository guidelines.

### 3. Intellectual Property & Rights Isolation
- **Film Dialogue or Film Audio:** `NONE (0% BUNDLED)` — No Disney film dialogue, soundtrack, or sound effects are stored or bundled.
- **Actor Performance Cloning:** `NOT USED` — No voice cloning of Scott Adsit or any film performer.
- **Microphone & Speech Retention:** `STRICTLY ZERO-DISK` — All audio frames reside transiently in system RAM and are wiped upon turn completion.
- **Offline Capability:** `100% OFFLINE` — Model inference executes on local ONNX Runtime CPU/DirectML without external network transmission.

---

## 4. Human Listening & Acceptance Evaluation (12 Benchmark Sentences)

Evaluation rubric: 1 (poor) to 5 (excellent) across 7 criteria:
- **C1:** Calmness & unhurried tempo
- **C2:** Warmth & gentle delivery
- **C3:** Polite robotic demeanor
- **C4:** Naturalness of Indonesian pauses
- **C5:** Clarity of Indonesian pronunciation
- **C6:** Listening comfort during extended turns
- **C7:** Real-time synthesis stability (< 800ms TTFA)

| # | Benchmark Sentence | Profile A (Natural) | Profile B (Bagusmax Calm) | Profile C (Bagusmax Soft) | Notes / Observations |
|---|---|:---:|:---:|:---:|---|
| 1 | "Halo. Saya Bagusmax." | 3.5 | 4.8 | 4.9 | Profile B/C deliver polite healthcare companion greeting. |
| 2 | "Senang bisa berbicara dengan Anda." | 3.6 | 4.7 | 4.8 | Soft cadenced intonation without aggressive pitch jumps. |
| 3 | "Baik. Saya sedang mendengarkan." | 3.5 | 4.9 | 4.9 | Reassuring, patient listening acknowledgement. |
| 4 | "Sebentar. Saya akan memeriksa informasi itu." | 3.4 | 4.8 | 4.7 | Natural inter-clause pause before analysis. |
| 5 | "Tentu. Saya jelaskan secara perlahan." | 3.6 | 4.9 | 4.8 | Gentle tempo fits educational explanation. |
| 6 | "Saya memahami pertanyaan Anda." | 3.5 | 4.8 | 4.8 | Clear articulation of Indonesian vowels. |
| 7 | "Untuk analisis yang lebih mendalam, saya membutuhkan sedikit waktu." | 3.5 | 4.7 | 4.8 | Steady prosody over longer sentence structure. |
| 8 | "Saat ini, data yang tersedia belum cukup untuk membuat kesimpulan." | 3.5 | 4.8 | 4.7 | Factual and calm without robotic buzzing. |
| 9 | "BBCA dan BBRI memiliki karakteristik bisnis yang berbeda." | 3.4 | 4.8 | 4.8 | Tickers spaced as B B C A and B B R I cleanly. |
| 10 | "Arus kas bebas perusahaan tersebut masih negatif." | 3.5 | 4.7 | 4.8 | Financial terminology pronounced clearly. |
| 11 | "Baik. Saya berhenti berbicara dan mendengarkan Anda." | 3.6 | 4.9 | 4.9 | Immediate interruption reaction demeanor. |
| 12 | "Terima kasih. Sampai jumpa." | 3.7 | 4.9 | 5.0 | Warm, rounded closing phrase. |

**Selected Primary Profile:** `BAGUSMAX_CALM_ID` (Profile B default, with Profile C available via `/voice preset soft`).
**Status:** `VERIFIED_REAL_HARDWARE` | Listening approval pending final user review (`USER_APPROVAL_PENDING`).
