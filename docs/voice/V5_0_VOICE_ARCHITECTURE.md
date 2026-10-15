# OPENBAGUS — V5.0 VOICE ARCHITECTURE & REAL-TIME PIPELINE SPECIFICATION
## Arsitektur Subsistem Suara, Full-Duplex Turn Controller, Anti-Hallucination ASR, dan Zero-Disk DSP Audio

**Dokumen:** V5_0_VOICE_ARCHITECTURE.md  
**Tanggal:** 15 Oktober 2026  
**Sistem:** OpenBagus V5.0 Local Voice Live  
**Penulis:** Antigravity (Voice Systems & Audio DSP Reliability Engineer)  
**Target Hardware:** Windows 11, Intel Core i5-13450HX, NVIDIA GeForce RTX 3050 Laptop GPU (6 GB VRAM), 12 GB RAM  
**Worktree:** `E:\Projects\OpenBagus-Voice`  
**Branch:** `feat/openbagus-local-voice-live`  

---

## 1. Overview & Arsitektur Tingkat Tinggi

Sistem suara OpenBagus V5.0 dirancang sebagai arsitektur percakapan suara real-time lokal (*full-duplex*) yang mengutamakan latensi rendah, ketahanan terhadap halusinasi suara ruangan, dan integritas reproduksi audio tanpa menulis file rekaman audio sementara ke disk penyimpanan (*strictly zero-disk in-memory streaming*).

```
+-------------------------------------------------------------------------------------------------------+
|                                    WINDOWS 11 HARDWARE & AUDIO SUB-SYSTEM                             |
+-------------------------------------------------------------------------------------------------------+
        |                                                                                      ^
 [Mic Realtek Array]                                                                    [Speaker / WASAPI]
  (44.1 / 48 kHz PCM)                                                                   (44.1 / 48 kHz PCM)
        |                                                                                      |
        v                                                                                      |
+-------------------+                                                                   +---------------+
| AudioCapture      |                                                                   | AudioPlayback |
| (sounddevice in)  |                                                                   | (WASAPI out)  |
| Resample -> 16kHz |                                                                   | Resample ^    |
+-------------------+                                                                   +---------------+
        | (Queue 30ms)                                                                         ^
        v                                                                                      | (PCM 22.05kHz)
+-----------------------------------------------------------------------+               +---------------+
|                          TURN CONTROLLER                              |               | Bagusmax DSP  |
|                                                                       |               | Processor     |
| +---------------------+   +---------------------+   +---------------+ |               | - Low-Mid EQ  |
| | Silero VAD          |   | Dynamic Noise Floor |   | State Machine | |               | - De-Esser    |
| | 32ms Chunks, 16kHz  |-->| Adaptive Threshold  |-->| LISTENING     | |               | - Resonance   |
| | Speech Probability  |   | Speech Window (2.0s)|   | THINKING      | |               | - Tanh Limiter|
| +---------------------+   +---------------------+   | SPEAKING      | |               +---------------+
|            |                                        | INTERRUPTED   | |                      ^
|            v (Acoustic Gated Energy)                +---------------+ |                      |
| +---------------------+                                     |         |               +---------------+
| | Whisper ASR Engine  |                                     |         |               | Piper TTS     |
| | large-v3 (FP16 CUDA)|                                     |         |               | ONNX Runtime  |
| | Phantom Outro Purge |                                     v         |               | Singleton     |
| +---------------------+                         +-------------------+ |               | (22.05 kHz)   |
|            |                                    | Fast Greeting /   | |               +---------------+
|            +----------------------------------->| Conversational    |------------------------+
|                      (Text Transcribed)         | Harness (LLM)     |   (Sentence Stream)
|                                                 +-------------------+ |
+-----------------------------------------------------------------------+
```

---

## 2. Rincian Komponen & Threading Model

### 2.1 AudioCapture (`openbagus/voice/audio_capture.py`)
- **Fungsi:** Mengambil aliran audio analog dari mikrofon default Windows (Realtek High Definition Audio Audio Array).
- **Format Tangkapan:** Mono PCM 16-bit, native hardware sample rate (umumnya 44.100 Hz atau 48.000 Hz).
- **Resampling Internal:** Dikonversi secara real-time ke format standar 16.000 Hz menggunakan interpolasi linear cepat di memori tanpa alokasi berat.
- **Mekanisme Antrean (V5.0 Single-Pass Queue):**
  Menggunakan `queue.Queue(maxsize=120)`. Metode `get_next_frame(timeout=0.03)` memastikan thread konsumen (*Turn Controller loop*) mengambil frame audio sekali jalan tanpa redundansi polling atau duplikasi buffer.
