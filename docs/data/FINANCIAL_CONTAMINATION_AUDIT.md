# OpenBagus — Financial Contamination Audit & Quarantine Report
**Document ID:** DOC-DATA-AUDIT-20261015-01  
**Target Worktree:** `E:\Projects\OpenBagus-Data`  
**Branch:** `feat/openbagus-automated-data-intelligence`  
**Base Commit:** `b75bc54`  
**Execution Timestamp:** 2026-10-15T06:04:06Z / 2026-10-14T23:04:06 UTC  

---

## 1. Executive Summary & Incident Analysis

During the execution of Master Engineering Directive V4, an automated seed script (`Seed statements for BBCA, RATU, AAPL`) manually synthesized financial statement files for Indonesian issuers `BBCA` (PT Bank Central Asia Tbk.) and `RATU` (PT Raharja Energi Cepu Tbk. / Ratu Prabu Energi) for fiscal years 2023 and 2024.

### Contamination Mechanics:
1. **Invented Uniform Resource Locators (URLs):**
   - Statements contained fabricated source URLs:
     - `https://www.idx.co.id/filings/BBCA_2023.json`
     - `https://www.idx.co.id/filings/BBCA_2024.json`
     - `https://www.idx.co.id/filings/RATU_2023.json`
     - `https://www.idx.co.id/filings/RATU_2024.json`
   - Neither the Indonesia Stock Exchange (IDX) nor any official regulator provides JSON endpoints formatted as `/filings/{TICKER}_{YEAR}.json`.
2. **Hardcoded Financial Quantities:**
   - BBCA FY2024: Revenue of IDR 60,000,000,000,000; Net Income attributable IDR 54,800,000,000,000; total equity IDR 252,000,000,000,000; NIM 5.8%; CAR 28.7%; NPL 1.8%.
   - RATU FY2024: Revenue IDR 330,000,000,000; Cost of Revenue IDR 195,000,000,000; Gross Profit IDR 135,000,000,000; DER 0.2x; ROE 15.3%.
   - **Severe Accounting Risk:** `total_debt = 0.0` was assigned to BBCA without primary filing lineage, causing `CalculateFinancialRatiosTool` to assert DER = 0.0 and report an unwarranted "Solvent" classification.
3. **Database Fact Contamination:**
   - The script executed `FinancialFactsDatabase.store_fact()` for both issuers, registering 48 normalized facts (22 for BBCA, 26 for RATU) with `validation_status = 'VALID'` and `source_provider = 'OFFICIAL_FILING'` in `data/equities/financial_facts.db`.

---

## 2. Pre-Quarantine Cryptographic State & Backup

Prior to modifying any production files, a full bit-for-bit backup was established:
- **Backup Directory:** `data/backup_pre_quarantine_20261015/`
- **Archived Stores:**
  - `data/backup_pre_quarantine_20261015/financials/`
  - `data/backup_pre_quarantine_20261015/financial_facts.db` (368,640 bytes)

### Quarantined File Inventory & Hashes:
| Quarantined File | Size | SHA-256 Digest | Fabricated Source URL |
| :--- | :--- | :--- | :--- |
| `data/equities/financials/BBCA/2023-FY.json` | 785 B | `93a957856ac80f8ffb826e7f5a76e07640c1dfbb3470a5b73bcb590b207e0383` | `https://www.idx.co.id/filings/BBCA_2023.json` |
| `data/equities/financials/BBCA/2024-FY.json` | 785 B | `7557a56f3125e49e0066c5c089f9bf0e277310452218e57c3e217e3a35b2b326` | `https://www.idx.co.id/filings/BBCA_2024.json` |
| `data/equities/financials/RATU/2023-FY.json` | 786 B | `9647f10ffe71b7df2e78593e71fc24bd6d4462261fa45a266474eb27ae5fea8e` | `https://www.idx.co.id/filings/RATU_2023.json` |
| `data/equities/financials/RATU/2024-FY.json` | 786 B | `022b9b6f911673dec81c78447d38b931eaa58a3a96a7705bd40e5ce9f4827a82` | `https://www.idx.co.id/filings/RATU_2024.json` |

---

## 3. Quarantine Migration Implementation

Quarantine execution was automated via `scripts/quarantine_synthetic_data.py`.

### Migration Capabilities Verified:
1. **Dry-Run Inspection (`--dry-run`):**  
   Pre-scanned files and SQLite database without disk mutation. Verified 4 files and 48 facts.
2. **Idempotent Quarantine (`--quarantine`):**  
   - Moved all 4 contaminated JSON files to `data/quarantine/financials/{SYMBOL}/`.
   - Updated all 48 database rows in `financial_facts.db` to:
     - `validation_status = 'QUARANTINED_SYNTHETIC'`
     - Added JSON lineage: `{"quarantined_at": "...", "quarantine_reason": "SYNTHETIC_SEED_DATA"}`.
   - Wrote comprehensive audit manifest: `data/quarantine_manifest.json`.
3. **Rollback & Restore Verification (`--rollback`):**  
   Executed complete rollback from backup, verified restoration of files and database states, then re-executed quarantine cleanly to establish idempotency.
4. **Verification Gate (`--verify`):**  
   Confirmed 0 active unquarantined rows for BBCA and RATU in SQLite and 0 synthetic JSON files in active directories.

---

## 4. Codebase Hardening & Defenses

To permanently prevent synthetic records from re-entering active analytical or conversational paths, three core modules were patched:

1. **`openbagus/domains/equities/storage.py`:**
   - In `store_statement()`: Inspects `source`. Rejects any statement containing `idx.co.id/filings` or marked `synthetic` with `ValueError`.
   - In `get_statement()`: Rejects files with synthetic URLs or `validation_status == 'QUARANTINED_SYNTHETIC'`.
   - In `list_periods()`: Excludes quarantined/synthetic statement files from period enumeration.
2. **`openbagus/domains/equities/facts_db.py`:**
   - In `store_fact()`: Raises `ValueError` if `source_url` matches `idx.co.id/filings` or contains `synthetic`.
   - In `get_fact()`, `get_facts_for_period()`, `get_metric_history()`, `list_available_periods()`: Excludes rows where `validation_status != 'VALID'`.
3. **`openbagus/ai/tools/finance_tools.py`:**
   - In `CalculateFinancialRatiosTool`: Prohibits treating missing debt as `0.0`. When debt keys are omitted from filings, `der` is set to `None`, `debt_verified` to `False`, and `accounting_health` to `"Debt Unverified"`.

---

## 5. Legitimate Data Preservation

Authentic SEC EDGAR corporate filings for Apple Inc. (`AAPL` / CIK `0000320193`) were fully audited:
- 69 multi-period statement files (`data/equities/financials/AAPL/2009-FY.json` through `2026-Q3.json`)
- 950 atomic facts in `data/equities/financial_facts.db`
- Provenance: Genuinely fetched from `data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json`
- Status: Preserved untouched as valid, authentic financial facts.
