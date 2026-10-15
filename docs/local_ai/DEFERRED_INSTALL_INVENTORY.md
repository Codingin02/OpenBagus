# OPENBAGUS — DEFERRED MODEL & RUNTIME INVENTORY
## Hasil Audit Kondisi Sistem, Model Lokal, Akselerasi GPU, dan Hardware Audio

**Tanggal Audit:** 15 Oktober 2026  
**Auditor:** Antigravity (Senior Systems & AI Infrastructure Engineer)  
**Sistem Operasi:** Windows 11 Home 64-bit (Build 22631)  
**Target Hardware:** Intel Core i5-13450HX, NVIDIA GeForce RTX 3050 Laptop GPU (6 GB VRAM), RAM 12 GB  
**Worktree:** `E:\Projects\OpenBagus-Voice` (Branch `feat/openbagus-local-voice-live`, Commit `36a7de8`)  

---

## 1. Inventarisasi Model Bahasa Lokal (LLM)

### 1.1 Model Ollama Lokal (Server v0.35.0, Port 11434, CUDA Active)
| Nama Model | Model ID / Hash | Ukuran | Status Pemasangan | Lisensi | Kegunaan di OpenBagus |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`qwen3.5:2b-q4_K_M`** | `124a03c34777` | 1.9 GB | **TERPASANG & TERVERIFIKASI** | Apache 2.0 | FAST Provider (Percakapan Cepat & Routing) |
| **`qwen3.5:4b`** | `2a654d98e6fb` | 3.4 GB | **TERPASANG & TERVERIFIKASI** | Apache 2.0 | DEEP Provider (Analisis Finansial & Tutor) |
| **`phi4-mini:latest`** | `78fad5d182a7` | 2.5 GB | **TERPASANG** | MIT | Model Alternatif / Evaluasi |
| **`ministral-3:3b`** | `f04aa1c738f6` | 3.0 GB | **TERPASANG** | Mistral Research | Model Alternatif |
| **`granite4.2:3b-q4_K_M`** | `40577dc168a3` | 2.2 GB | **TERPASANG** | Apache 2.0 | Model Alternatif Enterprise |
| **`gemma4:e2b-it-qat`** | `07ea59a47401` | 4.3 GB | **TERPASANG** | Gemma Terms | Model Alternatif |

### 1.2 Model GGUF Standalone
| Nama Berkas | Lokasi Direktori | Ukuran | Status Verifikasi | Engine Penangan |
| :--- | :--- | :--- | :--- | :--- |
| **`Qwen3-4B-Q4_K_M.gguf`** | `%LOCALAPPDATA%\OpenBagus\models\` | 2.497.280.256 Byte | **VALID** | LlamaServerProvider / llama.cpp |

---

## 2. Inventarisasi Model Suara & Pengenalan Suara (ASR, VAD, TTS)

### 2.1 Whisper ASR (Faster-Whisper / CTranslate2)
- **Model:** `faster-whisper-large-v3`
- **Lokasi Cache:** `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3\snapshots\edaa852ec7e145841d8ffdb056a99d816223b207\`
- **Format:** CTranslate2 model weights (FP16/INT8)
- **Status:** **TERPASANG & TERVERIFIKASI** (Berjalan di GPU CUDA RTX 3050, VRAM ~2.2 GB)

### 2.2 Silero VAD (Voice Activity Detection)
- **Model:** Silero VAD ONNX (512 sampel @ 16 kHz, chunk 32 ms)
- **Integrasi:** Paket `faster_whisper.vad.SileroVADModel` / ONNX Runtime
- **Status:** **TERPASANG & TERVERIFIKASI** (Real-time dynamic noise floor tracking aktif)

### 2.3 Piper Text-To-Speech (TTS)
| Berkas Model | Bahasa & Dialek | Format | Ukuran | SHA-256 Checksum | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`id_ID-news_tts-medium.onnx`** | Bahasa Indonesia (`id-ID`) | ONNX | 62.950.044 Byte | `ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8` | **AKTIF (V5.0 Bagusmax DSP)** |
| **`id_ID-news_tts-medium.onnx.json`** | Metadata Konfigurasi | JSON | 5.050 Byte | Valid JSON | **AKTIF** |
| **`en_US-norman-medium.onnx`** | Bahasa Inggris (`en-US` Pria) | ONNX | *Tertunda (Phase 2)* | Upstream Rhasspy HuggingFace | **PENDING DOWNLOAD** |
| **`en_US-norman-medium.onnx.json`** | Metadata Konfigurasi | JSON | *Tertunda (Phase 2)* | Upstream Rhasspy HuggingFace | **PENDING DOWNLOAD** |

---

## 3. Inventarisasi Perangkat Keras & Lingkungan Eksekusi

### 3.1 Unit Pemroses Grafis (GPU) & Akselerasi Komputasi
- **GPU:** NVIDIA GeForce RTX 3050 6GB Laptop GPU (WDDM Driver 616.92)
- **Total VRAM:** 6.144 MB
- **VRAM Bebas Saat Ini:** **5.877 MB** (Penggunaan idle ~267 MB)
- **CUDA Runtime:** Driver CUDA 13.4, Library CUDA 12.x / 13.x terdeteksi di Ollama dan CTranslate2.
- **Suhu Idle:** 43°C, Daya: 3W / 95W.

### 3.2 Memori Sistem & Media Penyimpanan
- **RAM Fisik:** 11,71 GB (Tersedia: 1,78 GB saat aplikasi browser/desktop terbuka).
- **Ruang Disk C:** 104,92 GB bebas dari total 474,53 GB (SSD NVMe).
- **Ruang Disk E:** 170,86 GB bebas dari total 500,00 GB (Drive Proyek & Data).

### 3.3 Subsistem Audio Windows
- **Mikrofon Default:** `Microphone Array (Realtek(R) Audio)` — WASAPI Input Device #9 / DirectSound #4.
- **Speaker Default:** `Speakers (Realtek(R) Audio)` — WASAPI Output Device #8 / DirectSound #6.
- **Sample Rate Native:** 48.000 Hz (WASAPI/DirectSound).
- **Resampling Pipeline:** Otomatis di memori via `openbagus/voice/audio_playback.py` (22.050 Hz -> 48.000 Hz).

### 3.4 Python Virtual Environments
- **Lingkungan Kerja Aktif:** `E:\Projects\OpenBagus\.venv` (Python 3.14.7 64-bit).
  - Paket vokal: `piper-tts 1.8.0`, `faster-whisper 1.2.1`, `ctranslate2 4.8.3`, `onnxruntime 1.31.0`, `sounddevice 0.5.6`, `numpy 2.5.4`.
  - Akselerasi: `nvidia-cublas-cu12`, `nvidia-cuda-nvrtc-cu12`, `nvidia-cudnn-cu12`.
- **Lingkungan Lain:**
  - `E:\Projects\OpenBagus-Voice\.venv` (Tidak lengkap / tanpa pip).
  - `E:\Projects\VS_Code_Default\venv_ai` (Tautan usang Python 3.11).
