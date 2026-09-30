# OpenBagus

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-OpenBagus-teal.svg)](#)
[![Status](https://img.shields.io/badge/status-active--research-emerald.svg)](#)
[![Active Domain](https://img.shields.io/badge/active_domain-crypto-orange.svg)](#)
[![Delivery Mode](https://img.shields.io/badge/delivery-NO__SEND__FILE__ONLY-yellow.svg)](#)

**OpenBagus** is a modular, domain-neutral quantitative intelligence and market research platform. Designed for long-term multi-asset extensibility, OpenBagus separates core analytical engines, risk modeling, and data pipelines from specific market domains.

In this primary phase, the **active domain is exclusively Crypto** (BTC, ETH, SOL) alongside shared cross-asset macro indicators. All equity and stock-specific pipelines are deactivated.

---

## 1. Architectural Philosophy

OpenBagus operates under strict institutional design boundaries:

```mermaid
graph TD
    Data[Data Layer: Public Market & Macro Ingestion] --> Core[Core Engine: Market Structure, VWAP, Profiles]
    Core --> Domain[Active Domain: Crypto Microstructure & Liquidity]
    Core --> Macro[Shared Macro: DXY, VIX, US10Y, DefiLlama]
    Domain --> Risk[Risk Engine: Sharpe, Sortino, VaR/CVaR, Drawdown]
    Macro --> Risk
    Risk --> Quant[Python Quant Decision Core: Stance, Conviction, Invalidation]
    Quant --> Guard[Safety & Compliance Guard]
    Guard --> Reporting[Reporting & PWA Dashboard]
    Guard --> Delivery[Local Outbox Delivery: NO_SEND_FILE_ONLY]
    LLM[Optional LLM Critic / Summarizer] -. Advisory Only .-> Reporting
```

1. **Umbrella Platform:** `OpenBagus` is not locked into any single asset class. Future domains (equities, commodities, forex, rates) can plug into the existing architecture without refactoring the core.
2. **Python Quant Core:** Numerical decisions, market regimes, conviction scores, invalidation levels, and portfolio stances are strictly computed in Python. LLMs **never** act as the numerical decision core.
3. **OpenClaw & Orchestration:** OpenClaw functions strictly as an orchestrator, scheduler, and interface gateway.
4. **Safety & Zero-Execution:** The platform executes **zero** live exchange or broker orders. Default communication mode is `NO_SEND_FILE_ONLY` (all reports are staged to local files).
5. **Exact Manual Trigger:** Interactive requests must use the exact trigger `OpenBagus`. Spaced variants (`Open Bagus`) or aliases are strictly rejected.

---

## 2. Directory Structure

```
OpenBagus/
├── config/                 # Domain-neutral runtime and source quality configurations
├── openbagus/              # Main modular Python package
│   ├── core/               # Generic contracts, guards, VWAP, Volume Profile, market structure
│   ├── domains/
│   │   └── crypto/         # Active crypto microstructure, order flow, liquidity metrics
│   ├── intelligence/
│   │   ├── macro/          # Shared macro scenarios (DXY, VIX, US10Y, commodities)
│   │   ├── news/           # Narrative tracking, dedup ranker, memory
│   │   ├── sentiment/      # Cross-asset sentiment scoring
│   │   └── llm/            # Advisory LLM router and critic prompts
│   ├── risk/               # Sharpe, Sortino, VaR, CVaR, Monte Carlo, Max Drawdown
│   ├── data/               # Public ingestion engine (Binance, CoinGecko, Yahoo, DefiLlama, DuckDB)
│   ├── analysis/           # Quantitative research decision core & quality agent
│   ├── reporting/          # Briefs, Gmail HTML reports, printable views, PWA dashboard
│   ├── delivery/           # Safety guards, local outbox staging, channel trackers
│   ├── storage/            # Historical CSV/JSON logging & spreadsheet exporters
│   └── runtime/            # Pipeline orchestrator and scheduler governance
├── openbagus_finance/      # Backward-compatibility shims for legacy callers
├── scripts/                # Execution entrypoints, validators, and dashboard server
├── docs/                   # Architectural blueprints and migration records
├── reports/runtime/        # Generated runtime reports, outbox staging, and web dashboard
└── tests/                  # Unit and integration test suite
```

---

## 3. Quickstart & Installation

### Requirements
- Python 3.11, 3.12, 3.13, or 3.14
- Standard scientific Python packages (`numpy`, `pandas`, `scipy`)

### Setup
```bash
# Clone the repository
git clone https://github.com/Codingin02/openbagus.git
cd openbagus

# Install dependencies
pip install -r requirements.txt
```

---

## 4. Running the Platform

### A. Run Runtime Validation Suite
Verifies static compilation, import graph integrity, domain neutrality, and secret scanning:
```bash
python scripts/validate_openbagus_runtime.py
```

### B. Run End-to-End Crypto Research Pipeline
Executes public data ingestion, quantitative analysis, local history persistence, and outbox staging:
```bash
python scripts/openbagus_run_final.py --mode crypto-daily
```

### C. Build and Serve the Interactive PWA Dashboard
Compile static dashboard assets and launch local server:
```bash
# Compile latest dashboard assets
python scripts/build_openbagus_static_app.py

# Launch local server (PowerShell)
powershell -File scripts/openbagus_serve_dashboard.ps1
# Open http://localhost:8080 in your browser
```

### D. Manual Research Query
Execute a manual query using the mandatory `OpenBagus` trigger:
```bash
python scripts/openbagus_run_final.py --mode manual-desk --query "OpenBagus review BTC and ETH"
```

---

## 5. Domain Status Matrix

| Domain | Status | Active Assets / Indicators | Notes |
| :--- | :--- | :--- | :--- |
| **Crypto** | **ACTIVE** | BTC, ETH, SOL | Full microstructure, order flow proxy, conviction scoring |
| **Shared Macro** | **ACTIVE (Context)** | DXY, VIX, US10Y, Gold, Oil, DefiLlama MCap | Contextual inputs for crypto regime evaluation |
| **Equities** | **DISABLED** | None | Deactivated for this phase. No active tickers or alerts |
| **Forex / Rates** | Planned | Future expansion | Extensible via `openbagus/domains/` |
| **Commodities** | Planned | Future expansion | Extensible via `openbagus/domains/` |

---

## 6. Safety & Disclaimers

> **RESEARCH ONLY:** OpenBagus is an automated quantitative intelligence engine. It does not provide financial advice, place trades, custody assets, or execute transactions. All outbound reports are staged to local disk (`NO_SEND_FILE_ONLY`) unless configured otherwise by an authenticated operator.

---
&copy; 2026 OpenBagus Platform. Developed by Ahmad Bagus Idkholus Surur.
