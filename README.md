# OpenBagus

OpenBagus is a CLI-first quantitative research and market-intelligence platform designed for modular, research-only market analysis.

Current active domain: Crypto.

| Capability | Status |
| --- | --- |
| CLI | Active |
| Crypto research | Active: BTC/USD, ETH/USD, SOL/USD |
| Public market data | Active |
| FRED | Optional |
| Email | Optional |
| Daily email scheduling | Optional and disabled by default |
| Equities | Disabled |
| WhatsApp / OpenClaw | Disabled |
| Live trading | Not implemented |

OpenBagus is research-only. Python owns all numerical analysis and risk outputs; optional language-model components may summarize or critique but do not set quantitative decisions.

## Quick Start

### Windows (One Click)

1. Clone or download the repository.
2. Double-click `setup.bat`.
3. Follow the setup prompts.
4. The OpenBagus CLI starts automatically.

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

### Core Commands

- `openbagus`: Launch the interactive CLI shell.
- `openbagus doctor`: Run environment, provider, and runtime diagnostics.
- `openbagus setup`: Interactive wizard to configure optional local API and email settings.
- `openbagus config`: View redacted configuration and provider status without revealing secrets.
- `openbagus crypto-daily`: Run daily crypto pipeline (BTC/USD, ETH/USD, SOL/USD).
- `openbagus manual-desk --query "OpenBagus review BTC ETH"`: Ad-hoc quantitative review.
- `openbagus email --email-action draft`: Generate local delivery draft (no send).
- `openbagus email --email-action check`: Validate email configuration format (no send).

### Key Notes

- **Public Data**: Basic market intelligence works immediately without any private API keys (Binance, CoinGecko, Yahoo Finance proxy, DefiLlama).
- **FRED**: Optional Federal Reserve Economic Data series can be configured via `openbagus setup` or `FRED_API_KEY` in `.env`.
- **Email**: Optional SMTP delivery. Stays disabled by default; reports are generated locally on disk without error.
- **Equities**: Disabled (active domain is crypto).
- **WhatsApp / OpenClaw**: Disabled.
- **Safety**: Research-only. OpenBagus does not execute trades, broker orders, exchange orders, or fund transfers.

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
