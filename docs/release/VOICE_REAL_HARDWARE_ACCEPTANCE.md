# Voice Real Hardware Acceptance Matrix & Pipeline Verification Report

**Canonical Repository:** `E:\Projects\OpenBagus`  
**Target Environment:** Windows 11 x64, Intel Core i5-13450HX, NVIDIA RTX 3050 Laptop GPU (6 GB VRAM)  
**Audio Hardware Devices:** `Microphone Array (Realtek(R) Audio) [Windows WASAPI ID 9]` & `Speakers (Realtek(R) Audio) [Windows WASAPI ID 8]`  
**Status:** **SIMULATED & UNIT PASS / HARDWARE ENUMERATED / USER ACCEPTANCE PENDING**  

---

## 1. Acceptance Evidence Taxonomy

To prevent conflation between synthetic algorithmic simulations and physical human evaluation, evidence across the OpenBagus voice subsystem is classified into strict categories:

- **`PASS_SIMULATED`**: Algorithmic pipeline verification using synthetic waveforms, mathematical matrices, or mocked components. Does not constitute physical hardware or human acoustic proof.
- **`PASS_REAL_MICROPHONE`**: Stream successfully opened, frames captured, and buffer managed on physical microphone hardware (Realtek WASAPI input device 9).
- **`PASS_REAL_SPEAKER`**: Stream successfully opened and audio rendered through physical speakers/headphones (Realtek WASAPI output device 8).
- **`PASS_INSTALLED_EXE`**: Verification executed directly against the compiled standalone Windows binaries (`dist\OpenBagus\OpenBagus.exe` / `_installed\OpenBagus\OpenBagus.exe`).
- **`USER_APPROVED`**: Human auditory satisfaction and live voice conversation confirmed by the user.
- **`FAIL`**: Defect confirmed and unresolved.
- **`NOT_TESTED`**: Not yet executed on physical hardware or by human user.

---

## 2. Reconciled Voice Acceptance Gates (D01–D12)

| Gate | Scenario | Status | Evidence Category | Real Hardware / Simulation Verification Detail |
|---|---|---|---|---|
| **D01** | Microphone Stream Open | **PASS_REAL_MICROPHONE** | Physical Hardware | `AudioCaptureStream` opened WASAPI stream on physical Realtek device 9; non-blocking capture confirmed with `RLock`. |
| **D02** | Output Device Detection | **PASS_INSTALLED_APP** | Installed Binary | `AudioPlaybackManager` queries native WASAPI device 8 (Speakers Realtek Audio, 48kHz, 2ch). |
| **D03** | Indonesian Test Sentence Transcription | **NOT_TESTED** | Live Human Mic | Automated pipeline tested with synthetic formant in V04; live human speech transcription awaiting user execution in Scenario B. |
| **D04** | Quiet Room Silence Immunity (P0 Bug) | **PASS_SIMULATED** / **NOT_TESTED** (5m Live) | Simulation / Live Mic | Silence Invariant gates 1875 synthetic frames (V01) and 9375 frames (V02) with 0 false transcripts. Physical 5-minute quiet room awaiting Scenario A. |
| **D05** | Natural Pause Continuation | **PASS_SIMULATED** / **NOT_TESTED** (Live) | Simulation / Live Mic | 700ms silence does not trigger premature endpoint in V06. Real human hesitation pause awaiting Scenario C. |
| **D06** | Speaker Echo Rejection | **PASS_SIMULATED** / **NOT_TESTED** (Live) | Simulation / Live Spk | Render-reference coupling threshold math verified in V07. Physical room speaker bleed awaiting Scenario D. |
| **D07** | Audible Response & Voice Demeanor | **NOT_TESTED** | Human Auditory | Local Piper TTS generates natural wav; aesthetic evaluation of tone and warmth reserved for user in Scenario B/D. |
| **D08** | Real Full-Duplex Barge-In | **PASS_SIMULATED** / **NOT_TESTED** (Live) | Simulation / Live Mic | Strong near-end speech condition and cancellation token trigger verified in V08. Physical speaker abort awaiting Scenario E. |
| **D09** | Repeated Rapid Interruption | **PASS_SIMULATED** | Simulation | 3 successive cancellation tokens processed without deadlock or state leakage in V09. |
| **D10** | Voice Preset Switching | **PASS_SIMULATED** | Simulation | Dynamic switching between `BAGUSMAX_GENTLE_ID` and `BAGUSMAX_CALM_ID` verified in V11. |
| **D11** | Zero-Disk Audio Privacy | **PASS_INSTALLED_EXE** | Installed Binary | `PrivacyGuard.verify_zero_persistent_audio()`: 0 violations, 0 persistent audio files found. |
| **D12** | Microphone Disconnect / Reconnect | **PASS_REAL_MICROPHONE** | Physical Hardware | Buffer clear and stream restart handle cleanly without unhandled exception or lock inversion. |

