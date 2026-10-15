# OPENBAGUS — V5.0 VOICE PRESET SPECIFICATION & COMPARISON MATRIX
## Panduan Profil Vokal, Parameter DSP, dan Karakteristik Akustik Bagusmax

**Dokumen:** V5_0_PRESET_COMPARISON.md  
**Tanggal:** 15 Oktober 2026  
**Sistem:** OpenBagus V5.0 Local Voice Live  
**Penulis:** Antigravity (Voice Systems & Audio DSP Reliability Engineer)  
**File Konfigurasi Utama:** `config/voices/bagusmax_calm_id.json`  

---

## 1. Ringkasan Eksekutif Profil Suara

OpenBagus V5.0 menyediakan 4 preset vokal yang telah dikalibrasi secara akustik untuk model TTS lokal Piper Bahasa Indonesia (`id_ID-news_tts-medium.onnx`). 

Semua preset V5.0 menerapkan prinsip **Zero Length-Distortion**: tidak ada manipulasi pitch shift berbasis resampling linier (`np.interp`) yang merusak durasi fonem atau menyebabkan suara terdengar berat dan terseret lambat (*slow-motion*). Karakter suara dibentuk melalui kombinasi tempo sintesis natural (`length_scale`), reduksi variabilitas fonem kasar (`noise_scale`), penguatan harmonik dada (*chest warmth EQ*), peredam desis konsonan geser (*de-essing*), dan resonansi robot pendamping (*subtle companion resonance*).

---

## 2. Matriks Perbandingan Parameter DSP & Sintesis

| Parameter Akustik | `BAGUSMAX_GENTLE_ID` *(Canonical / Default)* | `NATURAL` *(Baseline)* | `BAGUSMAX_CALM` *(Pengukuran Teliti)* | `BAGUSMAX_SOFT` *(Karakter Lembut)* |
| :--- | :--- | :--- | :--- | :--- |
| **Deskripsi Utama** | Pendamping robot kesehatan yang tenang, hangat, hangat di frekuensi dada, de-essed, dan resonansi halus. | Output asli model berita, kecepatan standar, tanpa pemrosesan DSP. | Penyampaian terukur dan tenang, cocok untuk pembacaan angka keuangan panjang. | Vokal lembut, artikulasi bulat, nuansa pendamping sangat menenangkan. |
| **Length Scale (Tempo)** | `1.06` (sedikit lebih santai dari berita) | `1.00` (tempo berita asli) | `1.08` (santai dan terukur) | `1.10` (lambat dan sangat ramah) |
| **Noise Scale (Variasi)** | `0.52` (konsisten dan stabil) | `0.667` (default Piper) | `0.55` (stabil) | `0.50` (sangat stabil) |
| **Noise W (Panjang Fonem)**| `0.70` | `0.80` (default Piper) | `0.70` | `0.70` |
| **Pitch Shift Semitones** | `0.0` (tanpa distorsi panjang) | `0.0` | `0.0` | `0.0` |
| **Warmth Gain (140-260 Hz)**| `+1.8 dB` | `0.0 dB` (mati) | `+1.2 dB` | `+1.5 dB` |
| **De-Essing (>6.5 kHz)** | `Aktif (Butterworth orde-2)` | `Tidak aktif` | `Aktif (Butterworth orde-2)` | `Aktif (Butterworth orde-2)` |
| **Robot Resonance Mix** | `5%` (delay 14 ms) | `0%` (mati) | `0%` (mati) | `3%` (delay 14 ms) |
| **Peak Limiter ($\tanh$)** | `Aktif` (ambang 0.95) | `Tidak aktif` | `Aktif` (ambang 0.95) | `Aktif` (ambang 0.95) |
| **Target Volume Scale** | `1.00` | `1.00` | `1.00` | `0.95` |

---

## 3. Detail Analisis Setiap Preset

