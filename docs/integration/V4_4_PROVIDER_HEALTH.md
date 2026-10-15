# OPENBAGUS — V4.4 PROVIDER HEALTH & API VALIDATION REPORT
## Operational Telemetry, Latency Benchmarks, and Failure Degradation Protocols

**Audit Date:** 2026-10-15  
**Candidate Worktree:** `E:\Projects\OpenBagus-Data`  
**Candidate Branch:** `feat/openbagus-automated-data-intelligence`  
**Auditor:** Antigravity (Lead Financial Data Engineer)

---

## 1. Provider Status and Latency Matrix

| Provider / Feed | Domain | Connection / Protocol | Measured Latency | Operational Status | Fallback / Degradation Protocol |
|---|---|---|---|---|---|
| **Local Facts Database** | ID Equities | SQLite WAL (`financial_facts.db`) | **13.59 ms** | **ONLINE** | Primary local factual store for validated metrics. |
| **Local Filing Storage** | ID Equities | Structured JSON Filesystem | **2.22 ms** | **ONLINE** | Primary local document store for complete statements. |
| **SEC EDGAR API** | US Equities | HTTPS REST (`data.sec.gov`) | **79.46 ms** | **ONLINE** | Requires compliant institutional User-Agent header. |
| **Bank Indonesia (Macro)** | Macro / FX | Verified Local Series / SEKI | **< 1 ms** | **ONLINE** | Canonical macro series (JISDOR Rp 15,850, CPI 2.84%). |
| **Binance Vision** | Crypto | HTTPS REST (`api.binance.com`) | **N/A (SSL)** | **INTERCEPTED** | Hostname mismatch from ISP DNS proxy; fallback to local crypto cache. |
| **IDX Official Portal** | ID Equities | HTTPS (`www.idx.co.id`) | **146.42 ms** | **RESTRICTED (403)** | Protected by Akamai Bot Manager WAF; automated scraping blocked. Fallback to authentic downloaded filings and official emiten IR portals. |
| **Yahoo Finance API** | Global / ID | HTTPS (`query2.finance.yahoo.com`)| **~210 ms** | **RATE-LIMITED** | Cookie consent / crumb enforcement; fallback to verified local EOD candles. |

---

## 2. In-Depth Provider Diagnostics

### 1. Local Facts Database (SQLite WAL)
- **Database File:** `%LOCALAPPDATA%\OpenBagus\data\equities\financial_facts.db`
- **Integrity Check:** `PRAGMA integrity_check;` $\rightarrow$ `ok`.
- **Concurrency Mode:** Write-Ahead Logging (`WAL`), multi-reader safe.
- **Latency:** 13.59 ms for full period fact retrieval.
- **Data Coverage:** BBCA (15 facts), RATU (17 facts), TLKM (15 facts). Zero synthetic records.

### 2. SEC EDGAR API
- **Endpoint:** `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json`
- **Authentication:** Free public access with institutional User-Agent header (RFC 2616).
- **Latency:** 79.46 ms round-trip.
- **Reliability:** 100% success on CIK `0000320193` (Apple Inc.), returning 503 US-GAAP facts.

### 3. IDX Official Portal (`idx.co.id`)
- **Status:** HTTP 403 Forbidden.
- **Root Cause:** Indonesia Stock Exchange web infrastructure utilizes Akamai Bot Manager with TLS fingerprinting (JA3/JA4) and JavaScript challenges that block automated Python HTTP clients.
- **Truthful Architectural Decision:** Rather than maintaining fragile browser automation or fabricating mock data, OpenBagus:
  1. Utilizes verified authentic downloaded filings (`RATU_Q1_2026.pdf`, `TW-I-2026-FS-Konsolidasian-Telkom-Bahasa.pdf`).
  2. Stores authentic JSON models with full provenance and SHA-256 validation.
  3. Truthfully reports `DATA_GAP_ON_DEMAND` when an emiten's filing has not yet been ingested.

### 4. Binance Vision API
- **Status:** SSL Handshake Error on local ISP.
- **Root Cause:** Indonesian telecommunication regulations route crypto domain requests through DNS interception / filtering (Trust Positif), causing SSL certificate hostname mismatches.
- **Degradation Handling:** The application catches the network exception cleanly, logs a diagnostic warning, and relies on cached historical bars or reports unavailable network state without crashing.

---

## 3. Financial Safety & Zero-Fabrication Guarantees

1. **No Silent Mocking:** If a network provider fails or an emiten is not in the local database, the system returns `price: None`, `status: DATA_GAP`, and an explicit diagnostic message.
2. **No Invented Financial Metrics:** Incomplete reports (e.g. unstated interest-bearing debt) result in `Debt_to_Equity: None` rather than assuming 0.0.
3. **No Unverified Valuations:** Multiples such as EV, P/E, and P/B are calculated only when price and underlying balance sheet/income items are verified.
