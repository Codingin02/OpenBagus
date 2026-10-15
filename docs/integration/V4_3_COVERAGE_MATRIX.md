# OpenBagus V4.3 Market-Wide Coverage Matrix

**Version:** 4.3.0  
**Date:** 2026-10-15  
**Audit Scope:** IDX Equities (968 instruments), US Equities (SEC EDGAR), Cryptocurrencies, Macroeconomic Indicators  
**Author:** Antigravity (Data Engineering Agent)  

---

## 1. Full IDX Universe Board Distribution

Reconciled from official IDX Statistical Universe (`openbagus/domains/equities/idx_universe.json`):

| Papan Pencatatan (Board) | Jumlah Emiten | Mekanisme Perdagangan | Status Riset | Status Eksekusi |
|---|---|---|---|---|
| **Papan Utama (Main)** | 252 | Continuous Auction | Eligible | Eligible |
| **Papan Pengembangan (Development)** | 440 | Continuous Auction | Eligible | Eligible |
| **Papan Akselerasi (Acceleration)** | 42 | Continuous Auction | Eligible | Eligible |
| **Papan Pemantauan Khusus (Special Monitoring)** | 214 | Periodic Call Auction (FCA) | Eligible | Restricted (Periodic Auction Only) |
| **Papan Ekonomi Baru (New Economy)** | 3 | Continuous Auction | Eligible | Eligible |
| **Indeks Sektoral & Komposit (Index)** | 17 | Composite Index | Eligible | Non-tradable Benchmark |
| **TOTAL** | **968** | — | **100% Eligible** | **Controlled via Policy** |

---

## 2. Representative Market-Wide Sample Audit

| Ticker | Nama Perusahaan | Papan / Sektor | Mata Uang | Sumber Filing | Status Neraca ($\Delta = A - [L + E]$) | Periode Terverifikasi |
|---|---|---|---|---|---|---|
| **TLKM** | PT Telkom Indonesia (Persero) Tbk | Main / Infrastruktur | IDR (Miliar) | IDX PDF (Audited) | $\Delta = 0.0$ (Seimbang) | 2025-FY, 2026-Q1 |
| **BBCA** | PT Bank Central Asia Tbk | Main / Keuangan (Perbankan) | IDR (Juta) | IDX PDF (Bilingual) | $\Delta = 0.0$ (Seimbang dengan Syirkah) | 2025-FY, 2026-Q1 |
| **RATU** | PT Raharja Energi Cepu Tbk | Development / Energi (Migas) | **USD (Penuh)** | IndoPremier / REC IR | $\Delta = 0.0$ (Seimbang) | 2025-FY, 2026-Q1 |
| **DATA** | PT Remala Abadi Tbk | Development / Telekomunikasi | IDR | Katalog BEI Offline | DATA_GAP (Jujur, Bebas Kolisi Kata) | Profil Terdaftar |
| **HGII** | PT Hero Global Investment Tbk | Development / Investasi | IDR | Katalog BEI Offline | DATA_GAP (Jujur) | Profil Terdaftar |
| **BRRC** | PT Raja Roti Cemerlang Tbk | Development / Konsumen | IDR | Katalog BEI Offline | DATA_GAP (Jujur) | Profil Terdaftar |
| **OBAT** | PT Brigit Biofarmaka Teknologi Tbk | Development / Kesehatan | IDR | Katalog BEI Offline | DATA_GAP (Jujur) | Profil Terdaftar |
| **AAPL** | Apple Inc. | US Equities / NASDAQ | USD | SEC EDGAR API | $\Delta = 0.0$ (US-GAAP) | 2024-FY .. 2026-Q3 |

---

## 3. Multi-Asset Zero-Key & Live Feed Coverage

| Kategori Aset | Provider Terverifikasi | Autentikasi | Data Tersedia | Rate Limit Safeguard |
|---|---|---|---|---|
| **IDX EOD & Live Quote** | Yahoo Finance Feed / IDX Discovery | Zero-Key | OHLCV, Volume, ADTV | Exponential Backoff (10-30s delay) |
| **US Equities Filings** | SEC EDGAR API (CIK Mapping) | User-Agent Resmi | 10-K, 10-Q, US-GAAP Facts | 10 req/s limit compliance |
| **Cryptocurrency Spot** | Binance Vision Public API / Gate.io | Zero-Key | Real-time Spot, 24h High/Low/Vol | Round-robin fallback |
| **Indikator Makroekonomi** | World Bank Open Data API | Zero-Key | CPI (Inflasi), PDB (GDP), JISDOR | 24h memory cache |

---

## 4. Fundamental Financial Invariant Matrix

| Emiten | Total Aset | Total Liabilitas | Total Ekuitas (+ Syirkah) | Selisih ($\Delta$) | Status Integritas |
|---|---|---|---|---|---|
| **RATU (2026-Q1)** | USD 130,922,817 | USD 70,227,868 | USD 60,694,949 | **0.0 USD** | **VALIDATED** |
| **RATU (2025-FY)** | USD 76,019,502 | USD 19,415,320 | USD 56,604,182 | **0.0 USD** | **VALIDATED** |
| **TLKM (2026-Q1)** | IDR 289,955 Miliar | IDR 134,145 Miliar | IDR 155,810 Miliar | **0.0 IDR** | **VALIDATED** |
| **BBCA (2026-Q1)** | IDR 1,640,830,566 Juta | IDR 1,370,360,247 Juta | IDR 259,358,793 Juta (+ Syirkah 11.111.526 Juta) | **0.0 IDR** | **VALIDATED** |