---

## 3. Automated V-Series Test Suite Status (V01–V14)

All 14 tests in `tests/test_voice_p0_acceptance.py` pass with strict simulation and unit boundaries:

| Test ID | Test Name | Classified Status | Description & Actual Evidence |
|---|---|---|---|
| **V01** | `test_v01_quiet_room_60_seconds` | **PASS_SIMULATED** | 1,875 synthetic frames (RMS 0.0018) -> 0 active frames, 0 endpoints, 0 ASR invocations. |
| **V02** | `test_v02_quiet_room_extended` | **PASS_SIMULATED** | 9,375 synthetic frames with transient clicks -> 0 speech onsets, 0 phantom turns. |
| **V03** | `test_v03_fan_noise_environment` | **PASS_SIMULATED** | 120Hz fan hum + white noise -> Gated by adaptive floor; ASR yields empty string. |
| **V04** | `test_v04_simulated_speech_acoustic_pipeline` | **PASS_SIMULATED** | Synthetic harmonic formant signal (f0=180Hz) verifies acoustic validation pipeline; does NOT evaluate human transcription. |
| **V05** | `test_v05_genuine_outro_phrase` | **PASS_SIMULATED** | Low-evidence outro rejected (`INSUFFICIENT_VAD_SPEECH`); High-evidence vocal outro accepted. |
| **V06** | `test_v06_pause_continuation` | **PASS_SIMULATED** | 700ms hesitation pause does not trigger endpointing (timeout is 1300ms). |
| **V07** | `test_v07_echo_only` | **PASS_SIMULATED** | Render RMS (0.025) enforces coupling threshold (0.0255); bleed frame (0.010) rejected. |
| **V08** | `test_v08_genuine_interruption` | **PASS_SIMULATED** | Near-end speech condition (RMS 0.045, prob 0.90) triggers interruption coordinator in simulation. |
| **V09** | `test_v09_repeated_interruption` | **PASS_SIMULATED** | 3 successive interruptions complete cleanly with unique turn tokens; zero deadlock. |
| **V10** | `test_v10_microphone_reconnect` | **PASS_REAL_MICROPHONE** / **PASS_SIMULATED** | Physical stream opening and buffer clearing verified without lockup. |
| **V11** | `test_v11_preset_switching` | **PASS_SIMULATED** | `LocalTTSEngine` updates `BAGUSMAX_GENTLE_ID` <-> `BAGUSMAX_CALM_ID` dynamically. |
| **V12** | `test_v12_audio_privacy` | **PASS_INSTALLED_EXE** | `PrivacyGuard.verify_zero_persistent_audio()`: 0 violations, 0 persisted audio files. |
| **V13** | `test_v13_financial_speech_context_switch` | **PASS_SIMULATED** | Entity context switches cleanly without residual data bleeding. |
| **V14** | `test_v14_english_tutor_speech` | **PASS_SIMULATED** | `ENGLISH_TUTOR` namespace isolates conversation from financial ticker memory. |

