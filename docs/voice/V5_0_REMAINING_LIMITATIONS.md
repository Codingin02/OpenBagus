# OPENBAGUS — V5.0 ARCHITECTURAL BOUNDARIES & REMAINING LIMITATIONS
## Analisis Batasan Teknis Jujur, Keterbatasan Dataset Akustik Dasar, dan Rencana Pengembangan

**Dokumen:** V5_0_REMAINING_LIMITATIONS.md  
**Tanggal:** 15 Oktober 2026  
**Sistem:** OpenBagus V5.0 Local Voice Live  
**Penulis:** Antigravity (Voice Systems & Audio DSP Reliability Engineer)  
**Status Klasifikasi Profil:** `USER_LISTENING_APPROVAL_PENDING`  

---

## 1. Prinsip Kejujuran Teknis OpenBagus

OpenBagus berpegang pada prinsip kejujuran mutlak terhadap kapabilitas sistem. Kami menolak menyamarkan keterbatasan mendasar dengan klaim "100% sempurna" tanpa bukti fisik yang dapat didengarkan langsung oleh pengguna.

Dokumen ini memaparkan batasan fisik dan arsitektur yang tetap ada pada OpenBagus V5.0 setelah seluruh perbaikan rekayasa diselesaikan.

---

## 2. Keterbatasan Model Dasar Vokal Lokal (Base TTS Dataset)

### 2.1 Fakta Dataset Piper yang Tersedia di Perangkat
- File model vokal lokal yang terpasang pada komputer pengguna saat ini adalah:
  `%LOCALAPPDATA%\OpenBagus\models\tts\id_ID-news_tts-medium.onnx`
- Metadata konfigurasi model (`id_ID-news_tts-medium.onnx.json`):
  ```json
  {
    "dataset": "news_tts",
    "num_speakers": 1,
    "sample_rate": 22050
  }
  ```
- **Fakta Teknis:** Model ini dilatih secara tunggal (*single-speaker*) menggunakan suara pembaca berita perempuan berbahasa Indonesia. Model ONNX ini **tidak memiliki multi-speaker embedding vector** dan tidak memiliki opsi tombol internal untuk beralih menjadi pembicara pria tulen secara native.

### 2.2 Batasan Pemrosesan DSP di V5.0
- **Apa yang Berhasil Diperbaiki di V5.0:**
  1. Menghilangkan artefak *slow-motion* yang merusak artikulasi kata (dihapusnya manipulasi `np.interp` yang memperlambat tempo).
  2. Menambahkan kehangatan resonansi dada (*chest warmth*) pada rentang frekuensi 140–260 Hz (+1.8 dB).
  3. Meredam desis konsonan geser tajam (*de-essing*) di atas 6.500 Hz.
  4. Menambahkan resonansi robot pendamping kesehatan yang halus (*subtle companion resonance* 5% wet mix).
- **Batasan Fisik yang Tetap Ada:**
  Meskipun suara menjadi lebih berbobot, tenang, ramah, dan bebas distorsi tempo, **frekuensi vokal fundamental (F0) dan kontur formant dasar tetap berakar dari data latih perempuan pembaca berita**.
- **Status Klasifikasi:**
  Profil vokal saat ini diklasifikasikan secara formal sebagai:
  **`USER_LISTENING_APPROVAL_PENDING`**  
  (Keputusan akhir mengenai penerimaan timbre suara ini berada di tangan pengguna setelah mendengarkan langsung output speaker melalui perintah `openbagus voice test`).

---

## 3. Peta Jalan Model Suara Maskulin / Netral Masa Depan

Bila pengguna menghendaki suara pria tulen atau robot bersuara maskulin-rendah murni di masa mendatang (dengan koneksi internet dan kuota yang leluasa), arsitektur modular OpenBagus V5.0 telah siap untuk mengintegrasikan alternatif berikut tanpa merombak turn controller:

1. **Piper TTS Indonesian Male Checkpoint:**
   Mengunduh atau melatih checkpoint Piper ONNX berbasis dataset pembicara pria berbahasa Indonesia (misal: Common Voice ID Male atau dataset audio buku berbahasa Indonesia).
2. **Kokoro TTS (ONNX Runtime):**
   Arsitektur TTS berbobot ringan (~80M parameter) yang memiliki kemampuan multi-voice dan multi-gender dengan latensi inferensi sangat rendah di perangkat lokal.
3. **ChatTTS / CosyVoice:**
   Model generasi vokal percakapan modern dengan kontrol nada bicara, tawa, dan intonasi emosional tingkat lanjut (memerlukan alokasi VRAM GPU ~3 GB).

---

## 4. Batasan Akustik Lingkungan & Mikrofon

1. **Kebisingan Ekstrem (> 75 dBA):**
   Mekanisme *dynamic noise floor tracking* pada V5.0 sangat efektif menolak desis kipas laptop dan hening ruangan ber-AC. Namun, pada kondisi ruangan dengan suara televisi keras atau orang lain berteriak di dekat laptop, ambang energi VAD mungkin tertrigger. Untuk lingkungan sangat berisik, disarankan menggunakan headset atau mikrofon dekat bibir (*close-proximity mic*).
2. **Singkatan & Dialek Daerah:**
   Normalizer teks keuangan telah menangani seluruh format mata uang (Rupiah), ticker saham (BBCA, TLKM, RATU), persentase, dan angka desimal. Namun istilah bahasa daerah yang sangat spesifik atau singkatan gaul non-standar dapat ditranskripsikan secara fonetik literal oleh Whisper.
