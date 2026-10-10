# Indonesian Equities

OpenBagus memakai satu CLI, IntentRouter, SessionState, QuantEngine dan ResearchPacket untuk crypto dan IDX. Foreign equities tidak aktif. Tidak ada pilihan market saat setup. `BUY/HOLD/WAIT/AVOID_ENTRY/REDUCE` adalah research view cash equity, bukan instruksi broker. `REDUCE` memerlukan konteks kepemilikan. Tidak ada perpetual, short selling, leverage atau eksekusi saham.

## Cakupan dan sumber

### IDX Data Coverage Matrix

| Provider | Data category | Authorization requirements | Free/keyless availability | Automated access permitted? | Historical coverage | Update frequency | Asset coverage | Source status | Known limitations |
|---|---|---|---|---|---|---|---|---|---|
| IDX Official Website | Company Profile & IDX-IC | Public publication | YES | NO (User Import Only) | 2021-now | Quarterly/Annual | 900+ Listed Issuers | IMPLEMENTED (User-owned import) | Terms prohibit scraping/crawling; imports require operator authorization |
| IDX Official Website | Daily Market Rules & Ticks | SK Direksi BEI | YES | NO (User Import Only) | Current policy snapshot | Per regulatory decree | All Regular & Cash boards | IMPLEMENTED (`config/idx_market_rules.json`) | Effective dates & calendar must be verified from authorized circulars |
| KSEI (Kustodian Sentral Efek Indonesia) | Shareholder Ownership (>5% & >1%) | Monthly Public Disclosure | YES | NO (User Import Only) | Monthly snapshots | Monthly (T+10) | All Listed Equities | IMPLEMENTED (`openbagus/domains/equities/ownership.py`) | Identifies holders >= 5%; residual float allocated to public remainder |
| Bank Indonesia (BI) | Policy Rate & JISDOR USD/IDR | Public Statistical Release | YES | NO (User Import Only) | 10+ years | Daily (JISDOR), Monthly (Rate) | Macro Reference | IMPLEMENTED (`openbagus/domains/equities/data.py`) | Reference figures only; cannot be assumed as live tick streaming |
| BPS (Badan Pusat Statistik) | CPI Inflation & GDP Growth | Official Press Release (BRS) | YES | NO (User Import Only) | 10+ years | Monthly (CPI), Quarterly (GDP) | Macro Reference | IMPLEMENTED (Macro events stack) | Monthly data; never backfilled as intraday observations |
| OJK (Otoritas Jasa Keuangan) | Banking & Capital Market Stats | Public Data Portal | YES | NO (User Import Only) | Monthly/Quarterly | Monthly | Banking Sector | IMPLEMENTED (Reported Bank Ratios) | Official publications; no undocumented JSON endpoints used |
| Verified Operator CSV/JSON | EOD OHLCV Price Bars | User-supplied data | YES | Local files only | Arbitrary historical length | Per import | User defined | IMPLEMENTED (`openbagus import-idx ohlcv`) | Requires explicit currency IDR, timezone, and corporate action status |
| Local OpenBagus Visualizer | Interactive HTML & Charts | Standard Library / Local Canvas | YES | YES (Offline Local) | Full dataset imported | Realtime on demand | All analyzed assets | IMPLEMENTED (`openbagus/reporting/visualizer.py`) | Self-contained HTML; zero CDN or cloud server dependencies |
| Local OpenBagus Word Engine | Microsoft Word DOCX Reports | Standard Library OpenXML | YES | YES (Offline Local) | Snapshot of research packet | On demand | All analyzed assets | IMPLEMENTED (`openbagus/reporting/word_report.py`) | Generates genuine DrawingML chart with embedded Excel workbook |

### Kepemilikan Saham (KSEI & IDX Ownership Intelligence)

OpenBagus menerapkan skema kepemilikan saham terverifikasi (`openbagus/domains/equities/ownership.py`):
1. **Pemisahan Denominator**: Membedakan secara eksplisit antara *shares outstanding* (total saham beredar) dengan *registered holdings* (efek tercatat KSEI).
2. **Pemegang Saham Utama**: Mencatat pemilik modal >= 5% beserta klasifikasi tipe investor (Institusi Domestik/Asing, Individu, BUMN/Pemerintah).
3. **Rekonsiliasi Sisa Publik**: Sisa persentase dihitung secara matematis (`100% - total_top_holders`) sebagai "Masyarakat / Publik (<5%)". Tidak ada rekayasa nama pemegang saham yang tidak dilaporkan.
4. **Komposisi Domestik vs Asing**: Memverifikasi agregat kepemilikan domestik dan asing agar saling eksklusif dan berjumlah 100% (dengan toleransi pembulatan).

### Validasi Indikator Matematika & Pola Candlestick

