# Voice Hardware Acceptance

Status: **FAIL / REVIEW_REQUIRED**. Voice tidak aktif pada startup dan belum layak dinyatakan andal. Chat teks tetap dapat digunakan.

## Bukti Hardware

Sesi EXE terpasang berhasil membuka `Microphone (Realtek USB2.0 Audi...)` dan mendeteksi `Headphones (Realtek USB2.0 Audi...)`. ASR memakai faster-whisper lokal CPU int8 agar tidak berbagi VRAM terbatas dengan LLM. Deteksi speaker bukan bukti bahwa pengguna mendengar jawaban.

Saat pengguna menyatakan tidak berbicara dan ruangan tenang, EXE menampilkan:

- `Sampai jumpa di video selanjutnya.`
- `Terima kasih telah menonton.`

Keduanya transkripsi palsu yang dikonfirmasi pengguna. Gate D04 dan BUG 03 tetap FAIL. Jawaban asisten setelahnya bukan percakapan manusia yang valid.

Mute menghentikan capture baru, tetapi ASR yang sudah berjalan masih menghasilkan transkripsi. `/voice off` digunakan untuk menghentikan sesi. Jangan menganggap mute membatalkan turn yang sudah masuk ASR.

## Diagnosis Terbatas

Pengukuran terpisah memakai microphone dan implementasi capture/VAD source yang sama selama 375 frame (12 detik), tanpa ASR/TTS: 0 active frame, 0 endpoint. RMS median 0,001440; RMS maksimum frame 0,010380; skor VAD maksimum 0,217606 (threshold onset 0,55).
Laporan lokal: `reports/runtime/release/quiet_mic_diagnostic.json`. Ini tidak mereproduksi kegagalan EXE dan bukan alasan mengubah D04 menjadi PASS.

Energi dan confidence decoder yang dipakai sekarang belum cukup menolak seluruh noise. Penyebab spesifik onset/transkripsi palsu pada sesi yang gagal belum dapat ditetapkan karena audio tidak disimpan. Jangan menyebutnya semata-mata suara video/TV atau menyelesaikannya dengan blacklist kalimat.

## Gate

| Gate | Status | Batas bukti |
| --- | --- | --- |
| D01 | PASS_REAL_HARDWARE | Stream microphone benar-benar terbuka |
| D02 | PASS_INSTALLED_APP | Output device terdeteksi; audible output belum disetujui |
| D03 | NOT_TESTED | Belum ada transkripsi kalimat uji yang dikonfirmasi pengguna |
| D04 | FAIL | Dua kalimat yang tidak diucapkan; ruangan tenang dikonfirmasi |
| D05-D09 | NOT_TESTED | Pause, echo, audible answer dan interruption belum terverifikasi akustik |
| D10 | NOT_TESTED | Unit/config tersedia; perubahan suara nyata belum diuji |
| D11 | PASS_INSTALLED_APP | Tidak ditemukan file audio di profile sesi; pemrosesan audio di RAM |
| D12 | NOT_TESTED | Microphone belum dicabut dalam uji EXE |

Angka GPU `0/0` pada banner Voice adalah telemetry tidak tersedia, bukan ukuran fisik GPU atau bukti CPU-only LLM. FAST/DEEP diperiksa melalui provider aktual secara terpisah.

Latency dari sesi yang gagal: ASR 10.533 ms, time-to-first-audio 240,7 ms, end-to-end 12.315,7 ms. Angka ini bukan benchmark percakapan benar dan bukan bukti kualitas suara.

## Pemakaian Trial

Mulai dengan teks. `/voice on` hanya untuk percobaan yang disengaja; `/voice off` menghentikan sesi. Mikrofon telah ditutup setelah diagnosis. Tidak ada audio mentah yang disimpan atau ditambahkan ke Git. Perbaikan berikutnya memerlukan reproduksi terukur dengan ucapan asli dan quiet interval pada EXE, termasuk cancellation mute, echo dan barge-in; belum ada persetujuan kualitas suara.
