# Windows Trial: Bug Recovery

Status akhir mengikuti `FINAL_RELEASE_CHECKPOINT.md` dan laporan acceptance lokal.
Regresi source: 38 tes terarah lulus. Ini bukan pengganti acceptance EXE atau akustik.

## BUG 01: Entity Dan Konteks

Ekstraksi ticker lama hanya memperbarui state tertentu saat konteks kosong. Input biasa juga melewati parser CLI legacy yang berbeda dari AgentHarness.
`cli.py` kini mengirim pesan natural ke AgentHarness; WorkingContext menjadi state percakapan chat/suara yang dibagikan. Ticker baru divalidasi, argumen tool memakai entitas aktif, dan perbandingan menjalankan tool per emiten.
Ticker eksplisit yang tidak terverifikasi tidak boleh memakai data emiten sebelumnya. Namespace tutor dan timeframe ikut serialization. Persistence tetap opt-in.

## BUG 02: Bukti Financial

Narasi bebas model sebelumnya dapat menambah fakta tanpa bukti. Permintaan angka umum kini memakai hasil tool terstruktur dan penyajian deterministik, termasuk provider, periode/observasi, waktu akses, satuan, serta data gap.
Input rasio yang hilang tidak diisi nol. ROE adalah return periode laporan, bukan otomatis annualized. Mata uang dan skala juta/miliar tidak ditukar. Provider kripto yang gagal tidak jatuh ke kuotasi saham.
Arsip filing existing belum diverifikasi ulang terhadap PDF primer; URL indeks plus nama PDF bukan bukti verifikasi sumber primer terbaru. Jangan menganggap hasil ini rekomendasi transaksi.

## BUG 03: Voice

VAD lama kehilangan konteks temporal per frame. Timer durasi maksimum juga menghitung waktu idle. Token cancellation yang sama dibersihkan lagi untuk turn baru, sehingga pekerjaan lama bisa hidup kembali.
Perbaikan: konteks VAD bergulir, fail-closed saat VAD gagal, timer mulai saat onset, event cancellation baru per turn, gate ASR untuk silence/confidence, dan endpoint akustik sekitar 1,28 detik.
ASR parsial sinkron di loop pengambilan audio dihapus agar Whisper CPU tidak menghentikan polling frame setiap jeda. ASR memakai CPU int8 pada GPU 6 GB untuk menyisakan VRAM bagi LLM.
Status: FAIL pada acceptance akustik. EXE menghasilkan dua transkripsi outro yang tidak diucapkan; pengguna mengonfirmasi ruangan tenang. Pengukuran VAD source selama 12 detik berikutnya tidak mereproduksi onset palsu, sehingga penyebab akustik tepatnya belum terbukti. Perbaikan internal di atas tidak menutup BUG 03.
Mute hanya menghentikan capture baru; satu ASR yang sedang berjalan masih sempat mengeluarkan transkripsi. Untuk menghentikan sesi sepenuhnya gunakan `/voice off`. Echo, pause dan barge-in belum memperoleh acceptance manusia; lihat `VOICE_HARDWARE_ACCEPTANCE.md`.

## BUG 04: DEEP Tutor

Budget awal terlalu kecil untuk thinking. Menaikkannya menjadi 3072 token belum cukup menjamin jawaban: satu uji EXE menghasilkan content kosong setelah 77,9 detik meskipun 4B termuat.
Adapter lama juga selalu melaporkan finish reason `stop`. Kini alasan asli disimpan. Bila API mengonfirmasi `length` dengan content kosong, hanya satu retry dilakukan pada model yang sama, tanpa thinking, maksimal 512 token dan dalam sisa timeout (maksimal 30 detik).
Recovery dinyatakan dalam jawaban dan `/status.model.last_generation`; tidak ada perpindahan diam-diam ke FAST. Ini tetap keterbatasan DEEP, bukan bukti penalaran lebih akurat.
Jalur tersebut teruji pada Ollama asli dengan budget satu token yang sengaja dipaksakan. Output satu huruf pada probe tersebut bukan acceptance kualitas tutor.

## BUG 05: Natural Input

Slash command diproses eksplisit; pesan tanpa slash masuk ke chat. Kata biasa tidak lagi dipakai sebagai command/ticker melalui parser legacy. Permintaan pergerakan companion tidak mengklaim aksi bila companion tidak aktif.

## Packaging Dan Diagnostik

Snapshot `idx_universe.json` sebelumnya tidak ikut EXE, menyebabkan HGII tidak dikenali. Snapshot existing kini disertakan tanpa membuat dataset baru.
JSON `/status` tidak dibungkus seperti paragraf sehingga string panjang tetap valid. Frozen resources, external models, child DLL lookup, audio default-device lookup, dan lifecycle server lokal ditangani pada bootstrap canonical.
Penanganan kegagalan startup kini menerima stdin tertutup tanpa menambahkan traceback `EOFError`; pesan BLOCKED dan lokasi diagnostik tetap terlihat.
