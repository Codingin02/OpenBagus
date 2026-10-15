# OPENBAGUS — V5.0 VOICE ROOT CAUSE & ARCHITECTURAL AUDIT
## Diagnosis Kegagalan Audio, Transkripsi Palsu, Karakter Suara, dan Interupsi Real-Time

**Tanggal Audit:** 15 Oktober 2026  
**Penyusun:** Antigravity (Voice Systems & Audio DSP Reliability Engineer)  
**Target Perangkat:** Windows 11, NVIDIA RTX 3050 Laptop GPU (6 GB VRAM), Intel Core i5-13450HX, RAM 12 GB  
**Worktree:** `E:\Projects\OpenBagus-Voice`  
**Branch:** `feat/openbagus-local-voice-live` (HEAD Baseline: `2f41da3`)  
**Status:** COMPREHENSIVE & REPRODUCIBLE

---

## 1. Executive Summary

Pengujian langsung oleh pengguna pada perangkat keras nyata (laptop Windows 11 dengan mikrofon array Realtek dan speaker internal) mengungkapkan 6 kegagalan vokal dan percakapan kritis:

1. **Karakter Suara Terdengar Feminin & Rusak Saat Di-Pitch Shift:** Pengguna mengharapkan suara asisten robot pendamping kesehatan yang lembut, tenang, hangat, dan maskulin/netral-rendah (terinspirasi dari karakter robot kesehatan seperti Baymax dalam film Big Hero 6). Suara saat ini terdengar seperti pembaca berita perempuan, dan ketika diturunkan pitch-nya, terdengar seperti suara perempuan yang diperlambat dan dipaksa rendah secara tidak wajar.
2. **Kemunculan Transkripsi Palsu ("Terima kasih telah menonton"):** Saat pengguna diam atau hanya terdengar desis kipas laptop / hening ruangan, sistem berulang kali memunculkan teks transkripsi *"Terima kasih"*, *"Terima kasih telah menonton"*, atau *"Terima kasih telah menonton!"*, lalu asisten merespons sendiri tanpa adanya ucapan pengguna.
3. **Pemotongan Giliran Bicara Terlalu Cepat (Hesitation Cutting):** Ketika pengguna berhenti sejenak untuk berpikir (misalnya: *"Kalau saham RATU itu... sebentar... untuk timeframe satu hari..."*), sistem langsung menganggap jeda pendek sebagai akhir kalimat dan menyela pengguna sebelum pertanyaan selesai.
4. **Kegagalan Introspeksi Suara & Preset Putus Hubungan:** Ketika pengguna bertanya *"Kenapa suara kamu masih perempuan?"* atau *"Aku tadi sudah mengganti preset ke natural, kenapa belum berubah?"*, agen bahasa berhalusinasi dan menjawab bahwa dirinya tidak memiliki suara atau tidak tahu status suaranya.
5. **Ketidaksempurnaan Interupsi (Barge-In) & Stale Response Leakage:** Saat asisten sedang berbicara, menyela pembicaraan asisten terkadang gagal karena speaker bleed memicu false positive atau sebaliknya audio lama tetap dimainkan setelah pengguna menyela.
6. **Integritas Sample Rate Windows Audio (22.050 Hz vs 44.100 / 48.000 Hz):** Model TTS Piper menghasilkan audio 22.050 Hz sedangkan perangkat output audio Windows (DirectSound/WASAPI) beroperasi pada 44.100 Hz atau 48.000 Hz. Pengiriman audio tanpa penanganan sample rate yang ketat menyebabkan degradasi artikulasi dan distorsi durasi.

---

## 2. Rincian 6 Masalah Pokok, Akar Penyebab Kode & Solusi V5.0

---

### Masalah 1: Karakter Suara Feminin & Resampling Pitch Shift Merusak Artikulasi

#### Gejala Pengguna
Suara terdengar seperti perempuan pembaca berita. Upaya menurunkan nada suara pada versi sebelumnya menghasilkan suara yang berat tidak wajar, artikulasi lambat, dan terdengar seperti rekaman suara perempuan yang diputar lambat (*slow-motion*).

