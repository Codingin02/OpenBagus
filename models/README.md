# OPENBAGUS — REPOSITORY-LOCAL MODEL REGISTRY

**Canonical Directory:** `E:\Projects\OpenBagus\models`  
**Architecture:** Local-First / Zero External API Key / Windows 11 RTX 3050  
**Directive:** Master Directive V5.1  

---

## 1. Overview & Single Source of Truth

In accordance with OpenBagus Architecture Directive V5.1, all operational AI weights, configs, and model caches are permanently hosted inside the main repository under `E:\Projects\OpenBagus\models`.

Runtime processes across all worktrees (`OpenBagus`, `OpenBagus-Voice`, `OpenBagus-Data`) resolve operational models exclusively through `openbagus.core.model_resolver.ModelResolver`.

No operational weights are read from `%LOCALAPPDATA%`, `Downloads`, or external user caches.

---

## 2. Directory Layout & Model Inventory

```text
models/
├── asr/
│   └── faster_whisper/
│       ├── config.json                 (Model config)
│       ├── model.bin                   (3.08 GB CTranslate2 weights)
│       ├── preprocessor_config.json
│       ├── tokenizer.json
│       └── vocabulary.json
│
├── llm/
│   ├── fast/
│   │   └── Qwen3-4B-Q4_K_M.gguf        (2.49 GB GGUF model for fast reasoning)
│   ├── deep/                           (Reserved for deep reasoning offload)
│   └── english_tutor/                  (Routed to Qwen3-4B with tutor system instruction)
│
├── tts/
│   ├── indonesian/
│   │   ├── id_ID-news_tts-medium.onnx  (62.9 MB Piper VITS Indonesian voice)
│   │   └── id_ID-news_tts-medium.onnx.json
│   ├── english/
│   │   └── norman-medium/
│   │       ├── en_US-norman-medium.onnx (63.5 MB Piper VITS US English male voice)
│   │       └── en_US-norman-medium.onnx.json
│   └── experimental/                   (Quarantined candidate voice samples)
│
├── vad/
│   └── silero/
│       └── silero_vad_v6.onnx          (1.2 MB Silero VAD ONNX model)
│
├── ollama/                             (Repository-local OLLAMA_MODELS root)
│
├── manifest.json                       (Bit-exact SHA-256 and metadata registry)
└── README.md                           (This document)
```

---

## 3. Verified Model Checksums & Licenses

| Component | Model Name | Format | Size | SHA-256 Checksum | License |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **LLM (Fast/Tutor)** | `Qwen3-4B-Q4_K_M.gguf` | GGUF | 2,497,280,256 B | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | Apache-2.0 |
| **TTS (Indonesian)** | `id_ID-news_tts-medium.onnx` | ONNX | 62,950,044 B | `ed8f02aa593f7af609bc17215392febe747dbef8602b1307b27ecdb767c9c0b1` | MIT |
| **TTS (English)** | `en_US-norman-medium.onnx` | ONNX | 63,531,379 B | `b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71` | MIT |
| **ASR (STT)** | `faster-whisper-large-v3` (`model.bin`) | CT2 | 3,087,284,237 B | `69f74147e333473188ff6a380ce3e970a05a81ca0df51e94146a29d91f42d20d` | Apache-2.0 / MIT |
| **VAD** | `silero_vad_v6.onnx` | ONNX | 1,245,151 B | `4cbf549b8326f60f9ddcb2dd2e6fa80ec5e4f479beacae296bf3c162eb05b76b` | MIT |

---

## 4. Git Policy

Binary model files (`*.gguf`, `*.onnx`, `*.bin`, `*.pt`, `*.safetensors`) are ignored by Git in `.gitignore` to prevent repository bloat, while `manifest.json`, `README.md`, configurations, and model cards remain fully tracked by Git.
