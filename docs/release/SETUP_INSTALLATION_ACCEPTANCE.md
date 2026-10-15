# Windows Installation Acceptance

Target: Windows 11 x64, RTX 3050 Laptop 6 GB, RAM terdeteksi 11,71 GB.

- Installer: `E:\Projects\OpenBagus\release\OpenBagus-Setup.exe`.
- Ukuran: 1.105.374.609 byte.
- SHA-256: `d8cb55e72f1244b60f50117e909a46ebda4be99c594ea0ed6b413676b65fdd9c`.
- Aplikasi: `E:\Projects\OpenBagus\_installed\OpenBagus\OpenBagus.exe`.
- Model external: `E:\Projects\OpenBagus\models`; tidak dibundel ulang.
- Installer unsigned. Windows dapat menampilkan peringatan unknown publisher. Tidak ada perubahan Defender, SmartScreen, PATH global, atau security policy.

## Bukti

Wizard native Inno Setup benar-benar berjalan, melakukan instalasi/repair per-user tanpa administrator, kemudian menjalankan EXE sebagai original user. Log release: `reports/runtime/release/installation_release.log`. Log menyatakan installation succeeded dan tidak perlu restart Windows.
Bootstrap EXE terpasang mencapai READY dengan inferensi lokal nyata. Pengujian chat dijalankan dari `C:\Program Files`, tanpa PYTHONPATH, PYTHONHOME, atau VIRTUAL_ENV developer. Script Python hanyalah penguji stdin/stdout, bukan dependency aplikasi.
Repair kandidat terakhir menggunakan installer yang sama selesai dengan exit code 0; lihat `reports/runtime/release/installation_checkpoint.log`.
Screenshot wizard sebelumnya: `reports/runtime/release/installation_completed.png`. Screenshot yang diambil saat Installing bukan bukti halaman license/completion meskipun nama file mengandung kata tersebut.

Kedua shortcut asli (Windows Desktop known-folder dan Start Menu) membuka EXE sampai READY, lalu `/exit` keluar dengan code 0 dan port provider tertutup. Bukti: `reports/runtime/release/shortcut_acceptance.json`.
Status repair integrity dan recovery tercatat dalam `reports/runtime/release/acceptance_matrix.json`. Kelima file preferensi/sesi yang di-hash sebelum repair tetap sama pada pemeriksaan awal. Pengaturan Voice dikembalikan ke hash awal setelah trial. Setelah uji shortcut memakai Save context, tiga file tetap byte-identical; database harness dan JSON konteks berubah melalui penyimpanan metadata normal. `quick_check` database menghasilkan `ok`, dengan 418 turn historis yang masih tersedia. Tidak diklaim seluruh profil byte-identical setelah penggunaan aplikasi.

## Batasan

Uninstaller disediakan oleh Inno Setup dan menjaga external models/user data melalui pemisahan direktori; uninstall aktual dan restart Windows belum diuji. Drive target yang tidak tersedia dan interaksi antivirus pada mesin lain belum diuji.
Ini installer trial lokal pada mesin yang sudah memiliki canonical models, bukan installer universal yang men-download models sendiri.

Source dan build instructions: `packaging/windows/README.md`, `OpenBagus.spec`, `OpenBagus.iss`, `build.py`.