---

## 4. End-to-End Human Acceptance Scenarios (Ready for User Execution)

The user can execute the following real-world scenarios on the installed application:

```powershell
# Jalankan aplikasi terpasang
E:\Projects\OpenBagus\_installed\OpenBagus\OpenBagus.exe
```

Di dalam OpenBagus shell:
```text
/voice start
```

### Scenario A — Quiet Room (5 Menit)
- **Aksi Pengguna:** Aktifkan sesi suara (`/voice start`), lalu diamkan mikrofon selama 5 menit di ruangan tenang.
- **Kriteria Keberhasilan:** Zero false transcript, tidak ada panggilan LLM, dan tidak ada respons suara asisten. Status: **NOT_TESTED** (Menunggu sesi pengguna).

### Scenario B — Indonesian Natural Conversation
- **Aksi Pengguna:** Ucapkan 3 kalimat Indonesia yang berbeda (misal: *"Halo Bagus, apa kabar?"*, *"Bagaimana kondisi ekonomi saat ini?"*, *"Terima kasih banyak atas bantuannya"*).
- **Kriteria Keberhasilan:** Transkripsi teks sesuai kata-kata yang diucapkan pengguna, asisten menjawab secara relevan dengan suara tenang. Status: **NOT_TESTED** (Menunggu sesi pengguna).

### Scenario C — Natural Pause
- **Aksi Pengguna:** Ucapkan kalimat, berhenti sejenak (~1 detik untuk berpikir), lalu lanjutkan kalimat. (Misal: *"Tolong berikan rekomendasi saham..." [jeda 1s] "...sektor perbankan untuk investasi jangka panjang"*).
- **Kriteria Keberhasilan:** Kalimat tidak dipotong menjadi dua respons berbeda; asisten menunggu jeda dan merespons kalimat lengkap. Status: **NOT_TESTED** (Menunggu sesi pengguna).

### Scenario D — Speaker Echo
- **Aksi Pengguna:** Biarkan OpenBagus berbicara melalui speaker laptop sementara pengguna diam.
- **Kriteria Keberhasilan:** Sistem tidak menangkap suaranya sendiri dari speaker laptop sebagai ucapan pengguna; tidak terjadi self-conversation loop. Status: **NOT_TESTED** (Menunggu sesi pengguna).

### Scenario E — Barge-In (Interupsi Nyata)
- **Aksi Pengguna:** Saat OpenBagus sedang berbicara, potong dengan berbicara tegas: *"Bagus, stop dulu."* atau *"Ganti topik, jelaskan BBCA saja."*
- **Kriteria Keberhasilan:** Output speaker langsung berhenti seketika (< 150 ms), sistem mendengarkan ujaran baru pengguna, dan topik beralih. Status: **NOT_TESTED** (Menunggu sesi pengguna).

### Scenario F — Financial Voice Context
- **Aksi Pengguna:** Tanyakan analisis RATU, kemudian lanjutkan dengan beralih ke BBCA: *"Sekarang bagaimana dengan BBCA?"*
- **Kriteria Keberhasilan:** Konteks ticker aktif berganti ke BBCA, tool-call parameter merujuk BBCA, dan data RATU tidak mencemari jawaban BBCA. Status: **NOT_TESTED** (Menunggu sesi pengguna).

### Scenario G — English Tutor Mode
- **Aksi Pengguna:** Alihkan ke English Tutor (`/voice mode deep` atau ucapkan *"Let's practice English"*), ajukan pertanyaan bahasa Inggris.
- **Kriteria Keberhasilan:** Asisten merespons dalam bahasa Inggris, memberikan koreksi grammar yang akurat, dan tidak memunculkan data pasar finansial yang tidak relevan. Status: **NOT_TESTED** (Menunggu sesi pengguna).