#### Lokasi Kode Penyebab
- `openbagus/voice/voice_processor.py` (Baris 91–99)
- `openbagus/voice/tts_engine.py` (Baris 108–112)
- `%LOCALAPPDATA%\OpenBagus\models\tts\id_ID-news_tts-medium.onnx` & `.json`

#### Mengapa Implementasi Lama Gagal
1. **Model Akustik Dasar Single-Speaker Perempuan:**  
   Model lokal Piper yang terpasang adalah `id_ID-news_tts-medium.onnx`. File konfigurasinya menetapkan `"num_speakers": 1` dan `"dataset": "news_tts"`. Model ini dilatih secara eksklusif menggunakan rekaman pembaca berita perempuan berbahasa Indonesia. Model Piper medium dengan satu speaker tidak memiliki vektor pergantian gender atau multi-speaker ID.
2. **Pitch Shifting Menggunakan Resampling Linear (`np.interp`):**  
   Kode di `voice_processor.py` melakukan pitch shifting dengan rumus:
   ```python
   factor = 2.0 ** (self.params.pitch_shift_semitones / 12.0)
   new_len = int(len(out) / factor)
   out = np.interp(np.linspace(0, len(out), new_len, endpoint=False), np.arange(len(out)), out)
   ```
   Ketika `pitch_shift_semitones = -1.0` atau `-2.0`, nilai `factor < 1.0`, yang membuat `new_len > len(out)`. Ini secara fisik memperpanjang durasi audio dan memperlambat tempo fonem! Teknik resampling sederhana ini **tidak memisahkan pitch dari durasi** (bukan *phase vocoder* atau *PSOLA*), sehingga formant vokal perempuan tetap ada namun terseret lambat seperti kaset pita yang diputar dengan kecepatan rendah.

#### Perubahan yang Diperlukan di V5.0
1. **Hapus Resampling Pitch Shift yang Merusak Durasi:** Hilangkan manipulasi panjang gelombang yang memperlambat tempo bicara.
2. **Implementasikan Profil Akustik Orisinal `BAGUSMAX_GENTLE_ID`:**
   - **Low-Mid Chest Warmth:** Filter shelf parametrik 140 Hz – 260 Hz (+1.5 dB) untuk memberikan bobot resonansi dada tanpa mengubah panjang fonem.
   - **High-Frequency Smoothing (De-Essing):** Roll-off lembut di atas 6.500 Hz untuk menghilangkan desis digital tajam pada konsonan geser (*sibilance*).
   - **Robot Companion Resonance:** Resonansi harmonik sangat halus (subtle comb filter dengan wet mix 4–6%) untuk memberikan nuansa robotik hangat tanpa distorsi logam yang mengganggu.
   - **Soft Limiting:** Kompresi kurva tanh lembut untuk mencegah digital clipping.
3. **Kejujuran Arsitektur & Katalog Model Alternatif:**  
   Sistem secara jujur melaporkan bahwa model dasar lokal adalah Piper `news_tts` (single speaker). Kami menyusun katalog model alternatif (termasuk model suara pria berbahasa Indonesia yang kompatibel) yang siap diunduh bila diizinkan pengguna di masa mendatang tanpa menghabiskan kuota internet saat ini secara diam-diam.

---

### Masalah 2: Kemunculan Transkripsi Palsu ("Terima kasih telah menonton") pada Keheningan

#### Gejala Pengguna
Saat pengguna tidak berbicara atau sedang diam, tiba-tiba muncul teks transkripsi:
- *"Terima kasih."*
- *"Terima kasih telah menonton."*
- *"Terima kasih telah menonton!"*
Lalu sistem merespons sendiri, membuat percakapan terasa rusak dan tidak terpercaya.

#### Lokasi Kode Penyebab
- `openbagus/voice/turn_controller.py` (Baris 263–265, 315–325, 348)
- `openbagus/voice/audio_capture.py` (Baris 251–256)
- `openbagus/voice/asr_engine.py` (Baris 296–342)

