# OpenBagus — Actual Dataset Coverage & Metrics Report
**Document ID:** DOC-DATA-COVERAGE-20261015-03  
**Target Worktree:** `E:\Projects\OpenBagus-Data`  
**Execution Timestamp:** 2026-10-15T06:09:39Z / 2026-10-14T23:09:39 UTC  

---

## 1. Universe vs. Data Coverage Realism

A common misconception in conversational AI systems is conflating catalog presence (knowing ticker names) with verified data depth (possessing multi-year audited financial statements). OpenBagus enforces an honest, transparent distinction between catalog scope and actual persistent data coverage.

---

## 2. Statistical Breakdown Across Datasets

### A. Listed Instrument Universe (Catalog Coverage: 100%)
- **Total Reference Instruments:** 968
- **Common Equities:** 951 IDX-listed public companies
- **Exchange Indices:** 17 benchmark indices (IHSG, LQ45, IDX30, ISSI, etc.)
- **Board Distribution:**
  - Main Board (`Papan Utama`): 252 issuers
  - Development Board (`Papan Pengembangan`): 440 issuers
  - Special Monitoring Board (`Papan Pemantauan Khusus`): 214 issuers
  - Acceleration Board (`Papan Akselerasi`): 42 issuers
  - Main New Economy (`Papan Utama Ekonomi Baru`): 3 issuers
  - Indices: 17
- **Sector Coverage:** 11 IDX IC sectors (Consumer Non-Cyclicals 132, Cyclicals 164, Basic Materials 110, Financials 105, Properties 94, Energy 89, Infrastructures 70, Industrials 68, Technology 46, Transportation 38, Healthcare 35).
- **Provenance:** Reconciled against official IDX Statistical Monthly Universe.

### B. End-Of-Day (EOD) Market Price Candles
- **Offline Cached Files:** 6 issuers (`ASII`, `BBCA`, `DATA`, `ISAT`, `RATU`, `TLKM`)
- **Offline Cached Share:** 0.63% of universe
- **Dynamic On-Demand Fetching:** Active via `YahooFinanceEquitiesProvider` (`auto_fetch=True`). When a user queries an uncached symbol, the system retrieves and stores 400+ EOD candles dynamically without user intervention.
- **Freshness Policy:** Classified strictly as `LATEST_EOD` or `DELAYED_VERIFIED`.

### C. Financial Statements (Audited & Reviewed Multi-Period Disclosures)
- **Active Authentic Issuers:** 1 (`AAPL` / Apple Inc.)
  - Total Statement Files: 69 periods (`2009-FY` through `2026-Q3`)
  - Provenance: US SEC EDGAR XBRL company facts API.
- **IDX Issuers with Persistent Statements:** 0 active in production.
  - Previous synthetic records for `BBCA` (2023-FY, 2024-FY) and `RATU` (2023-FY, 2024-FY) have been moved to `data/quarantine/financials/`.
  - Indonesian financial statements are classified as `DATA_GAP` until authentic filings are dropped into `data/equities/inbox/` or retrieved via permitted sessions.

### D. Canonical Facts Database (`financial_facts.db`)
- **Total Database Facts:** 998 rows across 2 tables:
  - **Active Valid Facts:** 950 rows (`AAPL` only, `validation_status = 'VALID'`)
  - **Quarantined Facts:** 48 rows (`BBCA`: 22 rows, `RATU`: 26 rows, `validation_status = 'QUARANTINED_SYNTHETIC'`)
- **Filing Index Table:** 0 unverified rows.

---

## 3. Summary Coverage Matrix

| Dataset Dimension | Total Universe | Offline Cached | Dynamic Fetch Available | Verified Authentic Data | Status Classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Catalog Metadata** | 951 Equities | 951 (100%) | N/A (Bundled) | 951 | `AUTHENTIC_VERIFIED` |
| **EOD OHLCV Candles** | 951 Equities | 6 (0.63%) | Yes (Yahoo Finance) | 6 cached + On-Demand | `LATEST_EOD` |
| **IDX Financial Filings** | 951 Equities | 0 | Restricted (Cloudflare) | 0 active (4 quarantined) | `DATA_GAP` / `SOURCE_RESTRICTED` |
| **SEC EDGAR Filings** | US Tickers | 1 (AAPL) | Yes (SEC EDGAR API) | 69 periods (950 facts) | `AUTHENTIC_VERIFIED` |
| **Crypto Spot Quotes** | Top Pairs | 0 cached | Yes (Binance Vision / Gate.io) | Real-time Zero-Key | `REALTIME_VERIFIED` |
| **Macro Indicators** | Global / IDN | 0 cached | Yes (World Bank Open Data) | CPI, GDP Annual Series | `AUTHENTIC_VERIFIED` |
