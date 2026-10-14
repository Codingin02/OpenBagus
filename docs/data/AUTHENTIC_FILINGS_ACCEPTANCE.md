# OpenBagus — Authentic Filings Acceptance & Endpoint Verification
**Document ID:** DOC-DATA-FILINGS-20261015-02  
**Target Worktree:** `E:\Projects\OpenBagus-Data`  
**Execution Timestamp:** 2026-10-15T06:07:49Z / 2026-10-14T23:07:49 UTC  

---

## 1. Directive Objective

To establish empirical truth regarding document discovery and retrieval across the Indonesia Stock Exchange (IDX) and the US Securities and Exchange Commission (SEC EDGAR). Rather than assuming success or constructing synthetic URLs, this audit probes authentic endpoints, captures HTTP status codes and response headers, detects Cloudflare access restrictions, and evaluates parser readiness.

---

## 2. Official IDX Document Discovery Audit

Probes were conducted across 4 representative issuers across multiple market capitalization tiers:
1. `BBCA` (PT Bank Central Asia Tbk. — Large Cap Banking / Main Board)
2. `TLKM` (PT Telkom Indonesia Tbk. — State-Owned Enterprise / Telecom)
3. `RATU` (PT Raharja Energi Cepu Tbk. / Ratu Prabu Energi — Development Board / Energy)
4. `DATA` (PT Remala Abadi Tbk. — Acceleration / Recent IPO Small Cap)

### Empirical Network Probe Results:

| Target Endpoint | Issuer / Period | HTTP Status | Server | Content-Type | Result / Payload Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan` | - | **403 Forbidden** | cloudflare | `text/html` | Blocked by Cloudflare Bot Management (Ray ID ending `-CGK`). |
| `https://idx.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan` | - | **200 OK** | cloudflare | `text/html` | Serves official Nuxt/Vue SSR landing page (187,202 bytes). |
| `https://www.idx.co.id/id/perusahaan-tercatat/xbrl` | - | **403 Forbidden** | cloudflare | `text/html` | Blocked by Cloudflare Challenge (Ray ID ending `-CGK`). |
| `https://idx.id/id/perusahaan-tercatat/xbrl` | - | **200 OK** | cloudflare | `text/html` | Serves official XBRL portal HTML (209,686 bytes). |
| `https://idx.id/primary/ListedCompany/GetFinancialReport?year=2023&reportType=rdf&kodeEmiten=BBCA` | BBCA (2023) | **200 OK** | cloudflare | `application/json` | `ResultCount: 1`, returns authentic metadata & 5 attachments (XLSX, PDF, XBRL zip). |
| `https://idx.id/primary/ListedCompany/GetFinancialReport?year=2023&reportType=rdf&kodeEmiten=TLKM` | TLKM (2023) | **200 OK** | cloudflare | `application/json` | `ResultCount: 1`, returns authentic metadata & 7 attachments. |
| `https://idx.id/primary/ListedCompany/GetFinancialReport?year=2024&reportType=rdf&kodeEmiten=DATA` | DATA (2024) | **200 OK** | cloudflare | `application/json` | `ResultCount: 1`, returns authentic metadata & 8 attachments. |
| `https://idx.id/primary/ListedCompany/GetFinancialReport?year=2023&reportType=rdf&kodeEmiten=RATU` | RATU (2023) | **200 OK** | cloudflare | `application/json` | `ResultCount: 0`, empty results (filing under different schedule or special board). |
| `https://www.idx.co.id/primary/ListedCompany/GetFinancialReport...` | All | **403 Forbidden** | cloudflare | `text/html` | Direct API on `www.idx.co.id` blocked without browser session token. |

---

## 3. Authentic Attachment Download Probing

The metadata retrieved from `https://idx.id/primary/ListedCompany/GetFinancialReport` provides real attachment records:
- **BBCA TW1 2023:**
  - Attachment: `FinancialStatement-2023-I-BBCA.xlsx`
  - File ID: `0d96190d-b768-4138-9921-8aac4ec2ed0a`
  - Reported Size: 589,422 bytes
  - Modified: `2023-04-27T17:17:03.217`
- **TLKM TW1 2023:**
  - Attachment: `FinancialStatement-2023-I-TLKM.xlsx`
  - File ID: `4a5d5646-1793-456d-9cb9-12815769264b`
  - Reported Size: 1,180,836 bytes
- **DATA TW1 2024:**
  - Attachment: `FinancialStatement-2024-I-DATA.xlsx`
  - File ID: `eaa27f28-06a9-49eb-b7c9-bc12b08720f5`
  - Reported Size: 362,409 bytes

### Binary Attachment Download Execution:
When attempting programmatic download of the attachment binary via:
- `https://idx.id/primary/ListedCompany/DownloadFinancialReport?fileId=0d96190d-b768-4138-9921-8aac4ec2ed0a` -> **HTTP 503 Service Unavailable** (Cloudflare Turnstile challenge)
- `https://www.idx.co.id/primary/ListedCompany/DownloadFinancialReport?fileId=...` -> **HTTP 403 Forbidden**

### Truthful Classification:
- **Metadata Discovery:** Fully functional via `https://idx.id/primary/ListedCompany/GetFinancialReport` (HTTP 200).
- **Direct Binary File Download:** Classified truthfully as `DOCUMENTED_ACCESS_RESTRICTION` / `SOURCE_RESTRICTED`. Automated background download requires session cookies, Cloudflare clearance, or manual file drop into `data/equities/inbox/`.

---

## 4. SEC EDGAR Provenance Audit (AAPL)

In contrast to IDX's Cloudflare challenges, the US SEC EDGAR API provides open access adhering to their documented User-Agent fair access policy.

### Audit Findings for Apple Inc.:
- **CIK:** `0000320193` (stored zero-padded as required by SEC standards)
- **Entity Name:** Apple Inc.
- **Source API URL:** `https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json`
- **Raw Cache:** `data/equities/sec/companyfacts_CIK0000320193.json` (7,961,464 bytes)
- **Taxonomies:** `dei` (Document and Entity Information), `us-gaap` (503 concepts)
- **Verified Facts in Database:** 950 atomic facts in `data/equities/financial_facts.db` with complete accession numbers (`0000320193-24-000106`, etc.), fiscal years, period end dates, and scaling units.
- **Canonical Statements:** 69 multi-period statement files under `data/equities/financials/AAPL/` spanning from `2009-FY.json` to `2026-Q3.json`.
- **Integrity Status:** 100% authentic, verified, and free of synthetic seed data.