#### Mengapa Implementasi Lama Gagal
1. **Polling Frame Mengambil Frame yang Sama Berulang Kali:**  
   `_run_loop` di `turn_controller.py` berjalan setiap 15 ms dan memanggil `capture_stream.get_latest_frame()`. Callback audio hanya memasukkan frame baru setiap 32 ms. Akibatnya, frame yang sama diproses 2–3 kali oleh VAD!
2. **VAD Mengakumulasi Noise Rendah:**  
   Karena polling ganda, ambang batas minimum durasi bicara (`min_speech_chunks = 7`) terpenuhi dalam waktu separuh dari yang seharusnya hanya dari fluktuasi desis kipas angin atau mikrofon.
3. **Penyakit Halusinasi YouTube pada Whisper Decoder:**  
   Ketika audio berenergi rendah atau hening (durasi 400 ms – 1,2 detik) dikirim ke model Whisper multilingual, autoregressive decoder memprediksi token berfrekuensi tinggi dari korpus subtitle video internet Indonesia, yaitu *"Terima kasih telah menonton"*.
4. **Penyaringan Halusinasi Terlalu Sempit:**  
   Daftar `phantom_markers` di `asr_engine.py` lama hanya memuat 7 variasi frasa panjang. Frasa *"Terima kasih."*, *"Terima kasih!"*, *"Terima kasih banyak"*, *"Sampai jumpa"* tidak ada dalam daftar tersebut dan lolos begitu saja ke agen AI tanpa verifikasi energi suara!

#### Perubahan yang Diperlukan di V5.0
1. **Thread-Safe Synchronized Frame Queue:** Mengganti polling `get_latest_frame()` dengan antrean `queue.Queue` di mana setiap frame audio 32 ms diproses tepat satu kali oleh VAD.
2. **Dynamic Noise Floor Calibration & Energy Gating:** Menghitung RMS dasar ambient ruangan secara berkala. Frame di bawah ambang kebisingan tidak dapat memicu status `SPEECH_DETECTED`.
3. **Acoustic Evidence Gate Menyeluruh:** Setiap teks keluaran ASR (bukan hanya yang cocok dengan blacklist) harus divalidasi silang terhadap bukti fisik audio: rasio segmen bicara VAD $\ge 25\%$, durasi nyata $\ge 0.5$ detik, dan SNR $\ge 5.0$ dB.
4. **Keputusan `NO_UTTERANCE`:** Jika bukti audio tidak mencukupi, audio dinyatakan hening (`NO_UTTERANCE`). Tidak ada panggilan ke LLM, tidak ada perubahan memori/konteks, dan asisten tetap diam.

---

### Masalah 3: Pemotongan Giliran Bicara Terlalu Cepat (Hesitation Cutting)

#### Gejala Pengguna
Pengguna yang sedang menyusun kalimat dan berhenti 0,5 – 0,8 detik langsung dipotong oleh OpenBagus.

#### Lokasi Kode Penyebab
- `openbagus/voice/turn_controller.py` (Baris 49–65, 327–342)
- `openbagus/voice/vad.py` (Baris 27–28, 44–46)

#### Mengapa Implementasi Lama Gagal
1. Ambang batas hening default (`base_silence_timeout_ms = 800 ms`) terlalu sempit untuk percakapan alami manusia yang memerlukan jeda berpikir.
2. Deteksi kalimat belum selesai (*incomplete utterance*) diuji secara reaktif setelah jeda mencapai 650 ms dengan memanggil ASR partial di latar belakang, yang menimbulkan latensi komputasi sehingga batas hening keburu terlewati sebelum perpanjangan waktu diterapkan.

#### Perubahan yang Diperlukan di V5.0
1. **Pemisahan 3 Konsep Giliran Bicara:**
   - `SPEECH_PAUSE`: Jeda sejenak untuk berpikir (sistem tetap menunggu).
   - `END_OF_UTTERANCE`: Akhir kalimat definitif (sistem mengambil giliran bicara).
   - `INTERRUPTION`: Interupsi aktif pengguna saat asisten sedang bersuara.
