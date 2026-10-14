# OPENBAGUS — DATA PROVIDER INVENTORY & CAPABILITY MATRIX

## 1. Executive Summary
This document provides the authoritative inventory of all integrated data providers and AI providers in OpenBagus. It details authentication mechanisms, public vs. authenticated access, rate limit governance, supported datasets, endpoint protocols, and fallback behaviors.

---

## 2. Integrated Data Providers

| Provider Identifier | Display Name | Domain | Authentication | Datasets Supported | Rate Limit / Throttling | Licensing & Attribution |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `yahoo_finance_id` | **Yahoo Finance (IDX & US Market)** | Equities, Indices, FX | **Zero-Key** (Public HTTP) | Daily OHLCV, Quotes, Corporate Splits | 30 req/min with exponential backoff on 429 | Public Documented API |
| `sec_edgar` | **SEC EDGAR Corporate Filings** | US Equities & Foreign Issuers | **Zero-Key** (Declared User-Agent header) | 10-K, 10-Q, 8-K, XBRL Company Facts, Submissions | Strictly <= 10 req/sec per SEC policy | Official US Federal Regulatory Public Domain |
| `binance_vision` | **Binance Vision & Zero-Key Cross Venue** | Cryptocurrencies | **Zero-Key** (Public REST) | Spot Tickers, 24h Stats, Order Book Depth, Klines | 60 req/min with Gate.io & Bybit failover | Public Market Data |
| `worldbank_macro` | **World Bank Open Data** | Macroeconomics | **Zero-Key** (Open Data REST API) | Indonesia CPI, GDP, Trade Balance, Annual Indicators | Unrestricted public API (30 req/min internal limit) | Official World Bank Open Data (CC-BY 4.0) |
| `idx_official` | **IDX Official Disclosures & Listing** | Indonesian Equities | **Zero-Key** + Local Catalog | 951+ Verified Issuers, Material Disclosures, Board Classification | Assisted Intake / Local Cache | Official Indonesia Stock Exchange |

---

## 3. Optional AI Model Providers

| Provider Identifier | Model Default | Auth Protocol | Verification Levels | Default Budget | Privacy Guarantee |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `OPENAI` | `gpt-4o-mini` | `Bearer sk-...` | **Level 1**: `GET /v1/models`<br>**Level 2**: `POST /v1/chat/completions` (1 token) | **$0.00 / month** (strictly local-first) | Zero data storage (`store: False`), unredacted keys never logged |
| `GEMINI` | `gemini-2.5-flash` | `x-goog-api-key` header | **Level 1**: `GET /v1beta/models`<br>**Level 2**: `POST /v1beta/models/{m}:generateContent` | **$0.00 / month** (strictly local-first) | No training on API traffic, unredacted keys never logged |
| `LOCAL_LLAMA` | `qwen3.5:2b` / `qwen3.5:4b` | None (Local CUDA loopback) | Hardware telemetry & warm status | **$0.00** (Local compute) | 100% offline, ephemeral RAM only |

---

## 4. Zero-Key Architecture & Failover Chains

```
[Equities Query]
       │
       ▼
   Yahoo Finance (RATU.JK, BBCA.JK, DATA.JK)
       │
       ├─ [Success] ──► Cache to SQLite L2 & data/equities/{ticker}.json
       │
       └─ [Fail/429] ─► Exponential Backoff Jitter + Offline Local EOD Cache

[Crypto Query]
       │
       ▼
   Binance Vision Spot API
       │
       ├─ [Success] ──► Median Consensus with Gate.io + Bybit (Spread check)
       │
       └─ [Fail/429] ─► Gate.io Public API Fallback

[Macro Query]
       │
       ▼
   World Bank Open Data API (Indonesia IDN)
       │
       ├─ [Success] ──► Ingest annual series (CPI, GDP, Trade)
       │
       └─ [Fail] ─────► BPS Web API / Offline Macro Cache
```
