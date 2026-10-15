# OPENBAGUS — V5.1 MODEL STORAGE ARCHITECTURE & REPOSITORY AUDIT

**Canonical Root:** `E:\Projects\OpenBagus\models`  
**Resolver Implementation:** `openbagus/core/model_resolver.py`  
**Date:** 2026-10-15  
**Audit Status:** **VERIFIED & COMPLIANT**  

---

## 1. Architectural Mandate & Problem Statement

Prior to V5.1, model storage was fragmented across multiple machine-specific paths:
- GGUF weights: `%LOCALAPPDATA%\OpenBagus\models`
- Piper TTS weights: `%LOCALAPPDATA%\OpenBagus\models\tts`
- Faster-Whisper ASR: `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3`
- Silero VAD: Python virtual environment site-packages

This fragmentation created several vulnerabilities:
1. Moving or sharing the project folder broke model resolution.
2. Unclear visibility into what models were physically downloaded.
3. Lack of bit-exact checksum tracking in project version control.
4. Risk of silent downloads if external caches were cleared.

---

## 2. V5.1 Repository-Local Storage Layout

All models now reside in the main repository:

```text
E:\Projects\OpenBagus\
├── models\
│   ├── asr\
│   │   └── faster_whisper\
│   │       ├── config.json
│   │       ├── model.bin
│   │       ├── preprocessor_config.json
│   │       ├── tokenizer.json
│   │       └── vocabulary.json
│   │
│   ├── llm\
│   │   ├── fast\
│   │   │   └── Qwen3-4B-Q4_K_M.gguf
│   │   ├── deep\
│   │   └── english_tutor\
│   │
│   ├── tts\
│   │   ├── indonesian\
│   │   │   ├── id_ID-news_tts-medium.onnx
│   │   │   └── id_ID-news_tts-medium.onnx.json
│   │   ├── english\
│   │   │   └── norman-medium\
│   │   │       ├── en_US-norman-medium.onnx
│   │   │       └── en_US-norman-medium.onnx.json
│   │   └── experimental\
│   │
│   ├── vad\
│   │   └── silero\
│   │       └── silero_vad_v6.onnx
│   │
│   ├── ollama\
│   │
│   ├── manifest.json
│   └── README.md
│
├── .cache\
│   ├── huggingface\
│   ├── torch\
│   ├── pip\
│   └── downloads\
```

---

## 3. Storage Audit & Path Resolution Verification

The runtime path resolution was audited on live Python processes running from both `E:\Projects\OpenBagus` and `E:\Projects\OpenBagus-Voice`:

| Component | Resolved Runtime Path | Within `models/`? | External/AppData Reference? |
| :--- | :--- | :---: | :---: |
| **ModelResolver Root** | `E:\Projects\OpenBagus\models` | **YES** | None |
| **LLM Fast (Qwen)** | `E:\Projects\OpenBagus\models\llm\fast\Qwen3-4B-Q4_K_M.gguf` | **YES** | None |
| **LLM Tutor** | `E:\Projects\OpenBagus\models\llm\fast\Qwen3-4B-Q4_K_M.gguf` | **YES** | None |
| **Indonesian TTS** | `E:\Projects\OpenBagus\models\tts\indonesian\id_ID-news_tts-medium.onnx` | **YES** | None |
| **English TTS** | `E:\Projects\OpenBagus\models\tts\english\norman-medium\en_US-norman-medium.onnx` | **YES** | None |
| **Faster-Whisper ASR**| `E:\Projects\OpenBagus\models\asr\faster_whisper` | **YES** | None |
| **Silero VAD** | `E:\Projects\OpenBagus\models\vad\silero\silero_vad_v6.onnx` | **YES** | None |
| **Hugging Face Cache**| `E:\Projects\OpenBagus\.cache\huggingface` | **YES** | None |
| **PyTorch Cache** | `E:\Projects\OpenBagus\.cache\torch` | **YES** | None |
| **Ollama Store** | `E:\Projects\OpenBagus\models\ollama` | **YES** | None |

---

## 4. Offline Safety & No Silent Downloads

`faster_whisper.WhisperModel` is initialized with `local_files_only=True` when pointing to `models/asr/faster_whisper`. If network connectivity is lost or disabled, all models continue to function normally without network timeouts, blocking errors, or attempted redownloads.
