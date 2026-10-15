# OPENBAGUS — V4.4 ROOT CAUSE & ARCHITECTURAL AUDIT
## Mengapa V4.3 Belum Sampai ke Pengguna & Diagnosis Kesenjangan Data Operasional

**Tanggal Audit:** 15 Oktober 2026  
**Penyusun:** Antigravity (Lead Financial Data Engineer & Systems Reliability Engineer)  
**Status:** COMPLETE & REPRODUCIBLE  

---

## 1. Executive Summary: Inti Permasalahan

Pengguna mengalami kondisi di mana OpenBagus berulang kali menyatakan:
- *"Data belum tersedia"*
- *"Laporan keuangan belum tersedia"*
- Memberikan jawaban umum tanpa menyajikan angka keuangan faktual
- Menanyakan kembali emiten apa yang ingin diteliti padahal pengguna telah menyebutkan `RATU`.

Berdasarkan audit langsung pada runtime Python, struktur worktree Git, alur eksekusi CLI, dan mekanisme Agent Harness, akar permasalahan **BUKAN** karena data laporan keuangan RATU tidak ada di disk, melainkan akibat **5 Celah Integrasi Vertikal (Vertical Integration Gaps)**:

1. **Kesenjangan Worktree (Deployment Isolation):** Kemajuan V4.1, V4.2, dan V4.3 berada di branch `feat/openbagus-automated-data-intelligence` pada worktree `E:\Projects\OpenBagus-Data`. Repositori utama `E:\Projects\OpenBagus` masih berada di commit lama `95d16dc` yang belum memiliki fungsi `get_operational_data_root()` maupun modul V4.3. Setiap kali pengguna menjalankan CLI dari folder utama `E:\Projects\OpenBagus`, sistem memuat kode usang yang membaca folder lokal kosong.
2. **Crash Format String pada Renderer Ekuitas (`research.py`):** Saat CLI mengeksekusi modul riset untuk RATU, pemformatan string rasio `f"{key} {value:,.3f}"` melempar `ValueError: Unknown format code 'f' for object of type 'str'` karena nilai rasio memuat teks status (misal `"ending_balance_point_in_time"` atau `"NOT_MEANINGFUL"`).
3. **Penyedia Deterministik Mengabaikan Hasil Eksekusi Tool (`fallback.py`):** Ketika LLM lokal offline atau dalam mode deterministik, `DeterministicFallbackProvider` memicu tool keuangan, namun pada giliran kedua (*synthesis turn*), ia sama sekali tidak membaca pesan `role == "tool"`. Akibatnya, data hasil tool diabaikan dan sistem mengembalikan kalimat template umum: *"Informasi emiten RATU tersedia di katalog... data dapat diakses melalui modul analitis terverifikasi"*.
4. **Heuristik Tool Tunggal (`if-elif` Chain):** Heuristik pemanggilan tool di `fallback.py` dirancang menggunakan rantai `elif` tunggal. Permintaan gabungan (harga + volume + laporan keuangan + katalis) hanya mengeksekusi `get_market_price` karena kata "harga" cocok pertama kali, sementara laporan keuangan dan katalis terabaikan.
5. **Kegagalan Parameter Wajib pada `GetFinancialStatementTool`:** Fungsi `run()` pada `GetFinancialStatementTool` mewajibkan argumen posisi `statement_type` tanpa nilai bawaan (*default*). Jika dipanggil hanya dengan `ticker="RATU"`, tool melempar `TypeError`.

---

## 2. Matriks Status Worktree & Jalur Impor Runtime

| Worktree | Branch Aktif | Commit HEAD | Status Git | Lokasi Berkas `openbagus` | Memiliki `get_operational_data_root`? |
|---|---|---|---|---|---|
| `E:\Projects\OpenBagus` (Main) | `fix/financial-integrity-recovery` | `95d16dc` | Clean | `E:\Projects\OpenBagus\openbagus\__init__.py` | **TIDAK** (`ImportError`) |
| `E:\Projects\OpenBagus-Data` | `feat/openbagus-automated-data-intelligence` | `ef04231` | Clean | `E:\Projects\OpenBagus-Data\openbagus\__init__.py` | **YA** (`C:\Users\bagus\AppData\Local\OpenBagus\data`) |
| `E:\Projects\OpenBagus-Voice` | `feat/openbagus-local-voice-live` | `39cd7a8` | Clean | `E:\Projects\OpenBagus-Voice\openbagus\__init__.py` | **TIDAK** (Commit Voice) |
| `E:\Projects\OpenBagus-3D` | `feat/bagusmax-3d-art` | `95d16dc` | Dirty | `E:\Projects\OpenBagus-3D\openbagus\__init__.py` | **TIDAK** (Aset Blender) |

