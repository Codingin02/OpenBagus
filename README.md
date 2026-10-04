# OpenBagus

OpenBagus is a CLI-first quantitative crypto research terminal and market-intelligence platform designed for modular, research-only market analysis.

Current active domain: **Crypto**.

| Capability | Status |
| --- | --- |
| Terminal UX | Active: Prompt-first interactive coin terminal & slash commands |
| Crypto Research | Active: Dynamic universe (Layer 1, Layer 2, DeFi, Memecoin, AI, RWA, etc.) |
| Public Market Data | Active: Multi-tier fallback (Binance Vision -> Binance Public -> CoinGecko -> Yahoo Finance) |
| Provider Architecture | Active: 23 declared providers, 4 zero-key public sources (Coverage Target: 12) |
| Intent Routing | Active: Sub-millisecond deterministic intent parser + optional local GGUF |
| FRED | Optional (Federal Reserve Economic Data macro indicators) |
| Email Delivery | Optional (Local staging default; SMTP delivery requires explicit confirmation) |
| Equities | Disabled |
| WhatsApp / OpenClaw | Disabled |
| Live Trading | Not implemented (Strictly quantitative research only) |

OpenBagus is research-only. Python owns all numerical analysis, pivot levels, and risk calculations; language-model components never calculate financial math or execute trades.

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

Once inside the `openbagus` interactive shell, query any coin directly:

- `ETH` or `SOL`: Comprehensive market snapshot, levels, pivots, and provider evidence.
- `open position ARB`: Trade-setup research view (directional bias, candidate zone, invalidation level).
- `risk DOGE`: Volatility regime, drawdown, distance to invalidation, and liquidity proxy.
- `support resistance AVAX`: Floor Trader Pivots (P, R1/R2, S1/S2) and structural reaction zones.
- `BTC vs ETH`: Side-by-side comparative quantitative snapshot.

### Management & Slash Commands

Inside the shell or directly from the CLI:

- `/status` or `openbagus status`: Runtime status, active domains, provider counts, and target.
- `/providers` or `openbagus providers`: View public providers and configured API coverage.
- `/providers --check`: Run live reachability and latency ping tests across public sources.
- `/assets [query]` or `openbagus assets [query]`: Search assets or filter by sector (`/assets defi`).
- `/categories` or `openbagus categories`: List taxonomy groups and coin counts.
- `/doctor [network]` or `openbagus doctor [--network]`: Environment diagnostics & live reachability.
- `/setup` or `openbagus setup`: Interactive wizard to configure provider API keys, email, or local AI.
- `/crypto` or `openbagus crypto-daily`: Core crypto pipeline (BTC/USD, ETH/USD, SOL/USD).
- `/email draft`: Generate local delivery draft (no send).

### Key Architectural Notes

- **Zero-Key Public Mode**: Works out of the box without any private API keys using public Binance, CoinGecko, Yahoo Finance proxy, and DefiLlama.
- **Provider Resilience**: Network timeouts on any single source trigger instantaneous sub-5s fallback to alternative providers, guaranteeing uninterrupted terminal sessions.
- **Coverage Target**: Tracks configured coverage toward `ENHANCED_PROVIDER_TARGET = 12` across 23 enterprise and macro providers.
- **Research Only**: "Open position" queries strictly produce research hypotheses with structural invalidations; OpenBagus has no live broker, wallet, or trading connectivity.

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

## Architecture

```text
openbagus/
├── openbagus/          Python package and canonical CLI
├── config/             Safe configuration templates
├── docs/               Documentation
├── scripts/            Operational tooling and setup scripts
├── tests/              Supported-surface tests
├── pyproject.toml      Packaging configuration
├── setup.bat           Windows one-click setup
└── README.md
```

The active pipeline flow is:

```text
public providers -> ingestion -> freshness -> analysis -> risk
                 -> intelligence -> reports -> storage -> optional email
```

See [architecture](docs/architecture.md).

## Safety

OpenBagus does not execute broker orders, exchange orders, wallet transactions, or fund transfers. Missing and stale inputs remain explicit as data gaps; they are never replaced with fabricated market values. Default delivery is `NO_SEND_FILE_ONLY`.

## Documentation

- [CLI Reference](docs/cli.md)
- [Configuration](docs/configuration.md)
- [Email Operations](docs/email.md)
- [Architecture](docs/architecture.md)

## Author

Ahmad Bagus Idkholus Surur
