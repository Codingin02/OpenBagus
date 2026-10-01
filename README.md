# OpenBagus

A modular quantitative research and market-intelligence platform with a CLI-first workflow.

| Capability | Status |
| --- | --- |
| CLI | Active |
| Crypto research | Active: BTC/USD, ETH/USD, SOL/USD |
| Public market data | Active |
| External API keys | Optional and provider-dependent |
| Email | Optional |
| Daily email scheduling | Optional and disabled by default |
| Equities | Disabled |
| WhatsApp / OpenClaw | Disabled |
| Live trading | Not implemented |

OpenBagus is research-only. Python owns all numerical analysis and risk outputs; optional language-model components may summarize or critique but do not set quantitative decisions.

## Quick Start

Requirements: Python 3.11 or newer.

```powershell
git clone https://github.com/Codingin02/openbagus.git
cd openbagus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
openbagus doctor
openbagus
```

On Linux or macOS, activate with `source .venv/bin/activate`. The package has no required third-party runtime dependencies. Optional DuckDB storage is available with `python -m pip install -e ".[storage]"`.

The module entry point always remains available:

```powershell
python -m openbagus doctor
python -m openbagus
```

## CLI

Run the interactive shell with `openbagus`. Scriptable commands use the same implementation:

```powershell
openbagus status
openbagus doctor
openbagus crypto-daily
openbagus manual-desk --query "OpenBagus review BTC ETH"
openbagus email --email-action draft
openbagus email --email-action check
```

The manual research trigger is exactly `OpenBagus`; `Open Bagus` is rejected. See [CLI reference](docs/cli.md).

## Configuration

Public Binance, CoinGecko, Yahoo Finance, and DefiLlama paths require no API key. `FRED_API_KEY` optionally enables official FRED macro series.

Copy the safe example to an ignored local file:

```powershell
Copy-Item config/openbagus_runtime_local.env.example config/openbagus_runtime_local.env
openbagus doctor
openbagus config
```

Never commit the local file or credentials. See [configuration](docs/configuration.md).

## Optional Email

Email is not required for crypto research or CLI startup. Draft and local MIME generation are the default; live SMTP requires complete configuration, local enablement, an explicit send action, and the exact confirmation phrase.

```powershell
openbagus email --email-action draft
openbagus email --email-action check
```

See [email operations](docs/email.md).

## Architecture

```text
openbagus/
├── openbagus/          Core package and canonical CLI
├── config/             Tracked examples and public-source policy
├── scripts/            Compatibility and operational entrypoints
├── tests/              Supported-surface tests
└── docs/               User and operator documentation
```

The active flow is:

```text
public providers -> ingestion -> freshness -> analysis -> risk
                 -> intelligence -> reports -> storage -> optional email
```

See [architecture](docs/architecture.md).

## Safety

OpenBagus does not execute broker orders, exchange orders, wallet transactions, or fund transfers. Missing and stale inputs remain explicit as data gaps; they are never replaced with fabricated market values. Default delivery is `NO_SEND_FILE_ONLY`.

## Documentation

- [CLI reference](docs/cli.md)
- [Configuration](docs/configuration.md)
- [Email operations](docs/email.md)
- [Architecture](docs/architecture.md)
- [Historical migration note](docs/migration/agent_sahamcrypto_to_openbagus.md)

## Author

Ahmad Bagus Idkholus Surur
