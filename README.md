# OpenBagus

OpenBagus is a CLI-first quantitative crypto research terminal and market-intelligence platform designed for modular, research-only market analysis.

Current active domain: **Crypto**.

| Capability | Status |
| --- | --- |
| Terminal UX | Active: Prompt-first interactive coin terminal & slash commands |
| Data Core | **ZERO-KEY CORE**: No API keys required for full crypto research |
| Crypto Research | Active: Dynamic universe (Layer 1, Layer 2, DeFi, Memecoin, AI, RWA, DEX tokens) |
| Public Market Data | Active: Binance Vision, Gate.io, Bybit, OKX, CoinGecko, GeckoTerminal, DefiLlama, Alternative.me, CoinLore |
| Decision Engine | Active: Local Python Quant Engine V2 (5 independent evidence families, strict RR >= 1.5 gate) |
| Intent Routing | Active: Deterministic bilingual (ID/EN) typo-tolerant intent parser |
| Optional APIs | Optional: FRED, CoinMarketCap, CryptoCompare, Coinalyze, Alpha Vantage (enhancements only) |
| Email Delivery | Optional (Local staging default; SMTP delivery requires explicit confirmation) |
| Equities | Disabled |
| WhatsApp / OpenClaw | Disabled by default |
| Live Trading | Not implemented (Strictly quantitative decision-support research only) |

OpenBagus is research-only. Python owns all numerical analysis, decision rules, structural levels, and risk calculations; no cloud LLMs or local neural weights calculate financial math or execute trades.

---

## Zero-Key Core

**No API key is required for standard crypto research.**

OpenBagus runs out of the box with zero configuration:
- **Centralized Spot**: Binance Vision, Gate.io, Bybit, OKX, KuCoin, Kraken, CoinGecko, CoinLore.
- **Derivatives & Perps**: Gate.io Futures, OKX, Bybit, KuCoin, CoinGecko Derivatives (mark price, funding rate, z-score, OI, basis, spread).
- **DEX & On-Chain Pools**: GeckoTerminal (search DEX pairs, price USD, reserves, 24h volume).
- **Sentiment & Macro**: Alternative.me Fear & Greed, DefiLlama stablecoin market cap.

Optional private API keys are **enhancements only** and improve:
- Specialized proprietary data
- Granular on-chain metrics (Bitquery, The Graph)
- Macroeconomic series (FRED, Alpha Vantage)
- Additional data redundancy

Do not advertise or treat optional credentials as requirements.

---

## Quant Engine V2

OpenBagus upgrades technical analysis into a deterministic multi-evidence decision engine:

1. **5 Independent Evidence Families**:
   - **A. Trend / Momentum**: Multi-timeframe returns (1h, 4h), EMA 8/21 alignment, and intraday range location.
   - **B. Volatility / Regime**: ATR, realized volatility, and deterministic regime classification (`TRENDING`, `CHOPPY`, `VOLATILE`, `COMPRESSED`).
   - **C. Price-Volume / Liquidity**: 24h volume confirmation, turnover tiers, and order book bid/ask depth imbalance.
   - **D. Derivatives / Basis / Positioning**: Funding rate, funding z-score, open interest, basis, and non-naive crowded-long logic (extreme funding $>0.04\%$ penalizes longs).
   - **E. Context / On-Chain / Sentiment**: Alternative.me Fear & Greed sentiment and DefiLlama stablecoin TVL.
2. **Strict Risk:Reward Gate (`minimum_reward_risk = 1.5`)**:
   - Directional trades (`BUY`, `LONG`, `SHORT`) are **never** issued if the nearest realistic target offers $RR < 1.5$.
   - Poor asymmetry automatically returns `WAIT` (spot) or `NO_TRADE` (perpetual) and calculates the ideal pullback limit price.
3. **Data Quality Gate**:
   - Requires at least 3 independent active evidence families and composite quality $\ge 0.45$.
4. **Conservative Leverage Policy**:
   - Hard maximum ceiling $\le 3x$ for general users.
   - Reduced automatically in `VOLATILE`, low-liquidity, or low-confidence conditions.
5. **Categorical Confidence**:
   - Emits calibrated qualitative confidence categories: `LOW`, `MODERATE`, `HIGH` (no fake percentage precision like 68%).
6. **Concise Terminal Output**:
   - Clean, human-readable terminal output without AI disclaimers or repetitive prose.

---

## Quick Start

### Windows (One Click)

1. Clone or download the repository.
2. Double-click `setup.bat`.
3. Follow the setup prompts.
4. The OpenBagus research terminal launches automatically.

### Manual Installation (Windows, Linux, macOS)

Requirements: Python 3.11 or newer.

```powershell
git clone https://github.com/Codingin02/openbagus.git
cd openbagus
python -m venv .venv

# Windows:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

python -m pip install -e .
openbagus doctor
openbagus
```

### Prompt-First Research Terminal

Once inside the `openbagus` interactive shell, query any coin directly in Indonesian or English:

- `BTC`: Concise perpetual/spot quantitative decision snapshot.
- `BUY btc?`: Spot decision support (`BUY` | `WAIT` | `REDUCE`) with entry zone and structural stop.
- `bagusnya BTC long atau short?`: Perpetual decision support (`LONG` | `SHORT` | `NO_TRADE`) with conservative leverage ceiling.
- `ETH entry dimana?`: Pullback limit required for $RR \ge 1.5$ gate.
- `Manta`: Dynamic online asset discovery and derivatives funding evaluation.
- `AERO` or `PEPE`: DEX pool and on-chain liquidity discovery.
- `margin BTC equity 1000 risk 2%`: Capital risk budgeting and margin position sizing calculator.
- `risk DOGE`: Volatility regime, drawdown, distance to invalidation, and liquidity proxy.
- `BTC vs ETH`: Side-by-side comparative quantitative snapshot.

### Management & Slash Commands

Inside the shell or directly from the CLI:

- `/status` or `openbagus status`: Runtime status, active domains, capability groups, and active keys.
- `/providers` or `openbagus providers`: View providers grouped into `ZERO-KEY CORE` and `OPTIONAL KEYED`.
- `/providers --check`: Run live reachability and credential checks across all providers.
- `/assets [query]` or `openbagus assets [query]`: Search assets or filter by sector (`/assets defi`).
- `/categories` or `openbagus categories`: List taxonomy groups and coin counts.
- `/doctor [network]` or `openbagus doctor [--network]`: Environment diagnostics & live reachability.
- `/setup` or `openbagus setup`: Interactive wizard to configure optional provider API keys and email.
- `/crypto` or `openbagus crypto-daily`: Core crypto pipeline (BTC/USD, ETH/USD, SOL/USD).
- `/email draft`: Generate local delivery draft (no send).

---

## Configuration

Settings are stored in the local `.env` file (ignored by Git, never committed).

Use the built-in wizard:

```powershell
openbagus setup
```

Or copy the safe template manually:

```powershell
Copy-Item .env.example .env
openbagus doctor
openbagus config
```

See [configuration guide](docs/configuration.md) and [email operations](docs/email.md).

---

## Safety

OpenBagus does not execute broker orders, exchange orders, wallet transactions, or fund transfers. Missing and stale inputs remain explicit as data gaps; they are never replaced with fabricated market values. Default delivery is `NO_SEND_FILE_ONLY`.

---

## Documentation

- [CLI Reference](docs/cli.md)
- [Configuration](docs/configuration.md)
- [Email Operations](docs/email.md)
- [Architecture](docs/architecture.md)

---

## Author

Ahmad Bagus Idkholus Surur
