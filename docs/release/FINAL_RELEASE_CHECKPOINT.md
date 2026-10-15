# Windows Local Trial Checkpoint

Status: **PARTIAL / REVIEW_REQUIRED**. Paket teks dapat dicoba; mandatory BUG 03 Voice masih FAIL. Tidak production-ready dan tidak digabungkan ke main.

## Aplikasi

- Installer: `E:\Projects\OpenBagus\release\OpenBagus-Setup.exe`.
- Ukuran: 1.105.374.609 byte (sekitar 1,03 GiB).
- SHA-256: `d8cb55e72f1244b60f50117e909a46ebda4be99c594ea0ed6b413676b65fdd9c`.
- Installed EXE: `E:\Projects\OpenBagus\_installed\OpenBagus\OpenBagus.exe`.
- EXE SHA-256: `4c56311fb1095ed21f9954ef17b0c331c33d9a157bc986279bc93ab079dd7325`.
- Models external: `E:\Projects\OpenBagus\models`; tidak disalin ke installer.
- Source: `E:\Projects\OpenBagus-ChatTest`, branch `test/openbagus-chat-acceptance`.
- Build berbasis parent `3abaf825a6b98b750736ff38e7ba173d575716d4` dengan perubahan source; commit checkpoint hasil pengujian dicatat di Git dan `release_manifest.json`.

Installer unsigned, untuk trial lokal pada mesin ini. Jangan menonaktifkan security Windows. Python/venv developer bukan dependency EXE terpasang.

## Acceptance

Laporan lengkap lokal: `reports/runtime/release/acceptance_matrix.json`.

| Bukti | Hasil |
| --- | --- |
| Regresi source terarah | 38 PASS_UNIT dalam 1,614 detik; bukan full repository suite |
| EXE online | 23 skenario, 0 FAIL |
| EXE offline/proxy terisolasi | 4 skenario, 0 FAIL |
| Gate dari 64 requirement | 49 PASS_INSTALLED_APP, 5 PASS_INTEGRATION, 1 PASS_REAL_HARDWARE, 1 FAIL, 8 NOT_TESTED |
| Hardware Voice | Microphone terbuka; silence hallucination dikonfirmasi pengguna |

Test installed-app menggunakan model dan tool sebenarnya, bukan mock. Status PASS_INSTALLED_APP pada financial bukan jaminan kebenaran seluruh provider atau fresh primary filing. Rincian sumber dan batas data ada di `FINANCIAL_SOURCE_ACCEPTANCE.md`.

## Fitur

- Chat natural tanpa `/chat`, konteks RATU -> BBCA, perbandingan dan koreksi: teruji.
- FAST: `qwen3.5:2b-q4_K_M`, provider lokal aktual, teruji.
- DEEP: `qwen3.5:4b`, teruji dengan recovery transparan bila thinking habis; bukan bukti lebih akurat daripada FAST.
- English Tutor: grammar correction dan namespace lintas mode teruji.
- Financial/crypto: tool berjalan dengan provenance, delayed status dan DATA_GAP; provider internet dapat gagal dan primary filing belum seluruhnya diverifikasi ulang.
- Voice: **FAIL**, default OFF. Dua transkripsi palsu pada ruangan tenang; audible output, echo, pause dan barge-in belum diterima pengguna.
- Companion 3D: INACTIVE; tidak menghalangi chat. Semua pekerjaan armor tetap dibekukan.

## Pengukuran Terbatas

Shortcut Desktop mencapai READY sekitar 15,9 detik; Start Menu sekitar 17,8 detik. Probe load/inference model FAST di dalam startup sekitar 5,3-5,5 detik. Respons tutor DEEP terakhir sekitar 77,1 detik termasuk recovery.
Snapshot API provider menunjukkan satu model resident per snapshot. Nilai model residency sekitar 1,56 GB FAST dan 3,07 GB DEEP pada putaran sebelumnya bukan peak VRAM keseluruhan. Tidak ada klaim FPS, stress stability, peak RAM, atau kualitas suara.

## Batas Yang Belum Ditutup

BUG 03 dan D04 tetap FAIL; D03/D05-D10/D12 NOT_TESTED secara akustik. Mute belum membatalkan ASR yang terlanjur berjalan; `/voice off` menghentikan sesi. Diagnosis VAD source 12 detik tidak mereproduksi false onset dan tidak meniadakan kegagalan EXE.
Windows restart, uninstall aktual, drive alternatif, long-session stress dan semua command legacy belum diuji ulang. DEEP dapat lambat dan memerlukan retry tanpa thinking pada model yang sama.

## Integritas Dan Penggunaan

Main `77188cc`, Voice `218a377` dan 3D `95d16dc` tidak dipindah/di-merge. Source main dan Voice bersih; kelompok untracked 3D tetap ada. Tidak ada modifikasi model 3D, Voice worktree, Data worktree, atau renderer. Local checkpoint hanya pada branch acceptance; tidak ada push.
Model hashes dan repair/data checks tersimpan lokal. Riwayat lama tidak dihapus; penggunaan shortcut dapat memperbarui metadata sesi yang memang sudah opt-in. Binary, user profiles, rekaman, keys dan logs pribadi tidak dimasukkan ke Git.

Buka installer dengan klik dua kali, selesaikan wizard, lalu gunakan teks pada jendela OpenBagus. Instalasi sudah ada, sehingga shortcut OpenBagus juga langsung dapat digunakan. Voice tetap percobaan opsional, bukan fitur yang sudah dinyatakan lulus. Setelah trial ini, tunggu evaluasi pengguna sebelum pekerjaan lanjutan.

Dokumen terkait: `SETUP_INSTALLATION_ACCEPTANCE.md`, `FINAL_BUG_RECOVERY.md`, `CHAT_AND_CONTEXT_ACCEPTANCE.md`, `VOICE_HARDWARE_ACCEPTANCE.md`, `FINANCIAL_SOURCE_ACCEPTANCE.md`.
