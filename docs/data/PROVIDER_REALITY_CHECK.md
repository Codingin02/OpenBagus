# OpenBagus — Provider Reality Check & Multi-Provider Capability Matrix
**Document ID:** DOC-DATA-PROVIDER-20261015-04  
**Target Worktree:** `E:\Projects\OpenBagus-Data`  
**Execution Timestamp:** 2026-10-15T06:10:14Z / 2026-10-14T23:10:14 UTC  

---

## 1. Evaluation Methodology

Every data provider in OpenBagus is evaluated across 7 distinct, independent criteria:
1. `IMPLEMENTED`: Concrete Python adapter class integrated into `DataProviderRegistry`.
2. `REACHABLE`: Remote endpoints respond without network timeouts or connection drops.
3. `AUTHENTICATED`: Authentication credentials or open access protocols verified.
4. `RETRIEVAL_VERIFIED`: Actual data payload retrieved over the network.
5. `PARSING_VERIFIED`: Response payload parsed into canonical models without schema error.
6. `DATABASE_INGESTION_VERIFIED`: Parsed records stored in SQLite or local persistent cache.
7. `CONVERSATION_VERIFIED`: Available to agent tools and surfaced in natural language dialogue.

---

## 2. Multi-Provider Reality Matrix

| Provider Name | Implemented | Reachable | Authenticated | Retrieval Verified | Parsing Verified | DB Ingestion Verified | Conversation Verified | Primary Freshness Classification |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Yahoo Finance** | YES | YES | YES (Zero-Key) | YES | YES | YES | YES | `LATEST_EOD` / `DELAYED_VERIFIED` |
| **SEC EDGAR** | YES | YES | YES (User-Agent) | YES | YES | YES | YES | `AUTHENTIC_VERIFIED` |
| **IDX Disclosures & Filings** | YES | PARTIAL | RESTRICTED | PARTIAL | YES | QUARANTINED | YES | `SOURCE_RESTRICTED` |
| **World Bank Open Data** | YES | YES | YES (Zero-Key) | YES | YES | YES | YES | `AUTHENTIC_VERIFIED` |
| **Bank Indonesia (wsKursBI)** | YES | NO (Reset) | PUBLIC | NO | YES | NO | NO | `SOURCE_UNAVAILABLE` |

---

## 3. Deep-Dive Provider Analysis

### 1. Yahoo Finance (`YahooFinanceEquitiesProvider`)
- **Role:** Primary provider for Indonesian (`.JK`) and US equity daily closing candles and delayed market quotes.
- **Reality Check:**
  - Queries `query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}.JK`.
  - HTTP 200 operational with zero API keys.
  - **Freshness Realism:** The provider returns delayed quotes during session hours and finalized EOD candles post-market. It is **never** classified as `REALTIME_VERIFIED`; its status is strictly `LATEST_EOD` or `DELAYED_VERIFIED`.

### 2. SEC EDGAR (`SecEdgarProvider`)
- **Role:** Primary provider for US corporate disclosures, 10-K/10-Q forms, and XBRL facts.
- **Reality Check:**
  - Queries `data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json`.
  - Authenticated via custom User-Agent complying with SEC Fair Access policy.
  - Successfully ingested Apple Inc. (`AAPL` / CIK `0000320193`) with 950 atomic facts and 69 multi-period statements. 100% verified.

### 3. Indonesia Stock Exchange (`IdxDisclosuresProvider` / `IdxXBRLFilingParser`)
- **Role:** Provider of official Indonesian financial filings, press releases, and corporate actions.
- **Reality Check:**
  - `https://www.idx.co.id`: Completely blocked by Cloudflare Bot Management (HTTP 403 Forbidden).
  - `https://idx.id`: Primary API `https://idx.id/primary/ListedCompany/GetFinancialReport` returns HTTP 200 with authentic filing metadata for BBCA, TLKM, and DATA.
  - Attachment binary download endpoints (`DownloadFinancialReport?fileId=...`) return HTTP 503 (Cloudflare Turnstile challenge).
  - **Strict Honesty:** Automated direct file download is `SOURCE_RESTRICTED`. Filings must be ingested via browser-permitted sessions or manual inbox ingestion (`data/equities/inbox/`).

### 4. World Bank Open Data (`WorldBankMacroProvider`)
- **Role:** Provider of macroeconomic indicators for Indonesia (CPI / Inflasi, GDP, Interest Rates).
- **Reality Check:**
  - Queries `https://api.worldbank.org/v2/country/IDN/indicator/{INDICATOR}?format=json`.
  - HTTP 200 operational with zero API keys.
  - Ingests verified annual time series (e.g., Indonesia CPI index from 1960 to 2024).

### 5. Bank Indonesia (`BankIndonesiaAdapter` / wsKursBI) vs SEKI
- **Role:** Provider of official reference exchange rates (JISDOR) and banking statistics.
- **Reality Check:**
  - Endpoint `https://www.bi.go.id/biwebservice/wskursbi.asmx/getSubKursJisdor1` currently throws `ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host` when probed directly from this host.
  - **Clarification on SEKI (Statistik Ekonomi dan Keuangan Indonesia):** Bank Indonesia does **not** provide an open programmatic REST JSON API for SEKI. SEKI is published monthly as static Excel workbooks and PDF compilations. Claims of automated live REST API ingestion for SEKI are inaccurate; SEKI requires periodic tabular file imports, unlike World Bank's automated JSON REST endpoint.