> [!CRITICAL]
> **Apakah CLI utama di `E:\Projects\OpenBagus` melihat perubahan V4.3?**  
> **TIDAK.** Branch `feat/openbagus-automated-data-intelligence` belum pernah di-merge ke `main` maupun ke `fix/financial-integrity-recovery`. Oleh karena itu, pengguna yang membuka terminal di `E:\Projects\OpenBagus` tidak dapat mengakses data V4.3.

---

## 3. Matriks Penyedia Data (Working vs Nonworking Providers)

| Penyedia / Modul | Status | Sumber & Detail Teknis | Keterbatasan / Catatan |
|---|---|---|---|
| **Local Verified EOD Storage** | **WORKING** | `data/equities/eod/RATU.json` (418 bar harian s.d. 14 Okt 2026) | Harga penutupan Rp 3.620, Volume 1.895.800 lembar. |
| **Financial Statements Storage** | **WORKING** | `%LOCALAPPDATA%\OpenBagus\data\equities\financials\RATU\` | 2026-Q1 (USD) dan 2025-FY (USD Audited), $\Delta = 0.0$. |
| **Financial Facts Database** | **WORKING** | `%LOCALAPPDATA%\OpenBagus\data\equities\financial_facts.db` (SQLite WAL) | 17 fakta kanonikal tersimpan untuk 2026-Q1 dan 15 fakta untuk 2025-FY. |
| **Binance Vision Spot API** | **WORKING** | `https://api.binance.com/api/v3/ticker/price` & `/klines` (Public) | Kripto spot (BTC, ETH, SOL) real-time dan bar 1 jam. |
| **SEC EDGAR API** | **WORKING** | `https://data.sec.gov/api/xbrl/companyfacts/` (CIK 0000320193) | Emiten US (AAPL), wajib menyertakan User-Agent institusional. |
| **BI SEKI / Macro Data** | **WORKING** | Serial lokal terverifikasi untuk CPI (2.84%), PDB (5.05%), JISDOR (Rp 15.850). | Seri data makro offline terverifikasi. |
| **IDX Official REST / WS** | **RESTRICTED** | `idx.co.id` diproteksi Akamai Bot Manager (HTTP 403 WAF). | Akses otomatis dialihkan ke portal resmi emiten / dokumen unduhan terverifikasi. |
| **Intraday Live Ticks IDX** | **UNAVAILABLE** | BEI tidak menyediakan feed websocket publik tanpa lisensi broker berbayar. | Dilaporkan secara jujur sebagai `VERIFIED_EOD` as-of tanggal bursa terakhir. |

---

## 4. Rincian 5 Celah Kritis (Top 5 High-Priority Defects) & Cara Reproduksi

### Celah 1: Isolasi Worktree & Ketidakterjangkauan Kode V4.3 dari CLI Utama
- **Lokasi Berkas:** `openbagus/core/env.py`
- **Penyebab:** Modul `get_operational_data_root()` hanya ada di worktree Data (`E:\Projects\OpenBagus-Data`). Di worktree utama (`E:\Projects\OpenBagus`), impor modul tersebut melempar `ImportError`. Akibatnya, instance CLI utama tidak pernah membaca `%LOCALAPPDATA%\OpenBagus\data`.
- **Perintah Reproduksi:**
  ```powershell
  Set-Location E:\Projects\OpenBagus
  & ".\.venv\Scripts\python.exe" -c "from openbagus.core.env import get_operational_data_root"
  ```
- **Keluaran Eror:** `ImportError: cannot import name 'get_operational_data_root' from 'openbagus.core.env'`

---

### Celah 2: Format String Crash pada `render_equity`
- **Lokasi Berkas:** `openbagus/domains/equities/research.py` (Baris 110 & 164)
- **Penyebab:** Kode melakukan format numerik tanpa pemeriksaan tipe data:
  ```python
  "; ".join(f"{key} {value:,.3f}" for key, value in f["ratios"].items())
  ```
  Nilai dalam `f["ratios"]` memuat string metadata seperti `average_equity_basis: "ending_balance_point_in_time"`, `FCF_status: "NOT_MEANINGFUL"`, atau `Debt: "Debt Unverified"`.
- **Perintah Reproduksi:**
  ```powershell
  Set-Location E:\Projects\OpenBagus-Data
  & "E:\Projects\OpenBagus\.venv\Scripts\python.exe" -m openbagus.cli "Analisis fundamental RATU"
  ```
- **Keluaran Eror:** `ValueError: Unknown format code 'f' for object of type 'str'`

---

