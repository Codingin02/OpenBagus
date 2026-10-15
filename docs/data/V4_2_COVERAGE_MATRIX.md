# OPENBAGUS V4.2 — COVERAGE MATRIX & DATASET REGISTRY

**Audit Date:** 15 Oktober 2026  
**Auditor:** Antigravity  
**Worktree:** `E:\Projects\OpenBagus-Data`  
**Branch:** `feat/openbagus-automated-data-intelligence`

---

## 1. Comprehensive Asset Coverage Matrix

| Asset Class | Ticker / Identifier | Entity Name | Fundamental Filing Status | Price / EOD Data Status | Canonical Storage Location | Source Provider & Attribution |
|---|---|---|---|---|---|---|
| **IDX Large-Cap** | `TLKM` | PT Telkom Indonesia Tbk. | **ACTIVE (2025-FY, 2026-Q1)** | **ACTIVE (400+ Candles)** | `data/equities/financials/TLKM/` | Telkom IR MinIO Official Storage |
| **IDX Large-Cap** | `BBCA` | PT Bank Central Asia Tbk. | **ACTIVE (2025-FY, 2026-Q1)** | **ACTIVE (400+ Candles)** | `data/equities/financials/BBCA/` | BCA Official Investor Relations |
| **IDX Mid-Cap** | `RATU` | PT Raharja Energi Cepu Tbk. | **DATA_GAP (Truthfully Preserved)** | **ACTIVE (400 Candles)** | `data/equities/candles/` | Yahoo Finance / ZeroKey EOD |
| **IDX Small-Cap** | `DATA` | PT Remala Abadi Tbk. | **UNINDEXED** | **CATALOG RESOLVED** | `openbagus/domains/equities/idx_universe.json` | IDX Listing Directory |
| **US Equity** | `AAPL` | Apple Inc. | **ACTIVE (10+ Periods)** | **ACTIVE (Daily Adjusted)** | `data/equities/financials/AAPL/` | SEC EDGAR Company Facts API (CIK 320193) |
| **Crypto Spot** | `BTC-USDT` | Bitcoin | N/A *(Decentralized Protocol)* | **ACTIVE (Real-time Spot)** | In-Memory Memory Cache | Binance Vision / Gate.io Zero-Key |
| **Crypto Spot** | `ETH-USDT` | Ethereum | N/A *(Decentralized Protocol)* | **ACTIVE (Real-time Spot)** | In-Memory Memory Cache | Binance Vision / Gate.io Zero-Key |
| **Macro** | `IDN_CPI` | Indonesia Consumer Price Index | N/A *(Macro Series)* | **ACTIVE (Annual Time Series)** | In-Memory / World Bank Cache | World Bank Open Data API (`FP.CPI.TOTL`) |

---

## 2. Fundamental Statement Storage Audit

| Symbol | Period | Format | Validation Status | Balance Sheet Assets (IDR) | Total Liabilities (IDR) | Equity (IDR) | Invariant Reconciliation |
|---|---|---|---|---|---|---|---|
| **TLKM** | `2026-Q1` | PDF | `VALIDATED` | 289.955 Miliar | 134.145 Miliar | 155.810 Miliar | $134.145 + 155.810 = 289.955$ ($\Delta = 0$) |
| **TLKM** | `2025-FY` | PDF | `VALIDATED` | 287.759 Miliar | 137.222 Miliar | 150.537 Miliar | $137.222 + 150.537 = 287.759$ ($\Delta = 0$) |
| **BBCA** | `2026-Q1` | PDF | `VALIDATED` | 1.640.830.566 Juta | 1.370.360.247 Juta | 259.358.793 Juta | $1.370.360.247 + 11.111.526\text{ (Syirkah)} + 259.358.793 = 1.640.830.566$ ($\Delta = 0$) |
| **BBCA** | `2025-FY` | PDF | `VALIDATED` | 1.586.828.536 Juta | 1.294.508.286 Juta | 281.687.555 Juta | $1.294.508.286 + 10.632.695\text{ (Syirkah)} + 281.687.555 = 1.586.828.536$ ($\Delta = 0$) |
| **RATU** | `2023-FY` | JSON | `QUARANTINED` | *Quarantined in `data/quarantine/`* | *Quarantined* | *Quarantined* | Excluded from active queries |
| **RATU** | `2024-FY` | JSON | `QUARANTINED` | *Quarantined in `data/quarantine/`* | *Quarantined* | *Quarantined* | Excluded from active queries |

---

## 3. SQLite Canonical Database (`financial_facts.db`) Statistics

- **Total Active Authentic Facts:** 966 atomic facts
  - AAPL (SEC EDGAR): 950 facts
  - TLKM (Telkom IR): 8 facts (`revenue`, `operating_income`, `net_income`, `net_income_attributable`, `total_assets`, `total_liabilities`, `interest_bearing_debt`, `equity`)
  - BBCA (BCA IR): 8 facts (`revenue`, `operating_income`, `net_income`, `total_assets`, `total_liabilities`, `syirkah_funds`, `equity`, etc.)
- **Total Quarantined Facts:** 48 facts (`QUARANTINED_SYNTHETIC`)
- **Query Verification:** `SELECT count(*), validation_status FROM financial_facts GROUP BY validation_status`
  - `VALID`: 950
  - `VALIDATED`: 16
  - `QUARANTINED_SYNTHETIC`: 48

---

## 4. Model Provider & Cost Guardrails

- **Local Default:** `LLAMA_CPP_CUDA` running on NVIDIA RTX 3050. Cost: **$0.00**.
- **Deterministic Fallback:** `DeterministicFallbackProvider`. Cost: **$0.00**.
- **Cloud Router Default Cap:** **$0.00 / month**. Cloud calls require explicit user opt-in (`/model set gemini` or `/model set openai`).