2. **Penyesuaian Ambang Batas Waktu Hening:**
   - Kalimat selesai sempurna: 900 – 1.100 ms.
   - Frasa ragu-ragu / jeda berpikir: 1.800 – 2.200 ms.
3. **Deteksi Leksikal & Sintaksis Ragu-Ragu:** Memperluas kamus kata penghubung bahasa Indonesia (*sebentar, anu, terus, kalau, jadi, maksudnya, kira-kira, untuk, dan, atau*) serta tanda baca elipsis (`...`) atau koma.

---

### Masalah 4: Kegagalan Introspeksi Suara & Preset Putus Hubungan

#### Gejala Pengguna
Pengguna mengganti preset suara (misal `/voice preset natural`), namun ketika bertanya *"Kenapa suaramu masih perempuan?"* atau *"Apakah preset sudah berganti?"*, model menjawab *"Saya adalah AI yang tidak memiliki suara..."*.

#### Lokasi Kode Penyebab
- `openbagus/voice/turn_controller.py` (Baris 598–628)
- `openbagus/ai/harness/orchestrator.py`
- `openbagus/ai/tools/system_tools.py`

#### Mengapa Implementasi Lama Gagal
Pemeriksaan perintah suara di `_handle_voice_preset_commands` hanya mencocokkan string kaku seperti `/voice status`. Pertanyaan natural seperti *"Kenapa suara kamu masih perempuan?"* atau *"Kenapa suara kamu masih tinggi?"* tidak tertangkap, sehingga diteruskan ke LLM. LLM fallback yang tidak memanggil tool status suara menjawab dengan jawaban umum bahwa dirinya tidak memiliki tubuh atau suara.

#### Perubahan yang Diperlukan di V5.0
1. **Penyadap Pertanyaan Introspeksi Suara Nyata:** Menambahkan pencocokan intent pertanyaan identitas vokal dan status suara secara langsung di level controller dan system tool.
2. **Jawaban Faktual Berbasis Status Runtime:** Sistem menjawab secara jujur dan transparan:
   *"Saat ini saya menggunakan model Piper Indonesian (news_tts) dengan preset [Nama Preset]. Model dasar ini memiliki timbre feminin bawaan, namun parameter tempo dan frekuensi telah disesuaikan agar lebih tenang dan hangat."*
3. **Registri Preset Kanonikal Lengkap:** Memastikan preset `NATURAL`, `CALM`, `SOFT`, dan `BAGUSMAX_GENTLE_ID` dapat diubah lewat CLI maupun suara dan langsung memperbarui konfigurasi aktif TTS engine.

---

### Masalah 5: Interupsi (Barge-In) Tidak Konsisten & Stale Response Leakage

#### Gejala Pengguna
Pengguna mencoba menyela asisten saat asisten sedang membaca laporan panjang, namun suara asisten terus berjalan, atau ketika berhenti, sisa kalimat sebelumnya tiba-tiba muncul kembali.

#### Lokasi Kode Penyebab
- `openbagus/voice/audio_playback.py` (Baris 79–85, 169–173)
- `openbagus/voice/turn_controller.py` (Baris 270–308)

#### Mengapa Implementasi Lama Gagal
1. **Deteksi Pantulan Speaker (Speaker Bleed):** Saat speaker laptop menyala kencang, mikrofon internal menangkap suara asisten itu sendiri. Ambang batas energi interupsi statis dapat menyebabkan false barge-in (asisten menginterupsi dirinya sendiri) atau sebaliknya membuat mikrofon tidak peka terhadap suara pengguna.
2. **Generasi Tidak Dibatalkan Total:** Chunk audio yang sudah terlanjur diantrekan di memori tetap dieksekusi oleh thread pemutar audio jika generation ID tidak dinaikkan secara atomik.

