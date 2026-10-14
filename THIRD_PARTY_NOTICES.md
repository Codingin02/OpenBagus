# Third-Party Components and Rights Register

This register documents third-party open-source components, models, and assets utilized by OpenBagus.
Each component remains subject to its own upstream license and terms.

| Component / Asset | Upstream Project | Version / Checksum | License | Project Usage | Distribution Status | Verification Status |
|---|---|---|---|---|---|---|
| **Piper TTS Engine** | https://github.com/OHF-Voice/piper1-gpl | `piper-tts` v1.8.0 | GPL-3.0-or-later | Local Indonesian Speech Synthesis | Copyleft obligations apply if redistributing binaries | VERIFIED_INSTALLED |
| **Piper Voice Model (`id_ID-news_tts-medium`)** | https://huggingface.co/rhasspy/piper-voices/tree/main/id/id_ID/news_tts/medium | SHA-256: `ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8` | Model Repo: MIT; Training Dataset: `news_tts` | Offline voice model for Indonesian speech | Private local use verified; commercial redistribution unverified | LICENSE_REVIEW_REQUIRED |
| **Faster-Whisper** | https://github.com/SYSTRAN/faster-whisper | v1.1.1 | Apache-2.0 | Local Speech-to-Text (ASR) on CUDA | Permitted | VERIFIED_INSTALLED |
| **CTranslate2** | https://github.com/OpenNMT/CTranslate2 | v4.6.0 | MIT | Transformer inference engine for Whisper | Permitted | VERIFIED_INSTALLED |
| **Silero VAD** | https://github.com/snakers4/silero-vad | ONNX Runtime | MIT | Real-time Voice Activity Detection | Permitted | VERIFIED_INSTALLED |
| **Sounddevice / PortAudio** | https://github.com/spatialaudio/python-sounddevice | v0.5.1 / PortAudio v19 | MIT | Native Windows DirectSound audio I/O | Permitted | VERIFIED_INSTALLED |
| **NumPy** | https://github.com/numpy/numpy | v2.2.0 | BSD-3-Clause | Audio DSP, array buffers, resampling | Permitted | VERIFIED_INSTALLED |
| **ONNX Runtime** | https://github.com/microsoft/onnxruntime | v1.20.1 | MIT | Piper & VAD neural network execution | Permitted | VERIFIED_INSTALLED |
| **Meta MMS-TTS Indonesian** (Alternative Candidate) | https://huggingface.co/facebook/mms-tts-ind | VITS ONNX | CC BY-NC 4.0 | Evaluated alternative candidate | Non-commercial restriction; not bundled | EVALUATION_ONLY |
| **Baymax / Disney Material** | Disney (*Big Hero 6*) | Not bundled (0%) | Proprietary | Stylistic & art-direction reference only | DO NOT BUNDLE; NOT AUTHORIZED | RIGHTS_ISOLATED |

---

## Detailed Notes & Rights Layers:

### Layer A — Original OpenBagus Materials
Original source code, quant engine, CLI interfaces, and orchestration systems are copyright (c) 2026 the original authors under the root repository LICENSE.

### Layer B — Open-Source Dependencies
Upstream libraries (`faster-whisper`, `CTranslate2`, `sounddevice`, `numpy`, `onnxruntime`) remain licensed under their respective Apache-2.0, MIT, and BSD licenses.

### Layer C — TTS Voice Model and GPL Engine
- The maintained Piper engine is licensed under **GPL-3.0-or-later**. In local personal environments, running the package creates no copyleft distribution obligations. However, before creating binary distributions or installers containing Piper, GPL compliance (e.g. source availability) must be reviewed.
- The `id_ID-news_tts-medium` voice model is trained on the Indonesian `news_tts` corpus. While public for personal/research use, dataset commercial rights contain historical uncertainties that should be evaluated prior to commercial deployment.

### Layer D — Disney Intellectual Property
- Baymax, the red armored superhero suit, inflatable healthcare companion design, and all character names originate from Disney's *Big Hero 6*.
- OpenBagus does **not** hold or claim any license or endorsement from Disney.
- No film audio, sound effects, or actor voice recordings (Scott Adsit) are bundled in this project.
- See full disclaimer in [docs/legal/BAGUSMAX_IP_NOTICE.md](docs/legal/BAGUSMAX_IP_NOTICE.md).