### Celah 3: `DeterministicFallbackProvider` Mengabaikan Hasil Tool
- **Lokasi Berkas:** `openbagus/ai/providers/fallback.py` (Baris 222–246)
- **Penyebab:** Pada iterasi ke-2 di `AgentHarness`, fungsi `generate()` dipanggil dengan `tools=None` dan menyertakan pesan tool result (`role == "tool"`). Namun fungsi `generate()` hanya mengekstrak `user_msg` dan mengabaikan seluruh pesan tool. Karena `tools=None`, ia langsung masuk ke blok `elif ticker and has_financial_intent` dan memuntahkan teks template statis tanpa angka keuangan.
- **Perintah Reproduksi:**
  ```powershell
  & "E:\Projects\OpenBagus\.venv\Scripts\python.exe" -c "
  from openbagus.ai.harness.orchestrator import AgentHarness
  from openbagus.ai.providers.fallback import DeterministicFallbackProvider
  h = AgentHarness(provider=DeterministicFallbackProvider())
  resp = h.run('Analisis RATU untuk timeframe harian dengan data terbaru. Tampilkan harga, volume, laporan keuangan, dan katalis relevan.')
  print(resp.content)
  "
  ```
- **Keluaran Teramati:**
  ```text
  Informasi emiten RATU tersedia di katalog lokal OpenBagus.
  Untuk analisis mendalam seperti laporan keuangan, rasio valuasi, dan perbandingan emiten, data dapat diakses melalui modul analitis terverifikasi.
  ```

---

### Celah 4: Rantai `elif` Menghalangi Pemanggilan Multi-Tool Finansial
- **Lokasi Berkas:** `openbagus/ai/providers/fallback.py` (Baris 188–221)
- **Penyebab:** Logika penentuan tool menggunakan struktur `if ... elif ... elif ...`. Jika pengguna menanyakan *"harga, volume, laporan keuangan, dan katalis"*, kata *"harga"* terdeteksi terlebih dahulu sehingga HANYA `get_market_price` yang dipanggil. Tool `calculate_financial_ratios`, `get_financial_statement`, dan `get_recent_company_events` tidak pernah dipanggil.
- **Perintah Reproduksi:**
  ```python
  # Inspeksi tool_calls_executed pada respons harness:
  # Hanya 1 tool terdaftar: get_market_price
  ```

---

### Celah 5: Parameter `statement_type` Wajib Tanpa Default di `GetFinancialStatementTool`
- **Lokasi Berkas:** `openbagus/ai/tools/finance_tools.py` (Baris 444–447)
- **Penyebab:** Definisi fungsi:
  ```python
  def run(self, ticker: str, statement_type: str, period: str = "LATEST")
  ```
  Jika agent atau pemanggil mengeksekusi `get_financial_statement(ticker="RATU")` tanpa menyertakan `statement_type`, Python melempar `TypeError: missing 1 required positional argument: 'statement_type'`.
- **Perintah Reproduksi:**
  ```powershell
  & "E:\Projects\OpenBagus\.venv\Scripts\python.exe" -c "
  from openbagus.ai.harness.orchestrator import get_global_tool_registry
  reg = get_global_tool_registry()
  res = reg.execute('get_financial_statement', {'ticker': 'RATU'})
  print(res.error)
  "
  ```
- **Keluaran Eror:** `GetFinancialStatementTool.run() missing 1 required positional argument: 'statement_type'`

---

## 5. Rencana Tindakan Perbaikan Vertikal (Immediate Vertical Slice Fix)

Untuk menyelesaikan masalah ini secara tuntas dari hulu ke hilir tanpa merusak stabilitas branch lain:

1. **Perbaikan Format String di `research.py`:** Tangani tipe data string/None pada dictionary rasio dengan aman (`f"{v:,.3f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{v}"`).
2. **Perbaikan Parameter Default di `GetFinancialStatementTool`:** Berikan nilai bawaan `statement_type: str = "ALL"`, dan buat skema parameter lebih fleksibel.
3. **Peningkatan `DeterministicFallbackProvider`:**
   - Ubah seleksi tool dari `elif` tunggal menjadi deteksi multi-kebutuhan sehingga query komprehensif memicu tool harga, rasio keuangan, dan keterbukaan informasi sekaligus.
   - Implementasikan *synthesis engine* pada `generate()` saat menerima pesan `role == "tool"`: baca hasil tool faktual (`reported_values`, `ratios`, `price`, `volume`, `events`) dan susun jawaban bahasa Indonesia yang terstruktur, padat, dan berbasis bukti nyata.
4. **Jalur Eksekusi CLI Non-Interaktif:** Pastikan `openbagus.cli` di argumen posisi menjalankan orkestrasi `AgentHarness` yang terintegrasi penuh jika query bersifat riset analitis natural, bukan hanya runner statis.
5. **Rencana Integrasi Worktree Terkontrol:** Dokumentasikan prosedur penggabungan aman (*safe cherry-pick / merge candidate*) dari branch data ke branch utama setelah acceptance audit lulus 100%.
