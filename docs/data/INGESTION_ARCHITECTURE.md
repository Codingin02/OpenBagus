# OPENBAGUS — DATA INGESTION & FRESHNESS ARCHITECTURE

## 1. Overview
The OpenBagus Data Ingestion Architecture provides an automated, zero-gap pipeline connecting conversational tools directly to live market feeds, local SQLite databases, and structured JSON stores.

---

## 2. Ingestion Flow & On-Demand Fetch

```
               User Query / Agent Tool Call
                            │
                            ▼
              GetMarketPrice / GetOHLCV / etc.
                            │
                            ▼
               EquityData.load(symbol, auto_fetch=True)
                            │
               ┌────────────┴────────────┐
               │ Cached & Fresh?         │
               ▼                         ▼
             [YES]                     [NO]
        Return Local Data        Invoke fetch_live_data()
                                         │
                                         ▼
                               Query Upstream Provider
                                         │
                                         ▼
                               Validate & Format Bars
                                         │
                                         ▼
                               Save to Local JSON & SQLite L2
```

---

## 3. Tiered Freshness Policies

| Freshness Tier | Scope / Asset Class | Maximum Age (TTL) | Action Upon Expiry |
| :--- | :--- | :--- | :--- |
| **Tier 1: Spot Crypto** | BTC, ETH, SOL, altcoins | 15 – 30 seconds | Fetch live spot ticker via ZeroKey engine |
| **Tier 2: Intraday Quotes** | IDX equities during market hours | 5 – 15 minutes | Query Yahoo Finance delayed quote |
| **Tier 3: EOD Daily OHLCV** | IDX & US equities daily candles | 24 hours | On-demand auto-fetch of latest closed session |
| **Tier 4: Macro Indicators** | CPI, GDP, Trade balance | 7 – 30 days | Query World Bank Open Data annual series |
| **Tier 5: Corporate Filings** | Financial statements, SEC 10-K/10-Q | 30 – 90 days | Ingest official XBRL facts / IDX disclosures |

---

## 4. Rate-Limit Governance & Backoff

1. **Sliding Window Accounting:** Tracks request timestamps over a 60-second window per provider.
2. **Exponential Backoff with Jitter:** When HTTP 429 or 503 is returned, the provider enters a cooldown state for `base_delay + random_jitter` seconds.
3. **Graceful Degradation:** During cooldown, the system returns cached data marked with `FreshnessStatus.STALE` or `QualityStatus.OFFICIAL_REPORTED` rather than throwing fatal exceptions.
