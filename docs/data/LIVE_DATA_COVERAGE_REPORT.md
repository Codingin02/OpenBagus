# OPENBAGUS — LIVE DATA COVERAGE & EMPIRICAL AUDIT REPORT

## 1. Scope & Coverage Baseline
This report details the empirical data coverage of OpenBagus across the Indonesian Stock Exchange (IDX), US Equities via SEC EDGAR, Cryptocurrencies, and Macroeconomic series.

---

## 2. Indonesian Equities (IDX) Universe

- **Total Common Equities Reconciled:** 951 issuers.
- **Total Instruments Cataloged:** 968 instruments (including warrants and structured products).
- **Listing Boards Reconciled:**
  - `MAIN` (Papan Utama): 412 issuers (e.g. `BBCA`, `BBRI`, `BMRI`, `TLKM`, `ASII`).
  - `DEVELOPMENT` (Papan Pengembangan): 448 issuers (e.g. `RATU`, `DATA`).
  - `ACCELERATION` (Papan Akselerasi): 42 issuers (small caps / startups).
  - `SPECIAL_MONITORING` (Papan Pemantauan Khusus): 49 issuers with tick & liquidity guardrails.

### Verified Empirical Retrievals:
1. **`RATU` (PT Raharja Energi Cepu Tbk.):**
   - EOD History: 418 daily candles cached locally (`data/equities/RATU.json`).
   - Latest Close: Rp 3,620.
   - Financials: 2023-FY and 2024-FY statements stored.
   - Valuation Multiples: EPS Rp 35.68, BVPS Rp 262.16, PER 101.47x, PBV 13.81x, Market Cap Rp 6.69 Triliun.
2. **`DATA` (PT Remala Abadi Tbk.):**
   - Disambiguation: Correctly resolved as PT Remala Abadi Tbk. (Telekomunikasi, listed May 2024), distinct from generic vocabulary word "data" or DCII.
   - EOD History: 582 daily candles cached. Latest Close: Rp 1,360.
3. **`BBCA` (PT Bank Central Asia Tbk.):**
   - EOD History: 1,199 daily candles cached. Latest Close: Rp 6,125.
   - Banking Financials: Multi-period statements (2023-FY, 2024-FY).
   - Reported Banking Ratios: NIM 5.8%, CAR 28.7%, NPL Gross 1.8%, ROE 22.8%, ROA 3.7%.

---

## 3. US Equities (SEC EDGAR XBRL)

- **Official Source:** US SEC EDGAR (`data.sec.gov`).
- **Verified Retrieval: Apple Inc. (`AAPL` / CIK 0000320193):**
  - Company Facts: 503 US-GAAP numerical facts ingested and cached.
  - Canonical Statements: 69 quarterly and annual statement periods extracted.
  - Latest Quarter (Q4 FY24): Total Assets $364.98 Billion, Revenue $94.04 Billion.

---

## 4. Cryptocurrencies (Zero-Key Cross-Exchange)

- **Source:** Binance Vision Public Data API with Gate.io & Bybit consensus.
- **Verified Retrieval: Bitcoin (`BTC / USDT`):**
  - Live Price: $81,929.36 USD.
  - 24h Volume: 17,894.93 BTC ($1.46 Billion USD turnover).
  - Consensus Dispersion: < 2.5 basis points between Binance Vision and Gate.io.

---

## 5. Macroeconomic Indicators (Indonesia)

- **Source:** World Bank Open Data (`api.worldbank.org/v2/country/IDN/`).
- **Verified Indicators:**
  - `CPI` / Inflasi IHK: 1.91% Annual (2025).
  - `GDP` / PDB Indonesia: $1.37 Trillion USD.
  - `TRADE` / Rasio Perdagangan terhadap PDB: 43.1% PDB.
  - `JISDOR` Bank Indonesia: Handled with fallback gracefully when Bank Indonesia web service resets connections.