- **Threading:** Background thread independen `_record_loop` yang berjalan non-blocking terhadap thread UI/CLI.

### 2.2 Voice Activity Detection & Adaptive Noise Floor (`openbagus/voice/vad.py`)
- **Engine:** Silero VAD (ONNX runtime berbasis CPU/CUDA).
- **Chunk Size:** 512 sampel pada 16.000 Hz (tepat 32,0 milidetik per evaluasi).
- **Dynamic Noise Floor Tracking:**
  Sistem memonitor RMS energi pada setiap frame bukan bicara:
  $$\text{noise\_floor}_{t} = (1 - \alpha) \cdot \text{noise\_floor}_{t-1} + \alpha \cdot \text{RMS}_{t} \quad (\alpha = 0.05)$$
  Nilai threshold VAD diadaptasi secara otomatis terhadap desis kipas laptop atau kebisingan ruangan untuk menghindari pemicuan palsu.
- **Adaptive Hesitation Window:**
  Untuk mencegah terpotongnya ucapan pengguna yang sedang berpikir (hesitasi), batas jeda hening (*silence timeout*) diatur adaptif hingga **1.800 – 2.200 ms** (default target 2.000 ms = 62 frame berturut-turut), jauh lebih toleran dibandingkan threshold lama (700–900 ms).

### 2.3 Anti-Hallucination ASR Engine (`openbagus/voice/asr_engine.py`)
- **Model:** Whisper `large-v3` berjalan pada mode `float16` di atas NVIDIA RTX 3050 Laptop GPU (CUDA).
- **Verifikasi Bukti Akustik Nyata:**
  Audio hanya dikirim ke Whisper jika memenuhi kriteria energi fisik:
  1. $\text{RMS} \ge 0.007$ atau $\text{Peak Amplitude} \ge 0.035$
  2. $\text{Crest Factor} \ge 1.20$ (memastikan audio memiliki variasi dinamis suara manusia, bukan desis konstan stasioner).
- **Suppression Layer untuk Phantom Hallucinations:**
  Jika model ASR menghasilkan transkripsi pada audio berenergi marginal, sistem memeriksa daftar hitam 24 penanda halusinasi YouTube/outro Whisper (seperti: *"Terima kasih"*, *"Terima kasih telah menonton"*, *"Jangan lupa subscribe"*, *"Thank you for watching"*).
  - Jika audio berenergi lemah ($\text{RMS} < 0.010$ dan $\text{Peak} < 0.060$), transkripsi tersebut langsung dibatalkan (*dropped as phantom hallucination*).
  - Jika audio berenergi kuat ($\text{RMS} \ge 0.010$), sistem mengizinkan sebagai ucapan asli pengguna (*genuine courtesy turn*).

### 2.4 Turn Controller & Fast Greeting Handler (`openbagus/voice/turn_controller.py`)
- **Status Siklus Percakapan (*State Machine*):**
  - `IDLE`: Menunggu deteksi suara awal.
  - `LISTENING`: Akumulasi frame ucapan pengguna dalam ring buffer memori.
  - `THINKING`: Proses ASR dan inferensi LLM Harness.
  - `SPEAKING`: Pemutaran respons TTS ke speaker.
  - `INTERRUPTED`: Terjadi interupsi (barge-in), audio speaker seketika dihentikan, state kembali ke `LISTENING`.
- **Fast-Path Greeting:**
  Ucapan salam seperti *"Halo Bagusmax"*, *"Hai Bagus"*, *"Selamat pagi"* langsung ditangani dalam ~180 ms tanpa query database keuangan yang lambat.
- **Honest Introspection Handler:**
  Pertanyaan mengenai karakteristik suara (*"Kenapa suara kamu masih perempuan?"*, *"Bagaimana cara ganti preset suara?"*) dijawab secara jujur dan akurat berdasarkan konfigurasi aktif.

### 2.5 TTS Synthesis & Singleton Engine (`openbagus/voice/tts_engine.py`)
- **Engine:** Piper TTS C++ ONNX Runtime.
- **Model Dasar:** `id_ID-news_tts-medium.onnx` (Sample rate native: 22.050 Hz).
- **Thread-Safe Singleton Caching:**
  Model Piper di-*cache* dalam memori (`_SHARED_PIPER_VOICE`) untuk menghindari overhead inisialisasi C++ ONNX dan alokasi ulang VRAM/RAM pada setiap giliran bicara.

