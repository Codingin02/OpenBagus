# Financial Evidence Acceptance

Pengujian release memakai tool dan dataset existing yang sebenarnya, bukan angka fixture. Ini pengujian alur aplikasi, bukan verifikasi independen seluruh laporan emiten.
Bukti input/output/provenance: `reports/runtime/release/windows_acceptance.json` dan `offline_acceptance.json`.

## Cakupan

RATU, BBCA, TLKM, HGII dan BTCUSDT diuji. Perpindahan entitas diperiksa pada WorkingContext dan argumen tool aktual. Perbandingan memisahkan hasil setiap emiten.
Output mencantumkan provider/sumber, waktu akses UTC, tanggal observasi/periode, status cached/unavailable, serta penolakan klaim real-time.
PBV yang tidak tersedia tetap DATA_GAP. Input laba/ekuitas yang hilang tidak menjadi nol. ROE BBCA diverifikasi ulang dari `net_income / total_equity * 100`, sesuai periode yang dilaporkan dan tanpa annualization otomatis.
Mata uang dan satuan sumber dipertahankan. Nilai dalam million_IDR/billion_IDR ditampilkan sebagai juta/miliar Rp, bukan rupiah satuan. Harga USDT tidak diberi label Rp.
Katalis kosong berarti sumber yang diperiksa tidak memiliki catatan, bukan bukti tidak ada pengumuman baru di bursa.

## Keterbatasan Penting

- Filing existing bertanggal periode 2026-Q1; tanggal arsip/import bukan otomatis tanggal publikasi primer.
- Sebagian URL sumber berupa indeks IDX plus nama PDF. PDF primer dan seluruh angka belum diverifikasi ulang pada sesi ini.
- Angka di datastore tidak otomatis menjadi benar hanya karena balance-sheet equation atau JSON schema lolos.
- Sumber harga saham adalah EOD/delayed. Crypto public providers memerlukan internet dan coverage dapat berubah.
- Tidak ada rekomendasi transaksi, pengiriman order, atau klaim akurasi prediksi.
- Valuasi lanjutan, seluruh 951 emiten, SEC, macro, backtest, dan semua provider lain tidak diuji end-to-end dalam trial ini.

Status kegagalan provider offline harus dibaca dari gate C10, bukan disimpulkan dari health check Yahoo yang sukses.