Seluruh kalkulasi teknikal dan risiko berada pada satu modul kanonikal (`openbagus/domains/quant/indicators.py`):
- **Moving Averages**: SMA dan EMA (dengan seed SMA).
- **Volatilitas**: Wilder ATR14, Realized Volatility, Bollinger Bands (Upper, Middle, Lower, Bandwidth).
- **Momentum & Trend**: RSI14 (Wilder smoothed), MACD (12, 26, 9), ADX14 (+DI, -DI), Stochastic %K/%D.
- **Microstructure**: VWAP, Relative Volume, Volume Profile (POC, VAH, VAL).
- **Risk Metrics**: Annualized Sharpe Ratio, Sortino Ratio, Value at Risk (VaR 95%), Conditional VaR (Expected Shortfall), Maximum Drawdown.
- **Pola Harga**: Bullish/Bearish Engulfing, Hammer Pin Bar, Shooting Star, Inside Bar, Double Bottom.

### Walk-Forward Backtesting

Engine backtest (`openbagus/domains/quant/backtesting.py`) menerapkan:
- **Pemisahan Kronologis**: Walk-forward Train (60%) -> Validation (20%) -> Out-of-Sample Test (20%). Tidak ada pengacakan time-series (*no shuffled validation*).
- **Bebas Lookahead**: Sinyal pada bar $t$ hanya memakai data $\le t$. Eksekusi dilakukan pada bar $t+1$ *open*.
- **Biaya Transaksi Nyata**:
  * Saham IDX: Komisi beli 0.15%, komisi jual 0.25% (termasuk levy BEI 0.043% dan PPh final 0.1%), satuan lot 100 lembar, serta fraksi harga (*tick bands*).
  * Crypto: Maker 0.05%, taker 0.10%, dan slippage model.
- **Promotion Gate**: Strategi hanya dipromosikan ke bobot produksi jika menghasilkan *out-of-sample profit factor* $\ge 1.20$, *win rate* yang memadai, dan *drawdown* dalam batas toleransi.

### Visualisasi & Pelaporan Native