#### Perubahan yang Diperlukan di V5.0
1. **Render-Reference Adaptive Gating:** `AudioPlaybackManager` menghitung RMS energi audio yang sedang dikirim ke speaker. Saat asisten bersuara, deteksi interupsi mewajibkan suara mikrofon berada jelas di atas level pantulan speaker dengan probabilitas Silero VAD $\ge 0.75$ selama 2 frame berturut-turut (~64 ms).
2. **Atomik Generation ID Invalidation:** Setiap interupsi langsung menaikkan `_current_generation_id`, memanggil `sd.stop()`, mengosongkan antrean playback, dan memicu event pembatalan pada thread LLM/TTS yang sedang berjalan.

---

### Masalah 6: Integritas Sample Rate Windows Audio (22.050 Hz vs 44.100 / 48.000 Hz)

#### Gejala Pengguna
Audio terdengar tersendat-sendat (*choppy*) atau mengalami distorsi frekuensi pada perangkat tertentu di Windows.

#### Lokasi Kode Penyebab
- `openbagus/voice/audio_playback.py` (Baris 154–161)
- `openbagus/voice/audio_devices.py` (Baris 87–93)

#### Mengapa Implementasi Lama Gagal
Model TTS Piper menghasilkan gelombang audio pada frekuensi 22.050 Hz. Kode langsung memanggil `sd.play(audio, samplerate=22050, device=dev_out)`. Pada Windows DirectSound atau WASAPI, jika driver perangkat keras mewajibkan 48.000 Hz atau 44.100 Hz dalam mode eksklusif/shared tanpa konversi yang mulus, PortAudio melakukan resampling berkualitas rendah atau mengalami *underflow buffer*.

#### Perubahan yang Diperlukan di V5.0
1. **Pre-Playback Resampling Otomatis:** Deteksi frekuensi bawaan perangkat output Windows aktif. Jika perangkat beroperasi pada 44.100 Hz atau 48.000 Hz, konversikan audio 22.050 Hz menggunakan interpolasi band-limited berkualitas tinggi sebelum diteruskan ke buffer `sounddevice`.
2. **Manajemen Perangkat Dinamis:** Jangan mengunci indeks perangkat statis; cari default device Windows secara dinamis berdasarkan nama dan Host API (WASAPI/DirectSound).

---

## 3. Matriks Rencana Pengujian & Verifikasi

| Komponen | Status Sebelum V5.0 | Target V5.0 | Kriteria Keberhasilan |
|---|---|---|---|
| **Transkripsi Hening (T01–T02)** | Muncul "Terima kasih telah menonton" | Hening total (`NO_UTTERANCE`) | 0 teks palsu selama 60 detik & 5 menit hening |
| **Penyaringan Halusinasi (T04)** | Whisper memuntahkan teks pada noise | Ditolak oleh Acoustic Evidence Gate | Logprob & SNR gating menolak noise acak |
| **Frasa Asli (T05)** | Ragu ditolak atau diterima | Diterima jika didukung suara riil | Ucapan manusia nyata tetap ditranskripsi |
| **Jeda Berpikir (T06)** | Terpotong dalam < 800 ms | Menunggu 1.800–2.200 ms | Pengguna dapat berhenti 1,5 detik tanpa disela |
| **Identitas Suara (T08–T10)** | Feminin / pembaca berita terseret | `BAGUSMAX_GENTLE_ID` (hangat, tenang, ramah) | Artikulasi jelas, tempo stabil, tanpa resampling semitone |
| **Introspeksi Suara (T11)** | Halusinasi "Saya tidak punya suara" | Jawaban faktual konfigurasi TTS nyata | Menjelaskan status model dan preset dengan benar |
| **Barge-In (T12–T14)** | Terkadang delay atau memutar audio sisa | Interupsi instan (< 250 ms), stop audio | Playback langsung hening dan berganti topik |
| **Integrasi Finansial (T18)** | Suara mengubah angka atau bypass harness | Angka terucap alami, multi-tool V4.4 terjaga | "Rp3.620" diucapkan "Tiga ribu enam ratus dua puluh rupiah" |

---

Dokumen ini menjadi acuan spesifikasi dan implementasi perbaikan kode pada subsistem `openbagus/voice/`.
