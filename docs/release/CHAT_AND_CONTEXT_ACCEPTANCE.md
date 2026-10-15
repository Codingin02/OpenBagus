# Chat And Context Acceptance

EXE release terpasang diuji melalui stdin/stdout asli, bukan respons model yang dipalsukan. Hasil: 23 skenario online lulus; 35 dari 64 gate dipenuhi oleh putaran online ini. Gate lain tetap memerlukan bukti terpisah.
Bukti lengkap: `reports/runtime/release/windows_acceptance.json`, termasuk input, output, state, tool arguments, provider, model dan waktu.

## Teruji

- Halo dan percakapan biasa tanpa `/chat`; kata biasa tidak berubah menjadi ticker.
- RATU D1, follow-up laporan, perpindahan BBCA, PBV/ROE, perbandingan RATU/BBCA, koreksi ke TLKM dan discovery HGII.
- Argumen tool diperiksa, bukan hanya nama emiten dalam narasi.
- BTCUSDT diarahkan ke asset kripto dan tool harga yang benar.
- Permintaan pergerakan companion tidak mengaku menjalankan aksi yang tidak terjadi.
- English Tutor aktif; `Yesterday I go to school` dikoreksi menjadi `went`.
- FAST -> DEEP mempertahankan namespace tutor. Putaran EXE terakhir selesai sekitar 77,1 detik: thinking mencapai batas token, lalu model 4B yang sama memberi jawaban setelah retry tanpa thinking. Pemberitahuan recovery terlihat dan `/status.model.last_generation` mencatat `THINKING_LIMIT_FINALIZATION`. Putaran sebelumnya selesai sekitar 39,2 detik tanpa recovery; latency tidak dijamin konstan.
- Kembali ke financial RATU serta restart dengan persistence opt-in memulihkan RATU D1, bukan namespace tutor yang sudah ditinggalkan.
- Shutdown normal keluar dengan code 0 dan menutup port provider yang dimiliki aplikasi.

## Batasan

Profil acceptance terisolasi dari riwayat pribadi pengguna. Persistence tetap opt-in melalui `/harness on`.
DEEP pernah gagal pada kandidat sebelumnya; recovery satu kali yang transparan kini tersedia bila thinking mencapai batas token. Satu putaran lulus bukan bukti kualitas semua pertanyaan atau long-session stability.
Durable persistence setelah percakapan suara, semua command legacy, dan stress test percakapan panjang belum diverifikasi ulang dalam release ini.