- **/visualize [ASSET]**: Membuka dashboard HTML interaktif di `%LOCALAPPDATA%\OpenBagus\reports\` tanpa TradingView atau server web permanen. Mencakup Candlestick interaktif, Radar Multi-Faktor, Sunburst Kepemilikan, dan Heatmap Korelasi.
- **/report word [ASSET]**: Menghasilkan dokumen Word `.docx` profesional dengan chart DrawingML native dan workbook Excel tersemat (*editable native Office chart*).
- **/backtest [ASSET]**: Menjalankan backtest walk-forward dan menampilkan kurva ekuitas & drawdown.
- **/ownership [ASSET]**: Menampilkan ringkasan struktur kepemilikan terverifikasi.

### Source policy

- [IDX terms](https://www.idx.co.id/id/syarat-penggunaan): scraping/crawling tidak diperbolehkan; tidak ada CAPTCHA/Cloudflare bypass atau internal API. Dokumen/tabel pengguna harus berizin untuk tujuan pemakaiannya. Penyebutan source URL bukan bukti lisensi redistribusi.
- [IDX company profiles](https://www.idx.co.id/id/perusahaan-tercatat/profil-perusahaan-tercatat/) dan [index handbook](https://www.idx.id/media/9816/idx-stock-index-handbook-v12-_-januari-2021.pdf): rujukan identitas/IDX-IC; seed tidak mengonfirmasi status listing/suspension hari ini.
- [IDX trading rules](https://www.idx.id/id/produk-layanan/jam-dan-mekanisme-perdagangan/): snapshot referensi II-A Kep-00136/BEI/09-2026 di `config/idx_market_rules.json`. Tanggal efektif/expiry dan kalender sengaja tidak direka. Policy lokal harus diisi dari dokumen berizin untuk mengaktifkan setup.
- [BI/JISDOR](https://www.bi.go.id/id/fungsi-utama/moneter/informasi-kurs/default.aspx), [BPS](https://www.bps.go.id/), [OJK data portal](https://data.ojk.go.id/SJKPublic): publikasi resmi bukan feed harga live. Tidak ada endpoint JSON undocumented yang diasumsikan.
- [ANTM reports](https://antam.com/en/company-report/annual-report), [BCA](https://www.bca.co.id/tentang-bca/Hubungan-Investor), [Mandiri IR](https://www.bankmandiri.co.id/web/ir): fakta bisnis/keuangan; impor hanya dokumen/data pengguna yang diizinkan. Tidak ada framework PDF extraction baru.
- [yfinance source limitations](https://ranaroussi.github.io/yfinance/): unofficial dan personal-use; connector IDX tidak diaktifkan karena izin dan cakupan penggunaan belum terverifikasi. `.JK` dikenali sebagai identitas, bukan janji live feed.
- CNBC Indonesia RSS, Kontan/Bisnis/Reuters dan optional Twelve Data/EODHD/Marketstack/Alpha Vantage/FMP/Finnhub **tidak diaktifkan** untuk IDX: permission, plan dan symbol coverage belum terverifikasi. Tidak ada compulsory key atau klaim free-tier IDX. Registry `/setup` existing tetap dipertahankan; penambahan vendor memerlukan bukti cakupan/izin sebelum activation.

## Impor lokal

Data saham masuk `data/equities/` (ignored), bukan dataset berlisensi dalam Git.

```powershell
openbagus import-idx catalog C:\Data\idx-catalog.json
openbagus import-idx market C:\Data\BBCA.json
openbagus import-idx ohlcv C:\Data\BBCA.csv --metadata C:\Data\BBCA-metadata.json
openbagus import-idx rules C:\Data\idx-rules.json
openbagus "BBCA daily"
openbagus "BBCA H1"
openbagus "IDX sektor energi"
openbagus "BTC vs BBCA"
openbagus "chart BBCA"
```

Catalog JSON: list of objects with `symbol`, `name`, `sector_code`, `source` (public HTTPS without credentials/query), `effective_date`; optional `industry`, `hierarchy` (official codes/names), `exposures`, `listing_status`, `board`, `asset_type` (`EQUITY_ID`/`INDEX_ID`). CSV uses the same columns; list values separated by `;`. Classification history is maintained in the user's source, not invented by OpenBagus. Ticker changes require replacing/importing verified identities; the old identity must be explicitly marked delisted where applicable.

Market JSON: object with `symbol`, `authorized_use: true`, `source`, `retrieved_at` (ISO timezone), `currency: IDR`, `volume_unit: shares` (or `index_not_applicable`), `timeframe`, `adjustment` (`adjusted`/`unadjusted`), `unresolved_corporate_actions`, `listing_status`, `board` (`MAIN`/`DEVELOPMENT`/`NEW_ECONOMY`), optional `market_segment`. `quote` holds `price`, `previous_close`, `as_of`, `delayed` (explicit false for fresh), and verified instrument/day `price_limit_low/high`. `fees.buy/sell` are fractions, not percent integers. Bounds are not inferred from a universal auto-rejection percentage.

`candles`: `open_at`, `close_at` with timezone, `open/high/low/close/volume` finite numbers. CSV uses exactly those headers with metadata JSON carrying the other fields. No synthetic candles, missing-volume replacements, future bars or H1 precision from D1 bars. `benchmark_candles` optional: IHSG close/time pairs aligned with every source bar, not future or unrelated timeframes.

`fundamentals` and optional `previous_fundamentals`: `source`, `published_at`, `period`, `period_type: FY/TTM/QUARTER`, `basis`, `currency: IDR`, `unit: IDR/thousand_IDR/million_IDR/billion_IDR`, `values`. Monetary values scale by unit; `weighted_average_shares/shares_outstanding` always share counts. Known values include `revenue`, `net_income_attributable`, `net_income`, `equity_attributable`, `equity`, `average_equity_attributable`, `average_assets`, `interest_bearing_debt`, `operating_income`, `operating_cash_flow`, `capital_expenditure`, `dividends_attributable`. `reported_ratios_pct` uses actual percent-valued bank metrics. Growth requires `comparison.previous_period` and `comparison.kind: YoY/QoQ`; QoQ only for QUARTER and same basis/duration type. Quarterly profitability is not silently annualized.

`events`: short `summary` (<=600 characters), original `source`, `observation_period`, `published_at`, optional `event_at`, `assets` and/or `sectors`. The root `retrieved_at` records the import retrieval separately. Store only permitted summaries, not full articles. BI rate -> funding cost/loan yield/NIM/credit quality is a conditional mechanism; JISDOR/CPI/commodity facts require their own source and period. ANTM nickel/gold exposure does not imply a guaranteed equity return. Missing fields produce SOURCE GAP, not estimates.

`rules` follows the reference config with authoritative `effective_from/effective_until`, `calendar` mapping ISO date to true=open or false=holiday, and original `source`. Rule coverage must be explicitly limited; missing calendar days block active decisions. Special boards/short-selling eligibility remain outside scope. Imported files are never proof of permission on their own: the operator confirms authorized use, source truth and relevant dates.

## Local model

Qwen3-4B-Q4_K_M remains canonical on direct llama.cpp CUDA. [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) is Apache-2.0; [SoAIHQ GGUF](https://huggingface.co/SoAIHQ/Qwen3.5-4B-GGUF) is third-party, not an official Qwen distribution. Artifact metadata access failed on this machine with TLS connection resets/HttpRequestException, so download/checksum/CUDA comparative benchmark and activation were not completed. The old model is not deleted and fresh installation still provisions the verified stable model. No performance advantage is claimed without paired fixtures and measured startup/latency/memory/grounding.