### 2.6 Bagusmax DSP Voice Processor (`openbagus/voice/voice_processor.py`)
Pemrosesan sinyal digital (*Digital Signal Processing*) diaplikasikan secara instan pada array float32 audio hasil sintesis:
1. **Low-Mid Warmth Parametric Filter:** Boost +1.8 dB pada rentang 140–260 Hz menggunakan biquad IIR filter berfase linier tanpa memperpanjang durasi fonem.
2. **High-Frequency De-Esser:** Filter low-pass Butterworth orde-2 dengan frekuensi cutoff 6.500 Hz untuk meredam kekasaran konsonan frikatif digital.
3. **Subtle Robot Companion Resonance:** Refleksi harmonik 14 milidetik dengan rasio campuran (wet mix) 5%, menghasilkan nuansa pendamping robot yang hangat tanpa artefak logam.
4. **Soft Peak Limiter:** Kurva transfer hiperbolik tangensial $\tanh(x)$ dengan ambang 0.95 untuk memastikan headroom audio bebas kliping digital (0 dBFS).

### 2.7 AudioPlayback & WASAPI Dynamic Resampling (`openbagus/voice/audio_playback.py`)
- **Backend:** `sounddevice` dengan Windows Audio Session API (WASAPI) / DirectSound.
- **Pencegahan Error PaErrorCode -9997:**
  Sebelum audio 22.050 Hz dikirim ke stream WASAPI, fungsi `_resample_audio` secara dinamis mendeteksi native rate perangkat output (misal 44.100 Hz atau 48.000 Hz) dan melakukan resampling berfase bersih di RAM.
- **Instant Flush on Barge-In:**
  Ketika barge-in terdeteksi, method `stop()` memanggil `stream.abort()` dan mengosongkan buffer pemutaran dalam tempo < 10 milidetik.

---

## 3. Dataflow & Latensi Pipeline

| Tahap Pipeline | Masukan | Keluaran | Latensi Tipikal | Lokasi Eksekusi |
| :--- | :--- | :--- | :--- | :--- |
| **1. Audio Capture** | Realtek Array (48kHz) | Buffer PCM 16kHz | Real-time (chunk 30ms) | CPU (Ring Buffer) |
| **2. Silero VAD** | 512 sampel @ 16kHz | Speech Prob [0..1] | 1.8 – 2.5 ms | CPU / ONNX |
| **3. Hesitation Guard** | Frame hening (0..62) | Keputusan End-of-Turn | 2.000 ms (adaptif) | Logic Controller |
| **4. Whisper ASR** | Audio Buffer (16kHz) | Teks Transkripsi | 380 – 650 ms | NVIDIA RTX 3050 (FP16) |
| **5. AI Harness** | Teks Permintaan | Kalimat Jawaban | 220 – 480 ms (TTFA) | Local / API Engine |
| **6. Piper TTS** | Kalimat Teks | PCM 22.050 Hz | 45 – 90 ms | CPU (Piper ONNX) |
| **7. Bagusmax DSP** | Float32 (22.05kHz) | Processed Audio | 2.2 – 4.5 ms | CPU (NumPy/SciPy) |
| **8. WASAPI Playback** | Float32 (48kHz) | Suara Speaker | 15 – 35 ms | Windows WASAPI Buffer |

---

## 4. Jaminan Integritas & Zero-Disk Storage

Sistem suara OpenBagus V5.0 menerapkan aturan ketat terhadap privasi dan keausan media penyimpanan (SSD):
1. **Tidak Ada File WAV/MP3 Sementara di Disk:** Seluruh transmisi audio dari mikrofon ke ASR, dan dari TTS ke speaker, disimpan secara eksklusif dalam buffer memori (`numpy.ndarray`, `collections.deque`, atau `io.BytesIO`).
2. **Audit Otomatis Direktori Proyek:** Selama pengujian 20 skenario acceptance test (T01–T20), tidak ada satupun file `.wav` atau file audio sementara yang tertulis di direktori aplikasi.
3. **Manajemen Memori Bersih:** Buffer percakapan yang selesai langsung dilepas ke garbage collector Python setelah giliran bicara selesai.