### 3.1 `BAGUSMAX_GENTLE_ID` (Canonical Default)
- **Tujuan:** Profil standar OpenBagus V5.0 yang merefleksikan karakter robot pendamping medis / kesehatan yang tenang dan bersahabat (terinspirasi dari karakter robot kesehatan seperti Baymax dalam film Big Hero 6).
- **Karakteristik Akustik:**
  - Desis sibilan pada konsonan *s*, *c*, *sy* diredam lembut sehingga tidak menusuk di telinga saat didengarkan melalui earphone atau speaker laptop.
  - Frekuensi 140–260 Hz diberi boost +1.8 dB untuk mengkompensasi tipisnya resonansi speaker laptop Windows, menciptakan ilusi suara yang lebih berbobot tanpa mengubah pitch vokal fundamental.
  - Resonansi robotik mikro (5% wet mix pada jeda 14 milidetik) menyatukan vokal sintetis menjadi karakter robot yang simpatik tanpa terdengar seperti robot kaleng lawas.
- **Cocok Untuk:** Percakapan harian, konsultasi keuangan interaktif, dialog santai, dan penggunaan umum.

### 3.2 `NATURAL`
- **Tujuan:** Opsi bypass tanpa filter bagi pengguna yang menginginkan artikulasi pembaca berita murni tanpa pemrosesan frekuensi atau penyesuaian tempo.
- **Karakteristik Akustik:**
  - Kecepatan pemutaran 1.00x standar model `news_tts`.
  - Tidak ada EQ, tidak ada de-essing, tidak ada resonansi.
- **Cocok Untuk:** Diagnostik pengujian kemurnian model dasar Piper dan perbandingan A/B terhadap preset olahan DSP.

### 3.3 `BAGUSMAX_CALM`
- **Tujuan:** Menghadirkan suasana pembicaraan yang sangat tenang, formal, dan analitis.
- **Karakteristik Akustik:**
  - Tempo sedikit diperlambat (`length_scale = 1.08`) agar pemaparan data keuangan (seperti laba bersih, rasio utang, dividen) mudah diserap oleh telinga pendengar.
  - Mematikan resonansi robotik (`robot_resonance_mix = 0%`), hanya mempertahankan penambahan bobot vokal (+1.2 dB) dan de-essing lembut.
- **Cocok Untuk:** Ringkasan laporan keuangan kuartalan, analisis neraca emiten, dan pengarahan risiko investasi.

### 3.4 `BAGUSMAX_SOFT`
- **Tujuan:** Menghadirkan karakter suara yang sangat lembut, santun, dan menenangkan.
- **Karakteristik Akustik:**
  - Tempo bicara paling rileks (`length_scale = 1.10`) dengan reduksi volume puncak ke `0.95`.
  - Resonansi robotik dipasang pada level subtil (3%), memberikan kehangatan intim yang tidak melelahkan telinga pada sesi percakapan malam hari.
- **Cocok Untuk:** Sesi refleksi portofolio, obrolan santai di ruangan hening, dan sesi edukasi pemula.

---

## 4. Cara Mengganti Preset Suara

### 4.1 Melalui Perintah CLI Langsung
```powershell
# Melihat daftar dan preset aktif
python openbagus/cli.py voice preset

# Mengganti ke preset Bagusmax Gentle ID (default)
python openbagus/cli.py voice preset BAGUSMAX_GENTLE_ID

# Mengganti ke preset Natural
python openbagus/cli.py voice preset NATURAL

# Mengganti ke preset Bagusmax Calm
python openbagus/cli.py voice preset BAGUSMAX_CALM

# Mengganti ke preset Bagusmax Soft
python openbagus/cli.py voice preset BAGUSMAX_SOFT
```

### 4.2 Melalui Interactive Shell OpenBagus
Saat berada di dalam sesi shell (`python openbagus/cli.py shell`):
```text
openbagus> /voice preset BAGUSMAX_CALM
Voice preset switched to BAGUSMAX_CALM (Measured calm delivery, reduced noise variability, subtle high-frequency smoothing)

openbagus> /voice test Halo, saya Bagusmax. Ini adalah pengujian preset suara calm.
Testing TTS playback with preset BAGUSMAX_CALM...
```

### 4.3 Melalui Percakapan Suara Alami (Conversational Tool Call)
Pengguna cukup berbicara langsung ke mikrofon:
> *"Bagusmax, tolong ubah preset suara kamu ke mode calm."*  
> *"Ganti suara kamu ke natural dong."*

Model LLM Harness akan memanggil tool internal `set_voice_preset(preset_name="BAGUSMAX_CALM")`, mengonfirmasi perubahan, dan giliran bicara berikutnya akan otomatis disintesis menggunakan parameter preset yang dipilih.
